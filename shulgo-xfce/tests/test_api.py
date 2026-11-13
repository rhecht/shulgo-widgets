"""The client's plumbing, with no network anywhere near it.

api._http is the only thing that touches a socket, so these tests replace it. What's worth pinning:
the URL and cache-key shapes, and the failure behaviour — a 4xx must come through untouched while a
network fault is answered from the last good reply.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shulgo_xfce import api as api_mod  # noqa: E402

GOOD_KEY = 'sg_live_' + 'ab12cd34' * 5          # the right shape, not a real key
ANSWER = {'data': [{'starts_at': '2026-11-12T18:30:00Z'}], 'meta': {'count': 1}}


class Headers(dict):
    def get(self, name, default=None):
        return dict.get(self, name, default)


class FakeHttp:
    """Stands in for api._http, remembering what it was asked for."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        reply = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(reply, Exception):
            raise reply
        status, body = reply

        return status, body if isinstance(body, str) else json.dumps(body), Headers()


class Swap:
    def __init__(self, fake):
        self.fake = fake

    def __enter__(self):
        self.real = api_mod._http
        api_mod._http = self.fake

        return self.fake

    def __exit__(self, *_):
        api_mod._http = self.real


class TheKeyShape(unittest.TestCase):
    def test_only_a_real_looking_key_counts(self):
        self.assertFalse(api_mod.ShulGoApi(api_key='').has_key)
        self.assertFalse(api_mod.ShulGoApi(api_key='sg_live_short').has_key)
        self.assertFalse(api_mod.ShulGoApi(api_key='sg_test_' + 'ab12cd34' * 5).has_key)
        self.assertFalse(api_mod.ShulGoApi(api_key='sg_live_' + 'AB12CD34' * 5).has_key)
        self.assertTrue(api_mod.ShulGoApi(api_key=GOOD_KEY).has_key)

    def test_no_key_is_an_answer_not_a_request(self):
        fake = FakeHttp((200, ANSWER))
        with Swap(fake):
            out = api_mod.ShulGoApi(api_key='').next(43.7, -79.4)
        self.assertFalse(out['ok'])
        self.assertEqual(out['code'], 'no_key')
        self.assertEqual(fake.calls, [], 'a keyless client must not hit the network at all')


class TheUrls(unittest.TestCase):
    def setUp(self):
        self.api = api_mod.ShulGoApi(api_key=GOOD_KEY)

    def test_query_is_built_like_encodeuricomponent(self):
        url = self.api._url('places', {'q': "Rabbi O'Brien & co", 'limit': 8})
        self.assertEqual(
            url, "https://shulgo.com/api/v1/places?q=Rabbi%20O'Brien%20%26%20co&limit=8")

    def test_empty_and_missing_values_are_left_out(self):
        self.assertEqual(self.api._url('next', {'lat': 1, 'lng': None, 'mode': ''}),
                         'https://shulgo.com/api/v1/next?lat=1')

    def test_the_site_url_drops_the_api_path(self):
        self.assertEqual(self.api.site_url, 'https://shulgo.com')

    def test_the_cache_key_rounds_the_point_but_the_request_does_not(self):
        """A fix wanders a few metres between readings. If the key moved with it, nothing written
        down would ever be found again — which looks exactly like a slow network."""
        q = {'lat': 43.7064512, 'lng': -79.4286498, 'window': 120}
        self.assertEqual(
            self.api._cache_key('next', q),
            'https://shulgo.com/api/v1/next?lat=43.706&lng=-79.429&window=120')
        self.assertIn('lat=43.7064512', self.api._url('next', q))

    def test_two_nearby_fixes_share_one_key(self):
        a = self.api._cache_key('next', {'lat': 43.70641, 'lng': -79.42861})
        b = self.api._cache_key('next', {'lat': 43.70644, 'lng': -79.42857})
        self.assertEqual(a, b)


