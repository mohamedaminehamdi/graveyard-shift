"""The promises the ghosts make: they read as data, they can't send, they stay in their room, and files move only when
you press Tidy (and come back with Undo)."""
import inspect
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from graveyard_shift import ghosts, llm, sandbox, sources

MAIL = {p.stem: sources.read_eml(p) for p in sorted((sources.FIXTURES / "mail").glob("*.eml"))}


def test_persona_sources_read_back():
    assert len(MAIL) == 28
    assert MAIL["m01"]["from"].startswith("Hans Kessler")
    events = sources.events_on(sources.read_ics((sources.FIXTURES / "calendar.ics").read_text()), date(2026, 10, 29))
    clashes = {e["title"]: e["clashes"] for e in events}
    assert clashes["Dentist (Dr. Ortega)"] and clashes["Lanternfish design review"] and not clashes["Lunch with Ana"]
    assert "EUR 18,400" in sources.read_text(sources.FIXTURES / "files/Downloads/Lanternfish_Contract_v3.pdf")


def test_weekly_events_land_on_the_right_day():
    ics = ("BEGIN:VEVENT\nUID:standup\nDTSTART;TZID=Europe/Berlin:20261005T091500\nDTEND;TZID=Europe/Berlin:20261005T093000\n"
           "RRULE:FREQ=WEEKLY;BYDAY=MO,TH\nSUMMARY:Standup\nEND:VEVENT\n")

    def seen_from(zone, day=date(2026, 10, 29)):   # a Thursday
        return [e["start"][11:16] for e in sources.events_on(sources.read_ics(ics, tz=ZoneInfo(zone)), day)]

    assert seen_from("Europe/Berlin") == ["09:15"]                 # the same wall-clock time across the DST change
    assert seen_from("UTC") == ["08:15"]                           # Berlin left summer time on Oct 25...
    assert seen_from("America/New_York") == ["04:15"]              # ...New York only leaves it on Nov 1
    assert seen_from("Europe/Berlin", date(2026, 10, 28)) == []    # a Wednesday


def test_the_possession_email_is_caught_without_the_model(monkeypatch):
    sent = []

    def fake_chat(messages, model=llm.NIGHT, schema=None, tools=None, timeout=900):
        sent.append({"messages": messages, "tools": tools})
        return {"message": {"content": json.dumps({"label": "fyi", "why": "billing notice", "summary": "x", "draft": ""})}}

    monkeypatch.setattr(llm, "chat", fake_chat)
    answer, _ = ghosts.triage(MAIL["m07"], "Marisol Vega")       # even if Gemma were fooled into "fyi"...
    assert answer["label"] == "suspicious" and answer["caught_by"] == ["rule"] and answer["draft"] == ""
    assert sent[0]["tools"] is None                             # ...the mail ghost never has tools to misuse
    assert "<data>" in sent[0]["messages"][1]["content"]
    assert not any(ghosts.POSSESSION.search(m["body"]) for k, m in MAIL.items() if k != "m07")


def test_no_ghost_can_send_and_only_tidy_moves():
    code = "\n".join(p.read_text() for p in Path(sources.__file__).parent.glob("*.py"))
    assert not re.search(r"\b(send|forward|reply)\s+(to|message)\b|smtplib|make new outgoing message|\bmove\b.*\bmailbox\b", code, re.I)
    assert "source of m" in sources.EXPORT_MAIL and "delete" not in sources.EXPORT_MAIL.lower()
    assert not re.search(r"chat\.(postMessage|update|delete)", code)                                  # Slack and Gmail only read
    assert not re.search(r"\.(store|append|copy|move|expunge|uid)\(", inspect.getsource(sources.gmail_letters))
    assert "data=" not in inspect.getsource(sources._slack_get)                                         # GET, never POST
    morning = inspect.getsource(sources.tidy) + inspect.getsource(sources.untidy)
    assert code.count("os.rename(") == morning.count("os.rename(") and "shutil.move" not in code and "unlink" not in morning
    with pytest.raises(ValueError):
        llm.chat([], model="gemma4:cloud")


def test_the_possessed_text_is_caught_without_the_model(monkeypatch):
    chats, skipped = sources.drop_codes(json.loads((sources.FIXTURES / "messages.json").read_text()))
    assert skipped == 1 and not any("482913" in m["text"] for t in chats for m in t["messages"])   # the bank's code never reaches a ghost
    sent = []

    def fake_chat(messages, model=llm.NIGHT, schema=None, tools=None, timeout=900):
        sent.append({"messages": messages, "tools": tools})
        return {"message": {"content": json.dumps({"label": "fyi", "why": "a security notice", "summary": "x", "draft": "ok"})}}

    monkeypatch.setattr(llm, "chat", fake_chat)
    possessed = next(t for t in chats if t["with"] == "+15550199")
    answer, _ = ghosts.read_thread(possessed, "Marisol Vega")
    assert answer["label"] == "suspicious" and answer["caught_by"] == ["rule"] and answer["draft"] == ""
    assert sent[0]["tools"] is None and "<data>" in sent[0]["messages"][1]["content"]
    assert [t["with"] for t in chats if ghosts.POSSESSION.search(" ".join(m["text"] for m in t["messages"]))] == ["+15550199"]


