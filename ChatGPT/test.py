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

from supybot.test import *

try:
    import httpx2 as httpx  # openai >= 3
except ImportError:
    import httpx
import openai
from openai.types.chat import ChatCompletion


def completion(content, finish_reason="stop"):
    return ChatCompletion.model_validate(
        {
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "gpt-6-luna",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish_reason,
                    "message": {"role": "assistant", "content": content},
                }
            ],
        }
    )


def status_error(cls, code, message):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(code, request=request)
    return cls(message, response=response, body={"message": message})


class FakeClient:
    def __init__(self):
        self.calls = []
        self.reply = "Hello there"
        self.chat = self
        self.completions = self

    def create(self, **params):
        self.calls.append(params)
        if isinstance(self.reply, Exception):
            raise self.reply
        if isinstance(self.reply, tuple):
            return completion(*self.reply)
        return completion(self.reply)


class ChatGPTTestCase(ChannelPluginTestCase):
    plugins = ("ChatGPT", "MessageParser")
    config = {"supybot.plugins.ChatGPT.api_key": "testkey"}

    def setUp(self):
        super().setUp()
        self.fake = FakeClient()
        cb = self.irc.getCallback("ChatGPT")
        cb.history.clear()
        cb._client = lambda api_key, base_url, timeout: self.fake

    def _collect(self, command="chat hi"):
        msgs = [self.getMsg(command)]
        while True:
            m = self.irc.takeMsg()
            if m is None:
                return msgs
            msgs.append(m)

    def testNoApiKey(self):
        with conf.supybot.plugins.ChatGPT.api_key.context(""):
            self.assertRegexp("chat hi", "plugins.ChatGPT.api_key")
        self.assertEqual(self.fake.calls, [])

    def testRequestOpenAI(self):
        self.assertResponse("chat hi", "Hello there")
        params = self.fake.calls[-1]
        self.assertEqual(params["model"], "gpt-6-luna")
        self.assertEqual(params["max_completion_tokens"], 200)
        self.assertNotIn("max_tokens", params)
        self.assertEqual(params["reasoning_effort"], "none")
        for name in ("temperature", "top_p", "presence_penalty",
                     "frequency_penalty", "user"):
            self.assertNotIn(name, params)
        messages = params["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn(self.irc.nick, messages[0]["content"])
        self.assertEqual(messages[-1], {"role": "user", "content": "%s: hi" % self.nick})

    def testRequestOtherServer(self):
        with conf.supybot.plugins.ChatGPT.base_url.context(
            "https://api.groq.com/openai/v1"
        ), conf.supybot.plugins.ChatGPT.reasoning_effort.context(""), \
                conf.supybot.plugins.ChatGPT.temperature.context(0.5):
            self.assertResponse("chat hi", "Hello there")
        params = self.fake.calls[-1]
        self.assertEqual(params["max_tokens"], 200)
        self.assertNotIn("max_completion_tokens", params)
        self.assertNotIn("reasoning_effort", params)
        self.assertEqual(params["temperature"], 0.5)

    def testHistory(self):
        self.assertNotError("chat one")
        self.assertNotError("chat two")
        messages = self.fake.calls[-1]["messages"]
        # system first, then one, answer, two
        self.assertEqual([m["role"] for m in messages],
                         ["system", "user", "assistant", "user"])
        cb = self.irc.getCallback("ChatGPT")
        self.assertEqual(list(cb.history), [(self.irc.network, self.channel)])
        with conf.supybot.plugins.ChatGPT.max_history.context(3):
            self.assertNotError("chat three")
            # stored history is trimmed too, and starts with a user turn
            stored = cb.history[(self.irc.network, self.channel)]
            self.assertLessEqual(len(stored), 3)
            self.assertEqual(stored[0]["role"], "user")
        with conf.supybot.plugins.ChatGPT.max_history.context(0):
            self.assertNotError("chat four")
        self.assertEqual(len(self.fake.calls[-1]["messages"]), 2)
        self.assertNotIn((self.irc.network, self.channel), cb.history)

    def testJoinedByDefault(self):
        self.fake.reply = "line one\n\nline two"
        self.assertResponse("chat hi", "line one line two")

    def testReplyIntact(self):
        self.fake.reply = "%s: line one\n\nline two" % self.irc.nick
        with conf.supybot.plugins.ChatGPT.reply_intact.context(True):
            self.assertResponse("chat hi", "line one")
            self.assertResponse(" ", "line two")

    def testFullReply(self):
        words = ["word%03d" % i for i in range(300)]
        self.fake.reply = " ".join(words)
        user, host = "u" * 10, "h" * 63
        self.irc.feedMsg(
            ircmsgs.IrcMsg(prefix=self.irc.prefix, command="CHGHOST", args=(user, host))
        )
        sender = "%s!%s@%s" % (self.irc.nick, user, host)
        with conf.supybot.reply.mores.instant.context(1):
            msgs = self._collect()
        sizes = [
            len(str(ircmsgs.IrcMsg(msg=m, server_tags={}, prefix=sender)).encode())
            for m in msgs
        ]
        self.assertGreater(len(msgs), 3)
        self.assertLessEqual(max(sizes), 512, sizes)
        self.assertGreaterEqual(min(sizes[:-1]), 490, sizes)
        self.assertEqual(" ".join(m.args[1] for m in msgs).split(), words)

    def testErrorReplies(self):
        self.fake.reply = status_error(openai.InternalServerError, 503, "overloaded")
        self.assertRegexp("chat hi", "busy right now .gpt-6-luna.")
        self.fake.reply = status_error(openai.RateLimitError, 429, "slow down")
        self.assertRegexp("chat hi", "rate limit or quota")
        self.fake.reply = status_error(openai.AuthenticationError, 401, "bad key")
        self.assertRegexp("chat hi", "plugins.ChatGPT.api_key")
        self.fake.reply = status_error(openai.NotFoundError, 404, "no model")
        self.assertRegexp("chat hi", "plugins.ChatGPT.model")
        self.fake.reply = status_error(
            openai.BadRequestError, 400, "Unsupported value: 'reasoning_effort'"
        )
        self.assertRegexp("chat hi", "API error 400: Unsupported value")
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        self.fake.reply = openai.APITimeoutError(request=request)
        self.assertRegexp("chat hi", "within 60 seconds")
        self.fake.reply = openai.APIConnectionError(request=request)
        self.assertRegexp("chat hi", "Couldn't reach the API")
        self.fake.reply = RuntimeError("boom")
        self.assertRegexp("chat hi", "RuntimeError")

    def testEmptyAnswers(self):
        self.fake.reply = (None, "length")
        self.assertRegexp("chat hi", "raise plugins.ChatGPT.max_tokens")
        self.fake.reply = (None, "content_filter")
        self.assertRegexp("chat hi", "No answer .content_filter.")
        cb = self.irc.getCallback("ChatGPT")
        self.assertEqual(cb.history, {})

    def testErrorReplyOff(self):
        self.fake.reply = RuntimeError("boom")
        with conf.supybot.plugins.ChatGPT.error_reply.context(False):
            self.assertNoResponse("chat hi", 1)

    def testMessageParserErrorCooldown(self):
        self.assertNotError(
            'messageparser add "(?i)(.*%s.*)" "chatgpt chat $1"' % self.irc.nick
        )
        cb = self.irc.getCallback("ChatGPT")
        line = "hey %s there" % self.irc.nick
        self.fake.reply = RuntimeError("boom")
        self.irc.feedMsg(ircmsgs.privmsg(self.channel, line, prefix=self.prefix))
        self.assertRegexp(" ", "RuntimeError")
        self.irc.feedMsg(ircmsgs.privmsg(self.channel, line, prefix=self.prefix))
        self.assertNoResponse(" ", 2)
        self.assertEqual(len(self.fake.calls), 2)
        self.assertRegexp("chat hi", "RuntimeError")
        for key in cb.last_error:
            cb.last_error[key] -= 601
        self.irc.feedMsg(ircmsgs.privmsg(self.channel, line, prefix=self.prefix))
        self.assertRegexp(" ", "RuntimeError")
        with conf.supybot.plugins.ChatGPT.error_cooldown.context(0):
            self.irc.feedMsg(ircmsgs.privmsg(self.channel, line, prefix=self.prefix))
            self.assertRegexp(" ", "RuntimeError")
        self.fake.reply = "Hello there"
        self.irc.feedMsg(ircmsgs.privmsg(self.channel, line, prefix=self.prefix))
        self.assertResponse(" ", "Hello there")

    def testDisabled(self):
        with conf.supybot.plugins.ChatGPT.enabled.context(False):
            self.assertNoResponse("chat hi", 1)
        self.assertEqual(self.fake.calls, [])

    def testClientCache(self):
        cb = self.irc.getCallback("ChatGPT")
        client = type(cb)._client(cb, "k", "https://api.openai.com/v1/", 60)
        self.assertIs(type(cb)._client(cb, "k", "https://api.openai.com/v1/", 60), client)
        self.assertEqual(client.timeout, 60)
        self.assertEqual(client.max_retries, 1)


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
