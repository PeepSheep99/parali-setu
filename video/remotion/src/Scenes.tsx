import React from 'react';
import {AbsoluteFill, Img, interpolate, OffthreadVideo, Sequence, useCurrentFrame} from 'remotion';
import booking from './booking.json';
import {C, F, has, pub} from './theme';
import {BaghBand, Browser, Chip, Ground, Kicker, sec, useIn} from './ui';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
const B = booking as any;
const SITE = 'parali-setu-aibuildercup-2026.web.app';
type P = {dur: number};

const Row: React.FC<{x: number; y: number; gap?: number; col?: boolean; children: React.ReactNode}> = ({x, y, gap = 16, col, children}) => (
  <div style={{position: 'absolute', left: x, top: y, display: 'flex', flexDirection: col ? 'column' : 'row', alignItems: 'flex-start', gap}}>{children}</div>
);

const Wordmark: React.FC<{at: number; size: number; color: string; tag: string}> = ({at, size, color, tag}) => {
  const a = useIn(at, 22);
  const b = useIn(at + 12, 22);
  return (
    <div style={{textAlign: 'center'}}>
      <div style={{fontFamily: F.display, fontWeight: 800, fontSize: size, lineHeight: 1, color, letterSpacing: -1, ...a}}>Parali Setu</div>
      <div lang="pa" style={{fontFamily: F.display, fontWeight: 600, fontSize: size * 0.36, color: tag, marginTop: size * 0.22, ...b}}>
        ਪਰਾਲੀ ਨਾ ਸਾੜੋ, ਸਾਨੂੰ ਵੇਚੋ।
      </div>
    </div>
  );
};

// 1. The fire season: aerial burning fields, then the real 2024 fire map from the landing page.
export const S1: React.FC<P> = ({dur}) => {
  const f = useCurrentFrame();
  const burn = has('assets/burning_fields.mp4');
  const cut = burn ? sec(4.98) : 0;
  return (
    <Ground>
      {burn ? (
        <Sequence durationInFrames={cut + 8}>
          <AbsoluteFill style={{opacity: interpolate(f, [cut - 2, cut + 8], [1, 0], clamp)}}>
            <OffthreadVideo src={pub('assets/burning_fields.mp4')} muted style={{width: '100%', height: '100%', objectFit: 'cover'}} />
            <Row x={80} y={940}><Chip at={sec(1.0)} tone="light">Punjab · October</Chip></Row>
          </AbsoluteFill>
        </Sequence>
      ) : null}
      <Sequence from={cut} durationInFrames={dur - cut}>
        <Ground>
          <BaghBand top={0} />
          <Browser src="footage/s01_map.mp4" url={`${SITE}/#map`} x={110} y={80} w={1700} />
          <Row x={150} y={960} gap={18}>
            <Chip at={sec(burn ? 0.4 : 2.5)}>NASA FIRMS · 2024 season</Chip>
            <Chip at={sec(2.442 - cut / 30 + (burn ? 2.5 : 0))} tone="light">~2 weeks: rice → wheat</Chip>
            <Chip at={sec(Math.max(0.8, 4.98 - cut / 30 + 0.6))} tone="silk">₹2,500–4,000 / acre to clear</Chip>
          </Row>
        </Ground>
      </Sequence>
    </Ground>
  );
};

// 2. Title card.
export const S2: React.FC<P> = () => {
  const baler = has('assets/baler_clear_sky.mp4');
  return (
    <AbsoluteFill style={{background: C.madder}}>
      {has('assets/title_bg.png') ? <Img src={pub('assets/title_bg.png')} style={{width: '100%', height: '100%', objectFit: 'cover'}} /> : <BaghBand bottom={0} h={40} />}
      {baler ? (
        <AbsoluteFill style={{opacity: 0.32, mixBlendMode: 'luminosity'}}>
          <OffthreadVideo src={pub('assets/baler_clear_sky.mp4')} muted style={{width: '100%', height: '100%', objectFit: 'cover'}} />
        </AbsoluteFill>
      ) : null}
      <AbsoluteFill style={{display: 'grid', placeItems: 'center', paddingBottom: 120}}>
        <Wordmark at={4} size={190} color={C.silkPale} tag={C.silk} />
      </AbsoluteFill>
      <div style={{position: 'absolute', left: 0, right: 0, top: 690, display: 'flex', justifyContent: 'center', gap: 22}}>
        <Chip at={sec(4.2)} tone="light">₹0 to clear</Chip>
        <Chip at={sec(6.6)} tone="light">paid same day</Chip>
        <Chip at={sec(9.4)} tone="light">12-month supply</Chip>
      </div>
    </AbsoluteFill>
  );
};

