// The graveyard on your Mac. Evening: leave a note. Night: one lane per ghost, live from the night's Temporal history
// (the Code ghost's lane is its terminal). Morning: the briefing, with Tidy / Undo and Keep / Exorcise.
// Every bit of text from letters, chats, files or the model goes in with textContent: nothing from a night is parsed as HTML.
const $ = (id) => document.getElementById(id);
const LABELS = { reply: 'Reply', fyi: 'FYI', newsletter: 'News', automated: 'Automated', suspicious: 'Possessed', unread: 'Not read before dawn' };
const APPS = { imessage: 'Messages', whatsapp: 'WhatsApp', slack: 'Slack' };
const LINKS = /^(sms:\+?[\w@.-]+$|whatsapp:\/\/send\?phone=\d+$|slack:\/\/channel\?team=\w+&id=\w+$)/;   // the only shapes the readers make
const LANES = [   // ghost, its name, its color, the step it repeats, what it works through
  ['mail', 'Mail ghost', 'mail', 'triage_email', 'mail'], ['messages', 'Messages ghost', 'msgs', 'read_thread', 'threads'],
  ['files', 'Files ghost', 'files', 'read_file_item', 'files'], ['calendar', 'Calendar ghost', 'cal', 'prep_meeting', 'events'],
  ['code', 'Code ghost', 'code']];
let token = null;

function h(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
const hm = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '');
function spirit(color) {
  const s = h('span', `spirit ${color}`), body = h('span', 'body');
  body.append(h('i'));
  s.append(body);
  return s;
}
async function api(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Token': token }, body: JSON.stringify(body || {}) });
  return r.json();
}

// ---- the night: what each ghost has done so far ---------------------------------------------------------------
function terminal(steps) {   // the Code ghost's real commands, as a terminal shows them
  const out = [];
  for (const s of steps) {
    const r = s.result || {};
    if (s.act === 'open_worktree') out.push(['c', `$ git worktree add … ${r.branch}`]);
    if (s.act === 'run_tool') {
      out.push(['c', r.tool === 'run_tests' ? `$ ${r.path || 'run the tests'}` : r.tool === 'search' ? `$ git grep -n -E ${r.path}` : `ghost> ${r.tool} ${r.path || ''}`]);
      (r.out || []).forEach((line) => out.push([r.passed === false ? 'o bad' : r.passed ? 'o ok' : 'o', line]));
    }
    if (s.act === 'commit_work') out.push(['c', '$ git commit'], ['o', r.sha ? `${r.sha}  ${r.stat}` : 'nothing to commit']);
  }
  return out;
}

function board(night) {
  const steps = night.steps.filter((s) => s.outcome === 'done');
  const inv = steps.find((s) => s.act === 'gather')?.result;
  const forecast = steps.find((s) => s.act === 'forecast_dawn')?.result;
  const peeks = steps.filter((s) => s.act === 'check_sleep').length;
  $('keeper').textContent = !inv ? 'Gathering the day…'
    : !forecast ? `The ghosts wait in their graves until you're asleep${peeks ? ` (looked ${peeks} times)` : ''}.`
    : `TabPFN expects you up around ${hm(forecast.wake)}.${new Date(forecast.dawn) > Date.now() ? ` The briefing will be ready by ${hm(forecast.dawn)}.` : ''}`;
  const lanes = $('lanes');
  lanes.replaceChildren();
  if (!inv) return;
  for (const [ghost, name, color, act, of] of LANES) {
    const li = h('li', `lane ${color}`), text = h('div', 'what');
    const mine = steps.filter((s) => s.ghost === ghost);
    li.append(spirit(color), text);
    text.append(h('b', '', name));
    if (ghost === 'code') {
      const term = h('div', 'term');
      for (const [cls, line] of terminal(mine).slice(-8)) term.append(h('p', cls, line));
      if (!term.childElementCount) term.append(h('p', 'o', 'waiting for the Keeper’s plan…'));
      text.append(term);
    } else {
      const done = mine.filter((s) => s.act === act), all = inv[of] || [], last = done.at(-1);
      const item = last && all.find((x) => x.id === last.target.split(':')[1]);
      const r = last?.result || {};
      const about = !item ? 'waiting for its turn with the candle'
        : ghost === 'mail' ? `${LABELS[r.label] ?? r.label}: ${item.from}, ${item.subject}`
        : ghost === 'messages' ? `${LABELS[r.label] ?? r.label}: ${item.with} on ${APPS[item.app] ?? item.app}`
        : ghost === 'files' ? `${item.name}${r.move_to ? ` → ${r.move_to}` : ''}`
        : `prepared ${item.title}`;
      const bar = h('span', 'progress'), fill = h('i');
      fill.style.setProperty('--k', String(all.length ? done.length / all.length : 0));   // CSSOM, allowed by the page's CSP
      bar.append(fill);
      text.append(h('span', '', about), bar);
      li.append(h('em', '', `${done.length} of ${all.length}`));
    }
    lanes.append(li);
  }
}

