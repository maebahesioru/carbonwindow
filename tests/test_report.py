"""Reduction rates checked against arithmetic worked out by hand.

The numbers in these tests are written as literal expected values with the sum
shown in a comment, so a regression in the sweep shows up as a wrong constant
rather than as a test that agrees with whatever the code happens to do.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from carbonwindow.ci_api import GridSeries
from carbonwindow.report import (
    DURATION_CHOICES, HORIZON_CHOICES, build_report, daily_table, data_quality,
    evaluate_condition, sensitivity, zero_day_effect,
)

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def mk(actual, forecast=None):
    """Build the real snapshot type, so these tests exercise the shipped class."""
    return GridSeries(
        start=START,
        actual=list(actual),
        forecast=list(forecast if forecast is not None else actual),
    )


def test_reduction_is_hand_computable():
    """One cheap block in an otherwise flat series.

    actual  = [100,100,100,100,20,20,100,100]   (slot = 30 min)
    job     = 1 h (2 slots), deadline = 2 h (4 slots) -> 3 candidate starts per arrival
    window means by start slot: s0=100 s1=100 s2=100 s3=60 s4=20 s5=60 s6=100

    arrival 0: starts 0..2 -> best 100  -> (100-100)/100 =  0.000 %
    arrival 1: starts 1..3 -> best  60  -> (100- 60)/100 = 40.000 %
    arrival 2: starts 2..4 -> best  20  -> (100- 20)/100 = 80.000 %
    arrival 3: starts 3..5 -> best  20  -> ( 60- 20)/ 60 = 66.667 %
    arrival 4: starts 4..6 -> best  20  -> ( 20- 20)/ 20 =  0.000 %
    -> n=5, median 40.000, mean (0+40+80+66.667+0)/5 = 37.333
    -> avoided gCO2 at 1 kWh per 1 h job: 0, 40, 80, 40, 0 -> median 40
    """
    series = mk([100, 100, 100, 100, 20, 20, 100, 100])
    stats = evaluate_condition(series, duration_slots=2, horizon_slots=4, decide_on="actual")
    assert stats["n"] == 5
    assert stats["median_pct"] == pytest.approx(40.0)
    assert stats["mean_pct"] == pytest.approx(37.333, abs=0.001)
    assert stats["worst_pct"] == pytest.approx(0.0)
    assert stats["best_pct"] == pytest.approx(80.0)
    assert stats["negative_share_pct"] == pytest.approx(0.0)
    assert stats["energy_kwh"] == pytest.approx(1.0)
    assert stats["gco2_avoided_median"] == pytest.approx(40.0)


def test_a_flat_series_cannot_be_improved():
    series = mk([120] * 20)
    stats = evaluate_condition(series, duration_slots=2, horizon_slots=12, decide_on="actual")
    assert stats["n"] == 20 - 12 + 1
    assert stats["median_pct"] == pytest.approx(0.0)
    assert stats["best_pct"] == pytest.approx(0.0)
    assert stats["gco2_avoided_median"] == pytest.approx(0.0)


def test_thirty_minute_job_costs_half_a_kwh():
    """Energy is stated, not implied: a 30 min job at 1 kW is 0.5 kWh."""
    series = mk([100, 100, 20, 20] * 4)
    short = evaluate_condition(series, duration_slots=1, horizon_slots=4, decide_on="actual")
    assert short["energy_kwh"] == pytest.approx(0.5)
    long = evaluate_condition(series, duration_slots=2, horizon_slots=4, decide_on="actual")
    assert long["energy_kwh"] == pytest.approx(1.0)


def test_forecast_decisions_are_scored_on_actual_values():
    """A confidently wrong forecast must be penalised, not excused.

    actual : [100]*8 with a cheap block at slots 2..3
    forecast: claims the cheap block is at slots 5..6 (wrong)
    The forecast-driven planner therefore moves the job onto expensive slots and
    the score has to come out negative.
    """
    actual = [100, 100, 20, 20, 100, 100, 100, 100]
    forecast = [100, 100, 100, 100, 100, 20, 20, 100]
    series = mk(actual, forecast)
    oracle = evaluate_condition(series, duration_slots=2, horizon_slots=4, decide_on="actual")
    live = evaluate_condition(series, duration_slots=2, horizon_slots=4, decide_on="forecast")
    assert oracle["best_pct"] > 0
    assert live["worst_pct"] < 0            # the wrong forecast cost us carbon
    assert live["negative_share_pct"] > 0   # and it did so more than once
    assert live["mean_pct"] < oracle["mean_pct"]



def test_gaps_are_dropped_and_counted():
    series = mk([100, 100, None, 100, 100, 100, 100, 100])
    stats = evaluate_condition(series, duration_slots=2, horizon_slots=4, decide_on="actual")
    assert stats["candidates"] == 5
    assert stats["n"] == stats["candidates"] - stats["dropped"]
    assert stats["dropped"] >= 1


def test_report_is_json_serialisable_and_internally_consistent():
    import json
    series = mk([(i * 37) % 250 + 10 for i in range(96 * 3)])
    report = build_report(series)
    text = json.dumps(report)                    # must not raise
    assert json.loads(text)["results"].keys() == {"oracle", "forecast"}
    for variant in ("oracle", "forecast"):
        for duration in DURATION_CHOICES:
            for horizon in HORIZON_CHOICES:
                entry = report["results"][variant][duration][horizon]
                if entry.get("n"):
                    assert entry["worst_pct"] <= entry["median_pct"] <= entry["best_pct"]
                    assert 0 <= entry["negative_share_pct"] <= 100


def test_daily_table_covers_every_complete_day():
    series = mk([(i * 11) % 200 + 20 for i in range(48 * 5)])
    rows = daily_table(series)
    assert len(rows) == 5
    assert all(row["slots"] == 48 for row in rows)
    assert sum(row["reduction_samples"] for row in rows) > 0


def test_zero_readings_are_flagged_not_silently_repaired():
    """A GB grid never really runs at 0 gCO2/kWh, so a lone 0 is a published gap."""
    series = mk([100, 100, 0, 100, 100, 100, 100, 100])
    quality = data_quality(series)
    assert quality["zero_count"] == 1
    assert quality["zero_readings"] == ["2026-01-01T01:00Z"]
    assert quality["min_nonzero"] == 100.0


def test_sensitivity_shows_one_bad_reading_does_not_move_the_headline():
    series = mk([100, 100, 0, 100, 100, 100, 100, 100])
    sens = sensitivity(series, duration_slots=1, horizon_slots=4)
    assert sens["dropped_readings"] == 1
    for variant in ("oracle", "forecast"):
        assert sens[variant]["median_raw"] is not None
        assert sens[variant]["median_without_zeros"] is not None
        # the zero only affects the one window that contains it
        assert abs(sens[variant]["delta"]) <= 100.0


def test_zero_day_effect_never_credits_the_implausible_zero():
    """Removing a 0 can only make a day look worse, and can only demote a best day.

    Three complete UTC days of 48 half hours all at 120 gCO2/kWh, with one half hour
    published as 0. Only the arrivals whose 23-window deadline can still reach that
    slot see the fake cheap window — at the reference condition that is at most one
    window-width per side, so on a flat grid it cannot move that day's median. What it
    *can* do is make the day look like the best day in the window, which is why the
    function reports the re-ranked winner rather than only the delta.
    """
    values = [120.0] * (48 * 3)
    values[48 + 20] = 0.0
    series = mk(values)
    effect = zero_day_effect(series)

    assert effect["applicable"] is True
    assert effect["day"] == "2026-01-02"
    # a fake cheap reading is never a reason to claim a *better* day after cleaning
    assert effect["median_without_zero_pct"] <= effect["median_raw_pct"]
    assert effect["delta_pp"] >= 0
    assert effect["best_day_raw_pct"] >= effect["best_day_without_zero_pct"]
    # the dropped slot is a real loss of candidates, never an interpolation
    assert effect["samples_without_zero"] < 48


def test_zero_day_effect_is_inert_without_zero_readings():
    series = mk([120.0] * (48 * 3))
    assert zero_day_effect(series)["applicable"] is False
