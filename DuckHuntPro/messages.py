"""
Player-facing message catalog, keyed by language then by message name.

This mirrors the intent of the original script's msgcat-based localization
(a numbered message per language) but uses symbolic names and Python
str.format() placeholders instead of Tcl's positional-arg numbering, since
that's more maintainable in this codebase. Only 'en' ships with real content;
adding another language later is just adding a sibling dict with the same
keys -- `get()` below falls back to English for anything missing.
"""

import re

from . import tclmessages


def _tclTable(lang):
    return tclmessages.FR if lang == 'fr' else tclmessages.EN


def tcl(lang, key, *args):
    """Original Duck Hunt v2.11 message `key` (m0..m4xx) in `lang` ('fr' or
    anything else for English), formatted with Tcl-style positional args like
    msgcat::mc does (a message without args is returned as is)."""
    text = _tclTable(lang)[key]
    if not args:
        return text
    if re.search(r'%\d+\$s', text):         # msgcat's positional form: %2$s
        return re.sub(r'%(\d+)\$s|%%', lambda m: '%' if m.group(0) == '%%'
                      else str(args[int(m.group(1)) - 1]), text)
    return text % args


def tclList(lang, key):
    """The original's list-valued messages (m134 rank names, m137 glyphs,
    m138 cries, m394 junk items)."""
    return _tclTable(lang) and (tclmessages.FR_LISTS if lang == 'fr' else tclmessages.EN_LISTS)[key]


def plural(value, singular, plural_):
    """Duck_Hunt.tcl's plural: the plural form from |2| up."""
    return plural_ if value >= 2 or value <= -2 else singular


def colorizeValue(value):
    """Duck_Hunt.tcl's colorize_value: red when <= 0."""
    return '\x0304%s\x03' % value if value <= 0 else str(value)


def lvl2rank(level, lang='en'):
    return tclList(lang, 'm134')[level]


def adaptTimeResolution(milliseconds, short=False, lang='en', skipZeroSeconds=False):
    """Duck_Hunt.tcl's adapt_time_resolution: a duration in milliseconds as
    '1 hour 5 minutes and 3.5 seconds' (or '1h5mn3.5s' when `short`). Zero
    units are skipped except seconds, which always show. (The original reads
    the last three characters of the number as the milliseconds, which
    mangles durations under 100 ms; this pads them properly.) With
    `skipZeroSeconds`, '5 minutes' instead of '5 minutes and 0 seconds'."""
    t = lambda key: tcl(lang, key)
    seconds_total, milli = divmod(abs(int(milliseconds)), 1000)
    days = seconds_total // 86400
    hours = (seconds_total % 86400) // 3600
    minutes = (seconds_total % 3600) // 60
    seconds = seconds_total % 60
    milli = ('%03d' % milli).rstrip('0')
    out = []
    valid = 0
    for counter, unit in enumerate((days, hours, minutes, seconds), 1):
        if unit <= 0 and counter != 4:
            continue
        if counter == 4 and skipZeroSeconds and valid and not unit and not milli:
            continue
        if counter == 1:
            out.append('%d%s' % (unit, t('m112')) if short else
                       '%d %s' % (unit, plural(unit, t('m110'), t('m111'))))
        elif counter == 2:
            out.append('%d%s' % (unit, t('m115')) if short else
                       '%d %s' % (unit, plural(unit, t('m113'), t('m114'))))
        elif counter == 3:
            out.append('%d%s' % (unit, t('m118')) if short else
                       '%d %s' % (unit, plural(unit, t('m116'), t('m117'))))
        elif milli:
            out.append('%d.%s%s' % (unit, milli, t('m119')) if short else
                       '%d.%s %s' % (unit, milli, plural(int('%d%s' % (unit, milli)),
                                                          t('m106'), t('m107'))))
        else:
            out.append('%d%s' % (unit, t('m119')) if short else
                       '%d %s' % (unit, plural(unit, t('m106'), t('m107'))))
        valid += 1
    if short:
        return ''.join(out)
    if valid > 1:
        out.insert(len(out) - 1, t('m120'))
    return ' '.join(out)


