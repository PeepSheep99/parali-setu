import React from 'react';
import {AbsoluteFill, Audio, Img, interpolate, OffthreadVideo, Sequence, staticFile, useCurrentFrame} from 'remotion';
import {BAGH, C, F} from './theme';
import {sec, useIn} from './ui';

// LinkedIn ad: 1080x1080, 30 fps. Every number is from parali-setu-api/bench/RESULTS.md.
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const SCENES = [
  {at: 0, len: 4.5},    // hook: fire map
  {at: 4.5, len: 5.5},  // the sum
  {at: 10.0, len: 4.0}, // reveal
  {at: 14.0, len: 6.5}, // product
  {at: 20.5, len: 4.5}, // the rule
  {at: 25.0, len: 5.0}, // proof
  {at: 30.0, len: 4.5}, // outro
];
export const AD_FRAMES = sec(34.5);

// Dip through the ground: each scene fades in over 8 frames and out over 8.
const Dip: React.FC<{len: number; children: React.ReactNode; bg: string}> = ({len, children, bg}) => {
  const f = useCurrentFrame();
  const d = sec(len);
  const o = Math.min(interpolate(f, [0, 8], [0, 1], clamp), interpolate(f, [d - 8, d], [1, 0], clamp));
  return <AbsoluteFill style={{background: bg}}><AbsoluteFill style={{opacity: o}}>{children}</AbsoluteFill></AbsoluteFill>;
};

const Line: React.FC<{at: number; size: number; color: string; weight?: number; font?: string; children: React.ReactNode; style?: React.CSSProperties}> =
  ({at, size, color, weight = 800, font = F.display, children, style}) => {
    const a = useIn(at, 16);
    return <div style={{fontFamily: font, fontWeight: weight, fontSize: size, lineHeight: 1.08, color, ...a, ...style}}>{children}</div>;
  };

const Band: React.FC<{top?: number; bottom?: number}> = ({top, bottom}) => (
  <div style={{position: 'absolute', left: 0, right: 0, top, bottom, height: 22, backgroundImage: BAGH, backgroundSize: '44px 22px'}} />
);

// 1. Hook: the real 2024 fire map, square crop, slow push-in.
const Hook: React.FC = () => {
  const f = useCurrentFrame();
  const z = interpolate(f, [0, sec(4.5)], [1.25, 1.4]);
  return (
    <AbsoluteFill style={{background: '#14090c'}}>
      <OffthreadVideo src={staticFile('footage/s01_map.mp4')} muted startFrom={sec(5.2)}
        style={{position: 'absolute', height: 1080, width: 1920, left: -420, top: 0, objectFit: 'cover', transform: `scale(${z})`, transformOrigin: '50% 50%'}} />
      <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(20,9,12,.15) 30%, rgba(20,9,12,.85) 100%)'}} />
      <div style={{position: 'absolute', left: 70, right: 70, bottom: 90}}>
        <Line at={6} size={86} color="#fff6ef">Every winter,<br />Punjab's fields burn.</Line>
      </div>
    </AbsoluteFill>
  );
};

// 2. The farmer's sum.
const Sum: React.FC = () => (
  <AbsoluteFill style={{background: C.madder, padding: 80, justifyContent: 'center', gap: 70}}>
    <Band top={0} />
    <div>
      <Line at={4} size={40} color={C.silk} weight={700}>Clear the straw by machine</Line>
      <Line at={10} size={80} color={C.silkPale}>thousands of rupees<br />an acre.</Line>
    </div>
    <div>
      <Line at={sec(2.6)} size={40} color={C.silk} weight={700}>Strike a matchstick</Line>
      <Line at={sec(2.6) + 6} size={120} color="#fff6ef">nothing.</Line>
    </div>
    <Band bottom={0} />
  </AbsoluteFill>
);

// 3. Reveal.
const Reveal: React.FC = () => (
  <AbsoluteFill style={{background: C.madder, alignItems: 'center', justifyContent: 'center', textAlign: 'center'}}>
    <Img src={staticFile('assets/title_bg.png')} style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}} />
    <Line at={2} size={150} color={C.silkPale}>Parali Setu</Line>
    <Line at={10} size={52} color={C.silk} weight={600} style={{marginTop: 18}}><span lang="pa">ਪਰਾਲੀ ਨਾ ਸਾੜੋ, ਸਾਨੂੰ ਵੇਚੋ।</span></Line>
    <Line at={sec(1.2)} size={50} color="#fff6ef" weight={600} font={F.body} style={{marginTop: 46}}>We buy the straw before it burns.</Line>
  </AbsoluteFill>
);

