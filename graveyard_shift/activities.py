"""The night's side effects, as Temporal activities.

Thinking (every Gemma call) runs on the "candle" task queue with room for one at a time: the ghosts take turns on the
GPU. Long calls heartbeat every 10 s, so if the worker dies Temporal notices within a minute and retries elsewhere.
Inputs are references (an email's id, a chat's id, a file's id), so the night's history holds no letters, chats or files.
"""
import asyncio
import json
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

from temporalio import activity

from . import ghosts, llm, sandbox, sleep, sources

HOME = Path.home() / ".graveyard-shift"
WORKTREES = HOME / "worktrees"
FOLDERS = ["~/Downloads", "~/Desktop", "~/Documents"]
MAX_THREADS = 30
LOOSE = ("Downloads", "Desktop")   # where the Files ghost may suggest a better folder
FULL_DISK = "allow Full Disk Access for Graveyard Shift in System Settings > Privacy & Security"


async def _beating(fn, *args):
    """Blocking work in a thread, with a heartbeat every 10 s from here."""
    task = asyncio.ensure_future(asyncio.to_thread(fn, *args))
    while True:
        done, _ = await asyncio.wait({task}, timeout=10)
        if done:
            return task.result()
        activity.heartbeat()


def _who(sender):
    name = sender.split("<")[0].strip().strip('"')
    return name or sender.strip("<>")


def _folder(path, base):
    try:
        return str(path.parent.relative_to(base)) or path.parent.name
    except ValueError:
        return path.parent.name


def _letters(night, mail, problems):
    """Today's letters into mail/: from Gmail if you connected it, else from Mail.app if you switched that on."""
    if night.get("gmail"):
        password = sources.secret(f"gmail:{night['gmail']}")
        if not password:
            return problems.append(f"Gmail: run  graveyard-shift connect gmail {night['gmail']}  once")
        try:
            sources.gmail_letters(night["gmail"], password, mail)
        except Exception as e:   # the password stays out of the message: imaplib never echoes it
            problems.append(f"Gmail said no: {str(e)[:160]}")
    elif night.get("mail"):
        sources.export_mail(mail)


def _chats(apps, problems):
    """Today's chats from each app you switched on. One app saying no costs that app, never the night."""
    def slack():
        token = sources.secret("slack")
        if not token:
            raise LookupError("run  graveyard-shift connect slack  once")
        return sources.slack_threads(token)
    readers = {"imessage": sources.imessage_threads, "whatsapp": sources.whatsapp_threads, "slack": slack}
    names = {"imessage": "Messages", "whatsapp": "WhatsApp", "slack": "Slack"}
    threads = []
    for app in apps:
        try:
            threads += readers[app]()
        except (sqlite3.Error, PermissionError):
            problems.append(f"{names[app]}: {FULL_DISK}" if app != "whatsapp" or sources.WHATSAPP_DB.exists()
                            else "WhatsApp: no WhatsApp for Mac on this Mac")
        except Exception as e:
            problems.append(f"{names.get(app, app)}: {str(e)[:160]}")
    return threads


