"""Resolve a playbook against data without launching a browser.

Catches missing template paths, bad conditions, and unmet pick mappings before
you ever open a browser against a live application form.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import conditions
from .context import DataError
from .engine import _match_key
from .parser import Playbook, Step
from .template import render_text, resolve_native


def analyze(
    playbook: Playbook, context: dict[str, Any], *, check_files: bool = False
) -> tuple[list[str], int]:
    """Resolve every step and report problems, without opening a browser.

    Returns ``(lines, problem_count)``. When ``check_files`` is true, also
    verifies that each active, non-optional ``upload`` points at a file that
    actually exists on disk — a common cause of a run dying halfway through.
    """
    lines: list[str] = []
    problems = 0

    if playbook.url and not any(s.kind == "open" for s in playbook.steps):
        lines.append(f"open    {playbook.url}")

    for n, step in enumerate(playbook.steps, start=1):
        try:
            active = step.when is None or conditions.evaluate(step.when, context)
        except Exception as exc:  # noqa: BLE001
            problems += 1
            lines.append(f"[{n}] ERROR evaluating when: {step.when!r}: {exc}")
            continue
        if not active:
            lines.append(f"[{n}] skip   ({step.kind}) when={step.when!r} -> False")
            continue
        try:
            lines.append(f"[{n}] " + _describe_resolved(step, context))
        except DataError as exc:
            problems += 1
            lines.append(f"[{n}] ERROR ({step.kind}): {exc}")
            continue
        if check_files and step.kind == "upload" and not step.optional:
            problems += _check_upload_file(n, step, context, lines)

    lines.append("")
    lines.append(f"{len(playbook.steps)} steps, {problems} problem(s) found.")
    return lines, problems


def render_plan(playbook: Playbook, context: dict[str, Any]) -> list[str]:
    """Backward-compatible wrapper returning just the printable lines."""
    lines, _ = analyze(playbook, context)
    return lines


def _check_upload_file(n: int, step: Step, context: dict[str, Any], lines: list[str]) -> int:
    try:
        path = render_text(step.value, context)
    except DataError:
        return 0  # the missing-value error was already reported above
    if not Path(path).exists():
        lines.append(f"[{n}] ERROR (upload): file does not exist: {path!r}")
        return 1
    return 0


def _describe_resolved(step: Step, context: dict[str, Any]) -> str:
    if step.kind == "open":
        return f"open    {render_text(step.target, context)}"
    if step.kind == "click":
        return f"click   {render_text(step.target, context)!r}"
    if step.kind == "fill":
        return f"fill    {render_text(step.target, context)!r} = {render_text(step.value, context)!r}"
    if step.kind == "select":
        return f"select  {render_text(step.target, context)!r} -> {render_text(step.value, context)!r}"
    if step.kind == "check":
        grp = f" in {step.group!r}" if step.group else ""
        return f"check   {render_text(step.target, context)!r}{grp}"
    if step.kind == "upload":
        return f"upload  {render_text(step.target, context)!r} <- {render_text(step.value, context)!r}"
    if step.kind == "sleep":
        return f"sleep   {step.target}s"
    if step.kind == "wait_for":
        sel = f"  selector={step.selector!r}" if step.selector else ""
        return f"wait_for {render_text(step.target, context)!r}{sel}"
    if step.kind == "scroll":
        return f"scroll  {render_text(step.target, context)!r}"
    if step.kind == "hover":
        return f"hover   {render_text(step.target, context)!r}"
    if step.kind == "press":
        return f"press   {render_text(step.target, context)!r} <- {render_text(step.value, context)!r}"
    if step.kind == "script":
        return f"script  {render_text(step.target, context)!r} (js)"
    if step.kind == "pick":
        cfg = step.pick
        value = resolve_native(str(cfg["source"]), context)
        chosen = cfg["map"].get(_match_key(value, cfg["map"]), cfg.get("default"))
        tgt = cfg.get("field") or cfg.get("group") or cfg.get("scope")
        return f"pick    {cfg['source']}={value!r} -> {chosen!r}  (on {tgt!r}, as {cfg['as']})"
    return step.kind
