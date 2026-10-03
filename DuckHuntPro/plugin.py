import html
import os
import random
import time
import urllib.parse
from datetime import datetime, timedelta

from supybot.commands import *
from supybot import callbacks, conf, ircmsgs, ircutils, schedule, world
import supybot.httpserver as httpserver

from . import data
from . import messages
from . import db
from .db import Database

try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('DuckHuntPro')
except ImportError:
    _ = lambda x: x


QUARTER_MONTHS = (1, 4, 7, 10)


class _WebNotFound(Exception):
    pass


class DuckHuntProWebCallback(httpserver.SupyHTTPServerCallback):
    name = 'DuckHuntPro web dashboard'

    def doGetOrHead(self, handler, path, write_content):
        try:
            body = self._plugin._renderWeb(path)
        except _WebNotFound:
            self.send_response(404)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            if write_content:
                self.write('Not found.')
            return
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        if write_content:
            self.write(body)

    def doGet(self, handler, path):
        self.doGetOrHead(handler, path, True)

    def doHead(self, handler, path):
        self.doGetOrHead(handler, path, False)


class DuckHuntPro(callbacks.Plugin):
    """A full-featured duck-hunting game, ported from the eggdrop TCL
    "Duck Hunt" v2.11 script: core spawn/shoot/level loop, the full 23-item
    shop economy and kill drop table, friendly-fire/ricochet, weapon
    confiscation, automatic nick-change stat fusion, and an admin toolbox.
    Network-independent (the same channel name on two different networks
    is two entirely separate games)."""

    threaded = True

    def __init__(self, irc):
        super().__init__(irc)
        self._rng = random.Random()
        dbPath = os.path.join(str(conf.supybot.directories.data),
                               'DuckHuntPro', 'duckhuntpro.json')
        self.db = Database(dbPath)
        self._activeDuck = {}    # (network(lower), channel(lower)) -> [duck dict, ...]
                                 # oldest-first; multiple ducks coexist,
                                 # bang()/accidents always target index 0
        self._scheduled = set()  # event names we've scheduled, for die()
        self._httpRunning = False
        self._floodWindows = {}  # (network, channel, nick) -> [timestamps]
        self._shopHandlers = {
            'extra_ammo': self._buyExtraAmmo,
            'extra_clip': self._buyExtraClip,
            'ap_ammo': self._buyApAmmo,
            'explosive_ammo': self._buyExplosiveAmmo,
            'buyback_weapon': self._buyBuyback,
            'grease': self._buyGrease,
            'sight': self._buySight,
            'infrared_detector': self._buyInfrared,
            'silencer': self._buySilencer,
            'four_leaf_clover': self._buyClover,
            'sunglasses': self._buySunglasses,
            'spare_clothes': self._buySpareClothes,
            'brush': self._buyBrush,
            'mirror': self._buyMirror,
            'sand': self._buySand,
            'water_bucket': self._buyWaterBucket,
            'sabotage': self._buySabotage,
            'life_insurance': self._buyLifeInsurance,
            'liability_insurance': self._buyLiabilityInsurance,
            'decoy': self._buyDecoy,
            'bread': self._buyBread,
            'duck_detector': self._buyDuckDetector,
            'fake_duck': self._buyFakeDuck,
        }
        # The nested `shop`/`admin` command groups are instantiated by
        # BasePlugin's __init__ (above) but have no reference to this
        # instance -- hand them one explicitly, same as Blacklist's
        # exempt/net groups. (Found the hard way in Phase 2: this is NOT
        # automatic and forgetting it only fails at runtime.)
        self.shop.plugin = self
        self.admin.plugin = self
        self._reschedulePlannedFlights(irc)
        self._scheduleAmmoRefill()
        if self.registryValue('quarterlyResetEnabled'):
            self._scheduleQuarterlyReset()
        conf.supybot.plugins.DuckHuntPro.web.enable.addCallback(self._doWebConf)
        if self.registryValue('web.enable'):
            self._startHttp()

    def die(self):
        conf.supybot.plugins.DuckHuntPro.web.enable.removeCallback(self._doWebConf)
        self._stopHttp()
        for name in list(self._scheduled):
            self._unschedule(name)
        super().die()

    # -----------------------------------------------------------------
    # Web dashboard
    # -----------------------------------------------------------------

    def _doWebConf(self, _):
        if self.registryValue('web.enable') and not self._httpRunning:
            self._startHttp()
        elif not self.registryValue('web.enable') and self._httpRunning:
            self._stopHttp()

    def _startHttp(self):
        callback = DuckHuntProWebCallback()
        callback._plugin = self
        httpserver.hook('duckhuntpro', callback)
        self._httpRunning = True

    def _stopHttp(self):
        if self._httpRunning:
            httpserver.unhook('duckhuntpro')
            self._httpRunning = False

    def _htmlPage(self, title, body):
        return (
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<title>%s</title></head><body><h1>%s</h1>%s</body></html>'
        ) % (html.escape(title), html.escape(title), body)

    def _renderWeb(self, path):
        parts = [urllib.parse.unquote(p) for p in path.split('/') if p]
        if not parts:
            return self._renderWebIndex()
        if len(parts) == 3:
            network, channel, page = parts
            if page == 'leaderboard':
                return self._renderWebLeaderboard(network, channel)
            if page == 'champions':
                return self._renderWebChampions(network, channel)
            if page == 'shop':
                return self._renderWebShop(network, channel)
        raise _WebNotFound()

    def _renderWebIndex(self):
        rows = []
        for network in self.db.networks():
            for cname in self.db.channels(network):
                netQ = urllib.parse.quote(network, safe='')
                chanQ = urllib.parse.quote(cname, safe='')
                rows.append(
                    '<li>%s %s -- <a href="/duckhuntpro/%s/%s/leaderboard">leaderboard</a>'
                    ' / <a href="/duckhuntpro/%s/%s/champions">champions</a>'
                    ' / <a href="/duckhuntpro/%s/%s/shop">shop</a></li>' % (
                        html.escape(network), html.escape(cname),
                        netQ, chanQ, netQ, chanQ, netQ, chanQ))
        body = '<ul>%s</ul>' % ''.join(rows) if rows else '<p>No games recorded yet.</p>'
        return self._htmlPage('DuckHuntPro', body)

    def _renderWebLeaderboard(self, network, channel):
        chan = self.db.getChannel(network, channel)
        if chan is None:
            raise _WebNotFound()
        players = self.db.topPlayers(network, channel, n=len(chan['players']))
        rows = []
        for i, p in enumerate(players, 1):
            rows.append(
                '<tr><td>%d</td><td>%s</td><td>%d</td><td>%d</td>'
                '<td>%d</td><td>%d</td></tr>' % (
                    i, html.escape(p['display_nick']), data.levelForXp(p['xp']),
                    p['xp'], p['stats']['killed'], p['stats']['golden_killed']))
        table = (
            '<table border="1" cellpadding="4"><tr><th>#</th><th>Nick</th>'
            '<th>Level</th><th>XP</th><th>Killed</th><th>Golden</th></tr>%s</table>'
        ) % (''.join(rows) if rows else '<tr><td colspan="6">No players yet.</td></tr>')
        title = 'DuckHuntPro leaderboard -- %s %s' % (network, channel)
        return self._htmlPage(title, table)

    def _renderWebChampions(self, network, channel):
        chan = self.db.getChannel(network, channel)
        if chan is None:
            raise _WebNotFound()
        archive = self.db.lastArchive(network, channel)
        if not archive:
            return self._htmlPage(
                'DuckHuntPro champions -- %s %s' % (network, channel),
                '<p>No quarterly reset has happened here yet.</p>')
        when = datetime.fromtimestamp(archive['archived_at']).strftime('%Y-%m-%d')
        rows = []
        for i, s in enumerate(archive['standings'], 1):
            rows.append('<tr><td>%d</td><td>%s</td><td>%d</td><td>%d</td></tr>' % (
                i, html.escape(s['nick']), s['xp'], s['killed']))
        table = (
            '<p>Season ending %s</p>'
            '<table border="1" cellpadding="4"><tr><th>#</th><th>Nick</th>'
            '<th>XP</th><th>Killed</th></tr>%s</table>'
        ) % (html.escape(when), ''.join(rows))
        title = 'DuckHuntPro champions -- %s %s' % (network, channel)
        return self._htmlPage(title, table)

    def _renderWebShop(self, network, channel):
        chan = self.db.getChannel(network, channel)
        if chan is None:
            raise _WebNotFound()
        title = 'DuckHuntPro shop -- %s %s' % (network, channel)
        return self._htmlPage(title, '<p>The shop economy is not implemented yet '
                                      '(planned for Phase 2).</p>')

    # -----------------------------------------------------------------
    # Quarterly stats reset
    # -----------------------------------------------------------------

    def _nextQuarterReset(self, now=None):
        """Timestamp of the next upcoming 1st-of-Jan/Apr/Jul/Oct at midnight,
        strictly after `now` (defaults to the real current time)."""
        now = now if now is not None else time.time()
        dt = datetime.fromtimestamp(now)
        for month in QUARTER_MONTHS:
            candidate = datetime(dt.year, month, 1)
            if candidate.timestamp() > now:
                return candidate.timestamp()
        return datetime(dt.year + 1, QUARTER_MONTHS[0], 1).timestamp()

    def _scheduleQuarterlyReset(self):
        at = self._nextQuarterReset()
        name = "DuckHuntPro:quarterlyreset:%r" % at
        self._scheduleEvent(name, at, self._fireQuarterlyReset, ())

    def _fireQuarterlyReset(self):
        for network in self.db.networks():
            irc = self._getIrc(network)
            for cname in self.db.channels(network):
                self.db.archiveAndReset(network, cname)
                if irc and cname in irc.state.channels and self.registryValue('enabled', cname):
                    lang = self.registryValue('language', cname)
                    irc.queueMsg(ircmsgs.privmsg(cname, messages.get(lang, 'quarterly_reset')))
        if self.registryValue('quarterlyResetEnabled'):
            self._scheduleQuarterlyReset()

    # -----------------------------------------------------------------
    # Scheduling helpers
    # -----------------------------------------------------------------

    def _scheduleEvent(self, name, at, func, args):
        try:
            schedule.addEvent(func, at, name=name, args=args)
            self._scheduled.add(name)
        except AssertionError:
            # Already scheduled (e.g. plugin reload) -- leave it alone.
            self._scheduled.add(name)

    def _unschedule(self, name):
        self._scheduled.discard(name)
        try:
            schedule.removeEvent(name)
        except KeyError:
            pass

    def _getIrc(self, network):
        irc = world.getIrc(network) if network else None
        if irc is None and world.ircs:
            irc = world.ircs[0]
        return irc

    # -----------------------------------------------------------------
    # Duck spawn planning (method 2: pre-planned daily flight times)
    # -----------------------------------------------------------------

    def _reschedulePlannedFlights(self, irc):
        """Restores spawn timers lost across a bot restart, and plans a
        fresh day for any enabled channel that has no future flights."""
        now = time.time()
        network = irc.network
        for cname in list(irc.state.channels.keys()):
            if not self.registryValue('enabled', cname):
                continue
            chan = self.db.channel(network, cname)
            with self.db.lock:
                previous = chan.get('planned_flights', [])
                future = [t for t in previous if t > now]
                chan['planned_flights'] = future
                previousPending = chan.get('fake_ducks_pending', [])
                futurePending = [e for e in previousPending if e['fires_at'] > now]
                chan['fake_ducks_pending'] = futurePending
            if future != previous or futurePending != previousPending:
                self.db.save()

            if future:
                for t in future:
                    name = "DuckHuntPro:flight:%s:%s:%r" % (network, cname, t)
                    self._scheduleEvent(name, t, self._fireSpawn, (network, cname))
            else:
                delay = self.registryValue('postInitDelay')
                name = "DuckHuntPro:plan:%s:%s" % (network, cname)
                self._scheduleEvent(name, now + delay, self._planDay, (network, cname))

            for entry in futurePending:
                name = "DuckHuntPro:special:%s:%s:%s:%r" % (
                    network, cname, entry['kind'], entry['fires_at'])
                self._scheduleEvent(name, entry['fires_at'], self._fireSpecialSpawn,
                                     (network, cname, entry['fires_at']))

            self._scheduleGunHandBack(network, cname)

    def doJoin(self, irc, msg):
        """When the bot itself joins a channel, kick off spawn planning if
        this channel is enabled and doesn't already have one scheduled."""
        if not ircutils.strEqual(msg.nick, irc.nick):
            return
        channel = msg.args[0]
        if not self.registryValue('enabled', channel):
            return
        network = irc.network
        chan = self.db.channel(network, channel)
        with self.db.lock:
            hasFuture = any(t > time.time() for t in chan.get('planned_flights', []))
        if not hasFuture:
            delay = self.registryValue('postInitDelay')
            name = "DuckHuntPro:plan:%s:%s" % (network, channel.lower())
            self._scheduleEvent(name, time.time() + delay, self._planDay, (network, channel))
        self._scheduleGunHandBack(network, channel)

    # -----------------------------------------------------------------
    # Nick-change stat fusion
    # -----------------------------------------------------------------

    def doNick(self, irc, msg):
        """Records a pending stat-transfer when a player renames. The
        actual merge is deferred to the renamed nick's next in-game action
        (_checkPendingRename), matching Duck_Hunt.tcl's deliberate delay
        "to reduce the risk of stat theft"."""
        oldNick = msg.nick
        newNick = msg.args[0]
        if ircutils.strEqual(oldNick, newNick):
            return
        network = irc.network
        for cname in list(irc.state.channels.keys()):
            if not self.registryValue('enabled', cname):
                continue
            if newNick not in irc.state.channels[cname].users:
                continue
            if not self.db.getPlayer(network, cname, oldNick):
                continue
            self.db.recordPendingTransfer(network, cname, oldNick, newNick)

    def doPart(self, irc, msg):
        channel = msg.args[0]
        if self.registryValue('enabled', channel):
            self.db.discardPendingTransfer(irc.network, channel, msg.nick)

    def doQuit(self, irc, msg):
        network = irc.network
        for cname in list(irc.state.channels.keys()):
            if self.registryValue('enabled', cname):
                self.db.discardPendingTransfer(network, cname, msg.nick)

    def _checkPendingRename(self, irc, channel, nick):
        network = irc.network
        entry = self.db.popPendingTransfer(network, channel, nick)
        if not entry:
            return
        oldNick = entry['old_nick']
        oldPlayer = self.db.getPlayer(network, channel, oldNick)
        if not oldPlayer:
            return
        lang = self.registryValue('language', channel)
        if self.registryValue('confiscationEnforcementOnFusion', channel):
            newPlayer = self.db.getPlayer(network, channel, nick)
            oldArmed = oldPlayer['gun_state'] == 'armed'
            newArmed = (not newPlayer) or newPlayer['gun_state'] == 'armed'
            if oldArmed and not newArmed:
                # Anti-confiscation-dodge: the disarmed new identity
                # doesn't get to inherit the old, still-armed one's stats.
                self.db.deletePlayer(network, channel, oldNick)
                return
            if not oldArmed and not newArmed:
                # Both disarmed: only the higher-xp profile survives.
                if newPlayer and newPlayer['xp'] >= oldPlayer['xp']:
                    self.db.deletePlayer(network, channel, oldNick)
                else:
                    self.db.deletePlayer(network, channel, nick)
                    self.db.renamePlayer(network, channel, oldNick, nick)
                return
        if self.db.mergeStats(network, channel, nick, oldNick):
            irc.queueMsg(ircmsgs.privmsg(channel, messages.get(
                lang, 'fusion_merged', old=oldNick, new=nick)))

    # -----------------------------------------------------------------
    # Antiflood
    # -----------------------------------------------------------------

    def _floodCheck(self, network, channel, nick):
        """Simplified from Duck_Hunt.tcl's 5 independent per-command
        thresholds plus 1 global one down to a single per-player, rolling
        60-second window shared across all commands -- full parity on
        every knob wasn't judged worth the complexity for what's meant to
        be a lightweight safety net, not a security boundary. Returns
        False if the action should be silently dropped."""
        if not self.registryValue('antifloodEnabled', channel):
            return True
        now = time.time()
        key = (network.lower(), channel.lower(), nick.lower())
        window = self._floodWindows.setdefault(key, [])
        cutoff = now - 60
        while window and window[0] < cutoff:
            window.pop(0)
        if len(window) >= self.registryValue('antifloodMaxPerMinute', channel):
            return False
        window.append(now)
        return True

    # -----------------------------------------------------------------
    # Weapon confiscation + auto-return
    # -----------------------------------------------------------------

    def _nextDailyTime(self, raw, now=None):
        """Timestamp of the next local HH:MM (from the config string `raw`,
        00:00 if it can't be parsed) strictly after `now`."""
        now = now if now is not None else time.time()
        try:
            hh, mm = (int(x) for x in raw.split(':', 1))
            datetime(2000, 1, 1, hh, mm)
        except (ValueError, AttributeError):
            hh, mm = 0, 0
        dt = datetime.fromtimestamp(now).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if dt.timestamp() <= now:
            dt = dt + timedelta(days=1)
        return dt.timestamp()

    def _nextHandBackTime(self, channelName, now=None):
        return self._nextDailyTime(
            self.registryValue('autoGunHandBackTime', channelName), now)

    # -----------------------------------------------------------------
    # Daily clip refill (Duck_Hunt.tcl refill_ammo / auto_refill_ammo_time)
    # -----------------------------------------------------------------

    def _scheduleAmmoRefill(self):
        at = self._nextDailyTime(self.registryValue('autoRefillAmmoTime'))
        self._scheduleEvent("DuckHuntPro:refill:%r" % at, at, self._fireAmmoRefill, ())

    def _fireAmmoRefill(self):
        self._refillAmmo()
        self._scheduleAmmoRefill()

    def _refillAmmo(self):
        """Every player's remaining clips go back to their level's count,
        discarding any extras, as the original does for all players on all
        channels. The clip currently in the gun is left alone, and players who
        haven't played yet (no ammo initialised) get a full set on first use."""
        changed = False
        with self.db.lock:
            for network in self.db.networks():
                for cname in self.db.channels(network):
                    for p in self.db.getChannel(network, cname)['players'].values():
                        if p['clips_left'] is None:
                            continue
                        count = data.LEVELS[data.levelForXp(p['xp'])].clip_count
                        if p['clips_left'] != count:
                            p['clips_left'] = count
                            changed = True
        if changed:
            self.db.save()
        return changed

    def _clampAmmo(self, player):
        """Duck_Hunt.tcl's recalculate_ammo_on_lvl_change: after xp drops,
        the clip in the gun and the clips left can't exceed what the
        (possibly lower) level allows."""
        lvl = data.LEVELS[data.levelForXp(player['xp'])]
        if player['clip_ammo'] is not None:
            player['clip_ammo'] = min(player['clip_ammo'], lvl.clip_size)
        if player['clips_left'] is not None:
            player['clips_left'] = min(player['clips_left'], lvl.clip_count)

    def _scheduleGunHandBack(self, network, channelName):
        if self.registryValue('gunHandBackMode', channelName) != 1:
            return
        at = self._nextHandBackTime(channelName)
        name = "DuckHuntPro:handback:%s:%s:%r" % (network, channelName.lower(), at)
        self._scheduleEvent(name, at, self._fireGunHandBack, (network, channelName))

    def _fireGunHandBack(self, network, channelName):
        self.db.handBackWeapons(network, channelName)
        if self.registryValue('gunHandBackMode', channelName) == 1:
            self._scheduleGunHandBack(network, channelName)

    def _maybeHandBackOnDuckGone(self, network, channelName):
        """Mode 2: temporarily-confiscated weapons return once the
        channel's whole "session" (every duck currently in flight, not
        just the one just resolved) has emptied out -- matches
        Duck_Hunt.tcl's gun_hand_back_mode==2, which is wired to the
        duck_sessions dict entry for that channel being fully unset, not
        to any single duck's resolution."""
        key = (network.lower(), channelName.lower())
        if self._activeDuck.get(key):
            return  # other ducks still in flight -- session isn't over
        if self.registryValue('gunHandBackMode', channelName) == 2:
            self.db.handBackWeapons(network, channelName)

    def _sleepHours(self, channelName):
        raw = self.registryValue('duckSleepHours', channelName)
        hours = set()
        for tok in raw.split():
            try:
                hours.add(int(tok))
            except ValueError:
                pass
        return hours

    def _planDay(self, network, channelName):
        """Pre-computes this channel's duck-flight times for the next 24h,
        matching the original script's method=2 (scheduled) spawning.

        Active bread adds extra flight slots (data.BREAD_EXTRA_DUCKS_PER_PIECE
        per piece), matching Duck_Hunt.tcl's plan_out_flights. Unlike the
        original, buying bread mid-day doesn't force an immediate replan of
        today's already-built schedule here -- the boost takes effect on the
        next time this channel's day gets (re)planned, which is how this
        self-rescheduling chain already refreshes on its own. Documented as
        a deliberate simplification, not an oversight."""
        chan = self.db.channel(network, channelName)
        breadCount = db.activeBreadCount(chan, time.time())
        n = self.registryValue('ducksPerDay', channelName) + breadCount * data.BREAD_EXTRA_DUCKS_PER_PIECE
        sleepHours = self._sleepHours(channelName)
        now = time.time()
        times = []
        attempts = 0
        while len(times) < n and attempts < n * 20:
            attempts += 1
            t = now + self._rng.uniform(0, 86400)
            if sleepHours and datetime.fromtimestamp(t).hour in sleepHours:
                continue
            times.append(t)
        times.sort()

        with self.db.lock:
            chan['planned_flights'] = times
        self.db.save()

        cname = channelName.lower()
        for t in times:
            name = "DuckHuntPro:flight:%s:%s:%r" % (network, cname, t)
            self._scheduleEvent(name, t, self._fireSpawn, (network, channelName))

        if times:
            name = "DuckHuntPro:plan:%s:%s" % (network, cname)
            self._scheduleEvent(name, times[-1] + 1, self._planDay, (network, channelName))

    def _fireSpawn(self, network, channelName):
        irc = self._getIrc(network)
        if irc is None:
            return
        if not self.registryValue('enabled', channelName):
            return
        if channelName not in irc.state.channels:
            return
        self._spawnDuck(irc, channelName)

    def _fireSpecialSpawn(self, network, channelName, firesAt):
        """Fires a decoy- or fake_duck-purchased spawn scheduled by
        `_scheduleSpecialSpawn`. Matches Duck_Hunt.tcl: spawning never
        checks whether a duck is already in flight -- multiple ducks can
        (and routinely do) coexist on the same channel."""
        chan = self.db.channel(network, channelName)
        with self.db.lock:
            entry = None
            remaining = []
            for e in chan.get('fake_ducks_pending', []):
                if entry is None and e['fires_at'] == firesAt:
                    entry = e
                else:
                    remaining.append(e)
            chan['fake_ducks_pending'] = remaining
        self.db.save()
        if entry is None:
            return
        irc = self._getIrc(network)
        if irc is None or channelName not in irc.state.channels:
            return
        if not self.registryValue('enabled', channelName):
            return
        self._spawnDuck(irc, channelName, forceNonGolden=entry['force_non_golden'],
                         isFake=(entry['kind'] == 'fake_duck'), buyer=entry.get('buyer'))

    def _scheduleSpecialSpawn(self, network, channelName, firesAt, kind, forceNonGolden, buyer):
        chan = self.db.channel(network, channelName)
        with self.db.lock:
            chan.setdefault('fake_ducks_pending', []).append({
                'fires_at': firesAt, 'kind': kind,
                'force_non_golden': forceNonGolden, 'buyer': buyer,
            })
        self.db.save()
        name = "DuckHuntPro:special:%s:%s:%s:%r" % (network, channelName.lower(), kind, firesAt)
        self._scheduleEvent(name, firesAt, self._fireSpecialSpawn, (network, channelName, firesAt))

    def _currentEscapeTime(self, network, channelName, now):
        base = self.registryValue('escapeTime', channelName)
        chan = self.db.channel(network, channelName)
        breadCount = db.activeBreadCount(chan, now)
        return base + breadCount * data.BREAD_ESCAPE_BONUS_PER_PIECE

    def _notifyDuckDetectors(self, irc, channelName):
        network = irc.network
        chan = self.db.getChannel(network, channelName)
        if not chan:
            return
        now = time.time()
        lang = self.registryValue('language', channelName)
        changed = False
        for player in list(chan['players'].values()):
            if db.itemActive(player, 'duck_detector', now):
                db.consumeItemUse(player, 'duck_detector')
                changed = True
                irc.queueMsg(ircmsgs.notice(player['display_nick'], messages.get(
                    lang, 'duck_detector_notice', channel=channelName)))
        if changed:
            self.db.save()

    def _spawnDuck(self, irc, channelName, forceNonGolden=False, isFake=False, buyer=None,
                    forceGolden=False):
        key = (irc.network.lower(), channelName.lower())
        ducksPerDay = max(1, self.registryValue('ducksPerDay', channelName))
        goldenPerDay = self.registryValue('approxGoldenDucksPerDay', channelName)
        if forceGolden:
            isGolden = True
        elif forceNonGolden:
            isGolden = False
        else:
            isGolden = self._rng.uniform(0, 100) < (100.0 * goldenPerDay / ducksPerDay)

        hpTotal = 1
        if isGolden:
            minHp = self.registryValue('goldenDuckMinHP', channelName)
            maxHp = self.registryValue('goldenDuckMaxHP', channelName)
            hpTotal = self._rng.randint(minHp, maxHp)

        now = time.time()
        self._activeDuck.setdefault(key, []).append({
            'spawned_at': now, 'is_golden': isGolden,
            'hp_total': hpTotal, 'hp_left': hpTotal, 'shots_fired': 0,
            'is_fake': isFake,
        })

        chan = self.db.channel(irc.network, channelName)
        with self.db.lock:
            chan['last_duck_at'] = now
        self.db.save()

        lang = self.registryValue('language', channelName)
        if self.registryValue('antiHighlight', channelName):
            art = data.randomDuckArt(self._rng)
            if isGolden:
                art += ' [GOLDEN]'
            irc.queueMsg(ircmsgs.privmsg(channelName, art))
        else:
            msgKey = 'golden_duck_flies' if isGolden else 'duck_flies'
            irc.queueMsg(ircmsgs.privmsg(channelName, messages.get(lang, msgKey)))
        self._notifyDuckDetectors(irc, channelName)

        escapeAt = now + self._currentEscapeTime(irc.network, channelName, now)
        name = "DuckHuntPro:escape:%s:%s:%r" % (irc.network, key[1], now)
        self._scheduleEvent(name, escapeAt, self._duckEscapes, (irc.network, channelName, now))

    def _duckEscapes(self, network, channelName, spawnedAt):
        # Removes the SPECIFIC duck whose own escape timer fired (matched
        # by spawned_at), not just "whichever duck is oldest" -- a
        # deliberate improvement over Duck_Hunt.tcl's terminate_duck_session,
        # which always operates on list-head regardless of which duck's
        # utimer actually fired. In the original this is harmless in
        # practice (escape deadlines are normally monotonic with spawn
        # order), but it's not identity-safe, and tracking identity costs
        # nothing here since every duck's spawned_at is already threaded
        # through its own scheduled event.
        duck = self._removeDuck(network, channelName, spawnedAt=spawnedAt)
        if duck is None:
            return  # already killed or fled
        irc = self._getIrc(network)
        if irc:
            lang = self.registryValue('language', channelName)
            irc.queueMsg(ircmsgs.privmsg(channelName, messages.get(lang, 'duck_escaped')))
        self._maybeHandBackOnDuckGone(network, channelName)

    def _removeDuck(self, network, channelName, spawnedAt=None):
        """Removes one duck from the channel's in-flight list and
        unschedules its escape timer. With no `spawnedAt`, removes the
        oldest (list head) -- the one `bang()`/accidents always target,
        matching Duck_Hunt.tcl's FIFO rule. Returns the removed duck dict,
        or None if there was nothing to remove (already gone)."""
        key = (network.lower(), channelName.lower())
        ducks = self._activeDuck.get(key)
        if not ducks:
            return None
        if spawnedAt is None:
            duck = ducks.pop(0)
        else:
            duck = None
            for i, d in enumerate(ducks):
                if d['spawned_at'] == spawnedAt:
                    duck = ducks.pop(i)
                    break
            if duck is None:
                return None
        if not ducks:
            del self._activeDuck[key]
        name = "DuckHuntPro:escape:%s:%s:%r" % (network, channelName.lower(), duck['spawned_at'])
        self._unschedule(name)
        return duck

    def _setVoice(self, irc, channel, nick, voice):
        try:
            if nick in irc.state.channels[channel].users:
                mode = '+v' if voice else '-v'
                irc.queueMsg(ircmsgs.mode(channel, (mode, nick)))
        except KeyError:
            pass

    def _ensureAmmo(self, player, lvl):
        if player['clip_ammo'] is None:
            player['clip_ammo'] = lvl.clip_size
            player['clips_left'] = lvl.clip_count

    def _formatDuration(self, seconds):
        seconds = int(seconds)
        if seconds < 60:
            return "%ds" % seconds
        minutes, seconds = divmod(seconds, 60)
        if minutes < 60:
            return "%dm%ds" % (minutes, seconds)
        hours, minutes = divmod(minutes, 60)
        return "%dh%dm" % (hours, minutes)

    def _ducksScaring(self, network, channel, player, now):
        """Ports Duck_Hunt.tcl's ducks_scaring: every gunshot that reaches
        this point (a miss always; a successful hit only if
        successfulShotsAlsoScareDucks is on) bumps EVERY duck currently in
        flight on this channel's scare counter by one -- not just the one
        that was aimed at. A duck whose counter reaches exactly
        shotsBeforeDuckFlee flees at once, except golden and fake/mechanical
        ducks, which are immune (but still counted). A silencer on the
        shooter's gun makes the shot unheard. Returns how many ducks fled;
        the caller words the announcement (m21-m24)."""
        key = (network.lower(), channel.lower())
        ducks = self._activeDuck.get(key)
        if not ducks or db.itemActive(player, 'silencer', now):
            return 0
        fleeAfter = self.registryValue('shotsBeforeDuckFlee', channel)
        fled = 0
        for duck in list(ducks):
            duck['shots_fired'] += 1
            if (duck['shots_fired'] == fleeAfter
                    and not duck['is_golden'] and not duck.get('is_fake', False)):
                self._removeDuck(network, channel, spawnedAt=duck['spawned_at'])
                fled += 1
        return fled

    # -----------------------------------------------------------------
    # Output (Duck_Hunt.tcl's display_output) and message helpers
    # -----------------------------------------------------------------

    def _lang(self, channel):
        return 'fr' if self.registryValue('language', channel) == 'fr' else 'en'

    def _t(self, channel, key, *args):
        """An original Duck Hunt message (m-key) in the channel's language."""
        return messages.tcl(self._lang(channel), key, *args)

    def _out(self, irc, channel, nick, text, kind='pref'):
        """Sends `text` (several lines if it contains newlines). kind
        'pref' follows preferredDisplayMode (1 = PRIVMSG to the channel,
        otherwise NOTICE to the player); 'public' is always the channel.
        Formatting is stripped when monochrome is on or the channel is +c."""
        mono = self.registryValue('monochrome', channel)
        if not mono:
            try:
                mono = 'c' in irc.state.channels[channel].modes
            except (KeyError, AttributeError):
                mono = False
        if mono:
            text = ircutils.stripFormatting(text)
        toChannel = kind == 'public' or (
            kind == 'pref' and self.registryValue('preferredDisplayMode', channel) == 1)
        for line in text.split('\n'):
            if line:
                irc.queueMsg(ircmsgs.privmsg(channel, line) if toChannel
                             else ircmsgs.notice(nick, line))

    def _kickIfOpped(self, irc, channel, nick, reason):
        """Kicks `nick`, or logs the original's m140 complaint if the bot has
        neither op nor halfop."""
        try:
            state = irc.state.channels[channel]
        except KeyError:
            return
        if state.isOp(irc.nick) or state.isHalfop(irc.nick):
            irc.queueMsg(ircmsgs.kick(channel, nick, reason))
        else:
            self.log.warning(messages.tcl('en', 'm140', 'DuckHuntPro', nick, channel))

    def _displayAmmo(self, player, lvl, channel):
        if self.registryValue('unlimitedAmmoPerClip', channel):
            return self._t(channel, 'm65')
        return '%s/%s' % (messages.colorizeValue(player['clip_ammo']), lvl.clip_size)

    def _displayClips(self, player, lvl, channel):
        if self.registryValue('unlimitedAmmoClips', channel):
            return self._t(channel, 'm65')
        return '%s/%s' % (messages.colorizeValue(player['clips_left']), lvl.clip_count)

    # -----------------------------------------------------------------
    # Commands
    # -----------------------------------------------------------------

    def bang(self, irc, msg, args, channel):
        """[<channel>]
        Shoots at the current duck.
        """
        network = irc.network
        self._checkPendingRename(irc, channel, msg.nick)
        if not self._floodCheck(network, channel, msg.nick):
            irc.reply(messages.get(self.registryValue('language', channel),
                                   'antiflood_blocked', nick=msg.nick))
            return
        player = self.db.player(network, channel, msg.nick)
        try:
            self._shoot(irc, msg.nick, channel, network, player)
        finally:
            self._clampAmmo(player)
            self.db.save()
    bang = wrap(bang, ['channel'])

    def _shoot(self, irc, nick, channel, network, player):
        """Port of Duck_Hunt.tcl's shoot, step for step: the order of the
        checks (not armed, water bucket, sand/grease/sabotage/liability,
        jammed, new jam roll, empty clip, infrared, ammo, dazzle/sight) and
        what each one consumes matches the original."""
        key = (network.lower(), channel.lower())
        now = time.time()
        stats = player['stats']
        t = lambda k, *a: self._t(channel, k, *a)
        out = lambda text, kind='pref': self._out(irc, channel, nick, text, kind)

        ducks = self._activeDuck.get(key)
        duckPresent = bool(ducks)
        numDucks = len(ducks) if ducks else 0
        if duckPresent:
            stats['reflex_ms'] += int((now - ducks[0]['spawned_at']) * 1000)
        player['last_activity'] = now
        lvl = data.LEVELS[data.levelForXp(player['xp'])]
        self._ensureAmmo(player, lvl)

        if player['gun_state'] != 'armed':
            out(t('m5', nick))
            return
        bucket = db.itemActive(player, 'water_bucket', now)
        if bucket:
            out(t('m332', nick, bucket.get('value') or '?', messages.adaptTimeResolution(
                (bucket['expires_at'] - now) * 1000, False, self._lang(channel))))
            return

        xpAccident = lvl.xp_accident
        jam = lvl.jam_pct
        sandMsg = sabotageMsg = dazzleMsg = liabilityMsg = ''
        sand = db.itemActive(player, 'sand', now)
        if sand:
            jam *= 2
            db.removeItem(player, 'sand')
            sandMsg = t('m333', sand.get('value') or '?')
        if db.itemActive(player, 'grease', now):
            jam = int(jam / 2)
        sabotage = db.itemActive(player, 'sabotage', now)
        if sabotage:
            db.removeItem(player, 'sabotage')
            sabotageMsg = t('m337', sabotage.get('value') or '?')
        if db.itemActive(player, 'liability_insurance', now):
            xpAccident = xpAccident // 3      # Tcl's int(x / 3) floors negatives
            liabilityMsg = t('m343')

        if player['jammed']:
            out(t('m7', nick))
            return
        if sabotage or self._rng.uniform(0, 100) < jam:
            player['jammed'] = True
            stats['jams'] += 1
            out(t('m8', nick, self._displayAmmo(player, lvl, channel),
                  self._displayClips(player, lvl, channel)) + sabotageMsg + sandMsg)
            if sabotage and self.registryValue('kickWhenSabotaged', channel):
                self._kickIfOpped(irc, channel, nick, t('m338', sabotage.get('value') or '?'))
            return

        unlimitedClip = self.registryValue('unlimitedAmmoPerClip', channel)
        if player['clip_ammo'] <= 0 and not unlimitedClip:
            stats['empty_shots'] += 1
            out(t('m6', nick, self._displayAmmo(player, lvl, channel),
                  self._displayClips(player, lvl, channel)))
            return
        if not duckPresent and db.itemActive(player, 'infrared_detector', now):
            out(t('m290', nick))
            db.consumeItemUse(player, 'infrared_detector')
            return
        if not unlimitedClip:
            player['clip_ammo'] -= 1

        accuracy = lvl.accuracy
        mirror = db.itemActive(player, 'mirror_dazzle', now)
        if mirror:
            accuracy = int(accuracy / 2)
            db.removeItem(player, 'mirror_dazzle')
            dazzleMsg = t('m334', mirror.get('value') or '?')
        if db.itemActive(player, 'sight', now):
            accuracy += int((100 - lvl.accuracy) / 3)
            db.removeItem(player, 'sight')

        fled = 0
        if not duckPresent or self._rng.uniform(0, 100) >= accuracy:
            fled = self._shotMissed(irc, channel, network, nick, player, lvl, duckPresent,
                                    xpAccident, dazzleMsg, liabilityMsg, now)
        else:
            damage = data.NORMAL_DAMAGE
            for ammoKey, dmg in data.AMMO_TYPE_DAMAGE.items():
                if db.itemActive(player, ammoKey, now):
                    damage = dmg
                    break
            self._resolveDuckHit(irc, channel, network, nick,
                                 self.registryValue('language', channel), damage)
            numDucks -= 1       # (even for a golden duck that only got hurt,
            #                     as in the original)
            if self.registryValue('successfulShotsAlsoScareDucks', channel):
                fled += self._ducksScaring(network, channel, player, now)

        if fled > 1:
            out(t('m21') if fled == numDucks else t('m22', fled), 'public')
        elif fled == 1:
            out(t('m23') if numDucks == 1 else t('m24'), 'public')

    def _shotMissed(self, irc, channel, network, nick, player, lvl, duckPresent,
                    xpAccident, dazzleMsg, liabilityMsg, now):
        """The miss/wild-fire half of Duck_Hunt.tcl's shoot: xp penalties,
        scaring the ducks, the hunting-accident ricochet chain, wild-fire
        confiscation and the demotion notice. Returns how many ducks the
        noise scared off."""
        stats = player['stats']
        t = lambda k, *a: self._t(channel, k, *a)
        out = lambda text, kind='pref': self._out(irc, channel, nick, text, kind)
        key = (network.lower(), channel.lower())
        xpMiss, xpWild = lvl.xp_missed_shot, lvl.xp_wild_shot

        stats['missed'] += 1
        previousXp = player['xp']
        player['xp'] += xpMiss
        if self.registryValue('devoiceOnMiss', channel):
            self._setVoice(irc, channel, nick, False)
        fled = 0
        wildMsg = ''
        if duckPresent:
            fled = self._ducksScaring(network, channel, player, now)
        else:
            wildMsg = t('m9', xpWild)

        try:
            population = len(irc.state.channels[channel].users)
        except KeyError:
            population = 1
        chance = data.accidentChance(population, duckPresent)
        someoneHit = confiscationSent = penaltySent = False
        ricochets = 0
        source = nick
        while self._rng.uniform(0, 100) < chance and ricochets < data.MAX_RICOCHETS:
            victim = self._pickAccidentVictim(irc, channel, network, source)
            if victim is None:
                break
            someoneHit = True
            source = victim
            self._checkPendingRename(irc, channel, victim)
            stats['humans_shot'] += 1
            if self.registryValue('devoiceOnAccident', channel):
                self._setVoice(irc, channel, nick, False)
            player['xp'] += xpAccident
            victimPlayer = self.db.player(network, channel, victim)
            victimPlayer['stats']['bullets_received'] += 1

            conf1 = conf2 = ''
            if (self.registryValue('gunConfiscationWhenShootingSomeone', channel)
                    and not confiscationSent):
                player['gun_state'] = 'confiscated'
                stats['confiscations'] += 1
                conf1, conf2 = t('m10'), t('m11')
            if not penaltySent:
                if duckPresent:
                    penaltyMsg = t('m12', xpMiss)
                    lostXp = abs(xpMiss) + abs(xpAccident)
                else:
                    penaltyMsg = t('m12', xpMiss) + wildMsg
                    lostXp = abs(xpMiss) + abs(xpWild) + abs(xpAccident)
            else:
                penaltyMsg = ''
                lostXp = abs(xpAccident)

            lifeMsg = lifeMsg2 = ''
            if db.itemActive(victimPlayer, 'life_insurance', now):
                db.consumeItemUse(victimPlayer, 'life_insurance')
                bonus = data.LIFE_INSURANCE_LEVEL_MULTIPLIER * data.levelForXp(victimPlayer['xp'])
                victimPlayer['xp'] += bonus
                lifeMsg, lifeMsg2 = t('m340', bonus, victim), t('m341', bonus)
            victimLvl = data.LEVELS[data.levelForXp(victimPlayer['xp'])]
            tail = conf1 + dazzleMsg + liabilityMsg + lifeMsg

            if self._rng.uniform(0, 100) < victimLvl.deflection:
                victimPlayer['stats']['deflected'] += 1
                ricochets += 1
                confiscationSent = penaltySent = True
                out(t('m13', nick, victim, victimLvl.deflection, penaltyMsg, xpAccident)
                    + tail, 'public')
                if (duckPresent and self._activeDuck.get(key)
                        and self._rng.uniform(0, 100) < data.CHANCE_RICOCHET_TOWARDS_DUCK):
                    damage = data.NORMAL_DAMAGE
                    for ammoKey, dmg in data.AMMO_TYPE_DAMAGE.items():
                        if db.itemActive(player, ammoKey, now):
                            damage = dmg
                            break
                    self._resolveDuckHit(irc, channel, network, nick,
                                         self.registryValue('language', channel),
                                         damage, isLucky=True)
                    break
            elif self._rng.uniform(0, 100) < victimLvl.defense:
                victimPlayer['stats']['absorbed'] += 1
                confiscationSent = penaltySent = True
                out(t('m14', victim, nick, victimLvl.defense, penaltyMsg, xpAccident)
                    + tail, 'public')
                break
            else:
                victimPlayer['stats']['deaths'] += 1
                confiscationSent = penaltySent = True
                if self.registryValue('kickWhenShot', channel):
                    self._kickIfOpped(irc, channel, victim,
                                      t('m15', nick, lostXp) + conf2 + lifeMsg2)
                out(t('m16', victim, nick, penaltyMsg, xpAccident) + tail, 'public')
                break

        if not duckPresent:
            stats['wild_shots'] += 1
            player['xp'] += xpWild
            if self.registryValue('devoiceOnWildFire', channel):
                self._setVoice(irc, channel, nick, False)
            confiscationMsg = ''
            if (self.registryValue('gunConfiscationOnWildFire', channel)
                    and player['gun_state'] == 'armed'):
                player['gun_state'] = 'confiscated'
                stats['confiscations'] += 1
                confiscationMsg = t('m17')
            if not someoneHit:
                out(t('m18', nick, xpMiss, xpWild) + confiscationMsg)
        elif not someoneHit:
            out(t('m19', nick, xpMiss) + dazzleMsg)
        if not duckPresent and self.registryValue('kickOnWildFire', channel):
            self._kickIfOpped(irc, channel, nick, t('m20', xpMiss, xpWild))
        newLevel = data.levelForXp(player['xp'])
        if data.levelForXp(previousXp) > newLevel:
            out(t('m2', nick, newLevel, messages.lvl2rank(newLevel, self._lang(channel))),
                'public')
        return fled

    def _resolveDuckHit(self, irc, channel, network, shooterNick, lang, damage, isLucky=False):
        """Resolves a confirmed hit on the channel's current duck: a
        partial hit on a multi-hp (golden) duck, or a full kill (xp gain,
        clover bonus, drop table, leveling, voice, mode-2 gun hand-back).
        Shared by bang()'s direct-hit path and _resolveAccident()'s
        ricochet-into-duck ("lucky shot") path."""
        key = (network.lower(), channel.lower())
        ducks = self._activeDuck.get(key)
        if not ducks:
            return
        duck = ducks[0]  # oldest -- always the target, see bang()
        player = self.db.player(network, channel, shooterNick)
        duck['hp_left'] -= damage
        if duck['hp_left'] > 0:
            self.db.save()
            irc.reply(messages.get(lang, 'kill_golden_hit', nick=shooterNick, hp=duck['hp_left']))
            return

        now = time.time()
        elapsed = now - duck['spawned_at']
        isFake = duck.get('is_fake', False)
        xpGain = 0 if isFake else (
            data.BASE_XP_GOLDEN_DUCK * duck['hp_total'] if duck['is_golden'] else data.XP_PER_DUCK)
        if isLucky:
            xpGain += data.XP_LUCKY_SHOT
        clover = db.itemActive(player, 'four_leaf_clover', now)
        if clover:
            # Preserves a Duck_Hunt.tcl quirk: the clover bonus-add isn't
            # gated on is_fake_duck in the original, so it applies even to
            # an otherwise-zero-xp fake duck kill. Kept for full parity.
            xpGain += clover.get('value') or 0
        oldLevel = data.levelForXp(player['xp'])
        player['xp'] += xpGain
        newLevel = data.levelForXp(player['xp'])
        st = player['stats']
        st['killed'] += 1
        if duck['is_golden']:
            st['golden_killed'] += 1
        ms = int(elapsed * 1000)
        st['total_time_ms'] += ms
        st['timed_shots'] += 1
        if st['best_time_ms'] is None or ms < st['best_time_ms']:
            st['best_time_ms'] = ms
        self._removeDuck(network, channel)

        dropMsg = None
        if self.registryValue('dropsEnabled', channel):
            dropMsg = self._rollAndApplyDrop(player, lang, now)

        self.db.save()

        if isLucky:
            irc.queueMsg(ircmsgs.privmsg(channel, messages.get(
                lang, 'kill_lucky', nick=shooterNick, ricochets=1, xp=xpGain, level=newLevel)))
        else:
            msgKey = 'kill_golden_final' if duck['is_golden'] else 'kill'
            irc.queueMsg(ircmsgs.privmsg(channel, messages.get(
                lang, msgKey, nick=shooterNick, elapsed=elapsed, xp=xpGain, level=newLevel)))
        if dropMsg:
            irc.queueMsg(ircmsgs.privmsg(channel, dropMsg))
        if newLevel > oldLevel:
            irc.queueMsg(ircmsgs.privmsg(channel, messages.get(
                lang, 'level_up', nick=shooterNick, level=newLevel)))
        if self.registryValue('voiceWhenDuckShot', channel):
            self._setVoice(irc, channel, shooterNick, True)
        self._maybeHandBackOnDuckGone(network, channel)

    def _pickAccidentVictim(self, irc, channel, network, excludeNick):
        """Duck_Hunt.tcl's random_user: a random channel occupant other than
        the bot and `excludeNick` (the current shooter, or the previous
        victim after a ricochet). With onlyHuntersCanBeShot, only players
        who have shot a duck or missed at least once qualify."""
        try:
            users = list(irc.state.channels[channel].users)
        except KeyError:
            return None
        candidates = [u for u in users if not ircutils.strEqual(u, irc.nick)
                      and not ircutils.strEqual(u, excludeNick)]
        if self.registryValue('onlyHuntersCanBeShot', channel):
            chan = self.db.getChannel(network, channel)
            hunters = set()
            if chan:
                hunters = {k for k, p in chan['players'].items()
                           if p['stats']['killed'] + p['stats']['missed'] > 0}
            candidates = [u for u in candidates if u.lower() in hunters]
        if not candidates:
            return None
        return candidates[self._rng.randint(0, len(candidates) - 1)]

    def _rollAndApplyDrop(self, player, lang, now):
        """Rolls the kill drop table and applies the winning drop (or
        returns None on a dry roll, the much more common case)."""
        key = data.rollDrop(self._rng)
        if key is None:
            return None
        if key == 'junk':
            idx = self._rng.randint(0, len(messages.JUNK_FLAVORS) - 1)
            return messages.get(lang, 'drop_junk', nick=player['display_nick'],
                                 junk=messages.JUNK_FLAVORS[idx])
        if key in data.XP_BOOK_VALUES:
            xp = data.XP_BOOK_VALUES[key]
            player['xp'] += xp
            return messages.get(lang, 'drop_xp_book', nick=player['display_nick'], xp=xp)
        if key in ('ammo', 'clip'):
            lvl = data.LEVELS[data.levelForXp(player['xp'])]
            self._ensureAmmo(player, lvl)
            if key == 'ammo':
                player['clip_ammo'] = min(lvl.clip_size, player['clip_ammo'] + 1)
            else:
                player['clips_left'] = min(lvl.clip_count, player['clips_left'] + 1)
            return messages.get(lang, 'drop_item', nick=player['display_nick'], item=key)
        if key in data.AMMO_TYPE_DAMAGE:
            other = 'explosive_ammo' if key == 'ap_ammo' else 'ap_ammo'
            db.removeItem(player, other)
        meta = data.ITEM_META.get(key)
        value = None
        if key == 'four_leaf_clover':
            value = self._rng.randint(data.CLOVER_BONUS_MIN, data.CLOVER_BONUS_MAX)
        if meta:
            db.giveItem(player, key, now, duration=meta['duration'], uses=meta['uses'], value=value)
        return messages.get(lang, 'drop_item', nick=player['display_nick'], item=key)

    def duckreload(self, irc, msg, args, channel):
        """[<channel>]
        Reloads your weapon (or clears a jam).
        """
        network = irc.network
        lang = self.registryValue('language', channel)
        self._checkPendingRename(irc, channel, msg.nick)
        player = self.db.player(network, channel, msg.nick)
        lvl = data.LEVELS[data.levelForXp(player['xp'])]

        if player['gun_state'] in ('confiscated', 'confiscated_permanent'):
            irc.reply(messages.get(lang, 'gun_not_armed', nick=msg.nick))
            return

        self._ensureAmmo(player, lvl)

        if player['jammed']:
            player['jammed'] = False
            self.db.save()
            irc.reply(messages.get(lang, 'reload_ok', nick=msg.nick))
            return

        if player['clip_ammo'] >= lvl.clip_size:
            irc.reply(messages.get(lang, 'reload_full', nick=msg.nick))
            return

        unlimitedClips = self.registryValue('unlimitedAmmoClips', channel)
        if player['clips_left'] <= 0 and not unlimitedClips:
            irc.reply(messages.get(lang, 'no_clips_left', nick=msg.nick))
            return

        player['clip_ammo'] = lvl.clip_size
        if not unlimitedClips:
            player['clips_left'] -= 1
        self.db.save()
        irc.reply(messages.get(lang, 'reload_ok', nick=msg.nick))
    duckreload = wrap(duckreload, ['channel'])

    def duckstats(self, irc, msg, args, channel, nick):
        """[<channel>] [<nick>]
        Shows hunting stats for you, or for <nick>.
        """
        target = nick or msg.nick
        lang = self.registryValue('language', channel)
        self._checkPendingRename(irc, channel, target)
        player = self.db.getPlayer(irc.network, channel, target)
        if not player:
            irc.reply("%s hasn't played DuckHuntPro here yet." % target)
            return
        level = data.levelForXp(player['xp'])
        st = player['stats']
        bestTime = "%.2fs" % (st['best_time_ms'] / 1000.0) if st['best_time_ms'] is not None else "n/a"
        gunState = 'jammed' if player['jammed'] else player['gun_state']
        irc.reply(messages.get(lang, 'duckstats_header', nick=player['display_nick'],
                                level=level, xp=player['xp']))
        irc.reply(messages.get(lang, 'duckstats_line', killed=st['killed'],
                                golden=st['golden_killed'], missed=st['missed'],
                                jams=st['jams'], best_time=bestTime, gun_state=gunState))
    duckstats = wrap(duckstats, ['channel', optional('nick')])

    def duckshooters(self, irc, msg, args, channel):
        """[<channel>]
        Shows the top shooters (ranked by xp, kills as tiebreaker) on this
        channel's current season. How many is set by topShootersCount.
        """
        lang = self.registryValue('language', channel)
        count = self.registryValue('topShootersCount', channel)
        top = self.db.topPlayers(irc.network, channel, n=count)
        if not top:
            irc.reply(messages.get(lang, 'shooters_empty'))
            return
        irc.reply(messages.get(lang, 'shooters_header'))
        for i, p in enumerate(top, 1):
            irc.reply(messages.get(lang, 'shooters_line', rank=i, nick=p['display_nick'],
                                    level=data.levelForXp(p['xp']), xp=p['xp'],
                                    killed=p['stats']['killed']))
    duckshooters = wrap(duckshooters, ['channel'])

    def duckchampions(self, irc, msg, args, channel):
        """[<channel>]
        Shows the top 3 shooters from this channel's most recent
        quarterly reset.
        """
        lang = self.registryValue('language', channel)
        archive = self.db.lastArchive(irc.network, channel)
        if not archive or not archive['standings']:
            irc.reply(messages.get(lang, 'champions_empty'))
            return
        when = datetime.fromtimestamp(archive['archived_at']).strftime('%Y-%m-%d')
        irc.reply(messages.get(lang, 'champions_header', when=when))
        for i, s in enumerate(archive['standings'][:3], 1):
            irc.reply(messages.get(lang, 'champions_line', rank=i, nick=s['nick'],
                                    xp=s['xp'], killed=s['killed']))
    duckchampions = wrap(duckchampions, ['channel'])

    def lastduck(self, irc, msg, args, channel):
        """[<channel>]
        Shows how long ago the last duck flew on this channel.
        """
        lang = self.registryValue('language', channel)
        chan = self.db.getChannel(irc.network, channel)
        lastAt = chan.get('last_duck_at') if chan else None
        if not lastAt:
            irc.reply(messages.get(lang, 'lastduck_never'))
            return
        elapsed = time.time() - lastAt
        irc.reply(messages.get(lang, 'lastduck', elapsed=self._formatDuration(elapsed)))
    lastduck = wrap(lastduck, ['channel'])

    # -----------------------------------------------------------------
    # Shop
    # -----------------------------------------------------------------

    class shop(callbacks.Commands):
        """Buy items with your xp -- see `shop list` for the catalog."""

        plugin = None

        def list(self, irc, msg, args, channel):
            """[<channel>]
            Lists everything for sale.
            """
            lines = ['%s (%d xp): %s' % (key, cost, data.ITEM_DESCRIPTIONS.get(key, ''))
                      for key, cost in data.ITEM_COSTS.items()]
            irc.reply(' | '.join(lines))
        list = wrap(list, ['channel'])

        def buy(self, irc, msg, args, channel, item, target):
            """<item> [<target>] [<channel>]
            Buys <item> from the shop, spending your xp. mirror/sand/
            water_bucket/sabotage need a <target> player.
            """
            self.plugin._buy(irc, msg, channel, item, target)
        buy = wrap(buy, ['channel', 'somethingWithoutSpaces', optional('somethingWithoutSpaces')])

    def _buy(self, irc, msg, channel, item, target):
        network = irc.network
        nick = msg.nick
        lang = self.registryValue('language', channel)
        self._checkPendingRename(irc, channel, nick)
        if not self._floodCheck(network, channel, nick):
            irc.reply(messages.get(lang, 'antiflood_blocked', nick=nick))
            return
        item = item.lower()
        if item not in data.ITEM_COSTS:
            irc.reply(messages.get(lang, 'shop_unknown_item', item=item))
            return
        player = self.db.player(network, channel, nick)
        if player['gun_state'] in ('confiscated', 'confiscated_permanent') and item != 'buyback_weapon':
            # buyback_weapon is the one item that's exempt from this gate --
            # it's the only way out of the confiscated state. A permanently
            # confiscated weapon still can't be bought back via the shop,
            # though -- see _buyBuyback.
            irc.reply(messages.get(lang, 'shop_gun_confiscated', nick=nick))
            return
        cost = data.ITEM_COSTS[item]
        floor = self.registryValue('minXpForShopping', channel)
        if player['xp'] - cost < floor:
            irc.reply(messages.get(lang, 'shop_not_rich_enough', floor=floor))
            return

        now = time.time()
        handler = self._shopHandlers[item]
        ok, reply = handler(irc, channel, player, target, lang, now)
        if not ok:
            if reply:
                irc.reply(reply)
            return

        oldLevel = data.levelForXp(player['xp'])
        player['xp'] -= cost
        self._clampAmmo(player)
        newLevel = data.levelForXp(player['xp'])
        self.db.save()
        irc.reply(reply or messages.get(lang, 'shop_bought', nick=nick, item=item, cost=cost))
        if newLevel < oldLevel:
            irc.queueMsg(ircmsgs.privmsg(channel, messages.get(
                lang, 'level_down', nick=nick, level=newLevel)))

    def _alreadyHaveMsg(self, player, key, lang, now):
        item = player['items'].get(key)
        remaining = (self._formatDuration(item['expires_at'] - now)
                     if item and item.get('expires_at') else 'a while')
        return messages.get(lang, 'shop_already_have', nick=player['display_nick'],
                             item='%s (%s left)' % (key, remaining))

    def _resolveTarget(self, irc, channel, network, target, lang, buyerNick):
        if not target:
            return None, messages.get(lang, 'shop_target_required')
        if ircutils.strEqual(target, buyerNick):
            return None, messages.get(lang, 'shop_target_self')
        if target not in irc.state.channels[channel].users:
            return None, messages.get(lang, 'shop_target_offline', target=target)
        targetPlayer = self.db.getPlayer(network, channel, target)
        if not targetPlayer:
            return None, messages.get(lang, 'shop_target_unknown', target=target)
        return targetPlayer, None

    # --- item purchase handlers: each returns (ok, message_or_None). A
    # False `ok` means the buyer isn't charged; the returned message (if
    # any) is the failure reason. A True `ok` means _buy() deducts the
    # item's cost regardless of whether the handler's own message
    # describes a success or a "paid but no effect" outcome (grease
    # absorbing sand, sunglasses blocking a mirror) -- matching
    # Duck_Hunt.tcl, which always charges once the purchase is validated.

    def _buyExtraAmmo(self, irc, channel, player, target, lang, now):
        lvl = data.LEVELS[data.levelForXp(player['xp'])]
        self._ensureAmmo(player, lvl)
        if player['clip_ammo'] >= lvl.clip_size:
            return False, messages.get(lang, 'clip_already_full', nick=player['display_nick'])
        player['clip_ammo'] += 1
        return True, None

    def _buyExtraClip(self, irc, channel, player, target, lang, now):
        lvl = data.LEVELS[data.levelForXp(player['xp'])]
        self._ensureAmmo(player, lvl)
        if player['clips_left'] >= lvl.clip_count:
            return False, messages.get(lang, 'clips_already_full', nick=player['display_nick'])
        player['clips_left'] += 1
        return True, None

    def _buyAmmoType(self, player, key, otherKey, lang, now):
        if db.itemActive(player, key, now):
            return False, self._alreadyHaveMsg(player, key, lang, now)
        db.removeItem(player, otherKey)
        meta = data.ITEM_META[key]
        db.giveItem(player, key, now, duration=meta['duration'], uses=meta['uses'])
        return True, None

    def _buyApAmmo(self, irc, channel, player, target, lang, now):
        return self._buyAmmoType(player, 'ap_ammo', 'explosive_ammo', lang, now)

    def _buyExplosiveAmmo(self, irc, channel, player, target, lang, now):
        return self._buyAmmoType(player, 'explosive_ammo', 'ap_ammo', lang, now)

    def _buyBuyback(self, irc, channel, player, target, lang, now):
        if player['gun_state'] == 'confiscated_permanent':
            return False, messages.get(lang, 'buyback_permanent', nick=player['display_nick'])
        if player['gun_state'] != 'confiscated':
            return False, messages.get(lang, 'buyback_not_confiscated', nick=player['display_nick'])
        player['gun_state'] = 'armed'
        return True, messages.get(lang, 'buyback_ok', nick=player['display_nick'])

    def _buyGrease(self, irc, channel, player, target, lang, now):
        if db.itemActive(player, 'grease', now):
            return False, self._alreadyHaveMsg(player, 'grease', lang, now)
        meta = data.ITEM_META['grease']
        db.giveItem(player, 'grease', now, duration=meta['duration'], uses=meta['uses'])
        return True, None

    def _buySight(self, irc, channel, player, target, lang, now):
        if db.itemActive(player, 'sight', now):
            return False, self._alreadyHaveMsg(player, 'sight', lang, now)
        meta = data.ITEM_META['sight']
        db.giveItem(player, 'sight', now, duration=meta['duration'], uses=meta['uses'])
        return True, messages.get(lang, 'sight_ok', nick=player['display_nick'])

    def _buyInfrared(self, irc, channel, player, target, lang, now):
        if db.itemActive(player, 'infrared_detector', now):
            return False, self._alreadyHaveMsg(player, 'infrared_detector', lang, now)
        meta = data.ITEM_META['infrared_detector']
        db.giveItem(player, 'infrared_detector', now, duration=meta['duration'], uses=meta['uses'])
        return True, None

    def _buySilencer(self, irc, channel, player, target, lang, now):
        if db.itemActive(player, 'silencer', now):
            return False, self._alreadyHaveMsg(player, 'silencer', lang, now)
        meta = data.ITEM_META['silencer']
        db.giveItem(player, 'silencer', now, duration=meta['duration'], uses=meta['uses'])
        return True, None

    def _buyClover(self, irc, channel, player, target, lang, now):
        if db.itemActive(player, 'four_leaf_clover', now):
            return False, self._alreadyHaveMsg(player, 'four_leaf_clover', lang, now)
        bonus = self._rng.randint(data.CLOVER_BONUS_MIN, data.CLOVER_BONUS_MAX)
        meta = data.ITEM_META['four_leaf_clover']
        db.giveItem(player, 'four_leaf_clover', now, duration=meta['duration'],
                    uses=meta['uses'], value=bonus)
        return True, None

    def _buySunglasses(self, irc, channel, player, target, lang, now):
        if db.itemActive(player, 'sunglasses', now):
            return False, self._alreadyHaveMsg(player, 'sunglasses', lang, now)
        meta = data.ITEM_META['sunglasses']
        db.giveItem(player, 'sunglasses', now, duration=meta['duration'], uses=meta['uses'])
        return True, None

    def _buySpareClothes(self, irc, channel, player, target, lang, now):
        if not db.itemActive(player, 'water_bucket', now):
            return False, messages.get(lang, 'spare_clothes_noop', nick=player['display_nick'])
        db.removeItem(player, 'water_bucket')
        return True, messages.get(lang, 'spare_clothes_ok', nick=player['display_nick'])

    def _buyBrush(self, irc, channel, player, target, lang, now):
        had = False
        if db.itemActive(player, 'sand', now):
            db.removeItem(player, 'sand')
            had = True
        if db.itemActive(player, 'sabotage', now):
            db.removeItem(player, 'sabotage')
            had = True
        if not had:
            return False, messages.get(lang, 'brush_noop', nick=player['display_nick'])
        return True, messages.get(lang, 'brush_ok', nick=player['display_nick'])

    def _buyMirror(self, irc, channel, player, target, lang, now):
        network = irc.network
        targetPlayer, err = self._resolveTarget(irc, channel, network, target, lang,
                                                 player['display_nick'])
        if err:
            return False, err
        if db.itemActive(targetPlayer, 'mirror_dazzle', now):
            return False, messages.get(lang, 'shop_already_have', nick=player['display_nick'],
                                        item='mirror on %s' % targetPlayer['display_nick'])
        if db.itemActive(targetPlayer, 'sunglasses', now):
            return True, messages.get(lang, 'mirror_no_effect_sunglasses',
                                       nick=player['display_nick'], target=targetPlayer['display_nick'])
        db.giveItem(targetPlayer, 'mirror_dazzle', now, duration=None, uses=1,
                    value=player['display_nick'])
        return True, messages.get(lang, 'mirror_ok', nick=player['display_nick'],
                                   target=targetPlayer['display_nick'])

    def _buySand(self, irc, channel, player, target, lang, now):
        network = irc.network
        targetPlayer, err = self._resolveTarget(irc, channel, network, target, lang,
                                                 player['display_nick'])
        if err:
            return False, err
        if targetPlayer['gun_state'] != 'armed':
            return False, messages.get(lang, 'sand_no_gun', target=targetPlayer['display_nick'])
        if db.itemActive(targetPlayer, 'sand', now):
            return False, messages.get(lang, 'shop_already_have', nick=player['display_nick'],
                                        item='sand on %s' % targetPlayer['display_nick'])
        if db.itemActive(targetPlayer, 'grease', now):
            db.removeItem(targetPlayer, 'grease')
            return True, messages.get(lang, 'sand_absorbed_by_grease', nick=player['display_nick'],
                                       target=targetPlayer['display_nick'])
        db.giveItem(targetPlayer, 'sand', now, duration=None, uses=1, value=player['display_nick'])
        return True, messages.get(lang, 'sand_ok', nick=player['display_nick'],
                                   target=targetPlayer['display_nick'])

    def _buyWaterBucket(self, irc, channel, player, target, lang, now):
        network = irc.network
        targetPlayer, err = self._resolveTarget(irc, channel, network, target, lang,
                                                 player['display_nick'])
        if err:
            return False, err
        if db.itemActive(targetPlayer, 'water_bucket', now):
            return False, messages.get(lang, 'shop_already_have', nick=player['display_nick'],
                                        item='water_bucket on %s' % targetPlayer['display_nick'])
        db.giveItem(targetPlayer, 'water_bucket', now, duration=data.WATER_BUCKET_DURATION,
                    uses=None, value=player['display_nick'])
        return True, messages.get(lang, 'water_bucket_ok', nick=player['display_nick'],
                                   target=targetPlayer['display_nick'])

    def _buySabotage(self, irc, channel, player, target, lang, now):
        network = irc.network
        targetPlayer, err = self._resolveTarget(irc, channel, network, target, lang,
                                                 player['display_nick'])
        if err:
            return False, err
        if targetPlayer['gun_state'] != 'armed':
            return False, messages.get(lang, 'sabotage_no_gun', target=targetPlayer['display_nick'])
        if db.itemActive(targetPlayer, 'sabotage', now):
            return False, messages.get(lang, 'shop_already_have', nick=player['display_nick'],
                                        item='sabotage on %s' % targetPlayer['display_nick'])
        db.giveItem(targetPlayer, 'sabotage', now, duration=None, uses=1, value=player['display_nick'])
        return True, messages.get(lang, 'sabotage_ok', nick=player['display_nick'],
                                   target=targetPlayer['display_nick'])

    def _buyLifeInsurance(self, irc, channel, player, target, lang, now):
        if db.itemActive(player, 'life_insurance', now):
            return False, self._alreadyHaveMsg(player, 'life_insurance', lang, now)
        meta = data.ITEM_META['life_insurance']
        db.giveItem(player, 'life_insurance', now, duration=meta['duration'], uses=meta['uses'])
        return True, messages.get(lang, 'life_insurance_ok', nick=player['display_nick'])

    def _buyLiabilityInsurance(self, irc, channel, player, target, lang, now):
        if db.itemActive(player, 'liability_insurance', now):
            return False, self._alreadyHaveMsg(player, 'liability_insurance', lang, now)
        meta = data.ITEM_META['liability_insurance']
        db.giveItem(player, 'liability_insurance', now, duration=meta['duration'], uses=meta['uses'])
        return True, messages.get(lang, 'liability_insurance_ok', nick=player['display_nick'])

    def _buyDecoy(self, irc, channel, player, target, lang, now):
        if (self.registryValue('cantAttractDucksWhenSleeping', channel)
                and datetime.fromtimestamp(now).hour in self._sleepHours(channel)):
            return False, messages.get(lang, 'decoy_blocked_sleep')
        delay = self._rng.uniform(data.DECOY_MIN_DELAY, data.DECOY_MAX_DELAY)
        forceNonGolden = not self.registryValue('decoysCanAttractGoldenDucks', channel)
        self._scheduleSpecialSpawn(irc.network, channel, now + delay, 'decoy', forceNonGolden, None)
        return True, messages.get(lang, 'decoy_ok', nick=player['display_nick'])

    def _buyFakeDuck(self, irc, channel, player, target, lang, now):
        self._scheduleSpecialSpawn(irc.network, channel, now + data.FAKE_DUCK_DELAY,
                                    'fake_duck', True, player['display_nick'])
        return True, messages.get(lang, 'fake_duck_ok', nick=player['display_nick'])

    def _buyBread(self, irc, channel, player, target, lang, now):
        if (self.registryValue('cantAttractDucksWhenSleeping', channel)
                and datetime.fromtimestamp(now).hour in self._sleepHours(channel)):
            return False, messages.get(lang, 'bread_blocked_sleep')
        chan = self.db.channel(irc.network, channel)
        maxBread = self.registryValue('maxBreadOnChan', channel)
        count = db.activeBreadCount(chan, now)
        if count >= maxBread:
            return False, messages.get(lang, 'bread_full', max=maxBread)
        db.addBread(chan, now, data.BREAD_DURATION)
        return True, messages.get(lang, 'bread_ok', nick=player['display_nick'],
                                   count=count + 1, max=maxBread)

    def _buyDuckDetector(self, irc, channel, player, target, lang, now):
        if db.itemActive(player, 'duck_detector', now):
            return False, self._alreadyHaveMsg(player, 'duck_detector', lang, now)
        meta = data.ITEM_META['duck_detector']
        db.giveItem(player, 'duck_detector', now, duration=meta['duration'], uses=meta['uses'])
        return True, messages.get(lang, 'duck_detector_ok', nick=player['display_nick'])

    # -----------------------------------------------------------------
    # Weapon confiscation admin commands
    # -----------------------------------------------------------------

    def unarm(self, irc, msg, args, channel, nick, mode):
        """<nick> [static] [<channel>]
        Confiscates <nick>'s weapon. Pass `static` to make it permanent --
        only `rearm` can undo it, and it survives every auto-hand-back mode.
        """
        static = bool(mode) and mode.lower() == 'static'
        lang = self.registryValue('language', channel)
        player = self.db.player(irc.network, channel, nick)
        newState = 'confiscated_permanent' if static else 'confiscated'
        if player['gun_state'] == newState:
            irc.reply(messages.get(lang, 'unarm_already', nick=player['display_nick']))
            return
        player['gun_state'] = newState
        player['stats']['confiscations'] += 1
        self.db.save()
        suffix = messages.get(lang, 'unarm_static_suffix') if static else ''
        irc.reply(messages.get(lang, 'unarm_ok', nick=player['display_nick'], static=suffix))
    unarm = wrap(unarm, [('checkChannelCapability', 'op'), 'channel',
                          'somethingWithoutSpaces', optional('somethingWithoutSpaces')])

    def rearm(self, irc, msg, args, channel, nick):
        """<nick> [<channel>]
        Force-restores <nick>'s weapon, regardless of confiscation mode.
        """
        lang = self.registryValue('language', channel)
        player = self.db.getPlayer(irc.network, channel, nick)
        if not player or player['gun_state'] == 'armed':
            irc.reply(messages.get(lang, 'rearm_already_armed', nick=nick))
            return
        player['gun_state'] = 'armed'
        self.db.save()
        irc.reply(messages.get(lang, 'rearm_ok', nick=player['display_nick']))
    rearm = wrap(rearm, [('checkChannelCapability', 'op'), 'channel', 'somethingWithoutSpaces'])

    def _exportPlayers(self):
        lines = ['network\tchannel\tnick\tlevel\txp\tkilled\tgolden_killed']
        for network in self.db.networks():
            for cname in self.db.channels(network):
                chan = self.db.getChannel(network, cname)
                for p in chan['players'].values():
                    lines.append('%s\t%s\t%s\t%d\t%d\t%d\t%d' % (
                        network, cname, p['display_nick'], data.levelForXp(p['xp']),
                        p['xp'], p['stats']['killed'], p['stats']['golden_killed']))
        directory = os.path.join(str(conf.supybot.directories.data), 'DuckHuntPro')
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, 'export-%d.txt' % int(time.time()))
        with open(path, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        return path

    # -----------------------------------------------------------------
    # Admin toolbox
    # -----------------------------------------------------------------

    class admin(callbacks.Commands):
        """Admin tools: list/fusion/rename/delete/planning/replanning/
        launch/export. All gated behind the `admin` capability."""

        plugin = None

        def list(self, irc, msg, args, channel, pattern):
            """[<channel>] [<pattern>]
            Lists player nicks (optionally filtered by a substring), with
            level/xp, highest xp first.
            """
            p = self.plugin
            lang = p.registryValue('language', channel)
            chan = p.db.getChannel(irc.network, channel)
            players = list(chan['players'].values()) if chan else []
            if pattern:
                players = [pl for pl in players
                           if pattern.lower() in pl['display_nick'].lower()]
            if not players:
                irc.reply(messages.get(lang, 'admin_list_empty'))
                return
            players.sort(key=lambda pl: pl['xp'], reverse=True)
            lines = ['%s (lvl %d, %d xp)' % (pl['display_nick'], data.levelForXp(pl['xp']), pl['xp'])
                      for pl in players]
            irc.reply(' | '.join(lines))
        list = wrap(list, ['admin', 'channel', optional('text')])

        def fusion(self, irc, msg, args, channel, dest, source):
            """<channel> <dest> <source>
            Merges <source>'s stats into <dest> (same logic as automatic
            nick-change fusion).
            """
            p = self.plugin
            lang = p.registryValue('language', channel)
            if not p.db.mergeStats(irc.network, channel, dest, source):
                irc.reply(messages.get(lang, 'admin_target_unknown', nick=source))
                return
            irc.reply(messages.get(lang, 'admin_fusion_ok', sources=source, dest=dest))
        fusion = wrap(fusion, ['admin', 'channel', 'somethingWithoutSpaces', 'somethingWithoutSpaces'])

        def rename(self, irc, msg, args, channel, old, new):
            """<channel> <old> <new>
            Pure rename of <old>'s profile to <new> -- refuses if <new>
            already has a profile (use `fusion` for that case instead).
            """
            p = self.plugin
            lang = p.registryValue('language', channel)
            if not p.db.renamePlayer(irc.network, channel, old, new):
                irc.reply(messages.get(lang, 'admin_rename_exists', new=new))
                return
            irc.reply(messages.get(lang, 'admin_rename_ok', old=old, new=new))
        rename = wrap(rename, ['admin', 'channel', 'somethingWithoutSpaces', 'somethingWithoutSpaces'])

        def delete(self, irc, msg, args, channel, nick):
            """<channel> <nick>
            Deletes <nick>'s profile entirely.
            """
            p = self.plugin
            lang = p.registryValue('language', channel)
            if not p.db.deletePlayer(irc.network, channel, nick):
                irc.reply(messages.get(lang, 'admin_target_unknown', nick=nick))
                return
            irc.reply(messages.get(lang, 'admin_delete_ok', nick=nick))
        delete = wrap(delete, ['admin', 'channel', 'somethingWithoutSpaces'])

        def planning(self, irc, msg, args, channel):
            """[<channel>]
            Shows the local time (HH:MM) of every duck flight currently
            planned for today on this channel, matching Duck_Hunt.tcl's
            duckplanning output.
            """
            p = self.plugin
            lang = p.registryValue('language', channel)
            chan = p.db.getChannel(irc.network, channel)
            flights = sorted(chan.get('planned_flights', [])) if chan else []
            if not flights:
                irc.reply(messages.get(lang, 'admin_planning_empty'))
                return
            times = ', '.join(datetime.fromtimestamp(t).strftime('%H:%M') for t in flights)
            irc.reply(messages.get(lang, 'admin_planning_line', channel=channel, times=times))
        planning = wrap(planning, ['admin', 'channel'])

        def replanning(self, irc, msg, args, channel):
            """[<channel>]
            Forces an immediate recompute of this channel's remaining duck
            schedule (same logic as the daily self-replan, triggered
            early), then shows the new times -- matching Duck_Hunt.tcl's
            duckreplanning output.
            """
            p = self.plugin
            network = irc.network
            lang = p.registryValue('language', channel)
            chan = p.db.getChannel(network, channel)
            if chan:
                for t in chan.get('planned_flights', []):
                    p._unschedule("DuckHuntPro:flight:%s:%s:%r" % (network, channel.lower(), t))
                p._unschedule("DuckHuntPro:plan:%s:%s" % (network, channel.lower()))
            p._planDay(network, channel)
            chan = p.db.getChannel(network, channel)
            flights = sorted(chan.get('planned_flights', [])) if chan else []
            times = ', '.join(datetime.fromtimestamp(t).strftime('%H:%M') for t in flights)
            irc.reply(messages.get(lang, 'admin_replanning_ok', channel=channel, times=times))
        replanning = wrap(replanning, ['admin', 'channel'])

        def launch(self, irc, msg, args, channel, golden):
            """[<channel>] [golden]
            Immediately force-spawns a duck, bypassing the schedule
            entirely. Pass a true value to force it golden. Adds to
            whatever's already in flight -- matches Duck_Hunt.tcl's
            !ducklaunch, which never checks for an existing duck either.
            """
            p = self.plugin
            lang = p.registryValue('language', channel)
            p._spawnDuck(irc, channel, forceGolden=bool(golden))
            irc.reply(messages.get(lang, 'admin_launch_ok'))
        launch = wrap(launch, ['admin', 'channel', optional('boolean')])

        def export(self, irc, msg, args, channel):
            """[<channel>]
            Exports every network/channel's player stats to a plaintext
            file under the bot's data directory.
            """
            p = self.plugin
            lang = p.registryValue('language', channel)
            path = p._exportPlayers()
            irc.reply(messages.get(lang, 'admin_export_ok', path=path))
        export = wrap(export, ['admin', 'channel'])


Class = DuckHuntPro
