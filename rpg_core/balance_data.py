from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .stat_helpers import STAT_KEYS, normalize_stats


def _resolve_balance_data_dir() -> Path:
    project_root = Path(__file__).resolve().parent.parent
    candidates = [
        project_root / "data" / "balance",
        project_root / "rpg_data",
    ]

    for path in candidates:
        if path.exists():
            return path

    return candidates[0]


BALANCE_DATA_DIR = _resolve_balance_data_dir()


def _load_json_file(filename: str) -> Any:
    path = BALANCE_DATA_DIR / filename

    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"Balance data file not found: {path}") from exc

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in balance data file: {path} ({exc})") from exc


def _expect_dict(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def _expect_list(value: Any, label: str) -> List[Any]:
    if not isinstance(value, list):
        raise RuntimeError(f"{label} must be a JSON array")
    return value


def _normalize_json_value(value: Any, label: str) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_normalize_json_value(item, f"{label}[]") for item in value]
    if isinstance(value, dict):
        normalized: Dict[str, Any] = {}
        for raw_key, raw_item in value.items():
            safe_key = str(raw_key or "").strip()
            if not safe_key:
                raise RuntimeError(f"{label} contains an empty key")
            normalized[safe_key] = _normalize_json_value(raw_item, f"{label}.{safe_key}")
        return normalized
    raise RuntimeError(f"{label} must contain only JSON-compatible values")


def _normalize_skill_special_effects(raw_effects: Any, label: str) -> List[Dict[str, Any]]:
    if raw_effects is None:
        return []

    effects = _expect_list(raw_effects, label)
    normalized_effects: List[Dict[str, Any]] = []
    for index, raw_effect in enumerate(effects, start=1):
        effect = dict(_expect_dict(raw_effect, f"{label}[{index}]"))
        allowed_effect_keys = {"kind", "summary", "timing", "target", "params", "tags"}
        unknown_effect_keys = set(effect) - allowed_effect_keys
        if unknown_effect_keys:
            unknown = ", ".join(sorted(unknown_effect_keys))
            raise RuntimeError(f"{label}[{index}] contains unknown keys: {unknown}")

        kind = str(effect.get("kind", "") or "").strip()
        if not kind:
            raise RuntimeError(f"{label}[{index}].kind must be non-empty")

        raw_params = effect.get("params", {})
        if raw_params is None:
            raw_params = {}
        if not isinstance(raw_params, dict):
            raise RuntimeError(f"{label}[{index}].params must be a JSON object")

        raw_tags = effect.get("tags", [])
        if raw_tags is None:
            raw_tags = []
        if not isinstance(raw_tags, list):
            raise RuntimeError(f"{label}[{index}].tags must be a JSON array")

        normalized_effects.append(
            {
                "kind": kind,
                "summary": str(effect.get("summary", "") or "").strip(),
                "timing": str(effect.get("timing", "") or "").strip(),
                "target": str(effect.get("target", "") or "").strip(),
                "params": _normalize_json_value(raw_params, f"{label}[{index}].params"),
                "tags": [
                    str(tag).strip()
                    for tag in raw_tags
                    if str(tag).strip()
                ],
            }
        )

    return normalized_effects


def _normalize_feature_unlock_entry(raw_feature: Any, label: str) -> Dict[str, Any]:
    if isinstance(raw_feature, str):
        feature_key = raw_feature.strip()
        if not feature_key:
            raise RuntimeError(f"{label} must be non-empty")
        return {"key": feature_key}

    if not isinstance(raw_feature, dict):
        raise RuntimeError(f"{label} must be a string or JSON object")

    allowed_feature_keys = {
        "key",
        "label",
        "summary",
        "rarity_bonus",
        "enhancement_bonus",
        "guard_bonus",
    }
    unknown_feature_keys = set(raw_feature) - allowed_feature_keys
    if unknown_feature_keys:
        unknown_keys = ", ".join(sorted(unknown_feature_keys))
        raise RuntimeError(f"{label} contains unknown keys: {unknown_keys}")

    feature_key = str(raw_feature.get("key", "") or "").strip()
    if not feature_key:
        raise RuntimeError(f"{label}.key must be non-empty")

    normalized: Dict[str, Any] = {"key": feature_key}
    for text_key in ("label", "summary"):
        if text_key not in raw_feature:
            continue
        text_value = raw_feature[text_key]
        if not isinstance(text_value, str):
            raise RuntimeError(f"{label}.{text_key} must be a string")
        safe_text_value = text_value.strip()
        if safe_text_value:
            normalized[text_key] = safe_text_value

    raw_rarity_bonus = raw_feature.get("rarity_bonus")
    if raw_rarity_bonus is not None:
        rarity_bonus = _expect_dict(raw_rarity_bonus, f"{label}.rarity_bonus")
        normalized_rarity_bonus: Dict[str, int] = {}
        for rarity_name, bonus_value in rarity_bonus.items():
            safe_rarity_name = str(rarity_name).strip()
            if safe_rarity_name not in RARITY_ORDER:
                raise RuntimeError(
                    f"{label}.rarity_bonus contains unknown rarity '{rarity_name}'"
                )
            if not isinstance(bonus_value, (int, float)):
                raise RuntimeError(f"{label}.rarity_bonus.{safe_rarity_name} must be numeric")
            normalized_rarity_bonus[safe_rarity_name] = int(bonus_value)
        normalized["rarity_bonus"] = normalized_rarity_bonus

    raw_enhancement_bonus = raw_feature.get("enhancement_bonus")
    if raw_enhancement_bonus is not None:
        enhancement_bonus = _expect_dict(raw_enhancement_bonus, f"{label}.enhancement_bonus")
        allowed_enhancement_keys = {
            "success_rate_bonus",
            "gold_cost_rate",
            "material_discount",
        }
        unknown_enhancement_keys = set(enhancement_bonus) - allowed_enhancement_keys
        if unknown_enhancement_keys:
            unknown_keys = ", ".join(sorted(unknown_enhancement_keys))
            raise RuntimeError(f"{label}.enhancement_bonus contains unknown keys: {unknown_keys}")

        normalized_enhancement_bonus: Dict[str, Any] = {}
        if "success_rate_bonus" in enhancement_bonus:
            success_rate_bonus = enhancement_bonus["success_rate_bonus"]
            if not isinstance(success_rate_bonus, (int, float)):
                raise RuntimeError(f"{label}.enhancement_bonus.success_rate_bonus must be numeric")
            normalized_enhancement_bonus["success_rate_bonus"] = float(success_rate_bonus)
        if "gold_cost_rate" in enhancement_bonus:
            gold_cost_rate = enhancement_bonus["gold_cost_rate"]
            if not isinstance(gold_cost_rate, (int, float)):
                raise RuntimeError(f"{label}.enhancement_bonus.gold_cost_rate must be numeric")
            if float(gold_cost_rate) < 0.0:
                raise RuntimeError(f"{label}.enhancement_bonus.gold_cost_rate must be 0 or greater")
            normalized_enhancement_bonus["gold_cost_rate"] = float(gold_cost_rate)
        if "material_discount" in enhancement_bonus:
            material_discount = enhancement_bonus["material_discount"]
            if not isinstance(material_discount, int) or int(material_discount) < 0:
                raise RuntimeError(
                    f"{label}.enhancement_bonus.material_discount must be a non-negative integer"
                )
            normalized_enhancement_bonus["material_discount"] = int(material_discount)
        normalized["enhancement_bonus"] = normalized_enhancement_bonus

    raw_guard_bonus = raw_feature.get("guard_bonus")
    if raw_guard_bonus is not None:
        guard_bonus = _expect_dict(raw_guard_bonus, f"{label}.guard_bonus")
        allowed_guard_keys = {"base_count"}
        unknown_guard_keys = set(guard_bonus) - allowed_guard_keys
        if unknown_guard_keys:
            unknown_keys = ", ".join(sorted(unknown_guard_keys))
            raise RuntimeError(f"{label}.guard_bonus contains unknown keys: {unknown_keys}")
        base_count = guard_bonus.get("base_count", 0)
        if not isinstance(base_count, int) or int(base_count) < 0:
            raise RuntimeError(f"{label}.guard_bonus.base_count must be a non-negative integer")
        normalized["guard_bonus"] = {"base_count": int(base_count)}

    return normalized


