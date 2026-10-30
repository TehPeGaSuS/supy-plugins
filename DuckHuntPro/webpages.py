"""
The original's web pages (duck_hunt/shop_*.html and progression_table_*.html,
v2.11), served by the web dashboard at /duckhuntpro/shop and
/duckhuntpro/levels, in English or French. The shop shows the prices of the
shopCosts settings and the progression table the levelGrantings table; the
words are the original's, in its HTML.
"""

import html
import urllib.parse

# (name, description) per shop id, in id order.
ITEMS = {
    'en': (
        ('Extra bullet',
         'One bullet is added directly in the gun chamber.'),
        ('Extra clip',
         'One clip is added to your stock.'),
        ('AP ammo<br /> (antiblindage)',
         'Damage x2 for 24h.<br /> Helps killing golden ducks.'),
        ('Explosive ammo',
         'Damage x3 for 24h.<br /> Helps killing golden ducks.'),
        ('Repurchase confiscated gun',
         'Allows you to get your gun back without having to wait.'),
        ('Grease',
         'Reduces the odds of jaming by 50% for 24h and protects from sand once.'),
        ('Sight',
         'Improves accuracy for the next shot by (100 - current accuracy) / 3.'),
        ('Infrared detector',
         'Locks the trigger when there is no duck on sight, thus helping you to save bullets.<br /> Works for 24h, blocks 6 times.'),
        ('Silencer',
         "Muffles most of the noise from your gun for 24h so ducks don't get frightened and escape."),
        ('Four-leaf clover',
         'Win a random XP bonus for each duck you shoot for 24h.<br /> Bonus can be from 1 to 10 and is determined at purchase.'),
        ('Sunglasses',
         'Protects from mirror induced glares for 24h.'),
        ('Spare clothes',
         'Dry set of clothes. Useful when someone poured a bucket of water on you.'),
        ('Brush for gun',
         'Cancels the sabotage and removes sand from your gun.'),
        ('Mirror',
         'Dazzles another player of your choice and make him lose 50% of his accuracy for his next shot.'),
        ('Handful of sand',
         'Throw sand on the gun of another player of your choice, his jamming odds will increase by 50% for the next shot.<br /> Cancels effects from the grease.'),
        ('Water bucket',
         'Throw a bucket of water on the hunter of your choice, forcing him to wait 1h for his clothes to dry before he can hunt again.'),
        ('Sabotage',
         'Sabotage the weapon of another player.<br /> His weapon will jam and explode at his face the next time he press the trigger.'),
        ('Life insurance',
         'Single use insurance policy allowing you to gain a bonus worth 2x the hunter level if you are the victim of a hunting accident for one week.'),
        ('Liability insurance',
         'Divides the XP penality for hunting accidents by 3 for two days.'),
        ('Decoy',
         'Attracts a duck in the next 10 minutes.'),
        ('Piece of bread',
         'Throw pieces of bread to improve the probability of seeing ducks for 1h.<br /> Bread also makes ducks stay 20 seconds longer.<br /> Multiple pieces of bread can be bought to cumulate the effects.'),
        ('Ducks detector',
         'Single use device allowing a hunter to be warned by a notice when the next duck soars.'),
        ('Mechanical duck',
         'Make a prank to other hunters by launching a fake duck. They will not gain any XP from it and lose their ammo.<br /> The duck will be automatically launched 10 minutes after you buy it.'),
    ),
    'fr': (
        ('Balle supplémentaire',
         'Une balle est ajoutée directement dans votre arme.'),
        ('Chargeur supplémentaire',
         'Un chargeur est ajouté à votre réserve de munitions.'),
        ('Munitions AP<br /> (antiblindage)',
         'Dégâts x2 pendant 24h.<br /> Aide à abattre les super-canards.'),
        ('Munitions explosives',
         'Dégâts x3 pendant 24h.<br /> Aide à abattre les super-canards.'),
        ("Rachat d'arme confisquée",
         'Vous permet de récupérer une arme confisquée.'),
        ('Graisse',
         "Réduit de 50% le risque d'enrayement de l'arme pendant 24h et protège (une seule fois) contre une poignée de sable."),
        ('Lunette de visée',
         'Améliore la précision du prochain tir de (100 - précision actuelle) / 3.'),
        ('Détecteur infrarouge',
         "Bloque la gâchette de l'arme quand il n'y a pas de canard dans les environs dans le but d'éviter le gaspillage de munitions pendant 24h.<br /> Fonctionne pour 6 utilisations."),
        ('Silencieux',
         'Réduit considérablement le bruit des tirs pendant 24h afin de ne pas effrayer les canards.'),
        ('Trèfle à 4 feuilles',
         "Vous fait gagner un bonus aléatoire d'xp sur tous les canards que vous tuez pendant 24h.<br /> Ce bonus est déterminé lors de l'achat et peut valoir de 1 à 10."),
        ('Lunettes de soleil',
         "Protège contre l'effet éblouissant du miroir pendant 24h."),
        ('Vêtements de rechange',
         "Annule l'effet du seau d'eau."),
        ('Goupillon',
         "Annule l'effet de la poignée de sable et du sabotage."),
        ('Miroir',
         'Éblouit un chasseur de votre choix pour lui faire perdre 50% de précision lors de son prochain tir.'),
        ('Poignée de sable',
         "Jetez du sable sur l'arme d'un chasseur de votre choix pour lui faire perdre 50% de fiabilité lors de son prochain tir.<br /> Supprime l'effet de la graisse."),
        ("Seau d'eau",
         "Videz un seau d'eau sur un chasseur de votre choix, l'obligeant ainsi à attendre pendant 1h que ses vêtements sèchent avant de pouvoir retourner chasser."),
        ('Sabotage',
         "Sabotez l'arme d'un chasseur de votre choix.<br /> Celle-ci s'enrayera et lui explosera à la figure lors de son prochain tir."),
        ('Assurance vie',
         "Assurance à usage unique permettant de gagner un bonus d'xp équivalent à 2x le niveau du tireur si vous êtes victime d'un accident de chasse pendant 1 semaine."),
        ('Assurance responsabilité civile',
         "Divise par 3 la pénalité d'xp encourue en cas d'accident de chasse pendant 2 jours."),
        ('Appeau',
         'Attire un canard dans les 10 prochaines minutes.'),
        ('Morceau de pain',
         "Jetez des morceaux de pain pour augmenter la probabilité qu'un canard apparaisse pendant 1h.<br /> Le pain augmente aussi de 20s le temps pendant lequel les canards restent avant de partir.<br /> Plusieurs morceaux de pain peuvent être achetés pour en cumuler l'effet."),
        ('Détecteur de canards',
         "Appareil à usage unique permettant d'être averti en notice quand le prochain canard s'envolera."),
        ('Canard mécanique',
         "Faites une bonne blague aux autres chasseurs en lançant un faux canard ne rapportant pas d'xp.<br /> Il sera lancé automatiquement 10mn après l'achat."),
    ),
}

