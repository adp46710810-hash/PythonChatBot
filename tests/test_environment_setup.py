from __future__ import annotations

import os
import unittest
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import app_config
import bot
import dev
from rpg_core.storage import JsonFileError, load_json

TEST_TMP_ROOT = Path(__file__).resolve().parent


class ValidateConfigTests(unittest.TestCase):
    def make_config(self, **overrides):
        values = {
            "client_id": "client",
            "client_secret": "secret",
            "bot_id": "bot",
            "owner_id": "owner",
            "channel": "sample_channel",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_validate_config_requires_twitch_channel(self) -> None:
        stderr = StringIO()
        with patch.object(bot, "CONFIG", self.make_config(channel="")):
            with patch("sys.stderr", stderr):
                self.assertFalse(bot.validate_config())

        self.assertIn("TWITCH_CHANNEL", stderr.getvalue())
        self.assertIn(".env.example", stderr.getvalue())

    def test_validate_config_accepts_complete_required_env(self) -> None:
        with patch.object(bot, "CONFIG", self.make_config()):
            self.assertTrue(bot.validate_config())


class EnvironmentSafetyTests(unittest.TestCase):
    def test_app_config_resolves_default_paths_from_project_root(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = app_config.AppConfig()

        project_root = Path(app_config.__file__).resolve().parent
        self.assertEqual(
            Path(config.data_file),
            project_root / "data" / "runtime" / "botdata.json",
        )
        self.assertEqual(
            Path(config.detail_overlay_html_file),
            project_root / "data" / "runtime" / "obs_detail_overlay.html",
        )
        self.assertEqual(
            Path(config.detail_overlay_text_file),
            project_root / "data" / "runtime" / "obs_detail_overlay.txt",
        )

    def test_app_config_resolves_relative_paths_from_project_root(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BOT_DATA_FILE": "custom/runtime.json",
                "DETAIL_OVERLAY_HTML_FILE": "custom/detail.html",
                "DETAIL_OVERLAY_TEXT_FILE": "custom/detail.txt",
            },
            clear=True,
        ):
            config = app_config.AppConfig()

        project_root = Path(app_config.__file__).resolve().parent
        self.assertEqual(Path(config.data_file), project_root / "custom" / "runtime.json")
        self.assertEqual(
            Path(config.detail_overlay_html_file),
            project_root / "custom" / "detail.html",
        )
        self.assertEqual(
            Path(config.detail_overlay_text_file),
            project_root / "custom" / "detail.txt",
        )

    def test_app_config_invalid_optional_values_fall_back_to_defaults(self) -> None:
        original_warnings = list(app_config.CONFIG_ENV_WARNINGS)
        try:
            app_config.CONFIG_ENV_WARNINGS.clear()
            with patch.dict(
                os.environ,
                {
                    "BOT_GLOBAL_CD": "oops",
                    "BOUYOMI_PORT": "bad-port",
                    "TTS_PROVIDER": "unknown",
                    "TTS_ENABLED": "maybe",
                },
                clear=False,
            ):
                config = app_config.AppConfig()

            self.assertEqual(config.global_reply_cooldown_sec, 2.0)
            self.assertEqual(config.bouyomi_port, 50001)
            self.assertEqual(config.tts_provider, "bouyomi")
            self.assertTrue(config.tts_enabled)
            self.assertTrue(
                any("BOT_GLOBAL_CD" in warning for warning in app_config.CONFIG_ENV_WARNINGS)
            )
            self.assertTrue(
                any("BOUYOMI_PORT" in warning for warning in app_config.CONFIG_ENV_WARNINGS)
            )
            self.assertTrue(
                any("TTS_PROVIDER" in warning for warning in app_config.CONFIG_ENV_WARNINGS)
            )
            self.assertTrue(
                any("TTS_ENABLED" in warning for warning in app_config.CONFIG_ENV_WARNINGS)
            )
        finally:
            app_config.CONFIG_ENV_WARNINGS[:] = original_warnings

    def test_validate_optional_env_values_reports_invalid_entries(self) -> None:
        errors = dev.validate_optional_env_values(
            {
                "BOT_GLOBAL_CD": "oops",
                "BOUYOMI_PORT": "abc",
                "TTS_PROVIDER": "mystery",
                "TTS_ENABLED": "sometimes",
            }
        )

        self.assertIn("BOT_GLOBAL_CD='oops'", errors)
        self.assertIn("BOUYOMI_PORT='abc'", errors)
        self.assertIn("TTS_PROVIDER='mystery'", errors)
        self.assertIn("TTS_ENABLED='sometimes'", errors)

    def test_inspect_json_file_reports_invalid_json(self) -> None:
        path = TEST_TMP_ROOT / f"tmp_invalid_botdata_{uuid4().hex}.json"
        try:
            path.write_text("{broken", encoding="utf-8")
            status, note = dev.inspect_json_file(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertEqual(status, "INVALID")
        self.assertIn("line 1", note)

    def test_load_json_raises_for_invalid_json(self) -> None:
        path = TEST_TMP_ROOT / f"tmp_invalid_botdata_{uuid4().hex}.json"
        try:
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(JsonFileError):
                load_json(str(path), default={"users": {}})
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
