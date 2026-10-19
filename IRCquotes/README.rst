.. _plugin-IRCquotes:

Documentation for the IRCquotes plugin for Supybot
===================================================

Purpose
-------

Per-channel quotes database with voting and an optional periodic
"random quote" announcer, ported from the Eggdrop TCL script "Public
Quotes System" (v2.52, by MenzAgitat). It aims to behave like the original
wherever Limnoria allows it; the differences that remain are listed at
the end.

Storage
-------

Unlike most Limnoria plugins, which key their channel database purely by
channel name, IRCquotes keeps a single SQLite database for every network
at once, at ``<data dir>/IRCquotes/ircquotes.db``, with every quote keyed
by ``(network, channel, id)``. This matters if the bot is on more than
one network: a plain per-channel-name keying scheme would make e.g.
``#software`` on two different networks share the exact same quotes and
id numbering, which is almost certainly not what you want.

The database is backed up every day at ``backupTime`` (00:00 by default)
to ``ircquotes.db.bak`` next to it, only if it changed since the last
backup. If the database is missing when the plugin loads, the backup is
restored automatically.

Commands
--------

Wherever a command takes ``[<channel>]``, you can give the channel before
the arguments (the Limnoria way) or after the quote number (the original
script's way): ``quoteget #chan 5`` and ``quoteget 5 #chan`` are the
same.

- ``addquote [<channel>] [--keep-timestamps] [--keep-attributes]
  <text>`` -- add a quote. The text is stored exactly as typed, so
  pasting a log line like ``[12:34] <@bob> he said "hi"`` works as is
  (Limnoria would otherwise read the brackets as a nested command and drop
  the quotation marks). Timestamps such as ``[12:34]`` and the status
  symbols in front of nicks (``<@bob>`` becomes ``<bob>``) are removed
  (``filterTimestamps``, ``filterAttributes``) unless you pass
  ``--keep-timestamps``/``--keep-attributes`` (the original's
  ``-keep_timestamps``/``-keep_attributes`` work too).

  **Multi-line quotes**: with ``multilineAdd`` on (the default), paste
  several lines at once, the first one starting with ``addquote``. Every
  line you send next in the channel becomes part of the same quote,
  joined with ``lineSeparator``. The quote is saved once you stop for
  ``multilineTimeout`` seconds, or when you send a line that is just
  ``.`` (``multilineEndSignal``). You get a notice when this starts.
  Commands you send meanwhile aren't caught, and pastes longer than
  ``multilineMaxLines`` are refused. Because of this, the "added" reply
  comes a second after a one-line ``addquote``.

  Adding can be gated by ``minQuoteChars``/``minQuoteWords``,
  ``addCapability`` and ``requireAddRegistration`` (see Configuration).
- ``quoteget [<channel>] <id>`` -- show a quote. A multi-line quote is
  shown over several lines (up to ``maxQuoteLines``, otherwise on one
  line with colored separators). If it was deleted, the reply says by
  whom and when.
- ``quoteinfo [<channel>] <id>`` -- who added a quote and when, and its
  rating (score = likes - dislikes), e.g. "The quote #5 has been added by
  bob on 19/10/2026 at 21:30:00. Its popularity rating is 2 (3 like, 1
  dislike)." For a deleted quote, who deleted it and when.
- ``randquote [<channel>]`` -- a random quote. No quote comes up twice
  until every quote has been shown.
- ``lastquote [<channel>] [-<index>]`` -- the latest quote. ``-1`` shows
  the one before it, ``-2`` the one before that, and so on (a plain
  ``<n>`` shows the n-th latest, 1 being the latest). Deleted quotes are
  skipped; if the latest quote was deleted, you're told so first.
- ``findquote [<channel>] [--all] [--by <user>] <search terms>`` -- the
  quotes containing every one of the search terms, in any order. Case,
  accents and IRC formatting don't matter; ``*`` and ``?`` are plain
  characters. Put ``"quotation marks"`` around words to search for that
  exact phrase. The terms must have at least ``findQuoteMinChars`` (3)
  characters. ``--all`` (or ``-all``) searches every channel whose quotes
  are enabled or in ``readableChannels``; ``--by`` only finds quotes added
  by that bot user.

  The reply lists the numbers of all the matches ("4 results have been
  found: 3|8|12|20"), then shows the ``findQuoteRecent`` (2) most recent
  ones in full, prefixed with their channel for ``--all``. If more than
  ``findQuoteMaxResults`` (100) quotes match, you're asked to be more
  precise instead.
- ``votequote [<channel>] <id> [+|-|0]`` -- without ``+``, ``-`` or
  ``0``, shows the quote's rating and how you voted for it. ``+`` likes
  it, ``-`` dislikes it, ``0`` cancels your vote; a vote can also be
  switched straight from ``+`` to ``-``. Unregistered voters are told
  apart by ``*!ident@*.domain`` (like the original), so changing nick
  doesn't buy a second vote; registered users are told apart by bot
  account. See ``votesEnabled``, ``canChangeVote``,
  ``canVoteExternalQuotes``, ``requireVoteRegistration`` and
  ``requireVoteAccount``.
- ``delquote [<channel>] <id>`` -- delete a quote you added yourself
  (matched by bot account, or by nick for unregistered users, as the
  original did). Ops use ``forcedelquote``. The quote keeps its number,
  so numbering never shifts, and can be restored with ``undelquote``.
- ``forcedelquote [<channel>] <id>`` -- delete anybody's quote. It's the
  same soft delete as ``delquote``, credited in public to "an
  administrator". Requires channel op.
- ``cancelquote [<channel>] <id>`` -- remove the *latest* quote for good,
  leaving no trace; its number goes to the next quote. ``<id>`` must be
  the latest quote's number, so nothing else gets removed by mistake.
  Requires channel op.
- ``undelquote [<channel>] <id>`` -- restore a deleted quote. Requires
  channel op.
- ``deletedquoteinfo [<channel>] <id>`` -- sent to you in private: who
  deleted a quote (with their ``nick!user@host``) and when, who added it
  and when, and the deleted text. Requires channel op.
- ``quotestats [<channel>]`` -- number of (non-deleted) quotes in the
  database, plus the ``web.publicUrl`` link if one is set for the
  channel.
- ``quotepage [<channel>]`` -- replies with ``<channel> Quotes: <url>``,
  the URL built from ``web.publicUrl`` plus the network and channel, if
  that base is set (same idea as the original script's
  ``html_page_url``).

Quotes are announced the way the original showed them: ``[5] the
quote``, without your nick in front. The style is ``quoteIdStyle``, and
``quotesColor`` sets one color for every quote. All colors and formatting
are removed in a channel that is ``+c`` (or where ``monochrome`` is on).

Flood control
-------------

As in the original, the quotes commands are rate-limited per channel,
both one by one and all together (``antiflood``, on by default). The
limits are under ``flood.*`` as ``"x:y"``, at most x uses every y
seconds:

+--------------+------------+--------------+------------+
| command      | default    | command      | default    |
+==============+============+==============+============+
| addquote     | 3:80       | lastquote    | 5:80       |
+--------------+------------+--------------+------------+
| quote (get)  | 5:80       | findquote    | 3:80       |
+--------------+------------+--------------+------------+
| quoteinfo    | 5:80       | votequote    | 5:80       |
+--------------+------------+--------------+------------+
| delquote     | 2:60       | global (all) | 10:120     |
+--------------+------------+--------------+------------+
| randquote    | 5:80       |              |            |
+--------------+------------+--------------+------------+

Commands over the limit are ignored. The channel is warned at most once
every ``antifloodMessageInterval`` seconds, and the warning for
quoteget/lastquote/findquote/randquote includes the web page link, if
there is one.

Permissions
-----------

The original script gates most admin actions (enabling/disabling quotes,
tuning the auto-post interval, undelquote/forcedelquote/cancelquote/
deletedquoteinfo) with per-channel Eggdrop flags. Here:

- Toggling ``enabled``/``autoRandQuoteInterval`` and every other setting
  maps onto Limnoria's own config system instead of the original's
  ``!quotes on/off``, ``!autorandquote`` and ``!quoteset`` commands:
  ``config channel <channel> plugins.IRCquotes.enabled true`` (and
  friends) already require channel op capability to change, same as any
  other channel config value.
- ``undelquote``, ``forcedelquote``, ``cancelquote`` and
  ``deletedquoteinfo`` require the ``#channel,op`` capability, mirroring
  the original's ``nm|nm`` (bot owner or channel master) flag.
- ``addquote`` can optionally be gated too, which the original script
  didn't support directly: set ``addCapability`` to a capability name
  (e.g. ``op`` or ``trusted``) to require it. If you'd rather not pick a
  specific capability, just enabling ``requireAddRegistration`` has the
  same effect as setting addCapability to ``op``.

Configuration
--------------

All of these are under ``supybot.plugins.IRCquotes``. "(channel)" ones can
be set per channel; "(global)" ones only for the whole bot.

Channel and access:

- ``enabled`` (channel) -- turn quotes on/off for a channel. Disabled by
  default (opt-in).
- ``readableChannels`` (global) -- channels whose quotes can be read
  (quoteget, quoteinfo, randquote, lastquote, findquote, votequote) even
  though quotes aren't enabled there (the original's ``include_chans``).
- ``addCapability`` (channel), ``requireAddRegistration`` (channel) --
  see Permissions.
- ``minQuoteChars`` (channel, 10), ``minQuoteWords`` (channel, 3) --
  addquote refuses quotes with fewer characters or words, as the original
  did. 0 disables either check.

Adding:

- ``filterTimestamps``, ``filterAttributes`` (channel) -- remove
  timestamps / status symbols in front of nicks from new quotes. On by
  default.
- ``multilineAdd`` (channel) -- catch multi-line pastes. On by default.
- ``multilineMaxLines`` (channel, 15), ``multilineTimeout`` (global, 4
  seconds), ``multilineEndSignal`` (channel, ``.``).

Display:

- ``lineSeparator`` (channel, ``" | "``) -- what separates the lines of a
  multi-line quote, on IRC and on the web page. Empty disables multi-line
  display.
- ``maxQuoteLines`` (channel, 15) -- longer quotes are shown on one line.
- ``multilinePrefix``, ``multilineLastPrefix`` (channel) -- what goes in
  front of the extra lines, and of the last one.
- ``multilineOnAdminCommands`` (channel, off) -- whether deletedquoteinfo
  and cancelquote show multi-line quotes over several lines.
- ``quoteIdStyle`` (channel) -- how the number is shown; ``%id%`` is
  replaced by it.
- ``channelStyle`` (channel) -- how the channel is shown in front of
  ``findquote --all`` results; ``%chan%`` is replaced by it.
- ``quotesColor`` (channel) -- an mIRC color (``07`` or ``07,01``) for
  every quote, dropping the quotes' own colors. Empty by default.
- ``alternateColor`` (channel, ``14``) -- color of the line separators of
  a quote shown on one line, and of the findquote result separators.
- ``monochrome`` (channel) -- remove all formatting from what the plugin
  says (automatic in a ``+c`` channel).

Searching:

- ``findQuoteMinChars`` (global, 3), ``findQuoteMaxResults`` (channel,
  100; 0 for no limit), ``findQuoteRecent`` (channel, 2),
  ``splitFindQuotesUpTo`` (channel, 1) -- up to how many results
  multi-line quotes are still shown over several lines.

Votes:

- ``votesEnabled`` (channel) -- quotes can be rated. On by default.
- ``canChangeVote`` (channel) -- votes can be switched or cancelled. On
  by default.
- ``canVoteExternalQuotes`` (channel) -- users can vote for another
  channel's quotes than the one they're in. On by default.
- ``requireVoteRegistration`` (channel) -- voting requires being
  registered with the bot.
- ``requireVoteAccount`` (channel) -- voting requires being logged in to
  services, the original's ``votequote_nickserv_restriction``. The bot
  learns accounts from the IRCv3 account-notify, extended-join and
  account-tag capabilities instead of asking NickServ.

Random quotes:

- ``autoRandQuoteInterval`` (channel) -- seconds between automatic
  random-quote announcements (0, the default, disables it).
- ``autoRandQuoteConsidersRatings`` (channel) -- the automatic random
  quote only picks quotes rated 0 or more. On by default.

Flood control and backups:

- ``antiflood`` (channel), ``flood.*`` (channel),
  ``antifloodMessageInterval`` (global, 20) -- see Flood control.
- ``backupTime`` (global, ``00:00``) -- time of the daily backup; empty
  disables it.

Web:

- ``web.enable`` (global) -- serve the quotes database over the bot's
  built-in HTTP server (``supybot.servers.http``).
- ``web.channel`` (channel) -- allow a channel's quotes to be browsed on
  the web.
- ``web.publicUrl`` (channel) -- the externally-reachable *base* URL
  IRCquotes is served from (e.g. behind a reverse proxy), such as
  ``https://quotes.example.com/ircquotes/``. The network and channel are
  appended automatically to build the page URL shown by ``quotepage``,
  ``quotestats`` and the flood warnings. Empty (the default) means nothing
  to show.
- ``web.quotesPerPage`` (channel, 50; 0 for one page).
- ``web.newestFirst`` (channel) -- newest quotes first (the default) or
  oldest first.
- ``web.showAuthor`` (channel) -- show who added each quote. Off by
  default, like the original.
- ``web.keepStyles`` (channel) -- keep the quotes' mIRC colors, bold,
  italics and underline on the page. On by default.
- ``web.topQuotesEnabled`` (channel, on), ``web.topQuotesCount``
  (channel, 5) -- a "top quotes" panel of the best-rated quotes on the
  first page, shown once something has been rated.
- ``web.footer1``, ``web.footer2`` (global) -- footer lines. They're raw
  HTML, which is why only the bot owner can set them.

Web interface
-------------

When enabled, quotes are browsable at ``/ircquotes/<network>/<channel>/``
on the bot's HTTP server -- the network is part of the URL (rather than
guessed) since the same channel name can exist, with entirely different
quotes, on more than one network the bot is connected to. Each quote shows
its number, date, rating (score, likes and dislikes, when votes are
enabled), its author if ``web.showAuthor`` is on, and its text with its
mIRC styles and one line per ``lineSeparator``. The page's look draws on
the original script's ``templates/default/{index.html,style.css}``,
redesigned with a cleaner responsive layout and a manual light/dark toggle
button (dark by default; falls back to the visitor's OS/browser preference
until they pick one explicitly, remembered via ``localStorage``).

