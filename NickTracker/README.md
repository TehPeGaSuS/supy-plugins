Remembers which nicks were seen from each host on a channel. When a known
host joins (or changes nick) under a nick it has not used before, the bot
announces the other nicks that host has used:

```
[#channel] NewNick also used: OldNick1, OldNick2, OldNick3
```

Based on [NickTracker by Valentin Lorentz (progval)](https://github.com/progval/Supybot-plugins/tree/master/NickTracker),
whose pattern-based keying and announce logic this keeps. Rewritten to use
its own SQLite database (no ChannelLogger needed) and to match the eggdrop
`nicktracker-sqlite.tcl` script feature for feature. Licence: AGPL-3.0, as
the original.

### Setup

```
load NickTracker
config channel #chan plugins.NickTracker.enabled True
config channel #chan plugins.NickTracker.targets "#chan-ops SomeOper"
```

`targets` is where announcements go (channels and/or nicks). People talking
in one of a channel's targets may also use the search commands for it, so a
staff channel works as a "backchan" without any capabilities.

### How users are keyed

By default a user is stored as `*@host`, so a changed ident does not split
one person's history. `specialPatterns` overrides that per `nick!user@host`
mask; the default keeps the ident for IRCCloud users (`uidNNN`/`sidNNN`
identifies the account):

```
config channel #chan plugins.NickTracker.defaultPattern "*@$host"
config channel #chan plugins.NickTracker.specialPatterns "*!uid*@*:$user@$host *!sid*@*:$user@$host"
```

A mask is an IRC-style glob (`*`, `?`, `[...]`). Prefix it with `re:` to use
a Python regex instead, e.g. for cloaked hosts where only a regex can be
precise enough:

```
config channel #chan plugins.NickTracker.specialPatterns "re:^[^!]+![us]id[0-9]+@:$user@$host"
```

Masks are matched case-insensitively. A regex that does not compile is
logged and skipped.

`ignoreHosts` is a list of `user@host` globs that are never recorded nor
announced, e.g. network staff:

```
config channel #chan plugins.NickTracker.ignoreHosts "*@support.network.tld *@*.staff.network.tld"
```

### Announcements

```
plugins.NickTracker.announce.text        "also used"
plugins.NickTracker.announce.others      "other(s)"      (+N other(s) suffix)
plugins.NickTracker.announce.color       True            blue channel, red nicks;
                                                         never on a +c channel
plugins.NickTracker.announce.nicks.perLine   10
plugins.NickTracker.announce.nicks.lines     3           0 = unlimited
plugins.NickTracker.announce.nicks.separator ", "
```

### Commands

| Command | Who | What |
|---|---|---|
| `searchnick [<channel>] <nick>` | admin, channel op, or from a target | other nicks sharing a host with `<nick>` |
| `searchhost [<channel>] <nick>` | same | hosts `<nick>` was seen from |
| `searchmask [<channel>] <mask>` | same | nicks seen from hosts matching `<mask>` (`*`/`?` wildcards; a plain string matches anywhere) |
| `stale [<channel>] <days>` | admin | hosts not seen for `<days>` days (full scan, runs in the background) |
| `importdata <path> [<channel>]` | owner | import old data, see below |

Without `<channel>`, a search from a target channel covers every channel
announcing to it; from a query it covers all tracked channels on the
network. Results list the most recent `searchResults` (default 10) entries.

### Importing old data

`importdata` accepts three formats, all for the current network:

- `*.json` — the database of NickTracker 2.x (`data/NickTracker/nicktracker.json`).
  Keys that are full hostmasks are re-keyed with the current pattern config.
- `nicktrack.db` — the SQLite database of the eggdrop `nicktracker-sqlite.tcl`
  script.
- `<chan>_nicklist.txt` — a file from the flat-file eggdrop script;
  `<channel>` defaults to the one in the file name.

Existing rows are kept. The import runs in the background and may take a
minute for millions of rows.

### Pruning

Every row carries `last_seen` (updated on each join). `stale` tells you how
much is old; pruning is manual, from the sqlite3 shell on
`data/NickTracker/nicktracker.db`:

```sql
DELETE FROM nicktrack WHERE last_seen < strftime('%s','now') - 180*86400;
VACUUM;
```
