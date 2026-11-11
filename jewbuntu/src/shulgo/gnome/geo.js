/* Where are we? In order: this computer's own location (GeoClue), then the place typed in settings, then
 * the last point we settled on. Anything that goes wrong just falls through to the next one — a widget in
 * the top bar can't put up a dialog about it.
 */

import GLib from 'gi://GLib';
import Gio from 'gi://Gio';

const BUS = 'org.freedesktop.GeoClue2';
const MANAGER_PATH = '/org/freedesktop/GeoClue2/Manager';

/** GeoClue's accuracy levels. 4 is the city, 6 the street — the city is plenty for finding a minyan. */
const ACCURACY_CITY = 4;

/** Don't ask the system for a fix more often than this (seconds). */
const FIX_TTL = 600;

export class Locator {
    /**
     * @param {import('../core/api.js').ShulGoApi} api
     * @param {import('../gnome/settings.js').Config} config
     * @param {string} [desktopId] the .desktop name GeoClue identifies us by
     */
    constructor(api, config, desktopId = 'org.jewbuntu.ShulGo') {
        this._api = api;
        this._config = config;
        this._desktopId = desktopId;
        this._fix = null;         // {lat, lng, at}
        this._client = null;      // GeoClue client proxy
        this._clientPath = null;
        this._geoclueFailed = false;
    }

    /**
     * @param {object} [opts]
     * @param {boolean} [opts.fresh] ask the system again even if we have a recent fix
     * @returns {Promise<{lat: number, lng: number, label: string, source: string}|null>}
     */
    async resolve({ fresh = false } = {}) {
        if (this._config.useGeolocation) {
            const here = await this._fromSystem({ fresh });
            if (here) {
                this._config.rememberPoint(here);

                return here;
            }
        }

        const typed = this._config.place.trim();
        if (typed) {
            const found = await this._fromPlace(typed);
            if (found) {
                this._config.rememberPoint(found);

                return found;
            }
        }

        const remembered = this._config.point;
        if (remembered)
            return { ...remembered, source: 'remembered' };

        return null;
    }

    /** Looks a typed place up through ShulGo, so "Boro Park" and "11230" both work. */
    async _fromPlace(text) {
        const answer = await this._api.places(text);
        if (!answer.ok || !answer.data?.length)
            return null;
        const best = answer.data[0];

        return { lat: best.lat, lng: best.lng, label: best.label, source: 'place' };
    }

    async _fromSystem({ fresh }) {
        const now = GLib.get_monotonic_time() / 1e6;
        if (!fresh && this._fix && now - this._fix.at < FIX_TTL)
            return { lat: this._fix.lat, lng: this._fix.lng, label: 'your location', source: 'geoclue' };
        if (this._geoclueFailed)
            return null;

        try {
            const client = await this._geoclueClient();
            if (!client)
                return null;

            const path = client.get_cached_property('Location')?.deepUnpack();
            if (!path || path === '/')
                return null;

            const location = await this._proxy(path, 'org.freedesktop.GeoClue2.Location');
            const lat = location.get_cached_property('Latitude')?.deepUnpack();
            const lng = location.get_cached_property('Longitude')?.deepUnpack();
            if (typeof lat !== 'number' || typeof lng !== 'number')
                return null;

            this._fix = { lat, lng, at: now };

            return { lat, lng, label: 'your location', source: 'geoclue' };
        } catch (e) {
            // Location services off, GeoClue missing, or we're not in its allowed list: use the typed place.
            this._geoclueFailed = true;
            log(`ShulGo: no system location (${e.message}); falling back to the typed place.`);

            return null;
        }
    }

    /** Makes (once) a GeoClue client that is started and watching. */
    async _geoclueClient() {
        if (this._client)
            return this._client;

        const manager = await this._proxy(MANAGER_PATH, 'org.freedesktop.GeoClue2.Manager');
        const [clientPath] = (await manager.call('GetClient', null, Gio.DBusCallFlags.NONE, 5000, null)).deepUnpack();
        this._clientPath = clientPath;

        const client = await this._proxy(clientPath, 'org.freedesktop.GeoClue2.Client');
        client.set_cached_property('DesktopId', new GLib.Variant('s', this._desktopId));
        await client.call('org.freedesktop.DBus.Properties.Set', new GLib.Variant('(ssv)',
            ['org.freedesktop.GeoClue2.Client', 'DesktopId', new GLib.Variant('s', this._desktopId)]),
        Gio.DBusCallFlags.NONE, 5000, null);
        await client.call('org.freedesktop.DBus.Properties.Set', new GLib.Variant('(ssv)',
            ['org.freedesktop.GeoClue2.Client', 'RequestedAccuracyLevel', new GLib.Variant('u', ACCURACY_CITY)]),
        Gio.DBusCallFlags.NONE, 5000, null);
        await client.call('Start', null, Gio.DBusCallFlags.NONE, 10000, null);

        // A fix takes a moment to arrive; the proxy caches it as the Location property.
        await new Promise((resolve) => {
            let done = false;
            const finish = () => {
                if (done)
                    return;
                done = true;
                resolve();
            };
            const id = client.connect('g-properties-changed', finish);
            GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 6, () => {
                client.disconnect(id);
                finish();

                return GLib.SOURCE_REMOVE;
            });
        });

        this._client = client;

        return client;
    }

    _proxy(path, iface) {
        return new Promise((resolve, reject) => {
            Gio.DBusProxy.new(
                Gio.DBus.system, Gio.DBusProxyFlags.NONE, null, BUS, path, iface, null,
                (source, result) => {
                    try {
                        resolve(Gio.DBusProxy.new_finish(result));
                    } catch (e) {
                        reject(e);
                    }
                });
        });
    }

    destroy() {
        if (this._client) {
            try {
                this._client.call('Stop', null, Gio.DBusCallFlags.NONE, 2000, null, null);
            } catch { /* going away anyway */ }
        }
        this._client = null;
    }
}
