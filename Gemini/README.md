GoogleAI Gemini Chat Plugin

This plugin is under development and probably shouldn't be used by anyone...

Requires the `google-genai` SDK (the old `google-generativeai` package is no longer supported):
```
pip install -r requirements.txt
```

Get an API key from https://aistudio.google.com/app/apikey
```
@config plugins.gemini.api_key YOUR_KEY_HERE
```

system prompt:
```
@config plugins.gemini.prompt "You are $botnick the IRC bot. Be brief, helpful"
```
^^ Configurable per channel, etc. get creative

```
@config list plugins.gemini
```

The default model is `gemini-3.8-flash` with `thinking_level` set to `minimal`. Thinking tokens count towards `max_tokens`, so raise `max_tokens` if you raise `thinking_level`. For Gemini 2.5 or older models, clear it:
```
@config plugins.gemini.thinking_level ""
```

Answers are sent in full by default: long lines are split into several messages instead of being held back for `@more`, whatever `supybot.reply.mores.instant` says. `supybot.reply.mores.maximum` still caps the number of messages. To use the normal `@more` behaviour instead:
```
@config plugins.gemini.full_reply False
```
^^ Please take a look at the various options and configure stuff before you do anything.

```
@chat <text>
```
^^ Command to send text to the Gemini API

```
@messageparser add "(?i)(.*BOT_NICK_HERE.*)" "chat $1"
```
^^ replace BOT_NICK_HERE with your bot nick and add automatic replies to nick mentions
