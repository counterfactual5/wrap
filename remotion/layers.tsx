import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {CardLayer, CodeLayer, HudLayer, TextLayer} from './spec';

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
  );
};

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

export const GeodesicComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const progress = interpolate(frame, [10, durationInFrames - 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const pathD = 'M 80,110 C 320,110 420,370 500,370 C 580,370 680,150 920,150';
  const pathLength = 1100;
  const strokeDashoffset = pathLength * (1 - progress);

  return (
    <div style={{position: 'absolute', left: layer.rect[0], top: layer.rect[1], width: layer.rect[2], height: layer.rect[3], pointerEvents: 'none'}}>
      <svg style={{width: '100%', height: '100%'}} viewBox="0 0 1000 680">
        <path d={pathD} fill="none" stroke="rgba(0, 240, 255, 0.2)" strokeWidth="4" />
        <path
          d={pathD}
          fill="none"
          stroke={layer.color || '#00F0FF'}
          strokeWidth="4"
          strokeDasharray={pathLength}
          strokeDashoffset={strokeDashoffset}
          filter="drop-shadow(0 0 10px #00F0FF)"
        />
        {/* Sun at center of gravity well */}
        <circle cx="500" cy="260" r="14" fill="none" stroke="#FFB800" strokeWidth="2" strokeDasharray="3 3" />
        <circle cx="500" cy="260" r="5" fill="#FFB800" />
      </svg>
    </div>
  );
};

export const RipplesComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const p1 = (frame * 2.5) % 100;
  const p2 = (frame * 2.5 + 50) % 100;

  return (
    <div style={{position: 'absolute', left: layer.rect[0], top: layer.rect[1], width: layer.rect[2], height: layer.rect[3], pointerEvents: 'none'}}>
      <svg style={{width: '100%', height: '100%'}} viewBox="0 0 1000 680">
        <ellipse
          cx="500"
          cy="260"
          rx={80 + p1 * 3.5}
          ry={40 + p1 * 1.5}
          fill="none"
          stroke={layer.color || '#00F0FF'}
          strokeWidth="1.5"
          strokeDasharray="4 6"
          opacity={(1 - p1 / 100) * 0.6}
        />
        <ellipse
          cx="500"
          cy="260"
          rx={80 + p2 * 3.5}
          ry={40 + p2 * 1.5}
          fill="none"
          stroke="#FFB800"
          strokeWidth="1.5"
          strokeDasharray="4 6"
          opacity={(1 - p2 / 100) * 0.5}
        />
      </svg>
    </div>
  );
};

export const TrampolineComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {rect} = layer;
  const width = rect[2];
  const height = rect[3];

  const cx = 500;
  const cy = 520;
  const pitch = 0.88;
  const cosPitch = Math.cos(pitch);
  const sinPitch = Math.sin(pitch);
  const yaw = -0.25;
  const cosYaw = Math.cos(yaw);
  const sinYaw = Math.sin(yaw);

  const wellDepth = 240 + Math.sin(frame * 0.06) * 15;
  const wellSigma = 2.8;

  const project = (u: number, v: number) => {
    const r = Math.sqrt(u * u + v * v);
    const z = -wellDepth / (1 + Math.pow(r / wellSigma, 2));
    const xr = u * cosYaw - v * sinYaw;
    const yr = u * sinYaw + v * cosYaw;
    const px = cx + xr * 44;
    const py = cy + yr * 22 * cosPitch - z * sinPitch;
    return {px, py, z};
  };

  const gridRange = [-10, -9, -8, -7, -6, -5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  const uLines: string[] = [];
  const vLines: string[] = [];

  for (const v of gridRange) {
    let d = '';
    for (let i = 0; i < gridRange.length; i++) {
      const u = gridRange[i];
      const {px, py} = project(u, v);
      d += i === 0 ? `M ${px.toFixed(1)},${py.toFixed(1)}` : ` L ${px.toFixed(1)},${py.toFixed(1)}`;
    }
    uLines.push(d);
  }

  for (const u of gridRange) {
    let d = '';
    for (let i = 0; i < gridRange.length; i++) {
      const v = gridRange[i];
      const {px, py} = project(u, v);
      d += i === 0 ? `M ${px.toFixed(1)},${py.toFixed(1)}` : ` L ${px.toFixed(1)},${py.toFixed(1)}`;
    }
    vLines.push(d);
  }

  const centerMassPos = project(0, 0);

  const p1Progress = (frame * 0.007) % 1.0;
  const p1Radius = 9.0 * (1 - p1Progress * 0.78);
  const p1Angle = p1Progress * Math.PI * 4.5 + 0.5;
  const p1U = p1Radius * Math.cos(p1Angle);
  const p1V = p1Radius * Math.sin(p1Angle);
  const p1Pos = project(p1U, p1V);

  const p1TailPoints: Array<{px: number; py: number}> = [];
  for (let step = 0; step < 18; step++) {
    const histProgress = Math.max(0, p1Progress - step * 0.002);
    const hr = 9.0 * (1 - histProgress * 0.78);
    const ha = histProgress * Math.PI * 4.5 + 0.5;
    p1TailPoints.push(project(hr * Math.cos(ha), hr * Math.sin(ha)));
  }
  const p1TailPath = p1TailPoints
    .map((pt, idx) => (idx === 0 ? `M ${pt.px.toFixed(1)},${pt.py.toFixed(1)}` : `L ${pt.px.toFixed(1)},${pt.py.toFixed(1)}`))
    .join(' ');

  const p2Progress = (frame * 0.007 + 0.5) % 1.0;
  const p2Radius = 8.5 * (1 - p2Progress * 0.75);
  const p2Angle = p2Progress * Math.PI * 4.2 + Math.PI + 0.2;
  const p2U = p2Radius * Math.cos(p2Angle);
  const p2V = p2Radius * Math.sin(p2Angle);
  const p2Pos = project(p2U, p2V);

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width: rect[2],
        height: rect[3],
        overflow: 'hidden',
        pointerEvents: 'none',
        borderRadius: 24,
        border: '1px solid rgba(0, 240, 255, 0.25)',
        backgroundColor: '#040711',
        boxShadow: '0 25px 70px rgba(0,0,0,0.85), inset 0 0 80px rgba(0, 240, 255, 0.05)',
      }}
    >
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <defs>
          <radialGradient id="sunGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#FFF4B8" stopOpacity="1" />
            <stop offset="35%" stopColor="#FFB800" stopOpacity="0.95" />
            <stop offset="70%" stopColor="#FF6B00" stopOpacity="0.75" />
            <stop offset="100%" stopColor="#FF2A00" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="wellAtmosphere" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#00F0FF" stopOpacity="0.18" />
            <stop offset="60%" stopColor="#0A1C38" stopOpacity="0.08" />
            <stop offset="100%" stopColor="#040711" stopOpacity="0" />
          </radialGradient>
          <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="8" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        <circle cx={centerMassPos.px} cy={centerMassPos.py} r="280" fill="url(#wellAtmosphere)" />

        <g stroke="rgba(0, 240, 255, 0.3)" strokeWidth="1.2" fill="none">
          {uLines.map((d, i) => (
            <path key={`u-${i}`} d={d} />
          ))}
          {vLines.map((d, i) => (
            <path key={`v-${i}`} d={d} />
          ))}
        </g>

        {[2.0, 4.0, 6.5].map((cr, idx) => {
          const ringPoints: Array<{px: number; py: number}> = [];
          for (let deg = 0; deg <= 360; deg += 10) {
            const rad = (deg * Math.PI) / 180;
            ringPoints.push(project(cr * Math.cos(rad), cr * Math.sin(rad)));
          }
          const ringPath = ringPoints
            .map((pt, i) => (i === 0 ? `M ${pt.px.toFixed(1)},${pt.py.toFixed(1)}` : `L ${pt.px.toFixed(1)},${pt.py.toFixed(1)}`))
            .join(' ');
          return (
            <path
              key={`ring-${idx}`}
              d={ringPath}
              fill="none"
              stroke="#00F0FF"
              strokeWidth="1.5"
              strokeDasharray="4 6"
              opacity={0.5 - idx * 0.12}
            />
          );
        })}

        <g transform={`translate(${centerMassPos.px}, ${centerMassPos.py})`}>
          <circle
            r={50 + ((frame * 1.5) % 80)}
            fill="none"
            stroke="#FFB800"
            strokeWidth="1.5"
            strokeDasharray="3 5"
            opacity={Math.max(0, 1 - ((frame * 1.5) % 80) / 80) * 0.6}
          />
          <circle r="60" fill="url(#sunGlow)" />
          <circle r="36" fill="#FFB800" filter="url(#glow)" />
          <circle r="36" fill="url(#sunGlow)" />
          <circle cx="-10" cy="-10" r="10" fill="#FFFFFF" opacity="0.6" />
          <text
            x="0"
            y="-48"
            fill="#FFD23F"
            fontSize="14"
            fontFamily="monospace"
            fontWeight="bold"
            letterSpacing="0.1em"
            textAnchor="middle"
          >
            ● 大质量天体 MASS (M)
          </text>
          <text
            x="0"
            y="56"
            fill="#8BA1C1"
            fontSize="12"
            fontFamily="monospace"
            textAnchor="middle"
          >
            时空下陷凹陷 (CURVATURE WELL)
          </text>
        </g>

        <path d={p1TailPath} fill="none" stroke="#00F0FF" strokeWidth="2.5" opacity="0.7" strokeDasharray="3 3" />
        <g transform={`translate(${p1Pos.px}, ${p1Pos.py})`}>
          <circle r="8" fill="#00F0FF" filter="url(#glow)" />
          <circle r="4" fill="#FFFFFF" />
          <text
            x="14"
            y="4"
            fill="#00F0FF"
            fontSize="13"
            fontFamily="monospace"
            fontWeight="bold"
          >
            惯性测地线滑落 // GEODESIC
          </text>
        </g>

        <g transform={`translate(${p2Pos.px}, ${p2Pos.py})`}>
          <circle r="7" fill="#FFB800" filter="url(#glow)" />
          <circle r="3.5" fill="#FFFFFF" />
          <text
            x="12"
            y="4"
            fill="#FFB800"
            fontSize="12"
            fontFamily="monospace"
          >
            自由落体 // FREE-FALL
          </text>
        </g>

        <g stroke="rgba(0, 240, 255, 0.4)" strokeWidth="1.5">
          <path d="M 30,50 L 30,30 L 50,30" fill="none" />
          <path d={`M ${width - 30},50 L ${width - 30},30 L ${width - 50},30`} fill="none" />
          <path d={`M 30,${height - 50} L 30,${height - 30} L 50,${height - 30}`} fill="none" />
          <path d={`M ${width - 30},${height - 50} L ${width - 30},${height - 30} L ${width - 50},${height - 30}`} fill="none" />
        </g>

        <text x="50" y="55" fill="rgba(0, 240, 255, 0.7)" fontSize="13" fontFamily="monospace" letterSpacing="0.1em">
          MODEL: 3D ELASTIC SPACETIME FABRIC // TENSIONAL SIMULATION
        </text>

        <g transform={`translate(50, ${height - 65})`}>
          <rect width="420" height="36" rx="8" fill="rgba(255, 80, 80, 0.12)" stroke="rgba(255, 80, 80, 0.4)" strokeWidth="1" />
          <text x="16" y="23" fill="#FF8080" fontSize="13" fontFamily="monospace">
            ❌ 牛顿视角: 太阳伸出无形之手拉扯地球 (超距力)
          </text>

          <rect x="440" width="450" height="36" rx="8" fill="rgba(0, 240, 255, 0.12)" stroke="rgba(0, 240, 255, 0.4)" strokeWidth="1" />
          <text x="456" y="23" fill="#00F0FF" fontSize="13" fontFamily="monospace">
            ✔ 爱因斯坦: 时空弯曲，物体只是在走测地线
          </text>
        </g>
      </svg>
    </div>
  );
};

