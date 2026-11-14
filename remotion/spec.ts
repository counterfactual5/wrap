// Rendering contracts contain media and project components, never built-in designs.
export type Rect = [x: number, y: number, w: number, h: number];
export type Ease = 'linear' | 'in' | 'out' | 'inout' | 'snap' | 'overshoot' | 'step';
export type Keyframe = [number, number] | [number, number, Ease];
export type Anim = Partial<Record<'x' | 'y' | 'scale' | 'opacity' | 'rotate' | 'flipX', Keyframe[]>>;
export type GeometricMotion = {
  type: 'geometric';
  zoom?: [number, number];
  pan?: [number, number];
};
export type PoseSpec = {frame: number; asset: string};
export type SpringSpec = {
  omega?: number;
  zeta?: number;
  coupling?: number;
  channel?: 'x' | 'y' | 'scale' | 'rotate';
  driverChannel?: 'x' | 'y' | 'scale' | 'rotate';
  maxAccel?: number;
};
export type LayerGeometry = {
  id: string;
  rect: Rect;
  z: number;
  anim?: Anim;
  parent?: string;
  pivot?: [number, number];
  joint?: [number, number];
  socket?: [number, number];
  clipRect?: Rect;
  flipX?: boolean;
  spring?: SpringSpec;
};
export type AiLayer = LayerGeometry & {
  type: 'ai' | 'image';
  asset: string;
  keyColor?: string;
  blend?: 'multiply' | 'screen' | 'normal';
  cutout?: boolean;
  cutoutSimilarity?: number;
  cutoutBlend?: number;
  input_asset?: string;
  reference_images?: string[];
  poses?: PoseSpec[];
  motion?: GeometricMotion;
  fit?: 'cover' | 'contain';
};
export type VideoLayer = LayerGeometry & {
  type: 'video';
  asset: string;
  fit?: 'cover' | 'contain';
  trim?: [number, number];
  playbackRate?: number;
  loop?: boolean;
  muted?: boolean;
  first_frame?: string;
  input_asset?: string;
  input_image?: string;
  last_frame?: string;
  last_frame_image?: string;
  reference_type?: 'first_frame' | 'last_frame' | 'subject';
  reference_images?: string[];
  motion?: GeometricMotion;
};
export type ComponentLayer = LayerGeometry & {
  type: 'component';
  component: string;
  props?: Record<string, unknown>;
};
export type Layer = AiLayer | VideoLayer | ComponentLayer;
export type Tracks = {
  captions?: Array<{frame: number; end_frame?: number; text: string}>;
  events?: Array<{frame: number; [key: string]: unknown}>;
};
export type AudioSpec = {voiceover?: string; voice?: string; bgm?: string};
export type Gate = {
  id: string;
  metric: 'changed_pixel_ratio' | 'subject_motion_ratio' | 'red_pixel_ratio' | 'accent_color_ratio' | 'edge_key_purity';
  lo?: number;
  hi?: number;
  lumaDelta?: number;
  region?: [number, number];
  ring?: number;
  tol?: number;
};
export type ShotSpec = {
  id: string;
  canvas: {w: number; h: number; bg?: string};
  fps: number;
  durationInFrames: number;
  style?: string;
  audio?: AudioSpec;
  tracks?: Tracks;
  layers: Layer[];
  gates?: Gate[];
};
