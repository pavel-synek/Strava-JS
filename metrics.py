import json
import numpy as np
import pandas as pd


def compute_hr_zones(max_hr: float, model: str = "5zone") -> dict:
    if model == "3zone":
        boundaries = {"Easy": (0.0, 0.70), "Moderate": (0.70, 0.85), "Hard": (0.85, 1.01)}
    else:
        boundaries = {
            "Z1": (0.0, 0.60), "Z2": (0.60, 0.70), "Z3": (0.70, 0.80),
            "Z4": (0.80, 0.90), "Z5": (0.90, 1.01),
        }
    return {name: (lo * max_hr, hi * max_hr) for name, (lo, hi) in boundaries.items()}


def compute_trimp(acts: pd.DataFrame, resting_hr: float, max_hr: float) -> pd.Series:
    hr_range = max_hr - resting_hr
    if hr_range <= 0:
        return pd.Series(np.nan, index=acts.index)
    hr_ratio = (acts["average_heartrate"] - resting_hr) / hr_range
    hr_ratio = hr_ratio.clip(0.01, 1.0)
    trimp = acts["moving_time_min"] * hr_ratio * 0.64 * np.exp(1.92 * hr_ratio)
    return trimp.where(acts["average_heartrate"].notna())


def make_daily_trimp(acts: pd.DataFrame, resting_hr: float, max_hr: float) -> pd.Series:
    acts2 = acts.copy()
    acts2["trimp"] = compute_trimp(acts, resting_hr, max_hr)
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
