from __future__ import annotations

from .balance_data import (
    AREA_ALIASES,
    AREA_MONSTERS,
    AREAS,
    BASE_RARITY_WEIGHTS,
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
    FEATURE_EFFECT_SUMMARIES,
    FEATURE_UNLOCK_DEFINITIONS,
    FEATURE_UNLOCK_LABELS,
    ITEM_BASE_NAMES,
    ITEM_MIN_VALUE,
    ITEM_POWER_PER_TIER,
    ITEM_POWER_ROLL_MAX,
    ITEM_POWER_ROLL_MIN,
    ITEM_SLOT_WEIGHTS,
    ITEM_SLOT_STAT_WEIGHTS,
    ITEM_VALUE_PER_RARITY_RANK,
    LEGENDARY_UNIQUE_NAMES,
    MATERIAL_LABELS,
    RARITY_LABEL,
    RARITY_ORDER,
    RARITY_POWER_BONUS,
    RARITY_PREFIX,
    RARE_HUNT_RARITY_BONUS,
    SKILLS,
    SLOT_LABEL,
    SURVIVAL_GUARD_BASE_COUNT,
    WEAPON_FORGE_GOLD_COST_RATE,
    WEAPON_FORGE_MATERIAL_DISCOUNT,
    WEAPON_FORGE_SUCCESS_RATE_BONUS,
    WORLD_BOSSES,
)

EXP_GAIN_MULTIPLIER = 5.0

CHAT_EXP_ENABLED = True
CHAT_EXP_MIN_INTERVAL_SEC = 30.0
CHAT_EXP_PER_MSG = max(1, int(round(2 * EXP_GAIN_MULTIPLIER)))
CHAT_EXP_RPG_WEIGHT = 1.0
CHAT_EXP_NOTIFY = False

AUTO_EXPLORE_STONE_NAME = "自動周回石"
AUTO_EXPLORE_STONE_DROP_RATE = 0.00001
AUTO_REPEAT_UNLOCK_FRAGMENT_REQUIREMENT = 3

LEVEL_EARLY_END = 20
LEVEL_MID_END = 50
LEVEL_EARLY_EXP_BASE = 14
LEVEL_EARLY_EXP_STEP = 2
LEVEL_MID_EXP_BASE = 58
LEVEL_MID_EXP_STEP = 6
LEVEL_LATE_EXP_BASE = 240
LEVEL_LATE_EXP_STEP = 18
LEVEL_LATE_EXP_ACCELERATION = 5

DEFAULT_MAX_HP = 70
POTION_PRICE = 150
POTION_HEAL_MIN = 35
POTION_HEAL_RATIO = 0.20
STARTER_POTION_COUNT = 2
RETURN_HEAL_GOLD_PER_MISSING_HP = 0.10
EXPLORATION_SECONDS_PER_TURN = 10
# Use real exploration timing by default. Tests can patch this override when needed.
EXPLORATION_DURATION_OVERRIDE_SEC = None
AUTO_REPEAT_COOLDOWN_SEC = 5

MAX_POTIONS_PER_EXPLORATION = 5
MAX_BATTLES_PER_EXPLORATION = 50
MAX_AUTO_REPEAT_EXPLORATIONS = 50

BATTLE_ESCALATION_INTERVAL = 5
BOSS_BATTLE_INTERVAL = 10
BATTLE_GROWTH_ACCELERATION = 0.12
BATTLE_HP_SCALE_PER_GROWTH = 0.55
BATTLE_ATK_BONUS_PER_GROWTH = 6.5
BATTLE_DEF_BONUS_PER_GROWTH = 1.4
BATTLE_EXP_SCALE_PER_GROWTH = 0.22
BATTLE_GOLD_SCALE_PER_GROWTH = 0.18
BATTLE_DROP_RATE_PER_GROWTH = 0.02

BATTLE_LATE_GAME_START = 20
BATTLE_LATE_GAME_HP_MULTIPLIER = 1.70
BATTLE_LATE_GAME_HP_MULTIPLIER_PER_STEP = 0.30
BATTLE_LATE_GAME_HP_ACCELERATION = 0.05
BATTLE_LATE_GAME_ATK_ENTRY_BONUS = 38
BATTLE_LATE_GAME_ATK_BONUS_PER_STEP = 9
BATTLE_LATE_GAME_ATK_ACCELERATION = 2
BATTLE_LATE_GAME_DEF_ENTRY_BONUS = 10
BATTLE_LATE_GAME_DEF_BONUS_PER_STEP = 4
BATTLE_LATE_GAME_DEF_ACCELERATION = 1
BATTLE_LATE_GAME_EXP_MULTIPLIER = 1.60
BATTLE_LATE_GAME_EXP_MULTIPLIER_PER_STEP = 0.12
BATTLE_LATE_GAME_EXP_ACCELERATION = 0.03
BATTLE_LATE_GAME_GOLD_MULTIPLIER = 1.40
BATTLE_LATE_GAME_GOLD_MULTIPLIER_PER_STEP = 0.22
BATTLE_LATE_GAME_GOLD_ACCELERATION = 0.05
BATTLE_LATE_GAME_DROP_RATE_BONUS = 0.06
BATTLE_LATE_GAME_DROP_RATE_BONUS_PER_STEP = 0.03
BATTLE_LATE_GAME_DROP_RATE_BONUS_ACCELERATION = 0.006
BATTLE_LATE_GAME_RESOURCE_BONUS = 0.0
BATTLE_LATE_GAME_RESOURCE_BONUS_PER_STEP = 0.60
BATTLE_LATE_GAME_RESOURCE_BONUS_ACCELERATION = 0.08

