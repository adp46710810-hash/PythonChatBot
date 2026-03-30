from __future__ import annotations

import queue
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot import StreamBot
from bot_components.rpg_commands import BasicCommands
from rpg_core.exploration_result import (
    RETURN_PHASE_DEFEAT,
    RETURN_PHASE_PREBATTLE,
    format_return_footer,
    get_battle_count,
    infer_return_info,
)
from rpg_core.item_service import ItemService
from rpg_core.manager import RPGManager
from rpg_core.rules import (
    AREAS,
    AUTO_REPEAT_COOLDOWN_SEC,
    CHAT_EXP_PER_MSG,
    EXP_GAIN_MULTIPLIER,
    MAX_POTIONS_PER_EXPLORATION,
    POTION_PRICE,
)
from rpg_core.user_service import UserService


class _DummyRPG:
    def resolve_exploration_mode(self, mode_key):
        return {"label": "通常", "key": mode_key or "normal"}

    def format_item_brief(self, item):
        return str(item.get("name", "?"))


class _DummyBot:
    owner_id = "owner"

    def __init__(self) -> None:
        self.rpg = _DummyRPG()

    def show_detail_overlay(self, title, lines) -> None:
        self._overlay = (title, lines)


class _PendingResultRPG:
    def __init__(
        self,
        result,
        finalize_message: str | None,
        display_name: str = "Alice",
        *,
        notified_ready: bool = False,
    ) -> None:
        self._result = result
        self._finalize_message = finalize_message
        self._display_name = display_name
        self._notified_ready = notified_ready

    def get_user(self, _username):
        return {"explore": {"result": self._result, "notified_ready": self._notified_ready}}

    def try_finalize_exploration(self, _username):
        return self._finalize_message

    def get_display_name(self, _username, fallback=None):
        return self._display_name or fallback


class _FinalizeBotDouble:
    def __init__(
        self,
        result,
        finalize_message: str | None,
        display_name: str = "Alice",
        *,
        notified_ready: bool = False,
    ) -> None:
        self.rpg = _PendingResultRPG(
            result,
            finalize_message,
            display_name=display_name,
            notified_ready=notified_ready,
        )
        self.saved = 0
        self.tts_results = []
        self.boss_tts_results = []
        self.feature_tts_results = []
        self.area_depth_tts_results = []
        self.record_tts_results = []
        self.defeat_tts_results = []

    def save_data(self) -> None:
        self.saved += 1

    def maybe_enqueue_legendary_drop_tts(self, display_name, result) -> None:
        self.tts_results.append((display_name, result))

    def maybe_enqueue_boss_clear_tts(self, display_name, result) -> None:
        self.boss_tts_results.append((display_name, result))

    def maybe_enqueue_feature_unlock_tts(self, display_name, result) -> None:
        self.feature_tts_results.append((display_name, result))

    def maybe_enqueue_record_update_tts(self, display_name, result) -> None:
        self.record_tts_results.append((display_name, result))

    def maybe_enqueue_area_depth_record_tts(self, display_name, result) -> None:
        self.area_depth_tts_results.append((display_name, result))

    def maybe_enqueue_exploration_defeat_tts(self, display_name, result) -> None:
        self.defeat_tts_results.append((display_name, result))

    def enqueue_exploration_result_tts(self, display_name, result) -> None:
        self.maybe_enqueue_exploration_defeat_tts(display_name, result)
        self.maybe_enqueue_boss_clear_tts(display_name, result)
        self.maybe_enqueue_feature_unlock_tts(display_name, result)
        self.maybe_enqueue_area_depth_record_tts(display_name, result)
        self.maybe_enqueue_record_update_tts(display_name, result)
        self.maybe_enqueue_legendary_drop_tts(display_name, result)


class _ManualClaimRPG:
    def __init__(self, pending_result, finalized_result, *, notified_ready: bool = False) -> None:
        self.pending_result = pending_result
        self.finalized_result = finalized_result
        self.user = {
            "explore": {
                "state": "exploring",
                "result": pending_result,
                "notified_ready": notified_ready,
            },
            "last_exploration_result": None,
            "gold": 0,
        }
        self.finalize_calls = 0

    def get_user(self, _username):
        return self.user

    def has_legendary_drop(self, result):
        drop_items = result.get("drop_items", []) if isinstance(result, dict) else []
        return any(item.get("rarity") == "legendary" for item in drop_items if isinstance(item, dict))

    def finalize_exploration(self, _username):
        self.finalize_calls += 1
        self.user["last_exploration_result"] = self.finalized_result
        return "ok"

    def get_adventure_level(self, _user):
        return 10


class _ManualClaimBot:
    owner_id = "owner"

    def __init__(self, pending_result, finalized_result, *, notified_ready: bool = False) -> None:
        self.rpg = _ManualClaimRPG(
            pending_result,
            finalized_result,
            notified_ready=notified_ready,
        )
        self.saved = 0
        self.legendary_tts = []
        self.boss_tts = []
        self.feature_tts = []
        self.area_depth_tts = []
        self.record_tts = []
        self.defeat_tts = []

    def save_data(self) -> None:
        self.saved += 1

    def maybe_enqueue_legendary_drop_tts(self, display_name, result) -> None:
        self.legendary_tts.append((display_name, result))

    def maybe_enqueue_boss_clear_tts(self, display_name, result) -> None:
        self.boss_tts.append((display_name, result))

    def maybe_enqueue_feature_unlock_tts(self, display_name, result) -> None:
        self.feature_tts.append((display_name, result))

    def maybe_enqueue_record_update_tts(self, display_name, result) -> None:
        self.record_tts.append((display_name, result))

    def maybe_enqueue_area_depth_record_tts(self, display_name, result) -> None:
        self.area_depth_tts.append((display_name, result))

    def maybe_enqueue_exploration_defeat_tts(self, display_name, result) -> None:
        self.defeat_tts.append((display_name, result))

    def enqueue_exploration_result_tts(self, display_name, result) -> None:
        self.maybe_enqueue_exploration_defeat_tts(display_name, result)
        self.maybe_enqueue_boss_clear_tts(display_name, result)
        self.maybe_enqueue_feature_unlock_tts(display_name, result)
        self.maybe_enqueue_area_depth_record_tts(display_name, result)
        self.maybe_enqueue_record_update_tts(display_name, result)
        self.maybe_enqueue_legendary_drop_tts(display_name, result)

    def show_detail_overlay(self, title, lines) -> None:
        self._overlay = (title, lines)


class _DummyCtx:
    def __init__(self) -> None:
        self.chatter = type(
            "Chatter",
            (),
            {"name": "alice", "login": "alice", "display_name": "Alice", "id": "viewer"},
        )()
        self.replies = []

    async def reply(self, message: str) -> None:
        self.replies.append(message)


class _AutoEnhanceRPG:
    def __init__(self, before_user, after_user, summary) -> None:
        self._user = before_user
        self._after_user = after_user
        self._summary = summary
        self.calls = []

    def get_user(self, _username):
        return self._user

    def get_total_power(self, user):
        return int(user.get("power_value", 0))

    def format_equipped_item(self, user, slot):
        return str(user.get("formatted_items", {}).get(slot, "なし"))

    def get_material_inventory(self, user):
        return dict(user.get("materials_snapshot", {}))

    def auto_enhance_equipped_items(self, username, slots=None):
        self.calls.append((username, list(slots or [])))
        self._user = self._after_user
        return dict(self._summary)


class _AutoEnhanceBot:
    owner_id = "owner"

    def __init__(self, before_user, after_user, summary) -> None:
        self.rpg = _AutoEnhanceRPG(before_user, after_user, summary)
        self.saved = 0
        self.published = []

    def save_data(self) -> None:
        self.saved += 1

    def publish_detail_response(self, title, lines) -> None:
        self.published.append((title, lines))

    def get_detail_destination_label(self) -> str:
        return "Discord"


