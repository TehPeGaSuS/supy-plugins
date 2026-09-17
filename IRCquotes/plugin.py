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
import time
import string
import sqlite3
import fnmatch
import threading
import html as html_escape
import urllib.parse

import supybot.conf as conf
import supybot.ircdb as ircdb
import supybot.ircutils as ircutils
import supybot.utils as utils
import supybot.world as world
import supybot.schedule as schedule
import supybot.callbacks as callbacks
import supybot.httpserver as httpserver
from supybot.commands import *
from supybot.i18n import PluginInternationalization, internationalizeDocstring
_ = PluginInternationalization('IRCquotes')


class QuoteRecord:
    """A single quote. Unlike a dbi Record, this is a plain attribute bag
    backed by a row in QuotesDB -- there's no automatic serialization
    magic to it."""
    __slots__ = ('id', 'at', 'by', 'text', 'likes', 'dislikes', 'voters',
                 'deleted', 'deletedBy', 'deletedAt')

    def __init__(self, id, at, by, text, likes=0, dislikes=0, voters='',
                 deleted=False, deletedBy='', deletedAt=0):
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


class QuotesDB:
    """One global SQLite database for every network and channel, keyed by
    (network, channel, id).

    This is deliberately not Limnoria's usual per-channel dbi flat-file
    plugin database: those key storage by channel name *alone*, so if the
    bot is on multiple networks that each have (say) a #software channel,
    they would all collide on the exact same file and share one quote
    list. Keying by (network, channel) keeps them independent while still
    living in a single file on disk."""

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

    def close(self):
        with self._lock:
            self._conn.close()

    @staticmethod
    def _rowToRecord(row):
        (_network, _channel, id, at, by, text, likes, dislikes, voters,
         deleted, deletedBy, deletedAt) = row
        return QuoteRecord(id, at, by, text, likes, dislikes, voters,
                            deleted, deletedBy, deletedAt)

    def add(self, network, channel, at, by, text):
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
        cur = self._conn.execute(
            "SELECT * FROM quotes WHERE network=? AND channel=? AND id=?",
            (network, channel, id))
        row = cur.fetchone()
        if row is None:
            raise KeyError(id)
        return self._rowToRecord(row)

    def set(self, network, channel, id, record):
        with self._lock:
            cur = self._conn.execute(
                "UPDATE quotes SET at=?, by=?, text=?, likes=?, dislikes=?, "
                "voters=?, deleted=?, deletedBy=?, deletedAt=? "
                "WHERE network=? AND channel=? AND id=?",
                (record.at, record.by, record.text, record.likes,
                 record.dislikes, record.voters, int(record.deleted),
                 record.deletedBy, record.deletedAt, network, channel, id))
            self._conn.commit()
            if cur.rowcount == 0:
                raise KeyError(id)

    def remove(self, network, channel, id):
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM quotes WHERE network=? AND channel=? AND id=?",
                (network, channel, id))
            self._conn.commit()
            if cur.rowcount == 0:
                raise KeyError(id)

    def select(self, network, channel, predicate, reverse=False):
        order = 'DESC' if reverse else 'ASC'
        cur = self._conn.execute(
            "SELECT * FROM quotes WHERE network=? AND channel=? "
            "ORDER BY id %s" % order, (network, channel))
        for row in cur.fetchall():
            record = self._rowToRecord(row)
            if predicate(record):
                yield record

    def random(self, network, channel):
        cur = self._conn.execute(
            "SELECT * FROM quotes WHERE network=? AND channel=? "
            "AND deleted=0 ORDER BY RANDOM() LIMIT 1", (network, channel))
        row = cur.fetchone()
        return self._rowToRecord(row) if row else None

    def size(self, network, channel):
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
    <footer class="pagefooter">""" + _('IRCquotes, ported from Public '
                                        'Quotes System') + """</footer>""",
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
@media (max-width: 480px) {
    .infobar { flex-direction: column; gap: 2px; }
}
""",
}
httpserver.set_default_templates(DEFAULT_TEMPLATES)


