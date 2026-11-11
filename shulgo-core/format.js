/* Turning ShulGo's JSON into the words and shapes the widget shows.
 *
 * Plain JavaScript on purpose: no GLib, no GTK, no Shell. The top-bar widget and the ShulGo app share it
 * today, and a Mac, Windows, iOS or Android build can take this file as it stands.
 */

/** The API sends codes; these are the words ShulGo itself uses. */
const TEFILLAH = {
    shacharis: 'Shacharis',
    mincha: 'Mincha',
    maariv: 'Maariv',
    selichos: 'Selichos',
    musaf: 'Musaf',
    neilah: 'Neilah',
};

/** Who a mikvah is for. */
const FOR_WHOM = { women: 'Women', men: 'Men', keilim: 'Keilim' };

function titleCase(text) {
    const s = String(text ?? '');

    return s.charAt(0).toUpperCase() + s.slice(1);
}

export function tefillahLabel(code) {
    if (!code)
        return 'Minyan';

    return TEFILLAH[code] ?? titleCase(code);
}

export function forWhomLabel(code) {
    return FOR_WHOM[code] ?? titleCase(code);
}

/** Seconds since the epoch for an ISO 8601 time with an offset, or null. */
export function toUnix(iso) {
    if (!iso)
        return null;
    const ms = Date.parse(iso);

    return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}

export function nowUnix() {
    return Math.floor(Date.now() / 1000);
}

/**
 * Minutes from now until an ISO time, worked out locally so a countdown can tick between requests
 * instead of asking the server again every minute.
 */
export function minutesUntil(iso, now = nowUnix()) {
    const at = toUnix(iso);
    if (at === null)
        return null;

    return Math.floor((at - now) / 60);
}

/** 0 → "now", 6 → "in 6 min", 95 → "in 1h 35m", −4 → "4 min ago". */
export function countdown(minutes) {
    if (minutes === null || minutes === undefined)
        return '';
    if (minutes === 0)
        return 'now';
    if (minutes < 0) {
        const past = Math.abs(minutes);

        return past < 60 ? `${past} min ago` : `${Math.floor(past / 60)}h ago`;
    }
    if (minutes < 60)
        return `in ${minutes} min`;
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;

    return m ? `in ${h}h ${m}m` : `in ${h}h`;
}

/** The short form for the top bar: "6m", "1h35". */
export function countdownShort(minutes) {
    if (minutes === null || minutes === undefined)
        return '';
    if (minutes <= 0)
        return 'now';
    if (minutes < 60)
        return `${minutes}m`;
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;

    return m ? `${h}h${String(m).padStart(2, '0')}` : `${h}h`;
}

/** 0.49 → "0.5 mi"; 12.4 → "12 mi". */
export function miles(value) {
    if (value === null || value === undefined)
        return '';
    const n = Number(value);
    if (!Number.isFinite(n))
        return '';

    return n < 10 ? `${n.toFixed(1)} mi` : `${Math.round(n)} mi`;
}

/**
 * "about 5 min drive" / "12 min walk", or nothing when ShulGo couldn't route it.
 *
 * travel_min always matches the mode that was asked for. The item's own travel_walk flag means something
 * narrower — you asked to drive, but it's near enough to walk — so the words follow the mode first, the
 * way shulgo.com's own pages put it.
 */
export function travel(item, mode = 'drive') {
    const min = item?.travel_min;
    if (min === null || min === undefined)
        return '';

    return mode === 'walk' || item.travel_walk ? `${min} min walk` : `about ${min} min drive`;
}

/**
 * How a minyan stands against the clock, for the colour of its dot and the panel pill:
 *   'comfortable' — plenty of room      'tight' — you'd have to leave now
 *   'missed'      — can't be made       'unknown' — ShulGo couldn't route it
 */
export function urgency(item) {
    if (item?.can_make_it === false)
        return 'missed';
    if (item?.can_make_it === null || item?.can_make_it === undefined)
        return 'unknown';
    const buffer = Number(item.buffer_min);

    return Number.isFinite(buffer) && buffer <= 5 ? 'tight' : 'comfortable';
}

/** The one line under a minyan's name: shul, distance, how long to get there, nusach. */
export function minyanSubtitle(item, mode = 'drive') {
    const bits = [];
    if (item.kind === 'live')
        bits.push(item.live?.notes ? 'Forming now' : 'Forming nearby');
    else if (item.shul?.display_name)
        bits.push(item.shul.display_name);

    const d = miles(item.distance_miles);
    if (d)
        bits.push(d);
    const t = travel(item, mode);
    if (t)
        bits.push(t);
    if (item.nusach)
        bits.push(item.nusach);

    return bits.join(' · ');
}

/** The second line, when there is one worth showing: a note, a one-off change, a standing minyan's venue. */
export function minyanNote(item) {
    const bits = [];
    if (item.kind === 'standing' && item.shul?.venue_label)
        bits.push(item.shul.venue_label);
    if (item.status && item.status !== 'scheduled')
        bits.push(titleCase(item.status));
    if (item.notes)
        bits.push(item.notes);

    return bits.join(' · ');
}

/** Where to send a map app for this minyan. */
export function minyanDestination(item) {
    if (item.kind === 'live')
        return item.live?.directions ?? null;
    const loc = item.shul?.location;
    if (loc)
        return `${loc.lat},${loc.lng}`;

    return item.shul?.address?.formatted ?? null;
}

