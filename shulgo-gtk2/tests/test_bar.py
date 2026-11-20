# -*- coding: utf-8 -*-
u"""The panel line, and the call the tray actually makes.

This file exists because of a crash on a live CD. bar.document() unpacked a dict with u'' keys into
a keyword call, which Python 2.5 refuses — keyword NAMES must be byte strings, and that was not
relaxed until 2.6.5. The widget died inside __init__, before the tray icon was created, so from the
outside nothing happened at all: the autostart entry ran and no icon appeared.

The GTK3 port has had tests for this module since the day it was written. This package shipped with
one test file, covering the wording only, and nothing here ever called document(). So the last test
in this file is the important one: it calls document() with exactly the arguments tray.py passes,
because a function tested only through arguments a test author chose is tested against the author's
imagination rather than the program.

Python 2.5 unittest: no setUpClass, no assertIn, no skip decorators.
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shulgo_gtk2 import bar

NOW = 1794509100


def at(offset_minutes, **extra):
    stamp = NOW + offset_minutes * 60
    row = {u'starts_at': time.strftime('%Y-%m-%dT%H:%M:%S-05:00', time.localtime(stamp)),
           u'tefillah': u'mincha', u'display_time': u'4:32 PM'}
    row.update(extra)

    return row


class TheLineBesideTheClock(unittest.TestCase):
    def test_says_the_time_and_what_it_is(self):
        self.assertEqual(bar.summary(at(12), now=NOW, place=u'Thornhill'),
                         u'4:32 PM Mincha · in 12 min')

    def test_never_wider_than_the_panel_allows(self):
        for name in (u'shacharis', u'mincha', u'maariv', u'selichos'):
            for stale in (False, True):
                text = bar.summary(at(90, tefillah=name, display_time=u'11:45 AM'),
                                   now=NOW, place=u'Thornhill', stale=stale)
                self.assertTrue(len(text) <= bar.MAX_TXT, text)

    def test_stale_is_marked_even_at_the_cost_of_the_countdown(self):
        text = bar.summary(at(12, tefillah=u'shacharis', display_time=u'7:15 AM'),
                           now=NOW, place=u'Thornhill', stale=True)
        self.assertTrue(u'(old)' in text, text)
        self.assertTrue(u'in 12 min' not in text, text)

    def test_asks_for_what_it_needs_before_claiming_to_know_anything(self):
        self.assertEqual(bar.summary(None, pending=True), u'ShulGo: waiting to link')
        self.assertEqual(bar.summary(None, has_key=False), u'ShulGo: not linked')
        self.assertEqual(bar.summary(None, place=None), u'ShulGo: choose a place')


class TheWholeDocument(unittest.TestCase):
    def test_is_the_shape_genmon_reads(self):
        text = bar.document(headline=at(12), rows=[at(12)], place=u'Thornhill', now=NOW)
        self.assertTrue(text.startswith(u'<txt>'), text)
        self.assertTrue(text.endswith(u'</tool>\n'), text)

    def test_a_shul_with_an_ampersand_does_not_break_the_panel(self):
        row = at(12, shul={u'display_name': u'Beis Medrash & Co <b>'})
        text = bar.document(headline=row, rows=[row], place=u'Thornhill', now=NOW)
        self.assertTrue(u'&amp;' in text, text)
        self.assertTrue(u'<b>' not in text, text)

    def test_a_name_outside_ascii_survives_the_whole_way_through(self):
        u"""simplejson returns unicode, and this is the path it all ends up in."""
        row = at(12, shul={u'display_name': u'Kehillas Grüner Weg — בית'})
        text = bar.document(headline=row, rows=[row], place=u'Grüner Weg', now=NOW)
        self.assertTrue(u'Grüner' in text, repr(text))

    def test_the_call_the_tray_actually_makes(self):
        u"""Every argument tray.py's _write_bar passes, by the same names, in one call.

        This is the test that was missing. document() unpacked a dict with u'' keys into a keyword
        call; Python 2.5 rejects unicode keyword names, so this raised TypeError and took the whole
        widget down in __init__ before the icon existed. Nothing smaller than the real call shape
        would have found it, because the fault was in how the arguments were forwarded, not in what
        any of them meant.
        """
        text = bar.document(
            headline=at(12),
            rows=[at(12), at(40, tefillah=u'maariv', display_time=u'5:10 PM')],
            zmanim=[{u'label': u'Sunrise', u'display': u'7:02 AM'}],
            place=u'Thornhill',
            has_key=True,
            stale=False,
            stale_since=None,
            window_minutes=120,
            pending=False,
        )
        self.assertTrue(text.startswith(u'<txt>'), text)
        self.assertTrue(u'Mincha' in text, text)
        self.assertTrue(u'Sunrise' in text, text)

    def test_the_same_call_in_every_empty_state(self):
        u"""Startup runs this before anything is known, which is exactly when it crashed."""
        for extra in ({u'has_key': False}, {u'place': None}, {u'pending': True},
                      {u'stale': True, u'stale_since': u'You’re offline'}):
            args = {u'headline': None, u'rows': (), u'zmanim': (), u'place': u'Thornhill',
                    u'has_key': True, u'stale': False, u'stale_since': None,
                    u'window_minutes': 120, u'pending': False}
            args.update(extra)
            # Keys here are byte strings on purpose: ** with unicode names is the bug this file is
            # about, and the test must not reproduce it while claiming to guard against it.
            call = {}
            for key in args:
                call[str(key)] = args[key]
            text = bar.document(**call)
            self.assertTrue(text.startswith(u'<txt>'), text)


class TheTooltipAgreesWithTheLine(unittest.TestCase):
    u"""The two are read together, so they must not say opposite things.

    Found by constructing a real Tray under Xvfb: the panel line said "ShulGo: not linked" while
    the tooltip behind it said "Nothing in the next 120 minutes" — which claims the opposite, that
    ShulGo looked and found nothing. Somebody reads the second and concludes there is no minyan
    near them.
    """

    def test_an_unlinked_machine_is_not_told_there_are_no_minyanim(self):
        text = bar.document(headline=None, rows=(), place=u'Thornhill', has_key=False)
        self.assertTrue(u'not linked' in text, text)
        self.assertTrue(u'Nothing in the next' not in text, text)

    def test_no_place_asks_for_one_rather_than_reporting_an_empty_search(self):
        text = bar.document(headline=None, rows=(), place=None)
        self.assertTrue(u'choose a place' in text.lower(), text)
        self.assertTrue(u'Nothing in the next' not in text, text)

    def test_waiting_to_link_says_so_in_both(self):
        text = bar.document(headline=None, rows=(), place=u'Thornhill', pending=True)
        self.assertTrue(u'waiting to link' in text, text)
        self.assertTrue(u'approved' in text, text)

    def test_a_real_empty_look_ahead_still_reports_one(self):
        text = bar.document(headline=None, rows=(), place=u'Thornhill',
                            has_key=True, window_minutes=120)
        self.assertTrue(u'Nothing in the next 120 minutes.' in text, text)


if __name__ == '__main__':
    unittest.main()
