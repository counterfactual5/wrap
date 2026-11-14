import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {CodeLayer} from '../spec';

export const Bar: React.FC<{color: string; width: number; height: number}> = ({
  color,
  width,
  height,
}) => (
  <div
    style={{
      position: 'absolute',
      width,
      height,
      backgroundColor: color,
    }}
  />
);


// ---------------------------------------------------------------------------
// Parameterized primitives: everything creative lives in layer.params; the
// component is a dumb interpreter. No baked-in decorations, no fixed layout.
// ---------------------------------------------------------------------------

/** Deterministic PRNG (mulberry32) — renders must stay bit-exact. */
const seededRandom = (seed: number) => () => {
  seed |= 0;
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

const num = (v: unknown, dflt: number): number => (typeof v === 'number' && !Number.isNaN(v) ? v : dflt);
const numList = (v: unknown, dflt: number[]): number[] =>
  Array.isArray(v) && v.length >= 2 && v.every((x) => typeof x === 'number') ? (v as number[]) : dflt;
const strList = (v: unknown, dflt: string[]): string[] =>
  Array.isArray(v) && v.every((x) => typeof x === 'string') && v.length > 0 ? (v as string[]) : dflt;

export const FieldComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {rect, color, params = {}} = layer;
  const width = rect[2];
  const height = rect[3];

  const count = Math.round(num(params.count, 40));
  const seed = Math.round(num(params.seed, 7));
  const colors = strList(params.colors, color ? [color] : ['#00F0FF']);
  const speed = numList(params.speed, [1, 3]); // px/frame
  const size = numList(params.size, [2, 5]);
  const dirDeg = num(params.dir, 0); // 0 = rightward, 90 = downward
  const spreadDeg = num(params.spread, 12);
  const glow = params.glow !== false;

  const dirRad = (dirDeg * Math.PI) / 180;
  const spreadRad = (spreadDeg * Math.PI) / 180;
  const rnd = seededRandom(seed);
  const particles = Array.from({length: count}).map((_, i) => {
    const angle = dirRad + (rnd() - 0.5) * 2 * spreadRad;
    const v = speed[0] + rnd() * (speed[1] - speed[0]);
    const span = Math.max(width, height) * 1.6;
    const travel = ((rnd() * span) + frame * v) % span;
    const jitter = (rnd() - 0.5) * 2 * spreadRad * travel * 0.6;
    const px = (Math.cos(angle + jitter) * travel + width) % width;
    const py = (Math.sin(angle + jitter) * travel + height) % height;
    return {
      x: ((px % width) + width) % width,
      y: ((py % height) + height) % height,
      r: size[0] + rnd() * (size[1] - size[0]),
      c: colors[i % colors.length],
      o: 0.25 + rnd() * 0.6,
    };
  });

  return (
    <div style={{position: 'absolute', left: rect[0], top: rect[1], width, height, overflow: 'hidden', pointerEvents: 'none'}}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        {particles.map((p, i) => (
          <g key={i}>
            {glow && <circle cx={p.x.toFixed(1)} cy={p.y.toFixed(1)} r={p.r * 2.4} fill={p.c} opacity={p.o * 0.25} />}
            <circle cx={p.x.toFixed(1)} cy={p.y.toFixed(1)} r={p.r} fill={p.c} opacity={p.o} />
          </g>
        ))}
      </svg>
    </div>
  );
};


export const PathComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {rect, color, params = {}} = layer;
  const width = rect[2];
  const height = rect[3];

  const d = typeof params.d === 'string' ? params.d : '';
  const stroke = typeof params.stroke === 'string' ? params.stroke : color || '#00F0FF';
  const strokeWidth = num(params.width, 4);
  const opacity = num(params.opacity, 1);
  // reveal: [fromFrame, toFrame] — 1-unit pathLength dash reveal
  const reveal = numList(params.reveal, [0, 60]);
  const flow = params.flow === true; // animated dash drift instead of solid reveal
  const flowDash = numList(params.flowDash, [10, 14]);

  if (!d) return null;
  const t = Math.min(1, Math.max(0, (frame - reveal[0]) / Math.max(1, reveal[1] - reveal[0])));
  const eased = 1 - (1 - t) * (1 - t); // ease-out reveal

  return (
    <div style={{position: 'absolute', left: rect[0], top: rect[1], width, height, overflow: 'hidden', pointerEvents: 'none'}}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        {flow ? (
          <path
            d={d}
            fill="none"
            stroke={stroke}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={`${flowDash[0]} ${flowDash[1]}`}
            strokeDashoffset={-frame * 1.5}
            opacity={t > 0 ? opacity : 0}
            filter="drop-shadow(0 0 6px currentColor)"
          />
        ) : (
          <path
            d={d}
            fill="none"
            stroke={stroke}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            pathLength={1}
            strokeDasharray={1}
            strokeDashoffset={1 - eased}
            opacity={opacity}
            filter="drop-shadow(0 0 6px currentColor)"
          />
        )}
      </svg>
    </div>
  );
};


export const CaptionsComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {rect, params = {}} = layer;
  const width = rect[2];

  type Item = {frame: number; end_frame?: number; text: string; hl?: string; size?: number};
  const items: Item[] = Array.isArray(params.items) ? (params.items as unknown as Item[]) : [];
  const size = num(params.size, 92);
  const hlColor = typeof params.hlColor === 'string' ? params.hlColor : '#FFB84D';

  const current = [...items].reverse().find((it) => frame >= it.frame);
  if (!current || (typeof current.end_frame === 'number' && frame > current.end_frame)) return null;
  const itemSize = typeof current.size === 'number' ? current.size : size;
  const local = frame - current.frame;
  const pop = Math.min(1, local / 7);
  const scale = pop < 0.35 ? 0.85 + 0.38 * (pop / 0.35) : 1.23 - 0.23 * ((pop - 0.35) / 0.65);
  const opacity = Math.min(1, local / 3);

  const parts: Array<{t: string; hl: boolean}> = [];
  if (current.hl && current.text.includes(current.hl)) {
    const [a, ...rest] = current.text.split(current.hl);
    if (a) parts.push({t: a, hl: false});
    parts.push({t: current.hl, hl: true});
    if (rest.length) parts.push({t: rest.join(current.hl), hl: false});
  } else {
    parts.push({t: current.text, hl: false});
  }

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width,
        height: rect[3],
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          transform: `scale(${scale.toFixed(3)})`,
          opacity,
          backgroundColor: 'rgba(5, 5, 12, 0.55)',
          padding: '16px 34px',
          borderRadius: 20,
          fontSize: itemSize,
          fontWeight: 900,
          lineHeight: 1.3,
          textAlign: 'center',
          color: '#FFFFFF',
          WebkitTextStroke: '3px #05050C',
          paintOrder: 'stroke fill',
          textShadow: '0 4px 24px rgba(0,0,0,0.85)',
          letterSpacing: '0.01em',
          whiteSpace: 'pre-line',
        }}
      >
        {parts.map((seg, i) =>
          seg.hl ? (
            <span key={i} style={{color: hlColor, textShadow: `0 0 26px ${hlColor}66, 0 4px 24px rgba(0,0,0,0.85)`}}>
              {seg.t}
            </span>
          ) : (
            <span key={i}>{seg.t}</span>
          )
        )}
      </div>
    </div>
  );
};
