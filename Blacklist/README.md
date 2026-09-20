A nifty channel kick and ban plugin.

Written especially for me, by a username named Kaya on IRC. Extended with a
network-wide blacklist, stable ban IDs, exemption lists, restart-safe timers,
a word/text filter with an escalating warn/kick/ban/kickban ladder, and a
few management commands.

### Extended bans (extbans)

Modern ircds (UnrealIRCd, InspIRCd, Solanum/Libera, etc.) support "extended
bans" -- `~account:name`, `$a:name`, `z:fingerprint` and dozens more,
matching on account name, certificate fingerprint, GeoIP country, ASN, other
channels, and more, depending on the ircd/module. Syntax is **not**
standardized across ircds (different prefix characters, different letter
codes for the same concept, InspIRCd doesn't even use a prefix character at
all), and several selectors depend on server-side state (GeoIP, oper class,
live channel membership) this plugin has no way to evaluate locally.

This plugin makes **zero** attempt to parse or interpret extban syntax. Any
mask that either has no `@`, or has a `:` anywhere before its first `@`, is
treated as "not a plain hostmask" and left completely alone:
- `add`/`timer`/`net add`/`net timer`: rejected with an explicit error
  ("The banmask specified is incorrect. It must be in the format of
  nick!user@host.") -- set it directly via `/mode` instead.
- Manually-set `+b`/`-b` (the `addManualBans` auto-sync): silently ignored --
  no DB entry, no expiry timer, no bot-issued unban, ever.

A `:` *after* the `@` (e.g. an IPv6 host like `*!*@2001:db8::1`) is fine and
never flagged -- only a `:` before the `@` triggers this.

## Channel blacklist

```
blacklist add [<channel>] <nick|mask> [<reason>]
```
Adds a mask to the channel's blacklist: permanent in the database, banned in
IRC. If `banlistExpiry` is set, the IRC-side `+b` is lifted after that many
minutes, but the blacklist entry itself is kept forever (it'll be re-applied
the next time that mask joins).

```
blacklist timer [<channel>] <nick|mask> [<minutes>] [<reason>]
```
Applies a temporary ban: both the IRC `+b` and the blacklist entry are
removed together once it expires (`banTimerExpiry` minutes if none given).

```
blacklist delete [<channel>] <mask|ID>
blacklist list [<channel>]
blacklist search [<channel>] <pattern>
blacklist reason [<channel>] <mask|ID> <reason>
blacklist extend [<channel>] <mask|ID> <minutes>
blacklist stats [<channel>]
blacklist clear <channel> confirm
blacklist kick [<channel>] <nick> [<reason>]
blacklist bantype
```
`list` shows each entry's stable numeric ID (used by `delete`/`reason`/
`extend` — the ID never shifts when other entries are added or removed, so
scripts and muscle memory both stay valid). `search` matches the mask, adder
or reason against `<pattern>`. `extend` sets/refreshes an entry's expiry to
`<minutes>` from now (removes it fully, IRC + list, when it fires). `clear`
wipes every entry for a channel and lifts every ban it applied — you must
literally pass the word `confirm` to run it.

Manual bans set directly on IRC (not via the bot) are picked up automatically
if `addManualBans` is on, and manual unbans are synced back the same way — see
`addManualBans` below for the exact semantics.

### Per-channel exemptions

```
blacklist exempt add [<channel>] <hostmask>
blacklist exempt remove [<channel>] <hostmask>
blacklist exempt list [<channel>]
```
Hostmasks on this list can never be added to the channel's blacklist, whether
via `add`/`timer` or auto-detected manual bans. Checked against the *real*
hostmask being banned, not the ban mask pattern, so `exempt add nick!*@*`
protects that user regardless of which `maskNumber` template generated the
ban.

## Network-wide blacklist

A second blacklist, independent of any one channel, enforced in every channel
that has `enforceGlobal` on. Requires the `admin` capability (not just
channel op), since it affects every channel the bot is in.

```
blacklist net add <nick|mask> [<reason>]
blacklist net timer <nick|mask> [<minutes>] [<reason>]
blacklist net delete <mask|ID>
blacklist net list
blacklist net search <pattern>
blacklist net clear confirm
blacklist net exemptadd <hostmask>
blacklist net exemptremove <hostmask>
blacklist net exemptlist
```
`net add` is permanent and bans/kicks the target immediately in every
enforcing channel; `net timer` is the temporary version. Joins are checked
against the network blacklist before the channel's own list.

## Word/text filter

Filters channel messages against configured word/phrase patterns, with an
escalating ladder of actions per offending hostmask. Off by default per
channel (`wordFilterEnabled`).

