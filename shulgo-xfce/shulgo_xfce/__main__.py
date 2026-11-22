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
import shutil
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

    from .tray import _load_indicator, choose_tray
    _module, flavour = _load_indicator()
    lines.append('tray library: %s' % (flavour or 'no AppIndicator installed'))

    # Which kind of item will be owned, and why. The fifth silent failure, and the one that cost
    # Cutefish: the icon appeared, the menu was complete, and a left-click did nothing because the
    # item libayatana exports has no ItemIsMenu property. Nothing on screen said which kind of item
    # was in use, so there was nothing to look at. Now there is.
    from . import config as _config, sni
    kind, why = choose_tray(flavour is not None, _config.load_settings())
    lines.append('tray item: %s — %s' % (
        {sni.OWN: 'ShulGo’s own (ItemIsMenu, menu over DBusMenu)',
         sni.LIBRARY: 'the appindicator library’s',
         sni.STATUS_ICON: 'Gtk.StatusIcon (deprecated, X11 only)'}.get(kind, kind), why))

    # Asked here and not when choosing, where it would be a race: at login this program is often
    # up before the compositor's watcher. It is still worth printing, because an item nothing has
    # registered with is an icon that silently never appears.
    if kind == sni.OWN:
        from . import tray_sni
        lines.append('tray listening: %s' % (
            'yes' if tray_sni.watcher_present()
            else 'not yet — the item will register itself when one starts'))

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

    # The same silent failure as the icon, wearing a different hat: the setting can be on and the
    # file written every minute, and the panel still shows nothing, because the helper is not on
    # PATH or Generic Monitor was never added to the panel. Neither of those is visible from inside
    # the widget, so say what IS visible and let the person match it against their panel.
    settings = config.load_settings()
    if settings.get('panel-line') == 'yes':
        helper = shutil.which('shulgo-bar')
        written = os.path.exists(config.bar_path())
        lines.append('top bar: on — %s' % (
            'writing %s' % config.bar_path() if written
            else 'nothing written yet (it appears on the first refresh)'))
        lines.append('  helper: %s' % (
            helper or 'shulgo-bar NOT on PATH — the panel has nothing to run'))
        lines.append('  panel: add Generic Monitor to the panel, command  shulgo-bar , every 15 s. '
                     'This cannot be checked from here.')
    else:
        lines.append('top bar: off (Settings → “A line on the top bar”)')

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
    from gi.repository import GLib, Gtk

    # Name the process before any window exists. GTK takes a toplevel's WM_CLASS from the program
    # name, and without this it is "python3" or "__main__" — so a dock has nothing to match against
    # shulgo-xfce.desktop and shows a generic cog instead of the shul. Must happen before the first
    # window is realised, which is why it is here rather than in the settings window.
    GLib.set_prgname('shulgo-xfce')
    GLib.set_application_name('ShulGo')

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
