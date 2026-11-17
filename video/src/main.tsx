import React, {useRef} from 'react';
import {createRoot} from 'react-dom/client';
import {Player, type PlayerRef} from '@remotion/player';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {Preview, type PreviewData} from './Preview';
import '@fontsource/jetbrains-mono/latin-400.css';
import '@fontsource/jetbrains-mono/latin-700.css';
import '@fontsource/space-grotesk/latin-600.css';
import '@fontsource/space-grotesk/latin-700.css';

const WIDTH = 1080;
const HEIGHT = 1920;
const FPS = 60;

function Preflight() {
  const frame = useCurrentFrame();
  return <AbsoluteFill style={{background: '#0F1115', color: '#F4F2EC', alignItems: 'center', justifyContent: 'center', font: '64px monospace'}}>
    ARM64 · {String(frame).padStart(3, '0')}
  </AbsoluteFill>;
}

declare global {
  interface Window {
    seekFrame?: (frame: number) => Promise<void>;
  }
}

function App({data}: {data?: PreviewData}) {
  const player = useRef<PlayerRef>(null);
  window.seekFrame = async (frame) => {
    if (!player.current) throw Error('Lecteur vidéo non initialisé');
    player.current.seekTo(frame);
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  };
  const options = {ref: player, compositionWidth: WIDTH, compositionHeight: HEIGHT, fps: FPS, style: {width: WIDTH, height: HEIGHT}};
  return data ? <Player {...options} component={Preview} inputProps={{data}} durationInFrames={48 * FPS} />
    : <Player {...options} component={Preflight} durationInFrames={2 * FPS} />;
}

const preflight = new URL(location.href).searchParams.get('preflight') === '1';
const data = preflight ? undefined : await fetch('/out/video-data.json').then((res) => {
  if (!res.ok) throw Error('Générer video/out/video-data.json avec prepare_data.py');
  return res.json() as Promise<PreviewData>;
});
createRoot(document.getElementById('root')!).render(<App data={data} />);
