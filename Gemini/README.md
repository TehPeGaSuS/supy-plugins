Gemini: Google AI Gemini chat for Limnoria

Chat with Google's Gemini models from IRC, with per-channel conversation history.

## Requirements

The `google-genai` SDK, 1.51 or newer (the old `google-generativeai` package is no longer supported):
```
pip install -r requirements.txt
```

## Setup

Get an API key from https://aistudio.google.com/app/apikey and set it:
```
@config plugins.Gemini.api_key YOUR_KEY_HERE
```

Set the bot's personality (`$botnick` is replaced by the bot's nick). Like most options, it can be set per channel with `@config channel #chan plugins.Gemini.prompt ...`:
```
@config plugins.Gemini.prompt "You are $botnick the IRC bot. Be brief, helpful"
```

Please take a look at the other options before you start (see the table below):
```
@config list plugins.Gemini
```

## Usage

```
@gemini chat <text>
```
Sends `<text>` to Gemini and replies with the answer. A plain `@chat` works too, unless another loaded plugin (like ChatGPT) also has a `chat` command.

To answer whenever the bot's nick is mentioned, replace `BOT_NICK_HERE` with the bot's nick:
```
@messageparser add "(?i)(.*BOT_NICK_HERE.*)" "gemini chat $1"
@config reply.whenAddressedBy.nick False
```
The second line stops the bot from also treating `BOT_NICK_HERE: hi` as a command, so the mention doesn't get two answers.

## Models and thinking

The default model is `gemini-3.8-flash`. See https://ai.google.dev/gemini-api/docs/models for the current list; `gemini-flash-latest` always points at the newest Flash model.

Gemini 3 models think before answering, and thinking tokens count towards `max_tokens`. `thinking_level` defaults to `minimal`; raise `max_tokens` if you raise it, or answers get cut short. `minimal` isn't supported by Gemini 3 Pro models, and Gemini 2.5 or older models don't have thinking levels at all, so clear it for those:
```
@config plugins.Gemini.thinking_level ""
```

## Replies and errors

Answers are sent in full: long lines are split into several messages that fit the IRC line limit (taking the bot's real `nick!ident@host`, the channel and any nick prefix into account) instead of being held back for `@more`, whatever `supybot.reply.mores.instant` says. `supybot.reply.mores.maximum` still caps the number of messages. Set `full_reply` to `False` for the normal `@more` behaviour.

When `chat` fails (model busy, rate limit or quota, timeout, bad API key or model, empty answer), the bot replies with a short error saying why. This only happens when someone runs the command directly: lines that MessageParser turns into `chat` stay silent, so a busy API doesn't spam the channel. Set `error_reply` to `False` to turn it off. Failures are always logged.

## Options

All options can be set globally, per network or per channel.

| Option | Default | Description |
|---|---|---|
| `enabled` | `True` | Answer `chat` at all. |
| `api_key` | (empty) | Your Google AI API key (required). |
| `model` | `gemini-3.8-flash` | Model to use. |
| `thinking_level` | `minimal` | `minimal`, `low`, `medium`, `high`, or empty for models without thinking levels. |
| `prompt` | "You are $botnick the IRC bot. Be brief, helpful. …" | System prompt; `$botnick` is replaced by the bot's nick. |
| `max_tokens` | `200` | Maximum tokens per answer, thinking included. |
| `max_history` | `50` | Messages of conversation history kept per channel (or per nick in private). `0` disables history. |
| `nick_include` | `True` | Send the user's nick with each message, so the model can tell people apart. |
| `nick_prefix` | `False` | Prefix replies with the user's nick. |
| `nick_strip` | `True` | Remove `botnick: ` from the start of answers. |
| `full_reply` | `True` | Send the whole answer instead of holding the rest back for `@more`. |
| `error_reply` | `True` | Reply with a short error when `chat` fails (not for MessageParser triggers). |
| `timeout` | `60` | Seconds to wait for Gemini; `0` waits forever (not recommended). |