def _merge_feature_unlock_definition(
    current: Dict[str, Any],
    incoming: Dict[str, Any],
    *,
    feature_key: str,
    source_label: str,
) -> Dict[str, Any]:
    merged = dict(current)

    for text_key in ("label", "summary"):
        incoming_value = str(incoming.get(text_key, "") or "").strip()
        if not incoming_value:
            continue
        current_value = str(merged.get(text_key, "") or "").strip()
        if current_value and current_value != incoming_value:
            raise RuntimeError(
                f"{source_label} defines feature '{feature_key}' with conflicting {text_key}"
            )
        merged[text_key] = incoming_value

    for effect_key in ("rarity_bonus", "enhancement_bonus", "guard_bonus"):
        if effect_key not in incoming:
            continue
        incoming_value = incoming[effect_key]
        current_value = merged.get(effect_key)
        if current_value is not None and current_value != incoming_value:
            raise RuntimeError(
                f"{source_label} defines feature '{feature_key}' with conflicting {effect_key}"
            )
        merged[effect_key] = incoming_value

    return merged


def _load_areas() -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    raw_areas = _expect_dict(_load_json_file("areas.json"), "balance/areas.json")

    areas: Dict[str, Dict[str, Any]] = {}
    aliases: Dict[str, str] = {}

    for area_name, area_data in raw_areas.items():
        area = dict(_expect_dict(area_data, f"areas[{area_name}]"))

        raw_aliases = area.pop("aliases", [])
        alias_list = _expect_list(raw_aliases, f"areas[{area_name}].aliases")

        encounters = area.get("encounters")
        if isinstance(encounters, list):
            area["encounters"] = tuple(encounters)

        areas[area_name] = area

        for alias in [area_name, *alias_list]:
            alias_text = str(alias).strip()
            if not alias_text:
                continue

            existing = aliases.get(alias_text)
            if existing and existing != area_name:
                raise RuntimeError(
                    f"Duplicate area alias '{alias_text}' is assigned to both '{existing}' and '{area_name}'"
                )
            aliases[alias_text] = area_name

    return areas, aliases


def _load_area_monsters() -> Dict[str, List[Dict[str, Any]]]:
    raw_monsters = _expect_dict(_load_json_file("monsters.json"), "balance/monsters.json")
    area_monsters: Dict[str, List[Dict[str, Any]]] = {}

    for area_name, monster_list in raw_monsters.items():
        monsters = _expect_list(monster_list, f"monsters[{area_name}]")
        area_monsters[area_name] = [
            dict(_expect_dict(monster_data, f"monsters[{area_name}][]"))
            for monster_data in monsters
        ]

    return area_monsters


def _load_equipment_data() -> Dict[str, Any]:
    return _expect_dict(_load_json_file("equipment.json"), "balance/equipment.json")


