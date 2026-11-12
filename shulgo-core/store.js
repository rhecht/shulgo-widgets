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

import { minutesUntil, nowUnix, systemTimezone, todayIso, toUnix } from './format.js';

/** When requests keep failing, wait longer each time rather than hammering a network that isn't there. */
const BACKOFF_CAP = 900; // 15 minutes

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
     * @param {{isOnline: () => boolean, onChange: (cb: (online: boolean) => void) => Function}} [network]
     *        what the machine says about the network, so we can stop trying while it's down and start
     *        again the moment it comes back.
     */
    constructor(api, config, locator, network = null) {
        this._api = api;
        this._config = config;
        this._locator = locator;
        this._network = network;
        this._listeners = new Set();
        this._refreshTimer = null;
        this._tickTimer = null;
        this._busy = false;
        this._failures = 0;
        this._unwatchNetwork = network?.onChange?.((online) => this._networkChanged(online)) ?? null;

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

            // How much of this is still to be trusted.
            offline: false,       // the machine says there's no network
            stale: false,         // what's shown was written down earlier, not fetched just now
            staleSince: null,     // unix seconds: when it was taken
            why: null,            // 'offline' | 'unreachable' | null
            zmanimForDate: null,  // the date the zmanim were worked out for
            nextTryAt: null,      // unix seconds: when we'll try again

            // The clock says we're somewhere else than when the place was last set. A laptop changes
            // its time zone when it travels, which is a free and dependable hint that "near Toronto"
            // may no longer be what you want — and it needs no location service to notice.
            movedTimezone: null,
        };

        this._noteTimezone();
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

    /** Starts the half-minute tick and the refresh that follows it. */
    start() {
        this.stop();
        this._running = true;
        this._tickTimer = setInterval(() => {
            this._dropPast();
            this._noteTimezone();
            this._emit('tick');
        }, 30_000);
        this._scheduleRefresh();
    }

    stop() {
        this._running = false;
        if (this._tickTimer)
            clearInterval(this._tickTimer);
        if (this._refreshTimer)
            clearTimeout(this._refreshTimer);
        this._tickTimer = null;
        this._refreshTimer = null;
    }

    /** The refresh interval changed. */
    restartTimers() {
        if (this._running)
            this.start();
    }

    /**
     * The next attempt. Normally the interval from settings; after a run of failures, longer each time
     * up to a quarter of an hour, because a network that isn't there won't be there a second sooner for
     * being asked more often.
     */
    _scheduleRefresh() {
        if (!this._running)
            return;
        if (this._refreshTimer)
            clearTimeout(this._refreshTimer);

        const base = Math.max(60, this._config.refreshSeconds);
        const wait = this._failures === 0
            ? base
            : Math.min(base * (2 ** Math.min(this._failures, 6)), BACKOFF_CAP);

        this.state.nextTryAt = nowUnix() + wait;
        this._refreshTimer = setTimeout(() => {
            this._refreshTimer = null;
            this.refresh().finally(() => this._scheduleRefresh());
        }, wait * 1000);
    }

    /** The machine's network came or went. */
    _networkChanged(online) {
        this.state.offline = !online;
        if (!online) {
            this._emit('changed');

            return;
        }
        // Back from the dead: try again at once rather than waiting out a backoff.
        this._failures = 0;
        this.refresh({ fresh: true }).finally(() => this._scheduleRefresh());
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
            // An answer that came out of the cache still counts as ok — it just isn't fresh, and the
            // panel is told so rather than being handed an error and an empty list.
            if (minyanim.ok) {
                this.state.minyanim = Array.isArray(minyanim.data) ? minyanim.data : [];
                this.state.minyanimMeta = minyanim.meta ?? {};
                this.state.error = null;
                this.state.stale = Boolean(minyanim.stale);
                this.state.staleSince = minyanim.stale ? minyanim.cachedAt : null;
                this.state.why = minyanim.stale ? (minyanim.why === 'offline' ? 'offline' : 'unreachable') : null;
                this.state.offline = minyanim.why === 'offline';
                this._failures = minyanim.stale ? this._failures + 1 : 0;
            } else {
                this.state.error = { code: minyanim.code, message: minyanim.message };
                this.state.stale = false;
                this.state.why = minyanim.code === 'offline' ? 'offline' : 'unreachable';
                this.state.offline = minyanim.code === 'offline';
                this._failures += 1;
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
                // Zmanim belong to one day. Yesterday's, handed back while we're offline, are simply
                // wrong, so the day they were worked out for travels with them and the panel checks it.
                this.state.zmanimForDate = this.state.zmanimMeta.date ?? null;
            }

            if (calendar.ok) {
                const wanted = this.state.zmanimMeta.date ?? todayIso();
                this.state.today = (calendar.data || []).find((d) => d.date === wanted) ?? null;
            }

            this._dropPast();
            // "Updated" means the last time ShulGo actually answered. A failed attempt, and an answer
            // served out of the cache, are both something else — the panel says which.
            if (!this.state.error && !this.state.stale)
                this.state.updatedAt = nowUnix();
        } finally {
            this._busy = false;
            this.state.loading = false;
            this._emit('changed');
        }
    }

    /**
     * Has the machine's time zone changed since the place was set? The first run just records where we
     * are, so nobody is asked about a journey they didn't make.
     */
    _noteTimezone() {
        const now = systemTimezone();
        if (!now)
            return;
        const seen = this._config.seenTimezone;
        if (!seen) {
            this._config.seenTimezone = now;

            return;
        }
        this.state.movedTimezone = now === seen ? null : now;
    }

    /** "Yes, I'm here now" or "no, leave it" — either way, stop asking about this journey. */
    settleTimezone() {
        const now = systemTimezone();
        if (now)
            this._config.seenTimezone = now;
        this.state.movedTimezone = null;
        this._emit('changed');
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

    /** True when the zmanim on hand were worked out for a different day — so not today's. */
    get zmanimOutOfDate() {
        return Boolean(this.state.zmanimForDate) && this.state.zmanimForDate !== todayIso();
    }

    /** Is there anything at all to show, fresh or not? */
    get hasAnything() {
        return this.state.minyanim.length > 0 || Object.keys(this.state.zmanim).length > 0;
    }

    /** Minutes until the headline minyan, worked out right now. */
    get nextMinyanIn() {
        const next = this.headline;

        return next ? minutesUntil(next.starts_at) : null;
    }

    destroy() {
        this.stop();
        this._unwatchNetwork?.();
        this._unwatchNetwork = null;
        this._listeners.clear();
        this._locator?.destroy?.();
    }
}
