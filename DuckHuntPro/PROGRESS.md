# DuckHuntPro -- progress & roadmap

**Status: all 3 planned phases are complete (2026-07-27, committed/pushed
as `14fd0ae`)**, plus the extra gathered requirements (best-shooters,
quarterly reset, web dashboard, network-independence), a `topShootersCount`
config knob, and multi-duck support (all added after the initial ship, see
below). 121 tests passing via `supybot-test`. The sections below are a
historical build log, not a live TODO list, except "Known limitations" in
`README.md` which documents the deliberate, permanent simplifications.

**Multi-duck support (added post-ship, 2026-07-27).** The initial ship
capped every channel at one duck in flight at a time -- a real gap from
"full parity," called out by the user right after shipping (see the
now-resolved correction this replaced). Removed entirely: `_activeDuck` is
now `{(network, channel): [duck, duck, ...]}`, oldest-first, instead of a
single dict; spawning (`_fireSpawn`, `_fireSpecialSpawn`, `admin launch`)
no longer checks for an existing duck before adding another, matching
Duck_Hunt.tcl exactly (confirmed via a dedicated research pass: the
original has no concurrent-duck cap either -- concurrency there is just an
emergent result of spawn timing vs. `escapeTime`). Key design points,
transcribed from the original's `duck_sessions` dict-of-lists rather than
guessed:
- **Targeting is strict FIFO** -- `bang()`/ricochet-into-duck always hits
  `ducks[0]` (oldest), matching `hit_a_duck`'s unconditional list-head
  operation. Never random, never "closest to escaping," never a shotgun
  spread across every duck in flight.
- **`successfulShotsAlsoScareDucks` finally wired up** (previously a
  registered-but-unread no-op knob) via a new `_ducksScaring()` method
  ported from `ducks_scaring`: a miss *always* bumps every currently-flying
  duck's own scare counter by one (not just the one aimed at); a kill only
  does this if the setting is on. Any duck (except golden/fake, always
  immune) whose counter reaches `shotsBeforeDuckFlee` flees immediately.
  `silencer` blocks this scaring effect entirely for that shot, for every
  duck, not just the target.
- **Per-duck escape identity, a deliberate improvement over literal
  fidelity**: Duck_Hunt.tcl's escape callback (`terminate_duck_session`)
  always removes list-head regardless of which specific duck's `utimer`
  fired -- harmless there since escape deadlines are normally monotonic
  with spawn order, but not identity-safe. This port's `_duckEscapes`
  removes the *specific* duck matching the timer's own `spawned_at`
  instead, since every duck's spawn time was already threaded through its
  scheduled event name for restart-safety -- tracking identity cost
  nothing extra here, so there was no reason to replicate a bug just for
  bug-for-bug fidelity. Documented as a deviation, not hidden.
- **Gun-hand-back mode 2 fixed to consider the whole session**: previously
  fired after *any* kill (correct only because there was always exactly
  one duck); now correctly waits for the channel's entire duck list to
  empty out, matching `gun_hand_back_mode==2`'s real semantics (confirmed
  via research: "session" = "whatever's concurrently in flight right now,"
  not a fixed batch or timer).
- `admin.launch`'s "duck already in flight" refusal was removed --
  Duck_Hunt.tcl's `!ducklaunch` never checked either; it always adds
  another duck.
- 11 new tests covering coexistence, FIFO targeting, cross-duck scare
  propagation (both hit- and miss-triggered), golden/fake immunity,
  silencer blocking scaring for every duck, per-duck escape identity, and
  mode-2 waiting for full session end.

**`duckplanning`/`duckreplanning` output format fixed to match the
original** (also post-ship, user provided real TCL output as reference):
both now list every planned flight's local HH:MM time
(`00:34, 01:57, 02:38, ...`), not a generic "N flights, next in Xm" summary
invented during the initial build without checking the original's actual
output shape.

