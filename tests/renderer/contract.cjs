// Execute the TS renderer without Chromium, network, or a project bundle.
const fs = require('fs');
const ts = require('typescript');
const Module = require('module');
const assert = require('node:assert/strict');
const React = require('react');
const {renderToStaticMarkup} = require('react-dom/server');
let frame = 0;
const registry = {};
const load = Module._load;
Module._load = function(name, ...args) {
  if (name === 'project-custom') return {CUSTOM_COMPONENTS: registry};
  if (name === 'remotion') return {
    useCurrentFrame: () => frame,
    useVideoConfig: () => ({fps: 30, durationInFrames: 11}),
    staticFile: path => `/static/${path}`,
    interpolate: (f, [a, b], [x, y]) => x + (y - x) * (f - a) / (b - a),
    Img: props => React.createElement('img', props),
  };
  if (name === '@remotion/media') return {Video: props => {
    assert.equal(props.trimBefore, 30);
    assert.equal(props.trimAfter, 90);
    assert.equal(props.playbackRate, 2);
    return React.createElement('video', {src: props.src});
  }};
  return load.call(this, name, ...args);
};
for (const ext of ['.ts', '.tsx']) require.extensions[ext] = (mod, filename) => {
  mod._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: {jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, esModuleInterop: true},
  }).outputText, filename);
};
// Compile a type-level contract: transpileModule alone does not check types.
const path = require('node:path');
const typeFile = path.resolve(__dirname, 'tracks-contract.ts');
const source = `import type {Tracks} from '../../remotion/spec';
const tracks: Tracks = {captions: [{frame: 0, text: 'hi'}], events: [{frame: 1, kind: 'cut'}], beats: [{frame: 2, strength: 1}]};
tracks.captions?.[0].text.toUpperCase();
tracks.events?.[0].frame.toFixed();
// @ts-expect-error captions require text
const badCaption: Tracks = {captions: [{frame: 0}]};
// @ts-expect-error arbitrary tracks require frame
const badTrack: Tracks = {beats: [{strength: 1}]};
// @ts-expect-error caption text retains its string type
tracks.captions?.[0].text.toFixed();`;
const options = {strict: true, noEmit: true, skipLibCheck: true, target: ts.ScriptTarget.ES2020, moduleResolution: ts.ModuleResolutionKind.NodeJs};
const host = ts.createCompilerHost(options);
const readFile = host.readFile.bind(host);
const fileExists = host.fileExists.bind(host);
host.readFile = name => name === typeFile ? source : readFile(name);
host.fileExists = name => name === typeFile || fileExists(name);
const diagnostics = ts.getPreEmitDiagnostics(ts.createProgram([typeFile], options, host));
assert.equal(ts.formatDiagnosticsWithColorAndContext(diagnostics, {getCurrentDirectory: () => process.cwd(), getCanonicalFileName: x => x, getNewLine: () => '\n'}), '');
const {Shot} = require('../../remotion/Shot.tsx');
const {channelValue, evalLayerTransform} = require('../../remotion/kinematics.ts');
const layer = {id: 'scene', type: 'component', component: 'Scene', rect: [12, 15, 30, 40], z: 0};
const spec = {id: 'test', canvas: {w: 100, h: 100}, fps: 30, durationInFrames: 11, layers: [layer],
  tracks: {captions: [{frame: 0, end_frame: 8, text: 'hello'}], events: [{frame: 5, value: 42}], beats: [{frame: 3, strength: 1}]}};
const prepared = {image: 'data:image/png;base64,AA=='};
const preparedVideos = {clip: 'prepared/test/clip.mp4'};
const render = (extra = {}) => renderToStaticMarkup(React.createElement(Shot, {spec, prepared, preparedVideos, ...extra}));
assert.throws(() => render(), /Unregistered project component: Scene/);
layer.component = 'toString';
assert.throws(() => render(), /Unregistered project component/);
layer.component = 'Scene';
layer.props = {anything: {color: 'project choice'}};
registry.Scene = props => {
  assert.equal(props.layer, layer);
  assert.equal(props.rect, layer.rect);
  assert.equal(props.props, layer.props);
  assert.equal(props.prepared, prepared);
  assert.equal(props.preparedVideos, preparedVideos);
  assert.equal(props.tracks, spec.tracks);
  assert.equal(props.frame, frame);
  assert.equal(props.fps, 30);
  assert.equal(props.durationInFrames, 11);
  return React.createElement('section', {style: {position: 'absolute', left: props.rect[0]}});
};
const markup = render();
assert.equal((markup.match(/left:12px/g) || []).length, 1, 'component rect must not be applied twice');
assert(!/background|font-family|border|shadow/.test(markup));
layer.anim = {x: [[0, 0], [10, 100]], opacity: [[0, 0.5]]};
layer.clipRect = [1, 2, 50, 60];
frame = 5;
assert.match(render(), /translate\(77\.00px/);
assert.match(render(), /left:1px;top:2px;width:50px;height:60px/);
assert.equal(channelValue([[0, 1], [10, 3]], 5, 0), 2);
const child = {id: 'child', type: 'image', asset: 'image', rect: [0, 0, 10, 10], z: 1,
  parent: 'scene', spring: {omega: 18, zeta: 0.25, coupling: 0.45, maxAccel: 4500, channel: 'x', driverChannel: 'x'}};
const map = {scene: layer, child};
assert.notEqual(evalLayerTransform(child, 10, 30, map).x, 0);
assert.deepEqual(evalLayerTransform(child, 10, 30, map), evalLayerTransform(child, 10, 30, map));
spec.layers = [child, layer];
assert.throws(() => render(), /Missing prepared media/);
child.id = 'image';
child.poses = [{frame: 5, asset: 'pose'}];
assert.throws(() => render(), /Missing prepared media/);
assert.match(render({preparedPoses: {image: {pose: 'data:image/png;base64,UE9TRQ=='}}}), /UE9TRQ==/);
frame = 4;
assert.match(render(), /base64,AA==/);
spec.layers = [{id: 'clip', type: 'video', asset: 'source', rect: [0, 0, 100, 100], z: 0,
  trim: [1, 3], playbackRate: 2}];
assert.match(render(), /\/static\/prepared\/test\/clip.mp4/);
assert.throws(() => render({preparedVideos: {}}), /Missing prepared media/);
console.log('Renderer component, media, geometry, pose and timing contracts passed');
