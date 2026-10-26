###
# Copyright (c) 2025 Nelluk
# Copyright (c) 2026, PeGaSuS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
###

from supybot import utils, plugins, ircutils, callbacks
from supybot.commands import *  # getopts, rest, somethingWithoutSpaces, etc.
from supybot.i18n import PluginInternationalization
import builtins
import re
from collections import defaultdict
from datetime import date
from openai import OpenAI, APIError, APIStatusError
import json

_ = PluginInternationalization("OpenRouter")

# Sampling parameters and the value every OpenAI-compatible API assumes when
# they are left out. Only values that differ are sent, so providers that do
# not support a parameter never see it unless it was actually configured.
_SAMPLING_DEFAULTS = {
    "temperature": 1.0,
    "top_p": 1.0,
    "presence_penalty": 0.0,
    "frequency_penalty": 0.0,
}

# Search engines accepted by OpenRouter's web plugin. Anything else (including
# "auto") leaves the choice to OpenRouter.
_WEB_ENGINES = ("native", "exa", "firecrawl", "parallel", "perplexity")


class OpenRouter(callbacks.Plugin):
    """Use an OpenAI‑compatible Chat Completion API via OpenRouter (or any compatible endpoint)."""
    threaded = True

    # ---------------------------- lifecycle ---------------------------- #

    def __init__(self, irc):
        super().__init__(irc)
        # maps (channel, qualifier) → list[dict]
        self.history = defaultdict(list)

    # ---------------------------- helpers ----------------------------- #

    def _get_param(self, opts, name, channel):
        """Return `name` from opts if present, else the channel registry default."""
        if name == "temperature" and "temp" in opts:
            return opts["temp"]
        return opts.get(name, self.registryValue(name, channel))

    def _is_openrouter(self):
        """True when base_url points at OpenRouter, which has extra features
        (web plugin, reasoning object) other endpoints do not understand."""
        return "openrouter.ai" in self.registryValue("base_url").lower()

    def _history_key(self, channel, model_name, alias_name):
        """Return the key object used to segregate chat histories."""
        scope = self.registryValue("contextScope", channel).lower()
        if scope == "channel":
            return (channel, None)
        if scope == "channel+alias":
            return (channel, alias_name or model_name)
        # default ⇒ channel+model
        return (channel, model_name)

    def _append_history(self, key, user_msg, assistant_msg, max_history):
        if max_history <= 0:
            return
        hist = self.history[key]
        hist.extend([
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": assistant_msg},
        ])
        # max_history counts exchanges (one user + one assistant message)
        excess = max(len(hist) - max_history * 2, 0)
        if excess:
            del hist[:excess]

    def _is_time_sensitive(self, text):
        if not text:
            return False
        lowered = text.lower()
        keywords = [
            "latest",
            "today",
            "yesterday",
            "tomorrow",
            "this week",
            "current",
            "breaking",
            "news",
            "price",
            "stock",
            "weather",
            "score",
            "release",
            "ceo",
            "as of",
            "right now",
        ]
        # builtins.any: `from supybot.commands import *` shadows any() with
        # Limnoria's `any` converter, which raises AssertionError here.
        if builtins.any(k in lowered for k in keywords):
            return True
        # YYYY-MM-DD
        if re.search(r"\b\d{4}-\d{2}-\d{2}\b", lowered):
            return True
        return False

    def _strip_urls_and_citations(self, text):
        if not text:
            return text
        # Replace markdown links with their label, unless the label is itself a URL-like token.
        def _md_link_repl(match):
            label = match.group(1).strip()
            # If label looks like a URL/domain, drop it to avoid citation spam.
            if re.match(r"^[\w.-]+\.[a-z]{2,}$", label.lower()):
                return ""
            return label

        text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", _md_link_repl, text)
        # Remove bare URLs
        text = re.sub(r"https?://\S+", "", text)
        # Collapse leftover double spaces/newlines
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s+\n", "\n", text)
        return text.strip()

    def _annotation_urls(self, annotations):
        """Return the source URLs of the reply's annotations, in order.

        The openai library hands annotations over as objects rather than
        dicts; the URL of a web citation is at url_citation.url."""
        urls = []
        for ann in annotations or []:
            if hasattr(ann, "model_dump"):
                ann = ann.model_dump()
            if not isinstance(ann, dict):
                continue
            citation = ann.get("url_citation") or {}
            url = (
                citation.get("url")
                or ann.get("url")
                or ann.get("source")
                or ann.get("link")
            )
            if url and url not in urls:
                urls.append(url)
        return urls

    def _api_error_message(self, e):
        """Turn an openai exception into a one-line message for IRC."""
        if isinstance(e, APIStatusError):
            detail = None
            body = e.body
            if isinstance(body, dict):
                err = body.get("error", body)
                if isinstance(err, dict):
                    detail = err.get("message")
                elif isinstance(err, str):
                    detail = err
            detail = utils.str.ellipsisify(
                " ".join(str(detail or e.message).split()), 300)
            if e.status_code == 429:
                return f"Rate limited by the API (429): {detail}"
            return f"API error {e.status_code}: {detail}"
        return f"Could not reach the API: {e}"

    # ---------------------------- command ----------------------------- #

    _OPTSPEC = {
        "model": "somethingWithoutSpaces",
        "temperature": "float",
        "temp": "float",              # alias for convenience
        "top_p": "float",
        "max_completion_tokens": "int",
        "max_tokens": "int",
        "presence_penalty": "float",
        "frequency_penalty": "float",
        "web": "",
        "no-web": "",
    }

    @wrap([
        getopts(_OPTSPEC),
        rest("text"),
    ])
    def chat(self, irc, msg, args, opts, prompt):
        """[--model <name>] [--temperature <f>] [--web|--no-web] … -- <prompt>

        Sends <prompt> to the configured API. Flags override the channel's
        defaults for this single call. --web and --no-web force OpenRouter's
        web search on or off for this call.
        """

        # list → dict and strip any accidental leading dashes
        opts = {opt.lstrip("-"): val for opt, val in opts}

        channel = msg.channel if irc.isChannel(msg.channel) else msg.nick
        if not self.registryValue("enabled", channel):
            return

        prompt_for_llm = (
            f"{msg.nick}: {prompt}"
            if self.registryValue("nick_include", channel)
            else prompt
        )

        # --------------------------------------------------------------- #
        # Build API request
        # --------------------------------------------------------------- #
        client = OpenAI(
            api_key=self.registryValue("api_key"),
            base_url=self.registryValue("base_url"),
        )
        is_openrouter = self._is_openrouter()

        system_prompt = self.registryValue("prompt", channel).replace(
            "$botnick", irc.nick
        )
        system_prompt = f"Current date: {date.today().isoformat()}\n{system_prompt}"

        model_name = opts.get("model", self.registryValue("model", channel))

        # Disallow blacklisted models
        try:
            blacklist = {m.lower() for m in (self.registryValue("models_blacklist") or [])}
        except Exception:
            blacklist = set()
        if isinstance(model_name, str) and model_name.lower() in blacklist:
            irc.error(
                f"Model '{model_name}' is disallowed by configuration. Choose a different model.")
            return

        # alias name is the first token after the bot nick, e.g. in "@grok" or "@claude"
        alias_name = msg.args[1].split()[0] if msg.args and len(msg.args) > 1 else None
        key = self._history_key(channel, model_name, alias_name)
        max_history = self.registryValue("max_history", channel)
        history = self.history[key][-max_history * 2:] if max_history > 0 else []

        request_params = {
            "model": model_name,
            "messages": [{"role": "system", "content": system_prompt}]
            + history
            + [{"role": "user", "content": prompt_for_llm}],
            "user": msg.nick,
        }
        extra_body = {}

        for pname, default in _SAMPLING_DEFAULTS.items():
            if pname == "frequency_penalty" and "gemini" in model_name.lower():
                continue
            value = self._get_param(opts, pname, channel)
            if value != default:
                request_params[pname] = value

        # Choose exactly one token limit parameter, preferring max_completion_tokens
        mct = self._get_param(opts, "max_completion_tokens", channel)
        if isinstance(mct, int) and mct > 0:
            request_params["max_completion_tokens"] = mct
        else:
            mt = self._get_param(opts, "max_tokens", channel)
            if isinstance(mt, int) and mt > 0:
                request_params["max_tokens"] = mt

        # OpenRouter takes a reasoning object, other endpoints (Groq, OpenAI)
        # the flat reasoning_effort parameter.
        effort = self.registryValue("reasoning_effort", channel).strip().lower()
        if effort:
            if is_openrouter:
                extra_body["reasoning"] = {"effort": effort}
            else:
                request_params["reasoning_effort"] = effort

        # --------------------------------------------------------------- #
        # Web search plugin options
        # --------------------------------------------------------------- #
        web_mode = str(self.registryValue("web_mode", channel)).lower()
        web_force_on = "web" in opts
        web_force_off = "no-web" in opts
        if web_force_off:
            use_web = False
        elif web_mode == "off":
            # Web search costs money, so "off" means off: --web does not
            # override it (use optin for that).
            if web_force_on:
                irc.error(
                    "Web search is disabled here (web_mode is off).")
                return
            use_web = False
        elif web_mode == "always":
            use_web = True
        elif web_mode == "optin":
            use_web = web_force_on
        else:
            use_web = web_force_on or self._is_time_sensitive(prompt)

        # The web plugin is an OpenRouter feature; other endpoints reject or
        # ignore it. Say so when search was asked for explicitly, and quietly
        # skip it when it was only triggered by auto mode.
        if use_web and not is_openrouter:
            if web_force_on or web_mode == "always":
                irc.error(
                    "Web search only works when base_url points at OpenRouter.")
                return
            use_web = False

        web_plugin = None
        if use_web:
            engine = str(self.registryValue("web_engine", channel)).lower()
            search_context_size = str(
                self.registryValue("web_search_context_size", channel)
            ).lower()
            try:
                max_results = int(self.registryValue("web_max_results", channel))
            except Exception:
                max_results = 5
            search_prompt = self.registryValue("web_search_prompt", channel)
            if max_results < 1:
                max_results = 1
            if max_results > 10:
                max_results = 10

            web_plugin = {"id": "web", "max_results": max_results}
            if search_prompt:
                web_plugin["search_prompt"] = search_prompt
            if engine in _WEB_ENGINES:
                web_plugin["engine"] = engine

            extra_body["plugins"] = [web_plugin]
            # Only used by models with native search
            extra_body["web_search_options"] = {
                "search_context_size": search_context_size,
            }

        if extra_body:
            request_params["extra_body"] = extra_body

        # --------------------------------------------------------------- #
        # Log the request; the full payload holds users' messages, so it
        # only goes to the debug log.
        # --------------------------------------------------------------- #
        scope = self.registryValue("contextScope", channel)
        self.log.info(
            f"OpenRouter request → base_url={self.registryValue('base_url')} "
            f"model={model_name} scope={scope} key={key!r} "
            f"history_used={len(history)} "
            f"messages_total={len(request_params['messages'])} "
            f"use_web={use_web} web_mode={web_mode} "
            f"web_plugin={web_plugin if use_web else 'omitted'}"
        )
        try:
            payload_json = json.dumps(request_params, ensure_ascii=False, separators=(",", ":"))
            self.log.debug(f"OpenRouter request payload={payload_json}")
        except Exception as e:
            # Fallback to repr if JSON serialization fails for any reason
            self.log.debug(
                f"OpenRouter request (repr fallback due to {e}): {request_params!r}"
            )

        # --------------------------------------------------------------- #
        # Call the API
        # --------------------------------------------------------------- #
        try:
            completion = client.chat.completions.create(**request_params)
        except APIError as e:
            self.log.warning(f"OpenRouter request failed: {e}")
            irc.error(self._api_error_message(e))
            return

        if not getattr(completion, "choices", None):
            self.log.warning(f"OpenRouter response without choices: {completion!r}")
            irc.error("The API returned no reply.")
            return

        choice0 = completion.choices[0]
        message0 = choice0.message
        finish_reason = getattr(choice0, "finish_reason", None)
        # Log response metadata
        try:
            usage = getattr(completion, "usage", None)
            prompt_toks = getattr(usage, "prompt_tokens", None) if usage else None
            completion_toks = getattr(usage, "completion_tokens", None) if usage else None
            total_toks = getattr(usage, "total_tokens", None) if usage else None
            self.log.info(
                f"OpenRouter response ← id={getattr(completion, 'id', None)} "
                f"model={getattr(completion, 'model', None)} finish={finish_reason} "
                f"tokens=({prompt_toks}, {completion_toks}, {total_toks}) "
                f"created={getattr(completion, 'created', None)}"
            )
        except Exception as e:
            self.log.info(f"OpenRouter response (metadata logging failed): {e}")

        # Reasoning models can spend the whole token budget thinking and
        # return no content at all.
        content = (message0.content or "").strip()
        if not content:
            if finish_reason == "length":
                irc.error(
                    "The model ran out of tokens before replying. Raise "
                    "max_tokens (or max_completion_tokens), or lower "
                    "reasoning_effort.")
            else:
                irc.error("The model returned an empty reply.")
            return

        # Log any annotations (sources) if present
        urls = self._annotation_urls(getattr(message0, "annotations", None))
        if urls:
            self.log.info(f"OpenRouter sources: {' '.join(urls)}")

        # Optionally append sources
        if self.registryValue("web_show_sources", channel) and urls:
            content = f"{content}\nSources: " + " ".join(urls)

        # If web sources are hidden, strip URLs/markdown citations.
        if use_web and not self.registryValue("web_show_sources", channel):
            content = self._strip_urls_and_citations(content)

        if self.registryValue("nick_strip", channel):
            content = re.sub(rf"^{re.escape(irc.nick)}: ?", "", content)

        if not content.strip():
            irc.error("The model returned an empty reply.")
            return

        # --------------------------------------------------------------- #
        # Send reply back to IRC
        # --------------------------------------------------------------- #
        prefix_flag = self.registryValue("nick_prefix", channel)
        if self.registryValue("reply_intact", channel):
            for line in content.splitlines():
                if line:
                    irc.reply(line, prefixNick=prefix_flag)
        else:
            irc.reply(" ".join(content.splitlines()), prefixNick=prefix_flag)

        # --------------------------------------------------------------- #
        # Save conversation history
        # --------------------------------------------------------------- #
        self._append_history(key, prompt_for_llm, content, max_history)


Class = OpenRouter

# vim: set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
