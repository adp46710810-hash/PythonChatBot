from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / "venv"
VENV_PYTHON = VENV_DIR / ("Scripts" if os.name == "nt" else "bin") / (
    "python.exe" if os.name == "nt" else "python"
)
REQUIRED_ENV_VARS = (
    "TWITCH_CLIENT_ID",
    "TWITCH_CLIENT_SECRET",
    "TWITCH_BOT_ID",
    "TWITCH_OWNER_ID",
    "TWITCH_CHANNEL",
)
OPTIONAL_FLOAT_ENV_VARS = ("BOT_GLOBAL_CD", "BOT_USER_CD", "TTS_COOLDOWN_SEC")
OPTIONAL_INT_ENV_VARS = ("BOUYOMI_PORT", "VOICEVOX_PORT", "VOICEVOX_SPEAKER", "TTS_MAX_LEN")
OPTIONAL_BOOL_ENV_VARS = ("TTS_ENABLED",)
OPTIONAL_CHOICE_ENV_VARS = {
    "TTS_PROVIDER": {"bouyomi", "voicevox"},
}
TRUE_ENV_VALUES = {"1", "true", "yes", "on"}
FALSE_ENV_VALUES = {"0", "false", "no", "off"}


def _format_command(parts: list[str]) -> str:
    rendered = []
    for part in parts:
        rendered.append(f'"{part}"' if " " in part else part)
    return " ".join(rendered)


def run_command(parts: list[str]) -> int:
    print(f"+ {_format_command(parts)}")
    completed = subprocess.run(parts, cwd=ROOT)
    return completed.returncode


def ensure_venv_exists() -> bool:
    if VENV_PYTHON.exists():
        return True

    print("venv is missing. Run `python dev.py setup` first.", file=sys.stderr)
    return False


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_bot_data_path(env_values: dict[str, str], *, root: Path = ROOT) -> Path:
    configured = env_values.get("BOT_DATA_FILE", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else root / path

    default_path = root / "data" / "runtime" / "botdata.json"
    legacy_path = root / "botdata.json"
    if default_path.exists():
        return default_path
    if legacy_path.exists():
        return legacy_path
    return default_path


def validate_optional_env_values(env_values: dict[str, str]) -> list[str]:
    errors: list[str] = []

    for name in OPTIONAL_FLOAT_ENV_VARS:
        raw_value = env_values.get(name, "").strip()
        if not raw_value:
            continue
        try:
            float(raw_value)
        except ValueError:
            errors.append(f"{name}={raw_value!r}")

    for name in OPTIONAL_INT_ENV_VARS:
        raw_value = env_values.get(name, "").strip()
        if not raw_value:
            continue
        try:
            int(raw_value)
        except ValueError:
            errors.append(f"{name}={raw_value!r}")

    for name in OPTIONAL_BOOL_ENV_VARS:
        raw_value = env_values.get(name, "").strip()
        if not raw_value:
            continue
        normalized = raw_value.lower()
        if normalized not in TRUE_ENV_VALUES | FALSE_ENV_VALUES:
            errors.append(f"{name}={raw_value!r}")

    for name, allowed_values in OPTIONAL_CHOICE_ENV_VARS.items():
        raw_value = env_values.get(name, "").strip()
        if not raw_value:
            continue
        normalized = raw_value.lower()
        if normalized not in allowed_values:
            errors.append(f"{name}={raw_value!r}")

    return errors


def inspect_json_file(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "OK", "will be created on first save"

    try:
        json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return "INVALID", f"line {exc.lineno}, column {exc.colno}"
    except OSError as exc:
        return "INVALID", str(exc)

    return "OK", ""


def command_setup() -> int:
    if not VENV_PYTHON.exists():
        code = run_command([sys.executable, "-m", "venv", str(VENV_DIR)])
        if code != 0:
            return code

    code = run_command([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip"])
    if code != 0:
        return code

    return run_command([str(VENV_PYTHON), "-m", "pip", "install", "-r", "requirements.txt"])


def command_test() -> int:
    if not ensure_venv_exists():
        return 1
    return run_command([str(VENV_PYTHON), "-m", "unittest", "discover", "-s", "tests", "-v"])


def command_run() -> int:
    if not ensure_venv_exists():
        return 1
    return run_command([str(VENV_PYTHON), "bot.py"])


def command_doctor() -> int:
    env_file = ROOT / ".env"
    env_values = read_env_file(env_file)
    for name in REQUIRED_ENV_VARS:
        current_value = os.environ.get(name, "").strip()
        if current_value:
            env_values[name] = current_value
    missing_env_vars = [name for name in REQUIRED_ENV_VARS if not env_values.get(name, "").strip()]
    optional_env_errors = validate_optional_env_values(env_values)
    runtime_data_path = resolve_bot_data_path(env_values)
    runtime_data_status, runtime_data_note = inspect_json_file(runtime_data_path)

    print(f"project_root: {ROOT}")
    print(f"venv_python:  {'OK' if VENV_PYTHON.exists() else 'MISSING'}  {VENV_PYTHON}")
    print(f"env_file:      {'OK' if env_file.exists() else 'MISSING'}  {env_file}")

    if missing_env_vars:
        print(f"required_env:  MISSING  {', '.join(missing_env_vars)}")
    else:
        print("required_env:  OK")

    if optional_env_errors:
        print(f"optional_env:  INVALID  {', '.join(optional_env_errors)}")
    else:
        print("optional_env:  OK")

    if runtime_data_note:
        print(f"runtime_data:  {runtime_data_status}  {runtime_data_path} ({runtime_data_note})")
    else:
        print(f"runtime_data:  {runtime_data_status}  {runtime_data_path}")

    print("next_steps:")
    if not VENV_PYTHON.exists():
        print("  python dev.py setup")
    if missing_env_vars:
        print("  fill `.env` from `.env.example`")
    if optional_env_errors:
        print("  fix invalid optional env values in `.env`")
    if runtime_data_status != "OK":
        print("  repair or restore the runtime data JSON file")
    if VENV_PYTHON.exists() and not missing_env_vars:
        print("  python dev.py test")
        print("  python dev.py run")

    is_healthy = (
        VENV_PYTHON.exists()
        and not missing_env_vars
        and not optional_env_errors
        and runtime_data_status == "OK"
    )
    return 0 if is_healthy else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Project helper for setup, checks, tests, and bot launch.")
    parser.add_argument(
        "command",
        nargs="?",
        default="doctor",
        choices=("setup", "doctor", "test", "run"),
        help="Which helper command to run.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "setup":
        return command_setup()
    if args.command == "test":
        return command_test()
    if args.command == "run":
        return command_run()
    return command_doctor()


if __name__ == "__main__":
    raise SystemExit(main())
