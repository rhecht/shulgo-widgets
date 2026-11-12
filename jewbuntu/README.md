# ShulGo for JewBuntu

The next minyan near you, in the Ubuntu top bar — and the same four lists in a window when you want room
to read them. Both halves talk to ShulGo's public API (`/api/v1`) and share one set of settings, so they
always say the same thing.

```
┌─ Top bar ───────────────────────────────────┐
│  🕍 Mincha 1:45 PM  3m                  ▾   │
└─────────────────────────────────────────────┘
      ╭──────────────────────────────────────╮
      │ Lakewood, NJ                   ⟳  ⚙  │
      │ 1 Kislev, 5787 · Rosh Chodesh Kislev │
      │ ╭──────────────────────────────────╮ │
      │ │ Minyanim │ Events │ Mikvaos │ Z  │ │
      │ ╰──────────────────────────────────╯ │
      │  Next  Shacharis  Mincha  Maariv     │
      │ ● 1:45 PM  Mincha                    │
      │   in 3 min Chevra Lomdei Torah·0.8mi │
      │ ● 1:45 PM  Mincha        Too far     │
      │   in 3 min Bais Medrash · 12 min walk│
      ╰──────────────────────────────────────╯
```

## What you get

- **A top-bar widget** (GNOME Shell extension, `jewbuntu@shulgo.com`) — the next minyan and a countdown
  in the bar, and a menu with four tabs: Minyanim, Events, Mikvaos and Zmanim.
- **A window** (`shulgo`, in the dock and the app grid) — the same four lists, with a hero card for the
  minyan you can still reach, a place search and the full zmanim table.

Both are ShulGo navy glass with a gold accent: the same palette as shulgo.com and the phone app, kept in
`src/shulgo/core/palette.js`.

## Install

```bash
./install.sh
```

Nothing goes outside `$HOME` and nothing needs root. Then:

```bash
gnome-extensions enable jewbuntu@shulgo.com
```

On Xorg, log out and back in first. `./install.sh --extension` or `--app` installs one half only, and
`./install.sh --uninstall` takes it all out again (your key and settings stay).

Needs GNOME Shell 45–49 (Ubuntu 24.04 and later), `gjs` and `libglib2.0-bin`.

## The API key

Everything the widget shows comes from ShulGo's API, which wants a key on every request.

1. In ShulGo, go to **Admin › System › API & apps** and make a key.
   - **ShulGo's own app** is the kind to pick if mikvaos should show: mikvah.org's terms restrict those
     listings to ShulGo's own apps. With any other kind the API answers `403` for mikvaos and the widget
     quietly drops that tab — everything else still works.
2. Open the widget's settings (`gnome-extensions prefs jewbuntu@shulgo.com`, or the gear in the menu),
   go to **ShulGo**, paste the key and press **Save and test**.

The key is written to `~/.config/jewbuntu/shulgo.conf`, readable only by you — not into dconf, which any
process in your session can read. `SHULGO_API_KEY` in the environment overrides it, which is handy when
testing against a second ShulGo.

## Settings

All of it is in one place, shared by both halves (`gsettings`, schema `com.shulgo.ShulGo`).

| | |
|---|---|
| **Where** | This computer's location (GeoClue), or a place you type — a city, neighborhood or zip, matched against ShulGo's own `/places`. |
| **How far ahead** | 15 minutes to 6 hours. |
| **How you get there** | Driving or walking — it decides whether a minyan is still reachable. |
| **Which tefillah** | Whatever is next, or just Shacharis, Mincha or Maariv. |
| **Top bar** | Tefillah + time + countdown, countdown only, time only, or just the icon. Left, centre or right. |
| **Glass** | See-through (default), frosted, or solid navy. |
| **Mikvaos** | All, or women, men or keilim only. |

