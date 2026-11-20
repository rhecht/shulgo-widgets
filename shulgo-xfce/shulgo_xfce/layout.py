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
# The measured figures, from the session that runs the VM: the Arch 32 edition's top bar is 24 px
# (xfce4-panel, p=6) and its dock is 48 px (xfce4-panel with Docklike, p=10), so 72 px. Jewbuntu
# Classic on 7.10 comes to 64 — GNOME's 24 px top panel and a 40 px bottom dock.
#
# 84 rather than 72, because these two are the editions somebody has measured and neither is the
# only desktop this will ever run on; a panel a little taller than Jewbuntu's costs nothing here
# and a panel taller than the allowance costs the buttons. The earlier guess of 28 + 60 happened
# to land on the same safe side of the real numbers, which is luck, not method.
PANELS = 84

ALLOWANCE_WIDTH = 48

# What a window manager's border costs on each side. xfwm4's is 1 px; this is deliberately larger,
# because it is only used to decide where to put the window, and a window a few pixels left of
# centre looks centred while a window a few pixels off the right edge does not.
FRAME = 8


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


def window_position(width, height, work_x, work_y, work_width, work_height):
    """Where to put a window of this size: the middle of the work area, never past its edges.

    None when the work area is unknown, meaning: do not move it, let the window manager choose.

    The *work* area, not the screen, and the difference is not pedantry. Centring on the screen is
    the obvious one-liner, and on the screens this runs on it is wrong: a 515 px frame centred on
    800 px of screen starts at y=42 and ends at 557, which on Jewbuntu is 6 px underneath the dock
    — the very fault this module exists to prevent, reintroduced for the sake of looking tidy.

    The window's decoration cannot be measured before the window is on screen, so ALLOWANCE stands
    in for it. That over-estimates xfwm4's by about ten pixels, which puts the window slightly
    above centre rather than slightly below it. Of those two, above is the one nobody notices.
    """
    if not _known(work_width) or not _known(work_height):
        return None

    return (_centre(work_x, work_width, width + 2 * FRAME),
            _centre(work_y, work_height, height + ALLOWANCE))


def _centre(origin, available, taken):
    origin = origin if origin else 0
    room = available - taken

    if room <= 0:
        return origin

    return origin + (room // 2)
