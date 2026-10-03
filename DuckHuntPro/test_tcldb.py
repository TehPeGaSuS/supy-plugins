"""Unit tests for tcldb.py (no Limnoria needed): run from this directory with
`python3 -m unittest test_tcldb`."""

import unittest

import tcldb

HEADER = (
    '--- Duck Hunt v2.11 - Base de donnees contenant les donnees des participants ---\n'
    '--- structure : #chan1 {player1 {gun jammed ...}} ---\n'
    '---\t\tgun : 1 = armed, 0 = temporary, -1 = permanent.\n'
    '---\n'
)

BOB = ('gun 1 jammed 0 current_ammo_clip 5 remaining_ammo_clips 2 xp 150 ducks_shot 12 '
       'missed_shots 3 empty_shots 0 humans_shot 1 wild_shots 4 bullets_received 2 '
       'deflected_bullets 1 deaths 1 confiscated_weapons 2 jammed_weapons 1 best_time 2.345 '
       'cumul_reflex_time 31000 nick Bob items {{4102444800 3 -} {- 7 1} {4102444800 10 6} '
       '{4102444800 8 4} {- 15 Mallory} {1 6 -}} golden_ducks_shot 1 last_activity 1790000000')
ODD = ('gun -1 jammed 1 current_ammo_clip 0 remaining_ammo_clips 0 xp -7 ducks_shot 0 '
       'missed_shots 0 empty_shots 0 humans_shot 0 wild_shots 0 bullets_received 0 '
       'deflected_bullets 0 deaths 0 confiscated_weapons 0 jammed_weapons 0 best_time -1 '
       'cumul_reflex_time 0 nick Odd\\[away\\] items {} golden_ducks_shot 0 last_activity -1')


class ParseTests(unittest.TestCase):
    def testListWithBracesQuotesAndEscapes(self):
        self.assertEqual(tcldb.parseList('a {b c} "d e" f\\ g {h {i j}} k\\[l\\]'),
                         ['a', 'b c', 'd e', 'f g', 'h {i j}', 'k[l]'])

    def testBracesWithEscapedBraceInside(self):
        self.assertEqual(tcldb.parseList('{a \\{ b} c'), ['a \\{ b', 'c'])

    def testDict(self):
        self.assertEqual(tcldb.parseDict('x 1 y {2 3}'), {'x': '1', 'y': '2 3'})

    def testBadInputs(self):
        for bad in ('{unclosed', '"unclosed'):
            with self.assertRaises(tcldb.TclParseError):
                tcldb.parseList(bad)
        with self.assertRaises(tcldb.TclParseError):
            tcldb.parseDict('a b c')

    def testHeaderIsSkippedAndNeedsItsTerminator(self):
        self.assertEqual(tcldb.splitHeader(HEADER + 'BODY'), 'BODY')
        self.assertEqual(tcldb.splitHeader('no header here'), 'no header here')
        with self.assertRaises(tcldb.TclParseError):
            tcldb.splitHeader('--- header\nnever closed')