def test_tidy_moves_only_what_the_ghost_suggested_and_undo_puts_it_back(tmp_path):
    night, loose, docs = tmp_path / "night", tmp_path / "Downloads", tmp_path / "Documents"
    for folder in ("Clients/Lanternfish", "Recipes"):
        (docs / folder).mkdir(parents=True)
    (docs / "Clients/Lanternfish/contract.pdf").write_text("an older contract")     # a name that's taken
    files, plan = [], []
    for n, (name, to) in enumerate([("contract.pdf", "Clients/Lanternfish"), ("recipe.txt", "Recipes"),
                                    ("id_rsa.txt", "Recipes"), ("notes.md", "Recipes"), ("receipt.csv", "../../outside"),
                                    ("talk.md", "Recipes")], 1):
        path = (docs if name == "talk.md" else loose) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)
        files.append({"id": f"f{n:02d}", "path": str(path), "movable": name != "talk.md",
                      "size": path.stat().st_size, "mtime": int(path.stat().st_mtime)})
        plan.append({"id": f"f{n:02d}", "move_to": to})
    (loose / "notes.md").write_text("changed after the ghost read it")
    night.mkdir()
    (night / "files.json").write_text(json.dumps(files))
    (night / "folders.json").write_text(json.dumps({"base": str(docs), "folders": sources.destinations(docs)}))
    (night / "briefing.json").write_text(json.dumps({"files": plan}))

    moved = sources.tidy(night)
    assert [Path(m["to"]).relative_to(docs).as_posix() for m in moved] == ["Clients/Lanternfish/contract 2.pdf", "Recipes/recipe.txt"]
    assert (docs / "Clients/Lanternfish/contract.pdf").read_text() == "an older contract"             # never overwritten
    assert sorted(os.listdir(loose)) == ["id_rsa.txt", "notes.md", "receipt.csv"] and (docs / "talk.md").exists()
    assert sources.tidy(night) == moved                                                              # pressing it twice moves nothing more
    assert sources.untidy(night) == [] and sorted(os.listdir(loose)) == sorted(n for n, _ in [
        ("contract.pdf", 0), ("recipe.txt", 0), ("id_rsa.txt", 0), ("notes.md", 0), ("receipt.csv", 0)])
    assert sorted(os.listdir(docs / "Clients/Lanternfish")) == ["contract.pdf"]


@pytest.fixture(scope="module")
def room(tmp_path_factory):
    base = tmp_path_factory.mktemp("night")
    repo = sources.persona_repo(base / "inkwell")
    return sandbox.make_worktree(repo, base / "worktrees", "test")["path"]


def test_path_guard(room):
    for bad in ["../outside.txt", "/etc/passwd", "~/.ssh/id_rsa", ".git/config", "posts/../../x"]:
        with pytest.raises(sandbox.Refused):
            sandbox.inside(room, bad)
    assert sandbox.inside(room, "inkwell/text.py").name == "text.py"
    assert sandbox.run_tool(room, {"name": "write_file", "args": {"path": "../escape.txt", "content": "x"}}, "").startswith("Refused")


@pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is macOS")
def test_tests_run_in_a_sandbox(room, tmp_path):
    outside = tmp_path / "ghost-was-here.txt"
    home = Path.home()
    probe = (f"python3 -c \"import urllib.request; urllib.request.urlopen('https://example.com', timeout=5)\" ; echo net=$?; "
             f"python3 -c \"open('{outside}', 'w')\" ; echo write=$?; python3 -c \"open('inside.txt', 'w')\" ; echo here=$?; "
             f"open https://example.com ; echo url=$?; ls {home} ; echo home=$?; "
             f"osascript -e 'tell application \"Finder\" to get name of startup disk' ; echo events=$?")
    passed, out = sandbox.run_sandboxed(room, probe)
    for blocked in ("net", "write", "url", "home", "events"):   # no network, no writes out, no opening URLs, no home, no Apple Events
        assert f"{blocked}=0" not in out, out
    assert "here=0" in out and not outside.exists()
    assert sandbox.run_sandboxed(room, "python3 -m unittest -q")[0]


def test_malformed_tool_calls_never_enter_the_history():
    bad = {"tool_calls": [{"function": {"name": "rm_rf", "arguments": {}}}]}
    assert ghosts.check_calls(bad, ghosts.CODE_ARGS) == (None, ghosts.check_calls(bad, ghosts.CODE_ARGS)[1])
    missing = {"tool_calls": [{"function": {"name": "write_file", "arguments": {"path": "a.py"}}}]}
    assert ghosts.check_calls(missing, ghosts.CODE_ARGS)[0] is None
    ok = {"tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "a.py", "extra": 1}}}]}
    assert ghosts.check_calls(ok, ghosts.CODE_ARGS)[0] == [{"name": "read_file", "args": {"path": "a.py"}}]


def test_the_local_page_answers_only_itself():
    import threading
    import urllib.error
    import urllib.request
    from functools import partial
    from http.server import ThreadingHTTPServer

    from graveyard_shift import server
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(server.WEB)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_port

    def call(path, post=False, **headers):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=b"{}" if post else None, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.headers.get("Content-Security-Policy", "")
        except urllib.error.HTTPError as e:
            return e.code, ""

    try:
        status, csp = call("/")
        assert status == 200 and "default-src 'self'" in csp
        assert call("/", Host="evil.example")[0] == 403                     # DNS rebinding
        assert call("/api/awake", post=True)[0] == 403                       # no token
        assert call("/api/awake", post=True, **{"X-Token": server.Handler.token, "Origin": "http://evil.example"})[0] == 403
        assert call("/api/exorcise", post=True, **{"X-Token": "guess"})[0] == 403
    finally:
        httpd.shutdown()
