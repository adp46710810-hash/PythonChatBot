from __future__ import annotations

import unittest
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

from devagent.profile import ProfileError, find_profile_path, load_profile, parse_simple_yaml

TEST_ROOT = Path(__file__).resolve().parent


def _make_temp_dir() -> Path:
    path = TEST_ROOT / f"tmp_devagent_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


class DevAgentProfileTests(unittest.TestCase):
    def test_parse_simple_yaml_supports_scalars_and_lists(self) -> None:
        data = parse_simple_yaml(
            """
name: Sample
root: .
language: python
allowed_tools:
  - list_files
  - read_file
"""
        )

        self.assertEqual(data["name"], "Sample")
        self.assertEqual(data["language"], "python")
        self.assertEqual(data["allowed_tools"], ["list_files", "read_file"])

    def test_load_profile_resolves_root_and_blocks_paths(self) -> None:
        root = _make_temp_dir()
        try:
            profile_path = root / "agent.project.yaml"
            profile_path.write_text(
                """
name: Sample
root: .
language: python
allowed_tools:
  - list_files
allowed_commands:
  - python dev.py test
blocked_paths:
  - .env
  - cache/
""".strip(),
                encoding="utf-8",
            )

            profile = load_profile(profile_path)

            self.assertEqual(profile.root, root.resolve())
            self.assertTrue(profile.is_blocked(root / ".env"))
            self.assertTrue(profile.is_blocked(root / "cache" / "output.txt"))
            self.assertFalse(profile.is_blocked(root / "src" / "main.py"))
        finally:
            rmtree(root, ignore_errors=True)

    def test_find_profile_path_walks_up_parent_directories(self) -> None:
        root = _make_temp_dir()
        try:
            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            (root / "agent.project.yaml").write_text(
                """
name: Sample
root: .
language: python
allowed_tools:
  - list_files
""".strip(),
                encoding="utf-8",
            )

            found = find_profile_path(nested)

            self.assertEqual(found, root / "agent.project.yaml")
        finally:
            rmtree(root, ignore_errors=True)

    def test_load_profile_rejects_missing_allowed_commands_when_run_enabled(self) -> None:
        root = _make_temp_dir()
        try:
            profile_path = root / "agent.project.yaml"
            profile_path.write_text(
                """
name: Sample
root: .
language: python
allowed_tools:
  - run_command
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaises(ProfileError):
                load_profile(profile_path)
        finally:
            rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
