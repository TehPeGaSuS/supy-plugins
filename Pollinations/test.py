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
import time


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
        with self.plugin.dict_lock:
            self.plugin._search_stats = {'day': None, 'searches': 0, 'pollinations_today': 0,
                                         'tavily_today': 0, 'month': None,
                                         'tavily_credits': 0, 'tavily_searches': 0}

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
        self.assertEqual(kwargs['json']['include_answer'], 'basic')
        self.assertTrue(kwargs['json']['include_usage'])

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
        self.assertIn('Current date and time: %s' % time.strftime('%A, %Y-%m-%d', time.gmtime()), system)
        self.assertIn('never use clocks or dates from these results', system)

    def testSnippetLength(self):
        tavily = _response(200, {'results': [
            {'title': 'Long', 'url': 'https://example.com/', 'content': 'a' * 1500 + 'TAIL'}]})
        calls = []

        def post(url, **kwargs):
            calls.append(kwargs)
            return tavily if 'tavily' in url else _chat_response('Ok.')

        with conf.supybot.plugins.Pollinations.tavily_rewrite.context(True), \
                patch.object(self.plugin.session, 'post', side_effect=post):
            self.assertResponse('pollinations search long', '[T] Ok. | https://example.com/')
            system = '\n'.join(m['content'] for m in calls[1]['json']['messages'] if m['role'] == 'system')
            self.assertIn('a' * 1000, system)
            self.assertNotIn('a' * 1001, system)
            with conf.supybot.plugins.Pollinations.search_snippet_length.context(2000):
                calls.clear()
                self.assertResponse('pollinations search long', '[T] Ok. | https://example.com/')
            system = '\n'.join(m['content'] for m in calls[1]['json']['messages'] if m['role'] == 'system')
            self.assertIn('TAIL', system)

    def testReasoningEffortSentAndDroppedOn400(self):
        tavily = _response(200, {'results': [{'title': 'T', 'url': 'https://example.com/', 'content': 'x'}]})
        chats = []

        def post(url, **kwargs):
            if 'tavily' in url:
                return tavily
            chats.append(dict(kwargs['json']))
            if 'reasoning_effort' in kwargs['json']:
                return _response(400, {'error': 'unknown parameter'})
            return _chat_response('Ok.')

        with conf.supybot.plugins.Pollinations.tavily_rewrite.context(True), \
                patch.object(self.plugin.session, 'post', side_effect=post):
            self.assertResponse('pollinations search x', '[T] Ok. | https://example.com/')
        self.assertEqual(chats[0]['reasoning_effort'], 'low')
        self.assertNotIn('reasoning_effort', chats[1])
        self.assertEqual(chats[0]['model'], chats[1]['model'])
        system = '\n'.join(m['content'] for m in chats[0]['messages'] if m['role'] == 'system')
        self.assertIn("never mention the results", system)
        self.assertIn("never ask the user questions", system)
        self.assertIn("rather than refusing", system)

    def testChatHasNoReasoningEffort(self):
        with patch.object(self.plugin.session, 'post', return_value=_chat_response('Hi.')) as post:
            self.assertResponse('pollinations chat hello', 'Hi.')
        self.assertNotIn('reasoning_effort', post.call_args[1]['json'])

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

    def testSearxngRecentRange(self):
        three = _response(200, {'results': [
            {'title': 'Marquez wins Japanese MotoGP', 'url': 'https://example.com/%d' % i, 'content': ''}
            for i in range(3)]})
        with conf.supybot.plugins.Pollinations.tavily_api_key.context(''), \
                patch.object(self.plugin.session, 'post', return_value=_chat_response('Marquez.')), \
                patch.object(self.plugin.session, 'get', return_value=three) as get:
            self.assertResponse('pollinations search who won the last MotoGP?', '[S] Marquez. | https://example.com/0')
            self.assertEqual(get.call_count, 1)
            self.assertEqual(get.call_args[1]['params']['time_range'], 'week')
            get.reset_mock()
            self.assertResponse('pollinations search who is Valentino Rossi', '[S] Marquez. | https://example.com/0')
            self.assertNotIn('time_range', get.call_args[1]['params'])

    def testSearxngRecentRangeWidensWhenThin(self):
        one = _response(200, {'results': [{'title': 'Old', 'url': 'https://example.com/old', 'content': ''}]})
        three = _response(200, {'results': [
            {'title': 'R', 'url': 'https://example.com/%d' % i, 'content': ''} for i in range(3)]})
        with conf.supybot.plugins.Pollinations.tavily_api_key.context(''), \
                patch.object(self.plugin.session, 'post', return_value=_chat_response('Ok.')), \
                patch.object(self.plugin.session, 'get', side_effect=[one, three]) as get:
            self.assertResponse('pollinations search latest kernel', '[S] Ok. | https://example.com/0')
        self.assertEqual(get.call_args_list[0][1]['params']['time_range'], 'week')
        self.assertNotIn('time_range', get.call_args_list[1][1]['params'])

    def testAllBackendsFailRefundsDailyCount(self):
        with patch.object(self.plugin.session, 'post', return_value=_response(500, {})), \
                patch.object(self.plugin.session, 'get', return_value=_response(403, {})):
            self.assertResponse('pollinations search anything',
                                'Web search is unavailable right now, please try again later.')
        self.assertEqual(self.plugin._search_stats['searches'], 0)

    def testEmptyKeyAndUrlSkipBackends(self):
        with conf.supybot.plugins.Pollinations.tavily_api_key.context(''), \
                conf.supybot.plugins.Pollinations.searxng_url.context(''), \
                patch.object(self.plugin.session, 'post') as post, \
                patch.object(self.plugin.session, 'get') as get:
            self.assertResponse('pollinations search anything',
                                'Web search is unavailable right now, please try again later.')
        post.assert_not_called()
        get.assert_not_called()

    def testDailyLimitSkipsTavilyForSearxng(self):
        tavily = _response(200, {'answer': 'Yes.', 'results': []})
        searx = _response(200, {'results': [
            {'title': 'Limnoria', 'url': 'https://limnoria.net/', 'content': 'A Python IRC bot'}]})

        def post(url, **kwargs):
            return tavily if 'tavily' in url else _chat_response('From SearXNG.')

        with conf.supybot.plugins.Pollinations.tavily_daily_limit.context(1), \
                patch.object(self.plugin.session, 'post', side_effect=post) as posted, \
                patch.object(self.plugin.session, 'get', return_value=searx):
            self.assertResponse('pollinations search one', '[T] Yes.')
            self.assertResponse('pollinations search two', '[S] From SearXNG. | https://limnoria.net/')
            self.assertResponse('pollinations search three', '[S] From SearXNG. | https://limnoria.net/')
        tavily_calls = [c for c in posted.call_args_list if 'tavily' in c[0][0]]
        self.assertEqual(len(tavily_calls), 1)
        self.assertEqual(self.plugin._search_stats['tavily_today'], 1)
        self.assertEqual(self.plugin._search_stats['searches'], 3)

    def testDailyLimitWithSearxngDown(self):
        tavily = _response(200, {'answer': 'Yes.', 'results': []})
        with conf.supybot.plugins.Pollinations.tavily_daily_limit.context(1), \
                patch.object(self.plugin.session, 'post', return_value=tavily), \
                patch.object(self.plugin.session, 'get', return_value=_response(502, {})):
            self.assertResponse('pollinations search one', '[T] Yes.')
            self.assertResponse('pollinations search two',
                                'Daily search limit reached. It resets at 00:00 UTC.')

    def testPollinationsDailyLimit(self):
        with conf.supybot.plugins.Pollinations.pollinations_daily_limit.context(1), \
                conf.supybot.plugins.Pollinations.search_backend.context(['pollinations']), \
                patch.object(self.plugin.session, 'post', return_value=_chat_response('Paid.')):
            self.assertResponse('pollinations search one', '[P] Paid.')
            self.assertResponse('pollinations search two',
                                'Daily search limit reached. It resets at 00:00 UTC.')

    def testSeparateLimitsChain(self):
        # sonar 1/day, then Tavily 1/day, then SearXNG with no limit
        tavily = _response(200, {'answer': 'From Tavily.', 'results': []})
        searx = _response(200, {'results': [{'title': 'X', 'url': 'https://x.example/', 'content': 'x'}]})

        def post(url, **kwargs):
            if 'tavily' in url:
                return tavily
            model = kwargs['json']['model']
            return _chat_response('From sonar.' if model == 'sonar' else 'From SearXNG.')

        with conf.supybot.plugins.Pollinations.pollinations_daily_limit.context(1), \
                conf.supybot.plugins.Pollinations.tavily_daily_limit.context(1), \
                conf.supybot.plugins.Pollinations.search_backend.context(['pollinations', 'tavily', 'searxng']), \
                patch.object(self.plugin.session, 'post', side_effect=post), \
                patch.object(self.plugin.session, 'get', return_value=searx):
            self.assertResponse('pollinations search one', '[P] From sonar.')
            self.assertResponse('pollinations search two', '[T] From Tavily.')
            self.assertResponse('pollinations search three', '[S] From SearXNG. | https://x.example/')
            self.assertResponse('pollinations search four', '[S] From SearXNG. | https://x.example/')
        stats = self.plugin._search_stats
        self.assertEqual((stats['pollinations_today'], stats['tavily_today'], stats['searches']), (1, 1, 4))

    def testPollinationsFailureFallsThrough(self):
        tavily = _response(200, {'answer': 'From Tavily.', 'results': []})

        def post(url, **kwargs):
            if 'tavily' in url:
                return tavily
            return _response(402, {'error': 'insufficient paid balance'})

        with conf.supybot.plugins.Pollinations.search_backend.context(['pollinations', 'tavily']), \
                patch.object(self.plugin.session, 'get', return_value=_response(500, {})), \
                patch.object(self.plugin.session, 'post', side_effect=post):
            self.assertResponse('pollinations search one', '[T] From Tavily.')
        # the failed paid search is not counted
        self.assertEqual(self.plugin._search_stats['pollinations_today'], 0)

    def testPollinationsFailureLastBackendReplies(self):
        with conf.supybot.plugins.Pollinations.search_backend.context(['pollinations']), \
                patch.object(self.plugin.session, 'get', return_value=_response(500, {})), \
                patch.object(self.plugin.session, 'post', return_value=_response(402, {})):
            self.assertResponse('pollinations search one',
                                'The AI service is currently unavailable, please try again in a moment.')

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

    def testTavilyAnswerAdvanced(self):
        tavily = _response(200, {'answer': 'Long answer.', 'results': []})
        with conf.supybot.plugins.Pollinations.tavily_answer.context('advanced'), \
                patch.object(self.plugin.session, 'post', return_value=tavily) as post:
            self.assertResponse('pollinations search x', '[T] Long answer.')
        self.assertEqual(post.call_args[1]['json']['include_answer'], 'advanced')
        self.assertEqual(post.call_args[1]['json']['search_depth'], 'basic')

    def testTavilyCreditsCounted(self):
        reported = _response(200, {'answer': 'Yes.', 'results': [], 'usage': {'credits': 1}})
        unreported = _response(200, {'answer': 'Yes.', 'results': []})
        with patch.object(self.plugin.session, 'post', return_value=reported):
            self.assertResponse('pollinations search one', '[T] Yes.')
        # Without a usage field the depth decides: advanced costs 2
        with conf.supybot.plugins.Pollinations.tavily_depth.context('advanced'), \
                patch.object(self.plugin.session, 'post', return_value=unreported):
            self.assertResponse('pollinations search two', '[T] Yes.')
        self.assertEqual(self.plugin._search_stats['tavily_credits'], 3)
        self.assertEqual(self.plugin._search_stats['tavily_searches'], 2)
        self.assertEqual(self.plugin._search_stats['searches'], 2)
        self.assertEqual(self.plugin._search_stats['tavily_today'], 2)

    def testFailedTavilyCostsNothing(self):
        with patch.object(self.plugin.session, 'post', return_value=_response(432, {})), \
                patch.object(self.plugin.session, 'get', return_value=_response(403, {})):
            self.assertResponse('pollinations search x',
                                'Web search is unavailable right now, please try again later.')
        self.assertEqual(self.plugin._search_stats['tavily_credits'], 0)

    def testSearchStatsPersist(self):
        tavily = _response(200, {'answer': 'Yes.', 'results': [], 'usage': {'credits': 1}})
        with patch.object(self.plugin.session, 'post', return_value=tavily):
            self.assertResponse('pollinations search one', '[T] Yes.')
        saved = self.plugin._load_search_stats()
        self.assertEqual(saved['searches'], 1)
        self.assertEqual(saved['tavily_credits'], 1)
        self.assertEqual(saved['day'], time.strftime('%Y-%m-%d', time.gmtime()))

    def testHandEditedStatsFile(self):
        with open(self.plugin._search_stats_path(), 'w') as f:
            f.write('{"day": "2026-10-21", "searches": "5", "capped": 5, "tavily_today": 5.0,'
                    ' "month": "2026-10", "tavily_credits": "x", "tavily_searches": "5"}')
        stats = self.plugin._load_search_stats()
        # an old "capped" field is ignored
        self.assertEqual(stats, {'day': '2026-10-21', 'searches': 5, 'pollinations_today': 0,
                                 'tavily_today': 5, 'month': '2026-10',
                                 'tavily_credits': 0, 'tavily_searches': 5})
        # and a search on top of it counts normally
        self.plugin._search_stats = stats
        with self.plugin.dict_lock:
            self.plugin._roll_search_stats()
        tavily = _response(200, {'answer': 'Yes.', 'results': [], 'usage': {'credits': 1}})
        with patch.object(self.plugin.session, 'post', return_value=tavily):
            self.assertResponse('pollinations search one', '[T] Yes.')

    def testNewMonthResetsCredits(self):
        with self.plugin.dict_lock:
            self.plugin._search_stats.update(day='2000-01-31', searches=5, pollinations_today=5,
                                             tavily_today=5, month='2000-01',
                                             tavily_credits=999, tavily_searches=999)
            self.plugin._roll_search_stats()
            stats = dict(self.plugin._search_stats)
        self.assertEqual((stats['searches'], stats['pollinations_today'], stats['tavily_today'],
                          stats['tavily_credits'], stats['tavily_searches']), (0, 0, 0, 0, 0))

    def testBareCitationsRemoved(self):
        clean = self.plugin._clean_markdown
        self.assertEqual(clean('Jorge Martín third [3][15].'), 'Jorge Martín third.')
        self.assertEqual(clean('Won in 2026 [1, 2] at Mandalika [4-6].'), 'Won in 2026 at Mandalika.')
        self.assertEqual(clean('Rated [PG] in [x]'), 'Rated [PG] in [x]')

    def testSearchUsage(self):
        with self.plugin.dict_lock:
            self.plugin._roll_search_stats()
            self.plugin._search_stats.update(searches=5, pollinations_today=3, tavily_today=2,
                                             tavily_credits=3, tavily_searches=2)
        usage = _response(200, {'account': {'current_plan': 'Researcher',
                                            'plan_usage': 150, 'plan_limit': 1000}})
        with conf.supybot.plugins.Pollinations.search_backend.context(['pollinations', 'tavily', 'searxng']), \
                patch.object(self.plugin.session, 'get', return_value=usage) as get:
            self.assertResponse('searchusage',
                                'Today: 5 searches, Pollinations 3/20, Tavily 2/30'
                                ' | Tavily this month (bot): 3 credits in 2 searches'
                                ' | Tavily account: 150/1000 credits used (850 left, plan Researcher; may lag)')
        self.assertEqual(get.call_args[0][0], 'https://api.tavily.com/usage')


