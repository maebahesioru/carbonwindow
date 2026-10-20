"""The optimiser must agree with an exhaustive search, not merely look plausible.

Every window is summed one element at a time in the reference implementation, so
the two agree only if the sliding-window maths is genuinely exact.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from carbonwindow.ci_api import GridSeries
from carbonwindow.optimize import (
    argmin_windows, best_window, brute_force_best_window, plan_job, window_means,
)

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_best_window_matches_brute_force_on_random_series():
    rng = random.Random(20261020)
    for trial in range(60):
        n = rng.randint(1, 60)
        values = [float(rng.randint(0, 400)) for _ in range(n)]
        k = rng.randint(1, n)
        expected = brute_force_best_window(values, k)
        actual = best_window(values, k)
        assert actual is not None and expected is not None
        assert actual[0] == expected[0], f"trial {trial}: start {actual} vs {expected}"
        assert actual[1] == pytest.approx(expected[1], abs=1e-12), f"trial {trial}"


def test_best_window_matches_brute_force_with_bounded_deadline():
    """The bounded query (deadline) must agree too — this is the shipped path."""
    rng = random.Random(7)
    for trial in range(60):
        n = rng.randint(4, 50)
        values = [float(rng.randint(0, 300)) for _ in range(n)]
        k = rng.randint(1, min(6, n))
        lo = rng.randint(0, n - k)
        hi = rng.randint(lo, n - k)
        expected = brute_force_best_window(values, k, lo, hi)
        actual = best_window(values, k, lo, hi)
        assert (actual is None) == (expected is None), f"trial {trial}"
        if expected:
            assert actual[0] == expected[0], f"trial {trial}: {actual} vs {expected}"
            assert actual[1] == pytest.approx(expected[1], abs=1e-12)


def test_sliding_argmin_matches_rescan():
    rng = random.Random(99)
    for trial in range(40):
        n = rng.randint(1, 40)
        means = [round(rng.uniform(0, 200), 3) for _ in range(n)]
        width = rng.randint(1, n)
        sliding = argmin_windows(means, width)
        assert len(sliding) == n - width + 1
        for i, chosen in enumerate(sliding):
            window = means[i:i + width]
            best_value = min(window)
            assert means[chosen] == pytest.approx(best_value), f"trial {trial} i={i}"
            # determinism: a tie must resolve to the earliest absolute index
            assert chosen == i + window.index(best_value), f"trial {trial} i={i} tie-break"


def test_window_means_are_plain_arithmetic_means():
    values = [10.0, 20.0, 30.0, 40.0]
    assert window_means(values, 1) == [10.0, 20.0, 30.0, 40.0]
    assert window_means(values, 2) == [15.0, 25.0, 35.0]
    assert window_means(values, 4) == [25.0]
    assert window_means(values, 5) == []


def test_missing_values_are_skipped_not_interpolated():
    values = [100.0, None, 10.0, 10.0, 200.0]
    # a window that touches the gap is not a candidate
    assert window_means(values, 2) == [None, None, 10.0, 105.0]
    # the global optimum is still found among the windows that are complete
    assert best_window(values, 2) == (2, 10.0)
    assert best_window(values, 2, 0, 1) is None
    assert brute_force_best_window(values, 2) == best_window(values, 2)


def test_greedy_cheapest_half_hour_is_not_the_optimum():
    """A realistic counter-example: the single cheapest slot is a one-off dip that
    cannot carry a 2 h job, while a slightly higher plateau averages better."""
    plateau = [120.0] * 4            # 120 for 2 h
    spike_dip = [40.0, 300.0, 300.0, 300.0]   # cheap start, terrible tail
    values = spike_dip + plateau
    assert best_window(values, 4) == (4, 120.0)
    # a "start at the cheapest slot" heuristic would have picked index 0 (=235.0)
    assert sum(values[0:4]) / 4 == pytest.approx(235.0)


class FakeSeries:
    def __init__(self, actual, forecast=None, start=None):
        from datetime import datetime, timezone
        self.start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.actual = list(actual)
        self.forecast = list(forecast if forecast is not None else actual)

    @property
    def slots(self):
        return len(self.actual)

    def time_of(self, index):
        from datetime import timedelta
        return self.start + timedelta(minutes=30 * index)

    def index_of(self, when):
        from datetime import timedelta
        return int((when - self.start) // timedelta(minutes=30))


def test_plan_job_prefers_the_clean_plateau():
    series = FakeSeries([200.0, 200.0] + [50.0] * 4 + [200.0] * 6)
    plan = plan_job(series, 0, duration_slots=2, horizon_slots=12, decide_on="actual")
    assert plan is not None
    assert plan.baseline_index == 0
    assert plan.baseline_mean == pytest.approx(200.0)
    assert plan.chosen_index == 2
    assert plan.chosen_mean == pytest.approx(50.0)
    assert plan.reduction_pct == pytest.approx(75.0)
    assert plan.energy_kwh == pytest.approx(1.0)
    assert plan.gco2_avoided == pytest.approx(150.0)


def test_plan_job_respects_the_deadline():
    """The cheapest window sits past the deadline, so it is not allowed."""
    series = FakeSeries([200.0] * 4 + [10.0] * 4)     # cheap block starts at slot 4
    tight = plan_job(series, 0, duration_slots=2, horizon_slots=4, decide_on="actual")
    assert tight is not None and tight.chosen_index == 0     # cannot reach slot 4
    assert tight.reduction_pct == pytest.approx(0.0)
    loose = plan_job(series, 0, duration_slots=2, horizon_slots=8, decide_on="actual")
    assert loose is not None and loose.chosen_index == 4
    assert loose.reduction_pct == pytest.approx(95.0)


def test_plan_job_reports_no_plan_when_data_is_missing():
    series = FakeSeries([100.0, None, 100.0, 100.0])
    assert plan_job(series, 0, duration_slots=2, horizon_slots=4, decide_on="actual") is None


def test_plan_job_horizon_must_fit_the_snapshot():
    series = FakeSeries([100.0] * 4)
    assert plan_job(series, 2, duration_slots=2, horizon_slots=48, decide_on="actual") is None


def test_forecast_decision_is_verified_against_the_forecast_series():
    """A forecast decision must be brute-forced on the forecast, not on the actuals.

    Regression: the CLI's `--brute-force-check` compared the chosen window's
    *measured* mean against a brute force over *measured* values, so any honest
    forecast decision that disagreed with hindsight was reported as a MISMATCH.
    The check has to re-minimise the same series the decision was made from.
    """
    actual = [100.0] * 24
    forecast = [100.0] * 24
    forecast[4] = forecast[5] = 10.0     # the forecast thinks the 4-5 window is cheap
    actual[8] = actual[9] = 60.0         # in hindsight the 8-9 window was cheapest
    series = GridSeries(start=START, actual=actual, forecast=forecast)

    plan = plan_job(series, 0, duration_slots=2, horizon_slots=12, decide_on="forecast")
    assert plan is not None
    assert plan.chosen_index == 4                      # decided on the forecast

    on_forecast = brute_force_best_window(series.forecast, 2, 0, 12 - 2)
    on_actual = brute_force_best_window(series.actual, 2, 0, 12 - 2)
    assert on_forecast[0] == plan.chosen_index
    # The measured best window is a different one: 8, not 4. The old check compared
    # that measured mean (60) with the plan's measured mean at slot 4 (100) and
    # called an honest forecast decision a MISMATCH.
    assert on_actual[0] == 8
    assert on_actual[1] == pytest.approx(60.0)
    assert plan.chosen_mean == pytest.approx(100.0)
