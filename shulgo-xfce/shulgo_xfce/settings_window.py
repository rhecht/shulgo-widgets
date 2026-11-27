"""The settings window — imported only when somebody opens it.

That is the whole reason this is a separate module rather than part of tray.py: on a machine with
256 MB of RAM, a session that never opens settings should never pay for the widgets, and Python only
reads a module the first time it is imported.

Plain GTK3 containers, no templates, no .ui file to parse. The place box asks ShulGo's /places
endpoint on a worker thread, because a lookup on the main loop would freeze the panel on a slow link.
"""

import threading

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import config, icon as icons, layout  # noqa: E402

MODES = (('drive', 'Driving'), ('walk', 'Walking'))
TEFILLOS = (
    ('next', 'Whatever is next'),
    ('shacharis', 'Shacharis'),
    ('mincha', 'Mincha'),
    ('maariv', 'Maariv'),
)


class SettingsWindow(Gtk.Window):
    def __init__(self, api, on_close):
        super().__init__(title='ShulGo settings')
        self.api = api
        self._on_close = on_close
        self._changed = False
        self._found = []
        self._looking = None

        self.values = config.load_settings()
        self.set_border_width(12)
        self.connect('destroy', self._finish)

        # Two columns at this width, not one tall one, and never taller than the screen. It used to
        # ask for 460 wide and whatever height it liked, which on a 1280x800 Pentium III put Close
        # and Save below the bottom edge — and those machines are usually 1024x768 or smaller.
        # layout.window_size does the arithmetic, where tests/test_layout.py can reach it.
        work_x, work_y, work_w, work_h, screen_w, screen_h = self._monitor()
        width, height = layout.window_size(work_w, work_h, screen_w, screen_h)
        self.set_default_size(width, height)

        # And somewhere deliberate to open, rather than wherever the window manager drops it —
        # Xfce put it against the top-left corner. The middle of the *work area*, not of the
        # screen: layout.window_position says why that distinction matters on an 800x600 machine.
        where = layout.window_position(width, height, work_x, work_y, work_w, work_h)
        if where:
            self.move(*where)

        # A ceiling as well, so dragging the window taller cannot put the buttons off-screen again.
        # It is the room on the screen, NOT the height opened at: those differ, and using the
        # opened height here would have made the window unresizable, which is a worse fault than
        # the one being fixed. Belt and braces either way — the default size above is what actually
        # guarantees the fit, since a window manager is free to ignore a maximum-size hint.
        ceiling = layout.height_ceiling(work_h, screen_h)
        if ceiling:
            try:
                hints = Gdk.Geometry()
                hints.max_width = 32767
                hints.max_height = ceiling
                self.set_geometry_hints(None, hints, Gdk.WindowHints.MAX_SIZE)
            except Exception:
                pass

        # Give the window its own icon rather than relying on a dock matching the .desktop file.
        # From a checkout the themed name resolves to nothing, exactly as it did for the tray, so
        # the bundled file is used in that case — the same decision, made the same way.
        try:
            directory = icons.bundled_dir()
            if icons.plan(Gtk.IconTheme.get_default().has_icon(icons.ICON_NAME),
                          directory) == icons.BUNDLED:
                self.set_icon_from_file(icons.bundled_file(directory))
            else:
                self.set_icon_name(icons.ICON_NAME)
        except Exception:
            # A window without its own icon is a cosmetic loss, not a reason to fail to open.
            pass

        # The body sits in a scroller and the buttons sit outside it, and that is the part which
        # makes the cap above mean anything. set_default_size is only a request: a window whose
        # child insists on 850 px gets 850 px however little was asked for, which is how Close and
        # Save ended up off the bottom of the screen. A scroller may be shorter than its contents,
        # so the window can be as short as the screen requires and the buttons are still on it —
        # at 800x600, and at a font size nobody here has tried.
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add(outer)

        scroller = Gtk.ScrolledWindow()
        # NEVER across: this window was made wider precisely so nothing needs scrolling sideways.
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        outer.pack_start(scroller, True, True, 0)

        columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20, homogeneous=True)
        scroller.add(columns)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        columns.pack_start(left, True, True, 0)
        columns.pack_start(right, True, True, 0)

        # ---- left: the key, then where you are
        left.pack_start(self._heading('Your ShulGo API key'), False, False, 0)
        self.key_entry = Gtk.Entry()
        self.key_entry.set_text(config.load_api_key())
        self.key_entry.set_visibility(False)
        self.key_entry.set_placeholder_text('sg_live_…')
        self.key_entry.set_hexpand(True)
        left.pack_start(self.key_entry, False, False, 0)

        # NOT "Admin › System › API & apps": that is where an administrator makes a key, and an
        # ordinary person running this widget cannot reach it. Telling them to go somewhere they
        # have no access to is worse than saying nothing.
        link_button = Gtk.Button(label='Link this computer…')
        link_button.connect('clicked', self._on_link)
        link_button.set_halign(Gtk.Align.START)
        left.pack_start(link_button, False, False, 0)

        left.pack_start(self._note('Linking shows a short code to approve on your phone, and this '
                                   'computer gets its own key within seconds. The box above is for '
                                   'a key somebody gave you, which most people never have. Either '
                                   'way it is kept in ~/.config/jewbuntu/shulgo.conf, readable '
                                   'only by you — never in dconf.'), False, False, 0)

        # The other half of linking, and the half an uninstaller cannot do. `apt remove` takes the
        # program and leaves the key in the person's home directory, with this computer still
        # listed as a live device on their ShulGo account.
        forget_button = Gtk.Button(label='Forget this computer…')
        forget_button.connect('clicked', self._on_forget)
        forget_button.set_halign(Gtk.Align.START)
        left.pack_start(forget_button, False, False, 0)

        left.pack_start(self._heading('Where you daven'), False, False, 0)
        finding = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.place_entry = Gtk.Entry()
        self.place_entry.set_placeholder_text('A city, neighbourhood or zip code')
        self.place_entry.set_text(self.values.get('place', ''))
        self.place_entry.set_hexpand(True)
        self.place_entry.connect('activate', lambda *_: self._look())
        finding.pack_start(self.place_entry, True, True, 0)
        look = Gtk.Button(label='Search')
        look.connect('clicked', lambda *_: self._look())
        finding.pack_start(look, False, False, 0)
        left.pack_start(finding, False, False, 0)

        self.found_box = Gtk.ComboBoxText()
        self.found_box.set_hexpand(True)
        self.found_box.connect('changed', self._on_pick)
        # Hidden until a search has something to put in it. An empty combo box under the place
        # entry reads as a broken field with no label, which is worse than nothing being there:
        # somebody would try to work out what it is for. set_no_show_all keeps show_all() below
        # from revealing it; _look() shows it as soon as there is something to say.
        self.found_box.set_no_show_all(True)
        left.pack_start(self.found_box, False, False, 0)
        self.place_note = self._note(self._place_summary())
        left.pack_start(self.place_note, False, False, 0)

        # ---- right: what to show
        right.pack_start(self._heading('What to show'), False, False, 0)
        grid = Gtk.Grid(row_spacing=8, column_spacing=10)
        right.pack_start(grid, False, False, 0)
        row = 0

        self.window_spin = self._spin(15, 360, config.as_int(self.values, 'window-minutes'), 15)
        row = self._labelled(grid, row, 'Look ahead (minutes)', self.window_spin)
        self.length_spin = self._spin(1, 12, config.as_int(self.values, 'list-length'), 1)
        row = self._labelled(grid, row, 'Minyanim in the menu', self.length_spin)
        self.refresh_spin = self._spin(60, 3600, config.as_int(self.values, 'refresh-seconds'), 60)
        row = self._labelled(grid, row, 'Check ShulGo every (seconds)', self.refresh_spin)

        self.mode_box = self._choice(MODES, self.values.get('travel-mode', 'drive'))
        row = self._labelled(grid, row, 'Getting there by', self.mode_box)
        self.tefillah_box = self._choice(TEFILLOS, self.values.get('tefillah', 'next'))
        row = self._labelled(grid, row, 'Show', self.tefillah_box)

        self.zmanim_check = Gtk.CheckButton(label='Today’s zmanim in the menu')
        self.zmanim_check.set_active(self.values.get('show-zmanim') == 'yes')
        right.pack_start(self.zmanim_check, False, False, 0)

        self.events_check = Gtk.CheckButton(label='Upcoming events near you')
        self.events_check.set_active(self.values.get('show-events') == 'yes')
        right.pack_start(self.events_check, False, False, 0)

        self.shiurim_check = Gtk.CheckButton(label='Shiurim near you')
        self.shiurim_check.set_active(self.values.get('show-shiurim') == 'yes')
        right.pack_start(self.shiurim_check, False, False, 0)

        self.bar_check = Gtk.CheckButton(label='A line on the top bar, beside the clock')
        self.bar_check.set_active(self.values.get('panel-line') == 'yes')
        right.pack_start(self.bar_check, False, False, 0)

        right.pack_start(self._note('Countdowns are worked out here, so ShulGo is only asked on the '
                                    'timer above. Each list you switch off is one request fewer '
                                    'when it does.'), False, False, 0)

        # ---- the buttons, outside the scroller so they are always on screen
        buttons = Gtk.Box(spacing=8)
        buttons.set_halign(Gtk.Align.END)
        close = Gtk.Button(label='Close')
        close.connect('clicked', lambda *_: self.destroy())
        save = Gtk.Button(label='Save')
        save.get_style_context().add_class('suggested-action')
        save.connect('clicked', self._save)
        buttons.add(close)
        buttons.add(save)
        outer.pack_start(buttons, False, False, 0)

        self.show_all()

        # Close, not the first field. The first field is the API key: GTK focuses it on open and
        # selects all of it, so the window arrived with a masked key highlighted and one stray
        # keypress replaced the whole thing. Save it then and the widget stops working, with the
        # cause invisible — the key is dots on screen and there is no undo. Focused here instead,
        # a stray letter does nothing and a stray Return closes the window without saving.
        self.set_focus(close)

    # ---- the screen ------------------------------------------------------------------------

    def _monitor(self):
        """(work x, work y, work width, work height, screen width, screen height).

        Zeros throughout when none of it can be found out.

        Both sizes, because layout.window_size compares them: a work area smaller than the screen
        is a desktop that has published its panels, and one equal to the screen means they are
        either absent or invisible to us. The origin as well, because the work area does not start
        at the top of the screen when there is a panel above it — on Jewbuntu it starts at y=25,
        and a window centred as though it started at 0 would sit that much too high.

        Named rather than indexed at the call site. The caller used to pull these apart with
        screen[1] and screen[3], which is precisely the sort of thing that comes loose the first
        time somebody adds a figure to the middle of the tuple — as this change just did.

        Zeros on any failure, which the layout module reads as "assume an ordinary screen, and
        leave the position to the window manager". A settings window that will not open is a far
        worse outcome than one sized for 1024x768 on a machine with more room than that.
        """
        try:
            display = Gdk.Display.get_default()

            if hasattr(display, 'get_primary_monitor'):          # GTK 3.22 and after
                monitor = display.get_primary_monitor() or display.get_monitor(0)
                work, whole = monitor.get_workarea(), monitor.get_geometry()

                return work.x, work.y, work.width, work.height, whole.width, whole.height

            # Older GTK3: the same two rectangles, asked for the other way round.
            screen = Gdk.Screen.get_default()
            which = screen.get_primary_monitor()
            work = screen.get_monitor_workarea(which)
            whole = screen.get_monitor_geometry(which)

            return work.x, work.y, work.width, work.height, whole.width, whole.height
        except Exception:
            return 0, 0, 0, 0, 0, 0

    # ---- small builders --------------------------------------------------------------------

    def _heading(self, text):
        label = Gtk.Label()
        label.set_markup('<b>%s</b>' % GLib.markup_escape_text(text))
        label.set_xalign(0.0)
        label.set_margin_top(8)

        return label

    def _note(self, text):
        label = Gtk.Label(label=text)
        label.set_xalign(0.0)
        label.set_line_wrap(True)
        # 40, not 56: these sit in a column half the window wide now, and a wrapping label's
        # minimum width is what this sets — too generous a figure here and the window is forced
        # wider than the screen it was just measured against.
        label.set_max_width_chars(40)
        label.set_width_chars(24)
        label.get_style_context().add_class('dim-label')

        return label

    def _spin(self, low, high, value, step):
        spin = Gtk.SpinButton.new_with_range(low, high, step)
        spin.set_value(value)

        return spin

    def _choice(self, options, chosen):
        box = Gtk.ComboBoxText()
        for value, label in options:
            box.append(value, label)
        box.set_active_id(chosen if any(v == chosen for v, _ in options) else options[0][0])

        return box

    def _labelled(self, grid, row, text, widget):
        label = Gtk.Label(label=text)
        label.set_xalign(0.0)
        # Allowed to wrap, so a long label costs a second line in a column with height to spare
        # rather than forcing the whole window wider. 22 is in the font's approximate character
        # width, which is wider than real lowercase text, so it buys about 28 characters — and
        # the longest of these labels, "Check ShulGo every (seconds)", is 28. The one that did
        # wrap on the Pentium III was a 33-character label, and it lost a word rather than this
        # figure being raised: at 30 the number fields would be down to about 98 px, and the
        # refresh one goes to 3600.
        label.set_line_wrap(True)
        label.set_max_width_chars(22)
        grid.attach(label, 0, row, 1, 1)
        widget.set_hexpand(True)
        grid.attach(widget, 1, row, 1, 1)

        return row + 1

    def _place_summary(self):
        place = config.saved_place(self.values)
        if not place:
            return 'No place chosen yet, so there is nothing to look up.'

        return 'Looking around %s (%.4f, %.4f).' % (place[2], place[0], place[1])

    def _on_forget(self, *_):
        """Delete the key, the settings and the cache, then close.

        Asked first, and the question says the two things somebody would not guess: that the key is
        shared with the GNOME extension, so both halves of a Jewbuntu desktop are unlinked, and
        that the account is untouched until they unlink the computer there themselves.

        The address is printed rather than opened. The desktop app opens it, which is right on a
        Mac; this widget exists for a 1 GHz machine with 256 MB of RAM, where launching a browser
        as the program quits is a minute of swapping and a window nobody asked for.
        """
        asking = Gtk.MessageDialog(transient_for=self, modal=True,
                                   message_type=Gtk.MessageType.WARNING,
                                   buttons=Gtk.ButtonsType.NONE,
                                   text='Forget this computer?')
        asking.format_secondary_text(
            'This deletes the key that links this computer, the place you chose and your '
            'settings, and then closes ShulGo. The same key is used by ShulGo in the GNOME '
            'panel, so that is unlinked too.\n\n'
            'Your ShulGo account is not touched. To stop this computer appearing in it, unlink '
            'it at shulgo.com/account/devices.')
        asking.add_button('Cancel', Gtk.ResponseType.CANCEL)
        asking.add_button('Forget', Gtk.ResponseType.OK)
        asking.set_default_response(Gtk.ResponseType.CANCEL)
        answer = asking.run()
        asking.destroy()

        if answer != Gtk.ResponseType.OK:
            return

        config.forget()
        Gtk.main_quit()

    def _on_link(self, *_):
        """Imported here, not at the top: a session that never links never loads the window."""
        from .link_window import LinkWindow

        def done(linked):
            if linked:
                # The key is in the file now; show it so the window is not quietly out of date.
                self.key_entry.set_text(config.load_api_key())
                self._changed = True

        LinkWindow(self.api, done, parent=self)

    # ---- the place lookup ------------------------------------------------------------------

    def _look(self):
        text = self.place_entry.get_text().strip()
        if len(text) < 2 or (self._looking is not None and self._looking.is_alive()):
            return
        self.found_box.remove_all()
        self.found_box.append('', 'Searching…')
        self.found_box.set_active(0)
        self.found_box.show()
        self._looking = threading.Thread(target=self._do_look, args=(text,), daemon=True)
        self._looking.start()

    def _do_look(self, text):
        answer = self.api.places(text)
        GLib.idle_add(self._show_found, answer)

    def _show_found(self, answer):
        self.found_box.remove_all()
        self._found = []
        if not answer.get('ok'):
            self.found_box.append('', answer.get('message') or 'ShulGo couldn’t be reached.')
            self.found_box.set_active(0)

            return False

        rows = answer.get('data') or []
        if not rows:
            self.found_box.append('', 'Nothing found for that.')
            self.found_box.set_active(0)

            return False

        for i, row in enumerate(rows):
            self._found.append(row)
            label = row.get('label') or row.get('name') or 'Somewhere'
            if row.get('shuls'):
                label = '%s — %s shul%s' % (label, row['shuls'],
                                            '' if row['shuls'] == 1 else 's')
            self.found_box.append(str(i), label)
        self.found_box.set_active(0)
        self._on_pick(self.found_box)

        return False

    def _on_pick(self, box):
        chosen = box.get_active_id()
        if chosen in (None, '') or not chosen.isdigit():
            return
        row = self._found[int(chosen)]
        point = row.get('location') or row
        lat, lng = point.get('lat'), point.get('lng')
        if lat is None or lng is None:
            return
        self.values['lat'] = repr(float(lat))
        self.values['lng'] = repr(float(lng))
        self.values['place'] = row.get('label') or row.get('name') or self.place_entry.get_text()
        self.place_note.set_text(self._place_summary())

    # ---- saving ----------------------------------------------------------------------------

    def _save(self, *_):
        self.values['window-minutes'] = str(self.window_spin.get_value_as_int())
        self.values['list-length'] = str(self.length_spin.get_value_as_int())
        self.values['refresh-seconds'] = str(self.refresh_spin.get_value_as_int())
        self.values['travel-mode'] = self.mode_box.get_active_id() or 'drive'
        self.values['tefillah'] = self.tefillah_box.get_active_id() or 'next'
        self.values['show-zmanim'] = 'yes' if self.zmanim_check.get_active() else 'no'
        self.values['show-events'] = 'yes' if self.events_check.get_active() else 'no'
        self.values['show-shiurim'] = 'yes' if self.shiurim_check.get_active() else 'no'
        self.values['panel-line'] = 'yes' if self.bar_check.get_active() else 'no'

        config.save_settings(self.values)
        config.save_api_key(self.key_entry.get_text())
        self._changed = True
        self.destroy()

    def _finish(self, *_):
        callback, self._on_close = self._on_close, None
        if callback is not None:
            callback(self._changed)
