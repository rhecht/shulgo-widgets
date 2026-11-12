# ShulGo for Xfce

The next minyan near you in the system tray, with today's zmanim. GTK3 and Python 3, for Xfce and any
other X11 panel that shows tray icons.

## Why this exists when there is already a ShulGo widget

There are three desktop builds and they are not interchangeable:

| | what it needs | where it fits |
| --- | --- | --- |
| [`../jewbuntu`](../jewbuntu) | GNOME 45+, a current gjs, GTK4 + libadwaita | GNOME, modern hardware |
| [`../desktop`](../desktop) | Electron | macOS, Windows, 64-bit Linux |
| **this one** | Python 3.9+, PyGObject, GTK3 | Xfce, old hardware, 32-bit |

It was written for a specific machine: a Pentium III laptop with 256 MB of RAM running Arch Linux 32
with Xfce 4.18 on X11. On that machine Electron does not exist, gjs is from 2021, there is no GL, and
the CPU has SSE but not SSE2 — so a JIT-heavy runtime is a gamble. CPython has no JIT, which is what
makes Python the safe choice here rather than the obvious one.

Everything about the shape follows from that: a popup menu rather than a window, widgets built once
and relabelled rather than rebuilt, countdowns worked out locally on a one-minute tick, and the
network touched every fifteen minutes by default.

## State, honestly

**The logic is tested. The window is not.**

61 tests pass, covering the wording, the API client, the offline failsafe, the key and settings files,
and the two rules that decide what you see. Of those, 138 individual wording cases are checked
*against the JavaScript* — see below.

But `tray.py` and `settings_window.py` have never been executed. There is no PyGObject on the machine
this was written on, so not one line of the GTK code has run, and no tray icon has ever appeared. A
static check for undefined names passes, which is worth something and is not worth much: it caught
one real crash-on-startup during development and it cannot catch a wrong argument to a GTK call.

Treat the first run as the first run. `python3 -m shulgo_xfce --check` is there for exactly that
moment — it reports which tray library is installed, whether there is a display, and whether a key and
a place have been saved, which are the three things that make a tray icon silently not appear.

## If every GTK program on Arch Linux 32 is broken, it isn't this one

Worth knowing before you conclude the widget is at fault, because the symptom looks exactly like a bug
in here. As of November 2026, Arch Linux 32's i686 repositories ship pango 1:1.58.2, which needs
`FcConfigSetDefaultSubstitute`, against fontconfig 2.14.1 from 2022, which does not have it — and
pangoft2 is linked `BIND_NOW`, so the failure happens at load rather than at first use. Everything
GTK falls over: xfwm4, xfce4-panel, thunar, and PyGObject's Gtk and Gdk. From Python it surfaces as an
`AssertionError` inside `gi/overrides/Gdk.py`, which reads like our problem and is not.

The workaround, verified by the Jewbuntu Arch port: install pango `1:1.54.0-1.0` from
archive.archlinux32.org, check its signature, and hold it with `IgnorePkg` until fontconfig is
rebuilt. 1.54.0, 1.52.2 and 1.50.14 load; 1.57.1 and 1.58.2-1.1 do not.

## Trying it

```sh
cd integrations/shulgo-xfce
python3 -m shulgo_xfce --check      # what this machine has
python3 -m shulgo_xfce              # run it
```

Then click the icon › Settings, paste a ShulGo API key, and search for where you daven.

## How the wording is kept honest

`shulgo-core/format.js` holds ShulGo's wording and is canonical: it is what the GNOME widget, the GTK
app and the Mac and Windows tray all read. Python cannot import a JavaScript module, so `fmt.py` is a
hand port of it — and a copy nobody checks is a copy that drifts.

So `tests/cases.json` holds 138 inputs, `tests/make-expected.mjs` runs **the real format.js** under
node over them, and `tests/test_fmt.py` insists the Python answers identically.

```sh
cd tests && TZ=America/Toronto node make-expected.mjs     # only when format.js changes
cd .. && TZ=America/Toronto python3 -m unittest discover -s tests
```

This is not ceremony. On its first run it found two defects in the shared JavaScript — a missing
distance printing as `0.0 mi`, which tells someone the shul is where they are standing, and `urgency`
calling a null buffer `tight` while an absent one was `comfortable`, the same absence of information
reported two different ways. Both were fixed in `format.js`, which means the GNOME and Mac builds got
the fix too.

Two things are deliberately not compared to the JavaScript, and `fmt.py` says so where it happens:
anything that reads the real clock (tested here against a frozen one), and the clock *format* — JS
asks `Intl` for the locale's own and Python has no `Intl`, so a 24-hour locale shows `13:45` there and
`1:45 PM` here, in a line that says how old the data is.

## Where your things are kept

The API key is in `~/.config/jewbuntu/shulgo.conf`, mode 0600 — **the same file, in the same format,
that the GNOME extension and the ShulGo GTK app use**, so a machine running both shares one key.
`SHULGO_API_KEY` in the environment overrides it, so a test run needn't touch the saved one. The key
is kept out of GSettings on purpose: dconf is readable by everything in your session.

This widget's own settings are in a **second** file, `shulgo-xfce.conf`. Not tidiness — the GNOME
half rewrites `shulgo.conf` from scratch whenever the key changes, keeping only the key line, so
anything else kept in there would be destroyed the next time you edited your key in GNOME.

The offline cache is `~/.cache/jewbuntu/shulgo-xfce.json`, at most 60 entries.

No GSettings anywhere on this side, which also means no schema to install and no dconf daemon to run.

## When ShulGo can't be reached

The last good answer is shown again, under a line saying you're offline or ShulGo isn't answering,
with the time it was taken. Countdowns keep ticking without the network. Minyanim whose time has
passed drop off by themselves, with a minute of grace — one that began forty seconds ago is still one
you can walk into — which is what makes an hour-old list honest rather than merely old.

A 4xx is never papered over with old data. Yesterday's minyanim behind a bad key would hide the one
thing worth telling you.

## Packaging

Dependencies are what the Jewbuntu Arch port measured on i686, not what seemed likely:
`python python-gobject gtk3 libayatana-appindicator`. `AyatanaAppIndicator3` 0.1 is the typelib that
exists there and the older `AppIndicator3` is absent, so the tray library is a hard dependency. There
is deliberately no dependency on `xfce4-statusnotifier-plugin` — Xfce 4.18's own systray already
contains the StatusNotifierWatcher, and that package does not exist in Arch Linux 32 at all.

`packaging/PKGBUILD` builds an `arch=('any')` package: no compiled code, so the same package serves
i686, x86_64 and the arm64 of an Apple Silicon machine. No install scripts, and nothing written into
a home directory by root — the widget makes its own files, as you, on first run.

Two things block it going anywhere:

1. **The source tag doesn't exist yet**, so `sha256sums` is `SKIP`. Run `updpkgsums` once it does.
2. **ShulGo has no licence yet**, and Arch requires a custom licence be shipped under
   `/usr/share/licenses/`. Until somebody chooses one, this cannot go to the AUR.

## What it does not do

No mikvaos: that data is mikvah.org's and their terms limit it to ShulGo's own first-party keys. No
events or Hebrew calendar — the endpoints exist and the port left them out to stay small. No GeoClue
by default; you pick a place once, because on a laptop with no usable WiFi scanning a location fix
mostly fails, and a widget that asks and fails is worse than one that asks once.
