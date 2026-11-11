/* ShulGo API v1 client.
 *
 * Plain JavaScript: it asks for an HTTP "transport" rather than reaching for one, so the same file serves
 * the GNOME widget (libsoup), a Mac or Windows build (fetch) and a phone build. Every call answers
 * {ok: true, data, meta} or {ok: false, code, message, status} — nothing throws at the caller, because a
 * widget in the top bar must never break the bar over a flaky network.
 *
 * Caching: each path+query is kept for its own little while (minyanim go stale fast, mikvaos don't), and
 * two requests for the same thing at once share one answer.
 */

/** How long an answer stays good, in seconds. */
const TTL = {
    next: 60,
    events: 600,
    mikvaos: 3600,
    zmanim: 21600,
    calendar: 43200,
    places: 300,
    shuls: 300,
};

/** What we tell the caller when something went wrong and the server didn't say. */
const FALLBACK = 'ShulGo couldn’t be reached.';

const seconds = () => Date.now() / 1000;

export class ShulGoApi {
    /**
     * @param {object} opts
     * @param {string} opts.baseUrl     e.g. https://shulgo.com/api/v1
     * @param {string} opts.apiKey      sg_live_… (Admin › System › API & apps)
     * @param {Function} opts.transport (url, {headers, timeout}) => {status, body, headers}
     * @param {number} [opts.timeout]   seconds
     * @param {import('./cache.js').Cache} [opts.cache]
     *        where good answers are written down, so a request that fails can be answered from the last
     *        one instead of with nothing. Leave it out and the client simply has no memory.
     * @param {() => boolean} [opts.isOnline]
     *        what the machine says about the network. When it says no, we don't sit through a timeout
     *        to find out — we go straight to what was written down.
     */
    constructor({ baseUrl, apiKey, transport, timeout = 15, cache = null, isOnline = null } = {}) {
        if (typeof transport !== 'function')
            throw new Error('ShulGoApi needs a transport; see gnome/transport.js.');

        this._base = String(baseUrl || 'https://shulgo.com/api/v1').replace(/\/+$/, '');
        this._key = apiKey || '';
        this._transport = transport;
        this._timeout = timeout;
        this._cache = new Map();    // url -> {at, value}; this minute's answers
        this._kept = cache;         // the same answers, written down for when we're offline
        this._isOnline = isOnline;
        this._inFlight = new Map(); // url -> Promise
    }

    /** The key or the base URL changed: start clean. */
    reconfigure({ baseUrl, apiKey } = {}) {
        if (baseUrl !== undefined)
            this._base = String(baseUrl || '').replace(/\/+$/, '') || this._base;
        if (apiKey !== undefined)
            this._key = apiKey || '';
        this.forget();
    }

    /** Forgets this minute's answers. What's written down for offline use is left alone. */
    forget() {
        this._cache.clear();
    }

    /** Throws away the written-down answers too. */
    forgetEverything() {
        this._cache.clear();
        this._kept?.clear();
    }

    get hasKey() {
        return /^sg_live_[0-9a-f]{40}$/.test(this._key);
    }

    /** The public site behind this API, for "open in ShulGo" links. */
    get siteUrl() {
        return this._base.replace(/\/api\/v1$/, '') || 'https://shulgo.com';
    }

    // ---- the endpoints the widget uses -------------------------------------------------------

    /** Minyanim starting soon near a point, soonest first. */
    next({ lat, lng, tefillah = 'next', windowMin = 120, mode = 'drive' }) {
        const q = { lat, lng, window: windowMin, mode };
        if (tefillah && tefillah !== 'next')
            q.tefillah = tefillah;

        return this._get('next', q);
    }

    /** Upcoming events within 50 miles (or everywhere, with no point). */
    events({ lat, lng, page = 1 } = {}) {
        const q = { page };
        if (lat !== undefined && lat !== null) {
            q.lat = lat;
            q.lng = lng;
        }

        return this._get('events', q);
    }

    /** Mikvaos near a point. ShulGo's own apps only — another key gets 403 forbidden. */
    mikvaos({ lat, lng, forWhom = null } = {}) {
        const q = { lat, lng };
        if (forWhom)
            q.for = forWhom;

        return this._get('mikvaos', q);
    }

    /** Today's zmanim (or another date) for a point. */
    zmanim({ lat, lng, date = null } = {}) {
        const q = { lat, lng };
        if (date)
            q.date = date;

        return this._get('zmanim', q);
    }

    /** A month of Hebrew dates, yomim tovim and candle lighting. */
    calendar({ lat, lng, month = null } = {}) {
        const q = { lat, lng };
        if (month)
            q.month = month;

        return this._get('calendar', q);
    }

