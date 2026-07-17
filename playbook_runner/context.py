"""Applicant data context: load profile JSON, expose builtins, resolve dotted paths."""
from __future__ import annotations

import copy
import json
import random
import re
import string
from collections.abc import Mapping
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
_POSITION_OVERRIDE_BUCKETS = ("position_overrides",)
_APP_ANSWER_EMPTY_DEFAULTS = {
    "authorized_to_work_us": None,
    "availability_to_start": "",
    "claims_veterans_preference": None,
    "current_organization": "",
    "current_title": "",
    "county": "",
    "cuhk_applied_class_of_appointment": "",
    "cuhk_applied_division": "",
    "cuhk_applied_position": "",
    "cuhk_chinese_name": "",
    "cuhk_degree": "",
    "cuhk_emergency_contact_address": "",
    "cuhk_emergency_contact_name": "",
    "cuhk_emergency_contact_number": "",
    "cuhk_emergency_contact_relationship": "",
    "cuhk_publication_authors": "",
    "cuhk_publication_description": "",
    "cuhk_publication_status": "",
    "cuhk_publication_title": "",
    "cuhk_publication_type": "",
    "cuhk_publication_venue": "",
    "cuhk_publication_work_type": "",
    "cuhk_research_interest": "",
    "cuhk_type_of_employment": "",
    "degree": "",
    "degree_date_earned": "",
    "degree_discipline": "",
    "degree_year_acquired": "",
    "degree_year_started": "",
    "desired_salary": "",
    "employee_referral": None,
    "employee_referrer_department": "",
    "employee_referrer_name": "",
    "employee_referrer_relationship": "",
    "ethnicity": "",
    "excluded_from_government_program": None,
    "excluded_from_government_program_details": "",
    "gender": "",
    "has_conflict_of_interest": None,
    "has_conflict_of_interest_details": "",
    "highest_education": "",
    "interfolio_degree": "",
    "interfolio_discipline": "",
    "interfolio_position_status": "",
    "interfolio_referral_source": "",
    "interfolio_state": "",
    "is_hispanic_or_latino": "",
    "is_veteran": None,
    "major": "",
    "license_cert": "",
    "nyulangone_employee_id": "",
    "nyulangone_highest_education": "",
    "nyulangone_degree": "",
    "nyulangone_school": "",
    "previously_employed_by_nyulangone": None,
    "previously_employed_by_nyulangone_details": "",
    "previously_employed_by_umn": "",
    "previously_employed_by_uthealth": None,
    "protected_veteran": "",
    "previous_employer_employee_id": "",
    "previously_employed_by_employer": None,
    "previously_employed_by_employer_details": "",
    "race_ethnicity": [],
    "referral_source": "",
    "related_to_employer_employee": None,
    "related_to_employer_employee_details": "",
    "requires_visa_sponsorship": None,
    "salary_period": "",
    "school": "",
    "search_source": "",
    "specific_referral_source": "",
    "ua_add_additional_positions": "0",
    "ua_certifications": "",
    "ua_citizenship_status": "",
    "ua_company_name": "",
    "ua_contact_employers": "",
    "ua_current_dept_and_title": "",
    "ua_degree_type": "",
    "ua_degree_year_started": "",
    "ua_education_status": "",
    "ua_education_type": "",
    "ua_employer_status": "",
    "ua_employment_status": "",
    "ua_end_month": "",
    "ua_end_year": "",
    "ua_family_member_details": "",
    "ua_has_family_employee": "",
    "ua_manager_name": "",
    "ua_reason_for_leaving": "",
    "ua_referral_source": "",
    "ua_responsibilities": "",
    "ua_start_day": "",
    "ua_start_month": "",
    "ua_start_year": "",
    "ua_title": "",
    "umn_degree": "",
    "umn_education_country": "",
    "umn_education_state": "",
    "utah_employee_id": "",
    "uthealth_region": "",
    "veteran_with_disability": None,
    "surviving_spouse_of_veteran": None,
    "orphan_of_veteran": None,
    "former_foster_child": None,
}


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

    return build_context(context, application_key=application_key)


def build_context(
    data: Mapping[str, Any], application_key: str | None = None
) -> dict[str, Any]:
    """Prepare an in-memory applicant mapping for validation or execution.

    This is the integration counterpart to :func:`load_context`: web backends
    can pass owner-scoped data directly instead of writing a temporary JSON
    profile. The caller's mapping is deep-copied because template refresh and
    generated runner values intentionally mutate the prepared context.
    """
    if not isinstance(data, Mapping):
        raise DataError("applicant data must be a mapping at the top level")

    context = copy.deepcopy(dict(data))
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
        # Kept as a compatibility key for existing playbooks. A product backend
        # may supply a stable target-specific +alias here; preserve that exact
        # address and never generate a fresh alias during a retry.
        account["generated_email"] = base_email


