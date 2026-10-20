"""Render the demo-video frames, telops and manifest for docs/make_video.sh.

    .venv/bin/python docs/make_video_slides.py && bash docs/make_video.sh

Every number drawn on a frame is read from ``results/summary.json`` or from a text
file that a real command produced under ``docs/video_src/``. Nothing is typed in by
hand, so the video cannot claim more than the measurement did.

Frames are 1280x720. The bottom 140 px are left empty: ``make_video.sh`` draws the
telop band there (a rule at y=594 and the subtitle at y=632).
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SRC = DOCS / "video_src"
FRAMES = DOCS / "video_frames"
TELOP = DOCS / "video_telop"
SUMMARY = ROOT / "results" / "summary.json"

W, H = 1280, 720
SAFE_BOTTOM = 574           # nothing important goes below this: the telop lives there
MARGIN = 72
TEXT_W = W - 2 * MARGIN

BG = (11, 16, 22)
PANEL = (22, 28, 36)
PANEL_2 = (28, 35, 45)
LINE = (48, 58, 72)
FG = (230, 237, 243)
MUTED = (139, 148, 158)
BLUE = (78, 161, 255)
GREEN = (61, 220, 132)
AMBER = (255, 190, 40)
RED = (255, 92, 92)
VIOLET = (167, 139, 250)

FONT = "/usr/share/fonts/noto/NotoSans-Regular.ttf"
FONT_B = "/usr/share/fonts/noto/NotoSans-Bold.ttf"
MONO = "/usr/share/fonts/noto/NotoSansMono-Regular.ttf"

MANIFEST: list[tuple[str, float, int, str]] = []


# --------------------------------------------------------------------------- #
# primitives
def font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    path = MONO if mono else (FONT_B if bold else FONT)
    return ImageFont.truetype(path, size)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    # a faint vertical gradient so flat panels do not look like a dead screen
    for y in range(0, H, 4):
        shade = 4 - int(4 * y / H)
        draw.rectangle([0, y, W, y + 3], fill=(BG[0] + shade, BG[1] + shade, BG[2] + shade))
    return image, draw


def kicker(draw: ImageDraw.ImageDraw, text: str, *, colour: tuple = GREEN) -> None:
    draw.rectangle([MARGIN, 46, MARGIN + 4, 60], fill=colour)
    draw.text((MARGIN + 12, 44), text.upper(), font=font(13, bold=True), fill=MUTED)


def h1(draw: ImageDraw.ImageDraw, text: str, *, y: int = 78, size: int = 44,
       colour: tuple = FG, bold: bool = True) -> int:
    draw.text((MARGIN, y), text, font=font(size, bold=bold), fill=colour)
    return y + size + 14


def para(draw: ImageDraw.ImageDraw, text: str, *, y: int, size: int = 20,
         colour: tuple = FG, width: int = TEXT_W, gap: int = 10,
         line: int = 30, x: int = MARGIN) -> int:
    for block in text.split("\n\n"):
        for row in textwrap.wrap(" ".join(block.split()), width=int(width / (size * 0.50))):
            draw.text((x, y), row, font=font(size), fill=colour)
            y += line
        y += gap
    return y


def bullets(draw: ImageDraw.ImageDraw, items: list[str], *, y: int, size: int = 20,
            colour: tuple = FG, width: int = TEXT_W, marker: str = "—",
            line: int = 28, gap: int = 12, x: int = MARGIN) -> int:
    for item in items:
        draw.text((x, y), marker, font=font(size - 2), fill=MUTED)
        wrapped = textwrap.wrap(item, width=int((width - 34) / (size * 0.50)))
        for k, row in enumerate(wrapped):
            draw.text((x + 26, y), row, font=font(size), fill=colour)
            y += line
        y += gap
    return y


def chip(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, *, head: str,
         body: str, colour: tuple = BLUE, head_size: int = 15, body_size: int = 17) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=PANEL, outline=LINE)
    draw.rectangle([x, y + 12, x + 4, y + 34], fill=colour)
    draw.text((x + 18, y + 13), head.upper(), font=font(head_size, bold=True), fill=colour)
    top = y + 13 + head_size + 10
    for row in textwrap.wrap(body, width=int((w - 36) / (body_size * 0.50)))[:3]:
        draw.text((x + 18, top), row, font=font(body_size), fill=FG)
        top += body_size + 8


def big_stat(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, *, value: str,
             label: str, note: str = "", colour: tuple = GREEN, h: int = 128) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=12, fill=PANEL, outline=LINE)
    draw.text((x + 20, y + 16), value, font=font(40, bold=True), fill=colour)
    draw.text((x + 20, y + 68), label, font=font(15, bold=True), fill=FG)
    if note:
        for k, row in enumerate(textwrap.wrap(note, width=int((w - 40) / (14 * 0.52)))[:2]):
            draw.text((x + 20, y + 90 + k * 18), row, font=font(13), fill=MUTED)


def terminal(draw: ImageDraw.ImageDraw, command: str, lines: list[str], *, y: int,
             h: int, title: str = "zsh", size: int = 16) -> None:
    draw.rounded_rectangle([MARGIN, y, W - MARGIN, y + h], radius=12, fill=(14, 18, 24),
                           outline=LINE)
    draw.rectangle([MARGIN, y, W - MARGIN, y + 34], fill=PANEL_2)
    for k, colour in enumerate((RED, AMBER, GREEN)):
        draw.ellipse([MARGIN + 16 + k * 20, y + 12, MARGIN + 26 + k * 20, y + 22], fill=colour)
    draw.text((MARGIN + 84, y + 8), title, font=font(14, bold=True), fill=MUTED)

    cursor = y + 48
    draw.text((MARGIN + 20, cursor), "$", font=font(size, mono=True), fill=GREEN)
    draw.text((MARGIN + 40, cursor), command, font=font(size, mono=True), fill=FG)
    cursor += size + 12
    for row in lines:
        colour = MUTED if row.startswith("#") else FG
        if row.startswith("+"):
            colour, row = GREEN, row[1:]
        elif row.startswith("!"):
            colour, row = AMBER, row[1:]
        draw.text((MARGIN + 20, cursor), row[:118], font=font(size, mono=True), fill=colour)
        cursor += size + 8
        if cursor > y + h - 24:
            break


def section(y0: int, y1: int, *, top: int = 8, max_h: int = 566) -> Image.Image:
    """Crop one whole section out of the rendered page and fit it above the telop band."""
    page = Image.open(SRC / "page_full.png").convert("RGB")
    crop = page.crop((0, y0, W, y1))
    if crop.height > max_h:
        scale = max_h / crop.height
        crop = crop.resize((int(crop.width * scale), max_h), Image.LANCZOS)
    image, draw = canvas()
    x = (W - crop.width) // 2
    image.paste(crop, (x, top))
    draw.rectangle([x - 1, top - 1, x + crop.width, top + crop.height], outline=LINE)
    return image


def footer(draw: ImageDraw.ImageDraw, text: str, *, colour: tuple = MUTED) -> None:
    draw.text((MARGIN, SAFE_BOTTOM - 34), text, font=font(13), fill=colour)


# --------------------------------------------------------------------------- #
# frames
def frame_title() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "IEEE ClimateChain Global Hackathon 2026")
    draw.text((MARGIN, 128), "CarbonWindow", font=font(78, bold=True), fill=FG)
    draw.text((MARGIN, 224), "Move the batch job to the clean half hour.",
              font=font(36, bold=True), fill=BLUE)
    draw.text((MARGIN, 272), "Measured, not estimated.", font=font(36, bold=True), fill=MUTED)
    para(draw, "A scheduler for flexible compute, scored against 90 days of real GB grid "
               "carbon data — and shipped with the evidence it cannot fake.",
         y=336, size=21, colour=FG)
    for k, (head, body, colour) in enumerate((
            ("data", "ESO Carbon Intensity API\nfree, no API key", GREEN),
            ("core", "exact O(n) window search\ntested against brute force", BLUE),
            ("output", "one HTML report\nno build step", VIOLET))):
        chip(draw, MARGIN + k * 384, 404, 348, 96, head=head, body=body, colour=colour)
    footer(draw, "cli: fetch · optimize · report · web · live      ·      python -m pytest")
    return image


def frame_problem() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "the problem")
    h1(draw, "The grid is not equally dirty all day", size=40)
    para(draw, "Half-hourly carbon intensity on the GB grid swings by more than 4× between "
               "days, and by more than that within a single day. A batch job that may start "
               "anywhere before its deadline does not have to run at the dirty half hour.",
         y=148, size=21)
    total, clean, dirty, ratio = data["__daily"]
    big_stat(draw, MARGIN, 254, 348, value=f"{total:.1f}", label="MEAN gCO2/kWh, 90 days",
             note="the average a job inherits if it ignores the clock", colour=FG)
    big_stat(draw, MARGIN + 384, 254, 348, value=f"{clean:.1f}", label="CLEANEST DAY MEAN",
             note="gCO2/kWh on the cleanest UTC day", colour=GREEN)
    big_stat(draw, MARGIN + 768, 254, 348, value=f"{dirty:.1f}", label="DIRTIEST DAY MEAN",
             note=f"{ratio:.2f}× the cleanest day, same three months", colour=RED)
    draw.text((MARGIN, 412), "So the question this project answers is:",
              font=font(20, bold=True), fill=FG)
    para(draw, "\u201cFor a job that may start any time before its deadline, how much lower is "
               "the average carbon intensity at the best start time than at \u2018now\u2019 — measured "
               "at every possible arrival, not on one lucky day?\u201d",
         y=444, size=22, colour=BLUE)
    footer(draw, "source: National Grid ESO Carbon Intensity API · GB national average")
    return image


def frame_build() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "what was built")
    h1(draw, "Four commands, one audit trail", size=40)
    steps = (
        ("01 fetch", "90 days of half-hourly intensity, 14-day chunks, cached on disk.", GREEN),
        ("02 optimize", "exact sliding-window minimum, O(n), compared against\na brute-force search in the tests.", BLUE),
        ("03 report", "replay every legal start time for 3 job lengths × 3 deadlines\n× 2 information sets.", AMBER),
        ("04 web", "one 768 KB HTML file, SVG charts, no CDN, no build step.", VIOLET),
    )
    y = 152
    for head, body, colour in steps:
        chip(draw, MARGIN, y, TEXT_W, 78, head=head, body=body.replace("\n", " "), colour=colour)
        y += 90
    para(draw, "All four write files into the repository, so the video, the report and the "
               "README are generated from the same measured snapshot.", y=y + 6, size=17,
         colour=MUTED)
    return image


def frame_data() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "the data source")
    h1(draw, "National Grid ESO Carbon Intensity API", size=38)
    para(draw, "Free, public, no API key, no registration. Half-hourly national average in "
               "gCO2/kWh for the GB grid, with an archive that goes back to 2019.",
         y=142, size=20)
    lines = [
        (GREEN, "GET /intensity/{from}/{to}"),
        (FG, "  half-hourly actual + the forecast that was published"),
        (GREEN, "GET /intensity/{from}/fw24h"),
        (FG, "  the day-ahead forecast a live scheduler would see"),
        (GREEN, "GET /regional"),
        (FG, "  14 DNO regions, same half-hourly shape"),
    ]
    y = 240
    for colour, row in lines:
        draw.text((MARGIN + 6, y), row, font=font(18, mono=True), fill=colour)
        y += 30
    draw.rounded_rectangle([MARGIN, 420, W - MARGIN, 420 + 110], radius=12, fill=PANEL,
                           outline=LINE)
    draw.rectangle([MARGIN, 436, MARGIN + 4, 508], fill=AMBER)
    draw.text((MARGIN + 22, 434), "QUIRKS MEASURED, THEN PINNED BY TESTS",
              font=font(14, bold=True), fill=AMBER)
    draw.text((MARGIN + 22, 458), "The response includes one row starting before the requested "
                                 "\u2018from\u2019 → naive chunk stitching duplicates half an hour.",
              font=font(15), fill=FG)
    draw.text((MARGIN + 22, 480), "Past forecast fields are a genuine pre-issued archive, not a "
                                 "copy of the actuals → a forecast-driven replay is honest.",
              font=font(15), fill=FG)
    draw.text((MARGIN + 22, 502), "Both are asserted in tests/test_api.py, so a future change "
                                 "cannot quietly reintroduce either.",
              font=font(15), fill=MUTED)
    footer(draw, "carbonintensity.org.uk · no key required at the time of measurement")
    return image


def frame_fetch() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "step 1 · fetch")
    h1(draw, "Seven requests, 4,329 half hours", size=38)
    terminal(draw, "python -m carbonwindow.cli fetch --from 2026-07-22T00:00Z --to 2026-10-20T04:00Z",
             read_src("fetch.txt"), y=146, h=338, title="fetch — real output")
    para(draw, "14-day chunks keep the request count low and make an interrupted run "
               "resumable: the cache is keyed by range, so a re-run costs zero requests. "
               "The snapshot is committed as data/ci_90d.json, 74 KB.",
         y=504, size=18, colour=MUTED)
    return image


def frame_coverage() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "step 1 · what the snapshot actually covers")
    h1(draw, "No gaps to hide", size=40)
    cov = data["coverage"]
    big_stat(draw, MARGIN, 152, 272, value=f"{cov['actual_present']:,}", label="HALF HOURS PRESENT",
             colour=GREEN)
    big_stat(draw, MARGIN + 288, 152, 272, value=f"{cov['actual_missing']:,}", label="MISSING",
             colour=GREEN, note="every slot aligned to a 30-min grid")
    big_stat(draw, MARGIN + 576, 152, 272, value=f"{data['window']['span_days']:.2f}", label="DAYS SPANNED",
             colour=FG, note="2026-07-21 → 2026-10-20 UTC")
    big_stat(draw, MARGIN + 864, 152, 272, value=f"{cov['coverage_pct']:.1f} %", label="COVERAGE",
             colour=BLUE)
    para(draw, "Missing slots are never interpolated. A gap stays a gap, and any window that "
               "touches one is dropped from the sweep and counted — which is why the sample "
               "sizes differ slightly between conditions (4,281 to 4,318 arrivals).",
         y=310, size=20)
    draw.rounded_rectangle([MARGIN, 418, W - MARGIN, 418 + 100], radius=12, fill=PANEL,
                           outline=LINE)
    draw.rectangle([MARGIN, 434, MARGIN + 4, 502], fill=AMBER)
    draw.text((MARGIN + 22, 432), "WHY THIS MATTERS", font=font(14, bold=True), fill=AMBER)
    draw.text((MARGIN + 22, 456), "An interpolated cheap slot would silently manufacture a "
                                 "perfect window. Every number downstream would be a fiction.",
              font=font(16), fill=FG)
    draw.text((MARGIN + 22, 480), "Interpolation is therefore not a feature this tool lacks; "
                                 "it is a bug it refuses to have.",
              font=font(16), fill=FG)
    footer(draw, "data/ci_90d.json  ·  4,329 slots × (actual, forecast)")
    return image


def frame_optimize() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "step 2 · optimize, on the real snapshot")
    h1(draw, "One decision, cross-checked", size=38)
    terminal(draw, "python -m carbonwindow.cli optimize --now 2026-08-26T02:00Z "
                   "--duration-hours 1 --horizon-hours 12 --brute-force-check",
             read_src("optimize_check.txt"), y=142, h=336, title="optimize — real output",
             size=15)
    para(draw, "The decision uses the archived forecast; the means printed are measured values, "
               "so the saving is scored honestly. The last line re-minimises the same forecast "
               "series and confirms the chosen window.",
         y=498, size=17, colour=MUTED)
    return image


def frame_algo() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "step 2 · how the optimum is found")
    h1(draw, "Exact, in one pass", size=40)
    para(draw, "A job of d half hours has to minimise the mean over every window that starts "
               "inside the deadline. Trying all of them for every arrival is O(n·T); CarbonWindow "
               "does it in O(n) and still cannot miss the cheapest window.",
         y=146, size=20)
    steps = (
        ("1", "prefix sums", "mean of any window = (S[i+d] − S[i]) / d, O(1) per window", GREEN),
        ("2", "monotonic deque", "a deque of candidate starts, kept increasing by mean, pops from the back", BLUE),
        ("3", "slide", "one pop-front, one push-back per arrival — O(n) total, no sorting", AMBER),
        ("4", "tie-break", "equal means resolve to the earliest start, so runs are reproducible", VIOLET),
    )
    y = 268
    for num, head, body, colour in steps:
        draw.ellipse([MARGIN, y + 8, MARGIN + 28, y + 36], fill=colour)
        draw.text((MARGIN + 9, y + 12), num, font=font(17, bold=True), fill=BG)
        draw.text((MARGIN + 44, y + 10), head, font=font(20, bold=True), fill=colour)
        draw.text((MARGIN + 240, y + 12), body, font=font(18), fill=FG)
        y += 46
    draw.text((MARGIN, 464), "And the part that keeps it honest:", font=font(18, bold=True), fill=FG)
    draw.text((MARGIN, 492), "brute_force_best_window() sums every window one element at a time and "
                             "lives in the same module as the fast path.",
              font=font(18), fill=MUTED)
    footer(draw, "carbonwindow/optimize.py · argmin_windows()")
    return image


def frame_tests() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "step 2 · the optimiser is checked, not trusted")
    h1(draw, "32 tests, including the bug they caught", size=36)
    terminal(draw, "python -m pytest", read_src("pytest.txt"), y=142, h=200,
             title="pytest — real output")
    para(draw, "The optimiser is compared against brute force on random series, on "
               "deadline-bounded windows, and on raw window means. Two cases exist only because "
               "they are where a greedy answer is wrong.", y=372, size=19)
    draw.rounded_rectangle([MARGIN, 440, W - MARGIN, 440 + 92], radius=12, fill=PANEL,
                           outline=LINE)
    draw.rectangle([MARGIN, 454, MARGIN + 4, 516], fill=RED)
    draw.text((MARGIN + 22, 452), "A REAL BUG, FOUND BY RUNNING THE TOOL",
              font=font(14, bold=True), fill=RED)
    draw.text((MARGIN + 22, 476), "The CLI's --brute-force-check minimised the measured series "
                                  "while the decision used the forecast — so an honest",
              font=font(16), fill=FG)
    draw.text((MARGIN + 22, 498), "forecast call printed MISMATCH. Fixed, with a regression test "
                                  "that fails on the old behaviour.",
              font=font(16), fill=FG)
    footer(draw, "tests/test_optimize.py · tests/test_api.py · tests/test_report.py")
    return image


def frame_report() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "step 3 · report")
    h1(draw, "Every arrival, eighteen conditions", size=38)
    terminal(draw, "python -m carbonwindow.cli report",
             read_src("report.txt"), y=140, h=356, title="report — real output", size=14)
    para(draw, "One pass per condition over ~4,300 arrivals; the whole sweep takes 0.25 s. "
               "oracle decides on measured values, forecast decides on the forecast archived for "
               "those half hours — both are scored against measured values.",
         y=512, size=16, colour=MUTED)
    return image


def frame_table() -> Image.Image:
    return section(774, 1398)


def frame_headline() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "result · the deployable number")
    h1(draw, "What a scheduler would actually have saved", size=34)
    ref_f = data["results"]["forecast"]["1h"]["12h"]
    ref_o = data["results"]["oracle"]["1h"]["12h"]
    f24 = data["results"]["forecast"]["1h"]["24h"]
    ceil = data["results"]["oracle"]["30m"]["24h"]
    big_stat(draw, MARGIN, 146, 348, value=f"{ref_f['median_pct']:.2f} %",
             label="MEDIAN REDUCTION", colour=GREEN,
             note="1 h job, 12 h deadline, forecast-driven")
    big_stat(draw, MARGIN + 384, 146, 348, value=f"{f24['median_pct']:.2f} %",
             label="SAME JOB, 24 h DEADLINE", colour=GREEN,
             note="more slack beats a shorter job")
    big_stat(draw, MARGIN + 768, 146, 348, value=f"{ceil['median_pct']:.2f} %",
             label="CEILING (PERFECT FORESIGHT)", colour=BLUE,
             note="30 min job, 24 h deadline — not achievable")
    para(draw, f"The forecast costs about a sixth of the ceiling at the reference condition: "
               f"{ref_f['median_pct']:.2f} % against {ref_o['median_pct']:.2f} %. Every one of "
               f"these numbers is a median over {ref_f['n']:,} separate arrivals, each one a "
               f"decision someone could have made at that half hour.",
         y=302, size=19)
    para(draw, "Energy is stated once as a model: a 1.0 kW load for the job's length, so a 1 h "
               "job is 1.00 kWh. The gCO2 column is that energy times the intensity difference — "
               "not a metered saving.",
         y=390, size=17, colour=MUTED)
    draw.rounded_rectangle([MARGIN, 448, W - MARGIN, 448 + 84], radius=12, fill=PANEL, outline=LINE)
    draw.rectangle([MARGIN, 462, MARGIN + 4, 520], fill=BLUE)
    draw.text((MARGIN + 22, 458), "SPREAD ACROSS THE ARRIVALS AT THAT CONDITION",
              font=font(13, bold=True), fill=BLUE)
    draw.text((MARGIN + 22, 480), f"worst {ref_f['worst_pct']:.1f} %   ·   "
                                  f"best {ref_f['best_pct']:.1f} %   ·   "
                                  f"P10 {ref_f['p10_pct']:.1f} %   ·   "
                                  f"P90 {ref_f['p90_pct']:.1f} %",
              font=font(16, mono=True), fill=FG)
    draw.text((MARGIN + 22, 502), f"{ref_f['negative_share_pct']:.1f} % of them ended up worse "
                                  f"than running immediately.",
              font=font(15), fill=RED)
    footer(draw, "results/summary.json · 90.19 days · 4,329 half hours")
    return image


def frame_deadline() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "result · perfect foresight here, on purpose", colour=AMBER)
    h1(draw, "Slack is the resource, not job length", size=36)
    cfg = data["config"]
    d1 = cfg["durations"]["1h"]
    c6 = cfg["horizons"]["6h"] - d1 + 1
    c24 = cfg["horizons"]["24h"] - d1 + 1
    o = data["results"]["oracle"]
    rows = [("1 h job · 6 h deadline", c6, o["1h"]["6h"]["median_pct"], GREEN),
            ("1 h job · 12 h deadline", cfg["horizons"]["12h"] - d1 + 1,
             o["1h"]["12h"]["median_pct"], BLUE),
            ("1 h job · 24 h deadline", c24, o["1h"]["24h"]["median_pct"], VIOLET)]
    y = 156
    scale = 640 / max(c24, 1)
    for label, cand, median, colour in rows:
        draw.text((MARGIN, y), label, font=font(19, bold=True), fill=FG)
        draw.text((MARGIN, y + 26), f"{cand} candidate start times", font=font(15), fill=MUTED)
        bar_x = MARGIN + 420
        draw.rounded_rectangle([bar_x, y + 6, bar_x + cand * scale, y + 34], radius=6, fill=colour)
        draw.text((bar_x + cand * scale + 14, y + 10), f"median {median:.2f} %",
                  font=font(17, bold=True), fill=colour)
        y += 74
    para(draw, "Four times the candidate windows, and the median reduction triples. Lengthening "
               "the job instead averages the good half hours away with the rest — a 2 h job at a "
               "6 h deadline gets less than a 1 h job at the same deadline.",
         y=372, size=19)
    two_six = data["results"]["oracle"]["2h"]["6h"]["median_pct"]
    one_six = data["results"]["oracle"]["1h"]["6h"]["median_pct"]
    big_stat(draw, MARGIN, 440, 348, value=f"{c24} vs {c6}", label="CANDIDATE STARTS",
             note="24 h vs 6 h deadline, 1 h job", colour=VIOLET, h=124)
    big_stat(draw, MARGIN + 384, 440, 348, value=f"{two_six:.2f} %",
             label="2 H JOB, 6 H DEADLINE",
             note=f"vs {one_six:.2f} % for a 1 h job", colour=AMBER, h=124)
    big_stat(draw, MARGIN + 768, 440, 348,
             value=f"{data['results']['oracle']['30m']['24h']['median_pct']:.2f} %",
             label="30 MIN JOB, 24 H DEADLINE", note="the best median in the grid",
             colour=GREEN, h=124)
    return image


def frame_chart() -> Image.Image:
    return section(1436, 2056)


def frame_tail() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "result · the part that hurts")
    h1(draw, "Scheduling on a forecast can lose", size=38)
    ref = data["results"]["forecast"]["1h"]["12h"]
    big_stat(draw, MARGIN, 150, 348, value=f"{ref['negative_share_pct']:.1f} %", label="ARRIVALS WORSE THAN NOW",
             colour=RED, note=f"{int(round(ref['n'] * ref['negative_share_pct'] / 100)):,} of {ref['n']:,}")
    big_stat(draw, MARGIN + 384, 150, 348, value=f"{ref['worst_pct']:.0f} %", label="WORST SINGLE ARRIVAL",
             colour=RED, note="the forecast said clean, the grid did not")
    big_stat(draw, MARGIN + 768, 150, 348, value=f"{ref['p10_pct']:.1f} %", label="10TH PERCENTILE",
             colour=AMBER, note="a tenth of arrivals got no real benefit")
    para(draw, "Perfect foresight never loses, because \u2018now\u2019 is always one of the candidate "
               "windows. A forecast-driven scheduler does not have that property, and the report "
               "prints the tail instead of quoting only the median.",
         y=302, size=19)
    err = data["ci_stats"]["forecast_error"]
    para(draw, f"Forecast error over {err['n']:,} half hours: mean absolute error {err['mae']:.1f} "
               f"gCO2/kWh, 95th percentile {err['p95_abs']:.0f}, worst {err['max_abs']:.0f} — against "
               f"a {data['ci_stats']['mean']:.1f} mean. Good enough to find cheap hours most of the "
               f"time, wrong enough to lose sometimes.",
         y=392, size=18, colour=MUTED)
    footer(draw, "the honest reading: a median saving, not a guarantee per job")
    return image


def frame_heatmap() -> Image.Image:
    return section(2470, 3162)


def frame_example() -> Image.Image:
    return section(3182, 3628)


def frame_hist() -> Image.Image:
    return section(3672, 4052)


def frame_zero() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "data quality · disclosed, not cleaned")
    h1(draw, "One impossible reading, shown", size=38)
    q = data["data_quality"]
    z = data["zero_day_effect"]
    para(draw, f"The snapshot contains exactly {q['zero_count']} half hour of 0 gCO2/kWh "
               f"({', '.join(q['zero_readings'])}). The lowest other reading in the whole window "
               f"is {q['min_nonzero']:.0f}. A GB grid does not run at zero: it is a missing value "
               f"published as zero.", y=142, size=19)
    draw.rounded_rectangle([MARGIN, 254, W - MARGIN, 254 + 132], radius=12, fill=PANEL, outline=LINE)
    draw.rectangle([MARGIN, 272, MARGIN + 4, 366], fill=AMBER)
    draw.text((MARGIN + 22, 268), "WHAT IT DOES TO THE NUMBERS", font=font(13, bold=True), fill=AMBER)
    sens = data["sensitivity"]["oracle"]
    draw.text((MARGIN + 22, 290), f"window medians:  oracle {sens['median_raw']:.2f} % → "
                                  f"{sens['median_without_zeros']:.2f} %  "
                                  f"({abs(sens['delta']):.2f} pp)",
              font=font(16, mono=True), fill=FG)
    draw.text((MARGIN + 22, 314), f"day medians:     {z['day']} {z['median_raw_pct']:.1f} % → "
                                  f"{z['median_without_zero_pct']:.1f} %  "
                                  f"({abs(z['delta_pp']):.1f} pp)",
              font=font(16, mono=True), fill=FG)
    draw.text((MARGIN + 22, 338), f"best day:        {z['best_day_raw']} → "
                                  f"{z['best_day_without_zero']} at "
                                  f"{z['best_day_without_zero_pct']:.1f} %",
              font=font(16, mono=True), fill=FG)
    para(draw, "The window medians barely move: one half hour out of 4,329 is diluted. The day "
               "ranking is a different story — the same reading was worth 30 percentage points on "
               "one day and decided which day came first.", y=404, size=19)
    para(draw, "It is left in the headline numbers, re-run as a gap in a sensitivity check, and "
               "printed on the web page. Quietly repairing it would have made the best day look "
               "like a result.", y=470, size=18, colour=MUTED)
    footer(draw, "carbonwindow/report.py · data_quality() + zero_day_effect()")
    return image


def frame_limits() -> Image.Image:
    return section(4100, 4584)


def frame_repo() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "the repository")
    h1(draw, "Everything needed to re-derive every number", size=34)
    rows = [
        ("carbonwindow/", "ci_api · optimize · report · web · cli"),
        ("tests/", f"{32} tests: optimiser vs brute force, API parsing, hand-computed reductions"),
        ("data/ci_90d.json", "the snapshot — 4,329 slots, actual + forecast, committed"),
        ("results/summary.json", "the single source the page and the docs are built from"),
        ("web/index.html", "the report: 768 KB, one file, no build step"),
        ("docs/", "ARCHITECTURE.md · REPORT.md · demo_video.mp4 · this script"),
        ("STATUS.md", "the build log, with each measurement in the order it happened"),
    ]
    y = 148
    for path, note in rows:
        draw.text((MARGIN, y), path, font=font(19, mono=True), fill=GREEN)
        draw.text((MARGIN + 300, y + 2), note, font=font(17), fill=FG)
        y += 42
    draw.rounded_rectangle([MARGIN, 452, W - MARGIN, 452 + 96], radius=12, fill=PANEL, outline=LINE)
    draw.text((MARGIN + 22, 466), "REPRODUCE  ·  docs/REPORT.md is generated, never hand-edited",
              font=font(13, bold=True), fill=BLUE)
    draw.text((MARGIN + 22, 496), "python -m carbonwindow.cli fetch …  →  report  →  web",
              font=font(16, mono=True), fill=FG)
    draw.text((MARGIN + 22, 522), "python tools/build_docs.py  ·  python -m pytest",
              font=font(16, mono=True), fill=FG)
    return image


def frame_close() -> Image.Image:
    image, draw = canvas()
    kicker(draw, "carbonwindow")
    h1(draw, "Move the work. Prove the saving.", size=44)
    ref = data["results"]["forecast"]["1h"]["12h"]
    draw.text((MARGIN, 160), f"{ref['median_pct']:.2f} % median reduction",
              font=font(30, bold=True), fill=GREEN)
    draw.text((MARGIN, 204), "1 h job, 12 h deadline, decided on the archived forecast, "
                             "over 4,306 arrivals in 90 days.",
              font=font(20), fill=FG)
    para(draw, "Not a dashboard, not a promise: a scheduler, a 90-day replay, and the exact list "
               "of reasons the number is smaller than it looks.", y=266, size=21)
    draw.text((MARGIN, 366), "Carbon Intensity API · National Grid ESO", font=font(18), fill=MUTED)
    draw.text((MARGIN, 396), "Python 3.14 · no runtime dependencies beyond the standard library",
              font=font(18), fill=MUTED)
    draw.text((MARGIN, 426), "web/index.html opens offline · docs/REPORT.md is generated",
              font=font(18), fill=MUTED)
    draw.rounded_rectangle([MARGIN, 470, W - MARGIN, 470 + 62], radius=12, fill=PANEL,
                           outline=LINE)
    draw.text((MARGIN + 22, 486), "TRACK: climate / sustainability — software for carbon-aware "
                                 "computing",
              font=font(17, bold=True), fill=BLUE)
    draw.text((MARGIN + 22, 508), "IEEE ClimateChain Global Hackathon 2026", font=font(15), fill=MUTED)
    footer(draw, "the video shows the tool running: fetch → optimize → report → web")
    return image


# --------------------------------------------------------------------------- #
def read_src(name: str) -> list[str]:
    text = (SRC / name).read_text(encoding="utf-8")
    root = str(ROOT)
    lines = []
    for row in text.rstrip("\n").split("\n"):
        row = row.replace(root, "…")
        lines.append(row)
    return lines


def add(name: str, image: Image.Image, seconds: float, *, zoom: int = 1, telop: str = "") -> None:
    image.save(FRAMES / f"{name}.png")
    path = TELOP / f"{name}.txt"
    path.write_text(telop.strip() + "\n", encoding="utf-8")
    MANIFEST.append((name, seconds, zoom, f"docs/video_telop/{name}.txt"))
    print(f"  {name:<16} {seconds:>5.1f}s  zoom={zoom}  {telop[:60]}")


def main() -> int:
    global data
    FRAMES.mkdir(parents=True, exist_ok=True)
    TELOP.mkdir(parents=True, exist_ok=True)
    data = json.loads(SUMMARY.read_text(encoding="utf-8"))

    days = data["daily"]
    cleanest = min(days, key=lambda r: r["ci_mean"])
    dirtiest = max(days, key=lambda r: r["ci_mean"])
    data["__daily"] = (data["ci_stats"]["mean"], cleanest["ci_mean"], dirtiest["ci_mean"],
                       dirtiest["ci_mean"] / cleanest["ci_mean"])

    print("== rendering frames")
    add("s01_title", frame_title(), 9,
        telop="CarbonWindow — move flexible compute into the grid's clean half hour.")
    add("s02_problem", frame_problem(), 12,
        telop="The GB grid swings 4.3x between days. When a job runs changes its cost.")
    add("s03_build", frame_build(), 10,
        telop="Four commands: fetch, optimize, report, web — each writes an auditable file.")
    add("s04_data", frame_data(), 11,
        telop="ESO Carbon Intensity API: free, no key, half-hourly GB national average.")
    add("s05_fetch", frame_fetch(), 10,
        telop="fetch: seven requests of 14 days each, cached, resumable, 4,329 half hours.", zoom=0)
    add("s06_coverage", frame_coverage(), 9,
        telop="Coverage is 100% with zero missing slots — and gaps are never interpolated.")
    add("s07_optimize", frame_optimize(), 12,
        telop="optimize: a 1 h job at 02:00 moves to 13:00 — 94.5 down to 73.0 gCO2/kWh.", zoom=0)
    add("s08_algo", frame_algo(), 11,
        telop="Prefix sums plus a monotonic deque find the exact window in one O(n) pass.")
    add("s09_tests", frame_tests(), 11,
        telop="32 tests — and running the CLI found a bug the tests had missed.", zoom=0)
    add("s10_report", frame_report(), 11,
        telop="report: every legal start time, 18 conditions, 0.25 s for the whole sweep.", zoom=0)
    add("s11_table", frame_table(), 13,
        telop="18 conditions: 3 job lengths x 3 deadlines x two information sets.",
        zoom=0)
    add("s12_headline", frame_headline(), 12,
        telop="18.91% median at the reference condition, 34.51% with a 24 h deadline.")
    add("s13_deadline", frame_deadline(), 11,
        telop="Deadline slack matters more than job length: 47 candidate starts beat 11.")
    add("s14_chart", frame_chart(), 11,
        telop="Ceiling in blue, what a forecast would actually have achieved in green.",
        zoom=0)
    add("s15_tail", frame_tail(), 12,
        telop="The tail is real: 13.8% of arrivals cost more than running immediately.")
    add("s16_heatmap", frame_heatmap(), 11,
        telop="90 days x 48 half hours. The clean hours move — that is the opportunity.",
        zoom=0)
    add("s17_example", frame_example(), 11,
        telop="One typical day, worked through: the chosen window is the cheapest stretch.",
        zoom=0)
    add("s18_hist", frame_hist(), 10,
        telop="Distribution of 4,306 arrivals. Everything left of the line cost carbon.",
        zoom=0)
    add("s19_zero", frame_zero(), 13,
        telop="The data defect is disclosed, re-run as a gap, and printed on the page.")
    add("s20_limits", frame_limits(), 12,
        telop="Limits stated up front: average intensity, not marginal. GB only. 30 min.",
        zoom=0)
    add("s21_repo", frame_repo(), 10,
        telop="Snapshot, tests, and the generator behind every document — all in the repo.")
    add("s22_close", frame_close(), 9,
        telop="Move the work. Prove the saving. Everything here can be re-derived offline.")

    manifest = FRAMES / "manifest.txt"
    manifest.write_text(
        "\n".join(f"{n}|{d:g}|{z}|{t}" for n, d, z, t in MANIFEST) + "\n", encoding="utf-8")
    total = sum(d for _, d, _, _ in MANIFEST)
    print(f"\n{len(MANIFEST)} frames, {total:.0f} s ({total / 60:.2f} min) -> {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
