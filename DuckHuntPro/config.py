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

conf.registerChannelValue(DuckHuntPro, 'shopEnabled',
    registry.Boolean(True, """Whether the shop command is available at all
    (Duck_Hunt.tcl's shop_enabled; when off the command does nothing)."""))

conf.registerChannelValue(DuckHuntPro, 'shopPreferredDisplayMode',
    registry.Integer(0, """What `shop` without arguments shows: 0 = the
    catalogue of items and prices, anything else = a message pointing to
    shopUrl instead."""))

conf.registerChannelValue(DuckHuntPro, 'shopUrl',
    registry.String('', """The web page listing the shop items, shown when
    shopPreferredDisplayMode is non-zero."""))

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

conf.registerGlobalValue(DuckHuntPro, 'method',
    registry.Integer(2, """How duck flights are scheduled (the original's `method`):
    1 = every minute each channel has a chance of a flight (random timing),
    2 = the day's flight times are planned in advance, replanned at midnight
    and whenever bread is bought or expires."""))

conf.registerChannelValue(DuckHuntPro, 'showBreadReplanning',
    registry.Boolean(True, """Log the new flight plan each time buying or
    losing bread replans the day (the original's show_bread_replanning)."""))

conf.registerChannelValue(DuckHuntPro, 'preferredDisplayMode',
    registry.Integer(1, """Where the game's per-player replies go: 1 = PRIVMSG to
    the channel, anything else = NOTICE to the player (the original's
    preferred_display_mode). Duck flights, kills and accidents are always
    public."""))

conf.registerChannelValue(DuckHuntPro, 'monochrome',
    registry.Boolean(False, """Strip colours and other formatting from every
    message the game sends (it is always stripped on channels with mode +c)."""))

conf.registerChannelValue(DuckHuntPro, 'kickOnWildFire',
    registry.Boolean(False, """Kick players who shoot when there is no duck
    (the original's kick_on_wild_fire)."""))

conf.registerGlobalValue(DuckHuntPro, 'autoRefillAmmoTime',
    registry.String('00:00', """Local time (HH:MM) at which every player's
    clips are refilled to their level's count each day (the original script's
    auto_refill_ammo_time)."""))

conf.registerGlobalValue(DuckHuntPro, 'huntingLogs',
    registry.Boolean(False, """Whether to keep the original's hunting logs: a
    plain-text trace of everything that happens (flights, shots, reloads,
    purchases, confiscations, stat transfers), one file per channel and day
    (the original script's hunting_logs)."""))

conf.registerGlobalValue(DuckHuntPro, 'huntingLogDirectory',
    registry.String('', """Where the hunting logs go, as <channel>_<yyyymmdd>.log
    files. Empty means a logs directory under the plugin's data directory."""))

conf.registerGlobalValue(DuckHuntPro, 'backupTime',
    registry.String('00:03', """Local time (HH:MM) at which the database file is
    copied to a .bak file next to it each day (the original script's
    backup_time)."""))

conf.registerGlobalValue(DuckHuntPro, 'anonymPrefix',
    registry.String('', """The prefix your network gives to users who don't
    identify in time ("Anonyme" for nicks like Anonyme54720). Stats are never
    transferred automatically to such a nick. Case-sensitive; empty = off."""))

conf.registerGlobalValue(DuckHuntPro, 'warnOnRename',
    registry.Boolean(False, """Log a notice when a player who changed nick
    already has stats under the new nick."""))

conf.registerGlobalValue(DuckHuntPro, 'warnOnTakeover',
    registry.Boolean(True, """Log what happened (and the stats involved) when a
    nick change makes two profiles merge, one replace the other, or a profile
    get claimed."""))

conf.registerGlobalValue(DuckHuntPro, 'pendingTransfersMaxAge',
    registry.PositiveInteger(3600, """Seconds. When the plugin starts, nick-change
    transfers still waiting are forgotten if nothing about them changed for
    longer than this."""))

conf.registerChannelValue(DuckHuntPro, 'confiscationEnforcementOnFusion',
    registry.Boolean(False, """When a renamed player's stats would be merged
    into their new nick (see nick-change stat fusion), whether a disarmed
    profile should have its stats discarded instead of merged (an
    anti-confiscation-dodging measure). Off by default, matching the
    original script."""))

conf.registerChannelValue(DuckHuntPro, 'antifloodEnabled',
    registry.Boolean(True, """Whether to rate-limit the game commands (the
    original's antiflood)."""))

_FLOOD_HELP = """ as "<requests>:<seconds>": no more than that many uses of the
    command per player in that many seconds (a rolling window)."""

