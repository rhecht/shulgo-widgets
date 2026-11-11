/* The settings window behind the top-bar widget's gear button.
 *
 * The pages themselves live in shulgo/gnome/prefs-pages.js, which the ShulGo app shows too, so the two
 * halves of the widget are configured in exactly the same words. Everything writes to the same GSettings;
 * the API key goes to ~/.config/jewbuntu/shulgo.conf, owner-only, and the widget notices it change.
 */

import { ExtensionPreferences } from 'resource:///org/gnome/shell/extensions/prefs.js';

import { ShulGoApi } from './shulgo/core/api.js';
import { makeTransport } from './shulgo/gnome/transport.js';
import { loadApiKey } from './shulgo/gnome/settings.js';
import { accountPage, barPage, placePage } from './shulgo/gnome/prefs-pages.js';

export default class ShulGoPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        const apiFor = (key = null) => new ShulGoApi({
            baseUrl: settings.get_string('api-base-url'),
            apiKey: key ?? loadApiKey(),
            transport: makeTransport({ userAgent: 'JewBuntu-ShulGo-Prefs/1.0' }),
        });

        window.set_default_size(640, 760);
        window.add(placePage(settings, apiFor));
        window.add(barPage(settings));
        window.add(accountPage(settings, apiFor));
    }
}
