from __future__ import annotations

import asyncio
import copy
import logging
import random
import re
import sys
from typing import Any, Awaitable, Dict, List, Optional, Tuple

import twitchio
from twitchio import eventsub
from twitchio.ext import commands

from app_config import CONFIG, CONFIG_ENV_WARNINGS
from bot_components import BasicCommands, NonCommandChat
from rpg_core.detail_overlay import DetailOverlayWriter
from rpg_core.discord_notifier import DiscordWebhookNotifier
from rpg_core.exploration_result import sanitize_return_info
from rpg_core.manager import RPGManager
from rpg_core.storage import JsonFileError, atomic_save_json, load_json
from rpg_core.tts import build_tts_client, build_voicevox_client
from rpg_core.tts_normalizer import normalize_rpg_tts_text
from rpg_core.utils import nfkc, now_ts


class StreamBot(commands.Bot):
    _AUTO_FINALIZE_SKIP_COMMANDS = {
        "探索結果",
        "claim",
        "result",
        "探索詳細",
        "explore_detail",
        "detail",
        "戦闘詳細",
        "battle_detail",
        "自動周回停止",
        "autostop",
        "loopstop",
    }
    _AUTO_FINALIZE_SKIP_SUBCOMMANDS = {
        "探索": {
            "結果",
            "result",
            "claim",
            "詳細",
            "detail",
            "戦闘",
            "battle",
            "battle_detail",
            "停止",
            "stop",
        },
    }
    _WORLD_BOSS_SPAWN_TTS_LINES = (
        "{boss_name} が湧いたぞ。寝てる雑魚は叩き起きろ",
        "ワールドボス {boss_name} だ。のろまは置いてくぞ",
        "{boss_name} 出現。腑抜けた面してないで来い",
    )
    _WORLD_BOSS_START_TTS_LINES = (
        "{boss_name} 戦開始。ぼさっとした雑魚から床を舐めるぞ",
        "{boss_name} が暴れ始めた。間抜けは吹き飛ばされるぞ",
        "開戦だ。手が遅い役立たずは後ろで震えてろ",
    )
    _WORLD_BOSS_JOIN_WARNING_TTS_LINES = (
        "開始まであと10秒。のろまは今すぐ滑り込め",
        "あと10秒。寝ぼけた雑魚は置いてくぞ",
        "残り10秒。間に合わない腑抜けは知らん",
    )
    _WORLD_BOSS_BATTLE_WARNING_TTS_LINES = (
        "残り30秒。手ぇ止めてる間抜けは戦犯だ",
        "あと30秒。火力のない雑魚は本気出せ",
        "残り30秒。もたもたした役立たずは置いてくぞ",
    )
    _WORLD_BOSS_AOE_TTS_LINES = (
        "{boss_name} の怒りの全体攻撃が炸裂した。鈍い雑魚は立て直せ",
        "{boss_name} の全体攻撃を叩き込まれたぞ。間抜けは今すぐ態勢を戻せ",
        "{boss_name} が範囲ごと薙ぎ払った。腑抜けは崩れる前に立て直せ",
    )
    _WORLD_BOSS_ENRAGE_TTS_LINES = (
        "{boss_name} が激昂した。半端者から順に潰されるぞ",
        "{boss_name} がキレたぞ。腰の引けた雑魚は沈む",
        "{boss_name} 激昂。間抜けな被弾はもう笑えない",
    )
    _WORLD_BOSS_CANCEL_TTS_LINES = (
        "{boss_name} は去ったぞ。集まれない雑魚しかいなかったな",
        "{boss_name} 戦は中止だ。腑抜けしかいなくて話にならん",
        "{boss_name} は消えた。のろましかいないとこうなる",
    )
    _WORLD_BOSS_CLEAR_TTS_LINES = (
        "{boss_name} 討伐成功。口だけじゃないところは見せたな",
        "{boss_name} 撃破。雑魚扱いはひとまず保留にしてやる",
        "{boss_name} を沈めたぞ。普段よりはマシだったな",
    )
    _WORLD_BOSS_MVP_TTS_LINES = (
        "MVPは {name}。他の雑魚は背中だけ見てろ",
        "{name} がMVPだ。役立たずどもは見習え",
        "MVP {name}。他の連中は爪の垢でも飲め",
    )
    _WORLD_BOSS_TIMEOUT_TTS_LINES = (
        "{boss_name} は逃がした。ぬるい火力で何してた",
        "{boss_name} 時間切れ。雑魚火力の見本市だったな",
        "{boss_name} を取り逃がした。もたついた連中は反省会だ",
    )
    _WORLD_BOSS_TOP_CONTRIBUTOR_TTS_LINES = (
        "最多貢献は {name}。他は足を引っ張るな",
        "{name} が一番働いてた。残りは置物か",
        "最多貢献 {name}。役立たずどもは手数を見習え",
    )

    _DISCORD_WORLD_BOSS_BATTLE_LOGS_ENABLED = False

    def __init__(self) -> None:
        super().__init__(
            client_id=CONFIG.client_id,
            client_secret=CONFIG.client_secret,
            bot_id=CONFIG.bot_id,
            owner_id=CONFIG.owner_id,
            prefix=CONFIG.prefix,
            initial_channels=[CONFIG.channel] if CONFIG.channel else [],
            enable_commands=True,
        )

        self.log = logging.getLogger("StreamBot")

        loaded_data = load_json(CONFIG.data_file, default={"users": {}})
        self.data = loaded_data if isinstance(loaded_data, dict) else {"users": {}}
        self.rpg = RPGManager(self.data, owner_username=CONFIG.channel)

        self._global_last_reply_ts = 0.0
        self._user_last_reply_ts: Dict[str, float] = {}
        self._user_last_emote_echo_ts: Dict[str, float] = {}

        self._chat_tts = build_tts_client(CONFIG)
        self._rpg_tts = build_voicevox_client(
            CONFIG,
            speaker=self.get_rpg_voicevox_speaker_id(),
        )
        self._tts_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self._tts_stop = asyncio.Event()
        self._tts_task: Optional[asyncio.Task] = None
        self._tts_last_ts = 0.0

        self._exploration_stop = asyncio.Event()
        self._exploration_task: Optional[asyncio.Task] = None
        self._detail_overlay = DetailOverlayWriter(
            CONFIG.detail_overlay_html_file,
            CONFIG.detail_overlay_text_file,
        )
        self._discord_notifier = DiscordWebhookNotifier(
            CONFIG.discord_webhook_url,
            username=CONFIG.discord_webhook_username,
        )
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._world_boss_visual_refresh_sec = 2.0
        self._world_boss_visual_last_refresh_ts = 0.0
        self._world_boss_visual_last_phase = "idle"
        self._world_boss_discord_logs_initialized = False
        self._world_boss_discord_last_recent_logs: List[str] = []
        self._world_boss_discord_last_phase = "idle"

    def save_data(self) -> None:
        try:
            atomic_save_json(CONFIG.data_file, self.data)
        except Exception:
            self.log.exception("Failed to save data")

    def show_detail_overlay(
        self,
        title: str,
        lines: List[str],
        *,
        include_world_boss_variant: bool = True,
    ) -> None:
        try:
            self._detail_overlay.show(
                title,
                lines,
                include_world_boss_variant=include_world_boss_variant,
            )
        except Exception:
            self.log.exception("Failed to update detail overlay")

    def _get_tts_settings(self) -> Dict[str, Any]:
        settings = self.data.get("tts_settings")
        if isinstance(settings, dict):
            return settings

        settings = {}
        self.data["tts_settings"] = settings
        return settings

    def get_rpg_voicevox_speaker_id(self) -> int:
        settings = self._get_tts_settings()
        raw_value = settings.get("rpg_voicevox_speaker")
        try:
            return max(0, int(raw_value))
        except (TypeError, ValueError):
            return max(0, int(CONFIG.voicevox_speaker))

    def get_rpg_voicevox_speaker_label(self) -> str:
        settings = self._get_tts_settings()
        label = nfkc(str(settings.get("rpg_voicevox_speaker_label", "") or "")).strip()
        if label:
            return label
        return f"VOICEVOX ID {self.get_rpg_voicevox_speaker_id()}"

    def get_discord_invite_url(self) -> str:
        return str(CONFIG.discord_invite_url or "").strip()

    def set_rpg_voicevox_speaker_id(self, speaker_id: int, *, label: Optional[str] = None) -> int:
        safe_speaker_id = max(0, int(speaker_id))
        settings = self._get_tts_settings()
        settings["rpg_voicevox_speaker"] = safe_speaker_id
        safe_label = nfkc(str(label or "")).strip()
        if safe_label:
            settings["rpg_voicevox_speaker_label"] = safe_label
        else:
            settings.pop("rpg_voicevox_speaker_label", None)
        self._rpg_tts.speaker = safe_speaker_id
        return safe_speaker_id

    def _normalize_voicevox_query(self, text: str) -> str:
        normalized = nfkc(str(text or "")).strip().lower()
        normalized = re.sub(r"[／/()（）・,_-]+", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def _choose_default_voicevox_style(
        self,
        entries: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not entries:
            return None

        for preferred_style_name in ("ノーマル", "normal"):
            normalized_preferred = self._normalize_voicevox_query(preferred_style_name)
            for entry in entries:
                if self._normalize_voicevox_query(str(entry.get("style_name", ""))) == normalized_preferred:
                    return entry
        return entries[0]

    def list_rpg_voicevox_styles(self) -> List[Dict[str, Any]]:
        fetcher = getattr(self._rpg_tts, "list_speakers", None)
        if not callable(fetcher):
            raise RuntimeError("RPG VOICEVOX backend does not support speaker listing")

        speakers = fetcher()
        entries: List[Dict[str, Any]] = []
        for speaker in speakers:
            if not isinstance(speaker, dict):
                continue

            speaker_name = nfkc(str(speaker.get("name", "") or "")).strip()
            styles = speaker.get("styles")
            if not speaker_name or not isinstance(styles, list):
                continue

            for style in styles:
                if not isinstance(style, dict):
                    continue
                try:
                    style_id = max(0, int(style.get("id")))
                except (TypeError, ValueError):
                    continue

                style_name = nfkc(str(style.get("name", "") or "")).strip() or "ノーマル"
                label = (
                    speaker_name
                    if not style_name
                    else f"{speaker_name} / {style_name}"
                )
                search_text = self._normalize_voicevox_query(
                    " ".join(
                        [
                            speaker_name,
                            style_name,
                            label,
                            f"{speaker_name}{style_name}",
                        ]
                    )
                )
                entries.append(
                    {
                        "speaker_name": speaker_name,
                        "style_name": style_name,
                        "style_id": style_id,
                        "label": label,
                        "search_text": search_text,
                    }
                )
        return entries

    def find_rpg_voicevox_style(
        self,
        query: str,
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        normalized_query = self._normalize_voicevox_query(query)
        if not normalized_query:
            return None, []

        entries = self.list_rpg_voicevox_styles()

        exact_speaker_matches = [
            entry
            for entry in entries
            if normalized_query == self._normalize_voicevox_query(str(entry.get("speaker_name", "")))
        ]
        if exact_speaker_matches:
            return (
                self._choose_default_voicevox_style(exact_speaker_matches),
                exact_speaker_matches,
            )

        exact_label_matches = [
            entry
            for entry in entries
            if normalized_query
            in {
                self._normalize_voicevox_query(str(entry.get("label", ""))),
                self._normalize_voicevox_query(
                    f"{entry.get('speaker_name', '')} {entry.get('style_name', '')}"
                ),
                self._normalize_voicevox_query(
                    f"{entry.get('speaker_name', '')}{entry.get('style_name', '')}"
                ),
            }
        ]
        if len(exact_label_matches) == 1:
            return exact_label_matches[0], exact_label_matches
        if exact_label_matches:
            return None, exact_label_matches

        exact_style_matches = [
            entry
            for entry in entries
            if normalized_query == self._normalize_voicevox_query(str(entry.get("style_name", "")))
        ]
        if len(exact_style_matches) == 1:
            return exact_style_matches[0], exact_style_matches
        if exact_style_matches:
            return None, exact_style_matches

        partial_matches = [
            entry
            for entry in entries
            if normalized_query in str(entry.get("search_text", ""))
        ]
        if not partial_matches:
            return None, []

        matched_speakers = {
            self._normalize_voicevox_query(str(entry.get("speaker_name", "")))
            for entry in partial_matches
        }
        if len(matched_speakers) == 1:
            return self._choose_default_voicevox_style(partial_matches), partial_matches
        if len(partial_matches) == 1:
            return partial_matches[0], partial_matches
        return None, partial_matches

    def _build_world_boss_ranking_summary(self, ranking: List[Dict[str, Any]]) -> str:
        entries = [entry for entry in ranking if isinstance(entry, dict)]
        if not entries:
            return ""

        parts = []
        for entry in entries[:5]:
            rank = max(1, int(entry.get("rank", 0)))
            name = str(entry.get("display_name", "?") or "?").strip() or "?"
            damage = max(0, int(entry.get("total_damage", 0)))
            parts.append(f"#{rank} {name} {damage}")
        return " / ".join(parts)

    def _build_world_boss_visual_overlay(self) -> tuple[str, List[str], str]:
        status = self.rpg.get_world_boss_status()
        phase = str(status.get("phase", "idle") or "idle").strip()
        boss = status.get("boss", {}) if isinstance(status, dict) else {}
        boss_name = str(boss.get("name", "WB") or "WB").strip() or "WB"
        boss_title = str(boss.get("title", "") or "").strip()
        participants = max(0, int(status.get("participants", 0) or 0))
        ranking_text = self._build_world_boss_ranking_summary(status.get("ranking", []))
        recent_logs = [
            str(line).strip()
            for line in status.get("recent_logs", [])
            if str(line).strip()
        ]

        title = f"ワールドボス / {boss_name}"
        lines = ["section: ワールドボス"]

        if phase == "recruiting":
            remain = max(0, int(float(status.get("join_ends_at", 0.0) or 0.0) - now_ts()))
            lines.extend(
                [
                    (
                        f"kv: WB | {boss_name}"
                        if not boss_title
                        else f"kv: WB | {boss_name} / {boss_title}"
                    ),
                    f"kv: 状態 | 募集中 / 残り {self.rpg.format_duration(remain)}",
                    f"kv: 参加人数 | {participants}人",
                ]
            )
        elif phase == "active":
            current_hp = max(0, int(status.get("current_hp", 0) or 0))
            max_hp = max(1, int(status.get("max_hp", 1) or 1))
            remain = max(0, int(float(status.get("ends_at", 0.0) or 0.0) - now_ts()))
            hp_pct = int(round((current_hp / max_hp) * 100))
            lines.extend(
                [
                    (
                        f"kv: WB | {boss_name}"
                        if not boss_title
                        else f"kv: WB | {boss_name} / {boss_title}"
                    ),
                    f"kv: 状態 | 戦闘中 / 残り {self.rpg.format_duration(remain)}",
                    f"kv: 参加人数 | {participants}人",
                    f"kv: HP | {current_hp}/{max_hp} ({hp_pct}%)",
                ]
            )
        elif phase == "cooldown":
            remain = max(0, int(float(status.get("cooldown_ends_at", 0.0) or 0.0) - now_ts()))
            lines.append(
                f"kv: 状態 | クールダウン / 残り {self.rpg.format_duration(remain)}"
            )
        else:
            lines.append("kv: 状態 | 待機中")

        if phase in {"recruiting", "active"} and ranking_text:
            lines.append(f"kv: 順位 | {ranking_text}")
        if phase in {"recruiting", "active"} and recent_logs:
            lines.append("section: 直近ログ")
            for index, log_line in enumerate(recent_logs[-5:], start=1):
                lines.append(f"kv: {index} | {log_line}")

        return title, lines, phase

    def refresh_world_boss_visual_html(self, *, force: bool = False) -> None:
        now = now_ts()
        last_refresh = float(getattr(self, "_world_boss_visual_last_refresh_ts", 0.0) or 0.0)
        last_phase = str(getattr(self, "_world_boss_visual_last_phase", "idle") or "idle")
        refresh_sec = float(getattr(self, "_world_boss_visual_refresh_sec", 2.0) or 2.0)
        title, lines, phase = self._build_world_boss_visual_overlay()
        stage_visible = phase in {"recruiting", "active"}
        stage_was_visible = last_phase in {"recruiting", "active"}
        phase_changed = phase != last_phase
        refresh_due = (now - last_refresh) >= refresh_sec

        should_refresh = force
        if not should_refresh and stage_visible:
            should_refresh = phase_changed or refresh_due or not stage_was_visible
        if not should_refresh and (stage_was_visible or phase_changed):
            should_refresh = True
        if not should_refresh:
            return

        try:
            self._detail_overlay.show_wb_html(title, lines)
        except Exception:
            self.log.exception("Failed to update world boss visual overlay")
            return

        self._world_boss_visual_last_refresh_ts = now
        self._world_boss_visual_last_phase = phase

    def publish_detail_response(self, title: str, lines: List[str]) -> None:
        if not self._discord_notifier.enabled:
            self.show_detail_overlay(title, lines)
            return
        self._schedule_background_task(
            self._discord_notifier.send_detail(title, lines),
            name=f"discord_detail:{title}",
        )

    def _build_world_boss_spawn_notification(self, headline: str) -> tuple[str, List[str]]:
        status = self.rpg.get_world_boss_status()
        boss = status.get("boss", {}) if isinstance(status, dict) else {}
        boss_name = str(boss.get("name", "WB") or "WB").strip() or "WB"
        boss_title = str(boss.get("title", "") or "").strip()
        participants = max(0, int(status.get("participants", 0) or 0))
        remain = max(0, int(float(status.get("join_ends_at", 0.0) or 0.0) - now_ts()))
        recent_logs = [
            str(line).strip()
            for line in status.get("recent_logs", [])
            if str(line).strip()
        ]

        title = f"ワールドボス出現 / {boss_name}"
        lines = [
            "section: ワールドボス通知",
            f"alert: kv: 通知 | {headline}",
            f"kv: WB | {boss_name}" if not boss_title else f"kv: WB | {boss_name} / {boss_title}",
            "kv: 状態 | 募集中",
            f"kv: 参加人数 | {participants}人",
            f"kv: 募集残り | {self.rpg.format_duration(remain)}",
            "alert: kv: 参加 | !wb 参加",
            "kv: 確認 | !wb / !wb ランキング",
        ]
        if recent_logs:
            lines.append("section: 直近ログ")
            for index, log_line in enumerate(recent_logs[-3:], start=1):
                lines.append(f"kv: {index} | {log_line}")
        return title, lines

    def publish_world_boss_spawn_notification(self, headline: str) -> None:
        title, lines = self._build_world_boss_spawn_notification(headline)
        # The dedicated WB visual overlay is refreshed separately, so avoid
        # rewriting the WB split output a second time for the spawn card.
        self.show_detail_overlay(
            title,
            lines,
            include_world_boss_variant=False,
        )
        self.maybe_enqueue_world_boss_spawn_tts(headline)
        if not self._discord_notifier.enabled:
            return
        self._schedule_background_task(
            self._discord_notifier.send_detail(title, lines),
            name=f"discord_world_boss:{title}",
        )

    def _diff_world_boss_recent_logs(
        self,
        previous_logs: List[str],
        current_logs: List[str],
    ) -> List[str]:
        safe_previous = [str(line).strip() for line in previous_logs if str(line).strip()]
        safe_current = [str(line).strip() for line in current_logs if str(line).strip()]
        if not safe_current:
            return []
        if not safe_previous:
            return list(safe_current)

        overlap = 0
        max_overlap = min(len(safe_previous), len(safe_current))
        for size in range(max_overlap, 0, -1):
            if safe_previous[-size:] == safe_current[:size]:
                overlap = size
                break
        return safe_current[overlap:]

    def _filter_world_boss_discord_battle_logs(self, log_lines: List[str]) -> List[str]:
        filtered: List[str] = []
        for raw_line in log_lines:
            line = str(raw_line).strip()
            if not line:
                continue
            if re.match(r"^T\d+:", line):
                filtered.append(line)
                continue
            if line.startswith(
                (
                    "戦闘開始:",
                    "途中参加:",
                    "復帰:",
                    "WB攻撃:",
                    "WB撃破:",
                    "WB全体攻撃:",
                    "攻撃参加者なし",
                    "討伐成功:",
                    "時間切れ:",
                )
            ):
                filtered.append(line)
        return filtered

    def _build_world_boss_battle_log_notification(
        self,
        log_lines: List[str],
        *,
        status: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, List[str]]:
        safe_logs = [str(line).strip() for line in log_lines if str(line).strip()]
        if len(safe_logs) > 4:
            omitted = len(safe_logs) - 4
            safe_logs = [f"...ほか{omitted}件", *safe_logs[-4:]]

        if not isinstance(status, dict):
            status = self.rpg.get_world_boss_status()
        boss = status.get("boss", {}) if isinstance(status, dict) else {}
        phase = str(status.get("phase", "idle") or "idle").strip()
        boss_name = str(boss.get("name", "WB") or "WB").strip() or "WB"
        boss_title = str(boss.get("title", "") or "").strip()
        participants = max(0, int(status.get("participants", 0) or 0))
        title = f"ワールドボス戦況 / {boss_name}"

        lines = [
            f"WB: {boss_name}" if not boss_title else f"WB: {boss_name} / {boss_title}",
        ]
        if phase == "active":
            current_hp = max(0, int(status.get("current_hp", 0) or 0))
            max_hp = max(1, int(status.get("max_hp", 1) or 1))
            remain = max(0, int(float(status.get("ends_at", 0.0) or 0.0) - now_ts()))
            hp_pct = int(round((current_hp / max_hp) * 100))
            lines.append(f"状況: 戦闘中 / 残り {self.rpg.format_duration(remain)}")
            lines.append(f"HP: {current_hp}/{max_hp} ({hp_pct}%) / 参加 {participants}人")
        elif phase == "cooldown":
            remain = max(0, int(float(status.get("cooldown_ends_at", 0.0) or 0.0) - now_ts()))
            last_result = status.get("last_result", {}) if isinstance(status, dict) else {}
            if isinstance(last_result, dict) and last_result:
                result_label = "討伐成功" if bool(last_result.get("cleared", False)) else "時間切れ"
                lines.append(f"状況: 戦闘終了 / {result_label} / 残り {self.rpg.format_duration(remain)}")
            else:
                lines.append(f"状況: 戦闘終了 / 残り {self.rpg.format_duration(remain)}")
            lines.append(f"参加: {participants}人")
        else:
            phase_label = {
                "recruiting": "募集中",
                "idle": "待機中",
            }.get(phase, "状況更新")
            lines.append(f"状況: {phase_label}")
            lines.append(f"参加: {participants}人")

        lines.append("ログ:")
        lines.extend(f"- {line}" for line in safe_logs)
        return title, lines

    def publish_world_boss_battle_log_updates(self) -> None:
        try:
            status = self.rpg.get_world_boss_status()
        except Exception:
            return

        phase = str(status.get("phase", "idle") or "idle").strip()
        recent_logs = [
            str(line).strip()
            for line in status.get("recent_logs", [])
            if str(line).strip()
        ]
        initialized = bool(getattr(self, "_world_boss_discord_logs_initialized", False))
        previous_logs = list(getattr(self, "_world_boss_discord_last_recent_logs", []))

        if not initialized:
            self._world_boss_discord_logs_initialized = True
            self._world_boss_discord_last_recent_logs = recent_logs
            self._world_boss_discord_last_phase = phase
            return

        new_logs = StreamBot._diff_world_boss_recent_logs(self, previous_logs, recent_logs)
        self._world_boss_discord_last_recent_logs = recent_logs
        self._world_boss_discord_last_phase = phase
        if not new_logs:
            return

        filtered_logs = StreamBot._filter_world_boss_discord_battle_logs(self, new_logs)
        if filtered_logs:
            try:
                StreamBot.maybe_enqueue_world_boss_log_tts(self, filtered_logs, status=status)
            except Exception:
                self.log.exception("Failed to enqueue world boss battle-log TTS")

        if (
            not self._discord_notifier.enabled
            or not getattr(
                self,
                "_DISCORD_WORLD_BOSS_BATTLE_LOGS_ENABLED",
                StreamBot._DISCORD_WORLD_BOSS_BATTLE_LOGS_ENABLED,
            )
        ):
            return

        if not filtered_logs:
            return

        title, lines = StreamBot._build_world_boss_battle_log_notification(
            self,
            filtered_logs,
            status=status,
        )
        self._schedule_background_task(
            self._discord_notifier.send_detail(title, lines),
            name=f"discord_world_boss_battle:{title}",
        )

    def get_detail_destination_label(self) -> str:
        return "Discord" if self._discord_notifier.enabled else "OBS"

    def _schedule_background_task(
        self,
        coroutine: Awaitable[None],
        *,
        name: str,
    ) -> None:
        try:
            task = asyncio.create_task(coroutine, name=name)
        except RuntimeError:
            return

        self._background_tasks.add(task)

        def _on_done(done_task: asyncio.Task[None]) -> None:
            self._background_tasks.discard(done_task)
            try:
                done_task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                self.log.exception("Background task failed: %s", name)

        task.add_done_callback(_on_done)

    def can_reply(self, username: str) -> bool:
        ts = now_ts()

        if ts - self._global_last_reply_ts < CONFIG.global_reply_cooldown_sec:
            return False

        last_u = self._user_last_reply_ts.get(username.lower(), 0.0)
        if ts - last_u < CONFIG.user_reply_cooldown_sec:
            return False

        self.note_reply(username, ts=ts)
        return True

    def note_reply(self, username: Optional[str] = None, *, ts: Optional[float] = None) -> None:
        stamp = now_ts() if ts is None else ts
        self._global_last_reply_ts = stamp
        if username:
            self._user_last_reply_ts[username.lower()] = stamp

    def tts_sanitize(self, author: str, text: str) -> Optional[str]:
        if not CONFIG.tts_enabled:
            return None
        if not text:
            return None
        if text.strip().startswith(CONFIG.prefix):
            return None

        if re.search(r"https?://\S+", text, re.IGNORECASE):
            return None

        t = nfkc(text).strip()
        if not t:
            return None

        if len(t) > CONFIG.tts_max_len:
            t = t[:CONFIG.tts_max_len] + "…"

        t = re.sub(r"\s+", " ", t)
        return t

    def _enqueue_tts(self, channel: str, author: str, text: str) -> None:
        tts = self.tts_sanitize(author, text)
        if not tts:
            return
        if channel == "rpg":
            tts = normalize_rpg_tts_text(tts)
            if not tts:
                return

        try:
            self._tts_queue.put_nowait((channel, tts))
        except Exception:
            self.log.exception("Failed to enqueue %s TTS message", channel)

    def enqueue_chat_tts_message(self, author: str, text: str) -> None:
        self._enqueue_tts("chat", author, text)

    def enqueue_tts_message(self, text: str) -> None:
        self._enqueue_tts("rpg", "", text)

    def maybe_enqueue_legendary_drop_tts(
        self,
        display_name: Optional[str],
        result: Optional[Dict[str, Any]],
    ) -> None:
        if not self.rpg.has_legendary_drop(result):
            return

        safe_display_name = nfkc(display_name or "").strip()
        if safe_display_name:
            self.enqueue_tts_message(f"{safe_display_name}さんがレジェンダリー装備をドロップしました")
            return
        self.enqueue_tts_message("レジェンダリー装備がドロップしました")

    def maybe_enqueue_boss_clear_tts(
        self,
        display_name: Optional[str],
        result: Optional[Dict[str, Any]],
    ) -> None:
        if not isinstance(result, dict):
            return

        safe_display_name = nfkc(display_name or "").strip()
        newly_cleared_boss_areas = result.get("newly_cleared_boss_areas")
        if not isinstance(newly_cleared_boss_areas, list):
            return

        for area_name in newly_cleared_boss_areas:
            safe_area_name = nfkc(str(area_name or "")).strip()
            if not safe_area_name:
                continue
            if safe_display_name:
                self.enqueue_tts_message(
                    f"{safe_display_name}さんが{safe_area_name}のボスを撃破しました"
                )
                continue
            self.enqueue_tts_message(f"{safe_area_name}のボスを撃破しました")

    def _choose_world_boss_tts_line(
        self,
        templates: tuple[str, ...],
        **values: str,
    ) -> Optional[str]:
        candidates = []
        for template in templates:
            safe_template = str(template or "").strip()
            if not safe_template:
                continue
            try:
                line = safe_template.format(**values).strip()
            except KeyError:
                continue
            if line:
                candidates.append(line)
        if not candidates:
            return None
        return random.choice(candidates)

    def _extract_world_boss_name_for_tts(self, source: Optional[str]) -> str:
        safe_source = nfkc(str(source or "")).strip()
        boss_name = ""

        try:
            status = self.rpg.get_world_boss_status()
        except Exception:
            status = {}
        boss = status.get("boss", {}) if isinstance(status, dict) else {}
        boss_name = nfkc(str(boss.get("name", "") or "")).strip()
        if boss_name:
            return boss_name

        if safe_source.startswith("WB激昂 / "):
            remainder = safe_source[len("WB激昂 / ") :].strip()
            return nfkc(remainder.removesuffix(" の攻撃が激化")).strip()

        parts = [nfkc(part).strip() for part in safe_source.split("/")]
        if safe_source.startswith("WB中止 / 参加者なし / ") and len(parts) >= 3:
            return parts[2]
        if safe_source.startswith(
            (
                "WB募集開始 / ",
                "WB開始 / ",
                "WB討伐成功 / ",
                "WB時間切れ / ",
            )
        ) and len(parts) >= 2:
            return parts[1]
        return ""

    def _extract_world_boss_actor_name_for_tts(self, source: Optional[str], prefix: str) -> str:
        safe_source = nfkc(str(source or "")).strip()
        if not safe_source.startswith(prefix):
            return ""
        remainder = safe_source[len(prefix) :].strip()
        if not remainder:
            return ""
        return nfkc(remainder.split("/")[0]).strip()

    def _is_world_boss_battle_tts_message(self, message: Optional[str]) -> bool:
        safe_message = nfkc(str(message or "")).strip()
        if not safe_message:
            return False

        # Keep chat announcements, but skip VOICEVOX battle callouts.
        return (
            "怒りの全体攻撃" in safe_message
            or safe_message.startswith("WB全体攻撃: ")
            or safe_message.startswith("WB激昂 / ")
        )

    def build_world_boss_tts_message(self, message: Optional[str]) -> Optional[str]:
        safe_message = nfkc(str(message or "")).strip()
        if not safe_message:
            return None
        if StreamBot._is_world_boss_battle_tts_message(self, safe_message):
            return None

        boss_name = StreamBot._extract_world_boss_name_for_tts(self, safe_message) or "ワールドボス"
        if safe_message.startswith("WB募集開始 / "):
            return StreamBot._choose_world_boss_tts_line(
                self,
                StreamBot._WORLD_BOSS_SPAWN_TTS_LINES,
                boss_name=boss_name,
            )
        if safe_message.startswith("WB開始 / "):
            return StreamBot._choose_world_boss_tts_line(
                self,
                StreamBot._WORLD_BOSS_START_TTS_LINES,
                boss_name=boss_name,
            )
        if safe_message.startswith("WB開始まで残り10秒"):
            return StreamBot._choose_world_boss_tts_line(
                self,
                StreamBot._WORLD_BOSS_JOIN_WARNING_TTS_LINES,
            )
        if safe_message.startswith("WB残り30秒"):
            return StreamBot._choose_world_boss_tts_line(
                self,
                StreamBot._WORLD_BOSS_BATTLE_WARNING_TTS_LINES,
            )
        if "怒りの全体攻撃" in safe_message or safe_message.startswith("WB全体攻撃: "):
            return StreamBot._choose_world_boss_tts_line(
                self,
                StreamBot._WORLD_BOSS_AOE_TTS_LINES,
                boss_name=boss_name,
            )
        if safe_message.startswith("WB激昂 / "):
            return StreamBot._choose_world_boss_tts_line(
                self,
                StreamBot._WORLD_BOSS_ENRAGE_TTS_LINES,
                boss_name=boss_name,
            )
        if safe_message.startswith("WB中止 / 参加者なし / "):
            return StreamBot._choose_world_boss_tts_line(
                self,
                StreamBot._WORLD_BOSS_CANCEL_TTS_LINES,
                boss_name=boss_name,
            )
        if safe_message.startswith("WB討伐成功 / "):
            return StreamBot._choose_world_boss_tts_line(
                self,
                StreamBot._WORLD_BOSS_CLEAR_TTS_LINES,
                boss_name=boss_name,
            )
        if safe_message.startswith("WB時間切れ / "):
            return StreamBot._choose_world_boss_tts_line(
                self,
                StreamBot._WORLD_BOSS_TIMEOUT_TTS_LINES,
                boss_name=boss_name,
            )
        if safe_message.startswith("MVP "):
            actor_name = (
                StreamBot._extract_world_boss_actor_name_for_tts(self, safe_message, "MVP ")
                or "誰か"
            )
            return StreamBot._choose_world_boss_tts_line(
                self,
                StreamBot._WORLD_BOSS_MVP_TTS_LINES,
                name=actor_name,
            )
        if safe_message.startswith("最多貢献 "):
            actor_name = (
                StreamBot._extract_world_boss_actor_name_for_tts(self, safe_message, "最多貢献 ")
                or "誰か"
            )
            return StreamBot._choose_world_boss_tts_line(
                self,
                StreamBot._WORLD_BOSS_TOP_CONTRIBUTOR_TTS_LINES,
                name=actor_name,
            )
        if safe_message.startswith("新称号 "):
            remainder = safe_message[len("新称号 ") :].strip()
            actor_name, _, title_label = remainder.partition(" / ")
            actor_name = nfkc(actor_name).strip() or "誰か"
            title_label = nfkc(title_label).strip() or "新称号"
            return f"{actor_name}が新称号 {title_label} を獲得しました"
        return None

    def build_world_boss_log_tts_message(
        self,
        log_line: Optional[str],
        *,
        status: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        safe_line = nfkc(str(log_line or "")).strip()
        if not safe_line:
            return None

        if not isinstance(status, dict):
            try:
                status = self.rpg.get_world_boss_status()
            except Exception:
                status = {}
        boss = status.get("boss", {}) if isinstance(status, dict) else {}
        boss_name = nfkc(str(boss.get("name", "") or "")).strip() or "ワールドボス"

        if safe_line.startswith("WB撃破: "):
            actor_name = (
                StreamBot._extract_world_boss_actor_name_for_tts(self, safe_line, "WB撃破: ")
                or "誰か"
            )
            return f"{actor_name} が {boss_name} に倒された"

        if safe_line.startswith("WB全体攻撃: ") and "戦闘不能" in safe_line:
            match = re.search(r"戦闘不能\s*(\d+)", safe_line)
            if match and int(match.group(1)) > 0:
                downed_count = int(match.group(1))
                if downed_count == 1:
                    return f"{boss_name} の全体攻撃で 1人が倒れた"
                return f"{boss_name} の全体攻撃で {downed_count}人が倒れた"
        return None

    def maybe_enqueue_world_boss_log_tts(
        self,
        log_lines: List[str],
        *,
        status: Optional[Dict[str, Any]] = None,
    ) -> None:
        for raw_line in log_lines:
            tts_message = StreamBot.build_world_boss_log_tts_message(
                self,
                raw_line,
                status=status,
            )
            if not tts_message:
                continue
            self.enqueue_tts_message(tts_message)
            break

    def maybe_enqueue_world_boss_event_tts(self, message: Optional[str]) -> None:
        tts_message = StreamBot.build_world_boss_tts_message(self, message)
        if tts_message:
            self.enqueue_tts_message(tts_message)

    def maybe_enqueue_world_boss_spawn_tts(self, headline: Optional[str]) -> None:
        StreamBot.maybe_enqueue_world_boss_event_tts(self, headline)

    def maybe_enqueue_feature_unlock_tts(
        self,
        display_name: Optional[str],
        result: Optional[Dict[str, Any]],
    ) -> None:
        if not isinstance(result, dict):
            return

        safe_display_name = nfkc(display_name or "").strip()
        newly_unlocked_features = result.get("newly_unlocked_features")
        if not isinstance(newly_unlocked_features, list):
            newly_unlocked_features = []

        first_clear_reward_summaries = result.get("first_clear_reward_summaries")
        if not isinstance(first_clear_reward_summaries, list):
            first_clear_reward_summaries = []

        if first_clear_reward_summaries:
            if safe_display_name:
                self.enqueue_tts_message(f"{safe_display_name}さんが恒久報酬を解放しました")
            else:
                self.enqueue_tts_message("恒久報酬が解放されました")

        if "auto_repeat" in {str(feature).strip() for feature in newly_unlocked_features}:
            if safe_display_name:
                self.enqueue_tts_message(f"{safe_display_name}さんが自動周回を解放しました")
            else:
                self.enqueue_tts_message("自動周回が解放されました")

    def maybe_enqueue_achievement_unlock_tts(
        self,
        display_name: Optional[str],
        result: Optional[Dict[str, Any]],
    ) -> None:
        if not isinstance(result, dict):
            return

        safe_display_name = nfkc(display_name or "").strip()
        new_titles = result.get("new_titles")
        if not isinstance(new_titles, list):
            new_titles = []

        announced = 0
        for title in new_titles[:2]:
            safe_title = nfkc(str(title or "")).strip()
            if not safe_title:
                continue
            announced += 1
            if safe_display_name:
                self.enqueue_tts_message(f"{safe_display_name}さんが新称号 {safe_title} を獲得しました")
            else:
                self.enqueue_tts_message(f"新称号 {safe_title} を獲得しました")

        if announced > 0:
            return

        new_achievements = result.get("new_achievements")
        if not isinstance(new_achievements, list) or not new_achievements:
            return
        if safe_display_name:
            self.enqueue_tts_message(f"{safe_display_name}さんが新実績を達成しました")
            return
        self.enqueue_tts_message("新実績を達成しました")

    def maybe_enqueue_record_update_tts(
        self,
        display_name: Optional[str],
        result: Optional[Dict[str, Any]],
    ) -> None:
        if not isinstance(result, dict):
            return

        new_records = result.get("new_records")
        if not isinstance(new_records, list) or not new_records:
            return

        safe_display_name = nfkc(display_name or "").strip()
        if safe_display_name:
            self.enqueue_tts_message(f"{safe_display_name}さんが探索記録を更新しました")
            return
        self.enqueue_tts_message("探索記録が更新されました")

    def maybe_enqueue_area_depth_record_tts(
        self,
        display_name: Optional[str],
        result: Optional[Dict[str, Any]],
    ) -> None:
        if not isinstance(result, dict):
            return

        record_update = result.get("area_depth_record_update")
        if not isinstance(record_update, dict):
            return

        safe_area_name = nfkc(str(record_update.get("area", "") or "")).strip()
        if not safe_area_name:
            return

        safe_display_name = nfkc(
            str(record_update.get("display_name", display_name or "") or "")
        ).strip()
        battle_count = max(0, int(record_update.get("battle_count", 0) or 0))
        total_turns = max(0, int(record_update.get("total_turns", 0) or 0))
        stats_suffix = ""
        if battle_count > 0:
            stats_suffix = f" {battle_count}戦 {total_turns}ターン"

        if bool(record_update.get("holder_changed", False)):
            if safe_display_name:
                self.enqueue_tts_message(
                    f"{safe_area_name}の最深記録が{safe_display_name}さんに入れ替わりました{stats_suffix}"
                )
            else:
                self.enqueue_tts_message(f"{safe_area_name}の最深記録が入れ替わりました{stats_suffix}")
            return

        if bool(record_update.get("is_first_record", False)):
            if safe_display_name:
                self.enqueue_tts_message(
                    f"{safe_display_name}さんが{safe_area_name}の最深記録になりました{stats_suffix}"
                )
            else:
                self.enqueue_tts_message(f"{safe_area_name}の最深記録が登録されました{stats_suffix}")
            return

        if safe_display_name:
            self.enqueue_tts_message(
                f"{safe_display_name}さんが{safe_area_name}の最深記録を更新しました{stats_suffix}"
            )
            return
        self.enqueue_tts_message(f"{safe_area_name}の最深記録が更新されました{stats_suffix}")

    def _get_exploration_defeat_monster_name(self, result: Optional[Dict[str, Any]]) -> str:
        if not isinstance(result, dict):
            return ""

        return_info = sanitize_return_info(
            result.get("return_info"),
            result.get("return_reason"),
        )
        monster_name = nfkc(str(return_info.get("monster", "") or "")).strip()
        if monster_name:
            return monster_name

        battle_logs = result.get("battle_logs")
        if not isinstance(battle_logs, list):
            return ""

        for battle in reversed(battle_logs):
            if not isinstance(battle, dict):
                continue
            monster_name = nfkc(str(battle.get("monster", "") or "")).strip()
            if not monster_name or monster_name == "ポーション使用":
                continue
            if bool(battle.get("won", True)):
                continue
            return monster_name
        return ""

    def maybe_enqueue_exploration_defeat_tts(
        self,
        display_name: Optional[str],
        result: Optional[Dict[str, Any]],
    ) -> None:
        if not isinstance(result, dict):
            return
        if not bool(result.get("downed", False)):
            return

        safe_display_name = nfkc(display_name or "").strip()
        monster_name = self._get_exploration_defeat_monster_name(result)

        if safe_display_name and monster_name:
            self.enqueue_tts_message(f"{safe_display_name}さんが{monster_name}によって倒されました")
            return
        if safe_display_name:
            self.enqueue_tts_message(f"{safe_display_name}さんが探索で倒されました")
            return
        if monster_name:
            self.enqueue_tts_message(f"{monster_name}によって倒されました")
            return
        self.enqueue_tts_message("探索で倒されました")

    def enqueue_exploration_result_tts(
        self,
        display_name: Optional[str],
        result: Optional[Dict[str, Any]],
    ) -> None:
        self.maybe_enqueue_exploration_defeat_tts(display_name, result)
        self.maybe_enqueue_boss_clear_tts(display_name, result)
        self.maybe_enqueue_feature_unlock_tts(display_name, result)
        self.maybe_enqueue_achievement_unlock_tts(display_name, result)
        self.maybe_enqueue_area_depth_record_tts(display_name, result)
        self.maybe_enqueue_record_update_tts(display_name, result)
        self.maybe_enqueue_legendary_drop_tts(display_name, result)

    async def _tts_worker(self) -> None:
        chat_backend_name = getattr(self._chat_tts, "backend_name", "TTS")
        rpg_backend_name = getattr(self._rpg_tts, "backend_name", "TTS")
        self.log.info(
            "TTS worker started with chat=%s / rpg=%s.",
            chat_backend_name,
            rpg_backend_name,
        )
        try:
            while not self._tts_stop.is_set():
                try:
                    channel, text = await asyncio.wait_for(self._tts_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break

                if self._tts_stop.is_set():
                    break
                if not text:
                    continue

                ts = now_ts()
                wait = (self._tts_last_ts + CONFIG.tts_cooldown_sec) - ts
                if wait > 0:
                    await asyncio.sleep(wait)

                try:
                    tts_client = self._rpg_tts if channel == "rpg" else self._chat_tts
                    backend_name = getattr(tts_client, "backend_name", "TTS")
                    tts_client.speak(text)
                    self._tts_last_ts = now_ts()
                except Exception:
                    failure_hint = str(getattr(tts_client, "failure_hint", "") or "").strip()
                    if failure_hint:
                        self.log.exception(
                            "%s speak failed for %s (%s)",
                            backend_name,
                            channel,
                            failure_hint,
                        )
                    else:
                        self.log.exception("%s speak failed for %s", backend_name, channel)
        except Exception:
            self.log.exception("TTS worker crashed unexpectedly")
        finally:
            self.log.info("TTS worker stopped.")

    async def _exploration_worker(self) -> None:
        self.log.info("Exploration worker started.")
        try:
            while not self._exploration_stop.is_set():
                try:
                    await self._announce_due_explorations()
                    await self._process_world_boss_events()
                    await asyncio.wait_for(self._exploration_stop.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    break
        except Exception:
            self.log.exception("Exploration worker crashed unexpectedly")
        finally:
            self.log.info("Exploration worker stopped.")

    async def _announce_due_explorations(self) -> None:
        users = self.data.get("users", {})
        save_needed = False
        current_ts = now_ts()
        for username in list(users.keys()):
            user = self.rpg.get_user(username)
            display_name = self.rpg.get_display_name(username, username)
            explore = user.get("explore", {})
            if explore.get("state") != "exploring":
                continue
            if current_ts < float(explore.get("ends_at", 0)):
                continue
            if bool(explore.get("auto_repeat", False)):
                auto_msg = self.try_finalize_exploration(username)
                refreshed_user = self.rpg.get_user(username)
                refreshed_explore = refreshed_user.get("explore", {})
                if refreshed_explore.get("state") != "exploring" and auto_msg:
                    try:
                        await self._send_channel_message(auto_msg, username=username)
                    except Exception:
                        self.log.exception("Failed to announce auto-repeat stop for %s", username)
                continue
            if bool(explore.get("notified_ready", False)):
                continue

            try:
                await self._send_channel_message(
                    f"{display_name} の探索完了 / `!探索 結果` / `!探索 戦闘`",
                    username=username,
                )
                explore["notified_ready"] = True
                save_needed = True
            except Exception:
                self.log.exception("Failed to announce exploration result for %s", username)

        if save_needed:
            self.save_data()

    async def _process_world_boss_events(self) -> None:
        try:
            messages, changed = self.rpg.process_world_boss()
        except Exception:
            self.log.exception("Failed to process world boss state")
            return

        if changed:
            self.save_data()
        try:
            self.refresh_world_boss_visual_html()
        except Exception:
            self.log.exception("Failed to refresh world boss visual overlay")
        try:
            self.publish_world_boss_battle_log_updates()
        except Exception:
            self.log.exception("Failed to publish world boss battle log updates")

        for message in messages:
            safe_message = str(message or "").strip()
            if not safe_message:
                continue
            if safe_message.startswith("WB募集開始 / "):
                try:
                    await self._send_channel_message(safe_message)
                except Exception:
                    self.log.exception("Failed to announce world boss event")
                try:
                    self.publish_world_boss_spawn_notification(safe_message)
                except Exception:
                    self.log.exception("Failed to publish world boss spawn notification")
                continue
            try:
                StreamBot.maybe_enqueue_world_boss_event_tts(self, safe_message)
            except Exception:
                self.log.exception("Failed to enqueue world boss TTS")
            try:
                await self._send_channel_message(safe_message)
            except Exception:
                self.log.exception("Failed to announce world boss event")

    async def _send_channel_message(self, message: str, *, username: Optional[str] = None) -> None:
        broadcaster = self.create_partialuser(str(self.owner_id), CONFIG.channel)
        await broadcaster.send_message(message=message, sender=self.bot_id)
        self.note_reply(username)

    def _extract_emote_text(self, payload: twitchio.ChatMessage, max_emotes: int = 2) -> List[str]:
        out: List[str] = []
        try:
            frags = getattr(payload, "fragments", None) or []
            for f in frags:
                if len(out) >= max_emotes:
                    break
                if getattr(f, "type", "") == "emote":
                    t = getattr(f, "text", "")
                    if t:
                        out.append(t)
        except Exception:
            pass
        return out

    def try_finalize_exploration(self, username: str) -> Optional[str]:
        user = self.rpg.get_user(username)
        explore = user.get("explore", {})
        pending_result = explore.get("result")
        display_name = self.rpg.get_display_name(username, username)
        msg = self.rpg.try_finalize_exploration(username)
        if msg:
            self.save_data()
            self.enqueue_exploration_result_tts(display_name, pending_result)
        return msg

    def _extract_command_words(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        stripped = nfkc(text).strip()
        if not stripped.startswith(CONFIG.prefix):
            return None, None

        remainder = stripped[len(CONFIG.prefix) :].strip()
        if not remainder:
            return None, None

        parts = remainder.split(maxsplit=2)
        root = parts[0].lower()
        subcommand = parts[1].lower() if len(parts) > 1 else None
        return root, subcommand

    def _split_chained_command_text(self, text: str) -> List[str]:
        stripped = nfkc(text).strip()
        if not stripped.startswith(CONFIG.prefix):
            return []

        parts = [part.strip() for part in re.split(r"[;；]+", stripped) if part.strip()]
        if len(parts) <= 1:
            return []

        command_texts: List[str] = []
        for part in parts:
            command_text = part
            if not command_text.startswith(CONFIG.prefix):
                command_text = f"{CONFIG.prefix}{command_text.lstrip()}"
            command_texts.append(command_text)
        return command_texts

    def _clone_chat_message_with_text(
        self,
        payload: twitchio.ChatMessage,
        text: str,
    ) -> twitchio.ChatMessage:
        cloned = copy.copy(payload)
        cloned.text = text
        return cloned

    async def _invoke_command_payload(self, payload: twitchio.ChatMessage) -> bool:
        ctx = self.get_context(payload)
        try:
            invoked = await ctx.invoke()
        except commands.CommandNotFound:
            return False

        return invoked is not False and ctx.command is not None and not ctx.failed

    async def _maybe_process_chained_commands(self, payload: twitchio.ChatMessage) -> bool:
        command_texts = self._split_chained_command_text(payload.text or "")
        if not command_texts:
            return False

        for command_text in command_texts:
            command_payload = self._clone_chat_message_with_text(payload, command_text)
            try:
                await self._maybe_auto_finalize_from_message(command_payload)
            except Exception:
                self.log.exception("Failed to auto-finalize exploration from chained command")

            ok = await self._invoke_command_payload(command_payload)
            if not ok:
                self.log.info("Stopped chained command execution at %r", command_text)
                break

        return True

    def _should_skip_auto_finalize(self, root: Optional[str], subcommand: Optional[str]) -> bool:
        if not root:
            return False
        if root in self._AUTO_FINALIZE_SKIP_COMMANDS:
            return True
        if not subcommand:
            return False
        return subcommand in self._AUTO_FINALIZE_SKIP_SUBCOMMANDS.get(root, set())

    async def _maybe_auto_finalize_from_message(self, payload: twitchio.ChatMessage) -> None:
        text = nfkc(payload.text or "").strip()
        if not text:
            return

        command_name, subcommand = self._extract_command_words(text)
        if self._should_skip_auto_finalize(command_name, subcommand):
            return

        chatter = payload.chatter
        username = getattr(chatter, "name", "") or getattr(chatter, "login", "") or ""
        display_name = getattr(chatter, "display_name", "") or username
        username_key = username.lower().strip()
        if not username_key:
            return

        self.rpg.remember_display_name(username_key, display_name)
        user = self.rpg.get_user(username_key)
        explore = user.get("explore", {})
        if bool(explore.get("auto_repeat", False)):
            return

        auto_msg = self.try_finalize_exploration(username_key)
        if not auto_msg:
            return

        await self._send_channel_message(auto_msg, username=username_key)

    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        if payload.chatter.id == self.bot_id:
            return

        if payload.source_broadcaster is not None:
            return

        if await self._maybe_process_chained_commands(payload):
            return

        try:
            await self._maybe_auto_finalize_from_message(payload)
        except Exception:
            self.log.exception("Failed to auto-finalize exploration from message")

        await self.process_commands(payload)

    async def setup_hook(self) -> None:
        self.show_detail_overlay(
            "OBS Detail Overlay",
            [
                "ボットは待機中です。",
                "!状態 / !探索 結果 / !探索 戦闘 を実行すると詳細ログがここに表示されます。",
            ],
        )

        if CONFIG.tts_enabled:
            self._tts_task = asyncio.create_task(self._tts_worker(), name="tts_worker")
        self._exploration_task = asyncio.create_task(self._exploration_worker(), name="exploration_worker")

        await self._ensure_chat_subscription()
        await self.add_component(BasicCommands(self))
        await self.add_component(NonCommandChat(self))

    async def close(self, **kwargs: Any) -> None:
        await self._shutdown_workers()
        await super().close(**kwargs)

    async def _shutdown_workers(self) -> None:
        try:
            if self._tts_task and not self._tts_task.done():
                self._tts_stop.set()
                try:
                    self._tts_queue.put_nowait(("", ""))
                except Exception:
                    pass

                self._tts_task.cancel()
                try:
                    await self._tts_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    self.log.exception("Error while stopping tts worker")
        finally:
            self._tts_task = None

        try:
            if self._exploration_task and not self._exploration_task.done():
                self._exploration_stop.set()
                self._exploration_task.cancel()
                try:
                    await self._exploration_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    self.log.exception("Error while stopping exploration worker")
        finally:
            self._exploration_task = None

        try:
            await self._shutdown_background_tasks()
        except Exception:
            self.log.exception("Error while stopping background tasks")

        try:
            self.save_data()
        except Exception:
            self.log.exception("Failed to save data on shutdown")

    async def _shutdown_background_tasks(self) -> None:
        pending = [task for task in self._background_tasks if not task.done()]
        if not pending:
            return

        done, still_pending = await asyncio.wait(pending, timeout=2.0)
        for task in done:
            self._background_tasks.discard(task)

        for task in still_pending:
            task.cancel()

        if still_pending:
            await asyncio.gather(*still_pending, return_exceptions=True)
            for task in still_pending:
                self._background_tasks.discard(task)

    async def _ensure_chat_subscription(self) -> None:
        try:
            payload = eventsub.ChatMessageSubscription(
                broadcaster_user_id=str(self.owner_id),
                user_id=str(self.bot_id),
            )
            await self.subscribe_websocket(payload=payload)
            self.log.info("Subscribed to ChatMessageSubscription.")
        except Exception:
            self.log.exception("Failed to subscribe to chat messages (missing tokens/scopes?).")

    async def event_ready(self) -> None:
        self.log.info("READY: bot_id=%s owner_id=%s", self.bot_id, self.owner_id)

    async def event_error(self, error: Exception) -> None:
        self.log.exception("TwitchIO event_error: %s", error)


def validate_config() -> bool:
    missing_vars = []

    if not CONFIG.client_id:
        missing_vars.append("TWITCH_CLIENT_ID")
    if not CONFIG.client_secret:
        missing_vars.append("TWITCH_CLIENT_SECRET")
    if not CONFIG.bot_id:
        missing_vars.append("TWITCH_BOT_ID")
    if not CONFIG.owner_id:
        missing_vars.append("TWITCH_OWNER_ID")
    if not CONFIG.channel:
        missing_vars.append("TWITCH_CHANNEL")

    if missing_vars:
        print(
            "\n[CONFIG ERROR]\n"
            "Missing env vars:\n"
            f"  {', '.join(missing_vars)}\n"
            "Create `.env` from `.env.example` and fill the required values.\n"
            "You can verify the setup with `python dev.py doctor`.\n",
            file=sys.stderr,
        )
        return False

    if CONFIG_ENV_WARNINGS:
        print(
            "\n[CONFIG WARNING]\n"
            + "\n".join(f"- {warning}" for warning in CONFIG_ENV_WARNINGS)
            + "\nReview `.env` or rely on the printed fallback values.\n",
            file=sys.stderr,
        )

    return True


def main() -> None:
    twitchio.utils.setup_logging(level=logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    if not validate_config():
        sys.exit(1)

    async def runner() -> None:
        async with StreamBot() as bot:
            await bot.start()

    try:
        asyncio.run(runner())
    except JsonFileError as exc:
        print(
            "\n[DATA FILE ERROR]\n"
            f"{exc}\n"
            "Refusing to continue so the runtime data is not overwritten.\n"
            "Repair the JSON file or restore it from backup, then run `python dev.py doctor`.\n",
            file=sys.stderr,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        logging.getLogger("StreamBot").warning("KeyboardInterrupt: shutting down...")


if __name__ == "__main__":
    main()
