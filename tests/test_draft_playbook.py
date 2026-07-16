from __future__ import annotations

import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parent.parent


class DraftPlaybookTests(unittest.TestCase):
    def test_generated_draft_ends_at_human_gate(self) -> None:
        module = runpy.run_path(str(ROOT / "tools" / "draft_playbook.py"))
        build_draft = module["build_draft"]
        args = SimpleNamespace(
            name="Example Application",
            url="https://example.test/apply",
            job_id="example-1",
            include_hidden=False,
            buttons="comments",
            todo_prefix="answers",
        )

        rendered = build_draft(
            [{"title": "Example", "url": args.url, "controls": {}}],
            args,
        )

        active_steps = [
            line.strip() for line in rendered.splitlines() if line.startswith("  - ")
        ]
        self.assertTrue(active_steps[-1].startswith("- pause_for_user:"))
        self.assertIn("final submission always remains manual", rendered)


if __name__ == "__main__":
    unittest.main()
