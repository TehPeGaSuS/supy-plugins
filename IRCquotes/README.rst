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
- ``delquote [<channel>] <id>`` -- remove a quote. Only the quote's author
  or a channel op can do this (same author-or-admin rule as the original
  script).
- ``randquote [<channel>]`` -- show a random quote.
- ``lastquote [<channel>] [<index>]`` -- show the most recently added
  quote, or the <index>'th most recent.
- ``findquote [<channel>] [--by <user>] [<glob>]`` -- search quotes.
- ``votequote [<channel>] <id> [+|-|0]`` -- like/dislike/clear your vote
  on a quote. Each user may cast one vote per quote.
- ``quotestats [<channel>]`` -- number of quotes in the database.

Permissions
-----------

The original script gates most admin actions (enabling/disabling quotes,
tuning the auto-post interval) with per-channel Eggdrop flags. Here, that
maps onto Limnoria's own channel-capability system instead of a bespoke
toggle command: ``config channel <channel> plugins.IRCquotes.enabled``
and ``...autoRandQuoteInterval`` already require channel op capability to
change, same as any other channel config value. ``delquote`` keeps the
original's author-or-admin rule directly.

Configuration
--------------

- ``supybot.plugins.IRCquotes.enabled`` (channel) -- turn quotes on/off
  for a channel.
- ``supybot.plugins.IRCquotes.requireVoteRegistration`` (channel) --
  require registration with the bot to vote.
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