class ExplorationResultTests(unittest.TestCase):
    def test_user_service_remembers_display_name(self) -> None:
        service = UserService({"users": {"alice": {}}})
        remembered = service.remember_display_name("alice", "AliceJP")
        self.assertEqual(remembered, "AliceJP")
        self.assertEqual(service.get_display_name("alice"), "AliceJP")

    def test_maybe_enqueue_boss_clear_tts_reads_display_name(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        queued_messages = []
        bot.enqueue_tts_message = queued_messages.append

        StreamBot.maybe_enqueue_boss_clear_tts(
            bot,
            "Alice",
            {"newly_cleared_boss_areas": ["朝の森"]},
        )

        self.assertEqual(queued_messages, ["Aliceさんが朝の森のボスを撃破しました"])

    def test_maybe_enqueue_boss_clear_tts_normalizes_area_name_for_rpg_voice(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        bot._tts_queue = queue.Queue()
        bot.log = SimpleNamespace(exception=lambda *_args, **_kwargs: None)
        bot.tts_sanitize = lambda author, text: text

        StreamBot.maybe_enqueue_boss_clear_tts(
            bot,
            "Alice",
            {"newly_cleared_boss_areas": ["朝の森"]},
        )

        self.assertEqual(
            bot._tts_queue.get_nowait(),
            ("rpg", "Aliceさんがアサのモリのボスを撃破しました"),
        )

    def test_maybe_enqueue_legendary_drop_tts_reads_display_name(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        queued_messages = []
        bot.enqueue_tts_message = queued_messages.append
        bot.rpg = type(
            "_LegendaryRpgDouble",
            (),
            {"has_legendary_drop": staticmethod(lambda _result: True)},
        )()

        StreamBot.maybe_enqueue_legendary_drop_tts(
            bot,
            "Alice",
            {"drop_items": [{"name": "深淵の剣", "rarity": "legendary"}]},
        )

        self.assertEqual(queued_messages, ["Aliceさんがレジェンダリー装備をドロップしました"])

    def test_maybe_enqueue_feature_unlock_tts_announces_permanent_reward_and_auto_repeat(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        queued_messages = []
        bot.enqueue_tts_message = queued_messages.append

        StreamBot.maybe_enqueue_feature_unlock_tts(
            bot,
            "Alice",
            {
                "first_clear_reward_summaries": ["高レア探索補正"],
                "newly_unlocked_features": ["rare_hunt", "auto_repeat"],
            },
        )

        self.assertEqual(
            queued_messages,
            [
                "Aliceさんが恒久報酬を解放しました",
                "Aliceさんが自動周回を解放しました",
            ],
        )

    def test_maybe_enqueue_record_update_tts_announces_when_new_records_exist(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        queued_messages = []
        bot.enqueue_tts_message = queued_messages.append

        StreamBot.maybe_enqueue_record_update_tts(
            bot,
            "Alice",
            {"new_records": ["最高EXP 120"]},
        )

        self.assertEqual(queued_messages, ["Aliceさんが探索記録を更新しました"])

    def test_maybe_enqueue_area_depth_record_tts_announces_first_record(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        queued_messages = []
        bot.enqueue_tts_message = queued_messages.append

        StreamBot.maybe_enqueue_area_depth_record_tts(
            bot,
            "Alice",
            {
                "area_depth_record_update": {
                    "area": "朝の森",
                    "display_name": "Alice",
                    "battle_count": 3,
                    "total_turns": 7,
                    "is_first_record": True,
                    "holder_changed": False,
                }
            },
        )

        self.assertEqual(
            queued_messages,
            ["Aliceさんが朝の森の最深記録になりました 3戦 7ターン"],
        )

    def test_maybe_enqueue_area_depth_record_tts_announces_holder_change(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        queued_messages = []
        bot.enqueue_tts_message = queued_messages.append

        StreamBot.maybe_enqueue_area_depth_record_tts(
            bot,
            "Alice",
            {
                "area_depth_record_update": {
                    "area": "朝の森",
                    "display_name": "Alice",
                    "battle_count": 5,
                    "total_turns": 12,
                    "is_first_record": False,
                    "holder_changed": True,
                    "previous_display_name": "Bob",
                }
            },
        )

        self.assertEqual(
            queued_messages,
            ["朝の森の最深記録がAliceさんに入れ替わりました 5戦 12ターン"],
        )

    def test_maybe_enqueue_exploration_defeat_tts_reads_monster_name(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        queued_messages = []
        bot.enqueue_tts_message = queued_messages.append

        StreamBot.maybe_enqueue_exploration_defeat_tts(
            bot,
            "Alice",
            {
                "downed": True,
                "return_reason": "第3戦の スライム に倒された",
            },
        )

        self.assertEqual(queued_messages, ["Aliceさんがスライムによって倒されました"])

    def test_maybe_enqueue_exploration_defeat_tts_normalizes_monster_name_for_rpg_voice(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        bot._tts_queue = queue.Queue()
        bot.log = SimpleNamespace(exception=lambda *_args, **_kwargs: None)
        bot.tts_sanitize = lambda author, text: text

        StreamBot.maybe_enqueue_exploration_defeat_tts(
            bot,
            "Alice",
            {
                "downed": True,
                "battle_logs": [
                    {"monster": "ポーション使用", "won": True},
                    {"monster": "精鋭草カブトムシ", "won": False},
                ],
            },
        )

        self.assertEqual(
            bot._tts_queue.get_nowait(),
            ("rpg", "Aliceさんがセイエイクサカブトムシによって倒されました"),
        )

    def test_maybe_enqueue_exploration_defeat_tts_falls_back_to_last_lost_battle(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        queued_messages = []
        bot.enqueue_tts_message = queued_messages.append

        StreamBot.maybe_enqueue_exploration_defeat_tts(
            bot,
            "Alice",
            {
                "downed": True,
                "return_reason": "戦闘不能で自動周回停止",
                "battle_logs": [
                    {"monster": "ポーション使用", "won": True},
                    {"monster": "精鋭草カブトムシ", "won": False},
                ],
            },
        )

        self.assertEqual(queued_messages, ["Aliceさんが精鋭草カブトムシによって倒されました"])

    def test_maybe_enqueue_world_boss_spawn_tts_uses_world_boss_name(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        queued_messages = []
        bot.enqueue_tts_message = queued_messages.append
        bot.rpg = type(
            "_WorldBossSpawnRpgDouble",
            (),
            {
                "get_world_boss_status": staticmethod(
                    lambda: {"boss": {"name": "試練の甲帝"}}
                )
            },
        )()

        with patch("bot.random.choice", side_effect=lambda seq: seq[0]):
            StreamBot.maybe_enqueue_world_boss_spawn_tts(
                bot,
                "WB募集開始 / 試練の甲帝 / 120秒 / `!wb参加`",
            )

        self.assertEqual(queued_messages, ["試練の甲帝 が湧いたぞ。寝てる雑魚は叩き起きろ"])

    def test_maybe_enqueue_world_boss_event_tts_skips_battle_start_line(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        queued_messages = []
        bot.enqueue_tts_message = queued_messages.append
        bot.rpg = type(
            "_WorldBossStartRpgDouble",
            (),
            {
                "get_world_boss_status": staticmethod(
                    lambda: {"boss": {"name": "Boss"}}
                )
            },
        )()

        with patch("bot.random.choice", side_effect=lambda seq: seq[0]):
            StreamBot.maybe_enqueue_world_boss_event_tts(
                bot,
                "WB開始 / Boss / HP 999 / 3 participants",
            )

        self.assertEqual(queued_messages, ["Boss 戦開始。ぼさっとした雑魚から床を舐めるぞ"])

    def test_maybe_enqueue_world_boss_event_tts_skips_aoe_line_after_attack_resolves(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        queued_messages = []
        bot.enqueue_tts_message = queued_messages.append
        bot.rpg = type(
            "_WorldBossAoeRpgDouble",
            (),
            {
                "get_world_boss_status": staticmethod(
                    lambda: {"boss": {"name": "Boss"}}
                )
            },
        )()

        with patch("bot.random.choice", side_effect=lambda seq: seq[0]):
            StreamBot.maybe_enqueue_world_boss_event_tts(
                bot,
                "WB全体攻撃: Boss",
            )

        self.assertEqual(queued_messages, [])

    def test_maybe_enqueue_world_boss_event_tts_reads_mvp_line(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        queued_messages = []
        bot.enqueue_tts_message = queued_messages.append
        bot.rpg = type(
            "_WorldBossMvpRpgDouble",
            (),
            {"get_world_boss_status": staticmethod(lambda: {"boss": {}})},
        )()

        with patch("bot.random.choice", side_effect=lambda seq: seq[0]):
            StreamBot.maybe_enqueue_world_boss_event_tts(
                bot,
                "MVP Alice / 999ダメ",
            )

        self.assertEqual(
            queued_messages,
            ["総合貢献王は Alice。他の雑魚は背中だけ見てろ"],
        )

    def test_build_world_boss_log_tts_message_reads_downed_log(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        bot.rpg = type(
            "_WorldBossDownedLogRpgDouble",
            (),
            {"get_world_boss_status": staticmethod(lambda: {"boss": {"name": "Boss"}})},
        )()

        message = StreamBot.build_world_boss_log_tts_message(
            bot,
            "WB撃破: Alice / 82ダメ / 復帰8秒",
        )

        self.assertEqual(message, "Alice が Boss に倒された")

    def test_maybe_enqueue_world_boss_log_tts_reads_aoe_downed_count(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        queued_messages = []
        bot.enqueue_tts_message = queued_messages.append
        bot.rpg = type(
            "_WorldBossLogAoeRpgDouble",
            (),
            {"get_world_boss_status": staticmethod(lambda: {"boss": {"name": "Boss"}})},
        )()

        StreamBot.maybe_enqueue_world_boss_log_tts(
            bot,
            [
                "WB攻撃: Alice に 12ダメ",
                "WB全体攻撃: 4人へ / 戦闘不能2人 / Alice / Bob",
            ],
        )

        self.assertEqual(queued_messages, ["Boss の全体攻撃で 2人が倒れた"])

    def test_new_user_starts_with_armor_and_ring_locked(self) -> None:
        manager = RPGManager({"users": {}})
        user = manager.get_user("alice")

        self.assertTrue(manager.is_slot_unlocked(user, "weapon"))
        self.assertFalse(manager.is_slot_unlocked(user, "armor"))
        self.assertFalse(manager.is_slot_unlocked(user, "ring"))
        self.assertEqual(manager.format_equipped_item(user, "armor"), "未開放")
        self.assertEqual(manager.format_equipped_item(user, "ring"), "未開放")

    def test_existing_user_keeps_legacy_slots_unlocked(self) -> None:
        manager = RPGManager({"users": {"alice": {}}})
        user = manager.get_user("alice")

        self.assertTrue(manager.is_slot_unlocked(user, "weapon"))
        self.assertTrue(manager.is_slot_unlocked(user, "armor"))
        self.assertTrue(manager.is_slot_unlocked(user, "ring"))

    def test_infer_return_info_for_prebattle_reason(self) -> None:
        info = infer_return_info("第35戦の 精鋭草カブトムシ を危険と判断して帰還")
        self.assertEqual(info["phase"], RETURN_PHASE_PREBATTLE)
        self.assertEqual(info["location"], "第35戦前 / 精鋭草カブトムシ")
        self.assertEqual(info["reason"], "危険判断で帰還")

    def test_get_battle_count_ignores_potion_logs(self) -> None:
        result = {
            "battle_logs": [
                {"monster": "ポーション使用", "turns": 0},
                {"monster": "スライム", "turns": 2},
            ],
            "battle_count": 0,
        }
        self.assertEqual(get_battle_count(result), 1)

    def test_battle_detail_lines_always_end_with_return_footer(self) -> None:
        commands = BasicCommands(_DummyBot())
        result = {
            "area": "朝の森",
            "mode": "normal",
            "battle_logs": [
                {
                    "monster": "スライム",
                    "turns": 2,
                    "damage_taken": 4,
                    "won": True,
                    "escaped": False,
                    "log": [],
                    "turn_details": [
                        {
                            "turn": 1,
                            "player_hp_start": 20,
                            "enemy_hp_start": 8,
                            "player_hp_end": 18,
                            "enemy_hp_end": 4,
                            "player_action": "自分→スライム 4ダメ",
                            "enemy_action": "スライム→自分 2ダメ",
                            "guarded": False,
                        }
                    ],
                    "drop_items": [],
                    "drop_materials": {"weapon": 0, "armor": 0, "ring": 0},
                    "drop_enchant_materials": {"weapon": 0, "armor": 0, "ring": 0},
                }
            ],
            "battle_count": 1,
            "return_reason": "第2戦の キングスライム を危険と判断して帰還",
        }

        lines, selected_battle_number, total_battles = commands._build_battle_detail_lines(
            "alice",
            result,
            detail_state_label="受取済み",
            battle_number=None,
        )

        self.assertIsNone(selected_battle_number)
        self.assertEqual(total_battles, 1)
        self.assertEqual(lines[-1], format_return_footer(result))

    def test_user_service_sanitizes_broken_result_and_infers_return_info(self) -> None:
        service = UserService(
            {
                "users": {
                    "alice": {
                        "bag": "invalid",
                        "materials": [],
                        "enchant_materials": [],
                        "equipped": "invalid",
                        "explore": {
                            "state": "idle",
                            "result": {
                                "battle_logs": "invalid",
                                "drop_items": "invalid",
                                "return_reason": "第3戦の スライム に倒された",
                            },
                        },
                    }
                }
            }
        )

        user = service.get_user("alice")
        result = user["explore"]["result"]

        self.assertEqual(user["bag"], [])
        self.assertEqual(result["battle_logs"], [])
        self.assertEqual(result["battle_count"], 0)
        self.assertEqual(result["return_info"]["phase"], RETURN_PHASE_DEFEAT)

    def test_user_service_revive_uses_stored_display_name(self) -> None:
        service = UserService(
            {
                "users": {
                    "alice": {
                        "display_name": "AliceJP",
                        "down": True,
                        "gold": 100,
                        "hp": 0,
                        "max_hp": 20,
                    }
                }
            }
        )

        ok, msg = service.revive_user("alice")

        self.assertTrue(ok)
        self.assertIn("AliceJP", msg)
        self.assertNotIn("alice は自力で復帰しました。", msg)

    def test_chat_exp_uses_exp_gain_multiplier(self) -> None:
        service = UserService({"users": {"alice": {}}})
        user = service.get_user("alice")

        gained = service.reward_chat_exp(user, 100.0)

        self.assertTrue(gained)
        self.assertEqual(user["chat_exp"], CHAT_EXP_PER_MSG)
        self.assertEqual(CHAT_EXP_PER_MSG, 10)

    def test_exploration_result_exp_uses_exp_gain_multiplier(self) -> None:
        manager = RPGManager({"users": {"alice": {}}})
        user = manager.get_user("alice")
        mode = manager.resolve_exploration_mode("normal")

        manager.users.get_player_combat_stats = lambda _u, _mode_key: (999, 999)
        manager.users.get_weapon_crit_stats = lambda _u: (0.0, 1.0)
        manager.users.get_armor_lethal_guard_count = lambda _u: 0
        manager.users.get_ring_exploration_rates = lambda _u: (1.0, 1.0, 0.0)
        manager.users.get_adventure_level = lambda _u: 1

        manager.exploration.get_area_exp_rate = lambda _area_name, _player_level: 1.0
        manager.exploration.pick_monster = lambda _area_name: {
            "name": "テストスライム",
            "hp": 1,
            "atk": 0,
            "def": 0,
            "exp": 3,
            "gold": 1,
            "drop_rate": 0.0,
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

        result = manager.simulate_exploration_result(user, "朝の森", mode)

        self.assertEqual(result["exp"], 3 * int(EXP_GAIN_MULTIPLIER))

    def test_late_battle_scaling_can_increase_rewards_progressively(self) -> None:
        manager = RPGManager({"users": {"alice": {}}})
        monster = {
            "name": "報酬検証スライム",
            "hp": 40,
            "atk": 8,
            "def": 2,
            "exp": 10,
            "gold": 8,
            "drop_rate": 0.10,
        }
        shared_scaling = {
            "late_game_start": 11,
            "late_progress_interval": 5,
            "late_hp_multiplier": 2.0,
            "late_hp_multiplier_per_step": 0.4,
            "late_hp_acceleration": 0.1,
            "late_atk_entry_bonus": 12,
            "late_atk_bonus_per_step": 4,
            "late_atk_acceleration": 1,
            "late_def_entry_bonus": 6,
            "late_def_bonus_per_step": 2,
            "late_def_acceleration": 1,
            "late_exp_multiplier": 1.0,
            "late_gold_multiplier": 1.0,
            "late_drop_rate_bonus": 0.0,
            "late_resource_bonus": 0.0,
        }
        reward_scaling = dict(shared_scaling)
        reward_scaling.update(
            {
                "late_exp_multiplier_per_step": 0.30,
                "late_exp_acceleration": 0.10,
                "late_gold_multiplier_per_step": 0.45,
                "late_gold_acceleration": 0.15,
                "late_drop_rate_bonus_per_step": 0.08,
                "late_drop_rate_bonus_acceleration": 0.02,
                "late_resource_bonus_per_step": 1.0,
            }
        )

        with patch.dict(
            "rpg_core.exploration_service.AREAS",
            {
                "終盤報酬比較A": {"tier": 1, "battle_scaling": dict(shared_scaling)},
                "終盤報酬比較B": {"tier": 1, "battle_scaling": reward_scaling},
            },
            clear=False,
        ):
            baseline = manager.exploration.scale_monster_for_battle(
                monster,
                16,
                "終盤報酬比較A",
            )
            boosted = manager.exploration.scale_monster_for_battle(
                monster,
                16,
                "終盤報酬比較B",
            )

        self.assertEqual(baseline["hp"], boosted["hp"])
        self.assertEqual(baseline["atk"], boosted["atk"])
        self.assertEqual(baseline["def"], boosted["def"])
        self.assertGreater(boosted["exp"], baseline["exp"])
        self.assertGreater(boosted["gold"], baseline["gold"])
        self.assertGreater(boosted["drop_rate"], baseline["drop_rate"])
        self.assertEqual(baseline["late_resource_bonus"], 0)
        self.assertEqual(boosted["late_resource_bonus"], 1)

    def test_finalize_exploration_unlocks_slots_on_first_morning_forest_boss_clear(self) -> None:
        manager = RPGManager({"users": {}})
        manager.remember_display_name("alice", "Alice")
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
                "kills": [{"name": "ボス鉄カブトムシ", "boss": True}],
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
                "return_info": {"phase": "complete", "reason": "探索終了", "raw_reason": "探索終了"},
                "potions_used": 2,
                "armor_guards_used": 0,
                "armor_guards_total": 0,
                "armor_enchant_consumed": False,
                "auto_repeat": False,
            },
        }

        manager.finalize_exploration("alice")

        self.assertTrue(manager.is_slot_unlocked(user, "armor"))
        self.assertTrue(manager.is_slot_unlocked(user, "ring"))
        self.assertIn("朝の森", user.get("boss_clear_areas", []))
        self.assertEqual(
            user["last_exploration_result"].get("newly_cleared_boss_areas"),
            ["朝の森"],
        )
        self.assertEqual(
            user["last_exploration_result"].get("newly_unlocked_slots"),
            ["armor", "ring", "shoes"],
        )
        self.assertEqual(len(user.get("exploration_history", [])), 1)
        self.assertEqual(user["exploration_history"][0]["area"], "朝の森")

    def test_finalize_exploration_records_first_area_depth_holder(self) -> None:
        manager = RPGManager({"users": {}})
        manager.remember_display_name("alice", "Alice")
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
                "kills": [{"name": "草スライム"}],
                "exp": 10,
                "gold": 5,
                "damage": 0,
                "drop_items": [],
                "auto_explore_stones": 0,
                "drop_materials": {"weapon": 0, "armor": 0, "ring": 0},
                "drop_enchant_materials": {"weapon": 0, "armor": 0, "ring": 0},
                "battle_logs": [],
                "battle_count": 3,
                "total_turns": 7,
                "hp_after": 70,
                "returned_safe": True,
                "downed": False,
                "return_reason": "探索終了",
                "return_info": {"phase": "complete", "reason": "探索終了", "raw_reason": "探索終了"},
                "potions_used": 0,
                "armor_guards_used": 0,
                "armor_guards_total": 0,
                "armor_enchant_consumed": False,
                "auto_repeat": False,
            },
        }

        manager.finalize_exploration("alice")

        self.assertEqual(
            manager.data["area_depth_records"]["朝の森"],
            {
                "area": "朝の森",
                "username": "alice",
                "display_name": "Alice",
                "battle_count": 3,
                "total_turns": 7,
                "updated_at": manager.data["area_depth_records"]["朝の森"]["updated_at"],
            },
        )
        self.assertEqual(
            user["last_exploration_result"]["area_depth_record_update"],
            {
                "area": "朝の森",
                "username": "alice",
                "display_name": "Alice",
                "battle_count": 3,
                "total_turns": 7,
                "updated_at": user["last_exploration_result"]["area_depth_record_update"]["updated_at"],
                "is_first_record": True,
                "holder_changed": False,
                "previous_username": "",
                "previous_display_name": "",
                "previous_battle_count": 0,
                "previous_total_turns": 0,
                "previous_updated_at": 0.0,
            },
        )

    def test_finalize_exploration_replaces_area_depth_holder_on_faster_tie(self) -> None:
        manager = RPGManager({"users": {}})
        manager.remember_display_name("alice", "Alice")
        manager.remember_display_name("bob", "Bob")
        manager.remember_display_name("carol", "Carol")

        alice = manager.get_user("alice")
        alice["explore"] = {
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
                "kills": [{"name": "草スライム"}],
                "exp": 10,
                "gold": 5,
                "damage": 0,
                "drop_items": [],
                "auto_explore_stones": 0,
                "drop_materials": {"weapon": 0, "armor": 0, "ring": 0},
                "drop_enchant_materials": {"weapon": 0, "armor": 0, "ring": 0},
                "battle_logs": [],
                "battle_count": 5,
                "total_turns": 12,
                "hp_after": 70,
                "returned_safe": True,
                "downed": False,
                "return_reason": "探索終了",
                "return_info": {"phase": "complete", "reason": "探索終了", "raw_reason": "探索終了"},
                "potions_used": 0,
                "armor_guards_used": 0,
                "armor_guards_total": 0,
                "armor_enchant_consumed": False,
                "auto_repeat": False,
            },
        }
        manager.finalize_exploration("alice")

        bob = manager.get_user("bob")
        bob["explore"] = {
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
                "kills": [{"name": "草スライム"}],
                "exp": 8,
                "gold": 4,
                "damage": 0,
                "drop_items": [],
                "auto_explore_stones": 0,
                "drop_materials": {"weapon": 0, "armor": 0, "ring": 0},
                "drop_enchant_materials": {"weapon": 0, "armor": 0, "ring": 0},
                "battle_logs": [],
                "battle_count": 5,
                "total_turns": 10,
                "hp_after": 64,
                "returned_safe": True,
                "downed": False,
                "return_reason": "探索終了",
                "return_info": {"phase": "complete", "reason": "探索終了", "raw_reason": "探索終了"},
                "potions_used": 0,
                "armor_guards_used": 0,
                "armor_guards_total": 0,
                "armor_enchant_consumed": False,
                "auto_repeat": False,
            },
        }
        manager.finalize_exploration("bob")

        carol = manager.get_user("carol")
        carol["explore"] = {
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
                "kills": [{"name": "草スライム"}],
                "exp": 6,
                "gold": 3,
                "damage": 0,
                "drop_items": [],
                "auto_explore_stones": 0,
                "drop_materials": {"weapon": 0, "armor": 0, "ring": 0},
                "drop_enchant_materials": {"weapon": 0, "armor": 0, "ring": 0},
                "battle_logs": [],
                "battle_count": 5,
                "total_turns": 11,
                "hp_after": 63,
                "returned_safe": True,
                "downed": False,
                "return_reason": "探索終了",
                "return_info": {"phase": "complete", "reason": "探索終了", "raw_reason": "探索終了"},
                "potions_used": 0,
                "armor_guards_used": 0,
                "armor_guards_total": 0,
                "armor_enchant_consumed": False,
                "auto_repeat": False,
            },
        }
        manager.finalize_exploration("carol")

        self.assertEqual(manager.data["area_depth_records"]["朝の森"]["username"], "bob")
        self.assertEqual(manager.data["area_depth_records"]["朝の森"]["display_name"], "Bob")
        self.assertEqual(manager.data["area_depth_records"]["朝の森"]["battle_count"], 5)
        self.assertEqual(manager.data["area_depth_records"]["朝の森"]["total_turns"], 10)
        self.assertEqual(
            bob["last_exploration_result"]["area_depth_record_update"]["previous_display_name"],
            "Alice",
        )
        self.assertTrue(
            bob["last_exploration_result"]["area_depth_record_update"]["holder_changed"]
        )
        self.assertNotIn("area_depth_record_update", carol["last_exploration_result"])

    def test_area_depth_record_non_owner_replaces_owner_even_with_lower_depth(self) -> None:
        manager = RPGManager({"users": {}}, owner_username="owner")

        first_update = manager.users.update_area_depth_record(
            "owner",
            "Owner",
            {"area": "朝の森", "battle_count": 6, "total_turns": 10},
        )
        second_update = manager.users.update_area_depth_record(
            "alice",
            "Alice",
            {"area": "朝の森", "battle_count": 3, "total_turns": 12},
        )

        self.assertIsNotNone(first_update)
        self.assertIsNotNone(second_update)
        self.assertEqual(manager.data["area_depth_records"]["朝の森"]["username"], "alice")
        self.assertTrue(second_update["holder_changed"])
        self.assertEqual(second_update["previous_username"], "owner")

    def test_area_depth_record_owner_does_not_replace_non_owner_holder(self) -> None:
        manager = RPGManager({"users": {}}, owner_username="owner")

        first_update = manager.users.update_area_depth_record(
            "alice",
            "Alice",
            {"area": "朝の森", "battle_count": 3, "total_turns": 12},
        )
        second_update = manager.users.update_area_depth_record(
            "owner",
            "Owner",
            {"area": "朝の森", "battle_count": 6, "total_turns": 10},
        )

        self.assertIsNotNone(first_update)
        self.assertIsNone(second_update)
        self.assertEqual(manager.data["area_depth_records"]["朝の森"]["username"], "alice")

    def test_finalize_exploration_applies_data_driven_feature_reward_on_first_boss_clear(self) -> None:
        manager = RPGManager({"users": {}})
        user = manager.get_user("alice")
        user["explore"] = {
            "state": "exploring",
            "area": "三日月廃墟",
            "mode": "normal",
            "started_at": 0.0,
            "ends_at": 0.0,
            "auto_repeat": False,
            "notified_ready": False,
            "result": {
                "area": "三日月廃墟",
                "mode": "normal",
                "kills": [{"name": "呪骸の司祭", "boss": True}],
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
                "return_info": {"phase": "complete", "reason": "探索終了", "raw_reason": "探索終了"},
                "potions_used": 2,
                "armor_guards_used": 0,
                "armor_guards_total": 0,
                "armor_enchant_consumed": False,
                "auto_repeat": False,
            },
        }

        manager.finalize_exploration("alice")

        self.assertTrue(user["feature_unlocks"].get("enchanting", False))
        self.assertEqual(
            user["last_exploration_result"].get("newly_cleared_boss_areas"),
            ["三日月廃墟"],
        )
        self.assertEqual(
            user["last_exploration_result"].get("newly_unlocked_features"),
            ["enchanting"],
        )
        self.assertEqual(
            user["last_exploration_result"].get("first_clear_reward_summaries"),
            ["エンチャント解放"],
        )

    def test_finalize_exploration_ignores_legacy_world_boss_flag_for_area_boss_clear(self) -> None:
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
                        "name": "ワールドボス鉄カブトムシ",
                        "boss": True,
                        "area_boss": False,
                        "world_boss": True,
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
                "hp_after": 52,
                "returned_safe": True,
                "downed": False,
                "return_reason": "探索完了時に出現した ワールドボス鉄カブトムシ を撃破して帰還",
                "return_info": {
                    "battle_number": 1,
                    "monster": "ワールドボス鉄カブトムシ",
                    "phase": "unknown",
                    "reason": "ワールドボス撃破",
                    "raw_reason": "探索完了時に出現した ワールドボス鉄カブトムシ を撃破して帰還",
                },
                "potions_used": 0,
                "armor_guards_used": 0,
                "armor_guards_total": 0,
                "armor_enchant_consumed": False,
                "auto_repeat": False,
            },
        }

        manager.finalize_exploration("alice")

        self.assertNotIn("朝の森", user.get("boss_clear_areas", []))
        self.assertEqual(
            user["last_exploration_result"].get("newly_cleared_boss_areas"),
            [],
        )

    def test_finalize_exploration_auto_refills_potions_when_affordable(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "starter_kit_granted": True,
                        "gold": 0,
                        "potions": MAX_POTIONS_PER_EXPLORATION,
                    }
                }
            }
        )
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
                "kills": [],
                "exp": 10,
                "gold": POTION_PRICE * 2,
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
                "return_info": {"phase": "complete", "reason": "探索終了", "raw_reason": "探索終了"},
                "potions_used": 2,
                "armor_guards_used": 0,
                "armor_guards_total": 0,
                "armor_enchant_consumed": False,
                "auto_repeat": False,
            },
        }

        message = manager.finalize_exploration("alice")

        self.assertIn("P補充+2", message)
        self.assertEqual(user["potions"], MAX_POTIONS_PER_EXPLORATION)
        self.assertEqual(user["gold"], 0)
        self.assertEqual(user["last_exploration_result"].get("auto_potions_bought"), 2)
        self.assertEqual(
            user["last_exploration_result"].get("auto_potion_refill_cost"),
            POTION_PRICE * 2,
        )
        self.assertEqual(
            user["last_exploration_result"].get("potions_after_claim"),
            MAX_POTIONS_PER_EXPLORATION,
        )

    def test_finalize_exploration_refills_potions_to_saved_target(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "starter_kit_granted": True,
                        "gold": POTION_PRICE * 2,
                        "potions": 3,
                        "auto_potion_refill_target": 3,
                    }
                }
            }
        )
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
                "kills": [],
                "exp": 10,
                "gold": 0,
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
                "return_info": {"phase": "complete", "reason": "探索終了", "raw_reason": "探索終了"},
                "potions_used": 2,
                "armor_guards_used": 0,
                "armor_guards_total": 0,
                "armor_enchant_consumed": False,
                "auto_repeat": False,
            },
        }

        message = manager.finalize_exploration("alice")

        self.assertIn("P補充+2", message)
        self.assertEqual(user["potions"], 3)
        self.assertEqual(user["gold"], 0)
        self.assertEqual(user["last_exploration_result"].get("auto_potions_bought"), 2)
        self.assertEqual(
            user["last_exploration_result"].get("auto_potion_refill_cost"),
            POTION_PRICE * 2,
        )
        self.assertEqual(
            user["last_exploration_result"].get("potions_after_claim"),
            3,
        )

    def test_finalize_exploration_skips_potion_refill_when_disabled(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "starter_kit_granted": True,
                        "gold": POTION_PRICE * 5,
                        "potions": 4,
                        "auto_potion_refill_target": 0,
                    }
                }
            }
        )
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
                "kills": [],
                "exp": 10,
                "gold": 0,
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
                "return_info": {"phase": "complete", "reason": "探索終了", "raw_reason": "探索終了"},
                "potions_used": 2,
                "armor_guards_used": 0,
                "armor_guards_total": 0,
                "armor_enchant_consumed": False,
                "auto_repeat": False,
            },
        }

        message = manager.finalize_exploration("alice")

        self.assertNotIn("P補充+", message)
        self.assertEqual(user["potions"], 2)
        self.assertEqual(user["gold"], POTION_PRICE * 5)
        self.assertEqual(user["last_exploration_result"].get("auto_potions_bought"), 0)
        self.assertEqual(user["last_exploration_result"].get("auto_potion_refill_cost"), 0)
        self.assertEqual(user["last_exploration_result"].get("potions_after_claim"), 2)

    def test_auto_repeat_continuation_adds_cooldown_on_top_of_short_debug_duration(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "starter_kit_granted": True,
                        "potions": MAX_POTIONS_PER_EXPLORATION,
                        "feature_unlocks": {
                            "auto_repeat": True,
                            "auto_repeat_route": True,
                        },
                    }
                }
            }
        )
        user = manager.get_user("alice")
        user["explore"] = {
            "state": "exploring",
            "area": "朝の森",
            "mode": "normal",
            "started_at": 0.0,
            "ends_at": 0.0,
            "auto_repeat": True,
            "notified_ready": False,
            "result": {
                "area": "朝の森",
                "mode": "normal",
                "kills": [],
                "exp": 0,
                "gold": 0,
                "damage": 0,
                "drop_items": [],
                "auto_explore_stones": 0,
                "drop_materials": {"weapon": 0, "armor": 0, "ring": 0},
                "drop_enchant_materials": {"weapon": 0, "armor": 0, "ring": 0},
                "battle_logs": [],
                "battle_count": 1,
                "total_turns": 1,
                "hp_after": 70,
                "returned_safe": True,
                "downed": False,
                "return_reason": "探索終了",
                "return_info": {"phase": "complete", "reason": "探索終了", "raw_reason": "探索終了"},
                "potions_used": 2,
                "armor_guards_used": 0,
                "armor_guards_total": 0,
                "armor_enchant_consumed": False,
                "auto_repeat": True,
            },
        }
        next_result = {
            "area": "朝の森",
            "mode": "normal",
            "kills": [],
            "exp": 0,
            "gold": 0,
            "damage": 0,
            "drop_items": [],
            "auto_explore_stones": 0,
            "drop_materials": {"weapon": 0, "armor": 0, "ring": 0},
            "drop_enchant_materials": {"weapon": 0, "armor": 0, "ring": 0},
            "battle_logs": [],
            "battle_count": 1,
            "total_turns": 1,
            "hp_after": 70,
            "returned_safe": True,
            "downed": False,
            "return_reason": "探索終了",
            "return_info": {"phase": "complete", "reason": "探索終了", "raw_reason": "探索終了"},
            "potions_used": 0,
            "armor_guards_used": 0,
            "armor_guards_total": 0,
            "armor_enchant_consumed": False,
            "auto_repeat": True,
        }

        manager.exploration.simulate_exploration_result = lambda *_args, **_kwargs: dict(next_result)

        with patch("rpg_core.exploration_service.EXPLORATION_DURATION_OVERRIDE_SEC", 1):
            with patch("rpg_core.exploration_service.now_ts", return_value=100.0):
                manager.finalize_exploration("alice")

        self.assertEqual(user["explore"]["state"], "exploring")
        self.assertTrue(user["explore"]["auto_repeat"])
        self.assertEqual(user["explore"]["started_at"], 100.0)
        self.assertEqual(user["explore"]["ends_at"], 106.0)
        self.assertEqual(
            user["explore"]["ends_at"] - user["explore"]["started_at"],
            1 + AUTO_REPEAT_COOLDOWN_SEC,
        )

    def test_finalize_exploration_keeps_return_hp_and_refills_potions(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "starter_kit_granted": True,
                        "gold": POTION_PRICE * 2 + 20,
                        "potions": MAX_POTIONS_PER_EXPLORATION,
                    }
                }
            }
        )
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
                "kills": [],
                "exp": 10,
                "gold": 0,
                "damage": 50,
                "drop_items": [],
                "auto_explore_stones": 0,
                "drop_materials": {"weapon": 0, "armor": 0, "ring": 0},
                "drop_enchant_materials": {"weapon": 0, "armor": 0, "ring": 0},
                "battle_logs": [],
                "battle_count": 1,
                "total_turns": 3,
                "hp_after": 20,
                "returned_safe": True,
                "downed": False,
                "return_reason": "探索終了",
                "return_info": {"phase": "complete", "reason": "探索終了", "raw_reason": "探索終了"},
                "potions_used": 2,
                "armor_guards_used": 0,
                "armor_guards_total": 0,
                "armor_enchant_consumed": False,
                "auto_repeat": False,
            },
        }

        manager.finalize_exploration("alice")

        self.assertEqual(user["hp"], 70)
        self.assertEqual(user["potions"], MAX_POTIONS_PER_EXPLORATION)
        self.assertEqual(user["gold"], 15)
        self.assertEqual(user["last_exploration_result"].get("auto_hp_heal_cost"), 5)
        self.assertEqual(user["last_exploration_result"].get("auto_hp_restored"), 50)
        self.assertEqual(user["last_exploration_result"].get("auto_potions_bought"), 2)
        self.assertEqual(
            user["last_exploration_result"].get("auto_potion_refill_cost"),
            POTION_PRICE * 2,
        )

    def test_finalize_exploration_auto_reenchants_armor_after_guard_break(self) -> None:
        manager = RPGManager(
            {
                "users": {
                    "alice": {
                        "starter_kit_granted": True,
                        "slot_unlocks": {"weapon": True, "armor": True, "ring": True},
                        "feature_unlocks": {"enchanting": True, "survival_guard": True},
                        "equipped": {
                            "weapon": {"name": "剣", "slot": "weapon", "rarity": "common", "power": 5, "value": 50, "enhance": 0, "enchant": None},
                            "armor": {"name": "鎧", "slot": "armor", "rarity": "common", "power": 5, "value": 50, "enhance": 0, "enchant": "armor"},
                            "ring": {"name": "指輪", "slot": "ring", "rarity": "common", "power": 5, "value": 50, "enhance": 0, "enchant": None},
                        },
                        "enchant_materials": {"weapon": 0, "armor": 1, "ring": 0},
                        "potions": MAX_POTIONS_PER_EXPLORATION,
                    }
                }
            }
        )
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
                "kills": [],
                "exp": 10,
                "gold": 0,
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
                "return_info": {"phase": "complete", "reason": "探索終了", "raw_reason": "探索終了"},
                "potions_used": 0,
                "armor_guards_used": 1,
                "armor_guards_total": 1,
                "armor_enchant_consumed": True,
                "auto_repeat": False,
            },
        }

        manager.finalize_exploration("alice")

        self.assertEqual(user["equipped"]["armor"]["enchant"], "armor")
        self.assertEqual(user["enchant_materials"]["armor"], 0)
        self.assertEqual(user["last_exploration_result"].get("auto_armor_reenchants"), 1)

    def test_exploration_result_lines_include_first_clear_reward_summary(self) -> None:
        commands = BasicCommands(_DummyBot())
        result = {
            "area": "朝の森",
            "mode": "normal",
            "battle_logs": [],
            "battle_count": 1,
            "exp": 10,
            "gold": 5,
            "total_turns": 3,
            "hp_after": 70,
            "returned_safe": True,
            "downed": False,
            "return_reason": "探索終了",
            "potions_used": 0,
            "armor_guards_used": 0,
            "armor_guards_total": 0,
            "armor_enchant_consumed": False,
            "newly_cleared_boss_areas": ["朝の森"],
            "first_clear_reward_summaries": ["防具・装飾スロット解放"],
        }

        lines = commands._build_exploration_result_lines(
            "Alice",
            result,
            command_name="!探索結果",
            detail_state_label="受取済み",
        )

        text = "\n".join(lines)
        self.assertIn("初回ボス撃破: 朝の森", text)
        self.assertIn("恒久報酬: 防具・装飾スロット解放", text)

    def test_exploration_result_lines_ignore_legacy_world_boss_summary(self) -> None:
        commands = BasicCommands(_DummyBot())
        result = {
            "area": "朝の森",
            "mode": "normal",
            "battle_logs": [],
            "battle_count": 2,
            "exp": 10,
            "gold": 5,
            "total_turns": 5,
            "hp_after": 52,
            "returned_safe": True,
            "downed": False,
            "return_reason": "探索完了時に出現した ワールドボス鉄カブトムシ を撃破して帰還",
            "potions_used": 0,
            "armor_guards_used": 0,
            "armor_guards_total": 0,
            "armor_enchant_consumed": False,
            "world_boss_encountered": True,
            "world_boss_defeated": True,
            "world_boss_name": "ワールドボス鉄カブトムシ",
        }

        lines = commands._build_exploration_result_lines(
            "Alice",
            result,
            command_name="!探索結果",
            detail_state_label="受取済み",
        )

        text = "\n".join(lines)
        self.assertNotIn("ワールドボス:", text)

    def test_exploration_result_lines_include_auto_potion_refill_summary(self) -> None:
        commands = BasicCommands(_DummyBot())
        result = {
            "area": "朝の森",
            "mode": "normal",
            "battle_logs": [],
            "battle_count": 1,
            "exp": 10,
            "gold": 5,
            "total_turns": 3,
            "hp_after": 70,
            "returned_safe": True,
            "downed": False,
            "return_reason": "探索終了",
            "potions_used": 2,
            "auto_potions_bought": 2,
            "auto_potion_refill_cost": POTION_PRICE * 2,
            "potions_after_claim": MAX_POTIONS_PER_EXPLORATION,
            "armor_guards_used": 0,
            "armor_guards_total": 0,
            "armor_enchant_consumed": False,
        }

        lines = commands._build_exploration_result_lines(
            "Alice",
            result,
            command_name="!探索結果",
            detail_state_label="受取済み",
        )

        text = "\n".join(lines)
        self.assertIn(
            f"帰還整備: ポーション購入 +2 / -{POTION_PRICE * 2}G / 現在 {MAX_POTIONS_PER_EXPLORATION}個",
            text,
        )

    def test_exploration_result_lines_include_auto_hp_recovery_summary(self) -> None:
        commands = BasicCommands(_DummyBot())
        result = {
            "area": "朝の森",
            "mode": "normal",
            "battle_logs": [],
            "battle_count": 1,
            "exp": 10,
            "gold": 5,
            "total_turns": 3,
            "hp_after": 20,
            "returned_safe": True,
            "downed": False,
            "return_reason": "探索終了",
            "potions_used": 2,
            "auto_hp_heal_cost": 5,
            "auto_hp_restored": 50,
            "potions_after_claim": 3,
            "claimed_status": {"hp": 70, "max_hp": 70, "down": False},
            "armor_guards_used": 0,
            "armor_guards_total": 0,
            "armor_enchant_consumed": False,
        }

        lines = commands._build_exploration_result_lines(
            "Alice",
            result,
            command_name="!探索結果",
            detail_state_label="受取済み",
        )

        text = "\n".join(lines)
        self.assertIn("帰還整備: HP全快 -5G / 現在 3個", text)

    def test_exploration_result_lines_include_auto_reenchant_summary(self) -> None:
        commands = BasicCommands(_DummyBot())
        result = {
            "area": "朝の森",
            "mode": "normal",
            "battle_logs": [],
            "battle_count": 1,
            "exp": 10,
            "gold": 5,
            "total_turns": 3,
            "hp_after": 70,
            "returned_safe": True,
            "downed": False,
            "return_reason": "探索終了",
            "potions_used": 0,
            "armor_guards_used": 1,
            "armor_guards_total": 1,
            "armor_enchant_consumed": True,
            "auto_armor_reenchants": 1,
        }

        lines = commands._build_exploration_result_lines(
            "Alice",
            result,
            command_name="!探索結果",
            detail_state_label="受取済み",
        )

        text = "\n".join(lines)
        self.assertIn("自動整備: 防具に致死回避エンチャを再付与", text)
        self.assertNotIn("alert: 致死回避エンチャが今回の探索で消滅", text)

    def test_moon_enchant_material_drops_guaranteed_from_boss_only(self) -> None:
        service = ItemService()

        non_boss_drop = service.get_enchantment_drop_for_monster(
            "三日月廃墟",
            {"boss": False, "elite": False},
        )
        self.assertEqual(non_boss_drop, {})

        with patch("rpg_core.item_service.random.random", return_value=0.49):
            boss_drop = service.get_enchantment_drop_for_monster(
                "三日月廃墟",
                {"boss": True, "elite": False},
            )
        self.assertEqual(boss_drop, {"weapon": 1})

        with patch("rpg_core.item_service.random.random", return_value=0.50):
            boss_drop_again = service.get_enchantment_drop_for_monster(
                "三日月廃墟",
                {"boss": True, "elite": False},
            )
        self.assertEqual(boss_drop_again, {"weapon": 1})

    def test_moon_ruins_late_battle_grants_extra_enchant_materials(self) -> None:
        manager = RPGManager({"users": {}})
        scaled_monster = manager.exploration.scale_monster_for_battle(
            {
                "name": "廃墟の亡者兵",
                "hp": 20,
                "atk": 4,
                "def": 1,
                "exp": 5,
                "gold": 3,
                "drop_rate": 0.1,
            },
            7,
            "三日月廃墟",
        )

        self.assertGreaterEqual(int(scaled_monster.get("late_resource_bonus", 0)), 1)
        with patch("rpg_core.item_service.random.random", return_value=0.0):
            late_drop = manager.items.get_enchantment_drop_for_monster("三日月廃墟", scaled_monster)
        self.assertGreaterEqual(int(late_drop.get("weapon", 0)), 1)

    def test_shoes_material_drops_only_in_tempest_cliff(self) -> None:
        service = ItemService()

        with (
            patch("rpg_core.item_service.random.random", return_value=0.0),
            patch("rpg_core.item_service.random.randint", return_value=1),
        ):
            areas_with_shoes = [
                area_name
                for area_name in AREAS
                if service.get_material_drop_for_monster(
                    area_name,
                    {"boss": False, "elite": False},
                ).get("shoes", 0)
                > 0
            ]
            altar_drop = service.get_material_drop_for_monster(
                "星影の祭壇",
                {"boss": False, "elite": False},
            )
            cliff_drop = service.get_material_drop_for_monster(
                "迅雷の断崖",
                {"boss": False, "elite": False},
            )

        self.assertEqual(areas_with_shoes, ["迅雷の断崖"])
        self.assertEqual(altar_drop, {"ring": 1})
        self.assertEqual(cliff_drop, {"shoes": 1})

    def test_late_resource_bonus_adds_to_material_and_enchantment_drops(self) -> None:
        service = ItemService()
        area_data = {
            "tier": 1,
            "material_drop": {
                "slot": "weapon",
                "chance": 1.0,
                "min": 1,
                "max": 1,
            },
            "enchantment_drops": [
                {
                    "slot": "weapon",
                    "chance": 1.0,
                    "min": 1,
                    "max": 1,
                }
            ],
        }

        with (
            patch.dict(
                "rpg_core.item_service.AREAS",
                {"終盤素材比較": area_data},
                clear=False,
            ),
            patch("rpg_core.item_service.random.random", return_value=0.0),
            patch("rpg_core.item_service.random.randint", return_value=1),
        ):
            material_drop = service.get_material_drop_for_monster(
                "終盤素材比較",
                {"late_resource_bonus": 2},
            )
            enchant_drop = service.get_enchantment_drop_for_monster(
                "終盤素材比較",
                {"late_resource_bonus": 2},
            )

        self.assertEqual(material_drop, {"weapon": 3})
        self.assertEqual(enchant_drop, {"weapon": 3})

    def test_enchant_requires_feature_unlock(self) -> None:
        service = ItemService()
        user = {
            "slot_unlocks": {"weapon": True, "armor": True, "ring": True},
            "feature_unlocks": {},
            "equipped": {
                "weapon": {
                    "name": "鉄の剣",
                    "slot": "weapon",
                    "rarity": "common",
                    "power": 5,
                    "value": 50,
                    "enhance": 0,
                    "enchant": None,
                }
            },
            "enchant_materials": {"weapon": 1, "armor": 0, "ring": 0},
        }

        attempted, msg = service.enchant_equipped_item(user, "weapon")

        self.assertFalse(attempted)
        self.assertIn("三日月廃墟", msg)

    def test_auto_enhance_equipped_items_spends_resources_until_blocked(self) -> None:
        service = ItemService()
        user = {
            "gold": 72,
            "materials": {"weapon": 2, "armor": 1, "ring": 1},
            "slot_unlocks": {"weapon": True, "armor": True, "ring": True},
            "equipped": {
                "weapon": {
                    "name": "鉄の剣",
                    "slot": "weapon",
                    "rarity": "common",
                    "power": 5,
                    "value": 50,
                    "enhance": 0,
                    "enchant": None,
                },
                "armor": {
                    "name": "革の服",
                    "slot": "armor",
                    "rarity": "common",
                    "power": 4,
                    "value": 40,
                    "enhance": 0,
                    "enchant": None,
                },
                "ring": {
                    "name": "石の指輪",
                    "slot": "ring",
                    "rarity": "common",
                    "power": 3,
                    "value": 30,
                    "enhance": 0,
                    "enchant": None,
                },
            },
        }

        with patch("rpg_core.item_service.random.random", return_value=0.0):
            summary = service.auto_enhance_equipped_items(user)

        self.assertTrue(summary["attempted"])
        self.assertEqual(summary["attempt_count"], 4)
        self.assertEqual(summary["success_count"], 4)
        self.assertEqual(summary["failure_count"], 0)
        self.assertEqual(
            [attempt["slot"] for attempt in summary["attempt_logs"]],
            ["weapon", "armor", "ring", "weapon"],
        )
        self.assertEqual(summary["gold_spent"], 72)
        self.assertEqual(user["gold"], 0)
        self.assertEqual(summary["spent_materials"]["weapon"], 2)
        self.assertEqual(summary["spent_materials"]["armor"], 1)
        self.assertEqual(summary["spent_materials"]["ring"], 1)
        self.assertEqual(user["equipped"]["weapon"]["enhance"], 2)
        self.assertEqual(user["equipped"]["armor"]["enhance"], 1)
        self.assertEqual(user["equipped"]["ring"]["enhance"], 1)
        self.assertIn("武器黒石 が不足", summary["stop_reasons"]["weapon"])

    def test_rare_hunt_boosts_epic_weight(self) -> None:
        service = ItemService()

        base_weights = dict(service.get_area_rarity_weights("ヘッセ深部"))
        boosted_weights = dict(
            service.get_area_rarity_weights(
                "ヘッセ深部",
                {"feature_unlocks": {"rare_hunt": True}},
            )
        )

        self.assertLess(boosted_weights["common"], base_weights["common"])
        self.assertGreater(boosted_weights["epic"], base_weights["epic"])

    def test_hesse_boss_legendary_drop_bonus_grows_with_battle_progress(self) -> None:
        manager = RPGManager({"users": {"alice": {}}})
        monster = {
            "name": "報酬検証亡霊",
            "hp": 96,
            "atk": 46,
            "def": 18,
            "exp": 12,
            "gold": 4,
            "drop_rate": 0.18,
        }

        early_boss = manager.exploration.scale_monster_for_battle(monster, 10, "ヘッセ深部")
        late_boss = manager.exploration.scale_monster_for_battle(monster, 30, "ヘッセ深部")

        self.assertGreater(
            float(early_boss.get("legendary_drop_rate_multiplier_bonus", 0.0)),
            0.0,
        )
        self.assertGreater(
            float(late_boss.get("legendary_drop_rate_multiplier_bonus", 0.0)),
            float(early_boss.get("legendary_drop_rate_multiplier_bonus", 0.0)),
        )

    def test_hesse_legendary_equipment_is_boss_only_and_scales_with_progress(self) -> None:
        service = ItemService()

        with (
            patch("rpg_core.item_service.random.random", return_value=0.12),
            patch("rpg_core.item_service.pick_weighted", side_effect=["weapon", "epic"]),
            patch("rpg_core.item_service.random.choice", return_value="武器"),
            patch("rpg_core.item_service.random.randint", return_value=1),
        ):
            base_boss_item = service.roll_equipment_for_monster(
                "ヘッセ深部",
                {"drop_rate": 1.0, "boss": True},
            )

        self.assertIsNotNone(base_boss_item)
        self.assertNotEqual(base_boss_item["rarity"], "legendary")

        with (
            patch("rpg_core.item_service.random.random", return_value=0.12),
            patch("rpg_core.item_service.pick_weighted", return_value="weapon"),
            patch("rpg_core.item_service.random.choice", return_value="武器"),
            patch("rpg_core.item_service.random.randint", return_value=1),
        ):
            boosted_boss_item = service.roll_equipment_for_monster(
                "ヘッセ深部",
                {
                    "drop_rate": 0.18,
                    "boss": True,
                    "legendary_drop_rate_multiplier_bonus": 0.5,
                },
            )

        self.assertIsNotNone(boosted_boss_item)
        self.assertEqual(boosted_boss_item["rarity"], "legendary")

        with (
            patch("rpg_core.item_service.random.random", return_value=0.0),
            patch("rpg_core.item_service.pick_weighted", side_effect=["weapon", "epic"]),
            patch("rpg_core.item_service.random.choice", return_value="武器"),
            patch("rpg_core.item_service.random.randint", return_value=1),
        ):
            normal_item = service.roll_equipment_for_monster(
                "ヘッセ深部",
                {
                    "drop_rate": 1.0,
                    "boss": False,
                    "legendary_drop_rate_multiplier_bonus": 9.0,
                },
            )

        self.assertIsNotNone(normal_item)
        self.assertNotEqual(normal_item["rarity"], "legendary")

    def test_legendary_equipment_uses_reincarnator_series_names(self) -> None:
        service = ItemService()

        expected_names = {
            "weapon": "転生者の武器",
            "armor": "転生者の防具",
            "ring": "転生者の装飾",
            "shoes": "転生者の靴",
        }
        for slot_name, expected_name in expected_names.items():
            item = service.create_guaranteed_equipment(
                "ヘッセ深部",
                slot_name,
                rarity="legendary",
            )

            self.assertIsNotNone(item)
            self.assertEqual(item["name"], expected_name)
            self.assertEqual(item["series"], expected_name)

    def test_manager_has_legendary_drop_only_for_safe_results(self) -> None:
        manager = RPGManager({"users": {}})

        self.assertTrue(
            manager.has_legendary_drop(
                {
                    "returned_safe": True,
                    "downed": False,
                    "drop_items": [{"name": "深淵の剣", "rarity": "legendary"}],
                }
            )
        )
        self.assertFalse(
            manager.has_legendary_drop(
                {
                    "returned_safe": False,
                    "downed": True,
                    "drop_items": [{"name": "深淵の剣", "rarity": "legendary"}],
                }
            )
        )
        self.assertFalse(
            manager.has_legendary_drop(
                {
                    "returned_safe": True,
                    "downed": False,
                    "drop_items": [{"name": "鉄の剣", "rarity": "rare"}],
                }
            )
        )

    def test_stream_bot_try_finalize_exploration_enqueues_display_name_and_pending_result_for_tts(self) -> None:
        pending_result = {
            "returned_safe": True,
            "downed": False,
            "drop_items": [{"name": "深淵の剣", "rarity": "legendary"}],
            "first_clear_reward_summaries": ["高レア探索補正"],
            "new_records": ["最高EXP 120"],
        }
        bot_double = _FinalizeBotDouble(pending_result, "claimed")

        message = StreamBot.try_finalize_exploration(bot_double, "alice")

        self.assertEqual(message, "claimed")
        self.assertEqual(bot_double.saved, 1)
        self.assertEqual(bot_double.defeat_tts_results, [("Alice", pending_result)])
        self.assertEqual(bot_double.boss_tts_results, [("Alice", pending_result)])
        self.assertEqual(bot_double.feature_tts_results, [("Alice", pending_result)])
        self.assertEqual(bot_double.area_depth_tts_results, [("Alice", pending_result)])
        self.assertEqual(bot_double.record_tts_results, [("Alice", pending_result)])
        self.assertEqual(bot_double.tts_results, [("Alice", pending_result)])

    def test_stream_bot_try_finalize_exploration_enqueues_defeat_tts_when_ready_notice_already_sent(self) -> None:
        pending_result = {
            "returned_safe": False,
            "downed": True,
            "return_reason": "第2戦の スライム に倒された",
        }
        bot_double = _FinalizeBotDouble(
            pending_result,
            "claimed",
            notified_ready=True,
        )

        message = StreamBot.try_finalize_exploration(bot_double, "alice")

        self.assertEqual(message, "claimed")
        self.assertEqual(bot_double.saved, 1)
        self.assertEqual(bot_double.defeat_tts_results, [("Alice", pending_result)])


