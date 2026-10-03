# DuckHuntPro

A Limnoria port of the Eggdrop Tcl script **Duck Hunt v2.11** by Menz Agitat:
XP-based levels, ammo and jamming, golden ducks, a 23-item shop, accidents and
ricochets, weapon confiscation, nick-change stat fusion and the staff tools,
with the original's message catalogue (English and French) and numbers. It is
a separate plugin from `PT/DuckHunt`; see "Known differences" if you run both.

The port follows the Tcl source function by function (`shoot`, `hit_a_duck`,
`plan_out_flights`, `merge_stats`, `antiflood`, ...). Where it deliberately
differs, that is listed in "Known differences" below.

## How it works

Ducks fly on a schedule (`ducksPerDay` per channel, honouring `duckSleepHours`),
whoever hits one first with `bang` gets the XP, and misses cost XP. XP sets
your level (41 levels: accuracy, deflection, defense, jam chance, clip size and
clip count all come from the original's table), and XP is also the shop's
currency. Several ducks can be in the air at once; `bang` always targets the
oldest. State is kept per (network, channel).

## Commands

Player commands (anyone, in the channel; a `[<channel>]` argument is only
needed in private):

| Command | |
|---|---|
| `bang` | Shoot at the current duck. |
| `duckreload` | Reload, or unjam your weapon (named so to avoid the Owner plugin's `reload`). |
| `duckstats [<nick>]` | Hunting stats (a NOTICE). |
| `lastduck` | How long ago the last duck flew. In private it needs channel op/halfop. |
| `shop [<id> [<target>]]` | The catalogue, or buy item 1-23 (14-17 need a target). |
| `duckshooters`, `duckchampions` | Top shooters of the season / of the last reset. |

Staff commands need `#channel,op`, `#channel,halfop` or the global `admin`
capability (the original's `mno|mnol` commands), for example
`channel capability add #channel <user> op` (or `halfop`; needs
`#channel,op` yourself). The global form is `admin capability add <user>
admin`, which only an admin can run and only for capabilities they hold.

| Command | |
|---|---|
| `unarm [-static] <nick>` | Confiscate a weapon (`-static`: permanent, only `rearm` undoes it). |
| `rearm <nick>` | Give the weapon back. |
| `ducklist <channel> [<search>]` | List the profiles of a channel. |
| `duckfusion <channel> <dest> <src> [<src> ...]` | Merge profiles into `<dest>`. |
| `duckrename <channel> <old> <new>` | Rename a profile (refuses if `<new>` exists). |
| `duckdelete <channel> <nick>` | Delete a profile. |
| `duckplanning <channel>` | Today's planned flights (method 2). |
| `duckreplanning <channel>` | Plan a different day (method 2). |
| `ducklaunch <channel> [0\|1]` | Launch a duck now; `1` makes it golden. Says nothing back, like the original. |

Global `admin` only:

| Command | |
|---|---|
| `duckexport [<sort criterion>]` | Write every player of the network to `<data>/DuckHuntPro/players_table.txt` (34 columns, the original's layout and sort criteria). |
| `duckimport <path> [overwrite]` | Import the original's `player_data.db` (see below). |

`blacklisted_handles` of the original maps to Limnoria's anti-capability:
`user capability add <user> -DuckHuntPro`.

## Moving over from the Tcl script

`duckimport /path/to/scripts/duck_hunt/database/player_data.db` reads the
original database (every channel in it lands on the network the command is
used on), converting levels' worth of stats, ammo, items (expired ones are
dropped), confiscation state and best times. Profiles that already exist are
kept unless you add `overwrite`. Take a copy of the plugin's data file first;
the daily `.bak` is the only undo.

## Game rules, briefly

- **Shooting** checks in the original's order: weapon state, water bucket,
  sand/grease/sabotage/liability, jam, empty clip, infrared detector, ammo,
  then the hit roll (sight, sunglasses/mirror dazzle). Misses and wild shots can
  hit a bystander (ricochet chains, deflection, defense, life insurance).
- **Weapons** are confiscated after accidents (and optionally wild fire) and are
  handed back daily at `autoGunHandBackTime`, when the channel's ducks have all
  gone, or never (`gunHandBackMode` 1/2/3). `unarm -static` is permanent.
- **Shop and drops**: 23 items at the original's prices; kills may drop an item
  or an xp book, rolled in the original's order.
- **Flights**: `method` 2 plans the day in advance (hours drawn without
  replacement, replanned at midnight and when bread is bought or expires);
  method 1 rolls every minute. Bread, decoys and fake ducks work as in the
  original. Ammo is refilled daily at `autoRefillAmmoTime`.
- **Nick changes**: the stats follow a renamed player when they next act (the
  original's deferral against stat theft), using its exact merge rules.
- **Antiflood**: per player and command (`floodShoot` 30:600, `floodReload`
  15:120, `floodStats` 2:120, `floodLastduck` 1:300, `floodShop` 3:600) and
  channel-wide (`floodGlobal` 30:600), with the original's throttled warnings.
- **Quarterly reset** (extra, not in the original): on 1 Jan/Apr/Jul/Oct each
  channel's standings are archived for `duckchampions` and xp/stats are zeroed.
  `quarterlyResetEnabled` turns it off.
- **Hunting logs** (`huntingLogs`, off by default): one line per game action in
  `<channel>_<yyyymmdd>.log`, in `huntingLogDirectory`
  (default `<data>/DuckHuntPro/logs/`).
- **Daily backup**: the data file is copied to `<file>.bak` at `backupTime`.

## Configuration

Names below are relative to `supybot.plugins.DuckHuntPro`, and `config help
<full name>` shows the same text as this table. *Scope*: **channel** settings
can be set per channel (`config channel #chan supybot.plugins.DuckHuntPro.ducksPerDay 24`),
**network** settings per network (`config network DALnet
supybot.plugins.DuckHuntPro.kickViaChanServ True`), **global** ones apply to the
whole bot.
Numbers and costs default to the original `Duck_Hunt.cfg` values. The level table
(accuracy, jam chance, clip sizes, thresholds) is fixed.

| Setting | Scope | Default | Description |
|---|---|---|---|
| `enabled` | channel | `False` | Enables the duck hunt game in this channel. |
| `language` | channel | `en` | Language used for this channel's game messages: en or fr (the original script's two catalogues). |
| `ducksPerDay` | channel | `18` | Approximate number of ducks that fly per day. |
| `approxGoldenDucksPerDay` | channel | `1` | Approximate number of golden (multi-hit) ducks per day; must not exceed ducksPerDay, since golden ducks are counted within it. |
| `goldenDuckMinHP` | channel | `3` | Minimum hit points of a golden duck. |
| `goldenDuckMaxHP` | channel | `5` | Maximum hit points of a golden duck. |
| `duckSleepHours` | channel | (empty) | Space-separated list of hours (0-23) during which no duck will fly, e.g. "2 3 4 5". Empty means ducks can fly at any hour. |
| `shotsBeforeDuckFlee` | channel | `3` | Number of non-lethal shots fired at a duck before it flees scared off. -1 means it never flees from gunfire (only from escapeTime). |
| `successfulShotsAlsoScareDucks` | channel | `True` | Whether a kill on one duck also counts toward scaring off other ducks currently in flight on the same channel. |
| `escapeTime` | channel | `300` | Seconds a duck stays in flight before escaping unharmed if nobody kills it. |
| `unlimitedAmmoPerClip` | channel | `False` | Whether clips have unlimited ammo (no reload needed). |
| `unlimitedAmmoClips` | channel | `False` | Whether players have an unlimited number of clips. |
| `antiHighlight` | channel | `False` | Randomizes the duck's flight art each time so highlight-triggered auto-shoot scripts can't be trained on a fixed string. |
| `voiceWhenDuckShot` | channel | `True` | Voices a player in the channel when they shoot down a duck. |
| `devoiceOnWildFire` | channel | `True` | Devoices a player who fires with no duck in sight. |
| `devoiceOnMiss` | channel | `False` | Devoices a player who misses a shot at a duck. |
| `postInitDelay` | global | `60` | Seconds to wait after the plugin loads before planning the day's duck flights, to give the bot time to join all its channels. |
| `quarterlyResetEnabled` | global | `True` | Whether to automatically archive and reset every channel's standings on the 1st of January/April/July/October. |
| `topShootersCount` | channel | `3` | How many players `duckshooters` shows, ranked by xp (kills as tiebreaker). |
| `web.enable` | global | `False` | Enables the built-in web dashboard (leaderboard/ champions/shop pages) served through Limnoria's HTTP server, at /duckhuntpro/<network>/<channel>/<page>. |
| `minXpForShopping` | channel | `0` | The lowest a player's xp balance is allowed to go after a shop purchase; a purchase that would drop them below this floor is refused. |
| `shopEnabled` | channel | `True` | Whether the shop command is available at all (Duck_Hunt.tcl's shop_enabled; when off the command does nothing). |
| `shopPreferredDisplayMode` | channel | `0` | What `shop` without arguments shows: 0 = the catalogue of items and prices, anything else = a message pointing to shopUrl instead. |
| `shopUrl` | channel | (empty) | The web page listing the shop items, shown when shopPreferredDisplayMode is non-zero. |
| `dropsEnabled` | channel | `True` | Whether killing a duck can also drop a bonus item/xp-book on top of the normal xp reward. |
| `maxBreadOnChan` | channel | `20` | Maximum number of active bread pieces on a channel at once; further bread purchases are refused (and not charged) once this cap is hit. |
| `kickWhenSabotaged` | channel | `True` | Whether a sabotaged weapon jamming also kicks the victim from the channel, matching the original script. |
| `cantAttractDucksWhenSleeping` | channel | `True` | Whether decoy/bread purchases are refused during this channel's duckSleepHours. |
| `decoysCanAttractGoldenDucks` | channel | `True` | Whether a duck lured in by the decoy item can randomly turn out to be a golden duck (if false, decoy ducks are always ordinary). |
| `onlyHuntersCanBeShot` | channel | `True` | Whether accidental-hit victims must already have fired at least one shot in this channel (if false, any channel occupant can be hit, even someone who's never played). |
| `gunConfiscationWhenShootingSomeone` | channel | `True` | Whether accidentally hitting another player gets your own weapon temporarily confiscated. |
| `gunConfiscationOnWildFire` | channel | `False` | Whether firing with no duck present (and hitting nobody) also risks a temporary confiscation. |
| `devoiceOnAccident` | channel | `True` | Devoices a player who accidentally hits someone else. |
| `kickWhenShot` | channel | `True` | Whether a player who takes a stray hit (and neither deflects nor is defended by armor) gets kicked. |
| `gunHandBackMode` | channel | `1` | How temporarily-confiscated weapons get returned: 1 = once daily at autoGunHandBackTime, 2 = whenever the channel's duck count drops back to zero (killed/escaped), 3 = never automatically (only the `rearm` command). Permanently-confiscated weapons (`unarm --static`) are never auto-returned by any mode. |
| `autoGunHandBackTime` | channel | `00:00` | Local time (HH:MM) weapons are auto-returned each day, when gunHandBackMode is 1. |
| `method` | global | `2` | How duck flights are scheduled (the original's `method`): 1 = every minute each channel has a chance of a flight (random timing), 2 = the day's flight times are planned in advance, replanned at midnight and whenever bread is bought or expires. |
| `showBreadReplanning` | channel | `True` | Log the new flight plan each time buying or losing bread replans the day (the original's show_bread_replanning). |
| `preferredDisplayMode` | channel | `1` | Where the game's per-player replies go: 1 = PRIVMSG to the channel, anything else = NOTICE to the player (the original's preferred_display_mode). Duck flights, kills and accidents are always public. |
| `monochrome` | channel | `False` | Strip colours and other formatting from every message the game sends (it is always stripped on channels with mode +c). |
| `kickOnWildFire` | channel | `False` | Kick players who shoot when there is no duck (the original's kick_on_wild_fire). |
| `autoRefillAmmoTime` | global | `00:00` | Local time (HH:MM) at which every player's clips are refilled to their level's count each day (the original script's auto_refill_ammo_time). |
| `huntingLogs` | global | `False` | Whether to keep the original's hunting logs: a plain-text trace of everything that happens (flights, shots, reloads, purchases, confiscations, stat transfers), one file per channel and day (the original script's hunting_logs). |
| `huntingLogDirectory` | global | (empty) | Where the hunting logs go, as <channel>_<yyyymmdd>.log files. Empty means a logs directory under the plugin's data directory. |
| `backupTime` | global | `00:03` | Local time (HH:MM) at which the database file is copied to a .bak file next to it each day (the original script's backup_time). |
| `anonymPrefix` | global | (empty) | The prefix your network gives to users who don't identify in time ("Anonyme" for nicks like Anonyme54720). Stats are never transferred automatically to such a nick. Case-sensitive; empty = off. |
| `warnOnRename` | global | `False` | Log a notice when a player who changed nick already has stats under the new nick. |
| `warnOnTakeover` | global | `True` | Log what happened (and the stats involved) when a nick change makes two profiles merge, one replace the other, or a profile get claimed. |
| `pendingTransfersMaxAge` | global | `3600` | Seconds. When the plugin starts, nick-change transfers still waiting are forgotten if nothing about them changed for longer than this. |
| `confiscationEnforcementOnFusion` | channel | `False` | When a renamed player's stats would be merged into their new nick (see nick-change stat fusion), whether a disarmed profile should have its stats discarded instead of merged (an anti-confiscation-dodging measure). Off by default, matching the original script. |
| `antifloodEnabled` | channel | `True` | Whether to rate-limit the game commands (the original's antiflood). |
| `floodShoot` | channel | `30:600` | Individual flood limit for the shooting command as "<requests>:<seconds>": no more than that many uses of the command per player in that many seconds (a rolling window). |
| `floodReload` | channel | `15:120` | Individual flood limit for duckreload as "<requests>:<seconds>": no more than that many uses of the command per player in that many seconds (a rolling window). |
| `floodStats` | channel | `2:120` | Individual flood limit for duckstats as "<requests>:<seconds>": no more than that many uses of the command per player in that many seconds (a rolling window). |
| `floodLastduck` | channel | `1:300` | Individual flood limit for lastduck as "<requests>:<seconds>": no more than that many uses of the command per player in that many seconds (a rolling window). |
| `floodShop` | channel | `3:600` | Individual flood limit for shop as "<requests>:<seconds>": no more than that many uses of the command per player in that many seconds (a rolling window). |
| `floodGlobal` | channel | `30:600` | Flood limit on all the game's commands together, for the whole channel ("<requests>:<seconds>"). The original suggests at least the largest individual limit. |
| `antifloodMsgInterval` | channel | `60` | Minimum number of seconds between two flood-control warnings for the same limit (not too low, or the warnings become the flood). |
| `kickViaChanServ` | network | `False` | Make the game's kicks through services instead of kicking directly (the original's kick_method 1), on this network. Needed when the bot has no op but is allowed to use services. |
| `chanServKickLine` | network | `CS KICK {channel} {nick} :{reason}` | The raw IRC line kickViaChanServ sends on this network, with {channel}, {nick} and {reason} filled in. The default is the original's `CS kick` (the network needs a CS alias for ChanServ, as DALnet's has). Without an alias, for example: `PRIVMSG ChanServ :KICK {channel} {nick} {reason}`; on Undernet the service is X: `PRIVMSG X@channels.undernet.org :KICK {channel} {nick} {reason}`. |
| `strayBulletExemptCapability` | global | (empty) | A capability (for example "duckhuntpro.exempt"): users who have it, or are bots that have it, can never take a stray bullet. The original's exempted_flags; leave empty to exempt only the bot itself. |
| `xpPerDuck` | global | `10` | Experience points for killing a duck (xp_duck). |
| `xpPerGoldenDuckHp` | global | `12` | Experience points for killing a golden duck, per hit point it had. |
| `xpLuckyShot` | global | `25` | Bonus experience points for a "lucky" kill (a ricochet that hits the duck). |
| `chanceRicochetTowardsDuck` | global | `10` | Percent chance for a deflected bullet to ricochet towards the duck (chances_to_ricochet_towards_duck). |
| `chancesToHitSomeoneElse.upTo10` | global | `10` | Percent chance that a missed shot at a duck hits someone else, in a channel of 10 users or fewer. |
| `chancesToHitSomeoneElse.upTo20` | global | `12` | Percent chance that a missed shot at a duck hits someone else, in 11 to 20 users. |
| `chancesToHitSomeoneElse.upTo30` | global | `14` | Percent chance that a missed shot at a duck hits someone else, in 21 to 30 users. |
| `chancesToHitSomeoneElse.above30` | global | `15` | Percent chance that a missed shot at a duck hits someone else, in 31 users or more. |
| `chancesWildFireHitSomeone.upTo10` | global | `1` | Percent chance that a wild shot (no duck) hits someone, in a channel of 10 users or fewer. |
| `chancesWildFireHitSomeone.upTo20` | global | `2` | Percent chance that a wild shot (no duck) hits someone, in 11 to 20 users. |
| `chancesWildFireHitSomeone.upTo30` | global | `3` | Percent chance that a wild shot (no duck) hits someone, in 21 to 30 users. |
| `chancesWildFireHitSomeone.above30` | global | `4` | Percent chance that a wild shot (no duck) hits someone, in 31 users or more. |

### Shop prices (`shopCosts.<item>`, xp)

| Item | Default |
|---|---|
| `extra_ammo` | 7 |
| `extra_clip` | 20 |
| `ap_ammo` | 15 |
| `explosive_ammo` | 25 |
| `buyback_weapon` | 40 |
| `grease` | 8 |
| `sight` | 6 |
| `infrared_detector` | 15 |
| `silencer` | 5 |
| `four_leaf_clover` | 13 |
| `sunglasses` | 5 |
| `spare_clothes` | 7 |
| `brush` | 7 |
| `mirror` | 7 |
| `sand` | 7 |
| `water_bucket` | 10 |
| `sabotage` | 14 |
| `life_insurance` | 10 |
| `liability_insurance` | 5 |
| `decoy` | 8 |
| `bread` | 2 |
| `duck_detector` | 5 |
| `fake_duck` | 50 |

### Kill drop chances (`dropChances.<drop>`, out of 1000)

Rolled in this order; the first success wins, so later drops are effectively rarer.

| Drop | Default |
|---|---|
| `junk` | 20 |
| `ammo` | 20 |
| `clip` | 15 |
| `ap_ammo` | 7 |
| `explosive_ammo` | 5 |
| `grease` | 7 |
| `sight` | 12 |
| `infrared_detector` | 7 |
| `silencer` | 12 |
| `sunglasses` | 12 |
| `duck_detector` | 12 |
| `four_leaf_clover` | 7 |
| `xp_book_10` | 3 |
| `xp_book_20` | 2 |
| `xp_book_30` | 1 |
| `xp_book_40` | 1 |
| `xp_book_50` | 1 |
| `xp_book_100` | 1 |

## Languages

Messages are the original's catalogues (`tclmessages.py`, generated from
`en.utf8`/`fr.utf8`: do not edit by hand). Set a channel's `language` to `en`
or `fr`.

## Known differences from the Tcl script

- Escape timers remove the specific duck whose timer fired, not the list head.
- `adaptTimeResolution` pads milliseconds (the original mangles times under
  100 ms).
- `duckfusion` skips a source that is the destination (the original would
  delete the profile).
- The export's items column lists the active item names, not the raw Tcl list.
- `ducklaunch` never makes a golden duck unless asked, and logs only its own
  `launch` line.
- Flood windows are tracked by timestamps instead of one timer per request
  (same behaviour).
- Commands are Limnoria commands (`bang`, not `!bang`); bind your own
  aliases or use the channel's command prefix. `shop_cmd`/`*_cmd`/`*_auth`
  variables have no equivalent: use Limnoria capabilities.
- Not ported: `max_line_length` (Limnoria splits long lines itself) and the
  database/table/transfer file paths (the plugin uses its own data file and the
  Limnoria data directory).
- If both this plugin and `PT/DuckHunt` are loaded, disambiguate shared names
  with the plugin name (`duckhuntpro bang`).

## Tests

`limnoria-test` runs the suite (about 290 tests); `python3 -m unittest
test_tcldb` in this directory runs the Tcl database reader's tests without
Limnoria.