def _load_world_bosses() -> Dict[str, Dict[str, Any]]:
    raw_world_bosses = _expect_dict(
        _load_json_file("world_bosses.json"),
        "balance/world_bosses.json",
    )
    world_bosses: Dict[str, Dict[str, Any]] = {}

    default_values = {
        "title": "",
        "visual_file": "",
        "spawn_weight": 1.0,
        "join_sec": 120,
        "duration_sec": 120,
        "tick_sec": 2,
        "boss_attack_every_ticks": 2,
        "respawn_sec": 18,
        "respawn_hp_ratio": 0.5,
        "material_key": "",
        "material_label": "",
        "participation_exp": 10,
        "participation_gold": 10,
        "participation_material": 1,
        "clear_exp_bonus": 10,
        "clear_gold_bonus": 10,
        "clear_material_bonus": 0,
        "failure_reward_rate": 0.5,
        "mvp_bonus_rate": 0.5,
        "runner_up_bonus_rate": 0.25,
        "third_bonus_rate": 0.1,
        "min_participation_ticks": 1,
        "min_contribution": 1,
        "aoe_thresholds": [75, 50, 25],
        "enrage_threshold_pct": 20,
        "enrage_atk_bonus": 0,
        "skill_book_exchange_cost": 0,
    }

    for boss_id, boss_data in raw_world_bosses.items():
        safe_boss_id = str(boss_id or "").strip()
        if not safe_boss_id:
            raise RuntimeError("balance/world_bosses.json contains an empty boss id")

        boss = dict(_expect_dict(boss_data, f"world_bosses[{safe_boss_id}]"))
        name = str(boss.get("name", "") or "").strip()
        if not name:
            raise RuntimeError(f"world_bosses[{safe_boss_id}].name must be non-empty")

        normalized: Dict[str, Any] = {"boss_id": safe_boss_id, "name": name}
        normalized["title"] = str(boss.get("title", default_values["title"]) or "").strip()
        normalized["visual_file"] = str(
            boss.get("visual_file", default_values["visual_file"]) or ""
        ).strip()

        numeric_int_fields = (
            "max_hp",
            "atk",
            "def",
            "speed",
            "join_sec",
            "duration_sec",
            "tick_sec",
            "boss_attack_every_ticks",
            "respawn_sec",
            "participation_exp",
            "participation_gold",
            "participation_material",
            "clear_exp_bonus",
            "clear_gold_bonus",
            "clear_material_bonus",
            "min_participation_ticks",
            "min_contribution",
            "enrage_threshold_pct",
            "enrage_atk_bonus",
            "skill_book_exchange_cost",
        )
        for field_name in numeric_int_fields:
            raw_value = boss.get(field_name, default_values.get(field_name, 0))
            if not isinstance(raw_value, (int, float)):
                raise RuntimeError(f"world_bosses[{safe_boss_id}].{field_name} must be numeric")
            normalized[field_name] = int(raw_value)

        float_fields = (
            "spawn_weight",
            "respawn_hp_ratio",
            "failure_reward_rate",
            "mvp_bonus_rate",
            "runner_up_bonus_rate",
            "third_bonus_rate",
        )
        for field_name in float_fields:
            raw_value = boss.get(field_name, default_values[field_name])
            if not isinstance(raw_value, (int, float)):
                raise RuntimeError(f"world_bosses[{safe_boss_id}].{field_name} must be numeric")
            normalized[field_name] = float(raw_value)

        thresholds = boss.get("aoe_thresholds", default_values["aoe_thresholds"])
        if not isinstance(thresholds, list):
            raise RuntimeError(f"world_bosses[{safe_boss_id}].aoe_thresholds must be a JSON array")
        normalized["aoe_thresholds"] = sorted(
            {
                int(threshold)
                for threshold in thresholds
                if isinstance(threshold, (int, float))
            },
            reverse=True,
        )
        if not normalized["aoe_thresholds"]:
            raise RuntimeError(f"world_bosses[{safe_boss_id}].aoe_thresholds must contain at least one threshold")

        normalized["material_key"] = str(
            boss.get("material_key", default_values["material_key"]) or ""
        ).strip()
        normalized["material_label"] = str(
            boss.get("material_label", default_values["material_label"]) or ""
        ).strip()
        if not normalized["material_key"]:
            raise RuntimeError(f"world_bosses[{safe_boss_id}].material_key must be non-empty")
        if not normalized["material_label"]:
            raise RuntimeError(f"world_bosses[{safe_boss_id}].material_label must be non-empty")

        if normalized["max_hp"] <= 0:
            raise RuntimeError(f"world_bosses[{safe_boss_id}].max_hp must be greater than 0")
        if normalized["atk"] <= 0:
            raise RuntimeError(f"world_bosses[{safe_boss_id}].atk must be greater than 0")
        if normalized["def"] < 0:
            raise RuntimeError(f"world_bosses[{safe_boss_id}].def must be 0 or greater")
        if normalized["join_sec"] <= 0:
            raise RuntimeError(f"world_bosses[{safe_boss_id}].join_sec must be greater than 0")
        if normalized["duration_sec"] <= 0:
            raise RuntimeError(f"world_bosses[{safe_boss_id}].duration_sec must be greater than 0")
        if normalized["tick_sec"] <= 0:
            raise RuntimeError(f"world_bosses[{safe_boss_id}].tick_sec must be greater than 0")
        if normalized["boss_attack_every_ticks"] <= 0:
            raise RuntimeError(
                f"world_bosses[{safe_boss_id}].boss_attack_every_ticks must be greater than 0"
            )
        if normalized["respawn_sec"] <= 0:
            raise RuntimeError(f"world_bosses[{safe_boss_id}].respawn_sec must be greater than 0")
        if normalized["skill_book_exchange_cost"] < 0:
            raise RuntimeError(
                f"world_bosses[{safe_boss_id}].skill_book_exchange_cost must be 0 or greater"
            )
        if not 0.0 < normalized["respawn_hp_ratio"] <= 1.0:
            raise RuntimeError(
                f"world_bosses[{safe_boss_id}].respawn_hp_ratio must be greater than 0 and at most 1"
            )
        if not 0.0 <= normalized["failure_reward_rate"] <= 1.0:
            raise RuntimeError(
                f"world_bosses[{safe_boss_id}].failure_reward_rate must be between 0 and 1"
            )
        if normalized["spawn_weight"] <= 0.0:
            raise RuntimeError(f"world_bosses[{safe_boss_id}].spawn_weight must be greater than 0")

        world_bosses[safe_boss_id] = normalized

    return world_bosses


