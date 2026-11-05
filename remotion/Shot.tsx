import React from 'react';
import {Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {Video} from '@remotion/media';
import {
  Bar,
  BlackHoleHeroComp,
  CardComp,
  GeodesicComp,
  GravityWellComp,
  HudComp,
  LightConeTiltHeroComp,
  LightDeflectionComp,
  RipplesComp,
  SpacetimeWavesComp,
  SpaghettificationHeroComp,
  TextComp,
  TimeDilationHeroComp,
  TrampolineComp,
  TunnelHeroComp,
  WavefunctionHeroComp,
  FieldComp,
  PathComp,
  CaptionsComp,
} from './layers';
import type {AiLayer, Anim, CodeLayer, Ease, Keyframe, Layer, ShotSpec, VideoLayer} from './spec';

// ---------------------------------------------------------------------------
// Generic keyframe engine: expression lives in the spec (layer.anim), the
// renderer only interpolates. Channels: x/y translate, scale, opacity, rotate.
// ---------------------------------------------------------------------------
const applyEase = (t: number, ease: Ease): number => {
  switch (ease) {
    case 'in':
      return t * t;
    case 'out':
      return 1 - (1 - t) * (1 - t);
    case 'inout':
      return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    default:
      return t;
  }
};

const channelValue = (kfs: Keyframe[], frame: number, fallback: number): number => {
  const first = kfs[0];
  const last = kfs[kfs.length - 1];
  if (frame <= (first as [number, number])[0]) return (first as [number, number])[1];
  if (frame >= (last as [number, number])[0]) return (last as [number, number])[1];
  for (let i = 0; i < kfs.length - 1; i++) {
    const k0 = kfs[i] as [number, number, Ease?];
    const k1 = kfs[i + 1] as [number, number, Ease?];
    if (frame >= k0[0] && frame <= k1[0]) {
      const t = (frame - k0[0]) / (k1[0] - k0[0]);
      return k0[1] + (k1[1] - k0[1]) * applyEase(t, k1[2] ?? 'linear');
    }
  }
  return fallback;
};

const AnimatedLayer: React.FC<{layer: Layer; children: React.ReactNode}> = ({layer, children}) => {
  const anim: Anim | undefined = layer.anim;
  if (!anim) return <>{children}</>;
  const frame = useCurrentFrame();
  const x = anim.x ? channelValue(anim.x, frame, 0) : 0;
  const y = anim.y ? channelValue(anim.y, frame, 0) : 0;
  const scale = anim.scale ? channelValue(anim.scale, frame, 1) : 1;
  const rotate = anim.rotate ? channelValue(anim.rotate, frame, 0) : 0;
  const opacity = anim.opacity ? channelValue(anim.opacity, frame, 1) : 1;
  const transform =
    x === 0 && y === 0 && scale === 1 && rotate === 0
      ? undefined
      : `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px) scale(${scale.toFixed(4)}) rotate(${rotate.toFixed(2)}deg)`;
  return (
    <div style={{position: 'absolute', inset: 0, transform, opacity, willChange: 'transform, opacity'}}>
      {children}
    </div>
  );
};

const FloatingParticles: React.FC<{count?: number}> = ({count = 32}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();

  return (
    <div style={{position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden'}}>
      {Array.from({length: count}).map((_, i) => {
        // Deterministic pseudo-random seed based on index
        const seedX = ((i * 137.5) % 1) * width;
        const seedY = ((i * 269.3) % 1) * height;
        const speed = 0.4 + ((i * 31.7) % 1) * 0.8;
        const size = 1.5 + ((i * 17.3) % 1) * 2.5;

        // Upward floating motion with gentle horizontal oscillation
        const y = (seedY - frame * speed * 2 + height) % height;
        const x = seedX + Math.sin((frame + i * 15) * 0.05) * 20;
        const opacity = 0.2 + Math.abs(Math.sin((frame + i * 20) * 0.06)) * 0.6;
        const isAmber = i % 4 === 0;

        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: x,
              top: y,
              width: size,
              height: size,
              borderRadius: '50%',
              backgroundColor: isAmber ? '#FFB800' : '#00F0FF',
              boxShadow: `0 0 ${size * 3}px ${isAmber ? '#FFB800' : '#00F0FF'}`,
              opacity,
            }}
          />
        );
      })}
    </div>
  );
};

