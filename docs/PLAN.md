# Strava-JS Dashboard Improvements Plan

Wave 1 + Wave 2 metric enhancements for the running dashboard.

<!-- PHASE:1 -->
## Phase 1: Backend Metrics Functions

### Branch
`phase-1-backend-metrics`

### Scope
Add all new compute functions to `metrics.py`. No changes to `app.py` or frontend yet.

Functions to add:
1. `compute_acwr(form_df)` — returns Series of ATL/CTL ratio (clamp CTL >= 1.0)
2. `compute_weekly_ramp_rate(acts)` — returns DataFrame with week_start and ramp_rate (% week-over-week distance change)
3. `compute_gear_mileage(acts, details)` — group by gear_name, sum distance_km; returns list of dicts
4. `compute_long_run_flags(acts)` — returns weekly DataFrame with is_long_run bool (workout_type==10 OR distance_km>=25), long_run_distance
5. `compute_cadence_trend(acts, details)` — merge on id, group by week, return weekly avg cadence + 4-week rolling avg
6. `compute_decoupling_factor(drift_df, acts)` — cardiac drift % = (late_hr - early_hr) / early_hr * 100; per-activity with 20-run rolling average
7. `compute_race_predictor(best_paces)` — Riegel formula T2=T1*(D2/D1)^1.06; returns predictions dict

### Files to Create/Modify
- `metrics.py` — add 7 new functions

### Acceptance Criteria
- [ ] `compute_acwr` returns a pd.Series with float values, CTL clamped to minimum 1.0 to prevent division by zero
- [ ] `compute_weekly_ramp_rate` returns DataFrame with columns `week_start` (str YYYY-MM-DD) and `ramp_rate` (float %, NaN for first week)
- [ ] `compute_gear_mileage` returns list of dicts with keys `gear_name`, `distance_km`; sorted by distance_km descending; handles missing gear_name gracefully
- [ ] `compute_long_run_flags` returns DataFrame with columns `week_start`, `distance_km`, `is_long_run` (bool), `long_run_distance` (float, NaN if no long run that week)
- [ ] `compute_cadence_trend` returns DataFrame with columns `week_start`, `avg_cadence`, `cadence_rolling`; returns empty DataFrame if average_cadence column is missing in details
- [ ] `compute_decoupling_factor` returns DataFrame with columns `activity_id`, `date`, `decoupling_pct`, `rolling_20`; formula uses (late_hr - early_hr) / early_hr * 100; returns empty DataFrame if inputs are empty
- [ ] `compute_race_predictor` takes a dict of {distance_label: best_pace_min_per_km}, applies Riegel, returns predictions dict; handles missing 5k/10k data (returns empty dict)
- [ ] All functions handle empty DataFrames gracefully without raising exceptions

### Tests Required
None required (no test infrastructure in this project). Manual verification via the API endpoint in Phase 2.
<!-- /PHASE:1 -->

<!-- PHASE:2 -->
## Phase 2: API Endpoint Extensions

### Branch
`phase-2-api-extensions`

### Scope
Extend all 4 relevant Flask endpoints in `app.py` to include new metrics in their JSON responses. Import new functions from metrics.py.

Changes:
1. `api_overview()` → add `gear_mileage` key (list) from `compute_gear_mileage(acts, load_activity_details())`
2. `api_fitness()` → add `acwr` dict: `{current_value, series: {dates, values}}` from `compute_acwr(form_df)`
3. `api_hr_zones()` → add `cadence_weekly` dict: `{dates, avg_cadence, cadence_rolling}` and `decoupling_factor` dict: `{dates, decoupling_pct, rolling_20}`
4. `api_pacing()` → add `race_history` dict (filtered workout_type==1 runs grouped by distance bracket) and `predictions` dict from `compute_race_predictor`
5. `api_periodization()` → add `ramp_rate` dict: `{weeks, ramp_rate}` and `long_runs` dict: `{weeks, is_long_run, long_run_distance}`

### Files to Create/Modify
- `app.py` — extend 4 endpoints + update imports

### Acceptance Criteria
- [ ] `GET /api/overview` response includes `gear_mileage` key (list of objects with gear_name, distance_km); empty list if no gear data
- [ ] `GET /api/fitness` response includes `acwr` key with `current_value` (float or null) and `series.dates` + `series.values` arrays
- [ ] `GET /api/hr-zones` response includes `cadence_weekly` key (dict with dates/avg_cadence/cadence_rolling arrays) and `decoupling_factor` key (dict with dates/decoupling_pct/rolling_20 arrays)
- [ ] `GET /api/pacing` response includes `race_history` key (dict by distance bracket with dates+pace arrays) and `predictions` key (dict with predicted paces as floats)
- [ ] `GET /api/periodization` response includes `ramp_rate` key (dict with weeks/ramp_rate arrays) and `long_runs` key (dict with weeks/is_long_run/long_run_distance arrays)
- [ ] Flask app starts without errors: `python app.py`
- [ ] All new response keys return valid JSON (no NaN, no Infinity — use existing `_sanitize()` via `jsonify`)
- [ ] Exceptions from new metric computations are caught silently (same pattern as existing `hr_recovery` try/except blocks)

