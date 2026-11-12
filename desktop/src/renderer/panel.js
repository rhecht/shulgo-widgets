/* The panel's view.
 *
 * It holds no logic of its own worth the name: every string and every class it draws was worked out by
 * shulgo-core in the main process and arrives as one state object. That is what keeps this panel and the
 * JewBuntu widget saying the same thing.
 */

const TABS = [
    { id: 'minyanim', label: 'Minyanim' },
    { id: 'events', label: 'Events' },
    { id: 'mikvaos', label: 'Mikvaos' },
    { id: 'zmanim', label: 'Zmanim' },
];

const TEFILLOS = [
    { id: 'next', label: 'Next' },
    { id: 'shacharis', label: 'Shacharis' },
    { id: 'mincha', label: 'Mincha' },
    { id: 'maariv', label: 'Maariv' },
];

const PIN = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.6a4.4 4.4 0 0 0-4.4 4.4c0 3.1 3.84 7.7 4 7.9a.5.5 0 0 0 .78 0c.17-.2 4.02-4.8 4.02-7.9A4.4 4.4 0 0 0 8 1.6zm0 6.1a1.7 1.7 0 1 1 0-3.4 1.7 1.7 0 0 1 0 3.4z"/></svg>';

/** A cloud with a line through it — the "we can't reach it" mark, drawn soft rather than alarming. */
const CLOUD = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7.2 18.5a4.2 4.2 0 0 1-.5-8.37 5.6 5.6 0 0 1 10.6-1.48 3.9 3.9 0 0 1 3.2 3.85 3.9 3.9 0 0 1-3.9 4H7.2zm0-1.8h9.4a2.1 2.1 0 0 0 0-4.2h-.9v-.9a3.8 3.8 0 0 0-7.36-1.3l-.25.68-.72.07A2.4 2.4 0 0 0 7.2 16.7z"/><path d="M3.4 3.1a.9.9 0 0 0-1.27 1.27l17.5 17.5a.9.9 0 0 0 1.27-1.27L3.4 3.1z" opacity=".55"/></svg>';

const el = {
    where: document.getElementById('where'),
    search: document.getElementById('search'),
    searchInput: document.getElementById('search-input'),
    searchClose: document.getElementById('search-close'),
    searchResults: document.getElementById('search-results'),
    place: document.getElementById('place'),
    hebrew: document.getElementById('hebrew'),
    refresh: document.getElementById('refresh'),
    settings: document.getElementById('settings'),
    tabs: document.getElementById('tabs'),
    content: document.getElementById('content'),
    updated: document.getElementById('updated'),
    openSite: document.getElementById('open-site'),
};

let state = null;
let tab = 'minyanim';

/** A little pill beside a row's title. Built as a node, never as a string of HTML: "Women" and the rest
 * come from the API, and the same ampersand that trips Pango on the Linux build would be markup here. */
function badge(text, kind) {
    return node('span', `badge${kind ? ` ${kind}` : ''}`, text);
}

function node(tag, className, text) {
    const n = document.createElement(tag);
    if (className)
        n.className = className;
    if (text !== undefined)
        n.textContent = text;

    return n;
}

function open(url) {
    if (!url)
        return;
    window.shulgo.openExternal(url);
    window.shulgo.hidePanel();
}

// ---- looking somewhere else ----------------------------------------------------------------

let searchTimer = null;

function openSearch() {
    el.search.hidden = false;
    el.searchInput.value = '';
    el.searchResults.replaceChildren();
    el.searchInput.focus();
}

function closeSearch() {
    clearTimeout(searchTimer);
    el.search.hidden = true;
    el.searchResults.replaceChildren();
}

async function runSearch() {
    const typed = el.searchInput.value.trim();
    el.searchResults.replaceChildren();
    if (typed.length < 2)
        return;

    const matches = await window.shulgo.searchPlaces(typed);
    if (!matches.length) {
        el.searchResults.append(node('div', 'search-note',
            `ShulGo doesn’t know “${typed}”. Try a city with its state or country, or a zip.`));

        return;
    }

    for (const match of matches.slice(0, 6)) {
        const hit = node('button', 'search-hit');
        hit.append(node('span', 'search-label', match.label));
        if (match.shuls)
            hit.append(node('span', 'search-count', `${match.shuls} shul${match.shuls === 1 ? '' : 's'}`));
        hit.addEventListener('click', () => {
            window.shulgo.setPlace(match);
            closeSearch();
        });
        el.searchResults.append(hit);
    }
}

