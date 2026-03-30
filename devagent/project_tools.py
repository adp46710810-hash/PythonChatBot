from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .profile import ProfileError, ProjectProfile

TEXT_EXTENSIONS = {
    ".c",
    ".cfg",
    ".conf",
    ".css",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".rst",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class SearchHit:
    path: Path
    line_number: int
    line_text: str


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS or path.name in {
        "README",
        "LICENSE",
        "Makefile",
        "Dockerfile",
    }


def iter_text_files(profile: ProjectProfile) -> list[Path]:
    files: list[Path] = []
    for path in profile.root.rglob("*"):
        if not path.is_file():
            continue
        if profile.is_blocked(path):
            continue
        if not _is_text_file(path):
            continue
        files.append(path)
    return sorted(files)


def list_relative_files(profile: ProjectProfile) -> list[Path]:
    return [path.relative_to(profile.root) for path in iter_text_files(profile)]


def read_text_file(profile: ProjectProfile, relative_path: str | Path, *, max_chars: int = 12000) -> str:
    path = profile.resolve_path(relative_path)
    if profile.is_blocked(path):
        raise ProfileError(f"Reading `{path}` is blocked by the project profile.")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ProfileError(f"Could not read `{path}`: {exc}") from exc
    if len(text) > max_chars:
        return text[:max_chars] + "\n... (truncated)\n"
    return text


def search_text(
    profile: ProjectProfile,
    query: str,
    *,
    limit: int = 20,
) -> list[SearchHit]:
    normalized_query = query.strip().casefold()
    if not normalized_query:
        return []

    hits: list[SearchHit] = []
    for path in iter_text_files(profile):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        for line_number, line in enumerate(lines, start=1):
            if normalized_query in line.casefold():
                hits.append(
                    SearchHit(
                        path=path.relative_to(profile.root),
                        line_number=line_number,
                        line_text=line.strip(),
                    )
                )
                if len(hits) >= limit:
                    return hits
    return hits


def get_git_status(profile: ProjectProfile) -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--short"],
        cwd=profile.root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return ["(git status unavailable)"]

    lines = [line.rstrip() for line in completed.stdout.splitlines() if line.strip()]
    return lines or ["working tree clean"]


def get_git_diff(profile: ProjectProfile, *, max_chars: int = 16000) -> str:
    completed = subprocess.run(
        ["git", "diff", "--unified=2"],
        cwd=profile.root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ProfileError("Could not read git diff.")

    text = completed.stdout.strip()
    if not text:
        return "(no unstaged diff)"
    if len(text) > max_chars:
        return text[:max_chars] + "\n... (truncated)\n"
    return text


def run_allowed_command(profile: ProjectProfile, command: str) -> subprocess.CompletedProcess[str]:
    normalized = " ".join(command.split())
    if not profile.is_command_allowed(normalized):
        raise ProfileError(f"Command is not allowed by the project profile: {normalized}")

    parts = normalized.split(" ")
    return subprocess.run(
        parts,
        cwd=profile.root,
        capture_output=True,
        text=True,
        check=False,
    )
