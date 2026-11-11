# ChanOnly

Blocks every command in a channel for everyone except owners, admins and
channel ops, optionally keeping a few plugins available to all, e.g. "only
Gemini works in #chat". Other channels and private messages are left alone.

Limnoria's capability system can only approximate this: with
`channel capability setdefault #chan False` you must then grant every command
three times (`gemini`, `chat`, `gemini.chat`) and redo it whenever the plugin
gains a command. ChanOnly works per plugin, using Limnoria's
`pre_command_callbacks` hook.

## Usage

    load ChanOnly
    config channel #chat plugins.ChanOnly.enabled on

That blocks every command in #chat. To keep some plugins available:

    config channel #chat plugins.ChanOnly.allowed "Gemini NuWeather"

Turn it off again: `config channel #chat plugins.ChanOnly.enabled off`.

## Configuration

All values are per channel.

- `plugins.ChanOnly.enabled` (default `False`): turns blocking on.
- `plugins.ChanOnly.allowed` (default empty): plugin names (not command
  names) whose commands everyone may still run, case-insensitive. Empty
  blocks every command.
- `plugins.ChanOnly.exempt` (default `op`): channel capability that lets a
  user run anything anyway, so `op` means `#chat,op`. `""` disables it.
- `plugins.ChanOnly.exemptGlobal` (default `admin`): global capability that
  lets a user run anything anyway. `""` disables it. Owners are always
  exempt.
- `plugins.ChanOnly.notify` (default `True`): reply "Commands are disabled
  in #chat." (or "Only commands from Gemini work in #chat.") when a command
  is blocked. `False` ignores blocked commands silently, useful if the
  channel has other bots sharing your prefix.

## Notes

- Nested commands are checked too: with only Gemini allowed,
  `@chat [echo hi]` is blocked because `echo` belongs to Utilities. The same
  goes for Aka aliases: allow `Aka` and the commands an alias runs are still
  checked one by one.
- Only commands are affected. Things that react to plain messages without
  running a command, such as Web's title snarfer, keep running; turn those
  off with their own per-channel settings. MessageParser triggers do run
  commands, so those commands are checked like any other.
- Commands you run through the bot in private, like
  `config channel #chat …`, are never blocked.
