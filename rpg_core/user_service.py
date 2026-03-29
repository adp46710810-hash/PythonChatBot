from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .achievements import ACHIEVEMENT_DEFINITIONS
from .exploration_result import get_battle_count, sanitize_return_info
from .rules import (
    AREAS,
    AUTO_REPEAT_UNLOCK_FRAGMENT_REQUIREMENT,
    BASE_PLAYER_ATK,
    BASE_PLAYER_DEF,
    BASE_PLAYER_SPEED,
    BEGINNER_GUARANTEE_AREA,
    BEGINNER_CAUTIOUS_RECOMMENDATION_COUNT,
    CHAT_EXP_ENABLED,
    CHAT_EXP_MIN_INTERVAL_SEC,
    CHAT_EXP_PER_MSG,
    CHAT_EXP_RPG_WEIGHT,
    DEFAULT_EXPLORATION_MODE,
    DEFAULT_AREA,
    DEFAULT_MAX_HP,
    ENCHANTMENT_ARMOR_GUARD_COUNT,
    ENCHANTMENT_EFFECT_LABELS,
    ENCHANTMENT_MATERIAL_LABELS,
    ENCHANTMENT_WEAPON_CRIT_DAMAGE_MULTIPLIER,
    ENCHANTMENT_WEAPON_CRIT_RATE,
    ENCHANTMENT_WEAPON_CRIT_RATE_PER_ENHANCE,
    ENCHANTMENT_RING_DROP_RATE_BONUS,
    ENCHANTMENT_RING_DROP_RATE_BONUS_PER_ENHANCE,
    ENCHANTMENT_RING_EXP_RATE,
    ENCHANTMENT_RING_EXP_RATE_PER_ENHANCE,
    ENCHANTMENT_RING_GOLD_RATE,
    ENCHANTMENT_RING_GOLD_RATE_PER_ENHANCE,
    EXPLORATION_PREPARATION_CONFIG,
    FEATURE_EFFECT_SUMMARIES,
    EXPLORATION_MODE_CONFIG,
    FEATURE_UNLOCK_LABELS,
    ITEM_SLOT_STAT_WEIGHTS,
    LEGENDARY_UNIQUE_NAMES,
    LEVEL_EARLY_END,
    LEVEL_EARLY_EXP_BASE,
    LEVEL_EARLY_EXP_STEP,
    LEVEL_LATE_EXP_ACCELERATION,
    LEVEL_LATE_EXP_BASE,
    LEVEL_LATE_EXP_STEP,
    LEVEL_MID_END,
    LEVEL_MID_EXP_BASE,
    LEVEL_MID_EXP_STEP,
    MAX_POTIONS_PER_EXPLORATION,
    MATERIAL_LABELS,
    POTION_PRICE,
    RARITY_ORDER,
    RETURN_HEAL_GOLD_PER_MISSING_HP,
    SKILLS,
    SLOT_LABEL,
    SURVIVAL_GUARD_BASE_COUNT,
    WORLD_BOSSES,
)
from .stat_helpers import (
    build_weighted_stats,
    format_item_stat_text,
    merge_stats,
    nonzero_stats,
    normalize_stats,
)
from .utils import clamp, nfkc, now_ts


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


ITEM_ID_PREFIX = "itm-"
EXPLORATION_HISTORY_LIMIT = 5
DEFAULT_ACTIVE_SKILL_SLOT = "active_1"
PASSIVE_SKILL_SLOT_NAMES = tuple(f"passive_{index}" for index in range(1, 4))
ACTIVE_SKILL_SLOT_NAMES = tuple(f"active_{index}" for index in range(1, 5))
ALL_SKILL_SLOT_NAMES = PASSIVE_SKILL_SLOT_NAMES + ACTIVE_SKILL_SLOT_NAMES
SKILL_BOOK_KEY = "skill_book"
SKILL_BOOK_LABEL = "スキルの書"
SKILL_BOOK_KEY_PREFIX = f"{SKILL_BOOK_KEY}:"


