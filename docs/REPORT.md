# CarbonWindow — measured results

Everything in this document is generated from `results/summary.json` by
`tools/build_docs.py`. No number here was typed by hand or estimated.

- **Source**: National Grid ESO Carbon Intensity API,
  `GET https://api.carbonintensity.org.uk/intensity/{from}/{to}`
  (free, no API key, half-hourly GB national average, gCO2/kWh).
- **Snapshot window**: `2026-07-21T23:30Z` → `2026-10-20T04:00Z`
  (90.19 days).
- **Coverage**: 4,329 of 4,329 half hours
  present = **100.0 %**, 0 missing
  (missing slots are never interpolated; a window that touches one is dropped and counted).
- **Snapshot file**: `data/ci_90d.json`; chunk cache in `data/cache/`.
- **Generated at**: 2026-10-20T04:54:48Z.

The question this document answers: *for a job that may start anywhere before its
deadline, how much lower is the average carbon intensity at the best start time than
at “now”, measured at every possible arrival over 90.2 days?*

Two information sets are reported side by side:

| Label | Decides using | Meaning |
|---|---|---|
| **oracle** | the measured values | the ceiling; not achievable in advance |
| **forecast** | the forecast the API archived for those half hours | what a real deployment would have known |

The forecast rows are not a re-simulation: the API keeps the forecast that was
actually published before each half hour, so the gap between it and the actual value
is a genuine out-of-sample error.

## 1. The grid over the window

| statistic | value |
|---|---|
| mean | 115.72 gCO2/kWh |
| median | 110.00 |
| minimum | 0.00 — a single 0 gCO2/kWh reading, see §4 |
| maximum | 247.00 |

Half hours per ESO intensity band (this is the whole window, not a weekly sample):

| band | half hours | share |
|---|---:|---:|
| very low | 250 | 5.8 % |
| low | 1,667 | 38.5 % |
| moderate | 1,193 | 27.6 % |
| high | 974 | 22.5 % |
| very high | 245 | 5.7 % |

Daily means ranged from **48.6** (2026-10-09) to
**209.8** (2026-10-06) — a
4.31× spread between the cleanest and
dirtiest day in the same three months. That spread, more than any intra-day cycle, is
what the scheduler is exploiting.

Archived-forecast accuracy over 4,329 half hours:

| metric | value |
|---|---|
| mean absolute error | 12.56 gCO2/kWh |
| median absolute error | 8.0 |
| 95th percentile | 39 |
| worst | 165 |

A mean absolute error of 12.6 against a 115.7 mean makes the
forecast-driven table below a fair test rather than a formality: the forecast is good
enough to find cheap half hours most of the time, and wrong enough to lose on some of
them.

## 2. Results

Energy model: the job is a constant **1.00 kW** load for its whole
length, so a 30 min job is 0.50 kWh, a 1 h job
1.00 kWh, a 2 h job 2.00 kWh.
The gCO2 column is that energy multiplied by the intensity difference between “start
now” and the chosen window. It is an assumption, stated once, not a measurement of any
particular workload.

**Perfect foresight (upper bound)**

