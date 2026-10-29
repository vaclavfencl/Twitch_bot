import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, PropertyMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import blackie_bot
from bot_config import BotConfig, load_config
from response_data import load_responses, matches_trigger, validate_responses


class ConfigTests(unittest.TestCase):
    def parse(self, text):
        with patch.object(Path, "read_text", return_value=text):
            return load_config()

    def test_settings_and_normalization(self):
        config = self.parse(
            "# Settings\ntoken = oauth:offline-token\nbot_name = Test_Bot\n"
            "channels = #First, SECOND, first\nprefix = ?\n"
            "ignored_users = StreamElements, Another_Bot\nreconnect_delay = 2.5\n"
        )
        self.assertEqual(config.token, "oauth:offline-token")
        self.assertEqual(config.bot_name, "test_bot")
        self.assertEqual(config.channels, ("first", "second"))
        self.assertEqual(config.ignored_users, ("streamelements", "another_bot"))
        self.assertEqual(config.prefix, "?")
        self.assertEqual(config.reconnect_delay, 2.5)
        self.assertNotIn("offline-token", repr(config))

    def test_bad_config_fails_without_echoing_secrets(self):
        base = "token = offline-token\nbot_name = test_bot\nchannels = test_channel\n"
        for text in (
            base.replace("offline-token", ""),
            base.replace("offline-token", "oauth:"),
            base.replace("offline-token", "CHANGE_THIS_TEXT_FOR_YOUR_TOKEN"),
            base.replace("test_channel", "https://twitch.tv/channel"),
            base.replace("channels = test_channel", "channels ="),
            base + "reconnect_delay = 0\n",
            base + "reconnect_delay = nan\n",
            base + "reconnect_delay = inf\n",
            base + "prefix = \n",
            base + "unknown = value\n",
            base + "token = duplicate-secret\n",
        ):
            with self.subTest(text=text):
                with self.assertRaises(ValueError) as error:
                    self.parse(text)
                self.assertNotIn("offline-token", str(error.exception))
                self.assertNotIn("duplicate-secret", str(error.exception))

    def test_missing_file_explains_setup(self):
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(ValueError, "config.txt.example"):
                load_config()

    def test_empty_ignore_list_is_allowed(self):
        config = self.parse(
            "token = offline-token\nbot_name = test_bot\nchannels = test_channel\nignored_users =\n"
        )
        self.assertEqual(config.ignored_users, ())


class ResponseDataTests(unittest.TestCase):
    def test_shipped_responses_are_valid(self):
        data = load_responses()
        self.assertEqual(len(data["commands"]), 7)
        self.assertEqual(len(data["triggers"]), 9)
        self.assertEqual(len(data["timers"]), 2)

    def test_bad_templates_fail_at_startup(self):
        for template in ("{typo}", "{user.upper}", "{user[0]}", "{user!r}", "{user:>10}", "{"):
            data = load_responses()
            data["commands"]["gf"]["responses"] = [template]
            with self.subTest(template=template), self.assertRaises(ValueError):
                validate_responses(data)

    def test_context_specific_placeholders(self):
        data = load_responses()
        data["timers"]["water_reminder"]["responses"] = ["Hello {user}"]
        with self.assertRaises(ValueError):
            validate_responses(data)
        data = load_responses()
        data["commands"]["hug"]["fallback_responses"] = ["Hug {target}"]
        with self.assertRaises(ValueError):
            validate_responses(data)

    def test_invalid_schema_is_rejected(self):
        mutations = (
            lambda d: d["commands"]["gf"].update(aliases=["help"]),
            lambda d: d["commands"]["gf"].update(responses=[]),
            lambda d: d["commands"]["gf"].update(cooldown_seconds=-1),
            lambda d: d["commands"]["gf"].update(cooldown_seconds=float("inf")),
            lambda d: d["commands"]["gf"].update(enabled="false"),
            lambda d: d["commands"]["gf"].update(type="unknown"),
            lambda d: d["triggers"][0].update(phrases=[]),
            lambda d: d["triggers"][0].update(match="regex"),
            lambda d: d["triggers"][0].update(mode="either"),
            lambda d: d["timers"]["chat_tips"].update(interval_seconds=True),
        )
        for mutate in mutations:
            data = load_responses()
            mutate(data)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                validate_responses(data)

    def test_json_errors_are_clear(self):
        for text in ('{"commands": {', '{"commands": {}, "commands": {}}'):
            with patch.object(Path, "read_text", return_value=text), self.assertRaises(ValueError):
                load_responses()

    def test_matching_modes_and_unicode(self):
        rule = {"phrases": ["hello there"]}
        self.assertTrue(matches_trigger(rule, "Well, HELLO THERE!"))
        self.assertFalse(matches_trigger(rule, "hello friend"))
        rule = {"phrases": ["cat"], "match": "words"}
        self.assertTrue(matches_trigger(rule, "A CAT!"))
        self.assertFalse(matches_trigger(rule, "catalog"))
        self.assertFalse(matches_trigger(rule, "čcat"))
        rule = {"phrases": ["hello there"], "match": "exact"}
        self.assertTrue(matches_trigger(rule, " HELLO THERE "))
        self.assertFalse(matches_trigger(rule, "hello there!"))
        rule = {"phrases": ["hello", "there"], "match": "words", "mode": "all"}
        self.assertTrue(matches_trigger(rule, "There you are, hello!"))
        self.assertFalse(matches_trigger(rule, "hello everyone"))


class BotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.data = load_responses()
        self.config = BotConfig("offline-token", "test_bot", ("test_channel",))
        self.bot = blackie_bot.Bot(self.config, self.data)
        self.channel = SimpleNamespace(name="test_channel", chatters=[], send=AsyncMock())

    async def asyncTearDown(self):
        await self.bot.close()

    def message(self, text, user="alice", channel=None, echo=False):
        return SimpleNamespace(
            content=text, author=SimpleNamespace(name=user, id=1, _ws=None),
            channel=channel or self.channel, tags={}, echo=echo,
        )

    async def invoke(self, text, user="alice", channel=None):
        # Use TwitchIO's real parser, command lookup, aliases, and cooldowns.
        with patch.object(blackie_bot.commands.Context, "send", new_callable=AsyncMock) as send:
            await self.bot.event_message(self.message(text, user, channel))
            return send.await_args_list

    async def test_all_commands_and_aliases_register(self):
        self.assertEqual(set(self.bot.commands), set(self.data["commands"]))
        for alias in ("help", "bestshow"):
            calls = await self.invoke("!" + alias)
            if alias == "help":
                self.assertIn(calls[0].args[0], self.data["commands"]["gravity"]["responses"])
            else:
                self.assertEqual(calls, [])  # Aliases share the same cooldown.

    async def test_added_json_command_works_without_python_changes(self):
        data = deepcopy(self.data)
        data["commands"]["welcome"] = {
            "aliases": ["hi"], "responses": ["Hello {user} in {channel}; prefix {prefix}"]
        }
        await self.bot.close()
        self.bot = blackie_bot.Bot(self.config, validate_responses(data))
        calls = await self.invoke("!hi")
        self.assertEqual(calls[0].args[0], "Hello alice in test_channel; prefix !")

    async def test_empty_chatters_and_self_targets_use_fallbacks(self):
        for name in ("slap", "kiss", "hug", "fight"):
            definition = self.data["commands"][name]
            ctx = SimpleNamespace(author=SimpleNamespace(name="alice"), channel=self.channel, send=AsyncMock())
            for viewers in ([], [SimpleNamespace(name="alice")]):
                self.channel.chatters = viewers
                await self.bot._send_command_response(ctx, definition)
                self.assertEqual(ctx.send.await_args.args[0], definition["fallback_responses"][0].format(user="alice"))

    async def test_interactions_and_fight_templates(self):
        self.channel.chatters = [SimpleNamespace(name="test_bot"), SimpleNamespace(name="bob")]
        ctx = SimpleNamespace(author=SimpleNamespace(name="alice"), channel=self.channel, send=AsyncMock())
        for name in ("kiss", "hug", "fight"):
            definition = dict(self.data["commands"][name])
            definition["responses"] = ["{user}/{target}/{winner}" if name == "fight" else "{user}/{target}"]
            await self.bot._send_command_response(ctx, definition)
            text = ctx.send.await_args.args[0]
            self.assertIn(text, ("alice/bob", "alice/bob/alice", "alice/bob/bob"))

    async def test_hello_there_and_multiple_matches(self):
        await self.bot.event_message(self.message("HELLO THERE, baf"))
        texts = [call.args[0] for call in self.channel.send.await_args_list]
        self.assertEqual(texts, ["lek", "GENERAL ALICE!"])

    async def test_ignored_and_self_messages(self):
        for user, echo in (("TEST_BOT", False), ("StreamElements", False), ("alice", True)):
            await self.bot.event_message(self.message("hello there", user=user, echo=echo))
        message = self.message("hello there")
        message.author = None
        await self.bot.event_message(message)
        self.channel.send.assert_not_awaited()

    async def test_trigger_cooldown_is_per_channel(self):
        self.data["triggers"] = [{"phrases": ["ping"], "responses": ["pong"], "cooldown_seconds": 10}]
        other = SimpleNamespace(name="other_channel", chatters=[], send=AsyncMock())
        with patch.object(blackie_bot.time, "monotonic", return_value=100):
            await self.bot.event_message(self.message("ping"))
            await self.bot.event_message(self.message("ping"))
            await self.bot.event_message(self.message("ping", channel=other))
        self.channel.send.assert_awaited_once_with("pong")
        other.send.assert_awaited_once_with("pong")
        with patch.object(blackie_bot.time, "monotonic", return_value=111):
            await self.bot.event_message(self.message("ping"))
        self.assertEqual(self.channel.send.await_count, 2)

    async def test_command_cooldown_is_per_channel(self):
        self.assertEqual(len(await self.invoke("!gf")), 1)
        self.assertEqual(await self.invoke("!gf", user="bob"), [])
        other = SimpleNamespace(name="another_channel", chatters=[], send=AsyncMock())
        self.assertEqual(len(await self.invoke("!gf", channel=other)), 1)

    async def test_disabled_entries_do_nothing(self):
        data = deepcopy(self.data)
        data["commands"]["gf"]["enabled"] = False
        for rule in data["triggers"]:
            rule["enabled"] = False
        for timer in data["timers"].values():
            timer["enabled"] = False
        await self.bot.close()
        self.bot = blackie_bot.Bot(self.config, validate_responses(data))
        self.assertNotIn("gf", self.bot.commands)
        await self.bot.event_message(self.message("hello there"))
        await self.bot.event_ready()
        self.assertFalse(self.bot._timer_tasks)
        self.channel.send.assert_not_awaited()

    async def test_ready_does_not_duplicate_timers_and_close_cancels_them(self):
        await self.bot.event_ready()
        tasks = dict(self.bot._timer_tasks)
        await self.bot.event_ready()
        self.assertEqual(self.bot._timer_tasks, tasks)
        await self.bot.close()
        self.assertTrue(all(task.cancelled() for task in tasks.values()))

    async def test_timer_formats_each_channel_and_is_cancellable(self):
        other = SimpleNamespace(name="second", send=AsyncMock())
        sleeps = AsyncMock(side_effect=[None, asyncio.CancelledError])
        timer = {"interval_seconds": 123, "responses": ["{prefix} in {channel}"]}
        with patch.object(blackie_bot.commands.Bot, "connected_channels", new_callable=PropertyMock,
                          return_value=[self.channel, other]), \
             patch.object(blackie_bot.asyncio, "sleep", sleeps):
            with self.assertRaises(asyncio.CancelledError):
                await self.bot._run_timer(timer)
        self.channel.send.assert_awaited_once_with("! in test_channel")
        other.send.assert_awaited_once_with("! in second")
        sleeps.assert_any_await(123)

    async def test_early_connection_failure_closes_resources(self):
        self.bot._http.session = AsyncMock()
        self.bot._connection._websocket = AsyncMock()
        self.bot._closing = asyncio.Event()
        await self.bot.close()
        self.assertTrue(self.bot._closing.is_set())
        self.bot._http.session.close.assert_awaited_once()
        self.bot._connection._websocket.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
