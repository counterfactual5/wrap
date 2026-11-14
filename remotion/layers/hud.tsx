import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {HudLayer} from '../spec';

export const HudComp: React.FC<{layer: HudLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps} = useVideoConfig();
  const {rect, hudType, text, color = '#00F0FF'} = layer;

  if (hudType === 'badge') {
    return (
      <div
        style={{
          position: 'absolute',
          left: rect[0],
          top: rect[1],
          display: 'inline-flex',
          alignItems: 'center',
          gap: 10,
          backgroundColor: 'rgba(0, 240, 255, 0.1)',
          border: `1px solid ${color}66`,
          borderRadius: 8,
          padding: '6px 16px',
          fontSize: 15,
          letterSpacing: '0.12em',
          color,
          fontFamily: 'monospace',
          boxShadow: '0 0 20px rgba(0, 240, 255, 0.15)',
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: '50%',
            backgroundColor: color,
            boxShadow: `0 0 10px ${color}`,
          }}
        />
        {text}
      </div>
    );
  }

  if (hudType === 'telemetry') {
    return (
      <div
        style={{
          position: 'absolute',
          left: rect[0],
          top: rect[1],
          color: 'rgba(0, 240, 255, 0.55)',
          fontSize: 13,
          fontFamily: 'monospace',
          letterSpacing: '0.06em',
        }}
      >
        {text}
      </div>
    );
  }

  if (hudType === 'equalizer') {
    const barsCount = 48;
    return (
      <div
        style={{
          position: 'absolute',
          left: rect[0],
          top: rect[1],
          width: rect[2],
          display: 'flex',
          alignItems: 'flex-end',
          gap: 6,
          height: rect[3],
        }}
      >
        {Array.from({length: barsCount}).map((_, i) => {
          const h = 8 + Math.abs(Math.sin((frame + i * 5) * 0.25)) * (rect[3] - 10);
          return (
            <div
              key={i}
              style={{
                width: 8,
                height: h,
                backgroundColor: i % 2 === 0 ? color : '#FFB800',
                borderRadius: 2,
                boxShadow: `0 0 8px ${i % 2 === 0 ? color : '#FFB800'}66`,
              }}
            />
          );
        })}
        <div style={{marginLeft: 'auto', color: '#00F0FF', fontSize: 13, fontFamily: 'monospace'}}>
          FRAME {String(frame).padStart(3, '0')} / {durationInFrames} [{(frame / fps).toFixed(2)}s]
        </div>
      </div>
    );
  }

  if (hudType === 'progress') {
    const progress = (frame / (durationInFrames - 1)) * 100;
    return (
      <div
        style={{
          position: 'absolute',
          left: rect[0],
          top: rect[1],
          width: rect[2],
          height: rect[3] || 6,
          backgroundColor: 'rgba(255, 255, 255, 0.08)',
          borderRadius: 3,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${progress}%`,
            height: '100%',
            background: `linear-gradient(90deg, ${color}, #FFB800)`,
            boxShadow: `0 0 12px ${color}`,
          }}
        />
      </div>
    );
  }

  return null;
};

