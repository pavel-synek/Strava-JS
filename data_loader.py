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

# BigQuery fully-qualified table names (GCP US stack)
_BQ_PROJECT = "kbc-use4-1566-d355"
_BQ_DATASET = "in_c_Garmin_full"

_KEBOOLA_TABLE_IDS = {
    "activities.csv":       f"{_KEBOOLA_BUCKET}.activities",
    "activity_details.csv": f"{_KEBOOLA_BUCKET}.activity_details",
}

_KEBOOLA_LOCAL_PATHS = {
    "activities.csv":        f"/data/in/tables/{_KEBOOLA_BUCKET}.activities.csv",
    "activity_details.csv":  f"/data/in/tables/{_KEBOOLA_BUCKET}.activity_details.csv",
    "streams.csv":           f"/data/in/tables/{_KEBOOLA_BUCKET}.streams.csv",
}

# Module-level cache for the GCS/BQ access token (valid ~1 hour)
_gcp_token_cache: dict = {"token": None, "expires_at": 0}


# ── GCS file download helpers ──────────────────────────────────────────────────

def _decompress(content: bytes) -> bytes:
    if content[:2] == b"\x1f\x8b":
        return gzip.decompress(content)
    return content


def _extract_gcs_token(file_meta: dict) -> str | None:
    """
    Extract a GCP Bearer token from Keboola's federationToken=1 response.
    On GCP stacks the response contains gcsCredentials.access_token directly.
    """
    gcs_creds = file_meta.get("gcsCredentials")
    if isinstance(gcs_creds, dict):
        if "access_token" in gcs_creds:
            return gcs_creds["access_token"]
        if gcs_creds.get("type") == "service_account":
            return _sa_to_token(gcs_creds)

    upload_params = file_meta.get("uploadParams") or {}
    sa = upload_params.get("credentials")
    if isinstance(sa, dict):
        if "access_token" in sa:
            return sa["access_token"]
        if sa.get("type") == "service_account":
            return _sa_to_token(sa)

    return None


def _sa_to_token(sa_info: dict) -> str:
    """Exchange service-account JSON for a short-lived Bearer token."""
    from google.oauth2 import service_account
    import google.auth.transport.requests as google_requests
    creds = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    creds.refresh(google_requests.Request())
    return creds.token


def _gs_to_https(gs_url: str) -> str:
    """Convert gs://bucket/obj → GCS JSON API download URL."""
    import urllib.parse
    path = gs_url[5:]
    bucket, obj = path.split("/", 1)
    return (
        f"https://storage.googleapis.com/download/storage/v1/b/"
        f"{bucket}/o/{urllib.parse.quote(obj, safe='')}?alt=media"
    )


def _http_get(url: str, token: str | None = None) -> bytes:
    import requests
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = requests.get(url, headers=headers, timeout=180)
    resp.raise_for_status()
    return resp.content


def _fetch_keboola_table(table_id: str) -> io.StringIO:
    """Download a Keboola table via async export → GCS signed download."""
    import json
    import requests

    kbc_headers = {"X-StorageApi-Token": _KEBOOLA_STORAGE_TOKEN}

    # 1. Start async export
    resp = requests.post(
        f"{_KEBOOLA_STORAGE_URL}/v2/storage/tables/{table_id}/export-async",
        headers=kbc_headers,
        timeout=30,
    )
    resp.raise_for_status()
    job_id = resp.json()["id"]

    # 2. Poll for completion
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

    # 3. Get file metadata + federation token (gives GCP access_token on GCP stacks)
    file_meta = requests.get(
        f"{_KEBOOLA_STORAGE_URL}/v2/storage/files/{file_id}?federationToken=1",
        headers=kbc_headers,
        timeout=10,
    ).json()

    gcp_token = _extract_gcs_token(file_meta)
    if gcp_token is None:
        gcs_creds = file_meta.get("gcsCredentials")
        raise RuntimeError(
            f"Cannot extract GCP access token from federation token response. "
            f"file_meta keys: {list(file_meta.keys())}, "
            f"gcsCredentials keys: {list(gcs_creds.keys()) if isinstance(gcs_creds, dict) else repr(gcs_creds)}"
        )

    # Cache the token for BigQuery queries
    _gcp_token_cache["token"] = gcp_token
    _gcp_token_cache["expires_at"] = time.time() + 3000  # ~50 min

    # 4. Resolve manifest/data URL
    raw_url = file_meta.get("url") or file_meta.get("absPath")
    if not raw_url:
        raise RuntimeError(f"No download URL in file_meta. Keys: {list(file_meta.keys())}")

    def fetch(url: str) -> bytes:
        if url.startswith("gs://"):
            return _http_get(_gs_to_https(url), gcp_token)
        return _http_get(url)

    raw = _decompress(fetch(raw_url))

    # 5. Handle sliced manifest
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
                chunks.append("\n".join(lines[1:] if lines[0] == header else lines))
        return io.StringIO("\n".join(chunks))

    return io.StringIO(raw.decode("utf-8"))


