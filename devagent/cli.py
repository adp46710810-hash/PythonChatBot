from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from .gemini_provider import GeminiProvider, ProviderError, load_gemini_config_from_env
from .profile import ProfileError, ProjectProfile, load_profile
from .project_tools import get_git_diff, run_allowed_command
from .prompts import (
    ASK_SYSTEM_PROMPT,
    CHALLENGE_SYSTEM_PROMPT,
    NOTE_SYSTEM_PROMPT,
    REVIEW_SYSTEM_PROMPT,
    SPEC_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
    build_ask_prompt,
    build_challenge_prompt,
    build_context_bundle,
    build_note_prompt,
    build_review_prompt,
    build_spec_prompt,
    build_summary_prompt,
    find_related_files,
)


def _load_env_from_profile(profile: ProjectProfile) -> None:
    load_dotenv(profile.root / ".env", override=False)


def _require_tools(profile: ProjectProfile, *tool_names: str) -> None:
    for tool_name in tool_names:
        if not profile.is_tool_allowed(tool_name):
            raise ProfileError(f"Tool is not allowed by the project profile: {tool_name}")


def _render_provider_response(prompt: str, *, system: str) -> str:
    config = load_gemini_config_from_env()
    if config is not None:
        provider = GeminiProvider(config)
        return provider.ask(prompt, system=system)

    return (
        "[manual handoff]\n"
        "Copy the following system prompt and user prompt into an external AI when needed.\n"
        "Set `GEMINI_API_KEY` in `.env` if you want DevAgent to call Gemini directly.\n\n"
        "[System]\n"
        f"{system}\n\n"
        "[Prompt]\n"
        f"{prompt}"
    )


def command_files(profile: ProjectProfile, topic: str) -> int:
    _require_tools(profile, "list_files", "search_text")
    for path in find_related_files(profile, topic, limit=10):
        print(path.as_posix())
    return 0


def command_context(profile: ProjectProfile, topic: str) -> int:
    _require_tools(profile, "list_files", "search_text", "read_file", "git_status")
    print(build_context_bundle(profile, topic, include_snippets=True), end="")
    return 0


def command_ask(profile: ProjectProfile, question: str) -> int:
    _require_tools(profile, "list_files", "search_text", "read_file", "git_status")
    prompt = build_ask_prompt(profile, question)
    print(_render_provider_response(prompt, system=ASK_SYSTEM_PROMPT))
    return 0


def command_challenge(profile: ProjectProfile, proposal: str) -> int:
    _require_tools(profile, "list_files", "search_text", "read_file", "git_status")
    prompt = build_challenge_prompt(profile, proposal)
    print(_render_provider_response(prompt, system=CHALLENGE_SYSTEM_PROMPT))
    return 0


def command_spec(profile: ProjectProfile, topic: str) -> int:
    _require_tools(profile, "list_files", "search_text", "read_file", "git_status")
    prompt = build_spec_prompt(profile, topic)
    print(_render_provider_response(prompt, system=SPEC_SYSTEM_PROMPT))
    return 0


def command_note(profile: ProjectProfile, topic: str) -> int:
    _require_tools(profile, "list_files", "search_text", "read_file", "git_status")
    prompt = build_note_prompt(profile, topic)
    print(_render_provider_response(prompt, system=NOTE_SYSTEM_PROMPT))
    return 0


def command_review(profile: ProjectProfile) -> int:
    _require_tools(profile, "git_status")
    diff_text = get_git_diff(profile)
    prompt = build_review_prompt(profile, diff_text)
    print(_render_provider_response(prompt, system=REVIEW_SYSTEM_PROMPT))
    return 0


