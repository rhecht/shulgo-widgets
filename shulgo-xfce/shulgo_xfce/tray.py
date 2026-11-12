"""The tray icon and its menu: GTK3, X11, StatusNotifierItem.

Written for a machine with 256 MB of RAM and a CPU around 1 GHz, and the shape follows from that
rather than from taste:

  * A Gtk.Menu, not a window. A popup menu is the cheapest thing a tray can own, it is what the
    systray protocol expects, and it needs no compositing.
  * Nothing is built until it is needed. The settings dialog lives in its own module and is imported
    the first time somebody opens it, so a session that never opens it never pays for it.
  * The menu's widgets are made once and then relabelled. Rebuilding a menu every time a countdown
    changes would be the single most expensive thing this program does.
  * Countdowns are worked out locally on a 60-second tick with no network at all. The network is
    touched on a long timer (15 minutes by default) and when somebody asks for it.
  * One worker thread does the asking, so the panel never stops drawing while a request is out.
    Answers come back to the main loop through GLib.idle_add, which is the only safe way in.

Three tray implementations are tried in order, because what a given Xfce has is not knowable from
here: Ayatana's AppIndicator3 (what Arch and most current distributions ship), the older Ubuntu
AppIndicator3, and finally Gtk.StatusIcon. StatusIcon is deprecated and GTK4 dropped it, but this is
GTK3 and on a 25-year-old laptop a deprecated thing that works beats a modern thing that is missing.
"""

import threading

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gio, Gtk  # noqa: E402

from . import config  # noqa: E402
from .api import Cache, ShulGoApi  # noqa: E402
from .pick import headline as pick_headline, still_ahead  # noqa: E402
from .fmt import (  # noqa: E402
    countdown, countdown_short, escape_markup, minutes_until, minyan_destination, minyan_note,
    minyan_subtitle, maps_uri, offline_notice, tefillah_label, today_iso, updated_ago, zmanim_list,
)

ICON_NAME = 'shulgo'


def _load_indicator():
    """The tray library this machine actually has. Returns (class, flavour) or (None, None).

    Three possibilities, tried in order, because what a given Xfce has is not knowable from here:
    Ayatana's AppIndicator3 (Arch and most current distributions), the older Ubuntu AppIndicator3,
    and then nothing — in which case the caller falls back to Gtk.StatusIcon. StatusIcon is
    deprecated and GTK4 dropped it, but this is GTK3, and on a 25-year-old laptop a deprecated thing
    that works beats a modern thing that is not installed.
    """
    for name, version in (('AyatanaAppIndicator3', '0.1'), ('AppIndicator3', '0.1')):
        try:
            gi.require_version(name, version)
            module = __import__('gi.repository', fromlist=[name])

            return getattr(module, name), name
        except (ValueError, ImportError, AttributeError):
            continue

    return None, None


