"""The window has to fit on the screens this edition actually runs on.

Written because it did not. shulgo-xfce 1.0.0 opened its settings window with Close and Save below
the bottom edge on a 1280x800 Pentium III, and the machines this edition targets are mostly smaller
than that one — 1024x768, sometimes 800x600.

The useful test here is not "does 1280x800 give 620". It is the property: on every screen in the
table below, by either reading of the work area, the whole window fits with the buttons on it. That
is what was broken, so that is what is asserted — and on its first run it found the allowance 20 px
short on 800x600, which no amount of reading the file had.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shulgo_xfce import layout  # noqa: E402

# The screens the JewBuntu editions are installed on, as reported by the sessions running them.
SCREENS = (
    (1280, 800),   # the Arch 32 VM the bug was found on
    (1024, 768),   # the common old laptop
    (800, 600),    # the floor of what these machines do
    (1366, 768),   # a slightly later laptop
)

# What sits on screen around the window. Deliberately a little larger than anything measured: the
# Arch 32 edition's panels are 24 and 48, and Jewbuntu Classic's are 24 and 40. Bigger figures here
# mean less room in the assertions, so these make the tests stricter than the desktops they stand
# for. They are not meant to be corrected downwards to match a measurement — that would quietly
# weaken every assertion below.
TOP_BAR = 28
DOCK = 60
TITLEBAR = 28


class FitsOnTheScreen(unittest.TestCase):
    def test_fits_when_the_desktop_reports_its_panels(self):
        """The ordinary case: the work area already excludes the bar and the dock."""
        for width, height in SCREENS:
            usable = height - TOP_BAR - DOCK
            _, asked = layout.window_size(width, usable, width, height)

            self.assertLessEqual(
                asked + TITLEBAR, usable,
                'a %dx%d screen with %d px usable got a %d px window'
                % (width, height, usable, asked))

    def test_fits_when_the_dock_publishes_no_struts(self):
        """The case that bit us: GTK reports the whole screen, panels and all.

        An overlay dock that sets no _NET_WORKAREA strut is invisible to get_workarea(), so the
        window has to survive being told the screen is bigger than the room it really has.
        """
        for width, height in SCREENS:
            _, asked = layout.window_size(width, height, width, height)
            really_usable = height - TOP_BAR - DOCK

            self.assertLessEqual(
                asked + TITLEBAR, really_usable,
                'a %dx%d screen reported whole got a %d px window, but only %d px is free'
                % (width, height, asked, really_usable))

    def test_width_fits_too(self):
        for width, height in SCREENS:
            asked, _ = layout.window_size(width, height, width, height)

            self.assertLessEqual(asked, width)

    def test_wider_than_tall(self):
        """The whole point of the change: two columns, not one tall one."""
        for width, height in SCREENS:
            usable = height - TOP_BAR - DOCK
            asked_width, asked_height = layout.window_size(width, usable, width, height)

            self.assertGreater(asked_width, asked_height)


class ReadingTheWorkArea(unittest.TestCase):
    def test_a_reported_work_area_is_trusted_and_gives_a_taller_window(self):
        """Told about the panels, it need not also guess about them.

        Without this the allowance is paid twice and an 800x600 machine gets a needlessly short
        window — correct, but worse than it has to be.
        """
        _, trusted = layout.window_size(1280, 712, 1280, 800)
        _, blind = layout.window_size(1280, 800, 1280, 800)

        self.assertGreaterEqual(trusted, blind)
        self.assertEqual(trusted, layout.HEIGHT)

    def test_a_work_area_equal_to_the_screen_leaves_room_for_a_dock(self):
        _, asked = layout.window_size(800, 600, 800, 600)

        self.assertEqual(asked, 600 - layout.ALLOWANCE - layout.PANELS)


class TheCeiling(unittest.TestCase):
    """The ceiling is the room on the screen, not the height the window opens at.

    Those are different numbers and conflating them makes the window unresizable — which is a
    worse fault than the one being fixed, so it gets its own test.
    """

    def test_the_ceiling_is_the_room_not_the_opening_height(self):
        work, whole = 712, 800
        _, opens_at = layout.window_size(1280, work, 1280, whole)
        ceiling = layout.height_ceiling(work, whole)

        self.assertEqual(opens_at, layout.HEIGHT)
        self.assertGreater(ceiling, opens_at)

    def test_the_ceiling_still_fits_the_screen(self):
        for width, height in SCREENS:
            for reported in (height - TOP_BAR - DOCK, height):
                ceiling = layout.height_ceiling(reported, height)
                really_usable = height - TOP_BAR - DOCK

                # No max() against MIN_HEIGHT here on purpose. A guard that never fires is how a
                # test quietly stops testing anything, and every screen in the table clears the
                # floor comfortably, so the assertion is made plainly.
                self.assertLessEqual(
                    ceiling + TITLEBAR, really_usable,
                    'a %dx%d screen reporting %d got a ceiling of %d'
                    % (width, height, reported, ceiling))

    def test_an_unmeasurable_screen_gets_no_ceiling_at_all(self):
        """Better a window that can be dragged anywhere than one that cannot be resized."""
        for nothing in (0, None, -1):
            self.assertIsNone(layout.height_ceiling(nothing, nothing))


class WhenTheScreenIsUnknown(unittest.TestCase):
    def test_nothing_known_gives_the_plain_defaults(self):
        """Under Xvfb, or from a checkout with no monitor to ask, assume an ordinary screen."""
        for nothing in (0, None, -1):
            self.assertEqual(layout.window_size(nothing, nothing, nothing, nothing),
                             (layout.WIDTH, layout.HEIGHT))

    def test_a_work_area_with_no_screen_to_compare_is_treated_as_blind(self):
        _, asked = layout.window_size(1024, 768, None, None)

        self.assertEqual(asked, min(layout.HEIGHT, 768 - layout.ALLOWANCE - layout.PANELS))

    def test_an_absurd_work_area_gives_the_floor_not_a_sliver(self):
        self.assertEqual(layout.window_size(100, 100, 100, 100),
                         (layout.MIN_WIDTH, layout.MIN_HEIGHT))


class TheArithmetic(unittest.TestCase):
    def test_a_big_screen_gets_the_wanted_size_not_the_whole_screen(self):
        self.assertEqual(layout.window_size(2560, 1400, 2560, 1440),
                         (layout.WIDTH, layout.HEIGHT))

    def test_a_small_screen_is_capped_to_what_is_free(self):
        _, asked = layout.window_size(1024, 600, 1024, 768)

        self.assertEqual(asked, 600 - layout.ALLOWANCE)


if __name__ == '__main__':
    unittest.main()
