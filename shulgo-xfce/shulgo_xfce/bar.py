"""The line ShulGo puts on the Xfce top bar.

Jewbuntu's panel runs xfce4-genmon-plugin every fifteen seconds, and all that helper does is `cat`
a file — no Python starts per tick, which is the point on a Pentium III. This module decides what
goes in that file; the tray writes it.

The format is genmon's: <txt> is the line beside the clock and <tool> the tooltip behind it. Both
are Pango markup, so anything from the API has to be escaped. No <txtclick>: popping a
StatusNotifierItem's menu from a command is not something there is a cheap way to do, and anything
else would start a second interpreter per click on a 1 GHz machine.

Everything here is a plain function of plain values, deliberately, so the wording and the length
limit can be tested on a machine with no GTK and no panel — which is the machine this is written on,
and the reason a string of small faults in this widget reached a Pentium III before they reached a
test.
"""

from .fmt import countdown, escape_markup, minutes_until, minyan_subtitle, minyan_time, \
    tefillah_label, zman_time

# The top bar is small on 1024x768, which is what these machines have. Past this the line is cut
# down rather than allowed to push the clock off the edge.
MAX_TXT = 30

# How many minyanim the tooltip lists. Enough to be useful, short enough to read at a glance.
TOOLTIP_ROWS = 4


def _fits(parts, note='', limit=MAX_TXT):
    """Join the fields with the separator, hang the note off the end, and say whether it fits.

    The note is attached with a plain space, not the separator: "4:32 PM Mincha · (old)" reads as
    though (old) were another field of the minyan, which it is not — it is a remark about the list.
    """
    text = ' · '.join(p for p in parts if p)
    if note:
        text = '%s %s' % (text, note) if text else note

    return text if len(text) <= limit else None


def summary(headline, now=None, stale=False, has_key=True, place=None,
            window_minutes=120, pending=False):
    """The line beside the clock. Short, and never a lie about how fresh it is."""
    if pending:
        return 'ShulGo: waiting to link'
    if not has_key:
        return 'ShulGo: not linked'
    if not place:
        return 'ShulGo: choose a place'
    if not headline:
        hours = window_minutes / 60.0
        pretty = ('%d h' % hours) if hours == int(hours) else ('%g h' % hours)

        return 'No minyan in the next %s' % pretty

    name = tefillah_label(headline.get('tefillah'))
    clock = minyan_time(headline)
    soon = countdown(minutes_until(headline.get('starts_at'), now))
    old = '(old)' if stale else ''

    when = '%s %s' % (clock, name) if clock else name

    # Most to least, and the first that fits wins. The time and the name are the part worth keeping,
    # and "(old)" outranks the countdown because a stale list that looks current is worse than one
    # with no countdown on it — so the countdown is what goes when the two cannot both fit.
    for parts, note in ((
        [when, soon], old), (
        [when], old), (
        [when], ''), (
        [clock or name], ''),
    ):
        text = _fits(parts, note)
        if text:
            return text

    return (clock or name)[:MAX_TXT]


def tooltip(rows, zmanim=(), place=None, stale_since=None, window_minutes=120):
    """The fuller picture, behind the line. Several lines; genmon shows them as a tooltip."""
    lines = []
    if place:
        lines.append('ShulGo — %s' % place)

    if rows:
        for row in rows[:TOOLTIP_ROWS]:
            when = minyan_time(row) or countdown(minutes_until(row.get('starts_at')))
            where = minyan_subtitle(row)
            lines.append('%s  %s%s' % (when, tefillah_label(row.get('tefillah')),
                                       '  —  %s' % where if where else ''))
    else:
        lines.append('Nothing in the next %d minutes.' % window_minutes)

    shown = [z for z in zmanim if zman_time(z)][:6]
    if shown:
        lines.append('')
        lines.append('  '.join('%s %s' % (z.get('label') or z.get('name') or '', zman_time(z))
                               for z in shown))

    if stale_since:
        lines.append('')
        lines.append(stale_since)

    return '\n'.join(lines)


def document(**kwargs):
    """The whole file genmon reads: <txt> and <tool>, both escaped.

    Escaping matters here and is easy to forget: a shul called "Beis Medrash & Co" would otherwise
    turn the panel's markup into an error rather than a name.
    """
    tool_args = {k: kwargs.pop(k) for k in
                 ('rows', 'zmanim', 'stale_since') if k in kwargs}
    place = kwargs.get('place')
    window = kwargs.get('window_minutes', 120)

    txt = summary(**kwargs)
    tool = tooltip(place=place, window_minutes=window, **{
        'rows': tool_args.get('rows') or (),
        'zmanim': tool_args.get('zmanim') or (),
        'stale_since': tool_args.get('stale_since'),
    })

    return '<txt>%s</txt>\n<tool>%s</tool>\n' % (escape_markup(txt), escape_markup(tool))
