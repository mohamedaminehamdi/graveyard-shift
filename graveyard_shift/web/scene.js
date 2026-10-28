// The graveyard. What is finished comes from a pure fold over the night's recorded steps (state = steps.reduce(apply)),
// and play() animates one step so that it ends exactly in that state. Scrubbing, skipping to dawn and reduced motion
// all just render a state, so the scene can never show something the ghosts didn't do.
const NS = 'http://www.w3.org/2000/svg';
const EASE = 'cubic-bezier(.45,0,.25,1)', OUT = 'cubic-bezier(.2,.8,.3,1)';
export const URNS = [['reply', 'Reply'], ['fyi', 'FYI'], ['newsletter', 'News'], ['suspicious', 'Possessed']];
export const GHOSTS = { keeper: 'The Keeper', mail: 'Mail ghost', files: 'Files ghost', calendar: 'Calendar ghost', code: 'Code ghost' };
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
export const pause = (ms) => new Promise((r) => setTimeout(r, ms));

function node(tag, attrs = {}, parent, text) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text != null) e.textContent = text;
  parent?.append(e);
  return e;
}
const clip = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
const rnd = (k) => ((Math.sin(k * 12.9898) * 43758.5453) % 1 + 1) % 1;   // the same scatter every time

// ---- the fold: what is finished after each step -------------------------------------------------------------
export function initial(inv, waits = false) {   // a real night starts with the ghosts in their graves
  return { inv, risen: !waits, mail: {}, files: {}, meetings: {}, forecast: null, plan: null, peeks: 0, model: null,
    tomb: { open: false, branch: '', lines: [], tests: null, sha: null, turns: 0 }, done: 0 };
}

export function apply(state, step) {
  const s = { ...state, done: state.done + 1, tomb: { ...state.tomb } };
  const r = step.result, id = step.target.split(':')[1];
  if (step.outcome !== 'done' || !r) return s;
  switch (step.act) {
    case 'triage_email': s.mail = { ...s.mail, [id]: r }; break;
    case 'read_file_item': s.files = { ...s.files, [id]: r }; break;
    case 'prep_meeting': s.meetings = { ...s.meetings, [id]: r }; break;
    case 'forecast_dawn': s.forecast = r; break;
    case 'check_sleep': s.peeks += 1; if (r.idle_min >= 20) s.risen = true; break;
    case 'choose_model': s.model = r.model; break;
    case 'open_worktree': Object.assign(s.tomb, { open: true, branch: r.branch, tests: r.baseline }); break;
    case 'run_tool':
      if (r.tool === 'write_file' && !s.tomb.lines.includes(r.path)) s.tomb.lines = [...s.tomb.lines, r.path];
      if (r.tool === 'run_tests') s.tomb.tests = r.passed;
      break;
    case 'commit_work': s.tomb.sha = r.sha || 'nothing to commit'; break;
    case 'llm_turn':
      if (r.plan) s.plan = r.plan;
      if (step.ghost === 'code') s.tomb.turns += 1;
      break;
  }
  return s;
}

// ---- layout: one composition for wide screens, one for phones ----------------------------------------------
function layout(portrait, inv) {
  const folders = [...new Set(inv.files.map((f) => f.folder.split('/')[0]))].slice(0, 3);
  if (!portrait) {
    const n = inv.events.length, gap = Math.min(78, 460 / Math.max(n, 1));
    return {
      W: 1200, H: 640, horizon: 318, moon: [150, 1050, 92, 230],
      tablets: inv.events.map((e, k) => [600 - ((n - 1) * gap) / 2 + k * gap, 322]),
      pile: [214, 470], cols: 7, urns: URNS.map((u, k) => [62 + k * 86, 604]),
      tomb: [600, 482], candle: [600, 608], keeper: [470, 580], trail: 'M1200 628C1060 600 900 640 800 616S700 612 690 612',
      crypts: folders.map((f, k) => [890 + k * 104, 500]),
      home: { mail: [350, 450], files: [880, 430], calendar: [600, 296], code: [716, 452], keeper: [470, 580] },
      sun: [1050, 318], folders,
    };
  }
  const n = inv.events.length, gap = Math.min(86, 520 / Math.max(n, 1));
  return {
    W: 600, H: 1000, horizon: 338, moon: [90, 510, 150, 250],
    tablets: inv.events.map((e, k) => [300 - ((n - 1) * gap) / 2 + k * gap, 342]),
    pile: [150, 742], cols: 6, urns: URNS.map((u, k) => [60 + k * 82, 950]),
    tomb: [300, 520], candle: [300, 662], keeper: [190, 640], trail: 'M0 990C120 960 40 880 150 840S230 700 230 676',
    crypts: folders.map((f, k) => [[420, 520, 470][k], [700, 700, 840][k]]),
    home: { mail: [250, 740], files: [470, 620], calendar: [300, 300], code: [410, 510], keeper: [190, 640] },
    sun: [540, 338], folders,
  };
}

