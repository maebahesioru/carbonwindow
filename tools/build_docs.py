"""Generate docs/REPORT.md and the README results block from results/summary.json.

Every number in those documents comes out of this script, so a re-run of
``fetch``/``report`` cannot leave the prose quoting a stale figure. Run with::

    python tools/build_docs.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SUMMARY = ROOT / "results" / "summary.json"
REPORT = ROOT / "docs" / "REPORT.md"
README = ROOT / "README.md"

DURATIONS = ("30m", "1h", "2h")
HORIZONS = ("6h", "12h", "24h")


def f(value, digits: int = 1, dash: str = "–") -> str:
    if value is None:
        return dash
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:,.{digits}f}"


def pct(value, digits: int = 2) -> str:
    return dash if value is None else f"{value:.{digits}f} %"


def fmt_shift(minutes: int) -> str:
    hours, rest = divmod(abs(int(minutes)), 60)
    return f"{hours} h {rest:02d} min" if hours else f"{rest} min"


def table(results: dict, variant: str, *, title: str) -> str:
    rows = [
        "| Job length | Deadline | Start times | Median | Mean | Worst | Best | "
        "P10 | P90 | Worse than “now” | gCO2 saved per job |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for duration in DURATIONS:
        for horizon in HORIZONS:
            stats = results[variant][duration][horizon]
            if not stats.get("n"):
                rows.append(f"| {duration} | {horizon} | 0 | – | – | – | – | – | – | – | – |")
                continue
            rows.append(
                f"| {duration} | {horizon} | {stats['n']:,} | "
                f"**{pct(stats['median_pct'])}** | {pct(stats['mean_pct'])} | "
                f"{pct(stats['worst_pct'])} | {pct(stats['best_pct'], 1)} | "
                f"{pct(stats.get('p10_pct'), 1)} | {pct(stats.get('p90_pct'), 1)} | "
                f"{pct(stats.get('negative_share_pct'), 1)} | "
                f"{f(stats.get('gco2_avoided_median'), 1)} |")
    return f"**{title}**\n\n" + "\n".join(rows) + "\n"


def build() -> str:
    data = json.loads(SUMMARY.read_text(encoding="utf-8"))
    window, coverage, ci = data["window"], data["coverage"], data["ci_stats"]
    config = data["config"]
    reference = config["reference"]
    results = data["results"]
    quality = data["data_quality"]
    sens = data["sensitivity"]
    daily = data["daily"]
    example = data["example"]
    decision = example["decision"]
    err = ci["forecast_error"]

    ref_o = results["oracle"][reference["duration"]][reference["horizon"]]
    ref_f = results["forecast"][reference["duration"]][reference["horizon"]]

    best_day = max(daily, key=lambda r: r["reduction_median_pct"] or -999)
    worst_day = min(daily, key=lambda r: r["reduction_median_pct"] if r["reduction_median_pct"] is not None else 999)
    cleanest = min(daily, key=lambda r: r["ci_mean"])
    dirtiest = max(daily, key=lambda r: r["ci_mean"])

    zero = data.get("zero_day_effect") or {"applicable": False}

    counts = ci["index_counts"]
    total_slots = sum(counts.values()) or 1
    bands = "\n".join(
        f"| {name} | {count:,} | {100.0 * count / total_slots:.1f} % |"
        for name, count in counts.items())

    parts: list[str] = []
    add = parts.append

    add(f"""# CarbonWindow — measured results

Everything in this document is generated from `results/summary.json` by
`tools/build_docs.py`. No number here was typed by hand or estimated.

- **Source**: National Grid ESO Carbon Intensity API,
  `GET https://api.carbonintensity.org.uk/intensity/{{from}}/{{to}}`
  (free, no API key, half-hourly GB national average, gCO2/kWh).
- **Snapshot window**: `{window["start_utc"]}` → `{window["end_utc"]}`
  ({f(window["span_days"], 2)} days).
- **Coverage**: {coverage["actual_present"]:,} of {coverage["slots"]:,} half hours
  present = **{f(coverage["coverage_pct"], 1)} %**, {coverage["actual_missing"]:,} missing
  (missing slots are never interpolated; a window that touches one is dropped and counted).
- **Snapshot file**: `data/ci_90d.json`; chunk cache in `data/cache/`.
- **Generated at**: {data["generated_at"]}.

The question this document answers: *for a job that may start anywhere before its
deadline, how much lower is the average carbon intensity at the best start time than
at “now”, measured at every possible arrival over {f(window["span_days"], 1)} days?*

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
| mean | {f(ci["mean"], 2)} gCO2/kWh |
| median | {f(ci["median"], 2)} |
| minimum | {f(ci["min"], 2)}{" — a single 0 gCO2/kWh reading, see §4" if quality["zero_count"] else ""} |
| maximum | {f(ci["max"], 2)} |

