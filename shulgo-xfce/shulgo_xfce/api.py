"""The ShulGo API v1 client and its offline memory — the Python side.

A port of shulgo-core/api.js and cache.js, for the same reason fmt.py is one: this widget runs where
there is no usable JavaScript engine. The behaviour is deliberately identical, including the parts that
look like details:

  * Every call answers a dict with ok=True/False. Nothing raises at the caller. A widget in a panel
    must not fall over because a network did.
  * Good answers are written down; a request that fails is answered with the last good one, marked
    stale, rather than with nothing.
  * An answer the server itself refused — a bad key, a key not allowed to read mikvaos — is a real
    answer and is never papered over with an old one. 4xx goes straight through.
  * The cache key rounds the coordinate to about a hundred metres, because a location fix wanders
    between readings and an exact-URL key would never be found again.

Synchronous on purpose. api.js juggles promises and de-duplicates requests in flight; here the tray
runs one worker thread that asks for one thing at a time, so there is nothing to de-duplicate and a
plain blocking call is less code, less memory and easier to reason about. urllib, not requests: no
third-party package has to be installed on a machine this old.
"""

import json
import os
import re
import socket
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from .fmt import js_to_fixed

# How long an answer stays good, in seconds. Straight from api.js.
TTL = {
    'next': 60,
    'events': 600,
    'mikvaos': 3600,
    'zmanim': 21600,
    'calendar': 43200,
    'places': 300,
    'shuls': 300,
}

# How old a written-down answer may be and still be worth showing when we can't reach ShulGo.
# Generous, because the alternative is a blank menu; being honest about the age is the UI's job.
OFFLINE_TTL = {
    'next': 86400,
    'events': 604800,
    'mikvaos': 2592000,
    'zmanim': 86400,
    'calendar': 2592000,
    'places': 2592000,
    'shuls': 604800,
}

MAX_ENTRIES = 60

FALLBACK = 'ShulGo couldn’t be reached.'

KEY_SHAPE = re.compile(r'^sg_live_[0-9a-f]{40}$')

# encodeURIComponent leaves these alone; quote() has to be told.
_SAFE = "!'()*-._~"


class Cache:
    """What we keep for when ShulGo can't be reached: a JSON file of the last good answers.

    The file is the same shape as the one the GNOME and Mac builds write ({version: 1, entries}), but
    it is a different file in a different place — this does not read theirs and they do not read this.
    """

    def __init__(self, path=None):
        self._path = path
        self._entries = {}
        self._dirty = False
        self._load()

    def _load(self):
        if not self._path:
            return
        try:
            with open(self._path, encoding='utf-8') as fh:
                saved = json.load(fh)
            if saved.get('version') != 1 or not isinstance(saved.get('entries'), dict):
                return
            for url, entry in saved['entries'].items():
                if isinstance(entry, dict) and isinstance(entry.get('at'), (int, float)) \
                        and 'value' in entry:
                    self._entries[url] = entry
        except (OSError, ValueError):
            # A cache that can't be read is not worth a word to anyone; we start without one.
            pass

    def save(self):
        if not self._path or not self._dirty:
            return
        self._dirty = False
        # Newest first, so the cap throws away what matters least.
        kept = sorted(self._entries.items(), key=lambda kv: kv[1]['at'], reverse=True)[:MAX_ENTRIES]
        self._entries = dict(kept)
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            # Written through a temporary file in the same directory and moved into place, so a
            # machine that loses power mid-write still has yesterday's cache rather than half a file.
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self._path), prefix='.cache-')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                    json.dump({'version': 1, 'entries': self._entries}, fh)
                os.replace(tmp, self._path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except (OSError, ValueError):
            pass

    def get(self, url):
        return self._entries.get(url)

    def get_usable(self, url, path, now=None):
        """The written-down answer for this request, if there is one worth still showing."""
        entry = self.get(url)
        if not entry:
            return None
        now = time.time() if now is None else now

        return entry if now - entry['at'] <= OFFLINE_TTL.get(path, 86400) else None

    def set(self, url, value):
        self._entries[url] = {'at': time.time(), 'value': value}
        self._dirty = True

    def clear(self):
        self._entries = {}
        self._dirty = True
        self.save()


def _http(url, headers, timeout):
    """One GET. Returns (status, body_text). Raises only what the caller turns into a failure dict."""
    request = urllib.request.Request(url, headers=headers, method='GET')
    # No proxy handler and no cookie jar: this talks to one host and wants nothing remembered.
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler())
    try:
        with opener.open(request, timeout=timeout) as answer:
            return answer.status, answer.read().decode('utf-8', 'replace'), answer.headers
    except urllib.error.HTTPError as e:
        # A 4xx or 5xx is an answer, not a failure: the body usually says why.
        return e.code, e.read().decode('utf-8', 'replace'), e.headers


