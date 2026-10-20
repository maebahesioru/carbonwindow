"""Choosing the lowest-carbon half hour to start a job.

Two things matter here.

**It has to be exact.**  A greedy "start at the cheapest half hour" heuristic and a
sliding-window minimum look identical on a smooth curve and disagree on a spiky one,
so :func:`best_window` computes the arithmetic mean of the job's whole runtime and
takes the true minimum.  The window is ``k`` consecutive half hours beginning at
``s``; the mean is ``(P[s+k] - P[s]) / k`` from a prefix sum, so every candidate is
O(1) and the scan is O(n).  The bounded version used by the reporter keeps the same
complexity with a monotonic deque (:func:`argmin_windows`) rather than rescanning
each allowed range.

**Ties are resolved deterministically** toward the earliest start, so two runs over
the same snapshot never disagree.

Missing data is never interpolated.  A window that touches a missing half hour is
skipped, and a query whose every candidate window touches one returns ``None``
instead of a number that looks like a measurement.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, asdict
from typing import Sequence

SLOT_HOURS = 0.5


# --------------------------------------------------------------------------- #
# prefix sums with gap awareness
# --------------------------------------------------------------------------- #
def _prefix(values: Sequence[float | None]) -> tuple[list[float], list[int]]:
    """Prefix sums and prefix counts of missing entries."""
    total = 0.0
    missing = 0
    sums = [0.0] * (len(values) + 1)
    gaps = [0] * (len(values) + 1)
    for index, value in enumerate(values):
        if value is None:
            missing += 1
        else:
            total += value
        sums[index + 1] = total
        gaps[index + 1] = missing
    return sums, gaps


def window_means(values: Sequence[float | None], k: int) -> list[float | None]:
    """Mean of every length-``k`` window; ``None`` where the window has a gap."""
    if k <= 0:
        raise ValueError("window length must be positive")
    if k > len(values):
        return []
    sums, gaps = _prefix(values)
    out: list[float | None] = []
    for start in range(len(values) - k + 1):
        if gaps[start + k] != gaps[start]:
            out.append(None)
            continue
        out.append((sums[start + k] - sums[start]) / k)
    return out


def argmin_windows(means: Sequence[float | None], width: int) -> list[int | None]:
    """Index of the smallest element of ``means[i : i+width]`` for every ``i``.

    Monotonic-deque sliding minimum: O(len(means)) total.  ``None`` entries are
    treated as "not a candidate"; a range with no usable entry yields ``None``.
    """
    if width <= 0:
        raise ValueError("width must be positive")
    n = len(means)
    if width > n:
        return []
    queue: deque[int] = deque()    # indices into means, values non-decreasing
    out: list[int | None] = []
    for right in range(n):
        value = means[right]
        if value is not None:
            while queue and means[queue[-1]] >= value:   # '>=' prefers earliest index
                queue.pop()
            queue.append(right)
        while queue and queue[0] < right - width + 1:
            queue.popleft()
        if right >= width - 1:
            out.append(queue[0] if queue else None)
    return out


# --------------------------------------------------------------------------- #
# job planning
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Plan:
    """One scheduling decision plus the counterfactual it is measured against."""

    baseline_index: int
    baseline_mean: float
    chosen_index: int
    chosen_mean: float
    reduction_pct: float
    duration_slots: int
    horizon_slots: int
    energy_kwh: float
    gco2_baseline: float
    gco2_chosen: float
    gco2_avoided: float

    def as_dict(self) -> dict:
        return asdict(self)


def best_window(values: Sequence[float | None], k: int,
                lo: int = 0, hi: int | None = None) -> tuple[int, float] | None:
    """Strict minimum mean over start positions ``lo..hi`` (inclusive), window ``k``.

    ``hi`` defaults to the last legal start.  Returns ``(start_index, mean)`` or
    ``None`` when no candidate window is free of gaps.
    """
    means = window_means(values, k)
    if not means:
        return None
    last = len(means) - 1
    lo = max(0, lo)
    hi = last if hi is None else min(last, hi)
    best: tuple[int, float] | None = None
    for start in range(lo, hi + 1):
        value = means[start]
        if value is None:
            continue
        if best is None or value < best[1]:      # strict '<' keeps the earliest start
            best = (start, value)
    return best


def brute_force_best_window(values: Sequence[float | None], k: int,
                            lo: int = 0, hi: int | None = None) -> tuple[int, float] | None:
    """Reference implementation used by the test-suite: sum each window in full."""
    n = len(values)
    last = n - k
    if last < 0:
        return None
    hi = last if hi is None else min(last, hi)
    best: tuple[int, float] | None = None
    for start in range(max(0, lo), hi + 1):
        total = 0.0
        ok = True
        for offset in range(k):
            value = values[start + offset]
            if value is None:
                ok = False
                break
            total += value
        if not ok:
            continue
        mean = total / k
        if best is None or mean < best[1]:
            best = (start, mean)
    return best


def plan_job(series, now_index: int, duration_slots: int, horizon_slots: int,
             *, decide_on: str = "actual", power_kw: float = 1.0) -> Plan | None:
    """Plan one job that starts at or after ``now_index`` and must finish within
    ``horizon_slots`` of it.

    ``decide_on`` picks the series the decision is made from: ``"actual"`` is the
    perfect-information (oracle) upper bound, ``"forecast"`` is what a scheduler
    running in real time could actually have known.  The plan is always *scored*
    on ``actual`` so both variants are comparable to the same baseline.

    Returns ``None`` when there is no complete window to compare.
    """
    if decide_on not in ("actual", "forecast"):
        raise ValueError("decide_on must be 'actual' or 'forecast'")
    if duration_slots <= 0 or horizon_slots < duration_slots:
        raise ValueError("horizon must be at least the job duration")
    if now_index < 0 or now_index + horizon_slots > series.slots:
        return None

    actual = series.actual
    decide = actual if decide_on == "actual" else series.forecast

    baseline_window = actual[now_index:now_index + duration_slots]
    if len(baseline_window) != duration_slots or any(v is None for v in baseline_window):
        return None
    baseline_mean = sum(baseline_window) / duration_slots

    lo = now_index
    hi = now_index + horizon_slots - duration_slots
    chosen_on_decider = best_window(decide, duration_slots, lo, hi)
    if chosen_on_decider is None:
        return None
    chosen_index = chosen_on_decider[0]

    scored = actual[chosen_index:chosen_index + duration_slots]
    if len(scored) != duration_slots or any(v is None for v in scored):
        return None
    chosen_mean = sum(scored) / duration_slots

    energy = power_kw * duration_slots * SLOT_HOURS
    reduction = (baseline_mean - chosen_mean) / baseline_mean * 100.0 if baseline_mean else 0.0
    return Plan(
        baseline_index=now_index,
        baseline_mean=baseline_mean,
        chosen_index=chosen_index,
        chosen_mean=chosen_mean,
        reduction_pct=reduction,
        duration_slots=duration_slots,
        horizon_slots=horizon_slots,
        energy_kwh=energy,
        gco2_baseline=baseline_mean * energy,
        gco2_chosen=chosen_mean * energy,
        gco2_avoided=(baseline_mean - chosen_mean) * energy,
    )