for _name, _default, _what in (
        ('floodShoot', '30:600', 'the shooting command'),
        ('floodReload', '15:120', 'duckreload'),
        ('floodStats', '2:120', 'duckstats'),
        ('floodLastduck', '1:300', 'lastduck'),
        ('floodShop', '3:600', 'shop')):
    conf.registerChannelValue(DuckHuntPro, _name,
        registry.String(_default, "Individual flood limit for %s%s" % (_what, _FLOOD_HELP)))

conf.registerChannelValue(DuckHuntPro, 'floodGlobal',
    registry.String('30:600', """Flood limit on all the game's commands
    together, for the whole channel ("<requests>:<seconds>"). The original
    suggests at least the largest individual limit."""))

conf.registerChannelValue(DuckHuntPro, 'antifloodMsgInterval',
    registry.PositiveInteger(60, """Minimum number of seconds between two
    flood-control warnings for the same limit (not too low, or the warnings
    become the flood)."""))


conf.registerNetworkValue(DuckHuntPro, 'kickViaChanServ',
    registry.Boolean(False, """Make the game's kicks through services instead of
    kicking directly (the original's kick_method 1), on this network. Needed
    when the bot has no op but is allowed to use services."""))

conf.registerNetworkValue(DuckHuntPro, 'chanServKickLine',
    registry.String('CS KICK {channel} {nick} :{reason}', """The raw IRC line
    kickViaChanServ sends on this network, with {channel}, {nick} and {reason}
    filled in. The default is the original's `CS kick` (the network needs a CS
    alias for ChanServ, as DALnet's has). Without an alias, for example:
    `PRIVMSG ChanServ :KICK {channel} {nick} {reason}`; on Undernet the
    service is X: `PRIVMSG X@channels.undernet.org :KICK {channel} {nick} {reason}`."""))

conf.registerGlobalValue(DuckHuntPro, 'strayBulletExemptCapability',
    registry.String('', """A capability (for example "duckhuntpro.exempt"):
    users who have it, or are bots that have it, can never take a stray
    bullet. The original's exempted_flags; leave empty to exempt only the
    bot itself."""))

# ---- The original's tunable numbers (Duck_Hunt.cfg) ------------------------

conf.registerGlobalValue(DuckHuntPro, 'xpPerDuck',
    registry.Integer(data.XP_PER_DUCK, """Experience points for killing a duck
    (xp_duck)."""))

conf.registerGlobalValue(DuckHuntPro, 'xpPerGoldenDuckHp',
    registry.Integer(data.BASE_XP_GOLDEN_DUCK, """Experience points for killing
    a golden duck, per hit point it had."""))

conf.registerGlobalValue(DuckHuntPro, 'xpLuckyShot',
    registry.Integer(data.XP_LUCKY_SHOT, """Bonus experience points for a
    "lucky" kill (a ricochet that hits the duck)."""))

conf.registerGlobalValue(DuckHuntPro, 'chanceRicochetTowardsDuck',
    registry.NonNegativeInteger(data.CHANCE_RICOCHET_TOWARDS_DUCK, """Percent chance for a
    deflected bullet to ricochet towards the duck
    (chances_to_ricochet_towards_duck)."""))

_TIERS = (('upTo10', 'a channel of 10 users or fewer'),
          ('upTo20', '11 to 20 users'),
          ('upTo30', '21 to 30 users'),
          ('above30', '31 users or more'))

conf.registerGroup(DuckHuntPro, 'chancesToHitSomeoneElse')
conf.registerGroup(DuckHuntPro, 'chancesWildFireHitSomeone')
for _i, (_name, _what) in enumerate(_TIERS):
    conf.registerGlobalValue(DuckHuntPro.chancesToHitSomeoneElse, _name,
        registry.PositiveInteger(data.ACCIDENT_CHANCE_DUCK_PRESENT[_i][1],
            "Percent chance that a missed shot at a duck hits someone else, in %s." % _what))
    conf.registerGlobalValue(DuckHuntPro.chancesWildFireHitSomeone, _name,
        registry.PositiveInteger(data.ACCIDENT_CHANCE_WILD_FIRE[_i][1],
            "Percent chance that a wild shot (no duck) hits someone, in %s." % _what))

conf.registerGroup(DuckHuntPro, 'shopCosts')
for _key, _cost in data.ITEM_COSTS.items():
    conf.registerGlobalValue(DuckHuntPro.shopCosts, _key,
        registry.NonNegativeInteger(_cost, "Price in xp of the shop item %s." % _key))

conf.registerGroup(DuckHuntPro, 'dropChances')
for _key, _chance in data.DROP_TABLE.items():
    conf.registerGlobalValue(DuckHuntPro.dropChances, _key,
        registry.NonNegativeInteger(_chance, """Chance, out of 1000, of the kill drop
        "%s" (rolled in the original's fixed order; the first success wins).""" % _key))

# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=79:
