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
import {CUSTOM_COMPONENTS} from './registry';
import {
  activeLayerIdForFrame,
  evalBaseAnim,
  evalLayerTransform,
} from './kinematics';

const LayerNode: React.FC<{
  layer: Layer;
  frame: number;
  fps: number;
  layerMap: Record<string, Layer>;
  children: React.ReactNode;
}> = ({layer, frame, fps, layerMap, children}) => {
  // Build ancestor chain [layer, parent, grandparent, ...] matching renderers/quartz/compose.swift
  const chain: Layer[] = [layer];
  const visited = new Set<string>([layer.id]);
  let cur: Layer = layer;
  while (cur.parent && layerMap[cur.parent] && !visited.has(cur.parent)) {
    visited.add(cur.parent);
    cur = layerMap[cur.parent];
    chain.push(cur);
  }

  let effectiveOpacity = 1;
  const transforms: Array<string | undefined> = [];
  for (let idx = 0; idx < chain.length; idx++) {
    const item = chain[idx];
    const ts = evalLayerTransform(item, frame, fps, layerMap);
    effectiveOpacity *= ts.opacity;
    const r = item.rect ?? [0, 0, 1920, 1080];
    const piv = item.pivot ?? [r[0] + r[2] / 2, r[1] + r[3] / 2];
    // When a text layer has no explicit pivot, flipX mirrors around the rendered
    // text content center inside TextComp rather than the full rect width center,
    // so left-aligned text is not flung to the opposite side of its wide rect box.
    const deferFlipToTextContent = idx === 0 && item.type === 'text' && !item.pivot;
    const effFlipX = deferFlipToTextContent ? false : ts.flipX;
    if (ts.x !== 0 || ts.y !== 0 || ts.scale !== 1 || ts.rotate !== 0 || effFlipX) {
      const sx = effFlipX ? -ts.scale : ts.scale;
      const sy = ts.scale;
      transforms.push(
        `translate(${(piv[0] + ts.x).toFixed(2)}px, ${(piv[1] + ts.y).toFixed(2)}px) scale(${sx.toFixed(4)}, ${sy.toFixed(4)}) rotate(${ts.rotate.toFixed(2)}deg) translate(${(-piv[0]).toFixed(2)}px, ${(-piv[1]).toFixed(2)}px)`
      );
    } else {
      transforms.push(undefined);
    }
  }

  const clipRect = layer.clipRect;

  let wrappedNode = (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        transform: transforms[0],
        transformOrigin: '0 0',
        opacity: effectiveOpacity,
        willChange: 'transform, opacity',
      }}
    >
      {children}
    </div>
  );

  for (let i = 1; i < transforms.length; i++) {
    if (transforms[i]) {
      wrappedNode = (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            transform: transforms[i],
            transformOrigin: '0 0',
          }}
        >
          {wrappedNode}
        </div>
      );
    }
  }

  const parentWrapped = wrappedNode;

  if (clipRect) {
    return (
      <div
        style={{
          position: 'absolute',
          left: clipRect[0],
          top: clipRect[1],
          width: clipRect[2],
          height: clipRect[3],
          overflow: 'hidden',
          pointerEvents: 'none',
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: -clipRect[0],
            top: -clipRect[1],
            width: '100%',
            height: '100%',
          }}
        >
          {parentWrapped}
        </div>
      </div>
    );
  }

  return parentWrapped;
};

