/* ShulGo Minyan Finder — the JewBuntu top-bar widget.
 *
 * In the bar: the next minyan near you and how long you have. In the menu: minyanim, upcoming events,
 * mikvaos and today's zmanim, all from ShulGo's API. The lists and the wording come from ../../shared,
 * which the ShulGo app uses too, so the two never disagree.
 */

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

import { ShulGoApi } from './shulgo/core/api.js';
import { Cache } from './shulgo/core/cache.js';
import { Config, configPath, loadApiKey } from './shulgo/gnome/settings.js';
import { Locator } from './shulgo/gnome/geo.js';
import { Store } from './shulgo/core/store.js';
import { makeTransport } from './shulgo/gnome/transport.js';
import { makeNetwork, makeStorage } from './shulgo/gnome/offline.js';
import * as F from './shulgo/core/format.js';

/* Laying a box out vertically, in whichever way the running shell understands.
 *
 * GNOME 48 added `orientation` to St.BoxLayout and deprecated `vertical`; GNOME 51 removed `vertical`
 * altogether. So there is no single spelling that covers everything this extension claims to run on:
 * 45, 46 and 47 have only `vertical`, 51 has only `orientation`, and 48 to 50 accept either. Reaching
 * for `orientation` everywhere would have fixed Fedora Asahi's GNOME 51 by breaking Ubuntu 24.04's
 * GNOME 46, which is a worse bug than the one it fixes, because nobody would be looking for it.
 *
 * Hence a feature check rather than a version check. A shell cannot be wrong about which properties
 * it has, whereas its reported version has been wrong before — and this keeps working on GNOME 52
 * without anyone editing it again.
 */
