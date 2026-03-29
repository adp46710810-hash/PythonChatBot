from __future__ import annotations

from typing import Any, Dict, List


ACHIEVEMENT_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "forest_boss_clear": {
        "name": "朝の森初踏破",
        "summary": "朝の森の初回ボスを撃破",
        "title": "森を越えし者",
        "category": "exploration",
        "aliases": ["朝の森", "森を越えし者", "forest"],
    },
    "legendary_finder": {
        "name": "伝説の一品",
        "summary": "初めてレジェンダリー装備を入手",
        "title": "伝説の拾い手",
        "category": "exploration",
        "aliases": ["レジェンダリー", "legendary"],
    },
    "record_breaker": {
        "name": "記録更新",
        "summary": "探索記録を初めて更新",
        "title": "記録更新者",
        "category": "exploration",
        "aliases": ["記録", "record"],
    },
    "auto_repeat_unlocked": {
        "name": "自動周回解放",
        "summary": "自動周回を解放",
        "title": "巡回解放者",
        "category": "exploration",
        "aliases": ["自動周回", "auto repeat", "loop"],
    },
    "wb_first_join": {
        "name": "初陣共闘",
        "summary": "ワールドボスに初参加",
        "title": "共闘者",
        "category": "world_boss",
        "aliases": ["WB参加", "共闘者", "join"],
    },
    "wb_first_clear": {
        "name": "WB初討伐",
        "summary": "ワールドボス討伐に初成功",
        "title": "討伐功労者",
        "category": "world_boss",
        "aliases": ["WB討伐", "討伐功労者", "clear"],
    },
    "wb_top_three": {
        "name": "WB上位入賞",
        "summary": "ワールドボスでTop3入賞",
        "title": "上位狩り",
        "category": "world_boss",
        "aliases": ["Top3", "上位狩り", "top3"],
    },
    "wb_mvp": {
        "name": "WB MVP",
        "summary": "ワールドボスでMVP獲得",
        "title": "MVP",
        "category": "world_boss",
        "aliases": ["MVP", "wbmvp"],
    },
}


ACHIEVEMENT_ORDER: List[str] = list(ACHIEVEMENT_DEFINITIONS.keys())


def get_achievement_definition(achievement_id: str) -> Dict[str, Any]:
    return dict(ACHIEVEMENT_DEFINITIONS.get(str(achievement_id or "").strip(), {}))
