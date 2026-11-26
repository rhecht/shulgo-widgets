/* ShulGo in the menu bar.
 *
 * The next minyan and a countdown sit in the macOS menu bar (the Windows tray on Windows); clicking opens
 * a frosted panel with the same four lists as the JewBuntu widget — Minyanim, Events, Mikvaos, Zmanim.
 *
 * The main process owns everything that matters: the settings, the API key, the API client and the store
 * from shulgo-core. The renderer is a view and nothing more — it never sees the key, and it talks through
 * a narrow preload bridge. The files under ../../shulgo-core are the very same ones the GNOME build runs.
 */

import { app, BrowserWindow, Menu, Tray, ipcMain, nativeImage, net, protocol, screen, shell } from 'electron';
import { dirname, join, normalize } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { ShulGoApi } from '../../shulgo-core/api.js';
import { Cache } from '../../shulgo-core/cache.js';
import { Store } from '../../shulgo-core/store.js';
import * as F from '../../shulgo-core/format.js';

import { Settings, looksLikeKey } from './settings.js';
import { hostname } from 'node:os';

import { makeTransport } from './transport.js';
import { Linking, words, DONE, EXPIRED, OFFLINE, PENDING } from '../../shulgo-core/link.js';
import { Locator } from './location.js';
import { makeNetwork, makeStorage } from './offline.js';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const rendererDir = join(root, 'src', 'renderer');

const PANEL_WIDTH = 420;
const PANEL_HEIGHT = 560;

/** Renderer files are served over app:// so they can use ES modules; file:// can't. */
protocol.registerSchemesAsPrivileged([
    { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true } },
]);

let settings;
let api;
let store;
let cache = null;
let network = null;
let tray = null;
let panel = null;
let settingsWindow = null;
let quitting = false;

// Whether the panel is up. Tracked here rather than asked of Electron, because on Linux the answer
// is wrong: the panel is created with show:false, but its xdg_toplevel exists from that moment and
// is committed with no buffer — nothing on screen, and isVisible() true all the same. So the FIRST
// click on the tray icon took the hide branch and destroyed a window nobody had seen, and it took a
// second click to get the panel up. Measured on a real Cutefish 20261117 screen under
// WAYLAND_DEBUG=client, twice from a fresh start. A flag we set where we show and hide cannot
// disagree with what we actually did.
let panelUp = false;

// ---- serving the renderer ---------------------------------------------------------------------

function serveRenderer() {
    protocol.handle('app', (request) => {
        const url = new URL(request.url);
        // Everything the renderer can load lives in one of two directories, and nowhere else.
        const base = url.hostname === 'core' ? join(root, 'shulgo-core') : rendererDir;
        const wanted = normalize(join(base, decodeURIComponent(url.pathname)));
        if (!wanted.startsWith(base))
            return new Response('Not found', { status: 404 });

        return net.fetch(pathToFileURL(wanted).toString());
    });
}

// ---- the menu bar ------------------------------------------------------------------------------

function trayImage() {
    // macOS template images are black with an alpha channel; the system tints them for light and dark.
    if (process.platform === 'darwin') {
        const image = nativeImage.createFromPath(join(root, 'assets', 'trayTemplate.png'));
        image.setTemplateImage(true);

        return image;
    }

    return nativeImage.createFromPath(join(root, 'assets', 'tray-light.png')).resize({ width: 16, height: 16 });
}

function updateTray() {
    if (!tray)
        return;

    const next = store.headline;
    const minutes = store.nextMinyanIn;
    const mode = settings.get('menuBarText');

    let title = '';
    if (next && mode !== 'icon') {
        const words = `${F.tefillahLabel(next.tefillah)} ${next.display_time}`;
        const pill = F.countdownShort(minutes);
        if (mode === 'countdown')
            title = pill;
        else if (mode === 'time')
            title = next.display_time;
        else
            title = `${words} · ${pill}`;
    }

    // A countdown worked out from an old list shouldn't look as certain as a fresh one. It still shows —
    // you want to know what there was — but with a dot in front of it, and the tooltip says why.
    const notice = F.offlineNotice(store.state, store.hasAnything);
    if (process.platform === 'darwin') {
        const shown = title ? `${notice ? '· ' : ''}${title}` : (notice ? '·' : '');
        tray.setTitle(shown ? ` ${shown}` : '');
    }

    const line = tooltipLine();
    tray.setToolTip(notice ? `${line}\n${notice.title}. ${notice.body}` : line);
}