# ── BigQuery query helper ──────────────────────────────────────────────────────

def _bq_query(sql: str) -> pd.DataFrame:
    """
    Run a synchronous BigQuery query using the cached GCP access token.
    Works because Keboola's GCP federation token has cloud-platform scope.
    """
    import requests as req

    token = _gcp_token_cache.get("token")
    if not token or time.time() > _gcp_token_cache.get("expires_at", 0):
        # Trigger a small export to refresh the token
        _fetch_keboola_table(f"{_KEBOOLA_BUCKET}.activities")
        token = _gcp_token_cache.get("token")
        if not token:
            raise RuntimeError("Could not obtain GCP access token for BigQuery")

    url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{_BQ_PROJECT}/queries"
    resp = req.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": sql, "useLegacySql": False, "timeoutMs": 120000},
        timeout=130,
    )
    resp.raise_for_status()
    result = resp.json()

    if not result.get("jobComplete"):
        raise RuntimeError(f"BigQuery query did not complete in time. Response: {result}")

    schema = result.get("schema", {}).get("fields", [])
    if not schema:
        return pd.DataFrame()

    col_names = [f["name"] for f in schema]
    rows = [[cell.get("v") for cell in row["f"]] for row in result.get("rows", [])]
    return pd.DataFrame(rows, columns=col_names)


# ── Data loaders ───────────────────────────────────────────────────────────────

def _load_csv(filename: str, **kwargs) -> pd.DataFrame:
    if _KEBOOLA_STORAGE_TOKEN and filename in _KEBOOLA_TABLE_IDS:
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


def get_zone_summary(zones: dict) -> pd.DataFrame:
    """
    Compute seconds per HR zone per activity via BigQuery.
    Falls back to local streams.csv if running outside Vercel.
    """
    if _KEBOOLA_STORAGE_TOKEN:
        return _get_zone_summary_bq(zones)

    # Local fallback: read streams.csv
    streams = _load_streams_local()
    return _zone_summary_from_df(streams, zones)


def _get_zone_summary_bq(zones: dict) -> pd.DataFrame:
    zone_names = list(zones.keys())
    boundaries = [zones[z][0] for z in zone_names] + [zones[zone_names[-1]][1]]

    cases = "\n    ".join(
        f"COUNTIF(hr >= {boundaries[i]:.4f} AND hr < {boundaries[i+1]:.4f}) AS `{zone_names[i]}_sec`"
        for i in range(len(zone_names))
    )

    sql = f"""
    SELECT
        activity_id,
        {cases}
    FROM (
        SELECT
            activity_id,
            SAFE_CAST(heartrate AS FLOAT64) AS hr
        FROM `{_BQ_PROJECT}`.`{_BQ_DATASET}`.`streams`
        WHERE heartrate IS NOT NULL AND heartrate != ''
          AND SAFE_CAST(heartrate AS FLOAT64) > 0
    )
    GROUP BY activity_id
    """
    df = _bq_query(sql)
    if df.empty:
        return df
    df["activity_id"] = pd.to_numeric(df["activity_id"], errors="coerce")
    for col in df.columns:
        if col.endswith("_sec"):
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    return df


