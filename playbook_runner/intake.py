"""Canonical applicant intake contract shared by products and the runner.

The browser playbooks consume nested applicant data, but a product needs more
than dotted paths to build a safe form.  This module supplies the labels,
control types, canonical option values, per-playbook requirements, and
application-only questions that sit in front of those paths.

The contract is deliberately deterministic.  Products may render these fields
in their own design system, but they must store the declared values and may not
invent alternate enum vocabularies.  Site-specific answers are scoped to one
playbook; reusable facts remain in the private applicant profile.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .context import resolve_path
from .parser import Playbook, load_playbook


@dataclass(frozen=True)
class IntakeOption:
    value: str
    label: str

    def as_dict(self) -> dict[str, str]:
        return {"value": self.value, "label": self.label}


@dataclass(frozen=True)
class IntakeField:
    path: str
    label: str
    section: str
    kind: str = "text"
    required: bool = False
    options: tuple[IntakeOption, ...] = ()
    help_text: str = ""
    min_value: int | None = None
    max_value: int | None = None
    required_when_path: str | None = None
    required_when_values: tuple[Any, ...] = ()
    visible_when_path: str | None = None
    visible_when_values: tuple[Any, ...] = ()
    storage: str = "profile"

    @property
    def form_name(self) -> str:
        return "field__" + self.path.replace(".", "__")

    @property
    def is_runtime_only(self) -> bool:
        return self.storage == "runtime_secret"

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "label": self.label,
            "section": self.section,
            "kind": self.kind,
            "required": self.required,
            "options": [option.as_dict() for option in self.options],
            "help_text": self.help_text,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "required_when_path": self.required_when_path,
            "required_when_values": list(self.required_when_values),
            "visible_when_path": self.visible_when_path,
            "visible_when_values": list(self.visible_when_values),
            "storage": self.storage,
        }


@dataclass(frozen=True)
class PlaybookIntake:
    contract_key: str
    application_key: str
    profile_fields: tuple[IntakeField, ...]
    application_fields: tuple[IntakeField, ...]
    required_profile_paths: tuple[str, ...]
    required_document_paths: tuple[str, ...]
    blockers: tuple[str, ...] = ()

    @property
    def storable_application_fields(self) -> tuple[IntakeField, ...]:
        return tuple(field for field in self.application_fields if not field.is_runtime_only)


@dataclass(frozen=True)
class IntakeIssue:
    code: str
    path: str
    label: str
    section: str
    message: str


_SECTION_LABELS = {
    "identity": "Identity",
    "contact": "Contact and address",
    "authorization": "Work authorization",
    "education": "Education",
    "employment": "Current employment",
    "professional": "Professional profile",
    "qualifications": "Qualifications and publications",
    "emergency": "Emergency contact",
    "defaults": "Application defaults",
    "demographics": "Voluntary demographics",
    "references": "References",
    "position": "Position-specific questions",
    "position_referral": "Position referral",
    "position_relationships": "Institution relationships",
    "history": "Employer history",
    "publication": "Publication",
    "screening": "Screening questions",
    "platform": "Application platform",
    "platform_defaults": "Application platforms",
}


def section_label(section: str) -> str:
    return _SECTION_LABELS.get(section, section.replace("_", " ").title())


def _options(*values: str | tuple[str, str]) -> tuple[IntakeOption, ...]:
    rows = []
    for value in values:
        if isinstance(value, tuple):
            rows.append(IntakeOption(value=value[0], label=value[1]))
        else:
            rows.append(IntakeOption(value=value, label=value))
    return tuple(rows)


def _country_options() -> tuple[IntakeOption, ...]:
    path = Path(__file__).resolve().parent / "data" / "country_options.txt"
    if not path.exists():
        return _options(
            "United States", "Canada", "Mexico", "United Kingdom", "India",
            "China", "Hong Kong", "Australia", "New Zealand",
        )

    replacements = {
        "United States of America": "United States",
        "United Kingdom (Great Britain)": "United Kingdom",
        "Korea, Republic of": "South Korea",
        "Korea, Democratic People's Republic of": "North Korea",
        "Viet Nam": "Vietnam",
        "Czech Republic": "Czechia",
        "Bahama": "Bahamas",
        "Macedonia": "North Macedonia",
    }
    values: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        label = line.split(" - ", 1)[-1].strip()
        if not label or "no longer exists" in label.lower():
            continue
        label = replacements.get(label, label)
        if label not in values:
            values.append(label)
    return tuple(IntakeOption(value=value, label=value) for value in values)


def _state_options() -> tuple[IntakeOption, ...]:
    # These are the canonical names accepted by the runner's state equivalence
    # group.  Full names are stored; university forms may expose abbreviations.
    from .equivalences import (  # local import keeps module initialization light
        _CANADIAN_PROVINCES_RAW,
        _MILITARY_STATE_CODES_RAW,
        _US_STATES_RAW,
        _US_TERRITORIES_RAW,
    )

    names = sorted(
        {
            *_US_STATES_RAW.values(),
            *_US_TERRITORIES_RAW.values(),
            *_MILITARY_STATE_CODES_RAW.values(),
            *_CANADIAN_PROVINCES_RAW.values(),
        }
    )
    names.append("Not Applicable (International)")
    return tuple(IntakeOption(value=name, label=name) for name in names)


COUNTRY_OPTIONS = _country_options()
STATE_OPTIONS = _state_options()

PREFIX_OPTIONS = _options("Dr", "Mr", "Ms", "Mrs", "Mx", "Prof")
SUFFIX_OPTIONS = _options("Jr.", "Sr.", "II", "III", "IV")
PRONOUN_OPTIONS = _options(
    ("he/him", "He/him"),
    ("she/her", "She/her"),
    ("they/them", "They/them"),
    ("ze/hir", "Ze/hir"),
    ("ze/zir", "Ze/zir"),
    ("decline", "Prefer not to say"),
)
GENDER_OPTIONS = _options(
    "Male",
    "Female",
    "Non-Binary",
    "I do not wish to provide this information",
)
HISPANIC_OPTIONS = _options(
    "Hispanic or Latino",
    "Not Hispanic or Latino",
    "I do not wish to provide this information",
)
RACE_OPTIONS = _options(
    "American Indian or Alaska Native",
    "Asian",
    "Black or African American",
    "Native Hawaiian or Other Pacific Islander",
    "White",
    "Two or More Races",
    "I do not wish to provide this information",
)
DECLINABLE_STATUS_OPTIONS = _options(
    ("yes", "Yes"),
    ("no", "No"),
    ("decline", "I do not wish to answer"),
)
DEGREE_LEVEL_OPTIONS = _options(
    "High School",
    "Associate",
    "Bachelors",
    "Masters",
    "Doctorate",
    "Professional Degree",
    "Other",
)
DEGREE_OPTIONS = _options(
    "High School",
    "Associate",
    "Bachelor of Arts",
    "Bachelor of Science",
    "Master of Arts",
    "Master of Science",
    "MBA",
    "Ph.D.",
    "Ed.D.",
    "J.D.",
    "M.D.",
    "Other",
)
VISA_OPTIONS = _options(
    "US Citizen",
    "Permanent Resident",
    "Noncitizen National",
    "Alien Authorized to Work",
    "F-1 OPT",
    "STEM OPT",
    "H-1B",
    "TN",
    "J-1",
    "Other",
)
REFERRAL_OPTIONS = _options(
    "Employer Website",
    "Job Board",
    "LinkedIn",
    "Indeed",
    "HigherEdJobs",
    "HERC",
    "Chronicle",
    "Professional Organization",
    "Employee Referral",
    "Recruiter",
    "Social Media",
    "Other",
)
POSITION_STATUS_OPTIONS = _options(
    "Tenured",
    "Tenure-track",
    "Full-time, non-tenure track",
    "Part-time, non-tenure track",
    "Post-Doc",
    "Graduate Student",
    "Medical Student",
    "Undergraduate/Pre-med",
    "Alternative Academic Career",
    "Other",
)
SCHOLARLY_DISCIPLINE_OPTIONS = _options(
    "Fine & Performing Arts",
    "Humanities",
    "Social Sciences",
    "STEM (Science, Technology, Engineering, Math)",
    "Business",
    "Law",
    "Medicine / Health Professions",
    "Government",
    "Education",
    "Other",
)
INTERFOLIO_REFERRAL_OPTIONS = _options(
    "A Professional or Academic Organization",
    "My Advisor, Professor, or Mentor",
    "My Colleague, Peer, or Friend",
    "My Institution",
    "Social Media",
    "An Article, Blog, or Online Forum",
    "Podcast",
    "Other",
)
EMPLOYMENT_RELATIONSHIP_OPTIONS = _options(
    ("never", "Never employed by this institution"),
    ("current", "Currently employed by this institution"),
    ("former", "Previously employed by this institution"),
)


def _field(
    path: str,
    label: str,
    section: str,
    kind: str = "text",
    *,
    options: tuple[IntakeOption, ...] = (),
    help_text: str = "",
    min_value: int | None = None,
    max_value: int | None = None,
    required_when_path: str | None = None,
    required_when_values: tuple[Any, ...] = (),
    visible_when_path: str | None = None,
    visible_when_values: tuple[Any, ...] = (),
) -> IntakeField:
    return IntakeField(
        path=path,
        label=label,
        section=section,
        kind=kind,
        options=options,
        help_text=help_text,
        min_value=min_value,
        max_value=max_value,
        required_when_path=required_when_path,
        required_when_values=required_when_values,
        visible_when_path=visible_when_path,
        visible_when_values=visible_when_values,
    )


_PROFILE_FIELD_ROWS = (
    _field("person_name.legal_name.prefix", "Title or prefix", "identity", "choice", options=PREFIX_OPTIONS),
    _field("person_name.legal_name.first", "Legal first name", "identity"),
    _field("person_name.legal_name.middle", "Legal middle name", "identity"),
    _field("person_name.legal_name.last", "Legal last name", "identity"),
    _field("person_name.legal_name.suffix", "Suffix", "identity", "choice", options=SUFFIX_OPTIONS),
    _field("person_name.chinese_name", "Chinese name", "identity"),
    _field("person_name.preferred_name.preferred_first", "Preferred first name", "identity"),
    _field("identity_and_status.pronouns.set", "Pronouns", "identity", "choice", options=PRONOUN_OPTIONS),
    _field("detailed_personal_info.date_of_birth", "Date of birth", "identity", "date"),

    _field("address_and_contact.primary_address.line_1", "Address line 1", "contact"),
    _field("address_and_contact.primary_address.line_2", "Address line 2", "contact"),
    _field("address_and_contact.primary_address.city", "City", "contact"),
    _field("address_and_contact.primary_address.county", "County", "contact"),
    _field("address_and_contact.primary_address.state_province", "State or province", "contact", "choice", options=STATE_OPTIONS),
    _field("address_and_contact.primary_address.postal_code", "Postal code", "contact"),
    _field("address_and_contact.primary_address.country", "Country", "contact", "choice", options=COUNTRY_OPTIONS),
    _field("address_and_contact.phone_numbers.mobile", "Mobile phone", "contact", "tel"),
    _field("address_and_contact.phone_numbers.home", "Home phone", "contact", "tel"),
    _field("address_and_contact.phone_numbers.work", "Work phone", "contact", "tel"),

    _field("emergency_contact.name", "Emergency contact name", "emergency"),
    _field("emergency_contact.relationship", "Emergency contact relationship", "emergency"),
    _field("emergency_contact.phone", "Emergency contact phone", "emergency", "tel"),
    _field("emergency_contact.address", "Emergency contact address", "emergency", "textarea"),

    _field("application_defaults.authorized_to_work_us", "Currently authorized to work in the United States", "authorization", "boolean"),
    _field("detailed_personal_info.birth_and_citizenship.requires_visa_sponsorship", "Now or in the future require visa sponsorship", "authorization", "boolean"),
    _field("detailed_personal_info.birth_and_citizenship.citizenship_country", "Country of citizenship", "authorization", "choice", options=COUNTRY_OPTIONS),
    _field("detailed_personal_info.birth_and_citizenship.visa_status.type", "Current citizenship or work status", "authorization", "choice", options=VISA_OPTIONS),
    _field("detailed_personal_info.birth_and_citizenship.visa_status.expiration_date", "Status expiration date", "authorization", "date"),

    _field("education.highest_level", "Highest education level", "education", "choice", options=DEGREE_LEVEL_OPTIONS),
    _field("education.schools.0.institution", "Institution", "education"),
    _field("education.schools.0.degree", "Degree", "education", "choice", options=DEGREE_OPTIONS),
    _field("education.schools.0.major", "Major or field of study", "education"),
    _field("education.schools.0.minor", "Minor", "education"),
    _field("education.schools.0.city", "Institution city", "education"),
    _field("education.schools.0.state_province", "Institution state or province", "education", "choice", options=STATE_OPTIONS),
    _field("education.schools.0.country", "Institution country", "education", "choice", options=COUNTRY_OPTIONS),
    _field("education.schools.0.start_date", "Education start month", "education", "month"),
    _field("education.schools.0.graduation_date", "Graduation or expected month", "education", "month"),
    _field("education.schools.0.degree_awarded_date", "Exact degree award date", "education", "date"),
    _field("education.schools.0.currently_enrolled", "Currently enrolled", "education", "boolean"),

    _field("work_history.0.company", "Current or most recent employer", "employment"),
    _field("work_history.0.job_title", "Current or most recent job title", "employment"),
    _field("work_history.0.employment_type", "Employment type", "employment", "choice", options=_options("full_time", "part_time", "temporary", "contract", "internship", "postdoc", "other")),
    _field("work_history.0.start_date", "Employment start month", "employment", "month"),
    _field("work_history.0.start_day", "Employment start day", "employment", "number", min_value=1, max_value=31),
    _field("work_history.0.end_date", "Employment end month", "employment", "month"),
    _field("work_history.0.currently_working_here", "Currently working here", "employment", "boolean"),
    _field("work_history.0.city", "Employer city", "employment"),
    _field("work_history.0.state_province", "Employer state or province", "employment", "choice", options=STATE_OPTIONS),
    _field("work_history.0.country", "Employer country", "employment", "choice", options=COUNTRY_OPTIONS),
    _field("work_history.0.supervisor_name", "Supervisor name", "employment"),
    _field("work_history.0.may_contact_supervisor", "May this employer be contacted", "employment", "boolean"),
    _field("work_history.0.responsibilities", "Responsibilities", "employment", "textarea"),
    _field("work_history.0.reason_for_leaving", "Reason for leaving", "employment", "textarea"),

    _field("professional_profile.research_interests", "Research interests", "professional", "textarea"),
    _field("professional_profile.current_position_status", "Current academic position status", "professional", "choice", options=POSITION_STATUS_OPTIONS),
    _field("professional_profile.scholarly_discipline", "Scholarly discipline", "professional", "choice", options=SCHOLARLY_DISCIPLINE_OPTIONS),
    _field("education.certifications.0.name", "Primary license or certification", "qualifications"),
    _field("education.certifications.0.issuer", "Certification issuer", "qualifications"),
    _field("education.certifications.0.issue_date", "Certification issue month", "qualifications", "month"),
    _field("education.certifications.0.expiration_date", "Certification expiration month", "qualifications", "month"),
    _field("publications.0.type", "Publication type", "qualifications", "choice", options=_options("Journal Article", "Book", "Book Chapter", "Conference Paper", "Other")),
    _field("publications.0.work_type", "Publication work type", "qualifications"),
    _field("publications.0.title", "Publication title", "qualifications"),
    _field("publications.0.authors", "Publication authors or creators", "qualifications"),
    _field("publications.0.venue", "Journal, publisher, or conference", "qualifications"),
    _field("publications.0.status", "Publication status", "qualifications", "choice", options=_options("Published", "Accepted", "In Press", "Submitted", "In Preparation")),
    _field("publications.0.description", "Publication description", "qualifications", "textarea"),

    _field("platform_preferences.interfolio.referral_source", "How you first heard about Interfolio", "platform_defaults", "choice", options=INTERFOLIO_REFERRAL_OPTIONS),

    _field("employment_basics.availability_to_start", "Earliest available start date", "defaults", "date"),
    _field("employment_basics.salary_expectation.amount_target", "Desired annual salary", "defaults", "number", min_value=0),
    _field("employment_basics.salary_expectation.period", "Salary period", "defaults", "choice", options=_options("annual", "hourly", "monthly", "weekly")),
    _field("employment_basics.willing_to_relocate", "Willing to relocate", "defaults", "boolean"),
    _field("employment_basics.willing_to_travel_percent", "Maximum travel percentage", "defaults", "number", min_value=0, max_value=100),
    _field("application_defaults.referral_source", "Default job source", "defaults", "choice", options=REFERRAL_OPTIONS),
    _field("application_defaults.specific_referral_source", "Default source details", "defaults"),
    _field("application_defaults.previously_employed_by_employer", "Previously employed by the hiring employer by default", "defaults", "boolean"),
    _field("application_defaults.previously_employed_by_employer_details", "Previous-employment details", "defaults", "textarea"),
    _field("application_defaults.previous_employer_employee_id", "Previous employee ID", "defaults"),
    _field("application_defaults.related_to_employer_employee", "Related to an employee by default", "defaults", "boolean"),
    _field("application_defaults.related_to_employer_employee_details", "Related-employee details", "defaults", "textarea"),
    _field("application_defaults.has_conflict_of_interest", "Conflict of interest by default", "defaults", "boolean"),
    _field("application_defaults.has_conflict_of_interest_details", "Conflict details", "defaults", "textarea"),
    _field("application_defaults.claims_veterans_preference", "Claim veteran's hiring preference when offered", "defaults", "boolean"),
    _field("application_defaults.excluded_from_government_program", "Excluded from a government program", "defaults", "boolean"),
    _field("application_defaults.excluded_from_government_program_details", "Government-program exclusion details", "defaults", "textarea"),

    _field("identity_and_status.gender.value", "Gender response for application forms", "demographics", "choice", options=GENDER_OPTIONS),
    _field(
        "identity_and_status.gender.custom_value",
        "Self-described gender",
        "demographics",
        required_when_path="identity_and_status.gender.value",
        required_when_values=("Non-Binary",),
    ),
    _field("detailed_personal_info.ethnicity.value", "Hispanic or Latino response", "demographics", "choice", options=HISPANIC_OPTIONS),
    _field("application_defaults.race_ethnicity", "Race or ethnicity categories", "demographics", "multi_choice", options=RACE_OPTIONS),
    _field("detailed_personal_info.disability_status.value", "Disability self-identification", "demographics", "choice", options=DECLINABLE_STATUS_OPTIONS),
    _field("detailed_personal_info.disability_status.accommodation_needed", "Accommodation requested", "demographics", "boolean"),
    _field("detailed_personal_info.disability_status.accommodation_details", "Accommodation details", "demographics", "textarea"),
    _field("detailed_personal_info.veteran_status.value", "Veteran self-identification", "demographics", "choice", options=DECLINABLE_STATUS_OPTIONS),
    _field("detailed_personal_info.veteran_status.veteran_with_disability", "Veteran with a disability", "demographics", "boolean"),
    _field("detailed_personal_info.veteran_status.surviving_spouse", "Surviving spouse of a veteran", "demographics", "boolean"),
    _field("detailed_personal_info.veteran_status.orphan_of_veteran", "Orphan of a veteran", "demographics", "boolean"),
    _field("detailed_personal_info.former_foster_child", "Former foster child", "demographics", "boolean"),

    *tuple(
        field
        for index in range(5)
        for field in (
            _field(f"references.{index}.name", f"Reference {index + 1} name", "references"),
            _field(f"references.{index}.relationship", f"Reference {index + 1} relationship", "references"),
            _field(f"references.{index}.company", f"Reference {index + 1} organization", "references"),
            _field(f"references.{index}.title", f"Reference {index + 1} title", "references"),
            _field(f"references.{index}.email", f"Reference {index + 1} email", "references", "email"),
            _field(f"references.{index}.phone", f"Reference {index + 1} phone", "references", "tel"),
            _field(f"references.{index}.years_known", f"Reference {index + 1} years known", "references", "number", min_value=0, max_value=100),
        )
    ),
)

PROFILE_FIELDS = {field.path: field for field in _PROFILE_FIELD_ROWS}


def profile_fields() -> tuple[IntakeField, ...]:
    return _PROFILE_FIELD_ROWS


def _app_field(
    path: str,
    label: str,
    section: str = "position",
    kind: str = "text",
    *,
    required: bool = True,
    options: tuple[IntakeOption, ...] = (),
    help_text: str = "",
    required_when_path: str | None = None,
    required_when_values: tuple[Any, ...] = (),
    visible_when_path: str | None = None,
    visible_when_values: tuple[Any, ...] = (),
    storage: str = "application",
) -> IntakeField:
    return IntakeField(
        path=path,
        label=label,
        section=section,
        kind=kind,
        required=required,
        options=options,
        help_text=help_text,
        required_when_path=required_when_path,
        required_when_values=required_when_values,
        visible_when_path=visible_when_path,
        visible_when_values=visible_when_values,
        storage=storage,
    )


_COMMON_POSITION_FIELDS = (
    _app_field(
        "position_overrides.referral_source",
        "How did you find this position?",
        "position_referral",
        "choice",
        required=False,
        options=REFERRAL_OPTIONS,
    ),
    _app_field(
        "position_overrides.specific_referral_source",
        "Position source details",
        "position_referral",
        required=False,
        visible_when_path="position_overrides.referral_source",
        visible_when_values=tuple(option.value for option in REFERRAL_OPTIONS),
    ),
    _app_field(
        "position_overrides.employee_referral",
        "Referred by an employee of this institution",
        "position_referral",
        "boolean",
        required=False,
    ),
    _app_field(
        "position_overrides.employee_referrer_name",
        "Referrer's name",
        "position_referral",
        required=False,
        visible_when_path="position_overrides.employee_referral",
        visible_when_values=(True,),
        required_when_path="position_overrides.employee_referral",
        required_when_values=(True,),
    ),
    _app_field(
        "position_overrides.employee_referrer_relationship",
        "Relationship to referrer",
        "position_referral",
        required=False,
        visible_when_path="position_overrides.employee_referral",
        visible_when_values=(True,),
    ),
    _app_field(
        "position_overrides.employee_referrer_department",
        "Referrer's department",
        "position_referral",
        required=False,
        visible_when_path="position_overrides.employee_referral",
        visible_when_values=(True,),
    ),
    _app_field(
        "position_overrides.employment_relationship",
        "Employment relationship with this institution",
        "position_relationships",
        "choice",
        required=False,
        options=EMPLOYMENT_RELATIONSHIP_OPTIONS,
    ),
    _app_field(
        "position_overrides.previously_employed_by_employer_details",
        "Institution employment details",
        "position_relationships",
        "textarea",
        required=False,
        required_when_path="position_overrides.employment_relationship",
        required_when_values=("current", "former"),
    ),
    _app_field(
        "position_overrides.previous_employer_employee_id",
        "Institution employee ID",
        "position_relationships",
        required=False,
        visible_when_path="position_overrides.employment_relationship",
        visible_when_values=("current", "former"),
    ),
    _app_field(
        "position_overrides.related_to_employer_employee",
        "Relative or close relationship employed by this institution",
        "position_relationships",
        "boolean",
        required=False,
    ),
    _app_field(
        "position_overrides.related_to_employer_employee_details",
        "Employee relationship details",
        "position_relationships",
        "textarea",
        required=False,
        required_when_path="position_overrides.related_to_employer_employee",
        required_when_values=(True,),
    ),
    _app_field(
        "position_overrides.has_conflict_of_interest",
        "Conflict of interest with this institution",
        "position_relationships",
        "boolean",
        required=False,
    ),
    _app_field(
        "position_overrides.has_conflict_of_interest_details",
        "Conflict details",
        "position_relationships",
        "textarea",
        required=False,
        required_when_path="position_overrides.has_conflict_of_interest",
        required_when_values=(True,),
    ),
)

_CUHK_FIELDS = (
    _app_field("position_overrides.cuhk_applied_division", "Applied division", options=_options("Statistics")),
    _app_field("position_overrides.cuhk_applied_class_of_appointment", "Applied class of appointment", options=_options("Tenure-Track", "Research", "Teaching")),
    _app_field("position_overrides.cuhk_applied_position", "Applied position"),
    _app_field("answers.cuhk_id_type", "Government ID type", "screening", "choice", options=_options("Passport", "Hong Kong Identity Card", "Mainland Identity Card", "Other"), storage="runtime_secret"),
    _app_field("answers.cuhk_id_type_other", "Other government ID type", "screening", required=False, storage="runtime_secret"),
    _app_field("answers.cuhk_id_number", "Government ID number", "screening", storage="runtime_secret"),
)

_NYU_FIELDS = (
    _app_field("position_overrides.license_cert", "License or certification for this NYU application", "screening", "choice", options=_options("N/A", "No License/Cert", "Council of Clin Research Coord(30143)", "Basic Life Support Cert(30017)")),
)

_UA_FIELDS = (
    _app_field("answers.ua_felony_conviction", "Felony conviction response", "screening", storage="runtime_secret"),
    _app_field("answers.ua_felony_description", "Felony conviction details", "screening", required=False, storage="runtime_secret"),
)

APPLICATION_FIELDS = {
    "cuhk": _CUHK_FIELDS + _COMMON_POSITION_FIELDS,
    "gustavus": _COMMON_POSITION_FIELDS,
    "nyulangone": _NYU_FIELDS + _COMMON_POSITION_FIELDS,
    "ua": _UA_FIELDS + _COMMON_POSITION_FIELDS,
    "uci": _COMMON_POSITION_FIELDS,
    "ucsb": _COMMON_POSITION_FIELDS,
    "umn": _COMMON_POSITION_FIELDS,
    "utah": _COMMON_POSITION_FIELDS,
    "uthealth": _COMMON_POSITION_FIELDS,
    "yale": _COMMON_POSITION_FIELDS,
}


_CORE_IDENTITY = {
    "person_name.legal_name.first",
    "person_name.legal_name.last",
}
_CORE_CONTACT = {
    "address_and_contact.primary_address.line_1",
    "address_and_contact.primary_address.city",
    "address_and_contact.primary_address.state_province",
    "address_and_contact.primary_address.postal_code",
    "address_and_contact.primary_address.country",
    "address_and_contact.phone_numbers.mobile",
}
_CORE_EDUCATION = {
    "education.highest_level",
    "education.schools.0.institution",
    "education.schools.0.degree",
    "education.schools.0.major",
    "education.schools.0.city",
    "education.schools.0.state_province",
    "education.schools.0.country",
    "education.schools.0.start_date",
    "education.schools.0.graduation_date",
}
_CORE_AUTH = {
    "application_defaults.authorized_to_work_us",
    "detailed_personal_info.birth_and_citizenship.requires_visa_sponsorship",
}
_CURRENT_WORK = {
    "work_history.0.company",
    "work_history.0.job_title",
    "work_history.0.start_date",
    "work_history.0.city",
    "work_history.0.country",
    "work_history.0.responsibilities",
}
_PROFESSIONAL = {
    "professional_profile.current_position_status",
    "professional_profile.scholarly_discipline",
}
_EMERGENCY_CONTACT = {
    "emergency_contact.name",
    "emergency_contact.relationship",
    "emergency_contact.phone",
    "emergency_contact.address",
}
_PRIMARY_PUBLICATION = {
    "publications.0.type",
    "publications.0.work_type",
    "publications.0.title",
    "publications.0.authors",
    "publications.0.venue",
    "publications.0.status",
    "publications.0.description",
}
_DEFAULTS = {
    "employment_basics.availability_to_start",
    "employment_basics.salary_expectation.amount_target",
    "employment_basics.salary_expectation.period",
    "application_defaults.referral_source",
    "application_defaults.previously_employed_by_employer",
    "application_defaults.related_to_employer_employee",
    "application_defaults.has_conflict_of_interest",
}


PROFILE_REQUIREMENTS = {
    "cuhk": _CORE_IDENTITY | _CORE_CONTACT | _CORE_EDUCATION | _CURRENT_WORK | _EMERGENCY_CONTACT | _PRIMARY_PUBLICATION | {
        "person_name.legal_name.prefix",
        "detailed_personal_info.date_of_birth",
        "detailed_personal_info.birth_and_citizenship.citizenship_country",
        "employment_basics.availability_to_start",
        "professional_profile.research_interests",
        "work_history.0.employment_type",
    },
    "gustavus": _CORE_IDENTITY | _CORE_CONTACT | _CORE_EDUCATION | _CORE_AUTH | _DEFAULTS | {
        *(f"references.{index}.{key}" for index in range(3) for key in ("name", "relationship", "email", "phone", "years_known")),
    },
    "nyulangone": _CORE_IDENTITY | _CORE_CONTACT | _CORE_EDUCATION | _DEFAULTS,
    "ua": _CORE_IDENTITY | _CORE_CONTACT | _CORE_EDUCATION | _CORE_AUTH | _CURRENT_WORK | {
        "person_name.legal_name.prefix",
        "work_history.0.start_day",
        "work_history.0.supervisor_name",
        "work_history.0.may_contact_supervisor",
        "detailed_personal_info.birth_and_citizenship.citizenship_country",
    },
    "uci": _CORE_IDENTITY | _CORE_CONTACT | _CORE_EDUCATION | _CURRENT_WORK,
    "ucsb": _CORE_IDENTITY | _CORE_CONTACT | _CORE_EDUCATION | _CURRENT_WORK,
    "umn": _CORE_IDENTITY | _CORE_CONTACT | _CORE_EDUCATION | _CORE_AUTH | _DEFAULTS,
    "utah": _CORE_IDENTITY | _CORE_CONTACT | _CORE_EDUCATION | {
        "person_name.legal_name.prefix",
        "identity_and_status.pronouns.set",
        "detailed_personal_info.birth_and_citizenship.visa_status.type",
        *(f"references.{index}.{key}" for index in range(5) for key in ("name", "relationship", "company", "title", "email")),
    },
    "uthealth": _CORE_IDENTITY | _CORE_CONTACT | _CORE_AUTH | {
        "detailed_personal_info.veteran_status.value",
        "detailed_personal_info.veteran_status.veteran_with_disability",
        "detailed_personal_info.veteran_status.surviving_spouse",
        "detailed_personal_info.veteran_status.orphan_of_veteran",
        "detailed_personal_info.former_foster_child",
    },
    "yale": _CORE_IDENTITY | _CORE_CONTACT | _CORE_EDUCATION | _CURRENT_WORK | _PROFESSIONAL | {
        "education.schools.0.degree_awarded_date",
        "platform_preferences.interfolio.referral_source",
    },
}


DOCUMENT_REQUIREMENTS = {
    "cuhk": (),
    "gustavus": ("documents.resume_path_or_url",),
    "nyulangone": ("documents.resume_path_or_url",),
    "ua": ("documents.resume_path_or_url", "documents.research_statement_path"),
    "uci": (),
    "ucsb": (),
    "umn": ("documents.resume_path_or_url",),
    "utah": (
        "documents.resume_path_or_url",
        "documents.cover_letter_path_or_url",
        "documents.research_statement_path",
        "documents.teaching_statement_path",
        "documents.references_path",
        "documents.writing_sample_path",
    ),
    "uthealth": ("documents.resume_path_or_url",),
    "yale": (
        "documents.resume_path_or_url",
        "documents.cover_letter_path_or_url",
        "documents.teaching_statement_path",
        "documents.syllabus_path",
        "documents.references_path",
    ),
}


PLAYBOOK_BLOCKERS = {
    "cuhk": (
        "CUHK requires a government ID number and its document-upload page is not yet mapped.",
    ),
    "uci": (
        "The UCI playbook still needs its required degree-discipline and attachment steps verified.",
    ),
    "ucsb": (
        "The UCSB playbook still needs its search-source options and attachment steps verified.",
    ),
    "ua": (
        "The UA criminal-history answer must be collected at a human checkpoint or encrypted secret store.",
    ),
}


def inspect_intake(path: str | Path) -> PlaybookIntake:
    playbook = load_playbook(str(path))
    return intake_for_playbook(playbook)


def intake_for_playbook(playbook: Playbook) -> PlaybookIntake:
    raw_intake = playbook.raw.get("intake")
    if not isinstance(raw_intake, dict):
        raise ValueError("playbook must declare intake.key")
    contract_key = raw_intake.get("key")
    if not isinstance(contract_key, str) or not contract_key.strip():
        raise ValueError("playbook intake.key must be a non-empty string")
    contract_key = contract_key.strip()
    if contract_key not in APPLICATION_FIELDS:
        raise ValueError(
            f"no applicant intake contract is registered for {contract_key!r}"
        )
    required_paths = tuple(sorted(PROFILE_REQUIREMENTS.get(contract_key, ())))
    unknown = [path for path in required_paths if path not in PROFILE_FIELDS]
    if unknown:
        raise ValueError(
            f"intake contract for {contract_key!r} has unknown profile paths: {unknown}"
        )
    return PlaybookIntake(
        contract_key=contract_key,
        application_key=playbook.application_key or "",
        profile_fields=_PROFILE_FIELD_ROWS,
        application_fields=tuple(APPLICATION_FIELDS[contract_key]),
        required_profile_paths=required_paths,
        required_document_paths=tuple(
            DOCUMENT_REQUIREMENTS.get(contract_key, ())
        ),
        blockers=tuple(PLAYBOOK_BLOCKERS.get(contract_key, ())),
    )


def prepare_intake_data(
    playbook: Playbook,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a copy with every known intake path present.

    Empty placeholders let conditional dry-run expressions evaluate normally;
    :func:`validate_intake` still reports required empty values separately.
    """
    prepared = copy.deepcopy(dict(data))
    contract = intake_for_playbook(playbook)
    for field in (*contract.profile_fields, *contract.application_fields):
        if field.is_runtime_only:
            continue
        _set_default_path(prepared, field.path, _empty_value(field.kind))
    for path in _DOCUMENT_PATHS:
        _set_default_path(prepared, path, "")
    return prepared


