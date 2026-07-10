from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

import yaml

from playbook_runner.context import load_context
from playbook_runner.equivalences import OptionCandidate, best_match


ROOT = Path(__file__).resolve().parents[1]
BASE_PROFILES = [
    ROOT / "applicants" / "test.json",
    ROOT / "applicants" / "test_stats_rao.json",
    ROOT / "applicants" / "test_stats_rodriguez.json",
]

REQUIRED_APPLICATION_DEFAULTS = {
    "authorized_to_work_us",
    "requires_visa_sponsorship",
    "desired_salary",
    "salary_period",
    "referral_source",
    "specific_referral_source",
    "employee_referral",
    "employee_referrer_name",
    "employee_referrer_relationship",
    "previously_employed_by_employer",
    "previously_employed_by_employer_details",
    "previous_employer_employee_id",
    "related_to_employer_employee",
    "related_to_employer_employee_details",
    "has_conflict_of_interest",
    "has_conflict_of_interest_details",
    "claims_veterans_preference",
    "excluded_from_government_program",
    "excluded_from_government_program_details",
}

REQUIRED_DOCUMENTS = {
    "resume_path_or_url",
    "cover_letter_path_or_url",
    "research_statement_path",
    "statement_of_research_path",
    "teaching_statement_path",
    "writing_sample_path",
    "teaching_evaluations_path",
    "syllabus_path",
    "references_path",
    "additional_attachment_path",
}

REFERRAL_SOURCES = {
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
}

HIGHEST_LEVELS = {
    "High School",
    "Associate",
    "Bachelors",
    "Masters",
    "Doctorate",
    "Professional Degree",
    "Other",
}

PRONOUN_SETS = {"", "he/him", "she/her", "they/them", "ze/hir", "ze/zir"}
GENDERS = {"Male", "Female", "I do not wish to provide this information"}
RACES = {
    "American Indian or Alaska Native",
    "Asian",
    "Black or African American",
    "Native Hawaiian or Other Pacific Islander",
    "White",
    "Two or More Races",
    "I do not wish to provide this information",
}

UTAH_STATE_OPTIONS = [
    "Not Applicable (Int'l Candidate)",
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA",
    "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY",
    "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX",
    "UT", "VT", "VA", "WA", "WV", "WI", "WY", "AS", "FM", "GU", "MH",
    "MP", "PW", "PR", "VI", "AE", "AA", "AP", "AB", "BC", "MB", "NB",
    "NF", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT",
]

UTAH_DEGREE_OPTIONS = [
    "A-Not Indicated",
    "B-Less Than HS Graduate",
    "C-HS Graduate or Equivalent",
    "D-Some College",
    "E-Technical School",
    "F-2-Year College Degree",
    "G-Bachelor's Level Degree",
    "H-Some Graduate School",
    "I-Master's Level Degree",
    "J-Doctorate (Academic)",
    "K-Doctorate (Professional)",
    "L-Post-Doctorate",
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def playbook_template_paths(prefix: str) -> set[str]:
    found: set[str] = set()
    for path in (ROOT / "playbooks").glob("*.playbook.yaml"):
        yaml.safe_load(path.read_text())
        for match in re.finditer(r"\{\{\s*" + re.escape(prefix) + r"\.([A-Za-z0-9_]+)", path.read_text()):
            found.add(match.group(1))
    return found


def option_candidates(labels: list[str]) -> list[OptionCandidate]:
    return [OptionCandidate(label) for label in labels]


def country_options() -> list[OptionCandidate]:
    fixture = ROOT / "tests" / "fixtures" / "utah_country_options.txt"
    return option_candidates([line for line in fixture.read_text().splitlines() if line])


class ProfileContractTests(unittest.TestCase):
    def test_schema_contains_document_keys_used_by_playbooks(self) -> None:
        schema_docs = load_json(ROOT / "information" / "test.json")["documents"]
        for key in playbook_template_paths("documents") | REQUIRED_DOCUMENTS:
            with self.subTest(document=key):
                self.assertIn(key, schema_docs)

    def test_base_profiles_have_all_playbook_answer_and_document_keys(self) -> None:
        answer_keys = playbook_template_paths("answers")
        document_keys = playbook_template_paths("documents") | REQUIRED_DOCUMENTS

        for path in BASE_PROFILES:
            data = load_json(path)
            with self.subTest(profile=path.name, section="answers"):
                self.assertFalse(sorted(answer_keys - set(data["answers"])))
            with self.subTest(profile=path.name, section="documents"):
                self.assertFalse(sorted(document_keys - set(data["documents"])))

    def test_base_profile_documents_exist_when_filled(self) -> None:
        for path in BASE_PROFILES:
            documents = load_json(path)["documents"]
            for key, value in documents.items():
                if not key.endswith(("_path", "_path_or_url")) or not value:
                    continue
                if str(value).startswith(("http://", "https://")):
                    continue
                with self.subTest(profile=path.name, document=key):
                    self.assertTrue((ROOT / value).exists(), value)

    def test_base_profiles_have_complete_application_defaults(self) -> None:
        schema_defaults = load_json(ROOT / "information" / "test.json")["application_defaults"]
        self.assertFalse(sorted(REQUIRED_APPLICATION_DEFAULTS - set(schema_defaults)))

        for path in BASE_PROFILES:
            defaults = load_json(path)["application_defaults"]
            with self.subTest(profile=path.name):
                self.assertFalse(sorted(REQUIRED_APPLICATION_DEFAULTS - set(defaults)))
                self.assertIn(defaults["referral_source"], REFERRAL_SOURCES)
                self.assertIn(defaults["salary_period"], {"annual", "hourly", "monthly", "weekly"})

    def test_base_profiles_use_intake_option_vocabulary(self) -> None:
        for path in BASE_PROFILES:
            data = load_json(path)
            answers = data["answers"]
            with self.subTest(profile=path.name, field="highest_level"):
                self.assertIn(data["education"]["highest_level"], HIGHEST_LEVELS)
            with self.subTest(profile=path.name, field="pronouns"):
                self.assertIn(data["identity_and_status"]["pronouns"]["set"], PRONOUN_SETS)
            with self.subTest(profile=path.name, field="gender"):
                self.assertIn(answers["gender"], GENDERS)

            race_value = answers["race_ethnicity"]
            race_values = race_value if isinstance(race_value, list) else [race_value]
            for race in race_values:
                with self.subTest(profile=path.name, field="race_ethnicity", race=race):
                    self.assertIn(race, RACES)

    def test_base_profile_values_match_utah_dropdowns(self) -> None:
        state_options = option_candidates(UTAH_STATE_OPTIONS)
        degree_options = option_candidates(UTAH_DEGREE_OPTIONS)
        countries = country_options()

        for path in BASE_PROFILES:
            data = load_json(path)
            context = load_context([str(path)], application_key="utah")
            address = data["address_and_contact"]["primary_address"]

            state_match = best_match(address["state_province"], state_options, context="State")
            self.assertIsNotNone(state_match, path.name)

            country_match = best_match(address["country"], countries, context="Country")
            self.assertIsNotNone(country_match, path.name)

            degree_match = best_match(
                context["app_answers"]["highest_education"],
                degree_options,
                context="Highest Degree",
            )
            self.assertIsNotNone(degree_match, path.name)


if __name__ == "__main__":
    unittest.main()
