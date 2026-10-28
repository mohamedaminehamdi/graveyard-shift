"""Everything the ghosts read is a file: .eml letters, an .ics calendar, recent files, git repos.

The same readers serve the fictional persona (the demo) and your own Mac: Mail.app exports each message's raw
source as .eml, Google Calendar's "secret address in iCal format" is an .ics, and Spotlight lists recent files.
Gathering happens at dusk, while you're still awake to answer any macOS permission prompt.
"""
import email
import email.policy
import html
import os
import re
import shutil
import subprocess
import urllib.request
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

FIXTURES = Path(__file__).resolve().parent / "persona"
TEXT_KINDS = {".txt", ".md", ".csv", ".json", ".html", ".htm", ".py", ".js", ".ics", ".tex", ".log"}
SENSITIVE = re.compile(r"\.(pem|key|p12|pfx|kdbx|env|keychain)$|id_(rsa|ed25519|ecdsa)|wallet|passw|secret|credential|token", re.I)
MAX_MAIL = 80
MAX_FILES = 40


# --- letters -------------------------------------------------------------------------------------------------

def read_eml(path, limit=4000):
    """Headers and plain text of one message. HTML is reduced to text; it is never rendered anywhere."""
    msg = email.message_from_bytes(Path(path).read_bytes(), policy=email.policy.default)
    part = msg.get_body(preferencelist=("plain", "html"))
    try:
        text = part.get_content() if part else ""
    except (LookupError, ValueError):  # an unknown charset: keep what decodes
        text = part.get_payload(decode=True).decode("utf-8", "replace")
    if part and part.get_content_type() == "text/html":
        text = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", "", text)))
    try:
        when = parsedate_to_datetime(str(msg["Date"])) if msg["Date"] else None
    except (TypeError, ValueError):
        when = None
    return {
        "id": Path(path).stem,
        "from": str(msg["From"] or ""),
        "subject": str(msg["Subject"] or "(no subject)"),
        "date": when.isoformat() if when else "",
        "message_id": str(msg["Message-ID"] or "").strip("<>"),
        "body": re.sub(r"\n{3,}", "\n\n", text).strip()[:limit],
    }


EXPORT_MAIL = """set cutoff to (current date) - (1 * days)
set out to {}
tell application "Mail"
\trepeat with m in (messages of inbox whose date received > cutoff)
\t\tif (count of out) > %d then exit repeat
\t\tset end of out to (source of m)
\tend repeat
end tell
set AppleScript's text item delimiters to (character id 30)
return out as text""" % (MAX_MAIL - 1)


def export_mail(dest):
    """Copy the last day of your inbox out of Mail.app as .eml files. Read-only: this script can't send or move."""
    r = subprocess.run(["osascript", "-e", EXPORT_MAIL], capture_output=True, text=True, timeout=900)
    if r.returncode:
        raise PermissionError(f"Mail.app said no ({r.stderr.strip()[:120]}). Allow it in System Settings > Privacy > Automation.")
    dest.mkdir(parents=True, exist_ok=True)
    sources = [s for s in r.stdout.split("\x1e") if s.strip()]
    for n, src in enumerate(sources, 1):
        (dest / f"m{n:02d}.eml").write_text(src)
    return len(sources)


# --- calendar ------------------------------------------------------------------------------------------------

def _when(value, params, tz):
    if params.get("VALUE") == "DATE" or len(value) == 8:
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    t = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return t.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    return t.replace(tzinfo=ZoneInfo(params["TZID"]) if "TZID" in params else tz).astimezone(tz)


def _unescape(v):
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def local_tz():
    """This Mac's timezone with its DST rules (not just today's offset)."""
    try:
        return ZoneInfo(os.path.realpath("/etc/localtime").split("zoneinfo/", 1)[1])
    except (IndexError, KeyError, ValueError):
        return datetime.now().astimezone().tzinfo


def read_ics(text, tz=None):
    """VEVENTs from an .ics feed, times in your timezone."""
    tz = tz or local_tz()
    events, ev = [], None
    for line in re.sub(r"\r?\n[ \t]", "", text).splitlines():
        if line == "BEGIN:VEVENT":
            ev = {"attendees": []}
        elif line == "END:VEVENT" and ev is not None:
            if "start" in ev and ev.get("status") != "CANCELLED":
                events.append(ev)
            ev = None
        elif ev is not None and ":" in line:
            key, _, value = line.partition(":")
            name, *rest = key.split(";")
            params = dict(p.split("=", 1) for p in rest if "=" in p)
            if name in ("DTSTART", "DTEND"):
                ev["start" if name == "DTSTART" else "end"] = _when(value, params, tz)
            elif name in ("SUMMARY", "LOCATION", "DESCRIPTION"):
                ev[{"SUMMARY": "title", "LOCATION": "where", "DESCRIPTION": "notes"}[name]] = _unescape(value)
            elif name == "ATTENDEE":
                ev["attendees"].append(re.sub(r"(?i)^mailto:", "", value))
            elif name in ("UID", "RRULE", "STATUS"):
                ev[name.lower()] = value
    return events