export const GravityWellComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {rect} = layer;
  const width = rect[2];
  const height = rect[3];

  const cx = 500;

  const rings = [
    {rx: 440, ry: 200, y: 270, stroke: 'rgba(0, 240, 255, 0.22)', dash: '6 8'},
    {rx: 370, ry: 165, y: 350, stroke: 'rgba(0, 240, 255, 0.35)', dash: '5 6'},
    {rx: 290, ry: 130, y: 440, stroke: 'rgba(0, 240, 255, 0.50)', dash: '4 4'},
    {rx: 210, ry: 95, y: 540, stroke: 'rgba(0, 240, 255, 0.65)', dash: '3 4'},
    {rx: 135, ry: 60, y: 650, stroke: 'rgba(0, 240, 255, 0.80)', dash: '2 3'},
    {rx: 75, ry: 34, y: 760, stroke: '#FFB800', dash: 'none'},
  ];

  const ribCount = 16;
  const ribs: string[] = [];
  for (let i = 0; i < ribCount; i++) {
    const angle = (i * 2 * Math.PI) / ribCount;
    const topX = cx + rings[0].rx * Math.cos(angle);
    const topY = rings[0].y + rings[0].ry * Math.sin(angle);
    const midX = cx + rings[3].rx * Math.cos(angle);
    const midY = rings[3].y + rings[3].ry * Math.sin(angle);
    const botX = cx + rings[5].rx * Math.cos(angle);
    const botY = rings[5].y + rings[5].ry * Math.sin(angle);
    const d = `M ${topX.toFixed(1)},${topY.toFixed(1)} Q ${midX.toFixed(1)},${midY.toFixed(1)} ${botX.toFixed(1)},${botY.toFixed(1)}`;
    ribs.push(d);
  }

  const orbitAngle = ((frame * 1.3) * Math.PI) / 180;
  const orbitRx = 300;
  const orbitRy = 135;
  const orbitY = 430;

  const earthX = cx + orbitRx * Math.cos(orbitAngle);
  const earthY = orbitY + orbitRy * Math.sin(orbitAngle);
  const vScale = 0.22;
  const vx = -orbitRx * Math.sin(orbitAngle) * vScale;
  const vy = orbitRy * Math.cos(orbitAngle) * vScale;

  const tailPoints: Array<{x: number; y: number}> = [];
  for (let t = 0; t < 36; t++) {
    const a = (((frame - t) * 1.3) * Math.PI) / 180;
    tailPoints.push({
      x: cx + orbitRx * Math.cos(a),
      y: orbitY + orbitRy * Math.sin(a),
    });
  }
  const tailPath = tailPoints
    .map((pt, idx) => (idx === 0 ? `M ${pt.x.toFixed(1)},${pt.y.toFixed(1)}` : `L ${pt.x.toFixed(1)},${pt.y.toFixed(1)}`))
    .join(' ');

  const gNormScale = 0.16;
  const gx = (cx - earthX) * gNormScale;
  const gy = (760 - earthY) * gNormScale;

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width: rect[2],
        height: rect[3],
        overflow: 'hidden',
        pointerEvents: 'none',
        borderRadius: 24,
        border: '1px solid rgba(0, 240, 255, 0.25)',
        backgroundColor: '#040711',
        boxShadow: '0 25px 70px rgba(0,0,0,0.85), inset 0 0 80px rgba(0, 240, 255, 0.05)',
      }}
    >
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <defs>
          <radialGradient id="sunWellGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#FFF2A3" stopOpacity="1" />
            <stop offset="30%" stopColor="#FFB800" stopOpacity="0.95" />
            <stop offset="70%" stopColor="#FF5500" stopOpacity="0.7" />
            <stop offset="100%" stopColor="#FF1100" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="earthGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#E6FAFF" stopOpacity="1" />
            <stop offset="50%" stopColor="#00F0FF" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#0066FF" stopOpacity="0" />
          </radialGradient>
          <filter id="glowF" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        <ellipse cx={cx} cy={760} rx="120" ry="60" fill="rgba(255, 184, 0, 0.12)" filter="url(#glowF)" />

        <g stroke="rgba(0, 240, 255, 0.32)" strokeWidth="1.2" fill="none">
          {ribs.map((d, i) => (
            <path key={`rib-${i}`} d={d} />
          ))}
        </g>

        {rings.map((r, i) => (
          <ellipse
            key={`r-${i}`}
            cx={cx}
            cy={r.y}
            rx={r.rx}
            ry={r.ry}
            fill="none"
            stroke={r.stroke}
            strokeWidth="1.6"
            strokeDasharray={r.dash}
          />
        ))}

        <ellipse
          cx={cx}
          cy={orbitY}
          rx={orbitRx}
          ry={orbitRy}
          fill="none"
          stroke="rgba(0, 240, 255, 0.25)"
          strokeWidth="1.5"
          strokeDasharray="4 6"
        />

        <path d={tailPath} fill="none" stroke="#00F0FF" strokeWidth="3" opacity="0.8" filter="url(#glowF)" />

        <g strokeWidth="2">
          <line
            x1={earthX}
            y1={earthY}
            x2={earthX + vx}
            y2={earthY + vy}
            stroke="#00F0FF"
          />
          <line
            x1={earthX}
            y1={earthY}
            x2={earthX + gx}
            y2={earthY + gy}
            stroke="#FFB800"
            strokeDasharray="3 3"
          />
        </g>

        <g transform={`translate(${earthX.toFixed(1)}, ${earthY.toFixed(1)})`}>
          <circle r="14" fill="url(#earthGlow)" filter="url(#glowF)" />
          <circle r="8" fill="#00F0FF" />
          <circle r="3" fill="#FFFFFF" />
          <text
            x="18"
            y="-8"
            fill="#00F0FF"
            fontSize="14"
            fontFamily="monospace"
            fontWeight="bold"
            filter="url(#glowF)"
          >
            地球 EARTH // 滚珠公转
          </text>
          <text
            x="18"
            y="10"
            fill="#8BA1C1"
            fontSize="12"
            fontFamily="monospace"
          >
            v = 29.8 km/s (惯性测地线)
          </text>
        </g>

        <g transform={`translate(${cx}, 760)`}>
          <circle
            r={30 + Math.sin(frame * 0.08) * 3}
            fill="url(#sunWellGlow)"
            filter="url(#glowF)"
          />
          <circle r="22" fill="#FFB800" />
          <circle r="12" fill="#FFF2A3" />
          <text
            x="0"
            y="48"
            fill="#FFD23F"
            fontSize="14"
            fontFamily="monospace"
            fontWeight="bold"
            textAnchor="middle"
          >
            太阳 (SUN) // 深陷时空漏斗
          </text>
          <text
            x="0"
            y="66"
            fill="#8BA1C1"
            fontSize="11"
            fontFamily="monospace"
            textAnchor="middle"
          >
            POTENTIAL DEPTH: Φ = -GM/r
          </text>
        </g>

        <g stroke="rgba(0, 240, 255, 0.4)" strokeWidth="1.5">
          <path d="M 30,50 L 30,30 L 50,30" fill="none" />
          <path d={`M ${width - 30},50 L ${width - 30},30 L ${width - 50},30`} fill="none" />
        </g>

        <text x="50" y="55" fill="rgba(0, 240, 255, 0.75)" fontSize="13" fontFamily="monospace" letterSpacing="0.1em">
          GRAVITATIONAL FUNNEL & MARBLE ORBIT // 漏斗模型与公转滚珠
        </text>

        <g transform={`translate(50, ${height - 65})`}>
          <rect width="900" height="40" rx="8" fill="rgba(0, 240, 255, 0.08)" stroke="rgba(0, 240, 255, 0.3)" strokeWidth="1" />
          <text x="24" y="25" fill="#FFFFFF" fontSize="14" fontFamily="monospace">
            ● 原理解析：像漏斗中的滚珠，地球无需超距引力拉扯，仅凭自身惯性在弯曲几何中永恒回转
          </text>
        </g>
      </svg>
    </div>
  );
};