```
blacklist word add [<channel>] [--type simple|regex] --action <chain> [--cooldown <minutes>] [--expiry <minutes>] [--reason <text>] <pattern>
blacklist word delete [<channel>] <pattern|ID>
blacklist word list [<channel>]
blacklist word search [<channel>] <pattern>
```
Network-wide equivalents (require `admin`, enforced in every channel with
`wordFilterEnabled` on, checked together with the channel's own list):
```
blacklist net wordadd [--type simple|regex] --action <chain> [--cooldown <minutes>] [--expiry <minutes>] [--reason <text>] <pattern>
blacklist net worddelete <pattern|ID>
blacklist net wordlist
blacklist net wordsearch <pattern>
```

**`--action`** is a comma-separated escalation chain. Each step must be one
of `warn`, `kick`, `ban`, `kickban`, and the chain **must strictly escalate**
through that order -- `kick,kickban` is valid, `kickban,kick` is rejected
(a later offense can never be milder than an earlier one). A single action
(e.g. `--action kick`) is also valid. Offense N (since the escalation
counter last reset) picks the Nth step, clamped to the last step once the
chain is exhausted -- e.g. with `warn,kick,kickban`, the 1st offense warns,
the 2nd kicks, the 3rd (and every one after) kickbans.

**`--type`** (default `simple`): `simple` is a glob (`*word*`) or plain
substring match via `fnmatch` -- fast, but reintroduces the classic
"Scunthorpe problem" (flags substrings inside innocent words, e.g.
`*ass*` matching "assassin"); this plugin makes no attempt to avoid that for
`--type simple`, the risk is accepted as a tradeoff for simplicity. `regex`
uses `re.search` -- use word boundaries (e.g. `\bfuck\b`) to avoid the same
problem.

**Escalation counters** are per-channel, per-offending-hostmask (`*!user@host`
from the message's own sender, not the nick -- so a nick change doesn't reset
or dodge the ladder), kept in memory only (not persisted across a bot
restart, same as any flood-style counter). **`--cooldown`** (default
`wordCooldown`) is how many minutes of silence since that hostmask's last
offense on *this entry* before its counter resets back to step 1 -- this is
independent from the ban duration below. Once the chain reaches `ban` or
`kickban`, the counter resets immediately instead of waiting on the
cooldown (the offender can't send another message until unbanned anyway),
so they start fresh at step 1 whenever they return.

**`--expiry`** (default `wordBanExpiry`) is the number of minutes before a
ban that a word entry's `ban`/`kickban` step applied is lifted -- a
*different* setting from `banlistExpiry`/`banTimerExpiry`, which only
govern manually-added mask bans. A `ban`/`kickban` firing from a word entry
is recorded and auto-expired through the exact same restart-safe timer
machinery as any other ban (see below), so it shows up in `blacklist list`
like any other entry.

**`--reason`** is optional: without it, each step falls back to its own
configured default message (`wordWarnMessage`/`wordKickMessage`/
`wordKickbanMessage` below). When given, it may be a single reason for every
step, or a `|`-delimited chain aligned with `--action` (one reason per step,
clamped the same way as the action chain once exhausted), e.g.
`--reason "Mind your language.|Warned already.|Cool off and come back later."`
Used as the kick/kickban reason, and substituted for `$reason` in the warn
message. `warn` never touches IRC bans/kicks -- it just sends
`wordWarnMessage` (`$nick`/`$reason` substituted) to the channel. The bare
`ban` step (no kick) never puts a reason anywhere user-visible -- there's no
wire mechanism for a `+b` to carry one on any ircd, unlike `kickban` which
visibly kicks with one. It still gets an internal-only DB reason (its own
`--reason`, or `blacklisted word: <pattern>` by default) purely so it shows
up sensibly in `blacklist list`/`search` instead of looking unexplained --
this is never sent over IRC, exactly like every other ban's reason.

Since a word entry has no configured mask (only a matched text pattern), a
`ban`/`kickban` step auto-generates one from the offender's own hostmask
(ident's leading `~` stripped to `*`), using the `wordMaskNumber` banmask
template (see `Banmask types` below).

Exemptions are shared with the mask blacklist: a hostmask on `exempt`/`net
exemptadd` is skipped by the word filter too.

## Restart-safe timers

Every timed ban (`timer`, `add`'s IRC-only lift, manual-ban auto-expiry, `net
timer`, a word entry's `ban`/`kickban` step) is recorded in the database with
its firing time, and re-armed when the plugin loads. A bot restart no longer
leaves a temporary ban stuck forever — anything that should already have
expired by the time the bot comes back up is lifted immediately on load,
everything else is rescheduled for its original expiry time.

Word-filter *escalation counters* (not bans -- the offense-count-per-hostmask
state used to pick the next action) are the one exception: they're
transient, in-memory only, and reset on a bot restart, same as any
flood-style counter in eggdrop or similar bots.

## Configuration

```
###
# Set whether to enable database in a channel.
#
# Default value: False
###
supybot.plugins.Blacklist.enabled: True
```
Needs to be `True` for the channel blacklist (`add`/`timer`/`doJoin`
enforcement) to do anything in that channel.

```
###
# Sets whether to watch for channel bans directly added by users (not
# using the bot) to the database.
#
# Default value: True
###
supybot.plugins.Blacklist.addManualBans: True
```

```
###
# Sets whether this channel enforces the network-wide (net) blacklist.
#
# Default value: True
###
supybot.plugins.Blacklist.enforceGlobal: True
```

```
###
# Sets the number of minutes before a ban is removed from the channel's
# banlist.
#
# Default value: 180
###
supybot.plugins.Blacklist.banlistExpiry: 180
```

```
###
# Sets the numer of minutes before a timed ban expires if none is given.
#
# Default value: 30
###
supybot.plugins.Blacklist.banTimerExpiry: 30
```

```
###
# Sets the number of minutes before a "net timer" ban expires if none is
# given.
#
# Default value: 30
###
supybot.plugins.Blacklist.netTimerExpiry: 30
```

See `Banmask types` below.
```
###
# Sets the default banmask number if none is given.
#
# Default value: 2
###
supybot.plugins.Blacklist.maskNumber: 2
```

```
###
# Sets the default banmask number used for network-wide (net) blacklist
# entries.
#
# Default value: 2
###
supybot.plugins.Blacklist.netMaskNumber: 2
```

Banmask types (0-9 match Eggdrop's own banmask types; 10 is an extra this
plugin adds):
```
0: '*!ident@host',
1: '*!*ident@host',
2: '*!*@host',
3: '*!*ident@*.host',
4: '*!*@*.host',
5: 'nick!ident@host',
6: 'nick!*ident@host',
7: 'nick!*@host',
8: 'nick!*ident@*.host',
9: 'nick!*@*.host',
10: '*!ident@*'
```

```
###
# Sets the default blacklist message if none is given.
#
# Default value: User has been banned from the channel.
###
supybot.plugins.Blacklist.banReason: User has been banned from the channel.
```

Pastebin configuration (used by `list`/`net list` when the ban list is too
long to fit inline):
```
###
# Maximum number of ban entries to display inline before using pastebin.
#
# Default value: 5
###
supybot.plugins.Blacklist.maxInlineEntries: 5
```

```
###
# URL of the paste service for large ban lists.
# Must accept multipart/form-data POST and return a plain URL.
#
# Default value: https://filehost.0bin.xyz/
###
supybot.plugins.Blacklist.pastebinUrl: https://filehost.0bin.xyz/
```

```
###
# Form field name expected by the paste service.
# Use 'file' for single_php_filehost / 0x0-style services.
# Use 'content' for dpaste.com (also append .txt to the returned URL manually).
#
# Default value: file
###
supybot.plugins.Blacklist.pastebinField: file
```

Word filter configuration:
```
###
# Sets whether the word/text blacklist (see "word") is enforced in this
# channel.
#
# Default value: False
###
supybot.plugins.Blacklist.wordFilterEnabled: True
```

```
###
# Sets the default number of minutes of silence (no new offense) before a
# user's escalation ladder for a word entry resets back to its first step.
#
# Default value: 2
###
supybot.plugins.Blacklist.wordCooldown: 2
```

```
###
# Sets the default number of minutes before a ban that was auto-applied by
# a word entry's "ban"/"kickban" step is lifted.
#
# Default value: 120
###
supybot.plugins.Blacklist.wordBanExpiry: 120
```

```
###
# Sets whether word entries match case-sensitively.
#
# Default value: False
###
supybot.plugins.Blacklist.wordCaseSensitive: False
```

```
###
# Sets the banmask number used to build the ban mask when a word entry's
# chain reaches "ban"/"kickban" (see Banmask types above).
#
# Default value: 2
###
supybot.plugins.Blacklist.wordMaskNumber: 2
```

```
###
# Sets the message used for a word entry's "warn" step (sent to the
# channel). $nick and $reason are substituted.
#
# Default value: $nick, mind your language in this channel.
###
supybot.plugins.Blacklist.wordWarnMessage: $nick, mind your language in this channel.
```

```
###
# Sets the default kick reason for a word entry's "kick" step, used when
# the entry has no explicit --reason.
#
# Default value: You've been told to mind your language in this channel.
###
supybot.plugins.Blacklist.wordKickMessage: You've been told to mind your language in this channel.
```

```
###
# Sets the default kick reason for a word entry's "kickban" step, used
# when the entry has no explicit --reason.
#
# Default value: Go get some air and return when you can mind your language.
###
supybot.plugins.Blacklist.wordKickbanMessage: Go get some air and return when you can mind your language.
```

Note: the old "phost" masks (types 3, 4, 8, 9) used to get a stray `p` glued
onto the real host. Root cause: those templates literally contained the text
`*.phost`, and `_createMask`'s placeholder substitution did a plain
`.replace("host", host)` — which also matches the `host` inside `phost`,
turning `*.phost` into `*.p<realhost>`. Fixed by making the templates read
`*.host` like the rest; covered by a regression test
(`testBanmasksMatchEggdrop` in `test.py`).
