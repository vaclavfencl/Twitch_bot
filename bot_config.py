"""Load private Twitch settings from config.txt next to this module."""

from configparser import ConfigParser, Error as ConfigError
from dataclasses import dataclass, field
import math
from pathlib import Path
import re


CONFIG_PATH = Path(__file__).with_name("config.txt")


@dataclass(frozen=True)
class BotConfig:
    token: str = field(repr=False)
    bot_name: str
    channels: tuple[str, ...]
    prefix: str = "!"
    ignored_users: tuple[str, ...] = ("streamelements",)
    reconnect_delay: float = 10


def load_config(path=CONFIG_PATH):
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ValueError(
            "Missing config.txt. Copy config.txt.example to config.txt and fill in your settings."
        ) from None

    parser = ConfigParser(interpolation=None, delimiters=("=",))
    try:
        parser.read_string("[bot]\n" + text)
    except ConfigError:
        raise ValueError("Invalid config.txt. Use one key = value setting per line.") from None
    section = parser["bot"]
    allowed = {"token", "bot_name", "channels", "prefix", "ignored_users", "reconnect_delay"}
    if set(section) - allowed or parser.sections() != ["bot"]:
        raise ValueError("Unknown config setting. Check config.txt.example for supported keys.")

    token = section.get("token", "").strip()
    if (not token.removeprefix("oauth:") or "CHANGE_THIS_TEXT" in token
            or any(character.isspace() for character in token)):
        raise ValueError("Set your Twitch user access token in config.txt (without quotation marks).")

    def username(value):
        value = value.strip().lstrip("#").lower()
        if not re.fullmatch(r"[a-z0-9_]{1,25}", value):
            raise ValueError("Bot, channel, and ignored-user names must be Twitch usernames, not URLs.")
        return value

    bot_name = username(section.get("bot_name", ""))
    channels = tuple(dict.fromkeys(
        username(value) for value in section.get("channels", "").split(",") if value.strip()
    ))
    if not channels:
        raise ValueError("Set at least one channel in config.txt.")
    ignored_users = tuple(
        username(value) for value in section.get("ignored_users", "streamelements").split(",")
        if value.strip()
    )
    prefix = section.get("prefix", "!").strip()
    if not prefix or any(character.isspace() for character in prefix):
        raise ValueError("The command prefix must be nonempty and contain no whitespace.")
    try:
        delay = float(section.get("reconnect_delay", "10"))
        if not math.isfinite(delay) or delay <= 0:
            raise ValueError
    except ValueError:
        raise ValueError("reconnect_delay must be a positive number of seconds.") from None

    return BotConfig(token, bot_name, channels, prefix, ignored_users, delay)
