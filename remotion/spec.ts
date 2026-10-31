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

export type CodeLayer = {
  id: string;
  type: 'code';
  draw: 'grid' | 'dots' | 'bar';
  rect: Rect;
  z: number;
  color?: string;
  motion?: GeometricMotion;
};

export type AiLayer = {
  id: string;
  type: 'ai';
  asset: string;
  keyColor: string;
  blend: 'multiply' | 'screen';
  rect: Rect;
  z: number;
  motion?: GeometricMotion;
};

export type Layer = CodeLayer | AiLayer;

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
  layers: Layer[];
  gates: Gate[];
};
