"""Parse and validate a canonical ``.playbook`` (YAML) file into Step objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class PlaybookError(Exception):
    pass


# The single "verb" key that identifies what a step does.
ACTION_KEYS = {"open", "click", "fill", "select", "check", "upload", "pick",
               "sleep", "script", "press", "wait_for", "scroll", "hover",
               "await_email_link", "await_email_code", "search_dialog",
               "ai_fill_page"}
# Keys allowed alongside the action verb.
MODIFIER_KEYS = {"when", "selector", "optional", "role", "group", "value",
                 "wait_after", "label", "exact", "scope", "timeout"}


@dataclass
class Step:
    kind: str                       # open|click|fill|select|check|upload|pick|sleep
    target: Any = None              # primary argument (url, field label, option, seconds)
    value: Any = None               # template string for fill/select/upload
    group: str | None = None        # fieldset/question text to scope a checkbox
    role: str | None = None         # button|link|tab for click
    when: str | None = None         # condition expression
    selector: str | None = None     # explicit CSS/XPath override
    scope: str | None = None        # CSS selector restricting a checkbox/radio set
    optional: bool = False          # do not fail if element is missing
    exact: bool = False             # exact accessible-name match
    wait_after: float | None = None  # seconds to wait after the action
    timeout: int | None = None      # per-step timeout (ms); used by wait_for
    label: str | None = None        # human description for logs
    pick: dict[str, Any] = field(default_factory=dict)  # pick config
    config: dict[str, Any] = field(default_factory=dict)  # await_email_link config
    line: int | None = None         # source line for error messages

    def describe(self) -> str:
        if self.label:
            return self.label
        if self.kind == "pick":
            tgt = (self.pick.get("field") or self.pick.get("group")
                   or self.pick.get("scope") or "?")
            return f"pick -> {tgt}"
        return f"{self.kind} {self.target!r}" if self.target is not None else self.kind


@dataclass
class Playbook:
    name: str
    url: str | None
    job_id: str | None
    employer_key: str | None
    application_key: str | None
    steps: list[Step]
    raw: dict[str, Any]


def load_playbook(path: str) -> Playbook:
    text = Path(path).read_text()
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PlaybookError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise PlaybookError(f"{path}: top level must be a mapping with a 'steps' list")

    version = doc.get("version")
    if version not in (None, 1):
        raise PlaybookError(f"{path}: unsupported playbook version {version!r} (expected 1)")

    raw_steps = doc.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PlaybookError(f"{path}: 'steps' must be a non-empty list")

    steps = [_parse_step(item, idx) for idx, item in enumerate(raw_steps, start=1)]
    employer_key = doc.get("employer_key")
    application_key = employer_key or doc.get("application_key") or doc.get("site_key")
    return Playbook(
        name=doc.get("name", Path(path).stem),
        url=doc.get("url"),
        job_id=doc.get("job_id"),
        employer_key=employer_key,
        application_key=application_key,
        steps=steps,
        raw=doc,
    )


def _parse_step(item: Any, index: int) -> Step:
    if not isinstance(item, dict):
        raise PlaybookError(f"step #{index}: must be a mapping, got {type(item).__name__}")

    present_actions = [k for k in item if k in ACTION_KEYS]
    if len(present_actions) != 1:
        raise PlaybookError(
            f"step #{index}: must contain exactly one action key "
            f"({', '.join(sorted(ACTION_KEYS))}); found {present_actions or 'none'}"
        )
    kind = present_actions[0]

    unknown = set(item) - ACTION_KEYS - MODIFIER_KEYS
    if unknown:
        raise PlaybookError(f"step #{index} ({kind}): unknown keys {sorted(unknown)}")

    step = Step(
        kind=kind,
        when=item.get("when"),
        selector=item.get("selector"),
        scope=item.get("scope"),
        optional=bool(item.get("optional", False)),
        exact=bool(item.get("exact", False)),
        role=item.get("role"),
        group=item.get("group"),
        value=item.get("value"),
        wait_after=item.get("wait_after"),
        timeout=item.get("timeout"),
        label=item.get("label"),
        line=index,
    )

    if kind == "pick":
        step.pick = _parse_pick(item["pick"], index)
    elif kind == "await_email_link":
        step.config = _parse_email_cfg(item["await_email_link"], index)
    elif kind == "await_email_code":
        step.config = _parse_email_code_cfg(item["await_email_code"], index)
    elif kind == "ai_fill_page":
        step.config = _parse_ai_fill_page_cfg(item["ai_fill_page"], index)
    else:
        step.target = item[kind]

    _validate_step(step, index)
    return step


def _parse_pick(cfg: Any, index: int) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        raise PlaybookError(f"step #{index} (pick): value must be a mapping")
    if "source" not in cfg:
        raise PlaybookError(f"step #{index} (pick): missing 'source'")
    if "map" not in cfg or not isinstance(cfg["map"], dict):
        raise PlaybookError(f"step #{index} (pick): missing 'map' mapping")
    as_kind = cfg.get("as", "check" if (cfg.get("group") or cfg.get("scope")) else "select")
    if as_kind not in ("select", "check"):
        raise PlaybookError(f"step #{index} (pick): 'as' must be 'select' or 'check'")
    if as_kind == "select" and not cfg.get("field"):
        raise PlaybookError(f"step #{index} (pick as select): missing 'field'")
    return {
        "source": cfg["source"],
        "map": {_norm_key(k): v for k, v in cfg["map"].items()},
        "default": cfg.get("default"),
        "as": as_kind,
        "field": cfg.get("field"),
        "group": cfg.get("group"),
        "scope": cfg.get("scope"),
    }


def _parse_email_cfg(cfg: Any, index: int) -> dict[str, Any]:
    """Validate an ``await_email_link`` mapping.

    Matching/extraction live in the playbook; the IMAP *credentials* do not —
    they come from env vars (IMAP_HOST/IMAP_USER/IMAP_PASSWORD) or, if you must,
    templated ``username``/``password`` keys (put those in a gitignored data
    file, never in the playbook). All keys are optional except that *some* way to
    reach a mailbox must resolve at run time.
    """
    if not isinstance(cfg, dict):
        raise PlaybookError(
            f"step #{index} (await_email_link): value must be a mapping "
            f"(from:/subject:/link_pattern: ...)"
        )
    allowed = {"from", "subject", "link_pattern", "imap_host", "mailbox",
               "username", "password", "timeout", "poll"}
    unknown = set(cfg) - allowed
    if unknown:
        raise PlaybookError(
            f"step #{index} (await_email_link): unknown keys {sorted(unknown)}; "
            f"allowed: {sorted(allowed)}"
        )
    return {
        "from": cfg.get("from"),
        "subject": cfg.get("subject"),
        "link_pattern": cfg.get("link_pattern"),
        "imap_host": cfg.get("imap_host"),
        "mailbox": cfg.get("mailbox", "INBOX"),
        "username": cfg.get("username"),
        "password": cfg.get("password"),
        "timeout": cfg.get("timeout"),
        "poll": cfg.get("poll"),
    }


def _parse_email_code_cfg(cfg: Any, index: int) -> dict[str, Any]:
    """Validate an ``await_email_code`` mapping.

    It is the code-oriented sibling of ``await_email_link``: poll IMAP, extract
    a short verification code, and fill it into a field on the current page.
    """
    if not isinstance(cfg, dict):
        raise PlaybookError(
            f"step #{index} (await_email_code): value must be a mapping "
            f"(field:/from:/subject:/code_pattern: ...)"
        )
    allowed = {"field", "from", "to", "subject", "code_pattern", "imap_host",
               "mailbox", "username", "password", "timeout", "poll"}
    unknown = set(cfg) - allowed
    if unknown:
        raise PlaybookError(
            f"step #{index} (await_email_code): unknown keys {sorted(unknown)}; "
            f"allowed: {sorted(allowed)}"
        )
    return {
        "field": cfg.get("field"),
        "from": cfg.get("from"),
        "to": cfg.get("to"),
        "subject": cfg.get("subject"),
        "code_pattern": cfg.get("code_pattern"),
        "imap_host": cfg.get("imap_host"),
        "mailbox": cfg.get("mailbox", "INBOX"),
        "username": cfg.get("username"),
        "password": cfg.get("password"),
        "timeout": cfg.get("timeout"),
        "poll": cfg.get("poll"),
    }


def _parse_ai_fill_page_cfg(cfg: Any, index: int) -> dict[str, Any]:
    """Validate an AI-assisted visible-page fill step.

    The model receives a page snapshot plus selected applicant-profile values and
    may return only ordinary safe playbook actions. Final submit-like actions are
    still blocked by the AI recovery layer.
    """
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        raise PlaybookError(
            f"step #{index} (ai_fill_page): value must be a mapping "
            f"(allowed_sources:/max_actions:/instructions: ...)"
        )
    allowed = {"allowed_sources", "max_actions", "instructions", "min_confidence"}
    unknown = set(cfg) - allowed
    if unknown:
        raise PlaybookError(
            f"step #{index} (ai_fill_page): unknown keys {sorted(unknown)}; "
            f"allowed: {sorted(allowed)}"
        )
    sources = cfg.get("allowed_sources")
    if sources is not None and (
        not isinstance(sources, list) or not all(isinstance(item, str) for item in sources)
    ):
        raise PlaybookError(
            f"step #{index} (ai_fill_page): allowed_sources must be a list of data-path strings"
        )
    max_actions = cfg.get("max_actions", 12)
    try:
        max_actions = int(max_actions)
    except (TypeError, ValueError) as exc:
        raise PlaybookError(f"step #{index} (ai_fill_page): max_actions must be an integer") from exc
    if max_actions < 1 or max_actions > 30:
        raise PlaybookError(f"step #{index} (ai_fill_page): max_actions must be between 1 and 30")
    min_confidence = cfg.get("min_confidence")
    if min_confidence is not None:
        try:
            min_confidence = float(min_confidence)
        except (TypeError, ValueError) as exc:
            raise PlaybookError(
                f"step #{index} (ai_fill_page): min_confidence must be a number"
            ) from exc
    instructions = cfg.get("instructions")
    if instructions is not None and not isinstance(instructions, str):
        raise PlaybookError(f"step #{index} (ai_fill_page): instructions must be a string")
    return {
        "allowed_sources": sources,
        "max_actions": max_actions,
        "min_confidence": min_confidence,
        "instructions": instructions,
    }


def _norm_key(key: Any) -> Any:
    """Normalize map keys so YAML true/false/null and strings all match."""
    if isinstance(key, bool) or key is None:
        return key
    if isinstance(key, str):
        low = key.strip().lower()
        if low == "true":
            return True
        if low == "false":
            return False
        if low in ("null", "none"):
            return None
    return key


def _validate_step(step: Step, index: int) -> None:
    if step.kind in ("fill", "select", "upload", "script", "press", "search_dialog") and step.value is None:
        raise PlaybookError(f"step #{index} ({step.kind}): requires a 'value'")
    if step.kind == "open" and not isinstance(step.target, str):
        raise PlaybookError(f"step #{index} (open): target must be a URL string")
    if step.kind == "sleep":
        try:
            float(step.target)
        except (TypeError, ValueError):
            raise PlaybookError(f"step #{index} (sleep): target must be seconds (number)")
    if step.kind in ("wait_for", "scroll", "hover") and not isinstance(step.target, str):
        raise PlaybookError(
            f"step #{index} ({step.kind}): target must be a label/text string "
            f"(e.g. {step.kind}: \"Apply Now\")"
        )
    if step.kind == "await_email_code" and not (step.config.get("field") or step.selector):
        raise PlaybookError(
            f"step #{index} (await_email_code): requires field: or selector: "
            "so the extracted code can be filled"
        )
    if step.timeout is not None:
        try:
            int(step.timeout)
        except (TypeError, ValueError):
            raise PlaybookError(f"step #{index} ({step.kind}): 'timeout' must be milliseconds (integer)")