export const LightDeflectionComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {rect} = layer;
  const width = rect[2];
  const height = rect[3];

  const trueStar = {x: 280, y: 130};
  const apparentStar = {x: 440, y: 110};
  const sunCenter = {x: 520, y: 520};
  const earthCenter = {x: 740, y: 920};

  const curvedPathD = 'M 280,130 C 330,320 405,480 435,540 C 475,620 620,800 740,920';
  const apparentPathD = 'M 740,920 L 440,110';

  const photonProgress = (frame * 0.012) % 1.0;
  const photonProgress2 = (frame * 0.012 + 0.33) % 1.0;
  const photonProgress3 = (frame * 0.012 + 0.66) % 1.0;

  const bezierPt = (t: number, p0: number, p1: number, p2: number, p3: number) => {
    const mt = 1 - t;
    return mt * mt * mt * p0 + 3 * mt * mt * t * p1 + 3 * mt * t * t * p2 + t * t * t * p3;
  };

  const getPhoton = (p: number) => {
    if (p < 0.5) {
      const t = p * 2;
      return {
        x: bezierPt(t, 280, 330, 405, 435),
        y: bezierPt(t, 130, 320, 480, 540),
      };
    } else {
      const t = (p - 0.5) * 2;
      return {
        x: bezierPt(t, 435, 475, 620, 740),
        y: bezierPt(t, 540, 620, 800, 920),
      };
    }
  };

  const ph1 = getPhoton(photonProgress);
  const ph2 = getPhoton(photonProgress2);
  const ph3 = getPhoton(photonProgress3);

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width: rect[2],
        height: rect[3],
        overflow: 'hidden',
        pointerEvents: 'none',
        borderRadius: 24,
        border: '1px solid rgba(0, 240, 255, 0.25)',
        backgroundColor: '#040711',
        boxShadow: '0 25px 70px rgba(0,0,0,0.85), inset 0 0 80px rgba(0, 240, 255, 0.05)',
      }}
    >
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <defs>
          <radialGradient id="eclipseCorona" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.9" />
            <stop offset="25%" stopColor="#A5ECFF" stopOpacity="0.75" />
            <stop offset="60%" stopColor="#FFB800" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#040711" stopOpacity="0" />
          </radialGradient>
          <filter id="lightGlow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        <g transform={`translate(${sunCenter.x}, ${sunCenter.y})`}>
          {[100, 160, 230].map((cr, idx) => (
            <circle
              key={idx}
              r={cr}
              fill="none"
              stroke="rgba(0, 240, 255, 0.25)"
              strokeWidth="1.2"
              strokeDasharray="4 6"
            />
          ))}

          <circle
            r={70 + Math.sin(frame * 0.1) * 4}
            fill="url(#eclipseCorona)"
            filter="url(#lightGlow)"
          />
          <circle r="44" fill="#030509" stroke="#FFB800" strokeWidth="1.5" />
          <circle r="43" fill="#070A14" />

          <text
            x="0"
            y="-56"
            fill="#FFB800"
            fontSize="14"
            fontFamily="monospace"
            fontWeight="bold"
            textAnchor="middle"
          >
            1919 日全食 (TOTAL ECLIPSE)
          </text>
          <text
            x="0"
            y="64"
            fill="#8BA1C1"
            fontSize="12"
            fontFamily="monospace"
            textAnchor="middle"
          >
            月球遮挡强光，星光得以显现
          </text>
        </g>

        <path
          d={curvedPathD}
          fill="none"
          stroke="rgba(0, 240, 255, 0.35)"
          strokeWidth="6"
        />
        <path
          d={curvedPathD}
          fill="none"
          stroke="#00F0FF"
          strokeWidth="2.5"
          filter="url(#lightGlow)"
        />

        {[ph1, ph2, ph3].map((ph, idx) => (
          <g key={idx} transform={`translate(${ph.x.toFixed(1)}, ${ph.y.toFixed(1)})`}>
            <circle r="7" fill="#00F0FF" filter="url(#lightGlow)" />
            <circle r="3" fill="#FFFFFF" />
          </g>
        ))}

        <path
          d={apparentPathD}
          fill="none"
          stroke="#FFB800"
          strokeWidth="2"
          strokeDasharray="6 6"
          opacity="0.8"
          filter="url(#lightGlow)"
        />

        <g transform={`translate(${trueStar.x}, ${trueStar.y})`}>
          <circle r="16" fill="rgba(0, 240, 255, 0.25)" filter="url(#lightGlow)" />
          <circle r="7" fill="#00F0FF" />
          <circle r="3" fill="#FFFFFF" />
          <text
            x="-24"
            y="-14"
            fill="#00F0FF"
            fontSize="15"
            fontFamily="monospace"
            fontWeight="bold"
            textAnchor="end"
          >
            ★ 恒星真实位置 (TRUE STAR)
          </text>
          <text
            x="-24"
            y="6"
            fill="#8BA1C1"
            fontSize="12"
            fontFamily="monospace"
            textAnchor="end"
          >
            发出直线光束
          </text>
        </g>

        <g transform={`translate(${apparentStar.x}, ${apparentStar.y})`}>
          <circle
            r={12 + ((frame * 1.2) % 25)}
            fill="none"
            stroke="#FFB800"
            strokeWidth="1.5"
            opacity={Math.max(0, 1 - ((frame * 1.2) % 25) / 25)}
          />
          <circle r="6" fill="none" stroke="#FFB800" strokeWidth="2" strokeDasharray="2 2" />
          <circle r="3" fill="#FFB800" />
          <text
            x="20"
            y="-10"
            fill="#FFB800"
            fontSize="15"
            fontFamily="monospace"
            fontWeight="bold"
          >
            ✦ 观测视位置 (APPARENT)
          </text>
          <text
            x="20"
            y="8"
            fill="#FFD23F"
            fontSize="12"
            fontFamily="monospace"
          >
            望远镜反向视线假像
          </text>
        </g>

        <g stroke="#FFB800" strokeWidth="1.5">
          <line x1={trueStar.x + 10} y1={trueStar.y - 12} x2={apparentStar.x - 10} y2={apparentStar.y - 12} />
          <line x1={trueStar.x + 10} y1={trueStar.y - 18} x2={trueStar.x + 10} y2={trueStar.y - 6} />
          <line x1={apparentStar.x - 10} y1={apparentStar.y - 18} x2={apparentStar.x - 10} y2={apparentStar.y - 6} />
        </g>
        <g transform="translate(340, 95)">
          <rect width="160" height="26" rx="6" fill="rgba(255, 184, 0, 0.15)" stroke="#FFB800" strokeWidth="1" />
          <text x="80" y="18" fill="#FFD23F" fontSize="13" fontFamily="monospace" fontWeight="bold" textAnchor="middle">
            Δθ = 1.75'' 错位
          </text>
        </g>

        <g transform={`translate(${earthCenter.x}, ${earthCenter.y})`}>
          <circle r="26" fill="rgba(0, 240, 255, 0.15)" />
          <circle r="16" fill="#00F0FF" filter="url(#lightGlow)" />
          <circle r="6" fill="#FFFFFF" />
          <line x1="-15" y1="-15" x2="-35" y2="-35" stroke="#00F0FF" strokeWidth="4" strokeLinecap="round" />
          <circle cx="-35" cy="-35" r="5" fill="#00F0FF" />
          <text
            x="-18"
            y="32"
            fill="#00F0FF"
            fontSize="15"
            fontFamily="monospace"
            fontWeight="bold"
            textAnchor="middle"
          >
            地球观测站 (EARTH OBSERVER)
          </text>
          <text
            x="-18"
            y="50"
            fill="#8BA1C1"
            fontSize="12"
            fontFamily="monospace"
            textAnchor="middle"
          >
            爱丁顿 1919 普林西比日食远征队
          </text>
        </g>

        <g stroke="rgba(0, 240, 255, 0.4)" strokeWidth="1.5">
          <path d="M 30,50 L 30,30 L 50,30" fill="none" />
          <path d={`M ${width - 30},50 L ${width - 30},30 L ${width - 50},30`} fill="none" />
        </g>
        <text x="50" y="55" fill="rgba(0, 240, 255, 0.75)" fontSize="13" fontFamily="monospace" letterSpacing="0.1em">
          EMPIRICAL PROOF: GRAVITATIONAL DEFLECTION OF LIGHT (1919)
        </text>

        <g transform={`translate(50, ${height - 65})`}>
          <rect width="900" height="40" rx="8" fill="rgba(0, 240, 255, 0.08)" stroke="rgba(0, 240, 255, 0.3)" strokeWidth="1" />
          <text x="24" y="25" fill="#FFFFFF" fontSize="14" fontFamily="monospace">
            ● 实验铁证：光子没有质量，但经过太阳弯曲时空时发生了偏折，一举证实广义相对论！
          </text>
        </g>
      </svg>
    </div>
  );
};

