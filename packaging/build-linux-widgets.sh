#!/bin/sh
# Build installable packages for the two Python widgets — the ones 32-bit Linux has to use.
#
#   sh integrations/packaging/build-linux-widgets.sh [output-dir]
#
# Why these exist as packages at all. Electron has shipped no 32-bit Linux build since version 4:
# its releases carry linux-x64, linux-arm64 and linux-armv7l and nothing else. So on an i686 machine
# the desktop widget is not "difficult", it is impossible, and shulgo-xfce (Python 3 + GTK 3) and
# shulgo-gtk2 (Python 2.5 + PyGTK, for a 2007 desktop) are what runs there. Until now neither had
# anything a person could download and open: xfce had a PKGBUILD, which is Arch only, and gtk2 had a
# Makefile and nothing else.
#
# Both are pure Python with nothing compiled, so each package is architecture-independent — one file
# serves i686, x86_64 and arm64 alike, which is the whole reason this works for the old machines.
# Installing and removing is then the system's own job: apt, dnf, zypper or the software centre,
# with nothing for anybody to follow.
#
# Needs fpm (gem install fpm), and rpmbuild for the .rpm.

set -eu

here=$(cd "$(dirname "$0")/.." && pwd)
out=${1:-$here/dist-linux-widgets}
mkdir -p "$out"

say() { printf '\n== %s\n' "$1"; }

# The version the program itself reports, rather than one written down twice and left to disagree
# with it.
version_of() {
    [ -f "$1" ] || { echo ""; return 0; }
    # u'...' as well as '...': the GNOME 2 widget is Python 2 and writes its version as a unicode
    # literal. u* rather than u\? because BSD sed and GNU sed disagree about \? and this script
    # runs on both.
    sed -n "s/^VERSION = u*'\\([^']*\\)'.*/\\1/p" "$1" | head -1
}

command -v fpm >/dev/null 2>&1 || { echo "fpm is not installed: gem install fpm" >&2; exit 1; }

MAINTAINER='ShulGo <info@shulgo.com>'
URL='https://shulgo.com'

# ---- ShulGo for Xfce: Python 3, GTK 3 ----------------------------------------------------------
# Debian and Fedora name the same four libraries differently, which is the only reason there are
# two dependency lists below rather than one.

xfce_version=$(version_of "$here/shulgo-xfce/shulgo_xfce/__main__.py")
[ -n "$xfce_version" ] || { echo "could not read shulgo-xfce's version" >&2; exit 1; }
say "shulgo-xfce $xfce_version"

stage=$(mktemp -d)
make -C "$here/shulgo-xfce" install DESTDIR="$stage" PREFIX=/usr

XFCE_DESC="The next minyan near you in the tray, with upcoming events, mikvaos and today's zmanim, from ShulGo."

fpm -s dir -t deb \
    --name shulgo-xfce --version "$xfce_version" --architecture all \
    --maintainer "$MAINTAINER" --url "$URL" --description "$XFCE_DESC" --category utils \
    --depends python3 --depends python3-gi --depends gir1.2-gtk-3.0 \
    --depends gir1.2-ayatanaappindicator3-0.1 \
    --deb-recommends xfce4-genmon-plugin \
    --deb-recommends gir1.2-dbusmenu-gtk3-0.4 \
    --chdir "$stage" \
    --package "$out/shulgo-xfce_${xfce_version}_all.deb" .

fpm -s dir -t rpm \
    --name shulgo-xfce --version "$xfce_version" --architecture noarch \
    --maintainer "$MAINTAINER" --url "$URL" --description "$XFCE_DESC" --category utils \
    --depends python3 --depends python3-gobject --depends gtk3 \
    --depends libayatana-appindicator-gtk3 \
    --chdir "$stage" \
    --package "$out/shulgo-xfce-${xfce_version}.noarch.rpm" .

rm -rf "$stage"

# ---- ShulGo for GNOME 2: Python 2.5, PyGTK 2.12 ------------------------------------------------
# For Jewbuntu Classic and anything else of that age. A .deb only: these machines run Ubuntu 7.10,
# and there is no 2007 RPM distribution anybody is still installing onto.

gtk2_version=$(version_of "$here/shulgo-gtk2/shulgo_gtk2/main.py")
[ -n "$gtk2_version" ] || { echo "could not read shulgo-gtk2's version" >&2; exit 1; }
say "shulgo-gtk2 $gtk2_version"

stage=$(mktemp -d)
make -C "$here/shulgo-gtk2" install DESTDIR="$stage" PREFIX=/usr

# gzip, not xz. dpkg learned to read xz-compressed packages around 2010; the desktop this is for is
# from 2007 and would refuse the package outright with today's default. Shipping a .deb it cannot
# open would defeat the only reason for building one.
fpm -s dir -t deb \
    --name shulgo-gtk2 --version "$gtk2_version" --architecture all \
    --maintainer "$MAINTAINER" --url "$URL" --category utils \
    --description "The next minyan near you, in the notification area of an older desktop." \
    --depends python --depends python-gtk2 \
    --deb-compression gz \
    --chdir "$stage" \
    --package "$out/shulgo-gtk2_${gtk2_version}_all.deb" .

rm -rf "$stage"

say "built into $out"
ls -lh "$out"
