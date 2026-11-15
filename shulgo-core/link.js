/* Linking a computer: what each answer means, apart from any window.
 *
 * The widget asks ShulGo for a pair of codes, shows the short one, and keeps asking whether anybody
 * has approved it. The asking is driven by each platform's own timer; what an answer *means* is
 * here, so the GNOME extension, the GTK app and the Mac build all read them the same way.
 *
 * This is the JavaScript twin of shulgo-xfce/shulgo_xfce/link.py, which carries the same rules for
 * the Python widget. The two are deliberately the same shape.
 *
 * RFC 8628's vocabulary, as /api/v1/device/token sends it:
 *
 *   authorization_pending   nobody has said yes yet — keep asking
 *   slow_down               asking too often — keep asking, but wait longer
 *   access_denied           somebody said no — stop
 *   expired_token           the code ran out — stop
 *   invalid_grant           the code means nothing, or was already used — stop
 */

export const PENDING = 'pending';
export const DONE = 'done';
export const DENIED = 'denied';
export const EXPIRED = 'expired';
export const ERROR = 'error';

/** What a slow_down adds. RFC 8628 §3.5 says to increase it; matching the server's own interval
 *  keeps the two from arguing about it. */
export const SLOW_DOWN_STEP = 5;

/**
 * What to say when this computer has no internet at all.
 *
 * Checked before anything else is attempted, and said plainly. Linking is the one thing in these
 * widgets that cannot fall back on what was saved earlier — there is nothing saved yet, that is the
 * point of it — so "ShulGo couldn't be reached" after a fifteen-second wait is both slow and
 * misleading on a machine that simply isn't connected.
 */
export const OFFLINE = 'This computer isn’t connected to the internet. Connect it and try again — '
    + 'linking needs to reach ShulGo.';

export class Linking {
    /** @param {object} started the data from /device/code */
    constructor(started, now = Date.now() / 1000) {
        const data = started ?? {};
        this.deviceCode = data.device_code ?? '';
        this.userCode = data.user_code ?? '';
        this.verificationUri = data.verification_uri || 'https://shulgo.com/link';
        this.interval = Math.max(1, Number(data.interval) || 5);
        this.startedAt = now;
        this.expiresAt = now + Math.max(1, Number(data.expires_in) || 600);
        this.key = null;
        // Two different jobs, and conflating them was a bug: `message` is why it ENDED, `waiting` is
        // why it has not ended yet. With one field the server's "Nobody has approved this yet" was
        // still on screen after the code expired, because a stale waiting-reason outranked the
        // expiry. Seen twice on a real machine before anybody noticed it here.
        this.message = null;
        this.waiting = null;
    }

    /** A linking with no device code is not one; say so rather than poll nothing for ten minutes. */
    get usable() {
        return Boolean(this.deviceCode && this.userCode);
    }

    secondsLeft(now = Date.now() / 1000) {
        return Math.max(0, Math.floor(this.expiresAt - now));
    }

    expired(now = Date.now() / 1000) {
        return this.secondsLeft(now) <= 0;
    }

    /**
     * Read one answer from /device/token and say what state the linking is now in.
     *
     * A network fault counts as "keep asking", deliberately. Somebody is standing at their phone
     * halfway through approving this, and a dropped packet is not a reason to throw that away. The
     * code's own ten minutes ends it soon enough if the link never comes back.
     */
    absorb(answer) {
        const got = answer ?? {};

        if (got.ok) {
            const key = got.data?.api_key;
            if (key) {
                this.key = key;

                return DONE;
            }
            this.message = 'ShulGo approved the link but sent no key.';

            return ERROR;
        }

        const code = got.code ?? '';

        if (code === 'slow_down') {
            // The server's own figure when it sends a bigger one, otherwise back off by a step.
            this.interval = Math.max(this.interval + SLOW_DOWN_STEP, Number(got.interval) || 0);

            return PENDING;
        }
        if (code === 'authorization_pending' || code === 'network' || code === 'timeout') {
            // The server distinguishes "nobody has approved this yet" from "waiting for a ShulGo
            // administrator" — both are authorization_pending in RFC 8628's vocabulary, and the
            // person watching deserves to know which. A network blip carries no message and leaves
            // whatever was last said standing.
            if (code === 'authorization_pending')
                this.waiting = got.message || null;

            return PENDING;
        }

        if (code === 'access_denied') {
            this.message = 'That request was turned down on the phone.';

            return DENIED;
        }
        if (code === 'expired_token' || code === 'invalid_grant') {
            this.message = 'That code has run out. Start again.';

            return EXPIRED;
        }

        this.message = got.message || 'ShulGo couldn’t be reached.';

        return ERROR;
    }
}

/** What to tell somebody watching. Here, so no window has an opinion of its own. */
export function words(state, linking) {
    if (state === DONE)
        return 'Linked. This computer has its own key now.';
    if (state === DENIED)
        return linking?.message ?? 'Turned down.';
    if (state === EXPIRED)
        return linking?.message ?? 'That code has run out. Start again.';
    if (state === ERROR)
        return linking?.message ?? 'Something went wrong.';

    // Whatever the server last said about why we are STILL waiting — never why it ended.
    if (linking?.waiting)
        return linking.waiting;

    const left = linking?.secondsLeft() ?? 0;
    if (left > 60)
        return `Waiting for you to approve it — about ${Math.round(left / 60)} minutes left.`;
    if (left > 0)
        return 'Waiting for you to approve it — less than a minute left.';

    return 'That code has run out. Start again.';
}
