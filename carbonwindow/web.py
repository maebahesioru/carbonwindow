"""Render the static, single-file report.

No build step, no bundler, no CDN: the page is one HTML file with the whole
summary embedded twice — once as human-readable markup, and once as raw JSON in
a ``<script type="application/json">`` block so anyone can re-derive the numbers
without trusting this page's <svg>.

Charts are emitted as SVG strings here in Python rather than drawn by JavaScript,
so the page renders identically with scripting disabled, inside a screenshot, and
in print.
"""

from __future__ import annotations

import html
import json
import statistics
from pathlib import Path

# --------------------------------------------------------------------------- #
# palette
BG = "#0b1016"
BG_2 = "#0f1620"
PANEL = "#141c26"
PANEL_2 = "#1a2430"
LINE = "#26313d"
FG = "#e8eef5"
MUTED = "#8d9aab"
DIM = "#5c6a7a"
BLUE = "#4ea1ff"
GREEN = "#3ddc84"
AMBER = "#ffbe28"
RED = "#ff5c5c"
VIOLET = "#a78bfa"

FONT = ('ui-sans-serif, system-ui, -apple-system, "Segoe UI", "Noto Sans", '
        '"DejaVu Sans", sans-serif')
MONO = 'ui-monospace, "SF Mono", "Noto Sans Mono", "DejaVu Sans Mono", monospace'

DURATION_ORDER = ("30m", "1h", "2h")
HORIZON_ORDER = ("6h", "12h", "24h")


# --------------------------------------------------------------------------- #
def _esc(text) -> str:
    return html.escape(str(text), quote=True)


def _n(value, digits: int = 1, dash: str = "–") -> str:
    if value is None:
        return dash
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:,.{digits}f}"


def _pct(value, digits: int = 1) -> str:
    return "–" if value is None else f"{value:.{digits}f}%"


def _band_colour(value: float | None) -> str:
    """Green (clean) → amber → red (dirty) over the GB intensity range."""
    if value is None:
        return "#0d141c"
    stops = [(0, (28, 108, 116)), (60, (46, 150, 112)), (110, (152, 186, 74)),
             (160, (238, 190, 62)), (210, (234, 118, 58)), (300, (196, 54, 64))]
    v = max(0.0, min(300.0, float(value)))
    for (x0, c0), (x1, c1) in zip(stops, stops[1:]):
        if v <= x1:
            t = 0.0 if x1 == x0 else (v - x0) / (x1 - x0)
            mix = tuple(round(a + (b - a) * t) for a, b in zip(c0, c1))
            return "#%02x%02x%02x" % mix
    return "#%02x%02x%02x" % stops[-1][1]


# --------------------------------------------------------------------------- #
# charts
def _y_grid(x0, y0, w, h, ticks, label_fmt, *, colour=LINE, size=11) -> list[str]:
    parts = []
    for value in ticks:
        y = y0 + h - (value / ticks[-1]) * h
        parts.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x0 + w}" y2="{y:.1f}" '
                     f'stroke="{colour}" stroke-width="1" opacity="0.55"/>')
        parts.append(f'<text x="{x0 - 10}" y="{y + 4:.1f}" text-anchor="end" '
                     f'font-size="{size}" fill="{DIM}" font-family="{MONO}">'
                     f'{label_fmt(value)}</text>')
    return parts


