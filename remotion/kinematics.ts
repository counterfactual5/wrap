// Generic keyframe & skeletal puppet engine: expression lives in the spec
// (layer.anim, parent, pivot, gait, spring, poses, flipX, depth, clipRect).
// This file is the TypeScript mirror of renderers/quartz/compose.swift — the two
// must evaluate the same kinematics frame for frame.
import type {Anim, Ease, Keyframe, Layer} from './spec';

export const applyEase = (t: number, ease: Ease): number => {
  switch (ease) {
    case 'in':
      return t * t;
    case 'out':
      return 1 - (1 - t) * (1 - t);
    case 'inout':
      return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    case 'snap':
      return 1 - Math.pow(1 - t, 4);
    case 'overshoot': {
      const c1 = 1.70158;
      const c3 = c1 + 1.0;
      return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
    }
    case 'step':
      return t < 1 ? 0 : 1;
    default:
      return t;
  }
};

export const channelValue = (kfs: Keyframe[] | undefined, frame: number, fallback: number): number => {
  if (!kfs || kfs.length === 0) return fallback;
  const first = kfs[0] as [number, number];
  const last = kfs[kfs.length - 1] as [number, number];
  if (frame <= first[0]) return first[1];
  if (frame >= last[0]) return last[1];
  for (let i = 0; i < kfs.length - 1; i++) {
    const k0 = kfs[i] as [number, number, Ease?];
    const k1 = kfs[i + 1] as [number, number, Ease?];
    if (frame >= k0[0] && frame <= k1[0]) {
      const span = Math.max(1e-6, k1[0] - k0[0]);
      const t = (frame - k0[0]) / span;
      return k0[1] + (k1[1] - k0[1]) * applyEase(t, k1[2] ?? 'linear');
    }
  }
  return fallback;
};

export interface TransformState {
  x: number;
  y: number;
  scale: number;
  rotate: number;
  opacity: number;
  depth: number;
  flipX: boolean;
}

export const evalBaseAnim = (layer: Layer, frame: number): TransformState => {
  const anim: Anim | undefined = layer.anim;
  const x = channelValue(anim?.x, frame, 0);
  const y = channelValue(anim?.y, frame, 0);
  const scale = channelValue(anim?.scale, frame, 1);
  const rotate = channelValue(anim?.rotate, frame, 0);
  const opacity = channelValue(anim?.opacity, frame, 1);
  const baseDepth = layer.type === 'ai' && typeof layer.depth === 'number' ? layer.depth : 0;
  const depth = Math.max(0, Math.min(1, channelValue(anim?.depth, frame, baseDepth)));
  const baseFlip = layer.flipX ? 1 : 0;
  const flipVal = channelValue(anim?.flipX, frame, baseFlip);
  return {x, y, scale, rotate, opacity, depth, flipX: flipVal >= 0.5};
};

const evalGaitModulation = (
  layer: Layer,
  frame: number,
  fps: number,
  layerMap: Record<string, Layer>
): {dx: number; dy: number; drot: number} => {
  const gait = layer.gait;
  const parentLayer = layer.parent ? layerMap[layer.parent] : undefined;
  const parentGait = parentLayer ? parentLayer.gait : undefined;

  if (!gait) {
    if (parentGait && parentGait.mode === 'shudder') {
      const range = parentGait.range;
      if (range && (frame < range[0] || frame > range[1])) return {dx: 0, dy: 0, drot: 0};
      const freq = parentGait.freq ?? 10;
      const sway = parentGait.sway ?? 3.2;
      const t = frame / Math.max(1, fps);
      const phase = t * freq * 2 * Math.PI + (layer.id.length % 5) * 0.9;
      return {dx: 0, dy: 0, drot: sway * 1.35 * Math.sin(phase * 1.7)};
    }
    return {dx: 0, dy: 0, drot: 0};
  }

  if (gait.range && (frame < gait.range[0] || frame > gait.range[1])) {
    return {dx: 0, dy: 0, drot: 0};
  }

  let vx = 0;
  if (layer.anim?.x && layer.anim.x.length >= 2) {
    vx = channelValue(layer.anim.x, frame + 1, 0) - channelValue(layer.anim.x, frame - 1, 0);
  } else if (parentLayer?.anim?.x && parentLayer.anim.x.length >= 2) {
    vx = channelValue(parentLayer.anim.x, frame + 1, 0) - channelValue(parentLayer.anim.x, frame - 1, 0);
  }
  const speedFactor = Math.min(1.6, Math.max(0.35, Math.abs(vx) * 0.18));
  const freq = gait.freq ?? 3.2;
  const bob = gait.bob ?? 6.0;
  const sway = gait.sway ?? 2.2;
  const phOff = gait.phase ?? 0;
  const t = frame / Math.max(1, fps);
  const phase = t * freq * 2 * Math.PI + phOff;

  if (gait.mode === 'puppet') {
    const qPhase = Math.round((phase / (2 * Math.PI)) * 12) * ((2 * Math.PI) / 12);
    return {
      dx: 0,
      dy: -Math.abs(Math.sin(qPhase)) * bob * speedFactor,
      drot: Math.sin(qPhase) * sway * speedFactor + Math.sin(phase * 3.5) * 0.6,
    };
  }
  if (gait.mode === 'walk') {
    return {
      dx: 0,
      dy: -Math.abs(Math.sin(phase)) * bob * speedFactor,
      drot: Math.cos(phase) * sway * speedFactor,
    };
  }
  if (gait.mode === 'float') {
    return {
      dx: Math.cos(phase * 0.5) * (bob * 0.4),
      dy: Math.sin(phase) * bob,
      drot: Math.sin(phase * 0.7) * sway,
    };
  }
  if (gait.mode === 'shudder') {
    return {
      dx: Math.sin(phase * 2.3) * (bob * 0.65),
      dy: Math.cos(phase * 1.9) * (bob * 0.45),
      drot: Math.sin(phase * 2.7) * sway,
    };
  }
  return {dx: 0, dy: 0, drot: 0};
};

