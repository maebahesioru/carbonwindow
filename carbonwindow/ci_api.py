"""Access to the UK National Grid ESO Carbon Intensity API.

Why this module exists
----------------------
The API is free and needs no key, but it has two behaviours that will silently
corrupt a naive implementation:

1. ``/intensity/{from}/{to}`` returns an interval that *starts before* ``from``
   (the half hour that contains ``from``).  Concatenating chunks naively
   produces duplicated and out-of-order rows.
2. A single request may span at most 14 days.  Longer spans must be chunked.

So every response is normalised to half-hour intervals keyed by ``start``
(UTC), de-duplicated, sorted, and cached on disk as the raw JSON.  ``load_series``
turns those snapshots into a dense, gap-aware :class:`GridSeries`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = "https://api.carbonintensity.org.uk"
SLOT = timedelta(minutes=30)
MAX_CHUNK = timedelta(days=14)          # documented maximum span per request
USER_AGENT = "CarbonWindow/1.0 (+IEEE ClimateChain hackathon project; local research)"


class ApiError(RuntimeError):
    """Raised when a request keeps failing after every retry."""


def _parse_ts(value: str) -> datetime:
    """Parse the API's ISO-8601 timestamps (always UTC, 'Z' suffix)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _fmt_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def http_json(url: str, *, retries: int = 5, timeout: float = 30.0,
              backoff: float = 2.0, sleep: float = 0.0) -> dict:
    """GET ``url`` and decode JSON, retrying transient failures with backoff."""
    if sleep:
        time.sleep(sleep)
    last: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                      "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
            return json.loads(payload)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                json.JSONDecodeError) as exc:      # noqa: PERF203 - retry loop
            last = exc
            if attempt + 1 < retries:
                time.sleep(backoff ** attempt)
    raise ApiError(f"GET {url} failed after {retries} attempts: {last}") from last


# --------------------------------------------------------------------------- #
# interval model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime
    actual: int | None
    forecast: int | None
    index: str

    @classmethod
    def from_api(cls, row: dict) -> "Interval":
        intensity = row.get("intensity") or {}
        return cls(
            start=_parse_ts(row["from"]),
            end=_parse_ts(row["to"]),
            actual=intensity.get("actual"),
            forecast=intensity.get("forecast"),
            index=intensity.get("index") or "unknown",
        )


def parse_intensity_payload(payload: dict) -> list[Interval]:
    """Normalise one ``/intensity/{from}/{to}`` response into intervals."""
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("payload has no 'data' list")
    out = []
    for row in rows:
        # the forecast-only family of endpoints nests the same shape one level down
        if "intensity" not in row and "intensity" in (row.get("intensity") or {}):
            row = row["intensity"]
        out.append(Interval.from_api(row))
    return out


def _dedupe(intervals: list[Interval]) -> list[Interval]:
    unique: dict[datetime, Interval] = {}
    for item in intervals:
        unique[item.start] = item
    return [unique[key] for key in sorted(unique)]