export const SpacetimeWavesComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {rect} = layer;
  const width = rect[2];
  const height = rect[3];

  const cx = 500;
  const cy = 390;

  const omega = (frame * 2.8 * Math.PI) / 180;
  const orbitR = 64;
  const star1 = {
    x: cx + orbitR * Math.cos(omega),
    y: cy + orbitR * 0.45 * Math.sin(omega),
  };
  const star2 = {
    x: cx - orbitR * Math.cos(omega),
    y: cy - orbitR * 0.45 * Math.sin(omega),
  };

  const waveCount = 8;
  const waves: Array<{rx: number; ry: number; opacity: number; isCyan: boolean}> = [];
  for (let i = 0; i < waveCount; i++) {
    const rawR = ((frame * 2.8 + i * 55) % 440) + 50;
    const opacity = Math.max(0, (1 - rawR / 490) * 0.85);
    waves.push({
      rx: rawR,
      ry: rawR * 0.48,
      opacity,
      isCyan: i % 2 === 0,
    });
  }

  const gridLines: string[] = [];
  for (let gy = 120; gy <= 640; gy += 45) {
    let d = '';
    for (let gx = 60; gx <= 940; gx += 20) {
      const dist = Math.sqrt(Math.pow(gx - cx, 2) + Math.pow((gy - cy) * 2, 2));
      const strain = Math.sin(dist * 0.05 - frame * 0.12) * Math.max(0, 18 - dist * 0.03);
      const py = gy + strain;
      d += gx === 60 ? `M ${gx},${py.toFixed(1)}` : ` L ${gx},${py.toFixed(1)}`;
    }
    gridLines.push(d);
  }

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width: rect[2],
        height: rect[3],
        overflow: 'hidden',
        pointerEvents: 'none',
        borderRadius: 24,
        border: '1px solid rgba(0, 240, 255, 0.25)',
        backgroundColor: '#040711',
        boxShadow: '0 25px 70px rgba(0,0,0,0.85), inset 0 0 80px rgba(0, 240, 255, 0.05)',
      }}
    >
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <defs>
          <filter id="starGlow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="7" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        <g stroke="rgba(0, 240, 255, 0.14)" strokeWidth="1" fill="none">
          {gridLines.map((d, i) => (
            <path key={`g-${i}`} d={d} />
          ))}
        </g>

        {waves.map((w, idx) => (
          <ellipse
            key={`wave-${idx}`}
            cx={cx}
            cy={cy}
            rx={w.rx}
            ry={w.ry}
            fill="none"
            stroke={w.isCyan ? '#00F0FF' : '#FFB800'}
            strokeWidth={w.isCyan ? 2 : 1.5}
            strokeDasharray={w.isCyan ? 'none' : '4 6'}
            opacity={w.opacity}
          />
        ))}

        <line
          x1={star1.x}
          y1={star1.y}
          x2={star2.x}
          y2={star2.y}
          stroke="rgba(0, 240, 255, 0.6)"
          strokeWidth="2"
          strokeDasharray="2 3"
        />

        <g transform={`translate(${star1.x.toFixed(1)}, ${star1.y.toFixed(1)})`}>
          <circle r="14" fill="#00F0FF" filter="url(#starGlow)" />
          <circle r="7" fill="#FFFFFF" />
        </g>

        <g transform={`translate(${star2.x.toFixed(1)}, ${star2.y.toFixed(1)})`}>
          <circle r="14" fill="#FFB800" filter="url(#starGlow)" />
          <circle r="7" fill="#FFFFFF" />
        </g>

        <text
          x={cx}
          y={cy - 85}
          fill="rgba(0, 240, 255, 0.85)"
          fontSize="14"
          fontFamily="monospace"
          fontWeight="bold"
          letterSpacing="0.1em"
          textAnchor="middle"
        >
          双星绕转引力波源 // BINARY MERGER GW SOURCE
        </text>

        <g transform="translate(50, 670)">
          <rect
            width="900"
            height="310"
            rx="18"
            fill="rgba(8, 14, 28, 0.92)"
            stroke="rgba(0, 240, 255, 0.4)"
            strokeWidth="1.5"
          />

          <g transform="translate(30, 22)">
            <rect width="360" height="30" rx="6" fill="rgba(0, 240, 255, 0.12)" stroke="rgba(0, 240, 255, 0.4)" strokeWidth="1" />
            <text x="14" y="20" fill="#00F0FF" fontSize="13" fontFamily="monospace" letterSpacing="0.1em">
              ● 广义相对论终极公理 // WHEELER'S AXIOM
            </text>
          </g>

          <text
            x="40"
            y="105"
            fill="#00F0FF"
            fontSize="32"
            fontFamily="PingFang SC, sans-serif"
            fontWeight="800"
            letterSpacing="0.04em"
            filter="url(#starGlow)"
          >
            “ 物质告诉时空如何弯曲 ，
          </text>
          <text
            x="70"
            y="158"
            fill="#FFB800"
            fontSize="32"
            fontFamily="PingFang SC, sans-serif"
            fontWeight="800"
            letterSpacing="0.04em"
            filter="url(#starGlow)"
          >
              时空告诉物质如何运动 。”
          </text>

          <g transform="translate(40, 205)">
            <rect width="820" height="42" rx="8" fill="rgba(0, 240, 255, 0.06)" stroke="rgba(255, 255, 255, 0.1)" strokeWidth="1" />
            <text x="24" y="26" fill="#00F0FF" fontSize="15" fontFamily="monospace" fontWeight="bold">
              [ G_μν 时空几何曲率 ]
            </text>
            <text x="410" y="27" fill="#FFFFFF" fontSize="18" fontFamily="monospace" textAnchor="middle">
              ⟷  (8πG / c⁴)  ⟷
            </text>
            <text x="796" y="26" fill="#FFB800" fontSize="15" fontFamily="monospace" fontWeight="bold" textAnchor="end">
              [ T_μν 物质能量动量 ]
            </text>
          </g>

          <text
            x="860"
            y="280"
            fill="#8BA1C1"
            fontSize="14"
            fontFamily="serif"
            fontStyle="italic"
            textAnchor="end"
          >
            — 约翰·阿奇博尔德·惠勒 (John Archibald Wheeler)
          </text>
        </g>

        <g stroke="rgba(0, 240, 255, 0.4)" strokeWidth="1.5">
          <path d="M 30,50 L 30,30 L 50,30" fill="none" />
          <path d={`M ${width - 30},50 L ${width - 30},30 L ${width - 50},30`} fill="none" />
        </g>
        <text x="50" y="55" fill="rgba(0, 240, 255, 0.75)" fontSize="13" fontFamily="monospace" letterSpacing="0.1em">
          DYNAMIC SPACETIME TAPESTRY & GRAVITATIONAL WAVES
        </text>
      </svg>
    </div>
  );
};

