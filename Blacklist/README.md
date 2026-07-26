A nifty channel kick and ban plugin.

Written especially for me, by a username named Kaya on IRC. Extended with a
network-wide blacklist, stable ban IDs, exemption lists, restart-safe timers,
and a few management commands.

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

Note: the old "phost" masks (types 3, 4, 8, 9) used to get a stray `p` glued
onto the real host. Root cause: those templates literally contained the text
`*.phost`, and `_createMask`'s placeholder substitution did a plain
`.replace("host", host)` — which also matches the `host` inside `phost`,
turning `*.phost` into `*.p<realhost>`. Fixed by making the templates read
`*.host` like the rest; covered by a regression test
(`testBanmasksMatchEggdrop` in `test.py`).