// ---- the morning briefing -------------------------------------------------------------------------------------
function group(box, label, items, each) {
  if (!items.length) return;
  const g = h('div', `group g-${label}`);
  g.append(h('p', 'group-head', `${LABELS[label] ?? label} · ${items.length}`));
  items.forEach((x) => g.append(each(x)));
  box.append(g);
}
function draft(text, what = 'Drafted reply (not sent)') {
  const d = h('details', 'draft');
  d.append(h('summary', '', what), h('p', '', text));
  return d;
}

function briefing(b, night) {
  const n = b.night, f = n.forecast || {};
  const ended = { done: 'The ghosts finished everything', dawn: 'Dawn came first', awake: 'You woke up, so the ghosts stopped',
    'no sleep tonight': 'You never fell asleep, so the ghosts stayed in their graves' }[n.ended] ?? n.ended;
  $('night-line').textContent = [`${ended} (${hm(n.finished)}).`, n.plan?.message,
    f.wake && `TabPFN expected you back at the Mac around ${hm(f.wake)}, after ${f.nights} nights of learning.`,
    n.model && `Model: ${n.model}, on this Mac.`].filter(Boolean).join(' ');
  const problems = $('problems');
  problems.replaceChildren(...(b.problems || []).map((p) => h('li', '', p)));

  const mail = $('mail');
  mail.replaceChildren();
  for (const label of ['reply', 'suspicious', 'fyi', 'newsletter', 'unread']) {
    group(mail, label, b.mail.filter((m) => m.label === label), (m) => {
      const box = h('div', 'item');
      box.append(h('b', '', m.from), ' ', h('span', 'muted', m.subject));
      if (m.why && label !== 'newsletter') box.append(h('div', 'why', m.why));
      if (label === 'suspicious' && m.caught_by?.length) box.append(h('div', 'meta bad', `Caught by ${m.caught_by.join(' and ')}. Nothing in it was followed.`));
      if (m.draft) box.append(draft(m.draft));
      if (m.message_id && !n.persona) {
        const a = h('a', 'meta', n.gmail ? 'Open in Gmail' : 'Open in Mail');
        a.href = n.gmail ? `https://mail.google.com/mail/u/0/#search/rfc822msgid%3A${encodeURIComponent(m.message_id)}`
          : `message://${encodeURIComponent(`<${m.message_id}>`)}`;
        box.append(a);
      }
      return box;
    });
  }

  const chats = $('messages');
  chats.replaceChildren();
  for (const label of ['reply', 'suspicious', 'fyi', 'automated', 'unread']) {
    group(chats, label, (b.messages || []).filter((t) => t.label === label), (t) => {
      const box = h('div', 'item');
      box.append(h('b', '', t.with), ' ', h('span', 'app', APPS[t.app] ?? t.app));
      if (t.why) box.append(h('div', 'why', t.why));
      if (label === 'suspicious' && t.caught_by?.length) box.append(h('div', 'meta bad', `Caught by ${t.caught_by.join(' and ')}. Nothing in it was followed.`));
      if (t.draft) box.append(draft(t.draft));
      if (LINKS.test(t.link || '') && !n.persona) {
        const a = h('a', 'meta', `Open in ${APPS[t.app]}`);
        a.href = t.link;
        box.append(a);
      }
      return box;
    });
  }
  if (b.skipped) chats.append(h('p', 'muted', `${b.skipped} one-time code${b.skipped > 1 ? 's' : ''} or password reset${b.skipped > 1 ? 's' : ''} left alone: no ghost read ${b.skipped > 1 ? 'them' : 'it'}.`));
  if (!(b.messages || []).length && !b.skipped) chats.append(h('p', 'muted', 'No chats tonight.'));

  const today = $('today');
  today.replaceChildren();
  const fileName = Object.fromEntries(b.files.map((x) => [x.id, x.name]));
  const from = Object.fromEntries([...b.mail.map((m) => [m.id, `${m.from}'s letter`]), ...(b.messages || []).map((t) => [t.id, `${t.with}'s chat`])]);
  const named = (text) => text.replace(/\b[fmt]\d{2}\b/g, (id) => fileName[id] ?? from[id] ?? id);
  for (const e of b.today) {
    const li = h('li');
    li.append(h('span', 'when', e.all_day ? 'all day' : e.start.slice(11, 16)), h('b', '', e.title));
    if (e.clashes?.length) li.append(' ', h('span', 'clash', `clashes with ${e.clashes.map((id) => b.today.find((x) => x.id === id)?.title ?? id).join(', ')}`));
    const ul = h('ul');
    (e.prep || []).forEach((p) => ul.append(h('li', '', named(p))));
    const linked = [...new Set([...(e.letters || []).map((id) => from[id]), ...(e.files || []).map((id) => fileName[id])])].filter(Boolean);
    if (linked.length) ul.append(h('li', 'muted', `Have open: ${linked.join(' · ')}`));
    li.append(ul);
    today.append(li);
  }

  const files = $('files');
  files.replaceChildren();
  for (const x of b.files) {
    const li = h('li');
    li.append(h('b', '', x.name), ' ', h('span', 'muted', x.folder));
    if (x.move_to) li.append(' ', h('span', 'to', `→ ${x.move_to}`));
    if (x.answers) li.append(' ', h('span', 'found', `you asked for ${x.answers}`));
    li.append(h('div', 'why', x.summary || ''));
    const checks = (x.check || []).filter((c) => c.length > 4 && !/^n\/?a$/i.test(c));
    if (checks.length) {
      const ul = h('ul');
      checks.forEach((c) => ul.append(h('li', '', c)));
      li.append(ul);
    }
    files.append(li);
  }
  tidyBox(b.files.filter((x) => x.move_to).length);

  const code = $('code');
  code.replaceChildren();
  for (const c of b.code) {
    const box = h('div', 'repo');
    box.append(h('b', '', c.repo), ' ', h('code', 'branch', c.branch || ''));
    box.append(h('p', '', `“${c.goal}”`), h('p', 'muted', c.summary || ''));
    if (c.passed != null) box.append(h('p', c.passed ? 'ok' : 'bad', c.passed ? "Tests pass on the ghost's branch." : "Tests still fail on the ghost's branch."));
    const term = h('div', 'term');
    for (const [cls, line] of terminal(night.steps.filter((s) => s.ghost === 'code' && s.outcome === 'done'))) term.append(h('p', cls, line));
    if (term.childElementCount) box.append(term);
    if (c.diff) {
      const d = h('details');
      d.append(h('summary', '', c.stat?.split('\n').pop() || 'the change'), h('pre', '', c.diff));
      box.append(d);
    }
    if (c.state === 'done' && c.sha) {
      const acts = h('div', 'acts'), keep = h('button', 'cta', 'Keep'), gone = h('button', 'quiet', 'Exorcise');
      keep.title = 'Keep the branch to merge yourself';
      gone.title = "Delete the ghost's branch and its copy";
      keep.onclick = () => settle('keep', c, box);
      gone.onclick = () => settle('exorcise', c, box);
      acts.append(keep, gone);
      box.append(acts);
    }
    code.append(box);
  }

  const log = $('log');
  log.replaceChildren();
  for (const s of night.steps) {
    const li = h('li');
    li.append(h('span', 't', hm(new Date(new Date(night.header.started).getTime() + s.t * 1000).toISOString())), h('span', '', s.ghost),
      h('span', s.attempt > 1 ? 'again' : '', `${s.act.replaceAll('_', ' ')}: ${s.outcome}${s.attempt > 1 ? ` (attempt ${s.attempt})` : ''}`));
    log.append(li);
  }
}

