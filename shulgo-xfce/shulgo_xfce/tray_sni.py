"""ShulGo's own StatusNotifierItem, for desktops that need a complete one.

Imported only when sni.plan says so, which on Xfce is never — a Pentium III should not pay to load
a module written for a Wayland compositor.

Everything decided here is in sni.py, which imports nothing and is tested. What is left in this
file is plumbing: own a bus name, export the item, hand libdbusmenu the Gtk.Menu that already
exists, and tell the watcher we are here. The menu is emphatically not rebuilt. tray.py keeps one
Gtk.Menu whose rows are relabelled in place, for the sake of a 1 GHz machine, and
dbusmenu_gtk_parse_menu_structure serves that same menu over the bus — which is exactly what
libayatana does internally, so the menu a panel sees is the one that already worked.

None of this has run anywhere. This machine has no D-Bus session, no GTK and no tray, so every
call below is written from the specification and the libraries' documentation rather than from a
session that worked. That is why tray.py wraps the whole of it in a try and falls back to the
library path: a mistake in here should cost Cutefish nothing it is not already missing, and must
cost Xfce nothing at all.
"""

import os

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gio  # noqa: E402

from . import sni  # noqa: E402

# The GIR name of dbusmenu_gtk_parse_menu_structure cannot be worked out from here with any
# confidence — it depends on how the typelib strips the prefix. Rather than guess once and fail
# silently, every plausible spelling is tried and the error names all of them, so one run in the
# Cutefish container settles it for good.
_PARSE_NAMES = ('parse_menu_structure', 'gtk_parse_menu_structure', 'menu_structure_parse')


def libraries():
    """(Dbusmenu, DbusmenuGtk3) or (None, None) when they are not installed.

    Both come from Debian's libdbusmenu source as gir1.2-dbusmenu-glib-0.4 and
    gir1.2-dbusmenu-gtk3-0.4, one version, the gtk3 one depending on the other. Without them this
    file cannot serve a menu, and an item that claims ItemIsMenu with no menu behind it is worse
    than the fault it was meant to fix: the panel would open nothing, having been told to expect
    something.
    """
    try:
        gi.require_version('Dbusmenu', '0.4')
        gi.require_version('DbusmenuGtk3', '0.4')
        from gi.repository import Dbusmenu, DbusmenuGtk3

        return Dbusmenu, DbusmenuGtk3
    except (ValueError, ImportError, AttributeError):
        return None, None


def available():
    """Whether an own item could be served at all. sni.plan's have_dbusmenu."""
    return libraries()[0] is not None


def watcher_present(connection=None):
    """Whether anything is listening for tray items on the session bus.

    Asked rather than assumed, because the answer decides whether to export an item at all. A
    StatusNotifierItem nobody has registered with is invisible: the icon would simply not appear,
    which is the hardest kind of failure to recognise from the outside.
    """
    try:
        connection = connection or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        answer = connection.call_sync(
            'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
            'NameHasOwner', GLib.Variant('(s)', (sni.WATCHER_NAME,)),
            GLib.VariantType('(b)'), Gio.DBusCallFlags.NONE, 2000, None)

        return bool(answer.unpack()[0])
    except Exception:
        return False


