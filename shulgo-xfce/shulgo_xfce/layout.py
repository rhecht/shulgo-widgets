"""How big to open a window on a screen this small.

Here rather than in settings_window.py for the reason pick.py gives: the machine this is written on
has no GTK at all, so anything decided inside a module that imports gi cannot be tested before it
reaches somebody's desktop. The settings window arrived on a 1280x800 Pentium III with its Close and
Save buttons below the bottom of the screen, and the arithmetic that put them there was never run
here. Now it is, and the first run of tests/test_layout.py found this file 20 px wrong on 800x600.

The numbers matter less than the structure around them. set_default_size is a *request*: a window
whose child needs 850 px will be 850 px tall however small a height is asked for, which is exactly
how the buttons ended up off-screen. What makes a cap work at all is the body sitting in a
Gtk.ScrolledWindow — that can be shorter than its contents — with the buttons outside it. Given
that, this only has to choose something comfortable and never taller than the screen.
"""

# Wider and shorter, which is what was asked for: two columns at this width instead of one long
# one. 800 rather than the middle of 760-820 because the columns are what want the room; 560 high
# because two columns of this content come to about 480, and the scroller covers being wrong.
WIDTH = 800
HEIGHT = 560

# Floors, for a work area reported so small that the arithmetic below would give something absurd.
# A window this size is uncomfortable; it is still better than a window of 40 px.
MIN_WIDTH = 560
MIN_HEIGHT = 320

# A titlebar, plus a little air. Always kept clear: the window manager's own decoration is not part
# of the work area and will push the bottom of the window down past it.
ALLOWANCE = 40

# What else to keep clear when nothing can be assumed about the panels. GTK reports the work area,
# which on a well-behaved desktop already excludes them — but only when the window manager
# publishes _NET_WORKAREA, and an overlay dock that sets no strut is invisible to get_workarea().
# The Arch 32 edition has a ~28 px top bar and a ~60 px dock, and this covers both.
PANELS = 84

ALLOWANCE_WIDTH = 48


def height_ceiling(work_area_height, screen_height=None):
    """The tallest this window may be on this screen and still show its buttons.

    None when the screen cannot be measured, meaning: set no ceiling at all. A window that cannot
    be resized is a worse thing to ship than one that can be dragged off the bottom of a screen
    nobody was able to measure.

    The two figures are compared rather than one being trusted. A work area shorter than the screen
    is a desktop that has told us about its panels, and then only the titlebar needs keeping clear.
    A work area that *is* the whole screen is either a desktop with no panels or one whose dock
    publishes no struts, and there is no way to tell which — so room is left for a dock that may
    not be there. Erring that way costs a shorter window, which the scroller makes harmless;
    erring the other way hides the buttons, which is the bug this exists to prevent.
    """
    if not _known(work_area_height):
        return None

    allowance = ALLOWANCE

    if not _known(screen_height) or work_area_height >= screen_height:
        allowance += PANELS

    room = work_area_height - allowance

    return room if room >= MIN_HEIGHT else MIN_HEIGHT


def window_size(work_area_width, work_area_height, screen_width=None, screen_height=None):
    """(width, height) to open at: the comfortable size, or the screen's, whichever is smaller.

    Any figure may be 0 or None when nothing could be found out about the screen — a checkout under
    Xvfb, say — and then the plain defaults are used, because an unknown screen is far more likely
    to be an ordinary one than a tiny one.
    """
    ceiling = height_ceiling(work_area_height, screen_height)
    height = HEIGHT if ceiling is None else min(HEIGHT, ceiling)

    return _fit(work_area_width, WIDTH, MIN_WIDTH, ALLOWANCE_WIDTH), height


def _known(value):
    return value is not None and value > 0


def _fit(available, wanted, floor, allowance):
    if not _known(available):
        return wanted

    room = available - allowance

    if room < floor:
        return floor

    return wanted if wanted < room else room
