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

    def testVoteQuote(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            self.assertNotError('addquote votable quote')
            self.assertNotError('votequote 1 +')
            self.assertRegexp('quoteinfo 1', '1 like')
            self.assertError('votequote 1 +') # already voted
            self.assertNotError('votequote 1 0') # clear vote
            self.assertNotError('votequote 1 -')
            self.assertRegexp('quoteinfo 1', '1 dislike')

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

# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
