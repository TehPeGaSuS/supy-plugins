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

from supybot.test import *

import json
import os

from google.genai import errors as genai_errors
from google.genai import types


class FakeChat:
    def __init__(self, parent, model, config, history):
        self.parent = parent
        self.model = model
        self.config = config
        self.history = list(history)

    def send_message(self, text):
        self.parent.sent.append(self)
        self.api_key = self.parent.api_key
        self.parent.texts.append(text)
        if isinstance(self.parent.reply, Exception):
            raise self.parent.reply
        self.history.append(types.Content(role="user", parts=[types.Part(text=text)]))
        if self.parent.reply is not None:
            self.history.append(
                types.Content(role="model", parts=[types.Part(text=self.parent.reply)])
            )
            candidate = types.Candidate(
                content=self.history[-1], finish_reason=types.FinishReason.STOP
            )
            if self.parent.grounding is not None:
                (queries, domains) = self.parent.grounding
                candidate.grounding_metadata = types.GroundingMetadata(
                    web_search_queries=queries,
                    grounding_chunks=[
                        types.GroundingChunk(
                            web=types.GroundingChunkWeb(
                                domain=d, title=d, uri="https://%s/" % d
                            )
                        )
                        for d in domains
                    ],
                )
        else:
            candidate = types.Candidate(finish_reason=types.FinishReason.SAFETY)
        return types.GenerateContentResponse(candidates=[candidate])

    def get_history(self, curated=False):
        return list(self.history)


class FakeClient:
    def __init__(self):
        self.sent = []
        self.texts = []
        self.reply = "Hello there"
        self.grounding = None
        self.api_key = None
        self.chats = self

    def create(self, model, config, history):
        return FakeChat(self, model, config, history)


