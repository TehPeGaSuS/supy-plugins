A nifty channel kick and ban plugin.

Written especially for me, by a a username named Kaya on IRC.

You can customize it almost as you like, here is your options:

```
###
# Sets whether to watch for channel bans directly added by users (not
# using the bot) to the database.
#
# Default value: True
###
supybot.plugins.Blacklist.addManualBans: True
```

Needs to be `True` in order to work
```
###
# Set whether to enable database in a channel.
#
# Default value: False
###
supybot.plugins.Blacklist.enabled: True
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
# Sets the default blacklist message if none is given.
#
# Default value: User has been kicked from the channel.
###
supybot.plugins.Blacklist.kickReason: User has been kicked from the channel.
```

See `Banmask types` below
```
###
# Sets the default banmask number if none is given.
#
# Default value: 2
###
supybot.plugins.Blacklist.maskNumber: 2
```

Banmask types:
```
0: '*!ident@host',
1: '*!*ident@host',
2: '*!*@host',
3: '*!*ident@*.phost',
4: '*!*@*.phost',
5: 'nick!ident@host',
6: 'nick!*ident@host',
7: 'nick!*@host',
8: 'nick!*ident@*.phost',
9: 'nick!*@*.phost',
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



Note: I'm having some issues with the `phost` masks where a `p` is added to the mask. I'll ask for a fix if I see the user again. (This is probably fixed with commit [1804a3d](https://github.com/TehPeGaSuS/supy-plugins/commit/1804a3d8b9307c46317a516b4091d3c32749ba63))
