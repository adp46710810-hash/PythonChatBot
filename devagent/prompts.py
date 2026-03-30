from __future__ import annotations

import re
from pathlib import Path

from .profile import ProjectProfile
from .project_tools import SearchHit, get_git_status, list_relative_files, read_text_file, search_text

ASK_SYSTEM_PROMPT = """あなたは開発支援の副担当AIです。
あなたの役割は、主担当AIや人間の判断を補助することです。
断定しすぎず、根拠が薄い点は仮説として扱ってください。
返答は必ず次の見出し順に日本語でまとめてください。
1. 要件の理解
2. 関連ファイル
3. 提案
4. テスト観点
5. 注意点"""

REVIEW_SYSTEM_PROMPT = """あなたはコードレビュー補助AIです。
差分からリスク、回帰、テスト不足を優先して指摘してください。
返答は日本語で、次の見出し順にまとめてください。
1. 変更概要
2. 気になる点
3. テスト観点
4. 注意点"""

SUMMARY_SYSTEM_PROMPT = """あなたはログ要約用AIです。
ログを読み、何が起きたかと次に見るべき点を短く整理してください。
返答は日本語で、次の見出し順にまとめてください。
1. 概要
2. 主なエラー
3. 次に見る箇所"""

CHALLENGE_SYSTEM_PROMPT = """あなたは反対意見担当の検証AIです。
提案をそのまま褒めず、破綻条件、見落とし、バランス崩壊、説明不足を優先して指摘してください。
返答は日本語で、次の見出し順にまとめてください。
1. 良い点
2. 気になる点
3. 破綻しやすい条件
4. 追加で決めるべきこと
5. 次に人間へ確認すべきこと"""

SPEC_SYSTEM_PROMPT = """あなたは仕様整理担当AIです。
雑多な案を実装しやすい仕様へ整理する役割です。
決まったことと未決定事項を分け、後で実装担当が迷わない形にまとめてください。
返答は日本語で、次の見出し順にまとめてください。
1. 目的
2. 既に決まっていること
3. 仕様案
4. 実装への影響
5. 未決定事項"""

NOTE_SYSTEM_PROMPT = """あなたは note 記事作成補助AIです。
与えられたプロジェクト文脈をもとに、読みやすく、誇張せず、実態に沿った記事案をまとめてください。
宣伝文句だけにせず、読者にとって分かりやすい価値、特徴、開発の工夫を整理してください。
返答は日本語で、次の見出し順にまとめてください。
1. 記事の狙い
2. 想定読者
3. 推しポイント
4. 記事構成案
5. 書き出し案
6. 注意点"""


def _tokenize_topic(topic: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9_./-]+|[一-龯ぁ-んァ-ヴー]+", topic)
    normalized: list[str] = []
    for token in tokens:
        value = token.strip().casefold()
        if len(value) >= 2:
            normalized.append(value)
    return normalized


def _score_path(path: Path, topic_tokens: list[str], *, important: bool) -> int:
    path_text = path.as_posix().casefold()
    score = 0
    if important:
        score += 6
    for token in topic_tokens:
        if token in path_text:
            score += 10
    return score


def _collect_hits(profile: ProjectProfile, topic: str) -> dict[str, list[SearchHit]]:
    hits_by_path: dict[str, list[SearchHit]] = {}
    if not topic.strip():
        return hits_by_path

    direct_hits = search_text(profile, topic, limit=40)
    for hit in direct_hits:
        hits_by_path.setdefault(hit.path.as_posix(), []).append(hit)

    if direct_hits:
        return hits_by_path

    for token in _tokenize_topic(topic):
        for hit in search_text(profile, token, limit=20):
            hits_by_path.setdefault(hit.path.as_posix(), []).append(hit)
    return hits_by_path


def find_related_files(profile: ProjectProfile, topic: str, *, limit: int = 8) -> list[Path]:
    topic_tokens = _tokenize_topic(topic)
    hits_by_path = _collect_hits(profile, topic)
    all_files = list_relative_files(profile)
    important = {Path(path).as_posix() for path in profile.important_files}

    scored: list[tuple[int, str, Path]] = []
    for path in all_files:
        key = path.as_posix()
        score = _score_path(path, topic_tokens, important=key in important)
        score += len(hits_by_path.get(key, [])) * 3
        if topic.strip() and score <= 0:
            continue
        scored.append((score, key, path))

    if not scored:
        fallback: list[Path] = []
        seen: set[str] = set()
        for candidate in [*profile.important_files, *profile.entrypoints]:
            path = Path(candidate)
            key = path.as_posix()
            if key not in seen:
                fallback.append(path)
                seen.add(key)
        return fallback[:limit]

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, _, path in scored[:limit]]


