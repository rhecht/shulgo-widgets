# -*- coding: utf-8 -*-
u"""Walk the startup path, minus the GTK.

A traceback in Tray.__init__ does not look like a crash on this hardware. The autostart entry runs,
no icon appears, and that is the whole of the user's experience — there is no window to show an
error in and nobody is watching a terminal. The widget shipped once in exactly that state.

Tray() itself cannot be built here: it needs a display. But almost everything __init__ does before
it touches a widget is ordinary Python, and that is what this file exercises, in order, against a
scratch HOME. Written for 2.5: no setUpClass, no assertIn, no skip decorators, no tempfile context
managers.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shulgo_gtk2 import api, bar, config, curl, fmt, link, pick


class EveryModuleImports(unittest.TestCase):
    def test_the_whole_package_loads(self):
        u"""A syntax error or a missing 2.6 builtin anywhere is a widget that never starts."""
        import shulgo_gtk2.main
        import shulgo_gtk2.tray
        import shulgo_gtk2.windows
        for module in (api, bar, config, curl, fmt, link, pick,
                       shulgo_gtk2.main, shulgo_gtk2.tray, shulgo_gtk2.windows):
            self.assertTrue(module is not None)


class StartupOnACleanMachine(unittest.TestCase):
    u"""The first run, when nothing has been configured and no file exists yet."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix='shulgo-home-')
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

    def test_reading_settings_that_do_not_exist_yet(self):
        u"""IOError is not OSError on Python 2, and this is the read that found that out."""
        values = config.load_settings()
        self.assertEqual(values[u'panel-line'], u'yes')
        self.assertEqual(config.load_api_key(), u'')
        self.assertTrue(config.saved_place(values) is None)
        self.assertTrue(config.load_pending() is None)

    def test_the_whole_startup_sequence_in_order(self):
        u"""What Tray.__init__ does, up to the first widget."""
        settings = config.load_settings()
        cache = api.Cache(config.cache_path())
        client = api.ShulGoApi(base_url=settings.get(u'api-base-url'),
                               api_key=config.load_api_key(), cache=cache)
        self.assertEqual(client.has_key, False)

        state = {u'minyanim': [], u'zmanim': {}, u'updated': 0,
                 u'why': None, u'whyMessage': None, u'staleSince': 0}
        rows = pick.still_ahead(state[u'minyanim'])
        place = config.saved_place(settings)

        # The call that killed it. Written out the long way, as tray.py writes it.
        document = bar.document(
            headline=pick.headline(rows) if place else None,
            rows=rows,
            zmanim=fmt.zmanim_list(state[u'zmanim']),
            place=place[2] if place else None,
            has_key=client.has_key,
            stale=False,
            stale_since=None,
            window_minutes=config.as_int(settings, u'window-minutes'),
            pending=False,
        )
        self.assertTrue(document.startswith(u'<txt>'), document)
        # Nothing configured, so the panel must say what to do rather than sit blank.
        self.assertTrue(u'ShulGo' in document, document)

        config.save_bar(document)
        self.assertTrue(os.path.exists(config.bar_path()))
        handle = open(config.bar_path(), 'rb')
        try:
            self.assertEqual(handle.read().decode('utf-8'), document)
        finally:
            handle.close()

        self.assertEqual(os.stat(config.bar_path()).st_mode & 0777, 0600)

        config.clear_bar()
        self.assertEqual(os.path.exists(config.bar_path()), False)

    def test_saving_and_reading_settings_back(self):
        values = config.load_settings()
        values[u'place'] = u'Grüner Weg'
        values[u'lat'] = u'48.2'
        values[u'lng'] = u'16.3'
        config.save_settings(values)

        again = config.load_settings()
        place = config.saved_place(again)
        self.assertTrue(place is not None)
        self.assertEqual(place[2], u'Grüner Weg')

    def test_the_api_key_file_is_not_readable_by_anyone_else(self):
        config.save_api_key(u'sg_live_' + u'0123456789abcdef' * 2 + u'01234567')
        self.assertEqual(os.stat(config.key_path()).st_mode & 0777, 0600)
        self.assertTrue(config.load_api_key().startswith(u'sg_live_'))


if __name__ == '__main__':
    unittest.main()
