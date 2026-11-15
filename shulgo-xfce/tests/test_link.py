"""Linking this computer: what each answer means.

The server half of this has its own tests in PHP. These are about the widget's side of the
conversation — and particularly about the answers that are NOT failures, which is where a polling
client usually goes wrong: authorization_pending and slow_down are the normal course of events.
"""

import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shulgo_xfce import link  # noqa: E402

STARTED = {
    'device_code': 'a' * 64,
    'user_code': 'K7PQ-4RDT',
    'verification_uri': 'https://shulgo.com/link',
    'expires_in': 600,
    'interval': 5,
}


class ReadingTheCodes(unittest.TestCase):
    def test_it_takes_what_the_server_sent(self):
        it = link.Linking(STARTED)
        self.assertEqual(it.user_code, 'K7PQ-4RDT')
        self.assertEqual(it.verification_uri, 'https://shulgo.com/link')
        self.assertEqual(it.interval, 5)
        self.assertTrue(it.usable)

    def test_a_nonsense_answer_is_not_a_linking(self):
        """Better to say so than to poll an empty string every five seconds for ten minutes."""
        self.assertFalse(link.Linking({}).usable)
        self.assertFalse(link.Linking(None).usable)
        self.assertFalse(link.Linking({'user_code': 'K7PQ-4RDT'}).usable)

    def test_the_clock_runs_down(self):
        now = time.time()
        it = link.Linking(STARTED, now=now)
        self.assertEqual(it.seconds_left(now), 600)
        self.assertEqual(it.seconds_left(now + 599), 1)
        self.assertFalse(it.expired(now + 599))
        self.assertTrue(it.expired(now + 600))
        self.assertEqual(it.seconds_left(now + 9999), 0, 'never negative')

    def test_sensible_defaults_when_the_server_leaves_things_out(self):
        it = link.Linking({'device_code': 'x', 'user_code': 'y'})
        self.assertEqual(it.interval, 5)
        self.assertGreater(it.seconds_left(), 0)
        self.assertIn('/link', it.verification_uri)


class WhatEachAnswerMeans(unittest.TestCase):
    def setUp(self):
        self.it = link.Linking(STARTED)

    def test_pending_is_the_normal_course_of_events(self):
        self.assertEqual(self.it.absorb({'ok': False, 'code': 'authorization_pending'}), link.PENDING)
        self.assertIsNone(self.it.key)

    def test_a_key_finishes_it(self):
        answer = {'ok': True, 'data': {'api_key': 'sg_live_' + 'ab12cd34' * 5}}
        self.assertEqual(self.it.absorb(answer), link.DONE)
        self.assertTrue(self.it.key.startswith('sg_live_'))

    def test_approved_but_no_key_is_an_error_not_a_success(self):
        self.assertEqual(self.it.absorb({'ok': True, 'data': {}}), link.ERROR)
        self.assertIsNone(self.it.key)

    def test_slow_down_keeps_going_but_waits_longer(self):
        before = self.it.interval
        self.assertEqual(self.it.absorb({'ok': False, 'code': 'slow_down'}), link.PENDING)
        self.assertGreater(self.it.interval, before)

    def test_slow_down_takes_the_servers_own_figure_when_it_is_bigger(self):
        self.it.absorb({'ok': False, 'code': 'slow_down', 'interval': 30})
        self.assertEqual(self.it.interval, 30)

    def test_slow_down_never_shortens_the_wait(self):
        self.it.interval = 20
        self.it.absorb({'ok': False, 'code': 'slow_down', 'interval': 5})
        self.assertGreaterEqual(self.it.interval, 20)

    def test_no_means_stop(self):
        self.assertEqual(self.it.absorb({'ok': False, 'code': 'access_denied'}), link.DENIED)

    def test_a_used_or_dead_code_means_stop(self):
        self.assertEqual(self.it.absorb({'ok': False, 'code': 'expired_token'}), link.EXPIRED)
        self.assertEqual(link.Linking(STARTED).absorb({'ok': False, 'code': 'invalid_grant'}),
                         link.EXPIRED)

    def test_it_says_which_approval_it_is_waiting_on(self):
        """Both are authorization_pending; only the server knows which half is outstanding."""
        self.it.absorb({'ok': False, 'code': 'authorization_pending',
                        'message': 'Waiting for a ShulGo administrator to approve this computer.'})
        self.assertIn('administrator', link.words(link.PENDING, self.it))

    def test_a_blip_does_not_wipe_what_the_server_last_said(self):
        self.it.absorb({'ok': False, 'code': 'authorization_pending',
                        'message': 'Waiting for a ShulGo administrator.'})
        self.it.absorb({'ok': False, 'code': 'network'})
        self.assertIn('administrator', link.words(link.PENDING, self.it))

    def test_a_waiting_reason_does_not_survive_the_code_running_out(self):
        """The bug, from a real machine: after the code expired the window still said "Nobody has
        approved this yet", because the reason we were WAITING outranked the reason it ENDED."""
        self.it.absorb({'ok': False, 'code': 'authorization_pending',
                        'message': 'Nobody has approved this yet.'})
        self.assertIn('Nobody has approved', link.words(link.PENDING, self.it))

        said = link.words(link.EXPIRED, self.it)
        self.assertNotIn('Nobody has approved', said)
        self.assertIn('run out', said)

    def test_nor_any_other_ending(self):
        self.it.absorb({'ok': False, 'code': 'authorization_pending',
                        'message': 'Waiting for a ShulGo administrator.'})
        for state in (link.DENIED, link.EXPIRED, link.ERROR):
            self.assertNotIn('administrator', link.words(state, self.it),
                             'a waiting reason must not explain an ending')

    def test_without_a_reason_it_counts_down_as_before(self):
        self.it.absorb({'ok': False, 'code': 'authorization_pending'})
        self.assertIn('minutes left', link.words(link.PENDING, self.it))

    def test_a_dropped_network_keeps_trying_rather_than_abandoning_it(self):
        """Somebody is at their phone halfway through approving this. A sleeping WiFi card is not a
        reason to throw that away — the code's own expiry ends it soon enough."""
        self.assertEqual(self.it.absorb({'ok': False, 'code': 'network'}), link.PENDING)
        self.assertEqual(self.it.absorb({'ok': False, 'code': 'timeout'}), link.PENDING)

    def test_anything_unrecognised_is_an_error_with_the_servers_own_words(self):
        state = self.it.absorb({'ok': False, 'code': 'teapot', 'message': 'ShulGo is a teapot.'})
        self.assertEqual(state, link.ERROR)
        self.assertEqual(self.it.message, 'ShulGo is a teapot.')

    def test_nothing_at_all_is_an_error_not_a_crash(self):
        self.assertEqual(self.it.absorb(None), link.ERROR)
        self.assertEqual(link.Linking(STARTED).absorb({}), link.ERROR)


