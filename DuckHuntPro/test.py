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
import time
import urllib.parse
from datetime import datetime

from supybot.test import *
import supybot.schedule as schedule
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

    def setUp(self):
        super().setUp()
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

    def _richPlayer(self, nick=None):
        nick = nick or self.nick
        player = self._cb().db.player(self.irc.network, self.channel, nick)
        player['xp'] = 100000
        self._cb().db.save()
        return player

    def _addOnlineNick(self, nick):
        self.irc.state.channels[self.channel].addUser(nick)

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

    def _putDuck(self, is_golden=False, hp_total=1):
        cb = self._cb()
        cb._activeDuck[self._key()] = {
            'spawned_at': time.time(), 'is_golden': is_golden,
            'hp_total': hp_total, 'hp_left': hp_total, 'shots_fired': 0,
        }
        return cb

    def testLevelTableSanity(self):
        self.assertEqual(len(data.LEVELS), 41)
        prev = None
        for lvl in data.LEVELS:
            if prev is not None:
                self.assertTrue(lvl.xp_to_next > prev,
                                 'level xp thresholds must strictly increase')
            prev = lvl.xp_to_next
            for pct in (lvl.accuracy, lvl.deflection, lvl.defense, lvl.jam_pct):
                self.assertTrue(0 <= pct <= 100, 'percentage field out of range: %r' % (lvl,))
            self.assertTrue(lvl.clip_size >= 1)
            self.assertTrue(lvl.clip_count >= 1)
        # Matches the source's documented starting condition.
        self.assertEqual(data.levelForXp(0), 1)

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
        self.assertEqual(player['xp'], 0)  # -1 penalty clamped to 0
        self.assertEqual(player['stats']['missed'], 1)
        self.assertEqual(cb._activeDuck[key]['shots_fired'], 1)

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
        self.assertEqual(cb._activeDuck[key]['hp_left'], 1)

        cb._rng = ScriptedRNG([100, 0])
        self.assertNotError('bang')
        self.assertTrue(key not in cb._activeDuck)
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['xp'], data.BASE_XP_GOLDEN_DUCK * 2)
        self.assertEqual(player['stats']['golden_killed'], 1)

    def testJamBlocksShotAndStillConsumesAmmo(self):
        cb = self._cb()
        cb._rng = ScriptedRNG([0])  # jam roll succeeds
        self.assertNotError('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertTrue(player['jammed'])
        self.assertEqual(player['stats']['jams'], 1)
        lvl = data.LEVELS[data.levelForXp(player['xp'])]
        self.assertEqual(player['clip_ammo'], lvl.clip_size - 1)

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
        self.assertRegexp('bang', 'empty')
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
        self.assertRegexp('bang', "doesn't have a gun")

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
        duck = cb._activeDuck[key]
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
        duck = cb._activeDuck[self._key()]
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
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        db.giveItem(player, 'sabotage', time.time(), duration=None, uses=1, value='bob')
        cb.db.save()
        self._putDuck()
        # No jam-roll rng call at all: forcedJam short-circuits it. Only the
        # ammo/level lookups need no rng, so the queue can stay empty.
        cb._rng = ScriptedRNG([])
        # Not assertNotError() here: KICK is a high-priority IRC command in
        # Limnoria's outgoing queue (see IrcMsgQueue._high in irclib.py), so
        # it jumps ahead of the plain PRIVMSG queued just before it --
        # assertNotError's single takeMsg() would grab the KICK and leave
        # the drain loop below with nothing to find. getMsg() still waits
        # (via its internal poll loop) for the threaded command to finish,
        # unlike a bare feedMsg().
        m = self.getMsg('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertTrue(player['jammed'])
        kicked = m is not None and m.command == 'KICK'
        m = self.irc.takeMsg()
        while m is not None:
            if m.command == 'KICK':
                kicked = True
            m = self.irc.takeMsg()
        self.assertTrue(kicked)

    def testInfraredBlocksWildShotWithoutConsumingAmmo(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        db.giveItem(player, 'infrared_detector', time.time(), duration=86400, uses=6)
        cb.db.save()
        self.assertRegexp('bang', 'locked')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertTrue(player['clip_ammo'] is None)  # ammo system never even ran
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
        self.assertEqual(cb._activeDuck[self._key()]['shots_fired'], 0)

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

    def testWaterBucketBlocksShootingEntirely(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        db.giveItem(player, 'water_bucket', time.time(), duration=3600, value='bob')
        cb.db.save()
        self._putDuck()
        self.assertRegexp('bang', 'wet')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(player['clip_ammo'], None)  # never even got to ammo check

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
        cb._activeDuck[self._key()] = {
            'spawned_at': time.time(), 'is_golden': False,
            'hp_total': 1, 'hp_left': 1, 'shots_fired': 0, 'is_fake': True,
        }
        cb._rng = ScriptedRNG([100, 0])  # no jam, hit
        self.assertNotError('bang')
        player = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        # Fake ducks are worth 0 xp on their own; the clover bonus (5) still
        # applies on top -- a deliberate parity quirk from Duck_Hunt.tcl.
        self.assertEqual(player['xp'], 5)

    # -----------------------------------------------------------------
    # Phase 2: drop table
    # -----------------------------------------------------------------

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
        msg = cb._rollAndApplyDrop(player, 'en', time.time())
        self.assertTrue('10' in msg)
        self.assertEqual(player['xp'], 10)

    def testRollAndApplyDropGrantsItem(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        cb._rng = ScriptedRNG(self._scriptedRollFor('grease'))
        now = time.time()
        msg = cb._rollAndApplyDrop(player, 'en', now)
        self.assertTrue('grease' in msg)
        self.assertTrue(db.itemActive(player, 'grease', now) is not None)

    def testRollAndApplyDropJunkIsFlavorOnly(self):
        cb = self._cb()
        player = cb.db.player(self.irc.network, self.channel, self.nick)
        cb._rng = ScriptedRNG(self._scriptedRollFor('junk'))
        msg = cb._rollAndApplyDrop(player, 'en', time.time())
        self.assertTrue(any(flavor in msg for flavor in messages.JUNK_FLAVORS))
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
        self._addOnlineNick('bob')
        bob = cb.db.player(self.irc.network, self.channel, 'bob')
        bob['last_activity'] = time.time()
        cb.db.save()
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
        self._addOnlineNick('bob')
        bob = cb.db.player(self.irc.network, self.channel, 'bob')
        bob['xp'] = 200
        bob['last_activity'] = time.time()
        cb.db.save()
        self._putDuck()
        cb._rng = ScriptedRNG([100, 100, 0, 0, 100, 0])  # deflect fails, defense succeeds
        self.assertNotError('bang')
        bobP = cb.db.getPlayer(self.irc.network, self.channel, 'bob')
        self.assertEqual(bobP['stats']['absorbed'], 1)
        self.assertEqual(bobP['stats']['deaths'], 0)

    def testAccidentRicochetIntoDuckKillsItWithLuckyBonus(self):
        cb = self._cb()
        self._addOnlineNick('bob')
        bob = cb.db.player(self.irc.network, self.channel, 'bob')
        bob['xp'] = 1000  # a level with deflection > 0
        bob['last_activity'] = time.time()
        cb.db.save()
        self._putDuck()
        # jam(no), accuracy(miss), accident-chance(hit), victim-pick(bob),
        # deflect(succeed), ricochet-towards-duck(succeed)
        cb._rng = ScriptedRNG([100, 100, 0, 0, 0, 0])
        self.assertNotError('bang')
        shooter = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        self.assertEqual(shooter['xp'], data.XP_PER_DUCK + data.XP_LUCKY_SHOT)
        self.assertTrue(self._key() not in cb._activeDuck)

    def testAccidentLifeInsurancePaysOutRegardlessOfOutcome(self):
        cb = self._cb()
        self._addOnlineNick('bob')
        bob = cb.db.player(self.irc.network, self.channel, 'bob')
        bob['xp'] = 100
        bob['last_activity'] = time.time()
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
        self._addOnlineNick('bob')
        cb.db.player(self.irc.network, self.channel, 'bob')['last_activity'] = time.time()
        shooter = cb.db.player(self.irc.network, self.channel, self.nick)
        shooter['xp'] = 500
        lvl = data.LEVELS[data.levelForXp(500)]
        db.giveItem(shooter, 'liability_insurance', time.time(), duration=172800)
        cb.db.save()
        self._putDuck()
        cb._rng = ScriptedRNG([100, 100, 0, 0, 100, 100])
        self.assertNotError('bang')
        shooter = cb.db.getPlayer(self.irc.network, self.channel, self.nick)
        expected = max(0, 500 + lvl.xp_missed_shot + int(lvl.xp_accident / 3))
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

    def testRandomDuckArtVariesAndUsesKnownGlyphs(self):
        rng = random.Random(42)
        arts = {data.randomDuckArt(rng) for _ in range(20)}
        self.assertTrue(len(arts) > 1)
        for art in arts:
            self.assertTrue(any(glyph in art for glyph in data.DUCK_GLYPHS))

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

    def testAdminPlanningShowsFlightCount(self):
        cb = self._cb()
        chan = cb.db.channel(self.irc.network, self.channel)
        chan['planned_flights'] = [time.time() + 100]
        cb.db.save()
        self.assertNotError('admin planning')

    def testAdminReplanningRebuildsSchedule(self):
        cb = self._cb()
        self.assertNotError('admin replanning')
        chan = cb.db.getChannel(self.irc.network, self.channel)
        self.assertTrue(len(chan['planned_flights']) > 0)

    def testAdminLaunchForcesImmediateSpawn(self):
        cb = self._cb()
        self.assertNotError('admin launch')
        self.assertTrue(self._key() in cb._activeDuck)
        cb._removeDuck(self.irc.network, self.channel)

    def testAdminLaunchBlockedWhenDuckAlreadyPresent(self):
        cb = self._cb()
        self._putDuck()
        self.assertRegexp('admin launch', 'already in flight')

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

    def testSameChannelNameDifferentNetworksAreIndependent(self):
        cb = self._cb()
        player1 = cb.db.player('NetworkOne', self.channel, self.nick)
        player1['xp'] = 500
        player2 = cb.db.player('NetworkTwo', self.channel, self.nick)
        cb.db.save()
        self.assertEqual(player2['xp'], 0)
        self.assertEqual(cb.db.getPlayer('networkone', self.channel, self.nick)['xp'], 500)


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
