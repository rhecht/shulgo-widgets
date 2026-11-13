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
import { writeFileSync, readFileSync } from 'node:fs';
import * as fmt from '../../shulgo-core/format.js';

const spec = JSON.parse(readFileSync('cases.json', 'utf8'));
const out = [];

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
    out.push(fn(...args) ?? null);
}

writeFileSync('expected.json', `${JSON.stringify({
    generatedFrom: 'shulgo-core/format.js',
    tz: process.env.TZ ?? null,
    // Recorded because eventDate and takenAt ask Intl for the locale's own forms. The Python has no
    // Intl and writes the en-US ones, so the comparison is only meaningful under en-US — the test
    // skips itself rather than failing for a reason that is nobody's fault.
    locale: Intl.DateTimeFormat().resolvedOptions().locale,
    node: process.version,
    results: out,
}, null, 2)}\n`);

console.log(`expected.json: ${out.length} results from format.js under ${process.version}`);