class ShulGoApi:
    def __init__(self, base_url=None, api_key='', timeout=15, cache=None, is_online=None):
        self._base = (base_url or 'https://shulgo.com/api/v1').rstrip('/')
        self._key = api_key or ''
        self._timeout = timeout
        self._fresh = {}        # url -> (at, value): this minute's answers
        self._kept = cache      # the same answers, written down for when we're offline
        self._is_online = is_online

    def reconfigure(self, base_url=None, api_key=None):
        if base_url is not None:
            self._base = (str(base_url).rstrip('/') or self._base)
        if api_key is not None:
            self._key = api_key or ''
        self.forget()

    def forget(self):
        """Forgets this minute's answers. What's written down for offline use is left alone."""
        self._fresh = {}

    @property
    def has_key(self):
        return bool(KEY_SHAPE.match(self._key))

    @property
    def site_url(self):
        """The public site behind this API, for "open in ShulGo" links."""
        return re.sub(r'/api/v1$', '', self._base) or 'https://shulgo.com'

    # ---- the endpoints this widget uses ------------------------------------------------------

    def next(self, lat, lng, tefillah='next', window_min=120, mode='drive'):
        """Minyanim starting soon near a point, soonest first."""
        q = {'lat': lat, 'lng': lng, 'window': window_min, 'mode': mode}
        if tefillah and tefillah != 'next':
            q['tefillah'] = tefillah

        return self._get('next', q)

    def zmanim(self, lat, lng, date=None):
        """Today's zmanim (or another date) for a point."""
        q = {'lat': lat, 'lng': lng}
        if date:
            q['date'] = date

        return self._get('zmanim', q)

    def places(self, text):
        """Cities, neighborhoods and zip codes, for the place box."""
        text = str(text or '').strip()
        if len(text) < 2:
            return {'ok': True, 'data': [], 'meta': {}}

        return self._get('places', {'q': text, 'limit': 8})

    # ---- the plumbing ------------------------------------------------------------------------

    def _url(self, path, query):
        parts = []
        for k, v in (query or {}).items():
            if v is None or v == '':
                continue
            parts.append('%s=%s' % (quote(str(k), safe=_SAFE), quote(str(v), safe=_SAFE)))

        return '%s/%s%s' % (self._base, path, ('?' + '&'.join(parts)) if parts else '')

    def _cache_key(self, path, query):
        """Not the URL: the point is rounded so the key stands still while the request stays exact."""
        coarse = dict(query or {})
        for name in ('lat', 'lng'):
            if coarse.get(name) not in (None, ''):
                coarse[name] = js_to_fixed(coarse[name], 3)

        return self._url(path, coarse)

    def _get(self, path, query, fresh=False):
        url = self._url(path, query)
        key = self._cache_key(path, query)
        now = time.time()
        ttl = TTL.get(path, 60)

        if not fresh:
            hit = self._fresh.get(key)
            if hit and now - hit[0] < ttl:
                answer = dict(hit[1])
                answer['cachedAt'] = hit[0]

                return answer

        if not self.has_key:
            return {
                'ok': False,
                'code': 'no_key',
                'message': 'Add your ShulGo API key in Settings to see minyanim.',
                'status': 0,
            }

        # No point sitting through a fifteen-second timeout to be told what the machine already knows.
        if self._is_online is not None and self._is_online() is False:
            return self._fallback(key, path, {
                'ok': False, 'code': 'offline', 'message': 'This computer is offline.', 'status': 0,
            })

        value = self._fetch(url)
        if value['ok']:
            self._fresh[key] = (time.time(), value)
            if self._kept is not None:
                self._kept.set(key, {'data': value.get('data'), 'meta': value.get('meta', {})})
                self._kept.save()

            return value

        return self._fallback(key, path, value)

    def _fallback(self, key, path, failure):
        """The last good answer instead of nothing — marked stale, with when it was taken.

        An answer the server itself refused is not a network problem and is never replaced with an
        old one: hiding a 401 behind yesterday's minyanim would hide the one thing worth telling.
        """
        if 400 <= failure.get('status', 0) < 500:
            return failure

        kept = self._kept.get_usable(key, path) if self._kept is not None else None
        if not kept:
            return failure

        return {
            'ok': True,
            'data': kept['value'].get('data'),
            'meta': kept['value'].get('meta') or {},
            'status': failure.get('status', 0),
            'stale': True,
            'cachedAt': kept['at'],
            'why': failure.get('code'),
            'whyMessage': failure.get('message'),
        }

    def _fetch(self, url):
        headers = {
            'X-Api-Key': self._key,
            'Accept': 'application/json',
            # Named so ShulGo's own logs can tell this widget apart from the others. No version of
            # the machine, the distribution or anything else about whoever is running it.
            'User-Agent': 'ShulGo-Xfce/1.0',
        }
        try:
            status, body_text, head = _http(url, headers, self._timeout)
        except socket.timeout:
            return {'ok': False, 'code': 'timeout', 'message': FALLBACK, 'status': 0}
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, 'reason', None)
            if isinstance(reason, socket.timeout):
                return {'ok': False, 'code': 'timeout', 'message': FALLBACK, 'status': 0}

            return {'ok': False, 'code': 'network', 'message': str(reason or e) or FALLBACK,
                    'status': 0}

        try:
            body = json.loads(body_text) if body_text else {}
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}

        if 200 <= status < 300 and 'data' in body:
            return {'ok': True, 'data': body['data'], 'meta': body.get('meta') or {},
                    'status': status}

        err = body.get('error') or {}
        try:
            retry_after = int(head.get('Retry-After') or 0) or None
        except (TypeError, ValueError):
            retry_after = None

        return {
            'ok': False,
            'status': status,
            'code': err.get('code') or ('http_%d' % status),
            'message': err.get('message') or self._http_message(status),
            'retryAfter': retry_after,
        }

    @staticmethod
    def _http_message(status):
        if status == 0:
            return FALLBACK
        if status == 401:
            return 'That ShulGo API key isn’t valid. Check it in Settings.'
        if status == 403:
            return 'This ShulGo API key isn’t allowed to read that.'
        if status == 429:
            return 'ShulGo is asking us to slow down. Trying again shortly.'
        if status >= 500:
            return 'ShulGo had a problem answering. Trying again shortly.'

        return 'ShulGo answered %d.' % status
