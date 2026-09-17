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


IRCquotes = conf.registerPlugin('IRCquotes')

conf.registerChannelValue(IRCquotes, 'enabled',
    registry.Boolean(False, _("""Determines whether the quotes commands
    (addquote, quoteget, delquote, etc.) are enabled in this channel.
    Disabled by default: it's an opt-in feature, so enable it per
    channel with "config channel <channel> plugins.IRCquotes.enabled
    true".""")))

conf.registerChannelValue(IRCquotes, 'requireVoteRegistration',
    registry.Boolean(False, _("""Determines whether users must be registered
    with the bot in order to vote on quotes with votequote.""")))

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

conf.registerChannelValue(IRCquotes, 'autoRandQuoteInterval',
    registry.NonNegativeInteger(0, _("""Determines how often, in seconds, the
    bot automatically announces a random quote in this channel. Set to 0
    to disable automatic announcing (the default).""")))

conf.registerChannelValue(IRCquotes, 'findQuoteMaxResults',
    registry.NonNegativeInteger(20, _("""Determines the maximum number of
    matches findquote will list in a single reply (same idea as the
    original script's max_findquote/max_findquote_total). Set to 0 for
    no limit.""")))

conf.registerChannelValue(IRCquotes, 'minQuoteChars',
    registry.NonNegativeInteger(0, _("""If non-zero, addquote will refuse
    quotes shorter than this many characters (same idea as the original
    script's min_chars_to_quote). Disabled (0) by default.""")))

conf.registerChannelValue(IRCquotes, 'minQuoteWords',
    registry.NonNegativeInteger(0, _("""If non-zero, addquote will refuse
    quotes with fewer words than this (same idea as the original script's
    min_words_to_quote). Disabled (0) by default.""")))

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


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
