/* The settings pages, built once and shown in two places: the top-bar widget's gear button opens them
 * through prefs.js, and the ShulGo app shows the same pages in its own Preferences dialog. One copy means
 * the two can't drift.
 */

import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

import { loadApiKey, looksLikeKey, saveApiKey } from './settings.js';

/** An Adw.ComboRow backed by a settings string: labels on screen, values in GSettings. */
function comboRow({ title, subtitle = null, settings, key, choices }) {
    const row = new Adw.ComboRow({
        title,
        subtitle,
        model: Gtk.StringList.new(choices.map((c) => c.label)),
    });
    const values = choices.map((c) => c.value);
    const current = settings.get_string(key);
    row.selected = Math.max(0, values.indexOf(current));
    row.connect('notify::selected', () => settings.set_string(key, values[row.selected]));
    settings.connect(`changed::${key}`, () => {
        const want = Math.max(0, values.indexOf(settings.get_string(key)));
        if (row.selected !== want)
            row.selected = want;
    });

    return row;
}

/**
 * An Adw.SpinRow backed by an integer setting.
 *
 * Wired by hand rather than with settings.bind: the row's value is a double and the key is an int, and
 * whether GSettings transforms between them quietly or complains is not something to find out in front
 * of someone. Two connections, an explicit round, and a guard so the two don't chase each other.
 */
function spinRow({ title, subtitle = null, settings, key, min, max, step }) {
    const row = new Adw.SpinRow({
        title,
        subtitle,
        adjustment: new Gtk.Adjustment({ lower: min, upper: max, step_increment: step, page_increment: step }),
    });

    row.value = settings.get_int(key);
    row.connect('notify::value', () => {
        const wanted = Math.round(row.value);
        if (settings.get_int(key) !== wanted)
            settings.set_int(key, wanted);
    });
    settings.connect(`changed::${key}`, () => {
        const saved = settings.get_int(key);
        if (Math.round(row.value) !== saved)
            row.value = saved;
    });

    return row;
}

// ---- where and when --------------------------------------------------------------------

export function placePage(settings, apiFor) {
    const page = new Adw.PreferencesPage({
        title: 'Where and when',
        icon_name: 'find-location-symbolic',
    });

    const where = new Adw.PreferencesGroup({
        title: 'Where to look',
        description: 'ShulGo looks for minyanim, events and mikvaos near one point.',
    });
    page.add(where);

    const useGeo = new Adw.SwitchRow({
        title: 'Use this computer’s location',
        use_markup: false,
    });
    settings.bind('use-geolocation', useGeo, 'active', Gio.SettingsBindFlags.DEFAULT);
    where.add(useGeo);

    // Say what actually happened last time, rather than leaving someone who switched this on and saw
    // nothing to wonder whether it is broken. The widget writes this down; we are a separate process
    // and cannot ask it directly.
    const sayHow = () => {
        if (!settings.get_boolean('use-geolocation')) {
            useGeo.subtitle = 'Off: ShulGo looks near the place below.';

            return;
        }
        useGeo.subtitle = {
            ok: 'Working: ShulGo is using where this computer says it is.',
            off: 'Your system’s Location Services are switched off, so the place below is being used '
                + 'instead. Turn them on in Settings, under Privacy.',
            error: 'This computer couldn’t say where it is, so the place below is being used instead.',
        }[settings.get_string('location-status')]
            ?? 'Asks the system where you are. The place below is used whenever it can’t say.';
    };
    sayHow();
    settings.connect('changed::location-status', sayHow);
    settings.connect('changed::use-geolocation', sayHow);

    // What ShulGo makes of what was typed, with the nearest matches to pick from.
    const suggestions = new Adw.ExpanderRow({
        title: 'Matches',
        subtitle: 'Type a city, neighborhood or zip above, then press Enter.',
        visible: false,
        // Its subtitle ends up carrying what was typed and what ShulGo said back, neither of which is
        // ours to parse as markup.
        use_markup: false,
    });

    const place = new Adw.EntryRow({
        title: 'Or a place',
        text: settings.get_string('place'),
        show_apply_button: true,
    });
    place.connect('apply', () => findPlace(settings, place, suggestions, apiFor));
    where.add(place);
    where.add(suggestions);

    const when = new Adw.PreferencesGroup({
        title: 'How far ahead',
        description: 'A longer window finds more minyanim; a shorter one keeps the list to what you can still reach.',
    });
    page.add(when);

    when.add(spinRow({
        title: 'Look ahead',
        subtitle: 'Minutes',
        settings, key: 'window-minutes', min: 15, max: 360, step: 15,
    }));

    when.add(comboRow({
        title: 'How you get there',
        subtitle: 'Used to work out whether you can still make it in time.',
        settings, key: 'travel-mode',
        choices: [{ label: 'Driving', value: 'drive' }, { label: 'Walking', value: 'walk' }],
    }));

    when.add(comboRow({
        title: 'Which tefillah',
        settings, key: 'tefillah',
        choices: [
            { label: 'Whatever is next', value: 'next' },
            { label: 'Shacharis', value: 'shacharis' },
            { label: 'Mincha', value: 'mincha' },
            { label: 'Maariv', value: 'maariv' },
        ],
    }));

    const mikvaos = new Adw.PreferencesGroup({ title: 'Mikvaos' });
    page.add(mikvaos);
    mikvaos.add(comboRow({
        title: 'Which mikvaos to list',
        settings, key: 'mikvah-for',
        choices: [
            { label: 'All of them', value: 'all' },
            { label: 'Women', value: 'women' },
            { label: 'Men', value: 'men' },
            { label: 'Keilim', value: 'keilim' },
        ],
    }));

    return page;
}

