/* The two things shulgo-core needs from GNOME to cope with being offline: somewhere to write the last
 * good answers, and someone to say whether there is a network at all.
 */

import GLib from 'gi://GLib';
import Gio from 'gi://Gio';

/** ~/.cache/jewbuntu-shulgo/answers.json — losing it costs nothing, which is what a cache directory is for. */
export function cachePath() {
    return GLib.build_filenamev([GLib.get_user_cache_dir(), 'jewbuntu-shulgo', 'answers.json']);
}

/** The storage adapter shulgo-core/cache.js asks for. */
export function makeStorage() {
    const path = cachePath();

    return {
        read() {
            try {
                const [ok, bytes] = Gio.File.new_for_path(path).load_contents(null);

                return ok ? new TextDecoder().decode(bytes) : null;
            } catch {
                return null; // nothing written yet, which is not worth a word
            }
        },
        write(text) {
            const file = Gio.File.new_for_path(path);
            try {
                const dir = file.get_parent();
                if (!dir.query_exists(null))
                    dir.make_directory_with_parents(null);
                GLib.chmod(dir.get_path(), 0o700);
                file.replace_contents(new TextEncoder().encode(text), null, false,
                    Gio.FileCreateFlags.REPLACE_DESTINATION | Gio.FileCreateFlags.PRIVATE, null);
                // It holds where you were and what you looked for, so it is yours to read and nobody
                // else's — the same footing as the key file.
                GLib.chmod(path, 0o600);
            } catch (e) {
                logError(e, 'ShulGo: could not write the offline cache');
            }
        },
    };
}

/**
 * What GNOME knows about the network. NetworkMonitor says more than "is there a cable": it knows about
 * captive portals and about having a link but no route, which is exactly the case that otherwise costs
 * a fifteen-second timeout.
 */
export function makeNetwork() {
    const monitor = Gio.NetworkMonitor.get_default();

    return {
        isOnline: () => {
            try {
                return monitor.get_network_available();
            } catch {
                return true; // if we can't tell, assume yes and let the request decide
            }
        },
        onChange: (callback) => {
            const id = monitor.connect('network-changed', (_m, available) => callback(available));

            return () => monitor.disconnect(id);
        },
    };
}