/** What the tray says on hover.

   Before 1.0.2 an unlinked ShulGo hovered as the single word “ShulGo”, which says nothing about why
   there are no times in it — the one state where the tooltip is the only explanation on screen, since
   the panel has to be opened to be read. The Xfce widget had this right already (“No key yet — choose
   “Link this computer”.”), so these are its words. */
function tooltipLine() {
    const next = store.headline;
    if (next)
        return `${F.tefillahLabel(next.tefillah)} ${next.display_time} — ${F.minyanSubtitle(next, settings.get('travelMode'))}`;

    const state = store.state;
    if (state.needsKey)
        return 'ShulGo — not linked yet. Click the icon, then “Link this computer”.';
    if (state.needsPlace)
        return 'ShulGo — no place chosen yet. Click the icon to pick one.';

    const place = state.place?.label;

    return `ShulGo${place ? ` — ${place}` : ''}`;
}

function buildTray() {
    tray = new Tray(trayImage());
    tray.setIgnoreDoubleClickEvents(true);
    tray.on('click', () => togglePanel());
    tray.on('right-click', () => tray.popUpContextMenu(contextMenu()));

    // Linux draws the menu itself, from the one set here and from nothing else. A tray icon there is a
    // StatusNotifierItem: the panel reads its menu over the bus, and popUpContextMenu — which asks this
    // process to place a window at the pointer — does nothing. Nor does the right-click event above ever
    // fire. So without this line the menu on Linux has no items in it at all, which is what 1.0.0
    // shipped: the icon appeared, the panel opened, and the menu was empty.
    //
    // It must stay Linux-only. On macOS a tray with a context menu set shows that menu on a LEFT click,
    // so this line there would mean the panel never opens again.
    if (process.platform === 'linux')
        tray.setContextMenu(contextMenu());

    updateTray();
}

function contextMenu() {
    // Command+… means something only on a Mac. Elsewhere Electron prints the string beside the item and
    // binds nothing, so a Linux panel was offering “Quit ShulGo   Command+Q” — a shortcut that does not
    // exist on the machine showing it. Better no hint than a wrong one.
    const mac = process.platform === 'darwin';

    return Menu.buildFromTemplate([
        // First, and on Linux the only way in: where an app indicator is used Electron ignores the click
        // event, so for some panels this menu is the whole of what a click on the icon can reach.
        { label: 'Open ShulGo', click: () => showPanel() },
        { type: 'separator' },
        { label: 'Refresh', click: () => store.refresh({ fresh: true }) },
        { label: 'Settings…', accelerator: mac ? 'Command+,' : undefined, click: () => openSettings() },
        { type: 'separator' },
        { label: 'Open shulgo.com', click: () => shell.openExternal(api.siteUrl) },
        { type: 'separator' },
        { label: 'Quit ShulGo', accelerator: mac ? 'Command+Q' : undefined, click: () => { quitting = true; app.quit(); } },
    ]);
}

// ---- the panel ---------------------------------------------------------------------------------

