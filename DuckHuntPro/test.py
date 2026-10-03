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

import random
import re
import time
import urllib.parse
from datetime import datetime

from supybot.test import *
import supybot.schedule as schedule
import supybot.drivers as drivers
from supybot import ircmsgs

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
        from the registry defaults instead."""
        for name, value in conf.supybot.plugins.DuckHuntPro.getValues(getChildren=True):
            if '.web.' in name:       # its callbacks start/stop the HTTP server
                continue
            if hasattr(value, '_default') and hasattr(value, 'setValue'):
                value.setValue(value._default)

    def setUp(self):
        super().setUp()
        self._resetConfig()
        conf.supybot.plugins.DuckHuntPro.enabled.setValue(True)
        # Drops are rolled per-key with a bottomless RNG queue in most
        # tests; leaving this on would let an exhausted ScriptedRNG queue
        # (which falls back to returning its lower bound, 1) silently
        # trigger a 'junk' drop on nearly every kill and queue an extra,
        # unexpected message. Dedicated drop-table tests re-enable it with
        # a fully-scripted queue.
        conf.supybot.plugins.DuckHuntPro.dropsEnabled.setValue(False)
        # Same reasoning: conf values are a process-global singleton that
        # persists across test methods, so a low antifloodMaxPerMinute set
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

    def testReloadClearsJam(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        player['jammed'] = True
        cb.db.save()
        self.assertNotError('duckreload')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertFalse(player['jammed'])

    def testReloadFullClipReportsNoOp(self):
        self.assertRegexp('duckreload', 'already full')

    def testReloadNoClipsLeftError(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        lvl = data.LEVELS[data.levelForXp(player['xp'])]
        player['clip_ammo'] = lvl.clip_size - 1
        player['clips_left'] = 0
        cb.db.save()
        self.assertRegexp('duckreload', 'no spare clips')

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

    def testShopListShowsCatalog(self):
        m = self.assertNotError('shop list')
        self.assertTrue('grease' in m.args[1])

    def testBuyUnknownItemFails(self):
        self._richPlayer()
        self.assertRegexp('shop buy nonsense', "isn't sold")

    def testMinXpForShoppingBlocksPurchase(self):
        # Fresh player starts at 0 xp; extra_ammo costs 7.
        self.assertRegexp('shop buy extra_ammo', 'xp floor')

    def testShopBlockedWhenGunConfiscatedExceptBuyback(self):
        player = self._richPlayer()
        player['gun_state'] = 'confiscated'
        self._cb().db.save()
        self.assertRegexp('shop buy grease', 'confiscated')
        # buyback_weapon is the one exemption -- otherwise a confiscated
        # player could never buy their way back to armed.
        self.assertNotError('shop buy buyback_weapon')
        player = self._cb().db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['gun_state'], 'armed')

    def testBuybackRequiresConfiscatedGun(self):
        self._richPlayer()
        self.assertRegexp('shop buy buyback_weapon', "isn't confiscated")

    def testBuyExtraAmmoAddsRoundAndChargesXp(self):
        cb = self._cb()
        player = self._richPlayer()
        player['clip_ammo'] = 0
        cb.db.save()
        self.assertNotError('shop buy extra_ammo')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['clip_ammo'], 1)
        self.assertEqual(player['xp'], 100000 - data.ITEM_COSTS['extra_ammo'])

    def testBuyExtraAmmoBlockedWhenClipFull(self):
        cb = self._cb()
        player = self._richPlayer()
        lvl = data.LEVELS[data.levelForXp(player['xp'])]
        player['clip_ammo'] = lvl.clip_size
        cb.db.save()
        self.assertRegexp('shop buy extra_ammo', 'already full')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['xp'], 100000)  # not charged

    def testBuyExtraClipBlockedWhenAtCap(self):
        cb = self._cb()
        player = self._richPlayer()
        lvl = data.LEVELS[data.levelForXp(player['xp'])]
        player['clips_left'] = lvl.clip_count
        cb.db.save()
        self.assertRegexp('shop buy extra_clip', 'max number')

    def testAmmoTypesAreMutuallyExclusive(self):
        cb = self._cb()
        self._richPlayer()
        now = time.time()
        self.assertNotError('shop buy ap_ammo')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertTrue(db.itemActive(player, 'ap_ammo', now) is not None)
        self.assertNotError('shop buy explosive_ammo')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertTrue(db.itemActive(player, 'ap_ammo', now) is None)
        self.assertTrue(db.itemActive(player, 'explosive_ammo', now) is not None)

    def testBuyingActiveItemTwiceIsBlocked(self):
        self._richPlayer()
        self.assertNotError('shop buy grease')
        self.assertRegexp('shop buy grease', 'already has')

    def testBuyCloverStoresRandomBonus(self):
        cb = self._cb()
        self._richPlayer()
        cb._rng = ScriptedRNG([7])
        self.assertNotError('shop buy four_leaf_clover')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        item = db.itemActive(player, 'four_leaf_clover', time.time())
        self.assertEqual(item['value'], 7)

    def testBuySightGivesUsableItem(self):
        self._richPlayer()
        self.assertNotError('shop buy sight')
        player = self._cb().db.getPlayer(self.irc.network, self.channel, self.nick)
        item = db.itemActive(player, 'sight', time.time())
        self.assertEqual(item['uses_left'], 1)

    def testMirrorRequiresTarget(self):
        self._richPlayer()
        self.assertRegexp('shop buy mirror', 'needs a target')

    def testMirrorCannotTargetSelf(self):
        self._richPlayer()
        self.assertRegexp('shop buy mirror %s' % self.nick, "target yourself")

    def testMirrorTargetMustBeOnline(self):
        self._richPlayer()
        self._cb().db.player(self.irc.network, self.channel, 'ghost')
        self.assertRegexp('shop buy mirror ghost', "isn't in the channel")

    def testMirrorTargetMustHavePlayed(self):
        self._richPlayer()
        self._addOnlineNick('newbie')
        self.assertRegexp('shop buy mirror newbie', "hasn't played")

    def testMirrorAppliesDazzleToTarget(self):
        cb = self._cb()
        self._richPlayer()
        self._addOnlineNick('bob')
        cb.db.player(self.irc.network, self.channel, 'bob')
        self.assertNotError('shop buy mirror bob')
        target = cb.db.getPlayer(self.irc.network, self.channel, 'bob')
        self.assertTrue(db.itemActive(target, 'mirror_dazzle', time.time()) is not None)

    def testMirrorFailsHarmlesslyAgainstSunglasses(self):
        cb = self._cb()
        self._richPlayer()
        self._addOnlineNick('bob')
        bob = cb.db.player(self.irc.network, self.channel, 'bob')
        db.giveItem(bob, 'sunglasses', time.time(), duration=86400)
        cb.db.save()
        self.assertRegexp('shop buy mirror bob', 'sunglasses')
        # still charged even though it had no effect
        me = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(me['xp'], 100000 - data.ITEM_COSTS['mirror'])
        self.assertTrue(db.itemActive(bob, 'mirror_dazzle', time.time()) is None)

    def testSandRequiresTargetWithGun(self):
        cb = self._cb()
        self._richPlayer()
        self._addOnlineNick('bob')
        bob = cb.db.player(self.irc.network, self.channel, 'bob')
        bob['gun_state'] = 'confiscated'
        cb.db.save()
        self.assertRegexp('shop buy sand bob', "doesn't have a weapon")

    def testSandAbsorbedByGrease(self):
        cb = self._cb()
        self._richPlayer()
        self._addOnlineNick('bob')
        bob = cb.db.player(self.irc.network, self.channel, 'bob')
        db.giveItem(bob, 'grease', time.time(), duration=86400)
        cb.db.save()
        self.assertRegexp('shop buy sand bob', 'greased')
        self.assertTrue(db.itemActive(bob, 'grease', time.time()) is None)
        self.assertTrue(db.itemActive(bob, 'sand', time.time()) is None)

    def testWaterBucketAppliesHourLongDebuff(self):
        cb = self._cb()
        self._richPlayer()
        self._addOnlineNick('bob')
        cb.db.player(self.irc.network, self.channel, 'bob')
        self.assertNotError('shop buy water_bucket bob')
        bob = cb.db.getPlayer(self.irc.network, self.channel, 'bob')
        item = db.itemActive(bob, 'water_bucket', time.time())
        self.assertTrue(item is not None)
        self.assertTrue(3500 < item['expires_at'] - time.time() <= 3600)

    def testSabotageRequiresTargetWithGun(self):
        cb = self._cb()
        self._richPlayer()
        self._addOnlineNick('bob')
        bob = cb.db.player(self.irc.network, self.channel, 'bob')
        bob['gun_state'] = 'confiscated'
        cb.db.save()
        self.assertRegexp('shop buy sabotage bob', "doesn't have a weapon")

    def testSpareClothesCuresWaterBucket(self):
        cb = self._cb()
        player = self._richPlayer()
        db.giveItem(player, 'water_bucket', time.time(), duration=3600, value='bob')
        cb.db.save()
        self.assertNotError('shop buy spare_clothes')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertTrue(db.itemActive(player, 'water_bucket', time.time()) is None)

    def testSpareClothesNoopWithoutWaterBucket(self):
        self._richPlayer()
        self.assertRegexp('shop buy spare_clothes', "doesn't need")

    def testBrushCuresSandAndSabotage(self):
        cb = self._cb()
        player = self._richPlayer()
        now = time.time()
        db.giveItem(player, 'sand', now, duration=None, uses=1, value='bob')
        db.giveItem(player, 'sabotage', now, duration=None, uses=1, value='bob')
        cb.db.save()
        self.assertNotError('shop buy brush')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertTrue(db.itemActive(player, 'sand', now) is None)
        self.assertTrue(db.itemActive(player, 'sabotage', now) is None)

    def testLifeAndLiabilityInsurancePurchaseOnly(self):
        # Phase 2 doesn't implement the friendly-fire/accident mechanic yet
        # (that's Phase 3), so these items can be bought and stored but have
        # no bang()-time trigger point wired up yet -- this just confirms
        # the purchase and item-storage side works.
        cb = self._cb()
        self._richPlayer()
        self.assertNotError('shop buy life_insurance')
        self.assertNotError('shop buy liability_insurance')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        now = time.time()
        self.assertTrue(db.itemActive(player, 'life_insurance', now) is not None)
        self.assertTrue(db.itemActive(player, 'liability_insurance', now) is not None)

    def testBuyDecoySchedulesPendingSpawn(self):
        cb = self._cb()
        self._richPlayer()
        cb._rng = ScriptedRNG([42])
        self.assertNotError('shop buy decoy')
        chan = cb.db.getChannel(self.irc.network, self.channel)
        self.assertEqual(len(chan['fake_ducks_pending']), 1)
        self.assertEqual(chan['fake_ducks_pending'][0]['kind'], 'decoy')

    def testBuyFakeDuckSchedulesFixedDelaySpawn(self):
        cb = self._cb()
        self._richPlayer()
        before = time.time()
        self.assertNotError('shop buy fake_duck')
        chan = cb.db.getChannel(self.irc.network, self.channel)
        entry = chan['fake_ducks_pending'][0]
        self.assertEqual(entry['kind'], 'fake_duck')
        self.assertTrue(entry['force_non_golden'])
        self.assertEqual(entry['buyer'], self.nick)
        self.assertTrue(abs(entry['fires_at'] - (before + data.FAKE_DUCK_DELAY)) < 5)

    def testFireSpecialSpawnProducesFakeDuck(self):
        cb = self._cb()
        self._richPlayer()
        self.assertNotError('shop buy fake_duck')
        chan = cb.db.getChannel(self.irc.network, self.channel)
        firesAt = chan['fake_ducks_pending'][0]['fires_at']
        cb._fireSpecialSpawn(self.irc.network, self.channel, firesAt)
        duck = cb._activeDuck[self._key()][0]
        self.assertTrue(duck['is_fake'])
        self.assertFalse(duck['is_golden'])
        cb._removeDuck(self.irc.network, self.channel)

    def testBreadStacksAndCapsAtMax(self):
        cb = self._cb()
        self._richPlayer()
        conf.supybot.plugins.DuckHuntPro.maxBreadOnChan.setValue(2)
        self.assertNotError('shop buy bread')
        self.assertNotError('shop buy bread')
        self.assertRegexp('shop buy bread', 'enough bread')
        chan = cb.db.getChannel(self.irc.network, self.channel)
        self.assertEqual(len(chan['bread']), 2)

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
        self.assertEqual(len(chan['planned_flights']), expectedCount)

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
        self.assertNotError('unarm bob')
        bob = cb.db.getPlayer(self.irc.network, self.channel, 'bob')
        self.assertEqual(bob['gun_state'], 'confiscated')
        self.assertNotError('rearm bob')
        bob = cb.db.getPlayer(self.irc.network, self.channel, 'bob')
        self.assertEqual(bob['gun_state'], 'armed')

    def testUnarmStaticSurvivesModeBasedHandBack(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.gunHandBackMode.setValue(2)
        self.assertNotError('unarm bob static')
        bob = cb.db.getPlayer(self.irc.network, self.channel, 'bob')
        self.assertEqual(bob['gun_state'], 'confiscated_permanent')
        cb._maybeHandBackOnDuckGone(self.irc.network, self.channel)
        bob = cb.db.getPlayer(self.irc.network, self.channel, 'bob')
        self.assertEqual(bob['gun_state'], 'confiscated_permanent')

    def testBuybackRefusesPermanentConfiscation(self):
        cb = self._cb()
        player = self._richPlayer()
        player['gun_state'] = 'confiscated_permanent'
        cb.db.save()
        self.assertRegexp('shop buy buyback_weapon', 'only an op')

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

    # -----------------------------------------------------------------
    # Phase 3: admin toolbox
    # -----------------------------------------------------------------

    def testAdminListShowsPlayers(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, 'alice')['xp'] = 50
        cb.db.save()
        self.assertNotError('admin list')

    def testAdminFusionMergesStats(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, 'alice')['xp'] = 50
        cb.db.player(self.irc.network, self.channel, 'bob')['xp'] = 30
        cb.db.save()
        self.assertNotError('admin fusion bob alice')
        bob = cb.db.getPlayer(self.irc.network, self.channel, 'bob')
        self.assertEqual(bob['xp'], 80)
        self.assertTrue(cb.db.getPlayer(self.irc.network, self.channel, 'alice') is None)

    def testAdminRenameRefusesExistingTarget(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, 'alice')
        cb.db.player(self.irc.network, self.channel, 'bob')
        cb.db.save()
        self.assertRegexp('admin rename alice bob', 'already has a profile')

    def testAdminDeleteRemovesProfile(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, 'alice')
        cb.db.save()
        self.assertNotError('admin delete alice')
        self.assertTrue(cb.db.getPlayer(self.irc.network, self.channel, 'alice') is None)

    def testAdminPlanningShowsTimeList(self):
        cb = self._cb()
        chan = cb.db.channel(self.irc.network, self.channel)
        t1 = datetime(2026, 1, 1, 3, 14).timestamp()
        t2 = datetime(2026, 1, 1, 9, 5).timestamp()
        chan['planned_flights'] = [t2, t1]  # out of order on purpose
        cb.db.save()
        m = self.assertNotError('admin planning')
        self.assertTrue('03:14' in m.args[1] and '09:05' in m.args[1])
        self.assertTrue(m.args[1].index('03:14') < m.args[1].index('09:05'))  # sorted

    def testAdminPlanningEmpty(self):
        self.assertRegexp('admin planning', 'No flights')

    def testAdminReplanningRebuildsSchedule(self):
        cb = self._cb()
        m = self.assertNotError('admin replanning')
        chan = cb.db.getChannel(self.irc.network, self.channel)
        self.assertTrue(len(chan['planned_flights']) > 0)
        # Message shows the actual new times, not just a generic "done".
        self.assertTrue(re.search(r'\d{2}:\d{2}', m.args[1]))

    def testAdminLaunchForcesImmediateSpawn(self):
        cb = self._cb()
        self.assertNotError('admin launch')
        self.assertTrue(self._key() in cb._activeDuck)
        cb._removeDuck(self.irc.network, self.channel)

    def testAdminLaunchAddsToExistingDucksInsteadOfBlocking(self):
        # Matches Duck_Hunt.tcl's !ducklaunch: never checks for an existing
        # duck, so launching while one's already in flight just adds a
        # second one rather than being refused.
        cb = self._cb()
        self._putDuck()
        self.assertNotError('admin launch')
        self.assertEqual(len(cb._activeDuck[self._key()]), 2)

    def testAdminExportWritesFile(self):
        cb = self._cb()
        cb.db.player(self.irc.network, self.channel, 'alice')['xp'] = 10
        cb.db.save()
        m = self.assertNotError('admin export')
        self.assertTrue('exported' in m.args[1])

    # -----------------------------------------------------------------
    # Phase 3: antiflood
    # -----------------------------------------------------------------

    def testFloodCheckAllowsUpToLimitThenBlocks(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.antifloodEnabled.setValue(True)
        conf.supybot.plugins.DuckHuntPro.antifloodMaxPerMinute.setValue(2)
        network, channel, nick = self.irc.network, self.channel, self.nick
        self.assertTrue(cb._floodCheck(network, channel, nick))
        self.assertTrue(cb._floodCheck(network, channel, nick))
        self.assertFalse(cb._floodCheck(network, channel, nick))

    def testBangBlockedByAntiflood(self):
        cb = self._cb()
        conf.supybot.plugins.DuckHuntPro.antifloodEnabled.setValue(True)
        conf.supybot.plugins.DuckHuntPro.antifloodMaxPerMinute.setValue(1)
        cb._rng = ScriptedRNG([100])
        self.assertNotError('bang')
        self._drain()
        self.assertRegexp('bang', 'slow down')

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
        self.assertNotError('shop buy fake_duck')
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
