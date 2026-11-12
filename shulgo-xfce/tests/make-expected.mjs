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

for (const [name, args] of spec.cases) {
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
    node: process.version,
    results: out,
}, null, 2)}\n`);

console.log(`expected.json: ${out.length} results from format.js under ${process.version}`);
