"""Stable, browser-free integration API for application backends."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .context import DataError, build_context
from .dryrun import analyze
from .intake import prepare_intake_data, validate_intake
from .parser import Playbook, PlaybookError, load_playbook


_ANALYSIS_ERROR_RE = re.compile(
    r"^\[(?P<step>\d+)\] ERROR"
    r"(?: \((?P<kind>[^)]+)\))?"
    r"(?: (?P<context>[^:]+))?: (?P<message>.*)$"
)


@dataclass(frozen=True)
class PlaybookListing:
    """Public catalog metadata for a website position card."""

    institution: str
    title: str
    department: str = ""
    field: str = ""
    category: str = ""
    rank: tuple[str, ...] = ()
    tenure: str = ""
    state: str = ""


@dataclass(frozen=True)
class PlaybookManifest:
    """Non-secret metadata used to bind a product target to one playbook."""

    name: str
    version: int
    job_id: str | None
    application_key: str | None
    intake_key: str | None
    url: str | None
    sha256: str
    step_count: int
    capabilities: tuple[str, ...]
    final_human_gate: bool
    listing: PlaybookListing | None


@dataclass(frozen=True)
class ValidationIssue:
    """One deterministic problem found before browser execution."""

    code: str
    message: str
    step: int | None = None
    kind: str | None = None
    path: str | None = None
    section: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    """Result of resolving a playbook against one applicant snapshot."""

    ready: bool
    manifest: PlaybookManifest | None
    issues: tuple[ValidationIssue, ...]

    @property
    def problem_count(self) -> int:
        return len(self.issues)


def inspect_playbook(path: str | Path) -> PlaybookManifest:
    """Parse a playbook and return immutable catalog metadata."""
    source = Path(path)
    playbook = load_playbook(str(source))
    return _manifest(source, playbook)


def validate_application(
    path: str | Path,
    applicant_data: Mapping[str, Any],
    *,
    check_files: bool = False,
) -> ValidationResult:
    """Validate applicant data against a playbook without launching a browser.

    Only errors are returned. The fully rendered execution plan is deliberately
    omitted because it can contain names, addresses, answers, and local document
    paths that should not cross a backend API boundary.
    """
    source = Path(path)
    try:
        playbook = load_playbook(str(source))
        manifest = _manifest(source, playbook)
        try:
            prepared_data = prepare_intake_data(playbook, applicant_data)
            intake_issues = validate_intake(playbook, prepared_data)
        except ValueError:
            # Third-party or test playbooks may not have a product intake
            # contract. Their ordinary template resolution still works.
            prepared_data = applicant_data
            intake_issues = ()
        context = build_context(
            prepared_data, application_key=playbook.application_key
        )
        lines, problem_count = analyze(
            playbook, context, check_files=check_files
        )
    except (DataError, OSError, PlaybookError) as exc:
        return ValidationResult(
            ready=False,
            manifest=None,
            issues=(ValidationIssue(code="configuration_error", message=str(exc)),),
        )

    issues = tuple(
        ValidationIssue(
            code=issue.code,
            message=issue.message,
            path=issue.path or None,
            section=issue.section,
        )
        for issue in intake_issues
    ) + tuple(_issues_from_lines(lines))
    total_problems = problem_count + len(intake_issues)
    if total_problems and not issues:
        issues = (
            ValidationIssue(
                code="validation_error",
                message=f"{total_problems} validation problem(s) found",
            ),
        )
    return ValidationResult(
        ready=total_problems == 0,
        manifest=manifest,
        issues=issues,
    )


def _manifest(source: Path, playbook: Playbook) -> PlaybookManifest:
    kinds = {step.kind for step in playbook.steps}
    capabilities = tuple(
        capability
        for capability, required in (
            ("email_link", "await_email_link" in kinds),
            ("email_code", "await_email_code" in kinds),
            ("human_checkpoint", "pause_for_user" in kinds),
        )
        if required
    )
    version = playbook.raw.get("version", 1)
    return PlaybookManifest(
        name=playbook.name,
        version=int(version),
        job_id=str(playbook.job_id) if playbook.job_id is not None else None,
        application_key=playbook.application_key,
        intake_key=_intake_key(playbook),
        url=playbook.url,
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        step_count=len(playbook.steps),
        capabilities=capabilities,
        final_human_gate=playbook.steps[-1].kind == "pause_for_user",
        listing=_listing(playbook),
    )


def _intake_key(playbook: Playbook) -> str | None:
    raw = playbook.raw.get("intake")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise PlaybookError("intake must be a mapping")
    key = raw.get("key")
    if not isinstance(key, str) or not key.strip():
        raise PlaybookError("intake.key must be a non-empty string")
    return key.strip()


def _listing(playbook: Playbook) -> PlaybookListing | None:
    raw = playbook.raw.get("listing")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise PlaybookError("listing must be a mapping")
    allowed = {
        "institution",
        "title",
        "department",
        "field",
        "category",
        "rank",
        "tenure",
        "state",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise PlaybookError(f"listing has unknown keys: {sorted(unknown)}")
    institution = raw.get("institution")
    title = raw.get("title")
    if not isinstance(institution, str) or not institution.strip():
        raise PlaybookError("listing.institution must be a non-empty string")
    if not isinstance(title, str) or not title.strip():
        raise PlaybookError("listing.title must be a non-empty string")
    rank = raw.get("rank") or []
    if isinstance(rank, str):
        rank = [rank]
    if not isinstance(rank, list) or not all(isinstance(item, str) for item in rank):
        raise PlaybookError("listing.rank must be a string list")

    values = {}
    for key in ("department", "field", "category", "tenure", "state"):
        value = raw.get(key, "")
        if not isinstance(value, str):
            raise PlaybookError(f"listing.{key} must be a string")
        values[key] = value.strip()
    return PlaybookListing(
        institution=institution.strip(),
        title=title.strip(),
        rank=tuple(item.strip() for item in rank if item.strip()),
        **values,
    )


def _issues_from_lines(lines: list[str]):
    for line in lines:
        match = _ANALYSIS_ERROR_RE.match(line)
        if not match:
            continue
        yield ValidationIssue(
            code="step_error",
            message=(
                f"{match.group('context')}: {match.group('message')}"
                if match.group("context")
                else match.group("message")
            ),
            step=int(match.group("step")),
            kind=match.group("kind") or (
                "condition" if match.group("context") == "evaluating when" else None
            ),
        )
