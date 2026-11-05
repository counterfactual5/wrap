// Spec types: the JSON in spec/*.poster.json is the single source of truth.
// S1/S2/S4 (Python) and this renderer (TypeScript) both read the same files;
// keep these types in sync with schema.py.

export type Rect = [x: number, y: number, w: number, h: number];

export type GeometricMotion = {
  type: 'geometric';
  /** [from, to] scale factors, linear over the shot. >= 1 so zoom never exposes an edge. */
  zoom?: [number, number];
  /** [xFrom, xTo] horizontal pan for bar layers, in canvas pixels. */
  pan?: [number, number];
};

export type Ease = 'linear' | 'in' | 'out' | 'inout';

/** [frame, value] or [frame, value, ease]; ease applies to the segment ending at this keyframe. */
export type Keyframe = [number, number] | [number, number, Ease];

/** Generic choreography: expression lives in the spec, the renderer only interpolates. */
export type Anim = Partial<Record<'x' | 'y' | 'scale' | 'opacity' | 'rotate', Keyframe[]>>;

/** Free parameter bag for primitive draws (field, path, captions, ...). */
export type Params = Record<
  string,
  string | number | boolean | number[] | string[] | Array<Record<string, unknown>>
>;

export type CodeLayer = {
  id: string;
  type: 'code';
  draw:
    | 'grid'
    | 'dots'
    | 'bar'
    | 'geodesic'
    | 'ripples'
    | 'trampoline'
    | 'gravity-well'
    | 'light-deflection'
    | 'spacetime-waves'
    | 'blackhole-hero'
    | 'time-dilation'
    | 'light-cone-tilt'
    | 'spaghettification'
    | 'tunnel-hero'
    | 'wavefunction-hero'
    | 'field'
    | 'path'
    | 'captions';
  rect: Rect;
  z: number;
  color?: string;
  motion?: GeometricMotion;
  params?: Params;
};

export type AiLayer = {
  id: string;
  type: 'ai';
  asset: string;
  keyColor: string;
  blend: 'multiply' | 'screen' | 'normal';
  rect: Rect;
  z: number;
  motion?: GeometricMotion;
  fit?: 'cover' | 'contain';
  /** false = full-bleed presentation, no card chrome (border/rounding/vignette). */
  plate?: boolean;
};

export type VideoLayer = {
  id: string;
  type: 'video';
  /** Frozen clip asset (assets/<asset>.mp4) — an mp4, never a still. */
  asset: string;
  rect: Rect;
  z: number;
  fit?: 'cover' | 'contain';
  /** [startSec, endSec] window into the source clip. */
  trim?: [number, number];
  /** Playback speed multiplier for the clip. */
  playbackRate?: number;
  loop?: boolean;
  /** true = the clip's own audio track is dropped (the TTS chain owns audio). */
  muted?: boolean;
  motion?: GeometricMotion;
  /** false = full-bleed presentation, no card chrome. */
  plate?: boolean;
};

export type TextLayer = {
  id: string;
  type: 'text';
  text: string;
  rect: Rect;
  z: number;
  fontSize?: number;
  fontWeight?: string | number;
  color?: string;
  subtext?: string;
  enter?: 'spring' | 'fade';
};

export type HudLayer = {
  id: string;
  type: 'hud';
  hudType: 'badge' | 'telemetry' | 'equalizer' | 'progress';
  rect: Rect;
  z: number;
  text?: string;
  color?: string;
};

export type CardLayer = {
  id: string;
  type: 'card';
  cardType: 'formula' | 'quote' | 'capsule';
  rect: Rect;
  z: number;
  title?: string;
  formula?: string;
  quote?: string;
  text?: string;
  author?: string;
  details?: Array<{label: string; desc: string; color?: string}>;
};

export type AudioSpec = {
  voiceover?: string;
  voice?: string;
  bgm?: string;
};

export type Layer = (CodeLayer | AiLayer | VideoLayer | TextLayer | HudLayer | CardLayer) & {
  /** Spec-driven keyframe channels applied by the renderer to ANY layer. */
  anim?: Anim;
};

export type Gate = {
  id: string;
  metric:
    | 'changed_pixel_ratio'
    | 'subject_motion_ratio'
    | 'red_pixel_ratio'
    | 'accent_color_ratio'
    | 'edge_key_purity';
  lo?: number;
  hi?: number;
  lumaDelta?: number;
  region?: [number, number];
  ring?: number;
  tol?: number;
};

export type ShotSpec = {
  id: string;
  canvas: {w: number; h: number};
  fps: number;
  durationInFrames: number;
  style?: string;
  audio?: AudioSpec;
  /** false = opt out of baked vertical-vibe ambience; bring your own via layers. */
  vibe?: boolean;
  /** Frame numbers for whole-canvas zoom punches (beat/keyword hits). */
  punches?: number[];
  /** Cinema grade pass on encode (grain + vignette + contrast). */
  vibe_grade?: boolean;
  layers: Layer[];
  gates: Gate[];
};
