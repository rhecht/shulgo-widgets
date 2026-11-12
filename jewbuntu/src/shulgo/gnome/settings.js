/* Settings shared by the top-bar widget and the ShulGo app.
 *
 * Everything but the API key lives in GSettings (schema com.shulgo.ShulGo), so a change in either half
 * shows up in the other at once. The key itself is kept in ~/.config/jewbuntu/shulgo.conf with owner-only
 * permissions, because dconf is world-readable inside the session and an API key shouldn't be.
 */

import GLib from 'gi://GLib';
import Gio from 'gi://Gio';

export const SCHEMA_ID = 'com.shulgo.ShulGo';

/** ~/.config/jewbuntu/shulgo.conf */
export function configPath() {
    return GLib.build_filenamev([GLib.get_user_config_dir(), 'jewbuntu', 'shulgo.conf']);
}

/**
 * The ShulGo API key. SHULGO_API_KEY in the environment wins, so a test run can use another key without
 * touching the saved one.
 */
export function loadApiKey() {
    const fromEnv = GLib.getenv('SHULGO_API_KEY');
    if (fromEnv)
        return fromEnv.trim();

    const file = Gio.File.new_for_path(configPath());
    try {
        const [ok, bytes] = file.load_contents(null);
        if (!ok)
            return '';
        const text = new TextDecoder().decode(bytes);
        for (const line of text.split('\n')) {
            const m = line.match(/^\s*api-key\s*=\s*(\S+)\s*$/);
            if (m)
                return m[1];
        }
    } catch {
        // No file yet, or we can't read it: the widget will ask for a key.
    }

    return '';
}

/** Writes the key, owner-read-write only. An empty key removes the file. */
export function saveApiKey(key) {
    const path = configPath();
    const dir = Gio.File.new_for_path(path).get_parent();
    try {
        if (!dir.query_exists(null))
            dir.make_directory_with_parents(null);
    } catch { /* already there */ }

    const file = Gio.File.new_for_path(path);
    const clean = String(key || '').trim();
    if (!clean) {
        try {
            file.delete(null);
        } catch { /* nothing to delete */ }

        return true;
    }

    const body = [
        '# ShulGo API key for the JewBuntu widget.',
        '# Make one in ShulGo: Admin › System › API & apps.',
        `api-key=${clean}`,
        '',
    ].join('\n');

    try {
        file.replace_contents(new TextEncoder().encode(body), null, false,
            Gio.FileCreateFlags.REPLACE_DESTINATION | Gio.FileCreateFlags.PRIVATE, null);
        GLib.chmod(path, 0o600);

        return true;
    } catch (e) {
        logError(e, 'ShulGo: could not save the API key');

        return false;
    }
}

export function looksLikeKey(key) {
    return /^sg_live_[0-9a-f]{40}$/.test(String(key || '').trim());
}

/**
 * A friendlier face on Gio.Settings, so neither half has to remember key names. The caller hands in the
 * Gio.Settings it already has: a Shell extension gets one from its own schema directory, the app from the
 * user's.
 */
export class Config {
    /** @param {Gio.Settings} settings */
    constructor(settings) {
        this.settings = settings;
        this._handlers = [];
    }

    get baseUrl() { return this.settings.get_string('api-base-url'); }
    get useGeolocation() { return this.settings.get_boolean('use-geolocation'); }
    get place() { return this.settings.get_string('place'); }
    get windowMinutes() { return this.settings.get_int('window-minutes'); }
    get travelMode() { return this.settings.get_string('travel-mode'); }
    get tefillah() { return this.settings.get_string('tefillah'); }
    get refreshSeconds() { return this.settings.get_int('refresh-seconds'); }
    get panelText() { return this.settings.get_string('panel-text'); }
    get glass() { return this.settings.get_string('glass'); }
    get panelPosition() { return this.settings.get_string('panel-position'); }
    get mikvahFor() { const v = this.settings.get_string('mikvah-for'); return v === 'all' ? null : v; }
    get listLength() { return this.settings.get_int('list-length'); }
    get lastTab() { return this.settings.get_string('last-tab'); }
    get seenTimezone() { return this.settings.get_string('seen-timezone'); }
    get locationStatus() { return this.settings.get_string('location-status'); }

    set lastTab(name) { this.settings.set_string('last-tab', name); }
    set seenTimezone(zone) { this.settings.set_string('seen-timezone', zone || ''); }
    set locationStatus(how) { this.settings.set_string('location-status', how || 'unknown'); }
    set tefillah(name) { this.settings.set_string('tefillah', name); }

    /** The point we last settled on, or null when we've never had one. */
    get point() {
        const lat = this.settings.get_double('latitude');
        const lng = this.settings.get_double('longitude');
        if (!lat && !lng)
            return null;

        return { lat, lng, label: this.settings.get_string('location-label') || 'your location' };
    }

    /** Remembers a point so the widget can draw something straight away next time it starts. */
    rememberPoint({ lat, lng, label }) {
        this.settings.set_double('latitude', lat);
        this.settings.set_double('longitude', lng);
        this.settings.set_string('location-label', label || '');
    }

    /** Calls back whenever one of these keys changes. */
    watch(keys, callback) {
        for (const key of keys) {
            const id = this.settings.connect(`changed::${key}`, () => callback(key));
            this._handlers.push(id);
        }
    }

    destroy() {
        for (const id of this._handlers)
            this.settings.disconnect(id);
        this._handlers = [];
    }
}
