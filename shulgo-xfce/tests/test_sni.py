"""The tray item ShulGo exports itself, and the choice of whether to export one.

Written because shulgo-xfce registered a tray icon on Cutefish, showed it, served a complete menu
over DBusMenu — and did nothing when clicked, because the item libayatana exports has no
`ItemIsMenu` property and no `Activate` method. There is no display, no D-Bus session and no tray on
the machine this is written on, so the parts that can be checked here are the decision and the
things the item says about itself. Those are checked thoroughly, because nothing else will be.

The assertion that matters most is in TheDesktopsThatMustNotBreak. Arch 32 on a Pentium III and
Jewbuntu Classic both work today, and a fix for a third desktop that disturbed either of them would
be a bad trade at any price.
"""

import os
import sys
import unittest
from xml.etree import ElementTree

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shulgo_xfce import sni  # noqa: E402

# Everything that can vary about a desktop, as plan() sees it.
PRESENT = (True, False)


class TheDesktopsThatMustNotBreak(unittest.TestCase):
    def test_x11_with_the_library_always_gets_the_library(self):
        """Arch 32 and Jewbuntu Classic are X11 and have libayatana. Nothing else may happen.

        Every other combination is swept because the point is not that the common case works: it
        is that no arrangement of the other facts can route an X11 machine with a working
        appindicator library onto the new path.
        """
        for have_dbusmenu in PRESENT:
            for forced in (None, '', 'nonsense'):
                kind, why = sni.plan(False, True, have_dbusmenu, forced)

                self.assertEqual(
                    kind, sni.LIBRARY,
                    'X11 with the library went to %s (dbusmenu=%s, forced=%r): %s'
                    % (kind, have_dbusmenu, forced, why))

    def test_a_healthy_machine_is_never_told_something_is_missing(self):
        """The reason must not blame a package nobody wanted.

        An X11 machine with the library is working perfectly and libdbusmenu-gtk3 is no part of
        what it needs. An earlier version reported "libdbusmenu-gtk3 is not installed" there, which
        reads as a fault on a machine that has none; the order of those checks is now decided by
        whether the own item was actually wanted.
        """
        _, why = sni.plan(False, True, False)

        self.assertIn('X11', why)
        self.assertNotIn('libdbusmenu', why)
        self.assertNotIn('not installed', why)

    def test_x11_without_the_library_still_falls_back_to_status_icon(self):
        """The oldest path in the program, and the one a 25-year-old laptop may still need."""
        for have_dbusmenu in PRESENT:
            kind, _ = sni.plan(False, False, have_dbusmenu)

            self.assertEqual(kind, sni.STATUS_ICON)


class TheDesktopThatWasBroken(unittest.TestCase):
    def test_cutefish_gets_our_own_item(self):
        """Wayland with libdbusmenu present: the one case that changes."""
        kind, why = sni.plan(True, True, True)

        self.assertEqual(kind, sni.OWN)
        self.assertIn('Wayland', why)

    def test_a_tray_that_has_not_started_yet_does_not_change_the_answer(self):
        """Deliberate, and it was wrong once: whether a tray is listening is not a fact here.

        ShulGo runs from an autostart entry, so at login it routinely comes up before the
        compositor has registered its StatusNotifierWatcher. An earlier version asked the bus who
        was listening and fell back to the library when nobody was, which meant the fix failed for
        the whole session in precisely the case it exists for. The item is exported regardless and
        registers itself when a tray appears, so there is nothing here to get wrong twice.
        """
        self.assertEqual(sni.plan(True, True, True)[0], sni.OWN)

    def test_wayland_with_no_libdbusmenu_is_left_as_it_was(self):
        """An item with ItemIsMenu and no menu behind it would be worse than the present fault.

        It would claim to have a menu and then have none, so a host would open nothing and have
        been told to expect something. Falling back is the honest move.
        """
        kind, why = sni.plan(True, True, False)

        self.assertEqual(kind, sni.LIBRARY)
        self.assertIn('libdbusmenu', why)

    def test_wayland_with_no_library_at_all_still_gets_our_own_item(self):
        """Our item does not need libayatana. Where it can work, missing the library is no bar."""
        kind, _ = sni.plan(True, False, True)

        self.assertEqual(kind, sni.OWN)


