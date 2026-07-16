from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from playbook_runner.engine import Engine
from playbook_runner.parser import ACTION_KEYS, PlaybookError, load_playbook


class ParserTests(unittest.TestCase):
    def _load_text(self, text: str):
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "sample.playbook.yaml"
            path.write_text(text, encoding="utf-8")
            return load_playbook(str(path))

    def test_employer_key_sets_application_key(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "sample.playbook.yaml"
            path.write_text(
                "\n".join(
                    [
                        "version: 1",
                        'name: "Sample"',
                        'job_id: "123"',
                        'employer_key: "sample-employer"',
                        'url: "https://example.test/apply"',
                        "steps:",
                        '  - click: "Apply"',
                    ]
                )
            )

            playbook = load_playbook(str(path))

        self.assertEqual(playbook.employer_key, "sample-employer")
        self.assertEqual(playbook.application_key, "sample-employer")

    def test_application_key_falls_back_to_legacy_site_key(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "sample.playbook.yaml"
            path.write_text(
                "\n".join(
                    [
                        "version: 1",
                        'name: "Sample"',
                        'site_key: "legacy-site"',
                        "steps:",
                        '  - click: "Apply"',
                    ]
                )
            )

            playbook = load_playbook(str(path))

        self.assertIsNone(playbook.employer_key)
        self.assertEqual(playbook.application_key, "legacy-site")

    def test_unresolved_selector_placeholder_is_rejected(self) -> None:
        with self.assertRaisesRegex(PlaybookError, "unresolved placeholder"):
            self._load_text(
                "\n".join(
                    [
                        "version: 1",
                        "steps:",
                        '  - fill: "Conditional detail"',
                        '    selector: "TODO"',
                        '    value: "answer"',
                    ]
                )
            )

    def test_unresolved_value_placeholder_is_rejected(self) -> None:
        with self.assertRaisesRegex(PlaybookError, "value.*unresolved placeholder"):
            self._load_text(
                "\n".join(
                    [
                        "version: 1",
                        "steps:",
                        '  - press: "Degree discipline"',
                        '    value: "TODO, Enter"',
                    ]
                )
            )

    def test_unresolved_pick_placeholder_is_rejected(self) -> None:
        with self.assertRaisesRegex(PlaybookError, "pick.*unresolved placeholder"):
            self._load_text(
                "\n".join(
                    [
                        "version: 1",
                        "steps:",
                        "  - pick:",
                        '      field: "Answer"',
                        "      source: answer",
                        '      map: {true: "Yes", false: "No"}',
                        '      default: "TODO"',
                    ]
                )
            )

    def test_boolean_modifiers_must_be_booleans(self) -> None:
        with self.assertRaisesRegex(PlaybookError, "optional.*true or false"):
            self._load_text(
                "\n".join(
                    [
                        "version: 1",
                        "steps:",
                        '  - click: "Continue"',
                        '    optional: "false"',
                    ]
                )
            )

    def test_every_parser_action_has_an_engine_handler(self) -> None:
        missing = [kind for kind in ACTION_KEYS if not hasattr(Engine, f"_do_{kind}")]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