def _first_text(*values: Any) -> str:
    for value in values:
        text = "" if value is None else str(value).strip()
        if text:
            return text
    return ""


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
    generated: dict[str, Any] = copy.deepcopy(_APP_ANSWER_EMPTY_DEFAULTS)
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

    for bucket_name in _POSITION_OVERRIDE_BUCKETS:
        bucket = context.get(bucket_name)
        if isinstance(bucket, dict):
            _deep_merge_into(generated, _without_unset_values(bucket))

    _apply_position_relationships(generated)
    _deep_merge_missing(generated, _platform_app_answers(context, generated))

    return generated


def _canonical_app_answers(context: dict[str, Any]) -> dict[str, Any]:
    """Derive obvious application answers from the structured profile."""
    answers: dict[str, Any] = {}

    legal_name = resolve_path("person_name.legal_name", context, default={})
    if isinstance(legal_name, dict):
        _set_if_present(answers, "ua_title", legal_name.get("prefix"))
    _set_if_present(
        answers,
        "cuhk_chinese_name",
        resolve_path("person_name.chinese_name", context, default=None),
    )

    address = resolve_path("address_and_contact.primary_address", context, default={})
    if isinstance(address, dict):
        _set_if_present(answers, "county", address.get("county"))
        _set_if_present(answers, "uthealth_region", address.get("city"))
        _set_if_present(answers, "state_province", address.get("state_province"))

    school = resolve_path("education.schools.0", context, default={})
    if isinstance(school, dict):
        _set_if_present(answers, "school", school.get("institution"))
        _set_if_present(answers, "degree", school.get("degree"))
        _set_if_present(answers, "major", school.get("major"))
        _set_if_present(answers, "degree_discipline", school.get("major"))
        degree_date = _first_present(
            school.get("degree_awarded_date"),
            school.get("graduation_date"),
            school.get("end_date"),
        )
        _set_if_present(answers, "degree_date_earned", degree_date)
        _set_if_present(
            answers,
            "degree_year_acquired",
            _extract_year(degree_date),
        )
        _set_if_present(answers, "degree_year_started", _extract_year(school.get("start_date")))
        _set_if_present(answers, "education_country", school.get("country"))
        _set_if_present(answers, "education_state", school.get("state_province"))
        _set_if_present(answers, "education_currently_enrolled", school.get("currently_enrolled"))

    highest_level = resolve_path("education.highest_level", context, default=None)
    _set_if_present(answers, "highest_education", highest_level)

    current_job = resolve_path("work_history.0", context, default={})
    if isinstance(current_job, dict):
        _set_if_present(answers, "current_title", current_job.get("job_title"))
        _set_if_present(answers, "current_organization", current_job.get("company"))
        _set_if_present(answers, "current_employment_type", current_job.get("employment_type"))
        _set_if_present(answers, "current_employment_start_date", current_job.get("start_date"))
        _set_if_present(answers, "current_employment_start_day", current_job.get("start_day"))
        _set_if_present(answers, "current_employment_end_date", current_job.get("end_date"))
        _set_if_present(answers, "current_employment_active", current_job.get("currently_working_here"))
        _set_if_present(answers, "current_manager_name", current_job.get("supervisor_name"))
        _set_if_present(answers, "may_contact_current_employer", current_job.get("may_contact_supervisor"))
        _set_if_present(answers, "current_responsibilities", current_job.get("responsibilities"))
        _set_if_present(answers, "current_reason_for_leaving", current_job.get("reason_for_leaving"))

    professional = resolve_path("professional_profile", context, default={})
    if isinstance(professional, dict):
        _set_if_present(answers, "cuhk_research_interest", professional.get("research_interests"))
        _set_if_present(answers, "interfolio_position_status", professional.get("current_position_status"))
        _set_if_present(answers, "interfolio_discipline", professional.get("scholarly_discipline"))

    _set_if_present(
        answers,
        "interfolio_referral_source",
        resolve_path(
            "platform_preferences.interfolio.referral_source",
            context,
            default=None,
        ),
    )

    emergency = resolve_path("emergency_contact", context, default={})
    if isinstance(emergency, dict):
        _set_if_present(answers, "cuhk_emergency_contact_name", emergency.get("name"))
        _set_if_present(answers, "cuhk_emergency_contact_relationship", emergency.get("relationship"))
        _set_if_present(answers, "cuhk_emergency_contact_number", emergency.get("phone"))
        _set_if_present(answers, "cuhk_emergency_contact_address", emergency.get("address"))

    certification = resolve_path("education.certifications.0", context, default={})
    if isinstance(certification, dict):
        _set_if_present(answers, "primary_certification", certification.get("name"))

    publication = resolve_path("publications.0", context, default={})
    if isinstance(publication, dict):
        for source_key, answer_key in (
            ("type", "cuhk_publication_type"),
            ("work_type", "cuhk_publication_work_type"),
            ("title", "cuhk_publication_title"),
            ("authors", "cuhk_publication_authors"),
            ("venue", "cuhk_publication_venue"),
            ("status", "cuhk_publication_status"),
            ("description", "cuhk_publication_description"),
        ):
            _set_if_present(answers, answer_key, publication.get(source_key))

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
        _set_if_present(answers, "citizenship_country", citizenship.get("citizenship_country"))
        visa = citizenship.get("visa_status")
        if isinstance(visa, dict):
            _set_if_present(answers, "visa_status", visa.get("type"))
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
    _set_if_present(
        answers,
        "veteran_with_disability",
        resolve_path(
            "detailed_personal_info.veteran_status.veteran_with_disability",
            context,
            default=None,
        ),
    )
    _set_if_present(
        answers,
        "surviving_spouse_of_veteran",
        resolve_path(
            "detailed_personal_info.veteran_status.surviving_spouse",
            context,
            default=None,
        ),
    )
    _set_if_present(
        answers,
        "orphan_of_veteran",
        resolve_path(
            "detailed_personal_info.veteran_status.orphan_of_veteran",
            context,
            default=None,
        ),
    )
    _set_if_present(
        answers,
        "former_foster_child",
        resolve_path(
            "detailed_personal_info.former_foster_child",
            context,
            default=None,
        ),
    )

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


