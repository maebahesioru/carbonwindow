"""Aggregate reduction rates over a long historical window.

For every half hour ``i`` in the measured window the reporter poses the same
question: *a job of length* ``d`` *arrives now and must finish within* ``T``
*hours — how much cleaner is the best legal start than starting immediately?*

    baseline  = mean CI over [i, i+d)
    chosen    = argmin over s in [i, i+T-d] of mean CI over [s, s+d)
    reduction = (baseline - chosen) / baseline * 100 %

Two decision variants are reported side by side, because conflating them is how
this kind of project usually ends up overstating itself:

``oracle``    the decision is made from measured CI  → a hard upper bound.
``forecast``  the decision is made from the forecast the API archived for those
              half hours *before the fact*, then scored against the measured CI.
              This is what a scheduler could really have done.

Both are scored on measured CI against the same baseline, so the gap between them
is the honest price of not knowing the future.  Nothing is interpolated: if either
window touches a missing half hour the start time is excluded from the sample and
the exclusion is counted in ``dropped``.

Complexity: O(n) per (variant, duration) via a sliding-window minimum, so a 90-day
sweep costs seconds rather than minutes.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from .optimize import SLOT_HOURS, argmin_windows, window_means

DURATION_CHOICES = {"30m": 1, "1h": 2, "2h": 4}
HORIZON_CHOICES = {"6h": 12, "12h": 24, "24h": 48}
REFERENCE = ("1h", "12h")          # the condition used for day-level charts

DEFAULT_POWER_KW = 1.0             # a 1 kWh job for 1 h: energy is stated, never assumed silently


def _stats(sample: list[float]) -> dict:
    """Median / mean / extremes / deciles of a non-empty sample."""
    if not sample:
        return {"n": 0}
    ordered = sorted(sample)
    if len(ordered) >= 10:
        p10 = ordered[int(0.10 * (len(ordered) - 1))]
        p90 = ordered[int(0.90 * (len(ordered) - 1))]
    else:
        p10, p90 = ordered[0], ordered[-1]
    return {
        "n": len(sample),
        "median_pct": round(statistics.median(ordered), 3),
        "mean_pct": round(statistics.fmean(ordered), 3),
        "worst_pct": round(ordered[0], 3),
        "best_pct": round(ordered[-1], 3),
        "p10_pct": round(p10, 3),
        "p90_pct": round(p90, 3),
        "negative_share_pct": round(100.0 * sum(1 for v in ordered if v < 0) / len(ordered), 3),
    }


def evaluate_condition(series, duration_slots: int, horizon_slots: int, decide_on: str,
                       *, power_kw: float = DEFAULT_POWER_KW) -> dict:
    """Every legal start time for one (duration, horizon, information) condition."""
    n = series.slots
    if horizon_slots > n or duration_slots > horizon_slots:
        return {"n": 0, "reason": "window shorter than the condition"}

    decide = series.actual if decide_on == "actual" else series.forecast
    if decide_on == "forecast" and all(v is None for v in decide):
        return {"n": 0, "reason": "no forecast archive in this snapshot"}

    means_decide = window_means(decide, duration_slots)
    means_actual = window_means(series.actual, duration_slots)
    width = horizon_slots - duration_slots + 1
    picks = argmin_windows(means_decide, width)

    energy = power_kw * duration_slots * SLOT_HOURS
    reductions: list[float] = []
    avoided: list[float] = []
    delayed: list[int] = []
    negatives = 0
    dropped = 0

    for now_index in range(0, n - horizon_slots + 1):
        baseline = means_actual[now_index] if now_index < len(means_actual) else None
        pick = picks[now_index] if now_index < len(picks) else None
        if baseline is None or pick is None:
            dropped += 1
            continue
        chosen = means_actual[pick]
        if chosen is None or baseline <= 0:
            dropped += 1
            continue
        reduction = (baseline - chosen) / baseline * 100.0
        reductions.append(reduction)
        avoided.append((baseline - chosen) * energy)
        delayed.append(pick - now_index)
        if reduction < 0:
            negatives += 1

    stats = _stats(reductions)
    stats["dropped"] = dropped
    stats["candidates"] = len(reductions) + dropped
    stats["duration_slots"] = duration_slots
    stats["horizon_slots"] = horizon_slots
    stats["energy_kwh"] = round(energy, 6)
    stats["decide_on"] = decide_on
    if reductions:
        stats["gco2_avoided_median"] = round(statistics.median(avoided), 3)
        stats["gco2_avoided_mean"] = round(statistics.fmean(avoided), 3)
        stats["gco2_avoided_per_kwh_median"] = round(statistics.median(avoided) / energy, 3) \
            if energy else None
        stats["delay_median_slots"] = statistics.median(delayed)
        stats["delay_median_hours"] = round(statistics.median(delayed) * SLOT_HOURS, 2)
        stats["share_moved_later_pct"] = round(100.0 * sum(1 for d in delayed if d > 0) / len(delayed), 3)
    return stats


def day_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def complete_day_keys(series) -> list[str]:
    """UTC days that have all 48 half hours present, in order.

    The snapshot is fetched on half-hour boundaries, so the first and last day are
    usually partial. Day-level statistics and charts use complete days only;
    anything partial would silently average a different number of samples.
    """
    counts: dict[str, int] = {}
    for index, value in enumerate(series.actual):
        if value is None:
            continue
        key = day_key(series.time_of(index))
        counts[key] = counts.get(key, 0) + 1
    return [day for day in sorted(counts) if counts[day] == 48]


def daily_table(series, *, complete_only: bool = True) -> list[dict]:
    """Per-UTC-day: mean measured CI and the reference-condition reduction."""
    duration_slots = DURATION_CHOICES[REFERENCE[0]]
    horizon_slots = HORIZON_CHOICES[REFERENCE[1]]
    n = series.slots
    per_slot = []                       # reduction at each start time, actual-decided
    means_decide = window_means(series.actual, duration_slots)
    width = horizon_slots - duration_slots + 1
    picks = argmin_windows(means_decide, width)
    for now_index in range(0, max(0, n - horizon_slots + 1)):
        base = means_decide[now_index]
        pick = picks[now_index] if now_index < len(picks) else None
        if base is None or pick is None or means_decide[pick] is None or base <= 0:
            per_slot.append((series.time_of(now_index), None))
            continue
        per_slot.append((series.time_of(now_index),
                         (base - means_decide[pick]) / base * 100.0))

    buckets: dict[str, list[float]] = {}
    ciby_day: dict[str, list[float]] = {}
    for index, value in enumerate(series.actual):
        if value is None:
            continue
        ciby_day.setdefault(day_key(series.time_of(index)), []).append(value)
    for when, value in per_slot:
        if value is None:
            continue
        buckets.setdefault(day_key(when), []).append(value)

    keep = set(complete_day_keys(series)) if complete_only else None
    rows = []
    for day in sorted(ciby_day):
        if keep is not None and day not in keep:
            continue
        red = buckets.get(day, [])
        rows.append({
            "date": day,
            "ci_mean": round(statistics.fmean(ciby_day[day]), 2),
            "ci_min": round(min(ciby_day[day]), 2),
            "ci_max": round(max(ciby_day[day]), 2),
            "slots": len(ciby_day[day]),
            "reduction_median_pct": round(statistics.median(red), 3) if red else None,
            "reduction_samples": len(red),
        })
    return rows


def example_day(series, *, duration_slots: int = DURATION_CHOICES[REFERENCE[0]],
                horizon_slots: int = HORIZON_CHOICES[REFERENCE[1]],
                day: str | None = None) -> dict | None:
    """The CI curve of one UTC day with the baseline and the chosen window marked."""
    rows = daily_table(series)
    if not rows:
        return None
    if day is None:
        # deterministic pick: the day with the median reduction, i.e. a typical day
        # for the scheduler rather than a flattering one
        values = [r["reduction_median_pct"] for r in rows if r["reduction_median_pct"] is not None]
        if not values:
            return None
        target = statistics.median(values)
        chosen_row = min(
            (r for r in rows if r["reduction_median_pct"] is not None),
            key=lambda r: (abs(r["reduction_median_pct"] - target), r["date"]))
        day = chosen_row["date"]

    start_dt = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    start_index = series.index_of(start_dt)
    day_slots = 48
    curve = []
    for offset in range(day_slots):
        index = start_index + offset
        if 0 <= index < series.slots:
            curve.append({"t": series.time_of(index).strftime("%H:%M"),
                          "index": index,
                          "actual": series.actual[index],
                          "forecast": series.forecast[index]})

    # One concrete decision from inside that day. The whole horizon has to fit
    # inside the plotted day so both windows are visible, and we take the arrival
    # whose outcome is the median of the day rather than a lucky first one.
    means_decide = window_means(series.forecast, duration_slots)
    means_actual = window_means(series.actual, duration_slots)
    picks = argmin_windows(means_decide, horizon_slots - duration_slots + 1)

    candidates = []
    for offset in range(0, day_slots):
        index = start_index + offset
        if index < 0 or index + horizon_slots > series.slots:
            continue
        if index >= len(means_decide) or means_decide[index] is None:
            continue
        if index >= len(picks) or picks[index] is None:
            continue
        chosen_mean = means_actual[picks[index]]
        if chosen_mean is None or means_actual[index] is None or means_actual[index] <= 0:
            continue
        reduction = (means_actual[index] - chosen_mean) / means_actual[index] * 100.0
        candidates.append((reduction, index))

    if not candidates:
        return {"date": day, "curve": curve, "decision": None}

    median_reduction = statistics.median([r for r, _ in candidates])
    now_index = min(candidates, key=lambda c: (abs(c[0] - median_reduction), c[1]))[1]
    pick = picks[now_index]
    baseline_mean = means_actual[now_index]
    chosen_mean = means_actual[pick]
    return {
        "date": day,
        "duration_slots": duration_slots,
        "horizon_slots": horizon_slots,
        "curve": curve,
        "decision": {
            "now": series.time_of(now_index).strftime("%H:%M"),
            "now_index_offset": now_index - start_index,
            "baseline_mean": round(baseline_mean, 2),
            "chosen": series.time_of(pick).strftime("%H:%M"),
            "chosen_index_offset": pick - start_index,
            "chosen_mean": round(chosen_mean, 2),
            "reduction_pct": round((baseline_mean - chosen_mean) / baseline_mean * 100.0, 3),
            "last_legal_start": series.time_of(now_index + horizon_slots - duration_slots).strftime("%H:%M"),
        },
    }


def data_quality(series) -> dict:
    """Flag readings that look like placeholders rather than measurements.

    The GB grid does not run at 0 gCO2/kWh: over this window the lowest reading
    other than the zeros below is 27.  A single isolated 0 therefore looks like a
    missing value published as zero, so it is counted, dated and reported instead
    of being quietly repaired or quietly used to claim a 100% saving.
    """
    zeros = [series.time_of(i).strftime("%Y-%m-%dT%H:%MZ")
             for i, v in enumerate(series.actual) if v is not None and v == 0]
    positives = [v for v in series.actual if v is not None and v > 0]
    steps = []
    for i in range(1, series.slots):
        a, b = series.actual[i - 1], series.actual[i]
        if a is None or b is None:
            continue
        steps.append(abs(b - a))
    return {
        "zero_readings": zeros,
        "zero_count": len(zeros),
        "min_nonzero": min(positives) if positives else None,
        "max_abs_step": max(steps) if steps else None,
        "note": ("isolated 0 gCO2/kWh readings are treated as published-missing "
                 "values; they are kept in the headline numbers and excluded from "
                 "the sensitivity block"),
    }


def _without_zero_readings(series):
    """The same snapshot with published zeros turned into gaps (no interpolation)."""
    actual = [None if (v == 0) else v for v in series.actual]
    return replace(series, actual=actual)


def sensitivity(series, duration_slots: int, horizon_slots: int) -> dict:
    """Would one suspicious reading move the headline number?"""
    cleaned = _without_zero_readings(series)
    out = {"dropped_readings": data_quality(series)["zero_count"]}
    for variant, decide_on in (("oracle", "actual"), ("forecast", "forecast")):
        raw = evaluate_condition(series, duration_slots, horizon_slots, decide_on)
        clean = evaluate_condition(cleaned, duration_slots, horizon_slots, decide_on)
        out[variant] = {
            "median_raw": raw.get("median_pct"),
            "median_without_zeros": clean.get("median_pct"),
            "delta": (None if raw.get("median_pct") is None or clean.get("median_pct") is None
                      else round(clean["median_pct"] - raw["median_pct"], 3)),
            "best_raw": raw.get("best_pct"),
            "best_without_zeros": clean.get("best_pct"),
            "dropped": clean.get("dropped"),
        }
    return out


def heatmap(series) -> dict:
    """CI by (UTC day, half-hour slot) — the shape behind the web heatmap."""
    days = complete_day_keys(series)
    position = {day: k for k, day in enumerate(days)}
    grid: list[list[float | None]] = [[None] * len(days) for _ in range(48)]
    for index, value in enumerate(series.actual):
        when = series.time_of(index)
        column = position.get(day_key(when))
        if column is None:            # a partial boundary day is not charted
            continue
        slot = when.hour * 2 + when.minute // 30
        grid[slot][column] = value
    return {
        "days": days,
        "slots": [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)],
        "values": grid,
    }


def reference_reductions(series) -> dict:
    """Per-arrival reduction at the reference condition, for both variants.

    Kept as time series so the report page can show the distribution *and* the
    bad days rather than only a median that hides them.
    """
    duration_slots = DURATION_CHOICES[REFERENCE[0]]
    horizon_slots = HORIZON_CHOICES[REFERENCE[1]]
    means_actual = window_means(series.actual, duration_slots)
    width = horizon_slots - duration_slots + 1
    out: dict[str, list] = {"start_utc": [], "oracle": [], "forecast": []}
    picks = {}
    for variant, decide in (("oracle", series.actual),
                            ("forecast", series.forecast if any(v is not None for v in series.forecast)
                             else series.actual)):
        picks[variant] = argmin_windows(window_means(decide, duration_slots), width)

    for now_index in range(0, max(0, series.slots - horizon_slots + 1)):
        baseline = means_actual[now_index] if now_index < len(means_actual) else None
        out["start_utc"].append(series.time_of(now_index).strftime("%Y-%m-%dT%H:%MZ"))
        for variant in ("oracle", "forecast"):
            pick = picks[variant][now_index] if now_index < len(picks[variant]) else None
            if baseline is None or baseline <= 0 or pick is None or means_actual[pick] is None:
                out[variant].append(None)
            else:
                out[variant].append(round((baseline - means_actual[pick]) / baseline * 100.0, 3))
    return out


def zero_day_effect(series) -> dict:
    """How much of the *day-level* ranking rests on the implausible 0 readings.

    The window medians barely move when the 0 is dropped (it is 1 half hour out of
    thousands), but a day only has 48 of them, so the same reading can decide which
    day looks best. Re-ranking with the 0 turned back into a gap shows that.
    """
    quality = data_quality(series)
    if not quality["zero_count"]:
        return {"applicable": False}

    clean = _without_zero_readings(series)

    def per_day(block: dict) -> dict[str, float]:
        buckets: dict[str, list[float]] = {}
        for stamp, value in zip(block["start_utc"], block["oracle"]):
            if value is not None:
                buckets.setdefault(stamp[:10], []).append(value)
        return {day: statistics.median(v) for day, v in buckets.items()}

    raw_block = reference_reductions(series)
    fixed_block = reference_reductions(clean)
    raw = per_day(raw_block)
    fixed = per_day(fixed_block)
    zero_day = quality["zero_readings"][0][:10]
    best_fixed = max(fixed.items(), key=lambda kv: kv[1])
    best_raw = max(raw.items(), key=lambda kv: kv[1])
    return {
        "applicable": True,
        "day": zero_day,
        "median_raw_pct": round(raw[zero_day], 3) if zero_day in raw else None,
        "median_without_zero_pct": round(fixed[zero_day], 3) if zero_day in fixed else None,
        "samples_without_zero": sum(
            1 for stamp, value in zip(fixed_block["start_utc"], fixed_block["oracle"])
            if value is not None and stamp.startswith(zero_day)),
        "best_day_raw": best_raw[0],
        "best_day_raw_pct": round(best_raw[1], 3),
        "best_day_without_zero": best_fixed[0],
        "best_day_without_zero_pct": round(best_fixed[1], 3),
        "delta_pp": (round(raw[zero_day] - fixed[zero_day], 3)
                     if zero_day in raw and zero_day in fixed else None),
    }


def build_report(series, *, power_kw: float = DEFAULT_POWER_KW,
                 durations: dict | None = None, horizons: dict | None = None,
                 coordinates: dict | None = None) -> dict:
    """The full measured report as a JSON-ready dict."""
    durations = durations or DURATION_CHOICES
    horizons = horizons or HORIZON_CHOICES
    results: dict[str, dict[str, dict[str, dict]]] = {}

    for variant in ("oracle", "forecast"):
        decide_on = "actual" if variant == "oracle" else "forecast"
        results[variant] = {}
        for dname, dslots in durations.items():
            results[variant][dname] = {}
            for hname, hslots in horizons.items():
                results[variant][dname][hname] = evaluate_condition(
                    series, dslots, hslots, decide_on, power_kw=power_kw)

    ci_values = [v for v in series.actual if v is not None]
    span_days = round(series.slots * SLOT_HOURS / 24.0, 2)
    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": {
            "start_utc": series.start.strftime("%Y-%m-%dT%H:%MZ"),
            "end_utc": (series.start + timedelta(minutes=30 * series.slots)).strftime("%Y-%m-%dT%H:%MZ"),
            "span_days": span_days,
        },
        "coverage": series.coverage(),
        "ci_stats": {
            "mean": round(statistics.fmean(ci_values), 2) if ci_values else None,
            "median": round(statistics.median(ci_values), 2) if ci_values else None,
            "min": round(min(ci_values), 2) if ci_values else None,
            "max": round(max(ci_values), 2) if ci_values else None,
            "index_counts": _index_counts(series),
            "forecast_error": forecast_error(series),
        },
        "config": {
            "power_kw": power_kw,
            "durations": durations,
            "horizons": horizons,
            "reference": {"duration": REFERENCE[0], "horizon": REFERENCE[1]},
            "slot_minutes": 30,
            "unit": "gCO2/kWh (National Grid ESO Carbon Intensity, GB national average)",
        },
        "results": results,
        "daily": daily_table(series),
        "example": example_day(series),
        "heatmap": heatmap(series),
        "reference_reductions": reference_reductions(series),
        "data_quality": data_quality(series),
        "zero_day_effect": zero_day_effect(series),
        "sensitivity": sensitivity(series, DURATION_CHOICES[REFERENCE[0]],
                                   HORIZON_CHOICES[REFERENCE[1]]),
    }
    if coordinates:
        report["coordinates"] = coordinates
    return report


def _index_counts(series) -> dict:
    """Count half hours per National Grid ESO band (0-49 … 200+)."""
    bands = [("very low", 0, 50), ("low", 50, 100), ("moderate", 100, 150),
             ("high", 150, 200), ("very high", 200, 10 ** 9)]
    counts = {name: 0 for name, _, _ in bands}
    for value in series.actual:
        if value is None:
            continue
        for name, low, high in bands:
            if low <= value < high:
                counts[name] += 1
                break
    return counts


def forecast_error(series) -> dict:
    """How accurate the archived forecast was — the reason ``forecast`` exists.

    The ``forecast`` field the API keeps for a past half hour is the value that was
    published before the fact, so the gap between it and ``actual`` is a real
    out-of-sample error, not a modelling artefact of this project.
    """
    errors = [abs(a - f) for a, f in zip(series.actual, series.forecast)
              if a is not None and f is not None]
    if not errors:
        return {"n": 0}
    ordered = sorted(errors)
    index = min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))
    return {
        "n": len(errors),
        "mae": round(statistics.fmean(errors), 3),
        "median_abs": round(statistics.median(ordered), 3),
        "p95_abs": round(ordered[index], 3),
        "max_abs": round(ordered[-1], 3),
    }


def compare_table(report: dict) -> list[dict]:
    """Flatten the results into rows for the markdown table in docs/REPORT.md."""
    rows = []
    for variant, by_duration in report["results"].items():
        for dname, by_horizon in by_duration.items():
            for hname, stats in by_horizon.items():
                if not stats.get("n"):
                    continue
                rows.append({
                    "variant": variant,
                    "duration": dname,
                    "horizon": hname,
                    "n": stats["n"],
                    "median": stats["median_pct"],
                    "mean": stats["mean_pct"],
                    "worst": stats["worst_pct"],
                    "best": stats["best_pct"],
                    "negative_share": stats.get("negative_share_pct"),
                    "gco2_median": stats.get("gco2_avoided_median"),
                })
    return rows
