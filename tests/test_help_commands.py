from __future__ import annotations

import unittest

from bot_components.rpg_commands import BasicCommands
from rpg_core.manager import RPGManager


class _DummyRPG:
    def resolve_exploration_mode(self, mode_key):
        return {"label": "通常", "key": mode_key or "normal"}


class _DummyBot:
    owner_id = "owner"

    def __init__(self) -> None:
        self.rpg = _DummyRPG()

    def show_detail_overlay(self, title, lines) -> None:
        self._overlay = (title, lines)


class _GuideBot:
    owner_id = "owner"

    def __init__(self, data) -> None:
        self.rpg = RPGManager(data)

    def show_detail_overlay(self, title, lines) -> None:
        self._overlay = (title, lines)


class HelpCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.commands = BasicCommands(_DummyBot())

    def test_rpg_help_lines_include_beginner_flow(self) -> None:
        lines = self.commands._build_rpg_help_lines()
        text = "\n".join(lines)

        self.assertIn("!探索 開始 朝の森", text)
        self.assertIn("!探索 自動", text)
        self.assertIn("!攻略", text)
        self.assertIn("!装備 整理", text)
        self.assertIn("!装備 自動強化", text)
        self.assertIn("!探索 履歴", text)
        self.assertIn("!探索 朝の森 / !探索 慎重 朝の森 / !探索 自動 朝の森", text)
        self.assertIn("!攻略 診断", text)
        self.assertIn("!称号 / !称号 森を越えし者 / !称号 解除", text)
        self.assertIn("!スキル / !スキル 強化 鉄壁 / !スキル 変更 ドルマダキア", text)
        self.assertIn("武器黒石 / 防具黒石 / 装飾黒石", text)
        self.assertIn("靴黒石", text)

    def test_progression_help_lines_follow_expected_area_order(self) -> None:
        lines = self.commands._build_progression_help_lines()
        text = "\n".join(lines)

        self.assertLess(text.index("朝の森"), text.index("三日月廃墟"))
        self.assertLess(text.index("三日月廃墟"), text.index("ヘッセ深部"))
        self.assertLess(text.index("ヘッセ深部"), text.index("紅蓮の鉱山"))
        self.assertLess(text.index("紅蓮の鉱山"), text.index("星影の祭壇"))
        self.assertLess(text.index("星影の祭壇"), text.index("迅雷の断崖"))
        self.assertIn("三日月呪石", text)

    def test_explore_help_lines_prefer_integrated_commands(self) -> None:
        lines = self.commands._build_explore_help_lines()
        text = "\n".join(lines)

        self.assertIn("!探索 朝の森", text)
        self.assertIn("!探索 慎重 朝の森", text)
        self.assertIn("!探索 開始 朝の森", text)
        self.assertIn("!探索 準備 武器", text)
        self.assertIn("!探索 結果 / !探索 前回 / !探索 履歴 / !探索 戦利品", text)
        self.assertIn("!探索 戦闘 / !探索 戦闘 3", text)
        self.assertIn("!攻略 エリア / !攻略 診断", text)

    def test_area_reward_summary_uses_feature_unlock_label(self) -> None:
        commands = BasicCommands(_GuideBot({"users": {}}))

        self.assertEqual(
            commands._get_area_first_clear_reward_summary("三日月廃墟"),
            "エンチャント解放",
        )

    def test_area_guide_lines_include_role_and_first_clear_status(self) -> None:
        commands = BasicCommands(_GuideBot({"users": {}}))
        user = commands.bot.rpg.get_user("alice")

        lines = commands._build_area_guide_lines("Alice", user)
        text = "\n".join(lines)

        self.assertIn(
            "朝の森: 序盤装備 / 初回報酬 防具・装飾・靴スロット解放 (未解放)",
            text,
        )
        self.assertIn(
            "三日月廃墟: 装備エンチャ素材 / 初回報酬 エンチャント解放 (未解放)",
            text,
        )
        self.assertIn("迅雷の断崖: 靴強化素材", text)

    def test_area_guide_prioritizes_uncleared_first_clear_rewards(self) -> None:
        commands = BasicCommands(
            _GuideBot(
                {
                    "users": {
                        "alice": {
                            "boss_clear_areas": ["朝の森", "三日月廃墟"],
                        }
                    }
                }
            )
        )
        user = commands.bot.rpg.get_user("alice")

        ordered = commands._get_prioritized_area_names(user)

        self.assertEqual(ordered[0], "ヘッセ深部")
        self.assertEqual(ordered[-3:], ["朝の森", "三日月廃墟", "迅雷の断崖"])

    def test_auto_repeat_unlock_line_uses_route_and_fragments(self) -> None:
        commands = BasicCommands(_GuideBot({"users": {}}))
        user = commands.bot.rpg.get_user("alice")
        user["feature_unlocks"]["auto_repeat_route"] = True
        user["auto_explore_fragments"] = 2

        self.assertEqual(
            commands._build_auto_repeat_unlock_line(user),
            "自動周回: 未解放 / 導線:済 / 欠片:2/3",
        )

    def test_recommendation_detail_lines_use_structured_sections_for_obs(self) -> None:
        commands = BasicCommands(_GuideBot({"users": {}}))
        user = commands.bot.rpg.get_user("alice")
        recommendation = commands.bot.rpg.build_next_recommendation(user)

        lines = commands._build_recommendation_detail_lines("Alice", user, recommendation)
        text = "\n".join(lines)

        self.assertIn("section: 次の一手", text)
        self.assertIn("kv: おすすめ行動 | !探索 開始 慎重 朝の森", text)
        self.assertIn("section: 恒久進行", text)
        self.assertIn("kv: 自動周回 | 未解放 / 導線:未 / 欠片:0/3", text)
        self.assertIn("section: 候補エリア", text)

    def test_history_detail_lines_include_auto_repeat_summary_section(self) -> None:
        commands = BasicCommands(_GuideBot({"users": {}}))
        history = [
            {
                "area": "朝の森",
                "mode": "normal",
                "downed": False,
                "battle_count": 12,
                "exploration_runs": 3,
                "exp": 90,
                "gold": 60,
                "drop_items": [],
                "drop_materials": {},
                "drop_enchant_materials": {},
            },
            {
                "area": "三日月廃墟",
                "mode": "normal",
                "downed": False,
                "battle_count": 4,
                "exploration_runs": 1,
                "exp": 20,
                "gold": 10,
                "drop_items": [],
                "drop_materials": {},
                "drop_enchant_materials": {},
            },
        ]

        lines = commands._build_history_detail_lines("Alice", history)
        text = "\n".join(lines)

        self.assertIn("section: 自動周回集計", text)
        self.assertIn("kv: セッション | 1件", text)
        self.assertIn("kv: 最大連続 | 3回分", text)
        self.assertIn("kv: 1. 自動周回 | 3回分 / 通常 朝の森", text)

    def test_exploration_diagnosis_lines_include_risk_reward_and_use(self) -> None:
        commands = BasicCommands(_GuideBot({"users": {}}))
        user = commands.bot.rpg.get_user("alice")

        diagnosis = commands.bot.rpg.build_exploration_diagnosis(user, "慎重 朝の森")
        lines = commands._build_exploration_diagnosis_lines("Alice", user, diagnosis)
        reply = commands._build_exploration_diagnosis_reply("Alice", user, diagnosis)
        text = "\n".join(lines)

        self.assertIn("コマンド: !攻略 診断", text)
        self.assertIn("想定危険度:", text)
        self.assertIn("初戦:", text)
        self.assertIn("ボス想定:", text)
        self.assertIn("用途: 朝の森: 序盤装備", text)
        self.assertIn("Alice 攻略診断", reply)
        self.assertIn("危険度:", reply)


if __name__ == "__main__":
    unittest.main()
