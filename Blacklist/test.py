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
        # Off by default; most tests exercise the network list, so turn it on.
        conf.supybot.plugins.Blacklist.enforceGlobal.setValue(True)
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

    def _exempt(self, cmd, *args):
        self.assertNotError('blacklist exempt %s %s' % (cmd, ' '.join(args)))
        self._drain()

    def testExemptLabelsGroupSeveralMasks(self):
        for args in (('add', 'Mimi', '*!*@a.host'), ('add', 'Mimi', '*!*@b.host'),
                     ('add', 'Bob', 'bob!*@*'), ('add', '*!*@loose.host')):
            self._exempt(*args)
        self.assertResponse(
            'blacklist exempt list',
            'Mimi: *!*@a.host, *!*@b.host | Bob: bob!*@* | *!*@loose.host')
        # Names are case-insensitive and shown as first filed.
        self.assertResponse('blacklist exempt list mimi',
                            'Mimi: *!*@a.host, *!*@b.host')
        self.assertError('blacklist exempt list nobody')

    def testExemptAddAppendsAndRelabels(self):
        self._exempt('add', 'Mimi', '*!*@a.host')
        self._exempt('add', 'Mimi', '*!*@b.host')    # appended, not replaced
        self._exempt('add', '*!*@c.host')             # bare mask still works
        self._exempt('add', 'Mimi', '*!*@c.host')     # ...and can be filed later
        self.assertResponse('blacklist exempt list',
                            'Mimi: *!*@a.host, *!*@b.host, *!*@c.host')

    def testExemptRemoveByMaskNameOrBoth(self):
        for args in (('Mimi', '*!*@a.host'), ('Mimi', '*!*@b.host'),
                     ('Mimi', '*!*@c.host'), ('Bob', 'bob!*@*')):
            self._exempt('add', *args)
        self._exempt('remove', 'Mimi', '*!*@a.host')     # one mask of a name
        self.assertResponse('blacklist exempt list mimi',
                            'Mimi: *!*@b.host, *!*@c.host')
        self._exempt('remove', '*!*@b.host')              # a bare mask
        self.assertResponse('blacklist exempt list mimi', 'Mimi: *!*@c.host')
        self._exempt('remove', 'MIMI')                    # everything under a name
        self.assertResponse('blacklist exempt list', 'Bob: bob!*@*')
        self.assertError('blacklist exempt remove Mimi')
        self.assertError('blacklist exempt remove Bob *!*@nope')

    def testExemptRejectsBadInput(self):
        self.assertError('blacklist exempt add notamask')
        self.assertError('blacklist exempt add Mimi notamask')
        self.assertError('blacklist exempt add *!*@a.host *!*@b.host')  # mask as name
        self.assertError('blacklist exempt add Caf\u00e9 *!*@a.host')
        self.assertError('blacklist exempt add Mimi *!*@h\u00f6st.example')

    def _withFakePaste(self, fn):
        """Runs fn with maxInlineEntries=2 and a captured fake paste upload;
        returns the list of (channel, content) uploads."""
        cb = self._cb()
        uploads = []
        cb._createPastebin = lambda channel, content: (
            uploads.append((channel, content)) or 'https://paste.example/abc')
        conf.supybot.plugins.Blacklist.maxInlineEntries.setValue(2)
        try:
            fn()
        finally:
            conf.supybot.plugins.Blacklist.maxInlineEntries.setValue(5)
            del cb._createPastebin
        return uploads

    def testLongExemptListGoesToThePasteService(self):
        for args in (('Mimi', '*!*@a.host'), ('Mimi', '*!*@b.host'),
                     ('Bob', 'bob!*@*'), ('*!*@loose.host',)):
            self._exempt('add', *args)
        def run():
            self.assertRegexp('blacklist exempt list',
                              r'too large \(4 masks\).*https://paste\.example/abc')
            # a single name's masks fit inline again
            self.assertResponse('blacklist exempt list mimi',
                                'Mimi: *!*@a.host, *!*@b.host')
        uploads = self._withFakePaste(run)
        self.assertEqual(len(uploads), 1)
        channel, text = uploads[0]
        self.assertEqual(channel, self.channel)
        self.assertTrue('Mimi:\n  *!*@a.host\n  *!*@b.host\n' in text)
        self.assertTrue('(no name):\n  *!*@loose.host\n' in text)

    def testShortExemptListStaysInline(self):
        self._exempt('add', 'Mimi', '*!*@a.host')
        self._exempt('add', 'Bob', 'bob!*@*')
        uploads = self._withFakePaste(lambda: self.assertResponse(
            'blacklist exempt list', 'Mimi: *!*@a.host | Bob: bob!*@*'))
        self.assertEqual(uploads, [])

    def testLongNetExemptListGoesToThePasteService(self):
        for args in ('Mimi *!*@a.host', 'Mimi *!*@b.host', 'Bob bob!*@*'):
            self.assertNotError('blacklist net exemptadd %s' % args)
            self._drain()
        uploads = self._withFakePaste(lambda: self.assertRegexp(
            'blacklist net exemptlist', r'too large \(3 masks\).*paste\.example'))
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0][0], None)
        self.assertTrue('Network exempt masks (3 masks)' in uploads[0][1])

    def testLabelledExemptStillProtects(self):
        self._exempt('add', 'Foo', 'foo!*@*')
        self.assertError('blacklist add foo shouldnotwork')

    def testExemptWorksOnAnOldDatabaseWithoutNames(self):
        bucket = self._cb()._ensure_channel_bucket(self.channel)
        bucket['exempt'] = ['old!*@*']
        bucket.pop('exempt_names', None)
        self.assertResponse('blacklist exempt list', 'old!*@*')
        self._exempt('add', 'Mimi', '*!*@a.host')
        self.assertResponse('blacklist exempt list', 'Mimi: *!*@a.host | old!*@*')
        self._exempt('remove', 'old!*@*')
        self.assertResponse('blacklist exempt list', 'Mimi: *!*@a.host')

    def testNetExemptLabels(self):
        for args in ('Mimi *!*@a.host', 'Mimi *!*@b.host', 'Bob bob!*@*'):
            self.assertNotError('blacklist net exemptadd %s' % args)
            self._drain()
        self.assertResponse('blacklist net exemptlist',
                            'Mimi: *!*@a.host, *!*@b.host | Bob: bob!*@*')
        self.assertNotError('blacklist net exemptremove Mimi *!*@a.host')
        self._drain()
        self.assertNotError('blacklist net exemptremove bob')
        self._drain()
        self.assertResponse('blacklist net exemptlist', 'Mimi: *!*@b.host')
        self.assertError('blacklist net exemptlist nobody')

    def testEnforceGlobalIsOffByDefault(self):
        self.assertFalse(conf.supybot.plugins.Blacklist.enforceGlobal._default)

    def testNetBlacklistIgnoredWhereEnforceGlobalIsOff(self):
        self.assertNotError('blacklist net add bar!bar@bar.host netreason')
        self._drain()
        conf.supybot.plugins.Blacklist.enforceGlobal.setValue(False)
        try:
            self.irc.feedMsg(ircmsgs.join(self.channel, prefix='bar!bar@bar.host'))
            self.assertEqual(self._takeAll(), [],
                              'A channel with enforceGlobal off must ignore the net list.')
            self.irc.feedMsg(ircmsgs.nick('barbar', prefix='bar!bar@bar.host'))
            self.assertEqual(self._takeAll(), [])
            msgs = self._takeAll(self.assertNotError(
                'blacklist net add foo!*@* netreason2'))
            self.assertEqual(self._kicked(msgs), [],
                              '`net add` must not ban or kick where it is off.')
        finally:
            conf.supybot.plugins.Blacklist.enforceGlobal.setValue(True)

    def _joinOtherChannel(self, name='#other'):
        self.irc.feedMsg(ircmsgs.join(name, prefix=self.irc.prefix))
        self._drain()
        return name

    def _replyTo(self, command):
        """The text the bot answered with. A net add queues its MODE/KICK
        before replying, so assertRegexp would see those first."""
        msgs = self._takeAll(self.assertNotError(command))
        replies = [m.args[1] for m in msgs if m.command == 'PRIVMSG']
        self.assertTrue(replies, 'No reply to %r' % command)
        return replies[-1]

    def testNetAddReportsTheChannelsItReached(self):
        other = self._joinOtherChannel()
        conf.supybot.plugins.Blacklist.enforceGlobal.get(other).setValue(False)
        self.assertRegex(
            self._replyTo('blacklist net add foo r1'),
            r'Added to the network blacklist\. Banned in #test \(no ops\); '
            r'enforceGlobal is off in 1 other channel\.')
        self.assertNotError('blacklist net delete 1')
        self._drain()
        self._botIsOpped()
        self.assertRegex(
            self._replyTo('blacklist net timer foo 5 r2'),
            r'for 5 minutes\. Banned in #test; enforceGlobal is off in 1 other channel\.')

    def testNetAddSaysWhenNoChannelEnforcesIt(self):
        other = self._joinOtherChannel()
        for chan in (self.channel, other):
            conf.supybot.plugins.Blacklist.enforceGlobal.get(chan).setValue(False)
        self.assertRegex(
            self._replyTo('blacklist net add foo r1'),
            r'Not enforced anywhere yet: enforceGlobal is off in 2 channels\.')

    def testNetReachTextCapsALongChannelList(self):
        cb = self._cb()
        text = cb._netReachText([('#c%d' % i, True) for i in range(11)], [])
        self.assertEqual(text, 'Banned in #c0, #c1, #c2, #c3, #c4, #c5, #c6, #c7 and 3 more.')

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

    # -------------------------------------------------------------
    # banlistExpiry ("dynamic ban") lifecycle: `add` keeps the entry forever
    # but lifts the IRC +b after banlistExpiry minutes; a later matching join
    # must re-apply the +b *and* arm a fresh lift, or the ban would outlive
    # banlistExpiry for good.
    # -------------------------------------------------------------

    def _firedLift(self, mask='*!*@foo.host'):
        """Adds foo via `blacklist add`, then simulates the scheduler having
        fired the IRC-only lift (the real scheduler drops the event once it
        runs). Returns (entry_id, bucket)."""
        self.assertNotError('blacklist add foo somereason')
        self._drain()
        cb = self._cb()
        bucket = cb.db['channels'][self.channel.lower()]
        entry_id = bucket['entries'][mask]['id']
        cb._unschedule('channel', self.channel, entry_id)
        cb._fire_expiry(self.irc.network, 'channel', self.channel,
                         entry_id, 'irc_only')
        self._drain()
        return entry_id, bucket

    def testIrcOnlyLiftClearsStaleExpiry(self):
        mask = '*!*@foo.host'
        entry_id, bucket = self._firedLift(mask)
        entry = bucket['entries'][mask]
        self.assertTrue(mask in bucket['entries'],
                         'An irc_only lift must keep the DB entry.')
        self.assertEqual((entry['expire_at'], entry['expire_mode']), (None, None),
                          'Nothing is pending after the lift fired; a stale '
                          'expire_at would be re-fired on every reload.')
        self.assertNotRegexp('blacklist list', r'expiring')
        # A reload must not send another UNBAN for an already-lifted ban.
        self._cb()._reschedule_all(self.irc)
        self.assertTrue(self.irc.takeMsg() is None,
                         'Reload re-lifted a ban that was already lifted.')

    def testDoJoinReappliesBanAndRearmsLift(self):
        mask = '*!*@foo.host'
        entry_id, bucket = self._firedLift(mask)
        cb = self._cb()
        name = cb._event_name('channel', self.channel, entry_id)
        try:
            self.irc.feedMsg(ircmsgs.join(self.channel,
                                           prefix='foo!foouser@foo.host'))
            m = self.irc.takeMsg()
            self.assertFalse(m is None, 'Expected the +b to be re-applied on join.')
            self.assertEqual(m.command, 'MODE')
            m2 = self.irc.takeMsg()
            self.assertFalse(m2 is None, 'Expected a kick on join.')
            self.assertEqual(m2.command, 'KICK')
            entry = bucket['entries'][mask]
            self.assertEqual(entry['expire_mode'], 'irc_only')
            self.assertTrue(entry['expire_at'] and entry['expire_at'] > time.time(),
                             'Re-applied ban must get a fresh expire_at.')
            self.assertTrue(name in schedule.schedule.events,
                             'Re-applied ban must have its lift re-scheduled.')
        finally:
            try:
                schedule.removeEvent(name)
            except KeyError:
                pass

    def testDoJoinDoesNotTouchTimedEntry(self):
        # `timer` entries ('full') are governed by their own timer; a join
        # that re-applies the ban must leave their expiry alone.
        self.assertNotError('blacklist timer foo 60 spamming')
        self._drain()
        cb = self._cb()
        bucket = cb.db['channels'][self.channel.lower()]
        entry = bucket['entries']['*!*@foo.host']
        before = (entry['expire_at'], entry['expire_mode'])
        self.irc.feedMsg(ircmsgs.join(self.channel, prefix='foo!foouser@foo.host'))
        self._drain()
        self.assertEqual((entry['expire_at'], entry['expire_mode']), before)
        self.assertEqual(entry['expire_mode'], 'full')

    # -------------------------------------------------------------
    # Eggdrop-style enforcement: a ban kicks *every* member it matches
    # (enforce-bans), exempts override bans on join, and the bot re-applies
    # bans the channel lost once it is opped (recheck_bans).
    # -------------------------------------------------------------

    def _takeAll(self, first=None):
        out = [first] if first is not None else []
        while True:
            m = self.irc.takeMsg()
            if m is None:
                return out
            out.append(m)

    def _kicked(self, msgs):
        return sorted(m.args[1] for m in msgs if m.command == 'KICK')

    def _joinBaz(self):
        # baz shares foo's host, so a *!*@foo.host mask matches both.
        self.irc.feedMsg(ircmsgs.join(self.channel, prefix='baz!bazuser@foo.host'))
        self._drain()

    def testAddKicksEveryMemberMatchingTheMask(self):
        self._joinBaz()
        msgs = self._takeAll(self.assertNotError('blacklist add foo somereason'))
        self.assertEqual(self._kicked(msgs), ['baz', 'foo'])

    def testTimerKicksEveryMemberMatchingTheMask(self):
        self._joinBaz()
        msgs = self._takeAll(self.assertNotError('blacklist timer foo 30 spamming'))
        self.assertEqual(self._kicked(msgs), ['baz', 'foo'])

    def testAddKickSkipsExemptMember(self):
        self._joinBaz()
        self.assertNotError('blacklist exempt add baz!*@*')
        self._drain()
        msgs = self._takeAll(self.assertNotError('blacklist add foo somereason'))
        self.assertEqual(self._kicked(msgs), ['foo'])

    def testKickMatchingNeverKicksTheBot(self):
        # `add *!*@*` is now refused outright, but the kick loop keeps its
        # own guard (stored entries, net enforcement, resync all use it).
        self.irc.state.channels[self.channel].addUser(self.irc.nick)
        kicked = self._cb()._kickMatching(self.irc, self.channel, '*!*@*',
                                          'catchall', lambda hm: False)
        self.assertTrue('foo' in kicked)
        self.assertFalse(self.irc.nick in kicked, 'The bot must never kick itself.')
        self._drain()

    def testNetAddKicksEveryMatchingMemberExceptNetExempt(self):
        self._joinBaz()
        msgs = self._takeAll(self.assertNotError('blacklist net add foo netreason'))
        self.assertEqual(self._kicked(msgs), ['baz', 'foo'])
        self.assertNotError('blacklist net delete 1')
        self._drain()
        self.assertNotError('blacklist net exemptadd baz!*@*')
        self._drain()
        # The harness applies our own KICKs to its state, so bring them back.
        self.irc.feedMsg(ircmsgs.join(self.channel, prefix='foo!foouser@foo.host'))
        self._joinBaz()
        msgs = self._takeAll(self.assertNotError('blacklist net add foo netreason'))
        self.assertEqual(self._kicked(msgs), ['foo'])

    def testDoJoinHonoursChannelExempt(self):
        self.assertNotError('blacklist add foo somereason')
        self._drain()
        self.assertNotError('blacklist exempt add baz!*@*')
        self._drain()
        self.irc.feedMsg(ircmsgs.join(self.channel, prefix='baz!bazuser@foo.host'))
        self.assertEqual(self._takeAll(), [],
                          'An exempt hostmask must not be banned/kicked on join.')
        # A non-exempt joiner on the same mask is still enforced.
        self.irc.feedMsg(ircmsgs.join(self.channel, prefix='qux!quxuser@foo.host'))
        self.assertEqual(self._kicked(self._takeAll()), ['qux'])

    def testDoJoinHonoursNetExempt(self):
        self.assertNotError('blacklist net add foo netreason')
        self._drain()
        self.assertNotError('blacklist net exemptadd baz!*@*')
        self._drain()
        self.irc.feedMsg(ircmsgs.join(self.channel, prefix='baz!bazuser@foo.host'))
        self.assertEqual(self._takeAll(), [],
                          'A net-exempt hostmask must not be banned/kicked on join.')

    def _channelLostItsBans(self):
        # Limnoria's state records the bans the bot itself sends; wipe it to
        # simulate a channel that was emptied and recreated (no +b left).
        self.irc.state.channels[self.channel].bans.clear()

    def _opBot(self):
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('+o', self.irc.nick),
                                       prefix='anop!op@op.host'))

    def testBotOpResyncsMissingBansAndKicksMatches(self):
        self.assertNotError('blacklist add foo somereason')
        self._drain()
        # foo got kicked by `add`; put him back in the state without a JOIN
        # (which would itself trigger doJoin) and drop the channel's bans.
        self.irc.state.channels[self.channel].addUser('foo')
        self._channelLostItsBans()
        self._opBot()
        msgs = self._takeAll()
        bans = [m for m in msgs if m.command == 'MODE' and '+b' in m.args[1]]
        self.assertTrue(any('*!*@foo.host' in m.args for m in bans),
                         'Expected the missing ban to be re-applied on op.')
        self.assertEqual(self._kicked(msgs), ['foo'])

    def testBotOpDoesNotReapplyBansAlreadyOnTheChannel(self):
        self.assertNotError('blacklist add foo somereason')
        self._drain()
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', '*!*@foo.host'),
                                       prefix=self.irc.prefix))
        self._opBot()
        self.assertEqual(self._takeAll(), [])

    def testBotOpResyncSkipsLiftedEntries(self):
        self._firedLift()          # banlistExpiry lifted the +b on purpose
        self._opBot()
        self.assertEqual(self._takeAll(), [],
                          'A ban lifted by banlistExpiry must wait for the next join.')

    def testBotOpResyncSkipsManuallyUnbannedEntries(self):
        self.assertNotError('blacklist add foo somereason')
        self._drain()
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', '*!*@foo.host'),
                                       prefix=self.irc.prefix))
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('-b', '*!*@foo.host'),
                                       prefix='anop!op@op.host'))
        bucket = self._cb().db['channels'][self.channel.lower()]
        self.assertTrue(bucket['entries']['*!*@foo.host'].get('lifted'),
                         'A manual -b of a bot entry must mark it lifted.')
        self._opBot()
        self.assertEqual(self._takeAll(), [],
                          "An op's deliberate -b must not be undone by a resync.")

    def testResyncOnlyWhenTheBotItselfGainsOps(self):
        self.assertNotError('blacklist add foo somereason')
        self._drain()
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('+o', 'foo'),
                                       prefix='anop!op@op.host'))
        self.assertEqual(self._takeAll(), [])

    def testEndOfBanListResyncsWhenAlreadyOpped(self):
        self.assertNotError('blacklist add foo somereason')
        self._drain()
        self._channelLostItsBans()
        self.irc.state.channels[self.channel].ops.add(self.irc.nick)
        self.irc.feedMsg(ircmsgs.IrcMsg(prefix='irc.server', command='368',
                                         args=(self.irc.nick, self.channel,
                                               'End of channel ban list')))
        bans = [m for m in self._takeAll()
                if m.command == 'MODE' and '+b' in m.args[1]]
        self.assertTrue(any('*!*@foo.host' in m.args for m in bans),
                         'Join-time sync (end of ban list) should re-apply it.')

    def testEndOfBanListDoesNothingWhenNotOpped(self):
        self.assertNotError('blacklist add foo somereason')
        self._drain()
        self.irc.feedMsg(ircmsgs.IrcMsg(prefix='irc.server', command='368',
                                         args=(self.irc.nick, self.channel,
                                               'End of channel ban list')))
        self.assertEqual(self._takeAll(), [])

    def testBotOpResyncsNetBlacklistToo(self):
        self.assertNotError('blacklist net add foo netreason')
        self._drain()
        self._channelLostItsBans()
        self._opBot()
        bans = [m for m in self._takeAll()
                if m.command == 'MODE' and '+b' in m.args[1]]
        self.assertTrue(any('*!*@foo.host' in m.args for m in bans))

    def testNickBanEnforcedOnNickChange(self):
        # `add *cunt*` -> *cunt*!*@*; a member who changes into a matching
        # nick after joining must be caught too (Eggdrop re-checks on NICK).
        self.assertNotError('blacklist add *cunt* offensive')
        self._drain()
        self.assertTrue('*cunt*!*@*' in
                         self._cb().db['channels'][self.channel.lower()]['entries'])
        self.irc.feedMsg(ircmsgs.nick('cuntface', prefix='foo!foouser@foo.host'))
        msgs = self._takeAll()
        self.assertEqual(self._kicked(msgs), ['cuntface'])
        self.assertTrue(any(m.command == 'MODE' and '*cunt*!*@*' in m.args
                             for m in msgs))

    def testNickChangeIntoCleanNickIsLeftAlone(self):
        self.assertNotError('blacklist add *cunt* offensive')
        self._drain()
        self.irc.feedMsg(ircmsgs.nick('fooey', prefix='foo!foouser@foo.host'))
        self.assertEqual(self._takeAll(), [])

    def testNickChangeHonoursExempt(self):
        self.assertNotError('blacklist add *cunt* offensive')
        self._drain()
        self.assertNotError('blacklist exempt add *!*@foo.host')
        self._drain()
        self.irc.feedMsg(ircmsgs.nick('cuntface', prefix='foo!foouser@foo.host'))
        self.assertEqual(self._takeAll(), [])

    # -------------------------------------------------------------
    # Self-ban protection (Eggdrop's "I'm not going to ban myself" and
    # got_ban's immediate -b), plus kickOnSelfBan for whoever tried it.
    # -------------------------------------------------------------

    def _selfMask(self):
        return self._cb()._botHostmask(self.irc)

    def _joinAnop(self):
        self.irc.feedMsg(ircmsgs.join(self.channel, prefix='anop!op@op.__no_testcap__.host'))
        self._drain()

    def _botIsOpped(self):
        # Straight into the state: a +o MODE would trigger the ban resync.
        self.irc.state.channels[self.channel].ops.add(self.irc.nick)

    def testCommandsRefuseToBanTheBot(self):
        for cmd in ('add', 'timer', 'net add', 'net timer'):
            for target in ('*!*@*', self._selfMask()):
                self.assertRegexp('blacklist %s %s' % (cmd, target),
                                   r'not going to ban myself')
                self._drain()
        cb = self._cb()
        bucket = cb.db['channels'].get(self.channel.lower())
        self.assertTrue(not bucket or not bucket['entries'])
        self.assertEqual(cb.db['net']['entries'], {})

    def testReactToSelfBanKicksAnIrcOnlyOp(self):
        self._joinAnop()
        self._botIsOpped()
        msg = ircmsgs.privmsg(self.channel, 'x', prefix='anop!op@op.__no_testcap__.host')
        self._cb()._reactToSelfBan(self.irc, msg, self.channel)
        msgs = self._takeAll()
        self.assertEqual(self._kicked(msgs), ['anop'])
        kick = [m for m in msgs if m.command == 'KICK'][0]
        self.assertEqual(
            kick.args[2],
            conf.supybot.plugins.Blacklist.kickOnSelfBanReason.getValue(),
            'The kick must use kickOnSelfBanReason.')

    def testReactToSelfBanRespectsTheOption(self):
        self._joinAnop()
        self._botIsOpped()
        msg = ircmsgs.privmsg(self.channel, 'x', prefix='anop!op@op.__no_testcap__.host')
        conf.supybot.plugins.Blacklist.kickOnSelfBan.setValue(False)
        try:
            self._cb()._reactToSelfBan(self.irc, msg, self.channel)
            self.assertEqual(self._takeAll(), [])
        finally:
            conf.supybot.plugins.Blacklist.kickOnSelfBan.setValue(True)

    def testManualBanOnTheBotIsUndoneAndSetterKicked(self):
        self._joinAnop()
        self._botIsOpped()
        mask = self._selfMask()
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', mask),
                                       prefix='anop!op@op.__no_testcap__.host'))
        msgs = self._takeAll()
        self.assertTrue(any(m.command == 'MODE' and '-b' in m.args[1]
                             and mask in m.args for m in msgs),
                         'Expected the ban on the bot to be removed at once.')
        self.assertEqual(self._kicked(msgs), ['anop'])
        bucket = self._cb().db['channels'].get(self.channel.lower())
        self.assertTrue(not bucket or mask not in bucket['entries'],
                         'A ban on the bot must never be recorded.')

    def testManualBanOnTheBotWithoutKickOption(self):
        self._joinAnop()
        self._botIsOpped()
        conf.supybot.plugins.Blacklist.kickOnSelfBan.setValue(False)
        try:
            self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', '*!*@*'),
                                           prefix='anop!op@op.__no_testcap__.host'))
            msgs = self._takeAll()
        finally:
            conf.supybot.plugins.Blacklist.kickOnSelfBan.setValue(True)
        self.assertTrue(any(m.command == 'MODE' and '-b' in m.args[1] for m in msgs))
        self.assertEqual(self._kicked(msgs), [])

    def testServerSetBanOnTheBotIsUndoneWithoutKick(self):
        self._botIsOpped()
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', '*!*@*'),
                                       prefix='irc.server'))
        msgs = self._takeAll()
        self.assertTrue(any(m.command == 'MODE' and '-b' in m.args[1] for m in msgs))
        self.assertEqual(self._kicked(msgs), [])

    def testBanOnTheBotIgnoredWhenNotOpped(self):
        self._joinAnop()
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', '*!*@*'),
                                       prefix='anop!op@op.__no_testcap__.host'))
        self.assertEqual(self._takeAll(), [],
                          "Without ops the bot can neither unban nor kick.")

    def testResyncNeverReappliesAMaskMatchingTheBot(self):
        self._cb()._internal_add(self.channel, '*!*@*', 'someop', 'old entry',
                                  is_bot_cmd=True)
        self._channelLostItsBans()
        self._opBot()
        self.assertEqual(self._takeAll(), [])

    def _botUser(self, name, *caps):
        """A user with the bot, recognised by a hostmask the capability
        system takes seriously (testing short-circuits every hostmask that
        lacks __no_testcap__)."""
        u = ircdb.users.newUser()
        u.name = name
        u.addHostmask('%s!%s@%s.__no_testcap__.host' % (name, name, name))
        for cap in caps:
            u.addCapability(cap)
        ircdb.users.setUser(u)
        return '%s!%s@%s.__no_testcap__.host' % (name, name, name)

    def _channelMessages(self, msgs):
        return [m for m in msgs if m.command == 'PRIVMSG' and m.args[0] == self.channel]

    def testBotRegisteredOpIsNotKickedJustToldOff(self):
        prefix = self._botUser('trusty', '%s,op' % self.channel)
        self.irc.feedMsg(ircmsgs.join(self.channel, prefix=prefix))
        self._drain()
        self._botIsOpped()
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', '*!*@*'), prefix=prefix))
        msgs = self._takeAll()
        self.assertTrue(any(m.command == 'MODE' and '-b' in m.args[1] for m in msgs),
                         'The ban on the bot is still undone.')
        self.assertEqual(self._kicked(msgs), [])
        said = self._channelMessages(msgs)
        self.assertEqual(len(said), 1)
        reason = conf.supybot.plugins.Blacklist.kickOnSelfBanReason.getValue()
        self.assertEqual(said[0].args[1], 'trusty: ' + reason)

    def testBotAdminIsNotKickedEither(self):
        prefix = self._botUser('boss', 'admin')
        self.irc.feedMsg(ircmsgs.join(self.channel, prefix=prefix))
        self._drain()
        self._botIsOpped()
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', '*!*@*'), prefix=prefix))
        msgs = self._takeAll()
        self.assertEqual(self._kicked(msgs), [])
        self.assertEqual(len(self._channelMessages(msgs)), 1)

    def testOpOfAnotherChannelIsStillAnIrcOnlyOp(self):
        prefix = self._botUser('elsewhere', '#other,op')
        self.irc.feedMsg(ircmsgs.join(self.channel, prefix=prefix))
        self._drain()
        self._botIsOpped()
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', '*!*@*'), prefix=prefix))
        self.assertEqual(self._kicked(self._takeAll()), ['elsewhere'])

    def testCustomSelfBanReasonIsUsed(self):
        self._joinAnop()
        self._botIsOpped()
        conf.supybot.plugins.Blacklist.kickOnSelfBanReason.setValue('Not today.')
        try:
            self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', '*!*@*'),
                                           prefix='anop!op@op.__no_testcap__.host'))
            kick = [m for m in self._takeAll() if m.command == 'KICK'][0]
        finally:
            conf.supybot.plugins.Blacklist.kickOnSelfBanReason.setValue(
                conf.supybot.plugins.Blacklist.kickOnSelfBanReason._default)
        self.assertEqual(kick.args[2], 'Not today.')

    def testOptionOffSilencesTheTrustedReplyToo(self):
        prefix = self._botUser('quiet', '%s,op' % self.channel)
        self.irc.feedMsg(ircmsgs.join(self.channel, prefix=prefix))
        self._drain()
        self._botIsOpped()
        conf.supybot.plugins.Blacklist.kickOnSelfBan.setValue(False)
        try:
            self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', '*!*@*'), prefix=prefix))
            msgs = self._takeAll()
        finally:
            conf.supybot.plugins.Blacklist.kickOnSelfBan.setValue(True)
        self.assertTrue(any(m.command == 'MODE' and '-b' in m.args[1] for m in msgs))
        self.assertEqual(self._channelMessages(msgs), [])

    # -------------------------------------------------------------
    # Extban handling: add/timer/net add/net timer reject them with a
    # clear error; doMode's manual-ban auto-sync silently ignores them.
    # -------------------------------------------------------------

    def testExtbanRejectedOnAdd(self):
        self.assertRegexp('blacklist add ~account:baduser',
                           r'nick!user@host')
        self.assertRegexp('blacklist timer ~account:baduser',
                           r'nick!user@host')
        self.assertRegexp('blacklist net add ~account:baduser',
                           r'nick!user@host')
        self.assertRegexp('blacklist net timer ~account:baduser',
                           r'nick!user@host')

    def testExtbanLookalikesStillRejected(self):
        for bad in ('~account:baduser', '$a:baduser', 'account:baduser',
                    '~baduser', 'z:fingerprint'):
            self.assertRegexp('blacklist add %s' % bad, r'nick!user@host')

    def testNonAsciiMasksRejected(self):
        # Nicks are case-mapped in US-ASCII, so non-ASCII bans can't match
        # reliably: rejected both as a bare nick and as a full mask.
        for bad in ('caf\u00e9*', 'caf\u00e9*!*@*', '*!*@h\u00f6st.example'):
            self.assertRegexp('blacklist add %s' % bad, r'ASCII only')
            self.assertRegexp('blacklist timer %s' % bad, r'ASCII only')
            self.assertRegexp('blacklist net add %s' % bad, r'ASCII only')
        bucket = self._cb().db['channels'].get(self.channel.lower())
        self.assertTrue(not bucket or not bucket['entries'])

    def testUnknownNickCompletesLikeEggdrop(self):
        # Eggdrop's +ban: nick -> nick!*@*, user@host -> *!user@host,
        # nick!user -> nick!user@*  (the nick need not be around).
        for arg in ('bob', 'ident@some.host', 'carl!cident', 'bo?*'):
            self.assertNotError('blacklist add %s why' % arg)
            self._drain()
        bucket = self._cb().db['channels'][self.channel.lower()]
        self.assertEqual(
            sorted(bucket['entries']),
            sorted(['bob!*@*', '*!ident@some.host', 'carl!cident@*', 'bo?*!*@*']))

    def testUnknownNickCompletesForTimerAndNet(self):
        self.assertNotError('blacklist timer dave 5 why')
        self._drain()
        self.assertNotError('blacklist net add erin why')
        self._drain()
        cb = self._cb()
        self.assertTrue('dave!*@*' in
                         cb.db['channels'][self.channel.lower()]['entries'])
        self.assertTrue('erin!*@*' in cb.db['net']['entries'])

    def testKnownNickStillResolvesToItsHostmask(self):
        # foo is on the channel: the maskNumber template (default 2) is used,
        # not the lame nick ban.
        self.assertNotError('blacklist add foo why')
        self._drain()
        bucket = self._cb().db['channels'][self.channel.lower()]
        self.assertTrue('*!*@foo.host' in bucket['entries'])
        self.assertFalse('foo!*@*' in bucket['entries'])

    def testExtbanBareNickStillWorks(self):
        # A bare nick (no '@' at all) is legitimate input for add/timer --
        # it's a nick to resolve, not an attempted mask -- so it must NOT
        # be caught by the extban guard.
        self.assertNotError('blacklist add foo stillworks')
        self._drain()

    def testExtbanIPv6HostNotRejected(self):
        # A ':' AFTER the '@' (IPv6 literal host) must never be flagged --
        # only a ':' before the '@' means "not a plain hostmask".
        self.assertNotError('blacklist add *!*@2001:db8::1 ipv6reason')
        self._drain()
        self.assertRegexp('blacklist list', r'2001:db8::1')

    def testDoModeIgnoresExtban(self):
        # No prior +b -> the channel bucket is legitimately never created;
        # the ignored-extban assertion IS that it stays that way.
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', '~account:baduser'),
                                       prefix='anop!op@op.host'))
        self.irc.feedMsg(ircmsgs.mode(self.channel, ('+b', 'account:baduser'),
                                       prefix='anop!op@op.host'))
        bucket = self._cb()._get_channel_bucket(self.channel)
        self.assertTrue(bucket is None or (
            '~account:baduser' not in bucket['entries'] and
            'account:baduser' not in bucket['entries']),
            'Extban-shaped +b (with or without a leading prefix char) must never be tracked.')
