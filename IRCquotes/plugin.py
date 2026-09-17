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

import time
import fnmatch
import html as html_escape

import supybot.conf as conf
import supybot.dbi as dbi
import supybot.ircdb as ircdb
import supybot.ircutils as ircutils
import supybot.utils as utils
import supybot.world as world
import supybot.plugins as plugins
import supybot.schedule as schedule
import supybot.callbacks as callbacks
import supybot.httpserver as httpserver
from supybot.commands import *
from supybot.i18n import PluginInternationalization, internationalizeDocstring
_ = PluginInternationalization('IRCquotes')


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
  <title>%(title)s</title>
  <link rel="stylesheet" href="/ircquotes/style.css" type="text/css" />
</head>
%(body)s
</html>"""

DEFAULT_TEMPLATES = {
    'ircquotes/index.html': PAGE_SKELETON % {
        'title': _('IRC Quotes'),
        'body': """\
<body>
  <div id="content">
    <div id="header">
      <div id="ombreh1"></div>
      <h1>""" + _('IRC Quotes') + """</h1>
    </div>
    <form action="." method="post">
      <label for="chan">""" + _('Channel name:') + """</label>
      <input type="text" placeholder="#channel" name="chan" id="chan" />
      <input type="submit" name="submit" value=\"""" + _('view') + """\" />
    </form>
  </div>
</body>""",
    },
    'ircquotes/channel.html': PAGE_SKELETON % {
        'title': _('Quotes of %(channel)s'),
        'body': """\
<body>
  <div id="content">
    <div id="header">
      <div id="ombreh1"></div>
      <h1>""" + _('Quotes of %(channel)s') + """</h1>
      <div id="informations">
        <div id="infosalon">
          <div id="listeinfos">
            <span class="li">""" + _('Network:') + """ <span
              class="variablef">%(network)s</span></span>
            <span class="li">""" + _('Channel:') + """ <span
              class="variablef">%(channel)s</span></span>
            <span class="li">""" + _('Bot:') + """ <span
              class="variablef">%(botnick)s</span></span>
          </div>
          <div id="infotime">""" + _('%(count)s quote(s) in the '
                                      'database.') + """</div>
        </div>
      </div>
    </div>
    <br />
%(topquotes)s
    <div id="archives">
      <div id="arch">
        <div id="ombrearch">
          <div id="quotes">
%(topquotes_titled)s
            %(rows)s
          </div>
        </div>
      </div>
    </div>
    <div id="footer">
      <div id="lif3">""" + _('IRCquotes, ported from Public Quotes '
                              'System') + """</div>
    </div>
  </div>