def _gather(night):
    d = Path(night["dir"])
    mail = d / "mail"
    mail.mkdir(parents=True, exist_ok=True)
    problems = []
    if night.get("persona"):
        for p in (sources.FIXTURES / "mail").glob("*.eml"):
            shutil.copy(p, mail / p.name)
        ics = (sources.FIXTURES / "calendar.ics").read_text()
        base = d / "files"   # Marisol's files, copied: in the morning Tidy really moves them
        if not base.exists():
            shutil.copytree(sources.FIXTURES / "files", base)
        for folder in json.loads((sources.FIXTURES / "folders.json").read_text()):
            (base / "Documents" / folder).mkdir(parents=True, exist_ok=True)
        found = sorted(p for p in base.rglob("*") if p.is_file() and not p.name.startswith("."))
        chats = json.loads((sources.FIXTURES / "messages.json").read_text())
        documents = base / "Documents"
        sources.persona_repo(Path(night["repos"][0]["path"]))
    else:
        _letters(night, mail, problems)
        chats = _chats(night.get("messages") or [], problems)
        ics = "\n".join(sources.fetch_ics(url) for url in night.get("ics", []))
        base, found = Path.home(), sources.recent_files(night.get("folders") or FOLDERS)
        documents = Path.home() / "Documents"
    chats, skipped = sources.drop_codes(chats)
    threads = [{"id": f"t{n:02d}", **t} for n, t in enumerate(chats[:MAX_THREADS], 1)]
    (d / "calendar.ics").write_text(ics)
    (d / "threads.json").write_text(json.dumps(threads, ensure_ascii=False))
    folders = sources.destinations(documents)
    (d / "folders.json").write_text(json.dumps({"base": str(documents), "folders": folders}))
    letters = [sources.read_eml(p) for p in sorted(mail.glob("*.eml"))]
    events = sources.events_on(sources.read_ics(ics), date.fromisoformat(night["day"]))
    files = [{"id": f"f{n:02d}", "path": str(p), "name": p.name, "folder": _folder(p, base),
              "kind": p.suffix.lstrip(".").lower() or "file", "movable": _folder(p, base).split("/")[0] in LOOSE,
              "size": p.stat().st_size, "mtime": int(p.stat().st_mtime)} for n, p in enumerate(found, 1)]
    (d / "files.json").write_text(json.dumps(files))
    (d / "events.json").write_text(json.dumps(events))
    return {
        "mail": [{"id": m["id"], "from": _who(m["from"]), "address": m["from"], "subject": m["subject"][:100],
                  "message_id": m["message_id"]} for m in letters],
        "threads": [{"id": t["id"], "app": t["app"], "with": t["with"], "link": t["link"], "count": len(t["messages"])}
                    for t in threads],
        "events": [{k: e[k] for k in ("id", "title", "start", "end", "all_day", "where", "clashes")} for e in events],
        "files": [{k: f[k] for k in ("id", "name", "folder", "kind", "movable")} for f in files],
        "folders": folders, "skipped": skipped, "problems": problems,
        "repos": [r["name"] for r in night["repos"]],
    }


@activity.defn
async def gather(night: dict) -> dict:
    """At dusk, while you're still awake for any permission prompt: letters, tomorrow's agenda, today's files."""
    return await asyncio.to_thread(_gather, night)


@activity.defn
async def check_sleep(a: dict) -> dict:
    return {"idle_min": round(sleep.idle_minutes(), 1), "on_ac": sleep.on_ac()}


@activity.defn
async def choose_model(a: dict) -> str:
    return llm.pick()


@activity.defn
async def forecast_dawn(a: dict) -> dict:
    out = datetime.fromisoformat(a["lights_out"]).astimezone()
    events = None
    if a.get("persona"):   # the demo learns Marisol's (fictional) nights, never yours
        events = [(datetime.fromisoformat(t), on) for t, on in json.loads((sources.FIXTURES / "power.json").read_text())]
    return {**await asyncio.to_thread(sleep.forecast, out.replace(tzinfo=None), events), "lights_out": out.isoformat()}


@activity.defn
async def triage_email(a: dict) -> dict:
    mail = sources.read_eml(Path(a["dir"]) / "mail" / f"{a['id']}.eml")
    answer, tokens = await _beating(ghosts.triage, mail, a["owner"], a["model"])
    return {**answer, "tokens": tokens, "model": a["model"]}


@activity.defn
async def read_thread(a: dict) -> dict:
    thread = {t["id"]: t for t in json.loads((Path(a["dir"]) / "threads.json").read_text())}[a["id"]]
    answer, tokens = await _beating(ghosts.read_thread, thread, a["owner"], a["model"])
    return {**answer, "tokens": tokens, "model": a["model"]}


@activity.defn
async def read_file_item(a: dict) -> dict:
    item = {f["id"]: f for f in json.loads((Path(a["dir"]) / "files.json").read_text())}[a["id"]]
    text = await asyncio.to_thread(sources.read_text, item["path"])
    answer, tokens = await _beating(ghosts.read_file_item, item, text, a["find"], a["owner"], a["model"], a.get("folders", []))
    return {**answer, "readable": text is not None, "tokens": tokens, "model": a["model"]}


