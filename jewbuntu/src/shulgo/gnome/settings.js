/* Settings shared by the top-bar widget and the ShulGo app.
 *
 * Everything but the API key lives in GSettings (schema com.shulgo.ShulGo), so a change in either half
 * shows up in the other at once. The key itself is kept in ~/.config/jewbuntu/shulgo.conf with owner-only
 * permissions, because dconf is world-readable inside the session and an API key shouldn't be.
 */

import GLib from 'gi://GLib';
import Gio from 'gi://Gio';

export const SCHEMA_ID = 'com.shulgo.ShulGo';

/** Where the settings used to live, before jewbuntu.org turned out not to be ours. */
export const OLD_SCHEMA_ID = 'org.jewbuntu.shulgo';

/**
 * Brings settings across from the old namespace, once.
 *
 * Renaming a GSettings schema does not move anybody's data. The values stay in dconf under
 * /org/jewbuntu/shulgo/, and once the old schema file is gone nothing can read them, because
 * GSettings will not touch a path it has no schema for. So the old schema is still shipped as a
 * shim (schemas/org.jewbuntu.shulgo.gschema.xml) purely so this function can read it one last time.
 *
 * Only keys the person actually changed are copied: get_user_value() answers null for anything still
 * at its default, so an upgrade cannot resurrect an old default over a new one. Keys that no longer
 * exist, or whose type has changed, are skipped rather than guessed at.
 *
 * Nothing here is allowed to stop the widget starting. A migration that fails is a lost preference;
 * a migration that throws during enable() is a widget that does not appear at all.
 *
 * @param {Gio.Settings} settings the new, current settings
 * @returns {number} how many keys were brought across
 */
export function migrateFromOldNamespace(settings) {
    try {
        if (settings.get_boolean('migrated-from-jewbuntu'))
            return 0;
    } catch {
        // An older schema without the flag: there is nothing this function can safely do.
        return 0;
    }

    let moved = 0;
    try {
        // Deliberately NOT `new Gio.Settings({schema_id})`. GSettings treats an unknown schema as a
        // programming error and aborts the whole process — it does not throw something catchable —
        // so the schema has to be looked up first, and most machines will not have the old one.
        const source = Gio.SettingsSchemaSource.get_default();
        const oldSchema = source ? source.lookup(OLD_SCHEMA_ID, true) : null;

        if (oldSchema) {
            const old = new Gio.Settings({ settings_schema: oldSchema });
            const mine = settings.settings_schema;

            for (const key of oldSchema.list_keys()) {
                if (key === 'migrated-from-jewbuntu' || !mine.has_key(key))
                    continue;

                // null means "still the default here", which is nothing worth carrying over.
                const value = old.get_user_value(key);
                if (!value)
                    continue;

                // A type that changed between the two would make set_value fail loudly; skipping is
                // the honest answer, since we have no idea what the old value should become.
                if (!value.get_type().equal(mine.get_key(key).get_value_type()))
                    continue;

                settings.set_value(key, value);
                moved++;
            }
        }
    } catch (e) {
        try {
            console.warn(`ShulGo: could not bring the old settings across: ${e}`);
        } catch { /* nowhere to log */ }
    }

    // Set even when nothing moved, and even after a failure. Retrying on every start would mean a
    // person who deliberately changed a setting back had it overwritten again the next morning.
    try {
        settings.set_boolean('migrated-from-jewbuntu', true);
    } catch { /* nothing more to be done */ }

    return moved;
}

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
        '# Ask your ShulGo administrator for a key.',
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
        // Both halves build a Config, so this is the one place that catches either of them starting
        // first. After the first run it is a single boolean read.
        migrateFromOldNamespace(settings);
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