export const BlackHoleHeroComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {rect} = layer;
  const width = rect[2];
  const height = rect[3];
  const cx = width / 2;
  const cy = height / 2;

  // 36 dynamic swirling photon particles along photon ring & accretion flow
  const particles = Array.from({length: 36}).map((_, i) => {
    const baseRadius = 140 + (i % 6) * 45;
    const speed = 0.04 + (1 / Math.sqrt(baseRadius)) * 0.45;
    const angle = (frame * speed + (i * Math.PI * 2) / 36) % (Math.PI * 2);
    // Relativistic inclined projection (elliptical orbit with Doppler beaming)
    const x = cx + Math.cos(angle) * baseRadius * 1.5;
    const y = cy + Math.sin(angle) * baseRadius * 0.65;
    // Approaching side (x < cx) is Doppler boosted (brighter, hotter color)
    const isApproaching = Math.sin(angle) > 0;
    const dopplerBrightness = isApproaching ? 0.95 : 0.4;
    const color = isApproaching ? '#FFF0C8' : '#FF7700';
    const size = isApproaching ? 3.5 : 2.0;

    return {x, y, dopplerBrightness, color, size};
  });

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width: rect[2],
        height: rect[3],
        overflow: 'hidden',
        pointerEvents: 'none',
        borderRadius: 24,
        border: '1px solid rgba(255, 136, 0, 0.35)',
        backgroundColor: 'transparent',
        boxShadow: '0 25px 70px rgba(0,0,0,0.85), inset 0 0 80px rgba(255, 136, 0, 0.08)',
      }}
    >
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <defs>
          <radialGradient id="bhGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#FF8800" stopOpacity="0.4" />
            <stop offset="60%" stopColor="#FF4400" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#06080F" stopOpacity="0" />
          </radialGradient>
          <filter id="bhBloom" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* Ambient atmospheric glow behind accretion disk */}
        <circle cx={cx} cy={cy} r="320" fill="url(#bhGlow)" filter="url(#bhBloom)" />

        {/* Concentric Relativistic Relativistic Orbit Radii */}
        {[
          {r: 120, label: 'EVENT HORIZON // 史瓦西半径 Rs = 2GM/c²', stroke: 'rgba(255, 68, 0, 0.55)', dash: '4 4'},
          {r: 180, label: 'PHOTON SPHERE // 光子球 r = 1.5 Rs', stroke: 'rgba(255, 184, 0, 0.65)', dash: '6 6'},
          {r: 320, label: 'ISCO // 最内稳定圆轨道 r = 3.0 Rs', stroke: 'rgba(0, 240, 255, 0.35)', dash: '8 8'},
        ].map((ring, idx) => (
          <g key={idx}>
            <ellipse
              cx={cx}
              cy={cy}
              rx={ring.r * 1.5}
              ry={ring.r * 0.65}
              fill="none"
              stroke={ring.stroke}
              strokeWidth="1.4"
              strokeDasharray={ring.dash}
            />
            <text
              x={cx + ring.r * 1.5 - 10}
              y={cy - 12 - idx * 22}
              textAnchor="end"
              fill={ring.stroke}
              fontSize="11"
              fontFamily="monospace"
              letterSpacing="0.05em"
            >
              {ring.label}
            </text>
          </g>
        ))}

        {/* Swirling Relativistic Photon Particles with Doppler Boost */}
        {particles.map((p, idx) => (
          <g key={idx} transform={`translate(${p.x.toFixed(1)}, ${p.y.toFixed(1)})`}>
            <circle
              r={p.size * 2}
              fill={p.color}
              opacity={p.dopplerBrightness * 0.5}
              filter="url(#bhBloom)"
            />
            <circle r={p.size} fill={p.color} opacity={p.dopplerBrightness} />
          </g>
        ))}

        {/* Doppler Beaming Indicator on the Left */}
        <g transform={`translate(100, ${cy - 80})`}>
          <rect width="240" height="48" rx="6" fill="rgba(255, 136, 0, 0.15)" stroke="rgba(255, 184, 0, 0.4)" strokeWidth="1" />
          <text x="14" y="20" fill="#FFB800" fontSize="12" fontFamily="monospace" fontWeight="bold">
            ⚡ 多普勒集束效应 (BEAMING)
          </text>
          <text x="14" y="38" fill="#FFF0C8" fontSize="11" fontFamily="monospace">
            朝向观察者高速运动，亮度狂飙
          </text>
        </g>

        {/* Holographic Frame HUD Header */}
        <g stroke="rgba(255, 136, 0, 0.5)" strokeWidth="1.5">
          <path d="M 30,50 L 30,30 L 50,30" fill="none" />
          <path d={`M ${width - 30},50 L ${width - 30},30 L ${width - 50},30`} fill="none" />
        </g>
        <text x="50" y="55" fill="rgba(255, 184, 0, 0.85)" fontSize="13" fontFamily="monospace" letterSpacing="0.1em">
          RELATIVISTIC ACCRETION DISK // GRAVITATIONAL LENSING
        </text>
      </svg>
    </div>
  );
};

export const TimeDilationHeroComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {rect} = layer;
  const width = rect[2];
  const height = rect[3];

  // Falling probe animation
  const loopT = (frame % 240) / 240; // 8s cycle
  // Objective time: probe approaches horizon asymptotically (slows down to 0)
  const outsideX = 140 + (1 - Math.exp(-loopT * 4)) * 260; // approaches 400
  // Subjective time: probe plunges steadily across horizon
  const insideX = 580 + loopT * 320; // crosses horizon at 740

  // Gravitational redshift: cyan (#00F0FF) -> amber (#FFB800) -> infrared crimson (#FF2244)
  const redshiftColor =
    loopT < 0.35
      ? '#00F0FF'
      : loopT < 0.7
        ? '#FFB800'
        : '#FF2244';
  const outsideOpacity = Math.max(0.2, 1 - loopT * 0.75);

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width: rect[2],
        height: rect[3],
        overflow: 'hidden',
        pointerEvents: 'none',
        borderRadius: 24,
        border: '1px solid rgba(0, 240, 255, 0.25)',
        backgroundColor: '#040711',
        boxShadow: '0 25px 70px rgba(0,0,0,0.85)',
      }}
    >
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        {/* Left Column: Outside Observer Perspective */}
        <rect x="30" y="90" width="450" height="880" rx="16" fill="rgba(10, 16, 36, 0.6)" stroke="rgba(0, 240, 255, 0.2)" strokeWidth="1" />
        <text x="50" y="140" fill="#00F0FF" fontSize="18" fontFamily="monospace" fontWeight="bold">
          [ 远方飞船视角 // 外部参考系 ]
        </text>
        <text x="50" y="170" fill="#8BA1C1" fontSize="13" fontFamily="monospace">
          引力时间膨胀公式: dt = dτ / √(1 - Rs/r)
        </text>

        {/* Event Horizon Line on Left */}
        <line x1="420" y1="210" x2="420" y2="880" stroke="#FF4400" strokeWidth="3" strokeDasharray="6 6" />
        <text x="410" y="240" fill="#FF4400" fontSize="13" fontFamily="monospace" fontWeight="bold" textAnchor="end">
          事件视界边界 (r = Rs)
        </text>

        {/* Outside Observer Spaceship */}
        <circle cx="80" cy="500" r="18" fill="rgba(0, 240, 255, 0.2)" />
        <circle cx="80" cy="500" r="7" fill="#00F0FF" />
        <text x="80" y="540" fill="#00F0FF" fontSize="12" fontFamily="monospace" textAnchor="middle">
          母舰观测站
        </text>

        {/* Falling Probe seen from outside */}
        <g transform={`translate(${outsideX.toFixed(1)}, 500)`}>
          <circle r="22" fill={redshiftColor} opacity={outsideOpacity * 0.3} />
          <circle r="10" fill={redshiftColor} opacity={outsideOpacity} />
          <text x="0" y="-30" fill={redshiftColor} fontSize="12" fontFamily="monospace" fontWeight="bold" textAnchor="middle">
            引力红移 (λ 极度拉长)
          </text>
          <text x="0" y="32" fill="#8BA1C1" fontSize="11" fontFamily="monospace" textAnchor="middle">
            速度渐进趋近 0 (无限冻结)
          </text>
        </g>

        {/* Left Bottom Insight */}
        <g transform="translate(50, 840)">
          <rect width="410" height="60" rx="8" fill="rgba(255, 68, 0, 0.15)" stroke="rgba(255, 68, 0, 0.4)" strokeWidth="1" />
          <text x="16" y="26" fill="#FF8800" fontSize="13" fontFamily="monospace" fontWeight="bold">
            ● 观测结论：时间永远停滞 (t → ∞)
          </text>
          <text x="16" y="46" fill="#FFF" fontSize="12" fontFamily="monospace">
            在外界眼里，你永远不会穿过视界，只留下一张红移遗照
          </text>
        </g>

        {/* Right Column: Infalling Astronaut Subjective Perspective */}
        <rect x="520" y="90" width="450" height="880" rx="16" fill="rgba(10, 16, 36, 0.6)" stroke="rgba(255, 184, 0, 0.2)" strokeWidth="1" />
        <text x="540" y="140" fill="#FFB800" fontSize="18" fontFamily="monospace" fontWeight="bold">
          [ 坠入者主观视角 // 自身参考系 ]
        </text>
        <text x="540" y="170" fill="#8BA1C1" fontSize="13" fontFamily="monospace">
          本征时间 τ 持续匀速流逝，毫无阻碍
        </text>

        {/* Event Horizon Line on Right */}
        <line x1="740" y1="210" x2="740" y2="880" stroke="#FF4400" strokeWidth="3" strokeDasharray="6 6" />
        <text x="750" y="240" fill="#FF4400" fontSize="13" fontFamily="monospace" fontWeight="bold">
          视界不是一堵墙
        </text>

        {/* Falling Probe seen subjectively */}
        <g transform={`translate(${insideX.toFixed(1)}, 500)`}>
          <circle r="22" fill="#FFB800" opacity="0.3" />
          <circle r="10" fill="#FFB800" />
          <circle r="4" fill="#FFFFFF" />
          <text x="0" y="-30" fill="#FFB800" fontSize="12" fontFamily="monospace" fontWeight="bold" textAnchor="middle">
            主观手表 τ 正常跳动
          </text>
          <text x="0" y="32" fill="#00F0FF" fontSize="11" fontFamily="monospace" textAnchor="middle">
            毫不迟疑穿过视界 ➔
          </text>
        </g>

        {/* Right Bottom Insight */}
        <g transform="translate(540, 840)">
          <rect width="410" height="60" rx="8" fill="rgba(0, 240, 255, 0.15)" stroke="rgba(0, 240, 255, 0.4)" strokeWidth="1" />
          <text x="16" y="26" fill="#00F0FF" fontSize="13" fontFamily="monospace" fontWeight="bold">
            ● 自身体验：数秒内毫无异样穿过
          </text>
          <text x="16" y="46" fill="#FFF" fontSize="12" fontFamily="monospace">
            你感觉不到任何边界撞击，平滑进入时间逆转的视界内部
          </text>
        </g>

        {/* Holographic Header */}
        <g stroke="rgba(0, 240, 255, 0.4)" strokeWidth="1.5">
          <path d="M 30,50 L 30,30 L 50,30" fill="none" />
          <path d={`M ${width - 30},50 L ${width - 30},30 L ${width - 50},30`} fill="none" />
        </g>
        <text x="50" y="55" fill="rgba(0, 240, 255, 0.75)" fontSize="13" fontFamily="monospace" letterSpacing="0.1em">
          GRAVITATIONAL TIME DILATION // TWIN PARADOX HORIZON
        </text>
      </svg>
    </div>
  );
};

