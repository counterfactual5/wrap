// The renderer's frame-file padding, read from the INSTALLED renderer.
// The engine renumbers the rendered frames itself (0-indexed -> 1-indexed),
// so it has to read the same padding the renderer wrote — the file names
// are the contract between the two.
//
// This script asks the installed @remotion/renderer what it does; it does
// not restate the rule.
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');

// The package's "exports" map does not expose its dist/ files, so the
// module is loaded by path — the installed implementation, not a copy.
const modulePath = path.resolve(__dirname, '../../node_modules/@remotion/renderer/dist/get-frame-padded-index.js');
assert.ok(fs.existsSync(modulePath),
  `the installed renderer no longer has ${modulePath} — the engine's frame-padding mirror must be checked against the new rule`);
const {getFilePadLength} = require(modulePath);

const rows = [];
for (let n = 1; n <= 2000; n++) {
  rows.push({
    n,
    actual_frames: getFilePadLength({lastFrame: n - 1, totalFrames: n, countType: 'actual-frames'}),
    from_zero: getFilePadLength({lastFrame: n - 1, totalFrames: n, countType: 'from-zero'}),
  });
}
assert.ok(rows.length > 0);
console.log(JSON.stringify(rows));