const VERTICAL = (() => {
    if ('orientation' in St.BoxLayout.prototype)
        return { orientation: Clutter.Orientation.VERTICAL };

    // Belt and braces. If some future GJS stops putting GObject properties on the prototype, the
    // check above would quietly answer "no" on a shell that does have `orientation`, and we'd be
    // back to passing a property that no longer exists. Building one throwaway box settles it.
    try {
        new St.BoxLayout({ orientation: Clutter.Orientation.VERTICAL }).destroy();

        return { orientation: Clutter.Orientation.VERTICAL };
    } catch {
        return { vertical: true };
    }
})();

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

        const holder = new PopupMenu.PopupBaseMenuItem({ reactive: false, can_focus: false });
        holder.style_class = 'shulgo-menu-item';
        this._holder = holder;

        const root = new St.BoxLayout({ ...VERTICAL, style_class: 'shulgo-root', x_expand: true });
        this._rootBox = root;

        // Header: where we are, and the two buttons.
        const header = new St.BoxLayout({ style_class: 'shulgo-header', x_expand: true });
        const titleBox = new St.BoxLayout({ ...VERTICAL, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
        this._placeLabel = new St.Label({ text: 'ShulGo', style_class: 'shulgo-place' });
        this._dateLabel = new St.Label({ text: '', style_class: 'shulgo-hebrew-date' });
        titleBox.add_child(this._placeLabel);
        titleBox.add_child(this._dateLabel);

        // The place is a button: travelling is the case where "open Settings, find the box, type"
        // is one step too many, so looking somewhere else starts right here.
        this._placeButton = new St.Button({
            style_class: 'shulgo-place-button',
            child: titleBox,
            can_focus: true,
            x_expand: true,
        });
        this._placeButton.connect('clicked', () => this._openSearch());
        header.add_child(this._placeButton);

        this._spinner = new St.Label({ text: '', style_class: 'shulgo-spinner', y_align: Clutter.ActorAlign.CENTER });
        header.add_child(this._spinner);
        header.add_child(iconButton('view-refresh-symbolic', 'Refresh', () => this._store.refresh({ fresh: true })));
        header.add_child(iconButton('emblem-system-symbolic', 'Settings', () => {
            this.menu.close();
            this._extension.openPreferences();
        }));
        root.add_child(header);
        root.add_child(this._buildSearch());

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
        this._content = new St.BoxLayout({ ...VERTICAL, style_class: 'shulgo-content', x_expand: true });
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

        this.applyGlass();
    }

    /** Type a city; ShulGo says what it could be; pick one. The path that works on any machine. */
    _buildSearch() {
        this._searchBox = new St.BoxLayout({ ...VERTICAL, style_class: 'shulgo-search', x_expand: true, visible: false });

        const row = new St.BoxLayout({ style_class: 'shulgo-search-row', x_expand: true });
        // Set on the actor, not asked for in the stylesheet. A shell theme styles StEntry — its
        // background, its border, its corners and the colour of its text — and it outranks us, which is
        // how the box ended up with dark text on dark and corners that were not ours. Same answer as
        // the menu surface: inline, where there is nothing to win or lose.
        this._searchEntry = new St.Entry({ style_class: 'shulgo-search-entry', can_focus: true, x_expand: true });

        // Inline wins over the stylesheet, so the focus ring has to be inline as well or it would never
        // appear. Two styles, swapped on focus. A 1px ring in the accent blue read as "a slightly
        // lighter border" rather than as focus, so focus gets two pixels of it and a navy ground; the
        // padding drops by the pixel the border gains, so the box doesn't change size as you tab into it.
        const entryStyle = (focused) => (focused
            ? 'background-color: rgba(18, 48, 90, 0.9); border: 2px solid #8fb3ea; padding: 5px 10px;'
            : 'background-color: rgba(11, 18, 32, 0.72);'
                + ' border: 1px solid rgba(143, 179, 234, 0.3); padding: 6px 11px;')
            + ' border-radius: 10px; color: #ffffff; caret-color: #ffffff;';
        this._searchEntry.set_style(entryStyle(false));
        this._searchEntry.connect('key-focus-in', () => this._searchEntry.set_style(entryStyle(true)));
        this._searchEntry.connect('key-focus-out', () => this._searchEntry.set_style(entryStyle(false)));

        // The placeholder gets its own actor for the same reason: the one St makes takes the theme's
        // colour, and on a dark box that was unreadable.
        const hint = new St.Label({ text: 'A city, neighborhood or zip' });
        hint.set_style('color: #aeb9c9;');
        this._searchEntry.set_hint_actor(hint);
        this._searchEntry.clutter_text.connect('text-changed', () => this._searchLater());
        this._searchEntry.clutter_text.connect('key-press-event', (_t, event) => {
            if (event.get_key_symbol() === Clutter.KEY_Escape) {
                this._closeSearch();

                return Clutter.EVENT_STOP;
            }

            return Clutter.EVENT_PROPAGATE;
        });
        row.add_child(this._searchEntry);
        row.add_child(iconButton('window-close-symbolic', 'Close', () => this._closeSearch()));
        this._searchBox.add_child(row);

        this._searchResults = new St.BoxLayout({ ...VERTICAL, style_class: 'shulgo-search-results', x_expand: true });
        this._searchBox.add_child(this._searchResults);

        return this._searchBox;
    }

    _openSearch() {
        this._searchBox.visible = true;
        this._searchEntry.set_text('');
        this._searchResults.destroy_all_children();
        global.stage.set_key_focus(this._searchEntry.clutter_text);
    }

    _closeSearch() {
        if (this._searchTimer) {
            GLib.Source.remove(this._searchTimer);
            this._searchTimer = null;
        }
        this._searchBox.visible = false;
        this._searchResults.destroy_all_children();
    }

    /** A breath after the last keystroke, so typing a city isn't a request per letter. */
    _searchLater() {
        if (this._searchTimer)
            GLib.Source.remove(this._searchTimer);
        this._searchTimer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 350, () => {
            this._searchTimer = null;
            this._searchNow().catch((e) => logError(e, 'ShulGo: place search failed'));

            return GLib.SOURCE_REMOVE;
        });
    }

    async _searchNow() {
        const typed = this._searchEntry.get_text().trim();
        this._searchResults.destroy_all_children();
        if (typed.length < 2)
            return;

        const answer = await this._extension.api.places(typed);
        if (!answer.ok) {
            this._searchResults.add_child(new St.Label({ text: answer.message, style_class: 'shulgo-search-note' }));

            return;
        }
        if (!answer.data.length) {
            this._searchResults.add_child(new St.Label({
                text: `ShulGo doesn’t know “${typed}”. Try a city with its state or country, or a zip.`,
                style_class: 'shulgo-search-note',
            }));

            return;
        }

        for (const match of answer.data.slice(0, 6)) {
            const line = new St.BoxLayout({ style_class: 'shulgo-search-hit', x_expand: true });
            line.add_child(new St.Label({ text: match.label, style_class: 'shulgo-search-label', x_expand: true }));
            if (match.shuls) {
                line.add_child(new St.Label({
                    text: `${match.shuls} shul${match.shuls === 1 ? '' : 's'}`,
                    style_class: 'shulgo-search-count',
                }));
            }
            const button = new St.Button({ style_class: 'shulgo-search-button', child: line, can_focus: true, x_expand: true });
            button.connect('clicked', () => this._usePlace(match));
            this._searchResults.add_child(button);
        }
    }

    _usePlace(match) {
        const settings = this._config.settings;
        settings.set_boolean('use-geolocation', false);
        settings.set_string('place', match.label);
        this._config.rememberPoint({ lat: match.lat, lng: match.lng, label: match.label });
        this._store.settleTimezone();
        this._closeSearch();
        this._extension.api.forget();
        this._store.refresh({ fresh: true });
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
        if (!this._rootBox)
            return;

        // Set directly on the actors, not through the stylesheet.
        //
        // Twice now the navy has been drawn by a rule that lost: first because it hung off the Shell
        // theme's own .popup-menu-content, then because an extension stylesheet does not outrank a
        // user theme's. A shell theme can restyle any class it knows, and it knows all of the Shell's;
        // an inline style on an actor is outside that argument entirely, so this is the end of it.
        //
        // Three layers, from the back: the box-pointer and the menu box are emptied of whatever the
        // theme would paint, and our own root — an actor we made, that no theme has a rule for —
        // carries the surface.
        const surface = {
            tint: 'background-color: rgba(11, 18, 32, 0.78); border: 1px solid rgba(143, 179, 234, 0.2);',
            blur: 'background-color: rgba(11, 18, 32, 0.62); border: 1px solid rgba(143, 179, 234, 0.2);',
            solid: 'background-color: #0b1220; border: 1px solid #26324a;',
        }[wanted] ?? '';

        const blank = 'background-color: transparent; border: none; box-shadow: none;';
        this.menu.actor.set_style(`${blank} -arrow-background-color: transparent; `
            + '-arrow-border-color: transparent; -arrow-border-width: 0;');
        this.menu.box.set_style(`${blank} padding: 0;`);
        this._holder?.set_style(`${blank} padding: 0;`);
        // No box-shadow: St draws one as a rectangle, ignoring the border-radius, which is what put a
        // square halo around the rounded panel. The navy carries its own edge well enough without it.
        this._rootBox.set_style(`${surface} border-radius: 16px; padding: 10px 8px 6px 8px;`);

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
        const s = this._store.state;
        this._updatedLabel.text = s.stale ? F.takenAt(s.staleSince) : F.updatedAgo(s.updatedAt);
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
                'Ask ShulGo for one at shulgo.com/developers/request — they email you a link that '
                + 'shows your key. Settings has the button, and the box to paste it into.',
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

        // The clock says the laptop has travelled. Ask rather than assume — the place may well still
        // be the one wanted, and guessing wrong is worse than a question.
        if (state.movedTimezone)
            this._content.add_child(this._movedPrompt(state.movedTimezone));

        // Showing something old is better than showing nothing, as long as it says so.
        const notice = F.offlineNotice(state, this._store.hasAnything);
        if (notice)
            this._content.add_child(this._offlineStrip(notice));

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

        if (state.error && !state.minyanim.length) {
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

        const timeBox = new St.BoxLayout({ ...VERTICAL, style_class: 'shulgo-time-box', y_align: Clutter.ActorAlign.CENTER });
        timeBox.add_child(new St.Label({ text: item.display_time || '', style_class: 'shulgo-time' }));
        timeBox.add_child(new St.Label({
            text: F.countdown(F.minutesUntil(item.starts_at)),
            style_class: `shulgo-countdown shulgo-countdown-${urgency}`,
        }));
        row.add_child(timeBox);

        const textBox = new St.BoxLayout({ ...VERTICAL, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
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

            const dateBox = new St.BoxLayout({ ...VERTICAL, style_class: 'shulgo-time-box', y_align: Clutter.ActorAlign.CENTER });
            dateBox.add_child(new St.Label({ text: F.eventDate(event.date), style_class: 'shulgo-event-date' }));
            if (event.start_time)
                dateBox.add_child(new St.Label({ text: event.start_time, style_class: 'shulgo-countdown' }));
            row.add_child(dateBox);

            const textBox = new St.BoxLayout({ ...VERTICAL, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
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

            const textBox = new St.BoxLayout({ ...VERTICAL, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
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

        if (this._store.zmanimOutOfDate) {
            this._content.add_child(this._empty('These zmanim are from another day',
                `Worked out for ${this._store.state.zmanimForDate}. Today’s come down as soon as ShulGo is back.`));
        }

        // The zmanim are one table, not a list of separate things, so they sit in one card with hairlines
        // between them — the way the window's AdwPreferencesGroup draws them. The other tabs give each
        // row its own card because each row is its own thing.
        const card = new St.BoxLayout({ ...VERTICAL, style_class: 'shulgo-zman-card', x_expand: true });
        rows.forEach((zman, i) => {
            const last = i === rows.length - 1;
            const row = new St.BoxLayout({
                style_class: `shulgo-zman${zman.isNext ? ' shulgo-zman-next' : ''}`
                    + `${zman.past ? ' shulgo-zman-past' : ''}${last ? '' : ' shulgo-zman-ruled'}`,
                x_expand: true,
            });
            row.add_child(new St.Label({ text: zman.label, style_class: 'shulgo-zman-label', x_expand: true }));
            row.add_child(new St.Label({ text: zman.display, style_class: 'shulgo-zman-time' }));
            if (zman.past && !zman.isNext)
                row.opacity = 130;
            card.add_child(row);
        });
        this._content.add_child(card);

        const candles = F.candleLighting(this._store.state.today);
        if (candles)
            this._content.add_child(new St.Label({ text: `Candle lighting ${candles}`, style_class: 'shulgo-credit' }));
    }

    // ---- the little blocks ------------------------------------------------------------------

    _notice(title, body, actionLabel, onAction) {
        const box = new St.BoxLayout({ ...VERTICAL, style_class: 'shulgo-notice', x_expand: true });
        box.add_child(new St.Label({ text: title, style_class: 'shulgo-notice-title' }));
        box.add_child(new St.Label({ text: body, style_class: 'shulgo-notice-body' }));
        if (actionLabel) {
            const button = new St.Button({ label: actionLabel, style_class: 'shulgo-primary-button', can_focus: true });
            button.connect('clicked', onAction);
            box.add_child(button);
        }

        return box;
    }

    /** "Your clock says you're in Chicago now — still looking near Toronto?" */
    _movedPrompt(zone) {
        const box = new St.BoxLayout({ style_class: 'shulgo-moved', x_expand: true });
        box.add_child(new St.Icon({ icon_name: 'find-location-symbolic', style_class: 'shulgo-moved-icon' }));

        const words = new St.BoxLayout({ ...VERTICAL, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
        words.add_child(new St.Label({
            text: `Your clock says you’re in ${F.placeFromTimezone(zone)} now`,
            style_class: 'shulgo-moved-title',
        }));
        const here = this._store.state.place?.label;
        words.add_child(new St.Label({
            text: here ? `Still looking near ${here}.` : 'Where should ShulGo look?',
            style_class: 'shulgo-moved-body',
        }));
        box.add_child(words);

        const change = new St.Button({ label: 'Look elsewhere', style_class: 'shulgo-moved-change', can_focus: true });
        change.connect('clicked', () => this._openSearch());
        box.add_child(change);

        const keep = iconButton('window-close-symbolic', 'Stay here', () => this._store.settleTimezone());
        box.add_child(keep);

        return box;
    }

    /**
     * The quiet strip above a list we couldn't refresh. Not an error: what's underneath is still worth
     * reading, and it mends itself.
     */
    _offlineStrip(notice) {
        const box = new St.BoxLayout({ style_class: 'shulgo-offline', x_expand: true });
        box.add_child(new St.Icon({ icon_name: 'network-offline-symbolic', style_class: 'shulgo-offline-icon' }));

        const words = new St.BoxLayout({ ...VERTICAL, x_expand: true, y_align: Clutter.ActorAlign.CENTER });
        words.add_child(new St.Label({ text: notice.title, style_class: 'shulgo-offline-title' }));
        words.add_child(new St.Label({ text: notice.body, style_class: 'shulgo-offline-body' }));
        box.add_child(words);

        const again = new St.Button({ label: 'Try now', style_class: 'shulgo-offline-retry', can_focus: true });
        again.connect('clicked', () => this._store.refresh({ fresh: true }));
        box.add_child(again);

        return box;
    }

    _errorBox(error) {
        const notice = F.offlineNotice(this._store.state, false);
        const box = new St.BoxLayout({ ...VERTICAL, style_class: 'shulgo-notice', x_expand: true });
        box.add_child(new St.Icon({ icon_name: 'network-offline-symbolic', style_class: 'shulgo-resting-icon' }));
        box.add_child(new St.Label({ text: notice?.title ?? 'ShulGo couldn’t answer', style_class: 'shulgo-notice-title' }));
        box.add_child(new St.Label({ text: notice?.body ?? error.message ?? '', style_class: 'shulgo-notice-body' }));
        const button = new St.Button({ label: 'Try now', style_class: 'shulgo-primary-button', can_focus: true });
        button.connect('clicked', () => this._store.refresh({ fresh: true }));
        box.add_child(button);

        return box;
    }

    _empty(title, body) {
        const box = new St.BoxLayout({ ...VERTICAL, style_class: 'shulgo-empty', x_expand: true });
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
        this.network = makeNetwork();
        this.cache = new Cache(makeStorage());
        this.api = new ShulGoApi({
            baseUrl: this.config.baseUrl,
            apiKey: loadApiKey(),
            transport: makeTransport({ userAgent: 'JewBuntu-ShulGo-Shell/1.0' }),
            cache: this.cache,
            isOnline: this.network.isOnline,
        });
        this.store = new Store(this.api, this.config, new Locator(this.api, this.config), this.network);
        this.store.connect((what) => {
            if (what === 'changed')
                this.cache.save();
        });

        this._indicator = new ShulGoIndicator(this);
        Main.panel.addToStatusArea('jewbuntu@shulgo.com', this._indicator, 1, this.config.panelPosition);

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
        this.cache?.save();
        this.store?.destroy();
        this.config?.destroy();
        this._indicator?.destroy();
        this._indicator = null;
        this.store = null;
        this.api = null;
        this.config = null;
        this.cache = null;
        this.network = null;
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
        Main.panel.addToStatusArea('jewbuntu@shulgo.com', this._indicator, 1, this.config.panelPosition);
    }
}
