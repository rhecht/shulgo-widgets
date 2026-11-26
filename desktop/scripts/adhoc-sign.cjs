/* Seal the Mac app with an ad-hoc signature, before the .dmg and .zip are made from it.
 *
 * Why this exists. The build deliberately signs nothing: CSC_IDENTITY_AUTO_DISCOVERY is false, so
 * electron-builder does not go looking for an identity in an empty keychain. What came out of that
 * was not an unsigned app, though — it was a broken one. The Electron binary inside carries its own
 * ad-hoc, linker-signed signature, but the bundle around it was never sealed: no
 * Contents/_CodeSignature at all. Gatekeeper's verdict on ShulGo 1.0.2 was
 *
 *     code has no resources but signature indicates they must be present
 *
 * which is a signature *failure*, not "this app is unsigned". The difference matters to the person
 * downloading it: an unsigned app offers the right-click › Open override, while one that fails
 * verification is refused outright as damaged, with nothing to click. Checked inside the published
 * disk image, so it was the build and not a copy that broke it.
 *
 * `codesign --sign -` costs nothing, needs no certificate and claims no identity. It does not stop
 * macOS warning about an unidentified developer — only a Developer ID does that, and see docs/TODO.md
 * — but it turns a dead end into a warning that can be clicked past.
 *
 * afterPack, not afterSign: afterSign does not run when there is no identity to sign with, and in
 * any case the .dmg and .zip are built from the app directory this hook is handed, so sealing it
 * here is what reaches the people who download them.
 */

const { execFileSync } = require('node:child_process');
const { join } = require('node:path');

exports.default = async function adhocSign(context) {
    if (context.electronPlatformName !== 'darwin') {
        return;
    }

    const app = join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);

    // --deep is deprecated by Apple for distribution signing and is the right tool here anyway:
    // ad-hoc sealing a tree of frameworks and helpers, bottom-up, with no identity to get wrong.
    // --force because the Electron binary inside already carries the linker's own ad-hoc signature.
    execFileSync('codesign', ['--force', '--deep', '--sign', '-', app], { stdio: 'inherit' });

    // Say so, and prove it in the log rather than claiming it: a build that silently signed nothing
    // would look exactly like a build that worked.
    execFileSync('codesign', ['--verify', '--deep', '--strict', '--verbose=1', app], { stdio: 'inherit' });
};