def validate_intake(playbook: Playbook, data: Mapping[str, Any]) -> tuple[IntakeIssue, ...]:
    contract = intake_for_playbook(playbook)
    issues: list[IntakeIssue] = []

    for blocker in contract.blockers:
        issues.append(
            IntakeIssue(
                code="playbook_blocked",
                path="",
                label="Playbook verification",
                section="position",
                message=blocker,
            )
        )

    for path in contract.required_profile_paths:
        field = PROFILE_FIELDS[path]
        value = _resolve(path, data)
        if not _has_value(value):
            issues.append(_missing_issue("missing_profile_field", field))
        elif not _valid_choice(field, value):
            issues.append(_choice_issue("invalid_profile_choice", field))

    for field in contract.profile_fields:
        if field.path in contract.required_profile_paths:
            continue
        value = _resolve(field.path, data)
        if _condition_requires(field, data) and not _has_value(value):
            issues.append(_missing_issue("missing_profile_field", field))
        elif _has_value(value) and not _valid_choice(field, value):
            issues.append(_choice_issue("invalid_profile_choice", field))

    for field in contract.application_fields:
        if field.is_runtime_only:
            continue
        value = _resolve(field.path, data)
        required = field.required or _condition_requires(field, data)
        if required and not _has_value(value):
            issues.append(_missing_issue("missing_application_field", field))
        elif _has_value(value) and not _valid_choice(field, value):
            issues.append(_choice_issue("invalid_application_choice", field))

    for path in contract.required_document_paths:
        value = _resolve(path, data)
        if not _has_value(value):
            label = _DOCUMENT_LABELS.get(path, path)
            issues.append(
                IntakeIssue(
                    code="missing_document",
                    path=path,
                    label=label,
                    section="documents",
                    message=f"Upload {label.lower()}.",
                )
            )
    return tuple(issues)