function createPanel() {
    panel = new BrowserWindow({
        width: PANEL_WIDTH,
        height: PANEL_HEIGHT,
        show: false,
        frame: false,
        resizable: false,
        movable: false,
        fullscreenable: false,
        skipTaskbar: true,
        transparent: true,
        hasShadow: true,
        roundedCorners: true,
        // Real glass: macOS blurs whatever is behind the window.
        vibrancy: process.platform === 'darwin' ? 'under-window' : undefined,
        visualEffectState: 'active',
        backgroundMaterial: process.platform === 'win32' ? 'acrylic' : undefined,
        webPreferences: {
            preload: join(here, 'preload.cjs'),
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: true,
        },
    });

    panel.loadURL('app://renderer/panel.html');
    // A menu-bar panel gets out of the way the moment you click elsewhere — except while developing,
    // where it needs to stay put to be looked at.
    const stayOpen = process.argv.includes('--dev');
    panel.on('blur', () => {
        if (!stayOpen && !panel.webContents.isDevToolsOpened())
            hidePanel();
    });
    panel.on('closed', () => {
        panel = null;
        panelUp = false;
    });
}

/** Puts the panel under the menu-bar icon, kept inside the screen it's on. */
function positionPanel() {
    const bounds = tray?.getBounds?.();
    // A tray icon that hasn't been placed in the menu bar yet still answers, with a rectangle of zero
    // height at the far left. Only a rectangle with both sides says where the icon really is; without
    // one, the top right — where the menu-bar extras live — is the better guess than the middle.
    const known = Boolean(bounds && bounds.width > 0 && bounds.height > 0);
    const display = screen.getDisplayNearestPoint(
        known ? { x: bounds.x, y: bounds.y } : screen.getCursorScreenPoint());
    const area = display.workArea;

    let x = known
        ? Math.round(bounds.x + bounds.width / 2 - PANEL_WIDTH / 2)
        : Math.round(area.x + area.width - PANEL_WIDTH - 16);
    x = Math.min(Math.max(x, area.x + 8), area.x + area.width - PANEL_WIDTH - 8);

    if (process.argv.includes('--dev'))
        console.log('[shulgo] tray', JSON.stringify(bounds), known ? '(placed)' : '(not placed yet)');

    const y = process.platform === 'darwin'
        ? Math.round((known ? bounds.y + bounds.height : area.y) + 6)
        : Math.round(area.y + area.height - PANEL_HEIGHT - 8);

    panel.setBounds({ x, y, width: PANEL_WIDTH, height: PANEL_HEIGHT });
}

function showPanel() {
    if (!panel)
        createPanel();
    positionPanel();
    panel.show();
    panel.focus();
    panelUp = true;
    warmUp();
    sendState();
    if (store.stale)
        store.refresh();
}

// How long to leave the first window up before replacing it. Long enough for the compositor to have
// seen it — a hide and a show in the same tick may never reach it as two events — and short enough
// that nobody waits. Measured on Cutefish: click to first frame went from three clicks to 98 ms.
const WARM_UP_MS = 60;
let warmedUp = false;

/** Throw the first window away and take the second, once, on Linux.
 *
 * The fault, traced on a real Cutefish screen with WAYLAND_DEBUG=client: the first time the panel is
 * shown, Electron creates the xdg_toplevel, acks its configure, commits the surface — and never
 * attaches a wl_buffer. Nothing is painted. The second click destroys that toplevel and the third
 * makes another, which attaches three buffers at once and works. The renderer has content the whole
 * time; it is that first toplevel which never gets a frame. So a left-click on a freshly started
 * ShulGo appeared to do nothing, twice, which is what "the widget doesn't work" looks like.
 *
 * This does to the first window what the user was otherwise forced to do by clicking twice more. It
 * runs once, and never on macOS or Windows, where the first window paints like any other and a hide
 * and show would be a visible flicker for nothing.
 *
 * Four candidates were built and measured on that screen before this one was kept. `invalidate()`
 * failed exactly as doing nothing did — there is nothing to repaint when the compositor never
 * received a surface with a buffer. Creating the window already shown and hiding it once painted
 * worked, but at login it took focus and held a painted frame for 21 ms, and ShulGo starts at login.
 * Destroying the window on every hide worked too, and made every reopen 4–5× slower for a fault that
 * happens once. This pays once, at the first show, and is a no-op afterwards.
 *
 * The weak point is the timer, and it is worth naming: on a machine slow enough that 60 ms is not
 * enough, the swap does nothing useful and the user is back to clicking twice — today's behaviour,
 * not something worse. That is the whole downside, which is why a timer was acceptable here.
 */
