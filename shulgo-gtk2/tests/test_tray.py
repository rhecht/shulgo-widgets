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

import gtk

from shulgo_gtk2 import config, link
from shulgo_gtk2 import tray as tray_module
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
        # A code it has only just asked for is not one to offer replacing.
        self.assertEqual(window.again.get_property('visible'), False)
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


class TheLinkingFinishes(unittest.TestCase):
    u"""Tray._pending_answer, which nothing had ever called.

    It read `self._pending.api_key` where link.Linking says `key`, so the one answer that carries the
    key raised AttributeError — on a real 7.10 install, after an administrator had approved it — and
    the key ShulGo hands out once was lost along with the rest of that function. link.py was tested
    to the hilt on its own; what the tray DID with its answer was not tested at all.

    The answers are fed in directly: nothing here reaches the network or a notification daemon.
    """

    KEY = u'sg_live_' + u'0123456789abcdef' * 2 + u'01234567'

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix='shulgo-link-')
        self.saved = {}
        for name in ('HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'SHULGO_API_KEY'):
            self.saved[name] = os.environ.get(name)
        os.environ['HOME'] = self.home
        os.environ['XDG_CONFIG_HOME'] = os.path.join(self.home, 'config')
        os.environ['XDG_CACHE_HOME'] = os.path.join(self.home, 'cache')
        if 'SHULGO_API_KEY' in os.environ:
            del os.environ['SHULGO_API_KEY']

        self.tray = Tray()
        self.bubbles = []
        self.tray._notify = lambda summary, body: self.bubbles.append((summary, body))

        self.tray._pending = link.Linking({
            u'device_code': u'dev-123', u'user_code': u'ABCD-EFGH',
            u'expires_in': 1200, u'interval': 5})
        config.save_pending(u'dev-123', u'ABCD-EFGH', self.tray._pending.expires_at, 5)
        self.assertTrue(os.path.exists(config.pending_path()))

    def tearDown(self):
        for name in self.saved:
            if self.saved[name] is None:
                if name in os.environ:
                    del os.environ[name]
            else:
                os.environ[name] = self.saved[name]
        shutil.rmtree(self.home, True)

    def test_an_approval_saves_the_key_and_forgets_the_code(self):
        self.tray._pending_answer({u'ok': True, u'data': {u'api_key': self.KEY}})

        self.assertEqual(config.load_api_key(), self.KEY)
        self.assertTrue(os.path.exists(config.key_path()), 'shulgo.conf was not written')
        self.assertTrue(not os.path.exists(config.pending_path()),
                        'the linking file outlived the link')
        self.assertTrue(self.tray._pending is None)
        self.assertTrue(self.tray.api.has_key, 'the running widget did not take the new key')

    def test_once_linked_the_widget_stops_saying_it_is_not(self):
        u"""What the owner actually saw: approved, and still told it wasn't linked."""
        self.tray._pending_answer({u'ok': True, u'data': {u'api_key': self.KEY}})

        # Held in a name: a menu nothing refers to is destroyed at once, taking its labels with it.
        # And PyGTK hands back UTF-8 bytes; compared with unicode as they are, every test passes.
        menu = self.tray._build_menu()
        labels = [item.get_child().get_text().decode('utf-8')
                  for item in menu.get_children()
                  if isinstance(item.get_child(), gtk.Label)]
        self.assertTrue(u'Refresh now' in labels, labels)
        self.assertTrue(u'Link this computer…' not in labels, labels)
        self.assertTrue(u'not linked' not in _read(config.bar_path()).lower(),
                        _read(config.bar_path()))

    def test_an_approval_says_so_in_a_bubble(self):
        self.tray._pending_answer({u'ok': True, u'data': {u'api_key': self.KEY}})
        self.assertEqual(len(self.bubbles), 1, self.bubbles)
        self.assertTrue(u'linked' in self.bubbles[0][0].lower(), self.bubbles)

    def test_a_refusal_forgets_the_code_and_keeps_no_key(self):
        self.tray._pending_answer({u'ok': False, u'code': u'access_denied'})

        self.assertTrue(not os.path.exists(config.pending_path()))
        self.assertTrue(not os.path.exists(config.key_path()))
        self.assertTrue(self.tray._pending is None)
        self.assertEqual(len(self.bubbles), 1, self.bubbles)
        self.assertTrue(u'turned down' in self.bubbles[0][0].lower(), self.bubbles)
        self.assertTrue(u'Link this computer' in self.bubbles[0][1], self.bubbles)

    def _ran_out(self, code):
        self.tray._pending_answer({u'ok': False, u'code': code})

        self.assertTrue(not os.path.exists(config.pending_path()), code)
        self.assertTrue(not os.path.exists(config.key_path()), code)
        self.assertTrue(self.tray._pending is None, code)
        self.assertEqual(len(self.bubbles), 1, self.bubbles)
        self.assertTrue(u'ran out' in self.bubbles[0][0].lower(), self.bubbles)

    def test_an_expired_code_forgets_the_code_and_keeps_no_key(self):
        self._ran_out(u'expired_token')

    def test_a_used_up_code_counts_as_expired(self):
        self._ran_out(u'invalid_grant')

    def test_still_waiting_keeps_the_code_and_says_nothing(self):
        self.tray._pending_answer({u'ok': False, u'code': u'authorization_pending'})

        self.assertTrue(os.path.exists(config.pending_path()))
        self.assertTrue(self.tray._pending is not None)
        self.assertEqual(self.bubbles, [])

    def test_an_open_link_window_hears_the_answer(self):
        u"""It used to say "Waiting for you to approve it" for ever, link or no link."""
        from shulgo_gtk2.windows import LinkWindow

        class StubApi(object):
            has_key = False

            def device_start(self, name, device_name=None):
                return {u'ok': False, u'code': u'network', u'message': u''}

        real = self.tray.api
        self.tray.api = StubApi()
        window = LinkWindow(self.tray)
        self.tray.api = real
        self.assertTrue(self.tray._link_window is window)

        self.tray._pending_answer({u'ok': True, u'data': {u'api_key': self.KEY}})
        self.assertTrue(u'Linked' in window.heading.get_text(), window.heading.get_text())

        window.window.destroy()
        self.assertTrue(self.tray._link_window is None)

    def _probe_window(self):
        u"""A LinkWindow that records asking ShulGo for a code instead of asking."""
        from shulgo_gtk2.windows import LinkWindow
        started = []

        class Probe(LinkWindow):
            def _start(self):
                started.append(True)

        window = Probe(self.tray)
        window.show()

        return window, started

    def test_reopening_the_link_window_shows_the_waiting_code_rather_than_minting_one(self):
        u"""It minted a new code every time, overwriting the one an administrator was about to
        approve — so the approval went to a code nothing was asking about any more."""
        window, started = self._probe_window()

        self.assertEqual(started, [], 'opening the window asked ShulGo for a new code')
        self.assertTrue(u'ABCD-EFGH' in window.code.get_text(), window.code.get_text())
        self.assertEqual(self.tray._pending.device_code, u'dev-123')
        self.assertEqual(config.load_pending()[u'device_code'], u'dev-123')
        self.assertEqual(window.again.get_property('visible'), True)
        window.window.destroy()

    def test_get_a_new_code_replaces_it_only_when_asked(self):
        window, started = self._probe_window()
        window._on_again()

        self.assertEqual(started, [True])
        self.assertTrue(self.tray._pending is None)
        self.assertTrue(config.load_pending() is None)
        self.assertEqual(window.again.get_property('visible'), False)
        window.window.destroy()

    def test_a_turned_down_link_offers_a_new_code_in_the_window(self):
        window, started = self._probe_window()
        self.tray._pending_answer({u'ok': False, u'code': u'access_denied'})
        self.assertEqual(window.again.get_property('visible'), True)
        window.window.destroy()

    def test_an_answer_about_a_replaced_code_is_ignored(self):
        u"""An old code's expired_token, absorbed into the new code, would end the new one."""
        self.tray._pending_answer({u'ok': False, u'code': u'expired_token'}, u'old-code')

        self.assertTrue(self.tray._pending is not None)
        self.assertEqual(self.tray._pending.device_code, u'dev-123')
        self.assertTrue(os.path.exists(config.pending_path()))
        self.assertEqual(self.bubbles, [])

    def test_an_answer_about_the_current_code_still_counts(self):
        self.tray._pending_answer({u'ok': True, u'data': {u'api_key': self.KEY}}, u'dev-123')
        self.assertEqual(config.load_api_key(), self.KEY)

    def test_a_timer_set_for_a_replaced_code_polls_nothing(self):
        u"""Each new code used to start a second chain of polls beside the old one."""
        import time
        polled = []
        self.tray._do_poll = lambda code: polled.append(code)

        self.tray._poll_pending(u'old-code')
        time.sleep(0.3)
        self.assertEqual(polled, [])

        self.tray._poll_pending(u'dev-123')
        for _ in range(20):
            if polled:
                break
            time.sleep(0.1)
        self.assertEqual(polled, [u'dev-123'])

    def test_a_linking_left_over_from_before_a_reboot_keeps_its_own_deadline(self):
        u"""The file holds a deadline; it was read as a fresh ten-minute code."""
        import time
        config.save_pending(u'dev-456', u'WXYZ-1234', time.time() + 3 * 86400, 5)
        self.tray._pending = None
        original = self.tray._poll_pending
        self.tray._poll_pending = lambda: False
        try:
            self.tray._watch_pending()
        finally:
            self.tray._poll_pending = original
        self.assertTrue(self.tray._pending.seconds_left() > 86400,
                        self.tray._pending.seconds_left())


class BubblesAreOptional(unittest.TestCase):
    u"""python-notify is not in the build container and not guaranteed on a stripped install."""

    def test_no_pynotify_is_not_an_error(self):
        saved = tray_module.pynotify
        tray_module.pynotify = None
        try:
            self.assertEqual(tray_module.bubble(None, u'a', u'b'), False)
        finally:
            tray_module.pynotify = saved

    def test_a_broken_notification_daemon_is_not_an_error(self):
        class Broken(object):
            class Notification(object):
                def __init__(self, *args):
                    pass

                def attach_to_status_icon(self, icon):
                    pass

                def show(self):
                    raise RuntimeError('no daemon')

        saved = tray_module.pynotify
        tray_module.pynotify = Broken
        try:
            self.assertEqual(tray_module.bubble(None, u'a', u'b'), False)
        finally:
            tray_module.pynotify = saved

    def test_the_bubble_points_at_the_tray_icon(self):
        seen = []

        class Recorder(object):
            class Notification(object):
                def __init__(self, summary, body, icon):
                    seen.append((summary, body, icon))

                def attach_to_status_icon(self, icon):
                    seen.append(icon)

                def show(self):
                    return True

        saved = tray_module.pynotify
        tray_module.pynotify = Recorder
        try:
            import gtk
            icon = gtk.StatusIcon()
            self.assertEqual(tray_module.bubble(icon, u'Linked', u'Body'), True)
        finally:
            tray_module.pynotify = saved
        self.assertEqual(seen[0][:2], (u'Linked', u'Body'))
        self.assertTrue(seen[1] is icon)


def _read(path):
    try:
        handle = open(path, 'rb')
    except EnvironmentError:
        return u''
    try:
        return handle.read().decode('utf-8')
    finally:
        handle.close()


if __name__ == '__main__':
    unittest.main()
