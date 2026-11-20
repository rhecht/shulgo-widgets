# -*- coding: utf-8 -*-
u"""The two windows, on PyGTK 2.12: Settings, and linking this computer.

GTK 2.12 has no Gtk.Grid (3.0), no Gtk.HeaderBar, and gtk.Table is what arranges things. The
wording and all the linking logic live elsewhere — link.py decides what the state means and what to
say about it — so what is here is layout and the handful of callbacks.
"""

from __future__ import division, with_statement

import threading

import gobject
import gtk

from . import config, link
from .fmt import escape_markup

MODES = ((u'drive', u'Driving'), (u'walk', u'Walking'))
TEFILLOS = ((u'next', u'Whatever is next'), (u'shacharis', u'Shacharis'),
            (u'mincha', u'Mincha'), (u'maariv', u'Maariv'))


class _Window(object):
    def __init__(self, tray, title):
        self.tray = tray
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.window.set_title(title)
        self.window.set_border_width(12)
        self.window.set_position(gtk.WIN_POS_CENTER)
        self.window.connect('destroy', self._on_destroy)

    def show(self):
        self.window.show_all()

    def _on_destroy(self, *ignored):
        return False

    def _row(self, table, row, label_text, widget):
        label = gtk.Label(label_text)
        label.set_alignment(0.0, 0.5)
        table.attach(label, 0, 1, row, row + 1, gtk.FILL, 0, 6, 4)
        table.attach(widget, 1, 2, row, row + 1, gtk.EXPAND | gtk.FILL, 0, 6, 4)

        return row + 1

    def _choice(self, options, current):
        box = gtk.combo_box_new_text()
        self._values = getattr(self, '_values', {})
        names = []
        for value, label in options:
            box.append_text(label)
            names.append(value)
        box.set_active(names.index(current) if current in names else 0)
        box.shulgo_values = names

        return box


class SettingsWindow(_Window):
    def __init__(self, tray):
        _Window.__init__(self, tray, u'ShulGo settings')
        self.values = dict(config.load_settings())

        table = gtk.Table(9, 2)
        row = 0

        place = config.saved_place(self.values)
        self.place_entry = gtk.Entry()
        self.place_entry.set_text(place[2] if place else u'')
        row = self._row(table, row, u'Where you daven', self.place_entry)

        self.lookup_note = gtk.Label(u'')
        self.lookup_note.set_alignment(0.0, 0.5)
        lookup = gtk.Button(u'Look it up')
        lookup.connect('clicked', self._on_lookup)
        row = self._row(table, row, u'', lookup)
        row = self._row(table, row, u'', self.lookup_note)

        self.window_entry = gtk.Entry()
        self.window_entry.set_text(u'%s' % self.values.get(u'window-minutes', u'120'))
        row = self._row(table, row, u'Look ahead (minutes)', self.window_entry)

        self.mode_box = self._choice(MODES, self.values.get(u'travel-mode', u'drive'))
        row = self._row(table, row, u'Getting there by', self.mode_box)

        self.tefillah_box = self._choice(TEFILLOS, self.values.get(u'tefillah', u'next'))
        row = self._row(table, row, u'Show', self.tefillah_box)

        self.zmanim_check = gtk.CheckButton(u'Today’s zmanim in the menu')
        self.zmanim_check.set_active(self.values.get(u'show-zmanim') == u'yes')
        table.attach(self.zmanim_check, 0, 2, row, row + 1, gtk.FILL, 0, 6, 4)
        row += 1

        self.bar_check = gtk.CheckButton(u'A line on the top panel, beside the clock')
        self.bar_check.set_active(self.values.get(u'panel-line') == u'yes')
        table.attach(self.bar_check, 0, 2, row, row + 1, gtk.FILL, 0, 6, 4)
        row += 1

        buttons = gtk.HButtonBox()
        buttons.set_layout(gtk.BUTTONBOX_END)
        cancel = gtk.Button(stock=gtk.STOCK_CANCEL)
        cancel.connect('clicked', lambda *a: self.window.destroy())
        save = gtk.Button(stock=gtk.STOCK_SAVE)
        save.connect('clicked', self._on_save)
        buttons.add(cancel)
        buttons.add(save)

        box = gtk.VBox(False, 8)
        box.pack_start(table, False, False, 0)
        box.pack_start(buttons, False, False, 0)
        self.window.add(box)

    def _on_lookup(self, *ignored):
        u"""Ask ShulGo what this place is called and where it is.

        On a worker thread, because a slow answer must not freeze the window — on this hardware a
        frozen window is read as a crash, and people start killing processes.
        """
        text = self.place_entry.get_text()
        if not text.strip():
            return

        self.lookup_note.set_text(u'Looking…')
        thread = threading.Thread(target=self._do_lookup, args=(text,))
        thread.setDaemon(True)
        thread.start()

    def _do_lookup(self, text):
        gobject.idle_add(self._lookup_answer, self.tray.api.places(text))

    def _lookup_answer(self, answer):
        if not answer.get(u'ok') or not answer.get(u'data'):
            self.lookup_note.set_text(answer.get(u'message') or u'Nothing found by that name.')

            return False

        first = answer[u'data'][0]
        self._found = first
        self.place_entry.set_text(first.get(u'label') or first.get(u'name') or u'')
        self.lookup_note.set_text(u'Found it. Save to use this place.')

        return False

    def _on_save(self, *ignored):
        found = getattr(self, '_found', None)
        if found is not None:
            self.values[u'lat'] = u'%s' % found.get(u'lat', u'')
            self.values[u'lng'] = u'%s' % found.get(u'lng', u'')
        self.values[u'place'] = self.place_entry.get_text().strip()
        self.values[u'window-minutes'] = self.window_entry.get_text().strip() or u'120'
        self.values[u'travel-mode'] = \
            self.mode_box.shulgo_values[self.mode_box.get_active()]
        self.values[u'tefillah'] = \
            self.tefillah_box.shulgo_values[self.tefillah_box.get_active()]
        self.values[u'show-zmanim'] = u'yes' if self.zmanim_check.get_active() else u'no'
        self.values[u'panel-line'] = u'yes' if self.bar_check.get_active() else u'no'

        config.save_settings(self.values)
        self.tray.settings = config.load_settings()
        self.tray.refresh(fresh=True)
        self.window.destroy()


