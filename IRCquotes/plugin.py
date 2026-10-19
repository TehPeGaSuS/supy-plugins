###
# Copyright (c) 2026, PeGaSuS
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
import re
import time
import random
import shutil
import builtins
import sqlite3
import threading
import collections
import unicodedata
import html as html_escape
import urllib.parse

import supybot.conf as conf
import supybot.ircdb as ircdb
import supybot.ircmsgs as ircmsgs
import supybot.ircutils as ircutils
import supybot.utils as utils
import supybot.world as world
import supybot.schedule as schedule
import supybot.callbacks as callbacks
import supybot.httpserver as httpserver
from supybot.commands import *
from supybot.i18n import PluginInternationalization, internationalizeDocstring
_ = PluginInternationalization('IRCquotes')


###
# Text helpers, ported from the original script's addquote filters,
# findquote matching and hostmask_process.
###

# A timestamp such as [12:34], (12:34:56) or <12:34>, with any formatting
# codes right before it and the spaces right after it.
TIMESTAMP_RE = re.compile(
    r'((\x02|\x03(?:\d{0,2}(?:,\d{0,2})?)?|\x1f|\x16|\x0f)+)?'
    r'[\[(|<]\d{1,2}:\d{1,2}(:\d{1,2})?[>|)\]](\s+)?')
# Channel status symbols at the start of a line, or in front of a nick
# inside brackets, as in "<@nick>" or "(+nick)".
LEADING_ATTRIBUTES_RE = re.compile(r'^[~&@%+]+')
NICK_ATTRIBUTES_RE = re.compile(r'([{\[(|<])[~&@%+]+(.+?[>|)\]}])')
# mIRC formatting codes, for the web page.
MIRC_CODE_RE = re.compile(
    r'\x03(?:(\d{1,2})(?:,(\d{1,2}))?)?|[\x02\x0f\x11\x16\x1d\x1e\x1f]')

def foldAccents(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', s)
                   if not unicodedata.combining(c))

def searchable(text):
    return foldAccents(ircutils.stripFormatting(text)).lower()

def voterMask(prefix):
    """*!ident@*.domain for a voter, the same mask the original script used
    to tell unregistered voters apart (hostmask_process, type 10), so a
    nick change doesn't buy another vote."""
    try:
        (_nick, ident, host) = ircutils.splitHostmask(prefix)
    except AssertionError:
        return prefix
    ident = ident.lstrip('~')
    parts = host.split('.')
    if re.search(r'\d+\.\d+\.\d+\.\d+', host):
        parts[-1] = '*'
    elif len(parts) == 3:
        parts[0] = '*'
    elif len(parts) > 3:
        parts[0:2] = ['*']
    return '*!%s@%s' % (ident, '.'.join(parts))

def mircToHtml(text, separator=''):
    """Turns a quote's mIRC formatting into <span>s (classes mb, mi, mu,
    ms, mr, fgNN and bgNN), and its line separators into <br/>."""
    out = []
    pieces = text.split(separator) if separator else [text]
    for (n, piece) in enumerate(pieces):
        if n:
            out.append('<br/>')
        bold = italic = underline = strike = reverse = False
        fg = bg = None
        opened = False
        pos = 0
        for m in MIRC_CODE_RE.finditer(piece):
            out.append(html_escape.escape(piece[pos:m.start()]))
            pos = m.end()
            code = m.group(0)[0]
            if code == '\x02':
                bold = not bold
            elif code == '\x1d':
                italic = not italic
            elif code == '\x1f':
                underline = not underline
            elif code == '\x1e':
                strike = not strike
            elif code == '\x16':
                reverse = not reverse
            elif code == '\x0f':
                bold = italic = underline = strike = reverse = False
                fg = bg = None
            elif code == '\x03':
                if m.group(1) is None:
                    fg = bg = None
                else:
                    fg = int(m.group(1))
                    if m.group(2) is not None:
                        bg = int(m.group(2))
            if opened:
                out.append('</span>')
                opened = False
            classes = [name for (on, name) in ((bold, 'mb'), (italic, 'mi'),
                       (underline, 'mu'), (strike, 'ms'), (reverse, 'mr'))
                       if on]
            if fg is not None:
                classes.append('fg%02d' % fg)
            if bg is not None:
                classes.append('bg%02d' % bg)
            if classes:
                out.append('<span class="%s">' % ' '.join(classes))
                opened = True
        out.append(html_escape.escape(piece[pos:]))
        if opened:
            out.append('</span>')
    return ''.join(out)


class QuoteRecord:
    """A single quote. Unlike a dbi Record, this is a plain attribute bag
    backed by a row in QuotesDB -- there's no automatic serialization
    magic to it."""
    __slots__ = ('id', 'at', 'by', 'text', 'likes', 'dislikes', 'voters',
                 'deleted', 'deletedBy', 'deletedAt', 'deletedByAdmin',
                 'deletedHost')

    def __init__(self, id, at, by, text, likes=0, dislikes=0, voters='',
                 deleted=False, deletedBy='', deletedAt=0,
                 deletedByAdmin=False, deletedHost=''):
        self.id = id
        self.at = at
        self.by = by
        self.text = text
        self.likes = likes
        self.dislikes = dislikes
        self.voters = voters
        self.deleted = bool(deleted)
        self.deletedBy = deletedBy
        self.deletedAt = deletedAt
        self.deletedByAdmin = bool(deletedByAdmin)
        self.deletedHost = deletedHost

    @property
    def score(self):
        return self.likes - self.dislikes


class QuotesDB:
    """One global SQLite database for every network and channel, keyed by
    (network, channel, id).

    This is deliberately not Limnoria's usual per-channel dbi flat-file
    plugin database: those key storage by channel name *alone*, so if the
    bot is on multiple networks that each have (say) a #software channel,
    they would all collide on the exact same file and share one quote
    list. Keying by (network, channel) keeps them independent while still
    living in a single file on disk."""

    # Columns added after the first release, created on older databases.
    _ADDED_COLUMNS = (
        ('deletedByAdmin', 'INTEGER NOT NULL DEFAULT 0'),
        ('deletedHost', "TEXT NOT NULL DEFAULT ''"),
    )

    def __init__(self, filename):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(filename, check_same_thread=False)
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS quotes (
                    network TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    id INTEGER NOT NULL,
                    at REAL NOT NULL,
                    by TEXT NOT NULL,
                    text TEXT NOT NULL,
                    likes INTEGER NOT NULL DEFAULT 0,
                    dislikes INTEGER NOT NULL DEFAULT 0,
                    voters TEXT NOT NULL DEFAULT '',
                    deleted INTEGER NOT NULL DEFAULT 0,
                    deletedBy TEXT NOT NULL DEFAULT '',
                    deletedAt REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (network, channel, id)
                )
            """)
            self._conn.commit()
            self._addMissingColumns()
            self._normalizeExistingChannels()
            self._conn.row_factory = sqlite3.Row

    def _addMissingColumns(self):
        have = set(row[1] for row in
                   self._conn.execute("PRAGMA table_info(quotes)"))
        for (name, declaration) in self._ADDED_COLUMNS:
            if name not in have:
                self._conn.execute("ALTER TABLE quotes ADD COLUMN %s %s" %
                                   (name, declaration))
        self._conn.commit()

    def _normalizeExistingChannels(self):
        # One-time migration for rows written before channel names were
        # normalized to lowercase at write-time (see _key()): fold any
        # mixed-case channel already on disk down to the same key a fresh
        # write would use now, so old and new rows for the "same" channel
        # don't end up split across two different cases.
        cur = self._conn.execute("SELECT DISTINCT channel FROM quotes")
        for (storedChannel,) in cur.fetchall():
            normalized = self._key(storedChannel)
            if normalized == storedChannel:
                continue
            try:
                self._conn.execute(
                    "UPDATE quotes SET channel=? WHERE channel=?",
                    (normalized, storedChannel))
                self._conn.commit()
            except sqlite3.IntegrityError:
                # A row already exists under the normalized key for the
                # same (network, id) -- extremely unlikely, but don't
                # crash the plugin over it; leave the old row as-is.
                self._conn.rollback()

    def close(self):
        with self._lock:
            self._conn.close()

    def backup(self, filename):
        """Copies the whole database to filename, safely even while it's
        in use."""
        with self._lock:
            target = sqlite3.connect(filename)
            try:
                self._conn.backup(target)
            finally:
                target.close()

    @staticmethod
    def _rowToRecord(row):
        return QuoteRecord(row['id'], row['at'], row['by'], row['text'],
                           row['likes'], row['dislikes'], row['voters'],
                           row['deleted'], row['deletedBy'], row['deletedAt'],
                           row['deletedByAdmin'], row['deletedHost'])

    @staticmethod
    def _key(channel):
        # IRC channel names are case-insensitive, but SQLite string
        # comparison isn't -- without this, "#Software" (e.g. the literal
        # case a PRIVMSG target happened to arrive in) and "#software"
        # (e.g. the case the channel was originally joined under, used to
        # build the web UI's links) would be treated as two different
        # channels and silently never see each other's quotes.
        return ircutils.toLower(channel)

    def add(self, network, channel, at, by, text):
        channel = self._key(channel)
        with self._lock:
            cur = self._conn.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM quotes "
                "WHERE network=? AND channel=?", (network, channel))
            newId = cur.fetchone()[0]
            self._conn.execute(
                "INSERT INTO quotes (network, channel, id, at, by, text) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (network, channel, newId, at, by, text))
            self._conn.commit()
            return newId

    def get(self, network, channel, id):
        channel = self._key(channel)
        cur = self._conn.execute(
            "SELECT * FROM quotes WHERE network=? AND channel=? AND id=?",
            (network, channel, id))
        row = cur.fetchone()
        if row is None:
            raise KeyError(id)
        return self._rowToRecord(row)

    def set(self, network, channel, id, record):
        channel = self._key(channel)
        with self._lock:
            cur = self._conn.execute(
                "UPDATE quotes SET at=?, by=?, text=?, likes=?, dislikes=?, "
                "voters=?, deleted=?, deletedBy=?, deletedAt=?, "
                "deletedByAdmin=?, deletedHost=? "
                "WHERE network=? AND channel=? AND id=?",
                (record.at, record.by, record.text, record.likes,
                 record.dislikes, record.voters, int(record.deleted),
                 record.deletedBy, record.deletedAt,
                 int(record.deletedByAdmin), record.deletedHost,
                 network, channel, id))
            self._conn.commit()
            if cur.rowcount == 0:
                raise KeyError(id)

    def remove(self, network, channel, id):
        channel = self._key(channel)
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM quotes WHERE network=? AND channel=? AND id=?",
                (network, channel, id))
            self._conn.commit()
            if cur.rowcount == 0:
                raise KeyError(id)

    def select(self, network, channel, predicate, reverse=False):
        channel = self._key(channel)
        order = 'DESC' if reverse else 'ASC'
        cur = self._conn.execute(
            "SELECT * FROM quotes WHERE network=? AND channel=? "
            "ORDER BY id %s" % order, (network, channel))
        for row in cur.fetchall():
            record = self._rowToRecord(row)
            if predicate(record):
                yield record

    def maxId(self, network, channel):
        channel = self._key(channel)
        cur = self._conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM quotes "
            "WHERE network=? AND channel=?", (network, channel))
        return cur.fetchone()[0]

    def channels(self, network):
        cur = self._conn.execute(
            "SELECT DISTINCT channel FROM quotes WHERE network=? "
            "ORDER BY channel", (network,))
        return [row[0] for row in cur.fetchall()]

    def size(self, network, channel):
        channel = self._key(channel)
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM quotes WHERE network=? AND channel=? "
            "AND deleted=0", (network, channel))
        return cur.fetchone()[0]


###
# Web interface. The look (dark background, orange "shadowed" header bar,
# rounded panels) is ported from the original Eggdrop script's
# templates/default/{index.html,style.css}, adapted to Limnoria's built-in
# HTTP server (supybot.httpserver) instead of the original's static HTML
# export.
###

PAGE_SKELETON = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>%(title)s</title>
  <link rel="stylesheet" href="/ircquotes/style.css" type="text/css" />
</head>
<body>
  <header class="topbar">
    <div class="topbar-inner">
      <span class="brand">""" + _('IRCquotes') + """</span>
      <button id="theme-toggle" type="button"
              aria-label=\"""" + _('Toggle color theme') + """\">🌓</button>
    </div>
  </header>
  <div id="content">
%(body)s
  </div>
  <script>
  (function () {
    var root = document.documentElement;
    var btn = document.getElementById('theme-toggle');
    var stored = null;
    try { stored = localStorage.getItem('ircquotes-theme'); } catch (e) {}
    if (stored === 'light' || stored === 'dark') {
      root.setAttribute('data-theme', stored);
    }
    btn.addEventListener('click', function () {
      var current = root.getAttribute('data-theme');
      if (!current) {
        var prefersLight = window.matchMedia &&
          window.matchMedia('(prefers-color-scheme: light)').matches;
        current = prefersLight ? 'light' : 'dark';
      }
      var next = current === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('ircquotes-theme', next); } catch (e) {}
    });
  })();
  </script>
</body>
</html>"""

