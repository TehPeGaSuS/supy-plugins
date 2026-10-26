# OpenRouter (Limnoria)

A small Limnoria plugin that turns your IRC bot into a front‑end for any
**OpenAI‑compatible chat‑completion service** (OpenRouter, Groq, OpenAI, Gemini,
a local Ollama/llama.cpp server, etc.).

**This plugin requires Limnoria.**

Forked from Nelluk's [OpenRouter](https://github.com/Nelluk/Limnoria-Plugins/tree/main/OpenRouter)
work, itself based on oddluck's ChatGPT plugin. Many thanks to both: the
plugin is theirs, this copy only fixes what had stopped working and makes
it safe to run on free tiers.

## Changes from Nelluk's version

- **Works out of the box again.** The default model,
  `deepseek/deepseek-chat-v3-0324:free`, no longer exists on OpenRouter. The new
  default, `openrouter/free`, is OpenRouter's router over whatever free models
  exist at the time, so it does not go stale.
- **Web search no longer crashes.** `from supybot.commands import *` replaces
  Python's `any()` with Limnoria's `any` converter, so with current Limnoria the
  time‑sensitivity check behind `web_mode auto` raised `AssertionError`, and every
  chat failed under the old default.
- **Web search is off by default**, because OpenRouter charges for it even with
  free models. `off` now really means off: `--web` gets a clear error instead of
  being silently ignored. Use `optin` to let users ask for it per message.
- **Web search options are sent where OpenRouter reads them** (`engine`,
  `max_results` and `search_prompt` on the web plugin, not in
  `web_search_options`). The firecrawl, parallel and perplexity engines can be
  selected too.
- **Web search is refused on other endpoints.** It is an OpenRouter feature.
  `--web` or `web_mode always` with another `base_url` gives an error, and auto
  mode quietly skips it.
- **`web_show_sources` works.** The openai library returns annotations as
  objects, not dicts, so source URLs were never found.
- **Reasoning models no longer crash the command.** A reply with no content,
  for example when the model spent all of `max_tokens` thinking, now gives a
  message saying so instead of a `TypeError`. `max_tokens` defaults to 1000
  instead of 200, and the new `reasoning_effort` setting controls the thinking
  (sent as `reasoning.effort` to OpenRouter, `reasoning_effort` elsewhere).
- **The system prompt comes first**, before the history, as the API expects.
- **History counts exchanges consistently.** It stored `2 × max_history`
  messages but sent only `max_history` of them, and with an odd value the
  history sent could start with a bot reply. `max_history` is now the number of exchanges kept and sent
  (default 5, which sends the same 10 messages as before).
- **API errors are reported cleanly**: `Rate limited by the API (429): …` or
  `API error 404: …` instead of a generic error.
- **Only non‑default sampling values are sent** (`temperature`, `top_p`,
  penalties), so providers that do not support one never see it unless you set it.
- **Users' messages stay out of the normal log**: the full request payload is
  logged at DEBUG, and the INFO line only summarises the request.
- Tests (with a fake API client) for all of the above.

## Installation

1. Copy the `OpenRouter/` directory into your bot's plugins directory.
2. Install the OpenAI Python library into the bot's environment (needed even
   when not using OpenAI): `pip install openai`, or for a uv‑installed
   Limnoria, reinstall it with `--with openai`.
