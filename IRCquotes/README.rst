.. _plugin-IRCquotes:

Documentation for the IRCquotes plugin for Supybot
===================================================

Purpose
-------

Per-channel quotes database with voting and an optional periodic "random
quote" announcer, ported from the Eggdrop TCL script "Public Quotes
System" (v2.52).

Storage
-------

Unlike most Limnoria plugins, which key their channel database purely by
channel name, IRCquotes keeps a single SQLite database for every network
at once, at ``<data dir>/IRCquotes/ircquotes.db``, with every quote keyed
by ``(network, channel, id)``. This matters if the bot is on more than
one network: a plain per-channel-name keying scheme would make e.g.
``#software`` on two different networks share the exact same quotes and
id numbering, which is almost certainly not what you want.

Commands
--------

- ``addquote [<channel>] <text>`` -- add a quote. Can be gated by
  minQuoteChars/minQuoteWords (both disabled by default; see
  Configuration).
- ``quoteget [<channel>] <id>`` -- show a quote by id.
- ``quoteinfo [<channel>] <id>`` -- show a quote's author, timestamp and
  vote counts.
- ``delquote [<channel>] <id>`` -- mark a quote as deleted. Only the
  quote's author or a channel op can do this. The quote keeps its id and
  slot in the database (numbering never shifts); its content is hidden
  and shown as ``#<id>: (This quote has been deleted)`` instead.
- ``undelquote [<channel>] <id>`` -- restore a quote removed with
  delquote. Requires being a channel op.
- ``forcedelquote [<channel>] <id>`` -- permanently purge a quote (unlike
  delquote, this cannot be undone). Requires being a channel op.
- ``deletedquoteinfo [<channel>] <id>`` -- show full details (including
  the original text) of a deleted quote: who added it, who deleted it,
  and when. Requires being a channel op.
- ``randquote [<channel>]`` -- show a random quote (deleted quotes are
  skipped).
- ``lastquote [<channel>] [<index>]`` -- show the most recently added
  quote, or the <index>'th most recent (deleted quotes are skipped).
- ``findquote [<channel>] [--by <user>] [<glob>]`` -- search quotes
  (deleted quotes are excluded). Results are capped at
  ``findQuoteMaxResults`` (default 20; 0 for no limit), noting how many
  were found if the list was truncated.
- ``votequote [<channel>] <id> [+|-|0]`` -- like/dislike/clear your vote
  on a quote. Each user may cast one vote per quote, but can switch
  directly between ``+`` and ``-`` without clearing first; ``0`` clears
  it entirely. Voting on a deleted quote replies with ``#<id>: This
  quote has been deleted and cannot be voted.`` instead of erroring.
- ``quotestats [<channel>]`` -- number of (non-deleted) quotes in the
  database. Also appends the ``web.publicUrl`` link, if one is set for
  the channel.
- ``quotepage [<channel>]`` -- shows the URL where <channel>'s quotes can
  be browsed on the web, if ``supybot.plugins.IRCquotes.web.publicUrl``
  is set for it (same idea as the original script's ``html_page_url``).

Permissions
-----------

The original script gates most admin actions (enabling/disabling quotes,
tuning the auto-post interval, undelquote/forcedelquote/deletedquoteinfo)
with per-channel Eggdrop flags. Here:

- Toggling ``enabled``/``autoRandQuoteInterval`` maps onto Limnoria's own
  channel-capability system instead of a bespoke command: ``config
  channel <channel> plugins.IRCquotes.enabled`` (and friends) already
  require channel op capability to change, same as any other channel
  config value.
- ``delquote`` matches the original script's rule: only the quote's
  author, or a channel op, may delete it.
- ``undelquote``, ``forcedelquote`` and ``deletedquoteinfo`` require
  channel op, mirroring the original's ``nm|nm`` (bot owner or channel
  master) flag on those three commands -- note this is *stricter* than
  ``delquote``, which anyone could nominally invoke in the original (the
  author check happened inside the command itself).