**`topShootersCount` (added post-ship, 2026-07-27).** User wanted
`duckshooters` to show more than a hard-coded top 3 (e.g. top 5). Added a
`registerChannelValue` knob, default 3 (keeping existing behavior for
anyone already running it), read at command time instead of a literal `3`.
Deliberately scoped to `duckshooters` only, not `duckchampions` (the
archived quarterly-reset leaderboard) -- user's explicit call, since
`duckchampions` is a snapshot of history rather than a live progression
view. Found via testing (not review): a new test driving `duckshooters`
with 5 players hit a real timing gap -- `DuckHuntPro` is `threaded = True`,
so a command that calls `irc.reply()` in a loop can still be mid-loop in
its background thread when a bare `self.irc.takeMsg()` (no poll/wait)
already returns `None`, understating how many messages actually got
queued. Fixed by adding a `_drainWait()` test helper that polls (same
`time.sleep` + `drivers.run()` pattern `_feedMsg` uses internally) instead
of assuming everything is already sitting in the queue. The original
2-player `testDuckshootersRanksByXp` test was left as-is since it hasn't
shown this flakiness in practice, but the same latent risk technically
applies to it too -- worth switching to `_drainWait()` if it ever flakes.

Working notes for resuming this project in a later session. See also the
original design plan at `~/.claude/plans/zany-finding-emerson.md` (architecture
rationale, full data-table provenance) and project memory
(`duckhuntpro_port` / `supybot_plugin_testing`).

Source material: eggdrop TCL "Duck Hunt" v2.11 by Menz Agitat --
`20160411155023-duck_hunt_v2_11/Duck_Hunt.tcl` (~4200 lines) +
`duck_hunt/Duck_Hunt.cfg` (~650 lines) in the Blacklist working directory.
Goal: a new, separate Limnoria plugin (`supy-plugins/DuckHuntPro/`) with
full feature parity, built in phases, English-first with a language-file
mechanism for more.

## Done

**Phase 1 -- core loop.**
- `data.py`: 41-level XP/accuracy/deflection/defense/jam/clip table +
  core constants (golden duck HP/xp, shots-before-flee, escape time,
  accident-chance tiers not yet used), all transcribed verbatim from
  `Duck_Hunt.cfg` -- not invented. `ITEM_COSTS`/`DROP_TABLE` dicts are
  transcribed too but unused until Phase 2.
- `messages.py`: custom `{lang: {key: template}}` dict + `get()` with
  English fallback. Only `en` has content. Deliberately NOT using
  Limnoria's built-in gettext/`_()` i18n -- that system is global-bot-
  language-only (no per-channel override) and this repo has no `.pot`
  extraction tooling, both poor fits for a content-heavy game.
- `db.py`: single JSON file, atomic writes (tempfile + os.replace),
  `threading.RLock`. **Keyed by (network, channel)**, not channel alone.
- `plugin.py`: pre-planned daily duck-flight scheduling (`schedule.addEvent`,
  restart-safe -- rehydrates from `planned_flights` on load, drops overdue
  ones, reschedules future ones, plans a fresh day if none are left),
  `bang`/`duckreload`/`duckstats`/`lastduck` commands, ammo/clip/jam driven
  by the level table, golden ducks (multi-hit), XP gain/penalties, leveling,
  `die()` cleanup. All randomness goes through `self._rng`
  (`random.Random()`) so tests can inject a `ScriptedRNG` instead of fighting
  real probabilities.
- `test.py`: 17 tests, passing via a real `supybot-test` run (scratch venv +
  isolated `--plugins-dir`, see `supybot_plugin_testing` memory for why this
  matters more than it sounds like it should).

**Network-independence retrofit (this session, after Phase 1 shipped).**
Originally Phase 1 keyed everything by channel name only, which breaks the
moment `#duckhunt` exists on two networks. Fixed:
- `db.py` schema is now `{"networks": {net: {"channels": {chan: {...}}}}}`;
  every `Database` method takes `network` as its first argument.
- `plugin.py`'s in-memory `self._activeDuck` is keyed by
  `(network.lower(), channel.lower())` tuples, not channel alone.
- Every scheduled event name includes the network
  (`DuckHuntPro:flight:<network>:<channel>:<time>`, etc.) for uniqueness and
  debuggability.
- `test.py` has `testSameChannelNameDifferentNetworksAreIndependent`
  covering this directly.
- No migration path was written -- Phase 1 was never deployed anywhere with
  real data, so there was nothing to migrate.

