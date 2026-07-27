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

from supybot import conf, registry

from . import data
try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('DuckHuntPro')
except ImportError:
    _ = lambda x: x


def configure(advanced):
    conf.registerPlugin('DuckHuntPro', True)


DuckHuntPro = conf.registerPlugin('DuckHuntPro')

conf.registerChannelValue(DuckHuntPro, 'enabled',
    registry.Boolean(False, """Enables the duck hunt game in this channel."""))

conf.registerChannelValue(DuckHuntPro, 'language',
    registry.String('en', """Language used for this channel's game messages.
    Only 'en' ships by default; add more languages by extending messages.py."""))

conf.registerChannelValue(DuckHuntPro, 'ducksPerDay',
    registry.PositiveInteger(18, """Approximate number of ducks that fly per day."""))

conf.registerChannelValue(DuckHuntPro, 'approxGoldenDucksPerDay',
    registry.NonNegativeInteger(1, """Approximate number of golden (multi-hit) ducks
    per day; must not exceed ducksPerDay, since golden ducks are counted within it."""))

conf.registerChannelValue(DuckHuntPro, 'goldenDuckMinHP',
    registry.PositiveInteger(3, """Minimum hit points of a golden duck."""))

conf.registerChannelValue(DuckHuntPro, 'goldenDuckMaxHP',
    registry.PositiveInteger(5, """Maximum hit points of a golden duck."""))

conf.registerChannelValue(DuckHuntPro, 'duckSleepHours',
    registry.String('', """Space-separated list of hours (0-23) during which no duck
    will fly, e.g. "2 3 4 5". Empty means ducks can fly at any hour."""))

conf.registerChannelValue(DuckHuntPro, 'shotsBeforeDuckFlee',
    registry.Integer(3, """Number of non-lethal shots fired at a duck before it flees
    scared off. -1 means it never flees from gunfire (only from escapeTime)."""))

conf.registerChannelValue(DuckHuntPro, 'successfulShotsAlsoScareDucks',
    registry.Boolean(True, """Whether a kill on one duck also counts toward scaring
    off other ducks currently in flight on the same channel."""))

conf.registerChannelValue(DuckHuntPro, 'escapeTime',
    registry.PositiveInteger(300, """Seconds a duck stays in flight before escaping
    unharmed if nobody kills it."""))

conf.registerChannelValue(DuckHuntPro, 'unlimitedAmmoPerClip',
    registry.Boolean(False, """Whether clips have unlimited ammo (no reload needed)."""))

conf.registerChannelValue(DuckHuntPro, 'unlimitedAmmoClips',
    registry.Boolean(False, """Whether players have an unlimited number of clips."""))

conf.registerChannelValue(DuckHuntPro, 'antiHighlight',
    registry.Boolean(False, """Randomizes the duck's flight art each time so
    highlight-triggered auto-shoot scripts can't be trained on a fixed string."""))

conf.registerChannelValue(DuckHuntPro, 'voiceWhenDuckShot',
    registry.Boolean(True, """Voices a player in the channel when they shoot down a duck."""))

conf.registerChannelValue(DuckHuntPro, 'devoiceOnWildFire',
    registry.Boolean(True, """Devoices a player who fires with no duck in sight."""))

conf.registerChannelValue(DuckHuntPro, 'devoiceOnMiss',
    registry.Boolean(False, """Devoices a player who misses a shot at a duck."""))

conf.registerGlobalValue(DuckHuntPro, 'postInitDelay',
    registry.PositiveInteger(60, """Seconds to wait after the plugin loads before
    planning the day's duck flights, to give the bot time to join all its channels."""))

conf.registerGlobalValue(DuckHuntPro, 'quarterlyResetEnabled',
    registry.Boolean(True, """Whether to automatically archive and reset every
    channel's standings on the 1st of January/April/July/October."""))

conf.registerChannelValue(DuckHuntPro, 'topShootersCount',
    registry.PositiveInteger(3, """How many players `duckshooters` shows,
    ranked by xp (kills as tiebreaker)."""))

conf.registerGroup(DuckHuntPro, 'web')