# The weapon shown for each level range (the progression page's labels).
WEAPONS = {
    'en': ((0, 'machine gun'), (7, 'assault rifle'), (16, 'shotgun'), (26, 'precision rifle')),
    'fr': ((0, 'mitrailleuse'), (7, "fusil d'assaut"), (16, 'fusil de chasse'),
           (26, 'fusil de précision')),
}

TEXTS = {
    'en': {
        'shopTitle': 'Duck Hunt - shop',
        'shopHeaders': ('Id', 'Name', 'Description', 'XP cost'),
        'levelsTitle': 'Duck Hunt - levels and bonuses',
        'levelsNote': '<span style="text-decoration: underline;">Note</span> : '
                      'Players begin at level 1 with 0 xp points.<br />',
        'levelsHeaders': ('level', 'required<br />xp', 'weapon', 'accuracy', 'reliability',
                          'ammo<br />/ clip', 'ammo clips', 'armor', 'deflection',
                          'xp penalty<br />/ miss', 'xp penalty<br />/ wild shot',
                          'xp penalty<br />/ accident'),
        'indexTitle': 'Duck Hunt',
        'indexHeaders': ('Network', 'Channel', 'Players', 'Pages'),
        'indexNote': '<a href="/duckhuntpro/shop/en">Shop</a> &nbsp;&middot;&nbsp; '
                     '<a href="/duckhuntpro/levels/en">Levels and bonuses</a>',
        'indexEmpty': 'No game recorded yet.',
        'leaderboard': 'leaderboard', 'champions': 'champions',
        'leaderboardTitle': 'Duck Hunt - leaderboard - %s',
        'leaderboardHeaders': ('#', 'Hunter', 'Level', 'Rank', 'xp', 'Ducks', 'Golden<br />ducks',
                               'Missed<br />shots', 'Wild<br />shots', 'Hunters<br />shot',
                               'Best<br />reflex'),
        'leaderboardEmpty': 'No hunter yet.',
        'championsTitle': 'Duck Hunt - champions - %s',
        'championsNote': 'Final standings of the season that ended on %s.',
        'championsHeaders': ('#', 'Hunter', 'xp', 'Ducks', 'Golden<br />ducks'),
        'championsEmpty': 'No quarterly reset has happened here yet.',
        'home': 'Home',
        'other': 'fr',
        'switch': 'Lisez-le en Français',
    },
    'fr': {
        'shopTitle': 'Duck Hunt - shop',
        'shopHeaders': ('Id', 'Nom', 'Description', 'Coût en xp'),
        'levelsTitle': 'Duck Hunt - niveaux et bonus',
        'levelsNote': '<span style="text-decoration: underline;">Note</span> : '
                      "Les joueurs commencent au niveau 1 avec 0 point d'xp.<br />",
        'levelsHeaders': ('niveau', 'xp<br />requise', 'arme', 'précision', 'fiabilité',
                          'balles<br />/ chargeur', 'chargeurs', 'armure', 'déflexion',
                          "pénalité d'xp<br />tir manqué", "pénalité d'xp<br />tir sauvage",
                          "pénalité d'xp<br />accident"),
        'indexTitle': 'Duck Hunt',
        'indexHeaders': ('Réseau', 'Salon', 'Joueurs', 'Pages'),
        'indexNote': '<a href="/duckhuntpro/shop/fr">Shop</a> &nbsp;&middot;&nbsp; '
                     '<a href="/duckhuntpro/levels/fr">Niveaux et bonus</a>',
        'indexEmpty': 'Aucune partie enregistrée pour le moment.',
        'leaderboard': 'classement', 'champions': 'champions',
        'leaderboardTitle': 'Duck Hunt - classement - %s',
        'leaderboardHeaders': ('#', 'Chasseur', 'Niveau', 'Grade', 'xp', 'Canards',
                               'Canards<br />dorés', 'Tirs<br />manqués', 'Tirs<br />sauvages',
                               'Chasseurs<br />touchés', 'Meilleur<br />réflexe'),
        'leaderboardEmpty': 'Aucun chasseur pour le moment.',
        'championsTitle': 'Duck Hunt - champions - %s',
        'championsNote': 'Classement final de la saison terminée le %s.',
        'championsHeaders': ('#', 'Chasseur', 'xp', 'Canards', 'Canards<br />dorés'),
        'championsEmpty': "Aucune remise à zéro trimestrielle n'a encore eu lieu ici.",
        'home': 'Accueil',
        'other': 'en',
        'switch': 'Read it in English',
    },
}

