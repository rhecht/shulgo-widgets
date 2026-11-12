#!/usr/bin/env bash
# Installs the JewBuntu ShulGo widget for the user who runs it — no root, nothing outside $HOME.
#
#   ./install.sh                 both halves: the top-bar widget and the ShulGo app
#   ./install.sh --extension     the top-bar widget only
#   ./install.sh --app           the ShulGo app only
#   ./install.sh --dev           compiles the schema into schemas/build for running from this checkout
#   ./install.sh --uninstall     takes it all out again (your API key and settings stay)
#
# After installing the widget, log out and back in on Xorg, or just enable it on Wayland:
#   gnome-extensions enable jewbuntu@shulgo.com

set -euo pipefail

UUID="jewbuntu@shulgo.com"
SCHEMA_ID="com.shulgo.ShulGo"
# Shipped alongside, for one release only, so settings saved under the old org.jewbuntu.shulgo name
# can be read once and brought across. See schemas/org.jewbuntu.shulgo.gschema.xml.
OLD_SCHEMA_ID="org.jewbuntu.shulgo"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORE="$(cd "${HERE}/../shulgo-core" && pwd)"

EXT_DIR="${HOME}/.local/share/gnome-shell/extensions/${UUID}"
APP_DIR="${HOME}/.local/share/jewbuntu-shulgo"
BIN_DIR="${HOME}/.local/bin"
SCHEMA_DIR="${HOME}/.local/share/glib-2.0/schemas"
DESKTOP_DIR="${HOME}/.local/share/applications"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
SYMBOLIC_DIR="${HOME}/.local/share/icons/hicolor/symbolic/apps"

say() { printf '  %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# What to type to install something, in the words of the package manager this machine actually has.
# ShulGo's GNOME half is plain GJS with no compiled part, so it runs wherever GNOME does: Ubuntu,
# Fedora Asahi Remix on an M-series Mac, Arch. On most of those "sudo apt install" is wrong advice,
# and wrong advice in an error message is worse than none.
install_hint() {
  local deb="$1" rpm="$2" arch="$3"
  if command -v apt-get >/dev/null 2>&1; then printf 'sudo apt install %s' "${deb}"
  elif command -v dnf >/dev/null 2>&1; then printf 'sudo dnf install %s' "${rpm}"
  elif command -v pacman >/dev/null 2>&1; then printf 'sudo pacman -S %s' "${arch}"
  elif command -v zypper >/dev/null 2>&1; then printf 'sudo zypper install %s' "${rpm}"
  else printf "it is in your distribution's %s package" "${deb}"
  fi
}

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "ShulGo: $1 is needed but isn't installed ($2)." >&2; exit 1; }
}

