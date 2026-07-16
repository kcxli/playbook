from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from playbook_runner.artifacts import append_private_text, write_private_text


@unittest.skipIf(os.name == "nt", "POSIX permission bits are not portable to Windows")
class ArtifactTests(unittest.TestCase):
    def test_private_writes_use_owner_only_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            target = Path(raw_tmp) / "nested" / "artifact.txt"
            write_private_text(target, "first\n")
            append_private_text(target, "second\n")

            file_mode = target.stat().st_mode & 0o777
            directory_mode = target.parent.stat().st_mode & 0o777
            contents = target.read_text(encoding="utf-8")

        self.assertEqual(file_mode, 0o600)
        self.assertEqual(directory_mode, 0o700)
        self.assertEqual(contents, "first\nsecond\n")


if __name__ == "__main__":
    unittest.main()
