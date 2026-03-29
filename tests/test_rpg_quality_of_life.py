from __future__ import annotations

import random
import unittest
from unittest.mock import patch

from rpg_core.battle_service import BattleService
from rpg_core.manager import RPGManager
from rpg_core.rules import ENHANCEMENT_POWER_GAIN, MAX_POTIONS_PER_EXPLORATION
from rpg_core.user_service import UserService


def _make_item(
    name: str,
    slot: str,
    power: int,
    *,
    rarity: str = "common",
    enchant: str | None = None,
) -> dict:
    return {
        "name": name,
        "slot": slot,
        "rarity": rarity,
        "power": power,
        "value": power * 10,
        "enhance": 0,
        "enhancement_gold_spent": 0,
        "enhancement_material_spent": 0,
        "enchant": enchant,
    }


def _organize_player(manager: RPGManager, username: str) -> None:
    changed = True
    while changed:
        changed = manager.autoequip_best(username)
    manager.sell_all_bag_items(username)


def _follow_recommendation_to_exploration(manager: RPGManager, username: str) -> None:
    slot_aliases = {
        "武器": "weapon",
        "防具": "armor",
        "装飾": "ring",
        "靴": "shoes",
    }

    for _ in range(12):
        recommendation = manager.build_next_recommendation(manager.get_user(username))
        action = str(recommendation.get("action", "") or "").strip()

        if action == "!整理" or action == "!装備 整理":
            _organize_player(manager, username)
            continue
        if action == "!蘇生" or action == "!状態 蘇生":
            ok, msg = manager.revive_user(username)
            if not ok:
                raise AssertionError(msg)
            continue
        if action == "!ポーション購入" or action == "!状態 ポーション":
            ok, msg = manager.buy_potions(username)
            if not ok:
                raise AssertionError(msg)
            continue
        if action.startswith("!探索 準備 "):
            slot_text = action.split(" ", 2)[-1].strip()
            slot_name = slot_aliases[slot_text]
            ok, msg = manager.prepare_exploration(username, slot_name)
            if not ok:
                raise AssertionError(msg)
            continue
        if action.startswith("!エンチャント ") or action.startswith("!装備 エンチャント "):
            slot_text = action.split(" ", 2)[-1].strip()
            slot_name = slot_aliases[slot_text]
            ok, msg = manager.enchant_equipped_item(username, slot_name)
            if not ok:
                raise AssertionError(msg)
            continue
        if action.startswith("!探索開始 "):
            area_text = action.split(" ", 1)[1].strip()
            ok, msg = manager.start_exploration(username, area_text)
            if not ok:
                raise AssertionError(msg)
            user = manager.get_user(username)
            user["explore"]["ends_at"] = 0
            manager.finalize_exploration(username)
            _organize_player(manager, username)
            return
        if action.startswith("!探索 開始 "):
            area_text = action.split(" ", 2)[2].strip()
            ok, msg = manager.start_exploration(username, area_text)
            if not ok:
                raise AssertionError(msg)
            user = manager.get_user(username)
            user["explore"]["ends_at"] = 0
            manager.finalize_exploration(username)
            _organize_player(manager, username)
            return

        raise AssertionError(f"Unhandled recommendation action: {action}")

    raise AssertionError("Recommendation loop did not reach exploration")


def _run_progression_trace(seed: int, max_runs: int = 80) -> dict:
    random.seed(seed)
    manager = RPGManager({"users": {}})
    username = f"sim{seed}"
    milestones: dict[str, int] = {}

    for run_count in range(1, max_runs + 1):
        _follow_recommendation_to_exploration(manager, username)
        user = manager.get_user(username)
        boss_clear_areas = {
            str(area_name).strip()
            for area_name in user.get("boss_clear_areas", [])
        }
        for area_name in (
            "朝の森",
            "三日月廃墟",
            "ヘッセ深部",
            "紅蓮の鉱山",
            "沈黙の城塞跡",
            "星影の祭壇",
        ):
            if area_name in boss_clear_areas and area_name not in milestones:
                milestones[area_name] = run_count
        if user.get("feature_unlocks", {}).get("auto_repeat", False):
            milestones.setdefault("auto_repeat", run_count)
            break

    return milestones


