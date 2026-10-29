# Copyright (c) 2021, Valentin Lorentz
# Copyright (c) 2026, PeGaSuS
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

###

import fnmatch
import json
import os
import re
import sqlite3
import string
import threading
import time

from supybot import callbacks, conf, ircdb, ircmsgs, ircutils, utils
from supybot.commands import optional, thread, wrap

try:
    from supybot.i18n import PluginInternationalization

    _ = PluginInternationalization("NickTracker")
except ImportError:
    _ = lambda x: x


class NickTrackerDB:
    """SQLite store: one row per (network, channel, host key, nick).

    rowid gives first-seen order, last_seen the most recent join.
    A single connection shared by all threads, serialised by a lock;
    every statement is short, so this never becomes a bottleneck.
    """

    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=5)
        with self.lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS nicktrack (
                    network TEXT NOT NULL,
                    chan TEXT NOT NULL,
                    host TEXT NOT NULL,
                    nick TEXT NOT NULL,
                    last_seen INTEGER,
                    PRIMARY KEY (network, chan, host, nick)
                );
                CREATE INDEX IF NOT EXISTS idx_nick
                    ON nicktrack (nick COLLATE NOCASE);
                """
            )
            # Without statistics the planner ignores idx_nick and scans the
            # whole channel on every search.
            if not self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'sqlite_stat1'"
            ).fetchone():
                self.conn.execute("ANALYZE")
            self.conn.execute("PRAGMA optimize")
            self.conn.commit()

    def close(self):
        with self.lock:
            self.conn.close()

    def clear(self):
        with self.lock:
            self.conn.execute("DELETE FROM nicktrack")
            self.conn.commit()

    def nicks_for_host(self, network, chan, host):
        """Nicks seen from this host, newest first."""
        with self.lock:
            rows = self.conn.execute(
                "SELECT nick FROM nicktrack"
                " WHERE network = ? AND chan = ? AND host = ?"
                " ORDER BY rowid DESC",
                (network, chan, host),
            ).fetchall()
        return [r[0] for r in rows]

    def record(self, network, chan, host, nick, known):
        """Store nick for host, or refresh last_seen if a case variant is
        already stored (nicks keep the spelling they were first seen with)."""
        now = int(time.time())
        stored = next((k for k in known if ircutils.strEqual(k, nick)), None)
        with self.lock:
            if stored is None:
                self.conn.execute(
                    "INSERT OR IGNORE INTO nicktrack"
                    " (network, chan, host, nick, last_seen)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (network, chan, host, nick, now),
                )
            else:
                self.conn.execute(
                    "UPDATE nicktrack SET last_seen = ?"
                    " WHERE network = ? AND chan = ? AND host = ? AND nick = ?",
                    (now, network, chan, host, stored),
                )
            self.conn.commit()

    def hosts_for_nick(self, network, chans, nick):
        """Hosts a nick was seen from, oldest first, deduplicated."""
        seen = {}
        with self.lock:
            for chan in chans:
                for rid, host in self.conn.execute(
                    "SELECT rowid, host FROM nicktrack"
                    " WHERE network = ? AND chan = ? AND nick = ? COLLATE NOCASE",
                    (network, chan, nick),
                ):
                    seen[host] = max(seen.get(host, 0), rid)
        return _by_recency(seen)

    def nicks_for_hosts(self, network, chans, hosts, exclude):
        """Nicks seen from any of the hosts, oldest first, minus exclude."""
        seen = {}
        with self.lock:
            for chan in chans:
                for host in hosts:
                    for rid, n in self.conn.execute(
                        "SELECT rowid, nick FROM nicktrack"
                        " WHERE network = ? AND chan = ? AND host = ?"
                        " AND nick != ? COLLATE NOCASE",
                        (network, chan, host, exclude),
                    ):
                        seen[n] = max(seen.get(n, 0), rid)
        return _by_recency(seen)

    def nicks_for_mask(self, network, chans, like):
        """Nicks seen from hosts matching a LIKE pattern, oldest first."""
        seen = {}
        with self.lock:
            for chan in chans:
                for rid, n in self.conn.execute(
                    "SELECT rowid, nick FROM nicktrack"
                    " WHERE network = ? AND chan = ? AND host LIKE ? ESCAPE '\\'",
                    (network, chan, like),
                ):
                    seen[n] = max(seen.get(n, 0), rid)
        return _by_recency(seen)

    def stale(self, network, chan, cutoff):
        """(chan, host, nick count, last seen) for hosts unseen since cutoff,
        oldest first. Full scan; call from a thread."""
        with self.lock:
            return self.conn.execute(
                "SELECT chan, host, count(*), max(last_seen) AS seen"
                " FROM nicktrack"
                " WHERE network = ? AND (? = '' OR chan = ?)"
                " GROUP BY chan, host HAVING seen < ? ORDER BY seen",
                (network, chan, chan, cutoff),
            ).fetchall()

    def import_rows(self, rows, batch=10000):
        """Bulk insert (network, chan, host, nick, last_seen) tuples in
        batches, releasing the lock between them so joins are not held up
        for the whole import. Returns (inserted, already present)."""
        inserted = skipped = 0
        pending = []

        def flush():
            nonlocal inserted, skipped
            with self.lock:
                try:
                    for row in pending:
                        cur = self.conn.execute(
                            "INSERT OR IGNORE INTO nicktrack"
                            " (network, chan, host, nick, last_seen)"
                            " VALUES (?, ?, ?, ?, ?)",
                            row,
                        )
                        if cur.rowcount:
                            inserted += 1
                        else:
                            skipped += 1
                    self.conn.commit()
                except Exception:
                    self.conn.rollback()
                    raise
            pending.clear()

        for row in rows:
            pending.append(row)
            if len(pending) >= batch:
                flush()
        flush()
        with self.lock:
            self.conn.execute("ANALYZE")
            self.conn.commit()
        return inserted, skipped

def _by_recency(seen):
    return [k for k, _rid in sorted(seen.items(), key=lambda kv: kv[1])]


def _like_pattern(mask):
    """IRC-style mask -> SQL LIKE pattern (\\ as escape). A mask without
    wildcards matches anywhere in the host."""
    mask = mask.lower().split("!")[-1]
    if not any(c in mask for c in "*?"):
        mask = "*%s*" % mask
    out = []
    for c in mask:
        if c in "\\%_":
            out.append("\\" + c)
        elif c == "*":
            out.append("%")
        elif c == "?":
            out.append("_")
        else:
            out.append(c)
    return "".join(out)


class NickTracker(callbacks.Plugin):
    """Remembers which nicks were seen from each host on a channel and
    announces the other nicks a host has used when it joins. Ops can search
    the history with searchnick, searchhost and searchmask."""

    threaded = True

    def __init__(self, irc):
        super().__init__(irc)
        self.db = NickTrackerDB(
            conf.supybot.directories.data.dirize("NickTracker/nicktracker.db")
        )

    def die(self):
        self.db.close()
        super().die()

    # ----------------------------------------------------------------- keys

    def _host_key(self, irc, channel, nick, user, host):
        """The host string a user is stored under, per the pattern config."""
        user = user.lstrip("~").lower()
        host = host.lower()
        full = "%s!%s@%s" % (nick.lower(), user, host)
        pattern = self.registryValue("defaultPattern", channel, irc.network)
        for pair in self.registryValue("specialPatterns", channel, irc.network):
            if ":" not in pair:
                self.log.warning("NickTracker: bad specialPattern %r", pair)
                continue
            # The $pattern side never contains ':', so split on the last one;
            # this lets a 're:' regex use ':' freely.
            mask, special = pair.rsplit(":", 1)
            if mask[:3].lower() == "re:":
                try:
                    matched = re.search(mask[3:], full, re.IGNORECASE)
                except re.error as e:
                    self.log.warning(
                        "NickTracker: bad specialPattern regex %r: %s", mask, e
                    )
                    continue
            else:
                matched = fnmatch.fnmatchcase(full, mask.lower())
            if matched:
                pattern = special
                break
        return string.Template(pattern).safe_substitute(
            nick=nick.lower(), user=user, host=host
        )

    def _ignored(self, irc, channel, user, host):
        uh = "%s@%s" % (user.lstrip("~").lower(), host.lower())
        for glob in self.registryValue("ignoreHosts", channel, irc.network):
            if fnmatch.fnmatchcase(uh, glob.lstrip("~").lower()):
                return True
        return False

    # ------------------------------------------------------------- tracking

    def doJoin(self, irc, msg):
        if msg.channel is None or ircutils.strEqual(msg.nick, irc.nick):
            return
        self._seen(irc, msg.channel, msg.nick, msg.user, msg.host)

    def doNick(self, irc, msg):
        new = msg.args[0]
        if ircutils.strEqual(msg.nick, irc.nick) or ircutils.strEqual(new, irc.nick):
            return
        for channel in msg.tagged("channels") or ():
            self._seen(irc, channel, new, msg.user, msg.host)

    def _seen(self, irc, channel, nick, user, host):
        if not self.registryValue("enabled", channel, irc.network):
            return
        if self._ignored(irc, channel, user, host):
            return
        chan = ircutils.toLower(channel)
        key = self._host_key(irc, channel, nick, user, host)
        known = self.db.nicks_for_host(irc.network, chan, key)
        if known:
            others = [n for n in known if not ircutils.strEqual(n, nick)]
            if others:
                self._announce(irc, channel, nick, others)
        self.db.record(irc.network, chan, key, nick, known)

    def _announce(self, irc, channel, nick, nicks):
        targets = self.registryValue("targets", channel, irc.network)
        if not targets:
            return
        per_line = self.registryValue("announce.nicks.perLine", channel, irc.network)
        max_lines = self.registryValue("announce.nicks.lines", channel, irc.network)
        sep = self.registryValue("announce.nicks.separator", channel, irc.network)
        text = self.registryValue("announce.text", channel, irc.network)
        others = self.registryValue("announce.others", channel, irc.network)

        remaining = 0
        if max_lines:
            cap = per_line * max_lines
            if len(nicks) > cap:
                remaining = len(nicks) - cap
                nicks = nicks[:cap]
        chunks = [nicks[i : i + per_line] for i in range(0, len(nicks), per_line)]

        for target in targets:
            colour = self.registryValue("announce.color", channel, irc.network)
            if colour and irc.isChannel(target):
                state = irc.state.channels.get(target)
                if state is not None and "c" in state.modes:
                    colour = False
            for i, chunk in enumerate(chunks):
                line = sep.join(chunk)
                if remaining and i == len(chunks) - 1:
                    line += " (+%d %s)" % (remaining, others)
                if colour:
                    out = "[%s] %s %s: %s" % (
                        ircutils.mircColor(channel, "blue"),
                        ircutils.mircColor(nick, "red"),
                        text,
                        ircutils.mircColor(line, "red"),
                    )
                else:
                    out = "[%s] %s %s: %s" % (channel, nick, text, line)
                irc.queueMsg(ircmsgs.privmsg(target, out))

    # -------------------------------------------------------------- searches

    def _tracked_channels(self, irc):
        return [
            c
            for c in irc.state.channels
            if self.registryValue("enabled", c, irc.network)
        ]

    def _resolve_channels(self, irc, msg, channel):
        """Channels a search applies to: the given/current one, or, when it
        is an announce target, the channels announcing to it; none given
        (query) means every tracked channel on the network."""
        if channel is None:
            return self._tracked_channels(irc)
        sources = [
            c
            for c in self._tracked_channels(irc)
            if any(
                ircutils.strEqual(t, channel)
                for t in self.registryValue("targets", c, irc.network)
            )
        ]
        return sources or [channel]

    def _allowed(self, irc, msg, channel):
        """admin, op of the channel, or speaking in one of its targets."""
        # ignoreDefaultAllow: unknown users get channel capabilities by
        # default allowance, which must not count as being an op here
        if ircdb.checkCapability(msg.prefix, "admin", ignoreDefaultAllow=True):
            return True
        if ircdb.checkCapability(
            msg.prefix,
            ircdb.makeChannelCapability(channel, "op"),
            ignoreDefaultAllow=True,
        ):
            return True
        if msg.channel is not None:
            return any(
                ircutils.strEqual(t, msg.channel)
                for t in self.registryValue("targets", channel, irc.network)
            )
        return False

    def _search_channels(self, irc, msg, channel):
        chans = [
            c for c in self._resolve_channels(irc, msg, channel)
            if self._allowed(irc, msg, c)
        ]
        if not chans:
            irc.error(
                _("You need to be an op of that channel, or ask from one of "
                  "its announce targets."),
                Raise=True,
            )
        return [ircutils.toLower(c) for c in chans]

    def _reply_results(self, irc, label, query, results):
        cap = self.registryValue("searchResults")
        shown = results[-cap:]
        irc.reply(
            _("Last %d/%d %s %s: %s")
            % (len(shown), len(results), label, query, ", ".join(shown))
        )

    def searchnick(self, irc, msg, args, channel, nick):
        """[<channel>] <nick>

        Lists the other nicks seen from the hosts <nick> used. Without
        <channel>, searches the channels announcing to the current one, or
        all tracked channels from a query.
        """
        chans = self._search_channels(irc, msg, channel)
        hosts = self.db.hosts_for_nick(irc.network, chans, nick)
        if not hosts:
            irc.reply(_("No data for nick %s in %s.") % (nick, ", ".join(chans)))
            return
        nicks = self.db.nicks_for_hosts(irc.network, chans, hosts, nick)
        if not nicks:
            irc.reply(_("No other nicks for %s in %s.") % (nick, ", ".join(chans)))
            return
        self._reply_results(irc, _("nick(s) also used by"), nick, nicks)

    searchnick = wrap(searchnick, [optional("channel"), "nick"])

    def searchhost(self, irc, msg, args, channel, nick):
        """[<channel>] <nick>

        Lists the hosts <nick> was seen from.
        """
        chans = self._search_channels(irc, msg, channel)
        hosts = self.db.hosts_for_nick(irc.network, chans, nick)
        if not hosts:
            irc.reply(_("No hosts for nick %s in %s.") % (nick, ", ".join(chans)))
            return
        self._reply_results(irc, _("host(s) for"), nick, hosts)

    searchhost = wrap(searchhost, [optional("channel"), "nick"])

    def searchmask(self, irc, msg, args, channel, mask):
        """[<channel>] <mask>

        Lists the nicks seen from hosts matching <mask> (host, user@host or
        nick!user@host, * and ? wildcards; a plain string matches anywhere
        in the host).
        """
        chans = self._search_channels(irc, msg, channel)
        key = mask
        if "@" in mask:
            # key the mask the way hosts are stored (ident dropped, etc.),
            # keeping the wildcards; use the first channel's pattern config
            n, uh = mask.split("!", 1) if "!" in mask else ("*", mask)
            u, h = uh.split("@", 1)
            key = self._host_key(irc, chans[0], n, u, h)
        nicks = self.db.nicks_for_mask(irc.network, chans, _like_pattern(key))
        if not nicks:
            irc.reply(_("No nicks for mask %s in %s.") % (mask, ", ".join(chans)))
            return
        self._reply_results(irc, _("nick(s) for mask"), mask, nicks)

    searchmask = wrap(searchmask, [optional("channel"), "somethingWithoutSpaces"])

    # ------------------------------------------------------------ maintenance

    def stale(self, irc, msg, args, channel, days):
        """[<channel>] <days>

        Counts hosts not seen for <days> days and lists the longest-unseen
        ones. Full table scan, runs in the background.
        """
        chan = ircutils.toLower(channel) if channel else ""
        cutoff = int(time.time()) - days * 86400
        rows = self.db.stale(irc.network, chan, cutoff)
        where = chan or _("all channels")
        if not rows:
            irc.reply(_("No hosts unseen for %d+ days in %s.") % (days, where))
            return
        nicks = sum(r[2] for r in rows)
        now = int(time.time())
        oldest = [
            "%s (%s, %d nick(s), %dd)" % (r[1], r[0], r[2], (now - r[3]) // 86400)
            for r in rows[:10]
        ]
        irc.reply(
            _("%d host(s) / %d nick(s) unseen for %d+ days in %s. Oldest: %s")
            % (len(rows), nicks, days, where, "; ".join(oldest))
        )

    stale = thread(wrap(stale, ["admin", optional("channel"), "positiveInt"]))

    def importdata(self, irc, msg, args, path, channel):
        """<path> [<channel>]

        Imports old data for the current network: a *.json database from
        NickTracker 2.x, a nicktrack.db written by the eggdrop
        nicktracker-sqlite.tcl script, or a <chan>_nicklist.txt file from
        the flat-file eggdrop script (<channel> defaults to the file name).
        Hosts are stored as they are in the file; current data is kept.
        """
        if channel is not None and not irc.isChannel(channel):
            irc.errorInvalid(_("channel"), channel)
        try:
            if path.endswith(".json"):
                rows = self._rows_from_json(irc, path)
            elif path.endswith(".txt"):
                rows = self._rows_from_eggdrop(irc, path, channel)
            else:
                rows = self._rows_from_sqlite(irc, path)
            inserted, skipped = self.db.import_rows(rows)
        except (OSError, ValueError, sqlite3.Error) as e:
            irc.error(_("Import failed, nothing imported: %s") % e)
            return
        irc.reply(
            _("Imported %s: %d inserted, %d already present.")
            % (os.path.basename(path), inserted, skipped)
        )

    # not optional("channel"): that falls back to the current channel and
    # the file-name default would never apply
    importdata = thread(
        wrap(importdata, ["owner", "filename", optional("somethingWithoutSpaces")])
    )

    def _rows_from_json(self, irc, path):
        """NickTracker 2.x: {network: {channel: {key: [nicks]}}}. Keys that
        are full hostmasks are re-keyed with the current pattern config."""
        now = int(time.time())
        with open(path) as f:
            data = json.load(f)
        for network, chans in data.items():
            for channel, hosts in chans.items():
                chan = ircutils.toLower(channel)
                for key, nicks in hosts.items():
                    if ircutils.isUserHostmask(key):
                        n, u, h = ircutils.splitHostmask(key)
                        key = self._host_key(irc, channel, n, u, h)
                    for nick in nicks:
                        yield (network, chan, key.lower(), nick, now)

    def _rows_from_eggdrop(self, irc, path, channel):
        """nick1,nick2<host per line, newest nick first."""
        now = int(time.time())
        if channel is None:
            name = os.path.basename(path)
            if not name.endswith("_nicklist.txt"):
                raise ValueError("cannot derive the channel from %s" % name)
            channel = "#" + name[: -len("_nicklist.txt")]
        chan = ircutils.toLower(channel)
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if "<" not in line:
                    continue
                nicks, host = line.split("<", 1)
                host = host.lstrip("~").lower()
                if not host:
                    continue
                for nick in reversed(nicks.split(",")):
                    if nick:
                        yield (irc.network, chan, host, nick, now)

    def _rows_from_sqlite(self, irc, path):
        """nicktrack(chan, host, nick[, last_seen]) from the Tcl script."""
        now = int(time.time())
        src = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        try:
            cols = [r[1] for r in src.execute("PRAGMA table_info(nicktrack)")]
            seen = "last_seen" if "last_seen" in cols else "NULL"
            for chan, host, nick, last in src.execute(
                "SELECT chan, host, nick, %s FROM nicktrack ORDER BY rowid" % seen
            ):
                yield (irc.network, chan.lower(), host, nick, last or now)
        finally:
            src.close()


Class = NickTracker

# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