class OwnItem:
    """The item, its menu and its registration, for as long as the tray is running."""

    def __init__(self, menu, item_id, title, icon_name, icon_theme_path=''):
        self.menu = menu
        self.item_id = item_id
        self.title = title
        self.tooltip_body = ''
        self._registration = 0
        self._name_id = 0
        self._watch_id = 0

        dbusmenu, dbusmenu_gtk = libraries()
        if dbusmenu is None:
            raise RuntimeError('libdbusmenu-gtk3 is not installed')

        self.values = sni.properties(item_id, title, icon_name, icon_theme_path)
        self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.bus_name = sni.bus_name(os.getpid())

        # The menu first. If this fails there is no point owning a name, and failing before
        # anything is published leaves the bus exactly as it was for the fallback to use.
        self.server = dbusmenu.Server.new(sni.MENU_PATH)
        self.server.set_root(_parse(dbusmenu_gtk, menu))

        node = Gio.DBusNodeInfo.new_for_xml(sni.INTROSPECTION)
        self._registration = self.connection.register_object(
            sni.ITEM_PATH, node.interfaces[0], self._on_method, self._on_get, None)

        # Only now take the name, so that a host reacting the instant it appears finds a complete
        # object rather than a half-exported one.
        self._name_id = Gio.bus_own_name_on_connection(
            self.connection, self.bus_name, Gio.BusNameOwnerFlags.NONE,
            self._on_name_acquired, None)

        # And keep registering. A tray that restarts — or one that starts after us, which is the
        # ordinary case for a session that autostarts ShulGo — forgets every item it knew, and an
        # item that does not come back is an icon that never returns.
        self._watch_id = Gio.bus_watch_name_on_connection(
            self.connection, sni.WATCHER_NAME, Gio.BusNameWatcherFlags.NONE,
            lambda *_: self._register(), None)

    # ---- what the panel asks ---------------------------------------------------------------

    def _on_get(self, _connection, _sender, _path, _interface, name):
        pair = self.values.get(name)
        if pair is None:
            return None

        signature, value = pair

        return GLib.Variant(signature, value)

    def _on_method(self, _connection, _sender, _path, _interface, method, _args, invocation):
        """Activate and ContextMenu answer and do nothing, deliberately.

        With ItemIsMenu true a host following the specification opens the menu itself and calls
        neither. A host that calls one anyway gets a reply instead of UnknownMethod, which is the
        whole fault being fixed here and not worth reproducing from the other side. Popping the
        menu ourselves is what we cannot do: on Wayland a client cannot place a popup at the
        pointer, or anywhere near the tray, with any reliability.
        """
        invocation.return_value(None)

    # ---- keeping it current ----------------------------------------------------------------

    def set_tooltip_body(self, text):
        """The next minyan, on hover. Called where the library path calls set_label."""
        text = text or ''
        if text == self.tooltip_body:
            return

        self.tooltip_body = text
        self.values['ToolTip'] = ('(sa(iiay)ss)', sni.tooltip(self.title, text))
        self._emit('NewToolTip')

    def _emit(self, signal):
        """No parameters, because the only signal sent is NewToolTip, which carries none.

        NewIcon and NewStatus are declared in the interface and never sent: this program's icon and
        status do not change once it has started, and a host is free to listen for signals that
        never come. There is deliberately no set_icon_name here to go with NewIcon — nothing in the
        program would call it.
        """
        try:
            self.connection.emit_signal(
                None, sni.ITEM_PATH, sni.ITEM_INTERFACE, signal, None)
        except Exception:
            # A missed signal costs a stale tooltip until the panel asks again. It is not worth
            # taking the tray down for, and there is nothing useful to do about it here.
            pass

    def _on_name_acquired(self, *_):
        self._register()

    def _register(self):
        """Tell the watcher. Harmless to repeat, and repeated on purpose when a tray appears."""
        try:
            self.connection.call_sync(
                sni.WATCHER_NAME, sni.WATCHER_PATH, sni.WATCHER_INTERFACE,
                'RegisterStatusNotifierItem', GLib.Variant('(s)', (self.bus_name,)),
                None, Gio.DBusCallFlags.NONE, 2000, None)
        except Exception:
            # Nothing listening yet. The name watcher above will call this again when something
            # starts, so there is no retry loop here and nothing to log on a machine with no log.
            pass

    def close(self):
        for unwatch, handle in ((Gio.bus_unwatch_name, self._watch_id),
                                (Gio.bus_unown_name, self._name_id)):
            if handle:
                try:
                    unwatch(handle)
                except Exception:
                    pass

        if self._registration:
            try:
                self.connection.unregister_object(self._registration)
            except Exception:
                pass


def _parse(dbusmenu_gtk, menu):
    """The Gtk.Menu, as a Dbusmenu tree that tracks it.

    One menu, two audiences. Rebuilding it as Dbusmenu.Menuitem objects by hand would mean every
    relabelling in tray.py had to happen twice and stay in step, and the countdown relabels a row
    every sixty seconds.
    """
    for name in _PARSE_NAMES:
        parse = getattr(dbusmenu_gtk, name, None)
        if parse is not None:
            return parse(menu)

    raise RuntimeError('libdbusmenu-gtk3 has none of %s' % ', '.join(_PARSE_NAMES))