conf.registerGlobalValue(DuckHuntPro.web, 'enable',
    registry.Boolean(False, """Enables the built-in web dashboard (leaderboard/
    champions/shop pages) served through Limnoria's HTTP server, at
    /duckhuntpro/<network>/<channel>/<page>."""))

conf.registerChannelValue(DuckHuntPro, 'minXpForShopping',
    registry.Integer(0, """The lowest a player's xp balance is allowed to go
    after a shop purchase; a purchase that would drop them below this floor
    is refused."""))

conf.registerChannelValue(DuckHuntPro, 'dropsEnabled',
    registry.Boolean(True, """Whether killing a duck can also drop a bonus
    item/xp-book on top of the normal xp reward."""))

conf.registerChannelValue(DuckHuntPro, 'maxBreadOnChan',
    registry.PositiveInteger(data.MAX_BREAD_ON_CHAN, """Maximum number of
    active bread pieces on a channel at once; further bread purchases are
    refused (and not charged) once this cap is hit."""))

conf.registerChannelValue(DuckHuntPro, 'kickWhenSabotaged',
    registry.Boolean(True, """Whether a sabotaged weapon jamming also kicks
    the victim from the channel, matching the original script."""))

conf.registerChannelValue(DuckHuntPro, 'cantAttractDucksWhenSleeping',
    registry.Boolean(True, """Whether decoy/bread purchases are refused
    during this channel's duckSleepHours."""))

conf.registerChannelValue(DuckHuntPro, 'decoysCanAttractGoldenDucks',
    registry.Boolean(True, """Whether a duck lured in by the decoy item can
    randomly turn out to be a golden duck (if false, decoy ducks are always
    ordinary)."""))

conf.registerChannelValue(DuckHuntPro, 'onlyHuntersCanBeShot',
    registry.Boolean(True, """Whether accidental-hit victims must already have
    fired at least one shot in this channel (if false, any channel occupant
    can be hit, even someone who's never played)."""))

conf.registerChannelValue(DuckHuntPro, 'gunConfiscationWhenShootingSomeone',
    registry.Boolean(True, """Whether accidentally hitting another player
    gets your own weapon temporarily confiscated."""))

conf.registerChannelValue(DuckHuntPro, 'gunConfiscationOnWildFire',
    registry.Boolean(False, """Whether firing with no duck present (and
    hitting nobody) also risks a temporary confiscation."""))

conf.registerChannelValue(DuckHuntPro, 'devoiceOnAccident',
    registry.Boolean(True, """Devoices a player who accidentally hits
    someone else."""))

conf.registerChannelValue(DuckHuntPro, 'kickWhenShot',
    registry.Boolean(True, """Whether a player who takes a stray hit (and
    neither deflects nor is defended by armor) gets kicked."""))

conf.registerChannelValue(DuckHuntPro, 'gunHandBackMode',
    registry.Integer(1, """How temporarily-confiscated weapons get returned:
    1 = once daily at autoGunHandBackTime, 2 = whenever the channel's duck
    count drops back to zero (killed/escaped), 3 = never automatically (only
    the `rearm` command). Permanently-confiscated weapons (`unarm --static`)
    are never auto-returned by any mode."""))

conf.registerChannelValue(DuckHuntPro, 'autoGunHandBackTime',
    registry.String('00:00', """Local time (HH:MM) weapons are auto-returned
    each day, when gunHandBackMode is 1."""))

conf.registerChannelValue(DuckHuntPro, 'confiscationEnforcementOnFusion',
    registry.Boolean(False, """When a renamed player's stats would be merged
    into their new nick (see nick-change stat fusion), whether a disarmed
    profile should have its stats discarded instead of merged (an
    anti-confiscation-dodging measure). Off by default, matching the
    original script."""))

conf.registerChannelValue(DuckHuntPro, 'antifloodEnabled',
    registry.Boolean(True, """Whether to rate-limit rapid repeated use of
    game commands per player."""))

conf.registerChannelValue(DuckHuntPro, 'antifloodMaxPerMinute',
    registry.PositiveInteger(10, """Maximum uses of any single DuckHuntPro
    command a player gets per rolling 60-second window before further uses
    are silently dropped (with an occasional warning)."""))

# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
