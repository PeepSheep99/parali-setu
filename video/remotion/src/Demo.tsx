import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile} from 'remotion';
import timing from './timing.json';
import {S1, S2, S3, S4, S5, S6, S7, S8, S9, S10, S11, S12} from './Scenes';

const SCENES = [S1, S2, S3, S4, S5, S6, S7, S8, S9, S10, S11, S12];

// Each scene starts exactly where its narration clip starts and lasts clip + pad (timing.json).
export const Demo: React.FC = () => (
  <AbsoluteFill style={{background: '#f6f1ec'}}>
    {timing.scenes.map((s, i) => {
      const Scene = SCENES[i];
      return (
        <Sequence key={s.id} from={s.from} durationInFrames={s.dur} name={`Scene ${s.id}`}>
          <Scene dur={s.dur} />
          <Audio src={staticFile(`audio/s${String(s.id).padStart(2, '0')}.wav`)} />
        </Sequence>
      );
    })}
  </AbsoluteFill>
);
