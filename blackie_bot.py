"""A Twitch chat bot with commands, phrase replies, and timers defined in JSON."""

import asyncio
import logging
import random
import time

from twitchio.ext import commands
from twitchio.ext.commands import CommandNotFound, CommandOnCooldown

from bot_config import load_config
from response_data import load_responses, matches_trigger


logger = logging.getLogger(__name__)


class Bot(commands.Bot):
    def __init__(self, config, responses):
        super().__init__(
            token=config.token,
            prefix=config.prefix,
            initial_channels=list(config.channels),
        )
        self.config = config
        self.responses = responses
        self._timer_tasks = {}
        self._trigger_last_sent = {}
        for name, definition in responses["commands"].items():
            if definition.get("enabled", True):
                self.add_command(self._make_command(name, definition))

    def _make_command(self, name, definition):
        async def callback(ctx):
            await self._send_command_response(ctx, definition)

        command = commands.Command(name, callback, aliases=definition.get("aliases", []))
        seconds = definition.get("cooldown_seconds", 0)
        if seconds:
            commands.cooldown(rate=1, per=seconds, bucket=commands.Bucket.channel)(command)
        return command

    def _variables(self, channel, user=""):
        return {
            "user": user,
            "user_upper": user.upper(),
            "channel": channel.name,
            "prefix": self.config.prefix,
        }

    def _is_self(self, username):
        return username.casefold() in {
            self.config.bot_name.casefold(), (self.nick or "").casefold()
        }

    async def _send_command_response(self, ctx, definition):
        user = ctx.author.name
        variables = self._variables(ctx.channel, user)
        kind = definition.get("type", "response")
        responses = definition["responses"]
        if kind in ("interaction", "fight"):
            viewers = [
                chatter.name for chatter in ctx.channel.chatters
                if not definition.get("exclude_bot", True) or not self._is_self(chatter.name)
            ]
            target = random.choice(viewers) if viewers else None
            if target is None or target.casefold() == user.casefold():
                responses = definition["fallback_responses"]
            else:
                variables["target"] = target
                if kind == "fight":
                    variables["winner"] = random.choice([user, target])
        await ctx.send(random.choice(responses).format(**variables))

    async def event_ready(self):
        logger.info("Connected to Twitch as %s", self.nick or self.config.bot_name)
        for name, timer in self.responses["timers"].items():
            if not timer.get("enabled", True) or timer.get("interval_seconds", 0) == 0:
                continue
            task = self._timer_tasks.get(name)
            if task is None or task.done():
                self._timer_tasks[name] = asyncio.create_task(self._run_timer(timer))

    async def _run_timer(self, timer):
        while True:
            await asyncio.sleep(timer["interval_seconds"])
            for channel in self.connected_channels:
                try:
                    text = random.choice(timer["responses"]).format(**self._variables(channel))
                    await channel.send(text)
                except Exception:
                    logger.exception("Could not send a timed message to %s", channel.name)

    async def event_message(self, message):
        if getattr(message, "echo", False) or message.author is None:
            return
        user = message.author.name
        if self._is_self(user) or user.casefold() in self.config.ignored_users:
            return

        variables = self._variables(message.channel, user)
        for index, rule in enumerate(self.responses["triggers"]):
            if not rule.get("enabled", True) or not matches_trigger(rule, message.content):
                continue
            key = (message.channel.name.casefold(), index)
            now = time.monotonic()
            last_sent = self._trigger_last_sent.get(key)
            if last_sent is not None and now - last_sent < rule.get("cooldown_seconds", 0):
                continue
            self._trigger_last_sent[key] = now
            await message.channel.send(random.choice(rule["responses"]).format(**variables))

        await self.handle_commands(message)

    async def event_command_error(self, ctx, error):
        if isinstance(error, CommandNotFound):
            return
        if isinstance(error, CommandOnCooldown):
            logger.info("Command %s is on cooldown for %.1f seconds", ctx.command.name, error.retry_after)
        else:
            logger.error("Command failed: %s", error)

    async def close(self):
        tasks = list(self._timer_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._timer_tasks.clear()
        # TwitchIO 2 can fail token validation before starting its keep-alive task.
        if self._connection._keeper is None:
            if self._closing is not None:
                self._closing.set()
            if self._connection._websocket is not None:
                await self._connection._websocket.close()
            if self._http.session is not None:
                await self._http.session.close()
        else:
            await super().close()


async def start_bot():
    config = load_config()
    responses = load_responses()
    while True:
        bot = Bot(config, responses)
        try:
            await bot.start()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Connection failed; retrying in %s seconds", config.reconnect_delay)
        else:
            return
        finally:
            await bot.close()
        await asyncio.sleep(config.reconnect_delay)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        pass
    except ValueError as error:
        logger.error("Setup error: %s", error)
        raise SystemExit(1)