// ---- the tab strip -------------------------------------------------------------------------

function buildTabs() {
    for (const t of TABS) {
        const button = node('button', null, t.label);
        button.setAttribute('role', 'tab');
        button.dataset.tab = t.id;
        button.addEventListener('click', () => {
            tab = t.id;
            window.shulgo.set({ lastTab: t.id });
            render();
        });
        el.tabs.append(button);
    }
}

// ---- rows ----------------------------------------------------------------------------------

/** One list row: a button for the whole row, with a second little button for directions. */
function rowButton({ link, headline, children, directions }) {
    const row = node('button', `row${headline ? ' headline' : ''}`);
    for (const child of children)
        row.append(child);

    if (directions) {
        const go = node('span', 'go');
        go.innerHTML = PIN;
        go.title = 'Directions';
        go.addEventListener('click', (event) => {
            event.stopPropagation();
            open(directions);
        });
        row.append(go);
    }

    if (link)
        row.addEventListener('click', () => open(link));
    else
        row.style.cursor = 'default';

    return row;
}

function minyanRow(m) {
    const when = node('div', 'when');
    when.append(node('div', 'time', m.displayTime ?? ''));
    when.append(node('div', `countdown urgency-${m.urgency}`, m.countdown));

    const body = node('div', 'body');
    const title = node('div', 'title', m.tefillah);
    if (m.kind === 'live')
        title.append(badge('Live', 'live'));
    else if (m.kind === 'standing')
        title.append(badge('Standing'));
    if (m.urgency === 'missed')
        title.append(badge('Too far', 'missed'));
    body.append(title);
    body.append(node('div', 'sub', m.subtitle));
    if (m.note)
        body.append(node('div', 'note', m.note));

    return rowButton({
        link: m.link,
        headline: m.isHeadline,
        directions: m.directions,
        children: [node('span', `dot ${m.urgency}`), when, body],
    });
}

function eventRow(e) {
    const when = node('div', 'when');
    when.append(node('div', 'time', e.dateLabel));
    if (e.start_time)
        when.append(node('div', 'countdown', e.start_time));

    const body = node('div', 'body');
    body.append(node('div', 'title', e.title ?? ''));
    if (e.whereLine)
        body.append(node('div', 'sub', e.whereLine));

    return rowButton({ link: e.link, directions: e.directions, children: [when, body] });
}

function mikvahRow(m) {
    const body = node('div', 'body');
    const title = node('div', 'title', m.name ?? '');
    for (const whom of m.whom)
        title.append(badge(whom, 'mikvah'));
    body.append(title);
    body.append(node('div', 'sub', m.whereLine));

    return rowButton({
        link: m.url,
        directions: m.directions,
        children: [node('span', 'dot mikvah'), body],
    });
}

// ---- whole-panel states ----------------------------------------------------------------------

/**
 * The quiet strip above a list we couldn't refresh. Deliberately not an error: the list under it is
 * still worth reading, and the thing mends itself.
 */
function offlineStrip(n) {
    const strip = node('div', 'offline-strip');

    const icon = node('span', 'offline-icon');
    icon.innerHTML = CLOUD;
    strip.append(icon);

    const words = node('div', 'offline-words');
    words.append(node('div', 'offline-title', n.title));
    words.append(node('div', 'offline-body', n.body));
    strip.append(words);

    const again = node('button', 'offline-retry', 'Try now');
    again.addEventListener('click', () => window.shulgo.refresh());
    strip.append(again);

    return strip;
}

/** The whole panel, when there is nothing saved to show behind the message. */
function restingState(n) {
    const box = node('div', 'resting');

    const art = node('div', 'resting-art');
    art.innerHTML = CLOUD;
    box.append(art);

    box.append(node('div', 'resting-title', n.title));
    box.append(node('div', 'resting-body', n.body));

    const again = node('button', 'primary', 'Try now');
    again.addEventListener('click', () => window.shulgo.refresh());
    box.append(again);

    return box;
}

