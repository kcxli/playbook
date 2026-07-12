from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from playbook_runner.parser import load_playbook


class ParserTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
