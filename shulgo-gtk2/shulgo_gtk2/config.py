# -*- coding: utf-8 -*-
u"""Where the key and the settings live.

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

# with_statement: `with` is a __future__ import on 2.5, not syntax. division: 5/60 is 0 without it.
from __future__ import division, with_statement

import os
import re
import stat
import codecs
import tempfile
import time

_LINE = re.compile(ur'^\s*([a-z][a-z0-9-]*)\s*=\s*(.*?)\s*$')
# The key is matched with \S+ exactly as the GNOME half does, so a line either side writes is read
# identically by the other.
_KEY_LINE = re.compile(ur'^\s*api-key\s*=\s*(\S+)\s*$')

DEFAULTS = {
    u'api-base-url': u'https://shulgo.com/api/v1',
    u'place': u'',               # what to call where you are, e.g. "Thornhill"
    u'lat': u'',
    u'lng': u'',
    u'window-minutes': u'120',   # how far ahead to look for minyanim
    u'travel-mode': u'drive',
    u'tefillah': u'next',
    u'list-length': u'5',        # how many minyanim in the menu
    u'refresh-seconds': u'900',  # 15 minutes. Gentle on purpose; countdowns tick locally.
    u'show-zmanim': u'yes',
    u'show-events': u'yes',
    u'show-shiurim': u'yes',
    u'panel-line': u'yes',       # the line beside the clock, via xfce4-genmon-plugin
}


from .fmt import _text


def _config_dir():
    base = os.environ.get(u'XDG_CONFIG_HOME') or os.path.join(os.path.expanduser(u'~'), u'.config')

    return os.path.join(base, u'jewbuntu')


def key_path():
    u"""~/.config/jewbuntu/shulgo.conf — shared with the GNOME half."""
    return os.path.join(_config_dir(), u'shulgo.conf')


def settings_path():
    u"""~/.config/jewbuntu/shulgo-xfce.conf — this widget's own."""
    return os.path.join(_config_dir(), u'shulgo-gtk2.conf')


# How far past its last known deadline a linking has to be before we give up on it without asking.
# The server's own longest wait is three days; a month past that is a file nothing will ever resolve.
ABANDONED_AFTER = 30 * 86400


def pending_path():
    u"""~/.config/jewbuntu/shulgo-xfce-linking.conf — a linking that has not finished yet.

    Written because the window promises "you can close this; it keeps working for three days", and
    for a while that was a lie: closing the window threw the linking away, and since the key is only
    minted on the first poll AFTER approval, it wasted both the person's approval and an
    administrator's. On a machine somebody switches off overnight, surviving a reboot is the normal
    case rather than the exotic one.

    Owner-only like the key file: a device code is a bearer token until it is used.
    """
    return os.path.join(_config_dir(), u'shulgo-gtk2-linking.conf')


def save_pending(device_code, user_code, expires_at, interval):
    u"""Remember a linking in progress, so the tray can carry on after the window is gone."""
    _write_private(pending_path(), u'\n'.join([
        u'# A ShulGo linking waiting to be approved. Deleted when it finishes or runs out.',
        u'device-code=%s' % device_code,
        u'user-code=%s' % user_code,
        u'expires-at=%d' % int(expires_at),
        u'interval=%d' % int(interval),
        u'',
    ]))


def load_pending():
    u"""The linking in progress, or None when there is none or it has run out."""
    found = {}
    for line in _read_lines(pending_path()):
        m = _LINE.match(line)
        if m and not line.lstrip().startswith(u'#'):
            found[m.group(1)] = m.group(2)

    if not found.get(u'device-code'):
        return None
    try:
        expires_at = int(found.get(u'expires-at') or 0)
        interval = int(found.get(u'interval') or 5)
    except (TypeError, ValueError):
        return None

    # NOT deleted merely because our own clock says so. Expiry is the server's to declare: the
    # deadline moves when somebody approves their own device — twenty minutes becomes three days —
    # and a file written before that move looks expired while the server still has it alive. Acting
    # on the local figure threw away a real pair of approvals. One poll settles it honestly, and the
    # answer to expired_token is what deletes this.
    #
    # The backstop is for a file that can never be polled at all — a machine off the network for a
    # month — rather than for one that is merely past its last known deadline.
    if expires_at + ABANDONED_AFTER <= time.time():
        clear_pending()

        return None

    return {
        u'device_code': found[u'device-code'],
        u'user_code': found.get(u'user-code') or u'',
        u'expires_at': expires_at,
        u'interval': max(1, interval),
    }


