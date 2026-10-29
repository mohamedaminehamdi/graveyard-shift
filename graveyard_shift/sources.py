"""What the ghosts read: letters, chats, a calendar, today's files and git repos. Every reader here only reads.

The same readers serve the fictional persona (the demo) and your own Mac: Gmail (read-only IMAP) or Mail.app give each
letter as an .eml, Messages, WhatsApp and Slack give today's chats, Google Calendar's "secret address in iCal format" is
an .ics, and Spotlight lists recent files. Gathering happens at dusk, while you're still awake to answer any macOS
permission prompt. The one thing here that changes your Mac is Tidy, and only after you press it in the morning.
"""
import email
import email.policy
import html
import imaplib
import json
import os
import re
import shutil
import sqlite3
import ssl
import subprocess
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import cache, partial
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
    # kept on its own clock, so a repeating event keeps its wall-clock time across that zone's DST change
    return t.replace(tzinfo=ZoneInfo("UTC") if value.endswith("Z") else ZoneInfo(params["TZID"]) if "TZID" in params else tz)


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
            ev = {"attendees": [], "tz": tz}
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
    """One day's agenda in your timezone, sorted, with repeating events moved onto that day and overlaps marked."""
    out = []
    for ev in events:
        start, end = ev["start"], ev.get("end") or ev["start"]
        all_day = not isinstance(start, datetime)
        first = start if all_day else start.date()   # on the event's own clock
        # your day can begin or end on the event's day before or after (a 23:00 New York call is 05:00 in Berlin)
        for own in [day] if all_day else [day - timedelta(days=1), day, day + timedelta(days=1)]:
            if own != first and ("rrule" not in ev or not _recurs_on(ev, own)):
                continue
            shift = timedelta(days=(own - first).days)   # whole days on its own clock, then onto yours
            s, e = (start + shift, end + shift) if all_day else ((start + shift).astimezone(ev["tz"]), (end + shift).astimezone(ev["tz"]))
            if (s if all_day else s.date()) != day:
                continue
            out.append({
                "id": re.sub(r"[^\w.-]", "_", ev.get("uid", ev.get("title", "event")))[:60],
                "title": ev.get("title", "(no title)"), "where": ev.get("where", ""), "notes": ev.get("notes", "")[:600],
                "attendees": ev["attendees"][:12], "all_day": all_day, "start": s, "end": e,
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


# --- tidy: the Files ghost suggests a folder at night; you press Tidy in the morning ------------------------

def destinations(base, limit=40):
    """Folders a loose file could go into: the ones in base and one level down, as names relative to it."""
    try:
        tops = sorted(p for p in Path(base).iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith("."))
        out = []
        for top in tops:
            out += [top.name] + [f"{top.name}/{p.name}" for p in sorted(top.iterdir())
                                 if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")]
        return out[:limit]
    except OSError:   # no access to Documents: nothing to suggest
        return []


def tidy(night):
    """Move each file into the folder the Files ghost suggested, once you've pressed Tidy. Never deletes, never
    overwrites, never leaves tonight's folders; each move goes in tidy.json first, so Undo can put it back."""
    night = Path(night)
    where = json.loads((night / "folders.json").read_text())
    base, allowed = Path(where["base"]).resolve(), set(where["folders"])
    files = {f["id"]: f for f in json.loads((night / "files.json").read_text())}
    journal = night / "tidy.json"
    done = json.loads(journal.read_text()) if journal.exists() else []
    for f in json.loads((night / "briefing.json").read_text())["files"]:
        item, to = files.get(f.get("id")), f.get("move_to")
        if not item or not item.get("movable") or to not in allowed or any(d["id"] == item["id"] for d in done):
            continue
        src, dest = Path(item["path"]), (base / to).resolve()
        if base not in dest.parents or not dest.is_dir() or src.is_symlink() or not src.is_file() or SENSITIVE.search(src.name):
            continue
        if (src.stat().st_size, int(src.stat().st_mtime)) != (item["size"], item["mtime"]):
            continue   # changed since the ghost read it: yours to file
        target, n = dest / src.name, 2
        while target.exists():
            target, n = dest / f"{src.stem} {n}{src.suffix}", n + 1
        done.append({"id": item["id"], "from": str(src), "to": str(target)})
        journal.write_text(json.dumps(done, indent=1))
        try:
            os.rename(src, target)   # the same disk: a move, never a copy and a delete
        except OSError:
            done.pop()
            journal.write_text(json.dumps(done, indent=1))
    return done


def untidy(night):
    """Undo: every file Tidy moved goes back where it was, unless something new sits there now."""
    journal = Path(night) / "tidy.json"
    left = []
    for move in reversed(json.loads(journal.read_text()) if journal.exists() else []):
        here, home = Path(move["to"]), Path(move["from"])
        if here.is_file() and not home.exists():
            os.rename(here, home)
        else:
            left.append(move)
    journal.write_text(json.dumps(left[::-1], indent=1))
    return left


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


# --- keychain ------------------------------------------------------------------------------------------------

def secret(account):
    """A secret from your login Keychain (service "graveyard-shift"), or None if there isn't one."""
    r = subprocess.run(["security", "find-generic-password", "-s", "graveyard-shift", "-a", account, "-w"],
                       capture_output=True, text=True)
    return None if r.returncode else r.stdout.removesuffix("\n")


def store_secret(account):
    """Keep a secret in your Keychain. `security` asks for it twice in Terminal, unechoed: it never passes through here."""
    r = subprocess.run(["security", "add-generic-password", "-U", "-s", "graveyard-shift", "-a", account, "-w"])
    return r.returncode == 0


# --- gmail ---------------------------------------------------------------------------------------------------

def gmail_letters(address, password, dest, days=1):
    """Your Gmail inbox's last days as .eml files, over IMAP. Read-only: EXAMINE, and PEEK so nothing turns read."""
    dest.mkdir(parents=True, exist_ok=True)
    since = (date.today() - timedelta(days=days)).strftime("%d-%b-%Y")
    # imaplib checks no certificate unless handed a context: the password goes to the real Gmail or nowhere
    with imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=ssl.create_default_context(), timeout=60) as box:
        box.login(address, password)
        box.select("INBOX", readonly=True)
        ids = box.search(None, "SINCE", since)[1][0].split()[-MAX_MAIL:]
        for n, i in enumerate(ids, 1):
            (dest / f"m{n:02d}.eml").write_bytes(box.fetch(i, "(BODY.PEEK[])")[1][0][1])
    return len(ids)


# --- chats ---------------------------------------------------------------------------------------------------

CHAT_DB = Path.home() / "Library/Messages/chat.db"
WHATSAPP_DB = Path.home() / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite"
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def _rows(db, sql, *params):
    """Rows from an app's own database, opened read-only."""
    con = sqlite3.connect(f"{Path(db).absolute().as_uri()}?mode=ro", uri=True)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def _apple_time(t):
    """Seconds since 2001-01-01 UTC, or nanoseconds in newer Messages databases."""
    return APPLE_EPOCH + timedelta(seconds=t / 1e9 if t >= 1e12 else t)


def _threads(app, rows, since, now):
    """(chat, with, link, from, me, text, when) rows as threads: the window's last 20 messages each, newest chat first."""
    threads = {}
    for chat, who, link, sender, me, text, when in sorted(rows, key=lambda r: r[-1]):
        text = (text or "").strip()[:600]
        if text and since <= when <= now:
            t = threads.setdefault(chat, {"app": app, "with": who, "link": link, "messages": []})
            t["messages"].append({"from": sender, "me": bool(me), "text": text, "at": when.isoformat(timespec="seconds")})
    for t in threads.values():
        t["messages"] = t["messages"][-20:]
    return sorted(threads.values(), key=lambda t: t["messages"][-1]["at"], reverse=True)   # all UTC: sorts as text


def _typedstream_text(blob):
    """The text inside an NSAttributedString typedstream (Messages' attributedBody), or "" if there is none."""
    _, found, rest = (blob or b"").partition(b"NSString")
    rest = rest[5:]   # past b"\x01\x94\x84\x01+", the rest of the class header
    if not found or not rest:
        return ""
    wide = {0x81: 2, 0x82: 4}.get(rest[0], 0)   # a longer length comes in the next 2 or 4 bytes, little-endian
    size = int.from_bytes(rest[1:1 + wide], "little") if wide else rest[0]
    return rest[1 + wide:][:size].decode("utf-8", "replace")


def imessage_threads(db=CHAT_DB, hours=24, now=None):
    """The last day of your Messages chats (iMessage and SMS), read-only. chat.db needs Full Disk Access."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    s = (since - APPLE_EPOCH).total_seconds()
    rows = _rows(db, """SELECT c.ROWID, c.chat_identifier, c.display_name, m.is_from_me, h.id, m.text, m.attributedBody, m.date
                        FROM message m JOIN chat_message_join j ON j.message_id = m.ROWID JOIN chat c ON c.ROWID = j.chat_id
                        LEFT JOIN handle h ON h.ROWID = m.handle_id
                        WHERE m.associated_message_type = 0 AND m.item_type = 0
                          AND (m.date >= ? OR m.date BETWEEN ? AND 1e12)""", s * 1e9, s)   # nanoseconds, or older seconds
    out = []
    for chat, ident, name, me, handle, text, body, when in rows:
        one = not name and not ident.startswith("chat")   # one-to-one: the identifier is a phone number or an email
        text = (text or _typedstream_text(body)).replace("￼", "")   # U+FFFC only marks where an attachment sat
        out.append((chat, name or ident, f"sms:{ident}" if one else "", "me" if me else handle or ident, me, text,
                    _apple_time(when)))
    return _threads("imessage", out, since, now)


def whatsapp_threads(db=WHATSAPP_DB, hours=24, now=None):
    """The last day of your WhatsApp chats, read-only from the Mac app's own database (an unofficial schema)."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    rows = _rows(db, """SELECT s.Z_PK, s.ZPARTNERNAME, s.ZCONTACTJID, m.ZISFROMME, m.ZTEXT, m.ZMESSAGEDATE
                        FROM ZWAMESSAGE m JOIN ZWACHATSESSION s ON s.Z_PK = m.ZCHATSESSION
                        WHERE m.ZMESSAGEDATE >= ? AND m.ZTEXT != ''""", (since - APPLE_EPOCH).total_seconds())
    out = []
    for chat, partner, jid, me, text, when in rows:
        number, one = (jid or "").partition("@")[0], (jid or "").endswith("@s.whatsapp.net")   # groups end in @g.us
        who = partner or number
        out.append((chat, who, f"whatsapp://send?phone={number}" if one else "",
                    "me" if me else who if one else "a member", me, text, _apple_time(when)))
    return _threads("whatsapp", out, since, now)


def _slack_get(token, method, params):
    """One read from Slack's Web API: always a GET, the token only in the Authorization header."""
    req = urllib.request.Request(f"https://slack.com/api/{method}?{urllib.parse.urlencode(params)}",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def slack_threads(token, hours=24, now=None, get=None):
    """The last day of your Slack DMs and group DMs, through four read methods of the Web API and nothing else."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    get = get or partial(_slack_get, token)

    def call(method, **params):
        r = get(method, params)
        if not r.get("ok"):
            raise RuntimeError(f"Slack said {r.get('error')}")
        return r

    @cache
    def name(user):
        u = call("users.info", user=user)["user"]
        return u.get("real_name") or u.get("name") or user

    me, rows = call("auth.test"), []
    # ponytail: the first 50 DMs, no cursor paging; follow response_metadata.next_cursor if someone has more
    for ch in call("conversations.list", types="im,mpim", exclude_archived="true", limit=50)["channels"]:
        for m in call("conversations.history", channel=ch["id"], oldest=str(since.timestamp()), limit=20)["messages"]:
            if m.get("subtype") not in (None, "bot_message"):
                continue
            mine = m.get("user") == me["user_id"]
            sender = "me" if mine else name(m["user"]) if m.get("user") else m.get("username") or "a bot"
            rows.append((ch["id"], name(ch["user"]) if ch.get("is_im") else "group DM",
                         f"slack://channel?team={me['team_id']}&id={ch['id']}", sender, mine, m.get("text"),
                         datetime.fromtimestamp(float(m["ts"]), timezone.utc)))
    return _threads("slack", rows, since, now)


# One-time codes and password resets are for you, for a minute: none of them reaches a ghost.
CODES = re.compile(
    r"\b(code|otp|passcode|pin|c[oó]digo)\W{0,3}(is|es)?\W{0,3}(\d{3}[- ]\d{3}|\d{4,8})\b"   # Your OTP is 771204
    r"|\b\d{4,8} (is|es) (your|tu)\b|\b(use|enter)\s+\d{4,8}\s+to\b"                       # G-123456 is your code
    r"|\b(reset|restablec\w*)\b.{0,20}\b(password|contraseña)\b|\bpassword reset\b", re.I)


def drop_codes(threads):
    """The threads without one-time codes or password resets, and how many messages that took out."""
    kept, skipped = [], 0
    for t in threads:
        messages = [m for m in t["messages"] if not CODES.search(m["text"])]
        skipped += len(t["messages"]) - len(messages)
        if messages:
            kept.append({**t, "messages": messages})
    return kept, skipped
