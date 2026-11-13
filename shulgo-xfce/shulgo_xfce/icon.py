"""Finding the tray icon — including when nobody has installed it yet.

This exists because of a real failure, on the first machine that ever ran this widget. The tray
registered itself correctly with the panel's StatusNotifierWatcher, the process sat there happily,
and **no icon appeared**, because `shulgo` is an icon *name* and names only resolve once the file is
in an icon theme. Run from a checkout, as anyone trying it out will, there is nothing to resolve and
the panel draws nothing. No error, no warning, no icon: the worst shape a bug can take.

So: if the icon theme does not know the name and we are running from a checkout that carries the
file, tell the panel where to look. The StatusNotifierItem protocol has an IconThemePath property for
exactly this, and Gtk.StatusIcon can simply be given the file.

Kept apart from tray.py so the decision can be tested on a machine with no GTK at all, which is where
this was written and is the reason the bug reached a Pentium III before it reached a test.
"""

import os

ICON_NAME = 'shulgo'

# What the tray should do about its icon.
IN_THEME = 'theme'      # installed properly; the name resolves and there is nothing to do
BUNDLED = 'bundled'     # not installed, but we are beside the file: point the panel at it
MISSING = 'missing'     # not installed and not found: the icon will not appear, and we should say so


def bundled_dir(module_file=None):
    """The checkout's packaging directory, when there is one with the icon in it, else None.

    Resolved from this file's own location rather than the working directory, because a tray widget
    is usually started from a desktop file or an autostart entry whose working directory is anybody's
    guess.
    """
    here = os.path.dirname(os.path.abspath(module_file or __file__))
    candidate = os.path.join(os.path.dirname(here), 'packaging')

    return candidate if os.path.isfile(os.path.join(candidate, ICON_NAME + '.svg')) else None


def bundled_file(directory=None):
    """The icon file inside that directory, or None."""
    directory = bundled_dir() if directory is None else directory

    return os.path.join(directory, ICON_NAME + '.svg') if directory else None


def plan(theme_has_icon, directory):
    """What to do, given whether the icon theme knows the name and whether we have the file.

    A plain function of two facts, so it can be tested without a display, an icon theme or GTK.

    The theme wins when it has the icon: a package install puts a properly sized, themed icon in
    hicolor, and overriding that with a path into some checkout would be worse than useless.
    """
    if theme_has_icon:
        return IN_THEME
    if directory:
        return BUNDLED

    return MISSING


def describe(state, directory=None):
    """One line for `--check`, which is the whole point: this failure is otherwise silent."""
    if state == IN_THEME:
        return 'icon: found in the icon theme'
    if state == BUNDLED:
        return ('icon: NOT in the icon theme — using the copy in %s. That works, but only for this '
                'checkout; installing the package puts it in hicolor properly.' % directory)

    return ('icon: NOT FOUND — the tray will register but show nothing at all. Install the package, '
            'or copy packaging/%s.svg into ~/.local/share/icons/hicolor/scalable/apps/ and run '
            'gtk-update-icon-cache.' % ICON_NAME)
