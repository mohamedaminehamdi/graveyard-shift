// One night, scrolled. As each chapter reaches the middle of the screen it sets the clock and the sky, and plays its
// scene once: finished stays finished. Without JS, or with reduced motion, every scene simply shows how it ends.
const root = document.documentElement;
const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
const EASE = 'cubic-bezier(.16, 1, .3, 1)';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
// animate from a state to wherever the element's CSS puts it, holding the start state during the delay
const from = (el, frame, opts) => el.animate([{ offset: 0, ...frame }], { duration: 700, easing: EASE, fill: 'backwards', ...opts });

if (!still) root.classList.add('ready');

// ---- the clock ---------------------------------------------------------------------------------------------
const digits = $$('.clock .d');
function roll(d, v) {
  const old = d.lastElementChild;
  if (old?.textContent === v) return;
  const next = document.createElement('span');
  next.textContent = v;
  d.append(next);
  if (still || !old) return old?.remove();
  old.animate([{ translate: '0 0', opacity: 1 }, { translate: '0 -80%', opacity: 0 }], { duration: 420, easing: EASE }).onfinish = () => old.remove();
  next.animate([{ translate: '0 80%', opacity: 0 }, { translate: '0 0', opacity: 1 }], { duration: 560, easing: EASE });
}

function countUp(el, delay, duration) {
  const to = Number(el.dataset.to ?? el.textContent);
  el.dataset.to = to;
  el.textContent = '0';
  const t0 = performance.now() + delay;
  const tick = (now) => {
    const k = Math.min(1, Math.max(0, (now - t0) / duration));
    el.textContent = String(Math.round(to * (1 - (1 - k) ** 3)));
    if (k < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

// ---- the scenes ----------------------------------------------------------------------------------------------
const scenes = {
  async note(sec) {   // the note types itself, Goodnight is pressed, the screen goes dark
    const text = $('.note-text', sec), full = text.textContent;
    text.style.minHeight = `${text.offsetHeight}px`;
    text.textContent = '';
    text.classList.add('typing');
    for (let i = 1; i <= full.length; i++) {
      text.textContent = full.slice(0, i);
      await wait(full[i - 1] === ';' ? 280 : 22);
    }
    await wait(450);
    text.classList.remove('typing');
    $('.goodnight', sec).animate([{ scale: 1 }, { scale: .92 }, { scale: 1 }], { duration: 380, easing: EASE });
    await wait(260);
    sec.classList.add('slept');
  },

  async wait(sec) {   // TabPFN's curve draws itself, then the sleeping spirits wake
    $('.curve .line', sec).animate([{ strokeDasharray: 1, strokeDashoffset: 1 }, { strokeDasharray: 1, strokeDashoffset: 0 }],
      { duration: 2400, delay: 200, easing: 'cubic-bezier(.45, 0, .2, 1)', fill: 'backwards' });
    from($('.curve .area', sec), { opacity: 0 }, { duration: 1400, delay: 1700 });
    from($('.curve .done-by', sec), { opacity: 0 }, { duration: 600, delay: 1900 });
    from($('.curve .up', sec), { opacity: 0 }, { duration: 600, delay: 2300 });
    $$('.flags span', sec).forEach((f, i) => from(f, { opacity: 0, translate: '0 8px' }, { delay: 2000 + i * 260 }));
    await wait(2900);
    sec.classList.add('risen');
  },

  async mail(sec) {   // letters fly in from above and land in their urns, one row at a time
    const b = $('.board', sec).getBoundingClientRect();
    const slips = $$('.col', sec).flatMap((c, ci) => $$('.slip', c).map((s, ri) => ({ s, ci, ri })))
      .sort((p, q) => p.ri - q.ri || p.ci - q.ci).map((x) => x.s);
    slips.forEach((s, i) => {
      const r = s.getBoundingClientRect();
      const dx = b.left + b.width / 2 - (r.left + r.width / 2), dy = b.top - 60 - (r.top + r.height / 2);
      from(s, { opacity: 0, translate: `${dx}px ${dy}px`, rotate: `${i % 2 ? 9 : -9}deg`, scale: .55 }, { duration: 900, delay: 200 + i * 120 });
    });
    const landed = 200 + slips.length * 120 + 700;
    $$('[data-count]', sec).forEach((c) => countUp(c, 250, landed - 250));
    await wait(landed);
    sec.classList.add('caught');
  },

  async files(sec) {   // the Files ghost reads today's files one by one, the contract last, and notes what to check
    const tiles = $$('.file', sec), reader = $('.reader', sec);
    tiles.forEach((t, i) => from(t, { opacity: 0, translate: '0 18px' }, { delay: 100 + i * 70 }));
    await wait(700);
    const g = $('.files', sec).getBoundingClientRect();
    let at;
    for (const t of [...tiles.slice(1), tiles[0]]) {
      const r = t.getBoundingClientRect(), to = `${r.right - g.left - 34}px ${r.top - g.top - 30}px`;
      reader.animate([{ translate: at ?? to, opacity: at ? 1 : 0 }, { translate: to, opacity: 1 }], { duration: at ? 480 : 360, easing: EASE, fill: 'forwards' });
      at = to;
      await wait(380);
      t.classList.add('reading');
      await wait(420);
      t.classList.replace('reading', 'read');
    }
    sec.classList.add('lifted');
    reader.animate([{ translate: at, opacity: 1 }, { translate: at, opacity: 0 }], { duration: 900, delay: 700, fill: 'forwards' });
  },

  async day(sec) {   // tomorrow lays itself out, the 10:00 gets its prep note, the clash lights up
    $$('.agenda > li', sec).forEach((li, i) => from(li, { opacity: 0, translate: '0 16px' }, { delay: 100 + i * 90 }));
    $('.prep', sec).animate([{ opacity: 0, clipPath: 'inset(0 0 100% 0 round 12px)' }, { opacity: 1, clipPath: 'inset(0 0 0% 0 round 12px)' }],
      { duration: 1000, delay: 900, easing: EASE, fill: 'backwards' });
    await wait(1900);
    sec.classList.add('flagged');
  },

  async crash(sec) {   // the worker dies mid-file; Temporal waits out the heartbeat and hands the file to a new one
    const art = $('.crash', sec);
    art.classList.add('glitch');
    await wait(900);
    art.classList.remove('glitch');
    sec.classList.add('dead');
    await wait(1000);
    sec.classList.add('waiting');
    await wait(1700);
    sec.classList.add('back');
    $$('.rest .dots i', sec).forEach((d, i) => from(d, { opacity: .12, scale: .4 }, { duration: 500, delay: i * 28 }));
  },

  async code(sec) {   // the diff types itself out, then the tests come back green
    const lines = $$('.ln', sec);
    lines.forEach((l, i) => l.animate([{ opacity: 1, clipPath: 'inset(0 100% 0 0)' }, { opacity: 1, clipPath: 'inset(0 0% 0 0)' }],
      { duration: 380, delay: 250 + i * 150, easing: 'steps(16, end)', fill: 'backwards' }));
    await wait(250 + lines.length * 150 + 500);
    sec.classList.add('green');
  },

  async dawn(sec) {   // the briefing rises as the ghosts sink back into the ground
    from($('.brief', sec), { opacity: 0, translate: '0 70px', scale: .96 }, { duration: 1300, delay: 250 });
    $$('.brief .row', sec).forEach((r, i) => from(r, { opacity: 0, translate: '0 10px' }, { delay: 900 + i * 160 }));
    await wait(400);
    sec.classList.add('sunk');
  },
};

// ---- the night: whichever chapter is in the middle of the screen sets the time -------------------------------
const sections = $$('main > section');
function enter(sec) {
  root.dataset.sky = sec.dataset.sky;
  root.classList.toggle('clock-on', Boolean(sec.dataset.time));
  if (sec.dataset.time) [...sec.dataset.time.replace(':', '')].forEach((v, i) => roll(digits[i], v));
  root.style.setProperty('--p', (sections.indexOf(sec) / (sections.length - 1)).toFixed(3));
  if (sec.dataset.played) return;
  sec.dataset.played = '1';
  if (!still) scenes[sec.id]?.(sec);
}
const io = new IntersectionObserver((entries) => {
  for (const e of entries) if (e.isIntersecting) enter(e.target);
}, { rootMargin: '-48% 0px -48% 0px' });
sections.forEach((s) => io.observe(s));

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
