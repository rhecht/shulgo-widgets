# ShulGo for GNOME 2 — install into a staging root for the .deb to pick up.
#
#   make install DESTDIR=debian/shulgo-gtk2 PREFIX=/usr
#
# No build step: there is nothing compiled here, which is the whole reason this exists rather than
# anything newer. Plain POSIX make and install, because the ISO pipeline is as old as the target.

PREFIX  ?= /usr
DESTDIR ?=
PYTHON  ?= python

LIBDIR   = $(DESTDIR)$(PREFIX)/lib/shulgo-gtk2
BINDIR   = $(DESTDIR)$(PREFIX)/bin
APPDIR   = $(DESTDIR)$(PREFIX)/share/applications
ICONDIR  = $(DESTDIR)$(PREFIX)/share/icons/hicolor
DOCDIR   = $(DESTDIR)$(PREFIX)/share/doc/shulgo-gtk2
# /etc, not $(PREFIX)/etc: autostart is read from /etc/xdg regardless of where the program lives.
AUTODIR  = $(DESTDIR)/etc/xdg/autostart

all:
	@echo "Nothing to build. Run: make install DESTDIR=... PREFIX=/usr"

install:
	install -d $(LIBDIR)/shulgo_gtk2
	install -m 644 shulgo_gtk2/*.py $(LIBDIR)/shulgo_gtk2/

	install -d $(BINDIR)
	install -m 755 bin/shulgo-gtk2 $(BINDIR)/shulgo-gtk2

	install -d $(APPDIR)
	install -m 644 packaging/shulgo-gtk2.desktop $(APPDIR)/shulgo-gtk2.desktop

	# Starts at login. The menu entry above will not do that however it is marked: only a file in
	# an autostart directory starts anything. Left visible so it can be switched off in Sessions.
	install -d $(AUTODIR)
	install -m 644 packaging/shulgo-gtk2-autostart.desktop $(AUTODIR)/shulgo-gtk2.desktop

	# PNG as well as SVG, deliberately: a 2007 install is not guaranteed to have the librsvg
	# pixbuf loader, and a tray icon that fails to load is not an error anyone sees - it is simply
	# an empty space where the widget should be.
	install -d $(ICONDIR)/scalable/apps $(ICONDIR)/22x22/apps $(ICONDIR)/24x24/apps $(ICONDIR)/48x48/apps
	install -m 644 packaging/shulgo.svg     $(ICONDIR)/scalable/apps/shulgo.svg
	install -m 644 packaging/shulgo-22.png  $(ICONDIR)/22x22/apps/shulgo.png
	install -m 644 packaging/shulgo-24.png  $(ICONDIR)/24x24/apps/shulgo.png
	install -m 644 packaging/shulgo-48.png  $(ICONDIR)/48x48/apps/shulgo.png

	install -d $(DOCDIR)
	install -m 644 README.md $(DOCDIR)/README.md

# Every test file, not one of them. `make check` used to run tests/test_fmt.py alone, which is how
# this package shipped with the panel-line module untested and crashed on a live CD. unittest
# discovery is 2.7, so the files are looped over by hand.
check:
	@for t in tests/test_*.py; do \
		[ "$$t" = "tests/test_tray.py" ] && continue; \
		echo "--- $$t"; \
		TZ=America/Toronto $(PYTHON) "$$t" || exit 1; \
	done

# The tray itself, which needs an X server and so cannot be part of `check`. Both startup crashes
# on the live CD were in Tray.__init__ and `check` could not reach it. Xvfb is in gutsy main.
check-display:
	@command -v Xvfb >/dev/null || { echo "Xvfb not installed: apt-get install xvfb"; exit 1; }
	@Xvfb :77 -screen 0 1024x768x16 >/dev/null 2>&1 & \
	sleep 2; \
	DISPLAY=:77 TZ=America/Toronto $(PYTHON) tests/test_tray.py; \
	status=$$?; \
	kill %1 2>/dev/null; \
	exit $$status

uninstall:
	rm -rf $(LIBDIR) $(DOCDIR)
	rm -f $(BINDIR)/shulgo-gtk2 $(APPDIR)/shulgo-gtk2.desktop $(AUTODIR)/shulgo-gtk2.desktop
	rm -f $(ICONDIR)/scalable/apps/shulgo.svg $(ICONDIR)/22x22/apps/shulgo.png \
	      $(ICONDIR)/24x24/apps/shulgo.png $(ICONDIR)/48x48/apps/shulgo.png

.PHONY: all install check check-display uninstall
