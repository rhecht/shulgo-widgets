"""ShulGo in the Xfce tray.

    python3 -m shulgo_xfce           run it
    python3 -m shulgo_xfce --check   say what this machine has, and exit

--check exists because the things that decide whether this works — which tray library is installed,
whether there is a display, whether the icon will resolve, and whether a key and a place have been
saved — are exactly the things that are awkward to find out by watching a tray icon fail to appear.

The icon line was added after the first real run on a Pentium III, where the tray registered
correctly and drew nothing because the icon was not in any theme. A check meant to catch silent
failures that missed the silent failure in front of it was not much of a check.
"""

import os
import sys

VERSION = '1.0.0'


def check():
    lines = ['ShulGo for Xfce %s' % VERSION, 'python %s' % sys.version.split()[0]]

    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk
        lines.append('GTK %d.%d.%d' % (Gtk.get_major_version(), Gtk.get_minor_version(),
                                       Gtk.get_micro_version()))
    except (ImportError, ValueError) as e:
        lines.append('GTK 3: MISSING (%s)' % e)
        print('\n'.join(lines))

        return 1

    from .tray import _load_indicator
    _module, flavour = _load_indicator()
    lines.append('tray: %s' % (flavour or 'no AppIndicator — falling back to Gtk.StatusIcon'))

    display = os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')
    lines.append('display: %s' % (display or 'NONE — there is no desktop to put an icon on'))

    # The fourth silent failure, and the one this command originally missed: the tray registers with
    # the panel perfectly and shows nothing, because an icon NAME resolves only once the file is in
    # an icon theme.
    from . import icon as icons
    directory = icons.bundled_dir()
    try:
        from gi.repository import Gtk as _Gtk
        theme_has_icon = _Gtk.IconTheme.get_default().has_icon(icons.ICON_NAME)
    except Exception:
        theme_has_icon = False
    lines.append(icons.describe(icons.plan(theme_has_icon, directory), directory))

    from . import config
    key = config.load_api_key()
    lines.append('api key: %s' % ('saved' if key else 'not set yet'))
    place = config.saved_place()
    lines.append('place: %s' % (place[2] if place else 'not chosen yet'))
    lines.append('settings: %s' % config.settings_path())
    lines.append('cache: %s' % config.cache_path())

    print('\n'.join(lines))

    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv

    if '--help' in argv or '-h' in argv:
        print(__doc__.strip())

        return 0
    if '--version' in argv:
        print(VERSION)

        return 0
    if '--check' in argv:
        return check()

    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        print('ShulGo: there is no display to put a tray icon on. Run this inside your desktop '
              'session.', file=sys.stderr)

        return 1

    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk

    from .tray import ShulGoTray

    # GLib's default SIGINT handling would leave the icon behind; this way Ctrl-C quits cleanly.
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    tray = ShulGoTray()
    try:
        Gtk.main()
    finally:
        tray.cache.save()

    return 0


if __name__ == '__main__':
    sys.exit(main())
