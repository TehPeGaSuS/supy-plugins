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

from supybot import callbacks, conf, ircdb, ircutils, log

try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('NoPrivate')
except ImportError:
    _ = lambda x: x


class NoPrivate(callbacks.Plugin):
    """Silently drops private messages (commands included) from everyone
    except users with the configured capability (admin by default) and
    owners. Channel messages, notices and server messages are untouched, so
    NickServ and friends keep working."""

    def _isAllowedCommand(self, text):
        prefixChars = conf.supybot.reply.whenAddressedBy.chars()
        words = text.lstrip(prefixChars).lower().split()[:2]
        allowed = [c.lower() for c in self.registryValue('allowedCommands')]
        return any(w in allowed for w in words)

    def inFilter(self, irc, msg):
        if msg.command != 'PRIVMSG' or irc.isChannel(msg.args[0]):
            return msg
        if not ircutils.isUserHostmask(msg.prefix):
            return msg
        if ircdb.checkCapability(msg.prefix, self.registryValue('capability')):
            return msg
        if self._isAllowedCommand(msg.args[1]):
            return msg
        log.debug('NoPrivate: dropping private message from %s', msg.prefix)
        return None


Class = NoPrivate


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
