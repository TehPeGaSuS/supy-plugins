"""
Static game data transcribed from the original eggdrop TCL script's
Duck_Hunt.cfg (Menz Agitat, v2.11). Numbers here are content/balance, not
per-installation config -- see config.py for the knobs an operator can
actually tune at runtime.

Level table syntax mirrors the source's comment for level_grantings(n):
  "xp,precision,deflection,defense,jam,clip_size,clip_count,
   xp_missed_shot,xp_wild_shot,xp_accident"
  - xp: XP required to reach the NEXT level (level 40's is the effective cap).
  - precision: % chance to hit the duck.
  - deflection: % chance an accidental bullet ricochets off the player.
  - defense: % chance an accidental bullet is absorbed with no effect.
  - jam: % chance the weapon jams on a shot.
  - clip_size: rounds per clip.
  - clip_count: number of clips refilled daily.
  - xp_missed_shot / xp_wild_shot / xp_accident: XP penalty (already
    negative) applied for a miss / a shot with no duck present / accidentally
    hitting another player.
"""

from collections import namedtuple

Level = namedtuple('Level', [
    'xp_to_next', 'accuracy', 'deflection', 'defense', 'jam_pct',
    'clip_size', 'clip_count', 'xp_missed_shot', 'xp_wild_shot', 'xp_accident',
])

# Index = level number (0-40). Transcribed verbatim from Duck_Hunt.cfg
# lines 250-290 (level_grantings array). Row 0's xp_to_next is -4 in the
# source, not a typo: the original doc says players "start at level 1 with
# 0 xp", and levelForXp()'s cumulative walk (0 + -4 = -4, then -4 + 20 = 16)
# reproduces exactly that -- a fresh player at 0 xp lands on level 1.
LEVELS = [
    Level(-4, 55, 0, 0, 15, 6, 1, -1, -1, -4),
    Level(20, 55, 0, 0, 15, 6, 2, -1, -1, -4),
    Level(50, 56, 0, 2, 14, 6, 2, -1, -1, -4),
    Level(90, 57, 1, 5, 13, 6, 2, -1, -1, -4),
    Level(140, 58, 2, 7, 12, 6, 2, -1, -1, -4),
    Level(200, 59, 4, 10, 11, 6, 2, -1, -1, -4),
    Level(270, 60, 6, 12, 10, 6, 2, -1, -1, -4),
    Level(350, 65, 8, 15, 7, 4, 3, -1, -1, -4),
    Level(440, 67, 10, 17, 7, 4, 3, -1, -1, -4),
    Level(540, 69, 12, 20, 7, 4, 3, -1, -1, -4),
    Level(650, 71, 14, 22, 6, 4, 3, -1, -2, -6),
    Level(770, 73, 16, 25, 6, 4, 3, -1, -2, -6),
    Level(900, 73, 18, 27, 6, 4, 3, -1, -2, -6),
    Level(1040, 74, 20, 30, 5, 4, 3, -1, -2, -6),
    Level(1190, 74, 22, 32, 5, 4, 3, -1, -2, -6),
    Level(1350, 75, 24, 35, 5, 4, 3, -1, -2, -6),
    Level(1520, 80, 26, 37, 3, 2, 4, -1, -2, -6),
    Level(1700, 81, 28, 40, 3, 2, 4, -1, -2, -6),
    Level(1890, 81, 30, 42, 3, 2, 4, -1, -2, -6),
    Level(2090, 82, 31, 45, 3, 2, 4, -1, -2, -6),
    Level(2300, 82, 32, 47, 3, 2, 4, -3, -5, -10),
    Level(2520, 83, 33, 50, 2, 2, 4, -3, -5, -10),
    Level(2750, 83, 34, 52, 2, 2, 4, -3, -5, -10),
    Level(2990, 84, 35, 55, 2, 2, 4, -3, -5, -10),
    Level(3240, 84, 36, 57, 2, 2, 4, -3, -5, -10),
    Level(3500, 85, 37, 60, 2, 2, 4, -3, -5, -10),
    Level(3770, 90, 38, 62, 1, 1, 5, -3, -5, -10),
    Level(4050, 91, 39, 65, 1, 1, 5, -3, -5, -10),
    Level(4340, 91, 40, 67, 1, 1, 5, -3, -5, -10),
    Level(4640, 92, 41, 70, 1, 1, 5, -3, -5, -10),
    Level(4950, 92, 42, 72, 1, 1, 5, -5, -8, -20),
    Level(5270, 93, 43, 75, 1, 1, 5, -5, -8, -20),
    Level(5600, 93, 44, 77, 1, 1, 5, -5, -8, -20),
    Level(5940, 94, 45, 80, 1, 1, 5, -5, -8, -20),
    Level(6290, 94, 46, 82, 1, 1, 5, -5, -8, -20),
    Level(6650, 95, 47, 85, 1, 1, 5, -5, -8, -20),
    Level(7020, 95, 48, 87, 1, 1, 5, -5, -8, -20),
    Level(7400, 96, 48, 90, 1, 1, 5, -5, -8, -20),
    Level(7790, 96, 49, 92, 1, 1, 5, -5, -8, -20),
    Level(8200, 97, 49, 95, 1, 1, 5, -5, -8, -20),
    Level(9999999999, 97, 50, 98, 99, 1, 5, -5, -8, -20),
]

