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
from gi.repository import GLib, Gtk  # noqa: E402

from . import config  # noqa: E402

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
        self.set_default_size(460, -1)
        self.set_border_width(12)
        self.connect('destroy', self._finish)

        grid = Gtk.Grid(row_spacing=8, column_spacing=10)
        self.add(grid)
        row = 0

        # ---- the key
        grid.attach(self._heading('Your ShulGo API key'), 0, row, 2, 1)
        row += 1
        self.key_entry = Gtk.Entry()
        self.key_entry.set_text(config.load_api_key())
        self.key_entry.set_visibility(False)
        self.key_entry.set_placeholder_text('sg_live_…')
        self.key_entry.set_hexpand(True)
        grid.attach(self.key_entry, 0, row, 2, 1)
        row += 1
        grid.attach(self._note('Make one in ShulGo under Admin › System › API & apps. It is kept in '
                               '~/.config/jewbuntu/shulgo.conf, readable only by you — never in '
                               'dconf.'), 0, row, 2, 1)
        row += 1

        # ---- where
        grid.attach(self._heading('Where you daven'), 0, row, 2, 1)
        row += 1
        self.place_entry = Gtk.Entry()
        self.place_entry.set_placeholder_text('A city, neighbourhood or zip code')
        self.place_entry.set_text(self.values.get('place', ''))
        self.place_entry.set_hexpand(True)
        self.place_entry.connect('activate', lambda *_: self._look())
        grid.attach(self.place_entry, 0, row, 1, 1)
        look = Gtk.Button(label='Search')
        look.connect('clicked', lambda *_: self._look())
        grid.attach(look, 1, row, 1, 1)
        row += 1
        self.found_box = Gtk.ComboBoxText()
        self.found_box.set_hexpand(True)
        self.found_box.connect('changed', self._on_pick)
        grid.attach(self.found_box, 0, row, 2, 1)
        row += 1
        self.place_note = self._note(self._place_summary())
        grid.attach(self.place_note, 0, row, 2, 1)
        row += 1

        # ---- the rest
        grid.attach(self._heading('What to show'), 0, row, 2, 1)
        row += 1
        self.window_spin = self._spin(15, 360, config.as_int(self.values, 'window-minutes'), 15)
        row = self._labelled(grid, row, 'Look ahead (minutes)', self.window_spin)
        self.length_spin = self._spin(1, 12, config.as_int(self.values, 'list-length'), 1)
        row = self._labelled(grid, row, 'Minyanim in the menu (next start)', self.length_spin)
        self.refresh_spin = self._spin(60, 3600, config.as_int(self.values, 'refresh-seconds'), 60)
        row = self._labelled(grid, row, 'Check ShulGo every (seconds)', self.refresh_spin)

        self.mode_box = self._choice(MODES, self.values.get('travel-mode', 'drive'))
        row = self._labelled(grid, row, 'Getting there by', self.mode_box)
        self.tefillah_box = self._choice(TEFILLOS, self.values.get('tefillah', 'next'))
        row = self._labelled(grid, row, 'Show', self.tefillah_box)

        self.zmanim_check = Gtk.CheckButton(label='Today’s zmanim in the menu')
        self.zmanim_check.set_active(self.values.get('show-zmanim') == 'yes')
        grid.attach(self.zmanim_check, 0, row, 2, 1)
        row += 1

        self.events_check = Gtk.CheckButton(label='Upcoming events near you')
        self.events_check.set_active(self.values.get('show-events') == 'yes')
        grid.attach(self.events_check, 0, row, 2, 1)
        row += 1

        self.shiurim_check = Gtk.CheckButton(label='Shiurim near you')
        self.shiurim_check.set_active(self.values.get('show-shiurim') == 'yes')
        grid.attach(self.shiurim_check, 0, row, 2, 1)
        row += 1

        grid.attach(self._note('Countdowns are worked out on this machine, so ShulGo is only asked '
                               'on the timer above. Each list you switch off is one request fewer '
                               'each time it does.'), 0, row, 2, 1)
        row += 1

        buttons = Gtk.Box(spacing=8)
        buttons.set_halign(Gtk.Align.END)
        close = Gtk.Button(label='Close')
        close.connect('clicked', lambda *_: self.destroy())
        save = Gtk.Button(label='Save')
        save.get_style_context().add_class('suggested-action')
        save.connect('clicked', self._save)
        buttons.add(close)
        buttons.add(save)
        grid.attach(buttons, 0, row, 2, 1)

        self.show_all()

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
        label.set_max_width_chars(56)
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
        grid.attach(label, 0, row, 1, 1)
        widget.set_hexpand(True)
        grid.attach(widget, 1, row, 1, 1)

        return row + 1

    def _place_summary(self):
        place = config.saved_place(self.values)
        if not place:
            return 'No place chosen yet, so there is nothing to look up.'

        return 'Looking around %s (%.4f, %.4f).' % (place[2], place[0], place[1])

    # ---- the place lookup ------------------------------------------------------------------

    def _look(self):
        text = self.place_entry.get_text().strip()
        if len(text) < 2 or (self._looking is not None and self._looking.is_alive()):
            return
        self.found_box.remove_all()
        self.found_box.append('', 'Searching…')
        self.found_box.set_active(0)
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

        config.save_settings(self.values)
        config.save_api_key(self.key_entry.get_text())
        self._changed = True
        self.destroy()

    def _finish(self, *_):
        callback, self._on_close = self._on_close, None
        if callback is not None:
            callback(self._changed)
