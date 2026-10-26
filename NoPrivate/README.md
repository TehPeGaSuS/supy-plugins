# NoPrivate

Silently ignores private messages (commands included) from everyone except
admins and owners. Channel messages, notices and server messages are left
alone, so NickServ/Services keep working.

Limnoria's capability system can't do this by itself: anticapabilities are
checked before the channel, so `-command` blocks it in channels too, and
`supybot.capabilities.default False` locks unregistered users out everywhere.

## Usage

    load NoPrivate

## Configuration

- `plugins.NoPrivate.capability` (default `admin`): capability needed for the
  bot to accept someone's private messages. Owners always pass.
- `plugins.NoPrivate.allowedCommands` (default `identify`): commands anyone may
  still send in private, so admins can identify before the bot recognises
  them. Matched against the first two words, so `identify` and
  `user identify` both pass. Not needed if your admins are matched by
  hostmask or services account.

Private CTCP (VERSION, PING) is dropped too.
