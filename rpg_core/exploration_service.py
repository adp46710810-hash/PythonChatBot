from __future__ import annotations

from copy import deepcopy
import math
import random
from typing import Any, Dict, List, Optional, Tuple

from .exploration_result import (
    RETURN_PHASE_BATTLE_CAP,
    RETURN_PHASE_BATTLE_ESCAPE,
    RETURN_PHASE_COMPLETE,
    RETURN_PHASE_DEFEAT,
    RETURN_PHASE_POSTBATTLE,
    RETURN_PHASE_PREBATTLE,
    build_return_info,
    get_battle_count,
)
from .rules import (
    AUTO_REPEAT_COOLDOWN_SEC,
    AREA_ALIASES,
    AREA_MONSTERS,
    AREAS,
    BATTLE_ATK_BONUS_PER_GROWTH,
    BATTLE_ESCALATION_INTERVAL,
    BATTLE_DEF_BONUS_PER_GROWTH,
    BATTLE_DROP_RATE_PER_GROWTH,
    BATTLE_EXP_SCALE_PER_GROWTH,
    BATTLE_GOLD_SCALE_PER_GROWTH,
    BATTLE_GROWTH_ACCELERATION,
    BATTLE_HP_SCALE_PER_GROWTH,
    BATTLE_LATE_GAME_ATK_ACCELERATION,
    BATTLE_LATE_GAME_ATK_BONUS_PER_STEP,
    BATTLE_LATE_GAME_ATK_ENTRY_BONUS,
    BATTLE_LATE_GAME_DEF_ACCELERATION,
    BATTLE_LATE_GAME_DEF_BONUS_PER_STEP,
    BATTLE_LATE_GAME_DEF_ENTRY_BONUS,
    BATTLE_LATE_GAME_DROP_RATE_BONUS,
    BATTLE_LATE_GAME_DROP_RATE_BONUS_ACCELERATION,
    BATTLE_LATE_GAME_DROP_RATE_BONUS_PER_STEP,
    BATTLE_LATE_GAME_EXP_MULTIPLIER,
    BATTLE_LATE_GAME_EXP_ACCELERATION,
    BATTLE_LATE_GAME_EXP_MULTIPLIER_PER_STEP,
    BATTLE_LATE_GAME_GOLD_MULTIPLIER,
    BATTLE_LATE_GAME_GOLD_ACCELERATION,
    BATTLE_LATE_GAME_GOLD_MULTIPLIER_PER_STEP,
    BATTLE_LATE_GAME_HP_ACCELERATION,
    BATTLE_LATE_GAME_HP_MULTIPLIER,
    BATTLE_LATE_GAME_HP_MULTIPLIER_PER_STEP,
    BATTLE_LATE_GAME_RESOURCE_BONUS,
    BATTLE_LATE_GAME_RESOURCE_BONUS_ACCELERATION,
    BATTLE_LATE_GAME_RESOURCE_BONUS_PER_STEP,
    BATTLE_LATE_GAME_START,
    BOSS_BATTLE_INTERVAL,
    BOSS_MONSTER_ATK_BONUS,
    BOSS_MONSTER_DEF_BONUS,
    BOSS_MONSTER_DROP_RATE_BONUS,
    BOSS_MONSTER_EXP_SCALE,
    BOSS_MONSTER_GOLD_SCALE,
    BOSS_MONSTER_HP_SCALE,
    BEGINNER_GUARANTEE_AREA,
    BEGINNER_GUARANTEE_MAX_LEVEL,
    DEFAULT_AREA,
    DEFAULT_EXPLORATION_MODE,
    DEFAULT_MAX_HP,
    DOWNED_EXP_KEEP_RATE,
    DOWNED_GOLD_KEEP_RATE,
    DOWNED_MATERIAL_KEEP_RATE,
    ENCHANTMENT_MATERIAL_LABELS,
    ELITE_MONSTER_ATK_BONUS,
    ELITE_MONSTER_DEF_BONUS,
    EXPLORATION_DURATION_OVERRIDE_SEC,
    EXPLORATION_MODE_CONFIG,
    EXPLORATION_SECONDS_PER_TURN,
    ELITE_MONSTER_DROP_RATE_BONUS,
    ELITE_MONSTER_EXP_SCALE,
    ELITE_MONSTER_GOLD_SCALE,
    ELITE_MONSTER_HP_SCALE,
    EXP_GAIN_MULTIPLIER,
    MAX_BATTLES_PER_EXPLORATION,
    MAX_AUTO_REPEAT_EXPLORATIONS,
    MAX_POTIONS_PER_EXPLORATION,
    MATERIAL_LABELS,
    POTION_PRICE,
    POTION_HEAL_MIN,
    POTION_HEAL_RATIO,
)
from .utils import nfkc, now_ts