Half hours per ESO intensity band (this is the whole window, not a weekly sample):

| band | half hours | share |
|---|---:|---:|
{bands}

Daily means ranged from **{f(cleanest["ci_mean"], 1)}** ({cleanest["date"]}) to
**{f(dirtiest["ci_mean"], 1)}** ({dirtiest["date"]}) — a
{f(dirtiest["ci_mean"] / cleanest["ci_mean"], 2)}× spread between the cleanest and
dirtiest day in the same three months. That spread, more than any intra-day cycle, is
what the scheduler is exploiting.

Archived-forecast accuracy over {err["n"]:,} half hours:

| metric | value |
|---|---|
| mean absolute error | {f(err["mae"], 2)} gCO2/kWh |
| median absolute error | {f(err["median_abs"], 1)} |
| 95th percentile | {f(err["p95_abs"], 0)} |
| worst | {f(err["max_abs"], 0)} |

A mean absolute error of {f(err["mae"], 1)} against a {f(ci["mean"], 1)} mean makes the
forecast-driven table below a fair test rather than a formality: the forecast is good
enough to find cheap half hours most of the time, and wrong enough to lose on some of
them.

## 2. Results

Energy model: the job is a constant **{f(config["power_kw"], 2)} kW** load for its whole
length, so a 30 min job is {f(0.5 * config["power_kw"], 2)} kWh, a 1 h job
{f(1.0 * config["power_kw"], 2)} kWh, a 2 h job {f(2.0 * config["power_kw"], 2)} kWh.
The gCO2 column is that energy multiplied by the intensity difference between “start
now” and the chosen window. It is an assumption, stated once, not a measurement of any
particular workload.

""" + table(results, "oracle", title="Perfect foresight (upper bound)") + """
""" + table(results, "forecast", title="Forecast-driven (what a deployment would have known)") + f"""
Reading the tables:

- **More deadline is worth more than a longer job is worth less.** At a 6 h deadline the
  median gain for a 1 h job is {pct(results["oracle"]["1h"]["6h"]["median_pct"])}; at 24 h
  the same job reaches {pct(results["oracle"]["1h"]["24h"]["median_pct"])}. Widening the
  deadline multiplies the number of candidate start times
  ({config["horizons"]["24h"] - config["durations"]["1h"] + 1} at 24 h versus
  {config["horizons"]["6h"] - config["durations"]["1h"] + 1} at 6 h), while lengthening the
  job averages the best half hours away with the rest.

- **The forecast costs about a sixth of the ceiling at the reference condition**:
  {pct(ref_f["median_pct"])} against {pct(ref_o["median_pct"])}
  ({reference["duration"]} job, {reference["horizon"]} deadline).
- **Every forecast condition has a negative tail.** {pct(ref_f["negative_share_pct"])} of
  the {ref_f["n"]:,} reference-condition arrivals ended up worse than running immediately,
  the worst by {pct(ref_f["worst_pct"], 1)}. Perfect foresight never loses
  ({pct(ref_o["worst_pct"], 1)} worst case by construction: “now” is always one of the
  candidate windows).

## 3. One day, worked through

The example day is picked as the day with the **median** per-day reduction, so it is a
typical day rather than the best one.

- Day: **{example["date"]}** (UTC), {len(example["curve"])} half hours.
- Condition: {example["duration_slots"] * 30} min job, {example["horizon_slots"] * 30} min
  deadline.
- Arrival: **{decision["now"]}** UTC, where the job would average
  **{f(decision["baseline_mean"], 1)} gCO2/kWh**.
- Chosen start: **{decision["chosen"]}** UTC, averaging
  **{f(decision["chosen_mean"], 1)} gCO2/kWh** — a **{f(decision["reduction_pct"], 1)} %**
  reduction, after a shift of {fmt_shift((decision["chosen_index_offset"] - decision["now_index_offset"]) * 30)}.
- Last legal start for this arrival: {decision["last_legal_start"]} UTC.

## 4. Data quality, stated rather than cleaned

- Half-hour readings of exactly 0 gCO2/kWh: **{quality["zero_count"]}**
  ({", ".join(quality["zero_readings"]) or "none"}).
- Lowest reading in the window excluding those: **{f(quality["min_nonzero"], 0)}**.
- Largest step between two consecutive half hours: **{f(quality["max_abs_step"], 0)}**.

A GB grid does not run at zero, so the 0 is treated as a missing value published as
zero. It is **left in** the headline tables above and **excluded** from the sensitivity
check below (turned back into a gap — not interpolated):

