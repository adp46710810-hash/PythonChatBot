from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ProfileError(RuntimeError):
    """Raised when the project profile is missing or invalid."""


@dataclass(frozen=True)
class ProjectProfile:
    name: str
    root: Path
    language: str
    entrypoints: tuple[str, ...] = ()
    important_files: tuple[str, ...] = ()
    test_commands: tuple[str, ...] = ()
    run_commands: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    allowed_commands: tuple[str, ...] = ()
    blocked_paths: tuple[str, ...] = ()
    prompt_notes: tuple[str, ...] = ()
    profile_path: Path = field(default_factory=Path)

    def is_tool_allowed(self, tool_name: str) -> bool:
        return tool_name in set(self.allowed_tools)

    def is_command_allowed(self, command: str) -> bool:
        normalized = " ".join(command.split())
        return normalized in {" ".join(value.split()) for value in self.allowed_commands}

    def resolve_path(self, relative_path: str | Path) -> Path:
        path = Path(relative_path)
        return path if path.is_absolute() else self.root / path

    def is_blocked(self, candidate: str | Path) -> bool:
        path = Path(candidate)
        absolute = path if path.is_absolute() else self.root / path

        try:
            relative = absolute.relative_to(self.root)
        except ValueError:
            return True

        normalized = relative.as_posix().strip()
        normalized_lower = normalized.casefold()

        for blocked in self.blocked_paths:
            blocked_value = blocked.strip().replace("\\", "/").strip("/")
            blocked_lower = blocked_value.casefold()
            if not blocked_lower:
                continue
            if normalized_lower == blocked_lower:
                return True
            if normalized_lower.startswith(f"{blocked_lower}/"):
                return True
        return False


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    result: list[str] = []

    for char in line:
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            break
        result.append(char)

    return "".join(result).rstrip()


def _parse_scalar(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    if (stripped.startswith('"') and stripped.endswith('"')) or (
        stripped.startswith("'") and stripped.endswith("'")
    ):
        return stripped[1:-1]
    return stripped


def parse_simple_yaml(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_key: str | None = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        if raw_line.lstrip().startswith("#"):
            continue

        line = _strip_comment(raw_line)
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if stripped.startswith("- "):
            if current_key is None:
                raise ProfileError(f"Line {line_number}: list item without a parent key.")
            if indent < 2:
                raise ProfileError(f"Line {line_number}: list item must be indented by two spaces.")
            current_value = data.setdefault(current_key, [])
            if not isinstance(current_value, list):
                raise ProfileError(
                    f"Line {line_number}: key `{current_key}` cannot mix scalar and list values."
                )
            current_value.append(_parse_scalar(stripped[2:]))
            continue

        if ":" not in stripped:
            raise ProfileError(f"Line {line_number}: expected `key: value`.")

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            raise ProfileError(f"Line {line_number}: missing key name.")

        if value:
            data[key] = _parse_scalar(value)
            current_key = None
        else:
            data[key] = []
            current_key = key

    return data


def _get_list(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if value in ("", None):
        return ()
    if not isinstance(value, list):
        raise ProfileError(f"`{key}` must be a list.")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ProfileError(f"`{key}` must contain strings only.")
        normalized.append(item.strip())
    return tuple(item for item in normalized if item)


def _get_str(data: dict[str, Any], key: str, *, required: bool = False, default: str = "") -> str:
    value = data.get(key, default)
    if isinstance(value, list):
        raise ProfileError(f"`{key}` must be a string.")
    if value is None:
        value = default
    rendered = str(value).strip()
    if required and not rendered:
        raise ProfileError(f"`{key}` is required.")
    return rendered


def find_profile_path(start_dir: Path | None = None) -> Path:
    current = (start_dir or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / "agent.project.yaml"
        if candidate.exists():
            return candidate
    raise ProfileError("`agent.project.yaml` was not found in the current directory tree.")


def load_profile(profile_path: str | Path | None = None, *, cwd: Path | None = None) -> ProjectProfile:
    if profile_path is None:
        resolved_profile_path = find_profile_path(cwd)
    else:
        candidate = Path(profile_path)
        resolved_profile_path = candidate if candidate.is_absolute() else (cwd or Path.cwd()) / candidate

    try:
        raw_text = resolved_profile_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileError(f"Could not read profile `{resolved_profile_path}`: {exc}") from exc

    data = parse_simple_yaml(raw_text)
    base_dir = resolved_profile_path.parent.resolve()
    root_value = _get_str(data, "root", default=".")
    root = (base_dir / root_value).resolve()

    profile = ProjectProfile(
        name=_get_str(data, "name", required=True),
        root=root,
        language=_get_str(data, "language", required=True),
        entrypoints=_get_list(data, "entrypoints"),
        important_files=_get_list(data, "important_files"),
        test_commands=_get_list(data, "test_commands"),
        run_commands=_get_list(data, "run_commands"),
        allowed_tools=_get_list(data, "allowed_tools"),
        allowed_commands=_get_list(data, "allowed_commands"),
        blocked_paths=_get_list(data, "blocked_paths"),
        prompt_notes=_get_list(data, "prompt_notes"),
        profile_path=resolved_profile_path.resolve(),
    )

    if not profile.allowed_tools:
        raise ProfileError("`allowed_tools` must contain at least one tool name.")
    if "run_command" in profile.allowed_tools and not profile.allowed_commands:
        raise ProfileError("`allowed_commands` is required when `run_command` is enabled.")

    return profile
