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

from . import bar, config, icon as icons  # noqa: E402
from .api import Cache, ShulGoApi  # noqa: E402
from .pick import headline as pick_headline, rows as rows_in, still_ahead  # noqa: E402
from . import link  # noqa: E402
from .fmt import (  # noqa: E402
    countdown, countdown_short, escape_markup, event_date, maps_uri, miles, minutes_until,
    minyan_destination, minyan_note, minyan_subtitle, minyan_time, offline_notice, shiur_subtitle,
    tefillah_label, today_iso, updated_ago, zman_time, zmanim_list,
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
        # A linking somebody started and walked away from. The window does not own its life: it is
        # written down, and this picks it up — after the window closes, and after a reboot, which on
        # a machine somebody switches off overnight is the normal case.
        self._pending = None
        self._pending_timer = None
        self._build()
        # The top-bar line goes out before anything is asked of the network. refresh() does draw it
        # on the no-place path, but only once it has run, and on a cold login that is a gap in which
        # the panel slot sits empty — which is the one moment a new user most needs to be told that
        # the thing wants linking. Somebody running --check in that gap saw "nothing written yet"
        # and reasonably read it as the line being broken.
        self._bar(None)
        self.refresh()
        GLib.timeout_add_seconds(60, self._tick)
        self._start_timer()
        self._watch_pending()

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
            ('Link this computer…', self._on_link),
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

    # ---- a linking that outlived its window ---------------------------------------------------

    def _watch_pending(self):
        """Carry on asking about a linking the window is no longer watching.

        Started when the tray starts, and again whenever the link window closes. Does nothing when
        there is nothing pending, which is almost always.
        """
        self._stop_pending_timer()
        saved = config.load_pending()
        if not saved:
            self._pending = None
            self._draw()

            return

        self._pending = link.Linking.resume(saved)
        self._draw()
        self._pending_timer = GLib.timeout_add_seconds(max(1, self._pending.interval),
                                                       self._poll_pending)

    def _stop_pending_timer(self):
        if self._pending_timer is not None:
            GLib.source_remove(self._pending_timer)
            self._pending_timer = None

    def _poll_pending(self):
        self._pending_timer = None
        if self._pending is None:
            return False

        # Deliberately NOT "if expired, give up". Our deadline is the last one the server told us,
        # and it moves; asking is cheap and the answer is authoritative. expired_token is what ends
        # this, below.
        threading.Thread(target=self._do_poll_pending,
                         args=(self._pending.device_code,), daemon=True).start()

        return False

    def _do_poll_pending(self, device_code):
        GLib.idle_add(self._pending_answer, self.api.device_poll(device_code))

    def _pending_answer(self, answer):
        if self._pending is None:
            return False

        state = self._pending.absorb(answer)
        if state == link.PENDING:
            # Keep the written-down deadline in step with the server's, so a restart does not read
            # a stale one and give up on a linking that is still alive.
            config.save_pending(self._pending.device_code, self._pending.user_code,
                                self._pending.expires_at, self._pending.interval)
            self._pending_timer = GLib.timeout_add_seconds(max(1, self._pending.interval),
                                                           self._poll_pending)
            self._draw()

            return False

        if state == link.DONE:
            # The same file a typed key goes in, and then straight to work: somebody approved this
            # hours ago and the widget should simply start.
            config.save_api_key(self._pending.key)
            config.clear_pending()
            self._pending = None
            self.api.reconfigure(api_key=config.load_api_key())
            self._draw()
            self.refresh(fresh=True)

            return False

        config.clear_pending()
        self._pending = None
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
            self._bar(None, no_place=True)

            return

        self._set(self.header, '<b>%s</b>' % escape_markup(place[2]))

        notice = offline_notice(self.state, bool(rows) or bool(self.state['zmanim']))
        if self._pending is not None:
            self._set(self.notice, '<i>%s</i>'
                      % escape_markup(link.words(link.PENDING, self._pending)))
            self.notice.show()
        elif not self.api.has_key:
            self._set(self.notice, 'No key yet — choose “Link this computer”.')
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
            # The time it starts, then what it is — which is what somebody glances for. The
            # countdown moves down beside the shul and the distance: useful, but not the headline.
            # The first version showed only a countdown and no clock time anywhere, which is how
            # "I don't see any times" came back from somebody actually using it.
            clock = minyan_time(row)
            line = '<b>%s</b>' % escape_markup(
                '%s  %s' % (clock, tefillah_label(row.get('tefillah'))) if clock
                else tefillah_label(row.get('tefillah')))
            under = ' · '.join([x for x in (countdown(minutes), subtitle) if x])
            if under:
                line += '\n<small>%s</small>' % escape_markup(under)
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
        self._bar(headline, rows=rows, notice=notice)

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
            when = zman_time(z)
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

    def _bar(self, headline, rows=(), notice=None, no_place=False):
        """Keep the top-bar file current, for xfce4-genmon-plugin to cat.

        Written on every redraw, which includes the minute tick, so the countdown beside the clock
        moves without the panel ever starting a Python interpreter. Switched off in settings, the
        file goes away rather than sitting there growing stale: a line that is quietly frozen is
        worse than no line, because somebody will read it on their way out of the door.
        """
        if self.settings.get('panel-line') != 'yes':
            config.clear_bar()

            return

        place = config.saved_place(self.settings)
        config.save_bar(bar.document(
            headline=headline,
            rows=rows,
            zmanim=zmanim_list(self.state['zmanim']),
            place=None if no_place else (place[2] if place else None),
            has_key=self.api.has_key,
            stale=bool(notice),
            stale_since=notice['short'] if notice else None,
            window_minutes=config.as_int(self.settings, 'window-minutes'),
            pending=self._pending is not None,
        ))

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

    def _on_link(self, *_):
        """Linking, straight from the menu: the first thing a new install needs, and the one thing
        it cannot do without a key."""
        from .link_window import LinkWindow

        def done(linked):
            if linked:
                self.api.reconfigure(api_key=config.load_api_key())
                self.refresh(fresh=True)
            # Either way: if the window was closed on a linking still waiting, this picks it up.
            self._watch_pending()

        LinkWindow(self.api, done)

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
            # A linking can be started from inside Settings too, and left waiting.
            self._watch_pending()

        self._settings_window = SettingsWindow(self.api, done)
        self._settings_window.present()

    def _on_quit(self, *_):
        self.cache.save()
        config.clear_bar()
        Gtk.main_quit()