def _without_unset_values(mapping: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in mapping.items():
        if _is_unset(value):
            continue
        if isinstance(value, dict):
            nested = _without_unset_values(value)
            if nested:
                cleaned[key] = nested
        else:
            cleaned[key] = value
    return cleaned


def _is_unset(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _deep_merge_missing(base: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, value in incoming.items():
        current = base.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            _deep_merge_missing(current, value)
        elif key not in base or _is_unset(current):
            base[key] = value


def _apply_position_relationships(answers: dict[str, Any]) -> None:
    relationship = _simple_key(answers.get("employment_relationship"))
    if relationship in {"never", "current", "former"}:
        answers["previously_employed_by_employer"] = relationship in {
            "current",
            "former",
        }
        answers["currently_employed_by_employer"] = relationship == "current"


def _platform_app_answers(
    context: dict[str, Any], answers: dict[str, Any]
) -> dict[str, Any]:
    """Shape canonical facts for ATS-specific labels without re-asking users."""
    shaped: dict[str, Any] = {}

    from .equivalences import state_abbreviation

    _set_if_present(
        shaped,
        "interfolio_state",
        state_abbreviation(answers.get("state_province")),
    )

    degree = answers.get("degree")
    _set_if_present(shaped, "interfolio_degree", _degree_label(degree, "interfolio"))
    _set_if_present(shaped, "cuhk_degree", _degree_label(degree, "cuhk"))
    _set_if_present(shaped, "nyulangone_degree", _degree_label(degree, "nyulangone"))
    _set_if_present(shaped, "umn_degree", _degree_label(degree, "umn"))
    _set_if_present(shaped, "ua_degree_type", _degree_label(degree, "ua"))

    highest = answers.get("highest_education")
    _set_if_present(
        shaped,
        "nyulangone_highest_education",
        _nyulangone_highest_education(highest),
    )
    _set_if_present(shaped, "nyulangone_school", answers.get("school"))
    _set_if_present(shaped, "license_cert", answers.get("primary_certification"))

    _set_if_present(
        shaped,
        "cuhk_type_of_employment",
        _cuhk_employment_type(answers.get("current_employment_type")),
    )

    authorized = answers.get("authorized_to_work_us")
    if authorized is True:
        citizen = _is_united_states(answers.get("citizenship_country"))
        permanent = "permanentresident" in _simple_key(answers.get("visa_status"))
        shaped["authorized_to_work_us_label"] = (
            "Yes - I am a permanent resident or citizen"
            if citizen or permanent
            else "Yes - I am currently authorized to work in the United States"
        )
    elif authorized is False:
        shaped["authorized_to_work_us_label"] = (
            "No - I am not currently authorized to work in the United States"
        )

    relationship = _employment_relationship(answers)
    status_labels = {
        "never": "I have never been employed by The University of Alabama",
        "current": "I am currently employed by The University of Alabama",
        "former": "I was previously employed by The University of Alabama",
    }
    _set_if_present(shaped, "ua_employment_status", status_labels.get(relationship))
    _set_if_present(
        shaped,
        "ua_current_dept_and_title",
        answers.get("previously_employed_by_employer_details"),
    )
    _set_if_present(
        shaped,
        "previously_employed_by_nyulangone",
        relationship in {"current", "former"} if relationship else None,
    )
    _set_if_present(
        shaped,
        "previously_employed_by_nyulangone_details",
        answers.get("previously_employed_by_employer_details"),
    )
    _set_if_present(
        shaped,
        "nyulangone_employee_id",
        answers.get("previous_employer_employee_id"),
    )
    _set_if_present(
        shaped,
        "previously_employed_by_umn",
        _yes_no_label(relationship in {"current", "former"})
        if relationship
        else None,
    )
    _set_if_present(
        shaped,
        "previously_employed_by_uthealth",
        relationship in {"current", "former"} if relationship else None,
    )
    _set_if_present(
        shaped,
        "utah_employee_id",
        answers.get("previous_employer_employee_id"),
    )

    related = answers.get("related_to_employer_employee")
    _set_if_present(shaped, "ua_has_family_employee", _yes_no_label(related))
    _set_if_present(
        shaped,
        "ua_family_member_details",
        answers.get("related_to_employer_employee_details"),
    )
    _set_if_present(shaped, "related_to_uthealth_employee", related)

    _set_if_present(
        shaped,
        "ua_education_type",
        _ua_education_type(highest, answers.get("education_currently_enrolled")),
    )
    _set_if_present(
        shaped,
        "ua_education_status",
        "In Progress" if answers.get("education_currently_enrolled") is True else "Completed",
    )
    _set_if_present(shaped, "ua_degree_year_started", answers.get("degree_year_started"))

    active = answers.get("current_employment_active")
    _set_if_present(
        shaped,
        "ua_employer_status",
        "Currently employed" if active is not False else "Previous employer",
    )
    start_year, start_month, start_day = _date_parts(
        answers.get("current_employment_start_date")
    )
    _set_if_present(shaped, "ua_start_year", start_year)
    _set_if_present(shaped, "ua_start_month", start_month)
    _set_if_present(
        shaped,
        "ua_start_day",
        answers.get("current_employment_start_day") or start_day,
    )
    end_year, end_month, _end_day = _date_parts(
        answers.get("current_employment_end_date")
    )
    _set_if_present(shaped, "ua_end_year", end_year)
    _set_if_present(shaped, "ua_end_month", end_month)
    _set_if_present(shaped, "ua_company_name", answers.get("current_organization"))
    _set_if_present(shaped, "ua_manager_name", answers.get("current_manager_name"))
    _set_if_present(shaped, "ua_responsibilities", answers.get("current_responsibilities"))
    _set_if_present(shaped, "ua_reason_for_leaving", answers.get("current_reason_for_leaving"))
    may_contact = answers.get("may_contact_current_employer")
    if may_contact is not None:
        shaped["ua_contact_employers"] = "yes" if may_contact else "no"
    shaped["ua_add_additional_positions"] = "0"
    _set_if_present(shaped, "ua_certifications", answers.get("primary_certification"))
    _set_if_present(
        shaped,
        "ua_citizenship_status",
        _ua_citizenship_status(
            answers.get("citizenship_country"), answers.get("visa_status")
        ),
    )
    _set_if_present(
        shaped,
        "ua_referral_source",
        _ua_referral_source(answers.get("referral_source")),
    )

    _set_if_present(shaped, "umn_education_country", answers.get("education_country"))
    _set_if_present(shaped, "umn_education_state", answers.get("education_state"))
    _set_if_present(shaped, "search_source", answers.get("referral_source"))

    veteran = answers.get("is_veteran")
    if veteran is True:
        shaped["protected_veteran"] = "Other Protected Veteran"
    elif veteran is False:
        shaped["protected_veteran"] = "Not an Other Protected Veteran"

    races = answers.get("race_ethnicity")
    if isinstance(races, list):
        _set_if_present(shaped, "ethnicity", races[0] if races else None)
    else:
        _set_if_present(shaped, "ethnicity", races)

    return shaped


def _degree_label(value: Any, platform: str) -> str | None:
    degree = _simple_key(value)
    groups = {
        "doctorate": {"phd", "philosophydoctor", "doctorofphilosophy", "doctorate"},
        "masters": {"ma", "ms", "masters", "masterofarts", "masterofscience"},
        "bachelors": {"ba", "bs", "bachelors", "bachelorofarts", "bachelorofscience"},
    }
    group = next((name for name, values in groups.items() if degree in values), None)
    labels = {
        "interfolio": {
            "doctorate": "Ph.D. - Doctor of Philosophy",
            "masters": "M.S. - Master of Science",
            "bachelors": "B.S. - Bachelor of Science",
        },
        "cuhk": {
            "doctorate": "Doctor of Philosophy (Ph.D.)",
            "masters": "Master's Degree",
            "bachelors": "Bachelor's Degree",
        },
        "nyulangone": {
            "doctorate": "Doctor Of Philosophy - Ph D",
            "masters": "Master Of Science - M S",
            "bachelors": "Bachelor Of Science - B S",
        },
        "umn": {
            "doctorate": "Doctor of Philosophy",
            "masters": "Master of Science",
            "bachelors": "Bachelor of Science",
        },
        "ua": {
            "doctorate": "PhD",
            "masters": "Masters",
            "bachelors": "Bachelors",
        },
    }
    if group:
        return labels.get(platform, {}).get(group)
    return str(value).strip() if value not in (None, "") else None


def _nyulangone_highest_education(value: Any) -> str | None:
    key = _simple_key(value)
    if "doctor" in key:
        return "Doctoral Degree"
    if "master" in key:
        return "Post Graduate Degree"
    if "bachelor" in key:
        return "Bachelor's Degree"
    return str(value).strip() if value not in (None, "") else None


def _cuhk_employment_type(value: Any) -> str | None:
    key = _simple_key(value)
    if key in {"fulltime", "postdoc", "contract"}:
        return "Full-Time"
    if key == "parttime":
        return "Part-Time"
    if key in {"temporary", "internship"}:
        return "Temporary"
    return None


def _employment_relationship(answers: dict[str, Any]) -> str | None:
    explicit = _simple_key(answers.get("employment_relationship"))
    if explicit in {"never", "current", "former"}:
        return explicit
    if answers.get("currently_employed_by_employer") is True:
        return "current"
    if answers.get("previously_employed_by_employer") is True:
        return "former"
    if answers.get("previously_employed_by_employer") is False:
        return "never"
    return None


def _yes_no_label(value: Any) -> str | None:
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return None


def _ua_education_type(highest: Any, currently_enrolled: Any) -> str | None:
    key = _simple_key(highest)
    if any(word in key for word in ("doctor", "master", "bachelor", "associate")):
        return "College / University" if currently_enrolled is True else "College / University Graduate"
    if "highschool" in key:
        return "High School"
    return "Other" if key else None


def _date_parts(value: Any) -> tuple[str | None, str | None, str | None]:
    match = re.search(r"\b(19|20)(\d{2})-(0[1-9]|1[0-2])(?:-([0-2]\d|3[01]))?\b", str(value or ""))
    if not match:
        return None, None, None
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return match.group(1) + match.group(2), months[int(match.group(3)) - 1], match.group(4)


def _ua_citizenship_status(country: Any, visa_status: Any) -> str | None:
    if _is_united_states(country) or _simple_key(visa_status) == "uscitizen":
        return "citizen"
    if "permanentresident" in _simple_key(visa_status):
        return "permanent_resident"
    if country or visa_status:
        return "non_resident"
    return None


def _ua_referral_source(value: Any) -> str | None:
    mapping = {
        "employerwebsite": "UA Employment Website (jobs.ua.edu)",
        "jobboard": "Web-based job posting board",
        "linkedin": "LinkedIn",
        "indeed": "Web-based job posting board",
        "higheredjobs": "Web-based job posting board",
        "herc": "HERC",
        "chronicle": "Professional Journal",
        "professionalorganization": "Professional Journal",
        "employeereferral": "Referred by UA Employee",
        "recruiter": "Referred by Search Firm",
        "socialmedia": "Other Social Media",
        "other": "Other Referral/Listserv/Email Notification",
    }
    key = _simple_key(value)
    return mapping.get(key, str(value).strip() if value not in (None, "") else None)


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
