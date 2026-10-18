import {loadFont as loadBaloo} from '@remotion/google-fonts/BalooPaaji2';
import {loadFont as loadHind} from '@remotion/google-fonts/Hind';
import {staticFile} from 'remotion';
import manifest from './manifest.json';
import timing from './timing.json';

// Phulkari palette, same tokens as parali-setu-frontend/shared/tokens.css
export const C = {
  madder: '#8e1f33',
  madderDeep: '#6f1626',
  silk: '#e08a1e',
  silkPale: '#f6dfb8',
  khaddar: '#f6f1ec',
  surface: '#fffdfb',
  ink: '#2a1a1f',
  inkSoft: '#6d5a5d',
  line: '#e3d6cf',
  ok: '#2f6b3b',
  fire: '#c2410c',
};

const baloo = loadBaloo('normal', {weights: ['500', '600', '700', '800'], subsets: ['latin', 'gurmukhi']});
const hind = loadHind('normal', {weights: ['400', '500', '600'], subsets: ['latin']});
export const F = {display: baloo.fontFamily, body: hind.fontFamily};

export const FPS = timing.fps;
export const has = (p: string) => Boolean((manifest as Record<string, boolean>)[p]);
export const pub = (p: string) => staticFile(p);

// The bagh band from the product's CSS (madder ground, silk and pale-silk diamonds).
export const BAGH = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='28' height='14' viewBox='0 0 28 14'%3E%3Crect width='28' height='14' fill='%238e1f33'/%3E%3Cpath d='M7 1 13 7 7 13 1 7Z' fill='%23e08a1e'/%3E%3Cpath d='M21 1 27 7 21 13 15 7Z' fill='%23f6dfb8'/%3E%3Crect x='5.5' y='5.5' width='3' height='3' fill='%238e1f33'/%3E%3Crect x='19.5' y='5.5' width='3' height='3' fill='%238e1f33'/%3E%3C/svg%3E")`;
