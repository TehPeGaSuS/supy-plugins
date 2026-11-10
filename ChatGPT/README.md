Use the OpenAI ChatGPT API

This plugin is under development and probably shouldn't be used by anyone...

Requires the `openai` SDK (1.58 or newer):
```
pip install -r requirements.txt
```

Get an API key from https://platform.openai.com/account/api-keys
```
@config plugins.chatgpt.api_key YOUR_KEY_HERE
```

Model:
```
@config plugins.chatgpt.model gpt-6-luna
```
^^ Use this config to set the language model. Default: gpt-6-luna (gpt-4o-mini shuts down on 2027-01-14, gpt-5-nano on 2026-12-11).

Reasoning:
```
@config plugins.chatgpt.reasoning_effort none
```
^^ Reasoning tokens count towards `max_tokens`, so keep this low for chat. gpt-6-luna takes none/low/medium/high/xhigh/max, older GPT-5 models take `minimal` instead of `none`. Set it to `""` for models or servers without reasoning.

Other servers:
```
@config plugins.chatgpt.base_url https://api.groq.com/openai/v1
@config plugins.chatgpt.reasoning_effort ""
```
^^ Any OpenAI-compatible API works. `max_tokens` is sent as `max_completion_tokens` to OpenAI and as `max_tokens` elsewhere; temperature, top_p and the penalties are only sent when changed from their defaults.

History:
```
@config plugins.chatgpt.max_history 10
```
^^ Use this config to set maximum number of messages to keep in your history. 0 to disable.

System Prompt:
```
@config plugins.chatgpt.prompt "You are $botnick the IRC bot. Be brief, helpful"
```
^^ Configurable per channel, etc. get creative

```
@config list plugins.chatgpt
```
^^ Please take a look at the various options and configure stuff before you do anything.

```
@chat <text>
```
^^ Command to send text to the chatgpt API

```
@messageparser add "(?i)(.*BOT_NICK_HERE.*)" "chat $1"
```
^^ replace BOT_NICK_HERE with your bot nick and add automatic replies to nick mentions.
```
@config reply.whenaddressedby.nick False
```
^^ You might want to set the above to false if using messageparser to reply on nick mentions.

Long answers are sent in full (`full_reply`), split to fit the IRC line limit instead of being held back for `@more`. Lines are joined into one reply unless `reply_intact` is on. When `chat` fails (busy, rate limit, timeout, bad key or model), the bot says why, but only when someone runs the command directly; MessageParser nick mentions stay silent (`error_reply`). Requests time out after `timeout` seconds (default 60).