class TheOfflineWarning(unittest.TestCase):
    """Said before anything else is attempted, and said the same on every platform.

    link.py and shulgo-core/link.js are twins: the same rules in two languages. A sentence a person
    reads is exactly the kind of thing that drifts between twins, so this reads the JavaScript and
    insists the two are word for word.
    """

    def test_it_says_something_useful(self):
        self.assertIn('internet', link.OFFLINE.lower())
        self.assertIn('ShulGo', link.OFFLINE)

    def test_it_matches_the_javascript_word_for_word(self):
        core = Path(__file__).resolve().parent.parent.parent / 'shulgo-core' / 'link.js'
        if not core.exists():
            self.skipTest('shulgo-core/link.js is not beside this checkout')

        text = core.read_text(encoding='utf-8')
        start = text.index('export const OFFLINE')
        end = text.index(';', start)
        # The JS writes it as adjacent quoted pieces joined by +; glue them back together.
        pieces = re.findall(r"'((?:[^'\\]|\\.)*)'", text[start:end])
        self.assertTrue(pieces, 'could not read OFFLINE out of link.js')
        joined = ''.join(pieces).replace("\\'", "'")

        self.assertEqual(joined, link.OFFLINE,
                         'the offline warning has drifted between link.py and link.js')


class WhatThePersonIsTold(unittest.TestCase):
    def test_each_ending_says_something(self):
        it = link.Linking(STARTED)
        for state in (link.DONE, link.DENIED, link.EXPIRED, link.ERROR, link.PENDING):
            self.assertTrue(link.words(state, it).strip())

    def test_waiting_counts_down_in_words(self):
        now = time.time()
        it = link.Linking(STARTED, now=now)
        self.assertIn('minutes left', link.words(link.PENDING, it))

        it.expires_at = time.time() + 30
        self.assertIn('less than a minute', link.words(link.PENDING, it))

        it.expires_at = time.time() - 1
        self.assertIn('run out', link.words(link.PENDING, it))

    def test_an_error_prefers_the_servers_own_words(self):
        it = link.Linking(STARTED)
        it.absorb({'ok': False, 'code': 'teapot', 'message': 'ShulGo is a teapot.'})
        self.assertEqual(link.words(link.ERROR, it), 'ShulGo is a teapot.')


if __name__ == '__main__':
    unittest.main()
