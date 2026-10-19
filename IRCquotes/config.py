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

import re

import supybot.conf as conf
import supybot.registry as registry
from supybot.i18n import PluginInternationalization, internationalizeDocstring
_ = PluginInternationalization('IRCquotes')

def configure(advanced):
    # This will be called by supybot to configure this module.  advanced is
    # a bool that specifies whether the user identified themself as an
    # advanced user or not.  You should effect your configuration by
    # manipulating the registry as appropriate.
    from supybot.questions import expect, anything, something, yn
    conf.registerPlugin('IRCquotes', True)


class FloodLimit(registry.String):
    """Must be "x:y": at most x commands every y seconds (both above 0)."""
    def setValue(self, v):
        m = re.match(r'^\s*(\d+):(\d+)\s*$', v)
        if not m or not int(m.group(1)) or not int(m.group(2)):
            self.error()
        super().setValue(v.strip())


class BackupTime(registry.String):
    """Must be a time of day as "HH:MM", or empty to disable the backup."""
    def setValue(self, v):
        v = v.strip()
        if v:
            m = re.match(r'^(\d{1,2}):(\d{2})$', v)
            if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
                self.error()
        super().setValue(v)


IRCquotes = conf.registerPlugin('IRCquotes')

conf.registerChannelValue(IRCquotes, 'enabled',
    registry.Boolean(False, _("""Determines whether the quotes commands
    (addquote, quoteget, delquote, etc.) are enabled in this channel.
    Disabled by default: it's an opt-in feature, so enable it per
    channel with "config channel <channel> plugins.IRCquotes.enabled
    true".""")))

conf.registerGlobalValue(IRCquotes, 'readableChannels',
    registry.SpaceSeparatedListOfStrings([], _("""Channels whose quotes can
    be read (quoteget, quoteinfo, randquote, lastquote, findquote,
    votequote) even though quotes aren't enabled there, same as the
    original script's include_chans.""")))

conf.registerChannelValue(IRCquotes, 'requireVoteRegistration',
    registry.Boolean(False, _("""Determines whether users must be registered
    with the bot in order to vote on quotes with votequote (the original
    script's must_have_a_handle_to_vote). Looking at a quote's rating never
    needs it.""")))

conf.registerChannelValue(IRCquotes, 'requireVoteAccount',
    registry.Boolean(False, _("""Determines whether users must be logged in
    to a services account in order to vote on quotes, the original script's
    votequote_nickserv_restriction. The bot learns accounts from the IRCv3
    account-notify, extended-join and account-tag capabilities instead of
    asking NickServ.""")))

conf.registerChannelValue(IRCquotes, 'votesEnabled',
    registry.Boolean(True, _("""Determines whether quotes can be rated with
    votequote. When off, ratings are also left out of quoteinfo and the web
    page.""")))

conf.registerChannelValue(IRCquotes, 'canChangeVote',
    registry.Boolean(True, _("""Determines whether users can change or
    cancel ("0") a vote they already cast.""")))

conf.registerChannelValue(IRCquotes, 'canVoteExternalQuotes',
    registry.Boolean(True, _("""Determines whether users can vote for the
    quotes of another channel than the one they're talking in.""")))

conf.registerChannelValue(IRCquotes, 'requireAddRegistration',
    registry.Boolean(False, _("""Determines whether adding quotes with
    addquote requires some form of registered-user gating. If
    addCapability is left empty, enabling this defaults it to requiring
    the "op" capability; if addCapability is already set to something
    specific, this setting has no additional effect (any capability
    check already implies the user must be registered).""")))

conf.registerChannelValue(IRCquotes, 'addCapability',
    registry.String('', _("""If set to a capability name (e.g. "op" or
    "trusted"), only users with that channel capability (equivalent to
    "#channel,<capability>") may add quotes with addquote. Leave empty to
    let anyone add quotes -- unless requireAddRegistration is also
    enabled, in which case empty defaults to "op".""")))

conf.registerChannelValue(IRCquotes, 'minQuoteChars',
    registry.NonNegativeInteger(10, _("""If non-zero, addquote will refuse
    quotes shorter than this many characters (the original script's
    min_chars_to_quote). 0 disables the check.""")))

conf.registerChannelValue(IRCquotes, 'minQuoteWords',
    registry.NonNegativeInteger(3, _("""If non-zero, addquote will refuse
    quotes with fewer words than this (the original script's
    min_words_to_quote). 0 disables the check.""")))

conf.registerChannelValue(IRCquotes, 'filterTimestamps',
    registry.Boolean(True, _("""Determines whether timestamps such as
    [12:34] or <12:34:56> are removed from quotes as they're added. Pass
    --keep-timestamps to addquote to keep them in a given quote.""")))

