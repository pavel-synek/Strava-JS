import traceback

import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request

import os

from data_loader import (
    _KEBOOLA_STORAGE_TOKEN,
    _KEBOOLA_STORAGE_URL,
    _KEBOOLA_LOCAL_PATHS,
    get_all_hr_drift,
    get_zone_summary,
    load_activities,
    load_activity_details,
    load_streams,
)
from metrics import (
    compute_aerobic_efficiency,
    compute_atl_ctl_tsb,
    compute_hr_zones,
    compute_split_stats,
    compute_streak,
    compute_training_monotony,
    default_max_hr,
    make_daily_trimp,
)

app = Flask(__name__)


def _parse_params():
    acts_all = load_activities()
    max_hr = float(request.args.get("max_hr", default_max_hr(acts_all)))
    resting_hr = float(request.args.get("resting_hr", 50))
    zone_model = request.args.get("zone_model", "5zone")
    sports = request.args.getlist("sports") or ["Run", "TrailRun"]
    date_start = request.args.get("date_start")
    date_end = request.args.get("date_end")

    mask = pd.Series(True, index=acts_all.index)
    if sports:
        mask &= acts_all["sport_type"].isin(sports)
    if date_start:
        mask &= acts_all["start_date_local"].dt.date >= pd.to_datetime(date_start).date()
    if date_end:
        mask &= acts_all["start_date_local"].dt.date <= pd.to_datetime(date_end).date()

    acts = acts_all[mask].copy()
    zones = compute_hr_zones(max_hr, zone_model)
    return acts, zones, max_hr, resting_hr


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
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
    acts, zones, max_hr, resting_hr = _parse_params()
    acts_all = load_activities()

    now = pd.Timestamp.now(tz="Europe/Prague")
    prev_acts = acts_all[acts_all["start_date_local"] < now - pd.DateOffset(years=1)]

    # KPIs
    kpis = {
        "activities": int(len(acts)),
        "distance_km": round(float(acts["distance_km"].sum()), 1),
        "elevation_m": round(float(acts["total_elevation_gain"].sum()), 0),
        "hours": round(float(acts["moving_time"].sum() / 3600), 1),
        "prev_distance_km": round(float(prev_acts["distance_km"].sum()), 1),
        "prev_elevation_m": round(float(prev_acts["total_elevation_gain"].sum()), 0),
        "prev_hours": round(float(prev_acts["moving_time"].sum() / 3600), 1),
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
    })


# ── HR Zones ──────────────────────────────────────────────────────────────────

@app.route("/api/hr-zones")
def api_hr_zones():
    acts, zones, max_hr, resting_hr = _parse_params()
    window_days = int(request.args.get("window_days", 90))

    # Zone definitions
    zone_defs = [
        {
            "name": name,
            "min_bpm": round(lo, 0),
            "max_bpm": round(min(hi, max_hr), 0),
            "pct": f"{lo/max_hr*100:.0f}–{min(hi/max_hr*100, 100):.0f}%",
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
    ae_data = {
        "dates": ae_weekly["week_start"].tolist(),
        "ae": ae_weekly["ae_mean"].round(5).tolist(),
        "ae_rolling": ae_weekly["ae_rolling"].round(5).tolist(),
    } if not ae_weekly.empty else {}

    # HR drift
    hr_drift_df = get_all_hr_drift()
    drift_merged = hr_drift_df.merge(
        acts[["id", "start_date_local", "pace_min_per_km", "distance_km"]].rename(columns={"id": "activity_id"}),
        on="activity_id", how="left",
    ).dropna(subset=["early_hr", "late_hr"])
    drift_data = {
        "early_hr": drift_merged["early_hr"].round(1).tolist(),
        "late_hr": drift_merged["late_hr"].round(1).tolist(),
        "pace": drift_merged["pace_min_per_km"].round(2).tolist(),
        "distance_km": drift_merged["distance_km"].round(1).tolist(),
        "dates": drift_merged["start_date_local"].dt.strftime("%Y-%m-%d").tolist(),
    } if not drift_merged.empty else {}

    return jsonify({
        "zone_defs": zone_defs,
        "rolling_zones": rolling_zones,
        "aerobic_efficiency": ae_data,
        "hr_drift": drift_data,
    })


# ── Fitness Tracker ───────────────────────────────────────────────────────────

@app.route("/api/fitness")
def api_fitness():
    acts, zones, max_hr, resting_hr = _parse_params()

    daily_trimp = make_daily_trimp(acts, resting_hr, max_hr)
    if daily_trimp.sum() == 0:
        return jsonify({"error": "No heart rate data available."})

    form_df = compute_atl_ctl_tsb(daily_trimp)
    latest = form_df.iloc[-1]
    week_ago = form_df.iloc[-8] if len(form_df) >= 8 else form_df.iloc[0]

    # Downsample to weekly for smaller payload
    form_weekly = form_df.resample("W").last().dropna()

    # Activity overlay (date + CTL value at that date)
    act_dates = pd.to_datetime(acts["date"])
    act_ctl = form_df["CTL"].reindex(act_dates, method="nearest")

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
    })


