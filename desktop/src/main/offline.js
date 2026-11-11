/* The two things shulgo-core needs from Electron to cope with being offline: somewhere to write the
 * last good answers, and someone to say whether there is a network at all.
 */

import { app, net } from 'electron';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

/** The storage adapter shulgo-core/cache.js asks for. */
export function makeStorage() {
    const path = join(app.getPath('userData'), 'answers.json');

    return {
        read() {
            try {
                return readFileSync(path, 'utf8');
            } catch {
                return null; // nothing written yet
            }
        },
        write(text) {
            try {
                mkdirSync(app.getPath('userData'), { recursive: true });
                writeFileSync(path, text, 'utf8');
            } catch (e) {
                console.error('ShulGo: could not write the offline cache', e);
            }
        },
    };
}

/**
 * What the machine knows about the network.
 *
 * Electron's main process can answer `net.isOnline()` but has nothing to subscribe to, so the panel —
 * an ordinary web page, which does get `online` and `offline` events — reports in through `report()`.
 * Chromium's own reading is the more informed of the two, so it wins while we have it.
 */
export function makeNetwork() {
    const listeners = new Set();
    let fromRenderer = null;

    return {
        isOnline: () => (fromRenderer === null ? net.isOnline() : fromRenderer),

        onChange: (callback) => {
            listeners.add(callback);

            return () => listeners.delete(callback);
        },

        /** Called over IPC when the panel sees the network come or go. */
        report: (online) => {
            if (fromRenderer === online)
                return;
            fromRenderer = online;
            for (const listener of [...listeners])
                listener(online);
        },
    };
}
