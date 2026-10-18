import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile} from 'remotion';
import timing from './timing.json';
import * as Scenes from './Scenes';

// Each scene starts exactly where its narration clip starts and lasts clip + pad (timing.json,
// built by build/make_timing_v6.py, which also names each scene's component and audio file).
// Background music (Lyria on Vertex AI, looped): kept far under the voice, rising a little in the pauses.
const UNDER = 0.14, GAP = 0.35, RAMP = 9;
const speaking = timing.scenes.map((s) => [s.from, s.from + Math.round(s.audioSec * timing.fps)]);
const musicVolume = (f: number) => {
  const near = Math.min(...speaking.map(([a, b]) => (f >= a && f <= b ? 0 : f < a ? a - f : f - b)));
  return UNDER + (GAP - UNDER) * Math.min(1, near / RAMP);
};

export const Demo: React.FC = () => (
  <AbsoluteFill style={{background: '#f6f1ec'}}>
    <Audio src={staticFile('audio/music_bed.wav')} volume={musicVolume} />
    {timing.scenes.map((s) => {
      const Scene = (Scenes as unknown as Record<string, React.FC<{dur: number}>>)[s.scene];
      return (
        <Sequence key={s.id} from={s.from} durationInFrames={s.dur} name={`Scene ${s.id} · ${s.scene}`}>
          <Scene dur={s.dur} />
          <Audio src={staticFile(`audio/${s.audio}`)} />
        </Sequence>
      );
    })}
  </AbsoluteFill>
);
