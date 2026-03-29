from __future__ import annotations

import random

import twitchio
from twitchio.ext import commands

from app_config import CONFIG, EMOTE_ECHO_ENABLED, EMOTE_ECHO_MIN_INTERVAL_SEC, KEYWORD_RESPONSES
from rpg_core.rules import CHAT_EXP_NOTIFY, CHAT_EXP_PER_MSG
from rpg_core.utils import looks_spammy, nfkc, norm_key, now_ts


class NonCommandChat(commands.Component):
    def __init__(self, bot: "StreamBot") -> None:
        self.bot = bot

    @commands.Component.listener()
    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        try:
            chatter = payload.chatter
            text_raw = payload.text or ""
            username = getattr(chatter, "name", "") or getattr(chatter, "login", "") or ""
            display_name = getattr(chatter, "display_name", "") or username
            user_id = str(getattr(chatter, "id", ""))

            if user_id and str(user_id) == str(self.bot.bot_id):
                return

            text_nfkc = nfkc(text_raw)
            if not text_nfkc.strip():
                return

            if text_nfkc.strip().startswith(CONFIG.prefix):
                return

            if looks_spammy(text_nfkc):
                return

            now = now_ts()
            username_key = username.lower()
            user = self.bot.rpg.get_user(username_key)
            display_name = self.bot.rpg.remember_display_name(username_key, display_name)

            gained = self.bot.rpg.reward_chat_exp(user, now)
            if gained:
                self.bot.save_data()
                if CHAT_EXP_NOTIFY and self.bot.can_reply(username_key):
                    await payload.broadcaster.send_message(
                        sender=self.bot.user,
                        message=f"{display_name} +{CHAT_EXP_PER_MSG}EXP",
                    )

            hit_word = self._find_keyword_hit(text_nfkc)
            if hit_word and self.bot.can_reply(username_key):
                response = random.choice(KEYWORD_RESPONSES[hit_word])
                await payload.broadcaster.send_message(sender=self.bot.user, message=response)

            await self._maybe_echo_emotes(payload, username_key, now)
            self._enqueue_tts(display_name, text_nfkc)

        except Exception:
            self.bot.log.exception("NonCommandChat.event_message crashed")

    def _find_keyword_hit(self, text: str) -> str | None:
        normalized_text = norm_key(text)
        for keyword in KEYWORD_RESPONSES:
            if keyword and norm_key(keyword) in normalized_text:
                return keyword
        return None

    async def _maybe_echo_emotes(
        self,
        payload: twitchio.ChatMessage,
        username_key: str,
        now: float,
    ) -> None:
        if not EMOTE_ECHO_ENABLED:
            return

        last_echo = self.bot._user_last_emote_echo_ts.get(username_key, 0.0)
        if now - last_echo < EMOTE_ECHO_MIN_INTERVAL_SEC:
            return

        emotes = self.bot._extract_emote_text(payload, max_emotes=2)
        if not emotes:
            return

        if not self.bot.can_reply(username_key):
            return

        self.bot._user_last_emote_echo_ts[username_key] = now
        await payload.broadcaster.send_message(
            sender=self.bot.user,
            message=" ".join(emotes),
        )

    def _enqueue_tts(self, username: str, text: str) -> None:
        try:
            self.bot.enqueue_chat_tts_message(username, text)
        except Exception:
            pass
