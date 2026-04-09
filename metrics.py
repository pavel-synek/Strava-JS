import json
from datetime import timedelta
import numpy as np
import pandas as pd


def compute_hr_zones(max_hr: float, model: str = "5zone", resting_hr: float = 45.0) -> dict:
    """Karvonen method: target HR = (HR_reserve × intensity%) + resting_hr"""
    hr_reserve = max_hr - resting_hr
    if model == "3zone":
        boundaries = {"Easy": (0.0, 0.70), "Moderate": (0.70, 0.85), "Hard": (0.85, 1.01)}
    else:
        boundaries = {
            "Z1": (0.0, 0.60), "Z2": (0.60, 0.70), "Z3": (0.70, 0.80),
            "Z4": (0.80, 0.90), "Z5": (0.90, 1.01),
        }
    return {name: (lo * hr_reserve + resting_hr, hi * hr_reserve + resting_hr) for name, (lo, hi) in boundaries.items()}


def compute_trimp(acts: pd.DataFrame, resting_hr: float, max_hr: float, resting_hr_series: pd.Series = None) -> pd.Series:
    per_act_resting = resting_hr  # default scalar path
    if resting_hr_series is not None and not resting_hr_series.empty:
        try:
            act_dates = pd.to_datetime(acts["date"]).dt.normalize()
            # Deduplicate index (multiple rows per day → keep last), then map via pandas alignment
            rs = resting_hr_series[~resting_hr_series.index.duplicated(keep="last")]
            per_act_resting = act_dates.map(rs).fillna(resting_hr).astype(float)
            per_act_resting.index = acts.index
        except Exception:
            per_act_resting = resting_hr  # fall back to scalar on any error

    hr_range = max_hr - per_act_resting
    if not isinstance(hr_range, pd.Series) and hr_range <= 0:
        return pd.Series(np.nan, index=acts.index)
    hr_ratio = (acts["average_heartrate"] - per_act_resting) / hr_range
    hr_ratio = hr_ratio.clip(0.01, 1.0)
    trimp = acts["moving_time_min"] * hr_ratio * 0.64 * np.exp(1.92 * hr_ratio)
    return trimp.where(acts["average_heartrate"].notna())


def make_daily_trimp(acts: pd.DataFrame, resting_hr: float, max_hr: float, resting_hr_series: pd.Series = None) -> pd.Series:
    acts2 = acts.copy()
    acts2["trimp"] = compute_trimp(acts, resting_hr, max_hr, resting_hr_series=resting_hr_series)
    acts2["date_only"] = pd.to_datetime(acts2["date"])
    daily = acts2.groupby("date_only")["trimp"].sum()
    full_range = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    return daily.reindex(full_range, fill_value=0)


def compute_atl_ctl_tsb(daily_trimp: pd.Series) -> pd.DataFrame:
    ctl = daily_trimp.ewm(span=42, adjust=False).mean()
    atl = daily_trimp.ewm(span=7, adjust=False).mean()
    return pd.DataFrame({"CTL": ctl, "ATL": atl, "TSB": ctl - atl})


def compute_aerobic_efficiency(acts: pd.DataFrame) -> pd.DataFrame:
    mask = (
        acts["sport_type"].isin(["Run", "TrailRun"]) &
        acts["average_heartrate"].notna() & (acts["average_heartrate"] > 0) &
        acts["average_speed"].notna() & (acts["average_speed"] > 0)
    )
    df = acts[mask].copy()
    # Elevation-adjusted speed: each metre of ascent ≈ 7 m of flat equivalent (Minetti)
    elev = df["total_elevation_gain"].fillna(0).clip(lower=0)
    effective_distance_m = df["distance_km"] * 1000 + elev * 7
    adjusted_speed = effective_distance_m / df["moving_time"]  # m/s, same units as average_speed
    df["ae"] = adjusted_speed / df["average_heartrate"]
    weekly = df.groupby("week").agg(ae_mean=("ae", "mean"), distance_km=("distance_km", "sum")).reset_index()
    weekly["ae_rolling"] = weekly["ae_mean"].rolling(4, min_periods=1).mean()
    weekly["week_start"] = weekly["week"].dt.start_time.dt.strftime("%Y-%m-%d")
    return weekly.drop(columns=["week"])