3. Load the plugin: `/msg yourbot load OpenRouter`
4. Get an API key from your provider (e.g. [openrouter.ai/keys](https://openrouter.ai/keys))
   and configure it.

## Configuration

```irc
# Required
@config plugins.OpenRouter.api_key   sk-or-your-key-here
@config plugins.OpenRouter.prompt    You are an IRC bot. Be concise, helpful, and accurate.

# Common tweaks
@config plugins.OpenRouter.model          openrouter/free   # default model
@config plugins.OpenRouter.temperature    0.7               # sampling temperature
@config plugins.OpenRouter.max_history    5                 # exchanges kept in memory
@config plugins.OpenRouter.max_tokens     1000              # reply budget, includes reasoning
@config plugins.OpenRouter.reasoning_effort low             # empty = model default
```

Run `@config list plugins.OpenRouter` to see all options.

### Other providers

`base_url` can point at any OpenAI‑compatible API, e.g. Gemini:
`https://generativelanguage.googleapis.com/v1beta/openai/`. Web search only
works with OpenRouter.

### Groq (free tier)

[Groq](https://console.groq.com) has a free tier with no credit card. Get a key
at [console.groq.com/keys](https://console.groq.com/keys), then:

```irc
@config plugins.OpenRouter.base_url https://api.groq.com/openai/v1
@config plugins.OpenRouter.api_key  gsk_your_groq_key
@config plugins.OpenRouter.model    openai/gpt-oss-120b
@config plugins.OpenRouter.reasoning_effort low
@config plugins.OpenRouter.max_history 3
@config plugins.OpenRouter.max_tokens 400
```

The free chat models in October 2026 were `openai/gpt-oss-120b`,
`openai/gpt-oss-20b` and `qwen/qwen3.8-27b`, all with the same limits: 30
requests per minute, 1K requests per day, 8K tokens per minute and 200K tokens
per day. Your account's current limits are at
[console.groq.com/settings/limits](https://console.groq.com/settings/limits).

Tokens run out long before requests do. Every call counts the system prompt,
the history and the reply, and gpt-oss also counts its hidden reasoning, so:

- `reasoning_effort low` saves the most tokens.
- `max_history 3` keeps the history short.
- `max_tokens 400` stops long replies, with room left for the reasoning.

That is roughly 500 to 1000 tokens per call. When a limit is hit, the bot
answers `Rate limited by the API (429): …`. The per-minute limit recovers
within a minute, the daily one the next day.

To use Groq through OpenRouter instead, so web search still works, add your
Groq key under Settings → Integrations on OpenRouter, in the Prioritized
section, with *Shared capacity fallback* set to "Never use shared capacity
for any model on this provider" (otherwise OpenRouter falls back to its own,
paid, capacity when your Groq limits are reached). Keep `base_url` on
OpenRouter and use a model Groq serves. OpenRouter charges a 5% fee on
requests made with your own keys, within a monthly free allowance that
depends on your OpenRouter plan.

## Command

```irc
@openrouter chat [--model <name>] [--temperature <f>] [--top_p <f>]
                 [--max_completion_tokens <n>] [--max_tokens <n>]
                 [--presence_penalty <f>] [--frequency_penalty <f>]
                 [--web | --no-web] -- <prompt>
```

* Flags override the channel‑level defaults for this single call.
* Use `--` to mark where flags end and your prompt begins.
* Token limit precedence (only one is sent):
  1) CLI `--max_completion_tokens` > 2) CLI `--max_tokens` >
  3) channel `max_completion_tokens` (> 0) > 4) channel `max_tokens`.

### Example

```irc
@openrouter chat --model google/gemma-4-31b-it:free --temp 0.3 -- Summarise today in haiku
```

## Web search

OpenRouter charges for web search on every model, free ones included (from
about $0.001 per request with the parallel engine to $0.007 with exa), so it
is off by default.

```irc
#   web_mode: off | optin | auto | always
#     off    – never (default); --web gives an error
#     optin  – only when a message uses --web
#     auto   – when the prompt looks time-sensitive ("latest", "today",
#              "price", "weather", a YYYY-MM-DD date, ...) or uses --web
#     always – every message, unless it uses --no-web
#   web_engine: auto | native | exa | firecrawl | parallel | perplexity
#   web_search_context_size: low | medium | high   (native search only)
@config plugins.OpenRouter.web_mode optin
@config plugins.OpenRouter.web_engine parallel
@config plugins.OpenRouter.web_max_results 5
@config plugins.OpenRouter.web_search_prompt "Use web results to answer. Be concise (2-3 sentences). Do not include citations or URLs unless explicitly asked."
@config plugins.OpenRouter.web_show_sources False
```

```irc
@openrouter chat --web -- What's the latest Nvidia driver?
@openrouter chat --no-web -- Explain recursion
```

With `web_show_sources True`, replies end with a `Sources:` line. Otherwise
URLs and citation links are stripped from the reply and the sources are only
logged.

The current date is always added to the system prompt to reduce stale‑date
answers.

## Conversation history

```irc
#   channel         – one shared thread per channel
#   channel+model   – separate thread per model (default)
#   channel+alias   – separate thread per command alias
@config plugins.OpenRouter.contextScope channel+model
```

History is kept in memory only, so it is cleared when the plugin is reloaded.

## Handy aliases

Create shortcuts so users don't have to remember long model names:

```irc
@alias add gemma "openrouter chat --model google/gemma-4-31b-it:free -- $*"
```

If you define several aliases, set `contextScope` to `channel+model` or
`channel+alias` so each keeps its own history.

## Model restrictions (blacklist)

Admins can block specific models globally. By default, `openai/o1-pro` is
blocked. Any attempt to chat with a blacklisted model returns an error and the
request is not sent to the API.

```irc
@config get plugins.OpenRouter.models_blacklist
@config set plugins.OpenRouter.models_blacklist "openai/o1-pro another/model-id"
```

## Running the tests

```bash
supybot-test ./OpenRouter
```

The tests replace the API client with a fake one, so no key or network is needed.