**On the location setting:** GeoClue has to be allowed to answer. If *Location Services* is off in
Settings › Privacy, or this app isn't in `/etc/geoclue/geoclue.conf`, the widget falls back to the place
you typed without complaining. Typing a place is the reliable route.

**On frosted glass:** the Shell's blur paints over a rectangle and doesn't follow rounded corners on every
GNOME version, which is why *see-through* is the default. Try *frosted* and keep it if it looks right on
your machine.

## How it fits together

```
../shulgo-core/       plain JavaScript, no GNOME in it at all — shared with the macOS build
  api.js              the ShulGo API v1 client — takes a transport, so it ports as it stands
  format.js           every word and number the two halves show
  store.js            where we are + the four lists + who to tell when they change
  palette.js          ShulGo's colours, from the website and the phone app

src/shulgo/gnome/     the parts that are GNOME's
  transport.js        one GET over libsoup 3
  settings.js         GSettings, and the key file
  geo.js              GeoClue
  prefs-pages.js      the settings pages — the widget and the window show the same ones

extension/jewbuntu@shulgo.com/   the top-bar widget (GNOME Shell, St/Clutter)
app/                             the window (GTK 4 + libadwaita, also GJS)
schemas/                         one settings schema, installed into both
```

`install.sh` assembles `shulgo/` for each half — `core/` from `../shulgo-core`, `gnome/` from here — so
each one can be moved or packaged on its own.

`shulgo-core` is deliberately free of GNOME, and the macOS menu-bar build in `../desktop` uses the very
same files. Each platform brings its own transport, settings store and location source; the client, the
wording and the palette carry over untouched.

## Working on it

```bash
./install.sh --dev    # compiles the schema and links the shared code into app/shulgo
SHULGO_SCHEMA_DIR="$PWD/schemas/build" gjs -m app/main.js
```

For the top-bar widget, install it and then watch what it says:

```bash
journalctl -f -o cat /usr/bin/gnome-shell
```

On Wayland, a Shell extension can't be reloaded in place — log out and back in, or test in a nested
Shell: `dbus-run-session -- gnome-shell --nested --wayland`.

## What it asks ShulGo for

| | |
|---|---|
| `GET /next` | minyanim starting soon, soonest first, with how long it takes to get there |
| `GET /events` | upcoming events within 50 miles |
| `GET /mikvaos` | mikvaos nearby (ShulGo's own apps only) |
| `GET /zmanim` | today's zmanim, each with a line on which opinion it follows |
| `GET /calendar` | the Hebrew date, yom tov and candle lighting |
| `GET /places` | what a typed place means |

Answers are cached for as long as they're good for — a minute for minyanim, six hours for zmanim — and two
requests for the same thing at once share one answer. Countdowns tick locally, so the bar stays right
between requests instead of asking every minute.

## When ShulGo can't be reached

Every good answer is also written down, in `~/.cache/jewbuntu-shulgo/answers.json`. When a request fails
— the machine is offline, the site is down, the train went into a tunnel — the last one is shown
instead, under a quiet strip saying where it came from and when:

> **You're offline** · This is the list from 1:45 PM. It'll catch up on its own.  ⟨Try now⟩

The list underneath stays usable: countdowns keep ticking locally and minyanim whose time has passed
drop off, so nothing is shown as upcoming when it isn't. The footer says "from 1:45 PM" rather than
"Updated just now", because that is the one thing the panel must not get wrong. Zmanim belong to a single
day, so if the saved ones are yesterday's they are labelled as such rather than passed off as today's.

With nothing saved yet, you get a friendly resting state instead of an error, and it keeps trying in the
background.

It uses GNOME's own `NetworkMonitor`, so it knows about a captive portal or a link with no route — which
means no fifteen-second timeout before it gives you the saved list. Repeated failures back off, up to a
quarter of an hour; the moment the network returns it tries again at once.

A key the server itself refused — invalid, or not allowed to read mikvaos — is never papered over with an
old answer. That is not a network problem, and you want to be told.
