import os
import functools
import pandas as pd


_KEBOOLA_BUCKET = "in.c-Garmin_full"

_KEBOOLA_TABLES = {
    "activities.csv":        f"/data/in/tables/{_KEBOOLA_BUCKET}.activities.csv",
    "activity_details.csv":  f"/data/in/tables/{_KEBOOLA_BUCKET}.activity_details.csv",
    "streams.csv":           f"/data/in/tables/{_KEBOOLA_BUCKET}.streams.csv",
}


def get_data_path(filename: str) -> str:
    keboola_path = _KEBOOLA_TABLES.get(filename)
    if keboola_path and os.path.exists(keboola_path):
        return keboola_path
    # Local fallback: CSVs live one level up (strava_output/)
    return os.path.join(os.path.dirname(__file__), "..", filename)


def _clean_sport_type(series: pd.Series) -> pd.Series:
    extracted = series.str.extract(r"root='(.+)'", expand=False)
    return extracted.where(extracted.notna(), series)


@functools.lru_cache(maxsize=1)
def load_activities() -> pd.DataFrame:
    cols = [
        "id", "name", "sport_type", "distance", "moving_time", "elapsed_time",
        "total_elevation_gain", "start_date_local", "average_speed", "max_speed",
        "average_heartrate", "max_heartrate", "elev_high", "elev_low",
        "trainer", "commute", "pr_count", "workout_type", "gear_id",
    ]
    df = pd.read_csv(get_data_path("activities.csv"), usecols=cols, low_memory=False)
    df["sport_type"] = _clean_sport_type(df["sport_type"])
    df["start_date_local"] = pd.to_datetime(df["start_date_local"], utc=True).dt.tz_convert("Europe/Prague")
    df["date"] = df["start_date_local"].dt.date
    local_naive = df["start_date_local"].dt.tz_localize(None)
    df["week"] = local_naive.dt.to_period("W")
    df["month"] = local_naive.dt.to_period("M")
    df["year"] = df["start_date_local"].dt.year
    df["distance_km"] = df["distance"] / 1000
    df["moving_time_min"] = df["moving_time"] / 60
    df["pace_min_per_km"] = df.apply(
        lambda r: r["moving_time"] / 60 / (r["distance"] / 1000) if r["distance"] > 0 else None,
        axis=1,
    )
    df["average_heartrate"] = df["average_heartrate"].astype("float32")
    df["max_heartrate"] = df["max_heartrate"].astype("float32")
    return df


@functools.lru_cache(maxsize=1)
def load_activity_details() -> pd.DataFrame:
    cols = [
        "id", "calories", "average_cadence", "average_watts", "max_watts",
        "weighted_average_watts", "kilojoules", "device_watts", "has_heartrate",
        "splits_metric", "gear_name",
    ]
    available = pd.read_csv(get_data_path("activity_details.csv"), nrows=0).columns.tolist()
    load_cols = [c for c in cols if c in available]
    return pd.read_csv(get_data_path("activity_details.csv"), usecols=load_cols, low_memory=False)


@functools.lru_cache(maxsize=1)
def load_streams() -> pd.DataFrame:
    cols = ["activity_id", "time", "heartrate", "velocity_smooth", "distance", "grade_smooth", "moving"]
    dtypes = {
        "activity_id": "int64",
        "time": "int32",
        "heartrate": "float32",
        "velocity_smooth": "float32",
        "distance": "float32",
        "grade_smooth": "float32",
    }
    df = pd.read_csv(get_data_path("streams.csv"), usecols=cols, dtype=dtypes, low_memory=False)
    if df["moving"].dtype == object:
        df["moving"] = df["moving"].map({"True": True, "False": False, True: True, False: False})
    df["heartrate_valid"] = df["heartrate"].notna() & (df["heartrate"] > 0)
    return df


def get_zone_summary(zones: dict) -> pd.DataFrame:
    streams = load_streams()
    valid = streams[streams["heartrate_valid"]].copy()
    if valid.empty:
        return pd.DataFrame()
    zone_names = list(zones.keys())
    boundaries = [zones[z][0] for z in zone_names] + [zones[zone_names[-1]][1]]
    valid["zone"] = pd.cut(valid["heartrate"], bins=boundaries, labels=zone_names, right=False, include_lowest=True)
    grouped = valid.groupby(["activity_id", "zone"], observed=True).size().unstack(fill_value=0)
    grouped.columns = [f"{c}_sec" for c in grouped.columns]
    return grouped.reset_index()


def get_all_hr_drift() -> pd.DataFrame:
    streams = load_streams()
    results = []
    for activity_id, grp in streams[streams["heartrate_valid"]].groupby("activity_id"):
        moving = grp[grp["moving"] == True]
        n = len(moving)
        if n < 20:
            continue
        cutoff = max(1, int(n * 0.2))
        results.append({
            "activity_id": activity_id,
            "early_hr": float(moving.iloc[:cutoff]["heartrate"].mean()),
            "late_hr": float(moving.iloc[-cutoff:]["heartrate"].mean()),
        })
    return pd.DataFrame(results)