ELITE_MONSTER_HP_SCALE = 1.45
ELITE_MONSTER_ATK_BONUS = 5
ELITE_MONSTER_DEF_BONUS = 3
ELITE_MONSTER_EXP_SCALE = 1.75
ELITE_MONSTER_GOLD_SCALE = 1.55
ELITE_MONSTER_DROP_RATE_BONUS = 0.12

BOSS_MONSTER_HP_SCALE = 3.80
BOSS_MONSTER_ATK_BONUS = 18
BOSS_MONSTER_DEF_BONUS = 10
BOSS_MONSTER_EXP_SCALE = 3.60
BOSS_MONSTER_GOLD_SCALE = 2.80
BOSS_MONSTER_DROP_RATE_BONUS = 0.25

RING_TIME_REDUCTION_PER_POWER = 0.03
RING_TIME_REDUCTION_MAX = 0.45
EXPLORATION_TIME_SCALE = 0.005

SAFE_RETURN_HP_RATIO = 0.30
SAFE_RETURN_MIN_HP = 10

DEFAULT_EXPLORATION_MODE = "normal"
BEGINNER_CAUTIOUS_RECOMMENDATION_COUNT = 3
EXPLORATION_MODE_CONFIG = {
    "cautious": {
        "label": "慎重",
        "aliases": ("慎重", "しんちょう", "careful", "cautious"),
        "prebattle_hp_ratio": 0.72,
        "prebattle_min_hp": 26,
        "postbattle_hp_ratio": 0.60,
        "postbattle_min_hp": 22,
        "fatal_risk_last_hit_margin": 0,
        "risk_ramp_start_battle": 11,
        "risk_ramp_interval": 5,
        "risk_prebattle_hp_ratio_penalty": 0.0,
        "risk_prebattle_min_hp_penalty": 0,
        "risk_fatal_margin_bonus": 0,
        "conservative_damage_check": True,
        "exp_rate": 0.92,
        "gold_rate": 0.92,
    },
    "normal": {
        "label": "通常",
        "aliases": ("通常", "ふつう", "normal"),
        "prebattle_hp_ratio": 0.40,
        "prebattle_min_hp": 12,
        "postbattle_hp_ratio": SAFE_RETURN_HP_RATIO,
        "postbattle_min_hp": SAFE_RETURN_MIN_HP,
        "fatal_risk_last_hit_margin": 1,
        "risk_ramp_start_battle": 11,
        "risk_ramp_interval": 5,
        "risk_prebattle_hp_ratio_penalty": 0.05,
        "risk_prebattle_min_hp_penalty": 2,
        "risk_fatal_margin_bonus": 1,
        "conservative_damage_check": False,
        "exp_rate": 1.0,
        "gold_rate": 1.0,
    },
    "saving": {
        "label": "節約",
        "aliases": ("節約", "節約モード", "せつやく", "saving", "eco", "economy"),
        "prebattle_hp_ratio": 0.40,
        "prebattle_min_hp": 12,
        "postbattle_hp_ratio": SAFE_RETURN_HP_RATIO,
        "postbattle_min_hp": SAFE_RETURN_MIN_HP,
        "fatal_risk_last_hit_margin": 0,
        "risk_ramp_start_battle": 11,
        "risk_ramp_interval": 5,
        "risk_prebattle_hp_ratio_penalty": 0.04,
        "risk_prebattle_min_hp_penalty": 1,
        "risk_fatal_margin_bonus": 0,
        "conservative_damage_check": False,
        "exp_rate": 1.0,
        "gold_rate": 1.0,
        "max_potions_to_use": 2,
    },
    "reckless": {
        "label": "強行",
        "aliases": ("強行", "ごうこう", "reckless", "hard"),
        "prebattle_hp_ratio": 0.16,
        "prebattle_min_hp": 4,
        "postbattle_hp_ratio": 0.10,
        "postbattle_min_hp": 3,
        "fatal_risk_last_hit_margin": 2,
        "risk_ramp_start_battle": 11,
        "risk_ramp_interval": 4,
        "risk_prebattle_hp_ratio_penalty": 0.06,
        "risk_prebattle_min_hp_penalty": 2,
        "risk_fatal_margin_bonus": 1,
        "conservative_damage_check": False,
        "exp_rate": 1.18,
        "gold_rate": 1.12,
    },
}

EXPLORATION_PREPARATION_CONFIG = {
    "weapon": {
        "material_cost": 8,
        "atk": 6,
    },
    "armor": {
        "material_cost": 8,
        "def": 6,
    },
    "ring": {
        "material_cost": 8,
        "exp_rate": 1.08,
        "gold_rate": 1.08,
        "drop_bonus": 0.03,
    },
    "shoes": {
        "material_cost": 8,
        "speed": 30,
    },
}

ARMOR_LETHAL_GUARD_POWER_STEP = 10
ARMOR_LETHAL_GUARD_MAX = 2

DOWNED_EXP_KEEP_RATE = 0.55
DOWNED_MATERIAL_KEEP_RATE = 0.55
DOWNED_GOLD_KEEP_RATE = 0.25

BASE_PLAYER_ATK = 5
BASE_PLAYER_DEF = 2
BASE_PLAYER_SPEED = 100
DEFAULT_MONSTER_SPEED = 100

DEFAULT_AREA = "朝の森"
BEGINNER_GUARANTEE_AREA = "朝の森"
BEGINNER_GUARANTEE_MAX_LEVEL = 5

if DEFAULT_AREA not in AREAS:
    raise RuntimeError(f"Default area '{DEFAULT_AREA}' is missing from data/balance/areas.json")

__all__ = [name for name in globals() if name.isupper()]
