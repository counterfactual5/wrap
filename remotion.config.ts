import {Config} from '@remotion/cli/config';

// Deterministic rendering: PNG frames, fixed pixel format, no color management surprises.
Config.setVideoImageFormat('png');
Config.setPixelFormat('yuv420p');
Config.setCodec('h264');
Config.setOverwriteOutput(true);
