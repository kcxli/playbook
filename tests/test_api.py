from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from playbook_runner import build_context, inspect_playbook, validate_application
from playbook_runner.context import DataError


class ContextApiTests(unittest.TestCase):
    def test_build_context_does_not_mutate_caller_data(self) -> None:
        source = {
            "person_name": {"legal_name": {"first": "Ada", "last": "Lovelace"}},
            "account": {"user_name": "ada_{{ builtins.short_unique }}"},
            "builtins": {"short_unique": "caller-controlled"},
        }

        context = build_context(source, application_key="sample")

        self.assertEqual(source["account"]["user_name"], "ada_{{ builtins.short_unique }}")
        self.assertEqual(source["builtins"]["short_unique"], "caller-controlled")
        self.assertRegex(context["account"]["user_name"], r"^ada_[a-z0-9]{8}$")
        self.assertEqual(context["runner"]["application_key"], "sample")
        self.assertEqual(context["builtins"]["legal_initials"], "AL")

    def test_build_context_requires_a_mapping(self) -> None:
        with self.assertRaisesRegex(DataError, "must be a mapping"):
            build_context(["not", "a", "mapping"])  # type: ignore[arg-type]


class ValidationApiTests(unittest.TestCase):
    def _playbook(self, directory: str, body: str) -> Path:
        path = Path(directory) / "sample.playbook.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_inspect_playbook_returns_hash_and_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._playbook(
                tmp,
                "\n".join(
                    [
                        "version: 1",
                        'name: "Sample application"',
                        'job_id: "JOB-7"',
                        'employer_key: "sample"',
                        'url: "https://jobs.example.test/JOB-7"',
                        "listing:",
                        '  institution: "Example University"',
                        '  title: "Assistant Professor"',
                        '  field: "Statistics"',
                        '  rank: ["assistant_professor"]',
                        "steps:",
                        '  - fill: "Email"',
                        '    value: "{{ emails.preferred_contact_email }}"',
                        '  - await_email_code:',
                        '      field: "Code"',
                        '  - pause_for_user: "Review and submit."',
                    ]
                ),
            )

            manifest = inspect_playbook(path)

        self.assertEqual(manifest.name, "Sample application")
        self.assertEqual(manifest.job_id, "JOB-7")
        self.assertEqual(manifest.application_key, "sample")
        self.assertIsNone(manifest.intake_key)
        self.assertEqual(manifest.step_count, 3)
        self.assertEqual(
            manifest.capabilities, ("email_code", "human_checkpoint")
        )
        self.assertTrue(manifest.final_human_gate)
        self.assertEqual(manifest.listing.institution, "Example University")
        self.assertEqual(manifest.listing.title, "Assistant Professor")
        self.assertEqual(manifest.listing.rank, ("assistant_professor",))
        self.assertRegex(manifest.sha256, r"^[0-9a-f]{64}$")

    def test_inspect_playbook_rejects_invalid_listing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._playbook(
                tmp,
                "\n".join(
                    [
                        "version: 1",
                        "listing:",
                        '  institution: "Example University"',
                        "steps:",
                        '  - pause_for_user: "Review."',
                    ]
                ),
            )

            with self.assertRaisesRegex(Exception, "listing.title"):
                inspect_playbook(path)

    def test_manifest_marks_a_declared_captcha_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._playbook(
                tmp,
                "\n".join(
                    [
                        "version: 1",
                        "human_requirements:",
                        "  - captcha",
                        "steps:",
                        '  - pause_for_user: "Complete the CAPTCHA."',
                    ]
                ),
            )

            manifest = inspect_playbook(path)

        self.assertIn("captcha", manifest.capabilities)

    def test_manifest_rejects_unknown_human_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._playbook(
                tmp,
                "\n".join(
                    [
                        "version: 1",
                        "human_requirements:",
                        "  - solve_captcha_automatically",
                        "steps:",
                        '  - pause_for_user: "Review."',
                    ]
                ),
            )

            with self.assertRaisesRegex(Exception, "unsupported values"):
                inspect_playbook(path)

    def test_validate_application_reports_missing_data_without_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._playbook(
                tmp,
                "\n".join(
                    [
                        "version: 1",
                        "steps:",
                        '  - fill: "First name"',
                        '    value: "{{ person_name.legal_name.first }}"',
                        '  - pause_for_user: "Review and submit."',
                    ]
                ),
            )

            result = validate_application(path, {})

        self.assertFalse(result.ready)
        self.assertEqual(result.problem_count, 1)
        self.assertEqual(result.issues[0].step, 1)
        self.assertIn("person_name.legal_name.first", result.issues[0].message)

    def test_validate_application_accepts_complete_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._playbook(
                tmp,
                "\n".join(
                    [
                        "version: 1",
                        "steps:",
                        '  - fill: "First name"',
                        '    value: "{{ person_name.legal_name.first }}"',
                        '  - pause_for_user: "Review and submit."',
                    ]
                ),
            )

            result = validate_application(
                path, {"person_name": {"legal_name": {"first": "Ada"}}}
            )

        self.assertTrue(result.ready)
        self.assertEqual(result.issues, ())

    def test_validate_application_structures_condition_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._playbook(
                tmp,
                "\n".join(
                    [
                        "version: 1",
                        "steps:",
                        '  - click: "Continue"',
                        '    when: "("',
                        '  - pause_for_user: "Review and submit."',
                    ]
                ),
            )

            result = validate_application(path, {})

        self.assertFalse(result.ready)
        self.assertEqual(result.problem_count, 1)
        self.assertEqual(result.issues[0].kind, "condition")
        self.assertIn("evaluating when", result.issues[0].message)


if __name__ == "__main__":
    unittest.main()
