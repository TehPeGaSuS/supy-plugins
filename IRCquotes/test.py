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

class IRCquotesTestCase(ChannelPluginTestCase):
    plugins = ('IRCquotes', 'User')

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

    def testDisabled(self):
        with conf.supybot.databases.plugins.requireRegistration.context(False):
            with conf.supybot.plugins.IRCquotes.enabled.context(False):
                self.assertError('addquote nope')

# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
