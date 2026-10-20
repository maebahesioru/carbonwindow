# STATUS — CarbonWindow build log

Running log of what was actually measured, in order. Everything here is a result
that ran on this machine; nothing is projected. If a step failed, it says so.

Project root: `実行/210_hackathons/climatechain2026/`
Target: IEEE ClimateChain Global Hackathon, deadline 2026-10-25 23:00 JST.
Submission is done by the parent agent — no external submission, no push.

---

## 2026-10-20 13:32 JST — environment

- `python3` 3.14.8 system, no pytest/Pillow → project-local `.venv` created,
  `pytest 9.1.1`, `Pillow 13.0.0` installed.
- `ffmpeg n9.0.2`, `node v26.9.0`, 12 cores, 31 GB RAM.
- Telop font present: `/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc`
  (same approach as `opencv2026/docs/make_video.sh`).
- Playwright's headless Chromium is cached at
  `~/.cache/ms-playwright/chromium_headless_shell-1248/` → used for exact
  1280×720 screenshots of the web report (the interactive browser tool rescales
  and produced unusable full-page captures).

## 13:33 — API probe (live)

All requests returned HTTP 200:

| request | rows | note |
|---|---|---|
| `intensity/2026-10-01T00:00Z/2026-10-03T00:00Z` | 97 | includes one row starting *before* `from` |
| `intensity/2025-01-10T00:00Z/2025-01-12T00:00Z` | 97 | `actual` present for all |
| `intensity/2019-06-01T00:00Z/2019-06-02T00:00Z` | 49 | archive starts 2019 |
| `regional` | 1 snapshot | 14 DNO regions |

Key finding: the row returned just *before* the requested `from` is real and is the
reason a naive concatenation duplicates data — `_dedupe()` in `carbonwindow/ci_api.py`
handles it, and `tests/test_api.py` pins the behaviour.

## 13:36 — core implementation

`carbonwindow/{ci_api,optimize,report,cli}.py` written; 29 tests.

- Optimiser: exact sliding-window argmin over prefix sums using a monotonic deque
  (`argmin_windows`) — O(n), deterministic earliest-start tie-break.
- Verified by `tests/test_optimize.py`: 60 random series against the single-window
  brute force, 60 more against the deadline-bounded brute force, and 40 random
  `means` arrays against a full rescan of every window (tie-break included).

`python -m pytest` → **29 passed**.

## 13:38 — fetch (the snapshot everything else uses)

```
python -m carbonwindow.cli fetch --from 2026-07-22T00:00Z --to 2026-10-20T04:00Z
```

- 7 chunks of ≤14 days, rate-limit friendly.
- intervals returned: **4,329**; grid slots **4,329** (2,164.5 h).
- coverage **100.0 %** — 4,329 present, **0 missing**. No retries were needed.
- snapshot: `data/ci_90d.json` (74 KB), chunk cache in `data/cache/` (7 files).

Window actually spanned: `2026-07-21T23:30Z → 2026-10-20T04:00Z`, **90.19 days**.

## 13:39 — report sweep

- Mean CI across the window: **115.72 gCO2/kWh** (median 110.0, min 0, max 247).
- 18 conditions × every legal start time = ~4,300 arrivals per condition; runtime 0.25 s.
- Forecast archive quality: MAE **12.56**, median abs error 8, p95 **39**, worst **165**.

Headline (forecast-driven, i.e. what a real deployment would have known):

| job | deadline | median | worst |
|---|---|---|---|
| 1 h | 12 h | **18.91 %** | −108.20 % |
| 1 h | 24 h | **34.51 %** | −326.47 % |
| 30 m | 24 h | 29.87 % | −300.00 % |

Perfect foresight tops out at **40.54 %** (30 m job, 24 h deadline).

## 13:41 — data-quality defect found and disclosed

Exactly **1** reading of `0.0 gCO2/kWh` (`2026-08-06T11:00Z`) out of 4,329; the next
lowest reading in the whole window is **27**. A GB grid does not run at zero, so it
is almost certainly a missing value published as zero.

