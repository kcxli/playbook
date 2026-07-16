from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.accept_equivalence_gap import GapError, promote_gap


class EquivalenceGapToolTests(unittest.TestCase):
    def _write_gap(self, root: Path, **updates) -> Path:
        gap = {
            "kind": "equivalence_gap",
            "wanted": "Job Board",
            "context": "How did you hear about this position?",
            "active_groups": ["decline", "referral", "yes_no"],
            "candidates": [
                {
                    "index": 0,
                    "candidate_index": 7,
                    "label": "Web-based job posting board",
                    "value": "WEB",
                }
            ],
        }
        gap.update(updates)
        path = root / "gap.json"
        path.write_text(json.dumps(gap), encoding="utf-8")
        return path

    def test_promotes_candidate_into_inferred_group(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            target = root / "custom.json"
            gap = self._write_gap(root)

            data, summary = promote_gap(
                gap, candidate_index=7, equivalences_path=target
            )

        self.assertEqual(summary["group"], "referral")
        self.assertIn(
            "Web-based job posting board",
            data["groups"]["referral"]["job board"],
        )

    def test_adds_context_hint_when_explicit_group_is_not_active(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            gap = self._write_gap(
                root,
                wanted="She/her",
                context="Preferred form of address",
                active_groups=["decline", "yes_no"],
                candidates=[
                    {
                        "index": 0,
                        "candidate_index": 2,
                        "label": "She/Her/Hers",
                        "value": "2",
                    }
                ],
            )

            data, summary = promote_gap(
                gap,
                candidate_index=2,
                group="pronouns",
                equivalences_path=root / "custom.json",
            )

        self.assertEqual(summary["context_hint"], "Preferred form of address")
        self.assertIn("Preferred form of address", data["context_hints"]["pronouns"])

    def test_rejects_alias_already_assigned_elsewhere(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            target = root / "custom.json"
            target.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "groups": {
                            "referral": {
                                "employee referral": ["Web-based job posting board"]
                            }
                        },
                        "context_hints": {},
                    }
                ),
                encoding="utf-8",
            )
            gap = self._write_gap(root)

            with self.assertRaises(GapError):
                promote_gap(gap, candidate_index=7, equivalences_path=target)

    def test_documented_script_invocation_works(self) -> None:
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            [sys.executable, "tools/accept_equivalence_gap.py", "--help"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--candidate-index", result.stdout)


if __name__ == "__main__":
    unittest.main()
