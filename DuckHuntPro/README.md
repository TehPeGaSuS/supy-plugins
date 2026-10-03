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

Everything lives under `supybot.plugins.DuckHuntPro`; use `config help
<name>`. Channel values (`enabled`, `language`, `ducksPerDay`,
`approxGoldenDucksPerDay`, `goldenDuckMinHP/MaxHP`, `duckSleepHours`,
`shotsBeforeDuckFlee`, `escapeTime`, `unlimitedAmmoPerClip/Clips`,
`antiHighlight`, `preferredDisplayMode`, `monochrome`, `shopEnabled`,
`shopUrl`, `gunHandBackMode`, `kickWhenShot/Sabotaged`, `kickOnWildFire`,
`onlyHuntersCanBeShot`, `topShootersCount`, and so on) can be set per channel;
the rest are global:

- `method`, `postInitDelay`, `autoRefillAmmoTime`, `backupTime`,
  `quarterlyResetEnabled`, `huntingLogs`, `huntingLogDirectory`,
  `anonymPrefix`, `warnOnRename`, `warnOnTakeover`, `pendingTransfersMaxAge`
- `kickViaChanServ` and `chanServKickLine`, both per network (the original's
  `kick_method 1`): the kick goes through services as the raw line in
  `chanServKickLine`, `CS KICK {channel} {nick} :{reason}` by default (needs a
  `CS` alias for ChanServ, as DALnet's has). For networks without it set e.g.
  `PRIVMSG ChanServ :KICK {channel} {nick} {reason}`, or Undernet's
  `PRIVMSG X@channels.undernet.org :<its command>`;
  `strayBulletExemptCapability` (its `exempted_flags`: users with that
  capability never take a stray bullet)
- the original's numbers: `xpPerDuck`, `xpPerGoldenDuckHp`, `xpLuckyShot`,
  `chanceRicochetTowardsDuck`, `chancesToHitSomeoneElse.*`,
  `chancesWildFireHitSomeone.*`, `shopCosts.*` and `dropChances.*` (all
  default to `Duck_Hunt.cfg`'s values)
- `web.enable`: a read-only dashboard through Limnoria's HTTP server
  (`/duckhuntpro/`, per-channel leaderboard and champions).

The level table (accuracy, jam chance, clip sizes, thresholds) is fixed.

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
