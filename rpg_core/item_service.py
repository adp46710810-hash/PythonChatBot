from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from .rules import (
    AREAS,
    AUTO_EXPLORE_STONE_DROP_RATE,
    BASE_RARITY_WEIGHTS,
    DEFAULT_AREA,
    ENHANCEMENT_DEEP_ENDGAME_START_LEVEL,
    ENHANCEMENT_ENDGAME_START_LEVEL,
    ENHANCEMENT_GOLD_COST_BASE,
    ENHANCEMENT_GOLD_COST_DEEP_ENDGAME_STEP,
    ENHANCEMENT_GOLD_COST_ENDGAME_STEP,
    ENHANCEMENT_GOLD_COST_STEP,
    ENHANCEMENT_MATERIAL_COST_BASE,
    ENHANCEMENT_MATERIAL_COST_DEEP_ENDGAME_STEP,
    ENHANCEMENT_MATERIAL_COST_ENDGAME_STEP,
    ENHANCEMENT_MATERIAL_COST_INTERVAL,
    ENHANCEMENT_MATERIAL_COST_STEP,
    ENHANCEMENT_MAX_LEVEL,
    ENHANCEMENT_POWER_GAIN,
    ENHANCEMENT_RARITY_GOLD_BONUS,
    ENHANCEMENT_SUCCESS_RATES,
    ENCHANTMENT_EFFECT_LABELS,
    ENCHANTMENT_MATERIAL_LABELS,
    ITEM_BASE_NAMES,
    ITEM_MIN_VALUE,
    ITEM_POWER_PER_TIER,
    ITEM_POWER_ROLL_MAX,
    ITEM_POWER_ROLL_MIN,
    ITEM_SLOT_STAT_WEIGHTS,
    ITEM_SLOT_WEIGHTS,
    ITEM_VALUE_PER_RARITY_RANK,
    LEGENDARY_UNIQUE_NAMES,
    MATERIAL_LABELS,
    RARE_HUNT_RARITY_BONUS,
    RARITY_ORDER,
    RARITY_POWER_BONUS,
    RARITY_PREFIX,
    SLOT_LABEL,
    WEAPON_FORGE_GOLD_COST_RATE,
    WEAPON_FORGE_MATERIAL_DISCOUNT,
    WEAPON_FORGE_SUCCESS_RATE_BONUS,
)
from .stat_helpers import build_weighted_stats, format_item_stat_text, nonzero_stats
from .utils import pick_weighted


HESSE_LEGENDARY_AREA = "ヘッセ深部"
HESSE_BOSS_LEGENDARY_DROP_RATE = 0.10


