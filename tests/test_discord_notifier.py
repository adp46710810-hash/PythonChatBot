from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import patch

from bot import StreamBot
from bot_components.rpg_commands import BasicCommands
from rpg_core.discord_notifier import DiscordWebhookNotifier


class _DetailPublishBot:
    owner_id = "owner"

    def __init__(self) -> None:
        self.published = []

    def publish_detail_response(self, title, lines) -> None:
        self.published.append((title, lines))

    def get_detail_destination_label(self) -> str:
        return "Discord"


class _NotifierStub:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self.sent = []

    async def send_detail(self, title, lines) -> None:
        self.sent.append((title, list(lines)))


class _WorldBossStatusRPG:
    def __init__(self) -> None:
        self.status = {
            "boss": {"name": "試練の甲帝", "title": "テスト用WB"},
            "participants": 0,
            "join_ends_at": time.time() + 30.0,
            "recent_logs": ["募集開始: 試練の甲帝"],
        }

    def get_world_boss_status(self):
        return dict(self.status)

    def format_duration(self, sec: int) -> str:
        return f"{int(sec)}秒"


class _StreamBotPublishDouble:
    def __init__(self, *, notifier_enabled: bool) -> None:
        self._discord_notifier = _NotifierStub(enabled=notifier_enabled)
        self.rpg = _WorldBossStatusRPG()
        self.overlays = []
        self.overlay_world_boss_variants = []
        self.scheduled = []
        self.tts_messages = []
        self._world_boss_discord_logs_initialized = False
        self._world_boss_discord_last_recent_logs = []
        self._world_boss_discord_last_phase = "idle"
        self._build_world_boss_spawn_notification = (
            lambda headline: StreamBot._build_world_boss_spawn_notification(self, headline)
        )
        self.maybe_enqueue_world_boss_spawn_tts = (
            lambda headline: StreamBot.maybe_enqueue_world_boss_spawn_tts(self, headline)
        )

    def show_detail_overlay(self, title, lines, *, include_world_boss_variant=True) -> None:
        self.overlays.append((title, list(lines)))
        self.overlay_world_boss_variants.append(include_world_boss_variant)

    def _schedule_background_task(self, coroutine, *, name: str) -> None:
        self.scheduled.append(name)
        asyncio.run(coroutine)

    def enqueue_tts_message(self, text: str) -> None:
        self.tts_messages.append(text)


