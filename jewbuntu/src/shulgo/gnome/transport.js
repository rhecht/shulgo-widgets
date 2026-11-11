/* The GNOME half of the HTTP transport: one GET over libsoup 3, which both GNOME Shell and GTK already
 * have loaded. core/api.js takes this as a function, so a Mac, Windows or phone build swaps in fetch()
 * without touching the client.
 */

import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import Soup from 'gi://Soup?version=3.0';

Gio._promisify(Soup.Session.prototype, 'send_and_read_async', 'send_and_read_finish');

/**
 * @param {object} [opts]
 * @param {string} [opts.userAgent]
 * @returns {(url: string, opts: {headers?: object, timeout?: number}) => Promise<{status: number, body: string, headers: {get: (name: string) => string|null}}>}
 */
export function makeTransport({ userAgent = 'JewBuntu-ShulGo/1.0' } = {}) {
    const session = new Soup.Session({ timeout: 15, user_agent: userAgent });

    return async function get(url, { headers = {}, timeout = 15 } = {}) {
        const message = Soup.Message.new('GET', url);
        if (!message) {
            const error = new Error(`Not a usable API address: ${url}`);
            error.code = 'bad_url';
            throw error;
        }

        for (const [name, value] of Object.entries(headers))
            message.request_headers.append(name, String(value));

        // Soup's own timeout can sit on a half-open socket, so cancel by hand as well.
        const cancellable = new Gio.Cancellable();
        let timedOut = false;
        const guard = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, timeout + 5, () => {
            timedOut = true;
            cancellable.cancel();

            return GLib.SOURCE_REMOVE;
        });

        let bytes;
        try {
            bytes = await session.send_and_read_async(message, GLib.PRIORITY_DEFAULT, cancellable);
        } catch (e) {
            const error = new Error(e?.message || 'The request failed.');
            error.code = timedOut ? 'timeout' : 'network';
            throw error;
        } finally {
            if (!timedOut)
                GLib.Source.remove(guard);
        }

        const responseHeaders = message.get_response_headers();

        return {
            status: message.get_status(),
            body: new TextDecoder().decode(bytes?.get_data() ?? new Uint8Array()),
            headers: { get: (name) => responseHeaders?.get_one(name) ?? null },
        };
    };
}