class PollinationsUsageTestCase(PluginTestCase):
    plugins = ('Pollinations',)
    config = {'supybot.plugins.Pollinations.api_token': 'sk_test'}

    def setUp(self):
        super().setUp()
        self.plugin = self.irc.getCallback('Pollinations')

    def _get(self, balance, usage):
        def get(url, **kwargs):
            self.assertEqual(kwargs['headers']['Authorization'], 'Bearer sk_test')
            return balance if url.endswith('/account/balance') else usage
        return get

    def testPolliUsage(self):
        balance = _response(200, {'balance': 3.5, 'accountBalance': {'total': 3.5, 'tier': 3.25, 'paid': 0.25}})
        usage = _response(200, {'usage': [
            {'model': 'openai-fast', 'cost_usd': 0.0001},
            {'model': 'openai-fast', 'cost_usd': 0.0002},
            {'model': 'flux', 'cost_usd': 0.001},
        ]})
        with patch.object(self.plugin.session, 'get', side_effect=self._get(balance, usage)) as get:
            self.assertResponse('polliusage',
                                'Pollen: 3.5000 left (Quest 3.2500, paid 0.2500) | '
                                'Last 24h (this key): 3 requests, $0.0013 (openai-fast 2, flux 1)')
        usage_call = [c for c in get.call_args_list if c[0][0].endswith('/key/usage')][0]
        self.assertEqual(usage_call[1]['params']['days'], 1)

    def testPolliUsageWithoutAccountPermission(self):
        balance = _response(403, {})
        usage = _response(200, {'usage': []})
        with patch.object(self.plugin.session, 'get', side_effect=self._get(balance, usage)):
            self.assertResponse('polliusage',
                                'Pollen: balance needs the account:usage permission on the key '
                                '(enter.pollinations.ai/keys) | Last 24h (this key): 0 requests, $0.0000')

    def testPolliUsageNoToken(self):
        with conf.supybot.plugins.Pollinations.api_token.context(''):
            self.assertResponse('polliusage', 'No Pollinations api_token is set.')


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
