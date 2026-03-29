from __future__ import annotations

import argparse
import json
import random
from statistics import mean
from typing import Any, Dict, List, Optional

from rpg_core.manager import RPGManager
from rpg_core.rules import AREAS

SLOT_ALIASES = {
    "武器": "weapon",
    "防具": "armor",
    "装飾": "ring",
    "靴": "shoes",
}


def organize_player(manager: RPGManager, username: str) -> None:
    changed = True
    while changed:
        changed = manager.autoequip_best(username)
    manager.sell_all_bag_items(username)


def execute_action(manager: RPGManager, username: str, action: str) -> Dict[str, Any]:
    record: Dict[str, Any] = {"action": action}

    if action in {"!整理", "!装備 整理"}:
        organize_player(manager, username)
        record["kind"] = "organize"
        return record

    if action in {"!蘇生", "!状態 蘇生"}:
        ok, message = manager.revive_user(username)
        if not ok:
            raise RuntimeError(message)
        record["kind"] = "revive"
        record["message"] = message
        return record

    if action in {"!ポーション購入", "!状態 ポーション"}:
        ok, message = manager.buy_potions(username)
        if not ok:
            raise RuntimeError(message)
        record["kind"] = "buy_potions"
        record["message"] = message
        return record

    if action.startswith("!探索 準備 "):
        slot_text = action.split(" ", 2)[-1].strip()
        slot_name = SLOT_ALIASES[slot_text]
        ok, message = manager.prepare_exploration(username, slot_name)
        if not ok:
            raise RuntimeError(message)
        record["kind"] = "prepare"
        record["slot"] = slot_name
        record["message"] = message
        return record

    if action.startswith("!エンチャント ") or action.startswith("!装備 エンチャント "):
        slot_text = action.split(" ", 2)[-1].strip()
        slot_name = SLOT_ALIASES[slot_text]
        ok, message = manager.enchant_equipped_item(username, slot_name)
        if not ok:
            raise RuntimeError(message)
        record["kind"] = "enchant"
        record["slot"] = slot_name
        record["message"] = message
        return record

    if action.startswith("!探索 結果"):
        message = manager.finalize_exploration(username)
        record["kind"] = "claim"
        record["message"] = message
        user = manager.get_user(username)
        result = user.get("last_exploration_result")
        if isinstance(result, dict):
            record["result"] = {
                "area": str(result.get("area", "") or ""),
                "battle_count": max(0, int(result.get("battle_count", 0))),
                "gold": max(0, int(result.get("gold", 0))),
                "exp": max(0, int(result.get("exp", 0))),
                "downed": bool(result.get("downed", False)),
                "newly_cleared_boss_areas": list(result.get("newly_cleared_boss_areas", [])),
            }
        return record

    if action.startswith("!探索 開始 "):
        area_text = action.split(" ", 2)[2].strip()
        ok, message = manager.start_exploration(username, area_text)
        if not ok:
            raise RuntimeError(message)
        user = manager.get_user(username)
        user["explore"]["ends_at"] = 0
        record["kind"] = "start"
        record["area_text"] = area_text
        record["message"] = message
        return record

    if action.startswith("!探索開始 "):
        area_text = action.split(" ", 1)[1].strip()
        ok, message = manager.start_exploration(username, area_text)
        if not ok:
            raise RuntimeError(message)
        user = manager.get_user(username)
        user["explore"]["ends_at"] = 0
        record["kind"] = "start"
        record["area_text"] = area_text
        record["message"] = message
        return record

    raise RuntimeError(f"Unhandled action: {action}")