### Tests Required
None required. Manual: `python app.py` then curl each endpoint.
<!-- /PHASE:2 -->

<!-- PHASE:3 -->
## Phase 3: Frontend Wave 1 — Tab 1, 3, 4, 5

### Branch
`phase-3-frontend-wave1`

### Scope
Add frontend visualizations for: Shoe Mileage (Tab 1), ACWR (Tab 3), Race History + Race Predictor (Tab 4), Ramp Rate + Long Run flags (Tab 5).

Dark theme: background `#1a1f2e`, text `#e0e0e0`. Follow existing Plotly patterns (PLOTLY_LAYOUT, PLOTLY_CONFIG, kpiCard helper from main.js).

Changes:
1. Tab 1 (overview.js + index.html): add `chart-gear` div + horizontal bar chart for shoe mileage with 700km reference line
2. Tab 3 (fitness.js + index.html): add ACWR KPI card + `chart-acwr` div with ACWR time series + colored risk bands
3. Tab 4 (pacing.js + index.html): add `chart-race-history` div + race history scatter + `race-predictor-block` div with HTML predictions table
4. Tab 5 (periodization.js + index.html): add `chart-ramp-rate` div + ramp rate chart; update weekly chart to highlight long-run weeks

### Files to Create/Modify
- `templates/index.html` — add new chart divs in tabs 1, 3, 4, 5
- `static/js/overview.js` — add gear mileage chart
- `static/js/fitness.js` — add ACWR KPI card + ACWR chart
- `static/js/pacing.js` — add race history chart + predictor table
- `static/js/periodization.js` — add ramp rate chart + highlight long-run weeks in weekly chart

### Acceptance Criteria
- [ ] Shoe mileage horizontal bar chart renders in Tab 1 with shoes sorted descending by distance; red reference line at 700 km; chart hidden gracefully if `data.gear_mileage` is empty array
- [ ] ACWR KPI card in Tab 3 shows current value colored correctly (green <1.3, orange 1.3-1.5, red >=1.5); shows "—" if no ACWR data
- [ ] ACWR chart in Tab 3 shows ACWR time series line with 3 colored background band shapes; hidden if no series data
- [ ] Race history scatter in Tab 4 shows race dots over time with different color per distance bracket; hidden if no race_history data
- [ ] Predictions table in Tab 4 renders as HTML table showing distance + predicted pace (MM:SS/km format); hidden if predictions is empty
- [ ] Ramp rate chart in Tab 5 shows bars colored red (>10%) or green (<=10%); reference annotation at 10%; hidden if no ramp_rate data
- [ ] Weekly volume chart in Tab 5 highlights long-run weeks in a distinct color (e.g. `#8e44ad` vs normal `#1abc9c`)
- [ ] No JavaScript console errors when data arrays are empty (all array accesses guarded)
- [ ] All new chart divs in index.html have unique IDs matching the JS render targets

### Tests Required
None required. Manual: open http://localhost:5000 and verify tabs 1, 3, 4, 5 render new charts.
<!-- /PHASE:3 -->

<!-- PHASE:4 -->
## Phase 4: Frontend Wave 2 — Tab 2 (HR Zones)

### Branch
`phase-4-frontend-wave2`

### Scope
Add cadence tracking chart and decoupling factor chart to Tab 2. Also render the HR Recovery chart if not already done (check existing hr_zones.js first).

Changes to hr_zones.js + index.html:
1. Add `chart-cadence` div — weekly cadence scatter + rolling line + reference band 170-180 spm
2. Add `chart-decoupling` div — decoupling % scatter + rolling line + reference line at 5%; points green <5%, red >=5%
3. Check if `data.hr_recovery` is already visualized — if not, add `chart-hr-recovery` div with 1-min/2-min recovery bars + rolling average + 12 bpm reference line

### Files to Create/Modify
- `templates/index.html` — add `chart-cadence`, `chart-decoupling` divs in `#tab-hr-zones`; optionally `chart-hr-recovery`
- `static/js/hr_zones.js` — add cadence chart, decoupling chart, optionally HR recovery chart

### Acceptance Criteria
- [ ] Cadence chart renders in Tab 2 with weekly avg scatter dots and 4-week rolling line; reference band/lines at 170 and 180 spm; chart hidden if cadence_weekly data is empty
- [ ] Decoupling factor chart renders in Tab 2 as scatter (colored green <5%, red >=5%) + rolling line; dashed reference line at 5% labeled "Aerobic threshold"; hidden if decoupling_factor data is empty
- [ ] Chart captions explain what the metrics mean (1-2 sentences visible below the chart heading)
- [ ] If HR recovery was not previously rendered: chart shows 1-min recovery as bar chart over time, rolling 20-run average as line, reference line at 12 bpm; hidden if hr_recovery is empty array
- [ ] No JavaScript console errors on Tab 2 load
- [ ] All new chart divs in index.html have unique IDs matching JS targets

### Tests Required
None required. Manual: open Tab 2 in browser after starting `python app.py`.
<!-- /PHASE:4 -->