conf.registerChannelValue(IRCquotes, 'filterAttributes',
    registry.Boolean(True, _("""Determines whether channel status symbols
    (~ & @ % +) in front of nicks, as in <@nick>, are removed from quotes
    as they're added. Pass --keep-attributes to addquote to keep them in a
    given quote.""")))

conf.registerChannelValue(IRCquotes, 'multilineAdd',
    registry.Boolean(True, _("""Determines whether addquote catches a
    multi-line paste: the lines you send right after the addquote line
    (until you stop for multilineTimeout seconds, or send a line that is
    just multilineEndSignal) become part of the same quote, joined with
    lineSeparator.""")))

conf.registerChannelValue(IRCquotes, 'multilineMaxLines',
    registry.PositiveInteger(15, _("""Determines how many lines a
    multi-line quote added on the fly may have. Longer pastes are refused
    and nothing is stored.""")))

conf.registerGlobalValue(IRCquotes, 'multilineTimeout',
    registry.PositiveFloat(4.0, _("""Determines how many seconds after the
    last line of a multi-line paste the quote is considered complete.
    Don't set it too low, or the server's fake lag will cut quotes
    short.""")))

conf.registerChannelValue(IRCquotes, 'multilineEndSignal',
    registry.String('.', _("""A line that is just this ends a multi-line
    quote right away, instead of waiting for multilineTimeout.""")))

conf.registerChannelValue(IRCquotes, 'lineSeparator',
    registry.String(' | ', _("""The text that separates the lines of a
    multi-line quote. Quotes containing it are shown over several lines on
    IRC (up to maxQuoteLines) and on the web page. Empty disables
    multi-line display.""")))

conf.registerChannelValue(IRCquotes, 'maxQuoteLines',
    registry.PositiveInteger(15, _("""Determines how many lines a
    multi-line quote may span on IRC; longer ones are shown on a single
    line, so they don't flood the channel.""")))

conf.registerChannelValue(IRCquotes, 'multilineOnAdminCommands',
    registry.Boolean(False, _("""Determines whether deletedquoteinfo and
    cancelquote show a multi-line quote over several lines (they use a
    single line by default).""")))

conf.registerChannelValue(IRCquotes, 'multilinePrefix',
    registry.String('\x0314|\x0f  ', _("""The prefix put in front of every
    extra line of a multi-line quote except the last one.""")))

conf.registerChannelValue(IRCquotes, 'multilineLastPrefix',
    registry.String('\x0314·\x0f  ', _("""The prefix put in front of
    the last line of a multi-line quote.""")))

conf.registerChannelValue(IRCquotes, 'quoteIdStyle',
    registry.String('\x1f[\x02%id%\x02]\x0f ', _("""How a quote's number is
    shown in front of it. %id% is replaced by the number.""")))

conf.registerChannelValue(IRCquotes, 'channelStyle',
    registry.String('\x0314%chan%\x0f ', _("""How the channel is shown in
    front of the quotes of a findquote --all search. %chan% is replaced by
    the channel name.""")))

conf.registerChannelValue(IRCquotes, 'quotesColor',
    registry.String('', _("""If set to an mIRC color ("07", or "07,01"
    with a background), quotes are shown in that color and the colors they
    contain are dropped. Empty keeps the quotes' own colors.""")))

conf.registerChannelValue(IRCquotes, 'alternateColor',
    registry.String('14', _("""The mIRC color used for the line separators
    of a quote shown on a single line and for the separators of the
    findquote result list. Empty for none.""")))

conf.registerChannelValue(IRCquotes, 'monochrome',
    registry.Boolean(False, _("""Determines whether all colors, bold and
    underline are removed from what the plugin says in this channel. This
    already happens on its own in a channel that is +c.""")))

conf.registerChannelValue(IRCquotes, 'autoRandQuoteInterval',
    registry.NonNegativeInteger(0, _("""Determines how often, in seconds, the
    bot automatically announces a random quote in this channel. Set to 0
    to disable automatic announcing (the default).""")))

conf.registerChannelValue(IRCquotes, 'autoRandQuoteConsidersRatings',
    registry.Boolean(True, _("""Determines whether the automatic random
    quote only picks quotes whose rating is 0 or more.""")))

conf.registerGlobalValue(IRCquotes, 'findQuoteMinChars',
    registry.NonNegativeInteger(3, _("""Determines how many characters a
    findquote search must have at least.""")))

conf.registerChannelValue(IRCquotes, 'findQuoteMaxResults',
    registry.NonNegativeInteger(100, _("""Determines how many quotes a
    findquote search may match; above this, the user is asked to be more
    precise instead (the original script's max_findquote_total). 0 for no
    limit.""")))