def get_all_hr_drift() -> pd.DataFrame:
    """
    Compute early/late HR per activity via BigQuery.
    Falls back to local streams.csv if running outside Vercel.
    """
    if _KEBOOLA_STORAGE_TOKEN:
        return _get_hr_drift_bq()

    streams = _load_streams_local()
    return _hr_drift_from_df(streams)


def _get_hr_drift_bq() -> pd.DataFrame:
    sql = f"""
    WITH numbered AS (
        SELECT
            activity_id,
            SAFE_CAST(heartrate AS FLOAT64) AS hr,
            ROW_NUMBER() OVER (PARTITION BY activity_id ORDER BY SAFE_CAST(time AS INT64)) AS rn,
            COUNT(*) OVER (PARTITION BY activity_id) AS total
        FROM `{_BQ_PROJECT}`.`{_BQ_DATASET}`.`streams`
        WHERE heartrate IS NOT NULL AND heartrate != ''
          AND SAFE_CAST(heartrate AS FLOAT64) > 0
          AND moving = 'True'
    ),
    counts AS (
        SELECT activity_id, COUNT(*) AS n FROM numbered GROUP BY activity_id
    )
    SELECT
        n.activity_id,
        AVG(IF(n.rn <= FLOOR(c.n * 0.2), n.hr, NULL)) AS early_hr,
        AVG(IF(n.rn >  FLOOR(c.n * 0.8), n.hr, NULL)) AS late_hr
    FROM numbered n
    JOIN counts c USING (activity_id)
    WHERE c.n >= 20
    GROUP BY n.activity_id
    HAVING early_hr IS NOT NULL AND late_hr IS NOT NULL
    """
    df = _bq_query(sql)
    if df.empty:
        return df
    df["activity_id"] = pd.to_numeric(df["activity_id"], errors="coerce")
    df["early_hr"] = pd.to_numeric(df["early_hr"], errors="coerce")
    df["late_hr"] = pd.to_numeric(df["late_hr"], errors="coerce")
    return df.dropna(subset=["early_hr", "late_hr"])


# ── Local fallback (Keboola Data App / local dev with streams.csv) ─────────────

@functools.lru_cache(maxsize=1)
def _load_streams_local() -> pd.DataFrame:
    cols = ["activity_id", "time", "heartrate", "velocity_smooth", "distance", "grade_smooth", "moving"]
    dtypes = {
        "activity_id": "int64",
        "time": "int32",
        "heartrate": "float32",
        "velocity_smooth": "float32",
        "distance": "float32",
        "grade_smooth": "float32",
    }
    keboola_path = _KEBOOLA_LOCAL_PATHS["streams.csv"]
    if os.path.exists(keboola_path):
        path = keboola_path
    else:
        path = os.path.join(os.path.dirname(__file__), "..", "streams.csv")
    df = pd.read_csv(path, usecols=cols, dtype=dtypes, low_memory=False)
    if df["moving"].dtype == object:
        df["moving"] = df["moving"].map({"True": True, "False": False, True: True, False: False})
    df["heartrate_valid"] = df["heartrate"].notna() & (df["heartrate"] > 0)
    return df


def _zone_summary_from_df(streams: pd.DataFrame, zones: dict) -> pd.DataFrame:
    valid = streams[streams["heartrate_valid"]].copy()
    if valid.empty:
        return pd.DataFrame()
    zone_names = list(zones.keys())
    boundaries = [zones[z][0] for z in zone_names] + [zones[zone_names[-1]][1]]
    valid["zone"] = pd.cut(
        valid["heartrate"], bins=boundaries, labels=zone_names,
        right=False, include_lowest=True,
    )
    grouped = valid.groupby(["activity_id", "zone"], observed=True).size().unstack(fill_value=0)
    grouped.columns = [f"{c}_sec" for c in grouped.columns]
    return grouped.reset_index()


def _hr_drift_from_df(streams: pd.DataFrame) -> pd.DataFrame:
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
