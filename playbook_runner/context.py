"""Applicant data context: load profile JSON, expose builtins, resolve dotted paths."""
from __future__ import annotations

import json
import random
import re
import string
from datetime import date, datetime
from pathlib import Path
from typing import Any


class DataError(Exception):
    """Raised when applicant data cannot be loaded or a path cannot be resolved."""


_MISSING = object()

_DECLINE = "I do not wish to provide this information"
_DEFAULT_ANSWER_BUCKETS = (
    "applicant_defaults",
    "application_defaults",
    "answer_defaults",
    "default_answers",
)
_APPLICATION_EXCEPTION_BUCKETS = (
    "application_exceptions",
    "employer_exceptions",
    "site_exceptions",
)


def _make_builtins() -> dict[str, str]:
    """Values supplied by the runner, refreshed on every run.

    ``unique`` is a short run-stamp (date + time + random tail) suitable for
    making account usernames / emails collision-free across re-runs.
    """
    now = datetime.now()
    tail = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    short_tail = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return {
        "today": now.strftime("%m/%d/%Y"),
        "today_iso": date.today().isoformat(),
        "year": now.strftime("%Y"),
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "unique": now.strftime("%Y%m%d%H%M%S") + tail,
        "run_id": now.strftime("%Y%m%d%H%M%S") + tail,
        "short_unique": short_tail,
    }


