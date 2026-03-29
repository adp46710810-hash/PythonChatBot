from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot_components.rpg_commands import BasicCommands
from rpg_core.manager import RPGManager
from rpg_core.rules import POTION_PRICE


TEST_WORLD_BOSSES = {
    "test_boss": {
        "boss_id": "test_boss",
        "name": "試練の甲帝",
        "title": "テスト用WB",
        "max_hp": 12,
        "atk": 6,
        "def": 0,
        "join_sec": 120,
        "duration_sec": 30,
        "tick_sec": 2,
        "boss_attack_every_ticks": 2,
        "respawn_sec": 5,
        "respawn_hp_ratio": 0.5,
        "material_key": "test_shell",
        "material_label": "試練殻片",
        "participation_exp": 10,
        "participation_gold": 5,
        "participation_material": 1,
        "clear_exp_bonus": 10,
        "clear_gold_bonus": 5,
        "clear_material_bonus": 1,
        "failure_reward_rate": 0.5,
        "mvp_bonus_rate": 0.5,
        "runner_up_bonus_rate": 0.25,
        "third_bonus_rate": 0.1,
        "min_participation_ticks": 1,
        "min_contribution": 1,
        "aoe_thresholds": [75, 50, 25],
        "enrage_threshold_pct": 20,
        "enrage_atk_bonus": 5,
        "skill_book_exchange_cost": 3,
    }
}

INDEXED_TEST_WORLD_BOSSES = {
    "boss_1": {
        **TEST_WORLD_BOSSES["test_boss"],
        "boss_id": "boss_1",
        "name": "一号WB",
    },
    "boss_2": {
        **TEST_WORLD_BOSSES["test_boss"],
        "boss_id": "boss_2",
        "name": "二号WB",
    },
    "boss_3": {
        **TEST_WORLD_BOSSES["test_boss"],
        "boss_id": "boss_3",
        "name": "三号WB",
    },
    "boss_4": {
        **TEST_WORLD_BOSSES["test_boss"],
        "boss_id": "boss_4",
        "name": "四号WB",
    },
}


class _RouterBot:
    owner_id = "owner"

    def __init__(self) -> None:
        self.rpg = RPGManager({"users": {"alice": {}, "owner": {}}})
        self.saved = 0
        self.overlays = []
        self.spawn_notifications = []
        self._speaker_id = 1
        self._speaker_label = "ずんだもん"

    def save_data(self) -> None:
        self.saved += 1

    def show_detail_overlay(self, title, lines) -> None:
        self.overlays.append((title, list(lines)))

    def publish_world_boss_spawn_notification(self, headline) -> None:
        self.spawn_notifications.append(headline)

    def get_rpg_voicevox_speaker_id(self) -> int:
        return self._speaker_id

    def set_rpg_voicevox_speaker_id(self, speaker_id: int, label: str | None = None) -> int:
        self._speaker_id = int(speaker_id)
        if label:
            self._speaker_label = str(label)
        return self._speaker_id

    def get_rpg_voicevox_speaker_label(self) -> str:
        return self._speaker_label


class _Ctx:
    def __init__(self, username: str, display_name: str, chatter_id: str) -> None:
        self.chatter = type(
            "Chatter",
            (),
            {
                "name": username,
                "login": username,
                "display_name": display_name,
                "id": chatter_id,
            },
        )()
        self.replies: list[str] = []

    async def reply(self, message: str) -> None:
        self.replies.append(message)


class CommandRouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bot = _RouterBot()
        self.commands = BasicCommands(self.bot)
        self.viewer = _Ctx("alice", "Alice", "viewer")
        self.owner = _Ctx("owner", "Owner", "owner")

    async def test_status_router_runs_real_subcommands(self) -> None:
        user = self.bot.rpg.get_user("alice")

        await self.commands.me.callback(self.commands, self.viewer, args="hp")
        self.assertIn("HP:", self.viewer.replies[-1])

        await self.commands.me.callback(self.commands, self.viewer, args="exp")
        self.assertIn("冒険EXP:", self.viewer.replies[-1])

        before_potions = int(user.get("potions", 0))
        user["gold"] = POTION_PRICE * 3
        await self.commands.me.callback(self.commands, self.viewer, args="ポーション 3")
        self.assertGreater(int(user.get("potions", 0)), before_potions)
        self.assertEqual(int(user.get("potions", 0)), 3)
        self.assertEqual(int(user.get("auto_potion_refill_target", -1)), 3)

        await self.commands.me.callback(self.commands, self.viewer, args="ポーション 0")
        self.assertEqual(int(user.get("auto_potion_refill_target", -1)), 0)

        user["down"] = True
        user["hp"] = 0
        await self.commands.me.callback(self.commands, self.viewer, args="蘇生")
        self.assertFalse(bool(user.get("down", False)))

    async def test_status_detail_shows_current_skill_loadout(self) -> None:
        await self.commands.me.callback(self.commands, self.viewer, args=None)

        self.assertTrue(self.bot.overlays)
        _, lines = self.bot.overlays[-1]
        text = "\n".join(lines)
        self.assertNotIn("スキル:", text)
        self.assertIn("パッシブ: 1:闘気 Lv1 / 2:鉄壁 Lv1 / 3:なし", text)
        self.assertIn("アクティブ: 1:なし / 2:なし / 3:なし / 4:なし", text)

    async def test_discord_invite_command_returns_configured_url(self) -> None:
        with patch(
            "bot_components.rpg_commands.CONFIG",
            SimpleNamespace(discord_invite_url="https://discord.gg/sample"),
        ):
            await self.commands.discord_invite.callback(self.commands, self.viewer)

        self.assertEqual(self.viewer.replies[-1], "Alice Discord参加URL: https://discord.gg/sample")

    async def test_discord_invite_command_reports_missing_url(self) -> None:
        with patch(
            "bot_components.rpg_commands.CONFIG",
            SimpleNamespace(discord_invite_url=""),
        ):
            await self.commands.discord_invite.callback(self.commands, self.viewer)

        self.assertIn("まだ公開されていません", self.viewer.replies[-1])

    async def test_world_boss_router_runs_real_subcommands(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            await self.commands.world_boss_start.callback(self.commands, self.owner, boss_id="test_boss")

            await self.commands.world_boss_status.callback(self.commands, self.viewer, args="ショップ")
            self.assertTrue(self.viewer.replies[-1])

            await self.commands.world_boss_status.callback(self.commands, self.viewer, args="参加")
            status = self.bot.rpg.get_world_boss_status("alice")
            self.assertIsNotNone(status.get("self"))

            await self.commands.world_boss_status.callback(self.commands, self.viewer, args="ランキング")
            self.assertTrue(self.viewer.replies[-1])

            await self.commands.world_boss_status.callback(self.commands, self.viewer, args="離脱")
            status = self.bot.rpg.get_world_boss_status("alice")
            self.assertIsNone(status.get("self"))

            await self.commands.world_boss_status.callback(self.commands, self.viewer, args="結果")
            self.assertTrue(self.viewer.replies[-1])

            await self.commands.world_boss_status.callback(self.commands, self.owner, args="スキップ")
            self.assertTrue(self.owner.replies[-1])

            await self.commands.world_boss_status.callback(self.commands, self.owner, args="終了")
            status = self.bot.rpg.get_world_boss_status()
            self.assertEqual(status.get("phase"), "idle")

    async def test_world_boss_router_accepts_numbered_owner_shortcut(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", INDEXED_TEST_WORLD_BOSSES):
            await self.commands.world_boss_status.callback(self.commands, self.owner, args="2")

        status = self.bot.rpg.get_world_boss_status()
        self.assertEqual(status.get("phase"), "recruiting")
        self.assertEqual(status.get("boss", {}).get("boss_id"), "boss_2")
        self.assertEqual(status.get("boss", {}).get("name"), "二号WB")
        self.assertIn("二号WB", self.owner.replies[-1])
        self.assertEqual(self.bot.spawn_notifications[-1], "WB募集開始 / 二号WB / 120秒 / `!wb参加`")

    async def test_world_boss_start_rejects_unknown_selector_without_fallback(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", INDEXED_TEST_WORLD_BOSSES):
            await self.commands.world_boss_start.callback(self.commands, self.owner, boss_id="99")

        status = self.bot.rpg.get_world_boss_status()
        self.assertEqual(status.get("phase"), "idle")
        self.assertIn("WB番号またはboss_id", self.owner.replies[-1])
        self.assertIn("1:一号WB (boss_1)", self.owner.replies[-1])

    async def test_world_boss_router_marks_number_shortcuts_as_debug_for_owner(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", INDEXED_TEST_WORLD_BOSSES):
            await self.commands.world_boss_status.callback(self.commands, self.owner, args="謎")

        self.assertIn("配信者デバッグ用", self.owner.replies[-1])
        self.assertIn("!wb <番号> / !wb終了", self.owner.replies[-1])

    async def test_manage_router_runs_real_subcommands(self) -> None:
        user = self.bot.rpg.get_user("alice")

        await self.commands.manage.callback(self.commands, self.owner, args="読み上げID 4")
        self.assertEqual(self.bot.get_rpg_voicevox_speaker_id(), 4)

        await self.commands.manage.callback(self.commands, self.owner, args="ping")
        self.assertEqual(self.owner.replies[-1], "pong")

        await self.commands.manage.callback(self.commands, self.owner, args="debug gold 7 alice")
        self.assertEqual(int(user.get("gold", 0)), 7)

        await self.commands.manage.callback(self.commands, self.owner, args="debug potion 3 alice")
        self.assertEqual(int(user.get("potions", 0)), 3)

        await self.commands.manage.callback(self.commands, self.owner, args="debug exp 5 alice")
        self.assertGreaterEqual(int(user.get("adventure_exp", 0)), 5)

        await self.commands.manage.callback(self.commands, self.owner, args="debug down alice")
        self.assertTrue(bool(user.get("down", False)))

        await self.commands.manage.callback(self.commands, self.owner, args="debug heal alice")
        self.assertEqual(int(user.get("hp", 0)), int(user.get("max_hp", 0)))

    async def test_explore_router_runs_real_subcommands_without_raising(self) -> None:
        cases = ["停止", "結果", "前回", "履歴", "戦利品"]

        for args in cases:
            with self.subTest(args=args):
                before = len(self.viewer.replies)
                await self.commands.explore.callback(self.commands, self.viewer, args=args)
                self.assertGreater(len(self.viewer.replies), before)
                self.assertTrue(self.viewer.replies[-1])

    async def test_explore_router_prepares_next_run_and_saves(self) -> None:
        user = self.bot.rpg.get_user("alice")
        user["materials"]["weapon"] = 8
        before_saved = self.bot.saved

        await self.commands.explore.callback(self.commands, self.viewer, args="準備 武器")

        self.assertEqual(user["materials"]["weapon"], 0)
        self.assertTrue(user["exploration_preparation"]["weapon"])
        self.assertGreater(self.bot.saved, before_saved)
        self.assertIn("次の探索1回だけ", self.viewer.replies[-1])

    async def test_explore_router_accepts_area_shortcut_start(self) -> None:
        before_saved = self.bot.saved

        await self.commands.explore.callback(self.commands, self.viewer, args="朝の森")

        self.assertGreater(self.bot.saved, before_saved)
        self.assertIn("朝の森", self.viewer.replies[-1])
        self.assertIn("探索に出発", self.viewer.replies[-1])

    async def test_explore_router_keeps_usage_for_unknown_subcommand(self) -> None:
        before_saved = self.bot.saved

        await self.commands.explore.callback(self.commands, self.viewer, args="結果x")

        self.assertEqual(self.bot.saved, before_saved)
        self.assertIn("!探索 <エリア>", self.viewer.replies[-1])

    async def test_advice_and_equip_routers_run_real_subcommands(self) -> None:
        await self.commands.advice.callback(self.commands, self.viewer, args="順")
        self.assertIn("攻略順", self.viewer.replies[-1])

        await self.commands.advice.callback(self.commands, self.viewer, args="エリア")
        self.assertIn("攻略エリア", self.viewer.replies[-1])

        await self.commands.equip.callback(self.commands, self.viewer, args="バッグ")
        self.assertIn("装備袋", self.viewer.replies[-1])

        await self.commands.equip.callback(self.commands, self.viewer, args="素材")
        self.assertIn("素材 /", self.viewer.replies[-1])

        await self.commands.equip.callback(self.commands, self.viewer, args="整理")
        self.assertIn("整理完了", self.viewer.replies[-1])

    async def test_title_command_switches_and_clears_active_title(self) -> None:
        user = self.bot.rpg.get_user("alice")
        self.bot.rpg.users.unlock_achievement(user, "forest_boss_clear")
        self.bot.rpg.users.unlock_achievement(user, "record_breaker")

        await self.commands.titles.callback(self.commands, self.viewer)
        self.assertIn("称号", self.viewer.replies[-1])

        await self.commands.titles.callback(self.commands, self.viewer, args="変更 記録更新者")
        self.assertEqual(self.bot.rpg.get_active_title_label(user), "記録更新者")
        self.assertIn("記録更新者", self.viewer.replies[-1])

        await self.commands.titles.callback(self.commands, self.viewer, args="解除")
        self.assertEqual(self.bot.rpg.get_active_title_label(user), "")
        self.assertIn("解除", self.viewer.replies[-1])

        await self.commands.titles.callback(self.commands, self.viewer, args="森を越えし者")
        self.assertEqual(self.bot.rpg.get_active_title_label(user), "森を越えし者")
        self.assertIn("森を越えし者", self.viewer.replies[-1])


if __name__ == "__main__":
    unittest.main()