</body>""",
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
/* Light theme, used only if the visitor's OS/browser prefers light. */
@media (prefers-color-scheme: light) {
    :root {
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
html, body {
    text-align: center;
    margin: 0;
    padding: 0;
    font: 0.95em/1.5 "Inter", "Segoe UI", helvetica, arial, sans-serif;
    color: var(--text);
    background-color: var(--bg);
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
#content { width: 1000px; margin: 0 auto; }
#header { padding: 0; margin: 0; width: 100%; }
#ombreh1 {
    margin-top: 44px;
    margin-left: 83px;
    margin-right: 77px;
    background-color: var(--panel);
    height: 35px;
    border-radius: 10px;
}
h1 {
    margin-top: -38px;
    margin-left: 80px;
    margin-right: 80px;
    font-size: 1.8em;
    font-weight: 600;
    text-align: center;
    background: linear-gradient(135deg, var(--panel-alt), var(--panel));
    color: var(--accent);
    height: 35px;
    line-height: 35px;
    border-radius: 10px;
    box-shadow: 0 4px 14px var(--shadow);
}
form {
    margin: 20px auto;
    text-align: center;
}
form input[type="text"] {
    padding: 6px 10px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--panel);
    color: var(--text);
}
form input[type="submit"] {
    padding: 6px 14px;
    border-radius: 6px;
    border: none;
    background: var(--accent);
    color: #10131a;
    font-weight: 600;
    cursor: pointer;
}
#informations {
    margin: 10px 5% 10px 5%;
}
#infosalon { text-align: center; min-height: 30px; }
#infotime { margin-top: 5px; text-align: center; color: var(--text-dim); }
.variablef { font-weight: 600; color: var(--text); }
.li { margin-left: 20px; margin-right: 20px; }
#topquotes {
    position: relative;
    color: var(--text);
    padding: 10px 14px;
    margin-bottom: 10px;
    background-color: var(--panel-alt);
    border-radius: 10px;
}
#titles {
    font-size: 1.3em;
    font-weight: 600;
    color: var(--accent-soft);
    margin-bottom: 6px;
}
#archives {
    clear: both;
    padding: 0;
    margin-top: 10px;
    width: 1000px;
    text-align: left;
}
#arch {
    margin-top: 25px;
    margin-left: 83px;
    margin-right: 77px;
    width: 1000px;
}
#ombrearch {
    padding: 0;
    width: 840px;
    background-color: var(--panel);
    border-radius: 10px;
    box-shadow: 0 4px 14px var(--shadow);
}
#quotes {
    position: relative;
    color: var(--text);
    padding: 10px 14px;
    background-color: var(--panel);
    border-radius: 10px;
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
#footer {
    clear: both;
    padding: 0;
    width: 1000px;
    color: var(--text-dim);
    font-size: 0.8em;
}
#lif3 {
    padding-top: 5px;
    padding-bottom: 10px;
    width: 100%;
    text-align: center;
    background-color: var(--panel);
    border-radius: 0 0 10px 10px;
}
""",
}
httpserver.set_default_templates(DEFAULT_TEMPLATES)


class IRCquotesWebCallback(httpserver.SupyHTTPServerCallback):
    name = 'IRCquotes web interface'

    def _renderQuote(self, record, username):
        rating = ''
        if record.likes:
            rating += '<span class="positiverating">+%d</span> ' % \
                record.likes
        if record.dislikes:
            rating += '<span class="negativerating">-%d</span>' % \
                record.dislikes
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

    def doGetOrHead(self, handler, path, write_content):
        parts = [p for p in path.split('/') if p]
        if not parts:
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            if write_content:
                self.write(httpserver.get_template('ircquotes/index.html'))
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
        records = list(self._plugin.db.select(channel, lambda r: True,
                                               reverse=True))
        if records:
            rows = '\n'.join(
                self._renderQuote(r, plugins.getUserName(r.by))
                for r in records)
        else:
            rows = '<p>%s</p>' % _('No quotes yet.')

        # "Top quotes" panel: the best-rated quotes, ported from the
        # original's %TOPQUOTES% block. Only shown once something has
        # actually been rated.
        rated = [r for r in records if r.likes or r.dislikes]
        rated.sort(key=lambda r: (r.likes - r.dislikes), reverse=True)
        top = rated[:3]
        if top:
            top_rows = '\n'.join(
                self._renderQuote(r, plugins.getUserName(r.by))
                for r in top)
            topquotes = """\
    <div id="archives">
      <div id="arch">
        <div id="ombrearch">
          <div id="topquotes">
            <div id="titles">%s</div>
            %s
          </div>
        </div>
      </div>
    </div>
    <br style="clear:both;" />""" % (
                html_escape.escape(_('Top %d quote(s)...') % len(top)),
                top_rows)
            topquotes_titled = '<div id="titles">%s</div>' % \
                html_escape.escape(_('All quotes...'))
        else:
            topquotes = ''
            topquotes_titled = ''

        irc = None
        for candidate in world.ircs:
            if channel in candidate.state.channels:
                irc = candidate
                break
        irc = irc or (world.ircs[0] if world.ircs else None)
        network = irc.network if irc else _('unknown')
        botnick = irc.nick if irc else _('unknown')

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


