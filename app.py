import json
import math
import traceback

import numpy as np
import pandas as pd
import requests
from flask import Flask, jsonify, render_template, request
from flask.json.provider import DefaultJSONProvider

import os

# Load .env for local development
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from data_loader import (
    _KEBOOLA_STORAGE_TOKEN,
    _KEBOOLA_STORAGE_URL,
    _KEBOOLA_LOCAL_PATHS,
    get_all_hr_drift,
    get_zone_summary,
    load_activities,
    load_activity_details,
    load_garmin_hr_daily,
    load_garmin_hr_intraday,
    warm_all_caches,
)
from metrics import (
    compute_acwr,
    compute_aerobic_efficiency,
    compute_atl_ctl_tsb,
    compute_cadence_trend,
    compute_decoupling_factor,
    compute_gear_mileage,
    compute_hr_recovery,
    compute_hr_zones,
    compute_long_run_flags,
    compute_morning_readiness,
    compute_race_predictor,
    compute_split_stats,
    compute_streak,
    compute_training_monotony,
    compute_weekly_ramp_rate,
    default_max_hr,
    make_daily_trimp,
)

def _sanitize(obj):
    """Recursively replace NaN/Inf floats with None so JSON stays valid."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, np.floating) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


class _SafeJSONProvider(DefaultJSONProvider):
    def dumps(self, obj, **kwargs):
        return json.dumps(_sanitize(obj), **kwargs)


app = Flask(__name__)
app.json_provider_class = _SafeJSONProvider
app.json = _SafeJSONProvider(app)

# Pre-warm all Keboola data caches in parallel so that the first real request
# is served from memory rather than blocking on sequential table exports.
if _KEBOOLA_STORAGE_TOKEN:
    try:
        warm_all_caches()
    except Exception as _warm_err:
        print(f"[startup] Cache pre-warm failed: {_warm_err}")


RESTING_HR = 45.0
MAX_HR = 179.0  # Karvonen: 220 - age (born 1985, age 41)

def _parse_params():
    acts_all = load_activities()
    max_hr = MAX_HR
    resting_hr = RESTING_HR
    zone_model = request.args.get("zone_model", "5zone")
    races_only = request.args.get("races_only", "false").lower() == "true"
    date_start = request.args.get("date_start")
    date_end = request.args.get("date_end")

    # Always filter to running sport types
    mask = acts_all["sport_type"].isin(["Run", "TrailRun", "VirtualRun"])
    if date_start:
        mask &= acts_all["start_date_local"].dt.date >= pd.to_datetime(date_start).date()
    if date_end:
        mask &= acts_all["start_date_local"].dt.date <= pd.to_datetime(date_end).date()

    acts = acts_all[mask].copy()

    if races_only:
        acts = acts[acts["workout_type"] == 1].copy()

    # Try to build a daily resting-HR series from Garmin data for accurate TRIMP
    resting_hr_series = None
    try:
        ghr = load_garmin_hr_daily()
        if not ghr.empty and "restingHeartRate" in ghr.columns:
            resting_hr_series = ghr["restingHeartRate"].dropna()
    except Exception:
        pass

    zones = compute_hr_zones(max_hr, zone_model, resting_hr)
    return {
        "acts": acts,
        "zones": zones,
        "max_hr": max_hr,
        "resting_hr": resting_hr,
        "resting_hr_series": resting_hr_series,
    }


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def index():
    return render_template("index.html")


# ── Config ────────────────────────────────────────────────────────────────────

@app.route("/api/config")
def api_config():
    acts = load_activities()
    return jsonify({
        "max_hr": default_max_hr(acts),
        "date_min": str(acts["start_date_local"].dt.date.min()),
        "date_max": str(acts["start_date_local"].dt.date.max()),
        "sports": sorted(acts["sport_type"].dropna().unique().tolist()),
        "total_activities": len(acts),
    })


# ── Overview ──────────────────────────────────────────────────────────────────

@app.route("/api/overview")
def api_overview():
    p = _parse_params()
    acts, zones, max_hr, resting_hr = p["acts"], p["zones"], p["max_hr"], p["resting_hr"]
    acts_all = load_activities()

    date_start = request.args.get("date_start")
    date_end = request.args.get("date_end")
    races_only = request.args.get("races_only", "false").lower() == "true"

    # Compute previous period window
    if date_start and date_end:
        ds = pd.to_datetime(date_start).date()
        de = pd.to_datetime(date_end).date()
        duration = (de - ds).days + 1
        prev_end = ds - pd.Timedelta(days=1)
        prev_start = ds - pd.Timedelta(days=duration)
        prev_label = f"vs prev {duration}d"
    elif date_start:
        ds = pd.to_datetime(date_start).date()
        today = pd.Timestamp.now(tz="Europe/Prague").date()
        duration = (today - ds).days + 1
        prev_end = ds - pd.Timedelta(days=1)
        prev_start = ds - pd.Timedelta(days=duration)
        prev_label = f"vs prev {duration}d"
    else:
        now = pd.Timestamp.now(tz="Europe/Prague")
        prev_start = pd.date_range(start=f"{now.year - 1}-01-01", periods=1)[0].date()
        prev_end = (now - pd.DateOffset(years=1)).date()
        prev_label = "vs prev year"

    # Filter acts_all for previous period with same sport/races_only filters
    prev_mask = acts_all["sport_type"].isin(["Run", "TrailRun", "VirtualRun"])
    prev_mask &= acts_all["start_date_local"].dt.date >= prev_start
    prev_mask &= acts_all["start_date_local"].dt.date <= prev_end
    prev_acts = acts_all[prev_mask].copy()
    if races_only:
        prev_acts = prev_acts[prev_acts["workout_type"] == 1].copy()

    # KPIs
    kpis = {
        "activities": int(len(acts)),
        "distance_km": round(float(acts["distance_km"].sum()), 1),
        "elevation_m": round(float(acts["total_elevation_gain"].sum()), 0),
        "hours": round(float(acts["moving_time"].sum() / 3600), 1),
        "prev_distance_km": round(float(prev_acts["distance_km"].sum()), 1),
        "prev_elevation_m": round(float(prev_acts["total_elevation_gain"].sum()), 0),
        "prev_hours": round(float(prev_acts["moving_time"].sum() / 3600), 1),
        "prev_label": prev_label,
    }

    # Weekly heatmap
    df = acts.copy()
    df["iso_week"] = df["start_date_local"].dt.isocalendar().week.astype(int)
    df["iso_year"] = df["start_date_local"].dt.isocalendar().year.astype(int)
    weekly = df.groupby(["iso_year", "iso_week"])["distance_km"].sum().reset_index()
    pivot = weekly.pivot(index="iso_week", columns="iso_year", values="distance_km").fillna(0)
    heatmap = {
        "z": pivot.values.tolist(),
        "x": [str(y) for y in pivot.columns.tolist()],
        "y": [f"W{w:02d}" for w in pivot.index.tolist()],
    }

    # Monthly bar
    df["month_str"] = df["start_date_local"].dt.strftime("%Y-%m")
    monthly = df.groupby("month_str").agg(
        distance_km=("distance_km", "sum"),
        elevation=("total_elevation_gain", "sum"),
    ).reset_index().sort_values("month_str")
    monthly_data = {
        "months": monthly["month_str"].tolist(),
        "distance": monthly["distance_km"].round(1).tolist(),
        "elevation": monthly["elevation"].round(0).tolist(),
    }

    # Sport distribution
    sport_counts = acts.groupby("sport_type").agg(
        count=("id", "count"), distance_km=("distance_km", "sum")
    ).reset_index()
    sports_data = {
        "labels": sport_counts["sport_type"].tolist(),
        "counts": sport_counts["count"].tolist(),
        "distances": sport_counts["distance_km"].round(1).tolist(),
    }

    # Streaks
    current_streak, longest_streak = compute_streak(acts)
    this_year = acts["year"].max() if not acts.empty else 0
    days_active = int(acts[acts["year"] == this_year]["date"].nunique())

    # Gear mileage
    details = load_activity_details()
    gear_mileage = compute_gear_mileage(acts, details)

    return jsonify({
        "kpis": kpis,
        "heatmap": heatmap,
        "monthly": monthly_data,
        "sports": sports_data,
        "streaks": {
            "current": current_streak,
            "longest": longest_streak,
            "days_active_this_year": days_active,
            "year": int(this_year),
        },
        "gear_mileage": gear_mileage,
    })


# ── HR Zones ──────────────────────────────────────────────────────────────────

@app.route("/api/hr-zones")
def api_hr_zones():
    p = _parse_params()
    acts, zones, max_hr, resting_hr = p["acts"], p["zones"], p["max_hr"], p["resting_hr"]
    window_days = int(request.args.get("window_days", 90))

    # Zone definitions (Karvonen — % of HR reserve)
    hr_reserve = max_hr - resting_hr
    zone_defs = [
        {
            "name": name,
            "min_bpm": round(lo, 0),
            "max_bpm": round(min(hi, max_hr), 0),
            "pct": f"{(lo - resting_hr) / hr_reserve * 100:.0f}–{min((hi - resting_hr) / hr_reserve * 100, 100):.0f}% HRR",
        }
        for name, (lo, hi) in zones.items()
    ]

    # Rolling time-in-zones
    zone_summary = get_zone_summary(zones)
    zone_cols = [c for c in zone_summary.columns if c.endswith("_sec")]
    merged = acts[["id", "start_date_local"]].merge(
        zone_summary.rename(columns={"activity_id": "id"}), on="id", how="inner"
    )
    rolling_zones = {}
    if not merged.empty:
        merged = merged.set_index("start_date_local").sort_index()
        daily = merged[zone_cols].resample("D").sum()
        rolled = daily.rolling(f"{window_days}D", min_periods=1).sum()
        total = rolled.sum(axis=1).replace(0, np.nan)
        pct = (rolled.div(total, axis=0) * 100).fillna(0)
        rolling_zones = {
            "dates": pct.index.strftime("%Y-%m-%d").tolist(),
            "zones": {
                col.replace("_sec", ""): pct[col].round(1).tolist()
                for col in zone_cols if col in pct.columns
            },
        }

    # Aerobic efficiency
    ae_weekly = compute_aerobic_efficiency(acts)
    if not ae_weekly.empty:
        ae_weekly = ae_weekly.dropna(subset=["week_start", "ae_mean", "ae_rolling"])
    ae_data = {
        "dates": ae_weekly["week_start"].tolist(),
        "ae": ae_weekly["ae_mean"].round(5).tolist(),
        "ae_rolling": ae_weekly["ae_rolling"].round(5).tolist(),
    } if not ae_weekly.empty else {}

    # HR drift
    hr_drift_df = get_all_hr_drift()
    drift_merged = hr_drift_df.merge(
        acts[["id", "start_date_local", "pace_min_per_km", "distance_km"]].rename(columns={"id": "activity_id"}),
        on="activity_id", how="inner",
    ).dropna(subset=["early_hr", "late_hr", "start_date_local", "pace_min_per_km"])
    drift_data = {
        "early_hr": drift_merged["early_hr"].round(1).tolist(),
        "late_hr": drift_merged["late_hr"].round(1).tolist(),
        "pace": drift_merged["pace_min_per_km"].round(2).tolist(),
        "distance_km": drift_merged["distance_km"].round(1).tolist(),
        "dates": drift_merged["start_date_local"].dt.strftime("%Y-%m-%d").tolist(),
    } if not drift_merged.empty else {}

    hr_recovery_data = []
    try:
        intraday = load_garmin_hr_intraday()
        recovery_df = compute_hr_recovery(intraday, acts)
        if not recovery_df.empty:
            hr_recovery_data = _sanitize(recovery_df.to_dict("records"))
    except Exception:
        pass

    # Cadence trend
    cadence_data = {}
    try:
        details_cad = load_activity_details()
        cadence_df = compute_cadence_trend(acts, details_cad)
        if not cadence_df.empty:
            cadence_data = {
                "dates": cadence_df["week_start"].tolist(),
                "avg_cadence": cadence_df["avg_cadence"].round(1).tolist(),
                "cadence_rolling": cadence_df["cadence_rolling"].round(1).tolist(),
            }
    except Exception:
        pass

    # Decoupling factor
    decoupling_data = {}
    try:
        drift_for_decouple = get_all_hr_drift()
        decouple_df = compute_decoupling_factor(drift_for_decouple, acts)
        if not decouple_df.empty:
            decouple_clean = decouple_df.dropna(subset=["decoupling_pct"])
            decoupling_data = {
                "dates": decouple_clean["date"].tolist(),
                "decoupling_pct": decouple_clean["decoupling_pct"].tolist(),
                "rolling_20": decouple_clean["rolling_20"].tolist(),
            }
    except Exception:
        pass

    return jsonify({
        "zone_defs": zone_defs,
        "rolling_zones": rolling_zones,
        "aerobic_efficiency": ae_data,
        "hr_drift": drift_data,
        "hr_recovery": hr_recovery_data,
        "cadence_weekly": cadence_data,
        "decoupling_factor": decoupling_data,
    })


# ── Fitness Tracker ───────────────────────────────────────────────────────────

@app.route("/api/fitness")
def api_fitness():
    p = _parse_params()
    acts, zones, max_hr, resting_hr = p["acts"], p["zones"], p["max_hr"], p["resting_hr"]

    try:
        daily_trimp = make_daily_trimp(acts, resting_hr, max_hr, resting_hr_series=p["resting_hr_series"])
    except Exception:
        daily_trimp = make_daily_trimp(acts, resting_hr, max_hr)
    if daily_trimp.sum() == 0:
        return jsonify({"error": "No heart rate data available."})

    form_df = compute_atl_ctl_tsb(daily_trimp)
    latest = form_df.iloc[-1]
    week_ago = form_df.iloc[-8] if len(form_df) >= 8 else form_df.iloc[0]

    # Downsample to weekly for smaller payload
    form_weekly = form_df.resample("W").last().dropna()

    # ACWR series
    acwr_series = compute_acwr(form_df)
    acwr_weekly = acwr_series.resample("W").last().dropna()
    acwr_current = float(acwr_series.iloc[-1]) if not acwr_series.empty else None

    # Activity overlay (date + CTL value at that date)
    act_dates = pd.to_datetime(acts["date"])
    act_ctl = form_df["CTL"].reindex(act_dates, method="nearest")

    # Resting HR trend for chart
    resting_hr_data = []
    morning_readiness_data = None
    try:
        ghr = load_garmin_hr_daily()
        if not ghr.empty:
            ghr_filtered = ghr[["restingHeartRate", "lastSevenDaysAvgRestingHeartRate"]].dropna(how="all").copy()
            ghr_filtered["date"] = ghr_filtered.index.strftime("%Y-%m-%d")
            ghr_filtered = ghr_filtered.sort_index()
            resting_hr_data = [
                {
                    "date": row["date"],
                    "resting_hr": None if pd.isna(row["restingHeartRate"]) else round(float(row["restingHeartRate"]), 1),
                    "rolling_7d": None if pd.isna(row["lastSevenDaysAvgRestingHeartRate"]) else round(float(row["lastSevenDaysAvgRestingHeartRate"]), 1),
                }
                for _, row in ghr_filtered.iterrows()
            ]
    except Exception:
        pass

    try:
        intraday = load_garmin_hr_intraday()
        ghr = load_garmin_hr_daily()
        readiness_df = compute_morning_readiness(intraday, ghr)
        if not readiness_df.empty:
            latest_r = readiness_df.iloc[-1]
            morning_readiness_data = {
                "date": latest_r["date"],
                "score": None if pd.isna(latest_r["readiness_score"]) else round(float(latest_r["readiness_score"]), 1),
                "morning_hr": None if pd.isna(latest_r["morning_hr"]) else round(float(latest_r["morning_hr"]), 1),
                "baseline_hr": None if pd.isna(latest_r["baseline_hr"]) else round(float(latest_r["baseline_hr"]), 1),
            }
    except Exception:
        pass

    return jsonify({
        "current": {
            "ctl": round(float(latest["CTL"]), 1),
            "atl": round(float(latest["ATL"]), 1),
            "tsb": round(float(latest["TSB"]), 1),
            "ctl_delta": round(float(latest["CTL"] - week_ago["CTL"]), 1),
            "atl_delta": round(float(latest["ATL"] - week_ago["ATL"]), 1),
            "tsb_delta": round(float(latest["TSB"] - week_ago["TSB"]), 1),
        },
        "series": {
            "dates": form_weekly.index.strftime("%Y-%m-%d").tolist(),
            "ctl": form_weekly["CTL"].round(1).tolist(),
            "atl": form_weekly["ATL"].round(1).tolist(),
            "tsb": form_weekly["TSB"].round(1).tolist(),
        },
        "activities": {
            "dates": act_dates.dt.strftime("%Y-%m-%d").tolist(),
            "ctl": act_ctl.round(1).tolist(),
            "names": acts["name"].fillna("Activity").tolist(),
            "distance_km": acts["distance_km"].round(1).tolist(),
        },
        "resting_hr_series": resting_hr_data,
        "morning_readiness": morning_readiness_data,
        "acwr": {
            "current_value": round(acwr_current, 3) if acwr_current is not None else None,
            "series": {
                "dates": acwr_weekly.index.strftime("%Y-%m-%d").tolist(),
                "values": acwr_weekly.round(3).tolist(),
            },
        },
    })


# ── Pacing ────────────────────────────────────────────────────────────────────

@app.route("/api/pacing")
def api_pacing():
    p = _parse_params()
    acts, zones, max_hr, resting_hr = p["acts"], p["zones"], p["max_hr"], p["resting_hr"]
    details = load_activity_details()

    split_stats = compute_split_stats(acts, details)
    splits_out = {}
    if not split_stats.empty:
        df = split_stats.dropna(subset=["split_diff"]).copy()
        df["rolling"] = df["split_diff"].rolling(20, min_periods=5).mean()
        df = df.dropna(subset=["rolling"])
        splits_out = {
            "dates": df["date"].tolist(),
            "split_diff": df["split_diff"].tolist(),
            "rolling": df["rolling"].round(1).tolist(),
            "distance_km": df["distance_km"].tolist(),
        }

    # Pacing consistency
    consistency_out = {}
    if not split_stats.empty:
        df2 = split_stats.dropna(subset=["pace_std"]).copy()
        df2["rolling"] = df2["pace_std"].rolling(20, min_periods=5).mean()
        df2 = df2.dropna(subset=["rolling"])
        consistency_out = {
            "dates": df2["date"].tolist(),
            "pace_std": df2["pace_std"].tolist(),
            "rolling": df2["rolling"].round(1).tolist(),
        }

    # Best efforts
    run_acts = acts[acts["sport_type"].isin(["Run", "TrailRun"])].copy()
    run_acts["month_str"] = run_acts["start_date_local"].dt.strftime("%Y-%m")
    thresholds = {"1 km": 1.0, "5 km": 5.0, "10 km": 10.0, "Half marathon": 21.0, "Marathon": 42.0}
    best_efforts = {}
    for label, min_km in thresholds.items():
        subset = run_acts[run_acts["distance_km"] >= min_km * 0.9]
        if subset.empty:
            continue
        monthly = subset.groupby("month_str")["pace_min_per_km"].min().reset_index().sort_values("month_str")
        monthly["pb"] = monthly["pace_min_per_km"].cummin()
        best_efforts[label] = {
            "months": monthly["month_str"].tolist(),
            "pace": monthly["pace_min_per_km"].round(2).tolist(),
            "pb": monthly["pb"].round(2).tolist(),
        }

    # Race history (workout_type == 1)
    race_history = {}
    race_acts = run_acts[run_acts.get("workout_type", pd.Series(0, index=run_acts.index)) == 1].copy() if "workout_type" in run_acts.columns else pd.DataFrame()
    if not race_acts.empty:
        thresholds_race = {"5 km": 4.5, "10 km": 9.0, "Half marathon": 19.0, "Marathon": 38.0}
        for label, min_km in thresholds_race.items():
            max_km = min_km * 3
            subset = race_acts[(race_acts["distance_km"] >= min_km) & (race_acts["distance_km"] < max_km)]
            if not subset.empty:
                race_history[label] = {
                    "dates": subset["start_date_local"].dt.strftime("%Y-%m-%d").tolist(),
                    "pace": subset["pace_min_per_km"].round(2).tolist(),
                    "distance_km": subset["distance_km"].round(1).tolist(),
                }

    # Race predictor
    best_paces_for_predict = {
        label: min(data["pace"]) for label, data in best_efforts.items() if data["pace"]
    }
    predictions = compute_race_predictor(best_paces_for_predict)

    return jsonify({
        "splits": splits_out,
        "consistency": consistency_out,
        "best_efforts": best_efforts,
        "race_history": race_history,
        "predictions": predictions,
    })


# ── Periodization ─────────────────────────────────────────────────────────────

@app.route("/api/periodization")
def api_periodization():
    p = _parse_params()
    acts, zones, max_hr, resting_hr = p["acts"], p["zones"], p["max_hr"], p["resting_hr"]

    # Weekly volume
    weekly = acts.groupby("week").agg(distance_km=("distance_km", "sum")).reset_index()
    weekly["week_start"] = weekly["week"].dt.start_time.dt.strftime("%Y-%m-%d")
    weekly = weekly.sort_values("week_start")
    weekly["rolling_4w"] = weekly["distance_km"].rolling(4, min_periods=1).mean()
    weekly_data = {
        "weeks": weekly["week_start"].tolist(),
        "distance": weekly["distance_km"].round(1).tolist(),
        "rolling": weekly["rolling_4w"].round(1).tolist(),
    }

    # Year-over-year — always uses full history (date filter ignored intentionally)
    races_only = request.args.get("races_only", "false").lower() == "true"
    acts_all = load_activities()
    yoy_mask = acts_all["sport_type"].isin(["Run", "TrailRun", "VirtualRun"])
    if races_only:
        yoy_mask &= acts_all["workout_type"] == 1
    df = acts_all[yoy_mask].copy()
    df["month_num"] = df["start_date_local"].dt.month
    # Elevation-adjusted speed (same formula as AE metric, factor=7)
    elev = df["total_elevation_gain"].fillna(0).clip(lower=0)
    eff_dist_m = df["distance_km"] * 1000 + elev * 7
    df["adj_speed"] = eff_dist_m / df["moving_time"]          # m/s
    df["gap_pace"] = (1000 / df["adj_speed"] / 60).where(df["adj_speed"] > 0)  # min/km

    yoy = df.groupby(["year", "month_num"])["distance_km"].sum().reset_index()
    years = sorted(yoy["year"].unique().tolist())
    month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    yoy_data = {
        "months": month_names,
        "years": {
            str(yr): yoy[yoy["year"] == yr].set_index("month_num")["distance_km"]
                .reindex(range(1, 13), fill_value=0).round(1).tolist()
            for yr in years
        },
    }

    # YoY — Aerobic Efficiency (requires HR data)
    df_ae = df[df["average_heartrate"].notna() & (df["average_heartrate"] > 0) & df["adj_speed"].notna()].copy()
    df_ae["ae"] = df_ae["adj_speed"] / df_ae["average_heartrate"]
    yoy_ae_grouped = df_ae.groupby(["year", "month_num"])["ae"].mean().reset_index()
    yoy_ae_years = sorted(yoy_ae_grouped["year"].unique().tolist())
    yoy_ae_data = {
        "months": month_names,
        "years": {
            str(yr): yoy_ae_grouped[yoy_ae_grouped["year"] == yr].set_index("month_num")["ae"]
                .reindex(range(1, 13)).round(5).tolist()
            for yr in yoy_ae_years
        },
    }

    # YoY — GAP Pace (min/km, lower = faster)
    df_gap = df[df["gap_pace"].notna() & (df["gap_pace"] > 0) & (df["gap_pace"] < 30)].copy()
    yoy_gap_grouped = df_gap.groupby(["year", "month_num"])["gap_pace"].mean().reset_index()
    yoy_gap_years = sorted(yoy_gap_grouped["year"].unique().tolist())
    yoy_gap_data = {
        "months": month_names,
        "years": {
            str(yr): yoy_gap_grouped[yoy_gap_grouped["year"] == yr].set_index("month_num")["gap_pace"]
                .reindex(range(1, 13)).round(2).tolist()
            for yr in yoy_gap_years
        },
    }

    # Training monotony
    try:
        daily_trimp = make_daily_trimp(acts, resting_hr, max_hr, resting_hr_series=p["resting_hr_series"])
    except Exception:
        daily_trimp = make_daily_trimp(acts, resting_hr, max_hr)
    monotony_data = {}
    if daily_trimp.sum() > 0:
        mono = compute_training_monotony(daily_trimp).dropna()
        # Weekly resample
        mono_weekly = mono.resample("W").mean().dropna()
        monotony_data = {
            "dates": mono_weekly.index.strftime("%Y-%m-%d").tolist(),
            "monotony": mono_weekly.round(2).tolist(),
        }

    # Easy/Moderate/Hard distribution
    zone_summary = get_zone_summary(zones)
    intensity_data = {}
    if not zone_summary.empty:
        zone_cols = [c for c in zone_summary.columns if c.endswith("_sec")]
        merged = acts[["id", "start_date_local", "month"]].merge(
            zone_summary.rename(columns={"activity_id": "id"}), on="id", how="inner"
        )
        if not merged.empty:
            model = request.args.get("zone_model", "5zone")
            if model == "3zone":
                merged["easy"] = merged.get("Easy_sec", 0)
                merged["moderate"] = merged.get("Moderate_sec", 0)
                merged["hard"] = merged.get("Hard_sec", 0)
            else:
                merged["easy"] = (
                    merged.get("Z1_sec", pd.Series(0, index=merged.index)).fillna(0) +
                    merged.get("Z2_sec", pd.Series(0, index=merged.index)).fillna(0)
                )
                merged["moderate"] = merged.get("Z3_sec", pd.Series(0, index=merged.index)).fillna(0).values
                merged["hard"] = (
                    merged.get("Z4_sec", pd.Series(0, index=merged.index)).fillna(0) +
                    merged.get("Z5_sec", pd.Series(0, index=merged.index)).fillna(0)
                )
            monthly = merged.groupby("month")[["easy", "moderate", "hard"]].sum().reset_index()
            total = monthly[["easy", "moderate", "hard"]].sum(axis=1).replace(0, np.nan)
            intensity_data = {
                "months": monthly["month"].astype(str).tolist(),
                "easy": (monthly["easy"] / total * 100).round(1).tolist(),
                "moderate": (monthly["moderate"] / total * 100).round(1).tolist(),
                "hard": (monthly["hard"] / total * 100).round(1).tolist(),
            }

    # Ramp rate
    ramp_df = compute_weekly_ramp_rate(acts)
    ramp_data = {}
    if not ramp_df.empty:
        ramp_data = {
            "weeks": ramp_df["week_start"].tolist(),
            "ramp_rate": _sanitize(ramp_df["ramp_rate"].tolist()),
        }

    # Long run flags
    long_run_df = compute_long_run_flags(acts)
    long_runs_data = {}
    if not long_run_df.empty:
        long_runs_data = {
            "weeks": long_run_df["week_start"].tolist(),
            "is_long_run": long_run_df["is_long_run"].tolist(),
            "long_run_distance": _sanitize(long_run_df["long_run_distance"].tolist()),
        }

    return jsonify({
        "weekly": weekly_data,
        "yoy": yoy_data,
        "yoy_ae": yoy_ae_data,
        "yoy_gap": yoy_gap_data,
        "monotony": monotony_data,
        "intensity": intensity_data,
        "ramp_rate": ramp_data,
        "long_runs": long_runs_data,
    })


# ── Debug ─────────────────────────────────────────────────────────────────────

@app.route("/api/debug")
def api_debug():
    result = {
        "env": {
            "KEBOOLA_STORAGE_TOKEN": (
                f"{_KEBOOLA_STORAGE_TOKEN[:6]}…{_KEBOOLA_STORAGE_TOKEN[-4:]}"
                if _KEBOOLA_STORAGE_TOKEN and len(_KEBOOLA_STORAGE_TOKEN) > 10
                else ("SET (short)" if _KEBOOLA_STORAGE_TOKEN else "NOT SET")
            ),
            "KEBOOLA_STORAGE_URL": _KEBOOLA_STORAGE_URL,
        },
        "local_paths": {
            name: os.path.exists(path)
            for name, path in _KEBOOLA_LOCAL_PATHS.items()
        },
        "token_verify": None,
        "activities_preview": None,
        "errors": [],
    }

    if _KEBOOLA_STORAGE_TOKEN:
        try:
            import requests as req
            resp = req.get(
                f"{_KEBOOLA_STORAGE_URL}/v2/storage/tokens/verify",
                headers={"X-StorageApi-Token": _KEBOOLA_STORAGE_TOKEN},
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                result["token_verify"] = {
                    "ok": True,
                    "description": data.get("description", ""),
                    "project": data.get("admin", {}).get("name", "") or str(data.get("isMasterToken")),
                }
            else:
                result["token_verify"] = {"ok": False, "status": resp.status_code, "body": resp.text[:300]}
        except Exception as e:
            result["errors"].append(f"Token verify failed: {e}")

        # Probe federation token structure (fast — just shows metadata, no full download)
        try:
            import requests as req
            from data_loader import _extract_gcs_token
            headers_kbc = {"X-StorageApi-Token": _KEBOOLA_STORAGE_TOKEN}
            job_resp = req.post(
                f"{_KEBOOLA_STORAGE_URL}/v2/storage/tables/in.c-Garmin_full.activities/export-async",
                headers=headers_kbc,
                timeout=15,
            )
            job_resp.raise_for_status()
            job_id = job_resp.json()["id"]
            import time as _time
            for _ in range(60):
                j = req.get(f"{_KEBOOLA_STORAGE_URL}/v2/storage/jobs/{job_id}", headers=headers_kbc, timeout=10).json()
                if j["status"] in ("success", "error", "terminated"):
                    break
                _time.sleep(1)
            if j.get("status") == "success":
                file_id = j["results"]["file"]["id"]
                fm = req.get(
                    f"{_KEBOOLA_STORAGE_URL}/v2/storage/files/{file_id}?federationToken=1",
                    headers=headers_kbc, timeout=10,
                ).json()
                gcs_creds = fm.get("gcsCredentials")
                token = _extract_gcs_token(fm)
                result["federation_token_probe"] = {
                    "file_meta_top_keys": list(fm.keys()),
                    "gcsCredentials_keys": list(gcs_creds.keys()) if isinstance(gcs_creds, dict) else repr(gcs_creds),
                    "token_extracted": token is not None,
                    "token_prefix": token[:12] + "…" if token else None,
                }
        except Exception:
            result["errors"].append(f"Federation token probe failed: {traceback.format_exc()}")

    try:
        acts = load_activities()
        result["activities_preview"] = {
            "rows": len(acts),
            "columns": acts.columns.tolist(),
            "date_range": f"{acts['start_date_local'].dt.date.min()} → {acts['start_date_local'].dt.date.max()}",
            "sports": sorted(acts["sport_type"].dropna().unique().tolist()),
        }
    except Exception as e:
        result["errors"].append(f"load_activities failed: {traceback.format_exc()}")

    return jsonify(result)


# ── Keboola Job API ───────────────────────────────────────────────────────────

_KEBOOLA_REFERENCE_JOB_ID = "42285798"
_KEBOOLA_QUEUE_URL = _KEBOOLA_STORAGE_URL.replace("connection.", "queue.")
_keboola_job_config_cache: dict = {}


_KEBOOLA_JOB_TOKEN = os.environ.get("KEBOOLA_JOB_TOKEN") or _KEBOOLA_STORAGE_TOKEN


def _keboola_headers():
    return {"X-StorageApi-Token": _KEBOOLA_JOB_TOKEN or ""}


def _get_keboola_job_config():
    """Fetch componentId + configId from the reference job (cached)."""
    global _keboola_job_config_cache
    if _keboola_job_config_cache:
        return _keboola_job_config_cache
    r = requests.get(
        f"{_KEBOOLA_QUEUE_URL}/jobs/{_KEBOOLA_REFERENCE_JOB_ID}",
        headers=_keboola_headers(),
        timeout=10,
    )
    r.raise_for_status()
    job = r.json()
    component_id = job.get("componentId") or job.get("component")
    config_id = job.get("configId") or job.get("config")
    if not component_id or not config_id:
        raise ValueError(
            f"Cannot extract componentId/configId from job response. "
            f"Available keys: {list(job.keys())}"
        )
    _keboola_job_config_cache = {"componentId": component_id, "configId": config_id}
    return _keboola_job_config_cache


@app.route("/api/keboola-status")
def api_keboola_status():
    try:
        cfg = _get_keboola_job_config()
        r = requests.get(
            f"{_KEBOOLA_QUEUE_URL}/jobs",
            params={
                "componentId": cfg["componentId"],
                "configId": cfg["configId"],
                "sortBy": "createdTime",
                "sortOrder": "desc",
                "limit": 1,
            },
            headers=_keboola_headers(),
            timeout=10,
        )
        r.raise_for_status()
        jobs = r.json()
        if not jobs:
            return jsonify({"last_run": None, "status": None})
        job = jobs[0]
        return jsonify({
            "last_run": job.get("endTime") or job.get("startTime") or job.get("createdTime"),
            "status": job.get("status"),
            "job_id": job.get("id"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/api/keboola-run", methods=["POST"])
def api_keboola_run():
    try:
        cfg = _get_keboola_job_config()
        body = {
            "component": cfg["componentId"],
            "config": cfg["configId"],
            "mode": "run",
        }
        r = requests.post(
            f"{_KEBOOLA_QUEUE_URL}/jobs",
            json=body,
            headers=_keboola_headers(),
            timeout=10,
        )
        if not r.ok:
            return jsonify({"error": f"Keboola {r.status_code}: {r.text}"}), 500
        job = r.json()
        return jsonify({"job_id": job.get("id"), "status": job.get("status")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Error handler ─────────────────────────────────────────────────────────────

@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
