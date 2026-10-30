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

"""
Slapper: "slap [<nick>]" sends a random phrase as a /me action. No nick
slaps the caller; slapping the bot slaps the caller back. Phrases and
custom variables are managed with "slaps ...".
"""

import os
import re
import json
import random
import threading

from supybot import callbacks, conf, ircdb, ircutils
from supybot.commands import wrap, optional
try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('Slapper')
except ImportError:
    _ = lambda x: x


# Filled in at slap time; a custom variable can't take these names.
BUILTINS = {
    'nick': 'who gets slapped',
    'who': 'who asked for the slap',
    'channel': 'the channel',
    'botnick': "the bot's nick",
    'randnick': 'a random user of the channel (not the bot)',
}

DEFAULT_PHRASES = [
    'slaps $nick around a bit with $fish',
    'slaps $nick with $fish',
    'hits $nick over the head with $object',
    'smacks $nick with $object. Courtesy of $who',
]

DEFAULT_VARS = {
    'fish': ['a large trout', 'a wet mackerel', 'a frozen herring', 'a slimy cod'],
    'object': ['a rubber chicken', 'a rolled-up newspaper', 'a keyboard', 'a pillow'],
}

VAR_RE = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)')
NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


class Store(object):
    """{"phrases": [...], "vars": {name: [value, ...]}} in a JSON file."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        data = None
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
        except Exception as e:
            callbacks.log.error('Slapper: cannot load %s, using defaults: %s', path, e)
        if not isinstance(data, dict):
            data = {'phrases': list(DEFAULT_PHRASES),
                    'vars': {k: list(v) for k, v in DEFAULT_VARS.items()}}
        data.setdefault('phrases', [])
        data.setdefault('vars', {})
        self.data = data

    def save(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)

    def phrases(self):
        with self.lock:
            return list(self.data['phrases'])

    def addPhrase(self, text):
        with self.lock:
            self.data['phrases'].append(text)
            n = len(self.data['phrases'])
        self.save()
        return n

    def delPhrase(self, nr):
        with self.lock:
            lst = self.data['phrases']
            if not 1 <= nr <= len(lst):
                return None
            text = lst.pop(nr - 1)
        self.save()
        return text

    def vars(self):
        with self.lock:
            return {k: list(v) for k, v in self.data['vars'].items()}

    def addValue(self, name, value):
        with self.lock:
            lst = self.data['vars'].setdefault(name.lower(), [])
            lst.append(value)
            n = len(lst)
        self.save()
        return n

    def delValue(self, name, nr=None):
        """Removes value `nr` of a variable, or the whole variable when nr
        is None. Returns what was removed (a value, a list) or None."""
        with self.lock:
            lst = self.data['vars'].get(name.lower())
            if lst is None:
                return None
            if nr is None:
                removed = self.data['vars'].pop(name.lower())
            else:
                if not 1 <= nr <= len(lst):
                    return None
                removed = lst.pop(nr - 1)
                if not lst:
                    del self.data['vars'][name.lower()]
        self.save()
        return removed


class Slapper(callbacks.Plugin):
    """Slaps people. "slap [<nick>]" sends a random phrase as a /me action;
    without a nick you slap yourself, and slapping the bot slaps you back.
    Manage phrases with "slaps add|del|list" and variables with
    "slaps var add|del|list". Phrases can use $nick, $who, $channel,
    $botnick, $randnick and any variable you define ($fish picks one of the
    values of the variable "fish")."""
    threaded = False

    def __init__(self, irc):
        self.__parent = super(Slapper, self)
        self.__parent.__init__(irc)
        self.store = Store(conf.supybot.directories.data.dirize('Slapper/slaps.json'))

    # -----------------------------------------------------------------

    def _render(self, phrase, values, custom):
        """Replaces $variables: built-ins from `values`, custom ones with a
        random value. Custom values may use variables too (a few levels
        deep); unknown names are left as they are."""
        def sub(m):
            name = m.group(1).lower()
            if name in values:
                return values[name]
            if custom.get(name):
                return random.choice(custom[name])
            return m.group(0)
        for _ in range(4):
            new = VAR_RE.sub(sub, phrase)
            if new == phrase:
                break
            phrase = new
        return phrase

    def _randomNick(self, irc, channel, exclude):
        try:
            users = [u for u in irc.state.channels[channel].users
                     if not ircutils.nickEqual(u, irc.nick)]
        except KeyError:
            return exclude
        return random.choice(users) if users else exclude

    def _canManage(self, irc, msg):
        cap = self.registryValue('manageCapability')
        if ircdb.checkCapability(msg.prefix, 'owner') or ircdb.checkCapability(msg.prefix, cap):
            return True
        irc.errorNoCapability(cap, Raise=False)
        return False

    # -----------------------------------------------------------------

    def slap(self, irc, msg, args, channel, target):
        """[<nick>]

        Slaps <nick>, or you if no nick is given. Slapping the bot is a
        bad idea.
        """
        if channel and not self.registryValue('enabled', channel, irc.network):
            return
        phrases = self.store.phrases()
        if not phrases:
            irc.error(_('There are no slap phrases; add one with "slaps add".'))
            return
        target = (target or '').strip() or msg.nick
        if ircutils.nickEqual(target, irc.nick):
            target = msg.nick                  # it slaps back
        values = {'nick': target, 'who': msg.nick, 'channel': channel or msg.nick,
                  'botnick': irc.nick,
                  'randnick': self._randomNick(irc, channel, msg.nick) if channel else msg.nick}
        text = self._render(random.choice(phrases), values, self.store.vars())
        irc.reply(text, action=True, prefixNick=False)
    slap = wrap(slap, [optional('inChannel'), optional('text')])

    class slaps(callbacks.Commands):
        """Manage slap phrases and variables."""

        def _plugin(self, irc):
            return irc.getCallback('Slapper')

        def add(self, irc, msg, args, text):
            """<phrase>

            Adds a slap phrase, sent as a /me action. It must contain
            $nick. Variables: $nick, $who, $channel, $botnick, $randnick and
            your own (see "slaps var").
            """
            plugin = self._plugin(irc)
            if not plugin._canManage(irc, msg):
                return
            if '$nick' not in text.lower():
                irc.error(_('The phrase must contain $nick (who gets slapped).'))
                return
            n = plugin.store.addPhrase(text)
            irc.replySuccess(_('Added as #%d.') % n)
        add = wrap(add, ['text'])

        def delete(self, irc, msg, args, nr):
            """<nr>

            Removes slap phrase <nr> (see "slaps list").
            """
            plugin = self._plugin(irc)
            if not plugin._canManage(irc, msg):
                return
            text = plugin.store.delPhrase(nr)
            if text is None:
                irc.error(_('There is no phrase #%d.') % nr)
            else:
                irc.replySuccess(_('Removed #%d: %s') % (nr, text))
        delete = wrap(delete, ['positiveInt'])

        def list(self, irc, msg, args):
            """takes no arguments

            Lists the slap phrases, numbered.
            """
            phrases = self._plugin(irc).store.phrases()
            if not phrases:
                irc.reply(_('No slap phrases yet.'))
                return
            irc.reply(' | '.join('#%d: %s' % (i, p) for i, p in enumerate(phrases, 1)))
        list = wrap(list)

        class var(callbacks.Commands):
            """Manage the variables slap phrases can use."""

            def _plugin(self, irc):
                return irc.getCallback('Slapper')

            def add(self, irc, msg, args, name, value):
                """<name> <value>

                Adds <value> to variable <name> ($<name> in phrases picks a
                random value). A value may use other variables.
                """
                plugin = self._plugin(irc)
                if not plugin._canManage(irc, msg):
                    return
                name = name.lstrip('$')
                if not NAME_RE.match(name):
                    irc.error(_('A variable name is letters, digits and _, not starting with a digit.'))
                    return
                if name.lower() in BUILTINS:
                    irc.error(_('$%s is built in.') % name.lower())
                    return
                n = plugin.store.addValue(name, value)
                irc.replySuccess(_('$%s now has %d value(s).') % (name.lower(), n))
            add = wrap(add, ['something', 'text'])

            def delete(self, irc, msg, args, name, nr):
                """<name> [<nr>]

                Removes value <nr> of variable <name>, or the whole variable.
                """
                plugin = self._plugin(irc)
                if not plugin._canManage(irc, msg):
                    return
                name = name.lstrip('$')
                removed = plugin.store.delValue(name, nr)
                if removed is None:
                    irc.error(_('No such variable or value.'))
                elif nr is None:
                    irc.replySuccess(_('Removed $%s (%d value(s)).') % (name.lower(), len(removed)))
                else:
                    irc.replySuccess(_('Removed "%s" from $%s.') % (removed, name.lower()))
            delete = wrap(delete, ['something', optional('positiveInt')])

            def list(self, irc, msg, args, name):
                """[<name>]

                Lists the variables, or the numbered values of <name>.
                """
                plugin = self._plugin(irc)
                custom = plugin.store.vars()
                if name:
                    name = name.lstrip('$').lower()
                    if name in BUILTINS:
                        irc.reply('$%s: %s' % (name, BUILTINS[name]))
                    elif name in custom:
                        irc.reply('$%s: %s' % (name, ' | '.join(
                            '#%d: %s' % (i, v) for i, v in enumerate(custom[name], 1))))
                    else:
                        irc.error(_('No variable $%s.') % name)
                    return
                builtin = ', '.join('$' + k for k in BUILTINS)
                mine = ', '.join('$%s (%d)' % (k, len(v)) for k, v in sorted(custom.items()))
                irc.reply(_('Built in: %s. Yours: %s.') % (builtin, mine or _('none')))
            list = wrap(list, [optional('something')])

        setattr(var, 'del', var.delete)

    setattr(slaps, 'del', slaps.delete)


Class = Slapper


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