def _load_skills() -> Dict[str, Dict[str, Any]]:
    raw_skills = _expect_dict(_load_json_file("skills.json"), "balance/skills.json")
    skills: Dict[str, Dict[str, Any]] = {}

    for skill_id, skill_data in raw_skills.items():
        safe_skill_id = str(skill_id or "").strip()
        if not safe_skill_id:
            raise RuntimeError("balance/skills.json contains an empty skill id")

        skill = dict(_expect_dict(skill_data, f"skills[{safe_skill_id}]"))
        allowed_keys = {
            "name",
            "type",
            "slot",
            "target",
            "deals_damage",
            "description",
            "aliases",
            "initial_unlocked",
            "sort_order",
            "max_level",
            "levels",
            "infinite_growth",
        }
        unknown_keys = set(skill) - allowed_keys
        if unknown_keys:
            unknown = ", ".join(sorted(unknown_keys))
            raise RuntimeError(f"skills[{safe_skill_id}] contains unknown keys: {unknown}")

        name = str(skill.get("name", "") or "").strip()
        if not name:
            raise RuntimeError(f"skills[{safe_skill_id}].name must be non-empty")

        skill_type = str(skill.get("type", "") or "").strip().lower()
        if skill_type not in {"passive", "active"}:
            raise RuntimeError(f"skills[{safe_skill_id}].type must be 'passive' or 'active'")

        aliases = skill.get("aliases", [])
        if aliases is None:
            aliases = []
        if not isinstance(aliases, list):
            raise RuntimeError(f"skills[{safe_skill_id}].aliases must be a JSON array")
        normalized_aliases = [
            str(alias).strip()
            for alias in aliases
            if str(alias).strip()
        ]

        slot = str(skill.get("slot", "") or "").strip()
        if not slot:
            slot = "active_1" if skill_type == "active" else "passive"
        target = str(skill.get("target", "single_enemy" if skill_type == "active" else "self") or "").strip()
        if target not in {"self", "single_enemy", "all_enemies", "single_ally", "all_allies"}:
            raise RuntimeError(
                f"skills[{safe_skill_id}].target must be one of self/single_enemy/all_enemies/single_ally/all_allies"
            )

        initial_unlocked = bool(skill.get("initial_unlocked", False))
        deals_damage = bool(skill.get("deals_damage", skill_type == "active"))
        sort_order = skill.get("sort_order", 0)
        if not isinstance(sort_order, int):
            raise RuntimeError(f"skills[{safe_skill_id}].sort_order must be an integer")
        raw_max_level = skill.get("max_level")
        max_level: int | None = None
        if raw_max_level is not None:
            if not isinstance(raw_max_level, int) or int(raw_max_level) <= 0:
                raise RuntimeError(f"skills[{safe_skill_id}].max_level must be a positive integer")
            max_level = int(raw_max_level)

        levels = skill.get("levels", [])
        if not isinstance(levels, list) or not levels:
            raise RuntimeError(f"skills[{safe_skill_id}].levels must be a non-empty JSON array")

        normalized_levels: list[Dict[str, Any]] = []
        for index, level_data in enumerate(levels, start=1):
            level_entry = dict(_expect_dict(level_data, f"skills[{safe_skill_id}].levels[{index}]"))
            allowed_level_keys = {
                "description",
                "stats",
                "atk_bonus",
                "def_bonus",
                "speed_bonus",
                "max_hp_bonus",
                "duration_turns",
                "duration_ticks",
                "cooldown_actions",
                "attack_multiplier",
                "action_gauge_bonus",
                "special_effects",
                "upgrade_costs",
            }
            unknown_level_keys = set(level_entry) - allowed_level_keys
            if unknown_level_keys:
                unknown = ", ".join(sorted(unknown_level_keys))
                raise RuntimeError(
                    f"skills[{safe_skill_id}].levels[{index}] contains unknown keys: {unknown}"
                )

            bonuses = normalize_stats(level_entry.get("stats"))
            for stat_name, field_name in (
                ("atk", "atk_bonus"),
                ("def", "def_bonus"),
                ("speed", "speed_bonus"),
                ("max_hp", "max_hp_bonus"),
            ):
                raw_value = level_entry.get(field_name, bonuses.get(stat_name, 0))
                if not isinstance(raw_value, (int, float)):
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].levels[{index}].{field_name} must be numeric"
                    )
                bonuses[stat_name] = max(bonuses[stat_name], int(raw_value))

            raw_attack_multiplier = level_entry.get("attack_multiplier", 1.0)
            if not isinstance(raw_attack_multiplier, (int, float)) or float(raw_attack_multiplier) <= 0.0:
                raise RuntimeError(
                    f"skills[{safe_skill_id}].levels[{index}].attack_multiplier must be greater than 0"
                )
            attack_multiplier = float(raw_attack_multiplier)

            raw_action_gauge_bonus = level_entry.get("action_gauge_bonus", 0)
            if not isinstance(raw_action_gauge_bonus, (int, float)) or int(raw_action_gauge_bonus) < 0:
                raise RuntimeError(
                    f"skills[{safe_skill_id}].levels[{index}].action_gauge_bonus must be a non-negative integer"
                )
            action_gauge_bonus = int(raw_action_gauge_bonus)
            special_effects = _normalize_skill_special_effects(
                level_entry.get("special_effects"),
                f"skills[{safe_skill_id}].levels[{index}].special_effects",
            )

            has_positive_bonus = any(bonuses[stat_name] > 0 for stat_name in STAT_KEYS)
            if (
                not has_positive_bonus
                and attack_multiplier <= 1.0
                and action_gauge_bonus <= 0
                and not special_effects
            ):
                raise RuntimeError(
                    f"skills[{safe_skill_id}].levels[{index}] must define a stat bonus, attack multiplier, action gauge bonus, or special_effects"
                )

            duration_turns = 0
            duration_ticks = 0
            cooldown_actions = 0
            if skill_type == "active":
                raw_duration_turns = level_entry.get("duration_turns", 3)
                raw_duration_ticks = level_entry.get("duration_ticks", raw_duration_turns)
                raw_cooldown_actions = level_entry.get("cooldown_actions", 0)
                if not isinstance(raw_duration_turns, int) or int(raw_duration_turns) < 0:
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].levels[{index}].duration_turns must be a non-negative integer"
                    )
                if not isinstance(raw_duration_ticks, int) or int(raw_duration_ticks) < 0:
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].levels[{index}].duration_ticks must be a non-negative integer"
                    )
                if not isinstance(raw_cooldown_actions, int) or int(raw_cooldown_actions) < 0:
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].levels[{index}].cooldown_actions must be a non-negative integer"
                    )
                duration_turns = int(raw_duration_turns)
                duration_ticks = int(raw_duration_ticks)
                cooldown_actions = int(raw_cooldown_actions)
                if has_positive_bonus and duration_turns <= 0 and duration_ticks <= 0:
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].levels[{index}] with stat bonuses must define duration_turns or duration_ticks"
                    )

            raw_upgrade_costs = level_entry.get("upgrade_costs", {})
            if raw_upgrade_costs is None:
                raw_upgrade_costs = {}
            if not isinstance(raw_upgrade_costs, dict):
                raise RuntimeError(
                    f"skills[{safe_skill_id}].levels[{index}].upgrade_costs must be a JSON object"
                )
            upgrade_costs: Dict[str, int] = {}
            for material_key, raw_cost in raw_upgrade_costs.items():
                safe_material_key = str(material_key or "").strip()
                if not safe_material_key:
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].levels[{index}].upgrade_costs contains an empty material key"
                    )
                if not isinstance(raw_cost, (int, float)) or int(raw_cost) < 0:
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].levels[{index}].upgrade_costs[{safe_material_key}] must be a non-negative integer"
                    )
                if int(raw_cost) > 0:
                    upgrade_costs[safe_material_key] = int(raw_cost)

            normalized_levels.append(
                {
                    "level": index,
                    "description": str(level_entry.get("description", "") or "").strip(),
                    "stats": bonuses,
                    "atk_bonus": bonuses["atk"],
                    "def_bonus": bonuses["def"],
                    "speed_bonus": bonuses["speed"],
                    "max_hp_bonus": bonuses["max_hp"],
                    "duration_turns": duration_turns,
                    "duration_ticks": duration_ticks,
                    "cooldown_actions": cooldown_actions,
                    "attack_multiplier": attack_multiplier,
                    "action_gauge_bonus": action_gauge_bonus,
                    "special_effects": special_effects,
                    "upgrade_costs": upgrade_costs,
                }
            )

        raw_infinite_growth = skill.get("infinite_growth")
        infinite_growth: Dict[str, Any] | None = None
        if raw_infinite_growth is not None:
            growth = dict(_expect_dict(raw_infinite_growth, f"skills[{safe_skill_id}].infinite_growth"))
            allowed_growth_keys = {
                "description_template",
                "atk_bonus_step",
                "def_bonus_step",
                "speed_bonus_step",
                "max_hp_bonus_step",
                "duration_turns_step",
                "duration_turns_every",
                "duration_ticks_step",
                "duration_ticks_every",
                "cooldown_actions_step",
                "cooldown_actions_every",
                "attack_multiplier_step",
                "attack_multiplier_every",
                "action_gauge_bonus_step",
                "action_gauge_bonus_every",
                "upgrade_cost_steps",
            }
            unknown_growth_keys = set(growth) - allowed_growth_keys
            if unknown_growth_keys:
                unknown = ", ".join(sorted(unknown_growth_keys))
                raise RuntimeError(
                    f"skills[{safe_skill_id}].infinite_growth contains unknown keys: {unknown}"
                )

            normalized_growth: Dict[str, Any] = {
                "description_template": str(growth.get("description_template", "") or "").strip(),
            }
            positive_growth_found = False
            for field_name in ("atk_bonus_step", "def_bonus_step", "speed_bonus_step", "max_hp_bonus_step"):
                raw_value = growth.get(field_name, 0)
                if not isinstance(raw_value, (int, float)) or int(raw_value) < 0:
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].infinite_growth.{field_name} must be a non-negative integer"
                    )
                normalized_value = int(raw_value)
                normalized_growth[field_name] = normalized_value
                if normalized_value > 0:
                    positive_growth_found = True

            if skill_type == "active":
                for field_name in ("duration_turns_step", "duration_ticks_step"):
                    raw_value = growth.get(field_name, 0)
                    if not isinstance(raw_value, (int, float)) or int(raw_value) < 0:
                        raise RuntimeError(
                            f"skills[{safe_skill_id}].infinite_growth.{field_name} must be a non-negative integer"
                        )
                    normalized_value = int(raw_value)
                    normalized_growth[field_name] = normalized_value
                    if normalized_value > 0:
                        positive_growth_found = True
                for field_name in ("duration_turns_every", "duration_ticks_every"):
                    raw_value = growth.get(field_name, 1)
                    if not isinstance(raw_value, (int, float)) or int(raw_value) <= 0:
                        raise RuntimeError(
                            f"skills[{safe_skill_id}].infinite_growth.{field_name} must be a positive integer"
                        )
                    normalized_growth[field_name] = int(raw_value)
                for field_name in ("cooldown_actions_step",):
                    raw_value = growth.get(field_name, 0)
                    if not isinstance(raw_value, (int, float)):
                        raise RuntimeError(
                            f"skills[{safe_skill_id}].infinite_growth.{field_name} must be an integer"
                        )
                    normalized_value = int(raw_value)
                    normalized_growth[field_name] = normalized_value
                    if normalized_value != 0:
                        positive_growth_found = True
                raw_cooldown_every = growth.get("cooldown_actions_every", 1)
                if not isinstance(raw_cooldown_every, (int, float)) or int(raw_cooldown_every) <= 0:
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].infinite_growth.cooldown_actions_every must be a positive integer"
                    )
                normalized_growth["cooldown_actions_every"] = int(raw_cooldown_every)
                raw_attack_multiplier_step = growth.get("attack_multiplier_step", 0.0)
                if not isinstance(raw_attack_multiplier_step, (int, float)) or float(raw_attack_multiplier_step) < 0.0:
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].infinite_growth.attack_multiplier_step must be a non-negative number"
                    )
                normalized_growth["attack_multiplier_step"] = float(raw_attack_multiplier_step)
                if float(raw_attack_multiplier_step) > 0.0:
                    positive_growth_found = True
                raw_attack_multiplier_every = growth.get("attack_multiplier_every", 1)
                if not isinstance(raw_attack_multiplier_every, (int, float)) or int(raw_attack_multiplier_every) <= 0:
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].infinite_growth.attack_multiplier_every must be a positive integer"
                    )
                normalized_growth["attack_multiplier_every"] = int(raw_attack_multiplier_every)

                raw_action_gauge_bonus_step = growth.get("action_gauge_bonus_step", 0)
                if not isinstance(raw_action_gauge_bonus_step, (int, float)) or int(raw_action_gauge_bonus_step) < 0:
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].infinite_growth.action_gauge_bonus_step must be a non-negative integer"
                    )
                normalized_growth["action_gauge_bonus_step"] = int(raw_action_gauge_bonus_step)
                if int(raw_action_gauge_bonus_step) > 0:
                    positive_growth_found = True
                raw_action_gauge_bonus_every = growth.get("action_gauge_bonus_every", 1)
                if not isinstance(raw_action_gauge_bonus_every, (int, float)) or int(raw_action_gauge_bonus_every) <= 0:
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].infinite_growth.action_gauge_bonus_every must be a positive integer"
                    )
                normalized_growth["action_gauge_bonus_every"] = int(raw_action_gauge_bonus_every)
            else:
                normalized_growth["duration_turns_step"] = 0
                normalized_growth["duration_ticks_step"] = 0
                normalized_growth["duration_turns_every"] = 1
                normalized_growth["duration_ticks_every"] = 1
                normalized_growth["cooldown_actions_step"] = 0
                normalized_growth["cooldown_actions_every"] = 1
                normalized_growth["attack_multiplier_step"] = 0.0
                normalized_growth["attack_multiplier_every"] = 1
                normalized_growth["action_gauge_bonus_step"] = 0
                normalized_growth["action_gauge_bonus_every"] = 1

            raw_upgrade_cost_steps = growth.get("upgrade_cost_steps", {})
            if raw_upgrade_cost_steps is None:
                raw_upgrade_cost_steps = {}
            if not isinstance(raw_upgrade_cost_steps, dict):
                raise RuntimeError(
                    f"skills[{safe_skill_id}].infinite_growth.upgrade_cost_steps must be a JSON object"
                )
            upgrade_cost_steps: Dict[str, int] = {}
            for material_key, raw_cost_step in raw_upgrade_cost_steps.items():
                safe_material_key = str(material_key or "").strip()
                if not safe_material_key:
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].infinite_growth.upgrade_cost_steps contains an empty material key"
                    )
                if not isinstance(raw_cost_step, (int, float)) or int(raw_cost_step) < 0:
                    raise RuntimeError(
                        f"skills[{safe_skill_id}].infinite_growth.upgrade_cost_steps[{safe_material_key}] must be a non-negative integer"
                    )
                if int(raw_cost_step) > 0:
                    upgrade_cost_steps[safe_material_key] = int(raw_cost_step)
            normalized_growth["upgrade_cost_steps"] = upgrade_cost_steps

            if not positive_growth_found:
                raise RuntimeError(
                    f"skills[{safe_skill_id}].infinite_growth must define at least one positive growth step"
                )
            infinite_growth = normalized_growth

        if max_level is not None:
            if infinite_growth is None and max_level != len(normalized_levels):
                raise RuntimeError(
                    f"skills[{safe_skill_id}].max_level must match levels length unless infinite_growth is set"
                )
            if infinite_growth is not None and max_level < len(normalized_levels):
                raise RuntimeError(
                    f"skills[{safe_skill_id}].max_level must be at least the number of defined levels"
                )

        normalized: Dict[str, Any] = {
            "skill_id": safe_skill_id,
            "name": name,
            "type": skill_type,
            "slot": slot,
            "target": target,
            "deals_damage": deals_damage,
            "description": str(skill.get("description", "") or "").strip(),
            "aliases": normalized_aliases,
            "initial_unlocked": initial_unlocked,
            "sort_order": int(sort_order),
            "max_level": max_level,
            "levels": normalized_levels,
            "infinite_growth": infinite_growth,
        }

        skills[safe_skill_id] = normalized

    return skills


