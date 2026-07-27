"""
Persistence layer: a single JSON file per bot, holding all channels' game
state. Writes are atomic (tempfile + os.replace) so a crash mid-write can't
corrupt the database -- neither the original TCL script's flat pickle files
nor the existing PT/DuckHunt plugin do this.

Channels are keyed by (network, channel), not channel alone: the same
channel name (e.g. "#duckhunt") can exist on more than one IRC network, and
those are meant to be two entirely independent games, not one shared by
coincidence of name.
"""

import json
import logging
import os
import tempfile
import threading
import time

from . import data

logger = logging.getLogger('supybot.plugins.DuckHuntPro')

# gun_state order, most restrictive last -- used by mergeStats() to decide
# which of two profiles' gun_state "wins" (confiscation always wins over
# armed, permanent always wins over temporary).
_GUN_STATE_ORDER = {'armed': 0, 'confiscated': 1, 'confiscated_permanent': 2}


def _newPlayer(nick):
    return {
        'display_nick': nick,
        'xp': 0,
        'gun_state': 'armed',       # armed | confiscated | confiscated_permanent
        'jammed': False,
        'clip_ammo': None,          # None means "not yet initialized"; the
        'clips_left': None,         # plugin fills these from the level table
        'stats': {
            'killed': 0, 'golden_killed': 0, 'missed': 0,
            'empty_shots': 0, 'humans_shot': 0, 'wild_shots': 0,
            'bullets_received': 0, 'deflected': 0, 'absorbed': 0,
            'confiscations': 0, 'jams': 0, 'deaths': 0,
            'best_time_ms': None, 'total_time_ms': 0, 'timed_shots': 0,
        },
        'items': {},
        'last_activity': None,
    }


def _newChannel():
    return {
        'language': 'en',
        'players': {},
        'bread': [],
        'planned_flights': [],
        'fake_ducks_pending': [],
        'last_duck_at': None,
        'archives': [],
    }


def _newNetwork():
    return {'channels': {}}


# -----------------------------------------------------------------------
# Item/bread helpers. These are plain functions, not Database methods --
# they operate on the mutable dicts already returned by Database.player()/
# .channel(), matching the existing convention in plugin.py (fetch the
# dict, mutate it directly, then call Database.save()) rather than taking
# their own lock.
# -----------------------------------------------------------------------

def itemActive(player, key, now):
    """Returns the item dict for `key` if the player holds it and it hasn't
    time-expired, else None (lazily deleting it if it has expired)."""
    item = player['items'].get(key)
    if item is None:
        return None
    if item.get('expires_at') is not None and item['expires_at'] <= now:
        del player['items'][key]
        return None
    return item


def giveItem(player, key, now, duration=None, uses=None, value=None):
    """Grants (or replaces) an item on a player. Matches Duck_Hunt.tcl:
    shop purchases usually refuse to stack (checked by the caller before
    calling this), but drop-table grants always silently replace."""
    expires_at = (now + duration) if duration else None
    player['items'][key] = {'expires_at': expires_at, 'uses_left': uses, 'value': value}


def removeItem(player, key):
    player['items'].pop(key, None)


def consumeItemUse(player, key):
    """Decrements an item's use counter, removing it once uses hit 0. A
    no-op for items with no use-cap (duration-only, e.g. grease)."""
    item = player['items'].get(key)
    if item is None or item.get('uses_left') is None:
        return
    item['uses_left'] -= 1
    if item['uses_left'] <= 0:
        del player['items'][key]


def addBread(chan, now, duration):
    chan['bread'].append({'expires_at': now + duration})


def pruneExpiredBread(chan, now):
    chan['bread'] = [b for b in chan['bread'] if b['expires_at'] > now]


def activeBreadCount(chan, now):
    pruneExpiredBread(chan, now)
    return len(chan['bread'])