class RpgQualityOfLifeTests(unittest.TestCase):
    def test_user_service_backfills_new_fields_and_item_ids_for_legacy_user(self) -> None:
        service = UserService(
            {
                "users": {
                    "alice": {
                        "bag": [
                            _make_item("革の服", "armor", 5),
                            _make_item("鉄の指輪", "ring", 4),
                        ],
                        "equipped": {
                            "weapon": _make_item("鉄の剣", "weapon", 7),
                        },
                    }
                }
            }
        )

        user = service.get_user("alice")

        self.assertEqual(user["exploration_history"], [])
        self.assertEqual(user["protected_item_ids"], [])
        self.assertIsInstance(user["feature_unlocks"], dict)
        self.assertEqual(user["auto_explore_fragments"], 3)
        self.assertEqual(user["auto_potion_refill_target"], MAX_POTIONS_PER_EXPLORATION)
        self.assertTrue(user["feature_unlocks"].get("auto_repeat", False))
        self.assertIsNone(user["last_recommendation"])
        all_item_ids = [
            item["item_id"]
            for item in [*user["bag"], *[item for item in user["equipped"].values() if isinstance(item, dict)]]
        ]
        self.assertEqual(len(all_item_ids), len(set(all_item_ids)))
        self.assertTrue(all(item_id.startswith("itm-") for item_id in all_item_ids))
        self.assertTrue(
            all(
                int(item.get("enhancement_gold_spent", -1)) == 0
                for item in [*user["bag"], *[item for item in user["equipped"].values() if isinstance(item, dict)]]
            )
        )

    def test_user_service_formats_equipment_with_slot_stat_labels(self) -> None:
        service = UserService(
            {
                "users": {
                    "alice": {
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True, "shoes": True},
                        "equipped": {
                            "weapon": _make_item("鉄の剣", "weapon", 5),
                            "armor": _make_item("革の服", "armor", 4),
                            "ring": _make_item("石の指輪", "ring", 3),
                            "shoes": _make_item("旅人の靴", "shoes", 2),
                        },
                    }
                }
            }
        )

        user = service.get_user("alice")

        self.assertEqual(service.format_equipped_item(user, "weapon"), "鉄の剣(A5)")
        self.assertEqual(service.format_equipped_item(user, "armor"), "革の服(D4)")
        self.assertEqual(service.format_equipped_item(user, "ring"), "石の指輪(A3/D3)")
        self.assertEqual(service.format_equipped_item(user, "shoes"), "旅人の靴(S2)")
        self.assertEqual(service.format_item_brief(_make_item("旅人の靴", "shoes", 2)), "旅人の靴[靴 S2]")

    def test_autoequip_preserves_item_ids_when_bag_item_moves_to_equipped(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True},
                        "equipped": {
                            "weapon": _make_item("木の剣", "weapon", 3),
                            "armor": None,
                            "ring": None,
                        },
                        "bag": [
                            _make_item("鋼の剣", "weapon", 9),
                        ],
                    }
                }
            }
        )

        user = manager.get_user("alice")
        old_weapon_id = user["equipped"]["weapon"]["item_id"]
        new_weapon_id = user["bag"][0]["item_id"]

        changed = manager.autoequip_best("alice")

        self.assertTrue(changed)
        user = manager.get_user("alice")
        self.assertEqual(user["equipped"]["weapon"]["item_id"], new_weapon_id)
        self.assertIn(
            old_weapon_id,
            {item["item_id"] for item in user["bag"]},
        )

    def test_autoequip_prefers_higher_rarity_even_when_power_is_lower(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True},
                        "equipped": {
                            "weapon": _make_item("鍛えた木剣", "weapon", 12, rarity="common"),
                        },
                        "bag": [
                            _make_item("青銅の剣", "weapon", 8, rarity="rare"),
                        ],
                    }
                }
            }
        )

        changed = manager.autoequip_best("alice")

        self.assertTrue(changed)
        user = manager.get_user("alice")
        self.assertEqual(user["equipped"]["weapon"]["name"], "青銅の剣")
        self.assertEqual(user["equipped"]["weapon"]["rarity"], "rare")
        self.assertEqual({item["name"] for item in user["bag"]}, {"鍛えた木剣"})

    def test_sell_all_bag_items_refunds_enhancement_materials_and_gold(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "gold": 100,
                        "materials": {"weapon": 1, "armor": 0, "ring": 0, "shoes": 0},
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True, "shoes": True},
                        "equipped": {
                            "weapon": _make_item("鍛えた木剣", "weapon", 5, rarity="common"),
                        },
                        "bag": [],
                    }
                }
            }
        )

        user = manager.get_user("alice")
        before_gold = user["gold"]

        with patch("rpg_core.item_service.random.random", return_value=0.0):
            attempted, _ = manager.enhance_equipped_item("alice", "weapon")

        self.assertTrue(attempted)
        enhancement_cost = before_gold - user["gold"]
        self.assertEqual(user["equipped"]["weapon"]["enhancement_gold_spent"], enhancement_cost)
        self.assertEqual(user["equipped"]["weapon"]["enhancement_material_spent"], 1)
        enhanced_sale_value = user["equipped"]["weapon"]["value"]

        user["bag"].append(user["equipped"]["weapon"])
        user["equipped"]["weapon"] = None
        sold_count, gold = manager.sell_all_bag_items("alice")

        self.assertEqual(sold_count, 1)
        self.assertEqual(gold, enhanced_sale_value + enhancement_cost)
        self.assertEqual(user["gold"], 100 + enhanced_sale_value)
        self.assertEqual(user["materials"]["weapon"], 1)

    def test_enhance_equipped_item_uses_slot_stat_label_in_success_message(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "gold": 100,
                        "materials": {"weapon": 0, "armor": 0, "ring": 0, "shoes": 1},
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True, "shoes": True},
                        "equipped": {
                            "shoes": _make_item("旅人の靴", "shoes", 4),
                        },
                        "bag": [],
                    }
                }
            }
        )

        with patch("rpg_core.item_service.random.random", return_value=0.0):
            attempted, message = manager.enhance_equipped_item("alice", "shoes")

        self.assertTrue(attempted)
        self.assertIn("旅人の靴 強化成功!", message)
        self.assertIn(" / S5 / ", message)

    def test_autoequip_transfers_upgrade_state_to_higher_rarity_item_without_double_refund(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "gold": 100,
                        "materials": {"weapon": 1, "armor": 0, "ring": 0, "shoes": 0},
                        "enchant_materials": {"weapon": 1, "armor": 0, "ring": 0},
                        "feature_unlocks": {"enchanting": True},
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True, "shoes": True},
                        "equipped": {
                            "weapon": _make_item("鍛えた木剣", "weapon", 5, rarity="common"),
                        },
                        "bag": [
                            _make_item("銀の剣", "weapon", 4, rarity="epic"),
                        ],
                    }
                }
            }
        )

        user = manager.get_user("alice")
        before_gold = user["gold"]
        replacement_base_power = user["bag"][0]["power"]

        with patch("rpg_core.item_service.random.random", return_value=0.0):
            attempted, _ = manager.enhance_equipped_item("alice", "weapon")

        self.assertTrue(attempted)
        enchanted, _ = manager.enchant_equipped_item("alice", "weapon")
        self.assertTrue(enchanted)

        enhancement_cost = before_gold - user["gold"]
        changed = manager.autoequip_best("alice")

        self.assertTrue(changed)
        user = manager.get_user("alice")
        equipped_weapon = user["equipped"]["weapon"]
        old_weapon = next(item for item in user["bag"] if item["name"] == "鍛えた木剣")

        self.assertEqual(equipped_weapon["name"], "銀の剣")
        self.assertEqual(equipped_weapon["enhance"], 1)
        self.assertEqual(equipped_weapon["enchant"], "weapon")
        self.assertEqual(equipped_weapon["enhancement_gold_spent"], enhancement_cost)
        self.assertEqual(equipped_weapon["enhancement_material_spent"], 1)
        self.assertEqual(equipped_weapon["power"], replacement_base_power + ENHANCEMENT_POWER_GAIN["weapon"])

        self.assertEqual(old_weapon["enhance"], 0)
        self.assertIsNone(old_weapon["enchant"])
        self.assertEqual(old_weapon["enhancement_gold_spent"], 0)
        self.assertEqual(old_weapon["enhancement_material_spent"], 0)
        self.assertEqual(old_weapon["power"], 5)

        sold_count, gold = manager.sell_all_bag_items("alice")

        self.assertEqual(sold_count, 1)
        self.assertEqual(gold, old_weapon["value"])
        self.assertEqual(user["gold"], 100 - enhancement_cost + old_weapon["value"])
        self.assertEqual(user["materials"]["weapon"], 0)

    def test_exploration_history_is_capped_to_latest_five_entries(self) -> None:
        service = UserService({"users": {"alice": {}}})
        user = service.get_user("alice")

        for index in range(6):
            service.append_exploration_history(
                user,
                {
                    "claimed_at": float(index),
                    "area": "朝の森",
                    "mode": "normal",
                    "exp": index,
                    "gold": index * 2,
                    "drop_items": [],
                    "drop_materials": {"weapon": 0, "armor": 0, "ring": 0},
                    "drop_enchant_materials": {"weapon": 0, "armor": 0, "ring": 0},
                    "battle_logs": [],
                    "battle_count": index,
                    "total_turns": index,
                    "returned_safe": True,
                    "downed": False,
                    "return_reason": "探索終了",
                    "potions_used": 0,
                    "armor_guards_used": 0,
                    "armor_guards_total": 0,
                    "armor_enchant_consumed": False,
                    "exploration_runs": 1,
                },
            )

        history = service.get_exploration_history(user, include_fallback=False)
        self.assertEqual(len(history), 5)
        self.assertEqual(history[0]["claimed_at"], 5.0)
        self.assertEqual(history[-1]["claimed_at"], 1.0)

    def test_sell_all_bag_items_keeps_only_legendary_and_protected_items(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True},
                        "bag": [
                            _make_item("売る剣", "weapon", 2),
                            _make_item("売るレア剣", "weapon", 5, rarity="rare"),
                            _make_item("売るエンチャ指輪", "ring", 4, enchant="ring"),
                            _make_item("残すレジェ服", "armor", 9, rarity="legendary"),
                            _make_item("残す保護服", "armor", 3),
                        ],
                    }
                }
            }
        )

        user = manager.get_user("alice")
        legendary_item = next(item for item in user["bag"] if item["rarity"] == "legendary")
        protected_item = next(item for item in user["bag"] if item["name"] == "残す保護服")
        changed = manager.set_item_protection("alice", protected_item["item_id"], True)

        self.assertTrue(changed)
        sold_count, gold = manager.sell_all_bag_items("alice")

        self.assertEqual(sold_count, 3)
        self.assertEqual(gold, 110)
        user = manager.get_user("alice")
        remaining_names = {item["name"] for item in user["bag"]}
        self.assertEqual(
            remaining_names,
            {legendary_item["name"], "残す保護服"},
        )

    def test_sell_all_bag_items_keeps_items_for_locked_slots(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "slot_unlocks": {"weapon": True, "armor": False, "ring": False},
                        "boss_clear_areas": [],
                        "bag": [
                            _make_item("売る剣", "weapon", 2),
                            _make_item("残す防具", "armor", 4),
                            _make_item("残す指輪", "ring", 3),
                        ],
                    }
                }
            }
        )

        sold_count, gold = manager.sell_all_bag_items("alice")

        self.assertEqual(sold_count, 1)
        self.assertEqual(gold, 20)
        user = manager.get_user("alice")
        remaining_names = {item["name"] for item in user["bag"]}
        self.assertEqual(remaining_names, {"残す防具", "残す指輪"})

    def test_build_next_recommendation_guides_new_user_to_morning_forest_unlock(self) -> None:
        manager = RPGManager({"users": {}})
        user = manager.get_user("alice")

        recommendation = manager.build_next_recommendation(user)

        self.assertEqual(recommendation["action"], "!探索 開始 慎重 朝の森")
        self.assertIn("防具・装飾", recommendation["reason"])

    def test_build_next_recommendation_switches_to_normal_after_three_morning_runs(self) -> None:
        manager = RPGManager({"users": {}})
        user = manager.get_user("alice")
        user["exploration_history"] = [
            {"area": "朝の森", "mode": "cautious"},
            {"area": "朝の森", "mode": "cautious"},
            {"area": "朝の森", "mode": "cautious"},
        ]

        recommendation = manager.build_next_recommendation(user)

        self.assertEqual(recommendation["action"], "!探索 開始 朝の森")
        self.assertIn("防具・装飾", recommendation["reason"])

    def test_build_next_recommendation_recovers_in_morning_forest_after_low_progress_stall(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "starter_kit_granted": True,
                        "gold": 0,
                        "potions": 0,
                        "hp": 120,
                        "max_hp": 320,
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True, "shoes": True},
                        "boss_clear_areas": ["朝の森"],
                        "exploration_history": [
                            {"area": "三日月廃墟", "mode": "normal", "battle_count": 0},
                            {"area": "三日月廃墟", "mode": "normal", "battle_count": 1},
                        ],
                    }
                }
            }
        )

        recommendation = manager.build_next_recommendation(manager.get_user("alice"))

        self.assertEqual(recommendation["action"], "!探索 開始 慎重 朝の森")
        self.assertIn("立て直す", recommendation["summary"])
        self.assertIn("三日月廃墟", recommendation["reason"])

    def test_build_next_recommendation_prefers_organize_when_upgrade_is_waiting(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True},
                        "equipped": {
                            "weapon": _make_item("古い剣", "weapon", 3),
                            "armor": _make_item("革鎧", "armor", 3),
                            "ring": _make_item("木の指輪", "ring", 3),
                        },
                        "bag": [
                            _make_item("新しい剣", "weapon", 8),
                        ],
                    }
                }
            }
        )

        user = manager.get_user("alice")

        recommendation = manager.build_next_recommendation(user)

        self.assertEqual(recommendation["action"], "!装備 整理")

    def test_build_next_recommendation_prefers_organize_for_higher_rarity_upgrade(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True},
                        "equipped": {
                            "weapon": _make_item("鍛えた木剣", "weapon", 12, rarity="common"),
                        },
                        "bag": [
                            _make_item("銀の剣", "weapon", 8, rarity="epic"),
                        ],
                    }
                }
            }
        )

        user = manager.get_user("alice")

        recommendation = manager.build_next_recommendation(user)

        self.assertEqual(recommendation["action"], "!装備 整理")
        self.assertIn("武器", recommendation["summary"])
        self.assertIn("更新候補", recommendation["reason"])

    def test_manager_grants_starter_weapon_and_potions_once_for_new_user(self) -> None:
        manager = RPGManager({"users": {}})

        user = manager.get_user("alice")
        starter_weapon = user["equipped"]["weapon"]

        self.assertIsNotNone(starter_weapon)
        self.assertEqual(starter_weapon["slot"], "weapon")
        self.assertEqual(user["potions"], 2)
        self.assertTrue(user["starter_kit_granted"])

        starter_item_id = starter_weapon["item_id"]
        user_again = manager.get_user("alice")
        self.assertEqual(user_again["equipped"]["weapon"]["item_id"], starter_item_id)
        self.assertEqual(user_again["potions"], 2)

    def test_exploration_duration_uses_turn_based_value_by_default(self) -> None:
        manager = RPGManager({"users": {}})

        self.assertEqual(manager.calculate_exploration_duration(3), 30)

    def test_exploration_duration_uses_turn_based_value_when_override_disabled(self) -> None:
        manager = RPGManager({"users": {}})

        with patch("rpg_core.exploration_service.EXPLORATION_DURATION_OVERRIDE_SEC", None):
            self.assertEqual(manager.calculate_exploration_duration(3), 30)

    def test_exploration_duration_override_only_applies_when_positive(self) -> None:
        manager = RPGManager({"users": {}})

        with patch("rpg_core.exploration_service.EXPLORATION_DURATION_OVERRIDE_SEC", 5):
            self.assertEqual(manager.calculate_exploration_duration(3), 5)

        with patch("rpg_core.exploration_service.EXPLORATION_DURATION_OVERRIDE_SEC", 0):
            self.assertEqual(manager.calculate_exploration_duration(3), 30)

    def test_speed_200_allows_two_actions_in_one_turn(self) -> None:
        battle_service = BattleService()

        with patch("rpg_core.battle_service.random.random", return_value=1.0):
            battle = battle_service.simulate_battle(
                30,
                20,
                0,
                {"name": "訓練木人", "hp": 30, "atk": 5, "def": 0, "speed": 100},
                max_hp=30,
                player_speed=200,
                enemy_speed=100,
            )

        self.assertTrue(battle["won"])
        self.assertEqual(battle["turns"], 1)
        self.assertEqual(battle["action_count"], 2)
        self.assertEqual(len(battle["turn_details"]), 1)
        self.assertEqual(battle["turn_details"][0]["enemy_action"], "行動なし")
        self.assertEqual(
            battle["turn_details"][0]["player_action"].count("自分→訓練木人"),
            2,
        )

    def test_exploration_duration_uses_turn_count_not_action_count(self) -> None:
        manager = RPGManager({"users": {}})

        self.assertEqual(manager.calculate_exploration_duration(1), 10)

    def test_build_next_recommendation_suggests_potion_refill_when_low(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "gold": 300,
                        "potions": 0,
                        "starter_kit_granted": True,
                    }
                }
            }
        )

        recommendation = manager.build_next_recommendation(manager.get_user("alice"))

        self.assertEqual(recommendation["action"], "!状態 ポーション")
        self.assertIn("補充", recommendation["summary"])

    def test_build_next_recommendation_suggests_weapon_enchant_when_material_is_ready(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "gold": 0,
                        "potions": 3,
                        "starter_kit_granted": True,
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True},
                        "feature_unlocks": {"enchanting": True},
                        "equipped": {
                            "weapon": _make_item("鉄の剣", "weapon", 8),
                            "armor": _make_item("革鎧", "armor", 6),
                            "ring": _make_item("銀の指輪", "ring", 5),
                        },
                        "enchant_materials": {"weapon": 1, "armor": 0, "ring": 0},
                    }
                }
            }
        )

        recommendation = manager.build_next_recommendation(manager.get_user("alice"))

        self.assertEqual(recommendation["action"], "!エンチャント 武器")
        self.assertIn("火力補強", recommendation["summary"])

    def test_build_next_recommendation_prioritizes_fragments_after_weapon_enchant_once(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "gold": 0,
                        "potions": 3,
                        "starter_kit_granted": True,
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True},
                        "feature_unlocks": {"enchanting": True},
                        "boss_clear_areas": ["朝の森", "三日月廃墟"],
                        "equipped": {
                            "weapon": _make_item("鉄の剣", "weapon", 8, enchant="weapon"),
                            "armor": _make_item("革鎧", "armor", 6),
                            "ring": _make_item("銀の指輪", "ring", 5),
                        },
                        "enchant_progress": {"weapon": True},
                        "enchant_materials": {"weapon": 0, "armor": 0, "ring": 0},
                    }
                }
            }
        )

        recommendation = manager.build_next_recommendation(manager.get_user("alice"))

        self.assertEqual(recommendation["action"], "!探索 開始 ヘッセ深部")
        self.assertIn("欠片", recommendation["summary"])

    def test_start_exploration_accepts_saving_mode_alias(self) -> None:
        manager = RPGManager({"users": {}})

        ok, msg = manager.start_exploration("alice", "節約モード 朝の森")

        self.assertTrue(ok)
        self.assertIn("節約モード", msg)
        user = manager.get_user("alice")
        self.assertEqual(user["explore"]["mode"], "saving")

    def test_prepare_exploration_consumes_material_and_marks_slot_ready(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "starter_kit_granted": True,
                        "materials": {"weapon": 10, "armor": 0, "ring": 0, "shoes": 0},
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True, "shoes": True},
                    }
                }
            }
        )

        ok, msg = manager.prepare_exploration("alice", "weapon")

        self.assertTrue(ok)
        self.assertIn("武器 の探索準備", msg)
        user = manager.get_user("alice")
        self.assertEqual(user["materials"]["weapon"], 2)
        self.assertTrue(user["exploration_preparation"]["weapon"])
        self.assertIn("武器(A+6)", manager.format_exploration_preparation_status(user))

    def test_start_exploration_consumes_preparation_and_mentions_it(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "starter_kit_granted": True,
                        "materials": {"weapon": 8, "armor": 0, "ring": 0, "shoes": 0},
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True, "shoes": True},
                    }
                }
            }
        )

        ok, msg = manager.prepare_exploration("alice", "weapon")
        self.assertTrue(ok)

        captured: dict[str, object] = {}
        template = manager.exploration._build_auto_repeat_result_template("朝の森", "normal")
        template["battle_count"] = 1
        template["total_turns"] = 1
        template["hp_after"] = 70

        def fake_simulation(_u, _area_name, _mode, preparation=None):
            captured["preparation"] = preparation
            return dict(template)

        manager.exploration.simulate_exploration_result = fake_simulation

        ok, start_message = manager.start_exploration("alice", "朝の森")

        self.assertTrue(ok)
        self.assertIn("準備:武器(A+6)", start_message)
        self.assertEqual(captured["preparation"]["atk"], 6)
        user = manager.get_user("alice")
        self.assertFalse(user["exploration_preparation"]["weapon"])

    def test_ring_preparation_boosts_exploration_rewards(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "starter_kit_granted": True,
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True, "shoes": True},
                        "equipped": {
                            "weapon": _make_item("鉄の剣", "weapon", 5),
                            "armor": _make_item("革鎧", "armor", 4),
                            "ring": _make_item("銀の指輪", "ring", 3),
                            "shoes": _make_item("旅人の靴", "shoes", 2),
                        },
                    }
                }
            }
        )
        user = manager.get_user("alice")
        mode = manager.resolve_exploration_mode("normal")
        preparation = {
            "slots": ["ring"],
            "atk": 0,
            "def": 0,
            "speed": 0,
            "exp_rate": 1.08,
            "gold_rate": 1.08,
            "drop_bonus": 0.03,
            "summary": "装飾(EXP+8% / Gold+8% / Drop+3%)",
        }

        manager.users.get_player_stats = lambda _u, _mode_key: {
            "atk": 999,
            "def": 999,
            "speed": 100,
            "max_hp": 70,
        }
        manager.users.get_weapon_crit_stats = lambda _u: (0.0, 1.0)
        manager.users.get_armor_lethal_guard_count = lambda _u: 0
        manager.users.get_ring_exploration_rates = lambda _u: (1.0, 1.0, 0.0)
        manager.users.get_adventure_level = lambda _u: 1
        manager.exploration.get_area_exp_rate = lambda _area_name, _player_level: 1.0
        manager.exploration.pick_monster = lambda _area_name: {
            "name": "検証スライム",
            "hp": 1,
            "atk": 0,
            "def": 0,
            "exp": 4,
            "gold": 10,
            "drop_rate": 0.0,
            "speed": 100,
        }
        manager.exploration._grant_beginner_equipment_set = lambda *_args, **_kwargs: None
        manager.items.roll_equipment_for_monster = lambda *_args, **_kwargs: None
        manager.items.get_material_drop_for_monster = lambda *_args, **_kwargs: {}
        manager.items.get_enchantment_drop_for_monster = lambda *_args, **_kwargs: {}
        manager.items.roll_auto_explore_stone = lambda: 0
        manager.battles.should_start_battle = lambda *_args, **_kwargs: True
        manager.battles.simulate_battle = lambda *_args, **_kwargs: {
            "player_hp_after": 70,
            "potions_used": 0,
            "guards_left": 0,
            "turns": 1,
            "damage_taken": 0,
            "won": True,
            "escaped": False,
            "log": [],
            "turn_details": [],
        }
        manager.battles.should_return_after_battle = lambda *_args, **_kwargs: True

        baseline = manager.simulate_exploration_result(
            user,
            "朝の森",
            mode,
        )
        result = manager.simulate_exploration_result(
            user,
            "朝の森",
            mode,
            preparation=preparation,
        )

        self.assertGreater(result["exp"], baseline["exp"])
        self.assertGreater(result["gold"], baseline["gold"])
        self.assertEqual(result["exploration_preparation"]["drop_bonus"], 0.03)

    def test_build_next_recommendation_suggests_exploration_preparation_when_materials_are_ready(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "gold": 0,
                        "potions": 3,
                        "starter_kit_granted": True,
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True, "shoes": True},
                        "feature_unlocks": {
                            "enchanting": True,
                            "auto_repeat_route": True,
                            "auto_repeat": True,
                        },
                        "equipped": {
                            "weapon": _make_item("鉄の剣", "weapon", 4, enchant="weapon"),
                            "armor": _make_item("革鎧", "armor", 8, enchant="armor"),
                            "ring": _make_item("銀の指輪", "ring", 7, enchant="ring"),
                            "shoes": _make_item("旅人の靴", "shoes", 5),
                        },
                        "materials": {"weapon": 8, "armor": 0, "ring": 0, "shoes": 0},
                        "enchant_materials": {"weapon": 1, "armor": 0, "ring": 0},
                    }
                }
            }
        )

        recommendation = manager.build_next_recommendation(manager.get_user("alice"))

        self.assertEqual(recommendation["action"], "!探索 準備 武器")
        self.assertIn("底上げ", recommendation["summary"])

    def test_existing_user_backfills_first_clear_feature_rewards_once(self) -> None:
        service = UserService(
            {
                "users": {
                    "alice": {
                        "boss_clear_areas": ["三日月廃墟"],
                    }
                }
            }
        )

        user = service.get_user("alice")

        self.assertTrue(user["feature_unlocks"].get("enchanting", False))
        self.assertEqual(user["claimed_first_clear_reward_areas"], ["三日月廃墟"])

        result = service.claim_area_first_clear_rewards(user, "三日月廃墟")

        self.assertEqual(result["newly_unlocked_features"], [])
        self.assertEqual(result["reward_summaries"], [])
        self.assertEqual(user["claimed_first_clear_reward_areas"], ["三日月廃墟"])

    def test_auto_repeat_unlock_requires_route_and_three_fragments(self) -> None:
        service = UserService({"users": {}})
        user = service.get_user("alice")

        for area_name in ("ヘッセ深部", "紅蓮の鉱山", "沈黙の城塞跡"):
            service.register_boss_clear(user, area_name)
            reward_result = service.claim_area_first_clear_rewards(user, area_name)
            self.assertNotIn("auto_repeat", reward_result["newly_unlocked_features"])

        progress = service.get_auto_repeat_progress(user)
        self.assertFalse(progress["unlocked"])
        self.assertFalse(progress["route_unlocked"])
        self.assertEqual(progress["fragments"], 3)
        self.assertEqual(progress["required_fragments"], 3)

        service.register_boss_clear(user, "星影の祭壇")
        reward_result = service.claim_area_first_clear_rewards(user, "星影の祭壇")

        self.assertTrue(service.is_auto_repeat_unlocked(user))
        self.assertIn("auto_repeat_route", reward_result["newly_unlocked_features"])
        self.assertIn("auto_repeat", reward_result["newly_unlocked_features"])

    def test_survival_guard_adds_base_guard_when_armor_is_equipped(self) -> None:
        service = UserService(
            {
                "users": {
                    "alice": {
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True},
                        "equipped": {
                            "weapon": _make_item("鉄の剣", "weapon", 5),
                            "armor": _make_item("革鎧", "armor", 4),
                            "ring": None,
                        },
                        "feature_unlocks": {"survival_guard": True},
                    }
                }
            }
        )

        user = service.get_user("alice")

        self.assertEqual(service.get_armor_lethal_guard_count(user), 1)

    def test_feature_effect_summaries_follow_data_driven_definitions(self) -> None:
        service = UserService({"users": {}})
        user = service.get_user("alice")
        user["auto_explore_fragments"] = 0
        user["feature_unlocks"] = {
            "rare_hunt": True,
            "weapon_forge": True,
            "auto_repeat": False,
            "armor_slot": False,
            "ring_slot": False,
        }

        self.assertEqual(
            service.get_feature_effect_summaries(user),
            ["高レア率アップ", "武器強化 成功率+8% / Cost軽減"],
        )

    def test_exploration_records_update_only_after_baseline_exists(self) -> None:
        service = UserService({"users": {"alice": {}}})
        user = service.get_user("alice")

        first_updates = service.update_exploration_records(
            user,
            {
                "exp": 20,
                "gold": 15,
                "battle_logs": [{"monster": "草カブトムシ", "turns": 2, "won": True}],
                "exploration_runs": 1,
            },
        )
        second_updates = service.update_exploration_records(
            user,
            {
                "exp": 35,
                "gold": 18,
                "battle_logs": [
                    {"monster": "草カブトムシ", "turns": 2, "won": True},
                    {"monster": "石カブトムシ", "turns": 3, "won": True},
                ],
                "exploration_runs": 2,
            },
        )

        self.assertEqual(first_updates, [])
        self.assertIn("最高EXP 35", second_updates)
        self.assertIn("最多戦闘 2", second_updates)
        self.assertIn("最多周回 2", second_updates)

    def test_auto_repeat_start_requires_progress_then_becomes_available(self) -> None:
        manager = RPGManager({"users": {}})

        ok, msg = manager.start_exploration("alice", "自動 朝の森")

        self.assertFalse(ok)
        self.assertIn("星影の祭壇ボス初回撃破", msg)
        self.assertIn("欠片 0/3", msg)

        user = manager.get_user("alice")
        for area_name in ("ヘッセ深部", "紅蓮の鉱山", "沈黙の城塞跡", "星影の祭壇"):
            manager.users.register_boss_clear(user, area_name)
            manager.users.claim_area_first_clear_rewards(user, area_name)

        ok, msg = manager.start_exploration("alice", "自動 朝の森")

        self.assertTrue(ok)
        self.assertIn("朝の森", msg)

    def test_progression_trace_keeps_early_fast_and_midgame_reachable(self) -> None:
        traces = [_run_progression_trace(seed) for seed in range(6)]

        morning_runs = [trace["朝の森"] for trace in traces]
        ruins_runs = [trace["三日月廃墟"] for trace in traces]
        auto_repeat_runs = [trace["auto_repeat"] for trace in traces]

        self.assertLessEqual(max(morning_runs), 5)
        self.assertLessEqual(max(ruins_runs), 10)
        self.assertLessEqual(sum(auto_repeat_runs) / len(auto_repeat_runs), 45)
        self.assertLessEqual(max(auto_repeat_runs), 50)


if __name__ == "__main__":
    unittest.main()