class DiscordNotifierTests(unittest.TestCase):
    def test_old_discordapp_domain_is_normalized(self) -> None:
        notifier = DiscordWebhookNotifier(
            "https://discordapp.com/api/webhooks/123/token"
        )

        self.assertEqual(
            notifier.webhook_url,
            "https://discord.com/api/webhooks/123/token",
        )

    def test_invalid_webhook_host_is_rejected(self) -> None:
        notifier = DiscordWebhookNotifier("https://example.invalid/api/webhooks/123/token")

        self.assertEqual(notifier.webhook_url, "")
        self.assertFalse(notifier.enabled)

    def test_insecure_webhook_scheme_is_rejected(self) -> None:
        notifier = DiscordWebhookNotifier("http://discord.com/api/webhooks/123/token")

        self.assertEqual(notifier.webhook_url, "")
        self.assertFalse(notifier.enabled)

    def test_request_uses_browser_like_user_agent(self) -> None:
        notifier = DiscordWebhookNotifier("https://discord.com/api/webhooks/123/token")

        req = notifier._build_request({"content": "test"})

        self.assertEqual(req.headers["Content-type"], "application/json")
        self.assertEqual(req.headers["Accept"], "application/json")
        self.assertEqual(req.headers["User-agent"], "Mozilla/5.0")

    def test_message_chunks_stay_within_discord_limit(self) -> None:
        notifier = DiscordWebhookNotifier("https://example.invalid/webhook")

        chunks = notifier._build_message_chunks(
            "Alice / !戦闘詳細",
            ["x" * 1900, "y" * 1900],
        )

        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(len(chunk) <= 2000 for chunk in chunks))
        self.assertTrue(chunks[0].startswith("**Alice / !戦闘詳細"))

    def test_basic_commands_publish_detail_uses_bot_publisher_and_label(self) -> None:
        bot = _DetailPublishBot()
        commands = BasicCommands(bot)

        commands._show_detail_overlay("Alice / !me", ["line1", "line2"])
        reply = commands._build_detail_hint_reply("Alice", "探索結果")

        self.assertEqual(bot.published, [("Alice / !me", ["line1", "line2"])])
        self.assertIn("詳細はDiscord", reply)

    def test_stream_bot_publish_detail_response_prefers_discord_over_html(self) -> None:
        bot = _StreamBotPublishDouble(notifier_enabled=True)

        StreamBot.publish_detail_response(bot, "Alice / !me", ["line1", "line2"])

        self.assertEqual(bot.overlays, [])
        self.assertEqual(bot.scheduled, ["discord_detail:Alice / !me"])
        self.assertEqual(
            bot._discord_notifier.sent,
            [("Alice / !me", ["line1", "line2"])],
        )

    def test_stream_bot_publish_detail_response_uses_html_when_discord_disabled(self) -> None:
        bot = _StreamBotPublishDouble(notifier_enabled=False)

        StreamBot.publish_detail_response(bot, "Alice / !me", ["line1", "line2"])

        self.assertEqual(bot.scheduled, [])
        self.assertEqual(bot._discord_notifier.sent, [])
        self.assertEqual(bot.overlays, [("Alice / !me", ["line1", "line2"])])

    def test_stream_bot_publish_world_boss_spawn_notification_updates_html_and_discord(self) -> None:
        bot = _StreamBotPublishDouble(notifier_enabled=True)

        with patch("bot.random.choice", side_effect=lambda seq: seq[0]):
            StreamBot.publish_world_boss_spawn_notification(
                bot,
                "WB募集開始 / 試練の甲帝 / 120秒 / `!wb参加`",
            )

        self.assertEqual(bot.scheduled, ["discord_world_boss:ワールドボス出現 / 試練の甲帝"])
        self.assertEqual(len(bot.overlays), 1)
        title, lines = bot.overlays[0]
        self.assertEqual(title, "ワールドボス出現 / 試練の甲帝")
        self.assertTrue(any("!wb参加" in line for line in lines))
        self.assertEqual(bot.overlay_world_boss_variants, [False])
        self.assertEqual(
            bot.tts_messages,
            ["試練の甲帝 が湧いたぞ。寝てる雑魚は叩き起きろ"],
        )
        self.assertEqual(
            bot._discord_notifier.sent,
            [(title, lines)],
        )

    def test_stream_bot_publish_world_boss_battle_log_updates_do_not_publish_to_discord(self) -> None:
        bot = _StreamBotPublishDouble(notifier_enabled=True)
        bot._world_boss_discord_logs_initialized = True
        bot._world_boss_discord_last_recent_logs = [
            "WB募集開始 / 試練の甲帝 / 120秒 / `!wb参加`",
        ]
        bot._world_boss_discord_last_phase = "recruiting"
        bot.rpg.status = {
            "phase": "active",
            "boss": {"name": "試練の甲帝", "title": "テスト用WB"},
            "participants": 3,
            "current_hp": 84,
            "max_hp": 120,
            "ends_at": 130.0,
            "recent_logs": [
                "WB募集開始 / 試練の甲帝 / 120秒 / `!wb参加`",
                "戦闘開始: 試練の甲帝 / HP 120",
                "スキル発動: Alice:闘気",
                "T1: 2行動で36ダメ",
                "WB攻撃: Alice に 12ダメ",
            ],
        }

        with patch("bot.now_ts", return_value=100.0):
            StreamBot.publish_world_boss_battle_log_updates(bot)

        self.assertEqual(bot.scheduled, [])
        self.assertEqual(bot._discord_notifier.sent, [])
        self.assertEqual(bot._world_boss_discord_last_phase, "active")
        self.assertEqual(bot._world_boss_discord_last_recent_logs, bot.rpg.status["recent_logs"])

    def test_stream_bot_publish_world_boss_battle_log_updates_enqueues_tts_when_discord_disabled(self) -> None:
        bot = _StreamBotPublishDouble(notifier_enabled=False)
        bot._world_boss_discord_logs_initialized = True
        bot._world_boss_discord_last_recent_logs = [
            "戦闘開始: 試練の甲帝 / HP 120",
        ]
        bot._world_boss_discord_last_phase = "active"
        bot.rpg.status = {
            "phase": "active",
            "boss": {"name": "試練の甲帝", "title": "テスト用WB"},
            "participants": 3,
            "current_hp": 84,
            "max_hp": 120,
            "ends_at": 130.0,
            "recent_logs": [
                "戦闘開始: 試練の甲帝 / HP 120",
                "WB撃破: Alice / 82ダメ / 復帰8秒",
            ],
        }

        StreamBot.publish_world_boss_battle_log_updates(bot)

        self.assertEqual(bot._discord_notifier.sent, [])
        self.assertEqual(bot.tts_messages, ["Alice が 試練の甲帝 に倒された"])


if __name__ == "__main__":
    unittest.main()
