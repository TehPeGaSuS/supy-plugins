###
# Copyright (c) 2023, oddluck
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

from types import SimpleNamespace

import openai

from supybot.test import *

from . import plugin as orplugin

GROQ = "https://api.groq.com/openai/v1"


class FakeOpenAI:
    """Stands in for openai.OpenAI; records requests, returns `response`."""
    calls = []
    response = None

    def __init__(self, **kwargs):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create))

    def _create(self, **params):
        FakeOpenAI.calls.append(params)
        if isinstance(FakeOpenAI.response, Exception):
            raise FakeOpenAI.response
        return FakeOpenAI.response


class FakeAnnotation:
    def __init__(self, url):
        self.url = url

    def model_dump(self):
        return {"type": "url_citation", "url_citation": {"url": self.url}}


def completion(content, finish="stop", annotations=None):
    message = SimpleNamespace(content=content, annotations=annotations)
    return SimpleNamespace(
        id="gen-1", model="m", created=0, usage=None,
        choices=[SimpleNamespace(message=message, finish_reason=finish)])


def status_error(cls, status, message):
    e = cls.__new__(cls)
    e.status_code = status
    e.message = message
    e.body = {"error": {"message": message}}
    return e


class OpenRouterTestCase(PluginTestCase):
    plugins = ("OpenRouter",)

    def setUp(self):
        super().setUp()
        self._real_openai = orplugin.OpenAI
        orplugin.OpenAI = FakeOpenAI
        FakeOpenAI.calls = []
        FakeOpenAI.response = completion("hello")
        self.irc.getCallback("OpenRouter").history.clear()

    def tearDown(self):
        orplugin.OpenAI = self._real_openai
        super().tearDown()

    def setting(self, name):
        return conf.supybot.plugins.OpenRouter.get(name)

    def testRequestShape(self):
        self.assertResponse("chat hi", "hello")
        params = FakeOpenAI.calls[-1]
        self.assertEqual(params["model"], "openrouter/free")
        roles = [m["role"] for m in params["messages"]]
        self.assertEqual(roles, ["system", "user"])
        self.assertEqual(params["messages"][-1]["content"], "test: hi")
        self.assertEqual(params["max_tokens"], 1000)
        # Sampling defaults and OpenRouter extras are left out
        for name in ("temperature", "top_p", "presence_penalty",
                     "frequency_penalty", "extra_body", "reasoning_effort"):
            self.assertNotIn(name, params)

    def testNonDefaultSamplingSent(self):
        self.assertResponse("chat --temp 0.3 hi", "hello")
        self.assertEqual(FakeOpenAI.calls[-1]["temperature"], 0.3)

    def testHistoryAfterSystemPrompt(self):
        self.assertResponse("chat one", "hello")
        FakeOpenAI.response = completion("second")
        self.assertResponse("chat two", "second")
        roles = [m["role"] for m in FakeOpenAI.calls[-1]["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])

    def testHistoryCountsExchanges(self):
        with self.setting("max_history").context(1):
            for word in ("one", "two", "three"):
                self.assertResponse(f"chat {word}", "hello")
            contents = [m["content"] for m in FakeOpenAI.calls[-1]["messages"]]
            self.assertEqual(contents[1:], ["test: two", "hello", "test: three"])

    def testHistoryDisabled(self):
        with self.setting("max_history").context(0):
            self.assertResponse("chat one", "hello")
            self.assertResponse("chat two", "hello")
            self.assertEqual(len(FakeOpenAI.calls[-1]["messages"]), 2)

    def testOutOfTokens(self):
        FakeOpenAI.response = completion(None, finish="length")
        self.assertRegexp("chat hi", "Error: .*ran out of tokens")

    def testEmptyReply(self):
        FakeOpenAI.response = completion("   ")
        self.assertRegexp("chat hi", "Error: .*empty reply")

    def testNoChoices(self):
        FakeOpenAI.response = SimpleNamespace(choices=[])
        self.assertRegexp("chat hi", "Error: .*no reply")

    def testRateLimited(self):
        FakeOpenAI.response = status_error(
            openai.RateLimitError, 429, "slow down")
        self.assertRegexp("chat hi", r"Error: Rate limited by the API \(429\): slow down")

    def testApiError(self):
        FakeOpenAI.response = status_error(
            openai.NotFoundError, 404, "No endpoints found")
        self.assertRegexp("chat hi", "Error: API error 404: No endpoints found")

    def testWebOffByDefault(self):
        self.assertResponse("chat latest news today", "hello")
        self.assertNotIn("extra_body", FakeOpenAI.calls[-1])
        self.assertRegexp("chat --web hi", "Error: .*web_mode is off")
        self.assertEqual(len(FakeOpenAI.calls), 1)

    def testWebAuto(self):
        with self.setting("web_mode").context("auto"):
            self.assertResponse("chat explain recursion", "hello")
            self.assertNotIn("extra_body", FakeOpenAI.calls[-1])
            self.assertResponse("chat latest news", "hello")
            self.assertIn("plugins", FakeOpenAI.calls[-1]["extra_body"])
            self.assertResponse("chat --no-web latest news", "hello")
            self.assertNotIn("extra_body", FakeOpenAI.calls[-1])

    def testWebOptin(self):
        with self.setting("web_mode").context("optin"):
            self.assertResponse("chat latest news", "hello")
            self.assertNotIn("extra_body", FakeOpenAI.calls[-1])
            self.assertResponse("chat --web hi", "hello")
            self.assertIn("plugins", FakeOpenAI.calls[-1]["extra_body"])

    def testWebOnOpenRouter(self):
        with self.setting("web_mode").context("always"):
            self.assertResponse("chat hi", "hello")
        extra = FakeOpenAI.calls[-1]["extra_body"]
        web = extra["plugins"][0]
        self.assertEqual(web["id"], "web")
        self.assertEqual(web["max_results"], 5)
        self.assertNotIn("engine", web)
        self.assertEqual(extra["web_search_options"],
                         {"search_context_size": "medium"})

    def testWebEngine(self):
        with self.setting("web_engine").context("parallel"), \
                self.setting("web_mode").context("optin"):
            self.assertResponse("chat --web hi", "hello")
        self.assertEqual(
            FakeOpenAI.calls[-1]["extra_body"]["plugins"][0]["engine"],
            "parallel")

    def testWebRefusedElsewhere(self):
        with conf.supybot.plugins.OpenRouter.base_url.context(GROQ):
            with self.setting("web_mode").context("optin"):
                self.assertRegexp("chat --web hi", "Error: .*only works")
            self.assertEqual(FakeOpenAI.calls, [])
            # auto mode skips it quietly
            with self.setting("web_mode").context("auto"):
                self.assertResponse("chat latest news", "hello")
            self.assertNotIn("extra_body", FakeOpenAI.calls[-1])

    def testReasoningEffort(self):
        with self.setting("reasoning_effort").context("low"):
            self.assertResponse("chat hi", "hello")
            self.assertEqual(FakeOpenAI.calls[-1]["extra_body"]["reasoning"],
                             {"effort": "low"})
            self.assertNotIn("reasoning_effort", FakeOpenAI.calls[-1])
            with conf.supybot.plugins.OpenRouter.base_url.context(GROQ):
                self.assertResponse("chat hi", "hello")
            self.assertEqual(FakeOpenAI.calls[-1]["reasoning_effort"], "low")
            self.assertNotIn("extra_body", FakeOpenAI.calls[-1])

    def testSourcesShown(self):
        FakeOpenAI.response = completion(
            "answer", annotations=[FakeAnnotation("https://a.example/x"),
                                   FakeAnnotation("https://a.example/x")])
        with self.setting("web_mode").context("always"), \
                self.setting("web_show_sources").context(True):
            self.assertResponse("chat hi", "answer Sources: https://a.example/x")

    def testSourcesStripped(self):
        FakeOpenAI.response = completion(
            "answer [a.example](https://a.example/x) see https://b.example",
            annotations=[FakeAnnotation("https://a.example/x")])
        with self.setting("web_mode").context("always"):
            self.assertResponse("chat hi", "answer see")

    def testBlacklist(self):
        self.assertRegexp("chat --model openai/o1-pro hi", "Error: .*disallowed")
        self.assertEqual(FakeOpenAI.calls, [])


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
