#!/usr/bin/env python3
"""Promote a human-confirmed live option into custom equivalences."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playbook_runner.equivalences import (
    active_groups_for_context,
    canonical_key_for_group,
    custom_equivalences_path,
    known_context_hint_groups,
    known_equivalence_groups,
    normalize,
)


class GapError(ValueError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Add a confirmed equivalence-gap candidate to the shared alias file."
    )
    parser.add_argument("gap", help="path to an equivalence-gap.json artifact")
    parser.add_argument(
        "--candidate-index",
        type=int,
        required=True,
        help="candidate_index shown in the gap artifact",
    )
    parser.add_argument(
        "--group",
        choices=known_equivalence_groups(),
        help="equivalence group; inferred only when the field context is unambiguous",
    )
    parser.add_argument(
        "--equivalences",
        default=str(custom_equivalences_path()),
        help="custom-equivalence JSON to update",
    )
    parser.add_argument(
        "--no-auto-context-hint",
        action="store_true",
        help="do not add the failed field label when it does not activate the chosen group",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the result without writing"
    )
    return parser


def promote_gap(
    gap_path: str | Path,
    *,
    candidate_index: int,
    group: str | None = None,
    equivalences_path: str | Path | None = None,
    auto_context_hint: bool = True,
) -> tuple[dict[str, Any], dict[str, str]]:
    gap = _read_object(Path(gap_path), label="gap artifact")
    if gap.get("kind") != "equivalence_gap":
        raise GapError("gap artifact must have kind='equivalence_gap'")

    wanted = str(gap.get("wanted") or "").strip()
    if not wanted:
        raise GapError("gap artifact has no wanted value")
    context = str(gap.get("context") or "").strip()
    selected = _select_candidate(gap.get("candidates"), candidate_index)
    alias = str(selected.get("label") or selected.get("value") or "").strip()
    if not alias:
        raise GapError(f"candidate {candidate_index} has no label or value")

    chosen_group = group or _infer_group(gap)
    if chosen_group not in known_equivalence_groups():
        raise GapError(f"unknown equivalence group: {chosen_group!r}")

    target = (
        Path(equivalences_path) if equivalences_path else custom_equivalences_path()
    )
    data = _read_or_initialize(target)
    groups = data.setdefault("groups", {})
    if not isinstance(groups, dict):
        raise GapError("custom-equivalence 'groups' must be an object")
    entries = groups.setdefault(chosen_group, {})
    if not isinstance(entries, dict):
        raise GapError(f"custom-equivalence group {chosen_group!r} must be an object")

    canonical = canonical_key_for_group(chosen_group, wanted) or normalize(wanted)
    _add_alias(entries, canonical, alias)

    hint_added = ""
    if (
        auto_context_hint
        and context
        and chosen_group in known_context_hint_groups()
        and chosen_group not in active_groups_for_context(context)
    ):
        hints = data.setdefault("context_hints", {})
        if not isinstance(hints, dict):
            raise GapError("custom-equivalence 'context_hints' must be an object")
        values = hints.setdefault(chosen_group, [])
        if not isinstance(values, list) or not all(
            isinstance(item, str) for item in values
        ):
            raise GapError(f"context_hints.{chosen_group} must be a string list")
        if normalize(context) not in {normalize(item) for item in values}:
            values.append(context)
            hint_added = context

    summary = {
        "group": chosen_group,
        "canonical": canonical,
        "alias": alias,
        "context_hint": hint_added,
        "path": str(target),
    }
    return data, summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data, summary = promote_gap(
            args.gap,
            candidate_index=args.candidate_index,
            group=args.group,
            equivalences_path=args.equivalences,
            auto_context_hint=not args.no_auto_context_hint,
        )
    except (GapError, OSError, json.JSONDecodeError) as exc:
        print(f"equivalence gap error: {exc}", file=sys.stderr)
        return 2

    rendered = json.dumps(data, indent=2, ensure_ascii=True) + "\n"
    if args.dry_run:
        print(rendered, end="")
    else:
        try:
            _atomic_write(Path(args.equivalences), rendered)
        except OSError as exc:
            print(
                f"equivalence gap error: could not write {args.equivalences}: {exc}",
                file=sys.stderr,
            )
            return 2
        print(
            f"Added {summary['alias']!r} -> {summary['canonical']!r} "
            f"in {summary['group']!r} ({summary['path']})"
        )
        if summary["context_hint"]:
            print(f"Added context hint {summary['context_hint']!r}")
    return 0


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GapError(f"{label} not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GapError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise GapError(f"{label} must contain a JSON object")
    return data


def _read_or_initialize(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "version": 1,
            "description": "Local deterministic aliases confirmed from new forms.",
            "groups": {},
            "context_hints": {},
        }
    return _read_object(path, label="custom-equivalence file")


def _select_candidate(raw: Any, candidate_index: int) -> dict[str, Any]:
    if not isinstance(raw, list):
        raise GapError("gap artifact candidates must be a list")
    candidates = [item for item in raw if isinstance(item, dict)]
    matches = [
        item for item in candidates if item.get("candidate_index") == candidate_index
    ]
    if not matches:
        matches = [item for item in candidates if item.get("index") == candidate_index]
    if len(matches) != 1:
        available = [
            item.get("candidate_index", item.get("index")) for item in candidates
        ]
        raise GapError(
            f"candidate index {candidate_index} is missing or ambiguous; available: {available}"
        )
    return matches[0]


def _infer_group(gap: dict[str, Any]) -> str:
    active = gap.get("active_groups")
    if not isinstance(active, list):
        active = active_groups_for_context(str(gap.get("context") or ""))
    known = set(known_equivalence_groups())
    contextual = [
        group
        for group in active
        if group in known and group not in {"yes_no", "decline"}
    ]
    if len(contextual) == 1:
        return contextual[0]
    raise GapError(
        "could not infer one equivalence group from the field context; pass --group"
    )


def _add_alias(entries: dict[str, Any], canonical: str, alias: str) -> None:
    alias_norm = normalize(alias)
    canonical_norm = normalize(canonical)
    for existing_canonical, raw_aliases in entries.items():
        values = [raw_aliases] if isinstance(raw_aliases, str) else raw_aliases
        if not isinstance(values, list):
            raise GapError(
                f"aliases for {existing_canonical!r} must be a string or list"
            )
        if alias_norm == normalize(existing_canonical) or alias_norm in {
            normalize(item) for item in values if isinstance(item, str)
        }:
            if normalize(existing_canonical) != canonical_norm:
                raise GapError(
                    f"alias {alias!r} is already assigned to {existing_canonical!r}"
                )
            return

    current = entries.setdefault(canonical, [])
    if isinstance(current, str):
        current = [current]
        entries[canonical] = current
    if not isinstance(current, list) or not all(
        isinstance(item, str) for item in current
    ):
        raise GapError(f"aliases for {canonical!r} must be a string or string list")
    if alias_norm != canonical_norm and alias_norm not in {
        normalize(item) for item in current
    }:
        current.append(alias)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            handle.write(text)
            temporary = Path(handle.name)
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
