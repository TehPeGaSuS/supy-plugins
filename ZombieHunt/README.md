The classic game of IRC Zombie Hunt.

Based on oddluck's DuckHunt game

Requires Python3, Limnoria.

Python 3 and score fixes. Plugin working.

[O.o] ~ ZombieHunt game for supybot ~ [o.O]
=======================================

How to play
-----------
 * Use the "starthunt" command to start a game.
 * The bot will randomly launch zombies. Whenever a zombie is launched, the first person to use the "bang" command wins a point. 
 * Using the "bang" command when there is no zombie launched costs a point.
 * Using the "bang" command two or more times while reloading costs a point.
 * If a player shoots all the zombies during a hunt, it's a perfect! This player gets extra bonus points.
 * The best scores for a channel are recorded and can be displayed with the "listscores" command.
 * The quickest and longest shoots are also recorded and can be displayed with the "listtimes" command.
 * The "launched" command tells if there is currently a zombie to shoot.

How to install
--------------
Just place the ZombieHunt plugin in the plugins directory of your supybot installation and load the module.

How to configure
----------------
Several per-channel configuration variables are available (look at the "channel" command to learn more on how to configure per-channel configuration variables):
 * autoRestart: Does a new hunt automatically start when the previous one is over?
 * zombies: Number of zombies during a hunt?
 * minthrottle: The minimum amount of time before a new zombie may be launched (in seconds)
 * maxthrottle: The maximum amount of time before a new zombie may be launched (in seconds)
 * reloadTime: The time it takes to reload your rifle once you have shot (in seconds)
 * kickMode: If someone shoots when there is no zombie, should he be kicked from the channel? (this requires the bot to be op on the channel)
 * autoFriday: Do we need to automatically launch more zombies on friday?
 * missProbability: The probability to miss the zombie