function warmUp() {
    if (warmedUp || process.platform !== 'linux')
        return;

    warmedUp = true;
    setTimeout(() => {
        if (!panel || !panelUp)
            return;

        panel.hide();
        panel.show();
        panel.focus();
        // Re-asserted because the hide above can raise 'blur', whose handler clears it. The window
        // operations are deliberately exactly the ones that were measured; this only keeps our idea
        // of what is on screen in step with what is.
        panelUp = true;
    }, WARM_UP_MS);
}

/** Every way the panel goes away comes through here, so the flag above cannot drift. */
function hidePanel() {
    panelUp = false;
    if (panel)
        panel.hide();
}

/** Split from showPanel for the tray menu's “Open ShulGo”, which must open and not close. */
function togglePanel() {
    if (panelUp) {
        hidePanel();

        return;
    }

    showPanel();
}

// ---- the settings window ------------------------------------------------------------------------

function openSettings() {
    if (settingsWindow) {
        settingsWindow.show();
        settingsWindow.focus();

        return;
    }

    settingsWindow = new BrowserWindow({
        width: 560,
        height: 680,
        title: 'ShulGo Settings',
        titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
        vibrancy: process.platform === 'darwin' ? 'sidebar' : undefined,
        visualEffectState: 'active',
        backgroundColor: process.platform === 'darwin' ? '#00000000' : '#0b1220',
        webPreferences: {
            preload: join(here, 'preload.cjs'),
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: true,
        },
    });
    settingsWindow.loadURL('app://renderer/settings.html');
    settingsWindow.on('closed', () => {
        settingsWindow = null;
    });
}

// ---- talking to the renderers --------------------------------------------------------------------

/** Everything a view needs, in one object. The key is never part of it. */
function viewState() {
    const s = store.state;
    const mode = settings.get('travelMode');
    const headline = store.headline;

    return {
        settings: { ...settings.all, hasKey: Boolean(settings.apiKey), keyFilePath: settings.keyFilePath },
        siteUrl: api.siteUrl,
        loading: s.loading,
        error: s.error,
        place: s.place,
        updatedAt: s.updatedAt,
        needsKey: s.needsKey,
        needsPlace: s.needsPlace,
        notice: F.offlineNotice(s, store.hasAnything),
        moved: s.movedTimezone ? { zone: s.movedTimezone, place: F.placeFromTimezone(s.movedTimezone) } : null,
        zmanimOutOfDate: store.zmanimOutOfDate,
        zmanimForDate: s.zmanimForDate,
        today: s.today,
        hebrewLine: F.hebrewDayLine(s.today),
        candles: F.candleLighting(s.today),
        mikvaosAllowed: s.mikvaos !== null,
        credit: F.creditLine(s.mikvaosCredit),
        zmanim: F.zmanimList(s.zmanim),
        zmanimMeta: s.zmanimMeta,
        events: (s.events ?? []).map((e) => ({
            ...e,
            dateLabel: F.eventDate(e.date),
            whereLine: [e.when, e.where, e.online ? 'Online' : '', F.miles(e.distance_miles)].filter(Boolean).join(' · '),
            link: e.url || `${api.siteUrl}/events`,
            directions: e.directions ? F.mapsUri(e.directions) : null,
        })),
        mikvaos: (s.mikvaos ?? []).map((m) => ({
            ...m,
            whom: (m.for ?? []).map(F.forWhomLabel),
            whereLine: [m.address, m.city, F.miles(m.distance_mi)].filter(Boolean).join(' · '),
            directions: F.mapsUri(m.lat !== null && m.lat !== undefined
                ? `${m.lat},${m.lng}`
                : [m.address, m.city].filter(Boolean).join(', ')),
        })),
        minyanim: s.minyanim.map((m) => ({
            kind: m.kind,
            tefillah: F.tefillahLabel(m.tefillah),
            displayTime: m.display_time,
            countdown: F.countdown(F.minutesUntil(m.starts_at)),
            urgency: F.urgency(m),
            subtitle: F.minyanSubtitle(m, mode),
            note: F.minyanNote(m),
            isHeadline: m === headline,
            link: m.shul?.url ?? (m.shul?.slug ? `${api.siteUrl}/shul/${m.shul.slug}` : null),
            directions: F.mapsUri(F.minyanDestination(m)),
        })),
        total: s.minyanim.length,
        // When what's shown came out of the cache, the footer says when it was taken, not when we
        // last tried — "Updated just now" over an hours-old list is the one lie the panel must not tell.
        updatedLabel: s.stale ? F.takenAt(s.staleSince) : F.updatedAgo(s.updatedAt),
        updatedAt: s.updatedAt,
    };
}

