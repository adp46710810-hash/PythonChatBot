from __future__ import annotations

from typing import Protocol

from app_config import AppConfig
from rpg_core.bouyomi import BouyomiClient
from rpg_core.voicevox import VoicevoxClient


class TTSClient(Protocol):
    backend_name: str
    failure_hint: str

    def speak(self, text: str) -> None: ...


def build_tts_client(config: AppConfig) -> TTSClient:
    provider = str(getattr(config, "tts_provider", "bouyomi") or "bouyomi").strip().lower()
    if provider == "voicevox":
        return build_voicevox_client(config)
    return BouyomiClient(config.bouyomi_host, config.bouyomi_port)


def build_voicevox_client(config: AppConfig, *, speaker: int | None = None) -> VoicevoxClient:
    speaker_id = config.voicevox_speaker if speaker is None else int(speaker)
    return VoicevoxClient(
        config.voicevox_host,
        config.voicevox_port,
        speaker_id,
    )


__all__ = ["TTSClient", "build_tts_client", "build_voicevox_client"]