    /** Cities, neighborhoods and zip codes, for the place box. */
    places(q) {
        const text = String(q || '').trim();
        if (text.length < 2)
            return Promise.resolve({ ok: true, data: [], meta: {} });

        return this._get('places', { q: text, limit: 8 });
    }

    // ---- the plumbing ------------------------------------------------------------------------

    _url(path, query) {
        const parts = [];
        for (const [k, v] of Object.entries(query || {})) {
            if (v === undefined || v === null || v === '')
                continue;
            parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
        }

        return `${this._base}/${path}${parts.length ? `?${parts.join('&')}` : ''}`;
    }

    /**
     * One GET, cached and de-duplicated.
     *
     * @param {string} path
     * @param {object} query
     * @param {object} [opts]
     * @param {boolean} [opts.fresh] ignore anything cached
     */
    async _get(path, query, { fresh = false } = {}) {
        const url = this._url(path, query);
        const now = seconds();
        const ttl = TTL[path] ?? 60;

        if (!fresh) {
            const hit = this._cache.get(url);
            if (hit && now - hit.at < ttl)
                return { ...hit.value, cachedAt: hit.at };

            const waiting = this._inFlight.get(url);
            if (waiting)
                return waiting;
        }

        if (!this.hasKey) {
            return {
                ok: false,
                code: 'no_key',
                message: 'Add your ShulGo API key in Settings to see minyanim.',
                status: 0,
            };
        }

        // No point sitting through a fifteen-second timeout to be told what the machine already knows.
        if (this._isOnline && this._isOnline() === false) {
            return this._fallback(url, path, {
                ok: false, code: 'offline', message: 'This computer is offline.', status: 0,
            });
        }

        const job = this._fetch(url).then((value) => {
            this._inFlight.delete(url);
            // Only good answers are kept; an error should be retried, not remembered.
            if (value.ok) {
                this._cache.set(url, { at: seconds(), value });
                this._kept?.set(url, { data: value.data, meta: value.meta });

                return value;
            }

            return this._fallback(url, path, value);
        }).catch((e) => {
            this._inFlight.delete(url);

            return this._fallback(url, path, {
                ok: false, code: 'network', message: e?.message || FALLBACK, status: 0,
            });
        });
        this._inFlight.set(url, job);

        return job;
    }

    /**
     * A request has failed. If we wrote down a good answer to the same question, hand that back instead
     * of nothing — marked `stale`, with when it was taken and what went wrong, so the panel can say so
     * plainly rather than pretending.
     *
     * An answer the server itself refused — a bad key, a key not allowed to read mikvaos — is not a
     * network problem and is never papered over with an old one.
     */
    _fallback(url, path, failure) {
        const serverSaidNo = failure.status >= 400 && failure.status < 500;
        if (serverSaidNo)
            return failure;

        const kept = this._kept?.getUsable(url, path);
        if (!kept)
            return failure;

        return {
            ok: true,
            data: kept.value.data,
            meta: kept.value.meta ?? {},
            status: failure.status,
            stale: true,
            cachedAt: kept.at,
            why: failure.code,
            whyMessage: failure.message,
        };
    }

    async _fetch(url) {
        let answer;
        try {
            answer = await this._transport(url, {
                headers: { 'X-Api-Key': this._key, Accept: 'application/json' },
                timeout: this._timeout,
            });
        } catch (e) {
            return {
                ok: false,
                code: e?.code === 'timeout' ? 'timeout' : 'network',
                message: e?.message || FALLBACK,
                status: 0,
            };
        }

        const status = Number(answer?.status ?? 0);
        let body = {};
        try {
            body = answer?.body ? JSON.parse(answer.body) : {};
        } catch {
            body = {};
        }

        if (status >= 200 && status < 300 && body && 'data' in body)
            return { ok: true, data: body.data, meta: body.meta ?? {}, status };

        const err = body?.error ?? {};
        const retryAfter = Number(answer?.headers?.get?.('Retry-After') || 0) || null;

        return {
            ok: false,
            status,
            code: err.code || `http_${status}`,
            message: err.message || this._httpMessage(status),
            retryAfter,
        };
    }

    _httpMessage(status) {
        if (status === 0)
            return FALLBACK;
        if (status === 401)
            return 'That ShulGo API key isn’t valid. Check it in Settings.';
        if (status === 403)
            return 'This ShulGo API key isn’t allowed to read that.';
        if (status === 429)
            return 'ShulGo is asking us to slow down. Trying again shortly.';
        if (status >= 500)
            return 'ShulGo had a problem answering. Trying again shortly.';

        return `ShulGo answered ${status}.`;
    }
}
