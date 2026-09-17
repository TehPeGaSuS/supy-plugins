.. _plugin-IRCquotes:

Documentation for the IRCquotes plugin for Supybot
===================================================

Purpose
-------

Per-channel quotes database with voting and an optional periodic "random
quote" announcer, ported from the Eggdrop TCL script "Public Quotes
System" (v2.52).

Commands
--------

- ``addquote [<channel>] <text>`` -- add a quote.
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
  (deleted quotes are excluded).
- ``votequote [<channel>] <id> [+|-|0]`` -- like/dislike/clear your vote
  on a quote. Each user may cast one vote per quote. Voting on a deleted
  quote replies with ``#<id>: This quote has been deleted and cannot be
  voted.`` instead of erroring.
- ``quotestats [<channel>]`` -- number of (non-deleted) quotes in the
  database.

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
  for a channel.
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
- ``supybot.plugins.IRCquotes.web.enable`` (global) -- serve the quotes
  database over the bot's built-in HTTP server (``supybot.servers.http``).
- ``supybot.plugins.IRCquotes.web.channel`` (channel) -- allow a specific
  channel's quotes to be browsed on the web.

Web interface
-------------

When enabled, quotes are browsable at ``/ircquotes/<channel>/`` on the
bot's HTTP server. The page's look (dark background, "shadowed" header
bar, rounded panels, top-quotes panel) is ported from the original
script's ``templates/default/{index.html,style.css}``, refreshed with a
more modern palette and automatic light/dark mode (dark by default,
switching to light if the visitor's browser prefers it).

Since Limnoria's built-in HTTP server has no TLS support of its own and
normally isn't meant to be exposed directly, example Apache reverse-proxy
vhosts (plaintext and TLS) are provided under ``webservers/``.

.. _commands-IRCquotes:
