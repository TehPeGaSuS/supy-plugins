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
    _ = PluginInternationalization("ChanOnly")
except ImportError:
    _ = lambda x: x


def configure(advanced):
    from supybot.questions import expect, anything, something, yn
    conf.registerPlugin("ChanOnly", True)


ChanOnly = conf.registerPlugin('ChanOnly')

conf.registerChannelValue(ChanOnly, 'enabled',
    registry.Boolean(False, _("""Block commands in this channel for
    everyone who isn't exempt, except those of the plugins in
    plugins.ChanOnly.allowed.""")))

conf.registerChannelValue(ChanOnly, 'allowed',
    registry.SpaceSeparatedListOfStrings([], _("""Plugins whose commands may
    still be used in this channel while ChanOnly is enabled. Plugin names, not
    command names (e.g. "Gemini NuWeather"), case-insensitive. Empty blocks
    every command.""")))

conf.registerChannelValue(ChanOnly, 'exempt',
    registry.String('op', _("""Channel capability that lets a user run any
    command anyway (so "op" means #channel,op). Owners are always exempt.
    Set to an empty string to disable this exemption.""")))

conf.registerChannelValue(ChanOnly, 'exemptGlobal',
    registry.String('admin', _("""Global capability that lets a user run any
    command anyway. Owners are always exempt. Set to an empty string to
    disable this exemption.""")))

conf.registerChannelValue(ChanOnly, 'notify',
    registry.Boolean(True, _("""Reply with an error (naming the allowed
    plugins, if any) when a command is blocked. If False, blocked commands are
    silently ignored.""")))


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
