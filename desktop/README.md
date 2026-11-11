# ShulGo in the menu bar

The next minyan near you in the macOS menu bar, and a frosted panel with the same four lists as the
JewBuntu widget — Minyanim, Events, Mikvaos, Zmanim. The same `../shulgo-core` files run behind both, so
the Mac and the Linux desktop never disagree about what they say.

```
  ⌘  🔅  🔊  📶   🕍 Mincha 2:20 PM  13m   Wed 2:07 PM
                  ╭─────────────────────────────────╮
                  │ Lakewood, NJ              ⟳  ⚙  │
                  │ 1 Kislev, 5787 · Rosh Chodesh   │
                  │ ╭─────────────────────────────╮ │
                  │ │Minyanim│Events│Mikvaos│Zman │ │
                  │ ╰─────────────────────────────╯ │
                  │ SOONEST YOU CAN MAKE            │
                  │▌2:20 PM  Mincha                 │
                  │ in 13 min Kol Shimshon · 1.2 mi │
                  │ ALSO COMING UP                  │
                  │ 2:15 PM  Mincha      Too far    │
                  ╰─────────────────────────────────╯
```

Built for macOS first. The same code runs on Windows (tray icon, acrylic panel) and Linux; neither has
been tried yet.

## Running it

```bash
npm install
npm run dev
```

`npm run dev` syncs `../shulgo-core` into the package, opens the panel straight away and keeps it open
when it loses focus, which it otherwise wouldn't. `npm start` runs it the way it really behaves: the
panel appears when you click the menu-bar icon and gets out of the way when you click elsewhere.

Then open Settings from the panel's gear, paste a ShulGo API key, and set a place.

## The API key

1. In ShulGo: **Admin › System › API & apps**, make a key.
   - Pick **ShulGo's own app** if mikvaos should show — mikvah.org's terms keep those listings to
     ShulGo's own apps. With any other kind the API answers `403` for mikvaos and the Mikvaos tab
     quietly disappears; everything else still works.
2. Paste it into Settings and press **Save and test**.

It is written to `~/Library/Application Support/shulgo-desktop/shulgo.conf`, mode 600, and never reaches
a renderer: the API client lives in the main process. `SHULGO_API_KEY` in the environment overrides it.

Pressing **Save and test** with the box empty tests the key that is already saved — it does not clear it.
**Remove** is the only thing that clears it.

## Where it thinks you are

You type a place; ShulGo's own `/places` works out what you meant and it is remembered.

There is deliberately no IP lookup — that means handing your address to a third party to learn what city
you are in, a poor trade for a minyan finder. macOS could do better through CoreLocation, but Electron
can only reach `navigator.geolocation` with a Google geolocation key, which is another third party. A
small native helper would fix this properly; until then, type a city once. The JewBuntu build has the
same fallback and gets the real thing from GeoClue.

## Glass

The panel is a real `NSVisualEffectView` — macOS blurs whatever is behind it — with ShulGo's navy laid
over the blur. The **Glass** setting decides how much navy: *see-through*, *frosted* or *solid navy*. On
Windows the same setting picks the acrylic backdrop.

## How it fits together

```
../shulgo-core/        plain JavaScript, no platform in it — shared with the JewBuntu build
  api.js               the ShulGo API v1 client; takes a transport, so it ran here unchanged
  format.js            every word and number both builds show
  store.js             where we are + the four lists + who to tell when they change
  palette.js           ShulGo's colours, from the website and the phone app

src/main/              the main process: it owns the settings, the key, the API client and the store
  main.js              tray, panel, settings window, IPC
  settings.js          settings.json, and the key file
  transport.js         one GET through Node's fetch
  location.js          a typed place, looked up and remembered
  preload.cjs          the only road between the panel and the main process

src/renderer/          the views — no logic worth the name, no Node, never the key
  panel.html/.js/.css  the menu-bar panel
  settings.html/...    the settings window
  shared.css           ShulGo's colours and the pieces both windows use

scripts/
  sync-core.mjs        copies ../shulgo-core in (runs on its own before start/pack/dist)
  make-icons.mjs       draws the tray and app icons straight to PNG, no image library
```

The renderer is served over `app://` rather than `file://`, because Chromium won't load ES modules from
`file://`. Context isolation is on, the sandbox is on, node integration is off, and there is a strict CSP
on both pages.

Everything the views draw is worked out by `shulgo-core` in the main process and arrives as one state
object — that is what keeps this panel and the JewBuntu widget saying the same thing.

## Packaging

```bash
npm run dist     # a .dmg and a .zip, through electron-builder
```

`LSUIElement` is set, so the packaged app has no Dock icon and no menu of its own — it is the menu-bar
item. For a signed, notarized build, add your signing identity to `build.mac` in `package.json`; nothing
here is signed yet.

## What it asks ShulGo for

The same six endpoints as the JewBuntu widget: `/next`, `/events`, `/mikvaos`, `/zmanim`, `/calendar`
and `/places`. Answers are cached for as long as they're good for — a minute for minyanim, six hours for
zmanim — and countdowns tick locally, so the menu bar stays right between requests.

## When ShulGo can't be reached

Every good answer is also written to `answers.json` beside the settings. When a request fails — no
network, site down, laptop lid just opened on a train — the last one is shown instead, under a quiet
amber strip saying where it came from and when, with a **Try now** button. The footer then says "from
1:45 PM" rather than "Updated just now", and the menu-bar text gains a leading dot so a countdown worked
out from an old list doesn't look as certain as a fresh one.

With nothing saved yet you get a friendly resting state rather than an error. Repeated failures back off
up to a quarter of an hour, and the panel — being an ordinary web page, and so the part of the app that
hears `online`/`offline` — tells the main process the moment the network returns, which retries at once.

A key the server itself refused is never papered over with an old answer.
