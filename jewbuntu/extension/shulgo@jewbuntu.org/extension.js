/* ShulGo Minyan Finder — the JewBuntu top-bar widget.
 *
 * In the bar: the next minyan near you and how long you have. In the menu: minyanim, upcoming events,
 * mikvaos and today's zmanim, all from ShulGo's API. The lists and the wording come from ../../shared,
 * which the ShulGo app uses too, so the two never disagree.
 */

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

import { ShulGoApi } from './shulgo/core/api.js';
import { Config, configPath, loadApiKey } from './shulgo/gnome/settings.js';
import { Locator } from './shulgo/gnome/geo.js';
import { Store } from './shulgo/core/store.js';
import { makeTransport } from './shulgo/gnome/transport.js';
import * as F from './shulgo/core/format.js';

const TABS = [
    { id: 'minyanim', label: 'Minyanim' },
    { id: 'events', label: 'Events' },
    { id: 'mikvaos', label: 'Mikvaos' },
    { id: 'zmanim', label: 'Zmanim' },
];

const TEFILLAH_CHIPS = [
    { id: 'next', label: 'Next' },
    { id: 'shacharis', label: 'Shacharis' },
    { id: 'mincha', label: 'Mincha' },
    { id: 'maariv', label: 'Maariv' },
];

/** St.ScrollView took its child through add_actor() in GNOME 45 and set_child() from 46 on. */
function setScrollChild(scroll, child) {
    if (typeof scroll.set_child === 'function')
        scroll.set_child(child);
    else
        scroll.add_actor(child);
}

function openUri(uri) {
    if (!uri)
        return;
    try {
        Gio.AppInfo.launch_default_for_uri(uri, global.create_app_launch_context(0, -1));
    } catch (e) {
        logError(e, `ShulGo: could not open ${uri}`);
    }
}

/** A small round icon button for the header and the rows. */
function iconButton(iconName, tooltip, onClick, extraClass = '') {
    const button = new St.Button({
        style_class: `shulgo-icon-button ${extraClass}`.trim(),
        child: new St.Icon({ icon_name: iconName, style_class: 'shulgo-icon-button-icon' }),
        can_focus: true,
        accessible_name: tooltip,
    });
    button.connect('clicked', onClick);

    return button;
}

