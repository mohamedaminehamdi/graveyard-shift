"""When will you wake up? TabPFN learns it from this Mac's own power log.

Falling asleep is easy to see (the Mac goes idle). Waking up is not: the ghosts have to know in advance when the
briefing must be ready. So after lights-out, TabPFN predicts the chance you're back at the Mac in each 15-minute
slot until noon, and the night's deadline ("dawn") is set just before the first likely wake.

Only display on/off and sleep events are read, from /var/log/powermanagement (no admin needed). Nothing leaves the Mac.
"""
import json
import math
import os
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

SLOT = timedelta(minutes=15)
EVENING = 18          # a "night" runs from 18:00 to noon the next day: 72 slots
SLOTS = 72
ACTIVE = 0.2          # display on for at least 3 of a slot's 15 minutes
CAUTIOUS = 0.25       # the deadline: a 1-in-4 chance you've already been up (per-slot thresholds cut it too close)
POWER_LOGS = Path("/private/var/log/powermanagement")
CACHE = Path.home() / ".graveyard-shift" / "power-events.json"
LINE = re.compile(r"^(\w{3} [ \d]\d \d\d:\d\d:\d\d) .*?<Notice>: (Display is turned (on|off)|Entering Sleep state)")


# --- the log -------------------------------------------------------------------------------------------------

def read_power_log():
    """[(time, on?)] display transitions, newest days cached so the history outlives the log's two-week rotation."""
    seen = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    for f in sorted(POWER_LOGS.glob("*.asl")):
        year = int(f.name[:4])
        out = subprocess.run(["syslog", "-f", str(f)], capture_output=True, text=True).stdout
        day = []
        for line in out.splitlines():
            m = LINE.match(line)
            if m:
                t = datetime.strptime(f"{year} {m.group(1)}", "%Y %b %d %H:%M:%S")
                day.append([t.isoformat(), m.group(3) == "on"])
        if day:
            seen[f.name[:10]] = day
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(seen))
    events = sorted((datetime.fromisoformat(t), on) for day in seen.values() for t, on in day)
    return events


def on_fraction(events, start, n=SLOTS):
    """For n slots from start: the share of each slot the display was on."""
    out, i, on = [0.0] * n, 0, False
    while i < len(events) and events[i][0] <= start:
        on = events[i][1]
        i += 1
    t = start
    for k in range(n):
        end, covered = t + SLOT, 0.0
        while i < len(events) and events[i][0] < end:
            if on:
                covered += (events[i][0] - t).total_seconds()
            t, on = events[i][0], events[i][1]
            i += 1
        if on:
            covered += (end - t).total_seconds()
        out[k] = covered / SLOT.total_seconds()
        t = end
    return out


def nights(events):
    """Every complete night in the log: its 72 slots (1 = at the Mac) and when the lights went out."""
    if not events:
        return []
    first, last = events[0][0].date(), events[-1][0].date()
    found = []
    for k in range((last - first).days):
        evening = datetime.combine(first + timedelta(days=k), datetime.min.time()) + timedelta(hours=EVENING)
        if evening + SLOTS * SLOT > events[-1][0]:
            break
        active = [int(f >= ACTIVE) for f in on_fraction(events, evening)]
        out = lights_out(active)
        if out is not None:
            found.append({"evening": evening, "active": active, "out": out})
    return found


def lights_out(active):
    """The slot where the night's longest stretch away from the Mac begins (at least 3 hours, starting 20:00-05:00)."""
    best, start = None, None
    for k, a in enumerate(active + [1]):
        if not a and start is None:
            start = k
        elif a and start is not None:
            begin = max(start, 8)  # away since the evening: count the night from 20:00
            if begin <= 44 and k - begin >= 12 and (best is None or k - begin > best[1] - best[0]):
                best = (begin, k)
            start = None
    return best[0] if best else None


# --- features ------------------------------------------------------------------------------------------------

def rows(night, history, out):
    """Features for each slot after lights-out. Only what is known at lights-out: no peeking at the morning."""
    wake_day = (night["evening"] + timedelta(days=1)).weekday()
    freq = [sum(h["active"][k] for h in history) / len(history) if history else math.nan for k in range(SLOTS)]
    prev = [history[-d]["active"] if len(history) >= d else None for d in (1, 2)]
    X = []
    for k in range(out, SLOTS):
        hour = EVENING + k / 4
        X.append([math.sin(2 * math.pi * hour / 24), math.cos(2 * math.pi * hour / 24), (k - out) / 4, out / 4,
                  wake_day, int(wake_day >= 5), *(p[k] if p else math.nan for p in prev), freq[k]])
    return X


def training_set(history):
    X, y = [], []
    for i, night in enumerate(history):
        X += rows(night, history[:i], night["out"])
        y += night["active"][night["out"]:]
    return X, y


def first_wake(probs, out, threshold):
    """The first slot, at least 2 hours after lights-out, where being back at the Mac is likely enough."""
    for k, p in enumerate(probs):
        if k >= 8 and p >= threshold:
            return out + k
    return SLOTS


