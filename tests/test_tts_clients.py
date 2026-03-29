from __future__ import annotations

import json
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from bot import StreamBot
from bot_components.rpg_commands import BasicCommands
from rpg_core.bouyomi import BouyomiClient
from rpg_core.tts import build_tts_client, build_voicevox_client
from rpg_core.voicevox import VoicevoxClient


class BuildTTSClientTests(unittest.TestCase):
    def make_config(self, **overrides):
        values = {
            "tts_provider": "bouyomi",
            "bouyomi_host": "127.0.0.1",
            "bouyomi_port": 50001,
            "voicevox_host": "127.0.0.1",
            "voicevox_port": 50021,
            "voicevox_speaker": 1,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_build_tts_client_defaults_to_bouyomi(self) -> None:
        client = build_tts_client(self.make_config())

        self.assertIsInstance(client, BouyomiClient)

    def test_build_tts_client_uses_voicevox_when_selected(self) -> None:
        client = build_tts_client(
            self.make_config(
                tts_provider="voicevox",
                voicevox_host="localhost",
                voicevox_port=50123,
                voicevox_speaker=8,
            )
        )

        self.assertIsInstance(client, VoicevoxClient)
        self.assertEqual(client.host, "localhost")
        self.assertEqual(client.port, 50123)
        self.assertEqual(client.speaker, 8)

    def test_build_voicevox_client_can_override_speaker_id(self) -> None:
        client = build_voicevox_client(
            self.make_config(
                voicevox_host="localhost",
                voicevox_port=50123,
                voicevox_speaker=8,
            ),
            speaker=12,
        )

        self.assertIsInstance(client, VoicevoxClient)
        self.assertEqual(client.host, "localhost")
        self.assertEqual(client.port, 50123)
        self.assertEqual(client.speaker, 12)


class VoicevoxClientTests(unittest.TestCase):
    class _FakeResponse:
        def __init__(self, payload: bytes):
            self.payload = payload

        def read(self) -> bytes:
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    def test_speak_posts_audio_query_and_synthesis_then_plays_wav(self) -> None:
        requests = []
        playback_calls = []

        def fake_urlopen(request, timeout):
            requests.append(
                {
                    "url": request.full_url,
                    "method": request.get_method(),
                    "data": request.data,
                    "timeout": timeout,
                }
            )
            if "/audio_query" in request.full_url:
                return self._FakeResponse(json.dumps({"speedScale": 1.0}).encode("utf-8"))
            return self._FakeResponse(b"RIFFtest")

        fake_winsound = SimpleNamespace(
            SND_MEMORY=4,
            PlaySound=lambda audio_bytes, flags: playback_calls.append((audio_bytes, flags)),
        )
        client = VoicevoxClient("127.0.0.1", 50021, 8)

        with patch("rpg_core.voicevox.urllib.request.urlopen", side_effect=fake_urlopen):
            with patch("rpg_core.voicevox.winsound", fake_winsound):
                client.speak("こんにちは")

        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["method"], "POST")
        self.assertEqual(requests[0]["data"], b"")
        self.assertEqual(requests[0]["timeout"], 10.0)
        self.assertEqual(
            parse_qs(urlsplit(requests[0]["url"]).query),
            {"speaker": ["8"], "text": ["こんにちは"]},
        )
        self.assertEqual(requests[1]["method"], "POST")
        self.assertEqual(
            parse_qs(urlsplit(requests[1]["url"]).query),
            {"speaker": ["8"]},
        )
        self.assertEqual(
            json.loads(requests[1]["data"].decode("utf-8")),
            {"speedScale": 1.0},
        )
        self.assertEqual(playback_calls, [(b"RIFFtest", 4)])