// 3. The real typed Punjabi booking on the live farmer page.
export const S3: React.FC<P> = () => (
  <Ground>
    <BaghBand top={0} />
    <Browser src="footage/s03_kisan.mp4" url={`${SITE}/kisan/`} x={60} y={70} w={1460} />
    <Row x={1550} y={110} col gap={18}>
      <Chip at={sec(0.5)}>Live site</Chip>
      <Chip at={sec(1.6)} tone="light">ਪੰਜਾਬੀ · typed</Chip>
      <Chip at={sec(7.5)} tone="silk">Gemini · Vertex AI</Chip>
      {B.turns ? <Chip at={sec(11)} tone="light">{B.turns.length} messages</Chip> : null}
      {B.speed3 > 1.2 ? <Chip at={sec(0.5)} tone="light" size={20}>{`sped up ${B.speed3.toFixed(1)}×`}</Chip> : null}
    </Row>
  </Ground>
);

// 4. The offer and the farmer's yes.
export const S4: React.FC<P> = ({dur}) => {
  const f = useCurrentFrame();
  const scale = interpolate(f, [0, dur * 0.45], [1, 1.32], {...clamp, easing: (t) => t * t * (3 - 2 * t)});
  const o = B.offer || {};
  return (
    <Ground>
      <BaghBand top={0} />
      <Browser src="footage/s04_kisan.mp4" url={`${SITE}/kisan/`} x={60} y={70} w={1460} zoom={{scale, ox: 0.39, oy: 0.85}} />
      <Row x={1550} y={110} col gap={18}>
        {o.price ? <Chip at={sec(1.6)} tone="silk">{o.price}</Chip> : null}
        {o.payout ? <Chip at={sec(3.0)}>{o.payout}</Chip> : null}
        {o.slot ? <Chip at={sec(4.6)} tone="light" size={22}>{o.slot}</Chip> : null}
        <Chip at={sec(Math.max(1, (B.marks?.booked_in_s4 ?? 9.5)))} tone="ok">Booked ✓</Chip>
        {B.speed4 > 1.2 ? <Chip at={sec(0.3)} tone="light" size={20}>{`sped up ${B.speed4.toFixed(1)}×`}</Chip> : null}
      </Row>
    </Ground>
  );
};

// 5. One number, two places: the agent's words and the optimizer's offer card.
const Shot: React.FC<{shot: any; x: number; y: number; w: number; hlAt: number; title: string; titleAt: number}> = ({shot, x, y, w, hlAt, title, titleAt}) => {
  const f = useCurrentFrame();
  const a = useIn(titleAt);
  if (!shot || !has(`shots/${shot.file}`)) return null;
  const k = w / shot.w;
  const p = interpolate(f, [hlAt, hlAt + 12], [0, 1], clamp);
  return (
    <div style={{position: 'absolute', left: x, top: y, width: w}}>
      <div style={{fontFamily: F.display, fontWeight: 700, fontSize: 30, color: C.madder, marginBottom: 16, ...a}}>{title}</div>
      <div style={{position: 'relative', width: w, height: shot.h * k, borderRadius: 18, overflow: 'hidden',
        boxShadow: '0 30px 60px -30px rgba(42,26,31,.45)', border: `1px solid ${C.line}`, background: C.surface}}>
        <Img src={pub(`shots/${shot.file}`)} style={{width: w, height: shot.h * k}} />
        {(shot.hl || []).map((r: any, i: number) => (
          <div key={i} style={{position: 'absolute', left: r.x * k - 6, top: r.y * k - 4, width: (r.w * k + 12) * p, height: r.h * k + 8,
            background: 'rgba(224,138,30,.30)', boxShadow: `inset 0 0 0 3px ${C.silk}`, borderRadius: 8}} />
        ))}
      </div>
    </div>
  );
};