class WhenItIsSetByHand(unittest.TestCase):
    def test_the_library_can_be_asked_for_on_wayland(self):
        kind, why = sni.plan(True, True, True, forced=sni.LIBRARY)

        self.assertEqual(kind, sni.LIBRARY)
        self.assertIn('settings', why)

    def test_our_own_item_can_be_asked_for_on_x11(self):
        """So that the desktop this was written for is not the only place it can be tried."""
        kind, why = sni.plan(False, True, True, forced=sni.OWN)

        self.assertEqual(kind, sni.OWN)
        self.assertIn('settings', why)

    def test_asking_for_what_cannot_work_says_so_and_carries_on(self):
        """A setting that cannot be honoured must not leave the machine with no tray icon."""
        kind, why = sni.plan(False, True, False, forced=sni.OWN)

        self.assertEqual(kind, sni.LIBRARY)
        self.assertIn('chosen in settings', why)
        self.assertIn('libdbusmenu', why)

    def test_asking_for_a_library_that_is_not_there_falls_through(self):
        kind, why = sni.plan(False, False, True, forced=sni.LIBRARY)

        self.assertEqual(kind, sni.STATUS_ICON)
        self.assertTrue(why)


class EveryAnswerIsUsable(unittest.TestCase):
    def test_every_combination_gives_a_known_kind_and_a_reason(self):
        """--check prints the reason, so an empty one is a bug in its own right."""
        for wayland in PRESENT:
            for library in PRESENT:
                for dbusmenu in PRESENT:
                    for forced in (None, sni.OWN, sni.LIBRARY):
                        kind, why = sni.plan(wayland, library, dbusmenu, forced)

                        self.assertIn(kind, (sni.OWN, sni.LIBRARY, sni.STATUS_ICON))
                        self.assertTrue(why and why.strip(), 'no reason for %s' % kind)
                        self.assertFalse(why.endswith(' '), 'ragged reason: %r' % why)

    def test_the_library_is_never_chosen_when_there_is_no_library(self):
        """tray.py reaches straight for indicator.Indicator on this answer.

        If plan ever returned LIBRARY without one, that line is an AttributeError in __init__ and
        the widget never appears at all — a silent autostart failure, which is the hardest kind to
        work out from the outside and the kind this program has already had once.
        """
        for wayland in PRESENT:
            for dbusmenu in PRESENT:
                for forced in (None, sni.OWN, sni.LIBRARY):
                    kind, _ = sni.plan(wayland, False, dbusmenu, forced)

                    self.assertNotEqual(kind, sni.LIBRARY)

    def test_our_own_item_is_never_chosen_when_it_cannot_work(self):
        """The one combination that would leave a tray with an item and no menu behind it."""
        for wayland in PRESENT:
            for library in PRESENT:
                for forced in (None, sni.OWN, sni.LIBRARY):
                    kind, _ = sni.plan(wayland, library, False, forced)

                    self.assertNotEqual(kind, sni.OWN)


class WhichKindOfSession(unittest.TestCase):
    def test_either_variable_on_its_own_is_enough(self):
        for environ in ({'WAYLAND_DISPLAY': 'wayland-0'},
                        {'XDG_SESSION_TYPE': 'wayland'},
                        {'WAYLAND_DISPLAY': 'wayland-0', 'XDG_SESSION_TYPE': 'wayland'}):
            self.assertTrue(sni.wayland(environ), environ)

    def test_an_x11_session_is_not_wayland(self):
        for environ in ({}, {'DISPLAY': ':0'}, {'XDG_SESSION_TYPE': 'x11', 'DISPLAY': ':0'},
                        {'XDG_SESSION_TYPE': 'tty'}):
            self.assertFalse(sni.wayland(environ), environ)

    def test_empty_and_blank_values_are_not_a_wayland_session(self):
        """An exported-but-empty variable is common in autostart environments and means nothing."""
        for environ in ({'WAYLAND_DISPLAY': ''}, {'WAYLAND_DISPLAY': '  '},
                        {'XDG_SESSION_TYPE': ''}):
            self.assertFalse(sni.wayland(environ), environ)

    def test_the_case_of_the_session_type_does_not_matter(self):
        self.assertTrue(sni.wayland({'XDG_SESSION_TYPE': 'Wayland'}))

    def test_gdk_backend_does_not_change_the_answer(self):
        """Under Cutefish, GDK_BACKEND=x11 means XWayland — the tray is still Cutefish's."""
        self.assertTrue(sni.wayland({'XDG_SESSION_TYPE': 'wayland', 'GDK_BACKEND': 'x11'}))


