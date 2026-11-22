# -*- coding: utf-8 -*-
u"""The ShulGo tray icon for GNOME 2.20, on PyGTK 2.12.

Not a port of the GTK3 tray so much as the same behaviour rebuilt on what 2007 had. The decisions
all live in modules this file only calls — pick.py chooses the minyan, fmt.py writes the words,
bar.py the panel line, link.py the linking — so almost nothing here needs a running desktop to be
tested, which is just as well, because a desktop from 2007 is not a thing a test can conjure.

What PyGTK 2.12 does not have, and what is used instead:

  gtk.show_uri            2.14  -> a browser is launched by hand, see _open()
  set_tooltip_text        2.16  -> gtk.StatusIcon.set_tooltip, which takes plain text, not markup
  gobject.timeout_add_seconds 2.14 -> gobject.timeout_add, in milliseconds
  AppIndicator            later -> gtk.StatusIcon, which GNOME 2.20's notification area shows

And one rule that is not about missing features: GTK is not thread-safe, and PyGTK 2.12 will corrupt
the display rather than complain if a worker touches a widget. Every answer from the network comes
back through gobject.idle_add and is drawn on the main loop. That is the single most dangerous
difference from the GTK3 version, because getting it wrong looks like flaky hardware.
"""

from __future__ import division, with_statement

import os
import subprocess
import threading

import gobject
import gtk

from . import bar, config, link
from .api import Cache, ShulGoApi
from .fmt import (
    countdown, escape_markup, minutes_until, minyan_destination, minyan_note, minyan_subtitle,
    minyan_time, maps_uri, offline_notice, tefillah_label, updated_ago, zman_time, zmanim_list,
)
from .pick import headline as pick_headline, still_ahead

# Bubbles are a nicety, not a dependency. python-notify is on a stock 7.10 desktop, but not in the
# build container, not on a stripped install, and its init() fails with no notification daemon. Any
# of those leaves the widget exactly as it was before bubbles existed, rather than not starting.
try:
    import pynotify
    if not pynotify.init(u'ShulGo'):
        pynotify = None
except Exception:
    pynotify = None

# Milliseconds. The countdown is redone locally every minute; the network is asked far less often.
TICK_MS = 60 * 1000


def _open(uri):
    u"""Open a link without gtk.show_uri, which does not exist yet.

    Tried in order, because which of these is present says a lot about how old the machine is, and
    the widget should not care. Nothing is ever passed through a shell: the URI comes from the API
    and a shul with a quote in its name must not be able to run anything.
    """
    for launcher in ('xdg-open', 'gnome-open', 'firefox'):
        try:
            subprocess.Popen([launcher, uri],
                             stdout=open(os.devnull, 'wb'), stderr=subprocess.STDOUT)

            return True
        except EnvironmentError:
            continue

    return False


def bubble(status_icon, summary, body):
    u"""A libnotify bubble pointing at the tray icon. False when there is no way to show one.

    Never raises: this runs on the main loop straight after a link is saved, and an exception here
    would be the same kind of fault as the one that lost an approved key — a traceback in the middle
    of an answer, with whatever comes after it never done.
    """
    if pynotify is None:
        return False
    try:
        path = icon_path()
        note = pynotify.Notification(summary, body, path and ('file://' + path) or 'gtk-home')
        if status_icon is not None and hasattr(note, 'attach_to_status_icon'):
            note.attach_to_status_icon(status_icon)

        return bool(note.show())
    except Exception:
        return False


