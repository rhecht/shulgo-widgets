/* Copies integrations/shulgo-core into this package, so the app has one self-contained tree to run and
 * to package. The copy is ignored by git — ../shulgo-core is the only real one.
 *
 * Runs on its own before start, pack and dist; there is no build step beyond this.
 */

import { copyFileSync, mkdirSync, readdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const from = join(root, '..', 'shulgo-core');
const to = join(root, 'shulgo-core');

rmSync(to, { recursive: true, force: true });
mkdirSync(to, { recursive: true });

// The code only — the README stays where it belongs.
const files = readdirSync(from).filter((name) => name.endsWith('.js'));
for (const name of files)
    copyFileSync(join(from, name), join(to, name));

console.log(`shulgo-core → ${to} (${files.join(', ')})`);
