"""Which minyanim to show, and which one the panel names.

These two rules are the product, not plumbing, and they are easy to get subtly wrong — so they live
here, in a module that imports nothing but the clock, rather than inside the GTK code where this
machine's Python can't reach them to test. Both are ports of shulgo-core/store.js: `_dropPast` and
the `headline` getter. See tests/test_pick.py.
"""

from .fmt import now_unix, to_unix


def still_ahead(rows, now=None):
    """Minyanim that have already started drop off as the minutes pass — store.js's _dropPast.

    Two deliberate choices, both copied rather than invented:

    The minute of grace. A minyan that began forty seconds ago is one you can still walk into, and
    keeping it is what makes a list cached an hour ago honest rather than merely old.

    A row whose time can't be read is kept. A missing or malformed starts_at is not evidence that the
    minyan is over, and dropping it would make a server-side oddity look like a quiet evening.

    The order is left exactly as it came: the API answers soonest first, and re-sorting here would
    silently override whatever else it knows about the ordering.
    """
    now = now_unix() if now is None else now
    keep = []
    for row in rows or []:
        at = to_unix((row or {}).get('starts_at'))
        if at is None or at > now - 60:
            keep.append(row)

    return keep


def headline(rows):
    """The one the panel names — store.js's `headline`, and deliberately not simply the soonest.

    The soonest minyan is often one you can no longer reach: a mincha four minutes off with an
    eight-minute drive. So the panel names the soonest one you could still make; failing that, the
    soonest one ShulGo couldn't route (can_make_it null — unknown is not the same as no); and only
    then the soonest of all, so the panel is never blank while a minyan is listed.

    `is True` and `is None` rather than truthiness, because false and null are different answers here
    and treating them alike is exactly the bug this shape exists to avoid.
    """
    rows = rows or []
    for row in rows:
        if row.get('can_make_it') is True:
            return row
    for row in rows:
        if row.get('can_make_it') is None:
            return row

    return rows[0] if rows else None


def rows(answer, key=None):
    """The list of things inside an API answer, whatever shape that answer happens to be.

    The v1 endpoints are not consistent and there is no point pretending otherwise: /next answers a
    bare array, while /events and /shiurim answer an object with the list under a name beside the
    total and the page. Checked against the controllers rather than guessed at.

    Anything unexpected — an error answer, a null, an object where a list belongs — comes back as an
    empty list. A tray menu with nothing in it is a fair description of "we have nothing"; a crash
    while drawing a menu is not.
    """
    if not isinstance(answer, dict) or not answer.get('ok'):
        return []

    data = answer.get('data')
    if key is None:
        return data if isinstance(data, list) else []

    if not isinstance(data, dict):
        return []
    found = data.get(key)

    return found if isinstance(found, list) else []
