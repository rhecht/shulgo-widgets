# -*- coding: utf-8 -*-
u"""HTTPS for a 2007 machine, by handing the job to a modern curl.

Ubuntu 7.10 ships OpenSSL 0.9.8, which speaks TLS 1.0 and nothing newer, and Python 2.5's urllib2
and ssl are built against it. shulgo.com will not accept TLS 1.0, so every call this widget could
make through the standard library is refused before a byte of HTTP is exchanged. Nothing in Python
can fix that; the problem is underneath Python.

So the Jewbuntu ISO ships a statically linked modern curl at /opt/jewbuntu/bin/curl, with OpenSSL 3
and a current CA bundle compiled in, and every request goes through it as a subprocess. It is not
elegant. It is the difference between a widget that works on a Pentium II and one that cannot talk
to the internet at all.

ON NOT PUTTING THE KEY ON THE COMMAND LINE
------------------------------------------
The obvious way to send the key is `curl -H "Authorization: Bearer sg_live_..."`, and it is wrong.
A process's arguments are world-readable on this system: any other account on the machine can run
`ps auxww` during the poll and read the key straight off the screen. A 2007 family desktop is
exactly the kind of machine that has four accounts on it.

So headers go in a config file instead, written 0600 in the user's own directory and deleted the
moment the call returns, and `curl -K` reads them from there. The same goes for POST bodies, which
carry the device code during linking: `--data @file`, never `-d` with the value inline. Nothing
secret is ever an argument.

Everything here is checked against the real curl in the Gutsy image rather than assumed.
"""

from __future__ import with_statement

import os
import stat
import subprocess
import tempfile

# Where the ISO puts the static build. Falling back to whatever `curl` is on PATH is a courtesy for
# anyone running this on a newer machine, not something the ISO relies on.
BUNDLED = u'/opt/jewbuntu/bin/curl'

# A request that has not finished by now is not going to. Without these a half-open socket hangs
# the widget's worker thread for as long as the kernel allows, which on a 128 MB machine is felt.
CONNECT_TIMEOUT = 10


class CurlMissing(Exception):
    u"""No curl anywhere. The caller turns this into the same 'offline' wording as a dead network."""


def binary():
    u"""The curl to use: the ISO's static one, else whatever is on PATH."""
    if os.path.exists(BUNDLED) and os.access(BUNDLED, os.X_OK):
        return BUNDLED

    for directory in (os.environ.get(u'PATH') or u'').split(os.pathsep):
        candidate = os.path.join(directory, u'curl')
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate

    return None


def _private_file(body, suffix=u''):
    u"""A file only this user can read, with no moment in which it is readable by anyone else.

    mkstemp creates at 0600, so unlike write-then-chmod there is no window at all - which matters
    here because what goes in these files is an API key.
    """
    fd, path = tempfile.mkstemp(prefix=u'.shulgo-', suffix=suffix)
    try:
        handle = os.fdopen(fd, u'wb')
        try:
            handle.write(body.encode(u'utf-8'))
        finally:
            handle.close()
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except BaseException:
        try:
            os.unlink(path)
        except EnvironmentError:
            pass
        raise

    return path


def _config(url, headers, timeout, body_file=None):
    u"""curl's own config syntax. Quoting is curl's problem, not the shell's, because there is no
    shell: the process is spawned directly."""
    lines = [u'silent', u'show-error',
             u'max-time = %d' % timeout,
             u'connect-timeout = %d' % CONNECT_TIMEOUT,
             # A 4xx or 5xx is an answer we want to read, not a failure, so no --fail.
             u'url = "%s"' % url.replace(u'"', u'%22')]
    for name in sorted(headers.keys()):
        lines.append(u'header = "%s: %s"' % (name, headers[name].replace(u'"', u'')))
    if body_file is not None:
        lines.append(u'request = POST')
        lines.append(u'data = "@%s"' % body_file)

    return u'\n'.join(lines) + u'\n'


def request(url, headers, timeout, body=None):
    u"""One request. Returns (status, body_text, headers_dict).

    Raises CurlMissing when there is no curl; every other failure comes back as status 0, which the
    caller already treats as 'could not be reached'.
    """
    exe = binary()
    if exe is None:
        raise CurlMissing(u'no curl at %s and none on PATH' % BUNDLED)

    temporary = []
    try:
        body_file = None
        if body is not None:
            body_file = _private_file(body, u'.json')
            temporary.append(body_file)
            headers = dict(headers)
            headers[u'Content-Type'] = u'application/json'

        config_file = _private_file(_config(url, headers, timeout, body_file), u'.conf')
        temporary.append(config_file)
        header_file = _private_file(u'', u'.head')
        temporary.append(header_file)

        # The status code is asked for separately and printed last, because curl exits 0 on a 500:
        # the process's own exit status says whether curl worked, not whether the request did.
        process = subprocess.Popen(
            [exe, u'-K', config_file, u'-D', header_file, u'-w', u'\\n%{http_code}'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = process.communicate()

        if process.returncode != 0:
            return 0, (err or '').decode(u'utf-8', u'replace'), {}

        text = (out or '').decode(u'utf-8', u'replace')
        cut = text.rfind(u'\n')
        status_text = text[cut + 1:].strip() if cut >= 0 else u''
        payload = text[:cut] if cut >= 0 else u''
        try:
            status = int(status_text)
        except ValueError:
            status = 0

        return status, payload, _parse_headers(header_file)
    finally:
        for path in temporary:
            try:
                os.unlink(path)
            except EnvironmentError:
                pass


def _parse_headers(path):
    u"""Only Retry-After is ever read, but the whole lot is parsed so that stays true by accident
    rather than by luck. Names are lowercased; the caller looks up through get()."""
    found = _Headers()
    try:
        handle = open(path, u'rb')
        try:
            raw = handle.read().decode(u'utf-8', u'replace')
        finally:
            handle.close()
    except EnvironmentError:
        return found

    for line in raw.split(u'\n'):
        if u':' not in line:
            continue
        name, value = line.split(u':', 1)
        found[name.strip().lower()] = value.strip()

    return found


class _Headers(dict):
    u"""A dict whose get() does not care about case, so head.get('Retry-After') works."""

    def get(self, name, default=None):
        return dict.get(self, name.lower(), default)
