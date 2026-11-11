# shulgo-core

The part of ShulGo's desktop clients that has no platform in it: plain JavaScript, no GNOME, no Electron,
no Node built-ins. One copy, used by every build.

| | |
|---|---|
| `api.js` | the ShulGo API v1 client. It takes an HTTP *transport* rather than reaching for one, so each platform hands it whatever it has — libsoup on GNOME, `fetch` on the desktop app. Caches each answer for as long as it's good for, and shares one answer between two requests for the same thing. |
| `format.js` | every word and number the clients show: tefillah names, countdowns, distances, "about 8 min drive", whether a minyan can still be reached, zmanim in clock order. |
| `store.js` | works out where we are, asks for the four lists, keeps them, and tells whoever is listening when anything changes. Timers are `setInterval`. |
| `palette.js` | ShulGo's colours, from `public/assets/css/site.css` and `mobile/src/constants/theme.ts`. |
| `cache.js` | the last good answer to every question, written down, so a failed request is answered from it rather than with nothing. |

Who uses it:

- `../jewbuntu` — the GNOME Shell widget and the GTK window. `install.sh` copies this directory in.
- `../desktop` — the macOS menu-bar app. `npm run sync-core` copies this directory in.

Each build copies rather than links, so it can be moved or packaged on its own. This directory is the
only real copy; change it here.

**Keep it platform-free.** No `gi://`, no `electron`, no `node:`. A platform brings its own three things:

1. a **transport** — one GET, answering `{status, body, headers}`
2. a **settings store** — anything with the getters `store.js` reads (`baseUrl`, `windowMinutes`,
   `travelMode`, `tefillah`, `refreshSeconds`, `mikvahFor`, `listLength`, `point`, `rememberPoint`)
3. a **locator** — anything with `resolve()` answering `{lat, lng, label, source}` or null
4. a **storage adapter** — `{read(): string|null, write(text)}` for `cache.js`, and optionally a
   **network monitor** — `{isOnline(), onChange(cb)}` — so the client needn't sit through a timeout to
   learn what the machine already knows

That is the whole contract. iOS and Android would need the same three and could take these four files as
they stand.
