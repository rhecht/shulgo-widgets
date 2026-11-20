# -*- coding: utf-8 -*-
u"""Construct the real Tray. Needs a display, so it is not part of `make check`.

Both startup crashes on the live CD were in Tray.__init__, and `make check` could not reach it: it
needs an X server. The 7.10 session pointed out that gutsy has Xvfb in main, which makes this a
three-line problem rather than an impossible one.

It is a separate target rather than a test that skips itself when DISPLAY is unset. A skip is a
silent absence, and this package has already been bitten once by a check that quietly stopped
running. `make check-display` either runs this or fails loudly because there is no X.

    make check-display

Does not call gtk.main(): only __init__, which is where the faults were, and the menu build. With
no place configured, refresh() returns before starting any network work, so this touches nothing
outside the machine it runs on.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.environ.get('DISPLAY'):
    sys.stderr.write(
        'test_tray.py needs an X server. Run it as:\n'
        '    Xvfb :5 -screen 0 1024x768x16 & DISPLAY=:5 python tests/test_tray.py\n'
        'or use `make check-display`.\n')
    sys.exit(2)

from shulgo_gtk2 import config
from shulgo_gtk2.tray import Tray, icon_path


class TheTrayStarts(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix='shulgo-tray-')
        self.saved = {}
        for name in ('HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME'):
            self.saved[name] = os.environ.get(name)
        os.environ['HOME'] = self.home
        os.environ['XDG_CONFIG_HOME'] = os.path.join(self.home, 'config')
        os.environ['XDG_CACHE_HOME'] = os.path.join(self.home, 'cache')

    def tearDown(self):
        for name in self.saved:
            if self.saved[name] is None:
                del os.environ[name]
            else:
                os.environ[name] = self.saved[name]
        shutil.rmtree(self.home, True)

    def test_it_constructs_on_a_machine_with_nothing_configured(self):
        u"""The whole bug, in one line: this raised, so no icon ever appeared."""
        tray = Tray()
        self.assertTrue(tray is not None)

    def test_the_icon_is_not_invisible(self):
        u"""An icon that fails to resolve is not an error. It is an empty space in the panel, and
        it is indistinguishable from a widget that never started — which has shipped before."""
        self.assertTrue(icon_path() is not None,
                        'no icon file found; the tray would be invisible')
        tray = Tray()
        self.assertEqual(tray.icon.get_visible(), True)
        has_image = (tray.icon.get_pixbuf() is not None) or (tray.icon.get_file() is not None)
        self.assertTrue(has_image, 'the status icon carries no image')

    def test_the_menu_builds_before_anything_has_been_fetched(self):
        tray = Tray()
        items = tray._build_menu().get_children()
        self.assertTrue(len(items) > 0)

    def test_startup_leaves_a_panel_line_that_says_what_to_do(self):
        Tray()
        path = config.bar_path()
        self.assertTrue(os.path.exists(path), 'no panel line written at startup')
        handle = open(path, 'rb')
        try:
            text = handle.read().decode('utf-8')
        finally:
            handle.close()
        self.assertTrue(u'not linked' in text, text)
        # And the tooltip must not contradict it by reporting an empty search.
        self.assertTrue(u'Nothing in the next' not in text, text)


if __name__ == '__main__':
    unittest.main()