class WhenThingsGoWrong(unittest.TestCase):
    def _api(self, cache=None):
        return api_mod.ShulGoApi(api_key=GOOD_KEY, cache=cache)

    def test_a_good_answer_comes_back_whole(self):
        with Swap(FakeHttp((200, ANSWER))):
            out = self._api().next(43.7, -79.4)
        self.assertTrue(out['ok'])
        self.assertEqual(out['data'], ANSWER['data'])
        self.assertEqual(out['meta'], {'count': 1})

    def test_the_key_travels_in_a_header_not_the_url(self):
        fake = FakeHttp((200, ANSWER))
        with Swap(fake):
            self._api().next(43.7, -79.4)
        url, headers, _timeout = fake.calls[0]
        self.assertNotIn(GOOD_KEY, url)
        self.assertEqual(headers['X-Api-Key'], GOOD_KEY)

    def test_a_401_is_passed_through_and_never_hidden(self):
        """Yesterday's minyanim behind a bad key would hide the one thing worth saying."""
        cache = api_mod.Cache(None)
        with Swap(FakeHttp((200, ANSWER))):
            self._api(cache).next(43.7, -79.4)

        client = self._api(cache)
        with Swap(FakeHttp((401, {'error': {'code': 'bad_key'}}))):
            out = client.next(43.7, -79.4)
        self.assertFalse(out['ok'])
        self.assertEqual(out['code'], 'bad_key')
        self.assertNotIn('data', out)

    def test_a_403_is_passed_through_too(self):
        with Swap(FakeHttp((403, {}))):
            out = self._api().next(43.7, -79.4)
        self.assertFalse(out['ok'])
        self.assertEqual(out['message'], 'This ShulGo API key isn’t allowed to read that.')

    def test_a_500_falls_back_to_the_last_good_answer_marked_old(self):
        cache = api_mod.Cache(None)
        with Swap(FakeHttp((200, ANSWER))):
            self._api(cache).next(43.7, -79.4)

        client = self._api(cache)       # a fresh client, so only the written-down copy can answer
        with Swap(FakeHttp((500, {}))):
            out = client.next(43.7, -79.4)
        self.assertTrue(out['ok'])
        self.assertTrue(out['stale'])
        self.assertEqual(out['data'], ANSWER['data'])
        self.assertTrue(out['cachedAt'] > 0)

    def test_a_dead_network_falls_back_as_well(self):
        import urllib.error
        cache = api_mod.Cache(None)
        with Swap(FakeHttp((200, ANSWER))):
            self._api(cache).next(43.7, -79.4)

        client = self._api(cache)
        with Swap(FakeHttp(urllib.error.URLError('no route to host'))):
            out = client.next(43.7, -79.4)
        self.assertTrue(out['ok'])
        self.assertTrue(out['stale'])
        self.assertEqual(out['why'], 'network')

    def test_with_nothing_saved_a_failure_stays_a_failure(self):
        import urllib.error
        with Swap(FakeHttp(urllib.error.URLError('down'))):
            out = self._api(api_mod.Cache(None)).next(43.7, -79.4)
        self.assertFalse(out['ok'])
        self.assertEqual(out['code'], 'network')

    def test_a_machine_that_knows_it_is_offline_does_not_wait_for_a_timeout(self):
        fake = FakeHttp((200, ANSWER))
        with Swap(fake):
            out = api_mod.ShulGoApi(api_key=GOOD_KEY, cache=api_mod.Cache(None),
                                    is_online=lambda: False).next(43.7, -79.4)
        self.assertFalse(out['ok'])
        self.assertEqual(out['code'], 'offline')
        self.assertEqual(fake.calls, [])

    def test_nonsense_instead_of_json_is_not_a_crash(self):
        with Swap(FakeHttp((200, 'this is not json'))):
            out = self._api().next(43.7, -79.4)
        self.assertFalse(out['ok'])
        self.assertEqual(out['status'], 200)

    def test_a_200_with_no_data_key_is_not_a_good_answer(self):
        with Swap(FakeHttp((200, {'meta': {}}))):
            out = self._api().next(43.7, -79.4)
        self.assertFalse(out['ok'])

    def test_the_same_question_twice_is_only_asked_once(self):
        fake = FakeHttp((200, ANSWER))
        client = self._api()
        with Swap(fake):
            client.next(43.7, -79.4)
            client.next(43.7, -79.4)
        self.assertEqual(len(fake.calls), 1, 'the 60-second TTL should have answered the second')

    def test_events_and_shiurim_ask_the_right_urls(self):
        fake = FakeHttp((200, {'data': {'events': []}}))
        with Swap(fake):
            api = self._api()
            api.events(43.7064, -79.4286)
            api.shiurim(43.7064, -79.4286)
        urls = [c[0] for c in fake.calls]
        self.assertEqual(urls[0], 'https://shulgo.com/api/v1/events?lat=43.7064&lng=-79.4286&page=1')
        # No `q`, deliberately: the server only treats a shiurim request as "near here" when no
        # search word is given, and a tray menu has nowhere to type one.
        self.assertEqual(urls[1], 'https://shulgo.com/api/v1/shiurim?lat=43.7064&lng=-79.4286&page=1')

    def test_a_shiurim_answer_is_cached_for_longer_than_a_minyan_list(self):
        """Ten minutes against one: a weekly shiur does not change while you look at it."""
        self.assertEqual(api_mod.TTL['shiurim'], 600)
        self.assertEqual(api_mod.TTL['events'], 600)
        self.assertEqual(api_mod.TTL['next'], 60)
        self.assertEqual(api_mod.OFFLINE_TTL['shiurim'], 604800)

    def test_a_short_place_query_asks_nobody(self):
        fake = FakeHttp((200, {'data': []}))
        with Swap(fake):
            out = self._api().places('a')
        self.assertTrue(out['ok'])
        self.assertEqual(out['data'], [])
        self.assertEqual(fake.calls, [])


