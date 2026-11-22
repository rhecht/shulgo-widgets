"""Does the Python wording still say exactly what the JavaScript says?

shulgo-core/format.js is canonical. shulgo_xfce/fmt.py is a hand port of it, because the machine this
widget is for cannot run the original. The two agreeing is not something to hope for, so:

    cd integrations/shulgo-xfce/tests && TZ=America/Toronto node make-expected.mjs
    cd integrations/shulgo-xfce && TZ=America/Toronto python3 -m unittest discover -s tests -v

cases.json holds the inputs, expected.json holds what format.js answered. This file feeds the same
inputs to fmt.py and insists on the same answers. Changing a line of ShulGo's wording therefore means:
edit format.js, regenerate, run this, and fix whatever it names.

TZ is pinned for the same reason it is pinned in the generator — two functions read the clock zone.

Not compared against the JavaScript, on purpose, and tested separately below:
  - taken_at and offline_notice with a staleSince, because they read the real clock. Frozen here.
  - the clock format itself, because JS asks Intl for the locale's own and Python has no Intl. fmt.py
    says so where it happens.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from shulgo_xfce import fmt  # noqa: E402

# cases.json names format.js's exports; these are the same functions in fmt.py.
BY_NAME = {
    'tefillahLabel': fmt.tefillah_label,
    'forWhomLabel': fmt.for_whom_label,
    'countdown': fmt.countdown,
    'countdownShort': fmt.countdown_short,
    'miles': fmt.miles,
    'travel': fmt.travel,
    'urgency': fmt.urgency,
    'minyanSubtitle': fmt.minyan_subtitle,
    'minyanNote': fmt.minyan_note,
    'minyanDestination': fmt.minyan_destination,
    'mapsUri': fmt.maps_uri,
    'escapeMarkup': fmt.escape_markup,
    'placeFromTimezone': fmt.place_from_timezone,
    'toUnix': fmt.to_unix,
    'minutesUntil': fmt.minutes_until,
    'updatedAgo': fmt.updated_ago,
    'offlineNotice': fmt.offline_notice,
    'zmanimList': fmt.zmanim_list,
    'eventDate': fmt.event_date,
    'audienceLabel': fmt.audience_label,
    'shiurSubtitle': fmt.shiur_subtitle,
}


def resolve(arg, now):
    """{"__daysFromToday": n} becomes a Y-M-D date, exactly as make-expected.mjs resolves it.

    Relative to the frozen `now` out of cases.json, never to the real clock. While it was the real
    clock, answers generated one day stopped matching the next and this whole class skipped itself —
    so the check that holds every ShulGo widget to one wording was absent from every package built
    after the day the fixture was made, and said so only in a line of test output nobody reads.
    """
    if isinstance(arg, dict) and '__daysFromToday' in arg:
        return fmt.today_iso(now + arg['__daysFromToday'] * 86400)

    return arg


class SameWordsAsTheJavaScript(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads((HERE / 'cases.json').read_text(encoding='utf-8'))
        cls.expected = cls._fresh() or cls._committed()

    @classmethod
    def _fresh(cls):
        """Run the real format.js now, if node is here, and compare against that.

        The committed expected.json was the whole fixture at first, and it rotted the moment the
        date changed: eventDate's cases are relative to today, so answers generated yesterday say
        "Tue, Nov 17" while both languages now say "Wed, Nov 18". Making the INPUTS relative was only
        half the fix — the expectations have to be worked out on the same day too.

        So where node is available this generates them afresh, into a temporary file rather than over
        the committed one, and the comparison is always against today's truth.
        """
        generator = HERE / 'make-expected.mjs'
        if not generator.exists() or not shutil.which('node'):
            return None

        out = Path(tempfile.mkdtemp(prefix='shulgo-fmt-')) / 'expected.json'
        try:
            subprocess.run(
                ['node', str(generator), ],
                cwd=str(HERE), check=True, capture_output=True,
                env=dict(os.environ, SHULGO_EXPECTED_OUT=str(out)),
                timeout=60,
            )

            return json.loads(out.read_text(encoding='utf-8'))
        except (subprocess.SubprocessError, OSError, ValueError):
            return None

    @classmethod
    def _committed(cls):
        path = HERE / 'expected.json'
        if not path.exists():
            raise unittest.SkipTest(
                'tests/expected.json is missing and node is not here to generate it. Run:\n'
                '  cd integrations/shulgo-xfce/tests && TZ=America/Toronto node make-expected.mjs'
            )
        saved = json.loads(path.read_text(encoding='utf-8'))

        # No ageing check any more: every clock-dependent case carries the frozen `now` from
        # cases.json, so a committed fixture is as true today as the day it was generated.

        return saved

    def test_every_case_matches(self):
        cases = self.spec['cases']
        results = self.expected['results']
        self.assertEqual(
            len(cases), len(results),
            'cases.json and expected.json disagree on how many cases there are — regenerate'
        )

        if self.expected.get('tz') and self.expected['tz'] != os.environ.get('TZ'):
            self.skipTest(
                'expected.json was generated under TZ=%s; run this with the same TZ'
                % self.expected['tz']
            )

        # eventDate and takenAt ask Intl for the locale's own forms; fmt.py writes the en-US ones.
        # Comparing them under another locale would fail for a reason that is nobody's fault, and
        # fmt.py says so where it happens.
        if self.expected.get('locale') and not str(self.expected['locale']).startswith('en-US'):
            self.skipTest(
                'expected.json was generated under locale %s; the date wording can only be compared '
                'under en-US' % self.expected['locale']
            )

        wrong = []
        for i, ((name, args), want) in enumerate(zip(cases, results)):
            fn = BY_NAME.get(name)
            self.assertIsNotNone(fn, 'test_fmt.py has no Python function mapped for %r' % name)
            got = fn(*[resolve(a, self.spec['now']) for a in args])
            # Round-trip through JSON so a tuple/list or int/float difference isn't called a
            # disagreement about wording, which is what this test is actually about.
            if json.loads(json.dumps(got)) != want:
                wrong.append('  [%d] %s(%s)\n       JS:     %r\n       Python: %r'
                             % (i, name, ', '.join(repr(a) for a in args), want, got))

        if wrong:
            self.fail('%d of %d cases differ from format.js:\n%s'
                      % (len(wrong), len(cases), '\n'.join(wrong)))


class FrozenClock:
    """Pins time.time so the functions that read the real clock can be tested at all."""

    def __init__(self, when):
        self.when = when
        self._real = None

    def __enter__(self):
        self._real = time.time
        time.time = lambda: self.when

        return self

    def __exit__(self, *_):
        time.time = self._real


class TheClockDependentOnes(unittest.TestCase):
    """taken_at and its one caller, against a clock that does not move.

    These cannot be compared to the JavaScript in one run — format.js reads Date.now() with no way to
    pass it in. The wording is asserted here instead, copied from format.js by eye; the shape of the
    sentence is what matters and it is short enough to check against the original.
    """

    # 2026-11-12 13:45:00 in America/Toronto, a Thursday. Checked with time.strftime rather than
    # worked out by hand, which is how this first went in a year wrong.
    NOON = 1794509100

    def test_nothing_to_say_without_a_time(self):
        self.assertEqual(fmt.taken_at(0), '')
        self.assertEqual(fmt.taken_at(None), '')

    def test_earlier_today_is_just_a_clock(self):
        with FrozenClock(self.NOON):
            self.assertEqual(fmt.taken_at(self.NOON - 2 * 3600), 'from 11:45 AM')

    def test_yesterday_says_yesterday(self):
        with FrozenClock(self.NOON):
            self.assertEqual(fmt.taken_at(self.NOON - 24 * 3600), 'from yesterday, 1:45 PM')

    def test_further_back_names_the_day(self):
        with FrozenClock(self.NOON):
            self.assertEqual(fmt.taken_at(self.NOON - 3 * 24 * 3600), 'from Mon 9 Nov, 1:45 PM')

    def test_midnight_reads_as_twelve(self):
        with FrozenClock(self.NOON):
            # 00:30 the same day — the hour is 12, not 0, which is the one thing a %12 gets wrong.
            midnight = self.NOON - 13 * 3600 - 15 * 60
            self.assertEqual(fmt.taken_at(midnight), 'from 12:30 AM')

    def test_offline_with_something_saved_says_how_old_it_is(self):
        with FrozenClock(self.NOON):
            notice = fmt.offline_notice(
                {'why': 'offline', 'staleSince': self.NOON - 2 * 3600}, True)
        self.assertEqual(notice['title'], 'You’re offline')
        self.assertEqual(notice['body'],
                         'This is the list from 11:45 AM. It’ll catch up on its own.')
        self.assertEqual(notice['short'],
                         'You’re offline — showing the list from 11:45 AM')

    def test_server_trouble_is_worded_differently_from_offline(self):
        with FrozenClock(self.NOON):
            notice = fmt.offline_notice({'why': 'network', 'staleSince': self.NOON - 60}, True)
        self.assertEqual(notice['title'], 'ShulGo isn’t answering')


class OneLineRows(unittest.TestCase):
    """For a menu the desktop draws itself, where a second line is thrown away.

    Cutefish's DBusMenu renderer shows the first line of a label and drops the rest, so every row
    read "5:00 PM  Maariv" and nothing else. The reply to that was "Maariv where?", and the shul
    being present is therefore the assertion that matters most here.
    """

    ROW = {
        'display_time': '5:00 PM',
        'tefillah': 'maariv',
        'shul': {'display_name': 'Torath Emeth (Viewmount)'},
        'distance_miles': 0.9,
    }

    def test_the_whole_row_is_on_one_line(self):
        line = fmt.minyan_one_line(self.ROW, 6)

        self.assertNotIn('\n', line)
        self.assertIn('5:00 PM', line)
        self.assertIn('Maariv', line)
        self.assertIn('Torath Emeth (Viewmount)', line)
        self.assertIn('in 6 min', line)

    def test_free_text_cannot_smuggle_in_a_line_break(self):
        """Notes and venue labels come from the API and from people typing.

        One newline in there would hand the renderer the same truncated row back, which would be
        a comic way to lose the fix.
        """
        for note in ('Downstairs\nuse the side door', 'Side door\r\nring the bell',
                     'Tab\there', '\nleading', 'trailing\n'):
            line = fmt.minyan_one_line(dict(self.ROW, notes=note), 6)

            self.assertNotIn('\n', line)
            self.assertNotIn('\r', line)
            self.assertNotIn('\t', line)

    def test_the_shul_is_never_dropped_however_long_the_line_gets(self):
        """Everything else is negotiable. This is the thing the row exists to say."""
        name = 'Congregation Shaarei Shomayim of Toronto (Main Sanctuary, Downstairs)'
        line = fmt.minyan_one_line(
            dict(self.ROW, shul={'display_name': name}, nusach='Ashkenaz',
                 notes='Use the side door'), 6)

        self.assertIn(name, line)

    def test_what_comes_off_first_is_the_least_useful(self):
        """Nusach, then the drive time, then the distance — and the countdown last of all."""
        crowded = dict(self.ROW, nusach='Ashkenaz', shul={'display_name': 'Beis Medrash Zichron Avraham'})
        line = fmt.minyan_one_line(crowded, 6)

        self.assertNotIn('Ashkenaz', line)
        self.assertIn('in 6 min', line)

    def test_a_cancelled_minyan_still_says_so(self):
        """A row that reads like any other when it has been cancelled is worse than a long row."""
        self.assertIn('Cancelled', fmt.minyan_one_line(dict(self.ROW, status='cancelled'), 6))

    def test_a_forming_minyan_says_where_it_is_forming(self):
        for live, expected in (({'notes': 'at the park'}, 'Forming now'), ({}, 'Forming nearby')):
            line = fmt.minyan_one_line({'kind': 'live', 'live': live, 'tefillah': 'mincha'}, 3)

            self.assertIn(expected, line)

    def test_an_empty_row_does_not_raise(self):
        """Rows are drawn from whatever the API sent, including, once, nothing at all."""
        self.assertTrue(fmt.minyan_one_line({}))
        self.assertTrue(fmt.minyan_one_line(None))

    def test_it_calls_a_place_what_the_two_line_version_calls_it(self):
        """Two renderings of one row must not name the same shul differently."""
        for row in (self.ROW,
                    {'kind': 'live', 'live': {}, 'tefillah': 'mincha'},
                    {'kind': 'live', 'live': {'notes': 'x'}, 'tefillah': 'mincha'}):
            where = fmt.minyan_where(row)
            if where:
                self.assertIn(where, fmt.minyan_subtitle(row))
                self.assertIn(where, fmt.minyan_one_line(row, 5))


class TheArithmeticJavaScriptDoes(unittest.TestCase):
    """The two rounding rules, checked directly as well as through miles().

    Worth their own test: Python's own round() and format() disagree with JavaScript on exactly the
    halfway cases, and a cache key that rounds a coordinate differently is a cache that never gets
    read — a bug that looks like a slow network rather than like a bug.
    """

    def test_math_round_sends_the_half_upwards(self):
        self.assertEqual(fmt.js_round(12.5), 13)       # Python's round() says 12
        self.assertEqual(fmt.js_round(13.5), 14)
        self.assertEqual(fmt.js_round(-12.5), -12)     # towards +infinity, not away from zero
        self.assertEqual(fmt.js_round(0.5), 1)
        self.assertEqual(fmt.js_round(-0.5), 0)

    def test_to_fixed_rounds_the_half_of_the_actual_double(self):
        self.assertEqual(fmt.js_to_fixed(0.25, 1), '0.3')     # Python's '%.1f' says 0.2
        self.assertEqual(fmt.js_to_fixed(0.35, 1), '0.3')     # 0.35 is really 0.34999999999999997
        self.assertEqual(fmt.js_to_fixed(1.005, 2), '1.00')   # and 1.005 is really 1.00499999...
        self.assertEqual(fmt.js_to_fixed(43.70645, 3), '43.706')
        self.assertEqual(fmt.js_to_fixed(-79.4286, 3), '-79.429')

    def test_timezone_city(self):
        self.assertEqual(fmt.place_from_timezone('America/Argentina/Buenos_Aires'), 'Buenos Aires')
        self.assertEqual(fmt.place_from_timezone(None), '')


if __name__ == '__main__':
    unittest.main()
