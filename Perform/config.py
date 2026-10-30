###
# Copyright (c) 2026, TehPeGaSuS
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


from supybot import conf, registry
try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization("Perform")
except ImportError:
    _ = lambda x: x


def configure(advanced):
    from supybot.questions import expect, anything, something, yn
    conf.registerPlugin("Perform", True)


Perform = conf.registerPlugin('Perform')

conf.registerNetworkValue(Perform, 'enabled',
    registry.Boolean(True, _("""Whether the perform list is sent when the bot
    connects to this network.""")))

conf.registerNetworkValue(Perform, 'delay',
    registry.NonNegativeInteger(0, _("""Seconds to wait after the end of the
    MOTD before sending the perform list (0 = right away, as ZNC does).""")))

conf.registerNetworkValue(Perform, 'nickRecoverEnabled',
    registry.Boolean(True, _("""Whether the bot tries to get its configured
    nick back (supybot.networks.<network>.nick, else supybot.nick) when it
    is connected under another one: it sends the nickrecover lines, then
    NICK, and repeats every nickRecoverInterval seconds. It also tries as
    soon as the holder quits or changes nick.""")))

conf.registerNetworkValue(Perform, 'nickRecoverInterval',
    registry.PositiveInteger(300, _("""Seconds between two attempts to get
    the configured nick back.""")))

conf.registerNetworkValue(Perform, 'nickRecoverTries',
    registry.NonNegativeInteger(12, _("""How many timed attempts per
    connection before giving up (0 = never give up). The holder quitting
    or changing nick is still acted on after that.""")))


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
