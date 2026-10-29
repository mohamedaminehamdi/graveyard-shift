// One night, scrolled. Your scroll is the night's clock: each chapter's scene follows how far you have scrolled
// through it, so the ghosts work as you scroll down, rewind as you scroll back up, and idle when you stop. Without
// JS, or with reduced motion, every scene simply shows how it ends.
const root = document.documentElement;
const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
const pinned = matchMedia('(min-width: 1024px) and (min-height: 720px)');   // the same query pins chapters in style.css
const EASE = 'cubic-bezier(.16, 1, .3, 1)', SWAY = 'cubic-bezier(.45, 0, .25, 1)';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const clamp = (x, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, x));
const span = (k, a, b) => clamp((k - a) / (b - a));   // 0 before a, 1 after b

if (!still) root.classList.add('ready');

// one move on a chapter's timeline, from a to b (shares of the scroll through the chapter); scrolling sets its time
function move(el, frames, a, b, easing = EASE) {
  const anim = el.animate(frames, { duration: (b - a) * 1000, delay: a * 1000, fill: 'both', easing });
  anim.pause();
  return anim;
}
// where an element sits inside a scene's box
function spot(el, box) {
  const r = el.getBoundingClientRect(), b = box.getBoundingClientRect();
  return { x: r.left - b.left, y: r.top - b.top, w: r.width, h: r.height };
}
// a ghost's flight through [k, x, y, opacity] stops: it holds still between two stops at the same place
function flight(ghost, stops) {
  const a = stops[0][0], b = stops.at(-1)[0];
  return move(ghost, stops.map(([k, x, y, o = 1]) => (
    { offset: (k - a) / (b - a), transform: `translate(${x}px, ${y}px)`, opacity: o, easing: SWAY })), a, b, 'linear');
}
const typed = (el, k) => {   // the share k of an element's text, as if being typed
  const full = (el.dataset.full ??= el.textContent), n = Math.round(k * full.length);
  if (el.textContent.length !== n) el.textContent = full.slice(0, n);
};

