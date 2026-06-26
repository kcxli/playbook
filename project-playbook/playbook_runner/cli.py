"""Command-line entry point for the playbook runner.

Drives a .playbook against a live form with Playwright::

    python -m playbook_runner playbooks/uthealth.playbook.yaml -d applicants/test.json

To draft a NEW playbook, use ``tools/form-extractor.js`` (paste it into the
DevTools console on the application page and hand its output to Claude).
"""
from __future__ import annotations

import argparse
import sys

from .context import DataError, load_context
from .dryrun import analyze
from .ai_recovery import AIRecovery
from .engine import Engine, StepError
from .parser import PlaybookError, load_playbook


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m playbook_runner",
        description=(
            "Run a .playbook file against an application form with Playwright.\n\n"
            "To draft a NEW playbook, paste tools/form-extractor.js into the\n"
            "DevTools console on the form page and hand its output to Claude."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("playbook", help="path to the .playbook (YAML) file")
    p.add_argument(
        "-d", "--data", action="append", default=[], metavar="FILE",
        help="applicant profile JSON (repeatable; later files override earlier)",
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
    p.add_argument("--ai-recover", action="store_true",
                   help="ask an OpenAI model for a bounded recovery plan when a non-optional step fails")
    p.add_argument("--ai-recover-model", metavar="MODEL",
                   help="OpenAI model for --ai-recover (default: PLAYBOOK_AI_MODEL or gpt-5.4-mini)")
    p.add_argument("--ai-recover-attempts", type=int, default=1, metavar="N",
                   help="maximum AI recovery attempts per failed step (default 1)")
    p.add_argument("--ai-recover-min-confidence", type=float, default=0.55, metavar="FLOAT",
                   help="minimum confidence accepted from AI recovery plans (default 0.55)")
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
        context = load_context(args.data)
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
        ai_recovery = None
        if args.ai_recover:
            ai_recovery = AIRecovery.from_env(
                model=args.ai_recover_model,
                max_attempts=max(1, args.ai_recover_attempts),
                min_confidence=args.ai_recover_min_confidence,
                log=print,
            )
        with Engine(
            context,
            headless=args.headless,
            slow_mo=args.slow_mo,
            default_timeout=args.timeout,
            screenshot_dir=args.screenshot_dir,
            pace=args.pace,
            ai_recovery=ai_recovery,
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
