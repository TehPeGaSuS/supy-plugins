# Perform

ZNC's `*perform` for Limnoria, plus nick recovery. Per network, the bot keeps
a numbered list of raw IRC lines and sends them, in order, every time it
connects (after the end of the MOTD). A second list says what to send when
the bot's configured nick is held by someone else, before asking for it back.

Why not the `Services` plugin? It only knows NickServ/ChanServ and one way
of talking to them. A perform list sends whatever the network needs:
`PRIVMSG NickServ@services.dal.net :IDENTIFY ...`, `AUTH` to Q, `OPER`,
`MODE %nick% +B`, a `PRIVMSG` to an ops channel, in the order you choose.

All commands need the `owner` capability. The lists live in
`<data>/Perform/perform.json`, so they survive reloads and restarts.

## Usage

    load Perform
    perform add PRIVMSG NickServ :IDENTIFY hunter2
    perform add MODE %nick% +B
    perform list
    perform execute

| Command | What it does |
|---|---|
| `perform add [<network>] <raw line>` | Appends a line to the perform list. |
| `perform del [<network>] <nr>` | Removes entry `<nr>` (`perform delete` works too). |
| `perform list [<network>]` | Lists the entries, numbered, in private (they tend to hold passwords). |
| `perform swap [<network>] <nr> <nr>` | Swaps two entries. |
| `perform delall [<network>]` | Empties the list. |
| `perform execute [<network>]` | Sends the list now, as if the bot had just connected. |

`<network>` defaults to the network the command is given on.

Variables in the lines: `%nick%` is the bot's current nick, `%wantnick%` its
configured nick, `%network%` the network name.

## Nick recovery

When the bot is connected under another nick than the one configured for the
network (`supybot.networks.<network>.nick`, else `supybot.nick`), it sends
the nick-recovery lines, then `NICK <configured nick>`, and repeats every
`nickRecoverInterval` seconds, `nickRecoverTries` times (then it gives up and
logs it). Whenever the holder of the nick quits or changes nick, the bot
tries again at once, even after giving up. In the nick-recovery lines,
`%nick%` is the nick being recovered.

    nickrecover add PRIVMSG NickServ :GHOST %nick% hunter2
    nickrecover add PRIVMSG NickServ :RELEASE %nick% hunter2

The group is its own command: `nickrecover add` and `perform nickrecover add`
are the same thing, so the two lists read as `perform ...` and
`nickrecover ...`.

Atheme users want `REGAIN`, Anope users `RECOVER`; DALnet needs `GHOST`
(the bot then renames itself) and the usual `IDENTIFY` in the perform list.

| Command | What it does |
|---|---|
| `nickrecover add [<network>] <raw line>` | Appends a nick-recovery line. |
| `nickrecover del [<network>] <nr>` | Removes entry `<nr>`. |
| `nickrecover list [<network>]` | Lists the lines (in private). |
| `nickrecover delall [<network>]` | Empties the list. |
| `nickrecover execute [<network>]` | Sends the lines and asks for the nick right now, even after giving up, and restarts the timed attempts. |
| `nickrecover status [<network>]` | Current nick, wanted nick, attempts so far. |

## Configuration

All values are per network (`config network <net> ...` or
`config supybot.plugins.Perform.<name>` for the default).

| Setting | Default | Meaning |
|---|---|---|
| `enabled` | `True` | Send the perform list on connect. |
| `delay` | `0` | Seconds to wait after the end of the MOTD before sending it. |
| `nickRecoverEnabled` | `True` | Try to get the configured nick back. |
| `nickRecoverInterval` | `300` | Seconds between timed attempts. |
| `nickRecoverTries` | `12` | Timed attempts per connection before giving up; `0` = never give up. |

The perform list is sent with `sendMsg`, in the order given: Limnoria's
normal queue would move `MODE` lines ahead of `PRIVMSG` ones.
