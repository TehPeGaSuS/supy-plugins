###
# Copyright (c) 2025, nuke
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
from unittest.mock import Mock, patch


class PollinationsTestCase(PluginTestCase):
    plugins = ('Pollinations',)

    def testTextModelAliasesRemainValidFallbacks(self):
        plugin = self.irc.getCallback('Pollinations')
        response = Mock(status_code=200)
        response.json.return_value = [
            {'name': 'openai/gpt-5-nano', 'aliases': ['openai-fast']},
            {'id': 'google/gemini-2.5-flash'},
            'legacy-model',
        ]
        with patch.object(plugin.session, 'get', return_value=response):
            models = plugin._get_valid_text_models()

        self.assertEqual(models, {
            'openai/gpt-5-nano', 'openai-fast',
            'google/gemini-2.5-flash', 'legacy-model',
        })


def _response(status, data):
    response = Mock(status_code=status, text=str(data))
    response.json.return_value = data
    return response


def _chat_response(content):
    return _response(200, {'choices': [{'message': {'content': content},
                                        'finish_reason': 'stop'}]})


class PollinationsSearchTestCase(ChannelPluginTestCase):
    plugins = ('Pollinations',)
    config = {
        'supybot.plugins.Pollinations.tavily_api_key': 'tvly-test',
        'supybot.plugins.Pollinations.searxng_url': 'http://127.0.0.1:8888/',
        'supybot.plugins.Pollinations.search_thinking': '',
        'supybot.plugins.Pollinations.search_cooldown': 0,
        'supybot.plugins.Pollinations.search_shorten_urls': False,
        'supybot.plugins.Pollinations.context_lines': 0,
        'supybot.plugins.Pollinations.nick_include': False,
    }

    def setUp(self):
        super().setUp()
        self.plugin = self.irc.getCallback('Pollinations')
        self.plugin._search_day = (None, 0)

    def testTavilyAnswerWithSource(self):
        tavily = _response(200, {
            'answer': 'Linux 6.17 is the latest stable kernel.',
            'results': [{'title': 'kernel.org', 'url': 'https://kernel.org/',
                         'content': 'The Linux Kernel Archives'}],
        })
        with patch.object(self.plugin.session, 'post', return_value=tavily) as post:
            self.assertResponse('pollinations search latest kernel',
                                '[T] Linux 6.17 is the latest stable kernel. | https://kernel.org/')
        url = post.call_args[0][0]
        self.assertEqual(url, 'https://api.tavily.com/search')
        kwargs = post.call_args[1]
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer tvly-test')
        self.assertEqual(kwargs['json']['query'], 'latest kernel')
        self.assertEqual(kwargs['json']['search_depth'], 'basic')
        self.assertTrue(kwargs['json']['include_answer'])

    def testTavilyRewriteUsesTextModel(self):
        tavily = _response(200, {
            'answer': 'ignored',
            'results': [{'title': 'kernel.org', 'url': 'https://kernel.org/',
                         'content': 'Latest stable: 6.17'}],
        })
        calls = []

        def post(url, **kwargs):
            calls.append((url, kwargs))
            if 'tavily' in url:
                return tavily
            return _chat_response('It is 6.17.')

        with conf.supybot.plugins.Pollinations.tavily_rewrite.context(True):
            with patch.object(self.plugin.session, 'post', side_effect=post):
                self.assertResponse('pollinations search latest kernel', '[T] It is 6.17. | https://kernel.org/')
        self.assertFalse(calls[0][1]['json']['include_answer'])
        chat = calls[1][1]['json']
        self.assertEqual(chat['model'], 'openai-fast')
        system = '\n'.join(m['content'] for m in chat['messages'] if m['role'] == 'system')
        self.assertIn('[1] kernel.org (https://kernel.org/)', system)
        self.assertIn('Latest stable: 6.17', system)

    def testFallsBackToSearxng(self):
        searx = _response(200, {'results': [
            {'title': 'Limnoria', 'url': 'https://limnoria.net/', 'content': 'A Python IRC bot'}]})

        def post(url, **kwargs):
            if 'tavily' in url:
                return _response(432, {'detail': {'error': 'plan limit'}})
            return _chat_response('Limnoria is a Python IRC bot.')

        with patch.object(self.plugin.session, 'post', side_effect=post), \
                patch.object(self.plugin.session, 'get', return_value=searx) as get:
            self.assertResponse('pollinations search limnoria',
                                '[S] Limnoria is a Python IRC bot. | https://limnoria.net/')
        self.assertEqual(get.call_args[0][0], 'http://127.0.0.1:8888/search')
        self.assertEqual(get.call_args[1]['params']['format'], 'json')

    def testAllBackendsFailRefundsDailyCount(self):
        with patch.object(self.plugin.session, 'post', return_value=_response(500, {})), \
                patch.object(self.plugin.session, 'get', return_value=_response(403, {})):
            self.assertResponse('pollinations search anything',
                                'Web search is unavailable right now, please try again later.')
        self.assertEqual(self.plugin._search_day[1], 0)

    def testEmptyKeyAndUrlSkipBackends(self):
        with conf.supybot.plugins.Pollinations.tavily_api_key.context(''), \
                conf.supybot.plugins.Pollinations.searxng_url.context(''), \
                patch.object(self.plugin.session, 'post') as post, \
                patch.object(self.plugin.session, 'get') as get:
            self.assertResponse('pollinations search anything',
                                'Web search is unavailable right now, please try again later.')
        post.assert_not_called()
        get.assert_not_called()

    def testDailyLimit(self):
        tavily = _response(200, {'answer': 'Yes.', 'results': []})
        with conf.supybot.plugins.Pollinations.search_daily_limit.context(1), \
                patch.object(self.plugin.session, 'post', return_value=tavily):
            self.assertResponse('pollinations search one', '[T] Yes.')
            self.assertResponse('pollinations search two',
                                'Daily search limit reached (1). It resets at 00:00 UTC.')

    def testCooldown(self):
        tavily = _response(200, {'answer': 'Yes.', 'results': []})
        with conf.supybot.plugins.Pollinations.search_cooldown.context(30), \
                patch.object(self.plugin.session, 'post', return_value=tavily):
            self.assertResponse('pollinations search one', '[T] Yes.')
            self.assertRegexp('pollinations search two', r'^Please wait \d+s before searching again\.$')

    def testShortensSourceUrl(self):
        tavily = _response(200, {'answer': 'Yes.', 'results': [
            {'title': 'Long', 'url': 'https://example.com/a/very/long/path', 'content': ''}]})
        isgd = Mock(status_code=200, text='https://is.gd/abc123\n')

        def post(url, **kwargs):
            return isgd if 'is.gd' in url else tavily

        with conf.supybot.plugins.Pollinations.search_shorten_urls.context(True), \
                patch.object(self.plugin.session, 'post', side_effect=post):
            self.assertResponse('pollinations search long', '[T] Yes. | https://is.gd/abc123')

    def testHideSources(self):
        tavily = _response(200, {'answer': 'Yes.', 'results': [
            {'title': 'kernel.org', 'url': 'https://kernel.org/', 'content': ''}]})
        with conf.supybot.plugins.Pollinations.search_sources.context(0), \
                patch.object(self.plugin.session, 'post', return_value=tavily):
            self.assertResponse('pollinations search kernel', '[T] Yes.')

    def testLongAnswerSplitByMoresInstant(self):
        answer = ' '.join(['word%d' % i for i in range(150)])
        tavily = _response(200, {'answer': answer, 'results': []})
        with conf.supybot.reply.mores.instant.context(3), \
                patch.object(self.plugin.session, 'post', return_value=tavily):
            replies = [self.getMsg('pollinations search long').args[1]]
            m = self.irc.takeMsg()
            while m is not None:
                replies.append(m.args[1])
                m = self.irc.takeMsg()
        self.assertGreater(len(replies), 1)
        joined = ' '.join(replies)
        self.assertIn('word0', replies[0])
        self.assertIn('word149', joined)
        self.assertNotIn('more message', joined)

    def testPollinationsBackendTag(self):
        with conf.supybot.plugins.Pollinations.search_backend.context(['pollinations']), \
                patch.object(self.plugin.session, 'post', return_value=_chat_response('Paid answer.')) as post:
            self.assertResponse('pollinations search kernel', '[P] Paid answer.')
        self.assertEqual(post.call_args[1]['json']['model'], 'sonar')

    def testSearchUsage(self):
        usage = _response(200, {'account': {'current_plan': 'Researcher',
                                            'plan_usage': 150, 'plan_limit': 1000}})
        with patch.object(self.plugin.session, 'get', return_value=usage) as get:
            self.assertResponse('searchusage',
                                'Today: 0/30 searches | Tavily: 150/1000 credits used '
                                '(850 left, plan Researcher)')
        self.assertEqual(get.call_args[0][0], 'https://api.tavily.com/usage')


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