def run_progression(seed: int, max_steps: int) -> Dict[str, Any]:
    random.seed(seed)
    manager = RPGManager({"users": {}})
    username = f"sim{seed}"
    trace: List[Dict[str, Any]] = []
    milestone_steps: Dict[str, int] = {}
    zero_battle_counts = {area_name: 0 for area_name in AREAS}
    low_progress_counts = {area_name: 0 for area_name in AREAS}
    command_counts = {
        "start": 0,
        "claim": 0,
        "organize": 0,
        "enchant": 0,
        "buy_potions": 0,
        "revive": 0,
    }

    for step in range(1, max_steps + 1):
        user = manager.get_user(username)
        recommendation = manager.build_next_recommendation(user)
        action = str(recommendation.get("action", "") or "").strip()
        event = execute_action(manager, username, action)
        kind = str(event.get("kind", "") or "")
        if kind in command_counts:
            command_counts[kind] += 1

        if kind == "claim":
            result = event.get("result") or {}
            area_name = str(result.get("area", "") or "").strip()
            battle_count = max(0, int(result.get("battle_count", 0)))
            if area_name in zero_battle_counts and battle_count <= 0:
                zero_battle_counts[area_name] += 1
            if area_name in low_progress_counts and battle_count <= 1:
                low_progress_counts[area_name] += 1
            for cleared_area in result.get("newly_cleared_boss_areas", []):
                safe_area = str(cleared_area or "").strip()
                if safe_area and safe_area not in milestone_steps:
                    milestone_steps[safe_area] = step

        if (
            manager.get_user(username).get("feature_unlocks", {}).get("auto_repeat", False)
            and kind == "claim"
        ):
            milestone_steps.setdefault("auto_repeat", step)
            break

        trace.append(
            {
                "step": step,
                "action": action,
                "kind": kind,
                "summary": str(recommendation.get("summary", "") or ""),
                "message": str(event.get("message", "") or ""),
            }
        )

    user = manager.get_user(username)
    equipped = {
        slot_name: (item or {}).get("name") if isinstance(item, dict) else None
        for slot_name, item in user.get("equipped", {}).items()
    }
    last_result = user.get("last_exploration_result")
    return {
        "seed": seed,
        "steps": step,
        "milestones": milestone_steps,
        "command_counts": command_counts,
        "zero_battle_counts": zero_battle_counts,
        "low_progress_counts": low_progress_counts,
        "trace_tail": trace[-12:],
        "adventure_level": manager.get_adventure_level(user),
        "gold": max(0, int(user.get("gold", 0))),
        "hp": max(0, int(user.get("hp", 0))),
        "max_hp": max(1, int(user.get("max_hp", 1))),
        "potions": max(0, int(user.get("potions", 0))),
        "materials": dict(user.get("materials", {})),
        "enchant_materials": dict(user.get("enchant_materials", {})),
        "boss_clear_areas": list(user.get("boss_clear_areas", [])),
        "auto_repeat_unlocked": bool(user.get("feature_unlocks", {}).get("auto_repeat", False)),
        "equipped": equipped,
        "last_result": dict(last_result) if isinstance(last_result, dict) else None,
    }


def summarize_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    milestone_labels = [
        "朝の森",
        "三日月廃墟",
        "ヘッセ深部",
        "紅蓮の鉱山",
        "沈黙の城塞跡",
        "星影の祭壇",
        "auto_repeat",
    ]
    milestone_summary: Dict[str, Dict[str, Any]] = {}
    for label in milestone_labels:
        reached = [int(result["milestones"][label]) for result in results if label in result["milestones"]]
        milestone_summary[label] = {
            "reached": len(reached),
            "avg_step": round(mean(reached), 2) if reached else None,
            "max_step": max(reached) if reached else None,
        }

    zero_battle_totals = {area_name: 0 for area_name in AREAS}
    low_progress_totals = {area_name: 0 for area_name in AREAS}
    for result in results:
        for area_name, count in result["zero_battle_counts"].items():
            zero_battle_totals[area_name] += int(count)
        for area_name, count in result["low_progress_counts"].items():
            low_progress_totals[area_name] += int(count)

    return {
        "runs": len(results),
        "auto_repeat_unlock_rate": round(
            sum(1 for result in results if result["auto_repeat_unlocked"]) / max(1, len(results)),
            4,
        ),
        "avg_steps": round(mean(result["steps"] for result in results), 2),
        "max_steps": max(result["steps"] for result in results),
        "avg_adventure_level": round(mean(result["adventure_level"] for result in results), 2),
        "avg_gold_left": round(mean(result["gold"] for result in results), 2),
        "avg_potions_left": round(mean(result["potions"] for result in results), 2),
        "avg_hp_ratio": round(
            mean(result["hp"] / max(1, result["max_hp"]) for result in results),
            4,
        ),
        "avg_weapon_materials_left": round(
            mean(result["materials"].get("weapon", 0) for result in results),
            2,
        ),
        "avg_armor_materials_left": round(
            mean(result["materials"].get("armor", 0) for result in results),
            2,
        ),
        "avg_ring_materials_left": round(
            mean(result["materials"].get("ring", 0) for result in results),
            2,
        ),
        "avg_weapon_enchant_materials_left": round(
            mean(result["enchant_materials"].get("weapon", 0) for result in results),
            2,
        ),
        "avg_command_counts": {
            key: round(mean(result["command_counts"][key] for result in results), 2)
            for key in results[0]["command_counts"]
        },
        "milestones": milestone_summary,
        "zero_battle_totals": zero_battle_totals,
        "low_progress_totals": low_progress_totals,
    }


