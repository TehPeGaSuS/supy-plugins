# Pollinations Plugin for Limnoria
A Limnoria IRC bot plugin that integrates with [Pollinations.ai](https://pollinations.ai) for AI-powered text generation and image creation.

## Features
- **Text Generation**: Generate AI responses using chat context via the unified gen.pollinations.ai API
- **Image Generation**: Create images from text prompts
- **Auto-Reply**: Automatically respond to trigger words in channel
- **Context Awareness**: Uses recent channel conversation for better responses
- **Resilience & Retry**: Automatic retries on 429/5xx, fallback models, queue-throttling notices
- **Highly Configurable**: Multiple settings for customization
- **URL Shortening**: Optional shortened URLs for generated images and search sources
- **Live Web Search**: `search` answers from the web through a chain of backends (paid Pollinations search model such as Perplexity Sonar, Tavily, your own SearXNG) with per-backend daily limits, automatic fallback and usage commands (see [Web Search](#web-search))

## Installation
1. Download the plugin files to your Limnoria plugins directory
2. Load the plugin: `/msg yourbot load Pollinations`
3. Obtain an API key from [enter.pollinations.ai/keys](https://enter.pollinations.ai/keys) and configure it (required for text generation — anonymous requests return 401)
4. Configure other plugin settings as needed

## Commands
### Text Generation
`chat <prompt>`

Generate AI text responses. The bot can use recent channel conversation as context.  
**Examples:**
`chat Explain quantum physics simply`
`chat What do you think about the previous discussion?`

### Image Generation
`image <prompt>`

Generate images from text descriptions.  
**Examples:**
`image beautiful sunset over mountains`
`image cute cat playing with yarn`
`image cyberpunk city at night`
`image realistic portrait of a medieval knight`

### Live Web Search
`search <query>`

Answers a question from the live web in a few sentences (up to about 1000 characters, i.e. two or three IRC lines), e.g. `[P] Marco Bezzecchi won the Indonesian GP on 11 October 2026; Fernández was second.` Everything about it (backends, limits, costs, settings, SearXNG setup) is in [Web Search](#web-search).  
**Examples:**
`search latest stable Linux kernel version`
`search who won the last MotoGP race`
`search current time in Paris`

### Search Usage
`searchusage` (owner only)

Today's searches and each limited backend's count against its daily limit, plus Tavily credits: `Today: 25 searches, Pollinations 20/20, Tavily 5/30 | Tavily this month (bot): 47 credits in 47 searches | Tavily account: 45/1000 credits used (955 left, plan Researcher; may lag)`. See [Usage commands](#usage-commands).

### Pollen Usage
`polliusage` (owner only)

The pollen balance and what the bot's key spent in the last 24 hours: `Pollen: 11.0713 left (Quest 3.6472, paid 7.4241) | Last 24h (this key): 12 requests, $0.0450 (sonar 10, openai-fast 2)`. See [Usage commands](#usage-commands).

### List Available Models
`models [text|image|search] [low|med|high]`

`models search` lists the models that support web search (queried live via `capabilities=web_search`).

Lists available API models organized by price categories (automatically fetched in real-time).  
**Examples:**
`models`
`models text low`
`models image med`

## Configuration
All settings can be configured per-channel using:
```
/msg yourbot config channel #yourchannel plugins.Pollinations.<setting> <value>
```

### Text Generation Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `api_token` | "" | **Required** — API key from [enter.pollinations.ai/keys](https://enter.pollinations.ai/keys). Sent as `Authorization: Bearer <key>`. Stored privately. |
| `prompt` | "You are $botnick the IRC bot. Be brief, helpful" | System prompt for the AI ($botnick = bot's nickname) |
| `text_model` | "openai" | Primary text model for chat completions (see [Recommended models](#recommended-models)) |
| `text_fallback_model` | "openai-fast" | Space-separated list of fallback models tried when the primary fails persistently (429/5xx) |
| `text_timeout` | 30 | Timeout in seconds for text generation requests |
| `context_lines` | 25 | Number of recent channel lines (from ChannelLogger) to include as context; 0 disables |
| `nick_include` | True | Include user's nickname in the prompt |
| `nick_strip` | True | Remove bot's nickname from responses |
| `nick_prefix` | False | Prefix responses with user's nickname |
| `reply_intact` | False | Send multi-line responses as separate messages |

### Auto-Reply Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `auto_reply` | False | Enable automatic replies to trigger words |
| `trigger_words` | [] | List of words that trigger auto-reply (space-separated). Use underscores for multi-word phrases and `*` wildcards for flexible matching. |
| `trigger_probability` | 1.0 | Probability (0.0-1.0) of responding to trigger words |
| `min_reply_interval` | 6 | Minimum seconds between automatic replies in a channel |

#### Trigger Words Wildcard Logic
- `good_morning`  
  Matches **only** when the message is exactly "good morning"
- `good_morning*`  
  Matches messages **starting** with "good morning", e.g., "good morning all"
- `*good_morning*`  
  Matches messages containing "good morning" anywhere, e.g., "hello good morning everyone"
- `*$botnick*`  
  Matches messages containing the bot nickname anywhere

### Image Generation Settings
| Setting | Default | Description |
|---------|---------|-------------|
| `image_width` | 1024 | Image width in pixels |
| `image_height` | 1024 | Image height in pixels |
| `image_model` | "flux" | AI model to use for generation |
| `image_enhance` | True | Enable image enhancement |
| `image_nologo` | True | Remove Pollinations watermark |
| `image_private` | True | Make images private |
| `image_safe` | False | Enable safe content filtering |
| `negative_prompt` | "" | What to avoid in generated images |
| `shorten_urls` | False | Use is.gd to shorten image URLs (search sources have their own `search_shorten_urls`) |

## Web Search

`search <query>` answers a question from the live web. The bot finds the answer through one of several **backends**, tried in the order of `search_backend`, and replies in a single IRC line that starts with a tag saying which backend answered.

### Backends

| Backend | Tag | What it is | Cost | Needs |
|---|---|---|---|---|
| `pollinations` | `[P]` | A Pollinations search model (`search_model`, default `sonar` = Perplexity Sonar) that searches, reads the pages and writes the answer in one call | **Paid pollen only** (Quest Pollen cannot pay for search models). Measured: ~0.004 pollen per search with `sonar` | `api_token` |
| `tavily` | `[T]` | [Tavily](https://tavily.com) search API: returns page extracts and, optionally, its own short answer | Free plan: 1000 credits/month; 1 credit per `basic` search, 2 per `advanced` | `tavily_api_key` |
| `searxng` | `[S]` | Your own [SearXNG](https://docs.searxng.org) metasearch instance (Google, Brave, Bing, Mojeek, Wikipedia…) | Free, no quota; the answer is written by `search_text_model` (Quest Pollen, a tiny fraction of a pollen) | `searxng_url` |

A backend is **skipped** when it is not configured (empty key/URL), has reached its daily limit, fails (HTTP error, timeout, bad JSON) or returns nothing; the next backend in the list then answers. If every backend is skipped the bot replies `Daily search limit reached. It resets at 00:00 UTC.` (when a limit was the reason) or `Web search is unavailable right now, please try again later.`

### Recommended setups

**Free first, paid as backup** (the setup this plugin was tuned with, October 2026):
```
/msg yourbot config plugins.Pollinations.search_backend tavily pollinations searxng
/msg yourbot config plugins.Pollinations.tavily_rewrite True
/msg yourbot config plugins.Pollinations.tavily_depth basic
/msg yourbot config plugins.Pollinations.search_snippet_length 5000
/msg yourbot config plugins.Pollinations.search_text_model gpt-oss
/msg yourbot config plugins.Pollinations.search_text_fallback_model openai-fast
/msg yourbot config plugins.Pollinations.search_reasoning_effort low
/msg yourbot config plugins.Pollinations.search_model sonar
/msg yourbot config plugins.Pollinations.search_fallback_model ""
/msg yourbot config plugins.Pollinations.tavily_daily_limit 30
/msg yourbot config plugins.Pollinations.pollinations_daily_limit 15
/msg yourbot config channel #yourchannel supybot.reply.mores.instant 2
```
Tavily answers the first 30 searches of the day (one free credit plus ~0.0002 Quest pollen for gpt-oss each, about 5 s); Sonar takes the next 15 and any search Tavily fails or finds nothing for (~0.0041 paid pollen each); SearXNG answers the rest for free. What was tried and dropped: `tavily_depth advanced` (2 credits, slower, no better answers), `search_reasoning_effort medium` (14 s instead of 5 s for one extra fact), `search_snippet_length` 1000 (cut off details such as exact version numbers that 5000 kept, for about 0.00002 pollen more).

**Best answers, paid first, free after:**
```
/msg yourbot config plugins.Pollinations.search_backend pollinations tavily searxng
/msg yourbot config plugins.Pollinations.search_model sonar
/msg yourbot config plugins.Pollinations.search_fallback_model ""
/msg yourbot config plugins.Pollinations.pollinations_daily_limit 20
/msg yourbot config plugins.Pollinations.tavily_daily_limit 30
/msg yourbot config plugins.Pollinations.tavily_rewrite True
```
Sonar answers the first 20 searches of the day, Tavily the next 30, SearXNG the rest. If Sonar fails (outage, paid pollen used up) Tavily and then SearXNG answer instead, and the failed Sonar search is not counted. `search_fallback_model ""` makes a failing Sonar go straight to Tavily instead of first trying another paid model.

**Free only:**
```
/msg yourbot config plugins.Pollinations.search_backend tavily searxng
/msg yourbot config plugins.Pollinations.tavily_rewrite True
```

**Paid only:** `search_backend pollinations`. When the daily limit is reached, searches stop until 00:00 UTC.

### How the answer is written

| Backend | Who writes the answer | `search_prompt` | `search_text_model` | `tavily_rewrite` |
|---|---|---|---|---|
| `pollinations` | `search_model` itself (search + answer in one call) | used | not used | not used |
| `tavily`, rewrite off (default) | Tavily's own answer (`tavily_answer` basic/advanced), sent as is | **not used** (Tavily takes no instructions) | not used | — |
| `tavily`, rewrite on | `search_text_model`, from Tavily's page extracts | used | used | **only Tavily** |
| `searxng` | always `search_text_model`, from the result snippets | used | used | not needed |

Tavily's own answer cannot be steered: it is often long (500+ characters), may start with "According to the sources" and does not know the current time. With `tavily_rewrite True` every `[T]` answer goes through your `search_prompt` like the others, at the cost of one cheap `search_text_model` call per search. Recommended.

Every model call made by the plugin (`chat` included) gets the **current UTC date and time** appended to its system prompt, so "last", "latest", "today" and "now" are resolved against the real date. For `tavily`/`searxng` the results are also introduced to the model as possibly days-old page copies, with instructions to:
- work out live facts (the time in a city, today's date) from the real clock, never from a crawled clock page;
- give an answer the results point to (e.g. a "X wins" headline) rather than refusing; say briefly that it could not find it only when nothing answers the question;
- never mention "the results", "the sources" or "listed here", never write `[n]` numbers, never ask the user questions or offer to look things up.

### The search prompt

The default `search_prompt`:
```
IRC bot: reply in sentences, max 1000 chars, no lists/headings. Direct answer first, then useful detail (when/where/how/numbers). For last/latest/now, use today's date and name the event/date. If ambiguous, pick the likeliest meaning and say so; if unsure, say so. Use the question's language. No markdown, emoji, [n], URLs, sources or questions back.
```
It is 351 characters on purpose: `config plugins.Pollinations.search_prompt <text>` must fit in one IRC line (512 bytes including `PRIVMSG yourbot :` and your hostmask as the server relays it), so a prompt of about 360 characters is the practical maximum when set from IRC. A longer prompt can be set by editing the bot's `.conf` file:
1. Find `supybot.plugins.Pollinations.search_prompt: ...` (channel values are `supybot.plugins.Pollinations.search_prompt.#channel: ...`) and edit the text after `: `, keeping it on one line.
2. Right away run `/msg yourbot config reload`, or stop the bot before editing and start it after. The bot rewrites the `.conf` periodically and would otherwise overwrite your edit.

To restore the default: `/msg yourbot config setdefault plugins.Pollinations.search_prompt`.

Why it is worded this way (each part fixes something seen in testing):
- **`max 1000 chars, no lists/headings`**: with long Tavily extracts (`search_snippet_length 5000`) and no length rule, gpt-oss wrote a whole article with headings, bullet lists and numbered steps (five IRC chunks). With a strict one-line limit (300 characters) answers were complete but sometimes terse. 1000 characters is two or three IRC lines; set `supybot.reply.mores.instant` to 2 or 3 so they are sent at once. Models count characters loosely, so expect roughly 600–1200.
- **`reply in sentences`, `then useful detail (when/where/how/numbers)`**: without these, small models answer like a database label (`Last MotoGP season champion: Marc Márquez – 2025 season.`).
- **`For last/latest/now, use today's date and name the event/date`**: the plugin gives every model the current UTC date and time; this makes it use them and say which race, release or day the answer is about.
- **`If ambiguous… if unsure, say so`**: "the last MotoGP" can mean the last race or the last season; an honest "unclear" beats a confident wrong answer.
- **`No … [n], URLs, sources or questions back`**: Sonar appends `[3][15]` citations and models like to offer "want me to look that up?". The plugin also strips citations itself, see [Answer formatting](#answer-formatting).
- An earlier default (`answer in one plain-text line, max 300 chars…`) is a good choice if you want strictly one line per answer.

`search_use_prompt True` puts the main `prompt` (bot personality) before `search_prompt`.

### Daily limits, cooldown and the stats file

- `pollinations_daily_limit` (default 20) and `tavily_daily_limit` (default 30) are **separate** limits, counted per UTC day across all channels. SearXNG has no limit. `0` disables a limit.
- A search counts against a backend's limit only when that backend was used: a Tavily request counts when Tavily returns HTTP 200; a Pollinations search counts unless it failed and another backend followed (then it is given back). A search where every backend failed is not counted in `searches` either.
- `search_cooldown` (default 30 s, per channel) is how long one user (by full hostmask) waits between searches. It applies to every search, whatever the backend.
- Counts are saved in `<bot data dir>/Pollinations-search.json` and survive restarts and reloads. The file is one line of JSON:
  ```json
  {"day": "2026-10-21", "searches": 5, "pollinations_today": 3, "tavily_today": 2, "month": "2026-10", "tavily_credits": 47, "tavily_searches": 47}
  ```
  `searches`, `pollinations_today` and `tavily_today` reset at 00:00 UTC; `tavily_credits`/`tavily_searches` reset on the 1st of each month (UTC; Tavily's own reset date may differ). `day` and `month` must match the current UTC date, otherwise the counts are treated as stale and start from 0.
- The file can be edited by hand (e.g. to set the Tavily count from the dashboard): edit it, then `/msg yourbot reload Pollinations` right away (a search in between overwrites the edit). Counts written as strings (`"5"`) or floats are accepted; anything that is not a number is ignored with a warning in the log. Fields from older versions (such as `capped`) are ignored.

### Answer formatting

- **Tag**: every answer starts with `[P]`, `[T]` or `[S]`. Error, cooldown and limit messages have no tag. With `nick_prefix` on the nick comes first: `nick: [T] ...`.
- **Sources**: `[T]`/`[S]` answers end with ` | <url>` for the first `search_sources` results (default 1; `0` hides them). `[P]` answers have no URL. URLs are shortened with is.gd when `search_shorten_urls` is on (default); if is.gd fails the full URL is used.
- **Cleanup**: markdown links and citations (`([site](url))`, `[site.com](url)`), bare numbered citations (`[3]`, `[3][15]`, `[1, 2]`, `[4-6]`), trailing bare domains, `Sources:` lines, headings and code ticks are removed; `**bold**` becomes IRC bold and `*italic*` IRC italic. Other brackets (`[PG]`, `[x]`) stay.
- **Long answers** are split by Limnoria at word boundaries. `supybot.reply.mores.instant` (per channel, default 1) is how many chunks are sent at once before `(N more messages)`:
  ```
  /msg yourbot config channel #chan supybot.reply.mores.instant 3
  ```
  This applies to every command in that channel, not just `search`.
- `search_thinking` (default `Thinking...`) is sent before the search starts; empty disables it.

### Speed

Typical times measured on IRC: Sonar 5–6 s; SearXNG ~1.5 s plus the `search_text_model` call. `search_reasoning_effort` (default `low`) is sent as `reasoning_effort` with every search answer (`[P]`, rewritten `[T]`, `[S]`): with `openai-fast` it cut the model call from 8.8 s to 3.1 s. Values: `minimal`, `low`, `medium`, `high`; empty leaves it to the model. A model that rejects the field (HTTP 400) is asked once more without it (`Retrying model X without reasoning_effort` in the log). Reasoning models can also return an **empty** reply (all tokens spent thinking), which counts as a failure and moves on to the fallback model: `openai/gpt-oss-20b` did this in testing, so it makes a poor primary `search_text_model`.

The log shows where time goes:
```
SearXNG search (time_range=week): 5 results
Search searxng for 'who won the last MotoGP?': Marquez wins Japanese MotoGP… | MotoGP Race Results | Crash.net | …
Text attempt on model openai-fast took 3.1s (status=ok)
```
The `Search <backend> for ...` line lists the titles the model was given, so a wrong answer can be traced to wrong results or to the model.

### Models and costs

Prices change; check them with `models search` / `models text low` or `https://gen.pollinations.ai/text/models`. Per-request costs below are from the Pollinations dashboard's "Last events" (October 2026), which lists every request with its exact cost and whether it was paid from Quest or paid pollen:

| Use | Model | Measured cost | Notes |
|---|---|---|---|
| `search_model` | `sonar` (`perplexity/sonar`) | 0.004012–0.004119 paid pollen/search | Best answers in testing: read the pages, named the right race, date and podium |
| `search_model` | `gemini-search` (`google/gemini-2.5-flash-lite:search`) | 0.008087 paid pollen/search | Twice Sonar's cost despite 4× lower token prices (Google's search fee is not in the token price) and answered with a year-old result. It is the default `search_fallback_model`; set that to `""` if you would rather fall through to the next backend |
| `search_text_model` | `openai-fast` (`openai/gpt-5-nano`) | <0.0001–0.000239 Quest pollen/answer | Default. Fast with `search_reasoning_effort low` |
| `search_text_model` | `openai/gpt-oss-20b` | <0.0001 Quest pollen/answer | Cheapest per call, partly because it returned empty replies (still billed) |
| `search_text_model` | `nvidia/nemotron-3.5-lightning` | 0.000366–0.000752 Quest pollen/answer | Cheap per token but verbose: 3–7× gpt-5-nano per answer, and took 11 s |

A rough budget for Sonar: `paid pollen ÷ 0.0041 = searches`. For example 7.42 pollen ≈ 1,800 searches; at 15 a day that is about 4 months, at 20 a day about 3 months. Community models (`community/...`) are not recommended for search: prices are set by their authors, several are wrappers that call `sonar` underneath and bill your paid pollen anyway, and your prompts pass through a third-party server.

### Tavily notes

- Get a key at [tavily.com](https://tavily.com); set it globally (it is stored privately): `/msg yourbot config plugins.Pollinations.tavily_api_key tvly-...`. Never paste it in a channel.
- Each search sends `search_depth` = `tavily_depth` (`basic`, `fast`, `ultra-fast` cost 1 credit, `advanced` 2), `include_answer` = `tavily_answer` (`basic` short, `advanced` longer, same cost; `false` when `tavily_rewrite` is on), `max_results` = `search_results` and `include_usage: true`.
- `include_usage` makes Tavily report the credits each request used; the bot adds them to its monthly count (if a response has no `usage`, 2 is assumed for `advanced`, else 1). Tavily's own `/usage` endpoint and dashboard lag behind (minutes to hours), which is why `searchusage` shows both.
- When the plan's credits run out Tavily answers HTTP 432 (433 = pay-as-you-go limit) and the next backend answers. Pay-as-you-go ($0.008/credit after the free 1000) is off unless you enable it in the Tavily dashboard; with it off the bot can never spend money on Tavily.
- Tavily page extracts are long (several ~500-character chunks per page); `search_snippet_length` (default 1000) is how much of each result reaches `search_text_model`.

### SearXNG setup

Run SearXNG with Docker on the bot's machine, reachable only from localhost. `docker-compose.yml`:
```yaml
services:
  searxng:
    image: docker.io/searxng/searxng:latest
    container_name: searxng
    restart: unless-stopped
    ports:
      - "127.0.0.1:8888:8080"   # localhost only
    volumes:
      - ./searxng:/etc/searxng
```
`searxng/settings.yml`:
```yaml
use_default_settings:
  engines:
    remove:
      - duckduckgo        # CAPTCHAs on datacenter IPs
server:
  secret_key: "CHANGE_ME"  # openssl rand -hex 32
  limiter: false           # only the bot uses it
  image_proxy: false
search:
  default_lang: "en"       # optional: stops engines guessing the language from the server's location
  formats:
    - html
    - json                 # required: the plugin asks for format=json
```
Then:
```
sed -i "s/CHANGE_ME/$(openssl rand -hex 32)/" searxng/settings.yml
docker compose up -d
/msg yourbot config plugins.Pollinations.searxng_url http://127.0.0.1:8888
```
Check it and see which engines fail:
```
curl -s 'http://127.0.0.1:8888/search?q=test&format=json' | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["results"]), "results"); print(d["unresponsive_engines"])'
```
- `403 Forbidden` from `format=json` means the `json` format is not enabled.
- An engine that keeps appearing in `unresponsive_engines` (CAPTCHA, too many requests) can be added to `remove:`. Search engines throttle datacenter IPs; SearXNG suspends a failing engine for a while and keeps answering from the others. Low volume helps, which is why it is best as the last backend.
- `X-Forwarded-For nor X-Real-IP header is set!` in SearXNG's log is harmless with the limiter off and no reverse proxy.
- SearXNG only returns the engines' own snippets (150–200 characters); no setting makes them longer, so `search_snippet_length` mostly matters for Tavily.
- Questions with a word from `searxng_recent_words` (`last latest today yesterday tonight now current currently recent recently newest`) are searched with `time_range` = `searxng_recent_range` (default `week`) first; if that finds fewer than 3 results the search is repeated without it. Search engines do not know what "last" means: without this, "who won the last MotoGP" returned championship-history pages.
- Update: `docker compose pull && docker compose up -d`.

### Usage commands

`searchusage` (owner only):
```
Today: 25 searches, Pollinations 20/20, Tavily 5/30 | Tavily this month (bot): 47 credits in 47 searches | Tavily account: 45/1000 credits used (955 left, plan Researcher; may lag)
```
- `Today` counts every search that got past the cooldown, minus searches where every backend failed; the per-backend counts are listed for the limited backends in `search_backend`.
- `Tavily this month (bot)` is the bot's own live count (see above); it misses credits spent elsewhere with the same key (playground, other scripts).
- `Tavily account` comes from `GET https://api.tavily.com/usage` (`account.plan_usage`/`plan_limit`) and lags behind the dashboard.

`polliusage` (owner only):
```
Pollen: 11.0713 left (Quest 3.6472, paid 7.4241) | Last 24h (this key): 12 requests, $0.0450 (sonar 10, openai-fast 2)
```
- From `GET https://gen.pollinations.ai/account/balance`. The Quest/paid split needs the read-only `account:usage` permission on the key (enable it at [enter.pollinations.ai/keys](https://enter.pollinations.ai/keys)); without it a 403 is shown with that hint. A key with its own pollen budget shows that budget instead of the account total.
- `Last 24h` is from `GET /account/key/usage?days=1` (no extra permission): request count, cost (the API reports it in USD) and the top three models. `[T]` answers with `tavily_rewrite` off make no Pollinations request at all, so they do not appear here.

### Search settings

| Setting | Scope | Default | Description |
|---|---|---|---|
| `search_enabled` | channel | True | False disables `search` (per channel or globally) |
| `search_backend` | channel | "tavily searxng" | Backends tried in order: `pollinations`, `tavily`, `searxng`. A backend that is not configured, failed or reached its daily limit is skipped |
| `pollinations_daily_limit` | global | 20 | Searches per UTC day answered by `pollinations` (0 = no limit) |
| `tavily_daily_limit` | global | 30 | Tavily searches per UTC day (0 = no limit). 30 × 31 ≈ 930 fits the free 1000 credits/month |
| `search_cooldown` | channel | 30 | Seconds one user waits between searches (0 disables) |
| `search_model` | channel | "sonar" | Model for `pollinations`; must support web search (`models search`); paid pollen |
| `search_fallback_model` | channel | "gemini-search" | Space-separated fallbacks tried when `search_model` fails, before falling through to the next backend. `""` falls through directly |
| `search_prompt` | channel | see [The search prompt](#the-search-prompt) | Instructions for every search answer written by a model |
| `search_use_prompt` | channel | False | True puts the main `prompt` before `search_prompt` |
| `search_thinking` | channel | "Thinking..." | Line sent before searching; empty disables |
| `search_reasoning_effort` | channel | "low" | `reasoning_effort` for search answers (`minimal`/`low`/`medium`/`high`, empty = model default); retried without it on HTTP 400 |
| `search_text_model` | channel | "openai-fast" | Writes `[S]` answers and `[T]` answers with `tavily_rewrite` |
| `search_text_fallback_model` | channel | "gpt-oss" | Space-separated fallbacks for `search_text_model` |
| `search_results` | channel | 5 | Results asked from Tavily/SearXNG and given to the model |
| `search_snippet_length` | channel | 1000 | Max characters of each result given to `search_text_model` |
| `search_sources` | channel | 1 | Source URLs appended to `[T]`/`[S]` answers (0 = none) |
| `search_shorten_urls` | channel | True | Shorten source URLs with is.gd |
| `search_timeout` | channel | 15 | Seconds for each Tavily/SearXNG request (the model call uses `text_timeout`) |
| `tavily_api_key` | global, private | "" | Tavily key (`tvly-...`); empty skips `tavily` |
| `tavily_depth` | channel | "basic" | `basic`/`fast`/`ultra-fast` (1 credit) or `advanced` (2 credits) |
| `tavily_answer` | channel | "basic" | Length of Tavily's own answer: `basic` or `advanced`; same cost |
| `tavily_rewrite` | channel | False | True: ignore Tavily's answer and let `search_text_model` write one from the extracts (recommended) |
| `searxng_url` | global | "" | SearXNG base URL with `json` enabled, e.g. `http://127.0.0.1:8888`; empty skips `searxng` |
| `searxng_recent_range` | channel | "week" | `time_range` tried first for "last/latest/today…" questions (`day`/`week`/`month`/`year`; empty disables) |
| `searxng_recent_words` | channel | "last latest today yesterday tonight now current currently recent recently newest" | Words that trigger `searxng_recent_range` |

Channel settings set with `config channel #chan ...` override the global value: if search behaves differently in one channel, check `config channel #chan plugins.Pollinations.search_backend` (and the other settings) there.

### Search troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Web search is unavailable right now` | Every backend failed or is unconfigured. Check the log for `Tavily search error`, `SearXNG search error` or `All text models failed` |
| `Daily search limit reached` | Every limited backend is at its limit and no unlimited backend (SearXNG) answered. Resets at 00:00 UTC |
| `[S] I could not find …` | The snippets did not contain the answer; the `Search searxng for …` log line shows what the model saw. Tavily or Sonar read whole pages and do better on such questions |
| Stale times or dates ("the time in Paris is 23:13" from a crawled clock) | Search results are old page copies. Use `tavily_rewrite True` so the model, which gets the real time, writes the answer; Tavily's own answer cannot be corrected |
| `Tavily search error 432` | Monthly credits used up (433: pay-as-you-go limit). The next backend answers |
| `SearXNG search error 403` | `json` format not enabled in `settings.yml` |
| `Retrying model X without reasoning_effort` | The model does not accept `reasoning_effort`; harmless, or set `search_reasoning_effort ""` |
| `TypeError` after editing the stats file | Fixed: hand-edited counts are converted; if it still happens, delete `Pollinations-search.json` (counts restart at 0) |
| `searchusage` Tavily account shows fewer credits than the dashboard | Tavily's API lags; the `(bot)` count is live |
| `Search` is ambiguous on the bot (Config also has `search`) | Call it as `pollinations search …` or make an alias, e.g. `aka add q "pollinations search $1"` (Aka's last `$N` takes all remaining words) |


## Configuration Examples

### API Key Setup (Required)
Get your API key from [enter.pollinations.ai/keys](https://enter.pollinations.ai/keys), then configure it:
```
# Global configuration
/msg yourbot config plugins.Pollinations.api_token your_key_here

# Or per-channel
/msg yourbot config channel #mychannel plugins.Pollinations.api_token your_key_here
```
The key is stored privately (flagged `private=True` in the registry) and sent as `Authorization: Bearer <key>` on every text request. Anonymous requests (no key) return HTTP 401.

### Basic Setup
```
/msg yourbot config channel #mychannel plugins.Pollinations.prompt "You are a friendly bot assistant."
/msg yourbot config channel #mychannel plugins.Pollinations.context_lines 25
/msg yourbot config channel #mychannel plugins.Pollinations.text_model openai
```

### Fallback Models Setup
```
/msg yourbot config channel #mychannel plugins.Pollinations.text_fallback_model "nova-fast openai-fast"
```

### Auto-Reply Setup
Enable auto-reply:
```
/msg yourbot config channel #mychannel plugins.Pollinations.auto_reply True
```

Set trigger words (bot will respond when these words appear in messages):
```
/msg yourbot config channel #mychannel plugins.Pollinations.trigger_words $botnick bom_dia boa_noite
```

Set probability (50% chance to respond):
```
/msg yourbot config channel #mychannel plugins.Pollinations.trigger_probability 0.5
```

### Image Settings
```
/msg yourbot config channel #mychannel plugins.Pollinations.image_width 512
/msg yourbot config channel #mychannel plugins.Pollinations.image_height 512
/msg yourbot config channel #mychannel plugins.Pollinations.negative_prompt "blurry, low quality"
```

### Disable URL Shortening
```
/msg yourbot config channel #mychannel plugins.Pollinations.shorten_urls False
```

## How It Works

### Text Generation
1. Reads recent channel messages for context (configurable amount)
2. Constructs a chat conversation with system prompt + context + user input
3. Sends POST request to Pollinations.ai unified API with authentication
4. Parses JSON response and extracts AI-generated content
5. Returns formatted response to channel

### Auto-Reply Feature
1. Monitors all channel messages for configured trigger words
2. When a trigger word is detected, automatically calls the chat function
3. Uses the entire message as input (not just the trigger word)
4. Respects probability setting and minimum reply interval to avoid spam
5. Supports `$botnick` placeholder to use bot's actual nickname
6. Limits concurrent requests to prevent overload (semaphore of 5; pending queue capped at 10 per channel)

### Image Generation
1. Takes user prompt and combines with configured parameters
2. Generates image using Pollinations.ai image API
3. Optionally shortens the URL using is.gd
4. Returns image URL to channel

## Requirements
- Limnoria IRC bot
- Python 3.6+
- `requests` library
- Internet connection
- Pollinations.ai API key (get from [enter.pollinations.ai/keys](https://enter.pollinations.ai/keys))

## API Usage
This plugin uses the Pollinations.ai API:
- **Text API**: `https://gen.pollinations.ai/v1/chat/completions` (unified API)
- **Image API**: `https://image.pollinations.ai/prompt/`

**Authentication**: An API key is **required** for text generation — anonymous requests return HTTP 401. Obtain yours at [enter.pollinations.ai/keys](https://enter.pollinations.ai/keys). The key is sent as `Authorization: Bearer <key>`.

**Available Models** (non-exhaustive, run `models` command for live list):
- Text: `openai`, `openai-fast`, `openai-large`, `claude`, `claude-fast`, `claude-large`, `gemini`, `gemini-fast`, `mistral`, `grok`, `deepseek`, `qwen-coder`, `perplexity-fast`, `nova-micro`
- Image: `flux` (default), `turbo`

See [Recommended models](#recommended-models) for suggested primary/fallback combos.

## Troubleshooting

### Common Issues

**"API Error 401" or "UNAUTHORIZED"**
- An API key is now **required** for text generation — anonymous requests are no longer accepted
- Get a key from [enter.pollinations.ai/keys](https://enter.pollinations.ai/keys)
- Set it: `/msg yourbot config plugins.Pollinations.api_token your_key_here`

**"API Error 400" with model error**
- Invalid model name for the unified API, or a parameter the model does not accept
- List valid names with `models text low` (or the full list at `https://gen.pollinations.ai/text/models`)
- Set it: `/msg yourbot config plugins.Pollinations.text_model openai`

**"Please provide a prompt"**
- You need to include text after the command
- Example: `chat hello` not just `chat`

**"Generated blank image"**
- Try a more detailed prompt
- Check if the prompt might be filtered by safety settings

**Auto-reply not working**
- Ensure `auto_reply` is set to `True`
- Check that `trigger_words` is properly configured
- Verify `trigger_probability` is > 0.0
- Check that `min_reply_interval` hasn't been triggered recently
- Make sure the trigger word appears in the message

**Bot responds to its own messages**
- This shouldn't happen (built-in protection), but if it does, check logs

**Context not working**
- Ensure ChannelLogger plugin is enabled
- Check if log files exist and are readable

**Request timeout or ping timeout**
- Default text timeout is 30 seconds (`text_timeout`); image timeout is 60 seconds
- Reduce `context_lines` if context reading is slow
- Check `min_reply_interval` to reduce auto-reply frequency
- The plugin limits concurrent requests to prevent overload (semaphore 5, pending queue max 10)

### Debug Information

To see current configuration:
```
/msg yourbot config list plugins.Pollinations
```

To check if the plugin is loaded:
```
/msg yourbot list Pollinations
```

To reload the plugin after changes:
```
/msg yourbot reload Pollinations
```

## Performance & Stability

The plugin includes several safeguards to prevent IRC ping timeouts:
- **Request limiting**: Maximum 5 concurrent text generation requests (single semaphore acquire per request)
- **Pending queue**: When the semaphore is full, requests are queued (max 10 per channel). When the queue is also full, a throttled notice is sent (once per 30 seconds per channel) instead of silently dropping
- **Timeouts**: 30-second default for text, 60-second for image generation
- **Thread management**: Controlled shutdown of background threads
- **Rate limiting**: Minimum interval between auto-replies per channel
- **Retry resilience**: urllib3 `Retry(total=2, backoff_factor=0.5, status_forcelist=[429,500,502,503,504])` on every text request (POST retried); on exhaustion, the real HTTP status is reported. Persistent 429/5xx on the primary model triggers a fallback attempt using `text_fallback_model`

## Recommended Models

| Role | Suggested model(s) | Notes |
|------|---------------------|-------|
| `text_model` (primary) | `openai` | GPT-5.4 Nano — fast, reliable |
| `text_fallback_model` | `nova-fast openai-fast` | Tried in order when primary fails persistently |

- **Avoid reasoning models** (`inkling`, `gpt-oss`, `perplexity-reasoning`, etc.) as fallbacks — they are significantly slower and will increase response latency
- **Avoid alpha/community models** as primaries — they may be unstable or rate-limited; save them for experiments only
- The plugin auto-skips unknown/invalid model names using a cached `/text/models` lookup (10-min TTL). Look for `Skipping unknown text fallback model` in the logs

## Resilience & Troubleshooting Details

### Retry behavior
1. Each text request uses urllib3 `Retry` with `total=2`, exponential backoff (`backoff_factor=0.5`), and retries on status codes 429, 500, 502, 503, 504
2. POST requests are retried (`allowed_methods=None`)
3. After all retries are exhausted, the real HTTP status code is shown to the user
4. If the primary model returns a persistent 429/5xx, a **fallback attempt** is made using the first valid model from `text_fallback_model`
5. If every text model fails, the bot replies: `All text models failed. Last error: HTTP ...`

### Overloaded service
- When all retries are exhausted (RetryError), the bot replies with: *"The AI service is overloaded right now, please try again in a moment."* instead of a bare "Network error."

### Queue-full notice
- When the pending queue (max 10 per channel) is full, the bot sends a throttled notice (at most once every 30 seconds per channel) so users know their request was not silently dropped

### Per-attempt telemetry
Each text attempt is logged with:
```
Text attempt on model X took N.Ns (status=...)
```
Use this to identify slow or consistently-failing models and adjust your `text_model` / `text_fallback_model` accordingly.

## Contributing
Feel free to submit issues and pull requests on GitHub.

## License
MIT, see [LICENSE](LICENSE).

## Credits
- Uses [Pollinations.ai](https://pollinations.ai) API
- Built for [Limnoria](https://github.com/ProgVal/Limnoria) IRC bot