class ExplorationService:
    _AUTO_REPEAT_ALIASES = {"自動", "自動周回", "周回", "auto", "loop", "repeat"}

    def __init__(self, user_service, item_service, battle_service):
        self.user_service = user_service
        self.item_service = item_service
        self.battle_service = battle_service

    def get_remaining_potions(self, available_potions: int, potions_used: int) -> int:
        total_available = min(MAX_POTIONS_PER_EXPLORATION, max(0, int(available_potions)))
        return max(0, total_available - max(0, int(potions_used)))

    def get_mode_usable_potions(self, available_potions: int, mode: Dict[str, Any]) -> int:
        total_available = min(MAX_POTIONS_PER_EXPLORATION, max(0, int(available_potions)))
        configured_limit = mode.get("max_potions_to_use")
        if configured_limit is None:
            return total_available
        return max(0, min(total_available, int(configured_limit)))

    def get_potion_heal_amount(self, max_hp: int) -> int:
        scaled_heal = int(max(0, int(max_hp)) * POTION_HEAL_RATIO)
        return max(POTION_HEAL_MIN, scaled_heal)

    def normalize_area_name(self, area: Optional[str]) -> str:
        if not area:
            return DEFAULT_AREA

        text = nfkc(area).strip()
        if not text:
            return DEFAULT_AREA

        return AREA_ALIASES.get(text, DEFAULT_AREA)

    def normalize_mode_name(self, mode_text: Optional[str]) -> Optional[str]:
        if not mode_text:
            return None

        text = nfkc(mode_text).strip().lower()
        if not text:
            return None

        for mode_key, config in EXPLORATION_MODE_CONFIG.items():
            aliases = [mode_key, *config.get("aliases", ())]
            if text in {nfkc(alias).strip().lower() for alias in aliases}:
                return mode_key
        return None

    def normalize_auto_repeat_name(self, text: Optional[str]) -> bool:
        normalized = nfkc(text or "").strip().lower()
        if not normalized:
            return False
        return normalized in {nfkc(alias).strip().lower() for alias in self._AUTO_REPEAT_ALIASES}

    def resolve_exploration_mode(self, mode_key: Optional[str]) -> Dict[str, Any]:
        normalized = mode_key if mode_key in EXPLORATION_MODE_CONFIG else DEFAULT_EXPLORATION_MODE
        config = EXPLORATION_MODE_CONFIG[normalized]
        return {"key": normalized, **config}

    def parse_exploration_request(self, area_text: Optional[str]) -> Tuple[str, Dict[str, Any], bool]:
        if not area_text:
            return DEFAULT_AREA, self.resolve_exploration_mode(DEFAULT_EXPLORATION_MODE), False

        raw_text = nfkc(area_text).strip()
        if not raw_text:
            return DEFAULT_AREA, self.resolve_exploration_mode(DEFAULT_EXPLORATION_MODE), False

        explicit_mode = self.normalize_mode_name(raw_text)
        if explicit_mode:
            return DEFAULT_AREA, self.resolve_exploration_mode(explicit_mode), False
        if self.normalize_auto_repeat_name(raw_text):
            return DEFAULT_AREA, self.resolve_exploration_mode(DEFAULT_EXPLORATION_MODE), True

        parts = [part for part in raw_text.split() if part]
        mode_key = DEFAULT_EXPLORATION_MODE
        auto_repeat = False
        area_parts: List[str] = []

        for part in parts:
            if self.normalize_auto_repeat_name(part):
                auto_repeat = True
                continue
            normalized_mode = self.normalize_mode_name(part)
            if normalized_mode:
                mode_key = normalized_mode
                continue
            area_parts.append(part)

        area_name = self.normalize_area_name(" ".join(area_parts) if area_parts else None)
        return area_name, self.resolve_exploration_mode(mode_key), auto_repeat

    def _build_idle_explore_state(self) -> Dict[str, Any]:
        return {
            "state": "idle",
            "area": "",
            "mode": DEFAULT_EXPLORATION_MODE,
            "started_at": 0.0,
            "ends_at": 0.0,
            "auto_repeat": False,
            "notified_ready": False,
            "result": None,
        }

    def _build_active_explore_state(
        self,
        area_name: str,
        mode: Dict[str, Any],
        result: Dict[str, Any],
        *,
        auto_repeat: bool,
        extra_delay_sec: int = 0,
    ) -> Tuple[Dict[str, Any], int]:
        start = now_ts()
        duration = self.calculate_exploration_duration(int(result.get("total_turns", 0)))
        total_wait_sec = duration + max(0, int(extra_delay_sec))
        end = start + total_wait_sec
        return {
            "state": "exploring",
            "area": area_name,
            "mode": mode["key"],
            "started_at": start,
            "ends_at": end,
            "auto_repeat": bool(auto_repeat),
            "notified_ready": False,
            "result": result,
        }, total_wait_sec

    def _should_grant_beginner_equipment_set(self, area_name: str, player_level: int) -> bool:
        return area_name == BEGINNER_GUARANTEE_AREA and max(1, int(player_level)) <= BEGINNER_GUARANTEE_MAX_LEVEL

    def _append_bonus_items_to_last_battle(
        self,
        battle_logs: List[Dict[str, Any]],
        items: List[Dict[str, Any]],
    ) -> None:
        if not items:
            return

        for battle in reversed(battle_logs):
            if str(battle.get("monster", "?")) == "ポーション使用":
                continue
            battle.setdefault("drop_items", []).extend(deepcopy(items))
            return

    def _grant_beginner_equipment_set(
        self,
        area_name: str,
        player_level: int,
        drop_items: List[Dict[str, Any]],
        battle_logs: List[Dict[str, Any]],
    ) -> None:
        if not self._should_grant_beginner_equipment_set(area_name, player_level):
            return
        if not any(str(battle.get("monster", "?")) != "ポーション使用" for battle in battle_logs):
            return

        owned_slots = {
            str(item.get("slot", "")).strip()
            for item in drop_items
            if isinstance(item, dict)
        }
        bonus_items: List[Dict[str, Any]] = []
        for slot_name in ("weapon", "armor", "ring", "shoes"):
            if slot_name in owned_slots:
                continue
            item = self.item_service.create_guaranteed_equipment(area_name, slot_name)
            if not item:
                continue
            drop_items.append(item)
            bonus_items.append(deepcopy(item))

        self._append_bonus_items_to_last_battle(battle_logs, bonus_items)

    def get_boss_clear_areas_from_result(self, result: Dict[str, Any]) -> List[str]:
        safe_area = str(result.get("area", DEFAULT_AREA) or DEFAULT_AREA).strip()
        if safe_area not in AREAS:
            return []

        kills = result.get("kills")
        if not isinstance(kills, list):
            return []

        for kill in kills:
            if not isinstance(kill, dict):
                continue
            if bool(
                kill.get(
                    "area_boss",
                    bool(kill.get("boss", False)) and not bool(kill.get("world_boss", False)),
                )
            ):
                return [safe_area]
        return []

    def _build_auto_repeat_result_template(
        self,
        area_name: str,
        mode_key: Optional[str],
    ) -> Dict[str, Any]:
        safe_area = area_name if area_name in AREAS else DEFAULT_AREA
        safe_mode = mode_key if mode_key in EXPLORATION_MODE_CONFIG else DEFAULT_EXPLORATION_MODE
        return {
            "area": safe_area,
            "mode": safe_mode,
            "kills": [],
            "exp": 0,
            "gold": 0,
            "damage": 0,
            "drop_items": [],
            "auto_explore_stones": 0,
            "drop_materials": {slot_name: 0 for slot_name in MATERIAL_LABELS},
            "drop_enchant_materials": {
                slot_name: 0 for slot_name in ENCHANTMENT_MATERIAL_LABELS
            },
            "battle_logs": [],
            "battle_count": 0,
            "total_turns": 0,
            "hp_after": 0,
            "returned_safe": True,
            "downed": False,
            "return_reason": "探索終了",
            "return_info": build_return_info(
                phase=RETURN_PHASE_COMPLETE,
                reason="探索終了",
                raw_reason="探索終了",
            ),
            "potions_used": 0,
            "auto_potions_bought": 0,
            "auto_potion_refill_cost": 0,
            "auto_hp_heal_cost": 0,
            "auto_hp_restored": 0,
            "potions_after_claim": 0,
            "armor_guards_used": 0,
            "armor_guards_total": 0,
            "armor_enchant_consumed": False,
            "auto_armor_reenchants": 0,
            "auto_repeat": False,
            "exploration_runs": 0,
        }

    def has_legendary_drop(self, result: Optional[Dict[str, Any]]) -> bool:
        if not isinstance(result, dict):
            return False

        if bool(result.get("downed", False) or not bool(result.get("returned_safe", True))):
            return False

        drop_items = result.get("drop_items")
        if not isinstance(drop_items, list):
            return False

        return any(
            isinstance(item, dict)
            and str(item.get("rarity", "") or "").strip() == "legendary"
            for item in drop_items
        )

    def _merge_exploration_result(
        self,
        summary: Dict[str, Any],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged = deepcopy(summary)
        merged["area"] = result.get("area", merged.get("area", DEFAULT_AREA))
        if merged["area"] not in AREAS:
            merged["area"] = DEFAULT_AREA
        merged["mode"] = result.get("mode", merged.get("mode", DEFAULT_EXPLORATION_MODE))
        if merged["mode"] not in EXPLORATION_MODE_CONFIG:
            merged["mode"] = DEFAULT_EXPLORATION_MODE

        merged.setdefault("kills", [])
        merged["kills"].extend(deepcopy(result.get("kills", [])))
        merged["exp"] = max(0, int(merged.get("exp", 0))) + max(0, int(result.get("exp", 0)))
        merged["gold"] = max(0, int(merged.get("gold", 0))) + max(0, int(result.get("gold", 0)))
        merged["damage"] = max(0, int(merged.get("damage", 0))) + max(0, int(result.get("damage", 0)))
        merged.setdefault("drop_items", [])
        merged["drop_items"].extend(deepcopy(result.get("drop_items", [])))
        merged["auto_explore_stones"] = 1 if (
            max(0, int(merged.get("auto_explore_stones", 0))) > 0
            or max(0, int(result.get("auto_explore_stones", 0))) > 0
        ) else 0

        merged_drop_materials = merged.setdefault("drop_materials", {})
        for slot_name in MATERIAL_LABELS:
            merged_drop_materials[slot_name] = max(0, int(merged_drop_materials.get(slot_name, 0))) + max(
                0,
                int(result.get("drop_materials", {}).get(slot_name, 0)),
            )

        merged_enchant_materials = merged.setdefault("drop_enchant_materials", {})
        for slot_name in ENCHANTMENT_MATERIAL_LABELS:
            merged_enchant_materials[slot_name] = max(
                0,
                int(merged_enchant_materials.get(slot_name, 0)),
            ) + max(
                0,
                int(result.get("drop_enchant_materials", {}).get(slot_name, 0)),
            )

        merged.setdefault("battle_logs", [])
        merged["battle_logs"].extend(deepcopy(result.get("battle_logs", [])))
        merged["battle_count"] = get_battle_count(merged) + get_battle_count(result)
        merged["total_turns"] = max(0, int(merged.get("total_turns", 0))) + max(
            0,
            int(result.get("total_turns", 0)),
        )
        merged["hp_after"] = int(result.get("hp_after", merged.get("hp_after", 0)))
        merged["returned_safe"] = bool(result.get("returned_safe", True))
        merged["downed"] = bool(result.get("downed", False) or not bool(result.get("returned_safe", True)))
        merged["return_reason"] = result.get("return_reason", merged.get("return_reason", "探索終了"))
        merged["return_info"] = deepcopy(
            result.get("return_info", merged.get("return_info"))
        )
        merged["potions_used"] = max(0, int(merged.get("potions_used", 0))) + max(
            0,
            int(result.get("potions_used", 0)),
        )
        merged["auto_potions_bought"] = max(0, int(merged.get("auto_potions_bought", 0))) + max(
            0,
            int(result.get("auto_potions_bought", 0)),
        )
        merged["auto_potion_refill_cost"] = max(
            0,
            int(merged.get("auto_potion_refill_cost", 0)),
        ) + max(
            0,
            int(result.get("auto_potion_refill_cost", 0)),
        )
        merged["auto_hp_heal_cost"] = max(
            0,
            int(merged.get("auto_hp_heal_cost", 0)),
        ) + max(
            0,
            int(result.get("auto_hp_heal_cost", 0)),
        )
        merged["auto_hp_restored"] = max(
            0,
            int(merged.get("auto_hp_restored", 0)),
        ) + max(
            0,
            int(result.get("auto_hp_restored", 0)),
        )
        merged["potions_after_claim"] = max(
            0,
            int(result.get("potions_after_claim", merged.get("potions_after_claim", 0))),
        )
        merged["armor_guards_used"] = max(0, int(merged.get("armor_guards_used", 0))) + max(
            0,
            int(result.get("armor_guards_used", 0)),
        )
        merged["armor_guards_total"] = max(0, int(merged.get("armor_guards_total", 0))) + max(
            0,
            int(result.get("armor_guards_total", 0)),
        )
        merged["armor_enchant_consumed"] = bool(
            merged.get("armor_enchant_consumed", False) or result.get("armor_enchant_consumed", False)
        )
        merged["auto_armor_reenchants"] = max(
            0,
            int(merged.get("auto_armor_reenchants", 0)),
        ) + max(
            0,
            int(result.get("auto_armor_reenchants", 0)),
        )
        merged["auto_repeat"] = False
        merged["exploration_runs"] = max(0, int(merged.get("exploration_runs", 0))) + 1
        return merged

    def get_mode_safe_line(self, max_hp: int, mode: Dict[str, Any], phase: str) -> int:
        ratio = float(mode.get(f"{phase}_hp_ratio", 0.0))
        min_hp = int(mode.get(f"{phase}_min_hp", 1))
        return self.battle_service.get_safe_return_line(
            max_hp,
            safe_return_ratio=ratio,
            safe_return_min_hp=min_hp,
        )

    def get_mode_risk_step(self, mode: Dict[str, Any], battle_number: int) -> int:
        ramp_start = max(1, int(mode.get("risk_ramp_start_battle", 11)))
        if battle_number < ramp_start:
            return 0

        ramp_interval = max(1, int(mode.get("risk_ramp_interval", 5)))
        return 1 + max(0, battle_number - ramp_start) // ramp_interval

    def get_prebattle_safety_profile(
        self,
        max_hp: int,
        mode: Dict[str, Any],
        battle_number: int,
    ) -> Dict[str, Any]:
        risk_step = self.get_mode_risk_step(mode, battle_number)
        base_ratio = max(0.0, float(mode.get("prebattle_hp_ratio", 0.0)))
        base_min_hp = max(1, int(mode.get("prebattle_min_hp", 1)))
        ratio_penalty = max(0.0, float(mode.get("risk_prebattle_hp_ratio_penalty", 0.0))) * risk_step
        min_hp_penalty = max(0, int(mode.get("risk_prebattle_min_hp_penalty", 0))) * risk_step
        ratio = max(0.0, base_ratio - ratio_penalty)
        min_hp = max(1, base_min_hp - min_hp_penalty)
        fatal_margin = max(0, int(mode.get("fatal_risk_last_hit_margin", 0)))
        fatal_margin += max(0, int(mode.get("risk_fatal_margin_bonus", 0))) * risk_step

        return {
            "minimum_post_hp": self.battle_service.get_safe_return_line(
                max_hp,
                safe_return_ratio=ratio,
                safe_return_min_hp=min_hp,
            ),
            "fatal_risk_last_hit_margin": fatal_margin,
            "conservative_damage_check": bool(mode.get("conservative_damage_check", False)),
            "risk_step": risk_step,
        }

    def apply_reward_rate(self, value: int, rate: float) -> int:
        value = max(0, int(value))
        if value <= 0:
            return 0
        return max(1, int(round(value * float(rate))))

    def apply_keep_rate(self, value: int, keep_rate: float) -> int:
        value = max(0, int(value))
        if value <= 0:
            return 0
        return max(1, int(math.ceil(value * float(keep_rate))))

    def get_area_exp_rate(self, area_name: str, player_level: int) -> float:
        area = AREAS.get(area_name, AREAS[DEFAULT_AREA])
        exp_rate = float(area.get("exp_rate", 1.0))
        level_scaling = area.get("level_exp_scaling")

        if not isinstance(level_scaling, dict):
            return max(0.0, exp_rate)

        threshold = max(0, int(level_scaling.get("threshold_level", 0)))
        if player_level <= threshold:
            exp_rate *= float(level_scaling.get("below_or_equal_rate", 1.0))
        else:
            exp_rate *= float(level_scaling.get("above_rate", 1.0))

        return max(0.0, exp_rate)

    def pick_monster(self, area_name: str) -> Dict[str, Any]:
        monsters = AREA_MONSTERS.get(area_name, AREA_MONSTERS[DEFAULT_AREA])
        names = [m["name"] for m in monsters]
        weights = [int(m.get("weight", 1)) for m in monsters]
        picked_name = random.choices(names, weights=weights, k=1)[0]

        for m in monsters:
            if m["name"] == picked_name:
                return dict(m)
        return dict(monsters[0])

    def _build_battle_log_entry(
        self,
        monster_data: Dict[str, Any],
        battle: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "monster": monster_data["name"],
            "turns": battle["turns"],
            "damage_taken": battle["damage_taken"],
            "won": battle["won"],
            "escaped": bool(battle.get("escaped", False)),
            "log": battle["log"],
            "turn_details": battle.get("turn_details", []),
            "drop_items": [],
            "auto_explore_stones": 0,
            "drop_materials": {slot_name: 0 for slot_name in MATERIAL_LABELS},
            "drop_enchant_materials": {
                slot_name: 0 for slot_name in ENCHANTMENT_MATERIAL_LABELS
            },
            "boss": bool(monster_data.get("boss", False)),
            "area_boss": bool(
                monster_data.get(
                    "area_boss",
                    bool(monster_data.get("boss", False)),
                )
            ),
            "encounter_type": str(monster_data.get("encounter_type", "normal") or "normal"),
        }

    def get_area_battle_scaling(self, area_name: str) -> Dict[str, float]:
        area = AREAS.get(area_name, AREAS[DEFAULT_AREA])
        raw_scaling = area.get("battle_scaling")
        if not isinstance(raw_scaling, dict):
            raw_scaling = {}

        return {
            "late_game_start": max(1, int(raw_scaling.get("late_game_start", BATTLE_LATE_GAME_START))),
            "late_progress_interval": max(1.0, float(raw_scaling.get("late_progress_interval", BOSS_BATTLE_INTERVAL))),
            "late_hp_multiplier": float(raw_scaling.get("late_hp_multiplier", BATTLE_LATE_GAME_HP_MULTIPLIER)),
            "late_hp_multiplier_per_step": float(
                raw_scaling.get("late_hp_multiplier_per_step", BATTLE_LATE_GAME_HP_MULTIPLIER_PER_STEP)
            ),
            "late_hp_acceleration": float(raw_scaling.get("late_hp_acceleration", BATTLE_LATE_GAME_HP_ACCELERATION)),
            "late_atk_entry_bonus": int(raw_scaling.get("late_atk_entry_bonus", BATTLE_LATE_GAME_ATK_ENTRY_BONUS)),
            "late_atk_bonus_per_step": float(
                raw_scaling.get("late_atk_bonus_per_step", BATTLE_LATE_GAME_ATK_BONUS_PER_STEP)
            ),
            "late_atk_acceleration": float(
                raw_scaling.get("late_atk_acceleration", BATTLE_LATE_GAME_ATK_ACCELERATION)
            ),
            "late_def_entry_bonus": int(raw_scaling.get("late_def_entry_bonus", BATTLE_LATE_GAME_DEF_ENTRY_BONUS)),
            "late_def_bonus_per_step": float(
                raw_scaling.get("late_def_bonus_per_step", BATTLE_LATE_GAME_DEF_BONUS_PER_STEP)
            ),
            "late_def_acceleration": float(
                raw_scaling.get("late_def_acceleration", BATTLE_LATE_GAME_DEF_ACCELERATION)
            ),
            "late_exp_multiplier": float(
                raw_scaling.get("late_exp_multiplier", BATTLE_LATE_GAME_EXP_MULTIPLIER)
            ),
            "late_exp_multiplier_per_step": float(
                raw_scaling.get(
                    "late_exp_multiplier_per_step",
                    BATTLE_LATE_GAME_EXP_MULTIPLIER_PER_STEP,
                )
            ),
            "late_exp_acceleration": float(
                raw_scaling.get("late_exp_acceleration", BATTLE_LATE_GAME_EXP_ACCELERATION)
            ),
            "late_gold_multiplier": float(
                raw_scaling.get("late_gold_multiplier", BATTLE_LATE_GAME_GOLD_MULTIPLIER)
            ),
            "late_gold_multiplier_per_step": float(
                raw_scaling.get(
                    "late_gold_multiplier_per_step",
                    BATTLE_LATE_GAME_GOLD_MULTIPLIER_PER_STEP,
                )
            ),
            "late_gold_acceleration": float(
                raw_scaling.get("late_gold_acceleration", BATTLE_LATE_GAME_GOLD_ACCELERATION)
            ),
            "late_drop_rate_bonus": float(
                raw_scaling.get("late_drop_rate_bonus", BATTLE_LATE_GAME_DROP_RATE_BONUS)
            ),
            "late_drop_rate_bonus_per_step": float(
                raw_scaling.get(
                    "late_drop_rate_bonus_per_step",
                    BATTLE_LATE_GAME_DROP_RATE_BONUS_PER_STEP,
                )
            ),
            "late_drop_rate_bonus_acceleration": float(
                raw_scaling.get(
                    "late_drop_rate_bonus_acceleration",
                    BATTLE_LATE_GAME_DROP_RATE_BONUS_ACCELERATION,
                )
            ),
            "late_resource_bonus": float(
                raw_scaling.get("late_resource_bonus", BATTLE_LATE_GAME_RESOURCE_BONUS)
            ),
            "late_resource_bonus_per_step": float(
                raw_scaling.get(
                    "late_resource_bonus_per_step",
                    BATTLE_LATE_GAME_RESOURCE_BONUS_PER_STEP,
                )
            ),
            "late_resource_bonus_acceleration": float(
                raw_scaling.get(
                    "late_resource_bonus_acceleration",
                    BATTLE_LATE_GAME_RESOURCE_BONUS_ACCELERATION,
                )
            ),
        }

    def _build_late_reward_scaling(
        self,
        battle_scaling: Dict[str, float],
        late_progress: float,
    ) -> Dict[str, float]:
        safe_late_progress = max(0.0, float(late_progress))
        late_progress_sq = safe_late_progress ** 2
        return {
            "exp_multiplier": max(
                0.0,
                float(battle_scaling["late_exp_multiplier"])
                + (safe_late_progress * float(battle_scaling["late_exp_multiplier_per_step"]))
                + (late_progress_sq * float(battle_scaling["late_exp_acceleration"])),
            ),
            "gold_multiplier": max(
                0.0,
                float(battle_scaling["late_gold_multiplier"])
                + (safe_late_progress * float(battle_scaling["late_gold_multiplier_per_step"]))
                + (late_progress_sq * float(battle_scaling["late_gold_acceleration"])),
            ),
            "drop_rate_bonus": max(
                0.0,
                float(battle_scaling["late_drop_rate_bonus"])
                + (safe_late_progress * float(battle_scaling["late_drop_rate_bonus_per_step"]))
                + (late_progress_sq * float(battle_scaling["late_drop_rate_bonus_acceleration"])),
            ),
            "resource_bonus": max(
                0.0,
                float(battle_scaling["late_resource_bonus"])
                + (safe_late_progress * float(battle_scaling["late_resource_bonus_per_step"]))
                + (late_progress_sq * float(battle_scaling["late_resource_bonus_acceleration"])),
            ),
        }

    def get_battle_growth(self, battle_number: int, area_name: str) -> Dict[str, float]:
        if battle_number <= 0:
            return {
                "progress_units": 0.0,
                "growth_curve": 0.0,
                "late_progress": 0.0,
            }

        battle_scaling = self.get_area_battle_scaling(area_name)
        progress_units = max(0.0, (battle_number - 1) / float(BATTLE_ESCALATION_INTERVAL))
        growth_curve = progress_units + ((progress_units ** 2) * BATTLE_GROWTH_ACCELERATION)
        late_progress = max(
            0.0,
            (battle_number - int(battle_scaling["late_game_start"])) / float(battle_scaling["late_progress_interval"]),
        )
        return {
            "progress_units": progress_units,
            "growth_curve": growth_curve,
            "late_progress": late_progress,
        }

    def is_elite_battle(self, battle_number: int) -> bool:
        return (
            battle_number > 0
            and (battle_number % BATTLE_ESCALATION_INTERVAL) == 0
            and not self.is_boss_battle(battle_number)
        )

    def is_boss_battle(self, battle_number: int) -> bool:
        return battle_number > 0 and (battle_number % BOSS_BATTLE_INTERVAL) == 0

    def scale_monster_for_battle(
        self,
        monster_data: Dict[str, Any],
        battle_number: int,
        area_name: str,
        *,
        force_boss: bool = False,
    ) -> Dict[str, Any]:
        scaled = dict(monster_data)
        growth = self.get_battle_growth(battle_number, area_name)
        battle_scaling = self.get_area_battle_scaling(area_name)
        growth_curve = float(growth["growth_curve"])
        late_progress = float(growth["late_progress"])
        is_elite = self.is_elite_battle(battle_number) and not force_boss
        is_boss = force_boss or self.is_boss_battle(battle_number)

        base_hp_scale = 1.0 + (growth_curve * BATTLE_HP_SCALE_PER_GROWTH)
        base_atk_bonus = math.ceil(growth_curve * BATTLE_ATK_BONUS_PER_GROWTH)
        base_def_bonus = math.ceil(growth_curve * BATTLE_DEF_BONUS_PER_GROWTH)
        base_exp_scale = 1.0 + (growth_curve * BATTLE_EXP_SCALE_PER_GROWTH)
        base_gold_scale = 1.0 + (growth_curve * BATTLE_GOLD_SCALE_PER_GROWTH)
        base_drop_rate = float(scaled.get("drop_rate", 0.0)) + (growth_curve * BATTLE_DROP_RATE_PER_GROWTH)
        legendary_drop_rate_multiplier_bonus = growth_curve * BATTLE_DROP_RATE_PER_GROWTH

        scaled["hp"] = max(1, int(round(int(scaled.get("hp", 1)) * base_hp_scale)))
        scaled["atk"] = max(1, int(scaled.get("atk", 1)) + base_atk_bonus)
        scaled["def"] = max(0, int(scaled.get("def", 0)) + base_def_bonus)
        scaled["speed"] = max(1, int(scaled.get("speed", 100) or 100))
        scaled["exp"] = max(1, int(round(int(scaled.get("exp", 0)) * base_exp_scale)))
        scaled["gold"] = max(1, int(round(int(scaled.get("gold", 0)) * base_gold_scale)))
        scaled["drop_rate"] = min(0.95, base_drop_rate)
        scaled["late_resource_bonus"] = 0
        scaled["legendary_drop_rate_multiplier_bonus"] = max(
            0.0,
            float(legendary_drop_rate_multiplier_bonus),
        )

        if battle_number >= int(battle_scaling["late_game_start"]):
            late_hp_multiplier = (
                float(battle_scaling["late_hp_multiplier"])
                + (late_progress * float(battle_scaling["late_hp_multiplier_per_step"]))
                + ((late_progress ** 2) * float(battle_scaling["late_hp_acceleration"]))
            )
            late_atk_bonus = (
                int(battle_scaling["late_atk_entry_bonus"])
                + math.ceil(late_progress * float(battle_scaling["late_atk_bonus_per_step"]))
                + math.ceil((late_progress ** 2) * float(battle_scaling["late_atk_acceleration"]))
            )
            late_def_bonus = (
                int(battle_scaling["late_def_entry_bonus"])
                + math.ceil(late_progress * float(battle_scaling["late_def_bonus_per_step"]))
                + math.ceil((late_progress ** 2) * float(battle_scaling["late_def_acceleration"]))
            )
            late_reward_scaling = self._build_late_reward_scaling(
                battle_scaling,
                late_progress,
            )

            scaled["hp"] = max(1, int(round(int(scaled.get("hp", 1)) * late_hp_multiplier)))
            scaled["atk"] = max(1, int(scaled.get("atk", 1)) + late_atk_bonus)
            scaled["def"] = max(0, int(scaled.get("def", 0)) + late_def_bonus)
            scaled["exp"] = max(
                1,
                int(round(int(scaled.get("exp", 0)) * float(late_reward_scaling["exp_multiplier"]))),
            )
            scaled["gold"] = max(
                1,
                int(round(int(scaled.get("gold", 0)) * float(late_reward_scaling["gold_multiplier"]))),
            )
            scaled["drop_rate"] = min(
                0.95,
                float(scaled.get("drop_rate", 0.0)) + float(late_reward_scaling["drop_rate_bonus"]),
            )
            scaled["late_resource_bonus"] = max(
                0,
                int(math.floor(float(late_reward_scaling["resource_bonus"]))),
            )
            scaled["legendary_drop_rate_multiplier_bonus"] = max(
                0.0,
                float(scaled.get("legendary_drop_rate_multiplier_bonus", 0.0))
                + float(late_reward_scaling["drop_rate_bonus"]),
            )

        if is_elite:
            scaled["name"] = f"精鋭{scaled['name']}"
            scaled["hp"] = max(1, int(round(int(scaled.get("hp", 1)) * ELITE_MONSTER_HP_SCALE)))
            scaled["atk"] = max(1, int(scaled.get("atk", 1)) + ELITE_MONSTER_ATK_BONUS)
            scaled["def"] = max(0, int(scaled.get("def", 0)) + ELITE_MONSTER_DEF_BONUS)
            scaled["exp"] = max(1, int(round(int(scaled.get("exp", 0)) * ELITE_MONSTER_EXP_SCALE)))
            scaled["gold"] = max(1, int(round(int(scaled.get("gold", 0)) * ELITE_MONSTER_GOLD_SCALE)))
            scaled["drop_rate"] = min(0.95, float(scaled.get("drop_rate", 0.0)) + ELITE_MONSTER_DROP_RATE_BONUS)

        if is_boss:
            scaled["name"] = f"ボス{scaled['name']}"
            scaled["hp"] = max(1, int(round(int(scaled.get("hp", 1)) * BOSS_MONSTER_HP_SCALE)))
            scaled["atk"] = max(1, int(scaled.get("atk", 1)) + BOSS_MONSTER_ATK_BONUS)
            scaled["def"] = max(0, int(scaled.get("def", 0)) + BOSS_MONSTER_DEF_BONUS)
            scaled["exp"] = max(1, int(round(int(scaled.get("exp", 0)) * BOSS_MONSTER_EXP_SCALE)))
            scaled["gold"] = max(1, int(round(int(scaled.get("gold", 0)) * BOSS_MONSTER_GOLD_SCALE)))
            scaled["drop_rate"] = min(0.95, float(scaled.get("drop_rate", 0.0)) + BOSS_MONSTER_DROP_RATE_BONUS)

        scaled["battle_number"] = battle_number
        scaled["battle_stage"] = int(growth["progress_units"])
        scaled["growth_curve"] = growth_curve
        scaled["elite"] = is_elite
        scaled["boss"] = is_boss
        scaled["area_boss"] = is_boss and not force_boss
        scaled["encounter_type"] = "boss" if is_boss else "elite" if is_elite else "normal"
        return scaled

    def _get_diagnosis_stage_start_hp(
        self,
        current_hp: int,
        max_hp: int,
        mode: Dict[str, Any],
        battle_number: int,
    ) -> int:
        if battle_number <= 1:
            return max(1, min(max_hp, current_hp))

        fatigue_multiplier = 1.0
        if battle_number >= BOSS_BATTLE_INTERVAL:
            fatigue_multiplier = 1.30
        elif battle_number >= BATTLE_ESCALATION_INTERVAL:
            fatigue_multiplier = 1.10

        minimum_hp = max(
            int(mode.get("prebattle_min_hp", 1)),
            int(round(max_hp * float(mode.get("prebattle_hp_ratio", 0.0)) * fatigue_multiplier)),
        )
        return max(1, min(max_hp, current_hp, minimum_hp))

    def _get_diagnosis_stage_supplies(
        self,
        available_potions: int,
        available_guards: int,
        battle_number: int,
        mode: Dict[str, Any],
    ) -> Tuple[int, int]:
        potion_factor = 1.0
        guard_factor = 1.0
        if battle_number >= BOSS_BATTLE_INTERVAL:
            potion_factor = 0.4
            guard_factor = 0.5
        elif battle_number >= BATTLE_ESCALATION_INTERVAL:
            potion_factor = 0.7
            guard_factor = 0.75

        return (
            max(
                0,
                int(
                    math.floor(
                        self.get_mode_usable_potions(available_potions, mode)
                        * potion_factor
                    )
                ),
            ),
            max(0, int(math.floor(max(0, available_guards) * guard_factor))),
        )

    def _classify_diagnosis_risk(
        self,
        estimate: Dict[str, Any],
        *,
        max_hp: int,
        safe_return_line: int,
    ) -> Dict[str, Any]:
        predicted_damage = max(0, int(estimate.get("predicted_damage", 0)))
        hp_after = max(0, int(estimate.get("player_hp_after", 0)))
        potions_used = max(0, int(estimate.get("potions_used", 0)))
        guards_used = max(0, int(estimate.get("guards_used", 0)))

        if not bool(estimate.get("can_win", False)) or hp_after <= 0:
            return {"severity": 3, "label": "非推奨", "reason": "勝ち筋が薄い"}
        if guards_used > 0:
            return {"severity": 2, "label": "高危険", "reason": "致死耐性前提になる"}
        if hp_after <= safe_return_line:
            return {"severity": 2, "label": "高危険", "reason": "撃破後の残HPが低い"}
        if potions_used > 0 or predicted_damage >= int(max_hp * 0.5):
            return {"severity": 1, "label": "注意", "reason": "被ダメが重い"}
        return {"severity": 0, "label": "安定", "reason": "大崩れしにくい"}

    def _build_diagnosis_stage(
        self,
        u: Dict[str, Any],
        area_name: str,
        mode: Dict[str, Any],
        *,
        battle_number: int,
        label: str,
    ) -> Dict[str, Any]:
        monsters = AREA_MONSTERS.get(area_name, AREA_MONSTERS[DEFAULT_AREA])
        current_hp = max(1, int(u.get("hp", DEFAULT_MAX_HP)))
        max_hp = max(1, int(u.get("max_hp", DEFAULT_MAX_HP)))
        stage_start_hp = self._get_diagnosis_stage_start_hp(current_hp, max_hp, mode, battle_number)
        player_stats = self.user_service.get_player_stats(u, mode["key"])
        player_atk = int(player_stats.get("atk", 1))
        player_def = int(player_stats.get("def", 0))
        crit_rate, crit_damage = self.user_service.get_weapon_crit_stats(u)
        active_skills = self.user_service.get_selected_active_skills(u)
        potion_heal = self.get_potion_heal_amount(max_hp)
        available_potions, available_guards = self._get_diagnosis_stage_supplies(
            int(u.get("potions", 0)),
            self.user_service.get_armor_lethal_guard_count(u),
            battle_number,
            mode,
        )
        safe_return_line = self.battle_service.get_safe_return_line(max_hp)

        selected_monster: Optional[Dict[str, Any]] = None
        selected_estimate: Optional[Dict[str, Any]] = None
        selected_risk: Optional[Dict[str, Any]] = None
        selected_key: Optional[Tuple[int, int, int, int]] = None

        for monster_data in monsters:
            scaled_monster = self.scale_monster_for_battle(monster_data, battle_number, area_name)
            estimate = self.battle_service.estimate_battle(
                stage_start_hp,
                player_atk,
                player_def,
                scaled_monster,
                max_hp=max_hp,
                crit_chance=crit_rate,
                crit_damage_multiplier=crit_damage,
                potion_heal=potion_heal,
                available_potions=available_potions,
                available_guards=available_guards,
                conservative_damage_check=bool(mode.get("conservative_damage_check", False)),
                active_skills=active_skills,
                player_speed=int(player_stats.get("speed", 100)),
                enemy_speed=int(scaled_monster.get("speed", 100)),
            )
            risk = self._classify_diagnosis_risk(
                estimate,
                max_hp=max_hp,
                safe_return_line=safe_return_line,
            )
            sort_key = (
                int(risk["severity"]),
                int(estimate.get("predicted_damage", 0)),
                int(scaled_monster.get("atk", 0)),
                int(scaled_monster.get("hp", 0)),
            )
            if selected_key is None or sort_key > selected_key:
                selected_monster = scaled_monster
                selected_estimate = estimate
                selected_risk = risk
                selected_key = sort_key

        return {
            "label": label,
            "battle_number": battle_number,
            "start_hp": stage_start_hp,
            "monster": selected_monster or {"name": "?"},  # defensive fallback
            "estimate": selected_estimate or {},
            "risk": selected_risk or {"severity": 0, "label": "安定", "reason": "大崩れしにくい"},
        }

    def _build_diagnosis_reward_estimate(
        self,
        u: Dict[str, Any],
        area_name: str,
        mode: Dict[str, Any],
    ) -> Dict[str, Any]:
        area = AREAS.get(area_name, AREAS[DEFAULT_AREA])
        monsters = AREA_MONSTERS.get(area_name, AREA_MONSTERS[DEFAULT_AREA])
        total_weight = max(1, sum(max(1, int(monster.get("weight", 1))) for monster in monsters))
        player_level = self.user_service.get_adventure_level(u)
        area_exp_rate = self.get_area_exp_rate(area_name, player_level)
        area_gold_rate = float(area.get("gold_rate", 1.0))
        ring_exp_rate, ring_gold_rate, ring_drop_bonus = self.user_service.get_ring_exploration_rates(u)
        equipment_enabled = str(area.get("specialty", "") or "").strip() != "武器強化素材"

        weighted_exp = 0.0
        weighted_gold = 0.0
        weighted_drop_rate = 0.0
        for monster_data in monsters:
            weight = max(1, int(monster_data.get("weight", 1)))
            scaled_monster = self.scale_monster_for_battle(monster_data, 1, area_name)
            weighted_exp += (
                float(scaled_monster.get("exp", 0))
                * area_exp_rate
                * float(mode.get("exp_rate", 1.0))
                * ring_exp_rate
                * weight
            )
            weighted_gold += (
                float(scaled_monster.get("gold", 0))
                * area_gold_rate
                * float(mode.get("gold_rate", 1.0))
                * ring_gold_rate
                * weight
            )
            if equipment_enabled:
                weighted_drop_rate += (
                    max(
                        0.0,
                        min(
                            0.95,
                            float(scaled_monster.get("drop_rate", 0.0))
                            + float(area.get("drop_rate_bonus", 0.0))
                            + ring_drop_bonus,
                        ),
                    )
                    * weight
                )

        encounters = area.get("encounters", (4, 6))
        if not isinstance(encounters, tuple) or len(encounters) != 2:
            encounters = (4, 6)

        return {
            "encounters_min": max(1, int(encounters[0])),
            "encounters_max": max(max(1, int(encounters[0])), int(encounters[1])),
            "avg_exp": max(0, int(round(weighted_exp / total_weight))),
            "avg_gold": max(0, int(round(weighted_gold / total_weight))),
            "avg_drop_rate_pct": max(0, int(round((weighted_drop_rate / total_weight) * 100))),
        }

    def build_exploration_diagnosis(
        self,
        u: Dict[str, Any],
        request_text: Optional[str],
    ) -> Dict[str, Any]:
        area_name, mode, _ = self.parse_exploration_request(request_text)
        current_hp = max(0, int(u.get("hp", DEFAULT_MAX_HP)))
        max_hp = max(1, int(u.get("max_hp", DEFAULT_MAX_HP)))
        player_stats = self.user_service.get_player_stats(u, mode["key"])
        diagnosis_stages = [
            self._build_diagnosis_stage(u, area_name, mode, battle_number=1, label="初戦"),
            self._build_diagnosis_stage(
                u,
                area_name,
                mode,
                battle_number=BATTLE_ESCALATION_INTERVAL,
                label="精鋭想定",
            ),
            self._build_diagnosis_stage(
                u,
                area_name,
                mode,
                battle_number=BOSS_BATTLE_INTERVAL,
                label="ボス想定",
            ),
        ]
        most_dangerous_stage = max(
            diagnosis_stages,
            key=lambda stage: (
                int(stage["risk"]["severity"]),
                int(stage["battle_number"]),
            ),
        )
        reward_estimate = self._build_diagnosis_reward_estimate(u, area_name, mode)
        return {
            "area": area_name,
            "mode": mode,
            "player": {
                "hp": current_hp,
                "max_hp": max_hp,
                "atk": int(player_stats.get("atk", 0)),
                "def": int(player_stats.get("def", 0)),
                "speed": int(player_stats.get("speed", 0)),
                "potions": max(0, int(u.get("potions", 0))),
                "guards": self.user_service.get_armor_lethal_guard_count(u),
            },
            "danger_label": str(most_dangerous_stage["risk"]["label"]),
            "danger_reason": (
                "初戦からボス想定まで大崩れしにくい"
                if int(most_dangerous_stage["risk"]["severity"]) <= 0
                else (
                    f"{most_dangerous_stage['label']}の"
                    f"{most_dangerous_stage['monster'].get('name', '?')}が"
                    f"{most_dangerous_stage['risk']['reason']}"
                )
            ),
            "stages": diagnosis_stages,
            "reward_estimate": reward_estimate,
        }

    def calculate_exploration_duration(self, total_turns: int) -> int:
        if EXPLORATION_DURATION_OVERRIDE_SEC is not None:
            override_sec = max(0, int(EXPLORATION_DURATION_OVERRIDE_SEC))
            if override_sec > 0:
                return override_sec
        return max(0, int(total_turns) * EXPLORATION_SECONDS_PER_TURN)

    def simulate_exploration_result(
        self,
        u: Dict[str, Any],
        area_name: str,
        mode: Dict[str, Any],
        preparation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        start_hp = int(u.get("hp", DEFAULT_MAX_HP))
        current_hp = start_hp
        max_hp = int(u.get("max_hp", DEFAULT_MAX_HP))

        active_preparation = preparation if isinstance(preparation, dict) else {}
        player_stats = dict(self.user_service.get_player_stats(u, mode["key"]))
        player_stats["atk"] = max(
            1,
            int(player_stats.get("atk", 1)) + max(0, int(active_preparation.get("atk", 0))),
        )
        player_stats["def"] = max(
            0,
            int(player_stats.get("def", 0)) + max(0, int(active_preparation.get("def", 0))),
        )
        player_stats["speed"] = max(
            1,
            int(player_stats.get("speed", 100)) + max(0, int(active_preparation.get("speed", 0))),
        )
        player_atk = int(player_stats.get("atk", 1))
        player_def = int(player_stats.get("def", 0))
        weapon_crit_rate, weapon_crit_multiplier = self.user_service.get_weapon_crit_stats(u)
        active_skills = self.user_service.get_selected_active_skills(u)
        potion_heal = self.get_potion_heal_amount(max_hp)
        armor_guards_total = self.user_service.get_armor_lethal_guard_count(u)
        armor_guards_left = armor_guards_total
        ring_exp_rate, ring_gold_rate, ring_drop_bonus = self.user_service.get_ring_exploration_rates(u)
        ring_exp_rate *= max(0.0, float(active_preparation.get("exp_rate", 1.0)))
        ring_gold_rate *= max(0.0, float(active_preparation.get("gold_rate", 1.0)))
        ring_drop_bonus += max(0.0, float(active_preparation.get("drop_bonus", 0.0)))

        kills: List[Dict[str, Any]] = []
        drop_items: List[Dict[str, Any]] = []
        auto_explore_stones = 0
        drop_materials: Dict[str, int] = {slot_name: 0 for slot_name in MATERIAL_LABELS}
        drop_enchant_materials: Dict[str, int] = {slot_name: 0 for slot_name in ENCHANTMENT_MATERIAL_LABELS}
        battle_logs: List[Dict[str, Any]] = []
        total_exp = 0
        total_gold = 0

        area = AREAS.get(area_name, AREAS[DEFAULT_AREA])
        player_level = self.user_service.get_adventure_level(u)
        area_exp_rate = self.get_area_exp_rate(area_name, player_level)
        gold_rate = float(area.get("gold_rate", 1.0))

        return_reason = "探索終了"
        return_info = build_return_info(
            phase=RETURN_PHASE_COMPLETE,
            reason="探索終了",
            raw_reason="探索終了",
        )
        returned_safe = True
        downed = False
        armor_enchant_consumed = False

        available_potions = int(u.get("potions", 0))
        usable_potions = self.get_mode_usable_potions(available_potions, mode)
        potions_used = 0
        battle_count = 0
        total_turns = 0

        while current_hp > 0 and battle_count < MAX_BATTLES_PER_EXPLORATION:
            upcoming_battle = battle_count + 1
            monster_data = self.scale_monster_for_battle(
                self.pick_monster(area_name),
                upcoming_battle,
                area_name,
            )
            prebattle_safety = self.get_prebattle_safety_profile(max_hp, mode, upcoming_battle)

            while not self.battle_service.should_start_battle(
                current_hp,
                player_atk,
                player_def,
                monster_data,
                max_hp,
                crit_chance=weapon_crit_rate,
                crit_damage_multiplier=weapon_crit_multiplier,
                potion_heal=potion_heal,
                available_potions=self.get_remaining_potions(usable_potions, potions_used),
                available_guards=armor_guards_left,
                minimum_post_hp=int(prebattle_safety["minimum_post_hp"]),
                fatal_risk_last_hit_margin=int(prebattle_safety["fatal_risk_last_hit_margin"]),
                conservative_damage_check=bool(prebattle_safety["conservative_damage_check"]),
                active_skills=active_skills,
                player_speed=int(player_stats.get("speed", 100)),
                enemy_speed=int(monster_data.get("speed", 100)),
            ):
                can_use_potion = (
                    self.get_remaining_potions(usable_potions, potions_used) > 0
                    and current_hp < max_hp
                )

                if not can_use_potion:
                    return_reason = (
                        f"第{upcoming_battle}戦の {monster_data['name']} を危険と判断して帰還"
                    )
                    return_info = build_return_info(
                        battle_number=upcoming_battle,
                        monster=monster_data["name"],
                        phase=RETURN_PHASE_PREBATTLE,
                        reason="危険判断で帰還",
                        raw_reason=return_reason,
                    )
                    break

                before_hp = current_hp
                current_hp = min(max_hp, current_hp + potion_heal)
                potions_used += 1

                battle_logs.append({
                    "monster": "ポーション使用",
                    "turns": 0,
                    "damage_taken": 0,
                    "won": True,
                    "log": [
                        f"危険回避でポーション使用: HP {before_hp} → {current_hp} "
                        f"({potions_used}/{max(1, usable_potions)})"
                    ],
                })

            if return_reason != "探索終了":
                break

            battle = self.battle_service.simulate_battle(
                current_hp,
                player_atk,
                player_def,
                monster_data,
                max_hp=max_hp,
                crit_chance=weapon_crit_rate,
                crit_damage_multiplier=weapon_crit_multiplier,
                potion_heal=potion_heal,
                available_potions=self.get_remaining_potions(usable_potions, potions_used),
                available_guards=armor_guards_left,
                active_skills=active_skills,
                player_speed=int(player_stats.get("speed", 100)),
                enemy_speed=int(monster_data.get("speed", 100)),
            )
            battle_count += 1
            current_hp = int(battle["player_hp_after"])
            potions_used += int(battle.get("potions_used", 0))
            armor_guards_left = int(battle.get("guards_left", armor_guards_left))
            total_turns += max(0, int(battle.get("turns", 0)))

            battle_log_entry = self._build_battle_log_entry(monster_data, battle)

            if bool(battle.get("escaped", False)):
                battle_logs.append(battle_log_entry)
                armor_enchant_consumed = True
                return_reason = (
                    f"第{battle_count}戦の {monster_data['name']} で致死耐性が発動したため緊急帰還"
                )
                return_info = build_return_info(
                    battle_number=battle_count,
                    monster=monster_data["name"],
                    phase=RETURN_PHASE_BATTLE_ESCAPE,
                    reason="致死耐性発動で緊急帰還",
                    raw_reason=return_reason,
                )
                break

            if not battle["won"]:
                battle_logs.append(battle_log_entry)
                current_hp = 0
                returned_safe = False
                downed = True
                return_reason = f"第{battle_count}戦の {monster_data['name']} に倒された"
                return_info = build_return_info(
                    battle_number=battle_count,
                    monster=monster_data["name"],
                    phase=RETURN_PHASE_DEFEAT,
                    reason="敗北",
                    raw_reason=return_reason,
                )
                break

            kills.append(monster_data)
            total_exp += self.apply_reward_rate(
                int(monster_data.get("exp", 0)),
                float(mode.get("exp_rate", 1.0))
                * area_exp_rate
                * ring_exp_rate
                * float(EXP_GAIN_MULTIPLIER),
            )
            total_gold += self.apply_reward_rate(
                max(1, int(int(monster_data.get("gold", 0)) * gold_rate)),
                float(mode.get("gold_rate", 1.0)) * ring_gold_rate,
            )

            eq = self.item_service.roll_equipment_for_monster(
                area_name,
                monster_data,
                extra_drop_rate_bonus=ring_drop_bonus,
                u=u,
            )
            if eq:
                drop_items.append(eq)
                battle_log_entry["drop_items"].append(deepcopy(eq))

            material_drop = self.item_service.get_material_drop_for_monster(
                area_name,
                monster_data,
                chance_bonus=ring_drop_bonus,
            )
            for slot_name, quantity in material_drop.items():
                safe_quantity = max(0, int(quantity))
                drop_materials[slot_name] = drop_materials.get(slot_name, 0) + safe_quantity
                battle_log_entry["drop_materials"][slot_name] = (
                    battle_log_entry["drop_materials"].get(slot_name, 0) + safe_quantity
                )

            enchant_drop = self.item_service.get_enchantment_drop_for_monster(
                area_name,
                monster_data,
                chance_bonus=ring_drop_bonus,
            )
            for slot_name, quantity in enchant_drop.items():
                safe_quantity = max(0, int(quantity))
                drop_enchant_materials[slot_name] = (
                    drop_enchant_materials.get(slot_name, 0) + safe_quantity
                )
                battle_log_entry["drop_enchant_materials"][slot_name] = (
                    battle_log_entry["drop_enchant_materials"].get(slot_name, 0) + safe_quantity
                )

            stone_drop = self.item_service.roll_auto_explore_stone()
            if stone_drop > 0 and auto_explore_stones <= 0:
                auto_explore_stones = 1
                battle_log_entry["auto_explore_stones"] = 1

            battle_logs.append(battle_log_entry)

            while self.battle_service.should_return_after_battle(
                current_hp,
                max_hp,
                safe_return_ratio=float(mode.get("postbattle_hp_ratio", 0.0)),
                safe_return_min_hp=int(mode.get("postbattle_min_hp", 1)),
            ):
                can_use_potion = (
                    self.get_remaining_potions(usable_potions, potions_used) > 0
                    and current_hp < max_hp
                )

                if not can_use_potion:
                    return_reason = (
                        f"第{battle_count}戦の {monster_data['name']} 戦後にHP低下のため安全帰還"
                    )
                    return_info = build_return_info(
                        battle_number=battle_count,
                        monster=monster_data["name"],
                        phase=RETURN_PHASE_POSTBATTLE,
                        reason="HP低下のため安全帰還",
                        raw_reason=return_reason,
                    )
                    break

                before_hp = current_hp
                current_hp = min(max_hp, current_hp + potion_heal)
                potions_used += 1

                battle_logs.append({
                    "monster": "ポーション使用",
                    "turns": 0,
                    "damage_taken": 0,
                    "won": True,
                    "log": [
                        f"戦闘後ポーション使用: HP {before_hp} → {current_hp} "
                        f"({potions_used}/{max(1, usable_potions)})"
                    ],
                })

            if return_reason != "探索終了":
                break

        if battle_count >= MAX_BATTLES_PER_EXPLORATION and return_reason == "探索終了":
            return_reason = (
                f"第{battle_count}戦の {monster_data['name']} 撃破後、"
                f"戦闘回数が{MAX_BATTLES_PER_EXPLORATION}回に達したため帰還"
            )
            return_info = build_return_info(
                battle_number=battle_count,
                monster=monster_data["name"],
                phase=RETURN_PHASE_BATTLE_CAP,
                reason="戦闘回数上限で帰還",
                raw_reason=return_reason,
            )

        self._grant_beginner_equipment_set(area_name, player_level, drop_items, battle_logs)

        total_damage = max(0, start_hp - current_hp)

        return {
            "area": area_name if area_name in AREAS else DEFAULT_AREA,
            "mode": mode["key"],
            "kills": kills,
            "exp": total_exp,
            "gold": total_gold,
            "damage": total_damage,
            "drop_items": drop_items,
            "auto_explore_stones": auto_explore_stones,
            "drop_materials": drop_materials,
            "drop_enchant_materials": drop_enchant_materials,
            "battle_logs": battle_logs,
            "battle_count": battle_count,
            "total_turns": total_turns,
            "hp_after": current_hp,
            "returned_safe": returned_safe,
            "downed": downed,
            "return_reason": return_reason,
            "return_info": return_info,
            "potions_used": potions_used,
            "armor_guards_used": max(0, armor_guards_total - armor_guards_left),
            "armor_guards_total": armor_guards_total,
            "armor_enchant_consumed": armor_enchant_consumed,
            "auto_repeat": False,
            "exploration_preparation": deepcopy(active_preparation),
        }

    def _build_auto_repeat_locked_message(self, u: Dict[str, Any]) -> str:
        progress = self.user_service.get_auto_repeat_progress(u)
        if progress.get("unlocked", False):
            return "は自動周回を開始できます。"

        segments: List[str] = []
        if not bool(progress.get("route_unlocked", False)):
            segments.append("星影の祭壇ボス初回撃破")
        segments.append(
            f"欠片 {int(progress.get('fragments', 0))}/{int(progress.get('required_fragments', 0))}"
        )
        return "はまだ自動周回を開始できません。 " + " / ".join(segments)

    def _build_auto_repeat_stop_reason(
        self,
        *,
        auto_repeat_requested: bool,
        session_active: bool,
        downed: bool,
        run_count: int,
        next_result_downed: bool,
    ) -> str:
        if not session_active:
            return ""
        if downed:
            return "戦闘不能で自動周回停止"
        if run_count >= MAX_AUTO_REPEAT_EXPLORATIONS:
            return f"自動周回上限 {MAX_AUTO_REPEAT_EXPLORATIONS} 回で停止"
        if auto_repeat_requested and next_result_downed:
            return "次回探索が危険なため自動周回停止"
        if not auto_repeat_requested:
            return "手動停止"
        return "探索終了"

    def start_exploration(self, username: str, area_text: Optional[str]) -> Tuple[bool, str]:
        u = self.user_service.get_user(username)

        if u.get("down", False):
            return False, "は戦闘不能です。 `!蘇生` で復帰してください。"

        explore = u.get("explore", {})
        if explore.get("state") == "exploring":
            remain = int(explore.get("ends_at", 0) - now_ts())
            if remain > 0:
                area_name = explore.get("area", DEFAULT_AREA)
                if area_name not in AREAS:
                    area_name = DEFAULT_AREA
                return False, f"はすでに {area_name} を探索中です。残り {self.user_service.format_duration(remain)}"
            return False, "は探索完了済みです。 `!探索結果` で受け取ってください。"

        area_name, mode, auto_repeat = self.parse_exploration_request(area_text)
        if auto_repeat and not self.user_service.is_auto_repeat_unlocked(u):
            return False, self._build_auto_repeat_locked_message(u)

        preparation = self.user_service.consume_exploration_preparations(u)
        result = self.simulate_exploration_result(u, area_name, mode, preparation=preparation)
        result["auto_repeat"] = bool(auto_repeat)
        if auto_repeat:
            u["auto_repeat_result"] = self._build_auto_repeat_result_template(area_name, mode["key"])
        elif u.get("auto_repeat_result") is not None:
            u["auto_repeat_result"] = None
        u["explore"], duration = self._build_active_explore_state(
            area_name,
            mode,
            result,
            auto_repeat=auto_repeat,
        )

        preparation_note = ""
        if preparation.get("summary"):
            preparation_note = f" / 準備:{preparation['summary']}"

        return True, (
            f"は {mode['label']}モードで {area_name} へ探索に出発。"
            f"帰還まで {self.user_service.format_duration(duration)}"
            f"{preparation_note}"
        )

    def finalize_exploration(self, username: str) -> str:
        u = self.user_service.get_user(username)
        display_name = self.user_service.get_display_name(username, username)
        explore = u.get("explore", {})

        if explore.get("state") != "exploring":
            return f"{display_name} は受け取り待ちの探索結果がありません。"

        result = explore.get("result") or {}
        auto_repeat = bool(explore.get("auto_repeat", False))
        area = result.get("area", DEFAULT_AREA)
        if area not in AREAS:
            area = DEFAULT_AREA

        battle_count = get_battle_count(result)
        exp_gain = int(result.get("exp", 0))
        gold_gain = int(result.get("gold", 0))
        drop_items: List[Dict[str, Any]] = result.get("drop_items", [])
        auto_explore_stones = max(0, int(result.get("auto_explore_stones", 0)))
        drop_materials: Dict[str, int] = result.get("drop_materials", {})
        drop_enchant_materials: Dict[str, int] = result.get("drop_enchant_materials", {})
        potions_used = max(0, int(result.get("potions_used", 0)))
        mode = self.resolve_exploration_mode(result.get("mode", DEFAULT_EXPLORATION_MODE))
        downed = bool(result.get("downed", False) or not bool(result.get("returned_safe", True)))
        armor_enchant_consumed = bool(result.get("armor_enchant_consumed", False))
        auto_repeat_result = u.get("auto_repeat_result")
        session_active = auto_repeat or isinstance(auto_repeat_result, dict)
        newly_cleared_boss_areas: List[str] = []
        newly_unlocked_slots: List[str] = []
        newly_unlocked_features: List[str] = []
        first_clear_reward_summaries: List[str] = []
        granted_auto_explore_fragments = 0

        for boss_area in self.get_boss_clear_areas_from_result(result):
            if not self.user_service.register_boss_clear(u, boss_area):
                continue
            newly_cleared_boss_areas.append(boss_area)
            reward_result = self.user_service.claim_area_first_clear_rewards(u, boss_area)
            newly_unlocked_slots.extend(reward_result.get("newly_unlocked_slots", []))
            newly_unlocked_features.extend(reward_result.get("newly_unlocked_features", []))
            first_clear_reward_summaries.extend(reward_result.get("reward_summaries", []))
            granted_auto_explore_fragments += max(
                0,
                int(reward_result.get("granted_auto_explore_fragments", 0)),
            )

        result["newly_cleared_boss_areas"] = newly_cleared_boss_areas
        result["newly_unlocked_slots"] = newly_unlocked_slots
        result["newly_unlocked_features"] = newly_unlocked_features
        result["first_clear_reward_summaries"] = first_clear_reward_summaries
        result["granted_auto_explore_fragments"] = granted_auto_explore_fragments
        area_depth_record_update = self.user_service.update_area_depth_record(
            username,
            display_name,
            result,
        )
        if area_depth_record_update:
            result["area_depth_record_update"] = deepcopy(area_depth_record_update)
        else:
            result.pop("area_depth_record_update", None)

        if downed:
            exp_gain = self.apply_keep_rate(exp_gain, DOWNED_EXP_KEEP_RATE)
            gold_gain = self.apply_keep_rate(gold_gain, DOWNED_GOLD_KEEP_RATE)
            drop_items = []
            drop_materials = {
                slot_name: self.apply_keep_rate(int(drop_materials.get(slot_name, 0)), DOWNED_MATERIAL_KEEP_RATE)
                for slot_name in MATERIAL_LABELS
            }
            drop_enchant_materials = {
                slot_name: self.apply_keep_rate(int(drop_enchant_materials.get(slot_name, 0)), DOWNED_MATERIAL_KEEP_RATE)
                for slot_name in ENCHANTMENT_MATERIAL_LABELS
            }

        for item in drop_items:
            if not isinstance(item, dict):
                continue
            self.user_service.assign_item_id(u, item)

        u["adventure_exp"] = int(u.get("adventure_exp", 0)) + exp_gain
        u["gold"] = int(u.get("gold", 0)) + gold_gain
        u["auto_explore_stones"] = 1 if (
            max(0, int(u.get("auto_explore_stones", 0))) > 0 or auto_explore_stones > 0
        ) else 0
        self.user_service._sync_feature_unlocks(u)

        for item in drop_items:
            u.setdefault("bag", []).append(item)

        materials = u.setdefault("materials", {})
        for slot_name in MATERIAL_LABELS:
            materials[slot_name] = max(0, int(materials.get(slot_name, 0))) + max(
                0,
                int(drop_materials.get(slot_name, 0)),
            )

        enchant_materials = u.setdefault("enchant_materials", {})
        for slot_name in ENCHANTMENT_MATERIAL_LABELS:
            enchant_materials[slot_name] = max(0, int(enchant_materials.get(slot_name, 0))) + max(
                0,
                int(drop_enchant_materials.get(slot_name, 0)),
            )

        if armor_enchant_consumed:
            armor_item = u.get("equipped", {}).get("armor")
            if isinstance(armor_item, dict):
                armor_item["enchant"] = None

        current_potions = int(u.get("potions", 0))
        actual_used = min(current_potions, potions_used)
        u["potions"] = max(0, current_potions - actual_used)
        u["hp"] = max(0, int(result.get("hp_after", 0)))
        self.user_service.sync_level_stats(u)
        auto_refill_summary = {
            "bought": 0,
            "cost": 0,
            "potions_after": int(u.get("potions", 0)),
        }
        auto_heal_summary = {
            "restored_hp": 0,
            "cost": 0,
            "full_heal": 1 if int(u.get("hp", 0)) >= int(u.get("max_hp", DEFAULT_MAX_HP)) else 0,
        }
        auto_armor_reenchants = 0
        if downed:
            u["hp"] = 0
            u["down"] = True
        else:
            u["down"] = False
            auto_heal_summary = self.user_service.auto_restore_hp_after_return(u)
            auto_refill_summary = self.user_service.auto_refill_potions(u, POTION_PRICE)
            if armor_enchant_consumed:
                reenchant_success, _ = self.item_service.enchant_equipped_item(u, "armor")
                auto_armor_reenchants = 1 if reenchant_success else 0

        finalized_run_result = deepcopy(result)
        finalized_run_result["exp"] = exp_gain
        finalized_run_result["gold"] = gold_gain
        finalized_run_result["drop_items"] = deepcopy(drop_items)
        finalized_run_result["auto_explore_stones"] = auto_explore_stones
        finalized_run_result["drop_materials"] = dict(drop_materials)
        finalized_run_result["drop_enchant_materials"] = dict(drop_enchant_materials)
        finalized_run_result["battle_count"] = battle_count
        finalized_run_result["auto_repeat"] = False
        finalized_run_result["exploration_runs"] = 1
        finalized_run_result["auto_potions_bought"] = max(
            0,
            int(auto_refill_summary.get("bought", 0)),
        )
        finalized_run_result["auto_potion_refill_cost"] = max(
            0,
            int(auto_refill_summary.get("cost", 0)),
        )
        finalized_run_result["auto_hp_heal_cost"] = max(
            0,
            int(auto_heal_summary.get("cost", 0)),
        )
        finalized_run_result["auto_hp_restored"] = max(
            0,
            int(auto_heal_summary.get("restored_hp", 0)),
        )
        finalized_run_result["potions_after_claim"] = max(
            0,
            int(auto_refill_summary.get("potions_after", u.get("potions", 0))),
        )
        finalized_run_result["auto_armor_reenchants"] = max(0, int(auto_armor_reenchants))

        aggregated_result = finalized_run_result
        if session_active:
            if not isinstance(auto_repeat_result, dict):
                auto_repeat_result = self._build_auto_repeat_result_template(area, mode["key"])
            aggregated_result = self._merge_exploration_result(auto_repeat_result, finalized_run_result)

        auto_repeat_continues = False
        next_result_downed = False
        if (
            auto_repeat
            and not downed
            and self.user_service.is_auto_repeat_unlocked(u)
            and int(aggregated_result.get("exploration_runs", 0)) < MAX_AUTO_REPEAT_EXPLORATIONS
        ):
            next_mode = self.resolve_exploration_mode(result.get("mode", DEFAULT_EXPLORATION_MODE))
            next_result = self.simulate_exploration_result(u, area, next_mode)
            next_result_downed = bool(
                next_result.get("downed", False) or not bool(next_result.get("returned_safe", True))
            )
            if not next_result_downed:
                next_result["auto_repeat"] = True
                u["explore"], _ = self._build_active_explore_state(
                    area,
                    next_mode,
                    next_result,
                    auto_repeat=True,
                    extra_delay_sec=AUTO_REPEAT_COOLDOWN_SEC,
                )
                u["auto_repeat_result"] = aggregated_result
                auto_repeat_continues = True
            else:
                u["explore"] = self._build_idle_explore_state()
                u["auto_repeat_result"] = None
        else:
            u["explore"] = self._build_idle_explore_state()
            u["auto_repeat_result"] = None

        level = self.user_service.get_adventure_level(u)
        display_result = aggregated_result if session_active else finalized_run_result
        auto_armor_reenchant_count = max(0, int(display_result.get("auto_armor_reenchants", 0)))
        enchant_break_summary = ""
        if armor_enchant_consumed:
            enchant_break_summary = (
                " / 防具E再付与" if auto_armor_reenchant_count > 0 else " / 防具エンチャ消滅"
            )
        auto_repeat_stop_reason = self._build_auto_repeat_stop_reason(
            auto_repeat_requested=auto_repeat,
            session_active=session_active and not auto_repeat_continues,
            downed=downed,
            run_count=max(0, int(aggregated_result.get("exploration_runs", 0))),
            next_result_downed=next_result_downed,
        )
        if auto_repeat_stop_reason:
            display_result["return_reason"] = auto_repeat_stop_reason
            display_result["return_info"] = build_return_info(
                phase=RETURN_PHASE_COMPLETE,
                reason=auto_repeat_stop_reason,
                raw_reason=auto_repeat_stop_reason,
            )
        display_result["auto_repeat"] = False
        display_result["claimed"] = True
        display_result["claimed_at"] = now_ts()
        display_result["claimed_status"] = {
            "hp": int(u.get("hp", DEFAULT_MAX_HP)),
            "max_hp": int(u.get("max_hp", DEFAULT_MAX_HP)),
            "down": bool(u.get("down", False)),
        }
        display_result["level_after"] = level
        if area_depth_record_update:
            display_result["area_depth_record_update"] = deepcopy(area_depth_record_update)
        else:
            display_result.pop("area_depth_record_update", None)
        display_result["new_records"] = self.user_service.update_exploration_records(u, display_result)
        achievement_unlocks = self.user_service.apply_exploration_achievement_unlocks(u, display_result)
        for key in ("new_achievements", "new_titles"):
            existing = self.user_service._sanitize_result_unlock_summaries(display_result.get(key))
            for summary in achievement_unlocks.get(key, []):
                safe_summary = str(summary or "").strip()
                if not safe_summary or safe_summary in existing:
                    continue
                existing.append(safe_summary)
            display_result[key] = existing
        if not auto_repeat_continues:
            u["last_exploration_result"] = display_result
            self.user_service.append_exploration_history(u, display_result)

        detail_note = " / !戦闘詳細" if get_battle_count(display_result) > 0 else ""
        auto_potion_note = ""
        if int(display_result.get("auto_potions_bought", 0)) > 0:
            auto_potion_note = f" / P補充+{int(display_result.get('auto_potions_bought', 0))}"
        auto_heal_note = ""
        if int(display_result.get("auto_hp_heal_cost", 0)) > 0:
            auto_heal_note = " / HP整備"
        if session_active and not auto_repeat_continues:
            return f"{display_name} の探索完了 / `!探索結果`"
        return (
            f"{display_name} 探索受取 / {mode['label']} {area} / "
            f"{'戦闘不能' if downed else '帰還'} / "
            f"{battle_count}戦 / 所持金{int(u.get('gold', 0))}G"
            f"{auto_heal_note}{auto_potion_note}{enchant_break_summary}{detail_note}"
        )

    def try_finalize_exploration(self, username: str) -> Optional[str]:
        u = self.user_service.get_user(username)
        explore = u.get("explore", {})
        if explore.get("state") != "exploring":
            return None
        if now_ts() < float(explore.get("ends_at", 0)):
            return None

        return self.finalize_exploration(username)

    def stop_auto_repeat(self, username: str) -> Tuple[bool, str]:
        u = self.user_service.get_user(username)
        explore = u.get("explore", {})
        if explore.get("state") != "exploring":
            return False, "は探索継続中ではありません。"
        if not bool(explore.get("auto_repeat", False)):
            return False, "は探索継続設定になっていません。"

        explore["auto_repeat"] = False
        area_name = explore.get("area", DEFAULT_AREA)
        if area_name not in AREAS:
            area_name = DEFAULT_AREA
        mode = self.resolve_exploration_mode(explore.get("mode"))
        if now_ts() < float(explore.get("ends_at", 0)):
            return True, f"の探索継続を停止しました。現在の {mode['label']} {area_name} が終わると待機します。"
        return True, "の探索継続を停止しました。`!探索結果` で結果を受け取れます。"