/** Asks ShulGo what the typed place might be, and offers the matches. */
async function findPlace(settings, entryRow, expander, apiFor) {
    const text = entryRow.text.trim();
    settings.set_string('place', text);
    if (!text) {
        expander.visible = false;

        return;
    }

    expander.visible = true;
    expander.subtitle = 'Looking…';
    for (const row of expander._rows ?? [])
        expander.remove(row);
    expander._rows = [];

    const api = apiFor();
    const answer = await api.places(text);
    if (!answer.ok) {
        expander.subtitle = answer.message;

        return;
    }
    if (!answer.data.length) {
        expander.subtitle = `ShulGo doesn’t know “${text}”. Try a city with its state or country, or a zip.`;

        return;
    }

    expander.subtitle = 'Pick the one you mean.';
    expander.expanded = true;
    for (const match of answer.data) {
        const row = new Adw.ActionRow({
            title: match.label,
            subtitle: match.shuls ? `${match.shuls} shul${match.shuls === 1 ? '' : 's'}` : null,
            activatable: true,
            use_markup: false,
        });
        row.connect('activated', () => {
            settings.set_string('place', match.label);
            settings.set_double('latitude', match.lat);
            settings.set_double('longitude', match.lng);
            settings.set_string('location-label', match.label);
            settings.set_boolean('use-geolocation', false);
            entryRow.text = match.label;
            expander.subtitle = `Looking near ${match.label}.`;
            expander.expanded = false;
        });
        expander.add_row(row);
        expander._rows.push(row);
    }
}

// ---- how it looks ----------------------------------------------------------------------

export function barPage(settings) {
    const page = new Adw.PreferencesPage({ title: 'Top bar', icon_name: 'preferences-desktop-appearance-symbolic' });

    const bar = new Adw.PreferencesGroup({ title: 'In the top bar' });
    page.add(bar);

    bar.add(comboRow({
        title: 'What it shows',
        settings, key: 'panel-text',
        choices: [
            { label: 'Tefillah, time and countdown', value: 'full' },
            { label: 'Countdown only', value: 'countdown' },
            { label: 'Time only', value: 'time' },
            { label: 'Just the icon', value: 'icon' },
        ],
    }));

    bar.add(comboRow({
        title: 'Where it sits',
        subtitle: 'Takes effect at once.',
        settings, key: 'panel-position',
        choices: [
            { label: 'Right, by the clock’s indicators', value: 'right' },
            { label: 'Centre, next to the clock', value: 'center' },
            { label: 'Left, by Activities', value: 'left' },
        ],
    }));

    bar.add(comboRow({
        title: 'Glass',
        subtitle: 'The menu is ShulGo navy either way; this is how much of the desktop shows through it.',
        settings, key: 'glass',
        // 'blur' is deliberately not offered any more: a Shell effect ignores border-radius, so it
        // drew a square blurred panel behind the rounded card. The value still works if somebody has
        // it saved — it renders see-through — it is just not something to choose afresh.
        choices: [
            { label: 'See-through', value: 'tint' },
            { label: 'Solid navy', value: 'solid' },
        ],
    }));

    const menu = new Adw.PreferencesGroup({ title: 'In the menu' });
    page.add(menu);

    menu.add(spinRow({
        title: 'Rows in each list',
        subtitle: 'The rest stay on ShulGo.',
        settings, key: 'list-length', min: 3, max: 40, step: 1,
    }));

    menu.add(spinRow({
        title: 'Ask ShulGo again every',
        subtitle: 'Seconds. Countdowns tick on their own in between, without asking.',
        settings, key: 'refresh-seconds', min: 60, max: 3600, step: 30,
    }));

    return page;
}

