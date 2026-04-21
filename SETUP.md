# Setup Guide

A personal running analytics dashboard powered by Flask, Plotly.js, and [Keboola](https://www.keboola.com/) as the data source. Deployed on Vercel via GitHub.

---

## Prerequisites

- A **Keboola project** on a GCP stack (US East 4 by default — see [Stack URL](#stack-url) below if yours differs)
- Strava and Garmin data synced into Keboola Storage with the table structure described below
- A **GitHub account** and a **Vercel account** (both free tiers work)

---

## 1. Keboola Data Structure

The app expects the following tables in a bucket named `in.c-Garmin_full`:

| Table | Key columns |
|---|---|
| `activities` | `id`, `name`, `sport_type`, `distance`, `moving_time`, `elapsed_time`, `total_elevation_gain`, `start_date_local`, `average_speed`, `max_speed`, `average_heartrate`, `max_heartrate`, `elev_high`, `elev_low`, `trainer`, `commute`, `pr_count`, `workout_type`, `gear_id` |
| `activity_details` | `id`, `calories`, `average_cadence`, `average_watts`, `max_watts`, `weighted_average_watts`, `kilojoules`, `device_watts`, `has_heartrate`, `splits_metric`, `gear_name` |
| `streams` | `activity_id`, `time`, `heartrate`, `velocity_smooth`, `distance`, `grade_smooth`, `moving` |
| `garmin_heart_rate` | `calendarDate`, `restingHeartRate`, `maxHeartRate`, `lastSevenDaysAvgRestingHeartRate` |
| `garmin_heart_rate_intraday` | `date`, `heartRate`, `timestampGMT` |

> Data is typically populated by a Strava extractor and a Garmin extractor component in Keboola. The exact setup of those extractors is outside the scope of this guide.

---

## 2. Keboola Storage Token

1. In your Keboola project, go to **Settings → API Tokens**.
2. Create a new token with **read access** to the `in.c-Garmin_full` bucket.
3. Copy the token — you will need it in the next step.

---

## 3. Deploy to Vercel

### 3a. Fork the repository

Fork this repo to your own GitHub account.

### 3b. Create a new Vercel project

1. Go to [vercel.com](https://vercel.com) → **Add New Project**.
2. Import your forked GitHub repository.
3. Vercel will auto-detect the `vercel.json` configuration — no build settings need to be changed.

### 3c. Set environment variables

In **Vercel → Project → Settings → Environment Variables**, add:

| Variable | Required | Description |
|---|---|---|
| `KEBOOLA_STORAGE_TOKEN` | **yes** | Storage API token from step 2 |
| `KEBOOLA_STORAGE_URL` | no | Connection URL of your Keboola stack (see [Stack URL](#stack-url)). Defaults to `https://connection.us-east4.gcp.keboola.com` |
| `KEBOOLA_JOB_TOKEN` | no | Token used for the **Run sync** button. If omitted, falls back to `KEBOOLA_STORAGE_TOKEN`. Use a token with **write/run** permissions if you want the button to work. |
| `KEBOOLA_REFERENCE_JOB_ID` | no | Job ID of a previous successful sync run. Required only if you want the **Run sync** button to trigger a new data refresh. Find it in **Keboola → Jobs** — any past job ID from your Strava/Garmin sync flow will work. |

### 3d. Deploy

Click **Deploy**. Vercel will install dependencies from `requirements.txt` and start the Flask app automatically.

---

## Stack URL

If your Keboola project is not on the default GCP US East 4 stack, set `KEBOOLA_STORAGE_URL` accordingly:

| Stack | URL |
|---|---|
| GCP US East 4 *(default)* | `https://connection.us-east4.gcp.keboola.com` |
| GCP EU West 4 | `https://connection.europe-west4.gcp.keboola.com` |
| AWS US East 1 | `https://connection.keboola.com` |
| Azure EU North | `https://connection.north-europe.azure.keboola.com` |

You can confirm your stack URL in Keboola under **Settings → Project Info**.

---

## Local Development

```bash
# 1. Clone the repo
git clone https://github.com/your-username/Strava-JS.git
cd Strava-JS

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set environment variables
cp .env.example .env
# Edit .env and fill in your KEBOOLA_STORAGE_TOKEN (and optionally KEBOOLA_STORAGE_URL)

# 5. Start the development server
flask --app app run --debug
```

Open [http://localhost:5000](http://localhost:5000).

> On first load the app fetches all tables from Keboola Storage. Depending on data size this takes 15–60 seconds. Subsequent requests within the same process are served from an in-memory cache.

---

## .env.example

Create a `.env` file in the project root (never commit it):

```
KEBOOLA_STORAGE_TOKEN=your-token-here
KEBOOLA_STORAGE_URL=https://connection.us-east4.gcp.keboola.com
KEBOOLA_JOB_TOKEN=
KEBOOLA_REFERENCE_JOB_ID=
```
