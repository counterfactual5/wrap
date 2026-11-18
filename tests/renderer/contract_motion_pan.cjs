// The renderer must not apply motion.pan: the contract removed it and
// refuses it with "migration required: motion.pan removed; use anim.x".
// A spec the contract rejects must not MOVE on screen.
//
// motion.zoom is alive and must keep interpolating; anim.x (the sanctioned
// replacement for pan) must keep moving the layer.
//
// Run without Chromium, network, or a project bundle: the same harness the
// other renderer contracts use.
const fs = require('fs');
const ts = require('typescript');
const Module = require('module');
const assert = require('node:assert/strict');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');

let frame = 0;
const load = Module._load;
Module._load = function(name, ...args) {
  if (name === 'project-custom') return {CUSTOM_COMPONENTS: {}};
  if (name === 'remotion') return {
    useCurrentFrame: () => frame,
    useVideoConfig: () => ({fps: 30, durationInFrames: 11}),
    staticFile: path => `/static/${path}`,
    interpolate: (f, [a, b], [x, y]) => x + (y - x) * (f - a) / (b - a),
    Img: props => React.createElement('img', props),
  };
  if (name === '@remotion/media') return {
    Video: props => React.createElement('video', {src: props.src}),
  };
  return load.call(this, name, ...args);
};
for (const ext of ['.ts', '.tsx']) require.extensions[ext] = (mod, filename) => {
  mod._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: {jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, esModuleInterop: true},
  }).outputText, filename);
};

const {Shot} = require('../../remotion/Shot.tsx');

const layer = {id: 'bg', type: 'ai', asset: 'bg', rect: [0, 0, 100, 100], z: 0};
const spec = {id: 'pan-probe', canvas: {w: 100, h: 100}, fps: 30,
  durationInFrames: 11, layers: [layer]};
const prepared = {bg: 'data:image/png;base64,AA=='};
const render = () => renderToStaticMarkup(React.createElement(Shot, {spec, prepared}));

// 1. motion.pan must not move the picture — at any frame.
layer.motion = {type: 'geometric', pan: [0, 100]};
frame = 0;
const atStart = render();
frame = 10;
const atEnd = render();
assert(!/translateX/.test(atStart), 'motion.pan must not be applied at frame 0');
assert(!/translateX/.test(atEnd), 'motion.pan must not be applied at the last frame');
assert.equal(atStart, atEnd, 'motion.pan must not change the rendered frame at all');

// 2. motion.zoom is alive: it still interpolates over the shot.
layer.motion = {type: 'geometric', zoom: [1, 2]};
frame = 0;
assert.match(render(), /scale\(1\)/, 'motion.zoom must still apply at frame 0');
frame = 10;
assert.match(render(), /scale\(2\)/, 'motion.zoom must still apply at the last frame');

// 3. The sanctioned channel (anim.x) still moves the layer.
layer.motion = undefined;
layer.anim = {x: [[0, 0], [10, 100]]};
frame = 10;
assert.match(render(), /translate\(150\.00px/, 'anim.x must still move the layer');

console.log('motion.pan is not applied; motion.zoom and anim.x still are');
