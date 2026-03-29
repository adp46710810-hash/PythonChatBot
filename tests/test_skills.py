from __future__ import annotations

import unittest
from unittest.mock import patch

from bot_components.rpg_commands import BasicCommands
from rpg_core import balance_data
from rpg_core.manager import RPGManager
from rpg_core.user_service import UserService


TEST_SKILL_WORLD_BOSSES = {
    "skill_boss": {
        "boss_id": "skill_boss",
        "name": "試技の巨兵",
        "title": "スキル検証用WB",
        "max_hp": 50,
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


def _skill_book_key(skill_id: str) -> str:
    return f"skill_book:{skill_id}"


class _SkillBot:
    owner_id = "owner"

    def __init__(self, data) -> None:
        self.rpg = RPGManager(data)
        self.saved = 0
        self.overlays = []

    def save_data(self) -> None:
        self.saved += 1

    def show_detail_overlay(self, title, lines) -> None:
        self.overlays.append((title, lines))


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


class SkillSystemTests(unittest.TestCase):
    def _build_user_data(self, *, exp: int, materials: dict | None = None) -> dict:
        return {
            "adventure_exp": exp,
            "starter_kit_granted": True,
            "equipped": {"weapon": None, "armor": None, "ring": None, "shoes": None},
            "potions": 0,
            "world_boss_materials": dict(materials or {}),
        }

    def test_starter_passive_skills_are_owned_and_equipped_by_default(self) -> None:
        manager = RPGManager({"users": {"alice": self._build_user_data(exp=0)}})
        user = manager.get_user("alice")

        selected_passives = manager.get_selected_passive_skills(user)
        passive_skills = manager.get_unlocked_passive_skills(user)
        active_skills = manager.get_unlocked_active_skills(user)

        self.assertEqual(
            [skill["name"] for skill in passive_skills],
            ["闘気", "鉄壁"],
        )
        self.assertEqual(
            [skill["name"] for skill in selected_passives],
            ["闘気", "鉄壁"],
        )
        self.assertEqual(passive_skills[0]["skill_level"], 1)
        self.assertEqual(passive_skills[1]["skill_level"], 1)
        self.assertIsNone(passive_skills[0]["max_level"])
        self.assertIsNone(manager.get_selected_active_skill(user))
        self.assertEqual(active_skills, [])

    def test_set_selected_active_skill_rejects_passive_skill(self) -> None:
        manager = RPGManager({"users": {"alice": self._build_user_data(exp=0)}})

        ok, message = manager.set_selected_active_skill("alice", "鉄壁")

        self.assertFalse(ok)
        self.assertIn("パッシブ", message)

    def test_exploration_battle_uses_starter_passive_bonus(self) -> None:
        manager = RPGManager({"users": {"alice": self._build_user_data(exp=68)}})
        user = manager.get_user("alice")

        mode = manager.resolve_exploration_mode("normal")
        manager.exploration.pick_monster = lambda _area_name: {
            "name": "訓練木人",
            "hp": 40,
            "atk": 0,
            "def": 0,
            "exp": 1,
            "gold": 1,
            "drop_rate": 0.0,
        }
        manager.exploration._grant_beginner_equipment_set = lambda *_args, **_kwargs: None
        manager.items.roll_equipment_for_monster = lambda *_args, **_kwargs: None
        manager.items.get_material_drop_for_monster = lambda *_args, **_kwargs: {}
        manager.items.get_enchantment_drop_for_monster = lambda *_args, **_kwargs: {}
        manager.items.roll_auto_explore_stone = lambda: 0
        manager.battles.should_return_after_battle = lambda *_args, **_kwargs: True

        result = manager.simulate_exploration_result(user, "朝の森", mode)

        first_battle = result["battle_logs"][0]
        first_turn = first_battle["turn_details"][0]
        self.assertNotIn("スキル発動", first_turn["player_action"])
        self.assertIn("19ダメ", first_turn["player_action"])

    def test_exploration_battle_uses_starter_defense_passive_bonus(self) -> None:
        manager = RPGManager({"users": {"alice": self._build_user_data(exp=68)}})
        user = manager.get_user("alice")

        mode = manager.resolve_exploration_mode("normal")
        manager.exploration.pick_monster = lambda _area_name: {
            "name": "訓練木人",
            "hp": 40,
            "atk": 12,
            "def": 0,
            "exp": 1,
            "gold": 1,
            "drop_rate": 0.0,
        }
        manager.exploration._grant_beginner_equipment_set = lambda *_args, **_kwargs: None
        manager.items.roll_equipment_for_monster = lambda *_args, **_kwargs: None
        manager.items.get_material_drop_for_monster = lambda *_args, **_kwargs: {}
        manager.items.get_enchantment_drop_for_monster = lambda *_args, **_kwargs: {}
        manager.items.roll_auto_explore_stone = lambda: 0
        manager.battles.should_return_after_battle = lambda *_args, **_kwargs: True

        result = manager.simulate_exploration_result(user, "朝の森", mode)

        first_battle = result["battle_logs"][0]
        enemy_turn = next(
            (
                turn
                for turn in first_battle["turn_details"]
                if "訓練木人→自分" in str(turn.get("enemy_action", ""))
            ),
            None,
        )
        self.assertIsNotNone(enemy_turn)
        self.assertEqual(enemy_turn["enemy_action"], "訓練木人→自分 2ダメ")

    def test_upgrade_skill_consumes_world_boss_materials_and_raises_level(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": self._build_user_data(
                        exp=68,
                        materials={_skill_book_key("starter_battle_cry"): 1},
                    )
                }
            }
        )
        user = manager.get_user("alice")

        ok, _ = manager.upgrade_skill("alice", "闘気")
        self.assertTrue(ok)

        upgraded = manager.get_skill_state(user, "starter_battle_cry")
        self.assertIsInstance(upgraded, dict)
        self.assertEqual(upgraded["skill_level"], 2)
        self.assertEqual(upgraded["atk_bonus"], 6)
        self.assertEqual(user["world_boss_materials"][_skill_book_key("starter_battle_cry")], 0)

    def test_upgrade_skill_auto_uses_available_materials_until_blocked(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": self._build_user_data(
                        exp=68,
                        materials={_skill_book_key("starter_battle_cry"): 3},
                    )
                }
            }
        )
        user = manager.get_user("alice")

        ok, message = manager.upgrade_skill("alice", "闘気")

        self.assertTrue(ok)
        self.assertIn("Lv3", message)
        self.assertIn("2段階強化", message)
        upgraded = manager.get_skill_state(user, "starter_battle_cry")
        self.assertIsInstance(upgraded, dict)
        self.assertEqual(upgraded["skill_level"], 3)
        self.assertEqual(upgraded["atk_bonus"], 8)
        self.assertEqual(user["world_boss_materials"][_skill_book_key("starter_battle_cry")], 0)

    def test_upgrade_skill_legacy_skill_book_remains_usable_for_backward_compatibility(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": self._build_user_data(
                        exp=68,
                        materials={"skill_book": 1},
                    )
                }
            }
        )
        user = manager.get_user("alice")

        ok, _ = manager.upgrade_skill("alice", "闘気")

        self.assertTrue(ok)
        self.assertEqual(user["world_boss_materials"]["skill_book"], 0)

    def test_skill_state_supports_infinite_growth_beyond_defined_levels(self) -> None:
        manager = RPGManager({"users": {"alice": self._build_user_data(exp=68)}})
        user = manager.get_user("alice")
        user["skill_levels"]["starter_battle_cry"] = 7

        skill = manager.get_skill_state(user, "starter_battle_cry")

        self.assertIsInstance(skill, dict)
        self.assertEqual(skill["skill_level"], 7)
        self.assertEqual(skill["atk_bonus"], 16)
        self.assertEqual(skill["duration_turns"], 0)
        self.assertEqual(skill["duration_ticks"], 0)
        self.assertEqual(skill["next_level"], 8)
        self.assertEqual(
            skill["next_upgrade_costs"],
            {_skill_book_key("starter_battle_cry"): 7},
        )
        self.assertEqual(skill["level_description"], "常時ATK+16")
        self.assertFalse(skill["is_max_level"])

    def test_load_skills_supports_future_extension_metadata(self) -> None:
        raw_skills = {
            "passive_plunder_master": {
                "name": "収奪術",
                "type": "passive",
                "max_level": 1,
                "description": "将来の探索補助パッシブの受け皿",
                "levels": [
                    {
                        "description": "ドロップ率+5% / 素材+1抽選",
                        "special_effects": [
                            {
                                "kind": "drop_bonus",
                                "summary": "ドロップ率+5%",
                                "timing": "exploration_reward",
                                "target": "self",
                                "params": {
                                    "drop_rate_bonus": 0.05,
                                    "resource_roll_bonus": 1,
                                },
                                "tags": ["farming", "future"],
                            }
                        ],
                        "upgrade_costs": {},
                    }
                ],
            }
        }

        with patch("rpg_core.balance_data._load_json_file", return_value=raw_skills):
            loaded = balance_data._load_skills()

        skill = loaded["passive_plunder_master"]
        self.assertEqual(skill["max_level"], 1)
        self.assertEqual(skill["levels"][0]["special_effects"][0]["kind"], "drop_bonus")
        self.assertEqual(
            skill["levels"][0]["special_effects"][0]["params"],
            {"drop_rate_bonus": 0.05, "resource_roll_bonus": 1},
        )
        self.assertEqual(skill["levels"][0]["special_effects"][0]["tags"], ["farming", "future"])

    def test_skill_state_caps_explicit_max_level_with_growth_extensions(self) -> None:
        raw_skills = {
            "active_siege_break": {
                "name": "破城一閃",
                "type": "active",
                "max_level": 20,
                "description": "将来追加する高倍率単発の雛形",
                "levels": [
                    {
                        "description": "攻x2.00 / CT6",
                        "attack_multiplier": 2.0,
                        "duration_turns": 0,
                        "duration_ticks": 0,
                        "cooldown_actions": 6,
                        "upgrade_costs": {"skill_book": 1},
                    }
                ],
                "infinite_growth": {
                    "description_template": "攻x{attack_multiplier:.2f} / CT{cooldown_actions}",
                    "attack_multiplier_step": 0.05,
                    "attack_multiplier_every": 2,
                    "cooldown_actions_step": -1,
                    "cooldown_actions_every": 6,
                    "upgrade_cost_steps": {"skill_book": 1},
                },
            }
        }

        with patch("rpg_core.balance_data._load_json_file", return_value=raw_skills):
            loaded = balance_data._load_skills()

        service = UserService(
            {
                "users": {
                    "alice": {
                        **self._build_user_data(exp=68),
                        "skill_levels": {"active_siege_break": 99},
                    }
                }
            }
        )

        with patch.dict("rpg_core.user_service.SKILLS", loaded, clear=False):
            user = service.get_user("alice")
            skill = service.get_skill_state(user, "active_siege_break")

        self.assertIsInstance(skill, dict)
        self.assertEqual(skill["skill_level"], 20)
        self.assertEqual(skill["max_level"], 20)
        self.assertTrue(skill["is_max_level"])
        self.assertAlmostEqual(skill["attack_multiplier"], 2.5)
        self.assertEqual(skill["cooldown_actions"], 2)
        self.assertIsNone(skill["next_level"])
        self.assertEqual(skill["level_description"], "攻x2.50 / CT2")

    def test_active_skill_state_clamps_to_level_twenty_with_new_progression(self) -> None:
        manager = RPGManager({"users": {"alice": self._build_user_data(exp=68)}})
        user = manager.get_user("alice")
        user["skill_levels"]["active_dormadakia"] = 25
        user["skill_levels"]["active_rundan"] = 25

        dormadakia = manager.get_skill_state(user, "active_dormadakia")
        rundan = manager.get_skill_state(user, "active_rundan")

        self.assertIsInstance(dormadakia, dict)
        self.assertIsInstance(rundan, dict)
        self.assertEqual(dormadakia["skill_level"], 20)
        self.assertEqual(dormadakia["max_level"], 20)
        self.assertTrue(dormadakia["is_max_level"])
        self.assertEqual(dormadakia["attack_multiplier"], 2.3)
        self.assertEqual(dormadakia["cooldown_actions"], 1)
        self.assertEqual(rundan["skill_level"], 20)
        self.assertEqual(rundan["max_level"], 20)
        self.assertTrue(rundan["is_max_level"])
        self.assertAlmostEqual(rundan["attack_multiplier"], 0.88)
        self.assertEqual(rundan["action_gauge_bonus"], 290)
        self.assertEqual(rundan["cooldown_actions"], 2)

    def test_rundan_attack_multiplier_grows_with_skill_level(self) -> None:
        manager = RPGManager(
            {"users": {"alice": self._build_user_data(exp=68, materials={_skill_book_key("active_rundan"): 7})}}
        )
        user = manager.get_user("alice")
        ok, _ = manager.upgrade_skill("alice", "ルンダン")
        self.assertTrue(ok)

        rundan = manager.get_skill_state(user, "active_rundan")
        self.assertIsInstance(rundan, dict)
        self.assertEqual(rundan["skill_level"], 3)
        self.assertAlmostEqual(rundan["attack_multiplier"], 0.54)

        battle = manager.battles.simulate_battle(
            120,
            50,
            5,
            {"name": "訓練木人", "hp": 120, "atk": 0, "def": 0, "speed": 1},
            max_hp=120,
            active_skills=manager.get_selected_active_skills(user),
            player_speed=100,
            enemy_speed=1,
        )

        first_turn = battle["turn_details"][0]
        self.assertIn("ルンダン", first_turn["player_action"])
        self.assertIn("自分→訓練木人 27ダメ", first_turn["player_action"])

    def test_new_passive_skills_can_be_selected_and_change_stats(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": self._build_user_data(
                        exp=68,
                        materials={
                            _skill_book_key("passive_hayate"): 2,
                            _skill_book_key("passive_life_pulse"): 2,
                        },
                    )
                }
            }
        )

        ok, _ = manager.upgrade_skill("alice", "疾風")
        self.assertTrue(ok)
        ok, _ = manager.upgrade_skill("alice", "生命脈動")
        self.assertTrue(ok)

        ok, _ = manager.set_selected_passive_skill("alice", "疾風")
        self.assertTrue(ok)
        user = manager.get_user("alice")
        selected_names = [skill["name"] for skill in manager.get_selected_passive_skills(user)]
        self.assertIn("疾風", selected_names)
        self.assertNotIn("生命脈動", selected_names)
        self.assertEqual(manager.get_player_speed(user), 108)

        ok, _ = manager.set_selected_passive_skill("alice", "生命脈動")
        self.assertTrue(ok)
        user = manager.get_user("alice")
        selected_names = [skill["name"] for skill in manager.get_selected_passive_skills(user)]
        self.assertIn("生命脈動", selected_names)
        self.assertNotIn("疾風", selected_names)
        self.assertEqual(manager.get_player_stats(user, None)["max_hp"], 114)

    def test_explicit_passive_loadout_can_reorder_slots(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        **self._build_user_data(exp=68),
                        "skill_levels": {
                            "passive_hayate": 1,
                            "passive_life_pulse": 1,
                        },
                    }
                }
            }
        )

        ok, message = manager.set_selected_skill_loadout(
            "alice",
            "passive",
            {1: "鉄壁", 2: "闘魂", 3: "迅雷"},
        )

        self.assertTrue(ok)
        self.assertIn("1:鉄壁", message)
        user = manager.get_user("alice")
        self.assertEqual(
            [skill["name"] for skill in manager.get_selected_passive_skills(user)],
            ["鉄壁", "闘気", "疾風"],
        )

    def test_explicit_active_loadout_can_set_multiple_slots(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        **self._build_user_data(exp=68),
                        "skill_levels": {
                            "active_crimson_focus": 1,
                            "active_siege_break": 1,
                            "active_star_guide": 1,
                        },
                    }
                }
            }
        )

        ok, message = manager.set_selected_skill_loadout(
            "alice",
            "active",
            {1: "星導", 2: "破城一閃", 3: "なし", 4: "なし"},
        )

        self.assertTrue(ok)
        self.assertIn("1:星導", message)
        user = manager.get_user("alice")
        self.assertEqual(
            [skill["name"] for skill in manager.get_selected_active_skills(user)],
            ["星導", "破城一閃"],
        )
        self.assertEqual(user["selected_skill_slots"]["active_3"], "")
        self.assertEqual(user["selected_skill_slots"]["active_4"], "")

    def test_crimson_focus_applies_attack_buff_before_next_hit(self) -> None:
        manager = RPGManager(
            {"users": {"alice": self._build_user_data(exp=68, materials={_skill_book_key("active_crimson_focus"): 2})}}
        )
        user = manager.get_user("alice")
        ok, _ = manager.upgrade_skill("alice", "紅蓮集中")
        self.assertTrue(ok)
        ok, _ = manager.set_selected_active_skill("alice", "紅蓮集中")
        self.assertTrue(ok)

        battle = manager.battles.simulate_battle(
            120,
            manager.get_player_stats(user, None)["atk"],
            manager.get_player_stats(user, None)["def"],
            {"name": "訓練木人", "hp": 90, "atk": 0, "def": 0},
            max_hp=manager.get_player_stats(user, None)["max_hp"],
            active_skills=manager.get_selected_active_skills(user),
            player_speed=manager.get_player_speed(user),
        )

        self.assertIn("紅蓮集中", battle["turn_details"][0]["player_action"])
        self.assertIn("27ダメ", battle["turn_details"][1]["player_action"])

    def test_siege_break_deals_heavier_single_hit_damage(self) -> None:
        manager = RPGManager(
            {"users": {"alice": self._build_user_data(exp=68, materials={_skill_book_key("active_siege_break"): 3})}}
        )
        user = manager.get_user("alice")
        ok, _ = manager.upgrade_skill("alice", "破城一閃")
        self.assertTrue(ok)
        ok, _ = manager.set_selected_active_skill("alice", "破城一閃")
        self.assertTrue(ok)

        battle = manager.battles.simulate_battle(
            120,
            manager.get_player_stats(user, None)["atk"],
            manager.get_player_stats(user, None)["def"],
            {"name": "訓練木人", "hp": 120, "atk": 0, "def": 0},
            max_hp=manager.get_player_stats(user, None)["max_hp"],
            active_skills=manager.get_selected_active_skills(user),
            player_speed=manager.get_player_speed(user),
        )

        self.assertIn("破城一閃", battle["turn_details"][0]["player_action"])
        self.assertIn("38ダメ", battle["turn_details"][0]["player_action"])

    def test_rekko_dan_ignores_portion_of_enemy_defense(self) -> None:
        manager = RPGManager(
            {"users": {"alice": self._build_user_data(exp=68, materials={_skill_book_key("active_rekko_dan"): 3})}}
        )
        user = manager.get_user("alice")
        ok, _ = manager.upgrade_skill("alice", "裂甲断")
        self.assertTrue(ok)
        ok, _ = manager.set_selected_active_skill("alice", "裂甲断")
        self.assertTrue(ok)

        battle = manager.battles.simulate_battle(
            120,
            manager.get_player_stats(user, None)["atk"],
            manager.get_player_stats(user, None)["def"],
            {"name": "重装木人", "hp": 60, "atk": 0, "def": 20},
            max_hp=manager.get_player_stats(user, None)["max_hp"],
            active_skills=manager.get_selected_active_skills(user),
            player_speed=manager.get_player_speed(user),
        )

        self.assertIn("裂甲断", battle["turn_details"][0]["player_action"])
        self.assertIn("防御50%無視", battle["turn_details"][0]["player_action"])
        self.assertIn("15ダメ", battle["turn_details"][0]["player_action"])

    def test_star_guide_reduces_total_turns_via_action_gauge_regen(self) -> None:
        manager = RPGManager(
            {"users": {"alice": self._build_user_data(exp=68, materials={_skill_book_key("active_star_guide"): 3})}}
        )
        user = manager.get_user("alice")
        ok, _ = manager.upgrade_skill("alice", "星導")
        self.assertTrue(ok)
        ok, _ = manager.set_selected_active_skill("alice", "星導")
        self.assertTrue(ok)

        player_stats = manager.get_player_stats(user, None)
        monster = {"name": "訓練木人", "hp": 160, "atk": 0, "def": 0}

        baseline = manager.battles.simulate_battle(
            120,
            player_stats["atk"],
            player_stats["def"],
            monster,
            max_hp=player_stats["max_hp"],
            player_speed=manager.get_player_speed(user),
        )
        accelerated = manager.battles.simulate_battle(
            120,
            player_stats["atk"],
            player_stats["def"],
            monster,
            max_hp=player_stats["max_hp"],
            active_skills=manager.get_selected_active_skills(user),
            player_speed=manager.get_player_speed(user),
        )

        self.assertIn("星導", accelerated["turn_details"][0]["player_action"])
        self.assertLess(accelerated["turns"], baseline["turns"])

    def test_world_boss_uses_upgraded_passive_bonus_in_tick_damage(self) -> None:
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", TEST_SKILL_WORLD_BOSSES):
            manager = RPGManager(
                {
                    "users": {
                        "alice": self._build_user_data(
                            exp=68,
                            materials={_skill_book_key("starter_battle_cry"): 1},
                        )
                    }
                }
            )
            user = manager.get_user("alice")
            ok, _ = manager.upgrade_skill("alice", "闘気")
            self.assertTrue(ok)
            manager.users.get_weapon_crit_stats = lambda _u: (0.0, 1.0)

            ok, _ = manager.world_boss.start_boss("skill_boss", now=0.0)
            self.assertTrue(ok)
            ok, _ = manager.world_boss.join_boss("alice", now=0.0)
            self.assertTrue(ok)

            recruiting_status = manager.get_world_boss_status("alice")
            player_atk = recruiting_status["self"]["snapshot_stats"]["atk"]
            self.assertEqual(
                player_atk,
                manager.get_player_stats(user, None)["atk"],
            )

            ok, _ = manager.world_boss.skip_recruiting(now=0.0)
            self.assertTrue(ok)
            manager.world_boss.process(now=2.0)

            active_status = manager.get_world_boss_status("alice")
            self.assertEqual(active_status["current_hp"], 50 - player_atk)

    def test_world_boss_rekko_dan_ignores_boss_defense(self) -> None:
        fortified_boss = {
            "skill_boss": {
                **TEST_SKILL_WORLD_BOSSES["skill_boss"],
                "def": 20,
            }
        }
        with patch("rpg_core.world_boss_service.WORLD_BOSSES", fortified_boss):
            manager = RPGManager(
                {
                    "users": {
                        "alice": self._build_user_data(
                            exp=68,
                            materials={_skill_book_key("active_rekko_dan"): 3},
                        )
                    }
                }
            )
            user = manager.get_user("alice")
            ok, _ = manager.upgrade_skill("alice", "裂甲断")
            self.assertTrue(ok)
            ok, _ = manager.set_selected_active_skill("alice", "裂甲断")
            self.assertTrue(ok)
            manager.users.get_weapon_crit_stats = lambda _u: (0.0, 1.0)

            ok, _ = manager.world_boss.start_boss("skill_boss", now=0.0)
            self.assertTrue(ok)
            ok, _ = manager.world_boss.join_boss("alice", now=0.0)
            self.assertTrue(ok)

            ok, _ = manager.world_boss.skip_recruiting(now=0.0)
            self.assertTrue(ok)
            manager.world_boss.process(now=2.0)

            active_status = manager.get_world_boss_status("alice")
            self.assertEqual(active_status["current_hp"], 50 - 15)

    def test_locked_active_skill_can_be_unlocked_with_skill_books(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": self._build_user_data(
                        exp=68,
                        materials={_skill_book_key("active_dormadakia"): 2},
                    )
                }
            }
        )
        user = manager.get_user("alice")

        ok, message = manager.upgrade_skill("alice", "ドルマダキア")

        self.assertTrue(ok)
        self.assertIn("解放", message)
        self.assertIn("ドルマダキア", [skill["name"] for skill in manager.get_unlocked_active_skills(user)])
        selected = manager.get_selected_active_skill(user)
        self.assertIsInstance(selected, dict)
        self.assertEqual(selected["name"], "ドルマダキア")
        self.assertEqual(user["world_boss_materials"][_skill_book_key("active_dormadakia")], 0)

    def test_exchange_world_boss_skill_books_consumes_materials(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": self._build_user_data(
                        exp=68,
                        materials={
                            "crimson_shell_fragment": 4,
                            "moon_core_shard": 3,
                        },
                    )
                }
            }
        )
        user = manager.get_user("alice")

        ok, message = manager.exchange_world_boss_skill_books("alice", "闘気")

        self.assertTrue(ok)
        self.assertIn("闘気の書", message)
        self.assertIn("2 冊", message)
        self.assertEqual(user["world_boss_materials"][_skill_book_key("starter_battle_cry")], 2)
        self.assertEqual(user["world_boss_materials"]["crimson_shell_fragment"], 0)
        self.assertEqual(user["world_boss_materials"]["moon_core_shard"], 0)

    def test_exchange_world_boss_skill_books_respects_requested_quantity(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": self._build_user_data(
                        exp=68,
                        materials={
                            "crimson_shell_fragment": 4,
                            "moon_core_shard": 3,
                        },
                    )
                }
            }
        )
        user = manager.get_user("alice")

        ok, message = manager.exchange_world_boss_skill_books("alice", "闘気", quantity=1)

        self.assertTrue(ok)
        self.assertIn("1 冊", message)
        self.assertEqual(user["world_boss_materials"][_skill_book_key("starter_battle_cry")], 1)
        self.assertEqual(user["world_boss_materials"]["crimson_shell_fragment"], 4)
        self.assertEqual(user["world_boss_materials"]["moon_core_shard"], 0)

    def test_dormadakia_scales_attack_damage_in_battle_log(self) -> None:
        manager = RPGManager(
            {"users": {"alice": self._build_user_data(exp=68, materials={_skill_book_key("active_dormadakia"): 2})}}
        )
        user = manager.get_user("alice")
        ok, _ = manager.upgrade_skill("alice", "ドルマダキア")
        self.assertTrue(ok)

        mode = manager.resolve_exploration_mode("normal")
        manager.exploration.pick_monster = lambda _area_name: {
            "name": "訓練木人",
            "hp": 80,
            "atk": 0,
            "def": 0,
            "exp": 1,
            "gold": 1,
            "drop_rate": 0.0,
        }
        manager.exploration._grant_beginner_equipment_set = lambda *_args, **_kwargs: None
        manager.items.roll_equipment_for_monster = lambda *_args, **_kwargs: None
        manager.items.get_material_drop_for_monster = lambda *_args, **_kwargs: {}
        manager.items.get_enchantment_drop_for_monster = lambda *_args, **_kwargs: {}
        manager.items.roll_auto_explore_stone = lambda: 0
        manager.battles.should_return_after_battle = lambda *_args, **_kwargs: True

        result = manager.simulate_exploration_result(user, "朝の森", mode)

        first_battle = result["battle_logs"][0]
        first_turn = first_battle["turn_details"][0]
        self.assertIn("ドルマダキア", first_turn["player_action"])
        self.assertIn("26ダメ", first_turn["player_action"])

    def test_rundan_adds_an_extra_action_in_same_turn(self) -> None:
        manager = RPGManager(
            {"users": {"alice": self._build_user_data(exp=68, materials={_skill_book_key("active_rundan"): 2})}}
        )
        user = manager.get_user("alice")
        ok, _ = manager.upgrade_skill("alice", "ルンダン")
        self.assertTrue(ok)

        battle = manager.battles.simulate_battle(
            120,
            19,
            5,
            {"name": "訓練木人", "hp": 60, "atk": 0, "def": 0, "speed": 1},
            max_hp=120,
            active_skills=manager.get_selected_active_skills(user),
            player_speed=100,
            enemy_speed=1,
        )

        first_turn = battle["turn_details"][0]
        self.assertIn("ルンダン", first_turn["player_action"])
        self.assertIn("自分→訓練木人 10ダメ", first_turn["player_action"])
        self.assertIn("自分→訓練木人 19ダメ", first_turn["player_action"])
        self.assertGreaterEqual(battle["action_count"], 2)

    def test_battle_allows_consecutive_actions_until_gauge_is_below_threshold(self) -> None:
        manager = RPGManager({"users": {"alice": self._build_user_data(exp=68)}})

        battle = manager.battles.simulate_battle(
            120,
            19,
            5,
            {"name": "訓練木人", "hp": 200, "atk": 0, "def": 0, "speed": 1},
            max_hp=120,
            player_speed=250,
            enemy_speed=1,
        )

        first_turn = battle["turn_details"][0]
        self.assertEqual(first_turn["enemy_action"], "行動なし")
        self.assertGreaterEqual(first_turn["player_action"].count("自分→訓練木人"), 2)
        self.assertGreaterEqual(battle["action_count"], 2)


class SkillCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_skill_commands_show_and_upgrade_passive_skill(self) -> None:
        bot = _SkillBot(
            {
                "users": {
                    "alice": {
                        "adventure_exp": 68,
                        "starter_kit_granted": True,
                        "equipped": {"weapon": None, "armor": None, "ring": None, "shoes": None},
                        "world_boss_materials": {_skill_book_key("starter_battle_cry"): 1},
                    }
                }
            }
        )
        commands = BasicCommands(bot)
        ctx = _Ctx("alice", "Alice", "viewer")

        await commands.skills.callback(commands, ctx)
        self.assertTrue(ctx.replies)
        self.assertIn("闘気 Lv1", ctx.replies[-1])
        self.assertTrue(bot.overlays)
        before_text = "\n".join(bot.overlays[-1][1])
        self.assertIn("鉄壁 Lv1", before_text)

        await commands.upgrade_skill.callback(commands, ctx, skill_name="闘気")
        self.assertTrue(ctx.replies)
        self.assertIn("Lv2", ctx.replies[-1])
        self.assertEqual(bot.saved, 1)

        user = bot.rpg.get_user("alice")
        upgraded = bot.rpg.get_skill_state(user, "starter_battle_cry")
        self.assertIsInstance(upgraded, dict)
        self.assertEqual(upgraded["skill_level"], 2)
        self.assertTrue(bot.overlays)
        _, lines = bot.overlays[-1]
        text = "\n".join(lines)
        self.assertIn("闘気 Lv2", text)
        self.assertIn("鉄壁 Lv1", text)
        self.assertIn("次強化:", text)

    async def test_skill_subcommand_router_can_upgrade_passive_skill(self) -> None:
        bot = _SkillBot(
            {
                "users": {
                    "alice": {
                        "adventure_exp": 68,
                        "starter_kit_granted": True,
                        "equipped": {"weapon": None, "armor": None, "ring": None, "shoes": None},
                        "world_boss_materials": {_skill_book_key("starter_battle_cry"): 1},
                    }
                }
            }
        )
        commands = BasicCommands(bot)
        ctx = _Ctx("alice", "Alice", "viewer")

        await commands.skills.callback(commands, ctx, args="強化 闘気")

        self.assertTrue(ctx.replies)
        self.assertIn("Lv2", ctx.replies[-1])
        self.assertEqual(bot.saved, 1)
        user = bot.rpg.get_user("alice")
        upgraded = bot.rpg.get_skill_state(user, "starter_battle_cry")
        self.assertIsInstance(upgraded, dict)
        self.assertEqual(upgraded["skill_level"], 2)

    async def test_skill_command_auto_upgrades_multiple_levels(self) -> None:
        bot = _SkillBot(
            {
                "users": {
                    "alice": {
                        "adventure_exp": 68,
                        "starter_kit_granted": True,
                        "equipped": {"weapon": None, "armor": None, "ring": None, "shoes": None},
                        "world_boss_materials": {_skill_book_key("starter_battle_cry"): 3},
                    }
                }
            }
        )
        commands = BasicCommands(bot)
        ctx = _Ctx("alice", "Alice", "viewer")

        await commands.upgrade_skill.callback(commands, ctx, skill_name="闘気")

        self.assertTrue(ctx.replies)
        self.assertIn("Lv3", ctx.replies[-1])
        self.assertIn("2段階強化", ctx.replies[-1])
        user = bot.rpg.get_user("alice")
        upgraded = bot.rpg.get_skill_state(user, "starter_battle_cry")
        self.assertIsInstance(upgraded, dict)
        self.assertEqual(upgraded["skill_level"], 3)

    async def test_skill_change_command_accepts_indexed_passive_loadout(self) -> None:
        bot = _SkillBot(
            {
                "users": {
                    "alice": {
                        "adventure_exp": 68,
                        "starter_kit_granted": True,
                        "equipped": {"weapon": None, "armor": None, "ring": None, "shoes": None},
                        "skill_levels": {
                            "passive_hayate": 1,
                            "passive_life_pulse": 1,
                        },
                    }
                }
            }
        )
        commands = BasicCommands(bot)
        ctx = _Ctx("alice", "Alice", "viewer")

        await commands.set_active_skill.callback(
            commands,
            ctx,
            skill_name="パッシブ 1 鉄壁 2 闘魂 3 迅雷",
        )

        self.assertTrue(ctx.replies)
        self.assertIn("パッシブ構成を変更", ctx.replies[-1])
        self.assertEqual(bot.saved, 1)
        user = bot.rpg.get_user("alice")
        self.assertEqual(
            [skill["name"] for skill in bot.rpg.get_selected_passive_skills(user)],
            ["鉄壁", "闘気", "疾風"],
        )

    async def test_skill_change_command_accepts_indexed_active_loadout(self) -> None:
        bot = _SkillBot(
            {
                "users": {
                    "alice": {
                        "adventure_exp": 68,
                        "starter_kit_granted": True,
                        "equipped": {"weapon": None, "armor": None, "ring": None, "shoes": None},
                        "skill_levels": {
                            "active_crimson_focus": 1,
                            "active_siege_break": 1,
                            "active_star_guide": 1,
                        },
                    }
                }
            }
        )
        commands = BasicCommands(bot)
        ctx = _Ctx("alice", "Alice", "viewer")

        await commands.set_active_skill.callback(
            commands,
            ctx,
            skill_name="アクティブ 1 星導 2 破城一閃 3 なし 4 なし",
        )

        self.assertTrue(ctx.replies)
        self.assertIn("アクティブ構成を変更", ctx.replies[-1])
        self.assertEqual(bot.saved, 1)
        user = bot.rpg.get_user("alice")
        self.assertEqual(
            [skill["name"] for skill in bot.rpg.get_selected_active_skills(user)],
            ["星導", "破城一閃"],
        )

    async def test_world_boss_shop_and_exchange_commands_work_for_skill_books(self) -> None:
        bot = _SkillBot(
            {
                "users": {
                    "alice": {
                        "adventure_exp": 68,
                        "starter_kit_granted": True,
                        "equipped": {"weapon": None, "armor": None, "ring": None, "shoes": None},
                        "world_boss_materials": {
                            "crimson_shell_fragment": 4,
                            "moon_core_shard": 3,
                        },
                    }
                }
            }
        )
        commands = BasicCommands(bot)
        ctx = _Ctx("alice", "Alice", "viewer")

        await commands.world_boss_shop.callback(commands, ctx)
        self.assertTrue(ctx.replies)
        self.assertIn("WBショップ", ctx.replies[-1])
        self.assertTrue(bot.overlays)
        before_text = "\n".join(bot.overlays[-1][1])
        self.assertIn("!wb 交換 闘気", before_text)
        self.assertIn("闘気の書", before_text)

        await commands.world_boss_exchange.callback(commands, ctx, item_name="闘気")
        self.assertTrue(ctx.replies)
        self.assertIn("2 冊交換", ctx.replies[-1])
        self.assertIn("闘気の書", ctx.replies[-1])
        self.assertEqual(bot.saved, 1)
        user = bot.rpg.get_user("alice")
        self.assertEqual(user["world_boss_materials"][_skill_book_key("starter_battle_cry")], 2)

    async def test_world_boss_exchange_command_accepts_requested_quantity(self) -> None:
        bot = _SkillBot(
            {
                "users": {
                    "alice": {
                        "adventure_exp": 68,
                        "starter_kit_granted": True,
                        "equipped": {"weapon": None, "armor": None, "ring": None, "shoes": None},
                        "world_boss_materials": {
                            "crimson_shell_fragment": 4,
                            "moon_core_shard": 3,
                        },
                    }
                }
            }
        )
        commands = BasicCommands(bot)
        ctx = _Ctx("alice", "Alice", "viewer")

        await commands.world_boss_exchange.callback(commands, ctx, item_name="闘気 1")

        self.assertTrue(ctx.replies)
        self.assertIn("1 冊交換", ctx.replies[-1])
        self.assertEqual(bot.saved, 1)
        user = bot.rpg.get_user("alice")
        self.assertEqual(user["world_boss_materials"][_skill_book_key("starter_battle_cry")], 1)
        self.assertEqual(user["world_boss_materials"]["crimson_shell_fragment"], 4)
        self.assertEqual(user["world_boss_materials"]["moon_core_shard"], 0)

    async def test_world_boss_exchange_subcommand_router_supports_rundan(self) -> None:
        bot = _SkillBot(
            {
                "users": {
                    "alice": {
                        "adventure_exp": 68,
                        "starter_kit_granted": True,
                        "equipped": {"weapon": None, "armor": None, "ring": None, "shoes": None},
                        "world_boss_materials": {
                            "crimson_shell_fragment": 4,
                            "moon_core_shard": 3,
                        },
                    }
                }
            }
        )
        commands = BasicCommands(bot)
        ctx = _Ctx("alice", "Alice", "viewer")

        await commands.world_boss_status.callback(commands, ctx, args="交換 ルンダン")

        self.assertTrue(ctx.replies)
        self.assertIn("2 冊交換", ctx.replies[-1])
        self.assertIn("ルンダンの書", ctx.replies[-1])
        self.assertEqual(bot.saved, 1)
        user = bot.rpg.get_user("alice")
        self.assertEqual(user["world_boss_materials"][_skill_book_key("active_rundan")], 2)


if __name__ == "__main__":
    unittest.main()