AREAS, AREA_ALIASES = _load_areas()
AREA_MONSTERS = _load_area_monsters()
_equipment_data = _load_equipment_data()
WORLD_BOSSES = _load_world_bosses()
SKILLS = _load_skills()

for area_name in AREA_MONSTERS:
    if area_name not in AREAS:
        raise RuntimeError(f"balance/monsters.json contains unknown area '{area_name}'")

for area_name in AREAS:
    if area_name not in AREA_MONSTERS:
        raise RuntimeError(f"balance/monsters.json is missing monster data for area '{area_name}'")

RARITY_ORDER = _expect_dict(_equipment_data.get("rarity_order"), "equipment.rarity_order")
RARITY_LABEL = _expect_dict(_equipment_data.get("rarity_label"), "equipment.rarity_label")
RARITY_PREFIX = _expect_dict(_equipment_data.get("rarity_prefix"), "equipment.rarity_prefix")
RARITY_POWER_BONUS = _expect_dict(
    _equipment_data.get("rarity_power_bonus"),
    "equipment.rarity_power_bonus",
)
BASE_RARITY_WEIGHTS = _expect_dict(
    _equipment_data.get("base_rarity_weights"),
    "equipment.base_rarity_weights",
)
SLOT_LABEL = _expect_dict(_equipment_data.get("slot_label"), "equipment.slot_label")
ITEM_BASE_NAMES = _expect_dict(_equipment_data.get("item_base_names"), "equipment.item_base_names")
ITEM_SLOT_STAT_WEIGHTS = _expect_dict(
    _equipment_data.get("slot_stat_weights", {}),
    "equipment.slot_stat_weights",
)
LEGENDARY_UNIQUE_NAMES = _expect_dict(
    _equipment_data.get("legendary_unique_names"),
    "equipment.legendary_unique_names",
)
MATERIAL_LABELS = _expect_dict(_equipment_data.get("material_labels"), "equipment.material_labels")
ITEM_SLOT_WEIGHTS = _expect_dict(
    _equipment_data.get("slot_drop_weights"),
    "equipment.slot_drop_weights",
)
_enhancement_data = _expect_dict(_equipment_data.get("enhancement"), "equipment.enhancement")
_enchantment_data = _expect_dict(_equipment_data.get("enchantment", {}), "equipment.enchantment")
ENHANCEMENT_POWER_GAIN = _expect_dict(
    _enhancement_data.get("power_gain"),
    "equipment.enhancement.power_gain",
)
ENHANCEMENT_RARITY_GOLD_BONUS = _expect_dict(
    _enhancement_data.get("rarity_gold_bonus"),
    "equipment.enhancement.rarity_gold_bonus",
)
ENHANCEMENT_SUCCESS_RATES = _expect_list(
    _enhancement_data.get("success_rates"),
    "equipment.enhancement.success_rates",
)
ENHANCEMENT_MAX_LEVEL = int(_enhancement_data.get("max_level", 10))
ENHANCEMENT_MATERIAL_COST_BASE = int(_enhancement_data.get("material_cost_base", 1))
ENHANCEMENT_MATERIAL_COST_STEP = int(_enhancement_data.get("material_cost_step", 1))
ENHANCEMENT_MATERIAL_COST_INTERVAL = int(_enhancement_data.get("material_cost_interval", 3))
ENHANCEMENT_ENDGAME_START_LEVEL = int(_enhancement_data.get("endgame_start_level", ENHANCEMENT_MAX_LEVEL))
ENHANCEMENT_MATERIAL_COST_ENDGAME_STEP = int(
    _enhancement_data.get("material_cost_endgame_step", 0)
)
ENHANCEMENT_DEEP_ENDGAME_START_LEVEL = int(
    _enhancement_data.get("deep_endgame_start_level", ENHANCEMENT_MAX_LEVEL)
)
ENHANCEMENT_MATERIAL_COST_DEEP_ENDGAME_STEP = int(
    _enhancement_data.get("material_cost_deep_endgame_step", 0)
)
ENHANCEMENT_GOLD_COST_BASE = int(_enhancement_data.get("gold_cost_base", 10))
ENHANCEMENT_GOLD_COST_STEP = int(_enhancement_data.get("gold_cost_step", 10))
ENHANCEMENT_GOLD_COST_ENDGAME_STEP = int(_enhancement_data.get("gold_cost_endgame_step", 0))
ENHANCEMENT_GOLD_COST_DEEP_ENDGAME_STEP = int(
    _enhancement_data.get("gold_cost_deep_endgame_step", 0)
)
ENCHANTMENT_MATERIAL_LABELS = _expect_dict(
    _enchantment_data.get("material_labels", {}),
    "equipment.enchantment.material_labels",
)
ENCHANTMENT_EFFECT_LABELS = _expect_dict(
    _enchantment_data.get("effect_labels", {}),
    "equipment.enchantment.effect_labels",
)
ENCHANTMENT_ARMOR_GUARD_COUNT = int(_enchantment_data.get("armor_guard_count", 1))
ENCHANTMENT_WEAPON_CRIT_RATE = float(_enchantment_data.get("weapon_crit_rate", 0.0))
ENCHANTMENT_WEAPON_CRIT_RATE_PER_ENHANCE = float(_enchantment_data.get("weapon_crit_rate_per_enhance", 0.0))
ENCHANTMENT_WEAPON_CRIT_DAMAGE_MULTIPLIER = float(
    _enchantment_data.get("weapon_crit_damage_multiplier", 1.0)
)
ENCHANTMENT_RING_EXP_RATE = float(_enchantment_data.get("ring_exp_rate", 1.0))
ENCHANTMENT_RING_EXP_RATE_PER_ENHANCE = float(_enchantment_data.get("ring_exp_rate_per_enhance", 0.0))
ENCHANTMENT_RING_GOLD_RATE = float(_enchantment_data.get("ring_gold_rate", 1.0))
ENCHANTMENT_RING_GOLD_RATE_PER_ENHANCE = float(_enchantment_data.get("ring_gold_rate_per_enhance", 0.0))
ENCHANTMENT_RING_DROP_RATE_BONUS = float(_enchantment_data.get("ring_drop_rate_bonus", 0.0))
ENCHANTMENT_RING_DROP_RATE_BONUS_PER_ENHANCE = float(
    _enchantment_data.get("ring_drop_rate_bonus_per_enhance", 0.0)
)
ITEM_POWER_PER_TIER = int(_equipment_data.get("power_per_tier", 3))
ITEM_POWER_ROLL_MIN = int(_equipment_data.get("power_roll_min", 1))
ITEM_POWER_ROLL_MAX = int(_equipment_data.get("power_roll_max", 3))
ITEM_VALUE_PER_RARITY_RANK = int(_equipment_data.get("value_per_rarity_rank", 4))
ITEM_MIN_VALUE = int(_equipment_data.get("minimum_item_value", 4))