MAX_LEVEL = len(LEVELS) - 1


def levelForXp(xp):
    """Returns the level index (0-40) for a given total xp."""
    level = 0
    total = 0
    for i, lvl in enumerate(LEVELS):
        if i == MAX_LEVEL:
            return i
        total += lvl.xp_to_next
        if xp < total:
            return i
        level = i + 1
    return level


# Core numeric constants, cfg lines 20-121, 211-221.
DUCKS_PER_DAY = 18
APPROX_GOLDEN_DUCKS_PER_DAY = 1
GOLDEN_DUCK_MIN_HP = 3
GOLDEN_DUCK_MAX_HP = 5
SHOTS_BEFORE_DUCK_FLEE = 3
SUCCESSFUL_SHOTS_ALSO_SCARE_DUCKS = True
ESCAPE_TIME_SECONDS = 300

XP_PER_DUCK = 10
BASE_XP_GOLDEN_DUCK = 12
XP_LUCKY_SHOT = 25

# Hunting-accident tuning (cfg lines 92-121): percent chance of hitting a
# random other channel occupant with a missed/ricocheted shot, keyed by
# channel population tier, split by whether a duck was actually present.
ACCIDENT_CHANCE_DUCK_PRESENT = [
    (10, 10), (20, 12), (30, 14), (None, 15),
]
ACCIDENT_CHANCE_WILD_FIRE = [
    (10, 1), (20, 2), (30, 3), (None, 4),
]
CHANCE_RICOCHET_TOWARDS_DUCK = 10
MAX_RICOCHETS = 5


def accidentChance(population, duckPresent):
    """% chance a stray shot hits a random bystander, given channel
    population and whether a duck was present when it was fired."""
    tiers = ACCIDENT_CHANCE_DUCK_PRESENT if duckPresent else ACCIDENT_CHANCE_WILD_FIRE
    for ceiling, chance in tiers:
        if ceiling is None or population <= ceiling:
            return chance
    return tiers[-1][1]


# Anti-highlight duck art (Duck_Hunt.tcl's hl_prevention, msgcat m136-138).
# Randomizes the flight announcement so highlight-triggered auto-shoot
# scripts can't be trained on one fixed string. A small representative set,
# not the original's ~228-entry glyph table -- full parity on game numbers/
# mechanics matters more than matching every joke string 1:1 here.
DUCK_TRAIL = "-.,_,.-·'`'·-.,_,.-·'`'·"
DUCK_GLYPHS = ('\\_O<', '\\_o<', '/_O<', '\\_O{', '\\_o{', '/_o<')
DUCK_CRIES = ('QUACK', 'QUAC', 'QUAAAC', 'KWAK', 'KWAAAK', 'ARK')


