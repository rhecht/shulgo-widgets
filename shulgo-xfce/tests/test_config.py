"""The key file and the settings file: the format, the permissions, and the trap they avoid.

The one that matters is test_the_gnome_half_can_read_what_we_write. The key file is shared with the
GNOME extension and the ShulGo GTK app, which read it with their own regex, so "compatible" has to
mean byte-level compatible and not roughly the same idea.
"""

import os
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shulgo_xfce import config  # noqa: E402

# Copied character for character out of jewbuntu/src/shulgo/gnome/settings.js. If this test fails,
# either that file changed or ours did, and the two halves have stopped sharing a key.
GNOME_KEY_LINE = re.compile(r'^\s*api-key\s*=\s*(\S+)\s*$')

A_KEY = 'sg_live_' + 'ab12cd34' * 5


class InATemporaryHome:
    """Points XDG_CONFIG_HOME and XDG_CACHE_HOME somewhere disposable."""

    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.saved = {k: os.environ.get(k) for k in
                      ('XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'SHULGO_API_KEY')}
        os.environ['XDG_CONFIG_HOME'] = os.path.join(self.dir.name, 'config')
        os.environ['XDG_CACHE_HOME'] = os.path.join(self.dir.name, 'cache')
        os.environ.pop('SHULGO_API_KEY', None)

        return self

    def __exit__(self, *_):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.dir.cleanup()


class TheKeyFile(unittest.TestCase):
    def test_it_round_trips(self):
        with InATemporaryHome():
            self.assertEqual(config.load_api_key(), '')
            config.save_api_key(A_KEY)
            self.assertEqual(config.load_api_key(), A_KEY)

    def test_only_its_owner_can_read_it(self):
        with InATemporaryHome():
            config.save_api_key(A_KEY)
            mode = stat.S_IMODE(os.stat(config.key_path()).st_mode)
            self.assertEqual(mode, 0o600, 'an API key must not be readable by anything else')

    def test_the_gnome_half_can_read_what_we_write(self):
        with InATemporaryHome():
            config.save_api_key(A_KEY)
            with open(config.key_path(), encoding='utf-8') as fh:
                lines = fh.read().split('\n')
        found = [GNOME_KEY_LINE.match(line) for line in lines]
        found = [m.group(1) for m in found if m]
        self.assertEqual(found, [A_KEY],
                         'the GNOME extension reads this file with its own regex — exactly one '
                         'api-key line, and this is it')

    def test_we_can_read_what_the_gnome_half_writes(self):
        """Its saveApiKey writes a comment block and then the key. Reproduced here verbatim."""
        with InATemporaryHome() as home:
            path = config.key_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write('\n'.join([
                    '# ShulGo API key for the JewBuntu widget.',
                    '# Ask your ShulGo administrator for a key.',
                    'api-key=%s' % A_KEY,
                    '',
                ]))
            self.assertEqual(config.load_api_key(), A_KEY)
            del home

    def test_an_empty_key_removes_the_file_rather_than_leaving_a_blank_one(self):
        with InATemporaryHome():
            config.save_api_key(A_KEY)
            config.save_api_key('')
            self.assertFalse(os.path.exists(config.key_path()))
            self.assertEqual(config.load_api_key(), '')

    def test_the_environment_wins_so_a_test_run_leaves_the_saved_key_alone(self):
        with InATemporaryHome():
            config.save_api_key(A_KEY)
            os.environ['SHULGO_API_KEY'] = '  sg_live_other  '
            self.assertEqual(config.load_api_key(), 'sg_live_other')


class TheSettingsFile(unittest.TestCase):
    def test_defaults_when_nothing_is_saved(self):
        with InATemporaryHome():
            values = config.load_settings()
            self.assertEqual(values['api-base-url'], 'https://shulgo.com/api/v1')
            self.assertEqual(values['refresh-seconds'], '900')
            self.assertIsNone(config.saved_place(values))

    def test_it_round_trips(self):
        with InATemporaryHome():
            values = config.load_settings()
            values.update({'place': 'Thornhill', 'lat': '43.8126', 'lng': '-79.4237',
                           'window-minutes': '90'})
            config.save_settings(values)

            back = config.load_settings()
            self.assertEqual(back['place'], 'Thornhill')
            self.assertEqual(config.as_int(back, 'window-minutes'), 90)
            self.assertEqual(config.saved_place(back), (43.8126, -79.4237, 'Thornhill'))

    def test_a_name_we_do_not_know_is_not_a_setting(self):
        with InATemporaryHome():
            config.save_settings({'place': 'Thornhill', 'rm -rf': 'no', 'nonsense': '1'})
            with open(config.settings_path(), encoding='utf-8') as fh:
                body = fh.read()
            self.assertIn('place=Thornhill', body)
            self.assertNotIn('nonsense', body)
            self.assertNotIn('rm -rf', body)

    def test_the_key_is_never_written_into_the_settings_file(self):
        """The two files are separate because the GNOME half rewrites shulgo.conf from scratch when
        the key changes, which would destroy anything else kept in there."""
        with InATemporaryHome():
            config.save_api_key(A_KEY)
            values = config.load_settings()
            values['place'] = 'Thornhill'
            config.save_settings(values)

            self.assertNotEqual(config.key_path(), config.settings_path())
            with open(config.settings_path(), encoding='utf-8') as fh:
                self.assertNotIn(A_KEY, fh.read())

            # And the reverse: rewriting the key must not disturb the settings.
            config.save_api_key('sg_live_' + 'ff00ff00' * 5)
            self.assertEqual(config.load_settings()['place'], 'Thornhill')

    def test_a_broken_number_falls_back_to_the_default(self):
        with InATemporaryHome():
            self.assertEqual(config.as_int({'window-minutes': 'soon'}, 'window-minutes'), 120)
            self.assertEqual(config.as_int({}, 'list-length'), 5)

    def test_half_a_place_is_no_place(self):
        with InATemporaryHome():
            self.assertIsNone(config.saved_place({'lat': '43.8', 'lng': '', 'place': 'x'}))
            self.assertIsNone(config.saved_place({'lat': 'north', 'lng': '-79.4'}))


if __name__ == '__main__':
    unittest.main()