DEFAULT_TEMPLATES = {
    'ircquotes/index.html': PAGE_SKELETON % {
        'title': _('IRC Quotes'),
        'body': """\
    <h1>""" + _('IRC Quotes') + """</h1>
    %(cards)s
    <form class="jumpform" action="." method="post">
      <label for="chan">""" + _('Or jump to a channel by name:') + """</label>
      <input type="text" placeholder="#channel" name="chan" id="chan" />
      <input type="submit" name="submit" value=\"""" + _('view') + """\" />
    </form>""",
    },
    'ircquotes/channel.html': PAGE_SKELETON % {
        'title': _('Quotes of %(channel)s'),
        'body': """\
    <h1>""" + _('Quotes of %(channel)s') + """</h1>
    <div class="infobar">
      <span class="infoitem">""" + _('Network:') + """ <span
        class="infovalue">%(network)s</span></span>
      <span class="infoitem">""" + _('Channel:') + """ <span
        class="infovalue">%(channel)s</span></span>
      <span class="infoitem">""" + _('Bot:') + """ <span
        class="infovalue">%(botnick)s</span></span>
      <div class="infocount">""" + _('%(count)s quote(s) in the '
                                      'database.') + """</div>
    </div>
%(topquotes)s
    %(pagenav)s
    <div class="panel" id="quotes">
%(topquotes_titled)s
      %(rows)s
    </div>
    %(pagenav)s
    <footer class="pagefooter">%(footer)s<div>""" + _('IRCquotes, ported '
                                       'from Public Quotes System') + """</div>
    </footer>""",
    },
    'ircquotes/style.css': """\
/* IRCquotes web style -- a modernized take on Public Quotes System's
   original dark theme (same layout/class structure, refreshed palette). */
/* Dark theme (the default). */
:root {
    --bg: #14161c;
    --panel: #1c1f28;
    --panel-alt: #20242f;
    --accent: #6ea8fe;
    --accent-soft: #8f7bff;
    --text: #d7dae2;
    --text-dim: #8890a0;
    --positive: #4ade80;
    --negative: #f87171;
    --shadow: rgba(0, 0, 0, 0.35);
    --border: #2a2e3a;
}
/* Automatic light theme, only used until the visitor picks one via the
   toggle button (data-theme then takes over, see below). */
@media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) {
        --bg: #f4f5f7;
        --panel: #ffffff;
        --panel-alt: #eef0f4;
        --accent: #2563eb;
        --accent-soft: #7c3aed;
        --text: #1f2430;
        --text-dim: #667085;
        --positive: #16a34a;
        --negative: #dc2626;
        --shadow: rgba(20, 20, 30, 0.08);
        --border: #e2e5eb;
    }
}
/* Explicit theme picked via the toggle button, overriding system
   preference either way. */
:root[data-theme="light"] {
    --bg: #f4f5f7;
    --panel: #ffffff;
    --panel-alt: #eef0f4;
    --accent: #2563eb;
    --accent-soft: #7c3aed;
    --text: #1f2430;
    --text-dim: #667085;
    --positive: #16a34a;
    --negative: #dc2626;
    --shadow: rgba(20, 20, 30, 0.08);
    --border: #e2e5eb;
}
* { box-sizing: border-box; }
html, body {
    margin: 0;
    padding: 0;
    font: 0.95em/1.5 "Inter", "Segoe UI", helvetica, arial, sans-serif;
    color: var(--text);
    background-color: var(--bg);
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.topbar {
    background-color: var(--panel);
    border-bottom: 1px solid var(--border);
}
.topbar-inner {
    max-width: 880px;
    margin: 0 auto;
    padding: 14px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.brand { font-weight: 700; color: var(--accent); font-size: 1.1em; }
#theme-toggle {
    background: var(--panel-alt);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 1em;
    line-height: 1;
    cursor: pointer;
    color: var(--text);
}
#theme-toggle:hover { border-color: var(--accent); }
#content {
    max-width: 880px;
    margin: 0 auto;
    padding: 28px 20px 40px 20px;
    text-align: center;
}
h1 {
    margin: 0 0 20px 0;
    font-size: 1.6em;
    font-weight: 700;
    color: var(--accent);
}
.jumpform {
    margin: 24px 0 0 0;
    display: flex;
    gap: 8px;
    align-items: center;
    justify-content: center;
    flex-wrap: wrap;
}
.jumpform label { color: var(--text-dim); }
.jumpform input[type="text"] {
    padding: 6px 10px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--panel);
    color: var(--text);
}
.jumpform input[type="submit"] {
    padding: 6px 14px;
    border-radius: 6px;
    border: none;
    background: var(--accent);
    color: #10131a;
    font-weight: 600;
    cursor: pointer;
}
.networks {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 16px;
    margin: 0;
}
.network-card {
    width: 100%;
    max-width: 260px;
    text-align: left;
    padding: 14px 18px;
    background-color: var(--panel);
    border-radius: 10px;
    box-shadow: 0 4px 14px var(--shadow);
}
.network-card h2 {
    margin: 0 0 10px 0;
    font-size: 1.1em;
    font-weight: 600;
    color: var(--accent-soft);
}
.network-card ul.channel-list {
    list-style: none;
    margin: 0;
    padding: 0;
}
.network-card ul.channel-list li {
    padding: 4px 0;
    border-bottom: 1px solid var(--border);
}
.network-card ul.channel-list li:last-child { border-bottom: none; }
.network-card ul.channel-list a { color: var(--accent); }
.no-networks { color: var(--text-dim); }
.infobar {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 4px 20px;
    margin: 0 0 24px 0;
    color: var(--text-dim);
}
.infovalue { font-weight: 600; color: var(--text); }
.infocount { width: 100%; margin-top: 4px; }
.panel {
    text-align: left;
    color: var(--text);
    padding: 14px 18px;
    background-color: var(--panel);
    border-radius: 10px;
    box-shadow: 0 4px 14px var(--shadow);
    margin-bottom: 10px;
}
.panel.topquotes { background-color: var(--panel-alt); }
.paneltitle {
    font-size: 1.2em;
    font-weight: 600;
    color: var(--accent-soft);
    margin-bottom: 10px;
}
.quote {
    padding: 10px 4px;
    border-bottom: 1px solid var(--border);
}
.quote:last-child { border-bottom: none; }
.quoteid { font-weight: 600; font-size: 0.9em; color: var(--accent); }
.quotetext { margin: 6px 0; white-space: pre-wrap; }
.quotetimestamp, .quoteauthor { color: var(--text-dim); font-size: 0.75em; }
.quoterating { color: var(--text-dim); font-size: 0.75em; float: right; }
.positiverating { color: var(--positive); font-weight: 600; }
.negativerating { color: var(--negative); font-weight: 600; }
.pagefooter {
    text-align: center;
    color: var(--text-dim);
    font-size: 0.8em;
    padding-top: 10px;
}
.pagenav {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 10px;
    margin: 10px 0;
    font-size: 0.9em;
}
.pagenav .pagecurrent {
    font-weight: 700;
    color: var(--accent);
    text-decoration: underline;
}
/* mIRC formatting kept in the quotes (web.keepStyles). */
.mb { font-weight: 700; }
.mi { font-style: italic; }
.mu { text-decoration: underline; }
.ms { text-decoration: line-through; }
.mu.ms { text-decoration: underline line-through; }
.mr { color: var(--bg); background-color: var(--text); }
.fg00 { color: #ffffff; }
.fg01 { color: #000000; }
.fg02 { color: #00007f; }
.fg03 { color: #009300; }
.fg04 { color: #ff0000; }
.fg05 { color: #7f0000; }
.fg06 { color: #9c009c; }
.fg07 { color: #fc7f00; }
.fg08 { color: #ffff00; }
.fg09 { color: #00fc00; }
.fg10 { color: #009393; }
.fg11 { color: #00ffff; }
.fg12 { color: #0000fc; }
.fg13 { color: #ff00ff; }
.fg14 { color: #7f7f7f; }
.fg15 { color: #d2d2d2; }
.bg00 { background-color: #ffffff; }
.bg01 { background-color: #000000; }
.bg02 { background-color: #00007f; }
.bg03 { background-color: #009300; }
.bg04 { background-color: #ff0000; }
.bg05 { background-color: #7f0000; }
.bg06 { background-color: #9c009c; }
.bg07 { background-color: #fc7f00; }
.bg08 { background-color: #ffff00; }
.bg09 { background-color: #00fc00; }
.bg10 { background-color: #009393; }
.bg11 { background-color: #00ffff; }
.bg12 { background-color: #0000fc; }
.bg13 { background-color: #ff00ff; }
.bg14 { background-color: #7f7f7f; }
.bg15 { background-color: #d2d2d2; }
.pagefooter div + div, .pagefooter p { margin: 2px 0; }
.quotemeta { color: var(--text-dim); font-size: 0.75em; }
@media (max-width: 480px) {
    .infobar { flex-direction: column; gap: 2px; }
}
""",
}
httpserver.set_default_templates(DEFAULT_TEMPLATES)


