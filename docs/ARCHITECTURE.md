# Architecture

CarbonWindow is deliberately small: five modules, one pure-function core, one I/O edge,
one renderer. The shape exists so that the number a user reads can be traced back to a
byte the API returned.

```
                    ┌──────────────────────────────┐
   ESO API ────────►│ ci_api                       │
   (HTTP, 30 min)   │  fetch (14-day chunks)       │
                    │  cache  → data/cache/*.json  │
                    │  parse  → list[Interval]     │
                    │  align  → GridSeries         │───► data/ci_90d.json
                    └──────────────┬───────────────┘        (the snapshot)
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ optimize                     │  pure
                    │  window_means   (prefix sums)│
                    │  argmin_windows (deque, O(n))│
                    │  plan_job       → Plan       │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │ report                       │  pure
                    │  evaluate_condition × 18     │
                    │  daily_table / heatmap       │
                    │  example_day / data_quality  │
                    │  build_report → summary.json │
                    └──────────────┬───────────────┘
                          ┌────────┴─────────┐
                          ▼                  ▼
              ┌───────────────────┐  ┌──────────────────┐
              │ web.py            │  │ tools/build_docs │
              │ summary → HTML    │  │ summary → .md    │
              │ web/index.html    │  │ docs/REPORT.md   │
              └───────────────────┘  └──────────────────┘
```

## Modules

### `carbonwindow/ci_api.py` — the only edge that talks to the network

- `fetch_intensity(start, end)` slices the range into ≤14-day chunks (`MAX_CHUNK`),
  requests each one, and writes it to `data/cache/ci_<from>_<to>.json`. The cache is keyed
  by the exact range, so a re-run of the same command costs zero requests and an
  interrupted run resumes where it stopped.
- `parse_intensity_payload` maps raw JSON to `Interval`, and `_dedupe` handles the one
  quirk that matters: the API returns a row starting *before* the requested `from`, so
  naive concatenation duplicates a half hour at each chunk boundary.
- `to_series` aligns intervals onto a fixed 30-minute grid anchored at the first
  interval's start. **Missing slots become `None` — never an interpolated value.** This is
  an invariant of the whole system, not an implementation detail: an interpolated slot
  would silently manufacture a cheap window.
- `GridSeries` is a frozen dataclass of `start`, `actual`, `forecast`, with the index maths
  (`time_of`, `index_of`, `coverage`) in one place instead of scattered offsets.

### `carbonwindow/optimize.py` — pure, exact, testable

- `window_means(values, k)` computes the mean of every length-`k` window from prefix sums,
  propagating `None` (a window touching a gap is `None`, not a partial average).
- `argmin_windows(means, width)` is the core: a **monotonic deque** that yields, for every
  arrival `i`, the index of the minimum mean in `[i, i + width)`. O(n) total, and the
  comparison is `>=` so ties resolve to the **earliest** start — determinism matters when
  two half hours are equally clean.
- `plan_job(series, now, duration, horizon, decide_on=…)` returns a `Plan` with both
  windows, the percentage reduction, and the gCO2 difference for a stated power draw.
  `decide_on` is the switch that makes the oracle/forecast distinction a parameter rather
  than a fork in the code.
- `brute_force_best_window` lives next to it on purpose: the fast path and the oracle that
  can falsify it sit in the same file, and `tests/test_optimize.py` runs both over random
  series.

### `carbonwindow/report.py` — the replay

- `evaluate_condition(series, duration, horizon, decide_on)` walks **every** legal arrival
  and accumulates median/mean/worst/best/P10/P90, the share of arrivals that ended up
  worse than “now”, and the gCO2 difference. One pass, no sampling.
- `daily_table`, `heatmap`, `example_day` are day-level views. All three use only
  **complete UTC days** (48 slots), because a partial day averages over a different
  number of samples and would be an artefact of where the snapshot happens to end.
- `example_day` deliberately picks the day whose median reduction is the **median** of all
  days, then a mid-rank arrival on that day: the illustration is a typical case, not the
  best case.
- `data_quality` and `sensitivity` exist to police the snapshot rather than trust it:
  a 0 gCO2/kWh reading is detected, disclosed, and re-run as a gap.
- `build_report` returns one JSON-serialisable dict — the single source for both the web
  page and the Markdown docs, so the two cannot disagree.

### `carbonwindow/web.py` — a renderer, not a web app

- The page is **one HTML file, 0 network requests**: CSS inline, charts as SVG emitted by
  Python, the whole summary embedded as JSON in a `<script type="application/json">`.
- Charts are SVG rather than canvas/JS so the page renders identically in a screenshot, in
  print, and with JavaScript disabled.
- The same JSON is what `tools/build_docs.py` reads, so if the web page and the docs ever
  disagreed, one of them would have been edited by hand.

### `carbonwindow/cli.py` — thin

Parses arguments, calls one library function, prints a table. No logic that is not tested
through the library.

## Invariants

1. **No interpolation.** Gaps stay gaps; windows touching them are dropped and counted.
2. **Determinism.** Ties resolve to the earliest start; no random seeds, no sampling in the
   measurement path.
3. **One number, one source.** `results/summary.json` feeds both outputs; docs are generated.
4. **Exactness is testable.** The O(n) optimiser is checked against brute force, not trusted.
5. **Disclosure over cleaning.** Anomalies are reported next to the number they affect.

## Complexity and cost

| step | cost | measured |
|---|---|---|
| fetch 90 days | 7 HTTP requests (14-day chunks) | 4,329 intervals, 0 retries |
| `report` (18 conditions, ~4,300 arrivals each) | O(n) per condition | 0.25 s |
| `web` render | O(slots) | 768 KB HTML |
| `pytest` | 31 tests | < 1 s |

## Testing strategy

- **`tests/test_optimize.py`** — the optimiser against brute force over random series
  (single-window, deadline-bounded, and raw `means` rescans), plus cases where the greedy
  “cheapest single half hour” answer is **wrong**, proving the sliding window is doing real
  work.
- **`tests/test_api.py`** — parsing of a real captured payload (including the
  pre-`from` row), chunk boundaries, cache reuse, and grid alignment with a missing slot.
- **`tests/test_report.py`** — reduction percentages computed by hand in the comments, so a
  regression shows up as a wrong constant rather than as a test that agrees with the code.

## Extension points

- **Different grid**: implement the same `GridSeries` contract from another operator's
  feed; nothing downstream changes.
- **Different objective**: `window_means` is the only place the objective (mean intensity)
  is encoded. A marginal-emissions or price objective is a swap there.
- **Different cost model**: `plan_job(..., power_kw=…)` and `build_report(..., power_kw=…)`
  already carry the energy assumption, so kWh and gCO2 scale with it.
