# Graveyard Shift 👻

**Ghost agents that work your night shift.** Leave a note at bedtime ("write tests for slugify in my blog repo; find the
contract Hans sent; prep my 10:00"). While you sleep, five ghosts go through your Gmail, your texts, WhatsApp and Slack,
today's files, tomorrow's calendar and your repo on **local Gemma 4**. In the morning there is one briefing: letters and
chats sorted, replies drafted (never sent), a folder picked for each loose file (press Tidy to move them, Undo to put them
back), meetings prepared, the contract found, and a branch with the tests written. Keep it or exorcise it.

**[See how a night goes](https://mohamedaminehamdi.github.io/graveyard-shift/)**, told from a real recorded night: the
letters, files, meetings, crash and code on that page come from its Temporal history.

Built with PriorLabs-TabPFN, Gemma 4 and Temporal. Everything runs on your Mac.

## Install (macOS, Apple silicon)

```sh
curl -fsSL https://mohamedaminehamdi.github.io/graveyard-shift/install.sh | sh
```

No admin password. It installs uv, Graveyard Shift, Ollama + Gemma 4, TabPFN's open v2 weights, the Temporal dev server
binary and a Graveyard Shift app in `~/Applications`. [Read the script](install.sh) first if you like.

At bedtime: open the app, leave a note, press **Goodnight**, and **leave the Mac open and plugged in**. A closed MacBook
sleeps whatever any app asks, so the ghosts can't work with the lid shut.

## How a night goes

| Phase | What happens |
| --- | --- |
| **Dusk** | Your letters, today's chats and files, and tomorrow's agenda are gathered while you're still awake, so macOS asks its permission questions then, not at 2 am. One-time codes are dropped here, before any ghost sees them. |
| **Graves** | The ghosts wait (a durable Temporal timer) and peek every 5 minutes until the Mac has been idle for 20 minutes and is on power. |
| **The Keeper** | Reads your note, asks **TabPFN** when you'll probably wake up, and plans the night. The briefing is due before then. |
| **Work** | The Mail, Messages, Files, Calendar and Code ghosts work at the same time but take turns on the GPU: there is one candle (a Temporal task queue with room for one Gemma call). |
| **Dawn** | When everything is done, at the deadline, or when you touch the Mac: the briefing. |

### The ghosts

- **Mail ghost**: sorts each letter into Reply / FYI / News / Possessed and drafts replies. It has **no tools at all**: it
  reads one letter as data and answers in a fixed JSON shape. Letters that try to give orders to an AI are marked
  *Possessed* (by Gemma, plus a plain rule as a backstop).
- **Messages ghost**: reads today's chats from Messages (iMessage and SMS), WhatsApp for Mac and Slack DMs, one
  conversation at a time, the same way: no tools, a fixed JSON answer, drafts that are never sent, and the same
  *Possessed* rule. One-time codes and password resets are removed at dusk and never reach it.
- **Files ghost**: reads what you saved today, says what each file is and what to check before you sign, pay or send it,
  and finds what your note asked for. For each loose file in Downloads or Desktop it picks one of your folders in
  Documents (it can only pick from that list). Nothing moves at night: in the morning **Tidy** moves them, never over an
  existing file, and **Undo** puts them back.
- **Calendar ghost**: prepares each meeting from the letters and files read tonight, and flags clashes. Never accepts or
  declines.
- **Code ghost**: the only one with tools (list, read, search, write, run tests, diff). It works in a git worktree on its
  own `ghost/…` branch. Paths can't leave the worktree, and the tests run under `sandbox-exec`: no network, no writes
  outside the worktree, no reads of `~/.ssh`, `~/Library` or your documents. It commits on its branch; it never merges
  or pushes. **Keep** leaves the branch for you; **Exorcise** deletes it.

Nothing a ghost writes is sent anywhere. There is no send, forward, accept or delete in the code, and files move only
when you press Tidy. The ghosts think offline; the only network reads happen at dusk: your calendar feed and, if you
connect them, Gmail (read-only IMAP: nothing is even marked read) and Slack (read-only API calls).

## Why Temporal

The night is one `NightShift` workflow. The workflow only decides; every side effect (reading a letter, each Gemma call,
each tool call, each test run) is an activity with a timeout and retries, and long Gemma calls heartbeat every 10 seconds.
The Temporal server runs as its own process with a sqlite file, so if the app crashes, the Mac reboots or the lid gets
closed, the night picks up where it stopped, and finished work is never done twice. The recorded night includes a
`kill -9` of the worker while it was reading a contract: after 60 seconds without a heartbeat, a new worker read that
file again, and none of the 20 finished steps before it ran twice.

`tests/test_night.py` runs the real workflow on a real Temporal dev server and checks: a whole night, dawn cutting it
short (the briefing is still written), "I'm awake" ending it early, and a dead worker costing no finished work.

## Why TabPFN

Falling asleep is easy to see: the Mac goes idle. Waking up isn't, and the briefing has to be ready before it happens.
After lights-out, TabPFN predicts, for each 15-minute slot until noon, the chance you're back at the Mac. It uses only
what's known at lights-out (time of night, weekday, when the lights went out, your last nights), learned in context from
this Mac's own power log (`/var/log/powermanagement`; display on/off and sleep events). The deadline is the moment you've
probably (1 in 4) been up already.

On my Mac (13 nights logged, each night predicted only from the nights before it):

| Model | Brier score | Wake-time error | Late briefings |
| --- | --- | --- | --- |
| **TabPFN** | **0.062** | **80 min** | 3 / 10 |
| each slot's frequency | 0.078 | 184 min | 2 / 10 |
| same as yesterday | 0.136 | 255 min | 3 / 10 |
| logistic regression | 0.075 | 102 min | 4 / 10 |

Run `graveyard-shift sleep-eval` for yours. It uses the open TabPFN v2 weights, so no account or token is needed.

## Your own nights

Settings live in `~/.graveyard-shift/config.json`:

```json
{
  "name": "Ada",
  "repos": [{"name": "blog", "path": "~/code/blog", "test": "python3 -m pytest -q"}],
  "ics": ["https://calendar.google.com/calendar/ical/…/basic.ics"],
  "gmail": "ada@gmail.com",
  "messages": ["imessage", "whatsapp", "slack"],
  "folders": ["~/Downloads", "~/Desktop", "~/Documents"]
}
```

- **Calendar**: Google Calendar > Settings > your calendar > *Secret address in iCal format*. No API key, no macOS
  permission.
- **Gmail**: `graveyard-shift connect gmail ada@gmail.com`. Make an
  [app password](https://myaccount.google.com/apppasswords) (it needs 2-Step Verification) and paste it when asked; it goes
  into your Keychain, never into a file. The ghosts read your inbox over IMAP in read-only mode. Some work accounts don't
  allow app passwords: use Mail.app then.
- **Mail.app**: `"mail": true` copies today's inbox out of Mail.app instead. The script only reads.
- **Messages and WhatsApp**: allow **Full Disk Access** for Graveyard Shift (System Settings > Privacy & Security). Both
  databases are opened read-only. WhatsApp's format isn't documented; if it changes, the briefing says it skipped it.
- **Slack**: make a Slack app at api.slack.com/apps with the user scopes `im:history`, `im:read`, `mpim:history`,
  `mpim:read` and `users:read`, install it, then `graveyard-shift connect slack` and paste the `xoxp-` token.
- `graveyard-shift check` shows what the ghosts could read tonight, as counts only.
- **Model**: the biggest Gemma 4 that fits in free memory tonight. On a 24 GB MacBook Air with Chrome and an editor open
  that's `gemma4:e4b`; with room, `gemma4:26b-a4b-it-qat`.

```text
graveyard-shift                open the graveyard (note, Goodnight, briefing)
graveyard-shift night [--now]  work tonight; run it again after a crash and it resumes
graveyard-shift demo           a night on Marisol's (fictional) day, starting now
graveyard-shift awake          tell the ghosts you're up
graveyard-shift connect gmail ada@gmail.com    keep a Gmail app password in your Keychain (or: connect slack)
graveyard-shift check          what the ghosts could read tonight, as counts only
graveyard-shift sleep-eval     TabPFN against simpler guesses, on your power log
```

## Uninstall

```sh
graveyard-shift --uninstall && uv tool uninstall graveyard-shift
```

Your nights and settings stay in `~/.graveyard-shift` until you delete it.

## The recorded night

The recorded night's day belongs to Marisol Vega, who doesn't exist: 28 letters (one tries to possess the ghosts), eight
chats on three apps (one is a bank's one-time code, one tries to possess the ghosts), six meetings (two clash), a
contract with a nasty clause, and a blog repo whose `slugify` mangles "Día de los Muertos". Her files live in
[`graveyard_shift/persona`](graveyard_shift/persona). The ghosts, Gemma 4, TabPFN and Temporal were real
and ran on a MacBook Air M3; [`history.json`](graveyard_shift/web/replay/history.json) is that night's raw Temporal
history, and CI rebuilds the replay from it and fails if they differ. The
[landing page](https://mohamedaminehamdi.github.io/graveyard-shift/) tells that night.

## License

MIT. The TabPFN v2 weights (downloaded at install) are under the Prior Labs License, Apache 2.0 with an attribution
requirement; a copy is in [`graveyard_shift/TABPFN_LICENSE.txt`](graveyard_shift/TABPFN_LICENSE.txt). Gemma 4 is under
Google's Gemma terms.
