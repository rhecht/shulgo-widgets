# -*- coding: utf-8 -*-
u"""Entry point, and --check.

A module rather than __main__.py because `python -m package` does not run a package until 2.7:
on 2.5, -m finds only top-level modules. bin/shulgo-gtk2 imports this and calls main().

--check exists for the same reason it exists in the Xfce build: everything that decides whether this
works is outside the program. Which PyGTK is installed, whether there is a notification area to put
an icon in, whether the ISO's curl is where it should be and speaks HTTPS at all. On this hardware
the usual failure is not a crash, it is a widget that starts, draws nothing, and is never mentioned
again because nobody has a way to look.
"""

from __future__ import with_statement

import os
import sys

VERSION = u'1.0.0'


def check():
    lines = [u'ShulGo for GNOME 2 (GTK2) %s' % VERSION,
             u'python %s' % sys.version.split()[0]]

    if sys.version_info[:2] < (2, 5):
        lines.append(u'python: TOO OLD — 2.5 is the minimum')

    try:
        import gtk
        lines.append(u'pygtk %s, gtk %s'
                     % ('.'.join([str(n) for n in gtk.pygtk_version]),
                        '.'.join([str(n) for n in gtk.gtk_version])))
    except ImportError, e:
        lines.append(u'pygtk: MISSING (%s) — install python-gtk2' % e)
        print('\n'.join(lines).encode('utf-8'))

        return 1

    try:
        import simplejson
        lines.append(u'simplejson %s' % getattr(simplejson, '__version__', 'present'))
    except ImportError:
        lines.append(u'simplejson: MISSING — install python-simplejson. '
                     u'The json module does not exist before Python 2.6.')

    display = os.environ.get('DISPLAY')
    lines.append(u'display: %s' % (display or u'NONE — there is no desktop to put an icon on'))

    from . import curl
    found = curl.binary()
    if found is None:
        lines.append(u'curl: MISSING — expected %s. Without it there is no HTTPS at all: this '
                     u'system’s own OpenSSL only speaks TLS 1.0, which ShulGo refuses.'
                     % curl.BUNDLED)
    else:
        lines.append(u'curl: %s%s' % (found, u'' if found == curl.BUNDLED
                                      else u'  (not the bundled one; TLS 1.2 is not guaranteed)'))

    from . import config
    # Not wrapped in a try: if asking where the icon is can itself fail, that is something --check
    # must say loudly rather than quietly report as a missing icon.
    from .tray import icon_path
    found_icon = icon_path()
    lines.append(u'icon: %s' % (found_icon or u'NOT FOUND — the tray icon would be invisible'))
    lines.append(u'api key: %s' % (u'saved' if config.load_api_key() else u'not set yet'))
    place = config.saved_place()
    lines.append(u'place: %s' % (place[2] if place else u'not chosen yet'))
    lines.append(u'settings: %s' % config.settings_path())

    values = config.load_settings()
    if values.get(u'panel-line') == u'yes':
        lines.append(u'panel line: on — %s' % config.bar_path())
    else:
        lines.append(u'panel line: off')

    print('\n'.join(lines).encode('utf-8'))

    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    if '--help' in argv or '-h' in argv:
        print(__doc__.strip().encode('utf-8'))

        return 0
    if '--version' in argv:
        print(VERSION)

        return 0
    if '--check' in argv:
        return check()

    from .tray import main as run

    return run()
