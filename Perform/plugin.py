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
Perform: a per-network list of raw IRC lines sent each time the bot
connects (ZNC's *perform: add/del/list/swap/delall/execute), plus nick
recovery: when the bot is connected under another nick than the configured
one, it sends the network's nickrecover lines (GHOST, RECOVER, REGAIN...)
and asks for the nick back, periodically and as soon as the holder leaves.
"""

import os
import json
import time
import threading

from supybot import callbacks, conf, ircmsgs, ircutils, schedule, world
from supybot.commands import wrap
try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('Perform')
except ImportError:
    _ = lambda x: x


class Store(object):
    """The lists, per network, in a JSON file in the bot's data directory:
    {network: {"perform": [line, ...], "nickrecover": [line, ...]}}."""

    KINDS = ('perform', 'nickrecover')

    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.data = {}
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    self.data = json.load(f)
        except Exception as e:
            callbacks.log.error('Perform: cannot load %s, starting empty: %s', path, e)
            self.data = {}

    def save(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)

    def lines(self, network, kind='perform'):
        with self.lock:
            return list(self.data.get(network.lower(), {}).get(kind, []))

    def _list(self, network, kind):
        return self.data.setdefault(network.lower(), {}).setdefault(kind, [])

    def add(self, network, line, kind='perform'):
        with self.lock:
            lst = self._list(network, kind)
            lst.append(line)
            n = len(lst)
        self.save()
        return n

    def delete(self, network, nr, kind='perform'):
        """Removes entry number `nr` (1-based). Returns the line, or None."""
        with self.lock:
            lst = self._list(network, kind)
            if not 1 <= nr <= len(lst):
                return None
            line = lst.pop(nr - 1)
        self.save()
        return line

    def swap(self, network, a, b, kind='perform'):
        with self.lock:
            lst = self._list(network, kind)
            if not (1 <= a <= len(lst) and 1 <= b <= len(lst)):
                return False
            lst[a - 1], lst[b - 1] = lst[b - 1], lst[a - 1]
        self.save()
        return True

    def clear(self, network, kind='perform'):
        with self.lock:
            lst = self._list(network, kind)
            n = len(lst)
            del lst[:]
        self.save()
        return n


def _rawMsg(line):
    """An IrcMsg for a raw line typed by the owner; None if it won't parse."""
    line = line.strip()
    if not line:
        return None
    try:
        return ircmsgs.IrcMsg(line)
    except Exception:
        return None


class Perform(callbacks.Plugin):
    """ZNC-style perform list (raw lines sent on connect) and nick recovery.
    Owner only. The list is per network: "perform add PRIVMSG NickServ :IDENTIFY
    secret", "perform list", "perform execute". Nick recovery:
    "nickrecover add PRIVMSG NickServ :GHOST %nick% secret" (also reachable as
    "perform nickrecover ...")."""
    threaded = False

    def __init__(self, irc):
        self.__parent = super(Perform, self)
        self.__parent.__init__(irc)
        dataDir = conf.supybot.directories.data.dirize('Perform')
        self.store = Store(os.path.join(dataDir, 'perform.json'))
        # network -> {'tries': n, 'last': t, 'gaveUp': bool}
        self._recovery = {}
        self._events = set()
        # Already connected networks (plugin loaded after connect)
        for net in world.ircs:
            if getattr(net, 'afterConnect', False):
                self._armRecovery(net)

    def die(self):
        for name in list(self._events):
            self._unschedule(name)
        self.__parent.die()

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _schedule(self, name, when, f, args=()):
        self._unschedule(name)
        schedule.addEvent(lambda: f(*args), when, name)
        self._events.add(name)

    def _unschedule(self, name):
        if name in self._events:
            try:
                schedule.removeEvent(name)
            except KeyError:
                pass
            self._events.discard(name)

    def _wantedNick(self, irc):
        """The nick the bot is configured to use on this network."""
        try:
            nick = conf.supybot.networks.get(irc.network).nick()
        except Exception:
            nick = ''
        return nick or conf.supybot.nick()

    def _expand(self, irc, line, nick=None):
        """%nick% is the bot's current nick (ZNC), or `nick` when given;
        %wantnick% the configured nick; %network% the network name."""
        return (line.replace('%nick%', nick or irc.nick)
                    .replace('%wantnick%', self._wantedNick(irc))
                    .replace('%network%', irc.network))

    def _send(self, irc, lines, nick=None):
        """Sends raw lines in order; returns how many were sent."""
        sent = 0
        for line in lines:
            msg = _rawMsg(self._expand(irc, line, nick))
            if msg is None:
                self.log.warning('Perform: skipping unparsable line on %s: %r',
                                 irc.network, line)
                continue
            irc.sendMsg(msg)      # FIFO: queueMsg would reorder MODE etc.
            sent += 1
        return sent

    def _network(self, irc, network):
        """The Irc object for `network` (an Irc from the networkIrc
        converter, or the current one)."""
        return network if network is not None else irc

    # -----------------------------------------------------------------
    # Connect: the perform list, then nick recovery
    # -----------------------------------------------------------------

    def do376(self, irc, msg):
        self._onConnect(irc)

    do422 = do376

    def _onConnect(self, irc):
        if self.registryValue('enabled', network=irc.network):
            delay = self.registryValue('delay', network=irc.network)
            if delay:
                self._schedule('Perform.execute.%s' % irc.network, time.time() + delay,
                               self._executeOn, (irc.network,))
            else:
                self._execute(irc)
        self._armRecovery(irc)

    def _executeOn(self, network):
        irc = world.getIrc(network)
        if irc is not None:
            self._execute(irc)

    def _execute(self, irc):
        lines = self.store.lines(irc.network, 'perform')
        if lines:
            n = self._send(irc, lines)
            self.log.info('Perform: sent %d line(s) on %s.', n, irc.network)
        return len(lines)

    # -----------------------------------------------------------------
    # Nick recovery
    # -----------------------------------------------------------------

    def _armRecovery(self, irc):
        self._recovery[irc.network] = {'tries': 0, 'last': 0, 'gaveUp': False}
        self._tryRecover(irc, timed=True)

    def _recoveryWanted(self, irc):
        if not self.registryValue('nickRecoverEnabled', network=irc.network):
            return False
        if not getattr(irc, 'afterConnect', True):
            return False
        return not ircutils.nickEqual(irc.nick, self._wantedNick(irc))

    def _tryRecover(self, irc, timed=False, force=False):
        """One attempt to get the configured nick back: the nickrecover
        lines, then NICK. Timed attempts stop after nickRecoverTries; an
        attempt made because the holder left (`force`) does not count and
        is always made. Returns whether an attempt was sent."""
        name = 'Perform.recover.%s' % irc.network
        state = self._recovery.setdefault(irc.network, {'tries': 0, 'last': 0, 'gaveUp': False})
        if not self._recoveryWanted(irc):
            self._unschedule(name)
            return False
        wanted = self._wantedNick(irc)
        limit = self.registryValue('nickRecoverTries', network=irc.network)
        interval = self.registryValue('nickRecoverInterval', network=irc.network)
        if timed:
            if limit and state['tries'] >= limit:
                if not state['gaveUp']:
                    state['gaveUp'] = True
                    self.log.warning('Perform: gave up getting nick %s back on %s after %d '
                                     'tries; staying %s (use: nickrecover execute).',
                                     wanted, irc.network, limit, irc.nick)
                self._unschedule(name)
                return False
            state['tries'] += 1
        elif not force:
            return False
        state['last'] = time.time()
        self._send(irc, self.store.lines(irc.network, 'nickrecover'), nick=wanted)
        irc.sendMsg(ircmsgs.nick(wanted))
        self.log.info('Perform: trying to get nick %s back on %s (attempt %d).',
                      wanted, irc.network, state['tries'])
        if timed:
            self._schedule(name, time.time() + interval, self._timedRecover, (irc.network,))
        return True

    def _timedRecover(self, network):
        irc = world.getIrc(network)
        if irc is not None:
            self._tryRecover(irc, timed=True)

    def doNick(self, irc, msg):
        newNick = msg.args[0]
        wanted = self._wantedNick(irc)
        if msg.nick == irc.nick or ircutils.nickEqual(newNick, irc.nick):
            # Our own nick change (irc.nick may already be updated).
            if ircutils.nickEqual(newNick, wanted):
                self.log.info('Perform: got nick %s back on %s.', wanted, irc.network)
                self._unschedule('Perform.recover.%s' % irc.network)
                self._recovery.pop(irc.network, None)
            return
        if ircutils.nickEqual(msg.nick, wanted) and not ircutils.nickEqual(newNick, wanted):
            # The holder let go of our nick.
            self._tryRecover(irc, force=True)

    def doQuit(self, irc, msg):
        if ircutils.nickEqual(msg.nick, self._wantedNick(irc)):
            self._tryRecover(irc, force=True)

    # -----------------------------------------------------------------
    # Commands: the perform list (ZNC's add/del/list/swap/delall/execute)
    # -----------------------------------------------------------------

    def add(self, irc, msg, args, network, line):
        """[<network>] <raw line>

        Appends a raw IRC line to the perform list of <network> (default:
        the current one). %nick% expands to the bot's current nick,
        %wantnick% to its configured nick, %network% to the network name.
        """
        target = self._network(irc, network)
        if _rawMsg(self._expand(target, line)) is None:
            irc.error(_('That does not parse as an IRC line.'))
            return
        n = self.store.add(target.network, line)
        irc.replySuccess(_('Added as #%d on %s.') % (n, target.network))
    add = wrap(add, ['owner', 'networkIrc', 'text'])

    def delete(self, irc, msg, args, network, nr):
        """[<network>] <nr>

        Removes entry <nr> from the perform list (see "perform list").
        """
        target = self._network(irc, network)
        line = self.store.delete(target.network, nr)
        if line is None:
            irc.error(_('No entry #%d on %s.') % (nr, target.network))
        else:
            irc.replySuccess(_('Removed #%d (%s) on %s.') % (nr, line, target.network))
    delete = wrap(delete, ['owner', 'networkIrc', 'positiveInt'])

    def list(self, irc, msg, args, network):
        """[<network>]

        Lists the perform list of <network>, numbered. Answered in private:
        the lines usually contain passwords.
        """
        target = self._network(irc, network)
        lines = self.store.lines(target.network)
        if not lines:
            irc.reply(_('The perform list of %s is empty.') % target.network, private=True)
            return
        for i, line in enumerate(lines, 1):
            irc.reply('[%s] #%d: %s' % (target.network, i, line), private=True)
    list = wrap(list, ['owner', 'networkIrc'])

    def swap(self, irc, msg, args, network, a, b):
        """[<network>] <nr> <nr>

        Swaps two entries of the perform list.
        """
        target = self._network(irc, network)
        if self.store.swap(target.network, a, b):
            irc.replySuccess()
        else:
            irc.error(_('No such entries on %s.') % target.network)
    swap = wrap(swap, ['owner', 'networkIrc', 'positiveInt', 'positiveInt'])

    def delall(self, irc, msg, args, network):
        """[<network>]

        Empties the perform list of <network>.
        """
        target = self._network(irc, network)
        n = self.store.clear(target.network)
        irc.replySuccess(_('Removed %d line(s) on %s.') % (n, target.network))
    delall = wrap(delall, ['owner', 'networkIrc'])

    def execute(self, irc, msg, args, network):
        """[<network>]

        Sends the perform list of <network> now, as if the bot had just
        connected.
        """
        target = self._network(irc, network)
        n = self._execute(target)
        irc.replySuccess(_('Sent %d line(s) on %s.') % (n, target.network))
    execute = wrap(execute, ['owner', 'networkIrc'])

    # -----------------------------------------------------------------
    # Commands: nick recovery
    # -----------------------------------------------------------------

    class nickrecover(callbacks.Commands):
        """The lines sent before asking for the configured nick back."""

        def _plugin(self, irc):
            return irc.getCallback('Perform')

        def add(self, irc, msg, args, network, line):
            """[<network>] <raw line>

            Appends a raw line to the nick-recovery list of <network>:
            what to send before NICK when the configured nick is taken
            (e.g. PRIVMSG NickServ :GHOST %nick% secret). Here %nick% is the
            nick being recovered.
            """
            plugin = self._plugin(irc)
            target = plugin._network(irc, network)
            if _rawMsg(plugin._expand(target, line, nick=plugin._wantedNick(target))) is None:
                irc.error(_('That does not parse as an IRC line.'))
                return
            n = plugin.store.add(target.network, line, 'nickrecover')
            irc.replySuccess(_('Added as #%d on %s.') % (n, target.network))
        add = wrap(add, ['owner', 'networkIrc', 'text'])

        def delete(self, irc, msg, args, network, nr):
            """[<network>] <nr>

            Removes entry <nr> from the nick-recovery list.
            """
            plugin = self._plugin(irc)
            target = plugin._network(irc, network)
            line = plugin.store.delete(target.network, nr, 'nickrecover')
            if line is None:
                irc.error(_('No entry #%d on %s.') % (nr, target.network))
            else:
                irc.replySuccess(_('Removed #%d (%s) on %s.') % (nr, line, target.network))
        delete = wrap(delete, ['owner', 'networkIrc', 'positiveInt'])

        def list(self, irc, msg, args, network):
            """[<network>]

            Lists the nick-recovery lines of <network> (in private).
            """
            plugin = self._plugin(irc)
            target = plugin._network(irc, network)
            lines = plugin.store.lines(target.network, 'nickrecover')
            if not lines:
                irc.reply(_('The nick-recovery list of %s is empty.') % target.network,
                          private=True)
                return
            for i, line in enumerate(lines, 1):
                irc.reply('[%s] #%d: %s' % (target.network, i, line), private=True)
        list = wrap(list, ['owner', 'networkIrc'])

        def delall(self, irc, msg, args, network):
            """[<network>]

            Empties the nick-recovery list of <network>.
            """
            plugin = self._plugin(irc)
            target = plugin._network(irc, network)
            n = plugin.store.clear(target.network, 'nickrecover')
            irc.replySuccess(_('Removed %d line(s) on %s.') % (n, target.network))
        delall = wrap(delall, ['owner', 'networkIrc'])

        def execute(self, irc, msg, args, network):
            """[<network>]

            Sends the nick-recovery lines and asks for the configured nick
            right now, even after the bot gave up, and restarts the timed
            attempts.
            """
            plugin = self._plugin(irc)
            target = plugin._network(irc, network)
            if not plugin._recoveryWanted(target):
                irc.reply(_('Nothing to recover on %s: the bot is %s.')
                          % (target.network, target.nick))
                return
            plugin._recovery[target.network] = {'tries': 0, 'last': 0, 'gaveUp': False}
            plugin._tryRecover(target, timed=True)
            irc.replySuccess(_('Trying to get %s back on %s.')
                             % (plugin._wantedNick(target), target.network))
        execute = wrap(execute, ['owner', 'networkIrc'])

        def status(self, irc, msg, args, network):
            """[<network>]

            Where nick recovery stands on <network>.
            """
            plugin = self._plugin(irc)
            target = plugin._network(irc, network)
            wanted = plugin._wantedNick(target)
            if ircutils.nickEqual(target.nick, wanted):
                irc.reply(_('%s: the bot has its nick (%s).') % (target.network, wanted))
                return
            state = plugin._recovery.get(target.network, {'tries': 0, 'gaveUp': False})
            irc.reply(_('%s: the bot is %s, wants %s; %d timed attempt(s) so far%s.')
                      % (target.network, target.nick, wanted, state['tries'],
                         _(', gave up') if state['gaveUp'] else ''))
        status = wrap(status, ['owner', 'networkIrc'])

    # ZNC spells it "del"; Python can't name a method that.
    setattr(nickrecover, 'del', nickrecover.delete)


setattr(Perform, 'del', Perform.delete)

Class = Perform


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
