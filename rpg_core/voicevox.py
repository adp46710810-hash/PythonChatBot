from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

try:
    import winsound
except ImportError:  # pragma: no cover - Windows runtime is expected for playback.
    winsound = None


class VoicevoxClient:
    backend_name = "VOICEVOX"
    failure_hint = "is the VOICEVOX engine running?"

    def __init__(
        self,
        host: str,
        port: int,
        speaker: int,
        *,
        timeout_sec: float = 10.0,
    ):
        self.host = host
        self.port = int(port)
        self.speaker = int(speaker)
        self.timeout_sec = float(timeout_sec)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _post(
        self,
        path: str,
        *,
        query: dict[str, Any],
        body: Any = None,
        expect_json: bool = True,
    ) -> Any:
        encoded_query = urllib.parse.urlencode(
            {key: str(value) for key, value in query.items()}
        )
        url = f"{self.base_url}{path}"
        if encoded_query:
            url = f"{url}?{encoded_query}"

        data = b""
        headers: dict[str, str] = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
            payload = response.read()

        if not expect_json:
            return payload
        if not payload:
            return {}
        return json.loads(payload.decode("utf-8"))

    def _get_json(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
            payload = response.read()
        if not payload:
            return {}
        return json.loads(payload.decode("utf-8"))

    def list_speakers(self) -> list[dict[str, Any]]:
        payload = self._get_json("/speakers")
        if not isinstance(payload, list):
            return []
        return [speaker for speaker in payload if isinstance(speaker, dict)]

    def _play_wav(self, audio_bytes: bytes) -> None:
        if winsound is None:
            raise RuntimeError("VOICEVOX playback requires Windows winsound support")
        winsound.PlaySound(audio_bytes, winsound.SND_MEMORY)

    def speak(self, text: str) -> None:
        safe_text = str(text or "").strip()
        if not safe_text:
            return

        query = self._post(
            "/audio_query",
            query={"text": safe_text, "speaker": self.speaker},
        )
        audio_bytes = self._post(
            "/synthesis",
            query={"speaker": self.speaker},
            body=query,
            expect_json=False,
        )
        self._play_wav(audio_bytes)
