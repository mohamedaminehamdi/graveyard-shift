# Graveyard Shift 👻

**Ghost agents that work your night shift.** Leave a note at bedtime ("write tests for slugify in my blog repo; find the
contract Hans sent; prep my 10:00"). While you sleep, four ghosts go through your inbox, today's files, tomorrow's
calendar and your repo on **local Gemma 4**. In the morning there is one briefing: letters sorted, replies drafted (never
sent), meetings prepared, the contract found, and a branch with the tests written. Keep it or exorcise it.

**[Watch a recorded night](https://mohamedaminehamdi.github.io/graveyard-shift/)**: every move on that page is one step
from the night's Temporal history, replayed.

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
| **Dusk** | Your letters, today's files and tomorrow's agenda are gathered while you're still awake, so macOS asks its permission questions then, not at 2 am. |
| **Graves** | The ghosts wait (a durable Temporal timer) and peek every 5 minutes until the Mac has been idle for 20 minutes and is on power. |
| **The Keeper** | Reads your note, asks **TabPFN** when you'll probably wake up, and plans the night. The briefing is due before then. |
| **Work** | The Mail, Files, Calendar and Code ghosts work at the same time but take turns on the GPU: there is one candle (a Temporal task queue with room for one Gemma call). |
| **Dawn** | When everything is done, at the deadline, or when you touch the Mac: the briefing. |

### The ghosts

- **Mail ghost**: sorts each letter into Reply / FYI / News / Possessed and drafts replies. It has **no tools at all**: it
  reads one letter as data and answers in a fixed JSON shape. Letters that try to give orders to an AI are marked
  *Possessed* (by Gemma, plus a plain rule as a backstop).
- **Files ghost**: reads what you saved today, says what each file is and what to check before you sign, pay or send it,
  and finds what your note asked for. No tools; it never moves anything.
- **Calendar ghost**: prepares each meeting from the letters and files read tonight, and flags clashes. Never accepts or
  declines.
- **Code ghost**: the only one with tools (list, read, search, write, run tests, diff). It works in a git worktree on its
  own `ghost/…` branch. Paths can't leave the worktree, and the tests run under `sandbox-exec`: no network, no writes
  outside the worktree, no reads of `~/.ssh`, `~/Library` or your documents. It commits on its branch; it never merges
  or pushes. **Keep** leaves the branch for you; **Exorcise** deletes it.

Nothing a ghost writes is sent anywhere. There is no send, forward, accept, move or delete in the code.

## Why Temporal

The night is one `NightShift` workflow. The workflow only decides; every side effect (reading a letter, each Gemma call,
each tool call, each test run) is an activity with a timeout and retries, and long Gemma calls heartbeat every 10 seconds.
The Temporal server runs as its own process with a sqlite file, so if the app crashes, the Mac reboots or the lid gets
closed, the night picks up where it stopped, and finished work is never done twice. The recorded night on the demo page
includes a `kill -9` of the whole app in the middle of a letter.

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
  "mail": true,
  "folders": ["~/Downloads", "~/Desktop", "~/Documents"]
}
```

- **Calendar**: Google Calendar > Settings > your calendar > *Secret address in iCal format*. No API key, no macOS
  permission.
- **Mail**: `"mail": true` copies today's inbox out of Mail.app (add your Google account in System Settings > Internet
  Accounts). The script only reads.
- **Model**: the biggest Gemma 4 that fits in free memory tonight. On a 24 GB MacBook Air with Chrome and an editor open
  that's `gemma4:e4b`; with room, `gemma4:26b-a4b-it-qat`.

```text
graveyard-shift                open the graveyard (note, Goodnight, briefing)
graveyard-shift night [--now]  work tonight; run it again after a crash and it resumes
graveyard-shift demo           a night on Marisol's (fictional) day, starting now
graveyard-shift awake          tell the ghosts you're up
graveyard-shift sleep-eval     TabPFN against simpler guesses, on your power log
```

## Uninstall

```sh
graveyard-shift --uninstall && uv tool uninstall graveyard-shift
```

Your nights and settings stay in `~/.graveyard-shift` until you delete it.

## The demo night

The day on the demo page belongs to Marisol Vega, who doesn't exist: 28 letters (one tries to possess the ghosts), six
meetings (two clash), a contract with a nasty clause, and a blog repo whose `slugify` mangles "Día de los Muertos". Her
files live in [`graveyard_shift/persona`](graveyard_shift/persona). The ghosts, Gemma 4, TabPFN and Temporal were real
and ran on a MacBook Air M3; [`history.json`](graveyard_shift/web/replay/history.json) is that night's raw Temporal
history, and CI rebuilds the page's replay from it and fails if they differ.

## License

MIT. The TabPFN v2 weights (downloaded at install) are under the Prior Labs License, Apache 2.0 with an attribution
requirement; a copy is in [`graveyard_shift/TABPFN_LICENSE.txt`](graveyard_shift/TABPFN_LICENSE.txt). Gemma 4 is under
Google's Gemma terms.