Found only by actually running `supybot-test` (not by review): a command
literally named `reload` was silently shadowed by the core Owner plugin's
`reload <plugin>` command. Renamed to `duckreload`.

**Gathered requirements, built this session (2026-07-27).**

1. **`duckshooters` -- top 3 best shooters.** `Database.topPlayers()` sorts
   by xp with kills as tiebreaker (decision made: xp, since it's the
   primary progression currency and what levels derive from -- kills alone
   would undercount golden-duck value). Returns just the top N.
2. **Quarterly stats reset**, 1st of Jan/Apr/Jul/Oct at local midnight.
   Implemented as a self-rescheduling one-shot `schedule.addEvent` chain
   (`_scheduleQuarterlyReset`/`_fireQuarterlyReset`/`_nextQuarterReset`),
   same trick as `_planDay`. **Archives final standings before wiping**
   (`Database.archiveAndReset`) -- decision made on what resets: only
   `xp`/`stats` zero out; gun state, ammo, and purchased items are left
   alone (this resets the competitive season, not a player's equipment).
   `duckchampions` shows the most recent archive's top 3. Controlled by
   `quarterlyResetEnabled` (global, default on).
3. **Web dashboard.** Built via Limnoria's built-in HTTP server exactly as
   planned (`httpserver.hook()`/`SupyHTTPServerCallback`, matching
   Factoids/Aka/Fediverse's pattern). Routes:
   `/duckhuntpro/` (index), `/duckhuntpro/<network>/<channel>/leaderboard`,
   `/duckhuntpro/<network>/<channel>/champions`,
   `/duckhuntpro/<network>/<channel>/shop` (placeholder until Phase 2 has a
   shop to show). Gated behind `web.enable` (global, default off), with a
   config-change callback so toggling it live starts/stops the listener,
   same convention as Factoids. **Limitation found while testing:**
   Limnoria's test harness swaps in `TestSupyHTTPServer` (a no-op stub)
   whenever `world.testing` is set, so a real socket-level HTTP request
   can't be exercised inside `supybot-test` -- confirmed by reading
   `src/httpserver.py`. The route-rendering logic (`_renderWeb` and its
   helpers) is unit-tested directly instead, and the hook/unhook lifecycle
   is tested for "does it run and toggle state without raising", not for
   an actual HTTP round-trip.
4. **Network-independence** -- done, see above (unchanged this session).

Also found only by running `supybot-test`: the `_WebNotFound` exception
class gets rebuilt as a new class object every time `plugin.py` is reloaded
(the plugin's `__init__.py` does `reload(plugin)` for live-reload support),
so importing `_WebNotFound` once at test-module load time and later
`assertRaises`-ing against it fails an identity check even though the
"same" exception (by name) is genuinely raised. Fixed by comparing
`type(e).__name__` instead of the class object. And: `_fireQuarterlyReset`
broadcasts a channel message as a side effect, which was bleeding into the
next `assertRegexp` call in `testDuckchampionsShowsLastArchive` (same
message-queue-draining gotcha as Blacklist's tests) -- fixed with a
`_drain()` helper.

## Done (Phase 2 -- economy, 2026-07-27)

Built by researching `Duck_Hunt.tcl` directly for each item's real mechanic
(the `.cfg` only ever had costs) -- see `data.ITEM_META`/`ITEM_DESCRIPTIONS`
and `plugin.py`'s `_buy*` handlers for the transcription. All 23 items from
`ITEM_COSTS` now have real behavior, not just a cost catalog:

- **Currency**: xp itself, with `minXpForShopping` as a floor on the
  post-purchase balance (matches the original's `min_xp_for_shopping`
  semantics exactly -- it's a floor on the result, not on the pre-purchase
  balance).
- **Ammo/buffs**: `extra_ammo`/`extra_clip` (instant, capped at level max),
  `ap_ammo`/`explosive_ammo` (24h, x2/x3 golden-duck damage, mutually
  exclusive), `grease` (24h, halves jam, absorbs one `sand`), `sight`
  (next-shot-only accuracy boost), `infrared_detector` (24h/6-use wild-shot
  blocker), `silencer` (24h, shots never scare ducks), `four_leaf_clover`
  (24h flat bonus xp per kill), `sunglasses` (24h, blocks incoming
  `mirror`).
- **Cures**: `spare_clothes` (cures `water_bucket`), `brush` (cures `sand`
  and/or `sabotage`).
- **PvP debuffs** (all targeted, all validate the target is online and has
  played): `mirror` (halves target's next-shot accuracy), `sand` (doubles
  target's next-shot jam chance, absorbed by target's `grease`),
  `water_bucket` (blocks target's shooting entirely for 1h), `sabotage`
  (guarantees target's next shot jams + kicks them, `kickWhenSabotaged`).
- **Channel-wide**: `decoy` (lures a real duck in 1-600s, `decoysCanAttractGoldenDucks`),
  `bread` (stacks up to `maxBreadOnChan`, boosts next-planned-day duck count
  and every duck's escape time), `fake_duck` (fixed 600s delay, 0-xp duck
  that still rolls the drop table).
- **Purchase-only, no trigger yet**: `life_insurance`/`liability_insurance`
  -- both need the friendly-fire/accident mechanic that's Phase 3 scope, so
  they're buyable and stored but inert until then. Documented, not hidden.
- **Kill drop table** (`data.rollDrop`): transcribed the TCL's actual
  algorithm exactly -- a FIXED-ORDER sequential Bernoulli check per key,
  first success wins, not a normalized weighted pick. Gated by
  `dropsEnabled`. `junk` is a pure dud; xp-book keys grant flat xp; every
  other key installs the same item a shop purchase would (silently
  replacing any existing one, unlike a purchase which blocks on "already
  have this").

**Two literal parity quirks preserved from Duck_Hunt.tcl** (flagged, not
silently "fixed"): `four_leaf_clover`'s bonus-xp isn't gated on
`is_fake_duck`, so it applies even to an otherwise-zero-xp fake duck kill;
and `life_insurance`'s bonus is `2x the victim's own level`, not `2x the
shooter's level` as the original script's own shop message claims --
verified by reading the actual TCL code twice, the doc comment is simply
stale.

**Deliberate simplification vs. the original**: buying bread doesn't force
an immediate reschedule of the current day's already-built flight schedule;
the boost applies starting with the next time that channel's day gets
(re)planned. The original does force an immediate replan; this was judged
not worth the extra complexity for how often replanning already happens
naturally.

**Bugs found only by running `supybot-test`** (not by review):
- `_buy()`'s "shop closed while confiscated" gate initially blocked
  `buyback_weapon` too, making a confiscated player's weapon permanently
  unrecoverable through the shop -- the one item that's supposed to be the
  escape hatch. Fixed by exempting `buyback_weapon` from that gate.
- `self.shop.plugin` was never set, so every `shop buy`/`shop list` call
  crashed with `AttributeError: 'NoneType' object has no attribute '_buy'`
  -- nested `callbacks.Commands` classes (`self.exempt`/`self.net` in
  Blacklist, `self.shop` here) do NOT get a `.plugin` back-reference
  automatically; the owning plugin's `__init__` has to set it explicitly
  (`self.shop.plugin = self`), exactly like Blacklist already does for its
  own nested groups. Missed this on the first pass despite having read
  Blacklist's pattern -- worth remembering for any *new* nested command
  group in this codebase.
- A test asserting a `sabotage`-triggered KICK failed because
  `assertNotError()`'s single `takeMsg()` call grabbed the KICK message
  before the drain loop could see it: Limnoria's outgoing queue
  (`IrcMsgQueue` in `src/irclib.py`) is priority-ordered, not FIFO --
  KICK/MODE-class commands are "high priority" and jump ahead of a
  PRIVMSG queued earlier in the same command. Not a plugin bug, a test
  design issue; fixed by using `getMsg()` and checking every message the
  command produced instead of assuming the first one popped is the one
  that matters.
- Two test assertions checked for wording ("rich enough") that didn't match
  the actual message text ("xp floor") -- caught immediately by the real
  test run, not a functional bug.

`test.py` now has 79 tests, all passing via `supybot-test`.

## Done (Phase 3 -- social & admin, 2026-07-27)

Full parity is now complete: all 3 originally-planned phases are built.
Researched directly from `Duck_Hunt.tcl` (a fresh, dedicated research pass
covering friendly-fire, confiscation, anti-highlight, nick-fusion, admin
commands, antiflood) rather than guessed.

- **Friendly fire / ricochet** (`plugin.py`'s `_resolveAccident`, called
  from both of `bang()`'s miss branches): population- and duck-presence-
  tiered chance of hitting a random other channel occupant
  (`onlyHuntersCanBeShot` restricts victims to people who've actually
  fired here, matching the original's default). Victim deflects (chains to
  another victim, or -- if a duck is in flight -- ricochets into a "lucky
  shot" kill via the newly-extracted `_resolveDuckHit` helper, shared with
  `bang()`'s direct-hit path), is defended (armor, no effect), or is hit
  outright (kicked unless `life_insurance` pays out). Shooter's weapon gets
  temporarily confiscated on the first hit
  (`gunConfiscationWhenShootingSomeone`) and devoiced. This is also what
  finally wires up `life_insurance` (2x victim's own level, awarded
  regardless of deflect/defense/death -- confirmed by re-reading the TCL
  code) and `liability_insurance` (shooter's own accident penalty ÷3),
  which Phase 2 could only buy-and-store.
- **Weapon confiscation, 3 modes** (`gunHandBackMode`): daily at a fixed
  time (self-rescheduling `schedule.addEvent`, same trick as quarterly
  reset), on-duck-count-zero (simplified from "per hunting session" since
  this port caps at one duck in flight), or manual-only. Added a third
  `gun_state` value, `confiscated_permanent` (`unarm --nick-- static`, only
  `rearm` undoes it, survives every auto-mode) alongside the existing
  `armed`/`confiscated`.
- **Anti-highlight duck art** (`data.randomDuckArt`): trail mutation + random
  glyph + random cry, wired into `_spawnDuck`. A representative glyph/cry
  set, not the original's ~228-entry table.
- **Nick-change stat fusion**: `doNick`/`doPart`/`doQuit` handlers +
  `Database.recordPendingTransfer`/`popPendingTransfer`. Deliberately
  deferred to the renamed player's *next* action (`_checkPendingRename`,
  called from every player-facing command) rather than merging instantly
  at rename time, matching the original's "reduce risk of stat theft"
  reasoning. `confiscationEnforcementOnFusion` (off by default) discards a
  disarmed profile's stats instead of merging.
- **Admin toolbox** (`class admin(callbacks.Commands)`, `admin`
  capability): list/fusion/rename/delete/planning/replanning/launch/export,
  plus top-level `unarm`/`rearm` (channel `op` capability, matching the
  original's pub-command gating). `export` writes a plaintext table to the
  bot's data directory rather than requiring a separate transport.
- **Antiflood**: one shared per-player rolling-60s-window threshold
  (`antifloodEnabled`/`antifloodMaxPerMinute`), collapsed from the
  original's 5 independent per-command thresholds + 1 global one -- a
  deliberate simplification, not full parity, since this is meant as a
  lightweight safety net rather than a security boundary.

**Bugs found only by running `supybot-test`** (not by review):
- The confiscated-weapon shop gate (`_buy()`) initially blocked
  `buyback_weapon` for BOTH `confiscated` and the newly-added
  `confiscated_permanent` states identically -- fixed `_buyBuyback` to give
  a distinct "permanently confiscated, only an op can rearm it" message
  instead of the misleading "isn't confiscated" one.
- `self.admin.plugin` needed the same explicit wiring as `self.shop.plugin`
  in `__init__` -- the exact same gotcha as Phase 2's `shop` group, caught
  immediately this time since it was already a known pattern.
- Initial `unarm` command used `getopts({'static': ''})` for a `--static`
  flag; iterating the resulting `optlist` inside the command body triggered
  an `AssertionError` deep in Limnoria's `commands.py` wrap-converter
  machinery (`assert isinstance(spec, context)`) for reasons not fully
  root-caused. Sidestepped entirely by switching to a plain positional
  `unarm <nick> [static]` argument (`optional('somethingWithoutSpaces')`),
  a pattern already proven throughout this codebase -- avoid `getopts` in
  this plugin unless a future need can't be met positionally.
- A conf-leakage gotcha, same shape as Phase 2's `dropsEnabled` fix: a test
  setting `antifloodMaxPerMinute` to a low value for its own purposes left
  that value in place for every alphabetically-later test (conf is a
  process-global singleton, not reset between test methods), causing
  unrelated multi-purchase/multi-shot tests to get spuriously flood-blocked.
  Fixed the same way -- `antifloodEnabled` defaults to off in `setUp()`,
  and only the two antiflood-specific tests turn it on.
- One test-only artifact: scripting an RNG queue down to exactly the values
  a single `bang()` call consumes, then calling `bang()` a second time in
  the same test, produced an extra stale reply still sitting in the message
  queue after `assertNotError()` consumed the first one -- a timing quirk
  of this exact combination (exhausted `ScriptedRNG` + `threaded = True`
  dispatch) that didn't reproduce with any other test in the suite. Not
  chased further since `_floodCheck`'s own decision logic was verified
  correct via direct instrumentation; worked around with the same
  `_drain()`-before-asserting pattern already used elsewhere in this file.

`test.py` now has 109 tests, all passing via `supybot-test`. **Full parity
achieved** -- no further phases planned. See "Known limitations" in
`README.md` for the handful of deliberate, documented simplifications
(bread's replan timing, nick-fusion's ammo-merge, antiflood's knob count,
the web dashboard's shop page, anti-highlight's glyph set).

## Considered and rejected

- **Configurable level count (e.g. 0-100 levels, funny names, per-network
  choice of how many are "in play").** Discussed 2026-07-26. The blocker
  isn't the per-network config (trivial, would just live in the DB's
  existing per-network record) -- it's that the current 41-row table is
  hand-tuned so level 40 specifically represents "maxed out" (near-100%
  accuracy, minimal jam%). Making level count configurable properly means
  replacing the static table with parametric curves so the last level
  always feels maxed out regardless of N, which is real complexity for
  what's meant to be a simple game. **Decision: not doing this, keep the
  fixed 41-level table as-is.** Don't re-propose without new information.

## Working conventions established for this plugin

- Verify every change with a real `supybot-test` run in a scratch venv +
  isolated plugin dir, not just code review -- see `supybot_plugin_testing`
  memory for the 3 real bugs this caught (builtin `any()` shadowing in
  Blacklist, the `reload` command collision here, a banmask typo in
  Blacklist).
- All game randomness goes through `self._rng`; keep doing this for any new
  probability-driven mechanic (drops, jams, accidents, ricochets) so it
  stays testable with `ScriptedRNG`.
- Scheduled event names: `DuckHuntPro:<kind>:<network>:<channel>:<extra>` --
  keep this convention for new timer types (item expiry, quarterly reset,
  etc.) for consistency and easy debugging via `schedule.schedule.events`.
- `_scheduleEvent`/`_unschedule` already handle the AssertionError-on-reload
  and KeyError-on-remove edge cases -- reuse them rather than calling
  `schedule.addEvent`/`removeEvent` directly.
- Any NEW nested `callbacks.Commands` group (like `shop`, `admin`) needs its
  `plugin` attribute set explicitly in the outer plugin's `__init__`
  (`self.<name>.plugin = self`) -- it is NOT wired up automatically, and
  the failure mode if you forget (`AttributeError: 'NoneType' object has
  no attribute ...`) only shows up at runtime, not at import time.
- Avoid `getopts()` wrap-specs in this plugin (hit an unresolved
  `AssertionError` deep in Limnoria's converter machinery when iterating
  its `optlist` result) -- a plain positional optional argument
  (`optional('somethingWithoutSpaces')`) covers "one optional flag-like
  argument" just fine and is already proven elsewhere in this codebase.
- Conf values are a process-global singleton that persists across test
  methods, not reset per-test -- any test that changes a shared knob
  (`dropsEnabled`, `antifloodEnabled`, etc.) for its own purposes will leak
  that value into every alphabetically-later test. Default the knob to
  "off"/inert in `setUp()` and have only the tests that specifically
  exercise it turn it on, rather than assuming a fresh default each test.
