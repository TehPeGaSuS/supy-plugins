###
# Copyright (c) 2024, oddluck
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

from supybot import conf, utils, plugins, ircmsgs, ircutils, callbacks
from supybot.commands import *
from supybot.i18n import PluginInternationalization
import supybot.log as log
import copy
import datetime
import json
import os
import re
import threading
import time
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

_ = PluginInternationalization("Gemini")


class Gemini(callbacks.Plugin):
    """GoogleAI Gemini Chat Plugin"""

    threaded = True

    def __init__(self, irc):
        self.__parent = super(Gemini, self)
        self.__parent.__init__(irc)
        # (network, channel or nick) -> list of types.Content
        self.history = {}
        # (api_key, timeout) -> genai.Client, so connections are reused
        self.clients = {}
        # network -> {"ident", "host"} from our own CHGHOST / 396
        self.own_hosts = {}
        # (network, channel or nick) -> time of the last error sent for a
        # MessageParser-triggered command
        self.last_error = {}
        # Google searches used by the search command, shared by every
        # network, channel and key, and kept across restarts.
        self.usage_file = conf.supybot.directories.data.dirize(
            "Gemini/search_usage.json"
        )
        self.usage_lock = threading.Lock()

    def _client(self, api_key, timeout):
        client = self.clients.get((api_key, timeout))
        if client is None:
            http_options = None
            if timeout:
                # Without it the SDK never times out, and a stalled request
                # leaves the command thread hanging with nothing logged.
                http_options = types.HttpOptions(timeout=timeout * 1000)
            client = genai.Client(api_key=api_key, http_options=http_options)
            self.clients[(api_key, timeout)] = client
        return client

    @staticmethod
    def _trim(history, max_history):
        history = history[-max_history:]
        # A conversation must start with a user turn.
        while history and history[0].role != "user":
            history = history[1:]
        return history

    def do001(self, irc, msg):
        # New connection: forget hosts from the previous one.
        self.own_hosts.pop(irc.network, None)

    def do396(self, irc, msg):
        # RPL_HOSTHIDDEN / RPL_VISIBLEHOST: "<nick> <host> :is now your
        # displayed host". Some ircds send "<ident>@<host>" instead.
        # Limnoria only learns the new host from our next own-sourced
        # message, so remember it for _own_prefix_length().
        if len(msg.args) >= 2:
            (_, _, host) = msg.args[1].rpartition("@")
            self.own_hosts.setdefault(irc.network, {})["host"] = host

    def doChghost(self, irc, msg):
        # Limnoria keeps irc.prefix on the old host after our own CHGHOST,
        # and its echo-message emulation then puts that stale prefix back
        # into irc.state.nicksToHostmasks, so track it ourselves.
        if ircutils.strEqual(msg.nick, irc.nick) and len(msg.args) >= 2:
            (ident, host) = msg.args[:2]
            self.own_hosts[irc.network] = {"ident": ident, "host": host}

    def _own_prefix_length(self, irc):
        """Bytes of the 'nick!ident@host' the server will put in front of
        our messages when relaying them. Takes the longest ident and host
        known from every source, since Limnoria's irc.prefix is not updated
        on our own CHGHOST or on 396, and is a placeholder before we joined
        anything. The longest wins: a line that is a bit short is harmless,
        one the server cuts loses text. Falls back to ISUPPORT USERLEN/HOSTLEN (or 10/63)."""
        idents, hosts = [], []
        masks = (irc.prefix, irc.state.nicksToHostmasks.get(irc.nick))
        for mask in masks:
            if mask and ircutils.isUserHostmask(mask):
                (_nick, ident, host) = ircutils.splitHostmask(mask)
                idents.append(ident)
                if host != "unset.domain":
                    hosts.append(host)
        own = self.own_hosts.get(irc.network, {})
        if own.get("ident"):
            idents.append(own["ident"])
        if own.get("host"):
            hosts.append(own["host"])
        supported = irc.state.supported
        if not hosts:
            hosts.append("x" * supported.get("hostlen", 63))
        if not idents:
            # +1 for the "~" of a missing identd reply
            idents.append("x" * (supported.get("userlen", 10) + 1))
        return (
            len(irc.nick.encode())
            + 1
            + max(len(i.encode()) for i in idents)
            + 1
            + max(len(h.encode()) for h in hosts)
        )

    def _max_payload(self, irc, msg, prefix):
        """Bytes of text that fit in one reply, accounting for our hostmask,
        the command (PRIVMSG/NOTICE), the target (channel or nick, with
        supybot.reply.inPrivate etc.), the 'nick: ' prefix and CRLF, within
        the 512-byte IRC line limit (tags have their own budget)."""
        try:
            # Same trick as Limnoria's _replyOverhead: build a dummy reply
            # and measure it. deepcopy because _makeReply tags the message.
            probe = copy.deepcopy(msg)
            probe.channel = msg.channel
            reply = callbacks._makeReply(irc, probe, "x", prefixNick=prefix)
            sender = "p" * self._own_prefix_length(irc)
            line = ircmsgs.IrcMsg(msg=reply, server_tags={}, prefix=sender)
            overhead = len(str(line).encode()) - len(b"x")
        except Exception:
            log.exception("Gemini: could not compute the reply overhead")
            overhead = 512 - 350
        length = 512 - overhead
        configured = conf.get(
            conf.supybot.reply.mores.length,
            channel=msg.channel,
            network=irc.network,
        )
        if configured:
            length = min(length, configured)
        return max(length, 50)

    def _fail(self, irc, msg, text):
        """Tells the user why there is no answer. Always when they ran the
        command themselves; when MessageParser turned a nick mention into
        'chat $1' (the line wasn't addressed to the bot), at most once every
        error_cooldown seconds per channel, so a busy API doesn't spam it."""
        channel, network = msg.channel, irc.network
        if not self.registryValue("error_reply", channel, network):
            return
        if not callbacks.addressed(irc, msg):
            cooldown = self.registryValue("error_cooldown", channel, network)
            key = (network, channel or msg.nick)
            now = time.monotonic()
            last = self.last_error.get(key)
            if cooldown and last is not None and now - last < cooldown:
                log.debug("%s: error reply skipped (error_cooldown)", self.name())
                return
            self.last_error[key] = now
        irc.error(text)

    @staticmethod
    def _is_timeout(e):
        # google-genai uses httpx (1.x/2.x) or httpx2 (3.x); match their
        # *Timeout classes by name rather than importing either.
        # (No any() here: supybot.commands' * import shadows it.)
        if isinstance(e, TimeoutError):
            return True
        for cls in type(e).__mro__:
            if "Timeout" in cls.__name__:
                return True
        return False

    @staticmethod
    def _api_error_text(e, model):
        if e.code == 429:
            return _("Gemini rate limit or quota reached, try again later.")
        if e.code in (500, 502, 503, 504):
            return _(
                "Gemini is busy right now (%s), try again in a bit."
            ) % model
        if e.code == 404:
            return _(
                "Gemini doesn't know the model %s, check: "
                "config plugins.Gemini.model"
            ) % model
        if e.code in (400, 401, 403) and "api key" in (e.message or "").lower():
            return _(
                "Gemini rejected the API key, check: "
                "config plugins.Gemini.api_key"
            )
        return _("Gemini error %s: %s") % (e.code, e.message)

    def _send_full(self, irc, msg, lines, prefix):
        """Sends every line, splitting long ones ourselves so nothing is
        held back for the 'more' command. supybot.reply.mores.maximum still
        caps the total number of messages."""
        channel, network = msg.channel, irc.network
        length = self._max_payload(irc, msg, prefix)
        maximum = conf.get(
            conf.supybot.reply.mores.maximum, channel=channel, network=network
        )
        chunks = [c for line in lines for c in ircutils.wrap(line, length)]
        if len(chunks) > maximum:
            log.warning(
                "Gemini: reply truncated to %s of %s messages "
                "(supybot.reply.mores.maximum)",
                maximum,
                len(chunks),
            )
        for chunk in chunks[:maximum]:
            irc.reply(chunk, prefixNick=prefix, noLengthCheck=True)

    # --- search usage counter -----------------------------------------------

    @staticmethod
    def _google_today():
        """Google resets its quotas at midnight Pacific time."""
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo("America/Los_Angeles")
        except Exception:
            tz = datetime.timezone(datetime.timedelta(hours=-8))
        return datetime.datetime.now(tz).date()

    def _load_usage(self):
        try:
            with open(self.usage_file) as f:
                usage = json.load(f)
        except FileNotFoundError:
            usage = {}
        except Exception:
            log.exception("Gemini: could not read %s", self.usage_file)
            usage = {}
        today = self._google_today()
        day, month = today.isoformat(), today.isoformat()[:7]
        if usage.get("day") != day:
            usage["day"], usage["day_count"] = day, 0
        if usage.get("month") != month:
            usage["month"], usage["month_count"] = month, 0
        return usage

    def _save_usage(self, usage):
        try:
            os.makedirs(os.path.dirname(self.usage_file), exist_ok=True)
            tmp = self.usage_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(usage, f)
            os.replace(tmp, self.usage_file)
        except Exception:
            log.exception("Gemini: could not write %s", self.usage_file)

    def _limits(self):
        return (
            self.registryValue("search_daily_limit"),
            self.registryValue("search_monthly_limit"),
        )

    def _reserve_search(self):
        """Counts one search before the request, so two requests at the
        same time can't both slip under the limit. Returns False when a
        limit is reached."""
        (daily, monthly) = self._limits()
        with self.usage_lock:
            usage = self._load_usage()
            if (
                not daily
                or not monthly
                or usage["day_count"] >= daily
                or usage["month_count"] >= monthly
            ):
                return False
            usage["day_count"] += 1
            usage["month_count"] += 1
            self._save_usage(usage)
            return True

    def _settle_search(self, used):
        """Replaces the one search reserved by _reserve_search() with the
        number of queries Google actually ran (and bills)."""
        with self.usage_lock:
            usage = self._load_usage()
            for name in ("day_count", "month_count"):
                usage[name] = max(0, usage[name] + used - 1)
            self._save_usage(usage)

    @staticmethod
    def _grounding(response):
        """(number of search queries run, list of source domains)."""
        if not response.candidates:
            return (0, [])
        meta = response.candidates[0].grounding_metadata
        if meta is None:
            return (0, [])
        queries = len(meta.web_search_queries or [])
        sources = []
        for chunk in meta.grounding_chunks or []:
            web = chunk.web
            if web is None:
                continue
            name = web.domain or web.title or web.uri
            if name and name not in sources:
                sources.append(name)
        if not queries and (sources or meta.search_entry_point):
            # Searched without telling us the queries: count it anyway.
            queries = 1
        return (queries, sources)

    # --- commands ------------------------------------------------------------

    def _ask(self, irc, msg, text, search=False):
        channel = msg.channel
        network = irc.network
        if not self.registryValue("enabled", channel, network):
            log.debug(
                "Gemini: plugins.Gemini.enabled is False for %s on %s, "
                "ignoring",
                channel or msg.nick,
                network,
            )
            return
        api_key = self.registryValue("api_key", channel, network)
        if search:
            api_key = (
                self.registryValue("search_api_key", channel, network)
                or api_key
            )
        if not api_key:
            irc.error(
                _(
                    "No API key set. Get one at "
                    "https://aistudio.google.com/app/apikey then use: "
                    "config plugins.Gemini.api_key <key>"
                ),
                Raise=True,
            )
        if search and not self._reserve_search():
            (daily, monthly) = self._limits()
            if not daily or not monthly:
                why = _("Web search is disabled on this bot.")
            elif self._load_usage()["month_count"] >= monthly:
                why = _(
                    "Monthly web search limit reached (%s). Try again "
                    "next month, or use: chat"
                ) % monthly
            else:
                why = _(
                    "Daily web search limit reached (%s). Try again after "
                    "midnight Pacific time, or use: chat"
                ) % daily
            self._fail(irc, msg, why)
            return
        prompt = self.registryValue("prompt", channel, network)
        if search:
            extra = self.registryValue("search_prompt", channel, network)
            if extra:
                prompt = "%s\n\n%s" % (prompt, extra)
        prompt = prompt.replace("$botnick", irc.nick)
        config = types.GenerateContentConfig(
            system_instruction=prompt,
            max_output_tokens=self.registryValue("max_tokens", channel, network),
        )
        if search:
            config.tools = [types.Tool(google_search=types.GoogleSearch())]
        thinking_level = self.registryValue("thinking_level", channel, network)
        if thinking_level:
            config.thinking_config = types.ThinkingConfig(
                thinking_level=thinking_level.upper()
            )
        key = (network, channel or msg.nick)
        max_history = self.registryValue("max_history", channel, network)
        if max_history < 1:
            history = []
        else:
            history = self._trim(self.history.get(key, []), max_history)
        model = self.registryValue("model", channel, network)
        timeout = self.registryValue("timeout", channel, network)
        chat = self._client(api_key, timeout).chats.create(
            model=model,
            config=config,
            history=history,
        )
        if self.registryValue("nick_include", channel, network):
            text = "%s: %s" % (msg.nick, text)
        log.debug(
            "Gemini: asking %s%s (history: %s turns, timeout: %ss)",
            model,
            " with Google Search" if search else "",
            len(history),
            timeout or "none",
        )
        started = time.monotonic()
        try:
            response = chat.send_message(text)
        except Exception as e:
            if search:
                # Nothing billed that we can see: give the reservation back.
                self._settle_search(0)
            if isinstance(e, genai_errors.APIError):
                log.error("Gemini: API error %s: %s", e.code, e.message)
                self._fail(irc, msg, self._api_error_text(e, model))
            elif self._is_timeout(e):
                log.error("Gemini: no answer within %ss: %r", timeout, e)
                self._fail(
                    irc,
                    msg,
                    _(
                        "Gemini didn't answer within %s seconds, "
                        "try again later."
                    )
                    % timeout,
                )
            else:
                log.error(
                    "Gemini failed to fetch response: %s: %s",
                    type(e).__name__,
                    e,
                )
                self._fail(
                    irc,
                    msg,
                    _("Couldn't reach Gemini (%s), see the bot's log.")
                    % type(e).__name__,
                )
            return
        sources = []
        if search:
            (queries, sources) = self._grounding(response)
            self._settle_search(queries)
            log.info("Gemini: search ran %s Google queries", queries)
        log.debug(
            "Gemini: %s answered in %.1fs", model, time.monotonic() - started
        )
        content = response.text
        if not content:
            reason = None
            if response.candidates:
                reason = response.candidates[0].finish_reason
            elif response.prompt_feedback:
                reason = response.prompt_feedback.block_reason
            log.warning("Gemini: empty response (reason: %s)", reason)
            name = getattr(reason, "name", None) or str(reason)
            self._fail(irc, msg, _("Gemini gave no answer (%s).") % name)
            return
        if self.registryValue("nick_strip", channel, network):
            content = re.sub(r"^%s: " % re.escape(irc.nick), "", content)
        prefix = self.registryValue("nick_prefix", channel, network)
        lines = [line for line in content.splitlines() if line.strip()]
        if not lines:
            log.warning("Gemini: answer was only whitespace: %r", content)
            return
        max_sources = self.registryValue("search_sources", channel, network)
        if sources and max_sources:
            lines.append(_("Sources: %s") % ", ".join(sources[:max_sources]))
        if self.registryValue("full_reply", channel, network):
            self._send_full(irc, msg, lines, prefix)
        else:
            for line in lines:
                irc.reply(line, prefixNick=prefix)
        self.history[key] = chat.get_history(curated=True)

    def chat(self, irc, msg, args, text):
        """<text>

        Sends <text> to Gemini and replies with the answer. Never searches
        the web, see the search command for that.
        """
        self._ask(irc, msg, text)

    chat = wrap(chat, ["text"])

    def search(self, irc, msg, args, text):
        """<text>

        Like chat, but Gemini may search the web with Google Search before
        answering. Uses plugins.Gemini.search_api_key when set, and stops
        at plugins.Gemini.search_daily_limit / search_monthly_limit.
        """
        self._ask(irc, msg, text, search=True)

    search = wrap(search, ["text"])

    def searches(self, irc, msg, args):
        """takes no arguments

        Shows how many Google searches the search command used today and
        this month (Google's days start at midnight Pacific time).
        """
        (daily, monthly) = self._limits()
        with self.usage_lock:
            usage = self._load_usage()
        irc.reply(
            _(
                "Web searches today: %s/%s, this month: %s/%s "
                "(days reset at midnight Pacific time)."
            )
            % (usage["day_count"], daily, usage["month_count"], monthly)
        )

    searches = wrap(searches)


Class = Gemini


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
