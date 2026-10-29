"""Validate the editable chat content before the bot connects to Twitch."""

import json
import math
from pathlib import Path
import re
from string import Formatter


RESPONSES_PATH = Path(__file__).with_name("responses.json")
BASE_FIELDS = {"user", "user_upper", "channel", "prefix"}


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _seconds(entry, key, where, default=0):
    value = entry.get(key, default)
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0):
        raise ValueError(f"{where}.{key} must be a nonnegative number.")


def _entry(entry, where):
    if not isinstance(entry, dict):
        raise ValueError(f"{where} must be a JSON object.")
    if not isinstance(entry.get("enabled", True), bool):
        raise ValueError(f"{where}.enabled must be true or false.")


def _strings(value, where):
    if (not isinstance(value, list) or not value
            or any(not isinstance(item, str) or not item.strip() for item in value)):
        raise ValueError(f"{where} must be a nonempty list of nonempty strings.")


def _templates(value, where, fields):
    _strings(value, where)
    for text in value:
        try:
            parts = list(Formatter().parse(text))
        except ValueError:
            raise ValueError(f"Invalid braces in {where}. Use double braces for literal braces.") from None
        for _, name, spec, conversion in parts:
            if name is not None and (name not in fields or spec or conversion):
                raise ValueError(f"Unsupported placeholder in {where}: {{{name}}}")


def validate_responses(data):
    if not isinstance(data, dict) or set(data) != {"commands", "triggers", "timers"}:
        raise ValueError("responses.json must contain commands, triggers, and timers.")
    if not isinstance(data["commands"], dict) or not isinstance(data["timers"], dict):
        raise ValueError("commands and timers must be JSON objects.")
    if not isinstance(data["triggers"], list):
        raise ValueError("triggers must be a JSON list.")

    names = set()
    for name, entry in data["commands"].items():
        where = f"commands.{name}"
        _entry(entry, where)
        aliases = entry.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
            raise ValueError(f"{where}.aliases must be a list of command names.")
        for label in [name, *aliases]:
            if not re.fullmatch(r"[a-z0-9_]+", label) or label in names:
                raise ValueError(f"Command names and aliases must be unique lowercase names: {label}")
            names.add(label)
        kind = entry.get("type", "response")
        if kind not in ("response", "interaction", "fight"):
            raise ValueError(f"Unknown command type in {where}: {kind}")
        _seconds(entry, "cooldown_seconds", where)
        fields = BASE_FIELDS | ({"target"} if kind != "response" else set())
        if kind == "fight":
            fields = fields | {"winner"}
        _templates(entry.get("responses"), f"{where}.responses", fields)
        if kind != "response":
            if not isinstance(entry.get("exclude_bot", True), bool):
                raise ValueError(f"{where}.exclude_bot must be true or false.")
            _templates(entry.get("fallback_responses"), f"{where}.fallback_responses", BASE_FIELDS)

    for index, entry in enumerate(data["triggers"]):
        where = f"triggers[{index}]"
        _entry(entry, where)
        _strings(entry.get("phrases"), f"{where}.phrases")
        if entry.get("match", "contains") not in ("contains", "words", "exact"):
            raise ValueError(f"{where}.match must be contains, words, or exact.")
        if entry.get("mode", "any") not in ("any", "all"):
            raise ValueError(f"{where}.mode must be any or all.")
        _seconds(entry, "cooldown_seconds", where)
        _templates(entry.get("responses"), f"{where}.responses", BASE_FIELDS)

    for name, entry in data["timers"].items():
        where = f"timers.{name}"
        _entry(entry, where)
        _seconds(entry, "interval_seconds", where)
        _templates(entry.get("responses"), f"{where}.responses", {"channel", "prefix"})

    return data


def load_responses(path=RESPONSES_PATH):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_keys)
    except FileNotFoundError:
        raise ValueError("Missing responses.json. Keep it next to blackie_bot.py.") from None
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid responses.json at line {error.lineno}, column {error.colno}.") from None
    return validate_responses(data)


def matches_trigger(rule, content):
    """Match phrases case-insensitively, using the selected any/all policy."""
    content = content.casefold()
    match_type = rule.get("match", "contains")

    def matches(phrase):
        phrase = phrase.casefold()
        if match_type == "exact":
            return content.strip() == phrase.strip()
        if match_type == "words":
            return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", content) is not None
        return phrase in content

    results = (matches(phrase) for phrase in rule["phrases"])
    return all(results) if rule.get("mode", "any") == "all" else any(results)