def group_fields(fields: Iterable[IntakeField]) -> tuple[dict[str, Any], ...]:
    grouped: dict[str, list[IntakeField]] = {}
    for field in fields:
        if field.is_runtime_only:
            continue
        grouped.setdefault(field.section, []).append(field)
    return tuple(
        {"key": key, "label": section_label(key), "fields": tuple(rows)}
        for key, rows in grouped.items()
    )


def get_path(data: Mapping[str, Any], path: str, default: Any = "") -> Any:
    return resolve_path(path, dict(data), default=default)


def set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current: Any = data
    for index, part in enumerate(parts[:-1]):
        next_part = parts[index + 1]
        if isinstance(current, list):
            position = int(part)
            while len(current) <= position:
                current.append({} if not next_part.isdigit() else [])
            current = current[position]
            continue
        if part.isdigit():
            raise ValueError(f"list index {part!r} has no parent list in {path!r}")
        expected: Any = [] if next_part.isdigit() else {}
        if not isinstance(current.get(part), type(expected)):
            current[part] = expected
        current = current[part]

    final = parts[-1]
    if isinstance(current, list):
        position = int(final)
        while len(current) <= position:
            current.append(None)
        current[position] = value
    else:
        current[final] = value


def _set_default_path(data: dict[str, Any], path: str, value: Any) -> None:
    marker = object()
    if _resolve(path, data, marker) is marker:
        set_path(data, path, value)


