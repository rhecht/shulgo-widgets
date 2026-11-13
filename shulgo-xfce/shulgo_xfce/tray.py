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

from . import config, icon as icons  # noqa: E402
from .api import Cache, ShulGoApi  # noqa: E402
from .pick import headline as pick_headline, rows as rows_in, still_ahead  # noqa: E402
from .fmt import (  # noqa: E402
    countdown, countdown_short, escape_markup, event_date, maps_uri, miles, minutes_until,
    minyan_destination, minyan_note, minyan_subtitle, offline_notice, shiur_subtitle,
    tefillah_label, today_iso, updated_ago, zmanim_list,
)

ICON_NAME = icons.ICON_NAME


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
            'minyanim': [], 'zmanim': {}, 'events': [], 'shiurim': [],
            'updated': 0, 'why': None, 'whyMessage': None, 'staleSince': 0, 'busy': False,
        }

        # The submenus are rebuilt from scratch, which is the most expensive thing this program does;
        # the minyan rows beside them are only relabelled. So they are rebuilt when new data arrives
        # and NOT on the one-minute countdown tick, which would otherwise throw away and remake three
        # menus a minute on a 1 GHz CPU for the sake of numbers that did not change.
        self._lists_dirty = True

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

        self.events_item = Gtk.MenuItem(label='Upcoming events')
        self.events_menu = Gtk.Menu()
        self.events_item.set_submenu(self.events_menu)
        self.menu.append(self.events_item)

        self.shiurim_item = Gtk.MenuItem(label='Shiurim nearby')
        self.shiurim_menu = Gtk.Menu()
        self.shiurim_item.set_submenu(self.shiurim_menu)
        self.menu.append(self.shiurim_item)

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
        self.events_item.hide()
        self.shiurim_item.hide()

        # Where the icon is going to come from. A name alone resolves only once the file is in an
        # icon theme, so run from a checkout there is nothing to resolve and the panel draws nothing
        # at all — no error, no warning, no icon. Found the hard way on the first machine that ever
        # ran this.
        self.icon_dir = icons.bundled_dir()
        theme_has_icon = False
        try:
            theme_has_icon = Gtk.IconTheme.get_default().has_icon(ICON_NAME)
        except Exception:
            pass
        self.icon_state = icons.plan(theme_has_icon, self.icon_dir)

        indicator, flavour = _load_indicator()
        self.flavour = flavour
        if indicator is not None:
            if self.icon_state == icons.BUNDLED and hasattr(indicator.Indicator, 'new_with_path'):
                # The StatusNotifierItem protocol carries an IconThemePath for exactly this, and the
                # panel looks for <path>/<name>.svg directly. Guarded by hasattr because this code
                # has to run against two different appindicator libraries and I can only test one.
                self.indicator = indicator.Indicator.new_with_path(
                    'shulgo-xfce', ICON_NAME, indicator.IndicatorCategory.APPLICATION_STATUS,
                    self.icon_dir)
            else:
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
            bundled = icons.bundled_file(self.icon_dir) if self.icon_state == icons.BUNDLED else None
            self.status_icon = (Gtk.StatusIcon.new_from_file(bundled) if bundled
                                else Gtk.StatusIcon.new_from_icon_name(ICON_NAME))
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
        # Each of these is one more request per refresh, which is why they are switchable and why the
        # settings window says so. Their TTLs are ten minutes against the minyan list's one, so a
        # refresh usually answers them from memory without touching the network at all.
        events = ({'ok': True, 'data': {}} if self.settings.get('show-events') != 'yes'
                  else api.events(lat, lng))
        shiurim = ({'ok': True, 'data': {}} if self.settings.get('show-shiurim') != 'yes'
                   else api.shiurim(lat, lng))

        GLib.idle_add(self._absorb, minyanim, zmanim, events, shiurim)

    def _absorb(self, minyanim, zmanim, events, shiurim):
        """Back on the main loop with whatever came of it."""
        self.state['busy'] = False

        if minyanim.get('ok'):
            self.state['minyanim'] = rows_in(minyanim)
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

        if events.get('ok'):
            self.state['events'] = rows_in(events, 'events')
        if shiurim.get('ok'):
            self.state['shiurim'] = rows_in(shiurim, 'shiurim')

        self._lists_dirty = True
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

        if self._lists_dirty:
            self._draw_zmanim()
            self._draw_events()
            self._draw_shiurim()
            self._lists_dirty = False

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

    def _draw_events(self):
        """Upcoming events near the saved place, worded as the GNOME and Mac widgets word them."""
        if self.settings.get('show-events') != 'yes':
            self.events_item.hide()

            return

        for child in self.events_menu.get_children():
            self.events_menu.remove(child)

        rows = self.state['events'][:config.as_int(self.settings, 'list-length')]
        if not rows:
            self.events_menu.append(
                self._text_item('<i>No events coming up near here.</i>', sensitive=False))
        for event in rows:
            when = event_date(event.get('date'))
            if event.get('start_time'):
                when = '%s, %s' % (when, event['start_time'])
            line = '<b>%s</b>' % escape_markup(event.get('title') or 'An event')
            where = ' · '.join([x for x in (
                when,
                event.get('where'),
                'Online' if event.get('online') else '',
                miles(event.get('distance_miles')),
            ) if x])
            if where:
                line += '\n<small>%s</small>' % escape_markup(where)

            item = self._text_item(line)
            item.shulgo_uri = event.get('url') or ('%s/events' % self.api.site_url)
            item.connect('activate', self._on_uri_item)
            self.events_menu.append(item)

        self.events_menu.show_all()
        self.events_item.show()

    def _draw_shiurim(self):
        """Shiurim near the saved place.

        A shiur's `when` arrives already written out by the server ("Mondays, 8:00 PM") because it is
        a weekday pattern rather than a moment, so there is no countdown here and nothing to tick.
        """
        if self.settings.get('show-shiurim') != 'yes':
            self.shiurim_item.hide()

            return

        for child in self.shiurim_menu.get_children():
            self.shiurim_menu.remove(child)

        rows = self.state['shiurim'][:config.as_int(self.settings, 'list-length')]
        if not rows:
            self.shiurim_menu.append(
                self._text_item('<i>No shiurim listed near here.</i>', sensitive=False))
        for shiur in rows:
            line = '<b>%s</b>' % escape_markup(shiur.get('title') or 'A shiur')
            if shiur.get('when'):
                line += '  <small>%s</small>' % escape_markup(shiur['when'])
            subtitle = shiur_subtitle(shiur)
            if subtitle:
                line += '\n<small>%s</small>' % escape_markup(subtitle)

            item = self._text_item(line)
            # A shiur has no page of its own on ShulGo, so the useful click is directions when we
            # have them and the shiurim list when we don't.
            item.shulgo_uri = (maps_uri(shiur.get('directions'))
                               or '%s/shiurim' % self.api.site_url)
            item.connect('activate', self._on_uri_item)
            self.shiurim_menu.append(item)

        self.shiurim_menu.show_all()
        self.shiurim_item.show()

    def _on_uri_item(self, item):
        uri = getattr(item, 'shulgo_uri', None)
        if uri:
            self._open(uri)

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