def chart_ci_daily(daily: list[dict], *, w: int = 1120, h: int = 260) -> str:
    """Daily mean CI across the window with the intra-day min/max band."""
    rows = [r for r in daily if r.get("ci_mean") is not None]
    if len(rows) < 2:
        return '<p class="muted">not enough complete days to chart</p>'
    pad_l, pad_r, pad_t, pad_b = 52, 12, 14, 30
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    top = max(r["ci_max"] for r in rows)
    top = max(200.0, (int(top // 50) + 1) * 50)
    n = len(rows)

    def px(i):
        return pad_l + (i / (n - 1)) * plot_w

    def py(v):
        return pad_t + plot_h - (v / top) * plot_h

    band_top = " ".join(f"{px(i):.1f},{py(r['ci_max']):.1f}" for i, r in enumerate(rows))
    band_bot = " ".join(f"{px(i):.1f},{py(r['ci_min']):.1f}" for i, r in reversed(list(enumerate(rows))))
    line = " ".join(f"{px(i):.1f},{py(r['ci_mean']):.1f}" for i, r in enumerate(rows))
    mean_all = statistics.fmean(r["ci_mean"] for r in rows)

    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" '
             f'aria-label="Daily mean carbon intensity">']
    parts += _y_grid(pad_l, pad_t, plot_w, plot_h, [0, top / 2, top], lambda v: f"{v:.0f}")
    parts.append(f'<polygon points="{band_top} {band_bot}" fill="{BLUE}" opacity="0.14"/>')
    parts.append(f'<polyline points="{line}" fill="none" stroke="{BLUE}" stroke-width="2"/>')
    y_mean = py(mean_all)
    parts.append(f'<line x1="{pad_l}" y1="{y_mean:.1f}" x2="{pad_l + plot_w}" '
                 f'y2="{y_mean:.1f}" stroke="{AMBER}" stroke-width="1" '
                 f'stroke-dasharray="5 4" opacity="0.8"/>')
    parts.append(f'<text x="{pad_l + plot_w - 4}" y="{y_mean - 7:.1f}" text-anchor="end" '
                 f'font-size="11" fill="{AMBER}" font-family="{MONO}">'
                 f'mean {mean_all:.1f}</text>')
    step = max(1, n // 7)
    for i in range(0, n, step):
        parts.append(f'<text x="{px(i):.1f}" y="{h - 8}" text-anchor="middle" font-size="11" '
                     f'fill="{DIM}" font-family="{MONO}">{_esc(rows[i]["date"][5:])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def chart_heatmap(hm: dict, *, w: int = 1120, cell_h: int = 12) -> str:
    """Half-hour × day grid: when the GB grid is clean, over 90 days."""
    days, slots, values = hm["days"], hm["slots"], hm["values"]
    if not days or not slots:
        return '<p class="muted">no heatmap data</p>'
    pad_l, pad_t, pad_r = 46, 8, 8
    cell_w = (w - pad_l - pad_r) / len(days)
    h = pad_t + cell_h * len(slots) + 22
    parts = [f'<svg viewBox="0 0 {w} {h:.0f}" width="100%" role="img" '
             f'aria-label="Carbon intensity heatmap by day and time of day">']
    for row, slot in enumerate(slots):
        if row % 4:
            continue
        y = pad_t + row * cell_h
        parts.append(f'<text x="{pad_l - 8}" y="{y + cell_h - 3}" text-anchor="end" '
                     f'font-size="10" fill="{DIM}" font-family="{MONO}">{slot}</text>')
    for row, slot in enumerate(slots):
        y = pad_t + row * cell_h
        for col, day in enumerate(days):
            value = values[row][col]
            colour = _band_colour(value)
            x = pad_l + col * cell_w
            tip = f"{day} {slot} · {value:.0f} gCO2/kWh" if value is not None else f"{day} {slot} · no data"
            parts.append(f'<rect x="{x:.2f}" y="{y}" width="{max(1.0, cell_w - 0.6):.2f}" '
                         f'height="{cell_h - 0.6}" fill="{colour}"><title>{_esc(tip)}</title></rect>')
    step = max(1, len(days) // 9)
    for col in range(0, len(days), step):
        x = pad_l + col * cell_w + cell_w / 2
        parts.append(f'<text x="{x:.1f}" y="{pad_t + cell_h * len(slots) + 15}" '
                     f'text-anchor="middle" font-size="10" fill="{DIM}" font-family="{MONO}">'
                     f'{_esc(days[col][5:])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def chart_histogram(values: list[float], *, w: int = 1120, h: int = 230,
                    lo: float = -60.0, hi: float = 100.0, step: float = 5.0) -> str:
    """Distribution of per-arrival reductions, negatives included."""
    usable = [v for v in values if v is not None]
    if not usable:
        return '<p class="muted">no samples</p>'
    edges = []
    x = lo
    while x < hi:
        edges.append(x)
        x += step
    counts = [0] * len(edges)
    below = 0
    for value in usable:
        if value < lo:
            below += 1
            continue
        index = min(len(edges) - 1, int((value - lo) // step))
        counts[index] += 1
    top = max(counts) or 1
    pad_l, pad_r, pad_t, pad_b = 52, 12, 16, 34
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    bar_w = plot_w / len(edges)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" '
             f'aria-label="Distribution of reductions">']
    parts += _y_grid(pad_l, pad_t, plot_w, plot_h, [0, top / 2, top],
                     lambda v: f"{v:,.0f}")
    zero_x = pad_l + (0 - lo) / (hi - lo) * plot_w
    for index, edge in enumerate(edges):
        count = counts[index]
        if not count:
            continue
        bh = count / top * plot_h
        x = pad_l + index * bar_w
        colour = RED if edge < 0 else (BLUE if edge < 55 else GREEN)
        opacity = "0.92" if edge < 0 else "0.75"
        parts.append(f'<rect x="{x + 0.5:.2f}" y="{pad_t + plot_h - bh:.2f}" '
                     f'width="{max(1.0, bar_w - 1.2):.2f}" height="{bh:.2f}" fill="{colour}" '
                     f'opacity="{opacity}"><title>{edge:.0f}% to {edge + step:.0f}%: '
                     f'{count:,} arrivals</title></rect>')
    parts.append(f'<line x1="{zero_x:.1f}" y1="{pad_t}" x2="{zero_x:.1f}" '
                 f'y2="{pad_t + plot_h}" stroke="{FG}" stroke-width="1.2" opacity="0.7"/>')
    parts.append(f'<text x="{zero_x:.1f}" y="{pad_t + plot_h + 16}" text-anchor="middle" '
                 f'font-size="10" fill="{MUTED}" font-family="{MONO}">0%</text>')
    for edge in (lo, lo + (hi - lo) / 2, hi):
        x = pad_l + (edge - lo) / (hi - lo) * plot_w
        if abs(edge) < 1e-9:
            continue
        parts.append(f'<text x="{x:.1f}" y="{pad_t + plot_h + 16}" text-anchor="middle" '
                     f'font-size="10" fill="{DIM}" font-family="{MONO}">{edge:.0f}%</text>')
    if below:
        parts.append(f'<text x="{pad_l}" y="{pad_t + 12}" font-size="10" fill="{RED}" '
                     f'font-family="{MONO}">{below:,} arrivals below {lo:.0f}% (clipped left)</text>')
    parts.append("</svg>")
    return "".join(parts)


def chart_example(example: dict, *, w: int = 1120, h: int = 300) -> str:
    """One day's CI curve with the 'run now' window and the chosen window."""
    curve = [c for c in example["curve"] if c.get("actual") is not None]
    if len(curve) < 2:
        return '<p class="muted">no example day</p>'
    decision = example.get("decision") or {}
    pad_l, pad_r, pad_t, pad_b = 52, 14, 16, 30
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    top = max(c["actual"] for c in curve)
    top = max(150.0, (int(top // 50) + 1) * 50)
    n = len(example["curve"])
    dur = example.get("duration_slots", 2)

    def px(i):
        return pad_l + (i / max(1, n - 1)) * plot_w

    def py(v):
        return pad_t + plot_h - (v / top) * plot_h

    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" '
             f'aria-label="Example day: carbon intensity and the chosen run window">']
    parts += _y_grid(pad_l, pad_t, plot_w, plot_h, [0, top / 2, top], lambda v: f"{v:.0f}")

    # window bands first, so the curve sits on top of them
    def band(offset, colour, label, y_label):
        if offset is None:
            return
        x = px(offset)
        bw = max(6.0, (dur / max(1, n - 1)) * plot_w)
        parts.append(f'<rect x="{x:.1f}" y="{pad_t}" width="{bw:.1f}" height="{plot_h}" '
                     f'fill="{colour}" opacity="0.22"/>')
        parts.append(f'<rect x="{x:.1f}" y="{pad_t}" width="{bw:.1f}" height="{plot_h}" '
                     f'fill="none" stroke="{colour}" stroke-width="1.4"/>')
        parts.append(f'<text x="{x + bw / 2:.1f}" y="{pad_t + 14}" text-anchor="middle" '
                     f'font-size="11" fill="{colour}" font-family="{MONO}">{_esc(label)}</text>')
        parts.append(f'<text x="{x + bw / 2:.1f}" y="{y_label:.1f}" text-anchor="middle" '
                     f'font-size="10" fill="{colour}" font-family="{MONO}">'
                     f'{_esc(decision.get("now" if label.startswith("run") else "chosen", ""))}</text>')

    band(decision.get("now_index_offset"), RED, "run now",
         py(decision.get("baseline_mean") or 0) - 8)
    band(decision.get("chosen_index_offset"), GREEN, "chosen",
         py(decision.get("chosen_mean") or 0) - 8)

    actual_line = " ".join(
        f"{px(i):.1f},{py(c['actual']):.1f}"
        for i, c in enumerate(example["curve"]) if c.get("actual") is not None)
    parts.append(f'<polyline points="{actual_line}" fill="none" stroke="{FG}" '
                 f'stroke-width="2"/>')

    fc_points = [(i, c["forecast"]) for i, c in enumerate(example["curve"])
                 if c.get("forecast") is not None]
    if len(fc_points) > 1:
        fc_line = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in fc_points)
        parts.append(f'<polyline points="{fc_line}" fill="none" stroke="{VIOLET}" '
                     f'stroke-width="1.4" stroke-dasharray="4 4" opacity="0.85"/>')

    for hour in range(0, 24, 4):
        index = hour * 2
        if index < n:
            parts.append(f'<text x="{px(index):.1f}" y="{h - 8}" text-anchor="middle" '
                         f'font-size="11" fill="{DIM}" font-family="{MONO}">'
                         f'{hour:02d}:00</text>')
    parts.append("</svg>")
    return "".join(parts)


def chart_conditions(report: dict, *, w: int = 1120, h: int = 260) -> str:
    """Median reduction per condition, oracle vs forecast, side by side."""
    results = report["results"]
    rows = []
    for duration in DURATION_ORDER:
        for horizon in HORIZON_ORDER:
            oracle = results.get("oracle", {}).get(duration, {}).get(horizon, {})
            fc = results.get("forecast", {}).get(duration, {}).get(horizon, {})
            rows.append((duration, horizon, oracle.get("median_pct"), fc.get("median_pct")))
    if not rows:
        return ""
    pad_l, pad_r, pad_t, pad_b = 52, 14, 20, 44
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    top = 50.0
    group = plot_w / len(rows)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" '
             f'aria-label="Median reduction by condition">']
    parts += _y_grid(pad_l, pad_t, plot_w, plot_h, [0, top / 2, top], lambda v: f"{v:.0f}%")
    bar_w = group * 0.30
    for index, (duration, horizon, oracle, fc) in enumerate(rows):
        cx = pad_l + index * group + group / 2
        for offset, value, colour, label in ((-bar_w * 0.62, oracle, BLUE, "oracle"),
                                             (bar_w * 0.62, fc, GREEN, "forecast")):
            if value is None:
                continue
            bh = max(0.0, value) / top * plot_h
            parts.append(f'<rect x="{cx + offset - bar_w / 2:.1f}" '
                         f'y="{pad_t + plot_h - bh:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" '
                         f'fill="{colour}" opacity="0.85"><title>{duration} / {horizon} '
                         f'{label}: median {value:.2f}%</title></rect>')
            parts.append(f'<text x="{cx + offset:.1f}" y="{pad_t + plot_h - bh - 4:.1f}" '
                         f'text-anchor="middle" font-size="9.5" fill="{colour}" '
                         f'font-family="{MONO}">{value:.1f}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{h - 22}" text-anchor="middle" font-size="10.5" '
                     f'fill="{MUTED}" font-family="{MONO}">{duration}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{h - 9}" text-anchor="middle" font-size="9.5" '
                     f'fill="{DIM}" font-family="{MONO}">{horizon}</text>')
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
# fragments
def _stat(value: str, label: str, note: str = "", accent: str = FG) -> str:
    return (f'<div class="stat"><div class="stat-v" style="color:{accent}">{value}</div>'
            f'<div class="stat-l">{_esc(label)}</div>'
            + (f'<div class="stat-n">{_esc(note)}</div>' if note else "")
            + "</div>")


def _condition_table(report: dict) -> str:
    results = report["results"]
    out = ['<table><thead><tr>'
           '<th>Job length</th><th>Deadline</th><th>Information</th>'
           '<th class="num">Starts</th><th class="num">Median</th><th class="num">Mean</th>'
           '<th class="num">Worst</th><th class="num">Best</th>'
           '<th class="num">P10</th><th class="num">P90</th>'
           '<th class="num">Worse<br>than now</th><th class="num">gCO2 saved<br>per job</th>'
           '</tr></thead><tbody>']
    for variant, label, colour in (("oracle", "oracle (perfect foresight)", BLUE),
                                   ("forecast", "forecast (day-ahead archive)", GREEN)):
        for duration in DURATION_ORDER:
            for horizon in HORIZON_ORDER:
                stats = results.get(variant, {}).get(duration, {}).get(horizon, {})
                if not stats.get("n"):
                    continue
                neg = stats.get("negative_share_pct") or 0.0
                neg_style = f'color:{RED};font-weight:600' if neg > 0 else f'color:{DIM}'
                out.append(
                    "<tr>"
                    f'<td>{duration}</td><td>{horizon}</td>'
                    f'<td style="color:{colour}">{_esc(label)}</td>'
                    f'<td class="num dim">{stats["n"]:,}</td>'
                    f'<td class="num strong">{_pct(stats["median_pct"], 2)}</td>'
                    f'<td class="num">{_pct(stats["mean_pct"], 2)}</td>'
                    f'<td class="num" style="color:{RED if (stats["worst_pct"] or 0) < 0 else DIM}">'
                    f'{_pct(stats["worst_pct"], 1)}</td>'
                    f'<td class="num" style="color:{MUTED}">{_pct(stats["best_pct"], 1)}</td>'
                    f'<td class="num dim">{_pct(stats.get("p10_pct"), 1)}</td>'
                    f'<td class="num dim">{_pct(stats.get("p90_pct"), 1)}</td>'
                    f'<td class="num" style="{neg_style}">{neg:.1f}%</td>'
                    f'<td class="num accent">{_n(stats.get("gco2_avoided_median"), 1)}</td>'
                    "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _day_table(daily: list[dict]) -> str:
    out = ['<table class="dense"><thead><tr><th>UTC day</th>'
           '<th class="num">Mean CI</th><th class="num">Min</th><th class="num">Max</th>'
           '<th class="num">Median reduction<br><span class="th-sub">reference condition</span></th>'
           '</tr></thead><tbody>']
    for row in daily:
        value = row.get("reduction_median_pct")
        colour = GREEN if (value or 0) >= 20 else (AMBER if (value or 0) >= 10 else MUTED)
        out.append(f'<tr><td class="mono">{_esc(row["date"])}</td>'
                   f'<td class="num">{_n(row["ci_mean"], 0)}</td>'
                   f'<td class="num dim">{_n(row["ci_min"], 0)}</td>'
                   f'<td class="num dim">{_n(row["ci_max"], 0)}</td>'
                   f'<td class="num" style="color:{colour}">{_pct(value, 1)}</td></tr>')
    out.append("</tbody></table>")
    return "".join(out)


def _legend() -> str:
    stops = [0, 60, 110, 160, 210, 300]
    cells = "".join(
        f'<span class="sw" style="background:{_band_colour(v)}"></span>'
        for v in range(0, 300, 10))
    ticks = "".join(f'<span>{v}</span>' for v in stops)
    return (f'<div class="legend"><span class="legend-l">clean</span>{cells}'
            f'<span class="legend-l">dirty</span></div>'
            f'<div class="legend-scale">{ticks}</div>')


# --------------------------------------------------------------------------- #
def render(summary: dict, out_path: Path | str) -> Path:
    """Write ``out_path`` and return it."""
    out_path = Path(out_path)
    window = summary["window"]
    coverage = summary["coverage"]
    ci = summary["ci_stats"]
    config = summary["config"]
    results = summary["results"]
    reference = config["reference"]
    ref_oracle = results["oracle"][reference["duration"]][reference["horizon"]]
    ref_forecast = results["forecast"][reference["duration"]][reference["horizon"]]
    power = config["power_kw"]
    forecast_error = ci.get("forecast_error", {})
    daily = summary["daily"]
    heat = summary["heatmap"]
    example = summary["example"] or {}
    decision = example.get("decision") or {}
    ref_values = (summary.get("reference_reductions") or {}).get("forecast") or []
    quality = summary.get("data_quality") or {}
    zero_day = summary.get("zero_day_effect") or {}
    sens = summary.get("sensitivity") or {}
    sens_oracle = sens.get("oracle") or {}
    sens_forecast = sens.get("forecast") or {}

    best_median = max(
        (results[v][d][h]["median_pct"] for v in results
         for d in results[v] for h in results[v][d]
         if results[v][d][h].get("median_pct") is not None), default=None)
    worst_seen = min(
        (results[v][d][h]["worst_pct"] for v in results
         for d in results[v] for h in results[v][d]
         if results[v][d][h].get("worst_pct") is not None), default=None)
    total_avoided_median = ref_forecast.get("gco2_avoided_median")

    payload = json.dumps(summary, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")

    stats_html = "".join([
        _stat(_pct(ref_forecast.get("median_pct"), 1),
              "median reduction",
              f"{reference['duration']} job, {reference['horizon']} deadline, forecast-driven",
              GREEN),
        _stat(_pct(ref_oracle.get("median_pct"), 1),
              "perfect-foresight median",
              f"same condition, actual values — the ceiling", BLUE),
        _stat(f"{ci['mean']:.1f}", "mean grid intensity",
              "gCO2/kWh across the measured window", FG),
        _stat(f"{coverage['coverage_pct']:.1f}%", "window coverage",
              f"{coverage['actual_present']:,} of {coverage['slots']:,} half hours", VIOLET),
    ])

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CarbonWindow — measured results</title>
<meta name="description" content="Measured carbon savings from shifting compute jobs into cleaner half hours on the GB electricity grid.">
<style>
  :root {{
    --bg: {BG}; --bg2: {BG_2}; --panel: {PANEL}; --panel2: {PANEL_2};
    --line: {LINE}; --fg: {FG}; --muted: {MUTED}; --dim: {DIM};
    --blue: {BLUE}; --green: {GREEN}; --amber: {AMBER}; --red: {RED}; --violet: {VIOLET};
  }}
  * {{ box-sizing: border-box; }}
  html {{ background: var(--bg); }}
  body {{
    margin: 0; font-family: {FONT}; color: var(--fg);
    background: radial-gradient(1100px 500px at 12% -12%, #12202e 0%, var(--bg) 62%) no-repeat,
                var(--bg);
    -webkit-font-smoothing: antialiased; line-height: 1.55;
  }}
  .wrap {{ max-width: 1180px; margin: 0 auto; padding: 46px 30px 80px; }}
  header.top {{ padding-bottom: 22px; border-bottom: 1px solid var(--line); }}
  .eyebrow {{
    font: 600 12px/1 {MONO}; letter-spacing: .16em; text-transform: uppercase;
    color: var(--green); margin-bottom: 14px;
  }}
  h1 {{ font-size: 40px; line-height: 1.1; margin: 0 0 12px; letter-spacing: -.02em; }}
  h1 .thin {{ color: var(--muted); font-weight: 400; }}
  .lede {{ font-size: 17px; color: var(--muted); max-width: 78ch; margin: 0; }}
  .lede b {{ color: var(--fg); font-weight: 600; }}
  .flow {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 26px 0 6px;
  }}
  .step {{
    background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
    padding: 13px 15px; position: relative;
  }}
  .step .k {{
    font: 600 10.5px/1 {MONO}; letter-spacing: .1em; text-transform: uppercase;
    color: var(--green); margin-bottom: 7px;
  }}
  .step .t {{ font-size: 13.5px; color: var(--fg); }}
  .step .s {{ font: 400 11.5px/1.4 {MONO}; color: var(--dim); margin-top: 5px; }}
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 30px 0 6px; }}
  .stat {{
    background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
    padding: 17px 18px 15px;
  }}
  .stat-v {{ font: 700 30px/1.05 {MONO}; letter-spacing: -.02em; }}
  .stat-l {{ font-size: 12.5px; color: var(--fg); margin-top: 7px; }}
  .stat-n {{ font: 400 11px/1.35 {MONO}; color: var(--dim); margin-top: 4px; }}
  h2 {{
    font-size: 21px; margin: 46px 0 6px; letter-spacing: -.01em;
    display: flex; align-items: baseline; gap: 12px;
  }}
  h2 .n {{ font: 600 11px/1 {MONO}; color: var(--green); letter-spacing: .1em; }}
  h2 + .sub {{ color: var(--muted); font-size: 13.5px; margin: 0 0 16px; max-width: 92ch; }}
  .card {{
    background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
    padding: 16px 18px 12px;
  }}
  .card + .card {{ margin-top: 14px; }}
  .card-title {{
    font: 600 12px/1 {MONO}; letter-spacing: .08em; text-transform: uppercase;
    color: var(--muted); margin-bottom: 12px;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
  thead th {{
    text-align: left; font: 600 10.5px/1.25 {MONO}; letter-spacing: .05em;
    text-transform: uppercase; color: var(--dim); padding: 0 8px 9px;
    border-bottom: 1px solid var(--line); vertical-align: bottom;
  }}
  tbody td {{ padding: 6px 8px; border-bottom: 1px solid rgba(38,49,61,.5); }}
  tbody tr:last-child td {{ border-bottom: none; }}
  .num {{ text-align: right; font-family: {MONO}; font-variant-numeric: tabular-nums; }}
  .strong {{ font-weight: 600; }}
  .dim {{ color: var(--dim); }}
  .mono {{ font-family: {MONO}; }}
  .accent {{ color: var(--amber); }}
  .th-sub {{ font-size: 9px; letter-spacing: 0; text-transform: none; color: var(--dim); }}
  table.dense tbody td {{ padding: 3px 8px; font-size: 12px; }}
  .legend {{ display: flex; align-items: center; gap: 10px; margin: 4px 0 2px; }}
  .sw {{ width: 100%; height: 11px; border-radius: 2px; display: block; }}
  .legend .sw {{ flex: 1; width: auto; }}
  .legend-l {{ font: 600 10px/1 {MONO}; color: var(--dim); text-transform: uppercase; letter-spacing: .08em; }}
  .legend-scale {{
    display: flex; justify-content: space-between; font: 400 10px/1 {MONO};
    color: var(--dim); margin: 4px 46px 0 40px;
  }}
  .two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
  .note {{
    border-left: 3px solid var(--amber); background: rgba(255,190,40,.06);
    padding: 12px 16px; border-radius: 0 8px 8px 0; font-size: 13px; color: var(--muted);
    margin: 16px 0 0;
  }}
  .note b {{ color: var(--fg); }}
  .note.red {{ border-left-color: var(--red); background: rgba(255,92,92,.07); }}
  ul.tight {{ margin: 8px 0 0; padding-left: 20px; color: var(--muted); font-size: 13px; }}
  ul.tight li {{ margin: 4px 0; }}
  ul.tight b {{ color: var(--fg); }}
  footer {{
    margin-top: 52px; padding-top: 20px; border-top: 1px solid var(--line);
    color: var(--dim); font-size: 12px; font-family: {MONO};
    display: flex; justify-content: space-between; gap: 20px; flex-wrap: wrap;
  }}
  a {{ color: var(--blue); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .kv {{ display: grid; grid-template-columns: 1fr; gap: 7px; font-size: 12.5px; }}
  .kv div {{ display: flex; justify-content: space-between; align-items: baseline; gap: 16px;
             border-bottom: 1px dashed rgba(38,49,61,.7); padding-bottom: 5px; }}
  .kv span:first-child {{ color: var(--dim); white-space: nowrap; }}
  .kv span:last-child {{ font-family: {MONO}; text-align: right; }}
  @media (max-width: 900px) {{
    .stats, .flow, .two {{ grid-template-columns: 1fr 1fr; }}
    h1 {{ font-size: 30px; }}
  }}
</style>
</head>
<body>
<div class="wrap">

<header class="top">
  <div class="eyebrow">CarbonWindow · measured on {_esc(window["start_utc"])} → {_esc(window["end_utc"])}</div>
  <h1>Move the batch job to the clean half hour.<br><span class="thin">Measured, not estimated.</span></h1>
  <p class="lede">CarbonWindow is a scheduler that shifts flexible compute into the half hours when the
  GB electricity grid is least carbon intensive. Every number on this page came from
  <b>{coverage["actual_present"]:,} half-hourly readings</b> of National Grid ESO's Carbon Intensity API,
  replayed at every possible start time over <b>{_n(window["span_days"], 2)} days</b>.</p>

  <div class="flow">
    <div class="step"><div class="k">01 fetch</div><div class="t">Cache the history</div>
      <div class="s">14-day chunks, JSON on disk</div></div>
    <div class="step"><div class="k">02 optimize</div><div class="t">Exact best window</div>
      <div class="s">sliding-window argmin, O(n)</div></div>
    <div class="step"><div class="k">03 replay</div><div class="t">Every start time</div>
      <div class="s">9 conditions × 2 information sets</div></div>
    <div class="step"><div class="k">04 report</div><div class="t">One static page</div>
      <div class="s">this file, no build step</div></div>
  </div>
</header>

<div class="stats">{stats_html}</div>

<h2><span class="n">01</span> What the scheduler saves</h2>
<p class="sub">Each row replays the whole window: at every legal start time, compare running the job
right now against running it at the cleanest start inside the deadline. Energy is stated as
{_n(power, 1)} kW for the full job length, so a {reference["duration"]} job at {_n(power, 1)} kW is
{_n(ref_forecast.get("energy_kwh", 0.5), 2)} kWh and the gCO2 column is that energy times the
intensity difference.</p>

<div class="card">
  <div class="card-title">Median reduction by condition — and the two information sets</div>
  {_condition_table(summary)}
</div>

<div class="card">
  <div class="card-title">Median reduction, side by side</div>
  {chart_conditions(summary)}
</div>

<div class="note red">
  <b>The honest part.</b> Rows labelled <i>forecast</i> decide using the day-ahead forecast the API
  archived for that half hour — what a real deployment would have known. The forecast is good but not
  perfect (mean absolute error <b>{_n(forecast_error.get("mae"), 1)} gCO2/kWh</b>,
  95th percentile <b>{_n(forecast_error.get("p95_abs"), 0)}</b>, worst <b>{_n(forecast_error.get("max_abs"), 0)}</b>),
  so a small share of arrivals end up <b>worse</b> than running immediately — up to
  <b>{_pct(worst_seen, 0)}</b> worse in the tail. Scheduling on a forecast lowers the median; it does not
  guarantee a saving on any single job.
</div>

<div class="note">
  <b>Data quality, stated rather than cleaned.</b> The snapshot contains
  <b>{_n(quality.get("zero_count"), 0)}</b> half-hour reading of exactly
  <b>0 gCO2/kWh</b> ({_esc(", ".join(quality.get("zero_readings") or []) or "none")}), while the lowest
  other reading in the whole window is <b>{_n(quality.get("min_nonzero"), 0)}</b> — so the 0 is almost
  certainly a missing value published as zero. It is left in every headline number above. Dropping it
  (turning it back into a gap, no interpolation) moves the reference-condition median from
  <b>{_pct(sens_oracle.get("median_raw"), 2)}</b> to <b>{_pct(sens_oracle.get("median_without_zeros"), 2)}</b>
  under perfect foresight and leaves the forecast-driven median at
  <b>{_pct(sens_forecast.get("median_without_zeros"), 2)}</b>. The window medians barely move — it is one
  half hour out of thousands — but a single day only has 48 of them, so the same reading decides which
  day looks best: <b>{_esc(zero_day.get("day", "–"))}</b> scores
  <b>{_pct(zero_day.get("median_raw_pct"), 1)}</b> in the day ranking below and
  <b>{_pct(zero_day.get("median_without_zero_pct"), 1)}</b> once the 0 is treated as a gap, at which point
  the best day becomes <b>{_esc(zero_day.get("best_day_without_zero", "–"))}</b>
  (<b>{_pct(zero_day.get("best_day_without_zero_pct"), 1)}</b>). One bad row is worth 30 points on a day
  and a different winner — so the day ranking is labelled as perfect foresight, not presented as a plan.
</div>

<h2><span class="n">02</span> When the grid is clean</h2>
<p class="sub">Mean carbon intensity per UTC day ({len(daily)} complete days), with the spread between the
cleanest and dirtiest half hour of each day behind it.</p>
<div class="card">
  <div class="card-title">Daily mean intensity — gCO2/kWh</div>
  {chart_ci_daily(daily)}
</div>

<div class="card">
  <div class="card-title">Every half hour of {len(heat["days"])} days</div>
  {_legend()}
  {chart_heatmap(heat)}
</div>

<h2><span class="n">03</span> One day, one decision</h2>
<p class="sub">{_esc(example.get("date", ""))} — a day with the median reduction, not a flattering one.
At <b>{_esc(decision.get("now", "–"))}</b> UTC the job would average
<b>{_n(decision.get("baseline_mean"), 1)} gCO2/kWh</b>. The scheduler moves it to
<b>{_esc(decision.get("chosen", "–"))}</b> UTC for <b>{_n(decision.get("chosen_mean"), 1)}</b> —
a <b>{_pct(decision.get("reduction_pct"), 1)}</b> reduction. The last legal start was
{_esc(decision.get("last_legal_start", "–"))}.</p>
<div class="card">
  <div class="card-title">Actual intensity (white), archived forecast (violet), both windows</div>
  {chart_example(example)}
</div>

<h2><span class="n">04</span> How often it backfires</h2>
<p class="sub">Distribution of per-arrival reductions at the reference condition
({reference["duration"]} job, {reference["horizon"]} deadline), forecast-driven and scored against
actuals. Every bar left of the white line is an arrival where waiting cost carbon.</p>
<div class="card">
  <div class="card-title">{len(ref_values):,} arrivals</div>
  {chart_histogram(ref_values)}
</div>

<h2><span class="n">05</span> Method, and what this is not</h2>
<div class="two">
  <div class="card">
    <div class="card-title">Measured configuration</div>
    <div class="kv">
      <div><span>source</span><span>ESO Carbon Intensity</span></div>
      <div><span>country</span><span>GB only</span></div>
      <div><span>resolution</span><span>{_n(config["slot_minutes"], 0)} min</span></div>
      <div><span>window start</span><span>{_esc(window["start_utc"])}</span></div>
      <div><span>window end</span><span>{_esc(window["end_utc"])}</span></div>
      <div><span>span</span><span>{_n(window["span_days"], 2)} d</span></div>
      <div><span>CI mean</span><span>{_n(ci["mean"], 2)}</span></div>
      <div><span>CI median</span><span>{_n(ci["median"], 2)}</span></div>
      <div><span>CI min / max</span><span>{_n(ci["min"], 0)} / {_n(ci["max"], 0)}</span></div>
      <div><span>assumed power</span><span>{_n(power, 1)} kW</span></div>
      <div><span>forecast MAE</span><span>{_n(forecast_error.get("mae"), 2)}</span></div>
      <div><span>generated</span><span>{_esc(summary["generated_at"])}</span></div>
    </div>
  </div>
  <div class="card">
    <div class="card-title">Limits — read these before quoting a number</div>
    <ul class="tight">
      <li><b>Indicator is average intensity, not marginal.</b> Shifting load does not necessarily avoid
      the average mix of that half hour; a marginal-emissions model would give different numbers.</li>
      <li><b>Great Britain only.</b> The API covers the GB grid. Nothing here generalises to another
      country without replaying its own data.</li>
      <li><b>Half-hour granularity.</b> Sub-30-minute flexibility is invisible to this model.</li>
      <li><b>Perfect stopping.</b> A plan is assumed to complete inside its window with no preemption,
      retries, or cold-start cost.</li>
      <li><b>Energy is assumed, not metered.</b> The gCO2 columns scale linearly with the stated power;
      they are not a measurement of any real workload.</li>
      <li><b>Historical replay.</b> The forecast rows use the archived forecast, so they model what a
      deployment would have known — they are not a live trial.</li>
    </ul>
  </div>
</div>

<footer>
  <span>CarbonWindow · data: National Grid ESO Carbon Intensity API (api.carbonintensity.org.uk)</span>
  <span>{_esc(summary["generated_at"])} · generated from results/summary.json</span>
</footer>

</div>
<script id="carbonwindow-data" type="application/json">{payload}</script>
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return out_path
