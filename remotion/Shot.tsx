import {Img, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {Bar} from './layers';
import type {AiLayer, CodeLayer, ShotSpec} from './spec';

// One layer = one component. Motion is numbers from the spec, interpolated
// linearly over the shot — the same math the old ffmpeg zoompan/overlay graph did,
// now in plain code. Full-frame code layers (grid/dots) arrive as prepared PNGs
// from S2 (lib/draw.py stays their single implementation); the bar is pure CSS.

const PreparedLayer: React.FC<{
  layer: AiLayer | CodeLayer;
  src: string;
}> = ({layer, src}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const {rect, motion} = layer;
  const zoom = motion?.zoom ?? [1, 1];
  const scale = interpolate(
    frame,
    [0, durationInFrames - 1],
    [zoom[0], zoom[1]]
  );

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width: rect[2],
        height: rect[3],
        overflow: 'hidden',
      }}
    >
      <Img
        src={src}
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          // AI assets carry zoom headroom (S2 scales to zmax*1.04); grid/dots
          // are exact-size, and scale(1) leaves them untouched either way.
          transform: `translate(-50%, -50%) scale(${scale})`,
          transformOrigin: 'center',
          mixBlendMode:
            layer.type === 'ai' && layer.blend === 'multiply'
              ? 'multiply'
              : layer.type === 'ai' && layer.blend === 'screen'
                ? 'screen'
                : 'normal',
        }}
      />
    </div>
  );
};

const CodeLayerComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const {rect, motion, color} = layer;

  if (layer.draw === 'grid' || layer.draw === 'dots') {
    // Rendered from the S2-prepared PNG (see PreparedLayer in Shot).
    return null;
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
  const layers = [...spec.layers].sort((a, b) => a.z - b.z);
  return (
    <div
      style={{
        position: 'relative',
        width: spec.canvas.w,
        height: spec.canvas.h,
        backgroundColor: '#fff',
        overflow: 'hidden',
      }}
    >
      {layers.map((layer) =>
        layer.type === 'ai' || layer.draw === 'grid' || layer.draw === 'dots' ? (
          <PreparedLayer key={layer.id} layer={layer} src={prepared[layer.id]} />
        ) : (
          <CodeLayerComp key={layer.id} layer={layer} />
        )
      )}
    </div>
  );
};