MESSAGES = {
    'en': {
        'duck_flies': '\\_o< Quack!',
        'golden_duck_flies': '\\_O< QUACK!! (a golden duck, worth extra XP -- it can take more than one shot)',
        'kill': '{nick} shot down the duck in {elapsed:.2f}s! (+{xp} xp, now level {level})',
        'kill_golden_final': "{nick} finished off the golden duck in {elapsed:.2f}s! (+{xp} xp, now level {level})",
        'kill_golden_hit': '{nick} hit the golden duck! It has {hp} health left.',
        'kill_lucky': '{nick} made a lucky shot after {ricochets} ricochet(s) and downed the duck! (+{xp} xp, now level {level})',
        'miss': '{nick} missed the duck! ({xp} xp)',
        'no_duck_wild_shot': "{nick} fired without a duck in sight! ({xp} xp)",
        'no_duck_nothing_there': "There's no duck to shoot at right now.",
        'duck_fled': 'The duck flew away, scared off by all the gunfire!',
        'duck_escaped': 'The duck flew off unharmed.',
        'empty_clip': "{nick}'s gun is empty! Try 'reload'.",
        'no_clips_left': "{nick} has no spare clips left to reload with.",
        'gun_jammed': "{nick}'s gun jams!",
        'gun_confiscated': "{nick}'s gun has been confiscated!",
        'gun_not_armed': "{nick} doesn't have a gun -- it was confiscated.",
        'reload_ok': '{nick} reloads.',
        'reload_full': "{nick}'s clip is already full.",
        'level_up': '{nick} reached level {level}!',
        'accident_hit': '{shooter} accidentally hits {victim}! ({xp} xp for {shooter})',
        'accident_gun_confiscated': "{shooter}'s weapon is confiscated for the accident!",
        'accident_deflected': '{victim} deflects the stray bullet!',
        'accident_absorbed': "{victim}'s armor absorbs the stray bullet, no harm done.",
        'accident_kicked': '{victim} takes the hit and is kicked!',
        'life_insurance_payout': "{nick}'s life insurance pays out {xp} bonus xp!",
        'ricochet_towards_duck': 'The ricochet flies towards the duck!',
        'ricochet_falls': 'The ricochet loses momentum and falls to the ground.',
        'duckstats_header': "Hunting stats for {nick}: level {level}, {xp} xp",
        'duckstats_line': ('{killed} killed ({golden} golden), {missed} missed, '
                            '{jams} jams, best time {best_time}, gun: {gun_state}'),
        'lastduck_never': 'No duck has flown on this channel yet.',
        'lastduck': 'The last duck flew {elapsed} ago.',
        'shooters_header': 'Top shooters:',
        'shooters_line': '#{rank} {nick} -- level {level}, {xp} xp, {killed} killed',
        'shooters_empty': "Nobody's shot a duck here yet.",
        'champions_header': 'Champions of the season ending {when}:',
        'champions_line': '#{rank} {nick} -- {xp} xp, {killed} killed',
        'champions_empty': 'No quarterly reset has happened here yet.',
        'lastduck_killer': 'It was shot by {nick}.',
        'lastduck_flying': 'It is still in the air.',
        'lastduck_escaped': 'Tired of waiting, it flew away after {duration}.',
        'lastduck_fled': 'Frightened by the gunfire, it flew away after {duration}.',
        'quarterly_reset': ("A new hunting season begins! Standings have been "
                             "archived -- see 'duckchampions' for last season's "
                             "top shooters."),

        'shop_unknown_item': "{item} isn't sold here. Try 'shop list'.",
        'shop_gun_confiscated': "{nick}'s weapon is confiscated -- the shop is closed to you.",
        'shop_not_rich_enough': "That would drop you below the xp floor here ({floor} xp).",
        'shop_already_have': '{nick} already has {item} active.',
        'shop_bought': '{nick} bought {item} for {cost} xp.',
        'shop_target_required': 'That item needs a target: shop buy <item> <nick>',
        'shop_target_self': "You can't target yourself with that.",
        'shop_target_unknown': "{target} hasn't played here.",
        'shop_target_offline': "{target} isn't in the channel right now.",
        'level_down': '{nick} drops back to level {level}.',

        'clip_already_full': "{nick}'s clip is already full.",
        'clips_already_full': '{nick} already has the max number of spare clips.',
        'buyback_not_confiscated': "{nick}'s weapon isn't confiscated.",
        'buyback_permanent': "{nick}'s weapon is permanently confiscated -- only an op can `rearm` it.",
        'buyback_ok': "{nick}'s weapon has been returned.",
        'sight_ok': '{nick} attaches a sight to the weapon.',
        'mirror_no_effect_sunglasses': "{nick}'s mirror has no effect -- {target} is wearing sunglasses.",
        'mirror_ok': '{nick} aims a mirror at {target}.',
        'mirror_hit': '{nick} is dazzled by a mirror ({attacker})! Accuracy halved this shot.',
        'sand_no_gun': "{target} doesn't have a weapon to jam.",
        'sand_absorbed_by_grease': "{nick}'s sand has no effect -- {target}'s weapon is greased.",
        'sand_ok': '{nick} throws sand at {target}.',
        'water_bucket_no_gun': "{target} doesn't have a weapon.",
        'water_bucket_ok': '{nick} soaks {target} with a bucket of water.',
        'water_bucket_blocked': "{nick}'s clothes are wet ({attacker}) -- try again in {remaining}.",
        'sabotage_no_gun': "{target} doesn't have a weapon to sabotage.",
        'sabotage_ok': '{nick} sabotages {target}\'s weapon.',
        'sabotage_fires': "{nick}'s weapon explodes -- sabotaged by {attacker}!",
        'spare_clothes_noop': "{nick} doesn't need to change clothes.",
        'spare_clothes_ok': '{nick} changes into spare clothes.',
        'brush_noop': "{nick} doesn't need a brush right now.",
        'brush_ok': '{nick} brushes off the weapon.',
        'life_insurance_ok': '{nick} takes out life insurance.',
        'liability_insurance_ok': '{nick} takes out liability insurance.',
        'decoy_ok': '{nick} sets out a decoy -- a duck should show up soon.',
        'decoy_blocked_sleep': "Ducks are asleep right now -- a decoy wouldn't work.",
        'bread_ok': '{nick} throws out a piece of bread ({count}/{max} on this channel).',
        'bread_full': 'There is already enough bread on this channel ({max} pieces).',
        'bread_blocked_sleep': "Ducks are asleep right now -- bread wouldn't work.",
        'duck_detector_ok': '{nick} sets up a duck detector.',
        'duck_detector_notice': 'Your duck detector on {channel} just went off!',
        'fake_duck_ok': "{nick} sets up a mechanical duck -- it'll arrive in about 10 minutes.",

        'infrared_blocked': "{nick}'s infrared detector kept the trigger locked -- no duck in sight.",
        'drop_junk': '{nick} also found {junk} -- utterly useless.',
        'drop_item': '{nick} also found {item}!',
        'drop_xp_book': '{nick} also found a book worth {xp} bonus xp!',

        'unarm_ok': "{nick}'s weapon has been confiscated{static}.",
        'unarm_static_suffix': ' (permanently)',
        'unarm_already': "{nick}'s weapon is already confiscated.",
        'rearm_ok': "{nick}'s weapon has been returned.",
        'rearm_already_armed': '{nick} looks at you, confused -- their weapon is already armed.',
        'admin_target_unknown': "{nick} hasn't played here.",
        'admin_rename_exists': '{new} already has a profile here -- use fusion instead.',
        'admin_rename_ok': '{old} renamed to {new}.',
        'admin_delete_ok': "{nick}'s profile has been deleted.",
        'admin_fusion_ok': '{sources} merged into {dest}.',
        'admin_list_empty': 'No players recorded here yet.',
        'admin_planning_empty': 'No flights currently planned for this channel.',
        'admin_planning_line': 'Planned duck soarings for the current day on {channel}: {times}',
        'admin_replanning_ok': 'A new planning has been computed for duck soarings on {channel}: {times}',
        'admin_launch_ok': 'A duck has been launched immediately.',
        'admin_export_ok': 'Player stats exported to {path}.',

        'fusion_merged': "{old}'s stats have been merged into {new} (nick change).",
    },
    # The plugin's own additions to the original (the season features); the
    # original's messages themselves are in tclmessages.py, in both languages.
    'fr': {
        'lastduck_killer': 'Il a été abattu par {nick}.',
        'lastduck_flying': 'Il est toujours là.',
        'lastduck_escaped': "Las d'attendre, il s'est enfui après {duration}.",
        'lastduck_fled': "Effrayé par les coups de feu, il s'est enfui après {duration}.",
        'shooters_header': 'Meilleurs chasseurs :',
        'shooters_line': '#{rank} {nick} -- niveau {level}, {xp} xp, {killed} tué(s)',
        'shooters_empty': "Personne n'a encore abattu de canard ici.",
        'champions_header': 'Champions de la saison terminée le {when} :',
        'champions_line': '#{rank} {nick} -- {xp} xp, {killed} tué(s)',
        'champions_empty': "Aucune remise à zéro trimestrielle n'a encore eu lieu ici.",
        'quarterly_reset': ("Une nouvelle saison de chasse commence ! Le classement a été "
                             "archivé -- voir 'duckchampions' pour les meilleurs chasseurs "
                             "de la saison précédente."),
    },
}

JUNK_FLAVORS = (
    'a plush duck', 'a pile of feathers', 'a chewed piece of gum',
    'an empty shell casing', 'a rusty bottle cap', 'a soggy newspaper',
)

DEFAULT_LANGUAGE = 'en'


def get(language, key, **kwargs):
    catalog = MESSAGES.get(language, MESSAGES[DEFAULT_LANGUAGE])
    template = catalog.get(key, MESSAGES[DEFAULT_LANGUAGE].get(key, key))
    return template.format(**kwargs)
