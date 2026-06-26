"""Optional AI-assisted recovery for failed browser steps.

The recovery agent is deliberately narrow: it receives a compact page snapshot
and may propose only ordinary playbook actions. It cannot run arbitrary
JavaScript, cannot solve CAPTCHA, and is blocked from submit-like actions.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .parser import Step
from .template import render_text

try:
    import certifi
except ImportError:  # pragma: no cover - dependency is pinned in requirements.txt
    certifi = None


class AIRecoveryError(Exception):
    """Raised when recovery cannot be attempted or returns an unusable plan."""


@dataclass
class RecoveryAction:
    kind: str
    target: str
    selector: str | None = None
    value: str | None = None
    role: str | None = None
    exact: bool = False
    wait_after: float | None = None


@dataclass
class RecoveryPlan:
    decision: str
    confidence: float
    reason: str
    actions: list[RecoveryAction]


RECOVERABLE_KINDS = {"click", "fill", "select", "check", "upload", "press", "wait_for", "scroll", "sleep"}
DEFAULT_COPILOT_SOURCES = [
    "person_name",
    "emails",
    "address_and_contact",
    "education",
    "work_history",
    "documents",
    "answers",
    "detailed_personal_info",
    "employment_basics",
    "references",
    "referral_and_relationships",
    "compliance_and_consent",
]
_SENSITIVE_PATH_RE = re.compile(
    r"(^|\.|_)(password|passcode|token|secret|api[_-]?key|ssn|social[_-]?security|"
    r"bank|routing|credit[_-]?card)($|\.|_)",
    re.I,
)
_BLOCKED_TEXT_RE = re.compile(
    r"\b("
    r"captcha|recaptcha|hcaptcha|turnstile|"
    r"social security|ssn|bank account|routing number|credit card|payment|"
    r"submit application|submit delivery|final submit|finish application|"
    r"certify and submit|complete application"
    r")\b",
    re.I,
)
_ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "confidence", "reason", "actions"],
    "properties": {
        "decision": {"type": "string", "enum": ["recover", "give_up"]},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "target", "selector", "value", "role", "exact", "wait_after"],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": sorted(RECOVERABLE_KINDS),
                    },
                    "target": {"type": "string"},
                    "selector": {"type": ["string", "null"]},
                    "value": {"type": ["string", "null"]},
                    "role": {"type": ["string", "null"], "enum": ["button", "link", "tab", "option", None]},
                    "exact": {"type": "boolean"},
                    "wait_after": {"type": ["number", "null"]},
                },
            },
        },
    },
}


class AIRecovery:
    def __init__(
        self,
        *,
        model: str,
        max_attempts: int = 1,
        min_confidence: float = 0.55,
        log: Callable[[str], None] = print,
    ):
        self.model = model
        self.max_attempts = max_attempts
        self.min_confidence = min_confidence
        self.log = log

    @classmethod
    def from_env(
        cls,
        *,
        model: str | None,
        max_attempts: int,
        min_confidence: float,
        log: Callable[[str], None],
    ) -> "AIRecovery":
        chosen = model or os.environ.get("PLAYBOOK_AI_MODEL") or "gpt-5.4-mini"
        return cls(
            model=chosen,
            max_attempts=max_attempts,
            min_confidence=min_confidence,
            log=log,
        )

    def propose(
        self,
        *,
        page,
        step_number: int,
        step: Step,
        error: Exception,
        context: dict[str, Any],
        recent_steps: list[str],
    ) -> RecoveryPlan:
        if not os.environ.get("OPENAI_API_KEY"):
            raise AIRecoveryError("OPENAI_API_KEY is not set")

        bundle = self._failure_bundle(page, step_number, step, error, context, recent_steps)
        raw = self._call_openai(bundle)
        plan = self._parse_plan(raw)
        self._validate_plan(plan, max_actions=4, label="AI recovery")
        return plan

    def propose_page_fill(
        self,
        *,
        page,
        step_number: int,
        step: Step,
        context: dict[str, Any],
        recent_steps: list[str],
    ) -> RecoveryPlan:
        """Ask the model to fill the current visible page from profile data.

        This is the Simplify-style assist path: interpret the page in front of
        the runner, map visible controls to known applicant-profile values, and
        return ordinary safe actions. It is still bounded by action schemas,
        confidence checks, and final-submit/sensitive-action blocking.
        """
        if not os.environ.get("OPENAI_API_KEY"):
            raise AIRecoveryError("OPENAI_API_KEY is not set")

        cfg = step.config
        allowed_sources = cfg.get("allowed_sources") or DEFAULT_COPILOT_SOURCES
        min_confidence = cfg.get("min_confidence")
        old_threshold = self.min_confidence
        if min_confidence is not None:
            self.min_confidence = float(min_confidence)
        try:
            bundle = self._page_fill_bundle(
                page,
                step_number,
                step,
                context,
                recent_steps,
                allowed_sources=allowed_sources,
            )
            raw = self._call_openai(bundle)
            plan = self._parse_plan(raw)
            self._validate_plan(
                plan,
                max_actions=int(cfg.get("max_actions", 12)),
                label="AI page copilot",
            )
            return plan
        finally:
            self.min_confidence = old_threshold

    def _failure_bundle(
        self,
        page,
        step_number: int,
        step: Step,
        error: Exception,
        context: dict[str, Any],
        recent_steps: list[str],
    ) -> dict[str, Any]:
        try:
            title = page.title()
        except Exception:
            title = ""
        try:
            url = page.url
        except Exception:
            url = ""

        return {
            "task": "repair_failed_step",
            "step_number": step_number,
            "failed_step": _step_for_prompt(step, context),
            "error": str(error),
            "url": url,
            "title": title,
            "recent_steps": recent_steps[-12:],
            "page_snapshot": capture_page_snapshot(page),
            "allowed_actions": sorted(RECOVERABLE_KINDS),
            "safety_rules": [
                "Do not solve or bypass CAPTCHA, reCAPTCHA, hCaptcha, or Turnstile.",
                "Do not click final submit/finish/certify buttons.",
                "Do not invent applicant facts or answer sensitive questions without the failed step's value.",
                "Prefer selectors from the page_snapshot. Use visible labels only when selector is absent.",
                "Use give_up if the safe recovery is unclear.",
            ],
        }

    def _page_fill_bundle(
        self,
        page,
        step_number: int,
        step: Step,
        context: dict[str, Any],
        recent_steps: list[str],
        *,
        allowed_sources: list[str],
    ) -> dict[str, Any]:
        try:
            title = page.title()
        except Exception:
            title = ""
        try:
            url = page.url
        except Exception:
            url = ""

        return {
            "task": "fill_current_visible_application_page",
            "step_number": step_number,
            "step": {
                "kind": step.kind,
                "instructions": step.config.get("instructions"),
                "max_actions": step.config.get("max_actions", 12),
            },
            "url": url,
            "title": title,
            "recent_steps": recent_steps[-12:],
            "page_snapshot": capture_page_snapshot(page),
            "profile_values": profile_values_for_prompt(context, allowed_sources=allowed_sources),
            "allowed_actions": sorted(RECOVERABLE_KINDS),
            "safety_rules": [
                "Use only profile_values; do not invent applicant facts.",
                "Fill only fields visible in page_snapshot, including visible iframe snapshots.",
                "Prefer selectors from page_snapshot. Use visible labels only when selector is absent.",
                "Do not click final submit/finish/certify buttons; stop before submission.",
                "Do not solve or bypass CAPTCHA, reCAPTCHA, hCaptcha, or Turnstile.",
                "Do not answer payment, SSN, banking, or government-ID fields.",
                "Use give_up if the safe mapping is unclear.",
            ],
        }

    def _call_openai(self, bundle: dict[str, Any]) -> str:
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You help repair and fill job-application browser automation flows. "
                        "Return only the requested structured JSON. Be conservative. "
                        "If the page appears to require CAPTCHA, final submission, payment, "
                        "SSN, banking, or invented personal facts, choose give_up."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(bundle, ensure_ascii=False),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "playbook_recovery_plan",
                    "strict": True,
                    "schema": _ACTION_SCHEMA,
                }
            },
            "max_output_tokens": 1200,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=data,
            headers={
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            context = ssl.create_default_context(cafile=certifi.where()) if certifi else None
            with urllib.request.urlopen(req, timeout=45, context=context) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise AIRecoveryError(f"OpenAI API error {exc.code}: {detail[:500]}") from exc
        except Exception as exc:  # noqa: BLE001
            raise AIRecoveryError(f"OpenAI API request failed: {exc}") from exc

        text = body.get("output_text")
        if isinstance(text, str) and text.strip():
            return text
        for item in body.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in ("output_text", "text") and content.get("text"):
                    return content["text"]
        raise AIRecoveryError("OpenAI response did not include output_text")

    def _parse_plan(self, raw: str) -> RecoveryPlan:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AIRecoveryError(f"AI recovery returned invalid JSON: {raw[:300]}") from exc
        actions = [
            RecoveryAction(
                kind=item["kind"],
                target=item["target"],
                selector=item.get("selector"),
                value=item.get("value"),
                role=item.get("role"),
                exact=bool(item.get("exact")),
                wait_after=_normalize_wait_after(item.get("wait_after")),
            )
            for item in data.get("actions", [])
        ]
        return RecoveryPlan(
            decision=data.get("decision", "give_up"),
            confidence=float(data.get("confidence", 0)),
            reason=str(data.get("reason", "")),
            actions=actions,
        )

    def _validate_plan(
        self,
        plan: RecoveryPlan,
        *,
        max_actions: int,
        label: str,
    ) -> None:
        if plan.decision != "recover":
            return
        if plan.confidence < self.min_confidence:
            raise AIRecoveryError(
                f"{label} confidence {plan.confidence:.2f} below threshold "
                f"{self.min_confidence:.2f}: {plan.reason}"
            )
        if not plan.actions:
            raise AIRecoveryError(f"{label} chose recover but returned no actions")
        if len(plan.actions) > max_actions:
            raise AIRecoveryError(f"{label} proposed too many actions")
        for action in plan.actions:
            if action.kind not in RECOVERABLE_KINDS:
                raise AIRecoveryError(f"{label} proposed unsupported action: {action.kind}")
            if action.kind in {"fill", "select", "upload", "press"} and action.value is None:
                raise AIRecoveryError(f"{label} proposed {action.kind} without a value")
            if action.kind == "sleep":
                try:
                    sleep_for = float(action.target)
                except ValueError as exc:
                    raise AIRecoveryError(f"{label} proposed sleep with non-numeric target") from exc
                if sleep_for > 10:
                    raise AIRecoveryError(f"{label} proposed an excessive sleep: {sleep_for}s")
            if action.wait_after is not None and action.wait_after > 10:
                raise AIRecoveryError(
                    f"{label} proposed an excessive wait_after: {action.wait_after}s"
                )
            blob = " ".join(str(x or "") for x in (action.kind, action.target, action.selector, action.value))
            if _BLOCKED_TEXT_RE.search(blob):
                raise AIRecoveryError(f"{label} proposed blocked/sensitive action: {blob[:160]}")


def action_to_step(action: RecoveryAction, *, line: int | None = None) -> Step:
    return Step(
        kind=action.kind,
        target=float(action.target) if action.kind == "sleep" else action.target,
        value=action.value,
        selector=action.selector,
        role=action.role,
        exact=action.exact,
        wait_after=action.wait_after,
        line=line,
        label=f"AI recovery: {action.kind} {action.target!r}",
    )


def _normalize_wait_after(value: Any) -> float | None:
    if value is None:
        return None
    try:
        wait = float(value)
    except (TypeError, ValueError):
        return None
    if wait < 0:
        return None
    # The playbook format uses seconds, but models often return milliseconds
    # for small UI pauses. Treat large values as ms to avoid multi-minute hangs.
    if wait > 30:
        wait = wait / 1000.0
    return min(wait, 10.0)


def capture_page_snapshot(page, *, max_items: int = 120) -> dict[str, Any]:
    script = r"""
    (maxItems) => {
      const visible = el => {
        if (!el || !el.isConnected) return false;
        const s = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
      };
      const text = el => (el.innerText || el.value || el.textContent || '').replace(/\s+/g, ' ').trim();
      const esc = v => window.CSS && CSS.escape ? CSS.escape(String(v)) : String(v).replace(/["\\#.:,[\]= >+~*|^$]/g, '\\$&');
      const selector = el => {
        if (el.id) return `#${esc(el.id)}`;
        if (el.name) return `${el.tagName.toLowerCase()}[name="${String(el.name).replace(/"/g, '\\"')}"]`;
        const aria = el.getAttribute('aria-label');
        if (aria) return `${el.tagName.toLowerCase()}[aria-label="${aria.replace(/"/g, '\\"')}"]`;
        return '';
      };
      const labelFor = el => {
        if (el.id) {
          const l = document.querySelector(`label[for="${esc(el.id)}"]`);
          if (l && text(l)) return text(l);
        }
        const wrap = el.closest('label');
        if (wrap && text(wrap)) return text(wrap);
        const aria = el.getAttribute('aria-label');
        if (aria) return aria.trim();
        const ph = el.getAttribute('placeholder');
        if (ph) return ph.trim();
        const near = el.closest('tr,.form-group,.field,.question,.form-row,li,section,div');
        return near ? text(near).slice(0, 180) : '';
      };
      const controls = [];
      const add = (kind, el, extra = {}) => {
        if (controls.length >= maxItems) return;
        controls.push({
          kind,
          tag: el.tagName.toLowerCase(),
          type: el.getAttribute('type') || '',
          label: labelFor(el),
          text: text(el).slice(0, 180),
          selector: selector(el),
          role: el.getAttribute('role') || '',
          disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
          ...extra
        });
      };
      document.querySelectorAll('button,input[type=button],input[type=submit],a,[role=button]')
        .forEach(el => { if (visible(el)) add('clickable', el); });
      document.querySelectorAll('input:not([type=hidden]):not([type=button]):not([type=submit]),textarea,select,[role=combobox]')
        .forEach(el => {
          if (!visible(el) && el.getAttribute('type') !== 'file') return;
          const tag = el.tagName.toLowerCase();
          const typ = el.getAttribute('type') || '';
          const kind = typ === 'file' ? 'file' : tag === 'select' ? 'select' : typ === 'radio' ? 'radio' : typ === 'checkbox' ? 'checkbox' : 'field';
          const extra = tag === 'select' ? {
            options: Array.from(el.options || []).map(o => o.text.trim()).filter(Boolean).slice(0, 40)
          } : {};
          add(kind, el, extra);
        });
      const alerts = Array.from(document.querySelectorAll(
        '[role=alert],.error,.errors,.invalid-feedback,.field-validation-error,.validation-error,[aria-invalid=true]'
      )).filter(visible).map(el => text(el).slice(0, 240)).filter(Boolean).slice(0, 30);
      const dialogs = Array.from(document.querySelectorAll(
        '[role=dialog],dialog,.modal,.popup,.cdk-overlay-pane'
      )).filter(visible).map(el => text(el).slice(0, 500)).filter(Boolean).slice(0, 10);
      const bodyText = text(document.body).slice(0, 3000);
      return { controls, alerts, dialogs, bodyText };
    }
    """
    try:
        snapshot = page.evaluate(script, max_items)
    except Exception as exc:  # noqa: BLE001
        snapshot = {"controls": [], "alerts": [], "dialogs": [], "bodyText": "", "error": str(exc)}
    frames: list[dict[str, Any]] = []
    try:
        main = page.main_frame
        for frame in page.frames:
            if frame == main:
                continue
            if len(frames) >= 8:
                break
            try:
                child = frame.evaluate(script, min(40, max_items))
                frames.append({
                    "name": frame.name,
                    "url": frame.url,
                    "controls": child.get("controls", []),
                    "alerts": child.get("alerts", []),
                    "dialogs": child.get("dialogs", []),
                    "bodyText": child.get("bodyText", "")[:1500],
                })
            except Exception as exc:  # noqa: BLE001
                frames.append({"name": frame.name, "url": frame.url, "error": str(exc)})
    except Exception:
        pass
    snapshot["frames"] = frames
    return snapshot


def profile_values_for_prompt(
    context: dict[str, Any],
    *,
    allowed_sources: list[str],
    max_items: int = 260,
) -> list[dict[str, Any]]:
    """Return scalar profile values the copilot may use.

    The model needs actual values to fill forms, but we keep the slice bounded
    and skip password/token/financial/government-ID-like paths. Values are
    accompanied by their profile path so successful AI plans are easier to
    translate back into durable playbook steps later.
    """
    values: list[dict[str, Any]] = []

    def add(path: str, value: Any) -> None:
        if len(values) >= max_items:
            return
        if _SENSITIVE_PATH_RE.search(path):
            return
        if value is None or value == "":
            return
        if isinstance(value, (str, int, float, bool)):
            text = str(value)
            if len(text) > 500:
                text = text[:500]
            values.append({"path": path, "value": text})

    def walk(path: str, node: Any) -> None:
        if len(values) >= max_items:
            return
        if isinstance(node, dict):
            for key, item in node.items():
                child = f"{path}.{key}" if path else str(key)
                walk(child, item)
        elif isinstance(node, list):
            for index, item in enumerate(node[:8]):
                child = f"{path}.{index}" if path else str(index)
                walk(child, item)
        else:
            add(path, node)

    for source in allowed_sources:
        if source == "builtins":
            continue
        current: Any = context
        missing = False
        for part in [p for p in source.split(".") if p]:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                missing = True
                break
        if not missing:
            walk(source, current)
    return values


def _step_for_prompt(step: Step, context: dict[str, Any]) -> dict[str, Any]:
    def safe_render(value: Any) -> Any:
        try:
            return render_text(value, context) if value is not None else None
        except Exception:
            return str(value) if value is not None else None

    return {
        "kind": step.kind,
        "target": safe_render(step.target),
        "value": safe_render(step.value),
        "selector": safe_render(step.selector),
        "role": step.role,
        "group": step.group,
        "scope": step.scope,
        "exact": step.exact,
        "optional": step.optional,
        "line": step.line,
    }
