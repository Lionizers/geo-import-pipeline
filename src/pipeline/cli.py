"""Command line: `pipeline run [--source NAME]` and `pipeline schedule`."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime

from croniter import croniter

from . import config, core, report

log = logging.getLogger("pipeline")


def _run(args: argparse.Namespace) -> int:
    cfg = config.load(args.config)
    r = core.run(cfg, config.dsn_from_env(), only=args.source, dry_run=args.dry_run)
    j, m = report.write(r, cfg.reports_dir)
    print(report.to_markdown(r))
    log.info("report written: %s, %s", j, m)
    return 0 if r["status"] == "ok" else 1


def _schedule(args: argparse.Namespace) -> int:
    """Runs each source on its own cron expression (schedule: in sources.yaml)."""
    cfg = config.load(args.config)
    now = datetime.now()
    plan = {s.name: croniter(s.schedule, now).get_next(datetime)
            for s in cfg.sources if s.enabled and s.schedule}
    if not plan:
        log.error("no source has a 'schedule'")
        return 2
    for name, nxt in plan.items():
        log.info("source %s: next run %s", name, nxt.isoformat(timespec="minutes"))
    while True:
        now = datetime.now()
        due = [n for n, t in plan.items() if t <= now]
        if due:
            r = core.run(cfg, config.dsn_from_env(), only=due)
            report.write(r, cfg.reports_dir)
            for n in due:
                src = next(s for s in cfg.sources if s.name == n)
                plan[n] = croniter(src.schedule, now).get_next(datetime)
        time.sleep(30)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="pipeline", description="Geodata import pipeline (WFS/CSV -> PostgreSQL/PostGIS)")
    p.add_argument("--config", default="config/sources.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run all (or selected) sources once")
    r.add_argument("--source", action="append", help="only this source; repeatable")
    r.add_argument("--dry-run", action="store_true", help="fetch and diff, but write nothing")
    r.set_defaults(func=_run)
    s = sub.add_parser("schedule", help="run sources on their cron schedule (service mode)")
    s.set_defaults(func=_schedule)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
