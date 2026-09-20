import json
import os
import re
import time
import threading
import fnmatch
import logging
import urllib.request
from supybot.commands import *
from supybot import callbacks, conf, ircmsgs, ircutils, schedule, world

try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('Blacklist')
except ImportError:
    _ = lambda x: x

logger = logging.getLogger('supybot.plugins.Blacklist')

# Word-filter escalation ladder. A word entry's -action chain must list a
# strictly increasing subsequence of this tuple (by index) -- e.g.
# "kick,kickban" is valid, "kickban,kick" is rejected, since a later
# offense can never be milder than an earlier one.
WORD_ACTIONS = ('warn', 'kick', 'ban', 'kickban')


class Blacklist(callbacks.Plugin):
    """Manages channel security with a numbered blacklist and ID-based deletion,
    an optional network-wide blacklist enforced across every channel, and an
    optional word/text filter with an escalating warn/kick/ban/kickban ladder."""

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
        # Nested command groups (self.exempt / self.net / self.word) are
        # instantiated by BasePlugin.__init__ above but have no reference to
        # this instance's DB, so we hand them one explicitly.
        self.exempt.plugin = self
        self.net.plugin = self
        self.word.plugin = self
        # Word-filter offense counters: transient, in-memory only (not
        # persisted -- like eggdrop/weechat-blacklist's flood-style
        # counters, they're meant to reset on a bot restart).
        # Keyed by (network, channel.lower(), hostmask, entry_id, scope)
        # -> {'count': int, 'last': float}
        self._word_offenses = {}
        self._word_offenses_lock = threading.RLock()
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
            self.db['net'].setdefault('words', {})
            self.db['net'].setdefault('word_next_id', 1)
            for bucket in self.db['channels'].values():
                bucket.setdefault('exempt', [])
                bucket.setdefault('words', {})
                bucket.setdefault('word_next_id', 1)
            self._dbWrite()
        except Exception as e:
            logger.error(f"Error loading DB: {e}")
            self.db = {'channels': {}, 'net': {'next_id': 1, 'entries': {}, 'exempt': [],
                                                'words': {}, 'word_next_id': 1}}

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
                c_lower, {'next_id': 1, 'entries': {}, 'exempt': [],
                          'words': {}, 'word_next_id': 1})
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
                c_lower, {'next_id': 1, 'entries': {}, 'exempt': [],
                          'words': {}, 'word_next_id': 1})
            existing = bucket['entries'].get(mask)
            entry_id = existing['id'] if existing else bucket['next_id']
            if not existing:
                bucket['next_id'] += 1
            bucket['entries'][mask] = {
                'id': entry_id, 'adder': adder, 'created_at': time.time(),
                'reason': reason, 'is_bot_cmd': is_bot_cmd,
                'expire_at': expire_at, 'expire_mode': expire_mode,
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
    # Word filter: entry storage
    # -----------------------------------------------------------------

    def _validateWordChain(self, raw_actions):
        """Parses a comma-separated -action chain and enforces that it
        strictly escalates through WORD_ACTIONS (warn < kick < ban <
        kickban) -- e.g. "kick,kickban" is fine, "kickban,kick" is not,
        since a later offense can never be milder than an earlier one.
        Returns the parsed list, or raises ValueError with a user-facing
        message."""
        actions = [a.strip().lower() for a in raw_actions.split(',') if a.strip()]
        if not actions:
            raise ValueError("You must specify at least one action.")
        bad = [a for a in actions if a not in WORD_ACTIONS]
        if bad:
            raise ValueError(f"Unknown action(s): {', '.join(bad)}. "
                              f"Must be from: {', '.join(WORD_ACTIONS)}.")
        ranks = [WORD_ACTIONS.index(a) for a in actions]
        if ranks != sorted(ranks) or len(set(ranks)) != len(ranks):
            raise ValueError(f"The action chain must strictly escalate "
                              f"({', '.join(WORD_ACTIONS)}), e.g. "
                              f"'kick,kickban' -- not '{','.join(actions)}'.")
        return actions

    def _wordBucketFor(self, channel):
        """channel=None -> the network-wide word bucket."""
        if channel is None:
            return self.db['net']
        return self._get_channel_bucket(channel)

    def _wordEntriesFor(self, channel):
        """All word entries that apply in `channel`: the channel's own plus
        the network-wide ones, as a flat list of (scope, mask, entry)."""
        out = []
        with self._db_lock:
            bucket = self._get_channel_bucket(channel)
            if bucket:
                out += [('channel', p, e) for p, e in bucket.get('words', {}).items()]
            out += [('net', p, e) for p, e in self.db['net'].get('words', {}).items()]
        return out

    def _word_add(self, channel, pattern, match_type, actions, cooldown_minutes,
                   ban_minutes, reason, adder):
        """channel=None adds to the network-wide word list."""
        with self._db_lock:
            bucket = self._ensure_channel_bucket(channel) if channel else self.db['net']
            bucket.setdefault('words', {})
            bucket.setdefault('word_next_id', 1)
            existing = bucket['words'].get(pattern)
            entry_id = existing['id'] if existing else bucket['word_next_id']
            if not existing:
                bucket['word_next_id'] += 1
            bucket['words'][pattern] = {
                'id': entry_id, 'adder': adder, 'created_at': time.time(),
                'match_type': match_type, 'actions': actions,
                'cooldown_minutes': cooldown_minutes, 'ban_minutes': ban_minutes,
                'reason': reason,
            }
            self._dbWrite()
        return entry_id

    def _word_resolve(self, bucket, token):
        if not bucket:
            return None
        words = bucket.get('words', {})
        if token.isdigit():
            idx = int(token)
            for p, e in words.items():
                if e['id'] == idx:
                    return p
            return None
        return token if token in words else None

    def _word_delete(self, channel, pattern):
        bucket = self._wordBucketFor(channel)
        with self._db_lock:
            if bucket and pattern in bucket.get('words', {}):
                del bucket['words'][pattern]
                self._dbWrite()
                return True
        return False

    # -----------------------------------------------------------------
    # Word filter: matching & escalation
    # -----------------------------------------------------------------

    def _wordMatches(self, pattern, match_type, text, case_sensitive):
        haystack = text if case_sensitive else text.lower()
        needle = pattern if case_sensitive else pattern.lower()
        if match_type == 'regex':
            try:
                return re.search(needle, haystack) is not None
            except re.error:
                return False
        # NB: don't use builtin any() here -- supybot.commands defines its
        # own `any` (a wrap-spec converter) that shadows it via our
        # `from supybot.commands import *` (see _matchesAny's note above).
        has_wildcard = False
        for c in '*?':
            if c in needle:
                has_wildcard = True
                break
        if has_wildcard:
            return fnmatch.fnmatchcase(haystack, needle)
        return needle in haystack

    def _bumpWordOffense(self, network, channel, hostmask, scope, entry_id, cooldown_minutes):
        key = (network, channel.lower(), hostmask.lower(), scope, entry_id)
        now = time.time()
        with self._word_offenses_lock:
            state = self._word_offenses.get(key)
            if state is None or (now - state['last']) > (cooldown_minutes * 60):
                count = 1
            else:
                count = state['count'] + 1
            self._word_offenses[key] = {'count': count, 'last': now}
        return count

    def _resetWordOffense(self, network, channel, hostmask, scope, entry_id):
        key = (network, channel.lower(), hostmask.lower(), scope, entry_id)
        with self._word_offenses_lock:
            self._word_offenses.pop(key, None)

    def _wordBanMask(self, channel, nick, ident, host):
        num = self.registryValue('wordMaskNumber', channel)
        ident = '*' if ident.startswith('~') else ident
        template = self.banmasks.get(num, self.banmasks[2])
        return template.replace("nick", nick).replace("ident", ident).replace("host", host)

    def _doWordAction(self, irc, channel, nick, hostmask, action, reason, pattern):
        """`reason` is the entry's explicit --reason (already sliced to this
        escalation step), or None if it didn't set one -- in which case a
        per-action default is used. "ban" (the bare, non-kicking step) never
        puts a reason anywhere user-visible (no wire mechanism exists for
        one on a plain +b), but it still gets an internal-only DB reason
        (the entry's --reason, or "blacklisted word: <pattern>") so it
        shows up in `blacklist list`/`search` like every other ban instead
        of looking unexplained."""
        try:
            n, ident, host = ircutils.splitHostmask(hostmask)
        except Exception:
            n, ident, host = nick, '*', hostmask

        if action == 'warn':
            tmpl = self.registryValue('wordWarnMessage', channel)
            text = tmpl.replace('$nick', nick).replace('$reason', reason or '')
            irc.queueMsg(ircmsgs.privmsg(channel, text))
            return

        if action == 'kick':
            reason = reason or self.registryValue('wordKickMessage', channel)
            if nick in irc.state.channels[channel].users:
                irc.queueMsg(ircmsgs.kick(channel, nick, reason))
            return

        # ban / kickban: reuse the normal ban-entry machinery (DB record +
        # auto-expiry) so it behaves and lists exactly like any other
        # channel ban.
        if action == 'kickban':
            wire_reason = reason or self.registryValue('wordKickbanMessage', channel)
            db_reason = wire_reason
        else:
            # bare "ban": no kick, no wire-visible reason (there's no such
            # thing for a plain +b in any ircd) -- but still worth a
            # DB-only reason for list/search, so it doesn't look unexplained.
            wire_reason = None
            db_reason = reason or f"blacklisted word: {pattern}"
        mask = self._wordBanMask(channel, n, ident, host)
        minutes = self.registryValue('wordBanExpiry', channel)
        expire_at = time.time() + (minutes * 60)
        entry_id = self._internal_add(channel, mask, irc.nick, db_reason, is_bot_cmd=True,
                                       expire_at=expire_at, expire_mode='full')
        irc.queueMsg(ircmsgs.ban(channel, mask))
        self._schedule_expiry(irc.network, 'channel', channel, entry_id, expire_at, 'full')
        if action == 'kickban' and nick in irc.state.channels[channel].users:
            irc.queueMsg(ircmsgs.kick(channel, nick, wire_reason))

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

        if not mask or irc is None:
            return
        if scope == 'channel':
            irc.queueMsg(ircmsgs.unban(channel, mask))
        else:
            for chan in list(irc.state.channels.keys()):
                irc.queueMsg(ircmsgs.unban(chan, mask))

    # -----------------------------------------------------------------
    # Mask creation & pastebin
    # -----------------------------------------------------------------

    def _createMask(self, irc, target, num):
        if ircutils.isUserHostmask(target): return target
        try:
            hostmask = irc.state.nickToHostmask(target)
            nick, ident, host = ircutils.splitHostmask(hostmask)
            template = self.banmasks.get(num, self.banmasks[2])
            return template.replace("nick", nick).replace("ident", ident).replace("host", host)
        except: return None

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

    def _enforceNet(self, irc, mask, reason, nick_hint=None):
        """Applies a network-blacklist mask across every channel that has
        enforceGlobal on, banning it and kicking any matching nick found."""
        for chan in list(irc.state.channels.keys()):
            if not self.registryValue('enforceGlobal', chan):
                continue
            irc.queueMsg(ircmsgs.ban(chan, mask))
            chan_state = irc.state.channels[chan]
            if nick_hint and nick_hint in chan_state.users:
                irc.queueMsg(ircmsgs.kick(chan, nick_hint, reason))
                continue
            for nick in list(chan_state.users):
                try:
                    hm = irc.state.nickToHostmask(nick)
                except KeyError:
                    continue
                if ircutils.hostmaskPatternEqual(mask, hm):
                    irc.queueMsg(ircmsgs.kick(chan, nick, reason))

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

    def add(self, irc, msg, args, channel, target, reason):
        """[<channel>] <nick|mask> [<reason>]
        Adds a mask to the blacklist (Permanent in DB, temporary +b in IRC).
        """
        if not self._isKnownNick(irc, target) and self._looksLikeExtban(target):
            irc.error("The banmask specified is incorrect. It must be in "
                      "the format of nick!user@host.")
            return
        mask = self._createMask(irc, target, self.registryValue('maskNumber', channel))
        if not mask:
            irc.error("Could not create hostmask.")
            return
        real_hostmask = self._resolveHostmask(irc, target)
        if self._isExempt(channel, real_hostmask or mask):
            irc.error("That hostmask is exempt from the blacklist.")
            return
        reason = reason or self.registryValue('banReason', channel)

        expiry = self.registryValue('banlistExpiry', channel)
        expire_at = time.time() + (expiry * 60) if expiry > 0 else None
        mode = 'irc_only' if expire_at else None

        entry_id = self._internal_add(channel, mask, msg.nick, reason, is_bot_cmd=True,
                                       expire_at=expire_at, expire_mode=mode)
        irc.queueMsg(ircmsgs.ban(channel, mask))

        if not ircutils.isUserHostmask(target) and target in irc.state.channels[channel].users:
            irc.queueMsg(ircmsgs.kick(channel, target, reason))

        if expire_at:
            self._schedule_expiry(irc.network, 'channel', channel, entry_id, expire_at, mode)

        irc.replySuccess()
    add = wrap(add, [('checkChannelCapability', 'op'), 'channel', 'somethingWithoutSpaces', optional('text')])

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

    def timer(self, irc, msg, args, channel, target, minutes, reason):
        """[<channel>] <nick|mask> [<minutes>] [<reason>]
        Applies a temporary ban. If minutes are not provided, uses banTimerExpiry.
        """
        if not self._isKnownNick(irc, target) and self._looksLikeExtban(target):
            irc.error("The banmask specified is incorrect. It must be in "
                      "the format of nick!user@host.")
            return
        mask = self._createMask(irc, target, self.registryValue('maskNumber', channel))
        if not mask:
            irc.error("Could not create hostmask.")
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

        entry_id = self._internal_add(channel, mask, msg.nick, db_reason, is_bot_cmd=True,
                                       expire_at=expire_at, expire_mode='full')
        irc.queueMsg(ircmsgs.ban(channel, mask))

        if not ircutils.isUserHostmask(target) and target in irc.state.channels[channel].users:
            irc.queueMsg(ircmsgs.kick(channel, target, kick_reason))

        self._schedule_expiry(irc.network, 'channel', channel, entry_id, expire_at, 'full')
        irc.replySuccess()
    timer = wrap(timer, [('checkChannelCapability', 'op'), 'channel', 'somethingWithoutSpaces', optional('positiveInt'), optional('text')])

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

        for mask, e in masks:
            irc.queueMsg(ircmsgs.unban(channel, mask))
            self._unschedule('channel', channel, e['id'])
        irc.reply(f"Cleared {len(masks)} entries from {channel}.")
    clear = wrap(clear, [('checkChannelCapability', 'op'), 'channel', 'somethingWithoutSpaces'])

    def stats(self, irc, msg, args, channel):
        """[<channel>]"""
        bucket = self._get_channel_bucket(channel)
        count = len(bucket['entries']) if bucket else 0
        net_count = len(self.db['net']['entries'])
        irc.reply(f"Channel {channel} has {count} bans in the blacklist "
                  f"({net_count} in the network blacklist).")
    stats = wrap(stats, [('checkChannelCapability', 'op'), 'channel'])

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

            elapsed = int(now - created_at) // 60
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

            entry = f"[{entry_id}] {m} ({elapsed}m ago by {adder}){remaining_str}{reason_display}"
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
        """Manages hostmasks that this channel's blacklist will never touch."""

        plugin = None

        def add(self, irc, msg, args, channel, mask):
            """[<channel>] <hostmask>
            Exempts <hostmask> from this channel's blacklist: `add`, `timer`
            and auto-detected manual bans will refuse to blacklist a real
            hostmask matching it.
            """
            if not ircutils.isUserHostmask(mask):
                irc.error("Must be a nick!user@host mask (wildcards allowed).")
                return
            p = self.plugin
            with p._db_lock:
                bucket = p._ensure_channel_bucket(channel)
                if mask not in bucket['exempt']:
                    bucket['exempt'].append(mask)
                    p._dbWrite()
            irc.replySuccess()
        add = wrap(add, [('checkChannelCapability', 'op'), 'channel', 'somethingWithoutSpaces'])

        def remove(self, irc, msg, args, channel, mask):
            """[<channel>] <hostmask>"""
            p = self.plugin
            with p._db_lock:
                bucket = p._get_channel_bucket(channel)
                if bucket and mask in bucket['exempt']:
                    bucket['exempt'].remove(mask)
                    p._dbWrite()
                    irc.replySuccess()
                    return
            irc.error("That mask isn't on this channel's exempt list.")
        remove = wrap(remove, [('checkChannelCapability', 'op'), 'channel', 'somethingWithoutSpaces'])

        def list(self, irc, msg, args, channel):
            """[<channel>]"""
            p = self.plugin
            bucket = p._get_channel_bucket(channel)
            masks = bucket['exempt'] if bucket else []
            irc.reply(", ".join(masks) if masks else "No exempt masks for this channel.")
        list = wrap(list, [('checkChannelCapability', 'op'), 'channel'])

    # -----------------------------------------------------------------
    # Network-wide blacklist
    # -----------------------------------------------------------------

    class net(callbacks.Commands):
        """The network-wide blacklist: entries here are enforced in every
        channel currently enforcing it (see the enforceGlobal config)."""

        plugin = None

        def add(self, irc, msg, args, target, reason):
            """<nick|hostmask> [<reason>]
            Adds <nick|hostmask> to the network-wide blacklist and immediately
            bans/kicks it in every channel currently enforcing it.
            """
            p = self.plugin
            if not p._isKnownNick(irc, target) and p._looksLikeExtban(target):
                irc.error("The banmask specified is incorrect. It must be in "
                          "the format of nick!user@host.")
                return
            mask = p._createNetMask(irc, target)
            if not mask:
                irc.error("Could not create hostmask.")
                return
            real_hostmask = p._resolveHostmask(irc, target)
            if p._isExemptNet(real_hostmask or mask):
                irc.error("That hostmask is exempt from the network blacklist.")
                return
            reason = reason or "Network-wide ban."
            p._net_add(mask, msg.nick, reason)
            nick_hint = target if not ircutils.isUserHostmask(target) else None
            p._enforceNet(irc, mask, reason, nick_hint)
            irc.replySuccess()
        add = wrap(add, ['admin', 'somethingWithoutSpaces', optional('text')])

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

        def timer(self, irc, msg, args, target, minutes, reason):
            """<nick|hostmask> [<minutes>] [<reason>]
            Applies a temporary network-wide ban. If minutes are not provided,
            uses netTimerExpiry.
            """
            p = self.plugin
            if not p._isKnownNick(irc, target) and p._looksLikeExtban(target):
                irc.error("The banmask specified is incorrect. It must be in "
                          "the format of nick!user@host.")
                return
            mask = p._createNetMask(irc, target)
            if not mask:
                irc.error("Could not create hostmask.")
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
            entry_id = p._net_add(mask, msg.nick, reason, expire_at=expire_at, expire_mode='full')
            nick_hint = target if not ircutils.isUserHostmask(target) else None
            p._enforceNet(irc, mask, reason, nick_hint)
            p._schedule_expiry(irc.network, 'net', None, entry_id, expire_at, 'full')
            irc.replySuccess()
        timer = wrap(timer, ['admin', 'somethingWithoutSpaces', optional('positiveInt'), optional('text')])

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
                elapsed = int(now - e['created_at']) // 60
                remaining_str = ""
                if e.get('expire_at'):
                    rem = int(e['expire_at'] - now) // 60
                    remaining_str = f" [{rem}m left]" if rem > 0 else " [expiring...]"
                entry = f"[{e['id']}] {m} ({elapsed}m ago by {e['adder']}){remaining_str}: {e['reason']}"
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
                for mask, e in masks:
                    irc.queueMsg(ircmsgs.unban(chan, mask))
            for mask, e in masks:
                p._unschedule('net', None, e['id'])
            irc.reply(f"Cleared {len(masks)} entries from the network blacklist.")
        clear = wrap(clear, ['admin', 'somethingWithoutSpaces'])

        def exemptadd(self, irc, msg, args, mask):
            """<hostmask>"""
            p = self.plugin
            if not ircutils.isUserHostmask(mask):
                irc.error("Must be a nick!user@host mask (wildcards allowed).")
                return
            with p._db_lock:
                if mask not in p.db['net']['exempt']:
                    p.db['net']['exempt'].append(mask)
                    p._dbWrite()
            irc.replySuccess()
        exemptadd = wrap(exemptadd, ['admin', 'somethingWithoutSpaces'])

        def exemptremove(self, irc, msg, args, mask):
            """<hostmask>"""
            p = self.plugin
            with p._db_lock:
                if mask in p.db['net']['exempt']:
                    p.db['net']['exempt'].remove(mask)
                    p._dbWrite()
                    irc.replySuccess()
                    return
            irc.error("That mask isn't on the network exempt list.")
        exemptremove = wrap(exemptremove, ['admin', 'somethingWithoutSpaces'])

        def exemptlist(self, irc, msg, args):
            """takes no arguments"""
            p = self.plugin
            masks = p.db['net']['exempt']
            irc.reply(", ".join(masks) if masks else "No exempt masks on the network blacklist.")
        exemptlist = wrap(exemptlist, ['admin'])

        # ---------------------------------------------------------
        # Network-wide word filter
        # ---------------------------------------------------------

        def wordadd(self, irc, msg, args, optlist, pattern):
            """[--type simple|regex] --action <chain> [--cooldown <minutes>] [--expiry <minutes>] [--reason <text>] <pattern>
            Adds <pattern> to the network-wide word filter, enforced in
            every channel with wordFilterEnabled on. --action is a
            comma-separated escalation chain that must strictly increase
            through warn < kick < ban < kickban, e.g. "kick,kickban".
            --type simple (default) is a glob/substring match (accepts the
            risk of false positives on substrings); "regex" uses re.search.
            """
            p = self.plugin
            opts = dict(optlist)
            match_type = opts.get('type', 'simple')
            if match_type not in ('simple', 'regex'):
                irc.error("--type must be 'simple' or 'regex'.")
                return
            try:
                actions = p._validateWordChain(opts.get('action', ''))
            except ValueError as e:
                irc.error(str(e))
                return
            cooldown = opts.get('cooldown') or p.registryValue('wordCooldown', None)
            ban_minutes = opts.get('expiry') or p.registryValue('wordBanExpiry', None)
            reason = opts.get('reason')
            entry_id = p._word_add(None, pattern, match_type, actions, cooldown,
                                    ban_minutes, reason, msg.nick)
            irc.reply(f"Network word entry #{entry_id} added: '{pattern}' -> {'>'.join(actions)}.")
        wordadd = wrap(wordadd, ['admin', getopts({'type': 'something', 'action': 'something',
                                                    'cooldown': 'positiveInt', 'expiry': 'positiveInt',
                                                    'reason': 'something'}), 'text'])

        def worddelete(self, irc, msg, args, target):
            """<pattern|ID>"""
            p = self.plugin
            bucket = p.db['net']
            pattern = p._word_resolve(bucket, target)
            if not pattern:
                irc.error(f"Not found in the network word list: {target}")
                return
            p._word_delete(None, pattern)
            irc.replySuccess()
        worddelete = wrap(worddelete, ['admin', 'somethingWithoutSpaces'])

        def wordlist(self, irc, msg, args):
            """takes no arguments"""
            p = self.plugin
            items = list(p.db['net'].get('words', {}).items())
            if not items:
                irc.reply("Network word list is empty.")
                return
            out = [f"[{e['id']}] '{m}' ({e['match_type']}) -> {'>'.join(e['actions'])}" for m, e in items]
            irc.reply(" | ".join(out))
        wordlist = wrap(wordlist, ['admin'])

        def wordsearch(self, irc, msg, args, pattern):
            """<pattern>"""
            p = self.plugin
            needle = pattern.lower()
            out = [f"[{e['id']}] '{m}'" for m, e in p.db['net'].get('words', {}).items()
                   if needle in m.lower()]
            irc.reply(" | ".join(out) if out else "No matching entries found.")
        wordsearch = wrap(wordsearch, ['admin', 'text'])

    # -----------------------------------------------------------------
    # Per-channel word filter
    # -----------------------------------------------------------------

    class word(callbacks.Commands):
        """Manages the channel's word/text filter with an escalating
        warn/kick/ban/kickban ladder per offending hostmask."""

        plugin = None

        def add(self, irc, msg, args, channel, optlist, pattern):
            """[<channel>] [--type simple|regex] --action <chain> [--cooldown <minutes>] [--expiry <minutes>] [--reason <text>] <pattern>
            Adds <pattern> to this channel's word filter. --action is a
            comma-separated escalation chain that must strictly increase
            through warn < kick < ban < kickban, e.g. "kick,kickban" (valid)
            vs "kickban,kick" (rejected). --type simple (default) is a
            glob/substring match -- this accepts the risk of false positives
            on substrings (e.g. "assassin" containing "ass"); use --type
            regex with word boundaries (e.g. "\\bfuck\\b") to avoid that.
            """
            p = self.plugin
            opts = dict(optlist)
            match_type = opts.get('type', 'simple')
            if match_type not in ('simple', 'regex'):
                irc.error("--type must be 'simple' or 'regex'.")
                return
            try:
                actions = p._validateWordChain(opts.get('action', ''))
            except ValueError as e:
                irc.error(str(e))
                return
            cooldown = opts.get('cooldown') or p.registryValue('wordCooldown', channel)
            ban_minutes = opts.get('expiry') or p.registryValue('wordBanExpiry', channel)
            reason = opts.get('reason')
            entry_id = p._word_add(channel, pattern, match_type, actions, cooldown,
                                    ban_minutes, reason, msg.nick)
            irc.reply(f"Word entry #{entry_id} added: '{pattern}' -> {'>'.join(actions)}.")
        add = wrap(add, [('checkChannelCapability', 'op'), 'channel',
                          getopts({'type': 'something', 'action': 'something',
                                   'cooldown': 'positiveInt', 'expiry': 'positiveInt',
                                   'reason': 'something'}), 'text'])

        def delete(self, irc, msg, args, channel, target):
            """[<channel>] <pattern|ID>"""
            p = self.plugin
            bucket = p._get_channel_bucket(channel)
            pattern = p._word_resolve(bucket, target)
            if not pattern:
                irc.error(f"Word entry not found for: {target}")
                return
            p._word_delete(channel, pattern)
            irc.replySuccess()
        delete = wrap(delete, [('checkChannelCapability', 'op'), 'channel', 'somethingWithoutSpaces'])

        def list(self, irc, msg, args, channel):
            """[<channel>]"""
            p = self.plugin
            bucket = p._get_channel_bucket(channel)
            items = list(bucket.get('words', {}).items()) if bucket else []
            if not items:
                irc.reply("Word list is empty.")
                return
            out = [f"[{e['id']}] '{m}' ({e['match_type']}) -> {'>'.join(e['actions'])}" for m, e in items]
            irc.reply(" | ".join(out))
        list = wrap(list, [('checkChannelCapability', 'op'), 'channel'])

        def search(self, irc, msg, args, channel, pattern):
            """[<channel>] <pattern>"""
            p = self.plugin
            bucket = p._get_channel_bucket(channel)
            needle = pattern.lower()
            items = bucket.get('words', {}).items() if bucket else []
            out = [f"[{e['id']}] '{m}'" for m, e in items if needle in m.lower()]
            irc.reply(" | ".join(out) if out else "No matching entries found.")
        search = wrap(search, [('checkChannelCapability', 'op'), 'channel', 'text'])

    # -----------------------------------------------------------------
    # IRC event handlers
    # -----------------------------------------------------------------

    def doMode(self, irc, msg):
        """Syncs the DB with manual bans/unbans made directly on IRC."""
        channel = msg.args[0]
        if len(msg.args) < 3 or ircutils.strEqual(msg.nick, irc.nick):
            return

        mode_change, mask = msg.args[1], msg.args[2]
        c_lower = channel.lower()

        if mode_change in ('+b', '-b') and self._looksLikeExtban(mask):
            # Extban syntax (ircd-specific, e.g. ~account:foo, $a:foo).
            # We never parse or track these -- leave them entirely alone.
            return

        if mode_change == '+b':
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
                    logger.info(f"Manual unban: {mask} kept in DB (is bot blacklist entry)")
                self._unschedule('channel', channel, entry['id'])

    def doJoin(self, irc, msg):
        if ircutils.strEqual(msg.nick, irc.nick):
            return
        channel = msg.args[0]
        c_lower = channel.lower()

        if self.registryValue('enforceGlobal', channel):
            with self._db_lock:
                net_items = list(self.db['net']['entries'].items())
            for mask, e in net_items:
                if ircutils.hostmaskPatternEqual(mask, msg.prefix):
                    irc.queueMsg(ircmsgs.ban(channel, mask))
                    irc.queueMsg(ircmsgs.kick(channel, msg.nick, e['reason'] or "Network-wide ban."))
                    return

        if self.registryValue('enabled', channel):
            with self._db_lock:
                bucket = self.db['channels'].get(c_lower)
                items = list(bucket['entries'].items()) if bucket else []
            for mask, e in items:
                if ircutils.hostmaskPatternEqual(mask, msg.prefix):
                    irc.queueMsg(ircmsgs.ban(channel, mask))
                    irc.queueMsg(ircmsgs.kick(channel, msg.nick, e['reason']))
                    return

    def doPrivmsg(self, irc, msg):
        if ircutils.strEqual(msg.nick, irc.nick):
            return
        channel = msg.args[0]
        if not ircutils.isChannel(channel):
            return
        if not self.registryValue('wordFilterEnabled', channel):
            return
        if self._isExempt(channel, msg.prefix) or self._isExemptNet(msg.prefix):
            return

        text = msg.args[1] if len(msg.args) > 1 else ''
        case_sensitive = self.registryValue('wordCaseSensitive', channel)

        # Every matching entry (channel + net) fires independently, same as
        # the weechat-blacklist reference this is modeled on -- a message
        # tripping two different word entries escalates both ladders.
        for scope, pattern, entry in self._wordEntriesFor(channel):
            if not self._wordMatches(pattern, entry['match_type'], text, case_sensitive):
                continue
            count = self._bumpWordOffense(irc.network, channel, msg.prefix, scope,
                                           entry['id'], entry['cooldown_minutes'])
            actions = entry['actions']
            idx = min(count, len(actions)) - 1
            action = actions[idx]

            reason_chain = entry['reason'].split('|') if entry['reason'] else []
            reason = reason_chain[min(idx, len(reason_chain) - 1)] if reason_chain else None

            if action in ('ban', 'kickban'):
                # They can't offend again until unbanned; reset now instead
                # of waiting on the cooldown so they start fresh at step 1
                # whenever they return.
                self._resetWordOffense(irc.network, channel, msg.prefix, scope, entry['id'])

            self._doWordAction(irc, channel, msg.nick, msg.prefix, action, reason, pattern)


Class = Blacklist