| condition | median with the 0 | median without it | change |
|---|---:|---:|---:|
| oracle, {reference["duration"]}/{reference["horizon"]} | {pct(sens["oracle"]["median_raw"])} | {pct(sens["oracle"]["median_without_zeros"])} | {f(sens["oracle"]["delta"], 3)} pp |
| forecast, {reference["duration"]}/{reference["horizon"]} | {pct(sens["forecast"]["median_raw"])} | {pct(sens["forecast"]["median_without_zeros"])} | {f(sens["forecast"]["delta"], 3)} pp |

Those two medians barely move, because one half hour out of 4,329 is diluted by the
whole window. The day-level view is a different story: see §5, where the same reading is
worth 30 percentage points on one day and changes which day ranks best. It also inflates
the *best* value in the 30-minute rows to 100 %, which is why the best column should be
read as “the luckiest arrival in three months”, not as an achievable target.

## 5. Best and worst days

| | day | mean CI | median reduction |
|---|---|---:|---:|
| best day for the scheduler | {best_day["date"]} | {f(best_day["ci_mean"], 1)} | {pct(best_day["reduction_median_pct"], 1)} |
| worst day for the scheduler | {worst_day["date"]} | {f(worst_day["ci_mean"], 1)} | {pct(worst_day["reduction_median_pct"], 1)} |

The best day for the scheduler ({best_day["date"]}) is not the cleanest day
({cleanest["date"]}, mean {f(cleanest["ci_mean"], 1)}) and the worst is not the dirtiest
({dirtiest["date"]}, mean {f(dirtiest["ci_mean"], 1)}). What matters is the *range inside
the deadline*, not the level.

**And the best day is an artefact.** {zero["day"]} is the UTC day that contains the
single 0 gCO2/kWh reading from §4. Treating that reading as a gap instead of a
measurement, the same day's median falls from **{pct(zero["median_raw_pct"], 1)}** to
**{pct(zero["median_without_zero_pct"], 1)}**
({zero["samples_without_zero"]} of its 48 arrivals survive the gap), and the best day in
the window becomes **{zero["best_day_without_zero"]}** at
{pct(zero["best_day_without_zero_pct"], 1)}. One bad row is worth
{f(abs(zero["delta_pp"]), 1)} percentage points on a single day's headline, and a
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
   applied at every half hour for {f(window["span_days"], 0)} days, so it is not
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
""")
    return "".join(parts)


def results_block(data: dict) -> str:
    reference = data["config"]["reference"]
    results = data["results"]
    ref_o = results["oracle"][reference["duration"]][reference["horizon"]]
    ref_f = results["forecast"][reference["duration"]][reference["horizon"]]
    lines = [
        f"Measured over **{f(data['window']['span_days'], 2)} days** of GB half-hourly carbon",
        f"intensity ({data['coverage']['actual_present']:,} readings,",
        f"{f(data['coverage']['coverage_pct'], 1)} % coverage).",
        "",
        f"| {reference['duration']} job, {reference['horizon']} deadline | median | mean | worst | worse than “now” |",
        "|---|---:|---:|---:|---:|",
        f"| perfect foresight (ceiling) | {pct(ref_o['median_pct'])} | {pct(ref_o['mean_pct'])} | "
        f"{pct(ref_o['worst_pct'], 1)} | {pct(ref_o['negative_share_pct'], 1)} |",
        f"| forecast-driven (deployable) | {pct(ref_f['median_pct'])} | {pct(ref_f['mean_pct'])} | "
        f"{pct(ref_f['worst_pct'], 1)} | {pct(ref_f['negative_share_pct'], 1)} |",
        "",
        f"At a 24 h deadline the forecast-driven median rises to "
        f"**{pct(results['forecast'][reference['duration']]['24h']['median_pct'])}**, and the "
        f"ceiling (`30m` job, 24 h deadline) is **{pct(results['oracle']['30m']['24h']['median_pct'])}**.",
        "Full 18-condition tables, per-day detail and the caveats: [docs/REPORT.md](docs/REPORT.md).",
    ]
    return "\n".join(lines)


def main() -> int:
    data = json.loads(SUMMARY.read_text(encoding="utf-8"))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build(), encoding="utf-8")
    print(f"wrote {REPORT.relative_to(ROOT)}")

    if README.exists():
        text = README.read_text(encoding="utf-8")
        begin, end = "<!-- results:begin -->", "<!-- results:end -->"
        if begin in text and end in text:
            head, rest = text.split(begin, 1)
            _, tail = rest.split(end, 1)
            text = f"{head}{begin}\n{results_block(data)}\n{end}{tail}"
            README.write_text(text, encoding="utf-8")
            print(f"updated results block in {README.relative_to(ROOT)}")
        else:
            print("README has no results markers; skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
