###
# Copyright (c) 2023, oddluck
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
import re
import time
from urllib.parse import urlparse

import openai
from openai import OpenAI


_ = PluginInternationalization("ChatGPT")


class ChatGPT(callbacks.Plugin):
    """Use the OpenAI ChatGPT API"""

    threaded = True

    def __init__(self, irc):
        self.__parent = super(ChatGPT, self)
        self.__parent.__init__(irc)
        # (network, channel or nick) -> list of {"role", "content"}
        self.history = {}
        # (api_key, base_url, timeout) -> OpenAI client
        self.clients = {}
        # network -> {"ident", "host"} from our own CHGHOST / 396
        self.own_hosts = {}
        # (network, channel or nick) -> time of the last error sent for a
        # MessageParser-triggered command
        self.last_error = {}

    def _client(self, api_key, base_url, timeout):
        key = (api_key, base_url, timeout)
        client = self.clients.get(key)
        if client is None:
            client = OpenAI(
                api_key=api_key,
                base_url=base_url or None,
                # The SDK default is 600s with 2 retries: a busy API would
                # leave the command hanging for many minutes.
                timeout=timeout or None,
                max_retries=1,
            )
            self.clients[key] = client
        return client

    @staticmethod
    def _is_openai(base_url):
        host = urlparse(base_url or "https://api.openai.com/v1/").hostname
        return host == "api.openai.com"

    @staticmethod
    def _trim(history, max_history):
        history = history[-max_history:]
        # A conversation must start with a user turn.
        while history and history[0]["role"] != "user":
            history = history[1:]
        return history

    # --- error replies -----------------------------------------------------

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
    def _error_text(e, model, timeout):
        if isinstance(e, openai.APITimeoutError):
            return _(
                "The API didn't answer within %s seconds, try again later."
            ) % timeout
        if isinstance(e, openai.APIConnectionError):
            return _("Couldn't reach the API, see the bot's log.")
        if isinstance(e, openai.RateLimitError):
            return _("Rate limit or quota reached, try again later.")
        if isinstance(e, openai.InternalServerError):
            return _("The API is busy right now (%s), try again in a bit.") % (
                model
            )
        if isinstance(e, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return _(
                "The API rejected the key, check: config plugins.ChatGPT.api_key"
            )
        if isinstance(e, openai.NotFoundError):
            return _(
                "The API doesn't know the model %s, check: "
                "config plugins.ChatGPT.model"
            ) % model
        if isinstance(e, openai.APIStatusError):
            message = e.message
            if isinstance(e.body, dict):
                message = e.body.get("message") or message
            return _("API error %s: %s") % (e.status_code, message)
        return _("Couldn't get an answer (%s), see the bot's log.") % (
            type(e).__name__
        )

    # --- reply splitting (same as the Gemini plugin) ------------------------

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
        one the server cuts loses text. Falls back to ISUPPORT
        USERLEN/HOSTLEN (or 10/63)."""
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
            log.exception("ChatGPT: could not compute the reply overhead")
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
                "ChatGPT: reply truncated to %s of %s messages "
                "(supybot.reply.mores.maximum)",
                maximum,
                len(chunks),
            )
        for chunk in chunks[:maximum]:
            irc.reply(chunk, prefixNick=prefix, noLengthCheck=True)

    # --- command -----------------------------------------------------------

    def _request(self, channel, network, model, base_url, messages):
        params = {"model": model, "messages": messages}
        max_tokens = self.registryValue("max_tokens", channel, network)
        if self._is_openai(base_url):
            # OpenAI deprecated max_tokens; reasoning models reject it.
            params["max_completion_tokens"] = max_tokens
        else:
            # Most OpenAI-compatible servers only know max_tokens.
            params["max_tokens"] = max_tokens
        effort = self.registryValue("reasoning_effort", channel, network)
        if effort:
            params["reasoning_effort"] = effort
        # Only send sampling parameters that differ from the API defaults:
        # reasoning models (and some compatible servers, e.g. Gemini for
        # frequency_penalty) reject them, even at their default values.
        for (name, default) in (
            ("temperature", 1),
            ("top_p", 1),
            ("presence_penalty", 0),
            ("frequency_penalty", 0),
        ):
            value = self.registryValue(name, channel, network)
            if value != default:
                params[name] = value
        return params

    def chat(self, irc, msg, args, text):
        """<text>

        Sends <text> to the ChatGPT API and replies with the answer.
        """
        channel = msg.channel
        network = irc.network
        if not self.registryValue("enabled", channel, network):
            log.debug(
                "ChatGPT: plugins.ChatGPT.enabled is False for %s on %s, "
                "ignoring",
                channel or msg.nick,
                network,
            )
            return
        api_key = self.registryValue("api_key")
        if not api_key:
            irc.error(
                _(
                    "No API key set. Get one at "
                    "https://platform.openai.com/account/api-keys then use: "
                    "config plugins.ChatGPT.api_key <key>"
                ),
                Raise=True,
            )
        if self.registryValue("nick_include", channel, network):
            text = "%s: %s" % (msg.nick, text)
        base_url = self.registryValue("base_url")
        model = self.registryValue("model", channel, network)
        timeout = self.registryValue("timeout", channel, network)
        prompt = self.registryValue("prompt", channel, network).replace(
            "$botnick", irc.nick
        )
        key = (network, channel or msg.nick)
        max_history = self.registryValue("max_history", channel, network)
        if max_history < 1:
            history = []
        else:
            history = self._trim(self.history.get(key, []), max_history)
        messages = (
            [{"role": "system", "content": prompt}]
            + history
            + [{"role": "user", "content": text}]
        )
        params = self._request(channel, network, model, base_url, messages)
        log.debug(
            "ChatGPT: asking %s (history: %s messages, timeout: %ss)",
            model,
            len(history),
            timeout or "none",
        )
        started = time.monotonic()
        try:
            client = self._client(api_key, base_url, timeout)
            completion = client.chat.completions.create(**params)
        except Exception as e:
            if isinstance(e, openai.APIStatusError):
                log.error(
                    "ChatGPT: API error %s: %s", e.status_code, e.message
                )
            else:
                log.error(
                    "ChatGPT failed to fetch response: %s: %s",
                    type(e).__name__,
                    e,
                )
            self._fail(irc, msg, self._error_text(e, model, timeout))
            return
        log.debug(
            "ChatGPT: %s answered in %.1fs", model, time.monotonic() - started
        )
        choice = completion.choices[0] if completion.choices else None
        content = (choice.message.content or "") if choice else ""
        if not content.strip():
            reason = choice.finish_reason if choice else None
            log.warning("ChatGPT: empty response (finish_reason: %s)", reason)
            if reason == "length":
                self._fail(
                    irc,
                    msg,
                    _(
                        "The answer ran out of tokens before any text "
                        "(reasoning counts too): raise "
                        "plugins.ChatGPT.max_tokens or lower "
                        "plugins.ChatGPT.reasoning_effort."
                    ),
                )
            else:
                self._fail(irc, msg, _("No answer (%s).") % reason)
            return
        if self.registryValue("nick_strip", channel, network):
            content = re.sub(r"^%s: " % re.escape(irc.nick), "", content)
        prefix = self.registryValue("nick_prefix", channel, network)
        lines = [line for line in content.splitlines() if line.strip()]
        if not self.registryValue("reply_intact", channel, network):
            lines = [" ".join(line.strip() for line in lines)]
        if self.registryValue("full_reply", channel, network):
            self._send_full(irc, msg, lines, prefix)
        else:
            for line in lines:
                irc.reply(line, prefixNick=prefix)
        if max_history >= 1:
            history = history + [
                {"role": "user", "content": text},
                {"role": "assistant", "content": content},
            ]
            self.history[key] = self._trim(history, max_history)
        else:
            self.history.pop(key, None)

    chat = wrap(chat, ["text"])


Class = ChatGPT

# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
