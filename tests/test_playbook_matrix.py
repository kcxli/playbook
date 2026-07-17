from __future__ import annotations

import unittest
from pathlib import Path

from playbook_runner.context import load_context
from playbook_runner.dryrun import analyze
from playbook_runner.api import inspect_playbook
from playbook_runner.parser import load_playbook


ROOT = Path(__file__).resolve().parent.parent
BASE_PROFILE = ROOT / "applicants" / "test.json"
SITE_OVERRIDES = {
    "ua": ROOT / "applicants" / "ua_overrides.json",
    "uci": ROOT / "applicants" / "uci_overrides.json",
    "ucsb": ROOT / "applicants" / "ucsb_overrides.json",
    "umn": ROOT / "applicants" / "umn_overrides.json",
    "yale": ROOT / "applicants" / "yale_overrides.json",
}


class PlaybookMatrixTests(unittest.TestCase):
    def test_every_playbook_has_website_listing_metadata(self) -> None:
        failures = []
        job_ids = set()
        for path in sorted((ROOT / "playbooks").glob("*.playbook.yaml")):
            manifest = inspect_playbook(path)
            if manifest.listing is None:
                failures.append(f"{path.name}: missing listing")
            if not manifest.job_id:
                failures.append(f"{path.name}: missing job_id")
            elif manifest.job_id in job_ids:
                failures.append(f"{path.name}: duplicate job_id {manifest.job_id}")
            else:
                job_ids.add(manifest.job_id)
            if not manifest.intake_key:
                failures.append(f"{path.name}: missing intake.key")

        self.assertEqual(failures, [])

    def test_every_playbook_ends_at_a_human_gate(self) -> None:
        failures: list[str] = []
        for path in sorted((ROOT / "playbooks").glob("*.playbook.yaml")):
            playbook = load_playbook(str(path))
            if playbook.steps[-1].kind != "pause_for_user":
                failures.append(path.name)

        self.assertEqual(
            failures,
            [],
            f"playbooks missing a final pause_for_user step: {failures}",
        )

    def test_known_captcha_playbooks_declare_and_expose_the_requirement(self) -> None:
        marked = set()
        for path in sorted((ROOT / "playbooks").glob("*.playbook.yaml")):
            manifest = inspect_playbook(path)
            if "captcha" in manifest.capabilities:
                marked.add(path.name.removesuffix(".playbook.yaml"))
                playbook = load_playbook(str(path))
                self.assertTrue(
                    any(
                        step.kind == "pause_for_user"
                        and "captcha" in str(step.target).casefold()
                        for step in playbook.steps
                    ),
                    f"{path.name} declares CAPTCHA without a CAPTCHA checkpoint",
                )

        self.assertEqual(marked, {"nyulangone", "utah"})

    def test_every_playbook_validates_with_its_intended_profile(self) -> None:
        playbooks = sorted((ROOT / "playbooks").glob("*.playbook.yaml"))
        self.assertGreater(len(playbooks), 0)

        failures: list[str] = []
        for path in playbooks:
            site = path.name.removesuffix(".playbook.yaml")
            data_paths = [str(BASE_PROFILE)]
            if site in SITE_OVERRIDES:
                data_paths.append(str(SITE_OVERRIDES[site]))

            playbook = load_playbook(str(path))
            context = load_context(data_paths, application_key=playbook.application_key)
            lines, problems = analyze(playbook, context, check_files=True)
            if problems:
                failures.append(f"{path.name}:\n" + "\n".join(lines))

        self.assertEqual(failures, [], "\n\n".join(failures))


if __name__ == "__main__":
    unittest.main()