// ---- drawing ------------------------------------------------------------------------------------------------
function flower(parent, x, y, s = 1) {
  const g = node('g', { class: 'flower', transform: `translate(${x} ${y}) scale(${s})` }, parent);
  for (let k = 0; k < 6; k++) node('circle', { cx: Math.cos(k) * 4, cy: Math.sin(k) * 4, r: 3.6 }, g);
  node('circle', { class: 'heart', r: 2.4 }, g);
  return g;
}

function ghost(parent, who) {
  const g = node('g', { class: `ghost g-${who}` }, parent);
  const bob = node('g', { class: 'bob' }, g);
  node('ellipse', { class: 'shadow', cx: 0, cy: 40, rx: 16, ry: 4 }, g);
  node('path', { class: 'sheet', d: 'M-19 6C-19-17-10-27 0-27S19-17 19 6V25Q14.5 19 9.5 25T0 25T-9.5 25T-19 25Z' }, bob);
  node('path', { class: 'scarf', d: 'M-15 1Q0 8 15 1' }, bob);
  node('ellipse', { class: 'eye', cx: -6.5, cy: -8, rx: 2.8, ry: 4 }, bob);
  node('ellipse', { class: 'eye', cx: 6.5, cy: -8, rx: 2.8, ry: 4 }, bob);
  if (who === 'keeper') {
    node('path', { class: 'hat', d: 'M-16-22H16M-9-22V-38H9V-22' }, bob);
    node('circle', { class: 'lantern', cx: 24, cy: 14, r: 5 }, bob);
  }
  node('path', { class: 'flame', d: 'M0-34C7-26 7-20 0-17-7-20-7-26 0-34Z', fill: 'url(#flame)', transform: 'translate(24 -14)' }, bob);   // its turn with the candle
  const hand = node('g', { class: 'hand', transform: 'translate(0 -42)' }, bob);
  const think = node('g', { class: 'think', transform: 'translate(22 -36)', opacity: 0 }, bob);
  for (const [cx, cy, r] of [[0, 8, 2], [5, 2, 3], [12, -5, 4.5]]) node('circle', { cx, cy, r }, think);
  return { g, bob, hand, think, x: 0, y: 0 };
}

function envelope(parent) {
  const g = node('g', { class: 'envelope' }, parent);
  node('rect', { x: -14, y: -9.5, width: 28, height: 19, rx: 2 }, g);
  node('path', { class: 'flap', d: 'M-14-9.5L0 2 14-9.5' }, g);
  node('circle', { class: 'seal', cx: 0, cy: 2, r: 3 }, g);
  return g;
}