_PAGE = """<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">
<html lang="%(lang)s">
<head>
	<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
	<meta http-equiv="Content-Language" content="%(lang)s">
 	<meta name="author" content="DuckHuntPro">
 	<meta name="description" content="%(title)s">
 	<title>%(title)s</title>
</head>

<body style="color: rgb(226, 234, 228); background-color: rgb(56, 56, 56); font-family: Ubuntu,sans-serif; font-size: 12px;" alink="#ffb81a" link="#ffd700" vlink="#e2ac09">
	<div style="text-align: right;" lang="%(other)s">%(back)s<a href="%(switchHref)s">%(switch)s</a></div>
	<br />
	<div style="text-align: center; font-weight: bold;">
		<table style="text-align: left; width: 847px; height: 47px; margin-left: auto; margin-right: auto;" border="1" cellpadding="1" cellspacing="1">
  		<tbody>
    		<tr>
      		<td style="vertical-align: middle; background-color: rgb(68, 68, 68); color: rgb(255, 179, 95); text-align: center; height: 5px; font-weight: bold;"><big><big><big>%(title)s</big></big></big></td>
    		</tr>
  		</tbody>
		</table>
	</div>
	<br />
%(note)s	<br />
	<br />
	<table style="background-color: rgb(88, 87, 104);%(width)s text-align: center; vertical-align: middle; margin-left: auto; margin-right: auto;" border="1" cellpadding="4" cellspacing="0">
	  <tbody>
  	  <tr style="text-align: center; vertical-align: middle; background-color: rgb(68, 68, 68);">
%(headers)s    	</tr>
%(rows)s	  </tbody>
	</table>
	<br />
	<br />
	<div style="text-align: center;">
		<font style="font-family: Tahoma; color: rgb(146, 151, 147);" size="-2">DuckHuntPro &nbsp;&middot;&nbsp; Based on Duck Hunt for Eggdrop by Menz Agitat</font>
	</div>
</body>
</html>
"""


