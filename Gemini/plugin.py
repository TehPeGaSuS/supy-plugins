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
import re
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

    def chat(self, irc, msg, args, text):
        """<text>

        Sends <text> to the Gemini API and replies with the answer.
        """
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
        if not api_key:
            irc.error(
                _(
                    "No API key set. Get one at "
                    "https://aistudio.google.com/app/apikey then use: "
                    "config plugins.Gemini.api_key <key>"
                ),
                Raise=True,
            )
        prompt = self.registryValue("prompt", channel, network).replace(
            "$botnick", irc.nick
        )
        config = types.GenerateContentConfig(
            system_instruction=prompt,
            max_output_tokens=self.registryValue("max_tokens", channel, network),
        )
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
            "Gemini: asking %s (history: %s turns, timeout: %ss)",
            model,
            len(history),
            timeout or "none",
        )
        started = time.monotonic()
        try:
            response = chat.send_message(text)
        except genai_errors.APIError as e:
            log.error("Gemini: API error %s: %s", e.code, e.message)
            return
        except Exception as e:
            log.error(
                "Gemini failed to fetch response: %s: %s", type(e).__name__, e
            )
            return
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
            return
        if self.registryValue("nick_strip", channel, network):
            content = re.sub(r"^%s: " % re.escape(irc.nick), "", content)
        prefix = self.registryValue("nick_prefix", channel, network)
        lines = [line for line in content.splitlines() if line.strip()]
        if not lines:
            log.warning("Gemini: answer was only whitespace: %r", content)
            return
        if self.registryValue("full_reply", channel, network):
            self._send_full(irc, msg, lines, prefix)
        else:
            for line in lines:
                irc.reply(line, prefixNick=prefix)
        self.history[key] = chat.get_history(curated=True)

    chat = wrap(chat, ["text"])


Class = Gemini


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