class TheOfflineFile(unittest.TestCase):
    def test_it_survives_a_round_trip(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'sub', 'cache.json')
            first = api_mod.Cache(path)
            first.set('https://example/next?lat=1', {'data': [1, 2, 3]})
            first.save()

            second = api_mod.Cache(path)
            self.assertEqual(second.get('https://example/next?lat=1')['value']['data'], [1, 2, 3])

    def test_rubbish_in_the_file_is_not_an_error(self):
        """A cache that can't be read is not worth a word to anyone; we start without one."""
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'cache.json')
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write('{ not json at all')
            self.assertIsNone(api_mod.Cache(path).get('anything'))

    def test_a_version_it_does_not_know_is_ignored(self):
        import tempfile, os, json as j
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'cache.json')
            with open(path, 'w', encoding='utf-8') as fh:
                j.dump({'version': 99, 'entries': {'x': {'at': 1, 'value': 1}}}, fh)
            self.assertIsNone(api_mod.Cache(path).get('x'))

    def test_no_file_at_all_is_fine(self):
        cache = api_mod.Cache(None)
        cache.set('x', {'data': 1})
        cache.save()
        self.assertEqual(cache.get('x')['value']['data'], 1)

    def test_only_the_newest_sixty_are_kept(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'cache.json')
            cache = api_mod.Cache(path)
            for i in range(api_mod.MAX_ENTRIES + 15):
                cache.set('url-%d' % i, {'data': i})
            cache.save()
            self.assertEqual(len(api_mod.Cache(path)._entries), api_mod.MAX_ENTRIES)

    def test_an_answer_too_old_to_be_worth_showing_is_not_offered(self):
        cache = api_mod.Cache(None)
        cache.set('u', {'data': 1})
        # next/ is good for a day offline; pretend this one is two days old.
        cache._entries['u']['at'] -= 2 * 86400
        self.assertIsNone(cache.get_usable('u', 'next'))
        # mikvaos barely change, so a month is allowed and two days is nothing.
        self.assertIsNotNone(cache.get_usable('u', 'mikvaos'))


if __name__ == '__main__':
    unittest.main()
