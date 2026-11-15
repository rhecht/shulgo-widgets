"""Linking this computer: what to do with each answer, apart from any window.

The widget asks ShulGo for a pair of codes, shows the short one, and keeps asking whether anybody
has approved it. The asking is driven by the GTK side on a timer; what each answer *means* is here,
in plain functions over plain dicts, so it can be tested on a machine with no GTK — which is the
machine this is written on, and the reason an earlier invisible-icon bug reached a Pentium III
before it reached a test.

RFC 8628 vocabulary, as ShulGo's /api/v1/device/token sends it:

    authorization_pending   nobody has said yes yet — keep asking
    slow_down               asking too often — keep asking, but wait longer
    access_denied           somebody said no — stop
    expired_token           the code ran out — stop
    invalid_grant           the code means nothing, or was already used — stop
"""

import time

PENDING = 'pending'
DONE = 'done'
DENIED = 'denied'
EXPIRED = 'expired'
ERROR = 'error'

# What a slow_down adds to the wait. RFC 8628 §3.5 says to increase it; five seconds is the server's
# own interval and matching it keeps the two from arguing.
SLOW_DOWN_STEP = 5

# What to say when this computer has no internet at all. Checked before anything else is attempted:
# linking is the one thing in this widget that cannot fall back on what was saved earlier — there is
# nothing saved yet, that is the point of it — so a fifteen-second wait ending in "ShulGo couldn't
# be reached" is both slow and misleading on a machine that simply isn't connected.
OFFLINE = ('This computer isn’t connected to the internet. Connect it and try again — '
           'linking needs to reach ShulGo.')


class Linking:
    """One linking in progress: the codes, the clock, and what the last answer meant."""

    def __init__(self, started, now=None):
        data = started or {}
        self.device_code = data.get('device_code') or ''
        self.user_code = data.get('user_code') or ''
        self.verification_uri = data.get('verification_uri') or 'https://shulgo.com/link'
        self.interval = max(1, int(data.get('interval') or 5))
        self.started_at = time.time() if now is None else now
        self.expires_at = self.started_at + max(1, int(data.get('expires_in') or 600))
        self.key = None
        # Two different jobs, and conflating them was a bug: `message` is why it ENDED, `waiting` is
        # why it has not ended yet. With one field the server's "Nobody has approved this yet" was
        # still on screen after the code expired, because a stale waiting-reason outranked the
        # expiry. Seen twice on a real machine before anybody noticed it here.
        self.message = None
        self.waiting = None

    @classmethod
    def resume(cls, saved):
        """Rebuild a linking from what config.save_pending wrote down.

        Only the device code and the deadline are worth keeping: the short code is for showing, and
        everything else — the interval, what the server last said — is re-learned on the next poll.
        """
        saved = saved or {}
        it = cls({
            'device_code': saved.get('device_code'),
            'user_code': saved.get('user_code'),
            'interval': saved.get('interval'),
            'expires_in': 1,
        })
        it.expires_at = float(saved.get('expires_at') or 0)

        return it

    @property
    def usable(self):
        """A linking with no device code is not one; say so rather than poll nothing forever."""
        return bool(self.device_code and self.user_code)

    def take_deadline(self, expires_in, now=None):
        """Move our deadline to the server's, when it sends one. Returns True if it changed.

        Only ever outwards in practice, but written to follow the server either way: it is the one
        that knows, and a widget's own clock on an old laptop is not evidence.
        """
        try:
            seconds = int(expires_in)
        except (TypeError, ValueError):
            return False
        if seconds <= 0:
            return False

        was = self.expires_at
        self.expires_at = (time.time() if now is None else now) + seconds

        # A second either way is the round trip, not a new deadline; only say so when it is real.
        return abs(self.expires_at - was) > 5

    def seconds_left(self, now=None):
        return max(0, int(self.expires_at - (time.time() if now is None else now)))

    def expired(self, now=None):
        return self.seconds_left(now) <= 0

    def absorb(self, answer):
        """Read one answer from /device/token and say what state the linking is now in.

        A network fault counts as "keep asking", deliberately. Somebody is standing at their phone
        halfway through approving this; a dropped packet or a sleeping WiFi card is not a reason to
        throw that away. The code's own expiry ends it soon enough if the link never comes back.
        """
        answer = answer or {}

        if answer.get('ok'):
            data = answer.get('data') or {}
            key = data.get('api_key')
            if key:
                self.key = key

                return DONE

            self.message = 'ShulGo approved the link but sent no key.'

            return ERROR

        code = answer.get('code') or ''

        if code == 'slow_down':
            # Take the server's own figure when it sends one, and otherwise back off by a step.
            self.interval = max(self.interval + SLOW_DOWN_STEP, int(answer.get('interval') or 0))

            return PENDING

        if code in ('authorization_pending', 'network', 'timeout'):
            # The server distinguishes "nobody has approved this yet" from "waiting for a ShulGo
            # administrator" — both are authorization_pending in RFC 8628's vocabulary, and the
            # person watching deserves to know which. A network blip carries no message and leaves
            # whatever was last said standing.
            if code == 'authorization_pending':
                self.waiting = answer.get('message') or None
                # The deadline MOVES. Approving your own device pushes it from twenty minutes to
                # three days, and a client holding the first figure decides the code is dead while
                # the server still has it alive — which is exactly how a real pair of approvals was
                # thrown away. So the server's figure wins whenever it sends one.
                self.take_deadline(answer.get('expires_in'))

            return PENDING

        if code == 'access_denied':
            self.message = 'That request was turned down on the phone.'

            return DENIED

        if code in ('expired_token', 'invalid_grant'):
            self.message = 'That code has run out. Start again.'

            return EXPIRED

        self.message = answer.get('message') or 'ShulGo could not be reached.'

        return ERROR


def words(state, linking):
    """What to tell somebody watching the window. Kept here so the window has no opinions."""
    if state == DONE:
        return 'Linked. This computer has its own key now.'
    if state == DENIED:
        return linking.message or 'Turned down.'
    if state == EXPIRED:
        return linking.message or 'That code has run out. Start again.'
    if state == ERROR:
        return linking.message or 'Something went wrong.'

    # Whatever the server last said about why we are STILL waiting — never why it ended.
    if linking.waiting:
        return linking.waiting

    left = linking.seconds_left()
    if left > 60:
        return 'Waiting for you to approve it — about %d minutes left.' % round(left / 60.0)
    if left > 0:
        return 'Waiting for you to approve it — less than a minute left.'

    return 'That code has run out. Start again.'
