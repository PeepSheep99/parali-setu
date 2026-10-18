import React from 'react';
import {AbsoluteFill, Img, interpolate, OffthreadVideo, Sequence, useCurrentFrame} from 'remotion';
import booking from './booking.json';
import {C, F, has, pub} from './theme';
import {BaghBand, Browser, Chip, Ground, Kicker, sec, useIn} from './ui';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
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
            <OffthreadVideo src={pub('assets/burning_fields.mp4')} muted style={{width: '100%', height: '100%', objectFit: 'cover', transform: 'scale(1.1)', transformOrigin: '30% 100%'}} />
            <Row x={80} y={940}><Chip at={sec(1.0)} tone="light">Punjab · October</Chip></Row>
          </AbsoluteFill>
        </Sequence>
      ) : null}
      <Sequence from={cut} durationInFrames={dur - cut}>
        <Ground>
          <BaghBand top={0} />
          <Browser src="footage/s01_map.mp4" url={`${SITE}/#map`} x={110} y={80} w={1700} />
          <Row x={150} y={960} gap={18}>
            <Chip at={burn ? 6 : sec(1.0)}>NASA FIRMS · 2024 season</Chip>
            <Chip at={sec(5.0) - cut + 6} tone="light">~2 weeks: rice → wheat</Chip>
            <Chip at={sec(9.4) - cut} tone="silk">₹2,500–4,000 / acre to clear</Chip>
          </Row>
        </Ground>
      </Sequence>
    </Ground>
  );
};