def print_report(results: List[Dict[str, Any]], summary: Dict[str, Any], show_traces: int) -> None:
    print("=" * 80)
    print("RPG progression balance report")
    print("=" * 80)
    print()
    print(f"Runs: {summary['runs']}")
    print(f"Auto-repeat unlock rate: {summary['auto_repeat_unlock_rate'] * 100:.1f}%")
    print(f"Average commands to unlock: {summary['avg_steps']}")
    print(f"Slowest unlock path: {summary['max_steps']} commands")
    print(f"Average adventure level at stop: {summary['avg_adventure_level']}")
    print()

    print("Economy and resources")
    print("-" * 80)
    print(f"Average gold left: {summary['avg_gold_left']}G")
    print(f"Average potions left: {summary['avg_potions_left']}")
    print(f"Average HP ratio at stop: {summary['avg_hp_ratio'] * 100:.1f}%")
    print(
        "Materials left:"
        f" weapon {summary['avg_weapon_materials_left']},"
        f" armor {summary['avg_armor_materials_left']},"
        f" ring {summary['avg_ring_materials_left']},"
        f" weapon-enchant {summary['avg_weapon_enchant_materials_left']}"
    )
    print()

    print("Average command usage")
    print("-" * 80)
    for key, value in summary["avg_command_counts"].items():
        print(f"{key:12} {value}")
    print()

    print("Milestones")
    print("-" * 80)
    for label, data in summary["milestones"].items():
        if data["avg_step"] is None:
            print(f"{label:12} unreached")
            continue
        print(
            f"{label:12} reached {data['reached']}/{summary['runs']}"
            f" runs, avg {data['avg_step']}, max {data['max_step']}"
        )
    print()

    print("Areas with many thin returns")
    print("-" * 80)
    ranked_areas = sorted(
        AREAS,
        key=lambda area_name: (
            summary["low_progress_totals"].get(area_name, 0),
            summary["zero_battle_totals"].get(area_name, 0),
        ),
        reverse=True,
    )
    for area_name in ranked_areas:
        low_progress = int(summary["low_progress_totals"].get(area_name, 0))
        zero_battles = int(summary["zero_battle_totals"].get(area_name, 0))
        print(f"{area_name:12} low-progress {low_progress:4d} / zero-battle {zero_battles:4d}")
    print()

    observations: List[str] = []
    if summary["avg_gold_left"] <= 10:
        observations.append("Gold is usually exhausted by the time auto-repeat unlocks.")
    if summary["avg_weapon_materials_left"] >= 100:
        observations.append("Weapon materials accumulate faster than the default flow consumes them.")
    if summary["low_progress_totals"].get("紅蓮の鉱山", 0) >= summary["runs"]:
        observations.append("Crimson Mine often produces thin progress during the unlock path.")
    if summary["low_progress_totals"].get("星影の祭壇", 0) >= summary["runs"]:
        observations.append("Star Shrine can take several low-battle runs before the first clear lands.")

    print("Observations")
    print("-" * 80)
    if observations:
        for note in observations:
            print(f"- {note}")
    else:
        print("- No strong anomalies crossed the current thresholds.")
    print()

    longest = sorted(results, key=lambda result: result["steps"], reverse=True)[:show_traces]
    print("Longest traces")
    print("-" * 80)
    for result in longest:
        print(
            f"seed {result['seed']}: steps {result['steps']},"
            f" bosses {', '.join(result['boss_clear_areas']) or '-'},"
            f" gold {result['gold']}G,"
            f" potions {result['potions']}"
        )
        for event in result["trace_tail"]:
            print(
                f"  step {event['step']:>3}: {event['action']}"
                f" | {event['summary'] or event['message']}"
            )
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run level-0 progression simulations and print a report.")
    parser.add_argument("--seeds", type=int, default=20, help="How many random seeds to simulate.")
    parser.add_argument("--max-steps", type=int, default=140, help="Maximum commands per seed.")
    parser.add_argument("--show-traces", type=int, default=3, help="How many long traces to print.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the raw summary as JSON after the text report.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results = [run_progression(seed, max_steps=max(1, int(args.max_steps))) for seed in range(max(1, int(args.seeds)))]
    summary = summarize_results(results)
    print_report(results, summary, show_traces=max(0, int(args.show_traces)))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
