"""Command-line entry point for the playbook runner.

Drives a .playbook against a live form with Playwright::

    python -m playbook_runner playbooks/uthealth.playbook.yaml -d applicants/test.json

To draft a NEW playbook, use ``tools/form-extractor.js`` as the live form
evidence, then write/review the YAML playbook directly.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from .context import DataError, load_context
from .dryrun import analyze
from .engine import Engine, StepError
from .parser import PlaybookError, load_playbook
from .template import render_text


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m playbook_runner",
        description=(
            "Run a .playbook file against an application form with Playwright.\n\n"
            "To draft a NEW playbook, paste tools/form-extractor.js into the\n"
            "DevTools console on the form page, then use that output as\n"
            "evidence while writing/reviewing the playbook."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("playbook", help="path to the .playbook (YAML) file")
    p.add_argument(
        "-d", "--data", action="append", default=[], metavar="FILE",
        help="applicant profile JSON (repeatable; later files recursively merge into earlier)",
    )
    p.add_argument("--dry-run", action="store_true",
                   help="resolve templates/conditions and print the plan; no browser")
    p.add_argument("--validate", action="store_true",
                   help="like --dry-run, but also check that upload files exist and "
                        "exit nonzero if any problem is found (use this in CI/batch)")
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
    argv = list(sys.argv[1:] if argv is None else argv)
    return _run(argv)


def _run(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)

    try:
        playbook = load_playbook(args.playbook)
    except (PlaybookError, OSError) as exc:
        print(f"playbook error: {exc}", file=sys.stderr)
        return 2

    try:
        application_key = playbook.application_key or playbook.job_id
        context = load_context(args.data, application_key=application_key)
    except DataError as exc:
        print(f"data error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run or args.validate:
        lines, problems = analyze(playbook, context, check_files=args.validate)
        for line in lines:
            print(line)
        if args.validate:
            if problems:
                print(f"\n✗ validation failed: {problems} problem(s) found", file=sys.stderr)
                return 1
            print("\n✓ validation passed — every field resolves and upload files exist")
        return 0

    try:
        generated_artifact = _record_generated_values(args.playbook, playbook, context)
    except DataError as exc:
        print(f"data error: {exc}", file=sys.stderr)
        return 2

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
    if generated_artifact:
        print(f"generated values recorded in {generated_artifact}")
    return 0


def _record_generated_values(playbook_path: str, playbook, context: dict) -> Path | None:
    items = playbook.raw.get("generated_values") or []
    if not items:
        return None
    if not isinstance(items, list):
        raise DataError("playbook generated_values must be a list")

    rendered = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise DataError(f"generated_values item #{index} must be a mapping")
        key = item.get("key")
        value = item.get("value")
        if not key or value is None:
            raise DataError(f"generated_values item #{index} requires key and value")
        rendered.append({
            "key": str(key),
            "value": render_text(value, context),
            "label": str(item.get("label") or ""),
        })

    out = Path(".run") / "generated-values.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "playbook": str(playbook_path),
        "name": playbook.name,
        "job_id": playbook.job_id,
        "employer_key": playbook.application_key,
        "values": rendered,
    }
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=True) + "\n")
    return out


if __name__ == "__main__":
    raise SystemExit(main())
