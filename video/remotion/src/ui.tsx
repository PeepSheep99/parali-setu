import React from 'react';
import {AbsoluteFill, Img, interpolate, OffthreadVideo, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {BAGH, C, F, FPS, has, pub} from './theme';

export const sec = (s: number) => Math.round(s * FPS);
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

// Fade/slide in at a frame; used for labels that land on a narration cue.
export const useIn = (at: number, len = 14) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: f - at, fps, config: {damping: 200}, durationInFrames: len});
  return {opacity: s, transform: `translateY(${(1 - s) * 18}px)`};
};

export const fadeEdges = (f: number, dur: number, inLen = 10, outLen = 0) =>
  Math.min(interpolate(f, [0, inLen], [0, 1], clamp), outLen ? interpolate(f, [dur - outLen, dur], [1, 0], clamp) : 1);

export const Ground: React.FC<{children?: React.ReactNode; bg?: string}> = ({children, bg}) => (
  <AbsoluteFill style={{background: C.khaddar, fontFamily: F.body, color: C.ink}}>
    {bg && has(bg) ? <Img src={pub(bg)} style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}} /> : null}
    {children}
  </AbsoluteFill>
);

export const BaghBand: React.FC<{top?: number; bottom?: number; h?: number}> = ({top, bottom, h = 18}) => (
  <div style={{position: 'absolute', left: 0, right: 0, top, bottom, height: h, backgroundImage: BAGH, backgroundSize: `${h * 2}px ${h}px`}} />
);

// A browser window around a live-site recording.
export const Browser: React.FC<{
  src: string; url: string; x: number; y: number; w: number; startFrom?: number; zoom?: {scale: number; ox: number; oy: number};
  children?: React.ReactNode; style?: React.CSSProperties;
}> = ({src, url, x, y, w, startFrom = 0, zoom, children, style}) => {
  const h = (w * 900) / 1600;
  return (
    <div style={{position: 'absolute', left: x, top: y, width: w, borderRadius: 16, overflow: 'hidden', background: C.surface,
      boxShadow: '0 2px 0 rgba(42,26,31,.05), 0 30px 60px -30px rgba(42,26,31,.45)', border: `1px solid ${C.line}`, ...style}}>
      <div style={{height: 40, display: 'flex', alignItems: 'center', gap: 8, padding: '0 16px', background: '#efe6df', borderBottom: `1px solid ${C.line}`}}>
        {[C.madder, C.silk, C.silkPale].map((c) => <span key={c} style={{width: 12, height: 12, borderRadius: 6, background: c}} />)}
        <span style={{marginLeft: 14, flex: 1, height: 26, borderRadius: 13, background: C.surface, color: C.inkSoft, fontSize: 16,
          display: 'flex', alignItems: 'center', padding: '0 14px'}}>{url}</span>
      </div>
      <div style={{position: 'relative', width: w, height: h, overflow: 'hidden'}}>
        {has(src) ? (
          <OffthreadVideo src={pub(src)} startFrom={startFrom} muted
            style={{width: w, height: h, transformOrigin: zoom ? `${zoom.ox * 100}% ${zoom.oy * 100}%` : undefined,
              transform: zoom ? `scale(${zoom.scale})` : undefined}} />
        ) : (
          <div style={{width: w, height: h, display: 'grid', placeItems: 'center', color: C.inkSoft, fontSize: 28, background: '#f3ece6'}}>
            recording pending: {src}
          </div>
        )}
        {children}
      </div>
    </div>
  );
};

export const Chip: React.FC<{at: number; children: React.ReactNode; tone?: 'madder' | 'silk' | 'light' | 'ok'; size?: number; style?: React.CSSProperties}> = ({at, children, tone = 'madder', size = 26, style}) => {
  const a = useIn(at);
  const bg = {madder: C.madder, silk: C.silk, light: C.surface, ok: C.ok}[tone];
  const fg = tone === 'light' ? C.ink : '#fff6ef';
  return (
    <div style={{display: 'inline-flex', alignItems: 'center', gap: 10, padding: `${size * 0.4}px ${size * 0.8}px`, borderRadius: 999,
      background: bg, color: fg, fontFamily: F.display, fontWeight: 600, fontSize: size, lineHeight: 1.1,
      boxShadow: tone === 'light' ? `inset 0 0 0 1.5px ${C.line}, 0 10px 24px -16px rgba(42,26,31,.5)` : '0 10px 24px -14px rgba(42,26,31,.6)', ...a, ...style}}>
      {children}
    </div>
  );
};

export const Kicker: React.FC<{at?: number; children: React.ReactNode; x: number; y: number}> = ({at = 4, children, x, y}) => {
  const a = useIn(at);
  return (
    <div style={{position: 'absolute', left: x, top: y, fontFamily: F.display, fontWeight: 700, fontSize: 30, color: C.madder,
      letterSpacing: 0.3, display: 'flex', alignItems: 'center', gap: 14, ...a}}>
      <span style={{width: 16, height: 16, background: C.silk, transform: 'rotate(45deg)'}} />
      {children}
    </div>
  );
};
