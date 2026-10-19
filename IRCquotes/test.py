###
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

import os
import tempfile

import supybot.utils as utils
import supybot.ircmsgs as ircmsgs
import supybot.ircutils as ircutils

from supybot.test import *

from . import plugin as ircquotes_plugin

class _FakeHttpHandler:
    """Minimal stand-in for the bits of SupyHTTPRequestHandler that
    doGetOrHead() writes to, without needing a live socket/server."""
    def __init__(self):
        self.status = None
        self.headers = []
        self.chunks = []

    def send_response(self, code):
        self.status = code

    def send_header(self, name, value):
        self.headers.append((name, value))

    def end_headers(self):
        pass

    def write(self, b):
        self.chunks.append(b)

    @property
    def body(self):
        return b''.join(self.chunks).decode('utf-8')

class IRCquotesTestCase(ChannelPluginTestCase):
    plugins = ('IRCquotes', 'User')

    def setUp(self):
        ChannelPluginTestCase.setUp(self)
        # Quotes are opt-in (disabled by default); enable them for the
        # test channel so the other tests don't have to.
        conf.supybot.plugins.IRCquotes.enabled.setValue(True)
        # Flood control and multi-line capture get in the way of most
        # tests; the tests for them turn them back on.
        conf.supybot.plugins.IRCquotes.antiflood.setValue(False)
        conf.supybot.plugins.IRCquotes.multilineAdd.setValue(False)
        conf.supybot.databases.plugins.requireRegistration.setValue(False)
        # Most tests add short quotes; testMinQuoteLength checks the limits.
        conf.supybot.plugins.IRCquotes.minQuoteChars.setValue(0)
        conf.supybot.plugins.IRCquotes.minQuoteWords.setValue(0)

    def _more(self):
        # The next message the bot sends after the one an assert* returned.
        m = self.irc.takeMsg()
        if m is None:
            return None
        prefix = self.nick + ': '
        return m.args[1][len(prefix):] if m.args[1].startswith(prefix) \
            else m.args[1]

    def _drain(self):
        while self.irc.takeMsg() is not None:
            pass

    def _feed(self, line, frm=None):
        # Feeds a line without waiting for an answer, unlike assert*.
        self.irc.feedMsg(ircmsgs.privmsg(self.channel, line,
                                         prefix=frm or self.prefix))

    def _command(self, line):
        self._feed(conf.supybot.reply.whenAddressedBy.chars()[0] + line)

    def _plain(self, s):
        return ircutils.stripFormatting(s)

    def testAddAndGet(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            self.assertNotError('addquote hello world')
            self.assertRegexp('quoteget 1', 'hello world')

    def testLastQuote(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            self.assertNotError('addquote first')
            self.assertNotError('addquote second')
            self.assertRegexp('lastquote', 'second')
            self.assertRegexp('lastquote 2', 'first')
            # The original's syntax: -1 is the one before the latest.
            self.assertRegexp('lastquote -1', 'first')
            self.assertRegexp('lastquote -2', "can't exceed -1")

    def testFindQuote(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            self.assertNotError('addquote a needle in a haystack')
            self.assertRegexp('findquote needle', '1 result has been found')
            self.assertTrue('a needle in a haystack' in self._more())
            # * and ? are plain characters, as in the original.
            self.assertRegexp('findquote *needle*', 'no results')

    def testFindQuoteWordsAndPhrases(self):
        self.assertNotError('addquote the quick brown fox')
        self.assertNotError('addquote the brown quick dog')
        self.assertNotError('addquote Ça fait du café')
        # Every word must be there, in any order...
        self.assertRegexp('findquote brown quick',
                          '2 results have been found: 1.*2')
        self._drain()
        # ...unless they're quoted together as an exact phrase.
        self.assertRegexp('findquote "quick brown"', '1 result')
        self._drain()
        # Case and accents don't matter.
        self.assertRegexp('findquote CAFE', '1 result')
        self._drain()
        self.assertRegexp('findquote ab', 'at least 3 characters')
        self.assertRegexp('findquote fox #elsewhere', 'switched their order')

    def testFindQuoteShowsRecent(self):
        for i in range(4):
            self.assertNotError('addquote needle number %d' % i)
        self.assertRegexp('findquote needle',
                          '4 results have been found: 1.*2.*3.*4')
        self.assertEqual(self._more(), 'Recent quotes:')
        # The 2 most recent (findQuoteRecent), newest first.
        self.assertTrue(self._plain(self._more()).startswith('[4] '))
        self.assertTrue(self._plain(self._more()).startswith('[3] '))
        self.assertEqual(self._more(), None)

    def testFindQuoteMaxResults(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            for i in range(5):
                self.assertNotError('addquote needle %d' % i)
            with conf.supybot.plugins.IRCquotes.findQuoteMaxResults.context(2):
                self.assertRegexp('findquote needle',
                                  'more than 2 results \\(precisely 5\\)')

    def testFindQuoteAll(self):
        cb = self.irc.getCallback('IRCquotes')
        cb.db.add(self.irc.network, '#other', time.time(), 'someone',
                  'a needle elsewhere')
        self.assertNotError('addquote a needle here')
        # #other isn't enabled... (enabled is set globally in setUp, so
        # turn it off just there).
        with conf.supybot.plugins.IRCquotes.enabled.get('#other').context(
                False):
            self.assertRegexp('findquote --all needle', '1 result has been '
                              'found on %s' % self.channel)
            self._drain()
            with conf.supybot.plugins.IRCquotes.readableChannels.context(
                    ['#other']):
                self.assertRegexp('findquote -all needle',
                                  '2 results have been found on the '
                                  'following channels: #other %s' %
                                  self.channel)
                self.assertEqual(self._more(), 'Recent quotes:')
                self.assertTrue(self._plain(self._more()).startswith(
                    '%s [1] a needle here' % self.channel))

    def testMinQuoteLength(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            with conf.supybot.plugins.IRCquotes.minQuoteChars.context(10):
                self.assertError('addquote short')
                self.assertNotError('addquote long enough now')
            with conf.supybot.plugins.IRCquotes.minQuoteWords.context(3):
                self.assertError('addquote two words')
                self.assertNotError('addquote this has three words')
        # The original's defaults: 10 characters and 3 words.
        cfg = conf.supybot.plugins.IRCquotes
        with cfg.minQuoteChars.context(cfg.minQuoteChars._default), \
                cfg.minQuoteWords.context(cfg.minQuoteWords._default):
            self.assertRegexp('addquote two words', "can't add quotes with "
                              "less than 10 characters or 3 words")
            self.assertNotError('addquote three whole words')

    def testVoteQuote(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            self.assertNotError('addquote votable quote')
            self.assertNotError('votequote 1 +')
            self.assertRegexp('quoteinfo 1', '1 like')
            self.assertError('votequote 1 +') # already voted that way
            self.assertNotError('votequote 1 0') # clear vote
            self.assertError('votequote 1 0') # nothing to clear
            self.assertNotError('votequote 1 -')
            self.assertRegexp('quoteinfo 1', '1 dislike')

    def testVoteQuoteDirectSwitch(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            self.assertNotError('addquote switchable quote')
            self.assertRegexp('votequote 1 +', 'Vote accepted.*rated 1 '
                              '\\(1 like, 0 dislike\\)')
            self.assertRegexp('quoteinfo 1', 'rating is 1 \\(1 like, 0 '
                              'dislike\\)')
            # Switch directly from + to - without clearing first.
            self.assertRegexp('votequote 1 -', 'modified')
            self.assertRegexp('quoteinfo 1', 'rating is -1 \\(0 like, 1 '
                              'dislike\\)')
            self.assertNotError('votequote 1 +')
            self.assertRegexp('quoteinfo 1', '\\(1 like, 0 dislike\\)')

    def testVoteQuoteWithoutDirectionShowsRating(self):
        self.assertNotError('addquote rate me')
        self.assertRegexp('votequote 1', 'rated 0 .*not yet rated')
        self.assertRegexp('quoteinfo 1', '\\(0 like, 0 dislike\\)')
        self.assertNotError('votequote 1 -')
        self.assertRegexp('votequote 1', 'rated -1 .*already disliked')

    def testVoteQuoteNickChangeDoesNotVoteTwice(self):
        self.assertNotError('addquote vote once')
        self.assertNotError('votequote 1 +')
        # Same ident and domain, other nick and host: still the same voter.
        other = 'othernick!~user@other.domain.tld'
        self.assertRegexp('votequote 1 +', 'already liked', frm=other)
        self.assertRegexp('votequote 1 +', 'Vote accepted',
                          frm='othernick!user@far.away.example.net')

    def testVoterMask(self):
        mask = ircquotes_plugin.voterMask
        self.assertEqual(mask('n!~id@a.b.c.d.example.com'),
                         '*!id@*.c.d.example.com')
        self.assertEqual(mask('n!id@host.example.com'),
                         '*!id@*.example.com')
        self.assertEqual(mask('n!id@192.168.1.20'), '*!id@192.168.1.*')
        self.assertEqual(mask('n!id@localhost'), '*!id@localhost')

    def testVoteQuoteSettings(self):
        self.assertNotError('addquote settings')
        with conf.supybot.plugins.IRCquotes.canChangeVote.context(False):
            self.assertError('votequote 1 0')
            self.assertNotError('votequote 1 +')
            self.assertRegexp('votequote 1 -', 'already liked')
        with conf.supybot.plugins.IRCquotes.votesEnabled.context(False):
            self.assertRegexp('votequote 1', 'disabled')
            self.assertNotRegexp('quoteinfo 1', 'rating')
        with conf.supybot.plugins.IRCquotes.requireVoteRegistration.context(
                True):
            self.assertRegexp('votequote 1 -', 'registered user')
            # Just looking doesn't need it.
            self.assertRegexp('votequote 1', 'rated 1')
        with conf.supybot.plugins.IRCquotes.canVoteExternalQuotes.context(
                False):
            self.assertRegexp('votequote 1 %s -' % self.channel, 'modified')
            self.assertRegexp('votequote %s 1 +' % self.channel,
                              'other channels', private=True)
            # Looking is still fine.
            self.assertRegexp('votequote 1 %s' % self.channel, 'rated -1',
                              private=True)

    def testVoteQuoteRequireAccount(self):
        self.assertNotError('addquote account')
        with conf.supybot.plugins.IRCquotes.requireVoteAccount.context(True):
            self.irc.state.nicksToAccounts[self.nick] = None
            self.assertRegexp('votequote 1 +', 'identify to services')
            self.irc.state.nicksToAccounts[self.nick] = 'someaccount'
            self.assertRegexp('votequote 1 +', 'Vote accepted')

    def testDelQuote(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            self.assertNotError('addquote to be deleted')
            self.assertRegexp('delquote 1', 'The quote #1 has been deleted')
            # Numbering is preserved: the id stays valid, but the content
            # is hidden instead of the quote vanishing entirely.
            self.assertRegexp('quoteget 1', "doesn't exist anymore, it has "
                              "been deleted by %s on" % self.nick)
            self.assertRegexp('quoteinfo 1', 'deleted by %s' % self.nick)
            self.assertRegexp('delquote 1', 'already been deleted')
            self.assertRegexp('votequote 1 +', "doesn't exist anymore")
            self.assertNotError('undelquote 1')
            self.assertRegexp('quoteget 1', 'to be deleted')
            self.assertRegexp('undelquote 1', "doesn't need to be restored")

    def testDelQuoteOnlyByAuthor(self):
        self.assertNotError('addquote mine')
        self.assertRegexp('delquote 1', 'not allowed.*added by %s' %
                          self.nick, frm='someoneelse!user@host.domain.tld')
        # Same nick, other host: still the author (the original compared
        # nicks).
        self.assertNotError('delquote 1', frm='%s!x@elsewhere' % self.nick)

    def testForceDelQuote(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            self.assertNotError('addquote to be removed')
            self.assertRegexp('forcedelquote 1', 'has been deleted')
            # A soft delete, credited to "an administrator" in public...
            self.assertRegexp('quoteget 1', 'deleted by an administrator')
            # ...with the details for ops, in private.
            m = self.getMsg('deletedquoteinfo 1')
            self.assertEqual(m.command, 'NOTICE')
            self.assertEqual(m.args[0], self.nick)
            self.assertTrue('(%s)' % self.prefix in m.args[1])
            self.assertTrue('to be removed' in self._more())
            self.assertNotError('undelquote 1')
            self.assertRegexp('deletedquoteinfo 1', "You'd rather use "
                              "quoteinfo")

    def testCancelQuote(self):
        self.assertNotError('addquote first')
        self.assertNotError('addquote second')
        self.assertRegexp('cancelquote 1', "doesn't match the latest")
        self.assertRegexp('cancelquote 2', 'latest quote has been canceled')
        self.assertTrue('second' in self._more())
        self.assertRegexp('quoteget 2', "doesn't exist yet \\(1 quote in")
        # The freed number goes to the next quote.
        self.assertRegexp('addquote third', '#2 has been added')

    def testPurgedQuoteNumber(self):
        cb = self.irc.getCallback('IRCquotes')
        for text in ('one', 'two', 'three'):
            cb.db.add(self.irc.network, self.channel, time.time(), 'x', text)
        cb.db.remove(self.irc.network, self.channel, 2)
        self.assertRegexp('quoteget 2', "doesn't exist anymore\\.")
        self.assertRegexp('quoteget 9', "doesn't exist yet")

    def testAddCapability(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            with conf.supybot.plugins.IRCquotes.addCapability.context('op'):
                noCapPrefix = ircutils.joinHostmask(
                    self.nick, 'user', '__no_testcap__.domain.tld')
                self.assertError('addquote nope, not an op',
                                  frm=noCapPrefix)

    def testRequireAddRegistrationDefaultsToOp(self):
        # With addCapability left empty, requireAddRegistration alone
        # should behave the same as addCapability = 'op'.
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            with conf.supybot.plugins.IRCquotes.requireAddRegistration.context(True):
                noCapPrefix = ircutils.joinHostmask(
                    self.nick, 'user', '__no_testcap__.domain.tld')
                self.assertError('addquote nope, not registered/op',
                                  frm=noCapPrefix)
                self.assertNotError('addquote yep, this passes')

    def testDisabled(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            with conf.supybot.plugins.IRCquotes.enabled.context(False):
                self.assertError('addquote nope')

    def testQuotePage(self):
        self.assertError('quotepage') # not configured by default
        with conf.supybot.plugins.IRCquotes.web.publicUrl.context(
                'https://quotes.example.com/ircquotes/'):
            # The base is set once; network and channel get appended
            # automatically to build the full page URL.
            self.assertResponse('quotepage',
                '%s Quotes: https://quotes.example.com/ircquotes/%s/%s/' % (
                    self.channel,
                    utils.web.urlquote(self.irc.network),
                    utils.web.urlquote(self.channel)))

    def testQuoteStatsShowsUrlWhenConfigured(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            self.assertNotError('addquote for stats')
        self.assertNotRegexp('quotestats', 'quotes.example.com')
        with conf.supybot.plugins.IRCquotes.web.publicUrl.context(
                'https://quotes.example.com/ircquotes/'):
            self.assertRegexp('quotestats', 'quotes.example.com')

    def testScheduleAutoRandQuote(self):
        # Regression test: _scheduleFor() used to call a nonexistent
        # schedule.schedule.count() and crash the moment a channel had a
        # non-zero autoRandQuoteInterval (e.g. right on plugin load).
        import supybot.schedule as schedule
        cb = self.irc.getCallback('IRCquotes')
        with conf.supybot.plugins.IRCquotes.autoRandQuoteInterval.context(60):
            cb._scheduleFor(self.irc, self.channel)
            name = cb._eventName(self.irc.network, self.channel)
            try:
                self.assertTrue(name in schedule.schedule.events)
                # Calling it again (as __init__/doJoin do) must not raise
                # either, and should just reschedule in place.
                cb._scheduleFor(self.irc, self.channel)
                self.assertTrue(name in schedule.schedule.events)
            finally:
                if name in schedule.schedule.events:
                    schedule.removeEvent(name)

    def testWebStyleCss(self):
        # Regression test: the web callback's routing only handled the
        # index page and per-channel listing paths, so a request for
        # /ircquotes/style.css (which every rendered page links to) fell
        # through to the "is this a channel?" branch and 404ed -- meaning
        # the page never actually got styled when hit directly.
        cb = self.irc.getCallback('IRCquotes')
        webcb = ircquotes_plugin.IRCquotesWebCallback()
        webcb._plugin = cb
        handler = _FakeHttpHandler()
        webcb.send_response = handler.send_response
        webcb.send_header = handler.send_header
        webcb.end_headers = handler.end_headers
        webcb.wfile = handler
        webcb.doGetOrHead(handler, '/style.css', True)
        self.assertEqual(handler.status, 200)
        self.assertTrue(('Content-type', 'text/css; charset=utf-8')
                         in handler.headers)
        self.assertTrue('quoteid' in handler.body)

    def testWebIndexCards(self):
        cb = self.irc.getCallback('IRCquotes')
        webcb = ircquotes_plugin.IRCquotesWebCallback()
        webcb._plugin = cb
        handler = _FakeHttpHandler()
        webcb.send_response = handler.send_response
        webcb.send_header = handler.send_header
        webcb.end_headers = handler.end_headers
        webcb.wfile = handler
        with conf.supybot.plugins.IRCquotes.web.channel.context(True):
            webcb.doGetOrHead(handler, '/', True)
        self.assertEqual(handler.status, 200)
        self.assertTrue('network-card' in handler.body)
        self.assertTrue(self.channel in handler.body)

    def testMultiNetworkIsolation(self):
        # The whole point of keying the database by (network, channel):
        # the same channel name on two different networks must not share
        # quotes or id numbering.
        cb = self.irc.getCallback('IRCquotes')
        idA = cb.db.add('NetworkA', '#software', time.time(), 'someone',
                         'hello from A')
        idB = cb.db.add('NetworkB', '#software', time.time(), 'someone',
                         'hello from B')
        self.assertEqual(idA, 1)
        self.assertEqual(idB, 1)
        recA = cb.db.get('NetworkA', '#software', 1)
        recB = cb.db.get('NetworkB', '#software', 1)
        self.assertEqual(recA.text, 'hello from A')
        self.assertEqual(recB.text, 'hello from B')
        self.assertEqual(cb.db.size('NetworkA', '#software'), 1)
        self.assertEqual(cb.db.size('NetworkB', '#software'), 1)

    def testChannelCaseIsNormalized(self):
        # Regression test: a PRIVMSG target's case (e.g. "#Software", as
        # actually used by the client) can differ from the case a channel
        # was joined/tracked under (e.g. "#software", used to build the
        # web UI's links). Both must resolve to the same stored quote.
        cb = self.irc.getCallback('IRCquotes')
        id_ = cb.db.add('NetworkA', '#Software', time.time(), 'someone',
                         'case test')
        self.assertEqual(cb.db.get('NetworkA', '#software', id_).text,
                          'case test')
        self.assertEqual(cb.db.size('NetworkA', '#SOFTWARE'), 1)

    def testExistingMixedCaseChannelsAreMigrated(self):
        # Rows written before this normalization existed (mixed-case
        # channel already on disk) must still be found after a fresh
        # QuotesDB() is opened on that file.
        fd, dbPath = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        try:
            db1 = ircquotes_plugin.QuotesDB(dbPath)
            db1._conn.execute(
                "INSERT INTO quotes (network, channel, id, at, by, text) "
                "VALUES ('NetworkA', '#Software', 1, 0, 'someone', "
                "'pre-existing')")
            db1._conn.commit()
            db1.close()
            db2 = ircquotes_plugin.QuotesDB(dbPath)
            try:
                self.assertEqual(
                    db2.get('NetworkA', '#software', 1).text,
                    'pre-existing')
            finally:
                db2.close()
        finally:
            os.remove(dbPath)

    def testWebChannelPageUsesUrlNetwork(self):
        # Regression test: the web page used to guess the network by
        # scanning world.ircs for the first Irc with a matching channel
        # name, which breaks the moment the same channel name is
        # web-enabled on more than one network. The network must now come
        # straight from the URL instead.
        cb = self.irc.getCallback('IRCquotes')
        cb.db.add(self.irc.network, self.channel, time.time(), 'someone',
                  'from the real network')
        cb.db.add('SomeOtherNetwork', self.channel, time.time(), 'someone',
                  'from a different network')
        webcb = ircquotes_plugin.IRCquotesWebCallback()
        webcb._plugin = cb
        handler = _FakeHttpHandler()
        webcb.send_response = handler.send_response
        webcb.send_header = handler.send_header
        webcb.end_headers = handler.end_headers
        webcb.wfile = handler
        path = '/%s/%s/' % (utils.web.urlquote(self.irc.network),
                             utils.web.urlquote(self.channel))
        with conf.supybot.plugins.IRCquotes.web.channel.context(True):
            webcb.doGetOrHead(handler, path, True)
        self.assertEqual(handler.status, 200)
        self.assertTrue('from the real network' in handler.body)
        self.assertTrue('from a different network' not in handler.body)

    def testWebJumpFormSingleMatchRedirects(self):
        webcb = ircquotes_plugin.IRCquotesWebCallback()
        webcb._plugin = self.irc.getCallback('IRCquotes')
        handler = _FakeHttpHandler()
        webcb.send_response = handler.send_response
        webcb.send_header = handler.send_header
        webcb.end_headers = handler.end_headers
        webcb.wfile = handler
        class _Value:
            def __init__(self, value):
                self.value = value
        form = {'chan': _Value(self.channel)}
        with conf.supybot.plugins.IRCquotes.web.channel.context(True):
            webcb.doPost(handler, '/', form)
        self.assertEqual(handler.status, 303)
        location = dict(handler.headers)['Location']
        self.assertEqual(location, './%s/%s/' % (
            utils.web.urlquote(self.irc.network),
            utils.web.urlquote(self.channel)))

    def testWebJumpFormNoMatchShowsMessage(self):
        webcb = ircquotes_plugin.IRCquotesWebCallback()
        webcb._plugin = self.irc.getCallback('IRCquotes')
        handler = _FakeHttpHandler()
        webcb.send_response = handler.send_response
        webcb.send_header = handler.send_header
        webcb.end_headers = handler.end_headers
        webcb.wfile = handler
        class _Value:
            def __init__(self, value):
                self.value = value
        form = {'chan': _Value('#nonexistent')}
        webcb.doPost(handler, '/', form)
        self.assertEqual(handler.status, 200)
        self.assertTrue('No network has a browsable' in handler.body)

    def _webPage(self):
        webcb = ircquotes_plugin.IRCquotesWebCallback()
        webcb._plugin = self.irc.getCallback('IRCquotes')
        handler = _FakeHttpHandler()
        webcb.send_response = handler.send_response
        webcb.send_header = handler.send_header
        webcb.end_headers = handler.end_headers
        webcb.wfile = handler
        path = '/%s/%s/' % (utils.web.urlquote(self.irc.network),
                             utils.web.urlquote(self.channel))
        with conf.supybot.plugins.IRCquotes.web.channel.context(True):
            webcb.doGetOrHead(handler, path, True)
        return handler.body

    def testWebStylesAuthorAndFooter(self):
        self.assertNotError('addquote \x0304red\x03 and \x02bold\x02 | '
                            'second line')
        body = self._webPage()
        self.assertTrue('<span class="fg04">red</span>' in body)
        self.assertTrue('<span class="mb">bold</span>' in body)
        self.assertTrue('<br/>second line' in body)
        self.assertTrue('\x03' not in body)
        # The author is hidden by default, like html_show_author.
        self.assertTrue('quoteauthor' not in body)
        with conf.supybot.plugins.IRCquotes.web.showAuthor.context(True), \
                conf.supybot.plugins.IRCquotes.web.footer1.context(
                    '<b>my footer</b>'):
            body = self._webPage()
        self.assertTrue('by %s' % self.nick in body)
        self.assertTrue('<b>my footer</b>' in body)
        with conf.supybot.plugins.IRCquotes.web.keepStyles.context(False):
            body = self._webPage()
        self.assertTrue('red and bold' in body)

    def testMircToHtml(self):
        html = ircquotes_plugin.mircToHtml
        self.assertEqual(html('a\x0304,01b\x0fc'),
                         'a<span class="fg04 bg01">b</span>c')
        self.assertEqual(html('<x> & y'), '&lt;x&gt; &amp; y')
        self.assertEqual(html('\x02a | b', ' | '),
                         '<span class="mb">a</span><br/>b')

    def testAddQuoteKeepsRawText(self):
        # Brackets would normally be a nested command and the quotation
        # marks would be eaten; the text is stored as it was typed, minus
        # the timestamp and the @ in front of the nick.
        self.assertRegexp('addquote [12:34] <@bob> he said "hi"  twice',
                          '#1 has been added')
        self.assertResponse('quoteget 1',
                            '\x1f[\x021\x02]\x0f <bob> he said "hi"  twice')

    def testAddQuoteKeepOptions(self):
        self.assertNotError('addquote -keep_timestamps [12:34] <@bob> hi')
        self.assertRegexp('quoteget 1', '\\[12:34\\] <bob> hi')
        self.assertNotError('addquote --keep-attributes --keep-timestamps '
                            '(12:34) <+bob> hi')
        self.assertRegexp('quoteget 2', '\\(12:34\\) <\\+bob> hi')
        with conf.supybot.plugins.IRCquotes.filterTimestamps.context(False):
            self.assertNotError('addquote <12:34:56> <%bob> hi')
            self.assertRegexp('quoteget 3', '<12:34:56> <bob> hi')

    def testAddQuoteWithChannel(self):
        self.assertNotError('addquote %s [01:02] <bob> elsewhere' %
                            self.channel, private=True)
        self.assertRegexp('quoteget 1', '<bob> elsewhere')

    def testMultilineAddQuote(self):
        cb = self.irc.getCallback('IRCquotes')
        with conf.supybot.plugins.IRCquotes.multilineAdd.context(True):
            self._command('addquote [10:00] <@bob> first line')
            for line in ('[10:01] <+alice> second line', 'not mine',
                         '[10:02] <bob> third line', '.'):
                frm = 'other!x@y' if line == 'not mine' else self.prefix
                self.irc.feedMsg(ircmsgs.privmsg(self.channel, line,
                                                 prefix=frm))
            notice = self.irc.takeMsg()
            self.assertEqual(notice.command, 'NOTICE')
            self.assertTrue('multiline quote is being recorded' in
                            notice.args[1])
            self.assertEqual(self._more(),
                             'The quote #1 has been added (3 lines).')
        self.assertEqual(cb._addSessions, {})
        self.assertResponse('quoteget 1',
                            '\x1f[\x021\x02]\x0f <bob> first line')
        self.assertEqual(self._more(), '\x0314|\x0f  <alice> second line')
        self.assertEqual(self._more(), '\x0314·\x0f  <bob> third line')

    def testMultilineAddQuoteTimeoutAndLimits(self):
        cb = self.irc.getCallback('IRCquotes')
        key = cb._sessionKey(self.irc.network, self.channel)
        with conf.supybot.plugins.IRCquotes.multilineAdd.context(True):
            self._command('addquote just one line')
            self.assertEqual(self.irc.takeMsg(), None)
            self.assertRegexp('addquote another one', 'being recorded')
            # What the timer does once nobody adds anything.
            cb._endSession(key)
            self.assertEqual(self._more(), 'The quote #1 has been added.')
            with conf.supybot.plugins.IRCquotes.multilineMaxLines.context(2):
                self._command('addquote one')
                for line in ('two', 'three'):
                    self.irc.feedMsg(ircmsgs.privmsg(self.channel, line,
                                                     prefix=self.prefix))
                self.irc.takeMsg() # the "being recorded" notice
                self.assertTrue('exceeded the allowed number of lines' in
                                self._more())
        self.assertEqual(cb.db.maxId(self.irc.network, self.channel), 1)

    def testMultilineDisplay(self):
        self.assertNotError('addquote a | b | c')
        with conf.supybot.plugins.IRCquotes.maxQuoteLines.context(2):
            # Too many lines: one line, with colored separators.
            self.assertResponse('quoteget 1',
                                '\x1f[\x021\x02]\x0f a\x0314 | \x0fb'
                                '\x0314 | \x0fc')
        with conf.supybot.plugins.IRCquotes.quotesColor.context('07'):
            self.assertResponse('quoteget 1',
                                '\x1f[\x021\x02]\x0f \x0307\x02\x02a')

    def testNoColorsOnPlusC(self):
        self.assertNotError('addquote \x0304colored\x03 quote')
        self.irc.state.channels[self.channel].modes['c'] = None
        try:
            self.assertResponse('quoteget 1', '[1] colored quote')
        finally:
            del self.irc.state.channels[self.channel].modes['c']
        with conf.supybot.plugins.IRCquotes.monochrome.context(True):
            self.assertResponse('quoteget 1', '[1] colored quote')

    def testTrailingChannel(self):
        self.assertNotError('addquote over there')
        self.assertRegexp('quoteget 1 %s' % self.channel, 'over there',
                          private=True)
        self.assertRegexp('quoteinfo 1 %s' % self.channel, 'added by',
                          private=True)
        self.assertRegexp('lastquote %s' % self.channel, 'over there',
                          private=True)
        self.assertRegexp('quoteget 1', 'channel', private=True)

    def testReadableChannels(self):
        cb = self.irc.getCallback('IRCquotes')
        cb.db.add(self.irc.network, '#closed', time.time(), 'x', 'hidden')
        with conf.supybot.plugins.IRCquotes.enabled.get('#closed').context(
                False):
            self.assertRegexp('quoteget 1 #closed', 'not enabled')
            with conf.supybot.plugins.IRCquotes.readableChannels.context(
                    ['#closed']):
                self.assertRegexp('quoteget 1 #closed', 'hidden')
                self.assertRegexp('addquote #closed nope', 'not enabled')

    def testRandQuoteDoesNotRepeat(self):
        cb = self.irc.getCallback('IRCquotes')
        for text in ('one', 'two', 'three', 'four'):
            cb.db.add(self.irc.network, self.channel, time.time(), 'x', text)
        for _round in range(3):
            seen = set(cb._nextRandom(self.irc.network, self.channel).id
                       for _i in range(4))
            self.assertEqual(seen, set([1, 2, 3, 4]))
        self.assertRegexp('randquote', 'one|two|three|four')

    def testAutoRandQuoteConsidersRatings(self):
        cb = self.irc.getCallback('IRCquotes')
        for text in ('liked', 'disliked'):
            cb.db.add(self.irc.network, self.channel, time.time(), 'x', text)
        self.assertNotError('votequote 2 -')
        for _i in range(5):
            self.assertEqual(cb._nextRandom(self.irc.network, self.channel,
                                            auto=True).id, 1)
        with conf.supybot.plugins.IRCquotes.autoRandQuoteConsidersRatings \
                .context(False):
            ids = set(cb._nextRandom(self.irc.network, self.channel,
                                     auto=True).id for _i in range(2))
            self.assertEqual(ids, set([1, 2]))

    def testLastQuoteSkipsDeletedNewest(self):
        self.assertNotError('addquote older')
        self.assertNotError('addquote newest')
        self.assertNotError('delquote 2')
        self.assertRegexp('lastquote', 'latest quote \\(#2\\) doesn\'t '
                          'exist anymore.*Looking')
        self.assertTrue('older' in self._more())

    def testFlood(self):
        self.assertNotError('addquote flood')
        with conf.supybot.plugins.IRCquotes.antiflood.context(True), \
                conf.supybot.plugins.IRCquotes.flood.quote.context('2:80'), \
                conf.supybot.plugins.IRCquotes.web.publicUrl.context(
                    'https://q.example/'):
            self.assertNotError('quoteget 1')
            self.assertNotError('quoteget 1')
            self.assertRegexp('quoteget 1', 'Flood control has been '
                              'triggered on the command .*quoteget.*no more '
                              'than 2 command\\(s\\) every 80 seconds.*'
                              'https://q.example/')
            self.assertNoResponse('quoteget 1', 1)
            # Other commands aren't affected...
            self.assertNotError('quoteinfo 1')
            # ...until the global limit.
            with conf.supybot.plugins.IRCquotes.flood.get('global').context(
                    '4:80'):
                self.assertRegexp('randquote', 'all commands')

    def testBackupAndRestore(self):
        cb = self.irc.getCallback('IRCquotes')
        self.assertNotError('addquote back me up')
        backup = cb._backupPath()
        if os.path.exists(backup):
            os.remove(backup)
        cb._backup()
        self.assertTrue(os.path.exists(backup))
        restored = ircquotes_plugin.QuotesDB(backup)
        try:
            self.assertEqual(restored.get(self.irc.network, self.channel,
                                          1).text, 'back me up')
        finally:
            restored.close()
        # A missing database is brought back from the backup on load.
        dbPath = cb._dbPath
        cb.db.close()
        os.remove(dbPath)
        cb._restoreBackup()
        cb.db = ircquotes_plugin.QuotesDB(dbPath)
        self.assertRegexp('quoteget 1', 'back me up')

    def testOldDatabaseGetsNewColumns(self):
        fd, dbPath = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        try:
            import sqlite3
            conn = sqlite3.connect(dbPath)
            conn.execute("""CREATE TABLE quotes (network TEXT NOT NULL,
                channel TEXT NOT NULL, id INTEGER NOT NULL, at REAL NOT NULL,
                by TEXT NOT NULL, text TEXT NOT NULL,
                likes INTEGER NOT NULL DEFAULT 0,
                dislikes INTEGER NOT NULL DEFAULT 0,
                voters TEXT NOT NULL DEFAULT '',
                deleted INTEGER NOT NULL DEFAULT 0,
                deletedBy TEXT NOT NULL DEFAULT '',
                deletedAt REAL NOT NULL DEFAULT 0,
                PRIMARY KEY (network, channel, id))""")
            conn.execute("INSERT INTO quotes (network, channel, id, at, by, "
                         "text) VALUES ('N', '#c', 1, 0, 'x', 'old')")
            conn.commit()
            conn.close()
            db = ircquotes_plugin.QuotesDB(dbPath)
            try:
                record = db.get('N', '#c', 1)
                self.assertEqual(record.text, 'old')
                self.assertFalse(record.deletedByAdmin)
                record.deletedByAdmin = True
                db.set('N', '#c', 1, record)
                self.assertTrue(db.get('N', '#c', 1).deletedByAdmin)
            finally:
                db.close()
        finally:
            os.remove(dbPath)

# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
