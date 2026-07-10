from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from playbook_runner.context import load_context


class ContextTests(unittest.TestCase):
    def test_short_unique_builtin_is_username_safe(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            data = tmp / "profile.json"
            data.write_text("{}")

            context = load_context([str(data)])

        short_unique = context["builtins"]["short_unique"]
        self.assertEqual(len(short_unique), 8)
        self.assertRegex(short_unique, r"^[a-z0-9]+$")

    def test_generated_account_email_uses_plus_alias(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            data = tmp / "profile.json"
            data.write_text(
                json.dumps(
                    {
                        "emails": {
                            "preferred_contact_email": "person+oldtag@example.com",
                            "institution_email": "person@example.edu",
                        }
                    }
                )
            )

            context = load_context([str(data)])

        tag = context["builtins"]["short_unique"]
        self.assertEqual(
            context["account"]["generated_email"],
            f"person+ut{tag}@example.com",
        )

    def test_legal_initials_builtin(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            data = tmp / "profile.json"
            data.write_text(
                json.dumps(
                    {
                        "person_name": {
                            "legal_name": {
                                "first": "Anika",
                                "middle": "Meera",
                                "last": "Rao",
                            }
                        }
                    }
                )
            )

            context = load_context([str(data)])

        self.assertEqual(context["builtins"]["legal_initials"], "AMR")

    def test_data_files_deep_merge(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            base = tmp / "base.json"
            override = tmp / "override.json"
            base.write_text(
                json.dumps(
                    {
                        "answers": {
                            "authorized_to_work_us": True,
                            "referral_source": "Job Board",
                        },
                        "account": {
                            "user_name": "person@example.com",
                            "password": "base-secret",
                        },
                    }
                )
            )
            override.write_text(
                json.dumps(
                    {
                        "answers": {"referral_source": "HERC"},
                        "account": {"password": "override-secret"},
                    }
                )
            )

            context = load_context([str(base), str(override)], application_key="umn")

        self.assertEqual(context["answers"]["authorized_to_work_us"], True)
        self.assertEqual(context["answers"]["referral_source"], "HERC")
        self.assertEqual(context["account"]["user_name"], "person@example.com")
        self.assertEqual(context["account"]["password"], "override-secret")

    def test_app_answers_merge_canonical_legacy_defaults_and_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            data = tmp / "profile.json"
            data.write_text(
                json.dumps(
                    {
                        "education": {
                            "highest_level": "Doctorate",
                            "schools": [
                                {
                                    "institution": "Base University",
                                    "degree": "Ph.D.",
                                    "major": "Statistics",
                                    "start_date": "2015-09",
                                    "graduation_date": "2021-06-11",
                                }
                            ],
                        },
                        "work_history": [
                            {
                                "company": "Current University",
                                "job_title": "Assistant Professor",
                            }
                        ],
                        "employment_basics": {
                            "availability_to_start": "2026-09-01",
                            "salary_expectation": {
                                "amount_min": 82000,
                                "amount_target": 90000,
                                "amount_max": 105000,
                                "period": "annual",
                            },
                            "willing_to_relocate": True,
                        },
                        "detailed_personal_info": {
                            "ethnicity": {
                                "value": "Not Hispanic or Latino",
                                "prefer_not_to_say": False,
                            },
                            "veteran_status": {"value": "no"},
                            "disability_status": {"value": "decline"},
                            "birth_and_citizenship": {
                                "work_authorization_country": "U.S.A.",
                                "requires_visa_sponsorship": False,
                            },
                        },
                        "identity_and_status": {"gender": {"value": "Female"}},
                        "answers": {
                            "referral_source": "Job Board",
                            "legacy_only": "still available",
                        },
                        "application_defaults": {
                            "authorized_to_work_us": None,
                            "specific_referral_source": "",
                            "previously_employed_by_employer": False,
                            "previously_employed_by_employer_details": "",
                            "previous_employer_employee_id": "",
                            "related_to_employer_employee": False,
                            "has_conflict_of_interest": False,
                        },
                        "application_exceptions": {
                            "University of Minnesota": {
                                "referral_source": "HERC",
                                "specific_referral_source": "HERC statistics mailing list",
                                "previously_employed_by_employer": True,
                                "previously_employed_by_employer_details": "Temporary research appointment.",
                                "previous_employer_employee_id": "12345",
                            }
                        },
                    }
                )
            )

            context = load_context([str(data)], application_key="university-of-minnesota")

        app_answers = context["app_answers"]
        self.assertEqual(context["runner"]["application_key"], "university-of-minnesota")
        self.assertEqual(app_answers["school"], "Base University")
        self.assertEqual(app_answers["degree"], "Ph.D.")
        self.assertEqual(app_answers["degree_discipline"], "Statistics")
        self.assertEqual(app_answers["degree_year_started"], "2015")
        self.assertEqual(app_answers["degree_year_acquired"], "2021")
        self.assertEqual(app_answers["current_title"], "Assistant Professor")
        self.assertEqual(app_answers["current_organization"], "Current University")
        self.assertEqual(app_answers["desired_salary"], "90000")
        self.assertEqual(app_answers["salary_period"], "annual")
        self.assertEqual(app_answers["authorized_to_work_us"], True)
        self.assertEqual(app_answers["requires_visa_sponsorship"], False)
        self.assertEqual(app_answers["is_hispanic_or_latino"], "No")
        self.assertEqual(app_answers["is_veteran"], False)
        self.assertEqual(app_answers["gender"], "Female")
        self.assertEqual(app_answers["legacy_only"], "still available")
        self.assertEqual(app_answers["previously_employed_by_employer"], True)
        self.assertEqual(app_answers["previously_employed_by_employer_details"], "Temporary research appointment.")
        self.assertEqual(app_answers["previous_employer_employee_id"], "12345")
        self.assertEqual(app_answers["related_to_employer_employee"], False)
        self.assertEqual(app_answers["has_conflict_of_interest"], False)
        self.assertEqual(app_answers["referral_source"], "HERC")
        self.assertEqual(app_answers["specific_referral_source"], "HERC statistics mailing list")


if __name__ == "__main__":
    unittest.main()
