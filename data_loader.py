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


def _decompress(content: bytes) -> bytes:
    if content[:2] == b"\x1f\x8b":
        return gzip.decompress(content)
    return content


def _http_get(url: str, gcs_token: str | None = None) -> bytes:
    import requests
    headers = {"Authorization": f"Bearer {gcs_token}"} if gcs_token else {}
    resp = requests.get(url, headers=headers, timeout=180)
    resp.raise_for_status()
    return resp.content


def _gs_to_https(gs_url: str) -> str:
    """Convert gs://bucket/obj to https://storage.googleapis.com/download/... URL."""
    import urllib.parse
    path = gs_url[5:]          # strip 'gs://'
    bucket, obj = path.split("/", 1)
    return (
        f"https://storage.googleapis.com/download/storage/v1/b/"
        f"{bucket}/o/{urllib.parse.quote(obj, safe='')}?alt=media"
    )


def _get_gcs_token(credentials_info: dict) -> str:
    """Exchange a service-account JSON for a short-lived Bearer token."""
    from google.oauth2 import service_account
    import google.auth.transport.requests as google_requests

    creds = service_account.Credentials.from_service_account_info(
        credentials_info,
        scopes=["https://www.googleapis.com/auth/devstorage.read_only"],
    )
    creds.refresh(google_requests.Request())
    return creds.token


def _fetch_keboola_table(table_id: str) -> io.StringIO:
    import json
    import requests

    kbc_headers = {"X-StorageApi-Token": _KEBOOLA_STORAGE_TOKEN}

    # ── 1. Start async export ────────────────────────────────────────────────
    resp = requests.post(
        f"{_KEBOOLA_STORAGE_URL}/v2/storage/tables/{table_id}/export-async",
        headers=kbc_headers,
        timeout=30,
    )
    resp.raise_for_status()
    job_id = resp.json()["id"]

    # ── 2. Poll for job completion ───────────────────────────────────────────
    for _ in range(180):
        job = requests.get(
            f"{_KEBOOLA_STORAGE_URL}/v2/storage/jobs/{job_id}",
            headers=kbc_headers,
            timeout=10,
        ).json()
        if job["status"] == "success":
            break
        if job["status"] in ("error", "terminated"):
            raise RuntimeError(
                f"Keboola export failed: {job.get('error', {}).get('message', 'unknown')}"
            )
        time.sleep(1)
    else:
        raise RuntimeError("Keboola export timed out after 180 seconds")

    file_id = job["results"]["file"]["id"]

    # ── 3. Fetch file metadata + GCS federation token ────────────────────────
    file_meta = requests.get(
        f"{_KEBOOLA_STORAGE_URL}/v2/storage/files/{file_id}?federationToken=1",
        headers=kbc_headers,
        timeout=10,
    ).json()

    # Extract GCS service-account credentials from the federation token response
    gcs_token = None
    sa_info = (
        file_meta.get("gcsCredentials")
        or file_meta.get("uploadParams", {}).get("credentials")
    )
    if sa_info and isinstance(sa_info, dict) and sa_info.get("type") == "service_account":
        gcs_token = _get_gcs_token(sa_info)

    # ── 4. Resolve the manifest/data URL ────────────────────────────────────
    raw_url = file_meta.get("url") or file_meta.get("absPath")
    if not raw_url:
        raise RuntimeError(
            f"No download URL in file metadata. Keys: {list(file_meta.keys())}"
        )

    def fetch(url: str) -> bytes:
        if url.startswith("gs://"):
            return _http_get(_gs_to_https(url), gcs_token)
        return _http_get(url)

    raw = _decompress(fetch(raw_url))

    # ── 5. Handle sliced manifest ────────────────────────────────────────────
    # Keboola exports large tables as a JSON manifest listing gs:// slice paths.
    first_line = raw.split(b"\n", 1)[0].strip()
    if first_line.startswith(b"{") or first_line.startswith(b"["):
        try:
            manifest = json.loads(raw)
            entries = manifest if isinstance(manifest, list) else manifest.get("entries", [])
            slice_urls = [e["url"] for e in entries if e.get("url")]
        except Exception as exc:
            raise RuntimeError(f"Failed to parse manifest ({raw[:200]}): {exc}")
        if not slice_urls:
            raise RuntimeError(f"Manifest had no entries: {raw[:500]}")

        chunks: list[str] = []
        header: str | None = None
        for url in slice_urls:
            text = _decompress(fetch(url)).decode("utf-8")
            lines = text.splitlines()
            if not lines:
                continue
            if header is None:
                header = lines[0]
                chunks.append(text)
            else:
                # Skip repeated header rows from subsequent slices
                chunks.append("\n".join(lines[1:] if lines[0] == header else lines))
        return io.StringIO("\n".join(chunks))

    return io.StringIO(raw.decode("utf-8"))


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