conf.registerChannelValue(IRCquotes, 'findQuoteRecent',
    registry.NonNegativeInteger(2, _("""Determines how many of the most
    recent matching quotes findquote shows in full, after the list of
    matching numbers (the original script's max_findquote).""")))

conf.registerChannelValue(IRCquotes, 'splitFindQuotesUpTo',
    registry.NonNegativeInteger(1, _("""Determines up to how many findquote
    results multi-line quotes are still shown over several lines; with
    more results they're shown on one line each.""")))

conf.registerChannelValue(IRCquotes, 'antiflood',
    registry.Boolean(True, _("""Determines whether the quotes commands are
    rate-limited in this channel, per command and overall (see the flood
    settings). Commands over the limit are ignored, with a warning now and
    then.""")))

conf.registerGroup(IRCquotes, 'flood')
for _command, _default in (('addquote', '3:80'), ('quote', '5:80'),
                           ('quoteinfo', '5:80'), ('delquote', '2:60'),
                           ('randquote', '5:80'), ('lastquote', '5:80'),
                           ('findquote', '3:80'), ('votequote', '5:80'),
                           ('global', '10:120')):
    conf.registerChannelValue(IRCquotes.flood, _command,
        FloodLimit(_default, _("""Flood limit for %s, as "x:y": at most x
        uses every y seconds in a channel. "quote" is quoteget; "global"
        counts all the commands together.""") % _command))

conf.registerGlobalValue(IRCquotes, 'antifloodMessageInterval',
    registry.PositiveInteger(20, _("""Determines the minimum number of
    seconds between two flood warnings in a channel.""")))

conf.registerGlobalValue(IRCquotes, 'backupTime',
    BackupTime('00:00', _("""Time of day (HH:MM, bot's local time) of the
    daily backup of the quotes database to ircquotes.db.bak, next to it.
    The backup is only rewritten if the database changed, and it's restored
    automatically if the database goes missing. Empty disables it.""")))

conf.registerGroup(IRCquotes, 'web')
conf.registerGlobalValue(IRCquotes.web, 'enable',
    registry.Boolean(False, _("""Determines whether the quotes database will
    be browsable on the bot's HTTP server (see supybot.servers.http).""")))
conf.registerChannelValue(IRCquotes.web, 'channel',
    registry.Boolean(False, _("""Determines whether this channel's quotes
    can be displayed via the web server.""")))
conf.registerChannelValue(IRCquotes.web, 'topQuotesEnabled',
    registry.Boolean(True, _("""Determines whether the web page shows a
    "top quotes" panel of the best-rated quotes, above the full list.""")))
conf.registerChannelValue(IRCquotes.web, 'topQuotesCount',
    registry.PositiveInteger(5, _("""Determines how many quotes are shown
    in the "top quotes" panel, when enabled.""")))
conf.registerChannelValue(IRCquotes.web, 'quotesPerPage',
    registry.NonNegativeInteger(50, _("""Determines how many quotes are
    shown per page on the web interface, same as the original script's
    html_quotes_per_page. Set to 0 to show every quote on a single
    page.""")))
conf.registerChannelValue(IRCquotes.web, 'newestFirst',
    registry.Boolean(True, _("""Determines whether the web page lists the
    newest quotes first (otherwise oldest first).""")))
conf.registerChannelValue(IRCquotes.web, 'showAuthor',
    registry.Boolean(False, _("""Determines whether the web page shows who
    added each quote.""")))
conf.registerChannelValue(IRCquotes.web, 'keepStyles',
    registry.Boolean(True, _("""Determines whether the mIRC colors, bold,
    italics and underline of the quotes are kept on the web page (otherwise
    they're removed).""")))
conf.registerGlobalValue(IRCquotes.web, 'footer1',
    registry.String('', _("""First line of the web page footer. It's raw
    HTML, which is why it can only be set globally, by the bot owner.""")))
conf.registerGlobalValue(IRCquotes.web, 'footer2',
    registry.String('', _("""Second line of the web page footer, raw HTML
    too.""")))
conf.registerChannelValue(IRCquotes.web, 'publicUrl',
    registry.String('', _("""If set, the externally-reachable base URL
    IRCquotes is served from (e.g. behind a reverse proxy in front of
    the bot's own HTTP server), such as
    "https://quotes.example.com/ircquotes/". The network and channel are
    appended automatically to build the full page URL shown by the
    quotepage command, quotestats and the flood warnings. Same idea as the
    original script's html_page_url. Empty (the default) means nothing to
    show.""")))


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