const FloatingParticles: React.FC<{count?: number}> = ({count = 32}) => {
  const frame = useCurrentFrame();
  const {width, height} = useVideoConfig();

  return (
    <div style={{position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden'}}>
      {Array.from({length: count}).map((_, i) => {
        const seedX = ((i * 137.5) % 1) * width;
        const seedY = ((i * 269.3) % 1) * height;
        const speed = 0.4 + ((i * 31.7) % 1) * 0.8;
        const size = 1.5 + ((i * 17.3) % 1) * 2.5;

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

const hexToRgba = (hex: string | undefined, alpha: number): string => {
  const raw = (hex ?? '#000000').replace('#', '');
  const clean = raw.length === 3 ? raw.split('').map((c) => c + c).join('') : raw;
  const n = parseInt(clean, 16);
  if (Number.isNaN(n)) return `rgba(0, 0, 0, ${alpha.toFixed(3)})`;
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(3)})`;
};

const PreparedLayer: React.FC<{
  layer: AiLayer | CodeLayer;
  src: string;
  depth?: number;
  isVerticalVibe?: boolean;
}> = ({layer, src, depth = 0, isVerticalVibe = false}) => {
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
  const isCutout = isAi && Boolean(layer.cutout);
  const isTranslucent = isAi && (layer.translucent ?? layer.blend === 'multiply');
  const plate = !(isAi && (layer.plate === false || isCutout));
  const blendMode =
    isAi && layer.blend === 'multiply'
      ? 'multiply'
      : isAi && layer.blend === 'screen'
        ? 'screen'
        : 'normal';

  const objectFit = isAi && (layer.fit ?? (isCutout ? 'contain' : 'cover')) ? (layer.fit ?? (isCutout ? 'contain' : 'cover')) : 'cover';

  let imgFilter: string | undefined = plate && isAi && isVerticalVibe ? 'contrast(1.08) brightness(1.02)' : undefined;
  let normalAlpha = 1;
  if (isCutout) {
    const clampedDepth = Math.max(0, Math.min(1, depth));
    const penumbraBlur = 7 + clampedDepth * 16;
    const penumbraDx = 4 + clampedDepth * 8;
    const penumbraDy = 6 + clampedDepth * 10;
    const baseAlpha = isTranslucent ? 0.88 : 1;
    normalAlpha = Math.max(0.1, baseAlpha - clampedDepth * 0.16);
    const shCol = hexToRgba(layer.shadowColor ?? '#000000', Math.max(0.05, 0.42 - clampedDepth * 0.12));
    imgFilter = `drop-shadow(${penumbraDx.toFixed(1)}px ${penumbraDy.toFixed(1)}px ${penumbraBlur.toFixed(1)}px ${shCol})`;
  }

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width: rect[2],
        height: rect[3],
        overflow: isCutout ? 'visible' : 'hidden',
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
          objectFit,
          transform: `translate(-50%, -50%) scale(${scale})`,
          transformOrigin: 'center',
          mixBlendMode: isCutout ? 'normal' : blendMode,
          opacity: normalAlpha,
          filter: imgFilter,
        }}
      />
      {isCutout && isTranslucent && (
        <Img
          src={src}
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            width: '100%',
            height: '100%',
            objectFit,
            transform: `translate(-50%, -50%) scale(${scale})`,
            transformOrigin: 'center',
            mixBlendMode: 'multiply',
            opacity: 0.28,
          }}
        />
      )}
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

const ControlRodsOverlay: React.FC<{
  layer: AiLayer;
  frame: number;
  fps: number;
  canvasW: number;
  canvasH: number;
  layerMap: Record<string, Layer>;
}> = ({layer, frame, fps, canvasW, canvasH, layerMap}) => {
  if (!layer.cutout || !layer.controlRod) return null;
  const anchors: Array<[number, number]> = layer.rodAnchors && layer.rodAnchors.length > 0
    ? layer.rodAnchors
    : layer.rodAnchor && layer.rodAnchor.length === 2
      ? [layer.rodAnchor]
      : [[0.55, 0.46]];

  const chain: Layer[] = [layer];
  const visited = new Set<string>([layer.id]);
  let cur: Layer = layer;
  while (cur.parent && layerMap[cur.parent] && !visited.has(cur.parent)) {
    visited.add(cur.parent);
    cur = layerMap[cur.parent];
    chain.push(cur);
  }

  let combinedOpacity = 1;
  const chainStates = chain.map((item) => {
    const ts = evalLayerTransform(item, frame, fps, layerMap);
    combinedOpacity *= ts.opacity;
    const r = item.rect ?? [0, 0, canvasW, canvasH];
    const piv = item.pivot ?? [r[0] + r[2] / 2, r[1] + r[3] / 2];
    return {ts, piv};
  });
  if (combinedOpacity <= 0.002) return null;

  const [rx, ry, rw, rh] = layer.rect;
  const stageBottomY = layer.clipRect && layer.clipRect.length === 4 ? layer.clipRect[1] + layer.clipRect[3] : canvasH;

  const rods = anchors.map((anc, aIdx) => {
    let wx = rx + rw * (anc[0] ?? 0.55);
    let wy = ry + rh * (anc[1] ?? 0.46);
    for (const {ts, piv} of chainStates) {
      const dx = wx - piv[0];
      const dy = wy - piv[1];
      const rad = (ts.rotate * Math.PI) / 180;
      const ca = Math.cos(rad);
      const sa = Math.sin(rad);
      const sx = ts.flipX ? -ts.scale : ts.scale;
      const sy = ts.scale;
      const sdx = sx * dx;
      const sdy = sy * dy;
      wx = piv[0] + ts.x + (sdx * ca - sdy * sa);
      wy = piv[1] + ts.y + (sdx * sa + sdy * ca);
    }
    const slant = (layer.parent ? -6 : -10) + aIdx * 4;
    const handX = wx + slant;
    const handY = Math.max(wy + 40, stageBottomY);
    const rodW = !layer.parent && aIdx === 0 ? 3.8 : 2.8;
    return {wx, wy, handX, handY, rodW};
  });

  const svgNode = (
    <svg
      width={canvasW}
      height={canvasH}
      viewBox={`0 0 ${canvasW} ${canvasH}`}
      style={{position: 'absolute', left: 0, top: 0, pointerEvents: 'none', opacity: combinedOpacity}}
    >
      {rods.map((r, i) => (
        <g key={i}>
          <line x1={r.wx} y1={r.wy} x2={r.handX} y2={r.handY} stroke="rgba(42, 19, 6, 0.62)" strokeWidth={r.rodW} strokeLinecap="round" />
          <line x1={r.wx - 0.9} y1={r.wy + 3} x2={r.handX - 0.9} y2={r.handY} stroke="rgba(168, 112, 44, 0.48)" strokeWidth={1.2} strokeLinecap="round" />
          <circle cx={r.wx} cy={r.wy} r={2.2} fill="rgba(34, 14, 3, 0.85)" />
          <circle cx={r.wx} cy={r.wy} r={4.0} fill="none" stroke="rgba(196, 140, 50, 0.78)" strokeWidth={1.6} />
        </g>
      ))}
    </svg>
  );

  if (layer.clipRect && layer.clipRect.length === 4) {
    const cr = layer.clipRect;
    return (
      <div style={{position: 'absolute', left: cr[0], top: cr[1], width: cr[2], height: cr[3], overflow: 'hidden', pointerEvents: 'none'}}>
        <div style={{position: 'absolute', left: -cr[0], top: -cr[1], width: canvasW, height: canvasH}}>
          {svgNode}
        </div>
      </div>
    );
  }
  return svgNode;
};

const VideoLayerComp: React.FC<{layer: VideoLayer; src: string}> = ({layer, src}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps} = useVideoConfig();
  const {rect, motion} = layer;
  const zoom = motion?.zoom ?? [1, 1];
  const scale = interpolate(frame, [0, durationInFrames - 1], [zoom[0], zoom[1]]);
  const plate = layer.plate !== false;
  const trim = layer.trim;
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

  const renderBar = () => {
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

  if (layer.draw === 'bar') {
    return renderBar();
  }

  return renderBar();
};

export const Shot: React.FC<{
  spec: ShotSpec;
  prepared: Record<string, string>;
  preparedVideos?: Record<string, string>;
  preparedPoses?: Record<string, Record<string, string>>;
}> = ({spec, prepared, preparedVideos, preparedPoses}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const layers = [...spec.layers].sort((a, b) => a.z - b.z);
  const layerMap: Record<string, Layer> = {};
  for (const l of spec.layers) {
    layerMap[l.id] = l;
  }

  const isVerticalVibe = spec.canvas.w === 1080;
  const vibe = isVerticalVibe && (spec as {vibe?: boolean}).vibe !== false;
  const bgColor = (spec.canvas as any).bg || (isVerticalVibe ? '#06080F' : '#fff');

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
        {vibe && (
          <>
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
            <FloatingParticles count={36} />
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
          let resolvedSrc = prepared[layer.id];
          if (layer.type === 'ai' && layer.poses && layer.poses.length > 0) {
            let chosenAsset = layer.asset;
            let bestF = -1;
            for (const p of layer.poses) {
              if (frame >= p.frame && p.frame >= bestF) {
                bestF = p.frame;
                chosenAsset = p.asset;
              }
            }
            if (chosenAsset && preparedPoses?.[layer.id]?.[chosenAsset]) {
              resolvedSrc = preparedPoses[layer.id][chosenAsset];
            } else if (chosenAsset && prepared[chosenAsset]) {
              resolvedSrc = prepared[chosenAsset];
            }
          }
          let combinedDepth = 0;
          if (layer.type === 'ai') {
            const seen = new Set<string>([layer.id]);
            let cur: Layer | undefined = layer;
            while (cur) {
              combinedDepth = Math.max(combinedDepth, evalBaseAnim(cur, frame).depth);
              cur = cur.parent && !seen.has(cur.parent) ? (seen.add(cur.parent), layerMap[cur.parent]) : undefined;
            }
          }
          return (
            <React.Fragment key={layer.id}>
              <LayerNode layer={layer} frame={frame} fps={fps} layerMap={layerMap}>
                {layer.type === 'video' ? (
                  <VideoLayerComp layer={layer} src={preparedVideos?.[layer.id] ?? ''} />
                ) : layer.type === 'ai' || (layer.type === 'code' && (layer.draw === 'grid' || layer.draw === 'dots')) ? (
                  <PreparedLayer layer={layer} src={resolvedSrc} depth={combinedDepth} isVerticalVibe={isVerticalVibe} />
                ) : layer.type === 'code' ? (
                <CodeLayerComp layer={layer} />
              ) : layer.type === 'text' ? (
                <TextComp layer={layer} />
              ) : layer.type === 'hud' ? (
                <HudComp layer={layer} />
              ) : layer.type === 'card' ? (
                <CardComp layer={layer} />
              ) : layer.type === 'component' ? (
                (() => {
                  const Comp = CUSTOM_COMPONENTS[layer.component];
                  if (Comp) {
                    return <Comp layer={layer} rect={layer.rect} props={layer.props} prepared={prepared} />;
                  }
                  return (
                    <div
                      style={{
                        position: 'absolute',
                        left: layer.rect[0],
                        top: layer.rect[1],
                        width: layer.rect[2],
                        height: layer.rect[3],
                        backgroundColor: 'rgba(255, 215, 79, 0.2)',
                        border: '1px dashed #FFD54F',
                        boxSizing: 'border-box',
                      }}
                    />
                  );
                })()
              ) : null}
              </LayerNode>
              {layer.type === 'ai' && layer.cutout && layer.controlRod && (
                <ControlRodsOverlay
                  layer={layer}
                  frame={frame}
                  fps={fps}
                  canvasW={spec.canvas.w}
                  canvasH={spec.canvas.h}
                  layerMap={layerMap}
                />
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
};