def deadline(probs, out, chance=CAUTIOUS):
    """The first slot by which you've probably been up at least once: many small per-slot chances add up."""
    asleep = 1.0
    for k, p in enumerate(probs):
        if k >= 8:
            asleep *= 1 - p
            if 1 - asleep >= chance:
                return out + k
    return SLOTS


# --- models --------------------------------------------------------------------------------------------------

def tabpfn():
    os.environ.setdefault("TABPFN_DISABLE_TELEMETRY", "1")
    import warnings
    warnings.filterwarnings("ignore", message="Running on CPU")  # a few hundred rows: seconds on CPU, and the GPU stays Gemma's
    from tabpfn import TabPFNClassifier
    from tabpfn.constants import ModelVersion
    # v2 weights: open (Apache 2.0 + attribution), no account or token; newer versions need a Prior Labs login
    return TabPFNClassifier.create_default_for_version(ModelVersion.V2, device="cpu")


def predict(model, X_train, y_train, X):
    import numpy as np
    if len(set(y_train)) < 2:
        return [float(y_train[0]) if y_train else 0.5] * len(X)
    model.fit(np.array(X_train, dtype=float), np.array(y_train))
    return [float(p) for p in model.predict_proba(np.array(X, dtype=float))[:, 1]]


def forecast(lights_out_at, events=None):
    """Tonight's chance of being back at the Mac per slot, the likely wake time, and the deadline for the ghosts."""
    history = nights(events if events is not None else read_power_log())
    evening = datetime.combine((lights_out_at - timedelta(hours=EVENING if lights_out_at.hour < EVENING else 0)).date(),
                               datetime.min.time()) + timedelta(hours=EVENING)
    out = max(0, min(SLOTS - 1, int((lights_out_at - evening) / SLOT)))
    if len(history) < 3:  # a new Mac: a cautious default until a few nights are logged
        dawn = (evening + timedelta(hours=12, minutes=15)).astimezone()
        return {"nights": len(history), "dawn": dawn.isoformat(), "wake": dawn.isoformat(), "curve": []}
    X_train, y_train = training_set(history)
    tonight = {"evening": evening, "active": [0] * SLOTS, "out": out}
    probs = predict(tabpfn(), X_train, y_train, rows(tonight, history, out))
    at = lambda k: (evening + k * SLOT).astimezone()
    early = deadline(probs, out)
    return {"nights": len(history), "wake": at(first_wake(probs, out, 0.5)).isoformat(),
            "dawn": (at(early) - SLOT).isoformat(),   # a quarter-hour before you've probably been up
            "curve": [[at(out + k).strftime("%H:%M"), round(p, 2)] for k, p in enumerate(probs)]}


def evaluate(events=None):
    """Walk-forward: each night is predicted only from the nights before it, like the ghosts do for real."""
    from sklearn.linear_model import LogisticRegression
    history = nights(events if events is not None else read_power_log())
    scores = {name: {"brier": [], "wake_error_min": [], "late": 0} for name in ("tabpfn", "slot_frequency", "same_as_yesterday", "logistic")}
    tested = 0
    model = tabpfn()
    for i in range(3, len(history)):
        past, night = history[:i], history[i]
        out = night["out"]
        truth = night["active"][out:]
        X_train, y_train = training_set(past)
        X = rows(night, past, out)
        filled = lambda M: [[0.5 if math.isnan(v) else v for v in r] for r in M]
        guesses = {
            "tabpfn": predict(model, X_train, y_train, X),
            "slot_frequency": [r[-1] for r in X],
            "same_as_yesterday": [float(past[-1]["active"][k]) for k in range(out, SLOTS)],
            "logistic": list(LogisticRegression(max_iter=2000).fit(filled(X_train), y_train).predict_proba(filled(X))[:, 1]),
        }
        actual_wake = first_wake(truth, out, 0.5)
        for name, p in guesses.items():
            s = scores[name]
            s["brier"].append(sum((a - b) ** 2 for a, b in zip(p, truth)) / len(truth))
            s["wake_error_min"].append(abs(first_wake(p, out, 0.5) - actual_wake) * 15)
            s["late"] += deadline(p, out) - 1 > actual_wake  # the briefing would not have been ready in time
        tested += 1
    summary = {"nights_logged": len(history), "nights_tested": tested}
    for name, s in scores.items():
        if tested:
            summary[name] = {"brier": round(sum(s["brier"]) / tested, 3),
                             "wake_error_min": round(sum(s["wake_error_min"]) / tested),
                             "late_briefings": s["late"]}
    return summary


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=1))


def idle_minutes():
    """Minutes since anyone touched the keyboard, trackpad or mouse."""
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem", "-d", "4"], capture_output=True, text=True).stdout
    m = re.search(r'"HIDIdleTime" = (\d+)', out)
    return int(m.group(1)) / 6e10 if m else 0.0


def on_ac():
    return "AC Power" in subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
