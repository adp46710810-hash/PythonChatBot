from __future__ import annotations

import unittest

from twitchio.ext import commands

from bot import StreamBot


class _Log:
    def exception(self, *_args, **_kwargs) -> None:
        return None

    def info(self, *_args, **_kwargs) -> None:
        return None


class _Payload:
    def __init__(self, text: str, *, chatter_id: str = "viewer") -> None:
        self.text = text
        self.chatter = type(
            "Chatter",
            (),
            {
                "id": chatter_id,
                "name": "alice",
                "login": "alice",
                "display_name": "Alice",
            },
        )()
        self.source_broadcaster = None


class _Context:
    def __init__(
        self,
        *,
        result: bool = True,
        failed: bool = False,
        command=object(),
        raises: Exception | None = None,
    ) -> None:
        self._result = result
        self._failed = failed
        self._command = command
        self._raises = raises

    async def invoke(self) -> bool:
        if self._raises is not None:
            raise self._raises
        return self._result

    @property
    def command(self):
        return self._command

    @property
    def failed(self) -> bool:
        return self._failed


class _InvokeBot:
    def __init__(self, ctx: _Context) -> None:
        self._ctx = ctx

    def get_context(self, _payload):
        return self._ctx


class _ChainBot:
    _split_chained_command_text = StreamBot._split_chained_command_text
    _clone_chat_message_with_text = StreamBot._clone_chat_message_with_text

    def __init__(self, results: dict[str, bool]) -> None:
        self.results = results
        self.auto_finalize_calls: list[str] = []
        self.command_calls: list[str] = []
        self.log = _Log()

    async def _maybe_auto_finalize_from_message(self, payload) -> None:
        self.auto_finalize_calls.append(payload.text)

    async def _invoke_command_payload(self, payload) -> bool:
        self.command_calls.append(payload.text)
        return self.results.get(payload.text, True)


class _EventBot:
    bot_id = "bot"

    def __init__(self) -> None:
        self.chain_calls: list[str] = []
        self.processed_calls: list[str] = []
        self.auto_finalize_calls: list[str] = []
        self.log = _Log()

    async def _maybe_process_chained_commands(self, payload) -> bool:
        self.chain_calls.append(payload.text)
        return True

    async def _maybe_auto_finalize_from_message(self, payload) -> None:
        self.auto_finalize_calls.append(payload.text)

    async def process_commands(self, payload) -> None:
        self.processed_calls.append(payload.text)


class ChainedCommandTests(unittest.IsolatedAsyncioTestCase):
    def test_split_chained_command_text_supports_fullwidth_semicolon(self) -> None:
        actual = StreamBot._split_chained_command_text(object(), "！状態；探索 結果；!wb")

        self.assertEqual(actual, ["!状態", "!探索 結果", "!wb"])

    async def test_invoke_command_payload_returns_false_for_unknown_or_failed_command(self) -> None:
        unknown_bot = _InvokeBot(_Context(raises=commands.CommandNotFound('The command "missing" was not found.')))
        failed_bot = _InvokeBot(_Context(failed=True))
        success_bot = _InvokeBot(_Context())

        self.assertFalse(await StreamBot._invoke_command_payload(unknown_bot, _Payload("!missing")))
        self.assertFalse(await StreamBot._invoke_command_payload(failed_bot, _Payload("!状態")))
        self.assertTrue(await StreamBot._invoke_command_payload(success_bot, _Payload("!状態")))

    async def test_process_chained_commands_stops_after_first_non_executable_command(self) -> None:
        bot = _ChainBot(
            {
                "!状態": True,
                "!探索 結果": False,
                "!wb": True,
            }
        )

        consumed = await StreamBot._maybe_process_chained_commands(
            bot,
            _Payload("!状態；!探索 結果；!wb"),
        )

        self.assertTrue(consumed)
        self.assertEqual(bot.auto_finalize_calls, ["!状態", "!探索 結果"])
        self.assertEqual(bot.command_calls, ["!状態", "!探索 結果"])

    async def test_event_message_returns_after_chained_command_processing(self) -> None:
        bot = _EventBot()

        await StreamBot.event_message(bot, _Payload("!状態；!wb"))

        self.assertEqual(bot.chain_calls, ["!状態；!wb"])
        self.assertEqual(bot.auto_finalize_calls, [])
        self.assertEqual(bot.processed_calls, [])


if __name__ == "__main__":
    unittest.main()