// 2. Title card.
export const S2: React.FC<P> = ({dur}) => {
  const baler = false;
  const rate = Math.min(1, (7.8 * 30) / dur);
  return (
    <AbsoluteFill style={{background: C.madder}}>
      {has('assets/title_bg.png') ? <Img src={pub('assets/title_bg.png')} style={{width: '100%', height: '100%', objectFit: 'cover'}} /> : <BaghBand bottom={0} h={40} />}
      {baler ? (
        <AbsoluteFill style={{opacity: 0.3, mixBlendMode: 'luminosity'}}>
          <OffthreadVideo src={pub('assets/baler_clear_sky.mp4')} muted playbackRate={rate} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
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

// 3-5: the ONE real v2 booking (typed Punjabi, 4 messages) recorded on the live farmer page.
const BK = booking as any;
const easeIO = (t: number) => t * t * (3 - 2 * t);

// English captions for the Punjabi conversation, timed to when each message or
// reply appears in the footage (raw recording marks / clip speed, make_clips.py).
type Line = [number, number, 'Farmer' | 'Assistant', string];
const OFFER_EN = "Gurpreet Singh ji, for Longowal, Sangrur, your straw is ₹0.76 per kg, ₹10,640 in total. Our team will come on Sunday, 18 October, 1–4 pm. Are your name, village and this time right, and do you agree?";
const S3_LINES: Line[] = [
  [1.9, 4.4, 'Farmer', 'Sat Sri Akal. I have 8 acres of paddy straw, village Longowal, Sangrur.'],
  [4.45, 6.5, 'Assistant', "Sat Sri Akal ji! I've noted your straw details. Please tell me your name, mobile number, and the date your field must be cleared by."],
  [6.55, 8.65, 'Farmer', 'I have to sow wheat on 28 October.'],
  [8.7, 10.85, 'Assistant', "I've noted the sowing date, 28 October. Please also tell me your name and mobile number."],
  [10.9, 14.1, 'Farmer', 'My name is Gurpreet Singh, number 9876543210.'],
  [14.15, 99, 'Assistant', OFFER_EN],
];
const S4_LINES: Line[] = [
  [0, 4.1, 'Assistant', OFFER_EN],
  [4.2, 7.9, 'Farmer', 'Yes ji, book it.'],
  [8.0, 99, 'Assistant', 'Your booking is done. Your booking code is PS-DE76. Our team will call you to confirm before coming to your field. Thank you!'],
];
const Subtitles: React.FC<{lines: Line[]; dur: number}> = ({lines, dur}) => {
  const f = useCurrentFrame();
  const cur = lines.find(([a, b]) => f >= sec(a) && f < Math.min(sec(b), dur));
  if (!cur) return null;
  const [a, b, who, text] = cur;
  const end = Math.min(sec(b), dur);
  const o = interpolate(f, [sec(a), sec(a) + 6, end - 6, end], [0, 1, 1, 0], clamp);
  return (
    <div style={{position: 'absolute', left: 60, width: 1500, bottom: 40, display: 'flex', justifyContent: 'center', opacity: o}}>
      <div style={{maxWidth: 1360, padding: '14px 26px', borderRadius: 14, background: 'rgba(42,26,31,.86)', color: '#fff6ef',
        fontFamily: F.body, fontSize: 30, lineHeight: 1.32, textAlign: 'center', boxShadow: '0 18px 40px -20px rgba(0,0,0,.6)'}}>
        <span style={{fontFamily: F.display, fontWeight: 700, color: who === 'Farmer' ? C.silk : C.silkPale, marginRight: 12}}>{who}:</span>
        {text}
      </div>
    </div>
  );
};

export const S3: React.FC<P> = ({dur}) => (
  <Ground>
    <BaghBand top={0} />
    <Browser src="footage/s03_kisan_v2.mp4" url={`${SITE}/kisan/`} x={60} y={90} w={1500} zoom={{scale: 1.12, ox: 0.3, oy: 0.62}} />
    <Subtitles lines={S3_LINES} dur={dur} />
    <Row x={1590} y={120} col gap={16}>
      <Chip at={sec(0.5)}>Live site</Chip>
      <Chip at={sec(1.3)} tone="light">typed in ਪੰਜਾਬੀ</Chip>
      <Chip at={sec(8.2)} tone="silk">Gemini · Vertex AI</Chip>
      <Chip at={sec(11.5)} tone="light">{`${BK.turns} messages`}</Chip>
      <Chip at={sec(0.5)} tone="light" size={19}>{`sped up ${BK.speed3}×`}</Chip>
    </Row>
  </Ground>
);

// 4. Offer card close-up, then the farmer's yes and the booked card (real time).
export const S4: React.FC<P> = ({dur}) => {
  const f = useCurrentFrame();
  const zin = interpolate(f, [0, sec(1.0)], [0, 1], {...clamp, easing: easeIO});
  const zout = interpolate(f, [sec(5.6), sec(6.6)], [0, 1], {...clamp, easing: easeIO});
  const scale = 1 + 0.6 * zin - 0.45 * zout;
  const oy = 0.53 + 0.1 * zout;
  const o = BK.offer || {};
  return (
    <Ground>
      <BaghBand top={0} />
      <Browser src="footage/s04_kisan_v2.mp4" url={`${SITE}/kisan/`} x={60} y={90} w={1500} zoom={{scale, ox: 0.33, oy}} />
      <Subtitles lines={S4_LINES} dur={dur} />
      <Row x={1590} y={120} col gap={16}>
        <Chip at={sec(1.2)} tone="silk">{o.price}</Chip>
        <Chip at={sec(2.2)}>{`${o.payout} payout`}</Chip>
        <Chip at={sec(3.4)} tone="light" size={22}>before sowing</Chip>
        <Chip at={sec(BK.booked_in_s4)} tone="ok">{`Booked · ${BK.code}`}</Chip>
      </Row>
    </Ground>
  );
};

// 5. One number, two places: the agent's words and the optimizer's offer card, price and payout highlighted in both.
const Shot: React.FC<{shot: any; file: string; x: number; y: number; w: number; hlAt: number[]; title: string; titleAt: number}> = ({shot, file, x, y, w, hlAt, title, titleAt}) => {
  const f = useCurrentFrame();
  const a = useIn(titleAt);
  if (!shot || !has(`shots/${file}`)) return null;
  const k = w / shot.w;
  return (
    <div style={{position: 'absolute', left: x, top: y, width: w, ...a}}>
      <div style={{fontFamily: F.display, fontWeight: 700, fontSize: 30, color: C.madder, marginBottom: 14}}>{title}</div>
      <div style={{position: 'relative', width: w, height: shot.h * k, borderRadius: 18, overflow: 'hidden',
        boxShadow: '0 30px 60px -30px rgba(42,26,31,.45)', border: `1px solid ${C.line}`, background: C.surface}}>
        <Img src={pub(`shots/${file}`)} style={{width: w, height: shot.h * k, display: 'block'}} />
        {(shot.hl || []).map((r: any, i: number) => {
          const at = hlAt[i] ?? hlAt[hlAt.length - 1];
          const p = interpolate(f, [at, at + 10], [0, 1], clamp);
          return <div key={i} style={{position: 'absolute', left: r.x * k - 6, top: r.y * k - 4, width: (r.w * k + 12) * p, height: r.h * k + 8,
            background: 'rgba(224,138,30,.30)', boxShadow: `inset 0 0 0 3px ${C.silk}`, borderRadius: 8}} />;
        })}
      </div>
    </div>
  );
};
export const S5: React.FC<P> = () => {
  const f = useCurrentFrame();
  const s = BK.shots || {};
  const line = interpolate(f, [sec(7.3), sec(8.3)], [0, 1], clamp);
  // reply hl order in the file: [payout, price]; card: [payout, price]
  return (
    <Ground bg="assets/tech_bg.png">
      <BaghBand top={0} />
      <Kicker x={90} y={60} at={4}>One number, two places</Kicker>
      <Shot shot={s.reply} file="reply.png" x={90} y={170} w={860} hlAt={[sec(6.0), sec(5.2)]} title="Gemini's reply" titleAt={sec(2.9)} />
      <div style={{position: 'absolute', left: 90, top: 170 + 54 + (s.reply ? s.reply.h * (860 / s.reply.w) : 180) + 18, width: 860,
        fontFamily: F.body, fontSize: 25, lineHeight: 1.35, color: C.inkSoft || C.ink, fontStyle: 'italic', ...useIn(sec(3.4))}}>
        In English: “…your straw is ₹0.76 per kg, ₹10,640 in total…”
      </div>
      <Shot shot={s.card} file="card.png" x={1130} y={170} w={640} hlAt={[sec(6.4), sec(5.6)]} title="Optimizer's offer card" titleAt={sec(4.96)} />
      <div style={{position: 'absolute', left: 975, top: 420, width: 130, height: 6, borderRadius: 3, background: C.silk, transformOrigin: 'left', transform: `scaleX(${line})`}} />
      <div style={{position: 'absolute', left: 960, top: 440, width: 160, textAlign: 'center', fontFamily: F.display, fontWeight: 700, fontSize: 22, color: C.madder, opacity: line}}>checked in code</div>
      <Row x={90} y={950} gap={18}>
        <Chip at={sec(13.4)} tone="madder" size={30}>0 invented numbers · 181 replies</Chip>
        <Chip at={sec(14.2)} tone="light" size={24}>bench/RESULTS.md</Chip>
      </Row>
    </Ground>
  );
};

// 6-9. Ops and company recordings.
const FootageScene: React.FC<{src: string; url: string; chips: [number, string, any?][]; side?: React.ReactNode; w?: number; zoom?: {scale: number; ox: number; oy: number}}> = ({src, url, chips, side, w = 1700, zoom}) => (
  <Ground>
    <BaghBand top={0} />
    <Browser src={src} url={url} x={(1920 - w) / 2 - (side ? 200 : 0)} y={70} w={w} zoom={zoom} />
    <Row x={(1920 - w) / 2 - (side ? 200 : 0) + 40} y={1080 - 118} gap={18}>
      {chips.map(([at, label, tone]) => <Chip key={label} at={sec(at)} tone={tone || 'madder'}>{label}</Chip>)}
    </Row>
    {side}
  </Ground>
);

export const S6: React.FC<P> = () => (
  <Ground>
    <BaghBand top={0} />
    <Browser src="footage/s06_dispatch.mp4" url={`${SITE}/ops/`} x={40} y={100} w={1500} />
    <Row x={1570} y={130} col gap={16}>
      <Chip at={sec(3.3)} tone="light">Confirm by phone first</Chip>
      <Chip at={sec(7.9)}>Google OR-Tools</Chip>
      <Chip at={sec(11.6)} tone="silk">−13% km</Chip>
      <Chip at={sec(14.6)} size={24}>Fire nearby alert · Pub/Sub</Chip>
    </Row>
  </Ground>
);
export const S7: React.FC<P> = () => (
  <FootageScene src="footage/s07_forecast.mp4" url={`${SITE}/ops/#forecast`}
    chips={[[4.5, 'NASA FIRMS · 25 seasons', 'light'], [7.5, 'BigQuery · TimesFM'], [11.5, 'peak within 1 week', 'silk']]} />
);
const SatPair: React.FC<{name: string; label: string; burned: boolean; y: number; at: number; wipeAt: number; labelAt: number}> = ({name, label, burned, y, at, wipeAt, labelAt}) => {
  const f = useCurrentFrame();
  const a = useIn(at, 16);
  const w = interpolate(f, [wipeAt, wipeAt + 18], [0, 1], {...clamp, easing: (t) => t * t * (3 - 2 * t)});
  const S = 300;
  const tag = (t: string) => <div style={{position: 'absolute', left: 10, top: 10, padding: '3px 12px', borderRadius: 999, background: 'rgba(42,26,31,.7)', color: '#fff6ef', fontSize: 20}}>{t}</div>;
  return (
    <div style={{position: 'absolute', left: 1040, top: y, ...a}}>
      <div style={{fontFamily: F.display, fontWeight: 700, fontSize: 26, color: C.ink, marginBottom: 10}}>{name}</div>
      <div style={{display: 'flex', gap: 18}}>
        <div style={{position: 'relative', width: S, height: S, borderRadius: 14, overflow: 'hidden', border: `1px solid ${C.line}`}}>
          <Img src={pub(`assets/satellite/${name.toLowerCase()}_before.png`)} style={{width: S, height: S, objectFit: 'cover'}} />{tag('before')}
        </div>
        <div style={{position: 'relative', width: S, height: S, borderRadius: 14, overflow: 'hidden', border: `1px solid ${C.line}`, opacity: w}}>
          {/* The burn-scar map (dNBR, before vs after): the measure the field check uses; red = burned, field circled. */}
          <Img src={pub(`assets/satellite/${name.toLowerCase()}_${has(`assets/satellite/${name.toLowerCase()}_scar_map.png`) ? 'scar_map' : 'after'}.png`)} style={{width: S, height: S, objectFit: 'cover'}} />
          {tag(has(`assets/satellite/${name.toLowerCase()}_scar_map.png`) ? 'burn-scar map' : 'after')}
        </div>
        <div style={{alignSelf: 'center'}}><Chip at={labelAt} tone={burned ? 'madder' : 'ok'} size={26}>{label}</Chip></div>
      </div>
    </div>
  );
};
const SAT = ['sangrur_before', 'sangrur_after', 'karnal_before', 'karnal_after'].every((n) => has(`assets/satellite/${n}.png`));
export const S8: React.FC<P> = () => SAT ? (
  <Ground bg="assets/tech_bg.png">
    <BaghBand top={0} />
    <Kicker x={60} y={50} at={2}>Sentinel-2 · Google Earth Engine</Kicker>
    <Browser src="footage/s08_impact.mp4" url={`${SITE}/ops/#impact`} x={40} y={130} w={960} />
    <SatPair name="Sangrur" label="burn scar" burned y={120} at={sec(1.0)} wipeAt={sec(4.4)} labelAt={sec(6.4)} />
    <SatPair name="Karnal" label="no burn scar" burned={false} y={500} at={sec(2.0)} wipeAt={sec(5.0)} labelAt={sec(7.0)} />
    <Row x={60} y={940} gap={18}><Chip at={sec(8.5)} tone="light">a scar stays for weeks</Chip></Row>
  </Ground>
) : (
  <FootageScene src="footage/s08_impact.mp4" url={`${SITE}/ops/#impact`}
    chips={[[1.5, 'Earth Engine · Sentinel-2'], [6.5, 'burn scar (dNBR)', 'light']]} />
);
export const S9: React.FC<P> = ({dur}) => {
  const f = useCurrentFrame();
  const z = interpolate(f, [0, dur], [1.0, 1.08]);
  const a = useIn(sec(0.4), 18);
  return (
    <AbsoluteFill style={{background: C.khaddar}}>
      {has('assets/village_bales.png') ? <Img src={pub('assets/village_bales.png')} style={{width: '100%', height: '100%', objectFit: 'cover', transform: `scale(${z})`, transformOrigin: '70% 40%'}} /> : null}
      <Browser src="footage/s09_company.mp4" url={`${SITE}/company/`} x={70} y={190} w={1150} style={{opacity: a.opacity}} />
      <Row x={1260} y={760} col gap={16}>
        <Chip at={sec(0.8)}>Buyer portal</Chip>
        <Chip at={sec(2.6)} tone="light">pellet · biogas · power plants</Chip>
        <Chip at={sec(3.6)} tone="silk">month by month</Chip>
      </Row>
    </AbsoluteFill>
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
        <Sequence durationInFrames={sec(7.6)}><AbsoluteFill><OffthreadVideo src={pub('assets/baler_clear_sky.mp4')} muted style={{width: '100%', height: '100%', objectFit: 'cover'}} /></AbsoluteFill></Sequence>
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
        <div style={{position: 'absolute', left: 0, right: 0, bottom: 200, textAlign: 'center', fontFamily: F.body, fontSize: 24, color: C.silkPale,
          opacity: interpolate(f, [sec(8.3), sec(8.9)], [0, 0.9], clamp)}}>
          Made with Remotion, Veo and Nano Banana · Narration: Google Chirp 3 HD
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
