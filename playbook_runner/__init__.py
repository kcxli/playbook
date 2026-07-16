"""Declarative form-filling: parse .playbook files and run them with Playwright."""
from .parser import Playbook, Step, load_playbook, PlaybookError
from .context import build_context, load_context, DataError
from .engine import Engine, StepError
from .api import (
    PlaybookListing,
    PlaybookManifest,
    ValidationIssue,
    ValidationResult,
    inspect_playbook,
    validate_application,
)
from .intake import (
    IntakeField,
    IntakeIssue,
    IntakeOption,
    PlaybookIntake,
    get_path,
    group_fields,
    inspect_intake,
    profile_fields,
    set_path,
    validate_intake,
)

__all__ = [
    "Playbook", "Step", "load_playbook", "PlaybookError",
    "build_context", "load_context", "DataError", "Engine", "StepError",
    "PlaybookListing", "PlaybookManifest", "ValidationIssue", "ValidationResult",
    "inspect_playbook", "validate_application",
    "IntakeField", "IntakeIssue", "IntakeOption", "PlaybookIntake",
    "get_path", "group_fields", "inspect_intake", "profile_fields",
    "set_path", "validate_intake",
]