class ShulGoTray:
    def __init__(self):
        self.settings = config.load_settings()
        self.cache = Cache(config.cache_path())
        self.monitor = Gio.NetworkMonitor.get_default()
        self.api = ShulGoApi(
            base_url=self.settings.get('api-base-url'),
            api_key=config.load_api_key(),
            cache=self.cache,
            is_online=lambda: self.monitor.get_network_available(),
        )

        # What we know. `why` and `staleSince` are the same names format.js's offlineNotice reads, so
        # the wording code can be handed this dict as it stands.
        self.state = {
            'minyanim': [], 'zmanim': {}, 'updated': 0, 'why': None, 'whyMessage': None,
            'staleSince': 0, 'busy': False,
        }

        self._work = None
        self._items = []          # the reusable minyan rows
        self._settings_window = None

        self._timer = None
        self._build()
        self.refresh()
        GLib.timeout_add_seconds(60, self._tick)
        self._start_timer()

    # ---- the tray icon ---------------------------------------------------------------------

    def _build(self):
        self.menu = Gtk.Menu()

        self.header = self._text_item('', sensitive=False)
        self.menu.append(self.header)
        self.menu.append(Gtk.SeparatorMenuItem())

        self.notice = self._text_item('', sensitive=False)
        self.menu.append(self.notice)

        # How many rows exist is fixed here. Changing "minyanim in the menu" in settings takes
        # effect next time the widget starts — rebuilding a live menu's children is not worth the
        # code or the memory on this hardware, and the settings window says so.
        for _ in range(max(1, config.as_int(self.settings, 'list-length'))):
            item = self._text_item('')
            item.connect('activate', self._on_minyan)
            item.destination = None
            self.menu.append(item)
            self._items.append(item)

        self.zmanim_item = Gtk.MenuItem(label='Today’s zmanim')
        self.zmanim_menu = Gtk.Menu()
        self.zmanim_item.set_submenu(self.zmanim_menu)
        self.menu.append(self.zmanim_item)

        self.menu.append(Gtk.SeparatorMenuItem())
        self.footer = self._text_item('', sensitive=False)
        self.menu.append(self.footer)

        for label, handler in (
            ('Refresh now', lambda *_: self.refresh(fresh=True)),
            ('Open ShulGo', self._on_open_site),
            ('Settings…', self._on_settings),
            ('Quit', self._on_quit),
        ):
            item = Gtk.MenuItem(label=label)
            item.connect('activate', handler)
            self.menu.append(item)

        self.menu.show_all()
        # show_all() turned on every row, including the minyan rows that have no minyan in them yet.
        # The first answer is still out on a thread, so hide them until there is something to say —
        # otherwise the menu opens with a column of empty lines.
        for item in self._items:
            item.hide()
        self.notice.hide()
        self.footer.hide()
        self.zmanim_item.hide()

        indicator, flavour = _load_indicator()
        self.flavour = flavour
        if indicator is not None:
            self.indicator = indicator.Indicator.new(
                'shulgo-xfce', ICON_NAME, indicator.IndicatorCategory.APPLICATION_STATUS)
            self.indicator.set_status(indicator.IndicatorStatus.ACTIVE)
            self.indicator.set_menu(self.menu)
            # Some panels show this beside the icon and some ignore it. Where it shows, it is the
            # whole point: the next minyan without opening anything.
            if hasattr(self.indicator, 'set_label'):
                self.indicator.set_label('', '')
            self.status_icon = None
        else:
            self.indicator = None
            self.status_icon = Gtk.StatusIcon.new_from_icon_name(ICON_NAME)
            self.status_icon.set_tooltip_text('ShulGo')
            self.status_icon.connect(
                'popup-menu',
                lambda icon, button, when: self.menu.popup(None, None, None, None, button, when))
            self.status_icon.connect(
                'activate',
                lambda icon: self.menu.popup(None, None, None, None, 0, Gtk.get_current_event_time()))

    def _text_item(self, markup, sensitive=True):
        """A menu row whose label we can keep rewriting, left-aligned, markup allowed."""
        item = Gtk.MenuItem()
        label = Gtk.Label()
        label.set_xalign(0.0)
        label.set_markup(markup)
        item.add(label)
        item.set_sensitive(sensitive)
        item.shulgo_label = label

        return item

    # ---- asking ShulGo ---------------------------------------------------------------------

    def refresh(self, fresh=False):
        """Ask for minyanim and zmanim on the worker thread, unless one is already out."""
        if self._work is not None and self._work.is_alive():
            return True

        place = config.saved_place(self.settings)
        if place is None:
            self.state.update(why=None, whyMessage=None)
            self._draw(no_place=True)

            return True

        lat, lng, _label = place
        self.state['busy'] = True
        self._work = threading.Thread(target=self._do_refresh, args=(lat, lng, fresh), daemon=True)
        self._work.start()

        return True

    def _do_refresh(self, lat, lng, fresh):
        """Runs OFF the main loop. Touches nothing but locals, then hands the answer back."""
        api = self.api
        minyanim = api.next(
            lat, lng,
            tefillah=self.settings.get('tefillah', 'next'),
            window_min=config.as_int(self.settings, 'window-minutes'),
            mode=self.settings.get('travel-mode', 'drive'),
        )
        zmanim = ({'ok': True, 'data': {}} if self.settings.get('show-zmanim') != 'yes'
                  else api.zmanim(lat, lng, date=today_iso()))

        GLib.idle_add(self._absorb, minyanim, zmanim)

    def _absorb(self, minyanim, zmanim):
        """Back on the main loop with whatever came of it."""
        self.state['busy'] = False

        if minyanim.get('ok'):
            # /next answers a bare array; store.js reads it the same way.
            data = minyanim.get('data')
            self.state['minyanim'] = data if isinstance(data, list) else []
            if minyanim.get('stale'):
                self.state['why'] = minyanim.get('why')
                self.state['whyMessage'] = minyanim.get('whyMessage')
                self.state['staleSince'] = minyanim.get('cachedAt') or 0
            else:
                self.state['why'] = None
                self.state['whyMessage'] = None
                self.state['staleSince'] = 0
                self.state['updated'] = int(GLib.get_real_time() / 1000000)
        else:
            self.state['why'] = minyanim.get('code')
            self.state['whyMessage'] = minyanim.get('message')

        if zmanim.get('ok'):
            data = zmanim.get('data')
            self.state['zmanim'] = data if isinstance(data, dict) else {}

        self._draw()

        return False

    def _start_timer(self):
        """(Re)arm the network timer from the setting.

        Re-armed rather than set once in __init__, because a timeout's interval is fixed when it is
        created: without this, changing "check ShulGo every" in settings would appear to work and
        then quietly go on using the old interval until the widget was restarted.
        """
        if self._timer is not None:
            GLib.source_remove(self._timer)
        seconds = max(60, config.as_int(self.settings, 'refresh-seconds'))
        self._timer = GLib.timeout_add_seconds(seconds, self._on_timer)

    def _on_timer(self):
        self.refresh()

        return True

    def _tick(self):
        """Every minute: redo the countdowns. No network, no new widgets."""
        self._draw()

        return True

    # ---- drawing ---------------------------------------------------------------------------

    def _draw(self, no_place=False):
        rows = still_ahead(self.state['minyanim'])

        place = config.saved_place(self.settings)
        if no_place or place is None:
            self._set(self.header, '<b>Choose where you daven</b>')
            self._set(self.notice, 'Open Settings and pick a place.')
            self.notice.show()
            for item in self._items:
                item.hide()
            self.zmanim_item.hide()
            self._set(self.footer, '')
            self.footer.hide()
            self._panel('')

            return

        self._set(self.header, '<b>%s</b>' % escape_markup(place[2]))

        notice = offline_notice(self.state, bool(rows) or bool(self.state['zmanim']))
        if not self.api.has_key:
            self._set(self.notice, 'Add your ShulGo API key in Settings.')
            self.notice.show()
        elif notice:
            self._set(self.notice, '<i>%s</i>' % escape_markup(notice['short']))
            self.notice.show()
        elif self.state.get('whyMessage') and not rows:
            self._set(self.notice, '<i>%s</i>' % escape_markup(self.state['whyMessage']))
            self.notice.show()
        else:
            self.notice.hide()

        mode = self.settings.get('travel-mode', 'drive')
        for item, row in zip(self._items, rows):
            minutes = minutes_until(row.get('starts_at'))
            subtitle = minyan_subtitle(row, mode)
            note = minyan_note(row)
            line = '<b>%s %s</b>' % (escape_markup(tefillah_label(row.get('tefillah'))),
                                     escape_markup(countdown(minutes)))
            if subtitle:
                line += '\n<small>%s</small>' % escape_markup(subtitle)
            if note:
                line += '\n<small>%s</small>' % escape_markup(note)
            self._set(item, line)
            item.destination = minyan_destination(row)
            item.show()
        for item in self._items[len(rows):]:
            item.hide()

        if not rows and self.api.has_key and not notice:
            self._set(self.notice, 'Nothing in the next %d minutes.'
                      % config.as_int(self.settings, 'window-minutes'))
            self.notice.show()

        self._draw_zmanim()

        updated = updated_ago(self.state['updated']) if self.state['updated'] else ''
        self._set(self.footer, '<small>%s</small>' % escape_markup(updated) if updated else '')
        self.footer.set_visible(bool(updated))

        headline = pick_headline(rows)
        self._panel(countdown_short(minutes_until(headline.get('starts_at'))) if headline else '')

    def _draw_zmanim(self):
        if self.settings.get('show-zmanim') != 'yes':
            self.zmanim_item.hide()

            return

        rows = zmanim_list(self.state['zmanim'])
        for child in self.zmanim_menu.get_children():
            self.zmanim_menu.remove(child)
        if not rows:
            self.zmanim_item.hide()

            return

        for z in rows:
            label = z.get('label') or z.get('name') or ''
            when = z.get('display_time') or ''
            text = '%s  %s' % (escape_markup(label), escape_markup(when))
            item = self._text_item('<b>%s</b>' % text if z.get('isNext') else text, sensitive=False)
            self.zmanim_menu.append(item)
        self.zmanim_menu.show_all()
        self.zmanim_item.show()

    def _set(self, item, markup):
        item.shulgo_label.set_markup(markup)

    def _panel(self, text):
        """The bit of text beside the icon, where the panel shows one."""
        if self.indicator is not None and hasattr(self.indicator, 'set_label'):
            self.indicator.set_label(text or '', '1h00')
        if self.status_icon is not None:
            self.status_icon.set_tooltip_text('ShulGo — %s' % text if text else 'ShulGo')

    # ---- what the menu does ----------------------------------------------------------------

    def _on_minyan(self, item):
        uri = maps_uri(getattr(item, 'destination', None))
        if uri:
            self._open(uri)

    def _on_open_site(self, *_):
        self._open(self.api.site_url)

    def _open(self, uri):
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error:
            # No browser, or no desktop to ask. Not worth a dialog in a tray menu.
            pass

    def _on_settings(self, *_):
        # Imported here, not at the top: a session that never opens settings never loads this.
        from .settings_window import SettingsWindow

        if self._settings_window is not None:
            self._settings_window.present()

            return

        def done(changed):
            self._settings_window = None
            if changed:
                self.settings = config.load_settings()
                self.api.reconfigure(base_url=self.settings.get('api-base-url'),
                                     api_key=config.load_api_key())
                self._start_timer()
                self.refresh(fresh=True)

        self._settings_window = SettingsWindow(self.api, done)
        self._settings_window.present()

    def _on_quit(self, *_):
        self.cache.save()
        Gtk.main_quit()