| Job length | Deadline | Start times | Median | Mean | Worst | Best | P10 | P90 | Worse than “now” | gCO2 saved per job |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30m | 6h | 4,317 | **12.61 %** | 17.91 % | 0.00 % | 100.0 % | 0.0 % | 44.6 % | 0.0 % | 6.0 |
| 30m | 12h | 4,305 | **27.46 %** | 27.93 % | 0.00 % | 100.0 % | 0.0 % | 57.7 % | 0.0 % | 14.0 |
| 30m | 24h | 4,281 | **40.54 %** | 38.74 % | 0.00 % | 100.0 % | 2.6 % | 67.7 % | 0.0 % | 21.5 |
| 1h | 6h | 4,318 | **10.46 %** | 16.27 % | 0.00 % | 74.8 % | 0.0 % | 42.1 % | 0.0 % | 10.5 |
| 1h | 12h | 4,306 | **25.93 %** | 26.64 % | 0.00 % | 80.7 % | 0.0 % | 56.5 % | 0.0 % | 26.5 |
| 1h | 24h | 4,282 | **39.76 %** | 37.67 % | 0.00 % | 86.2 % | 1.7 % | 66.9 % | 0.0 % | 42.5 |
| 2h | 6h | 4,318 | **6.96 %** | 13.18 % | 0.00 % | 62.2 % | 0.0 % | 36.8 % | 0.0 % | 14.0 |
| 2h | 12h | 4,306 | **22.64 %** | 24.35 % | 0.00 % | 79.4 % | 0.0 % | 53.9 % | 0.0 % | 46.0 |
| 2h | 24h | 4,282 | **38.06 %** | 35.98 % | 0.00 % | 85.4 % | 0.7 % | 65.2 % | 0.0 % | 79.8 |

**Forecast-driven (what a deployment would have known)**

| Job length | Deadline | Start times | Median | Mean | Worst | Best | P10 | P90 | Worse than “now” | gCO2 saved per job |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30m | 6h | 4,317 | **3.36 %** | 9.97 % | -195.65 % | 100.0 % | -9.5 % | 41.9 % | 23.7 % | 2.0 |
| 30m | 12h | 4,305 | **16.18 %** | 14.91 % | -300.00 % | 100.0 % | -15.1 % | 54.3 % | 21.2 % | 8.0 |
| 30m | 24h | 4,281 | **29.87 %** | 20.30 % | -300.00 % | 84.4 % | -24.6 % | 62.1 % | 20.2 % | 14.0 |
| 1h | 6h | 4,318 | **3.14 %** | 11.38 % | -67.07 % | 67.7 % | -5.6 % | 40.7 % | 19.7 % | 3.0 |
| 1h | 12h | 4,306 | **18.91 %** | 21.00 % | -108.20 % | 80.2 % | -3.2 % | 53.9 % | 13.8 % | 19.0 |
| 1h | 24h | 4,282 | **34.51 %** | 30.98 % | -326.47 % | 83.7 % | -0.7 % | 63.5 % | 10.2 % | 35.8 |
| 2h | 6h | 4,318 | **2.19 %** | 10.46 % | -57.32 % | 62.2 % | -2.6 % | 35.9 % | 16.1 % | 4.5 |
| 2h | 12h | 4,306 | **17.66 %** | 20.84 % | -67.52 % | 79.4 % | -0.5 % | 52.8 % | 10.9 % | 35.5 |
| 2h | 24h | 4,282 | **35.28 %** | 31.93 % | -130.15 % | 82.5 % | 0.0 % | 63.5 % | 7.9 % | 72.5 |

Reading the tables:

- **More deadline is worth more than a longer job is worth less.** At a 6 h deadline the
  median gain for a 1 h job is 10.46 %; at 24 h
  the same job reaches 39.76 %. Widening the
  deadline multiplies the number of candidate start times
  (47 at 24 h versus
  11 at 6 h), while lengthening the
  job averages the best half hours away with the rest.

- **The forecast costs about a sixth of the ceiling at the reference condition**:
  18.91 % against 25.93 %
  (1h job, 12h deadline).
- **Every forecast condition has a negative tail.** 13.84 % of
  the 4,306 reference-condition arrivals ended up worse than running immediately,
  the worst by -108.2 %. Perfect foresight never loses
  (0.0 % worst case by construction: “now” is always one of the
  candidate windows).

## 3. One day, worked through

The example day is picked as the day with the **median** per-day reduction, so it is a
typical day rather than the best one.

- Day: **2026-08-26** (UTC), 48 half hours.
- Condition: 60 min job, 720 min
  deadline.
- Arrival: **02:00** UTC, where the job would average
  **94.5 gCO2/kWh**.
