/**
 * Workaround for an upstream bug that stops TrueForge booting on Windows.
 *
 * kysely's FileMigrationProvider loads migration files with
 *     await import(filePath)
 * where filePath is an OS path. On Windows that is "D:\...\x.js", and Node's ESM
 * loader parses the leading "D:" as a URL scheme, so startup dies with
 *     ERR_UNSUPPORTED_ESM_URL_SCHEME ... Received protocol 'd:'
 * before TrueForge ever reaches its HTTP listener. Confirmed against both
 * trueforge 0.1.4 and 0.2.0-rc.0, on both C: and D:, so it is Windows-wide and
 * not specific to this checkout.
 *
 * The fix is the one Node documents: hand import() a file:// URL. Runs from
 * npm postinstall, is idempotent, and no-ops on macOS/Linux where the bug can't
 * fire -- so a teammate on another OS is unaffected.
 *
 * Upstream: kysely FileMigrationProvider (seen in 0.29.5). Delete this script
 * once kysely ships the fix and TrueForge picks it up.
 */

import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const target = path.join(root, 'node_modules', 'kysely', 'dist', 'migration', 'file-migration-provider.js');

const NEEDLE = 'await import(/* webpackIgnore: true */ filePath)';
const PATCHED = 'await import(/* webpackIgnore: true */ pathToFileURL(filePath).href)';
const IMPORT_LINE = "import { pathToFileURL } from 'node:url';\n";

if (process.platform !== 'win32') {
  console.log('patch-kysely-esm: not Windows, nothing to do');
  process.exit(0);
}

if (!existsSync(target)) {
  console.log('patch-kysely-esm: kysely not installed, skipping');
  process.exit(0);
}

let src = readFileSync(target, 'utf8');

if (src.includes(PATCHED)) {
  console.log('patch-kysely-esm: already applied');
  process.exit(0);
}

if (!src.includes(NEEDLE)) {
  console.error('patch-kysely-esm: expected import() call not found -- kysely may have changed.');
  console.error('  Check whether the upstream fix has landed before deleting this script.');
  process.exit(0); // don't fail the install over it
}

src = src.replace(NEEDLE, PATCHED);
if (!src.includes('pathToFileURL')) {
  throw new Error('patch-kysely-esm: replacement did not take');
}
if (!src.includes(IMPORT_LINE)) {
  src = src.replace(/^(\/\/\/[^\n]*\n)/, `$1${IMPORT_LINE}`);
}

writeFileSync(target, src);
console.log('patch-kysely-esm: applied to', path.relative(root, target));
