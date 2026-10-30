# Slapper

`!slap [<nick>]` for Limnoria. The bot picks a random phrase and sends it as
a `/me` action.

- `slap bob` slaps bob. Anything goes as the target: `slap the moon`.
- `slap` with nothing slaps you.
- Slapping the bot slaps you instead.

The plugin is called Slapper, not Slap, so `slap list` slaps someone named
"list" instead of being read as a plugin command.

## Usage

    load Slapper
    slap bob
    slaps add slaps $nick around a bit with $fish
    slaps var add fish a large trout

| Command | Who | What it does |
|---|---|---|
| `slap [<nick>]` | anyone | Slaps `<nick>`, or you. |
| `slaps add <phrase>` | manager | Adds a phrase. It must contain `$nick`. |
| `slaps del <nr>` | manager | Removes phrase `<nr>` (`slaps delete` works too). |
| `slaps list` | anyone | Lists the phrases, numbered. |
| `slaps var add <name> <value>` | manager | Adds a value to a variable. |
| `slaps var del <name> [<nr>]` | manager | Removes one value, or the whole variable. |
| `slaps var list [<name>]` | anyone | Lists the variables, or one variable's values. |

"Manager" means the `manageCapability` capability, `admin` by default.
Owners always pass.

## Variables

Built in:

| Variable | Value |
|---|---|
| `$nick` | Who gets slapped. |
| `$who` | Who asked for the slap. |
| `$channel` | The channel. |
| `$botnick` | The bot's nick. |
| `$randnick` | A random user of the channel, never the bot. |

Your own variables are lists. `$fish` picks a random value of the variable
`fish` each time. A value can use other variables, a few levels deep:

    slaps var add size large
    slaps var add size tiny
    slaps var add fish a $size trout
    slaps add slaps $nick around a bit with $fish

Names are case-insensitive, made of letters, digits and `_`, and can't start
with a digit or reuse a built-in name. An unknown `$name` is left as it is.

On first start the plugin comes with four classic phrases and the `$fish`
and `$object` variables. Everything lives in `<data>/Slapper/slaps.json` and
is shared by all channels and networks.

## Configuration

| Setting | Scope | Default | Meaning |
|---|---|---|---|
| `enabled` | channel | `True` | Whether `slap` works in the channel. |
| `manageCapability` | global | `admin` | Capability needed to change phrases and variables. |