if ITEM_POWER_ROLL_MAX < ITEM_POWER_ROLL_MIN:
    raise RuntimeError("equipment.power_roll_max must be greater than or equal to power_roll_min")
if ENHANCEMENT_MAX_LEVEL < 0:
    raise RuntimeError("equipment.enhancement.max_level must be 0 or greater")
if len(ENHANCEMENT_SUCCESS_RATES) < ENHANCEMENT_MAX_LEVEL:
    raise RuntimeError(
        "equipment.enhancement.success_rates must contain at least max_level entries"
    )
if ENHANCEMENT_ENDGAME_START_LEVEL < 0 or ENHANCEMENT_ENDGAME_START_LEVEL > ENHANCEMENT_MAX_LEVEL:
    raise RuntimeError(
        "equipment.enhancement.endgame_start_level must be between 0 and max_level"
    )
if (
    ENHANCEMENT_DEEP_ENDGAME_START_LEVEL < ENHANCEMENT_ENDGAME_START_LEVEL
    or ENHANCEMENT_DEEP_ENDGAME_START_LEVEL > ENHANCEMENT_MAX_LEVEL
):
    raise RuntimeError(
        "equipment.enhancement.deep_endgame_start_level must be between endgame_start_level and max_level"
    )
if ENHANCEMENT_MATERIAL_COST_ENDGAME_STEP < 0:
    raise RuntimeError(
        "equipment.enhancement.material_cost_endgame_step must be 0 or greater"
    )
