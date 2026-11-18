import React from 'react';
import {Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {Video} from '@remotion/media';
import type {AiLayer, Layer, VideoLayer} from './spec';
import type {ShotProps} from './index';
import {CUSTOM_COMPONENTS} from './registry';
import {evalLayerTransform} from './kinematics';

const LayerNode: React.FC<{
  layer: Layer;
  frame: number;
  fps: number;
  layerMap: Record<string, Layer>;
  children: React.ReactNode;
}> = ({layer, frame, fps, layerMap, children}) => {
  // Transforms use canvas coordinates, including project component children.
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
    const r = item.rect;
    const piv = item.pivot ?? [r[0] + r[2] / 2, r[1] + r[3] / 2];
    const effFlipX = ts.flipX;
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

const MediaLayer: React.FC<{layer: AiLayer | VideoLayer; src: string}> = ({layer, src}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps} = useVideoConfig();
  // motion.zoom is a live capability: the contract accepts it for prepared
  // media (core/spec/layers.py) and the renderer interpolates it below.
  // motion.pan is NOT: the contract removed it and refuses it with
  // "migration required: motion.pan removed; use anim.x". The renderer
  // must not apply it either — an implicit render of a removed word is a
  // contract hole. The sanctioned channel is anim.x, which the layer
  // transform chain already applies (LayerNode -> evalLayerTransform).
  const zoom = layer.motion?.zoom ?? [1, 1];
  const end = Math.max(1, durationInFrames - 1);
  const scale = interpolate(frame, [0, end], zoom);
  const style: React.CSSProperties = {
    position: 'absolute', width: '100%', height: '100%',
    objectFit: layer.fit ?? 'cover',
    transform: `scale(${scale})`,
    transformOrigin: 'center',
  };
  return <div style={{position: 'absolute', left: layer.rect[0], top: layer.rect[1],
    width: layer.rect[2], height: layer.rect[3], overflow: 'hidden',
    mixBlendMode: layer.type !== 'video' ? layer.blend : undefined}}>
    {layer.type === 'video' ? <Video src={staticFile(src)}
      trimBefore={layer.trim ? Math.round(layer.trim[0] * fps) : undefined}
      trimAfter={layer.trim ? Math.round(layer.trim[1] * fps) : undefined}
      loop={layer.loop ?? true} muted={layer.muted ?? true}
      playbackRate={layer.playbackRate ?? 1} style={style} />
      : <Img src={src} style={style} />}
  </div>;
};

export const Shot: React.FC<ShotProps> = ({spec, prepared, preparedVideos = {}, preparedPoses = {}}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const layers = [...spec.layers].sort((a, b) => a.z - b.z);
  const layerMap = Object.fromEntries(layers.map(layer => [layer.id, layer]));
  return <div style={{position: 'relative', width: spec.canvas.w, height: spec.canvas.h,
    overflow: 'hidden', backgroundColor: spec.canvas.bg}}>
    {layers.map(layer => {
      let content: React.ReactNode;
      if (layer.type === 'component') {
        const Comp = Object.prototype.hasOwnProperty.call(CUSTOM_COMPONENTS, layer.component)
          ? CUSTOM_COMPONENTS[layer.component] : undefined;
        if (!Comp) throw new Error(`Unregistered project component: ${layer.component} (layer ${layer.id})`);
        // No rect-offset wrapper: components position themselves in canvas coordinates.
        content = <Comp layer={layer} rect={layer.rect} props={layer.props}
          prepared={prepared} preparedVideos={preparedVideos} tracks={spec.tracks ?? {}}
          frame={frame} fps={fps} durationInFrames={durationInFrames} />;
      } else if (layer.type === 'ai' || layer.type === 'image' || layer.type === 'video') {
        let src = layer.type === 'video' ? preparedVideos[layer.id] : prepared[layer.id];
        if (layer.type !== 'video') {
          let pose: string | undefined;
          let bestFrame = -Infinity;
          for (const p of layer.poses ?? []) {
            if (p.frame <= frame && p.frame >= bestFrame) {
              pose = p.asset;
              bestFrame = p.frame;
            }
          }
          if (pose !== undefined) {
            src = preparedPoses[layer.id]?.[pose] ?? (pose === layer.asset ? src : undefined);
          }
        }
        if (!src) throw new Error(`Missing prepared media for layer ${layer.id} at frame ${frame}`);
        content = <MediaLayer layer={layer} src={src} />;
      } else {
        throw new Error(`Unsupported layer type: ${(layer as Layer).type}`);
      }
      return <LayerNode key={layer.id} layer={layer} frame={frame} fps={fps} layerMap={layerMap}>
        {content}
      </LayerNode>;
    })}
  </div>;
};
