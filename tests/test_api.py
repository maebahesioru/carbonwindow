"""Parsing the API's real payload shape, and the two behaviours that bite.

The fixture is six consecutive rows copied verbatim from a live
``/intensity/{from}/{to}`` response, including the row that *starts before* the
requested ``from`` — that row is the reason naive concatenation duplicates data.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from carbonwindow import ci_api
from carbonwindow.ci_api import (
    Interval, chunk_ranges, parse_intensity_payload, to_series,
)

FIXTURE = Path(__file__).parent / "fixtures" / "intensity_sample.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_has_the_shape_the_api_actually_returns():
    payload = load_fixture()
    assert set(payload) == {"data"}
    row = payload["data"][0]
    assert set(row) == {"from", "to", "intensity"}
    assert set(row["intensity"]) == {"forecast", "actual", "index"}


def test_parse_returns_utc_intervals_in_order():
    intervals = parse_intensity_payload(load_fixture())
    assert len(intervals) == 6
    first = intervals[0]
    assert first.start == datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)
    assert first.end == datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    assert first.actual == 179
    assert first.forecast == 157
    assert first.index == "high"
    assert first.end - first.start == timedelta(minutes=30)
    # the API really does hand back a row that begins before the requested "from"
    assert intervals[0].start < datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_missing_actual_is_preserved_as_none():
    payload = load_fixture()
    payload["data"][2]["intensity"]["actual"] = None
    intervals = parse_intensity_payload(payload)
    assert intervals[2].actual is None
    assert intervals[2].forecast == 189


def test_payload_without_data_is_rejected():
    with pytest.raises(ValueError):
        parse_intensity_payload({"error": "nope"})


def test_chunks_never_exceed_fourteen_days():
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 10, 21, tzinfo=timezone.utc)
    spans = chunk_ranges(start, end)
    assert spans[0][0] == start and spans[-1][1] == end
    for span_start, span_end in spans:
        assert span_end - span_start <= timedelta(days=14)
        assert span_end > span_start
    # contiguous, with no gap and no overlap
    for (_, prev_end), (next_start, _) in zip(spans, spans[1:]):
        assert prev_end == next_start


def test_to_series_lays_intervals_on_a_dense_grid():
    payload = load_fixture()
    payload["data"][1]["intensity"]["actual"] = None
    payload["data"][1]["intensity"]["forecast"] = None
    series = to_series(parse_intensity_payload(payload))
    assert series.slots == 6
    assert series.actual[0] == 179.0
    assert series.actual[1] is None          # a gap stays a gap
    assert series.forecast[1] is None
    assert series.time_of(0) == datetime(2026, 9, 30, 23, 30, tzinfo=timezone.utc)
    assert series.time_of(1) - series.time_of(0) == timedelta(minutes=30)
    coverage = series.coverage()
    assert coverage["actual_present"] == 5
    assert coverage["actual_missing"] == 1


def test_overlapping_chunks_are_de_duplicated_by_start_time():
    payload = load_fixture()
    intervals = parse_intensity_payload(payload)
    # simulate two adjacent chunks overlapping on the boundary half hour
    combined = ci_api._dedupe(intervals + intervals[:2])
    assert len(combined) == len(intervals)
    assert [i.start for i in combined] == sorted(i.start for i in intervals)


def test_cached_chunk_is_not_refetched(tmp_path, monkeypatch):
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    end = datetime(2026, 10, 2, tzinfo=timezone.utc)
    path = ci_api.cache_path(tmp_path, start, end)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    def explode(*_args, **_kwargs):
        raise AssertionError("network was used for a cached chunk")

    monkeypatch.setattr(ci_api, "http_json", explode)
    intervals = ci_api.fetch_intensity(start, end, cache_dir=tmp_path, sleep=0.0)
    assert len(intervals) == 6


def test_round_trip_through_disk(tmp_path):
    series = to_series(parse_intensity_payload(load_fixture()))
    path = ci_api.save_series(series, tmp_path / "s.json", meta={"k": "v"})
    again = ci_api.load_series(path)
    assert again.start == series.start
    assert again.actual == series.actual
    assert again.forecast == series.forecast


def test_interval_from_api_tolerates_missing_fields():
    row = {"from": "2026-10-01T00:00Z", "to": "2026-10-01T00:30Z",
           "intensity": {"forecast": 100, "actual": None, "index": "low"}}
    interval = Interval.from_api(row)
    assert interval.actual is None
    assert interval.forecast == 100