Landing on ``/ircquotes/`` itself shows a card per connected network,
each listing the channels there whose ``web.channel`` is enabled, linking
straight to their quotes page. There's also a "jump to a channel by
name" field for convenience: type just a channel name and it either
redirects straight there (if only one network has it web-enabled) or
shows network cards filtered down to that channel name so you can pick
which one you meant.

Since Limnoria's built-in HTTP server has no TLS support of its own and
normally isn't meant to be exposed directly, example Apache reverse-proxy
vhosts (plaintext and TLS) are provided under ``webservers/``.

Differences from the original
-----------------------------

- Settings are changed with Limnoria's ``config`` instead of
  ``!quoteset``, ``!quotes on/off`` and ``!autorandquote``, and
  permissions are Limnoria capabilities instead of Eggdrop flags.
- The web page is served live by the bot instead of being exported to
  static files, so there is no ``!exportquotes``, and the page navigation
  is numeric links only (no drop-down).
- ``requireVoteAccount`` relies on the IRCv3 account capabilities rather
  than asking NickServ for ``STATUS``.
- Replies other than the quotes themselves are Limnoria replies (nick
  prefix, ``Error:``), with no ``main_color``/``warning_prefix``.
- Unlike the original, the date format is always ``dd/mm/yyyy`` and
  ``hh:mm:ss``, and the multi-line quotes don't go through a separate
  low-priority queue.

.. _commands-IRCquotes:
