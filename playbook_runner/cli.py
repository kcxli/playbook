"""Command-line entry point for the playbook runner."""
from __future__ import annotations

import argparse
import sys

from .context import DataError, load_context
from .dryrun import render_plan
from .engine import Engine, StepError
from .parser import PlaybookError, load_playbook


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m playbook_runner",
        description="Run a .playbook file against an application form with Playwright.",
    )
    p.add_argument("playbook", help="path to the .playbook (YAML) file")
    p.add_argument(
        "-d", "--data", action="append", default=[], metavar="FILE",
        help="applicant profile JSON (repeatable; later files override earlier)",
    )
    p.add_argument("--dry-run", action="store_true",
                   help="resolve templates/conditions and print the plan; no browser")
    p.add_argument("--headless", action="store_true",
                   help="run without a visible browser window")
    p.add_argument("--slow-mo", type=int, default=0, metavar="MS",
                   help="slow each Playwright action by MS milliseconds (debugging)")
    p.add_argument("--pace", type=float, default=0.0, metavar="SECONDS",
                   help="pause SECONDS after every step (overall slowdown to watch)")
    p.add_argument("--timeout", type=int, default=15000, metavar="MS",
                   help="default per-action timeout in milliseconds (default 15000)")
    p.add_argument("--screenshot-dir", metavar="DIR",
                   help="directory to save a screenshot when a step fails")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        playbook = load_playbook(args.playbook)
    except (PlaybookError, OSError) as exc:
        print(f"playbook error: {exc}", file=sys.stderr)
        return 2

    try:
        context = load_context(args.data)
    except DataError as exc:
        print(f"data error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        for line in render_plan(playbook, context):
            print(line)
        return 0

    try:
        with Engine(
            context,
            headless=args.headless,
            slow_mo=args.slow_mo,
            default_timeout=args.timeout,
            screenshot_dir=args.screenshot_dir,
            pace=args.pace,
        ) as engine:
            engine.run(playbook)
    except StepError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    except DataError as exc:
        print(f"\ndata error: {exc}", file=sys.stderr)
        return 1

    print("\n✓ playbook completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