// ---- the scenes: each builds its moves once, and draw(k) does what moves can't (text, counts, states) -------
const scenes = {
  top(sec) {   // scrolling on sends the ghosts out of the laptop to work
    const art = $('.hero-art', sec).getBoundingClientRect(), out = [[-.55, -1], [-.2, -1.2], [.3, -1.1], [.6, -.8], [-.35, -1.3]];
    const anims = $$('.hero-art .spirit', sec).flatMap((s, i) => [
      move(s, [{ transform: 'none' }, { transform: `translate(${out[i][0] * art.width}px, ${out[i][1] * art.height}px) scale(.55)` }],
        .05, 1, 'cubic-bezier(.55, 0, .8, .45)'),
      move($('.body', s), [{ opacity: 1 }, { opacity: 0 }], .55, 1, 'linear'),
    ]);
    anims.push(move($('.screen', sec), [{ opacity: 1 }, { opacity: .35 }], 0, .8, 'linear'));
    return { anims };
  },

  note(sec) {   // the note types itself, the ghosts read over its edge, then Goodnight and they go to wait
    const text = $('.note-text', sec);
    text.textContent = text.dataset.full ?? text.textContent;
    text.style.minHeight = '';
    text.style.minHeight = `${text.offsetHeight}px`;
    const anims = [move($('.goodnight', sec), [{ scale: 1 }, { scale: .9, offset: .5 }, { scale: 1 }], .64, .72, 'linear')];
    $$('.peekers .spirit', sec).forEach((s, i) => anims.push(move(s, [
      { transform: 'translateY(75%)', opacity: 0 }, { transform: 'none', opacity: 1, offset: .32 },
      { transform: 'none', opacity: 1, offset: .74 }, { transform: 'translateY(75%)', opacity: 0 }], .02 + i * .03, .9 + i * .02, 'linear')));
    return { anims, draw(k) {
      typed(text, span(k, .08, .6));
      text.classList.toggle('typing', k > .04 && k < .64);
      sec.classList.toggle('slept', k > .74);
    } };
  },

  wait(sec) {   // TabPFN's wake curve draws itself; the ghosts lie on the flat line until you're asleep, then rise
    const anims = [
      move($('.curve .line', sec), [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], .04, .6, 'cubic-bezier(.45, 0, .2, 1)'),
      move($('.curve .area', sec), [{ opacity: 0 }, { opacity: 1 }], .42, .64),
      move($('.curve .done-by', sec), [{ opacity: 0 }, { opacity: 1 }], .5, .6),
      move($('.curve .up', sec), [{ opacity: 0 }, { opacity: 1 }], .55, .63),
      ...$$('.flags span', sec).map((f, i) => move(f, [{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }], .56 + i * .06, .66 + i * .06)),
      ...$$('.sleeper', sec).map((s, i) => move(s, [{ opacity: .3, transform: 'translateY(32px)' }, { opacity: 1, transform: 'none' }], .72 + i * .04, .88 + i * .04)),
    ];
    return { anims, draw: (k) => sec.classList.toggle('risen', k > .74) };
  },

  mail(sec) {   // the Mail ghost reads the inbox letter by letter, and each letter drops into its pile
    const box = $('.mailroom', sec), rows = $$('.rows li', sec), read = $('[data-read]', sec);
    const slips = Object.fromEntries($$('.slip', sec).map((s) => [s.dataset.m, s]));
    const counts = $$('[data-count]', sec).map((c) => [c, +(c.dataset.to ??= c.textContent)]);
    const total = +(read.dataset.to ??= read.textContent);
    const step = .66 / rows.length, at = (i) => .1 + i * step;
    const anims = [move($('.inbox', sec), [{ opacity: 0, transform: 'scale(.94)' }, { opacity: 1, transform: 'none' }], 0, .08)];
    const first = spot(rows[0], box), stops = [[.02, first.x - 60, first.y - 20, 0]];
    let caught = 1;
    rows.forEach((row, i) => {
      const r = spot(row, box), x = r.x + r.w - 58, y = r.y - 30;
      stops.push([at(i), x, y], [at(i) + step * .55, x, y]);
      if (row.classList.contains('evil')) {   // it reads the orders, and recoils
        stops.splice(-1, 0, [at(i) + step * .3, x + 26, y - 22]);
        caught = at(i) + step * 1.3;
      }
      anims.push(move(row, [{ opacity: 1 }, { opacity: .3 }], at(i) + step * .5, at(i) + step * .8));
      const slip = slips[row.dataset.m];
      if (!slip?.offsetParent) return;
      const s = spot(slip, box);
      anims.push(move(slip, [{ opacity: 0, transform: `translate(${r.x - s.x}px, ${r.y - s.y}px) scale(.85)` },
        { opacity: 1, offset: .3 }, { opacity: 1, transform: 'none' }], at(i) + step * .45, at(i) + step * 1.35));
    });
    const board = spot($('.board', sec), box), end = at(rows.length - 1) + step;
    stops.push([end + .06, board.x + board.w * .45, board.y - 64], [.97, board.x + board.w * .45, board.y - 140, 0]);
    anims.push(move($('.draft', sec), [{ opacity: 0, transform: 'translateY(-8px)' }, { opacity: 1, transform: 'none' }], end + .02, end + .1));
    anims.push(flight($('.runner', sec), stops));
    return { anims, draw(k) {
      const p = span(k, at(0) + step * .5, end);
      rows.forEach((row, i) => row.classList.toggle('on', k >= at(i) - step * .1 && k < at(i) + step * .65));
      for (const [c, to] of counts) c.textContent = String(Math.round(to * p));
      read.textContent = String(Math.round(total * p));
      sec.classList.toggle('caught', k >= caught);
    } };
  },

  chats(sec) {   // the Messages ghost reads each chat in turn, flies past the one-time code, and drafts the answers
    const room = $('.chatroom', sec), rows = $$('.convos li', sec), read = rows.filter((r) => r.dataset.t);
    const chats = Object.fromEntries($$('.chat', sec).map((c) => [c.dataset.t, c]));
    const step = .7 / read.length, at = (i) => .1 + i * step;
    const anims = rows.map((r, i) => move(r, [{ opacity: 0, transform: 'translateY(12px)' }, { opacity: 1, transform: 'none' }], .01 + i * .01, .07 + i * .01));
    anims.push(move($('.chatpane', sec), [{ opacity: 0, transform: 'scale(.95)' }, { opacity: 1, transform: 'none' }], .03, .1));
    const stops = [];
    read.forEach((row, i) => {
      const r = spot(row, room), x = r.x + r.w - 44, y = r.y - 30;
      if (!i) stops.push([.04, x - 60, y - 40, 0]);
      stops.push([at(i), x, y], [at(i) + step * .7, x, y]);
      const parts = $$('.bubbles > *', chats[row.dataset.t]);
      parts.forEach((b, j) => anims.push(move(b, [{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }],
        at(i) + step * (.65 * j / parts.length - .3), at(i) + step * (.65 * j / parts.length - .18))));   // the first bubbles are there as it arrives
      anims.push(move($('em', row), [{ opacity: 0, transform: 'scale(.6)' }, { opacity: 1, transform: 'none' }], at(i) + step * .7, at(i) + step * .85));
    });
    const [, x, y] = stops.at(-1);
    stops.push([.9, x, y], [.97, x + 20, y - 60, 0]);
    anims.push(flight($('.runner', sec), stops));
    return { anims, draw(k) {
      const now = clamp(Math.floor((k - .1) / step + .3), 0, read.length - 1);   // the chat opens as the ghost arrives
      read.forEach((row, i) => row.classList.toggle('on', i === now && k >= .08 && k < .9));
      for (const [t, chat] of Object.entries(chats)) chat.classList.toggle('on', t === read[now].dataset.t);
    } };
  },

  files(sec) {   // the Files ghost reads today's files one by one, the contract last, and notes what to check
    const grid = $('.tiles', sec), tiles = $$('.file', sec);
    const order = [...tiles].sort((a, b) => a.dataset.f.localeCompare(b.dataset.f));   // the order the ghost really read them in
    const step = .54 / order.length, at = (j) => .14 + j * step;
    const anims = tiles.map((t, i) => move(t, [{ opacity: 0, transform: 'translateY(18px)' }, { opacity: 1, transform: 'none' }], .01 + i * .012, .08 + i * .012));
    const stops = [];
    order.forEach((t, j) => {
      const r = spot(t, grid), x = r.x + r.w - 36, y = r.y - 30;
      if (!j) stops.push([.06, x - 50, y - 30, 0]);
      stops.push([at(j), x, y], [at(j) + step * .6, x, y]);
    });
    // then it carries a see-through copy of each loose file to the folder it picked: the file itself waits for Tidy
    const art = $('.ch-art', sec), copies = $$('.copy', sec);
    copies.forEach((c, i) => {
      const from = spot($(`.file[data-f="${c.dataset.f}"]`, sec), art), to = spot(c, art);
      anims.push(move(c, [{ opacity: 0, transform: `translate(${from.x - to.x}px, ${from.y - to.y}px)` }, { opacity: .9, offset: .2 },
        { opacity: 1, transform: 'none' }], .76 + i * .025, .86 + i * .025));
    });
    const shelf = $('.shelf', sec), [, x, y] = stops.at(-1);
    if (shelf) {
      const s = spot(shelf, grid);
      stops.push([.74, x, y], [.84, s.x + s.w * .5, s.y - 40], [.95, s.x + s.w * .5 + 20, s.y - 100, 0]);
    } else stops.push([.8, x, y], [.92, x + 20, y - 60, 0]);
    return { anims: [...anims, flight($('.runner', sec), stops)], draw(k) {
      order.forEach((t, j) => {
        t.classList.toggle('reading', k >= at(j) && k < at(j) + step * .85);
        t.classList.toggle('read', k >= at(j) + step * .85);
      });
      sec.classList.toggle('lifted', k >= .66);
      sec.classList.toggle('packed', k >= .78);
    } };
  },

  day(sec) {   // the Calendar ghost walks tomorrow, pins the prep note on the 10:00, and marks the clash
    const art = $('.ch-art', sec), rows = $$('.agenda > li', sec);
    const at = [.06, .14, .48, .56, .64, .74];   // when it reaches each meeting: it stays at the 10:00 while the note goes on
    const anims = rows.map((li, i) => move(li, [{ opacity: 0, transform: 'translateY(16px)' }, { opacity: 1, transform: 'none' }], at[i] - .05, at[i] + .02));
    anims.push(move($('.prep', sec), [{ opacity: 0, clipPath: 'inset(0 0 100% 0 round 12px)' }, { opacity: 1, clipPath: 'inset(0 0 0% 0 round 12px)' }], .2, .4));
    anims.push(...$$('.prep .links span', sec).map((c, i) => move(c, [{ opacity: 0, transform: 'scale(.8)' }, { opacity: 1, transform: 'none' }], .38 + i * .03, .44 + i * .03)));
    const where = rows.map((li) => { const r = spot(li, art); return [r.x + r.w - 40, r.y - 22]; });
    const stops = [[.02, where[0][0] + 40, where[0][1] - 40, 0], ...rows.map((li, i) => [at[i], ...where[i]])];
    stops.splice(3, 0, [.42, ...where[1]]);
    stops.push([.84, ...where[5]], [.95, where[5][0] + 30, where[5][1] - 70, 0]);
    return { anims: [...anims, flight($('.runner', sec), stops)], draw: (k) => sec.classList.toggle('flagged', k >= .66) };
  },

  crash(sec) {   // the worker dies mid-file; Temporal waits out the heartbeat and hands the file to a new one
    const box = $('.history', sec), cmd = $('.kill span', sec);
    const what = spot($('.what', sec), box), a2 = spot($('.a2', sec), box);
    const x = Math.min(what.w, box.clientWidth - 90);
    const anims = [
      move($('.victim', sec), [{ opacity: 1, transform: `translate(${x}px, ${what.y - 40}px)` },
        { opacity: 0, transform: `translate(${x}px, ${what.y - 40}px) scale(.3) rotate(-14deg)` }], .25, .31),
      move($('.timer .fill', sec), [{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }], .32, .68, 'linear'),
      move($('.heir', sec), [{ opacity: 0, transform: `translate(${a2.x + a2.w - 120}px, ${a2.y + 10}px)` },
        { opacity: 1, transform: `translate(${a2.x + a2.w - 120}px, ${a2.y - 22}px)` }], .7, .78),
      ...$$('.rest .dots i', sec).map((d, i) => move(d, [{ opacity: .12, transform: 'scale(.4)' }, { opacity: .95, transform: 'none' }], .78 + i * .004, .8 + i * .004)),
    ];
    return { anims, draw(k) {
      typed(cmd, span(k, .04, .2));
      sec.classList.toggle('dead', k >= .25);
      sec.classList.toggle('waiting', k >= .32);
      sec.classList.toggle('back', k >= .7);
    } };
  },

  code(sec) {   // the Code ghost opens a terminal in its sandbox and types what it really ran; the tests go green
    const room = $('.devroom', sec), tl = $('.tl', sec), lines = $$('.tl p', sec);
    const step = .64 / lines.length, at = (i) => .1 + i * step, ok = at(lines.findIndex((p) => p.classList.contains('ok')));
    const rows = +getComputedStyle(tl).getPropertyValue('--rows'), lh = parseFloat(getComputedStyle(lines[0]).lineHeight);
    const up = (i) => Math.max(0, i - rows + 1) * lh;   // once the terminal is full it scrolls, so the line being typed stays in view
    const anims = [move($('.term', sec), [{ opacity: 0, transform: 'scale(.94)' }, { opacity: 1, transform: 'none' }], .02, .1),
      move($('.tl-in', sec), lines.map((_, i) => ({ offset: i / (lines.length - 1), transform: `translateY(${-up(i)}px)`, easing: 'steps(1, end)' })),
        at(0), at(lines.length - 1), 'linear')];   // it jumps a line at a time, like a terminal
    const stops = [];
    lines.forEach((p, i) => {
      const c = p.classList.contains('c');
      anims.push(move(p, [{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0% 0 0)' }], at(i), at(i) + step * (c ? .9 : .3),
        c ? `steps(${Math.min(30, p.textContent.length)}, end)` : 'linear'));
      if (!c) return;
      const r = spot(p, room), x = Math.min(r.x + r.w + 8, room.clientWidth - 52), y = r.y - up(i) - 34;   // the line's end, or the edge on a phone
      if (!stops.length) stops.push([.02, x + 50, y - 36, 0]);
      stops.push([at(i), x, y], [at(i) + step * .9, x, y]);
    });
    // each part of the diff appears when the ghost writes that file
    $$('.ln', sec).forEach((l, j) => {
      const w = at(lines.findIndex((p) => p.textContent.startsWith(`Wrote ${l.dataset.wrote}`))) + (j % 7) * .01;
      anims.push(move(l, [{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0% 0 0)' }], w, w + .03, 'steps(12, end)'));
    });
    const [, x, y] = stops.at(-1);
    stops.push([.9, x, y], [.97, x + 30, y - 60, 0]);
    anims.push(flight($('.runner', sec), stops));
    return { anims, draw: (k) => sec.classList.toggle('green', k >= ok) };
  },

  dawn(sec) {   // the briefing rises as the ghosts sink back into the ground
    return { anims: [
      move($('.brief', sec), [{ opacity: 0, transform: 'translateY(70px) scale(.96)' }, { opacity: 1, transform: 'none' }], .02, .3),
      ...$$('.brief .row', sec).map((r, i) => move(r, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'none' }], .14 + i * .06, .24 + i * .06)),
      ...$$('.sinking .spirit', sec).map((s, i) => move(s, [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(70px)' }], .42 + i * .06, .72 + i * .06)),
    ] };
  },
};

// ---- the night: scroll drives the scenes, the chapter in the middle of the screen sets the sky and the clock ---
const sections = $$('main > section');
const tracks = [];
const digits = $$('.clock .d > span');
let current = sections[0], width = innerWidth, lastY = scrollY, lean = 0, queued = false;

function progress(sec) {   // how far you are through a chapter, 0 to 1
  const r = sec.getBoundingClientRect(), vh = innerHeight;
  if (sec.id === 'top') return clamp(-r.top / (r.height * .8));
  // pinned: from when the chapter fills most of the screen until its stage lets go; otherwise across its pass
  return pinned.matches ? clamp((.4 * vh - r.top) / (r.height - .6 * vh)) : clamp((.85 * vh - r.top) / (r.height + .25 * vh));
}

function setClock(hhmm) {
  [...hhmm].forEach((v, i) => { if (digits[i].textContent !== v) digits[i].textContent = v; });
}
const minutes = (t) => +t.slice(0, 2) * 60 + +t.slice(3);
function clock(sec, k) {   // the minutes run on as you scroll, from this chapter's time to just before the next one's
  if (!sec.dataset.time) return;
  const a = minutes(sec.dataset.time), next = sections[sections.indexOf(sec) + 1]?.dataset.time;
  const b = next ? minutes(next) + (minutes(next) < a ? 1440 : 0) : a;
  const m = Math.round(a + (b - a) * k * .98) % 1440;
  setClock(String(Math.floor(m / 60)).padStart(2, '0') + String(m % 60).padStart(2, '0'));
}

function build() {   // (re)measure every scene: on load, and when the page's width changes
  for (const t of tracks.splice(0)) t.anims.forEach((a) => a.cancel());
  for (const sec of sections) if (scenes[sec.id]) tracks.push({ sec, k: -1, ...scenes[sec.id](sec) });
  width = innerWidth;
  frame();
}

function frame() {
  queued = false;
  const vh = innerHeight;
  for (const t of tracks) {
    const r = t.sec.getBoundingClientRect();
    if (r.bottom < -vh || r.top > 2 * vh) continue;   // only chapters on or near the screen
    const k = progress(t.sec);
    if (k === t.k) continue;
    t.k = k;
    for (const a of t.anims) a.currentTime = k * 1000;
    t.draw?.(k);
  }
  const now = tracks.find((t) => t.sec === current);
  if (now) clock(current, now.k);
  const v = scrollY - lastY;   // the ghosts lean into your scrolling, and settle when you stop
  lastY = scrollY;
  lean += (clamp(v / 60, -1, 1) - lean) * .18;
  if (Math.abs(lean) < .003) lean = 0;
  root.style.setProperty('--lean', lean.toFixed(3));
  root.style.setProperty('--stretch', Math.abs(lean).toFixed(3));
  if (lean) request();
}
function request() {
  if (!queued) { queued = true; requestAnimationFrame(frame); }
}

function enter(sec) {
  current = sec;
  root.dataset.sky = sec.dataset.sky;
  root.classList.toggle('clock-on', Boolean(sec.dataset.time));
  root.style.setProperty('--p', (sections.indexOf(sec) / (sections.length - 1)).toFixed(3));
  if (still && sec.dataset.time) setClock(sec.dataset.time.replace(':', ''));
  else request();
}
const io = new IntersectionObserver((entries) => {
  for (const e of entries) if (e.isIntersecting) enter(e.target);
}, { rootMargin: '-48% 0px -48% 0px' });
sections.forEach((s) => io.observe(s));

if (!still) {
  document.fonts.ready.then(build);
  let later;
  addEventListener('resize', () => {   // a phone's address bar changes only the height: no need to measure again
    clearTimeout(later);
    later = setTimeout(() => (innerWidth !== width ? build() : request()), 150);
  });
  pinned.addEventListener('change', build);
  addEventListener('scroll', request, { passive: true });
}

// ---- install ------------------------------------------------------------------------------------------------
const cmd = $('#cmd').textContent.trim();
const copyBtn = $('#copy'), status = $('#copied');
const isMac = /Mac/.test(navigator.userAgent) && navigator.maxTouchPoints < 2;
if (!isMac) $('#phone').hidden = false;
async function copy(message) {
  try {
    await navigator.clipboard.writeText(cmd);
    copyBtn.classList.add('done');
    $('span', copyBtn).textContent = 'Copied';
    status.textContent = message;
    setTimeout(() => { copyBtn.classList.remove('done'); $('span', copyBtn).textContent = 'Copy'; }, 2400);
  } catch {
    getSelection().selectAllChildren($('#cmd'));
    status.textContent = 'Press ⌘C to copy it.';
  }
}
copyBtn.addEventListener('click', () => copy('Copied. Paste it into Terminal.'));
// the hero's button copies the line too, then flies through the night to it
$$('[data-install]').forEach((a) => a.addEventListener('click', () => { if (isMac) copy('The line is copied. Paste it into Terminal.'); }));
