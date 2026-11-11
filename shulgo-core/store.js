/* One place that knows what to show: it works out where we are, asks ShulGo for the four lists, keeps the
 * answers, and tells whoever is listening when anything changes. Both the top-bar widget and the ShulGo app
 * sit on top of this, which is what keeps the two saying the same thing.
 *
 * It fires two kinds of notice:
 *   'changed' — new data, a new place, or an error worth showing
 *   'tick'    — half a minute went by, so countdowns need redrawing (no network involved)
 *
 * Plain JavaScript, like the rest of core/: timers are setInterval, which GJS, browsers and React Native
 * all have.
 */

import { minutesUntil, nowUnix, todayIso, toUnix } from './format.js';

function warn(message, error) {
    try {
        console.warn(`ShulGo: ${message}`, error ?? '');
    } catch { /* nowhere to log */ }
}

export class Store {
    /**
     * @param {import('./api.js').ShulGoApi} api
     * @param {object} config see gnome/settings.js Config — any object with the same getters will do
     * @param {object} locator something with resolve({fresh}) => {lat, lng, label, source}|null
     */
    constructor(api, config, locator) {
        this._api = api;
        this._config = config;
        this._locator = locator;
        this._listeners = new Set();
        this._refreshTimer = null;
        this._tickTimer = null;
        this._busy = false;

        this.state = {
            loading: false,
            error: null,          // {code, message}
            place: null,          // {lat, lng, label, source}
            minyanim: [],
            minyanimMeta: {},
            events: [],
            mikvaos: [],
            mikvaosCredit: null,
            zmanim: {},
            zmanimMeta: {},
            today: null,          // the calendar's day: Hebrew date, yom tov, candle lighting
            updatedAt: null,      // unix seconds
            needsKey: !api.hasKey,
            needsPlace: false,
        };
    }

    // ---- listeners ---------------------------------------------------------------------------

    /** @returns {Function} call it to stop listening */
    connect(callback) {
        this._listeners.add(callback);

        return () => this._listeners.delete(callback);
    }

    _emit(what) {
        for (const cb of [...this._listeners]) {
            try {
                cb(what, this.state);
            } catch (e) {
                warn('a listener threw', e);
            }
        }
    }

    // ---- the clock --------------------------------------------------------------------------

    /** Starts the half-minute tick and the periodic refresh. */
    start() {
        this.stop();
        this._tickTimer = setInterval(() => {
            this._dropPast();
            this._emit('tick');
        }, 30_000);
        this._refreshTimer = setInterval(() => {
            this.refresh();
        }, Math.max(60, this._config.refreshSeconds) * 1000);
    }

    stop() {
        if (this._tickTimer)
            clearInterval(this._tickTimer);
        if (this._refreshTimer)
            clearInterval(this._refreshTimer);
        this._tickTimer = null;
        this._refreshTimer = null;
    }

    /** The refresh interval changed. */
    restartTimers() {
        if (this._tickTimer || this._refreshTimer)
            this.start();
    }

    // ---- asking ShulGo ----------------------------------------------------------------------

    /** True when what we hold is too old to show without asking again. */
    get stale() {
        if (!this.state.updatedAt)
            return true;

        return nowUnix() - this.state.updatedAt > 60;
    }

    /**
     * Fetches everything for the current place.
     *
     * @param {object} [opts]
     * @param {boolean} [opts.fresh] ignore anything cached, and ask the system for a new location fix
     */
    async refresh({ fresh = false } = {}) {
        if (this._busy)
            return;
        this._busy = true;
        this.state.loading = true;
        this.state.needsKey = !this._api.hasKey;
        this._emit('changed');

        try {
            if (this.state.needsKey) {
                this.state.error = { code: 'no_key', message: 'Add your ShulGo API key to get started.' };

                return;
            }

            const place = await this._locator.resolve({ fresh });
            if (!place) {
                this.state.needsPlace = true;
                this.state.error = { code: 'no_place', message: 'Tell ShulGo where you are to see minyanim near you.' };

                return;
            }
            this.state.needsPlace = false;
            this.state.place = place;

            const point = { lat: place.lat, lng: place.lng };
            const [minyanim, events, mikvaos, zmanim, calendar] = await Promise.all([
                this._api.next({
                    ...point,
                    tefillah: this._config.tefillah,
                    windowMin: this._config.windowMinutes,
                    mode: this._config.travelMode,
                }),
                this._api.events(point),
                this._api.mikvaos({ ...point, forWhom: this._config.mikvahFor }),
                this._api.zmanim(point),
                this._api.calendar(point),
            ]);

            // Minyanim are the one list the widget can't do without, so only that one sets the error.
            if (minyanim.ok) {
                this.state.minyanim = Array.isArray(minyanim.data) ? minyanim.data : [];
                this.state.minyanimMeta = minyanim.meta ?? {};
                this.state.error = null;
            } else {
                this.state.error = { code: minyanim.code, message: minyanim.message };
            }

            if (events.ok)
                this.state.events = events.data?.events ?? [];

            // Mikvaos are ShulGo's own apps only; a key without that right just means no mikvah tab.
            if (mikvaos.ok) {
                this.state.mikvaos = Array.isArray(mikvaos.data) ? mikvaos.data : [];
                this.state.mikvaosCredit = mikvaos.meta?.attribution ?? null;
            } else if (mikvaos.code === 'forbidden' || mikvaos.code === 'not_available') {
                this.state.mikvaos = null; // null means "this key doesn't get mikvaos": hide the tab
            }

            if (zmanim.ok) {
                this.state.zmanim = zmanim.data ?? {};
                this.state.zmanimMeta = zmanim.meta ?? {};
            }

            if (calendar.ok) {
                const wanted = this.state.zmanimMeta.date ?? todayIso();
                this.state.today = (calendar.data || []).find((d) => d.date === wanted) ?? null;
            }

            this._dropPast();
            this.state.updatedAt = nowUnix();
        } finally {
            this._busy = false;
            this.state.loading = false;
            this._emit('changed');
        }
    }

    /** Minyanim that have already started drop off the list as the minutes pass. */
    _dropPast() {
        const now = nowUnix();
        const keep = this.state.minyanim.filter((m) => {
            const at = toUnix(m.starts_at);

            return at === null || at > now - 60;
        });
        if (keep.length !== this.state.minyanim.length)
            this.state.minyanim = keep;
    }

    // ---- what the widget asks for -----------------------------------------------------------

    /** The soonest minyan still ahead, whether or not you could get there, or null. */
    get nextMinyan() {
        return this.state.minyanim[0] ?? null;
    }

    /**
     * What the top bar should say. The soonest minyan is often one you can no longer reach — a mincha
     * four minutes off with an eight-minute drive — so the headline is the soonest one you could still
     * make, and only falls back to the soonest of all when none can be made.
     */
    get headline() {
        const rows = this.state.minyanim;

        return rows.find((m) => m.can_make_it === true)
            ?? rows.find((m) => m.can_make_it === null || m.can_make_it === undefined)
            ?? this.nextMinyan;
    }

    /** Minutes until the headline minyan, worked out right now. */
    get nextMinyanIn() {
        const next = this.headline;

        return next ? minutesUntil(next.starts_at) : null;
    }

    destroy() {
        this.stop();
        this._listeners.clear();
        this._locator?.destroy?.();
    }
}
