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
        ('Golden magnet',
         'Golden ducks are twice as likely to appear on the channel for 12h, for every hunter.<br /> Buying one while another is active adds 12h to it.'),
        ('Golden feather',
         'Single use: your next kill of an ordinary duck pays as much xp as a golden duck.<br /> It still counts as an ordinary duck in your stats.'),
        ('Mirror shield',
         'For 24h, a mirror or a handful of sand thrown at you hits the thrower instead.'),
        ('Bribed ranger',
         'For 12h, the park ranger waives your xp penalties for hunting accidents and wild fire.<br /> Weapon confiscations still apply.'),
        ('Drunk Snowman',
         'Snowman, the village drunk, scares off the next duck before anyone can shoot it, you included.<br /> Once he has, nobody on the channel can hire him again for a while.'),
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
        ('Aimant doré',
         "Les canards dorés ont deux fois plus de chances d'apparaître sur le salon pendant 12h, pour tous les chasseurs.<br /> En acheter un pendant qu'un autre est actif le prolonge de 12h."),
        ('Plume dorée',
         "Usage unique : votre prochain canard ordinaire abattu rapporte autant d'xp qu'un canard doré.<br /> Il compte toujours comme un canard ordinaire dans vos statistiques."),
        ('Bouclier miroir',
         "Pendant 24h, un miroir ou une poignée de sable qu'on vous lance revient sur le lanceur."),
        ('Garde-chasse soudoyé',
         "Pendant 12h, le garde-chasse annule vos pénalités d'xp pour accident de chasse et tir sauvage.<br /> Les confiscations d'arme s'appliquent toujours."),
        ('Snowman ivre',
         "Snowman, l'ivrogne du village, fait fuir le prochain canard avant que quiconque puisse tirer, vous compris.<br /> Ensuite, personne sur le salon ne peut l'engager à nouveau pendant un moment."),
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
        'whatTitle': 'Duck Hunt - what is it?',
        'indexTitle': 'Duck Hunt',
        'indexHeaders': ('Network', 'Channel', 'Players', 'Pages'),
        'indexNote': '<a href="/duckhuntpro/whatis/en">What is Duck Hunt?</a> &nbsp;&middot;&nbsp; '
                     '<a href="/duckhuntpro/shop/en">Shop</a> &nbsp;&middot;&nbsp; '
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
        'whatTitle': "Duck Hunt - qu'est-ce que c'est ?",
        'indexTitle': 'Duck Hunt',
        'indexHeaders': ('Réseau', 'Salon', 'Joueurs', 'Pages'),
        'indexNote': '<a href="/duckhuntpro/whatis/fr">Qu\'est-ce que Duck Hunt ?</a> &nbsp;&middot;&nbsp; '
                     '<a href="/duckhuntpro/shop/fr">Shop</a> &nbsp;&middot;&nbsp; '
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
 	<meta name="viewport" content="width=device-width, initial-scale=1">
 	<title>%(title)s</title>
	<style type="text/css">
	body { color: rgb(226, 234, 228); background-color: rgb(56, 56, 56); font-family: Ubuntu,sans-serif; font-size: 12px; }
	a:link { color: #ffd700; } a:visited { color: #e2ac09; } a:active { color: #ffb81a; }
	.title { text-align: left; width: 847px; max-width: 100%%; height: 47px; margin-left: auto; margin-right: auto; }
	.scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
	.data { background-color: rgb(88, 87, 104); text-align: center; vertical-align: middle; margin-left: auto; margin-right: auto; }
	.data td { overflow-wrap: break-word; }
	.text { max-width: 847px; margin-left: auto; margin-right: auto; font-size: 13px; line-height: 1.5; }
	.text h2 { color: rgb(255, 179, 95); font-size: 16px; margin: 1.6em 0 0.4em; border-bottom: 1px solid rgb(100, 100, 100); }
	.text p, .text ul { margin: 0.4em 0 0.8em; }
	.text li { margin-bottom: 0.3em; }
	.text code { color: rgb(255, 215, 0); font-family: monospace; font-size: 13px; }
	.text .data { margin: 0.6em auto 1em; }
	@media (max-width: 640px) {
		body { font-size: 14px; margin: 8px; }
		.title big { font-size: 110%%; }
		.data { width: 100%% !important; }
		.data th { width: auto !important; }
		.data th, .data td { padding: 3px; }
		.wide td { white-space: nowrap; }
		.wide td:first-child, .wide th:first-child { position: sticky; left: 0; background-color: rgb(88, 87, 104); }
		.pin2 td:first-child, .pin2 th:first-child { box-sizing: border-box; width: 2.6em; min-width: 2.6em; }
		.pin2 td:nth-child(2), .pin2 th:nth-child(2) { position: sticky; left: 2.6em; background-color: rgb(88, 87, 104); }
		.wide th:first-child, .pin2 th:nth-child(2) { background-color: rgb(68, 68, 68); }
	}
	</style>
</head>

<body alink="#ffb81a" link="#ffd700" vlink="#e2ac09">
	<div style="text-align: right;" lang="%(other)s">%(back)s<a href="%(switchHref)s">%(switch)s</a></div>
	<br />
	<div style="text-align: center; font-weight: bold;">
		<table class="title" border="1" cellpadding="1" cellspacing="1">
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
%(content)s	<br />
	<br />
	<div style="text-align: center;">
		<font style="font-family: Tahoma; color: rgb(146, 151, 147);" size="-2">DuckHuntPro &nbsp;&middot;&nbsp; Based on Duck Hunt for Eggdrop by Menz Agitat</font>
	</div>
</body>
</html>
"""


_TABLE = """	<div class="scroll">
	<table class="data%(wide)s"%(width)s border="1" cellpadding="4" cellspacing="0">
	  <tbody>
  	  <tr style="text-align: center; vertical-align: middle; background-color: rgb(68, 68, 68);">
%(headers)s    	</tr>
%(rows)s	  </tbody>
	</table>
	</div>
"""


def _table(headers, rows, width='', wide=False):
    """A data table: `headers` are (style, text) pairs, `rows` its <tr>s."""
    return _TABLE % {
        'rows': ''.join(rows),
        'width': ' style="width: %s;"' % width if width else '',
        'wide': {False: '', True: ' wide', 2: ' wide pin2'}[wide],
        'headers': ''.join('\t      <th%s>%s</th>\n' % (style, h) for style, h in headers)}


def _page(lang, page, title, headers, rows, note='', width='', wide=False, content=None):
    """`page` is the path under /duckhuntpro/ without the language ('' for
    the index). Every page but the index gets a Home link (to the index, in
    the same language) before the language switch. A `wide` table keeps its
    cells on one line on phones and scrolls sideways instead, its first
    column pinned (its first two with wide=2). With `content` (HTML), that
    replaces the table."""
    texts = TEXTS[lang]
    return _PAGE % {
        'lang': lang, 'other': texts['other'], 'switch': texts['switch'],
        'switchHref': '/duckhuntpro/%s%s' % (page + '/' if page else '', texts['other']),
        'back': ('<a href="/duckhuntpro/%s">%s</a> &nbsp;&middot;&nbsp; '
                 % (lang, texts['home']) if page else ''),
        'title': html.escape(title),
        'content': (content if content is not None
                    else _table(headers, rows, width=width, wide=wide)),
        'note': ('\t<div style="text-align: center;">\n\t\t%s\n\t</div>\n\t<br />\n' % note
                 if note else '\t<br />\n')}


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
                 width='90%')


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
                 rows, note=texts['levelsNote'], wide=True)


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
                 (('', h) for h in texts['leaderboardHeaders']), rows, wide=2)


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


def _span(values, suffix=''):
    """'a' or 'a&ndash;b' for the smallest and largest of `values`."""
    low, high = min(values), max(values)
    return ('%d%s' % (low, suffix) if low == high
            else '%d%s&ndash;%d%s' % (low, suffix, high, suffix))


def _levelSpan(first, last):
    return str(first) if first == last else '%d&ndash;%d' % (first, last)


def _groups(levels, keyOf):
    """Consecutive runs of levels 1.. sharing keyOf(level): (first, last)."""
    runs = []
    for number in range(1, len(levels)):
        key = keyOf(number)
        if runs and runs[-1][2] == key:
            runs[-1][1] = number
        else:
            runs.append([number, number, key])
    return [(first, last) for first, last, _ in runs]


def _duration(seconds, lang):
    if seconds % 60:
        return '%d s' % seconds
    minutes = seconds // 60
    if lang == 'fr':
        return '%d minute%s' % (minutes, 's' if minutes > 1 else '')
    return '%d minute%s' % (minutes, 's' if minutes != 1 else '')


WHATIS_HEADERS = {
    'en': {
        'weapons': ('levels', 'weapon', 'accuracy', 'reliability', 'armor', 'deflection',
                    'ammo<br />/ clip', 'clips<br />/ day'),
        'penalties': ('levels', 'missed shot', 'wild shot', 'per person hit'),
        'accidents': ('people on the channel', 'missed shot<br />(duck in sight)',
                      'wild shot<br />(no duck)'),
        'upTo': 'up to %d', 'above': 'more than %d',
    },
    'fr': {
        'weapons': ('niveaux', 'arme', 'précision', 'fiabilité', 'armure', 'déflexion',
                    'balles<br />/ chargeur', 'chargeurs<br />/ jour'),
        'penalties': ('niveaux', 'tir manqué', 'tir sauvage', 'par personne touchée'),
        'accidents': ('personnes sur le salon', 'tir manqué<br />(canard en vue)',
                      'tir sauvage<br />(pas de canard)'),
        'upTo': "jusqu'à %d", 'above': 'plus de %d',
    },
}

WHATIS = {
    'en': """	<div class="text">
	<p><b>Duck Hunt</b> is a shooting game played in an IRC channel. Every now and then a
	duck flies across the channel, and the first hunter to shoot it down earns experience
	points (xp). xp makes you climb levels: a higher level means a better gun, better aim and
	more armor, but also bigger penalties when you make a mistake.</p>

	<h2>Commands</h2>
	<ul>
	<li><code>{p}bang</code> &ndash; shoot at the duck.</li>
	<li><code>{p}{reload}</code> &ndash; put a new clip in an empty gun, or unjam it.</li>
	<li><code>{p}duckstats [nick]</code> &ndash; your stats (or someone else's): level, xp,
	ammo, accuracy, karma, items&hellip;</li>
	<li><code>{p}lastduck</code> &ndash; how long ago the last duck flew.</li>
	<li><code>{p}shop [id [target]]</code> &ndash; list the shop, or buy item <i>id</i>
	with your xp (some items need a <i>target</i> player).</li>
	<li><code>{p}duckshooters</code> &ndash; the channel's best hunters this season.</li>
	<li><code>{p}duckchampions</code> &ndash; the podium of the last season.</li>
	</ul>

	<h2>Ducks</h2>
	<p>About <b>{perDay}</b> ducks fly each day at random times (none during the channel's
	sleep hours, if it has some), about <b>{golden}</b> of them golden. A duck that nobody
	shoots down escapes after <b>{escape}</b>.</p>
	<p>Ducks are scared by noise: every shot fired while ducks are flying ({scareWhat})
	counts, and after <b>{scare}</b> shots the ordinary ducks fly away. A silencer keeps your
	shots from being heard. Golden and mechanical ducks aren't scared by noise.</p>
	<p><b>Golden ducks</b> look like ordinary ones until the first hit. They have
	<b>{hpMin}&ndash;{hpMax}</b> hit points: a normal bullet takes 1, AP ammo 2 and explosive
	ammo 3. Killing one pays {xpHp} xp per hit point ({goldMin}&ndash;{goldMax} xp).
	<b>Mechanical ducks</b> are fakes bought in the shop by a prankster: they pay no xp.</p>

	<h2>Shooting</h2>
	<p>Each shot first checks whether your gun <b>jams</b> (the chance is 100% minus your
	reliability). A jammed gun won't fire until you <code>{p}{reload}</code> it. Then the shot
	hits the duck with your <b>accuracy</b> as the chance, otherwise it is a miss.</p>
	<p>Each clip holds a few bullets. Once it is empty, <code>{p}{reload}</code> puts in a new
	one (you can't reload a clip that still has bullets). Your clips are refilled every day at
	<b>{refill}</b>; the number you get depends on your level.</p>
	<p>Some items change the odds for one shot or for a while: a mirror halves the victim's
	accuracy, a sight adds a third of what is missing to 100%, sand doubles the jam chance and
	grease halves it.</p>

	<h2>Experience and levels</h2>
	<div class="scroll"><table class="data" border="1" cellpadding="4" cellspacing="0"><tbody>
	<tr style="background-color: rgb(68, 68, 68);"><th>event</th><th>xp</th></tr>
	<tr><td style="text-align: left;">ordinary duck</td><td>+{xpDuck}</td></tr>
	<tr><td style="text-align: left;">golden duck</td><td>+{xpHp} per hit point</td></tr>
	<tr><td style="text-align: left;">kill with a lucky ricochet</td><td>+{xpLucky} more</td></tr>
	<tr><td style="text-align: left;">missed shot</td><td>missed shot penalty</td></tr>
	<tr><td style="text-align: left;">wild shot (no duck in sight)</td><td>missed + wild shot penalties</td></tr>
	<tr><td style="text-align: left;">each person hit by accident</td><td>accident penalty</td></tr>
	</tbody></table></div>
	<p>Your level comes from your total xp, so losing xp can also lose you a level. Everyone
	starts at level 1 with 0 xp; below {lvl0} xp you fall to level 0. As you climb, your gun
	gets better, but the penalties grow:</p>
{weapons}
{penalties}
	<p>Every level, with its exact xp, is in the <a href="/duckhuntpro/levels/en">levels
	and bonuses</a> table.</p>

	<h2>Hunting accidents</h2>
	<p>A shot that misses can hit someone else on the channel{huntersOnly}. The more people
	there are, the higher the risk, and it is much lower when you shoot at nothing:</p>
{accidents}
	<p>The person hit first rolls their <b>deflection</b>: the bullet bounces off them and
	may hit somebody else (up to {ricochets} times in a row). With a duck in sight, a ricochet
	has a {ricochetDuck}% chance to hit the duck instead: a lucky shot, worth {xpLucky} extra
	xp. If it doesn't bounce, their <b>armor</b> may stop it. Otherwise they are hit and may be
	kicked.</p>
	<p>The shooter loses the accident penalty for each person hit{confiscation}. A life
	insurance pays its holder twice their level in xp when they get shot; a liability insurance
	divides the shooter's accident penalty by 3, and a bribed ranger waives it.</p>
	<p>A <b>wild shot</b> (firing with no duck in sight) costs both the missed shot and the
	wild shot penalties{wildConfiscation}. An infrared detector locks the trigger when there
	is no duck.</p>

	<h2>Shop and finds</h2>
	<p>xp can be spent in the <a href="/duckhuntpro/shop/en">shop</a> on ammo, accessories,
	insurances and pranks against other hunters{minXp}.{drops}</p>

	<h2>Karma</h2>
	<p><code>{p}duckstats</code> shows your karma: 100 &times; (2 &times; ducks &minus; wild
	shots &minus; 3 &times; people hit) &divide; (2 &times; ducks + wild shots + 3 &times;
	people hit). It goes from &minus;100% (a danger to everyone) to +100% (a model hunter).</p>
{season}	</div>
""",
    'fr': """	<div class="text">
	<p><b>Duck Hunt</b> est un jeu de tir qui se joue sur un salon IRC. De temps en temps, un
	canard traverse le salon, et le premier chasseur qui l'abat gagne des points d'expérience
	(xp). L'xp vous fait monter de niveau : plus le niveau est élevé, meilleurs sont l'arme, la
	précision et l'armure, mais plus les pénalités sont lourdes quand vous faites une erreur.</p>

	<h2>Commandes</h2>
	<ul>
	<li><code>{p}bang</code> &ndash; tirer sur le canard.</li>
	<li><code>{p}{reload}</code> &ndash; mettre un nouveau chargeur dans une arme vide, ou la
	décoincer.</li>
	<li><code>{p}duckstats [nick]</code> &ndash; vos statistiques (ou celles d'un autre) :
	niveau, xp, munitions, précision, karma, objets&hellip;</li>
	<li><code>{p}lastduck</code> &ndash; depuis combien de temps le dernier canard s'est
	envolé.</li>
	<li><code>{p}shop [id [cible]]</code> &ndash; afficher la boutique, ou acheter l'objet
	<i>id</i> avec votre xp (certains objets demandent un joueur <i>cible</i>).</li>
	<li><code>{p}duckshooters</code> &ndash; les meilleurs chasseurs du salon cette saison.</li>
	<li><code>{p}duckchampions</code> &ndash; le podium de la saison précédente.</li>
	</ul>

	<h2>Les canards</h2>
	<p>Environ <b>{perDay}</b> canards s'envolent chaque jour à des heures aléatoires (aucun
	pendant les heures de sommeil du salon, s'il en a), dont environ <b>{golden}</b> doré(s).
	Un canard que personne n'abat s'échappe au bout de <b>{escape}</b>.</p>
	<p>Les canards ont peur du bruit : chaque tir pendant qu'ils volent ({scareWhat}) compte,
	et après <b>{scare}</b> tirs les canards ordinaires s'enfuient. Un silencieux empêche vos
	tirs d'être entendus. Les canards dorés et mécaniques n'ont pas peur du bruit.</p>
	<p>Les <b>canards dorés</b> ressemblent aux canards ordinaires jusqu'au premier impact. Ils
	ont <b>{hpMin}&ndash;{hpMax}</b> points de vie : une balle normale en retire 1, une munition
	AP 2 et une munition explosive 3. En abattre un rapporte {xpHp} xp par point de vie
	({goldMin}&ndash;{goldMax} xp). Les <b>canards mécaniques</b> sont des leurres achetés à la
	boutique par un farceur : ils ne rapportent aucune xp.</p>

	<h2>Le tir</h2>
	<p>À chaque tir, on vérifie d'abord si l'arme <b>s'enraye</b> (le risque est 100% moins
	votre fiabilité). Une arme enrayée ne tire plus tant que vous ne faites pas
	<code>{p}{reload}</code>. Ensuite, le tir touche le canard avec votre <b>précision</b> comme
	chance, sinon c'est raté.</p>
	<p>Chaque chargeur contient quelques balles. Une fois vide, <code>{p}{reload}</code> en met
	un nouveau (impossible de recharger un chargeur qui contient encore des balles). Vos
	chargeurs sont réapprovisionnés chaque jour à <b>{refill}</b> ; leur nombre dépend de votre
	niveau.</p>
	<p>Certains objets changent les chances pour un tir ou pour un moment : un miroir divise par
	deux la précision de la victime, une lunette de visée ajoute un tiers de ce qui manque pour
	atteindre 100%, le sable double le risque d'enrayement et la graisse le divise par deux.</p>

	<h2>Expérience et niveaux</h2>
	<div class="scroll"><table class="data" border="1" cellpadding="4" cellspacing="0"><tbody>
	<tr style="background-color: rgb(68, 68, 68);"><th>événement</th><th>xp</th></tr>
	<tr><td style="text-align: left;">canard ordinaire</td><td>+{xpDuck}</td></tr>
	<tr><td style="text-align: left;">canard doré</td><td>+{xpHp} par point de vie</td></tr>
	<tr><td style="text-align: left;">canard abattu par un ricochet chanceux</td><td>+{xpLucky} en plus</td></tr>
	<tr><td style="text-align: left;">tir manqué</td><td>pénalité de tir manqué</td></tr>
	<tr><td style="text-align: left;">tir sauvage (pas de canard en vue)</td><td>pénalités de tir manqué + tir sauvage</td></tr>
	<tr><td style="text-align: left;">chaque personne touchée par accident</td><td>pénalité d'accident</td></tr>
	</tbody></table></div>
	<p>Votre niveau dépend de votre xp totale : perdre de l'xp peut donc aussi vous faire perdre
	un niveau. Tout le monde commence au niveau 1 avec 0 xp ; en dessous de {lvl0} xp, vous
	tombez au niveau 0. En montant, votre arme s'améliore, mais les pénalités augmentent :</p>
{weapons}
{penalties}
	<p>Chaque niveau, avec son xp exacte, se trouve dans le tableau des
	<a href="/duckhuntpro/levels/fr">niveaux et bonus</a>.</p>

	<h2>Accidents de chasse</h2>
	<p>Un tir manqué peut toucher quelqu'un d'autre sur le salon{huntersOnly}. Plus il y a de
	monde, plus le risque est grand, et il est bien plus faible quand vous tirez dans le
	vide :</p>
{accidents}
	<p>La personne touchée tente d'abord sa <b>déflexion</b> : la balle ricoche sur elle et
	peut toucher quelqu'un d'autre (jusqu'à {ricochets} fois de suite). Avec un canard en vue,
	un ricochet a {ricochetDuck}% de chances de toucher le canard à la place : un tir chanceux,
	qui rapporte {xpLucky} xp de plus. Si la balle ne ricoche pas, son <b>armure</b> peut
	l'arrêter. Sinon, elle est touchée et peut être expulsée du salon.</p>
	<p>Le tireur perd la pénalité d'accident pour chaque personne touchée{confiscation}. Une
	assurance vie rapporte à son détenteur deux fois son niveau en xp quand il se fait tirer
	dessus ; une assurance responsabilité civile divise par 3 la pénalité d'accident du tireur,
	et un garde-chasse soudoyé l'annule.</p>
	<p>Un <b>tir sauvage</b> (tirer sans canard en vue) coûte à la fois la pénalité de tir
	manqué et celle de tir sauvage{wildConfiscation}. Un détecteur infrarouge bloque la gâchette
	quand il n'y a pas de canard.</p>

	<h2>Boutique et trouvailles</h2>
	<p>L'xp se dépense à la <a href="/duckhuntpro/shop/fr">boutique</a> en munitions,
	accessoires, assurances et farces contre les autres chasseurs{minXp}.{drops}</p>

	<h2>Karma</h2>
	<p><code>{p}duckstats</code> affiche votre karma : 100 &times; (2 &times; canards &minus;
	tirs sauvages &minus; 3 &times; personnes touchées) &divide; (2 &times; canards + tirs
	sauvages + 3 &times; personnes touchées). Il va de &minus;100% (un danger public) à +100%
	(un chasseur exemplaire).</p>
{season}	</div>
""",
}

WHATIS_PARTS = {
    'en': {
        'scareMisses': 'misses', 'scareAll': 'misses and hits',
        'huntersOnly': ' who has already played',
        'confiscation': ', and their gun is confiscated: %s',
        'wildConfiscation': ', and the gun is confiscated: %s',
        'handBack': {1: 'it is given back every day at %s', 2: 'it is given back once no duck is left flying',
                     3: 'only an operator can give it back'},
        'minXp': ' (a purchase may not leave you below %d xp)',
        'drops': ''' About %d%% of kills also turn up something in the bushes: bullets, a clip,
	special ammo, an accessory or an xp book (from +10 to +100 xp).''',
        'season': """
	<h2>Seasons</h2>
	<p>On the 1st of January, April, July and October the season ends: the final standings
	are kept on the channel's <i>champions</i> page and every hunter starts again from 0 xp.</p>
""",
    },
    'fr': {
        'scareMisses': 'tirs manqués', 'scareAll': 'tirs manqués et réussis',
        'huntersOnly': ' qui a déjà joué',
        'confiscation': ', et son arme est confisquée : %s',
        'wildConfiscation': ", et l'arme est confisquée : %s",
        'handBack': {1: 'elle est rendue chaque jour à %s',
                     2: "elle est rendue dès qu'il n'y a plus de canard en vol",
                     3: 'seul un opérateur peut la rendre'},
        'minXp': " (un achat ne peut pas vous laisser sous %d xp)",
        'drops': ''' Environ %d%% des canards abattus laissent aussi quelque chose dans les
	buissons : des balles, un chargeur, des munitions spéciales, un accessoire ou un livre d'xp
	(de +10 à +100 xp).''',
        'season': """
	<h2>Saisons</h2>
	<p>Le 1er janvier, avril, juillet et octobre, la saison se termine : le classement final
	est conservé sur la page <i>champions</i> du salon et tous les chasseurs repartent de
	0 xp.</p>
""",
    },
}


def renderWhatIs(lang, levels, cfg):
    """The 'what is' page: how the game works, with the numbers of `levels`
    (as data.LEVELS) and of `cfg`, a dict of the bot-wide settings that
    matter here (see plugin._renderWeb for its keys)."""
    texts, heads, parts = TEXTS[lang], WHATIS_HEADERS[lang], WHATIS_PARTS[lang]
    weapons = WEAPONS[lang]

    def weaponOf(number):
        return [name for start, name in weapons if number >= start][-1]

    rows = []
    for first, last in _groups(levels, lambda n: (weaponOf(n), levels[n].clip_size,
                                                  levels[n].clip_count)):
        run = levels[first:last + 1]
        rows.append(_cells((
            _levelSpan(first, last), weaponOf(first),
            _span([l.accuracy for l in run], '%'), _span([100 - l.jam_pct for l in run], '%'),
            _span([l.defense for l in run], '%'), _span([l.deflection for l in run], '%'),
            _span([l.clip_size for l in run]), _span([l.clip_count for l in run]))))
    weaponTable = _table((('', h) for h in heads['weapons']), rows, wide=True)

    rows = []
    for first, last in _groups(levels, lambda n: (levels[n].xp_missed_shot, levels[n].xp_wild_shot,
                                                  levels[n].xp_accident)):
        lvl = levels[first]
        rows.append(_cells((_levelSpan(first, last), lvl.xp_missed_shot, lvl.xp_wild_shot,
                            lvl.xp_accident)))
    penaltyTable = _table((('', h) for h in heads['penalties']), rows)

    rows = []
    for (ceiling, onDuck), (_, wild) in zip(cfg['accidentDuck'], cfg['accidentWild']):
        rows.append(_cells((heads['upTo'] % ceiling if ceiling is not None
                            else heads['above'] % cfg['accidentDuck'][-2][0],
                            '%d%%' % onDuck, '%d%%' % wild)))
    accidentTable = _table((('', h) for h in heads['accidents']), rows)

    handBack = parts['handBack'].get(cfg['handBackMode'], parts['handBack'][3])
    if '%s' in handBack:
        handBack = handBack % html.escape(cfg['handBackTime']).replace(',', ', ')
    hpMin, hpMax = cfg['goldenMinHP'], max(cfg['goldenMinHP'], cfg['goldenMaxHP'])
    content = WHATIS[lang].format(
        p=html.escape(cfg['prefix']), reload=html.escape(cfg['reload']),
        perDay=cfg['ducksPerDay'], golden=cfg['goldenPerDay'],
        escape=_duration(cfg['escapeTime'], lang),
        scare=cfg['scareShots'] if cfg['scareShots'] >= 0 else '&infin;',
        scareWhat=parts['scareAll'] if cfg['successScares'] else parts['scareMisses'],
        hpMin=hpMin, hpMax=hpMax, xpHp=cfg['xpPerGoldenHp'],
        goldMin=hpMin * cfg['xpPerGoldenHp'], goldMax=hpMax * cfg['xpPerGoldenHp'],
        refill=html.escape(cfg['refillTime']).replace(',', ', '),
        xpDuck=cfg['xpPerDuck'], xpLucky=cfg['xpLucky'], lvl0=levels[0].xp_threshold,
        weapons=weaponTable, penalties=penaltyTable, accidents=accidentTable,
        huntersOnly=parts['huntersOnly'] if cfg['onlyHunters'] else '',
        ricochets=cfg['maxRicochets'], ricochetDuck=cfg['ricochetDuck'],
        confiscation=(parts['confiscation'] % handBack) if cfg['confiscateAccident'] else '',
        wildConfiscation=(parts['wildConfiscation'] % handBack) if cfg['confiscateWild'] else '',
        minXp=(parts['minXp'] % cfg['minXpShop']) if cfg['minXpShop'] > 0 else '',
        drops=(parts['drops'] % cfg['drops']) if cfg['drops'] else '', season=parts['season'] if cfg['quarterly'] else '')
    return _page(lang, 'whatis', texts['whatTitle'], (), (), content=content)
