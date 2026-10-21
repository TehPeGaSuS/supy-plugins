# Pollinations Plugin for Limnoria
A Limnoria IRC bot plugin that integrates with [Pollinations.ai](https://pollinations.ai) for AI-powered text generation and image creation.

## Features
- **Text Generation**: Generate AI responses using chat context via the unified gen.pollinations.ai API
- **Image Generation**: Create images from text prompts
- **Auto-Reply**: Automatically respond to trigger words in channel
- **Context Awareness**: Uses recent channel conversation for better responses
- **Resilience & Retry**: Automatic retries on 429/5xx, fallback models, queue-throttling notices
- **Highly Configurable**: Multiple settings for customization
- **URL Shortening**: Optional shortened URLs for generated images

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

Answers using live web search. Backends are tried in the order of `search_backend`:
- `tavily`: [Tavily](https://tavily.com) search (free plan: 1000 credits/month, 1 per basic search). Replies with Tavily's own short answer, or with `tavily_rewrite` on, `search_text_model` writes it from the results.
- `searxng`: your own [SearXNG](https://docs.searxng.org) instance (free, no quota); `search_text_model` writes the answer from the results.
- `pollinations`: a paid Pollinations search model (`search_model`, falling back to `search_fallback_model`). It replies itself, so put it last.

Answers start with the backend that answered: `[T]` Tavily, `[S]` SearXNG, `[P]` Pollinations. Answers from tavily/searxng end with `search_sources` source URLs. Tavily and Pollinations searches are capped per UTC day (`search_daily_limit`); after that SearXNG answers alone, uncapped since it is free. Each user also waits `search_cooldown` between searches. The counts are saved in `data/Pollinations-search.json`, so they survive restarts.

Long answers are split by Limnoria itself: `supybot.reply.mores.instant` (per channel, default 1) is how many chunks are sent at once before `(N more messages)`, e.g. `config channel #chan supybot.reply.mores.instant 3`.  
**Examples:**
`search latest stable Linux kernel version`
`search who won the match last night`

### Search Usage
`searchusage` (owner only)

Shows today's search count and, with a Tavily key, the Tavily credits the bot spent this month (counted from each response's `usage`, saved on disk, reset on the 1st UTC) and the account usage from `https://api.tavily.com/usage`. Tavily's own count lags behind, so the bot's count is the live one; it misses credits spent elsewhere with the same key (playground, other scripts).

### Pollen Usage
`polliusage` (owner only)

Shows the pollen left (`GET /account/balance`; the Quest/paid split needs the `account:usage` permission on the key, otherwise only a budgeted key's balance is shown) and what this key spent in the last 24 hours, with the top models (`GET /account/key/usage`, no extra permission). Costs are as the API reports them, in USD.

### List Available Models
`models [text|image|search] [low|med|high]`

`models search` lists the models that support web search (queried live via `capabilities=web_search`).

Lists available API models organized by price categories (automatically fetched in real-time).  
**Examples:**
`models`
`models text low`
`models image med`
```

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
| `search_enabled` | True | Set to False to disable `search` (per channel or globally) |
| `search_backend` | "tavily searxng" | Backends tried in order: `tavily`, `searxng`, `pollinations` (paid, last) |
| `tavily_api_key` | "" | Tavily API key (global, private). Empty skips `tavily` |
| `tavily_depth` | "basic" | `basic`, `fast`, `ultra-fast` (1 credit) or `advanced` (2 credits) |
| `tavily_answer` | "basic" | Tavily's own answer: `basic` (short) or `advanced` (longer); same credit cost |
| `tavily_rewrite` | False | If True, ignore Tavily's answer and let `search_text_model` write one from the results |
| `searxng_url` | "" | SearXNG base URL with the json format enabled, e.g. `http://127.0.0.1:8888` (global). Empty skips `searxng` |
| `searxng_recent_range` | "week" | For questions with a `searxng_recent_words` word, SearXNG is asked for pages from this period first (`day`/`week`/`month`/`year`); fewer than 3 results → searched again without it. Empty disables |
| `searxng_recent_words` | "last latest today yesterday tonight now current currently recent recently newest" | Words that trigger `searxng_recent_range` |
| `search_text_model` | "openai-fast" | Model that writes answers from tavily/searxng results |
| `search_text_fallback_model` | "gpt-oss" | Space-separated fallbacks for `search_text_model` |
| `search_results` | 5 | Results asked from the backend |
| `search_snippet_length` | 1000 | Max characters of each result's text given to `search_text_model` (Tavily extracts are long; SearXNG snippets are short) |
| `search_sources` | 1 | Source URLs appended to the answer (0 for none) |
| `search_shorten_urls` | True | Shorten source URLs with is.gd |
| `search_timeout` | 15 | Timeout in seconds for tavily/searxng requests |
| `search_daily_limit` | 30 | Tavily + Pollinations searches per UTC day across all channels (global, 0 for no limit); SearXNG is not counted. 30 fits Tavily's free plan |
| `search_cooldown` | 30 | Seconds between searches per user (0 to disable) |
| `search_model` | "sonar" | Model for the `pollinations` backend (must support web search, see `models search`; paid) |
| `search_prompt` | "You are answering on IRC. Use live web search… plain text only, no sources/URLs/markdown…" | Instructions for `search` only (e.g. no citations/markdown) |
| `search_use_prompt` | False | If True, `search` also uses the main `prompt` (personality) before `search_prompt`; if False only `search_prompt` is used |
| `search_thinking` | "Thinking..." | Line sent before a `search` answer; empty disables |
| `search_fallback_model` | "gemini-search" | Space-separated fallbacks for `search` |
| `text_timeout` | 30 | Timeout in seconds for text generation requests |
| `context_lines` | 50 | Number of recent messages to include as context |
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
| `shorten_urls` | True | Use is.gd to shorten image URLs |

## Configuration Examples

### API Key Setup (Required)
Get your API key from [enter.pollinations.ai/keys](https://enter.pollinations.ai/keys), then configure it:
```
# Global configuration
/msg yourbot config supybot.Pollinations.api_token your_key_here

# Or per-channel
/msg yourbot config channel #mychannel supybot.Pollinations.api_token your_key_here
```
The key is stored privately (flagged `private=True` in the registry) and sent as `Authorization: Bearer <key>` on every text request. Anonymous requests (no key) return HTTP 401.

### Basic Setup
```
/msg yourbot config channel #mychannel plugins.Pollinations.prompt "You are a friendly bot assistant."
/msg yourbot config channel #mychannel plugins.Pollinations.context_lines 25
/msg yourbot config channel #mychannel supybot.Pollinations.text_model openai
```

### Fallback Models Setup
```
/msg yourbot config channel #mychannel supybot.Pollinations.text_fallback_model "nova-fast openai-fast"
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
- Set it: `/msg yourbot config supybot.Pollinations.api_token your_key_here`

**"API Error 400" with model error**
- Invalid model name for the unified API
- Use: `openai`, `claude`, `mistral`, or `llama`
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
This plugin is released under the same license as Limnoria.

## Credits
- Uses [Pollinations.ai](https://pollinations.ai) API
- Built for [Limnoria](https://github.com/ProgVal/Limnoria) IRC bot
