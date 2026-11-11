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


from supybot import callbacks, ircdb

try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('ChanOnly')
except ImportError:
    _ = lambda x: x


class ChanOnly(callbacks.Plugin):
    """Blocks every command in a channel except those of the plugins listed
    in plugins.ChanOnly.allowed for that channel. Owners and (by default)
    channel ops are exempt. It has no commands of its own; configure it with
    "config channel #chan plugins.ChanOnly.allowed Gemini"."""

    def __init__(self, irc):
        super().__init__(irc)
        # Class-level list shared by every plugin; Limnoria calls each entry
        # before running any command and drops the command if one returns
        # True.
        callbacks.Commands.pre_command_callbacks.append(self._preCommand)

    def die(self):
        hooks = callbacks.Commands.pre_command_callbacks
        while self._preCommand in hooks:
            hooks.remove(self._preCommand)
        super().die()

    def _preCommand(self, cb, command, irc, msg, *args, **kwargs):
        channel = msg.channel
        if not channel:
            return False
        network = getattr(irc, 'network', None)
        if not self.registryValue('enabled', channel, network):
            return False
        allowed = self.registryValue('allowed', channel, network)
        if callbacks.canonicalName(cb.name()) in \
                {callbacks.canonicalName(p) for p in allowed}:
            return False
        # ignoreDefaultAllow: otherwise a channel's defaultAllow (True unless
        # changed) hands #channel,op to everyone the channel doesn't deny.
        if ircdb.checkCapability(msg.prefix, 'owner',
                                 ignoreDefaultAllow=True):
            return False
        exempt = self.registryValue('exemptGlobal', channel, network).strip()
        if exempt and ircdb.checkCapability(msg.prefix, exempt,
                                            ignoreDefaultAllow=True):
            return False
        exempt = self.registryValue('exempt', channel, network).strip()
        if exempt and ircdb.checkCapability(
                msg.prefix, ircdb.makeChannelCapability(channel, exempt),
                ignoreDefaultAllow=True):
            return False
        self.log.info('ChanOnly: blocked %s %s from %s on %s.', cb.name(),
                      ' '.join(command), msg.prefix, channel)
        if self.registryValue('notify', channel, network):
            if allowed:
                irc.error(_('Only commands from %s work in %s.') %
                          (', '.join(allowed), channel))
            else:
                irc.error(_('Commands are disabled in %s.') % channel)
        return True


Class = ChanOnly


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
