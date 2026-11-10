import {Config} from '@remotion/cli/config';
import fs from 'fs';
import path from 'path';

// Deterministic rendering: PNG frames, fixed pixel format, no color management surprises.
Config.setVideoImageFormat('png');
Config.setPixelFormat('yuv420p');
Config.setCodec('h264');
Config.setOverwriteOutput(true);

// Projects register their own custom components in <project>/remotion-custom.tsx.
// The engine ships none: when POSTER_ROOT points at a project that provides the
// file, the 'project-custom' module aliases to it; otherwise it falls back to
// the empty registry in remotion/custom/empty.tsx.
const engineRoot = __dirname;
const projectCustom = process.env.POSTER_ROOT
  ? path.join(process.env.POSTER_ROOT, 'remotion-custom.tsx')
  : null;
const aliasTarget =
  projectCustom && fs.existsSync(projectCustom)
    ? projectCustom
    : path.join(engineRoot, 'remotion', 'custom', 'empty.tsx');

Config.overrideWebpackConfig((currentConfiguration) => ({
  ...currentConfiguration,
  resolve: {
    ...currentConfiguration.resolve,
    alias: {
      ...currentConfiguration.resolve?.alias,
      'project-custom': aliasTarget,
    },
  },
}));
