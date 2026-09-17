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
    registry.Boolean(True, _("""Determines whether the quotes commands
    (addquote, quote, delquote, etc.) are enabled in this channel.""")))

conf.registerChannelValue(IRCquotes, 'requireVoteRegistration',
    registry.Boolean(False, _("""Determines whether users must be registered
    with the bot in order to vote on quotes with votequote.""")))

conf.registerChannelValue(IRCquotes, 'autoRandQuoteInterval',
    registry.NonNegativeInteger(0, _("""Determines how often, in seconds, the
    bot automatically announces a random quote in this channel. Set to 0
    to disable automatic announcing (the default).""")))

conf.registerGroup(IRCquotes, 'web')
conf.registerGlobalValue(IRCquotes.web, 'enable',
    registry.Boolean(False, _("""Determines whether the quotes database will
    be browsable on the bot's HTTP server (see supybot.servers.http).""")))
conf.registerChannelValue(IRCquotes.web, 'channel',
    registry.Boolean(False, _("""Determines whether this channel's quotes
    can be displayed via the web server.""")))


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