export const LightConeTiltHeroComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {rect} = layer;
  const width = rect[2];
  const height = rect[3];

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width: rect[2],
        height: rect[3],
        overflow: 'hidden',
        pointerEvents: 'none',
        borderRadius: 24,
        border: '1px solid rgba(255, 136, 0, 0.3)',
        backgroundColor: '#040711',
        boxShadow: '0 25px 70px rgba(0,0,0,0.85)',
      }}
    >
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        {/* Background Coordinate Grid */}
        <defs>
          <linearGradient id="singularityGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#FF2244" stopOpacity="0.8" />
            <stop offset="100%" stopColor="#FF7700" stopOpacity="0.1" />
          </linearGradient>
        </defs>

        {/* Zone 1: Normal Universe (r > Rs) */}
        <g transform="translate(160, 520)">
          <text x="0" y="-280" fill="#00F0FF" fontSize="16" fontFamily="monospace" fontWeight="bold" textAnchor="middle">
            {'[ 正常宇宙 r > Rs ]'}
          </text>
          <text x="0" y="-255" fill="#8BA1C1" fontSize="12" fontFamily="monospace" textAnchor="middle">
            光锥垂直朝向时间未来
          </text>

          {/* Upright Light Cone (0 deg tilt) */}
          <polygon points="0,0 -80,-160 80,-160" fill="rgba(0, 240, 255, 0.15)" stroke="#00F0FF" strokeWidth="2" />
          <line x1="0" y1="0" x2="0" y2="-180" stroke="#00F0FF" strokeWidth="2" strokeDasharray="4 4" />
          <text x="0" y="-190" fill="#00F0FF" fontSize="12" fontFamily="monospace" textAnchor="middle">未来时间轴 t ➔</text>
          <text x="0" y="30" fill="#FFF" fontSize="13" fontFamily="monospace" textAnchor="middle">空间自由移动 (← r →)</text>
        </g>

        {/* Event Horizon Dividing Wall */}
        <g transform="translate(470, 200)">
          <line x1="0" y1="0" x2="0" y2="680" stroke="#FF4400" strokeWidth="3" strokeDasharray="8 6" />
          <text x="0" y="-30" fill="#FF4400" fontSize="17" fontFamily="monospace" fontWeight="bold" textAnchor="middle">
            事件视界 r = Rs
          </text>
          <text x="0" y="-10" fill="#FFB800" fontSize="12" fontFamily="monospace" textAnchor="middle">
            光锥倾斜 45°
          </text>

          {/* 45-degree Tilted Light Cone at Horizon */}
          <g transform="translate(0, 320)">
            <polygon points="0,0 -40,-120 120,-40" fill="rgba(255, 136, 0, 0.25)" stroke="#FF8800" strokeWidth="2.5" />
            <text x="0" y="30" fill="#FF8800" fontSize="12" fontFamily="monospace" textAnchor="middle">光线无法向外逃逸</text>
          </g>
        </g>

        {/* Zone 3: Inside Horizon (r < Rs) */}
        <g transform="translate(730, 520)">
          <text x="0" y="-280" fill="#FF2244" fontSize="16" fontFamily="monospace" fontWeight="bold" textAnchor="middle">
            {'[ 视界内部 r < Rs ]'}
          </text>
          <text x="0" y="-255" fill="#FF8800" fontSize="12" fontFamily="monospace" textAnchor="middle">
            光锥彻底横转 90°
          </text>

          {/* 90-degree Tilted Light Cone (Points right into Singularity) */}
          <polygon points="0,0 140,-70 140,70" fill="rgba(255, 34, 68, 0.25)" stroke="#FF2244" strokeWidth="2.5" />
          <line x1="0" y1="0" x2="160" y2="0" stroke="#FF2244" strokeWidth="2" strokeDasharray="4 4" />
          <text x="170" y="5" fill="#FF2244" fontSize="12" fontFamily="monospace" textAnchor="start">必然坠落 ➔</text>
          <text x="70" y="105" fill="#FFF" fontSize="13" fontFamily="monospace" textAnchor="middle">径向 r 变成了单向时间！</text>
        </g>

        {/* Center Bottom Core Invariant */}
        <g transform="translate(70, 840)">
          <rect width="860" height="70" rx="10" fill="rgba(255, 136, 0, 0.12)" stroke="rgba(255, 136, 0, 0.4)" strokeWidth="1" />
          <text x="30" y="30" fill="#FFB800" fontSize="15" fontFamily="monospace" fontWeight="bold">
            ★ 相对论终极颠覆：奇点不再是空间中的一个地点，而是你时间线上的“明天”
          </text>
          <text x="30" y="52" fill="#FFFFFF" fontSize="13" fontFamily="monospace">
            你无法阻止明天的到来，正如在黑洞内部，你无论朝哪个方向喷气，都会不可逆地坠向中心奇点。
          </text>
        </g>

        {/* Holographic Header */}
        <g stroke="rgba(255, 136, 0, 0.4)" strokeWidth="1.5">
          <path d="M 30,50 L 30,30 L 50,30" fill="none" />
          <path d={`M ${width - 30},50 L ${width - 30},30 L ${width - 50},30`} fill="none" />
        </g>
        <text x="50" y="55" fill="rgba(255, 136, 0, 0.85)" fontSize="13" fontFamily="monospace" letterSpacing="0.1em">
          SPACETIME INVERSION // LIGHT CONE TIPPING INTO FUTURE
        </text>
      </svg>
    </div>
  );
};

