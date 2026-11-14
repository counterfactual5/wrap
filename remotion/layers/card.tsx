import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {CardLayer} from '../spec';

export const CardComp: React.FC<{layer: CardLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const {rect, cardType, title, formula, quote, author, details} = layer;

  const spr = spring({
    frame: Math.max(0, frame - 8),
    fps,
    config: {damping: 14, mass: 0.8},
  });

  if (cardType === 'formula') {
    return (
      <div
        style={{
          position: 'absolute',
          left: rect[0],
          top: rect[1],
          width: rect[2],
          backgroundColor: 'rgba(10, 16, 30, 0.92)',
          border: '1px solid rgba(0, 240, 255, 0.32)',
          borderRadius: 18,
          padding: '24px 28px',
          boxShadow: '0 20px 50px rgba(0,0,0,0.8), 0 0 30px rgba(0, 240, 255, 0.08)',
          transform: `translateY(${(1 - spr) * 20}px)`,
          opacity: spr,
          boxSizing: 'border-box',
        }}
      >
        {title && (
          <div
            style={{
              fontSize: 14,
              color: '#00F0FF',
              fontFamily: 'monospace',
              letterSpacing: '0.12em',
              marginBottom: 14,
            }}
          >
            ● {title}
          </div>
        )}
        {formula && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 44,
              fontWeight: 700,
              fontFamily: 'Georgia, serif',
              color: '#FFFFFF',
              margin: '10px 0 20px 0',
              textShadow: '0 0 25px rgba(0, 240, 255, 0.5)',
            }}
          >
            {formula}
          </div>
        )}
        {details && details.length > 0 && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: `repeat(${details.length}, 1fr)`,
              gap: 16,
              borderTop: '1px solid rgba(255, 255, 255, 0.08)',
              paddingTop: 16,
            }}
          >
            {details.map((item, idx) => (
              <div
                key={idx}
                style={{
                  backgroundColor: 'rgba(0, 240, 255, 0.06)',
                  border: '1px solid rgba(0, 240, 255, 0.15)',
                  padding: '12px 16px',
                  borderRadius: 10,
                }}
              >
                <div style={{color: item.color || '#00F0FF', fontWeight: 600, fontSize: 16, marginBottom: 4}}>
                  {item.label}
                </div>
                <div style={{color: '#8BA1C1', fontSize: 13, lineHeight: 1.4}}>{item.desc}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (cardType === 'quote') {
    return (
      <div
        style={{
          position: 'absolute',
          left: rect[0],
          top: rect[1],
          width: rect[2],
          backgroundColor: 'rgba(12, 18, 34, 0.95)',
          borderLeft: '4px solid #00F0FF',
          borderRight: '1px solid rgba(0, 240, 255, 0.2)',
          borderTop: '1px solid rgba(0, 240, 255, 0.2)',
          borderBottom: '1px solid rgba(0, 240, 255, 0.2)',
          borderRadius: '0 18px 18px 0',
          padding: '24px 28px',
          boxShadow: '0 20px 50px rgba(0, 0, 0, 0.8), 0 0 30px rgba(0, 240, 255, 0.06)',
          transform: `translateY(${(1 - spr) * 20}px)`,
          opacity: spr,
          boxSizing: 'border-box',
        }}
      >
        <div
          style={{
            fontSize: 26,
            fontWeight: 700,
            lineHeight: 1.5,
            color: '#FFFFFF',
            marginBottom: 12,
            textShadow: '0 2px 10px rgba(0,0,0,0.5)',
          }}
        >
          “{quote}”
        </div>
        {author && (
          <div style={{fontSize: 16, color: '#8BA1C1', fontStyle: 'italic', fontFamily: 'serif'}}>
            — {author}
          </div>
        )}
      </div>
    );
  }

  if (cardType === 'capsule') {
    return (
      <div
        style={{
          position: 'absolute',
          left: rect[0],
          top: rect[1],
          width: rect[2],
          height: rect[3],
          backgroundColor: 'rgba(10, 16, 32, 0.88)',
          border: '1px solid rgba(0, 240, 255, 0.35)',
          borderRadius: 24,
          padding: '20px 30px 16px 30px',
          boxShadow: '0 15px 45px rgba(0,0,0,0.75), 0 0 30px rgba(0, 240, 255, 0.12)',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'flex-start',
          gap: 8,
          boxSizing: 'border-box',
          transform: `translateY(${(1 - spr) * 16}px)`,
          opacity: spr,
        }}
      >
        {title && (
          <div
            style={{
              fontSize: 15,
              fontFamily: 'monospace',
              letterSpacing: '0.12em',
              color: '#00F0FF',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              textTransform: 'uppercase',
              flexShrink: 0,
            }}
          >
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: '50%',
                backgroundColor: '#00F0FF',
                boxShadow: '0 0 10px #00F0FF',
              }}
            />
            {title}
          </div>
        )}
        <div
          style={{
            fontSize: 26,
            fontWeight: 600,
            lineHeight: 1.4,
            color: '#FFFFFF',
            letterSpacing: '0.02em',
            textShadow: '0 2px 10px rgba(0,0,0,0.6)',
          }}
        >
          {quote || layer.text || (details && details[0]?.desc)}
        </div>
      </div>
    );
  }

  return null;
};

