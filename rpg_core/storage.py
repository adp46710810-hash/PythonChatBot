from __future__ import annotations

from copy import deepcopy
import json
import os
import tempfile
import time
from typing import Any


class JsonFileError(RuntimeError):
    pass


def load_json(path: str, default: Any):
    if not os.path.exists(path):
        return deepcopy(default)

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise JsonFileError(
            f"Invalid JSON in data file: {path} (line {exc.lineno}, column {exc.colno})"
        ) from exc
    except OSError as exc:
        raise JsonFileError(f"Failed to read data file: {path}") from exc


def atomic_save_json(path: str, data: Any) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=".__tmp__", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def atomic_write_text(path: str, text: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=".__tmp__", suffix=".txt", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        replace_error = None
        for _attempt in range(6):
            try:
                os.replace(tmp_path, path)
                replace_error = None
                break
            except PermissionError as exc:
                replace_error = exc
                time.sleep(0.05)

        if replace_error is not None:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