def load_context(data_paths: list[str], application_key: str | None = None) -> dict[str, Any]:
    """Merge one or more JSON data files, attach builtins, and refresh templates.

    Later files override earlier ones with a recursive dictionary merge. Lists
    and scalar values still replace the earlier value. The reserved ``builtins``
    namespace is always added last and cannot be shadowed.

    ``application_key`` is the stable playbook/employer key. It is used to build
    ``app_answers`` from canonical profile facts, reusable defaults, and
    application-specific exceptions.

    Any ``{{ ... }}`` token *inside the data* is expanded at load time so a
    profile can self-refresh — e.g. ``"user_name": "jdoe_{{ builtins.unique }}"``
    yields a fresh, collision-free username on every run.
    """
    context: dict[str, Any] = {}
    for raw in data_paths:
        path = Path(raw)
        if not path.exists():
            raise DataError(f"data file not found: {path}")
        try:
            loaded = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise DataError(f"invalid JSON in {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise DataError(f"data file {path} must contain a JSON object at the top level")
        _deep_merge_into(context, loaded)

    context["builtins"] = _make_builtins()
    _set_runner_metadata(context, application_key)
    _refresh_in_place(context)
    _set_derived_builtins(context)
    _set_generated_account_values(context)
    context["app_answers"] = _build_app_answers(context, application_key)
    return context


def _set_runner_metadata(context: dict[str, Any], application_key: str | None) -> None:
    runner = context.get("runner")
    if not isinstance(runner, dict):
        runner = {}
    runner["application_key"] = application_key or ""
    context["runner"] = runner


def _set_derived_builtins(context: dict[str, Any]) -> None:
    builtins = context.get("builtins")
    if not isinstance(builtins, dict):
        return

    name = resolve_path("person_name.legal_name", context, default={})
    if not isinstance(name, dict):
        return

    initials = "".join(
        _first_initial(name.get(part))
        for part in ("first", "middle", "last")
    )
    if initials:
        builtins["legal_initials"] = initials


def _first_initial(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return text[:1].upper() if text else ""


def _set_generated_account_values(context: dict[str, Any]) -> None:
    account = context.get("account")
    if not isinstance(account, dict):
        account = {}
        context["account"] = account

    base_email = _first_text(
        resolve_path("emails.preferred_contact_email", context, default=""),
        resolve_path("emails.institution_email", context, default=""),
        resolve_path("emails.personal_email", context, default=""),
        resolve_path("account.email", context, default=""),
    )
    if base_email and "@" in base_email:
        account["generated_email"] = _plus_email_alias(
            base_email,
            "ut" + str(context["builtins"]["short_unique"]),
        )


def _first_text(*values: Any) -> str:
    for value in values:
        text = "" if value is None else str(value).strip()
        if text:
            return text
    return ""


def _plus_email_alias(email: str, tag: str) -> str:
    local, domain = email.rsplit("@", 1)
    base_local = local.split("+", 1)[0]
    clean_tag = re.sub(r"[^A-Za-z0-9]", "", tag)
    return f"{base_local}+{clean_tag}@{domain}"


def _deep_merge_into(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``incoming`` into ``base`` and return ``base``."""
    for key, value in incoming.items():
        current = base.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            _deep_merge_into(current, value)
        else:
            base[key] = value
    return base


def _build_app_answers(context: dict[str, Any], application_key: str | None) -> dict[str, Any]:
    """Generate reusable application answers for playbooks.

    Resolution order, from weakest to strongest:

    1. canonical facts derived from the structured applicant profile;
    2. legacy ``answers`` values, so existing profiles automatically work;
    3. reusable default buckets such as ``application_defaults``;
    4. current application exceptions, keyed by ``employer_key``/``application_key``.
    """
    generated: dict[str, Any] = {}
    _deep_merge_into(generated, _canonical_app_answers(context))

    legacy = context.get("answers")
    if isinstance(legacy, dict):
        _deep_merge_into(generated, legacy)

    for bucket_name in _DEFAULT_ANSWER_BUCKETS:
        bucket = context.get(bucket_name)
        if isinstance(bucket, dict):
            _deep_merge_into(generated, _without_null_values(bucket))

    if application_key:
        for bucket_name in _APPLICATION_EXCEPTION_BUCKETS:
            bucket = context.get(bucket_name)
            selected = _lookup_keyed_mapping(bucket, application_key)
            if isinstance(selected, dict):
                _deep_merge_into(generated, _without_null_values(selected))

    return generated


def _canonical_app_answers(context: dict[str, Any]) -> dict[str, Any]:
    """Derive obvious application answers from the structured profile."""
    answers: dict[str, Any] = {}

    school = resolve_path("education.schools.0", context, default={})
    if isinstance(school, dict):
        _set_if_present(answers, "school", school.get("institution"))
        _set_if_present(answers, "degree", school.get("degree"))
        _set_if_present(answers, "major", school.get("major"))
        _set_if_present(answers, "degree_discipline", school.get("major"))
        _set_if_present(answers, "degree_date_earned", school.get("graduation_date"))
        _set_if_present(
            answers,
            "degree_year_acquired",
            _extract_year(school.get("graduation_date")),
        )
        _set_if_present(answers, "degree_year_started", _extract_year(school.get("start_date")))

    highest_level = resolve_path("education.highest_level", context, default=None)
    _set_if_present(answers, "highest_education", highest_level)

    current_job = resolve_path("work_history.0", context, default={})
    if isinstance(current_job, dict):
        _set_if_present(answers, "current_title", current_job.get("job_title"))
        _set_if_present(answers, "current_organization", current_job.get("company"))

    salary = resolve_path("employment_basics.salary_expectation", context, default={})
    if isinstance(salary, dict):
        _set_if_present(
            answers,
            "desired_salary",
            _first_present(
                salary.get("amount_target"),
                salary.get("amount_min"),
                salary.get("amount_max"),
            ),
        )
        _set_if_present(answers, "salary_period", salary.get("period"))

    _set_if_present(
        answers,
        "availability_to_start",
        resolve_path("employment_basics.availability_to_start", context, default=None),
    )
    _set_if_present(
        answers,
        "willing_to_relocate",
        resolve_path("employment_basics.willing_to_relocate", context, default=None),
    )
    _set_if_present(
        answers,
        "willing_to_travel_percent",
        resolve_path("employment_basics.willing_to_travel_percent", context, default=None),
    )

    citizenship = resolve_path(
        "detailed_personal_info.birth_and_citizenship", context, default={}
    )
    if isinstance(citizenship, dict):
        if _is_united_states(citizenship.get("work_authorization_country")):
            answers["authorized_to_work_us"] = True
        _set_if_present(
            answers,
            "requires_visa_sponsorship",
            citizenship.get("requires_visa_sponsorship"),
        )

    ethnicity = resolve_path("detailed_personal_info.ethnicity", context, default={})
    if isinstance(ethnicity, dict):
        _set_if_present(
            answers,
            "is_hispanic_or_latino",
            _ethnicity_to_hispanic_answer(
                ethnicity.get("value"),
                ethnicity.get("prefer_not_to_say"),
            ),
        )

    veteran_status = resolve_path(
        "detailed_personal_info.veteran_status.value",
        context,
        default=None,
    )
    _set_if_present(answers, "is_veteran", _yes_no_decline_to_bool(veteran_status))

    disability_status = resolve_path(
        "detailed_personal_info.disability_status.value", context, default=None
    )
    _set_if_present(answers, "has_disability", _yes_no_decline_to_bool(disability_status))

    gender = resolve_path("identity_and_status.gender.value", context, default=None)
    _set_if_present(answers, "gender", _gender_for_constrained_forms(gender))

    source = resolve_path("referral_and_relationships.discovery_source", context, default=None)
    _set_if_present(answers, "referral_source", source)
    _set_if_present(
        answers,
        "specific_referral_source",
        resolve_path("referral_and_relationships.discovery_source_details", context, default=None),
    )
    _set_if_present(
        answers,
        "employee_referral",
        resolve_path("referral_and_relationships.referred_by_employee", context, default=None),
    )
    _set_if_present(
        answers,
        "employee_referrer_name",
        resolve_path(
            "referral_and_relationships.referral_details.employee_name",
            context,
            default=None,
        ),
    )
    _set_if_present(
        answers,
        "employee_referrer_relationship",
        resolve_path(
            "referral_and_relationships.referral_details.relationship",
            context,
            default=None,
        ),
    )
    nepotism = resolve_path("referral_and_relationships.nepotism_disclosures", context, default=[])
    if isinstance(nepotism, list) and any(
        isinstance(item, dict) and item.get("works_here") is True for item in nepotism
    ):
        answers["related_to_employer_employee"] = True

    return answers


def _lookup_keyed_mapping(mapping: Any, key: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    if key in mapping:
        return mapping[key]

    normalized_key = _simple_key(key)
    for candidate_key, value in mapping.items():
        if _simple_key(candidate_key) == normalized_key:
            return value
    return None


def _without_null_values(mapping: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in mapping.items():
        if value is None:
            continue
        if isinstance(value, dict):
            cleaned[key] = _without_null_values(value)
        else:
            cleaned[key] = value
    return cleaned


def _set_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None or value == "":
        return
    if isinstance(value, bool):
        target[key] = value
    else:
        target[key] = str(value) if isinstance(value, (int, float)) else value


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _extract_year(value: Any) -> str | None:
    if value is None:
        return None
    match = re.search(r"\b(19|20)\d{2}\b", str(value))
    return match.group(0) if match else None


def _simple_key(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def _is_united_states(value: Any) -> bool:
    return _simple_key(value) in {"us", "usa", "unitedstates", "unitedstatesofamerica"}


def _yes_no_decline_to_bool(value: Any) -> bool | None:
    normalized = _simple_key(value)
    if normalized in {"yes", "y", "true"}:
        return True
    if normalized in {"no", "n", "false"}:
        return False
    return None


def _ethnicity_to_hispanic_answer(value: Any, prefer_not_to_say: Any) -> str | None:
    if prefer_not_to_say is True:
        return _DECLINE
    normalized = _simple_key(value)
    if not normalized:
        return None
    if (
        "nothispanic" in normalized
        or "nonhispanic" in normalized
        or "notlatino" in normalized
        or "nonlatino" in normalized
    ):
        return "No"
    if "hispanic" in normalized or "latino" in normalized or "latina" in normalized:
        return "Yes"
    if normalized in {
        "decline",
        "prefernottoanswer",
        "prefernottosay",
        "idontwishtoprovide",
        "idonotwishtoprovidethisinformation",
        "donotwishtoprovide",
        "donotwishtoprovidethisinformation",
    }:
        return _DECLINE
    return None


def _gender_for_constrained_forms(value: Any) -> str | None:
    normalized = _simple_key(value)
    if normalized == "male":
        return "Male"
    if normalized == "female":
        return "Female"
    if normalized in {
        "decline",
        "prefernottoanswer",
        "prefernottosay",
        "idontwishtoprovide",
        "idonotwishtoprovidethisinformation",
        "donotwishtoprovide",
        "donotwishtoprovidethisinformation",
    }:
        return _DECLINE
    return None


def _refresh_in_place(context: dict[str, Any]) -> None:
    """Expand ``{{ ... }}`` tokens found in the data against the context.

    Done as a single pass over everything except the ``builtins`` namespace.
    Imported locally to avoid a circular import with :mod:`template`.
    """
    from .template import render_text

    def expand(node: Any) -> Any:
        if isinstance(node, str):
            return render_text(node, context) if "{{" in node else node
        if isinstance(node, dict):
            return {k: expand(v) for k, v in node.items()}
        if isinstance(node, list):
            return [expand(v) for v in node]
        return node

    for key in list(context.keys()):
        if key == "builtins":
            continue
        context[key] = expand(context[key])


def resolve_path(path: str, context: dict[str, Any], default: Any = _MISSING) -> Any:
    """Resolve a dotted path like ``a.b.0.c`` against the context.

    List indices are written as integers in the path (``schools.0.degree``).
    Returns ``default`` if provided and the path is missing; otherwise raises.
    """
    current: Any = context
    parts = [p for p in path.strip().split(".") if p != ""]
    if not parts:
        raise DataError("empty data path")

    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                return _missing(path, default)
            current = current[part]
        elif isinstance(current, (list, tuple)):
            if not part.lstrip("-").isdigit():
                return _missing(path, default)
            idx = int(part)
            if idx >= len(current) or idx < -len(current):
                return _missing(path, default)
            current = current[idx]
        else:
            return _missing(path, default)
    return current


def _missing(path: str, default: Any) -> Any:
    if default is _MISSING:
        raise DataError(f"data path not found: '{path}'")
    return default


def path_exists(path: str, context: dict[str, Any]) -> bool:
    sentinel = object()
    return resolve_path(path, context, default=sentinel) is not sentinel