class IRCquotes(plugins.ChannelIdDatabasePlugin):
    """Per-channel quotes database with voting and an optional periodic
    "random quote" announcer. Ported from the Eggdrop TCL script
    'public_quotes_system'.

    Configuration variables in ``supybot.plugins.IRCquotes`` and
    ``supybot.databases.plugins`` affect this plugin."""

    class DB(plugins.ChannelIdDatabasePlugin.DB):
        class DB(plugins.ChannelIdDatabasePlugin.DB.DB):
            class Record(plugins.ChannelIdDatabasePlugin.DB.DB.Record):
                __fields__ = [
                    'at',
                    'by',
                    'text',
                    ('likes', (int, 0)),
                    ('dislikes', (int, 0)),
                    ('voters', (utils.safeEval, '')),
                ]

            def add(self, at, by, text, **kwargs):
                kwargs.setdefault('likes', 0)
                kwargs.setdefault('dislikes', 0)
                kwargs.setdefault('voters', '')
                record = self.Record(at=at, by=by, text=text, **kwargs)
                # Call dbi.DB.add() directly (not via super(self.__class__,
                # self), which the base ChannelIdDatabasePlugin.DB.DB.add()
                # uses -- that pattern resolves relative to the *actual*
                # runtime class, so when we subclass it further it skips
                # straight past the base's own add() and lands here with
                # the wrong signature).
                return dbi.DB.add(self, record)

    def __init__(self, irc):
        self.__parent = super(IRCquotes, self)
        self.__parent.__init__(irc)
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
        if schedule.schedule.count(name):
            schedule.removeEvent(name)
        if not interval:
            return

        def sendRandomQuote():
            quote = self.db.random(channel)
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
        if not schedule.schedule.count(name):
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

    @internationalizeDocstring
    def addquote(self, irc, msg, args, channel, text):
        """[<channel>] <text>

        Adds <text> as a new quote to the quotes database for <channel>.
        <channel> is only necessary if the message isn't sent in the channel
        itself.
        """
        self._checkEnabled(irc, channel)
        user = self.getUserId(irc, msg.prefix, channel) or msg.prefix
        at = time.time()
        self.addValidator(irc, text)
        if text is not None:
            id = self.db.add(channel, at, user, text)
            irc.replySuccess(_('Quote #%s added.') % id)
    addquote = wrap(addquote, ['channeldb', 'text'])

    @internationalizeDocstring
    def quoteget(self, irc, msg, args, channel, id):
        """[<channel>] <id>

        Returns the quote with id <id> from <channel>'s quotes database.
        <channel> is only necessary if the message isn't sent in the channel
        itself.
        """
        self._checkEnabled(irc, channel)
        try:
            record = self.db.get(channel, id)
            irc.reply(self.showRecord(record))
        except KeyError:
            self.noSuchRecord(irc, channel, id)
    quoteget = wrap(quoteget, ['channeldb', 'id'])

    @internationalizeDocstring
    def quoteinfo(self, irc, msg, args, channel, id):
        """[<channel>] <id>

        Returns metadata (author, timestamp, votes) about the quote with id
        <id> in <channel>'s quotes database.
        """
        self._checkEnabled(irc, channel)
        try:
            record = self.db.get(channel, id)
        except KeyError:
            self.noSuchRecord(irc, channel, id)
            return
        username = plugins.getUserName(record.by)
        irc.reply(_('Quote #%s added by %s on %s; %s like(s), '
                    '%s dislike(s).') %
                  (record.id, username, utils.str.timestamp(record.at),
                   record.likes, record.dislikes))
    quoteinfo = wrap(quoteinfo, ['channeldb', 'id'])

    @internationalizeDocstring
    def delquote(self, irc, msg, args, channel, id):
        """[<channel>] <id>

        Removes the quote with id <id> from <channel>'s quotes database.
        You must be the original author of the quote, or a channel op, to
        remove it (same as the original script's author-or-admin rule).
        <channel> is only necessary if the message isn't sent in the channel
        itself.
        """
        self._checkEnabled(irc, channel)
        user = self.getUserId(irc, msg.prefix, channel) or msg.prefix
        try:
            record = self.db.get(channel, id)
            self.checkChangeAllowed(irc, msg, channel, user, record)
            self.db.remove(channel, id)
            irc.replySuccess()
        except KeyError:
            self.noSuchRecord(irc, channel, id)
    delquote = wrap(delquote, ['channeldb', 'id'])

    @internationalizeDocstring
    def randquote(self, irc, msg, args, channel):
        """[<channel>]

        Returns a random quote from <channel>'s quotes database. <channel>
        is only necessary if the message isn't sent in the channel itself.
        """
        self._checkEnabled(irc, channel)
        quote = self.db.random(channel)
        if quote:
            irc.reply(self.showRecord(quote))
        else:
            irc.error(_('I have no quotes in my database for %s.') %
                      channel)
    randquote = wrap(randquote, ['channeldb'])

    @internationalizeDocstring
    def lastquote(self, irc, msg, args, channel, index):
        """[<channel>] [<index>]

        Returns the most recently added quote from <channel>'s database, or
        the <index>'th most recent one if <index> is given (1 is the most
        recent). <channel> is only necessary if the message isn't sent in the
        channel itself.
        """
        self._checkEnabled(irc, channel)
        if index < 1:
            irc.error(_('<index> must be at least 1.'), Raise=True)
        records = list(self.db.select(channel, lambda r: True, reverse=True))
        if len(records) < index:
            irc.error(_('I have fewer than %s quotes in my database for '
                        '%s.') % (index, channel))
            return
        irc.reply(self.showRecord(records[index - 1]))
    lastquote = wrap(lastquote, ['channeldb', additional('positiveInt', 1)])

    @internationalizeDocstring
    def findquote(self, irc, msg, args, channel, optlist, glob):
        """[<channel>] [--by <user>] [<glob>]

        Searches <channel>'s quotes database for quotes matching <glob>
        (a case-insensitive '*'-glob against the quote text), optionally
        restricted to quotes added by <user>.
        """
        self._checkEnabled(irc, channel)
        predicates = []
        for (opt, arg) in optlist:
            if opt == 'by':
                predicates.append(lambda r, arg=arg: r.by == arg.id)
        if glob:
            def globP(r, glob=glob.lower()):
                return fnmatch.fnmatch(r.text.lower(), glob)
            predicates.append(globP)
        def p(record):
            return all(predicate(record) for predicate in predicates)
        candidates = list(self.db.select(channel, p))
        if candidates:
            L = [self.searchSerializeRecord(r) for r in candidates]
            L.sort()
            irc.reply(format(_('%s found: %L'), len(L), L))
        else:
            irc.reply(_('No matching quotes were found.'))
    findquote = wrap(findquote, ['channeldb',
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
            record = self.db.get(channel, id)
        except KeyError:
            self.noSuchRecord(irc, channel, id)
            return

        voters = set(v for v in record.voters.split(',') if v)
        alreadyVoted = voterId in voters

        if direction == '0':
            if alreadyVoted:
                voters.discard(voterId)
            record.voters = ','.join(voters)
            self.db.set(channel, id, record)
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
        self.db.set(channel, id, record)
        irc.replySuccess(_('Quote #%s now has %s like(s) and %s '
                           'dislike(s).') % (id, record.likes,
                                             record.dislikes))
    votequote = wrap(votequote, ['channeldb', 'id',
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
        n = self.db.size(channel)
        irc.reply(format(_('There %b %n in my database.'),
                          n, (n, 'quote')))
    quotestats = wrap(quotestats, ['channeldb'])


Class = IRCquotes


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