/** A map link that works on every desktop and phone we build for. */
export function mapsUri(destination) {
    if (!destination)
        return null;

    return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(destination)}`;
}

/** Midnight local time for a Y-M-D string, as a Date. */
function dateOnly(isoDate) {
    const [y, m, d] = String(isoDate || '').split('-').map(Number);
    if (!y || !m || !d)
        return null;

    return new Date(y, m - 1, d, 12, 0, 0);
}

/** A date as Y-M-D in local time; today by default. */
export function todayIso(now = new Date()) {
    const pad = (n) => String(n).padStart(2, '0');

    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** "Tue 17 Nov" for an event's date, and "Today" / "Tomorrow" when it's close. */
export function eventDate(isoDate) {
    const when = dateOnly(isoDate);
    if (!when)
        return String(isoDate ?? '');
    const today = dateOnly(todayIso());
    const days = Math.round((when - today) / 86400000);
    if (days === 0)
        return 'Today';
    if (days === 1)
        return 'Tomorrow';

    const options = days < 180 && days > -180
        ? { weekday: 'short', day: 'numeric', month: 'short' }
        : { day: 'numeric', month: 'short', year: 'numeric' };
    try {
        return new Intl.DateTimeFormat(undefined, options).format(when);
    } catch {
        return isoDate;
    }
}

/** Zmanim come back as an object; this puts them in clock order and says which is still ahead. */
export function zmanimList(data, now = nowUnix()) {
    const rows = Object.entries(data || {})
        .filter(([, z]) => z && z.time)
        .map(([name, z]) => ({ name, ...z, at: toUnix(z.time) }))
        .filter((z) => z.at !== null)
        .sort((a, b) => a.at - b.at);
    const nextIndex = rows.findIndex((r) => r.at > now);

    return rows.map((r, i) => ({ ...r, isNext: i === nextIndex, past: r.at <= now }));
}

/** A one-line "what today is", from the calendar endpoint's day. */
export function hebrewDayLine(day) {
    if (!day)
        return '';
    const titles = (day.events || [])
        .filter((e) => e.category !== 'note' && e.category !== 'zmanim' && e.category !== 'candles')
        .map((e) => e.title);
    const extra = titles.length ? ` · ${titles.slice(0, 2).join(' · ')}` : '';

    return `${day.hebrew || ''}${extra}`.trim();
}

/**
 * The mikvah data comes from mikvah.org and their terms say so on the page. The API sends
 * {text, name, logo, url}; this is the line to print, and the URL to open.
 */
export function creditLine(attribution) {
    if (!attribution)
        return null;
    if (typeof attribution === 'string')
        return { text: attribution, url: null };

    return {
        text: [attribution.text, attribution.name].filter((x) => x).join(' ') || null,
        url: attribution.url ?? null,
    };
}

/** Candle lighting for a day, when the calendar has it. */
export function candleLighting(day) {
    const e = (day?.events || []).find((x) => x.category === 'candles' || /candle/i.test(x.title || ''));

    return e?.display_time ?? null;
}

/** Pango and Clutter both read markup, so anything from the API has to be made safe first. */
export function escapeMarkup(text) {
    return String(text ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;');
}

/** "from 1:45 PM", or "from yesterday" once it's no longer today's. */
export function takenAt(unix) {
    if (!unix)
        return '';
    const when = new Date(unix * 1000);
    const sameDay = todayIso(when) === todayIso();
    let clock;
    try {
        clock = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(when);
    } catch {
        clock = `${when.getHours()}:${String(when.getMinutes()).padStart(2, '0')}`;
    }

    if (sameDay)
        return `from ${clock}`;

    const days = Math.round((dateOnly(todayIso()) - dateOnly(todayIso(when))) / 86400000);
    if (days === 1)
        return `from yesterday, ${clock}`;

    let day;
    try {
        day = new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short' }).format(when);
    } catch {
        day = todayIso(when);
    }

    return `from ${day}, ${clock}`;
}

/**
 * What to say when ShulGo can't be reached. Kept here so the top-bar widget, the window and the Mac
 * panel all say it the same way — and say it kindly: this is a thing you glance at on your way out of
 * the door, not a server you are administering.
 *
 * @param {object} state the store's state
 * @param {boolean} hasAnything whether there is saved data to show behind the message
 * @returns {{title: string, body: string, tone: string}|null} null when all is well
 */
export function offlineNotice(state, hasAnything) {
    if (!state?.why)
        return null;

    const offline = state.why === 'offline';
    const taken = takenAt(state.staleSince);

    if (hasAnything) {
        return {
            tone: 'resting',
            title: offline ? 'You’re offline' : 'ShulGo isn’t answering',
            body: taken
                ? `This is the list ${taken}. It’ll catch up on its own.`
                : 'Showing what was here a moment ago. It’ll catch up on its own.',
        };
    }

    return {
        tone: 'resting',
        title: offline ? 'You’re offline' : 'ShulGo isn’t answering just now',
        body: offline
            ? 'Nothing saved yet to show you. The moment you’re back, this fills itself in.'
            : 'Nothing saved yet to show you. It keeps trying in the background.',
    };
}

/** "Updated 2 min ago", for the footer. */
export function updatedAgo(unix, now = nowUnix()) {
    if (!unix)
        return '';
    const mins = Math.floor((now - unix) / 60);
    if (mins <= 0)
        return 'Updated just now';
    if (mins === 1)
        return 'Updated a minute ago';
    if (mins < 60)
        return `Updated ${mins} min ago`;
    const h = Math.floor(mins / 60);

    return `Updated ${h} hour${h === 1 ? '' : 's'} ago`;
}
