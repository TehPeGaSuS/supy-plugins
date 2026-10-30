###
# Copyright (c) 2026, TehPeGaSuS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the above copyright notice and
# this list of conditions are retained. See plugin.py for the full licence.
###

import time

from supybot.test import *
from supybot import conf, ircmsgs, schedule, world

NICK_PLUGIN = conf.supybot.plugins.Perform


class PerformTestCase(PluginTestCase):
    plugins = ('Perform',)

    def setUp(self):
        super().setUp()
        self._cb().store.data = {}

    def _cb(self):
        return self.irc.getCallback('Perform')

    def _drain(self):
        out = []
        m = self.irc.takeMsg()
        while m is not None:
            out.append(m)
            m = self.irc.takeMsg()
        return out

    def _raw(self, msgs):
        return [' '.join((m.command,) + tuple(m.args)) for m in msgs]

    def _connect(self):
        self._drain()
        self.irc.feedMsg(ircmsgs.IrcMsg(':irc.example 376 %s :End of /MOTD' % self.irc.nick))
        return self._raw(self._drain())

    # ---- the perform list -------------------------------------------

    def testAddListDelSwapDelall(self):
        self.assertRegexp('perform add PRIVMSG NickServ :IDENTIFY hunter2', 'Added as #1 on test')
        self.assertRegexp('perform add MODE %nick% +B', 'Added as #2')
        self.assertRegexp('perform add OPER me pass', '#3')
        self.assertNotError('perform swap 1 3')
        self.assertEqual(self._cb().store.lines('test'),
                         ['OPER me pass', 'MODE %nick% +B', 'PRIVMSG NickServ :IDENTIFY hunter2'])
        self.assertRegexp('perform del 2', 'Removed #2 \\(MODE %nick% \\+B\\)')
        self.assertRegexp('perform delete 9', 'No entry #9')
        self.assertRegexp('perform delall', 'Removed 2 line')
        self.assertEqual(self._cb().store.lines('test'), [])

    def testListIsPrivateAndNumbered(self):
        self.assertNotError('perform add PRIVMSG NickServ :IDENTIFY hunter2')
        self.assertNotError('perform add MODE %nick% +B')
        self._drain()
        self.irc.feedMsg(ircmsgs.privmsg(self.irc.nick, 'perform list', prefix=self.prefix))
        msgs = self._drain()
        self.assertEqual([m.args[1] for m in msgs],
                         ['[test] #1: PRIVMSG NickServ :IDENTIFY hunter2', '[test] #2: MODE %nick% +B'])
        self.assertTrue(all(m.args[0] == self.nick for m in msgs))

    def testEmptyList(self):
        self.assertRegexp('perform list', 'empty')

    def testGarbageIsRefused(self):
        self.assertError('perform add :')
        self.assertEqual(self._cb().store.lines('test'), [])

    def testExplicitNetworkArgument(self):
        self.assertRegexp('perform add test PRIVMSG NickServ :IDENTIFY x', 'on test')
        self.assertEqual(self._cb().store.lines('test'), ['PRIVMSG NickServ :IDENTIFY x'])
        # a first word that is not a network is part of the line
        self.assertNotError('perform add PRIVMSG Q@CServe.quakenet.org :AUTH me x')
        self.assertEqual(self._cb().store.lines('test')[1], 'PRIVMSG Q@CServe.quakenet.org :AUTH me x')

    def testSentOnConnectWithVariables(self):
        self.assertNotError('perform add PRIVMSG NickServ :IDENTIFY hunter2')
        self.assertNotError('perform add MODE %nick% +B')
        self.assertNotError('perform add PRIVMSG #ops :%network% up')
        out = self._connect()
        self.assertTrue('PRIVMSG NickServ IDENTIFY hunter2' in out, out)
        self.assertTrue('MODE %s +B' % self.irc.nick in out, out)
        self.assertTrue('PRIVMSG #ops test up' in out, out)
        self.assertTrue(out.index('PRIVMSG NickServ IDENTIFY hunter2') < out.index('MODE %s +B' % self.irc.nick))

    def testNotSentWhenDisabled(self):
        self.assertNotError('perform add PRIVMSG NickServ :IDENTIFY hunter2')
        with NICK_PLUGIN.enabled.context(False):
            out = self._connect()
        self.assertFalse(any('IDENTIFY' in l for l in out), out)

    def testDelayedSend(self):
        self.assertNotError('perform add PRIVMSG NickServ :IDENTIFY hunter2')
        with NICK_PLUGIN.delay.context(60):
            out = self._connect()
            self.assertFalse(any('IDENTIFY' in l for l in out), out)
            self.assertTrue('Perform.execute.test' in self._cb()._events)
            schedule.schedule.events['Perform.execute.test']()
        out = self._raw(self._drain())
        self.assertTrue('PRIVMSG NickServ IDENTIFY hunter2' in out, out)
        self._cb()._unschedule('Perform.execute.test')

    def testExecuteNow(self):
        self.assertNotError('perform add PRIVMSG NickServ :IDENTIFY hunter2')
        self._drain()
        self.irc.feedMsg(ircmsgs.privmsg(self.channel if hasattr(self, 'channel') else self.irc.nick,
                                         'perform execute', prefix=self.prefix))
        out = self._raw(self._drain())
        self.assertTrue('PRIVMSG NickServ IDENTIFY hunter2' in out, out)
        self.assertTrue(any('Sent 1 line' in l for l in out), out)

    def testSurvivesReload(self):
        self.assertNotError('perform add PRIVMSG NickServ :IDENTIFY hunter2')
        path = self._cb().store.path
        from Perform.plugin import Store
        self.assertEqual(Store(path).lines('test'), ['PRIVMSG NickServ :IDENTIFY hunter2'])

    # ---- nick recovery ----------------------------------------------

    def _wanting(self, nick='Wanted'):
        return conf.supybot.nick.context(nick)

    def testNoRecoveryWhenNickIsOurs(self):
        out = self._connect()
        self.assertFalse(any(l.startswith('NICK ') for l in out), out)
        self.assertRegexp('perform nickrecover status', 'has its nick')

    def testRecoveryOnConnectSendsLinesThenNick(self):
        self.assertNotError('perform nickrecover add PRIVMSG NickServ :GHOST %nick% hunter2')
        self.assertNotError('perform nickrecover add PRIVMSG NickServ :RELEASE %nick% hunter2')
        with self._wanting():
            out = self._connect()
            ghost = out.index('PRIVMSG NickServ GHOST Wanted hunter2')
            release = out.index('PRIVMSG NickServ RELEASE Wanted hunter2')
            self.assertTrue(ghost < release < out.index('NICK Wanted'), out)
            self.assertTrue('Perform.recover.test' in self._cb()._events)
            self.assertRegexp('perform nickrecover status', 'is test, wants Wanted; 1 timed attempt')
        self._cb()._unschedule('Perform.recover.test')

    def testRecoveryWhenHolderQuitsOrRenames(self):
        with self._wanting():
            self._connect()
            self.irc.feedMsg(ircmsgs.quit('bye', prefix='Wanted!u@h'))
            out = self._raw(self._drain())
            self.assertEqual(out.count('NICK Wanted'), 1, out)
            self.irc.feedMsg(ircmsgs.nick('Other', prefix='Wanted!u@h'))
            out = self._raw(self._drain())
            self.assertEqual(out.count('NICK Wanted'), 1, out)
            # an unrelated quit does nothing
            self.irc.feedMsg(ircmsgs.quit('bye', prefix='Someone!u@h'))
            self.assertEqual(self._raw(self._drain()), [])
        self._cb()._unschedule('Perform.recover.test')

    def testRecoveryStopsOnceWeHaveTheNick(self):
        with self._wanting():
            self._connect()
            self.irc.feedMsg(ircmsgs.nick('Wanted', prefix=self.irc.prefix))
            self.assertFalse('Perform.recover.test' in self._cb()._events)
            self.assertRegexp('perform nickrecover status', 'has its nick')
            self.irc.feedMsg(ircmsgs.quit('bye', prefix='Wanted!u@h'))
            self.assertFalse(any(l.startswith('NICK ') for l in self._raw(self._drain())))

    def testTimedAttemptsGiveUpButHolderLeavingStillCounts(self):
        with self._wanting(), NICK_PLUGIN.nickRecoverTries.context(2):
            self._connect()
            cb = self._cb()
            cb._timedRecover('test')
            self.assertEqual(self._raw(self._drain()).count('NICK Wanted'), 1)
            cb._timedRecover('test')
            self.assertEqual(self._raw(self._drain()), [])
            self.assertTrue(cb._recovery['test']['gaveUp'])
            self.assertFalse('Perform.recover.test' in cb._events)
            self.assertRegexp('perform nickrecover status', 'gave up')
            self.irc.feedMsg(ircmsgs.quit('bye', prefix='Wanted!u@h'))
            self.assertEqual(self._raw(self._drain()).count('NICK Wanted'), 1)
            # "execute" restarts the timed attempts
            self.irc.feedMsg(ircmsgs.privmsg(self.irc.nick, 'perform nickrecover execute', prefix=self.prefix))
            out = self._raw(self._drain())
            self.assertEqual(out.count('NICK Wanted'), 1, out)
            self.assertTrue(any('Trying to get Wanted back' in l for l in out), out)
            self.assertEqual(cb._recovery['test']['tries'], 1)
        self._cb()._unschedule('Perform.recover.test')

    def testUnlimitedTries(self):
        with self._wanting(), NICK_PLUGIN.nickRecoverTries.context(0):
            self._connect()
            cb = self._cb()
            for _ in range(20):
                cb._timedRecover('test')
            self.assertEqual(self._raw(self._drain()).count('NICK Wanted'), 20)
        self._cb()._unschedule('Perform.recover.test')

    def testRecoveryCanBeDisabled(self):
        with self._wanting(), NICK_PLUGIN.nickRecoverEnabled.context(False):
            out = self._connect()
            self.assertFalse(any(l.startswith('NICK ') for l in out), out)
            self.irc.feedMsg(ircmsgs.quit('bye', prefix='Wanted!u@h'))
            self.assertEqual(self._raw(self._drain()), [])

    def testNetworkNickWins(self):
        with self._wanting('Global'), conf.supybot.networks.test.nick.context('PerNet'):
            out = self._connect()
            self.assertTrue('NICK PerNet' in out, out)
        self._cb()._unschedule('Perform.recover.test')

    def testNickrecoverListDelDelall(self):
        self.assertNotError('perform nickrecover add PRIVMSG NickServ :GHOST %nick% x')
        self.assertNotError('perform nickrecover add PRIVMSG NickServ :RELEASE %nick% x')
        self.assertRegexp('perform nickrecover del 1', 'Removed #1')
        self.assertEqual(self._cb().store.lines('test', 'nickrecover'), ['PRIVMSG NickServ :RELEASE %nick% x'])
        self.assertRegexp('perform nickrecover delall', 'Removed 1 line')
        self.assertRegexp('perform nickrecover list', 'empty')
        # the two lists are independent
        self.assertNotError('perform add MODE %nick% +B')
        self.assertEqual(self._cb().store.lines('test', 'nickrecover'), [])

    def testGroupWorksWithoutThePluginName(self):
        self.assertRegexp('nickrecover add PRIVMSG NickServ :GHOST %nick% x', 'Added as #1')
        self.assertRegexp('nickrecover list', 'GHOST')
        self.assertRegexp('nickrecover status', 'has its nick')
        self.assertRegexp('nickrecover delall', 'Removed 1 line')

    def testOwnerOnly(self):
        self.assertError('perform add MODE x +B', frm='stranger!u@__no_testcap__.example')
        self.assertEqual(self._cb().store.lines('test'), [])


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
