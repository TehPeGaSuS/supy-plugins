# Copyright (c) 2021, Valentin Lorentz
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

from supybot import conf, registry

try:
    from supybot.i18n import PluginInternationalization

    _ = PluginInternationalization("NickTracker")
except ImportError:
    _ = lambda x: x


def configure(advanced):
    conf.registerPlugin("NickTracker", True)


NickTracker = conf.registerPlugin("NickTracker")

conf.registerChannelValue(
    NickTracker,
    "enabled",
    registry.Boolean(
        False,
        _("""Track and announce nicks on this channel."""),
    ),
)

conf.registerChannelValue(
    NickTracker,
    "targets",
    registry.SpaceSeparatedSetOfStrings(
        set(),
        _(
            """
            Channels and/or nicks to announce joins to. People talking in one
            of these channels may also use the search commands for this
            channel.
            """
        ),
    ),
    opSettable=False,
)

conf.registerChannelValue(
    NickTracker,
    "defaultPattern",
    registry.String(
        "*@$host",
        _(
            """
            How a user is keyed in the database. Variables: $nick, $user,
            $host. The default ignores the ident, so one person keeps a
            single history even if the ident changes.
            """
        ),
    ),
)

conf.registerChannelValue(
    NickTracker,
    "specialPatterns",
    registry.SpaceSeparatedListOfStrings(
        ["*!uid*@*:$user@$host", "*!sid*@*:$user@$host"],
        _(
            """
            List of mask:pattern pairs. When nick!user@host matches the
            mask, that pattern is used instead of defaultPattern. The mask is
            an IRC-style glob, or a regex when prefixed with 're:' (handy for
            cloaked hosts, e.g. re:^[^!]+![us]id[0-9]+@:$user@$host). The
            default keeps the ident for IRCCloud users, whose uidNNN/sidNNN
            ident identifies the account. A bad regex is logged and skipped.
            """
        ),
    ),
)

conf.registerChannelValue(
    NickTracker,
    "ignoreHosts",
    registry.SpaceSeparatedListOfStrings(
        [],
        _(
            """
            user@host globs that are never recorded or announced, e.g.
            network staff: *@support.network.tld
            """
        ),
    ),
)

conf.registerGroup(NickTracker, "announce")

conf.registerChannelValue(
    NickTracker.announce,
    "text",
    registry.String(
        "also used",
        _("""Text between the nick and the list, e.g. 'also used'."""),
    ),
)

conf.registerChannelValue(
    NickTracker.announce,
    "others",
    registry.String(
        "other(s)",
        _("""Word used in the '(+N other(s))' suffix when the list is cut."""),
    ),
)

conf.registerChannelValue(
    NickTracker.announce,
    "color",
    registry.Boolean(
        True,
        _(
            """
            Colour the announcement (blue channel, red nicks). Never used on
            a target channel that has mode +c.
            """
        ),
    ),
)

conf.registerGroup(NickTracker.announce, "nicks")

conf.registerChannelValue(
    NickTracker.announce.nicks,
    "perLine",
    registry.PositiveInteger(
        10,
        _("""Nicks per announcement line."""),
    ),
)

conf.registerChannelValue(
    NickTracker.announce.nicks,
    "lines",
    registry.NonNegativeInteger(
        3,
        _("""Maximum announcement lines per join; 0 means no limit."""),
    ),
)

conf.registerChannelValue(
    NickTracker.announce.nicks,
    "separator",
    registry.String(
        ", ",
        _("""Separator between nicks."""),
    ),
)

conf.registerChannelValue(
    NickTracker,
    "searchResults",
    registry.PositiveInteger(
        10,
        _("""Maximum results shown by the search commands."""),
    ),
)

# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