export const SpaghettificationHeroComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {rect} = layer;
  const width = rect[2];
  const height = rect[3];
  const cx = width / 2;

  // Spaghettification stretching cycle
  const stretchProgress = (frame % 180) / 180;
  const stretchHeight = 100 + stretchProgress * 420;
  const stretchWidth = Math.max(8, 70 - stretchProgress * 62);
  const probeY = 220 + stretchProgress * 280;

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width: rect[2],
        height: rect[3],
        overflow: 'hidden',
        pointerEvents: 'none',
        borderRadius: 24,
        border: '1px solid rgba(255, 68, 0, 0.35)',
        backgroundColor: '#040711',
        boxShadow: '0 25px 70px rgba(0,0,0,0.85)',
      }}
    >
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <defs>
          <radialGradient id="singularityCore" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="1" />
            <stop offset="30%" stopColor="#FFB800" stopOpacity="0.9" />
            <stop offset="70%" stopColor="#FF2244" stopOpacity="0.4" />
            <stop offset="100%" stopColor="#040711" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Tidal Gradient Vector Arrows (Stretching Vertical, Compressing Horizontal) */}
        <g stroke="rgba(255, 136, 0, 0.4)" strokeWidth="1.5">
          {[-180, 180].map((dx, i) => (
            <g key={i} transform={`translate(${cx + dx}, 400)`}>
              <line x1="0" y1="-120" x2="0" y2="120" />
              <path d="M -8,-100 L 0,-120 L 8,-100" fill="none" />
              <path d="M -8,100 L 0,120 L 8,100" fill="none" />
              <text x={dx > 0 ? 15 : -15} y="5" fill="#FF8800" fontSize="12" fontFamily="monospace" textAnchor={dx > 0 ? 'start' : 'end'}>
                纵向极端拉伸 (▲ ▼)
              </text>
            </g>
          ))}
        </g>

        {/* Spaghettification Falling Body (Stretched into glowing atomic filament) */}
        <g transform={`translate(${cx}, ${probeY})`}>
          <ellipse
            cx="0"
            cy="0"
            rx={stretchWidth}
            ry={stretchHeight / 2}
            fill="rgba(0, 240, 255, 0.25)"
            stroke="#00F0FF"
            strokeWidth="2"
          />
          {/* Internal atomic particle string */}
          {Array.from({length: 12}).map((_, i) => {
            const py = -stretchHeight / 2 + (i * stretchHeight) / 11;
            return <circle key={i} cx="0" cy={py} r="3" fill="#FFB800" />;
          })}
          <text x="45" y="0" fill="#00F0FF" fontSize="13" fontFamily="monospace" fontWeight="bold">
            面条化 (SPAGHETTIFICATION)
          </text>
          <text x="45" y="20" fill="#8BA1C1" fontSize="11" fontFamily="monospace">
            脚底与头顶引力差达数百万 G
          </text>
        </g>

        {/* Central Singularity Point at Bottom */}
        <g transform={`translate(${cx}, 780)`}>
          <circle r={35 + Math.sin(frame * 0.15) * 6} fill="url(#singularityCore)" />
          <circle r="6" fill="#FFFFFF" />
          <circle r="12" fill="none" stroke="#FFFFFF" strokeWidth="1.5" strokeDasharray="3 3" />
          <text x="0" y="60" fill="#FF2244" fontSize="16" fontFamily="monospace" fontWeight="bold" textAnchor="middle">
            中心奇点 // THE SINGULARITY
          </text>
          <text x="0" y="82" fill="#8BA1C1" fontSize="12" fontFamily="monospace" textAnchor="middle">
            曲率与密度无穷大，已知物理学在此崩溃
          </text>
        </g>

        {/* Golden Closing Quote Box */}
        <g transform="translate(60, 890)">
          <rect width="880" height="70" rx="10" fill="rgba(255, 68, 0, 0.12)" stroke="rgba(255, 136, 0, 0.4)" strokeWidth="1" />
          <text x="440" y="42" fill="#FFB800" fontSize="18" fontFamily="serif" fontWeight="bold" textAnchor="middle">
            “黑洞不是空间的终点，它是时间的尽头。”
          </text>
        </g>

        {/* Holographic Header */}
        <g stroke="rgba(255, 68, 0, 0.4)" strokeWidth="1.5">
          <path d="M 30,50 L 30,30 L 50,30" fill="none" />
          <path d={`M ${width - 30},50 L ${width - 30},30 L ${width - 50},30`} fill="none" />
        </g>
        <text x="50" y="55" fill="rgba(255, 136, 0, 0.85)" fontSize="13" fontFamily="monospace" letterSpacing="0.1em">
          TIDAL FORCES & SINGULARITY // THE FINAL DESTINATION
        </text>
      </svg>
    </div>
  );
};

export const TunnelHeroComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {rect} = layer;
  const width = rect[2];
  const height = rect[3];

  const barrierW = 84;
  const barrierX = width / 2;
  const ballR = 26;
  const leftEdge = 80;
  const hitX = barrierX - barrierW / 2 - ballR;
  const midY = height / 2 - 30;

  // Classical ball: bounces off the wall every 150 frames (squash on impact).
  const t = (frame % 150) / 150;
  const travel = hitX - leftEdge;
  const ballX = t < 0.5 ? leftEdge + (t / 0.5) * travel : hitX - ((t - 0.5) / 0.5) * travel;
  const atWall = Math.abs(t - 0.5) < 0.05;
  const ballSquish = atWall ? 1.35 : 1;

  // Quantum particle: launched from the wall right as the ball hits, crosses the
  // right half with a probability cloud; a detection ring pops at arrival.
  const tq = ((frame + 75) % 150) / 150;
  const qStartX = barrierX + barrierW / 2 + 12;
  const qEndX = width - 120;
  const qx = qStartX + tq * (qEndX - qStartX);
  const qOpacity = Math.sin(tq * Math.PI);

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width,
        height,
        overflow: 'hidden',
        pointerEvents: 'none',
        borderRadius: 24,
        border: '1px solid rgba(184, 77, 255, 0.3)',
        backgroundColor: 'rgba(7, 5, 18, 0.55)',
        boxShadow: '0 25px 70px rgba(0,0,0,0.85), inset 0 0 80px rgba(184, 77, 255, 0.06)',
      }}
    >
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <defs>
          <filter id="tqGlow" x="-40%" y="-40%" width="180%" height="180%">
            <feGaussianBlur stdDeviation="7" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* Central barrier: pulsing violet wall */}
        <rect
          x={barrierX - barrierW / 2}
          y={90}
          width={barrierW}
          height={height - 260}
          rx={14}
          fill="rgba(184, 77, 255, 0.22)"
          stroke="#B84DFF"
          strokeWidth={2}
          opacity={0.85 + Math.sin(frame * 0.1) * 0.15}
          filter="url(#tqGlow)"
        />
        <text
          x={barrierX}
          y={70}
          fill="#B84DFF"
          fontSize="15"
          fontFamily="monospace"
          fontWeight="bold"
          textAnchor="middle"
          letterSpacing="0.08em"
        >
          势垒 BARRIER (V₀)
        </text>

        {/* Zone labels */}
        <text x={leftEdge} y={110} fill="#8BA1C1" fontSize="15" fontFamily="monospace" fontWeight="bold">
          经典世界 // CLASSICAL
        </text>
        <text x={leftEdge} y={134} fill="rgba(139, 161, 193, 0.7)" fontSize="12" fontFamily="monospace">
          球 100% 被弹回
        </text>
        <text x={width - 80} y={110} fill="#00F0FF" fontSize="15" fontFamily="monospace" fontWeight="bold" textAnchor="end">
          量子世界 // QUANTUM
        </text>
        <text x={width - 80} y={134} fill="rgba(0, 240, 255, 0.7)" fontSize="12" fontFamily="monospace" textAnchor="end">
          粒子有概率穿过
        </text>

        {/* Classical ball (amber, squashes against the wall) */}
        <g transform={`translate(${ballX.toFixed(1)}, ${midY}) scale(${ballSquish}, ${1 / ballSquish})`}>
          <circle r={ballR * 1.9} fill="#FFB800" opacity="0.18" />
          <circle r={ballR} fill="#FFB800" />
          <circle r={ballR * 0.4} fill="#FFF2A3" />
        </g>
        {atWall && (
          <circle
            cx={hitX + ballR}
            cy={midY}
            r={30 + (frame % 8) * 4}
            fill="none"
            stroke="#FFB800"
            strokeWidth="2"
            opacity={0.6 - (frame % 8) * 0.07}
          />
        )}

        {/* Quantum particle with trailing probability cloud */}
        <g opacity={qOpacity}>
          <circle cx={qx - 46} cy={midY} r={20} fill="#00F0FF" opacity="0.10" />
          <circle cx={qx - 26} cy={midY} r={16} fill="#00F0FF" opacity="0.18" />
          <circle cx={qx} cy={midY} r={26} fill="#00F0FF" opacity="0.28" filter="url(#tqGlow)" />
          <circle cx={qx} cy={midY} r={11} fill="#00F0FF" />
          <circle cx={qx - 3} cy={midY - 3} r={4} fill="#FFFFFF" />
        </g>
        {tq > 0.93 && (
          <circle
            cx={qEndX}
            cy={midY}
            r={(tq - 0.93) * 300}
            fill="none"
            stroke="#00F0FF"
            strokeWidth="2.5"
            opacity={(1 - tq) * 6}
          />
        )}
        <text x={qEndX} y={midY - 44} fill="rgba(0, 240, 255, 0.85)" fontSize="13" fontFamily="monospace" textAnchor="end">
          探测到！DETECTED ✓
        </text>

        {/* Verdict strip */}
        <g transform={`translate(40, ${height - 175})`}>
          <rect width="440" height="46" rx="9" fill="rgba(255, 80, 80, 0.12)" stroke="rgba(255, 80, 80, 0.4)" strokeWidth="1" />
          <text x="16" y="29" fill="#FF8080" fontSize="14" fontFamily="monospace">
            ❌ 经典: E &lt; V₀ ⇒ 永远过不去
          </text>
          <rect x="470" width="450" height="46" rx="9" fill="rgba(0, 240, 255, 0.12)" stroke="rgba(0, 240, 255, 0.4)" strokeWidth="1" />
          <text x="486" y="29" fill="#00F0FF" fontSize="14" fontFamily="monospace">
            ✔ 量子: 波未归零 ⇒ 概率穿墙
          </text>
        </g>

        {/* Holographic header */}
        <g stroke="rgba(184, 77, 255, 0.45)" strokeWidth="1.5">
          <path d="M 30,52 L 30,32 L 50,32" fill="none" />
          <path d={`M ${width - 30},52 L ${width - 30},32 L ${width - 50},32`} fill="none" />
        </g>
        <text x="50" y="58" fill="rgba(184, 77, 255, 0.85)" fontSize="13" fontFamily="monospace" letterSpacing="0.1em">
          CLASSICAL BOUNCE vs QUANTUM TUNNELING
        </text>
      </svg>
    </div>
  );
};

