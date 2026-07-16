#!/usr/bin/env python3
"""Generate a conservative playbook draft from form-extractor output.

The extractor still produces a human-readable report, but the generator reads
the JSON block between PLAYBOOK_EXTRACT_JSON_START/END. It intentionally emits
TODOs and commented button candidates where it cannot infer safe behavior.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


JSON_START = "PLAYBOOK_EXTRACT_JSON_START"
JSON_END = "PLAYBOOK_EXTRACT_JSON_END"
JSON_BLOCK_RE = re.compile(
    rf"{JSON_START}\s*(\{{.*?\}})\s*{JSON_END}",
    re.DOTALL,
)

NAV_BUTTON_RE = re.compile(
    r"\b(next|continue|save|apply|register|login|log in|sign in|sign up|create account|"
    r"submit|finish|done|cancel|delete|remove|close|back|previous|logout|sign out)\b",
    re.I,
)
SUBMIT_BUTTON_RE = re.compile(r"\b(submit|finish|delete|remove)\b", re.I)
YES_RE = re.compile(r"^(yes|y|true|1)$", re.I)
NO_RE = re.compile(r"^(no|n|false|0)$", re.I)


@dataclass(frozen=True)
class InferredValue:
    value: str
    source: str
    confidence: str


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.collect:
            return collect_mode(args)
        texts = collect_input_texts(args)
        reports = parse_reports(texts)
        if not reports:
            raise SystemExit(
                "No extractor JSON found. Paste/save the full form-extractor output, "
                f"including {JSON_START}/{JSON_END}."
            )
        write_draft_file(reports, args, allow_overwrite=args.force or args.capture_dir)
    except BrokenPipeError:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a conservative .playbook.yaml draft from one or more "
            "tools/form-extractor.js outputs."
        )
    )
    parser.add_argument(
        "-x",
        "--extract",
        action="append",
        metavar="FILE",
        help=(
            "Extractor output file. Repeat for multiple pages/states. Use '-' "
            "or omit this option to paste/read from stdin."
        ),
    )
    parser.add_argument(
        "--collect",
        action="store_true",
        help=(
            "Interactive page-by-page mode. Run once, then paste each page's "
            "form-extractor output. Each completed paste is appended to one "
            "capture file and --out is regenerated."
        ),
    )
    parser.add_argument(
        "--capture-file",
        metavar="FILE",
        help=(
            "Combined extractor-output archive for --collect. Defaults to "
            "extracts/<output-name>.txt."
        ),
    )
    parser.add_argument(
        "--capture-dir",
        metavar="DIR",
        help=(
            "Page-by-page workflow directory. With --page, saves the pasted/current "
            "extractor output as the next numbered capture, then regenerates --out "
            "from every saved capture in that directory."
        ),
    )
    parser.add_argument(
        "--page",
        metavar="LABEL",
        help=(
            "Label for the extractor output being pasted/saved into --capture-dir, "
            "for example 'personal', 'education', or 'documents'."
        ),
    )
    parser.add_argument("-o", "--out", required=True, help="Output playbook YAML path.")
    parser.add_argument("--name", help="Playbook name. Defaults to the first report title.")
    parser.add_argument("--url", help="Top-level playbook URL. Defaults to the first report URL.")
    parser.add_argument("--job-id", help="Optional job/requisition id.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden/collapsed controls as commented TODO candidates.",
    )
    parser.add_argument(
        "--buttons",
        choices=("comments", "none", "safe-active"),
        default="comments",
        help=(
            "How to handle visible buttons/links. Default comments all candidates. "
            "safe-active activates only non-navigation/non-submit buttons."
        ),
    )
    parser.add_argument(
        "--todo-prefix",
        default="answers",
        help="Data namespace for generated TODO pick sources, default: answers.",
    )
    return parser


def collect_mode(args: argparse.Namespace) -> int:
    if args.extract:
        raise SystemExit("--collect reads pasted input directly; do not pass --extract")
    if args.capture_dir or args.page:
        raise SystemExit("--collect replaces --capture-dir/--page; use only --collect")

    capture_file = Path(args.capture_file) if args.capture_file else default_capture_file(args.out)
    capture_file.parent.mkdir(parents=True, exist_ok=True)
    existing_reports = parse_reports([(str(capture_file), capture_file.read_text())]) if capture_file.exists() else []
    if existing_reports:
        write_draft_file(existing_reports, args, allow_overwrite=True)

    print(
        "Paste one full form-extractor output at a time. The draft regenerates "
        f"when {JSON_END} is seen. Press Ctrl-D when finished.",
        file=sys.stderr,
    )
    print(f"Capture file: {capture_file}", file=sys.stderr)
    print(f"Playbook: {args.out}", file=sys.stderr)

    buffer: list[str] = []
    saved_count = len(existing_reports)
    for line in sys.stdin:
        if not buffer and not starts_capture(line):
            continue
        buffer.append(line)
        if JSON_END in line:
            text = "".join(buffer)
            parse_reports([("pasted capture", text)])
            saved_count += 1
            append_capture(capture_file, text, saved_count)
            reports = parse_reports([(str(capture_file), capture_file.read_text())])
            write_draft_file(reports, args, allow_overwrite=True)
            print(
                f"Saved capture {saved_count}; regenerated {args.out} from "
                f"{len(reports)} capture(s). Paste the next page, or press Ctrl-D.",
                file=sys.stderr,
            )
            buffer = []

    if buffer and JSON_START in "".join(buffer):
        print(
            f"Ignored incomplete paste: saw {JSON_START} but not {JSON_END}.",
            file=sys.stderr,
        )
    return 0


def write_draft_file(
    reports: list[dict[str, Any]],
    args: argparse.Namespace,
    *,
    allow_overwrite: bool,
) -> None:
    draft = build_draft(reports, args)
    out = Path(args.out)
    if out.exists() and not allow_overwrite:
        raise SystemExit(f"{out} already exists; pass --force to overwrite it.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(draft)
    print(f"Wrote {out} from {len(reports)} extractor capture(s).", file=sys.stderr)


def default_capture_file(out: str) -> Path:
    output = Path(out)
    stem = output.name
    for suffix in (".yaml", ".yml"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    if stem.endswith(".playbook"):
        stem = stem[: -len(".playbook")]
    return Path("extracts") / f"{stem}.txt"


def starts_capture(line: str) -> bool:
    stripped = line.strip()
    return (
        "FORM EXTRACTOR" in stripped
        or stripped.startswith("URL:")
        or stripped.startswith("Title:")
        or stripped == JSON_START
        or stripped.startswith("{")
    )


def append_capture(capture_file: Path, text: str, index: int) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    with capture_file.open("a") as handle:
        if capture_file.stat().st_size:
            handle.write("\n\n")
        handle.write(f"# ===== Capture {index} saved {stamp} =====\n")
        handle.write(text.strip())
        handle.write("\n")


def collect_input_texts(args: argparse.Namespace) -> list[tuple[str, str]]:
    if not args.capture_dir:
        if args.page:
            raise SystemExit("--page requires --capture-dir")
        return read_inputs(args.extract)

    capture_dir = Path(args.capture_dir)
    capture_dir.mkdir(parents=True, exist_ok=True)

    if args.page:
        texts_to_save = read_inputs(args.extract)
        # Validate before saving so a partial paste does not pollute the capture dir.
        parse_reports(texts_to_save)
        saved = save_capture_texts(capture_dir, args.page, texts_to_save)
        for path in saved:
            print(f"Saved extractor capture {path}", file=sys.stderr)

    texts = read_capture_dir(capture_dir)
    if args.extract and not args.page:
        texts.extend(read_inputs(args.extract))
    if not texts:
        raise SystemExit(
            f"No captures found in {capture_dir}. Paste a page with "
            f"--capture-dir {capture_dir} --page <label> first."
        )
    return texts


def read_inputs(paths: list[str] | None) -> list[tuple[str, str]]:
    if not paths:
        if sys.stdin.isatty():
            print(
                "Paste the full form-extractor output, then press Ctrl-D.",
                file=sys.stderr,
            )
        return [("stdin", sys.stdin.read())]

    texts: list[tuple[str, str]] = []
    for raw in paths:
        if raw == "-":
            texts.append(("stdin", sys.stdin.read()))
        else:
            path = Path(raw)
            texts.append((str(path), path.read_text()))
    return texts


def read_capture_dir(capture_dir: Path) -> list[tuple[str, str]]:
    paths = sorted(capture_dir.glob("*.txt"))
    return [(str(path), path.read_text()) for path in paths]


def save_capture_texts(
    capture_dir: Path,
    page_label: str,
    texts: list[tuple[str, str]],
) -> list[Path]:
    saved: list[Path] = []
    count = len(texts)
    for index, (_source, text) in enumerate(texts, start=1):
        label = page_label if count == 1 else f"{page_label}-{index}"
        path = next_capture_path(capture_dir, label)
        path.write_text(text)
        saved.append(path)
    return saved


def next_capture_path(capture_dir: Path, page_label: str) -> Path:
    next_index = 1
    for path in capture_dir.glob("*.txt"):
        match = re.match(r"^(\d+)-", path.name)
        if match:
            next_index = max(next_index, int(match.group(1)) + 1)
    return capture_dir / f"{next_index:03d}-{slug(page_label)[:64] or 'page'}.txt"


def parse_reports(texts: list[tuple[str, str]]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for source, text in texts:
        blocks = JSON_BLOCK_RE.findall(text)
        if not blocks:
            stripped = text.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                blocks = [stripped]
        for index, block in enumerate(blocks, start=1):
            try:
                report = json.loads(block)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{source}: extractor JSON block #{index} is invalid: {exc}") from exc
            if not isinstance(report, dict):
                raise SystemExit(f"{source}: extractor JSON block #{index} is not an object")
            report["_source_file"] = source
            report["_source_index"] = index
            reports.append(report)
    return reports


def build_draft(reports: list[dict[str, Any]], args: argparse.Namespace) -> str:
    first = reports[0]
    name = args.name or first.get("title") or "Generated Application Playbook"
    url = args.url or first.get("url")

    lines: list[str] = [
        "version: 1",
        f"name: {q(name)}",
    ]
    if args.job_id:
        lines.append(f"job_id: {q(args.job_id)}")
    if url:
        lines.append(f"url: {q(url)}")

    lines.extend(
        [
            "",
            "# Draft generated by tools/draft_playbook.py from form-extractor output.",
            "# Review every TODO before running against a live application.",
            "# Navigation buttons require review; final submission always remains manual.",
            "",
            "steps:",
        ]
    )

    emitted_any_step = False
    seen_keys: set[str] = set()
    for report_index, report in enumerate(reports, start=1):
        source_label = page_label(report_index, report)
        add_comment(lines, 1, f"--- {source_label} ---")
        add_comment(lines, 1, f"source: {report.get('_source_file', 'unknown')}")
        if report.get("url"):
            add_comment(lines, 1, f"captured url: {report['url']}")
        if report.get("title"):
            add_comment(lines, 1, f"captured title: {report['title']}")

        controls = ordered_controls(report, include_hidden=False)
        if not controls:
            add_comment(lines, 1, "No visible controls found in this extractor report.")

        current_section = object()
        for control in controls:
            key = control_key(control)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            section = clean_label(control.get("section") or "")
            if section and section != current_section:
                add_comment(lines, 1, section)
                current_section = section
            emit_control_step(lines, control, args)
            emitted_any_step = True

        emit_discovered_controls(lines, report, args, seen_keys)
        if args.include_hidden:
            emit_hidden_controls(lines, report, args, seen_keys)
        emit_button_candidates(lines, report, args)
        lines.append("")

    if not emitted_any_step:
        add_comment(lines, 1, "TODO: No steps were generated. Check the extractor output.")
        lines.append(f"  - scroll: {q('bottom')}")

    add_comment(lines, 1, "Human review and final submission")
    add_step(
        lines,
        "pause_for_user",
        "Review the completed application and click the final submit button manually. "
        "Confirm here after submitting.",
    )

    return "\n".join(lines).rstrip() + "\n"


def ordered_controls(report: dict[str, Any], *, include_hidden: bool) -> list[dict[str, Any]]:
    controls = report.get("controls") or {}
    out: list[dict[str, Any]] = []
    for group_name in (
        "text_inputs",
        "native_selects",
        "datalist_inputs",
        "file_uploads",
        "radio_groups",
        "checkboxes",
        "custom_widgets",
    ):
        for item in controls.get(group_name) or []:
            if isinstance(item, dict):
                item = dict(item)
                item["_control_group"] = group_name
                out.append(item)

    if include_hidden:
        for item in controls.get("hidden_controls") or []:
            if isinstance(item, dict):
                item = dict(item)
                item["_control_group"] = "hidden_controls"
                out.append(item)

    return sorted(out, key=sort_key)


def sort_key(control: dict[str, Any]) -> tuple[str, int, str]:
    frame = str(control.get("frame") or "main")
    order = control.get("document_order")
    try:
        order_int = int(order)
    except (TypeError, ValueError):
        order_int = 999_999
    label = clean_label(control.get("label") or control.get("question") or "")
    return (frame, order_int if order_int >= 0 else 999_999, label)


def emit_control_step(lines: list[str], control: dict[str, Any], args: argparse.Namespace) -> None:
    group = control.get("_control_group")
    action = control.get("action_hint") or action_from_group(group)
    if group == "radio_groups":
        emit_radio_group(lines, control, args)
        return
    if action == "fill":
        emit_fill(lines, control)
    elif action == "select":
        emit_select(lines, control)
    elif action == "upload":
        emit_upload(lines, control)
    elif action == "press":
        emit_press(lines, control)
    elif action == "check":
        emit_check(lines, control)
    else:
        emit_comment_candidate(lines, control, "TODO: inspect this control")


def action_from_group(group: str | None) -> str:
    return {
        "text_inputs": "fill",
        "native_selects": "select",
        "datalist_inputs": "press",
        "file_uploads": "upload",
        "checkboxes": "check",
        "custom_widgets": "press",
    }.get(group or "", "inspect")


def emit_fill(lines: list[str], control: dict[str, Any]) -> None:
    label = target_label(control)
    inferred = infer_value(control)
    required = bool(control.get("required"))
    value = inferred.value if inferred else ("TODO" if required else "")
    comments = control_comments(control)
    if inferred:
        comments.append(f"value guessed from {inferred.source} ({inferred.confidence})")
    elif required:
        comments.append("TODO: required field; map this to applicant data")
    else:
        comments.append("optional unknown field left blank")
    add_comments(lines, 1, comments)
    add_step(lines, "fill", label, attrs=step_attrs(control, value=value, optional=not required))


def emit_select(lines: list[str], control: dict[str, Any]) -> None:
    label = target_label(control)
    inferred = infer_value(control)
    required = bool(control.get("required"))
    value = inferred.value if inferred else "TODO"
    comments = control_comments(control)
    add_options_comment(comments, control.get("options"))
    if inferred:
        comments.append(f"value guessed from {inferred.source} ({inferred.confidence})")
    else:
        comments.append("TODO: choose exact option text")
    add_comments(lines, 1, comments)
    add_step(lines, "select", label, attrs=step_attrs(control, value=value, optional=not required))


def emit_press(lines: list[str], control: dict[str, Any]) -> None:
    label = target_label(control)
    inferred = infer_value(control)
    required = bool(control.get("required"))
    base = inferred.value if inferred else "TODO"
    value = f"{base}, Enter"
    comments = control_comments(control)
    add_options_comment(comments, control.get("options"))
    if inferred:
        comments.append(f"value guessed from {inferred.source} ({inferred.confidence})")
    else:
        comments.append("TODO: custom widget/datalist; type exact option text")
    add_comments(lines, 1, comments)
    add_step(lines, "press", label, attrs=step_attrs(control, value=value, optional=not required))


def emit_upload(lines: list[str], control: dict[str, Any]) -> None:
    label = target_label(control)
    inferred = infer_upload_value(control)
    required = bool(control.get("required"))
    value = inferred.value if inferred else "TODO"
    comments = control_comments(control)
    if control.get("accept"):
        comments.append(f"accepts: {control['accept']}")
    if control.get("hidden"):
        comments.append("file input is hidden; runner can still use selector with upload")
    if inferred:
        comments.append(f"file guessed from {inferred.source} ({inferred.confidence})")
    else:
        comments.append("TODO: map upload to documents.* path")
    add_comments(lines, 1, comments)
    add_step(lines, "upload", label, attrs=step_attrs(control, value=value, optional=not required))


def emit_check(lines: list[str], control: dict[str, Any]) -> None:
    label = target_label(control)
    comments = control_comments(control)
    checked = bool(control.get("checked"))
    if checked:
        comments.append("already checked in captured state")
    if should_skip_checkbox(control):
        comments.append("TODO: optional/sensitive checkbox; confirm before enabling")
        emit_commented_step(lines, "check", label, attrs=step_attrs(control, optional=True), comments=comments)
        return
    add_comments(lines, 1, comments)
    add_step(lines, "check", label, attrs=step_attrs(control, optional=not bool(control.get("required"))))


def emit_radio_group(lines: list[str], group: dict[str, Any], args: argparse.Namespace) -> None:
    question = clean_label(group.get("question") or group.get("label") or group.get("name") or "Radio group")
    options = [clean_label(opt.get("option_label") or opt.get("label") or "") for opt in group.get("options") or []]
    comments = [f"radio options: {join_options(options)}"] if options else []
    if group.get("scope"):
        comments.append(f"scope candidate: {group['scope']}")
    source = infer_pick_source(question, args.todo_prefix)
    yes = first_match(options, YES_RE)
    no = first_match(options, NO_RE)
    if yes and no:
        comments.append("generated pick skeleton from Yes/No radio group")
        add_comments(lines, 1, comments)
        lines.append("  - pick:")
        lines.append(f"      group: {q(question)}")
        lines.append(f"      source: {source}")
        lines.append("      map:")
        lines.append(f"        true: {q(yes)}")
        lines.append(f"        false: {q(no)}")
        lines.append(f"      default: {q('TODO')}")
        if group.get("scope"):
            lines.append(f"    scope: {q(group['scope'])}")
        return

    comments.append("TODO: choose one option or convert to pick:")
    add_comments(lines, 1, comments)
    add_step(
        lines,
        "check",
        "TODO",
        attrs={"group": question, "scope": group.get("scope"), "optional": not bool(group.get("required"))},
    )


def emit_discovered_controls(
    lines: list[str],
    report: dict[str, Any],
    args: argparse.Namespace,
    seen_keys: set[str],
) -> None:
    findings = report.get("findings") or {}
    for kind, title in (
        ("modal_fields", "Modal/popup fields discovered by probing"),
        ("conditional_fields", "Conditional fields discovered by probing"),
    ):
        items = findings.get(kind) or []
        if not items:
            continue
        add_comment(lines, 1, title)
        for finding in items:
            trigger = finding.get("trigger") or "unknown trigger"
            add_comment(lines, 1, f"after trigger: {trigger}")
            for control in sorted((finding.get("controls") or []), key=sort_key):
                if not isinstance(control, dict):
                    continue
                key = control_key(control)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                add_comment(lines, 1, "TODO: add an appropriate when: condition if this field is conditional")
                control = dict(control)
                control["_control_group"] = infer_group_from_action(control.get("action_hint"))
                emit_control_step(lines, control, args)


def emit_hidden_controls(
    lines: list[str],
    report: dict[str, Any],
    args: argparse.Namespace,
    seen_keys: set[str],
) -> None:
    hidden = report.get("controls", {}).get("hidden_controls") or []
    if not hidden:
        return
    add_comment(lines, 1, "Hidden/collapsed controls present in DOM")
    for control in sorted(hidden, key=sort_key):
        if not isinstance(control, dict):
            continue
        key = control_key(control)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        control = dict(control)
        control["_control_group"] = infer_group_from_action(control.get("action_hint"))
        emit_comment_candidate(lines, control, "hidden/collapsed; enable only if relevant")


def emit_button_candidates(lines: list[str], report: dict[str, Any], args: argparse.Namespace) -> None:
    if args.buttons == "none":
        return
    buttons = [button for button in report.get("buttons") or [] if isinstance(button, dict)]
    if not buttons:
        return
    add_comment(lines, 1, "Button/link candidates from this captured state")
    for button in sorted(buttons, key=sort_key):
        text = clean_label(button.get("text") or button.get("label") or "")
        if not text:
            continue
        attrs = step_attrs(button, wait_after=2)
        submit_like = bool(SUBMIT_BUTTON_RE.search(text))
        risky = bool(button.get("likely_navigation_or_submit")) or submit_like
        if args.buttons == "safe-active" and not risky and not NAV_BUTTON_RE.search(text):
            add_comments(lines, 1, control_comments(button))
            add_step(lines, "click", text, attrs=attrs)
            continue
        comments = control_comments(button)
        if submit_like:
            comments.append("submit-like button; keep inactive in human-submission mode")
        else:
            comments.append(
                "button left commented; confirm ordering/navigation before enabling"
            )
        if risky and not submit_like:
            comments.append("navigation-like button")
        emit_commented_step(lines, "click", text, attrs=attrs, comments=comments)


def infer_group_from_action(action: str | None) -> str:
    return {
        "fill": "text_inputs",
        "select": "native_selects",
        "press": "custom_widgets",
        "upload": "file_uploads",
        "check": "checkboxes",
    }.get(action or "", "unknown")


def target_label(control: dict[str, Any]) -> str:
    return clean_label(
        control.get("label")
        or control.get("question")
        or control.get("placeholder")
        or control.get("name")
        or control.get("id")
        or "(unlabeled)"
    )


def step_attrs(
    control: dict[str, Any],
    *,
    value: str | None = None,
    optional: bool | None = None,
    wait_after: int | float | None = None,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    selector = control.get("selector")
    if selector and selector != "(no stable selector)":
        attrs["selector"] = selector
    if value is not None:
        attrs["value"] = value
    if control.get("frame") and control.get("frame") != "main":
        attrs["# frame"] = control.get("frame")
    if optional:
        attrs["optional"] = True
    if wait_after is not None:
        attrs["wait_after"] = wait_after
    return attrs


def add_step(lines: list[str], action: str, target: str, attrs: dict[str, Any] | None = None) -> None:
    attrs = attrs or {}
    lines.append(f"  - {action}: {q(target)}")
    for key, value in attrs.items():
        if value is None or value is False:
            continue
        if str(key).startswith("#"):
            add_comment(lines, 2, f"{str(key)[1:].strip()}: {value}")
        elif isinstance(value, bool):
            lines.append(f"    {key}: {'true' if value else 'false'}")
        elif isinstance(value, (int, float)):
            lines.append(f"    {key}: {value}")
        else:
            lines.append(f"    {key}: {q(str(value))}")


def emit_commented_step(
    lines: list[str],
    action: str,
    target: str,
    *,
    attrs: dict[str, Any] | None = None,
    comments: list[str] | None = None,
) -> None:
    add_comments(lines, 1, comments or [])
    rendered: list[str] = []
    add_step(rendered, action, target, attrs)
    for line in rendered:
        lines.append(f"  # {line[2:] if line.startswith('  ') else line}")


def emit_comment_candidate(lines: list[str], control: dict[str, Any], reason: str) -> None:
    comments = control_comments(control)
    comments.append(reason)
    emit_commented_step(lines, control.get("action_hint") or "fill", target_label(control), attrs=step_attrs(control, value="TODO"), comments=comments)


def add_comment(lines: list[str], indent: int, text: str) -> None:
    prefix = "  " * indent + "# "
    for chunk in wrap_comment(text):
        lines.append(prefix + chunk)


def add_comments(lines: list[str], indent: int, comments: list[str]) -> None:
    for comment in comments:
        if comment:
            add_comment(lines, indent, comment)


def control_comments(control: dict[str, Any]) -> list[str]:
    comments: list[str] = []
    notes = control.get("selector_notes") or []
    if notes:
        comments.extend(str(note) for note in notes)
    if control.get("frame") and control.get("frame") != "main":
        comments.append(f"inside frame: {control['frame']}")
    if control.get("required"):
        comments.append("required")
    if control.get("disabled"):
        comments.append("disabled in captured state")
    if control.get("hidden"):
        comments.append("hidden in captured state")
    return comments


def add_options_comment(comments: list[str], options: Any) -> None:
    if not isinstance(options, list) or not options:
        return
    texts = []
    for option in options:
        if isinstance(option, dict):
            text = option.get("text") or option.get("label") or option.get("value")
            if option.get("placeholder"):
                continue
        else:
            text = str(option)
        if text:
            texts.append(clean_label(text))
    if texts:
        comments.append(f"options: {join_options(texts)}")


def infer_value(control: dict[str, Any]) -> InferredValue | None:
    label = " ".join(
        str(control.get(key) or "")
        for key in ("label", "placeholder", "name", "id", "section")
    )
    text = norm(label)

    if re.search(r"\b(full name|full legal name|legal name|your name|applicant name|signature)\b", text) or text == "name":
        return InferredValue(
            "{{ person_name.legal_name.first }} {{ person_name.legal_name.last }}",
            "person_name.legal_name.first + last",
            "label heuristic",
        )

    path = infer_path(text)
    if path:
        return InferredValue(template(path), path, "label heuristic")
    return None


def infer_upload_value(control: dict[str, Any]) -> InferredValue | None:
    text = norm(" ".join(str(control.get(key) or "") for key in ("label", "name", "id", "accept", "section")))
    upload_patterns = [
        (r"\b(cv|curriculum vitae|resume|resume cv|resume/cv)\b", "documents.resume_path_or_url"),
        (r"\bcover letter\b", "documents.cover_letter_path_or_url"),
        (r"\bresearch\b", "documents.research_statement_path"),
        (r"\bteaching statement|teaching philosophy\b", "documents.teaching_statement_path"),
        (r"\bteaching evaluation", "documents.teaching_evaluations_path"),
        (r"\bsyllabus\b", "documents.syllabus_path"),
        (r"\breference", "documents.references_path"),
        (r"\badditional\b|\bother document\b|\battachment\b", "documents.additional_attachment_path"),
    ]
    for pattern, path in upload_patterns:
        if re.search(pattern, text):
            return InferredValue(template(path), path, "upload label heuristic")
    return None


def infer_path(text: str) -> str | None:
    # More specific patterns first.
    patterns = [
        (r"\bverification code\b", None),
        (r"\bconfirm password\b|\bpassword confirmation\b|\bre-enter password\b", "account.password"),
        (r"\bpassword\b", "account.password"),
        (r"\buser\s*name\b|\busername\b|\blogin id\b", "account.user_name"),
        (r"\bemail\b", "emails.institution_email"),
        (r"\bpreferred\b.*\bfirst\b", "person_name.preferred_name.preferred_first"),
        (r"\blegal\b.*\bfirst\b|\bfirst name\b|\bgiven name\b", "person_name.legal_name.first"),
        (r"\bmiddle name\b|\blegal\b.*\bmiddle\b", "person_name.legal_name.middle"),
        (r"\bpreferred\b.*\blast\b", "person_name.preferred_name.preferred_last"),
        (r"\blast name\b|\bfamily name\b|\bsurname\b|\blegal\b.*\blast\b", "person_name.legal_name.last"),
        (r"\bsuffix\b", "person_name.legal_name.suffix"),
        (r"\bjob title\b|\bposition title\b|\bcurrent title\b|\bposition\b", "work_history.0.job_title"),
        (r"^(title|prefix|salutation)\b", "person_name.legal_name.prefix"),
        (r"\bdate of birth\b|\bbirth date\b|\bdob\b", "detailed_personal_info.date_of_birth"),
        (r"\btoday'?s date\b|\bsignature date\b|\bdate signed\b|^date$", "builtins.today"),
        (r"\bcitizenship\b|\bcitizen\b", "detailed_personal_info.birth_and_citizenship.citizenship_country"),
        (r"\baddress line 2\b|\baddress 2\b|\bline two\b|\bline 2\b|\bapt\b", "address_and_contact.primary_address.line_2"),
        (r"\bstreet\b|\baddress line 1\b|\baddress 1\b|\bhome address\b|\bmailing address\b|\baddress\b", "address_and_contact.primary_address.line_1"),
        (r"\bzip\b|\bpostal\b", "address_and_contact.primary_address.postal_code"),
        (r"\bstate\b|\bprovince\b|\bdistrict\b", "address_and_contact.primary_address.state_province"),
        (r"\bcountry\b|\bregion\b", "address_and_contact.primary_address.country"),
        (r"\bcity\b", "address_and_contact.primary_address.city"),
        (r"\bmobile\b|\bcell\b", "address_and_contact.phone_numbers.mobile"),
        (r"\bhome phone\b|\btelephone.*home\b", "address_and_contact.phone_numbers.home"),
        (r"\bwork phone\b|\boffice phone\b|\btelephone.*office\b", "address_and_contact.phone_numbers.work"),
        (r"\bphone\b|\btelephone\b", "address_and_contact.phone_numbers.mobile"),
        (r"\bhighest.*education\b|\beducation level\b", "education.highest_level"),
        (r"\bdegree\b", "education.schools.0.degree"),
        (r"\bmajor\b|\bfield of study\b|\bdiscipline\b", "education.schools.0.major"),
        (r"\binstitution\b|\bschool\b|\buniversity\b|\bcollege\b", "education.schools.0.institution"),
        (r"\bgraduation\b|\bdate earned\b|\byear acquired\b|\bdate obtained\b", "education.schools.0.graduation_date"),
        (r"\bemployer\b|\bcompany\b|\borganization\b", "work_history.0.company"),
        (r"\bsupervisor\b|\bmanager\b", "work_history.0.supervisor_name"),
        (r"\bresponsibilit|\bnature of work\b|\bduties\b", "work_history.0.responsibilities"),
        (r"\breason for leaving\b", "work_history.0.reason_for_leaving"),
        (r"\bstart date\b|\bdate started\b", "work_history.0.start_date"),
        (r"\bend date\b|\bdate ended\b", "work_history.0.end_date"),
        (r"\bavailability\b|\bearliest date\b|\bstart work\b", "employment_basics.availability_to_start"),
        (r"\bsalary\b", "employment_basics.salary_expectation.amount_min"),
        (r"\breference.*email\b", "references.0.email"),
        (r"\breference.*phone\b", "references.0.phone"),
        (r"\breference.*title\b", "references.0.title"),
        (r"\breference.*company\b|\breference.*organization\b", "references.0.company"),
        (r"\breference.*name\b", "references.0.name"),
        (r"\blinkedin\b", "documents.linkedin_url"),
        (r"\bgithub\b", "documents.github_url"),
        (r"\bportfolio\b|\bwebsite\b", "documents.portfolio_url"),
        (r"\bgender\b", "identity_and_status.gender.value"),
        (r"\bpronoun\b", "identity_and_status.pronouns.set"),
        (r"\bmarital\b", "identity_and_status.marital_status.value"),
    ]
    for pattern, path in patterns:
        if re.search(pattern, text):
            return path
    return None


def infer_pick_source(question: str, prefix: str) -> str:
    text = norm(question)
    if "visa" in text or "sponsor" in text:
        return "detailed_personal_info.birth_and_citizenship.requires_visa_sponsorship"
    if "veteran" in text:
        return "answers.is_veteran"
    if "disability" in text:
        return "detailed_personal_info.disability_status.value"
    if "hispanic" in text or "latino" in text:
        return "answers.is_hispanic_or_latino"
    if "authorized" in text and "work" in text:
        return "answers.authorized_to_work_us"
    if "felony" in text or "convicted" in text:
        return "answers.felony_conviction"
    if "employee" in text or "employed" in text:
        return f"{prefix}.{slug(question)}"
    return f"{prefix}.{slug(question)}"


def should_skip_checkbox(control: dict[str, Any]) -> bool:
    text = norm(target_label(control))
    if re.search(r"\bterms\b|\bprivacy\b|\bagree\b|\bconsent\b|\bcertify\b|\battest\b", text):
        return False
    if re.search(r"\bsubmit\b|\bwithdraw\b|\bdelete\b", text):
        return True
    return not bool(control.get("required"))


def first_match(values: list[str], pattern: re.Pattern[str]) -> str | None:
    for value in values:
        if pattern.search(value.strip()):
            return value
    return None


def control_key(control: dict[str, Any]) -> str:
    selector = control.get("selector")
    if selector and selector != "(no stable selector)":
        return f"{control.get('frame', 'main')}::{selector}"
    return "::".join(
        [
            str(control.get("frame") or "main"),
            str(control.get("tag") or ""),
            str(control.get("type") or ""),
            clean_label(control.get("label") or control.get("question") or ""),
            str(control.get("document_order") or ""),
        ]
    )


def page_label(index: int, report: dict[str, Any]) -> str:
    title = clean_label(report.get("title") or "")
    source = report.get("_source_file")
    if source and source != "stdin":
        stem = Path(source).stem
        return f"Capture {index}: {stem}" + (f" ({title})" if title else "")
    return f"Capture {index}" + (f": {title}" if title else "")


def q(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def template(path: str) -> str:
    return f"{{{{ {path} }}}}"


def clean_label(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned[:80] or "todo"


def join_options(values: list[str], max_items: int = 20) -> str:
    cleaned = [clean_label(value) for value in values if clean_label(value)]
    shown = cleaned[:max_items]
    suffix = f" | ... ({len(cleaned) - max_items} more)" if len(cleaned) > max_items else ""
    return " | ".join(shown) + suffix


def wrap_comment(text: str, width: int = 110) -> list[str]:
    text = clean_label(text)
    if len(text) <= width:
        return [text]
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > width and current:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