class ManualClaimTtsTests(unittest.IsolatedAsyncioTestCase):
    async def test_exploration_result_command_enqueues_legendary_tts_when_claiming(self) -> None:
        pending_result = {
            "area": "朝の森",
            "mode": "normal",
            "returned_safe": True,
            "downed": False,
            "drop_items": [{"name": "深淵の剣", "rarity": "legendary"}],
            "first_clear_reward_summaries": ["高レア探索補正"],
            "new_records": ["最高EXP 120"],
        }
        finalized_result = {
            "area": "朝の森",
            "mode": "normal",
            "returned_safe": True,
            "downed": False,
            "drop_items": [{"name": "深淵の剣", "rarity": "legendary"}],
            "exploration_runs": 1,
            "first_clear_reward_summaries": ["高レア探索補正"],
            "new_records": ["最高EXP 120"],
        }
        bot = _ManualClaimBot(pending_result, finalized_result)
        commands = BasicCommands(bot)
        ctx = _DummyCtx()

        commands._get_identity = lambda _ctx: ("alice", "Alice")
        commands._get_available_exploration_detail = lambda _user: (
            pending_result,
            "pending_claim",
            "受取待ち",
        )
        commands._show_detail_overlay = lambda _title, _lines: None
        commands._build_exploration_result_lines = lambda *_args, **_kwargs: []
        commands._build_exploration_result_reply_message = lambda *_args, **_kwargs: "ok"

        await commands._handle_exploration_result_command(ctx)

        self.assertEqual(bot.rpg.finalize_calls, 1)
        self.assertEqual(bot.saved, 1)
        self.assertEqual(bot.defeat_tts, [("Alice", pending_result)])
        self.assertEqual(bot.boss_tts, [("Alice", pending_result)])
        self.assertEqual(bot.feature_tts, [("Alice", pending_result)])
        self.assertEqual(bot.area_depth_tts, [("Alice", pending_result)])
        self.assertEqual(bot.record_tts, [("Alice", pending_result)])
        self.assertEqual(bot.legendary_tts, [("Alice", pending_result)])
        self.assertEqual(ctx.replies, ["ok"])

    async def test_exploration_result_command_enqueues_defeat_tts_even_after_ready_notice(self) -> None:
        pending_result = {
            "area": "朝の森",
            "mode": "normal",
            "returned_safe": False,
            "downed": True,
            "return_reason": "第2戦の スライム に倒された",
            "drop_items": [],
        }
        finalized_result = {
            "area": "朝の森",
            "mode": "normal",
            "returned_safe": False,
            "downed": True,
            "return_reason": "第2戦の スライム に倒された",
            "drop_items": [],
            "exploration_runs": 1,
        }
        bot = _ManualClaimBot(pending_result, finalized_result, notified_ready=True)
        commands = BasicCommands(bot)
        ctx = _DummyCtx()

        commands._get_identity = lambda _ctx: ("alice", "Alice")
        commands._get_available_exploration_detail = lambda _user: (
            pending_result,
            "pending_claim",
            "受取待ち",
        )
        commands._show_detail_overlay = lambda _title, _lines: None
        commands._build_exploration_result_lines = lambda *_args, **_kwargs: []
        commands._build_exploration_result_reply_message = lambda *_args, **_kwargs: "ok"

        await commands._handle_exploration_result_command(ctx)

        self.assertEqual(bot.rpg.finalize_calls, 1)
        self.assertEqual(bot.saved, 1)
        self.assertEqual(bot.defeat_tts, [("Alice", pending_result)])
        self.assertEqual(ctx.replies, ["ok"])

    async def test_announce_due_explorations_does_not_enqueue_result_tts_before_claim(self) -> None:
        class _AnnounceDueRPG:
            def __init__(self) -> None:
                self.user = {
                    "explore": {
                        "state": "exploring",
                        "ends_at": 0,
                        "auto_repeat": False,
                        "notified_ready": False,
                        "result": {
                            "downed": True,
                            "return_reason": "第2戦の スライム に倒された",
                        },
                    }
                }

            def get_user(self, _username):
                return self.user

            def get_display_name(self, _username, fallback=None):
                return "Alice" if fallback is None else "Alice"

        class _AnnounceDueBot:
            def __init__(self) -> None:
                self.data = {"users": {"alice": {}}}
                self.rpg = _AnnounceDueRPG()
                self.sent_messages = []
                self.saved = 0
                self.defeat_tts_results = []

            async def _send_channel_message(self, message: str, *, username=None) -> None:
                self.sent_messages.append((message, username))

            def save_data(self) -> None:
                self.saved += 1

            def maybe_enqueue_exploration_defeat_tts(self, display_name, result) -> None:
                self.defeat_tts_results.append((display_name, result))

        bot = _AnnounceDueBot()

        await StreamBot._announce_due_explorations(bot)

        self.assertEqual(bot.defeat_tts_results, [])
        self.assertEqual(
            bot.sent_messages,
            [("Alice の探索完了 / `!探索 結果` / `!探索 戦闘`", "alice")],
        )
        self.assertEqual(bot.saved, 1)

    async def test_auto_enhance_command_publishes_detail_and_short_reply(self) -> None:
        before_user = {
            "gold": 180,
            "power_value": 12,
            "formatted_items": {
                "weapon": "鉄の剣(A5)",
                "armor": "革の服(D4)",
                "ring": "石の指輪(A3/D3)",
                "shoes": "なし",
            },
            "materials_snapshot": {"weapon": 2, "armor": 1, "ring": 0, "shoes": 0},
        }
        after_user = {
            "gold": 10,
            "power_value": 17,
            "formatted_items": {
                "weapon": "鉄の剣+2(A7)",
                "armor": "革の服+1(D5)",
                "ring": "石の指輪(A3/D3)",
                "shoes": "なし",
            },
            "materials_snapshot": {"weapon": 0, "armor": 0, "ring": 0, "shoes": 0},
        }
        summary = {
            "attempted": True,
            "target_slots": ["weapon", "armor", "ring", "shoes"],
            "attempt_count": 3,
            "success_count": 2,
            "failure_count": 1,
            "attempt_logs": [
                {"slot": "weapon", "message": "鉄の剣 強化成功! +0 -> +1 / A6 / 武器黒石-1 / -10G"},
                {"slot": "armor", "message": "革の服 強化失敗... 防具黒石-1 / -10G / +0 維持"},
                {"slot": "weapon", "message": "鉄の剣 強化成功! +1 -> +2 / A7 / 武器黒石-1 / -20G"},
            ],
            "stop_reasons": {
                "weapon": "所持金不足です。必要:30G / 所持:10G",
                "armor": "防具黒石 が不足しています。 必要:1 / 所持:0",
                "ring": "装飾黒石 が不足しています。 必要:1 / 所持:0",
                "shoes": "靴黒石 が不足しています。 必要:1 / 所持:0",
            },
        }
        bot = _AutoEnhanceBot(before_user, after_user, summary)
        commands = BasicCommands(bot)
        ctx = _DummyCtx()

        commands._get_identity = lambda _ctx: ("alice", "Alice")

        await commands._run_auto_enhance_command(
            ctx,
            command_label="!自動強化",
            slot=None,
        )

        self.assertEqual(bot.rpg.calls, [("alice", ["weapon", "armor", "ring", "shoes"])])
        self.assertEqual(bot.saved, 1)
        self.assertEqual(len(bot.published), 1)
        title, lines = bot.published[0]
        self.assertEqual(title, "Alice / !自動強化")
        detail_text = "\n".join(lines)
        self.assertIn("成功 2 / 失敗 1", detail_text)
        self.assertIn("武器黒石 2 -> 0", detail_text)
        self.assertIn("鉄の剣 強化成功!", detail_text)
        self.assertIn("停止理由", detail_text)
        self.assertEqual(len(ctx.replies), 1)
        self.assertIn("自動強化 3回", ctx.replies[0])
        self.assertIn("詳細はDiscord", ctx.replies[0])


if __name__ == "__main__":
    unittest.main()
