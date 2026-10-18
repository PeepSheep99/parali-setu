import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile} from 'remotion';
import timing from './timing.json';
import * as Scenes from './Scenes';

// Each scene starts exactly where its narration clip starts and lasts clip + pad (timing.json,
// built by build/make_timing_v6.py, which also names each scene's component and audio file).
export const Demo: React.FC = () => (
  <AbsoluteFill style={{background: '#f6f1ec'}}>
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
