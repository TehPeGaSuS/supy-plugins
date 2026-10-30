###
# Copyright (c) 2026, TehPeGaSuS
# All rights reserved. See plugin.py for the licence.
###

from supybot.test import *
from supybot import conf, ircdb

ALICE = 'alice!a@__no_testcap__.example'


class SlapperTestCase(ChannelPluginTestCase):
    plugins = ('Slapper',)

    def setUp(self):
        super().setUp()
        cb = self.irc.getCallback('Slapper')
        cb.store.data = {'phrases': ['slaps $nick'], 'vars': {}}
        self.irc.state.channels[self.channel].addUser('alice')
        self.irc.state.channels[self.channel].addUser('bob')

    def _store(self):
        return self.irc.getCallback('Slapper').store

    def testSlapSomeone(self):
        self.assertAction('slap bob', 'slaps bob')

    def testSlapNobodySlapsTheCaller(self):
        self.assertAction('slap', 'slaps alice', frm=ALICE)

    def testSlapTheBotSlapsBack(self):
        self.assertAction('slap %s' % self.irc.nick, 'slaps alice', frm=ALICE)
        self.assertAction('slap %s' % self.irc.nick.upper(), 'slaps alice', frm=ALICE)

    def testSlapAnythingGoes(self):
        self.assertAction('slap the moon', 'slaps the moon')

    def testBuiltinVariables(self):
        self._store().data['phrases'] = ['$who slaps $nick in $channel while $botnick watches']
        self.assertAction('slap bob', 'alice slaps bob in %s while %s watches'
                          % (self.channel, self.irc.nick), frm=ALICE)

    def testRandnickNeverPicksTheBot(self):
        self._store().data['phrases'] = ['slaps $nick and $randnick']
        for _ in range(15):
            m = self.assertAction('slap bob')
            self.assertNotEqual(ircmsgs.unAction(m).split()[-1], self.irc.nick)

    def testCustomVariablesAndNesting(self):
        self.assertNotError('slaps var add fish a $size trout')
        self.assertNotError('slaps var add $size large')
        self.assertNotError('slaps add slaps $nick with $fish, $UNKNOWN stays')
        self.assertNotError('slaps del 1')
        self.assertAction('slap bob', 'slaps bob with a large trout, $UNKNOWN stays')

    def testPhraseNeedsNick(self):
        self.assertError('slaps add slaps everyone')
        self.assertEqual(self._store().phrases(), ['slaps $nick'])

    def testListAndDelete(self):
        self.assertNotError('slaps add hugs $nick')
        self.assertRegexp('slaps list', '#1: slaps \\$nick \\| #2: hugs \\$nick')
        self.assertRegexp('slaps del 2', 'Removed #2: hugs')
        self.assertError('slaps delete 7')

    def testNoPhrases(self):
        self.assertNotError('slaps del 1')
        self.assertRegexp('slap bob', 'no slap phrases')

    def testVarManagement(self):
        self.assertError('slaps var add nick bob')
        self.assertError('slaps var add 9lives x')
        self.assertNotError('slaps var add fish trout')
        self.assertNotError('slaps var add fish cod')
        self.assertRegexp('slaps var list', 'Yours: \\$fish \\(2\\)')
        self.assertRegexp('slaps var list fish', '#1: trout \\| #2: cod')
        self.assertRegexp('slaps var list nick', 'who gets slapped')
        self.assertRegexp('slaps var del fish 1', 'Removed "trout"')
        self.assertRegexp('slaps var del fish', 'Removed \\$fish \\(1 value')
        self.assertError('slaps var list fish')

    def testManagingNeedsTheCapability(self):
        self.assertRegexp('slaps add hits $nick', "Error: You don't have the admin", frm=ALICE)
        self.assertRegexp('slaps var add fish x', "Error: You don't have the admin", frm=ALICE)
        self.assertEqual(self._store().phrases(), ['slaps $nick'])
        user = ircdb.users.newUser()
        user.name = 'alice'
        user.addHostmask(ALICE)
        user.addCapability('admin')
        ircdb.users.setUser(user)
        self.assertNotError('slaps add hits $nick', frm=ALICE)
        # anyone can slap and list
        self.assertAction('slap bob', frm='carol!c@__no_testcap__.example')

    def testDisabledChannel(self):
        with conf.supybot.plugins.Slapper.enabled.context(False):
            self.assertNoResponse('slap bob')

    def testDefaultsOnFirstStart(self):
        from Slapper.plugin import Store, DEFAULT_PHRASES
        import tempfile, os
        s = Store(os.path.join(tempfile.mkdtemp(), 'x', 'slaps.json'))
        self.assertEqual(s.phrases(), DEFAULT_PHRASES)
        self.assertTrue(s.vars()['fish'])
        s.addPhrase('pokes $nick')
        self.assertEqual(Store(s.path).phrases()[-1], 'pokes $nick')


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
