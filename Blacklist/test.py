###
# Copyright (c) 2022, Mike Oxlong
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

import json
import time

from supybot.test import *
import supybot.ircdb as ircdb
import supybot.ircmsgs as ircmsgs
import supybot.schedule as schedule


class BlacklistTestCase(ChannelPluginTestCase):
    plugins = ('Blacklist', 'User')

    def setUp(self):
        super().setUp()
        conf.supybot.plugins.Blacklist.enabled.setValue(True)
        # A real JOIN (not just addUser) is needed so irc.state.nickToHostmask
        # can resolve 'foo' the way _createMask does.
        self.irc.feedMsg(ircmsgs.join(self.channel, prefix='foo!foouser@foo.host'))
        # Register 'test' (self.nick/self.prefix) with op + admin so every
        # command in the plugin is reachable from these tests.
        self.irc.feedMsg(ircmsgs.privmsg(self.irc.nick, 'register %s pass' %
                                          self.nick, prefix=self.prefix))
        m = self.irc.takeMsg()
        assert m is not None and 'Error' not in m.args[1], \
            'Registration failed: %r' % (m,)
        u = ircdb.users.getUser(ircdb.users.getUserId(self.nick))
        u.addCapability('%s.op' % self.channel)
        u.addCapability('admin')
        ircdb.users.setUser(u)

    def _cb(self):
        return self.irc.getCallback('Blacklist')

    def _drain(self):
        """add/timer/net add/net timer/clear queue a ban and/or kick message
        in addition to the actual reply; assertNotError/assertRegexp etc. only
        pop one message off the front of the queue, so leftover side-effect
        messages must be drained before the next assertion or it'll pick up
        a stale one instead of the next command's real reply."""
        while self.irc.takeMsg() is not None:
            pass

    def testBanmasksMatchEggdrop(self):
        # Types 3, 4, 8, 9 used to read "*.phost" instead of "*.host": since
        # "phost" contains "host" as a substring, _createMask's naive
        # .replace("host", host) turned "*.phost" into "*.p<realhost>",
        # gluing a stray "p" onto the real host (the bug the README used to
        # warn about).
        cb = self._cb()
        irc = self.irc
        # foo's hostmask (from setUp) is 'foo!foouser@foo.host'.
        for num in (3, 4, 8, 9):
            mask = cb._createMask(irc, 'foo', num)
            expectSuffix = '*.foo.host'
            self.assertTrue(mask.endswith(expectSuffix),
                             'type %d produced %r, expected it to end with %r '
                             '(a stray "p" means the *.phost typo is back)' %
                             (num, mask, expectSuffix))

    def testAddListDeleteStableIds(self):
        self.assertNotError('blacklist add foo somereason')
        self._drain()
        self.assertRegexp('blacklist list', r'\[1\].*somereason')
        self.assertNotError('blacklist add bar!bar@bar.host anotherreason')
        self._drain()
        self.assertRegexp('blacklist list', r'\[2\].*anotherreason')
        # Deleting by stable ID must remove the right entry regardless of
        # dict/positional ordering.
        self.assertNotError('blacklist delete 1')
        self.assertNotRegexp('blacklist list', r'\[1\]')
        self.assertRegexp('blacklist list', r'\[2\].*anotherreason')

    def testReasonAndExtend(self):
        self.assertNotError('blacklist add foo original')
        self._drain()
        self.assertNotError('blacklist reason 1 updated reason')
        self.assertRegexp('blacklist list', 'updated reason')
        self.assertNotError('blacklist extend 1 5')
        cb = self._cb()
        bucket = cb.db['channels'][self.channel.lower()]
        self.assertTrue(any(e.get('expire_at') for e in bucket['entries'].values()),
                         'extend should have set expire_at on the entry.')

    def testSearch(self):
        self.assertNotError('blacklist add foo needle-reason')
        self._drain()
        self.assertRegexp('blacklist search needle', 'needle-reason')
        self.assertResponse('blacklist search doesnotexist',
                             'No matching entries found.')

    def testClearRequiresConfirm(self):
        self.assertNotError('blacklist add foo x')
        self._drain()
        self.assertError('blacklist clear %s' % self.channel)
        self.assertNotError('blacklist clear %s confirm' % self.channel)
        self._drain()
        self.assertResponse('blacklist list', 'List is empty.')

    def testChannelExempt(self):
        self.assertNotError('blacklist exempt add foo!*@*')
        self.assertError('blacklist add foo shouldnotwork')
        self.assertNotError('blacklist exempt remove foo!*@*')
        self.assertNotError('blacklist add foo worksnow')
        self._drain()

    def testNetAddEnforcesAcrossChannel(self):
        self.assertNotError('blacklist net add foo netreason')
        self._drain()
        self.assertRegexp('blacklist net list', r'\[1\].*netreason')
        # foo should have been banned & kicked in self.channel.
        self.assertNotError('blacklist net delete 1')
        self._drain()
        self.assertResponse('blacklist net list', 'Network blacklist is empty.')

    def testNetExempt(self):
        self.assertNotError('blacklist net exemptadd foo!*@*')
        self.assertError('blacklist net add foo nope')
        self.assertNotError('blacklist net exemptremove foo!*@*')
        self.assertNotError('blacklist net add foo yesnow')
        self._drain()

    def testDoJoinBansNetBlacklistedUser(self):
        self.assertNotError('blacklist net add bar!bar@bar.host joinreason')
        self._drain()
        self.irc.feedMsg(ircmsgs.join(self.channel, prefix='bar!bar@bar.host'))
        m = self.irc.takeMsg()
        self.assertFalse(m is None, 'Expected a ban for the net-blacklisted joiner.')
        self.assertEqual(m.command, 'MODE')
        m2 = self.irc.takeMsg()
        self.assertFalse(m2 is None, 'Expected a kick for the net-blacklisted joiner.')
        self.assertEqual(m2.command, 'KICK')

    def testDoModeTracksManualBan(self):
        # Must come from someone other than the bot itself (irc.nick == 'test'
        # == self.nick), or doMode's self-action guard drops the message.
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', '*!*@manual.host'),
                                       prefix='anop!op@op.host'))
        bucket = self._cb().db['channels'][self.channel.lower()]
        self.assertTrue('*!*@manual.host' in bucket['entries'])
        self.assertEqual(bucket['entries']['*!*@manual.host']['reason'], '*manual ban')

    def testDoModeSkipsExemptMask(self):
        self.assertNotError('blacklist exempt add *!*@exempt.host')
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', '*!*@exempt.host'),
                                       prefix='anop!op@op.host'))
        bucket = self._cb().db['channels'][self.channel.lower()]
        self.assertTrue('*!*@exempt.host' not in bucket['entries'])

    def testLegacyMigration(self):
        cb = self._cb()
        legacy = {
            self.channel.lower(): {
                '*!*@host1': ['someop', time.time(), 'reason one', True, None],
                '*!*@host2': ['someop', time.time(), '*manual ban', False, None],
            }
        }
        with open(cb.dbfile, 'w') as f:
            json.dump(legacy, f)
        cb._initdb()
        bucket = cb.db['channels'][self.channel.lower()]
        ids = sorted(e['id'] for e in bucket['entries'].values())
        self.assertEqual(ids, [1, 2])
        self.assertEqual(bucket['entries']['*!*@host1']['reason'], 'reason one')
        self.assertEqual(bucket['exempt'], [])

    def testRestartReschedulesFutureExpiry(self):
        cb = self._cb()
        mask = '*!*@futurehost'
        expire_at = time.time() + 3600
        entry_id = cb._internal_add(self.channel, mask, 'someop', '', is_bot_cmd=True,
                                     expire_at=expire_at, expire_mode='full')
        name = cb._event_name('channel', self.channel, entry_id)
        # Simulate the timer having been lost (e.g. bot restart).
        try:
            schedule.removeEvent(name)
        except KeyError:
            pass
        cb._reschedule_all(self.irc)
        self.assertTrue(name in schedule.schedule.events,
                         'Expiry was not rescheduled after reload.')
        # Cleanup so later tests / driver runs don't trip over it.
        schedule.removeEvent(name)

    def testRestartFiresPastDueExpiryImmediately(self):
        cb = self._cb()
        mask = '*!*@pasthost'
        entry_id = cb._internal_add(self.channel, mask, 'someop', '', is_bot_cmd=True,
                                     expire_at=time.time() - 10, expire_mode='full')
        cb._reschedule_all(self.irc)
        bucket = cb.db['channels'][self.channel.lower()]
        self.assertTrue(mask not in bucket['entries'],
                         'Past-due entry should have been removed immediately on reload.')
        m = self.irc.takeMsg()
        self.assertFalse(m is None, 'Expected an UNBAN to be queued for the past-due entry.')
        self.assertEqual(m.command, 'MODE')


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