class ItemService:
    def _refresh_item_stats(self, item: Dict[str, Any]) -> None:
        slot_name = str(item.get("slot", "") or "").strip()
        item["stats"] = nonzero_stats(
            build_weighted_stats(
                max(0, int(item.get("power", 0))),
                ITEM_SLOT_STAT_WEIGHTS.get(slot_name, {}),
            )
        )

    def _has_feature_unlock(self, u: Optional[Dict[str, Any]], feature_key: str) -> bool:
        if not isinstance(u, dict):
            return False
        feature_unlocks = u.get("feature_unlocks", {})
        if not isinstance(feature_unlocks, dict):
            return False
        return bool(feature_unlocks.get(feature_key, False))

    def _roll_area_rarity(self, area_name: str, u: Optional[Dict[str, Any]] = None) -> str:
        return pick_weighted(self.get_area_rarity_weights(area_name, u))

    def _create_equipment(
        self,
        area_name: str,
        slot: str,
        *,
        rarity: Optional[str] = None,
        u: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        slot_name = str(slot).strip()
        if slot_name not in ITEM_BASE_NAMES:
            return None

        area = AREAS.get(area_name, AREAS[DEFAULT_AREA])
        resolved_rarity = str(rarity or self._roll_area_rarity(area_name, u)).strip()
        if resolved_rarity not in RARITY_ORDER:
            resolved_rarity = self._roll_area_rarity(area_name, u)

        base_name = random.choice(ITEM_BASE_NAMES[slot_name])
        tier = int(area["tier"])

        power = tier * ITEM_POWER_PER_TIER + random.randint(ITEM_POWER_ROLL_MIN, ITEM_POWER_ROLL_MAX)
        power += RARITY_POWER_BONUS[resolved_rarity]
        value = max(
            ITEM_MIN_VALUE,
            power + (RARITY_ORDER[resolved_rarity] * ITEM_VALUE_PER_RARITY_RANK),
        )

        if resolved_rarity == "legendary":
            item_name = LEGENDARY_UNIQUE_NAMES.get(
                slot_name,
                f"{RARITY_PREFIX[resolved_rarity]}{base_name}",
            )
        else:
            item_name = f"{RARITY_PREFIX[resolved_rarity]}{base_name}"

        item = {
            "name": item_name,
            "slot": slot_name,
            "rarity": resolved_rarity,
            "power": power,
            "value": value,
            "series": item_name if resolved_rarity == "legendary" else None,
            "enhance": 0,
            "enhancement_gold_spent": 0,
            "enhancement_material_spent": 0,
            "enchant": None,
        }
        self._refresh_item_stats(item)
        return item

    def _get_shared_enchantment_slots(self, slot: str) -> List[str]:
        label = ENCHANTMENT_MATERIAL_LABELS.get(slot)
        if not label:
            return []
        return [
            material_slot
            for material_slot, material_label in ENCHANTMENT_MATERIAL_LABELS.items()
            if material_label == label
        ]

    def _is_slot_unlocked(self, u: Dict[str, Any], slot: str) -> bool:
        slot_unlocks = u.get("slot_unlocks", {})
        if not isinstance(slot_unlocks, dict):
            return slot == "weapon"
        return bool(slot_unlocks.get(slot, slot == "weapon"))

    def _get_hesse_boss_legendary_drop_rate(self, monster_data: Dict[str, Any]) -> float:
        progress_bonus = max(
            0.0,
            float(monster_data.get("legendary_drop_rate_multiplier_bonus", 0.0)),
        )
        return min(0.95, HESSE_BOSS_LEGENDARY_DROP_RATE * (1.0 + progress_bonus))

    def _should_drop_hesse_boss_legendary(self, area_name: str, monster_data: Dict[str, Any]) -> bool:
        return (
            area_name == HESSE_LEGENDARY_AREA
            and bool(monster_data.get("boss", False))
            and random.random() < self._get_hesse_boss_legendary_drop_rate(monster_data)
        )

    def _get_available_enchantment_materials(self, u: Dict[str, Any], slot: str) -> int:
        enchant_materials = u.setdefault("enchant_materials", {})
        return sum(
            max(0, int(enchant_materials.get(material_slot, 0)))
            for material_slot in self._get_shared_enchantment_slots(slot)
        )

    def _consume_enchantment_materials(self, u: Dict[str, Any], slot: str, quantity: int) -> bool:
        remaining = max(0, int(quantity))
        if remaining <= 0:
            return True

        enchant_materials = u.setdefault("enchant_materials", {})
        for material_slot in self._get_shared_enchantment_slots(slot):
            available = max(0, int(enchant_materials.get(material_slot, 0)))
            if available <= 0:
                continue

            consumed = min(available, remaining)
            enchant_materials[material_slot] = available - consumed
            remaining -= consumed
            if remaining <= 0:
                return True

        return False

    def _get_material_drop_configs(self, area: Dict[str, Any]) -> List[Dict[str, Any]]:
        configs: List[Dict[str, Any]] = []

        raw_multi = area.get("material_drops")
        if isinstance(raw_multi, list):
            configs.extend(config for config in raw_multi if isinstance(config, dict))

        raw_single = area.get("material_drop")
        if isinstance(raw_single, dict):
            configs.append(raw_single)

        return configs

    def _get_enchantment_drop_configs(self, area: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw_multi = area.get("enchantment_drops")
        if not isinstance(raw_multi, list):
            return []
        return [config for config in raw_multi if isinstance(config, dict)]

    def _roll_configured_drops(
        self,
        configs: List[Dict[str, Any]],
        valid_labels: Dict[str, str],
        monster_data: Dict[str, Any],
        chance_bonus: float = 0.0,
        late_bonus_key: Optional[str] = None,
    ) -> Dict[str, int]:
        total_drops: Dict[str, int] = {}

        for drop_config in configs:
            slot = str(drop_config.get("slot", "")).strip()
            if slot not in valid_labels:
                continue

            chance = max(0.0, min(1.0, float(drop_config.get("chance", 0.0)) + float(chance_bonus)))
            if random.random() >= chance:
                continue

            drop_min = max(0, int(drop_config.get("min", 1)))
            drop_max = max(drop_min, int(drop_config.get("max", drop_min)))
            quantity = random.randint(drop_min, drop_max)

            if monster_data.get("elite", False):
                quantity += max(0, int(drop_config.get("elite_bonus", 0)))
            if monster_data.get("boss", False):
                quantity += max(0, int(drop_config.get("boss_bonus", 0)))
            if late_bonus_key:
                quantity += max(0, int(monster_data.get(late_bonus_key, 0)))

            if quantity <= 0:
                continue

            total_drops[slot] = total_drops.get(slot, 0) + quantity

        return total_drops

    def get_material_drop_for_monster(
        self,
        area_name: str,
        monster_data: Dict[str, Any],
        chance_bonus: float = 0.0,
    ) -> Dict[str, int]:
        area = AREAS.get(area_name, AREAS[DEFAULT_AREA])
        return self._roll_configured_drops(
            self._get_material_drop_configs(area),
            MATERIAL_LABELS,
            monster_data,
            chance_bonus=chance_bonus,
            late_bonus_key="late_resource_bonus",
        )

    def get_enchantment_drop_for_monster(
        self,
        area_name: str,
        monster_data: Dict[str, Any],
        chance_bonus: float = 0.0,
    ) -> Dict[str, int]:
        area = AREAS.get(area_name, AREAS[DEFAULT_AREA])
        return self._roll_configured_drops(
            self._get_enchantment_drop_configs(area),
            ENCHANTMENT_MATERIAL_LABELS,
            monster_data,
            chance_bonus=chance_bonus,
            late_bonus_key="late_resource_bonus",
        )

    def get_area_rarity_weights(
        self,
        area_name: str,
        u: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[str, int]]:
        area = AREAS.get(area_name, AREAS[DEFAULT_AREA])
        bonus = area.get("rare_bonus", {})
        max_rarity = str(area.get("max_rarity", "")).strip()
        max_rarity_rank = RARITY_ORDER.get(max_rarity)
        rare_hunt_bonus = RARE_HUNT_RARITY_BONUS if self._has_feature_unlock(u, "rare_hunt") else {}

        pairs: List[Tuple[str, int]] = []
        for rarity, base_weight in BASE_RARITY_WEIGHTS.items():
            rarity_rank = RARITY_ORDER.get(rarity, 0)
            if max_rarity_rank is not None and rarity_rank > max_rarity_rank:
                continue
            w = base_weight + int(bonus.get(rarity, 0)) + int(rare_hunt_bonus.get(rarity, 0))
            pairs.append((rarity, max(1, w)))

        return pairs or list(BASE_RARITY_WEIGHTS.items())

    def roll_equipment_for_monster(
        self,
        area_name: str,
        monster_data: Dict[str, Any],
        extra_drop_rate_bonus: float = 0.0,
        u: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        area = AREAS.get(area_name, AREAS[DEFAULT_AREA])
        specialty = str(area.get("specialty", "")).strip()
        if specialty == "武器強化素材":
            return None

        if self._should_drop_hesse_boss_legendary(area_name, monster_data):
            slot = pick_weighted([(slot_name, int(weight)) for slot_name, weight in ITEM_SLOT_WEIGHTS.items()])
            return self._create_equipment(area_name, slot, rarity="legendary", u=u)

        base_drop = float(monster_data.get("drop_rate", 0.0)) + float(extra_drop_rate_bonus)
        final_drop = base_drop + float(area.get("drop_rate_bonus", 0.0))
        final_drop = max(0.01, min(0.95, final_drop))

        if random.random() >= final_drop:
            return None

        slot = pick_weighted([(slot_name, int(weight)) for slot_name, weight in ITEM_SLOT_WEIGHTS.items()])
        return self._create_equipment(area_name, slot, u=u)

    def create_guaranteed_equipment(
        self,
        area_name: str,
        slot: str,
        *,
        rarity: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return self._create_equipment(area_name, slot, rarity=rarity)

    def roll_auto_explore_stone(self) -> int:
        return 1 if random.random() < AUTO_EXPLORE_STONE_DROP_RATE else 0

    def get_enhancement_success_rate(self, current_enhance: int) -> float:
        current_enhance = max(0, int(current_enhance))
        if not ENHANCEMENT_SUCCESS_RATES:
            return 0.0
        index = min(current_enhance, len(ENHANCEMENT_SUCCESS_RATES) - 1)
        return max(0.0, min(1.0, float(ENHANCEMENT_SUCCESS_RATES[index])))

    def get_enhancement_material_cost(self, current_enhance: int) -> int:
        current_enhance = max(0, int(current_enhance))
        step_count = current_enhance // ENHANCEMENT_MATERIAL_COST_INTERVAL
        endgame_levels = max(0, current_enhance - ENHANCEMENT_ENDGAME_START_LEVEL + 1)
        deep_endgame_levels = max(0, current_enhance - ENHANCEMENT_DEEP_ENDGAME_START_LEVEL + 1)
        return max(
            1,
            ENHANCEMENT_MATERIAL_COST_BASE
            + (step_count * ENHANCEMENT_MATERIAL_COST_STEP)
            + (endgame_levels * ENHANCEMENT_MATERIAL_COST_ENDGAME_STEP)
            + (deep_endgame_levels * ENHANCEMENT_MATERIAL_COST_DEEP_ENDGAME_STEP),
        )

    def get_enhancement_gold_cost(self, item: Dict[str, Any]) -> int:
        current_enhance = max(0, int(item.get("enhance", 0)))
        rarity = str(item.get("rarity", "common"))
        rarity_bonus = int(ENHANCEMENT_RARITY_GOLD_BONUS.get(rarity, 0))
        endgame_levels = max(0, current_enhance - ENHANCEMENT_ENDGAME_START_LEVEL + 1)
        deep_endgame_levels = max(0, current_enhance - ENHANCEMENT_DEEP_ENDGAME_START_LEVEL + 1)
        return max(
            0,
            ENHANCEMENT_GOLD_COST_BASE
            + (current_enhance * ENHANCEMENT_GOLD_COST_STEP)
            + (endgame_levels * ENHANCEMENT_GOLD_COST_ENDGAME_STEP)
            + (deep_endgame_levels * ENHANCEMENT_GOLD_COST_DEEP_ENDGAME_STEP)
            + rarity_bonus,
        )

    def recalculate_item_value(self, item: Dict[str, Any]) -> None:
        rarity_rank = int(RARITY_ORDER.get(item.get("rarity", "common"), 0))
        power = max(0, int(item.get("power", 0)))
        item["value"] = max(ITEM_MIN_VALUE, power + (rarity_rank * ITEM_VALUE_PER_RARITY_RANK))

    def get_item_enchant_key(self, item: Optional[Dict[str, Any]]) -> Optional[str]:
        if not item:
            return None
        enchant_key = str(item.get("enchant", "") or "").strip()
        if enchant_key in ENCHANTMENT_EFFECT_LABELS:
            return enchant_key
        return None

    def _get_item_upgrade_score(self, item: Optional[Dict[str, Any]]) -> Tuple[int, int, int]:
        if not item:
            return (-1, -1, -1)
        return (
            RARITY_ORDER.get(item.get("rarity", "common"), 0),
            int(item.get("power", 0)),
            1 if self.get_item_enchant_key(item) else 0,
        )

    def _get_item_enhancement_bonus_power(self, item: Optional[Dict[str, Any]]) -> int:
        if not item:
            return 0
        slot_name = str(item.get("slot", "") or "").strip()
        enhance_level = max(0, int(item.get("enhance", 0)))
        power_gain = max(0, int(ENHANCEMENT_POWER_GAIN.get(slot_name, 0)))
        return enhance_level * power_gain

    def _move_upgrade_state_to_higher_rarity_item(
        self,
        source_item: Optional[Dict[str, Any]],
        target_item: Optional[Dict[str, Any]],
    ) -> None:
        if not source_item or not target_item:
            return

        source_rarity = RARITY_ORDER.get(source_item.get("rarity", "common"), 0)
        target_rarity = RARITY_ORDER.get(target_item.get("rarity", "common"), 0)
        if target_rarity <= source_rarity:
            return

        source_enhance = max(0, int(source_item.get("enhance", 0)))
        source_gold_spent = max(0, int(source_item.get("enhancement_gold_spent", 0)))
        source_material_spent = max(0, int(source_item.get("enhancement_material_spent", 0)))
        source_enchant = self.get_item_enchant_key(source_item)

        # Fresh higher-rarity drops inherit upgrades, but we avoid overwriting
        # upgrades that were already invested into the replacement item.
        target_has_own_enhancement = any(
            (
                max(0, int(target_item.get("enhance", 0))) > 0,
                max(0, int(target_item.get("enhancement_gold_spent", 0))) > 0,
                max(0, int(target_item.get("enhancement_material_spent", 0))) > 0,
            )
        )
        move_enhancement = source_enhance > 0 and not target_has_own_enhancement
        move_enchant = bool(source_enchant) and self.get_item_enchant_key(target_item) in (None, source_enchant)

        if not move_enhancement and not move_enchant:
            return

        if move_enhancement:
            bonus_power = self._get_item_enhancement_bonus_power(source_item)
            target_item["enhance"] = source_enhance
            target_item["enhancement_gold_spent"] = source_gold_spent
            target_item["enhancement_material_spent"] = source_material_spent
            target_item["power"] = max(0, int(target_item.get("power", 0))) + bonus_power

            source_item["enhance"] = 0
            source_item["enhancement_gold_spent"] = 0
            source_item["enhancement_material_spent"] = 0
            source_item["power"] = max(0, int(source_item.get("power", 0)) - bonus_power)

        if move_enchant:
            target_item["enchant"] = source_enchant
            source_item["enchant"] = None

        self._refresh_item_stats(source_item)
        self.recalculate_item_value(source_item)
        self._refresh_item_stats(target_item)
        self.recalculate_item_value(target_item)

    def _get_item_sale_gold(self, item: Dict[str, Any]) -> int:
        base_value = max(0, int(item.get("value", 0)))
        enhancement_refund = max(0, int(item.get("enhancement_gold_spent", 0)))
        return base_value + enhancement_refund

    def _get_enhancement_attempt_context(
        self,
        u: Dict[str, Any],
        slot: str,
    ) -> Dict[str, Any]:
        slot = str(slot)
        equipped = u.get("equipped", {})
        item = equipped.get(slot)

        if slot not in MATERIAL_LABELS:
            return {"attemptable": False, "reason": "不明な装備種別です。", "slot": slot, "item": None}
        if not self._is_slot_unlocked(u, slot):
            return {
                "attemptable": False,
                "reason": f"{SLOT_LABEL.get(slot, slot)}スロットは未開放です。",
                "slot": slot,
                "item": item,
            }
        if not item:
            return {
                "attemptable": False,
                "reason": f"{SLOT_LABEL.get(slot, slot)}を装備していません。",
                "slot": slot,
                "item": None,
            }

        current_enhance = max(0, int(item.get("enhance", 0)))
        if current_enhance >= ENHANCEMENT_MAX_LEVEL:
            return {
                "attemptable": False,
                "reason": f"{item['name']} はすでに +{ENHANCEMENT_MAX_LEVEL} です。",
                "slot": slot,
                "item": item,
                "current_enhance": current_enhance,
            }

        materials = u.setdefault("materials", {})
        available_materials = max(0, int(materials.get(slot, 0)))
        material_cost = self.get_enhancement_material_cost(current_enhance)
        gold_cost = self.get_enhancement_gold_cost(item)
        success_rate = self.get_enhancement_success_rate(current_enhance)
        current_gold = max(0, int(u.get("gold", 0)))

        if slot == "weapon" and self._has_feature_unlock(u, "weapon_forge"):
            material_cost = max(1, material_cost - int(WEAPON_FORGE_MATERIAL_DISCOUNT))
            gold_cost = max(0, int(round(gold_cost * float(WEAPON_FORGE_GOLD_COST_RATE))))
            success_rate = min(0.98, success_rate + float(WEAPON_FORGE_SUCCESS_RATE_BONUS))

        if available_materials < material_cost:
            return {
                "attemptable": False,
                "reason": (
                    f"{MATERIAL_LABELS[slot]} が不足しています。"
                    f" 必要:{material_cost} / 所持:{available_materials}"
                ),
                "slot": slot,
                "item": item,
                "current_enhance": current_enhance,
                "material_cost": material_cost,
                "gold_cost": gold_cost,
                "success_rate": success_rate,
            }
        if current_gold < gold_cost:
            return {
                "attemptable": False,
                "reason": f"所持金不足です。必要:{gold_cost}G / 所持:{current_gold}G",
                "slot": slot,
                "item": item,
                "current_enhance": current_enhance,
                "material_cost": material_cost,
                "gold_cost": gold_cost,
                "success_rate": success_rate,
            }

        return {
            "attemptable": True,
            "slot": slot,
            "item": item,
            "current_enhance": current_enhance,
            "material_cost": material_cost,
            "gold_cost": gold_cost,
            "success_rate": success_rate,
        }

    def enhance_equipped_item(self, u: Dict[str, Any], slot: str) -> Tuple[bool, str]:
        context = self._get_enhancement_attempt_context(u, slot)
        if not bool(context.get("attemptable", False)):
            return False, str(context.get("reason", "強化できません。"))

        slot = str(context["slot"])
        item = context["item"]
        current_enhance = int(context["current_enhance"])
        material_cost = int(context["material_cost"])
        gold_cost = int(context["gold_cost"])
        success_rate = float(context["success_rate"])
        materials = u.setdefault("materials", {})
        current_gold = max(0, int(u.get("gold", 0)))

        materials[slot] = max(0, int(materials.get(slot, 0))) - material_cost
        u["gold"] = current_gold - gold_cost
        item["enhancement_gold_spent"] = max(0, int(item.get("enhancement_gold_spent", 0))) + gold_cost
        item["enhancement_material_spent"] = max(0, int(item.get("enhancement_material_spent", 0))) + material_cost

        if random.random() >= success_rate:
            return True, (
                f"{item['name']} 強化失敗... "
                f"{MATERIAL_LABELS[slot]}-{material_cost} / -{gold_cost}G / "
                f"+{current_enhance} 維持"
            )

        power_gain = max(1, int(ENHANCEMENT_POWER_GAIN.get(slot, 1)))
        item["enhance"] = current_enhance + 1
        item["power"] = max(0, int(item.get("power", 0))) + power_gain
        self._refresh_item_stats(item)
        self.recalculate_item_value(item)

        return True, (
            f"{item['name']} 強化成功! "
            f"+{current_enhance} -> +{item['enhance']} / "
            f"{format_item_stat_text(slot, item.get('stats', {}), power=int(item.get('power', 0)))} / "
            f"{MATERIAL_LABELS[slot]}-{material_cost} / -{gold_cost}G"
        )

    def auto_enhance_equipped_items(
        self,
        u: Dict[str, Any],
        slots: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        preferred_order = ("weapon", "armor", "ring", "shoes")
        slot_order = [slot_name for slot_name in preferred_order if slot_name in MATERIAL_LABELS]
        slot_order.extend(
            slot_name
            for slot_name in MATERIAL_LABELS
            if slot_name not in slot_order
        )
        requested_slots = [str(slot_name) for slot_name in (slots or slot_order)]
        target_slots = [slot_name for slot_name in requested_slots if slot_name in MATERIAL_LABELS]

        before_gold = max(0, int(u.get("gold", 0)))
        before_materials = {
            slot_name: max(0, int(u.setdefault("materials", {}).get(slot_name, 0)))
            for slot_name in MATERIAL_LABELS
        }
        attempt_logs: List[Dict[str, Any]] = []
        success_count = 0
        failure_count = 0

        while True:
            pass_progress = False
            for slot_name in target_slots:
                context = self._get_enhancement_attempt_context(u, slot_name)
                if not bool(context.get("attemptable", False)):
                    continue

                item = context["item"]
                before_gold_for_attempt = max(0, int(u.get("gold", 0)))
                before_materials_for_attempt = max(
                    0,
                    int(u.setdefault("materials", {}).get(slot_name, 0)),
                )
                current_enhance = int(context["current_enhance"])
                attempted, message = self.enhance_equipped_item(u, slot_name)
                if not attempted:
                    continue

                pass_progress = True
                success = max(0, int(item.get("enhance", 0))) > current_enhance
                if success:
                    success_count += 1
                else:
                    failure_count += 1

                attempt_logs.append(
                    {
                        "slot": slot_name,
                        "item_name": str(item.get("name", "?")),
                        "success": success,
                        "message": message,
                        "gold_spent": before_gold_for_attempt - max(0, int(u.get("gold", 0))),
                        "material_spent": (
                            before_materials_for_attempt
                            - max(0, int(u.setdefault("materials", {}).get(slot_name, 0)))
                        ),
                    }
                )

            if not pass_progress:
                break

        after_gold = max(0, int(u.get("gold", 0)))
        after_materials = {
            slot_name: max(0, int(u.setdefault("materials", {}).get(slot_name, 0)))
            for slot_name in MATERIAL_LABELS
        }
        stop_reasons: Dict[str, str] = {}
        for slot_name in target_slots:
            context = self._get_enhancement_attempt_context(u, slot_name)
            if bool(context.get("attemptable", False)):
                continue
            stop_reasons[slot_name] = str(context.get("reason", "強化できません。"))

        attempts_by_slot = {slot_name: 0 for slot_name in target_slots}
        spent_materials = {
            slot_name: max(0, before_materials.get(slot_name, 0) - after_materials.get(slot_name, 0))
            for slot_name in MATERIAL_LABELS
        }
        for attempt in attempt_logs:
            slot_name = str(attempt.get("slot", "") or "")
            attempts_by_slot[slot_name] = attempts_by_slot.get(slot_name, 0) + 1

        return {
            "attempted": bool(attempt_logs),
            "target_slots": target_slots,
            "attempt_logs": attempt_logs,
            "attempt_count": len(attempt_logs),
            "success_count": success_count,
            "failure_count": failure_count,
            "before_gold": before_gold,
            "after_gold": after_gold,
            "gold_spent": max(0, before_gold - after_gold),
            "before_materials": before_materials,
            "after_materials": after_materials,
            "spent_materials": spent_materials,
            "attempts_by_slot": attempts_by_slot,
            "stop_reasons": stop_reasons,
        }

    def enchant_equipped_item(self, u: Dict[str, Any], slot: str) -> Tuple[bool, str]:
        slot = str(slot)
        if slot not in ENCHANTMENT_MATERIAL_LABELS:
            return False, "エンチャントできるのは武器・防具・装飾です。"
        if not self._is_slot_unlocked(u, slot):
            return False, f"{SLOT_LABEL.get(slot, slot)}スロットは未開放です。"
        if not self._has_feature_unlock(u, "enchanting"):
            return False, "エンチャントは三日月廃墟ボス初回撃破で解放されます。"

        equipped = u.get("equipped", {})
        item = equipped.get(slot)
        if not item:
            return False, f"{SLOT_LABEL.get(slot, slot)}を装備していません。"

        if self.get_item_enchant_key(item) == slot:
            return False, f"{item['name']} にはすでに {ENCHANTMENT_EFFECT_LABELS[slot]} が付与されています。"

        available_materials = self._get_available_enchantment_materials(u, slot)
        if available_materials < 1:
            return False, (
                f"{ENCHANTMENT_MATERIAL_LABELS[slot]} が不足しています。"
                f" 必要:1 / 所持:{available_materials}"
            )

        self._consume_enchantment_materials(u, slot, 1)
        item["enchant"] = slot
        enchant_progress = u.setdefault("enchant_progress", {})
        if isinstance(enchant_progress, dict):
            enchant_progress[slot] = True
        return True, (
            f"{item['name']} に {ENCHANTMENT_EFFECT_LABELS[slot]} を付与しました。"
            f" {ENCHANTMENT_MATERIAL_LABELS[slot]}-1"
        )

    def autoequip_best(self, u: Dict[str, Any]) -> bool:
        changed = False

        bag = u.get("bag", [])
        equipped = u.get("equipped", {})

        preferred_order = ("weapon", "armor", "ring", "shoes")
        slot_order = [slot_name for slot_name in preferred_order if slot_name in SLOT_LABEL]
        slot_order.extend(slot_name for slot_name in SLOT_LABEL if slot_name not in slot_order)
        for slot in slot_order:
            if not self._is_slot_unlocked(u, slot):
                continue
            best_index = None
            current_score = self._get_item_upgrade_score(equipped.get(slot))

            for i, item in enumerate(bag):
                if item.get("slot") != slot:
                    continue
                s = self._get_item_upgrade_score(item)
                if s > current_score:
                    current_score = s
                    best_index = i

            if best_index is not None:
                new_item = bag.pop(best_index)
                old_item = equipped.get(slot)
                self._move_upgrade_state_to_higher_rarity_item(old_item, new_item)
                equipped[slot] = new_item
                if old_item:
                    bag.append(old_item)
                changed = True

        return changed

    def _is_protected_from_auto_sell(self, u: Dict[str, Any], item: Dict[str, Any]) -> bool:
        slot_name = str(item.get("slot", "")).strip()
        if slot_name in SLOT_LABEL and not self._is_slot_unlocked(u, slot_name):
            return True

        item_id = str(item.get("item_id", "") or "").strip()
        if item_id and item_id in set(u.get("protected_item_ids", [])):
            return True

        return str(item.get("rarity", "common") or "common").strip() == "legendary"

    def sell_all_bag_items(self, u: Dict[str, Any]) -> Tuple[int, int]:
        bag = u.get("bag", [])
        materials = u.setdefault("materials", {})

        sold_count = 0
        gold_gain = 0
        kept_items: List[Dict[str, Any]] = []
        material_refunds = {slot_name: 0 for slot_name in MATERIAL_LABELS}

        for item in bag:
            if self._is_protected_from_auto_sell(u, item):
                kept_items.append(item)
                continue
            sold_count += 1
            gold_gain += self._get_item_sale_gold(item)
            slot_name = str(item.get("slot", "") or "").strip()
            if slot_name in material_refunds:
                material_refunds[slot_name] += max(0, int(item.get("enhancement_material_spent", 0)))

        u["bag"] = kept_items
        for slot_name, refund_quantity in material_refunds.items():
            if refund_quantity <= 0:
                continue
            materials[slot_name] = max(0, int(materials.get(slot_name, 0))) + refund_quantity
        u["gold"] = int(u.get("gold", 0)) + gold_gain
        return sold_count, gold_gain