def _page(lang, page, title, headers, rows, note='', width=''):
    """`page` is the path under /duckhuntpro/ without the language ('' for
    the index). Every page but the index gets a Home link (to the index, in
    the same language) before the language switch."""
    texts = TEXTS[lang]
    return _PAGE % {
        'lang': lang, 'other': texts['other'], 'switch': texts['switch'],
        'switchHref': '/duckhuntpro/%s%s' % (page + '/' if page else '', texts['other']),
        'back': ('<a href="/duckhuntpro/%s">%s</a> &nbsp;&middot;&nbsp; '
                 % (lang, texts['home']) if page else ''),
        'title': html.escape(title), 'width': width, 'rows': ''.join(rows),
        'note': ('\t<div style="text-align: center;">\n\t\t%s\n\t</div>\n\t<br />\n' % note
                 if note else '\t<br />\n'),
        'headers': ''.join('\t      <th%s>%s</th>\n' % (style, h) for style, h in headers)}


def renderShop(lang, costs):
    """The shop page in `lang` ('en' or 'fr'), `costs` being the 23 prices."""
    texts = TEXTS[lang]
    rows = []
    for number, ((name, description), cost) in enumerate(zip(ITEMS[lang], costs), 1):
        rows.append(
            '\t    <tr>\n\t      <td>%d</td>\n\t      <td>%s</td>\n'
            '\t\t\t\t<td style="text-align: left;">%s</td>\n\t      <td>%s</td>\n\t    </tr>\n'
            % (number, name, description, html.escape(str(cost))))
    styles = (' style="width: 30px;"', ' style="width: 230px;"', ' style="text-align: left;"',
              ' style="width: 90px;"')
    return _page(lang, 'shop', texts['shopTitle'], zip(styles, texts['shopHeaders']), rows,
                 width=' width: 90%;')