@activity.defn
async def prep_meeting(a: dict) -> dict:
    event = {e["id"]: e for e in json.loads((Path(a["dir"]) / "events.json").read_text())}[a["id"]]
    answer, tokens = await _beating(ghosts.prep_meeting, event, a["letters"], a["files"], a["owner"], a["model"])
    for key, lines in (("letters", a["letters"]), ("files", a["files"])):
        known = {line.split(" | ")[0] for line in lines}
        answer[key] = [i for i in answer[key] if i in known][:5]
    return {**answer, "tokens": tokens, "model": a["model"]}


TOOLS = {"keeper": ghosts.KEEPER_TOOLS, "code": ghosts.CODE_TOOLS}
ALLOWED = {"keeper": {"forecast_dawn": []}, "code": ghosts.CODE_ARGS}
SCHEMAS = {"plan": ghosts.PLAN_SCHEMA}


def _turn(a):
    """One reply from the Keeper or the code ghost. Malformed tool calls are re-asked here and never kept."""
    tools, schema, messages = TOOLS.get(a.get("tools")), SCHEMAS.get(a.get("schema")), list(a["messages"])
    for _ in range(3):
        out = llm.chat(messages, a["model"], schema=schema, tools=tools)
        msg, tokens = out["message"], {"in": out.get("prompt_eval_count", 0), "out": out.get("eval_count", 0)}
        if schema:
            return {"message": {"role": "assistant", "content": msg["content"]}, "content": json.loads(msg["content"]),
                    "calls": [], "tokens": tokens}
        calls, problem = ghosts.check_calls(msg, ALLOWED[a["tools"]])
        if problem is None:
            kept = {"role": "assistant", "content": msg.get("content") or ""}
            if msg.get("tool_calls"):
                kept["tool_calls"] = [{"function": {"name": c["name"], "arguments": c["args"]}} for c in calls]
            return {"message": kept, "calls": calls, "tokens": tokens}
        messages += [{"role": "assistant", "content": msg.get("content") or "", "tool_calls": msg.get("tool_calls", [])},
                     {"role": "user", "content": problem}]
    raise RuntimeError("Gemma kept calling tools the wrong way")


@activity.defn
async def llm_turn(a: dict) -> dict:
    return {**await _beating(_turn, a), "model": a["model"]}


@activity.defn
async def open_worktree(a: dict) -> dict:
    repo = Path(a["repo"]["path"]).expanduser()

    def work():
        room = sandbox.make_worktree(repo, WORKTREES, a["slug"])
        passed, out = sandbox.run_sandboxed(room["path"], a["repo"]["test"])
        tree = sources.git(room["path"], "ls-files").splitlines()
        return {**room, "status": sources.repo_status(repo), "baseline": {"passed": passed, "tail": out[-1500:]},
                "tree": tree[:150] + ([f"…and {len(tree) - 150} more"] if len(tree) > 150 else [])}
    return await _beating(work)


@activity.defn
async def run_tool(a: dict) -> dict:
    text = await _beating(sandbox.run_tool, a["root"], a["call"], a["test"])
    return {"text": text[:3000], "passed": text.startswith("PASSED") if a["call"]["name"] == "run_tests" else None}


@activity.defn
async def commit_work(a: dict) -> dict:
    return await asyncio.to_thread(sandbox.commit, a["root"], a["message"])


@activity.defn
async def write_briefing(a: dict) -> str:
    path = Path(a["dir"]) / "briefing.json"
    path.write_text(json.dumps(a["briefing"], indent=1, ensure_ascii=False))
    return str(path)


@activity.defn
async def unload_model(a: dict) -> None:
    await asyncio.to_thread(llm.unload, a["model"])


ON_MAIN = [gather, check_sleep, choose_model, forecast_dawn, open_worktree, run_tool, commit_work, write_briefing, unload_model]
ON_CANDLE = [triage_email, read_thread, read_file_item, prep_meeting, llm_turn]
