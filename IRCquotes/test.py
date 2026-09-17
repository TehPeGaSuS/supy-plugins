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

    def testFindQuote(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            self.assertNotError('addquote a needle in a haystack')
            self.assertRegexp('findquote *needle*', 'needle')

    def testFindQuoteMaxResults(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            for i in range(5):
                self.assertNotError('addquote needle %d' % i)
            with conf.supybot.plugins.IRCquotes.findQuoteMaxResults.context(2):
                self.assertRegexp('findquote *needle*', 'showing 2')

    def testMinQuoteLength(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            with conf.supybot.plugins.IRCquotes.minQuoteChars.context(10):
                self.assertError('addquote short')
                self.assertNotError('addquote long enough now')
            with conf.supybot.plugins.IRCquotes.minQuoteWords.context(3):
                self.assertError('addquote two words')
                self.assertNotError('addquote this has three words')

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
            self.assertNotError('votequote 1 +')
            self.assertRegexp('quoteinfo 1', '1 like\\(s\\), 0 dislike')
            # Switch directly from + to - without clearing first.
            self.assertNotError('votequote 1 -')
            self.assertRegexp('quoteinfo 1', '0 like\\(s\\), 1 dislike')
            self.assertNotError('votequote 1 +')
            self.assertRegexp('quoteinfo 1', '1 like\\(s\\), 0 dislike')

    def testDelQuote(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            self.assertNotError('addquote to be deleted')
            self.assertNotError('delquote 1')
            # Numbering is preserved: the id stays valid, but the content
            # is hidden instead of the quote vanishing entirely.
            self.assertRegexp('quoteget 1', 'has been deleted')
            self.assertError('delquote 1') # already deleted
            # Not an error reply, just a plain notice -- can't vote on a
            # deleted quote.
            self.assertRegexp('votequote 1 +', 'cannot be voted')
            self.assertNotError('undelquote 1')
            self.assertRegexp('quoteget 1', 'to be deleted')

    def testForceDelQuote(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            self.assertNotError('addquote to be purged')
            self.assertNotError('forcedelquote 1')
            self.assertError('quoteget 1') # gone for good, no such record

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
                'https://quotes.example.com/ircquotes/%s/%s/' % (
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

# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
