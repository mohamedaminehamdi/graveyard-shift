// The page: plays a night (a recorded one on the web, the live or last one on your Mac), then the morning briefing.
// Every bit of text from letters, files or the model goes in with textContent: nothing from a night is ever parsed as HTML.
import { createScene, URNS, GHOSTS } from './scene.js';

const $ = (id) => document.getElementById(id);
const SHOWN = new Set(['gather', 'check_sleep', 'llm_turn', 'forecast_dawn', 'triage_email', 'read_file_item', 'prep_meeting',
  'open_worktree', 'run_tool', 'commit_work']);
const PACE = { gather: 2600, check_sleep: 520, llm_turn: 1500, forecast_dawn: 2800, triage_email: 1500, read_file_item: 1800,
  prep_meeting: 1800, open_worktree: 1700, run_tool: 850, commit_work: 2000 };
const SPEEDS = [1, 2, 4];
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

let night, steps = [], scene, i = 0, playing = !reduced, speed = 1, run = 0, local = null, looping = false;
const scrub = $('scrub');

function h(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
const at = (secs) => new Date(new Date(night.header.started).getTime() + secs * 1000);
const hm = (d) => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

// ---- the player ---------------------------------------------------------------------------------------------
function counts() {
  const s = scene.state(), inv = s.inv, c = $('counts');
  const n = (o) => Object.keys(o).length;
  const t = s.tomb;
  const code = !t.open ? '' : t.sha ? `${inv.repos[0]}: committed` : `${inv.repos[0]}: tests ${t.tests ? 'pass' : 'fail'}`;
  const parts = [[n(s.mail), inv.mail.length, 'letters'], [n(s.files), inv.files.length, 'files'], [n(s.meetings), inv.events.length, 'meetings']];
  c.replaceChildren();
  parts.forEach(([a, b, what], k) => {
    if (k) c.append(' · ');
    c.append(h('b', '', `${a}/${b}`), ` ${what}`);
  });
  if (code) c.append(' · ', h('b', '', code));
  if (s.model) c.append(' · ', s.model);
  const step = steps[Math.min(i, steps.length - 1)];
  $('clock').textContent = step ? hm(at(i >= steps.length ? step.end : step.t)) : '';
}

async function loop() {
  const my = ++run;
  looping = true;
  while (playing && my === run && i < steps.length) {
    await scene.play(steps[i], (PACE[steps[i].act] + (steps[i].attempt > 1 ? 2600 : 0)) / speed, (i + 1) / steps.length);
    if (my !== run) return;
    i++;
    scrub.value = i;
    counts();
  }
  if (my === run) looping = false;
  if (my === run && i >= steps.length && !local?.running) morning(true);   // a live night: wait for more steps
}

function seek(k) {
  run++;
  i = Math.max(0, Math.min(k, steps.length));
  scene.seek(i);
  scrub.value = i;
  counts();
  morning(i >= steps.length && !local?.running);
  if (playing && i < steps.length) loop();
}

function setPlaying(on) {
  playing = on;
  document.body.classList.toggle('paused', !on);
  $('play').setAttribute('aria-label', on ? 'Pause' : 'Play');
  if (on) { if (i >= steps.length && !local?.running) seek(0); else loop(); } else { run++; looping = false; }
}

let dawned = false;
function morning(on) {
  if (on === dawned) return;
  dawned = on;
  scene.dawn(on);
  document.body.classList.toggle('morning', on);
  $('briefing').hidden = !on && !reduced;
  if (on) $('cap-who').textContent = '', $('cap-line').textContent = 'Dawn. The ghosts sink back into the ground.',
  $('cap-detail').textContent = night.briefing ? 'The briefing is below.' : '';
}

// ---- the morning briefing -----------------------------------------------------------------------------------
function briefing(b) {
  if (!b) return;
  const n = b.night, f = n.forecast || {};
  const ended = { done: 'The ghosts finished everything', dawn: 'Dawn came first', awake: 'You woke up, so the ghosts stopped', 'no sleep tonight': 'You never fell asleep, so the ghosts stayed in their graves' }[n.ended] ?? n.ended;
  $('night-line').textContent = [`${ended} (${hm(new Date(n.finished))}).`, n.plan?.message,
    f.wake && `TabPFN expected you back at the Mac around ${f.wake.slice(11, 16)}, after ${f.nights} nights of learning.`,
    n.model && `Model: ${n.model}, on this Mac.`].filter(Boolean).join(' ');

  const mail = $('mail');
  mail.replaceChildren();
  for (const [label, name] of URNS) {
    const items = b.mail.filter((m) => m.label === label);
    if (!items.length) continue;
    const g = h('div', `group g-${label}`);
    const p = h('p');
    p.append(h('i'), `${name} · ${items.length}`);
    g.append(p);
    if (label === 'newsletter') {
      const wrap = h('div', 'compact');
      items.forEach((m) => wrap.append(h('span', '', m.from)));
      g.append(wrap);
    } else if (label === 'fyi') {
      const wrap = h('div', 'rows');
      items.forEach((m) => { const row = h('div'); row.title = m.why || ''; row.append(h('b', '', m.from), ' ', h('span', '', m.subject)); wrap.append(row); });
      g.append(wrap);
    } else items.forEach((m) => g.append(letter(m, label)));
    mail.append(g);
  }
  const unread = b.mail.filter((m) => !URNS.some(([l]) => l === m.label));
  if (unread.length) {
    const g = h('div', 'group g-unread'), wrap = h('div', 'rows');
    g.append(h('p', '', `Not read before dawn · ${unread.length}`));
    unread.forEach((m) => { const row = h('div'); row.append(h('b', '', m.from), ' ', h('span', '', m.subject)); wrap.append(row); });
    g.append(wrap);
    mail.append(g);
  }

  const today = $('today');
  today.replaceChildren();
  const fileName = Object.fromEntries(b.files.map((f) => [f.id, f.name]));
  const mailFrom = Object.fromEntries(b.mail.map((m) => [m.id, `${m.from}: ${m.subject}`]));
  for (const e of b.today) {
    const li = h('li');
    li.append(h('span', 'when', e.all_day ? 'all day' : e.start.slice(11, 16)), h('b', '', e.title));
    if (e.clashes?.length) li.append(' ', h('span', 'clash', `clashes with ${e.clashes.map((id) => b.today.find((x) => x.id === id)?.title ?? id).join(', ')}`));
    const ul = h('ul');
    const named = (t) => t.replace(/\b[fm]\d{2}\b/g, (id) => fileName[id] ?? (mailFrom[id] ? `${mailFrom[id].split(':')[0]}'s letter` : id));
    (e.prep || []).forEach((p) => ul.append(h('li', '', named(p))));
    const linked = [...(e.letters || []).map((id) => mailFrom[id]), ...(e.files || []).map((id) => fileName[id])].filter(Boolean);
    if (linked.length) ul.append(h('li', 'what', `Have open: ${linked.join(' · ')}`));
    li.append(ul);
    today.append(li);
  }

  const files = $('files');
  files.replaceChildren();
  for (const f of b.files) {
    const li = h('li');
    li.append(h('b', '', f.name), ' ', h('span', 'what', `${f.folder}`));
    if (f.answers) li.append(' ', h('span', 'found', `★ you asked for ${f.answers}`));
    li.append(h('div', 'what', f.summary || ''));
    const checks = (f.check || []).filter((c) => c.length > 4 && !/^n\/?a$/i.test(c));
    if (checks.length) {
      const ul = h('ul');
      checks.forEach((c) => ul.append(h('li', '', c)));
      li.append(ul);
    }
    files.append(li);
  }

  const code = $('code');
  code.replaceChildren();
  for (const c of b.code) {
    const box = h('div', 'repo');
    box.append(h('b', '', c.repo), ' ', h('code', '', c.branch || ''));
    box.append(h('p', '', `“${c.goal}”`));
    box.append(h('p', '', c.summary || ''));
    if (c.passed != null) box.append(h('p', c.passed ? 'ok' : 'bad', c.passed ? 'Tests pass on the ghost\'s branch.' : 'Tests still fail on the ghost\'s branch.'));
    if (c.diff) {
      const d = h('details'), s = h('summary', '', c.stat?.split('\n').pop() || 'the change');
      d.append(s, h('pre', '', c.diff));
      box.append(d);
    }
    if (local && c.state === 'done' && c.sha) {
      const acts = h('div', 'acts'), keep = h('button', 'keep', 'Keep'), gone = h('button', 'exorcise', 'Exorcise');
      keep.title = 'Keep the branch to merge yourself'; gone.title = 'Delete the ghost\'s branch and its copy';
      keep.onclick = () => act('keep', c, box); gone.onclick = () => act('exorcise', c, box);
      acts.append(keep, gone);
      box.append(acts);
    } else if (!local) box.append(h('p', 'what', 'On your Mac: Keep (merge it yourself) or Exorcise (it never happened).'));
    code.append(box);
  }

  const log = $('log');
  log.replaceChildren();
  for (const s of steps) {
    const li = h('li');
    li.append(h('span', 't', hm(at(s.t))), h('span', '', GHOSTS[s.ghost] ?? s.ghost), h('span', s.attempt > 1 ? 'again' : '', line(s)));
    log.append(li);
  }
}

function letter(m, label) {
  const box = h('div', 'letter');
  box.append(h('span', 'who', m.from), ' ', h('span', 'subj', m.subject));
  if (m.why) box.append(h('div', 'why', m.why));
  if (label === 'suspicious' && m.caught_by?.length) box.append(h('div', 'meta', `Caught by ${m.caught_by.join(' and ')}. Nothing in it was followed.`));
  if (m.draft) {
    const d = h('details');
    d.append(h('summary', '', 'Drafted reply (not sent)'), h('pre', '', m.draft));
    box.append(d);
  }
  if (local && m.message_id && !night.briefing?.night?.persona) {
    const a = h('a', 'meta', 'Open in Mail');
    a.href = `message://${encodeURIComponent(`<${m.message_id}>`)}`;
    box.append(a);
  }
  return box;
}

function line(s) {
  const r = s.result || {};
  if (s.outcome !== 'done') return `${s.act.replace('_', ' ')}: ${s.outcome}`;
  switch (s.act) {
    case 'triage_email': return `${r.label}: ${r.why}`;
    case 'read_file_item': return `${r.kind}: ${r.summary}`;
    case 'prep_meeting': return `${r.prep} prep notes`;
    case 'llm_turn': return r.plan ? 'planned the night' : r.calls?.map((c) => `${c.name} ${c.path}`).join(', ') || 'thought';
    case 'run_tool': return `${r.tool} ${r.path || ''}${r.passed != null ? (r.passed ? ' → pass' : ' → fail') : ''}`;
    case 'forecast_dawn': return `TabPFN: awake around ${r.wake?.slice(11, 16)}, briefing by ${r.dawn?.slice(11, 16)}`;
    case 'open_worktree': return `opened ${r.branch}`;
    case 'commit_work': return r.sha ? `committed ${r.sha}` : 'nothing to commit';
    case 'gather': return `gathered ${r.mail.length} letters, ${r.files.length} files, ${r.events.length} meetings`;
    case 'check_sleep': return `idle ${r.idle_min} min`;
    default: return s.act;
  }
}

// ---- local mode: your own nights, Keep / Exorcise ------------------------------------------------------------
async function api(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Token': local.token }, body: JSON.stringify(body || {}) });
  return r.json();
}
async function poll() {   // a live night: Temporal's history keeps growing, so does the replay
  const st = await (await fetch('/api/state', { cache: 'no-store' })).json();
  local = { ...local, ...st };
  if (!st.night) return setTimeout(poll, 5000);
  if (!scene) return start(st.night), setTimeout(poll, 5000);
  const fresh = st.night.steps.filter(keep);
  if (fresh.length > steps.length) {
    steps.push(...fresh.slice(steps.length));
    scrub.max = steps.length;
    if (playing && !looping) loop();
  }
  night = st.night;
  if (st.running) setTimeout(poll, 5000);
  else { briefing(night.briefing); $('evening').hidden = false; if (playing && !looping) loop(); }
}

async function goodnight() {
  $('goodnight').disabled = true;
  await api('/api/goodnight', { note: $('note').value });
  $('evening').hidden = true;
  $('cap-line').textContent = 'Goodnight. The ghosts wait in their graves until you\'re asleep.';
  local.running = true;
  setTimeout(poll, 3000);
}

async function act(what, c, box) {
  box.querySelectorAll('button').forEach((b) => { b.disabled = true; });
  const res = await api(`/api/${what}`, { repo: c.repo, branch: c.branch });
  box.querySelector('.acts').replaceWith(h('p', 'what', res.error ? res.error : what === 'keep' ? `Kept: ${c.branch} is yours to merge.` : 'Exorcised: the branch and its copy are gone.'));
}

// ---- the install sheet (Pages only) -------------------------------------------------------------------------
function installSheet() {
  const dialog = $('install'), cmd = $('cmd').textContent, copy = $('copy');
  const onMac = /Macintosh/.test(navigator.userAgent) && !('ontouchend' in document);
  async function copyCmd() {
    try {
      await navigator.clipboard.writeText(cmd);
      copy.textContent = 'Copied';
      dialog.classList.add('copied');
    } catch {
      getSelection().selectAllChildren($('cmd'));
      copy.textContent = 'Press ⌘C';
    }
  }
  $('phone').hidden = onMac;
  $('install-open').addEventListener('click', () => { dialog.showModal(); if (onMac) copyCmd(); });
  copy.addEventListener('click', copyCmd);
  $('install-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', (e) => { if (e.target === dialog) dialog.close(); });
}

// ---- start --------------------------------------------------------------------------------------------------
const keep = (s) => SHOWN.has(s.act) && (s.act !== 'run_tool' || s.result);

async function main() {
  installSheet();
  if (new URLSearchParams(location.search).has('local')) {   // opened by the app on your Mac
    try { local = await (await fetch('/api/state', { cache: 'no-store' })).json(); } catch { /* not running */ }
  }
  document.body.classList.toggle('local', !!local);
  if (local) {
    $('goodnight').onclick = goodnight;
    $('evening').hidden = local.running;
    if (local.running) setTimeout(poll, 5000);
    if (!local.night) return;
  }
  start(local?.night ?? await (await fetch('replay/night.json', { cache: 'no-store' })).json());
}

function start(n) {
  night = n;
  steps = night.steps.filter(keep);
  const inv = steps.find((s) => s.act === 'gather')?.result;
  if (!inv) return;
  scene = createScene($('scene'), { box: $('caption'), who: $('cap-who'), line: $('cap-line'), detail: $('cap-detail') });
  scene.build(inv, steps, night.briefing?.night?.deadline);
  scrub.max = steps.length;
  briefing(night.briefing);
  counts();
  $('play').onclick = () => setPlaying(!playing);
  $('speed').onclick = () => { speed = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length]; $('speed').textContent = `${speed}×`; };
  $('skip').onclick = () => seek(steps.length);
  scrub.oninput = () => seek(+scrub.value);
  addEventListener('resize', () => scene.rebuildIfNeeded(inv));
  if (reduced) { setPlaying(false); seek(steps.length); } else loop();
}
main();
