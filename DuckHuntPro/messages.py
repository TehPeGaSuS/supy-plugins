"""
Player-facing message catalog, keyed by language then by message name.

This mirrors the intent of the original script's msgcat-based localization
(a numbered message per language) but uses symbolic names and Python
str.format() placeholders instead of Tcl's positional-arg numbering, since
that's more maintainable in this codebase. Only 'en' ships with real content;
adding another language later is just adding a sibling dict with the same
keys -- `get()` below falls back to English for anything missing.
"""

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

        'antiflood_blocked': '{nick}, slow down -- try that again in a bit.',

        'fusion_merged': "{old}'s stats have been merged into {new} (nick change).",
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
