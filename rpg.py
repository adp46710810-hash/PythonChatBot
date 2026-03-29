from __future__ import annotations

from rpg_core import (
    BouyomiClient,
    RPGManager,
    atomic_save_json,
    load_json,
    looks_spammy,
    nfkc,
    norm_key,
    now_ts,
)
from rpg_core.rules import RARITY_ORDER

__all__ = [
    "BouyomiClient",
    "RPGManager",
    "atomic_save_json",
    "load_json",
    "looks_spammy",
    "nfkc",
    "norm_key",
    "now_ts",
    "RARITY_ORDER",
]
