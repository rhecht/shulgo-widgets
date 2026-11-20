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


class TheWindowsAndTheMenu(unittest.TestCase):
    u"""The parts QEMU could not reach.

    On the live CD the mouse never got through to the guest, so the popup menu, the settings window
    and the link window have never been opened by anybody. They are several hundred lines of PyGTK
    written against a toolkit from 2007 by someone who could not run it — gtk.Table, combo boxes,
    gtk.HButtonBox — and until something constructs them, "it compiles" is the whole of what is
    known about them.

    Nothing here touches the network. The link window is given a stub that answers the way the API
    would, because the real call mints a device code and emails Rafi's administrators.
    """

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix='shulgo-win-')
        self.saved = {}
        for name in ('HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME'):
            self.saved[name] = os.environ.get(name)
        os.environ['HOME'] = self.home
        os.environ['XDG_CONFIG_HOME'] = os.path.join(self.home, 'config')
        os.environ['XDG_CACHE_HOME'] = os.path.join(self.home, 'cache')
        self.tray = Tray()

    def tearDown(self):
        for name in self.saved:
            if self.saved[name] is None:
                del os.environ[name]
            else:
                os.environ[name] = self.saved[name]
        shutil.rmtree(self.home, True)

    def test_the_menu_pops_up(self):
        u"""Building it is not the same as showing it: show_all walks every child widget."""
        import gtk
        menu = self.tray._build_menu()
        menu.show_all()
        for item in menu.get_children():
            self.assertTrue(isinstance(item, gtk.MenuItem)
                            or isinstance(item, gtk.SeparatorMenuItem))

    def test_the_menu_still_builds_once_there_are_minyanim_and_zmanim(self):
        u"""The empty menu is the easy one. This is the shape people actually see."""
        self.tray.state[u'minyanim'] = [{
            u'tefillah': u'mincha', u'display_time': u'4:32 PM',
            u'starts_at': u'2099-01-01T00:00:00Z',
            u'shul': {u'display_name': u'Beis Medrash & Co'},
            u'distance_miles': 1.2,
        }]
        self.tray.state[u'zmanim'] = {
            u'sunrise': {u'label': u'Sunrise', u'time': u'2099-01-01T12:00:00Z'},
        }
        self.tray.settings[u'place'] = u'Thornhill'
        self.tray.settings[u'lat'] = u'43.8'
        self.tray.settings[u'lng'] = u'-79.4'
        menu = self.tray._build_menu()
        menu.show_all()
        self.assertTrue(len(menu.get_children()) > 3)

    def test_the_settings_window_builds_and_shows(self):
        from shulgo_gtk2.windows import SettingsWindow
        window = SettingsWindow(self.tray)
        window.show()
        self.assertTrue(window.window is not None)
        window.window.destroy()

    def test_the_settings_window_saves_without_a_lookup(self):
        u"""Somebody types a place and presses Save without pressing Look it up."""
        from shulgo_gtk2.windows import SettingsWindow
        window = SettingsWindow(self.tray)
        window.place_entry.set_text(u'Thornhill')
        window.window_entry.set_text(u'90')
        window._on_save()
        self.assertEqual(config.load_settings()[u'window-minutes'], u'90')

    def test_the_link_window_builds_and_shows_a_code(self):
        from shulgo_gtk2.windows import LinkWindow

        class StubApi(object):
            has_key = False

            def device_start(self, name, device_name=None):
                return {u'ok': True, u'data': {
                    u'device_code': u'dev-123', u'user_code': u'ABCD-EFGH',
                    u'verification_uri': u'https://shulgo.com/link',
                    u'expires_in': 1200, u'interval': 5}}

            def device_poll(self, code):
                return {u'ok': False, u'code': u'authorization_pending'}

        self.tray.api = StubApi()
        window = LinkWindow(self.tray)
        window._started(self.tray.api.device_start(u'test'))
        self.assertTrue(u'ABCD-EFGH' in window.code.get_text(), window.code.get_text())
        window.window.destroy()

    def test_the_link_window_says_offline_before_it_says_ask_an_administrator(self):
        u"""Told to ask an administrator while the machine has no internet, somebody goes and asks,
        and then waits for nothing."""
        from shulgo_gtk2.windows import LinkWindow

        class DeadApi(object):
            has_key = False

            def device_start(self, name, device_name=None):
                return {u'ok': False, u'code': u'network', u'message': u''}

        self.tray.api = DeadApi()
        window = LinkWindow(self.tray)
        window._started(self.tray.api.device_start(u'test'))
        words = window.heading.get_text() + u' ' + window.body.get_text()
        self.assertTrue(u'internet' in words.lower() or u'reach' in words.lower(), words)
        self.assertTrue(u'administrator' not in words.lower(), words)
        window.window.destroy()


if __name__ == '__main__':
    unittest.main()
