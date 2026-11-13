"""Where the key and the settings live.

Two files, and the split matters.

The API key goes in ~/.config/jewbuntu/shulgo.conf, mode 0600 — deliberately the same file, in the
same format, that the GNOME extension and the ShulGo GTK app use. A machine running both the GNOME
widget and this one shares one key, pasted once. The key is kept out of GSettings for the reason the
GNOME half documents: dconf is readable by everything in the session, and an API key should not be.

This widget's own settings go in a SECOND file, shulgo-xfce.conf. That is not tidiness: the GNOME
half's saveApiKey() rewrites shulgo.conf from scratch every time the key is changed, keeping only the
key line. Anything else written in there would be silently destroyed the next time somebody edited
their key in GNOME's preferences. Separate files, no such trap.

No GSettings at all on this side, which also means no schema to install and no dconf daemon to run —
worth having on a machine with 256 MB of RAM.

Plain stdlib. The format is the same "# comment" and "name=value" shape the GNOME half writes, read
with a regex rather than configparser so a file written by either side is read the same way.
"""

import os
import re
import stat
import tempfile

_LINE = re.compile(r'^\s*([a-z][a-z0-9-]*)\s*=\s*(.*?)\s*$')
# The key is matched with \S+ exactly as the GNOME half does, so a line either side writes is read
# identically by the other.
_KEY_LINE = re.compile(r'^\s*api-key\s*=\s*(\S+)\s*$')

DEFAULTS = {
    'api-base-url': 'https://shulgo.com/api/v1',
    'place': '',               # what to call where you are, e.g. "Thornhill"
    'lat': '',
    'lng': '',
    'window-minutes': '120',   # how far ahead to look for minyanim
    'travel-mode': 'drive',
    'tefillah': 'next',
    'list-length': '5',        # how many minyanim in the menu
    'refresh-seconds': '900',  # 15 minutes. Gentle on purpose; countdowns tick locally.
    'show-zmanim': 'yes',
    'show-events': 'yes',
    'show-shiurim': 'yes',
}


def _config_dir():
    base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')

    return os.path.join(base, 'jewbuntu')


def key_path():
    """~/.config/jewbuntu/shulgo.conf — shared with the GNOME half."""
    return os.path.join(_config_dir(), 'shulgo.conf')


def settings_path():
    """~/.config/jewbuntu/shulgo-xfce.conf — this widget's own."""
    return os.path.join(_config_dir(), 'shulgo-xfce.conf')


def cache_path():
    base = os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache')

    return os.path.join(base, 'jewbuntu', 'shulgo-xfce.json')


def _read_lines(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return fh.read().split('\n')
    except OSError:
        return []


def _write_private(path, body):
    """Write a file only its owner can read, without ever leaving it briefly readable.

    mkstemp makes the file 0600 to begin with, so there is no window in which the key sits on disk
    world-readable — which is what writing the file and then chmod-ing it would do.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.shulgo-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(body)
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_api_key():
    """The ShulGo API key. SHULGO_API_KEY in the environment wins, so a test run needn't touch the
    saved one."""
    from_env = os.environ.get('SHULGO_API_KEY')
    if from_env:
        return from_env.strip()

    for line in _read_lines(key_path()):
        m = _KEY_LINE.match(line)
        if m:
            return m.group(1)

    return ''


def save_api_key(key):
    """Writes the key owner-only, in the GNOME half's own format. An empty key removes the file."""
    clean = str(key or '').strip()
    path = key_path()
    if not clean:
        try:
            os.unlink(path)
        except OSError:
            pass

        return True

    _write_private(path, '\n'.join([
        '# ShulGo API key for the JewBuntu widget.',
        '# Ask your ShulGo administrator for a key, or request one at',
        '# https://shulgo.com/developers/request',
        'api-key=%s' % clean,
        '',
    ]))

    return True


def load_settings():
    """This widget's settings, with the defaults filled in for anything not written down."""
    values = dict(DEFAULTS)
    for line in _read_lines(settings_path()):
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        m = _LINE.match(line)
        if m and m.group(1) in DEFAULTS:
            values[m.group(1)] = m.group(2)

    return values


def save_settings(values):
    """Writes the settings back, keeping only names we know, so a typo can't become a setting."""
    body = ['# ShulGo for Xfce. The API key is NOT here — it is in shulgo.conf, owner-only.', '']
    for name in DEFAULTS:
        if name in values and str(values[name]) != '':
            body.append('%s=%s' % (name, values[name]))
    body.append('')
    # Not secret, but there is no reason for anything else on the machine to read where you daven.
    _write_private(settings_path(), '\n'.join(body))

    return True


def saved_place(values=None):
    """Where to look, as (lat, lng, label), or None when nothing has been chosen yet."""
    values = load_settings() if values is None else values
    try:
        lat = float(values.get('lat') or '')
        lng = float(values.get('lng') or '')
    except (TypeError, ValueError):
        return None

    return lat, lng, (values.get('place') or 'your location')


def as_int(values, name):
    try:
        return int(str(values.get(name, DEFAULTS[name])).strip())
    except (TypeError, ValueError):
        return int(DEFAULTS[name])
