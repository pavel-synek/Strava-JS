import gzip
import io
import os
import time
import functools
import pandas as pd


_KEBOOLA_BUCKET = "in.c-Garmin_full"
_KEBOOLA_STORAGE_URL = os.environ.get(
    "KEBOOLA_STORAGE_URL", "https://connection.us-east4.gcp.keboola.com"
)
_KEBOOLA_STORAGE_TOKEN = os.environ.get("KEBOOLA_STORAGE_TOKEN")

_KEBOOLA_TABLE_IDS = {
    "activities.csv":       f"{_KEBOOLA_BUCKET}.activities",
    "activity_details.csv": f"{_KEBOOLA_BUCKET}.activity_details",
    "streams.csv":          f"{_KEBOOLA_BUCKET}.streams",
}

_KEBOOLA_LOCAL_PATHS = {
    "activities.csv":        f"/data/in/tables/{_KEBOOLA_BUCKET}.activities.csv",
    "activity_details.csv":  f"/data/in/tables/{_KEBOOLA_BUCKET}.activity_details.csv",
    "streams.csv":           f"/data/in/tables/{_KEBOOLA_BUCKET}.streams.csv",
}


def _fetch_keboola_table(table_id: str) -> io.StringIO:
    import requests

    headers = {"X-StorageApi-Token": _KEBOOLA_STORAGE_TOKEN}

    resp = requests.post(
        f"{_KEBOOLA_STORAGE_URL}/v2/storage/tables/{table_id}/export-async",
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    job_id = resp.json()["id"]

    for _ in range(180):
        job_resp = requests.get(
            f"{_KEBOOLA_STORAGE_URL}/v2/storage/jobs/{job_id}",
            headers=headers,
            timeout=10,
        )
        job = job_resp.json()
        if job["status"] == "success":
            break
        elif job["status"] in ("error", "terminated"):
            raise RuntimeError(
                f"Keboola export failed: {job.get('error', {}).get('message', 'unknown')}"
            )
        time.sleep(1)
    else:
        raise RuntimeError("Keboola export timed out after 180 seconds")

    file_info = job["results"]["file"]
    file_id = file_info.get("id")

    # The job result contains only the file ID; fetch the signed download URL separately
    file_meta_resp = requests.get(
        f"{_KEBOOLA_STORAGE_URL}/v2/storage/files/{file_id}",
        headers=headers,
        timeout=10,
    )
    file_meta_resp.raise_for_status()
    file_meta = file_meta_resp.json()
    download_url = file_meta.get("url") or file_meta.get("absPath")
    if not download_url:
        raise RuntimeError(
            f"No download URL in file metadata. Keys present: {list(file_meta.keys())}"
        )

    csv_resp = requests.get(download_url, timeout=180)
    csv_resp.raise_for_status()

    content = csv_resp.content
    file_name = file_meta.get("name", file_info.get("name", ""))
    if file_name.endswith(".gz") or content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)

    return io.StringIO(content.decode("utf-8"))


def _load_csv(filename: str, **kwargs) -> pd.DataFrame:
    if _KEBOOLA_STORAGE_TOKEN:
        table_id = _KEBOOLA_TABLE_IDS[filename]
        return pd.read_csv(_fetch_keboola_table(table_id), **kwargs)
    keboola_path = _KEBOOLA_LOCAL_PATHS.get(filename)
    if keboola_path and os.path.exists(keboola_path):
        return pd.read_csv(keboola_path, **kwargs)
    local_path = os.path.join(os.path.dirname(__file__), "..", filename)
    return pd.read_csv(local_path, **kwargs)


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
    df = _load_csv("activities.csv", usecols=cols, low_memory=False)
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
    df = _load_csv("activity_details.csv", low_memory=False)
    load_cols = [c for c in cols if c in df.columns]
    return df[load_cols]


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
    df = _load_csv("streams.csv", usecols=cols, dtype=dtypes, low_memory=False)
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
