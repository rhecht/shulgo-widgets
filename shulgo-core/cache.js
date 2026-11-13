/* What we keep for when ShulGo can't be reached.
 *
 * The widget is a thing you glance at on the way out of the door, so "no network" must not mean "no
 * answer". Every good answer is written down, and when a request fails the last one is handed back
 * instead, marked as old so nothing pretends to be current.
 *
 * Plain JavaScript, like the rest of core/: it is given a storage adapter — a file on GNOME, a file in
 * the app's data directory on the Mac — and does not care which.
 */

/**
 * How old a written-down answer may be and still be worth showing when we're offline. These are
 * generous because the alternative is a blank panel; honesty about the age is the UI's job, and the
 * store throws out minyanim whose time has passed regardless.
 */
const OFFLINE_TTL = {
    next: 86400,          // a day — past minyanim drop out on their own
    events: 604800,       // a week
    mikvaos: 2592000,     // a month; they barely change
    zmanim: 86400,        // a day, and only for the day they were worked out for
    calendar: 2592000,    // a month
    places: 2592000,      // a month
    shuls: 604800,
    shiurim: 604800,    // a week; a weekly shiur is still on next week
};

/** Enough room for a few places' worth of every list, and no more. */
const MAX_ENTRIES = 60;

const seconds = () => Date.now() / 1000;

export class Cache {
    /**
     * @param {{read: () => (string|null), write: (text: string) => void}|null} storage
     *        null is allowed: the cache then simply never remembers anything across restarts.
     */
    constructor(storage = null) {
        this._storage = storage;
        this._entries = new Map(); // url -> {at, value}
        this._dirty = false;
        this._load();
    }

    _load() {
        if (!this._storage)
            return;
        try {
            const text = this._storage.read();
            if (!text)
                return;
            const saved = JSON.parse(text);
            if (saved?.version !== 1 || !saved.entries)
                return;
            for (const [url, entry] of Object.entries(saved.entries)) {
                if (entry && typeof entry.at === 'number' && 'value' in entry)
                    this._entries.set(url, entry);
            }
        } catch {
            // A cache that can't be read is not worth a word to anyone; we just start without one.
        }
    }

    save() {
        if (!this._storage || !this._dirty)
            return;
        this._dirty = false;
        try {
            // Newest first, so the cap throws away what matters least.
            const sorted = [...this._entries.entries()].sort((a, b) => b[1].at - a[1].at).slice(0, MAX_ENTRIES);
            this._entries = new Map(sorted);
            this._storage.write(JSON.stringify({ version: 1, entries: Object.fromEntries(sorted) }));
        } catch (e) {
            try {
                console.warn('ShulGo: could not write the offline cache', e);
            } catch { /* nowhere to log */ }
        }
    }

    /** @returns {{at: number, value: any}|null} */
    get(url) {
        return this._entries.get(url) ?? null;
    }

    /**
     * The written-down answer for this request, if there is one and it isn't past the point of being
     * worth showing.
     *
     * @returns {{at: number, value: any}|null}
     */
    getUsable(url, path, now = seconds()) {
        const entry = this.get(url);
        if (!entry)
            return null;

        return now - entry.at <= (OFFLINE_TTL[path] ?? 86400) ? entry : null;
    }

    set(url, value) {
        this._entries.set(url, { at: seconds(), value });
        this._dirty = true;
    }

    clear() {
        this._entries.clear();
        this._dirty = true;
        this.save();
    }
}