// ---- the key ---------------------------------------------------------------------------

export function accountPage(settings, apiFor) {
    const page = new Adw.PreferencesPage({ title: 'ShulGo', icon_name: 'dialog-password-symbolic' });

    const group = new Adw.PreferencesGroup({
        title: 'API key',
        // Markup, like AdwStatusPage's description — so any ampersand has to be written out.
        description: 'ShulGo gives out its own keys. Ask for one below: the team reads every request and '
            + 'emails you a link that shows your key once. It is then kept in '
            + '~/.config/jewbuntu/shulgo.conf, readable only by you.',
    });
    page.add(group);

    // How an ordinary person gets a key. The admin page is no use to them — it sits behind ShulGo's own
    // staff login — so the request form is the row that comes first.
    const ask = new Adw.ActionRow({
        title: 'Ask ShulGo for a key',
        subtitle: 'Opens the request form in your browser',
        activatable: true,
        use_markup: false,
    });
    ask.add_suffix(new Gtk.Image({ icon_name: 'adw-external-link-symbolic' }));
    ask.connect('activated', () => {
        const url = `${apiFor().siteUrl}/developers/request`;
        try {
            Gtk.UriLauncher
                ? new Gtk.UriLauncher({ uri: url }).launch(ask.get_root(), null, null)
                : Gio.AppInfo.launch_default_for_uri(url, null);
        } catch (e) {
            logError(e, `ShulGo: could not open ${url}`);
        }
    });
    group.add(ask);

    const entry = new Adw.PasswordEntryRow({ title: 'Key', text: loadApiKey() });
    group.add(entry);

    // Its subtitle carries ShulGo's own message when a key is refused.
    const status = new Adw.ActionRow({ title: 'Not checked yet', subtitle: '', use_markup: false });
    group.add(status);

    const buttons = new Gtk.Box({ spacing: 8, halign: Gtk.Align.END, margin_top: 8 });
    const save = new Gtk.Button({ label: 'Save', css_classes: ['suggested-action'] });
    const test = new Gtk.Button({ label: 'Save and test' });
    buttons.append(test);
    buttons.append(save);
    group.add(buttons);

    const put = () => {
        const key = entry.text.trim();
        if (key && !looksLikeKey(key)) {
            status.title = 'That doesn’t look like a ShulGo key';
            status.subtitle = 'A key looks like sg_live_ followed by 40 letters and digits.';

            return false;
        }
        if (!saveApiKey(key)) {
            status.title = 'The key couldn’t be saved';
            status.subtitle = `Check that ${GLib.get_user_config_dir()}/jewbuntu is writable.`;

            return false;
        }
        status.title = key ? 'Key saved' : 'Key removed';
        status.subtitle = '';

        return true;
    };

    save.connect('clicked', () => put());
    test.connect('clicked', async () => {
        if (!put())
            return;
        status.title = 'Asking ShulGo…';
        const api = apiFor(entry.text.trim());
        const answer = await api.places('Lakewood, NJ');
        if (answer.ok) {
            status.title = 'The key works';
            status.subtitle = `${api.siteUrl} answered.`;
        } else {
            status.title = 'ShulGo wouldn’t accept it';
            status.subtitle = answer.message;
        }
    });

    const mikvahNote = new Adw.PreferencesGroup({
        title: 'About mikvaos',
        description: 'The mikvah listings come from mikvah.org, whose terms keep them to ShulGo’s own '
            + 'apps. A key you ask for here reads everything else — minyanim, events, zmanim — but the '
            + 'Mikvaos tab stays hidden. If you run ShulGo yourself, an admin can issue a key of the kind '
            + 'that includes them under Admin › System › API &amp; apps.',
    });
    page.add(mikvahNote);

    const advanced = new Adw.PreferencesGroup({
        title: 'Advanced',
        description: 'Leave this alone unless you run your own ShulGo.',
    });
    page.add(advanced);

    const base = new Adw.EntryRow({
        title: 'API address',
        text: settings.get_string('api-base-url'),
        show_apply_button: true,
    });
    base.connect('apply', () => settings.set_string('api-base-url', base.text.trim()));
    advanced.add(base);

    const reset = new Adw.ActionRow({
        title: 'Back to shulgo.com',
        activatable: true,
    });
    reset.connect('activated', () => {
        settings.reset('api-base-url');
        base.text = settings.get_string('api-base-url');
    });
    advanced.add(reset);

    return page;
}