export function createScene(svgEl, caption) {
  let L, S, els, ghosts, steps = [], token = 0, deadline = null;
  const portrait = () => svgEl.clientWidth < 640;

  function build(inv) {
    svgEl.replaceChildren();
    L = layout(portrait(), inv);
    svgEl.setAttribute('viewBox', `0 0 ${L.W} ${L.H}`);
    const defs = node('defs', {}, svgEl);
    defs.innerHTML = `
      <linearGradient id="night" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#140f33"/><stop offset=".55" stop-color="#2b2163"/><stop offset="1" stop-color="#5a3f86"/></linearGradient>
      <linearGradient id="day" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffe3b8"/><stop offset=".45" stop-color="#ffc8a2"/><stop offset=".75" stop-color="#f6a48f"/><stop offset="1" stop-color="#c99bcc"/></linearGradient>
      <radialGradient id="glow"><stop offset="0" stop-color="#fff6d8" stop-opacity=".55"/><stop offset="1" stop-color="#fff6d8" stop-opacity="0"/></radialGradient>
      <radialGradient id="flame" cx=".5" cy=".7" r=".6"><stop offset="0" stop-color="#fff3c4"/><stop offset=".5" stop-color="#ffc24a"/><stop offset="1" stop-color="#ff7a1a"/></radialGradient>`;
    node('rect', { class: 'sky', width: L.W, height: L.H, fill: 'url(#night)' }, svgEl);
    els = { day: node('rect', { class: 'sky-day', width: L.W, height: L.H, fill: 'url(#day)', opacity: 0 }, svgEl) };
    const stars = node('g', { class: 'stars' }, svgEl);
    for (let k = 0; k < (L.W > 800 ? 46 : 30); k++) {
      const st = node('circle', { cx: rnd(k) * L.W, cy: rnd(k + 99) * (L.horizon - 40), r: 0.6 + rnd(k + 7) * 1.3 }, stars);
      st.style.animationDelay = `${(rnd(k + 3) * -6).toFixed(2)}s`;
    }
    // papel picado across the top
    const picado = node('g', { class: 'picado' }, svgEl);
    node('path', { class: 'string', d: `M0 6Q${L.W / 2} 26 ${L.W} 6` }, picado);
    const flags = L.W > 800 ? 16 : 9;
    for (let k = 0; k < flags; k++) {
      const x = (k + 0.5) * (L.W / flags), y = 6 + 20 * (1 - ((2 * (x / L.W) - 1) ** 2)) * 0.95;
      const f = node('g', { class: `flag f${k % 5}`, transform: `translate(${x} ${y})` }, picado);
      node('path', { d: 'M-17 0H17V30L11 26 5.5 30 0 26-5.5 30-11 26-17 30Z' }, f);
      node('circle', { class: 'cut', cx: 0, cy: 12, r: 4.5 }, f);
      node('path', { class: 'cut', d: 'M-10 6l3 4-3 4M10 6l-3 4 3 4' }, f);
    }
    els.moon = node('g', { class: 'moon' }, svgEl);
    node('circle', { r: 70, fill: 'url(#glow)' }, els.moon);
    node('circle', { class: 'disc', r: 30 }, els.moon);
    for (const [cx, cy, r] of [[-9, -6, 5], [8, 7, 4], [6, -11, 2.5]]) node('circle', { class: 'crater', cx, cy, r }, els.moon);
    els.sun = node('g', { class: 'sun', transform: `translate(${L.sun[0]} ${L.sun[1]})`, opacity: 0 }, svgEl);
    node('path', { class: 'arc' }, svgEl).id = 'dawn-arc';
    els.arc = svgEl.querySelector('#dawn-arc');
    node('circle', { r: 13 }, els.sun);
    els.sunText = node('text', { class: 'sun-text', y: -22, 'text-anchor': 'middle' }, els.sun, '');
    // the hill, the fence, the old graves
    node('path', { class: 'hill far', d: `M0 ${L.horizon + 14}Q${L.W * 0.3} ${L.horizon - 22} ${L.W * 0.62} ${L.horizon + 4}T${L.W} ${L.horizon - 6}V${L.H}H0Z` }, svgEl);
    const fence = node('g', { class: 'fence' }, svgEl);
    for (let x = 10; x < L.W; x += 17) node('path', { d: `M${x} ${L.horizon + 8}v-26l-2.5 4M${x} ${L.horizon - 18}l2.5 4` }, fence);
    node('path', { d: `M0 ${L.horizon - 4}H${L.W}M0 ${L.horizon + 4}H${L.W}` }, fence);
    node('path', { class: 'hill near', d: `M0 ${L.horizon + 40}Q${L.W * 0.5} ${L.horizon + 4} ${L.W} ${L.horizon + 36}V${L.H}H0Z` }, svgEl);
    const graves = node('g', { class: 'old-graves' }, svgEl);
    for (let k = 0; k < (L.W > 800 ? 9 : 5); k++) {
      const x = 40 + rnd(k + 40) * (L.W - 80), y = L.horizon + 30 + rnd(k + 50) * 30;
      node('path', { d: `M${x - 9} ${y}v-14a9 9 0 0 1 18 0v14z` }, graves);
    }
    if (L.W > 800) node('path', { class: 'tree', d: 'M1150 372c-4-60 6-110-14-150m14 70c14-18 30-22 44-40m-48 4c-18-16-26-36-40-44m54 140c10-10 26-14 40-26' }, svgEl);

    // calendar: stone tablets
    els.tablets = {};
    L.tablets.forEach(([x, y], k) => {
      const e = inv.events[k];
      const g = node('g', { class: 'tablet', transform: `translate(${x} ${y})` }, svgEl);
      node('path', { class: 'stone', d: 'M-26 74V18A26 18 0 0 1 26 18V74Z' }, g);
      node('text', { class: 'time', y: 30, 'text-anchor': 'middle' }, g, e.all_day ? 'all day' : e.start.slice(11, 16));
      node('text', { class: 'title', y: 43, 'text-anchor': 'middle' }, g, clip(e.title, 11));
      const lines = node('g', { class: 'lines' }, g);
      node('path', { class: 'crack', d: 'M-8 18l6 12-5 8 7 10-3 12' }, g);
      flower(g, 0, 10, 0.9);
      els.tablets[e.id] = { g, lines, x, y };
    });

    // mail: the day's letters, the four urns
    els.urns = {};
    URNS.forEach(([label, name], k) => {
      const [x, y] = L.urns[k];
      const g = node('g', { class: `urn u-${label}`, transform: `translate(${x} ${y})` }, svgEl);
      const stack = node('g', { class: 'stack' }, g);
      node('path', { class: 'pot', d: 'M-15-34H15L12-28C24-20 24 0 12 8H-12C-24 0-24-20-12-28Z' }, g);
      node('text', { class: 'count', y: -8, 'text-anchor': 'middle' }, g, '0');
      node('text', { class: 'label', y: 26, 'text-anchor': 'middle' }, g, name);
      flower(g, 15, -30, 0.8);
      els.urns[label] = { g, stack, count: g.querySelector('.count'), x, y };
    });
    els.letters = {};
    inv.mail.forEach((m, k) => {
      const col = k % L.cols, row = Math.floor(k / L.cols);
      const x = L.pile[0] - ((L.cols - 1) * 33) / 2 + col * 33 + (rnd(k) - 0.5) * 8;
      const y = L.pile[1] + row * 24 + (rnd(k + 9) - 0.5) * 6;
      const g = envelope(svgEl);
      g.style.transform = `translate(${x}px, ${y}px) rotate(${(rnd(k + 5) - 0.5) * 24}deg)`;
      els.letters[m.id] = { g, x, y, k };
    });

    // files: one crypt per folder
    els.crypts = {};
    L.folders.forEach((folder, k) => {
      const [x, y] = L.crypts[k];
      const g = node('g', { class: 'crypt', transform: `translate(${x} ${y})` }, svgEl);
      node('path', { class: 'roof', d: 'M-44-58L0-84 44-58Z' }, g);
      node('rect', { class: 'walls', x: -38, y: -58, width: 76, height: 86 }, g);
      node('text', { class: 'name', y: -64, 'text-anchor': 'middle' }, g, clip(folder, 11));
      node('rect', { class: 'doorway', x: -15, y: -30, width: 30, height: 58, rx: 15 }, g);
      const door = node('rect', { class: 'door', x: -15, y: -30, width: 30, height: 58, rx: 3 }, g);
      node('text', { class: 'count', y: 44, 'text-anchor': 'middle' }, g, '');
      flower(g, -30, 26, 0.8); flower(g, 30, 26, 0.8);
      els.crypts[folder] = { g, door, count: g.querySelector('.count'), x, y };
    });

    // code: the repo's tombstone, the test candles, the one candle on the altar
    const [tx, ty] = L.tomb;
    const tomb = node('g', { class: 'tomb', transform: `translate(${tx} ${ty})` }, svgEl);
    node('path', { class: 'stone', d: 'M-72 100V-30A72 64 0 0 1 72-30V100Z' }, tomb);
    node('text', { class: 'name', y: -36, 'text-anchor': 'middle' }, tomb, inv.repos[0] || 'your repo');
    const branch = node('text', { class: 'branch', y: -16, 'text-anchor': 'middle' }, tomb, '');
    const carved = node('g', { class: 'carved' }, tomb);
    const sha = node('text', { class: 'sha', y: 70, 'text-anchor': 'middle' }, tomb, '');
    for (const [fx, fy] of [[-66, 98], [-50, 104], [52, 104], [68, 98]]) flower(tomb, fx, fy, 1);
    els.tomb = { g: tomb, branch, carved, sha };
    // marigold petals lead the spirits home, to the ofrenda and its one candle (the GPU: one ghost at a time)
    const trail = node('path', { class: 'trail', d: L.trail }, svgEl), petals = node('g', { class: 'petals' }, svgEl);
    for (let k = 0, len = trail.getTotalLength(); k < len; k += 13) {
      const pt = trail.getPointAtLength(k);
      node('ellipse', { cx: pt.x + (rnd(k) - 0.5) * 9, cy: pt.y + (rnd(k + 1) - 0.5) * 5, rx: 3.2, ry: 2, transform: `rotate(${rnd(k + 2) * 180} ${pt.x} ${pt.y})` }, petals);
    }
    els.altar = node('g', { class: 'altar', transform: `translate(${L.candle[0]} ${L.candle[1]})` }, svgEl);
    node('rect', { class: 'tier', x: -80, y: 8, width: 160, height: 14, rx: 2 }, els.altar);
    node('rect', { class: 'tier', x: -54, y: -6, width: 108, height: 14, rx: 2 }, els.altar);
    for (let k = 0; k < 8; k++) node('path', { class: `fringe f${k % 5}`, d: `M${-54 + k * 13.5} -6h13.5l-6.75 8z` }, els.altar);
    for (const px of [-34, 34]) {
      const ph = node('g', { class: 'photo', transform: `translate(${px} -20)` }, els.altar);
      node('rect', { x: -9, y: -12, width: 18, height: 22, rx: 1.5 }, ph);
      node('circle', { cx: 0, cy: -3, r: 4 }, ph);
      node('path', { d: 'M-6 9a6 6 0 0 1 12 0' }, ph);
    }
    const pan = node('g', { class: 'pan', transform: 'translate(-62 3)' }, els.altar);
    node('ellipse', { rx: 10, ry: 6 }, pan);
    node('path', { d: 'M-6-2l12 4M-6 2l12-4' }, pan);
    node('rect', { class: 'wax', x: -5, y: -26, width: 10, height: 20, rx: 2 }, els.altar);
    node('path', { class: 'flame', d: 'M0-34C7-26 7-20 0-17-7-20-7-26 0-34Z', fill: 'url(#flame)', transform: 'translate(0 -3)' }, els.altar);
    flower(els.altar, 62, 2, 1.1); flower(els.altar, 72, 9, 0.9); flower(els.altar, -74, 9, 0.9);

    ghosts = {};
    for (const who of Object.keys(GHOSTS)) {
      ghosts[who] = ghost(svgEl, who);
      place(who, ...L.home[who]);
    }
    S = initial(inv);
  }

  // ---- render a state instantly ----------------------------------------------------------------------------
  function place(who, x, y) {
    const gh = ghosts[who];
    gh.x = x; gh.y = y;
    gh.g.style.transform = `translate(${x}px, ${y}px)`;
  }

  function stackUrn(label, n) {
    const u = els.urns[label];
    u.count.textContent = n;
    u.g.classList.toggle('full', n > 0);
    u.stack.replaceChildren();
    for (let k = 0; k < Math.min(n, 4); k++) {
      const e = envelope(u.stack);
      e.setAttribute('transform', `translate(${(k - 1.5) * 6} ${-36 - k * 2}) rotate(${(k - 1.5) * 14}) scale(.6)`);
    }
  }

  function render(state, progress) {
    S = state;
    const counts = Object.fromEntries(URNS.map(([l]) => [l, 0]));
    for (const [id, r] of Object.entries(state.mail)) counts[r.label] = (counts[r.label] || 0) + 1;
    for (const [id, l] of Object.entries(els.letters)) {
      const r = state.mail[id];
      l.g.classList.toggle('gone', !!r && r.label in counts);
      l.g.style.transform = `translate(${l.x}px, ${l.y}px) rotate(${(rnd(l.k + 5) - 0.5) * 24}deg)`;
      l.g.style.opacity = '';
    }
    for (const [label] of URNS) stackUrn(label, counts[label]);
    const byFolder = {};
    state.inv.files.forEach((f) => { const k = f.folder.split('/')[0]; (byFolder[k] ??= [0, 0])[1]++; if (state.files[f.id]) byFolder[k][0]++; });
    for (const [folder, c] of Object.entries(els.crypts)) {
      const [read, all] = byFolder[folder] || [0, 0];
      c.count.textContent = all ? `${read}/${all}` : '';
      c.g.classList.toggle('done', all > 0 && read === all);
      c.g.classList.toggle('found', state.inv.files.some((f) => f.folder.split('/')[0] === folder && state.files[f.id]?.answers));
    }
    for (const e of state.inv.events) {
      const t = els.tablets[e.id], m = state.meetings[e.id];
      t.lines.replaceChildren();
      for (let k = 0; k < (m?.prep ?? 0); k++) node('path', { d: `M-15 ${52 + k * 6}h${30 - (k % 2) * 8}` }, t.lines);
      t.g.classList.toggle('done', !!m);
      t.g.classList.toggle('clash', !!m && e.clashes.length > 0);
    }
    const T = state.tomb;
    els.tomb.branch.textContent = T.open ? clip(T.branch, 26) : '';
    els.tomb.carved.replaceChildren();
    T.lines.slice(-4).forEach((p, k) => node('text', { y: 6 + k * 13, 'text-anchor': 'middle' }, els.tomb.carved, clip(p, 24)));
    els.tomb.g.classList.toggle('pass', T.tests === true);
    els.tomb.g.classList.toggle('fail', T.tests === false);
    els.tomb.g.classList.toggle('done', !!T.sha);
    els.tomb.sha.textContent = T.sha ? (T.sha === 'nothing to commit' ? T.sha : `kept on ${T.sha}`) : '';
    if (state.forecast) {
      els.sun.setAttribute('opacity', 1);
      els.sunText.textContent = `ready by ${(deadline || state.forecast.dawn).slice(11, 16)}`;
    } else els.sun.setAttribute('opacity', 0);
    for (const gh of Object.values(ghosts)) gh.g.classList.toggle('in-grave', !state.risen);
    moon(progress ?? 0);
  }

  function moon(p) {
    const [x0, x1, top, low] = L.moon, x = x0 + (x1 - x0) * p, y = top + (low - top) * (2 * p - 1) ** 2;
    els.moon.style.transform = `translate(${x}px, ${y}px)`;
    if (S?.forecast) els.arc.setAttribute('d', `M${x} ${y + 34}Q${(x + L.sun[0]) / 2} ${Math.min(y, L.sun[1]) - 40} ${L.sun[0]} ${L.sun[1] - 18}`);
    else els.arc.setAttribute('d', '');
  }

  // ---- motion ----------------------------------------------------------------------------------------------
  async function go(target, to, ms, easing = EASE) {
    if (ms < 30) { Object.assign(target.style, to); return; }
    const a = target.animate([to], { duration: ms, easing, fill: 'forwards' });
    try { await a.finished; a.commitStyles(); } catch { /* cancelled by a seek */ } finally { a.cancel(); }
  }
  async function fly(who, x, y, ms) {
    const gh = ghosts[who], dist = Math.hypot(x - gh.x, y - gh.y);
    if (Math.abs(x - gh.x) > 2) gh.g.classList.toggle('flip', x < gh.x);
    gh.x = x; gh.y = y;
    await go(gh.g, { transform: `translate(${x}px, ${y}px)` }, dist < 2 ? 0 : ms);
  }
  function holdFlame(who) {   // one candle, one GPU: only the ghost whose turn it is holds the flame
    for (const [w, gh] of Object.entries(ghosts)) gh.g.classList.toggle('lit', w === who);
    els.altar.classList.toggle('lit', !who);
  }
  function say(who, line, detail = '') {
    caption.who.textContent = GHOSTS[who] ?? '';
    caption.line.textContent = line;
    caption.detail.textContent = detail;
    caption.box.dataset.who = who;
  }
  const thinking = (who, on) => ghosts[who].think.setAttribute('opacity', on ? 1 : 0);

  const LABEL = Object.fromEntries(URNS);
  async function play(step, ms, i) {
    const my = token, who = step.ghost in ghosts ? step.ghost : 'keeper', r = step.result, id = step.target.split(':')[1];
    const next = apply(S, step), still = () => my === token;
    if (reduced.matches) ms = Math.min(ms, 260);
    if (step.candle) holdFlame(who);
    if (step.attempt > 1) {
      const silent = Math.round(step.t - step.queued);
      say(who, `came back from the dead (attempt ${step.attempt})`,
        `the app was killed mid-step; ${step.retried?.includes('eartbeat') ? 'Temporal noticed the missing heartbeat' : 'Temporal noticed'} and a new worker took over ${silent > 0 ? `${silent} s later` : ''}`);
      ghosts[who].g.classList.add('possessed');
      await go(ghosts[who].g, { opacity: 0, transform: `translate(${ghosts[who].x}px, ${ghosts[who].y + 40}px)` }, ms * 0.25);
      await go(ghosts[who].g, { opacity: 1, transform: `translate(${ghosts[who].x}px, ${ghosts[who].y}px)` }, ms * 0.35, OUT);
      ghosts[who].g.classList.remove('possessed');
      if (!still()) return;
    }
    const d = ms;
    switch (step.act) {
      case 'gather': {
        say('keeper', 'Dusk. The day is gathered for the ghosts.', `${S.inv.mail.length} letters · ${S.inv.files.length} files · ${S.inv.events.length} meetings tomorrow`);
        await Promise.all(Object.values(els.letters).map((l, k) => l.g.animate([{ opacity: 0, translate: '0 -40px' }, { opacity: 1, translate: '0 0' }],
          { duration: d * 0.6, delay: k * (d * 0.3 / Object.keys(els.letters).length), easing: OUT, fill: 'backwards' }).finished.catch(() => {})));
        break;
      }
      case 'check_sleep': {
        const up = r?.idle_min >= 20;
        say('keeper', up ? 'You\'re asleep. The ghosts rise.' : `Peeking out of the graves (${S.peeks + 1})… still awake.`,
          `idle for ${r?.idle_min ?? '?'} min · ${r?.on_ac ? 'on power' : 'on battery'}`);
        for (const gh of Object.values(ghosts)) {
          if (up) gh.g.classList.remove('in-grave');
          gh.bob.animate(up ? [{ translate: '0 46px', opacity: 0 }, { translate: '0 0', opacity: 1 }]
            : [{ translate: '0 46px', opacity: 0 }, { translate: '0 22px', opacity: 0.8 }, { translate: '0 46px', opacity: 0 }], { duration: d * 0.9, easing: OUT });
        }
        await pause(d);
        break;
      }
      case 'llm_turn': {
        thinking(who, true);
        if (who === 'keeper') {
          await fly('keeper', ...L.keeper, d * 0.2);
          if (r?.plan) {
            const code = r.plan.code?.map((c) => `${c.repo}: ${c.goal}`).join('; ');
            say('keeper', 'plans the night', [code && `code → ${code}`, r.plan.find?.length && `find → ${r.plan.find.join(', ')}`].filter(Boolean).join(' · '));
          } else say('keeper', 'reads your note', r?.calls?.length ? 'and asks TabPFN when you\'ll wake' : '');
        } else {
          await fly('code', L.tomb[0] + 96, L.tomb[1] - 24, d * 0.25);
          const calls = r?.calls?.map((c) => `${c.name} ${c.path}`.trim()).join(', ');
          say('code', calls ? `decides: ${calls}` : 'thinks', r?.said || '');
        }
        await pause(d * 0.7);
        thinking(who, false);
        break;
      }
      case 'forecast_dawn':
        say('keeper', `asks TabPFN when you'll wake: around ${r?.wake?.slice(11, 16)}`, `learned from ${r?.nights} nights of this Mac's power log · the briefing must be ready by ${(deadline || r?.dawn || '').slice(11, 16)}`);
        S = next; render(S, i);
        els.arc.animate([{ strokeDashoffset: 400 }, { strokeDashoffset: 0 }], { duration: d * 0.8, easing: OUT });
        els.sun.animate([{ scale: 0.3, opacity: 0 }, { scale: 1, opacity: 1 }], { duration: d * 0.6, easing: OUT });
        await pause(d);
        break;
      case 'triage_email': {
        const l = els.letters[id], m = S.inv.mail.find((x) => x.id === id), u = els.urns[r?.label];
        say('mail', `reads a letter from ${m?.from ?? 'someone'}`, `“${clip(m?.subject ?? '', 60)}”`);
        await fly('mail', l.x + 4, l.y - 40, d * 0.28);
        if (!still()) return;
        l.g.classList.add('open');
        await go(l.g, { transform: `translate(${l.x + 4}px, ${l.y - 62}px) rotate(0deg) scale(1.25)` }, d * 0.12, OUT);
        if (!r || !u) break;
        say('mail', `${LABEL[r.label]}: ${r.why}`, r.label === 'suspicious' ? `this letter tried to possess the ghosts · caught by ${r.caught_by.join(' + ')}` : `“${clip(m?.subject ?? '', 60)}”`);
        if (r.label === 'suspicious') {
          ghosts.mail.g.classList.add('possessed');
          await ghosts.mail.bob.animate([{ rotate: '0deg' }, { rotate: '-9deg' }, { rotate: '8deg' }, { rotate: '-5deg' }, { rotate: '0deg' }], { duration: d * 0.22 }).finished.catch(() => {});
          ghosts.mail.g.classList.remove('possessed');
        } else await pause(d * 0.16);
        if (!still()) return;
        await Promise.all([fly('mail', u.x + 26, u.y - 66, d * 0.26),
          go(l.g, { transform: `translate(${u.x}px, ${u.y - 50}px) rotate(0deg) scale(.7)` }, d * 0.26)]);
        await go(l.g, { transform: `translate(${u.x}px, ${u.y - 20}px) rotate(0deg) scale(.3)`, opacity: 0 }, d * 0.1);
        u.g.animate([{ rotate: '0deg' }, { rotate: '-4deg' }, { rotate: '3deg' }, { rotate: '0deg' }], { duration: 380 });
        l.g.classList.remove('open');
        break;
      }
      case 'read_file_item': {
        const f = S.inv.files.find((x) => x.id === id), c = els.crypts[f?.folder.split('/')[0]];
        say('files', `opens ${f?.folder ?? 'a folder'} and reads ${f?.name ?? 'a file'}`, '');
        if (!c) { await pause(d); break; }
        await fly('files', c.x - 34, c.y - 4, d * 0.3);
        if (!still()) return;
        c.g.classList.add('open');
        const scroll = node('g', { class: 'scroll', transform: `translate(${c.x} ${c.y - 6})` }, svgEl);
        node('rect', { x: -12, y: -15, width: 24, height: 30, rx: 3 }, scroll);
        for (let k = 0; k < 4; k++) node('path', { d: `M-7 ${-8 + k * 6}h${14 - (k % 2) * 5}` }, scroll);
        await go(scroll, { transform: `translate(${c.x}px, ${c.y - 64}px)` }, d * 0.15, OUT);
        if (r) say('files', r.answers ? `found it: ${r.answers}` : `${f.name}: ${r.kind}`, r.summary);
        if (r?.answers) scroll.classList.add('found');
        await pause(d * 0.35);
        await go(scroll, { transform: `translate(${c.x}px, ${c.y - 6}px)`, opacity: 0 }, d * 0.15);
        scroll.remove();
        c.g.classList.remove('open');
        break;
      }
      case 'prep_meeting': {
        const e = S.inv.events.find((x) => x.id === id), t = els.tablets[id];
        say('calendar', `prepares ${e?.start.slice(11, 16) ?? ''} ${e?.title ?? ''}`, r ? `${r.prep} notes${r.letters.length ? ` · letters ${r.letters.join(', ')}` : ''}${r.files.length ? ` · files ${r.files.join(', ')}` : ''}${e?.clashes.length ? ' · clashes with another meeting' : ''}` : '');
        await fly('calendar', t.x + 40, t.y + 10, d * 0.32);
        if (!still()) return;
        for (let k = 0; k < (r?.prep ?? 0); k++) {
          const p = node('path', { class: 'writing', d: `M-15 ${52 + k * 6}h${30 - (k % 2) * 8}` }, t.lines);
          p.animate([{ strokeDashoffset: 30 }, { strokeDashoffset: 0 }], { duration: (d * 0.5) / Math.max(1, r.prep), fill: 'backwards' });
          await pause((d * 0.5) / Math.max(1, r.prep));
        }
        await pause(d * 0.15);
        break;
      }
      case 'open_worktree':
        say('code', `opens a private copy of ${S.inv.repos[0]}`, r ? `branch ${r.branch} · the tests ${r.baseline ? 'pass' : 'fail'} right now${r.stale?.length ? ` · stale branch: ${r.stale.join(', ')}` : ''}` : '');
        await fly('code', L.tomb[0] + 96, L.tomb[1] - 24, d * 0.4);
        await pause(d * 0.4);
        break;
      case 'run_tool': {
        const tool = r?.tool;
        say('code', tool === 'run_tests' ? 'runs the tests (no network, sandboxed)' : `${tool?.replace('_', ' ')} ${r?.path ?? ''}`,
          tool === 'run_tests' ? (r?.passed ? 'they pass' : 'they fail') : '');
        if (tool === 'write_file') await fly('code', L.tomb[0] + 52, L.tomb[1] - 8, d * 0.3);
        if (tool === 'run_tests') {
          els.tomb.g.classList.add('testing');
          await pause(d * 0.6);
          els.tomb.g.classList.remove('testing');
        } else await pause(d * 0.5);
        break;
      }
      case 'commit_work':
        say('code', r?.sha ? `carves it in: commit ${r.sha}` : 'had nothing to commit', r?.stat || '');
        await fly('code', L.tomb[0] + 96, L.tomb[1] - 24, d * 0.2);
        await pause(d * 0.5);
        break;
      default:
        await pause(Math.min(d, 300));
    }
    if (!still()) return;
    if (step.candle) holdFlame(null);
    render(next, i);
  }

  return {
    build(inv, all, due) {
      steps = all; deadline = due; build(inv);
      S = initial(inv, all.some((x) => x.act === 'check_sleep'));
      render(S, 0); holdFlame(null);
    },
    rebuildIfNeeded(inv) { if ((L.W > 800) === portrait()) { const keep = S; build(inv); render(keep, 0); holdFlame(null); } },
    play(step, ms, progress) { return play(step, ms, progress); },
    seek(k) {   // jump: cancel what's moving, render the state after k steps
      token++;
      svgEl.getAnimations({ subtree: true }).forEach((a) => a.cancel());
      svgEl.querySelectorAll('.scroll').forEach((e) => e.remove());
      for (const w of Object.keys(ghosts)) place(w, ...L.home[w]);
      holdFlame(null);
      render(steps.slice(0, k).reduce(apply, initial(S.inv, steps.some((x) => x.act === 'check_sleep'))), k / Math.max(1, steps.length));
    },
    state: () => S,
    dawn(on) {
      svgEl.classList.toggle('dawn', on);
      els.day.animate([{ opacity: on ? 0 : 1 }, { opacity: on ? 1 : 0 }], { duration: reduced.matches ? 1 : 2400, fill: 'forwards', easing: EASE });
      for (const gh of Object.values(ghosts)) gh.g.animate([{ opacity: on ? 1 : 0 }, { opacity: on ? 0 : 1 }], { duration: reduced.matches ? 1 : 1800, fill: 'forwards', delay: on ? 600 : 0 });
    },
  };
}
