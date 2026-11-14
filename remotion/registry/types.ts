import type React from 'react';
import type {ComponentLayer, Rect, Tracks} from '../spec';

export type CustomComponentProps = {
  layer: ComponentLayer;
  /** Canvas coordinates; the component owns its positioning. */
  rect: Rect;
  props?: Record<string, unknown>;
  /** Prepared top-level media, keyed by layer id. No separate component asset system. */
  prepared: Record<string, string>;
  preparedVideos: Record<string, string>;
  tracks: Tracks;
  frame: number;
  fps: number;
  durationInFrames: number;
};

export type CustomComponentRegistry = Record<string, React.FC<CustomComponentProps>>;
