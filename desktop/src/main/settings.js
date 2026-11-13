/* Settings for the desktop app.
 *
 * Everything but the API key goes in settings.json under the app's own data directory. The key is kept
 * apart, in shulgo.conf with owner-only permissions, for the same reason the JewBuntu build keeps it out
 * of dconf: a key shouldn't sit in a file the rest of the session can read.
 *
 * The shape matches the GNOME build's GSettings schema key for key, so the two can be talked about in
 * the same words — and so a shared settings page could read either one later.
 */

import { app } from 'electron';
import { chmodSync, mkdirSync, readFileSync, writeFileSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';

const DEFAULTS = {
    apiBaseUrl: 'https://shulgo.com/api/v1',
    place: '',
    latitude: 0,
    longitude: 0,
    locationLabel: '',
    windowMinutes: 120,
    travelMode: 'drive',
    tefillah: 'next',
    refreshSeconds: 300,
    menuBarText: 'full',      // full | countdown | time | icon
    glass: 'tint',            // tint | frosted | solid
    mikvahFor: 'all',
    lastTab: 'minyanim',
    seenTimezone: '',
    listLength: 8,
    openAtLogin: false,
};

export class Settings {
    constructor() {
        this._dir = app.getPath('userData');
        this._file = join(this._dir, 'settings.json');
        this._keyFile = join(this._dir, 'shulgo.conf');
        this._values = { ...DEFAULTS };
        this._watchers = new Set();
        this._load();
    }

    _load() {
        try {
            const saved = JSON.parse(readFileSync(this._file, 'utf8'));
            for (const [k, v] of Object.entries(saved)) {
                if (k in DEFAULTS)
                    this._values[k] = v;
            }
        } catch {
            // No settings yet: the defaults stand.
        }
    }

    _save() {
        try {
            mkdirSync(this._dir, { recursive: true });
            writeFileSync(this._file, `${JSON.stringify(this._values, null, 2)}\n`, 'utf8');
        } catch (e) {
            console.error('ShulGo: could not save settings', e);
        }
    }

    get all() {
        return { ...this._values };
    }

    get(key) {
        return this._values[key];
    }

    /** Sets one or more values, saves, and tells anyone watching which keys moved. */
    set(changes) {
        const moved = [];
        for (const [key, value] of Object.entries(changes)) {
            if (!(key in DEFAULTS) || this._values[key] === value)
                continue;
            this._values[key] = value;
            moved.push(key);
        }
        if (!moved.length)
            return [];
        this._save();
        for (const watcher of [...this._watchers])
            watcher(moved);

        return moved;
    }

    watch(callback) {
        this._watchers.add(callback);

        return () => this._watchers.delete(callback);
    }

    // ---- the API key -------------------------------------------------------------------------

    /** SHULGO_API_KEY in the environment wins, so a test run needn't touch the saved one. */
    get apiKey() {
        const fromEnv = process.env.SHULGO_API_KEY;
        if (fromEnv)
            return fromEnv.trim();
        try {
            const text = readFileSync(this._keyFile, 'utf8');
            const match = text.match(/^\s*api-key\s*=\s*(\S+)\s*$/m);

            return match ? match[1] : '';
        } catch {
            return '';
        }
    }

    set apiKey(key) {
        const clean = String(key || '').trim();
        try {
            mkdirSync(this._dir, { recursive: true });
            if (!clean) {
                unlinkSync(this._keyFile);

                return;
            }
            writeFileSync(this._keyFile, [
                '# ShulGo API key.',
                '# Ask your ShulGo administrator for a key, or request one at https://shulgo.com/developers/request.',
                `api-key=${clean}`,
                '',
            ].join('\n'), { mode: 0o600 });
            chmodSync(this._keyFile, 0o600);
        } catch (e) {
            if (e?.code !== 'ENOENT')
                console.error('ShulGo: could not save the API key', e);
        }
    }

    get keyFilePath() {
        return this._keyFile;
    }

    /**
     * The shape core/store.js wants. It reads plain getters, so this adapter is all that stands between
     * the shared store and however a platform happens to keep its settings.
     */
    asConfig() {
        const values = this._values;
        // Captured, because inside the object below "this" is the object, not the Settings.
        const save = (changes) => this.set(changes);

        return {
            get baseUrl() { return values.apiBaseUrl; },
            get windowMinutes() { return values.windowMinutes; },
            get travelMode() { return values.travelMode; },
            get tefillah() { return values.tefillah; },
            get refreshSeconds() { return values.refreshSeconds; },
            get mikvahFor() { return values.mikvahFor === 'all' ? null : values.mikvahFor; },
            get listLength() { return values.listLength; },
            get place() { return values.place; },
            get seenTimezone() { return values.seenTimezone; },
            set seenTimezone(zone) { save({ seenTimezone: zone || '' }); },
            get point() {
                if (!values.latitude && !values.longitude)
                    return null;

                return { lat: values.latitude, lng: values.longitude, label: values.locationLabel || 'your location' };
            },
            rememberPoint: ({ lat, lng, label }) => save({ latitude: lat, longitude: lng, locationLabel: label || '' }),
        };
    }
}

export function looksLikeKey(key) {
    return /^sg_live_[0-9a-f]{40}$/.test(String(key || '').trim());
}
