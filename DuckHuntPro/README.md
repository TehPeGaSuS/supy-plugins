# DuckHuntPro

A from-scratch Limnoria port of the eggdrop TCL "Duck Hunt" v2.11 script by
Menz Agitat -- a much deeper game than the existing `PT/DuckHunt` plugin
(XP-based leveling, ammo/jamming, golden ducks, a full shop economy, and
social/PvP mechanics). It's a separate plugin, not a replacement; see
"Known limitations" below if you plan to run both at once.

**All 3 planned phases are done**: the core spawn/shoot/level loop, the
full 23-item shop economy with the kill drop table, and friendly-fire/
ricochet accidents, weapon confiscation with 3 auto-return modes,
anti-highlight duck art, automatic nick-change stat fusion, an admin
toolbox, and antiflood. See "Known limitations" below for the handful of
deliberate simplifications made along the way (all flagged, none hidden).

## How it works

Ducks fly on their own schedule (`ducksPerDay` per channel, spread across
each day, honoring `duckSleepHours`), independent of any player action.
Whoever hits it first with `bang` gets the XP; missing costs a small XP
penalty. Golden ducks take multiple hits and are worth more. XP determines
your level (41 levels, thresholds/accuracy/jam-chance/clip-size all
transcribed from the original script's config), which in turn determines
your accuracy and how forgiving your weapon is.

The game is **network-independent**: all state is keyed by (network,
channel), not channel alone, so `#duckhunt` on one IRC network and
`#duckhunt` on another are two completely separate games sharing nothing
but the plugin code.

## Commands

- `bang [<channel>]` -- shoot at the current duck.
- `duckreload [<channel>]` -- reload your weapon, or clear a jam. (Not
  named `reload` -- that collides with the core Owner plugin's
  `reload <plugin>` command.)
- `duckstats [<channel>] [<nick>]` -- your hunting stats, or someone else's.
- `lastduck [<channel>]` -- how long ago the last duck flew here.
- `duckshooters [<channel>]` -- top 3 shooters this season, ranked by xp
  (kills as tiebreaker).
- `duckchampions [<channel>]` -- top 3 shooters from the most recently
  completed season (see "Quarterly reset" below).
- `shop list [<channel>]` -- lists everything for sale with cost and a
  one-line description.
- `shop buy <item> [<target>] [<channel>]` -- buys `<item>`, spending your
  xp. `mirror`/`sand`/`water_bucket`/`sabotage` need a `<target>` player.
- `unarm <nick> [static] [<channel>]` -- (op) confiscates `<nick>`'s weapon.
  `static` makes it permanent -- only `rearm` can undo it, and it survives
  every auto-hand-back mode.
- `rearm <nick> [<channel>]` -- (op) force-restores `<nick>`'s weapon,
  regardless of confiscation mode.
- `admin list/fusion/rename/delete/planning/replanning/launch/export` --
  (admin capability) the admin toolbox; see "Admin toolbox" below.

## Shop economy

Currency is xp itself -- the same stat that drives your level -- so buying
things can knock you back down a level (`minXpForShopping`, default 0, sets
a floor on your post-purchase balance). The shop is closed entirely while
your weapon is confiscated, except for `buyback_weapon` itself.

| Item | Cost | Effect |
|---|---|---|
| `extra_ammo` | 7 | +1 round in your current clip (capped at your level's clip size). |
| `extra_clip` | 20 | +1 spare clip (capped at your level's clip count). |
| `ap_ammo` | 15 | 24h: x2 damage vs golden ducks. Mutually exclusive with `explosive_ammo`. |
| `explosive_ammo` | 25 | 24h: x3 damage vs golden ducks. Mutually exclusive with `ap_ammo`. |
| `buyback_weapon` | 40 | Un-confiscates your weapon. |
| `grease` | 8 | 24h: halves your jam chance; also absorbs one `sand` throw aimed at you. |
| `sight` | 6 | Your very next shot only: accuracy boost, then consumed regardless of hit/miss. |
| `infrared_detector` | 15 | 24h or 6 uses (whichever first): blocks a would-be wasted wild shot outright, ammo untouched. |
| `silencer` | 5 | 24h: your shots never scare ducks into fleeing. |
| `four_leaf_clover` | 13 | 24h: a flat random bonus (1-10 xp) added to every kill, even a 0-xp fake duck. |
| `sunglasses` | 5 | 24h: makes a `mirror` thrown at you fail (you're still told about the attempt). |
| `spare_clothes` | 7 | Cures `water_bucket`. |
| `brush` | 7 | Cures `sand` and/or `sabotage`. |
| `mirror` | 7 | Targeted: halves the target's accuracy on their next shot, then consumed. |
| `sand` | 7 | Targeted: doubles the target's jam chance on their next shot, then consumed. Absorbed harmlessly by the target's `grease`. |
| `water_bucket` | 10 | Targeted: target can't shoot at all for 1 hour. |
| `sabotage` | 14 | Targeted: guarantees the target's next shot jams, and kicks them (`kickWhenSabotaged`). |
| `life_insurance` | 10 | 7 days/1 use: pays out `2x your own level` in bonus xp if you take a stray hit -- regardless of whether that hit is deflected, absorbed, or lands. |
| `liability_insurance` | 5 | 2 days: cuts your own accident xp penalty to a third when you hit a bystander. |
| `decoy` | 8 | Lures a real duck to the channel within 1-600 seconds. |
| `bread` | 2 | 1h, stacks up to `maxBreadOnChan`: +1 duck slot per piece on the next planned day, +20s escape time per piece on every duck while active. |
| `duck_detector` | 5 | Next duck spawn only: you get a NOTICE in advance, then consumed. |
| `fake_duck` | 50 | A duck arrives in exactly 600 seconds, worth 0 xp (still rolls the drop table). |

Two parity notes carried over deliberately from Duck_Hunt.tcl, not bugs:
`four_leaf_clover`'s bonus isn't gated on the duck being a fake one, so it
applies even to an otherwise-zero-xp fake duck kill; and `life_insurance`'s
bonus is computed from the *victim's own* level, not the shooter's, despite
the original script's shop message claiming the latter.

**Kill drop table**: every kill (real, golden, or fake) has a small chance
of an extra drop, gated by `dropsEnabled`. It's rolled key-by-key in a fixed
order (junk, ammo, clip, ap_ammo, explosive_ammo, grease, sight,
infrared_detector, silencer, four_leaf_clover, sunglasses, duck_detector,
then xp-books worth 10/20/30/40/50/100), each an independent per-1000
chance, stopping at the first success -- so a kill drops at most one thing,
and later keys are effectively rarer than their raw percentage suggests
since an earlier key may have already "used" the roll. `junk` is a pure
flavor-text dud with no effect.

**Deliberate simplification vs. the original**: buying bread doesn't force
an immediate reschedule of the day's already-planned duck flights; the
extra spawn density takes effect the next time that channel's day gets
(re)planned (which happens often anyway, since a day's schedule
self-replans once it runs out).

## Friendly fire / ricochet

Every miss (wild shot or a genuine miss with a duck present) has a small
chance of hitting a random other channel occupant instead, tiered by
channel population and by whether a duck was actually present
(`onlyHuntersCanBeShot`, default on, restricts victims to people who've
actually fired a shot here before). What happens to the victim:

1. **Deflects** (their level's deflection stat) -- the bullet either
   ricochets toward the current duck (a "lucky shot" kill, worth the
   normal duck xp plus a flat bonus) or continues on to hit *another*
   random victim, chaining up to `MAX_RICOCHETS` (5) times.
2. **Is defended** (their level's defense/armor stat) -- no harm done.
3. **Is hit outright** -- kicked (`kickWhenShot`), unless their
   `life_insurance` pays out instead (see the shop table above).

The shooter's own weapon gets temporarily confiscated the first time they
hit someone this way (`gunConfiscationWhenShootingSomeone`, default on),
and is devoiced (`devoiceOnAccident`). Firing wild (no duck present) can
also risk confiscation on its own via `gunConfiscationOnWildFire` (default
off).

## Weapon confiscation

A confiscated weapon has two states: temporary (auto-returned) or
permanent (`unarm <nick> static` -- only `rearm` undoes it). Temporary
confiscations return via `gunHandBackMode`:

1. **Daily**, at a fixed local time (`autoGunHandBackTime`, default
   `00:00`).
2. **Whenever the channel's duck count drops back to zero** (killed,
   fled, or escaped) -- simplified from the original's "per hunting
   session" semantics since this port caps at one duck in flight at a
   time, so every resolution already empties the queue.
3. **Never automatically** -- only `rearm` returns a weapon.

## Anti-highlight duck art

`antiHighlight` randomizes the flight announcement (trail + duck glyph +
cry, each picked independently) so highlight-triggered auto-shoot scripts
can't be trained on one fixed string. A representative set of glyphs/cries
is used rather than the original's ~228-entry table -- full parity on game
numbers/mechanics mattered more here than matching every joke string 1:1.

## Nick-change stat fusion

Fully automatic, no confirmation needed. When a player renames, the merge
is deferred until their *next* in-game command (not the rename itself) --
matching the original's deliberate delay "to reduce the risk of stat
theft." If they part/quit before ever acting again, nothing merges and
their old stats stay under the old nick. By default the merge just sums
everything (xp, kills, stats); `confiscationEnforcementOnFusion` (off by
default) instead discards a disarmed profile's stats as an
anti-confiscation-dodge measure.

## Admin toolbox

`admin <subcommand>`, gated by the `admin` capability:

- `list [<channel>] [<pattern>]` -- player nicks (optionally filtered),
  ranked by xp.
- `fusion <channel> <dest> <source>` -- manually merges `<source>`'s stats
  into `<dest>` (same logic as automatic nick-fusion).
- `rename <channel> <old> <new>` -- pure rename; refuses if `<new>` already
  has a profile (use `fusion` instead).
- `delete <channel> <nick>` -- deletes a profile entirely.
- `planning <channel>` -- shows how many flights are currently scheduled
  and when the next one is.
- `replanning <channel>` -- forces an immediate recompute of the day's
  remaining schedule.
- `launch <channel> [golden]` -- force-spawns a duck right now, bypassing
  the schedule; refused if a duck is already in flight.
- `export [<channel>]` -- writes every network/channel's player stats to a
  plaintext file under the bot's data directory.

## Antiflood

A single per-player, rolling 60-second window (`antifloodEnabled`,
`antifloodMaxPerMinute`, default 10/minute) shared across all commands.
Simplified from the original's 5 independent per-command thresholds plus 1
global one -- full parity on every knob wasn't judged worth the complexity
for what's meant to be a lightweight safety net, not a security boundary.
Blocked attempts are silently dropped with a short reply, no kick/ban.

## Quarterly reset

On the 1st of January/April/July/October, every channel's standings are
archived (see `duckchampions`) and then every player's xp and stats are
zeroed -- a fresh competitive season. Gun state, ammo, and purchased items
are left untouched; this resets the leaderboard, not a player's equipment.
Controlled by `supybot.plugins.DuckHuntPro.quarterlyResetEnabled` (global,
default on). Implemented as a self-rescheduling one-shot `schedule.addEvent`
(same pattern as daily flight planning), so it survives restarts the same
way -- the next reset is always computed fresh from the current date rather
than stored.

## Web dashboard

Set `supybot.plugins.DuckHuntPro.web.enable` (global) to `True` to serve a
read-only dashboard through Limnoria's built-in HTTP server:

- `/duckhuntpro/` -- index of all known network/channel games.
- `/duckhuntpro/<network>/<channel>/leaderboard` -- current-season standings.
- `/duckhuntpro/<network>/<channel>/champions` -- last season's top 3.
- `/duckhuntpro/<network>/<channel>/shop` -- placeholder; a real catalog/
  purchase page isn't built yet even though the shop itself (via IRC
  commands) is fully implemented.

Routes are scoped by network then channel (both URL-encoded) so that the
same channel name on two different networks gets two different pages, in
keeping with the plugin's network-independence. This follows the same
`httpserver.hook()`/`SupyHTTPServerCallback` pattern used by the stock
`Factoids`/`Aka`/`Fediverse` plugins.

## Configuration

All values are per-channel (`supybot.plugins.DuckHuntPro.<name>`), except
`postInitDelay` which is global.

| Setting | Default | Meaning |
|---|---|---|
| `enabled` | False | Turn the game on for this channel. |
| `language` | en | Message language (only `en` ships; see below). |
| `ducksPerDay` | 18 | Approximate ducks per day. |
| `approxGoldenDucksPerDay` | 1 | Approximate golden ducks per day (subset of ducksPerDay). |
| `goldenDuckMinHP` / `goldenDuckMaxHP` | 3 / 5 | Golden duck hit points range. |
| `duckSleepHours` | (empty) | Space-separated hours (0-23) with no flights, e.g. `2 3 4 5`. |
| `shotsBeforeDuckFlee` | 3 | Non-lethal shots before a (non-golden) duck flees. -1 = never. |
| `successfulShotsAlsoScareDucks` | True | Reserved for when multiple ducks can be in flight at once; currently unused, since this port caps it at one duck per channel. |
| `escapeTime` | 300 | Seconds before an unshot duck escapes. |
| `unlimitedAmmoPerClip` / `unlimitedAmmoClips` | False | Disable ammo/clip limits. |
| `antiHighlight` | False | Randomizes duck-flight art to defeat highlight-triggered auto-shoot scripts. |
| `voiceWhenDuckShot` | True | Voice a player when they kill a duck. |
| `devoiceOnWildFire` | True | Devoice a player who shoots with no duck present. |
| `devoiceOnMiss` | False | Devoice a player who misses. |
| `postInitDelay` (global) | 60 | Seconds after load/join before planning a channel's first day of flights. |
| `quarterlyResetEnabled` (global) | True | Auto-archive and reset every channel's standings on the 1st of Jan/Apr/Jul/Oct. |
| `web.enable` (global) | False | Serve the read-only web dashboard (see below). |
| `minXpForShopping` | 0 | Floor on a player's post-purchase xp balance. |
| `dropsEnabled` | True | Whether kills can also drop a bonus item/xp-book. |
| `maxBreadOnChan` | 20 | Cap on simultaneously active bread pieces per channel. |
| `kickWhenSabotaged` | True | Whether a triggered `sabotage` also kicks the victim. |
| `cantAttractDucksWhenSleeping` | True | Whether `decoy`/`bread` are refused during `duckSleepHours`. |
| `decoysCanAttractGoldenDucks` | True | Whether a `decoy`-lured duck can turn out golden. |
| `onlyHuntersCanBeShot` | True | Whether accidental-hit victims must already have fired a shot here. |
| `gunConfiscationWhenShootingSomeone` | True | Whether hitting a bystander confiscates your own weapon. |
| `gunConfiscationOnWildFire` | False | Whether firing wild also risks confiscation. |
| `devoiceOnAccident` | True | Devoices a player who hits someone by accident. |
| `kickWhenShot` | True | Whether an accidental-hit victim who isn't insured gets kicked. |
| `gunHandBackMode` | 1 | 1=daily, 2=on duck-count-zero, 3=manual only (`rearm`). |
| `autoGunHandBackTime` | 00:00 | Local HH:MM weapons are returned daily, when mode is 1. |
| `confiscationEnforcementOnFusion` | False | Discard a disarmed profile's stats on nick-fusion instead of merging. |
| `antifloodEnabled` | True | Rate-limit rapid repeated command use per player. |
| `antifloodMaxPerMinute` | 10 | Max uses of any command per player per rolling 60s window. |

## Language files

Player-facing strings live in `messages.py`, in a dict keyed by language then
by message name (`MESSAGES['en']['kill']`, etc.), mirroring the original
script's `msgcat`-based localization but with named placeholders instead of
positional ones. Only English ships. To add a language, add a sibling dict
(e.g. `MESSAGES['pt'] = {...}`) with the same keys and set the channel's
`language` config to match -- `messages.get()` falls back to English for any
key a language dict doesn't define.

## Known limitations

- At most one duck in flight per channel at a time (the original script
  supports several at once, e.g. via decoys/bread/fake ducks stacking). A
  `decoy`/`fake_duck` purchase is silently dropped if a duck is already in
  flight when its timer fires. `successfulShotsAlsoScareDucks` is a
  reserved config knob for that future multi-duck case; it's currently
  unread by the code.
- If you flip `enabled` on for a channel the bot already joined a while ago
  (rather than at load time or via a fresh join), flight planning won't
  kick in until the plugin reloads. Toggling it right after `!load` or
  right after the bot joins the channel works fine.
- If both this plugin and `PT/DuckHunt` are loaded on the same bot, any
  identically-named command (there shouldn't be any left after the
  `reload`->`duckreload` rename, but double-check if you add commands)
  needs to be disambiguated with the plugin name (e.g. `duckhuntpro bang`).
- Nick-fusion's ammo merge is simplified: the destination profile's
  ammo/clip state is kept as-is rather than proportionally recalculating it
  from both profiles' combined capacity/usage, unlike the original.
- Antiflood is one shared per-player threshold rather than 5 independent
  per-command ones plus a global one -- see "Antiflood" above.
- The web dashboard's shop page is a placeholder even though the shop
  itself works over IRC.
- The dashboard can't be exercised with a real HTTP request under
  `supybot-test` -- Limnoria's test harness stubs out the actual socket
  listener in test mode, so its hook/unhook lifecycle is tested directly
  instead of end-to-end. It follows the exact pattern used by the stock
  `Factoids`/`Aka`/`Fediverse` plugins.
