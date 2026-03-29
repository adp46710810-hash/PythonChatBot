from __future__ import annotations

from typing import Any, Dict, Iterable


STAT_KEYS = ("atk", "def", "speed", "max_hp")
GAUGE_THRESHOLD = 100


def empty_stats() -> Dict[str, int]:
    return {key: 0 for key in STAT_KEYS}


def normalize_stats(raw_stats: Any, *, allow_negative: bool = False) -> Dict[str, int]:
    normalized = empty_stats()
    if not isinstance(raw_stats, dict):
        return normalized

    for stat_name, raw_value in raw_stats.items():
        safe_stat_name = str(stat_name or "").strip()
        if safe_stat_name not in normalized:
            continue
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        normalized[safe_stat_name] = value if allow_negative else max(0, value)
    return normalized


def merge_stats(*stat_blocks: Dict[str, Any]) -> Dict[str, int]:
    total = empty_stats()
    for block in stat_blocks:
        for stat_name, value in normalize_stats(block, allow_negative=True).items():
            total[stat_name] += int(value)
    return total


def build_weighted_stats(power: int, weights: Any) -> Dict[str, int]:
    safe_power = max(0, int(power))
    if safe_power <= 0 or not isinstance(weights, dict):
        return empty_stats()

    stats = empty_stats()
    for stat_name, raw_weight in weights.items():
        safe_stat_name = str(stat_name or "").strip()
        if safe_stat_name not in stats:
            continue
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            continue
        stats[safe_stat_name] = max(0, int(round(safe_power * weight)))
    return stats


def nonzero_stats(stats: Dict[str, Any]) -> Dict[str, int]:
    return {
        stat_name: value
        for stat_name, value in normalize_stats(stats).items()
        if int(value) != 0
    }


def format_item_stat_text(slot_name: str, stats: Any, *, power: int = 0) -> str:
    safe_power = max(0, int(power))
    normalized = nonzero_stats(stats)
    safe_slot_name = str(slot_name or "").strip()

    if not normalized and safe_power > 0:
        if safe_slot_name == "weapon":
            normalized = {"atk": safe_power}
        elif safe_slot_name == "armor":
            normalized = {"def": safe_power}
        elif safe_slot_name == "ring":
            normalized = {"atk": safe_power, "def": safe_power}
        elif safe_slot_name == "shoes":
            normalized = {"speed": safe_power}

    parts = []
    for stat_name, label in (("atk", "A"), ("def", "D"), ("speed", "S"), ("max_hp", "HP")):
        value = max(0, int(normalized.get(stat_name, 0)))
        if value > 0:
            parts.append(f"{label}{value}")

    if parts:
        return "/".join(parts)
    return f"P{safe_power}"


def copy_skill_list(skills: Iterable[Dict[str, Any]]) -> list[Dict[str, Any]]:
    copied: list[Dict[str, Any]] = []
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        copied.append(dict(skill))
    return copied
