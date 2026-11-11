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


from supybot.test import *
from supybot import callbacks, conf, ircdb, ircmsgs

PLEB = 'pleb!p@__no_testcap__.pleb'
OPPER = 'opper!o@__no_testcap__.opper'
BOSS = 'boss!b@__no_testcap__.boss'
ADMIN = 'adm!a@__no_testcap__.adm'


class ChanOnlyTestCase(ChannelPluginTestCase):
    plugins = ('ChanOnly', 'Utilities', 'Misc', 'Channel', 'Config')

    def setUp(self):
        super().setUp()
        for name, mask, cap in (('opper', OPPER, '#test,op'),
                                ('boss', BOSS, 'owner'),
                                ('adm', ADMIN, 'admin')):
            u = ircdb.users.newUser()
            u.name = name
            u.addHostmask(mask)
            u.addCapability(cap)
            ircdb.users.setUser(u)
        self.setAllowed('')
        self.setEnabled(False)
        self.assertNotError('config channel #test plugins.ChanOnly.exempt op')
        self.assertNotError('config plugins.ChanOnly.exemptGlobal admin')
        self.assertNotError('config channel #test plugins.ChanOnly.notify on')

    def tearDown(self):
        self.setAllowed('')
        self.setEnabled(False)
        super().tearDown()

    def setEnabled(self, on):
        self.assertNotError('config channel #test plugins.ChanOnly.enabled '
                            + ('on' if on else 'off'))

    def setAllowed(self, value):
        self.assertNotError('config channel #test plugins.ChanOnly.allowed '
                            '"%s"' % value)
        if value:
            self.setEnabled(True)

    def say(self, text, prefix=PLEB, target=None):
        self.irc.feedMsg(ircmsgs.privmsg(target or self.channel, text,
                                         prefix=prefix))
        m = self.irc.takeMsg()
        return m.args[1] if m else None

    def testOffByDefault(self):
        self.assertEqual(self.say('@echo hi'), 'hi')
        self.assertEqual(self.say('@ping'), 'pong')

    def testAllowedListAloneDoesNothing(self):
        self.assertNotError('config channel #test plugins.ChanOnly.allowed '
                            'Utilities')
        self.assertEqual(self.say('@ping'), 'pong')

    def testBlockEverything(self):
        self.setEnabled(True)
        self.assertIn('Commands are disabled in #test', self.say('@echo hi'))
        self.assertIn('Commands are disabled in #test', self.say('@ping'))
        self.assertIn('Commands are disabled in #test',
                      self.say('@config plugins.ChanOnly.enabled'))
        self.assertEqual(self.say('@ping', prefix=ADMIN), 'pong')
        self.assertEqual(self.say('@ping', prefix=OPPER), 'pong')
        self.assertEqual(self.say('@ping', prefix=BOSS), 'pong')

    def testAdminExempt(self):
        self.setAllowed('Utilities')
        self.assertEqual(self.say('@ping', prefix=ADMIN), 'pong')
        self.assertNotError('config plugins.ChanOnly.exemptGlobal ""')
        self.assertIn('Only commands from', self.say('@ping', prefix=ADMIN))
        self.assertEqual(self.say('@ping', prefix=BOSS), 'pong')

    def testOnlyAllowedPlugin(self):
        self.setAllowed('Utilities')
        self.assertEqual(self.say('@echo hi'), 'hi')
        self.assertIn('Only commands from Utilities work in #test',
                      self.say('@ping'))
        self.assertIn('Only commands from', self.say('@misc ping'))

    def testCaseInsensitive(self):
        self.setAllowed('utilities')
        self.assertEqual(self.say('@echo hi'), 'hi')

    def testSeveralPlugins(self):
        self.setAllowed('Utilities Misc')
        self.assertEqual(self.say('@echo hi'), 'hi')
        self.assertEqual(self.say('@ping'), 'pong')

    def testNestedBlocked(self):
        self.setAllowed('Utilities')
        reply = self.say('@echo [ping]')
        self.assertNotEqual(reply, 'pong')
        self.assertIn('Only commands from', reply)

    def testNestedCommandClass(self):
        # "channel capability list" lives in a nested Commands class.
        self.setAllowed('Channel')
        self.assertNotIn('Only commands from',
                         self.say('@channel capability list') or '')
        self.setAllowed('Utilities')
        self.assertIn('Only commands from',
                      self.say('@channel capability list'))

    def testSilent(self):
        self.setAllowed('Utilities')
        self.assertNotError('config channel #test plugins.ChanOnly.notify off')
        self.assertIsNone(self.say('@ping'))
        self.assertEqual(self.say('@echo hi'), 'hi')

    def testOpExempt(self):
        self.setAllowed('Utilities')
        self.assertEqual(self.say('@ping', prefix=OPPER), 'pong')

    def testDefaultAllowDoesNotExemptEveryone(self):
        # The channel's defaultAllow is True, which would hand #test,op to
        # unknown users if the exemption check didn't ignore it.
        self.assertTrue(ircdb.channels.getChannel('#test').defaultAllow)
        self.setAllowed('Utilities')
        self.assertIn('Only commands from', self.say('@ping'))

    def testNoExemption(self):
        self.setAllowed('Utilities')
        self.assertNotError('config channel #test plugins.ChanOnly.exempt ""')
        self.assertNotError('config plugins.ChanOnly.exemptGlobal ""')
        self.assertIn('Only commands from', self.say('@ping', prefix=OPPER))
        self.assertIn('Only commands from', self.say('@ping', prefix=ADMIN))
        self.assertEqual(self.say('@ping', prefix=BOSS), 'pong')

    def testOtherChannelUntouched(self):
        self.setAllowed('Utilities')
        self.assertEqual(self.say('@ping', target='#other'), 'pong')

    def testPrivateUntouched(self):
        self.setAllowed('Utilities')
        self.assertEqual(self.say('ping', target=self.nick), 'pong')

    def testUnloadRemovesHook(self):
        hooks = callbacks.Commands.pre_command_callbacks
        self.assertEqual(len(hooks), 1)
        self.assertNotError('unload ChanOnly')
        self.assertEqual(hooks, [])


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
