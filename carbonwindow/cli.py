"""Command line entry point: ``python -m carbonwindow <command>``.

    fetch     download and cache historical CI for a date range
    optimize  plan one job and print the chosen window
    report    sweep a cached snapshot and write results/summary.json
    web       render the single-file static report (web/index.html)
    live      decide a job from the next 24 h forecast (needs the network)

Every command prints only numbers it read from a snapshot on disk.  ``fetch`` is
the single place that talks to the network for historical data.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ci_api, report as report_mod
from .optimize import (
    Plan, argmin_windows, best_window, brute_force_best_window, plan_job, window_means,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data" / "ci_90d.json"
DEFAULT_CACHE = ROOT / "data" / "cache"
DEFAULT_SUMMARY = ROOT / "results" / "summary.json"


# --------------------------------------------------------------------------- #
def cmd_fetch(args: argparse.Namespace) -> int:
    end = ci_api.parse_dt(args.to)
    start = ci_api.parse_dt(args.frm) if args.frm else end - timedelta(days=args.days)
    print(f"fetch {start:%Y-%m-%dT%H:%MZ} .. {end:%Y-%m-%dT%H:%MZ} "
          f"({(end - start).days} days, chunks of <=14 days)")
    intervals = ci_api.fetch_intensity(start, end, cache_dir=Path(args.cache),
                                       sleep=args.sleep, refresh=args.refresh)
    series = ci_api.to_series(intervals)
    out = Path(args.out)
    ci_api.save_series(series, out, meta={
        "source": "https://api.carbonintensity.org.uk/intensity/{from}/{to}",
        "requested_start_utc": start.strftime("%Y-%m-%dT%H:%MZ"),
        "requested_end_utc": end.strftime("%Y-%m-%dT%H:%MZ"),
        "intervals": len(intervals),
        "coverage": series.coverage(),
    })
    coverage = series.coverage()
    print(f"  intervals      : {len(intervals)}")
    print(f"  grid slots     : {coverage['slots']} ({coverage['slots'] * 0.5:.1f} h)")
    print(f"  actual present : {coverage['actual_present']} "
          f"({coverage['coverage_pct']}% coverage)")
    print(f"  actual missing : {coverage['actual_missing']}")
    print(f"wrote {out}")
    return 0


def cmd_optimize(args: argparse.Namespace) -> int:
    series = ci_api.load_series(Path(args.data))
    now_index = series.index_of(ci_api.parse_dt(args.now))
    duration = int(round(args.duration_hours / 0.5))
    horizon = int(round(args.horizon_hours / 0.5))
    plan = plan_job(series, now_index, duration, horizon, decide_on=args.decide_on,
                    power_kw=args.power_kw)
    if plan is None:
        print("no complete window for that job in this snapshot", file=sys.stderr)
        return 2
    print(f"snapshot      : {Path(args.data)}")
    print(f"now (UTC)     : {series.time_of(plan.baseline_index):%Y-%m-%d %H:%M}")
    print(f"job duration  : {args.duration_hours:g} h   deadline T+{args.horizon_hours:g} h")
    print(f"decide on     : {args.decide_on} "
          f"({'measured values, hindsight' if args.decide_on == 'actual' else 'the archived forecast, as at the time'})")
    print("")
    print(f"run now       : mean {plan.baseline_mean:8.2f} gCO2/kWh measured  "
          f"({series.time_of(plan.baseline_index):%H:%M} onward)")
    print(f"best window   : mean {plan.chosen_mean:8.2f} gCO2/kWh measured  "
          f"({series.time_of(plan.chosen_index):%H:%M} onward, "
          f"+{(plan.chosen_index - plan.baseline_index) * 0.5:g} h)")
    print(f"reduction     : {plan.reduction_pct:6.2f} %")
    print(f"per {plan.energy_kwh:g} kWh : {plan.gco2_baseline:7.1f} -> {plan.gco2_chosen:7.1f} gCO2 "
          f"(saves {plan.gco2_avoided:6.1f} g)")
    if args.brute_force_check:
        # Brute force the SAME series the decision was made from, and compare the
        # chosen window -- not its mean, because the plan is scored on measured
        # values while a forecast decision minimises forecast values.  Comparing
        # those two means would flag an honest forecast decision as a mismatch.
        decide = series.actual if args.decide_on == "actual" else series.forecast
        reference = brute_force_best_window(
            decide, duration, plan.baseline_index,
            plan.baseline_index + horizon - duration)
        assert reference is not None
        agree = reference[0] == plan.chosen_index
        print(f"brute force   : start+{reference[0] - plan.baseline_index:g} "
              f"mean {reference[1]:.2f} on the {args.decide_on} series "
              f"-> {'MATCH' if agree else 'MISMATCH'}")
        if not agree:
            return 3
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    series = ci_api.load_series(Path(args.data))
    payload = report_mod.build_report(series, power_kw=args.power_kw)
    payload["source_file"] = str(Path(args.data).relative_to(ROOT)) \
        if Path(args.data).is_absolute() and str(Path(args.data)).startswith(str(ROOT)) \
        else str(args.data)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    window = payload["window"]
    coverage = payload["coverage"]
    print(f"window        : {window['start_utc']} .. {window['end_utc']} "
          f"({window['span_days']} days)")
    print(f"coverage      : {coverage['actual_present']}/{coverage['slots']} "
          f"slots ({coverage['coverage_pct']}%)")
    print(f"CI mean       : {payload['ci_stats']['mean']} gCO2/kWh")
    print("")
    header = f"{'variant':9} {'job':>4} {'T':>4} {'n':>6} {'median%':>8} {'mean%':>7} " \
             f"{'worst%':>7} {'best%':>7} {'neg%':>6} {'gCO2/job':>9}"
    print(header)
    print("-" * len(header))
    for row in report_mod.compare_table(payload):
        print(f"{row['variant']:9} {row['duration']:>4} {row['horizon']:>4} {row['n']:>6} "
              f"{row['median']:>8.2f} {row['mean']:>7.2f} {row['worst']:>7.2f} "
              f"{row['best']:>7.2f} {row['negative_share']:>6.2f} {row['gco2_median']:>9.2f}")
    print(f"\nwrote {out}")
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    from . import web
    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    out = web.render(summary, Path(args.out))
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    """A real decision from the next 24 h of forecast, for a 1 h job.

    There are no measured values for the future, so every mean printed here is the
    forecast's own mean. It answers "which hour would this scheduler pick", not
    "what did it save" -- savings are measured in ``report``.
    """
    now = datetime.now(timezone.utc)
    intervals = ci_api.fetch_fw24h(now)
    raw = ci_api.to_series(intervals)
    # /fw24h carries forecast values only, so the plan works on a series whose
    # "actual" IS the forecast -- every label below says so.
    values = [v for v in raw.forecast if v is not None]
    series = ci_api.GridSeries(start=raw.start, actual=list(raw.forecast),
                               forecast=list(raw.forecast))
    if not values:
        print("the 24 h forecast endpoint returned no usable slots", file=sys.stderr)
        return 2

    duration = int(round(args.duration_hours / 0.5))
    horizon = min(series.slots, int(round(args.horizon_hours / 0.5)))
    print(f"fetched {len(values)} half hours of forecast from {series.start:%Y-%m-%dT%H:%MZ}")
    print(f"CI over the next 24 h: min {min(values):.0f} / mean "
          f"{sum(values) / len(values):.1f} / max {max(values):.0f} gCO2/kWh")
    print("")
    if horizon < duration:
        print(f"the deadline ({args.horizon_hours:g} h) is shorter than the job "
              f"({args.duration_hours:g} h)", file=sys.stderr)
        return 2

    plan = plan_job(series, 0, duration, horizon, decide_on="actual",
                    power_kw=args.power_kw)  # "actual" here == the forecast
    if plan is None:
        print("no complete window in the forecast", file=sys.stderr)
        return 2
    print(f"job {args.duration_hours:g} h, deadline T+{args.horizon_hours:g} h")
    print(f"run now     : {plan.baseline_mean:8.2f} gCO2/kWh forecast  "
          f"({series.time_of(plan.baseline_index):%H:%M} UTC onward)")
    print(f"best window : {plan.chosen_mean:8.2f} gCO2/kWh forecast  "
          f"({series.time_of(plan.chosen_index):%H:%M} UTC onward, "
          f"+{(plan.chosen_index - plan.baseline_index) * 0.5:g} h)")
    print(f"reduction   : {plan.reduction_pct:6.2f} % (forecast vs forecast)")
    print(f"per {plan.energy_kwh:g} kWh: {plan.gco2_baseline:6.1f} -> {plan.gco2_chosen:6.1f} g "
          f"(projected {plan.gco2_avoided:6.1f} g)")
    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="carbonwindow", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="download historical CI into data/")
    fetch.add_argument("--to", required=True, help="end, YYYY-MM-DD or ISO timestamp")
    fetch.add_argument("--from", dest="frm", default=None, help="start (default: to - days)")
    fetch.add_argument("--days", type=int, default=90)
    fetch.add_argument("--out", default=str(DEFAULT_DATA))
    fetch.add_argument("--cache", default=str(DEFAULT_CACHE))
    fetch.add_argument("--sleep", type=float, default=1.0, help="delay between chunks")
    fetch.add_argument("--refresh", action="store_true")
    fetch.set_defaults(func=cmd_fetch)

    optimize = sub.add_parser("optimize", help="plan one job against a snapshot")
    optimize.add_argument("--data", default=str(DEFAULT_DATA))
    optimize.add_argument("--now", required=True, help="arrival time, ISO timestamp (UTC)")
    optimize.add_argument("--duration-hours", type=float, default=2.0)
    optimize.add_argument("--horizon-hours", type=float, default=12.0)
    optimize.add_argument("--decide-on", choices=["actual", "forecast"], default="forecast")
    optimize.add_argument("--power-kw", type=float, default=1.0)
    optimize.add_argument("--brute-force-check", action="store_true")
    optimize.set_defaults(func=cmd_optimize)

    rep = sub.add_parser("report", help="sweep a snapshot into results/summary.json")
    rep.add_argument("--data", default=str(DEFAULT_DATA))
    rep.add_argument("--out", default=str(DEFAULT_SUMMARY))
    rep.add_argument("--power-kw", type=float, default=report_mod.DEFAULT_POWER_KW)
    rep.set_defaults(func=cmd_report)

    web = sub.add_parser("web", help="render web/index.html")
    web.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    web.add_argument("--out", default=str(ROOT / "web" / "index.html"))
    web.set_defaults(func=cmd_web)

    live = sub.add_parser("live", help="a real decision from the next 24 h forecast (network)")
    live.add_argument("--duration-hours", type=float, default=1.0)
    live.add_argument("--horizon-hours", type=float, default=24.0)
    live.add_argument("--power-kw", type=float, default=report_mod.DEFAULT_POWER_KW)
    live.set_defaults(func=cmd_live)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
