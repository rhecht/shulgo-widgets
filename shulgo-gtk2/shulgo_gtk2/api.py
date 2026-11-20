# -*- coding: utf-8 -*-
u"""The ShulGo API v1 client and its offline memory — the Python side.

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

from __future__ import division, with_statement

import codecs
import os
import re
import socket
import tempfile
import time
from urllib import quote

# json itself does not exist until Python 2.6. simplejson rather than a vendored copy, so the
# dependency is visible to anyone looking at what the package needs.
import simplejson as json

from . import config, curl
from .curl import CurlMissing

from .fmt import _text, js_to_fixed

# How long an answer stays good, in seconds. Straight from api.js.
TTL = {
    u'next': 60,
    u'events': 600,
    u'mikvaos': 3600,
    u'zmanim': 21600,
    u'calendar': 43200,
    u'places': 300,
    u'shuls': 300,
    u'shiurim': 600,
}

# How old a written-down answer may be and still be worth showing when we can't reach ShulGo.
# Generous, because the alternative is a blank menu; being honest about the age is the UI's job.
OFFLINE_TTL = {
    u'next': 86400,
    u'events': 604800,
    u'mikvaos': 2592000,
    u'zmanim': 86400,
    u'calendar': 2592000,
    u'places': 2592000,
    u'shuls': 604800,
    u'shiurim': 604800,   # a week; a weekly shiur is still on next week
}

MAX_ENTRIES = 60

FALLBACK = u'ShulGo couldn’t be reached.'

KEY_SHAPE = re.compile(ur'^sg_live_[0-9a-f]{40}$')

# encodeURIComponent leaves these alone; quote() has to be told.
# Bytes, not unicode: urllib.quote on 2.5 tests `c in safe` and a unicode safe makes that a
# TypeError rather than anything you could read.
_SAFE = u"!'()*-._~".encode('ascii')


class Cache(object):
    u"""What we keep for when ShulGo can't be reached: a JSON file of the last good answers.

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
            with codecs.open(self._path, u'r', u'utf-8') as fh:
                saved = json.loads(fh.read())
            if saved.get(u'version') != 1 or not isinstance(saved.get(u'entries'), dict):
                return
            for url, entry in saved[u'entries'].items():
                if isinstance(entry, dict) and isinstance(entry.get(u'at'), (int, float)) \
                        and u'value' in entry:
                    self._entries[url] = entry
        except (EnvironmentError, ValueError):
            # A cache that can't be read is not worth a word to anyone; we start without one.
            pass

    def save(self):
        if not self._path or not self._dirty:
            return
        self._dirty = False
        # Newest first, so the cap throws away what matters least.
        kept = sorted(self._entries.items(), key=lambda kv: kv[1][u'at'], reverse=True)[:MAX_ENTRIES]
        self._entries = dict(kept)
        try:
            config._make_dir(os.path.dirname(self._path))
            # Written through a temporary file in the same directory and moved into place, so a
            # machine that loses power mid-write still has yesterday's cache rather than half a file.
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self._path), prefix=u'.cache-')
            try:
                with os.fdopen(fd, u'wb') as fh:
                    fh.write(json.dumps({u'version': 1, u'entries': self._entries}).encode(u'utf-8'))
                # os.replace is 3.3; os.rename is atomic on POSIX, which is all this runs on.
                os.rename(tmp, self._path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except EnvironmentError:
                    pass
                raise
        except (EnvironmentError, ValueError):
            pass

    def get(self, url):
        return self._entries.get(url)

    def get_usable(self, url, path, now=None):
        u"""The written-down answer for this request, if there is one worth still showing."""
        entry = self.get(url)
        if not entry:
            return None
        now = time.time() if now is None else now

        return entry if now - entry[u'at'] <= OFFLINE_TTL.get(path, 86400) else None

    def set(self, url, value):
        self._entries[url] = {u'at': time.time(), u'value': value}
        self._dirty = True

    def clear(self):
        self._entries = {}
        self._dirty = True
        self.save()


def _http(url, headers, timeout, body=None):
    u"""One request, through curl. Returns (status, body_text, headers).

    Python's own HTTPS cannot be used here at all: 7.10's OpenSSL 0.9.8 offers TLS 1.0 and shulgo.com
    will not accept it, so urllib2 fails before any HTTP happens. curl.py explains the rest, including
    why the key never appears in the process's arguments.
    """
    return curl.request(url, headers, timeout,
                        body=json.dumps(body) if body is not None else None)


class ShulGoApi(object):
    def __init__(self, base_url=None, api_key=u'', timeout=15, cache=None, is_online=None):
        self._base = (base_url or u'https://shulgo.com/api/v1').rstrip(u'/')
        self._key = api_key or u''
        self._timeout = timeout
        self._fresh = {}        # url -> (at, value): this minute's answers
        self._kept = cache      # the same answers, written down for when we're offline
        self._is_online = is_online

    def reconfigure(self, base_url=None, api_key=None):
        if base_url is not None:
            self._base = (_text(base_url).rstrip(u'/') or self._base)
        if api_key is not None:
            self._key = api_key or u''
        self.forget()

    def forget(self):
        u"""Forgets this minute's answers. What's written down for offline use is left alone."""
        self._fresh = {}

    @property
    def has_key(self):
        return bool(KEY_SHAPE.match(self._key))

    @property
    def site_url(self):
        u"""The public site behind this API, for "open in ShulGo" links."""
        return re.sub(ur'/api/v1$', u'', self._base) or u'https://shulgo.com'

    # ---- the endpoints this widget uses ------------------------------------------------------

    def next(self, lat, lng, tefillah=u'next', window_min=120, mode=u'drive'):
        u"""Minyanim starting soon near a point, soonest first."""
        q = {u'lat': lat, u'lng': lng, u'window': window_min, u'mode': mode}
        if tefillah and tefillah != u'next':
            q[u'tefillah'] = tefillah

        return self._get(u'next', q)

    def zmanim(self, lat, lng, date=None):
        u"""Today's zmanim (or another date) for a point."""
        q = {u'lat': lat, u'lng': lng}
        if date:
            q[u'date'] = date

        return self._get(u'zmanim', q)

    def events(self, lat, lng, page=1):
        u"""Upcoming events within fifty miles of a point, soonest first."""
        return self._get(u'events', {u'lat': lat, u'lng': lng, u'page': page})

    def shiurim(self, lat, lng, page=1):
        u"""Shiurim near a point.

        No search word is passed, which is what makes the server treat it as "near here" — a typed
        search is meant to reach the whole directory rather than your neighbourhood, and a tray menu
        has nowhere to type.
        """
        return self._get(u'shiurim', {u'lat': lat, u'lng': lng, u'page': page})

    # ---- linking this computer, which is how a key is got in the first place -----------------

    def device_start(self, client_name, device_name=None):
        u"""Begin "link this computer". Answers a short code to show and a device code to poll with.

        Deliberately not through _get: these two calls carry no API key — they are how a machine
        gets one — and must never be cached or answered from the offline copy.
        """
        return self._post(u'device/code', {
            u'client_name': client_name,
            u'device_name': device_name or u'',
        })

    def device_poll(self, device_code):
        u"""Ask whether it has been approved yet.

        The server answers RFC 8628's vocabulary: authorization_pending and slow_down come back with
        a 200 and an error code, which _fetch already turns into {ok: False, code: ...} — those are
        the normal course of events, not failures.
        """
        return self._post(u'device/token', {u'device_code': device_code})

    def _post(self, path, payload):
        u"""An unauthenticated POST. No key, no cache, no offline fallback."""
        try:
            status, body_text, head = _http(u'%s/%s' % (self._base, path), {
                u'Accept': u'application/json',
                u'User-Agent': u'ShulGo-Xfce/1.0',
            }, self._timeout, payload)
        except socket.timeout:
            return {u'ok': False, u'code': u'timeout', u'message': FALLBACK, u'status': 0}
        except (CurlMissing, EnvironmentError), e:
            reason = getattr(e, u'reason', None)
            if isinstance(reason, socket.timeout):
                return {u'ok': False, u'code': u'timeout', u'message': FALLBACK, u'status': 0}

            return {u'ok': False, u'code': u'network', u'message': _text(reason or e) or FALLBACK,
                    u'status': 0}

        return self._read(status, body_text, head)

    def places(self, text):
        u"""Cities, neighborhoods and zip codes, for the place box."""
        text = _text(text).strip()
        if len(text) < 2:
            return {u'ok': True, u'data': [], u'meta': {}}

        return self._get(u'places', {u'q': text, u'limit': 8})

    # ---- the plumbing ------------------------------------------------------------------------

    def _url(self, path, query):
        parts = []
        for k, v in (query or {}).items():
            # Normalised before it is compared, not after. `v == u''` against a byte string with a
            # high character in it does not raise on Python 2 — it warns and quietly answers False,
            # which is the sort of comparison that works until the day a place name has an accent.
            if v is None:
                continue
            text = _text(v)
            if text == u'':
                continue
            parts.append(u'%s=%s' % (quote(_text(k).encode('utf-8'), safe=_SAFE),
                                     quote(text.encode('utf-8'), safe=_SAFE)))

        return u'%s/%s%s' % (self._base, path, (u'?' + u'&'.join(parts)) if parts else u'')

    def _cache_key(self, path, query):
        u"""Not the URL: the point is rounded so the key stands still while the request stays exact."""
        coarse = dict(query or {})
        for name in (u'lat', u'lng'):
            if coarse.get(name) not in (None, u''):
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
                answer[u'cachedAt'] = hit[0]

                return answer

        if not self.has_key:
            return {
                u'ok': False,
                u'code': u'no_key',
                u'message': u'Add your ShulGo API key in Settings to see minyanim.',
                u'status': 0,
            }

        # No point sitting through a fifteen-second timeout to be told what the machine already knows.
        if self._is_online is not None and self._is_online() is False:
            return self._fallback(key, path, {
                u'ok': False, u'code': u'offline', u'message': u'This computer is offline.', u'status': 0,
            })

        value = self._fetch(url)
        if value[u'ok']:
            self._fresh[key] = (time.time(), value)
            if self._kept is not None:
                self._kept.set(key, {u'data': value.get(u'data'), u'meta': value.get(u'meta', {})})
                self._kept.save()

            return value

        return self._fallback(key, path, value)

    def _fallback(self, key, path, failure):
        u"""The last good answer instead of nothing — marked stale, with when it was taken.

        An answer the server itself refused is not a network problem and is never replaced with an
        old one: hiding a 401 behind yesterday's minyanim would hide the one thing worth telling.
        """
        if 400 <= failure.get(u'status', 0) < 500:
            return failure

        kept = self._kept.get_usable(key, path) if self._kept is not None else None
        if not kept:
            return failure

        return {
            u'ok': True,
            u'data': kept[u'value'].get(u'data'),
            u'meta': kept[u'value'].get(u'meta') or {},
            u'status': failure.get(u'status', 0),
            u'stale': True,
            u'cachedAt': kept[u'at'],
            u'why': failure.get(u'code'),
            u'whyMessage': failure.get(u'message'),
        }

    def _fetch(self, url):
        headers = {
            u'X-Api-Key': self._key,
            u'Accept': u'application/json',
            # Named so ShulGo's own logs can tell this widget apart from the others. No version of
            # the machine, the distribution or anything else about whoever is running it.
            u'User-Agent': u'ShulGo-Xfce/1.0',
        }
        try:
            status, body_text, head = _http(url, headers, self._timeout)
        except socket.timeout:
            return {u'ok': False, u'code': u'timeout', u'message': FALLBACK, u'status': 0}
        except (CurlMissing, EnvironmentError), e:
            reason = getattr(e, u'reason', None)
            if isinstance(reason, socket.timeout):
                return {u'ok': False, u'code': u'timeout', u'message': FALLBACK, u'status': 0}

            return {u'ok': False, u'code': u'network', u'message': _text(reason or e) or FALLBACK,
                    u'status': 0}

        return self._read(status, body_text, head)

    def _read(self, status, body_text, head):
        u"""Turn an answer into the {ok: ...} shape, the same way for a GET and a POST."""
        try:
            body = json.loads(body_text) if body_text else {}
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}

        if 200 <= status < 300 and u'data' in body:
            return {u'ok': True, u'data': body[u'data'], u'meta': body.get(u'meta') or {},
                    u'status': status}

        err = body.get(u'error') or {}
        try:
            retry_after = int(head.get(u'Retry-After') or 0) or None
        except (TypeError, ValueError):
            retry_after = None

        answer = {
            u'ok': False,
            u'status': status,
            u'code': err.get(u'code') or (u'http_%d' % status),
            u'message': err.get(u'message') or self._http_message(status),
            u'retryAfter': retry_after,
        }
        # RFC 8628 sends the polling interval back with slow_down; the linking code needs it.
        if isinstance(err.get(u'interval'), int):
            answer[u'interval'] = err[u'interval']

        return answer

    @staticmethod
    def _http_message(status):
        if status == 0:
            return FALLBACK
        if status == 401:
            return u'That ShulGo API key isn’t valid. Check it in Settings.'
        if status == 403:
            return u'This ShulGo API key isn’t allowed to read that.'
        if status == 429:
            return u'ShulGo is asking us to slow down. Trying again shortly.'
        if status >= 500:
            return u'ShulGo had a problem answering. Trying again shortly.'

        return u'ShulGo answered %d.' % status
