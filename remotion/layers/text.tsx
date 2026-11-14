import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {TextLayer} from '../spec';

export const TextComp: React.FC<{layer: TextLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const {rect, text, subtext, fontSize = 54, fontWeight = 800, enter = 'spring'} = layer;

  const spr = spring({
    frame,
    fps,
    config: {damping: 14, mass: 0.8},
  });

  const translateY = enter === 'spring' ? (1 - spr) * 24 : 0;
  const opacity = enter === 'spring' ? spr : 1;

  // Evaluate flipX for content-centered mirroring when no explicit pivot is set on the text layer
  let flipVal = layer.flipX ? 1 : 0;
  const flipKfs = layer.anim?.flipX;
  if (flipKfs && flipKfs.length > 0) {
    const first = flipKfs[0];
    const last = flipKfs[flipKfs.length - 1];
    if (frame <= first[0]) {
      flipVal = first[1];
    } else if (frame >= last[0]) {
      flipVal = last[1];
    } else {
      for (let i = 0; i < flipKfs.length - 1; i++) {
        const k0 = flipKfs[i];
        const k1 = flipKfs[i + 1];
        if (frame >= k0[0] && frame <= k1[0]) {
          const span = Math.max(1e-6, k1[0] - k0[0]);
          const t = (frame - k0[0]) / span;
          flipVal = k1[2] === 'step' ? (t < 1 ? k0[1] : k1[1]) : k0[1] + (k1[1] - k0[1]) * t;
          break;
        }
      }
    }
  }
  const contentFlipX = !layer.pivot && flipVal >= 0.5;

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width: rect[2],
        height: rect[3],
        transform: `translateY(${translateY}px)`,
        opacity,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          width: 'fit-content',
          maxWidth: '100%',
          transform: contentFlipX ? 'scaleX(-1)' : undefined,
          transformOrigin: 'center center',
        }}
      >
        <div
          style={
            layer.color
              ? {
                  fontSize,
                  fontWeight,
                  lineHeight: 1.25,
                  letterSpacing: '-0.02em',
                  color: layer.color,
                  textShadow: '0 2px 12px rgba(0, 0, 0, 0.75)',
                  whiteSpace: 'pre-line',
                }
              : {
                  fontSize,
                  fontWeight,
                  lineHeight: 1.25,
                  letterSpacing: '-0.02em',
                  background: 'linear-gradient(180deg, #FFFFFF 25%, #A5ECFF 100%)',
                  WebkitBackgroundClip: 'text',
                  WebkitTextFillColor: 'transparent',
                  // Dark scrim shadow first (legibility over any background), cyan glow second (style).
                  filter:
                    'drop-shadow(0 2px 3px rgba(0, 0, 0, 0.9)) drop-shadow(0 2px 14px rgba(0, 240, 255, 0.35))',
                  whiteSpace: 'pre-line',
                }
          }
        >
          {text}
        </div>
        {subtext && (
          <div
            style={{
              fontSize: Math.round(fontSize * 0.42),
              color: '#8BA1C1',
              fontFamily: 'monospace',
              marginTop: 10,
              letterSpacing: '0.06em',
            }}
          >
            {subtext}
          </div>
        )}
      </div>
    </div>
  );
};