class WhatTheItemSaysAboutItself(unittest.TestCase):
    def test_it_says_it_is_a_menu(self):
        """The whole fix, in one property. Everything else here was already working."""
        self.assertEqual(sni.properties('shulgo-xfce', 'ShulGo', 'shulgo')['ItemIsMenu'],
                         ('b', True))

    def test_it_points_at_the_menu(self):
        signature, path = sni.properties('shulgo-xfce', 'ShulGo', 'shulgo')['Menu']

        self.assertEqual(signature, 'o')
        self.assertEqual(path, sni.MENU_PATH)
        self.assertTrue(path.startswith('/'), 'an object path has to start with a slash')

    def test_the_icon_theme_path_is_a_string_even_when_there_is_none(self):
        """None would be sent as a variant of the wrong type and the host would drop the item."""
        self.assertEqual(
            sni.properties('shulgo-xfce', 'ShulGo', 'shulgo', icon_theme_path=None)
            ['IconThemePath'],
            ('s', ''))

    def test_every_value_matches_the_signature_it_is_sent_with(self):
        """These are built into variants by hand, and a mismatch is a crash on a desktop, here."""
        kinds = {'s': str, 'i': int, 'b': bool, 'o': str}

        for name, (signature, value) in sni.properties(
                'shulgo-xfce', 'ShulGo', 'shulgo', '/tmp/x', 'in 20 min').items():
            if signature in kinds:
                self.assertIsInstance(value, kinds[signature], '%s is not a %s' % (name, signature))
            else:
                self.assertIsInstance(value, tuple, '%s should be a structure' % name)

    def test_the_tooltip_carries_no_image_bytes(self):
        """Deliberate: the tray has the icon already, and the machine has 256 MB of memory."""
        icon, pixmaps, title, body = sni.tooltip('ShulGo', 'Mincha in 20 min')

        self.assertEqual(icon, '')
        self.assertEqual(pixmaps, [])
        self.assertEqual(title, 'ShulGo')
        self.assertEqual(body, 'Mincha in 20 min')

    def test_the_tooltip_body_is_a_string_when_empty(self):
        self.assertEqual(sni.tooltip('ShulGo', None)[3], '')

    def test_the_bus_name_looks_like_every_other_tray_item(self):
        self.assertEqual(sni.bus_name(1234), 'org.kde.StatusNotifierItem-1234-1')
        self.assertEqual(sni.bus_name(1234, 7), 'org.kde.StatusNotifierItem-1234-7')


class TheInterfaceItDeclares(unittest.TestCase):
    """The XML and properties() have to agree, and nothing makes them agree by itself."""

    def setUp(self):
        self.node = ElementTree.fromstring(sni.INTROSPECTION)
        self.interface = self.node.find('interface')

    def test_the_introspection_is_valid_xml_for_the_right_interface(self):
        self.assertEqual(self.interface.get('name'), sni.ITEM_INTERFACE)

    def test_it_declares_exactly_the_properties_it_will_answer(self):
        """Either direction is a fault: an undeclared property is invisible to a host that reads
        the interface, and a declared one that is never answered is an error waiting to be hit."""
        declared = dict((p.get('name'), p.get('type')) for p in self.interface.findall('property'))
        answered = dict((name, signature) for name, (signature, _) in sni.properties(
            'shulgo-xfce', 'ShulGo', 'shulgo').items())

        self.assertEqual(declared, answered)

    def test_it_declares_the_two_methods_whose_absence_caused_all_this(self):
        """Cutefish called Activate on an item that had none and got UnknownMethod."""
        methods = [m.get('name') for m in self.interface.findall('method')]

        self.assertIn('Activate', methods)
        self.assertIn('ContextMenu', methods)


if __name__ == '__main__':
    unittest.main()


class LubuntuLXQt(unittest.TestCase):
    """LXQt is X11, but its panel sends left-clicks as Activate, which the library's item ignores."""

    def test_lxqt_with_libdbusmenu_gets_our_own_item(self):
        kind, why = sni.plan(False, True, True, lxqt=True)

        self.assertEqual(kind, sni.OWN)
        self.assertIn('LXQt', why)

    def test_lxqt_without_libdbusmenu_keeps_the_library(self):
        kind, _ = sni.plan(False, True, False, lxqt=True)

        self.assertEqual(kind, sni.LIBRARY)

    def test_a_setting_still_wins_on_lxqt(self):
        self.assertEqual(sni.plan(False, True, True, forced=sni.LIBRARY, lxqt=True)[0], sni.LIBRARY)

    def test_not_lxqt_x11_is_unchanged(self):
        """Xfce (Arch 32), Classic and Lubuntu 18.04's LXDE are not LXQt: the library, as before."""
        for have_dbusmenu in PRESENT:
            self.assertEqual(sni.plan(False, True, have_dbusmenu, lxqt=False)[0], sni.LIBRARY)

    def test_lxqt_is_read_from_xdg_current_desktop(self):
        self.assertTrue(sni.lxqt({'XDG_CURRENT_DESKTOP': 'LXQt'}))
        self.assertTrue(sni.lxqt({'XDG_CURRENT_DESKTOP': 'Lubuntu:LXQt'}))
        self.assertTrue(sni.lxqt({'XDG_CURRENT_DESKTOP': 'lxqt'}))
        self.assertFalse(sni.lxqt({'XDG_CURRENT_DESKTOP': 'XFCE'}))
        self.assertFalse(sni.lxqt({'XDG_CURRENT_DESKTOP': 'LXDE'}))
        self.assertFalse(sni.lxqt({}))
