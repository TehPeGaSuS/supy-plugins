ChatGPT: OpenAI chat for Limnoria

Chat with OpenAI's models, or any OpenAI-compatible API (Groq, OpenRouter, a local server...), from IRC, with per-channel conversation history.

## Requirements

The `openai` SDK, 1.58 or newer:
```
pip install -r requirements.txt
```

## Setup

Get an API key from https://platform.openai.com/account/api-keys and set it:
```
@config plugins.ChatGPT.api_key YOUR_KEY_HERE
```

Set the bot's personality (`$botnick` is replaced by the bot's nick). Like most options, it can be set per channel with `@config channel #chan plugins.ChatGPT.prompt ...`:
```
@config plugins.ChatGPT.prompt "You are $botnick the IRC bot. Be brief, helpful"
```

Please take a look at the other options before you start (see the table below):
```
@config list plugins.ChatGPT
```

## Usage

```
@chatgpt chat <text>
```
Sends `<text>` to the API and replies with the answer. A plain `@chat` works too, unless another loaded plugin (like Gemini) also has a `chat` command.

To answer whenever the bot's nick is mentioned, replace `BOT_NICK_HERE` with the bot's nick:
```
@messageparser add "(?i)(.*BOT_NICK_HERE.*)" "chatgpt chat $1"
@config reply.whenAddressedBy.nick False
```
The second line stops the bot from also treating `BOT_NICK_HERE: hi` as a command, so the mention doesn't get two answers.

## Models and reasoning

The default model is `gpt-6-luna`. See https://developers.openai.com/api/docs/models for the current list. Older defaults are going away: `gpt-4o-mini` shuts down on 2027-01-14 and `gpt-5-nano` on 2026-12-11.

Reasoning models think before answering, and reasoning tokens count towards `max_tokens`. `reasoning_effort` defaults to `none`; raise `max_tokens` if you raise it, or answers come back empty. Supported values depend on the model: `gpt-6-luna` takes `none`, `low`, `medium`, `high`, `xhigh` and `max`, while older GPT-5 models take `minimal` instead of `none`.

`temperature`, `top_p`, `presence_penalty` and `frequency_penalty` are only sent when changed from their defaults, since reasoning models reject them.

## Other OpenAI-compatible servers

Point `base_url` at the server, pick one of its models, and clear `reasoning_effort` unless the model supports it. For example, Groq:
```
@config plugins.ChatGPT.base_url https://api.groq.com/openai/v1
@config plugins.ChatGPT.api_key YOUR_GROQ_KEY
@config plugins.ChatGPT.model MODEL_NAME
@config plugins.ChatGPT.reasoning_effort ""
```
`api_key` and `base_url` are global (one server per bot). `max_tokens` is sent as `max_completion_tokens` to OpenAI and as `max_tokens` to other servers.

## Replies and errors

By default the answer's lines are joined into a single reply; set `reply_intact` to `True` to keep its line breaks, one message per line.

Answers are sent in full: long lines are split into several messages that fit the IRC line limit (taking the bot's real `nick!ident@host`, the channel and any nick prefix into account) instead of being held back for `@more`, whatever `supybot.reply.mores.instant` says. `supybot.reply.mores.maximum` still caps the number of messages. Set `full_reply` to `False` for the normal `@more` behaviour.

When `chat` fails (API busy, rate limit or quota, timeout, bad API key or model, empty answer), the bot replies with a short error saying why. Commands run directly always get their error. Lines that MessageParser turns into a command (nick mentions) get one at most every `error_cooldown` seconds per channel (default 600, `0` for every error), so a busy API doesn't spam the channel. Set `error_reply` to `False` to turn errors off. Failures are always logged.

## Options

Options marked global apply to the whole bot; the others can be set globally, per network or per channel.

| Option | Default | Description |
|---|---|---|
| `enabled` | `True` | Answer `chat` at all. |
| `api_key` | (empty) | API key (required). Global. |
| `base_url` | `https://api.openai.com/v1/` | API server, for OpenAI-compatible providers. Global. |
| `model` | `gpt-6-luna` | Model to use. |
| `reasoning_effort` | `none` | `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, or empty to not send it. |
| `prompt` | "You are $botnick the IRC bot. Be brief, helpful" | System prompt; `$botnick` is replaced by the bot's nick. |
| `max_tokens` | `200` | Maximum tokens per answer, reasoning included. |
| `max_history` | `10` | Messages of conversation history kept per channel (or per nick in private). `0` disables history. |
| `temperature` | `1` | Sampling temperature, 0 to 2. Only sent when changed. |
| `top_p` | `1` | Nucleus sampling. Only sent when changed. |
| `presence_penalty` | `0` | -2.0 to 2.0. Only sent when changed. |
| `frequency_penalty` | `0` | -2.0 to 2.0. Only sent when changed. |
| `nick_include` | `True` | Send the user's nick with each message, so the model can tell people apart. |
| `nick_prefix` | `False` | Prefix replies with the user's nick. |
| `nick_strip` | `True` | Remove `botnick: ` from the start of answers. |
| `reply_intact` | `False` | Keep the answer's line breaks instead of joining them into one reply. |
| `full_reply` | `True` | Send the whole answer instead of holding the rest back for `@more`. |
| `error_reply` | `True` | Reply with a short error when a command fails. |
| `error_cooldown` | `600` | Seconds between errors for MessageParser triggers, per channel; `0` sends every error. |
| `timeout` | `60` | Seconds to wait for the API (one retry is made); `0` uses the SDK's 10 minutes. |