def renderLevels(lang, levels):
    """The progression table in `lang` for the level rows `levels` (as
    data.LEVELS): what a level needs is the previous level's threshold."""
    texts = TEXTS[lang]
    weapons = WEAPONS[lang]
    rows = []
    for number, lvl in enumerate(levels):
        required = ('&le; %d' % (lvl.xp_threshold - 1) if number == 0
                    else str(levels[number - 1].xp_threshold))
        weapon = [name for start, name in weapons if number >= start][-1]
        cells = (number, required, weapon, '%d%%' % lvl.accuracy, '%d%%' % (100 - lvl.jam_pct),
                 lvl.clip_size, lvl.clip_count, '%d%%' % lvl.defense, '%d%%' % lvl.deflection,
                 lvl.xp_missed_shot, lvl.xp_wild_shot, lvl.xp_accident)
        rows.append('\t    <tr>\n%s\t    </tr>\n'
                    % ''.join('\t      <td>%s</td>\n' % cell for cell in cells))
    return _page(lang, 'levels', texts['levelsTitle'], (('', h) for h in texts['levelsHeaders']),
                 rows, note=texts['levelsNote'])


def _cells(cells, left=()):
    return '\t    <tr>\n%s\t    </tr>\n' % ''.join(
        '\t      <td%s>%s</td>\n' % (' style="text-align: left;"' if i in left else '', cell)
        for i, cell in enumerate(cells))


def _empty(lang, key, span):
    return '\t    <tr>\n\t      <td colspan="%d">%s</td>\n\t    </tr>\n' % (span, TEXTS[lang][key])


def channelPath(network, channel):
    """The URL path piece for a channel's pages."""
    return '%s/%s' % (urllib.parse.quote(network, safe=''), urllib.parse.quote(channel, safe=''))


def renderIndex(lang, channels):
    """The front page: `channels` is a list of (network, channel, players)."""
    texts = TEXTS[lang]
    rows = []
    for network, channel, players in channels:
        path = channelPath(network, channel)
        links = ('<a href="/duckhuntpro/%s/leaderboard/%s">%s</a> &nbsp;&middot;&nbsp; '
                 '<a href="/duckhuntpro/%s/champions/%s">%s</a>'
                 % (path, lang, texts['leaderboard'], path, lang, texts['champions']))
        rows.append(_cells((html.escape(network), html.escape(channel), players, links), left=(0, 1)))
    if not rows:
        rows.append(_empty(lang, 'indexEmpty', 4))
    return _page(lang, '', texts['indexTitle'], (('', h) for h in texts['indexHeaders']), rows,
                 note=texts['indexNote'])


def renderLeaderboard(lang, network, channel, players):
    """`players` is a list of dicts with rank, nick, level, grade, xp, killed,
    golden, missed, wild, humans and best (the best reflex in seconds, or
    None), already in order."""
    texts = TEXTS[lang]
    rows = []
    for p in players:
        best = '-' if p['best'] is None else '%.3f s' % p['best']
        rows.append(_cells((p['rank'], html.escape(p['nick']), p['level'], html.escape(p['grade']),
                            p['xp'], p['killed'], p['golden'], p['missed'], p['wild'],
                            p['humans'], best), left=(1, 3)))
    if not rows:
        rows.append(_empty(lang, 'leaderboardEmpty', 11))
    return _page(lang, '%s/leaderboard' % channelPath(network, channel),
                 texts['leaderboardTitle'] % channel,
                 (('', h) for h in texts['leaderboardHeaders']), rows)


def renderChampions(lang, network, channel, when, standings):
    """`when` is the season's end as text (None if there was no season yet);
    `standings` the archived (nick, xp, killed, golden) rows in order."""
    texts = TEXTS[lang]
    rows = []
    for rank, (nick, xp, killed, golden) in enumerate(standings, 1):
        rows.append(_cells((rank, html.escape(nick), xp, killed, golden), left=(1,)))
    if not rows:
        rows.append(_empty(lang, 'championsEmpty', 5))
    note = texts['championsNote'] % html.escape(when) if when else ''
    return _page(lang, '%s/champions' % channelPath(network, channel),
                 texts['championsTitle'] % channel,
                 (('', h) for h in texts['championsHeaders']), rows, note=note)
