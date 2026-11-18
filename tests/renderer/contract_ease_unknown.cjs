/* Runtime check: the renderer rejects an unknown ease, like Python does.
 *
 * The spec validator (core/spec/channels.py) already refuses an ease
 * outside ANIM_EASES, so this path is only reachable when a spec is fed
 * straight to the renderer — a Remotion Studio preview of a hand-edited
 * or stale props file. Before the fix, the Python side raised and the
 * TypeScript side silently rendered a straight line; the silent half is
 * the dangerous one.
 *
 * The TS source is transpiled in-process (no Chromium, no network), the
 * same harness the other renderer contracts use.
 */
const fs = require('fs');
const ts = require('typescript');
const Module = require('module');
const assert = require('node:assert/strict');

for (const ext of ['.ts', '.tsx']) require.extensions[ext] = (mod, filename) => {
  mod._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: {jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, esModuleInterop: true},
  }).outputText, filename);
};

const {applyEase, EASES} = require('../../remotion/kinematics.ts');

// 1. An unknown ease throws instead of rendering as a straight line.
let threw = null;
try {
  applyEase(0.5, 'bogus_ease');
} catch (e) {
  threw = e;
}
assert.ok(threw !== null, 'an unknown ease must throw, not render as linear');
assert.match(String(threw.message), /unknown ease/,
  `the error must name the problem, got: ${threw && threw.message}`);

// 2. The error lists the legal eases, so the author can fix it.
let message = '';
try {
  applyEase(0.5, 'not-an-ease');
} catch (e) {
  message = String(e && e.message);
}
for (const ease of EASES) {
  assert.ok(message.includes(ease), `the error must list ${ease}, got: ${message}`);
}

// 3. Every legal ease still evaluates to the same curve as before.
const expected = {
  linear: 0.5,
  in: 0.25,
  out: 0.75,
  snap: 0.9375,
  step: 0,
};
for (const [ease, value] of Object.entries(expected)) {
  const got = applyEase(0.5, ease);
  assert.ok(Math.abs(got - value) < 1e-9,
    `${ease} should evaluate to ${value}, got ${got}`);
}
assert.ok(Number.isFinite(applyEase(0.5, 'inout')), 'inout must be finite');
assert.ok(Number.isFinite(applyEase(0.5, 'overshoot')), 'overshoot must be finite');

// 4. The vocabulary is exported, so a test can compare it with Python's.
assert.ok(Array.isArray(EASES) && EASES.length === 7,
  `EASES must be exported as the 7-entry vocabulary, got ${JSON.stringify(EASES)}`);

console.log('PASS unknown ease throws');
console.log('PASS the error lists the legal eases');
console.log('PASS every legal ease still evaluates');
console.log('PASS the ease vocabulary is exported');
console.log('ease contract: the renderer rejects unknown eases');