class IRCquotesWebCallback(httpserver.SupyHTTPServerCallback):
    name = 'IRCquotes web interface'

    def _renderQuote(self, network, channel, record):
        # Same fields as the original's HTML export: [id], date, the author
        # (web.showAuthor), the rating (when votes are enabled) and the
        # quote, with its mIRC styles (web.keepStyles) and one line per
        # lineSeparator.
        plugin = self._plugin
        separator = plugin.registryValue('lineSeparator', channel, network)
        if plugin.registryValue('web.keepStyles', channel, network):
            text = mircToHtml(record.text, separator)
        else:
            text = mircToHtml(ircutils.stripFormatting(record.text),
                              separator)
        author = ''
        if plugin.registryValue('web.showAuthor', channel, network):
            author = ' - <span class="quoteauthor">%s</span>' % \
                html_escape.escape(_('by %s') %
                                   plugin._userName(record.by))
        rating = ''
        if plugin.registryValue('votesEnabled', channel, network):
            score = record.score
            if score > 0:
                score = '<span class="positiverating">%d</span>' % score
            elif score < 0:
                score = '<span class="negativerating">%d</span>' % score
            rating = """\
  <span class="quoterating">%s %s
    (<span class="positiverating">%d+</span>
    <span class="negativerating">%d-</span>)</span>""" % (
                html_escape.escape(_('rating:')), score, record.likes,
                record.dislikes)
        return """\
<div class="quote">
  <span class="quoteid">[%(id)s]</span>
  <span class="quotetimestamp">%(at)s</span>%(author)s
%(rating)s
  <div class="quotetext">%(text)s</div>
</div>""" % {
            'id': record.id,
            'rating': rating,
            'text': text,
            'author': author,
            'at': html_escape.escape(plugin._when(record.at)),
        }

    def _renderNetworkCards(self, onlyChannel=None):
        # One card per connected network, listing the channels there whose
        # quotes have been opted into being browsable (web.channel). If
        # onlyChannel is given, cards are filtered down to networks that
        # have that exact channel -- used to disambiguate the "jump to a
        # channel" form when the same channel name exists on more than
        # one network.
        channelsByNetwork = {}
        for irc in world.ircs:
            channels = sorted(
                channel for channel in irc.state.channels
                if self._plugin.registryValue('web.channel', channel)
                and (onlyChannel is None or
                     ircutils.strEqual(channel, onlyChannel)))
            if channels:
                channelsByNetwork[irc.network] = channels
        if not channelsByNetwork:
            if onlyChannel is None:
                message = _('No channels are browsable here yet.')
            else:
                message = _('No network has a browsable quotes page for '
                            '%s.') % onlyChannel
            return '<p class="no-networks">%s</p>' % \
                html_escape.escape(message)
        cards = []
        for network in sorted(channelsByNetwork):
            links = '\n'.join(
                '    <li><a href="/ircquotes/%s/%s/">%s</a></li>' % (
                    utils.web.urlquote(network),
                    utils.web.urlquote(channel),
                    html_escape.escape(channel))
                for channel in channelsByNetwork[network])
            cards.append("""\
<div class="network-card">
  <h2>%s</h2>
  <ul class="channel-list">
%s
  </ul>
</div>""" % (html_escape.escape(network), links))
        return '<div class="networks">\n%s\n</div>' % '\n'.join(cards)

    def _renderPageNav(self, pageNum, totalPages):
        if totalPages <= 1:
            return ''
        links = []
        if pageNum > 1:
            links.append('<a href="?page=%d">&laquo; %s</a>' %
                          (pageNum - 1, html_escape.escape(_('Prev'))))
        for p in range(1, totalPages + 1):
            if p == pageNum:
                links.append('<span class="pagecurrent">%d</span>' % p)
            else:
                links.append('<a href="?page=%d">%d</a>' % (p, p))
        if pageNum < totalPages:
            links.append('<a href="?page=%d">%s &raquo;</a>' %
                          (pageNum + 1, html_escape.escape(_('Next'))))
        return '<div class="pagenav">%s</div>' % ' '.join(links)

    def doGetOrHead(self, handler, path, write_content):
        parsed = urllib.parse.urlsplit(path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        parts = [p for p in path.split('/') if p]
        if not parts:
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            if write_content:
                self.write(httpserver.get_template('ircquotes/index.html') %
                    {'cards': self._renderNetworkCards()})
            return
        if parts == ['style.css']:
            self.send_response(200)
            self.send_header('Content-type', 'text/css; charset=utf-8')
            self.end_headers()
            if write_content:
                self.write(httpserver.get_template('ircquotes/style.css'))
            return
        if len(parts) < 2:
            self.send_response(404)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            if write_content:
                self.write(httpserver.get_template('generic/error.html') % {
                    'title': 'IRCquotes - not found',
                    'error': 'Expected /ircquotes/&lt;network&gt;/'
                             '&lt;channel&gt;/.',
                })
            return
        network = utils.web.urlunquote(parts[0])
        channel = utils.web.urlunquote(parts[1])
        if not ircutils.isChannel(channel):
            self.send_response(404)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            if write_content:
                self.write(httpserver.get_template('generic/error.html') % {
                    'title': 'IRCquotes - not a channel',
                    'error': 'This is not a channel.',
                })
            return
        if not self._plugin.registryValue('web.channel', channel):
            self.send_response(403)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            if write_content:
                self.write(httpserver.get_template('generic/error.html') % {
                    'title': 'IRCquotes - unavailable',
                    'error': 'This channel\'s quotes are not available '
                             'here.',
                })
            return

        # network is taken directly from the URL rather than guessed by
        # scanning world.ircs for the channel name, since the same channel
        # name can exist -- with entirely different quotes -- on more than
        # one network the bot is connected to. The match itself is
        # case-insensitive (matching how IRC network names are normally
        # treated), but once found we use the *canonical* casing from the
        # Irc object for the database lookup and display, since the quotes
        # were stored under irc.network's exact casing at add-time -- not
        # whatever case the visitor happened to type in the URL.
        irc = None
        for candidate in world.ircs:
            if ircutils.strEqual(candidate.network, network):
                irc = candidate
                break
        if irc is None:
            self.send_response(404)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            if write_content:
                self.write(httpserver.get_template('generic/error.html') % {
                    'title': 'IRCquotes - unknown network',
                    'error': 'The bot is not connected to a network named '
                             '%s.' % html_escape.escape(network),
                })
            return
        network = irc.network
        botnick = irc.nick

        newestFirst = self._plugin.registryValue('web.newestFirst', channel,
                                                 network)
        records = list(self._plugin.db.select(
            network, channel, lambda r: not r.deleted, reverse=newestFirst))

        # Pagination, same idea as the original's html_quotes_per_page (0
        # means unlimited, everything on a single page).
        perPage = self._plugin.registryValue('web.quotesPerPage', channel)
        if perPage:
            totalPages = max(1, -(-len(records) // perPage)) # ceil div
        else:
            totalPages = 1
        try:
            pageNum = int(query.get('page', ['1'])[0])
        except ValueError:
            pageNum = 1
        pageNum = min(max(pageNum, 1), totalPages)
        if perPage:
            start = (pageNum - 1) * perPage
            pageRecords = records[start:start + perPage]
        else:
            pageRecords = records
        pagenav = self._renderPageNav(pageNum, totalPages)

        if pageRecords:
            rows = '\n'.join(self._renderQuote(network, channel, r)
                             for r in pageRecords)
        else:
            rows = '<p>%s</p>' % _('No quotes yet.')

        # "Top quotes" panel: the best-rated quotes, ported from the
        # original's toggleable, count-configurable html_show_best_rated_
        # quotes/%TOPQUOTES% feature: the highest scores first, quotes
        # with the same score in random order, and only on the first page
        # (same as the original). Only shown once something has actually
        # been rated, though.
        topQuotesEnabled = self._plugin.registryValue(
            'web.topQuotesEnabled', channel, network)
        topQuotesCount = self._plugin.registryValue(
            'web.topQuotesCount', channel, network)
        top = []
        if topQuotesEnabled and pageNum == 1 and \
                builtins.any(r.likes or r.dislikes for r in records):
            top = records[:]
            random.shuffle(top)
            top.sort(key=lambda r: r.score, reverse=True)
            top = top[:topQuotesCount]
        if top:
            top_rows = '\n'.join(self._renderQuote(network, channel, r)
                                 for r in top)
            topquotes = """\
    <div class="panel topquotes">
      <div class="paneltitle">%s</div>
      %s
    </div>""" % (
                html_escape.escape(_('Top %d quote(s)...') % len(top)),
                top_rows)
            topquotes_titled = '<div class="paneltitle">%s</div>' % \
                html_escape.escape(_('All quotes...'))
        else:
            topquotes = ''
            topquotes_titled = ''

        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        if write_content:
            self.write(httpserver.get_template('ircquotes/channel.html') % {
                'channel': html_escape.escape(channel),
                'network': html_escape.escape(network),
                'botnick': html_escape.escape(botnick),
                'count': len(records),
                'topquotes': topquotes,
                'topquotes_titled': topquotes_titled,
                'rows': rows,
                'pagenav': pagenav,
                'footer': ''.join(
                    '<div>%s</div>' % footer for footer in
                    (self._plugin.registryValue('web.footer1'),
                     self._plugin.registryValue('web.footer2'))
                    if footer),
            })

    def doPost(self, handler, path, form):
        if 'chan' not in form:
            self.send_response(400)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.write("Missing field 'chan'.")
            return
        channel = form['chan'].value
        matches = sorted(
            irc.network for irc in world.ircs
            if channel in irc.state.channels
            and self._plugin.registryValue('web.channel', channel))
        if len(matches) == 1:
            # Only one network has this channel web-enabled: go straight
            # there.
            self.send_response(303)
            self.send_header('Location', './%s/%s/' % (
                utils.web.urlquote(matches[0]),
                utils.web.urlquote(channel)))
            self.end_headers()
            return
        # Zero or multiple matches: show network cards filtered down to
        # this channel name, so the visitor can either see there's nothing
        # to show, or pick which network they meant.
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.write(httpserver.get_template('ircquotes/index.html') %
            {'cards': self._renderNetworkCards(onlyChannel=channel)})




def getLeadingChannel(irc, msg, args, state):
    # Like 'channel', but doesn't fail outside a channel: the original
    # syntax takes the channel *after* the quote number too, so the command
    # decides once it has seen both (see _target()).
    if args and irc.isChannel(args[0]):
        state.args.append(args.pop(0))
    else:
        state.args.append(msg.channel)

def getTrailingChannel(irc, msg, args, state):
    if args and irc.isChannel(args[0]):
        state.args.append(args.pop(0))
    else:
        state.args.append(None)

addConverter('ircquotesChannel', getLeadingChannel)
addConverter('ircquotesTrailingChannel', getTrailingChannel)

# What addquote's text is replaced with by inFilter, which keeps the text
# as it was typed for addquote to pick up.
RAW_TEXT_TOKEN = 'ircquotes:raw-text'
ADDQUOTE_RE = re.compile(r'^((?:ircquotes\s+)?addquote)(?:\s+(.*))?$',
                         re.I | re.S)

KEEP_TIMESTAMPS = ('-keep_timestamps', '--keep-timestamps',
                   '--keep_timestamps')
KEEP_ATTRIBUTES = ('-keep_attributes', '--keep-attributes',
                   '--keep_attributes')


class IRCquotes(callbacks.Plugin):
    """Per-network-and-channel quotes database with voting and an optional
    periodic "random quote" announcer. Ported from the Eggdrop TCL script
    'public_quotes_system'.

    Configuration variables in ``supybot.plugins.IRCquotes`` affect this
    plugin."""

    def __init__(self, irc):
        self.__parent = super(IRCquotes, self)
        self.__parent.__init__(irc)
        dbDir = conf.supybot.directories.data.dirize('IRCquotes')
        if not os.path.isdir(dbDir):
            os.makedirs(dbDir)
        self._dbPath = os.path.join(dbDir, 'ircquotes.db')
        self._restoreBackup()
        self.db = QuotesDB(self._dbPath)
        # Quotes already shown by randquote/autorandquote, per (network,
        # channel, auto): like the original, nothing repeats until every
        # quote has had its turn.
        self._randSeen = {}
        # Multi-line addquote sessions in progress, per (network, channel).
        self._addSessions = {}
        # Flood control state, per (network, channel, command).
        self._flood = {}
        # addquote's text as typed, per (network, prefix); see inFilter().
        self._rawText = {}
        for channel in getattr(irc.state, 'channels', {}) or {}:
            self._scheduleFor(irc, channel)
        self._scheduleBackup()
        conf.supybot.plugins.IRCquotes.backupTime.addCallback(
            self._scheduleBackup)
        self._http_running = False
        conf.supybot.plugins.IRCquotes.web.enable.addCallback(
            self._doHttpConf)
        if self.registryValue('web.enable'):
            self._startHttp()

    def die(self):
        for name in list(schedule.schedule.events):
            if name.startswith('IRCquotes_'):
                schedule.removeEvent(name)
        conf.supybot.plugins.IRCquotes.backupTime.removeCallback(
            self._scheduleBackup)
        conf.supybot.plugins.IRCquotes.web.enable.removeCallback(
            self._doHttpConf)
        if self._http_running:
            self._stopHttp()
        self.db.close()
        self.__parent.die()

    ###
    # Web interface lifecycle.
    ###

    def _doHttpConf(self, *args, **kwargs):
        if self.registryValue('web.enable'):
            if not self._http_running:
                self._startHttp()
        else:
            if self._http_running:
                self._stopHttp()

    def _startHttp(self):
        callback = IRCquotesWebCallback()
        callback._plugin = self
        httpserver.hook('ircquotes', callback)
        self._http_running = True

    def _stopHttp(self):
        httpserver.unhook('ircquotes')
        self._http_running = False

    ###
    # Daily backup, restored automatically if the database goes missing
    # (port of the original's backup_db and its restore-on-load).
    ###

    def _backupPath(self):
        return self._dbPath + '.bak'

    def _restoreBackup(self):
        backup = self._backupPath()
        if not os.path.exists(self._dbPath) and os.path.exists(backup):
            shutil.copyfile(backup, self._dbPath)
            self.log.warning('IRCquotes: %s was missing, so it was restored '
                             'from %s.', self._dbPath, backup)

    def _scheduleBackup(self, *args, **kwargs):
        name = 'IRCquotes_backup'
        if name in schedule.schedule.events:
            schedule.removeEvent(name)
        when = self.registryValue('backupTime')
        if not when:
            return
        (hour, minute) = map(int, when.split(':'))
        now = time.time()
        today = time.localtime(now)
        at = time.mktime((today.tm_year, today.tm_mon, today.tm_mday,
                          hour, minute, 0, 0, 0, -1))
        if at <= now:
            at += 86400
        schedule.addEvent(self._backup, at, name=name)

    def _backup(self):
        backup = self._backupPath()
        try:
            if not os.path.exists(backup) or \
                    os.path.getmtime(self._dbPath) > \
                    os.path.getmtime(backup):
                self.log.info('IRCquotes: backing up the quotes database.')
                self.db.backup(backup + '.tmp')
                os.replace(backup + '.tmp', backup)
        except (OSError, sqlite3.Error) as e:
            self.log.error('IRCquotes: backup to %s failed: %s', backup, e)
        self._scheduleBackup()

    ###
    # Periodic "random quote" announcer (port of !autorandquote).
    ###

    def _eventName(self, network, channel):
        return 'IRCquotes_autorandquote_%s_%s' % (network, channel)

    def _scheduleFor(self, irc, channel):
        interval = self.registryValue('autoRandQuoteInterval', channel,
                                      irc.network)
        name = self._eventName(irc.network, channel)
        if name in schedule.schedule.events:
            schedule.removeEvent(name)
        if not interval:
            return

        def sendRandomQuote():
            if channel in (getattr(irc.state, 'channels', {}) or {}):
                quote = self._nextRandom(irc.network, channel, auto=True)
                if quote:
                    for line in self._quoteLines(irc, channel, channel,
                                                 quote):
                        irc.queueMsg(ircmsgs.privmsg(channel, line))
            self._scheduleFor(irc, channel)

        schedule.addEvent(sendRandomQuote, time.time() + interval, name=name)

    def doJoin(self, irc, msg):
        # (Re)start the announcer the first time we see a channel we're in,
        # in case it wasn't known yet when the plugin was loaded.
        if not ircutils.strEqual(msg.nick, irc.nick):
            return
        channel = msg.args[0]
        name = self._eventName(irc.network, channel)
        if name not in schedule.schedule.events:
            self._scheduleFor(irc, channel)

    def _nextRandom(self, network, channel, auto=False):
        quotes = dict((r.id, r) for r in
                      self.db.select(network, channel, lambda r: not r.deleted))
        if auto and self.registryValue('autoRandQuoteConsidersRatings',
                                       channel, network):
            quotes = dict((id, r) for (id, r) in quotes.items()
                          if r.score >= 0)
        if not quotes:
            return None
        key = (network, QuotesDB._key(channel), auto)
        (seen, last) = self._randSeen.get(key, (set(), None))
        seen &= set(quotes)
        pool = [id for id in quotes if id not in seen]
        if not pool:
            # Everything has been shown: start a new round, but not with
            # the quote that ended the last one.
            seen = set()
            pool = [id for id in quotes if id != last] or list(quotes)
        pick = random.choice(pool)
        seen.add(pick)
        self._randSeen[key] = (seen, pick)
        return quotes[pick]

    ###
    # Flood control (port of the original's antiflood): per channel, per
    # command and for all the commands together. Over the limit, commands
    # are ignored, with a warning now and then.
    ###

    def _flooded(self, irc, msg, command):
        channel = msg.channel
        if not channel or not self.registryValue('antiflood', channel,
                                                 irc.network):
            return False
        for kind in ('global', command):
            (limit, seconds) = map(int, self.registryValue(
                'flood.' + kind, channel, irc.network).split(':'))
            key = (irc.network, ircutils.toLower(channel), kind)
            state = self._flood.setdefault(
                key, {'hits': collections.deque(), 'warned': False,
                      'warnedAt': 0})
            now = time.time()
            hits = state['hits']
            expired = False
            while hits and hits[0] <= now - seconds:
                hits.popleft()
                expired = True
            if expired:
                state['warned'] = False
            if len(hits) >= limit:
                interval = self.registryValue('antifloodMessageInterval')
                if not state['warned']:
                    state['warned'] = True
                    state['warnedAt'] = now
                    irc.reply(self._style(irc, channel,
                        self._floodWarning(irc, channel, kind, limit,
                                           seconds)), prefixNick=False)
                elif now - state['warnedAt'] >= interval:
                    state['warnedAt'] = now
                    irc.reply(self._style(irc, channel,
                        _('Flood control is still active, please try again '
                          'later.')), prefixNick=False)
                else:
                    irc.noReply()
                return True
            hits.append(now)
        return False

    def _floodWarning(self, irc, channel, kind, limit, seconds):
        if kind == 'global':
            return _('Flood control has been triggered on all commands of '
                     'IRCquotes: no more than %s command(s) every %s '
                     'seconds.') % (limit, seconds)
        command = 'quoteget' if kind == 'quote' else kind
        text = _('Flood control has been triggered on the command %s: no '
                 'more than %s command(s) every %s seconds.') % (
                     ircutils.bold(command), limit, seconds)
        url = self._quotePageUrl(irc, channel)
        if url and kind in ('quote', 'lastquote', 'findquote', 'randquote'):
            text += _(' You can access the entirety of %s\'s quotes here: '
                      '%s') % (channel, url)
        return text

    ###
    # Access checks.
    ###

    def _target(self, irc, leading, trailing):
        channel = trailing or leading
        if not channel:
            irc.error(_('You must give a channel when not in one.'),
                      Raise=True)
        return channel

    def _checkEnabled(self, irc, channel):
        if not self.registryValue('enabled', channel, irc.network):
            irc.error(_('Quotes are not enabled on channel %s.') % channel,
                      Raise=True)

    def _checkReadable(self, irc, channel):
        # The original's include_chans: channels whose quotes can be read
        # although quotes aren't enabled there.
        readable = self.registryValue('readableChannels')
        if not builtins.any(ircutils.strEqual(channel, c) for c in readable):
            self._checkEnabled(irc, channel)

    def _requireOp(self, irc, msg, channel):
        cap = ircdb.makeChannelCapability(channel, 'op')
        if not ircdb.checkCapability(msg.prefix, cap):
            irc.errorNoCapability(cap, Raise=True)

    def _requireCapability(self, irc, msg, channel, capname):
        # capname is a bare capability name (e.g. "op", "trusted"); it's
        # turned into the usual "#channel,<capability>" form. An already
        # fully-qualified capability (containing a comma, e.g.
        # "#channel,op") is accepted as-is. This is always checked against
        # ircdb (i.e. requires the user be registered with the bot and
        # granted the capability) -- deliberately not satisfied by merely
        # being opped on IRC, since that status isn't tied to any bot-side
        # identity and destructive commands (undelquote, forcedelquote,
        # deletedquoteinfo) shouldn't trust it.
        if not capname:
            return
        cap = capname if ',' in capname \
            else ircdb.makeChannelCapability(channel, capname)
        if not ircdb.checkCapability(msg.prefix, cap):
            irc.errorNoCapability(cap, Raise=True)

    def getUserId(self, irc, prefix, channel=None):
        try:
            return str(ircdb.users.getUser(prefix).id)
        except KeyError:
            if conf.get(conf.supybot.databases.plugins.requireRegistration,
                        channel=channel, network=irc.network):
                irc.errorNotRegistered(Raise=True)
            return None

    def _isAuthor(self, msg, record):
        # A registered author is matched by bot account; otherwise by nick,
        # like the original did.
        if record.by.isdigit():
            try:
                return str(ircdb.users.getUser(msg.prefix).id) == record.by
            except KeyError:
                return False
        nick = ircutils.nickFromHostmask(record.by) \
            if ircutils.isUserHostmask(record.by) else record.by
        return ircutils.strEqual(nick, msg.nick)

    ###
    # Display.
    ###

    def _userName(self, by):
        # 'by' is either a bot user id (a string of digits) or the hostmask
        # of an unregistered user; only the nick of the latter is shown,
        # as the original only ever stored the nick.
        if by.isdigit():
            try:
                return ircdb.users.getUser(int(by)).name
            except KeyError:
                return _('a user that is no longer registered')
        if ircutils.isUserHostmask(by):
            return ircutils.nickFromHostmask(by)
        return by

    def _deleterName(self, record):
        if record.deletedByAdmin:
            return _('an administrator')
        return self._userName(record.deletedBy)

    def _date(self, t):
        return time.strftime(_('%d/%m/%Y'), time.localtime(t))

    def _time(self, t):
        return time.strftime('%H:%M:%S', time.localtime(t))

    def _when(self, t):
        return '%s %s' % (self._date(t), self._time(t))

    def _noColors(self, irc, target, channel):
        if self.registryValue('monochrome', channel, irc.network):
            return True
        state = irc.state.channels.get(target) if target else None
        return state is not None and 'c' in state.modes

    def _style(self, irc, target, text):
        if self._noColors(irc, target, target):
            return ircutils.stripFormatting(text)
        return text

    def _quoteLines(self, irc, target, channel, record, multiline=True,
                    showChannel=False):
        """The lines a quote is shown as: the original's quote_id_style in
        front, one line per lineSeparator (up to maxQuoteLines) with the
        multi-line prefixes, quotesColor, and no formatting at all where
        colors are blocked (+c) or monochrome is on. target is where it's
        said, channel where the quote comes from."""
        get = lambda name: self.registryValue(name, target or channel,
                                              irc.network)
        separator = self.registryValue('lineSeparator', channel, irc.network)
        text = record.text
        color = get('quotesColor')
        if color:
            text = ircutils.stripReverse(ircutils.stripColor(text))
            text = text.replace('\x0f', '')
            color = '\x03%s\x02\x02' % color
        head = get('quoteIdStyle').replace('%id%', str(record.id))
        if showChannel:
            head = get('channelStyle').replace('%chan%', channel) + head
        lines = []
        if multiline and separator and separator in text:
            lines = [line for line in text.split(separator) if line]
        if 1 < len(lines) <= get('maxQuoteLines'):
            out = [head + color + lines[0]]
            for (n, line) in enumerate(lines[1:], 2):
                prefix = get('multilineLastPrefix') if n == len(lines) \
                    else get('multilinePrefix')
                out.append(prefix + color + line)
        else:
            alternate = get('alternateColor')
            if separator and not color and alternate:
                text = text.replace(separator, '\x03%s%s\x0f' %
                                    (alternate, separator))
            out = [head + color + text]
        if self._noColors(irc, target, target or channel):
            out = [ircutils.stripFormatting(line) for line in out]
        return out

    def _sayQuote(self, irc, msg, channel, record, multiline=True,
                  showChannel=False, **kwargs):
        for line in self._quoteLines(irc, msg.channel, channel, record,
                                     multiline, showChannel):
            irc.reply(line, prefixNick=False, **kwargs)

    def _getQuote(self, irc, channel, id, allowDeleted=False):
        """Returns quote <id>, or says why there's none (not yet added,
        purged, or deleted unless allowDeleted) and returns None."""
        try:
            record = self.db.get(irc.network, channel, id)
        except KeyError:
            maxId = self.db.maxId(irc.network, channel)
            if id > maxId:
                irc.error(format(_("The quote #%s doesn't exist yet (%n in "
                                   "%s's database)."), id,
                                 (maxId, _('quote')), channel))
            else:
                irc.error(_("The quote #%s doesn't exist anymore.") % id)
            return None
        if record.deleted and not allowDeleted:
            irc.error(_("The quote #%s doesn't exist anymore, it has been "
                        "deleted by %s on %s at %s.") % (
                id, self._deleterName(record), self._date(record.deletedAt),
                self._time(record.deletedAt)))
            return None
        return record

    def _alreadyDeleted(self, irc, record):
        irc.error(_("The quote #%s doesn't exist anymore, it has already "
                    "been deleted by %s on %s at %s.") % (
            record.id, self._deleterName(record),
            self._date(record.deletedAt), self._time(record.deletedAt)))

    def _markDeleted(self, irc, msg, channel, record, admin):
        record.deleted = True
        record.deletedBy = self.getUserId(irc, msg.prefix, channel) \
            or msg.prefix
        record.deletedAt = time.time()
        record.deletedByAdmin = admin
        record.deletedHost = msg.prefix
        self.db.set(irc.network, channel, record.id, record)

    def _ratingText(self, record):
        return _('%s (%s like, %s dislike)') % (record.score, record.likes,
                                               record.dislikes)

    ###
    # Adding quotes, including multi-line pastes caught on the fly.
    ###

    def _filterLine(self, irc, channel, line, keepTimestamps,
                    keepAttributes):
        if self.registryValue('filterTimestamps', channel, irc.network) \
                and not keepTimestamps:
            line = TIMESTAMP_RE.sub('', line)
        if self.registryValue('filterAttributes', channel, irc.network) \
                and not keepAttributes:
            line = LEADING_ATTRIBUTES_RE.sub('', line)
            line = NICK_ATTRIBUTES_RE.sub(r'\1\2', line)
        return line

    def _tooShort(self, irc, channel, text):
        minChars = self.registryValue('minQuoteChars', channel, irc.network)
        minWords = self.registryValue('minQuoteWords', channel, irc.network)
        if (minChars and len(text) < minChars) or \
                (minWords and len(text.split()) < minWords):
            limits = []
            if minChars:
                limits.append(format('%n', (minChars, _('character'))))
            if minWords:
                limits.append(format('%n', (minWords, _('word'))))
            return _("You can't add quotes with less than %s.") % \
                _(' or ').join(limits)
        return None

    def _storeQuote(self, irc, channel, by, text, lines):
        """Adds the quote and returns the reply to give."""
        id = self.db.add(irc.network, channel, time.time(), by, text)
        if lines > 1:
            return format(_('The quote #%s has been added (%n).'), id,
                          (lines, _('line')))
        return _('The quote #%s has been added.') % id

    def _sessionKey(self, network, channel):
        return (network, ircutils.toLower(channel))

    def _armSession(self, key, delay):
        name = 'IRCquotes_addquote_%s_%s' % key
        if name in schedule.schedule.events:
            schedule.removeEvent(name)
        schedule.addEvent(lambda: self._endSession(key), time.time() + delay,
                          name=name)

    def _dropSession(self, key):
        name = 'IRCquotes_addquote_%s_%s' % key
        if name in schedule.schedule.events:
            schedule.removeEvent(name)
        return self._addSessions.pop(key, None)

    def _endSession(self, key):
        session = self._dropSession(key)
        if session is None:
            return
        (irc, channel) = (session['irc'], session['channel'])
        error = self._tooShort(irc, channel, session['text'])
        if error:
            irc.queueMsg(ircmsgs.privmsg(channel, error))
            return
        irc.queueMsg(ircmsgs.privmsg(channel, self._storeQuote(
            irc, channel, session['by'], session['text'],
            session['lines'])))

    def inFilter(self, irc, msg):
        # addquote takes its text as it was typed: Limnoria's own parsing
        # would turn a pasted "[12:34] <bob> hi" into a nested command,
        # drop "quotation marks" and squeeze repeated spaces. The text is
        # kept aside and replaced with a token addquote looks for.
        if msg.command != 'PRIVMSG' or ircmsgs.isCtcp(msg):
            return msg
        payload = callbacks.addressed(irc, msg)
        match = ADDQUOTE_RE.match(payload) if payload else None
        if not match or not match.group(2) or not match.group(2).strip():
            return msg
        (command, raw) = match.groups()
        lead = ''
        words = raw.split(None, 1)
        if irc.isChannel(words[0]):
            lead = words[0] + ' '
            raw = words[1] if len(words) > 1 else ''
        text = msg.args[1]
        at = text.rfind(payload)
        if not raw.strip() or at == -1:
            return msg
        self._rawText[(irc.network, msg.prefix)] = raw.strip()
        newMsg = ircmsgs.IrcMsg(msg=msg, args=(msg.args[0], '%s%s %s%s' % (
            text[:at], command, lead, RAW_TEXT_TOKEN)))
        newMsg.channel = msg.channel
        newMsg.tags.pop('addressed', None)
        return newMsg

    def doPrivmsg(self, irc, msg):
        # The lines of a multi-line addquote, sent right after it by the
        # same person in the same channel.
        if not self._addSessions or not msg.channel:
            return
        key = self._sessionKey(irc.network, msg.channel)
        session = self._addSessions.get(key)
        if session is None or msg.prefix != session['prefix'] or \
                ircmsgs.isCtcp(msg) or callbacks.addressed(irc, msg):
            return
        channel = session['channel']
        line = msg.args[1].strip()
        if session['lines'] == 1:
            irc.queueMsg(ircmsgs.notice(msg.nick,
                _('%s > A multiline quote is being recorded... Please wait '
                  'a few seconds without typing anything else after the '
                  'last line of the quote, or end with a line containing '
                  'only "%s"') % (msg.nick, self.registryValue(
                      'multilineEndSignal', channel, irc.network))))
        if ircutils.stripFormatting(line) == self.registryValue(
                'multilineEndSignal', channel, irc.network):
            self._endSession(key)
            return
        session['lines'] += 1
        maxLines = self.registryValue('multilineMaxLines', channel,
                                      irc.network)
        if session['lines'] > maxLines:
            self._dropSession(key)
            irc.queueMsg(ircmsgs.privmsg(channel, format(
                _('You exceeded the allowed number of lines while adding a '
                  'multiline quote on the fly. Please don\'t exceed %n. The '
                  'quote has not been recorded.'), (maxLines, _('line')))))
            return
        line = self._filterLine(irc, channel, line, session['keepTimestamps'],
                                session['keepAttributes'])
        separator = self.registryValue('lineSeparator', channel,
                                       irc.network) or ' '
        session['text'] += separator + line
        self._armSession(key, self.registryValue('multilineTimeout'))

    @internationalizeDocstring
    def addquote(self, irc, msg, args, channel, text):
        """[<channel>] [--keep-timestamps] [--keep-attributes] <text>

        Adds <text> as a new quote to the quotes database for <channel>.
        Timestamps and the status symbols in front of nicks (~ & @ % +) are
        removed (see filterTimestamps/filterAttributes) unless you pass
        --keep-timestamps/--keep-attributes. When multilineAdd is on, the
        lines you paste right after this one in the channel become part of
        the same quote. If supybot.plugins.IRCquotes.addCapability is set
        (e.g. to "op"), only users with that channel capability may use
        this command; if it's left empty but requireAddRegistration is
        enabled, it defaults to requiring "op". <channel> is only necessary
        if the message isn't sent in the channel itself.
        """
        self._checkEnabled(irc, channel)
        cap = self.registryValue('addCapability', channel, irc.network)
        if not cap and self.registryValue('requireAddRegistration', channel,
                                          irc.network):
            cap = 'op'
        self._requireCapability(irc, msg, channel, cap)
        if text == RAW_TEXT_TOKEN:
            text = self._rawText.pop((irc.network, msg.prefix), '')
        if self._flooded(irc, msg, 'addquote'):
            return
        # The options are only looked for in the first two words, same as
        # the original (-keep_timestamps also works).
        keepTimestamps = keepAttributes = False
        for _i in range(2):
            match = re.match(r'\s*(\S+)\s*', text)
            if not match:
                break
            if match.group(1).lower() in KEEP_TIMESTAMPS:
                keepTimestamps = True
            elif match.group(1).lower() in KEEP_ATTRIBUTES:
                keepAttributes = True
            else:
                break
            text = text[match.end():]
        text = self._filterLine(irc, channel, text.strip(), keepTimestamps,
                                keepAttributes).strip()
        if not text:
            raise callbacks.ArgumentError
        by = self.getUserId(irc, msg.prefix, channel) or msg.prefix
        key = self._sessionKey(irc.network, channel)
        if self.registryValue('multilineAdd', channel, irc.network) and \
                msg.channel and ircutils.strEqual(msg.channel, channel):
            if key in self._addSessions:
                irc.error(_('A quote is currently being recorded. Please try '
                            'again in a few moments.'))
                return
            self._addSessions[key] = {
                'irc': irc.getRealIrc(), 'channel': channel,
                'prefix': msg.prefix, 'by': by, 'text': text, 'lines': 1,
                'keepTimestamps': keepTimestamps,
                'keepAttributes': keepAttributes,
            }
            # A short wait for the first extra line, which shouldn't be
            # held back by fake lag yet; multilineTimeout after that.
            self._armSession(key, 1)
            irc.noReply()
            return
        error = self._tooShort(irc, channel, text)
        if error:
            irc.error(error, Raise=True)
        irc.reply(self._storeQuote(irc, channel, by, text, 1))
    addquote = wrap(addquote, ['channel', 'text'])

    ###
    # Reading quotes.
    ###

    @internationalizeDocstring
    def quoteget(self, irc, msg, args, channel, id, trailing):
        """[<channel>] <id> [<channel>]

        Shows quote <id> from <channel>'s quotes database. <channel> is only
        necessary if the message isn't sent in the channel itself.
        """
        channel = self._target(irc, channel, trailing)
        self._checkReadable(irc, channel)
        if self._flooded(irc, msg, 'quote'):
            return
        record = self._getQuote(irc, channel, id)
        if record is not None:
            self._sayQuote(irc, msg, channel, record)
    quoteget = wrap(quoteget, ['ircquotesChannel', 'id',
                               'ircquotesTrailingChannel'])

    @internationalizeDocstring
    def quoteinfo(self, irc, msg, args, channel, id, trailing):
        """[<channel>] <id> [<channel>]

        Says who added quote <id> and when, and its rating.
        """
        channel = self._target(irc, channel, trailing)
        self._checkReadable(irc, channel)
        if self._flooded(irc, msg, 'quoteinfo'):
            return
        record = self._getQuote(irc, channel, id, allowDeleted=True)
        if record is None:
            return
        votes = self.registryValue('votesEnabled', channel, irc.network)
        if record.deleted:
            rating = _(' Its popularity rating was %s.') % \
                self._ratingText(record) if votes else ''
            irc.reply(_("The quote #%s doesn't exist anymore, it has been "
                        "deleted by %s on %s at %s.%s") % (
                id, self._deleterName(record), self._date(record.deletedAt),
                self._time(record.deletedAt), rating))
        else:
            rating = _(' Its popularity rating is %s.') % \
                self._ratingText(record) if votes else ''
            irc.reply(_('The quote #%s has been added by %s on %s at %s.%s')
                      % (id, self._userName(record.by),
                         self._date(record.at), self._time(record.at),
                         rating))
    quoteinfo = wrap(quoteinfo, ['ircquotesChannel', 'id',
                                 'ircquotesTrailingChannel'])

    @internationalizeDocstring
    def randquote(self, irc, msg, args, channel, trailing):
        """[<channel>]

        Shows a random quote from <channel>'s quotes database. No quote is
        shown twice until all of them have been. <channel> is only
        necessary if the message isn't sent in the channel itself.
        """
        channel = self._target(irc, channel, trailing)
        self._checkReadable(irc, channel)
        if self._flooded(irc, msg, 'randquote'):
            return
        record = self._nextRandom(irc.network, channel)
        if record is None:
            irc.error(_('No valid quote has been found.'))
        else:
            self._sayQuote(irc, msg, channel, record)
    randquote = wrap(randquote, ['ircquotesChannel',
                                 'ircquotesTrailingChannel'])

    @internationalizeDocstring
    def lastquote(self, irc, msg, args, channel, rest):
        """[<channel>] [-<index>]

        Shows the latest quote added to <channel>'s quotes database. -1
        shows the one before it, -2 the one before that, and so on (a plain
        <n> shows the n-th latest, 1 being the latest). Deleted quotes are
        skipped. <channel> is only necessary if the message isn't sent in
        the channel itself.
        """
        index = place = None
        for arg in rest:
            if index is None and re.match(r'^-\d+$', arg):
                index = int(arg[1:])
            elif index is None and arg.isdigit():
                index = max(int(arg) - 1, 0)
            elif place is None and irc.isChannel(arg):
                place = arg
            else:
                raise callbacks.ArgumentError
        channel = self._target(irc, channel, place)
        self._checkReadable(irc, channel)
        if self._flooded(irc, msg, 'lastquote'):
            return
        records = list(self.db.select(irc.network, channel, lambda r: True,
                                      reverse=True))
        valid = [r for r in records if not r.deleted]
        if index is None:
            if records and records[0].deleted:
                newest = records[0]
                irc.reply(_("The latest quote (#%s) doesn't exist anymore, "
                            "it has been deleted by %s on %s at %s. Looking "
                            "for the latest valid quote...") % (
                    newest.id, self._deleterName(newest),
                    self._date(newest.deletedAt),
                    self._time(newest.deletedAt)))
            index = 0
        elif valid and index >= len(valid):
            irc.error(_("The quote you asked for doesn't exist. The index "
                        "can't exceed -%s.") % (len(valid) - 1))
            return
        if not valid:
            irc.error(_('No valid quote has been found.'))
            return
        self._sayQuote(irc, msg, channel, valid[index])
    lastquote = wrap(lastquote, ['ircquotesChannel', any('something')])

    @internationalizeDocstring
    def findquote(self, irc, msg, args, channel, tokens):
        """[<channel>] [--all] [--by <user>] <search terms>

        Searches <channel>'s quotes for the ones containing every one of
        <search terms> (case and accents don't matter; * and ? are plain
        characters). Put "quotation marks" around words to search for that
        exact phrase. --all searches every channel's quotes; --by only
        finds quotes added by <user>. Lists the numbers of all the matches
        and shows the most recent ones in full.
        """
        # The options are parsed here rather than with getopts, which
        # would take the original's -all for -a -l -l.
        allChannels = False
        by = None
        while tokens and tokens[0].lower() in ('--all', '-all', '--by'):
            option = tokens.pop(0).lower()
            if option == '--by':
                if not tokens:
                    raise callbacks.ArgumentError
                try:
                    by = ircdb.users.getUser(tokens.pop(0))
                except KeyError:
                    irc.errorNoUser(Raise=True)
            else:
                allChannels = True
        # Limnoria's parser already turned "an exact phrase" into a single
        # token (and refuses unbalanced quotation marks), so every token is
        # one search term.
        text = ' '.join(tokens)
        if not tokens and by is None:
            raise callbacks.ArgumentError
        if not all(tokens):
            irc.error(_('You used "" in your search criteria; it means an '
                        'empty exact search, which findquote doesn\'t '
                        'allow. You must include some text between the '
                        'quotation marks. Example: findquote "a test"'),
                      Raise=True)
        minChars = self.registryValue('findQuoteMinChars')
        if text and len(text) < minChars:
            irc.error(_('Your search criteria must contain at least %s '
                        'characters.') % minChars, Raise=True)
        if allChannels:
            readable = self.registryValue('readableChannels')
            channels = [c for c in self.db.channels(irc.network)
                        if self.registryValue('enabled', c, irc.network) or
                        builtins.any(ircutils.strEqual(c, r) for r in readable)]
        else:
            if not channel:
                irc.error(_('You must give a channel when not in one.'),
                          Raise=True)
            self._checkReadable(irc, channel)
            channels = [channel]
        if self._flooded(irc, msg, 'findquote'):
            return
        terms = [searchable(token) for token in tokens]

        def matches(record):
            if record.deleted:
                return False
            if by is not None and record.by != str(by.id):
                return False
            haystack = searchable(record.text)
            return all(term in haystack for term in terms)

        results = [(c, r) for c in channels
                   for r in self.db.select(irc.network, c, matches)]
        n = len(results)
        if not n:
            if len(tokens) > 1 and (irc.isChannel(tokens[-1]) or
                                    tokens[-1].lower() == '-all'):
                irc.reply(_('The search yielded no results. After analyzing '
                            'your search criteria, it appears that you may '
                            'have switched their order. The correct syntax '
                            'is: findquote [<channel>] [--all] <search '
                            'terms>.'))
            else:
                irc.reply(_('The search yielded no results.'))
            return
        maxResults = self.registryValue('findQuoteMaxResults', channel,
                                        irc.network)
        if maxResults and n > maxResults:
            irc.error(_('The search yielded more than %s results (precisely '
                        '%s). Please try to be more precise in order to '
                        'reduce the number of results.') % (maxResults, n))
            return
        alternate = self.registryValue('alternateColor', msg.channel,
                                       irc.network)
        if n == 1:
            if allChannels:
                irc.reply(_('1 result has been found on %s:') % results[0][0])
            else:
                irc.reply(_('1 result has been found:'))
        elif allChannels:
            irc.reply(_('%s results have been found on the following '
                        'channels: %s') % (
                n, ' '.join(sorted(set(c for (c, r) in results)))))
            irc.reply(_('Recent quotes:'))
        else:
            separator = '\x03%s|\x03\x02\x02' % alternate if alternate \
                else '|'
            ids = separator.join(str(r.id) for (c, r) in results)
            irc.reply(self._style(irc, msg.channel,
                                  _('%s results have been found: %s') %
                                  (n, ids)))
            irc.reply(_('Recent quotes:'))
        recent = sorted(results, key=lambda cr: (cr[1].at, cr[1].id),
                        reverse=True)
        multiline = n <= self.registryValue('splitFindQuotesUpTo', channel,
                                            irc.network)
        for (c, record) in recent[:self.registryValue('findQuoteRecent',
                                                      channel, irc.network)]:
            self._sayQuote(irc, msg, c, record, multiline,
                           showChannel=allChannels)
    findquote = wrap(findquote, ['ircquotesChannel', any('anything')])

    ###
    # Votes.
    ###

    def _voters(self, record):
        # "voter=direction" entries; old data (a bare voter with no
        # '=direction') is treated as a legacy '+' vote.
        voters = {}
        for entry in record.voters.split(','):
            if not entry:
                continue
            (voter, _sep, direction) = entry.partition('=')
            voters[voter] = direction or '+'
        return voters

    @internationalizeDocstring
    def votequote(self, irc, msg, args, channel, id, trailing, direction):
        """[<channel>] <id> [<channel>] [+|-|0]

        Without +, - or 0, shows the rating of quote <id> and how you voted
        for it. '+' likes it, '-' dislikes it, and '0' cancels your vote
        (see canChangeVote). <channel> is only necessary if the message
        isn't sent in the channel itself.
        """
        external = msg.channel is None or \
            not ircutils.strEqual(trailing or channel or '', msg.channel)
        channel = self._target(irc, channel, trailing)
        self._checkReadable(irc, channel)
        if not self.registryValue('votesEnabled', channel, irc.network):
            irc.error(_('The quotes rating system is currently disabled on '
                        '%s.') % channel, Raise=True)
        canChange = self.registryValue('canChangeVote', channel, irc.network)
        if direction == '0' and not canChange:
            raise callbacks.ArgumentError
        if self._flooded(irc, msg, 'votequote'):
            return
        try:
            userId = str(ircdb.users.getUser(msg.prefix).id)
        except KeyError:
            userId = None
        if direction is not None:
            if userId is None and self.registryValue(
                    'requireVoteRegistration', channel, irc.network):
                irc.error(_('You must be a registered user on %s before you '
                            'can vote for a quote.') % irc.nick, Raise=True)
            if self.registryValue('requireVoteAccount', channel,
                                  irc.network):
                try:
                    account = irc.state.nickToAccount(msg.nick)
                except KeyError:
                    irc.error(_('I can\'t tell yet whether you\'re '
                                'identified to services; please try again '
                                'in a few moments.'), Raise=True)
                if not account:
                    irc.error(_('You must identify to services before you '
                                'can vote for a quote.'), Raise=True)
        record = self._getQuote(irc, channel, id, allowDeleted=True)
        if record is None:
            return
        if record.deleted:
            if external:
                irc.error(_("The quote #%s doesn't exist anymore on %s.") %
                          (id, channel))
            else:
                irc.error(_("The quote #%s doesn't exist anymore.") % id)
            return
        voters = self._voters(record)
        # A previous vote is found by bot account, by *!ident@*.domain, or
        # (old data) by the exact hostmask it was cast from.
        mask = voterMask(msg.prefix)
        previousKey = None
        for key in (userId, mask, msg.prefix):
            if key and key in voters:
                previousKey = key
                break
        previous = voters.get(previousKey)
        already = {'+': _('You have already liked that quote.'),
                   '-': _('You have already disliked that quote.')}

        if direction is None:
            irc.reply(_('The quote #%s is rated %s. %s') % (
                id, self._ratingText(record),
                already.get(previous,
                            _('You have not yet rated that quote.'))))
            return
        if external and not self.registryValue('canVoteExternalQuotes',
                                               channel, irc.network):
            irc.error(_('The possibility to rate quotes from other channels '
                        'has been disabled by an administrator.'))
            return
        if previous is not None and (previous == direction or
                                     not canChange):
            irc.error(already[previous])
            return

        def count(d, n):
            if d == '+':
                record.likes = max(0, record.likes + n)
            elif d == '-':
                record.dislikes = max(0, record.dislikes + n)

        if direction == '0':
            if previous is None:
                irc.error(_('You have not yet rated that quote and therefore '
                            'can\'t cancel your vote.'))
                return
            count(previous, -1)
            del voters[previousKey]
            reply = _('Your previous vote has been canceled. The quote #%s '
                      'is now rated %s.')
        else:
            if previous is not None:
                count(previous, -1)
                del voters[previousKey]
                reply = _('Your previous vote has been modified. The quote '
                          '#%s is now rated %s.')
            else:
                reply = _('Vote accepted. The quote #%s is now rated %s.')
            count(direction, 1)
            voters[userId or mask] = direction
        record.voters = ','.join('%s=%s' % kv for kv in voters.items())
        self.db.set(irc.network, channel, id, record)
        irc.reply(reply % (id, self._ratingText(record)))
    votequote = wrap(votequote, ['ircquotesChannel', 'id',
                                 'ircquotesTrailingChannel',
                                 optional(('literal', ('+', '-', '0')))])

    ###
    # Deleting quotes.
    ###

    @internationalizeDocstring
    def delquote(self, irc, msg, args, channel, id):
        """[<channel>] <id>

        Deletes quote <id>. You can only delete a quote you added yourself;
        ops use forcedelquote. The quote keeps its number (numbering never
        shifts) and can be brought back with undelquote. <channel> is only
        necessary if the message isn't sent in the channel itself.
        """
        self._checkEnabled(irc, channel)
        if self._flooded(irc, msg, 'delquote'):
            return
        record = self._getQuote(irc, channel, id, allowDeleted=True)
        if record is None:
            return
        if record.deleted:
            self._alreadyDeleted(irc, record)
            return
        if not self._isAuthor(msg, record):
            irc.error(_('You are not allowed to delete this quote. It has '
                        'been added by %s.') % self._userName(record.by))
            return
        self._markDeleted(irc, msg, channel, record, admin=False)
        irc.reply(_('The quote #%s has been deleted.') % id)
    delquote = wrap(delquote, ['channel', 'id'])

    @internationalizeDocstring
    def forcedelquote(self, irc, msg, args, channel, id):
        """[<channel>] <id>

        Deletes quote <id> even if you didn't add it; it's shown as deleted
        by an administrator. Like delquote, it can be undone with
        undelquote. Requires being a channel op.
        """
        self._checkEnabled(irc, channel)
        self._requireOp(irc, msg, channel)
        record = self._getQuote(irc, channel, id, allowDeleted=True)
        if record is None:
            return
        if record.deleted:
            self._alreadyDeleted(irc, record)
            return
        self._markDeleted(irc, msg, channel, record, admin=True)
        irc.reply(_('The quote #%s has been deleted.') % id)
    forcedelquote = wrap(forcedelquote, ['channel', 'id'])

    @internationalizeDocstring
    def cancelquote(self, irc, msg, args, channel, id):
        """[<channel>] <id>

        Cancels the latest quote added to <channel>, leaving no trace of it;
        its number will be given to the next quote. <id> must be the latest
        quote's number, so no other quote gets removed by mistake. Requires
        being a channel op.
        """
        self._checkEnabled(irc, channel)
        self._requireOp(irc, msg, channel)
        latest = self.db.maxId(irc.network, channel)
        if not latest or id != latest:
            irc.error(_('The specified quote number doesn\'t match the latest '
                        'quote number. In order to prevent accidental '
                        'deletion of a quote, you must specify the latest '
                        'quote number.'), Raise=True)
        record = self.db.get(irc.network, channel, latest)
        self.db.remove(irc.network, channel, latest)
        if record.deleted:
            irc.reply(_('The latest quote has been canceled. This quote was '
                        'deleted by %s on %s at %s.') % (
                self._deleterName(record), self._date(record.deletedAt),
                self._time(record.deletedAt)))
            return
        irc.reply(_('The latest quote has been canceled:'))
        self._sayQuote(irc, msg, channel, record,
                       multiline=self.registryValue(
                           'multilineOnAdminCommands', channel, irc.network))
    cancelquote = wrap(cancelquote, ['channel', 'id'])

    @internationalizeDocstring
    def undelquote(self, irc, msg, args, channel, id):
        """[<channel>] <id>

        Restores quote <id>, deleted with delquote or forcedelquote.
        Requires being a channel op.
        """
        self._checkEnabled(irc, channel)
        self._requireOp(irc, msg, channel)
        record = self._getQuote(irc, channel, id, allowDeleted=True)
        if record is None:
            return
        if not record.deleted:
            irc.error(_('The quote exists and therefore doesn\'t need to be '
                        'restored.'))
            return
        record.deleted = record.deletedByAdmin = False
        record.deletedBy = record.deletedHost = ''
        record.deletedAt = 0
        self.db.set(irc.network, channel, id, record)
        irc.reply(_('The quote #%s has been restored.') % id)
    undelquote = wrap(undelquote, ['channel', 'id'])

    @internationalizeDocstring
    def deletedquoteinfo(self, irc, msg, args, channel, id):
        """[<channel>] <id>

        Tells you, in private, who deleted quote <id> and when, who had
        added it, and what it said. Requires being a channel op.
        """
        self._checkEnabled(irc, channel)
        self._requireOp(irc, msg, channel)
        record = self._getQuote(irc, channel, id, allowDeleted=True)
        if record is None:
            return
        if not record.deleted:
            irc.error(_("The quote #%s exists. You'd rather use quoteinfo.")
                      % id)
            return
        irc.reply(_('The quote #%s has been deleted by %s (%s) on %s at %s. '
                    'The quote was added by %s on %s at %s. Here is the '
                    'deleted quote:') % (
            id, self._deleterName(record),
            record.deletedHost or self._userName(record.deletedBy),
            self._date(record.deletedAt), self._time(record.deletedAt),
            self._userName(record.by), self._date(record.at),
            self._time(record.at)), private=True, notice=True)
        for line in self._quoteLines(irc, None, channel, record,
                                     self.registryValue(
                                         'multilineOnAdminCommands', channel,
                                         irc.network)):
            irc.reply(line, private=True, notice=True, prefixNick=False)
    deletedquoteinfo = wrap(deletedquoteinfo, ['channel', 'id'])

    ###
    # Stats and the web page.
    ###

    @internationalizeDocstring
    def quotestats(self, irc, msg, args, channel):
        """[<channel>]

        Returns the number of quotes in <channel>'s quotes database.
        <channel> is only necessary if the message isn't sent in the channel
        itself.
        """
        self._checkEnabled(irc, channel)
        n = self.db.size(irc.network, channel)
        reply = format(_('There %b %n in my database.'), n, (n, 'quote'))
        url = self._quotePageUrl(irc, channel)
        if url:
            reply += _(' View %s quotes at %s') % (channel, url)
        irc.reply(reply)
    quotestats = wrap(quotestats, ['channel'])

    def _quotePageUrl(self, irc, channel):
        # web.publicUrl is just the base the reverse proxy (or the bot's
        # own HTTP server) serves IRCquotes from, e.g.
        # "https://quotes.example.com/ircquotes/" -- the network/channel
        # segments of the actual page URL are appended here, so admins
        # only have to set the base once instead of a full URL per
        # channel.
        base = self.registryValue('web.publicUrl', channel, irc.network)
        if not base:
            return None
        if not base.endswith('/'):
            base += '/'
        return '%s%s/%s/' % (base, utils.web.urlquote(irc.network),
                              utils.web.urlquote(channel))

    @internationalizeDocstring
    def quotepage(self, irc, msg, args, channel):
        """[<channel>]

        Shows the URL where <channel>'s quotes can be browsed on the web,
        if supybot.plugins.IRCquotes.web.publicUrl has been configured for
        it.
        """
        self._checkEnabled(irc, channel)
        url = self._quotePageUrl(irc, channel)
        if url:
            irc.reply(_('%s Quotes: %s') % (channel, url))
        else:
            irc.error(_('No web page has been configured for %s.') %
                      channel)
    quotepage = wrap(quotepage, ['channel'])


Class = IRCquotes


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