const PreparedLayer: React.FC<{
  layer: AiLayer | CodeLayer;
  src: string;
  isVerticalVibe?: boolean;
}> = ({layer, src, isVerticalVibe = false}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const {rect, motion} = layer;
  const zoom = motion?.zoom ?? [1, 1];
  const scale = interpolate(
    frame,
    [0, durationInFrames - 1],
    [zoom[0], zoom[1]]
  );

  const isAi = layer.type === 'ai';
  // plate=false: full-bleed presentation — no card chrome (border, rounding,
  // inner bg, vignette). The chrome is a spec decision, not a renderer default.
  const plate = !(isAi && (layer as {plate?: boolean}).plate === false);
  const blendMode =
    isAi && layer.blend === 'multiply'
      ? 'multiply'
      : isAi && layer.blend === 'screen'
        ? 'screen'
        : 'normal';

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width: rect[2],
        height: rect[3],
        overflow: 'hidden',
        borderRadius: plate && isAi && isVerticalVibe ? 20 : 0,
        border: plate && isAi && isVerticalVibe ? '1px solid rgba(0, 240, 255, 0.3)' : undefined,
        boxShadow: plate && isAi && isVerticalVibe ? '0 20px 60px rgba(0,0,0,0.8), 0 0 40px rgba(0, 240, 255, 0.12)' : undefined,
        backgroundColor: plate && isAi && isVerticalVibe ? '#030509' : undefined,
      }}
    >
      <Img
        src={src}
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          width: '100%',
          height: '100%',
          objectFit: isAi && layer.fit ? layer.fit : 'cover',
          transform: `translate(-50%, -50%) scale(${scale})`,
          transformOrigin: 'center',
          mixBlendMode: blendMode,
          filter: plate && isAi && isVerticalVibe ? 'contrast(1.08) brightness(1.02)' : undefined,
        }}
      />
      {/* Soft edge vignette to integrate smoothly into dark border */}
      {plate && isAi && isVerticalVibe && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            boxShadow: 'inset 0 0 70px 30px #030509',
            pointerEvents: 'none',
          }}
        />
      )}
    </div>
  );
};

const VideoLayerComp: React.FC<{layer: VideoLayer; src: string}> = ({layer, src}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps} = useVideoConfig();
  const {rect, motion} = layer;
  const zoom = motion?.zoom ?? [1, 1];
  const scale = interpolate(frame, [0, durationInFrames - 1], [zoom[0], zoom[1]]);
  // A video layer has no key color to key out — it is placed as-is. The
  // chrome (border/rounding/vignette) is a spec decision, same as for an ai
  // layer, and defaults to on unless plate:false asks for full bleed.
  const plate = layer.plate !== false;
  const trim = layer.trim;
  // trim is expressed in seconds; Remotion wants frames. S2 re-encodes every
  // clip to the SHOT's frame rate, so the source the renderer sees is always
  // at the canvas fps — that is the rate the seconds must be converted with.
  const trimBefore = trim ? Math.round(trim[0] * fps) : undefined;
  const trimAfter = trim ? Math.round(trim[1] * fps) : undefined;
  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width: rect[2],
        height: rect[3],
        overflow: 'hidden',
        borderRadius: plate ? 12 : 0,
        backgroundColor: plate ? '#030509' : undefined,
      }}
    >
      <Video
        src={staticFile(src)}
        trimBefore={trimBefore}
        trimAfter={trimAfter}
        loop={layer.loop ?? true}
        muted={layer.muted ?? true}
        playbackRate={layer.playbackRate ?? 1}
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          width: '100%',
          height: '100%',
          objectFit: layer.fit ?? 'cover',
          transform: `translate(-50%, -50%) scale(${scale})`,
          transformOrigin: 'center',
        }}
      />
      {plate && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            boxShadow: 'inset 0 0 70px 30px #030509',
            pointerEvents: 'none',
          }}
        />
      )}
    </div>
  );
};

const CodeLayerComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const {rect, motion, color} = layer;

  if (layer.draw === 'grid' || layer.draw === 'dots') {
    return null;
  }

  if (layer.draw === 'geodesic') {
    return <GeodesicComp layer={layer} />;
  }

  if (layer.draw === 'ripples') {
    return <RipplesComp layer={layer} />;
  }

  if (layer.draw === 'trampoline') {
    return <TrampolineComp layer={layer} />;
  }

  if (layer.draw === 'gravity-well') {
    return <GravityWellComp layer={layer} />;
  }

  if (layer.draw === 'light-deflection') {
    return <LightDeflectionComp layer={layer} />;
  }

  if (layer.draw === 'spacetime-waves') {
    return <SpacetimeWavesComp layer={layer} />;
  }

  if (layer.draw === 'blackhole-hero') {
    return <BlackHoleHeroComp layer={layer} />;
  }

  if (layer.draw === 'time-dilation') {
    return <TimeDilationHeroComp layer={layer} />;
  }

  if (layer.draw === 'light-cone-tilt') {
    return <LightConeTiltHeroComp layer={layer} />;
  }

  if (layer.draw === 'spaghettification') {
    return <SpaghettificationHeroComp layer={layer} />;
  }

  if (layer.draw === 'tunnel-hero') {
    return <TunnelHeroComp layer={layer} />;
  }

  if (layer.draw === 'wavefunction-hero') {
    return <WavefunctionHeroComp layer={layer} />;
  }

  if (layer.draw === 'field') {
    return <FieldComp layer={layer} />;
  }

  if (layer.draw === 'path') {
    return <PathComp layer={layer} />;
  }

  if (layer.draw === 'captions') {
    return <CaptionsComp layer={layer} />;
  }

  // bar
  const pan = motion?.pan ?? [rect[0], rect[0]];
  const x = interpolate(frame, [0, durationInFrames - 1], [pan[0], pan[1]]);
  return (
    <div style={{position: 'absolute', left: 0, top: 0, width: '100%', height: '100%'}}>
      <div style={{position: 'absolute', left: x, top: rect[1]}}>
        <Bar color={color ?? '#E03A3A'} width={rect[2]} height={rect[3]} />
      </div>
    </div>
  );
};