class LinkWindow(_Window):
    u"""Linking this computer to a ShulGo account, by the smart-TV method.

    The widget never sees a password. It asks ShulGo for a short code, the person types that code
    into shulgo.com on a machine with a keyboard they trust, an administrator approves it, and the
    key comes back here. Nothing secret is ever typed into this window, which is the point.
    """

    def __init__(self, tray):
        _Window.__init__(self, tray, u'Link this computer')
        self.window.set_default_size(420, -1)

        self.heading = gtk.Label()
        self.heading.set_alignment(0.0, 0.5)
        self.body = gtk.Label()
        self.body.set_alignment(0.0, 0.5)
        self.body.set_line_wrap(True)

        # Selectable, so the code can be copied rather than copied out by hand, and with no caret:
        # a blinking cursor on a label people cannot type into reads as a broken text box.
        self.code = gtk.Label()
        self.code.set_selectable(True)
        self.code.set_alignment(0.0, 0.5)

        close = gtk.Button(stock=gtk.STOCK_CLOSE)
        close.connect('clicked', lambda *a: self.window.destroy())
        buttons = gtk.HButtonBox()
        buttons.set_layout(gtk.BUTTONBOX_END)
        buttons.add(close)

        box = gtk.VBox(False, 10)
        for widget in (self.heading, self.code, self.body, buttons):
            box.pack_start(widget, False, False, 0)
        self.window.add(box)

        self._say(u'<b>Starting…</b>', u'')
        self._start()

    def _say(self, heading, body, code=u''):
        self.heading.set_markup(heading)
        self.body.set_markup(body)
        self.code.set_markup(code)
        self.code.set_property('visible', bool(code))

    def _start(self):
        thread = threading.Thread(target=self._do_start)
        thread.setDaemon(True)
        thread.start()

    def _do_start(self):
        gobject.idle_add(self._started, self.tray.api.device_start(u'ShulGo for GNOME 2'))

    def _started(self, answer):
        if not answer.get(u'ok'):
            # Offline is its own message, and it comes first: told "ask your administrator" while
            # the machine has no internet, somebody will go and ask, and wait for nothing.
            self._say(u'<b>Can’t reach ShulGo</b>',
                      escape_markup(answer.get(u'message') or link.OFFLINE))

            return False

        self.tray._pending = link.Linking(answer.get(u'data') or {})
        pending = self.tray._pending
        config.save_pending(pending.device_code, pending.user_code,
                            pending.expires_at, pending.interval)
        self._show_pending()
        self.tray._poll_pending()

        return False

    def _show_pending(self):
        pending = self.tray._pending
        if pending is None:
            return

        # The code comes before the sentence that tells you where to type it, because the code is
        # what the eye goes to and the sentence is meaningless without it.
        self._say(
            u'<b>Type this code at %s</b>' % escape_markup(pending.verification_uri),
            escape_markup(link.words(link.PENDING, pending)),
            u'<span size="xx-large" weight="bold">%s</span>' % escape_markup(pending.user_code))
