# CarbonWindow

**Move the batch job to the clean half hour — and prove the number.**

CarbonWindow is a scheduler for flexible compute that scores every legal start time
against real grid carbon data, then picks the cheapest half hour inside the deadline.
It ships with the evidence, not just the optimiser: a 90-day replay over every possible
arrival, a static report you can open without a build step, and a test suite that
checks the O(n) optimiser against brute force.

Built for the **IEEE ClimateChain Global Hackathon**.

- 🌍 **Data**: National Grid ESO Carbon Intensity API — free, no API key, half-hourly GB
  national average in gCO2/kWh.
- 🧮 **Optimiser**: exact sliding-window minimum, O(n) with a monotonic deque, and a
  brute-force oracle in `tests/` that it must agree with.
- 📊 **Report**: one HTML file, SVG charts, no CDN, no build step, works offline.
- 🔍 **Honest by construction**: perfect-foresight and forecast-driven numbers are shown
  side by side, and a data defect found in the snapshot is disclosed instead of cleaned.

<!-- results:begin -->
Measured over **90.19 days** of GB half-hourly carbon
intensity (4,329 readings,
100.0 % coverage).

| 1h job, 12h deadline | median | mean | worst | worse than “now” |
|---|---:|---:|---:|---:|
| perfect foresight (ceiling) | 25.93 % | 26.64 % | 0.0 % | 0.0 % |
| forecast-driven (deployable) | 18.91 % | 21.00 % | -108.2 % | 13.8 % |

At a 24 h deadline the forecast-driven median rises to **34.51 %**, and the ceiling (`30m` job, 24 h deadline) is **40.54 %**.
Full 18-condition tables, per-day detail and the caveats: [docs/REPORT.md](docs/REPORT.md).
<!-- results:end -->

## What it does

Given a job that takes `d` half hours and must start before a deadline `T`, and a
series of half-hourly carbon intensity values, `optimize` finds the window
`[start, start + d)` that minimises the **mean** intensity. The comparison baseline is
always “run it right now”, so every number the tool prints is a decision someone could
actually make.

```
now ──────────────────────────────────────────────────► deadline
      ▁▂▁▃▅▇█▇▅▃▂▁▂▃▁▂▁▃▂▁▁▂▃▂▁▁▁▂▃▅▃▂▁▁▂▁▁▂▁▁▁▁▁▁▁▁▁▁▁▁
      [now]                    [best window]         [T]
```

The optimiser is exact, not a heuristic: it cannot miss a cheaper window, which is why
it can be compared honestly against a brute-force search on the same data.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# 1. fetch ~90 days of history (14-day chunks, cached, resumable)
python -m carbonwindow.cli fetch --from 2026-07-22T00:00Z --to 2026-10-20T04:00Z

# 2. replay every arrival and aggregate
python -m carbonwindow.cli report

# 3. a single live decision, using the next 24 h of forecast
python -m carbonwindow.cli live --duration-hours 1 --horizon-hours 12

# 4. build the static report
python -m carbonwindow.cli web        # -> web/index.html

# 5. regenerate docs from the measured summary
python tools/build_docs.py

# 6. tests
python -m pytest
```

`fetch` is the only command that touches the network for history, it asks for
at most 14 days per request out of respect for the API's rate limits, and it reuses
`data/cache/` so a second run costs zero requests.

## CLI

| command | what it does |
|---|---|
| `fetch` | download and cache half-hourly intensity for a date range into one JSON snapshot |
| `optimize` | one decision at a chosen moment, with `--brute-force-check` to cross-verify |
| `report` | replay **every** legal start time for 3 job lengths × 3 deadlines × 2 information sets |
| `web` | render `results/summary.json` into a single self-contained `web/index.html` |
| `live` | a real decision from the next 24 h forecast, printed as a table |

## How the numbers are made

1. **Collect.** Half-hourly `actual` and `forecast` values into a `GridSeries`. Missing
   slots stay `None`; they are never interpolated.
2. **Score.** For each arrival `i` and condition `(d, T)`, compute the baseline window
   mean at `i` and the minimum window mean over the legal starts `[i, i + T - d]`.
   Reduction = `(baseline - best) / baseline × 100`.
3. **Decide with one information set, score with another.**
   - `oracle` decides on measured values — the ceiling.
   - `forecast` decides on the forecast the API archived for those half hours — what a
     real deployment would have known — and is still scored against measured values.
4. **Aggregate.** Per condition: n, median, mean, worst, best, P10, P90, share of
   arrivals that ended up **worse** than running immediately, and the gCO2 difference
   for a stated energy model.

A window that touches a missing slot is dropped and counted (`dropped`), never smoothed
over, so `n` differs slightly between conditions.

## Results

Genuine results for this snapshot, produced by `report` and regenerated into this file by
`tools/build_docs.py`. Full tables, per-day detail and the threat model:
[docs/REPORT.md](docs/REPORT.md).

See the block at the top of this file — it is generated, not typed.

## What this is not

Stated plainly, because a scheduler that hides these is worse than no scheduler:

- **Average intensity, not marginal emissions.** The API reports the average mix on the
  grid. Shifting 1 kWh does not necessarily avoid 1 kWh of that average; it may displace
  a marginal generator that is dirtier or cleaner. The gCO2 column is a stated model
  (`power_kw` × hours × intensity difference), not a metered saving. **This is the
  biggest caveat in the project.**
- **Great Britain only.** One national average. Nothing here transfers to another grid
  without replaying that grid's own data.
- **Half-hour granularity.** Flexibility finer than 30 minutes is invisible to this model.
- **The forecast can lose.** A forecast-driven schedule lowers the median reduction but
  has a negative tail: some arrivals end up worse than running immediately. The report
  quantifies that tail instead of hiding it.
- **Plans complete.** No preemption, no cold starts, no retries inside the window.

## Repository layout

```
carbonwindow/         library: API client, optimiser, replay, static report renderer, CLI
  ci_api.py           ESO client, chunked fetch, cache, GridSeries
  optimize.py         prefix sums, monotonic-deque argmin, plan_job
  report.py           the 90-day replay, per-day tables, heatmap, data-quality probes
  web.py              single-file HTML + SVG report
  cli.py              fetch / optimize / report / web / live
tests/                optimiser vs brute force, API parsing, hand-computed reductions
tools/build_docs.py   regenerates docs/REPORT.md and the results block above
data/                 the measured snapshot + 14-day chunk cache
results/summary.json  everything the web page and the docs are built from
web/index.html        the report (generated; open it directly)
docs/                 ARCHITECTURE.md, REPORT.md, SUBMISSION_DRAFT.md, demo video
STATUS.md             running log of what was measured, in order
```

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the pieces fit and why
- [docs/REPORT.md](docs/REPORT.md) — the measured results and every caveat
- [docs/SUBMISSION_DRAFT.md](docs/SUBMISSION_DRAFT.md) — hackathon submission copy
- [STATUS.md](STATUS.md) — the build log with the measurements in the order they happened

## Data source

National Grid ESO Carbon Intensity API — <https://carbonintensity.org.uk/>. Free, no key
required. This project stores what it fetched (`data/ci_90d.json`) so every number can be
re-derived offline and audited against the same bytes.

## License

MIT — see [LICENSE](LICENSE).
