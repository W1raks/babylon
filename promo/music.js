/* Музыка к промо «Вавилона»: синтезируется в OfflineAudioContext, все удары стоят на событиях кадра.
   Ля минор, 120 BPM (доля 0,5 с, такт 2 с): Am – F – C – G. Под голосом музыка приглушается. */
const mtof = m => 440 * Math.pow(2, (m - 69) / 12);

function renderMusic(sr) {
  const o = new OfflineAudioContext(2, Math.round(sr * DUR), sr);
  const master = o.createGain();
  master.gain.setValueAtTime(0, 0); master.gain.linearRampToValueAtTime(1, .25);
  master.gain.setValueAtTime(1, 50.2); master.gain.linearRampToValueAtTime(0, 51.95);
  const comp = o.createDynamicsCompressor();
  comp.threshold.value = -16; comp.ratio.value = 4; comp.attack.value = .005; comp.release.value = .2;
  const lim = o.createDynamicsCompressor();
  lim.threshold.value = -3; lim.knee.value = 0; lim.ratio.value = 20; lim.attack.value = .001; lim.release.value = .1;
  const trim = o.createGain(); trim.gain.value = .75;
  master.connect(comp); comp.connect(trim); trim.connect(lim); lim.connect(o.destination);

  const rev = o.createConvolver();
  const ir = o.createBuffer(2, sr * 3, sr);
  for (let c = 0; c < 2; c++) { const d = ir.getChannelData(c); for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / d.length, 3); }
  rev.buffer = ir;
  const revOut = o.createGain(); revOut.gain.value = .4; rev.connect(revOut); revOut.connect(master);
  const send = (node, amount) => { const g = o.createGain(); g.gain.value = amount; node.connect(g); g.connect(rev); };

  // музыкальная шина приглушается под голос
  const bus = o.createGain(); bus.connect(master); send(bus, .28);
  for (const [a, b] of VO) { bus.gain.setValueAtTime(1, a - .25); bus.gain.linearRampToValueAtTime(.62, a - .05); bus.gain.setValueAtTime(.62, b + .05); bus.gain.linearRampToValueAtTime(1, b + .35); }
  const fx = o.createGain(); fx.connect(master); send(fx, .45);
  const pump = o.createGain(); pump.connect(bus);

  const nb = o.createBuffer(1, sr * 2, sr);
  { const d = nb.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1; }

  const env = (t, a, peak, dur, dest, curve = 'exp') => {
    const g = o.createGain(), p = g.gain;
    if (curve === 'rise') { p.setValueAtTime(.0001, t); p.exponentialRampToValueAtTime(peak, t + dur); p.linearRampToValueAtTime(0, t + dur + .03); }
    else if (curve === 'hold') { p.setValueAtTime(0, t); p.linearRampToValueAtTime(peak, t + a); p.setValueAtTime(peak, t + Math.max(a, dur * .7)); p.linearRampToValueAtTime(0, t + dur); }
    else { p.setValueAtTime(.0001, t); p.exponentialRampToValueAtTime(peak, t + a); p.exponentialRampToValueAtTime(.0001, t + dur); }
    g.connect(dest); return g;
  };
  const osc = (type, f, t, dur, dest, x = {}) => {
    const s = o.createOscillator(); s.type = type; s.frequency.setValueAtTime(f, t);
    if (x.to) s.frequency.exponentialRampToValueAtTime(x.to, t + (x.glide ?? dur));
    if (x.detune) s.detune.value = x.detune;
    s.connect(dest); s.start(t); s.stop(t + dur + .05);
  };
  const noise = (t, dur, dest, x = {}) => {
    const s = o.createBufferSource(); s.buffer = nb; s.loop = true;
    const fl = o.createBiquadFilter(); fl.type = x.type ?? 'bandpass'; fl.Q.value = x.q ?? 1;
    fl.frequency.setValueAtTime(x.f ?? 1000, t); if (x.to) fl.frequency.exponentialRampToValueAtTime(x.to, t + dur);
    const pn = o.createStereoPanner(); pn.pan.setValueAtTime(x.pan ?? 0, t);
    if (x.panTo !== undefined) pn.pan.linearRampToValueAtTime(x.panTo, t + dur);
    const g = env(t, x.a ?? .003, x.gain ?? .2, dur, pn, x.curve);
    s.connect(fl); fl.connect(g); pn.connect(dest);
    s.start(t, rnd(t * 7) * 1.5); s.stop(t + dur + .05);
  };
  const bell = (t, m, gain) => [[1, 1], [2.76, .4], [5.4, .18]].forEach(([r, a]) => osc('sine', mtof(m) * r, t, 1.6 / r, env(t, .002, gain * a, 1.6 / r, fx)));
  const kick = (t, gain = .9, duckIt = true) => {
    osc('sine', 155, t, .42, env(t, .002, gain, .42, master), { to: 43, glide: .12 });
    noise(t, .02, master, { type: 'highpass', f: 2500, gain: .1 * gain });
    if (duckIt) { pump.gain.setValueAtTime(.35, t); pump.gain.linearRampToValueAtTime(1, t + .3); }
  };
  const boom = (t, gain) => {
    osc('sine', 80, t, 2.2, env(t, .003, gain, 2.2, fx), { to: 26, glide: 1.3 });
    noise(t, 1.2, fx, { type: 'lowpass', f: 5000, to: 140, gain: .45 });
  };
  const whoosh = (t, dur = .5, gain = .25) => noise(t - dur, dur + .1, fx, { f: 400, to: 6000, q: 1.2, gain, curve: 'rise', pan: -.6, panTo: .6 });
  const hit = (t, gain = 1) => { kick(t, gain, false); boom(t, .5 * gain); noise(t, .35, fx, { f: 1800, q: .7, gain: .35 * gain }); };
  const blip = (t, m = 88, g = .12) => { osc('sine', mtof(m), t, .14, env(t, .002, g, .14, fx)); osc('sine', mtof(m + 7), t + .05, .14, env(t + .05, .002, g * .7, .14, fx)); };
  const click = (t, g = .25) => { noise(t, .03, fx, { type: 'highpass', f: 3000, gain: g }); osc('sine', 900, t, .04, env(t, .001, g * .4, .04, fx), { to: 300 }); };

  // гармония: Am – F – C – G
  const CH = [[57, 60, 64, 69], [53, 57, 60, 65], [55, 60, 64, 67], [55, 59, 62, 67]];
  const ROOT = [45, 41, 48, 43];
  const chordAt = t => CH[Math.floor(t / 2) % 4];
  const inSec = (t, secs) => secs.some(([a, b]) => t >= a && t < b);

  // пэд на всю длину, фильтр открывается по сценам
  const padF = o.createBiquadFilter(); padF.type = 'lowpass'; padF.Q.value = .7; padF.connect(pump);
  [[0, 280], [3.9, 1400], [4.1, 500], [6.8, 2200], [10.5, 1100], [17.5, 2600], [27.5, 900], [34, 1500], [39, 2400], [46, 3000], [52, 400]]
    .forEach(([tt, f], i) => i ? padF.frequency.exponentialRampToValueAtTime(f, tt) : padF.frequency.setValueAtTime(f, tt));
  for (let b = 0; b < 23; b++) for (const m of CH[b % 4]) for (const d of [-8, 8])
    osc('sawtooth', mtof(m - 12), b * 2, 2.4, env(b * 2, .45, .028, 2.4, padF, 'hold'), { detune: d });

  // бас
  const GROOVE = [[7, 27.5], [34, 46]];
  const bassF = o.createBiquadFilter(); bassF.type = 'lowpass'; bassF.frequency.value = 480; bassF.Q.value = 3; bassF.connect(pump);
  for (let i = 28; i * .25 < 46; i++) {
    const t = i * .25; if (!inSec(t, GROOVE)) continue;
    const r = ROOT[Math.floor(t / 2) % 4] - 12, n = r + (i % 4 === 2 ? 12 : 0);
    osc('sawtooth', mtof(n), t, .2, env(t, .005, .13, .2, bassF));
    osc('sine', mtof(r), t, .23, env(t, .005, .2, .23, pump));
  }

  // арпеджио с дилеем
  const arpF = o.createBiquadFilter(); arpF.type = 'lowpass'; arpF.Q.value = 5; arpF.connect(bus);
  [[10.5, 1200], [17.5, 4200], [27.5, 1400], [34, 2600], [39, 5200], [46, 1500]]
    .forEach(([tt, f], i) => i ? arpF.frequency.exponentialRampToValueAtTime(f, tt) : arpF.frequency.setValueAtTime(f, tt));
  const dl = o.createDelay(1), fb = o.createGain(), dg = o.createGain();
  dl.delayTime.value = .375; fb.gain.value = .33; dg.gain.value = .38;
  arpF.connect(dl); dl.connect(fb); fb.connect(dl); dl.connect(dg); dg.connect(bus);
  const PAT = [0, 2, 1, 3, 2, 1, 3, 2];
  for (let i = 84; i * .125 < 46; i++) {
    const t = i * .125; let g = .06;
    if (t >= 27.5 && t < 34) { if (i % 2) continue; g = .045; } else if (t >= 17.5 && t < 27.5 || t >= 39) g = .075;
    osc('square', mtof(chordAt(t)[PAT[i % 8]] + 12), t, .16, env(t, .004, g, .16, arpF));
  }

  // ударные
  for (let t = 7; t < 17.5; t += 1) kick(t, .75);           // спокойно: 1 и 3
  for (let t = 17.5; t < 27.5; t += .5) kick(t);              // припев: каждую долю
  for (let t = 34; t < 39; t += 1) kick(t, .75);
  for (let t = 39.5; t < 45.3; t += .5) kick(t, .85);
  for (const [a, b, g] of [[10.5, 17.5, .04], [17.5, 27.5, .065], [34, 39, .04], [39, 45.3, .06]]) {
    for (let t = a + .25; t < b; t += .5) noise(t, .05, bus, { type: 'highpass', f: 8000, gain: g });
    if (g > .05) for (let t = a + .5; t < b; t += 1) noise(t, .18, bus, { f: 1900, q: .8, gain: .16 });
  }

  // 1. слова появляются — тихие «пики»
  for (let i = 0; i < 36; i++) { const t = .1 + i * .075; noise(t, .03, fx, { type: 'highpass', f: 3000 + rnd(i) * 4000, gain: .05, pan: rnd(i + 3) - .5 }); }
  for (let i = 0; i < 12; i++) blip(.5 + i * .16, 76 + (i % 4) * 3, .03);
  whoosh(4.1, 1.2, .3); osc('sawtooth', 110, 2.9, 1.2, env(2.9, 0, .04, 1.2, fx, 'rise'), { to: 660 });
  // 2. башня: ярус за ярусом
  for (let k = 0; k < 9; k++) { const t = 4.3 + k * .27; osc('sine', 70 + k * 9, t, .3, env(t, .002, .5, .3, fx), { to: 40, glide: .2 }); click(t, .08); }
  noise(5.4, 1.4, fx, { f: 300, to: 5000, q: 2, gain: .2, curve: 'rise' });
  boom(6.8, 1.1); bell(6.8, 81, .2); bell(6.85, 88, .14);
  bell(7.9, 76, .12); bell(8.5, 81, .08);
  // 3. выделение и клавиши
  whoosh(10.5, .5, .3);
  noise(11.4, .9, fx, { f: 1200, to: 3000, q: 3, gain: .06, curve: 'hold', a: .3 });
  [12.65, 12.82, 12.99].forEach(t => click(t, .4));
  whoosh(13.2, .25, .22); bell(13.2, 88, .14); bell(13.3, 93, .1);
  [13.5, 13.75, 14.0].forEach((t, i) => blip(t, 72 + i * 5, .06));
  // 4. живые субтитры
  boom(17.5, .9); whoosh(17.5, .5, .35);
  noise(18.3, .6, fx, { f: 2000, q: 2, gain: .05, curve: 'hold', a: .1 });
  click(19.0, .3); bell(19.0, 84, .1);
  [19.0, 21.0, 23.6, 26.2].forEach(t => blip(t, 91, .1));
  // 5. фото: сканер
  whoosh(27.5, .5, .3);
  noise(28.6, 2.0, fx, { f: 500, to: 7000, q: 6, gain: .12, curve: 'hold', a: .3, pan: -.7, panTo: .7 });
  bell(30.6, 81, .12);
  click(32.6, .25); click(33.2, .25);
  // 6. видео: прогресс и готовые файлы
  for (let i = 0; i < 26; i++) click(34.4 + i * .1, .05);
  bell(37.0, 84, .14); bell(37.08, 88, .1);
  blip(37.2, 79, .1); blip(37.45, 84, .1);
  // 7. факты — удары
  whoosh(39.0, .5, .3);
  [39.4, 41.05, 42.65, 43.95].forEach(t => hit(t, .9));
  [45.3, 45.36, 45.42, 45.48].forEach((t, i) => blip(t, 79 + i * 3, .07));
  // 8. финал
  boom(46.0, 1.2); bell(46.2, 81, .2); bell(46.2, 69, .15);
  const finF = o.createBiquadFilter(); finF.type = 'lowpass'; finF.connect(fx);
  finF.frequency.setValueAtTime(3000, 46); finF.frequency.exponentialRampToValueAtTime(400, 52);
  for (const m of [45, 57, 64, 69, 71, 72, 76, 81]) for (const d of [-7, 7])
    osc('sawtooth', mtof(m), 46.0, 5.9, env(46.0, .05, .028, 5.9, finF, 'hold'), { detune: d });
  bell(47.2, 76, .08); bell(48.0, 81, .06);

  return o.startRendering().then(buf => {
    // WAV 16 бит
    const ch = [buf.getChannelData(0), buf.getChannelData(1)], n = buf.length;
    const ab = new ArrayBuffer(44 + n * 4), v = new DataView(ab);
    const str = (p, s) => { for (let i = 0; i < s.length; i++) v.setUint8(p + i, s.charCodeAt(i)); };
    str(0, 'RIFF'); v.setUint32(4, 36 + n * 4, true); str(8, 'WAVE'); str(12, 'fmt ');
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 2, true); v.setUint32(24, sr, true);
    v.setUint32(28, sr * 4, true); v.setUint16(32, 4, true); v.setUint16(34, 16, true); str(36, 'data'); v.setUint32(40, n * 4, true);
    let p = 44;
    for (let i = 0; i < n; i++) for (let c = 0; c < 2; c++) { v.setInt16(p, Math.max(-1, Math.min(1, ch[c][i])) * 32767, true); p += 2; }
    let bin = ''; const u = new Uint8Array(ab);
    for (let i = 0; i < u.length; i += 0x8000) bin += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
    return btoa(bin);
  });
}
window.renderMusic = renderMusic;
