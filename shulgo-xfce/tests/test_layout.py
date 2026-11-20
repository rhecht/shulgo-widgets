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

# xfwm4's decoration measured 29 px on the VM (a 560 px window came back as a 589 px frame), so 28
# was a pixel short of the thing it stands for — harmless, because ALLOWANCE is 40, but a constant
# that claims to be generous should be. 32 for the same reason as the panels above.
TITLEBAR = 32


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


class WhereItOpens(unittest.TestCase):
    """Centred in the work area — and the point of testing it is that centring has a trap in it.

    Centring on the *screen* is the one-line version and it puts an 800x600 window's bottom edge
    under the dock, which is the original bug wearing a tidier hat. These assertions are about the
    frame, decoration included, staying inside the work area on every screen in the table.
    """

    def test_the_whole_frame_stays_inside_the_work_area(self):
        for width, height in SCREENS:
            for work_y in (0, TOP_BAR):
                work_h = height - work_y - DOCK
                asked_w, asked_h = layout.window_size(width, work_h, width, height)
                x, y = layout.window_position(asked_w, asked_h, 0, work_y, width, work_h)

                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, work_y)
                self.assertLessEqual(
                    x + asked_w, width,
                    'a %dx%d screen put a %d px window at x=%d' % (width, height, asked_w, x))
                self.assertLessEqual(
                    y + asked_h + TITLEBAR, work_y + work_h,
                    'a %dx%d screen put a %d px window at y=%d, and the work area ends at %d'
                    % (width, height, asked_h, y, work_y + work_h))

    def test_a_window_with_no_room_to_spare_sits_at_the_top_not_below_it(self):
        """800x600 with both panels: the window is as tall as the room allows.

        There is nothing to centre, and the arithmetic has to notice that rather than halving a
        negative number and moving the window up off the top of the work area.
        """
        _, asked = layout.window_size(800, 526, 800, 600)
        _, y = layout.window_position(800, asked, 0, 25, 800, 526)

        self.assertEqual(y, 25)

    def test_it_is_actually_centred_when_there_is_room(self):
        """Not just inside the work area — a function that returned the origin would pass that."""
        x, y = layout.window_position(800, 560, 0, 25, 1280, 726)

        self.assertGreater(x, 200)
        self.assertGreater(y, 25)

    def test_the_origin_of_the_work_area_is_not_assumed_to_be_zero(self):
        """A panel above the work area moves its top edge down, and the window has to follow."""
        _, high = layout.window_position(800, 400, 0, 0, 1280, 700)
        _, low = layout.window_position(800, 400, 0, 25, 1280, 700)

        self.assertEqual(low - high, 25)

    def test_a_work_area_smaller_than_the_window_does_not_go_negative(self):
        """No screen in the table is this small, and the guard against it still has to be tested.

        Below about 580 px wide the MIN_WIDTH floor is wider than the whole work area, so there is
        nothing left over to halve; halving it anyway would put the window off the left edge as
        well as the right. This case is here because a mutation that deleted the guard passed
        every other test in this file — which is the same way a dead guard hides, from the other
        side.
        """
        self.assertEqual(
            layout.window_position(layout.MIN_WIDTH, layout.MIN_HEIGHT, 0, 0, 500, 300),
            (0, 0))

    def test_an_unknown_work_area_means_let_the_window_manager_decide(self):
        for nothing in (0, None, -1):
            self.assertIsNone(
                layout.window_position(800, 560, nothing, nothing, nothing, nothing))


if __name__ == '__main__':
    unittest.main()
