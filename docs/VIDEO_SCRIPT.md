# Demo video script — CarbonWindow

`docs/demo_video.mp4` · 1280×720 · 30 fps · H.264 High / yuv420p · 4 min 01 s · silent (AAC track at
−∞ so the file never plays as a broken stream) · English on-screen subtitles.

Everything on screen is a picture of a file this repository produced:

| frame | shows | source of the numbers |
| --- | --- | --- |
| s01 | title, one-sentence pitch | — |
| s02 | the swing between days | `results/summary.json → ci_stats`, `daily` |
| s03 | the four commands | the CLI itself |
| s04 | the API, and its two measured quirks | `tests/test_api.py` |
| s05 | `fetch`, real terminal output | `docs/video_src/fetch.txt` |
| s06 | coverage: 4,329 slots, 0 missing | `summary.json → coverage` |
| s07 | `optimize --brute-force-check`, real output | `docs/video_src/optimize_check.txt` |
| s08 | how the optimum is found (O(n) deque) | `carbonwindow/optimize.py` |
| s09 | `pytest`, and a bug the CLI found | `docs/video_src/pytest.txt` |
| s10 | `report`, real terminal output | `docs/video_src/report.txt` |
| s11 | the full 18-condition table | `web/index.html` (rendered) |
| s12 | medians: 18.91 %, 34.51 %, 40.54 % | `summary.json → results` |
| s13 | why the deadline dominates | `summary.json → config`, `results.oracle` |
| s14 | median reduction side by side | `web/index.html` (rendered) |
| s15 | the tail: 13.8 % worse than now | `summary.json → results.forecast` |
| s16 | 90 days × 48 half hours heatmap | `web/index.html` (rendered) |
| s17 | one day worked through | `summary.json → example` |
| s18 | distribution of 4,306 arrivals | `web/index.html` (rendered) |
| s19 | the 0 gCO2/kWh reading, disclosed | `summary.json → data_quality`, `zero_day_effect`, `sensitivity` |
| s20 | limits, stated up front | `web/index.html` (rendered) |
| s21 | repository map | the repository |
| s22 | close | `summary.json → results.forecast.reference` |

Rebuild in two commands:

```bash
.venv/bin/python docs/make_video_slides.py   # 22 PNG frames + telops + manifest
bash docs/make_video.sh                      # ffmpeg: one clip per frame, then concat
```

## Narration (the subtitles, in order)

1. CarbonWindow — move flexible compute into the grid's clean half hour.
2. The GB grid swings 4.3x between days. When a job runs changes its cost.
3. Four commands: fetch, optimize, report, web — each writes an auditable file.
4. ESO Carbon Intensity API: free, no key, half-hourly GB national average.
5. fetch: seven requests of 14 days each, cached, resumable, 4,329 half hours.
6. Coverage is 100% with zero missing slots — and gaps are never interpolated.
7. optimize: a 1 h job at 02:00 moves to 13:00 — 94.5 down to 73.0 gCO2/kWh.
8. Prefix sums plus a monotonic deque find the exact window in one O(n) pass.
9. 32 tests — and running the CLI found a bug the tests had missed.
10. report: every legal start time, 18 conditions, 0.25 s for the whole sweep.
11. 18 conditions: 3 job lengths x 3 deadlines x two information sets.
12. 18.91% median at the reference condition, 34.51% with a 24 h deadline.
13. Deadline slack matters more than job length: 47 candidate starts beat 11.
14. Ceiling in blue, what a forecast would actually have achieved in green.
15. The tail is real: 13.8% of arrivals cost more than running immediately.
16. 90 days x 48 half hours. The clean hours move — that is the opportunity.
17. One typical day, worked through: the chosen window is the cheapest stretch.
18. Distribution of 4,306 arrivals. Everything left of the line cost carbon.
19. The data defect is disclosed, re-run as a gap, and printed on the page.
20. Limits stated up front: average intensity, not marginal. GB only. 30 min.
21. Snapshot, tests, and the generator behind every document — all in the repo.
22. Move the work. Prove the saving. Everything here can be re-derived offline.

## Rules the video follows

* **No number is typed by hand.** `docs/make_video_slides.py` reads
  `results/summary.json` and the captured command output under `docs/video_src/`.
  A frame cannot show a figure the measurement did not produce.
* **Perfect foresight is labelled as such.** Frames s13 and s14 are explicitly marked
  *perfect foresight*, because they isolate the geometry of the problem from forecast
  error. s12 and s15 carry the deployable, forecast-driven numbers.
* **The bad news has its own frames.** s15 (13.8 % of arrivals worse than running now,
  worst −108.2 %) and s19 (the impossible 0 gCO2/kWh reading and what it does to the
  day ranking) exist because a demo that only shows the median would be selling
  something.
* **The terminal frames are not mock-ups.** They are the bytes in `docs/video_src/`,
  captured from real runs; only the absolute repository path is shortened to `…`.
