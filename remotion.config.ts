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
// the empty registry in remotion/registry/empty.tsx.
//
// The engine root must NOT come from __dirname: webpack rewrites __dirname
// while bundling this config, so it resolved to the CLI's own dist directory
// and the alias pointed at a file that does not exist there (every render then
// failed to bundle and S3 silently fell back to the Quartz compositor).
// Resolution is device-independent:
//   1. WRAP_ENGINE_ROOT — the pipeline sets this explicitly.
//   2. process.cwd()     — valid when the CLI is launched from the engine root
//      (which the pipeline does) or an engine checkout is used manually.
function engineRootFromCandidates(candidates: (string | undefined)[]): string | null {
  for (const dir of candidates) {
    if (dir && fs.existsSync(path.join(dir, 'remotion', 'registry', 'empty.tsx'))) {
      return dir;
    }
  }
  return null;
}

const engineRoot =
  engineRootFromCandidates([process.env.WRAP_ENGINE_ROOT, process.cwd()]) ??
  process.cwd();

const projectCustom = process.env.POSTER_ROOT
  ? path.join(process.env.POSTER_ROOT, 'remotion-custom.tsx')
  : null;
const emptyRegistry = path.join(engineRoot, 'remotion', 'registry', 'empty.tsx');
const aliasTarget =
  projectCustom && fs.existsSync(projectCustom) ? projectCustom : emptyRegistry;

if (!fs.existsSync(aliasTarget)) {
  throw new Error(
    `remotion.config: no custom-component registry at ${aliasTarget} ` +
    `(set WRAP_ENGINE_ROOT to the engine root, or POSTER_ROOT to a project ` +
    `that ships remotion-custom.tsx)`
  );
}

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
