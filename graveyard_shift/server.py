"""The graveyard on your Mac, served only to this machine (127.0.0.1).

Evening: leave a note and say goodnight (the night runs as its own process, so closing this page changes nothing).
Night: the page replays the live Temporal history as it grows. Morning: the briefing, with Keep / Exorcise.
"""
import asyncio
import json
import secrets
import subprocess
import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import night as nights
from . import replay, sandbox
from .workflow import NightShift

WEB = Path(__file__).parent / "web"
PORT = 8742
IDLE_SECONDS = 1800
CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'; font-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'"
LOOP = asyncio.new_event_loop()   # Temporal's client is async; the web server isn't
threading.Thread(target=LOOP.run_forever, daemon=True).start()


def on_loop(coro, timeout=20):
    return asyncio.run_coroutine_threadsafe(coro, LOOP).result(timeout)


async def _running():
    client = await nights.connect()
    async for wf in client.list_workflows("WorkflowType='NightShift' AND ExecutionStatus='Running'"):
        handle = client.get_workflow_handle(wf.id)
        return replay.build((await handle.fetch_history()).to_json_dict())
    return None


async def _hand_note(note):
    """If tonight's ghosts are already waiting (the 9 pm run), give them the note instead of starting another night."""
    client = await nights.connect()
    async for wf in client.list_workflows("WorkflowType='NightShift' AND ExecutionStatus='Running'"):
        await client.get_workflow_handle(wf.id).signal(NightShift.leave_note, note)
        return True
    return False


def last_night():
    done = sorted((nights.HOME / "nights").glob("*/night.json"), key=lambda p: p.stat().st_mtime)
    return json.loads(done[-1].read_text()) if done else None


class Handler(SimpleHTTPRequestHandler):
    token = secrets.token_urlsafe(24)   # per launch: only this page can change anything
    lock = threading.Lock()

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _local(self):
        """Host must be this machine (blocks DNS rebinding); Origin, when sent, must be this page."""
        port = self.server.server_port
        ours = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")
        return self.headers.get("Host") in ours and (origin is None or origin in {f"http://{h}" for h in ours})

    def do_GET(self):
        if not self._local():
            return self._json({"error": "forbidden"}, 403)
        if self.path.split("?")[0] == "/api/state":
            try:
                live = nights.server_up() and on_loop(_running())
            except Exception:
                live = None
            return self._json({"token": self.token, "running": bool(live), "night": live or last_night()})
        return super().do_GET()

    def do_POST(self):
        if not self._local() or not secrets.compare_digest(self.headers.get("X-Token", ""), self.token):
            return self._json({"error": "forbidden"}, 403)
        length = min(int(self.headers.get("Content-Length") or 0), 100_000)
        body = json.loads(self.rfile.read(length) or b"{}")
        if not self.lock.acquire(blocking=False):
            return self._json({"error": "busy"}, 409)
        try:
            if self.path == "/api/goodnight":
                return self._goodnight(body)
            if self.path == "/api/awake":
                subprocess.run([sys.executable, "-m", "graveyard_shift.cli", "awake"], capture_output=True, timeout=30)
                return self._json({"ok": True})
            if self.path in ("/api/keep", "/api/exorcise"):
                return self._settle(self.path.rsplit("/", 1)[1], body)
            return self._json({"error": "not found"}, 404)
        finally:
            self.lock.release()

    def _goodnight(self, body):
        note = str(body.get("note", ""))[:2000]
        if not (nights.server_up() and on_loop(_hand_note(note))):
            log = open(nights.HOME / "night.log", "ab")
            subprocess.Popen([sys.executable, "-m", "graveyard_shift.cli", "night", "--note", note],
                             stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        threading.Timer(8, subprocess.run, [["pmset", "displaysleepnow"]]).start()   # lights out; the Mac stays awake
        return self._json({"ok": True})

    def _settle(self, what, body):
        """Keep or Exorcise one branch the ghosts made last night, and nothing else."""
        night = last_night() or {}
        code = next((c for c in ((night.get("briefing") or {}).get("code") or [])
                     if c.get("branch") == body.get("branch") and c.get("repo") == body.get("repo")), None)
        if (night.get("briefing") or {}).get("night", {}).get("persona"):
            repo = {"path": str(nights.HOME / "persona" / "inkwell")}
        else:
            repos = json.loads(nights.CONFIG.read_text()).get("repos", []) if nights.CONFIG.exists() else []
            repo = next((r for r in repos if r["name"] == body.get("repo")), None)
        if not code or not repo or not code["branch"].startswith("ghost/"):
            return self._json({"error": "That isn't a branch the ghosts made."}, 400)
        repo_path = Path(repo["path"]).expanduser()
        if what == "keep":
            sandbox.keep(repo_path, code["path"])
        else:
            sandbox.exorcise(repo_path, code["path"], code["branch"])
        return self._json({"ok": True})


def serve(port=PORT, open_browser=True, idle=IDLE_SECONDS):
    url = f"http://127.0.0.1:{port}/?local=1"
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(WEB)))
    except OSError:   # already open: show that one
        if open_browser:
            webbrowser.open(url)
        return
    print(f"The graveyard is at {url}  (Ctrl+C to close)")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    stop = threading.Event()
    httpd.timeout = idle
    httpd.handle_timeout = stop.set   # nobody looked for half an hour
    try:
        while not stop.is_set():
            httpd.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