copy_shared() {
  # One copy of the shared code per half, so each can be moved or packaged on its own.
  # core/ comes from integrations/shulgo-core — the same files the macOS build uses.
  local target="$1"
  rm -rf "${target}/shulgo"
  mkdir -p "${target}/shulgo/core"
  cp "${CORE}"/*.js "${target}/shulgo/core/"
  cp -R "${HERE}/src/shulgo/gnome" "${target}/shulgo/"
}

install_schema() {
  step "Settings schema"
  mkdir -p "${SCHEMA_DIR}"
  cp "${HERE}/schemas/${SCHEMA_ID}.gschema.xml" "${SCHEMA_DIR}/"
  cp "${HERE}/schemas/${OLD_SCHEMA_ID}.gschema.xml" "${SCHEMA_DIR}/"
  glib-compile-schemas "${SCHEMA_DIR}"
  say "installed in ${SCHEMA_DIR}"
}

install_extension() {
  step "Top-bar widget"
  mkdir -p "${EXT_DIR}"
  cp "${HERE}/extension/${UUID}/metadata.json" "${EXT_DIR}/"
  cp "${HERE}/extension/${UUID}/extension.js" "${EXT_DIR}/"
  cp "${HERE}/extension/${UUID}/prefs.js" "${EXT_DIR}/"
  cp "${HERE}/extension/${UUID}/stylesheet.css" "${EXT_DIR}/"
  mkdir -p "${EXT_DIR}/icons"
  cp "${HERE}/extension/${UUID}/icons/"*.svg "${EXT_DIR}/icons/"
  copy_shared "${EXT_DIR}"

  # A Shell extension reads its own schema directory, so it gets its own compiled copy.
  mkdir -p "${EXT_DIR}/schemas"
  cp "${HERE}/schemas/${SCHEMA_ID}.gschema.xml" "${EXT_DIR}/schemas/"
  cp "${HERE}/schemas/${OLD_SCHEMA_ID}.gschema.xml" "${EXT_DIR}/schemas/"
  glib-compile-schemas "${EXT_DIR}/schemas"
  say "installed in ${EXT_DIR}"
}

# An icon directory is only a theme if it has an index.theme. ~/.local/share/icons/hicolor usually has
# none, because nothing has ever had reason to make one there.
#
# The trap: gtk-update-icon-cache -t ("ignore the theme index") will happily write an icon-theme.cache
# into such a directory, and GTK then reads that cache in place of scanning — so an icon that is sitting
# right there is never found. Which is a blank square in the app grid.
#
# So: write the index.theme first, THEN build the cache. Both are standard, and the index is the same
# one every distribution ships — it only lists which directories hold what.
refresh_icons() {
  local theme="${HOME}/.local/share/icons/hicolor"
  [ -d "${theme}" ] || return 0

  if [ ! -f "${theme}/index.theme" ]; then
    cat > "${theme}/index.theme" <<'INDEX'
[Icon Theme]
Name=Hicolor
Comment=Fallback icon theme
Hidden=true
Directories=scalable/apps,symbolic/apps

[scalable/apps]
Context=Applications
Size=128
MinSize=16
MaxSize=512
Type=Scalable

[symbolic/apps]
Context=Applications
Size=16
MinSize=16
MaxSize=512
Type=Scalable
INDEX
  fi

  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -f "${theme}" 2>/dev/null || true
}

install_app() {
  step "ShulGo app"
  mkdir -p "${APP_DIR}" "${BIN_DIR}" "${DESKTOP_DIR}" "${ICON_DIR}" "${SYMBOLIC_DIR}"
  cp "${HERE}/app/main.js" "${HERE}/app/style.css" "${APP_DIR}/"
  copy_shared "${APP_DIR}"

  cat > "${BIN_DIR}/shulgo" <<LAUNCHER
#!/bin/sh
# ShulGo for JewBuntu
exec gjs -m "${APP_DIR}/main.js" "\$@"
LAUNCHER
  chmod +x "${BIN_DIR}/shulgo"

  cp "${HERE}/app/com.shulgo.ShulGo.svg" "${ICON_DIR}/"
  cp "${HERE}/extension/${UUID}/icons/shulgo-symbolic.svg" "${SYMBOLIC_DIR}/com.shulgo.ShulGo-symbolic.svg"

  # The launcher has to be on PATH for the .desktop file's Exec to work.
  sed "s|^Exec=shulgo$|Exec=${BIN_DIR}/shulgo|" "${HERE}/app/com.shulgo.ShulGo.desktop" \
    > "${DESKTOP_DIR}/com.shulgo.ShulGo.desktop"

  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "${DESKTOP_DIR}" || true
  refresh_icons

  say "installed in ${APP_DIR}"
  say "launcher: ${BIN_DIR}/shulgo"
  case ":${PATH}:" in
    *":${BIN_DIR}:"*) ;;
    *) say "note: ${BIN_DIR} isn't on your PATH — the app grid will still find it." ;;
  esac
}

dev_schema() {
  step "Schema for running from this checkout"
  mkdir -p "${HERE}/schemas/build"
  cp "${HERE}/schemas/${SCHEMA_ID}.gschema.xml" "${HERE}/schemas/build/"
  cp "${HERE}/schemas/${OLD_SCHEMA_ID}.gschema.xml" "${HERE}/schemas/build/"
  glib-compile-schemas "${HERE}/schemas/build"
  mkdir -p "${HERE}/app/shulgo"
  ln -sfn "${CORE}" "${HERE}/app/shulgo/core"
  ln -sfn "${HERE}/src/shulgo/gnome" "${HERE}/app/shulgo/gnome"
  say "linked the shared code into app/shulgo/"
  say "run the app with:"
  say "  SHULGO_SCHEMA_DIR=${HERE}/schemas/build gjs -m ${HERE}/app/main.js"
}

uninstall() {
  step "Removing"
  rm -rf "${EXT_DIR}" "${APP_DIR}"
  rm -f "${BIN_DIR}/shulgo" "${DESKTOP_DIR}/com.shulgo.ShulGo.desktop"
  rm -f "${ICON_DIR}/com.shulgo.ShulGo.svg" "${SYMBOLIC_DIR}/com.shulgo.ShulGo-symbolic.svg"
  # If ours were the only icons there, take the theme we made with them. Leaving the cache behind is
  # worse than leaving nothing: it still lists an icon whose file has gone, and GTK trusts the per-user
  # hicolor cache ahead of /usr/share — so a system-wide ShulGo installed afterwards draws a blank tile.
  if [ -d "${HOME}/.local/share/icons/hicolor" ] \
     && [ -z "$(find "${HOME}/.local/share/icons/hicolor" \( -name '*.svg' -o -name '*.png' \) -print 2>/dev/null)" ]; then
    rm -f "${HOME}/.local/share/icons/hicolor/index.theme" "${HOME}/.local/share/icons/hicolor/icon-theme.cache"
  else
    refresh_icons
  fi
  rm -f "${SCHEMA_DIR}/${SCHEMA_ID}.gschema.xml" "${SCHEMA_DIR}/${OLD_SCHEMA_ID}.gschema.xml"
  command -v glib-compile-schemas >/dev/null 2>&1 && glib-compile-schemas "${SCHEMA_DIR}" 2>/dev/null || true
  say "gone. Your API key (~/.config/jewbuntu/shulgo.conf) and your settings were left alone."
  say "Remove them too with: rm ~/.config/jewbuntu/shulgo.conf && dconf reset -f /com/shulgo/ShulGo/"
}

finish() {
  step "Next"
  say "1. Enable the widget:  gnome-extensions enable ${UUID}"
  say "   (on Xorg, log out and back in first)"
  say "2. Open its settings:  gnome-extensions prefs ${UUID}"
  say "3. Paste the API key you made in ShulGo under Admin › System › API & apps."
  printf '\n'
  say "The ShulGo app shows up in the app grid without its icon until GNOME reads the"
  say "icon theme again — log out and back in, and it will be there."
  printf '\n'
}

need glib-compile-schemas "$(install_hint libglib2.0-bin glib2-devel glib2-devel)"
need gjs "$(install_hint gjs gjs gjs)"

case "${1:---all}" in
  --uninstall) uninstall ;;
  --dev) dev_schema ;;
  --extension) install_schema; install_extension; finish ;;
  --app) install_schema; install_app; finish ;;
  --all) install_schema; install_extension; install_app; finish ;;
  *) echo "Usage: $0 [--all|--extension|--app|--dev|--uninstall]" >&2; exit 2 ;;
esac
