# Strava Training Dashboard — Technická dokumentace

## Obsah
1. [Architektura aplikace](#1-architektura-aplikace)
2. [Datové tabulky](#2-datové-tabulky)
3. [Výpočty metrik](#3-výpočty-metrik)
4. [Grafy a vizualizace](#4-grafy-a-vizualizace)
5. [Struktura záložek](#5-struktura-záložek)
6. [Filtrování a datové rozsahy](#6-filtrování-a-datové-rozsahy)
7. [API endpointy](#7-api-endpointy)
8. [Klíčové konstanty](#8-klíčové-konstanty)
9. [Závislosti](#9-závislosti)

---

## 1. Architektura aplikace

**Typ:** Flask Python web aplikace s Plotly.js frontendem

| Vrstva | Technologie | Popis |
|--------|-------------|-------|
| Backend | Flask REST API | JSON endpointy, výpočty metrik (`app.py`) |
| Frontend | Vanilla JS + Plotly.js 2.32.0 | Single-page aplikace, interaktivní grafy |
| Datový zdroj | Keboola + GCS/BigQuery | Cloud storage, lokální CSV fallback |
| Deployment | Vercel | Serverless funkce |
| Časová zóna | `Europe/Prague` | Všechny datetime konverze |

**Tok dat:**
```
Strava API → Keboola (in.c-Garmin_full) → GCS federation token → pandas DataFrame → Flask JSON → Plotly.js
```

**BigQuery fallback:** Streams data se agregují přes BigQuery při dostupnosti Keboola tokenu, jinak se stáhne celý `streams.csv`.

---

## 2. Datové tabulky

### Bucket: `in.c-Garmin_full`

| Tabulka | Zdroj dat | Použití |
|---------|-----------|---------|
| `activities` | Strava API | Hlavní log aktivit s výkonnostními metrikami |
| `activity_details` | Strava API | Podrobnosti: výkon, kadence, zařízení, splity |
| `streams` | Strava API | Time series: tepová frekvence, rychlost, grade |

---

### 2.1 Tabulka `activities`

| Sloupec | Typ | Popis |
|---------|-----|-------|
| `id` | int64 | Unikátní identifikátor aktivity |
| `name` | string | Název aktivity |
| `sport_type` | string | Run, TrailRun, VirtualRun, Ride, Walk, Hike |
| `distance` | float | Vzdálenost v metrech |
| `distance_km` | float | **COMPUTED:** `distance / 1000` |
| `moving_time` | int | Sekund v pohybu |
| `moving_time_min` | float | **COMPUTED:** `moving_time / 60` |
| `elapsed_time` | int | Celkový čas v sekundách |
| `total_elevation_gain` | float | Převýšení v metrech |
| `start_date_local` | datetime | Začátek aktivity (Europe/Prague TZ) |
| `date` | date | **COMPUTED:** `start_date_local.date()` |
| `week` | period[W] | **COMPUTED:** ISO týdenní perioda |
| `month` | period[M] | **COMPUTED:** Měsíční perioda |
| `year` | int | **COMPUTED:** Rok z `start_date_local` |
| `average_speed` | float | m/s (konvertováno z km/h) |
| `max_speed` | float | m/s |
| `average_heartrate` | float32 | TF v bpm (null pro aktivity bez HR) |
| `max_heartrate` | float32 | Maximální TF v bpm |
| `pace_min_per_km` | float | **COMPUTED:** `(moving_time / 60) / (distance / 1000)` |
| `elev_high` | float | Nejvyšší bod v metrech |
| `elev_low` | float | Nejnižší bod v metrech |
| `trainer` | bool | Příznak indoor trenažéru |
| `commute` | bool | Příznak dojíždění |
| `pr_count` | int | Počet personal records v aktivitě |
| `workout_type` | int | 0 = normální, 1 = závod, 10 = long run |
| `gear_id` | string | Identifikátor vybavení/bot |

---

### 2.2 Tabulka `activity_details`

| Sloupec | Typ | Popis |
|---------|-----|-------|
| `id` | int64 | FK → `activities.id` |
| `calories` | float | Odhadovaná spotřeba kalorií |
| `average_cadence` | float | Kadence běhu (kroky/min) |
| `average_watts` | float | Výkon (cyklistika) |
| `max_watts` | float | Špičkový výkon |
| `weighted_average_watts` | float | Normalizovaný výkon |
| `kilojoules` | float | Energie v kJ |
| `device_watts` | bool | Výkon ze zařízení (vs. odhad) |
| `has_heartrate` | bool | Přítomnost HR senzoru |
| `splits_metric` | JSON string | Per-km splitová data (parsováno jako DF) |
| `gear_name` | string | Popis vybavení |

**Struktura splits_metric JSON:**
```json
[
  {"distance": 1000, "elapsed_time": 305, "average_speed": 3.28, "distance_km": 1.0},
  ...
]
```

---

### 2.3 Tabulka `streams` (time series)

| Sloupec | Typ | Popis |
|---------|-----|-------|
| `activity_id` | int64 | FK → `activities.id` |
| `time` | int32 | Sekund od začátku aktivity |
| `heartrate` | float32 | TF v bpm (null/0 pro aktivity bez HR) |
| `velocity_smooth` | float32 | Vyhlazená rychlost m/s |
| `distance` | float32 | Kumulativní vzdálenost v metrech |
| `grade_smooth` | float32 | Vyhlazený sklon v % |
| `moving` | bool | Zda byl atlet v pohybu |

---

## 3. Výpočty metrik

### 3.1 Model srdečních zón (Karvonova metoda)

**Základní vzorec:**
```
HR_reserve = max_hr - resting_hr
Zone_min = (intensity_min% × HR_reserve) + resting_hr
Zone_max = (intensity_max% × HR_reserve) + resting_hr
```

**5-zónový model (výchozí):**

| Zóna | Rozsah intenzity | Příklad (Max=179, Klid=45) | Účel |
|------|-----------------|----------------------------|------|
| Z1 | 0–60 % | 45–125 bpm | Regenerace / velmi lehká |
| Z2 | 60–70 % | 125–139 bpm | Aerobní základ |
| Z3 | 70–80 % | 139–152 bpm | Tempo / prahová |
| Z4 | 80–90 % | 152–166 bpm | Intervalová práce |
| Z5 | 90–101 % | 166–179+ bpm | VO2 max / sprint |

**3-zónový model:**

| Zóna | Rozsah | Účel |
|------|--------|------|
| Easy | 0–70 % | Regenerace |
| Moderate | 70–85 % | Steady state |
| Hard | 85–101 % | Tvrdé úsilí |

---

### 3.2 TRIMP (Training Impulse)

**Vzorec per aktivita:**
```
HR_ratio = (average_heartrate - resting_hr) / (max_hr - resting_hr)
HR_ratio = clip([0.01, 1.0])
TRIMP = moving_time_min × HR_ratio × 0.64 × exp(1.92 × HR_ratio)
```

**Parametry:**
- `0.64` — empirická konstanta (gender/fitness, Foster et al. 1995)
- `1.92` — exponenciální váha intenzity TF
- Jen aktivity s `average_heartrate > 0`

**Denní TRIMP:**
```
daily_trimp[datum] = sum(TRIMP pro všechny aktivity daného dne)
```

---

### 3.3 Fitness Tracker — CTL / ATL / TSB

**CTL (Chronic Training Load)** — tréninkový základ / fitness:
```
CTL[t] = EMA(daily_trimp, span=42)   ← exponenciální klouzavý průměr, poloperioda 42 dní
```

**ATL (Acute Training Load)** — únava:
```
ATL[t] = EMA(daily_trimp, span=7)    ← exponenciální klouzavý průměr, poloperioda 7 dní
```

**TSB (Training Stress Balance)** — forma:
```
TSB[t] = CTL[t] - ATL[t]
```

**Interpretace TSB:**

| TSB hodnota | Stav | Doporučení |
|-------------|------|------------|
| ≥ +5 | "Fresh" — svěžest | Vhodné pro závodní výkon |
| −10 až +5 | "Neutral" | Normální stav |
| ≤ −10 | "Fatigued" — únava | Nutná regenerace |

---

### 3.4 Aerobní efektivita (AE)

**Vzorec per aktivita:**
```
elev_gain = total_elevation_gain (min 0)
effective_distance_m = (distance_km × 1000) + (elev_gain × 7)
adjusted_speed = effective_distance_m / moving_time  [m/s]
ae = adjusted_speed / average_heartrate
```

**Kde:**
- `7` — koeficient ekvivalence převýšení (Minetti biomechanika: 1 m převýšení ≈ 7 m roviny)
- Jen běhy s `average_heartrate > 0`

**Agregace:**
- Týdenní průměr: `ae_mean = mean(ae) per week`
- 4-týdenní rolling průměr: `ae_rolling = rolling(ae_mean, window=4)`

> **Vyšší AE = lepší forma** (vyšší rychlost při stejné TF)

---

### 3.5 GAP (Grade-Adjusted Pace)

**Vzorec per aktivita:**
```
elev_gain = total_elevation_gain (min 0)
effective_distance_m = (distance_km × 1000) + (elev_gain × 7)
adj_speed = effective_distance_m / moving_time  [m/s]
gap_pace = 1000 / adj_speed / 60  [min/km]
```

**Filtry:**
- Platný jen pokud `0 < gap_pace < 30` min/km
- `null` pokud `adj_speed <= 0`

> **Nižší GAP = rychlejší tempo** (kompenzováno převýšením)

---

### 3.6 Tréninková monotónnost

**Výpočet per týden (7-denní okno):**
```
roll_mean = rolling mean(daily_trimp, window=7)
roll_std  = rolling std(daily_trimp, window=7, min_periods=3)
monotony  = roll_mean / roll_std
```

**Interpretace:**

| Monotonnost | Stav | Riziko |
|-------------|------|--------|
| ≤ 1.5 | Normální variabilita | Nízké |
| 1.5–2.0 | Výstraha | Zvyšující se riziko zranění |
| > 2.0 | Riziko | Příliš repetitivní tréninkový stimul |

---

### 3.7 Pacing metriky

**Split difference (pro aktivity s 1km splity):**
```
first_half_pace  = 1000 / mean(velocity_smooth pro první 50 % splitů)
second_half_pace = 1000 / mean(velocity_smooth pro druhých 50 % splitů)
split_diff = second_half_pace - first_half_pace  [s/km]
```

**Interpretace:**
- **Záporný split_diff** — negativní split (rychlejší 2. polovina) = dobrý pacing
- **Kladný split_diff** — pozitivní split (pomalejší 2. polovina) = typická únava

**Konzistence pacingu:**
```
paces_per_km = 1000 / velocity_smooth pro každý split
pace_std = std(paces_per_km)  [s/km]
```

> **Nižší std = rovnoměrnější pacing**

---

### 3.8 HR Drift

**Výpočet per aktivita (≥ 20 pohyblivých vzorků):**
```
early_hr = avg(heartrate pro prvních 20 % moving vzorků)
late_hr  = avg(heartrate pro posledních 20 % moving vzorků)
hr_drift = late_hr - early_hr
```

**Kladný drift** = TF rostla během aktivity (únava, teplo)

---

### 3.9 Výpočet série (streak)

**Aktuální série:**
```python
active_dates = sorted unique dates of Run/TrailRun aktivit
current_streak = 0
check = dnes
while check.date() in active_dates:
    current_streak += 1
    check -= 1 den
```

**Nejdelší série:** Maximum po sobě jdoucích dní v celé historii.

---

### 3.10 ACWR (Acute:Chronic Workload Ratio)

**Vzorec:**
```
ACWR[t] = ATL[t] / CTL[t]
```

**Interpretace:**

| ACWR | Stav | Doporučení |
|------|------|------------|
| < 1.3 | Bezpečné | Normální tréninkový stimul |
| 1.3–1.5 | Opatrnost | Zvýšené riziko přetížení |
| > 1.5 | Riziko zranění | Redukovat objem/intenzitu |

---

### 3.11 Ramp rate

**Výpočet per týden:**
```
ramp_rate[týden] = (current_week_km - prev_week_km) / prev_week_km × 100  [%]
```

**Práh:** > 10 % = příliš rychlý nárůst (riziko zranění), zobrazeno červeně.

---

### 3.12 Kadence (Cadence Trend)

Průměrná kadence v krocích/min per týden z `activity_details.average_cadence`.

**Referenční pásmo:** 170–180 spm — pod touto hodnotou zvýšené riziko overstriding.

---

### 3.13 Aerobní decoupling (Aerobic Decoupling Factor)

**Vzorec per aktivita:**
```
early_ae  = adjusted_speed_first_half / avg_hr_first_half
late_ae   = adjusted_speed_second_half / avg_hr_second_half
decoupling = (early_ae - late_ae) / early_ae × 100  [%]
```

**Interpretace:** Pod 5 % = aerobní systém navázán (aktivita byla skutečně lehká).

---

### 3.14 Závodní prediktor (Race Predictor — Riegelův vzorec)

**Vzorec:**
```
T2 = T1 × (D2 / D1) ^ 1.06
```

kde `T1` je nejlepší tréninkový čas na vzdálenosti `D1`, `T2` je predikovaný čas pro závod `D2`.

Predikce se generují pro standardní závodní vzdálenosti: 5 km, 10 km, půlmaraton (21,097 km), maraton (42,195 km).

---

### 3.15 Maximální TF (výpočet z dat)

```python
valid_max_hrs = activities["max_heartrate"].dropna()
max_hr = int(valid_max_hrs.quantile(0.98))  # 98. percentil — filtruje outliers
```

---

## 4. Grafy a vizualizace

### Záložka 1: Overview

| Graf | Typ | Metrika |
|------|-----|---------|
| KPI Row | Textové karty | Počet aktivit, celková vzdálenost (km), převýšení (m), pohybový čas (h) + delty vs. předchozí období |
| Weekly Heatmap | Heatmapa | Vzdálenost per ISO týden, barevná intenzita (Greens colorscale) |
| Sport Distribution | Koláčový (donut) | Počet aktivit per sport_type |
| Monthly Bar | Dvojosý sloupcový | Vzdálenost (km, levá osa) + Převýšení (m, pravá osa) per měsíc |
| Streak Row | Textové karty | Aktuální série dní, nejdelší série, aktivní dny v roce |
| Shoe Mileage | Horizontální sloupcový | Celkové km per obuv · červeně ≥ 700 km (varování výměny) · přerušovaná linie 700 km |

---

### Záložka 2: HR Zones & Efficiency

| Graf | Typ | Metrika |
|------|-----|---------|
| Zone Definitions | HTML tabulka | Definice zón (bpm, %HRR) pro vybraný model |
| Rolling Time in Zones | Stackovaná plocha | % tréninkového času per zóna (okno 30/90/365 dní) |
| Aerobic Efficiency | Scatter + linie | AE per týden (body) + 4-týdenní rolling (linie) |
| HR Drift | Scatter | Early HR vs. Late HR, obarveno tempem, velikost dle vzdálenosti |
| Running Cadence Trend | Scatter + linie | Týdenní průměr kroků/min · referenční pásmo 170–180 spm |
| Aerobic Decoupling Factor | Scatter + linie | Cardiac drift % per aktivita · pod 5 % = dobře navázaný aerobní systém |

---

### Záložka 3: Fitness Tracker

| Graf | Typ | Metrika |
|------|-----|---------|
| KPI Row | Textové karty | CTL, ATL, TSB + 7-denní delta, status formy |
| Fitness Series | Multi-osa | CTL (linie, levá Y), ATL (přerušovaná linie, levá Y), TSB (sloupcový, pravá Y, barevný dle znaménka), overlay aktivit |
| ACWR | Linie s barevnými pásmy | ATL ÷ CTL v čase · zelená <1,3 (bezpečné) · amber 1,3–1,5 (opatrnost) · červená >1,5 (riziko zranění) |

**Overlay aktivit:** Zobrazuje hodnotu CTL v datu každé aktivity, velikost dle vzdálenosti.

---

### Záložka 4: Pacing & Splits

| Graf | Typ | Metrika |
|------|-----|---------|
| Positive vs Negative Splits | Scatter + linie | Split difference per aktivita (červená = pozitivní, zelená = negativní) + 20-běhový rolling |
| Pacing Consistency | Scatter + linie | Std dev tempa per aktivita + 20-běhový rolling |
| Best Efforts | Multi-series linie | Nejlepší měsíční tempo pro: 1 km, 5 km, 10 km, půlmaraton, maraton + kumulativní PB trend |
| Race Performance History | Scatter | Oficiální závody · obarveno dle vzdálenostního pásma (<5 km, 5–12 km, 13–22 km, >22 km) |
| Race Predictor | HTML tabulka | Riegelův vzorec z nejlepšího tréninkového úsilí: T2 = T1 × (D2/D1)^1,06 |

---

### Záložka 5: Volume & Periodization

| Graf | Typ | Metrika |
|------|-----|---------|
| Weekly Volume | Sloupcový + linie | Týdenní vzdálenost + 4-týdenní rolling průměr |
| YoY Monthly Distance | Multi-year linie | Vzdálenost per měsíc napříč roky |
| YoY Aerobic Efficiency | Multi-year linie | Průměrná AE per měsíc per rok (ignoruje filtr datumu — plná historie) |
| YoY GAP Pace | Multi-year linie | Průměrné GAP tempo per měsíc per rok |
| Training Monotony | Linie s anotacemi | Monotonnost per týden + prahy 1.5 (výstraha) a 2.0 (riziko) |
| Easy/Moderate/Hard | Stackovaný sloupcový | Měsíční % tréninkového času v easy/moderate/hard zónách |
| Weekly Load Ramp Rate | Sloupcový | Týden/týden změna objemu v % · červeně >10 % (příliš rychlý nárůst = riziko zranění) |

**Mapování intenzit na zóny:**
- **5-zónový model:** Easy = Z1+Z2, Moderate = Z3, Hard = Z4+Z5
- **3-zónový model:** Easy/Moderate/Hard přímo ze zone_summary

---

## 5. Struktura záložek

### Navigace (hlavní horizontální lišta)

1. **Overview** (výchozí) — přehled tréninkového objemu, heatmapa, sport breakdown, měsíční trendy, série
2. **HR Zones & Efficiency** — definice zón, distribuce času v zónách, aerobní efektivita, HR drift
3. **Fitness Tracker** — ATL/CTL/TSB forma, KPI karty s deltami, časová řada CTL+ATL+TSB
4. **Pacing & Splits** — pozitivní/negativní splity, konzistence pacingu, best efforts per vzdálenost
5. **Volume & Periodization** — týdenní objem, YoY srovnání, monotonnost, distribuce intenzity

### Kontrolní lišta (top)

**Výběr datového rozsahu:**
- Rychlé předvolby: Last 7d, Last 4w, 6m, Last 12m, This year to date, All time
- Manuálně: "From" + "To" datepickery
- Vždy filtruje na: Run, TrailRun, VirtualRun

**Filtry:**
- **Races Only** checkbox — filtruje na `workout_type == 1`
- **Zone Model** — 5-zone (výchozí) nebo 3-zone

**HR Zone Window** (pouze záložka HR Zones):
- 30 / 90 (výchozí) / 365 dní

**Apply Button** — reload všech načtených záložek s novými filtry

---

## 6. Filtrování a datové rozsahy

### Pipeline filtrování aktivit

**Vždy aplikováno:**
```python
mask = activities["sport_type"].isin(["Run", "TrailRun", "VirtualRun"])
```

**Podmíněně (z query params):**
```python
# Datový rozsah
if date_start:
    mask &= activities["start_date_local"].dt.date >= pd.to_datetime(date_start).date()
if date_end:
    mask &= activities["start_date_local"].dt.date <= pd.to_datetime(date_end).date()

# Jen závody
if races_only == "true":
    mask &= activities["workout_type"] == 1
```

### Logika srovnávacího období (KPI delty v Overview)

| Scénář | Podmínka | Srovnávací období |
|--------|----------|-------------------|
| Oba datumy | `date_start` i `date_end` zadány | Stejně dlouhé období před `date_start` |
| Jen začátek | Pouze `date_start` | Stejně dlouhé období před `date_start` (do dnes) |
| Nic | Bez filtru | Jan 1 předchozího roku → (dnes − 1 rok) |

### Výjimky z filtrování

- **YoY záložky** ignorují filtr datumu záměrně (používají plnou historii)
- **HR zone window** je nezávislý na date range (rolling okno z filtrovaných dat)
- **Fitness data** vyžadují HR data; bez nich zobrazí chybovou hlášku

---

## 7. API endpointy

| Endpoint | Metoda | Parametry | Vrací |
|----------|--------|-----------|-------|
| `/` | GET | — | HTML stránka (index.html) |
| `/api/config` | GET | — | `max_hr`, `date_min/max`, sports, `total_activities` |
| `/api/overview` | GET | `date_start`, `date_end`, `races_only`, `zone_model` | KPI, heatmap, monthly, sports, streaks, gear_mileage + srovnání |
| `/api/hr-zones` | GET | `date_start`, `date_end`, `races_only`, `zone_model`, `window_days` | Definice zón, rolling zóny %, AE, HR drift, cadence trend, decoupling |
| `/api/fitness` | GET | `date_start`, `date_end`, `races_only`, `zone_model` | CTL/ATL/TSB aktuální + series, ACWR series, overlay aktivit |
| `/api/pacing` | GET | `date_start`, `date_end`, `races_only`, `zone_model` | Splity, konzistence, best efforts, race history, race predictor |
| `/api/periodization` | GET | `date_start`, `date_end`, `races_only`, `zone_model` | Weekly, YoY distance/AE/GAP, monotonnost, intenzita, ramp_rate |
| `/api/keboola-status` | GET | — | Timestamp posledního běhu, stav jobu |
| `/api/keboola-run` | POST | — | Spustí sync dat, vrátí job ID |
| `/api/debug` | GET | — | Diagnostika: env, token stav, náhled dat |

---

## 8. Klíčové konstanty

| Konstanta | Hodnota | Soubor | Účel |
|-----------|---------|--------|------|
| `RESTING_HR` | 45.0 bpm | `app.py` | Klidová TF pro zóny |
| `MAX_HR` | 179.0 bpm | `app.py` | Výchozí max TF (vypočteno z DOB 1985) |
| Elevation factor | 7 | `metrics.py`, `app.py` | 1 m převýšení ≈ 7 m roviny |
| TRIMP konstanta | 0.64 | `metrics.py` | Gender/fitness empirický faktor |
| TRIMP exponent | 1.92 | `metrics.py` | Váha intenzity TF (Foster) |
| CTL span | 42 dní | `metrics.py` | Okno chronic training load |
| ATL span | 7 dní | `metrics.py` | Okno acute training load |
| AE rolling window | 4 týdny | `metrics.py` | Vyhlazení aerobní efektivity |
| Split rolling window | 20 běhů | `app.py` | Rolling průměr pacingu |
| Monotony window | 7 dní | `metrics.py` | Variabilita tréninkového stresu |
| Monotony caution | 1.5 | `periodization.js` | Prahová linie výstrahy v UI |
| Monotony risk | 2.0 | `periodization.js` | Prahová linie rizika v UI |
| Timezone | `Europe/Prague` | `data_loader.py` | Všechny datetime konverze |
| Keboola bucket | `in.c-Garmin_full` | `data_loader.py` | Prefix tabulek |
| GCP project | `kbc-use4-1566-d355` | `data_loader.py` | BigQuery projekt ID |

---

## 9. Závislosti

### Python backend

| Balíček | Verze | Účel |
|---------|-------|------|
| `flask` | ≥ 3.0 | Web framework, routing, JSON odpovědi |
| `pandas` | ≥ 2.1 | DataFrames, time series, groupby, rolling windows |
| `numpy` | ≥ 1.26 | Numerické operace, NaN handling, exp/log |
| `requests` | ≥ 2.31 | HTTP pro Keboola API, BigQuery, GCS |
| `google-auth` | ≥ 2.0 | GCP service account auth, federation token exchange |
| `gunicorn` | ≥ 21.0 | Produkční WSGI server (Vercel deployment) |

### JavaScript frontend

| Knihovna | Verze | Účel |
|----------|-------|------|
| `plotly.js` | 2.32.0 | Interaktivní grafy (scatter, line, bar, heatmap, pie) |
| Vanilla JS | ES6 | Tab switching, správa parametrů, API fetch |

### Externí služby

| Služba | Účel |
|--------|------|
| **Keboola** | Cloud datové úložiště, async export tabulek, job API |
| **Google Cloud Storage (GCS)** | Federation token → stažení souborů |
| **BigQuery** | Agregace streaming dat (HR zóny, drift) |
| **Vercel** | Deployment platform (serverless funkce) |
| **Strava API** | (upstream) Zdrojová data všech aktivit a streamů |

---

*Dokumentace aktualizována: 2026-04-10*
