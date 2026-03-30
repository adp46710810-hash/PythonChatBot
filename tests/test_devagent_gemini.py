from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from devagent.gemini_provider import (
    DEFAULT_GEMINI_BASE_URL,
    DEFAULT_GEMINI_MODEL,
    GeminiConfig,
    GeminiProvider,
    ProviderError,
    load_gemini_config_from_env,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class GeminiProviderTests(unittest.TestCase):
    def test_load_gemini_config_from_env_uses_defaults(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False):
            config = load_gemini_config_from_env()

        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.api_key, "test-key")
        self.assertEqual(config.model, DEFAULT_GEMINI_MODEL)
        self.assertEqual(config.base_url, DEFAULT_GEMINI_BASE_URL)
        self.assertEqual(config.timeout_sec, 60.0)

    def test_load_gemini_config_from_env_returns_none_without_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = load_gemini_config_from_env()

        self.assertIsNone(config)

    def test_gemini_provider_posts_generate_content_request(self) -> None:
        config = GeminiConfig(
            api_key="test-key",
            model="gemini-test",
            base_url="https://example.invalid/v1beta",
            timeout_sec=12.5,
        )
        provider = GeminiProvider(config)

        def _fake_urlopen(request, timeout):
            self.assertEqual(timeout, 12.5)
            self.assertEqual(
                request.full_url,
                "https://example.invalid/v1beta/models/gemini-test:generateContent",
            )
            self.assertEqual(request.headers["Content-type"], "application/json")
            self.assertEqual(request.headers["X-goog-api-key"], "test-key")

            payload = json.loads(request.data.decode("utf-8"))
            self.assertEqual(payload["contents"][0]["parts"][0]["text"], "Explain TTS")
            self.assertEqual(payload["systemInstruction"]["parts"][0]["text"], "Be terse.")
            return _FakeResponse(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": "1. 要件の理解\n2. 関連ファイル"}]
                            }
                        }
                    ]
                }
            )

        with patch("devagent.gemini_provider.urllib.request.urlopen", side_effect=_fake_urlopen):
            text = provider.ask("Explain TTS", system="Be terse.")

        self.assertIn("要件の理解", text)

    def test_gemini_provider_raises_on_empty_response(self) -> None:
        provider = GeminiProvider(GeminiConfig(api_key="test-key"))

        with patch(
            "devagent.gemini_provider.urllib.request.urlopen",
            return_value=_FakeResponse({"promptFeedback": {"blockReason": "SAFETY"}}),
        ):
            with self.assertRaises(ProviderError) as exc_info:
                provider.ask("Explain TTS", system="Be terse.")

        self.assertIn("SAFETY", str(exc_info.exception))


if __name__ == "__main__":
    unittest.main()
