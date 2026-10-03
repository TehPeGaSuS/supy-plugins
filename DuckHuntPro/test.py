###
# Copyright (c) 2026, TehPeGaSuS
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
import random
import shutil
import tempfile
import re
import time
import urllib.parse
from datetime import datetime

from supybot.test import *
import supybot.schedule as schedule
import supybot.drivers as drivers
from supybot import ircdb, ircmsgs

from . import data
from . import db
from . import messages


class ScriptedRNG:
    """Returns pre-scripted values instead of real randomness, so
    probability-driven mechanics (accuracy/jam/golden rolls) are testable
    without flaky statistical assertions."""

    def __init__(self, values):
        self.values = list(values)

    def uniform(self, a, b):
        return self.values.pop(0) if self.values else a

    def randint(self, a, b):
        return self.values.pop(0) if self.values else a


class DuckHuntProTestCase(ChannelPluginTestCase):
    plugins = ('DuckHuntPro',)

    def _resetConfig(self):
        """Conf values are process-global and survive from one test method to
        the next, so a test that flips an option (and forgets to flip it
        back) silently changes every test that runs after it. Start each test
        from the registry defaults instead, and make the per-channel values
        inherit from them again (a channel value that was set explicitly stops
        following its parent)."""
        for name, value in conf.supybot.plugins.DuckHuntPro.getValues(getChildren=True):
            if '.web.' in name or '.#' in name or '.:' in name:
                continue     # the web group's callbacks start/stop the HTTP server
            if hasattr(value, '_default') and hasattr(value, 'setValue'):
                value.setValue(value._default)
                for child in list(getattr(value, '_children', {}).values()):
                    if hasattr(child, '_setValue'):
                        child._setValue(value.value, inherited=True)

    def setUp(self):
        super().setUp()
        self._resetConfig()
        conf.supybot.plugins.DuckHuntPro.enabled.setValue(True)
        self._cb()._postInitDone = True      # the post-init delay has "elapsed"
        self._cb()._floodState.clear()
        # Enabling the channel just now planned a day (the `enabled` hook); tests
        # start without one.
        self._cb()._cancelFlights(self.irc.network, self.channel)
        self._cb().db.channel(self.irc.network, self.channel)['planned_soarings'] = []
        # Drops are rolled per-key with a bottomless RNG queue in most
        # tests; leaving this on would let an exhausted ScriptedRNG queue
        # (which falls back to returning its lower bound, 1) silently
        # trigger a 'junk' drop on nearly every kill and queue an extra,
        # unexpected message. Dedicated drop-table tests re-enable it with
        # a fully-scripted queue.
        conf.supybot.plugins.DuckHuntPro.dropsEnabled.setValue(False)
        # Same reasoning: conf values are a process-global singleton that
        # persists across test methods, so a low flood limit set
        # by one antiflood-specific test would otherwise leak into every
        # later test that calls bang()/shop buy more than once. Off by
        # default here; the two antiflood tests re-enable it explicitly.
        conf.supybot.plugins.DuckHuntPro.antifloodEnabled.setValue(False)

    def _cb(self):
        return self.irc.getCallback('DuckHuntPro')

    def _key(self):
        return (self.irc.network.lower(), self.channel.lower())

    def _drain(self):
        while self.irc.takeMsg() is not None:
            pass

    def _drainWait(self, minCount, timeout=2.0):
        """Like _drain(), but polls (same pattern _feedMsg uses internally)
        instead of assuming every queued message is already sitting there --
        DuckHuntPro is `threaded = True`, so a command that calls irc.reply()
        several times in a loop can still be mid-loop in its background
        thread when a plain takeMsg() would already return None. Stops once
        at least minCount messages have been collected and takeMsg() goes
        quiet, or the timeout elapses."""
        msgs = []
        deadline = time.time() + timeout
        while True:
            m = self.irc.takeMsg()
            if m is not None:
                msgs.append(m)
                continue
            if len(msgs) >= minCount or time.time() >= deadline:
                return msgs
            time.sleep(0.01)
            drivers.run()

    def _richPlayer(self, nick=None):
        nick = nick or self.nick
        player = self._cb().db.player(self.irc.network, self.channel, nick)
        player['xp'] = 100000
        self._cb().db.save()
        return player

    def _addOnlineNick(self, nick):
        self.irc.state.channels[self.channel].addUser(nick)

    def _addHunter(self, nick, xp=0):
        """A channel member who has fired before, so accidents can hit them."""
        self._addOnlineNick(nick)
        p = self._cb().db.player(self.irc.network, self.channel, nick)
        p['xp'] = xp
        p['stats']['missed'] = 1
        self._cb().db.save()
        return p

    def _botOpped(self):
        self.irc.state.channels[self.channel].ops.add(self.irc.nick)

    def _sent(self):
        """Every message the bot queued so far, as (command, target, text)."""
        out = []
        while True:
            m = self.irc.takeMsg()
            if m is None:
                return out
            out.append((m.command, m.args[0], m.args[-1]))

    def _assertRendersNotFound(self, cb, path):
        # plugin.py's `_WebNotFound` gets a fresh class object each time the
        # plugin module is reloaded, so a class imported at test-module load
        # time won't `isinstance`-match what's actually raised -- compare by
        # name instead of identity.
        try:
            cb._renderWeb(path)
        except Exception as e:
            self.assertEqual(type(e).__name__, '_WebNotFound',
                              'Expected _WebNotFound, got %r' % (e,))
        else:
            self.fail('Expected _WebNotFound, nothing was raised')

    def _putDuck(self, is_golden=False, hp_total=1, is_fake=False):
        cb = self._cb()
        cb._activeDuck.setdefault(self._key(), []).append({
            'spawned_at': time.time(), 'is_golden': is_golden,
            'hp_total': hp_total, 'hp_left': hp_total, 'shots_fired': 0,
            'is_fake': is_fake,
        })
        return cb

    def testLevelTableSanity(self):
        self.assertEqual(len(data.LEVELS), 41)
        prev = None
        for lvl in data.LEVELS:
            if prev is not None:
                self.assertTrue(lvl.xp_threshold > prev,
                                 'level xp thresholds must strictly increase')
            prev = lvl.xp_threshold
            for pct in (lvl.accuracy, lvl.deflection, lvl.defense, lvl.jam_pct):
                self.assertTrue(0 <= pct <= 100, 'percentage field out of range: %r' % (lvl,))
            self.assertTrue(lvl.clip_size >= 1)
            self.assertTrue(lvl.clip_count >= 1)
        # Matches the source's documented starting condition.
        self.assertEqual(data.levelForXp(0), 1)

    def testLevelThresholdsAreAbsolute(self):
        # Expected values worked out from the Tcl get_level_and_grantings over
        # the cfg's level_grantings thresholds (-4, 20, 50, 90, ...), where a
        # player's level is the first row whose threshold their xp is below.
        expected = {-5: 0, -4: 1, 0: 1, 19: 1, 20: 2, 49: 2, 50: 3, 89: 3, 90: 4,
                    200: 6, 650: 11, 2090: 20, 3500: 26, 8199: 39, 8200: 40,
                    10000: 40, 10 ** 9: 40}
        for xp, level in expected.items():
            self.assertEqual(data.levelForXp(xp), level, 'xp %d' % xp)

    def testDailyRefillRestoresClipsToTheLevelCount(self):
        cb = self._cb()
        p = cb.db.player(self.irc.network, self.channel, 'foo')
        p['xp'] = 700          # level 12: 4 clips of 3
        p['clip_ammo'] = 1
        p['clips_left'] = 0
        fresh = cb.db.player(self.irc.network, self.channel, 'bar')
        fresh['xp'] = 700      # never initialised (clips_left is None)
        extra = cb.db.player(self.irc.network, self.channel, 'baz')
        extra['xp'] = 0
        extra['clip_ammo'] = 6
        extra['clips_left'] = 9   # e.g. from drops: refill resets to the level count
        self.assertTrue(cb._refillAmmo())
        self.assertEqual(p['clips_left'], data.LEVELS[data.levelForXp(700)].clip_count)
        self.assertEqual(p['clip_ammo'], 1, 'the clip in the gun is left alone')
        self.assertTrue(fresh['clips_left'] is None)
        self.assertEqual(extra['clips_left'], data.LEVELS[1].clip_count)
        self.assertFalse(cb._refillAmmo(), 'nothing left to change')

    def testRefillIsScheduledDailyAtTheConfiguredTime(self):
        cb = self._cb()
        for name in [n for n in cb._scheduled if n.startswith('DuckHuntPro:refill:')]:
            cb._unschedule(name)
        conf.supybot.plugins.DuckHuntPro.autoRefillAmmoTime.setValue('04:30')
        try:
            cb._scheduleAmmoRefill()
            names = [n for n in cb._scheduled if n.startswith('DuckHuntPro:refill:')]
            self.assertEqual(len(names), 1)
            at = float(names[0].rsplit(':', 1)[1])
            dt = datetime.fromtimestamp(at)
            self.assertEqual((dt.hour, dt.minute), (4, 30))
            self.assertTrue(time.time() < at <= time.time() + 86400 + 1)
        finally:
            conf.supybot.plugins.DuckHuntPro.autoRefillAmmoTime.setValue('00:00')
            for name in [n for n in cb._scheduled if n.startswith('DuckHuntPro:refill:')]:
                cb._unschedule(name)

    def testBackupIsScheduledDailyAtTheConfiguredTime(self):
        cb = self._cb()
        self.assertEqual(cb.registryValue('backupTime'), '00:03')
        for name in [n for n in cb._scheduled if n.startswith('DuckHuntPro:backup:')]:
            cb._unschedule(name)
        conf.supybot.plugins.DuckHuntPro.backupTime.setValue('05:15')
        cb._scheduleBackup()
        names = [n for n in cb._scheduled if n.startswith('DuckHuntPro:backup:')]
        self.assertEqual(len(names), 1)
        dt = datetime.fromtimestamp(float(names[0].rsplit(':', 1)[1]))
        self.assertEqual((dt.hour, dt.minute), (5, 15))
        cb._unschedule(names[0])

    def testBackupCopiesTheDatabaseFile(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, 'alice')['xp'] = 77
        cb.db.save()
        for name in [n for n in cb._scheduled if n.startswith('DuckHuntPro:backup:')]:
            cb._unschedule(name)
        try:
            os.unlink(cb.db.path + '.bak')
        except OSError:
            pass
        cb._fireBackup()
        with open(cb.db.path + '.bak') as f, open(cb.db.path) as g:
            self.assertEqual(f.read(), g.read())
        self.assertIn('"xp": 77', open(cb.db.path + '.bak').read())
        self.assertEqual(len([n for n in cb._scheduled if n.startswith('DuckHuntPro:backup:')]), 1)

    def testAmmoIsClampedWhenXpDropsToALowerLevel(self):
        cb = self._cb()
        p = cb.db.player(self.irc.network, self.channel, 'foo')
        p['xp'] = 40       # level 2: 6 rounds, 2 clips
        p['clip_ammo'] = 6
        p['clips_left'] = 2
        p['xp'] = -10      # below level 1's 20-xp threshold... and below -4: level 0
        cb._clampAmmo(p)
        lvl = data.LEVELS[data.levelForXp(p['xp'])]
        self.assertTrue(p['clip_ammo'] <= lvl.clip_size)
        self.assertTrue(p['clips_left'] <= lvl.clip_count)
        self.assertEqual(p['clips_left'], 1)   # level 0 only gets one clip

    def testBangKillsDuckAndGrantsXp(self):
        cb = self._putDuck()
        cb._rng = ScriptedRNG([100, 0])  # no jam, guaranteed hit
        self.assertNotError('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['xp'], data.XP_PER_DUCK)
        self.assertEqual(player['stats']['killed'], 1)
        self.assertTrue(self._key() not in cb._activeDuck)

    def testBangMissAppliesPenaltyAndTracksShots(self):
        cb = self._putDuck()
        key = self._key()
        cb._rng = ScriptedRNG([100, 100])  # no jam, miss
        self.assertNotError('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        # xp isn't floored at 0: a new player's miss takes them to -1
        self.assertEqual(player['xp'], data.LEVELS[1].xp_missed_shot)
        self.assertEqual(player['stats']['missed'], 1)
        self.assertEqual(cb._activeDuck[key][0]['shots_fired'], 1)

    def testDuckFleesAfterConfiguredMisses(self):
        conf.supybot.plugins.DuckHuntPro.shotsBeforeDuckFlee.setValue(1)
        cb = self._putDuck()
        key = self._key()
        cb._rng = ScriptedRNG([100, 100])
        self.assertNotError('bang')
        self.assertTrue(key not in cb._activeDuck)

    def testGoldenDuckRequiresMultipleHits(self):
        cb = self._putDuck(is_golden=True, hp_total=2)
        key = self._key()
        cb._rng = ScriptedRNG([100, 0])
        self.assertNotError('bang')
        self.assertTrue(key in cb._activeDuck)
        self.assertEqual(cb._activeDuck[key][0]['hp_left'], 1)

        cb._rng = ScriptedRNG([100, 0])
        self.assertNotError('bang')
        self.assertTrue(key not in cb._activeDuck)
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['xp'], data.BASE_XP_GOLDEN_DUCK * 2)
        self.assertEqual(player['stats']['golden_killed'], 1)

    def testJamBlocksShotAndDoesNotConsumeAmmo(self):
        cb = self._cb()
        cb._rng = ScriptedRNG([0])  # jam roll succeeds
        self.assertNotError('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertTrue(player['jammed'])
        self.assertEqual(player['stats']['jams'], 1)
        lvl = data.LEVELS[data.levelForXp(player['xp'])]
        # the jam is rolled before the bullet is spent, as in the original
        self.assertEqual(player['clip_ammo'], lvl.clip_size)

    # ---- parity with Duck_Hunt.tcl's reload_gun / display_stats / lastduck

    def _cmd(self, command, setup=None, private=False):
        """Runs `command` as the test user and returns what the bot sent.
        `setup(player)` may adjust the test user's profile first."""
        cb = self._cb()
        if setup:
            setup(cb.db.player(self.irc.network, self.channel, self.nick))
            cb.db.save()
        if private:
            msg = ircmsgs.privmsg(self.irc.nick, command, prefix=self.prefix)
        else:
            msg = ircmsgs.privmsg(self.channel, '%s: %s' % (self.irc.nick, command),
                                  prefix=self.prefix)
        self.irc.feedMsg(msg)
        deadline = time.time() + 2
        sent = []
        while not sent and time.time() < deadline:
            time.sleep(0.05)
            drivers.run()
            sent = self._sent()
        time.sleep(0.1)
        return sent + self._sent()

    def _tidy(self, p, ammo=6, clips=2, jammed=False, xp=0):
        p.update(xp=xp, clip_ammo=ammo, clips_left=clips, jammed=jammed)
        return p

    def _player(self):
        return self._cb().db.getPlayer(self.irc.network, self.channel, self.nick)

    def testReloadWithoutAProfileShowsTheLevelOneCapacities(self):
        sent = self._cmd('duckreload')
        self.assertEqual(self._texts(sent), [messages.tcl('en', 'm204', self.nick, 6, 6, 2, 2)])
        self.assertTrue(self._player() is None)      # reading doesn't create a profile

    def testReloadWhenUnarmed(self):
        sent = self._cmd('duckreload', setup=lambda p: p.update(gun_state='confiscated'))
        self.assertEqual(self._texts(sent), [messages.tcl('en', 'm5', self.nick)])

    def testReloadReloadsAnEmptyGunAndSpendsAClip(self):
        sent = self._cmd('duckreload', setup=lambda p: self._tidy(p, ammo=0, clips=2))
        self.assertEqual(self._texts(sent), [messages.tcl('en', 'm35', self.nick, '6/6', '1/2')])
        p = self._player()
        self.assertEqual((p['clip_ammo'], p['clips_left']), (6, 1))

    def testReloadDoesNotTopUpAPartlyFullClip(self):
        sent = self._cmd('duckreload', setup=lambda p: self._tidy(p, ammo=3, clips=2))
        self.assertEqual(self._texts(sent), [messages.tcl('en', 'm36', self.nick, '3/6', '2/2')])
        p = self._player()
        self.assertEqual((p['clip_ammo'], p['clips_left']), (3, 2))

    def testReloadUnjamsOnly(self):
        sent = self._cmd('duckreload', setup=lambda p: self._tidy(p, ammo=4, clips=2, jammed=True))
        self.assertEqual(self._texts(sent), [messages.tcl('en', 'm33', self.nick, '4/6', '2/2')])
        p = self._player()
        self.assertEqual((p['jammed'], p['clip_ammo'], p['clips_left']), (False, 4, 2))

    def testReloadUnjamsAndReloadsAnEmptyGun(self):
        sent = self._cmd('duckreload', setup=lambda p: self._tidy(p, ammo=0, clips=2, jammed=True))
        self.assertEqual(self._texts(sent), [messages.tcl('en', 'm32', self.nick, '6/6', '1/2')])
        p = self._player()
        self.assertEqual((p['jammed'], p['clip_ammo'], p['clips_left']), (False, 6, 1))

    def testReloadUnjamsAnEmptyGunWithNoClipsLeft(self):
        sent = self._cmd('duckreload', setup=lambda p: self._tidy(p, ammo=0, clips=0, jammed=True))
        self.assertEqual(self._texts(sent), [messages.tcl(
            'en', 'm31', self.nick, '\x03040\x03/6', '\x03040\x03/2')])
        p = self._player()
        self.assertEqual((p['jammed'], p['clip_ammo'], p['clips_left']), (False, 0, 0))

    def testReloadWithUnlimitedClipsKeepsTheCount(self):
        conf.supybot.plugins.DuckHuntPro.unlimitedAmmoClips.setValue(True)
        sent = self._cmd('duckreload', setup=lambda p: self._tidy(p, ammo=0, clips=0))
        self.assertEqual(self._texts(sent), [messages.tcl(
            'en', 'm35', self.nick, '6/6', messages.tcl('en', 'm65'))])
        self.assertEqual(self._player()['clips_left'], 0)

    def testReloadCountsReactionTimeWhileADuckFlies(self):
        cb = self._putDuck()
        cb._activeDuck[self._key()][0]['spawned_at'] -= 1.5
        self._cmd('duckreload', setup=lambda p: self._tidy(p))
        self.assertTrue(1400 <= self._player()['stats']['reflex_ms'] <= 2200)

    def _stats(self, setup=None, nick=None):
        sent = self._cmd('duckstats' + (' ' + nick if nick else ''), setup=setup)
        self.assertEqual([c for c, _, _ in sent], ['NOTICE'] * len(sent), sent)
        return '\n'.join(x for _, _, x in sent)

    def testDuckstatsOfAnUnknownNickShowsTheDefaults(self):
        text = self._stats(nick='ghost')
        self.assertIn('ammo: 6/6', text)
        self.assertIn('charg.: 2/2', text)
        self.assertIn('lvl 1 (', text)
        self.assertIn('karma: neutral', text)
        self.assertIn('best time: -', text)

    def testDuckstatsShowsTheOriginalSheet(self):
        def setup(p):
            self._tidy(p, ammo=4, clips=1, xp=70)
            p['stats'].update(killed=3, golden_killed=1, missed=1, empty_shots=2, humans_shot=0,
                              wild_shots=4, bullets_received=5, deaths=1, deflected=2,
                              jams=2, confiscations=1, best_time_ms=3500, reflex_ms=9000)
        text = self._stats(setup)
        lvl = data.LEVELS[data.levelForXp(70)]            # level 3
        self.assertIn('ammo: 4/6', text)
        self.assertIn('charg.: 1/2', text)
        self.assertIn('jammed: no (2 times)', text)
        self.assertIn('confisc.: no (1 times)', text)
        self.assertIn('70 xp', text)
        self.assertIn('lvl 3 (', text)
        self.assertIn('/ 20 xp pts for lvl sup.', text)
        # 4 wild, 0 humans, 3 ducks: 100 * (-4 + 6) / (4 + 6) = 20 -> good hunter
        self.assertIn('karma: \x03033\x17' if False else 'good hunter', text)
        self.assertIn('theor. accuracy: %d%%' % lvl.accuracy, text)
        self.assertIn('effectiv. of fire: 75%', text)
        self.assertIn('gun reliability: %d%%' % (100 - lvl.jam_pct), text)
        self.assertIn('armor: %d%%' % lvl.defense, text)
        self.assertIn('deflection: %d%%' % lvl.deflection, text)
        self.assertIn('best time: 3.5s', text)
        self.assertIn('average react. time: 3s', text)
        self.assertIn('3 ducks (incl. 1 golden duck)', text)
        self.assertIn('1 miss', text)
        self.assertIn('4 wild shots', text)
        self.assertIn('4 ammo used', text)
        self.assertIn('5 stray bullets', text)
        self.assertIn('1 lethal', text)
        self.assertIn('2 ricocheted', text)
        self.assertIn('2 neutralized', text)        # 5 received - 1 death - 2 ricochets
        self.assertIn('\n', text)                    # the sheet is several lines
        self.assertNotIn('Inventory', text)

    def testDuckstatsKarmaWording(self):
        cb = self._cb()
        self.assertEqual(cb._karma(self.channel, 0, 0, 0), 'neutral')
        self.assertIn('33.33%', cb._karma(self.channel, 4, 0, 1))
        self.assertIn('bad hunter', cb._karma(self.channel, 4, 0, 1))
        self.assertIn('good hunter', cb._karma(self.channel, 0, 0, 5))
        self.assertIn('100%', cb._karma(self.channel, 0, 0, 5))

    def testDuckstatsModifiersInventoryAndEffects(self):
        def setup(p):
            self._tidy(p)
            now = time.time()
            db.giveItem(p, 'grease', now, duration=86400)
            db.giveItem(p, 'sand', now, duration=None, uses=1, value='bob')
            db.giveItem(p, 'mirror_dazzle', now, duration=None, uses=1, value='bob')
            db.giveItem(p, 'sight', now, duration=None, uses=1)
            db.giveItem(p, 'silencer', now, duration=86400)
            db.giveItem(p, 'water_bucket', now, duration=3600, value='bob')
        text = self._stats(setup)
        self.assertIn('gun reliability: 85%\x0303+7%\x03\x0304-42%\x03', text)
        self.assertIn('theor. accuracy: 55%\x0304-27%\x03\x0303+15%\x03', text)
        self.assertIn('Inventory', text)
        self.assertIn('Grease \x0314/\x03 Sight \x0314/\x03 Silencer', text)
        self.assertIn('Effects', text)
        self.assertIn('Bedazzled \x0314/\x03 Sand \x0314/\x03 Soggy', text)

    def testDuckstatsAnotherPlayerGoesToTheAsker(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, 'bob')['stats']['killed'] = 2
        text = self._stats(nick='bob')
        self.assertIn('2 ducks', text)

    def testLastduckInTheChannel(self):
        self.assertEqual(self._texts(self._cmd('lastduck')),
                         [messages.tcl('en', 'm146', self.channel)])
        chan = self._cb().db.channel(self.irc.network, self.channel)
        chan['last_duck_at'] = time.time() - 3725
        self.assertEqual(self._texts(self._cmd('lastduck')), [messages.tcl(
            'en', 'm144', '1 hour 2 minutes and 5 seconds')])

    def testLastduckInNoticeMode(self):
        conf.supybot.plugins.DuckHuntPro.preferredDisplayMode.setValue(2)
        sent = self._cmd('lastduck')
        self.assertEqual([c for c, _, _ in sent], ['NOTICE'])

    def testLastduckByMessageIsANoticeWithTheChannelName(self):
        chan = self._cb().db.channel(self.irc.network, self.channel)
        chan['last_duck_at'] = time.time() - 65
        sent = self._cmd('lastduck %s' % self.channel, private=True)
        self.assertEqual(sent, [('NOTICE', self.nick, messages.tcl(
            'en', 'm147', self.channel, '1 minute and 5 seconds'))])
        conf.supybot.plugins.DuckHuntPro.enabled.setValue(False)
        sent = self._cmd('lastduck %s' % self.channel, private=True)
        self.assertEqual(sent, [('NOTICE', self.nick, messages.tcl(
            'en', 'm76', 'DuckHuntPro', self.channel))])

    def _bob(self):
        return self._cb().db.getPlayer(self.irc.network, self.channel, 'bob')

    def _unarmed(self, state):
        bob = self._cb().db.player(self.irc.network, self.channel, 'bob')
        bob['gun_state'] = state
        bob['stats']['confiscations'] = 0

    def testUnarmShowsItsSyntaxWithoutAnArgument(self):
        self.assertEqual(self._texts(self._cmd('unarm')),
                         [messages.tcl('en', 'm66', 'unarm')])
        self.assertEqual(self._texts(self._cmd('rearm')),
                         [messages.tcl('en', 'm71', 'rearm')])

    def testUnarmAnUnknownNickCreatesNoProfile(self):
        sent = self._cmd('unarm ghost')
        self.assertEqual(self._texts(sent), [messages.tcl('en', 'm67', self.nick, 'ghost', self.channel)])
        self.assertTrue(self._cb().db.getPlayer(self.irc.network, self.channel, 'ghost') is None)
        sent = self._cmd('rearm ghost')
        self.assertEqual(self._texts(sent), [messages.tcl('en', 'm67', self.nick, 'ghost', self.channel)])

    def testUnarmTemporarilyCountsOnlyTheFirstConfiscation(self):
        self._unarmed('armed')
        self._cmd('unarm bob')
        self.assertEqual((self._bob()['gun_state'], self._bob()['stats']['confiscations']),
                         ('confiscated', 1))
        sent = self._cmd('unarm bob')                       # already disarmed
        self.assertEqual(self._texts(sent), [messages.tcl('en', 'm130', self.nick, 'bob')])
        self.assertEqual(self._bob()['stats']['confiscations'], 1)

    def testUnarmTemporarilyDowngradesAPermanentConfiscation(self):
        self._unarmed('confiscated_permanent')
        sent = self._cmd('unarm bob')
        self.assertEqual(self._texts(sent), [messages.tcl('en', 'm128', self.nick, 'bob')])
        self.assertEqual(self._bob()['gun_state'], 'confiscated')

    def testUnarmStaticOnEveryStartingState(self):
        for state, mkey, args, count in (
                ('armed', 'm69', (self.nick, 'bob'), 1),
                ('confiscated', 'm70', (self.nick, 'bob'), 0),
                ('confiscated_permanent', 'm68', (self.nick, 'bob', 'bob'), 0)):
            self._unarmed(state)
            sent = self._cmd('unarm -static bob')
            self.assertEqual(self._texts(sent), [messages.tcl('en', mkey, *args)], state)
            self.assertEqual(self._bob()['gun_state'], 'confiscated_permanent', state)
            self.assertEqual(self._bob()['stats']['confiscations'], count, state)

    def testRearmOfAnArmedPlayerIsPuzzling(self):
        self._unarmed('armed')
        sent = self._cmd('rearm bob')
        self.assertEqual(self._texts(sent), [messages.tcl('en', 'm72', 'bob', self.nick)])

    def testRearmRestoresPermanentConfiscationsToo(self):
        self._unarmed('confiscated_permanent')
        self._cmd('rearm bob')
        self.assertEqual(self._bob()['gun_state'], 'armed')

    def testReloadClearsJam(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        player['jammed'] = True
        cb.db.save()
        self.assertNotError('duckreload')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertFalse(player['jammed'])

    def testReloadFullClipReportsNoOp(self):
        sent = self._cmd('duckreload', setup=lambda p: self._tidy(p))
        self.assertEqual(self._texts(sent), [messages.tcl('en', 'm36', self.nick, '6/6', '2/2')])

    def testReloadNoClipsLeftError(self):
        sent = self._cmd('duckreload', setup=lambda p: self._tidy(p, ammo=0, clips=0))
        self.assertEqual(self._texts(sent), [messages.tcl(
            'en', 'm34', self.nick, '\x03040\x03/6', '\x03040\x03/2')])

    def testEmptyClipMessage(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        player['clip_ammo'] = 0
        player['clips_left'] = 0
        cb.db.save()
        cb._rng = ScriptedRNG([100])   # the gun doesn't jam first
        self.assertRegexp('bang', 'EMPTY MAGAZINE')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['stats']['empty_shots'], 1)

    def testWildShotWhenNoDuck(self):
        cb = self._cb()
        self.assertTrue(self._key() not in cb._activeDuck)
        cb._rng = ScriptedRNG([100])  # no jam
        self.assertNotError('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['stats']['wild_shots'], 1)

    def testConfiscatedGunBlocksShot(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        player['gun_state'] = 'confiscated'
        cb.db.save()
        self.assertRegexp('bang', 'not armed')

    def testDuckstatsAndLastduck(self):
        cb = self._putDuck()
        cb._rng = ScriptedRNG([100, 0])
        self.assertNotError('bang')
        self.assertNotError('duckstats')
        self.assertNotError('lastduck')

    def testRestartReschedulesFutureFlight(self):
        cb = self._cb()
        network = self.irc.network
        cname = self.channel.lower()
        future = time.time() + 3600
        chan = cb.db.channel(network, self.channel)
        chan['planned_flights'] = [future]
        cb.db.save()
        name = "DuckHuntPro:flight:%s:%s:%r" % (network, cname, future)
        try:
            schedule.removeEvent(name)
        except KeyError:
            pass
        cb._reschedulePlannedFlights(self.irc)
        self.assertTrue(name in schedule.schedule.events,
                         'Future flight was not rescheduled after reload.')
        schedule.removeEvent(name)

    def testRestartPlansFreshDayWhenNoFutureFlights(self):
        cb = self._cb()
        network = self.irc.network
        cname = self.channel.lower()
        chan = cb.db.channel(network, self.channel)
        chan['planned_flights'] = []
        cb.db.save()
        planName = "DuckHuntPro:plan:%s:%s" % (network, cname)
        try:
            schedule.removeEvent(planName)
        except KeyError:
            pass
        cb._reschedulePlannedFlights(self.irc)
        self.assertTrue(planName in schedule.schedule.events,
                         'No fresh plan was scheduled for a channel with no future flights.')
        schedule.removeEvent(planName)

    def testSpawnDuckAnnouncesAndTracksGolden(self):
        cb = self._cb()
        key = self._key()
        # golden-chance roll (0 < ~5.5%), then HP roll -> 4
        cb._rng = ScriptedRNG([0, 4])
        cb._spawnDuck(self.irc, self.channel)
        self.assertTrue(key in cb._activeDuck)
        duck = cb._activeDuck[key][0]
        self.assertTrue(duck['is_golden'])
        self.assertEqual(duck['hp_total'], 4)
        m = self.irc.takeMsg()
        self.assertFalse(m is None)
        self.assertEqual(m.command, 'PRIVMSG')
        # Clean up the escape timer this spawned.
        cb._removeDuck(self.irc.network, self.channel)

    def testDuckshootersRanksByXp(self):
        cb = self._cb()
        network = self.irc.network
        cb.db.player(network, self.channel, 'alice')['xp'] = 100
        cb.db.player(network, self.channel, 'bob')['xp'] = 200
        cb.db.save()
        self.assertNotError('duckshooters')
        m = self.irc.takeMsg()
        self.assertTrue(m is not None and 'bob' in str(m))
        m = self.irc.takeMsg()
        self.assertTrue(m is not None and 'alice' in str(m))

    def testDuckshootersEmptyChannel(self):
        self.assertRegexp('duckshooters', 'yet')

    def testDuckshootersCountIsConfigurable(self):
        cb = self._cb()
        network = self.irc.network
        for i, nick in enumerate(['alice', 'bob', 'carol', 'dave', 'erin']):
            cb.db.player(network, self.channel, nick)['xp'] = 100 + i
        cb.db.save()
        conf.supybot.plugins.DuckHuntPro.topShootersCount.setValue(5)
        m = self.getMsg('duckshooters')  # header
        rest = self._drainWait(minCount=5)
        lines = [m.args[1]] + [r.args[1] for r in rest]
        self.assertEqual(len(lines), 6)  # header + 5 shooters
        self.assertTrue(any('erin' in line for line in lines))  # highest xp
        self.assertTrue(any('alice' in line for line in lines))  # lowest xp, still in top 5

    def testNextQuarterResetCalculation(self):
        cb = self._cb()
        jan15 = datetime(2026, 1, 15).timestamp()
        self.assertEqual(cb._nextQuarterReset(jan15), datetime(2026, 4, 1).timestamp())
        dec15 = datetime(2026, 12, 15).timestamp()
        self.assertEqual(cb._nextQuarterReset(dec15), datetime(2027, 1, 1).timestamp())
        exactlyApr1 = datetime(2026, 4, 1).timestamp()
        self.assertEqual(cb._nextQuarterReset(exactlyApr1), datetime(2026, 7, 1).timestamp())

    def testFireQuarterlyResetArchivesAndResetsStats(self):
        cb = self._cb()
        network = self.irc.network
        player = cb.db.player(network, self.channel, self.nick)
        player['xp'] = 250
        player['stats']['killed'] = 5
        cb.db.save()
        cb._fireQuarterlyReset()
        player = cb.db.getPlayer(network, self.channel, self.nick)
        self.assertEqual(player['xp'], 0)
        self.assertEqual(player['stats']['killed'], 0)
        archive = cb.db.lastArchive(network, self.channel)
        self.assertTrue(archive is not None)
        self.assertEqual(archive['standings'][0]['xp'], 250)

    def testDuckchampionsShowsLastArchive(self):
        cb = self._cb()
        network = self.irc.network
        player = cb.db.player(network, self.channel, self.nick)
        player['xp'] = 300
        cb.db.save()
        cb._fireQuarterlyReset()
        self._drain()  # the reset broadcasts a channel message; clear it first
        self.assertNotError('duckchampions')  # header line
        m = self.irc.takeMsg()
        self.assertTrue(m is not None and '300' in str(m))

    def testDuckchampionsEmptyBeforeAnyReset(self):
        self.assertRegexp('duckchampions', 'yet')

    def testRenderWebIndexListsChannels(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, self.nick)
        cb.db.save()
        body = cb._renderWeb('/')
        self.assertTrue(self.channel in body)

    def testRenderWebLeaderboardRendersPlayers(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        player['xp'] = 42
        cb.db.save()
        path = '/%s/%s/leaderboard' % (
            urllib.parse.quote(self.irc.network, safe=''),
            urllib.parse.quote(self.channel, safe=''))
        body = cb._renderWeb(path)
        self.assertTrue('42' in body)

    def testRenderWebChampionsBeforeAnyReset(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, self.nick)
        cb.db.save()
        path = '/%s/%s/champions' % (
            urllib.parse.quote(self.irc.network, safe=''),
            urllib.parse.quote(self.channel, safe=''))
        body = cb._renderWeb(path)
        self.assertTrue('No quarterly reset' in body)

    def testRenderWebShopPlaceholder(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, self.nick)
        cb.db.save()
        path = '/%s/%s/shop' % (
            urllib.parse.quote(self.irc.network, safe=''),
            urllib.parse.quote(self.channel, safe=''))
        body = cb._renderWeb(path)
        self.assertTrue('Phase 2' in body)

    def testRenderWebUnknownChannelRaises404(self):
        cb = self._cb()
        path = '/%s/%s/leaderboard' % (
            urllib.parse.quote(self.irc.network, safe=''),
            urllib.parse.quote('#neverjoined', safe=''))
        self._assertRendersNotFound(cb, path)

    def testHookUnhookLifecycle(self):
        # Limnoria's test harness stubs the real HTTP server under
        # world.testing (TestSupyHTTPServer.serve_forever is a no-op, see
        # src/httpserver.py) so a live socket request can't be exercised
        # here -- this only verifies hook()/unhook() run without raising
        # and toggle _httpRunning correctly. The doGetOrHead/_renderWeb
        # wiring itself is covered by the _renderWeb tests above, and the
        # hook/unhook call shape mirrors Factoids/Aka/Fediverse exactly.
        cb = self._cb()
        self.assertFalse(cb._httpRunning)
        cb._startHttp()
        self.assertTrue(cb._httpRunning)
        cb._stopHttp()
        self.assertFalse(cb._httpRunning)

    def testRenderWebUnknownPageRaises404(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, self.nick)
        cb.db.save()
        path = '/%s/%s/nonsense' % (
            urllib.parse.quote(self.irc.network, safe=''),
            urllib.parse.quote(self.channel, safe=''))
        self._assertRendersNotFound(cb, path)

    # -----------------------------------------------------------------
    # Phase 2: shop purchase mechanics
    # -----------------------------------------------------------------

    # ---- the shop command (port of ::DuckHunt::shop)

    def _shopRun(self, text='', xp=1000, setup=None):
        """Runs `shop <text>` for a player with `xp` xp and a full gun and
        returns the texts the bot sent."""
        def prep(p):
            lvl = data.LEVELS[data.levelForXp(xp)]
            self._tidy(p, ammo=lvl.clip_size, clips=lvl.clip_count, xp=xp)
            if setup:
                setup(p)
        sent = self._cmd(('shop ' + text).strip(), setup=prep)
        return [t for _, _, t in sent]

    def _target(self, nick='bob', **fields):
        """A known hunter who is in the channel."""
        self._addOnlineNick(nick)
        p = self._cb().db.player(self.irc.network, self.channel, nick)
        p.update(fields)
        self._cb().db.save()
        return p

    def _msg(self, key, *args, lang='en'):
        return messages.tcl(lang, key, *args)

    def _word(self, n, lang='en'):
        return messages.plural(n, self._msg('m285', lang=lang), self._msg('m286', lang=lang))

    def _okMsg(self, itemKey, mkey, *extra):
        """The purchase message for items whose text is (nick, cost, word)."""
        c = data.ITEM_COSTS[itemKey]
        return self._msg(mkey, self.nick, c, self._word(c), *extra)

    def _assertMsg(self, texts, key, *args):
        """One message equal to the catalogue entry, where the argument
        'WILDCARD' matches anything (a remaining-time span)."""
        pattern = re.escape(self._msg(key, *args)).replace('WILDCARD', '.+')
        self.assertEqual(len(texts), 1, texts)
        self.assertRegex(texts[0], '^%s$' % pattern)

    def _breadMsg(self, n):
        c = data.ITEM_COSTS['bread']
        return self._msg('m347', self.nick, c, self._word(c), n,
                         messages.plural(n, self._msg('m348'), self._msg('m349')), self.channel)

    def _xp(self):
        return self._player()['xp']

    def _item(self, p, key):
        return db.itemActive(p, key, time.time())

    def testShopNoArgumentListsTheCatalog(self):
        costs = [data.ITEM_COSTS[k] for k in data.SHOP_ITEMS]
        self.assertEqual(len(costs), 23)
        texts = self._shopRun()
        self.assertEqual(texts, [self._msg('m265', 'DuckHuntPro', *(costs + ['shop']))])
        self.assertEqual(self._xp(), 1000)
        # Listing is not a shop "activity" in Tcl (last_activity untouched).
        self.assertTrue(self._player()['last_activity'] is None)

    def testShopNoArgumentPointsToTheUrlWhenPreferred(self):
        conf.supybot.plugins.DuckHuntPro.shopPreferredDisplayMode.setValue(1)
        conf.supybot.plugins.DuckHuntPro.shopUrl.setValue('http://example.org/shop.html')
        self.assertEqual(self._shopRun(), [self._msg(
            'm263', 'DuckHuntPro', 'http://example.org/shop.html', 'shop')])

    def testShopSyntaxErrors(self):
        syntax = self._msg('m264', 'shop')
        for text in ('0', '24', 'abc', '01', '-1', '1 bob', '5 x', '23 x', '14', '15',
                     '16', '17', '14 a b', '1 2 3'):
            self.assertEqual(self._shopRun(text), [syntax], text)
        self.assertEqual(self._xp(), 1000)
        self.assertTrue(self._player()['last_activity'] is None)

    def testShopIsSilentWhenDisabled(self):
        conf.supybot.plugins.DuckHuntPro.shopEnabled.setValue(False)
        self.assertEqual(self._shopRun('1', setup=lambda p: p.update(clip_ammo=0)), [])
        self.assertEqual(self._xp(), 1000)

    def testShopRepliesFollowThePreferredDisplayMode(self):
        sent = self._cmd('shop 99')
        self.assertEqual(sent, [('PRIVMSG', self.channel, self._msg('m264', 'shop'))])
        conf.supybot.plugins.DuckHuntPro.preferredDisplayMode.setValue(2)
        sent = self._cmd('shop 99')
        self.assertEqual(sent, [('NOTICE', self.nick, self._msg('m264', 'shop'))])
        sent = self._cmd('shop 22', setup=lambda p: p.update(xp=1000))
        self.assertEqual(sent, [('NOTICE', self.nick, self._okMsg('duck_detector', 'm350'))])

    def testShopMessagesFollowTheChannelLanguage(self):
        conf.supybot.plugins.DuckHuntPro.language.setValue('fr')
        self.assertEqual(self._shopRun('1', xp=3, setup=lambda p: p.update(clip_ammo=0)),
                         [self._msg('m266', self.nick, lang='fr')])
        costs = data.ITEM_COSTS['sight']
        texts = self._shopRun('7')
        self.assertEqual(texts, [self._msg('m287', self.nick, costs, self._word(costs, 'fr'),
                                           lang='fr')])

    def testShopRefusesWhenTooPoorButStillCountsAsActivity(self):
        # 3 xp - 7 < 0 (the default floor).
        texts = self._shopRun('1', xp=3, setup=lambda p: p.update(clip_ammo=0))
        self.assertEqual(texts, [self._msg('m266', self.nick)])
        p = self._player()
        self.assertEqual((p['xp'], p['clip_ammo']), (3, 0))
        # Tcl stamps last_activity before the xp floor test.
        self.assertTrue(p['last_activity'] is not None)

    def testShopMinXpFloorIsConfigurable(self):
        # The floor test comes first, whatever the item: with the default
        # floor of 0, 10 xp cannot buy the 40 xp buyback even though the gun
        # is not confiscated (which would be the next refusal).
        self.assertEqual(self._shopRun('5', xp=10), [self._msg('m266', self.nick)])
        conf.supybot.plugins.DuckHuntPro.minXpForShopping.setValue(5)
        self.assertEqual(self._shopRun('5', xp=44), [self._msg('m266', self.nick)])
        self.assertEqual(self._shopRun('5', xp=45), [self._msg('m281', self.nick)])
        self.assertEqual(self._shopRun('1', xp=11, setup=lambda p: p.update(clip_ammo=0)),
                         [self._msg('m266', self.nick)])
        self.assertEqual(self._shopRun('1', xp=12, setup=lambda p: p.update(clip_ammo=0)),
                         [self._okMsg('extra_ammo', 'm268')])
        self.assertEqual(self._xp(), 12 - 7)
        conf.supybot.plugins.DuckHuntPro.minXpForShopping.setValue(-20)
        self.assertEqual(self._shopRun('1', xp=3, setup=lambda p: p.update(clip_ammo=0)),
                         [self._okMsg('extra_ammo', 'm268')])
        self.assertEqual(self._xp(), -4)

    def testShopDoesNothingForAPermanentlyConfiscatedGun(self):
        texts = self._shopRun('1', setup=lambda p: p.update(gun_state='confiscated_permanent',
                                                          clip_ammo=0))
        self.assertEqual(texts, [])
        p = self._player()
        self.assertEqual((p['xp'], p['clip_ammo'], p['gun_state']), (1000, 0, 'confiscated_permanent'))
        self.assertTrue(p['last_activity'] is None)

    def testShopStaysOpenForATemporarilyConfiscatedGun(self):
        confiscated = lambda p: p.update(gun_state='confiscated')
        # Items 1 and 2 need an armed gun...
        self.assertEqual(self._shopRun('1', setup=confiscated), [self._msg('m5', self.nick)])
        self.assertEqual(self._shopRun('2', setup=confiscated), [self._msg('m5', self.nick)])
        # ...everything else works, including the buyback.
        self.assertEqual(self._shopRun('6', setup=confiscated), [self._okMsg('grease', 'm284')])
        self.assertEqual(self._shopRun('5', setup=confiscated), [self._okMsg('buyback_weapon', 'm282')])
        self.assertEqual(self._player()['gun_state'], 'armed')

    def testBuyExtraAmmo(self):
        texts = self._shopRun('1', setup=lambda p: p.update(clip_ammo=0))
        self.assertEqual(texts, [self._okMsg('extra_ammo', 'm268')])
        p = self._player()
        self.assertEqual(p['clip_ammo'], 1)
        self.assertEqual(p['xp'], 1000 - data.ITEM_COSTS['extra_ammo'])
        self.assertTrue(p['last_activity'] is not None)

    def testBuyExtraAmmoRefusedWhenClipFull(self):
        self.assertEqual(self._shopRun('1'), [self._msg('m267', self.nick)])
        self.assertEqual(self._xp(), 1000)

    def testBuyExtraClip(self):
        texts = self._shopRun('2', setup=lambda p: p.update(clips_left=0))
        self.assertEqual(texts, [self._okMsg('extra_clip', 'm270')])
        p = self._player()
        self.assertEqual(p['clips_left'], 1)
        self.assertEqual(p['xp'], 1000 - data.ITEM_COSTS['extra_clip'])

    def testBuyExtraClipRefusedWhenReserveFull(self):
        self.assertEqual(self._shopRun('2'), [self._msg('m269', self.nick)])
        self.assertEqual(self._xp(), 1000)

    def testBuyApAmmoReplacesExplosiveAndRefusesToStack(self):
        def explosive(p):
            db.giveItem(p, 'explosive_ammo', time.time(), duration=86400)
        self.assertEqual(self._shopRun('3', setup=explosive), [self._okMsg('ap_ammo', 'm278')])
        p = self._player()
        self.assertTrue(self._item(p, 'ap_ammo') is not None)
        self.assertTrue(self._item(p, 'explosive_ammo') is None)
        self.assertTrue(85000 < p['items']['ap_ammo']['expires_at'] - time.time() <= 86400)
        self.assertEqual(p['xp'], 1000 - data.ITEM_COSTS['ap_ammo'])
        texts = self._shopRun('3', setup=lambda p: None, xp=p['xp'])
        self._assertMsg(texts, 'm277', self.nick, 'WILDCARD')
        self.assertEqual(self._xp(), p['xp'])

    def testBuyExplosiveAmmoReplacesApAndRefusesToStack(self):
        def ap(p):
            db.giveItem(p, 'ap_ammo', time.time(), duration=86400)
        self.assertEqual(self._shopRun('4', setup=ap), [self._okMsg('explosive_ammo', 'm279')])
        p = self._player()
        self.assertTrue(self._item(p, 'explosive_ammo') is not None)
        self.assertTrue(self._item(p, 'ap_ammo') is None)
        self._assertMsg(self._shopRun('4', xp=p['xp']), 'm277', self.nick, 'WILDCARD')

    def testBuyBuybackNeedsAConfiscatedGun(self):
        self.assertEqual(self._shopRun('5'), [self._msg('m281', self.nick)])
        self.assertEqual(self._xp(), 1000)

    def testBuyBuybackReturnsTheGun(self):
        texts = self._shopRun('5', setup=lambda p: p.update(gun_state='confiscated'))
        self.assertEqual(texts, [self._okMsg('buyback_weapon', 'm282')])
        p = self._player()
        self.assertEqual(p['gun_state'], 'armed')
        self.assertEqual(p['xp'], 1000 - data.ITEM_COSTS['buyback_weapon'])

    def testBuyGrease(self):
        self.assertEqual(self._shopRun('6'), [self._okMsg('grease', 'm284')])
        p = self._player()
        self.assertTrue(85000 < p['items']['grease']['expires_at'] - time.time() <= 86400)
        self.assertEqual(p['xp'], 1000 - data.ITEM_COSTS['grease'])
        self._assertMsg(self._shopRun('6', xp=p['xp']), 'm283', self.nick, 'WILDCARD')
        self.assertEqual(self._xp(), 1000 - data.ITEM_COSTS['grease'])

    def testBuySight(self):
        self.assertEqual(self._shopRun('7'), [self._okMsg('sight', 'm287')])
        p = self._player()
        self.assertEqual(p['items']['sight']['uses_left'], 1)
        self.assertTrue(p['items']['sight']['expires_at'] is None)
        self.assertEqual(self._shopRun('7', xp=p['xp']),
                         [self._msg('m288', self.nick, 1, self._msg('m292'))])

    def testBuyInfraredDetector(self):
        self.assertEqual(self._shopRun('8'), [self._okMsg('infrared_detector', 'm289')])
        p = self._player()
        self.assertEqual(p['items']['infrared_detector']['uses_left'], 6)
        self.assertEqual(p['xp'], 1000 - data.ITEM_COSTS['infrared_detector'])
        self._assertMsg(self._shopRun('8', xp=p['xp']), 'm295', self.nick, 'WILDCARD', 6,
                        self._msg('m293'))

    def testBuySilencer(self):
        self.assertEqual(self._shopRun('9'), [self._okMsg('silencer', 'm291')])
        p = self._player()
        self.assertTrue(self._item(p, 'silencer') is not None)
        self._assertMsg(self._shopRun('9', xp=p['xp']), 'm283', self.nick, 'WILDCARD')

    def testBuyFourLeafClover(self):
        self._cb()._rng = ScriptedRNG([7])
        c = data.ITEM_COSTS['four_leaf_clover']
        texts = self._shopRun('10')
        self.assertEqual(texts, [self._msg(
            'm294', self.nick, c, self._word(c), 7,
            '%s %s' % (self._msg('m286'), self._msg('m425')))])
        p = self._player()
        self.assertEqual(p['items']['four_leaf_clover']['value'], 7)
        self._assertMsg(self._shopRun('10', xp=p['xp']), 'm283', self.nick, 'WILDCARD')
        # A bonus of 1 uses the singular wording.
        self._cb()._rng = ScriptedRNG([1])
        texts = self._shopRun('10', setup=lambda p: p['items'].clear())
        self.assertEqual(texts, [self._msg(
            'm294', self.nick, c, self._word(c), 1,
            '%s %s' % (self._msg('m285'), self._msg('m424')))])

    def testBuySunglasses(self):
        self.assertEqual(self._shopRun('11'), [self._okMsg('sunglasses', 'm296')])
        p = self._player()
        self.assertTrue(self._item(p, 'sunglasses') is not None)
        self._assertMsg(self._shopRun('11', xp=p['xp']), 'm283', self.nick, 'WILDCARD')

    def testBuySpareClothes(self):
        self.assertEqual(self._shopRun('12'), [self._msg('m297', self.nick)])
        self.assertEqual(self._xp(), 1000)
        def wet(p):
            db.giveItem(p, 'water_bucket', time.time(), duration=3600, value='bob')
        self.assertEqual(self._shopRun('12', setup=wet), [self._okMsg('spare_clothes', 'm298')])
        p = self._player()
        self.assertTrue(self._item(p, 'water_bucket') is None)
        self.assertEqual(p['xp'], 1000 - data.ITEM_COSTS['spare_clothes'])

    def testBuyBrush(self):
        self.assertEqual(self._shopRun('13'), [self._msg('m299', self.nick)])
        self.assertEqual(self._xp(), 1000)
        now = time.time()
        def sand(p):
            db.giveItem(p, 'sand', now, uses=1, value='bob')
        def sabotage(p):
            db.giveItem(p, 'sabotage', now, uses=1, value='bob')
        def both(p):
            sand(p)
            sabotage(p)
        for setup in (sand, sabotage, both):
            self.assertEqual(self._shopRun('13', setup=lambda p: (p['items'].clear(), setup(p))),
                             [self._okMsg('brush', 'm300')])
            p = self._player()
            self.assertEqual(p['items'], {})
            self.assertEqual(p['xp'], 1000 - data.ITEM_COSTS['brush'])

    def testMirrorTargetChecks(self):
        self.assertEqual(self._shopRun('14 newbie'), [self._msg('m362', self.nick)])
        self._addOnlineNick('newbie')
        self.assertEqual(self._shopRun('14 newbie'), [self._msg('m362', self.nick)])
        self._cb().db.player(self.irc.network, self.channel, 'ghost')
        self.assertEqual(self._shopRun('14 ghost'), [self._msg('m363', self.nick, 'ghost')])
        self._target('bob', items={'mirror_dazzle': {'expires_at': None, 'uses_left': 1,
                                                       'value': 'x'}})
        self.assertEqual(self._shopRun('14 bob'), [self._msg('m324', self.nick, 'bob')])
        self.assertEqual(self._xp(), 1000)

    def testMirrorDazzlesTheTarget(self):
        self._target('bob')
        c = data.ITEM_COSTS['mirror']
        self.assertEqual(self._shopRun('14 bob'), [self._msg(
            'm326', self.nick, c, self._word(c), 'bob')])
        item = self._item(self._bob(), 'mirror_dazzle')
        self.assertEqual((item['value'], item['uses_left'], item['expires_at']),
                         (self.nick, 1, None))
        self.assertEqual(self._xp(), 1000 - c)

    def testMirrorChecksTheBuyersSunglassesNotTheTargets(self):
        c = data.ITEM_COSTS['mirror']
        # Tcl quirk: the sunglasses tested are the BUYER's, though the message
        # blames the target. The buyer pays and nothing happens.
        self._target('bob')
        def glasses(p):
            db.giveItem(p, 'sunglasses', time.time(), duration=86400)
        self.assertEqual(self._shopRun('14 bob', setup=glasses), [self._msg(
            'm325', self.nick, 'bob', c, self._word(c))])
        self.assertTrue(self._item(self._bob(), 'mirror_dazzle') is None)
        self.assertEqual(self._xp(), 1000 - c)
        # ...while a target wearing sunglasses is dazzled all the same.
        db.giveItem(self._bob(), 'sunglasses', time.time(), duration=86400)
        self.assertEqual(self._shopRun('14 bob', setup=lambda p: p['items'].clear()), [self._msg(
            'm326', self.nick, c, self._word(c), 'bob')])
        self.assertTrue(self._item(self._bob(), 'mirror_dazzle') is not None)

    def testMirrorCanTargetYourself(self):
        # Tcl has no "target yourself" refusal.
        self._addOnlineNick(self.nick)
        c = data.ITEM_COSTS['mirror']
        self.assertEqual(self._shopRun('14 %s' % self.nick), [self._msg(
            'm326', self.nick, c, self._word(c), self.nick)])
        self.assertTrue(self._item(self._player(), 'mirror_dazzle') is not None)

    def testSandTargetChecks(self):
        self.assertEqual(self._shopRun('15 newbie'), [self._msg('m362', self.nick)])
        self._cb().db.player(self.irc.network, self.channel, 'ghost')
        self.assertEqual(self._shopRun('15 ghost'), [self._msg('m364', self.nick, 'ghost')])
        self._target('bob', gun_state='confiscated')
        self.assertEqual(self._shopRun('15 bob'), [self._msg('m367', self.nick, 'bob')])
        self._bob()['gun_state'] = 'confiscated_permanent'
        self.assertEqual(self._shopRun('15 bob'), [self._msg('m367', self.nick, 'bob')])
        self._bob()['gun_state'] = 'armed'
        db.giveItem(self._bob(), 'sand', time.time(), uses=1, value='x')
        self.assertEqual(self._shopRun('15 bob'), [self._msg('m327', self.nick, 'bob')])
        self.assertEqual(self._xp(), 1000)

    def testSandJamsTheTargetAndGreaseAbsorbsIt(self):
        c = data.ITEM_COSTS['sand']
        bob = self._target('bob')
        self.assertEqual(self._shopRun('15 bob'), [self._msg(
            'm329', self.nick, 'bob', c, self._word(c))])
        self.assertEqual(self._item(bob, 'sand')['value'], self.nick)
        self.assertEqual(self._xp(), 1000 - c)
        # With grease on the target the sand has no effect (the grease goes).
        bob['items'].clear()
        db.giveItem(bob, 'grease', time.time(), duration=86400)
        self.assertEqual(self._shopRun('15 bob'), [self._msg(
            'm328', self.nick, 'bob', c, self._word(c))])
        self.assertTrue(self._item(bob, 'grease') is None)
        self.assertTrue(self._item(bob, 'sand') is None)
        self.assertEqual(self._xp(), 1000 - c)
        # A target already sanded is refused even when greased too.
        db.giveItem(bob, 'grease', time.time(), duration=86400)
        db.giveItem(bob, 'sand', time.time(), uses=1, value='x')
        self.assertEqual(self._shopRun('15 bob'), [self._msg('m327', self.nick, 'bob')])
        self.assertTrue(self._item(bob, 'grease') is not None)

    def testWaterBucket(self):
        self.assertEqual(self._shopRun('16 newbie'), [self._msg('m362', self.nick)])
        self._cb().db.player(self.irc.network, self.channel, 'ghost')
        self.assertEqual(self._shopRun('16 ghost'), [self._msg('m365', self.nick, 'ghost')])
        c = data.ITEM_COSTS['water_bucket']
        bob = self._target('bob')
        self.assertEqual(self._shopRun('16 bob'), [self._msg(
            'm331', self.nick, 'bob', c, self._word(c))])
        item = self._item(bob, 'water_bucket')
        self.assertTrue(3500 < item['expires_at'] - time.time() <= 3600)
        self.assertEqual(item['value'], self.nick)
        self.assertEqual(self._xp(), 1000 - c)
        self.assertEqual(self._shopRun('16 bob', xp=1000 - c), [self._msg('m330', self.nick, 'bob')])
        self.assertEqual(self._xp(), 1000 - c)

    def testWaterBucketIgnoresTheTargetsGun(self):
        self._target('bob', gun_state='confiscated')
        c = data.ITEM_COSTS['water_bucket']
        self.assertEqual(self._shopRun('16 bob'), [self._msg(
            'm331', self.nick, 'bob', c, self._word(c))])

    def testSabotage(self):
        self.assertEqual(self._shopRun('17 newbie'), [self._msg('m362', self.nick)])
        self._cb().db.player(self.irc.network, self.channel, 'ghost')
        self.assertEqual(self._shopRun('17 ghost'), [self._msg('m366', self.nick, 'ghost')])
        c = data.ITEM_COSTS['sabotage']
        bob = self._target('bob', gun_state='confiscated')
        self.assertEqual(self._shopRun('17 bob'), [self._msg('m368', self.nick, 'bob')])
        bob['gun_state'] = 'armed'
        self.assertEqual(self._shopRun('17 bob'), [self._msg(
            'm336', self.nick, 'bob', c, self._word(c))])
        self.assertEqual(self._item(bob, 'sabotage')['value'], self.nick)
        self.assertEqual(self._xp(), 1000 - c)
        self.assertEqual(self._shopRun('17 bob', xp=1000 - c), [self._msg('m335', self.nick, 'bob')])
        self.assertEqual(self._xp(), 1000 - c)

    def testTargetNameIsMatchedCaseInsensitively(self):
        bob = self._target('bob')
        c = data.ITEM_COSTS['sabotage']
        self.assertEqual(self._shopRun('17 BOB'), [self._msg(
            'm336', self.nick, 'BOB', c, self._word(c))])
        self.assertTrue(self._item(bob, 'sabotage') is not None)

    def testBuyLifeInsurance(self):
        self.assertEqual(self._shopRun('18'), [self._okMsg('life_insurance', 'm339')])
        p = self._player()
        item = p['items']['life_insurance']
        self.assertEqual(item['uses_left'], 1)
        self.assertTrue(600000 < item['expires_at'] - time.time() <= 604800)
        self._assertMsg(self._shopRun('18', xp=p['xp']), 'm295', self.nick, 'WILDCARD', 1,
                        self._msg('m292'))

    def testBuyLiabilityInsurance(self):
        self.assertEqual(self._shopRun('19'), [self._okMsg('liability_insurance', 'm342')])
        p = self._player()
        self.assertTrue(170000 < p['items']['liability_insurance']['expires_at']
                        - time.time() <= 172800)
        self._assertMsg(self._shopRun('19', xp=p['xp']), 'm283', self.nick, 'WILDCARD')

    def testBuyDecoySchedulesAPendingSpawn(self):
        cb = self._cb()
        cb._rng = ScriptedRNG([42])
        before = time.time()
        self.assertEqual(self._shopRun('20'), [self._okMsg('decoy', 'm344')])
        entry = cb.db.getChannel(self.irc.network, self.channel)['fake_ducks_pending'][0]
        self.assertEqual((entry['kind'], entry['force_non_golden'], entry['buyer']),
                         ('decoy', False, None))
        self.assertTrue(abs(entry['fires_at'] - (before + 42)) < 5)
        self.assertEqual(self._xp(), 1000 - data.ITEM_COSTS['decoy'])

    def testDecoyCanBeKeptFromAttractingGoldenDucks(self):
        conf.supybot.plugins.DuckHuntPro.decoysCanAttractGoldenDucks.setValue(False)
        self._shopRun('20')
        entry = self._cb().db.getChannel(self.irc.network, self.channel)['fake_ducks_pending'][0]
        self.assertTrue(entry['force_non_golden'])

    def _sleepNow(self):
        conf.supybot.plugins.DuckHuntPro.duckSleepHours.setValue(
            '%d' % datetime.fromtimestamp(time.time()).hour)

    def testDecoyAndBreadRefusedWhileTheDucksSleep(self):
        self._sleepNow()
        self.assertEqual(self._shopRun('20'), [self._msg('m388', self.nick)])
        self.assertEqual(self._shopRun('21'), [self._msg('m388', self.nick)])
        self.assertEqual(self._xp(), 1000)
        conf.supybot.plugins.DuckHuntPro.cantAttractDucksWhenSleeping.setValue(False)
        self.assertEqual(self._shopRun('20'), [self._okMsg('decoy', 'm344')])
        self.assertEqual(self._shopRun('21'), [self._breadMsg(1)])

    def testBuyBreadStacksAndTellsTheCount(self):
        cb = self._cb()
        calls = []
        cb._onBreadChanged = lambda network, channel, reason, who=None: calls.append(reason)
        c = data.ITEM_COSTS['bread']
        for n in (1, 2):
            self.assertEqual(self._shopRun('21'), [self._breadMsg(n)])
        self.assertEqual(calls, ['bread_added', 'bread_added'])
        chan = cb.db.getChannel(self.irc.network, self.channel)
        self.assertEqual(len(chan['bread']), 2)
        self.assertTrue(3500 < chan['bread'][0]['expires_at'] - time.time() <= 3600)
        self.assertEqual(self._xp(), 1000 - c)

    def testBreadIsRefusedAtTheCapButTheCapIsAnEqualityTest(self):
        cb = self._cb()
        chan = cb.db.channel(self.irc.network, self.channel)
        conf.supybot.plugins.DuckHuntPro.maxBreadOnChan.setValue(2)
        for _ in range(2):
            db.addBread(chan, time.time(), data.BREAD_DURATION)
        self.assertEqual(self._shopRun('21'), [self._msg('m387', self.nick, 2, self.channel)])
        self.assertEqual(self._xp(), 1000)
        self.assertEqual(len(chan['bread']), 2)
        # Tcl quirk: the test is `==`, so with more pieces than the cap
        # (the cap was lowered meanwhile) a purchase goes through.
        conf.supybot.plugins.DuckHuntPro.maxBreadOnChan.setValue(1)
        texts = self._shopRun('21')
        self.assertEqual(len(chan['bread']), 3)
        self.assertEqual(texts, [self._breadMsg(3)])

    def testBuyDuckDetector(self):
        self.assertEqual(self._shopRun('22'), [self._okMsg('duck_detector', 'm350')])
        p = self._player()
        self.assertEqual(p['items']['duck_detector']['uses_left'], 1)
        self.assertEqual(self._shopRun('22', xp=p['xp']),
                         [self._msg('m288', self.nick, 1, self._msg('m292'))])
        self.assertEqual(self._xp(), 1000 - data.ITEM_COSTS['duck_detector'])

    def testBuyFakeDuckSchedulesFixedDelaySpawn(self):
        cb = self._cb()
        before = time.time()
        self.assertEqual(self._shopRun('23'), [self._okMsg('fake_duck', 'm361')])
        entry = cb.db.getChannel(self.irc.network, self.channel)['fake_ducks_pending'][0]
        self.assertEqual(entry['kind'], 'fake_duck')
        self.assertTrue(entry['force_non_golden'])
        self.assertEqual(entry['buyer'], self.nick)
        self.assertTrue(abs(entry['fires_at'] - (before + data.FAKE_DUCK_DELAY)) < 5)
        self.assertEqual(self._xp(), 1000 - data.ITEM_COSTS['fake_duck'])

    def testFakeDuckHasNoSleepOrGunCheck(self):
        self._sleepNow()
        texts = self._shopRun('23', setup=lambda p: p.update(gun_state='confiscated'))
        self.assertEqual(texts, [self._okMsg('fake_duck', 'm361')])

    def testFireSpecialSpawnProducesFakeDuck(self):
        cb = self._cb()
        self._shopRun('23')
        chan = cb.db.getChannel(self.irc.network, self.channel)
        firesAt = chan['fake_ducks_pending'][0]['fires_at']
        cb._fireSpecialSpawn(self.irc.network, self.channel, firesAt)
        duck = cb._activeDuck[self._key()][0]
        self.assertTrue(duck['is_fake'])
        self.assertFalse(duck['is_golden'])
        cb._removeDuck(self.irc.network, self.channel)

    def testShopPurchaseThatDemotesAddsTheLevelDownText(self):
        # xp 272 is in level 7's range (clips of 4 x 3); 267 is level 6's.
        self.assertEqual(data.levelForXp(272), 7)
        self.assertEqual(data.levelForXp(267), 6)
        texts = self._shopRun('11', xp=272, setup=lambda p: p.update(clips_left=3))
        self.assertEqual(texts, [self._okMsg('sunglasses', 'm296') + self._msg(
            'm280', 6, messages.lvl2rank(6, 'en'))])
        p = self._player()
        self.assertEqual(p['xp'], 267)
        # The reserve is cut back to what the lower level allows.
        self.assertEqual(p['clips_left'], data.LEVELS[6].clip_count)

    def testShopRefusalNeverAddsTheLevelDownText(self):
        texts = self._shopRun('12', xp=272)
        self.assertEqual(texts, [self._msg('m297', self.nick)])

    def testShopUseDuringADuckAddsToTheReflexTime(self):
        cb = self._cb()
        self._putDuck()
        cb._activeDuck[self._key()][0]['spawned_at'] = time.time() - 5
        self._shopRun()
        self.assertTrue(5000 <= self._player()['stats']['reflex_ms'] < 9000)
        cb._removeDuck(self.irc.network, self.channel)

    def testBreadBoostsEscapeTimeAndPlannedFlightCount(self):
        cb = self._cb()
        self._richPlayer()
        network = self.irc.network
        chan = cb.db.channel(network, self.channel)
        db.addBread(chan, time.time(), data.BREAD_DURATION)
        db.addBread(chan, time.time(), data.BREAD_DURATION)
        cb.db.save()
        baseEscape = cb.registryValue('escapeTime', self.channel)
        self.assertEqual(cb._currentEscapeTime(network, self.channel, time.time()),
                          baseEscape + 2 * data.BREAD_ESCAPE_BONUS_PER_PIECE)
        cb._planDay(network, self.channel)
        expectedCount = (cb.registryValue('ducksPerDay', self.channel)
                          + 2 * data.BREAD_EXTRA_DUCKS_PER_PIECE)
        self.assertEqual(len(chan['planned_soarings']), expectedCount)

    def testDuckDetectorNotifiesOnNextSpawn(self):
        cb = self._cb()
        player = self._richPlayer()
        db.giveItem(player, 'duck_detector', time.time(), duration=None, uses=1)
        cb.db.save()
        cb._spawnDuck(self.irc, self.channel)
        notices = []
        m = self.irc.takeMsg()
        while m is not None:
            notices.append(m)
            m = self.irc.takeMsg()
        self.assertTrue(any(m.command == 'NOTICE' for m in notices))
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertTrue(db.itemActive(player, 'duck_detector', time.time()) is None)
        cb._removeDuck(self.irc.network, self.channel)

    # -----------------------------------------------------------------
    # Phase 2: bang()-time item effects
    # -----------------------------------------------------------------

    def testGreaseHalvesJamChance(self):
        cb = self._cb()
        player = self._richPlayer()  # level 40: jam_pct == 99
        db.giveItem(player, 'grease', time.time(), duration=86400)
        cb.db.save()
        self._putDuck()
        # 70 < 99 (would jam ungreased) but 70 >= 49.5 (halved) -- proves
        # the halving, not just "still sometimes jams".
        cb._rng = ScriptedRNG([70, 0])
        self.assertNotError('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertFalse(player['jammed'])

    def testSandDoublesJamChance(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        db.giveItem(player, 'sand', time.time(), duration=None, uses=1, value='bob')
        cb.db.save()
        self._putDuck()
        # level 0 jam_pct == 15; 20 >= 15 (wouldn't jam normally) but
        # 20 < 30 (doubled) -- proves the doubling, not just "still jams".
        cb._rng = ScriptedRNG([20])
        self.assertNotError('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertTrue(player['jammed'])
        self.assertTrue(db.itemActive(player, 'sand', time.time()) is None)

    def testSabotageForcesJamAndKicks(self):
        cb = self._cb()
        self._botOpped()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        db.giveItem(player, 'sabotage', time.time(), duration=None, uses=1, value='bob')
        cb.db.save()
        self._putDuck()
        # No jam-roll rng call at all: a sabotaged gun jams without rolling.
        cb._rng = ScriptedRNG([])
        # KICK is a high-priority IRC command in Limnoria's outgoing queue,
        # so it can jump ahead of the PRIVMSG queued before it: getMsg()
        # waits for the threaded command to finish, then scan everything.
        m = self.getMsg('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertTrue(player['jammed'])
        sent = [(m.command, m.args[0], m.args[-1])] if m else []
        sent += self._sent()
        self.assertTrue(any(c == 'KICK' and 'sabotage' in text for c, _, text in sent), sent)
        self.assertTrue(any('sabotage by bob' in text for c, _, text in sent), sent)

    def testInfraredBlocksWildShotWithoutConsumingAmmo(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        db.giveItem(player, 'infrared_detector', time.time(), duration=86400, uses=6)
        cb.db.save()
        cb._rng = ScriptedRNG([100])   # no jam
        self.assertRegexp('bang', 'Trigger locked')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['clip_ammo'], data.LEVELS[1].clip_size)  # not spent
        item = db.itemActive(player, 'infrared_detector', time.time())
        self.assertEqual(item['uses_left'], 5)

    def testInfraredDoesNothingWhenDuckPresent(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        db.giveItem(player, 'infrared_detector', time.time(), duration=86400, uses=6)
        cb.db.save()
        self._putDuck()
        cb._rng = ScriptedRNG([100, 0])  # no jam, hit
        self.assertNotError('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        item = db.itemActive(player, 'infrared_detector', time.time())
        self.assertEqual(item['uses_left'], 6)  # not consumed

    def testSilencerPreventsScaringDucksAway(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.shotsBeforeDuckFlee.setValue(1)
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        db.giveItem(player, 'silencer', time.time(), duration=86400)
        cb.db.save()
        self._putDuck()
        cb._rng = ScriptedRNG([100, 100])  # no jam, miss
        self.assertNotError('bang')
        self.assertTrue(self._key() in cb._activeDuck)  # didn't flee
        self.assertEqual(cb._activeDuck[self._key()][0]['shots_fired'], 0)

    def testSightBoostsAccuracyForOneShotThenConsumed(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        lvl = data.LEVELS[data.levelForXp(player['xp'])]
        db.giveItem(player, 'sight', time.time(), duration=None, uses=1)
        cb.db.save()
        self._putDuck()
        boosted = lvl.accuracy + int((100 - lvl.accuracy) / 3)
        rollValue = (lvl.accuracy + boosted) / 2.0  # between base and boosted
        cb._rng = ScriptedRNG([100, rollValue])  # no jam, roll between the two
        self.assertNotError('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['stats']['killed'], 1)  # hit thanks to the boost
        self.assertTrue(db.itemActive(player, 'sight', time.time()) is None)

    def testMirrorDazzleHalvesAccuracyThenConsumed(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        lvl = data.LEVELS[data.levelForXp(player['xp'])]
        db.giveItem(player, 'mirror_dazzle', time.time(), duration=None, uses=1, value='bob')
        cb.db.save()
        self._putDuck()
        rollValue = (lvl.accuracy + lvl.accuracy / 2.0) / 2.0  # between halved and base
        cb._rng = ScriptedRNG([100, rollValue])
        self.assertRegexp('bang', 'dazzled')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['stats']['missed'], 1)  # missed thanks to the halving
        self.assertTrue(db.itemActive(player, 'mirror_dazzle', time.time()) is None)

    # ---- parity with Duck_Hunt.tcl's shoot -----------------------------

    def _bangSent(self):
        first = self.getMsg('bang')
        time.sleep(0.1)       # the command's thread may still be queueing
        sent = [(first.command, first.args[0], first.args[-1])] if first else []
        return sent + self._sent()

    def _texts(self, sent, command='PRIVMSG'):
        return [text for c, _, text in sent if c == command]

    def testJammedGunStillEatsSandAndSabotage(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        player['jammed'] = True
        db.giveItem(player, 'sand', time.time(), duration=None, uses=1, value='bob')
        db.giveItem(player, 'sabotage', time.time(), duration=None, uses=1, value='bob')
        cb.db.save()
        sent = self._bangSent()
        self.assertTrue(any('JAMMED GUN' in x for x in self._texts(sent)), sent)
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertTrue(db.itemActive(player, 'sand', time.time()) is None)
        self.assertTrue(db.itemActive(player, 'sabotage', time.time()) is None)

    def testWildFireCostsTheMissAndTheWildFirePenalty(self):
        cb = self._cb()
        cb._rng = ScriptedRNG([100])    # no jam; nobody to hit afterwards
        sent = self._bangSent()
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        lvl = data.LEVELS[1]
        self.assertEqual(player['xp'], lvl.xp_missed_shot + lvl.xp_wild_shot)
        self.assertEqual(player['stats']['missed'], 1)
        self.assertEqual(player['stats']['wild_shots'], 1)
        self.assertTrue(any('Luckily you missed' in x and '[missed: -1 xp]' in x
                            and '[wild fire: -1 xp]' in x for x in self._texts(sent)), sent)

    def _levelOneHit(self, roll, items):
        """Shoots a level-1 player (55 accuracy) holding `items` with the
        accuracy roll `roll`; returns whether the duck was killed."""
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        for key in items:
            db.giveItem(player, key, time.time(), duration=None, uses=1, value='bob')
        cb.db.save()
        self._putDuck()
        cb._rng = ScriptedRNG([100, roll])
        self.assertNotError('bang')
        return self._key() not in cb._activeDuck

    def testMirrorHalvesAccuracyBeforeTheSightAddsItsThird(self):
        # 55 -> int(55/2) = 27, then + int((100 - 55) / 3) = 15  ->  42
        # (sight first and halving after would give 35)
        self.assertTrue(self._levelOneHit(41.9, ['mirror_dazzle', 'sight']))

    def testMirrorAndSightBoundary(self):
        self.assertFalse(self._levelOneHit(42, ['mirror_dazzle', 'sight']))

    def testSightAndMirrorAreSpentEvenOnAWildShot(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        for key in ('sight', 'mirror_dazzle'):
            db.giveItem(player, key, time.time(), duration=None, uses=1, value='bob')
        cb.db.save()
        cb._rng = ScriptedRNG([100])
        self.assertNotError('bang')       # no duck: wild fire
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertTrue(db.itemActive(player, 'sight', time.time()) is None)
        self.assertTrue(db.itemActive(player, 'mirror_dazzle', time.time()) is None)

    def _jamLevel(self, jam):
        for i, lvl in enumerate(data.LEVELS[:-1]):
            if lvl.jam_pct == jam:
                return lvl, (data.LEVELS[i - 1].xp_threshold if i else 0)

    def testGreaseHalvesJamWithIntegerDivision(self):
        cb = self._cb()
        lvl, xp = self._jamLevel(1)
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        player['xp'] = xp
        db.giveItem(player, 'grease', time.time(), duration=86400)
        cb.db.save()
        cb._rng = ScriptedRNG([0, 100])   # a 1% gun would jam on 0; int(1/2) = 0 can't
        self.assertNotError('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertFalse(player['jammed'])

    def testSandDoublesTheJamChance(self):
        for roll, jams in ((29.9, True), (30, False)):
            cb = self._cb()
            player = cb.db.player(self.irc.network, self.channel, self.nick)
            player.update(jammed=False, xp=0, clip_ammo=None, clips_left=None)
            player['items'].clear()
            db.giveItem(player, 'sand', time.time(), duration=None, uses=1, value='bob')
            cb.db.save()
            cb._rng = ScriptedRNG([roll, 100])     # level 1 jams 15% -> 30% with sand
            self.assertNotError('bang')
            self._drain()
            self.assertEqual(cb.db.getPlayer(self.irc.network, self.channel,
                                             self.nick)['jammed'], jams, roll)

    def _flee(self, golden=0, count=2, shots=2):
        cb = self._cb()
        for i in range(count):
            self._putDuck(is_golden=i < golden)
            cb._activeDuck[self._key()][-1]['shots_fired'] = shots
        cb._rng = ScriptedRNG([100, 100])    # no jam, miss
        return self._texts(self._bangSent())

    def testAllDucksFleeAnnouncement(self):
        self.assertTrue(any('all ducks fled' in x for x in self._flee(count=2)))

    def testSomeDucksFleeAnnouncements(self):
        sent = self._flee(golden=1, count=3)       # the golden duck can't flee
        self.assertTrue(any('2 ducks fled' in x for x in sent), sent)

    def testOneOfSeveralDucksFleeAnnouncement(self):
        sent = self._flee(golden=1, count=2)
        self.assertTrue(any('a duck fled' in x for x in sent), sent)

    def testTheOnlyDuckFleeAnnouncement(self):
        sent = self._flee(count=1)
        self.assertTrue(any('the duck fled' in x for x in sent), sent)

    def testMissingIntoALowerLevelAnnouncesTheDemotion(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        player['xp'] = data.LEVELS[1].xp_threshold          # level 2, one xp over
        cb.db.save()
        self._putDuck()
        cb._rng = ScriptedRNG([100, 100])
        sent = self._bangSent()
        self.assertTrue(any('is demoted to level 1' in x for x in self._texts(sent)), sent)

    def testMissIsANoticeWhenPreferredDisplayModeIsTwo(self):
        self._putDuck()
        self._cb()._rng = ScriptedRNG([100, 100])
        conf.supybot.plugins.DuckHuntPro.preferredDisplayMode.setValue(2)
        try:
            sent = self._bangSent()
        finally:
            conf.supybot.plugins.DuckHuntPro.preferredDisplayMode.setValue(1)
        self.assertTrue(any(c == 'NOTICE' and 'Missed.' in x for c, _, x in sent), sent)

    def testMonochromeStripsTheFormatting(self):
        self._putDuck()
        self._cb()._rng = ScriptedRNG([100, 100])
        conf.supybot.plugins.DuckHuntPro.monochrome.setValue(True)
        try:
            sent = self._bangSent()
        finally:
            conf.supybot.plugins.DuckHuntPro.monochrome.setValue(False)
        text = [x for x in self._texts(sent) if 'Missed.' in x]
        self.assertTrue(text and '\x03' not in text[0] and '\x02' not in text[0], sent)

    def testReactionTimeAccumulatesWhileADuckFlies(self):
        cb = self._putDuck()
        cb._activeDuck[self._key()][0]['spawned_at'] -= 2.0
        cb._rng = ScriptedRNG([100, 100])
        self.assertNotError('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertTrue(1900 <= player['stats']['reflex_ms'] <= 2500, player['stats'])

    def testKickOnWildFireIsOptIn(self):
        cb = self._cb()
        self._botOpped()
        cb._rng = ScriptedRNG([100])
        sent = self._bangSent()
        self.assertEqual(self._texts(sent, 'KICK'), [])
        conf.supybot.plugins.DuckHuntPro.kickOnWildFire.setValue(True)
        try:
            cb._rng = ScriptedRNG([100])
            sent = self._bangSent()
        finally:
            conf.supybot.plugins.DuckHuntPro.kickOnWildFire.setValue(False)
        self.assertTrue(any('Who are you aiming at' in x for x in self._texts(sent, 'KICK')), sent)

    def testWildFireConfiscationAddsItsTag(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.gunConfiscationOnWildFire.setValue(True)
        try:
            cb._rng = ScriptedRNG([100])
            sent = self._bangSent()
        finally:
            conf.supybot.plugins.DuckHuntPro.gunConfiscationOnWildFire.setValue(False)
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['gun_state'], 'confiscated')
        self.assertTrue(any('GUN CONFISCATED: wild fire' in x for x in self._texts(sent)), sent)

    def testAccidentMessageCarriesThePenaltiesOnce(self):
        cb = self._cb()
        self._addHunter('bob')
        self._putDuck()
        cb._rng = ScriptedRNG([100, 100, 0, 0, 100, 100])   # ...victim hit outright
        sent = self._bangSent()
        shot = [x for x in self._texts(sent) if 'just get shot by accident by' in x]
        self.assertEqual(len(shot), 1, sent)
        self.assertIn('[missed: -1 xp]', shot[0])
        self.assertIn('[accident: -4 xp]', shot[0])

    # ---- parity with Duck_Hunt.tcl's hit_a_duck / duck_soaring ----------

    def _shot(self, roll=0):
        """A clean hit on the oldest duck; returns the messages sent."""
        self._cb()._rng = ScriptedRNG([100, roll])    # no jam, then the accuracy roll
        return self._texts(self._bangSent())

    def testKillAnnouncementUsesTheOriginalWording(self):
        self._putDuck()
        kill = [x for x in self._shot() if 'You shot down the duck in' in x]
        self.assertEqual(len(kill), 1)
        self.assertIn('which makes you a total of 1 duck on #test', kill[0])
        self.assertIn('[10 xp]', kill[0])
        self.assertIn('*BANG*', kill[0])

    def testTunableNumbersDefaultToTheOriginalsValues(self):
        cb = self._cb()
        self.assertEqual((cb.registryValue('xpPerDuck'), cb.registryValue('xpPerGoldenDuckHp'),
                          cb.registryValue('chanceRicochetTowardsDuck')), (10, 12, 10))
        self.assertEqual([cb.registryValue('chancesToHitSomeoneElse.' + k)
                          for k in ('upTo10', 'upTo20', 'upTo30', 'above30')], [10, 12, 14, 15])
        self.assertEqual([cb.registryValue('chancesWildFireHitSomeone.' + k)
                          for k in ('upTo10', 'upTo20', 'upTo30', 'above30')], [1, 2, 3, 4])
        self.assertEqual(cb.registryValue('shopCosts.fake_duck'), 50)
        self.assertEqual(cb.registryValue('dropChances.junk'), 20)

    def testXpPerDuckIsConfigurable(self):
        conf.supybot.plugins.DuckHuntPro.xpPerDuck.setValue(25)
        self._putDuck()
        kill = [x for x in self._shot() if 'You shot down the duck in' in x]
        self.assertIn('[25 xp]', kill[0])

    def testShopCostsAreConfigurable(self):
        conf.supybot.plugins.DuckHuntPro.shopCosts.extra_ammo.setValue(3)
        self._shopRun('1', setup=lambda p: p.update(clip_ammo=0))
        self.assertEqual(self._player()['xp'], 1000 - 3)

    def testDropChancesAreConfigurable(self):
        cb = self._cb()
        for key in data.DROP_TABLE:
            getattr(conf.supybot.plugins.DuckHuntPro.dropChances, key).setValue(0)
        conf.supybot.plugins.DuckHuntPro.dropChances.sight.setValue(1000)
        conf.supybot.plugins.DuckHuntPro.dropsEnabled.setValue(True)
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        cb._rollAndApplyDrop(self.channel, player, self.nick, time.time())
        self.assertIn('sight', player['items'])

    def testAccidentChancesAreConfigurable(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.chancesWildFireHitSomeone.upTo10.setValue(77)
        self.assertEqual(data.accidentChance(5, False, [(10, 77), (None, 1)]), 77)
        # the plugin builds the same table from the settings
        self.assertEqual(cb.registryValue('chancesWildFireHitSomeone.upTo10'), 77)

    def _networkSetting(self, name, value):
        setting = getattr(conf.supybot.plugins.DuckHuntPro, name).getSpecific(network=self.irc.network)
        old = setting.value
        self.addCleanup(setting.setValue, old)
        setting.setValue(value)

    def testKicksCanGoThroughChanServ(self):
        self._networkSetting('kickViaChanServ', True)
        self._cb()._kickIfOpped(self.irc, self.channel, 'bob', 'boom now')
        self.assertEqual(self._sent(), [('CS', 'KICK', 'boom now')])

    def testChanServKickLineIsPerNetworkAndCustomisable(self):
        self._networkSetting('kickViaChanServ', True)
        self._networkSetting('chanServKickLine', 'PRIVMSG X@channels.undernet.org :KICK {channel} {nick} {reason}')
        self._cb()._kickIfOpped(self.irc, self.channel, 'bob', 'you got shot')
        self.assertEqual(self._sent(), [('PRIVMSG', 'X@channels.undernet.org',
                                         'KICK %s bob you got shot' % self.channel)])

    def testBadChanServKickLineSendsNothing(self):
        self._networkSetting('kickViaChanServ', True)
        self._networkSetting('chanServKickLine', '')
        self._cb()._kickIfOpped(self.irc, self.channel, 'bob', 'x')
        self.assertEqual(self._sent(), [])

    def testKickSettingsAreOffByDefaultAndPerNetwork(self):
        cb = self._cb()
        self.assertFalse(cb.registryValue('kickViaChanServ', network=self.irc.network))
        self.assertEqual(cb.registryValue('chanServKickLine', network=self.irc.network),
                         'CS KICK {channel} {nick} :{reason}')
        self.assertFalse(cb.registryValue('kickViaChanServ', network='othernet'))

    def testStrayBulletExemptCapability(self):
        cb = self._cb()
        self._addHunter('bob')
        self._addHunter('carol')
        conf.supybot.plugins.DuckHuntPro.strayBulletExemptCapability.setValue('duckhuntpro.exempt')
        real = ircdb.checkCapability
        ircdb.checkCapability = lambda prefix, cap, *a, **kw: (
            cap == 'duckhuntpro.exempt' and prefix.startswith('bob!'))
        state = self.irc.state
        state.nickToHostmask = lambda nick: '%s!u@h' % nick
        try:
            picks = set()
            for roll in (0, 0):
                cb._rng = ScriptedRNG([roll])
                picks.add(cb._pickAccidentVictim(self.irc, self.channel, self.irc.network, 'nobody'))
            self.assertNotIn('bob', picks)
            self.assertIn('carol', picks)
        finally:
            ircdb.checkCapability = real
            del state.nickToHostmask

    def testSeasonCommandsSpeakFrenchToo(self):
        conf.supybot.plugins.DuckHuntPro.language.setValue('fr')
        self.assertEqual(self._texts(self._cmd('duckshooters')),
                         [self.nick + ': ' + messages.get('fr', 'shooters_empty')])
        self.assertEqual(self._texts(self._cmd('duckchampions')),
                         [self.nick + ': ' + messages.get('fr', 'champions_empty')])
        self.assertIn('Meilleurs', messages.get('fr', 'shooters_header'))
        self.assertNotEqual(messages.get('fr', 'quarterly_reset'), messages.get('en', 'quarterly_reset'))

    def testKillingOneOfSeveralDucksSaysOneOfTheDucks(self):
        self._putDuck()
        self._putDuck()
        sent = self._shot()
        self.assertTrue(any('You shot down one of the ducks in' in x for x in sent), sent)

    def testKillTotalPluralises(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, self.nick)['stats']['killed'] = 1
        self._putDuck()
        sent = self._shot()
        self.assertTrue(any('a total of 2 ducks on #test' in x for x in sent), sent)

    def testLevelUpIsAppendedToTheKillLine(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, self.nick)['xp'] = 15   # level 1, 5 short
        self._putDuck()
        sent = self._shot()
        self.assertTrue(any('You are promoted to level 2 (' in x for x in sent), sent)

    def testRicochetKillAnnouncementCarriesTheLuckyShotTag(self):
        cb = self._cb()
        self._addHunter('bob', xp=1000)
        self._putDuck()
        cb._rng = ScriptedRNG([100, 100, 0, 0, 0, 0])   # miss, accident, deflect, ricochet to duck
        sent = self._texts(self._bangSent())
        self.assertTrue(any('by ricochet' in x and '[lucky shot]' in x for x in sent), sent)

    def testMechanicalDuckKillNamesItsBuyerAndPaysNothing(self):
        cb = self._putDuck(is_fake=True)
        cb._activeDuck[self._key()][-1]['author'] = 'bob'
        sent = self._shot()
        self.assertTrue(any('You shot down the mechanical duck in' in x
                            and 'offered by bob' in x for x in sent), sent)
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['xp'], 0)

    def testGoldenDuckIsOnlyRevealedByTheFirstHurtingShot(self):
        cb = self._putDuck(is_golden=True, hp_total=3)
        first = self._shot()
        self.assertTrue(any('GOLDEN DUCK DETECTED' in x and '[life -1]' in x
                            and 'The duck survived' in x for x in first), first)
        second = self._shot()
        self.assertTrue(any('The golden duck survived' in x for x in second), second)
        self.assertFalse(any('DETECTED' in x for x in second), second)

    def testGoldenDuckRevealIsPublicInNoticeMode(self):
        self._putDuck(is_golden=True, hp_total=3)
        conf.supybot.plugins.DuckHuntPro.preferredDisplayMode.setValue(2)
        self._cb()._rng = ScriptedRNG([100, 0])
        sent = self._bangSent()
        self.assertEqual([x for c, _, x in sent if c == 'PRIVMSG' and 'DETECTED' in x
                          and 'survived' not in x].__len__(), 1, sent)
        self.assertTrue(any(c == 'NOTICE' and 'The golden duck survived' in x
                            for c, _, x in sent), sent)
        self._cb()._rng = ScriptedRNG([100, 0])
        again = self._bangSent()
        self.assertFalse(any('DETECTED' in x for _, _, x in again), again)   # only once

    def testGoldenKillAnnouncementCountsGoldenDucks(self):
        cb = self._putDuck(is_golden=True, hp_total=1)
        sent = self._shot()
        self.assertTrue(any('You shot down the golden duck in' in x
                            and 'a total of 1 duck (including 1 golden duck)' in x
                            and '[12 xp]' in x for x in sent), sent)

    def testAmmoTypeSetsTheFireSoundAndGoldenTag(self):
        for key, sound, tag in (('ap_ammo', '*BANG*', '[AP ammo]'),
                                ('explosive_ammo', '*BOOM*', '[expl. ammo]')):
            cb = self._cb()
            player = cb.db.player(self.irc.network, self.channel, self.nick)
            player['items'].clear()
            player['clip_ammo'], player['clips_left'] = None, None
            db.giveItem(player, key, time.time(), duration=86400)
            cb.db._data = cb.db._data if hasattr(cb.db, '_data') else None
            cb._activeDuck.pop(self._key(), None)
            self._putDuck(is_golden=True, hp_total=1)
            sent = self._shot()
            kill = [x for x in sent if 'golden duck in' in x]
            self.assertTrue(kill and sound in kill[0] and tag in kill[0], (key, sent))

    def testCloverTagAndBonusOnKills(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        db.giveItem(player, 'four_leaf_clover', time.time(), duration=86400, value=4)
        self._putDuck()
        sent = self._shot()
        self.assertTrue(any('[four-leaf clover]' in x and '[14 xp]' in x for x in sent), sent)

    def _escape(self, **duck):
        cb = self._cb()
        self._putDuck(**duck)
        spawned = cb._activeDuck[self._key()][-1]['spawned_at']
        cb._duckEscapes(self.irc.network, self.channel, spawned)
        return ' '.join(self._texts(self._sent()))

    def testEscapeWordingFollowsTheKindOfDuckAndWhetherOthersFly(self):
        self.assertIn('The duck escapes', self._escape())
        self.assertIn('The golden duck escapes', self._escape(is_golden=True))
        self.assertIn('The mechanical duck escapes', self._escape(is_fake=True))
        self._putDuck()        # another duck is still flying
        self.assertIn('A duck escapes', self._escape())
        self.assertIn('A golden duck escapes', self._escape(is_golden=True))
        self.assertIn('A mechanical duck escapes', self._escape(is_fake=True))

    def testFlightAnnouncementDoesNotGiveAwayGoldenOrMechanicalDucks(self):
        cb = self._cb()
        plain = messages.tcl('en', 'm135')
        for kwargs in ({'forceGolden': True}, {'isFake': True}, {}):
            cb._spawnDuck(self.irc, self.channel, **kwargs)
            self.assertEqual(self._texts(self._sent()), [plain], kwargs)
            cb._activeDuck.pop(self._key(), None)

    def testDuckDetectorNoticeUsesTheOriginalText(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        db.giveItem(player, 'duck_detector', time.time(), uses=1)
        cb._spawnDuck(self.irc, self.channel)
        sent = self._sent()
        self.assertTrue(any(c == 'NOTICE' and x == '%s > DUCK on %s' % (self.nick, self.channel)
                            for c, _, x in sent), sent)

    def _drop(self, key, rolls=(), setup=None):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        player['items'].clear()
        player['clip_ammo'], player['clips_left'] = None, None
        if setup:
            setup(player)
        cb._rng = ScriptedRNG(self._scriptedRollFor(key) + list(rolls))
        msg = cb._rollAndApplyDrop(self.channel, player, self.nick, time.time())
        return player, msg

    def testDropsGiveTheOriginalItemsAndMessages(self):
        now = time.time()
        for key, mkey, uses in (
                ('sight', 'm400', 1), ('infrared_detector', 'm401', 6),
                ('silencer', 'm402', None), ('sunglasses', 'm403', None),
                ('duck_detector', 'm404', 1), ('grease', 'm399', None)):
            player, msg = self._drop(key)
            held = db.itemActive(player, key, now)
            self.assertTrue(held is not None, key)
            self.assertEqual(held['uses_left'], uses, key)
            self.assertEqual(msg, messages.tcl('en', mkey, self.nick), key)

    def testApAndExplosiveDropsReplaceEachOther(self):
        now = time.time()
        player, msg = self._drop('ap_ammo', setup=lambda p: db.giveItem(
            p, 'explosive_ammo', now, duration=86400))
        self.assertTrue(db.itemActive(player, 'ap_ammo', now))
        self.assertTrue(db.itemActive(player, 'explosive_ammo', now) is None)
        player, msg = self._drop('explosive_ammo', setup=lambda p: db.giveItem(
            p, 'ap_ammo', now, duration=86400))
        self.assertTrue(db.itemActive(player, 'explosive_ammo', now))
        self.assertTrue(db.itemActive(player, 'ap_ammo', now) is None)

    def testAmmoAndClipDropsStopAtTheLevelCaps(self):
        lvl = data.LEVELS[1]
        player, _ = self._drop('ammo', setup=lambda p: p.update(
            clip_ammo=2, clips_left=lvl.clip_count, xp=0))
        self.assertEqual(player['clip_ammo'], 3)
        player, _ = self._drop('ammo', setup=lambda p: p.update(
            clip_ammo=lvl.clip_size, clips_left=lvl.clip_count, xp=0))
        self.assertEqual(player['clip_ammo'], lvl.clip_size)
        player, _ = self._drop('clip', setup=lambda p: p.update(
            clip_ammo=lvl.clip_size, clips_left=0, xp=0))
        self.assertEqual(player['clips_left'], 1)
        player, _ = self._drop('clip', setup=lambda p: p.update(
            clip_ammo=lvl.clip_size, clips_left=lvl.clip_count, xp=0))
        self.assertEqual(player['clips_left'], lvl.clip_count)

    def testCloverDropRollsItsBonusAndPluralises(self):
        player, msg = self._drop('four_leaf_clover', rolls=[1])
        self.assertTrue(db.itemActive(player, 'four_leaf_clover', time.time())['value'] == 1)
        self.assertIn('a +1 four-leaf clover', msg)
        self.assertIn('extra 1 xp point ', msg)
        player, msg = self._drop('four_leaf_clover', rolls=[7])
        self.assertIn('extra 7 xp points ', msg)

    def testWaterBucketBlocksShootingEntirely(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        db.giveItem(player, 'water_bucket', time.time(), duration=3600, value='bob')
        cb.db.save()
        self._putDuck()
        self.assertRegexp('bang', 'soggy')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        # the bucket stops the shot before any jam roll or ammo use
        self.assertEqual(player['clip_ammo'], data.LEVELS[1].clip_size)
        self.assertFalse(player['jammed'])

    def testApAmmoDoublesDamageAgainstGoldenDuck(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        db.giveItem(player, 'ap_ammo', time.time(), duration=86400)
        cb.db.save()
        self._putDuck(is_golden=True, hp_total=2)
        cb._rng = ScriptedRNG([100, 0])  # no jam, hit
        self.assertNotError('bang')
        # 2 damage vs 2 hp -- dead in one hit instead of two.
        self.assertTrue(self._key() not in cb._activeDuck)

    def testCloverBonusAppliesEvenToFakeDuckKill(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        db.giveItem(player, 'four_leaf_clover', time.time(), duration=86400, value=5)
        cb.db.save()
        self._putDuck(is_fake=True)
        cb._rng = ScriptedRNG([100, 0])  # no jam, hit
        self.assertNotError('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        # Fake ducks are worth 0 xp on their own; the clover bonus (5) still
        # applies on top -- a deliberate parity quirk from Duck_Hunt.tcl.
        self.assertEqual(player['xp'], 5)

    # -----------------------------------------------------------------
    # Phase 2: drop table
    # -----------------------------------------------------------------

    def testDropTableKeepsTheOriginalRollOrder(self):
        self.assertEqual(list(data.DROP_TABLE), [
            'junk', 'ammo', 'clip', 'ap_ammo', 'explosive_ammo', 'grease', 'sight',
            'infrared_detector', 'silencer', 'sunglasses', 'duck_detector',
            'four_leaf_clover', 'xp_book_10', 'xp_book_20', 'xp_book_30',
            'xp_book_40', 'xp_book_50', 'xp_book_100'])

    def testRollDropSequentialBernoulli(self):
        keys = list(data.DROP_TABLE.items())
        values = [chance + 1 for _, chance in keys[:2]] + [keys[2][1]]
        rng = ScriptedRNG(values)
        self.assertEqual(data.rollDrop(rng), keys[2][0])

    def testRollDropReturnsNoneWhenEveryRollFails(self):
        values = [chance + 1 for _, chance in data.DROP_TABLE.items()]
        rng = ScriptedRNG(values)
        self.assertTrue(data.rollDrop(rng) is None)

    def _scriptedRollFor(self, targetKey):
        values = []
        for key, chance in data.DROP_TABLE.items():
            if key == targetKey:
                values.append(chance)
                break
            values.append(chance + 1)
        return values

    def testRollAndApplyDropGrantsXpBook(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        cb._rng = ScriptedRNG(self._scriptedRollFor('xp_book_10'))
        msg = cb._rollAndApplyDrop(self.channel, player, self.nick, time.time())
        self.assertIn('hunting magazine', msg)
        self.assertIn('[10 xp]', msg)
        self.assertEqual(player['xp'], 10)

    def testRollAndApplyDropGrantsItem(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        cb._rng = ScriptedRNG(self._scriptedRollFor('grease'))
        now = time.time()
        msg = cb._rollAndApplyDrop(self.channel, player, self.nick, now)
        self.assertTrue('you find some gun grease' in msg.lower() or 'grease' in msg.lower(), msg)
        self.assertTrue(db.itemActive(player, 'grease', now) is not None)

    def testRollAndApplyDropJunkIsFlavorOnly(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        junk = messages.tclList('en', 'm394')
        cb._rng = ScriptedRNG(self._scriptedRollFor('junk') + [1])   # second junk entry
        msg = cb._rollAndApplyDrop(self.channel, player, self.nick, time.time())
        self.assertTrue(msg.endswith(junk[1]), msg)
        self.assertTrue(msg.startswith(messages.tcl('en', 'm393', self.nick)), msg)
        self.assertEqual(player['xp'], 0)

    def testDropsDisabledSkipsRoll(self):
        cb = self._cb()
        player = self._richPlayer()
        conf.supybot.plugins.DuckHuntPro.dropsEnabled.setValue(False)
        self._putDuck()
        cb._rng = ScriptedRNG([100, 0])  # no jam, hit -- would drop if rolled
        self.assertNotError('bang')
        # No crash, no drop message queued (only kill message, if any).
        self._drain()

    # -----------------------------------------------------------------
    # Phase 3: friendly-fire / ricochet accidents
    # -----------------------------------------------------------------

    def testAccidentHitsBystanderAndConfiscatesGun(self):
        cb = self._cb()
        self._addHunter('bob')
        self._putDuck()
        # jam(no), accuracy(miss), accident-chance(hit), victim-pick(bob),
        # deflect(fail), defense(fail) -> victim hit/kicked
        cb._rng = ScriptedRNG([100, 100, 0, 0, 100, 100])
        self.assertNotError('bang')
        shooter = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(shooter['gun_state'], 'confiscated')
        self.assertEqual(shooter['stats']['humans_shot'], 1)
        bobP = cb.db.getPlayer(self.irc.network, self.channel, 'bob')
        self.assertEqual(bobP['stats']['bullets_received'], 1)
        self.assertEqual(bobP['stats']['deaths'], 1)

    def testAccidentVictimDefenseAbsorbsNoHarm(self):
        cb = self._cb()
        self._addHunter('bob', xp=200)
        self._putDuck()
        cb._rng = ScriptedRNG([100, 100, 0, 0, 100, 0])  # deflect fails, defense succeeds
        self.assertNotError('bang')
        bobP = cb.db.getPlayer(self.irc.network, self.channel, 'bob')
        self.assertEqual(bobP['stats']['absorbed'], 1)
        self.assertEqual(bobP['stats']['deaths'], 0)

    def testAccidentRicochetIntoDuckKillsItWithLuckyBonus(self):
        cb = self._cb()
        self._addHunter('bob', xp=1000)   # a level with deflection > 0
        self._putDuck()
        # jam(no), accuracy(miss), accident-chance(hit), victim-pick(bob),
        # deflect(succeed), ricochet-towards-duck(succeed)
        cb._rng = ScriptedRNG([100, 100, 0, 0, 0, 0])
        self.assertNotError('bang')
        shooter = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        lvl = data.LEVELS[data.levelForXp(0)]
        # the miss and the accident both cost xp (no floor at 0) before the
        # lucky kill pays out
        self.assertEqual(shooter['xp'], lvl.xp_missed_shot + lvl.xp_accident
                         + data.XP_PER_DUCK + data.XP_LUCKY_SHOT)
        self.assertTrue(self._key() not in cb._activeDuck)

    def testAccidentLifeInsurancePaysOutRegardlessOfOutcome(self):
        cb = self._cb()
        bob = self._addHunter('bob', xp=100)
        db.giveItem(bob, 'life_insurance', time.time(), duration=604800, uses=1)
        cb.db.save()
        self._putDuck()
        cb._rng = ScriptedRNG([100, 100, 0, 0, 100, 100])
        self.assertNotError('bang')
        bobP = cb.db.getPlayer(self.irc.network, self.channel, 'bob')
        self.assertTrue(bobP['xp'] > 100)
        self.assertTrue(db.itemActive(bobP, 'life_insurance', time.time()) is None)

    def testAccidentLiabilityInsuranceReducesShooterPenalty(self):
        cb = self._cb()
        self._addHunter('bob')
        shooter = cb.db.player(self.irc.network, self.channel, self.nick)
        shooter['xp'] = 500
        lvl = data.LEVELS[data.levelForXp(500)]
        db.giveItem(shooter, 'liability_insurance', time.time(), duration=172800)
        cb.db.save()
        self._putDuck()
        cb._rng = ScriptedRNG([100, 100, 0, 0, 100, 100])
        self.assertNotError('bang')
        shooter = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        # Tcl's int(x / 3) floors a negative: -6 becomes -2, -10 becomes -4.
        expected = 500 + lvl.xp_missed_shot + lvl.xp_accident // 3
        self.assertEqual(shooter['xp'], expected)

    def testOnlyHuntersCanBeShotExcludesNonPlayers(self):
        cb = self._cb()
        self._addOnlineNick('bystander')
        self._putDuck()
        cb._rng = ScriptedRNG([100, 100, 0])  # miss, accident-chance succeeds, no valid victim
        self.assertNotError('bang')
        bystander = cb.db.getPlayer(self.irc.network, self.channel, 'bystander')
        self.assertTrue(bystander is None)

    def testGunConfiscationOnWildFire(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.gunConfiscationOnWildFire.setValue(True)
        cb._rng = ScriptedRNG([100])  # no jam, no duck present -> wild shot
        self.assertNotError('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['gun_state'], 'confiscated')

    # -----------------------------------------------------------------
    # Phase 3: weapon confiscation + auto-return
    # -----------------------------------------------------------------

    def testGunHandBackMode2AppliesAfterKillToOtherConfiscatedPlayers(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.gunHandBackMode.setValue(2)
        other = cb.db.player(self.irc.network, self.channel, 'someoneElse')
        other['gun_state'] = 'confiscated'
        cb.db.save()
        self._putDuck()
        cb._rng = ScriptedRNG([100, 0])  # no jam, hit -> kill
        self.assertNotError('bang')
        other = cb.db.getPlayer(self.irc.network, self.channel, 'someoneElse')
        self.assertEqual(other['gun_state'], 'armed')

    def testGunHandBackMode3NeverAutoReturns(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.gunHandBackMode.setValue(3)
        other = cb.db.player(self.irc.network, self.channel, 'someoneElse')
        other['gun_state'] = 'confiscated'
        cb.db.save()
        self._putDuck()
        cb._rng = ScriptedRNG([100, 0])
        self.assertNotError('bang')
        other = cb.db.getPlayer(self.irc.network, self.channel, 'someoneElse')
        self.assertEqual(other['gun_state'], 'confiscated')

    def testNextHandBackTimeCalculation(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.autoGunHandBackTime.setValue('03:30')
        noon = datetime(2026, 1, 1, 12, 0, 0).timestamp()
        expected = datetime(2026, 1, 2, 3, 30, 0).timestamp()
        self.assertEqual(cb._nextHandBackTime(self.channel, noon), expected)
        earlyMorning = datetime(2026, 1, 1, 1, 0, 0).timestamp()
        expected2 = datetime(2026, 1, 1, 3, 30, 0).timestamp()
        self.assertEqual(cb._nextHandBackTime(self.channel, earlyMorning), expected2)

    def testUnarmAndRearmCommands(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, 'bob')
        sent = self._cmd('unarm bob')
        self.assertEqual(self._texts(sent), [messages.tcl('en', 'm129', self.nick, 'bob')])
        self.assertEqual(self._bob()['gun_state'], 'confiscated')
        sent = self._cmd('rearm bob')
        self.assertEqual(self._texts(sent), [messages.tcl('en', 'm73', self.nick, 'bob')])
        self.assertEqual(self._bob()['gun_state'], 'armed')

    def testUnarmStaticSurvivesModeBasedHandBack(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, 'bob')
        conf.supybot.plugins.DuckHuntPro.gunHandBackMode.setValue(2)
        self.assertEqual(self._texts(self._cmd('unarm -static bob')),
                         [messages.tcl('en', 'm69', self.nick, 'bob')])
        self.assertEqual(self._bob()['gun_state'], 'confiscated_permanent')
        cb._maybeHandBackOnDuckGone(self.irc.network, self.channel)
        self.assertEqual(self._bob()['gun_state'], 'confiscated_permanent')

    def testShopIgnoresAPermanentlyConfiscatedGun(self):
        cb = self._cb()
        player = self._richPlayer()
        player['gun_state'] = 'confiscated_permanent'
        cb.db.save()
        # Tcl closes the shop to a permanently confiscated gun, silently.
        self.assertEqual(self._cmd('shop 5'), [])
        self.assertEqual(self._player()['gun_state'], 'confiscated_permanent')

    # -----------------------------------------------------------------
    # Phase 3: anti-highlight duck art
    # -----------------------------------------------------------------

    def testAntiHighlightAnnouncementVariesAndUsesTheOriginalGlyphs(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.antiHighlight.setValue(True)
        cb._rng = random.Random(42)
        glyphs = messages.tclList('en', 'm137')
        cries = messages.tclList('en', 'm138')
        trail = messages.tcl('en', 'm136')
        arts = {cb._duckAnnouncement(self.channel) for _ in range(30)}
        self.assertTrue(len(arts) > 5)
        for art in arts:
            self.assertTrue(any('\x02%s\x02' % g in art for g in glyphs), art)
            self.assertTrue(any(art.endswith('\x0314%s\x0f' % c) for c in cries), art)
            shown = art.split('\x0f')[0][len('\x0314'):]
            self.assertEqual(len(shown), len(trail) - 4)   # four trail chars removed

    def testPlainAnnouncementIsTheOriginalOne(self):
        self.assertEqual(self._cb()._duckAnnouncement(self.channel), messages.tcl('en', 'm135'))

    def testSpawnDuckUsesAntiHighlightArtWhenEnabled(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.antiHighlight.setValue(True)
        cb._spawnDuck(self.irc, self.channel)
        m = self.irc.takeMsg()
        self.assertTrue(m is not None)
        self.assertNotEqual(m.args[1], messages.get('en', 'duck_flies'))
        cb._removeDuck(self.irc.network, self.channel)

    # -----------------------------------------------------------------
    # Phase 3: nick-change stat fusion
    # -----------------------------------------------------------------

    def testDoNickRecordsPendingTransfer(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, self.nick)
        self._addOnlineNick('newnick')
        msg = ircmsgs.nick('newnick', prefix=self.prefix)
        cb.doNick(self.irc, msg)
        pending = cb.db.popPendingTransfer(self.irc.network, self.channel, 'newnick')
        self.assertTrue(pending is not None)
        self.assertEqual(pending['old_nick'], self.nick)

    def testCheckPendingRenameMergesStats(self):
        cb = self._cb()
        old = cb.db.player(self.irc.network, self.channel, self.nick)
        old['xp'] = 250
        old['stats']['killed'] = 3
        cb.db.save()
        cb.db.recordPendingTransfer(self.irc.network, self.channel, self.nick, 'newnick')
        cb._checkPendingRename(self.irc, self.channel, 'newnick')
        newP = cb.db.getPlayer(self.irc.network, self.channel, 'newnick')
        self.assertEqual(newP['xp'], 250)
        self.assertEqual(newP['stats']['killed'], 3)
        self.assertTrue(cb.db.getPlayer(self.irc.network, self.channel, self.nick) is None)

    def testDoPartDiscardsPendingTransfer(self):
        cb = self._cb()
        cb.db.recordPendingTransfer(self.irc.network, self.channel, 'old', 'new')
        msg = ircmsgs.part(self.channel, prefix='new!x@y')
        cb.doPart(self.irc, msg)
        self.assertTrue(cb.db.popPendingTransfer(self.irc.network, self.channel, 'new') is None)

    def testConfiscationEnforcementDiscardsDisarmedOldStats(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.confiscationEnforcementOnFusion.setValue(True)
        old = cb.db.player(self.irc.network, self.channel, 'oldnick')
        old['xp'] = 300
        old['gun_state'] = 'armed'
        newP = cb.db.player(self.irc.network, self.channel, 'newnick')
        newP['gun_state'] = 'confiscated'
        cb.db.save()
        cb.db.recordPendingTransfer(self.irc.network, self.channel, 'oldnick', 'newnick')
        cb._checkPendingRename(self.irc, self.channel, 'newnick')
        newP = cb.db.getPlayer(self.irc.network, self.channel, 'newnick')
        self.assertEqual(newP['xp'], 0)
        self.assertTrue(cb.db.getPlayer(self.irc.network, self.channel, 'oldnick') is None)

    # ---- parity with Duck_Hunt.tcl's nick tracking and merge_stats --------

    def _profile(self, nick, **fields):
        cb = self._cb()
        p = cb.db.player(self.irc.network, self.channel, nick)
        stats = fields.pop('stats', {})
        p.update(fields)
        p['stats'].update(stats)
        cb.db.save()
        return p

    def _pending(self, nick):
        return self._cb().db.getPendingTransfer(self.irc.network, self.channel, nick)

    def _renamed(self, old, new):
        self._addOnlineNick(new)
        self._cb()._trackNickChange(self.irc, self.channel, old, new)

    def testMergeRecomputesAmmoFromWhatBothSidesSpent(self):
        cb = self._cb()
        self._profile('old', xp=30, clip_ammo=4, clips_left=1)
        self._profile('new', xp=25, clip_ammo=6, clips_left=2)
        cb.db.mergeStats(self.irc.network, self.channel, 'new', 'old')
        merged = cb.db.getPlayer(self.irc.network, self.channel, 'new')
        # full = (6*2+6)*2 = 36; used = 36 - 6 - 4 - 12 - 6 = 8; level 3: 6 per clip, 2 clips
        self.assertEqual((merged['xp'], merged['clip_ammo'], merged['clips_left']), (55, 4, 1))
        self.assertTrue(cb.db.getPlayer(self.irc.network, self.channel, 'old') is None)

    def testMergeNeverLeavesNegativeClips(self):
        cb = self._cb()
        self._profile('old', xp=0, clip_ammo=0, clips_left=0)
        self._profile('new', xp=0, clip_ammo=0, clips_left=0)
        cb.db.mergeStats(self.irc.network, self.channel, 'new', 'old')
        merged = cb.db.getPlayer(self.irc.network, self.channel, 'new')
        self.assertEqual((merged['clip_ammo'], merged['clips_left']), (0, 0))

    def testMergeCombinesTheRest(self):
        cb = self._cb()
        now = time.time()
        old = self._profile('old', xp=10, gun_state='confiscated', jammed=True,
                            last_activity=500, stats={'killed': 2, 'best_time_ms': 3000,
                                                      'reflex_ms': 400})
        db.giveItem(old, 'grease', now, duration=86400)
        db.giveItem(old, 'silencer', now, duration=100)
        new = self._profile('new', xp=5, gun_state='armed', jammed=False, last_activity=900,
                            stats={'killed': 3, 'best_time_ms': 2000, 'reflex_ms': 100})
        db.giveItem(new, 'silencer', now, duration=5000)
        cb.db.mergeStats(self.irc.network, self.channel, 'new', 'old')
        m = cb.db.getPlayer(self.irc.network, self.channel, 'new')
        self.assertEqual((m['gun_state'], m['jammed'], m['last_activity']), ('confiscated', True, 900))
        self.assertEqual((m['stats']['killed'], m['stats']['best_time_ms'], m['stats']['reflex_ms']),
                         (5, 2000, 500))
        self.assertTrue(db.itemActive(m, 'grease', now))
        self.assertAlmostEqual(m['items']['silencer']['expires_at'], now + 5000, delta=2)

    def testMergeKeepsTheOnlyBestTimeThereIs(self):
        cb = self._cb()
        self._profile('old', stats={'best_time_ms': None})
        self._profile('new', stats={'best_time_ms': 1500})
        cb.db.mergeStats(self.irc.network, self.channel, 'new', 'old')
        self.assertEqual(cb.db.getPlayer(self.irc.network, self.channel, 'new')['stats']['best_time_ms'], 1500)

    def testNickChangeToANickWithStatsIsPendingNotMerged(self):
        self._profile('old', xp=40)
        self._profile('new', xp=10)
        self._renamed('old', 'new')
        self.assertEqual(self._pending('new')['old_nick'], 'old')
        self.assertTrue(self._cb().db.getPlayer(self.irc.network, self.channel, 'old'))   # untouched

    def testNickChangeFromAProfileToAFreshNickIsPending(self):
        self._profile('old', xp=40)
        self._renamed('old', 'fresh')
        self.assertEqual(self._pending('fresh')['old_nick'], 'old')

    def testNickChangeWithNoStatsAnywhereIsIgnored(self):
        self._profile('someone')
        self._renamed('ghost', 'phantom')
        self.assertTrue(self._pending('phantom') is None)

    def testRenamingBackCancelsThePendingTransfer(self):
        self._profile('a', xp=40)
        self._profile('b', xp=10)
        self._renamed('a', 'b')
        self.assertTrue(self._pending('b'))
        self._renamed('b', 'a')
        self.assertTrue(self._pending('b') is None)
        self.assertTrue(self._pending('a') is None)

    def testChainedRenamesAreFactoredIntoOneTransfer(self):
        self._profile('a', xp=40)
        self._profile('c', xp=10)
        self._renamed('a', 'b')            # b has no stats: pending b <- a
        self.assertEqual(self._pending('b')['old_nick'], 'a')
        self._renamed('b', 'c')            # c has stats: pending c <- a, b's entry is gone
        self.assertEqual(self._pending('c')['old_nick'], 'a')
        self.assertTrue(self._pending('b') is None)

    def testAnonymousPrefixNicksNeverReceiveStats(self):
        conf.supybot.plugins.DuckHuntPro.anonymPrefix.setValue('Guest')
        self._profile('old', xp=40)
        self._renamed('old', 'Guest12345')
        self.assertTrue(self._pending('Guest12345') is None)
        self._renamed('Guest12345', 'old2')            # leaving the anonymous nick is fine
        self._profile('Guest99999', xp=1)
        self._renamed('Guest99999', 'Guest11111')       # anonymous -> anonymous too
        self.assertTrue(self._pending('Guest11111'))

    def testStalePendingTransfersAreForgotten(self):
        cb = self._cb()
        self._profile('old', xp=40)
        self._renamed('old', 'fresh')
        self.assertFalse(cb.db.dropStalePendingTransfers(3600))
        cb.db.data['pending_transfers_at'] = time.time() - 7200
        self.assertTrue(cb.db.dropStalePendingTransfers(3600))
        self.assertTrue(self._pending('fresh') is None)

    def testBothDisarmedKeepsOnlyTheRicherProfile(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.confiscationEnforcementOnFusion.setValue(True)
        self._profile('old', xp=300, gun_state='confiscated')
        self._profile('new', xp=20, gun_state='confiscated')
        cb.db.recordPendingTransfer(self.irc.network, self.channel, 'old', 'new')
        cb._checkPendingRename(self.irc, self.channel, 'new')
        survivor = cb.db.getPlayer(self.irc.network, self.channel, 'new')
        self.assertEqual((survivor['xp'], survivor['display_nick']), (300, 'new'))
        self.assertTrue(cb.db.getPlayer(self.irc.network, self.channel, 'old') is None)

    def testBothDisarmedNewProfileWinsWhenItHasAtLeastTheXp(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.confiscationEnforcementOnFusion.setValue(True)
        self._profile('old', xp=20, gun_state='confiscated_permanent')
        self._profile('new', xp=20, gun_state='confiscated')
        cb.db.recordPendingTransfer(self.irc.network, self.channel, 'old', 'new')
        cb._checkPendingRename(self.irc, self.channel, 'new')
        self.assertEqual(cb.db.getPlayer(self.irc.network, self.channel, 'new')['gun_state'], 'confiscated')
        self.assertTrue(cb.db.getPlayer(self.irc.network, self.channel, 'old') is None)

    def testPendingRenameLogsTheTakeoverLine(self):
        cb = self._cb()
        lines = []
        cb._logLine = lambda channel, key, *args: lines.append((key, args))
        self._profile('old', xp=20)
        self._profile('new', xp=10)
        cb.db.recordPendingTransfer(self.irc.network, self.channel, 'old', 'new')
        cb._checkPendingRename(self.irc, self.channel, 'new')
        self.assertEqual([k for k, _ in lines], ['m102'])
        # fresh nick, but the new nick already has stats (re-assignment): m127
        lines.clear()
        self._profile('x', xp=5)
        cb.db.recordPendingTransfer(self.irc.network, self.channel, 'gone', 'x')
        cb._checkPendingRename(self.irc, self.channel, 'x')
        self.assertEqual([k for k, _ in lines], ['m127'])
        conf.supybot.plugins.DuckHuntPro.warnOnTakeover.setValue(False)
        lines.clear()
        self._profile('y', xp=5)
        cb.db.recordPendingTransfer(self.irc.network, self.channel, 'gone', 'y')
        cb._checkPendingRename(self.irc, self.channel, 'y')
        self.assertEqual(lines, [])

    # -----------------------------------------------------------------
    # Phase 3: admin toolbox
    # -----------------------------------------------------------------

    def _notices(self, command, **kw):
        return self._texts(self._cmd(command, **kw), 'NOTICE')

    def _players(self, **xp):
        cb = self._cb()
        for nick, value in xp.items():
            cb.db.player(self.irc.network, self.channel, nick)['xp'] = value
        cb.db.save()

    def testDucklistListsSortedNicksAndSearches(self):
        self._players(zed=1, alice=2, Bob=3)
        self.assertEqual(self._notices('ducklist ' + self.channel),
                         [messages.tcl('en', 'm125', 3, 'alice bob zed')])
        self.assertEqual(self._notices('ducklist %s LI' % self.channel),
                         [messages.tcl('en', 'm124', 'alice')])
        self.assertEqual(self._notices('ducklist %s nope' % self.channel),
                         [messages.tcl('en', 'm126', 'nope')])

    def testDucklistErrors(self):
        self.assertEqual(self._notices('ducklist ' + self.channel),
                         [messages.tcl('en', 'm123', self.channel)])
        self.assertEqual(self._notices('ducklist #nowhere'),
                         [messages.tcl('en', 'm75', '#nowhere')])
        self.assertEqual(self._notices('ducklist'), [messages.tcl('en', 'm122', 'ducklist')])

    def testDuckfusionMergesSeveralSources(self):
        cb = self._cb()
        self._players(alice=50, bob=30, carol=5)
        self.assertEqual(self._notices('duckfusion %s bob alice carol' % self.channel),
                         [messages.tcl('en', 'm78', 'bob', 'alice', 'bob', self.channel),
                          messages.tcl('en', 'm78', 'bob', 'carol', 'bob', self.channel)])
        self.assertEqual(cb.db.getPlayer(self.irc.network, self.channel, 'bob')['xp'], 85)
        for gone in ('alice', 'carol'):
            self.assertTrue(cb.db.getPlayer(self.irc.network, self.channel, gone) is None)

    def testDuckfusionReportsUnknownProfilesAndKeepsGoing(self):
        cb = self._cb()
        self._players(alice=50, bob=30)
        self.assertEqual(self._notices('duckfusion %s bob ghost alice' % self.channel),
                         [messages.tcl('en', 'm77', 'ghost', self.channel),
                          messages.tcl('en', 'm78', 'bob', 'alice', 'bob', self.channel)])
        self.assertEqual(self._notices('duckfusion %s ghost alice' % self.channel),
                         [messages.tcl('en', 'm77', 'ghost', self.channel)])
        self.assertEqual(self._notices('duckfusion %s bob' % self.channel),
                         [messages.tcl('en', 'm74', 'duckfusion')])

    def testDuckfusionIntoItselfChangesNothing(self):
        cb = self._cb()
        self._players(bob=30)
        self._cmd('duckfusion %s bob BOB' % self.channel)
        self.assertEqual(cb.db.getPlayer(self.irc.network, self.channel, 'bob')['xp'], 30)

    def testDuckfusionClampsAmmoToTheMergedLevel(self):
        cb = self._cb()
        self._players(alice=0, bob=0)
        for nick in ('alice', 'bob'):
            p = cb.db.getPlayer(self.irc.network, self.channel, nick)
            p['clip_ammo'], p['clips_left'] = 6, 2
        self._cmd('duckfusion %s bob alice' % self.channel)
        bob = cb.db.getPlayer(self.irc.network, self.channel, 'bob')
        lvl = data.LEVELS[data.levelForXp(bob['xp'])]
        self.assertTrue(bob['clip_ammo'] <= lvl.clip_size and bob['clips_left'] <= lvl.clip_count)

    def testDuckrename(self):
        cb = self._cb()
        self._players(alice=50, bob=30)
        self.assertEqual(self._notices('duckrename %s alice bob' % self.channel),
                         [messages.tcl('en', 'm132', 'bob', self.channel, 'duckfusion')])
        self.assertEqual(self._notices('duckrename %s ghost x' % self.channel),
                         [messages.tcl('en', 'm77', 'ghost', self.channel)])
        self.assertEqual(self._notices('duckrename %s alice Alicia' % self.channel),
                         [messages.tcl('en', 'm133', 'alice', 'Alicia', self.channel)])
        moved = cb.db.getPlayer(self.irc.network, self.channel, 'alicia')
        self.assertEqual((moved['xp'], moved['display_nick']), (50, 'Alicia'))
        self.assertTrue(cb.db.getPlayer(self.irc.network, self.channel, 'alice') is None)
        self.assertEqual(self._notices('duckrename %s a' % self.channel),
                         [messages.tcl('en', 'm131', 'duckrename')])

    def testDuckdelete(self):
        cb = self._cb()
        self._players(alice=50)
        self.assertEqual(self._notices('duckdelete %s alice' % self.channel),
                         [messages.tcl('en', 'm143', 'alice', self.channel)])
        self.assertTrue(cb.db.getPlayer(self.irc.network, self.channel, 'alice') is None)
        self.assertEqual(self._notices('duckdelete %s alice' % self.channel),
                         [messages.tcl('en', 'm142', 'alice', self.channel)])
        self.assertEqual(self._notices('duckdelete %s' % self.channel),
                         [messages.tcl('en', 'm141', 'duckdelete')])

    def testFusionAndRenameNeedTheGameEnabledButDeleteAndListDoNot(self):
        self._players(alice=50, bob=1)
        conf.supybot.plugins.DuckHuntPro.enabled.setValue(False)
        m76 = [messages.tcl('en', 'm76', 'DuckHuntPro', self.channel)]
        self.assertEqual(self._notices('duckfusion %s bob alice' % self.channel), m76)
        self.assertEqual(self._notices('duckrename %s alice x' % self.channel), m76)
        self.assertEqual(self._notices('ducklist ' + self.channel),
                         [messages.tcl('en', 'm125', 2, 'alice bob')])
        self.assertEqual(self._notices('duckdelete %s bob' % self.channel),
                         [messages.tcl('en', 'm143', 'bob', self.channel)])

    def testStaffCommandsNeedChannelOpHalfopOrAdmin(self):
        cb = self._cb()
        self._players(alice=50)
        caps = []
        real = ircdb.checkCapability
        try:
            ircdb.checkCapability = lambda prefix, cap, *a, **kw: cap in caps
            for cap, allowed in ((self.channel + ',voice', False), (self.channel + ',op', True),
                                 (self.channel + ',halfop', True), ('admin', True),
                                 ('#other,op', False)):
                caps[:] = [cap]
                self.assertEqual(cb._isStaff(self.prefix, self.channel), allowed, cap)
            caps[:] = []
            for command in ('ducklist ' + self.channel, 'duckdelete %s alice' % self.channel,
                            'unarm alice', 'rearm alice', 'ducklaunch ' + self.channel,
                            'duckexport'):
                sent = self._cmd(command)
                self.assertFalse([x for c, _, x in sent if 'alice' in x or 'm143' in x], command)
            self.assertTrue(cb.db.getPlayer(self.irc.network, self.channel, 'alice'))
            self.assertFalse(self._key() in cb._activeDuck)
            caps[:] = [self.channel + ',halfop']
            self.assertEqual(self._notices('ducklist ' + self.channel),
                             [messages.tcl('en', 'm124', 'alice')])
            self.assertEqual(self._notices('duckexport'), [])      # global admin only
        finally:
            ircdb.checkCapability = real

    def testAdminPlanningShowsTimeList(self):
        cb = self._cb()
        chan = cb.db.channel(self.irc.network, self.channel)
        chan['planned_soarings'] = ['09:05', '03:14']   # out of order on purpose
        cb.db.save()
        self.assertEqual(self._texts(self._cmd('duckplanning ' + self.channel), 'NOTICE'),
                         [messages.tcl('en', 'm81', self.channel, '03:14, 09:05')])

    def testAdminPlanningEmpty(self):
        self.assertEqual(self._texts(self._cmd('duckplanning ' + self.channel), 'NOTICE'),
                         [messages.tcl('en', 'm154', self.channel)])

    def testAdminReplanningRebuildsSchedule(self):
        cb = self._cb()
        sent = self._texts(self._cmd('duckreplanning ' + self.channel), 'NOTICE')
        chan = cb.db.getChannel(self.irc.network, self.channel)
        self.assertEqual(len(chan['planned_soarings']), cb.registryValue('ducksPerDay', self.channel))
        # the reply lists the new plan, sorted
        self.assertEqual(sent, [messages.tcl(
            'en', 'm149', self.channel, ', '.join(sorted(chan['planned_soarings'])))])

    # ---- parity with Duck_Hunt.tcl's flight planning --------------------

    NOON = datetime(2026, 1, 1, 12, 0).timestamp()

    def _planTo(self, now=None, reason=None, **config):
        """Plans with the scheduler stubbed out; returns (soarings, [(name, at)])."""
        cb = self._cb()
        calls = []
        cb._scheduleEvent = lambda name, at, f, args: calls.append((name, at))
        try:
            for key, value in config.items():
                getattr(conf.supybot.plugins.DuckHuntPro, key).setValue(value)
            soarings = cb._planDay(self.irc.network, self.channel, reason, now)
        finally:
            del cb._scheduleEvent
        return soarings, calls

    def testPlanDrawsEachAllowedHourOnceBeforeReusingAny(self):
        # 24 hours, 18 ducks: no hour twice
        soarings, _ = self._planTo(self.NOON)
        hours = [s.split(':')[0] for s in soarings]
        self.assertEqual(len(soarings), 18)
        self.assertEqual(len(set(hours)), 18)

    def testPlanSkipsTheSleepingHours(self):
        soarings, _ = self._planTo(self.NOON, duckSleepHours='0 1 2 3 4 5')
        hours = sorted(int(s.split(':')[0]) for s in soarings)
        self.assertEqual(hours, list(range(6, 24)))     # 18 ducks, 18 hours: each once

    def testPlanRefillsTheHourPoolWhenItRunsOut(self):
        soarings, _ = self._planTo(self.NOON, ducksPerDay=30)
        counts = {}
        for s in soarings:
            counts[s.split(':')[0]] = counts.get(s.split(':')[0], 0) + 1
        self.assertEqual(len(soarings), 30)
        self.assertEqual(sorted(counts.values()), [1] * 18 + [2] * 6)

    def testPlanNeverPicksMidnightSharp(self):
        cb = self._cb()
        cb._rng = ScriptedRNG([0, 0])          # hour index 0 = '00', minute 0
        soarings, _ = self._planTo(self.NOON, ducksPerDay=1)
        self.assertEqual(soarings, ['00:01'])

    def testPlanRerollsATakenMinute(self):
        cb = self._cb()
        # only hour 05 is awake: hour pick, minute 10, hour pick, minute 10 (taken), minute 11
        cb._rng = ScriptedRNG([0, 10, 0, 10, 11])
        soarings, _ = self._planTo(self.NOON, ducksPerDay=2,
                                   duckSleepHours=' '.join(str(h) for h in range(24) if h != 5))
        self.assertEqual(soarings, ['05:10', '05:11'])

    def testOnlyTheTimesStillAheadAreScheduled(self):
        soarings, calls = self._planTo(self.NOON)
        ahead = [s for s in soarings if s > '12:00']
        self.assertEqual(len(calls), len(ahead))
        self.assertTrue(all(at > self.NOON for _, at in calls))
        chan = self._cb().db.getChannel(self.irc.network, self.channel)
        self.assertEqual(len(chan['planned_flights']), len(ahead))
        self.assertEqual(len(chan['planned_soarings']), 18)       # the whole plan is kept

    def testBreadReplanKeepsTheNearestUpcomingTime(self):
        cb = self._cb()
        chan = cb.db.channel(self.irc.network, self.channel)
        chan['planned_soarings'] = ['20:00', '03:00', '13:30']
        soarings, _ = self._planTo(self.NOON, reason='bread_added')
        self.assertEqual(soarings[0], '13:30')
        self.assertEqual(len(soarings), 18)

    def testBreadExpiredReplanOnlyKeepsATimeWhileBreadRemains(self):
        cb = self._cb()
        chan = cb.db.channel(self.irc.network, self.channel)
        chan['planned_soarings'] = ['13:30']
        cb._rng = ScriptedRNG([])               # all hours/minutes come out as the lowest
        soarings, _ = self._planTo(self.NOON, reason='bread_expired')
        self.assertNotEqual(soarings[0], '13:30')            # no bread left: fresh plan
        chan['planned_soarings'] = ['13:30']
        db.addBread(chan, self.NOON, data.BREAD_DURATION)
        soarings, _ = self._planTo(self.NOON, reason='bread_expired')
        self.assertEqual(soarings[0], '13:30')

    def testBreadHookReplansAndLogs(self):
        cb = self._cb()
        plans = []
        cb._planDay = lambda network, channel, reason=None, now=None: plans.append(reason) or ['07:07']
        cb._onBreadChanged(self.irc.network, self.channel, 'bread_added', 'bob')
        cb._onBreadChanged(self.irc.network, self.channel, 'bread_expired')
        self.assertEqual(plans, ['bread_added', 'bread_expired'])

    def testNoReplanOnBreadWhenMethodIsOne(self):
        cb = self._cb()
        plans = []
        cb._planDay = lambda *a, **k: plans.append(1)
        conf.supybot.plugins.DuckHuntPro.method.setValue(1)
        cb._onBreadChanged(self.irc.network, self.channel, 'bread_added', 'bob')
        self.assertEqual(plans, [])

    def testExpiredBreadIsRemovedOneByOneWithAReplanEach(self):
        cb = self._cb()
        calls = []
        cb._onBreadChanged = lambda network, channel, reason, who=None: calls.append(reason)
        chan = cb.db.channel(self.irc.network, self.channel)
        now = time.time()
        chan['bread'] = [{'expires_at': now - 5}, {'expires_at': now - 1},
                         {'expires_at': now + 600}]
        cb._expireBread()
        self.assertEqual(calls, ['bread_expired', 'bread_expired'])
        self.assertEqual(len(chan['bread']), 1)

    def testCountingBreadDoesNotRemoveExpiredPieces(self):
        chan = self._cb().db.channel(self.irc.network, self.channel)
        now = time.time()
        chan['bread'] = [{'expires_at': now - 5}, {'expires_at': now + 600}]
        self.assertEqual(db.activeBreadCount(chan, now), 1)
        self.assertEqual(len(chan['bread']), 2)

    def testMidnightReplansEnabledChannelsAndSchedulesTheNextMidnight(self):
        cb = self._cb()
        chan = cb.db.channel(self.irc.network, self.channel)
        chan['planned_soarings'] = []
        for name in [n for n in cb._scheduled if n.startswith('DuckHuntPro:midnight:')]:
            cb._unschedule(name)
        cb._midnight()
        self.assertEqual(len(chan['planned_soarings']), 18)
        names = [n for n in cb._scheduled if n.startswith('DuckHuntPro:midnight:')]
        self.assertEqual(len(names), 1)
        at = float(names[0].rsplit(':', 1)[1])
        dt = datetime.fromtimestamp(at)
        self.assertEqual((dt.hour, dt.minute, dt.second), (0, 0, 0))
        self.assertTrue(at > time.time())
        cb._unschedule(names[0])

    def testPlannedFlightIsSkippedWhenADuckJustFlew(self):
        cb = self._cb()
        chan = cb.db.channel(self.irc.network, self.channel)
        chan['last_duck_at'] = time.time()
        cb._fireSpawn(self.irc.network, self.channel)
        self.assertTrue(self._key() not in cb._activeDuck)
        chan['last_duck_at'] = time.time() - 5
        cb._fireSpawn(self.irc.network, self.channel)
        self.assertTrue(self._key() in cb._activeDuck)
        cb._removeDuck(self.irc.network, self.channel)

    def testMethodOneRollsEveryMinuteOutsideSleepHours(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.method.setValue(1)
        cb._rng = ScriptedRNG([18])                    # 18 <= 18 ducks per day: a flight
        cb._checkBushes()
        self.assertTrue(self._key() in cb._activeDuck)
        cb._removeDuck(self.irc.network, self.channel)
        chan = cb.db.channel(self.irc.network, self.channel)
        chan['last_duck_at'] = None
        cb._rng = ScriptedRNG([19])                    # just over: nothing
        cb._checkBushes()
        self.assertTrue(self._key() not in cb._activeDuck)

    def testMethodOneChanceGrowsWithBreadAndRespectsSleepHours(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.method.setValue(1)
        chan = cb.db.channel(self.irc.network, self.channel)
        db.addBread(chan, time.time(), data.BREAD_DURATION)
        cb._rng = ScriptedRNG([20])                    # 18 + 2 per piece of bread
        cb._checkBushes()
        self.assertTrue(self._key() in cb._activeDuck)
        cb._removeDuck(self.irc.network, self.channel)
        chan['last_duck_at'] = None
        conf.supybot.plugins.DuckHuntPro.duckSleepHours.setValue(
            ' '.join(str(h) for h in range(24)))        # everybody sleeps
        cb._rng = ScriptedRNG([1])
        cb._checkBushes()
        self.assertTrue(self._key() not in cb._activeDuck)

    def testMethodOnePlansNothing(self):
        conf.supybot.plugins.DuckHuntPro.method.setValue(1)
        self.assertEqual(self._cb()._planDay(self.irc.network, self.channel), [])

    def testEnablingAChannelPlansItAndDisablingCancelsTheFlights(self):
        cb = self._cb()
        value = cb.registryValue('enabled', self.channel, value=False)
        chan = cb.db.channel(self.irc.network, self.channel)
        try:
            value.setValue(False)
            self.assertEqual(chan['planned_flights'], [])
            value.setValue(True)
            self.assertEqual(len(chan['planned_soarings']), 18)
            value.setValue(False)
            self.assertEqual(chan['planned_flights'], [])
        finally:
            value.setValue(True)
            cb._cancelFlights(self.irc.network, self.channel)

    def testAdminLaunchForcesImmediateSpawn(self):
        cb = self._cb()
        sent = self._cmd('ducklaunch ' + self.channel)
        self.assertTrue(self._key() in cb._activeDuck)
        self.assertEqual([x for c, _, x in sent if c in ('PRIVMSG', 'NOTICE')],
                         [messages.tcl('en', 'm135')])        # just the flight announcement
        cb._removeDuck(self.irc.network, self.channel)

    def testAdminLaunchIsNeverGoldenUnlessAsked(self):
        cb = self._cb()
        for arg, golden in (('', False), (' 0', False), (' 1', True)):
            cb._activeDuck.pop(self._key(), None)
            cb._rng = ScriptedRNG([0, 3])     # a golden roll would succeed with 0
            self._cmd('ducklaunch ' + self.channel + arg)
            self.assertEqual(cb._activeDuck[self._key()][0]['is_golden'], golden, arg)
        cb._removeDuck(self.irc.network, self.channel)

    def testAdminCommandsRefuseADisabledChannel(self):
        conf.supybot.plugins.DuckHuntPro.enabled.setValue(False)
        self.assertEqual(self._texts(self._cmd('ducklaunch ' + self.channel), 'NOTICE'),
                         [messages.tcl('en', 'm76', 'DuckHuntPro', self.channel)])

    def testAdminLaunchAddsToExistingDucksInsteadOfBlocking(self):
        # Matches Duck_Hunt.tcl's !ducklaunch: never checks for an existing
        # duck, so launching while one's already in flight just adds a
        # second one rather than being refused.
        cb = self._cb()
        self._putDuck()
        self._cmd('ducklaunch ' + self.channel)
        self.assertEqual(len(cb._activeDuck[self._key()]), 2)

    def _export(self, arg=''):
        notices = self._notices(('duckexport ' + arg).strip())
        self.assertEqual(len(notices), 1, notices)
        path = os.path.join(str(conf.supybot.directories.data), 'DuckHuntPro', 'players_table.txt')
        self.assertEqual(notices, [messages.tcl('en', 'm262', path)])
        with open(path, encoding='utf-8') as f:
            return f.read().split('\n')

    def _exportPlayers(self):
        cb = self._cb()
        for nick, xp, killed in (('alice', 50, 3), ('Bob', 30, 12), ('carol', 400, 3)):
            p = cb.db.player(self.irc.network, self.channel, nick)
            p['xp'] = xp
            p['stats']['killed'] = killed
        cb.db.getPlayer(self.irc.network, self.channel, 'Bob')['stats']['best_time_ms'] = 2345
        cb.db.save()

    def _exportNicks(self, lines):
        start = lines.index(self.channel) + 4
        nicks = []
        for line in lines[start:]:
            if not line:
                break
            nicks.append(line.split()[0])
        return nicks

    def testExportHasTheOriginalsLayout(self):
        self._exportPlayers()
        lines = self._export()
        self.assertTrue(lines[1].startswith('|  DuckHuntPro v2.11 '))
        self.assertIn('sorted by nick', lines[1])
        self.assertEqual(lines[4], messages.tcl('en', 'm244') + ' ' + ' '.join(self._cb()._EXPORT_CRITERIA))
        header = lines[lines.index(self.channel) + 2]
        for key in range(209, 243):
            self.assertIn(messages.tcl('en', 'm%d' % key), header)
        bob = [l for l in lines if l.startswith('Bob ')][0]
        for expected in ('2.345s', '100%', '30'):
            self.assertIn(expected, bob)

    def testExportSortsByNickByDefaultAndByCriteria(self):
        self._exportPlayers()
        self.assertEqual(self._exportNicks(self._export()), ['alice', 'Bob', 'carol'])
        self.assertEqual(self._exportNicks(self._export('xp')), ['carol', 'alice', 'Bob'])
        self.assertEqual(self._exportNicks(self._export('ducks')), ['Bob', 'alice', 'carol'])
        self.assertEqual(self._exportNicks(self._export('best_time')), ['Bob', 'alice', 'carol'])
        self.assertEqual(self._exportNicks(self._export('level')), ['carol', 'alice', 'Bob'])

    def testExportRejectsABadCriterionAndExtraWords(self):
        valid = list(self._cb()._EXPORT_CRITERIA)
        valid.insert(len(valid) - 1, 'or')
        self.assertEqual(self._notices('duckexport bogus'),
                         [messages.tcl('en', 'm206', 'bogus', ' '.join(valid))])
        self.assertEqual(self._notices('duckexport xp level'),
                         [messages.tcl('en', 'm205', 'duckexport')])

    def _tclDb(self):
        import tempfile
        header = '--- Duck Hunt v2.11 ---\n---\n'
        body = ('%s {alice {gun 1 xp 150 ducks_shot 12 nick Alice current_ammo_clip 4 remaining_ammo_clips 1} '
                'bob {gun -1 xp 20 nick Bob}} #other {carol {xp 5}}' % self.channel)
        f = tempfile.NamedTemporaryFile('w', suffix='.db', delete=False, encoding='utf-8')
        f.write(header + body)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def testDuckimportAddsProfilesAndKeepsExistingOnes(self):
        cb = self._cb()
        self._players(alice=999)
        path = self._tclDb()
        m = self.assertNotError('duckimport ' + path)
        self.assertIn('2 channel(s): 2 profile(s) added, 0 replaced, 1 kept', m.args[1])
        alice = cb.db.getPlayer(self.irc.network, self.channel, 'alice')
        self.assertEqual(alice['xp'], 999)
        bob = cb.db.getPlayer(self.irc.network, self.channel, 'bob')
        self.assertEqual((bob['xp'], bob['gun_state'], bob['display_nick']), (20, 'confiscated_permanent', 'Bob'))
        self.assertEqual(cb.db.getPlayer(self.irc.network, '#other', 'carol')['xp'], 5)

    def testDuckimportOverwrite(self):
        cb = self._cb()
        self._players(alice=999)
        m = self.assertNotError('duckimport %s overwrite' % self._tclDb())
        self.assertIn('2 profile(s) added, 1 replaced', m.args[1])
        alice = cb.db.getPlayer(self.irc.network, self.channel, 'alice')
        self.assertEqual((alice['xp'], alice['stats']['killed'], alice['clip_ammo'], alice['clips_left']),
                         (150, 12, 4, 1))

    def testDuckimportRejectsABadFileAndABadWord(self):
        self.assertError('duckimport /nonexistent/player_data.db')
        self.assertError('duckimport %s please' % self._tclDb())

    def testExportOfAnEmptyDatabase(self):
        lines = self._export()
        self.assertIn(messages.tcl('en', 'm208'), lines)

    def testPositionalMessagesFormat(self):
        self.assertEqual(messages.tcl('en', 'm207', 'S', 'V', 'N', 'dd', 'mm', 'yyyy', 'time', 'xp'),
                         'S vV (©2015-2016 Menz Agitat) - N - Report generated on mm/dd/yyyy at time - sorted by xp')

    # -----------------------------------------------------------------
    # Phase 3: antiflood
    # -----------------------------------------------------------------

    def _flood(self, command, key, now, nick=None):
        cb = self._cb()
        msg = ircmsgs.privmsg(self.channel, 'x', prefix=(nick or self.nick) + '!u@h')
        blocked = cb._floodBlocked(self.irc, msg, self.channel, command, key, now)
        return blocked, self._texts(self._sent())

    def testFloodSettingsHaveTheOriginalsDefaults(self):
        cb = self._cb()
        self.assertEqual([cb._floodLimit(self.channel, k) for k in (
            'floodShoot', 'floodReload', 'floodStats', 'floodLastduck', 'floodShop', 'floodGlobal')],
            [(30, 600), (15, 120), (2, 120), (1, 300), (3, 600), (30, 600)])
        conf.supybot.plugins.DuckHuntPro.floodStats.setValue('banana')
        self.assertEqual(cb._floodLimit(self.channel, 'floodStats'), (2, 120))

    def testFloodBlocksAfterTheLimitAndWarnsOnce(self):
        conf.supybot.plugins.DuckHuntPro.antifloodEnabled.setValue(True)
        self.assertEqual(self._flood('duckstats', 'floodStats', 1000), (False, []))
        self.assertEqual(self._flood('duckstats', 'floodStats', 1001), (False, []))
        warning = messages.tcl('en', 'm273', self.nick, 'duckstats', 2, 'requests', 120, 'seconds')
        self.assertEqual(self._flood('duckstats', 'floodStats', 1002), (True, [warning]))
        self.assertEqual(self._flood('duckstats', 'floodStats', 1003), (True, []))   # silent

    def testFloodWarnsAgainAfterTheMessageInterval(self):
        conf.supybot.plugins.DuckHuntPro.antifloodEnabled.setValue(True)
        for now in (1000, 1001):
            self._flood('duckstats', 'floodStats', now)
        self._flood('duckstats', 'floodStats', 1002)                       # the warning
        self.assertEqual(self._flood('duckstats', 'floodStats', 1061), (True, []))
        self.assertEqual(self._flood('duckstats', 'floodStats', 1063),     # 60 s later
                         (True, [messages.tcl('en', 'm109')]))
        self.assertEqual(self._flood('duckstats', 'floodStats', 1064), (True, []))

    def testFloodReleasesUsesAfterTheWindow(self):
        conf.supybot.plugins.DuckHuntPro.antifloodEnabled.setValue(True)
        self._flood('duckstats', 'floodStats', 1000)
        self._flood('duckstats', 'floodStats', 1050)
        self.assertEqual(self._flood('duckstats', 'floodStats', 1100)[0], True)
        self.assertEqual(self._flood('duckstats', 'floodStats', 1120), (False, []))   # 1000 + 120
        self.assertEqual(self._flood('duckstats', 'floodStats', 1121)[0], True)

    def testFloodLimitsArePerPlayerAndPerCommand(self):
        conf.supybot.plugins.DuckHuntPro.antifloodEnabled.setValue(True)
        conf.supybot.plugins.DuckHuntPro.floodStats.setValue('1:100')
        self._flood('duckstats', 'floodStats', 1000)
        self.assertEqual(self._flood('duckstats', 'floodStats', 1001, nick='someoneelse')[0], False)
        self.assertEqual(self._flood('duckreload', 'floodReload', 1001)[0], False)
        self.assertEqual(self._flood('duckstats', 'floodStats', 1001)[0], True)

    def testGlobalFloodLimitCountsOnlyWhatTheCommandLimitLetsThrough(self):
        conf.supybot.plugins.DuckHuntPro.antifloodEnabled.setValue(True)
        conf.supybot.plugins.DuckHuntPro.floodGlobal.setValue('3:600')
        conf.supybot.plugins.DuckHuntPro.floodStats.setValue('1:600')
        self.assertEqual(self._flood('duckstats', 'floodStats', 1000)[0], False)   # global 1
        for now in (1001, 1002, 1003):
            self.assertEqual(self._flood('duckstats', 'floodStats', now)[0], True)  # own limit
        self.assertEqual(self._flood('duckreload', 'floodReload', 1004)[0], False)  # global 2
        self.assertEqual(self._flood('lastduck', 'floodLastduck', 1005, nick='x')[0], False)  # 3
        blocked, said = self._flood('duckreload', 'floodReload', 1006, nick='y')
        self.assertTrue(blocked)
        self.assertEqual(said, [messages.tcl('en', 'm103', 'DuckHuntPro', 3, 'requests', 600, 'seconds')])

    def testFloodWarningNamesThePlayerWhenTheGlobalLimitIsPerPlayerFocus(self):
        cb = self._cb()
        msg = ircmsgs.privmsg(self.channel, 'x', prefix=self.prefix)
        conf.supybot.plugins.DuckHuntPro.floodGlobal.setValue('1:600')
        cb._antiflood(self.irc, msg, self.channel, 'nick', '*', 'floodGlobal', 1000)
        self.assertTrue(cb._antiflood(self.irc, msg, self.channel, 'nick', '*', 'floodGlobal', 1001))
        self.assertEqual(self._texts(self._sent()),
                         [messages.tcl('en', 'm421', self.nick, 'DuckHuntPro', 1, 'request', 600, 'seconds')])

    def testFloodLeavesNothingBehindOnceEverythingIsReleased(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.antifloodEnabled.setValue(True)
        self._flood('duckstats', 'floodStats', 1000)
        self._flood('duckstats', 'floodStats', 1001)
        self._flood('duckstats', 'floodStats', 1002)              # warned
        self._flood('duckstats', 'floodStats', 5000)              # all released, allowed again
        state = [s for k, s in cb._floodState.items() if k[2] == 'duckstats'][0]
        self.assertEqual((len(state['times']), state['msg']), (1, 0))

    def testBangBlockedByAntiflood(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.antifloodEnabled.setValue(True)
        conf.supybot.plugins.DuckHuntPro.floodShoot.setValue('1:600')
        cb._rng = ScriptedRNG([100])
        self._cmd('bang')
        self._drain()
        sent = self._cmd('bang')
        self.assertEqual(self._texts(sent),
                         [messages.tcl('en', 'm273', self.nick, 'bang', 1, 'request', 600, 'seconds')])

    def testDisabledAntifloodNeverBlocks(self):
        for now in range(1000, 1010):
            self.assertEqual(self._flood('duckstats', 'floodStats', now), (False, []))

    # -----------------------------------------------------------------
    # Hunting logs (Duck_Hunt.tcl's add_to_log)
    # -----------------------------------------------------------------

    def _enableLogs(self):
        directory = tempfile.mkdtemp(prefix='duckhuntlogs')
        self.addCleanup(shutil.rmtree, directory, True)
        conf.supybot.plugins.DuckHuntPro.huntingLogs.setValue(True)
        conf.supybot.plugins.DuckHuntPro.huntingLogDirectory.setValue(directory)
        # Freeze the clock: a test that straddles a second boundary would
        # otherwise see two different time stamps.
        cb, real, frozen = self._cb(), self._cb()._huntLog, time.time()

        def huntLog(*args, **kwargs):
            if kwargs.get('now') is None:
                kwargs['now'] = frozen
            return real(*args, **kwargs)
        cb._huntLog = huntLog
        self.addCleanup(lambda: cb.__dict__.pop('_huntLog', None))
        return directory

    def _logLines(self, directory):
        files = os.listdir(directory)
        self.assertEqual(len(files), 1, files)
        with open(os.path.join(directory, files[0]), encoding='utf-8') as f:
            return f.read().split('\n')

    CLOCK = r'\[(\d\d:\d\d:\d\d)\]'

    def _stamped(self, line):
        """The log line's own clock, to build the expected text around it."""
        return re.search(self.CLOCK, line).group(1)

    def testHuntingLogsAreOffByDefaultAndWriteNothing(self):
        directory = tempfile.mkdtemp(prefix='duckhuntlogs')
        self.addCleanup(shutil.rmtree, directory, True)
        conf.supybot.plugins.DuckHuntPro.huntingLogDirectory.setValue(directory)
        self.assertFalse(conf.supybot.plugins.DuckHuntPro.huntingLogs())
        self._cmd('duckreload', setup=lambda p: self._tidy(p, ammo=1))
        self.assertEqual(os.listdir(directory), [])

    def testLogFileIsNamedAfterTheChannelAndTheCurrentDate(self):
        directory = self._enableLogs()
        cb = self._cb()
        cb._huntLog(self.channel, 'soaring', now=time.time() - 5 * 86400)
        self.assertEqual(os.listdir(directory),
                         ['%s_%s.log' % (self.channel, time.strftime('%Y%m%d'))])

    def testShotLineShowsAmmoClipsAndKillCount(self):
        directory = self._enableLogs()
        cb = self._putDuck()
        cb._rng = ScriptedRNG([100, 0])
        self._cmd('bang', setup=lambda p: self._tidy(p, ammo=6, clips=2))
        line = self._logLines(directory)[0]
        lvl = data.LEVELS[data.levelForXp(20)]
        self.assertRegex(line, r'^ \|-- ' + self.CLOCK + r' %s \(5/%d\|2/%d\)   \*BANG\* \\_X<  \*KWAK\* \(1 duck / [0-9.a-z]+\)$'
                         % (self.nick, lvl.clip_size, lvl.clip_count))

    def testMissJamEmptyAndReloadLines(self):
        directory = self._enableLogs()
        cb = self._putDuck()
        lvl = data.LEVELS[data.levelForXp(0)]
        cb._rng = ScriptedRNG([100, 100, 100])               # no jam, miss, no accident
        self._cmd('bang', setup=lambda p: self._tidy(p, ammo=3, clips=2))
        cb._rng = ScriptedRNG([0])                           # jams
        self._cmd('bang')
        self._cmd('duckreload')                              # unjams (the clip still has rounds)
        self._cmd('duckreload')                              # nothing to do: not logged
        lines = [l for l in self._logLines(directory) if l]
        counts = '%d/%d' % (3 - 1, lvl.clip_size), '2/%d' % lvl.clip_count
        # each line carries its own time stamp (the test can straddle a second)
        expected = [messages.tcl('en', key, self._stamped(line), self.nick, *counts)
                    for key, line in zip(('m162', 'm165', 'm166'), lines)]
        self.assertEqual(lines, expected)

    def testReloadAndEmptyShotLines(self):
        directory = self._enableLogs()
        cb = self._putDuck()
        lvl = data.LEVELS[data.levelForXp(0)]
        cb._rng = ScriptedRNG([100])
        self._cmd('bang', setup=lambda p: self._tidy(p, ammo=0, clips=2))          # *CLIC*
        self._cmd('duckreload')                                                    # *CLAC CLAC*
        lines = [l for l in self._logLines(directory) if l]
        stamp = self._stamped(lines[0])
        self.assertEqual(lines[0], messages.tcl('en', 'm163', stamp, self.nick, '0/%d' % lvl.clip_size,
                                                '2/%d' % lvl.clip_count))
        self.assertEqual(lines[1], messages.tcl('en', 'm164', stamp, self.nick, '%d/%d' % (lvl.clip_size, lvl.clip_size),
                                                '1/%d' % lvl.clip_count))

    def testWildFireAndConfiscationShareALine(self):
        directory = self._enableLogs()
        conf.supybot.plugins.DuckHuntPro.gunConfiscationOnWildFire.setValue(True)
        cb = self._cb()
        cb._rng = ScriptedRNG([100, 100, 100])               # no jam, no accident
        self._cmd('bang', setup=lambda p: self._tidy(p, ammo=3, clips=2))
        lines = [l for l in self._logLines(directory) if l]
        self.assertEqual(len(lines), 1, lines)
        stamp = self._stamped(lines[0])
        lvl = data.LEVELS[data.levelForXp(0)]
        self.assertEqual(lines[0], messages.tcl('en', 'm172', stamp, self.nick, '2/%d' % lvl.clip_size,
                                                '2/%d' % lvl.clip_count) + messages.tcl('en', 'm173'))

    def testWildFireWithoutConfiscationIsALineOfItsOwn(self):
        directory = self._enableLogs()
        conf.supybot.plugins.DuckHuntPro.gunConfiscationOnWildFire.setValue(False)
        cb = self._cb()
        cb._rng = ScriptedRNG([100, 100])
        self._cmd('bang', setup=lambda p: self._tidy(p, ammo=3, clips=2))
        self.assertEqual(self._logLines(directory)[1:], [''])

    def testRicochetKillAndDropLines(self):
        directory = self._enableLogs()
        cb = self._putDuck()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        self._tidy(player)
        cb._rng = ScriptedRNG(self._scriptedRollFor('grease'))
        conf.supybot.plugins.DuckHuntPro.dropsEnabled.setValue(True)
        cb._resolveDuckHit(self.irc, self.channel, self.irc.network, self.nick, 'en',
                           data.NORMAL_DAMAGE, isLucky=True)
        lines = [l for l in self._logLines(directory) if l]
        stamp = self._stamped(lines[1])
        self.assertEqual(lines[0], messages.tcl('en', 'm174'))
        self.assertEqual(lines[1], messages.tcl('en', 'm419', stamp, self.nick, messages.tcl('en', 'm411')))

    def testDropNamesForTheLog(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        for key, expected in (('xp_book_10', messages.tcl('en', 'm418', 10)),
                              ('ap_ammo', messages.tcl('en', 'm409')),
                              ('duck_detector', messages.tcl('en', 'm416'))):
            loot = []
            cb._rng = ScriptedRNG(self._scriptedRollFor(key))
            cb._rollAndApplyDrop(self.channel, player, self.nick, time.time(), lootOut=loot)
            self.assertEqual(loot, [expected])
        junk = messages.tclList('en', 'm394')
        loot = []
        cb._rng = ScriptedRNG(self._scriptedRollFor('junk') + [1])
        cb._rollAndApplyDrop(self.channel, player, self.nick, time.time(), lootOut=loot)
        self.assertEqual(loot, [junk[1]])

    def testShopPurchaseLineHasTheCost(self):
        directory = self._enableLogs()
        self._cmd('shop 6', setup=lambda p: self._tidy(p, xp=500))
        lines = [l for l in self._logLines(directory) if l]
        stamp = self._stamped(lines[0])
        self.assertEqual(lines, [messages.tcl('en', 'm306', stamp, self.nick, data.ITEM_COSTS['grease'])])

    def testShopTargetedPurchaseNamesTheTarget(self):
        directory = self._enableLogs()
        self._cb().db.player(self.irc.network, self.channel, 'bob')
        self._addOnlineNick('bob')
        self._cmd('shop 15 bob', setup=lambda p: self._tidy(p, xp=500))
        lines = [l for l in self._logLines(directory) if l]
        stamp = self._stamped(lines[0])
        self.assertEqual(lines, [messages.tcl('en', 'm315', stamp, self.nick, 'bob', data.ITEM_COSTS['sand'])])

    def testRefusedPurchaseIsNotLogged(self):
        directory = self._enableLogs()
        self._cmd('shop 6', setup=lambda p: self._tidy(p, xp=0))
        self.assertEqual(os.listdir(directory), [])

    def testUnarmAndRearmLines(self):
        directory = self._enableLogs()
        self._cb().db.player(self.irc.network, self.channel, 'bob')
        self._cmd('unarm bob')
        self._cmd('unarm -static bob')
        self._cmd('unarm bob')                    # a permanent confiscation becomes a temporary one
        self._cmd('rearm bob')
        lines = [l for l in self._logLines(directory) if l]
        stamp = self._stamped(lines[0])
        self.assertEqual(lines, [messages.tcl('en', 'm178', stamp, 'bob', self.nick),
                                 messages.tcl('en', 'm177', stamp, 'bob', self.nick),
                                 messages.tcl('en', 'm178', stamp, 'bob', self.nick),
                                 messages.tcl('en', 'm179', stamp, 'bob', self.nick)])

    def testSoaringAndEscapeLines(self):
        directory = self._enableLogs()
        cb = self._cb()
        cb._rng = ScriptedRNG([100])
        cb._spawnDuck(self.irc, self.channel)
        duck = cb._activeDuck[self._key()][0]
        cb._duckEscapes(self.irc.network, self.channel, duck['spawned_at'])
        cb._spawnDuck(self.irc, self.channel, isFake=True, forceNonGolden=True)
        cb._duckEscapes(self.irc.network, self.channel, cb._activeDuck[self._key()][0]['spawned_at'])
        lines = [l for l in self._logLines(directory) if l]
        stamp = self._stamped(lines[0])
        self.assertEqual(lines, [messages.tcl('en', 'm157', stamp), messages.tcl('en', 'm160', stamp),
                                 messages.tcl('en', 'm352', stamp), messages.tcl('en', 'm355', stamp)])

    def testManualLaunchHasItsOwnLineInsteadOfASoaringOne(self):
        directory = self._enableLogs()
        cb = self._cb()
        self._cmd('ducklaunch ' + self.channel)
        cb._removeDuck(self.irc.network, self.channel)
        lines = [l for l in self._logLines(directory) if l]
        self.assertEqual(lines, [messages.tcl('en', 'm158', self._stamped(lines[0]), self.nick)])

    def testScaredDucksAreLoggedOnePerDuck(self):
        directory = self._enableLogs()
        conf.supybot.plugins.DuckHuntPro.shotsBeforeDuckFlee.setValue(1)
        cb = self._putDuck()
        self._putDuck()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        self.assertEqual(cb._ducksScaring(self.irc.network, self.channel, player, time.time()), 2)
        lines = [l for l in self._logLines(directory) if l]
        self.assertEqual(lines, [messages.tcl('en', 'm159', self._stamped(lines[0]))] * 2)

    def testRefillAndHandBackLines(self):
        directory = self._enableLogs()
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, 'bob')
        cb._refillAmmo()
        cb._fireGunHandBack(self.irc.network, self.channel)
        lines = [l for l in self._logLines(directory) if l]
        stamp = self._stamped(lines[0])
        self.assertEqual(lines[:2], [messages.tcl('en', 'm175', stamp), messages.tcl('en', 'm176', stamp)])

    def testStatTransferLines(self):
        directory = self._enableLogs()
        cb = self._cb()
        for nick, xp in (('old', 30), ('new', 25)):
            cb.db.player(self.irc.network, self.channel, nick)['xp'] = xp
        before = cb._statsText(cb.db.getPlayer(self.irc.network, self.channel, 'old')), \
            cb._statsText(cb.db.getPlayer(self.irc.network, self.channel, 'new'))
        self._cmd('duckfusion %s new old' % self.channel)
        lines = [l for l in self._logLines(directory) if l]
        after = cb._statsText(cb.db.getPlayer(self.irc.network, self.channel, 'new'))
        stamp = self._stamped(lines[0])
        self.assertEqual(lines, [messages.tcl('en', 'm420', stamp, 'old', before[0], 'new', before[1], 'new', after)])

    def testAutomaticMergeLine(self):
        directory = self._enableLogs()
        cb = self._cb()
        for nick, xp in (('old', 30), ('new', 25)):
            cb.db.player(self.irc.network, self.channel, nick)['xp'] = xp
        cb.db.recordPendingTransfer(self.irc.network, self.channel, 'old', 'new')
        cb._checkPendingRename(self.irc, self.channel, 'new')
        lines = [l for l in self._logLines(directory) if l]
        self.assertEqual(len(lines), 1)
        self.assertIn('[Stats transfer]   hunter renaming to hunter: old {', lines[0])
        self.assertIn(' = new {', lines[0])

    def testEnforcedMergeLinesNeedWarnOnTakeover(self):
        directory = self._enableLogs()
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.confiscationEnforcementOnFusion.setValue(True)
        conf.supybot.plugins.DuckHuntPro.warnOnTakeover.setValue(False)
        cb.db.player(self.irc.network, self.channel, 'old')
        cb.db.player(self.irc.network, self.channel, 'new')['gun_state'] = 'confiscated'
        cb.db.recordPendingTransfer(self.irc.network, self.channel, 'old', 'new')
        cb._checkPendingRename(self.irc, self.channel, 'new')
        self.assertEqual(os.listdir(directory), [])
        conf.supybot.plugins.DuckHuntPro.warnOnTakeover.setValue(True)
        cb.db.player(self.irc.network, self.channel, 'old')
        cb.db.recordPendingTransfer(self.irc.network, self.channel, 'old', 'new')
        cb._checkPendingRename(self.irc, self.channel, 'new')
        lines = [l for l in self._logLines(directory) if l]
        self.assertIn('hunter renaming to unarmed hunter', lines[0])

    # -----------------------------------------------------------------
    # Multi-duck (removing the single-duck-per-channel cap)
    # -----------------------------------------------------------------

    def testMultipleDucksCanCoexist(self):
        cb = self._cb()
        cb._rng = ScriptedRNG([0, 4])  # golden-chance succeeds, hp roll -> 4
        cb._spawnDuck(self.irc, self.channel)
        cb._rng = ScriptedRNG([100])  # golden-chance fails
        cb._spawnDuck(self.irc, self.channel)
        ducks = cb._activeDuck[self._key()]
        self.assertEqual(len(ducks), 2)
        self.assertTrue(ducks[0]['is_golden'])
        self.assertFalse(ducks[1]['is_golden'])
        cb._removeDuck(self.irc.network, self.channel)
        cb._removeDuck(self.irc.network, self.channel)

    def testBangTargetsOldestDuckFirst(self):
        # Matches Duck_Hunt.tcl's hit_a_duck: always list-head (FIFO), never
        # random/closest-to-escaping/shotgun-spread.
        cb = self._cb()
        self._putDuck(hp_total=1)               # oldest -- should die
        self._putDuck(is_golden=True, hp_total=5)  # newer -- should survive
        cb._rng = ScriptedRNG([100, 0])  # no jam, hit
        self.assertNotError('bang')
        ducks = cb._activeDuck[self._key()]
        self.assertEqual(len(ducks), 1)
        self.assertTrue(ducks[0]['is_golden'])

    def testKillingOneDuckDoesNotAffectAnotherWithScaringOff(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.shotsBeforeDuckFlee.setValue(1)
        conf.supybot.plugins.DuckHuntPro.successfulShotsAlsoScareDucks.setValue(False)
        self._putDuck(hp_total=1)
        self._putDuck(hp_total=1)
        cb._rng = ScriptedRNG([100, 0])  # no jam, hit
        self.assertNotError('bang')
        ducks = cb._activeDuck.get(self._key())
        self.assertEqual(len(ducks), 1)
        self.assertEqual(ducks[0]['shots_fired'], 0)

    def testSuccessfulHitScaresOtherDucksWhenEnabled(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.shotsBeforeDuckFlee.setValue(1)
        conf.supybot.plugins.DuckHuntPro.successfulShotsAlsoScareDucks.setValue(True)
        self._putDuck(hp_total=1)  # oldest -- killed outright
        self._putDuck(hp_total=1)  # should flee from the scare propagation
        cb._rng = ScriptedRNG([100, 0])  # no jam, hit
        self.assertNotError('bang')
        self.assertTrue(self._key() not in cb._activeDuck)  # one killed, one fled

    def testMissAlwaysScaresAllDucksRegardlessOfSetting(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.shotsBeforeDuckFlee.setValue(1)
        conf.supybot.plugins.DuckHuntPro.successfulShotsAlsoScareDucks.setValue(False)
        self._putDuck(hp_total=1)
        self._putDuck(hp_total=1)
        cb._rng = ScriptedRNG([100, 100])  # no jam, miss
        self.assertNotError('bang')
        self.assertTrue(self._key() not in cb._activeDuck)  # both fled

    def testGoldenAndFakeDucksAreImmuneToScaring(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.shotsBeforeDuckFlee.setValue(1)
        self._putDuck(is_golden=True, hp_total=5)
        self._putDuck(is_fake=True, hp_total=1)
        cb._rng = ScriptedRNG([100, 100])  # no jam, miss
        self.assertNotError('bang')
        ducks = cb._activeDuck.get(self._key())
        self.assertEqual(len(ducks), 2)

    def testSilencerPreventsScaringEveryDuckNotJustTarget(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.shotsBeforeDuckFlee.setValue(1)
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        db.giveItem(player, 'silencer', time.time(), duration=86400)
        cb.db.save()
        self._putDuck(hp_total=1)
        self._putDuck(hp_total=1)
        cb._rng = ScriptedRNG([100, 100])  # no jam, miss
        self.assertNotError('bang')
        ducks = cb._activeDuck.get(self._key())
        self.assertEqual(len(ducks), 2)
        self.assertTrue(all(d['shots_fired'] == 0 for d in ducks))

    def testEscapeRemovesOnlyTheExpiredDuck(self):
        cb = self._cb()
        key = self._key()
        self._putDuck(hp_total=1)
        self._putDuck(hp_total=1)
        ducks = cb._activeDuck[key]
        expired, survivor = ducks[0]['spawned_at'], ducks[1]['spawned_at']
        cb._duckEscapes(self.irc.network, self.channel, expired)
        remaining = cb._activeDuck.get(key)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]['spawned_at'], survivor)
        cb._removeDuck(self.irc.network, self.channel)

    def testGunHandBackMode2WaitsForAllDucksGone(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.gunHandBackMode.setValue(2)
        conf.supybot.plugins.DuckHuntPro.successfulShotsAlsoScareDucks.setValue(False)
        other = cb.db.player(self.irc.network, self.channel, 'someoneElse')
        other['gun_state'] = 'confiscated'
        cb.db.save()
        self._putDuck(hp_total=1)
        self._putDuck(hp_total=1)
        cb._rng = ScriptedRNG([100, 0])  # no jam, hit -- kills only the oldest
        self.assertNotError('bang')
        other = cb.db.getPlayer(self.irc.network, self.channel, 'someoneElse')
        self.assertEqual(other['gun_state'], 'confiscated')  # one duck remains
        cb._removeDuck(self.irc.network, self.channel)
        cb._maybeHandBackOnDuckGone(self.irc.network, self.channel)
        other = cb.db.getPlayer(self.irc.network, self.channel, 'someoneElse')
        self.assertEqual(other['gun_state'], 'armed')

    def testSpecialSpawnCoexistsWithAnExistingDuck(self):
        cb = self._cb()
        self._putDuck(hp_total=1)
        self._richPlayer()
        self.assertEqual(len(self._cmd('shop 23')), 1)
        chan = cb.db.getChannel(self.irc.network, self.channel)
        firesAt = chan['fake_ducks_pending'][0]['fires_at']
        cb._fireSpecialSpawn(self.irc.network, self.channel, firesAt)
        ducks = cb._activeDuck[self._key()]
        self.assertEqual(len(ducks), 2)
        cb._removeDuck(self.irc.network, self.channel)
        cb._removeDuck(self.irc.network, self.channel)

    def testSameChannelNameDifferentNetworksAreIndependent(self):
        cb = self._cb()
        player1 = cb.db.player('NetworkOne', self.channel, self.nick)
        player1['xp'] = 500
        player2 = cb.db.player('NetworkTwo', self.channel, self.nick)
        cb.db.save()
        self.assertEqual(player2['xp'], 0)
        self.assertEqual(cb.db.getPlayer('networkone', self.channel, self.nick)['xp'], 500)


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