def command_summarize(profile: ProjectProfile, log_path: str) -> int:
    _require_tools(profile, "read_file")
    resolved = Path(log_path)
    source_path = resolved if resolved.is_absolute() else Path.cwd() / resolved
    if not source_path.exists():
        raise ProfileError(f"Log file was not found: {source_path}")

    log_text = source_path.read_text(encoding="utf-8", errors="replace")
    if len(log_text) > 16000:
        log_text = log_text[:16000] + "\n... (truncated)\n"
    prompt = build_summary_prompt(profile, log_text, source_name=source_path.name)
    print(_render_provider_response(prompt, system=SUMMARY_SYSTEM_PROMPT))
    return 0


def _resolve_run_target(profile: ProjectProfile, target: str) -> list[str]:
    normalized = target.strip()
    if not normalized:
        raise ProfileError("Run target is required.")
    if normalized == "test":
        if not profile.test_commands:
            raise ProfileError("This project profile does not define `test_commands`.")
        return list(profile.test_commands)
    if normalized == "run":
        if not profile.run_commands:
            raise ProfileError("This project profile does not define `run_commands`.")
        return list(profile.run_commands)
    return [normalized]


def command_run(profile: ProjectProfile, target: str) -> int:
    _require_tools(profile, "run_command")
    exit_code = 0
    for command in _resolve_run_target(profile, target):
        completed = run_allowed_command(profile, command)
        print(f"+ {command}")
        if completed.stdout:
            print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
        if completed.stderr:
            print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n")
        if completed.returncode != 0:
            exit_code = completed.returncode
            break
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devagent",
        description="Codex-first development assistant for local context and optional Gemini sidecar calls.",
    )
    parser.add_argument(
        "--profile",
        help="Path to agent.project.yaml. Defaults to the nearest file in the current directory tree.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    files_parser = subparsers.add_parser("files", help="List files related to the given topic.")
    files_parser.add_argument("topic", help="Topic, bug, or feature name to search for.")

    context_parser = subparsers.add_parser("context", help="Render a reusable context bundle.")
    context_parser.add_argument("topic", help="Topic, bug, or feature name to summarize.")

    ask_parser = subparsers.add_parser(
        "ask",
        help="Ask about the current project via Gemini, or render a manual handoff prompt.",
    )
    ask_parser.add_argument("question", help="Question to ask about the current project.")

    challenge_parser = subparsers.add_parser(
        "challenge",
        help="Ask Gemini to critique an idea from an opposing or skeptical viewpoint.",
    )
    challenge_parser.add_argument("proposal", help="Proposal, idea, or draft to challenge.")

    spec_parser = subparsers.add_parser(
        "spec",
        help="Turn a topic or rough idea into a more concrete implementation spec.",
    )
    spec_parser.add_argument("topic", help="Topic, feature, or design theme to formalize.")

    note_parser = subparsers.add_parser(
        "note",
        help="Prepare a note article angle or draft from the current project context.",
    )
    note_parser.add_argument("topic", help="Article theme or angle for the note draft.")

    subparsers.add_parser("review", help="Review the current git diff.")

    summarize_parser = subparsers.add_parser("summarize", help="Summarize a text log file.")
    summarize_parser.add_argument("--log", required=True, help="Path to the log file.")

    run_parser = subparsers.add_parser("run", help="Run a safe command from the project profile.")
    run_parser.add_argument("target", help="`test`, `run`, or an exact allowed command.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        profile = load_profile(args.profile)
        _load_env_from_profile(profile)

        if args.command == "files":
            return command_files(profile, args.topic)
        if args.command == "context":
            return command_context(profile, args.topic)
        if args.command == "ask":
            return command_ask(profile, args.question)
        if args.command == "challenge":
            return command_challenge(profile, args.proposal)
        if args.command == "spec":
            return command_spec(profile, args.topic)
        if args.command == "note":
            return command_note(profile, args.topic)
        if args.command == "review":
            return command_review(profile)
        if args.command == "summarize":
            return command_summarize(profile, args.log)
        if args.command == "run":
            return command_run(profile, args.target)
    except (ProfileError, ProviderError) as exc:
        print(f"devagent error: {exc}")
        return 1

    parser.error(f"Unknown command: {args.command}")
    return 2
