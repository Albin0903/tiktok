import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdir, readdir, access} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {finished} from 'node:stream/promises';
import {chromium} from 'playwright-core';
import {createServer} from 'vite';

const out = resolve('out');
const preflight = process.argv.includes('--preflight');
const browserPath = process.env.VIDEO_BROWSER ?? 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const tools = join(out, 'toolchain');
const defaultFfmpeg = async () => {
  const directory = (await readdir(tools)).find((name) => name.startsWith('ffmpeg-') && !name.endsWith('.zip'));
  if (!directory) throw Error('Renseigner FFMPEG_PATH avec ffmpeg.exe ARM64');
  return join(tools, directory, 'bin', 'ffmpeg.exe');
};
const ffmpeg = process.env.FFMPEG_PATH ?? await defaultFfmpeg();
await access(ffmpeg);
await mkdir(out, {recursive: true});
const server = await createServer({server: {host: '127.0.0.1', port: 0}});
await server.listen();
let browser;
let encoder;
try {
  browser = await chromium.launch({executablePath: browserPath, headless: true});
  const page = await browser.newPage({viewport: {width: 1080, height: 1920}, deviceScaleFactor: 1});
  const {port} = server.httpServer.address();
  await page.goto(`http://127.0.0.1:${port}/?preflight=${preflight ? 1 : 0}`);
  await page.waitForFunction(() => Boolean(window.seekFrame));
  const destination = join(out, preflight ? 'preflight_arm64.mp4' : 'test_plf2027_preview.mp4');
  encoder = spawn(ffmpeg, [
    '-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', '60', '-i', 'pipe:0',
    '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', destination,
  ], {stdio: ['pipe', 'inherit', 'inherit'], windowsHide: true});
  const exit = once(encoder, 'close');
  const sceneStarts = new Set([3, 16, 29, 42].map((seconds) => seconds * 60));
  let image;
  for (let frame = 0; frame < (preflight ? 120 : 48 * 60); frame++) {
    if (preflight || frame < 180 || sceneStarts.has(frame)) {
      await page.evaluate((n) => window.seekFrame(n), frame);
      image = await page.screenshot({type: 'jpeg', quality: 87});
    }
    if (!encoder.stdin.write(image)) await once(encoder.stdin, 'drain');
  }
  encoder.stdin.end();
  await finished(encoder.stdin);
  const [code] = await exit;
  if (code !== 0) throw Error(`FFmpeg a quitté avec le code ${code}`);
  console.log(destination);
} finally {
  if (encoder?.exitCode === null) encoder.kill();
  await browser?.close();
  await server.close();
}
