A nifty channel kick and ban plugin.

Written especially for me, by a username named Kaya on IRC. Extended with a
network-wide blacklist, stable ban IDs, exemption lists, restart-safe timers,
Eggdrop-style ban enforcement, and a few management commands.

### Extended bans (extbans)

Modern ircds (UnrealIRCd, InspIRCd, Solanum/Libera, etc.) support "extended
bans" -- `~account:name`, `$a:name`, `z:fingerprint` and dozens more,
matching on account name, certificate fingerprint, GeoIP country, ASN, other
channels, and more, depending on the ircd/module. Syntax is **not**
standardized across ircds (different prefix characters, different letter
codes for the same concept, InspIRCd doesn't even use a prefix character at
all), and several selectors depend on server-side state (GeoIP, oper class,
live channel membership) this plugin has no way to evaluate locally.

This plugin makes **zero** attempt to parse or interpret extban syntax. Anything
that doesn't look like a plain hostmask is left completely alone:
- `add`/`timer`/`net add`/`net timer`: a mask that starts with `~` or `$`, or
  has a `:` anywhere before its first `@`, is rejected with an explicit error
  ("The banmask specified is incorrect. It must be in the format of
  nick!user@host (ASCII only).") -- set it directly via `/mode` instead.
- Manually-set `+b`/`-b` (the `addManualBans` auto-sync): a mask with no `@`,
  or a `:` before its first `@`, is silently ignored -- no DB entry, no expiry
  timer, no bot-issued unban, ever.

A `:` *after* the `@` (e.g. an IPv6 host like `*!*@2001:db8::1`) is fine and
never flagged -- only a `:` before the `@` triggers this.

### Mask arguments

`add`/`timer`/`net add`/`net timer` take `<nick|mask>`:
- A nick the bot can see is resolved to its real hostmask using the banmask
  template (`maskNumber`/`netMaskNumber`, default 2 = `*!*@host`).
- Anything else is completed the way Eggdrop's `+ban` does: `bob` becomes
  `bob!*@*`, `user@host` becomes `*!user@host`, and `bob!user` becomes
  `bob!user@*`. Each part may contain `*`/`?` wildcards (`bo?*` is fine).
- A full `nick!user@host` is used as given.
- Masks must be plain ASCII. Networks case-map nicks in US-ASCII only, so a
  ban containing non-ASCII characters can't match reliably and is rejected.

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
if `addManualBans` is on: they become entries tagged "manual" and expire after
`banlistExpiry` minutes. Manual unbans are synced back too: a manual entry is
dropped when someone removes its `+b`, while an entry added with `add` or
`timer` is kept (marked lifted) and comes back when a matching mask joins.
Anyone with ops on IRC can do this; only users with `#channel,op` on the bot
can use the commands.

### Per-channel exemptions

```
blacklist exempt add [<channel>] [<nick>] <hostmask>
blacklist exempt remove [<channel>] <nick> [<hostmask>]
blacklist exempt remove [<channel>] <hostmask>
blacklist exempt list [<channel>] [<nick>]
```
Masks are appended one at a time, never replaced. An optional name (usually
the person's nick) groups several masks under one person, so
`exempt add Mimi *!*@a.host` followed by `exempt add Mimi *!*@b.host` leaves
both. `remove <nick> <hostmask>` drops one of them, `remove <nick>` drops all
of that name's masks, and `remove <hostmask>` drops a single mask. `list`
shows `Mimi: *!*@a.host, *!*@b.host | Bob: bob!*@*`, or just one name. Names
are case-insensitive and ASCII, and masks must be plain ASCII too. Lists made
before names existed keep working, with their masks shown unnamed.

Like the ban list, a list longer than `maxInlineEntries` masks is uploaded to
the configured paste service (`pastebinUrl`/`pastebinField`) and answered with
the link; a single name's masks usually fit inline.

Hostmasks on this list can never be added to the channel's blacklist, whether
via `add`/`timer` or auto-detected manual bans. Checked against the *real*
hostmask being banned, not the ban mask pattern, so `exempt add nick!*@*`
protects that user regardless of which `maskNumber` template generated the
ban. The list is the bot's own: it doesn't set `+e` on the channel, so it
stops the *bot* from banning or kicking these users, not the ircd from
enforcing a ban someone else set.

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
blacklist net exemptadd [<nick>] <hostmask>
blacklist net exemptremove <nick> [<hostmask>]
blacklist net exemptremove <hostmask>
blacklist net exemptlist [<nick>]
```
`net add` is permanent and bans/kicks the target immediately in every
enforcing channel; `net timer` is the temporary version. Joins are checked
against the network blacklist before the channel's own list.

## Enforcement (Eggdrop-style)

- **A ban kicks everyone it matches.** `add`, `timer`, `net add` and `net
  timer` kick every member whose hostmask matches the mask (Eggdrop's
  `enforce-bans`), not just the nick you named. The bot itself and exempt
  hostmasks are never kicked.
- **Exempts override bans on join.** A joiner on the channel's exempt list
  (or the network exempt list) is not banned or kicked even if a stored mask
  matches. Network bans honour only the network exempt list.
- **The bot never bans itself.** `add`, `timer`, `net add` and `net timer`
  refuse any mask that matches the bot ("I'm not going to ban myself."). A
  manual `+b` on the channel that matches the bot is removed again at once
  (Eggdrop's `got_ban`) and never recorded; this needs ops. With
  `kickOnSelfBan` on, the person is also dealt with: an IRC op with no account
  on the bot is kicked with `kickOnSelfBanReason`, while a user who has
  `#channel,op` (or `admin`) on the bot is not kicked and just gets that
  message in the channel (or in the command's reply). Server-set modes are
  only undone. "Has the capability" means an explicit capability for a
  hostmask the bot recognises, not Limnoria's default-allow rule.
- **Nick changes are re-checked.** A member who changes into a nick that
  matches a stored mask is banned and kicked, the same as on join. That is
  what makes nick bans like `blacklist add *cunt*` (stored as `*cunt*!*@*`)
  useful. Exempts are honoured here too.
- **Lost bans are re-applied when the bot is opped.** When the bot gains ops
  (or finishes joining already opped), any stored ban that is missing from the
  channel's ban list is set again and its matching members are kicked, like
  Eggdrop's `recheck_bans`. This covers a channel that emptied and was
  recreated, or a ban added while the bot wasn't opped. The network blacklist
  is synced the same way in channels with `enforceGlobal` on.
- **Lifted bans stay lifted until the next join.** An entry whose `+b` was
  lifted by `banlistExpiry`, or removed by an op with `-b`, is marked lifted
  and is *not* re-applied by that resync; it comes back when a matching mask
  joins, as before.

## Restart-safe timers

Every timed ban (`timer`, `add`'s IRC-only lift, manual-ban auto-expiry, `net
timer`) is recorded in the database with its firing time, and re-armed when
the plugin loads. A bot restart no longer leaves a temporary ban stuck
forever — anything that should already have expired by the time the bot comes
back up is lifted immediately on load, everything else is rescheduled for its
original expiry time.

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
# Sets whether to react to someone trying to ban the bot itself. The ban is
# always refused (commands) or removed again at once (a manual +b); this only
# controls the reaction: an IRC op with no account with the bot is kicked,
# while a user with #channel,op (or admin) on the bot just gets the reason
# said in the channel.
#
# Default value: True
###
supybot.plugins.Blacklist.kickOnSelfBan: True
```

```
###
# Sets the kick reason used when someone tries to ban the bot (see
# kickOnSelfBan). Users with #channel,op or admin on the bot are not kicked;
# the bot says this in the channel instead, prefixed with their nick.
#
# Default value: Nice try. The ban hammer doesn't swing at the one holding it.
###
supybot.plugins.Blacklist.kickOnSelfBanReason: Nice try. The ban hammer doesn't swing at the one holding it.
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

Pastebin configuration (used by `list`/`net list` and `exempt list`/`net
exemptlist` when the list is too long to fit inline):
```
###
# Maximum number of ban entries (or exempt masks) to display inline before
# using pastebin.
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

Note: the old "phost" masks (types 3, 4, 8, 9) used to get a stray `p` glued
onto the real host. Root cause: those templates literally contained the text
`*.phost`, and `_createMask`'s placeholder substitution did a plain
`.replace("host", host)` — which also matches the `host` inside `phost`,
turning `*.phost` into `*.p<realhost>`. Fixed by making the templates read
`*.host` like the rest; covered by a regression test
(`testBanmasksMatchEggdrop` in `test.py`).