def _recurs_on(ev, day):
    """Daily and weekly RRULEs, enough for standups and 1:1s."""
    # ponytail: ignores COUNT, EXDATE and monthly rules; a full RFC 5545 expander if real calendars need it
    rule = dict(p.split("=", 1) for p in ev["rrule"].split(";") if "=" in p)
    first = ev["start"] if isinstance(ev["start"], date) and not isinstance(ev["start"], datetime) else ev["start"].date()
    if day < first or ("UNTIL" in rule and day.strftime("%Y%m%d") > rule["UNTIL"][:8]):
        return False
    every = int(rule.get("INTERVAL", 1))
    if rule.get("FREQ") == "DAILY":
        return (day - first).days % every == 0
    if rule.get("FREQ") == "WEEKLY":
        names = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
        days = [d[-2:] for d in rule.get("BYDAY", names[first.weekday()]).split(",")]
        return names[day.weekday()] in days and ((day - first).days // 7) % every == 0
    return False


def events_on(events, day):
    """One day's agenda, sorted, with repeating events moved onto that day and overlaps marked."""
    out = []
    for ev in events:
        start, end = ev["start"], ev.get("end") or ev["start"]
        all_day = not isinstance(start, datetime)
        first = start if all_day else start.date()
        if first != day:
            if "rrule" not in ev or not _recurs_on(ev, day):
                continue
            shift = timedelta(days=(day - first).days)
            start, end = start + shift, end + shift
        out.append({
            "id": re.sub(r"[^\w.-]", "_", ev.get("uid", ev.get("title", "event")))[:60],
            "title": ev.get("title", "(no title)"), "where": ev.get("where", ""), "notes": ev.get("notes", "")[:600],
            "attendees": ev["attendees"][:12], "all_day": all_day, "start": start, "end": end,
        })
    out.sort(key=lambda e: (not e["all_day"], str(e["start"])))
    timed = [e for e in out if not e["all_day"]]
    for a in out:
        a["clashes"] = [b["id"] for b in timed if b is not a and not a["all_day"] and a["start"] < b["end"] and b["start"] < a["end"]]
    for e in out:
        e["start"], e["end"] = e["start"].isoformat(), e["end"].isoformat()
    return out


def fetch_ics(url):
    """Google Calendar > Settings > your calendar > Secret address in iCal format. No key, no macOS permission."""
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


# --- files ---------------------------------------------------------------------------------------------------

def recent_files(folders, hours=24):
    """Files changed in the last day, via Spotlight. Hidden, sensitive and huge files are skipped."""
    args = ["mdfind"] + [a for f in folders for a in ("-onlyin", str(Path(f).expanduser()))]
    r = subprocess.run(args + [f"kMDItemFSContentChangeDate >= $time.now(-{hours * 3600})"],
                       capture_output=True, text=True, timeout=120)
    paths = [Path(p) for p in r.stdout.splitlines()]
    return [p for p in paths if p.is_file() and not any(s.startswith(".") for s in p.parts)
            and not SENSITIVE.search(p.name) and p.stat().st_size < 50_000_000][:MAX_FILES]


def read_text(path, limit=4000):
    """Readable text of a file, or None for photos, archives and the like."""
    path = Path(path)
    try:
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            text = "\n".join((page.extract_text() or "") for page in PdfReader(path).pages[:3])
        elif path.suffix.lower() in TEXT_KINDS:
            text = path.read_text(errors="replace")
        else:
            return None
    except Exception:
        return None
    return text.strip()[:limit] or None


# --- repos ---------------------------------------------------------------------------------------------------

def git(repo, *args, check=True):
    """git with hooks off: a repo's own hooks never run on the ghosts' behalf."""
    r = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=120)
    if check and r.returncode:
        raise RuntimeError(f"git {args[0]} failed: {r.stderr.strip()[:200]}")
    return r.stdout


def persona_repo(dest):
    """The persona's blog repo as a real git repo, with history and one stale branch. Same result every time."""
    if (dest / ".git").exists():
        return dest
    shutil.copytree(FIXTURES / "repo" / "inkwell", dest, ignore=shutil.ignore_patterns("__pycache__"))
    env = {"GIT_AUTHOR_NAME": "Marisol Vega", "GIT_AUTHOR_EMAIL": "marisol@hollowlane.example",
           "GIT_COMMITTER_NAME": "Marisol Vega", "GIT_COMMITTER_EMAIL": "marisol@hollowlane.example"}

    def commit(msg, when):
        stamp = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
        subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-C", str(dest), "commit", "-qm", msg],
                       check=True, env={**env, **stamp, "PATH": "/usr/bin:/bin:/opt/homebrew/bin"})

    git(dest, "init", "-q", "-b", "main")
    git(dest, "add", "-A")
    commit("inkwell: posts in, pages out", "2026-09-14T10:00:00+02:00")
    git(dest, "checkout", "-q", "-b", "old-theme")
    (dest / "theme.css").write_text("body { font-family: Georgia, serif; }\n")
    git(dest, "add", "theme.css")
    commit("try a serif theme", "2026-09-16T21:30:00+02:00")
    git(dest, "checkout", "-q", "main")
    return dest


def repo_status(repo):
    """What the code ghost reports about a repo: stale branches, uncommitted work, TODOs. Read-only."""
    now = datetime.now().timestamp()
    refs = git(repo, "for-each-ref", "--format=%(refname:short)\t%(committerdate:unix)", "refs/heads")
    branches = [line.split("\t") for line in refs.splitlines() if "\t" in line]
    todos = git(repo, "grep", "-n", "-I", "-E", r"\b(TODO|FIXME)\b", check=False).splitlines()
    return {"branch": git(repo, "branch", "--show-current").strip(),
            "stale": [name for name, ts in branches if now - int(ts) > 30 * 86400 and not name.startswith("ghost/")],
            "uncommitted": len(git(repo, "status", "--porcelain").splitlines()),
            "todos": todos[:5], "todo_count": len(todos)}