def _resolve(path: str, data: Mapping[str, Any], default: Any = None) -> Any:
    return resolve_path(path, dict(data), default=default)


def _empty_value(kind: str) -> Any:
    if kind == "multi_choice":
        return []
    if kind in {"boolean", "number"}:
        return None
    return ""


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return True


def _valid_choice(field: IntakeField, value: Any) -> bool:
    if not field.options:
        return True
    permitted = {option.value for option in field.options}
    values = value if field.kind == "multi_choice" and isinstance(value, list) else [value]
    return all(str(item) in permitted for item in values)


def _condition_requires(field: IntakeField, data: Mapping[str, Any]) -> bool:
    if not field.required_when_path:
        return False
    value = _resolve(field.required_when_path, data)
    return value in field.required_when_values


def _missing_issue(code: str, field: IntakeField) -> IntakeIssue:
    return IntakeIssue(
        code=code,
        path=field.path,
        label=field.label,
        section=field.section,
        message=f"Provide {field.label.lower()}.",
    )


def _choice_issue(code: str, field: IntakeField) -> IntakeIssue:
    return IntakeIssue(
        code=code,
        path=field.path,
        label=field.label,
        section=field.section,
        message=f"Choose a supported value for {field.label.lower()}.",
    )


_DOCUMENT_PATHS = (
    "documents.resume_path_or_url",
    "documents.cover_letter_path_or_url",
    "documents.research_statement_path",
    "documents.statement_of_research_path",
    "documents.teaching_statement_path",
    "documents.writing_sample_path",
    "documents.teaching_evaluations_path",
    "documents.syllabus_path",
    "documents.references_path",
    "documents.additional_attachment_path",
)
_DOCUMENT_LABELS = {
    "documents.resume_path_or_url": "Resume or CV",
    "documents.cover_letter_path_or_url": "Cover letter",
    "documents.research_statement_path": "Research statement",
    "documents.statement_of_research_path": "Research statement",
    "documents.teaching_statement_path": "Teaching statement",
    "documents.writing_sample_path": "Writing sample",
    "documents.teaching_evaluations_path": "Teaching evaluations",
    "documents.syllabus_path": "Syllabus",
    "documents.references_path": "References document",
    "documents.additional_attachment_path": "Additional attachment",
}
