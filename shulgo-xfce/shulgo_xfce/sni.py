"""What a StatusNotifierItem has to say about itself, and which kind of tray item to use.

Here rather than in tray.py for the reason layout.py and pick.py give: this machine has no GTK, no
D-Bus session and no tray, so anything decided inside a module that imports gi cannot be run until
it is on somebody's desktop. The decision below is the whole of the Cutefish fix, so it is the last
thing that should go untested.

The fault being fixed: libayatana-appindicator exports a StatusNotifierItem with no `ItemIsMenu`
property and no `Activate` method at all. That is not a bug in libayatana so much as its age —
Ayatana's design was menu-only, its own panels always showed the menu, and `ItemIsMenu` was added to
the specification later by KDE to say "I am menu-only, do not call Activate". KDE's own tray copes
by showing the menu when `Activate` fails. Cutefish reads `ItemIsMenu`, finds nothing, calls
`Activate`, gets UnknownMethod, and does nothing at all — which is what "the shulgo widget doesn't
work" looks like from the outside.

So on a desktop like that, ShulGo exports its own item instead, with `ItemIsMenu` true and `Menu`
pointing at the same menu. The menu itself is not rebuilt: libdbusmenu-gtk3 can serve the existing
Gtk.Menu directly, so there is one menu in the program and it goes on being the one the panel shows.
"""

# Where the item lives on our own bus name, and where the panel is asked to find the menu.
ITEM_PATH = '/StatusNotifierItem'
MENU_PATH = '/StatusNotifierItem/Menu'

ITEM_INTERFACE = 'org.kde.StatusNotifierItem'
WATCHER_NAME = 'org.kde.StatusNotifierWatcher'
WATCHER_PATH = '/StatusNotifierWatcher'
WATCHER_INTERFACE = 'org.kde.StatusNotifierWatcher'

# The three kinds of tray item this program can own.
OWN = 'own'                  # ShulGo's own StatusNotifierItem, the one with ItemIsMenu on it
LIBRARY = 'library'          # libayatana-appindicator, or the older Ubuntu one
STATUS_ICON = 'status-icon'  # Gtk.StatusIcon: deprecated, X11 only, and still the last resort

# Only the parts of org.kde.StatusNotifierItem that are answered. A host that asks for anything
# else gets an error naming the property, which is a clearer thing to find in a log than silence.
#
# Activate and ContextMenu are declared and do nothing. With ItemIsMenu true a well-behaved host
# shows the menu itself and calls neither — but answering them cleanly costs two lines, and the
# whole reason this module exists is a host that called a method which was not there.
INTROSPECTION = """<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
    <signal name="NewStatus">
      <arg name="status" type="s"/>
    </signal>
  </interface>
</node>"""


def plan(wayland, have_library, have_dbusmenu, forced=None, lxqt=False):
    """Which kind of tray item to own, and in one phrase why. Returns (kind, reason).

    The reason is not decoration: `--check` prints it, and the question somebody asks when a tray
    icon misbehaves is always "which of these is it even using".

    The policy, in order:

      1. A setting chosen by hand wins, where it can be honoured at all.
      2. Otherwise, on Wayland, ShulGo's own item — when libdbusmenu-gtk3 is there to serve
         the menu.
      3. Otherwise the appindicator library, as before.
      4. Otherwise Gtk.StatusIcon.

    Rule 2 is deliberately narrow. The two desktops this widget is known to work on — Xfce on Arch
    32 and Jewbuntu Classic — are both X11, so they fall straight through to rule 3 and get the
    code path they have now, to the line. That is the point: the fix cannot reach them to break
    them.

    Wayland is a stand-in for the real condition, which is "this host requires ItemIsMenu", and
    there is no way to ask a host that. It is a fair stand-in: on Wayland there is no XEmbed tray
    for the library to fall back to, so a StatusNotifierItem is the only kind of tray item that can
    work there at all, and ours is the one that is complete.

    Whether a tray is listening on the bus right now is deliberately NOT one of the facts. It was,
    briefly, and it was a bug: ShulGo starts from an autostart entry, so at login it routinely
    comes up before the compositor has registered its watcher, and the answer would have been "no
    tray, use the library" for the whole of that session — the fix failing exactly when it is most
    needed. tray_sni.OwnItem watches for the watcher and registers whenever one appears, so an
    item exported into an empty session costs nothing and is there the moment a tray arrives.
    """
    own_possible = bool(have_dbusmenu)

    if forced == LIBRARY and have_library:
        return LIBRARY, 'chosen in settings'

    if forced == OWN and own_possible:
        return OWN, 'chosen in settings'

    asked = 'own item chosen in settings, but ' if forced == OWN else ''

    if wayland and own_possible:
        return OWN, 'a Wayland session, where no other kind of item is read'

    # LXQt (Lubuntu) is X11, but its panel sends a left-click to the item as Activate, which the
    # library's item does not implement: left-click did nothing there, and at login the library's
    # XEmbed fallback added a second icon (seen on Lubuntu 26.10, 2026-11-26). Our item answers
    # Activate by opening the menu, and has no XEmbed fallback. Xfce and Classic are not LXQt.
    if lxqt and own_possible:
        return OWN, 'LXQt, whose panel sends a left-click to the item as Activate'

    if have_library:
        return LIBRARY, asked + _why_not_own(wayland or lxqt, forced, have_dbusmenu)

    return STATUS_ICON, asked + 'no appindicator library is installed'