const ShulGoIndicator = GObject.registerClass(
class ShulGoIndicator extends PanelMenu.Button {
    _init(extension) {
        super._init(0.5, 'ShulGo', false);

        this._extension = extension;
        this._config = extension.config;
        this._store = extension.store;
        this._tab = this._config.lastTab;

        this.add_style_class_name('shulgo-indicator');

        // ---- what sits in the top bar ----
        const panelBox = new St.BoxLayout({ style_class: 'panel-status-menu-box shulgo-panel-box' });
        this._panelIcon = new St.Icon({
            gicon: Gio.icon_new_for_string(`${extension.path}/icons/shulgo-symbolic.svg`),
            style_class: 'system-status-icon shulgo-panel-icon',
        });
        this._panelLabel = new St.Label({
            text: '',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'shulgo-panel-label',
        });
        this._panelPill = new St.Label({
            text: '',
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'shulgo-panel-pill',
        });
        panelBox.add_child(this._panelIcon);
        panelBox.add_child(this._panelLabel);
        panelBox.add_child(this._panelPill);
        this.add_child(panelBox);

        this._buildMenu();

        this._unsubscribe = this._store.connect((what) => {
            if (what === 'changed')
                this._render();
            else
                this._renderTick();
        });

        this.menu.connect('open-state-changed', (_menu, isOpen) => {
            if (isOpen && this._store.stale)
                this._store.refresh();
        });

        this._render();
    }

    // ---- the menu's furniture ---------------------------------------------------------------

    _buildMenu() {
        this.menu.box.add_style_class_name('shulgo-menu');
        this.applyGlass();

        const holder = new PopupMenu.PopupBaseMenuItem({ reactive: false, can_focus: false });
        holder.style_class = 'shulgo-menu-item';

        const root = new St.BoxLayout({ vertical: true, style_class: 'shulgo-root', x_expand: true });

        // Header: where we are, and the two buttons.
        const header = new St.BoxLayout({ style_class: 'shulgo-header', x_expand: true });
        const titleBox = new St.BoxLayout({ vertical: true, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
        this._placeLabel = new St.Label({ text: 'ShulGo', style_class: 'shulgo-place' });
        this._dateLabel = new St.Label({ text: '', style_class: 'shulgo-hebrew-date' });
        titleBox.add_child(this._placeLabel);
        titleBox.add_child(this._dateLabel);
        header.add_child(titleBox);

        this._spinner = new St.Label({ text: '', style_class: 'shulgo-spinner', y_align: Clutter.ActorAlign.CENTER });
        header.add_child(this._spinner);
        header.add_child(iconButton('view-refresh-symbolic', 'Refresh', () => this._store.refresh({ fresh: true })));
        header.add_child(iconButton('emblem-system-symbolic', 'Settings', () => {
            this.menu.close();
            this._extension.openPreferences();
        }));
        root.add_child(header);

        // The tab strip.
        this._tabBar = new St.BoxLayout({ style_class: 'shulgo-tabs', x_expand: true });
        this._tabButtons = new Map();
        for (const tab of TABS) {
            const button = new St.Button({
                label: tab.label,
                style_class: 'shulgo-tab',
                can_focus: true,
                x_expand: true,
            });
            button.connect('clicked', () => {
                this._tab = tab.id;
                this._config.lastTab = tab.id;
                this._render();
            });
            this._tabButtons.set(tab.id, button);
            this._tabBar.add_child(button);
        }
        root.add_child(this._tabBar);

        // The list.
        this._scroll = new St.ScrollView({
            style_class: 'shulgo-scroll',
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
            x_expand: true,
            y_expand: true,
        });
        this._content = new St.BoxLayout({ vertical: true, style_class: 'shulgo-content', x_expand: true });
        setScrollChild(this._scroll, this._content);
        root.add_child(this._scroll);

        // Footer.
        const footer = new St.BoxLayout({ style_class: 'shulgo-footer', x_expand: true });
        this._updatedLabel = new St.Label({ text: '', style_class: 'shulgo-updated', y_align: Clutter.ActorAlign.CENTER });
        footer.add_child(this._updatedLabel);
        footer.add_child(new St.Widget({ x_expand: true }));
        const openSite = new St.Button({ label: 'Open ShulGo', style_class: 'shulgo-link-button', can_focus: true });
        openSite.connect('clicked', () => {
            this.menu.close();
            openUri(`${this._extension.api.siteUrl}/next`);
        });
        footer.add_child(openSite);
        root.add_child(footer);

        holder.add_child(root);
        this.menu.addMenuItem(holder);
    }

    /**
     * The menu is ShulGo's own navy surface, not the Shell theme's grey. "tint" lets the desktop show
     * through it; "blur" also frosts what's behind, through the Shell's own blur effect; "solid" is flat
     * navy for anyone who'd rather just read it.
     *
     * The Shell's blur paints over the actor's rectangle and doesn't follow its rounded corners on every
     * GNOME version, which is why "tint" — which always looks right — is the one it starts on.
     */
    applyGlass() {
        const wanted = this._config.glass;
        const pointer = this.menu.actor;

        for (const name of ['blur', 'tint', 'solid'])
            pointer.remove_style_class_name(`shulgo-glass-${name}`);
        pointer.add_style_class_name(`shulgo-glass-${wanted}`);

        if (this._blur) {
            this.menu.box.remove_effect(this._blur);
            this._blur = null;
        }
        if (wanted !== 'blur')
            return;

        try {
            this._blur = new Shell.BlurEffect({
                brightness: 0.72,
                sigma: 28,
                mode: Shell.BlurMode.BACKGROUND,
            });
            this.menu.box.add_effect(this._blur);
        } catch (e) {
            // Older or stricter Shells don't offer a background blur; the tint alone still looks right.
            this._blur = null;
            logError(e, 'ShulGo: this GNOME Shell can’t blur behind the menu');
        }
    }

    // ---- drawing ----------------------------------------------------------------------------

    /** Just the numbers that move: the panel text and each row's countdown. */
    _renderTick() {
        this._renderPanel();
        if (this._tab === 'minyanim' || this._tab === 'zmanim')
            this._renderContent();
        this._updatedLabel.text = F.updatedAgo(this._store.state.updatedAt);
    }

    _render() {
        const { state } = this._store;

        this._renderPanel();

        this._placeLabel.text = state.place?.label
            ? (state.place.label === 'your location' ? 'Near you' : state.place.label)
            : 'ShulGo';
        this._dateLabel.text = F.hebrewDayLine(state.today) || '';
        this._dateLabel.visible = this._dateLabel.text !== '';
        this._spinner.text = state.loading ? '…' : '';
        this._updatedLabel.text = F.updatedAgo(state.updatedAt);

        // The mikvah tab is only there for keys that may read mikvaos.
        const mikvaosAllowed = state.mikvaos !== null;
        this._tabButtons.get('mikvaos').visible = mikvaosAllowed;
        if (!mikvaosAllowed && this._tab === 'mikvaos')
            this._tab = 'minyanim';

        for (const [id, button] of this._tabButtons) {
            if (id === this._tab)
                button.add_style_class_name('shulgo-tab-active');
            else
                button.remove_style_class_name('shulgo-tab-active');
        }

        this._renderContent();
    }

    _renderPanel() {
        const next = this._store.headline;
        const mode = this._config.panelText;
        const minutes = this._store.nextMinyanIn;

        if (!next || mode === 'icon') {
            this._panelLabel.visible = false;
            this._panelPill.visible = false;
            this._panelIcon.remove_style_class_name('shulgo-panel-icon-alert');
            if (!next && this._store.state.error)
                this._panelIcon.add_style_class_name('shulgo-panel-icon-alert');

            return;
        }

        const words = `${F.tefillahLabel(next.tefillah)} ${next.display_time}`;
        this._panelLabel.text = mode === 'countdown' ? '' : (mode === 'time' ? next.display_time : words);
        this._panelLabel.visible = this._panelLabel.text !== '';

        const pill = F.countdownShort(minutes);
        this._panelPill.text = pill;
        this._panelPill.visible = mode !== 'time' && pill !== '';
        for (const name of ['comfortable', 'tight', 'missed', 'unknown'])
            this._panelPill.remove_style_class_name(`shulgo-pill-${name}`);
        this._panelPill.add_style_class_name(`shulgo-pill-${F.urgency(next)}`);
    }

    _renderContent() {
        this._content.destroy_all_children();
        const { state } = this._store;

        if (state.needsKey) {
            this._content.add_child(this._notice(
                'Add your ShulGo API key',
                'Make a key in ShulGo (Admin › System › API & apps), then paste it into Settings.',
                'Open Settings', () => {
                    this.menu.close();
                    this._extension.openPreferences();
                }));

            return;
        }

        if (state.needsPlace) {
            this._content.add_child(this._notice(
                'Where are you?',
                'Turn on “Use this computer’s location”, or type a city, neighborhood or zip in Settings.',
                'Open Settings', () => {
                    this.menu.close();
                    this._extension.openPreferences();
                }));

            return;
        }

        if (this._tab === 'minyanim')
            this._renderMinyanim();
        else if (this._tab === 'events')
            this._renderEvents();
        else if (this._tab === 'mikvaos')
            this._renderMikvaos();
        else
            this._renderZmanim();
    }

    _renderMinyanim() {
        const { state } = this._store;

        // Which tefillah.
        const chips = new St.BoxLayout({ style_class: 'shulgo-chips', x_expand: true });
        for (const chip of TEFILLAH_CHIPS) {
            const button = new St.Button({
                label: chip.label,
                style_class: `shulgo-chip${this._config.tefillah === chip.id ? ' shulgo-chip-active' : ''}`,
                can_focus: true,
            });
            button.connect('clicked', () => {
                this._config.tefillah = chip.id;
                this._store.refresh();
            });
            chips.add_child(button);
        }
        this._content.add_child(chips);

        if (state.error) {
            this._content.add_child(this._errorBox(state.error));

            return;
        }

        if (!state.minyanim.length) {
            this._content.add_child(this._empty(
                `Nothing in the next ${this._config.windowMinutes} minutes.`,
                'Try a longer window in Settings, or look on ShulGo.'));

            return;
        }

        // The one the top bar counts down to leads, then the rest in time order. Without this, a run of
        // minyanim you can no longer reach pushes the one you actually want off the bottom of the menu.
        const headline = this._store.headline;
        const rest = state.minyanim.filter((m) => m !== headline);
        const rows = headline
            ? [headline, ...rest.slice(0, Math.max(0, this._config.listLength - 1))]
            : rest.slice(0, this._config.listLength);
        rows.forEach((item) => this._content.add_child(this._minyanRow(item, item === headline)));

        if (state.minyanim.length > rows.length) {
            this._content.add_child(this._moreRow(
                `${state.minyanim.length - rows.length} more on ShulGo`,
                `${this._extension.api.siteUrl}/next`));
        }
    }

    _minyanRow(item, isHeadline) {
        const urgency = F.urgency(item);
        const row = new St.BoxLayout({
            style_class: `shulgo-row shulgo-row-${urgency}${isHeadline ? ' shulgo-row-first' : ''}`,
            x_expand: true,
        });

        row.add_child(new St.Widget({ style_class: `shulgo-dot shulgo-dot-${urgency}`, y_align: Clutter.ActorAlign.CENTER }));

        const timeBox = new St.BoxLayout({ vertical: true, style_class: 'shulgo-time-box', y_align: Clutter.ActorAlign.CENTER });
        timeBox.add_child(new St.Label({ text: item.display_time || '', style_class: 'shulgo-time' }));
        timeBox.add_child(new St.Label({
            text: F.countdown(F.minutesUntil(item.starts_at)),
            style_class: `shulgo-countdown shulgo-countdown-${urgency}`,
        }));
        row.add_child(timeBox);

        const textBox = new St.BoxLayout({ vertical: true, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
        const titleRow = new St.BoxLayout({ x_expand: true });
        titleRow.add_child(new St.Label({ text: F.tefillahLabel(item.tefillah), style_class: 'shulgo-row-title' }));
        if (item.kind === 'live')
            titleRow.add_child(new St.Label({ text: 'Live', style_class: 'shulgo-badge shulgo-badge-live' }));
        else if (item.kind === 'standing')
            titleRow.add_child(new St.Label({ text: 'Standing', style_class: 'shulgo-badge' }));
        if (urgency === 'missed')
            titleRow.add_child(new St.Label({ text: 'Too far', style_class: 'shulgo-badge shulgo-badge-missed' }));
        textBox.add_child(titleRow);
        textBox.add_child(new St.Label({ text: F.minyanSubtitle(item, this._config.travelMode), style_class: 'shulgo-row-subtitle' }));
        const note = F.minyanNote(item);
        if (note)
            textBox.add_child(new St.Label({ text: note, style_class: 'shulgo-row-note' }));
        row.add_child(textBox);

        const destination = F.minyanDestination(item);
        if (destination) {
            row.add_child(iconButton('find-location-symbolic', 'Directions', () => {
                this.menu.close();
                openUri(F.mapsUri(destination));
            }, 'shulgo-row-action'));
        }

        const shulUrl = item.shul?.url || (item.shul?.slug ? `${this._extension.api.siteUrl}/shul/${item.shul.slug}` : null);
        if (!shulUrl)
            return row;

        const button = new St.Button({ style_class: 'shulgo-row-button', child: row, can_focus: true, x_expand: true });
        button.connect('clicked', () => {
            this.menu.close();
            openUri(shulUrl);
        });

        return button;
    }

    _renderEvents() {
        const events = this._store.state.events ?? [];
        if (!events.length) {
            this._content.add_child(this._empty('No events coming up near here.',
                'Events shuls send in show up here once ShulGo has them.'));

            return;
        }

        for (const event of events.slice(0, this._config.listLength)) {
            const row = new St.BoxLayout({ style_class: 'shulgo-row shulgo-row-event', x_expand: true });

            const dateBox = new St.BoxLayout({ vertical: true, style_class: 'shulgo-time-box', y_align: Clutter.ActorAlign.CENTER });
            dateBox.add_child(new St.Label({ text: F.eventDate(event.date), style_class: 'shulgo-event-date' }));
            if (event.start_time)
                dateBox.add_child(new St.Label({ text: event.start_time, style_class: 'shulgo-countdown' }));
            row.add_child(dateBox);

            const textBox = new St.BoxLayout({ vertical: true, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
            textBox.add_child(new St.Label({ text: event.title || '', style_class: 'shulgo-row-title' }));
            const where = [event.where, event.online ? 'Online' : '', F.miles(event.distance_miles)]
                .filter((x) => x).join(' · ');
            if (where)
                textBox.add_child(new St.Label({ text: where, style_class: 'shulgo-row-subtitle' }));
            row.add_child(textBox);

            const url = event.url || `${this._extension.api.siteUrl}/events`;
            const button = new St.Button({ style_class: 'shulgo-row-button', child: row, can_focus: true, x_expand: true });
            button.connect('clicked', () => {
                this.menu.close();
                openUri(url);
            });
            this._content.add_child(button);
        }
    }

    _renderMikvaos() {
        const mikvaos = this._store.state.mikvaos ?? [];
        if (!mikvaos.length) {
            this._content.add_child(this._empty('No mikvaos listed near here.', ''));

            return;
        }

        for (const mikvah of mikvaos.slice(0, this._config.listLength)) {
            const row = new St.BoxLayout({ style_class: 'shulgo-row shulgo-row-mikvah', x_expand: true });
            row.add_child(new St.Widget({ style_class: 'shulgo-dot shulgo-dot-mikvah', y_align: Clutter.ActorAlign.CENTER }));

            const textBox = new St.BoxLayout({ vertical: true, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
            const titleRow = new St.BoxLayout({ x_expand: true });
            titleRow.add_child(new St.Label({ text: mikvah.name || '', style_class: 'shulgo-row-title' }));
            for (const who of mikvah.for ?? [])
                titleRow.add_child(new St.Label({ text: F.forWhomLabel(who), style_class: 'shulgo-badge shulgo-badge-mikvah' }));
            textBox.add_child(titleRow);
            const where = [mikvah.address, mikvah.city, F.miles(mikvah.distance_mi)].filter((x) => x).join(' · ');
            textBox.add_child(new St.Label({ text: where, style_class: 'shulgo-row-subtitle' }));
            row.add_child(textBox);

            const destination = mikvah.lat !== null && mikvah.lat !== undefined
                ? `${mikvah.lat},${mikvah.lng}`
                : [mikvah.address, mikvah.city].filter((x) => x).join(', ');
            if (destination) {
                row.add_child(iconButton('find-location-symbolic', 'Directions', () => {
                    this.menu.close();
                    openUri(F.mapsUri(destination));
                }, 'shulgo-row-action'));
            }

            const button = new St.Button({ style_class: 'shulgo-row-button', child: row, can_focus: true, x_expand: true });
            button.connect('clicked', () => {
                this.menu.close();
                openUri(mikvah.url);
            });
            this._content.add_child(button);
        }

        // mikvah.org's terms: their name goes on the list.
        const credit = F.creditLine(this._store.state.mikvaosCredit);
        if (credit?.text) {
            if (credit.url) {
                const link = new St.Button({ label: credit.text, style_class: 'shulgo-credit-button', can_focus: true });
                link.connect('clicked', () => {
                    this.menu.close();
                    openUri(credit.url);
                });
                this._content.add_child(link);
            } else {
                this._content.add_child(new St.Label({ text: credit.text, style_class: 'shulgo-credit' }));
            }
        }
    }

    _renderZmanim() {
        const rows = F.zmanimList(this._store.state.zmanim);
        if (!rows.length) {
            this._content.add_child(this._empty('No zmanim yet.', ''));

            return;
        }

        for (const zman of rows) {
            const row = new St.BoxLayout({
                style_class: `shulgo-zman${zman.isNext ? ' shulgo-zman-next' : ''}${zman.past ? ' shulgo-zman-past' : ''}`,
                x_expand: true,
            });
            row.add_child(new St.Label({ text: zman.label, style_class: 'shulgo-zman-label', x_expand: true }));
            row.add_child(new St.Label({ text: zman.display, style_class: 'shulgo-zman-time' }));
            if (zman.past && !zman.isNext)
                row.opacity = 130;
            this._content.add_child(row);
        }

        const candles = F.candleLighting(this._store.state.today);
        if (candles)
            this._content.add_child(new St.Label({ text: `Candle lighting ${candles}`, style_class: 'shulgo-credit' }));
    }

    // ---- the little blocks ------------------------------------------------------------------

    _notice(title, body, actionLabel, onAction) {
        const box = new St.BoxLayout({ vertical: true, style_class: 'shulgo-notice', x_expand: true });
        box.add_child(new St.Label({ text: title, style_class: 'shulgo-notice-title' }));
        box.add_child(new St.Label({ text: body, style_class: 'shulgo-notice-body' }));
        if (actionLabel) {
            const button = new St.Button({ label: actionLabel, style_class: 'shulgo-primary-button', can_focus: true });
            button.connect('clicked', onAction);
            box.add_child(button);
        }

        return box;
    }

    _errorBox(error) {
        const box = new St.BoxLayout({ vertical: true, style_class: 'shulgo-notice shulgo-notice-error', x_expand: true });
        box.add_child(new St.Label({ text: 'ShulGo couldn’t answer', style_class: 'shulgo-notice-title' }));
        box.add_child(new St.Label({ text: error.message || '', style_class: 'shulgo-notice-body' }));
        const button = new St.Button({ label: 'Try again', style_class: 'shulgo-primary-button', can_focus: true });
        button.connect('clicked', () => this._store.refresh({ fresh: true }));
        box.add_child(button);

        return box;
    }

    _empty(title, body) {
        const box = new St.BoxLayout({ vertical: true, style_class: 'shulgo-empty', x_expand: true });
        box.add_child(new St.Label({ text: title, style_class: 'shulgo-empty-title' }));
        if (body)
            box.add_child(new St.Label({ text: body, style_class: 'shulgo-empty-body' }));

        return box;
    }

    _moreRow(label, url) {
        const button = new St.Button({ label, style_class: 'shulgo-more', can_focus: true, x_expand: true });
        button.connect('clicked', () => {
            this.menu.close();
            openUri(url);
        });

        return button;
    }

    destroy() {
        this._unsubscribe?.();
        if (this._blur) {
            this.menu.box.remove_effect(this._blur);
            this._blur = null;
        }
        super.destroy();
    }
});

export default class ShulGoExtension extends Extension {
    enable() {
        this.config = new Config(this.getSettings());
        this.api = new ShulGoApi({
            baseUrl: this.config.baseUrl,
            apiKey: loadApiKey(),
            transport: makeTransport({ userAgent: 'JewBuntu-ShulGo-Shell/1.0' }),
        });
        this.store = new Store(this.api, this.config, new Locator(this.api, this.config));

        this._indicator = new ShulGoIndicator(this);
        Main.panel.addToStatusArea('shulgo@jewbuntu.org', this._indicator, 1, this.config.panelPosition);

        // The key lives outside GSettings, so watch its file as well as the settings.
        this._watchKeyFile();
        this.config.watch(
            ['api-base-url', 'use-geolocation', 'place', 'window-minutes', 'travel-mode', 'tefillah', 'mikvah-for'],
            (key) => {
                if (key === 'api-base-url')
                    this.api.reconfigure({ baseUrl: this.config.baseUrl });
                this.api.forget();
                this.store.refresh();
            });
        this.config.watch(['refresh-seconds'], () => this.store.restartTimers());
        this.config.watch(['panel-position'], () => this._movePanel());
        this.config.watch(['panel-text', 'list-length'], () => this._indicator?._render());
        this.config.watch(['glass'], () => this._indicator?.applyGlass());

        this.store.start();
        this.store.refresh();
    }

    disable() {
        this._keyMonitor?.cancel();
        this._keyMonitor = null;
        this.store?.destroy();
        this.config?.destroy();
        this._indicator?.destroy();
        this._indicator = null;
        this.store = null;
        this.api = null;
        this.config = null;
    }

    /** Settings writes the key to a file; pick it up without a restart. */
    _watchKeyFile() {
        const file = Gio.File.new_for_path(configPath());
        try {
            this._keyMonitor = file.monitor_file(Gio.FileMonitorFlags.NONE, null);
        } catch (e) {
            logError(e, 'ShulGo: could not watch the key file');

            return;
        }
        this._keyMonitor.connect('changed', () => {
            this.api.reconfigure({ apiKey: loadApiKey() });
            this.store.refresh({ fresh: true });
        });
    }

    _movePanel() {
        if (!this._indicator)
            return;
        const indicator = this._indicator;
        this._indicator = null;
        indicator.destroy();
        this._indicator = new ShulGoIndicator(this);
        Main.panel.addToStatusArea('shulgo@jewbuntu.org', this._indicator, 1, this.config.panelPosition);
    }
}