def parse_splits_metric(splits_json_str) -> pd.DataFrame | None:
    if pd.isna(splits_json_str) or not splits_json_str:
        return None
    try:
        data = json.loads(splits_json_str)
        return pd.DataFrame(data) if data else None
    except (json.JSONDecodeError, TypeError):
        return None


def compute_split_stats(acts: pd.DataFrame, details: pd.DataFrame) -> pd.DataFrame:
    if "splits_metric" not in details.columns:
        return pd.DataFrame()
    run_acts = acts[acts["sport_type"].isin(["Run", "TrailRun"])]
    merged = run_acts[["id", "start_date_local", "distance_km"]].merge(
        details[["id", "splits_metric"]], on="id", how="inner"
    )
    results = []
    for _, row in merged.iterrows():
        splits_df = parse_splits_metric(row.get("splits_metric"))
        if splits_df is None or len(splits_df) < 2 or "average_speed" not in splits_df.columns:
            continue
        speeds = splits_df["average_speed"].dropna()
        if len(speeds) < 2:
            continue
        half = len(speeds) // 2
        first_pace = 1000 / speeds.iloc[:half].mean() if speeds.iloc[:half].mean() > 0 else np.nan
        second_pace = 1000 / speeds.iloc[half:].mean() if speeds.iloc[half:].mean() > 0 else np.nan
        paces = 1000 / speeds.replace(0, np.nan)
        results.append({
            "activity_id": int(row["id"]),
            "date": row["start_date_local"].strftime("%Y-%m-%d"),
            "distance_km": round(float(row["distance_km"]), 1),
            "split_diff": round(float(second_pace - first_pace), 1) if not (np.isnan(first_pace) or np.isnan(second_pace)) else None,
            "pace_std": round(float(paces.std()), 1),
        })
    return pd.DataFrame(results)


def compute_training_monotony(daily_trimp: pd.Series, window: int = 7) -> pd.Series:
    roll = daily_trimp.rolling(window, min_periods=3)
    return (roll.mean() / roll.std().replace(0, np.nan))


def compute_streak(acts: pd.DataFrame) -> tuple[int, int]:
    run_acts = acts[acts["sport_type"].isin(["Run", "TrailRun"])]
    if run_acts.empty:
        return 0, 0
    active_dates = sorted(set(pd.to_datetime(run_acts["date"])))
    longest = current = 1
    for i in range(1, len(active_dates)):
        if (active_dates[i] - active_dates[i - 1]).days == 1:
            current += 1
            longest = max(longest, current)
        elif (active_dates[i] - active_dates[i - 1]).days > 1:
            current = 1
    today = pd.Timestamp.now(tz="UTC").tz_convert("Europe/Prague").normalize().tz_localize(None)
    active_set = {d.date() if hasattr(d, "date") else d for d in active_dates}
    current_streak = 0
    check = today
    while check.date() in active_set:
        current_streak += 1
        check -= pd.Timedelta(days=1)
    return current_streak, longest


def default_max_hr(acts: pd.DataFrame) -> int:
    valid = acts["max_heartrate"].dropna()
    return int(valid.quantile(0.98)) if not valid.empty else 185


