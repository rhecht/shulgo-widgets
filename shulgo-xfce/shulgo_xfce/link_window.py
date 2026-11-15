"""The "Link this computer" window — imported only when somebody opens it.

Shows the short code ShulGo gave us, large enough to read from where the phone is, and keeps asking
whether anybody has approved it. When they have, the key lands in the usual file and the window
closes.

What each answer means is in link.py, which has no GTK in it and is tested. This file is the window
and the clock, and nothing else: it decides when to ask, never what the answer meant.
"""

import socket
import threading

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import GLib, Gio, Gtk, Pango  # noqa: E402

from . import config, link  # noqa: E402


class LinkWindow(Gtk.Window):
    def __init__(self, api, on_done, parent=None):
        super().__init__(title='Link this computer')
        self.api = api
        self._on_done = on_done
        self.linking = None
        self._timer = None
        self._working = False

        self.set_default_size(420, -1)
        self.set_border_width(16)
        self.set_modal(bool(parent))
        if parent:
            self.set_transient_for(parent)
        self.connect('destroy', self._finish)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(box)

        heading = Gtk.Label()
        heading.set_markup('<b>Link this computer to your ShulGo account</b>')
        heading.set_xalign(0.0)
        box.add(heading)

        self.steps = Gtk.Label(label='Asking ShulGo for a code…')
        self.steps.set_xalign(0.0)
        self.steps.set_line_wrap(True)
        self.steps.set_max_width_chars(46)
        box.add(self.steps)

        # Order matters here and I got it wrong first time: the code went into the box BEFORE the
        # line introducing it, so the window read "…open" / CODE / "https://… and type this code:",
        # with the sentence cut in half by the thing it was describing. Found by somebody reading it
        # on the screen it was built for; no test here could have seen it.
        self.where = Gtk.Label()
        self.where.set_xalign(0.0)
        self.where.set_line_wrap(True)
        self.where.set_selectable(True)
        box.add(self.where)

        # The code itself, big. This is read from across a room and typed on a phone, which is the
        # whole reason the alphabet has no O, 0, I or 1 in it.
        self.code = Gtk.Label(label='')
        self.code.set_selectable(True)
        # Selectable so it can be copied, but not focusable: with focus it draws a text caret at the
        # left edge and looks like a box you are meant to type into, which is the opposite of true.
        self.code.set_can_focus(False)
        self.code.override_font(Pango.FontDescription('Monospace Bold 26'))
        box.add(self.code)

        self.status = Gtk.Label(label='')
        self.status.set_xalign(0.0)
        self.status.set_line_wrap(True)
        self.status.set_max_width_chars(46)
        self.status.get_style_context().add_class('dim-label')
        box.add(self.status)

        buttons = Gtk.Box(spacing=8)
        buttons.set_halign(Gtk.Align.END)
        self.again = Gtk.Button(label='Start again')
        self.again.connect('clicked', lambda *_: self.begin())
        self.again.set_sensitive(False)
        close = Gtk.Button(label='Close')
        close.connect('clicked', lambda *_: self.destroy())
        buttons.add(self.again)
        buttons.add(close)
        box.add(buttons)

        self.show_all()
        self.begin()

    # ---- asking -----------------------------------------------------------------------------

    def begin(self):
        if self._working:
            return

        # Before anything else. A machine with no network would otherwise sit on "Asking ShulGo for
        # a code…" for fifteen seconds and then blame ShulGo, which is both slow and untrue.
        if not self._connected():
            self.steps.set_text('No internet connection')
            self.status.set_text(link.OFFLINE)
            self.code.set_text('')
            self.where.set_text('')
            self.again.set_sensitive(True)

            return

        self._working = True
        self.again.set_sensitive(False)
        self.code.set_text('')
        self.steps.set_text('Asking ShulGo for a code…')
        self.status.set_text('')
        self._stop_timer()

        threading.Thread(target=self._do_start, daemon=True).start()

    @staticmethod
    def _connected():
        """What the machine says about its own network.

        Taken as true when the question cannot be asked at all: a widget that refuses to try because
        it could not find a network monitor is worse than one that tries and fails honestly.
        """
        try:
            return Gio.NetworkMonitor.get_default().get_network_available()
        except Exception:
            return True

    def _do_start(self):
        """Off the main loop. The machine's own name travels so the account page can tell laptops
        apart; nothing else about it does."""
        answer = self.api.device_start('ShulGo for Xfce', socket.gethostname())
        GLib.idle_add(self._started, answer)

    def _started(self, answer):
        self._working = False

        if not answer.get('ok'):
            self.steps.set_text('ShulGo could not be reached.')
            self.status.set_text(answer.get('message') or '')
            self.again.set_sensitive(True)

            return False

        self.linking = link.Linking(answer.get('data') or {})
        if self.linking.usable:
            # Written down before anything else, so closing this window — or losing the power — does
            # not throw away an approval somebody is about to give. The tray picks it up from here.
            config.save_pending(self.linking.device_code, self.linking.user_code,
                                self.linking.expires_at, self.linking.interval)
        if not self.linking.usable:
            self.steps.set_text('ShulGo sent an answer this widget could not use.')
            self.again.set_sensitive(True)

            return False

        self.steps.set_text('On your phone or another computer, open')
        self.where.set_markup('<b>%s</b>\n\nand type this code:'
                              % GLib.markup_escape_text(self.linking.verification_uri))
        self.code.set_text(self.linking.user_code)
        # Reads, top to bottom: "…open" / the address / "and type this code:" / the code.
        self.status.set_text(link.words(link.PENDING, self.linking))
        self._arm()

        return False

    def _arm(self):
        self._stop_timer()
        self._timer = GLib.timeout_add_seconds(max(1, self.linking.interval), self._tick)

    def _stop_timer(self):
        if self._timer is not None:
            GLib.source_remove(self._timer)
            self._timer = None

    def _tick(self):
        self._timer = None
        if self.linking is None:
            return False

        if self.linking.expired():
            self._settle(link.EXPIRED)

            return False

        if not self._working:
            self._working = True
            threading.Thread(target=self._do_poll, args=(self.linking.device_code,),
                             daemon=True).start()

        return False

    def _do_poll(self, device_code):
        answer = self.api.device_poll(device_code)
        GLib.idle_add(self._polled, answer)

    def _polled(self, answer):
        self._working = False
        if self.linking is None:
            return False

        state = self.linking.absorb(answer)
        if state == link.PENDING:
            self.status.set_text(link.words(state, self.linking))
            self._arm()

            return False

        self._settle(state)

        return False

    # ---- endings ----------------------------------------------------------------------------

    def _settle(self, state):
        self._stop_timer()
        self.status.set_text(link.words(state, self.linking))

        if state != link.DONE:
            # Denied, expired or broken: there is nothing left for the tray to wait on either.
            config.clear_pending()
            self.code.set_text('')
            self.again.set_sensitive(True)

            return

        # The key goes exactly where a typed one goes: the same file, the same permissions. Nothing
        # about having arrived over the wire makes it different.
        config.save_api_key(self.linking.key)
        config.clear_pending()
        self.steps.set_text('Done.')
        self.where.set_text('')
        self.code.set_text('')
        callback, self._on_done = self._on_done, None
        if callback is not None:
            callback(True)
        GLib.timeout_add_seconds(2, lambda: (self.destroy(), False)[1])

    def _finish(self, *_):
        """Closing this window stops THIS window polling, and nothing else.

        It used to abandon the linking outright, which made a liar of the sentence above it — "you
        can close this; it keeps working for three days" — and, because the key is only minted on
        the first poll after approval, wasted both the person's approval and an administrator's. The
        tray carries on from the file config.save_pending wrote.
        """
        self._stop_timer()
        linked = self.linking is not None and self.linking.key is not None
        self.linking = None
        callback, self._on_done = self._on_done, None
        if callback is not None:
            callback(linked)
