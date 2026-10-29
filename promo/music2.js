/* Музыка ко второму ролику (без голоса): спокойная электроника в духе продуктовых роликов.
   Ре минор, 110 BPM: Dm – B♭ – F – C. Удары и «вжухи» стоят на событиях кадра из promo2.html. */
const mtof = m => 440 * Math.pow(2, (m - 69) / 12);
const rnd = i => { const x = Math.sin(i * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };

function renderMusic(sr) {
  const o = new OfflineAudioContext(2, Math.round(sr * DUR), sr);
  const master = o.createGain();
  master.gain.setValueAtTime(0, 0); master.gain.linearRampToValueAtTime(1, .25);
  master.gain.setValueAtTime(1, 39.6); master.gain.linearRampToValueAtTime(0, 40.95);
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

  const B = 60 / 110, BAR = 4 * B;
  const CH = [[50, 53, 57, 62], [46, 50, 53, 58], [53, 57, 60, 65], [48, 52, 55, 60]];
  const ROOT = [38, 34, 41, 36];
  const chordAt = t => CH[Math.floor(t / BAR) % 4];

  // пэд: тихо в начале, раскрывается на логотипе и к финалу
  const padF = o.createBiquadFilter(); padF.type = 'lowpass'; padF.Q.value = .6; padF.connect(pump);
  [[0, 500], [4.0, 900], [6.3, 300], [6.95, 2600], [8.6, 1500], [33.6, 900], [37.4, 3200], [41, 600]]
    .forEach(([tt, f], i) => i ? padF.frequency.exponentialRampToValueAtTime(f, tt) : padF.frequency.setValueAtTime(f, tt));
  for (let b = 0; b * BAR < DUR; b++) for (const m of CH[b % 4]) for (const d of [-7, 7])
    osc('sawtooth', mtof(m - 12), b * BAR, BAR + .3, env(b * BAR, .6, .024, BAR + .3, padF, 'hold'), { detune: d });

  // бас и ритм — после логотипа; на «бесплатно» ритм стихает, на финале — аккорд
  const GROOVE = [[6.95, 33.6]];
  const inG = t => GROOVE.some(([a, b]) => t >= a && t < b);
  const bassF = o.createBiquadFilter(); bassF.type = 'lowpass'; bassF.frequency.value = 380; bassF.Q.value = 2.5; bassF.connect(pump);
  for (let t = 6.95; t < 33.6; t += B / 2) {
    const r = ROOT[Math.floor(t / BAR) % 4] - 12, n = r + (Math.round(t / (B / 2)) % 4 === 2 ? 12 : 0);
    osc('sawtooth', mtof(n), t, B / 2 * .85, env(t, .006, .1, B / 2 * .85, bassF));
    osc('sine', mtof(r), t, B / 2 * .9, env(t, .006, .17, B / 2 * .9, pump));
  }
  for (let t = 6.95; t < 33.6; t += B) kick(t, (t < 8.6 ? .55 : .75));
  for (let t = 6.95 + B / 2; t < 33.6; t += B) noise(t, .04, bus, { type: 'highpass', f: 8500, gain: .05 });
  for (let t = 6.95 + B; t < 33.6; t += 2 * B) noise(t, .16, bus, { f: 1900, q: .8, gain: .11 });

  // мягкое арпеджио
  const arpF = o.createBiquadFilter(); arpF.type = 'lowpass'; arpF.Q.value = 4; arpF.connect(bus);
  [[0, 1400], [6.95, 2600], [20.4, 3600], [33.6, 1800], [41, 1200]]
    .forEach(([tt, f], i) => i ? arpF.frequency.exponentialRampToValueAtTime(f, tt) : arpF.frequency.setValueAtTime(f, tt));
  const dl = o.createDelay(1), fb = o.createGain(), dg = o.createGain();
  dl.delayTime.value = B * .75; fb.gain.value = .32; dg.gain.value = .35;
  arpF.connect(dl); dl.connect(fb); fb.connect(dl); dl.connect(dg); dg.connect(bus);
  const PAT = [0, 2, 1, 3, 2, 1, 3, 2];
  for (let i = 0, t = 6.95; t < 37.4; i++, t += B / 4) {
    if (t >= 33.6 && i % 2) continue;
    osc('triangle', mtof(chordAt(t)[PAT[i % 8]] + 12), t, .2, env(t, .004, t >= 33.6 ? .04 : .055, .2, arpF));
  }

  // 1. переводчики появляются — колокольчики
  [.2, 1.1, 2.0, 2.9].forEach((t, i) => { bell(t, [74, 77, 81, 84][i], .14); noise(t, .5, fx, { f: 900, to: 3000, q: 2, gain: .04, curve: 'hold', a: .1 }); });
  noise(3.85, 1.3, fx, { f: 300, to: 2500, q: 1.5, gain: .1, curve: 'hold', a: .6 });
  // 2. круг сжимается, вспышка полосы, логотип
  osc('sine', 880, 5.55, .8, env(5.55, .05, .05, .8, fx, 'hold'), { to: 220, glide: .8 });
  noise(5.4, 1.0, fx, { f: 5000, to: 400, q: 3, gain: .09, curve: 'hold', a: .4 });
  whoosh(6.4, .35, .3);
  boom(6.95, 1.1); bell(6.95, 86, .18); bell(7.05, 81, .14);
  // 3. возможности: мягкий «вжух» на каждой смене сцены
  [8.6, 12.6, 16.8, 20.4, 24.2, 27.4, 30.6].forEach(t => { whoosh(t, .45, .2); bell(t + .05, 81 + (t % 3 > 1.5 ? 5 : 0), .06); });
  blip(9.65, 88, .08);
  noise(21.3, 1.7, fx, { f: 600, to: 6500, q: 5, gain: .09, curve: 'hold', a: .3, pan: -.6, panTo: .6 });
  bell(23.0, 86, .1);
  for (let i = 0; i < 7; i++) click(31.2 + i * .32, .14);
  // 4. «бесплатно…» — удар на каждую строку
  [34.0, 34.7, 35.4, 36.1].forEach((t, i) => { kick(t, .6 + i * .08, false); bell(t, [74, 77, 81, 86][i], .1); });
  // 5. финал
  boom(37.4, 1.0); bell(37.45, 86, .16); bell(37.45, 74, .12);
  const finF = o.createBiquadFilter(); finF.type = 'lowpass'; finF.connect(fx);
  finF.frequency.setValueAtTime(2800, 37.4); finF.frequency.exponentialRampToValueAtTime(500, 41);
  for (const m of [38, 50, 57, 62, 64, 65, 69, 74]) for (const d of [-7, 7])
    osc('sawtooth', mtof(m), 37.4, 3.6, env(37.4, .05, .026, 3.6, finF, 'hold'), { detune: d });

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