# ── Pacing ────────────────────────────────────────────────────────────────────

@app.route("/api/pacing")
def api_pacing():
    acts, zones, max_hr, resting_hr = _parse_params()
    details = load_activity_details()

    split_stats = compute_split_stats(acts, details)
    splits_out = {}
    if not split_stats.empty:
        df = split_stats.dropna(subset=["split_diff"]).copy()
        df["rolling"] = df["split_diff"].rolling(20, min_periods=5).mean()
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

    return jsonify({
        "splits": splits_out,
        "consistency": consistency_out,
        "best_efforts": best_efforts,
    })


# ── Periodization ─────────────────────────────────────────────────────────────

@app.route("/api/periodization")
def api_periodization():
    acts, zones, max_hr, resting_hr = _parse_params()

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

    # Year-over-year
    df = acts.copy()
    df["month_num"] = df["start_date_local"].dt.month
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

    # Training monotony
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

    return jsonify({
        "weekly": weekly_data,
        "yoy": yoy_data,
        "monotony": monotony_data,
        "intensity": intensity_data,
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

        # Probe the export job result structure without downloading
        try:
            import requests as req
            headers_kbc = {"X-StorageApi-Token": _KEBOOLA_STORAGE_TOKEN}
            job_resp = req.post(
                f"{_KEBOOLA_STORAGE_URL}/v2/storage/tables/in.c-Garmin_full.activities/export-async",
                headers=headers_kbc,
                timeout=15,
            )
            job_resp.raise_for_status()
            job_id = job_resp.json()["id"]
            import time as _time
            for _ in range(30):
                j = req.get(f"{_KEBOOLA_STORAGE_URL}/v2/storage/jobs/{job_id}", headers=headers_kbc, timeout=10).json()
                if j["status"] in ("success", "error", "terminated"):
                    break
                _time.sleep(1)
            result["export_job_probe"] = {
                "status": j.get("status"),
                "results_keys": list(j.get("results", {}).keys()),
                "file_keys": list((j.get("results", {}).get("file") or {}).keys()),
            }
            if j.get("status") == "success":
                file_id = j["results"]["file"].get("id")
                if file_id:
                    fm = req.get(f"{_KEBOOLA_STORAGE_URL}/v2/storage/files/{file_id}?federationToken=1", headers=headers_kbc, timeout=10).json()
                    result["file_meta_keys"] = list(fm.keys())
                    result["file_meta_url_present"] = "url" in fm
                    result["file_meta_url_value"] = str(fm.get("url", ""))[:80]
                    sa = fm.get("gcsCredentials") or fm.get("uploadParams", {}).get("credentials")
                    result["gcs_credentials_type"] = sa.get("type") if isinstance(sa, dict) else str(type(sa))
        except Exception as e:
            result["errors"].append(f"Export probe failed: {traceback.format_exc()}")

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


# ── Error handler ─────────────────────────────────────────────────────────────

@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
