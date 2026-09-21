"""UnrealIRCd extban letter<->name translation.

UnrealIRCd extbans come in two equivalent spellings, e.g. ``~a:foo`` and
``~account:foo``. ISUPPORT's ``EXTBAN=`` token is *always* letter-only
(src/api-extban.c: set_isupport_extban()), regardless of how the server is
actually configured to display bans -- so ISUPPORT can never be used to
tell which form a given network shows to users. What actually governs the
displayed/stored form is the ``set::named-extended-bans`` config option
(src/api-extban.c: prefix_with_extban(), default "yes" per src/conf.c),
which normalizes every +b/+e/+I mask through this same table regardless of
which form it was originally typed in (src/channel.c, generic ban mask
cleaning path).

This table was built from UnrealIRCd's own ``HELPOP EXTBANS`` reference
and cross-checked letter-by-letter against a live PTirc (UnrealIRCd 6.2.7)
ISUPPORT EXTBAN= token (acfijmnpqrtACFGOST) -- all 18 letters below are
confirmed to exist on that network with no unexplained/custom entries.

This module deliberately only translates the *selector* token
(letter<->name); it never validates or interprets the argument that
follows the ``:``, since that's extban-specific and irrelevant to
translation.
"""

import re

# Group 1: ban-modifying wrapper
# Group 2/3/4: action/selector/special extbans
LETTER_TO_NAME = {
    't': 'time',
    'q': 'quiet',
    'n': 'nickchange',
    'j': 'join',
    'm': 'msgbypass',
    'f': 'forward',
    'F': 'flood',
    'a': 'account',
    'A': 'asn',
    'c': 'channel',
    'C': 'country',
    'O': 'operclass',
    'r': 'realname',
    'G': 'security-group',
    'S': 'certfp',
    'i': 'inherit',
    'T': 'text',
    'p': 'partmsg',
}

NAME_TO_LETTER = {name: letter for letter, name in LETTER_TO_NAME.items()}

# Matches one extban token: ~ followed by everything up to (but not
# including) the next ~, e.g. in "~time:60:~join:~country:BD" the tokens
# are "~time:60:", "~join:", "~country:BD".
_TOKEN_RE = re.compile(r'~[^~]*')


def _convert_token(token, table):
    """Convert the selector portion of a single '~selector[:arg[:...]]'
    token using `table` (LETTER_TO_NAME or NAME_TO_LETTER). Leaves the
    argument(s) after the first ':' untouched. Tokens whose selector isn't
    in `table` are returned unchanged."""
    if not token.startswith('~'):
        return token
    body = token[1:]
    if ':' in body:
        selector, rest = body.split(':', 1)
        sep = ':'
    else:
        selector, rest = body, None
        sep = ''
    replacement = table.get(selector, selector)
    if rest is None:
        return '~' + replacement
    return '~' + replacement + sep + rest


def split_stacked(mask):
    """Split a (possibly time-wrapped/stacked) extban mask into its
    individual '~selector[:arg]' tokens, e.g.
    '~time:60:~join:~country:BD' -> ['~time:60:', '~join:', '~country:BD']

    Text before the first '~' (there shouldn't normally be any) is
    returned as-is in the first slot if present."""
    if not mask.startswith('~'):
        return [mask]
    return _TOKEN_RE.findall(mask)


def to_named(mask):
    """Convert every letter-form extban selector in `mask` to its named
    form. Non-extban text and unrecognized selectors pass through
    unchanged. Handles time-wrapped/stacked masks."""
    tokens = split_stacked(mask)
    return ''.join(_convert_token(t, LETTER_TO_NAME) for t in tokens)


def to_letter(mask):
    """Convert every named-form extban selector in `mask` to its letter
    form. Non-extban text and unrecognized selectors pass through
    unchanged. Handles time-wrapped/stacked masks."""
    tokens = split_stacked(mask)
    return ''.join(_convert_token(t, NAME_TO_LETTER) for t in tokens)
