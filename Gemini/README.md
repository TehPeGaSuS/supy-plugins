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

## Web search

```
@gemini search <text>
```
Like `chat`, but Gemini may search the web with Google Search before answering, and the answer ends with a short list of the source websites. `chat` never searches. Use the plugin prefix here: a bare `search` is Limnoria's own `config search` command.

Google Search grounding needs a Google project with **billing enabled**: the free tier doesn't include it. A billed project gets 5,000 searches a month free (shared across Gemini 3 models), then $14 per 1,000. But billing applies to the whole project, so every `chat` on it would be billed too. To keep chat free, you can have two projects:

- a project **without billing** for chat: its key goes in `api_key`;
- a project **with billing** (ideally with a spending cap) for search only: its key goes in `search_api_key`.

```
@config plugins.Gemini.api_key FREE_PROJECT_KEY
@config plugins.Gemini.search_api_key BILLED_PROJECT_KEY
```
With a single billed project, just leave `search_api_key` empty and `api_key` is used for both.

To stay inside the free 5,000 searches, the plugin counts the searches Google runs (one answer can run several) and stops at `search_daily_limit` (default 150) and `search_monthly_limit` (default 4,800), whichever comes first. The count covers every network, channel and key, is kept across restarts, and resets at midnight Pacific time like Google's. When a limit is reached, `search` says so and `chat` keeps working. See the usage with:
```
@gemini searches
```
The limits only know about this bot: other bots or programs using the same billed project share Google's 5,000 but not this count. If several bots use the same key, split the limits between them, e.g. three bots with `search_daily_limit 50` and `search_monthly_limit 1600` each.

`search_prompt` is added to `prompt` for searches. By default it asks for plain IRC text: no Markdown, no citation markers, no footnotes and no URLs (Google's source links are long redirects; the bot lists the source sites itself, see `search_sources`).

## Replies and errors

Answers are sent in full: long lines are split into several messages that fit the IRC line limit (taking the bot's real `nick!ident@host`, the channel and any nick prefix into account) instead of being held back for `@more`, whatever `supybot.reply.mores.instant` says. `supybot.reply.mores.maximum` still caps the number of messages. Set `full_reply` to `False` for the normal `@more` behaviour.

When `chat` fails (model busy, rate limit or quota, timeout, bad API key or model, empty answer), the bot replies with a short error saying why. This only happens when someone runs the command directly: lines that MessageParser turns into `chat` stay silent, so a busy API doesn't spam the channel. Set `error_reply` to `False` to turn it off. Failures are always logged.

## Options

Options marked global apply to the whole bot; the others can be set globally, per network or per channel.

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
| `search_api_key` | (empty) | Key for the `search` command (a billed project); empty uses `api_key`. |
| `search_prompt` | "This answer may use Google Search results. Reply in plain text for IRC: …" | Added to `prompt` for searches; empty adds nothing. |
| `search_sources` | `3` | Source websites listed after a search answer; `0` hides them. |
| `search_daily_limit` | `150` | Google searches per day, all networks and channels; `0` disables search. Global. |
| `search_monthly_limit` | `4800` | Google searches per month, all networks and channels; `0` disables search. Global. |
