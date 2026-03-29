from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

APP_ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=APP_ROOT / ".env")

CONFIG_ENV_WARNINGS: List[str] = []

_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}
_FALSE_ENV_VALUES = {"0", "false", "no", "off"}


def _append_env_warning(name: str, raw_value: str, fallback_value: object) -> None:
    CONFIG_ENV_WARNINGS.append(
        f"{name}={raw_value!r} is invalid. Falling back to {fallback_value!r}."
    )


def _get_env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _get_env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name, "")
    if not raw_value.strip():
        return float(default)

    try:
        return float(raw_value)
    except ValueError:
        _append_env_warning(name, raw_value, default)
        return float(default)


def _get_env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, "")
    if not raw_value.strip():
        return int(default)

    try:
        return int(raw_value)
    except ValueError:
        _append_env_warning(name, raw_value, default)
        return int(default)


def _get_env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name, "")
    if not raw_value.strip():
        return bool(default)

    normalized = raw_value.strip().lower()
    if normalized in _TRUE_ENV_VALUES:
        return True
    if normalized in _FALSE_ENV_VALUES:
        return False

    _append_env_warning(name, raw_value, default)
    return bool(default)


def _get_env_choice(name: str, default: str, allowed: set[str]) -> str:
    raw_value = os.getenv(name, "")
    if not raw_value.strip():
        return str(default)

    normalized = raw_value.strip().lower()
    if normalized in allowed:
        return normalized

    _append_env_warning(name, raw_value, default)
    return str(default)


def _resolve_path(raw_path: str, default_relative: str) -> str:
    candidate = str(raw_path or "").strip()
    if candidate:
        path = Path(candidate)
    else:
        path = APP_ROOT / default_relative

    if not path.is_absolute():
        path = APP_ROOT / path
    return str(path)


def _default_data_file() -> str:
    env_path = os.getenv("BOT_DATA_FILE", "")
    if env_path.strip():
        return _resolve_path(env_path, os.path.join("data", "runtime", "botdata.json"))

    default_path = APP_ROOT / "data" / "runtime" / "botdata.json"
    legacy_path = APP_ROOT / "botdata.json"

    if os.path.exists(default_path):
        return str(default_path)
    if os.path.exists(legacy_path):
        return str(legacy_path)
    return str(default_path)


@dataclass(frozen=True)
class AppConfig:
    client_id: str = field(default_factory=lambda: _get_env_str("TWITCH_CLIENT_ID", ""))
    client_secret: str = field(default_factory=lambda: _get_env_str("TWITCH_CLIENT_SECRET", ""))
    bot_id: str = field(default_factory=lambda: _get_env_str("TWITCH_BOT_ID", ""))
    owner_id: str = field(default_factory=lambda: _get_env_str("TWITCH_OWNER_ID", ""))
    channel: str = field(default_factory=lambda: _get_env_str("TWITCH_CHANNEL", ""))

    prefix: str = "!"
    data_file: str = field(default_factory=_default_data_file)
    detail_overlay_html_file: str = field(
        default_factory=lambda: _resolve_path(
            _get_env_str("DETAIL_OVERLAY_HTML_FILE", ""),
            os.path.join("data", "runtime", "obs_detail_overlay.html"),
        )
    )
    detail_overlay_text_file: str = field(
        default_factory=lambda: _resolve_path(
            _get_env_str("DETAIL_OVERLAY_TEXT_FILE", ""),
            os.path.join("data", "runtime", "obs_detail_overlay.txt"),
        )
    )
    discord_webhook_url: str = field(
        default_factory=lambda: _get_env_str("DISCORD_WEBHOOK_URL", "")
    )
    discord_webhook_username: str = field(
        default_factory=lambda: _get_env_str("DISCORD_WEBHOOK_USERNAME", "Twitch RPG Detail")
    )
    discord_invite_url: str = field(
        default_factory=lambda: _get_env_str("DISCORD_INVITE_URL", "")
    )

    global_reply_cooldown_sec: float = field(
        default_factory=lambda: _get_env_float("BOT_GLOBAL_CD", 2.0)
    )
    user_reply_cooldown_sec: float = field(
        default_factory=lambda: _get_env_float("BOT_USER_CD", 6.0)
    )

    tts_enabled: bool = field(default_factory=lambda: _get_env_bool("TTS_ENABLED", True))
    tts_provider: str = field(
        default_factory=lambda: _get_env_choice(
            "TTS_PROVIDER",
            "bouyomi",
            {"bouyomi", "voicevox"},
        )
    )
    bouyomi_host: str = field(default_factory=lambda: _get_env_str("BOUYOMI_HOST", "127.0.0.1"))
    bouyomi_port: int = field(default_factory=lambda: _get_env_int("BOUYOMI_PORT", 50001))
    voicevox_host: str = field(
        default_factory=lambda: _get_env_str("VOICEVOX_HOST", "127.0.0.1")
    )
    voicevox_port: int = field(default_factory=lambda: _get_env_int("VOICEVOX_PORT", 50021))
    voicevox_speaker: int = field(
        default_factory=lambda: _get_env_int("VOICEVOX_SPEAKER", 1)
    )
    tts_max_len: int = field(default_factory=lambda: _get_env_int("TTS_MAX_LEN", 80))
    tts_cooldown_sec: float = field(
        default_factory=lambda: _get_env_float("TTS_COOLDOWN_SEC", 1.5)
    )


CONFIG = AppConfig()

KEYWORD_RESPONSES: Dict[str, List[str]] = {
    "初見です(๑・◡・๑)": ["先生！来てくだすったんですね！", "初見の職権乱用"],
    "初見です(๑･◡･๑)": ["先生！来てくだすったんですね！", "初見の職権乱用"],
    "疲れた": ["無理するな", "休め"],
    "天才": ["それは言い過ぎ", "気のせい"],
    "こんにちは": ["こんちは！", "やほー"],
}

EMOTE_ECHO_ENABLED = True
EMOTE_ECHO_MIN_INTERVAL_SEC = 12.0

__all__ = ["AppConfig"] + [name for name in globals() if name.isupper()]
