import html
import os
import random
import re
import time
import urllib.parse
from datetime import datetime, timedelta

from supybot.commands import *
from supybot import callbacks, conf, ircmsgs, ircutils, schedule, world
from supybot import ircdb
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
        self._postInitDone = False   # Duck_Hunt.tcl's post_init_done
        self._enabledHooks = {}      # (network, channel) -> (registry value, callback)
        self.db.dropStalePendingTransfers(self.registryValue('pendingTransfersMaxAge'))
        self._scheduleEvent("DuckHuntPro:postinit",
                            time.time() + self.registryValue('postInitDelay'),
                            self._setPostInitDone, ())
        self._reschedulePlannedFlights(irc)
        self._scheduleMidnight()
        self._scheduleMinuteTick()
        self._scheduleAmmoRefill()
        if self.registryValue('quarterlyResetEnabled'):
            self._scheduleQuarterlyReset()
        conf.supybot.plugins.DuckHuntPro.web.enable.addCallback(self._doWebConf)
        if self.registryValue('web.enable'):
            self._startHttp()

    def die(self):
        conf.supybot.plugins.DuckHuntPro.web.enable.removeCallback(self._doWebConf)
        self._stopHttp()
        for value, callback in self._enabledHooks.values():
            value.removeCallback(callback)
        self._enabledHooks.clear()
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
        def run(*a):
            self._scheduled.discard(name)    # it has fired: nothing left to cancel
            return func(*a)
        try:
            schedule.addEvent(run, at, name=name, args=args)
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

    def _flightName(self, network, channelName, t):
        return "DuckHuntPro:flight:%s:%s:%r" % (network, channelName.lower(), t)

    def _planName(self, network, channelName):
        return "DuckHuntPro:plan:%s:%s" % (network, channelName.lower())

    def _setPostInitDone(self):
        self._postInitDone = True

    def _cancelFlights(self, network, channelName):
        """Drops a channel's scheduled flights and any pending first plan."""
        chan = self.db.channel(network, channelName)
        with self.db.lock:
            old = list(chan.get('planned_flights', []))
            chan['planned_flights'] = []
        for t in old:
            self._unschedule(self._flightName(network, channelName, t))
        self._unschedule(self._planName(network, channelName))

    def _schedulePlanAfterDelay(self, network, channelName):
        self._scheduleEvent(self._planName(network, channelName),
                            time.time() + self.registryValue('postInitDelay'),
                            self._planDay, (network, channelName))

    def _reschedulePlannedFlights(self, irc):
        """Restores flight timers lost across a bot restart, and plans a
        fresh day (after postInitDelay) for any enabled channel that has no
        future flights. (The original re-plans from scratch on every load;
        restoring the day's remaining flights is a deliberate improvement.)"""
        now = time.time()
        network = irc.network
        for cname in list(irc.state.channels.keys()):
            self._hookEnabled(network, cname)
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
                    self._scheduleEvent(self._flightName(network, cname, t), t,
                                        self._fireSpawn, (network, cname))
            elif self.registryValue('method') == 2:
                self._schedulePlanAfterDelay(network, cname)

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
        network = irc.network
        self._hookEnabled(network, channel)
        if not self.registryValue('enabled', channel):
            return
        chan = self.db.channel(network, channel)
        with self.db.lock:
            hasFuture = any(t > time.time() for t in chan.get('planned_flights', []))
        if not hasFuture and self.registryValue('method') == 2:
            self._schedulePlanAfterDelay(network, channel)
        self._scheduleGunHandBack(network, channel)

    def _hookEnabled(self, network, channelName):
        """Duck_Hunt.tcl hooks `.chanset +/-DuckHunt` to re-plan at once;
        this watches the channel's `enabled` setting the same way."""
        key = (network.lower(), channelName.lower())
        if key in self._enabledHooks:
            return
        value = self.registryValue('enabled', channelName, value=False)
        state = {'on': bool(self.registryValue('enabled', channelName))}

        def changed():
            on = bool(self.registryValue('enabled', channelName))
            if on != state['on']:
                state['on'] = on
                self._onEnabledChanged(network, channelName, on)
        value.addCallback(changed)
        self._enabledHooks[key] = (value, changed)

    def _onEnabledChanged(self, network, channelName, on):
        if on:
            if self.registryValue('method') == 2:
                self._planDay(network, channelName)
        else:
            self._cancelFlights(network, channelName)

    # -----------------------------------------------------------------
    # Nick-change stat fusion
    # -----------------------------------------------------------------

    def doNick(self, irc, msg):
        """Nick-change tracking (Duck_Hunt.tcl's nickchange_tracking): notes
        that a profile may belong to a player's new nick. The transfer itself
        is deferred to the renamed nick's next in-game action
        (_checkPendingRename), "to reduce the risk of stat theft"."""
        oldNick = msg.nick
        newNick = msg.args[0]
        if oldNick.lower() == newNick.lower():
            return
        for cname in list(irc.state.channels.keys()):
            if (self.registryValue('enabled', cname)
                    and newNick in irc.state.channels[cname].users):
                self._trackNickChange(irc, cname, oldNick, newNick)

    def _logLine(self, channel, key, *args):
        """The original's 'loglev' output: a line in the bot's log."""
        self.log.info(ircutils.stripFormatting(self._t(channel, key, *args)))

    @staticmethod
    def _gunValue(player):
        return {'armed': 1, 'confiscated': 0}.get(player['gun_state'], -1)

    def _statsText(self, p):
        """A profile's numbers in the order the original prints them."""
        st = p['stats']
        best = -1 if st['best_time_ms'] is None else '%.3f' % (st['best_time_ms'] / 1000.0)
        return '{%s}' % ' '.join(str(x) for x in (
            self._gunValue(p), int(bool(p['jammed'])), p['clip_ammo'], p['clips_left'], p['xp'],
            st['killed'], st['missed'], st['empty_shots'], st['humans_shot'], st['wild_shots'],
            st['bullets_received'], st['deflected'], st['deaths'], st['confiscations'],
            st['jams'], best, st['reflex_ms']))

    def _hostOf(self, irc, nick):
        try:
            return irc.state.nickToHostmask(nick).split('!', 1)[1]
        except (KeyError, IndexError):
            return '?'

    def _trackNickChange(self, irc, channel, oldNick, newNick):
        network = irc.network
        lowOld, lowNew = oldNick.lower(), newNick.lower()
        prefix = self.registryValue('anonymPrefix')
        if prefix:
            anonymous = re.compile('^%s[0-9]+$' % re.escape(prefix), re.I)
            # Never hand stats to the nick a server gave an unidentified user.
            if not anonymous.match(oldNick) and anonymous.match(newNick):
                return
        chan = self.db.getChannel(network, channel)
        if not chan:
            return
        players = chan['players']
        # A transfer filed under `oldNick` means somebody earlier renamed TO it.
        pending = self.db.getPendingTransfer(network, channel, oldNick)
        warn = self.registryValue('warnOnRename')
        if lowNew in players:
            # The new nick already has stats: note it, merge later. A reverse
            # entry cancels out; two entries chain into one.
            if pending and pending['old_nick'].lower() == lowNew:
                self.db.popPendingTransfer(network, channel, oldNick)
            elif pending:
                self.db.popPendingTransfer(network, channel, oldNick)
                self.db.recordPendingTransfer(network, channel, pending['old_nick'], newNick)
                if warn:
                    self._logLine(channel, 'm139', 'DuckHuntPro', oldNick,
                                  self._hostOf(irc, newNick), newNick, channel)
            else:
                self.db.recordPendingTransfer(network, channel, oldNick, newNick)
                if warn:
                    self._logLine(channel, 'm139', 'DuckHuntPro', oldNick,
                                  self._hostOf(irc, newNick), newNick, channel)
        elif lowOld in players and not pending:
            self.db.recordPendingTransfer(network, channel, oldNick, newNick)
        elif pending and pending['old_nick'].lower() == lowNew:
            self.db.popPendingTransfer(network, channel, oldNick)

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
        """Duck_Hunt.tcl's ckeck_for_pending_rename: if `nick` just took over
        a nick that had stats, move or merge them now that the new nick is
        playing. With confiscationEnforcementOnFusion, a disarmed new nick
        can't escape its confiscation by inheriting an armed profile."""
        network = irc.network
        entry = self.db.popPendingTransfer(network, channel, nick)
        if not entry:
            return
        oldNick = entry['old_nick']
        oldP = self.db.getPlayer(network, channel, oldNick)
        newP = self.db.getPlayer(network, channel, nick)
        warn = self.registryValue('warnOnTakeover')
        host = self._hostOf(irc, nick)
        script = 'DuckHuntPro'
        log = lambda key, *args: warn and self._logLine(channel, key, script, oldNick, host, nick, *args)
        if oldP is not None:
            enforce = self.registryValue('confiscationEnforcementOnFusion', channel)
            newGun = 1 if newP is None else self._gunValue(newP)
            oldGun = self._gunValue(oldP)
            if enforce and newGun < 1 and oldGun == 1:
                # the old profile was armed, the new one is not: the old stats are dropped
                log('m245', nick, oldNick, oldNick, self._statsText(oldP))
                self.db.deletePlayer(network, channel, oldNick)
            elif enforce and newGun < 1 and oldGun < 1:
                # neither is armed: only the profile with more xp survives
                if newP['xp'] >= oldP['xp']:
                    log('m246', oldNick, self._statsText(oldP))
                    self.db.deletePlayer(network, channel, oldNick)
                else:
                    log('m246', nick, self._statsText(newP))
                    self.db.deletePlayer(network, channel, nick)
                    self.db.renamePlayer(network, channel, oldNick, nick)
            else:
                log('m102', oldNick, self._statsText(oldP), nick,
                    self._statsText(newP) if newP is not None else '{}')
                self.db.mergeStats(network, channel, nick, oldNick)
            survivor = self.db.getPlayer(network, channel, nick)
            if survivor is not None:
                self._clampAmmo(survivor)
            self.db.save()
        elif newP is not None:
            # No stats under the old nick: just flag the (re)assignment.
            log('m127', nick, oldNick, nick, self._statsText(newP))

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

    def _planDay(self, network, channelName, reason=None, now=None):
        """Port of Duck_Hunt.tcl's plan_out_flights for method 2: plans the
        day's flights as clock times. Each duck gets an hour drawn without
        replacement from the allowed (non-sleeping) hours -- the pool is
        refilled when it runs out -- and a random minute (00:00 becomes
        00:01; a taken minute is re-rolled). Active bread adds one flight
        per piece. A replan after bread was bought or expired keeps the
        nearest upcoming time so frequent replans don't thin the ducks out.
        Only the times still ahead of now fire today, as with the original's
        binds (they would fire tomorrow too, but midnight replans first).
        Returns the planned 'HH:MM' strings. (`now` is for tests.)"""
        chan = self.db.channel(network, channelName)
        if (self.registryValue('method') != 2
                or not self.registryValue('enabled', channelName)):
            self._cancelFlights(network, channelName)
            with self.db.lock:
                chan['planned_soarings'] = []
            self.db.save()
            return []
        self._cancelFlights(network, channelName)
        now = now if now is not None else time.time()
        sleepHours = self._sleepHours(channelName)
        reference = ['%02d' % h for h in range(24) if h not in sleepHours]
        if not reference:
            return []
        breadCount = db.activeBreadCount(chan, now)
        perDay = self.registryValue('ducksPerDay', channelName) + breadCount * data.BREAD_EXTRA_DUCKS_PER_PIECE
        keep = None
        # (precedence as in the Tcl: bread_added always; bread_expired only
        # with bread left and after the post-init delay)
        if reason == 'bread_added' or (reason == 'bread_expired' and breadCount > 0
                                       and self._postInitDone):
            current = datetime.fromtimestamp(now).strftime('%H,%M')
            for scanned in sorted(chan.get('planned_soarings', [])):
                if scanned.replace(':', ',', 1) > current:
                    keep = scanned
                    break
        hours = list(reference)
        soarings = []
        for number in range(1, perDay + 1):
            if keep is not None and number == 1:
                hour, minute = keep.split(':')
            else:
                hour = hours.pop(self._rng.randint(0, len(hours) - 1))
                if not hours:
                    hours = list(reference)
                minute = '%02d' % self._rng.randint(0, 59)
                if hour == '00' and minute == '00':
                    minute = '01'
            while '%s:%s' % (hour, minute) in soarings:
                minute = '%02d' % self._rng.randint(0, 59)
            soarings.append('%s:%s' % (hour, minute))
        today = datetime.fromtimestamp(now)
        times = []
        for entry in soarings:
            h, m = (int(x) for x in entry.split(':'))
            at = today.replace(hour=h, minute=m, second=0, microsecond=0).timestamp()
            if at > now:
                times.append(at)
        times.sort()
        with self.db.lock:
            chan['planned_soarings'] = soarings
            chan['planned_flights'] = times
        self.db.save()
        for t in times:
            self._scheduleEvent(self._flightName(network, channelName, t), t,
                                self._fireSpawn, (network, channelName))
        return soarings

    def _plannedText(self, network, channelName):
        chan = self.db.getChannel(network, channelName)
        return ', '.join(sorted(chan.get('planned_soarings', []))) if chan else ''

    def _fireSpawn(self, network, channelName):
        """A planned (or method-1) flight is due. Skipped when a duck already
        flew in this very second -- the original's guard against Eggdrop
        timer drift launching two."""
        irc = self._getIrc(network)
        if irc is None:
            return
        if not self.registryValue('enabled', channelName):
            return
        if channelName not in irc.state.channels:
            return
        chan = self.db.channel(network, channelName)
        last = chan.get('last_duck_at')
        if last is not None and int(time.time()) == int(last):
            return
        self._spawnDuck(irc, channelName)

    # -----------------------------------------------------------------
    # Midnight replan, the per-minute tick (bread expiry, method 1)
    # -----------------------------------------------------------------

    def _scheduleMidnight(self):
        nxt = (datetime.now() + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0).timestamp()
        self._scheduleEvent("DuckHuntPro:midnight:%r" % nxt, nxt, self._midnight, ())

    def _midnight(self):
        """The original replans every channel's flights at 00:00 (method 2)."""
        try:
            if self.registryValue('method') == 2:
                for irc in list(world.ircs):
                    for cname in list(irc.state.channels.keys()):
                        if self.registryValue('enabled', cname):
                            self._planDay(irc.network, cname)
        finally:
            self._scheduleMidnight()

    def _scheduleMinuteTick(self):
        at = (int(time.time() // 60) + 1) * 60
        self._scheduleEvent("DuckHuntPro:tick:%r" % at, at, self._minuteTick, ())

    def _minuteTick(self):
        try:
            self._expireBread()
            if self.registryValue('method') == 1:
                self._checkBushes()
        finally:
            self._scheduleMinuteTick()

    def _expireBread(self):
        """Duck_Hunt.tcl's check_for_expired_pieces_of_bread: expired pieces
        go away one by one, each triggering a replan (method 2)."""
        now = time.time()
        for irc in list(world.ircs):
            for cname in list(irc.state.channels.keys()):
                if (not self.registryValue('enabled', cname)
                        or not self.registryValue('shopEnabled', cname)):
                    continue
                chan = self.db.getChannel(irc.network, cname)
                if not chan or not chan.get('bread'):
                    continue
                with self.db.lock:
                    expired = [b for b in chan['bread'] if b['expires_at'] < now]
                    chan['bread'] = [b for b in chan['bread'] if b['expires_at'] >= now]
                if expired:
                    self.db.save()
                    for _ in expired:
                        self._onBreadChanged(irc.network, cname, 'bread_expired')

    def _checkBushes(self):
        """Method 1: every minute each enabled channel gets a chance of a
        flight, outside the ducks' sleeping hours; each piece of bread adds
        two chances per day."""
        now = datetime.now()
        for irc in list(world.ircs):
            for cname in list(irc.state.channels.keys()):
                if not self.registryValue('enabled', cname):
                    continue
                sleepHours = self._sleepHours(cname)
                span = 1440 - len(sleepHours) * 60
                if now.hour in sleepHours or span <= 0:
                    continue
                chan = self.db.channel(irc.network, cname)
                extra = 2 * db.activeBreadCount(chan, time.time())
                if self._rng.randint(1, span) <= self.registryValue('ducksPerDay', cname) + extra:
                    self._fireSpawn(irc.network, cname)

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

    def _onBreadChanged(self, network, channelName, reason, who=None):
        """Bread was bought ('bread_added') or ran out ('bread_expired'):
        the day's flights are replanned (method 2), as the original's
        replan_flights does, and the replan is logged when
        showBreadReplanning is on."""
        if (self.registryValue('method') != 2
                or not self.registryValue('enabled', channelName)):
            return
        if reason == 'bread_expired' and not self._postInitDone:
            return
        self._planDay(network, channelName, reason)
        if self.registryValue('showBreadReplanning', channelName):
            listing = self._plannedText(network, channelName)
            text = (self._t(channelName, 'm346', 'DuckHuntPro', channelName, listing)
                    if reason == 'bread_expired' else
                    self._t(channelName, 'm345', 'DuckHuntPro', who or '?', channelName, listing))
            self.log.info(ircutils.stripFormatting(text))

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
        changed = False
        for player in list(chan['players'].values()):
            if db.itemActive(player, 'duck_detector', now):
                db.consumeItemUse(player, 'duck_detector')
                changed = True
                self._out(irc, channelName, player['display_nick'],
                          self._t(channelName, 'm351', player['display_nick'], channelName),
                          'notice')
        if changed:
            self.db.save()

    def _duckAnnouncement(self, channel):
        """Duck_Hunt.tcl's flight announcement. Identical for every duck (a
        golden or mechanical one is not given away). With antiHighlight
        (hl_prevention) it is built from random pieces so highlight-triggered
        auto-shooters can't be trained on one string: the trail with four
        quarter-spaced characters removed, a random glyph and a random cry."""
        lang = self._lang(channel)
        if not self.registryValue('antiHighlight', channel):
            return messages.tcl(lang, 'm135')
        trail = messages.tcl(lang, 'm136')
        quarter = len(trail) // 4
        index = self._rng.randint(0, len(trail) - 1)
        indexes = [index]
        for _ in range(3):
            index = (index + quarter) % len(trail)
            indexes.append(index)
        for idx in sorted(indexes, reverse=True):
            trail = trail[:idx] + trail[idx + 1:]
        glyphs = messages.tclList(lang, 'm137')
        cries = messages.tclList(lang, 'm138')
        glyph = glyphs[self._rng.randint(0, len(glyphs) - 1)]
        cry = cries[self._rng.randint(0, len(cries) - 1)]
        return '\x0314%s\x0f \x02%s\x02   \x0314%s\x0f' % (trail, glyph, cry)

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

        # Duck detectors are told first, as in the original.
        self._notifyDuckDetectors(irc, channelName)

        now = time.time()
        self._activeDuck.setdefault(key, []).append({
            'spawned_at': now, 'is_golden': isGolden,
            'hp_total': hpTotal, 'hp_left': hpTotal, 'shots_fired': 0,
            'is_fake': isFake, 'author': buyer, 'signaled': False,
        })

        chan = self.db.channel(irc.network, channelName)
        with self.db.lock:
            chan['last_duck_at'] = now
        self.db.save()

        self._out(irc, channelName, None, self._duckAnnouncement(channelName), 'public')

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
        key = (network.lower(), channelName.lower())
        others = len(self._activeDuck.get(key) or []) > 1
        duck = self._removeDuck(network, channelName, spawnedAt=spawnedAt)
        if duck is None:
            return  # already killed or fled
        irc = self._getIrc(network)
        if irc:
            # "A ... escapes" while others are still flying, "The ..." for the last.
            mkey = ('m247' if others else 'm248') if duck['is_golden'] else (
                ('m353' if others else 'm354') if duck.get('is_fake') else
                ('m3' if others else 'm4'))
            self._out(irc, channelName, None, self._t(channelName, mkey), 'public')
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
        channel = channel or None           # a command without a channel (duckexport)
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
                irc.queueMsg(ircmsgs.privmsg(channel, line) if toChannel and channel
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
        """Port of Duck_Hunt.tcl's hit_a_duck: a hit on the oldest duck.
        A golden duck only loses health (and is revealed by that); a kill
        pays xp (clover bonus included), updates the player's totals and best
        time, may drop an item, and is announced with the original's wording
        for the kind of duck (normal / golden / mechanical), whether it was a
        ricochet and whether other ducks are still flying. `lang` is unused
        (kept for the callers); the channel's language is used."""
        key = (network.lower(), channel.lower())
        ducks = self._activeDuck.get(key)
        if not ducks:
            return
        duck = ducks[0]  # oldest -- always the target
        player = self.db.player(network, channel, shooterNick)
        nick = shooterNick
        now = time.time()
        t = lambda k, *a: self._t(channel, k, *a)
        sound, ammoMsg = {2: ('m427', 'm428'), 3: ('m430', 'm429')}.get(damage, ('m426', None))
        sound = t(sound)
        ammoMsg = t(ammoMsg) if ammoMsg else ''
        noticeMode = self.registryValue('preferredDisplayMode', channel) == 2

        if duck['is_golden']:
            first = duck['hp_left'] == duck['hp_total']
            duck['hp_left'] -= damage
            if duck['hp_left'] > 0:
                if noticeMode and not duck.get('signaled'):
                    self._out(irc, channel, nick, t('m259'), 'public')
                    duck['signaled'] = True
                if first and not noticeMode:
                    self._out(irc, channel, nick, t('m249', nick, sound, damage))
                else:
                    self._out(irc, channel, nick, t('m271', nick, sound, damage))
                return
            xpWon = data.BASE_XP_GOLDEN_DUCK * duck['hp_total']
            if isLucky:
                xpWon += data.XP_LUCKY_SHOT
        elif duck.get('is_fake'):
            xpWon = 0
        else:
            xpWon = data.XP_PER_DUCK + (data.XP_LUCKY_SHOT if isLucky else 0)
        cloverMsg = ''
        clover = db.itemActive(player, 'four_leaf_clover', now)
        if clover:
            # The clover bonus isn't gated on the duck being real in the
            # original: it also applies to a mechanical duck's zero xp.
            xpWon += clover.get('value') or 0
            cloverMsg = t('m369')

        elapsedMs = int((now - duck['spawned_at']) * 1000)
        self._removeDuck(network, channel)
        st = player['stats']
        if duck['is_golden']:
            st['golden_killed'] += 1
        st['killed'] += 1
        oldLevel = data.levelForXp(player['xp'])
        player['xp'] += xpWon
        newLevel = data.levelForXp(player['xp'])
        st['total_time_ms'] += elapsedMs
        st['timed_shots'] += 1
        if st['best_time_ms'] is None or elapsedMs < st['best_time_ms']:
            st['best_time_ms'] = elapsedMs
        lvlUp = (t('m25', newLevel, messages.lvl2rank(newLevel, self._lang(channel)))
                 if newLevel > oldLevel else '')
        spent = messages.adaptTimeResolution(elapsedMs, True, self._lang(channel))

        drop = None
        if self.registryValue('dropsEnabled', channel):
            drop = self._rollAndApplyDrop(channel, player, nick, now)

        total = st['killed']
        totalWord = messages.plural(total, t('m27'), t('m28'))
        goldTotal = st['golden_killed']
        goldWord = messages.plural(goldTotal, t('m274'), t('m275'))
        others = bool(self._activeDuck.get(key))
        golden, fake = duck['is_golden'], duck.get('is_fake')
        if not isLucky:
            mkey = (('m251' if others else 'm250') if golden else
                    ('m357' if others else 'm356') if fake else
                    ('m155' if others else 'm26'))
        else:
            mkey = (('m253' if others else 'm252') if golden else
                    ('m359' if others else 'm358') if fake else
                    ('m156' if others else 'm29'))
        if fake:
            text = t(mkey, nick, sound, spent, duck.get('author') or '?')
        elif golden:
            text = t(mkey, nick, sound, spent, total, totalWord, goldTotal, goldWord,
                     channel, lvlUp, xpWon) + cloverMsg + ammoMsg
        else:
            text = t(mkey, nick, sound, spent, total, totalWord, channel, lvlUp,
                     xpWon) + cloverMsg
        self._out(irc, channel, nick, text, 'public')
        if not others:
            self._maybeHandBackOnDuckGone(network, channel)
        if drop:
            self._out(irc, channel, nick, drop, 'public')
        if self.registryValue('voiceWhenDuckShot', channel):
            self._setVoice(irc, channel, shooterNick, True)

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

    def _rollAndApplyDrop(self, channel, player, nick, now):
        """Rolls the kill drop table (the original's first-success order) and
        applies the winning drop. Returns the announcement, or None on a dry
        roll (the common case)."""
        key = data.rollDrop(self._rng)
        if key is None:
            return None
        t = lambda k, *a: self._t(channel, k, *a)
        lvl = data.LEVELS[data.levelForXp(player['xp'])]
        self._ensureAmmo(player, lvl)
        if key == 'junk':
            junk = messages.tclList(self._lang(channel), 'm394')
            return t('m393', nick) + junk[self._rng.randint(0, len(junk) - 1)]
        if key in data.XP_BOOK_VALUES:
            xp = data.XP_BOOK_VALUES[key]
            player['xp'] += xp
            return t('m406', nick, xp, t('m286'), xp)
        if key == 'ammo':
            if player['clip_ammo'] < lvl.clip_size:
                player['clip_ammo'] += 1
            return t('m395', nick)
        if key == 'clip':
            if player['clips_left'] < lvl.clip_count:
                player['clips_left'] += 1
            return t('m396', nick)
        if key in data.AMMO_TYPE_DAMAGE:
            # AP and explosive ammo replace each other.
            db.removeItem(player, 'explosive_ammo' if key == 'ap_ammo' else 'ap_ammo')
        value = None
        if key == 'four_leaf_clover':
            value = self._rng.randint(data.CLOVER_BONUS_MIN, data.CLOVER_BONUS_MAX)
        meta = data.ITEM_META.get(key)
        db.removeItem(player, key)
        if meta:
            db.giveItem(player, key, now, duration=meta['duration'], uses=meta['uses'],
                        value=value)
        mkey = {'ap_ammo': 'm397', 'explosive_ammo': 'm398', 'grease': 'm399',
                'sight': 'm400', 'infrared_detector': 'm401', 'silencer': 'm402',
                'sunglasses': 'm403', 'duck_detector': 'm404'}.get(key)
        if key == 'four_leaf_clover':
            word = messages.plural(value, '%s %s' % (t('m285'), t('m424')),
                                   '%s %s' % (t('m286'), t('m425')))
            return t('m405', nick, value, value, word)
        return t(mkey, nick)

    def duckreload(self, irc, msg, args, channel):
        """[<channel>]
        Reloads your weapon, or unjams it (and reloads it if it is empty).
        """
        network = irc.network
        nick = msg.nick
        self._checkPendingRename(irc, channel, nick)
        t = lambda k, *a: self._t(channel, k, *a)
        out = lambda text: self._out(irc, channel, nick, text)
        player = self.db.getPlayer(network, channel, nick)
        if player is None:
            # Never played: the original shows the level-1 capacities, untouched.
            lvl = data.LEVELS[data.levelForXp(1)]
            out(t('m204', nick, lvl.clip_size, lvl.clip_size, lvl.clip_count, lvl.clip_count))
            return
        now = time.time()
        player['last_activity'] = now
        try:
            if player['gun_state'] != 'armed':
                out(t('m5', nick))
                return
            key = (network.lower(), channel.lower())
            ducks = self._activeDuck.get(key)
            if ducks:
                player['stats']['reflex_ms'] += int((now - ducks[0]['spawned_at']) * 1000)
            lvl = data.LEVELS[data.levelForXp(player['xp'])]
            self._ensureAmmo(player, lvl)
            noAmmoLimit = self.registryValue('unlimitedAmmoPerClip', channel)
            noClipLimit = self.registryValue('unlimitedAmmoClips', channel)
            empty = player['clip_ammo'] <= 0 and not noAmmoLimit
            outOfClips = player['clips_left'] <= 0 and not noClipLimit

            def counters():
                return (self._displayAmmo(player, lvl, channel),
                        self._displayClips(player, lvl, channel))
            if player['jammed']:
                player['jammed'] = False
                if empty and outOfClips:
                    out(t('m31', nick, *counters()))          # unjammed, no ammo left
                elif empty:
                    player['clip_ammo'] = lvl.clip_size
                    if not noClipLimit:
                        player['clips_left'] -= 1
                    out(t('m32', nick, *counters()))          # unjammed and reloaded
                else:
                    out(t('m33', nick, *counters()))          # just unjammed
            elif empty:
                if outOfClips:
                    out(t('m34', nick, *counters()))
                else:
                    player['clip_ammo'] = lvl.clip_size
                    if not noClipLimit:
                        player['clips_left'] -= 1
                    out(t('m35', nick, *counters()))
            else:
                out(t('m36', nick, *counters()))              # nothing to do
        finally:
            self.db.save()
    duckreload = wrap(duckreload, ['channel'])

    @staticmethod
    def _formatFloat(value, precision):
        """Duck_Hunt.tcl's format_floating_point_value: fixed decimals with
        the trailing zeros (and a dangling point) trimmed."""
        text = ('%.' + str(precision) + 'f') % value
        return text.rstrip('0').rstrip('.') if '.' in text else text

    def _karma(self, channel, wild, humans, ducks):
        """calculate_karma (long form)."""
        if wild + humans + ducks == 0:
            return self._t(channel, 'm41')
        karma = self._formatFloat(
            100.0 * (-((wild * 1) + (humans * 3)) + (ducks * 2))
            / ((wild * 1) + (humans * 3) + (ducks * 2)), 2)
        if float(karma) < 0:
            return self._t(channel, 'm39', self._formatFloat(abs(float(karma)), 2))
        return self._t(channel, 'm40', karma)

    _STATS_INVENTORY = (('ap_ammo', 'm370'), ('explosive_ammo', 'm371'), ('grease', 'm372'),
                        ('sight', 'm373'), ('infrared_detector', 'm374'), ('silencer', 'm375'),
                        ('four_leaf_clover', 'm376'), ('sunglasses', 'm377'),
                        ('life_insurance', 'm378'), ('liability_insurance', 'm379'),
                        ('duck_detector', 'm380'))
    _STATS_EFFECTS = (('mirror_dazzle', 'm381'), ('sand', 'm382'),
                      ('water_bucket', 'm383'), ('sabotage', 'm384'))

    def duckstats(self, irc, msg, args, channel, target):
        """[<channel>] [<nick>]
        Shows your hunting stats, or <nick>'s (a NOTICE).
        """
        target = target or msg.nick
        self._checkPendingRename(irc, channel, target)
        t = lambda k, *a: self._t(channel, k, *a)
        now = time.time()
        player = self.db.getPlayer(irc.network, channel, target)
        known = player is not None
        if not known:
            player = db._newPlayer(target)          # a fresh profile's default values
        st = player['stats']
        lvlIndex = data.levelForXp(player['xp'])
        lvl = data.LEVELS[lvlIndex]
        if not known:
            player['clip_ammo'], player['clips_left'] = lvl.clip_size, lvl.clip_count
        else:
            self._ensureAmmo(player, lvl)
        ducks, missed = st['killed'], st['missed']
        golden = st['golden_killed']
        neutralized = st['bullets_received'] - st['deaths'] - st['deflected']
        reliability = 100 - lvl.jam_pct
        reliabilityMod = ''
        if db.itemActive(player, 'grease', now):
            reliabilityMod += '\x0303+%d%%\x03' % int((100 - reliability) / 2)
        if db.itemActive(player, 'sand', now):
            reliabilityMod += '\x0304-%d%%\x03' % int(reliability / 2)
        lang = self._lang(channel)
        bestTime = ('-' if st['best_time_ms'] is None
                    else messages.adaptTimeResolution(st['best_time_ms'], True, lang))
        avgReflex = ('-' if ducks == 0 else messages.adaptTimeResolution(
            round(st['reflex_ms'] / ducks), True, lang))
        yes, no = t('m37'), t('m38')
        totalFired = ducks + missed
        effective = '%d%%' % ((100 * ducks) // totalFired) if totalFired else '-'
        accuracyMod = ''
        if db.itemActive(player, 'mirror_dazzle', now):
            accuracyMod += '\x0304-%d%%\x03' % int(lvl.accuracy / 2)
        if db.itemActive(player, 'sight', now):
            accuracyMod += '\x0303+%d%%\x03' % int((100 - lvl.accuracy) / 3)
        names = {k: t(m) for k, m in self._STATS_INVENTORY + self._STATS_EFFECTS}
        inventory = [names[k] for k, _ in self._STATS_INVENTORY if db.itemActive(player, k, now)]
        effects = [names[k] for k, _ in self._STATS_EFFECTS if db.itemActive(player, k, now)]
        sep = ' \x0314/\x03 '
        itemsText = t('m385', sep.join(inventory)) if inventory else ''
        effectsText = t('m386', sep.join(effects)) if effects else ''
        toNext = lvl.xp_threshold - player['xp']
        p = messages.plural
        text = t('m42',
                 self._displayAmmo(player, lvl, channel), self._displayClips(player, lvl, channel),
                 yes if player['jammed'] else no, st['jams'],
                 yes if player['gun_state'] != 'armed' else no, st['confiscations'],
                 messages.colorizeValue(player['xp']), lvlIndex, messages.lvl2rank(lvlIndex, lang),
                 toNext, p(toNext, t('m43'), t('m44')),
                 self._karma(channel, st['wild_shots'], st['humans_shot'], ducks),
                 lvl.accuracy, accuracyMod, effective, reliability, reliabilityMod,
                 lvl.defense, lvl.deflection, bestTime, avgReflex,
                 ducks, p(ducks, t('m45'), t('m46')),
                 golden, p(golden, t('m274'), t('m275')),
                 missed, p(missed, t('m47'), t('m48')),
                 st['humans_shot'], p(st['humans_shot'], t('m49'), t('m50')),
                 st['empty_shots'], p(st['empty_shots'], t('m51'), t('m52')),
                 st['wild_shots'], p(st['wild_shots'], t('m53'), t('m54')),
                 totalFired, p(totalFired, t('m55'), t('m56')),
                 st['bullets_received'], p(st['bullets_received'], t('m57'), t('m58')),
                 st['deaths'], p(st['deaths'], t('m59'), t('m60')),
                 st['deflected'], p(st['deflected'], t('m61'), t('m62')),
                 neutralized, p(neutralized, t('m63'), t('m64'))) + itemsText + effectsText
        self._out(irc, channel, msg.nick, text, 'notice')
    duckstats = wrap(duckstats, ['channel', optional('somethingWithoutSpaces')])

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
        Shows how long ago the last duck flew on <channel>. In the channel it
        is a normal reply; sent privately it needs the channel op capability
        and answers with a NOTICE (the original's lastduck /msg command).
        """
        chan = self.db.getChannel(irc.network, channel)
        lastAt = chan.get('last_duck_at') if chan else None
        lang = self._lang(channel)
        if ircutils.isChannel(msg.args[0]):
            if not lastAt:
                self._out(irc, channel, msg.nick, self._t(channel, 'm146', channel))
            else:
                self._out(irc, channel, msg.nick, self._t(channel, 'm144', messages.adaptTimeResolution(
                    (int(time.time()) - int(lastAt)) * 1000, False, lang)))
            return
        notice = lambda text: self._out(irc, channel, msg.nick, text, 'notice')
        if not self._isStaff(msg.prefix, channel):
            return
        if channel not in irc.state.channels:
            notice(self._t(channel, 'm75', channel))
        elif not self.registryValue('enabled', channel):
            notice(self._t(channel, 'm76', 'DuckHuntPro', channel))
        elif not lastAt:
            notice(self._t(channel, 'm146', channel))
        else:
            notice(self._t(channel, 'm147', channel, messages.adaptTimeResolution(
                (int(time.time()) - int(lastAt)) * 1000, False, lang)))
    lastduck = wrap(lastduck, ['channel'])

    # -----------------------------------------------------------------
    # Shop
    # -----------------------------------------------------------------

    def _onChan(self, irc, channel, nick):
        """Tcl's `onchan`: case-insensitive membership of the channel."""
        try:
            users = irc.state.channels[channel].users
        except KeyError:
            return False
        for u in users:
            if ircutils.strEqual(u, nick):
                return True
        return False

    def shop(self, irc, msg, args, channel, text):
        """[<channel>] [<id> [<target>]]
        Without arguments lists the purchasable items, otherwise buys item
        number <id> (1-23) with your xp. Items 14-17 (mirror, sand, water
        bucket, sabotage) need a <target> player, the others take none.
        """
        # Tcl only binds the command when shop_enabled is set.
        if not self.registryValue('shopEnabled', channel):
            return
        network = irc.network
        nick = msg.nick
        self._checkPendingRename(irc, channel, nick)
        if not self._floodCheck(network, channel, nick):
            irc.reply(messages.get(self.registryValue('language', channel),
                                   'antiflood_blocked', nick=nick))
            return
        player = self.db.player(network, channel, nick)
        try:
            self._shop(irc, channel, nick, network, player, (text or '').split())
        finally:
            self.db.save()
    shop = wrap(shop, ['channel', optional('text')])

    def _shop(self, irc, channel, nick, network, player, parts):
        """Port of Duck_Hunt.tcl's ::DuckHunt::shop, check for check."""
        key = (network.lower(), channel.lower())
        now = time.time()
        lang = self._lang(channel)
        t = lambda k, *a: self._t(channel, k, *a)
        # Tcl: the shop is only closed to a PERMANENTLY confiscated gun (gun
        # == -1), and then it does nothing at all, not even a message.
        if player['gun_state'] == 'confiscated_permanent':
            return
        ducks = self._activeDuck.get(key)
        if ducks:
            # Tcl: any shop use during a duck session adds to the reflex time.
            player['stats']['reflex_ms'] += int((now - ducks[0]['spawned_at']) * 1000)
        out = lambda text: self._out(irc, channel, nick, text, 'pref')
        costs = [data.ITEM_COSTS[k] for k in data.SHOP_ITEMS]
        itemId = parts[0] if parts else ''
        targetNick = parts[1] if len(parts) > 1 else ''
        valid = [str(i) for i in range(1, 24)]
        noTarget = [str(i) for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
                                     18, 19, 20, 21, 22, 23)]
        withTarget = ['14', '15', '16', '17']
        if ((itemId in noTarget and len(parts) != 1)
                or (itemId in withTarget and len(parts) != 2)
                or (itemId != '' and itemId not in valid)):
            out(t('m264', 'shop'))
            return
        if itemId == '':
            if self.registryValue('shopPreferredDisplayMode', channel):
                out(t('m263', 'DuckHuntPro', self.registryValue('shopUrl', channel), 'shop'))
            else:
                out(t('m265', 'DuckHuntPro', *(costs + ['shop'])))
            return

        player['last_activity'] = now
        itemNo = int(itemId)
        itemKey = data.SHOP_ITEMS[itemNo - 1]
        cost = costs[itemNo - 1]
        plural = messages.plural(cost, t('m285'), t('m286'))
        # Tcl: the floor test uses the price even for a purchase that is then
        # refused for another reason, and runs before any other check.
        if player['xp'] - cost < self.registryValue('minXpForShopping', channel):
            out(t('m266', nick))
            return
        if targetNick:
            self._checkPendingRename(irc, channel, targetNick)
        prevLevel = data.levelForXp(player['xp'])
        lvl = data.LEVELS[prevLevel]
        self._ensureAmmo(player, lvl)
        items = player['items']
        left = lambda item: messages.adaptTimeResolution(
            int(((item.get('expires_at') or now) - now) * 1000), False, lang)
        usesWord = lambda n: messages.plural(n, t('m292'), t('m293'))
        output = None
        charged = False

        def give(p, k, value=None):
            meta = data.ITEM_META[k]
            db.giveItem(p, k, now, duration=meta['duration'], uses=meta['uses'], value=value)

        if itemNo in (1, 2):
            # Tcl tests gun == 0 here: a temporarily confiscated player is
            # "not armed" (a permanent one never gets this far).
            if player['gun_state'] != 'armed':
                out(t('m5', nick))
            elif itemNo == 1 and player['clip_ammo'] >= lvl.clip_size:
                out(t('m267', nick))
            elif itemNo == 2 and player['clips_left'] >= lvl.clip_count:
                out(t('m269', nick))
            else:
                if itemNo == 1:
                    player['clip_ammo'] += 1
                    output = t('m268', nick, cost, plural)
                else:
                    player['clips_left'] += 1
                    output = t('m270', nick, cost, plural)
                charged = True
        elif itemNo in (3, 4):
            other = 'explosive_ammo' if itemNo == 3 else 'ap_ammo'
            item = db.itemActive(player, itemKey, now)
            if item:
                out(t('m277', nick, left(item)))
            else:
                # Tcl: buying one ammo type silently replaces the other.
                db.removeItem(player, other)
                give(player, itemKey)
                output = t('m278' if itemNo == 3 else 'm279', nick, cost, plural)
                charged = True
        elif itemNo == 5:
            if player['gun_state'] == 'armed':
                out(t('m281', nick))
            else:
                player['gun_state'] = 'armed'
                output = t('m282', nick, cost, plural)
                charged = True
        elif itemNo in (6, 9, 10, 11, 19):
            item = db.itemActive(player, itemKey, now)
            if item:
                out(t('m283', nick, left(item)))
            else:
                if itemNo == 10:
                    bonus = self._rng.randint(data.CLOVER_BONUS_MIN, data.CLOVER_BONUS_MAX)
                    give(player, itemKey, bonus)
                    output = t('m294', nick, cost, plural, bonus, messages.plural(
                        bonus, '%s %s' % (t('m285'), t('m424')), '%s %s' % (t('m286'), t('m425'))))
                else:
                    give(player, itemKey)
                    output = t({6: 'm284', 9: 'm291', 11: 'm296', 19: 'm342'}[itemNo],
                               nick, cost, plural)
                charged = True
        elif itemNo in (7, 22):
            item = db.itemActive(player, itemKey, now)
            if item:
                out(t('m288', nick, item['uses_left'], usesWord(item['uses_left'])))
            else:
                give(player, itemKey)
                output = t('m287' if itemNo == 7 else 'm350', nick, cost, plural)
                charged = True
        elif itemNo in (8, 18):
            item = db.itemActive(player, itemKey, now)
            if item:
                out(t('m295', nick, left(item), item['uses_left'], usesWord(item['uses_left'])))
            else:
                give(player, itemKey)
                output = t('m289' if itemNo == 8 else 'm339', nick, cost, plural)
                charged = True
        elif itemNo == 12:
            # Spare clothes only cure the water bucket (Tcl item 16).
            if not db.itemActive(player, 'water_bucket', now):
                out(t('m297', nick))
            else:
                db.removeItem(player, 'water_bucket')
                output = t('m298', nick, cost, plural)
                charged = True
        elif itemNo == 13:
            if (not db.itemActive(player, 'sand', now)
                    and not db.itemActive(player, 'sabotage', now)):
                out(t('m299', nick))
            else:
                db.removeItem(player, 'sand')
                db.removeItem(player, 'sabotage')
                output = t('m300', nick, cost, plural)
                charged = True
        elif itemNo in (14, 15, 16, 17):
            # Tcl never refuses a target equal to the buyer.
            targetPlayer = self.db.getPlayer(network, channel, targetNick)
            gone = {14: 'm363', 15: 'm364', 16: 'm365', 17: 'm366'}[itemNo]
            if targetPlayer is None:
                out(t('m362', nick))
            elif not self._onChan(irc, channel, targetNick):
                out(t(gone, nick, targetNick))
            elif itemNo == 14:
                if db.itemActive(targetPlayer, 'mirror_dazzle', now):
                    out(t('m324', nick, targetNick))
                elif db.itemActive(player, 'sunglasses', now):
                    # Tcl quirk: tests the BUYER's sunglasses, yet the message
                    # says the target wears them; the buyer pays for nothing.
                    output = t('m325', nick, targetNick, cost, plural)
                    charged = True
                else:
                    db.giveItem(targetPlayer, 'mirror_dazzle', now, duration=None,
                                uses=1, value=player['display_nick'])
                    output = t('m326', nick, cost, plural, targetNick)
                    charged = True
            elif itemNo == 15:
                if targetPlayer['gun_state'] != 'armed':
                    out(t('m367', nick, targetNick))
                elif db.itemActive(targetPlayer, 'sand', now):
                    out(t('m327', nick, targetNick))
                elif db.itemActive(targetPlayer, 'grease', now):
                    # Grease is used up by the sand, which has no effect.
                    db.removeItem(targetPlayer, 'grease')
                    output = t('m328', nick, targetNick, cost, plural)
                    charged = True
                else:
                    db.giveItem(targetPlayer, 'sand', now, duration=None, uses=1,
                                value=player['display_nick'])
                    output = t('m329', nick, targetNick, cost, plural)
                    charged = True
            elif itemNo == 16:
                if db.itemActive(targetPlayer, 'water_bucket', now):
                    out(t('m330', nick, targetNick))
                else:
                    db.giveItem(targetPlayer, 'water_bucket', now,
                                duration=data.WATER_BUCKET_DURATION, uses=None,
                                value=player['display_nick'])
                    output = t('m331', nick, targetNick, cost, plural)
                    charged = True
            else:
                if targetPlayer['gun_state'] != 'armed':
                    out(t('m368', nick, targetNick))
                elif db.itemActive(targetPlayer, 'sabotage', now):
                    out(t('m335', nick, targetNick))
                else:
                    db.giveItem(targetPlayer, 'sabotage', now, duration=None, uses=1,
                                value=player['display_nick'])
                    output = t('m336', nick, targetNick, cost, plural)
                    charged = True
        elif itemNo in (20, 21):
            if (self.registryValue('cantAttractDucksWhenSleeping', channel)
                    and datetime.fromtimestamp(now).hour in self._sleepHours(channel)):
                out(t('m388', nick))
            elif itemNo == 20:
                # Tcl: utimer int(rand()*600)+1 seconds.
                delay = self._rng.randint(data.DECOY_MIN_DELAY, data.DECOY_MAX_DELAY)
                forceNonGolden = not self.registryValue('decoysCanAttractGoldenDucks', channel)
                self._scheduleSpecialSpawn(network, channel, now + delay, 'decoy',
                                           forceNonGolden, None)
                output = t('m344', nick, cost, plural)
                charged = True
            else:
                chan = self.db.channel(network, channel)
                maxBread = self.registryValue('maxBreadOnChan', channel)
                # Tcl quirk: the cap test is `==`, so lowering maxBreadOnChan
                # below the current count lets purchases through again.
                if db.activeBreadCount(chan, now) == maxBread:
                    out(t('m387', nick, maxBread, channel))
                else:
                    db.addBread(chan, now, data.BREAD_DURATION)
                    self._onBreadChanged(network, channel, 'bread_added', nick)
                    count = len(chan['bread'])
                    output = t('m347', nick, cost, plural, count,
                               messages.plural(count, t('m348'), t('m349')), channel)
                    charged = True
        else:
            # 23: Tcl has no sleeping-hours or other check for the fake duck.
            self._scheduleSpecialSpawn(network, channel, now + data.FAKE_DUCK_DELAY,
                                       'fake_duck', True, player['display_nick'])
            output = t('m361', nick, cost, plural)
            charged = True

        if charged:
            player['xp'] -= cost
            self._clampAmmo(player)
        newLevel = data.levelForXp(player['xp'])
        if prevLevel > newLevel and output is not None:
            # Tcl appends m280 (not the m2 channel announcement) to the reply.
            output += t('m280', newLevel, messages.lvl2rank(newLevel, lang))
        if output is not None:
            out(output)

    # -----------------------------------------------------------------
    # Weapon confiscation admin commands
    # -----------------------------------------------------------------

    def unarm(self, irc, msg, args, channel, text):
        """[<channel>] [-static] <nick>
        Confiscates <nick>'s weapon; it is handed back at the next automatic
        hand-back. With -static the confiscation is permanent: only `rearm`
        undoes it and no automatic hand-back mode touches it.
        """
        self._requireStaff(irc, msg, channel)
        t = lambda k, *a: self._t(channel, k, *a)
        out = lambda text: self._out(irc, channel, msg.nick, text, 'public')
        parts = (text or '').split()
        static = bool(parts) and parts[0].lower() in ('-static', '--static')
        if static:
            parts = parts[1:]
        if not parts:
            out(t('m66', 'unarm'))
            return
        target = parts[0]
        self._checkPendingRename(irc, channel, target)
        player = self.db.getPlayer(irc.network, channel, target)
        if player is None:
            out(t('m67', msg.nick, target, channel))
            return
        state = player['gun_state']
        nick = msg.nick
        if static:
            if state == 'confiscated_permanent':
                out(t('m68', nick, target, target))
            elif state == 'armed':
                player['stats']['confiscations'] += 1
                player['gun_state'] = 'confiscated_permanent'
                out(t('m69', nick, target))
            else:
                player['gun_state'] = 'confiscated_permanent'
                out(t('m70', nick, target))
        elif state == 'confiscated_permanent':
            player['gun_state'] = 'confiscated'
            out(t('m128', nick, target))
        elif state == 'armed':
            player['stats']['confiscations'] += 1
            player['gun_state'] = 'confiscated'
            out(t('m129', nick, target))
        else:
            out(t('m130', nick, target))
        self.db.save()
    unarm = wrap(unarm, ['channel', optional('text')])

    def rearm(self, irc, msg, args, channel, target):
        """[<channel>] <nick>
        Gives <nick> their weapon back, whether it was confiscated
        automatically, temporarily or permanently.
        """
        self._requireStaff(irc, msg, channel)
        t = lambda k, *a: self._t(channel, k, *a)
        out = lambda text: self._out(irc, channel, msg.nick, text, 'public')
        if not target:
            out(t('m71', 'rearm'))
            return
        self._checkPendingRename(irc, channel, target)
        player = self.db.getPlayer(irc.network, channel, target)
        if player is None:
            out(t('m67', msg.nick, target, channel))
        elif player['gun_state'] == 'armed':
            out(t('m72', target, msg.nick))
        else:
            player['gun_state'] = 'armed'
            out(t('m73', msg.nick, target))
            self.db.save()
    rearm = wrap(rearm, ['channel', optional('somethingWithoutSpaces')])

    # -----------------------------------------------------------------
    # Staff commands (the original's /msg commands, Duck_Hunt.cfg's *_auth)
    # -----------------------------------------------------------------

    def _isStaff(self, prefix, channel):
        """The original's `o|o` / `m|m` flags (channel op or halfop). Limnoria
        has no per-channel flags, so it is the #channel,op / #channel,halfop
        capabilities; global admin counts too."""
        for cap in (ircdb.makeChannelCapability(channel, 'op'),
                    ircdb.makeChannelCapability(channel, 'halfop'), 'admin'):
            if ircdb.checkCapability(prefix, cap):
                return True
        return False

    def _requireStaff(self, irc, msg, channel):
        if not self._isStaff(msg.prefix, channel):
            irc.errorNoCapability(ircdb.makeChannelCapability(channel, 'op'), Raise=True)

    def _staffArgs(self, irc, msg, text, cmd, syntaxKey, minArgs, maxArgs):
        """Common head of the admin commands: splits `text`, checks the staff
        capability on its first word (the channel), and answers with the
        command's syntax NOTICE when the argument count is wrong. Returns the
        word list, or None when the command is over."""
        parts = (text or '').split()
        chan = parts[0] if parts else None
        if chan is None:
            if not (ircdb.checkCapability(msg.prefix, 'admin')):
                irc.errorNoCapability('admin', Raise=True)
        else:
            self._requireStaff(irc, msg, chan)
        if not minArgs <= len(parts) <= maxArgs:
            self._out(irc, chan or '', msg.nick, self._t(chan, syntaxKey, cmd), 'notice')
            return None
        return parts

    def _knownChannel(self, irc, msg, chan, requireEnabled=True):
        """The original's `validchan` and `channel get $chan DuckHunt` checks:
        the channel's name as the bot knows it, or None after the NOTICE."""
        for name in irc.state.channels:
            if ircutils.strEqual(name, chan):
                if requireEnabled and not self.registryValue('enabled', name):
                    self._out(irc, name, msg.nick, self._t(name, 'm76', 'DuckHuntPro', name), 'notice')
                    return None
                return name
        self._out(irc, chan, msg.nick, self._t(chan, 'm75', chan), 'notice')
        return None

    def ducklist(self, irc, msg, args, text):
        """<channel> [<search>]
        Lists the profiles (nicks) known on <channel>, or those containing
        <search>."""
        parts = self._staffArgs(irc, msg, text, 'ducklist', 'm122', 1, 2)
        if parts is None:
            return
        chan = self._knownChannel(irc, msg, parts[0], requireEnabled=False)
        if chan is None:
            return
        notice = lambda out: self._out(irc, chan, msg.nick, out, 'notice')
        info = self.db.getChannel(irc.network, chan)
        if not info or not info['players']:
            notice(self._t(chan, 'm123', chan))
            return
        nicks = sorted(info['players'])
        search = parts[1] if len(parts) > 1 else ''
        if search:
            nicks = [n for n in nicks if search.lower() in n.lower()]
        if not nicks:
            notice(self._t(chan, 'm126', search))
        elif len(nicks) == 1:
            notice(self._t(chan, 'm124', nicks[0]))
        else:
            notice(self._t(chan, 'm125', len(nicks), ' '.join(nicks)))
    ducklist = wrap(ducklist, [optional('text')])

    def duckfusion(self, irc, msg, args, text):
        """<channel> <destination nick> <source nick> [<source nick> ...]
        Merges the stats of the source profiles into the destination's."""
        parts = self._staffArgs(irc, msg, text, 'duckfusion', 'm74', 3, 1000)
        if parts is None:
            return
        chan = self._knownChannel(irc, msg, parts[0])
        if chan is None:
            return
        dst = parts[1]
        notice = lambda out: self._out(irc, chan, msg.nick, out, 'notice')
        if self.db.getPlayer(irc.network, chan, dst) is None:
            notice(self._t(chan, 'm77', dst, chan))
            return
        merged = False
        for src in parts[2:]:
            if self.db.getPlayer(irc.network, chan, src) is None:
                notice(self._t(chan, 'm77', src, chan))
            elif src.lower() == dst.lower():
                continue                # merging a profile into itself would delete it
            else:
                self.db.mergeStats(irc.network, chan, dst, src)
                merged = True
                notice(self._t(chan, 'm78', dst, src, dst, chan))
        if merged:
            self._clampAmmo(self.db.getPlayer(irc.network, chan, dst))
            self.db.save()
    duckfusion = wrap(duckfusion, [optional('text')])

    def duckrename(self, irc, msg, args, text):
        """<channel> <old nick> <new nick>
        Renames a profile."""
        parts = self._staffArgs(irc, msg, text, 'duckrename', 'm131', 3, 3)
        if parts is None:
            return
        chan = self._knownChannel(irc, msg, parts[0])
        if chan is None:
            return
        old, new = parts[1], parts[2]
        notice = lambda out: self._out(irc, chan, msg.nick, out, 'notice')
        if self.db.getPlayer(irc.network, chan, old) is None:
            notice(self._t(chan, 'm77', old, chan))
        elif not self.db.renamePlayer(irc.network, chan, old, new):
            notice(self._t(chan, 'm132', new, chan, 'duckfusion'))
        else:
            notice(self._t(chan, 'm133', old, new, chan))
    duckrename = wrap(duckrename, [optional('text')])

    def duckdelete(self, irc, msg, args, text):
        """<channel> <nick>
        Deletes a profile."""
        parts = self._staffArgs(irc, msg, text, 'duckdelete', 'm141', 2, 2)
        if parts is None:
            return
        chan = self._knownChannel(irc, msg, parts[0], requireEnabled=False)
        if chan is None:
            return
        notice = lambda out: self._out(irc, chan, msg.nick, out, 'notice')
        if not self.db.deletePlayer(irc.network, chan, parts[1]):
            notice(self._t(chan, 'm142', parts[1], chan))
        else:
            notice(self._t(chan, 'm143', parts[1], chan))
    duckdelete = wrap(duckdelete, [optional('text')])

    def _planningChecks(self, irc, msg, text, cmd, syntaxKey):
        """The head shared by duckplanning and duckreplanning: returns the
        channel when the plan can be shown or recomputed."""
        if self.registryValue('method') != 2:
            irc.error('Flights are not planned in advance (method is not 2).', Raise=True)
        parts = self._staffArgs(irc, msg, text, cmd, syntaxKey, 1, 1)
        if parts is None:
            return None
        chan = self._knownChannel(irc, msg, parts[0])
        if chan is None:
            return None
        if not self._postInitDone:
            self._out(irc, chan, msg.nick, self._t(chan, 'm243', 'DuckHuntPro'), 'notice')
            return None
        return chan

    def duckplanning(self, irc, msg, args, text):
        """<channel>
        Shows today's planned duck flights on <channel> (method 2 only)."""
        chan = self._planningChecks(irc, msg, text, 'duckplanning', 'm79')
        if chan is None:
            return
        listing = self._plannedText(irc.network, chan)
        self._out(irc, chan, msg.nick, self._t(chan, 'm81', chan, listing)
                  if listing else self._t(chan, 'm154', chan), 'notice')
    duckplanning = wrap(duckplanning, [optional('text')])

    def duckreplanning(self, irc, msg, args, text):
        """<channel>
        Computes a different flight plan for the rest of today (method 2
        only) and shows it."""
        chan = self._planningChecks(irc, msg, text, 'duckreplanning', 'm148')
        if chan is None:
            return
        soarings = self._planDay(irc.network, chan)
        self._out(irc, chan, msg.nick,
                  self._t(chan, 'm149', chan, ', '.join(sorted(soarings))), 'notice')
    duckreplanning = wrap(duckreplanning, [optional('text')])

    def ducklaunch(self, irc, msg, args, text):
        """<channel> [<golden duck: 0|1>]
        Makes a duck fly right now on <channel>; 1 makes it a golden one. It
        adds to whatever is already flying and, like the original, says
        nothing back."""
        parts = self._staffArgs(irc, msg, text, 'ducklaunch', 'm82', 1, 2)
        if parts is None:
            return
        if len(parts) == 2 and parts[1] not in ('0', '1'):
            self._out(irc, parts[0], msg.nick, self._t(parts[0], 'm82', 'ducklaunch'), 'notice')
            return
        chan = self._knownChannel(irc, msg, parts[0])
        if chan is None:
            return
        golden = len(parts) == 2 and parts[1] == '1'
        self._spawnDuck(irc, chan, forceGolden=golden, forceNonGolden=not golden)
    ducklaunch = wrap(ducklaunch, [optional('text')])

    # The export's columns, in the original's order: (sort key, header message).
    _EXPORT_COLUMNS = ('nick', 'last_activity', 'xp', 'level', 'xp_lvl_up', 'ammo', 'max_ammo',
                       'ammo_clips', 'max_clips', 'accuracy', 'effective_accuracy', 'deflection',
                       'armor', 'jamming', 'jammed', 'jammed_nbr', 'gun', 'confisc', 'ducks',
                       'golden_ducks', 'missed', 'empty', 'accidents', 'wild_shots',
                       'total_ammo', 'shot_at', 'neutralized', 'deflected', 'deaths',
                       'best_time', 'average_reflex_time', 'karma', 'rank', 'items')
    _EXPORT_WIDTHS = (0, 19, 5, 3, 4, 3, 3, 3, 3, 4, 7, 4, 4, 4, 1, 4, 2, 4, 5, 3, 5, 5, 4, 5,
                      6, 4, 4, 4, 4, 16, 16, 7, 0, 0)
    _EXPORT_CRITERIA = ('nick', 'last_activity', 'xp', 'level', 'xp_lvl_up', 'gun', 'ammo',
                        'max_ammo', 'ammo_clips', 'max_clips', 'accuracy', 'effective_accuracy',
                        'deflection', 'defense', 'jamming', 'jammed', 'jammed_nbr', 'confisc',
                        'ducks', 'golden_ducks', 'missed', 'empty', 'accidents', 'wild_shots',
                        'total_ammo', 'shot_at', 'neutralized', 'deflected', 'deaths',
                        'best_time', 'average_reflex_time', 'karma', 'rank', 'items')

    @staticmethod
    def _dictionaryKey(value):
        """Tcl's `lsort -dictionary`: case-insensitive, digit runs compared as
        numbers."""
        return [(0, int(chunk), '') if chunk.isdigit() else (1, 0, chunk.lower())
                for chunk in re.findall(r'\d+|\D+', str(value))]

    def _exportRow(self, channel, player, now):
        lvlIndex = data.levelForXp(player['xp'])
        lvl = data.LEVELS[lvlIndex]
        st = player['stats']
        ducks, missed = st['killed'], st['missed']
        total = ducks + missed
        clipAmmo = lvl.clip_size if player['clip_ammo'] is None else player['clip_ammo']
        clips = lvl.clip_count if player['clips_left'] is None else player['clips_left']
        karma = 0
        if st['wild_shots'] + st['humans_shot'] + ducks:
            karma = float(self._formatFloat(
                100.0 * (-(st['wild_shots'] + st['humans_shot'] * 3) + ducks * 2)
                / (st['wild_shots'] + st['humans_shot'] * 3 + ducks * 2), 2))
        lastActivity = player.get('last_activity')
        return [player['display_nick'], -1 if lastActivity is None else int(lastActivity),
                player['xp'], lvlIndex, lvl.xp_threshold - player['xp'], clipAmmo, lvl.clip_size,
                clips, lvl.clip_count, lvl.accuracy,
                float(self._formatFloat(100.0 * ducks / total, 2)) if total else -1,
                lvl.deflection, lvl.defense, lvl.jam_pct, 1 if player['jammed'] else 0,
                st['jams'],
                {'armed': 1, 'confiscated': 0}.get(player['gun_state'], -1),
                st['confiscations'], ducks, st['golden_killed'], missed, st['empty_shots'],
                st['humans_shot'], st['wild_shots'], total, st['bullets_received'],
                st['bullets_received'] - st['deaths'] - st['deflected'], st['deflected'],
                st['deaths'],
                9999999999 if st['best_time_ms'] is None else st['best_time_ms'] / 1000.0,
                round(st['reflex_ms'] / ducks / 1000.0, 3) if ducks else 9999999999,
                karma, messages.lvl2rank(lvlIndex, self._lang(channel)),
                ' '.join(sorted(k for k in player['items'] if db.itemActive(player, k, now)))]

    def _exportPlayers(self, network, sortBy):
        """Duck_Hunt.tcl's export_players_table: writes a fixed-width table of
        every channel's players on `network`; returns the file's path."""
        now = time.time()
        lang = self.registryValue('language')
        t = lambda key, *a: messages.tcl(lang, key, *a)
        sortBy = sortBy or 'nick'
        sortKey = {'defense': 'armor', 'jammed_nbr': 'jammed_nbr'}.get(sortBy, sortBy)
        index = self._EXPORT_COLUMNS.index(sortKey)
        stamp = datetime.fromtimestamp(now)
        title = t('m207', 'DuckHuntPro', '2.11', network, stamp.strftime('%d'),
                  stamp.strftime('%m'), stamp.strftime('%Y'), stamp.strftime('%H:%M:%S'), sortBy)
        lines = [' ' + '-' * (len(title) + 4) + ' ', '|  %s  |' % title,
                 ' ' + '-' * (len(title) + 4) + ' ', '',
                 '%s %s' % (t('m244'), ' '.join(self._EXPORT_CRITERIA)), '', '']
        channels = [(name, self.db.getChannel(network, name)) for name in self.db.channels(network)]
        channels = [(name, c) for name, c in channels if c and c['players']]
        if not channels:
            lines.append(t('m208'))
        else:
            rows = {name: [self._exportRow(name, p, now) for p in c['players'].values()]
                    for name, c in channels}
            allRows = [row for chanRows in rows.values() for row in chanRows]
            widths = list(self._EXPORT_WIDTHS)
            widths[0] = max([len(row[0]) for row in allRows] or [0])
            widths[32] = max(len(r) for r in messages.tclList(lang, 'm134'))
            widths[33] = max([len(row[33]) for row in allRows] or [0])
            headers = [t('m%d' % (209 + i)) for i in range(34)]
            underline = [max(w, len(h)) for w, h in zip(widths, headers)]
            colWidth = [w + 3 for w in underline]
            fmt = lambda cells: ''.join(str(c).ljust(w) for c, w in zip(cells, colWidth))
            for name, _ in channels:
                lines += [name, '-' * len(name), fmt(headers), fmt('-' * u for u in underline)]
                table = sorted(rows[name], key=lambda r: self._dictionaryKey(r[0]))
                if sortKey in ('nick', 'rank'):
                    table.sort(key=lambda r: self._dictionaryKey(r[index]))
                elif sortKey in ('best_time', 'average_reflex_time'):
                    table.sort(key=lambda r: r[index])
                elif sortKey == 'items':
                    table.sort(key=lambda r: self._dictionaryKey(r[index]))
                    table.sort(key=lambda r: len(r[index]), reverse=True)
                else:
                    table.sort(key=lambda r: r[index], reverse=True)
                for r in table:
                    r = list(r)
                    r[10] = '-' if r[10] == -1 else '%s%%' % self._formatFloat(r[10], 2)
                    for i in (9, 11, 12, 13):
                        r[i] = '%s%%' % r[i]
                    r[29] = '-' if r[29] == 9999999999 else messages.adaptTimeResolution(
                        round(r[29] * 1000), True, lang)
                    r[30] = '-' if r[30] == 9999999999 else messages.adaptTimeResolution(
                        round(r[30] * 1000), True, lang)
                    r[1] = '-' if r[1] == -1 else time.strftime(t('m422'), time.localtime(r[1]))
                    lines.append(fmt(r))
                lines += ['', '']
        directory = os.path.join(str(conf.supybot.directories.data), 'DuckHuntPro')
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, 'players_table.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        return path

    def duckexport(self, irc, msg, args, sortBy):
        """[<sort criterion>]
        Writes a table of every player's data to a text file (sorted by nick
        unless a criterion is given). Needs the global admin capability,
        since it covers every channel."""
        if not ircdb.checkCapability(msg.prefix, 'admin'):
            irc.errorNoCapability('admin', Raise=True)
        notice = lambda out: self._out(irc, '', msg.nick, out, 'notice')
        lang = self.registryValue('language')
        sortBy = (sortBy or '').strip()
        if len(sortBy.split()) > 1:
            notice(messages.tcl(lang, 'm205', 'duckexport'))
        elif sortBy and sortBy.lower() not in self._EXPORT_CRITERIA:
            valid = list(self._EXPORT_CRITERIA)
            valid.insert(len(valid) - 1, messages.tcl(lang, 'm80'))
            notice(messages.tcl(lang, 'm206', sortBy, ' '.join(valid)))
        else:
            notice(messages.tcl(lang, 'm262', self._exportPlayers(irc.network, sortBy.lower())))
    duckexport = wrap(duckexport, [optional('text')])


Class = DuckHuntPro
