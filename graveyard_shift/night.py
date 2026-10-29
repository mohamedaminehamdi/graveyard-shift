"""Run a night: the Temporal server, the worker, and the NightShift workflow.

The server is its own process with its own sqlite file, so killing the worker (or the whole app) never loses the
night: run the same command again and it picks up where it stopped. The worker has two queues: the main one, and the
"candle" with room for one Gemma call at a time.
"""
import asyncio
import io
import json
import os
import re
import socket
import subprocess
import tarfile
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from temporalio.client import Client, WorkflowHandle
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker

from . import activities, sleep, sources
from .workflow import CANDLE, MAIN, NightShift

HOME = Path.home() / ".graveyard-shift"
TEMPORAL = HOME / "bin" / "temporal"
TEMPORAL_URL = "https://temporal.download/cli/archive/latest?platform=darwin&arch=arm64"
PORT, UI_PORT = 7233, 8233
CONFIG = HOME / "config.json"


def server_up():
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def download_temporal():
    """The open-source Temporal CLI (one binary, ~150 MB), fetched once."""
    print("Fetching the Temporal dev server (once)…")
    with urllib.request.urlopen(TEMPORAL_URL, timeout=300) as r:
        archive = tarfile.open(fileobj=io.BytesIO(r.read()))
    TEMPORAL.parent.mkdir(parents=True, exist_ok=True)
    TEMPORAL.write_bytes(archive.extractfile("temporal").read())
    TEMPORAL.chmod(0o755)


def ensure_server():
    """Temporal's dev server on 127.0.0.1, its state in ~/.graveyard-shift/temporal.db. UI at :8233."""
    if server_up():
        return
    if not TEMPORAL.exists():
        download_temporal()
    log = open(HOME / "temporal.log", "ab")
    subprocess.Popen([str(TEMPORAL), "server", "start-dev", "--db-filename", str(HOME / "temporal.db"), "--ip", "127.0.0.1",
                      "--port", str(PORT), "--ui-port", str(UI_PORT), "--log-level", "warn"],
                     stdout=log, stderr=log, start_new_session=True)
    for _ in range(120):
        if server_up():
            return
        time.sleep(0.5)
    raise RuntimeError("The Temporal server didn't start; see ~/.graveyard-shift/temporal.log")


async def connect():
    ensure_server()   # the identity names the worker in the history: a pid, not this Mac's hostname
    return await Client.connect(f"127.0.0.1:{PORT}", identity=f"ghosts-{os.getpid()}")


def workers(client):
    return (Worker(client, task_queue=MAIN, workflows=[NightShift], activities=activities.ON_MAIN),
            Worker(client, task_queue=CANDLE, activities=activities.ON_CANDLE, max_concurrent_activities=1))


def _local(dt):
    return dt.astimezone().isoformat(timespec="seconds")


def _evening(now, hour=21):
    """Tonight from 9 pm (or now, if that's later)."""
    return _local(max(now, now.replace(hour=hour, minute=0, second=0, microsecond=0)) if now.hour >= 5 else now)


def persona_night(note=None, dawn_in=None, wait=False):
    """The demo: Marisol Vega's day (fictional), worked on by real ghosts on this Mac."""
    now = datetime.now()
    if not wait and not dawn_in:   # starting now, maybe at noon: TabPFN's dawn for a noon "lights out" would end it at once
        dawn_in = 90
    stamp = now.strftime("%m%d-%H%M")
    return {"id": f"persona-{stamp}", "stamp": stamp, "dir": str(HOME / "nights" / f"persona-{stamp}"),
            "owner": "Marisol Vega", "persona": True, "tonight": "Wednesday 28 October", "day": "2026-10-29",
            "note": note or (sources.FIXTURES / "note.txt").read_text(),
            "repos": [{"name": "inkwell", "path": str(HOME / "persona" / "inkwell"), "test": "python3 -m unittest -q"}],
            "wait": wait, "give_up": _local(now.replace(hour=5, minute=0) + timedelta(days=now.hour >= 5)),
            "not_before": _evening(now) if wait else None,
            "dawn": _local(now + timedelta(minutes=dawn_in)) if dawn_in else None, "model": None}


