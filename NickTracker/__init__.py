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

"""
NickTracker: remembers which nicks were seen from each host on a channel,
announces the other nicks a host has used when it joins, and lets ops search
the history. SQLite-backed.

Based on NickTracker by Valentin Lorentz (progval):
https://github.com/progval/Supybot-plugins/tree/master/NickTracker
"""

import supybot
from supybot import world

__version__ = "3.0.0"

__author__ = supybot.Author("Valentin Lorentz", "progval", "progval@progval.net")
__maintainer__ = supybot.Author("PeGaSuS", "PeGaSuS", "")

__contributors__ = {}

__url__ = "https://github.com/TehPeGaSuS/pegasus-supy-plugins"

from . import config
from . import plugin
from importlib import reload

reload(config)
reload(plugin)

if world.testing:
    from . import test

Class = plugin.Class
configure = config.configure

# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
