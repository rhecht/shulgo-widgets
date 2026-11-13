# ShulGo on your desktop

The next minyan near you, in the top bar — with upcoming events, mikvaos and today's zmanim. Built on
[ShulGo](https://shulgo.com)'s public API.

There are five things in here, and they share one brain.

| | what it is | state |
| --- | --- | --- |
| [`jewbuntu/`](jewbuntu) | a GNOME Shell extension and a GTK app, for GNOME 45–50 | **tried and working**, on JewBuntu and GNOME Shell 50 |
| [`desktop/`](desktop) | an Electron menu-bar / tray app for macOS, Windows and Linux | **macOS tried and working**; Windows and Linux build but **nobody has run them yet** |
| [`shulgo-xfce/`](shulgo-xfce) | a Python 3 + GTK3 tray widget for Xfce, old hardware and 32-bit | **logic tested, window never run** — see its README |
| [`wordpress/`](wordpress) | a plugin that puts your shul's times on your own site with a shortcode | |
| [`shulgo-core/`](shulgo-core) | the shared part: the API client, the offline cache, the wording | |

`shulgo-core` has no platform imports at all. Each platform hands it four things — a transport, a
settings store, a locator and a storage adapter — and gets the same behaviour in return, so a minyan
list says the same thing on GNOME as it does on a Mac. [Its README](shulgo-core/README.md) spells out
the contract if you want to carry it somewhere new.

With one exception, and it is an honest one. `shulgo-xfce` is **Python**, so it cannot import any of
that — the machine it was written for has no usable JavaScript engine. It carries a hand port
instead, and the port is held to the original by a test that runs the real `format.js` under node and
insists the Python produces the same 138 strings. That is the arrangement any future port that can't
run JavaScript — an iOS or Android home-screen widget, say — would have to make too.

## Getting it

**GNOME (JewBuntu, Ubuntu, Fedora, anything with GNOME 45 or newer)**

```sh
cd jewbuntu && ./install.sh
```

Per-user, no root. It installs the top-bar extension, the ShulGo app, and the settings schema they
share. `./install.sh --uninstall` takes it all out again.

**macOS, Windows, Linux (the tray app)**

Installers are built for all three by [the desktop
workflow](https://github.com/rhecht/shulgo-widgets/actions/workflows/desktop.yml). To build it
yourself:

```sh
cd desktop && npm install && npm run dev
```

Nothing is code-signed yet. macOS will say the app is from an unidentified developer — right-click ›
Open the first time. Windows SmartScreen will warn before the installer runs. Linux needs no
signature.

**Xfce, or anything old**

```sh
cd shulgo-xfce && python3 -m shulgo_xfce --check && python3 -m shulgo_xfce
```

Python 3.9+, PyGObject and GTK3; no Electron, no GNOME, no compiled code. There is an `arch=('any')`
PKGBUILD in `shulgo-xfce/packaging`, which needs a release tag and a licence before it can go
anywhere. Read that directory's README first — the logic is well tested and the GTK layer has never
been run at all.

**WordPress**

Copy `wordpress/shulgo-minyanim` into `wp-content/plugins`, switch it on, then put
`[shulgo_times shul="your-shul"]` in a page.

## You need a ShulGo API key

Every piece here talks to `https://shulgo.com/api/v1`, which wants a key. Ask your ShulGo
administrator for one, then paste it into the widget's own settings window.

The key is never kept in GSettings or dconf, and never reaches a renderer process. It lives in a file
only you can read — `~/.config/jewbuntu/shulgo.conf` on Linux, `shulgo.conf` in the app's data
directory on macOS — and `SHULGO_API_KEY` in the environment overrides it, so a test run needn't touch
the saved one.

One honest limit: **mikvaos need a first-party key.** mikvah.org's terms restrict that data, so the
keys the public form issues light up minyanim, events and zmanim, but not the mikvaos tab.

## When ShulGo can't be reached

The last good answer is written down, and shown again under a friendly strip saying you're offline or
ShulGo isn't answering, with the time it was taken. Countdowns keep ticking. A 4xx — a bad key, a
forbidden tab — is never papered over with stale data, because that would hide a real answer. If
nothing has been saved yet you get a resting state rather than an error.

This was tried on a real desktop with the network pulled out, and both halves recovered on their own
when it came back.

## Licence

Not settled yet. Until it is, treat this as "all rights reserved": you can read it, and you can build
and run it for yourself, but nothing here grants you the right to redistribute it.

The WordPress plugin's own header declares GPL-2.0-or-later, because WordPress.org requires it, and a
GNOME Shell extension has to be GPL-compatible to go on extensions.gnome.org. So a GPL licence is the
likely answer — but it hasn't been chosen, and this file won't pretend otherwise.

## Where this comes from

The code is developed inside ShulGo's own (private) repository and mirrored out here. Issues and
patches are welcome; they may take a detour on the way in.
