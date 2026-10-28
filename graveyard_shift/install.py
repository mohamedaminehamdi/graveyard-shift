"""Set up Graveyard Shift on this Mac: the models, the Temporal binary, an app in ~/Applications and, if you want,
the ghosts every night at 9 pm. install.sh runs `graveyard-shift --setup`. No admin password; nothing is sent anywhere.
"""
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from . import llm, night, sleep

APP = Path.home() / "Applications" / "Graveyard Shift.app"
BUNDLE_ID = "io.github.mohamedaminehamdi.graveyardshift"
AGENT = Path.home() / "Library" / "LaunchAgents" / f"{BUNDLE_ID}.night.plist"
ICON = Path(__file__).parent / "ghost.icns"
FILES_WHY = "At bedtime the Files ghost reads what you saved today, to prepare your morning briefing. It never moves anything."
MAIL_WHY = "At bedtime the Mail ghost copies today's letters out of Mail to sort them on this Mac. It can't send, move or delete."

# Opening the app shows the graveyard; the nightly run starts a night in the background and the app quits.
APPLET = """set mode to system attribute "GS_MODE"
if mode is "night" then
\tdo shell script quoted form of "{exe}" & " night > /dev/null 2>&1 &"
else
\tdo shell script quoted form of "{exe}" & " > /dev/null 2>&1 &"
end if
"""


def ollama_up(seconds=60):
    for _ in range(seconds):
        try:
            urllib.request.urlopen(f"{llm.OLLAMA}/api/version", timeout=2).read()
            return True
        except OSError:
            time.sleep(1)
    return False


def pull(model, why):
    print(f"Downloading {model} ({why}, only once)…")
    req = urllib.request.Request(f"{llm.OLLAMA}/api/pull", data=json.dumps({"model": model}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=None) as r:
        for line in r:
            msg = json.loads(line) if line.strip() else {}
            if "error" in msg:   # Ollama reports failures inside a 200 stream
                raise RuntimeError(msg["error"])
            if msg.get("total"):
                print(f"\r  {msg.get('status', '')[:30]:<30} {100 * msg.get('completed', 0) // msg['total']:3d}%", end="", flush=True)
    print(f"\r  {model} is ready." + " " * 40)


def warm_tabpfn():
    """The open TabPFN v2 weights (Apache 2.0 + attribution, no account), fetched by fitting a tiny made-up table."""
    import numpy as np
    print("Downloading TabPFN, which learns when you wake up…")
    X, y = np.arange(20, dtype=float).reshape(10, 2), np.array([0, 1] * 5)
    sleep.tabpfn().fit(X, y).predict(X)
    print("  TabPFN is ready.")


def default_config():
    if night.CONFIG.exists():
        return
    name = subprocess.run(["id", "-F"], capture_output=True, text=True).stdout.strip() or "you"
    night.CONFIG.parent.mkdir(parents=True, exist_ok=True)
    night.CONFIG.write_text(json.dumps({
        "name": name, "mail": False, "ics": [], "folders": ["~/Downloads", "~/Desktop", "~/Documents"],
        "repos": [], "_help": "repos: [{'name': 'blog', 'path': '~/code/blog', 'test': 'python3 -m pytest -q'}]; "
                              "ics: Google Calendar > Settings > your calendar > Secret address in iCal format; "
                              "mail: true reads today's inbox from Mail.app (add your account in Internet Accounts)"}, indent=1))
    print(f"  Settings: {night.CONFIG} (your name, repos, calendar feed).")


def _ours(app):
    try:
        return plistlib.loads((app / "Contents" / "Info.plist").read_bytes()).get("CFBundleIdentifier") == BUNDLE_ID
    except OSError:
        return False


def make_app(exe, app=APP):
    """A double-clickable app, built on this Mac (not downloaded), so Gatekeeper has nothing to block."""
    if app.exists():
        if not _ours(app):
            raise SystemExit(f"{app} exists and isn't ours; leaving it alone.")
        shutil.rmtree(app)
    app.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".applescript", delete=False) as f:
        f.write(APPLET.format(exe=str(exe).replace("\\", "\\\\").replace('"', '\\"')))
    subprocess.run(["osacompile", "-o", str(app), f.name], check=True, capture_output=True)
    os.unlink(f.name)
    res = app / "Contents" / "Resources"
    shutil.copy(ICON, res / "applet.icns")
    (res / "Assets.car").unlink(missing_ok=True)   # it would override our icon
    info_path = app / "Contents" / "Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    info.pop("CFBundleIconName", None)
    info.update(CFBundleIdentifier=BUNDLE_ID, CFBundleName="Graveyard Shift", CFBundleDisplayName="Graveyard Shift",
                NSAppleEventsUsageDescription=MAIL_WHY, NSDesktopFolderUsageDescription=FILES_WHY,
                NSDocumentsFolderUsageDescription=FILES_WHY, NSDownloadsFolderUsageDescription=FILES_WHY)
    info_path.write_bytes(plistlib.dumps(info))
    # Editing the bundle breaks osacompile's ad-hoc signature; macOS ties permissions to a valid one.
    subprocess.run(["codesign", "--force", "--deep", "-s", "-", str(app)], check=True, capture_output=True)
    subprocess.run(["touch", str(app)])
    return app


def _launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True)


def nightly(app=APP):
    """At 9 pm the app starts a night: the ghosts wait in their graves until you're asleep."""
    AGENT.parent.mkdir(parents=True, exist_ok=True)
    AGENT.write_bytes(plistlib.dumps({
        "Label": f"{BUNDLE_ID}.night",
        "ProgramArguments": ["/usr/bin/open", "-g", "--env", "GS_MODE=night", "-a", str(app)],
        "StartCalendarInterval": {"Hour": 21, "Minute": 0},
    }))
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", domain, str(AGENT))
    if _launchctl("bootstrap", domain, str(AGENT)).returncode:
        print("  Couldn't schedule the nightly ghosts; say Goodnight in the app instead.")
    else:
        print("  The ghosts will rise every night after you fall asleep (leave the Mac open and plugged in).")


def setup(models=True, every_night=False):
    exe = Path(sys.argv[0]).absolute() if Path(sys.argv[0]).name == "graveyard-shift" else shutil.which("graveyard-shift")
    if not exe:
        raise SystemExit("Can't find the graveyard-shift command to point the app at.")
    if models:
        if ollama_up():
            pull(llm.LIGHT, "Gemma 4, 6.6 GB")
            if int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout or 0) >= 32 * 2**30:
                pull(llm.NIGHT, "the 26B Gemma 4 for roomy Macs, 15.6 GB")
        else:
            print("Ollama isn't running, so no Gemma 4 yet. Open Ollama and run: graveyard-shift --setup")
        warm_tabpfn()
        if not night.TEMPORAL.exists():
            night.download_temporal()
    default_config()
    app = make_app(exe)
    print(f"Made {app.name} in your Applications folder.")
    if every_night:
        nightly(app)


def uninstall():
    if AGENT.exists():
        _launchctl("bootout", f"gui/{os.getuid()}", str(AGENT))
        AGENT.unlink()
    if _ours(APP):
        shutil.rmtree(APP)
    print("Removed the app and the nightly ghosts. Your nights and settings in ~/.graveyard-shift are untouched.")
    print("To remove the program too:  uv tool uninstall graveyard-shift")
