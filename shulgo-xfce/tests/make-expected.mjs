/* Runs the canonical format.js over tests/cases.json and writes down what it said.
 *
 * This is the whole point of the arrangement: shulgo-core/format.js holds ShulGo's wording, the Xfce
 * widget has to carry a Python copy of it, and a copy nobody checks is a copy that drifts. So the
 * JavaScript answers are generated here and committed as expected.json, and test_fmt.py asserts the
 * Python says the same thing. Change the wording in format.js, run this, commit the new expected.json,
 * and the Python test will tell you exactly which lines you now have to bring over.
 *
 *   cd integrations/shulgo-xfce/tests && TZ=America/Toronto node make-expected.mjs
 *
 * TZ is pinned because two of these read the machine's clock zone, and an expectation that depends on
 * where the laptop is would be worse than no expectation at all.
 */
import { writeFileSync, readFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

/* format.js is an ES module with a .js name, and whether node believes that depends on the nearest
 * package.json and on the node version — 22 guesses, 18 does not, and "SyntaxError: Unexpected
 * token 'export'" is what you get for assuming. Copying it to a .mjs and importing that works on
 * any version and changes nothing about the file under test: it has no imports of its own. */
const CORE = new URL('../../shulgo-core/format.js', import.meta.url);
const copy = join(mkdtempSync(join(tmpdir(), 'shulgo-fmt-')), 'format.mjs');
writeFileSync(copy, readFileSync(CORE, 'utf8'));
const fmt = await import(pathToFileURL(copy).href);

const spec = JSON.parse(readFileSync(new URL('cases.json', import.meta.url), 'utf8'));
const results = [];

/**
 * {"__daysFromToday": n} becomes a Y-M-D date, resolved at run time by both runners.
 *
 * Without this, a date written into cases.json would be "Tue, Nov 17" when expected.json was
 * generated and "Nov 17, 2026" six months later, and the Python test would start failing for a
 * reason that has nothing to do with the Python.
 */
const resolve = (arg) => {
    if (arg && typeof arg === 'object' && '__daysFromToday' in arg) {
        const when = new Date();
        when.setDate(when.getDate() + arg.__daysFromToday);

        return fmt.todayIso(when);
    }

    return arg;
};

for (const [name, rawArgs] of spec.cases) {
    const args = rawArgs.map(resolve);
    const fn = fmt[name];
    if (typeof fn !== 'function')
        throw new Error(`format.js has no export named ${name} — cases.json is out of date`);
    // Deliberately not caught: if the canonical implementation throws on one of these inputs, that is
    // a finding about format.js, not something to paper over with a null in a fixture.
    results.push(fn(...args) ?? null);
}

// The test runs this into a temporary file so the comparison is against today's answers; running
// it by hand writes the committed fixture, which is what somebody without node falls back on.
const out = process.env.SHULGO_EXPECTED_OUT ?? 'expected.json';

writeFileSync(out, `${JSON.stringify({
    generatedFrom: 'shulgo-core/format.js',
    tz: process.env.TZ ?? null,
    // Recorded because eventDate and takenAt ask Intl for the locale's own forms. The Python has no
    // Intl and writes the en-US ones, so the comparison is only meaningful under en-US — the test
    // skips itself rather than failing for a reason that is nobody's fault.
    locale: Intl.DateTimeFormat().resolvedOptions().locale,
    node: process.version,
    // The day it was made. eventDate's cases are relative to today, so answers from yesterday are
    // not answers about today, and a fixture that cannot say when it was made rots silently.
    generatedOn: fmt.todayIso(),
    results,
}, null, 2)}\n`);

console.log(`${out}: ${results.length} results from format.js under ${process.version}`);