- Chosen start: **13:00** UTC, averaging
  **73.0 gCO2/kWh** — a **22.8 %**
  reduction, after a shift of 11 h 00 min.
- Last legal start for this arrival: 13:00 UTC.

## 4. Data quality, stated rather than cleaned

- Half-hour readings of exactly 0 gCO2/kWh: **1**
  (2026-08-06T11:00Z).
- Lowest reading in the window excluding those: **27**.
- Largest step between two consecutive half hours: **41**.

A GB grid does not run at zero, so the 0 is treated as a missing value published as
zero. It is **left in** the headline tables above and **excluded** from the sensitivity
check below (turned back into a gap — not interpolated):

| condition | median with the 0 | median without it | change |
|---|---:|---:|---:|
| oracle, 1h/12h | 25.93 % | 25.72 % | -0.209 pp |
| forecast, 1h/12h | 18.91 % | 18.91 % | 0.000 pp |

Those two medians barely move, because one half hour out of 4,329 is diluted by the
whole window. The day-level view is a different story: see §5, where the same reading is
worth 30 percentage points on one day and changes which day ranks best. It also inflates
the *best* value in the 30-minute rows to 100 %, which is why the best column should be
read as “the luckiest arrival in three months”, not as an achievable target.

## 5. Best and worst days

| | day | mean CI | median reduction |
|---|---|---:|---:|
| best day for the scheduler | 2026-08-06 | 103.1 | 56.8 % |
| worst day for the scheduler | 2026-10-11 | 126.0 | 1.1 % |

The best day for the scheduler (2026-08-06) is not the cleanest day
(2026-10-09, mean 48.6) and the worst is not the dirtiest
(2026-10-06, mean 209.8). What matters is the *range inside
the deadline*, not the level.

**And the best day is an artefact.** 2026-08-06 is the UTC day that contains the
single 0 gCO2/kWh reading from §4. Treating that reading as a gap instead of a
measurement, the same day's median falls from **56.8 %** to
**25.2 %**
(46 of its 48 arrivals survive the gap), and the best day in
the window becomes **2026-10-16** at
48.2 %. One bad row is worth
31.6 percentage points on a single day's headline, and a
different winner. The day ranking uses perfect foresight, so it is the most exposed of
all the numbers here to that defect — which is exactly why it is shown rather than
cleaned.

## 6. Threat model for these numbers

Reasons a reader should discount them, in order of how much they would matter:

1. **Average intensity is the wrong quantity for load shifting.** The API reports the
   average mix on the grid. Shifting 1 kWh does not necessarily avoid 1 kWh of that
   average; it may displace a marginal generator that is dirtier or cleaner. A proper
   marginal-emissions model (or an actual metered experiment) would give different — and
   possibly much smaller — numbers. This is the single biggest caveat.
2. **The forecast is a real archive but the decision rule is a hindsight choice.** The
   rule “pick the cleanest forecast window inside the deadline” is fixed in advance and
   applied at every half hour for 90 days, so it is not
   overfitted to one period, but a production scheduler would also react to price,
   queue depth, retries and failure costs that are absent here.
3. **Half-hour granularity.** Sub-30-minute flexibility (and anything finer than the
   API's own resolution) is invisible.
4. **Plans complete.** No preemption, no cold start, no re-runs inside the window.
5. **Great Britain only.** GB national average; the API's regional endpoint exists but
   the optimiser here scores national intensity, as the scheduler would see it.
6. **The kWh numbers are a stated model**, not metered consumption.

## 7. Reproducing this

```bash
python -m carbonwindow.cli fetch  --from 2026-07-22T00:00Z --to 2026-10-20T04:00Z
python -m carbonwindow.cli report
python -m carbonwindow.cli web
python tools/build_docs.py
python -m pytest
```

`fetch` is the only command that touches the network for historical data; it caches
14-day chunks under `data/cache/` and reuses them, so a second run costs zero requests.
