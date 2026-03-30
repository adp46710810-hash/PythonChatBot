from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from devagent.cli import main
from devagent.gemini_provider import GeminiConfig
from devagent.profile import load_profile
from devagent.prompts import build_context_bundle, build_note_prompt, find_related_files


class DevAgentCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile_path = Path(__file__).resolve().parent.parent / "agent.project.yaml"
        self.profile = load_profile(self.profile_path)

    def test_find_related_files_uses_profile_and_query(self) -> None:
        files = find_related_files(self.profile, "TTS", limit=10)
        rendered = {path.as_posix() for path in files}

        self.assertIn("bot_components/chat_listener.py", rendered)
        self.assertIn("app_config.py", rendered)

    def test_build_context_bundle_contains_prompt_notes(self) -> None:
        bundle = build_context_bundle(self.profile, "ワールドボス", include_snippets=False)

        self.assertIn("## Prompt Notes", bundle)
        self.assertIn("外部AIの回答は参考情報として扱い", bundle)

    def test_build_note_prompt_includes_note_article_brief(self) -> None:
        prompt = build_note_prompt(self.profile, "このプロジェクトの紹介記事")

        self.assertIn("## Note Article Brief", prompt)
        self.assertIn("note記事用プロジェクト共有コンテキスト", prompt)
        self.assertIn("このプロジェクトの紹介記事", prompt)

    def test_cli_context_renders_bundle(self) -> None:
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = main(["--profile", str(self.profile_path), "context", "TTS"])

        output = stream.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("## Related Files", output)
        self.assertIn("app_config.py", output)

    def test_cli_run_test_alias_executes_profile_command(self) -> None:
        with patch("devagent.cli.run_allowed_command") as mocked_run:
            mocked_run.return_value = type(
                "Completed",
                (),
                {"stdout": "ok\n", "stderr": "", "returncode": 0},
            )()
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = main(["--profile", str(self.profile_path), "run", "test"])

        self.assertEqual(code, 0)
        mocked_run.assert_called_once_with(self.profile, "python dev.py test")
        self.assertIn("+ python dev.py test", stream.getvalue())

    def test_cli_ask_renders_manual_handoff_prompt(self) -> None:
        stream = io.StringIO()
        with patch("devagent.cli.load_gemini_config_from_env", return_value=None):
            with redirect_stdout(stream):
                code = main(["--profile", str(self.profile_path), "ask", "TTS を改善したい"])

        output = stream.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("[manual handoff]", output)
        self.assertIn("[System]", output)
        self.assertIn("[Prompt]", output)
        self.assertIn("TTS を改善したい", output)

    def test_cli_ask_uses_gemini_when_configured(self) -> None:
        config = GeminiConfig(api_key="test-key", model="gemini-test")
        with patch("devagent.cli.load_gemini_config_from_env", return_value=config):
            with patch("devagent.cli.GeminiProvider") as mocked_provider:
                mocked_provider.return_value.ask.return_value = "1. 要件の理解\n2. 関連ファイル"
                stream = io.StringIO()
                with redirect_stdout(stream):
                    code = main(["--profile", str(self.profile_path), "ask", "TTS を改善したい"])

        self.assertEqual(code, 0)
        mocked_provider.assert_called_once_with(config)
        mocked_provider.return_value.ask.assert_called_once()
        output = stream.getvalue()
        self.assertIn("要件の理解", output)
        self.assertNotIn("[manual handoff]", output)

    def test_cli_challenge_renders_manual_handoff_prompt(self) -> None:
        stream = io.StringIO()
        with patch("devagent.cli.load_gemini_config_from_env", return_value=None):
            with redirect_stdout(stream):
                code = main(["--profile", str(self.profile_path), "challenge", "WBを6分イベントにしたい"])

        output = stream.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("[manual handoff]", output)
        self.assertIn("WBを6分イベントにしたい", output)
        self.assertIn("破綻", output)

    def test_cli_spec_uses_gemini_when_configured(self) -> None:
        config = GeminiConfig(api_key="test-key", model="gemini-test")
        with patch("devagent.cli.load_gemini_config_from_env", return_value=config):
            with patch("devagent.cli.GeminiProvider") as mocked_provider:
                mocked_provider.return_value.ask.return_value = "1. 目的\n2. 既に決まっていること"
                stream = io.StringIO()
                with redirect_stdout(stream):
                    code = main(
                        ["--profile", str(self.profile_path), "spec", "ワールドボスの総合貢献王仕様"]
                    )

        self.assertEqual(code, 0)
        mocked_provider.assert_called_once_with(config)
        mocked_provider.return_value.ask.assert_called_once()
        output = stream.getvalue()
        self.assertIn("既に決まっていること", output)
        self.assertNotIn("[manual handoff]", output)

    def test_cli_note_renders_manual_handoff_prompt(self) -> None:
        stream = io.StringIO()
        with patch("devagent.cli.load_gemini_config_from_env", return_value=None):
            with redirect_stdout(stream):
                code = main(["--profile", str(self.profile_path), "note", "このプロジェクトの紹介記事"])

        output = stream.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("[manual handoff]", output)
        self.assertIn("このプロジェクトの紹介記事", output)
        self.assertIn("書き出し案", output)


if __name__ == "__main__":
    unittest.main()
