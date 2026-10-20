# Devpost submission draft — CarbonWindow

Copy-paste material for the Devpost form. Every figure below is a measured value from
`results/summary.json` (window 2026-07-21 23:30 UTC → 2026-10-20 04:00 UTC, 90.19 days,
4,329 half hours, 100 % coverage). Nothing here is an estimate.

---

## Eligibility — read this before filling the form

`devpost.com/hackathons` lists **IEEE ClimateChain Global Hackathon 2026** among the events whose
eligibility is **"above the legal age of majority" (18+)**. The account this project was built
for is 16. Per the exclusion list kept from earlier submissions, IEEE ClimateChain is on it.

**So: verify the age rule on the hackathon's own rules page and in the registration agreement
before submitting.** If the agreement says 18+, this submission is not eligible and should not be
filed — the repository and the video stand on their own either way.

---

## Project name (60 char limit)

```
CarbonWindow
```

## Tagline (200 char limit)

```
A scheduler that moves flexible compute into the grid's clean half hour — scored against 90 days
of real GB carbon data, with an exact optimiser and the bad news printed next to the good.
```

## Short description (project gallery / elevator pitch)

```
The GB grid is not equally dirty all day: the cleanest day in our 90-day window averaged 48.6
gCO2/kWh, the dirtiest 209.8 — a 4.3x spread, before counting the swings inside each day.

CarbonWindow is a scheduler for work that has a deadline but no fixed start time: batch jobs,
model training, backups, CI. Point it at a job length and a deadline and it picks the half hour
with the lowest average carbon intensity that still meets the deadline, and it states what that
choice would have saved.

We replayed every legal start time of the 90-day snapshot — 18 conditions (3 job lengths x 3
deadlines x 2 information sets), ~4,300 arrivals each, scored against measured intensity, not the
forecast:

  * 1 h job, 12 h deadline, decided on the archived day-ahead forecast:
    18.91 % median reduction, 21.00 % mean, 13.8 % of arrivals ended up worse than running now.
  * Same job, 24 h deadline: 34.51 % median.
  * Ceiling with perfect foresight, 30 min job, 24 h deadline: 40.54 % median.

At a 1.0 kW load a 1 h job is 1.00 kWh, so the reference condition is ~19 gCO2 saved per job. It
is a median over a distribution, not a guarantee, and the report prints the tail: the worst single
arrival in that condition was -108.2 % — the forecast promised a clean half hour and the grid
delivered a dirty one.

The optimiser is exact, not greedy: prefix sums plus a monotonic deque find the minimum-mean
window in O(n) with no window ever missed, and the test suite checks it against brute force on
random series. The report is a single self-contained HTML file with hand-written SVG — no CDN, no
build step, no JavaScript required to read it.
```

## Built with (Devpost tag list)

```
Python, HTML, SVG, JSON, ffmpeg, pytest, Pillow, urllib
```

The runtime needs **nothing outside the Python standard library**; `pytest` and `pillow` are only
for the test suite and the demo-video renderer.

## Track

```
Climate / sustainability — software for carbon-aware computing
```

(If the form offers a "Planet / Climate" track choose that; otherwise "Open Innovation" with the
climate angle in the tagline.)

## Links (fill after the repo is pushed)

* Repository: `https://github.com/<owner>/carbonwindow` — **not pushed yet**; local commit only.
* Demo video: `docs/demo_video.mp4` — 4 min 01 s, 1280x720. Devpost only accepts YouTube/Vimeo
  URLs, so it must be uploaded (unlisted or public) before the form accepts the link.
* Static report: open `web/index.html` locally, or enable GitHub Pages and link
  `https://<owner>.github.io/carbonwindow/` (the page is one file with no external requests).

---

## "What did you build / how does it work" — longer answer (if a free-text field asks)

Four commands, each of which writes a file you can audit:

1. `fetch` — pulls half-hourly national carbon intensity for the GB grid from the National Grid ESO
   Carbon Intensity API in 14-day chunks, caches each chunk, and writes one JSON snapshot
   (`data/ci_90d.json`, 74 KB, 4,329 slots, actual + the forecast that was published at the time).
2. `optimize` — one decision for one arrival: a job of `d` half hours must start before a deadline
   `T`; the best window is the minimum mean over all legal starts. Prefix sums give O(1) window
   means, a monotonic deque keeps the candidates in order, so the whole search is O(n). A
   `--brute-force-check` flag re-minimises the same series the decision was made from and compares
   the chosen window index.
3. `report` — replays **every** legal arrival in the snapshot for 3 job lengths x 3 deadlines under
   two information sets: `oracle` (decides on measured values — the ceiling) and `forecast`
   (decides on the forecast archived for those half hours — what a deployment would have known),
   both scored against measured intensity.
