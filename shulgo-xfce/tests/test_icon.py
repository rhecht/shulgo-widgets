"""Where the tray icon comes from.

Written after the first real run of this widget, on an emulated Pentium III, where the tray
registered itself with the panel perfectly and displayed nothing: `shulgo` is an icon *name*, and a
name resolves only once the file is in an icon theme. Run from a checkout there was nothing to
resolve, and the panel drew nothing — no error, no warning, no icon.

These are plain functions of plain facts precisely so they can be tested on a machine with no GTK,
no display and no icon theme, which is where this widget is written and is the reason the bug got as
far as a Pentium III before it got as far as a test.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shulgo_xfce import icon  # noqa: E402


class WhatToDoAboutTheIcon(unittest.TestCase):
    def test_the_theme_wins_when_it_has_it(self):
        """A package install puts a properly themed icon in hicolor; a checkout must not override."""
        self.assertEqual(icon.plan(True, '/some/checkout/packaging'), icon.IN_THEME)
        self.assertEqual(icon.plan(True, None), icon.IN_THEME)

    def test_the_bundled_copy_is_used_when_the_theme_has_nothing(self):
        self.assertEqual(icon.plan(False, '/some/checkout/packaging'), icon.BUNDLED)

    def test_neither_is_reported_rather_than_shrugged_at(self):
        self.assertEqual(icon.plan(False, None), icon.MISSING)


class FindingTheBundledFile(unittest.TestCase):
    def test_it_finds_the_real_one_in_this_checkout(self):
        directory = icon.bundled_dir()
        self.assertIsNotNone(directory, 'packaging/shulgo.svg should be found from the package')
        self.assertTrue(os.path.isfile(icon.bundled_file(directory)))

    def test_it_is_found_relative_to_the_module_not_the_working_directory(self):
        """A tray widget is started from a desktop file; its working directory is anybody's guess."""
        here = os.getcwd()
        try:
            os.chdir(tempfile.gettempdir())
            self.assertIsNotNone(icon.bundled_dir())
        finally:
            os.chdir(here)

    def test_an_installed_layout_has_no_packaging_directory(self):
        """/usr/lib/shulgo-xfce/shulgo_xfce/ has no packaging/ beside it — and should not."""
        with tempfile.TemporaryDirectory() as d:
            fake_module = os.path.join(d, 'shulgo_xfce', 'icon.py')
            os.makedirs(os.path.dirname(fake_module))
            self.assertIsNone(icon.bundled_dir(fake_module))

    def test_a_packaging_directory_without_the_icon_does_not_count(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'shulgo_xfce'))
            os.makedirs(os.path.join(d, 'packaging'))
            self.assertIsNone(icon.bundled_dir(os.path.join(d, 'shulgo_xfce', 'icon.py')))

    def test_it_counts_once_the_icon_is_there(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'shulgo_xfce'))
            os.makedirs(os.path.join(d, 'packaging'))
            open(os.path.join(d, 'packaging', 'shulgo.svg'), 'w').close()
            found = icon.bundled_dir(os.path.join(d, 'shulgo_xfce', 'icon.py'))
            self.assertEqual(found, os.path.join(d, 'packaging'))


class WhatCheckSays(unittest.TestCase):
    """--check exists to catch silent failures, and it missed this one. It must not again."""

    def test_the_missing_case_says_the_icon_will_not_appear(self):
        said = icon.describe(icon.MISSING)
        self.assertIn('NOT FOUND', said)
        self.assertIn('show nothing', said)

    def test_the_bundled_case_says_it_works_but_only_here(self):
        said = icon.describe(icon.BUNDLED, '/checkout/packaging')
        self.assertIn('/checkout/packaging', said)
        self.assertIn('only for this checkout', said)

    def test_the_happy_case_is_short(self):
        self.assertEqual(icon.describe(icon.IN_THEME), 'icon: found in the icon theme')

    def test_every_state_says_something(self):
        for state in (icon.IN_THEME, icon.BUNDLED, icon.MISSING):
            self.assertTrue(icon.describe(state, '/x').startswith('icon: '))


if __name__ == '__main__':
    unittest.main()