const selectAnimChannel = (anim: Anim | undefined, name: string): Keyframe[] | undefined => {
  switch (name) {
    case 'x': return anim?.x;
    case 'y': return anim?.y;
    case 'scale': return anim?.scale;
    case 'rotate': return anim?.rotate;
    default: return anim?.rotate;
  }
};

const computeSpringOffset = (
  layer: Layer,
  parentLayer: Layer | undefined,
  frame: number,
  fps: number
): number => {
  const sp = layer.spring;
  if (!sp) return 0.0;
  const omega = sp.omega ?? 18.0;
  const zeta = sp.zeta ?? 0.25;
  const coupling = sp.coupling ?? 0.45;
  const maxAccel = Math.max(1.0, sp.maxAccel ?? 4500.0);
  const targetCh = sp.channel ?? 'rotate';
  const driverAnim = parentLayer?.anim ?? layer.anim;
  const driverKfs = sp.driverChannel
    ? selectAnimChannel(driverAnim, sp.driverChannel)
    : selectAnimChannel(driverAnim, targetCh) ?? driverAnim?.rotate ?? driverAnim?.x ?? driverAnim?.y ?? driverAnim?.scale;
  if (!driverKfs || driverKfs.length < 2) return 0.0;

  const dtFrame = 1.0 / Math.max(1.0, fps);
  const substeps = 4;
  const dt = dtFrame / substeps;
  let theta = 0.0;
  let vel = 0.0;
  const maxF = Math.max(0, Math.floor(frame));
  for (let f = 1; f <= maxF; f++) {
    const uPrev = channelValue(driverKfs, Math.max(0, f - 1), 0.0);
    const uCurr = channelValue(driverKfs, f, 0.0);
    const uNext = channelValue(driverKfs, f + 1, uCurr);
    const rawAccel = (uNext - 2.0 * uCurr + uPrev) / (dtFrame * dtFrame);
    const accel = Math.max(-maxAccel, Math.min(maxAccel, rawAccel));
    for (let s = 0; s < substeps; s++) {
      const force = -coupling * accel - 2.0 * zeta * omega * vel - omega * omega * theta;
      vel += force * dt;
      theta += vel * dt;
    }
  }
  return theta;
};
export const evalLayerTransform = (
  layer: Layer,
  frame: number,
  fps: number,
  layerMap: Record<string, Layer>
): TransformState => {
  const s = evalBaseAnim(layer, frame);
  const g = evalGaitModulation(layer, frame, fps, layerMap);
  const parentLayer = layer.parent ? layerMap[layer.parent] : undefined;
  const spOffset = computeSpringOffset(layer, parentLayer, frame, fps);
  const spCh = layer.spring?.channel ?? 'rotate';
  let sx = s.x + g.dx;
  let sy = s.y + g.dy;
  let srot = s.rotate + g.drot;
  let sscale = s.scale;
  if (spOffset !== 0) {
    if (spCh === 'x') sx += spOffset;
    else if (spCh === 'y') sy += spOffset;
    else if (spCh === 'scale') sscale = Math.max(0.05, sscale + spOffset * 0.01);
    else srot += spOffset;
  }
  return {
    ...s,
    x: sx,
    y: sy,
    scale: sscale,
    rotate: srot,
  };
};

export const activeLayerIdForFrame = (layer: Layer, frame: number): string => {
  if (layer.type !== 'ai' || !layer.poses || layer.poses.length === 0) return layer.id;
  let chosenIdx = -1;
  let bestFrame = -1;
  layer.poses.forEach((p, idx) => {
    if (frame >= p.frame && p.frame >= bestFrame) {
      bestFrame = p.frame;
      chosenIdx = idx;
    }
  });
  return chosenIdx >= 0 ? `${layer.id}__pose_${chosenIdx}` : layer.id;
};