def _render_snippets(profile: ProjectProfile, paths: list[Path], *, snippet_lines: int = 30) -> str:
    blocks: list[str] = []
    for path in paths:
        text = read_text_file(profile, path, max_chars=6000)
        lines = text.splitlines()
        snippet = "\n".join(lines[:snippet_lines])
        blocks.append(f"### {path.as_posix()}\n```text\n{snippet}\n```")
    return "\n\n".join(blocks)


def build_context_bundle(
    profile: ProjectProfile,
    topic: str,
    *,
    include_snippets: bool = True,
    limit: int = 6,
) -> str:
    related = find_related_files(profile, topic, limit=limit)
    git_status = get_git_status(profile)

    sections: list[str] = [
        f"# Project: {profile.name}",
        f"- root: {profile.root}",
        f"- language: {profile.language}",
        "",
        "## Topic",
        topic.strip() or "(not provided)",
        "",
        "## Important Files",
    ]

    for path in profile.important_files:
        sections.append(f"- {path}")

    sections.extend(["", "## Related Files"])
    for path in related:
        sections.append(f"- {path.as_posix()}")

    sections.extend(["", "## Git Status"])
    for line in git_status[:20]:
        sections.append(f"- {line}")

    if profile.prompt_notes:
        sections.extend(["", "## Prompt Notes"])
        for note in profile.prompt_notes:
            sections.append(f"- {note}")

    if include_snippets and related:
        sections.extend(["", "## Snippets", _render_snippets(profile, related[:4])])

    return "\n".join(sections).strip() + "\n"


def build_ask_prompt(profile: ProjectProfile, question: str) -> str:
    context_bundle = build_context_bundle(profile, question, include_snippets=True)
    return f"{context_bundle}\n## Request\n{question.strip()}\n"


def build_challenge_prompt(profile: ProjectProfile, proposal: str) -> str:
    context_bundle = build_context_bundle(profile, proposal, include_snippets=True)
    return (
        f"{context_bundle}\n"
        "## Request\n"
        "次の案を厳しめに検討し、見落としや破綻条件を洗い出してください。\n\n"
        f"{proposal.strip()}\n"
    )


def build_spec_prompt(profile: ProjectProfile, topic: str) -> str:
    context_bundle = build_context_bundle(profile, topic, include_snippets=True)
    return (
        f"{context_bundle}\n"
        "## Request\n"
        "次のテーマについて、決まったことと未決定事項を分けながら、"
        "実装へ落としやすい仕様案に整理してください。\n\n"
        f"テーマ: {topic.strip()}\n"
    )


def _load_note_brief(profile: ProjectProfile) -> str:
    brief_path = profile.root / "docs" / "note_article_project_context.md"
    if not brief_path.exists():
        return ""
    return brief_path.read_text(encoding="utf-8", errors="replace").strip()


def build_note_prompt(profile: ProjectProfile, topic: str) -> str:
    context_bundle = build_context_bundle(profile, topic, include_snippets=False)
    note_brief = _load_note_brief(profile)

    sections = [context_bundle.strip()]
    if note_brief:
        sections.extend(["", "## Note Article Brief", note_brief])
    sections.extend(
        [
            "",
            "## Request",
            "このプロジェクトを note 記事で紹介・解説する前提で、"
            "読者に伝わりやすい記事案を作ってください。"
            "事実ベースで、過剰な宣伝は避けてください。"
            "記事本文のたたき台として使える具体性を持たせてください。",
            "",
            f"記事テーマ: {topic.strip()}",
        ]
    )
    return "\n".join(sections).strip() + "\n"


def build_review_prompt(profile: ProjectProfile, diff_text: str) -> str:
    sections = [f"# Project: {profile.name}"]
    if profile.prompt_notes:
        sections.extend(["## Prompt Notes", *[f"- {note}" for note in profile.prompt_notes], ""])
    sections.extend(["## Diff", "```diff", diff_text, "```"])
    return "\n".join(sections).strip() + "\n"


def build_summary_prompt(profile: ProjectProfile, log_text: str, *, source_name: str) -> str:
    return (
        f"# Project: {profile.name}\n"
        f"## Source\n{source_name}\n\n"
        "## Log\n"
        "```text\n"
        f"{log_text}\n"
        "```\n"
    )