export const S5: React.FC<P> = () => {
  const f = useCurrentFrame();
  const s = B.shots || {};
  const line = interpolate(f, [sec(7.3), sec(8.3)], [0, 1], clamp);
  return (
    <Ground bg="assets/tech_bg.png">
      <BaghBand top={0} />
      <Kicker x={90} y={60} at={4}>One number, two places</Kicker>
      <Shot shot={s.reply} x={90} y={150} w={820} hlAt={sec(5.2)} title="Gemini's reply" titleAt={sec(2.9)} />
      <Shot shot={s.card} x={1090} y={150} w={620} hlAt={sec(5.6)} title="Optimizer's offer" titleAt={sec(4.96)} />
      <div style={{position: 'absolute', left: 940, top: 470, width: 120, height: 6, borderRadius: 3, background: C.silk,
        transformOrigin: 'left', transform: `scaleX(${line})`}} />
      <div style={{position: 'absolute', left: 925, top: 495, width: 150, textAlign: 'center', fontFamily: F.display, fontWeight: 700,
        fontSize: 22, color: C.madder, opacity: line}}>checked in code</div>
      <Row x={90} y={960} gap={18}>
        <Chip at={sec(13.4)} tone="madder" size={30}>0 invented numbers · 181 replies</Chip>
      </Row>
    </Ground>
  );
};

// 6-9. Ops and company recordings.
const FootageScene: React.FC<{src: string; url: string; chips: [number, string, any?][]; side?: React.ReactNode; w?: number}> = ({src, url, chips, side, w = 1700}) => (
  <Ground>
    <BaghBand top={0} />
    <Browser src={src} url={url} x={(1920 - w) / 2 - (side ? 200 : 0)} y={70} w={w} />
    <Row x={(1920 - w) / 2 - (side ? 200 : 0) + 40} y={1080 - 118} gap={18}>
      {chips.map(([at, label, tone]) => <Chip key={label} at={sec(at)} tone={tone || 'madder'}>{label}</Chip>)}
    </Row>
    {side}
  </Ground>
);

export const S6: React.FC<P> = () => (
  <FootageScene src="footage/s06_dispatch.mp4" url={`${SITE}/ops/`}
    chips={[[2.2, 'Confirm by phone first', 'light'], [6.6, 'Google OR-Tools'], [11.0, 'on-call crews as backup', 'light'], [15.2, '−13% km', 'silk']]} />
);
export const S7: React.FC<P> = () => (
  <FootageScene src="footage/s07_forecast.mp4" url={`${SITE}/ops/#forecast`}
    chips={[[4.5, 'NASA FIRMS · 25 seasons', 'light'], [7.5, 'BigQuery · TimesFM'], [11.5, 'peak within 1 week', 'silk']]} />
);
export const S8: React.FC<P> = () => (
  <FootageScene src="footage/s08_impact.mp4" url={`${SITE}/ops/#impact`}
    chips={[[1.5, 'Earth Engine · Sentinel-2'], [6.5, 'burn scar (dNBR)', 'light']]} />
);
export const S9: React.FC<P> = () => {
  const a = useIn(sec(0.3), 18);
  return (
    <FootageScene src="footage/s09_company.mp4" url={`${SITE}/company/`} w={1360}
      chips={[[0.6, 'Buyer portal'], [3.4, 'month by month', 'light']]}
      side={has('assets/village_bales.png') ? (
        <div style={{position: 'absolute', right: 40, top: 230, width: 520, borderRadius: 18, overflow: 'hidden', ...a,
          boxShadow: '0 30px 60px -30px rgba(42,26,31,.5)'}}>
          <Img src={pub('assets/village_bales.png')} style={{width: 520, height: 290, objectFit: 'cover'}} />
          <div style={{background: C.surface, padding: '14px 18px', fontFamily: F.display, fontWeight: 600, fontSize: 24, color: C.madder}}>
            Pellet · biogas · power plants
          </div>
        </div>
      ) : null} />
  );
};

// 10. Architecture on Google Cloud; each service lands as the voice names it.
const SERVICES: [number, string][] = [
  [2.85, 'Gemini · Vertex AI'], [6.13, 'Text-to-Speech'], [7.3, 'Speech-to-Text'], [9.25, 'Cloud Run'],
  [11.8, 'Firestore'], [12.7, 'BigQuery'], [14.05, 'Earth Engine'], [15.0, 'Maps Platform'], [15.6, 'Firebase Hosting'],
];
export const S10: React.FC<P> = () => {
  const a = useIn(4, 20);
  return (
    <Ground bg="assets/tech_bg.png">
      <BaghBand top={0} />
      <Kicker x={70} y={44} at={2}>Architecture</Kicker>
      <div style={{position: 'absolute', left: 60, top: 104, width: 1290, height: 942, borderRadius: 18, overflow: 'hidden', background: '#fff',
        boxShadow: '0 30px 60px -30px rgba(42,26,31,.45)', border: `1px solid ${C.line}`, ...a}}>
        <Img src={pub('img/architecture.png')} style={{width: 1290, height: 942}} />
      </div>
      <div style={{position: 'absolute', left: 1400, top: 104, display: 'flex', flexDirection: 'column', gap: 14}}>
        <Chip at={sec(0.6)} tone="madder" size={30}>Google Cloud</Chip>
        {SERVICES.map(([t, s]) => <Chip key={s} at={sec(t)} tone="light" size={27}>{s}</Chip>)}
        <Chip at={sec(9.6)} tone="silk" size={24}>OR-Tools optimizers</Chip>
      </div>
    </Ground>
  );
};