/** "Your clock says you're in Chicago now — still looking near Toronto?" */
function movedPrompt(moved) {
    const box = node('div', 'moved');

    const words = node('div', 'moved-words');
    words.append(node('div', 'moved-title', `Your clock says you’re in ${moved.place} now`));
    words.append(node('div', 'moved-body', state.place?.label
        ? `Still looking near ${state.place.label}.`
        : 'Where should ShulGo look?'));
    box.append(words);

    const change = node('button', 'moved-change', 'Look elsewhere');
    change.addEventListener('click', () => openSearch());
    box.append(change);

    const keep = node('button', 'moved-keep', '✕');
    keep.title = 'Stay here';
    keep.addEventListener('click', () => window.shulgo.settleTimezone());
    box.append(keep);

    return box;
}

function notice({ title, body, actionLabel, onAction, error = false }) {
    const box = node('div', `notice${error ? ' error' : ''}`);
    box.append(node('h2', null, title));
    if (body)
        box.append(node('p', null, body));
    if (actionLabel) {
        const button = node('button', 'primary', actionLabel);
        button.addEventListener('click', onAction);
        box.append(button);
    }

    return box;
}

// ---- drawing ---------------------------------------------------------------------------------

function render() {
    if (!state)
        return;

    document.body.className = `glass-${state.settings.glass === 'blur' ? 'frosted' : state.settings.glass}`;

    el.place.textContent = state.place?.label ?? 'ShulGo';
    el.hebrew.textContent = state.hebrewLine ?? '';
    el.updated.textContent = state.updatedLabel ?? '';
    el.refresh.classList.toggle('spinning', Boolean(state.loading));

    if (!state.mikvaosAllowed && tab === 'mikvaos')
        tab = 'minyanim';

    for (const button of el.tabs.children) {
        const id = button.dataset.tab;
        button.setAttribute('aria-selected', String(id === tab));
        button.hidden = id === 'mikvaos' && !state.mikvaosAllowed;
    }

    el.content.replaceChildren();

    // Nothing saved to fall back on: say so kindly and get out of the way.
    if (state.notice && !state.minyanim.length && !state.needsKey && !state.needsPlace) {
        el.content.append(restingState(state.notice));

        return;
    }

    if (state.needsKey) {
        el.content.append(notice({
            title: 'Add your ShulGo API key',
            body: 'Ask ShulGo for one at shulgo.com/developers/request — they email you a link that '
                + 'shows your key. Settings has the button, and the box to paste it into.',
            actionLabel: 'Open Settings',
            onAction: () => window.shulgo.openSettings(),
        }));

        return;
    }

    if (state.needsPlace) {
        el.content.append(notice({
            title: 'Where are you?',
            body: 'Tell ShulGo a city, neighborhood or zip and it will remember it.',
            actionLabel: 'Open Settings',
            onAction: () => window.shulgo.openSettings(),
        }));

        return;
    }

    // The clock says this machine has travelled. Ask; don't assume.
    if (state.moved)
        el.content.append(movedPrompt(state.moved));

    if (state.notice)
        el.content.append(offlineStrip(state.notice));

    if (tab === 'minyanim')
        renderMinyanim();
    else if (tab === 'events')
        renderEvents();
    else if (tab === 'mikvaos')
        renderMikvaos();
    else
        renderZmanim();
}

function renderMinyanim() {
    const chips = node('div', 'chips');
    for (const t of TEFILLOS) {
        const button = node('button', null, t.label);
        button.setAttribute('aria-pressed', String(state.settings.tefillah === t.id));
        button.addEventListener('click', () => window.shulgo.set({ tefillah: t.id }));
        chips.append(button);
    }
    el.content.append(chips);

    if (state.error) {
        el.content.append(notice({
            title: 'ShulGo couldn’t answer',
            body: state.error.message,
            actionLabel: 'Try again',
            onAction: () => window.shulgo.refresh(),
            error: true,
        }));

        return;
    }

    if (!state.minyanim.length) {
        el.content.append(notice({
            title: `Nothing in the next ${state.settings.windowMinutes} minutes`,
            body: 'Try looking further ahead, or a different tefillah.',
        }));

        return;
    }

    // The one the menu bar counts down to leads, then the rest in time order.
    const headline = state.minyanim.find((m) => m.isHeadline);
    const rest = state.minyanim.filter((m) => !m.isHeadline);
    const rows = headline
        ? [headline, ...rest.slice(0, state.settings.listLength - 1)]
        : rest.slice(0, state.settings.listLength);

    if (headline) {
        el.content.append(sectionLabel(headline.urgency === 'missed'
            ? 'Soonest — but you’d not make it'
            : 'Soonest you can make'));
        el.content.append(minyanRow(headline));
        if (rows.length > 1)
            el.content.append(sectionLabel('Also coming up'));
    }
    for (const m of rows.filter((m) => m !== headline))
        el.content.append(minyanRow(m));

    if (state.total > rows.length)
        el.content.append(moreButton(`${state.total - rows.length} more on ShulGo`, `${state.siteUrl}/next`));
}