def icon_path():
    u"""A path, never a theme name.

    A module-level function rather than a method, so --check can ask the same question without an
    instance. It was a method, and --check called it with a None self, which on Python 2 is a
    TypeError rather than a trick that works - caught by a bare `except` and reported as "icon: NOT
    FOUND". A check that fails silently and blames the thing it is checking is worse than no check.

    By path because looking an icon up by name only works once it has been installed into an icon
    theme, so a name is exactly what shows nothing at all when the widget runs from a checkout -
    which is how an invisible tray icon shipped once already.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for candidate in (
        u'/usr/share/icons/hicolor/24x24/apps/shulgo.png',
        u'/usr/share/icons/hicolor/22x22/apps/shulgo.png',
        os.path.join(os.path.dirname(here), u'packaging', u'shulgo-24.png'),
        os.path.join(os.path.dirname(here), u'packaging', u'shulgo-22.png'),
    ):
        if os.path.exists(candidate):
            return candidate

    return None


class Tray(object):
    def __init__(self):
        self.settings = config.load_settings()
        self.cache = Cache(config.cache_path())
        self.api = ShulGoApi(
            base_url=self.settings.get(u'api-base-url'),
            api_key=config.load_api_key(),
            cache=self.cache,
        )
        self.state = {
            u'minyanim': [], u'zmanim': {}, u'updated': 0,
            u'why': None, u'whyMessage': None, u'staleSince': 0,
        }
        self._work = None
        self._pending = None
        self._pending_timer = None
        # The open "Link this computer" window, if there is one, so the answer reaches it too.
        self._link_window = None

        self.icon = gtk.StatusIcon()
        path = icon_path()
        if path:
            self.icon.set_from_file(path)
        else:
            # Never leave it blank: an icon that fails to resolve is simply invisible, and an
            # invisible tray icon is indistinguishable from a widget that did not start. That exact
            # fault shipped once in the GTK3 build and nobody could see it to report it.
            self.icon.set_from_stock(gtk.STOCK_HOME)
        self.icon.set_tooltip(u'ShulGo')
        self.icon.set_visible(True)
        self.icon.connect('activate', self._on_click)
        self.icon.connect('popup-menu', self._on_menu)

        # The panel line before anything is asked of the network, so the slot is never empty while
        # a cold login waits on a first request.
        self._write_bar(None)
        self.refresh()
        gobject.timeout_add(TICK_MS, self._tick)
        gobject.timeout_add(max(60, config.as_int(self.settings, u'refresh-seconds')) * 1000,
                            self._on_timer)
        self._watch_pending()

    # ---- the icon itself -------------------------------------------------------------------

    # ---- asking ShulGo ---------------------------------------------------------------------

    def _on_timer(self):
        self.refresh()

        return True

    def _tick(self):
        self._draw()

        return True

    def refresh(self, fresh=False):
        if self._work is not None and self._work.isAlive():
            return True

        place = config.saved_place(self.settings)
        if place is None:
            self._draw()

            return True

        lat, lng = place[0], place[1]
        self._work = threading.Thread(target=self._do_refresh, args=(lat, lng, fresh))
        self._work.setDaemon(True)
        self._work.start()

        return True

    def _do_refresh(self, lat, lng, fresh):
        u"""Runs OFF the main loop. Touches no widget — only locals, then hands the answer back."""
        minyanim = self.api.next(
            lat, lng,
            tefillah=self.settings.get(u'tefillah', u'next'),
            window_min=config.as_int(self.settings, u'window-minutes'),
            mode=self.settings.get(u'travel-mode', u'drive'),
        )
        zmanim = {}
        if self.settings.get(u'show-zmanim') == u'yes':
            zmanim = self.api.zmanim(lat, lng)

        gobject.idle_add(self._absorb, minyanim, zmanim)

    def _absorb(self, minyanim, zmanim):
        u"""Back on the main loop, which is the only place a widget may be touched."""
        if minyanim.get(u'ok'):
            self.state[u'minyanim'] = minyanim.get(u'data') or []
            self.state[u'updated'] = minyanim.get(u'at') or 0
            self.state[u'why'] = None
            self.state[u'whyMessage'] = None
            self.state[u'staleSince'] = 0
        else:
            self.state[u'why'] = minyanim.get(u'code')
            self.state[u'whyMessage'] = minyanim.get(u'message')
            self.state[u'staleSince'] = minyanim.get(u'staleSince') or 0
            if minyanim.get(u'data'):
                self.state[u'minyanim'] = minyanim[u'data']
        if zmanim.get(u'ok'):
            self.state[u'zmanim'] = zmanim.get(u'data') or {}
        self._draw()

        return False

    # ---- drawing ---------------------------------------------------------------------------

    def _draw(self):
        rows = still_ahead(self.state[u'minyanim'])
        place = config.saved_place(self.settings)
        headline = pick_headline(rows) if place else None

        # StatusIcon tooltips are plain text on 2.12 — no markup — so this is the same information
        # the menu carries, written out flat.
        lines = []
        if place is None:
            lines.append(u'ShulGo — open Settings and choose a place')
        elif not self.api.has_key:
            lines.append(u'ShulGo — not linked yet')
        else:
            lines.append(u'ShulGo — %s' % place[2])
            notice = offline_notice(self.state, bool(rows))
            if notice:
                lines.append(notice[u'short'])
            if headline:
                lines.append(u'%s  %s  %s' % (
                    minyan_time(headline) or u'',
                    tefillah_label(headline.get(u'tefillah')),
                    countdown(minutes_until(headline.get(u'starts_at')))))
            elif not notice:
                lines.append(u'Nothing in the next %d minutes.'
                             % config.as_int(self.settings, u'window-minutes'))
        self.icon.set_tooltip(u'\n'.join(lines))

        self._write_bar(headline, rows)

    def _write_bar(self, headline, rows=()):
        u"""Keep the panel file current. Same contract and same wording as the Xfce widget."""
        if self.settings.get(u'panel-line') != u'yes':
            config.clear_bar()

            return

        place = config.saved_place(self.settings)
        notice = offline_notice(self.state, bool(rows))
        config.save_bar(bar.document(
            headline=headline,
            rows=rows,
            zmanim=zmanim_list(self.state[u'zmanim']),
            place=place[2] if place else None,
            has_key=self.api.has_key,
            stale=bool(notice),
            stale_since=notice[u'short'] if notice else None,
            window_minutes=config.as_int(self.settings, u'window-minutes'),
            pending=self._pending is not None,
        ))

    # ---- the menu --------------------------------------------------------------------------

    def _label_item(self, markup, sensitive=True):
        item = gtk.MenuItem()
        label = gtk.Label()
        label.set_markup(markup)
        label.set_alignment(0.0, 0.5)
        item.add(label)
        item.set_sensitive(sensitive)

        return item

    def _build_menu(self):
        u"""Rebuilt on each open rather than kept and updated.

        On a Pentium III that sounds wasteful and is not: the menu exists for a second or two a few
        times a day, and a menu rebuilt from the current state cannot show yesterday's minyan
        because some update path forgot to touch it.
        """
        menu = gtk.Menu()
        rows = still_ahead(self.state[u'minyanim'])
        place = config.saved_place(self.settings)

        if place is None:
            menu.append(self._label_item(u'<b>Choose where you daven</b>', sensitive=False))
            menu.append(self._label_item(u'<small>Open Settings and pick a place.</small>',
                                         sensitive=False))
        else:
            menu.append(self._label_item(u'<b>%s</b>' % escape_markup(place[2]), sensitive=False))

            if self._pending is not None:
                menu.append(self._label_item(
                    u'<i>%s</i>' % escape_markup(link.words(link.PENDING, self._pending)),
                    sensitive=False))
            elif not self.api.has_key:
                menu.append(self._label_item(
                    u'<small>Not linked yet — choose “Link this computer”.</small>',
                    sensitive=False))

            notice = offline_notice(self.state, bool(rows))
            if notice:
                menu.append(self._label_item(u'<i>%s</i>' % escape_markup(notice[u'short']),
                                             sensitive=False))

            how = self.settings.get(u'travel-mode', u'drive')
            for row in rows[:config.as_int(self.settings, u'list-length')]:
                clock = minyan_time(row)
                name = tefillah_label(row.get(u'tefillah'))
                first = u'%s  %s' % (clock, name) if clock else name
                under = u' · '.join([x for x in (
                    countdown(minutes_until(row.get(u'starts_at'))),
                    minyan_subtitle(row, how)) if x])
                markup = u'<b>%s</b>' % escape_markup(first)
                if under:
                    markup += u'\n<small>%s</small>' % escape_markup(under)
                note = minyan_note(row)
                if note:
                    markup += u'\n<small>%s</small>' % escape_markup(note)
                item = self._label_item(markup)
                item.destination = minyan_destination(row)
                item.connect('activate', self._on_minyan)
                menu.append(item)

            if not rows and self.api.has_key and not notice:
                menu.append(self._label_item(
                    u'<small>Nothing in the next %d minutes.</small>'
                    % config.as_int(self.settings, u'window-minutes'), sensitive=False))

            zmanim = zmanim_list(self.state[u'zmanim'])
            if zmanim and self.settings.get(u'show-zmanim') == u'yes':
                menu.append(gtk.SeparatorMenuItem())
                holder = gtk.MenuItem(u'Today’s zmanim')
                inner = gtk.Menu()
                for z in zmanim:
                    text = u'%s  %s' % (escape_markup(z.get(u'label') or z.get(u'name') or u''),
                                        escape_markup(zman_time(z)))
                    inner.append(self._label_item(
                        u'<b>%s</b>' % text if z.get(u'isNext') else text, sensitive=False))
                holder.set_submenu(inner)
                menu.append(holder)

            if self.state[u'updated']:
                menu.append(self._label_item(
                    u'<small>%s</small>' % escape_markup(updated_ago(self.state[u'updated'])),
                    sensitive=False))

        menu.append(gtk.SeparatorMenuItem())
        for text, handler in (
            (u'Refresh now', self._on_refresh),
            (u'Link this computer…', self._on_link),
            (u'Settings…', self._on_settings),
            (u'Quit', self._on_quit),
        ):
            if text.startswith(u'Link') and self.api.has_key:
                continue
            item = gtk.MenuItem(text)
            item.connect('activate', handler)
            menu.append(item)

        menu.show_all()

        return menu

    # ---- what the menu does ----------------------------------------------------------------

    def _on_click(self, icon):
        menu = self._build_menu()
        menu.popup(None, None, gtk.status_icon_position_menu, 1, gtk.get_current_event_time(), icon)

    def _on_menu(self, icon, button, when):
        menu = self._build_menu()
        menu.popup(None, None, gtk.status_icon_position_menu, button, when, icon)

    def _on_minyan(self, item):
        uri = maps_uri(getattr(item, 'destination', None))
        if uri:
            _open(uri)

    def _on_refresh(self, *ignored):
        self.refresh(fresh=True)

    def _on_settings(self, *ignored):
        from .windows import SettingsWindow
        SettingsWindow(self).show()

    def _on_link(self, *ignored):
        from .windows import LinkWindow
        LinkWindow(self).show()

    def _on_quit(self, *ignored):
        self.cache.save()
        config.clear_bar()
        gtk.main_quit()

    # ---- a linking somebody walked away from -----------------------------------------------

    def _watch_pending(self):
        u"""Pick up a linking that outlived its window, or a reboot.

        The window does not own the linking: it is written down. Closing the window used to abandon
        it, which cost a real person two rounds of asking an administrator to approve something that
        was then thrown away.
        """
        saved = config.load_pending()
        if saved is None:
            return

        # resume, not the constructor: the file holds a deadline, not a duration, and the
        # constructor read it as a fresh ten-minute code.
        self._pending = link.Linking.resume(saved)
        self._poll_pending()

    def _poll_pending(self):
        if self._pending is None:
            return False

        threading.Thread(target=self._do_poll, args=(self._pending.device_code,)).start()

        return False

    def _do_poll(self, device_code):
        gobject.idle_add(self._pending_answer, self.api.device_poll(device_code))

    def _pending_answer(self, answer):
        if self._pending is None:
            return False

        pending = self._pending
        state = pending.absorb(answer)
        if state == link.DONE:
            # `key`, which is what link.Linking calls it. This read `api_key` and raised
            # AttributeError on the one answer that mattered — after ShulGo had minted the key and
            # before it was written down — so an approved computer stayed "not linked" and the
            # key, which the server hands out once, was gone.
            config.save_api_key(pending.key)
            config.clear_pending()
            self._pending = None
            self.api.reconfigure(api_key=pending.key)
            self.refresh(fresh=True)
            self._notify(u'This computer is linked to ShulGo',
                         u'Click the ShulGo icon to see the next minyanim.')
        elif state in (link.DENIED, link.EXPIRED):
            config.clear_pending()
            self._pending = None
            self._notify(state == link.DENIED and u'ShulGo link turned down'
                         or u'ShulGo link code ran out',
                         u'%s To try again, click the ShulGo icon and choose “Link this computer…”.'
                         % link.words(state, pending))
        else:
            config.save_pending(self._pending.device_code, self._pending.user_code,
                                self._pending.expires_at, self._pending.interval)
            gobject.timeout_add(max(1, self._pending.interval) * 1000, self._poll_pending)
        self._draw()
        if self._link_window is not None:
            self._link_window.show_state(state, pending)

        return False

    def _notify(self, summary, body):
        u"""Separate so a test can listen in without a notification daemon."""
        return bubble(self.icon, summary, body)


def main():
    gtk.gdk.threads_init()
    Tray()
    gtk.main()

    return 0
