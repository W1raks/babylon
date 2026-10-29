// Рендер промо-ролика: кадры canvas → ffmpeg, музыка из OfflineAudioContext → wav.
//   node render.js <url> preview <папка> 1.5 6 12 ...   — отдельные кадры png
//   node render.js <url> video <out.mp4> [fps]            — все кадры (без звука)
//   node render.js <url> music <out.wav>                  — музыка
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');

(async () => {
  const [url, mode, out, ...rest] = process.argv.slice(2);
  const browser = await chromium.launch({ args: ['--no-proxy-server'] });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  page.on('console', m => console.log('page:', m.text()));
  page.on('pageerror', e => console.log('page error:', e.message));
  await page.goto(url + (url.includes('?') ? '&' : '?') + 'render=1');
  await page.evaluate(() => window.ready);
  const canvas = (await page.$('#cv')) || (await page.$('#stage'));  // canvas или DOM-сцена
  if (mode === 'preview') {
    fs.mkdirSync(out, { recursive: true });
    for (const t of rest) {
      await page.evaluate(t => window.draw(t), +t);
      await canvas.screenshot({ path: `${out}/f_${(+t).toFixed(2)}.png` });
    }
  } else if (mode === 'video') {
    const fps = +(rest[0] || 60);
    const dur = await page.evaluate(() => DUR);
    const from = +(rest[1] || 0), to = +(rest[2] || dur);  // можно отрендерить только кусок
    const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-c:v', 'mjpeg', '-i', '-',
      '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-pix_fmt', 'yuv420p', '-r', String(fps), out], { stdio: ['pipe', 'inherit', 'inherit'] });
    const n = Math.round((to - from) * fps);
    const t0 = Date.now();
    for (let i = 0; i < n; i++) {
      await page.evaluate(t => window.draw(t), from + i / fps);
      const buf = await canvas.screenshot({ type: 'jpeg', quality: 95 });
      if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
      if (i % 300 === 0) console.log(`frame ${i}/${n} ${((Date.now() - t0) / 1000).toFixed(0)} s`);
    }
    ff.stdin.end();
    await new Promise(r => ff.on('close', r));
  } else if (mode === 'music') {
    const b64 = await page.evaluate(() => window.renderMusic(48000));
    fs.writeFileSync(out, Buffer.from(b64, 'base64'));
  }
  await browser.close();
})();
