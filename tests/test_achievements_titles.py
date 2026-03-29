from __future__ import annotations

import unittest
from unittest.mock import patch

from bot_components.rpg_commands import BasicCommands
from rpg_core.manager import RPGManager


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
    }
}


class _GuideBot:
    owner_id = "owner"

    def __init__(self, data) -> None:
        self.rpg = RPGManager(data)

    def show_detail_overlay(self, title, lines) -> None:
        self._overlay = (title, lines)


class AchievementAndTitleTests(unittest.TestCase):
    def test_exploration_boss_clear_unlocks_achievement_and_title(self) -> None:
        manager = RPGManager({"users": {}})
        user = manager.get_user("alice")
        user["explore"] = {
            "state": "exploring",
            "area": "朝の森",
            "mode": "normal",
            "started_at": 0.0,
            "ends_at": 0.0,
            "auto_repeat": False,
            "notified_ready": False,
            "result": {
                "area": "朝の森",
                "mode": "normal",
                "kills": [
                    {
                        "name": "森王の幼体",
                        "boss": True,
                        "area_boss": True,
                    }
                ],
                "exp": 24,
                "gold": 12,
                "damage": 0,
                "drop_items": [],
                "auto_explore_stones": 0,
                "drop_materials": {"weapon": 0, "armor": 0, "ring": 0, "shoes": 0},
                "drop_enchant_materials": {"weapon": 0, "armor": 0, "ring": 0, "shoes": 0},
                "battle_logs": [],
                "battle_count": 1,
                "total_turns": 3,
                "hp_after": 70,
                "returned_safe": True,
                "downed": False,
                "return_reason": "探索終了",
                "return_info": {
                    "phase": "complete",
                    "reason": "探索終了",
                    "raw_reason": "探索終了",
                },
                "potions_used": 0,
                "armor_guards_used": 0,
                "armor_guards_total": 0,
                "armor_enchant_consumed": False,
                "auto_repeat": False,
            },
        }

        manager.finalize_exploration("alice")

        user = manager.get_user("alice")
        result = user.get("last_exploration_result")
        self.assertIsInstance(result, dict)
        self.assertIn("朝の森初踏破", result["new_achievements"])
        self.assertIn("森を越えし者", result["new_titles"])
        self.assertEqual(manager.get_active_title_label(user), "森を越えし者")

        commands = BasicCommands(_GuideBot(manager.data))
        me_lines = commands._build_me_detail_lines("Alice", user)
        me_text = "\n".join(me_lines)
        self.assertIn("称号: 森を越えし者 / 実績 1件", me_text)

        result_lines = commands._build_exploration_result_lines(
            "Alice",
            result,
            command_name="!探索 結果",
            detail_state_label="受取完了",
        )
        result_text = "\n".join(result_lines)
        self.assertIn("新実績: 朝の森初踏破", result_text)
        self.assertIn("新称号: 森を越えし者", result_text)

    def test_world_boss_join_and_clear_unlock_titles(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            manager = RPGManager({"users": {"alice": {}, "bob": {}, "charlie": {}}})
            manager.remember_display_name("alice", "Alice")
            manager.remember_display_name("bob", "Bob")
            manager.remember_display_name("charlie", "Charlie")
            manager.users.get_player_stats = lambda _u, _mode_key: {
                "atk": 10,
                "def": 3,
                "speed": 100,
                "max_hp": 120,
            }
            manager.users.get_weapon_crit_stats = lambda _u: (0.0, 1.0)

            ok, _ = manager.world_boss.start_boss("test_boss", now=100.0)
            self.assertTrue(ok)

            ok, join_msg = manager.world_boss.join_boss("alice", now=101.0)
            self.assertTrue(ok)
            self.assertIn("新称号 共闘者", join_msg)
            manager.world_boss.join_boss("bob", now=102.0)
            manager.world_boss.join_boss("charlie", now=103.0)
            manager.world_boss.skip_recruiting(now=104.0)

            messages, changed = manager.world_boss.process(now=108.0)
            self.assertTrue(changed)
            self.assertIn("WB討伐成功 / 試練の甲帝", messages)

            alice = manager.get_user("alice")
            result = alice.get("last_world_boss_result")
            self.assertIsInstance(result, dict)
            self.assertIn("WB初討伐", result["new_achievements"])
            self.assertIn("WB上位入賞", result["new_achievements"])
            self.assertIn("WB MVP", result["new_achievements"])
            self.assertIn("MVP", result["new_titles"])

            commands = BasicCommands(_GuideBot(manager.data))
            result_lines = commands._build_world_boss_result_lines("Alice", result)
            result_text = "\n".join(result_lines)
            self.assertIn("新実績", result_text)
            self.assertIn("新称号", result_text)
            self.assertIn("MVP", result_text)

            status = manager.get_world_boss_status("alice")
            ranking_lines = commands._build_world_boss_ranking_lines("Alice", status)
            ranking_text = "\n".join(ranking_lines)
            self.assertIn("[共闘者] Alice", ranking_text)


if __name__ == "__main__":
    unittest.main()
