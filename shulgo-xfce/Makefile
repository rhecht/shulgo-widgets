# ShulGo for Xfce — install into a staging root for a package to pick up.
#
#   make install DESTDIR=/tmp/stage PREFIX=/usr
#   make uninstall PREFIX=/usr          (as root, on a machine where it was installed by hand)
#
# The same layout the PKGBUILD installs, in the one place, so the Arch package and the .deb and the
# .rpm cannot drift apart. There is no build step: nothing here is compiled, which is the whole
# reason this widget exists rather than the Electron one. That is also why one package serves i686,
# x86_64 and arm64 alike — and why 32-bit Linux has this and not the desktop app, which Electron
# has not built for ia32 since version 4.

PREFIX  ?= /usr
DESTDIR ?=
PYTHON  ?= python3

LIBDIR  = $(DESTDIR)$(PREFIX)/lib/shulgo-xfce
BINDIR  = $(DESTDIR)$(PREFIX)/bin
APPDIR  = $(DESTDIR)$(PREFIX)/share/applications
ICONDIR = $(DESTDIR)$(PREFIX)/share/icons/hicolor
DOCDIR  = $(DESTDIR)$(PREFIX)/share/doc/shulgo-xfce
# /etc, not $(PREFIX)/etc: autostart is read from /etc/xdg wherever the program itself lives.
AUTODIR = $(DESTDIR)/etc/xdg/autostart

all:
	@echo "Nothing to build. Run: make install DESTDIR=... PREFIX=/usr"

install:
	# Its own directory rather than site-packages: nothing to collide with, and a Python upgrade
	# does not strand it. bin/shulgo-xfce is the only thing that knows the path.
	install -d $(LIBDIR)/shulgo_xfce
	install -m 644 shulgo_xfce/*.py $(LIBDIR)/shulgo_xfce/

	install -d $(BINDIR)
	install -m 755 bin/shulgo-xfce $(BINDIR)/shulgo-xfce
	# What Generic Monitor runs for the line beside the clock: a shell script that cats one file,
	# because nothing should start an interpreter every fifteen seconds on a Pentium III.
	install -m 755 bin/shulgo-bar $(BINDIR)/shulgo-bar

	install -d $(APPDIR)
	install -m 644 packaging/shulgo-xfce.desktop $(APPDIR)/shulgo-xfce.desktop

	# Starts at login. The menu entry above will not, however it is marked — only a file in an
	# autostart directory starts anything — and it stays visible in Session and Startup so it can
	# be unticked by anyone who would rather launch it themselves.
	install -d $(AUTODIR)
	install -m 644 packaging/shulgo-xfce-autostart.desktop $(AUTODIR)/shulgo-xfce.desktop

	install -d $(ICONDIR)/scalable/apps
	install -m 644 packaging/shulgo.svg $(ICONDIR)/scalable/apps/shulgo.svg

	install -d $(DOCDIR)
	install -m 644 README.md $(DOCDIR)/README.md

check:
	TZ=America/Toronto $(PYTHON) -m unittest discover -s tests

# Only what install put there. The settings and the saved key live under the person's own home
# directory, which is not root's to delete on their behalf and not something a package manager
# should touch: on a shared machine one `apt remove` would unlink everybody.
#
# That does leave the same gap the Electron widget had until today — removing the program leaves
# the key behind, still listed as a live device on the person's ShulGo account. The desktop app now
# answers that with "Remove ShulGo from this computer" in its own Settings; this widget has no such
# thing yet, and should. Noted in docs/TODO.md rather than left to be rediscovered.
uninstall:
	rm -rf $(LIBDIR) $(DOCDIR)
	rm -f $(BINDIR)/shulgo-xfce $(BINDIR)/shulgo-bar
	rm -f $(APPDIR)/shulgo-xfce.desktop $(AUTODIR)/shulgo-xfce.desktop
	rm -f $(ICONDIR)/scalable/apps/shulgo.svg

.PHONY: all install check uninstall