4. `web` — renders the summary into one 768 KB HTML file with SVG charts: the condition table, the
   median side-by-side, a 90-day x 48-half-hour heatmap, one worked day, and the distribution of
   per-arrival reductions including everything left of zero.

Two numbers exist because the honest version of this project needed them: 13.8 % of arrivals in
the reference condition came out worse than running immediately, and the snapshot contains exactly
one 0 gCO2/kWh reading (2026-08-06T11:00Z) whose lowest other value in 90 days is 27 — we treat it
as a missing value published as zero, keep it in the headline numbers, and re-run the whole
analysis with it removed as a gap: window medians move by 0.21 pp, but the *day* ranking moves by
31.6 pp and the best day changes from 2026-08-06 to 2026-10-16. That defect is disclosed on the
web page and in `docs/REPORT.md` §4-5 rather than quietly repaired.

## "What was hard" — long answer

* **The API lies in a way that only shows up when you stitch chunks.** Every response begins one
  half hour *before* the requested `from`, so naive concatenation duplicates a slot at every chunk
  boundary. It is now de-duplicated by timestamp and asserted in `tests/test_api.py`.
* **Building a replay that cannot flatter itself.** The temptation is to decide on measured values
  and quote that as the result — it produces a beautiful 40 % headline that no deployment could
  achieve. The archive turned out to contain the genuine pre-issued forecast for each half hour, so
  the report carries both numbers with the information set printed in the column header, and the
  ceiling is labelled *not achievable* wherever it appears.
* **Missing data is where carbon claims are born.** Interpolating a cheap half hour would
  manufacture a perfect window and every downstream number would inherit the fiction. Gaps stay
  gaps; any window that touches one is dropped and counted, which is why n differs slightly between
  conditions (4,281 to 4,318).
* **A bug the CLI found and the tests had not.** `--brute-force-check` minimised the measured
  series while the decision used the forecast, so an honest forecast-driven call printed MISMATCH
  and exited 3. Fixed to re-minimise the series the decision was made from and compare window
  indices; a regression test now fails on the old behaviour. We only found it because we ran the
  tool for the demo video instead of trusting the test suite.
* **Proving the optimiser, not decorating it.** The fast path and the brute-force path live in the
  same module and the suite compares them on random series, deadline-bounded windows, and raw
  window means — including the two shapes where a greedy answer is wrong.
* **Making the deliverable re-derivable.** `docs/REPORT.md` and the README results block are
  generated from `results/summary.json`, so prose cannot drift from the measurement; the demo video
  frames are rendered from the same JSON and from captured command output, so a frame cannot show a
  number the run did not produce.

## "What we tried and rejected" (short answers, keep the honesty)

* **Marginal-intensity modelling** — the API publishes an average-intensity gauge. Shifting load
  genuinely does not move the average the way a marginal-emissions model would. We say so in the
  report's limits section instead of claiming a marginal saving we did not measure.
* **Fitting a forecast model ourselves** — out of scope for the deadline; the API's own day-ahead
  forecast is what a deployment would actually have, so that is what we scored.
* **Reporting only the median** — rejected: it hides the 13.8 % of arrivals that lost carbon, and
  the tail is the most useful thing a user of this tool can know.

## Repo layout (for the "try it out" section)

```
carbonwindow/   ci_api.py · optimize.py · report.py · web.py · cli.py
tests/          32 tests (optimiser vs brute force, API parsing, hand-computed reductions)
data/           ci_90d.json — the committed 90-day snapshot
results/        summary.json — the single source of every number above
web/            index.html — the report, one file, no build step
docs/           ARCHITECTURE.md · REPORT.md · VIDEO_SCRIPT.md · demo_video.mp4
tools/          build_docs.py — generates REPORT.md and the README results block
STATUS.md       the build log, measurements in the order they happened
```

## Quick start (paste-ready)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m carbonwindow.cli report      # the committed snapshot is already there
python -m carbonwindow.cli web         # -> web/index.html
python -m pytest                       # 32 passed
```

---

## Pre-submit checklist (parent)

1. [ ] Re-read the age rule on the hackathon rules page; if 18+, do not submit.
2. [ ] `git remote add origin …` and push (nothing has been pushed from this session).
3. [ ] Upload `docs/demo_video.mp4` to YouTube (unlisted is enough unless the rules say public) and
       put the URL in the Devpost *video* field — Devpost rejects self-hosted MP4s.
4. [ ] Enable GitHub Pages, or link the repo and tell the judges to open `web/index.html`.
5. [ ] Paste the name / tagline / description above; the tagline is under the 200-character limit
       and the title under 60.
6. [ ] Do not paste the eligibility paragraph into the submission — it is a note to us, not to the
       judges.