export const Shot: React.FC<{
  spec: ShotSpec;
  prepared: Record<string, string>;
  preparedVideos?: Record<string, string>;
}> = ({spec, prepared, preparedVideos}) => {
  const frame = useCurrentFrame();
  const layers = [...spec.layers].sort((a, b) => a.z - b.z);
  const isVerticalVibe = spec.canvas.w === 1080;
  // vibe=false: the shot opts out of the baked vertical-vibe ambience
  // (floating particles, scanline, blueprint grid, radial glow). Atmosphere
  // should come from spec layers (field/path), not renderer defaults.
  const vibe = isVerticalVibe && (spec as {vibe?: boolean}).vibe !== false;
  const bgColor = (spec.canvas as any).bg || (isVerticalVibe ? '#06080F' : '#fff');

  // Zoom punches: whole-canvas scale spike at each spec'd frame — the beat hit.
  const punches = spec.punches ?? [];
  let punchScale = 1;
  let punchFlash = 0;
  for (const f of punches) {
    if (frame >= f && frame <= f + 9) {
      punchScale = Math.max(punchScale, 1 + 0.13 * Math.sin((Math.PI * (frame - f)) / 9));
    }
    if (frame >= f && frame < f + 5) {
      punchFlash = Math.max(punchFlash, 0.32 * (1 - (frame - f) / 5));
    }
  }

  return (
    <div
      style={{
        position: 'relative',
        width: spec.canvas.w,
        height: spec.canvas.h,
        backgroundColor: bgColor,
        overflow: 'hidden',
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif',
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          transform: punchScale !== 1 ? `scale(${punchScale.toFixed(4)})` : undefined,
        }}
      >
      {punchFlash > 0 && (
        <div style={{position: 'absolute', inset: 0, backgroundColor: '#FFFFFF', opacity: punchFlash, pointerEvents: 'none'}} />
      )}
      {/* Dynamic atmospheric layer for vertical vibe video (spec may opt out) */}
      {vibe && (
        <>
          {/* 1. Deep space ambient radial glow centered on visual region */}
          <div
            style={{
              position: 'absolute',
              top: 300,
              left: '50%',
              transform: 'translateX(-50%)',
              width: 1000,
              height: 700,
              background: `radial-gradient(ellipse at center, rgba(0, 240, 255, ${
                0.12 + Math.sin(frame * 0.05) * 0.03
              }) 0%, rgba(255, 184, 0, 0.04) 50%, transparent 75%)`,
              pointerEvents: 'none',
            }}
          />

          {/* 2. Floating living quantum particles */}
          <FloatingParticles count={36} />

          {/* 3. Subtle blueprint grid */}
          <div
            style={{
              position: 'absolute',
              inset: 0,
              backgroundImage: `
                linear-gradient(to right, rgba(0, 240, 255, 0.04) 1px, transparent 1px),
                linear-gradient(to bottom, rgba(0, 240, 255, 0.04) 1px, transparent 1px)
              `,
              backgroundSize: '40px 40px',
              pointerEvents: 'none',
              opacity: 0.9,
            }}
          />

          {/* 4. Sweeping technical laser scanline */}
          <div
            style={{
              position: 'absolute',
              left: 0,
              top: (frame * 6) % spec.canvas.h,
              width: '100%',
              height: 5,
              background: 'linear-gradient(90deg, transparent 5%, #00F0FF 50%, transparent 95%)',
              boxShadow: '0 0 16px #00F0FF',
              opacity: 0.85,
              pointerEvents: 'none',
            }}
          />
        </>
      )}

      {layers.map((layer: Layer) => (
        <AnimatedLayer key={layer.id} layer={layer}>
          {layer.type === 'video' ? (
            <VideoLayerComp layer={layer} src={preparedVideos?.[layer.id] ?? ''} />
          ) : layer.type === 'ai' || (layer.type === 'code' && (layer.draw === 'grid' || layer.draw === 'dots')) ? (
            <PreparedLayer layer={layer} src={prepared[layer.id]} isVerticalVibe={isVerticalVibe} />
          ) : layer.type === 'code' ? (
            <CodeLayerComp layer={layer} />
          ) : layer.type === 'text' ? (
            <TextComp layer={layer} />
          ) : layer.type === 'hud' ? (
            <HudComp layer={layer} />
          ) : layer.type === 'card' ? (
            <CardComp layer={layer} />
          ) : null}
        </AnimatedLayer>
      ))}
      </div>
    </div>
  );
};