class IRCquotesWebCallback(httpserver.SupyHTTPServerCallback):
    name = 'IRCquotes web interface'

    def _renderQuote(self, record, username):
        rating = (
            _('Likes: <span class="positiverating">%d</span>') % record.likes
            + ' | ' +
            _('Dislikes: <span class="negativerating">%d</span>') %
                record.dislikes
        )
        return """\
<div class="quote">
  <span class="quoteid">#%(id)s</span>
  <span class="quoterating">%(rating)s</span>
  <div class="quotetext">%(text)s</div>
  <span class="quoteauthor">%(author)s</span> -
  <span class="quotetimestamp">%(at)s</span>
</div>""" % {
            'id': record.id,
            'rating': rating,
            'text': html_escape.escape(record.text).replace('\n', '<br/>'),
            'author': html_escape.escape(username),
            'at': utils.str.timestamp(record.at),
        }

    def _renderNetworkCards(self):
        # One card per connected network, listing the channels there whose
        # quotes have been opted into being browsable (web.channel).
        channelsByNetwork = {}
        for irc in world.ircs:
            channels = sorted(
                channel for channel in irc.state.channels
                if self._plugin.registryValue('web.channel', channel))
            if channels:
                channelsByNetwork[irc.network] = channels
        if not channelsByNetwork:
            return '<p class="no-networks">%s</p>' % \
                html_escape.escape(_('No channels are browsable here yet.'))
        cards = []
        for network in sorted(channelsByNetwork):
            links = '\n'.join(
                '    <li><a href="/ircquotes/%s/">%s</a></li>' % (
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
        channel = utils.web.urlunquote(parts[0])
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

        # Quotes are keyed by (network, channel), so we need to know which
        # network this channel belongs to. If the same channel name is
        # web-enabled on more than one network, this will only ever show
        # whichever one the bot happens to find first.
        irc = None
        for candidate in world.ircs:
            if channel in candidate.state.channels:
                irc = candidate
                break
        irc = irc or (world.ircs[0] if world.ircs else None)
        network = irc.network if irc else _('unknown')
        botnick = irc.nick if irc else _('unknown')

        records = list(self._plugin.db.select(
            network, channel, lambda r: not r.deleted, reverse=True))

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
            rows = '\n'.join(
                self._renderQuote(r, self._plugin._getUserName(r.by))
                for r in pageRecords)
        else:
            rows = '<p>%s</p>' % _('No quotes yet.')

        # "Top quotes" panel: the best-rated quotes, ported from the
        # original's toggleable, count-configurable html_show_best_rated_
        # quotes/%TOPQUOTES% feature. Only shown once something has
        # actually been rated (and if enabled for this channel), and only
        # on the first page (same as the original).
        topQuotesEnabled = self._plugin.registryValue(
            'web.topQuotesEnabled', channel)
        topQuotesCount = self._plugin.registryValue(
            'web.topQuotesCount', channel)
        rated = [r for r in records if r.likes or r.dislikes]
        rated.sort(key=lambda r: (r.likes - r.dislikes), reverse=True)
        top = rated[:topQuotesCount] if (topQuotesEnabled and pageNum == 1) \
            else []
        if top:
            top_rows = '\n'.join(
                self._renderQuote(r, self._plugin._getUserName(r.by))
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
            })

    def doPost(self, handler, path, form):
        if 'chan' in form:
            self.send_response(303)
            self.send_header('Location',
                './%s/' % utils.web.urlquote(form['chan'].value))
            self.end_headers()
        else:
            self.send_response(400)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.write("Missing field 'chan'.")


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
        self.db = QuotesDB(os.path.join(dbDir, 'ircquotes.db'))
        for channel in getattr(irc.state, 'channels', {}) or {}:
            self._scheduleFor(irc, channel)
        self._http_running = False
        conf.supybot.plugins.IRCquotes.web.enable.addCallback(
            self._doHttpConf)
        if self.registryValue('web.enable'):
            self._startHttp()

    def die(self):
        for name in list(schedule.schedule.events):
            if name.startswith('IRCquotes_autorandquote_'):
                schedule.removeEvent(name)
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
    # Periodic "random quote" announcer (port of !autorandquote).
    ###

    def _eventName(self, network, channel):
        return 'IRCquotes_autorandquote_%s_%s' % (network, channel)

    def _scheduleFor(self, irc, channel):
        import supybot.ircmsgs as ircmsgs
        interval = conf.supybot.plugins.IRCquotes.autoRandQuoteInterval.getSpecific(
            irc.network, channel)()
        name = self._eventName(irc.network, channel)
        if name in schedule.schedule.events:
            schedule.removeEvent(name)
        if not interval:
            return

        def sendRandomQuote():
            quote = self.db.random(irc.network, channel)
            if quote and channel in (getattr(irc.state, 'channels', {}) or {}):
                irc.sendMsg(ircmsgs.privmsg(channel, self.showRecord(quote)))
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

    ###
    # Quote commands. These are thin, legacy-named wrappers around the
    # generic ChannelIdDatabasePlugin commands (add/get/remove/random/
    # search), plus the extra voting and "last quote" features.
    ###

    def _checkEnabled(self, irc, channel):
        if not conf.supybot.plugins.IRCquotes.enabled.getSpecific(
                irc.network, channel)():
            irc.error(_('Quotes are disabled in %s.') % channel, Raise=True)

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

    def _getUserName(self, by):
        # 'by' is always a string: either a bot user id (as a string of
        # digits) or a raw hostmask, depending on whether the poster was
        # registered with the bot at add-time.
        try:
            userId = int(by)
        except (TypeError, ValueError):
            return by
        try:
            return ircdb.users.getUser(userId).name
        except KeyError:
            return _('a user that is no longer registered')

    def checkChangeAllowed(self, irc, msg, channel, user, record):
        if user == record.by:
            return True
        cap = ircdb.makeChannelCapability(channel, 'op')
        if ircdb.checkCapability(msg.prefix, cap):
            return True
        irc.errorNoCapability(cap)

    def noSuchRecord(self, irc, channel, id):
        irc.error(_('There is no quote with id #%s in my database for '
                    '%s.') % (id, channel))

    def searchSerializeRecord(self, record):
        text = utils.str.ellipsisify(record.text, 50)
        return format(_('#%s: %q'), record.id, text)

    def showRecord(self, record):
        # Deleted quotes keep their id and slot in the database (so
        # numbering never shifts, same as the original script), but their
        # content is hidden from normal display.
        if record.deleted:
            return _('#%s: (This quote has been deleted)') % record.id
        template = string.Template(conf.supybot.replies.databaseRecord())
        username = self._getUserName(record.by)
        nick = username.split('!')[0] # nick==username iff registered
        return template.substitute(
            id=record.id,
            text=utils.str.quoted(record.text),
            userid=record.by,
            username=username,
            nick=nick,
            at=utils.str.timestamp(record.at),
            Types=_('Quotes'), Type=_('Quote'),
            types=_('quotes'), type=_('quote'))

    @internationalizeDocstring
    def addquote(self, irc, msg, args, channel, text):
        """[<channel>] <text>

        Adds <text> as a new quote to the quotes database for <channel>.
        If supybot.plugins.IRCquotes.addCapability is set (e.g. to "op"),
        only users with that channel capability may use this command; if
        it's left empty but requireAddRegistration is enabled, it defaults
        to requiring "op". <channel> is only necessary if the message
        isn't sent in the channel itself.
        """
        self._checkEnabled(irc, channel)
        cap = self.registryValue('addCapability', channel)
        if not cap and self.registryValue('requireAddRegistration', channel):
            cap = 'op'
        self._requireCapability(irc, msg, channel, cap)
        user = self.getUserId(irc, msg.prefix, channel) or msg.prefix
        at = time.time()
        id = self.db.add(irc.network, channel, at, user, text)
        irc.replySuccess(_('Quote #%s added.') % id)
    addquote = wrap(addquote, ['channel', 'text'])

    @internationalizeDocstring
    def quoteget(self, irc, msg, args, channel, id):
        """[<channel>] <id>

        Returns the quote with id <id> from <channel>'s quotes database.
        <channel> is only necessary if the message isn't sent in the channel
        itself.
        """
        self._checkEnabled(irc, channel)
        try:
            record = self.db.get(irc.network, channel, id)
            irc.reply(self.showRecord(record))
        except KeyError:
            self.noSuchRecord(irc, channel, id)
    quoteget = wrap(quoteget, ['channel', 'id'])

    @internationalizeDocstring
    def quoteinfo(self, irc, msg, args, channel, id):
        """[<channel>] <id>

        Returns metadata (author, timestamp, votes) about the quote with id
        <id> in <channel>'s quotes database.
        """
        self._checkEnabled(irc, channel)
        try:
            record = self.db.get(irc.network, channel, id)
        except KeyError:
            self.noSuchRecord(irc, channel, id)
            return
        if record.deleted:
            irc.reply(self.showRecord(record))
            return
        username = self._getUserName(record.by)
        irc.reply(_('Quote #%s added by %s on %s; %s like(s), '
                    '%s dislike(s).') %
                  (record.id, username, utils.str.timestamp(record.at),
                   record.likes, record.dislikes))
    quoteinfo = wrap(quoteinfo, ['channel', 'id'])

    @internationalizeDocstring
    def deletedquoteinfo(self, irc, msg, args, channel, id):
        """[<channel>] <id>

        Shows full details (including the original text) about a deleted
        quote: who added it, who deleted it, and when. Requires being a
        channel op.
        """
        self._checkEnabled(irc, channel)
        self._requireOp(irc, msg, channel)
        try:
            record = self.db.get(irc.network, channel, id)
        except KeyError:
            self.noSuchRecord(irc, channel, id)
            return
        if not record.deleted:
            irc.error(_('Quote #%s has not been deleted.') % id)
            return
        author = self._getUserName(record.by)
        deleter = self._getUserName(record.deletedBy)
        irc.reply(_('Quote #%s (added by %s on %s, deleted by %s on %s): '
                    '%s') % (
            record.id, author, utils.str.timestamp(record.at),
            deleter, utils.str.timestamp(record.deletedAt),
            utils.str.quoted(record.text)))
    deletedquoteinfo = wrap(deletedquoteinfo, ['channel', 'id'])

    @internationalizeDocstring
    def delquote(self, irc, msg, args, channel, id):
        """[<channel>] <id>

        Marks the quote with id <id> as deleted in <channel>'s quotes
        database. You must be the original author of the quote, or a
        channel op, to delete it (same as the original script's
        author-or-admin rule). The quote keeps its id and slot in the
        database (so numbering never shifts) but its content is hidden;
        see undelquote to restore it, or forcedelquote to purge it for
        good. <channel> is only necessary if the message isn't sent in the
        channel itself.
        """
        self._checkEnabled(irc, channel)
        user = self.getUserId(irc, msg.prefix, channel) or msg.prefix
        try:
            record = self.db.get(irc.network, channel, id)
            self.checkChangeAllowed(irc, msg, channel, user, record)
            if record.deleted:
                irc.error(_('Quote #%s is already deleted.') % id)
                return
            record.deleted = True
            record.deletedBy = user
            record.deletedAt = time.time()
            self.db.set(irc.network, channel, id, record)
            irc.replySuccess()
        except KeyError:
            self.noSuchRecord(irc, channel, id)
    delquote = wrap(delquote, ['channel', 'id'])

    @internationalizeDocstring
    def undelquote(self, irc, msg, args, channel, id):
        """[<channel>] <id>

        Restores a quote previously removed with delquote. Requires being
        a channel op (in the original script, undelquote/forcedelquote/
        deletedquoteinfo were all master/channel-master-only, unlike the
        looser author-or-op delquote). <channel> is only necessary if the
        message isn't sent in the channel itself.
        """
        self._checkEnabled(irc, channel)
        self._requireOp(irc, msg, channel)
        try:
            record = self.db.get(irc.network, channel, id)
            if not record.deleted:
                irc.error(_('Quote #%s is not deleted.') % id)
                return
            record.deleted = False
            record.deletedBy = ''
            record.deletedAt = 0
            self.db.set(irc.network, channel, id, record)
            irc.replySuccess()
        except KeyError:
            self.noSuchRecord(irc, channel, id)
    undelquote = wrap(undelquote, ['channel', 'id'])

    @internationalizeDocstring
    def forcedelquote(self, irc, msg, args, channel, id):
        """[<channel>] <id>

        Permanently purges the quote with id <id> from <channel>'s quotes
        database (unlike delquote, this cannot be undone with undelquote).
        Requires being a channel op.
        """
        self._checkEnabled(irc, channel)
        self._requireOp(irc, msg, channel)
        try:
            self.db.remove(irc.network, channel, id)
            irc.replySuccess()
        except KeyError:
            self.noSuchRecord(irc, channel, id)
    forcedelquote = wrap(forcedelquote, ['channel', 'id'])

    @internationalizeDocstring
    def randquote(self, irc, msg, args, channel):
        """[<channel>]

        Returns a random quote from <channel>'s quotes database. <channel>
        is only necessary if the message isn't sent in the channel itself.
        """
        self._checkEnabled(irc, channel)
        quote = self.db.random(irc.network, channel)
        if quote:
            irc.reply(self.showRecord(quote))
        else:
            irc.error(_('I have no quotes in my database for %s.') %
                      channel)
    randquote = wrap(randquote, ['channel'])

    @internationalizeDocstring
    def lastquote(self, irc, msg, args, channel, index):
        """[<channel>] [<index>]

        Returns the most recently added quote from <channel>'s database, or
        the <index>'th most recent one if <index> is given (1 is the most
        recent). Deleted quotes are skipped. <channel> is only necessary if
        the message isn't sent in the channel itself.
        """
        self._checkEnabled(irc, channel)
        if index < 1:
            irc.error(_('<index> must be at least 1.'), Raise=True)
        records = list(self.db.select(irc.network, channel,
                                      lambda r: not r.deleted, reverse=True))
        if len(records) < index:
            irc.error(_('I have fewer than %s quotes in my database for '
                        '%s.') % (index, channel))
            return
        irc.reply(self.showRecord(records[index - 1]))
    lastquote = wrap(lastquote, ['channel', additional('positiveInt', 1)])

    @internationalizeDocstring
    def findquote(self, irc, msg, args, channel, optlist, glob):
        """[<channel>] [--by <user>] [<glob>]

        Searches <channel>'s quotes database for quotes matching <glob>
        (a case-insensitive '*'-glob against the quote text), optionally
        restricted to quotes added by <user>. Deleted quotes are excluded.
        """
        self._checkEnabled(irc, channel)
        predicates = [lambda r: not r.deleted]
        for (opt, arg) in optlist:
            if opt == 'by':
                predicates.append(lambda r, arg=arg: r.by == str(arg.id))
        if glob:
            def globP(r, glob=glob.lower()):
                return fnmatch.fnmatch(r.text.lower(), glob)
            predicates.append(globP)
        def p(record):
            return all(predicate(record) for predicate in predicates)
        candidates = list(self.db.select(irc.network, channel, p))
        if candidates:
            L = [self.searchSerializeRecord(r) for r in candidates]
            L.sort()
            irc.reply(format(_('%s found: %L'), len(L), L))
        else:
            irc.reply(_('No matching quotes were found.'))
    findquote = wrap(findquote, ['channel',
                                 getopts({'by': 'otherUser'}),
                                 additional(rest('glob'))])

    @internationalizeDocstring
    def votequote(self, irc, msg, args, channel, id, direction):
        """[<channel>] <id> [+|-|0]

        Votes on the quote with id <id> in <channel>'s quotes database. Use
        '+' to like it (the default), '-' to dislike it, or '0' to clear
        your previous vote.
        """
        self._checkEnabled(irc, channel)
        if conf.supybot.plugins.IRCquotes.requireVoteRegistration.getSpecific(
                irc.network, channel)():
            try:
                voterId = str(ircdb.users.getUser(msg.prefix).id)
            except KeyError:
                irc.errorNotRegistered(Raise=True)
        else:
            voterId = msg.prefix

        try:
            record = self.db.get(irc.network, channel, id)
        except KeyError:
            self.noSuchRecord(irc, channel, id)
            return

        if record.deleted:
            irc.reply(_('#%s: This quote has been deleted and cannot be '
                        'voted.') % id)
            return

        voters = set(v for v in record.voters.split(',') if v)
        alreadyVoted = voterId in voters

        if direction == '0':
            if alreadyVoted:
                voters.discard(voterId)
            record.voters = ','.join(voters)
            self.db.set(irc.network, channel, id, record)
            irc.replySuccess(_('Your vote for quote #%s has been cleared.')
                              % id)
            return

        if alreadyVoted:
            irc.error(_('You have already voted on quote #%s.') % id)
            return

        if direction == '-':
            record.dislikes += 1
        else:
            record.likes += 1
        voters.add(voterId)
        record.voters = ','.join(voters)
        self.db.set(irc.network, channel, id, record)
        irc.replySuccess(_('Quote #%s now has %s like(s) and %s '
                           'dislike(s).') % (id, record.likes,
                                             record.dislikes))
    votequote = wrap(votequote, ['channel', 'id',
                                 additional(("literal", ('+', '-', '0')),
                                            '+')])

    @internationalizeDocstring
    def quotestats(self, irc, msg, args, channel):
        """[<channel>]

        Returns the number of quotes in <channel>'s quotes database.
        <channel> is only necessary if the message isn't sent in the channel
        itself.
        """
        self._checkEnabled(irc, channel)
        n = self.db.size(irc.network, channel)
        irc.reply(format(_('There %b %n in my database.'),
                          n, (n, 'quote')))
    quotestats = wrap(quotestats, ['channel'])


Class = IRCquotes


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