// 11. Measured results (bench/RESULTS.md).
const Stat: React.FC<{at: number; big: string; small: string}> = ({at, big, small}) => {
  const a = useIn(at, 16);
  return (
    <div style={{width: 400, padding: '26px 30px', borderRadius: 18, background: C.surface, border: `1px solid ${C.line}`,
      boxShadow: '0 30px 60px -34px rgba(42,26,31,.5)', ...a}}>
      <div style={{fontFamily: F.display, fontWeight: 800, fontSize: 88, lineHeight: 1, color: C.madder}}>{big}</div>
      <div style={{fontSize: 27, marginTop: 10, color: C.ink, lineHeight: 1.25}}>{small}</div>
    </div>
  );
};
export const S11: React.FC<P> = () => (
  <Ground bg="assets/tech_bg.png">
    <BaghBand top={0} />
    <Kicker x={90} y={60} at={2}>bench/RESULTS.md</Kicker>
    <Browser src="footage/s11_agent.mp4" url={`${SITE}/ops/#forecast`} x={90} y={140} w={880} style={{opacity: 0.95}} />
    <div style={{position: 'absolute', left: 1020, top: 140, display: 'grid', gridTemplateColumns: '400px 400px', gap: 26}}>
      <Stat at={sec(1.56)} big="40/40" small="simulated farmers booked" />
      <Stat at={sec(4.07)} big="0" small="invented numbers in 181 replies" />
      <Stat at={sec(6.29)} big="10/10" small="trick conversations handled" />
      <Stat at={sec(11.9)} big="0.96" small="groundedness · Vertex AI Gen AI Evaluation" />
    </div>
  </Ground>
);

// 12. Fires give way to booked farms; closing title.
export const S12: React.FC<P> = ({dur}) => {
  const f = useCurrentFrame();
  const t = sec(4.1);
  const green = interpolate(f, [sec(1.6), sec(2.6)], [0, 1], clamp);
  const title = interpolate(f, [t, t + 14], [0, 1], clamp);
  const out = interpolate(f, [dur - 18, dur], [1, 0], clamp);
  const baler = has('assets/baler_clear_sky.mp4');
  return (
    <AbsoluteFill style={{background: C.khaddar, opacity: out}}>
      {baler ? (
        <AbsoluteFill><OffthreadVideo src={pub('assets/baler_clear_sky.mp4')} muted style={{width: '100%', height: '100%', objectFit: 'cover'}} /></AbsoluteFill>
      ) : (
        <>
          <Browser src="footage/s12_fires.mp4" url={`${SITE}/#map`} x={110} y={80} w={1700} />
          <Browser src="footage/s12_firemap.mp4" url={`${SITE}/ops/#forecast`} x={110} y={80} w={1700} style={{opacity: green}} />
          <Row x={150} y={960}><Chip at={sec(2.0)} tone="ok">Booked farms</Chip></Row>
        </>
      )}
      <AbsoluteFill style={{opacity: title}}>
        {has('assets/title_bg.png') ? <Img src={pub('assets/title_bg.png')} style={{width: '100%', height: '100%', objectFit: 'cover'}} /> : <AbsoluteFill style={{background: C.madder}} />}
        <AbsoluteFill style={{display: 'grid', placeItems: 'center', paddingBottom: 140}}>
          <Wordmark at={t} size={170} color={C.silkPale} tag={C.silk} />
        </AbsoluteFill>
        <div style={{position: 'absolute', left: 0, right: 0, top: 700, textAlign: 'center', fontFamily: F.body, fontSize: 30, color: C.silkPale, opacity: 0.85}}>
          {SITE}/kisan/
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
