from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_TIMEOUT_SEC = 60.0


class ProviderError(RuntimeError):
    """Raised when an external AI provider request fails."""


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str
    model: str = DEFAULT_GEMINI_MODEL
    base_url: str = DEFAULT_GEMINI_BASE_URL
    timeout_sec: float = DEFAULT_TIMEOUT_SEC


def _extract_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        return ""

    chunks: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content", {})
        if not isinstance(content, dict):
            continue
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = str(part.get("text", "")).strip()
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


def _extract_error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error", {})
    if isinstance(error, dict):
        message = str(error.get("message", "")).strip()
        status = str(error.get("status", "")).strip()
        if message and status:
            return f"{status}: {message}"
        if message:
            return message

    prompt_feedback = payload.get("promptFeedback", {})
    if isinstance(prompt_feedback, dict):
        block_reason = str(prompt_feedback.get("blockReason", "")).strip()
        if block_reason:
            return f"Prompt blocked: {block_reason}"

    return ""


def _parse_json_bytes(raw_bytes: bytes) -> dict[str, Any]:
    if not raw_bytes:
        return {}
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_gemini_config_from_env() -> GeminiConfig | None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
    base_url = os.getenv("GEMINI_BASE_URL", DEFAULT_GEMINI_BASE_URL).strip() or DEFAULT_GEMINI_BASE_URL
    timeout_value = os.getenv("GEMINI_TIMEOUT_SEC", "").strip()
    timeout_sec = DEFAULT_TIMEOUT_SEC
    if timeout_value:
        try:
            timeout_sec = max(1.0, float(timeout_value))
        except ValueError:
            timeout_sec = DEFAULT_TIMEOUT_SEC

    return GeminiConfig(
        api_key=api_key,
        model=model,
        base_url=base_url,
        timeout_sec=timeout_sec,
    )


class GeminiProvider:
    def __init__(self, config: GeminiConfig) -> None:
        self.config = config

    def ask(self, prompt: str, *, system: str | None = None) -> str:
        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ]
        }
        if system and system.strip():
            payload["systemInstruction"] = {
                "parts": [{"text": system.strip()}],
            }

        encoded_model = urllib.parse.quote(self.config.model, safe="")
        url = f"{self.config.base_url.rstrip('/')}/models/{encoded_model}:generateContent"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.config.api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_sec) as response:
                raw_bytes = response.read()
        except urllib.error.HTTPError as exc:
            payload = _parse_json_bytes(exc.read())
            message = _extract_error_message(payload) or str(exc)
            raise ProviderError(f"Gemini API request failed ({exc.code}): {message}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Gemini API request failed: {exc}") from exc

        response_payload = _parse_json_bytes(raw_bytes)
        text = _extract_text(response_payload)
        if text:
            return text

        message = _extract_error_message(response_payload)
        if message:
            raise ProviderError(f"Gemini API returned no text: {message}")
        raise ProviderError("Gemini API returned no text response.")
