from __future__ import annotations

import unittest
from unittest.mock import patch

from bot import StreamBot
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


class _WorldBossBot:
    owner_id = "owner"

    def __init__(self, data) -> None:
        self.rpg = RPGManager(data)
        self.saved = 0
        self.overlays = []
        self.world_boss_notifications = []

    def save_data(self) -> None:
        self.saved += 1

    def show_detail_overlay(self, title, lines) -> None:
        self.overlays.append((title, lines))

    def publish_world_boss_spawn_notification(self, headline) -> None:
        self.world_boss_notifications.append(headline)


class _VisualOverlayRecorder:
    def __init__(self) -> None:
        self.calls = []

    def show_wb_html(self, title, lines) -> None:
        self.calls.append((title, list(lines)))


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
        self.replies = []

    async def reply(self, message: str) -> None:
        self.replies.append(message)


class WorldBossServiceTests(unittest.TestCase):
    def test_world_boss_hp_scaling_uses_tuned_participant_bonus(self) -> None:
        manager = RPGManager({"users": {}})

        self.assertEqual(manager.world_boss._scale_boss_hp(100, 1), 100)
        self.assertEqual(manager.world_boss._scale_boss_hp(100, 2), 190)
        self.assertEqual(manager.world_boss._scale_boss_hp(100, 3), 243)

    def test_world_boss_random_pick_uses_spawn_weight(self) -> None:
        weighted_world_bosses = {
            "common_boss": {
                **TEST_WORLD_BOSSES["test_boss"],
                "boss_id": "common_boss",
                "name": "常設ボス",
                "spawn_weight": 1.0,
            },
            "rare_boss": {
                **TEST_WORLD_BOSSES["test_boss"],
                "boss_id": "rare_boss",
                "name": "レアボス",
                "spawn_weight": 0.1,
            },
        }

        with patch("rpg_core.world_boss_service.WORLD_BOSSES", weighted_world_bosses), patch(
            "rpg_core.world_boss_service.random.choices",
            return_value=["rare_boss"],
        ) as choices_mock:
            manager = RPGManager({"users": {}})

            boss_id, boss = manager.world_boss._pick_random_boss_template()

        self.assertEqual(boss_id, "rare_boss")
        self.assertEqual(boss["name"], "レアボス")
        choices_mock.assert_called_once()
        args, kwargs = choices_mock.call_args
        self.assertEqual(args[0], ["common_boss", "rare_boss"])
        self.assertEqual(kwargs["weights"], [1.0, 0.1])
        self.assertEqual(kwargs["k"], 1)

    def test_world_boss_ranking_deprioritizes_owner_when_viewer_competes(self) -> None:
        manager = RPGManager({"users": {}}, owner_username="streamer")

        ranking = manager.world_boss._build_ranking(
            {
                "streamer": {
                    "username": "streamer",
                    "display_name": "Streamer",
                    "contribution_score": 999,
                    "total_damage": 999,
                    "joined_at": 0.0,
                },
                "alice": {
                    "username": "alice",
                    "display_name": "Alice",
                    "contribution_score": 100,
                    "total_damage": 100,
                    "joined_at": 0.0,
                },
            }
        )

        self.assertEqual(ranking[0]["username"], "alice")
        self.assertEqual(ranking[1]["username"], "streamer")
        self.assertEqual(ranking[0]["rank"], 1)
        self.assertEqual(ranking[1]["rank"], 2)

    def test_world_boss_respawn_restores_participant_to_boss_ratio_hp(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            manager = RPGManager({"users": {"alice": {}}})
            manager.users.get_player_stats = lambda _u, _mode_key: {
                "atk": 10,
                "def": 3,
                "speed": 100,
                "max_hp": 120,
            }
            manager.users.get_weapon_crit_stats = lambda _u: (0.0, 1.0)

            ok, _ = manager.world_boss.start_boss("test_boss", now=100.0)
            self.assertTrue(ok)
            ok, _ = manager.world_boss.join_boss("alice", now=101.0)
            self.assertTrue(ok)
            ok, _ = manager.world_boss.skip_recruiting(now=102.0)
            self.assertTrue(ok)

            state = manager.world_boss.get_state()
            participant = state["participants"]["alice"]
            participant["alive"] = False
            participant["current_hp"] = 0
            participant["respawn_at"] = 110.0
            participant["snapshot_max_hp"] = 120

            manager.world_boss._handle_respawns(state, now=110.0)

            self.assertTrue(participant["alive"])
            self.assertEqual(participant["current_hp"], 60)

    def test_world_boss_single_target_attack_logs_downed_participant(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            manager = RPGManager({"users": {"alice": {"display_name": "Alice"}}})
            manager.users.get_player_stats = lambda _u, _mode_key: {
                "atk": 10,
                "def": 3,
                "speed": 100,
                "max_hp": 120,
            }
            manager.users.get_weapon_crit_stats = lambda _u: (0.0, 1.0)

            ok, _ = manager.world_boss.start_boss("test_boss", now=100.0)
            self.assertTrue(ok)
            ok, _ = manager.world_boss.join_boss("alice", now=101.0)
            self.assertTrue(ok)
            ok, _ = manager.world_boss.skip_recruiting(now=102.0)
            self.assertTrue(ok)

            state = manager.world_boss.get_state()
            participant = state["participants"]["alice"]
            participant["current_hp"] = 1

            with patch.object(manager.world_boss.battle_service, "get_base_damage", return_value=99):
                manager.world_boss._run_single_target_attack(state, now=103.0, enraged=False)

            self.assertFalse(participant["alive"])
            self.assertEqual(participant["times_downed"], 1)
            self.assertEqual(state["recent_logs"][-1], "WB撃破: Alice / 99ダメ / 復帰5秒")

    def test_world_boss_threshold_aoe_logs_downed_participant_count(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            manager = RPGManager(
                {
                    "users": {
                        "alice": {"display_name": "Alice"},
                        "bob": {"display_name": "Bob"},
                        "carol": {"display_name": "Carol"},
                        "dave": {"display_name": "Dave"},
                    }
                }
            )
            manager.users.get_player_stats = lambda _u, _mode_key: {
                "atk": 10,
                "def": 3,
                "speed": 100,
                "max_hp": 120,
            }
            manager.users.get_weapon_crit_stats = lambda _u: (0.0, 1.0)

            ok, _ = manager.world_boss.start_boss("test_boss", now=100.0)
            self.assertTrue(ok)
            for offset, username in enumerate(("alice", "bob", "carol", "dave"), start=1):
                ok, _ = manager.world_boss.join_boss(username, now=100.0 + offset)
                self.assertTrue(ok)
            ok, _ = manager.world_boss.skip_recruiting(now=105.0)
            self.assertTrue(ok)

            state = manager.world_boss.get_state()
            for participant in state["participants"].values():
                participant["current_hp"] = 1

            with patch.object(manager.world_boss.battle_service, "get_base_damage", return_value=99):
                message = manager.world_boss._run_threshold_aoe(state, threshold=75, now=106.0)

            self.assertEqual(message, "WB HP75%突破 / PHASE 2")
            self.assertEqual(
                state["recent_logs"][-1],
                "WB全体攻撃: 4人へ / 戦闘不能4人 / Alice / Bob / Carol / ...ほか1人",
            )
            self.assertTrue(all(not participant["alive"] for participant in state["participants"].values()))

    def test_world_boss_clear_grants_rewards_and_records_results(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            manager = RPGManager({"users": {"alice": {}, "bob": {}}})
            manager.users.get_player_stats = lambda _u, _mode_key: {
                "atk": 10,
                "def": 3,
                "speed": 100,
                "max_hp": 120,
            }
            manager.users.get_weapon_crit_stats = lambda _u: (0.0, 1.0)

            ok, _ = manager.world_boss.start_boss("test_boss", now=100.0)
            self.assertTrue(ok)

            ok, _ = manager.world_boss.join_boss("alice", now=101.0)
            self.assertTrue(ok)
            ok, _ = manager.world_boss.join_boss("bob", now=101.0)
            self.assertTrue(ok)

            ok, _ = manager.world_boss.skip_recruiting(now=102.0)
            self.assertTrue(ok)

            messages, changed = manager.world_boss.process(now=106.0)
            self.assertTrue(changed)
            self.assertIn("WB討伐成功 / 試練の甲帝", messages)

            status = manager.get_world_boss_status("alice")
            self.assertEqual(status["phase"], "cooldown")
            self.assertTrue(status["last_result"]["cleared"])

            alice = manager.get_user("alice")
            result = alice.get("last_world_boss_result")
            self.assertIsInstance(result, dict)
            self.assertTrue(result["cleared"])
            self.assertEqual(result["boss_name"], "試練の甲帝")
            self.assertGreater(result["rewards"]["exp"], 0)
            self.assertGreater(result["rewards"]["gold"], 0)
            self.assertGreater(result["rewards"]["material_amount"], 0)
            self.assertGreater(result["contribution"]["objective_score"], 0)
            self.assertGreater(alice["world_boss_materials"]["test_shell"], 0)
            self.assertEqual(len(alice["world_boss_history"]), 1)

    def test_world_boss_status_hides_late_join_visual_event_and_delays_race_focus(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            manager = RPGManager({"users": {"alice": {}, "bob": {}}})
            manager.users.get_player_stats = lambda _u, _mode_key: {
                "atk": 10,
                "def": 3,
                "speed": 100,
                "max_hp": 120,
            }
            manager.users.get_weapon_crit_stats = lambda _u: (0.0, 1.0)

            ok, _ = manager.world_boss.start_boss("test_boss", now=100.0)
            self.assertTrue(ok)
            ok, _ = manager.world_boss.join_boss("alice", now=101.0)
            self.assertTrue(ok)
            ok, _ = manager.world_boss.skip_recruiting(now=102.0)
            self.assertTrue(ok)
            ok, _ = manager.world_boss.join_boss("bob", now=103.0)
            self.assertTrue(ok)

            status = manager.world_boss.get_status("bob")
            self.assertEqual(status["phase"], "active")
            self.assertEqual(status["event_kind"], "")
            self.assertEqual(status["event_text"], "")
            self.assertFalse(status["race_focus_active"])
            self.assertTrue(
                any(str(line).startswith("途中参加:") for line in status["recent_logs"])
            )

            state = manager.world_boss.get_state()
            state["current_hp"] = 2
            manager.world_boss._refresh_visual_state(state)

            last_stand_status = manager.world_boss.get_status("bob")
            self.assertEqual(last_stand_status["phase_id"], "last_stand")
            self.assertTrue(last_stand_status["race_focus_active"])

    def test_world_boss_support_skill_adds_support_score_breakdown(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            manager = RPGManager({"users": {"alice": {}}})
            manager.users.get_player_stats = lambda _u, _mode_key: {
                "atk": 10,
                "def": 3,
                "speed": 100,
                "max_hp": 120,
            }
            manager.users.get_weapon_crit_stats = lambda _u: (0.0, 1.0)
            manager.users.get_selected_active_skills = lambda _u: [
                {
                    "skill_id": "active_crimson_focus",
                    "name": "紅蓮集中",
                    "target": "self",
                    "deals_damage": False,
                    "atk_bonus": 8,
                    "duration_turns": 2,
                    "duration_ticks": 2,
                    "cooldown_actions": 5,
                }
            ]

            ok, _ = manager.world_boss.start_boss("test_boss", now=100.0)
            self.assertTrue(ok)
            ok, _ = manager.world_boss.join_boss("alice", now=101.0)
            self.assertTrue(ok)
            ok, _ = manager.world_boss.skip_recruiting(now=102.0)
            self.assertTrue(ok)

            state = manager.world_boss.get_state()
            manager.world_boss._run_player_phase(state)

            participant = state["participants"]["alice"]
            self.assertEqual(participant["total_damage"], 0)
            self.assertGreater(participant["contribution"]["support_score"], 0)
            self.assertGreater(participant["contribution"]["survival_score"], 0)
            self.assertTrue(participant["active_effects"])

    def test_finalize_exploration_area_boss_clear_can_auto_start_world_boss(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES), patch(
            "rpg_core.world_boss_service.random.random",
            return_value=0.0,
        ):
            manager = RPGManager({"users": {"alice": {}}})
            user = manager.get_user("alice")
            user["explore"] = {
                "state": "exploring",
                "area": "紅蓮の鉱山",
                "mode": "normal",
                "started_at": 0.0,
                "ends_at": 0.0,
                "auto_repeat": False,
                "notified_ready": False,
                "result": {
                    "area": "紅蓮の鉱山",
                    "mode": "normal",
                    "kills": [
                        {
                            "name": "ボス灼刃の狂戦士",
                            "boss": True,
                            "area_boss": True,
                        }
                    ],
                    "exp": 10,
                    "gold": 5,
                    "damage": 0,
                    "drop_items": [],
                    "auto_explore_stones": 0,
                    "drop_materials": {"weapon": 0, "armor": 0, "ring": 0},
                    "drop_enchant_materials": {"weapon": 0, "armor": 0, "ring": 0},
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

            status = manager.get_world_boss_status()
            self.assertEqual(status["phase"], "recruiting")

            progress = manager.data.get("world_boss_progress", {})
            self.assertEqual(progress.get("claim_count"), 0)
            self.assertEqual(progress.get("pending_rolls"), [])
            self.assertEqual(progress.get("area_boss_clear_counts"), {})
            self.assertEqual(progress.get("completed_cycles"), 1)
            self.assertEqual(progress.get("last_trigger_area"), "紅蓮の鉱山")

            messages, changed = manager.process_world_boss()
            self.assertTrue(changed)
            self.assertIn("WB募集開始 / 試練の甲帝 / 120秒 / `!wb参加`", messages)

    def test_finalize_exploration_without_area_boss_clear_does_not_trigger_world_boss_roll(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES), patch(
            "rpg_core.world_boss_service.random.random",
            return_value=0.0,
        ):
            manager = RPGManager({"users": {"alice": {}}})
            user = manager.get_user("alice")
            user["explore"] = {
                "state": "exploring",
                "area": "紅蓮の鉱山",
                "mode": "normal",
                "started_at": 0.0,
                "ends_at": 0.0,
                "auto_repeat": False,
                "notified_ready": False,
                "result": {
                    "area": "紅蓮の鉱山",
                    "mode": "normal",
                    "kills": [],
                    "exp": 10,
                    "gold": 5,
                    "damage": 0,
                    "drop_items": [],
                    "auto_explore_stones": 0,
                    "drop_materials": {"weapon": 0, "armor": 0, "ring": 0},
                    "drop_enchant_materials": {"weapon": 0, "armor": 0, "ring": 0},
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

            status = manager.get_world_boss_status()
            self.assertEqual(status["phase"], "idle")

            progress = manager.data.get("world_boss_progress", {})
            self.assertFalse(progress)

    def test_pending_auto_spawn_roll_waits_until_current_world_boss_finishes(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            manager = RPGManager({"users": {"alice": {}}})

            ok, _ = manager.world_boss.start_boss("test_boss", now=100.0)
            self.assertTrue(ok)

            manager.world_boss.record_area_boss_clear("朝の森", now=110.0)

            status = manager.get_world_boss_status()
            self.assertEqual(status["phase"], "recruiting")

            progress = manager.data.get("world_boss_progress", {})
            self.assertEqual(len(progress.get("pending_rolls", [])), 1)
            self.assertEqual(progress.get("area_boss_clear_counts", {}).get("朝の森"), 1)

            ok, _ = manager.world_boss.stop_boss()
            self.assertTrue(ok)

            with patch("rpg_core.world_boss_service.random.random", return_value=0.0):
                messages, changed = manager.world_boss.process(now=111.0)
            self.assertTrue(changed)
            self.assertIn("WB募集開始 / 試練の甲帝 / 120秒 / `!wb参加`", messages)
            self.assertEqual(manager.data["world_boss_progress"]["pending_rolls"], [])
            self.assertEqual(manager.data["world_boss_progress"]["area_boss_clear_counts"], {})

    def test_area_difficulty_and_boss_clear_count_raise_auto_spawn_chance(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            manager = RPGManager({"users": {"alice": {}}})

            ok, _ = manager.world_boss.start_boss("test_boss", now=100.0)
            self.assertTrue(ok)

            manager.world_boss.record_area_boss_clear("朝の森", now=101.0)
            manager.world_boss.record_area_boss_clear("朝の森", now=102.0)
            manager.world_boss.record_area_boss_clear("迅雷の断崖", now=103.0)

            progress = manager.data.get("world_boss_progress", {})
            pending_rolls = progress.get("pending_rolls", [])

            self.assertEqual(len(pending_rolls), 3)
            self.assertLess(pending_rolls[0]["chance"], pending_rolls[1]["chance"])
            self.assertLess(pending_rolls[0]["chance"], pending_rolls[2]["chance"])

    def test_auto_spawn_uses_pity_after_three_failed_boss_clear_rolls(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES), patch(
            "rpg_core.world_boss_service.random.random",
            return_value=1.0,
        ):
            manager = RPGManager({"users": {"alice": {}}})

            for _ in range(3):
                manager.world_boss.record_area_boss_clear("朝の森", now=100.0)

            status = manager.get_world_boss_status()
            self.assertEqual(status["phase"], "recruiting")

            progress = manager.data.get("world_boss_progress", {})
            self.assertEqual(progress.get("claim_count"), 0)
            self.assertEqual(progress.get("pending_rolls"), [])
            self.assertEqual(progress.get("completed_cycles"), 3)
            self.assertEqual(progress.get("failed_rolls"), 0)
            self.assertEqual(progress.get("area_boss_clear_counts"), {})

            messages, changed = manager.process_world_boss()
            self.assertTrue(changed)
            self.assertIn("WB募集開始 / 試練の甲帝 / 120秒 / `!wb参加`", messages)

    def test_user_can_summon_world_boss_with_enhancement_materials(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES), patch(
            "rpg_core.world_boss_service.random.choices",
            return_value=["test_boss"],
        ):
            manager = RPGManager(
                {
                    "users": {
                        "alice": {
                            "materials": {
                                "weapon": 30,
                                "armor": 20,
                                "ring": 5,
                                "shoes": 0,
                            }
                        }
                    }
                }
            )

            ok, payload = manager.summon_world_boss("alice")

            self.assertTrue(ok)
            self.assertEqual(payload["headline"], "WB募集開始 / 試練の甲帝 / 120秒 / `!wb参加`")
            self.assertIn("alice がWBを召喚。", payload["reply"])
            self.assertIn("武器黒石x30", payload["reply"])
            self.assertIn("防具黒石x18", payload["reply"])
            user = manager.get_user("alice")
            self.assertEqual(user["materials"]["weapon"], 0)
            self.assertEqual(user["materials"]["armor"], 2)
            self.assertEqual(user["materials"]["ring"], 5)
            status = manager.get_world_boss_status("alice")
            self.assertEqual(status["phase"], "recruiting")
            self.assertIn("召喚: alice / 武器黒石x30 / 防具黒石x18", status["recent_logs"])

    def test_summon_world_boss_requires_enough_total_materials(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            manager = RPGManager(
                {
                    "users": {
                        "alice": {
                            "materials": {
                                "weapon": 10,
                                "armor": 12,
                                "ring": 6,
                                "shoes": 5,
                            }
                        }
                    }
                }
            )

            ok, payload = manager.summon_world_boss("alice")

            self.assertFalse(ok)
            self.assertIn("現在 33/48", payload["reply"])
            status = manager.get_world_boss_status("alice")
            self.assertEqual(status["phase"], "idle")


class WorldBossCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_owner_can_start_and_user_can_join_world_boss(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            bot = _WorldBossBot({"users": {"streamer": {}, "alice": {}}})
            commands = BasicCommands(bot)
            owner_ctx = _Ctx("streamer", "Streamer", "owner")
            alice_ctx = _Ctx("alice", "Alice", "viewer")

            await commands.world_boss_start.callback(commands, owner_ctx, boss_id="test_boss")
            await commands.world_boss_join.callback(commands, alice_ctx)

            self.assertEqual(bot.saved, 2)
            self.assertEqual(len(owner_ctx.replies), 1)
            self.assertIn("WB募集開始", owner_ctx.replies[0])
            self.assertEqual(len(alice_ctx.replies), 1)
            self.assertIn("参加しました", alice_ctx.replies[0])
            self.assertEqual(
                bot.world_boss_notifications,
                ["WB募集開始 / 試練の甲帝 / 120秒 / `!wb参加`"],
            )

            status = bot.rpg.get_world_boss_status("alice")
            self.assertEqual(status["phase"], "recruiting")
            self.assertEqual(status["participants"], 1)
            self.assertTrue(bot.overlays)
            overlay_title, overlay_lines = bot.overlays[-1]
            self.assertEqual(overlay_title, "Alice / !wb")
            self.assertIn("kv: 参加人数 | 1人", overlay_lines)

    async def test_user_can_summon_world_boss_from_wb_command(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES), patch(
            "rpg_core.world_boss_service.random.choices",
            return_value=["test_boss"],
        ):
            bot = _WorldBossBot(
                {
                    "users": {
                        "alice": {
                            "materials": {
                                "weapon": 28,
                                "armor": 20,
                                "ring": 8,
                                "shoes": 0,
                            }
                        }
                    }
                }
            )
            commands = BasicCommands(bot)
            alice_ctx = _Ctx("alice", "Alice", "viewer")

            await commands.world_boss_summon.callback(commands, alice_ctx)

            self.assertEqual(bot.saved, 1)
            self.assertEqual(
                bot.world_boss_notifications,
                ["WB募集開始 / 試練の甲帝 / 120秒 / `!wb参加`"],
            )
            self.assertEqual(len(alice_ctx.replies), 1)
            self.assertIn("Alice がWBを召喚。", alice_ctx.replies[0])
            self.assertIn("武器黒石x28", alice_ctx.replies[0])
            self.assertIn("防具黒石x20", alice_ctx.replies[0])
            status = bot.rpg.get_world_boss_status("alice")
            self.assertEqual(status["phase"], "recruiting")
            self.assertIn("召喚: Alice / 武器黒石x28 / 防具黒石x20", status["recent_logs"])

    async def test_user_can_join_world_boss_during_active_battle(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            bot = _WorldBossBot({"users": {"streamer": {}, "alice": {}, "bob": {}}})
            bot.rpg.users.get_player_stats = lambda _u, _mode_key: {
                "atk": 12,
                "def": 3,
                "speed": 100,
                "max_hp": 120,
            }
            bot.rpg.users.get_weapon_crit_stats = lambda _u: (0.0, 1.0)
            commands = BasicCommands(bot)
            owner_ctx = _Ctx("streamer", "Streamer", "owner")
            alice_ctx = _Ctx("alice", "Alice", "viewer-a")
            bob_ctx = _Ctx("bob", "Bob", "viewer-b")

            await commands.world_boss_start.callback(commands, owner_ctx, boss_id="test_boss")
            await commands.world_boss_join.callback(commands, alice_ctx)
            ok, _ = bot.rpg.world_boss.skip_recruiting(now=200.0)
            self.assertTrue(ok)

            await commands.world_boss_join.callback(commands, bob_ctx)

            status = bot.rpg.get_world_boss_status("bob")
            self.assertEqual(status["phase"], "active")
            self.assertEqual(status["participants"], 2)
            self.assertIsNotNone(status["self"])
            self.assertTrue(status["self"]["alive"])
            self.assertIn("途中参加しました", bob_ctx.replies[-1])
            self.assertIn("途中参加: Bob", status["recent_logs"])
            self.assertEqual(status["event_text"], "")
            self.assertFalse(status["race_focus_active"])
            self.assertTrue(bot.overlays)
            overlay_title, overlay_lines = bot.overlays[-1]
            self.assertEqual(overlay_title, "Bob / !wb")
            self.assertIn("kv: 参加人数 | 2人", overlay_lines)
            self.assertNotIn("kv: イベント | 途中参加: Bob", overlay_lines)
            self.assertFalse(any("総合貢献王争い" in line for line in overlay_lines))

    async def test_advice_recommends_world_boss_join_only_once_during_recruiting(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            bot = _WorldBossBot({"users": {"streamer": {}, "alice": {}}})
            commands = BasicCommands(bot)
            owner_ctx = _Ctx("streamer", "Streamer", "owner")
            alice_ctx = _Ctx("alice", "Alice", "viewer")

            await commands.world_boss_start.callback(commands, owner_ctx, boss_id="test_boss")
            await commands.advice.callback(commands, alice_ctx)
            await commands.advice.callback(commands, alice_ctx)

            self.assertEqual(bot.saved, 2)
            self.assertEqual(len(alice_ctx.replies), 2)
            self.assertIn("!wb 参加 でWBへ合流", alice_ctx.replies[0])
            self.assertNotIn("!wb 参加 でWBへ合流", alice_ctx.replies[1])
            self.assertIn("三日月廃墟", alice_ctx.replies[1])

    async def test_world_boss_leave_refreshes_overlay_participant_count(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            bot = _WorldBossBot({"users": {"streamer": {}, "alice": {}}})
            commands = BasicCommands(bot)
            owner_ctx = _Ctx("streamer", "Streamer", "owner")
            alice_ctx = _Ctx("alice", "Alice", "viewer")

            await commands.world_boss_start.callback(commands, owner_ctx, boss_id="test_boss")
            await commands.world_boss_join.callback(commands, alice_ctx)
            await commands.world_boss_leave.callback(commands, alice_ctx)

            self.assertGreaterEqual(bot.saved, 3)
            self.assertTrue(bot.overlays)
            overlay_title, overlay_lines = bot.overlays[-1]
            self.assertEqual(overlay_title, "Alice / !wb")
            self.assertIn("kv: 参加人数 | 0人", overlay_lines)
            self.assertTrue(alice_ctx.replies)
            self.assertIn("参加を取り消しました", alice_ctx.replies[-1])

    async def test_wb_result_command_publishes_detail_after_battle(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_WORLD_BOSSES):
            bot = _WorldBossBot({"users": {"streamer": {}, "alice": {}}})
            bot.rpg.users.get_player_stats = lambda _u, _mode_key: {
                "atk": 20,
                "def": 3,
                "speed": 100,
                "max_hp": 120,
            }
            bot.rpg.users.get_weapon_crit_stats = lambda _u: (0.0, 1.0)
            commands = BasicCommands(bot)
            owner_ctx = _Ctx("streamer", "Streamer", "owner")
            alice_ctx = _Ctx("alice", "Alice", "viewer")

            await commands.world_boss_start.callback(commands, owner_ctx, boss_id="test_boss")
            await commands.world_boss_join.callback(commands, alice_ctx)

            ok, _ = bot.rpg.world_boss.skip_recruiting(now=200.0)
            self.assertTrue(ok)
            bot.rpg.world_boss.process(now=202.0)

            await commands.world_boss_result.callback(commands, alice_ctx)

            self.assertTrue(bot.overlays)
            title, lines = bot.overlays[-1]
            self.assertEqual(title, "Alice / !wb 結果")
            text = "\n".join(lines)
            self.assertIn("試練の甲帝", text)
            self.assertIn("順位 #1", text)
            self.assertIn("貢献内訳", text)
            self.assertIn("試練殻片", text)
            self.assertTrue(alice_ctx.replies)
            self.assertIn("試練の甲帝", alice_ctx.replies[-1])

    async def test_process_world_boss_events_publishes_spawn_notification(self) -> None:
        class _ProcessBot:
            def __init__(self) -> None:
                self.saved = 0
                self.sent_messages = []
                self.world_boss_notifications = []
                self.visual_refreshes = 0
                self.log = type("Log", (), {"exception": lambda *_args, **_kwargs: None})()
                self.rpg = type(
                    "Rpg",
                    (),
                    {
                        "process_world_boss": lambda *_args, **_kwargs: (
                            ["WB募集開始 / 試練の甲帝 / 120秒 / `!wb参加`"],
                            True,
                        )
                    },
                )()

            def save_data(self) -> None:
                self.saved += 1

            def publish_world_boss_spawn_notification(self, headline: str) -> None:
                self.world_boss_notifications.append(headline)

            def refresh_world_boss_visual_html(self, *, force: bool = False) -> None:
                self.visual_refreshes += 1

            async def _send_channel_message(self, message: str, *, username=None) -> None:
                self.sent_messages.append((message, username))

        bot = _ProcessBot()

        await StreamBot._process_world_boss_events(bot)

        self.assertEqual(bot.saved, 1)
        self.assertEqual(
            bot.world_boss_notifications,
            ["WB募集開始 / 試練の甲帝 / 120秒 / `!wb参加`"],
        )
        self.assertEqual(
            bot.sent_messages,
            [("WB募集開始 / 試練の甲帝 / 120秒 / `!wb参加`", None)],
        )
        self.assertEqual(bot.visual_refreshes, 1)

    async def test_process_world_boss_events_enqueues_tts_for_non_spawn_messages(self) -> None:
        class _ProcessBot:
            def __init__(self) -> None:
                self.saved = 0
                self.sent_messages = []
                self.tts_messages = []
                self.world_boss_notifications = []
                self.visual_refreshes = 0
                self.log = type("Log", (), {"exception": lambda *_args, **_kwargs: None})()
                self.rpg = type(
                    "Rpg",
                    (),
                    {
                        "process_world_boss": lambda *_args, **_kwargs: (
                            ["WB残り30秒", "総合貢献王 Alice / 貢献 120 / 120ダメ"],
                            True,
                        ),
                        "get_world_boss_status": lambda *_args, **_kwargs: {
                            "boss": {"name": "試練の甲帝"}
                        },
                    },
                )()

            def save_data(self) -> None:
                self.saved += 1

            def publish_world_boss_spawn_notification(self, headline: str) -> None:
                self.world_boss_notifications.append(headline)

            def refresh_world_boss_visual_html(self, *, force: bool = False) -> None:
                self.visual_refreshes += 1

            def enqueue_tts_message(self, text: str) -> None:
                self.tts_messages.append(text)

            async def _send_channel_message(self, message: str, *, username=None) -> None:
                self.sent_messages.append((message, username))

        bot = _ProcessBot()

        with patch("bot.random.choice", side_effect=lambda seq: seq[0]):
            await StreamBot._process_world_boss_events(bot)

        self.assertEqual(bot.saved, 1)
        self.assertEqual(bot.world_boss_notifications, [])
        self.assertEqual(
            bot.tts_messages,
            [
                "残り30秒。手ぇ止めてる間抜けは戦犯だ",
                "総合貢献王は Alice。他の雑魚は背中だけ見てろ",
            ],
        )
        self.assertEqual(
            bot.sent_messages,
            [("WB残り30秒", None), ("総合貢献王 Alice / 貢献 120 / 120ダメ", None)],
        )
        self.assertEqual(bot.visual_refreshes, 1)

    def test_refresh_world_boss_visual_html_keeps_stage_visible_while_recruiting(self) -> None:
        overlay = _VisualOverlayRecorder()
        bot = type("Bot", (), {})()
        bot._detail_overlay = overlay
        bot._world_boss_visual_last_refresh_ts = 0.0
        bot._world_boss_visual_last_phase = "idle"
        bot._world_boss_visual_refresh_sec = 2.0
        bot.log = type("Log", (), {"exception": lambda *_args, **_kwargs: None})()
        bot._build_world_boss_ranking_summary = lambda ranking: StreamBot._build_world_boss_ranking_summary(
            bot, ranking
        )
        bot._build_world_boss_visual_overlay = lambda: StreamBot._build_world_boss_visual_overlay(bot)
        bot.rpg = type(
            "Rpg",
            (),
            {
                "get_world_boss_status": lambda *_args, **_kwargs: {
                    "phase": "recruiting",
                    "boss": {"name": "試練の甲帝", "title": "テスト用WB"},
                    "participants": 3,
                    "join_ends_at": 130.0,
                    "recent_logs": ["WB募集開始 / 試練の甲帝 / 120秒 / `!wb参加`"],
                    "ranking": [],
                },
                "format_duration": lambda *_args, **_kwargs: "30秒",
            },
        )()

        with patch("bot.now_ts", return_value=100.0):
            StreamBot.refresh_world_boss_visual_html(bot)

        self.assertEqual(len(overlay.calls), 1)
        title, lines = overlay.calls[0]
        text = "\n".join(lines)
        self.assertEqual(title, "ワールドボス / 試練の甲帝")
        self.assertIn("kv: WB | 試練の甲帝 / テスト用WB", text)
        self.assertIn("kv: 状態 | 募集中 / 残り 30秒", text)
        self.assertIn("kv: 参加人数 | 3人", text)
        self.assertEqual(bot._world_boss_visual_last_phase, "recruiting")

    def test_refresh_world_boss_visual_html_clears_stage_after_battle(self) -> None:
        overlay = _VisualOverlayRecorder()
        bot = type("Bot", (), {})()
        bot._detail_overlay = overlay
        bot._world_boss_visual_last_refresh_ts = 100.0
        bot._world_boss_visual_last_phase = "active"
        bot._world_boss_visual_refresh_sec = 2.0
        bot.log = type("Log", (), {"exception": lambda *_args, **_kwargs: None})()
        bot._build_world_boss_ranking_summary = lambda ranking: StreamBot._build_world_boss_ranking_summary(
            bot, ranking
        )
        bot._build_world_boss_visual_overlay = lambda: StreamBot._build_world_boss_visual_overlay(bot)
        bot.rpg = type(
            "Rpg",
            (),
            {
                "get_world_boss_status": lambda *_args, **_kwargs: {
                    "phase": "cooldown",
                    "boss": {"name": "試練の甲帝", "title": "テスト用WB"},
                    "cooldown_ends_at": 145.0,
                    "participants": 0,
                    "recent_logs": ["WB討伐成功 / 試練の甲帝"],
                    "ranking": [],
                },
                "format_duration": lambda *_args, **_kwargs: "45秒",
            },
        )()

        with patch("bot.now_ts", return_value=100.5):
            StreamBot.refresh_world_boss_visual_html(bot)

        self.assertEqual(len(overlay.calls), 1)
        _title, lines = overlay.calls[0]
        text = "\n".join(lines)
        self.assertIn("kv: 状態 | クールダウン / 残り 45秒", text)
        self.assertNotIn("kv: WB |", text)
        self.assertEqual(bot._world_boss_visual_last_phase, "cooldown")

    def test_refresh_world_boss_visual_html_passes_race_focus_meta(self) -> None:
        overlay = _VisualOverlayRecorder()
        bot = type("Bot", (), {})()
        bot._detail_overlay = overlay
        bot._world_boss_visual_last_refresh_ts = 0.0
        bot._world_boss_visual_last_phase = "active"
        bot._world_boss_visual_refresh_sec = 2.0
        bot.log = type("Log", (), {"exception": lambda *_args, **_kwargs: None})()
        bot._build_world_boss_ranking_summary = lambda ranking: StreamBot._build_world_boss_ranking_summary(
            bot, ranking
        )
        bot._build_world_boss_visual_overlay = lambda: StreamBot._build_world_boss_visual_overlay(bot)
        bot.rpg = type(
            "Rpg",
            (),
            {
                "get_world_boss_status": lambda *_args, **_kwargs: {
                    "phase": "active",
                    "phase_id": "last_stand",
                    "phase_label": "LAST STAND",
                    "event_kind": "ranking",
                    "event_text": "総合貢献王争い / #1 Alice 120 / #2 Bob 112 / 差 8",
                    "boss_id": "crimson_beetle_emperor",
                    "boss": {"name": "灼甲帝ヴァルカラン", "title": "紅蓮を喰らう甲殻王"},
                    "participants": 3,
                    "current_hp": 480,
                    "max_hp": 1500,
                    "ends_at": 122.0,
                    "recent_logs": ["WB残り30秒"],
                    "ranking": [
                        {"rank": 1, "display_name": "Alice", "total_contribution_score": 120},
                        {"rank": 2, "display_name": "Bob", "total_contribution_score": 112},
                    ],
                    "leader_name": "Alice",
                    "leader_score": 120,
                    "runner_up_name": "Bob",
                    "runner_up_score": 112,
                    "leader_gap": 8,
                    "race_focus_active": True,
                },
                "format_duration": lambda *_args, **_kwargs: "22秒",
            },
        )()

        with patch("bot.now_ts", return_value=100.0):
            StreamBot.refresh_world_boss_visual_html(bot)

        self.assertEqual(len(overlay.calls), 1)
        _title, lines = overlay.calls[0]
        text = "\n".join(lines)
        self.assertIn("meta: wb_phase | active", text)
        self.assertIn("meta: wb_phase_id | last_stand", text)
        self.assertIn("meta: wb_boss_id | crimson_beetle_emperor", text)
        self.assertIn("meta: wb_event_kind | ranking", text)
        self.assertIn("meta: wb_race_focus_active | 1", text)
        self.assertIn("meta: wb_race_text | #1 Alice 120 / #2 Bob 112 / 差 8", text)


if __name__ == "__main__":
    unittest.main()