// 4. The product: the live booking, offer card then booked, cropped to the chat column.
const Product: React.FC = () => {
  const f = useCurrentFrame();
  const swap = sec(3.3);
  const a = interpolate(f, [swap - 6, swap], [1, 0], clamp);
  const b = interpolate(f, [swap, swap + 6], [0, 1], clamp);
  return (
    <AbsoluteFill style={{background: C.khaddar}}>
      <div style={{position: 'absolute', left: 60, top: 230, width: 960, height: 790, borderRadius: 26, overflow: 'hidden',
        boxShadow: '0 40px 80px -40px rgba(42,26,31,.55)', border: `1px solid ${C.line}`, background: '#fff'}}>
        <OffthreadVideo src={staticFile('footage/s04_kisan_en.mp4')} muted playbackRate={1.25}
          style={{position: 'absolute', width: 1600 * 1.26, height: 900 * 1.26, left: -232 * 1.26, top: -150}} />
      </div>
      <div style={{position: 'absolute', left: 70, right: 70, top: 64, height: 150}}>
        <div style={{position: 'absolute', opacity: a}}>
          <Line at={4} size={64} color={C.madder}>Talk in Punjabi, Hindi<br />or English.</Line>
        </div>
        <div style={{position: 'absolute', opacity: b}}>
          <Line at={swap} size={64} color={C.madder}>Free pickup.<br />Paid the same day.</Line>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// 5. The rule.
const Rule: React.FC = () => (
  <AbsoluteFill style={{background: C.khaddar, padding: 80, justifyContent: 'center', gap: 56}}>
    <Band top={0} />
    <Line at={4} size={96} color={C.madder}>Gemini only talks.</Line>
    <Line at={sec(1.4)} size={96} color={C.ink}>Optimizers own every number.</Line>
    <Line at={sec(2.6)} size={36} color={C.inkSoft} weight={500} font={F.body}>Code checks every reply before a farmer sees it.</Line>
  </AbsoluteFill>
);

// 6. Proof: four tiles, one by one.
const STATS: [string, string][] = [
  ['40/40', 'simulated farmers booked'],
  ['0 / 181', 'replies with an unverified number'],
  ['12/12', 'trick conversations handled'],
  ['0.96', 'groundedness, Vertex AI evaluation'],
];
const Tile: React.FC<{at: number; big: string; small: string}> = ({at, big, small}) => {
  const a = useIn(at, 14);
  return (
    <div style={{background: C.surface, borderRadius: 24, padding: '34px 34px 30px', border: `1px solid ${C.line}`,
      boxShadow: '0 30px 60px -36px rgba(42,26,31,.5)', ...a}}>
      <div style={{fontFamily: F.display, fontWeight: 800, fontSize: 104, lineHeight: 1, color: C.madder}}>{big}</div>
      <div style={{fontFamily: F.body, fontWeight: 500, fontSize: 32, lineHeight: 1.2, color: C.ink, marginTop: 12}}>{small}</div>
    </div>
  );
};
const Proof: React.FC = () => (
  <AbsoluteFill style={{background: C.khaddar, padding: '70px 60px'}}>
    <Line at={2} size={52} color={C.ink}>Measured against real Gemini</Line>
    <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 26, marginTop: 44}}>
      {STATS.map(([big, small], i) => <Tile key={big} at={8 + i * 14} big={big} small={small} />)}
    </div>
  </AbsoluteFill>
);

// 7. Outro.
const Outro: React.FC = () => (
  <AbsoluteFill style={{background: C.madder, alignItems: 'center', justifyContent: 'center', textAlign: 'center'}}>
    <Img src={staticFile('assets/title_bg.png')} style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}} />
    <Line at={2} size={130} color={C.silkPale}>Parali Setu</Line>
    <Line at={8} size={36} color={C.silk} weight={700} style={{marginTop: 24}}>Google Cloud AI Builder Cup JAPAC 2026</Line>
    <Line at={14} size={34} color="#fff6ef" weight={500} font={F.body} style={{marginTop: 54}}>parali-setu-aibuildercup-2026.web.app</Line>
    <Line at={sec(1.3)} size={34} color={C.silkPale} weight={600} font={F.body} style={{marginTop: 40}}>Built by Sainath Chakravadhanula & Navneet Kumar</Line>
  </AbsoluteFill>
);

const PARTS: [React.FC, string][] = [[Hook, '#14090c'], [Sum, C.madder], [Reveal, C.madder], [Product, C.khaddar], [Rule, C.khaddar], [Proof, C.khaddar], [Outro, C.madder]];

export const LinkedInAd: React.FC = () => {
  const f = useCurrentFrame();
  const vol = Math.min(interpolate(f, [0, 15], [0, 0.55], clamp), interpolate(f, [AD_FRAMES - 36, AD_FRAMES], [0.55, 0], clamp));
  return (
    <AbsoluteFill style={{background: C.madder}}>
      {SCENES.map((s, i) => {
        const [Part, bg] = PARTS[i];
        return (
          <Sequence key={i} from={sec(s.at)} durationInFrames={sec(s.len)}>
            <Dip len={s.len} bg={bg}><Part /></Dip>
          </Sequence>
        );
      })}
      <Audio src={staticFile('audio/music_bed.wav')} startFrom={sec(6)} volume={vol} />
    </AbsoluteFill>
  );
};