# --------------------------------------------------------------------------- #
# chunked fetch + cache
# --------------------------------------------------------------------------- #
def chunk_ranges(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Split ``[start, end)`` into consecutive spans of at most 14 days."""
    spans, cursor = [], start
    while cursor < end:
        nxt = min(cursor + MAX_CHUNK, end)
        spans.append((cursor, nxt))
        cursor = nxt
    return spans


def cache_path(cache_dir: Path, start: datetime, end: datetime) -> Path:
    return cache_dir / f"ci_{_fmt_ts(start).replace(':', '')}_{_fmt_ts(end).replace(':', '')}.json"


def fetch_intensity(start: datetime, end: datetime, *, cache_dir: Path | None = None,
                    sleep: float = 1.0, refresh: bool = False,
                    retries: int = 5) -> list[Interval]:
    """Fetch ``[start, end)`` in <=14-day chunks, caching each chunk's raw JSON.

    ``sleep`` is a courtesy delay between chunk requests: the service is free and
    we never want to look like a scraper.  Chunks already cached are not re-fetched
    unless ``refresh`` is set.
    """
    if end <= start:
        raise ValueError("end must be after start")
    collected: list[Interval] = []
    for index, (span_start, span_end) in enumerate(chunk_ranges(start, end)):
        path = cache_path(cache_dir, span_start, span_end) if cache_dir else None
        if path and path.exists() and not refresh:
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            url = f"{BASE}/intensity/{_fmt_ts(span_start)}/{_fmt_ts(span_end)}"
            payload = http_json(url, retries=retries, sleep=sleep if index else 0.0)
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        collected.extend(parse_intensity_payload(payload))
    return _dedupe(collected)


def fetch_fw24h(from_ts: datetime, *, sleep: float = 0.0) -> list[Interval]:
    """``/intensity/{from}/fw24h`` — the next 24 h of national forecast."""
    payload = http_json(f"{BASE}/intensity/{_fmt_ts(from_ts)}/fw24h", sleep=sleep)
    return _dedupe(parse_intensity_payload(payload))


def fetch_regional(from_ts: datetime | None = None, *, sleep: float = 0.0) -> dict:
    """``/regional`` — current half hour, per distribution region."""
    suffix = f"/{_fmt_ts(from_ts)}" if from_ts else ""
    return http_json(f"{BASE}/regional{suffix}", sleep=sleep)


# --------------------------------------------------------------------------- #
# dense series
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GridSeries:
    """Half-hour CI values over a contiguous UTC span.

    ``actual`` is the measured gCO2/kWh; ``forecast`` is the forecast the API
    archived for that same half hour (genuinely issued before the fact — it is
    not a copy of ``actual``, which is what makes the forecast-driven evaluation
    in :mod:`carbonwindow.report` honest).
    """

    start: datetime
    actual: list[float | None]
    forecast: list[float | None]

    @property
    def slots(self) -> int:
        return len(self.actual)

    def time_of(self, index: int) -> datetime:
        return self.start + index * SLOT

    def index_of(self, when: datetime) -> int:
        return int((when - self.start) // SLOT)

    def coverage(self) -> dict:
        filled = sum(1 for value in self.actual if value is not None)
        return {
            "slots": self.slots,
            "actual_present": filled,
            "actual_missing": self.slots - filled,
            "coverage_pct": round(100.0 * filled / self.slots, 3) if self.slots else 0.0,
            "forecast_present": sum(1 for value in self.forecast if value is not None),
        }


def to_series(intervals: list[Interval]) -> GridSeries:
    """Project normalised intervals onto a dense half-hour grid.

    A missing half hour becomes ``None`` rather than an interpolated number: an
    invented value would quietly inflate every downstream statistic.
    """
    ordered = _dedupe(intervals)
    if not ordered:
        raise ValueError("no intervals")
    start = ordered[0].start
    span = int((ordered[-1].end - start) // SLOT)
    actual: list[float | None] = [None] * span
    forecast: list[float | None] = [None] * span
    for item in ordered:
        offset = int((item.start - start) // SLOT)
        if 0 <= offset < span:
            actual[offset] = None if item.actual is None else float(item.actual)
            forecast[offset] = None if item.forecast is None else float(item.forecast)
    return GridSeries(start=start, actual=actual, forecast=forecast)


def load_series(path: Path) -> GridSeries:
    """Load a previously saved ``GridSeries`` snapshot (JSON)."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return GridSeries(
        start=_parse_ts(payload["start"]),
        actual=[None if v is None else float(v) for v in payload["actual"]],
        forecast=[None if v is None else float(v) for v in payload["forecast"]],
    )


def save_series(series: GridSeries, path: Path, *, meta: dict | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "start": _fmt_ts(series.start),
        "slot_minutes": 30,
        "actual": series.actual,
        "forecast": series.forecast,
        "meta": meta or {},
    }, indent=1), encoding="utf-8")
    return path


def parse_dt(text: str) -> datetime:
    """Accept ``YYYY-MM-DD`` or a full ISO timestamp; return UTC."""
    if len(text) == 10:
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    return _parse_ts(text) if text.endswith("Z") else \
        datetime.fromisoformat(text).astimezone(timezone.utc)
