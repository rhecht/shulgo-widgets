"""The two rules that decide what a person actually sees.

These are ports of store.js's _dropPast and headline. They can't be compared to the JavaScript the
way fmt.py is — store.js needs a transport, a config object and a running clock — so the rules are
asserted here directly, and each test says which behaviour of the original it is pinning.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shulgo_xfce.pick import headline, still_ahead  # noqa: E402

NOW = 1794509100            # 2026-11-12 13:45:00 -0500


def at(offset_minutes, **extra):
    """A minyan starting this many minutes from NOW."""
    stamp = NOW + offset_minutes * 60
    import time
    row = {'starts_at': time.strftime('%Y-%m-%dT%H:%M:%S-05:00', time.localtime(stamp))}
    row.update(extra)

    return row


class WhatStaysOnTheList(unittest.TestCase):
    def test_future_minyanim_stay(self):
        rows = [at(5), at(40), at(90)]
        self.assertEqual(len(still_ahead(rows, NOW)), 3)

    def test_one_that_began_forty_seconds_ago_is_still_yours(self):
        """store.js keeps anything after now - 60: you can still walk into it."""
        rows = still_ahead([{'starts_at': '2026-11-12T13:44:20-05:00'}], NOW)
        self.assertEqual(len(rows), 1)

    def test_one_that_began_two_minutes_ago_is_gone(self):
        rows = still_ahead([{'starts_at': '2026-11-12T13:43:00-05:00'}], NOW)
        self.assertEqual(rows, [])

    def test_a_time_we_cannot_read_is_kept_not_dropped(self):
        """A missing starts_at is not evidence the minyan is over."""
        self.assertEqual(len(still_ahead([{'starts_at': None}], NOW)), 1)
        self.assertEqual(len(still_ahead([{}], NOW)), 1)
        self.assertEqual(len(still_ahead([{'starts_at': 'soon-ish'}], NOW)), 1)

    def test_the_order_is_left_alone(self):
        """The API answers soonest first; re-sorting here would override what else it knows."""
        rows = [at(90, id='c'), at(5, id='a'), at(40, id='b')]
        self.assertEqual([r['id'] for r in still_ahead(rows, NOW)], ['c', 'a', 'b'])

    def test_nothing_in_nothing_out(self):
        self.assertEqual(still_ahead([], NOW), [])
        self.assertEqual(still_ahead(None, NOW), [])


class WhichOneThePanelNames(unittest.TestCase):
    def test_the_soonest_you_can_actually_make(self):
        """The whole point: a mincha four minutes off with an eight-minute drive is not the answer."""
        rows = [at(4, id='too-soon', can_make_it=False), at(25, id='reachable', can_make_it=True)]
        self.assertEqual(headline(rows)['id'], 'reachable')

    def test_a_definite_yes_beats_an_unknown_however_far_off(self):
        """The rule scans ALL rows for can_make_it true before it will settle for an unknown, so a
        minyan ShulGo says you can make wins over a nearer one it couldn't route. Being told yes is
        worth more than being told nothing, even at twenty minutes' difference."""
        rows = [at(4, id='no', can_make_it=False), at(10, id='unrouted', can_make_it=None),
                at(30, id='yes', can_make_it=True)]
        self.assertEqual(headline(rows)['id'], 'yes')

    def test_unknown_beats_known_impossible(self):
        """With no definite yes anywhere, an unrouted minyan still beats one that can't be made:
        null means ShulGo couldn't work it out, which is not the same answer as no."""
        rows = [at(4, id='no', can_make_it=False), at(10, id='unrouted', can_make_it=None),
                at(30, id='also-no', can_make_it=False)]
        self.assertEqual(headline(rows)['id'], 'unrouted')

    def test_a_missing_flag_counts_as_unknown(self):
        rows = [at(4, id='no', can_make_it=False), at(10, id='silent')]
        self.assertEqual(headline(rows)['id'], 'silent')

    def test_when_none_can_be_made_the_soonest_still_shows(self):
        """Better to say "mincha in 4 min, you won't make it" than to leave the panel blank."""
        rows = [at(4, id='first', can_make_it=False), at(30, id='second', can_make_it=False)]
        self.assertEqual(headline(rows)['id'], 'first')

    def test_false_and_none_are_not_treated_alike(self):
        self.assertEqual(headline([at(5, id='n', can_make_it=None)])['id'], 'n')
        self.assertEqual(headline([at(5, id='f', can_make_it=False)])['id'], 'f')

    def test_nothing_to_name(self):
        self.assertIsNone(headline([]))
        self.assertIsNone(headline(None))


if __name__ == '__main__':
    unittest.main()