function tidyBox(count, moved = null) {   // Tidy moves the files into the folders the ghost picked; Undo puts them back
  const box = $('tidy');
  box.replaceChildren();
  if (!count) return;
  const go = h('button', moved == null ? 'cta' : 'quiet', moved == null ? 'Tidy' : 'Undo');
  box.append(h('span', '', moved == null ? `${count} file${count > 1 ? 's' : ''} ready for a folder.` : `Moved ${moved}.`), go);
  go.onclick = async () => {
    go.disabled = true;
    const res = await api(moved == null ? '/api/tidy' : '/api/untidy');
    if (res.error) box.replaceChildren(h('span', 'bad', res.error));
    else tidyBox(count, moved == null ? res.moved : null);
  };
}

async function settle(what, c, box) {
  box.querySelectorAll('.acts button').forEach((b) => { b.disabled = true; });
  const res = await api(`/api/${what}`, { repo: c.repo, branch: c.branch });
  box.querySelector('.acts').replaceWith(h('p', 'muted', res.error ? res.error
    : what === 'keep' ? `Kept: ${c.branch} is yours to merge.` : 'Exorcised: the branch and its copy are gone.'));
}

// ---- evening, night, morning ----------------------------------------------------------------------------------
function show(st) {
  const night = st.night, b = night?.briefing;
  $('status').textContent = st.running ? 'A night is running.' : b ? `Last night: ${hm(b.night.finished)}` : '';
  $('evening').hidden = st.running;
  $('night').hidden = !st.running;
  $('briefing').hidden = st.running || !b;
  document.body.classList.toggle('morning', !st.running && Boolean(b));
  if (st.running && night) board(night);
  else if (b) briefing(b, night);
}

async function poll() {
  try {
    const st = await (await fetch('/api/state', { cache: 'no-store' })).json();
    token = st.token;
    show(st);
    setTimeout(poll, st.running ? 5000 : 60000);
  } catch {
    $('status').textContent = "The graveyard isn't open: run graveyard-shift.";
  }
}

$('goodnight').onclick = async () => {
  $('goodnight').disabled = true;
  await api('/api/goodnight', { note: $('note').value });
  $('status').textContent = "Goodnight. The ghosts wait in their graves until you're asleep.";
  setTimeout(poll, 3000);
};
$('awake').onclick = async () => {
  $('awake').disabled = true;
  await api('/api/awake');
  $('status').textContent = 'The ghosts are finishing the step in hand and writing your briefing.';
  setTimeout(poll, 3000);
};
poll();
