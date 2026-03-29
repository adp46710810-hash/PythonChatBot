from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

RETURN_PHASE_PREBATTLE = "prebattle"
RETURN_PHASE_POSTBATTLE = "postbattle"
RETURN_PHASE_BATTLE_ESCAPE = "battle_escape"
RETURN_PHASE_DEFEAT = "defeat"
RETURN_PHASE_BATTLE_CAP = "battle_cap"
RETURN_PHASE_COMPLETE = "complete"
RETURN_PHASE_UNKNOWN = "unknown"

RETURN_INFO_PATTERNS = (
    (
        re.compile(r"^第(?P<battle>\d+)戦の (?P<monster>.+?) を危険と判断して帰還$"),
        RETURN_PHASE_PREBATTLE,
        "危険判断で帰還",
    ),
    (
        re.compile(r"^第(?P<battle>\d+)戦の (?P<monster>.+?) 戦後にHP低下のため安全帰還$"),
        RETURN_PHASE_POSTBATTLE,
        "HP低下のため安全帰還",
    ),
    (
        re.compile(r"^第(?P<battle>\d+)戦の (?P<monster>.+?) で致死耐性が発動したため緊急帰還$"),
        RETURN_PHASE_BATTLE_ESCAPE,
        "致死耐性発動で緊急帰還",
    ),
    (
        re.compile(r"^第(?P<battle>\d+)戦の (?P<monster>.+?) に倒された$"),
        RETURN_PHASE_DEFEAT,
        "敗北",
    ),
    (
        re.compile(
            r"^第(?P<battle>\d+)戦の (?P<monster>.+?) 撃破後、"
            r"戦闘回数が(?P<limit>\d+)回に達したため帰還$"
        ),
        RETURN_PHASE_BATTLE_CAP,
        "戦闘回数上限で帰還",
    ),
)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_actual_battle_logs(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    battle_logs = result.get("battle_logs", [])
    if not isinstance(battle_logs, list):
        return []

    return [
        battle
        for battle in battle_logs
        if isinstance(battle, dict) and str(battle.get("monster", "?")) != "ポーション使用"
    ]


def get_battle_count(result: Dict[str, Any]) -> int:
    stored = _safe_int(result.get("battle_count", 0), 0)
    actual_count = len(get_actual_battle_logs(result))
    if actual_count > 0:
        return actual_count
    return max(0, stored)


def _build_return_location(
    battle_number: Optional[int],
    monster: Optional[str],
    phase: str,
) -> str:
    safe_monster = str(monster or "").strip()
    safe_battle_number = max(0, _safe_int(battle_number, 0))

    if phase == RETURN_PHASE_COMPLETE:
        return "なし"

    if safe_battle_number <= 0 and not safe_monster:
        return "不明"

    battle_label = ""
    if safe_battle_number > 0:
        suffix = {
            RETURN_PHASE_PREBATTLE: "戦前",
            RETURN_PHASE_POSTBATTLE: "戦後",
            RETURN_PHASE_BATTLE_ESCAPE: "戦中",
            RETURN_PHASE_BATTLE_CAP: "戦後",
        }.get(phase, "戦")
        battle_label = f"第{safe_battle_number}{suffix}"

    parts = [part for part in (battle_label, safe_monster) if part]
    return " / ".join(parts) if parts else "不明"


def build_return_info(
    *,
    battle_number: Optional[int] = None,
    monster: Optional[str] = None,
    phase: str = RETURN_PHASE_UNKNOWN,
    reason: Optional[str] = None,
    raw_reason: Optional[str] = None,
) -> Dict[str, Any]:
    safe_phase = str(phase or RETURN_PHASE_UNKNOWN).strip() or RETURN_PHASE_UNKNOWN
    safe_raw_reason = str(raw_reason or "").strip()
    safe_reason = str(reason or safe_raw_reason or "不明").strip() or "不明"
    safe_battle_number = max(0, _safe_int(battle_number, 0))
    safe_monster = str(monster or "").strip()
    return {
        "battle_number": safe_battle_number,
        "monster": safe_monster,
        "phase": safe_phase,
        "location": _build_return_location(safe_battle_number, safe_monster, safe_phase),
        "reason": safe_reason,
        "raw_reason": safe_raw_reason or safe_reason,
    }


def infer_return_info(return_reason: Any) -> Dict[str, Any]:
    safe_reason = str(return_reason or "").strip() or "探索終了"
    if safe_reason == "探索終了":
        return build_return_info(
            phase=RETURN_PHASE_COMPLETE,
            reason="探索終了",
            raw_reason=safe_reason,
        )

    for pattern, phase, reason in RETURN_INFO_PATTERNS:
        match = pattern.match(safe_reason)
        if not match:
            continue
        return build_return_info(
            battle_number=_safe_int(match.groupdict().get("battle"), 0),
            monster=match.groupdict().get("monster"),
            phase=phase,
            reason=reason,
            raw_reason=safe_reason,
        )

    return build_return_info(
        phase=RETURN_PHASE_UNKNOWN,
        reason=safe_reason,
        raw_reason=safe_reason,
    )


def sanitize_return_info(return_info: Any, return_reason: Any) -> Dict[str, Any]:
    if not isinstance(return_info, dict):
        return infer_return_info(return_reason)

    normalized = build_return_info(
        battle_number=return_info.get("battle_number", 0),
        monster=return_info.get("monster"),
        phase=str(return_info.get("phase", RETURN_PHASE_UNKNOWN)).strip() or RETURN_PHASE_UNKNOWN,
        reason=return_info.get("reason"),
        raw_reason=return_info.get("raw_reason") or return_reason,
    )
    if normalized["phase"] == RETURN_PHASE_UNKNOWN and str(return_reason or "").strip():
        inferred = infer_return_info(return_reason)
        if inferred["phase"] != RETURN_PHASE_UNKNOWN:
            return inferred
    return normalized


def format_return_footer(result: Dict[str, Any]) -> str:
    return_reason = str(result.get("return_reason", "探索終了") or "探索終了").strip() or "探索終了"
    return_info = sanitize_return_info(result.get("return_info"), return_reason)
    return f"撤退情報: {return_info['location']} / 理由 {return_info['reason']}"