def clear_pending():
    try:
        os.unlink(pending_path())
    except EnvironmentError:
        pass


def cache_path():
    base = os.environ.get(u'XDG_CACHE_HOME') or os.path.join(os.path.expanduser(u'~'), u'.cache')

    return os.path.join(base, u'jewbuntu', u'shulgo-gtk2.json')


def bar_path():
    u"""Where the panel helper looks for the top-bar line.

    The helper that xfce4-genmon-plugin runs is a one-line shell script that cats this file, so on a
    Pentium III nothing heavier than `cat` runs every fifteen seconds. The widget is what keeps the
    file current.
    """
    return os.path.join(os.path.dirname(cache_path()), u'shulgo-bar.txt')


def save_bar(text):
    u"""Replace the top-bar line, atomically, 0600.

    Atomically because genmon may read it at any moment and half a line of markup is a parse error
    in the panel; 0600 because the tooltip names where somebody davens and when they will be there,
    which is nobody else's business on a shared machine.
    """
    try:
        _write_private(bar_path(), text)
    except EnvironmentError:
        pass


def clear_bar():
    u"""Take the line away. Called on quit, so the panel does not keep showing times forever."""
    try:
        os.unlink(bar_path())
    except EnvironmentError:
        pass


def _read_lines(path):
    try:
        with codecs.open(path, u'r', u'utf-8') as fh:
            return fh.read().split(u'\n')
    except EnvironmentError:
        # EnvironmentError, not OSError. On Python 2 those are two separate classes and a failed
        # read raises IOError, so `except OSError` here let a missing file escape as a traceback on
        # the very first run, which is precisely the run where there is no file yet.
        return []


def _write_private(path, body):
    u"""Write a file only its owner can read, without ever leaving it briefly readable.

    mkstemp makes the file 0600 to begin with, so there is no window in which the key sits on disk
    world-readable — which is what writing the file and then chmod-ing it would do.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=u'.shulgo-')
    try:
        with os.fdopen(fd, u'wb') as fh:
            fh.write(body.encode(u'utf-8'))
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.rename(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except EnvironmentError:
            pass
        raise


def load_api_key():
    u"""The ShulGo API key. SHULGO_API_KEY in the environment wins, so a test run needn't touch the
    saved one."""
    from_env = os.environ.get(u'SHULGO_API_KEY')
    if from_env:
        return from_env.strip()

    for line in _read_lines(key_path()):
        m = _KEY_LINE.match(line)
        if m:
            return m.group(1)

    return u''


def save_api_key(key):
    u"""Writes the key owner-only, in the GNOME half's own format. An empty key removes the file."""
    clean = _text(key).strip()
    path = key_path()
    if not clean:
        try:
            os.unlink(path)
        except EnvironmentError:
            pass

        return True

    _write_private(path, u'\n'.join([
        u'# ShulGo API key for the JewBuntu widget.',
        u'# Ask your ShulGo administrator for a key.',
        u'api-key=%s' % clean,
        u'',
    ]))

    return True


def load_settings():
    u"""This widget's settings, with the defaults filled in for anything not written down."""
    values = dict(DEFAULTS)
    for line in _read_lines(settings_path()):
        if not line.strip() or line.lstrip().startswith(u'#'):
            continue
        m = _LINE.match(line)
        if m and m.group(1) in DEFAULTS:
            values[m.group(1)] = m.group(2)

    return values


def save_settings(values):
    u"""Writes the settings back, keeping only names we know, so a typo can't become a setting."""
    body = [u'# ShulGo for Xfce. The API key is NOT here — it is in shulgo.conf, owner-only.', u'']
    for name in DEFAULTS:
        if name in values and _text(values[name]) != u'':
            body.append(u'%s=%s' % (name, values[name]))
    body.append(u'')
    # Not secret, but there is no reason for anything else on the machine to read where you daven.
    _write_private(settings_path(), u'\n'.join(body))

    return True


def saved_place(values=None):
    u"""Where to look, as (lat, lng, label), or None when nothing has been chosen yet."""
    values = load_settings() if values is None else values
    try:
        lat = float(values.get(u'lat') or u'')
        lng = float(values.get(u'lng') or u'')
    except (TypeError, ValueError):
        return None

    return lat, lng, (values.get(u'place') or u'your location')


def as_int(values, name):
    try:
        return int(_text(values.get(name, DEFAULTS[name])).strip())
    except (TypeError, ValueError):
        return int(DEFAULTS[name])
