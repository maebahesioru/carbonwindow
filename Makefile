# CarbonWindow — the whole pipeline, in the order it has to run.
#
#   make fetch     # one snapshot of ~90 days (7 requests, cached in data/cache/)
#   make report    # replay every arrival -> results/summary.json
#   make web       # results/summary.json -> web/index.html
#   make docs      # summary + README results block regenerated
#   make video     # docs/demo_video.mp4 (needs ffmpeg + the telop font)
#   make test      # 32 tests
#   make all       # fetch report web docs test
#
# PY defaults to the local virtualenv if one exists, so `make` works untouched.

PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python)
export OMP_NUM_THREADS ?= 2

FROM ?= 2026-07-22T00:00Z
TO   ?= 2026-10-20T04:00Z

.PHONY: all fetch report web docs video test clean

all: fetch report web docs test

fetch:
	$(PY) -m carbonwindow.cli fetch --from $(FROM) --to $(TO)

report:
	$(PY) -m carbonwindow.cli report

web:
	$(PY) -m carbonwindow.cli web

docs:
	$(PY) tools/build_docs.py

video:
	$(PY) docs/make_video_slides.py
	bash docs/make_video.sh

test:
	$(PY) -m pytest

clean:
	rm -rf results/summary.json web/index.html docs/video_frames/build .pytest_cache
