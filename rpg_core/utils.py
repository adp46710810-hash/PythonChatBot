from __future__ import annotations

import random
import re
import time
import unicodedata
from typing import List, Tuple


RE_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
RE_MANY_SYMBOLS = re.compile(r"[!-/:-@[-`{-~]")


def now_ts() -> float:
    return time.time()


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "")


def norm_key(s: str) -> str:
    return nfkc(s).strip().lower()


def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def pick_weighted(pairs: List[Tuple[str, int]]) -> str:
    names = [x[0] for x in pairs]
    weights = [x[1] for x in pairs]
    return random.choices(names, weights=weights, k=1)[0]


def looks_spammy(text: str, max_message_len: int = 120, max_symbol_ratio: float = 0.35) -> bool:
    s = nfkc(text or "").strip()
    if not s:
        return False

    if len(s) > max_message_len:
        return True

    if RE_URL.search(s):
        return True

    symbol_count = sum(1 for ch in s if RE_MANY_SYMBOLS.match(ch))
    if len(s) > 0 and (symbol_count / len(s)) > max_symbol_ratio:
        return True

    return False