export const WavefunctionHeroComp: React.FC<{layer: CodeLayer}> = ({layer}) => {
  const frame = useCurrentFrame();
  const {rect} = layer;
  const width = rect[2];
  const height = rect[3];

  const plotX0 = 80;
  const plotX1 = width - 80;
  const baseY = height / 2 - 40;
  const bx1 = width * 0.42;
  const bx2 = width * 0.58;
  const barrierW = bx2 - bx1;
  const decayLen = barrierW * 0.9;
  const amp = 66;
  const transmittedAmp = amp * Math.exp(-barrierW / decayLen);

  const envelope = (x: number) => amp * Math.exp(-(x - bx1) / decayLen);
  const waveY = (x: number) => {
    if (x < bx1) return Math.sin((x - frame * 4) * 0.05) * amp;
    if (x <= bx2) return envelope(x) * Math.sin((x - frame * 2) * 0.09);
    return transmittedAmp * Math.sin((x - frame * 4) * 0.05);
  };

  const sample = (from: number, to: number, step = 5) => {
    let d = '';
    for (let x = from; x <= to; x += step) {
      const y = baseY - waveY(x);
      d += x === from ? `M ${x.toFixed(1)},${y.toFixed(1)}` : ` L ${x.toFixed(1)},${y.toFixed(1)}`;
    }
    return d;
  };

  // Probability packet riding the transmitted wave
  const packetX = plotX0 + ((frame * 3.2) % (plotX1 - plotX0));
  const inBarrier = packetX >= bx1 && packetX <= bx2;

  return (
    <div
      style={{
        position: 'absolute',
        left: rect[0],
        top: rect[1],
        width,
        height,
        overflow: 'hidden',
        pointerEvents: 'none',
        borderRadius: 24,
        border: '1px solid rgba(0, 240, 255, 0.25)',
        backgroundColor: 'rgba(7, 5, 18, 0.55)',
        boxShadow: '0 25px 70px rgba(0,0,0,0.85), inset 0 0 80px rgba(0, 240, 255, 0.05)',
      }}
    >
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <defs>
          <filter id="wfGlow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        {/* Baseline */}
        <line x1={plotX0} y1={baseY} x2={plotX1} y2={baseY} stroke="rgba(139, 161, 193, 0.4)" strokeWidth="1.5" />

        {/* Barrier zone */}
        <rect
          x={bx1}
          y={baseY - amp - 70}
          width={barrierW}
          height={(amp + 70) * 2}
          fill="rgba(184, 77, 255, 0.14)"
          stroke="#B84DFF"
          strokeWidth="1.5"
          strokeDasharray="5 5"
        />
        <text x={(bx1 + bx2) / 2} y={baseY - amp - 84} fill="#B84DFF" fontSize="15" fontFamily="monospace" fontWeight="bold" textAnchor="middle">
          势垒 V₀
        </text>

        {/* Incident wave (left of barrier) */}
        <path d={sample(plotX0, bx1)} fill="none" stroke="#00F0FF" strokeWidth="3" filter="url(#wfGlow)" />

        {/* Exponential envelope inside the barrier (dashed) */}
        <path
          d={`M ${bx1},${baseY - amp} ${Array.from({length: 24}, (_, i) => {
            const x = bx1 + ((i + 1) / 24) * barrierW;
            return `L ${x.toFixed(1)},${(baseY - envelope(x)).toFixed(1)}`;
          }).join(' ')}`}
          fill="none"
          stroke="#B84DFF"
          strokeWidth="2"
          strokeDasharray="6 5"
        />
        <path
          d={`M ${bx1},${baseY + amp} ${Array.from({length: 24}, (_, i) => {
            const x = bx1 + ((i + 1) / 24) * barrierW;
            return `L ${x.toFixed(1)},${(baseY + envelope(x)).toFixed(1)}`;
          }).join(' ')}`}
          fill="none"
          stroke="#B84DFF"
          strokeWidth="2"
          strokeDasharray="6 5"
        />
        {/* Decaying oscillation inside the barrier */}
        <path d={sample(bx1, bx2)} fill="none" stroke="rgba(0, 240, 255, 0.55)" strokeWidth="2.5" />

        {/* Transmitted wave (right of barrier) */}
        <path d={sample(bx2, plotX1)} fill="none" stroke="#00F0FF" strokeWidth="3" filter="url(#wfGlow)" opacity="0.85" />

        {/* Probability packet riding the wave */}
        <g opacity={inBarrier ? 0.5 : 1}>
          <circle cx={packetX} cy={baseY - waveY(packetX)} r={22} fill="#00F0FF" opacity="0.25" filter="url(#wfGlow)" />
          <circle cx={packetX} cy={baseY - waveY(packetX)} r={9} fill="#00F0FF" />
          <circle cx={packetX - 2} cy={baseY - waveY(packetX) - 2} r={3} fill="#FFFFFF" />
        </g>

        {/* Wave labels */}
        <text x={plotX0 + 12} y={baseY - amp - 26} fill="#00F0FF" fontSize="14" fontFamily="monospace" fontWeight="bold">
          入射波 ψ_in
        </text>
        <text x={(bx1 + bx2) / 2 + 10} y={baseY + amp + 62} fill="#B84DFF" fontSize="13" fontFamily="monospace" textAnchor="middle">
          指数衰减 e^(−κx)
        </text>
        <text x={plotX1 - 12} y={baseY + transmittedAmp + 48} fill="rgba(0, 240, 255, 0.85)" fontSize="14" fontFamily="monospace" textAnchor="end">
          透射波 ψ_trans
        </text>

        {/* Key insight strip */}
        <g transform={`translate(40, ${height - 155})`}>
          <rect width={width - 80} height="52" rx="10" fill="rgba(0, 240, 255, 0.08)" stroke="rgba(0, 240, 255, 0.3)" strokeWidth="1" />
          <text x={24} y={32} fill="#FFFFFF" fontSize="15" fontFamily="monospace">
            ● 波函数在墙内指数衰减，但永不到零 → 粒子有概率出现在另一侧
          </text>
        </g>

        {/* Holographic header */}
        <g stroke="rgba(0, 240, 255, 0.4)" strokeWidth="1.5">
          <path d="M 30,52 L 30,32 L 50,32" fill="none" />
          <path d={`M ${width - 30},52 L ${width - 30},32 L ${width - 50},32`} fill="none" />
        </g>
        <text x="50" y="58" fill="rgba(0, 240, 255, 0.8)" fontSize="13" fontFamily="monospace" letterSpacing="0.1em">
          WAVEFUNCTION THROUGH BARRIER // ψ DECAYS, NEVER ZERO
        </text>
      </svg>
    </div>
  );
};

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

  type Item = {frame: number; text: string; hl?: string; size?: number};
  const items: Item[] = Array.isArray(params.items) ? (params.items as unknown as Item[]) : [];
  const size = num(params.size, 92);
  const hlColor = typeof params.hlColor === 'string' ? params.hlColor : '#FFB84D';

  const current = [...items].reverse().find((it) => frame >= it.frame);
  if (!current) return null;
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