def real_night(note, wait=True):
    """Your night: your inbox (Gmail or Mail.app), your chats, your calendar feed, your files, your repos. Settings in
    config.json; the Gmail app password and the Slack token live in your Keychain."""
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    now = datetime.now()
    morning = now + timedelta(days=1) if now.hour >= 12 else now
    stamp = now.strftime("%m%d-%H%M")
    return {"id": f"night-{now:%Y%m%d}", "stamp": stamp, "dir": str(HOME / "nights" / f"night-{now:%Y%m%d}"),
            "owner": cfg.get("name", "you"), "persona": False, "tonight": now.strftime("%A %d %B"),
            "day": morning.date().isoformat(), "note": note, "mail": cfg.get("mail", False), "gmail": cfg.get("gmail", ""),
            "messages": cfg.get("messages", []), "ics": cfg.get("ics", []),
            "folders": cfg.get("folders"), "repos": cfg.get("repos", []), "wait": wait,
            "give_up": _local(now.replace(hour=5, minute=0) + timedelta(days=now.hour >= 5)),
            "not_before": _evening(now) if wait else None, "dawn": None,
            "model": cfg.get("model")}


async def start(client, night):
    """Start tonight's NightShift, or find the one already running (after a crash or reboot)."""
    try:
        return await client.start_workflow(NightShift.run, night, id=night["id"], task_queue=MAIN,
                                           id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
    except WorkflowAlreadyStartedError:
        return client.get_workflow_handle(night["id"])


async def running_night():
    """The night that's still going (after a crash or a reboot), so running the command again resumes it."""
    client = await connect()
    async for wf in client.list_workflows("WorkflowType='NightShift' AND ExecutionStatus='Running'"):
        args = HOME / "nights" / wf.id / "args.json"
        if args.exists():
            return json.loads(args.read_text())
    return None


async def run(night, watch_touch=True):
    """Work a whole night in this process; returns the briefing. Safe to re-run: it resumes."""
    folder = Path(night["dir"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "args.json").write_text(json.dumps(night))
    client = await connect()
    caffeinate = subprocess.Popen(["caffeinate", "-s", "-w", str(os.getpid())])  # awake only while plugged in
    main, candle = workers(client)
    async with main, candle:
        handle = await start(client, night)
        result = asyncio.ensure_future(handle.result())
        while not result.done():
            await asyncio.wait({result}, timeout=30)
            if watch_touch and not result.done() and sleep.idle_minutes() < 1:
                if (await handle.query(NightShift.progress))["phase"] == "work":
                    await handle.signal(NightShift.wake)   # you touched the Mac: dawn comes early
        briefing = result.result()
    caffeinate.terminate()
    await export(handle, Path(night["dir"]))
    return briefing


def machine():
    """Where the night ran, for the replay's header."""
    get = lambda *cmd: subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    model = re.search(r"Model Name: (.+)", get("system_profiler", "SPHardwareDataType"))
    chip, ram = get("sysctl", "-n", "machdep.cpu.brand_string"), int(get("sysctl", "-n", "hw.memsize") or 0) // 2**30
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=5) as r:
            ollama = json.load(r)["version"]
    except OSError:
        ollama = None
    return {"machine": f"{model.group(1) if model else 'Mac'}, {chip}, {ram} GB", "ollama": ollama}


async def export(handle: WorkflowHandle, folder: Path):
    """The night's raw Temporal history, and the replay built from it."""
    from . import replay
    history = (await handle.fetch_history()).to_json_dict()
    meta = machine()
    (folder / "history.json").write_text(json.dumps(history))
    (folder / "meta.json").write_text(json.dumps(meta))
    (folder / "night.json").write_text(json.dumps(replay.build(history, meta), ensure_ascii=False))


async def work_only():
    """Just the worker: picks up any night that's waiting for one (the comeback after a crash)."""
    client = await connect()
    main, candle = workers(client)
    async with main, candle:
        await asyncio.Event().wait()