def compute_hr_recovery(intraday_df: pd.DataFrame, activities_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each activity with HR data, compute post-activity HR recovery from intraday data.
    Returns DataFrame with activity_id, date, distance_km, pace_min_per_km, recovery_1min, recovery_2min.
    """
    empty_cols = ["activity_id", "date", "distance_km", "pace_min_per_km", "recovery_1min", "recovery_2min"]
    if activities_df.empty or intraday_df.empty:
        return pd.DataFrame(columns=empty_cols)

    acts = activities_df[
        (activities_df["average_heartrate"] > 0) &
        (activities_df["elapsed_time"] > 0) &
        activities_df["start_date_local"].notna()
    ].copy()

    if acts.empty:
        return pd.DataFrame(columns=empty_cols)

    # Ensure intraday timestamps are UTC-aware
    ts = intraday_df["timestampGMT"]
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("UTC")
    else:
        ts = ts.dt.tz_convert("UTC")

    results = []
    for _, row in acts.iterrows():
        start_local = row["start_date_local"]
        elapsed = int(row["elapsed_time"])
        end_time = start_local + timedelta(seconds=elapsed)

        # Convert end_time to UTC
        if hasattr(end_time, "tzinfo") and end_time.tzinfo is not None:
            end_time_utc = end_time.tz_convert("UTC")
        else:
            end_time_utc = end_time.tz_localize("UTC")

        t_m2 = end_time_utc - timedelta(minutes=2)
        t_p30s = end_time_utc + timedelta(seconds=30)
        t_p90s = end_time_utc + timedelta(seconds=90)
        t_p150s = end_time_utc + timedelta(seconds=150)

        peak_window = intraday_df[(ts >= t_m2) & (ts <= t_p30s)]
        if len(peak_window) < 2:
            continue

        hr_at_end = peak_window["heartRate"].max()
        if pd.isna(hr_at_end):
            continue

        early_recovery = intraday_df[(ts > t_p30s) & (ts <= t_p90s)]
        hr_1min_after = early_recovery["heartRate"].mean() if not early_recovery.empty else np.nan

        late_recovery = intraday_df[(ts > t_p90s) & (ts <= t_p150s)]
        hr_2min_after = late_recovery["heartRate"].mean() if not late_recovery.empty else np.nan

        recovery_1min = hr_at_end - hr_1min_after
        recovery_2min = hr_at_end - hr_2min_after

        distance_km = float(row["distance_km"]) if "distance_km" in row and pd.notna(row.get("distance_km")) else np.nan
        moving_time = row.get("moving_time", np.nan)
        if pd.notna(distance_km) and distance_km > 0 and pd.notna(moving_time) and moving_time > 0:
            pace_min_per_km = (float(moving_time) / 60.0) / distance_km
        else:
            pace_min_per_km = np.nan

        results.append({
            "activity_id": int(row["id"]),
            "date": start_local.strftime("%Y-%m-%d"),
            "distance_km": round(distance_km, 2) if pd.notna(distance_km) else np.nan,
            "pace_min_per_km": round(pace_min_per_km, 2) if pd.notna(pace_min_per_km) else np.nan,
            "recovery_1min": round(recovery_1min, 1) if pd.notna(recovery_1min) else np.nan,
            "recovery_2min": round(recovery_2min, 1) if pd.notna(recovery_2min) else np.nan,
        })

    return pd.DataFrame(results, columns=empty_cols) if results else pd.DataFrame(columns=empty_cols)


def compute_morning_readiness(intraday_df: pd.DataFrame, hr_daily_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute morning readiness score from early-morning intraday HR vs 7-day average resting HR.
    Returns DataFrame with date, morning_hr, baseline_hr, readiness_score.
    """
    empty_cols = ["date", "morning_hr", "baseline_hr", "readiness_score"]
    if intraday_df.empty or hr_daily_df.empty:
        return pd.DataFrame(columns=empty_cols)

    df = intraday_df.copy()

    # Convert timestampGMT to Europe/Prague local time
    if df["timestampGMT"].dt.tz is None:
        df["ts_local"] = df["timestampGMT"].dt.tz_localize("UTC").dt.tz_convert("Europe/Prague")
    else:
        df["ts_local"] = df["timestampGMT"].dt.tz_convert("Europe/Prague")

    df["hour"] = df["ts_local"].dt.hour

    # Filter to early morning (4–7 AM local)
    morning = df[(df["hour"] >= 4) & (df["hour"] < 7)].copy()
    if morning.empty:
        return pd.DataFrame(columns=empty_cols)

    # Group by the string date column and compute median, requiring at least 3 samples
    morning_grouped = morning.groupby("date")["heartRate"].agg(["median", "count"])
    morning_grouped = morning_grouped[morning_grouped["count"] >= 3]
    if morning_grouped.empty:
        return pd.DataFrame(columns=empty_cols)

    results = []
    for date_str, row_g in morning_grouped.iterrows():
        morning_hr = float(row_g["median"])
        ts_key = pd.Timestamp(date_str)
        baseline_hr = hr_daily_df.get(ts_key, np.nan) if hasattr(hr_daily_df, "get") else np.nan
        if isinstance(hr_daily_df, pd.DataFrame):
            # If hr_daily_df is a DataFrame indexed by date, look up lastSevenDaysAvgRestingHeartRate
            if ts_key in hr_daily_df.index and "lastSevenDaysAvgRestingHeartRate" in hr_daily_df.columns:
                baseline_hr = float(hr_daily_df.loc[ts_key, "lastSevenDaysAvgRestingHeartRate"])
            else:
                baseline_hr = np.nan
        elif isinstance(hr_daily_df, pd.Series):
            baseline_hr = float(hr_daily_df.get(ts_key, np.nan))

        if pd.notna(baseline_hr) and baseline_hr > 0:
            readiness_score = (baseline_hr - morning_hr) / baseline_hr * 100
        else:
            readiness_score = np.nan

        results.append({
            "date": date_str,
            "morning_hr": round(morning_hr, 1),
            "baseline_hr": round(baseline_hr, 1) if pd.notna(baseline_hr) else np.nan,
            "readiness_score": round(readiness_score, 2) if pd.notna(readiness_score) else np.nan,
        })

    result_df = pd.DataFrame(results, columns=empty_cols)
    return result_df.sort_values("date").reset_index(drop=True)


def compute_acwr(form_df: pd.DataFrame) -> pd.Series:
    """Compute Acute:Chronic Workload Ratio (ATL/CTL). CTL clamped to min 1.0."""
    if form_df.empty:
        return pd.Series(name="ACWR", dtype=float)
    ctl_safe = form_df["CTL"].clip(lower=1.0)
    acwr = form_df["ATL"] / ctl_safe
    acwr.name = "ACWR"
    return acwr


def compute_weekly_ramp_rate(acts: pd.DataFrame) -> pd.DataFrame:
    """Compute week-over-week distance % change."""
    empty_cols = ["week_start", "ramp_rate"]
    if acts.empty:
        return pd.DataFrame(columns=empty_cols)
    weekly = acts.groupby("week")["distance_km"].sum().reset_index()
    weekly = weekly.sort_values("week")
    weekly["ramp_rate"] = weekly["distance_km"].pct_change() * 100
    weekly["week_start"] = weekly["week"].dt.start_time.dt.strftime("%Y-%m-%d")
    return weekly[empty_cols].reset_index(drop=True)


def compute_gear_mileage(acts: pd.DataFrame, details: pd.DataFrame) -> list:
    """Return list of dicts {gear_name, distance_km} sorted by distance descending."""
    if acts.empty:
        return []
    # Merge details gear_name onto acts; details takes priority
    if not details.empty and "gear_name" in details.columns:
        merged = acts.merge(
            details[["id", "gear_name"]].rename(columns={"gear_name": "gear_name_det"}),
            on="id", how="left"
        )
        merged["gear_resolved"] = merged["gear_name_det"].where(
            merged["gear_name_det"].notna() & (merged["gear_name_det"] != ""),
            other=merged.get("gear_name")
        )
    else:
        merged = acts.copy()
        merged["gear_resolved"] = merged.get("gear_name")

    # Filter out unknown/empty gear
    invalid = {"", "Unknown", None}
    mask = merged["gear_resolved"].notna() & ~merged["gear_resolved"].isin(invalid)
    filtered = merged[mask]
    if filtered.empty:
        return []

    grouped = (
        filtered.groupby("gear_resolved")["distance_km"]
        .sum()
        .reset_index()
        .rename(columns={"gear_resolved": "gear_name"})
        .sort_values("distance_km", ascending=False)
    )
    return [{"gear_name": row["gear_name"], "distance_km": float(row["distance_km"])} for _, row in grouped.iterrows()]


def compute_long_run_flags(acts: pd.DataFrame) -> pd.DataFrame:
    """Return weekly DataFrame with is_long_run flag and long_run_distance."""
    empty_cols = ["week_start", "distance_km", "is_long_run", "long_run_distance"]
    if acts.empty:
        return pd.DataFrame(columns=empty_cols)

    def week_stats(grp):
        total_dist = grp["distance_km"].sum()
        long_mask = (grp.get("workout_type") == 10) | (grp["distance_km"] >= 25)
        is_long = bool(long_mask.any())
        long_run_dist = grp.loc[long_mask, "distance_km"].max() if is_long else np.nan
        return pd.Series({
            "distance_km": total_dist,
            "is_long_run": is_long,
            "long_run_distance": long_run_dist,
        })

    weekly = acts.groupby("week").apply(week_stats).reset_index()
    weekly["week_start"] = weekly["week"].dt.start_time.dt.strftime("%Y-%m-%d")
    weekly = weekly.sort_values("week_start").reset_index(drop=True)
    return weekly[empty_cols]


def compute_cadence_trend(acts: pd.DataFrame, details: pd.DataFrame) -> pd.DataFrame:
    """Return weekly cadence + 4-week rolling average for Run/TrailRun activities."""
    empty_cols = ["week_start", "avg_cadence", "cadence_rolling"]
    if acts.empty or details.empty:
        return pd.DataFrame(columns=empty_cols)

    if "average_cadence" not in details.columns:
        return pd.DataFrame(columns=empty_cols)

    runs = acts[acts["sport_type"].isin(["Run", "TrailRun"])][["id", "week"]]
    merged = runs.merge(details[["id", "average_cadence"]], on="id", how="inner")
    merged = merged[merged["average_cadence"].notna()]
    if merged.empty:
        return pd.DataFrame(columns=empty_cols)

    # Normalise cadence: Strava stores as full steps/min (spm); some devices halve it
    median_cad = merged["average_cadence"].median()
    if median_cad < 110:
        merged["average_cadence"] = merged["average_cadence"] * 2

    weekly = merged.groupby("week")["average_cadence"].mean().reset_index()
    weekly = weekly.rename(columns={"average_cadence": "avg_cadence"})
    weekly = weekly.sort_values("week")
    weekly["cadence_rolling"] = weekly["avg_cadence"].rolling(4, min_periods=1).mean()
    weekly["week_start"] = weekly["week"].dt.start_time.dt.strftime("%Y-%m-%d")
    weekly = weekly.dropna(subset=["avg_cadence"])
    return weekly[empty_cols].reset_index(drop=True)


def compute_decoupling_factor(drift_df: pd.DataFrame, acts: pd.DataFrame) -> pd.DataFrame:
    """Compute cardiac drift % per activity with 20-activity rolling average."""
    empty_cols = ["activity_id", "date", "decoupling_pct", "rolling_20"]
    if drift_df.empty or acts.empty:
        return pd.DataFrame(columns=empty_cols)

    df = drift_df.copy()
    df["decoupling_pct"] = (df["late_hr"] - df["early_hr"]) / df["early_hr"] * 100

    date_map = acts[["id", "start_date_local"]].copy()
    date_map["date"] = pd.to_datetime(date_map["start_date_local"]).dt.strftime("%Y-%m-%d")

    merged = df.merge(date_map[["id", "date"]], left_on="activity_id", right_on="id", how="left")
    merged = merged.sort_values("date").reset_index(drop=True)
    merged["rolling_20"] = merged["decoupling_pct"].rolling(20, min_periods=1).mean()

    merged["decoupling_pct"] = merged["decoupling_pct"].round(2)
    merged["rolling_20"] = merged["rolling_20"].round(2)
    return merged[empty_cols].reset_index(drop=True)


def compute_race_predictor(best_paces: dict) -> dict:
    """
    Riegel formula predictions for Half Marathon and Marathon.
    T2 = T1 * (D2/D1)^1.06
    Input: {distance_label: best_pace_min_per_km}
    Output: {label: predicted_pace_min_per_km}
    """
    distance_map = {
        "1 km": 1.0,
        "5 km": 5.0,
        "10 km": 10.0,
        "Half marathon": 21.0975,
        "Marathon": 42.195,
    }
    if not best_paces:
        return {}

    # Select best reference from 5k or 10k (lowest pace = fastest)
    ref_label = None
    ref_pace = None
    for label in ["5 km", "10 km"]:
        if label in best_paces and best_paces[label] is not None:
            pace = best_paces[label]
            if ref_pace is None or pace < ref_pace:
                ref_label = label
                ref_pace = pace

    if ref_label is None:
        return {}

    ref_dist = distance_map[ref_label]
    ref_time = ref_pace * ref_dist  # total minutes

    predictions = {}
    for label, dist in distance_map.items():
        if dist <= ref_dist:
            continue
        if label in best_paces:
            continue
        predicted_time = ref_time * (dist / ref_dist) ** 1.06
        predictions[label] = round(predicted_time / dist, 4)

    return predictions
