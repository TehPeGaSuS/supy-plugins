# Copyright (c) 2026, PeGaSuS
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

###

import json
import os
import sqlite3
import time

from supybot.test import *
import supybot.ircdb as ircdb
import supybot.ircmsgs as ircmsgs
import supybot.ircutils as ircutils

from . import plugin as nt_plugin

BLUE = ircutils.mircColor("%s", "blue")
RED = ircutils.mircColor("%s", "red")


def coloured(chan, nick, nicks):
    return "[%s] %s also used: %s" % (BLUE % chan, RED % nick, RED % nicks)


class NickTrackerTestCase(ChannelPluginTestCase):
    plugins = ("NickTracker",)

    def setUp(self):
        super().setUp()
        self.cb = self.irc.getCallback("NickTracker")
        self.cb.db.clear()
        self.plugin_conf = conf.supybot.plugins.NickTracker
        self.plugin_conf.enabled.get(self.channel).setValue(True)
        self.plugin_conf.targets.get(self.channel).setValue({"#back"})
        # register the test user as admin so the search commands are reachable
        u = ircdb.users.newUser()
        u.name = "tester"
        u.addHostmask(self.prefix)
        u.addCapability("admin")
        ircdb.users.setUser(u)

    def tearDown(self):
        try:
            ircdb.users.delUser(ircdb.users.getUserId("tester"))
        except KeyError:
            pass
        super().tearDown()

    def join(self, nick, userhost, channel=None):
        self.irc.feedMsg(
            ircmsgs.join(channel or self.channel, prefix="%s!%s" % (nick, userhost))
        )

    def taken(self):
        out = []
        m = self.irc.takeMsg()
        while m is not None:
            if m.command == "PRIVMSG":
                out.append((m.args[0], m.args[1]))
            m = self.irc.takeMsg()
        return out

    def assertAnnounced(self, nick, nicks, channel=None):
        self.assertEqual(
            self.taken(), [("#back", coloured(channel or self.channel, nick, nicks))]
        )

    # ------------------------------------------------------------- tracking

    def testFirstJoinSilent(self):
        self.join("Alice", "~al@Host.Example.com")
        self.assertEqual(self.taken(), [])
        self.assertEqual(
            self.cb.db.nicks_for_host(self.irc.network, self.channel, "*@host.example.com"),
            ["Alice"],
        )

    def testAnnounceNewestFirst(self):
        self.join("Alice", "a@host.example.com")
        self.join("Bob", "b@host.example.com")
        self.assertAnnounced("Bob", "Alice")
        self.join("Carol", "c@host.example.com")
        self.assertAnnounced("Carol", "Bob, Alice")

    def testCaseVariantNotStoredButRefreshed(self):
        self.join("Alice", "a@h")
        self.join("Bob", "b@h")
        self.taken()
        self.join("ALICE", "a@h")
        self.assertAnnounced("ALICE", "Bob")
        self.assertEqual(
            self.cb.db.nicks_for_host(self.irc.network, self.channel, "*@h"),
            ["Bob", "Alice"],
        )

    def testIrcCloudKeepsIdent(self):
        self.join("I1", "uid123@id-1.irccloud.com")
        self.join("I2", "uid999@id-1.irccloud.com")
        self.assertEqual(self.taken(), [])
        self.join("I3", "~uid123@id-1.irccloud.com")
        self.assertAnnounced("I3", "I1")

    def testNickChange(self):
        self.join("Alice", "a@h")
        self.irc.feedMsg(ircmsgs.nick("Alicia", prefix="Alice!a@h"))
        self.assertAnnounced("Alicia", "Alice")

    def testBotIgnored(self):
        self.join(self.irc.nick, "bot@h")
        self.assertEqual(
            self.cb.db.nicks_for_host(self.irc.network, self.channel, "*@h"), []
        )

    def testDisabledChannel(self):
        self.plugin_conf.enabled.get(self.channel).setValue(False)
        try:
            self.join("Alice", "a@h")
            self.join("Bob", "b@h")
            self.assertEqual(self.taken(), [])
        finally:
            self.plugin_conf.enabled.get(self.channel).setValue(True)

    def testIgnoreHosts(self):
        self.plugin_conf.ignoreHosts.get(self.channel).setValue(
            ["*@support.network.tld", "*@*.Staff.net"]
        )
        try:
            self.join("S1", "~oper@support.network.tld")
            self.join("S2", "x@Support.Network.TLD")
            self.join("S3", "x@a.staff.net")
            self.assertEqual(self.taken(), [])
            self.assertEqual(
                self.cb.db.nicks_for_host(
                    self.irc.network, self.channel, "*@support.network.tld"
                ),
                [],
            )
        finally:
            self.plugin_conf.ignoreHosts.get(self.channel).setValue([])

    def testSpecialPatternRegex(self):
        self.plugin_conf.specialPatterns.get(self.channel).setValue(
            ["re:^[^!]+![us]id[0-9]+@:$user@$host", "re:(bad:$user@$host"]
        )
        try:
            self.join("R1", "uid123@cloud.irccloud.com")
            self.join("R2", "~uid123@cloud.irccloud.com")
            self.join("R3", "uidx@cloud.irccloud.com")
            self.taken()
            db = self.cb.db
            self.assertEqual(
                db.nicks_for_host(self.irc.network, self.channel,
                                  "uid123@cloud.irccloud.com"),
                ["R2", "R1"],
            )
            self.assertEqual(
                db.nicks_for_host(self.irc.network, self.channel,
                                  "*@cloud.irccloud.com"),
                ["R3"],
            )
        finally:
            self.plugin_conf.specialPatterns.get(self.channel).setValue(
                self.plugin_conf.specialPatterns._default
            )

    def testTruncationAndSuffix(self):
        self.plugin_conf.announce.nicks.perLine.get(self.channel).setValue(2)
        self.plugin_conf.announce.nicks.lines.get(self.channel).setValue(2)
        try:
            for n in "ABCDEF":
                self.join(n, "x@h")
            self.taken()
            self.join("G", "x@h")
            self.assertEqual(
                self.taken(),
                [
                    ("#back", coloured(self.channel, "G", "F, E")),
                    ("#back", coloured(self.channel, "G", "D, C (+2 other(s))")),
                ],
            )
        finally:
            self.plugin_conf.announce.nicks.perLine.get(self.channel).setValue(10)
            self.plugin_conf.announce.nicks.lines.get(self.channel).setValue(3)

    def testNoColourOnPlusC(self):
        self.irc.feedMsg(ircmsgs.join("#back", prefix=self.irc.prefix))
        self.irc.feedMsg(ircmsgs.mode("#back", "+c"))
        self.taken()
        self.join("Alice", "a@h")
        self.join("Bob", "b@h")
        self.assertEqual(
            self.taken(), [("#back", "[%s] Bob also used: Alice" % self.channel)]
        )

    def testColourOff(self):
        self.plugin_conf.announce.color.get(self.channel).setValue(False)
        try:
            self.join("Alice", "a@h")
            self.join("Bob", "b@h")
            self.assertEqual(
                self.taken(), [("#back", "[%s] Bob also used: Alice" % self.channel)]
            )
        finally:
            self.plugin_conf.announce.color.get(self.channel).setValue(True)

    def testMultipleTargets(self):
        self.plugin_conf.targets.get(self.channel).setValue({"#back", "Oper"})
        try:
            self.join("Alice", "a@h")
            self.join("Bob", "b@h")
            self.assertEqual(
                sorted(self.taken()),
                sorted(
                    [
                        ("#back", coloured(self.channel, "Bob", "Alice")),
                        ("Oper", coloured(self.channel, "Bob", "Alice")),
                    ]
                ),
            )
        finally:
            self.plugin_conf.targets.get(self.channel).setValue({"#back"})

    # ------------------------------------------------------------- searches

    def seed(self):
        self.join("Alice", "a@host.example.com")
        self.join("Bob", "b@host.example.com")
        self.join("Carol", "c@host.example.com")
        self.join("U1", "x@under_score.net")
        self.join("U2", "x@underXscore.net")
        self.join("Br", "x@br.host")
        self.join("[x]", "x@br.host")
        self.taken()

    def testSearchNick(self):
        self.seed()
        self.assertResponse(
            "searchnick %s alice" % self.channel,
            "Last 2/2 nick(s) also used by alice: Bob, Carol",
        )
        self.assertResponse(
            "searchnick nobody", "No data for nick nobody in %s." % self.channel
        )

    def testSearchHost(self):
        self.seed()
        self.assertResponse(
            "searchhost Alice", "Last 1/1 host(s) for Alice: *@host.example.com"
        )

    def testSearchMask(self):
        self.seed()
        self.assertResponse(
            "searchmask under_score", "Last 1/1 nick(s) for mask under_score: U1"
        )
        self.assertResponse(
            "searchmask *!~foo@under*.net",
            "Last 2/2 nick(s) for mask *!~foo@under*.net: U1, U2",
        )
        self.assertResponse(
            "searchmask 100%", "No nicks for mask 100%% in %s." % self.channel
        )
        self.assertResponse("searchmask br.host", "Last 2/2 nick(s) for mask br.host: Br, [x]")

    def testSearchResultsCap(self):
        for i in range(15):
            self.join("Long", "x@h%d.example.org" % i)
        self.taken()
        m = self.getMsg("searchhost Long")
        self.assertIn("Last 10/15 host(s) for Long: *@h5.example.org", m.args[1])

    def testSearchFromTargetWithoutCapability(self):
        self.seed()
        # unregistered user asking in #back (a target of self.channel)
        m = self.getMsg("searchhost Alice", to="#back", frm="guest!g@__no_testcap__.h")
        self.assertIn("*@host.example.com", m.args[1])
        # same user from an unrelated channel is refused
        m = self.getMsg("searchhost Alice", to="#elsewhere", frm="guest!g@__no_testcap__.h")
        self.assertIn("Error", m.args[1])

    def testStale(self):
        self.seed()
        ago = int(time.time()) - 100 * 86400
        with self.cb.db.lock:
            self.cb.db.conn.execute(
                "UPDATE nicktrack SET last_seen = ? WHERE host = '*@br.host'", (ago,)
            )
            self.cb.db.conn.commit()
        self.assertResponse(
            "stale %s 90" % self.channel,
            "1 host(s) / 2 nick(s) unseen for 90+ days in %s. Oldest: "
            "*@br.host (%s, 2 nick(s), 100d)" % (self.channel, self.channel),
        )
        self.assertResponse("stale 365", "No hosts unseen for 365+ days in %s." % self.channel)

    # -------------------------------------------------------------- imports

    def testImportEggdropTxt(self):
        path = os.path.join(conf.supybot.directories.data(), "chan_nicklist.txt")
        with open(path, "w") as f:
            f.write("Newest,Middle,Oldest<~joe@old.host.net\r\nSolo<uid9@id-9.irccloud.com\n")
        self.assertResponse(
            "importdata %s" % path, "Imported chan_nicklist.txt: 4 inserted, 0 already present."
        )
        self.assertEqual(
            self.cb.db.nicks_for_host(self.irc.network, "#chan", "joe@old.host.net"),
            ["Newest", "Middle", "Oldest"],
        )

    def testImportTclSqlite(self):
        path = os.path.join(conf.supybot.directories.data(), "tcl.db")
        if os.path.exists(path):
            os.remove(path)
        src = sqlite3.connect(path)
        src.executescript(
            "CREATE TABLE nicktrack (chan TEXT, host TEXT, nick TEXT, last_seen INTEGER,"
            " PRIMARY KEY (chan, host, nick));"
            "INSERT INTO nicktrack VALUES ('#Amicizia','*@v.host','One',1000);"
            "INSERT INTO nicktrack VALUES ('#amicizia','*@v.host','Two',2000);"
        )
        src.commit()
        src.close()
        self.assertResponse(
            "importdata %s" % path, "Imported tcl.db: 2 inserted, 0 already present."
        )
        self.assertResponse(
            "importdata %s" % path, "Imported tcl.db: 0 inserted, 2 already present."
        )
        self.join("Three", "x@v.host", "#amicizia")
        self.assertEqual(self.taken(), [])  # #amicizia is not enabled
        self.plugin_conf.enabled.get("#amicizia").setValue(True)
        self.plugin_conf.targets.get("#amicizia").setValue({"#back"})
        try:
            self.join("Three", "x@v.host", "#amicizia")
            self.assertAnnounced("Three", "Two, One", "#amicizia")
        finally:
            self.plugin_conf.enabled.get("#amicizia").setValue(False)

    def testImportJson(self):
        path = os.path.join(conf.supybot.directories.data(), "old.json")
        with open(path, "w") as f:
            json.dump(
                {self.irc.network: {self.channel: {"*!~al@Host.net": ["Alice", "Al"]}}}, f
            )
        self.assertResponse(
            "importdata %s" % path, "Imported old.json: 2 inserted, 0 already present."
        )
        self.join("Bob", "b@host.net")
        self.assertAnnounced("Bob", "Al, Alice")


class LikePatternTestCase(SupyTestCase):
    def testPatterns(self):
        like = nt_plugin._like_pattern
        self.assertEqual(like("under_score"), "%under\\_score%")
        self.assertEqual(like("*!~foo@Under*.net"), "~foo@under%.net")
        self.assertEqual(like("100%"), "%100\\%%")
        self.assertEqual(like("a?b"), "a_b")


# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
