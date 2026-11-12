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
import { makeTransport } from './transport.js';
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

    const place = store.state.place?.label;
    const line = next
        ? `${F.tefillahLabel(next.tefillah)} ${next.display_time} — ${F.minyanSubtitle(next, settings.get('travelMode'))}`
        : `ShulGo${place ? ` — ${place}` : ''}`;
    tray.setToolTip(notice ? `${line}\n${notice.title}. ${notice.body}` : line);
}

function buildTray() {
    tray = new Tray(trayImage());
    tray.setIgnoreDoubleClickEvents(true);
    tray.on('click', () => togglePanel());
    tray.on('right-click', () => tray.popUpContextMenu(contextMenu()));
    updateTray();
}

function contextMenu() {
    return Menu.buildFromTemplate([
        { label: 'Refresh', click: () => store.refresh({ fresh: true }) },
        { label: 'Settings…', accelerator: 'Command+,', click: () => openSettings() },
        { type: 'separator' },
        { label: 'Open shulgo.com', click: () => shell.openExternal(api.siteUrl) },
        { type: 'separator' },
        { label: 'Quit ShulGo', accelerator: 'Command+Q', click: () => { quitting = true; app.quit(); } },
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
            panel.hide();
    });
    panel.on('closed', () => {
        panel = null;
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

function togglePanel() {
    if (!panel)
        createPanel();
    if (panel.isVisible()) {
        panel.hide();

        return;
    }
    positionPanel();
    panel.show();
    panel.focus();
    sendState();
    if (store.stale)
        store.refresh();
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
