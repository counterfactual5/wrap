import React from 'react';
import {Img, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
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
} from './layers';
import type {AiLayer, CodeLayer, Layer, ShotSpec} from './spec';

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
        borderRadius: isAi && isVerticalVibe ? 20 : 0,
        border: isAi && isVerticalVibe ? '1px solid rgba(0, 240, 255, 0.3)' : undefined,
        boxShadow: isAi && isVerticalVibe ? '0 20px 60px rgba(0,0,0,0.8), 0 0 40px rgba(0, 240, 255, 0.12)' : undefined,
        backgroundColor: isAi && isVerticalVibe ? '#030509' : undefined,
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
          filter: isAi && isVerticalVibe ? 'contrast(1.08) brightness(1.02)' : undefined,
        }}
      />
      {/* Soft edge vignette to integrate smoothly into dark border */}
      {isAi && isVerticalVibe && (
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
}> = ({spec, prepared}) => {
  const frame = useCurrentFrame();
  const layers = [...spec.layers].sort((a, b) => a.z - b.z);
  const isVerticalVibe = spec.canvas.w === 1080;
  const bgColor = (spec.canvas as any).bg || (isVerticalVibe ? '#06080F' : '#fff');

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
      {/* Dynamic atmospheric layer for vertical vibe video */}
      {isVerticalVibe && (
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

      {layers.map((layer: Layer) => {
        if (layer.type === 'ai' || (layer.type === 'code' && (layer.draw === 'grid' || layer.draw === 'dots'))) {
          return <PreparedLayer key={layer.id} layer={layer} src={prepared[layer.id]} isVerticalVibe={isVerticalVibe} />;
        }
        if (layer.type === 'code') {
          return <CodeLayerComp key={layer.id} layer={layer} />;
        }
        if (layer.type === 'text') {
          return <TextComp key={layer.id} layer={layer} />;
        }
        if (layer.type === 'hud') {
          return <HudComp key={layer.id} layer={layer} />;
        }
        if (layer.type === 'card') {
          return <CardComp key={layer.id} layer={layer} />;
        }
        return null;
      })}
    </div>
  );
};
