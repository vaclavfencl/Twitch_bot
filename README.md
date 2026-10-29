# Blackie Twitch Bot

A configurable Twitch chat bot originally made for the Karas community. It provides viewer interactions, random quotes, automatic phrase replies, and scheduled reminders. The supplied responses preserve the original mix of Czech and English text and humor.

Chat content lives in `responses.json`. You can add reply commands, aliases, phrase matches, and timers without changing Python code. Private settings live in `config.txt`.

## Setup

1. Install Python 3.10 or newer and make sure `python` is available on PATH.
2. On Windows, double-click `install_dependencies.bat`, or run this from the project folder:

   ```sh
   python -m pip install -r requirements.txt
   ```

3. Copy `config.txt.example` to `config.txt` and fill in your settings. If you already have a configured local file, keep it.
4. Obtain a **user access token for the bot's Twitch account**, with the IRC scopes `chat:read` and `chat:edit`. See Twitch's [OAuth guide](https://dev.twitch.tv/docs/authentication/getting-tokens-oauth/) and [IRC authentication documentation](https://dev.twitch.tv/docs/chat/irc/). An application access token is not a substitute. Never publish your token.
5. Start the bot:

   ```sh
   python blackie_bot.py
   ```

The requirements pin **TwitchIO 2.10.0**, matching this bot's IRC interface. TwitchIO 3 uses a different interface and is not a drop-in upgrade. Token refresh is not implemented: replace an expired or revoked token in your local config and restart.

## Configuration

```ini
token = CHANGE_THIS_TEXT_FOR_YOUR_TWITCH_USER_ACCESS_TOKEN
bot_name = your_bot_username
channels = your_channel, another_channel
prefix = !
ignored_users = streamelements
reconnect_delay = 10
```

| Setting | Purpose |
| --- | --- |
| `token` | Bot account's user access token, with or without `oauth:`. Do not add quotes. |
| `bot_name` | Twitch username associated with that token. |
| `channels` | Comma-separated channel usernames, without Twitch URLs. |
| `prefix` | Command prefix, such as `!`. |
| `ignored_users` | Comma-separated users whose messages the bot ignores. Leave empty to ignore no additional users. The bot always ignores itself. |
| `reconnect_delay` | Positive number of seconds to wait after a connection failure. |

Config and JSON paths are resolved relative to the scripts, so launching from another folder also works. Restart after editing either file. Invalid settings or response templates produce a setup error before connecting.

`.gitignore` excludes the real `config.txt`, Python caches, and `.venv`. The example config contains placeholders only.

## Included commands

| Command | Behavior | Cooldown per channel |
| --- | --- | --- |
| `!slap` | Choose a chatter for a slap response. | 30 seconds |
| `!kiss` | Choose a chatter for a kiss response. | 30 seconds |
| `!hug` | Choose a chatter for a hug response. | 30 seconds |
| `!fight` | Choose an opponent and randomly choose the winner. | 30 seconds |
| `!deep` | Send a random dark-humor response. | 60 seconds |
| `!gf` | Send the original joke response. | 30 seconds |
| `!gravity` | Send a random Gravity Falls quote. Aliases: `!bestshow`, `!help`. | 30 seconds |

Viewer selection uses TwitchIO's cached chatters, which may not include everyone watching. If the list is empty or the selected chatter is the caller, the bot uses a fallback response. These commands select randomly; they do not take a target username argument.

The included timers send a random chat tip every **300 seconds** and a water reminder every **1900 seconds** to each connected channel. They run while the bot is connected, even if the stream is offline.

## Edit commands in JSON

`responses.json` has three sections: `commands`, `triggers`, and `timers`. Keep it valid UTF-8 JSON with double quotes and no comments or trailing commas.

To add a simple command, add an entry inside `commands`:

```json
"discord": {
  "type": "response",
  "aliases": ["dc"],
  "cooldown_seconds": 30,
  "responses": ["Join our Discord: https://example.com/invite"]
}
```

This registers `!discord` and `!dc`. Names and aliases must be unique lowercase letters, numbers, or underscores; omit the prefix from their names. Multiple responses are chosen randomly. Aliases share the command's cooldown. Set `enabled` to `false` to disable an entry, or set `cooldown_seconds` to `0` for no command cooldown.

Supported command types:

- `response`: send a random response.
- `interaction`: choose a random chatter as `{target}`. Requires `fallback_responses` for an empty list or a self-target. `exclude_bot` defaults to `true`.
- `fight`: like `interaction`, with a random `{winner}` chosen from the caller and opponent.

Copy an existing interaction or fight entry to add another command of that type. New behavior beyond these three types requires Python changes.

## Word and phrase replies

Add an object to the `triggers` list:

```json
{
  "phrases": ["hello there"],
  "match": "contains",
  "mode": "any",
  "cooldown_seconds": 10,
  "responses": ["GENERAL {user_upper}!"]
}
```

All matching is case-insensitive:

- `contains`: match the phrase anywhere, including inside another word. This preserves the original bot's matching behavior.
- `words`: match whole words or a whole multiword phrase; `cat` matches `cat!` but not `catalog`.
- `exact`: match the entire message, ignoring leading and trailing whitespace.

`mode` can be `any` (at least one listed phrase) or `all` (every listed phrase must match). For example, `phrases: ["hello", "there"]` with `match: "words"` and `mode: "all"` matches both words anywhere in the message. Use a single `"hello there"` phrase when their order and adjacency matter.

Every matching trigger can send one reply, then commands are processed as well. Trigger cooldowns are independent per rule and per channel, and default to `0`. Use `enabled: false` to disable a rule. Messages from the bot itself, echo messages, and configured ignored users are skipped.

## Scheduled messages

Add a named entry inside `timers`:

```json
"stretch": {
  "interval_seconds": 1800,
  "responses": ["Time to stand up and stretch!"]
}
```

Each timer waits its interval before the first message and sends one randomly selected response to each connected channel. Set `enabled` to `false` or `interval_seconds` to `0` to disable it. Repeated text in a response list intentionally increases its selection probability.

## Template placeholders

| Placeholder | Available in |
| --- | --- |
| `{user}` | Commands, fallbacks, and phrase replies; the caller's username. |
| `{user_upper}` | Commands, fallbacks, and phrase replies; username in uppercase. |
| `{target}` | Successful interaction and fight responses. |
| `{winner}` | Successful fight responses. |
| `{channel}` | All responses; the channel username. |
| `{prefix}` | All responses; the configured command prefix. |

Use `{{` and `}}` for literal braces. A placeholder cannot be used outside its supported context. Console diagnostics remain in Python; all chat replies and reminder text are in JSON.

## Offline checks

Run the tests from this folder after installing requirements:

```sh
python -B -m unittest discover -s tests -v
```

Tests use fake messages and tokens; they do not connect to Twitch or send chat messages.
