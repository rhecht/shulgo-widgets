"""The line on the Xfce top bar.

Everything the panel shows is decided in bar.py, so it can be checked here — on a Mac with no panel
and no GTK. That is the point of the module existing: the faults in this widget that reached a
Pentium III (an invisible icon, a stale reason that outlived its cause, times that were simply
missing) were all in code a test could not reach.
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shulgo_xfce import bar  # noqa: E402

NOW = 1794509100            # 2026-11-12 13:45:00 -0500


def at(offset_minutes, **extra):
    stamp = NOW + offset_minutes * 60
    row = {'starts_at': time.strftime('%Y-%m-%dT%H:%M:%S-05:00', time.localtime(stamp)),
           'tefillah': 'mincha', 'display_time': '4:32 PM'}
    row.update(extra)

    return row


class Summary(unittest.TestCase):
    def test_says_the_time_and_what_it_is(self):
        """The clock time first, because that is what somebody glances at the panel for."""
        self.assertEqual(bar.summary(at(12), now=NOW, place='Thornhill'),
                         '4:32 PM Mincha · in 12 min')

    def test_never_longer_than_the_room_there_is(self):
        """The panel is beside the clock on a 1024x768 screen. Over the limit, fields go."""
        for name in ('shacharis', 'mincha', 'maariv', 'selichos'):
            for stale in (False, True):
                text = bar.summary(at(90, tefillah=name, display_time='11:45 AM'),
                                   now=NOW, place='Thornhill', stale=stale)
                self.assertLessEqual(len(text), bar.MAX_TXT, text)

    def test_stale_is_marked_even_at_the_cost_of_the_countdown(self):
        """A frozen list that looks current is worse than one with no countdown on it."""
        text = bar.summary(at(12, tefillah='shacharis', display_time='7:15 AM'),
                           now=NOW, place='Thornhill', stale=True)
        self.assertIn('(old)', text)
        self.assertNotIn('in 12 min', text)

    def test_the_mark_is_not_dressed_up_as_a_field(self):
        """"4:32 PM Mincha · (old)" reads as though (old) were part of the minyan. It isn't."""
        text = bar.summary(at(12), now=NOW, place='Thornhill', stale=True)
        self.assertEqual(text, '4:32 PM Mincha (old)')

    def test_falls_back_to_the_name_when_there_is_no_clock_time(self):
        """Some rows come back with a start time and no display_time. Say what we have."""
        text = bar.summary(at(12, display_time=''), now=NOW, place='Thornhill')
        self.assertEqual(text, 'Mincha · in 12 min')

    def test_asks_for_what_it_needs_before_it_claims_to_know_anything(self):
        self.assertEqual(bar.summary(None, pending=True), 'ShulGo: waiting to link')
        self.assertEqual(bar.summary(None, has_key=False), 'ShulGo: not linked')
        self.assertEqual(bar.summary(None, place=None), 'ShulGo: choose a place')

    def test_an_empty_look_ahead_says_how_far_it_looked(self):
        """Not "nothing found", which sounds like a failure. It looked two hours; it says so."""
        self.assertEqual(bar.summary(None, place='Thornhill', window_minutes=120),
                         'No minyan in the next 2 h')
        self.assertEqual(bar.summary(None, place='Thornhill', window_minutes=90),
                         'No minyan in the next 1.5 h')

    def test_the_prompts_come_in_the_order_they_can_be_acted_on(self):
        """No key beats no place: picking a place first and then being told to link is a dead end."""
        self.assertEqual(bar.summary(None, has_key=False, place=None), 'ShulGo: not linked')


class Tooltip(unittest.TestCase):
    def test_lists_a_few_and_names_the_place(self):
        text = bar.tooltip([at(12), at(40, tefillah='maariv', display_time='5:10 PM')],
                           place='Thornhill')
        self.assertIn('ShulGo — Thornhill', text)
        self.assertIn('4:32 PM', text)
        self.assertIn('Maariv', text)

    def test_does_not_run_on_forever(self):
        text = bar.tooltip([at(i * 10) for i in range(1, 20)], place='Thornhill')
        self.assertLessEqual(len(text.strip().split('\n')), bar.TOOLTIP_ROWS + 1)

    def test_says_why_it_is_showing_an_old_list(self):
        text = bar.tooltip([at(12)], place='Thornhill',
                           stale_since='You’re offline — showing the list from 1:45 PM')
        self.assertIn('from 1:45 PM', text)

    def test_an_empty_look_ahead_is_a_sentence_not_a_blank(self):
        self.assertIn('Nothing in the next 120 minutes.',
                      bar.tooltip([], place='Thornhill', window_minutes=120))


class Document(unittest.TestCase):
    def test_is_the_shape_genmon_reads(self):
        text = bar.document(headline=at(12), rows=[at(12)], place='Thornhill', now=NOW)
        self.assertTrue(text.startswith('<txt>'))
        self.assertIn('</txt>', text)
        self.assertIn('<tool>', text)
        self.assertTrue(text.endswith('</tool>\n'))

    def test_a_shul_with_an_ampersand_does_not_break_the_panel(self):
        """Pango markup, so a name like "Beis Medrash & Co" has to be escaped or the panel errors."""
        row = at(12, shul={'display_name': 'Beis Medrash & Co <b>'})
        text = bar.document(headline=row, rows=[row], place='Thornhill', now=NOW)
        self.assertIn('&amp;', text)
        self.assertNotIn('& Co', text)
        self.assertNotIn('<b>', text)

    def test_a_place_name_with_an_ampersand_is_escaped_too(self):
        text = bar.document(headline=None, place='Bathurst & Steeles')
        self.assertIn('Bathurst &amp; Steeles', text)
        self.assertNotIn('Bathurst & Steeles', text)


class TheTooltipAgreesWithTheLine(unittest.TestCase):
    """The two are read together, so they must not say opposite things."""

    def test_an_unlinked_machine_is_not_told_there_are_no_minyanim(self):
        text = bar.document(headline=None, rows=(), place='Thornhill', has_key=False)
        self.assertIn('not linked', text)
        self.assertNotIn('Nothing in the next', text)

    def test_no_place_asks_for_a_place_rather_than_reporting_an_empty_search(self):
        text = bar.document(headline=None, rows=(), place=None)
        self.assertIn('choose a place', text.lower())
        self.assertNotIn('Nothing in the next', text)

    def test_waiting_to_link_says_so_in_both(self):
        text = bar.document(headline=None, rows=(), place='Thornhill', pending=True)
        self.assertIn('waiting to link', text)
        self.assertIn('approved', text)

    def test_an_empty_look_ahead_still_reports_one_when_it_really_is_one(self):
        """The real empty case must survive all of the above."""
        text = bar.document(headline=None, rows=(), place='Thornhill',
                            has_key=True, window_minutes=120)
        self.assertIn('Nothing in the next 120 minutes.', text)


class NoTxtClick(unittest.TestCase):
    def test_there_is_no_txtclick(self):
        """Deliberate. Popping a StatusNotifierItem's menu from a shell command is not something
        there is a cheap way to do, and anything else starts a second interpreter per click on a
        1 GHz machine. The menu is the icon's job; the line is for reading."""
        text = bar.document(headline=at(12), rows=[at(12)], place='Thornhill', now=NOW)
        self.assertNotIn('txtclick', text)


if __name__ == '__main__':
    unittest.main()