class Database:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.data = {'networks': {}, 'pending_transfers': {}}
        self._load()

    def _load(self):
        with self.lock:
            try:
                if os.path.exists(self.path):
                    with open(self.path, 'r') as f:
                        self.data = json.load(f)
            except Exception as e:
                logger.error("Error loading DB, starting fresh: %s", e)
                self.data = {}
            self.data.setdefault('networks', {})
            self.data.setdefault('pending_transfers', {})

    def save(self):
        with self.lock:
            directory = os.path.dirname(self.path)
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory, prefix='.duckhuntpro-',
                                        suffix='.tmp')
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(self.data, f, indent=2)
                os.replace(tmp, self.path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

    def _network(self, network):
        n = network.lower()
        with self.lock:
            return self.data['networks'].setdefault(n, _newNetwork())

    def networks(self):
        """Returns the list of network names known to the DB (lowercased)."""
        with self.lock:
            return list(self.data['networks'].keys())

    def channels(self, network):
        """Returns the list of channel names known for a network (lowercased)."""
        net = self.data['networks'].get(network.lower())
        with self.lock:
            return list(net['channels'].keys()) if net else []

    def channel(self, network, channelName):
        net = self._network(network)
        c = channelName.lower()
        with self.lock:
            chan = net['channels'].setdefault(c, _newChannel())
            chan.setdefault('archives', [])
            return chan

    def getChannel(self, network, channelName):
        """Read-only lookup; does not create the network/channel if absent."""
        with self.lock:
            net = self.data['networks'].get(network.lower())
            if not net:
                return None
            return net['channels'].get(channelName.lower())

    def player(self, network, channelName, nick):
        chan = self.channel(network, channelName)
        n = nick.lower()
        with self.lock:
            p = chan['players'].setdefault(n, _newPlayer(nick))
            p['display_nick'] = nick
            return p

    def getPlayer(self, network, channelName, nick):
        """Read-only lookup; does not create the player if absent."""
        chan = self.getChannel(network, channelName)
        if not chan:
            return None
        with self.lock:
            return chan['players'].get(nick.lower())

    def topPlayers(self, network, channelName, n=3):
        """Returns up to `n` players ranked by xp (kills as tiebreaker),
        highest first. Empty list if the channel has no players yet."""
        chan = self.getChannel(network, channelName)
        if not chan:
            return []
        with self.lock:
            players = list(chan['players'].values())
        players.sort(key=lambda p: (p['xp'], p['stats']['killed']), reverse=True)
        return players[:n]

    def archiveAndReset(self, network, channelName):
        """Snapshots the current standings (all players, ranked) into the
        channel's archive list, then zeroes every player's xp/stats. Gun
        state, ammo, and items are left untouched -- this resets the
        competitive season, not a player's equipment."""
        chan = self.channel(network, channelName)
        with self.lock:
            standings = [
                {'nick': p['display_nick'], 'xp': p['xp'],
                 'killed': p['stats']['killed'],
                 'golden_killed': p['stats']['golden_killed']}
                for p in chan['players'].values()
            ]
            standings.sort(key=lambda s: (s['xp'], s['killed']), reverse=True)
            chan.setdefault('archives', []).append({
                'archived_at': time.time(),
                'standings': standings,
            })
            for p in chan['players'].values():
                p['xp'] = 0
                for key in p['stats']:
                    p['stats'][key] = None if key == 'best_time_ms' else 0
        self.save()

    def lastArchive(self, network, channelName):
        """Returns the most recent archive dict ({archived_at, standings}),
        or None if this channel has never had a quarterly reset."""
        chan = self.getChannel(network, channelName)
        if not chan or not chan.get('archives'):
            return None
        with self.lock:
            return chan['archives'][-1]

    def deletePlayer(self, network, channelName, nick):
        """Removes a player's profile entirely. Returns whether one existed."""
        chan = self.channel(network, channelName)
        with self.lock:
            existed = chan['players'].pop(nick.lower(), None) is not None
        if existed:
            self.save()
        return existed

    def renamePlayer(self, network, channelName, oldNick, newNick):
        """Pure rename (a key swap, no stat merging) -- refuses if newNick
        already has a profile (use mergeStats for that case instead),
        matching Duck_Hunt.tcl's duckrename admin command."""
        chan = self.channel(network, channelName)
        oldKey, newKey = oldNick.lower(), newNick.lower()
        with self.lock:
            if newKey in chan['players']:
                return False
            player = chan['players'].pop(oldKey, None)
            if player is None:
                return False
            player['display_nick'] = newNick
            chan['players'][newKey] = player
        self.save()
        return True

    def mergeStats(self, network, channelName, dstNick, srcNick):
        """Merges srcNick's profile into dstNick's (xp/stats summed, ammo
        left as dstNick's, gun_state/jammed the more restrictive of the
        two, items unioned, best_time_ms the minimum of the two), then
        deletes srcNick. Returns False if srcNick had no profile to merge
        (a no-op, matching Duck_Hunt.tcl's silent no-merge for a fresh
        nick). Ammo counts are NOT proportionally recalculated the way the
        original's merge_stats attempts to -- dstNick's ammo state is kept
        as-is, a deliberate simplification of a minor edge case."""
        chan = self.channel(network, channelName)
        srcKey, dstKey = srcNick.lower(), dstNick.lower()
        with self.lock:
            src = chan['players'].get(srcKey)
            if not src:
                return False
            dst = chan['players'].setdefault(dstKey, _newPlayer(dstNick))
            dst['xp'] += src['xp']
            for key in data.FUSION_SUMMED_STATS:
                dst['stats'][key] = dst['stats'].get(key, 0) + src['stats'].get(key, 0)
            times = [t for t in (dst['stats'].get('best_time_ms'), src['stats'].get('best_time_ms'))
                     if t is not None]
            dst['stats']['best_time_ms'] = min(times) if times else None
            dst['gun_state'] = max(dst['gun_state'], src['gun_state'],
                                    key=lambda s: _GUN_STATE_ORDER.get(s, 0))
            dst['jammed'] = dst['jammed'] or src['jammed']
            for key, item in src.get('items', {}).items():
                dst.setdefault('items', {}).setdefault(key, item)
            srcActivity = src.get('last_activity')
            if srcActivity and (not dst.get('last_activity') or srcActivity > dst['last_activity']):
                dst['last_activity'] = srcActivity
            if srcKey != dstKey:
                del chan['players'][srcKey]
        self.save()
        return True

    def handBackWeapons(self, network, channelName):
        """Restores every temporarily-confiscated ('confiscated') weapon on
        this channel to 'armed'. Permanently-confiscated
        ('confiscated_permanent') weapons are untouched -- only the `rearm`
        command can undo those. Returns whether anything changed."""
        chan = self.channel(network, channelName)
        changed = False
        with self.lock:
            for p in chan['players'].values():
                if p['gun_state'] == 'confiscated':
                    p['gun_state'] = 'armed'
                    changed = True
        if changed:
            self.save()
        return changed

    def _transferKey(self, network, channelName, nick):
        return "%s|%s|%s" % (network.lower(), channelName.lower(), nick.lower())

    def recordPendingTransfer(self, network, channelName, oldNick, newNick):
        """Records that `oldNick` renamed to `newNick` on this channel; the
        actual stat merge is deferred until newNick's next in-game action
        (see plugin.py's _checkPendingRename), matching Duck_Hunt.tcl's
        "reduce the risk of stat theft" deferral."""
        key = self._transferKey(network, channelName, newNick)
        with self.lock:
            self.data['pending_transfers'][key] = {
                'old_nick': oldNick, 'new_nick': newNick, 'created_at': time.time(),
            }
        self.save()

    def popPendingTransfer(self, network, channelName, nick):
        """Returns and removes the pending transfer for `nick` on this
        channel, or None if there isn't one."""
        key = self._transferKey(network, channelName, nick)
        with self.lock:
            return self.data['pending_transfers'].pop(key, None)

    def discardPendingTransfer(self, network, channelName, nick):
        """Drops a pending transfer without merging -- used when the
        renamed player leaves before ever acting again."""
        key = self._transferKey(network, channelName, nick)
        with self.lock:
            existed = self.data['pending_transfers'].pop(key, None) is not None
        if existed:
            self.save()
