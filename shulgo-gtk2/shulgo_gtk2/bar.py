# -*- coding: utf-8 -*-
u"""The line ShulGo puts on the Xfce top bar.

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


def _fits(parts, note=u'', limit=MAX_TXT):
    u"""Join the fields with the separator, hang the note off the end, and say whether it fits.

    The note is attached with a plain space, not the separator: "4:32 PM Mincha · (old)" reads as
    though (old) were another field of the minyan, which it is not — it is a remark about the list.
    """
    text = u' · '.join(p for p in parts if p)
    if note:
        text = u'%s %s' % (text, note) if text else note

    return text if len(text) <= limit else None


def summary(headline, now=None, stale=False, has_key=True, place=None,
            window_minutes=120, pending=False):
    u"""The line beside the clock. Short, and never a lie about how fresh it is."""
    if pending:
        return u'ShulGo: waiting to link'
    if not has_key:
        return u'ShulGo: not linked'
    if not place:
        return u'ShulGo: choose a place'
    if not headline:
        hours = window_minutes / 60.0
        pretty = (u'%d h' % hours) if hours == int(hours) else (u'%g h' % hours)

        return u'No minyan in the next %s' % pretty

    name = tefillah_label(headline.get(u'tefillah'))
    clock = minyan_time(headline)
    soon = countdown(minutes_until(headline.get(u'starts_at'), now))
    old = u'(old)' if stale else u''

    when = u'%s %s' % (clock, name) if clock else name

    # Most to least, and the first that fits wins. The time and the name are the part worth keeping,
    # and "(old)" outranks the countdown because a stale list that looks current is worse than one
    # with no countdown on it — so the countdown is what goes when the two cannot both fit.
    for parts, note in ((
        [when, soon], old), (
        [when], old), (
        [when], u''), (
        [clock or name], u''),
    ):
        text = _fits(parts, note)
        if text:
            return text

    return (clock or name)[:MAX_TXT]


def tooltip(rows, zmanim=(), place=None, stale_since=None, window_minutes=120,
            has_key=True, pending=False):
    u"""The fuller picture, behind the line. Several lines; genmon shows them as a tooltip.

    It is told has_key and pending for one reason: so it cannot contradict the line it sits
    behind. Without them a machine that had never been linked showed "ShulGo: not linked" on
    the panel and "Nothing in the next 120 minutes" in the tooltip — which says the opposite,
    that ShulGo looked and found nothing. Somebody would believe the second one and conclude
    there are no minyanim near them.
    """
    if pending:
        return u'ShulGo is waiting for this computer to be approved.'
    if not has_key:
        return (u'ShulGo is not linked to an account yet.\n'
                u'Open the menu and choose “Link this computer”.')
    if not place:
        return (u'ShulGo does not know where you are yet.\n'
                u'Open Settings and choose a place.')

    lines = [u'ShulGo — %s' % place]

    if rows:
        for row in rows[:TOOLTIP_ROWS]:
            when = minyan_time(row) or countdown(minutes_until(row.get(u'starts_at')))
            where = minyan_subtitle(row)
            lines.append(u'%s  %s%s' % (when, tefillah_label(row.get(u'tefillah')),
                                       u'  —  %s' % where if where else u''))
    else:
        lines.append(u'Nothing in the next %d minutes.' % window_minutes)

    shown = [z for z in zmanim if zman_time(z)][:6]
    if shown:
        lines.append(u'')
        lines.append(u'  '.join(u'%s %s' % (z.get(u'label') or z.get(u'name') or u'', zman_time(z))
                               for z in shown))

    if stale_since:
        lines.append(u'')
        lines.append(stale_since)

    return u'\n'.join(lines)


def document(**kwargs):
    u"""The whole file genmon reads: <txt> and <tool>, both escaped.

    Escaping matters here and is easy to forget: a shul called "Beis Medrash & Co" would otherwise
    turn the panel's markup into an error rather than a name.
    """
    # The tooltip's arguments are pulled out and passed by name, never by unpacking a dict.
    #
    # Python 2.5 requires keyword argument NAMES to be byte strings: f(**{u'x': 1}) raises
    # "TypeError: keywords must be strings", and it was not relaxed until 2.6.5. Every literal in
    # this package carries a u prefix because 2.5 has no unicode_literals — so the moment a dict
    # with those keys met a **, the widget died in __init__, before the tray icon existed. It did
    # not look like a crash to anybody: the autostart entry ran, nothing appeared, and that was all.
    #
    # Passing them by name sidesteps the rule entirely rather than depending on remembering it.
    rows = kwargs.pop(u'rows', None) or ()
    zmanim = kwargs.pop(u'zmanim', None) or ()
    stale_since = kwargs.pop(u'stale_since', None)
    place = kwargs.get(u'place')
    window = kwargs.get(u'window_minutes', 120)

    txt = summary(**kwargs)
    tool = tooltip(rows, zmanim=zmanim, place=place, stale_since=stale_since,
                   window_minutes=window, has_key=kwargs.get(u'has_key', True),
                   pending=kwargs.get(u'pending', False))

    return u'<txt>%s</txt>\n<tool>%s</tool>\n' % (escape_markup(txt), escape_markup(tool))