- It is **left in** every headline number (no silent repair) and flagged by
  `data_quality()` in `carbonwindow/report.py`, and `sensitivity()` re-runs the
  reference condition with it turned back into a gap: oracle median 25.93 % → 25.72 %
  (−0.21 pp), forecast median unchanged at 18.91 %. Disclosed on the web page too.

## 13:43 — web report

`web/index.html` — single file, 768 KB, no build step, no CDN. Charts are SVG emitted
from Python (so they render without JavaScript), the whole summary is also embedded
as JSON in `<script type="application/json">`.

Sections: hero + 4 stat cards, 18-row condition table, grouped bar chart, honesty
note, 90-day daily CI chart, 90 x 48 half-hour heatmap, one worked example day,
distribution histogram of 4,306 arrivals, method + limits.

Verified by screenshotting the file with headless Chromium at 1280 px and reading
the PNGs back (7 tiles, all legible; the rendered page is 4,672 px tall).

## 13:56 — docs generated from the measurement

`tools/build_docs.py` writes `docs/REPORT.md` and the `<!-- results:begin -->` block in
`README.md` straight out of `results/summary.json`, so no prose number is typed by hand.

`docs/ARCHITECTURE.md` added: data flow, module boundaries, five invariants
(no interpolation, determinism via earliest-start tie-break, one number one source,
exactness is testable, disclosure over cleaning).

## 14:00 — the 0 gCO2/kWh reading also poisons the day ranking

The zero is *oracle*-side (hindsight), so it inflates the daily table as well:

| quantity | with the zero | zero treated as a gap |
|---|---|---|
| 2026-08-06 day median | 56.82 % | **25.20 %** (-31.62 pp) |
| best day | 2026-08-06 (56.82 %) | **2026-10-16 (48.25 %)** |
| window median, oracle | 25.93 % | 25.72 % (-0.21 pp) |
| window median, forecast | 18.91 % | 18.91 % (unchanged) |

One half hour out of 4,329 barely moves a window median but moves a *day* median by
31.6 pp, because a single day only has 48 of them. Implemented as
`report.zero_day_effect()`, printed on the web page, in `docs/REPORT.md` §4-5, and
pinned by two tests. This is the kind of thing that would have become an unearned
"best day" talking point, so it is stated instead.

## 14:05 — a real bug the demo run found

`optimize --brute-force-check` with `--decide-on forecast` printed **MISMATCH** and
exited 3: the check minimised the measured series while the decision was made on the
forecast. Fixed to re-minimise the same series and compare window indices; regression
test `test_forecast_decision_is_verified_against_the_forecast_series` added.

`pytest` -> **32 passed in 0.19s**.

## 14:10 — demo video

`docs/make_video_slides.py` renders 22 frames (1280x720) from `results/summary.json`
and the captured command output in `docs/video_src/`; `docs/make_video.sh` (adapted
from `opencv2026/docs/make_video.sh`, telops via NotoSansCJK) encodes one clip per
frame and concatenates.

Result: **`docs/demo_video.mp4` — 241 s (4 min 01 s), 1280x720, 30 fps, H.264 High,
29.3 MB**, English telops. Contains real `fetch` / `optimize` / `report` / `pytest`
terminal output and five screenshots of the real rendered page.

## 14:15 — packaging

`requirements.txt` (stdlib runtime; pytest + pillow for dev), `Makefile` (fetch /
report / web / docs / video / test), `.gitignore`, `LICENSE` (MIT),
`docs/SUBMISSION_DRAFT.md` (English Devpost copy: name, tagline, description, track,
built-with, what was hard, tried-and-rejected, checklist).

## open risks for the parent

1. **Eligibility.** The skill record from earlier submissions lists IEEE ClimateChain
   among the **18+ only** Devpost events, and the account is 16. Re-read the rules page
   and the registration agreement before submitting; `docs/SUBMISSION_DRAFT.md` says the
   same at the top.
2. **Demo video URL.** Devpost rejects self-hosted MP4 URLs; the video must go to
   YouTube/Vimeo first.
3. **Nothing has been pushed.** `git init` + one local commit only, by instruction.