def _why_not_own(wayland, forced, have_dbusmenu):
    """Why the own item was not used — which depends on whether it was wanted.

    The order of these is the whole content of the function. On a healthy Arch 32 machine nothing
    is missing and nothing is wrong, so the reason is the policy: X11, where the library works.
    Say "libdbusmenu-gtk3 is not installed" there and it reads as a fault on a machine that has
    none. But once somebody has actually asked for the own item, the session type is beside the
    point and the thing that blocked them is the only useful answer.
    """
    if not (wayland or forced == OWN):
        return 'an X11 session, where the library works'

    # Only reachable with the item wanted, since plan() would otherwise have returned OWN.
    return 'libdbusmenu-gtk3 is not installed, so there would be no menu to show'


def wayland(environ):
    """Whether this is a Wayland session, from the environment alone.

    A plain function of a dict so it can be tested here, and because the two variables disagree
    more often than one would like: a session can set XDG_SESSION_TYPE and no WAYLAND_DISPLAY, or
    the reverse under a nested compositor, so either one on its own is taken as a yes.

    GDK_BACKEND is deliberately not consulted. Under Cutefish a GTK program told to use x11 runs
    on XWayland, but the tray reading its item is still Cutefish's, and still wants ItemIsMenu. The
    question here is which desktop is listening, not which protocol this process happens to draw
    with.
    """
    if (environ.get('WAYLAND_DISPLAY') or '').strip():
        return True

    return (environ.get('XDG_SESSION_TYPE') or '').strip().lower() == 'wayland'


def lxqt(environ):
    """Whether the desktop is LXQt (Lubuntu 22.04 and newer), from XDG_CURRENT_DESKTOP alone.

    The variable is a colon-separated list ("LXQt", or "Lubuntu:LXQt" on some versions); any entry
    equal to LXQt, ignoring case, counts. LXDE (Lubuntu 18.04) is not LXQt and keeps the library.
    """
    return any(part.strip().lower() == 'lxqt'
               for part in (environ.get('XDG_CURRENT_DESKTOP') or '').split(':'))


def bus_name(pid, serial=1):
    """The name to own on the session bus.

    The shape is the one every host already recognises, down to the hyphens: KDE's own items are
    named this way and some hosts have been known to match on the prefix rather than ask the
    watcher. There is no reason to be the one item that looks different.
    """
    return 'org.kde.StatusNotifierItem-%d-%d' % (pid, serial)


def properties(item_id, title, icon_name, icon_theme_path='', tooltip_body='', status='Active'):
    """Everything the item will answer, as {name: (signature, value)}.

    Signatures travel with the values so that the plumbing can build the variants without a second
    table to keep in step, and so this can be checked on a machine with no D-Bus at all.

    `ItemIsMenu` true is the entire fix. `Menu` is what makes it true in practice: with both, a
    host that follows the specification opens the menu itself on a left-click and never needs to
    call a method on us.
    """
    return {
        'Category': ('s', 'ApplicationStatus'),
        'Id': ('s', item_id),
        'Title': ('s', title),
        'Status': ('s', status),
        'WindowId': ('i', 0),
        'IconName': ('s', icon_name),
        # Empty unless ShulGo is running from a checkout, where the icon is not in any theme and
        # the panel has to be told the folder to look in. The same problem, and the same answer,
        # as icon.py describes for the library path.
        'IconThemePath': ('s', icon_theme_path or ''),
        'OverlayIconName': ('s', ''),
        'AttentionIconName': ('s', ''),
        'AttentionMovieName': ('s', ''),
        'ToolTip': ('(sa(iiay)ss)', tooltip(title, tooltip_body)),
        'ItemIsMenu': ('b', True),
        'Menu': ('o', MENU_PATH),
    }


def tooltip(title, body=''):
    """The ToolTip structure: icon name, pixmaps, title, body.

    No icon and no pixmaps — the tray already has our icon, and sending it twice would mean
    carrying image bytes over the bus on a machine chosen for having very little of anything.

    The body is where the next minyan goes. The library path cannot do this at all (libayatana
    ignores ToolTip), so on Wayland the hover text is better than on X11, which is an odd place to
    end up but not a reason to leave it empty.
    """
    return ('', [], title, body or '')