class ConvertTests(unittest.TestCase):
    NOW = 1800000000

    def db(self, channels=None):
        text = HEADER + ' '.join('%s {%s}' % (chan, players)
                                 for chan, players in (channels or {
                                     '#test': 'bob {%s} {odd nick} {%s}' % (BOB, ODD)}).items())
        return tcldb.loadText(text)

    def testLoadsEveryChannelAndPlayer(self):
        data = self.db()
        self.assertEqual(list(data), ['#test'])
        self.assertEqual(sorted(data['#test']), ['bob', 'odd nick'])
        self.assertEqual(data['#test']['bob']['xp'], '150')

    def testBracedNickWithSpaces(self):
        self.assertEqual(tcldb.convertPlayer({'nick': 'Big Bob'}, 'big bob')['display_nick'], 'Big Bob')
        self.assertEqual(tcldb.parseDict('nick {Big Bob} xp 2'), {'nick': 'Big Bob', 'xp': '2'})

    def testBracedChannelNamesAndEmptyDatabase(self):
        data = tcldb.loadText(HEADER + '{#a} {bob {xp 3}}')
        self.assertEqual(data, {'#a': {'bob': {'xp': '3'}}})
        self.assertEqual(tcldb.loadText(HEADER), {})

    def testPlayerFieldsMapToThePluginSchema(self):
        bob = tcldb.convertChannel(self.db()['#test'], self.NOW)['bob']
        self.assertEqual(bob['display_nick'], 'Bob')
        self.assertEqual((bob['xp'], bob['gun_state'], bob['jammed']), (150, 'armed', False))
        self.assertEqual((bob['clip_ammo'], bob['clips_left']), (5, 2))
        self.assertEqual(bob['last_activity'], 1790000000)
        st = bob['stats']
        self.assertEqual((st['killed'], st['golden_killed'], st['missed']), (12, 1, 3))
        self.assertEqual((st['humans_shot'], st['wild_shots'], st['empty_shots']), (1, 4, 0))
        self.assertEqual((st['bullets_received'], st['deflected'], st['deaths']), (2, 1, 1))
        self.assertEqual((st['confiscations'], st['jams']), (2, 1))
        self.assertEqual(st['best_time_ms'], 2345)
        self.assertEqual(st['reflex_ms'], 31000)

    def testItemsKeepTheirMeaningAndExpiredOnesAreDropped(self):
        items = tcldb.convertChannel(self.db()['#test'], self.NOW)['bob']['items']
        self.assertEqual(sorted(items), ['ap_ammo', 'four_leaf_clover', 'infrared_detector',
                                         'sand', 'sight'])
        self.assertEqual(items['ap_ammo'], {'expires_at': 4102444800, 'uses_left': None, 'value': None})
        self.assertEqual(items['sight'], {'expires_at': None, 'uses_left': 1, 'value': None})
        self.assertEqual(items['four_leaf_clover']['value'], 6)
        self.assertEqual(items['infrared_detector']['uses_left'], 4)
        self.assertEqual(items['sand']['value'], 'Mallory')
        self.assertNotIn('grease', items)           # expired (timestamp 1)

    def testPermanentConfiscationNegativeXpAndEscapedNick(self):
        odd = tcldb.convertChannel(self.db()['#test'], self.NOW)['odd nick']
        self.assertEqual(odd['display_nick'], 'Odd[away]')
        self.assertEqual((odd['gun_state'], odd['jammed'], odd['xp']), ('confiscated_permanent', True, -7))
        self.assertEqual((odd['clip_ammo'], odd['clips_left']), (0, 0))
        self.assertTrue(odd['stats']['best_time_ms'] is None and odd['last_activity'] is None)

    def testTemporaryConfiscation(self):
        p = tcldb.convertPlayer({'gun': '0'}, 'x', self.NOW)
        self.assertEqual(p['gun_state'], 'confiscated')

    def testOldDatabaseWithMissingFieldsGetsTheOriginalDefaults(self):
        p = tcldb.convertPlayer({'xp': '40', 'ducks_shot': '3'}, 'carol', self.NOW)
        self.assertEqual((p['display_nick'], p['gun_state'], p['jammed']), ('carol', 'armed', False))
        self.assertTrue(p['clip_ammo'] is None and p['clips_left'] is None)  # filled from the level
        self.assertEqual((p['items'], p['last_activity']), ({}, None))
        self.assertEqual(p['stats']['killed'], 3)
        self.assertEqual(p['stats']['golden_killed'], 0)

    def testConvertedPlayersHaveEveryStatTheDatabaseHas(self):
        # The plugin's per-player stats dict (db._newPlayer) has exactly these keys.
        keys = {'killed', 'golden_killed', 'missed', 'empty_shots', 'humans_shot', 'wild_shots',
                'bullets_received', 'deflected', 'absorbed', 'confiscations', 'jams', 'deaths',
                'best_time_ms', 'total_time_ms', 'timed_shots', 'reflex_ms'}
        self.assertEqual(set(tcldb.convertPlayer({}, 'x', self.NOW)['stats']), keys)


if __name__ == '__main__':
    unittest.main()
