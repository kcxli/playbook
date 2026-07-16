from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from playbook_runner.cli import _run
from playbook_runner.context import DataError
from playbook_runner.engine import Engine
from playbook_runner.parser import Step


class HumanPauseTests(unittest.TestCase):
    def test_engine_delegates_pause_to_human_prompt(self) -> None:
        messages: list[str] = []
        engine = Engine(
            {"job": "Example University"},
            human_prompt=messages.append,
        )

        engine._do_pause_for_user(
            Step(kind="pause_for_user", target="Review {{ job }}")
        )

        self.assertEqual(messages, ["Review Example University"])

    def test_headless_engine_rejects_human_pause(self) -> None:
        engine = Engine({}, headless=True, human_prompt=lambda _message: None)

        with self.assertRaisesRegex(DataError, "visible browser"):
            engine._do_pause_for_user(
                Step(kind="pause_for_user", target="Review and submit")
            )

    def test_cli_rejects_live_headless_run_before_browser_launch(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "pause.playbook.yaml"
            path.write_text(
                "\n".join(
                    [
                        "version: 1",
                        "steps:",
                        '  - pause_for_user: "Review and submit manually"',
                    ]
                ),
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = _run([str(path), "--headless"])

        self.assertEqual(result, 2)
        self.assertIn("requires a visible browser", stderr.getvalue())

    def test_cli_allows_headless_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            path = Path(raw_tmp) / "pause.playbook.yaml"
            path.write_text(
                "\n".join(
                    [
                        "version: 1",
                        "steps:",
                        '  - pause_for_user: "Review and submit manually"',
                    ]
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = _run([str(path), "--headless", "--validate"])

        self.assertEqual(result, 0)
        self.assertIn("validation passed", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
