import json
import os
import re
import time
import threading
import fnmatch
import logging
import urllib.request
from supybot.commands import *
from supybot import callbacks, conf, ircdb, ircmsgs, ircutils, schedule, world

try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('Blacklist')
except ImportError:
    _ = lambda x: x

logger = logging.getLogger('supybot.plugins.Blacklist')

class Blacklist(callbacks.Plugin):
    """Manages channel security with a numbered blacklist and ID-based deletion,
    plus an optional network-wide blacklist enforced across every channel."""

    banmasks = {
        0: '*!ident@host', 1: '*!*ident@host', 2: '*!*@host',
        3: '*!*ident@*.host', 4: '*!*@*.host', 5: 'nick!ident@host',
        6: 'nick!*ident@host', 7: 'nick!*@host', 8: 'nick!*ident@*.host',
        9: 'nick!*@*.host', 10: '*!ident@*'
    }

    threaded = True

    def __init__(self, irc):
        super().__init__(irc)
        self.dbfile = os.path.join(str(conf.supybot.directories.data), 'Blacklist', 'blacklist.json')
        self._db_lock = threading.RLock()
        self.db = {}
        self._initdb()
        # Nested command groups (self.exempt / self.net) are
        # instantiated by BasePlugin.__init__ above but have no reference to
        # this instance's DB, so we hand them one explicitly.
        self.exempt.plugin = self
        self.net.plugin = self
        self._reschedule_all(irc)

    # -----------------------------------------------------------------
    # DB persistence, schema & migration
    # -----------------------------------------------------------------

    def _initdb(self):
        try:
            if not os.path.exists(os.path.dirname(self.dbfile)):
                os.makedirs(os.path.dirname(self.dbfile))
            if os.path.exists(self.dbfile):
                with open(self.dbfile, 'r') as f:
                    self.db = json.load(f)
            else:
                self.db = {}
            self._migrate_legacy()
            self.db.setdefault('channels', {})
            self.db.setdefault('net', {'next_id': 1, 'entries': {}, 'exempt': []})
            self.db['net'].setdefault('entries', {})
            self.db['net'].setdefault('exempt', [])
            self.db['net'].setdefault('next_id', 1)
            for bucket in self.db['channels'].values():
                bucket.setdefault('exempt', [])
            self._dbWrite()
        except Exception as e:
            logger.error(f"Error loading DB: {e}")
            self.db = {'channels': {}, 'net': {'next_id': 1, 'entries': {}, 'exempt': []}}

    def _migrate_legacy(self):
        """Converts the old {channel: {mask: [adder, created_at, reason,
        is_bot_cmd, expiry_at]}} schema (positional IDs, no net list, no
        exempt list) into the current schema with stable per-entry IDs."""
        if not self.db or 'channels' in self.db or 'net' in self.db:
            return
        old = self.db
        migrated = {}
        for chan, masks in old.items():
            entries = {}
            next_id = 1
            if not isinstance(masks, dict):
                continue
            for mask, data in masks.items():
                if not isinstance(data, list):
                    continue
                adder = data[0] if len(data) > 0 else 'unknown'
                created_at = data[1] if len(data) > 1 else time.time()
                reason = data[2] if len(data) > 2 else ''
                is_bot_cmd = data[3] if len(data) > 3 else False
                expire_at = data[4] if len(data) > 4 else None
                expire_mode = 'full' if expire_at else None
                entries[mask] = {
                    'id': next_id, 'adder': adder, 'created_at': created_at,
                    'reason': reason, 'is_bot_cmd': is_bot_cmd,
                    'expire_at': expire_at, 'expire_mode': expire_mode,
                }
                next_id += 1
            migrated[chan] = {'next_id': next_id, 'entries': entries, 'exempt': []}
        self.db = {'channels': migrated, 'net': {'next_id': 1, 'entries': {}, 'exempt': []}}
        logger.info("Blacklist: migrated legacy database to the new schema.")

    def _dbWrite(self):
        with self._db_lock:
            try:
                with open(self.dbfile, 'w') as f:
                    json.dump(self.db, f, indent=2)
            except Exception as e:
                logger.error(f"Error writing DB: {e}")

    # -----------------------------------------------------------------
    # Bucket / entry helpers
    # -----------------------------------------------------------------

    def _get_channel_bucket(self, channel):
        return self.db['channels'].get(channel.lower())

    def _ensure_channel_bucket(self, channel):
        c_lower = channel.lower()
        with self._db_lock:
            bucket = self.db['channels'].setdefault(
                c_lower, {'next_id': 1, 'entries': {}, 'exempt': []})
        return bucket

    def _resolve(self, bucket, token):
        """Resolves a mask-or-ID user token to the actual mask key in bucket."""
        if not bucket:
            return None
        if token.isdigit():
            idx = int(token)
            for m, e in bucket['entries'].items():
                if e['id'] == idx:
                    return m
            return None
        return token if token in bucket['entries'] else None

    def _search_bucket(self, bucket, pattern):
        if not bucket:
            return []
        needle = pattern.lower()
        with self._db_lock:
            items = list(bucket['entries'].items())
        out = []
        for m, e in items:
            haystack = f"{m} {e['adder']} {e['reason']}".lower()
            if needle in haystack or fnmatch.fnmatch(m.lower(), f"*{needle}*"):
                out.append(f"[{e['id']}] {m}: {e['reason'] or '(no reason)'}")
        return out

    def _internal_add(self, channel, mask, adder, reason, is_bot_cmd=False,
                       expire_at=None, expire_mode=None):
        c_lower = channel.lower()
        with self._db_lock:
            bucket = self.db['channels'].setdefault(
                c_lower, {'next_id': 1, 'entries': {}, 'exempt': []})
            existing = bucket['entries'].get(mask)
            entry_id = existing['id'] if existing else bucket['next_id']
            if not existing:
                bucket['next_id'] += 1
            bucket['entries'][mask] = {
                'id': entry_id, 'adder': adder, 'created_at': time.time(),
                'reason': reason, 'is_bot_cmd': is_bot_cmd,
                'expire_at': expire_at, 'expire_mode': expire_mode,
                'lifted': False,
            }
            self._dbWrite()
        return entry_id

    def _internal_del(self, channel, mask):
        c_lower = channel.lower()
        with self._db_lock:
            bucket = self.db['channels'].get(c_lower)
            if bucket and mask in bucket['entries']:
                del bucket['entries'][mask]
                self._dbWrite()
                return True
        return False

    def _net_add(self, mask, adder, reason, expire_at=None, expire_mode=None):
        with self._db_lock:
            bucket = self.db['net']
            existing = bucket['entries'].get(mask)
            entry_id = existing['id'] if existing else bucket['next_id']
            if not existing:
                bucket['next_id'] += 1
            bucket['entries'][mask] = {
                'id': entry_id, 'adder': adder, 'created_at': time.time(),
                'reason': reason, 'is_bot_cmd': True,
                'expire_at': expire_at, 'expire_mode': expire_mode,
            }
            self._dbWrite()
        return entry_id

    # -----------------------------------------------------------------
    # Exempt lists: masks, optionally grouped under a label (usually the
    # person's nick). Shared by the channel lists and the network list. The
    # flat store['exempt'] list is what matching uses; store['exempt_names']
    # maps mask -> label purely for grouping, so old databases keep working.
    # -----------------------------------------------------------------

    def _exemptAdd(self, store, first, second):
        """Appends (never replaces). `first` is a label and `second` its
        mask, or `first` alone is a bare mask. Returns an error string or
        None."""
        label, mask = (first, second) if second is not None else (None, first)
        if not ircutils.isUserHostmask(mask) or not mask.isascii():
            return "Must be a nick!user@host mask (wildcards allowed, ASCII only)."
        if label is not None and (not label.isascii() or ircutils.isUserHostmask(label)):
            return "The name must be a plain ASCII label (usually a nick), not a mask."
        with self._db_lock:
            masks = store.setdefault('exempt', [])
            names = store.setdefault('exempt_names', {})
            if mask not in masks:
                masks.append(mask)
            if label is not None:
                names[mask] = label
            self._dbWrite()
        return None

    def _exemptRemove(self, store, first, second):
        """`first second` removes that mask from that label; a lone `first`
        removes that mask, or every mask under that label. Returns an error
        string or None."""
        with self._db_lock:
            masks = store.setdefault('exempt', [])
            names = store.setdefault('exempt_names', {})
            def labelled(m):
                return names.get(m, '').lower() == first.lower()
            if second is not None:
                victims = [m for m in masks if m == second and labelled(m)]
                if not victims:
                    return "That mask isn't listed under %s." % first
            elif first in masks:
                victims = [first]
            else:
                victims = [m for m in masks if labelled(m)]
                if not victims:
                    return "No exempt mask or name matches %s." % first
            for m in victims:
                masks.remove(m)
                names.pop(m, None)
            self._dbWrite()
        return None

    def _exemptGroups(self, store, label=None):
        """[(name or None, [masks])] in listing order -- named groups first,
        then the unnamed masks -- or just one name's group."""
        with self._db_lock:
            masks = list(store.get('exempt', []))
            names = dict(store.get('exempt_names', {}))
        if label is not None:
            sel = [m for m in masks if names.get(m, '').lower() == label.lower()]
            return [(names[sel[0]], sel)] if sel else []
        groups, plain = {}, []
        for m in masks:
            n = names.get(m)
            if n:
                groups.setdefault(n.lower(), (n, []))[1].append(m)
            else:
                plain.append(m)
        out = list(groups.values())
        if plain:
            out.append((None, plain))
        return out

    def _replyExemptList(self, irc, store, channel, title, label, empty):
        """Replies with the exempt list ('Mimi: m1, m2 | Bob: m3 | m4, m5'),
        or, past maxInlineEntries masks, uploads it to the configured paste
        service (pastebinUrl/pastebinField, same as the ban list) and
        replies with the link. `label` limits it to one name."""
        groups = self._exemptGroups(store, label)
        total = sum(len(ms) for _, ms in groups)
        if not total:
            irc.error("No exempt masks under %s." % label) if label else irc.reply(empty)
            return
        if total > (self.registryValue('maxInlineEntries', channel) or 5):
            text = f"{title} ({total} masks):\n" + "=" * 45 + "\n"
            for name, ms in groups:
                text += (f"{name}:\n" if name else "(no name):\n")
                text += "".join(f"  {m}\n" for m in ms)
            url = self._createPastebin(channel, text)
            irc.reply(f"Exempt list too large ({total} masks). View here: {url}")
        else:
            irc.reply(" | ".join(
                (f"{n}: " if n else "") + ", ".join(ms) for n, ms in groups))

    # -----------------------------------------------------------------
    # Exemption checks
    # -----------------------------------------------------------------

    def _matchesAny(self, patterns, hostmask):
        # NB: supybot.commands defines its own `any` (a wrap-spec converter),
        # which shadows the builtin via our `from supybot.commands import *`.
        # Spell this out as a loop instead of relying on builtin any().
        for p in patterns:
            if ircutils.hostmaskPatternEqual(p, hostmask):
                return True
        return False

    def _isExempt(self, channel, hostmask):
        if not hostmask:
            return False
        with self._db_lock:
            patterns = list(self.db['net'].get('exempt', []))
            bucket = self.db['channels'].get(channel.lower())
            if bucket:
                patterns += list(bucket.get('exempt', []))
        return self._matchesAny(patterns, hostmask)

    def _isExemptNet(self, hostmask):
        if not hostmask:
            return False
        with self._db_lock:
            patterns = list(self.db['net'].get('exempt', []))
        return self._matchesAny(patterns, hostmask)

    def _resolveHostmask(self, irc, target):
        """Best-effort resolution of a nick or mask argument to a concrete
        hostmask, for matching against exempt patterns."""
        if ircutils.isUserHostmask(target):
            return target
        try:
            return irc.state.nickToHostmask(target)
        except KeyError:
            return None

    def _looksLikeExtban(self, mask):
        """True if `mask` can't be a plain nick!user@host ban (e.g. an
        ircd-specific extban such as ~account:foo, $a:foo, or z:foo). A
        real mask always has an '@' with no ':' before it. We never parse
        or interpret extban syntax -- just refuse to touch it."""
        at = mask.find('@')
        if at == -1:
            return True
        return ':' in mask[:at]

    def _botHostmask(self, irc):
        try:
            return irc.state.nickToHostmask(irc.nick)
        except KeyError:
            return irc.prefix

    def _isSelfBan(self, irc, mask):
        """True if `mask` would match the bot itself."""
        return not self._looksLikeExtban(mask) and \
            ircutils.hostmaskPatternEqual(mask, self._botHostmask(irc))

    def _isBotTrusted(self, prefix, channel=None):
        """True if `prefix` maps to a bot user that explicitly has `admin`
        or the channel's op capability. ignoreDefaultAllow, as AutoMode
        does, so a stranger can't pass on Limnoria's default-allow rule."""
        caps = ['admin']
        if channel:
            caps.insert(0, ircdb.makeChannelCapability(channel, 'op'))
        # NB: a loop, not any() -- supybot.commands' `any` shadows the builtin.
        for cap in caps:
            if ircdb.checkCapability(prefix, cap, ignoreDefaultAllow=True):
                return True
        return False

    def _reactToSelfBan(self, irc, msg, channel):
        """Somebody (msg.prefix) just tried to ban the bot, and the ban has
        been refused or undone. If kickOnSelfBan is on: someone who is only
        an IRC op gets kicked with kickOnSelfBanReason; someone registered
        with the bot as a channel op or admin just gets the reason said in
        the channel, tagged with their nick."""
        if not channel or not self.registryValue('kickOnSelfBan', channel):
            return
        if not ircutils.isUserHostmask(msg.prefix) \
                or ircutils.strEqual(msg.nick, irc.nick):
            return
        reason = self.registryValue('kickOnSelfBanReason', channel)
        if self._isBotTrusted(msg.prefix, channel):
            irc.queueMsg(ircmsgs.privmsg(channel, f"{msg.nick}: {reason}"))
            return
        try:
            state = irc.state.channels[channel]
        except KeyError:
            return
        if msg.nick in state.users and (state.isOp(irc.nick) or state.isHalfop(irc.nick)):
            irc.queueMsg(ircmsgs.kick(channel, msg.nick, reason))

    def _refuseSelfBan(self, irc, msg, channel=None):
        """A command asked for a ban that matches the bot. Net commands pass
        no channel and use the one the command was sent in, if any. A
        trusted requester gets the reason in the reply itself; anyone else
        is handled like a manual self-ban (kicked, if the option is on)."""
        if channel is None and msg.args and ircutils.isChannel(msg.args[0]):
            channel = msg.args[0]
        if channel and self.registryValue('kickOnSelfBan', channel) \
                and self._isBotTrusted(msg.prefix, channel):
            reason = self.registryValue('kickOnSelfBanReason', channel)
            irc.error(f"I'm not going to ban myself. {reason}")
            return
        irc.error("I'm not going to ban myself.")
        self._reactToSelfBan(irc, msg, channel)

    # Nick characters (RFC 1459 specials included) plus the * and ? wildcards.
    _NICKISH = re.compile(r'^[A-Za-z\[\]\\`_^{|}*?][A-Za-z0-9\[\]\\`_^{|}*?-]*$')

    def _completeMask(self, target):
        """Eggdrop's +ban completion for a token that isn't a full
        nick!user@host: `nick` -> nick!*@*, `user@host` -> *!user@host,
        `nick!user` -> nick!user@*. Returns None for extban-looking input (a
        leading ~ or $, or a ':' before the '@') and for anything that still
        isn't a plain hostmask after completion. ASCII only: networks
        case-map nicks in US-ASCII, so a non-ASCII ban can't match reliably."""
        if not target or not target.isascii() \
                or target[0] in '~$' or ':' in target.split('@', 1)[0]:
            return None
        if '!' not in target:
            if '@' not in target:
                mask = target + '!*@*' if self._NICKISH.match(target) else None
            else:
                mask = '*!' + target
        elif '@' not in target:
            mask = target + '@*'
        else:
            mask = target
        return mask if mask and ircutils.isUserHostmask(mask) else None

    def _isKnownNick(self, irc, target):
        """True if `target` currently resolves to a real, known nick.
        NB: ircutils.isNick() is deliberately NOT used here -- Limnoria
        monkeypatches it (see conf.py) to defer to the lenient
        supybot.protocols.irc.strictRfc setting, under which almost any
        space-free, '!'-free, non-channel string (including extban syntax
        like "~account:foo") reports as a "valid nick". Actual
        resolvability is the only reliable signal."""
        try:
            irc.state.nickToHostmask(target)
            return True
        except KeyError:
            return False

    # -----------------------------------------------------------------
    # ircd limits (ISUPPORT MODES / MAXLIST), mask coverage, hit tracking
    # -----------------------------------------------------------------

    def _modesPerLine(self, irc):
        """ISUPPORT MODES: how many list modes one MODE line may carry. If
        it's absent the spec default of 3 applies; present without a value
        means no limit, which we still cap at 12 to keep lines short."""
        supported = irc.state.supported
        if 'modes' not in supported:
            return 3
        return supported['modes'] or 12

    def _modeMsgs(self, irc, channel, masks, unban=False):
        """MODE messages setting +b (or -b) on `masks`, stacked as many per
        line as the ircd allows and kept well under the 512-byte limit."""
        build = ircmsgs.unbans if unban else ircmsgs.bans
        per_line = self._modesPerLine(irc)
        msgs, chunk, size = [], [], 0
        for mask in masks:
            if chunk and (len(chunk) >= per_line or size + len(mask) > 400):
                msgs.append(build(channel, chunk))
                chunk, size = [], 0
            chunk.append(mask)
            size += len(mask) + 1
        if chunk:
            msgs.append(build(channel, chunk))
        return msgs

    def _banRoom(self, irc, channel):
        """How many more +b the channel's ban list takes (ISUPPORT MAXLIST's
        b, or the older MAXBANS), or None if the ircd didn't say. Only +b is
        counted: Limnoria doesn't track +e/+I/+q, which share one pool with
        +b on some ircds (Solanum's MAXLIST=bqeI:100), and bans still in
        flight aren't counted either. So this can only overestimate the
        room, never refuse wrongly; do478 covers the gap."""
        supported = irc.state.supported
        limit = (supported.get('maxlist') or {}).get('b') or supported.get('maxbans')
        if not limit:
            return None
        try:
            used = len(irc.state.channels[channel].bans)
        except KeyError:
            return None
        return max(limit - used, 0)

    def _makeRoom(self, irc, channel, keep):
        """The ban list is full and `keep` needs a slot: if rotateBans is
        on, lift the least recently active ban this plugin owns (one of the
        channel's entries, or a network entry if the channel enforces
        those). Bans set outside the plugin and extbans are never touched.
        A permanent channel entry is only marked lifted and comes back on
        the next matching join, as with banlistExpiry; a timed one ('full'
        expiry, e.g. `timer` or a manual ban) is released early, entry and
        all, for good behaviour. A network entry is only lifted in this
        channel. Returns (mask, released), or None if nothing could go."""
        if not self.registryValue('rotateBans', channel):
            return None
        try:
            present = {b.lower() for b in irc.state.channels[channel].bans}
        except KeyError:
            return None
        candidates = []  # (last activity, mask, scope, entry)
        with self._db_lock:
            bucket = self.db['channels'].get(channel.lower())
            for m, e in (bucket['entries'].items() if bucket else ()):
                candidates.append((e.get('last_hit') or e['created_at'], m, 'channel', e))
            if self.registryValue('enforceGlobal', channel):
                for m, e in self.db['net']['entries'].items():
                    candidates.append((e.get('last_hit') or e['created_at'], m, 'net', e))
        candidates = [c for c in candidates
                      if c[1].lower() in present and c[1].lower() != keep.lower()]
        if not candidates:
            return None
        _, mask, scope, e = min(candidates, key=lambda c: c[0])
        irc.queueMsg(ircmsgs.unban(channel, mask))
        irc.state.channels[channel].bans.discard(mask)
        released = scope == 'channel' and e.get('expire_mode') == 'full'
        if scope == 'channel':
            with self._db_lock:
                if released:
                    self.db['channels'][channel.lower()]['entries'].pop(mask, None)
                else:
                    e['lifted'] = True
                    if e.get('expire_mode') == 'irc_only':
                        e['expire_at'] = e['expire_mode'] = None
                self._dbWrite()
            self._unschedule('channel', channel, e['id'])
        logger.info(f"Blacklist: {channel}'s ban list is full; "
                    f"{'released' if released else 'lifted'} {mask} "
                    f"to make room for {keep}.")
        return mask, released

    def _hasRoom(self, irc, channel, mask):
        """True if a +b for `mask` should fit, making room first if the
        list is full and rotateBans allows it."""
        return self._banRoom(irc, channel) != 0 \
            or self._makeRoom(irc, channel, mask) is not None

    def _maskCovers(self, wide, narrow):
        """True if every hostmask `narrow` matches is also matched by `wide`:
        a '*' in `wide` absorbs anything, a '?' any one character but a '*',
        and everything else must be equal under IRC casemapping."""
        a, b = ircutils.toLower(wide), ircutils.toLower(narrow)
        memo = {}
        def covers(i, j):
            if (i, j) not in memo:
                if i == len(a):
                    r = j == len(b)
                elif a[i] == '*':
                    r = covers(i + 1, j) or (j < len(b) and covers(i, j + 1))
                elif j == len(b):
                    r = False
                elif a[i] == '?':
                    r = b[j] != '*' and covers(i + 1, j + 1)
                else:
                    r = a[i] == b[j] and covers(i + 1, j + 1)
                memo[(i, j)] = r
            return memo[(i, j)]
        return covers(0, 0)

    def _coverage(self, entries, mask, expire_at=None):
        """(covering, covered) for a new `mask` against existing (mask, entry)
        pairs: an entry that already bans everything `mask` would (and lasts
        at least as long), and the narrower entries `mask` makes redundant.
        The identical mask is neither: re-adding it just updates the entry."""
        covering, covered = None, []
        for m, e in entries:
            if ircutils.toLower(m) == ircutils.toLower(mask):
                continue
            if self._maskCovers(m, mask):
                theirs = e.get('expire_at') if e.get('expire_mode') == 'full' else None
                if covering is None and (theirs is None or
                        (expire_at is not None and theirs >= expire_at)):
                    covering = (m, e)
            elif self._maskCovers(mask, m):
                covered.append((m, e))
        return covering, covered

    def _coveredNote(self, covered, limit=5):
        """Reply suffix naming the existing entries a new mask makes redundant."""
        if not covered:
            return ""
        names = ", ".join(f"[{e['id']}] {m}" for m, e in covered[:limit])
        if len(covered) > limit:
            names += f" and {len(covered) - limit} more"
        return (f" It also covers {names}; delete "
                f"{'them' if len(covered) > 1 else 'it'} to free ban list slots.")

    def _matchingMembers(self, irc, channel, mask, exempt):
        """Nicks in `channel` whose hostmask matches `mask`, except the bot
        itself and anything the `exempt(hostmask)` callable protects."""
        try:
            members = list(irc.state.channels[channel].users)
        except KeyError:
            return []
        out = []
        for nick in members:
            if ircutils.strEqual(nick, irc.nick):
                continue
            try:
                hm = irc.state.nickToHostmask(nick)
            except KeyError:
                continue
            if not exempt(hm) and ircutils.hostmaskPatternEqual(mask, hm):
                out.append(nick)
        return out

    def _tooBroad(self, irc, channel, mask, exempt):
        """An error string if `mask` matches more members of `channel` than
        its maxBanMatches allows (0 = no limit), else None."""
        limit = self.registryValue('maxBanMatches', channel)
        if not limit:
            return None
        n = len(self._matchingMembers(irc, channel, mask, exempt))
        if n <= limit:
            return None
        return (f"{mask} matches {n} people in {channel} (maxBanMatches is "
                f"{limit}). Add --force if you really mean it.")

    def _recordHit(self, scope, channel, mask, count=1):
        """Counts `count` people caught by an entry and stamps when."""
        with self._db_lock:
            bucket = self.db['net'] if scope == 'net' \
                else self.db['channels'].get(channel.lower())
            entry = bucket['entries'].get(mask) if bucket else None
            if entry is None:
                return
            entry['hits'] = entry.get('hits', 0) + count
            entry['last_hit'] = time.time()
            self._dbWrite()

    def _ago(self, seconds):
        seconds = max(int(seconds), 0)
        for unit, size in (('d', 86400), ('h', 3600), ('m', 60)):
            if seconds >= size:
                return f"{seconds // size}{unit}"
        return f"{seconds}s"

    def _hitText(self, e, now):
        """', 3 hits, last 2d ago' for an entry that has caught anyone."""
        hits = e.get('hits', 0)
        if not hits:
            return ""
        return (f", {hits} hit{'s' if hits != 1 else ''}, "
                f"last {self._ago(now - e['last_hit'])} ago")

    def _replyStale(self, irc, channel, items, days, title):
        """Replies with the entries that haven't caught anyone in `days`
        days (never-hit entries count from when they were added), least
        recently active first, pasting the list when it's long."""
        now = time.time()
        cutoff = now - days * 86400
        stale = sorted(((e.get('last_hit') or e['created_at'], m, e)
                        for m, e in items
                        if (e.get('last_hit') or e['created_at']) <= cutoff),
                       key=lambda t: t[0])
        if not stale:
            irc.reply(f"Every entry has caught someone in the last {days} days.")
            return
        lines = []
        for _, m, e in stale:
            seen = f"last hit {self._ago(now - e['last_hit'])} ago" \
                if e.get('last_hit') else "never hit"
            lines.append(f"[{e['id']}] {m} ({seen}, added "
                         f"{self._ago(now - e['created_at'])} ago)")
        if len(lines) > (self.registryValue('maxInlineEntries', channel) or 5):
            text = f"{title} ({len(lines)} entries):\n" + "=" * 45 + "\n"
            text += "".join(line + "\n" for line in lines)
            url = self._createPastebin(channel, text)
            irc.reply(f"{len(lines)} stale entries. View here: {url}")
        else:
            irc.reply(" | ".join(lines))

    # -----------------------------------------------------------------
    # Expiry scheduling
    # -----------------------------------------------------------------

    def _event_name(self, scope, channel, entry_id):
        ch = channel.lower() if channel else '-'
        return f"Blacklist:{scope}:{ch}:{entry_id}"

    def _schedule_expiry(self, network, scope, channel, entry_id, expire_at, mode):
        if not expire_at or not mode:
            return
        name = self._event_name(scope, channel, entry_id)
        try:
            schedule.addEvent(self._fire_expiry, expire_at, name=name,
                               args=(network, scope, channel, entry_id, mode))
        except AssertionError:
            # Already scheduled (e.g. plugin reload); leave the existing timer.
            pass

    def _unschedule(self, scope, channel, entry_id):
        name = self._event_name(scope, channel, entry_id)
        try:
            schedule.removeEvent(name)
        except KeyError:
            pass

    def _reschedule_all(self, irc):
        """Restores expiry timers lost across a bot restart. The DB is the
        source of truth for expire_at/expire_mode; schedule.addEvent() only
        lives in memory, so every load must repopulate it."""
        now = time.time()
        network = irc.network
        for c_lower, bucket in list(self.db['channels'].items()):
            for mask, e in list(bucket['entries'].items()):
                expire_at = e.get('expire_at')
                mode = e.get('expire_mode')
                if not expire_at or not mode:
                    continue
                if expire_at <= now:
                    self._fire_expiry(network, 'channel', c_lower, e['id'], mode)
                else:
                    self._schedule_expiry(network, 'channel', c_lower, e['id'], expire_at, mode)
        for mask, e in list(self.db['net']['entries'].items()):
            expire_at = e.get('expire_at')
            mode = e.get('expire_mode')
            if not expire_at or not mode:
                continue
            if expire_at <= now:
                self._fire_expiry(network, 'net', None, e['id'], mode)
            else:
                self._schedule_expiry(network, 'net', None, e['id'], expire_at, mode)

    def _fire_expiry(self, network, scope, channel, entry_id, mode):
        irc = world.getIrc(network) if network else None
        if irc is None and world.ircs:
            irc = world.ircs[0]

        mask = None
        with self._db_lock:
            if scope == 'channel':
                bucket = self.db['channels'].get(channel.lower()) if channel else None
            else:
                bucket = self.db['net']
            if bucket:
                for m, e in bucket['entries'].items():
                    if e['id'] == entry_id:
                        mask = m
                        break
                if mask and mode == 'full':
                    del bucket['entries'][mask]
                    self._dbWrite()
                elif mask and mode == 'irc_only':
                    # The +b is lifted but the entry stays; nothing is pending
                    # any more. Clearing this keeps a reload from re-sending
                    # the UNBAN (and lifting a ban re-applied meanwhile), and
                    # stops `list` showing a stale "[expiring...]".
                    entry = bucket['entries'][mask]
                    entry['expire_at'] = None
                    entry['expire_mode'] = None
                    entry['lifted'] = True
                    self._dbWrite()

        if not mask or irc is None:
            return
        if scope == 'channel':
            irc.queueMsg(ircmsgs.unban(channel, mask))
        else:
            for chan in list(irc.state.channels.keys()):
                irc.queueMsg(ircmsgs.unban(chan, mask))

    def _rearm_irc_lift(self, irc, channel, mask, entry):
        """An entry's +b was just re-applied on join, so it is no longer
        'lifted'. For bot-added entries also arm a fresh banlistExpiry lift,
        the same way `add` does, so the ban doesn't outlive banlistExpiry.
        Timed ('full') entries keep their own timer, and manual-ban entries
        are never lifted by this path."""
        expiry = self.registryValue('banlistExpiry', channel)
        rearm = entry.get('is_bot_cmd') and entry.get('expire_mode') != 'full'
        expire_at = time.time() + (expiry * 60) if rearm and expiry > 0 else None
        mode = 'irc_only' if expire_at else None
        with self._db_lock:
            live = (self.db['channels'].get(channel.lower()) or {}) \
                .get('entries', {}).get(mask)
            if live is None:
                return
            live['lifted'] = False
            if rearm:
                live['expire_at'] = expire_at
                live['expire_mode'] = mode
            self._dbWrite()
        if not rearm:
            return
        self._unschedule('channel', channel, entry['id'])
        if expire_at:
            self._schedule_expiry(irc.network, 'channel', channel, entry['id'],
                                  expire_at, mode)

    # -----------------------------------------------------------------
    # Mask creation & pastebin
    # -----------------------------------------------------------------

    def _createMask(self, irc, target, num):
        """A full nick!user@host is used as given. A nick the bot can see is
        resolved to its real hostmask through the banmask template `num`.
        Anything else is completed the way Eggdrop's +ban does
        (see _completeMask), or None if it can't be."""
        if ircutils.isUserHostmask(target):
            return target if target.isascii() else None
        try:
            hostmask = irc.state.nickToHostmask(target)
        except KeyError:
            return self._completeMask(target)
        try:
            nick, ident, host = ircutils.splitHostmask(hostmask)
            template = self.banmasks.get(num, self.banmasks[2])
            mask = template.replace("nick", nick).replace("ident", ident).replace("host", host)
        except Exception:
            return None
        return mask if mask.isascii() else None

    def _createNetMask(self, irc, target):
        return self._createMask(irc, target, self.registryValue('netMaskNumber'))

    def _createPastebin(self, channel, content):
        """Uploads content to the configured paste service."""
        try:
            api_url = self.registryValue('pastebinUrl', channel)
            field = self.registryValue('pastebinField', channel)
            boundary = '----SupybotBlacklist'
            body = (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="{field}"; filename="banlist.txt"\r\n'
                f'Content-Type: text/plain\r\n\r\n'
                + content +
                f'\r\n--{boundary}--\r\n'
            ).encode('utf-8')
            req = urllib.request.Request(api_url, data=body, method='POST')
            req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.read().decode('utf-8').strip()
        except Exception as e:
            logger.error(f"Pastebin upload failed: {e}")
            return "Error: Pastebin service unavailable."

    def _kickMatching(self, irc, channel, mask, reason, exempt):
        """Kicks every member of `channel` whose hostmask matches `mask` (the
        enforce-bans behavior), except the bot itself and anything the
        `exempt(hostmask)` callable protects. Returns the nicks kicked."""
        kicked = self._matchingMembers(irc, channel, mask, exempt)
        for nick in kicked:
            irc.queueMsg(ircmsgs.kick(channel, nick, reason))
        return kicked

    def _enforceNet(self, irc, mask, reason):
        """Applies a network-blacklist mask across every channel that has
        enforceGlobal on, banning it and kicking every matching member.
        Returns (reached, skipped, full): [(channel, bot_has_ops)] for the
        channels it was applied in, the channels with enforceGlobal off, and
        the channels whose ban list was full (kicked there, but no +b)."""
        reached, skipped, full = [], [], []
        hits = 0
        for chan in list(irc.state.channels.keys()):
            if not self.registryValue('enforceGlobal', chan):
                skipped.append(chan)
                continue
            if not self._hasRoom(irc, chan, mask):
                full.append(chan)
            else:
                irc.queueMsg(ircmsgs.ban(chan, mask))
            hits += len(self._kickMatching(irc, chan, mask, reason, self._isExemptNet))
            state = irc.state.channels[chan]
            reached.append((chan, state.isOp(irc.nick) or state.isHalfop(irc.nick)))
        if hits:
            self._recordHit('net', None, mask, hits)
        return reached, skipped, full

    def _netTooBroad(self, irc, mask):
        """_tooBroad across every channel enforcing the network blacklist."""
        for chan in list(irc.state.channels.keys()):
            if self.registryValue('enforceGlobal', chan):
                err = self._tooBroad(irc, chan, mask, self._isExemptNet)
                if err:
                    return err
        return None

    def _guardNewNet(self, irc, mask, expire_at, force):
        """_guardNew for the network blacklist. Returns (error, note)."""
        if force:
            return None, ""
        err = self._netTooBroad(irc, mask)
        if err:
            return err, ""
        with self._db_lock:
            items = list(self.db['net']['entries'].items())
        covering, covered = self._coverage(items, mask, expire_at)
        if covering:
            m, e = covering
            return (f"{mask} is already covered by network entry [{e['id']}] "
                    f"{m}. Add --force to store it anyway."), ""
        return None, self._coveredNote(covered)

    def _netReachText(self, reached, skipped, full=(), limit=8):
        """One line saying where a network ban landed: the channels it was
        applied in and those where the bot has no op (so it won't take).
        Channels with enforceGlobal off are only mentioned when that leaves
        the ban enforced nowhere, and full ban lists are always mentioned."""
        def capped(names):
            text = ", ".join(names[:limit])
            return text + (f" and {len(names) - limit} more" if len(names) > limit else "")
        parts = []
        opped = [c for c, has_op in reached if has_op]
        no_op = [c for c, has_op in reached if not has_op]
        if opped:
            parts.append(f"Banned in {capped(opped)}.")
        if no_op and not opped:
            parts.append("I'm not op in any channel, so it won't be applied anywhere.")
        elif no_op:
            parts.append(f"I'm not op in {capped(no_op)}, so it won't be applied there.")
        if not reached:
            if skipped:
                n = len(skipped)
                parts.append("Not enforced anywhere yet: enforceGlobal is off in "
                             f"{n} channel{'s' if n != 1 else ''}.")
            else:
                parts.append("Not enforced anywhere yet.")
        if full:
            parts.append(f"The ban list is full in {capped(list(full))}, "
                         "so matching users are only kicked there.")
        return " ".join(parts)

    def _resyncBans(self, irc, channel):
        """Re-applies stored bans that are missing from the channel's ban
        list and kicks the members they match (Eggdrop's recheck_bans). Runs
        when the bot gains ops, or finishes joining already opped. Entries
        that were lifted on purpose (banlistExpiry, or an op's manual -b)
        are left alone: they come back on the next matching join.
        If the ban list can't take them all, the most recently active
        entries win and the rest are marked lifted, to return on join."""
        try:
            state = irc.state.channels[channel]
        except KeyError:
            return
        if not (state.isOp(irc.nick) or state.isHalfop(irc.nick)):
            return
        present = {b.lower() for b in state.bans}
        # mask.lower() -> (mask, kick reason, exempt check, scope, entry)
        wanted = {}
        if self.registryValue('enabled', channel):
            with self._db_lock:
                bucket = self.db['channels'].get(channel.lower())
                items = list(bucket['entries'].items()) if bucket else []
            for mask, e in items:
                if not e.get('lifted'):
                    wanted[mask.lower()] = (
                        mask, e['reason'],
                        lambda hm: self._isExempt(channel, hm), 'channel', e)
        if self.registryValue('enforceGlobal', channel):
            with self._db_lock:
                net_items = list(self.db['net']['entries'].items())
            for mask, e in net_items:
                wanted.setdefault(mask.lower(), (
                    mask, e['reason'] or "Network-wide ban.", self._isExemptNet,
                    'net', e))
        todo = [w for k, w in wanted.items()
                if k not in present and not self._looksLikeExtban(w[0])
                and not self._isSelfBan(irc, w[0])]
        room = self._banRoom(irc, channel)
        if room is not None and len(todo) > room:
            todo.sort(key=lambda w: w[4].get('last_hit') or w[4]['created_at'],
                      reverse=True)
            todo, dropped = todo[:room], todo[room:]
            logger.warning(f"Blacklist: {channel}'s ban list is full; "
                           f"{len(dropped)} stored ban(s) not re-applied.")
            with self._db_lock:
                for mask, _, _, scope, e in dropped:
                    if scope == 'channel':
                        e['lifted'] = True
                self._dbWrite()
        for m in self._modeMsgs(irc, channel, [w[0] for w in todo]):
            irc.queueMsg(m)
        for mask, reason, exempt, scope, _ in todo:
            kicked = self._kickMatching(irc, channel, mask, reason, exempt)
            if kicked:
                self._recordHit(scope, channel, mask, len(kicked))

    # -----------------------------------------------------------------
    # Commands
    # -----------------------------------------------------------------

    def bantype(self, irc, msg, args):
        """Lists available mask types."""
        m = [f"({k}) {v}" for k, v in self.banmasks.items()]
        irc.reply(" | ".join(m[0:4]))
        irc.reply(" | ".join(m[4:8]))
        irc.reply(" | ".join(m[8:11]))
    bantype = wrap(bantype, ['admin'])

    def _guardNew(self, irc, channel, mask, expire_at, force):
        """Checks a new channel entry against the ones already stored and
        the people in the channel. Returns (error, note): refuse with
        `error` if set, else append `note` to the success reply."""
        if force:
            return None, ""
        exempt = lambda hm: self._isExempt(channel, hm)
        err = self._tooBroad(irc, channel, mask, exempt)
        if err:
            return err, ""
        bucket = self._get_channel_bucket(channel)
        with self._db_lock:
            items = list(bucket['entries'].items()) if bucket else []
        covering, covered = self._coverage(items, mask, expire_at)
        if covering:
            m, e = covering
            return (f"{mask} is already covered by [{e['id']}] {m}. "
                    "Add --force to store it anyway."), ""
        return None, self._coveredNote(covered)

    def _applyBan(self, irc, channel, mask, reason, exempt):
        """Sets the +b for a just-stored channel entry and kicks whoever it
        matches. If the ban list is full the +b is skipped and the entry
        marked lifted (it returns on the next matching join), unless
        rotateBans can lift an older one to make room. Returns a reply
        note."""
        note = ""
        full = self._banRoom(irc, channel) == 0
        lifted = self._makeRoom(irc, channel, mask) if full else None
        if lifted:
            old, released = lifted
            note = (f" {channel}'s ban list was full, so I " + (
                f"released timed ban {old} early to make room." if released else
                f"lifted {old} to make room (it comes back on a matching join)."))
        if full and not lifted:
            with self._db_lock:
                bucket = self.db['channels'].get(channel.lower())
                e = bucket['entries'].get(mask) if bucket else None
                if e is not None:
                    e['lifted'] = True
                    self._dbWrite()
            note = (f" {channel}'s ban list is full, so I couldn't set the "
                    "+b; it's stored, and matching users are kicked on join.")
        else:
            irc.queueMsg(ircmsgs.ban(channel, mask))
        kicked = self._kickMatching(irc, channel, mask, reason, exempt)
        if kicked:
            self._recordHit('channel', channel, mask, len(kicked))
        return note

    def add(self, irc, msg, args, channel, optlist, target, reason):
        """[<channel>] [--force] <nick|mask> [<reason>]
        Adds a mask to the blacklist (Permanent in DB, temporary +b in IRC).
        Refuses a mask matching more people than maxBanMatches, or one an
        existing entry already covers, unless --force is given.
        """
        if not self._isKnownNick(irc, target) and self._completeMask(target) is None:
            irc.error("The banmask specified is incorrect. It must be in "
                      "the format of nick!user@host (ASCII only).")
            return
        mask = self._createMask(irc, target, self.registryValue('maskNumber', channel))
        if not mask:
            irc.error("Could not create hostmask.")
            return
        if self._isSelfBan(irc, mask):
            self._refuseSelfBan(irc, msg, channel)
            return
        real_hostmask = self._resolveHostmask(irc, target)
        if self._isExempt(channel, real_hostmask or mask):
            irc.error("That hostmask is exempt from the blacklist.")
            return
        reason = reason or self.registryValue('banReason', channel)
        # The entry itself is permanent; only its +b is lifted on a timer.
        err, note = self._guardNew(irc, channel, mask, None, dict(optlist).get('force'))
        if err:
            irc.error(err)
            return

        expiry = self.registryValue('banlistExpiry', channel)
        expire_at = time.time() + (expiry * 60) if expiry > 0 else None
        mode = 'irc_only' if expire_at else None

        entry_id = self._internal_add(channel, mask, msg.nick, reason, is_bot_cmd=True,
                                       expire_at=expire_at, expire_mode=mode)
        note += self._applyBan(irc, channel, mask, reason,
                               lambda hm: self._isExempt(channel, hm))

        if expire_at:
            self._schedule_expiry(irc.network, 'channel', channel, entry_id, expire_at, mode)

        irc.replySuccess(note.strip())
    add = wrap(add, [('checkChannelCapability', 'op'), 'channel', getopts({'force': ''}),
                     'somethingWithoutSpaces', optional('text')])

    def delete(self, irc, msg, args, channel, target):
        """[<channel>] <mask|ID>
        Removes a mask by its string or its ID number from the list.
        """
        bucket = self._get_channel_bucket(channel)
        mask = self._resolve(bucket, target)
        if not mask:
            irc.error(f"Ban not found for: {target}")
            return

        entry_id = bucket['entries'][mask]['id']
        self._internal_del(channel, mask)
        irc.queueMsg(ircmsgs.unban(channel, mask))
        self._unschedule('channel', channel, entry_id)
        irc.replySuccess()
    delete = wrap(delete, [('checkChannelCapability', 'op'), 'channel', 'somethingWithoutSpaces'])

    def timer(self, irc, msg, args, channel, optlist, target, minutes, reason):
        """[<channel>] [--force] <nick|mask> [<minutes>] [<reason>]
        Applies a temporary ban. If minutes are not provided, uses banTimerExpiry.
        --force skips the maxBanMatches and already-covered checks, as in add.
        """
        if not self._isKnownNick(irc, target) and self._completeMask(target) is None:
            irc.error("The banmask specified is incorrect. It must be in "
                      "the format of nick!user@host (ASCII only).")
            return
        mask = self._createMask(irc, target, self.registryValue('maskNumber', channel))
        if not mask:
            irc.error("Could not create hostmask.")
            return
        if self._isSelfBan(irc, mask):
            self._refuseSelfBan(irc, msg, channel)
            return
        real_hostmask = self._resolveHostmask(irc, target)
        if self._isExempt(channel, real_hostmask or mask):
            irc.error("That hostmask is exempt from the blacklist.")
            return

        if minutes is None:
            minutes = self.registryValue('banTimerExpiry', channel)
            if minutes <= 0:
                irc.error("Please specify minutes or set a default banTimerExpiry > 0.")
                return

        db_reason = reason or ""
        kick_reason = reason or "Temporary ban"
        expire_at = time.time() + (minutes * 60)
        err, note = self._guardNew(irc, channel, mask, expire_at, dict(optlist).get('force'))
        if err:
            irc.error(err)
            return

        entry_id = self._internal_add(channel, mask, msg.nick, db_reason, is_bot_cmd=True,
                                       expire_at=expire_at, expire_mode='full')
        note += self._applyBan(irc, channel, mask, kick_reason,
                               lambda hm: self._isExempt(channel, hm))

        self._schedule_expiry(irc.network, 'channel', channel, entry_id, expire_at, 'full')
        irc.replySuccess(note.strip())
    timer = wrap(timer, [('checkChannelCapability', 'op'), 'channel', getopts({'force': ''}),
                         'somethingWithoutSpaces', optional('positiveInt'), optional('text')])

    def reason(self, irc, msg, args, channel, target, newreason):
        """[<channel>] <mask|ID> <reason>
        Updates the stored reason for an existing blacklist entry.
        """
        bucket = self._get_channel_bucket(channel)
        mask = self._resolve(bucket, target)
        if not mask:
            irc.error(f"Ban not found for: {target}")
            return
        with self._db_lock:
            bucket['entries'][mask]['reason'] = newreason
            self._dbWrite()
        irc.replySuccess()
    reason = wrap(reason, [('checkChannelCapability', 'op'), 'channel', 'somethingWithoutSpaces', 'text'])

    def extend(self, irc, msg, args, channel, target, minutes):
        """[<channel>] <mask|ID> <minutes>
        Sets/extends the expiry of a blacklist entry to <minutes> from now.
        The mask is fully removed (IRC ban lifted + entry deleted) when it expires.
        """
        bucket = self._get_channel_bucket(channel)
        mask = self._resolve(bucket, target)
        if not mask:
            irc.error(f"Ban not found for: {target}")
            return

        with self._db_lock:
            entry = bucket['entries'][mask]
            entry_id = entry['id']
            expire_at = time.time() + (minutes * 60)
            entry['expire_at'] = expire_at
            entry['expire_mode'] = 'full'
            self._dbWrite()

        self._unschedule('channel', channel, entry_id)
        self._schedule_expiry(irc.network, 'channel', channel, entry_id, expire_at, 'full')
        irc.reply(f"Expiry for {mask} set to {minutes} minutes from now.")
    extend = wrap(extend, [('checkChannelCapability', 'op'), 'channel', 'somethingWithoutSpaces', 'positiveInt'])

    def search(self, irc, msg, args, channel, pattern):
        """[<channel>] <pattern>
        Searches the channel's blacklist for entries whose mask, adder or
        reason contain <pattern> (case-insensitive).
        """
        bucket = self._get_channel_bucket(channel)
        results = self._search_bucket(bucket, pattern)
        irc.reply(" | ".join(results) if results else "No matching entries found.")
    search = wrap(search, [('checkChannelCapability', 'op'), 'channel', 'text'])

    def clear(self, irc, msg, args, channel, confirm):
        """<channel> confirm
        Wipes the ENTIRE blacklist for <channel> and lifts every ban it applied.
        You must literally pass the word "confirm".
        """
        if confirm.lower() != 'confirm':
            irc.error('This removes every entry for the channel. Re-run as: clear <channel> confirm')
            return

        bucket = self._get_channel_bucket(channel)
        with self._db_lock:
            if not bucket or not bucket['entries']:
                irc.reply("List is already empty.")
                return
            masks = list(bucket['entries'].items())
            bucket['entries'] = {}
            self._dbWrite()

        for m in self._modeMsgs(irc, channel, [mask for mask, _ in masks], unban=True):
            irc.queueMsg(m)
        for mask, e in masks:
            self._unschedule('channel', channel, e['id'])
        irc.reply(f"Cleared {len(masks)} entries from {channel}.")
    clear = wrap(clear, [('checkChannelCapability', 'op'), 'channel', 'somethingWithoutSpaces'])

    def stats(self, irc, msg, args, channel):
        """[<channel>]"""
        bucket = self._get_channel_bucket(channel)
        with self._db_lock:
            entries = list(bucket['entries'].values()) if bucket else []
        count = len(entries)
        net_count = len(self.db['net']['entries'])
        text = (f"Channel {channel} has {count} bans in the blacklist "
                f"({net_count} in the network blacklist).")
        never = sum(1 for e in entries if not e.get('hits'))
        if count:
            text += f" {never} of them never caught anyone."
        room = self._banRoom(irc, channel)
        if room is not None:
            used = len(irc.state.channels[channel].bans)
            text += f" Channel ban list: {used}/{used + room}."
        irc.reply(text)
    stats = wrap(stats, [('checkChannelCapability', 'op'), 'channel'])

    def stale(self, irc, msg, args, channel, days):
        """[<channel>] [<days>]
        Lists the entries that haven't caught anyone in <days> days (default
        30), oldest first; entries that never have count from when they were
        added. Candidates to delete to keep the channel's ban list short.
        """
        bucket = self._get_channel_bucket(channel)
        with self._db_lock:
            items = list(bucket['entries'].items()) if bucket else []
        self._replyStale(irc, channel, items, days or 30,
                         f"Stale bans for {channel} (no hits in {days or 30} days)")
    stale = wrap(stale, [('checkChannelCapability', 'op'), 'channel', optional('positiveInt')])

    def list(self, irc, msg, args, channel):
        """[<channel>]
        Lists all blacklisted masks with elapsed and remaining time.
        """
        bucket = self._get_channel_bucket(channel)
        with self._db_lock:
            items = list(bucket['entries'].items()) if bucket else []
        if not items:
            irc.reply("List is empty.")
            return

        ban_count = len(items)
        max_inline = self.registryValue('maxInlineEntries', channel) or 5
        output_list = []
        full_text = f"Numbered Ban List for {channel} ({ban_count} entries):\n" + "="*45 + "\n"
        now = time.time()

        for m, e in items:
            entry_id = e['id']
            adder = e['adder']
            created_at = e['created_at']
            reason = e['reason']
            expire_at = e.get('expire_at')
            expire_mode = e.get('expire_mode')

            elapsed = self._ago(now - created_at)
            remaining_str = ""

            if expire_at:
                rem = int(expire_at - now) // 60
                if rem > 0:
                    tag = "IRC ban lifts" if expire_mode == 'irc_only' else "expires"
                    remaining_str = f" [{tag} in {rem}m]"
                else:
                    remaining_str = " [expiring...]"

            reason_display = ""
            if reason and reason not in ["Temporary ban", "*manual ban", ""]:
                reason_display = f": {reason}"
            elif reason == "*manual ban":
                reason_display = " [manual]"

            entry = (f"[{entry_id}] {m} ({elapsed} ago by {adder}{self._hitText(e, now)})"
                     f"{remaining_str}{reason_display}")
            output_list.append(entry)
            full_text += entry + "\n"

        if ban_count > max_inline:
            url = self._createPastebin(channel, full_text)
            irc.reply(f"Ban list too large ({ban_count} entries). View here: {url}")
        else:
            irc.reply(" | ".join(output_list))

    list = wrap(list, [('checkChannelCapability', 'op'), 'channel'])

    def kick(self, irc, msg, args, channel, nick, reason):
        """[<channel>] <nick> [<reason>]"""
        if nick not in irc.state.channels[channel].users:
            irc.error(f"{nick} is not in the channel.")
            return
        reason = reason or "Kicked by an operator."
        irc.queueMsg(ircmsgs.kick(channel, nick, reason))
    kick = wrap(kick, [('checkChannelCapability', 'op'), 'channel', 'nick', optional('text')])

    # -----------------------------------------------------------------
    # Per-channel exemption list
    # -----------------------------------------------------------------

    class exempt(callbacks.Commands):
        """Manages hostmasks that this channel's blacklist will never touch.
        Masks are appended one at a time, and can be grouped under a name
        (usually a nick) so one person can carry several."""

        plugin = None

        def add(self, irc, msg, args, channel, first, second):
            """[<channel>] <nick> <hostmask> | [<channel>] <hostmask>
            Adds <hostmask> to this channel's exempt list (appended, never
            replacing), optionally filed under <nick>: `add`, `timer` and
            auto-detected manual bans refuse to blacklist a hostmask matching
            it, and joins matching it are left alone.
            """
            p = self.plugin
            with p._db_lock:
                store = p._ensure_channel_bucket(channel)
            err = p._exemptAdd(store, first, second)
            irc.error(err) if err else irc.replySuccess()
        add = wrap(add, [('checkChannelCapability', 'op'), 'channel',
                         'somethingWithoutSpaces', optional('somethingWithoutSpaces')])

        def remove(self, irc, msg, args, channel, first, second):
            """[<channel>] <nick> [<hostmask>] | [<channel>] <hostmask>
            Removes <hostmask> from the exempt list, or, given only a <nick>,
            every mask filed under that name.
            """
            p = self.plugin
            bucket = p._get_channel_bucket(channel)
            err = p._exemptRemove(bucket, first, second) if bucket \
                else "This channel has no exempt list."
            irc.error(err) if err else irc.replySuccess()
        remove = wrap(remove, [('checkChannelCapability', 'op'), 'channel',
                               'somethingWithoutSpaces', optional('somethingWithoutSpaces')])

        def list(self, irc, msg, args, channel, label):
            """[<channel>] [<nick>]
            Lists the exempt masks, grouped by name, or just <nick>'s masks.
            """
            p = self.plugin
            p._replyExemptList(irc, p._get_channel_bucket(channel) or {}, channel,
                               f"Exempt masks for {channel}", label,
                               "No exempt masks for this channel.")
        list = wrap(list, [('checkChannelCapability', 'op'), 'channel',
                           optional('somethingWithoutSpaces')])

    # -----------------------------------------------------------------
    # Network-wide blacklist
    # -----------------------------------------------------------------

    class net(callbacks.Commands):
        """The network-wide blacklist: entries here are enforced in every
        channel currently enforcing it (see the enforceGlobal config)."""

        plugin = None

        def add(self, irc, msg, args, optlist, target, reason):
            """[--force] <nick|hostmask> [<reason>]
            Adds <nick|hostmask> to the network-wide blacklist and immediately
            bans/kicks it in every channel currently enforcing it. Refuses a
            mask matching more people than a channel's maxBanMatches, or one
            an existing network entry already covers, unless --force is given.
            """
            p = self.plugin
            if not p._isKnownNick(irc, target) and p._completeMask(target) is None:
                irc.error("The banmask specified is incorrect. It must be in "
                          "the format of nick!user@host (ASCII only).")
                return
            mask = p._createNetMask(irc, target)
            if not mask:
                irc.error("Could not create hostmask.")
                return
            if p._isSelfBan(irc, mask):
                p._refuseSelfBan(irc, msg)
                return
            real_hostmask = p._resolveHostmask(irc, target)
            if p._isExemptNet(real_hostmask or mask):
                irc.error("That hostmask is exempt from the network blacklist.")
                return
            reason = reason or "Network-wide ban."
            err, note = p._guardNewNet(irc, mask, None, dict(optlist).get('force'))
            if err:
                irc.error(err)
                return
            p._net_add(mask, msg.nick, reason)
            reached, skipped, full = p._enforceNet(irc, mask, reason)
            irc.reply("Added to the network blacklist. " +
                      p._netReachText(reached, skipped, full) + note)
        add = wrap(add, ['admin', getopts({'force': ''}), 'somethingWithoutSpaces',
                         optional('text')])

        def delete(self, irc, msg, args, target):
            """<mask|ID>"""
            p = self.plugin
            bucket = p.db['net']
            mask = p._resolve(bucket, target)
            if not mask:
                irc.error(f"Not found in the network blacklist: {target}")
                return
            entry_id = bucket['entries'][mask]['id']
            with p._db_lock:
                del bucket['entries'][mask]
                p._dbWrite()
            for chan in list(irc.state.channels.keys()):
                irc.queueMsg(ircmsgs.unban(chan, mask))
            p._unschedule('net', None, entry_id)
            irc.replySuccess()
        delete = wrap(delete, ['admin', 'somethingWithoutSpaces'])

        def timer(self, irc, msg, args, optlist, target, minutes, reason):
            """[--force] <nick|hostmask> [<minutes>] [<reason>]
            Applies a temporary network-wide ban. If minutes are not provided,
            uses netTimerExpiry. --force skips the maxBanMatches and
            already-covered checks, as in net add.
            """
            p = self.plugin
            if not p._isKnownNick(irc, target) and p._completeMask(target) is None:
                irc.error("The banmask specified is incorrect. It must be in "
                          "the format of nick!user@host (ASCII only).")
                return
            mask = p._createNetMask(irc, target)
            if not mask:
                irc.error("Could not create hostmask.")
                return
            if p._isSelfBan(irc, mask):
                p._refuseSelfBan(irc, msg)
                return
            real_hostmask = p._resolveHostmask(irc, target)
            if p._isExemptNet(real_hostmask or mask):
                irc.error("That hostmask is exempt from the network blacklist.")
                return

            if minutes is None:
                minutes = p.registryValue('netTimerExpiry')
                if minutes <= 0:
                    irc.error("Please specify minutes or set netTimerExpiry > 0.")
                    return

            reason = reason or "Temporary network-wide ban."
            expire_at = time.time() + (minutes * 60)
            err, note = p._guardNewNet(irc, mask, expire_at, dict(optlist).get('force'))
            if err:
                irc.error(err)
                return
            entry_id = p._net_add(mask, msg.nick, reason, expire_at=expire_at, expire_mode='full')
            reached, skipped, full = p._enforceNet(irc, mask, reason)
            p._schedule_expiry(irc.network, 'net', None, entry_id, expire_at, 'full')
            irc.reply(f"Added to the network blacklist for {minutes} minutes. " +
                      p._netReachText(reached, skipped, full) + note)
        timer = wrap(timer, ['admin', getopts({'force': ''}), 'somethingWithoutSpaces',
                             optional('positiveInt'), optional('text')])

        def list(self, irc, msg, args):
            """takes no arguments"""
            p = self.plugin
            with p._db_lock:
                items = list(p.db['net']['entries'].items())
            if not items:
                irc.reply("Network blacklist is empty.")
                return

            now = time.time()
            out = []
            full_text = f"Network Ban List ({len(items)} entries):\n" + "="*45 + "\n"
            for m, e in items:
                elapsed = p._ago(now - e['created_at'])
                remaining_str = ""
                if e.get('expire_at'):
                    rem = int(e['expire_at'] - now) // 60
                    remaining_str = f" [{rem}m left]" if rem > 0 else " [expiring...]"
                entry = (f"[{e['id']}] {m} ({elapsed} ago by {e['adder']}"
                         f"{p._hitText(e, now)}){remaining_str}: {e['reason']}")
                out.append(entry)
                full_text += entry + "\n"

            max_inline = p.registryValue('maxInlineEntries', None) or 5
            if len(items) > max_inline:
                url = p._createPastebin(None, full_text)
                irc.reply(f"Network ban list too large ({len(items)} entries). View here: {url}")
            else:
                irc.reply(" | ".join(out))
        list = wrap(list, ['admin'])

        def search(self, irc, msg, args, pattern):
            """<pattern>"""
            p = self.plugin
            results = p._search_bucket(p.db['net'], pattern)
            irc.reply(" | ".join(results) if results else "No matching entries found.")
        search = wrap(search, ['admin', 'text'])

        def clear(self, irc, msg, args, confirm):
            """confirm
            Wipes the ENTIRE network blacklist. You must literally pass the
            word "confirm".
            """
            p = self.plugin
            if confirm.lower() != 'confirm':
                irc.error('This removes every network-wide entry. Re-run as: net clear confirm')
                return

            bucket = p.db['net']
            with p._db_lock:
                if not bucket['entries']:
                    irc.reply("Network blacklist is already empty.")
                    return
                masks = list(bucket['entries'].items())
                bucket['entries'] = {}
                p._dbWrite()

            for chan in list(irc.state.channels.keys()):
                for m in p._modeMsgs(irc, chan, [mask for mask, _ in masks], unban=True):
                    irc.queueMsg(m)
            for mask, e in masks:
                p._unschedule('net', None, e['id'])
            irc.reply(f"Cleared {len(masks)} entries from the network blacklist.")
        clear = wrap(clear, ['admin', 'somethingWithoutSpaces'])

        def stale(self, irc, msg, args, days):
            """[<days>]
            Lists the network entries that haven't caught anyone in <days>
            days (default 30), oldest first; entries that never have count
            from when they were added.
            """
            p = self.plugin
            with p._db_lock:
                items = list(p.db['net']['entries'].items())
            p._replyStale(irc, None, items, days or 30,
                          f"Stale network bans (no hits in {days or 30} days)")
        stale = wrap(stale, ['admin', optional('positiveInt')])

        def exemptadd(self, irc, msg, args, first, second):
            """<nick> <hostmask> | <hostmask>
            Adds <hostmask> to the network exempt list (appended, never
            replacing), optionally filed under <nick>.
            """
            p = self.plugin
            err = p._exemptAdd(p.db['net'], first, second)
            irc.error(err) if err else irc.replySuccess()
        exemptadd = wrap(exemptadd, ['admin', 'somethingWithoutSpaces',
                                     optional('somethingWithoutSpaces')])

        def exemptremove(self, irc, msg, args, first, second):
            """<nick> [<hostmask>] | <hostmask>
            Removes <hostmask> from the network exempt list, or, given only a
            <nick>, every mask filed under that name.
            """
            p = self.plugin
            err = p._exemptRemove(p.db['net'], first, second)
            irc.error(err) if err else irc.replySuccess()
        exemptremove = wrap(exemptremove, ['admin', 'somethingWithoutSpaces',
                                           optional('somethingWithoutSpaces')])

        def exemptlist(self, irc, msg, args, label):
            """[<nick>]
            Lists the network exempt masks, grouped by name, or just <nick>'s.
            """
            p = self.plugin
            p._replyExemptList(irc, p.db['net'], None, "Network exempt masks",
                               label, "No exempt masks on the network blacklist.")
        exemptlist = wrap(exemptlist, ['admin', optional('somethingWithoutSpaces')])

    # -----------------------------------------------------------------
    # IRC event handlers
    # -----------------------------------------------------------------

    def doMode(self, irc, msg):
        """Syncs the DB with manual bans/unbans made directly on IRC."""
        channel = msg.args[0]
        if len(msg.args) < 3 or not ircutils.isChannel(channel):
            return

        # The bot itself being opped (by anyone): re-apply the bans the
        # channel is missing, like Eggdrop's recheck_bans.
        for mode, arg in ircutils.separateModes(msg.args[1:]):
            if mode in ('+o', '+h') and arg and ircutils.strEqual(arg, irc.nick):
                self._resyncBans(irc, channel)
                break

        # A +b matching the bot itself (Eggdrop's got_ban): undo it at once
        # and, if kickOnSelfBan, kick whoever set it. Needs ops to act.
        for mode, arg in ircutils.separateModes(msg.args[1:]):
            if mode == '+b' and arg and self._isSelfBan(irc, arg):
                try:
                    state = irc.state.channels[channel]
                except KeyError:
                    continue
                if state.isOp(irc.nick) or state.isHalfop(irc.nick):
                    irc.queueMsg(ircmsgs.unban(channel, arg))
                    self._reactToSelfBan(irc, msg, channel)

        if ircutils.strEqual(msg.nick, irc.nick):
            return

        mode_change, mask = msg.args[1], msg.args[2]
        c_lower = channel.lower()

        if mode_change in ('+b', '-b') and self._looksLikeExtban(mask):
            # Extban syntax (ircd-specific, e.g. ~account:foo, $a:foo).
            # We never parse or track these -- leave them entirely alone.
            return

        if mode_change == '+b' and self._isSelfBan(irc, mask):
            return  # undone above; never recorded

        if mode_change == '+b':
            # An op re-setting a lifted entry's ban puts it back on the channel.
            with self._db_lock:
                bucket = self.db['channels'].get(c_lower)
                back = bucket['entries'].get(mask) if bucket else None
                if back is not None and back.get('lifted'):
                    back['lifted'] = False
                    self._dbWrite()
            if not self.registryValue('addManualBans', channel):
                return
            if self._isExempt(channel, mask):
                return
            with self._db_lock:
                bucket = self.db['channels'].get(c_lower)
                exists = bucket is not None and mask in bucket['entries']

            if not exists:
                expiry = self.registryValue('banlistExpiry', channel)
                expire_at = time.time() + (expiry * 60) if expiry > 0 else None
                mode = 'full' if expire_at else None

                entry_id = self._internal_add(channel, mask, msg.nick, "*manual ban",
                                               is_bot_cmd=False, expire_at=expire_at,
                                               expire_mode=mode)
                if expire_at:
                    self._schedule_expiry(irc.network, 'channel', channel, entry_id, expire_at, mode)

        elif mode_change == '-b':
            with self._db_lock:
                bucket = self.db['channels'].get(c_lower)
                entry = bucket['entries'].get(mask) if bucket else None

            if entry:
                # Bot-added blacklist entries are kept on disk even if manually
                # unbanned on IRC (they'll be re-applied on next join);
                # manually-added ones are dropped entirely.
                if not entry['is_bot_cmd']:
                    self._internal_del(channel, mask)
                    logger.info(f"Manual unban: {mask} removed from DB (was manual ban)")
                else:
                    # Mark it lifted so a later resync doesn't undo this
                    # deliberate unban; it returns on the next matching join.
                    with self._db_lock:
                        entry['lifted'] = True
                        self._dbWrite()
                    logger.info(f"Manual unban: {mask} kept in DB (is bot blacklist entry)")
                self._unschedule('channel', channel, entry['id'])

    def _enforceMember(self, irc, channel, nick, prefix):
        """Bans and kicks `nick` (whose current hostmask is `prefix`) if the
        network or channel blacklist matches it. Exempts win. Returns True
        if it was enforced."""
        # A full ban list (with nothing to rotate out) still gets the
        # kick, just not the +b.
        if self.registryValue('enforceGlobal', channel) \
                and not self._isExemptNet(prefix):
            with self._db_lock:
                net_items = list(self.db['net']['entries'].items())
            for mask, e in net_items:
                if ircutils.hostmaskPatternEqual(mask, prefix):
                    if self._hasRoom(irc, channel, mask):
                        irc.queueMsg(ircmsgs.ban(channel, mask))
                    irc.queueMsg(ircmsgs.kick(channel, nick, e['reason'] or "Network-wide ban."))
                    self._recordHit('net', None, mask)
                    return True

        if self.registryValue('enabled', channel) \
                and not self._isExempt(channel, prefix):
            with self._db_lock:
                bucket = self.db['channels'].get(channel.lower())
                items = list(bucket['entries'].items()) if bucket else []
            for mask, e in items:
                if ircutils.hostmaskPatternEqual(mask, prefix):
                    banned = self._hasRoom(irc, channel, mask)
                    if banned:
                        irc.queueMsg(ircmsgs.ban(channel, mask))
                    irc.queueMsg(ircmsgs.kick(channel, nick, e['reason']))
                    self._recordHit('channel', channel, mask)
                    if banned:
                        self._rearm_irc_lift(irc, channel, mask, e)
                    return True
        return False

    def doJoin(self, irc, msg):
        if ircutils.strEqual(msg.nick, irc.nick):
            return
        self._enforceMember(irc, msg.args[0], msg.nick, msg.prefix)

    def doNick(self, irc, msg):
        """A nick change can make a member match a nick ban (e.g.
        *cunt*!*@*), so re-check them in every channel they share with the
        bot, like Eggdrop's gotnick -> check_this_member."""
        if not msg.args or ircutils.strEqual(msg.nick, irc.nick):
            return
        newnick = msg.args[0]
        if ircutils.strEqual(newnick, irc.nick):
            return
        try:
            _, user, host = ircutils.splitHostmask(msg.prefix)
        except Exception:
            return
        prefix = ircutils.joinHostmask(newnick, user, host)
        for channel, state in list(irc.state.channels.items()):
            if newnick in state.users:
                self._enforceMember(irc, channel, newnick, prefix)

    def doChghost(self, irc, msg):
        """IRCv3 CHGHOST: a member's user@host changed in place (a vhost or
        cloak on identify, or losing one), so re-check them the way doNick
        does. Without the cap the ircd fakes a quit and rejoin instead,
        which doJoin already covers."""
        if len(msg.args) < 2 or ircutils.strEqual(msg.nick, irc.nick):
            return
        prefix = ircutils.joinHostmask(msg.nick, msg.args[0], msg.args[1])
        for channel, state in list(irc.state.channels.items()):
            if msg.nick in state.users:
                self._enforceMember(irc, channel, msg.nick, prefix)

    def do478(self, irc, msg):
        """ERR_BANLISTFULL: a +b didn't take because the channel's ban list
        is full. Mark the matching channel entry lifted, so it's clear it
        isn't on the channel; like any lifted entry it is tried again on
        the next matching join."""
        if len(msg.args) < 3 or not ircutils.isChannel(msg.args[1]):
            return
        channel, mask = msg.args[1], msg.args[2]
        logger.warning(f"Blacklist: {channel}'s ban list is full; {mask} not set.")
        with self._db_lock:
            bucket = self.db['channels'].get(channel.lower())
            entry = bucket['entries'].get(mask) if bucket else None
            if entry is not None and not entry.get('lifted'):
                entry['lifted'] = True
                self._dbWrite()

    def do368(self, irc, msg):
        """End of the channel ban list, requested by Limnoria on join. If the
        bot already has ops by now, sync the stored bans to the channel."""
        if len(msg.args) >= 2 and ircutils.isChannel(msg.args[1]):
            self._resyncBans(irc, msg.args[1])


Class = Blacklist