class GeminiTestCase(ChannelPluginTestCase):
    plugins = ("Gemini", "MessageParser")
    config = {"supybot.plugins.Gemini.api_key": "testkey"}

    def setUp(self):
        super().setUp()
        self.fake = FakeClient()
        cb = self.irc.getCallback("Gemini")
        cb.history.clear()
        def client(api_key, timeout):
            self.fake.api_key = api_key
            return self.fake

        cb._client = client
        if os.path.exists(cb.usage_file):
            os.remove(cb.usage_file)

    def testNoApiKey(self):
        with conf.supybot.plugins.Gemini.api_key.context(""):
            self.assertError("chat hi")
        self.assertEqual(self.fake.sent, [])

    def testReplyAndConfig(self):
        self.assertResponse("chat hi", "Hello there")
        chat = self.fake.sent[-1]
        self.assertEqual(chat.model, "gemini-3.8-flash")
        self.assertEqual(chat.config.max_output_tokens, 200)
        self.assertEqual(
            chat.config.thinking_config.thinking_level, types.ThinkingLevel.MINIMAL
        )
        self.assertIn(self.irc.nick, chat.config.system_instruction)
        self.assertEqual(self.fake.texts[-1], "%s: hi" % self.nick)

    def testNoThinkingLevel(self):
        with conf.supybot.plugins.Gemini.thinking_level.context(""):
            self.assertResponse("chat hi", "Hello there")
        self.assertIsNone(self.fake.sent[-1].config.thinking_config)

    def testHistory(self):
        self.assertNotError("chat one")
        self.assertNotError("chat two")
        self.assertEqual(len(self.fake.sent[-1].history), 4)
        cb = self.irc.getCallback("Gemini")
        self.assertEqual(list(cb.history), [(self.irc.network, self.channel)])
        with conf.supybot.plugins.Gemini.max_history.context(3):
            self.assertNotError("chat three")
        # [one, model, two, model] trimmed to 3, then the leading model
        # turn is dropped: [two, model], plus the new exchange.
        chat = self.fake.sent[-1]
        self.assertEqual(len(chat.history), 4)
        self.assertEqual(chat.history[0].role, "user")
        self.assertEqual(chat.history[0].parts[0].text, "%s: two" % self.nick)
        with conf.supybot.plugins.Gemini.max_history.context(0):
            self.assertNotError("chat four")
        self.assertEqual(len(self.fake.sent[-1].history), 2)

    def testNickStrip(self):
        self.fake.reply = "%s: multi\n\nline" % self.irc.nick
        self.assertResponse("chat hi", "multi line")

    def testReplyIntact(self):
        self.fake.reply = "%s: line one\n\nline two" % self.irc.nick
        with conf.supybot.plugins.Gemini.reply_intact.context(True):
            self.assertResponse("chat hi", "line one")
            self.assertResponse(" ", "line two")

    def testFullReply(self):
        words = ["word%03d" % i for i in range(300)]  # ~2.4 KB, one line
        self.fake.reply = " ".join(words) + "\nsecond line"
        with conf.supybot.reply.mores.instant.context(1), \
                conf.supybot.plugins.Gemini.reply_intact.context(True):
            m = self.getMsg("chat hi")
            msgs = [m]
            while True:
                m = self.irc.takeMsg()
                if m is None:
                    break
                msgs.append(m)
        got = [m.args[1] for m in msgs]
        self.assertGreater(len(got), 3)
        self.assertEqual(got[-1], "second line")
        self.assertNotIn("more message", " ".join(got))
        self.assertEqual(" ".join(got[:-1]).split(), words)
        for m in msgs:
            line = ircmsgs.IrcMsg(msg=m, server_tags={}, prefix=self.irc.prefix)
            self.assertLessEqual(len(str(line).encode()), 512)

    def _collect(self, command="chat hi"):
        msgs = [self.getMsg(command)]
        while True:
            m = self.irc.takeMsg()
            if m is None:
                return msgs
            msgs.append(m)

    def _relayed(self, m, sender):
        """The line as the server relays it to the other users."""
        line = ircmsgs.IrcMsg(msg=m, server_tags={}, prefix=sender)
        return len(str(line).encode())

    def _assertSplit(self, sender, words, joiner=" "):
        msgs = self._collect()
        sizes = [self._relayed(m, sender) for m in msgs]
        self.assertLessEqual(max(sizes), 512, sizes)
        # no space wasted either: every message but the last is nearly full
        self.assertGreaterEqual(min(sizes[:-1]), 490, sizes)
        self.assertEqual(" ".join(m.args[1] for m in msgs).split(), words)
        return msgs

    def testSplitAfterChghost(self):
        user, host = "u" * 10, "h" * 63
        self.irc.feedMsg(
            ircmsgs.IrcMsg(prefix=self.irc.prefix, command="CHGHOST", args=(user, host))
        )
        words = ["word%03d" % i for i in range(300)]
        self.fake.reply = " ".join(words)
        self._assertSplit("%s!%s@%s" % (self.irc.nick, user, host), words)

    def testSplitAfter396(self):
        host = "a-rather-long-vhost.users.example-network.org"
        self.irc.feedMsg(
            ircmsgs.IrcMsg(
                prefix="irc.server",
                command="396",
                args=(self.irc.nick, host, "is now your displayed host"),
            )
        )
        cb = self.irc.getCallback("Gemini")
        self.assertEqual(cb.own_hosts[self.irc.network], {"host": host})
        words = ["word%03d" % i for i in range(300)]
        self.fake.reply = " ".join(words)
        ident = ircutils.splitHostmask(self.irc.prefix)[1]
        self._assertSplit("%s!%s@%s" % (self.irc.nick, ident, host), words)

    def testOwnHostsResetOnConnect(self):
        cb = self.irc.getCallback("Gemini")
        self.irc.feedMsg(
            ircmsgs.IrcMsg(prefix=self.irc.prefix, command="CHGHOST", args=("u", "h" * 63))
        )
        self.assertIn(self.irc.network, cb.own_hosts)
        self.irc.feedMsg(
            ircmsgs.IrcMsg(prefix="irc.server", command="001", args=(self.irc.nick, "hi"))
        )
        self.assertNotIn(self.irc.network, cb.own_hosts)

    def testSplitUnknownHost(self):
        cb = self.irc.getCallback("Gemini")
        self.irc.prefix = "%s!%s@unset.domain" % (self.irc.nick, "x")
        self.irc.state.nicksToHostmasks.pop(self.irc.nick, None)
        self.irc.state.supported["hostlen"] = 64
        self.irc.state.supported["userlen"] = 12
        try:
            self.assertEqual(
                cb._own_prefix_length(self.irc), len(self.irc.nick) + 1 + 1 + 1 + 64
            )
            self.irc.prefix = "%s@unset.domain" % self.irc.nick  # no ident
            self.assertEqual(
                cb._own_prefix_length(self.irc), len(self.irc.nick) + 1 + 13 + 1 + 64
            )
        finally:
            del self.irc.state.supported["hostlen"]
            del self.irc.state.supported["userlen"]

    def testMoresLengthIsCapped(self):
        words = ["word%03d" % i for i in range(300)]
        self.fake.reply = " ".join(words)
        with conf.supybot.reply.mores.length.context(1000):
            self._assertSplit(self.irc.prefix, words)
        with conf.supybot.reply.mores.length.context(100):
            msgs = self._collect()
        self.assertTrue(all(len(m.args[1].encode()) <= 100 for m in msgs))

    def testSplitUtf8(self):
        words = ["ação%03d" % i for i in range(300)]
        self.fake.reply = " ".join(words)
        self._assertSplit(self.irc.prefix, words)

    def testSplitLongWord(self):
        url = "https://example.org/" + "x" * 1000
        self.fake.reply = "see %s ok" % url
        msgs = self._collect()
        for m in msgs:
            self.assertLessEqual(self._relayed(m, self.irc.prefix), 512)
        self.assertEqual("".join(m.args[1] for m in msgs).replace(" ", ""),
                         ("see%sok" % url))

    def testFullReplyMaximum(self):
        self.fake.reply = "\n".join("line %d" % i for i in range(10))
        with conf.supybot.reply.mores.maximum.context(3), \
                conf.supybot.plugins.Gemini.reply_intact.context(True):
            self.assertResponse("chat hi", "line 0")
            self.assertResponse(" ", "line 1")
            self.assertResponse(" ", "line 2")
            self.assertNoResponse(" ", 1)

    def testFullReplyOff(self):
        self.fake.reply = " ".join("word%03d" % i for i in range(300))
        with conf.supybot.plugins.Gemini.full_reply.context(False), \
                conf.supybot.reply.mores.instant.context(1):
            m = self.getMsg("chat hi")
            self.assertIn("more message", m.args[1])
            self.assertIsNone(self.irc.takeMsg())

    def _apiError(self, code, message, status):
        return genai_errors.APIError(
            code, {"error": {"code": code, "message": message, "status": status}}
        )

    def testErrorReplies(self):
        self.fake.reply = self._apiError(
            503, "This model is currently experiencing high demand.", "UNAVAILABLE"
        )
        self.assertRegexp("chat hi", "busy right now .gemini-3.8-flash.")
        self.fake.reply = self._apiError(429, "Resource exhausted", "RESOURCE_EXHAUSTED")
        self.assertRegexp("chat hi", "rate limit or quota")
        self.fake.reply = self._apiError(
            400, "API key not valid. Please pass a valid API key.", "INVALID_ARGUMENT"
        )
        self.assertRegexp("chat hi", "plugins.Gemini.api_key")
        self.fake.reply = self._apiError(
            400, "Thinking level is not supported for this model.", "INVALID_ARGUMENT"
        )
        self.assertRegexp("chat hi", 'support thinking levels, use: config plugins.Gemini.thinking_level ""')
        self.fake.reply = self._apiError(
            400,
            "Thinking level MINIMAL is not supported for this model. Please retry with other thinking level.",
            "INVALID_ARGUMENT",
        )
        self.assertRegexp("chat hi", "support this thinking level, try another one")
        self.fake.reply = self._apiError(404, "models/nope is not found", "NOT_FOUND")
        self.assertRegexp("chat hi", "plugins.Gemini.model")
        self.fake.reply = type("ReadTimeout", (Exception,), {})("timed out")
        self.assertRegexp("chat hi", "within 60 seconds")
        self.fake.reply = RuntimeError("boom")
        self.assertRegexp("chat hi", "RuntimeError")
        self.fake.reply = None
        self.assertRegexp("chat hi", "no answer .SAFETY.")

    def testErrorReplyOff(self):
        self.fake.reply = RuntimeError("boom")
        with conf.supybot.plugins.Gemini.error_reply.context(False):
            self.assertNoResponse("chat hi", 1)

    def testMessageParserErrorCooldown(self):
        # a nick mention turned into "chat $1" by MessageParser: the line
        # itself isn't addressed to the bot, so errors are rate limited
        self.assertNotError(
            'messageparser add "(?i)(.*%s.*)" "gemini chat $1"' % self.irc.nick
        )
        cb = self.irc.getCallback("Gemini")
        line = "hey %s there" % self.irc.nick
        self.fake.reply = RuntimeError("boom")
        self.irc.feedMsg(ircmsgs.privmsg(self.channel, line, prefix=self.prefix))
        self.assertRegexp(" ", "RuntimeError")
        self.assertEqual(self.fake.texts[-1], "%s: %s" % (self.nick, line))
        # within error_cooldown: silent
        self.irc.feedMsg(ircmsgs.privmsg(self.channel, line, prefix=self.prefix))
        self.assertNoResponse(" ", 2)
        # commands run directly always get their error
        self.assertRegexp("chat hi", "RuntimeError")
        # once the cooldown has passed, the next one is sent again
        for key in cb.last_error:
            cb.last_error[key] -= 601
        self.irc.feedMsg(ircmsgs.privmsg(self.channel, line, prefix=self.prefix))
        self.assertRegexp(" ", "RuntimeError")
        # 0 sends every error
        with conf.supybot.plugins.Gemini.error_cooldown.context(0):
            self.irc.feedMsg(ircmsgs.privmsg(self.channel, line, prefix=self.prefix))
            self.assertRegexp(" ", "RuntimeError")
        # and it still answers through MessageParser when all is well
        self.fake.reply = "Hello there"
        self.irc.feedMsg(ircmsgs.privmsg(self.channel, line, prefix=self.prefix))
        self.assertResponse(" ", "Hello there")

    def testClientTimeout(self):
        cb = self.irc.getCallback("Gemini")
        client = type(cb)._client(cb, "k", 60)
        self.assertIs(type(cb)._client(cb, "k", 60), client)
        self.assertEqual(client._api_client._http_options.timeout, 60000)
        self.assertIsNone(type(cb)._client(cb, "k", 0)._api_client._http_options.timeout)

    def testWhitespaceAnswerIsSilent(self):
        self.fake.reply = "  \n \n"
        self.assertNoResponse("chat hi", 1)

    def _usage(self):
        cb = self.irc.getCallback("Gemini")
        with open(cb.usage_file) as f:
            return json.load(f)

    def _chatPrompt(self):
        self.assertNotError("chat hi")
        return self.fake.sent[-1].config.system_instruction

    def testSearchPromptEmpty(self):
        with conf.supybot.plugins.Gemini.search_prompt.context(""):
            self.assertNotError("gemini search hi")
        self.assertEqual(
            self.fake.sent[-1].config.system_instruction, self._chatPrompt()
        )

    def testChatNeverSearches(self):
        with conf.supybot.plugins.Gemini.search_api_key.context("billed"):
            self.assertResponse("chat hi", "Hello there")
        chat = self.fake.sent[-1]
        self.assertFalse(chat.config.tools)
        self.assertEqual(chat.api_key, "testkey")

    def testSearch(self):
        self.fake.reply = "Benfica won 2-1"
        self.fake.grounding = (["benfica porto result"] * 2, ["record.pt", "abola.pt", "x.com", "y.org"])
        with conf.supybot.plugins.Gemini.search_api_key.context("billed"):
            self.assertResponse("gemini search who won?", "Benfica won 2-1")
            self.assertNoResponse(" ", 1)  # no extra lines
        chat = self.fake.sent[-1]
        self.assertEqual(chat.api_key, "billed")
        self.assertIsNotNone(chat.config.tools[0].google_search)
        # the search prompt replaces the normal (personality) prompt
        self.assertIn("no Markdown", chat.config.system_instruction)
        self.assertIn(self.irc.nick, chat.config.system_instruction)
        self.assertNotIn("$botnick", chat.config.system_instruction)
        usage = self._usage()
        self.assertEqual((usage["day_count"], usage["month_count"]), (2, 2))
        self.assertResponse("searches", "Web searches today: 2/150, this month: 2/4800 (days reset at midnight Pacific time).")
        # search answers go into the shared history, so chat can follow up
        self.assertNotError("chat and then?")
        history = self.fake.sent[-1].history
        self.assertEqual(len(history), 4)  # search + this one
        self.assertEqual(history[1].parts[0].text, "Benfica won 2-1")
        # whatever the personality prompt says
        with conf.supybot.plugins.Gemini.prompt.context("Be RUDE"):
            self.assertNotError("gemini search hi")
            self.assertNotIn("RUDE", self.fake.sent[-1].config.system_instruction)
            self.assertEqual(self._chatPrompt(), "Be RUDE")

    def testSearchWithoutSearchingCountsOne(self):
        # Google's quota counts the request even if the model didn't search
        self.fake.grounding = None
        self.assertResponse("gemini search hi", "Hello there")
        self.assertEqual(self.fake.sent[-1].api_key, "testkey")  # falls back
        self.assertEqual(self._usage()["day_count"], 1)

    def testSearchLimits(self):
        self.fake.grounding = (["q"], ["a.com"])
        with conf.supybot.plugins.Gemini.search_daily_limit.context(2):
            self.assertNotError("gemini search one")
            self.assertNotError("gemini search two")
            before = len(self.fake.sent)
            self.assertRegexp("gemini search three", "Daily web search limit reached .2.. Try again after midnight")
            self.assertEqual(len(self.fake.sent), before)
            # chat still works
            self.assertResponse("chat hi", "Hello there")
        with conf.supybot.plugins.Gemini.search_monthly_limit.context(2):
            self.assertRegexp(
                "gemini search three", "Monthly web search limit reached .2.. Try again next month"
            )
        with conf.supybot.plugins.Gemini.search_daily_limit.context(0):
            self.assertRegexp("gemini search three", "disabled")

    def testSearchErrorGivesReservationBack(self):
        self.fake.reply = RuntimeError("boom")
        self.assertRegexp("gemini search hi", "RuntimeError")
        self.assertEqual(self._usage()["day_count"], 0)

    def testUsageResets(self):
        cb = self.irc.getCallback("Gemini")
        os.makedirs(os.path.dirname(cb.usage_file), exist_ok=True)
        with open(cb.usage_file, "w") as f:
            json.dump({"day": "2000-01-01", "day_count": 150,
                       "month": cb._google_today().isoformat()[:7],
                       "month_count": 300}, f)
        self.assertResponse("searches", "Web searches today: 0/150, this month: 300/4800 (days reset at midnight Pacific time).")

    def testDisabled(self):
        with conf.supybot.plugins.Gemini.enabled.context(False):
            self.assertNoResponse("chat hi", 1)
        self.assertEqual(self.fake.sent, [])


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