- ``addquote`` can optionally be gated too, which the original script
  didn't support directly: set
  ``supybot.plugins.IRCquotes.addCapability`` to a capability name (e.g.
  ``op`` or ``trusted``) to require it. If you'd rather not pick a
  specific capability, just enabling
  ``supybot.plugins.IRCquotes.requireAddRegistration`` has the same
  effect as setting addCapability to ``op``.

Configuration
--------------

- ``supybot.plugins.IRCquotes.enabled`` (channel) -- turn quotes on/off
  for a channel. Disabled by default (opt-in): run
  ``config channel <channel> plugins.IRCquotes.enabled true`` to turn it
  on for a channel.
- ``supybot.plugins.IRCquotes.requireVoteRegistration`` (channel) --
  require registration with the bot to vote.
- ``supybot.plugins.IRCquotes.addCapability`` (channel) -- if set to a
  capability name (e.g. ``op`` or ``trusted``), only users with that
  channel capability (equivalent to ``#channel,<capability>``) may add
  quotes. Empty (the default) allows anyone, unless
  requireAddRegistration is also set.
- ``supybot.plugins.IRCquotes.requireAddRegistration`` (channel) -- when
  addCapability is left empty, enabling this defaults it to ``op``
  (i.e. equivalent to setting addCapability to ``op``). Has no
  additional effect if addCapability is already set to something.
- ``supybot.plugins.IRCquotes.autoRandQuoteInterval`` (channel) -- seconds
  between automatic random-quote announcements (0 disables it).
- ``supybot.plugins.IRCquotes.findQuoteMaxResults`` (channel) -- maximum
  number of matches findquote lists in one reply (same idea as the
  original's max_findquote/max_findquote_total). Defaults to 20; 0 for
  no limit.
- ``supybot.plugins.IRCquotes.minQuoteChars`` (channel) -- if non-zero,
  addquote refuses quotes shorter than this many characters (same idea
  as the original's min_chars_to_quote). Disabled (0) by default.
- ``supybot.plugins.IRCquotes.minQuoteWords`` (channel) -- if non-zero,
  addquote refuses quotes with fewer words than this (same idea as the
  original's min_words_to_quote). Disabled (0) by default.
- ``supybot.plugins.IRCquotes.web.enable`` (global) -- serve the quotes
  database over the bot's built-in HTTP server (``supybot.servers.http``).
- ``supybot.plugins.IRCquotes.web.channel`` (channel) -- allow a specific
  channel's quotes to be browsed on the web.
- ``supybot.plugins.IRCquotes.web.publicUrl`` (channel) -- the
  externally-reachable URL where this channel's quotes can be browsed
  (e.g. behind a reverse proxy), shown by the ``quotepage`` command.
  Empty (the default) means nothing to show.
- ``supybot.plugins.IRCquotes.web.topQuotesEnabled`` (channel) -- show a
  "top quotes" panel of the best-rated quotes above the full list, same
  as the original script's toggleable ``html_show_best_rated_quotes``.
  Enabled by default.
- ``supybot.plugins.IRCquotes.web.topQuotesCount`` (channel) -- how many
  quotes appear in that panel (same idea as the original's
  ``num_best_rated_quotes``). Defaults to 5.

Web interface
-------------

When enabled, quotes are browsable at ``/ircquotes/<network>/<channel>/``
on the bot's HTTP server -- the network is part of the URL (rather than
guessed) since the same channel name can exist, with entirely different
quotes, on more than one network the bot is connected to. The page's
look (dark background, rounded panels, top-quotes panel) draws on the
original script's ``templates/default/{index.html,style.css}``,
redesigned with a cleaner responsive layout and a manual light/dark
toggle button (dark by default; falls back to the visitor's OS/browser
preference until they pick one explicitly, remembered via
``localStorage``).

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

.. _commands-IRCquotes:
