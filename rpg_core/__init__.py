__all__ = [
    "BouyomiClient",
    "DetailOverlayWriter",
    "RPGManager",
    "atomic_save_json",
    "atomic_write_text",
    "load_json",
    "looks_spammy",
    "nfkc",
    "norm_key",
    "now_ts",
]


def __getattr__(name: str):
    if name == "BouyomiClient":
        from .bouyomi import BouyomiClient

        return BouyomiClient
    if name == "DetailOverlayWriter":
        from .detail_overlay import DetailOverlayWriter

        return DetailOverlayWriter
    if name == "RPGManager":
        from .manager import RPGManager

        return RPGManager
    if name == "atomic_save_json":
        from .storage import atomic_save_json

        return atomic_save_json
    if name == "atomic_write_text":
        from .storage import atomic_write_text

        return atomic_write_text
    if name == "load_json":
        from .storage import load_json

        return load_json
    if name == "looks_spammy":
        from .utils import looks_spammy

        return looks_spammy
    if name == "nfkc":
        from .utils import nfkc

        return nfkc
    if name == "norm_key":
        from .utils import norm_key

        return norm_key
    if name == "now_ts":
        from .utils import now_ts

        return now_ts

    raise AttributeError(f"module 'rpg_core' has no attribute '{name}'")
