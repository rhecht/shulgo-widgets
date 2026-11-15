/* The desktop half of the HTTP transport: one GET through Node's own fetch, which Electron's main
 * process has. shulgo-core/api.js takes this as a function, exactly as the GNOME build hands it libsoup.
 *
 * It lives in the main process on purpose: the API key never reaches a renderer.
 */

/**
 * @param {object} [opts]
 * @param {string} [opts.userAgent]
 * @returns {(url: string, opts: {headers?: object, timeout?: number, method?: string, body?: any}) => Promise<{status: number, body: string, headers: {get: (name: string) => string|null}}>}
 */
export function makeTransport({ userAgent = 'ShulGo-Desktop/1.0' } = {}) {
    return async function get(url, { headers = {}, timeout = 15, method = 'GET', body = null } = {}) {
        try {
            const sending = body !== null && body !== undefined;
            const response = await fetch(url, {
                method,
                // Only device linking posts anything, and it posts JSON.
                ...(sending ? { body: typeof body === 'string' ? body : JSON.stringify(body) } : {}),
                headers: {
                    ...headers,
                    ...(sending ? { 'Content-Type': 'application/json' } : {}),
                    'User-Agent': userAgent,
                },
                signal: AbortSignal.timeout(timeout * 1000),
                redirect: 'follow',
            });

            return {
                status: response.status,
                body: await response.text(),
                headers: { get: (name) => response.headers.get(name) },
            };
        } catch (e) {
            const error = new Error(e?.message || 'The request failed.');
            error.code = e?.name === 'TimeoutError' || e?.name === 'AbortError' ? 'timeout' : 'network';
            throw error;
        }
    };
}
