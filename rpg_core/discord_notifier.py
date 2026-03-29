from __future__ import annotations

import asyncio
import json
from typing import Iterable, List
from urllib import request
from urllib.parse import urlparse, urlunparse


class DiscordWebhookNotifier:
    _MAX_MESSAGE_LEN = 2000
    _BODY_LEN_LIMIT = 1800
    _REQUEST_TIMEOUT_SEC = 10
    _ALLOWED_WEBHOOK_HOSTS = {"discord.com", "discordapp.com"}

    def __init__(self, webhook_url: str, *, username: str = "Twitch RPG Detail") -> None:
        self.webhook_url = self._normalize_webhook_url(webhook_url)
        self.username = str(username or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    async def send_detail(self, title: str, lines: Iterable[str]) -> None:
        if not self.enabled:
            return

        for content in self._build_message_chunks(title, lines):
            await asyncio.to_thread(self._post_content, content)

    def _build_message_chunks(self, title: str, lines: Iterable[str]) -> List[str]:
        safe_title = self._sanitize_text(title) or "詳細ログ"
        normalized_lines = self._normalize_lines(lines)
        if not normalized_lines:
            normalized_lines = ["詳細はありません。"]

        expanded_lines: List[str] = []
        for line in normalized_lines:
            expanded_lines.extend(self._split_long_line(line, self._BODY_LEN_LIMIT))

        bodies: List[str] = []
        current_lines: List[str] = []
        current_len = 0
        for line in expanded_lines:
            projected_len = len(line) if not current_lines else current_len + 1 + len(line)
            if current_lines and projected_len > self._BODY_LEN_LIMIT:
                bodies.append("\n".join(current_lines))
                current_lines = [line]
                current_len = len(line)
                continue

            current_lines.append(line)
            current_len = projected_len

        if current_lines:
            bodies.append("\n".join(current_lines))

        if not bodies:
            bodies.append("詳細はありません。")

        multiple = len(bodies) > 1
        messages: List[str] = []
        for index, body in enumerate(bodies, start=1):
            header = (
                f"**{safe_title} ({index}/{len(bodies)})**"
                if multiple
                else f"**{safe_title}**"
            )
            message = f"{header}\n{body}".strip()
            messages.append(message[: self._MAX_MESSAGE_LEN])
        return messages

    def _post_content(self, content: str) -> None:
        payload = {
            "content": content,
            "allowed_mentions": {"parse": []},
        }
        if self.username:
            payload["username"] = self.username

        req = self._build_request(payload)
        with request.urlopen(req, timeout=self._REQUEST_TIMEOUT_SEC) as response:
            response.read()

    def _normalize_lines(self, lines: Iterable[str]) -> List[str]:
        normalized: List[str] = []
        for raw_line in lines:
            safe_line = self._sanitize_text(raw_line)
            if safe_line:
                normalized.append(safe_line)
        return normalized

    def _split_long_line(self, text: str, limit: int) -> List[str]:
        if len(text) <= limit:
            return [text]

        chunks: List[str] = []
        remaining = text
        while len(remaining) > limit:
            split_at = remaining.rfind(" ", 0, limit + 1)
            if split_at <= 0:
                split_at = limit
            chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()

        if remaining:
            chunks.append(remaining)
        return chunks

    def _sanitize_text(self, text: object) -> str:
        safe_text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        safe_text = safe_text.replace("```", "'''").strip()
        return safe_text

    def _normalize_webhook_url(self, webhook_url: object) -> str:
        raw_url = str(webhook_url or "").strip()
        if not raw_url:
            return ""

        parsed = urlparse(raw_url)
        if str(parsed.scheme or "").lower() != "https":
            return ""

        hostname = (parsed.hostname or "").strip().lower()
        if hostname not in self._ALLOWED_WEBHOOK_HOSTS:
            return ""
        if parsed.username or parsed.password:
            return ""
        if parsed.port not in (None, 443):
            return ""
        if not str(parsed.path or "").startswith("/api/webhooks/"):
            return ""

        normalized = parsed._replace(netloc="discord.com")
        return urlunparse(normalized)

    def _build_request(self, payload: dict) -> request.Request:
        return request.Request(
            self.webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                # Discord's Cloudflare edge may reject urllib's default Python user agent.
                "User-Agent": "Mozilla/5.0",
            },
            method="POST",
        )
