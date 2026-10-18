import React from 'react';
import {Composition} from 'remotion';
import {Demo} from './Demo';
import timing from './timing.json';

export const Root: React.FC = () => (
  <Composition id="ParaliSetuDemo" component={Demo} durationInFrames={timing.total} fps={timing.fps} width={1920} height={1080} />
);
