"""The promises the ghosts make: they read as data, they can't send, they stay in their room."""
import json
import re
import sys
from datetime import date
from pathlib import Path

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
    events = sources.read_ics(ics)
    assert [e["start"][11:16] for e in sources.events_on(events, date(2026, 10, 29))] == ["09:15"]   # a Thursday
    assert sources.events_on(events, date(2026, 10, 28)) == []                                        # a Wednesday


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


def test_no_ghost_can_send_or_move():
    code = "\n".join(p.read_text() for p in Path(sources.__file__).parent.glob("*.py"))
    assert not re.search(r"\b(send|forward|reply)\s+(to|message)\b|smtplib|make new outgoing message|\bmove\b.*\bmailbox\b", code, re.I)
    assert "source of m" in sources.EXPORT_MAIL and "delete" not in sources.EXPORT_MAIL.lower()
    with pytest.raises(ValueError):
        llm.chat([], model="gemma4:cloud")


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
    probe = (f"python3 -c \"import urllib.request; urllib.request.urlopen('https://example.com', timeout=5)\" ; echo net=$?; "
             f"python3 -c \"open('{outside}', 'w')\" ; echo write=$?; python3 -c \"open('inside.txt', 'w')\" ; echo here=$?")
    passed, out = sandbox.run_sandboxed(room, probe)
    assert "net=1" in out and "write=1" in out and "here=0" in out and not outside.exists()
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