class StreamBotTTSRoutingTests(unittest.TestCase):
    def test_enqueue_chat_tts_message_marks_job_as_chat(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        bot._tts_queue = queue.Queue()
        bot.log = SimpleNamespace(exception=lambda *_args, **_kwargs: None)

        bot.tts_sanitize = lambda author, text: f"{author}:{text}"

        StreamBot.enqueue_chat_tts_message(bot, "Alice", "こんにちは")

        self.assertEqual(bot._tts_queue.get_nowait(), ("chat", "Alice:こんにちは"))

    def test_enqueue_tts_message_marks_job_as_rpg(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        bot._tts_queue = queue.Queue()
        bot.log = SimpleNamespace(exception=lambda *_args, **_kwargs: None)

        bot.tts_sanitize = lambda author, text: text

        StreamBot.enqueue_tts_message(bot, "WB開始")

        self.assertEqual(bot._tts_queue.get_nowait(), ("rpg", "WB開始"))

    def test_enqueue_tts_message_normalizes_rpg_pronunciation_risks(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        bot._tts_queue = queue.Queue()
        bot.log = SimpleNamespace(exception=lambda *_args, **_kwargs: None)

        bot.tts_sanitize = lambda author, text: text

        StreamBot.enqueue_tts_message(
            bot,
            "灼甲帝ヴァルカラン が激昂した。腑抜けた面してないで来い",
        )

        self.assertEqual(
            bot._tts_queue.get_nowait(),
            ("rpg", "シャクコウテイヴァルカラン がゲキコウした。フヌケたツラしてないで来い"),
        )

    def test_enqueue_chat_tts_message_does_not_apply_rpg_pronunciation_dictionary(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        bot._tts_queue = queue.Queue()
        bot.log = SimpleNamespace(exception=lambda *_args, **_kwargs: None)

        bot.tts_sanitize = lambda author, text: text

        StreamBot.enqueue_chat_tts_message(bot, "Alice", "腑抜けた面してないで来い")

        self.assertEqual(
            bot._tts_queue.get_nowait(),
            ("chat", "腑抜けた面してないで来い"),
        )

    def test_rpg_voicevox_speaker_id_uses_saved_value_when_available(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        bot.data = {"users": {}, "tts_settings": {"rpg_voicevox_speaker": 17}}

        with patch("bot.CONFIG", SimpleNamespace(voicevox_speaker=3)):
            self.assertEqual(StreamBot.get_rpg_voicevox_speaker_id(bot), 17)

    def test_set_rpg_voicevox_speaker_id_updates_runtime_and_storage(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        bot.data = {"users": {}}
        bot._rpg_tts = SimpleNamespace(speaker=3)

        applied_id = StreamBot.set_rpg_voicevox_speaker_id(bot, 11)

        self.assertEqual(applied_id, 11)
        self.assertEqual(bot._rpg_tts.speaker, 11)
        self.assertEqual(bot.data["tts_settings"]["rpg_voicevox_speaker"], 11)

    def test_set_rpg_voicevox_speaker_id_can_store_label(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        bot.data = {"users": {}}
        bot._rpg_tts = SimpleNamespace(speaker=3)

        applied_id = StreamBot.set_rpg_voicevox_speaker_id(
            bot,
            11,
            label="ずんだもん / ノーマル",
        )

        self.assertEqual(applied_id, 11)
        self.assertEqual(
            bot.data["tts_settings"]["rpg_voicevox_speaker_label"],
            "ずんだもん / ノーマル",
        )

    def test_find_rpg_voicevox_style_prefers_normal_for_exact_speaker_match(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        bot.list_rpg_voicevox_styles = lambda: [
            {
                "speaker_name": "ずんだもん",
                "style_name": "あまあま",
                "style_id": 1,
                "label": "ずんだもん / あまあま",
                "search_text": "ずんだもん あまあま",
            },
            {
                "speaker_name": "ずんだもん",
                "style_name": "ノーマル",
                "style_id": 3,
                "label": "ずんだもん / ノーマル",
                "search_text": "ずんだもん のーまる",
            },
        ]
        bot._normalize_voicevox_query = lambda text: StreamBot._normalize_voicevox_query(bot, text)
        bot._choose_default_voicevox_style = (
            lambda entries: StreamBot._choose_default_voicevox_style(bot, entries)
        )

        selected, candidates = StreamBot.find_rpg_voicevox_style(bot, "ずんだもん")

        self.assertIsNotNone(selected)
        self.assertEqual(selected["style_id"], 3)
        self.assertEqual(len(candidates), 2)

    def test_find_rpg_voicevox_style_can_match_speaker_and_style_name(self) -> None:
        bot = StreamBot.__new__(StreamBot)
        bot.list_rpg_voicevox_styles = lambda: [
            {
                "speaker_name": "ずんだもん",
                "style_name": "あまあま",
                "style_id": 1,
                "label": "ずんだもん / あまあま",
                "search_text": "ずんだもん あまあま",
            },
            {
                "speaker_name": "ずんだもん",
                "style_name": "ノーマル",
                "style_id": 3,
                "label": "ずんだもん / ノーマル",
                "search_text": "ずんだもん のーまる",
            },
        ]
        bot._normalize_voicevox_query = lambda text: StreamBot._normalize_voicevox_query(bot, text)
        bot._choose_default_voicevox_style = (
            lambda entries: StreamBot._choose_default_voicevox_style(bot, entries)
        )

        selected, candidates = StreamBot.find_rpg_voicevox_style(bot, "ずんだもん あまあま")

        self.assertIsNotNone(selected)
        self.assertEqual(selected["style_id"], 1)
        self.assertEqual(len(candidates), 1)


class VoicevoxSpeakerCommandTests(unittest.IsolatedAsyncioTestCase):
    class _SpeakerBot:
        owner_id = "owner"

        def __init__(self) -> None:
            self.rpg = SimpleNamespace(remember_display_name=lambda _u, d: d)
            self.current_speaker_id = 4
            self.current_speaker_label = "四国めたん / ノーマル"
            self.saved = 0

        def get_rpg_voicevox_speaker_id(self) -> int:
            return self.current_speaker_id

        def get_rpg_voicevox_speaker_label(self) -> str:
            return self.current_speaker_label

        def set_rpg_voicevox_speaker_id(self, speaker_id: int, *, label: str | None = None) -> int:
            self.current_speaker_id = speaker_id
            if label:
                self.current_speaker_label = label
            return speaker_id

        def find_rpg_voicevox_style(self, query: str):
            normalized = query.strip()
            if normalized == "ずんだもん":
                return (
                    {"style_id": 3, "label": "ずんだもん / ノーマル"},
                    [{"style_id": 3, "label": "ずんだもん / ノーマル"}],
                )
            if normalized == "春日部":
                return (
                    None,
                    [
                        {"style_id": 8, "label": "春日部つむぎ / ノーマル"},
                        {"style_id": 9, "label": "春日部つむぎ / ツンツン"},
                    ],
                )
            return None, []

        def save_data(self) -> None:
            self.saved += 1

    class _Ctx:
        def __init__(self, chatter_id: str) -> None:
            self.chatter = SimpleNamespace(
                name="streamer",
                login="streamer",
                display_name="Streamer",
                id=chatter_id,
            )
            self.replies = []

        async def reply(self, message: str) -> None:
            self.replies.append(message)

    async def test_voicevox_speaker_command_shows_current_id_without_argument(self) -> None:
        commands = BasicCommands(self._SpeakerBot())
        ctx = self._Ctx("owner")

        await commands.set_voicevox_speaker_id.callback(commands, ctx, speaker_id=None)

        self.assertEqual(
            ctx.replies,
            ["RPG読み上げVOICEVOX ID は 4 です。 `!管理 読み上げID <数字>` で変更できます。"],
        )

    async def test_voicevox_speaker_command_updates_id_for_owner(self) -> None:
        bot = self._SpeakerBot()
        commands = BasicCommands(bot)
        ctx = self._Ctx("owner")

        await commands.set_voicevox_speaker_id.callback(commands, ctx, speaker_id="9")

        self.assertEqual(bot.current_speaker_id, 9)
        self.assertEqual(bot.saved, 1)
        self.assertEqual(ctx.replies, ["RPG読み上げVOICEVOX ID を 9 に変更しました。"])

    async def test_voicevox_speaker_command_rejects_non_owner(self) -> None:
        bot = self._SpeakerBot()
        commands = BasicCommands(bot)
        ctx = self._Ctx("viewer")

        await commands.set_voicevox_speaker_id.callback(commands, ctx, speaker_id="9")

        self.assertEqual(bot.current_speaker_id, 4)
        self.assertEqual(bot.saved, 0)
        self.assertEqual(ctx.replies, ["このコマンドは配信者のみ使用できます。"])

    async def test_voicevox_speaker_name_command_shows_current_name_without_argument(self) -> None:
        commands = BasicCommands(self._SpeakerBot())
        ctx = self._Ctx("owner")

        await commands.set_voicevox_speaker_name.callback(commands, ctx, speaker_query=None)

        self.assertEqual(
            ctx.replies,
            ["RPG読み上げ話者は 四国めたん / ノーマル (ID:4) です。 `!管理 読み上げ話者 <話者名>` で変更できます。"],
        )

    async def test_voicevox_speaker_name_command_updates_style_from_name(self) -> None:
        bot = self._SpeakerBot()
        commands = BasicCommands(bot)
        ctx = self._Ctx("owner")

        await commands.set_voicevox_speaker_name.callback(commands, ctx, speaker_query="ずんだもん")

        self.assertEqual(bot.current_speaker_id, 3)
        self.assertEqual(bot.current_speaker_label, "ずんだもん / ノーマル")
        self.assertEqual(bot.saved, 1)
        self.assertEqual(
            ctx.replies,
            ["RPG読み上げ話者を ずんだもん / ノーマル (ID:3) に変更しました。"],
        )

    async def test_voicevox_speaker_name_command_shows_candidates_when_ambiguous(self) -> None:
        bot = self._SpeakerBot()
        commands = BasicCommands(bot)
        ctx = self._Ctx("owner")

        await commands.set_voicevox_speaker_name.callback(commands, ctx, speaker_query="春日部")

        self.assertEqual(bot.current_speaker_id, 4)
        self.assertEqual(bot.saved, 0)
        self.assertEqual(
            ctx.replies,
            [
                "候補が複数あります。 春日部つむぎ / ノーマル / 春日部つむぎ / ツンツン / `!管理 読み上げ話者 <話者名 スタイル名>` で絞ってください。"
            ],
        )


if __name__ == "__main__":
    unittest.main()