if ENHANCEMENT_MATERIAL_COST_DEEP_ENDGAME_STEP < 0:
    raise RuntimeError(
        "equipment.enhancement.material_cost_deep_endgame_step must be 0 or greater"
    )
if ENHANCEMENT_MATERIAL_COST_INTERVAL <= 0:
    raise RuntimeError("equipment.enhancement.material_cost_interval must be greater than 0")
if ENHANCEMENT_GOLD_COST_ENDGAME_STEP < 0:
    raise RuntimeError("equipment.enhancement.gold_cost_endgame_step must be 0 or greater")
if ENHANCEMENT_GOLD_COST_DEEP_ENDGAME_STEP < 0:
    raise RuntimeError(
        "equipment.enhancement.gold_cost_deep_endgame_step must be 0 or greater"
    )
if ENCHANTMENT_WEAPON_CRIT_DAMAGE_MULTIPLIER < 1.0:
    raise RuntimeError("equipment.enchantment.weapon_crit_damage_multiplier must be 1.0 or greater")

for slot_name in ITEM_SLOT_WEIGHTS:
    if slot_name not in ITEM_BASE_NAMES:
        raise RuntimeError(f"equipment.slot_drop_weights contains unknown slot '{slot_name}'")
    if slot_name not in SLOT_LABEL:
        raise RuntimeError(f"equipment.slot_label is missing slot '{slot_name}'")
    if slot_name not in ITEM_SLOT_STAT_WEIGHTS:
        raise RuntimeError(f"equipment.slot_stat_weights is missing slot '{slot_name}'")

for slot_name in MATERIAL_LABELS:
    if slot_name not in SLOT_LABEL:
        raise RuntimeError(f"equipment.material_labels contains unknown slot '{slot_name}'")

for slot_name, weights in ITEM_SLOT_STAT_WEIGHTS.items():
    if slot_name not in SLOT_LABEL:
        raise RuntimeError(f"equipment.slot_stat_weights contains unknown slot '{slot_name}'")
    safe_weights = _expect_dict(weights, f"equipment.slot_stat_weights[{slot_name}]")
    unknown_stats = set(safe_weights) - set(STAT_KEYS)
    if unknown_stats:
        raise RuntimeError(
            f"equipment.slot_stat_weights[{slot_name}] contains unknown stats: {', '.join(sorted(unknown_stats))}"
        )

for slot_name in ENCHANTMENT_MATERIAL_LABELS:
    if slot_name not in SLOT_LABEL:
        raise RuntimeError(f"equipment.enchantment.material_labels contains unknown slot '{slot_name}'")

for slot_name in ENCHANTMENT_EFFECT_LABELS:
    if slot_name not in SLOT_LABEL:
        raise RuntimeError(f"equipment.enchantment.effect_labels contains unknown slot '{slot_name}'")

for slot_name in ENHANCEMENT_POWER_GAIN:
    if slot_name not in SLOT_LABEL:
        raise RuntimeError(f"equipment.enhancement.power_gain contains unknown slot '{slot_name}'")

_raw_feature_unlock_definitions: Dict[str, Dict[str, Any]] = {}

