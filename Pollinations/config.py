from supybot import conf, registry
import requests

try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization("Pollinations")
except:
    # Placeholder that allows to run the plugin on a bot
    # without the i18n module
    _ = lambda x: x

def configure(advanced):
    # This will be called by supybot to configure this module. advanced is
    # a bool that specifies whether the user identified themself as an advanced
    # user or not. You should effect your configuration by manipulating the
    # registry as appropriate.
    from supybot.questions import expect, anything, something, yn
    conf.registerPlugin("Pollinations", True)

def fetch_api_models(endpoint, fallback_text):
    """Tenta obter a lista de modelos da API no momento em que o config é carregado."""
    try:
        # Timeout muito curto para não bloquear o arranque do bot
        response = requests.get(f"https://gen.pollinations.ai/{endpoint}", timeout=2)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                if len(data) > 0 and isinstance(data[0], dict):
                    models = [m.get("name", m.get("id", str(m))) for m in data]
                else:
                    models = [str(m) for m in data]

                models = [m for m in models if m]
                if models:
                    return "" + ", ".join(models)
    except Exception:
        pass
    return fallback_text
    
Pollinations = conf.registerPlugin("Pollinations")

conf.registerChannelValue(
    Pollinations,
    "prompt",
    registry.String(
        "You are $botnick the IRC bot. Be brief, helpful",
        _(
            """
            The prompt defining your bot's personality.
            """
        ),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "api_token",
    registry.String(
        "",  
        _("""Pollinations.ai API token (Authorization: Bearer). Leave empty for anonymous access."""),
        private=True,
    ),
)

conf.registerChannelValue(
    Pollinations,
    "reply_intact",
    registry.Boolean(
        False,
        _(
            """
            Get spammy and enable line per line reply...
            """
        ),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "nick_prefix",
    registry.Boolean(
        False,
        _(
            """
            Prefix nick on replies true/false...
            """
        ),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "nick_include",
    registry.Boolean(
        True,
        _(
            """
            Include user nicks in queries.
            """
        ),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "nick_strip",
    registry.Boolean(
        True,
        _(
            """
            Prevent the bot from starting replies with its own nick.
            """
        ),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "text_model",
    registry.String(
        "openai",
        fetch_api_models("text/models", _("""Text models: openai, openai-fast, openai-large, claude, claude-fast, claude-large, gemini, gemini-fast, gemini-large, gemini-search, mistral, grok, deepseek, qwen-coder, perplexity-fast, perplexity-reasoning, midijourney, chickytutor, kimi-k2-thinking, nova-micro""")),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "text_fallback_model",
    registry.String(
        "openai-fast",
        _("""Space-separated fallback models if the primary text_model fails (e.g. 'openai-fast')"""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "search_model",
    registry.String(
        "gemini-search",
        _("""Model used by the 'search' command for live web search. Must support web_search (see 'models search'); requires an API token."""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "search_prompt",
    registry.String(
        "You are answering on IRC. Use live web search to get current facts, then reply with plain text only: one or two short sentences. Do NOT mention or list websites, domain names, URLs, sources, citations, references or links, and do not write 'according to' or 'source:'. Do not use markdown, bullet points, bold or emoji. Output only the answer itself.",
        _("""Instructions for the 'search' command only. Used on its own, or appended to the main prompt if search_use_prompt is on."""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "search_use_prompt",
    registry.Boolean(
        False,
        _("""If on, 'search' also uses the main prompt (bot personality) before search_prompt. If off, only search_prompt is used."""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "search_thinking",
    registry.String(
        "Thinking...",
        _("""Line sent to the channel before a 'search' answer. Empty to disable."""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "search_fallback_model",
    registry.String(
        "perplexity",
        _("""Space-separated fallback models for the 'search' command if search_model fails"""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "context_lines",
    registry.Integer(
        25,
        _("""Number of recent chat lines to use as context (0 to disable)"""),
    ),
)

# Image generation parameters
conf.registerChannelValue(
    Pollinations,
    "image_width",
    registry.Integer(
        1024,
        _("""Image width in pixels"""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "image_height", 
    registry.Integer(
        1024,
        _("""Image height in pixels"""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "image_model",
    registry.String(
        "flux",
        fetch_api_models("image/models", _("""Image models: flux (default), turbo, zimage, gptimage, gptimage-large, seedream, seedream-pro, kontext, nanobanana, nanobanana-pro""")),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "image_enhance",
    registry.Boolean(
        False,
        _("""Enhance image quality (slower, makes an extra LLM call to improve the prompt)"""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "image_nologo",
    registry.Boolean(
        False,
        _("""Remove watermark/logo (requires an API token, ignored for anonymous access)"""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "image_private",
    registry.Boolean(
        False,
        _("""Private generation (requires an API token, ignored for anonymous access)"""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "image_timeout",
    registry.Integer(
        60,
        _("""Timeout (s) for image generation requests. Image gen can take 30-60s."""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "image_fallback_model",
    registry.String(
        "flux",
        _("""Fallback model if the configured image_model fails (use a model that works anonymously, e.g. flux)"""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "image_safe",
    registry.Boolean(
        False,
        _("""Apply safety filters"""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "negative_prompt",
    registry.String(
        "",
        _("""Negative prompt (what to avoid in image)"""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "shorten_urls",
    registry.Boolean(
        False,
        _("""Shorten image URLs using is.gd (disabled by default because is.gd is often unreliable)"""),
    ),
)

# Auto-reply configuration
conf.registerChannelValue(
    Pollinations,
    "auto_reply",
    registry.Boolean(
        False,
        _("""Enable automatic replies to trigger words"""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "trigger_words",
    registry.SpaceSeparatedListOfStrings(
        [],
        _("""Space-separated list of words that trigger auto-reply"""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "trigger_probability",
    registry.Float(
        1.0,
        _("""Probability (0.0-1.0) of responding to trigger words"""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "text_timeout",
    registry.Integer(
        30,
        _("""Timeout (s) for text generation requests"""),
    ),
)

conf.registerChannelValue(
    Pollinations,
    "min_reply_interval",
    registry.Integer(
        6,
        _("""Minimum seconds between automatic replies in a channel"""),
    ),
)

# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