def randomDuckArt(rng):
    """Builds one randomized duck-flight announcement: a slightly mutated
    trail + a random duck glyph + a random cry, so the announcement string
    differs every flight (hl_prevention)."""
    trail = list(DUCK_TRAIL)
    step = max(1, len(trail) // 4)
    start = rng.randint(0, step - 1) if step > 1 else 0
    removed = 0
    for i in range(4):
        idx = start + i * step - removed
        if 0 <= idx < len(trail):
            del trail[idx]
            removed += 1
    glyph = DUCK_GLYPHS[rng.randint(0, len(DUCK_GLYPHS) - 1)]
    cry = DUCK_CRIES[rng.randint(0, len(DUCK_CRIES) - 1)]
    return "%s %s   %s" % (''.join(trail), glyph, cry)


# Nick-fusion (merge_stats): stat keys summed when merging an old nick's
# profile into a renamed player's new one.
FUSION_SUMMED_STATS = (
    'killed', 'golden_killed', 'missed', 'empty_shots', 'humans_shot',
    'wild_shots', 'bullets_received', 'deflected', 'absorbed',
    'confiscations', 'jams', 'deaths', 'total_time_ms', 'timed_shots',
)


# Shop items (cfg lines 318-376): key -> XP cost. Effects are documented in
# the original comments; Phase 1 only needs the catalog to exist for
# duckstats/leaderboard display context. Phase 2 adds behavior.
ITEM_COSTS = {
    'extra_ammo': 7,
    'extra_clip': 20,
    'ap_ammo': 15,
    'explosive_ammo': 25,
    'buyback_weapon': 40,
    'grease': 8,
    'sight': 6,
    'infrared_detector': 15,
    'silencer': 5,
    'four_leaf_clover': 13,
    'sunglasses': 5,
    'spare_clothes': 7,
    'brush': 7,
    'mirror': 7,
    'sand': 7,
    'water_bucket': 10,
    'sabotage': 14,
    'life_insurance': 10,
    'liability_insurance': 5,
    'decoy': 8,
    'bread': 2,
    'duck_detector': 5,
    'fake_duck': 50,
}

MAX_BREAD_ON_CHAN = 20

# Kill drop table (cfg lines 404-438): per-1000 chance, keyed by drop name.
DROP_TABLE = {
    'junk': 20,
    'ammo': 20,
    'clip': 15,
    'ap_ammo': 7,
    'explosive_ammo': 5,
    'grease': 7,
    'sight': 12,
    'infrared_detector': 7,
    'silencer': 12,
    'four_leaf_clover': 7,
    'sunglasses': 12,
    'duck_detector': 12,
    'xp_book_10': 3,
    'xp_book_20': 2,
    'xp_book_30': 1,
    'xp_book_40': 1,
    'xp_book_50': 1,
    'xp_book_100': 1,
}

# XP-book drop keys grant flat xp directly, no item involved.
XP_BOOK_VALUES = {
    'xp_book_10': 10, 'xp_book_20': 20, 'xp_book_30': 30,
    'xp_book_40': 40, 'xp_book_50': 50, 'xp_book_100': 100,
}


def rollDrop(rng):
    """Rolls the kill drop table exactly as Duck_Hunt.tcl's hit_a_duck does:
    each key is checked in a FIXED order, as an independent Bernoulli trial
    (roll 1-1000 <= that key's per-1000 chance), and the FIRST one to
    succeed wins -- this is deliberately not a single normalized weighted
    pick, so keys later in DROP_TABLE's order have their effective odds
    reduced by earlier keys already "using up" that kill's roll. Returns the
    winning key, or None if every roll failed (the much more common case)."""
    for key, chance in DROP_TABLE.items():
        if rng.randint(1, 1000) <= chance:
            return key
    return None


# Per-item purchase metadata (durations in seconds, None = no time expiry;
# uses = None means no use-cap, only the duration governs removal). Costs
# stay in ITEM_COSTS above; this is behavior, transcribed from Duck_Hunt.tcl
# (see ::DuckHunt::shop, lines ~1692-2156) rather than the .cfg, since the
# .cfg only has costs. Items not listed here (buyback_weapon, spare_clothes,
# brush, mirror, sand, water_bucket, sabotage, decoy, bread, fake_duck) are
# one-shot triggers or channel-wide effects with no standing item-slot state
# of their own (water_bucket is the one exception with a real duration, but
# it lives on the *target*, not the buyer -- handled specially in plugin.py).
ITEM_META = {
    'ap_ammo': {'duration': 86400, 'uses': None},
    'explosive_ammo': {'duration': 86400, 'uses': None},
    'grease': {'duration': 86400, 'uses': None},
    'sight': {'duration': None, 'uses': 1},
    'infrared_detector': {'duration': 86400, 'uses': 6},
    'silencer': {'duration': 86400, 'uses': None},
    'four_leaf_clover': {'duration': 86400, 'uses': None},
    'sunglasses': {'duration': 86400, 'uses': None},
    'duck_detector': {'duration': None, 'uses': 1},
    'life_insurance': {'duration': 604800, 'uses': 1},
    'liability_insurance': {'duration': 172800, 'uses': None},
}

# Ammo-type items are mutually exclusive (buying one silently replaces the
# other) and boost per-shot damage against multi-hit (golden) ducks only --
# normal ducks always die in one hit regardless of damage value.
AMMO_TYPE_DAMAGE = {'ap_ammo': 2, 'explosive_ammo': 3}
NORMAL_DAMAGE = 1

CLOVER_BONUS_MIN = 1
CLOVER_BONUS_MAX = 10

# 2x the victim's own level, not "2x the shooter's level" as the original
# script's shop message/comment claims -- the actual TCL code
# (::DuckHunt::shoot, accident branch) computes the bonus from the victim's
# own xp/level, not the shooter's. Preserved here as real behavior (full
# parity is the goal), not "fixed" to match the stale doc comment.
LIFE_INSURANCE_LEVEL_MULTIPLIER = 2

WATER_BUCKET_DURATION = 3600

BREAD_DURATION = 3600
BREAD_ESCAPE_BONUS_PER_PIECE = 20
BREAD_EXTRA_DUCKS_PER_PIECE = 1

DECOY_MIN_DELAY = 1
DECOY_MAX_DELAY = 600
FAKE_DUCK_DELAY = 600

# Short blurbs for `shop list`, in the same order as ITEM_COSTS.
ITEM_DESCRIPTIONS = {
    'extra_ammo': '+1 round in your current clip',
    'extra_clip': '+1 spare clip',
    'ap_ammo': '24h, x2 damage vs golden ducks (replaces explosive_ammo)',
    'explosive_ammo': '24h, x3 damage vs golden ducks (replaces ap_ammo)',
    'buyback_weapon': 'un-confiscates your weapon',
    'grease': '24h, halves jam chance; also absorbs one sand throw',
    'sight': 'next shot only: accuracy boost',
    'infrared_detector': '24h/6 uses: blocks wasted wild shots outright',
    'silencer': "24h: your shots never scare ducks into fleeing",
    'four_leaf_clover': '24h: flat bonus xp on every kill',
    'sunglasses': "24h: makes a mirror thrown at you fail",
    'spare_clothes': 'cures water_bucket',
    'brush': 'cures sand or sabotage',
    'mirror': 'targeted: halves target\'s accuracy on their next shot',
    'sand': "targeted: doubles target's jam chance on their next shot",
    'water_bucket': "targeted: target can't shoot for 1 hour",
    'sabotage': "targeted: guarantees target's next shot jams (+kick)",
    'life_insurance': '7 days/1 use: bonus xp if you take a stray hit',
    'liability_insurance': "2 days: cuts your own accident xp penalty by 2/3",
    'decoy': 'lures a real duck to the channel within 10 minutes',
    'bread': "1h, stacks: more ducks per day + longer escape time",
    'duck_detector': 'next duck spawn: you get an advance notice',
    'fake_duck': 'a decoy duck arrives in exactly 10 minutes, worth 0 xp',
}
