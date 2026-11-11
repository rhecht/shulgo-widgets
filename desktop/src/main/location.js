/* Where are we?
 *
 * On the desktop this is the place you tell it, looked up through ShulGo's own /places, and then
 * remembered. There is deliberately no IP lookup: that would mean handing your address to a third party
 * to find out what city you're in, which is a poor trade for a minyan finder.
 *
 * macOS can do better one day — CoreLocation, through a small native helper — but Electron has no way to
 * reach it without a Google geolocation key, and that is another third party. Until then: type a city
 * once, and it stays.
 */

export class Locator {
    /**
     * @param {import('../../shulgo-core/api.js').ShulGoApi} api
     * @param {object} config the adapter from settings.asConfig()
     */
    constructor(api, config) {
        this._api = api;
        this._config = config;
    }

    /** @returns {Promise<{lat: number, lng: number, label: string, source: string}|null>} */
    async resolve() {
        const typed = String(this._config.place || '').trim();
        const remembered = this._config.point;

        // A place that's already been looked up doesn't need looking up again.
        if (typed && remembered && remembered.label === typed)
            return { ...remembered, source: 'place' };

        if (typed) {
            const answer = await this._api.places(typed);
            if (answer.ok && answer.data?.length) {
                const best = answer.data[0];
                const found = { lat: best.lat, lng: best.lng, label: best.label, source: 'place' };
                this._config.rememberPoint(found);

                return found;
            }
        }

        return remembered ? { ...remembered, source: 'remembered' } : null;
    }

    destroy() {}
}