function renderEvents() {
    if (!state.events.length) {
        el.content.append(notice({
            title: 'No events coming up near here',
            body: 'Events that shuls send in to ShulGo show up here, soonest first.',
        }));

        return;
    }
    for (const e of state.events.slice(0, state.settings.listLength))
        el.content.append(eventRow(e));
    el.content.append(moreButton('All events on ShulGo', `${state.siteUrl}/events`));
}

function renderMikvaos() {
    if (!state.mikvaos.length) {
        el.content.append(notice({ title: 'No mikvaos listed near here' }));

        return;
    }
    for (const m of state.mikvaos.slice(0, state.settings.listLength))
        el.content.append(mikvahRow(m));

    // mikvah.org's terms: their name goes on the list.
    if (state.credit?.text) {
        const credit = node('div', 'credit');
        if (state.credit.url) {
            const button = node('button', null, state.credit.text);
            button.addEventListener('click', () => open(state.credit.url));
            credit.append(button);
        } else {
            credit.textContent = state.credit.text;
        }
        el.content.append(credit);
    }
}

function renderZmanim() {
    if (!state.zmanim.length) {
        el.content.append(notice({ title: 'No zmanim yet' }));

        return;
    }

    // Zmanim belong to one day; yesterday's must not pass for today's.
    if (state.zmanimOutOfDate) {
        el.content.append(notice({
            title: 'These zmanim are from another day',
            body: `Worked out for ${state.zmanimForDate}. Today’s come down as soon as ShulGo is back.`,
        }));
    }

    // The zmanim are one table, not a list of separate things, so they share one card. The other tabs
    // give each row its own, because each row there is its own thing.
    const card = node('div', 'zman-card');
    for (const z of state.zmanim) {
        const row = node('div', `zman${z.isNext ? ' next' : ''}${z.past && !z.isNext ? ' past' : ''}`);
        row.append(node('span', 'label', z.label));
        row.append(node('span', 'at', z.display));
        if (z.isNext && z.about)
            row.append(node('span', 'about', z.about));
        card.append(row);
    }
    el.content.append(card);

    if (state.candles)
        el.content.append(node('div', 'credit', `Candle lighting ${state.candles}`));
}

/** A quiet little heading between groups of rows. */
function sectionLabel(text) {
    return node('div', 'section', text);
}

function moreButton(label, url) {
    const button = node('button', 'more', label);
    button.addEventListener('click', () => open(url));

    return button;
}

// ---- wiring ----------------------------------------------------------------------------------

buildTabs();
el.where.addEventListener('click', () => (el.search.hidden ? openSearch() : closeSearch()));
el.searchClose.addEventListener('click', () => closeSearch());
for (const event of ['input', 'change', 'search']) {
    el.searchInput.addEventListener(event, () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => runSearch(), 300);
    });
}
el.refresh.addEventListener('click', () => window.shulgo.refresh());
el.settings.addEventListener('click', () => window.shulgo.openSettings());
el.openSite.addEventListener('click', () => open(`${state?.siteUrl ?? 'https://shulgo.com'}/next`));
document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
        if (!el.search.hidden) {
            closeSearch();

            return;
        }
        window.shulgo.hidePanel();
    }
    if (event.key === 'r' && (event.metaKey || event.ctrlKey))
        window.shulgo.refresh();
});

// The panel is an ordinary web page, so it is the part of the app that hears the network come and go.
// It passes that on, which saves the main process sitting through timeouts to find out.
const tellMain = () => window.shulgo.reportNetwork(navigator.onLine);
window.addEventListener('online', tellMain);
window.addEventListener('offline', tellMain);
tellMain();

window.shulgo.onState((next) => {
    state = next;
    tab = TABS.some((t) => t.id === tab) ? tab : 'minyanim';
    render();
});

window.shulgo.getState().then((first) => {
    state = first;
    tab = first.settings.lastTab || 'minyanim';
    render();
});
