"""
Reader for the player database of the original Eggdrop Tcl script
(Duck_Hunt.tcl v2.11, `player_data.db`), so existing scores can be carried
over to this plugin.

The file is a few header lines (the first starts with "--- ", the header ends
at a line that is exactly "---") followed by a Tcl dict written with `puts`:

    #chan {lowernick {gun 1 jammed 0 current_ammo_clip 6 ... items {{exp id data}}}}

This module has no Limnoria dependency, so it can be unit-tested on its own.
"""

import time

# Tcl item ids -> this plugin's item keys (the shop's numbering).
ITEM_KEYS = {
    '3': 'ap_ammo', '4': 'explosive_ammo', '6': 'grease', '7': 'sight',
    '8': 'infrared_detector', '9': 'silencer', '10': 'four_leaf_clover',
    '11': 'sunglasses', '14': 'mirror_dazzle', '15': 'sand', '16': 'water_bucket',
    '17': 'sabotage', '18': 'life_insurance', '19': 'liability_insurance',
    '22': 'duck_detector',
}
# Items whose third field is a use counter / the giver's nick.
_USES_ITEMS = {'7', '8', '18', '22'}
_NICK_ITEMS = {'14', '15', '16', '17'}

_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r'}


class TclParseError(ValueError):
    pass


def parseList(text):
    """Splits a Tcl list string into its elements. Braced elements lose their
    braces (nested content is kept verbatim, to be parsed again as needed);
    quoted elements and bare words have their backslash escapes decoded."""
    words = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == '{':
            depth = 1
            j = i + 1
            while j < n and depth:
                ch = text[j]
                if ch == '\\':
                    j += 2
                    continue
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                j += 1
            if depth:
                raise TclParseError('unbalanced brace in %r' % text[i:i + 40])
            words.append(text[i + 1:j - 1])
            i = j
        elif c == '"':
            j = i + 1
            buf = []
            while j < n and text[j] != '"':
                if text[j] == '\\' and j + 1 < n:
                    j += 1
                    buf.append(_ESCAPES.get(text[j], text[j]))
                else:
                    buf.append(text[j])
                j += 1
            if j >= n:
                raise TclParseError('unterminated quote in %r' % text[i:i + 40])
            words.append(''.join(buf))
            i = j + 1
        else:
            j = i
            buf = []
            while j < n and not text[j].isspace():
                if text[j] == '\\' and j + 1 < n:
                    j += 1
                    buf.append(_ESCAPES.get(text[j], text[j]))
                else:
                    buf.append(text[j])
                j += 1
            words.append(''.join(buf))
            i = j
    return words


def parseDict(text):
    words = parseList(text)
    if len(words) % 2:
        raise TclParseError('dict with an odd number of elements')
    return dict(zip(words[0::2], words[1::2]))


def splitHeader(content):
    """Returns the dict text of a database file's content (the header, when
    there is one, is skipped)."""
    lines = content.split('\n')
    if lines and lines[0].startswith('--- '):
        for idx, line in enumerate(lines[1:], 1):
            if line.strip() == '---':
                return '\n'.join(lines[idx + 1:])
        raise TclParseError('database header is never closed')
    return content


def loadText(content):
    """{channel: {lowernick: {field: value}}} from a database file's text."""
    body = splitHeader(content).strip()
    if not body:
        return {}
    return {chan: {nick: parseDict(rec) for nick, rec in parseDict(players).items()}
            for chan, players in parseDict(body).items()}


def loadFile(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        return loadText(f.read())


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def convertItems(raw, now=None):
    """The Tcl `items` list ({expiry id data} elements) as this plugin's
    {key: {'expires_at', 'uses_left', 'value'}} dict. Expired and unknown
    items are dropped."""
    now = now if now is not None else time.time()
    items = {}
    for element in parseList(raw or ''):
        parts = parseList(element)
        if len(parts) != 3 or parts[1] not in ITEM_KEYS:
            continue
        expiry, itemId, data = parts
        expiresAt = None if expiry == '-' else _int(expiry)
        if expiresAt is not None and expiresAt <= now:
            continue
        uses = _int(data) if itemId in _USES_ITEMS else None
        value = None
        if itemId == '10':
            value = _int(data)                  # the clover's bonus xp
        elif itemId in _NICK_ITEMS and data != '-':
            value = data                        # who sent it
        items[ITEM_KEYS[itemId]] = {'expires_at': expiresAt, 'uses_left': uses, 'value': value}
    return items


def convertPlayer(fields, nick, now=None):
    """One Tcl player record as this plugin's player dict. Fields missing
    from an older database take the original's defaults."""
    get = lambda k, d='0': fields.get(k, d)
    gun = _int(get('gun', '1'), 1)
    try:
        bestTime = float(get('best_time', '-1'))
    except ValueError:
        bestTime = -1
    lastActivity = _int(get('last_activity', '-1'), -1)
    return {
        'display_nick': fields.get('nick') or nick,
        'xp': _int(get('xp')),
        'gun_state': 'armed' if gun == 1 else 'confiscated' if gun == 0 else 'confiscated_permanent',
        'jammed': _int(get('jammed')) == 1,
        'clip_ammo': _int(fields['current_ammo_clip']) if 'current_ammo_clip' in fields else None,
        'clips_left': _int(fields['remaining_ammo_clips']) if 'remaining_ammo_clips' in fields else None,
        'stats': {
            'killed': _int(get('ducks_shot')),
            'golden_killed': _int(get('golden_ducks_shot')),
            'missed': _int(get('missed_shots')),
            'empty_shots': _int(get('empty_shots')),
            'humans_shot': _int(get('humans_shot')),
            'wild_shots': _int(get('wild_shots')),
            'bullets_received': _int(get('bullets_received')),
            'deflected': _int(get('deflected_bullets')),
            'absorbed': 0,
            'confiscations': _int(get('confiscated_weapons')),
            'jams': _int(get('jammed_weapons')),
            'deaths': _int(get('deaths')),
            'best_time_ms': None if bestTime < 0 else int(round(bestTime * 1000)),
            'total_time_ms': 0,
            'timed_shots': 0,
            'reflex_ms': _int(get('cumul_reflex_time')),
        },
        'items': convertItems(get('items', ''), now),
        'last_activity': None if lastActivity < 0 else lastActivity,
    }


def convertChannel(players, now=None):
    """{lowernick: record} -> {lowernick: player dict}."""
    return {nick: convertPlayer(rec, nick, now) for nick, rec in players.items()}