function sendState() {
    const state = viewState();
    for (const window of [panel, settingsWindow]) {
        if (window && !window.isDestroyed())
            window.webContents.send('shulgo:state', state);
    }
}

function registerIpc() {
    ipcMain.handle('shulgo:getState', () => viewState());
    ipcMain.handle('shulgo:refresh', () => store.refresh({ fresh: true }));
    ipcMain.handle('shulgo:openExternal', (_event, url) => {
        if (typeof url === 'string' && /^https?:\/\//.test(url))
            shell.openExternal(url);
    });
    ipcMain.handle('shulgo:openSettings', () => openSettings());
    ipcMain.handle('shulgo:hidePanel', () => panel?.hide());
    ipcMain.handle('shulgo:network', (_event, online) => network.report(Boolean(online)));
    ipcMain.handle('shulgo:settleTimezone', () => store.settleTimezone());
    ipcMain.handle('shulgo:quit', () => {
        quitting = true;
        app.quit();
    });

    ipcMain.handle('shulgo:set', (_event, changes) => {
        const moved = settings.set(changes ?? {});
        if (moved.includes('openAtLogin'))
            app.setLoginItemSettings({ openAtLogin: settings.get('openAtLogin') });

        return viewState();
    });

    ipcMain.handle('shulgo:searchPlaces', async (_event, text) => {
        const answer = await api.places(String(text ?? ''));

        return answer.ok ? answer.data : [];
    });

    ipcMain.handle('shulgo:setPlace', (_event, match) => {
        settings.set({
            place: match.label,
            latitude: match.lat,
            longitude: match.lng,
            locationLabel: match.label,
        });
        // Choosing a place answers the "have you travelled?" question too.
        store.settleTimezone();
        api.forget();
        store.refresh({ fresh: true });
    });

    /* Linking this computer (RFC 8628). The whole handshake stays in the main process on purpose:
     * the renderer is told the short code and how it is going, and never sees the device code or
     * the key itself — the same reason the transport lives here. */
    let linking = null;

    ipcMain.handle('shulgo:linkStart', async () => {
        // Before anything else. Linking is the one thing here that cannot fall back on what was
        // saved earlier — there is nothing saved yet — so an unconnected machine should be told
        // that, not left waiting on a timeout and then told ShulGo is at fault.
        if (network.isOnline() === false)
            return { ok: false, message: OFFLINE };

        const started = await api.deviceStart('ShulGo for Mac', hostname());
        if (!started.ok)
            return { ok: false, message: started.message };

        linking = new Linking(started.data ?? {});
        if (!linking.usable) {
            linking = null;

            return { ok: false, message: 'ShulGo sent an answer this app couldn’t use.' };
        }

        return {
            ok: true,
            userCode: linking.userCode,
            verificationUri: linking.verificationUri,
            interval: linking.interval,
            words: words(PENDING, linking),
        };
    });

    ipcMain.handle('shulgo:linkPoll', async () => {
        if (!linking)
            return { state: 'error', words: 'Nothing is being linked.' };
        if (linking.expired())
            return { state: EXPIRED, words: words(EXPIRED, linking) };

        const state = linking.absorb(await api.devicePoll(linking.deviceCode));

        if (state === DONE) {
            // The key is saved here and goes no further: the renderer learns only that it worked.
            settings.apiKey = linking.key;
            api.reconfigure({ apiKey: linking.key });
            linking = null;
            store.refresh({ fresh: true });

            return { state, words: words(state, null) };
        }

        const answer = { state, words: words(state, linking), interval: linking.interval };
        if (state !== PENDING)
            linking = null;

        return answer;
    });

    ipcMain.handle('shulgo:linkStop', () => {
        linking = null;

        return { ok: true };
    });

    ipcMain.handle('shulgo:setKey', async (_event, key, { remove = false } = {}) => {
        const clean = String(key ?? '').trim();

        if (remove) {
            settings.apiKey = '';
            api.reconfigure({ apiKey: '' });
            store.refresh({ fresh: true });

            return { ok: true, message: 'Key removed.' };
        }

        // The box starts empty even when a key is saved, because the saved one is never shown. Pressing
        // the button with nothing typed must therefore test what's saved, not wipe it.
        if (!clean) {
            if (!settings.apiKey)
                return { ok: false, message: 'Paste a key first.' };
            const check = await api.places('Lakewood, NJ');

            return check.ok
                ? { ok: true, message: `The saved key works — ${api.siteUrl} answered.` }
                : { ok: false, message: check.message };
        }

        if (!looksLikeKey(clean))
            return { ok: false, message: 'A ShulGo key looks like sg_live_ followed by 40 letters and digits.' };

        settings.apiKey = clean;
        api.reconfigure({ apiKey: clean });

        const answer = await api.places('Lakewood, NJ');
        if (!answer.ok)
            return { ok: false, message: answer.message };

        store.refresh({ fresh: true });

        return { ok: true, message: `The key works — ${api.siteUrl} answered.` };
    });
}

// ---- starting up ----------------------------------------------------------------------------------

function start() {
    settings = new Settings();
    const config = settings.asConfig();

    network = makeNetwork();
    cache = new Cache(makeStorage());

    api = new ShulGoApi({
        baseUrl: settings.get('apiBaseUrl'),
        apiKey: settings.apiKey,
        transport: makeTransport(),
        cache,
        isOnline: network.isOnline,
    });
    store = new Store(api, config, new Locator(api, config), network);

    store.connect(() => {
        updateTray();
        sendState();
        cache.save();
    });

    settings.watch((moved) => {
        if (moved.includes('apiBaseUrl'))
            api.reconfigure({ baseUrl: settings.get('apiBaseUrl') });
        if (moved.some((k) => ['apiBaseUrl', 'place', 'windowMinutes', 'travelMode', 'tefillah', 'mikvahFor'].includes(k))) {
            api.forget();
            store.refresh();
        }
        if (moved.includes('refreshSeconds'))
            store.restartTimers();
        updateTray();
        sendState();
    });

    // A tray app has no menu bar, but on Linux it is given one anyway: a desktop with a global menu
    // bar — Cutefish's, for one — shows Electron's default File / Edit / View / Window / Help while
    // the panel is up, and not one of those items does anything in ShulGo. Linux only: a null menu on
    // macOS would take away Cmd-Q, Cmd-C and the rest, which every Mac app is expected to have.
    if (process.platform === 'linux')
        Menu.setApplicationMenu(null);

    serveRenderer();
    registerIpc();
    buildTray();
    createPanel();

    store.start();
    store.refresh();
}

// A menu-bar app has no Dock icon and no windows of its own to keep it alive.
if (process.platform === 'darwin')
    app.dock?.hide();

if (!app.requestSingleInstanceLock()) {
    app.quit();
} else {
    app.on('second-instance', () => togglePanel());

    app.whenReady().then(() => {
        start();
        if (process.argv.includes('--show'))
            togglePanel();
    });

    app.on('window-all-closed', (event) => {
        // The tray is the app; closing the settings window mustn't end it.
        if (!quitting)
            event?.preventDefault?.();
    });

    app.on('before-quit', () => {
        quitting = true;
        store?.destroy();
        cache?.save();
    });
}
