###
# Copyright (c) 2022, Mike Oxlong
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

from . import plugin

from supybot import conf, registry
try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization("Blacklist")
except:
    # Placeholder that allows to run the plugin on a bot
    # without the i18n module
    _ = lambda x: x

def configure(advanced):
    # This will be called by supybot to configure this module.  advanced is
    # a bool that specifies whether the user identified themself as an advanced
    # user or not.  You should effect your configuration by manipulating the
    # registry as appropriate.
    from supybot.questions import expect, anything, something, yn
    conf.registerPlugin("Blacklist", True)

class CurrencyCommand(registry.Integer):
    def setValue(self, num):
        if num > max(plugin.Blacklist.banmasks):
            raise registry.InvalidRegistryValue(f"Number must be between 0 and {max(plugin.Blacklist.banmasks)}.")
        registry.String.setValue(self, num)

Blacklist = conf.registerPlugin('Blacklist')

conf.registerChannelValue(Blacklist, 'maxInlineEntries',
        registry.PositiveInteger(5, """Maximum number of ban entries to display inline before using pastebin."""))

conf.registerChannelValue(Blacklist, 'enabled',
        registry.Boolean(False, """Set whether to enable database in a channel."""))

conf.registerChannelValue(Blacklist, 'banlistExpiry',
        registry.PositiveInteger(180, """Sets the number of minutes before a ban is removed from the channl's banlist."""))

conf.registerChannelValue(Blacklist, 'banTimerExpiry',
        registry.PositiveInteger(30, """Sets the numer of minutes before a timed ban expires if none is given."""))

conf.registerChannelValue(Blacklist, 'maskNumber',
        CurrencyCommand(2, """Sets the default banmask number if none is given."""))

conf.registerChannelValue(Blacklist, 'banReason',
        registry.String("User has been banned from the channel.", """Sets the default blacklist message if none is given."""))

conf.registerChannelValue(Blacklist, 'addManualBans',
        registry.Boolean(True, """Sets whether to watch for channel bans directly added by users (not using the bot) to the database."""))

# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79: