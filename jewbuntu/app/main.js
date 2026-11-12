#!/usr/bin/env -S gjs -m
/* ShulGo for JewBuntu — the window.
 *
 * The same four lists as the top-bar widget, with room to breathe: a hero card for the minyan you can
 * still make, a place search, and the full zmanim table. It reads the same settings and the same shared
 * code (shulgo/core, shulgo/gnome) as the widget, so the two always agree.
 *
 * Run it from the source tree with:
 *   SHULGO_SCHEMA_DIR=../schemas/build gjs -m app/main.js
 */

import Adw from 'gi://Adw?version=1';
import Gdk from 'gi://Gdk?version=4.0';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Gtk from 'gi://Gtk?version=4.0';
import { programArgs, programInvocationName } from 'system';

import { ShulGoApi } from './shulgo/core/api.js';
import { Cache } from './shulgo/core/cache.js';
import { Store } from './shulgo/core/store.js';
import * as F from './shulgo/core/format.js';
import { makeTransport } from './shulgo/gnome/transport.js';
import { makeNetwork, makeStorage } from './shulgo/gnome/offline.js';
import { Config, SCHEMA_ID, loadApiKey } from './shulgo/gnome/settings.js';
import { Locator } from './shulgo/gnome/geo.js';
import { adwaitaColors } from './shulgo/core/palette.js';
import { accountPage, barPage, placePage } from './shulgo/gnome/prefs-pages.js';

const APP_ID = 'com.shulgo.ShulGo';

const SECTIONS = [
    { id: 'minyanim', title: 'Minyanim', icon: 'alarm-symbolic' },
    { id: 'events', title: 'Events', icon: 'x-office-calendar-symbolic' },
    { id: 'mikvaos', title: 'Mikvaos', icon: 'weather-showers-symbolic' },
    { id: 'zmanim', title: 'Zmanim', icon: 'daytime-sunset-symbolic' },
];

const TEFILLAH_CHIPS = [
    { id: 'next', label: 'Next' },
    { id: 'shacharis', label: 'Shacharis' },
    { id: 'mincha', label: 'Mincha' },
    { id: 'maariv', label: 'Maariv' },
];

/** Where this file is, so it can find shulgo/ and style.css beside it. */
function hereDir() {
    const uri = import.meta.url;

    return Gio.File.new_for_uri(uri).get_parent();
}

/**
 * The settings schema. Normally it is installed in the user's or the system's schema directory;
 * SHULGO_SCHEMA_DIR lets a source checkout run against a compiled copy without installing anything.
 */
function openSettings() {
    const dir = GLib.getenv('SHULGO_SCHEMA_DIR');
    if (dir) {
        const source = Gio.SettingsSchemaSource.new_from_directory(dir,
            Gio.SettingsSchemaSource.get_default(), false);
        const schema = source.lookup(SCHEMA_ID, true);
        if (schema)
            return new Gio.Settings({ settings_schema: schema });
    }

    const found = Gio.SettingsSchemaSource.get_default()?.lookup(SCHEMA_ID, true);
    if (!found) {
        printerr(`ShulGo: the settings schema ${SCHEMA_ID} isn’t installed. Run install.sh, or set `
            + 'SHULGO_SCHEMA_DIR to a directory holding a compiled gschemas.compiled.');
        return null;
    }

    return new Gio.Settings({ settings_schema: found });
}

/** libadwaita renamed these windows to dialogs in 1.5; use whichever this system has. */
function presentPreferences(parent, pages) {
    if (Adw.PreferencesDialog) {
        const dialog = new Adw.PreferencesDialog();
        for (const page of pages)
            dialog.add(page);
        dialog.present(parent);

        return;
    }
    const window = new Adw.PreferencesWindow({ transient_for: parent, modal: true });
    for (const page of pages)
        window.add(page);
    window.present();
}

function presentAbout(parent) {
    const fields = {
        application_name: 'ShulGo',
        application_icon: APP_ID,
        developer_name: 'ShulGo · JewBuntu',
        version: '1.0',
        comments: 'Minyanim, events, mikvaos and zmanim near you, from shulgo.com.',
        website: 'https://shulgo.com',
        license_type: Gtk.License.MIT_X11,
    };
    if (Adw.AboutDialog) {
        new Adw.AboutDialog(fields).present(parent);

        return;
    }
    new Adw.AboutWindow({ ...fields, transient_for: parent, modal: true }).present();
}

function openUri(widget, uri) {
    if (!uri)
        return;
    try {
        Gtk.UriLauncher
            ? new Gtk.UriLauncher({ uri }).launch(widget.get_root(), null, null)
            : Gio.AppInfo.launch_default_for_uri(uri, null);
    } catch (e) {
        logError(e, `ShulGo: could not open ${uri}`);
    }
}

/** A flat pill button, for the tefillah chips. */
function chip(label, active, onClick) {
    const button = new Gtk.ToggleButton({
        label,
        active,
        css_classes: active ? ['shulgo-chip', 'shulgo-chip-active'] : ['shulgo-chip'],
    });
    button.connect('clicked', () => {
        if (button.active)
            onClick();
    });

    return button;
}

const ShulGoWindow = GObject.registerClass(
class ShulGoWindow extends Adw.ApplicationWindow {
    _init(application, { api, config, store }) {
        super._init({
            application,
            title: 'ShulGo',
            default_width: 980,
            default_height: 720,
            width_request: 360,
            height_request: 420,
        });

        this._api = api;
        this._config = config;
        this._store = store;
        this._searchTimer = null;

        this._build();
        this.applyGlass();

        this._unsubscribe = this._store.connect((what) => {
            if (what === 'tick')
                this._renderTick();
            else
                this._render();
        });

        this.connect('close-request', () => {
            this._unsubscribe?.();

            return false;
        });

        this._render();
    }

    /**
     * How much of the desktop shows through. GNOME doesn't blur app windows the way the Shell blurs its
     * own menus, so "frosted" here is the same translucency with more of ShulGo's navy mixed in.
     */
    applyGlass() {
        for (const name of ['blur', 'tint', 'solid'])
            this.remove_css_class(`shulgo-glass-${name}`);
        this.add_css_class(`shulgo-glass-${this._config.glass}`);
    }

    // ---- the frame -------------------------------------------------------------------------

    _build() {
        this._stack = new Adw.ViewStack({ vexpand: true });
        this._pages = new Map();
        for (const section of SECTIONS) {
            const box = new Gtk.Box({ orientation: Gtk.Orientation.VERTICAL, spacing: 18 });
            const clamp = new Adw.Clamp({ maximum_size: 760, tightening_threshold: 600, child: box });
            const scroller = new Gtk.ScrolledWindow({
                hscrollbar_policy: Gtk.PolicyType.NEVER,
                vexpand: true,
                child: clamp,
            });
            this._pages.set(section.id, box);
            const page = this._stack.add_titled(scroller, section.id, section.title);
            page.set_icon_name(section.icon);
        }

        // Sidebar.
        this._sidebarList = new Gtk.ListBox({
            css_classes: ['navigation-sidebar'],
            selection_mode: Gtk.SelectionMode.SINGLE,
        });
        for (const section of SECTIONS) {
            const row = new Adw.ActionRow({ title: section.title });
            row.add_prefix(new Gtk.Image({ icon_name: section.icon }));
            row._sectionId = section.id;
            this._sidebarList.append(row);
        }
        this._sidebarList.connect('row-selected', (_list, row) => {
            if (!row)
                return;
            this._stack.set_visible_child_name(row._sectionId);
            this._config.lastTab = row._sectionId;
            this._split.set_show_content(true);
        });

        const sidebarView = new Adw.ToolbarView({
            content: new Gtk.ScrolledWindow({ hscrollbar_policy: Gtk.PolicyType.NEVER, child: this._sidebarList }),
        });
        sidebarView.add_top_bar(new Adw.HeaderBar({
            title_widget: new Adw.WindowTitle({ title: 'ShulGo' }),
            show_end_title_buttons: false,
        }));

        // Content.
        this._windowTitle = new Adw.WindowTitle({ title: 'ShulGo', subtitle: '' });
        const header = new Adw.HeaderBar({ title_widget: this._windowTitle });

        const refresh = new Gtk.Button({
            icon_name: 'view-refresh-symbolic',
            tooltip_text: 'Ask ShulGo again',
        });
        refresh.connect('clicked', () => this._store.refresh({ fresh: true }));
        header.pack_start(refresh);

        this._searchToggle = new Gtk.ToggleButton({
            icon_name: 'system-search-symbolic',
            tooltip_text: 'Look near another place',
        });
        header.pack_end(this._menuButton());
        header.pack_end(this._searchToggle);

        // The banner shows whatever ShulGo said went wrong, which is not ours to parse as markup.
        this._banner = new Adw.Banner({ revealed: false, button_label: 'Try again', use_markup: false });
        this._banner.connect('button-clicked', () => this._store.refresh({ fresh: true }));

        const contentBox = new Gtk.Box({ orientation: Gtk.Orientation.VERTICAL });
        contentBox.append(this._banner);
        contentBox.append(this._searchBar());
        contentBox.append(this._stack);

        const contentView = new Adw.ToolbarView({ content: contentBox });
        contentView.add_top_bar(header);

        this._split = new Adw.NavigationSplitView({
            sidebar: new Adw.NavigationPage({ title: 'ShulGo', child: sidebarView }),
            content: new Adw.NavigationPage({ title: 'ShulGo', child: contentView }),
            min_sidebar_width: 200,
            max_sidebar_width: 260,
        });

        const breakpoint = new Adw.Breakpoint({
            condition: Adw.BreakpointCondition.parse('max-width: 640px'),
        });
        breakpoint.add_setter(this._split, 'collapsed', true);
        this.add_breakpoint(breakpoint);

        this.set_content(this._split);

        // Open on whatever was last looked at.
        const wanted = SECTIONS.findIndex((s) => s.id === this._config.lastTab);
        this._sidebarList.select_row(this._sidebarList.get_row_at_index(Math.max(0, wanted)));
    }

    _menuButton() {
        const menu = new Gio.Menu();
        menu.append('Settings', 'app.preferences');
        menu.append('Open shulgo.com', 'app.website');
        menu.append('About ShulGo', 'app.about');

        return new Gtk.MenuButton({
            icon_name: 'open-menu-symbolic',
            menu_model: menu,
            tooltip_text: 'Main menu',
        });
    }

    /** A place box that offers ShulGo's own matches as you type. */
    _searchBar() {
        this._searchEntry = new Gtk.SearchEntry({
            placeholder_text: 'A city, neighborhood or zip — “Lakewood, NJ”, “Boro Park”, “11230”',
            hexpand: true,
        });
        this._searchResults = new Gtk.ListBox({
            css_classes: ['boxed-list'],
            selection_mode: Gtk.SelectionMode.NONE,
            visible: false,
            margin_top: 6,
        });

        const box = new Gtk.Box({ orientation: Gtk.Orientation.VERTICAL, spacing: 0 });
        box.append(this._searchEntry);
        box.append(this._searchResults);

        const bar = new Gtk.SearchBar({ child: new Adw.Clamp({ maximum_size: 640, child: box }) });
        bar.connect_entry(this._searchEntry);
        this._searchToggle.bind_property('active', bar, 'search-mode-enabled',
            GObject.BindingFlags.BIDIRECTIONAL);

        this._searchEntry.connect('search-changed', () => this._searchLater());

        return bar;
    }

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
        const text = this._searchEntry.text.trim();
        let child = this._searchResults.get_first_child();
        while (child) {
            const next = child.get_next_sibling();
            this._searchResults.remove(child);
            child = next;
        }
        if (text.length < 2) {
            this._searchResults.visible = false;

            return;
        }

        const answer = await this._api.places(text);
        if (!answer.ok || !answer.data.length) {
            this._searchResults.visible = false;

            return;
        }

        for (const match of answer.data.slice(0, 6)) {
            const row = new Adw.ActionRow({
                title: match.label,
                subtitle: match.shuls ? `${match.shuls} shul${match.shuls === 1 ? '' : 's'}` : null,
                activatable: true,
            });
            row.connect('activated', () => {
                this._config.settings.set_boolean('use-geolocation', false);
                this._config.settings.set_string('place', match.label);
                this._config.rememberPoint({ lat: match.lat, lng: match.lng, label: match.label });
                this._searchToggle.active = false;
                this._searchEntry.text = '';
                this._store.refresh({ fresh: true });
            });
            this._searchResults.append(row);
        }
        this._searchResults.visible = true;
    }

    // ---- drawing ---------------------------------------------------------------------------

    _renderTick() {
        if (this._config.lastTab === 'minyanim' || this._config.lastTab === 'zmanim')
            this._render();
    }

    _render() {
        const { state } = this._store;

        this._windowTitle.title = state.place?.label
            ? (state.place.label === 'your location' ? 'Near you' : state.place.label)
            : 'ShulGo';
        this._windowTitle.subtitle = [
            F.hebrewDayLine(state.today),
            state.stale ? F.takenAt(state.staleSince) : F.updatedAgo(state.updatedAt),
        ].filter((x) => x).join(' · ');

        // The banner is how the window says "this is older than it looks" without taking the list away.
        const notice = F.offlineNotice(state, this._store.hasAnything);
        if (notice && this._store.hasAnything) {
            // AdwBanner gives one line and ellipsises it, so it gets the short form rather than the
            // title and body run together and cut off mid-sentence.
            this._banner.title = notice.short;
            this._banner.button_label = 'Try now';
            this._banner.revealed = true;
        } else if (state.error && !state.needsKey && !state.needsPlace && !notice) {
            this._banner.title = state.error.message;
            this._banner.button_label = 'Try again';
            this._banner.revealed = true;
        } else {
            this._banner.revealed = false;
        }

        // Mikvaos only exist for keys that may read them.
        const mikvahRow = this._sidebarList.get_row_at_index(2);
        if (mikvahRow)
            mikvahRow.visible = state.mikvaos !== null;

        this._renderMinyanim();
        this._renderEvents();
        this._renderMikvaos();
        this._renderZmanim();
    }

    _clear(id) {
        const box = this._pages.get(id);
        let child = box.get_first_child();
        while (child) {
            const next = child.get_next_sibling();
            box.remove(child);
            child = next;
        }

        return box;
    }

    /** The one notice that stands in for a whole page: no key, no place, nothing found. */
    _status(box, { icon, title, description, actionLabel = null, onAction = null }) {
        const page = new Adw.StatusPage({ icon_name: icon, title, description, vexpand: true });
        if (actionLabel) {
            const button = new Gtk.Button({
                label: actionLabel,
                halign: Gtk.Align.CENTER,
                css_classes: ['suggested-action', 'pill'],
            });
            button.connect('clicked', onAction);
            page.set_child(button);
        }
        box.append(page);
    }

    _gate(box) {
        const { state } = this._store;

        // Nothing saved to fall back on: say so kindly, and leave the trying to the background.
        const notice = F.offlineNotice(state, this._store.hasAnything);
        if (notice && !this._store.hasAnything && !state.needsKey && !state.needsPlace) {
            this._status(box, {
                icon: 'network-offline-symbolic',
                title: notice.title,
                description: notice.body,
                actionLabel: 'Try now',
                onAction: () => this._store.refresh({ fresh: true }),
            });

            return true;
        }

        if (state.needsKey) {
            this._status(box, {
                icon: 'dialog-password-symbolic',
                title: 'Add your ShulGo API key',
                description: 'Ask ShulGo for one at shulgo.com/developers/request — they email you a '
                    + 'link that shows your key. Settings has the button, and the box to paste it into.',
                actionLabel: 'Open Settings',
                onAction: () => this.application.activate_action('preferences', null),
            });

            return true;
        }
        if (state.needsPlace) {
            this._status(box, {
                icon: 'find-location-symbolic',
                title: 'Where are you?',
                description: 'Turn on “Use this computer’s location”, or search for a city, neighborhood or zip.',
                actionLabel: 'Search for a place',
                onAction: () => {
                    this._searchToggle.active = true;
                    this._searchEntry.grab_focus();
                },
            });

            return true;
        }

        return false;
    }

    _renderMinyanim() {
        const box = this._clear('minyanim');
        if (this._gate(box))
            return;

        const { state } = this._store;
        const headline = this._store.headline;

        if (headline)
            box.append(this._hero(headline));

        const chips = new Gtk.Box({ spacing: 6, halign: Gtk.Align.CENTER });
        for (const c of TEFILLAH_CHIPS) {
            chips.append(chip(c.label, this._config.tefillah === c.id, () => {
                this._config.tefillah = c.id;
                this._store.refresh();
            }));
        }
        box.append(chips);

        const rest = state.minyanim.filter((m) => m !== headline);
        if (!rest.length && !headline) {
            this._status(box, {
                icon: 'alarm-symbolic',
                title: `Nothing in the next ${this._config.windowMinutes} minutes`,
                description: 'Try looking further ahead, or a different tefillah.',
            });

            return;
        }

        const group = new Adw.PreferencesGroup({ title: 'Also coming up' });
        for (const item of rest.slice(0, 40))
            group.add(this._minyanRow(item));
        if (rest.length)
            box.append(group);

        box.append(this._moreButton(`${this._api.siteUrl}/next`, 'See every minyan on ShulGo'));
    }

    /** The big card: the soonest minyan you could still get to. */
    _hero(item) {
        const urgency = F.urgency(item);
        const card = new Gtk.Box({
            orientation: Gtk.Orientation.VERTICAL,
            spacing: 4,
            css_classes: ['card', 'shulgo-hero', `shulgo-hero-${urgency}`],
        });

        const top = new Gtk.Box({ spacing: 14 });
        const timeBox = new Gtk.Box({ orientation: Gtk.Orientation.VERTICAL, spacing: 0 });
        timeBox.append(new Gtk.Label({
            label: item.display_time || '',
            xalign: 0,
            css_classes: ['shulgo-hero-time'],
        }));
        timeBox.append(new Gtk.Label({
            label: F.countdown(F.minutesUntil(item.starts_at)),
            xalign: 0,
            css_classes: ['shulgo-hero-countdown', `shulgo-urgency-${urgency}`],
        }));
        top.append(timeBox);

        const textBox = new Gtk.Box({ orientation: Gtk.Orientation.VERTICAL, spacing: 2, hexpand: true, valign: Gtk.Align.CENTER });
        textBox.append(new Gtk.Label({
            label: `${F.tefillahLabel(item.tefillah)}${item.kind === 'live' ? ' · forming now' : ''}`,
            xalign: 0,
            css_classes: ['shulgo-hero-title'],
        }));
        textBox.append(new Gtk.Label({
            label: item.shul?.display_name ?? 'Nearby',
            xalign: 0,
            wrap: true,
            css_classes: ['shulgo-hero-shul'],
        }));
        const detail = [F.miles(item.distance_miles), F.travel(item, this._config.travelMode), item.nusach, F.minyanNote(item)]
            .filter((x) => x).join(' · ');
        if (detail)
            textBox.append(new Gtk.Label({ label: detail, xalign: 0, wrap: true, css_classes: ['dim-label'] }));
        top.append(textBox);
        card.append(top);

        const buttons = new Gtk.Box({ spacing: 8, halign: Gtk.Align.END, margin_top: 8 });
        const destination = F.minyanDestination(item);
        if (destination) {
            const directions = new Gtk.Button({ label: 'Directions', css_classes: ['suggested-action'] });
            directions.connect('clicked', () => openUri(this, F.mapsUri(destination)));
            buttons.append(directions);
        }
        const shulUrl = item.shul?.url ?? (item.shul?.slug ? `${this._api.siteUrl}/shul/${item.shul.slug}` : null);
        if (shulUrl) {
            const open = new Gtk.Button({ label: 'This shul' });
            open.connect('clicked', () => openUri(this, shulUrl));
            buttons.append(open);
        }
        if (buttons.get_first_child())
            card.append(buttons);

        return card;
    }

    _minyanRow(item) {
        const urgency = F.urgency(item);
        const row = new Adw.ActionRow({
            title: `${item.display_time} · ${F.tefillahLabel(item.tefillah)}`,
            subtitle: F.minyanSubtitle(item, this._config.travelMode),
            activatable: true,
            use_markup: false,
        });

        const dot = new Gtk.Image({
            icon_name: 'media-record-symbolic',
            css_classes: ['shulgo-dot', `shulgo-urgency-${urgency}`],
            tooltip_text: {
                comfortable: 'You have time',
                tight: 'You would have to leave now',
                missed: 'Too far to make it',
                unknown: 'ShulGo couldn’t work out the drive',
            }[urgency],
        });
        row.add_prefix(dot);

        const countdown = new Gtk.Label({
            label: F.countdown(F.minutesUntil(item.starts_at)),
            css_classes: ['shulgo-row-countdown', `shulgo-urgency-${urgency}`],
            valign: Gtk.Align.CENTER,
        });
        row.add_suffix(countdown);

        const destination = F.minyanDestination(item);
        if (destination) {
            const directions = new Gtk.Button({
                icon_name: 'find-location-symbolic',
                css_classes: ['flat'],
                valign: Gtk.Align.CENTER,
                tooltip_text: 'Directions',
            });
            directions.connect('clicked', () => openUri(this, F.mapsUri(destination)));
            row.add_suffix(directions);
        }

        const shulUrl = item.shul?.url ?? (item.shul?.slug ? `${this._api.siteUrl}/shul/${item.shul.slug}` : null);
        if (shulUrl)
            row.connect('activated', () => openUri(this, shulUrl));

        return row;
    }

    _renderEvents() {
        const box = this._clear('events');
        if (this._gate(box))
            return;

        const events = this._store.state.events ?? [];
        if (!events.length) {
            this._status(box, {
                icon: 'x-office-calendar-symbolic',
                title: 'No events coming up near here',
                description: 'Events that shuls send in to ShulGo show up here, soonest first.',
            });

            return;
        }

        const group = new Adw.PreferencesGroup({ title: 'Coming up' });
        for (const event of events) {
            const row = new Adw.ActionRow({
                title: event.title || '',
                subtitle: [event.when, event.where, event.online ? 'Online' : '', F.miles(event.distance_miles)]
                    .filter((x) => x).join(' · '),
                activatable: true,
                use_markup: false,
            });
            row.add_prefix(new Gtk.Label({
                label: F.eventDate(event.date),
                css_classes: ['shulgo-event-date'],
                valign: Gtk.Align.CENTER,
                width_chars: 9,
                xalign: 0,
            }));
            const url = event.url || `${this._api.siteUrl}/events`;
            row.connect('activated', () => openUri(this, url));
            group.add(row);
        }
        box.append(group);
        box.append(this._moreButton(`${this._api.siteUrl}/events`, 'All events on ShulGo'));
    }

    _renderMikvaos() {
        const box = this._clear('mikvaos');
        if (this._gate(box))
            return;

        const mikvaos = this._store.state.mikvaos ?? [];
        if (!mikvaos.length) {
            this._status(box, {
                icon: 'weather-showers-symbolic',
                title: 'No mikvaos listed near here',
                description: '',
            });

            return;
        }

        const group = new Adw.PreferencesGroup({ title: 'Nearest first' });
        for (const mikvah of mikvaos) {
            const whom = (mikvah.for ?? []).map(F.forWhomLabel).join(', ');
            const row = new Adw.ActionRow({
                title: mikvah.name || '',
                subtitle: [whom, mikvah.address, mikvah.city, F.miles(mikvah.distance_mi)]
                    .filter((x) => x).join(' · '),
                activatable: true,
                use_markup: false,
            });
            row.add_prefix(new Gtk.Image({ icon_name: 'weather-showers-symbolic', css_classes: ['shulgo-mikvah-icon'] }));

            const destination = mikvah.lat !== null && mikvah.lat !== undefined
                ? `${mikvah.lat},${mikvah.lng}`
                : [mikvah.address, mikvah.city].filter((x) => x).join(', ');
            if (destination) {
                const directions = new Gtk.Button({
                    icon_name: 'find-location-symbolic',
                    css_classes: ['flat'],
                    valign: Gtk.Align.CENTER,
                    tooltip_text: 'Directions',
                });
                directions.connect('clicked', () => openUri(this, F.mapsUri(destination)));
                row.add_suffix(directions);
            }
            row.connect('activated', () => openUri(this, mikvah.url));
            group.add(row);
        }
        box.append(group);

        // mikvah.org's terms: their name goes on the list.
        const credit = F.creditLine(this._store.state.mikvaosCredit);
        if (credit?.text) {
            const button = new Gtk.Button({
                label: credit.text,
                css_classes: ['flat', 'shulgo-credit'],
                halign: Gtk.Align.CENTER,
            });
            button.connect('clicked', () => openUri(this, credit.url));
            box.append(button);
        }
    }

    _renderZmanim() {
        const box = this._clear('zmanim');
        if (this._gate(box))
            return;

        const rows = F.zmanimList(this._store.state.zmanim);
        if (!rows.length) {
            this._status(box, { icon: 'daytime-sunset-symbolic', title: 'No zmanim yet', description: '' });

            return;
        }

        const meta = this._store.state.zmanimMeta;
        const group = new Adw.PreferencesGroup({
            title: 'Today',
            description: [meta.date, meta.timezone].filter((x) => x).join(' · '),
        });
        if (this._store.zmanimOutOfDate) {
            group.set_description(`These were worked out for ${this._store.state.zmanimForDate}, not today. `
                + 'Today’s come down as soon as ShulGo is back.');
        }

        for (const zman of rows) {
            const row = new Adw.ActionRow({
                title: zman.label,
                subtitle: zman.about || '',
                css_classes: zman.isNext ? ['shulgo-zman-next'] : (zman.past ? ['dim-label'] : []),
                use_markup: false,
            });
            row.add_suffix(new Gtk.Label({
                label: zman.display,
                css_classes: zman.isNext ? ['shulgo-zman-time', 'accent'] : ['shulgo-zman-time'],
                valign: Gtk.Align.CENTER,
            }));
            group.add(row);
        }
        box.append(group);

        const candles = F.candleLighting(this._store.state.today);
        if (candles) {
            box.append(new Gtk.Label({
                label: `Candle lighting ${candles}`,
                css_classes: ['shulgo-candles'],
                halign: Gtk.Align.CENTER,
            }));
        }
    }

    _moreButton(url, label) {
        const button = new Gtk.Button({ label, css_classes: ['flat'], halign: Gtk.Align.CENTER, margin_bottom: 12 });
        button.connect('clicked', () => openUri(this, url));

        return button;
    }
});

const ShulGoApp = GObject.registerClass(
class ShulGoApp extends Adw.Application {
    _init() {
        super._init({ application_id: APP_ID, flags: Gio.ApplicationFlags.DEFAULT_FLAGS });
    }

    vfunc_startup() {
        super.vfunc_startup();

        const settings = openSettings();
        if (!settings) {
            this.quit();

            return;
        }

        this._config = new Config(settings);
        this._network = makeNetwork();
        this._cache = new Cache(makeStorage());
        this._api = new ShulGoApi({
            baseUrl: this._config.baseUrl,
            apiKey: loadApiKey(),
            transport: makeTransport({ userAgent: 'JewBuntu-ShulGo-App/1.0' }),
            cache: this._cache,
            isOnline: this._network.isOnline,
        });
        this._store = new Store(this._api, this._config, new Locator(this._api, this._config, APP_ID),
            this._network);
        this._store.connect((what) => {
            if (what === 'changed')
                this._cache.save();
        });

        this._loadStyle();
        this._addActions();

        this._config.watch(
            ['api-base-url', 'use-geolocation', 'place', 'window-minutes', 'travel-mode', 'tefillah', 'mikvah-for'],
            (key) => {
                if (key === 'api-base-url')
                    this._api.reconfigure({ baseUrl: this._config.baseUrl });
                this._api.forget();
                this._store.refresh();
            });
        this._config.watch(['refresh-seconds'], () => this._store.restartTimers());
        this._config.watch(['glass'], () => this._window?.applyGlass());

        this._store.start();
    }

    vfunc_activate() {
        if (!this._window)
            this._window = new ShulGoWindow(this, { api: this._api, config: this._config, store: this._store });
        this._window.present();
        this._store.refresh();
    }

    vfunc_shutdown() {
        this._cache?.save();
        this._store?.destroy();
        this._config?.destroy();
        super.vfunc_shutdown();
    }

    /**
     * Two stylesheets: the shapes, from style.css, and the colours, written out of core/palette.js.
     * GTK has no prefers-color-scheme, so the colours are rewritten whenever the system switches
     * between light and dark.
     */
    _loadStyle() {
        const display = Gdk.Display.get_default();

        const css = hereDir().get_child('style.css');
        if (css.query_exists(null)) {
            const shapes = new Gtk.CssProvider();
            shapes.load_from_path(css.get_path());
            Gtk.StyleContext.add_provider_for_display(display, shapes, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION);
        }

        this._palette = new Gtk.CssProvider();
        Gtk.StyleContext.add_provider_for_display(display, this._palette,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION - 1);

        const style = Adw.StyleManager.get_default();
        const paint = () => {
            const css2 = adwaitaColors(style.dark);
            if (this._palette.load_from_string)
                this._palette.load_from_string(css2);
            else
                this._palette.load_from_data(css2, -1);
        };
        style.connect('notify::dark', paint);
        paint();
    }

    _addActions() {
        const add = (name, run) => {
            const action = new Gio.SimpleAction({ name });
            action.connect('activate', run);
            this.add_action(action);
        };

        add('preferences', () => {
            const apiFor = (key = null) => new ShulGoApi({
                baseUrl: this._config.baseUrl,
                apiKey: key ?? loadApiKey(),
                transport: makeTransport({ userAgent: 'JewBuntu-ShulGo-App/1.0' }),
            });
            presentPreferences(this._window, [
                placePage(this._config.settings, apiFor),
                barPage(this._config.settings),
                accountPage(this._config.settings, apiFor),
            ]);
        });
        add('website', () => openUri(this._window, this._api.siteUrl));
        add('about', () => presentAbout(this._window));
        add('refresh', () => this._store.refresh({ fresh: true }));
        add('quit', () => this.quit());

        this.set_accels_for_action('app.refresh', ['<Control>r', 'F5']);
        this.set_accels_for_action('app.quit', ['<Control>q']);
        this.set_accels_for_action('app.preferences', ['<Control>comma']);
    }
});

new ShulGoApp().run([programInvocationName, ...programArgs]);