for area_name, area in AREAS.items():
    max_rarity = area.get("max_rarity")
    if max_rarity is not None and str(max_rarity).strip() not in RARITY_ORDER:
        raise RuntimeError(f"areas[{area_name}].max_rarity contains unknown rarity '{max_rarity}'")

    raw_first_clear_rewards = area.get("first_clear_rewards")
    if raw_first_clear_rewards is not None and not isinstance(raw_first_clear_rewards, dict):
        raise RuntimeError(f"areas[{area_name}].first_clear_rewards must be a JSON object")
    if isinstance(raw_first_clear_rewards, dict):
        allowed_reward_keys = {
            "unlock_slots",
            "unlock_features",
            "auto_explore_fragments",
            "summary",
        }
        unknown_reward_keys = set(raw_first_clear_rewards) - allowed_reward_keys
        if unknown_reward_keys:
            unknown_keys = ", ".join(sorted(unknown_reward_keys))
            raise RuntimeError(
                f"areas[{area_name}].first_clear_rewards contains unknown keys: {unknown_keys}"
            )

        raw_unlock_slots = raw_first_clear_rewards.get("unlock_slots")
        if raw_unlock_slots is not None:
            if not isinstance(raw_unlock_slots, list):
                raise RuntimeError(f"areas[{area_name}].first_clear_rewards.unlock_slots must be a JSON array")
            for index, slot_name in enumerate(raw_unlock_slots):
                safe_slot_name = str(slot_name).strip()
                if safe_slot_name not in SLOT_LABEL:
                    raise RuntimeError(
                        f"areas[{area_name}].first_clear_rewards.unlock_slots[{index}] contains unknown slot '{slot_name}'"
                    )

        raw_unlock_features = raw_first_clear_rewards.get("unlock_features")
        if raw_unlock_features is not None:
            if not isinstance(raw_unlock_features, list):
                raise RuntimeError(
                    f"areas[{area_name}].first_clear_rewards.unlock_features must be a JSON array"
                )
            normalized_unlock_features: List[str] = []
            for index, raw_feature in enumerate(raw_unlock_features):
                feature_label = f"areas[{area_name}].first_clear_rewards.unlock_features[{index}]"
                definition = _normalize_feature_unlock_entry(raw_feature, feature_label)
                feature_key = str(definition.get("key", "") or "").strip()
                if not feature_key:
                    raise RuntimeError(f"{feature_label}.key must be non-empty")
                normalized_unlock_features.append(feature_key)
                current_definition = _raw_feature_unlock_definitions.get(feature_key, {"key": feature_key})
                _raw_feature_unlock_definitions[feature_key] = _merge_feature_unlock_definition(
                    current_definition,
                    definition,
                    feature_key=feature_key,
                    source_label=feature_label,
                )
            raw_first_clear_rewards["unlock_features"] = normalized_unlock_features

        if "auto_explore_fragments" in raw_first_clear_rewards:
            fragment_count = raw_first_clear_rewards["auto_explore_fragments"]
            if not isinstance(fragment_count, int) or int(fragment_count) < 0:
                raise RuntimeError(
                    f"areas[{area_name}].first_clear_rewards.auto_explore_fragments must be a non-negative integer"
                )

        if "summary" in raw_first_clear_rewards and not isinstance(raw_first_clear_rewards["summary"], str):
            raise RuntimeError(f"areas[{area_name}].first_clear_rewards.summary must be a string")

    raw_battle_scaling = area.get("battle_scaling")
    if raw_battle_scaling is not None and not isinstance(raw_battle_scaling, dict):
        raise RuntimeError(f"areas[{area_name}].battle_scaling must be a JSON object")
    if isinstance(raw_battle_scaling, dict):
        numeric_fields = (
            "late_game_start",
            "late_progress_interval",
            "late_hp_multiplier",
            "late_hp_multiplier_per_step",
            "late_hp_acceleration",
            "late_atk_entry_bonus",
            "late_atk_bonus_per_step",
            "late_atk_acceleration",
            "late_def_entry_bonus",
            "late_def_bonus_per_step",
            "late_def_acceleration",
            "late_exp_multiplier",
            "late_exp_multiplier_per_step",
            "late_exp_acceleration",
            "late_gold_multiplier",
            "late_gold_multiplier_per_step",
            "late_gold_acceleration",
            "late_drop_rate_bonus",
            "late_drop_rate_bonus_per_step",
            "late_drop_rate_bonus_acceleration",
            "late_resource_bonus",
            "late_resource_bonus_per_step",
            "late_resource_bonus_acceleration",
        )
        for field_name in numeric_fields:
            if field_name not in raw_battle_scaling:
                continue
            if not isinstance(raw_battle_scaling[field_name], (int, float)):
                raise RuntimeError(f"areas[{area_name}].battle_scaling.{field_name} must be numeric")
        if "late_game_start" in raw_battle_scaling and int(raw_battle_scaling["late_game_start"]) <= 0:
            raise RuntimeError(f"areas[{area_name}].battle_scaling.late_game_start must be greater than 0")
        if (
            "late_progress_interval" in raw_battle_scaling
            and float(raw_battle_scaling["late_progress_interval"]) <= 0
        ):
            raise RuntimeError(
                f"areas[{area_name}].battle_scaling.late_progress_interval must be greater than 0"
            )

    raw_material_drop = area.get("material_drop")
    if raw_material_drop is not None and not isinstance(raw_material_drop, dict):
        raise RuntimeError(f"areas[{area_name}].material_drop must be a JSON object")

    raw_material_drops = area.get("material_drops")
    if raw_material_drops is not None and not isinstance(raw_material_drops, list):
        raise RuntimeError(f"areas[{area_name}].material_drops must be a JSON array")

    raw_enchantment_drops = area.get("enchantment_drops")
    if raw_enchantment_drops is not None and not isinstance(raw_enchantment_drops, list):
        raise RuntimeError(f"areas[{area_name}].enchantment_drops must be a JSON array")

    material_configs: List[Tuple[str, Dict[str, Any]]] = []
    if isinstance(raw_material_drop, dict):
        material_configs.append(("material_drop", raw_material_drop))
    if isinstance(raw_material_drops, list):
        for index, config in enumerate(raw_material_drops):
            if not isinstance(config, dict):
                raise RuntimeError(f"areas[{area_name}].material_drops[{index}] must be a JSON object")
            material_configs.append((f"material_drops[{index}]", config))

    for field_name, config in material_configs:
        slot_name = str(config.get("slot", "")).strip()
        if slot_name not in MATERIAL_LABELS:
            raise RuntimeError(f"areas[{area_name}].{field_name}.slot contains unknown slot '{slot_name}'")

    if isinstance(raw_enchantment_drops, list):
        for index, config in enumerate(raw_enchantment_drops):
            if not isinstance(config, dict):
                raise RuntimeError(f"areas[{area_name}].enchantment_drops[{index}] must be a JSON object")
            slot_name = str(config.get("slot", "")).strip()
            if slot_name not in ENCHANTMENT_MATERIAL_LABELS:
                raise RuntimeError(
                    f"areas[{area_name}].enchantment_drops[{index}].slot contains unknown slot '{slot_name}'"
                )

_feature_unlock_builtin_definitions: Dict[str, Dict[str, Any]] = {
    "auto_repeat": {
        "key": "auto_repeat",
        "label": "自動周回解放",
        "summary": "自動周回解放",
    },
    "armor_slot": {
        "key": "armor_slot",
        "label": "防具スロット解放",
        "summary": "防具スロット解放",
    },
    "ring_slot": {
        "key": "ring_slot",
        "label": "装飾スロット解放",
        "summary": "装飾スロット解放",
    },
}

FEATURE_UNLOCK_DEFINITIONS: Dict[str, Dict[str, Any]] = {}
for feature_key, definition in _raw_feature_unlock_definitions.items():
    normalized_definition = dict(definition)
    label = str(normalized_definition.get("label", "") or "").strip() or feature_key
    normalized_definition["label"] = label
    normalized_definition["summary"] = (
        str(normalized_definition.get("summary", "") or "").strip() or label
    )
    FEATURE_UNLOCK_DEFINITIONS[feature_key] = normalized_definition

for feature_key, definition in _feature_unlock_builtin_definitions.items():
    FEATURE_UNLOCK_DEFINITIONS.setdefault(feature_key, dict(definition))

FEATURE_UNLOCK_LABELS = {
    feature_key: str(definition.get("label", feature_key) or feature_key)
    for feature_key, definition in FEATURE_UNLOCK_DEFINITIONS.items()
}
FEATURE_EFFECT_SUMMARIES = {
    feature_key: str(definition.get("summary", "") or FEATURE_UNLOCK_LABELS.get(feature_key, feature_key)).strip()
    for feature_key, definition in FEATURE_UNLOCK_DEFINITIONS.items()
}

RARE_HUNT_RARITY_BONUS = dict(
    FEATURE_UNLOCK_DEFINITIONS.get("rare_hunt", {}).get("rarity_bonus", {})
)
_weapon_forge_enhancement_bonus = dict(
    FEATURE_UNLOCK_DEFINITIONS.get("weapon_forge", {}).get("enhancement_bonus", {})
)
WEAPON_FORGE_SUCCESS_RATE_BONUS = float(
    _weapon_forge_enhancement_bonus.get("success_rate_bonus", 0.0)
)
WEAPON_FORGE_GOLD_COST_RATE = float(
    _weapon_forge_enhancement_bonus.get("gold_cost_rate", 1.0)
)
WEAPON_FORGE_MATERIAL_DISCOUNT = int(
    _weapon_forge_enhancement_bonus.get("material_discount", 0)
)
_survival_guard_bonus = dict(
    FEATURE_UNLOCK_DEFINITIONS.get("survival_guard", {}).get("guard_bonus", {})
)
SURVIVAL_GUARD_BASE_COUNT = int(_survival_guard_bonus.get("base_count", 0))
