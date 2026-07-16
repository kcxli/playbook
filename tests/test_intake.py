from __future__ import annotations

import re
import unittest
from pathlib import Path

from playbook_runner.intake import (
    APPLICATION_FIELDS,
    COUNTRY_OPTIONS,
    PROFILE_FIELDS,
    inspect_intake,
    prepare_intake_data,
    validate_intake,
)
from playbook_runner.parser import load_playbook


ROOT = Path(__file__).resolve().parent.parent
ANSWER_PATH_RE = re.compile(r"\banswers\.[A-Za-z0-9_.]+")
PROFILE_PATH_RE = re.compile(
    r"\b(?:person_name|identity_and_status|detailed_personal_info|"
    r"address_and_contact|education|work_history|employment_basics|references|"
    r"emergency_contact|professional_profile|platform_preferences|publications)"
    r"\.[A-Za-z0-9_.]+"
)


def step_text(playbook):
    for step in playbook.steps:
        for value in (
            step.target,
            step.value,
            step.selector,
            step.when,
            step.group,
            step.scope,
            step.pick,
            step.config,
        ):
            yield from nested_strings(value)


def nested_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from nested_strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from nested_strings(child)


class IntakeContractTests(unittest.TestCase):
    def test_every_maintained_playbook_has_an_intake_contract(self):
        for path in sorted((ROOT / "playbooks").glob("*.playbook.yaml")):
            with self.subTest(playbook=path.name):
                contract = inspect_intake(path)
                self.assertTrue(contract.application_key)
                self.assertEqual(
                    contract.contract_key,
                    path.name.removesuffix(".playbook.yaml"),
                )
                self.assertGreater(len(contract.profile_fields), 0)

    def test_every_legacy_answer_path_is_registered_as_application_scoped(self):
        for path in sorted((ROOT / "playbooks").glob("*.playbook.yaml")):
            playbook = load_playbook(str(path))
            contract = inspect_intake(path)
            used = {
                match
                for text in step_text(playbook)
                for match in ANSWER_PATH_RE.findall(text)
            }
            registered = {
                field.path for field in APPLICATION_FIELDS[contract.contract_key]
            }
            with self.subTest(playbook=path.name):
                self.assertEqual(sorted(used - registered), [])

    def test_every_direct_profile_path_is_registered(self):
        ignored_false_positives = {"education.education", "references.reference"}
        for path in sorted((ROOT / "playbooks").glob("*.playbook.yaml")):
            playbook = load_playbook(str(path))
            used = {
                match
                for text in step_text(playbook)
                for match in PROFILE_PATH_RE.findall(text)
            } - ignored_false_positives
            with self.subTest(playbook=path.name):
                self.assertEqual(sorted(used - set(PROFILE_FIELDS)), [])

    def test_country_picker_is_global_not_mac_or_us_only(self):
        values = {option.value for option in COUNTRY_OPTIONS}
        self.assertGreater(len(values), 200)
        for value in ("United States", "Canada", "India", "Nigeria", "South Korea"):
            self.assertIn(value, values)

    def test_runtime_secrets_are_not_storable_application_fields(self):
        cuhk = inspect_intake(ROOT / "playbooks" / "cuhk.playbook.yaml")
        storable = {field.path for field in cuhk.storable_application_fields}

        self.assertNotIn("answers.cuhk_id_number", storable)
        self.assertTrue(cuhk.blockers)

    def test_storable_position_answers_are_true_target_overrides(self):
        for path in sorted((ROOT / "playbooks").glob("*.playbook.yaml")):
            contract = inspect_intake(path)
            with self.subTest(playbook=path.name):
                self.assertTrue(
                    all(
                        field.path.startswith("position_overrides.")
                        for field in contract.storable_application_fields
                    )
                )

    def test_yale_does_not_repeat_shared_profile_questions(self):
        yale = inspect_intake(ROOT / "playbooks" / "yale.playbook.yaml")
        labels = {field.label for field in yale.storable_application_fields}

        self.assertNotIn("Current academic position status", labels)
        self.assertNotIn("Degree institution", labels)
        self.assertIn("How did you find this position?", labels)
        self.assertIn("Employment relationship with this institution", labels)

    def test_preparation_scaffolds_paths_but_validation_still_reports_missing(self):
        playbook = load_playbook(str(ROOT / "playbooks" / "gustavus.playbook.yaml"))
        prepared = prepare_intake_data(playbook, {})
        issues = validate_intake(playbook, prepared)

        self.assertEqual(
            prepared["person_name"]["legal_name"]["first"],
            "",
        )
        self.assertIn("missing_profile_field", {issue.code for issue in issues})


if __name__ == "__main__":
    unittest.main()
