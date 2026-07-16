from __future__ import annotations

import unittest

from playbook_runner.dryrun import analyze
from playbook_runner.parser import Playbook, Step


def _playbook(step: Step) -> Playbook:
    return Playbook(
        name="Test",
        url=None,
        job_id=None,
        employer_key=None,
        application_key=None,
        steps=[step],
        raw={},
    )


class DryRunTests(unittest.TestCase):
    def test_pick_without_mapping_or_default_is_a_problem(self) -> None:
        step = Step(
            kind="pick",
            pick={
                "source": "answer",
                "map": {True: "Yes", False: "No"},
                "default": None,
                "as": "select",
                "field": "Answer",
                "group": None,
                "scope": None,
            },
        )

        lines, problems = analyze(_playbook(step), {"answer": None})

        self.assertEqual(problems, 1)
        self.assertIn("matched no map key", "\n".join(lines))

    def test_password_value_is_redacted(self) -> None:
        step = Step(kind="fill", target="Password", value="{{ account.password }}")

        lines, problems = analyze(
            _playbook(step), {"account": {"password": "secret-value"}}
        )

        rendered = "\n".join(lines)
        self.assertEqual(problems, 0)
        self.assertIn("(redacted)", rendered)
        self.assertNotIn("secret-value", rendered)

    def test_human_pause_is_visible_in_plan(self) -> None:
        step = Step(
            kind="pause_for_user",
            target="Review {{ application }} and submit manually.",
        )

        lines, problems = analyze(_playbook(step), {"application": "the form"})

        self.assertEqual(problems, 0)
        self.assertIn(
            "pause_for_user  'Review the form and submit manually.'",
            "\n".join(lines),
        )


if __name__ == "__main__":
    unittest.main()