class UserService:
    def __init__(self, data: Dict[str, Any], *, owner_username: str = ""):
        self.data = data
        self.owner_username = str(owner_username or "").strip().lower()

    def _is_owner_rank_content_user(self, username: Optional[str]) -> bool:
        safe_username = str(username or "").strip().lower()
        return bool(self.owner_username) and safe_username == self.owner_username

    def _sanitize_exploration_records(self, records: Any) -> Dict[str, int]:
        if not isinstance(records, dict):
            records = {}
        return {
            "best_exp": max(0, _safe_int(records.get("best_exp", 0), 0)),
            "best_gold": max(0, _safe_int(records.get("best_gold", 0), 0)),
            "best_battle_count": max(0, _safe_int(records.get("best_battle_count", 0), 0)),
            "best_exploration_runs": max(0, _safe_int(records.get("best_exploration_runs", 0), 0)),
        }

    def _sanitize_achievement_ids(self, achievement_ids: Any) -> List[str]:
        if not isinstance(achievement_ids, list):
            achievement_ids = []

        sanitized: List[str] = []
        seen = set()
        for raw_achievement_id in achievement_ids:
            achievement_id = str(raw_achievement_id or "").strip()
            if achievement_id not in ACHIEVEMENT_DEFINITIONS or achievement_id in seen:
                continue
            sanitized.append(achievement_id)
            seen.add(achievement_id)
        return sanitized

    def _sanitize_result_unlock_summaries(self, summaries: Any) -> List[str]:
        if not isinstance(summaries, list):
            summaries = []
        return [
            str(summary).strip()
            for summary in summaries
            if str(summary).strip()
        ]

    def _sanitize_area_depth_record(
        self,
        area_name: Any,
        record: Any,
    ) -> Optional[Dict[str, Any]]:
        safe_area_name = str(area_name or DEFAULT_AREA).strip() or DEFAULT_AREA
        if safe_area_name not in AREAS or not isinstance(record, dict):
            return None

        username = str(record.get("username", "") or "").strip().lower()
        battle_count = max(0, _safe_int(record.get("battle_count", 0), 0))
        if not username or battle_count <= 0:
            return None

        return {
            "area": safe_area_name,
            "username": username,
            "display_name": self._normalize_display_name(username, record.get("display_name")),
            "battle_count": battle_count,
            "total_turns": max(0, _safe_int(record.get("total_turns", 0), 0)),
            "updated_at": float(record.get("updated_at", 0.0) or 0.0),
        }

    def _sanitize_area_depth_record_update(self, value: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(value, dict):
            return None

        record = self._sanitize_area_depth_record(value.get("area"), value)
        if not record:
            return None

        previous_username = str(value.get("previous_username", "") or "").strip().lower()
        previous_record = None
        if previous_username:
            previous_record = {
                "area": record["area"],
                "username": previous_username,
                "display_name": value.get("previous_display_name"),
                "battle_count": value.get("previous_battle_count", 0),
                "total_turns": value.get("previous_total_turns", 0),
                "updated_at": value.get("previous_updated_at", 0.0),
            }
            previous_record = self._sanitize_area_depth_record(record["area"], previous_record)

        sanitized = dict(record)
        sanitized["is_first_record"] = bool(value.get("is_first_record", False))
        sanitized["holder_changed"] = bool(value.get("holder_changed", False))
        sanitized["previous_username"] = ""
        sanitized["previous_display_name"] = ""
        sanitized["previous_battle_count"] = 0
        sanitized["previous_total_turns"] = 0
        sanitized["previous_updated_at"] = 0.0
        if previous_record:
            sanitized["previous_username"] = previous_record["username"]
            sanitized["previous_display_name"] = previous_record["display_name"]
            sanitized["previous_battle_count"] = previous_record["battle_count"]
            sanitized["previous_total_turns"] = previous_record["total_turns"]
            sanitized["previous_updated_at"] = previous_record["updated_at"]
        return sanitized

    def _normalize_display_name(self, username: str, display_name: Optional[str]) -> str:
        safe_username = str(username or "").strip()
        safe_display_name = str(display_name or "").strip()
        return safe_display_name or safe_username

    def _get_slot_order(self) -> List[str]:
        preferred = ("weapon", "armor", "ring", "shoes")
        ordered = [slot_name for slot_name in preferred if slot_name in SLOT_LABEL]
        ordered.extend(
            slot_name
            for slot_name in SLOT_LABEL
            if slot_name not in ordered
        )
        return ordered

    def _build_item_stats(self, slot_name: str, power: int) -> Dict[str, int]:
        return nonzero_stats(
            build_weighted_stats(
                max(0, int(power)),
                ITEM_SLOT_STAT_WEIGHTS.get(str(slot_name or "").strip(), {}),
            )
        )

    def _sanitize_item(self, item: Dict[str, Any]) -> None:
        item["name"] = str(item.get("name", "?") or "?").strip() or "?"
        item["slot"] = str(item.get("slot", "") or "").strip()
        item["rarity"] = str(item.get("rarity", "common") or "common").strip() or "common"
        item["power"] = max(0, _safe_int(item.get("power", 0), 0))
        item["value"] = max(0, _safe_int(item.get("value", 0), 0))
        item["enhance"] = max(0, _safe_int(item.get("enhance", 0), 0))
        item["enhancement_gold_spent"] = max(0, _safe_int(item.get("enhancement_gold_spent", 0), 0))
        item["enhancement_material_spent"] = max(0, _safe_int(item.get("enhancement_material_spent", 0), 0))
        item_id = str(item.get("item_id", "") or "").strip()
        item["item_id"] = item_id or None

        enchant_key = str(item.get("enchant", "") or "").strip()
        item["enchant"] = enchant_key if enchant_key in ENCHANTMENT_EFFECT_LABELS else None

        slot_name = str(item.get("slot", "") or "").strip()
        if str(item.get("rarity", "") or "").strip() == "legendary":
            canonical_name = LEGENDARY_UNIQUE_NAMES.get(slot_name)
            if canonical_name:
                item["name"] = canonical_name
                item["series"] = canonical_name
        else:
            item["series"] = None

        raw_stats = item.get("stats")
        stats = normalize_stats(raw_stats)
        if not any(int(value) > 0 for value in stats.values()):
            stats = self._build_item_stats(slot_name, int(item.get("power", 0)))
        item["stats"] = nonzero_stats(stats)

    def _iter_user_items(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        bag = u.get("bag", [])
        if isinstance(bag, list):
            items.extend(item for item in bag if isinstance(item, dict))

        equipped = u.get("equipped", {})
        if isinstance(equipped, dict):
            items.extend(item for item in equipped.values() if isinstance(item, dict))

        return items

    def _update_next_item_id_from_value(self, u: Dict[str, Any], item_id: Optional[str]) -> None:
        safe_item_id = str(item_id or "").strip()
        if not safe_item_id.startswith(ITEM_ID_PREFIX):
            return

        suffix = safe_item_id[len(ITEM_ID_PREFIX) :]
        if not suffix.isdigit():
            return

        current_next = max(1, _safe_int(u.get("next_item_id", 1), 1))
        u["next_item_id"] = max(current_next, int(suffix) + 1)

    def _generate_item_id(self, u: Dict[str, Any], reserved_ids: Optional[set[str]] = None) -> str:
        reserved = set(reserved_ids or set())
        next_item_id = max(1, _safe_int(u.get("next_item_id", 1), 1))

        while True:
            candidate = f"{ITEM_ID_PREFIX}{next_item_id}"
            next_item_id += 1
            if candidate in reserved:
                continue
            u["next_item_id"] = next_item_id
            return candidate

    def _ensure_user_item_ids(self, u: Dict[str, Any]) -> None:
        u["next_item_id"] = max(1, _safe_int(u.get("next_item_id", 1), 1))
        items = self._iter_user_items(u)
        seen_ids: set[str] = set()

        for item in items:
            item_id = str(item.get("item_id", "") or "").strip()
            if not item_id:
                item["item_id"] = None
                continue
            if item_id in seen_ids:
                item["item_id"] = None
                continue
            seen_ids.add(item_id)
            self._update_next_item_id_from_value(u, item_id)

        for item in items:
            if item.get("item_id"):
                continue
            new_item_id = self._generate_item_id(u, seen_ids)
            item["item_id"] = new_item_id
            seen_ids.add(new_item_id)

    def _sanitize_history_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = {
            "name": str(item.get("name", "?") or "?").strip() or "?",
            "slot": str(item.get("slot", "") or "").strip(),
            "rarity": str(item.get("rarity", "common") or "common").strip() or "common",
            "power": max(0, _safe_int(item.get("power", 0), 0)),
            "enhance": max(0, _safe_int(item.get("enhance", 0), 0)),
            "enchant": item.get("enchant"),
            "item_id": str(item.get("item_id", "") or "").strip() or None,
        }
        self._sanitize_item(sanitized)
        return sanitized

    def _sanitize_exploration_history_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        area_name = str(entry.get("area", DEFAULT_AREA) or DEFAULT_AREA).strip() or DEFAULT_AREA
        if area_name not in AREAS:
            area_name = DEFAULT_AREA

        mode_key = str(entry.get("mode", DEFAULT_EXPLORATION_MODE) or DEFAULT_EXPLORATION_MODE).strip()
        if mode_key not in EXPLORATION_MODE_CONFIG:
            mode_key = DEFAULT_EXPLORATION_MODE

        raw_drop_items = entry.get("drop_items")
        if not isinstance(raw_drop_items, list):
            raw_drop_items = []
        drop_items = [
            self._sanitize_history_item(item)
            for item in raw_drop_items[:5]
            if isinstance(item, dict)
        ]

        drop_materials = entry.get("drop_materials")
        if not isinstance(drop_materials, dict):
            drop_materials = {}
        sanitized_drop_materials = {
            slot_name: max(0, _safe_int(drop_materials.get(slot_name, 0), 0))
            for slot_name in MATERIAL_LABELS
        }

        drop_enchant_materials = entry.get("drop_enchant_materials")
        if not isinstance(drop_enchant_materials, dict):
            drop_enchant_materials = {}
        sanitized_drop_enchant_materials = {
            slot_name: max(0, _safe_int(drop_enchant_materials.get(slot_name, 0), 0))
            for slot_name in ENCHANTMENT_MATERIAL_LABELS
        }

        downed = bool(entry.get("downed", False))
        result_label = "戦闘不能" if downed else "帰還"
        return {
            "claimed_at": float(entry.get("claimed_at", 0.0) or 0.0),
            "area": area_name,
            "mode": mode_key,
            "battle_count": max(0, _safe_int(entry.get("battle_count", 0), 0)),
            "exploration_runs": max(1, _safe_int(entry.get("exploration_runs", 1), 1)),
            "downed": downed,
            "result": str(entry.get("result", result_label) or result_label).strip() or result_label,
            "exp": max(0, _safe_int(entry.get("exp", 0), 0)),
            "gold": max(0, _safe_int(entry.get("gold", 0), 0)),
            "return_reason": str(entry.get("return_reason", "探索終了") or "探索終了").strip() or "探索終了",
            "drop_items": drop_items,
            "drop_item_count": max(
                len(drop_items),
                _safe_int(entry.get("drop_item_count", len(drop_items)), len(drop_items)),
            ),
            "drop_materials": sanitized_drop_materials,
            "drop_enchant_materials": sanitized_drop_enchant_materials,
            "auto_explore_stones": 1 if max(0, _safe_int(entry.get("auto_explore_stones", 0), 0)) > 0 else 0,
        }

    def _sanitize_last_recommendation(self, recommendation: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(recommendation, dict):
            return None

        action = str(recommendation.get("action", "") or "").strip()
        summary = str(recommendation.get("summary", "") or "").strip()
        reason = str(recommendation.get("reason", "") or "").strip()
        if not action and not summary and not reason:
            return None

        return {
            "action": action,
            "summary": summary,
            "reason": reason,
            "area": str(recommendation.get("area", "") or "").strip(),
            "generated_at": float(recommendation.get("generated_at", 0.0) or 0.0),
        }

    def _sanitize_record_summaries(self, values: Any) -> List[str]:
        if not isinstance(values, list):
            return []
        return [
            str(summary).strip()
            for summary in values
            if str(summary).strip()
        ]

    def _sanitize_turn_detail(self, turn_detail: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "turn": max(1, _safe_int(turn_detail.get("turn", 1), 1)),
            "player_hp_start": max(0, _safe_int(turn_detail.get("player_hp_start", 0), 0)),
            "enemy_hp_start": max(0, _safe_int(turn_detail.get("enemy_hp_start", 0), 0)),
            "player_hp_end": max(0, _safe_int(turn_detail.get("player_hp_end", 0), 0)),
            "enemy_hp_end": max(0, _safe_int(turn_detail.get("enemy_hp_end", 0), 0)),
            "player_action": str(turn_detail.get("player_action", "") or "").strip() or "行動なし",
            "enemy_action": str(turn_detail.get("enemy_action", "") or "").strip() or "行動なし",
            "guarded": bool(turn_detail.get("guarded", False)),
        }

    def _sanitize_battle_log(self, battle: Dict[str, Any]) -> Dict[str, Any]:
        battle["monster"] = str(battle.get("monster", "?") or "?").strip() or "?"
        battle["turns"] = max(0, _safe_int(battle.get("turns", 0), 0))
        battle["damage_taken"] = max(0, _safe_int(battle.get("damage_taken", 0), 0))
        battle["won"] = bool(battle.get("won", False))
        battle["escaped"] = bool(battle.get("escaped", False))
        battle["auto_explore_stones"] = 1 if max(0, _safe_int(battle.get("auto_explore_stones", 0), 0)) > 0 else 0

        raw_log = battle.get("log")
        if not isinstance(raw_log, list):
            raw_log = []
        battle["log"] = [
            str(log_line).strip()
            for log_line in raw_log
            if str(log_line).strip()
        ]

        raw_turn_details = battle.get("turn_details")
        if not isinstance(raw_turn_details, list):
            raw_turn_details = []
        battle["turn_details"] = [
            self._sanitize_turn_detail(turn_detail)
            for turn_detail in raw_turn_details
            if isinstance(turn_detail, dict)
        ]

        drop_items = battle.get("drop_items")
        if not isinstance(drop_items, list):
            drop_items = []
        battle["drop_items"] = [
            item
            for item in drop_items
            if isinstance(item, dict)
        ]
        for item in battle["drop_items"]:
            self._sanitize_item(item)

        battle_drop_materials = battle.get("drop_materials")
        if not isinstance(battle_drop_materials, dict):
            battle_drop_materials = {}
            battle["drop_materials"] = battle_drop_materials
        for slot_name in MATERIAL_LABELS:
            battle_drop_materials[slot_name] = max(0, _safe_int(battle_drop_materials.get(slot_name, 0), 0))

        battle_drop_enchant_materials = battle.get("drop_enchant_materials")
        if not isinstance(battle_drop_enchant_materials, dict):
            battle_drop_enchant_materials = {}
            battle["drop_enchant_materials"] = battle_drop_enchant_materials
        for slot_name in ENCHANTMENT_MATERIAL_LABELS:
            battle_drop_enchant_materials[slot_name] = max(
                0,
                _safe_int(battle_drop_enchant_materials.get(slot_name, 0), 0),
            )

        return battle

    def get_user(self, username: str) -> Dict[str, Any]:
        uname = username.lower()
        users = self.data.get("users")
        if not isinstance(users, dict):
            users = {}
            self.data["users"] = users
        is_new_user = False
        if uname not in users:
            users[uname] = {}
            is_new_user = True

        u = users[uname]
        self._ensure_user_defaults(u, is_new_user=is_new_user)
        self._sanitize_explore_data(u)
        self._sync_level_stats(u)
        return u

    def _ensure_user_defaults(self, u: Dict[str, Any], *, is_new_user: bool = False) -> None:
        u.setdefault("chat_exp", 0)
        u.setdefault("chat_exp_ts", 0.0)
        u["chat_exp"] = max(0, _safe_int(u.get("chat_exp", 0), 0))

        u.setdefault("adventure_exp", 0)
        u.setdefault("gold", 0)
        u.setdefault("potions", 0)
        u.setdefault("auto_potion_refill_target", MAX_POTIONS_PER_EXPLORATION)
        u.setdefault("auto_explore_stones", 0)
        u.setdefault("auto_explore_fragments", 0)
        u.setdefault("next_item_id", 1)
        u.setdefault("starter_kit_granted", not is_new_user)
        u["adventure_exp"] = max(0, _safe_int(u.get("adventure_exp", 0), 0))
        u["gold"] = max(0, _safe_int(u.get("gold", 0), 0))
        u["potions"] = max(0, _safe_int(u.get("potions", 0), 0))
        u["auto_potion_refill_target"] = clamp(
            _safe_int(
                u.get("auto_potion_refill_target", MAX_POTIONS_PER_EXPLORATION),
                MAX_POTIONS_PER_EXPLORATION,
            ),
            0,
            MAX_POTIONS_PER_EXPLORATION,
        )
        u["auto_explore_stones"] = 1 if max(0, _safe_int(u.get("auto_explore_stones", 0), 0)) > 0 else 0
        u["auto_explore_fragments"] = max(0, _safe_int(u.get("auto_explore_fragments", 0), 0))
        u["next_item_id"] = max(1, _safe_int(u.get("next_item_id", 1), 1))
        u["starter_kit_granted"] = bool(u.get("starter_kit_granted", not is_new_user))

        u.setdefault("hp", DEFAULT_MAX_HP)
        u.setdefault("max_hp", DEFAULT_MAX_HP)
        u.setdefault("down", False)
        u["hp"] = max(0, _safe_int(u.get("hp", DEFAULT_MAX_HP), DEFAULT_MAX_HP))
        u["max_hp"] = max(1, _safe_int(u.get("max_hp", DEFAULT_MAX_HP), DEFAULT_MAX_HP))
        u["down"] = bool(u.get("down", False))
        u["display_name"] = self._normalize_display_name(
            u.get("display_name", ""),
            u.get("display_name", ""),
        )
        u["achievements"] = self._sanitize_achievement_ids(u.get("achievements"))
        active_title = str(u.get("active_title", "") or "").strip()
        if active_title not in u["achievements"]:
            active_title = ""
        elif not str(self._get_achievement_definition(active_title).get("title", "") or "").strip():
            active_title = ""
        u["active_title"] = active_title

        if not isinstance(u.get("bag"), list):
            u["bag"] = []
        u["bag"] = [item for item in u["bag"] if isinstance(item, dict)]
        for item in u["bag"]:
            self._sanitize_item(item)

        materials = u.get("materials")
        if not isinstance(materials, dict):
            materials = {}
            u["materials"] = materials
        for slot_name in MATERIAL_LABELS:
            materials[slot_name] = max(0, _safe_int(materials.get(slot_name, 0), 0))

        enchant_materials = u.get("enchant_materials")
        if not isinstance(enchant_materials, dict):
            enchant_materials = {}
            u["enchant_materials"] = enchant_materials
        for slot_name in ENCHANTMENT_MATERIAL_LABELS:
            enchant_materials[slot_name] = max(0, _safe_int(enchant_materials.get(slot_name, 0), 0))

        exploration_preparation = u.get("exploration_preparation")
        if not isinstance(exploration_preparation, dict):
            exploration_preparation = {}
            u["exploration_preparation"] = exploration_preparation
        for slot_name in EXPLORATION_PREPARATION_CONFIG:
            exploration_preparation[slot_name] = bool(exploration_preparation.get(slot_name, False))

        equipped = u.get("equipped")
        if not isinstance(equipped, dict):
            equipped = {}
            u["equipped"] = equipped
        for slot_name in self._get_slot_order():
            equipped.setdefault(slot_name, None)
        for slot_name, item in equipped.items():
            if isinstance(item, dict):
                self._sanitize_item(item)
            elif slot_name in SLOT_LABEL:
                equipped[slot_name] = None

        enchant_progress = u.get("enchant_progress")
        if not isinstance(enchant_progress, dict):
            enchant_progress = {}
            u["enchant_progress"] = enchant_progress
        for slot_name in ENCHANTMENT_MATERIAL_LABELS:
            enchant_progress[slot_name] = bool(enchant_progress.get(slot_name, False))
            if any(self.get_item_enchant_key(item) == slot_name for item in self._iter_user_items(u)):
                enchant_progress[slot_name] = True

        self._ensure_user_item_ids(u)

        protected_item_ids = u.get("protected_item_ids")
        if not isinstance(protected_item_ids, list):
            protected_item_ids = []
        existing_item_ids = {
            str(item.get("item_id"))
            for item in self._iter_user_items(u)
            if str(item.get("item_id", "") or "").strip()
        }
        deduped_protected_ids: List[str] = []
        seen_protected_ids = set()
        for item_id in protected_item_ids:
            safe_item_id = str(item_id or "").strip()
            if not safe_item_id or safe_item_id in seen_protected_ids:
                continue
            if safe_item_id not in existing_item_ids:
                continue
            deduped_protected_ids.append(safe_item_id)
            seen_protected_ids.add(safe_item_id)
        u["protected_item_ids"] = deduped_protected_ids

        raw_slot_unlocks = u.get("slot_unlocks")
        if not isinstance(raw_slot_unlocks, dict):
            raw_slot_unlocks = {}
            u["slot_unlocks"] = raw_slot_unlocks
        default_slot_unlocks = {
            "weapon": True,
            "armor": not is_new_user,
            "ring": not is_new_user,
            "shoes": not is_new_user,
        }
        for slot_name, default_unlocked in default_slot_unlocks.items():
            if slot_name not in SLOT_LABEL:
                continue
            raw_slot_unlocks[slot_name] = bool(raw_slot_unlocks.get(slot_name, default_unlocked))

        raw_boss_clear_areas = u.get("boss_clear_areas")
        if isinstance(raw_boss_clear_areas, list):
            u["boss_clear_areas"] = [
                area_name
                for area_name in raw_boss_clear_areas
                if area_name in AREAS
            ]
        else:
            u["boss_clear_areas"] = [] if is_new_user else list(AREAS.keys())

        claimed_first_clear_reward_areas = u.get("claimed_first_clear_reward_areas")
        if isinstance(claimed_first_clear_reward_areas, list):
            deduped_reward_areas: List[str] = []
            seen_reward_areas = set()
            for area_name in claimed_first_clear_reward_areas:
                safe_area_name = str(area_name or "").strip()
                if not safe_area_name or safe_area_name not in AREAS or safe_area_name in seen_reward_areas:
                    continue
                deduped_reward_areas.append(safe_area_name)
                seen_reward_areas.add(safe_area_name)
            u["claimed_first_clear_reward_areas"] = deduped_reward_areas
        else:
            u["claimed_first_clear_reward_areas"] = []

        explore = u.get("explore")
        if not isinstance(explore, dict):
            explore = {}
            u["explore"] = explore
        explore.setdefault("state", "idle")
        explore.setdefault("area", "")
        explore.setdefault("mode", DEFAULT_EXPLORATION_MODE)
        explore.setdefault("started_at", 0.0)
        explore.setdefault("ends_at", 0.0)
        explore.setdefault("auto_repeat", False)
        explore.setdefault("notified_ready", False)
        explore.setdefault("result", None)
        u.setdefault("selected_active_skill", "")
        u.setdefault("skill_levels", {})
        u.setdefault("selected_skill_slots", {})
        u.setdefault("auto_fill_active_skills", True)
        u.setdefault("auto_repeat_result", None)
        u.setdefault("last_exploration_result", None)
        u["exploration_records"] = self._sanitize_exploration_records(u.get("exploration_records"))

        exploration_history = u.get("exploration_history")
        if not isinstance(exploration_history, list):
            exploration_history = []
        u["exploration_history"] = [
            self._sanitize_exploration_history_entry(entry)
            for entry in exploration_history[:EXPLORATION_HISTORY_LIMIT]
            if isinstance(entry, dict)
        ]

        self._sync_feature_unlocks(u)
        self._sync_claimed_first_clear_rewards(u)
        self._sync_skill_progress(u)
        self._sync_selected_skill_loadouts(u)

        u["last_recommendation"] = self._sanitize_last_recommendation(u.get("last_recommendation"))

    def _sanitize_exploration_result(self, result: Dict[str, Any]) -> None:
        r_area = result.get("area")
        if r_area and r_area not in AREAS:
            result["area"] = DEFAULT_AREA

        kills = result.get("kills")
        if not isinstance(kills, list):
            result["kills"] = []

        drop_items = result.get("drop_items")
        if not isinstance(drop_items, list):
            drop_items = []
            result["drop_items"] = drop_items
        result["drop_items"] = [item for item in drop_items if isinstance(item, dict)]
        for item in result["drop_items"]:
            self._sanitize_item(item)

        result["auto_explore_stones"] = 1 if max(0, _safe_int(result.get("auto_explore_stones", 0), 0)) > 0 else 0
        result["auto_repeat"] = bool(result.get("auto_repeat", False))
        drop_materials = result.get("drop_materials")
        if not isinstance(drop_materials, dict):
            drop_materials = {}
            result["drop_materials"] = drop_materials
        for slot_name in MATERIAL_LABELS:
            drop_materials[slot_name] = max(0, _safe_int(drop_materials.get(slot_name, 0), 0))

        drop_enchant_materials = result.get("drop_enchant_materials")
        if not isinstance(drop_enchant_materials, dict):
            drop_enchant_materials = {}
            result["drop_enchant_materials"] = drop_enchant_materials
        for slot_name in ENCHANTMENT_MATERIAL_LABELS:
            drop_enchant_materials[slot_name] = max(0, _safe_int(drop_enchant_materials.get(slot_name, 0), 0))

        battle_logs = result.get("battle_logs")
        if not isinstance(battle_logs, list):
            battle_logs = []
        result["battle_logs"] = [
            self._sanitize_battle_log(battle)
            for battle in battle_logs
            if isinstance(battle, dict)
        ]

        total_turns_from_logs = sum(
            max(0, _safe_int(log.get("turns", 0), 0))
            for log in result["battle_logs"]
        )
        result["battle_count"] = get_battle_count(result)
        result["total_turns"] = max(
            max(0, _safe_int(result.get("total_turns", 0), 0)),
            total_turns_from_logs,
        )
        result["exploration_runs"] = max(0, _safe_int(result.get("exploration_runs", 1), 1))
        result["return_reason"] = str(result.get("return_reason", "探索終了") or "探索終了").strip() or "探索終了"
        result["return_info"] = sanitize_return_info(result.get("return_info"), result["return_reason"])
        result["returned_safe"] = bool(result.get("returned_safe", True))
        result["potions_used"] = max(0, _safe_int(result.get("potions_used", 0), 0))
        result["auto_potions_bought"] = max(0, _safe_int(result.get("auto_potions_bought", 0), 0))
        result["auto_potion_refill_cost"] = max(
            0,
            _safe_int(result.get("auto_potion_refill_cost", 0), 0),
        )
        result["auto_hp_heal_cost"] = max(0, _safe_int(result.get("auto_hp_heal_cost", 0), 0))
        result["auto_hp_restored"] = max(0, _safe_int(result.get("auto_hp_restored", 0), 0))
        result["potions_after_claim"] = max(0, _safe_int(result.get("potions_after_claim", 0), 0))
        result.setdefault("mode", DEFAULT_EXPLORATION_MODE)
        result["downed"] = bool(result.get("downed", False) or not result["returned_safe"])
        result["armor_guards_used"] = max(0, _safe_int(result.get("armor_guards_used", 0), 0))
        result["armor_guards_total"] = max(0, _safe_int(result.get("armor_guards_total", 0), 0))
        result["armor_enchant_consumed"] = bool(result.get("armor_enchant_consumed", False))
        result["auto_armor_reenchants"] = max(
            0,
            _safe_int(result.get("auto_armor_reenchants", 0), 0),
        )
        result.pop("world_boss_encountered", None)
        result.pop("world_boss_defeated", None)
        result.pop("world_boss_name", None)
        result.pop("world_boss_battle_number", None)
        newly_cleared_boss_areas = result.get("newly_cleared_boss_areas")
        if not isinstance(newly_cleared_boss_areas, list):
            newly_cleared_boss_areas = []
        result["newly_cleared_boss_areas"] = [
            area_name
            for area_name in newly_cleared_boss_areas
            if area_name in AREAS
        ]
        newly_unlocked_slots = result.get("newly_unlocked_slots")
        if not isinstance(newly_unlocked_slots, list):
            newly_unlocked_slots = []
        result["newly_unlocked_slots"] = [
            slot_name
            for slot_name in newly_unlocked_slots
            if slot_name in SLOT_LABEL
        ]
        newly_unlocked_features = result.get("newly_unlocked_features")
        if not isinstance(newly_unlocked_features, list):
            newly_unlocked_features = []
        result["newly_unlocked_features"] = [
            str(feature_key).strip()
            for feature_key in newly_unlocked_features
            if str(feature_key).strip()
        ]
        result["granted_auto_explore_fragments"] = max(
            0,
            _safe_int(result.get("granted_auto_explore_fragments", 0), 0),
        )
        first_clear_reward_summaries = result.get("first_clear_reward_summaries")
        if not isinstance(first_clear_reward_summaries, list):
            first_clear_reward_summaries = []
        result["first_clear_reward_summaries"] = [
            str(summary).strip()
            for summary in first_clear_reward_summaries
            if str(summary).strip()
        ]
        result["new_records"] = self._sanitize_record_summaries(result.get("new_records"))
        result["new_achievements"] = self._sanitize_result_unlock_summaries(result.get("new_achievements"))
        result["new_titles"] = self._sanitize_result_unlock_summaries(result.get("new_titles"))
        area_depth_record_update = self._sanitize_area_depth_record_update(
            result.get("area_depth_record_update")
        )
        if area_depth_record_update:
            result["area_depth_record_update"] = area_depth_record_update
        else:
            result.pop("area_depth_record_update", None)
        if result.get("mode") not in EXPLORATION_MODE_CONFIG:
            result["mode"] = DEFAULT_EXPLORATION_MODE

    def _sanitize_explore_data(self, u: Dict[str, Any]) -> None:
        explore = u.get("explore", {})
        area = explore.get("area")
        mode = str(explore.get("mode", DEFAULT_EXPLORATION_MODE))
        result = explore.get("result")

        if area and area not in AREAS:
            explore["area"] = DEFAULT_AREA
        if mode not in EXPLORATION_MODE_CONFIG:
            explore["mode"] = DEFAULT_EXPLORATION_MODE
        explore["auto_repeat"] = bool(explore.get("auto_repeat", False))
        explore["notified_ready"] = bool(explore.get("notified_ready", False))

        if isinstance(result, dict):
            self._sanitize_exploration_result(result)

        auto_repeat_result = u.get("auto_repeat_result")
        if isinstance(auto_repeat_result, dict):
            self._sanitize_exploration_result(auto_repeat_result)
            auto_repeat_result["exploration_runs"] = max(
                0,
                _safe_int(auto_repeat_result.get("exploration_runs", 0), 0),
            )
        elif auto_repeat_result is not None:
            u["auto_repeat_result"] = None

        last_result = u.get("last_exploration_result")
        if isinstance(last_result, dict):
            self._sanitize_exploration_result(last_result)
            last_result["exploration_runs"] = max(1, _safe_int(last_result.get("exploration_runs", 1), 1))
        elif last_result is not None:
            u["last_exploration_result"] = None

    def remember_display_name(self, username: str, display_name: Optional[str]) -> str:
        target = str(username or "").lower().strip()
        if not target:
            return self._normalize_display_name("", display_name)

        u = self.get_user(target)
        safe_display_name = self._normalize_display_name(target, display_name)
        if safe_display_name:
            u["display_name"] = safe_display_name
        return self.get_display_name(target)

    def get_display_name(self, username: str, fallback: Optional[str] = None) -> str:
        target = str(username or "").lower().strip()
        safe_fallback = self._normalize_display_name(target, fallback)
        if not target:
            return safe_fallback

        users = self.data.get("users")
        if not isinstance(users, dict):
            return safe_fallback

        raw_user = users.get(target)
        if not isinstance(raw_user, dict):
            return safe_fallback

        stored = self._normalize_display_name(target, raw_user.get("display_name"))
        return stored or safe_fallback

    def _get_achievement_definition(self, achievement_id: str) -> Dict[str, Any]:
        safe_achievement_id = str(achievement_id or "").strip()
        return ACHIEVEMENT_DEFINITIONS.get(safe_achievement_id, {})

    def get_unlocked_achievement_ids(self, u: Dict[str, Any]) -> List[str]:
        achievement_ids = self._sanitize_achievement_ids(u.get("achievements"))
        u["achievements"] = achievement_ids
        return achievement_ids

    def get_unlocked_achievements(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        achievements: List[Dict[str, Any]] = []
        for achievement_id in self.get_unlocked_achievement_ids(u):
            definition = self._get_achievement_definition(achievement_id)
            if not definition:
                continue
            entry = dict(definition)
            entry["achievement_id"] = achievement_id
            achievements.append(entry)
        return achievements

    def get_unlocked_titles(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        titles: List[Dict[str, Any]] = []
        for achievement in self.get_unlocked_achievements(u):
            title_label = str(achievement.get("title", "") or "").strip()
            if not title_label:
                continue
            entry = dict(achievement)
            entry["title_label"] = title_label
            titles.append(entry)
        return titles

    def get_achievement_count(self, u: Dict[str, Any]) -> int:
        return len(self.get_unlocked_achievement_ids(u))

    def get_active_title(self, u: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        active_title_id = str(u.get("active_title", "") or "").strip()
        if not active_title_id:
            return None
        if active_title_id not in self.get_unlocked_achievement_ids(u):
            return None

        definition = self._get_achievement_definition(active_title_id)
        title_label = str(definition.get("title", "") or "").strip()
        if not definition or not title_label:
            return None

        entry = dict(definition)
        entry["achievement_id"] = active_title_id
        entry["title_label"] = title_label
        return entry

    def get_active_title_label(self, u: Dict[str, Any]) -> str:
        active_title = self.get_active_title(u)
        if not isinstance(active_title, dict):
            return ""
        return str(active_title.get("title_label", "") or "").strip()

    def format_titled_display_name(self, display_name: Optional[str], title_label: Optional[str]) -> str:
        safe_display_name = str(display_name or "?").strip() or "?"
        safe_title_label = str(title_label or "").strip()
        if not safe_title_label:
            return safe_display_name
        return f"[{safe_title_label}] {safe_display_name}"

    def _build_unlock_result(self, unlocked_entries: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        return {
            "new_achievement_ids": [
                str(entry.get("achievement_id", "") or "").strip()
                for entry in unlocked_entries
                if str(entry.get("achievement_id", "") or "").strip()
            ],
            "new_achievements": [
                str(entry.get("name", "") or "").strip()
                for entry in unlocked_entries
                if str(entry.get("name", "") or "").strip()
            ],
            "new_titles": [
                str(entry.get("title", "") or "").strip()
                for entry in unlocked_entries
                if str(entry.get("title", "") or "").strip()
            ],
        }

    def unlock_achievement(self, u: Dict[str, Any], achievement_id: str) -> Optional[Dict[str, Any]]:
        safe_achievement_id = str(achievement_id or "").strip()
        definition = self._get_achievement_definition(safe_achievement_id)
        if not definition:
            return None

        achievement_ids = self.get_unlocked_achievement_ids(u)
        if safe_achievement_id in achievement_ids:
            return None

        achievement_ids.append(safe_achievement_id)
        u["achievements"] = achievement_ids

        title_label = str(definition.get("title", "") or "").strip()
        current_active_title = str(u.get("active_title", "") or "").strip()
        if title_label and (
            (not current_active_title and len(achievement_ids) == 1)
            or current_active_title not in achievement_ids
        ):
            u["active_title"] = safe_achievement_id

        entry = dict(definition)
        entry["achievement_id"] = safe_achievement_id
        entry["title"] = title_label
        return entry

    def _has_legendary_drop(self, result: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(result, dict):
            return False
        drop_items = result.get("drop_items")
        if not isinstance(drop_items, list):
            return False
        return any(
            isinstance(item, dict)
            and str(item.get("rarity", "") or "").strip() == "legendary"
            for item in drop_items
        )

    def apply_exploration_achievement_unlocks(self, u: Dict[str, Any], result: Optional[Dict[str, Any]]) -> Dict[str, List[str]]:
        if not isinstance(result, dict):
            return self._build_unlock_result([])

        unlocked_entries: List[Dict[str, Any]] = []
        newly_cleared_boss_areas = result.get("newly_cleared_boss_areas")
        if not isinstance(newly_cleared_boss_areas, list):
            newly_cleared_boss_areas = []
        if "朝の森" in newly_cleared_boss_areas:
            unlocked = self.unlock_achievement(u, "forest_boss_clear")
            if unlocked:
                unlocked_entries.append(unlocked)

        if self._has_legendary_drop(result):
            unlocked = self.unlock_achievement(u, "legendary_finder")
            if unlocked:
                unlocked_entries.append(unlocked)

        new_records = result.get("new_records")
        if isinstance(new_records, list) and new_records:
            unlocked = self.unlock_achievement(u, "record_breaker")
            if unlocked:
                unlocked_entries.append(unlocked)

        newly_unlocked_features = result.get("newly_unlocked_features")
        if not isinstance(newly_unlocked_features, list):
            newly_unlocked_features = []
        if "auto_repeat" in {str(feature_key).strip() for feature_key in newly_unlocked_features}:
            unlocked = self.unlock_achievement(u, "auto_repeat_unlocked")
            if unlocked:
                unlocked_entries.append(unlocked)

        return self._build_unlock_result(unlocked_entries)

    def apply_world_boss_join_achievements(self, u: Dict[str, Any]) -> Dict[str, List[str]]:
        unlocked = self.unlock_achievement(u, "wb_first_join")
        if not unlocked:
            return self._build_unlock_result([])
        return self._build_unlock_result([unlocked])

    def apply_world_boss_result_achievements(self, u: Dict[str, Any], result: Optional[Dict[str, Any]]) -> Dict[str, List[str]]:
        if not isinstance(result, dict):
            return self._build_unlock_result([])

        unlocked_entries: List[Dict[str, Any]] = []
        eligible = bool(result.get("eligible", False))
        cleared = bool(result.get("cleared", False))
        rank = max(1, _safe_int(result.get("rank", 1), 1))
        participant_count = max(1, _safe_int(result.get("participant_count", 1), 1))

        if eligible and cleared:
            unlocked = self.unlock_achievement(u, "wb_first_clear")
            if unlocked:
                unlocked_entries.append(unlocked)

        if eligible and participant_count >= 3 and rank <= 3:
            unlocked = self.unlock_achievement(u, "wb_top_three")
            if unlocked:
                unlocked_entries.append(unlocked)

        if eligible and rank == 1:
            unlocked = self.unlock_achievement(u, "wb_mvp")
            if unlocked:
                unlocked_entries.append(unlocked)

        return self._build_unlock_result(unlocked_entries)

    def _find_matching_title_achievement_id(self, u: Dict[str, Any], title_query: Optional[str]) -> Optional[str]:
        normalized_query = nfkc(str(title_query or "")).strip().lower()
        if not normalized_query:
            return None

        for title in self.get_unlocked_titles(u):
            achievement_id = str(title.get("achievement_id", "") or "").strip()
            if not achievement_id:
                continue

            candidates = {
                achievement_id.lower(),
                nfkc(str(title.get("name", "") or "")).strip().lower(),
                nfkc(str(title.get("title_label", "") or "")).strip().lower(),
            }
            for alias in title.get("aliases", []):
                safe_alias = nfkc(str(alias or "")).strip().lower()
                if safe_alias:
                    candidates.add(safe_alias)

            if normalized_query in candidates:
                return achievement_id
        return None

    def set_active_title(self, u: Dict[str, Any], title_query: Optional[str]) -> Tuple[bool, str]:
        unlocked_titles = self.get_unlocked_titles(u)
        if not unlocked_titles:
            return False, "まだ称号を持っていません。"

        normalized_query = nfkc(str(title_query or "")).strip()
        if not normalized_query:
            current_title = self.get_active_title_label(u) or "なし"
            return False, f"切替先を指定してください。 現在 {current_title} / `!称号 変更 <名前>`"

        normalized_lower = normalized_query.lower()
        if normalized_query in {"解除", "なし"} or normalized_lower in {"off", "none", "clear", "reset"}:
            u["active_title"] = ""
            return True, "称号表示を解除しました。"

        achievement_id = self._find_matching_title_achievement_id(u, normalized_query)
        if not achievement_id:
            return False, "該当する称号が見つかりません。"

        definition = self._get_achievement_definition(achievement_id)
        title_label = str(definition.get("title", "") or "").strip() or "称号"
        if str(u.get("active_title", "") or "").strip() == achievement_id:
            return True, f"称号はすでに {title_label} です。"

        u["active_title"] = achievement_id
        return True, f"称号を {title_label} に変更しました。"

    def _get_area_first_clear_rewards(self, area_name: str) -> Dict[str, Any]:
        safe_area_name = str(area_name or "").strip()
        area = AREAS.get(safe_area_name, {})
        raw_rewards = area.get("first_clear_rewards")
        if not isinstance(raw_rewards, dict):
            raw_rewards = {}

        raw_unlock_slots = raw_rewards.get("unlock_slots")
        if not isinstance(raw_unlock_slots, list):
            raw_unlock_slots = []
        unlock_slots: List[str] = []
        for slot_name in raw_unlock_slots:
            safe_slot_name = str(slot_name).strip()
            if safe_slot_name in SLOT_LABEL:
                unlock_slots.append(safe_slot_name)

        raw_unlock_features = raw_rewards.get("unlock_features")
        if not isinstance(raw_unlock_features, list):
            raw_unlock_features = []
        unlock_features: List[str] = []
        for feature_key in raw_unlock_features:
            safe_feature_key = str(feature_key).strip()
            if safe_feature_key:
                unlock_features.append(safe_feature_key)

        return {
            "unlock_slots": unlock_slots,
            "unlock_features": unlock_features,
            "auto_explore_fragments": max(
                0,
                _safe_int(raw_rewards.get("auto_explore_fragments", 0), 0),
            ),
            "summary": str(raw_rewards.get("summary", "") or "").strip(),
        }

    def _build_first_clear_reward_summaries(
        self,
        rewards: Dict[str, Any],
        *,
        newly_unlocked_slots: List[str],
        newly_unlocked_features: List[str],
        granted_auto_explore_fragments: int,
    ) -> List[str]:
        summary = str(rewards.get("summary", "") or "").strip()
        if summary and (
            newly_unlocked_slots
            or newly_unlocked_features
            or granted_auto_explore_fragments > 0
        ):
            return [summary]

        summaries: List[str] = []
        if newly_unlocked_slots:
            slot_labels = [
                SLOT_LABEL.get(slot_name, slot_name)
                for slot_name in newly_unlocked_slots
            ]
            if slot_labels:
                summaries.append(f"{'・'.join(slot_labels)}スロット解放")

        if newly_unlocked_features:
            feature_labels = [
                FEATURE_UNLOCK_LABELS.get(feature_key, feature_key)
                for feature_key in newly_unlocked_features
                if str(feature_key).strip()
            ]
            if feature_labels:
                summaries.append(" / ".join(feature_labels))

        if granted_auto_explore_fragments > 0:
            summaries.append(f"自動周回欠片 +{granted_auto_explore_fragments}")

        return summaries

    def _sync_claimed_first_clear_rewards(self, u: Dict[str, Any]) -> None:
        boss_clear_areas = u.get("boss_clear_areas", [])
        if not isinstance(boss_clear_areas, list):
            return

        for area_name in boss_clear_areas:
            if area_name in AREAS:
                self.claim_area_first_clear_rewards(u, area_name)

    def _sync_level_stats(self, u: Dict[str, Any]) -> None:
        level = self.get_adventure_level(u)
        passive_bonuses = self.get_passive_skill_bonuses(u)
        equipment_stats = self.get_total_equipment_stats(u)
        new_max_hp = (
            self.get_max_hp_by_level(level)
            + max(0, int(passive_bonuses.get("max_hp", 0)))
            + max(0, int(equipment_stats.get("max_hp", 0)))
        )

        old_max_hp = _safe_int(u.get("max_hp", new_max_hp), new_max_hp)
        current_hp = _safe_int(u.get("hp", new_max_hp), new_max_hp)

        if old_max_hp != new_max_hp:
            hp_diff = new_max_hp - old_max_hp
            u["max_hp"] = new_max_hp
            u["hp"] = clamp(current_hp + hp_diff, 0, new_max_hp)
        else:
            u["max_hp"] = new_max_hp
            u["hp"] = clamp(current_hp, 0, new_max_hp)

    def _has_feature_unlock(self, u: Dict[str, Any], feature_key: str) -> bool:
        feature_unlocks = u.get("feature_unlocks", {})
        if not isinstance(feature_unlocks, dict):
            return False
        return bool(feature_unlocks.get(feature_key, False))

    def is_feature_unlocked(self, u: Dict[str, Any], feature_key: str) -> bool:
        return self._has_feature_unlock(u, feature_key)

    def is_auto_repeat_route_unlocked(self, u: Dict[str, Any]) -> bool:
        return self._has_feature_unlock(u, "auto_repeat_route")

    def get_auto_repeat_required_fragments(self, u: Dict[str, Any]) -> int:
        return max(1, int(AUTO_REPEAT_UNLOCK_FRAGMENT_REQUIREMENT))

    def get_auto_repeat_progress(self, u: Dict[str, Any]) -> Dict[str, Any]:
        fragments = max(0, _safe_int(u.get("auto_explore_fragments", 0), 0))
        route_unlocked = self.is_auto_repeat_route_unlocked(u)
        feature_unlocks = u.get("feature_unlocks", {})
        legacy_unlocked = False
        if isinstance(feature_unlocks, dict):
            legacy_unlocked = bool(feature_unlocks.get("auto_repeat", False))
        stone_unlocked = max(0, _safe_int(u.get("auto_explore_stones", 0), 0)) > 0
        required_fragments = self.get_auto_repeat_required_fragments(u)
        unlocked = legacy_unlocked or stone_unlocked or (
            route_unlocked and fragments >= required_fragments
        )
        remaining_fragments = 0 if unlocked else max(0, required_fragments - fragments)
        return {
            "unlocked": unlocked,
            "route_unlocked": route_unlocked,
            "fragments": fragments,
            "required_fragments": required_fragments,
            "remaining_fragments": remaining_fragments,
            "legacy_stone_unlocked": stone_unlocked,
        }

    def is_auto_repeat_unlocked(self, u: Dict[str, Any]) -> bool:
        return bool(self.get_auto_repeat_progress(u).get("unlocked", False))

    def _sync_feature_unlocks(self, u: Dict[str, Any]) -> Dict[str, Any]:
        feature_unlocks = u.get("feature_unlocks")
        if not isinstance(feature_unlocks, dict):
            feature_unlocks = {}
        feature_unlocks["auto_repeat"] = self.is_auto_repeat_unlocked(u)
        feature_unlocks["armor_slot"] = bool(
            feature_unlocks.get("armor_slot", False) or self.is_slot_unlocked(u, "armor")
        )
        feature_unlocks["ring_slot"] = bool(
            feature_unlocks.get("ring_slot", False) or self.is_slot_unlocked(u, "ring")
        )
        u["feature_unlocks"] = feature_unlocks
        return feature_unlocks

    def _normalize_skill_query(self, value: Any) -> str:
        return nfkc(str(value or "")).strip().lower()

    def _iter_sorted_skills(self) -> List[Dict[str, Any]]:
        return sorted(
            (dict(skill) for skill in SKILLS.values()),
            key=lambda skill: (
                int(skill.get("sort_order", 0)),
                str(skill.get("slot", "")),
                str(skill.get("name", "")),
                str(skill.get("skill_id", "")),
            ),
        )

    def _is_skill_book_material(self, material_key: Any) -> bool:
        safe_material_key = str(material_key or "").strip()
        return safe_material_key == SKILL_BOOK_KEY or safe_material_key.startswith(SKILL_BOOK_KEY_PREFIX)

    def _get_skill_book_skill_id(self, material_key: Any) -> Optional[str]:
        safe_material_key = str(material_key or "").strip()
        if not safe_material_key.startswith(SKILL_BOOK_KEY_PREFIX):
            return None
        skill_id = safe_material_key[len(SKILL_BOOK_KEY_PREFIX):].strip()
        return skill_id or None

    def _get_skill_book_key(self, skill: Any) -> str:
        if isinstance(skill, dict):
            skill_id = str(skill.get("skill_id", "") or "").strip()
        else:
            skill_id = str(skill or "").strip()
        return f"{SKILL_BOOK_KEY_PREFIX}{skill_id}" if skill_id else SKILL_BOOK_KEY

    def _get_skill_book_label(self, skill: Any) -> str:
        skill_name = ""
        if isinstance(skill, dict):
            skill_name = str(skill.get("name", "") or "").strip()
        else:
            safe_skill_id = str(skill or "").strip()
            skill_data = SKILLS.get(safe_skill_id)
            if isinstance(skill_data, dict):
                skill_name = str(skill_data.get("name", "") or "").strip()
        return f"{skill_name}の書" if skill_name else SKILL_BOOK_LABEL

    def _build_skill_query_candidates(self, skill: Dict[str, Any]) -> set[str]:
        base_terms = {
            str(skill.get("skill_id", "") or "").strip(),
            str(skill.get("name", "") or "").strip(),
        }
        base_terms.update(
            str(alias or "").strip()
            for alias in skill.get("aliases", [])
            if str(alias or "").strip()
        )

        candidates = {
            self._normalize_skill_query(term)
            for term in base_terms
            if self._normalize_skill_query(term)
        }
        candidates.update(
            self._normalize_skill_query(label)
            for label in (
                self._get_skill_book_label(skill),
                f"{str(skill.get('name', '') or '').strip()}の強化書",
                f"{str(skill.get('name', '') or '').strip()}強化書",
            )
            if self._normalize_skill_query(label)
        )
        candidates.update(
            self._normalize_skill_query(f"{term}の書")
            for term in base_terms
            if self._normalize_skill_query(f"{term}の書")
        )
        return candidates

    def _normalize_skill_upgrade_costs(
        self,
        skill_data: Dict[str, Any],
        costs: Any,
    ) -> Dict[str, int]:
        if not isinstance(costs, dict):
            return {}

        normalized: Dict[str, int] = {}
        legacy_skill_book_cost = 0
        for material_key, raw_amount in costs.items():
            safe_material_key = str(material_key or "").strip()
            safe_amount = max(0, int(raw_amount or 0))
            if not safe_material_key or safe_amount <= 0:
                continue
            if safe_material_key == SKILL_BOOK_KEY:
                legacy_skill_book_cost += safe_amount
                continue
            normalized[safe_material_key] = normalized.get(safe_material_key, 0) + safe_amount

        if legacy_skill_book_cost > 0:
            specific_skill_book_key = self._get_skill_book_key(skill_data)
            normalized[specific_skill_book_key] = (
                normalized.get(specific_skill_book_key, 0) + legacy_skill_book_cost
            )

        return normalized

    def _get_available_world_boss_material_amount(
        self,
        inventory: Dict[str, int],
        material_key: Any,
    ) -> int:
        safe_material_key = str(material_key or "").strip()
        available_amount = max(0, int(inventory.get(safe_material_key, 0) or 0))
        if self._get_skill_book_skill_id(safe_material_key):
            available_amount += max(0, int(inventory.get(SKILL_BOOK_KEY, 0) or 0))
        return available_amount

    def _consume_world_boss_material(
        self,
        inventory: Dict[str, int],
        material_key: Any,
        required_amount: Any,
    ) -> bool:
        safe_material_key = str(material_key or "").strip()
        remaining = max(0, int(required_amount or 0))
        if not safe_material_key or remaining <= 0:
            return True

        available_amount = max(0, int(inventory.get(safe_material_key, 0) or 0))
        consume_amount = min(available_amount, remaining)
        inventory[safe_material_key] = available_amount - consume_amount
        remaining -= consume_amount

        if remaining > 0 and self._get_skill_book_skill_id(safe_material_key):
            legacy_amount = max(0, int(inventory.get(SKILL_BOOK_KEY, 0) or 0))
            legacy_consume = min(legacy_amount, remaining)
            inventory[SKILL_BOOK_KEY] = legacy_amount - legacy_consume
            remaining -= legacy_consume

        return remaining <= 0

    def _sync_skill_progress(self, u: Dict[str, Any]) -> Dict[str, int]:
        raw_skill_levels = u.get("skill_levels")
        if not isinstance(raw_skill_levels, dict):
            raw_skill_levels = {}

        normalized_levels: Dict[str, int] = {}
        for skill_id, raw_level in raw_skill_levels.items():
            safe_skill_id = str(skill_id or "").strip()
            skill = SKILLS.get(safe_skill_id)
            if not safe_skill_id or not isinstance(skill, dict):
                continue
            level = max(0, _safe_int(raw_level, 0))
            if level <= 0:
                continue
            max_level = self._get_skill_max_level(skill)
            if max_level is None:
                normalized_levels[safe_skill_id] = level
                continue
            normalized_levels[safe_skill_id] = min(level, max_level)

        for skill_id, skill in SKILLS.items():
            if not isinstance(skill, dict):
                continue
            if not bool(skill.get("initial_unlocked", False)):
                continue
            normalized_levels[skill_id] = max(1, normalized_levels.get(skill_id, 0))

        raw_selected_slots = u.get("selected_skill_slots")
        if not isinstance(raw_selected_slots, dict):
            raw_selected_slots = {}
        normalized_slots: Dict[str, str] = {}
        for slot_name, selected_skill_id in raw_selected_slots.items():
            safe_slot = str(slot_name or "").strip()
            if safe_slot not in ALL_SKILL_SLOT_NAMES:
                continue
            normalized_slots[safe_slot] = str(selected_skill_id or "").strip()

        legacy_selected_skill_id = str(u.get("selected_active_skill", "") or "").strip()
        if legacy_selected_skill_id and DEFAULT_ACTIVE_SKILL_SLOT not in normalized_slots:
            normalized_slots[DEFAULT_ACTIVE_SKILL_SLOT] = legacy_selected_skill_id

        u["skill_levels"] = normalized_levels
        u["selected_skill_slots"] = normalized_slots
        u["auto_fill_active_skills"] = bool(u.get("auto_fill_active_skills", True))
        u["auto_anchor_passive_skills"] = bool(u.get("auto_anchor_passive_skills", True))
        return normalized_levels

    def get_skill_level(self, u: Dict[str, Any], skill_id: str) -> int:
        skill_levels = self._sync_skill_progress(u)
        return max(0, int(skill_levels.get(str(skill_id or "").strip(), 0)))

    def _get_skill_max_level(self, skill_data: Dict[str, Any]) -> Optional[int]:
        raw_max_level = skill_data.get("max_level")
        if isinstance(raw_max_level, int) and int(raw_max_level) > 0:
            return int(raw_max_level)
        if self._has_infinite_skill_growth(skill_data):
            return None
        return max(1, len(skill_data.get("levels", [])))

    def _get_skill_special_effect_summaries(self, level_data: Optional[Dict[str, Any]]) -> List[str]:
        if not isinstance(level_data, dict):
            return []

        raw_effects = level_data.get("special_effects")
        if not isinstance(raw_effects, list):
            return []

        summaries: List[str] = []
        for raw_effect in raw_effects:
            if not isinstance(raw_effect, dict):
                continue
            summary = str(raw_effect.get("summary", "") or "").strip()
            if summary:
                summaries.append(summary)
                continue
            kind = str(raw_effect.get("kind", "") or "").strip()
            if kind:
                summaries.append(kind)
        return summaries

    def _build_skill_state(
        self,
        skill_data: Dict[str, Any],
        *,
        skill_level: int,
    ) -> Optional[Dict[str, Any]]:
        safe_skill_level = max(0, int(skill_level))
        if safe_skill_level <= 0:
            return None

        current_level_data = self._get_skill_level_data(skill_data, safe_skill_level)
        if not isinstance(current_level_data, dict):
            return None
        next_level_data = self._get_skill_level_data(skill_data, safe_skill_level + 1)
        max_level = self._get_skill_max_level(skill_data)

        state = dict(skill_data)
        state.pop("levels", None)
        current_stats = normalize_stats(current_level_data.get("stats"))
        next_stats = normalize_stats(next_level_data.get("stats", {})) if isinstance(next_level_data, dict) else {}
        state.update(
            {
                "skill_level": safe_skill_level,
                "skill_book_key": self._get_skill_book_key(skill_data),
                "skill_book_label": self._get_skill_book_label(skill_data),
                "max_level": max_level,
                "is_max_level": False if max_level is None else safe_skill_level >= max_level,
                "stats": nonzero_stats(current_stats),
                "atk_bonus": max(0, int(current_stats.get("atk", 0) or 0)),
                "def_bonus": max(0, int(current_stats.get("def", 0) or 0)),
                "speed_bonus": max(0, int(current_stats.get("speed", 0) or 0)),
                "max_hp_bonus": max(0, int(current_stats.get("max_hp", 0) or 0)),
                "duration_turns": max(0, int(current_level_data.get("duration_turns", 0) or 0)),
                "duration_ticks": max(0, int(current_level_data.get("duration_ticks", 0) or 0)),
                "cooldown_actions": max(0, int(current_level_data.get("cooldown_actions", 0) or 0)),
                "attack_multiplier": max(
                    0.0,
                    float(current_level_data.get("attack_multiplier", 1.0) or 1.0),
                ),
                "action_gauge_bonus": max(0, int(current_level_data.get("action_gauge_bonus", 0) or 0)),
                "special_effects": list(current_level_data.get("special_effects", [])),
                "special_effect_summaries": self._get_skill_special_effect_summaries(current_level_data),
                "deals_damage": bool(skill_data.get("deals_damage", skill_data.get("type") == "active")),
                "level_description": str(
                    current_level_data.get("description", state.get("description", "")) or ""
                ).strip(),
                "next_level": safe_skill_level + 1 if next_level_data else None,
                "next_level_description": (
                    str(next_level_data.get("description", "") or "").strip()
                    if isinstance(next_level_data, dict)
                    else ""
                ),
                "next_upgrade_costs": (
                    dict(next_level_data.get("upgrade_costs", {}))
                    if isinstance(next_level_data, dict)
                    else {}
                ),
                "next_special_effects": (
                    list(next_level_data.get("special_effects", []))
                    if isinstance(next_level_data, dict)
                    else []
                ),
                "next_special_effect_summaries": self._get_skill_special_effect_summaries(next_level_data),
                "next_stats": nonzero_stats(next_stats),
            }
        )
        return state

    def _has_infinite_skill_growth(self, skill_data: Dict[str, Any]) -> bool:
        return isinstance(skill_data.get("infinite_growth"), dict)

    def _render_skill_growth_description(
        self,
        skill_data: Dict[str, Any],
        level_data: Dict[str, Any],
    ) -> str:
        growth = skill_data.get("infinite_growth")
        template = str((growth or {}).get("description_template", "") or "").strip()
        if not template:
            return str(skill_data.get("description", "") or "").strip()
        payload = {
            "skill_name": str(skill_data.get("name", "") or "").strip(),
            "level": max(1, int(level_data.get("level", 1) or 1)),
            "atk_bonus": max(0, int(level_data.get("atk_bonus", 0) or 0)),
            "def_bonus": max(0, int(level_data.get("def_bonus", 0) or 0)),
            "speed_bonus": max(0, int(level_data.get("speed_bonus", 0) or 0)),
            "max_hp_bonus": max(0, int(level_data.get("max_hp_bonus", 0) or 0)),
            "duration_turns": max(0, int(level_data.get("duration_turns", 0) or 0)),
            "duration_ticks": max(0, int(level_data.get("duration_ticks", 0) or 0)),
            "cooldown_actions": max(0, int(level_data.get("cooldown_actions", 0) or 0)),
            "attack_multiplier": max(0.0, float(level_data.get("attack_multiplier", 1.0) or 1.0)),
            "action_gauge_bonus": max(0, int(level_data.get("action_gauge_bonus", 0) or 0)),
        }
        try:
            return template.format(**payload).strip()
        except KeyError:
            return str(skill_data.get("description", "") or "").strip()

    def _build_infinite_growth_level_data(
        self,
        skill_data: Dict[str, Any],
        *,
        level: int,
    ) -> Optional[Dict[str, Any]]:
        levels = skill_data.get("levels", [])
        if not isinstance(levels, list) or not levels:
            return None
        growth = skill_data.get("infinite_growth")
        if not isinstance(growth, dict):
            return None

        base_level = len(levels)
        if level <= base_level:
            return dict(levels[level - 1])

        extra_levels = level - base_level
        base_level_data = dict(levels[-1])
        level_data = dict(base_level_data)
        level_data["level"] = level

        for field_name in ("atk_bonus", "def_bonus", "speed_bonus", "max_hp_bonus"):
            base_value = max(0, int(base_level_data.get(field_name, 0) or 0))
            step_value = max(0, int(growth.get(f"{field_name}_step", 0) or 0))
            level_data[field_name] = base_value + (step_value * extra_levels)

        for field_name in ("duration_turns", "duration_ticks"):
            base_value = max(0, int(base_level_data.get(field_name, 0) or 0))
            step_value = max(0, int(growth.get(f"{field_name}_step", 0) or 0))
            every_value = max(1, int(growth.get(f"{field_name}_every", 1) or 1))
            growth_steps = (extra_levels + every_value - 1) // every_value if step_value > 0 else 0
            level_data[field_name] = base_value + (step_value * growth_steps)

        base_cooldown = max(0, int(base_level_data.get("cooldown_actions", 0) or 0))
        cooldown_step = int(growth.get("cooldown_actions_step", 0) or 0)
        cooldown_every = max(1, int(growth.get("cooldown_actions_every", 1) or 1))
        cooldown_steps = (extra_levels + cooldown_every - 1) // cooldown_every if cooldown_step > 0 else 0
        if cooldown_step < 0:
            cooldown_steps = (extra_levels + cooldown_every - 1) // cooldown_every
        level_data["cooldown_actions"] = max(0, base_cooldown + (cooldown_step * cooldown_steps))

        base_attack_multiplier = max(0.0, float(base_level_data.get("attack_multiplier", 1.0) or 1.0))
        attack_multiplier_step = max(0.0, float(growth.get("attack_multiplier_step", 0.0) or 0.0))
        attack_multiplier_every = max(1, int(growth.get("attack_multiplier_every", 1) or 1))
        attack_multiplier_steps = (
            (extra_levels + attack_multiplier_every - 1) // attack_multiplier_every
            if attack_multiplier_step > 0.0
            else 0
        )
        level_data["attack_multiplier"] = base_attack_multiplier + (attack_multiplier_step * attack_multiplier_steps)

        base_action_gauge_bonus = max(0, int(base_level_data.get("action_gauge_bonus", 0) or 0))
        action_gauge_bonus_step = max(0, int(growth.get("action_gauge_bonus_step", 0) or 0))
        action_gauge_bonus_every = max(1, int(growth.get("action_gauge_bonus_every", 1) or 1))
        action_gauge_bonus_steps = (
            (extra_levels + action_gauge_bonus_every - 1) // action_gauge_bonus_every
            if action_gauge_bonus_step > 0
            else 0
        )
        level_data["action_gauge_bonus"] = base_action_gauge_bonus + (
            action_gauge_bonus_step * action_gauge_bonus_steps
        )

        base_upgrade_costs = dict(base_level_data.get("upgrade_costs", {}))
        growth_cost_steps = dict(growth.get("upgrade_cost_steps", {}))
        upgrade_costs: Dict[str, int] = {}
        for material_key in sorted(set(base_upgrade_costs) | set(growth_cost_steps)):
            base_cost = max(0, int(base_upgrade_costs.get(material_key, 0) or 0))
            step_cost = max(0, int(growth_cost_steps.get(material_key, 0) or 0))
            total_cost = base_cost + (step_cost * extra_levels)
            if total_cost > 0:
                upgrade_costs[material_key] = total_cost
        level_data["upgrade_costs"] = self._normalize_skill_upgrade_costs(skill_data, upgrade_costs)
        level_data["stats"] = nonzero_stats(
            {
                "atk": level_data.get("atk_bonus", 0),
                "def": level_data.get("def_bonus", 0),
                "speed": level_data.get("speed_bonus", 0),
                "max_hp": level_data.get("max_hp_bonus", 0),
            }
        )
        level_data["special_effects"] = list(base_level_data.get("special_effects", []))
        level_data["description"] = self._render_skill_growth_description(skill_data, level_data)
        return level_data

    def _get_skill_level_data(
        self,
        skill_data: Dict[str, Any],
        level: int,
    ) -> Optional[Dict[str, Any]]:
        safe_level = max(1, int(level))
        max_level = self._get_skill_max_level(skill_data)
        if max_level is not None and safe_level > max_level:
            return None
        levels = skill_data.get("levels", [])
        if safe_level <= len(levels):
            level_data = dict(levels[safe_level - 1])
            level_data["upgrade_costs"] = self._normalize_skill_upgrade_costs(
                skill_data,
                level_data.get("upgrade_costs", {}),
            )
            return level_data
        return self._build_infinite_growth_level_data(skill_data, level=safe_level)

    def get_skill_state(self, u: Dict[str, Any], skill_id: str) -> Optional[Dict[str, Any]]:
        safe_skill_id = str(skill_id or "").strip()
        skill = SKILLS.get(safe_skill_id)
        if not isinstance(skill, dict):
            return None
        return self._build_skill_state(
            skill,
            skill_level=self.get_skill_level(u, safe_skill_id),
        )

    def get_unlocked_skills(
        self,
        u: Dict[str, Any],
        *,
        skill_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        normalized_type = str(skill_type or "").strip().lower() or None
        unlocked: List[Dict[str, Any]] = []
        for skill in self._iter_sorted_skills():
            if normalized_type and str(skill.get("type", "") or "").strip().lower() != normalized_type:
                continue
            state = self._build_skill_state(
                skill,
                skill_level=self.get_skill_level(u, str(skill.get("skill_id", "") or "").strip()),
            )
            if not isinstance(state, dict):
                continue
            unlocked.append(state)
        return unlocked

    def get_locked_skills(
        self,
        u: Dict[str, Any],
        *,
        skill_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        normalized_type = str(skill_type or "").strip().lower() or None
        locked: List[Dict[str, Any]] = []
        for skill in self._iter_sorted_skills():
            if normalized_type and str(skill.get("type", "") or "").strip().lower() != normalized_type:
                continue
            if self.get_skill_level(u, str(skill.get("skill_id", "") or "").strip()) > 0:
                continue
            locked.append(dict(skill))
        return locked

    def get_unlocked_passive_skills(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.get_unlocked_skills(u, skill_type="passive")

    def get_unlocked_active_skills(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.get_unlocked_skills(u, skill_type="active")

    def get_locked_passive_skills(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.get_locked_skills(u, skill_type="passive")

    def get_locked_active_skills(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.get_locked_skills(u, skill_type="active")

    def _get_skill_slot_names(self, skill_type: str) -> Tuple[str, ...]:
        normalized_type = str(skill_type or "").strip().lower()
        if normalized_type == "passive":
            return PASSIVE_SKILL_SLOT_NAMES
        if normalized_type == "active":
            return ACTIVE_SKILL_SLOT_NAMES
        return tuple()

    def _get_skill_preferred_slot(self, skill: Dict[str, Any], skill_type: str) -> str:
        preferred_slot = str(skill.get("slot", "") or "").strip()
        if preferred_slot in self._get_skill_slot_names(skill_type):
            return preferred_slot
        return ""

    def _sync_selected_skill_loadouts(self, u: Dict[str, Any]) -> Dict[str, str]:
        self._sync_skill_progress(u)
        selected_slots = u.setdefault("selected_skill_slots", {})
        normalized_slots = {
            slot_name: str(selected_slots.get(slot_name, "") or "").strip()
            for slot_name in ALL_SKILL_SLOT_NAMES
        }

        for skill_type in ("passive", "active"):
            slot_names = self._get_skill_slot_names(skill_type)
            owned_skills = self.get_unlocked_skills(u, skill_type=skill_type)
            owned_by_id = {
                str(skill.get("skill_id", "") or "").strip(): dict(skill)
                for skill in owned_skills
                if str(skill.get("skill_id", "") or "").strip()
            }
            selected_ids_in_order: List[str] = []
            for slot_name in slot_names:
                skill_id = normalized_slots.get(slot_name, "")
                if skill_id not in owned_by_id or skill_id in selected_ids_in_order:
                    normalized_slots[slot_name] = ""
                    continue
                selected_ids_in_order.append(skill_id)

            if skill_type == "passive" and bool(u.get("auto_anchor_passive_skills", True)):
                anchored_slots: Dict[str, str] = {}
                anchored_ids: set[str] = set()
                for skill in owned_skills:
                    if not bool(skill.get("initial_unlocked", False)):
                        continue
                    skill_id = str(skill.get("skill_id", "") or "").strip()
                    preferred_slot = self._get_skill_preferred_slot(skill, skill_type)
                    if not skill_id or not preferred_slot or preferred_slot in anchored_slots:
                        continue
                    anchored_slots[preferred_slot] = skill_id
                    anchored_ids.add(skill_id)

                flex_slots = [slot_name for slot_name in slot_names if slot_name not in anchored_slots]
                flex_selected_ids = [
                    skill_id
                    for skill_id in selected_ids_in_order
                    if skill_id not in anchored_ids
                ]
                remaining_flex_ids = [
                    str(skill.get("skill_id", "") or "").strip()
                    for skill in owned_skills
                    if str(skill.get("skill_id", "") or "").strip()
                    and str(skill.get("skill_id", "") or "").strip() not in anchored_ids
                    and str(skill.get("skill_id", "") or "").strip() not in flex_selected_ids
                ]
                flex_queue = flex_selected_ids + remaining_flex_ids
                for slot_name in slot_names:
                    normalized_slots[slot_name] = ""
                for slot_name, skill_id in anchored_slots.items():
                    normalized_slots[slot_name] = skill_id
                for slot_name in flex_slots:
                    if not flex_queue:
                        break
                    normalized_slots[slot_name] = flex_queue.pop(0)
                continue

            used_ids = set(selected_ids_in_order)
            should_autofill = skill_type == "active" and bool(u.get("auto_fill_active_skills", True))
            if should_autofill:
                remaining_skills = [
                    skill
                    for skill in owned_skills
                    if str(skill.get("skill_id", "") or "").strip() not in used_ids
                ]
                for slot_name in slot_names:
                    if normalized_slots.get(slot_name):
                        continue
                    if not remaining_skills:
                        break
                    skill_id = str(remaining_skills.pop(0).get("skill_id", "") or "").strip()
                    if not skill_id:
                        continue
                    normalized_slots[slot_name] = skill_id
                    used_ids.add(skill_id)

        u["selected_skill_slots"] = normalized_slots
        u["selected_active_skill"] = normalized_slots.get(DEFAULT_ACTIVE_SKILL_SLOT, "")
        return normalized_slots

    def _get_selected_skills_by_type(self, u: Dict[str, Any], skill_type: str) -> List[Dict[str, Any]]:
        selected_slots = self._sync_selected_skill_loadouts(u)
        selected_skills: List[Dict[str, Any]] = []
        for slot_name in self._get_skill_slot_names(skill_type):
            skill_id = str(selected_slots.get(slot_name, "") or "").strip()
            if not skill_id:
                continue
            skill_state = self.get_skill_state(u, skill_id)
            if not isinstance(skill_state, dict):
                continue
            selected_skills.append({**skill_state, "slot_name": slot_name})
        return selected_skills

    def get_selected_passive_skills(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._get_selected_skills_by_type(u, "passive")

    def get_selected_active_skills(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self._get_selected_skills_by_type(u, "active")

    def get_passive_skill_bonuses(self, u: Dict[str, Any]) -> Dict[str, int]:
        return merge_stats(*(skill.get("stats", {}) for skill in self.get_selected_passive_skills(u)))

    def get_world_boss_material_inventory(self, u: Dict[str, Any]) -> Dict[str, int]:
        materials = u.get("world_boss_materials")
        if not isinstance(materials, dict):
            materials = {}
            u["world_boss_materials"] = materials

        normalized: Dict[str, int] = {}
        for material_key, amount in materials.items():
            safe_material_key = str(material_key or "").strip()
            if not safe_material_key:
                continue
            normalized[safe_material_key] = max(0, _safe_int(amount, 0))
        u["world_boss_materials"] = normalized
        return normalized

    def get_world_boss_material_label(self, material_key: str) -> str:
        safe_material_key = str(material_key or "").strip()
        skill_id = self._get_skill_book_skill_id(safe_material_key)
        if skill_id:
            return self._get_skill_book_label(skill_id)
        if safe_material_key == SKILL_BOOK_KEY:
            return SKILL_BOOK_LABEL
        for boss in WORLD_BOSSES.values():
            if str(boss.get("material_key", "") or "").strip() != safe_material_key:
                continue
            label = str(boss.get("material_label", "") or "").strip()
            if label:
                return label
        return safe_material_key

    def get_world_boss_shop_catalog(self, u: Dict[str, Any]) -> Dict[str, Any]:
        inventory = self.get_world_boss_material_inventory(u)
        recipes: List[Dict[str, Any]] = []
        seen_material_keys: set[str] = set()
        skill_book_targets = [
            {
                "skill_id": str(skill.get("skill_id", "") or "").strip(),
                "skill_name": str(skill.get("name", "スキル") or "スキル").strip() or "スキル",
                "skill_book_key": self._get_skill_book_key(skill),
                "skill_book_label": self._get_skill_book_label(skill),
                "current_amount": max(0, int(inventory.get(self._get_skill_book_key(skill), 0) or 0)),
            }
            for skill in self._iter_sorted_skills()
        ]
        ordered_bosses = sorted(
            WORLD_BOSSES.values(),
            key=lambda boss: (
                max(0, int(boss.get("skill_book_exchange_cost", 0) or 0)) <= 0,
                max(0, int(boss.get("skill_book_exchange_cost", 0) or 0)),
                str(boss.get("name", "") or ""),
            ),
        )
        for boss in ordered_bosses:
            material_key = str(boss.get("material_key", "") or "").strip()
            if not material_key or material_key in seen_material_keys:
                continue
            seen_material_keys.add(material_key)
            exchange_cost = max(0, int(boss.get("skill_book_exchange_cost", 0) or 0))
            if exchange_cost <= 0:
                continue
            current_amount = max(0, int(inventory.get(material_key, 0) or 0))
            recipes.append(
                {
                    "material_key": material_key,
                    "material_label": self.get_world_boss_material_label(material_key),
                    "boss_name": str(boss.get("name", "") or "").strip(),
                    "cost": exchange_cost,
                    "current_amount": current_amount,
                    "purchasable": current_amount // exchange_cost,
                }
            )
        return {
            "skill_book_key": SKILL_BOOK_KEY,
            "skill_book_label": "指定スキルの書",
            "skill_book_amount": max(0, int(inventory.get(SKILL_BOOK_KEY, 0) or 0))
            + sum(max(0, int(entry.get("current_amount", 0) or 0)) for entry in skill_book_targets),
            "legacy_skill_book_key": SKILL_BOOK_KEY,
            "legacy_skill_book_label": SKILL_BOOK_LABEL,
            "legacy_skill_book_amount": max(0, int(inventory.get(SKILL_BOOK_KEY, 0) or 0)),
            "skill_book_targets": skill_book_targets,
            "recipes": recipes,
        }

    def exchange_world_boss_skill_books(
        self,
        u: Dict[str, Any],
        item_query: Optional[str],
        quantity: Optional[int] = None,
    ) -> Tuple[bool, str]:
        if not str(item_query or "").strip():
            return False, "交換先のスキル名を指定してください。 `!wb 交換 闘気` / `!wb 交換 闘気 2`"
        if quantity is not None and int(quantity) <= 0:
            return False, "交換冊数は1以上で指定してください。 `!wb 交換 闘気 2`"

        target_skill = self._resolve_skill_definition(item_query)
        if not isinstance(target_skill, dict):
            return False, "交換先のスキル名が見つかりません。 `!wb 交換 闘気` / `!wb 交換 闘気 2`"
        target_skill_book_key = self._get_skill_book_key(target_skill)
        target_skill_book_label = self._get_skill_book_label(target_skill)

        shop = self.get_world_boss_shop_catalog(u)
        inventory = self.get_world_boss_material_inventory(u)
        recipes = [recipe for recipe in shop.get("recipes", []) if int(recipe.get("purchasable", 0) or 0) > 0]
        requested_quantity = max(0, int(quantity or 0)) if quantity is not None else None
        if not recipes:
            recipe_notes = [
                f"{recipe['material_label']} {int(recipe['current_amount'])}/{int(recipe['cost'])}"
                for recipe in shop.get("recipes", [])
            ]
            if recipe_notes:
                return False, f"{target_skill_book_label}に交換できる素材が足りません。 " + " / ".join(recipe_notes)
            return False, "交換できるWB素材がありません。"

        total_purchasable = sum(max(0, int(recipe.get("purchasable", 0) or 0)) for recipe in recipes)
        if requested_quantity is not None and total_purchasable < requested_quantity:
            recipe_notes = [
                f"{recipe['material_label']} {int(recipe['current_amount'])}/{int(recipe['cost'])}"
                for recipe in shop.get("recipes", [])
            ]
            return False, (
                f"{target_skill_book_label}は {requested_quantity} 冊ぶん交換できません。 "
                f"交換可能 {total_purchasable} 冊"
                + (f" / {' / '.join(recipe_notes)}" if recipe_notes else "")
            )

        acquired = 0
        spent_parts: List[str] = []
        remaining_quantity = requested_quantity
        for recipe in recipes:
            purchasable = max(0, int(recipe.get("purchasable", 0) or 0))
            if purchasable <= 0:
                continue
            if remaining_quantity is not None:
                purchasable = min(purchasable, remaining_quantity)
                if purchasable <= 0:
                    break
            material_key = str(recipe.get("material_key", "") or "").strip()
            exchange_cost = max(1, int(recipe.get("cost", 1) or 1))
            spent_amount = purchasable * exchange_cost
            inventory[material_key] = max(0, int(inventory.get(material_key, 0) or 0) - spent_amount)
            acquired += purchasable
            spent_parts.append(f"{recipe['material_label']}x{spent_amount}")
            if remaining_quantity is not None:
                remaining_quantity -= purchasable
                if remaining_quantity <= 0:
                    break

        inventory[target_skill_book_key] = max(0, int(inventory.get(target_skill_book_key, 0) or 0)) + acquired
        return True, (
            f"{target_skill_book_label}を {acquired} 冊交換しました。 "
            f"消費 {' / '.join(spent_parts)} / 所持 {target_skill_book_label}x"
            f"{int(inventory.get(target_skill_book_key, 0) or 0)}"
        )

    def get_selected_active_skill(self, u: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        active_skills = self.get_selected_active_skills(u)
        return dict(active_skills[0]) if active_skills else None

    def format_selected_skill_slots(self, u: Dict[str, Any], skill_type: str) -> str:
        return self._format_selected_skill_slots(u, skill_type)

    def _format_selected_skill_slots(self, u: Dict[str, Any], skill_type: str) -> str:
        selected_slots = self._sync_selected_skill_loadouts(u)
        parts: List[str] = []
        for index, slot_name in enumerate(self._get_skill_slot_names(skill_type), start=1):
            skill_id = str(selected_slots.get(slot_name, "") or "").strip()
            skill_name = "なし"
            if skill_id:
                skill_state = self.get_skill_state(u, skill_id)
                if isinstance(skill_state, dict):
                    skill_label = str(skill_state.get("name", skill_name) or skill_name).strip() or skill_name
                    skill_level = max(1, int(skill_state.get("skill_level", 1) or 1))
                    skill_name = f"{skill_label} Lv{skill_level}"
            parts.append(f"{index}:{skill_name}")
        return " / ".join(parts) if parts else "なし"

    def set_selected_skill_loadout(
        self,
        u: Dict[str, Any],
        skill_type: str,
        slot_queries: Dict[int, str],
    ) -> Tuple[bool, str]:
        normalized_type = str(skill_type or "").strip().lower()
        slot_names = self._get_skill_slot_names(normalized_type)
        if normalized_type not in {"passive", "active"} or not slot_names:
            return False, "変更するスキル種別が不正です。"
        if not isinstance(slot_queries, dict) or not slot_queries:
            return False, "変更するスロット番号とスキル名を指定してください。"

        type_label = "パッシブ" if normalized_type == "passive" else "アクティブ"
        clear_queries = {"なし", "解除", "off", "none", "clear"}
        current_slots = self._sync_selected_skill_loadouts(u)
        next_slot_ids = {
            slot_name: str(current_slots.get(slot_name, "") or "").strip()
            for slot_name in slot_names
        }

        for raw_slot_index, raw_query in sorted(slot_queries.items()):
            safe_slot_index = _safe_int(raw_slot_index, 0)
            if safe_slot_index <= 0 or safe_slot_index > len(slot_names):
                return False, f"{type_label}{safe_slot_index} は存在しません。1-{len(slot_names)} を指定してください。"

            query = str(raw_query or "").strip()
            if not query:
                return False, f"{type_label}{safe_slot_index} のスキル名を指定してください。"

            if self._normalize_skill_query(query) in clear_queries:
                next_slot_ids[slot_names[safe_slot_index - 1]] = ""
                continue

            resolved_skill = self._resolve_owned_skill(u, query, skill_type=normalized_type)
            if isinstance(resolved_skill, dict):
                next_slot_ids[slot_names[safe_slot_index - 1]] = str(
                    resolved_skill.get("skill_id", "") or ""
                ).strip()
                continue

            skill_definition = self._resolve_skill_definition(query)
            if isinstance(skill_definition, dict):
                resolved_type = str(skill_definition.get("type", "") or "").strip().lower()
                skill_name = str(skill_definition.get("name", "スキル") or "スキル").strip() or "スキル"
                if resolved_type != normalized_type:
                    other_label = "パッシブ" if resolved_type == "passive" else "アクティブ"
                    return False, f"{skill_name} は{other_label}スキルです。"
                return False, f"{skill_name} はまだ所持していません。"

            return False, f"{type_label}{safe_slot_index} のスキルが見つかりません。"

        used_slots: Dict[str, int] = {}
        for index, slot_name in enumerate(slot_names, start=1):
            skill_id = str(next_slot_ids.get(slot_name, "") or "").strip()
            if not skill_id:
                continue
            if skill_id in used_slots:
                skill_state = self.get_skill_state(u, skill_id)
                skill_name = (
                    str(skill_state.get("name", "スキル") or "スキル").strip()
                    if isinstance(skill_state, dict)
                    else "スキル"
                ) or "スキル"
                return False, (
                    f"{type_label}{used_slots[skill_id]} と {type_label}{index} に "
                    f"同じスキル {skill_name} は設定できません。"
                )
            used_slots[skill_id] = index

        selected_slots = u.setdefault("selected_skill_slots", {})
        for slot_name in slot_names:
            selected_slots[slot_name] = next_slot_ids.get(slot_name, "")

        if normalized_type == "active":
            u["auto_fill_active_skills"] = False
        else:
            u["auto_anchor_passive_skills"] = False

        self._sync_selected_skill_loadouts(u)
        return True, f"{type_label}構成を変更しました。 {self._format_selected_skill_slots(u, normalized_type)}"

    def get_next_locked_skill(self, u: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        locked = self.get_locked_skills(u)
        if not locked:
            return None
        return dict(locked[0])

    def _resolve_skill_definition(
        self,
        skill_query: Optional[str],
        *,
        skill_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        query = self._normalize_skill_query(skill_query)
        if not query:
            return None
        normalized_type = str(skill_type or "").strip().lower() or None
        for skill in self._iter_sorted_skills():
            if normalized_type and str(skill.get("type", "") or "").strip().lower() != normalized_type:
                continue
            candidates = self._build_skill_query_candidates(skill)
            if query in candidates:
                return dict(skill)
        return None

    def _resolve_owned_skill(
        self,
        u: Dict[str, Any],
        skill_query: Optional[str],
        *,
        skill_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        query = self._normalize_skill_query(skill_query)
        owned_skills = self.get_unlocked_skills(u, skill_type=skill_type)
        if not query:
            if skill_type in (None, "active"):
                selected_active = self.get_selected_active_skill(u)
                if isinstance(selected_active, dict):
                    return selected_active
            if skill_type == "passive":
                selected_passives = self.get_selected_passive_skills(u)
                if len(selected_passives) == 1:
                    return dict(selected_passives[0])
            if len(owned_skills) == 1:
                return dict(owned_skills[0])
            return None

        for skill in owned_skills:
            candidates = self._build_skill_query_candidates(skill)
            if query in candidates:
                return dict(skill)
        return None

    def _format_skill_upgrade_costs(
        self,
        u: Dict[str, Any],
        costs: Dict[str, int],
    ) -> str:
        if not isinstance(costs, dict) or not costs:
            return "不要"

        inventory = self.get_world_boss_material_inventory(u)
        parts: List[str] = []
        for material_key, required_amount in sorted(costs.items()):
            safe_required_amount = max(0, int(required_amount))
            current_amount = self._get_available_world_boss_material_amount(inventory, material_key)
            parts.append(
                f"{self.get_world_boss_material_label(material_key)} {current_amount}/{safe_required_amount}"
            )
        return " / ".join(parts) if parts else "不要"

    def set_selected_active_skill(
        self,
        u: Dict[str, Any],
        skill_query: Optional[str],
    ) -> Tuple[bool, str]:
        query = self._normalize_skill_query(skill_query)
        if not query:
            return False, "切り替えるアクティブスキル名を指定してください。"

        if query in {"なし", "解除", "off", "none", "clear"}:
            selected_slots = u.setdefault("selected_skill_slots", {})
            for slot_name in ACTIVE_SKILL_SLOT_NAMES:
                selected_slots[slot_name] = ""
            u["auto_fill_active_skills"] = False
            u["selected_active_skill"] = ""
            return True, "アクティブスキルの自動使用を解除しました。"

        resolved_skill = self._resolve_owned_skill(u, skill_query, skill_type="active")
        if isinstance(resolved_skill, dict):
            skill_id = str(resolved_skill.get("skill_id", "") or "").strip()
            selected_slots = u.setdefault("selected_skill_slots", {})
            existing_order = [
                str(selected_slots.get(slot_name, "") or "").strip()
                for slot_name in ACTIVE_SKILL_SLOT_NAMES
                if str(selected_slots.get(slot_name, "") or "").strip()
            ]
            next_order = [skill_id] + [
                existing_skill_id
                for existing_skill_id in existing_order
                if existing_skill_id and existing_skill_id != skill_id
            ]
            owned_active_ids = {
                str(skill.get("skill_id", "") or "").strip()
                for skill in self.get_unlocked_active_skills(u)
                if str(skill.get("skill_id", "") or "").strip()
            }
            for owned_skill in self.get_unlocked_active_skills(u):
                owned_skill_id = str(owned_skill.get("skill_id", "") or "").strip()
                if owned_skill_id and owned_skill_id not in next_order:
                    next_order.append(owned_skill_id)
            next_order = [
                owned_skill_id
                for owned_skill_id in next_order
                if owned_skill_id in owned_active_ids
            ][: len(ACTIVE_SKILL_SLOT_NAMES)]
            selected_slots = u.setdefault("selected_skill_slots", {})
            for index, slot_name in enumerate(ACTIVE_SKILL_SLOT_NAMES):
                selected_slots[slot_name] = next_order[index] if index < len(next_order) else ""
            u["auto_fill_active_skills"] = True
            self._sync_selected_skill_loadouts(u)
            return True, f"アクティブ優先1を {resolved_skill['name']} に変更しました。"

        for skill in self._iter_sorted_skills():
            if str(skill.get("type", "") or "").strip().lower() != "active":
                continue
            candidates = self._build_skill_query_candidates(skill)
            if query in candidates:
                return False, f"{skill['name']} はまだ所持していません。"

        for skill in self._iter_sorted_skills():
            if str(skill.get("type", "") or "").strip().lower() != "passive":
                continue
            candidates = self._build_skill_query_candidates(skill)
            if query in candidates:
                return False, f"{skill['name']} はパッシブスキルです。`!スキル` で確認してください。"

        return False, "該当するアクティブスキルが見つかりません。"

    def set_selected_passive_skill(
        self,
        u: Dict[str, Any],
        skill_query: Optional[str],
    ) -> Tuple[bool, str]:
        query = self._normalize_skill_query(skill_query)
        if not query:
            return False, "切り替えるパッシブスキル名を指定してください。"

        resolved_skill = self._resolve_owned_skill(u, skill_query, skill_type="passive")
        if isinstance(resolved_skill, dict):
            skill_id = str(resolved_skill.get("skill_id", "") or "").strip()
            owned_passives = self.get_unlocked_passive_skills(u)
            selected_slots = u.setdefault("selected_skill_slots", {})
            anchored_slots: Dict[str, str] = {}
            anchored_ids: set[str] = set()
            for owned_skill in owned_passives:
                if not bool(owned_skill.get("initial_unlocked", False)):
                    continue
                owned_skill_id = str(owned_skill.get("skill_id", "") or "").strip()
                preferred_slot = self._get_skill_preferred_slot(owned_skill, "passive")
                if not owned_skill_id or not preferred_slot or preferred_slot in anchored_slots:
                    continue
                anchored_slots[preferred_slot] = owned_skill_id
                anchored_ids.add(owned_skill_id)

            flex_slots = [slot_name for slot_name in PASSIVE_SKILL_SLOT_NAMES if slot_name not in anchored_slots]
            if not flex_slots and skill_id not in anchored_ids:
                return False, "現在は切り替え可能なパッシブ枠がありません。"

            current_flex_order = [
                str(selected_slots.get(slot_name, "") or "").strip()
                for slot_name in PASSIVE_SKILL_SLOT_NAMES
                if str(selected_slots.get(slot_name, "") or "").strip()
                and str(selected_slots.get(slot_name, "") or "").strip() not in anchored_ids
            ]
            next_flex_order = [skill_id] + [
                existing_skill_id
                for existing_skill_id in current_flex_order
                if existing_skill_id and existing_skill_id != skill_id
            ]
            owned_flex_ids = [
                str(owned_skill.get("skill_id", "") or "").strip()
                for owned_skill in owned_passives
                if str(owned_skill.get("skill_id", "") or "").strip()
                and str(owned_skill.get("skill_id", "") or "").strip() not in anchored_ids
            ]
            for owned_skill_id in owned_flex_ids:
                if owned_skill_id not in next_flex_order:
                    next_flex_order.append(owned_skill_id)

            for slot_name in PASSIVE_SKILL_SLOT_NAMES:
                selected_slots[slot_name] = anchored_slots.get(slot_name, "")
            for index, slot_name in enumerate(flex_slots):
                selected_slots[slot_name] = next_flex_order[index] if index < len(next_flex_order) else ""
            u["auto_anchor_passive_skills"] = True
            self._sync_selected_skill_loadouts(u)
            return True, f"パッシブ枠に {resolved_skill['name']} を設定しました。"

        for skill in self._iter_sorted_skills():
            candidates = self._build_skill_query_candidates(skill)
            if query not in candidates:
                continue
            if str(skill.get("type", "") or "").strip().lower() == "passive":
                return False, f"{skill['name']} はまだ所持していません。"
            return False, f"{skill['name']} はアクティブスキルです。`!スキル変更 アクティブ {skill['name']}` を使ってください。"

        return False, "該当するパッシブスキルが見つかりません。"

    def upgrade_skill(
        self,
        u: Dict[str, Any],
        skill_query: Optional[str],
    ) -> Tuple[bool, str]:
        skill = self._resolve_owned_skill(u, skill_query)
        inventory = self.get_world_boss_material_inventory(u)
        skill_levels = self._sync_skill_progress(u)
        if isinstance(skill, dict):
            if bool(skill.get("is_max_level", False)):
                return False, f"{skill['name']} はすでに最大Lvです。"
            skill_id = str(skill.get("skill_id", "") or "").strip()
            current_skill: Optional[Dict[str, Any]] = dict(skill)
            starting_level = max(0, int(skill.get("skill_level", 0) or 0))
        else:
            if not str(skill_query or "").strip():
                return False, "強化するスキル名を指定してください。"
            skill_definition = self._resolve_skill_definition(skill_query)
            if not isinstance(skill_definition, dict):
                return False, "強化できるスキルが見つかりません。"
            skill_id = str(skill_definition.get("skill_id", "") or "").strip()
            first_level_data = self._get_skill_level_data(skill_definition, 1)
            if not isinstance(first_level_data, dict):
                return False, "スキル強化先の状態を取得できませんでした。"
            starting_level = 0
            current_skill = {
                "skill_id": skill_id,
                "name": str(skill_definition.get("name", "スキル") or "スキル").strip() or "スキル",
                "skill_level": 0,
                "is_max_level": False,
                "next_upgrade_costs": dict(first_level_data.get("upgrade_costs", {})),
            }
        upgrade_count = 0

        while isinstance(current_skill, dict) and not bool(current_skill.get("is_max_level", False)):
            next_upgrade_costs = dict(current_skill.get("next_upgrade_costs", {}))
            missing_costs = {
                material_key: required_amount
                for material_key, required_amount in next_upgrade_costs.items()
                if self._get_available_world_boss_material_amount(inventory, material_key)
                < max(0, int(required_amount))
            }
            if missing_costs:
                if upgrade_count <= 0:
                    return False, (
                        f"{current_skill['name']} の強化素材が不足しています。 "
                        f"{self._format_skill_upgrade_costs(u, next_upgrade_costs)}"
                    )
                break

            for material_key, required_amount in next_upgrade_costs.items():
                self._consume_world_boss_material(inventory, material_key, required_amount)

            skill_levels[skill_id] = max(0, int(current_skill.get("skill_level", 0))) + 1
            u["skill_levels"] = skill_levels
            upgrade_count += 1
            current_skill = self.get_skill_state(u, skill_id)

        self.sync_level_stats(u)
        upgraded_skill = self.get_skill_state(u, skill_id)
        if not isinstance(upgraded_skill, dict):
            return False, "スキル強化後の状態を取得できませんでした。"
        self._sync_selected_skill_loadouts(u)
        if starting_level <= 0 and upgrade_count == 1:
            return True, (
                f"{upgraded_skill['name']} を解放しました。 "
                f"{upgraded_skill.get('level_description', self._format_skill_upgrade_costs(u, {}))}"
            )
        if starting_level <= 0 and upgrade_count > 1:
            return True, (
                f"{upgraded_skill['name']} を解放して Lv{int(upgraded_skill['skill_level'])} まで強化しました。 "
                f"{upgrade_count}段階強化 / "
                f"{upgraded_skill.get('level_description', self._format_skill_upgrade_costs(u, {}))}"
            )
        if upgrade_count == 1:
            return True, (
                f"{upgraded_skill['name']} を Lv{int(upgraded_skill['skill_level'])} に強化しました。 "
                f"{upgraded_skill.get('level_description', self._format_skill_upgrade_costs(u, {}))}"
            )
        return True, (
            f"{upgraded_skill['name']} を Lv{int(upgraded_skill['skill_level'])} まで強化しました。 "
            f"{upgrade_count}段階強化 / "
            f"{upgraded_skill.get('level_description', self._format_skill_upgrade_costs(u, {}))}"
        )

    def get_feature_effect_summaries(self, u: Dict[str, Any]) -> List[str]:
        effects: List[str] = []
        for feature_key in ("enchanting", "rare_hunt", "weapon_forge", "survival_guard"):
            if not self.is_feature_unlocked(u, feature_key):
                continue
            summary = str(FEATURE_EFFECT_SUMMARIES.get(feature_key, "") or "").strip()
            if summary:
                effects.append(summary)

        auto_repeat_progress = self.get_auto_repeat_progress(u)
        if auto_repeat_progress["unlocked"]:
            effects.append("自動周回解放")
        elif auto_repeat_progress["route_unlocked"] or auto_repeat_progress["fragments"] > 0:
            effects.append(
                f"自動周回 欠片{auto_repeat_progress['fragments']}/{auto_repeat_progress['required_fragments']}"
            )
        return effects

    def sync_level_stats(self, u: Dict[str, Any]) -> None:
        self._sync_level_stats(u)

    def get_unlocked_slots(self, u: Dict[str, Any]) -> Dict[str, bool]:
        slot_unlocks = u.setdefault("slot_unlocks", {})
        return {
            slot_name: bool(slot_unlocks.get(slot_name, slot_name == "weapon"))
            for slot_name in self._get_slot_order()
        }

    def is_slot_unlocked(self, u: Dict[str, Any], slot: str) -> bool:
        return bool(self.get_unlocked_slots(u).get(slot, False))

    def unlock_slots(self, u: Dict[str, Any], slots: Tuple[str, ...] | list[str]) -> list[str]:
        slot_unlocks = u.setdefault("slot_unlocks", {})
        newly_unlocked: list[str] = []

        for slot_name in slots:
            if slot_name not in SLOT_LABEL:
                continue
            if bool(slot_unlocks.get(slot_name, slot_name == "weapon")):
                continue
            slot_unlocks[slot_name] = True
            newly_unlocked.append(slot_name)

        return newly_unlocked

    def claim_area_first_clear_rewards(self, u: Dict[str, Any], area_name: str) -> Dict[str, Any]:
        safe_area_name = str(area_name or "").strip()
        empty_result = {
            "newly_unlocked_slots": [],
            "newly_unlocked_features": [],
            "granted_auto_explore_fragments": 0,
            "reward_summaries": [],
        }
        if safe_area_name not in AREAS:
            return empty_result

        claimed_reward_areas = u.setdefault("claimed_first_clear_reward_areas", [])
        if safe_area_name in claimed_reward_areas:
            return empty_result

        rewards = self._get_area_first_clear_rewards(safe_area_name)
        newly_unlocked_slots = self.unlock_slots(u, rewards["unlock_slots"])
        auto_repeat_unlocked_before = self.is_auto_repeat_unlocked(u)

        feature_unlocks = u.setdefault("feature_unlocks", {})
        newly_unlocked_features: List[str] = []
        for feature_key in rewards["unlock_features"]:
            if bool(feature_unlocks.get(feature_key, False)):
                continue
            feature_unlocks[feature_key] = True
            newly_unlocked_features.append(feature_key)

        granted_auto_explore_fragments = max(0, int(rewards.get("auto_explore_fragments", 0)))
        if granted_auto_explore_fragments > 0:
            u["auto_explore_fragments"] = max(0, int(u.get("auto_explore_fragments", 0))) + granted_auto_explore_fragments

        self._sync_feature_unlocks(u)
        if not auto_repeat_unlocked_before and self.is_auto_repeat_unlocked(u):
            newly_unlocked_features.append("auto_repeat")

        claimed_reward_areas.append(safe_area_name)
        return {
            "newly_unlocked_slots": newly_unlocked_slots,
            "newly_unlocked_features": newly_unlocked_features,
            "granted_auto_explore_fragments": granted_auto_explore_fragments,
            "reward_summaries": self._build_first_clear_reward_summaries(
                rewards,
                newly_unlocked_slots=newly_unlocked_slots,
                newly_unlocked_features=newly_unlocked_features,
                granted_auto_explore_fragments=granted_auto_explore_fragments,
            ),
        }

    def register_boss_clear(self, u: Dict[str, Any], area_name: str) -> bool:
        safe_area = str(area_name or "").strip()
        if safe_area not in AREAS:
            return False

        boss_clear_areas = u.setdefault("boss_clear_areas", [])
        if safe_area in boss_clear_areas:
            return False

        boss_clear_areas.append(safe_area)
        return True

    def assign_item_id(self, u: Dict[str, Any], item: Dict[str, Any]) -> str:
        self._sanitize_item(item)
        reserved_ids = {
            str(existing.get("item_id"))
            for existing in self._iter_user_items(u)
            if isinstance(existing, dict) and existing is not item and str(existing.get("item_id", "") or "").strip()
        }
        current_item_id = str(item.get("item_id", "") or "").strip()
        if current_item_id and current_item_id not in reserved_ids:
            item["item_id"] = current_item_id
            self._update_next_item_id_from_value(u, current_item_id)
            return current_item_id

        new_item_id = self._generate_item_id(u, reserved_ids)
        item["item_id"] = new_item_id
        return new_item_id

    def is_item_protected(self, u: Dict[str, Any], item_or_id: Any) -> bool:
        if isinstance(item_or_id, dict):
            item_id = str(item_or_id.get("item_id", "") or "").strip()
        else:
            item_id = str(item_or_id or "").strip()
        if not item_id:
            return False
        return item_id in set(u.get("protected_item_ids", []))

    def set_item_protection(self, u: Dict[str, Any], item_id: str, protected: bool) -> bool:
        safe_item_id = str(item_id or "").strip()
        if not safe_item_id:
            return False

        valid_item_ids = {
            str(item.get("item_id"))
            for item in self._iter_user_items(u)
            if str(item.get("item_id", "") or "").strip()
        }
        if safe_item_id not in valid_item_ids:
            return False

        protected_item_ids = list(u.setdefault("protected_item_ids", []))
        is_protected = safe_item_id in protected_item_ids
        if protected:
            if is_protected:
                return False
            protected_item_ids.append(safe_item_id)
            u["protected_item_ids"] = protected_item_ids
            return True

        if not is_protected:
            return False
        u["protected_item_ids"] = [existing for existing in protected_item_ids if existing != safe_item_id]
        return True

    def _get_equipped_item_for_slot(self, u: Dict[str, Any], slot: str) -> Optional[Dict[str, Any]]:
        if not self.is_slot_unlocked(u, slot):
            return None

        item = u.get("equipped", {}).get(slot)
        return item if isinstance(item, dict) else None

    def get_level_exp(self, u: Dict[str, Any]) -> int:
        adventure_exp = int(u.get("adventure_exp", 0))
        chat_exp = int(u.get("chat_exp", 0))
        weighted_chat_exp = int(chat_exp * CHAT_EXP_RPG_WEIGHT)
        return max(0, adventure_exp + weighted_chat_exp)

    def get_exp_to_next_level(self, level: int) -> int:
        level = max(1, int(level))

        if level < LEVEL_EARLY_END:
            return LEVEL_EARLY_EXP_BASE + ((level - 1) * LEVEL_EARLY_EXP_STEP)

        if level < LEVEL_MID_END:
            return LEVEL_MID_EXP_BASE + ((level - LEVEL_EARLY_END) * LEVEL_MID_EXP_STEP)

        late_index = level - LEVEL_MID_END
        return (
            LEVEL_LATE_EXP_BASE
            + (late_index * LEVEL_LATE_EXP_STEP)
            + (late_index * late_index * LEVEL_LATE_EXP_ACCELERATION)
        )

    def get_adventure_level(self, u: Dict[str, Any]) -> int:
        exp = self.get_level_exp(u)
        level = 1

        while True:
            required_exp = self.get_exp_to_next_level(level)
            if exp < required_exp:
                break
            exp -= required_exp
            level += 1

        return level

    def get_max_hp_by_level(self, level: int) -> int:
        return DEFAULT_MAX_HP + (max(1, level) - 1) * 8

    def get_equipped_item_power(self, u: Dict[str, Any], slot: str) -> int:
        item = self._get_equipped_item_for_slot(u, slot)
        if not item:
            return 0
        return int(item.get("power", 0))

    def get_equipped_item_stats(self, u: Dict[str, Any], slot: str) -> Dict[str, int]:
        item = self._get_equipped_item_for_slot(u, slot)
        if not item:
            return {}
        self._sanitize_item(item)
        return dict(item.get("stats", {}))

    def get_total_equipment_stats(self, u: Dict[str, Any]) -> Dict[str, int]:
        return merge_stats(
            *(self.get_equipped_item_stats(u, slot_name) for slot_name in self._get_slot_order())
        )

    def get_weapon_power(self, u: Dict[str, Any]) -> int:
        return self.get_equipped_item_power(u, "weapon")

    def get_armor_power(self, u: Dict[str, Any]) -> int:
        return self.get_equipped_item_power(u, "armor")

    def get_ring_power(self, u: Dict[str, Any]) -> int:
        return self.get_equipped_item_power(u, "ring")

    def get_shoes_power(self, u: Dict[str, Any]) -> int:
        return self.get_equipped_item_power(u, "shoes")

    def get_item_enchant_key(self, item: Optional[Dict[str, Any]]) -> Optional[str]:
        if not item:
            return None
        enchant_key = str(item.get("enchant", "") or "").strip()
        if enchant_key in ENCHANTMENT_EFFECT_LABELS:
            return enchant_key
        return None

    def get_item_enchant_label(self, item: Optional[Dict[str, Any]]) -> str:
        enchant_key = self.get_item_enchant_key(item)
        if not enchant_key:
            return ""
        return ENCHANTMENT_EFFECT_LABELS.get(enchant_key, "")

    def get_equipped_item_enchant_label(self, u: Dict[str, Any], slot: str) -> str:
        item = self._get_equipped_item_for_slot(u, slot)
        return self.get_item_enchant_label(item)

    def has_ring_exploration_enchant(self, u: Dict[str, Any]) -> bool:
        return self.get_item_enchant_key(self._get_equipped_item_for_slot(u, "ring")) == "ring"

    def has_weapon_crit_enchant(self, u: Dict[str, Any]) -> bool:
        return self.get_item_enchant_key(self._get_equipped_item_for_slot(u, "weapon")) == "weapon"

    def get_weapon_crit_stats(self, u: Dict[str, Any]) -> Tuple[float, float]:
        if not self.has_weapon_crit_enchant(u):
            return 0.0, 1.0

        weapon_item = self._get_equipped_item_for_slot(u, "weapon")
        enhance_level = max(0, int((weapon_item or {}).get("enhance", 0)))
        crit_rate = float(ENCHANTMENT_WEAPON_CRIT_RATE) + (
            enhance_level * float(ENCHANTMENT_WEAPON_CRIT_RATE_PER_ENHANCE)
        )
        return (
            min(1.0, max(0.0, crit_rate)),
            max(1.0, float(ENCHANTMENT_WEAPON_CRIT_DAMAGE_MULTIPLIER)),
        )

    def get_weapon_crit_bonus_text(self, u: Dict[str, Any]) -> str:
        crit_rate, crit_multiplier = self.get_weapon_crit_stats(u)
        if crit_rate <= 0.0 or crit_multiplier <= 1.0:
            return ""

        crit_pct = int(round(crit_rate * 100))
        crit_damage_pct = int(round((crit_multiplier - 1.0) * 100))
        return f"クリ率+{crit_pct}% 会心威力+{crit_damage_pct}%"

    def get_ring_exploration_bonus_text(self, u: Dict[str, Any]) -> str:
        exp_rate, gold_rate, drop_bonus = self.get_ring_exploration_rates(u)
        if exp_rate <= 1.0 and gold_rate <= 1.0 and drop_bonus <= 0.0:
            return ""
        exp_pct = int(round((exp_rate - 1.0) * 100))
        gold_pct = int(round((gold_rate - 1.0) * 100))
        drop_pct = int(round(drop_bonus * 100))
        return f"探索EXP+{exp_pct}% Gold+{gold_pct}% Drop+{drop_pct}%"

    def get_ring_exploration_rates(self, u: Dict[str, Any]) -> Tuple[float, float, float]:
        if not self.has_ring_exploration_enchant(u):
            return 1.0, 1.0, 0.0

        ring_item = self._get_equipped_item_for_slot(u, "ring")
        enhance_level = max(0, int((ring_item or {}).get("enhance", 0)))
        return (
            max(
                0.0,
                float(ENCHANTMENT_RING_EXP_RATE) + (enhance_level * float(ENCHANTMENT_RING_EXP_RATE_PER_ENHANCE)),
            ),
            max(
                0.0,
                float(ENCHANTMENT_RING_GOLD_RATE)
                + (enhance_level * float(ENCHANTMENT_RING_GOLD_RATE_PER_ENHANCE)),
            ),
            float(ENCHANTMENT_RING_DROP_RATE_BONUS)
            + (enhance_level * float(ENCHANTMENT_RING_DROP_RATE_BONUS_PER_ENHANCE)),
        )

    def get_ring_mode_bonus(self, u: Dict[str, Any], mode_key: Optional[str]) -> Tuple[int, int]:
        ring_stats = self.get_equipped_item_stats(u, "ring")
        ring_atk = max(0, int(ring_stats.get("atk", 0)))
        ring_def = max(0, int(ring_stats.get("def", 0)))
        normalized_mode = str(mode_key or DEFAULT_EXPLORATION_MODE)

        if normalized_mode == "cautious":
            return -ring_atk, ring_def
        if normalized_mode == "reckless":
            return ring_atk, -ring_def
        return 0, 0

    def get_armor_lethal_guard_count(self, u: Dict[str, Any]) -> int:
        armor_item = self._get_equipped_item_for_slot(u, "armor")
        base_guard = 0
        if armor_item and self.is_feature_unlocked(u, "survival_guard"):
            base_guard = max(0, int(SURVIVAL_GUARD_BASE_COUNT))
        if self.get_item_enchant_key(armor_item) != "armor":
            return base_guard
        return base_guard + max(0, int(ENCHANTMENT_ARMOR_GUARD_COUNT))

    def get_player_atk(self, u: Dict[str, Any]) -> int:
        level = self.get_adventure_level(u)
        passive_bonuses = self.get_passive_skill_bonuses(u)
        weapon_stats = self.get_equipped_item_stats(u, "weapon")
        return BASE_PLAYER_ATK + level * 2 + max(0, int(weapon_stats.get("atk", 0))) + max(
            0,
            int(passive_bonuses.get("atk", 0)),
        )

    def get_player_def(self, u: Dict[str, Any]) -> int:
        level = self.get_adventure_level(u)
        passive_bonuses = self.get_passive_skill_bonuses(u)
        armor_stats = self.get_equipped_item_stats(u, "armor")
        return BASE_PLAYER_DEF + level + max(0, int(armor_stats.get("def", 0))) + max(
            0,
            int(passive_bonuses.get("def", 0)),
        )

    def get_player_speed(self, u: Dict[str, Any]) -> int:
        passive_bonuses = self.get_passive_skill_bonuses(u)
        shoes_stats = self.get_equipped_item_stats(u, "shoes")
        return BASE_PLAYER_SPEED + max(0, int(shoes_stats.get("speed", 0))) + max(
            0,
            int(passive_bonuses.get("speed", 0)),
        )

    def get_player_stats(self, u: Dict[str, Any], mode_key: Optional[str]) -> Dict[str, int]:
        atk, defense = self.get_player_combat_stats(u, mode_key)
        return {
            "atk": atk,
            "def": defense,
            "speed": max(1, self.get_player_speed(u)),
            "max_hp": max(1, int(u.get("max_hp", DEFAULT_MAX_HP))),
        }

    def get_player_combat_stats(self, u: Dict[str, Any], mode_key: Optional[str]) -> Tuple[int, int]:
        base_atk = self.get_player_atk(u)
        base_def = self.get_player_def(u)
        atk_delta, def_delta = self.get_ring_mode_bonus(u, mode_key)
        return max(1, base_atk + atk_delta), max(0, base_def + def_delta)

    def get_total_power(self, u: Dict[str, Any]) -> int:
        level = self.get_adventure_level(u)
        passive_bonuses = self.get_passive_skill_bonuses(u)
        return (
            level * 3
            + self.get_weapon_power(u)
            + self.get_armor_power(u)
            + self.get_ring_power(u)
            + self.get_shoes_power(u)
            + max(0, int(passive_bonuses.get("atk", 0)))
            + max(0, int(passive_bonuses.get("def", 0)))
            + max(0, int(passive_bonuses.get("speed", 0))) // 10
            + max(0, int(passive_bonuses.get("max_hp", 0))) // 8
        )

    def get_material_inventory(self, u: Dict[str, Any]) -> Dict[str, int]:
        materials = u.setdefault("materials", {})
        return {
            slot_name: max(0, int(materials.get(slot_name, 0)))
            for slot_name in MATERIAL_LABELS
        }

    def get_exploration_preparation_state(self, u: Dict[str, Any]) -> Dict[str, bool]:
        preparation = u.get("exploration_preparation")
        if not isinstance(preparation, dict):
            preparation = {}
        normalized = {
            slot_name: bool(preparation.get(slot_name, False))
            for slot_name in EXPLORATION_PREPARATION_CONFIG
        }
        u["exploration_preparation"] = normalized
        return normalized

    def get_exploration_preparation_material_cost(self, slot: str) -> int:
        config = EXPLORATION_PREPARATION_CONFIG.get(str(slot or "").strip(), {})
        return max(1, _safe_int(config.get("material_cost", 1), 1))

    def get_exploration_preparation_effect_summary(self, slot: str) -> str:
        config = EXPLORATION_PREPARATION_CONFIG.get(str(slot or "").strip(), {})
        parts: List[str] = []

        atk_bonus = max(0, _safe_int(config.get("atk", 0), 0))
        if atk_bonus > 0:
            parts.append(f"A+{atk_bonus}")

        def_bonus = max(0, _safe_int(config.get("def", 0), 0))
        if def_bonus > 0:
            parts.append(f"D+{def_bonus}")

        speed_bonus = max(0, _safe_int(config.get("speed", 0), 0))
        if speed_bonus > 0:
            parts.append(f"S+{speed_bonus}")

        exp_rate_bonus = max(0.0, float(config.get("exp_rate", 1.0)) - 1.0)
        if exp_rate_bonus > 0.0:
            parts.append(f"EXP+{int(round(exp_rate_bonus * 100))}%")

        gold_rate_bonus = max(0.0, float(config.get("gold_rate", 1.0)) - 1.0)
        if gold_rate_bonus > 0.0:
            parts.append(f"Gold+{int(round(gold_rate_bonus * 100))}%")

        drop_bonus = max(0.0, float(config.get("drop_bonus", 0.0)))
        if drop_bonus > 0.0:
            parts.append(f"Drop+{int(round(drop_bonus * 100))}%")

        return " / ".join(parts) if parts else "補正なし"

    def format_exploration_preparation_status(self, u: Dict[str, Any]) -> str:
        preparation = self.get_exploration_preparation_state(u)
        active_slots = [
            slot_name
            for slot_name in self._get_slot_order()
            if slot_name in preparation and preparation.get(slot_name, False)
        ]
        if not active_slots:
            return "なし"
        return " / ".join(
            f"{SLOT_LABEL.get(slot_name, slot_name)}({self.get_exploration_preparation_effect_summary(slot_name)})"
            for slot_name in active_slots
        )

    def prepare_exploration(self, u: Dict[str, Any], slot: str) -> Tuple[bool, str]:
        safe_slot = str(slot or "").strip()
        if safe_slot not in EXPLORATION_PREPARATION_CONFIG:
            return False, "はその探索準備を行えません。"
        if bool(u.get("down", False)):
            return False, "は戦闘不能です。 `!蘇生` で復帰してください。"

        explore = u.get("explore", {})
        if isinstance(explore, dict) and explore.get("state") == "exploring":
            return False, "は探索中です。探索準備は帰還後に行ってください。"
        if not self.is_slot_unlocked(u, safe_slot):
            return False, f"はまだ{SLOT_LABEL.get(safe_slot, safe_slot)}スロットが未開放です。"

        preparation = self.get_exploration_preparation_state(u)
        if preparation.get(safe_slot, False):
            return False, (
                f"はすでに{SLOT_LABEL.get(safe_slot, safe_slot)}を準備済みです。"
                "次の探索で消費されます。"
            )

        materials = u.setdefault("materials", {})
        available_materials = max(0, _safe_int(materials.get(safe_slot, 0), 0))
        material_cost = self.get_exploration_preparation_material_cost(safe_slot)
        if available_materials < material_cost:
            return False, (
                f"の探索準備素材が足りません。 "
                f"{MATERIAL_LABELS[safe_slot]} 必要:{material_cost} / 所持:{available_materials}"
            )

        materials[safe_slot] = available_materials - material_cost
        preparation[safe_slot] = True
        u["exploration_preparation"] = preparation
        return True, (
            f"は {SLOT_LABEL.get(safe_slot, safe_slot)} の探索準備を整えた。 "
            f"{MATERIAL_LABELS[safe_slot]}-{material_cost} / 次の探索1回だけ "
            f"{self.get_exploration_preparation_effect_summary(safe_slot)} / "
            f"待機中:{self.format_exploration_preparation_status(u)}"
        )

    def consume_exploration_preparations(self, u: Dict[str, Any]) -> Dict[str, Any]:
        preparation = self.get_exploration_preparation_state(u)
        active_slots = [
            slot_name
            for slot_name in self._get_slot_order()
            if slot_name in preparation and preparation.get(slot_name, False)
        ]
        result = {
            "slots": active_slots,
            "atk": 0,
            "def": 0,
            "speed": 0,
            "exp_rate": 1.0,
            "gold_rate": 1.0,
            "drop_bonus": 0.0,
            "summary": "",
        }
        if not active_slots:
            return result

        summary_parts: List[str] = []
        for slot_name in active_slots:
            config = EXPLORATION_PREPARATION_CONFIG.get(slot_name, {})
            result["atk"] += max(0, _safe_int(config.get("atk", 0), 0))
            result["def"] += max(0, _safe_int(config.get("def", 0), 0))
            result["speed"] += max(0, _safe_int(config.get("speed", 0), 0))
            result["exp_rate"] *= max(0.0, float(config.get("exp_rate", 1.0)))
            result["gold_rate"] *= max(0.0, float(config.get("gold_rate", 1.0)))
            result["drop_bonus"] += max(0.0, float(config.get("drop_bonus", 0.0)))
            summary_parts.append(
                f"{SLOT_LABEL.get(slot_name, slot_name)}({self.get_exploration_preparation_effect_summary(slot_name)})"
            )
            preparation[slot_name] = False

        u["exploration_preparation"] = preparation
        result["summary"] = " / ".join(summary_parts)
        return result

    def get_enchant_material_inventory(self, u: Dict[str, Any]) -> Dict[str, int]:
        enchant_materials = u.setdefault("enchant_materials", {})
        totals: Dict[str, int] = {}
        for slot_name, label in ENCHANTMENT_MATERIAL_LABELS.items():
            totals[label] = totals.get(label, 0) + max(0, int(enchant_materials.get(slot_name, 0)))
        return totals

    def format_material_inventory(self, u: Dict[str, Any]) -> str:
        materials = self.get_material_inventory(u)
        enchant_materials = self.get_enchant_material_inventory(u)

        enhancement_text = " / ".join(
            f"{MATERIAL_LABELS[slot_name]}:{materials.get(slot_name, 0)}"
            for slot_name in MATERIAL_LABELS
        )
        enchantment_text = " / ".join(
            f"{label}:{count}"
            for label, count in enchant_materials.items()
        )
        return f"強化[{enhancement_text}] / エンチャ[{enchantment_text}]"

    def format_duration(self, sec: int) -> str:
        sec = max(0, int(sec))
        m, s = divmod(sec, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}時間{m}分"
        if m > 0:
            return f"{m}分{s}秒"
        return f"{s}秒"

    def format_equipped_item(self, u: Dict[str, Any], slot: str) -> str:
        if not self.is_slot_unlocked(u, slot):
            return "未開放"

        item = self._get_equipped_item_for_slot(u, slot)
        if not item:
            return "なし"

        self._sanitize_item(item)
        enchant_label = self.get_item_enchant_label(item)
        enhance = int(item.get("enhance", 0))
        item_text = item["name"]
        if enhance > 0:
            item_text += f"+{enhance}"
        item_text += (
            f"({format_item_stat_text(item.get('slot', slot), item.get('stats', {}), power=int(item.get('power', 0)))})"
        )
        if enchant_label:
            item_text += f"{{{enchant_label}}}"
        return item_text

    def format_item_brief(self, item: Dict[str, Any]) -> str:
        self._sanitize_item(item)
        item_text = item["name"]
        enhance = int(item.get("enhance", 0))
        if enhance > 0:
            item_text += f"+{enhance}"

        item_text += (
            f"[{SLOT_LABEL.get(item.get('slot', ''), item.get('slot', ''))} "
            f"{format_item_stat_text(item.get('slot', ''), item.get('stats', {}), power=int(item.get('power', 0)))}]"
        )
        enchant_label = self.get_item_enchant_label(item)
        if enchant_label:
            item_text += f"{{{enchant_label}}}"
        return item_text

    def _get_item_score(self, item: Optional[Dict[str, Any]]) -> Tuple[int, int, int]:
        if not item:
            return (-1, -1, -1)
        return (
            RARITY_ORDER.get(item.get("rarity", "common"), 0),
            int(item.get("power", 0)),
            1 if self.get_item_enchant_key(item) else 0,
        )

    def get_sorted_bag_items(self, u: Dict[str, Any]) -> List[Dict[str, Any]]:
        bag = u.get("bag", [])
        if not isinstance(bag, list):
            return []

        return sorted(
            [item for item in bag if isinstance(item, dict)],
            key=lambda item: (
                -int(self.is_item_protected(u, item)),
                -int(bool(self.get_item_enchant_key(item))),
                -RARITY_ORDER.get(item.get("rarity", "common"), 0),
                -int(item.get("power", 0)),
                item.get("slot", ""),
                item.get("name", ""),
            ),
        )

    def get_best_upgrade_candidates(self, u: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        bag = u.get("bag", [])
        equipped = u.get("equipped", {})
        if not isinstance(bag, list) or not isinstance(equipped, dict):
            return {}

        candidates: Dict[str, Dict[str, Any]] = {}
        for slot_name in self._get_slot_order():
            if not self.is_slot_unlocked(u, slot_name):
                continue
            current_score = self._get_item_score(equipped.get(slot_name))
            best_item: Optional[Dict[str, Any]] = None
            best_score = current_score
            for item in bag:
                if not isinstance(item, dict) or item.get("slot") != slot_name:
                    continue
                item_score = self._get_item_score(item)
                if item_score <= best_score:
                    continue
                best_item = item
                best_score = item_score
            if best_item:
                candidates[slot_name] = best_item
        return candidates

    def build_exploration_history_entry(self, result: Dict[str, Any]) -> Dict[str, Any]:
        safe_result = dict(result)
        self._sanitize_exploration_result(safe_result)

        raw_drop_items = safe_result.get("drop_items", [])
        sorted_drop_items = sorted(
            [item for item in raw_drop_items if isinstance(item, dict)],
            key=lambda item: (
                -int(bool(self.get_item_enchant_key(item))),
                -RARITY_ORDER.get(item.get("rarity", "common"), 0),
                -int(item.get("power", 0)),
                item.get("slot", ""),
                item.get("name", ""),
            ),
        )
        summary_items = [
            self._sanitize_history_item(item)
            for item in sorted_drop_items[:5]
        ]

        downed = bool(safe_result.get("downed", False) or not bool(safe_result.get("returned_safe", True)))
        return self._sanitize_exploration_history_entry(
            {
                "claimed_at": float(safe_result.get("claimed_at", 0.0) or 0.0),
                "area": safe_result.get("area", DEFAULT_AREA),
                "mode": safe_result.get("mode", DEFAULT_EXPLORATION_MODE),
                "battle_count": get_battle_count(safe_result),
                "exploration_runs": max(1, _safe_int(safe_result.get("exploration_runs", 1), 1)),
                "downed": downed,
                "result": "戦闘不能" if downed else "帰還",
                "exp": max(0, _safe_int(safe_result.get("exp", 0), 0)),
                "gold": max(0, _safe_int(safe_result.get("gold", 0), 0)),
                "return_reason": safe_result.get("return_reason", "探索終了"),
                "drop_items": summary_items,
                "drop_item_count": len(raw_drop_items),
                "drop_materials": safe_result.get("drop_materials", {}),
                "drop_enchant_materials": safe_result.get("drop_enchant_materials", {}),
                "auto_explore_stones": safe_result.get("auto_explore_stones", 0),
            }
        )

    def append_exploration_history(self, u: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        entry = self.build_exploration_history_entry(result)
        history = u.setdefault("exploration_history", [])
        history.insert(0, entry)
        del history[EXPLORATION_HISTORY_LIMIT:]
        return entry

    def get_area_depth_records(self) -> Dict[str, Dict[str, Any]]:
        raw_records = self.data.get("area_depth_records")
        if not isinstance(raw_records, dict):
            raw_records = {}

        sanitized: Dict[str, Dict[str, Any]] = {}
        for area_name, record in raw_records.items():
            safe_record = self._sanitize_area_depth_record(area_name, record)
            if not safe_record:
                continue
            sanitized[safe_record["area"]] = safe_record

        self.data["area_depth_records"] = sanitized
        return sanitized

    def get_area_depth_record(self, area_name: Optional[str]) -> Optional[Dict[str, Any]]:
        safe_area_name = str(area_name or DEFAULT_AREA).strip() or DEFAULT_AREA
        if safe_area_name not in AREAS:
            return None

        record = self.get_area_depth_records().get(safe_area_name)
        if not isinstance(record, dict):
            return None
        return dict(record)

    def update_area_depth_record(
        self,
        username: str,
        display_name: Optional[str],
        result: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        safe_area_name = str(result.get("area", DEFAULT_AREA) or DEFAULT_AREA).strip() or DEFAULT_AREA
        if safe_area_name not in AREAS:
            return None

        battle_count = max(0, get_battle_count(result))
        total_turns = max(0, _safe_int(result.get("total_turns", 0), 0))
        if battle_count <= 0:
            return None

        safe_username = str(username or "").strip().lower()
        if not safe_username:
            return None
        safe_display_name = self._normalize_display_name(safe_username, display_name)

        records = self.get_area_depth_records()
        previous = records.get(safe_area_name)
        comparison_previous = previous
        if previous:
            previous_username = str(previous.get("username", "") or "").strip().lower()
            previous_is_owner = self._is_owner_rank_content_user(previous_username)
            candidate_is_owner = self._is_owner_rank_content_user(safe_username)
            if previous_is_owner and not candidate_is_owner:
                comparison_previous = None
            elif candidate_is_owner and not previous_is_owner:
                return None
        if comparison_previous:
            previous_battle_count = max(0, _safe_int(comparison_previous.get("battle_count", 0), 0))
            previous_total_turns = max(0, _safe_int(comparison_previous.get("total_turns", 0), 0))
            if battle_count < previous_battle_count:
                return None
            if battle_count == previous_battle_count and total_turns >= previous_total_turns:
                return None

        updated_at = now_ts()
        records[safe_area_name] = {
            "area": safe_area_name,
            "username": safe_username,
            "display_name": safe_display_name,
            "battle_count": battle_count,
            "total_turns": total_turns,
            "updated_at": updated_at,
        }
        self.data["area_depth_records"] = records

        update = {
            "area": safe_area_name,
            "username": safe_username,
            "display_name": safe_display_name,
            "battle_count": battle_count,
            "total_turns": total_turns,
            "updated_at": updated_at,
            "is_first_record": previous is None,
            "holder_changed": bool(previous and previous.get("username") != safe_username),
            "previous_username": "",
            "previous_display_name": "",
            "previous_battle_count": 0,
            "previous_total_turns": 0,
            "previous_updated_at": 0.0,
        }
        if previous:
            update["previous_username"] = str(previous.get("username", "") or "").strip().lower()
            update["previous_display_name"] = self._normalize_display_name(
                update["previous_username"],
                previous.get("display_name"),
            )
            update["previous_battle_count"] = max(0, _safe_int(previous.get("battle_count", 0), 0))
            update["previous_total_turns"] = max(0, _safe_int(previous.get("total_turns", 0), 0))
            update["previous_updated_at"] = float(previous.get("updated_at", 0.0) or 0.0)
        return self._sanitize_area_depth_record_update(update)

    def update_exploration_records(self, u: Dict[str, Any], result: Dict[str, Any]) -> List[str]:
        records = self._sanitize_exploration_records(u.get("exploration_records"))
        u["exploration_records"] = records

        candidates = [
            ("best_exp", "最高EXP", max(0, _safe_int(result.get("exp", 0), 0))),
            ("best_gold", "最高Gold", max(0, _safe_int(result.get("gold", 0), 0))),
            ("best_battle_count", "最多戦闘", max(0, get_battle_count(result))),
            (
                "best_exploration_runs",
                "最多周回",
                max(0, _safe_int(result.get("exploration_runs", 1), 1)),
            ),
        ]

        updated: List[str] = []
        for key, label, value in candidates:
            previous = max(0, _safe_int(records.get(key, 0), 0))
            if value <= previous:
                continue
            records[key] = value
            if previous > 0:
                updated.append(f"{label} {value}")
        return updated

    def get_exploration_history(self, u: Dict[str, Any], *, include_fallback: bool = True) -> List[Dict[str, Any]]:
        history = u.get("exploration_history", [])
        if isinstance(history, list) and history:
            return [
                self._sanitize_exploration_history_entry(entry)
                for entry in history
                if isinstance(entry, dict)
            ][:EXPLORATION_HISTORY_LIMIT]

        if include_fallback:
            last_result = u.get("last_exploration_result")
            if isinstance(last_result, dict):
                return [self.build_exploration_history_entry(last_result)]
        return []

    def _build_enchant_recommendation(self, u: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.is_feature_unlocked(u, "enchanting"):
            return None

        enchant_materials = self.get_enchant_material_inventory(u)
        if sum(enchant_materials.values()) <= 0:
            return None

        recommendations = (
            (
                "weapon",
                "!エンチャント 武器",
                "!エンチャント 武器 で火力補強",
                "会心でボスまで押し切りやすくなります。",
            ),
            (
                "ring",
                "!エンチャント 装飾",
                "!エンチャント 装飾 で探索効率UP",
                "探索EXPとドロップ補正を伸ばせます。",
            ),
            (
                "armor",
                "!エンチャント 防具",
                "!エンチャント 防具 で安定化",
                "致死回避で事故が減って探索が安定します。",
            ),
        )
        for slot_name, action, summary, reason in recommendations:
            if not self.is_slot_unlocked(u, slot_name):
                continue
            item = self._get_equipped_item_for_slot(u, slot_name)
            if not item:
                continue
            if self.get_item_enchant_key(item) == slot_name:
                continue
            return {
                "action": action,
                "summary": summary,
                "reason": reason,
                "area": "",
            }

        return None

    def _get_completed_enchant_slots(self, u: Dict[str, Any]) -> Dict[str, bool]:
        raw_progress = u.get("enchant_progress")
        progress = raw_progress if isinstance(raw_progress, dict) else {}
        return {
            slot_name: bool(progress.get(slot_name, False))
            or any(self.get_item_enchant_key(item) == slot_name for item in self._iter_user_items(u))
            for slot_name in ENCHANTMENT_MATERIAL_LABELS
        }

    def has_completed_enchant_slot(self, u: Dict[str, Any], slot_name: str) -> bool:
        safe_slot_name = str(slot_name or "").strip()
        if safe_slot_name not in ENCHANTMENT_MATERIAL_LABELS:
            return False
        return bool(self._get_completed_enchant_slots(u).get(safe_slot_name, False))

    def _get_area_completion_count(self, u: Dict[str, Any], area_name: str) -> int:
        safe_area_name = str(area_name or "").strip()
        if safe_area_name not in AREAS:
            return 0
        return sum(
            1
            for entry in u.get("exploration_history", [])
            if isinstance(entry, dict) and str(entry.get("area", "") or "").strip() == safe_area_name
        )

    def should_recommend_beginner_cautious_mode(self, u: Dict[str, Any]) -> bool:
        morning_runs = self._get_area_completion_count(u, BEGINNER_GUARANTEE_AREA)
        return morning_runs < int(BEGINNER_CAUTIOUS_RECOMMENDATION_COUNT)

    def _build_recovery_recommendation(self, u: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        current_potions = max(0, _safe_int(u.get("potions", 0), 0))
        current_gold = max(0, _safe_int(u.get("gold", 0), 0))
        if current_potions > 0 or current_gold >= int(POTION_PRICE):
            return None

        history = self.get_exploration_history(u, include_fallback=False)
        if len(history) < 2:
            return None

        latest_area = str(history[0].get("area", "") or "").strip()
        if latest_area not in AREAS or latest_area == BEGINNER_GUARANTEE_AREA:
            return None

        boss_clear_areas = {
            str(area_name).strip()
            for area_name in u.get("boss_clear_areas", [])
            if str(area_name).strip() in AREAS
        }
        if latest_area in boss_clear_areas:
            return None

        recent_same_area = [
            entry
            for entry in history[:3]
            if str(entry.get("area", "") or "").strip() == latest_area
        ]
        low_progress_count = sum(
            1
            for entry in recent_same_area
            if max(0, _safe_int(entry.get("battle_count", 0), 0)) <= 1
        )
        if low_progress_count < 2:
            return None

        current_hp = max(0, _safe_int(u.get("hp", DEFAULT_MAX_HP), DEFAULT_MAX_HP))
        max_hp = max(1, _safe_int(u.get("max_hp", DEFAULT_MAX_HP), DEFAULT_MAX_HP))
        cautious = current_hp * 2 < max_hp
        action = f"!探索 開始 {BEGINNER_GUARANTEE_AREA}"
        summary = f"{BEGINNER_GUARANTEE_AREA} で資金とポーションを立て直す"
        if cautious:
            action = f"!探索 開始 慎重 {BEGINNER_GUARANTEE_AREA}"
            summary = f"慎重 {BEGINNER_GUARANTEE_AREA} で立て直す"

        return {
            "action": action,
            "summary": summary,
            "reason": (
                f"{latest_area} で戦闘数が伸びていないため、"
                f"いったん {BEGINNER_GUARANTEE_AREA} で資金とポーションを立て直すのが安定です。"
            ),
            "area": BEGINNER_GUARANTEE_AREA,
        }

    def _build_exploration_preparation_recommendation(self, u: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if bool(u.get("down", False)):
            return None
        if any(self.get_exploration_preparation_state(u).values()):
            return None

        explore = u.get("explore", {})
        if isinstance(explore, dict) and explore.get("state") == "exploring":
            return None

        materials = self.get_material_inventory(u)
        candidates: List[Tuple[int, int, int, str]] = []
        preferred_slots = ("weapon", "armor", "ring")
        for order_index, slot_name in enumerate(preferred_slots):
            if not self.is_slot_unlocked(u, slot_name):
                continue
            if not isinstance(self._get_equipped_item_for_slot(u, slot_name), dict):
                continue

            material_cost = self.get_exploration_preparation_material_cost(slot_name)
            available_materials = materials.get(slot_name, 0)
            if available_materials < material_cost:
                continue

            candidates.append(
                (
                    self.get_equipped_item_power(u, slot_name),
                    -available_materials,
                    order_index,
                    slot_name,
                )
            )

        if not candidates:
            return None

        slot_name = min(candidates)[3]
        slot_label = SLOT_LABEL.get(slot_name, slot_name)
        effect_summary = self.get_exploration_preparation_effect_summary(slot_name)
        return {
            "action": f"!探索 準備 {slot_label}",
            "summary": f"!探索 準備 {slot_label} で次の探索を底上げ",
            "reason": (
                f"{MATERIAL_LABELS[slot_name]}が十分あるため、"
                f"次の探索1回だけ {effect_summary} を付けて素材を戦力へ変換できます。"
            ),
            "area": "",
        }

    def calculate_return_heal_cost(self, missing_hp: int) -> int:
        safe_missing_hp = max(0, int(missing_hp))
        if safe_missing_hp <= 0:
            return 0
        return max(
            1,
            int(math.ceil(safe_missing_hp * float(RETURN_HEAL_GOLD_PER_MISSING_HP))),
        )

    def auto_restore_hp_after_return(self, u: Dict[str, Any]) -> Dict[str, int]:
        max_hp = max(1, int(u.get("max_hp", DEFAULT_MAX_HP)))
        current_hp = max(0, int(u.get("hp", 0)))
        missing_hp = max(0, max_hp - current_hp)
        if missing_hp <= 0:
            u["hp"] = max_hp
            return {"restored_hp": 0, "cost": 0, "full_heal": 1}

        current_gold = max(0, int(u.get("gold", 0)))
        if current_gold <= 0:
            return {"restored_hp": 0, "cost": 0, "full_heal": 0}

        full_cost = self.calculate_return_heal_cost(missing_hp)
        restored_hp = missing_hp
        cost = full_cost

        if current_gold < full_cost:
            gold_per_hp = float(RETURN_HEAL_GOLD_PER_MISSING_HP)
            if gold_per_hp <= 0:
                restored_hp = missing_hp
            else:
                restored_hp = min(
                    missing_hp,
                    max(0, int(math.floor(current_gold / gold_per_hp))),
                )
            if restored_hp <= 0:
                return {"restored_hp": 0, "cost": 0, "full_heal": 0}
            cost = self.calculate_return_heal_cost(restored_hp)
            while restored_hp > 0 and cost > current_gold:
                restored_hp -= 1
                cost = self.calculate_return_heal_cost(restored_hp)
            if restored_hp <= 0:
                return {"restored_hp": 0, "cost": 0, "full_heal": 0}

        u["gold"] = max(0, current_gold - cost)
        u["hp"] = min(max_hp, current_hp + restored_hp)
        return {
            "restored_hp": max(0, int(restored_hp)),
            "cost": max(0, int(cost)),
            "full_heal": 1 if int(u.get("hp", 0)) >= max_hp else 0,
        }

    def get_auto_potion_refill_target(self, u: Dict[str, Any]) -> int:
        return clamp(
            _safe_int(
                u.get("auto_potion_refill_target", MAX_POTIONS_PER_EXPLORATION),
                MAX_POTIONS_PER_EXPLORATION,
            ),
            0,
            MAX_POTIONS_PER_EXPLORATION,
        )

    def build_next_recommendation(self, u: Dict[str, Any]) -> Dict[str, Any]:
        explore = u.get("explore", {})
        if bool(u.get("down", False)):
            return {
                "action": "!状態 蘇生",
                "summary": "!状態 蘇生 で復帰",
                "reason": "戦闘不能なのでまず復帰が必要です。",
                "area": "",
            }

        if isinstance(explore, dict) and explore.get("state") == "exploring":
            if bool(explore.get("auto_repeat", False)):
                return {
                    "action": "!探索 停止",
                    "summary": "自動周回中。止める時は !探索 停止",
                    "reason": "周回が続いている間は結果がまとまるまで待機します。",
                    "area": str(explore.get("area", DEFAULT_AREA)),
                }
            if not bool(explore.get("auto_repeat", False)) and float(explore.get("ends_at", 0)) <= now_ts():
                return {
                    "action": "!探索 結果",
                    "summary": "!探索 結果 で受け取り",
                    "reason": "探索が完了しているため結果受取が先です。",
                    "area": str(explore.get("area", DEFAULT_AREA)),
                }
            if not bool(explore.get("auto_repeat", False)) and float(explore.get("ends_at", 0)) > now_ts():
                return {
                    "action": "!探索 結果",
                    "summary": "探索中。帰還後に !探索 結果",
                    "reason": "探索が終わったら受け取りましょう。",
                    "area": str(explore.get("area", DEFAULT_AREA)),
                }

        upgrade_candidates = self.get_best_upgrade_candidates(u)
        if upgrade_candidates:
            slot_name = next(iter(upgrade_candidates))
            slot_label = SLOT_LABEL.get(slot_name, slot_name)
            return {
                "action": "!装備 整理",
                "summary": f"!装備 整理 で{slot_label}更新",
                "reason": f"バッグに {slot_label} の更新候補があります。",
                "area": "",
            }

        current_potions = max(0, _safe_int(u.get("potions", 0), 0))
        current_gold = max(0, _safe_int(u.get("gold", 0), 0))
        if current_potions <= 1 and current_gold >= int(POTION_PRICE):
            return {
                "action": "!状態 ポーション",
                "summary": "!状態 ポーション で補充",
                "reason": "ポーションが少ないので探索前に補充しておくと安定します。",
                "area": "",
            }

        unlocked_slots = self.get_unlocked_slots(u)
        if not unlocked_slots.get("armor", False) or not unlocked_slots.get("ring", False):
            beginner_action = f"!探索 開始 {BEGINNER_GUARANTEE_AREA}"
            beginner_summary = f"{BEGINNER_GUARANTEE_AREA} で初回ボス撃破"
            beginner_reason = f"{BEGINNER_GUARANTEE_AREA}ボス撃破で防具・装飾スロットが解放されます。"
            if self.should_recommend_beginner_cautious_mode(u):
                beginner_action = f"!探索 開始 慎重 {BEGINNER_GUARANTEE_AREA}"
                beginner_summary = f"慎重 {BEGINNER_GUARANTEE_AREA} で初回ボス撃破"
                beginner_reason = (
                    f"最初の数回は慎重モードで進むと {BEGINNER_GUARANTEE_AREA} の事故が減り、"
                    "防具・装飾解放まで安定しやすいです。"
                )
            return {
                "action": beginner_action,
                "summary": beginner_summary,
                "reason": beginner_reason,
                "area": BEGINNER_GUARANTEE_AREA,
            }

        recovery_recommendation = self._build_recovery_recommendation(u)
        if recovery_recommendation:
            return recovery_recommendation

        if not self.is_feature_unlocked(u, "enchanting"):
            return {
                "action": "!探索 開始 三日月廃墟",
                "summary": "三日月廃墟で初回ボス撃破",
                "reason": "三日月廃墟ボス撃破でエンチャントが解放されます。",
                "area": "三日月廃墟",
            }

        auto_repeat_progress = self.get_auto_repeat_progress(u)
        prioritize_fragments_early = (
            not auto_repeat_progress["unlocked"]
            and self.has_completed_enchant_slot(u, "weapon")
            and int(auto_repeat_progress.get("fragments", 0)) <= 0
        )
        enchant_materials = self.get_enchant_material_inventory(u)
        if sum(enchant_materials.values()) <= 0 and not prioritize_fragments_early:
            return {
                "action": "!探索 開始 三日月廃墟",
                "summary": "三日月廃墟でエンチャ素材集め",
                "reason": "エンチャント素材がまだないので先に確保すると伸びやすいです。",
                "area": "三日月廃墟",
            }
        enchant_recommendation = self._build_enchant_recommendation(u)
        if enchant_recommendation and not prioritize_fragments_early:
            return enchant_recommendation

        if not auto_repeat_progress["unlocked"]:
            boss_clear_areas = {
                str(area_name).strip()
                for area_name in u.get("boss_clear_areas", [])
                if str(area_name).strip() in AREAS
            }
            fragment_focus = (
                ("ヘッセ深部", "高レア装備更新と自動周回欠片集めを兼ねます。"),
                ("紅蓮の鉱山", "武器育成を進めつつ自動周回欠片を確保できます。"),
                ("沈黙の城塞跡", "防具育成を進めつつ自動周回欠片を確保できます。"),
            )
            for area_name, reason in fragment_focus:
                rewards = self._get_area_first_clear_rewards(area_name)
                if area_name in boss_clear_areas:
                    continue
                if int(rewards.get("auto_explore_fragments", 0)) <= 0:
                    continue
                return {
                    "action": f"!探索 開始 {area_name}",
                    "summary": f"{area_name} で自動周回欠片を進める",
                    "reason": reason,
                    "area": area_name,
                }
            if not auto_repeat_progress["route_unlocked"]:
                return {
                    "action": "!探索 開始 星影の祭壇",
                    "summary": "星影の祭壇で自動周回導線を解放",
                    "reason": "星影の祭壇ボス初回撃破で自動周回導線が開放されます。",
                    "area": "星影の祭壇",
                }

        exploration_preparation_recommendation = self._build_exploration_preparation_recommendation(u)
        if exploration_preparation_recommendation:
            return exploration_preparation_recommendation

        weapon_power = self.get_weapon_power(u)
        armor_power = self.get_armor_power(u)
        ring_power = self.get_ring_power(u)
        weakest_slot = min(
            (
                ("weapon", weapon_power),
                ("armor", armor_power),
                ("ring", ring_power),
            ),
            key=lambda pair: pair[1],
        )[0]
        material_focus = {
            "weapon": ("紅蓮の鉱山", "火力が伸びやすい武器素材を集めましょう。"),
            "armor": ("沈黙の城塞跡", "耐久が不安なら防具素材を優先しましょう。"),
            "ring": ("星影の祭壇", "周回効率を上げる装飾素材を集めましょう。"),
        }
        focus_area, focus_reason = material_focus[weakest_slot]
        materials = self.get_material_inventory(u)
        if materials.get(weakest_slot, 0) < 5:
            return {
                "action": f"!探索 開始 {focus_area}",
                "summary": f"{focus_area} で{SLOT_LABEL.get(weakest_slot, weakest_slot)}育成",
                "reason": focus_reason,
                "area": focus_area,
            }

        return {
            "action": "!探索 開始 ヘッセ深部",
            "summary": "ヘッセ深部で高レア装備狙い",
            "reason": "次は高レア装備を掘って全体戦力を更新する段階です。",
            "area": "ヘッセ深部",
        }

    def reward_chat_exp(self, u: Dict[str, Any], now: float) -> bool:
        if not CHAT_EXP_ENABLED:
            return False

        last = float(u.get("chat_exp_ts", 0.0))
        if now - last < CHAT_EXP_MIN_INTERVAL_SEC:
            return False

        u["chat_exp_ts"] = now
        u["chat_exp"] = int(u.get("chat_exp", 0)) + int(CHAT_EXP_PER_MSG)
        self._sync_level_stats(u)
        return True

    def buy_potions(self, username: str, qty: Optional[int], potion_price: int) -> Tuple[bool, str]:
        u = self.get_user(username)

        gold = int(u.get("gold", 0))
        current_potions = int(u.get("potions", 0))
        autofill = qty is None

        if autofill:
            if u.get("down", False):
                return False, "は戦闘不能のため購入できません。 `!蘇生` で復帰してください。"
            missing_potions = max(0, MAX_POTIONS_PER_EXPLORATION - current_potions)
            if missing_potions <= 0:
                return False, (
                    f"ポーションはすでに探索上限の{MAX_POTIONS_PER_EXPLORATION}個あります。"
                )
            if potion_price <= 0:
                qty = missing_potions
            else:
                qty = min(missing_potions, gold // potion_price)
            if qty <= 0:
                return False, (
                    "所持金不足です。"
                    f" ポーション補充には最低 {potion_price}G 必要です。"
                )
            cost = potion_price * qty

            if gold < cost:
                return False, f"所持金不足です。ポーション{qty}個で {cost}G 必要です。"

            u["gold"] = gold - cost
            u["potions"] = current_potions + qty
            return True, (
                f"ポーションを {qty} 個補充。 -{cost}G / "
                f"所持ポーション:{u['potions']} / 探索上限:{MAX_POTIONS_PER_EXPLORATION}"
            )

        target_potions = clamp(int(qty), 0, MAX_POTIONS_PER_EXPLORATION)
        u["auto_potion_refill_target"] = target_potions

        if target_potions <= 0:
            return True, f"ポーション自動補充をOFFにしました。現在 {current_potions}個"

        if u.get("down", False):
            return True, (
                f"ポーション自動補充を {target_potions} 個に設定しました。"
                " 戦闘不能中のため今は購入できません。"
            )

        missing_potions = max(0, target_potions - current_potions)
        if missing_potions <= 0:
            return True, (
                f"ポーション自動補充を {target_potions} 個に設定しました。"
                f" 現在 {current_potions}個所持しています。"
            )

        if potion_price <= 0:
            qty_to_buy = missing_potions
        else:
            qty_to_buy = min(missing_potions, gold // potion_price)

        if qty_to_buy <= 0:
            return True, (
                f"ポーション自動補充を {target_potions} 個に設定しました。"
                " 今は所持金不足で補充できません。"
            )

        cost = potion_price * qty_to_buy
        u["gold"] = gold - cost
        u["potions"] = current_potions + qty_to_buy
        if qty_to_buy >= missing_potions:
            return True, (
                f"ポーション自動補充を {target_potions} 個に設定。"
                f" {qty_to_buy}個補充して現在 {u['potions']}個です。 -{cost}G"
            )

        remaining = missing_potions - qty_to_buy
        return True, (
            f"ポーション自動補充を {target_potions} 個に設定。"
            f" 今は {qty_to_buy}個補充して現在 {u['potions']}個です。"
            f" -{cost}G / 残り {remaining}個は後で補充されます。"
        )

    def auto_refill_potions(self, u: Dict[str, Any], potion_price: int) -> Dict[str, int]:
        current_potions = max(0, _safe_int(u.get("potions", 0), 0))
        gold = max(0, _safe_int(u.get("gold", 0), 0))
        target_potions = self.get_auto_potion_refill_target(u)
        missing_potions = max(0, target_potions - current_potions)

        if bool(u.get("down", False)) or missing_potions <= 0:
            return {
                "bought": 0,
                "cost": 0,
                "potions_after": current_potions,
                "gold_after": gold,
            }

        qty = missing_potions
        full_cost = max(0, int(potion_price)) * qty
        cost = min(gold, full_cost)
        u["gold"] = gold - cost
        u["potions"] = current_potions + qty
        return {
            "bought": qty,
            "cost": cost,
            "potions_after": int(u["potions"]),
            "gold_after": int(u["gold"]),
        }

    def revive_user(self, username: str) -> Tuple[bool, str]:
        target = username.lower()
        u = self.get_user(target)
        display_name = self.get_display_name(target, username)

        if not u.get("down", False):
            return False, f"{display_name} は戦闘不能ではありません。"

        current_gold = int(u.get("gold", 0))
        lost_gold = current_gold // 4
        u["gold"] = max(0, current_gold - lost_gold)
        u["down"] = False
        u["hp"] = max(1, int(u.get("max_hp", DEFAULT_MAX_HP)))
        return True, (
            f"{display_name} は自力で復帰しました。"
            f" -{lost_gold}G / 所持金{u['gold']}G / HP {u['hp']}/{u['max_hp']}"
        )

    def debug_heal_user(self, username: str) -> Tuple[bool, str]:
        u = self.get_user(username)
        u["hp"] = int(u.get("max_hp", DEFAULT_MAX_HP))
        u["down"] = False
        return True, f"HPを全回復しました。HP {u['hp']}/{u['max_hp']}"

    def debug_add_gold(self, username: str, amount: int) -> Tuple[bool, str]:
        u = self.get_user(username)
        new_gold = max(0, int(u.get("gold", 0)) + int(amount))
        u["gold"] = new_gold
        sign = "+" if amount >= 0 else ""
        return True, f"所持金を調整しました。 {sign}{amount}G / 現在 {u['gold']}G"

    def debug_add_potions(self, username: str, amount: int) -> Tuple[bool, str]:
        u = self.get_user(username)
        new_potions = max(0, int(u.get("potions", 0)) + int(amount))
        u["potions"] = new_potions
        sign = "+" if amount >= 0 else ""
        return True, f"ポーション数を調整しました。 {sign}{amount} / 現在 {u['potions']}個"

    def debug_add_adventure_exp(self, username: str, amount: int) -> Tuple[bool, str]:
        u = self.get_user(username)
        before_level = self.get_adventure_level(u)

        new_exp = max(0, int(u.get("adventure_exp", 0)) + int(amount))
        u["adventure_exp"] = new_exp
        self._sync_level_stats(u)

        after_level = self.get_adventure_level(u)
        sign = "+" if amount >= 0 else ""

        if after_level > before_level:
            return True, f"冒険EXPを調整しました。 {sign}{amount}EXP / Lv{after_level} に上昇"
        return True, f"冒険EXPを調整しました。 {sign}{amount}EXP / 現在 Lv{after_level}"

    def debug_down_user(self, username: str) -> Tuple[bool, str]:
        u = self.get_user(username)
        u["hp"] = 0
        u["down"] = True
        return True, "戦闘不能状態にしました。"
