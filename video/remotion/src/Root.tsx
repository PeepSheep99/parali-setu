import React from 'react';
import {Composition} from 'remotion';
import {Demo} from './Demo';
import {AD_FRAMES, LinkedInAd} from './LinkedInAd';
import timing from './timing.json';

export const Root: React.FC = () => (
  <>
    <Composition id="ParaliSetuDemo" component={Demo} durationInFrames={timing.total} fps={timing.fps} width={1920} height={1080} />
    <Composition id="LinkedInAd" component={LinkedInAd} durationInFrames={AD_FRAMES} fps={30} width={1080} height={1080} />
  </>
);
