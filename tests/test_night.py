"""The night is durable: dawn and "I'm awake" end it cleanly, and a dead worker never costs finished work.

These run the real NightShift workflow on a real Temporal dev server, with every activity faked.
"""
import asyncio
import base64
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from graveyard_shift import replay
from graveyard_shift.workflow import CANDLE, MAIN, NightShift

RUNS = {}            # how many times each email was read
AWAKE_THEN_ASLEEP = iter([])
PACE = {"s": 0.0}    # how long each email takes
OURS = Path.home() / ".graveyard-shift" / "bin" / "temporal"


def soon(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def night(**changes):
    return {"id": f"test-{uuid.uuid4().hex[:8]}", "stamp": "test", "dir": "/nowhere", "owner": "Marisol",
            "tonight": "Wednesday 28 October", "note": "add tests for slugify in inkwell",
            "repos": [{"name": "inkwell", "path": "/nowhere", "test": "true"}], "wait": False,
            "give_up": soon(3600), "dawn": soon(600), "model": "fake", **changes}


@activity.defn(name="gather")
async def gather(n):
    return {"mail": [{"id": f"m{i}", "from": "Hans", "address": "hans@x.example", "subject": "hi", "message_id": ""} for i in range(6)],
            "threads": [{"id": "t01", "app": "whatsapp", "with": "Ana", "link": "", "count": 2}],
            "events": [{"id": "kickoff", "title": "Kickoff", "start": "", "end": "", "all_day": False, "where": "", "clashes": []}],
            "files": [{"id": "f01", "name": "contract.pdf", "folder": "Downloads", "kind": "pdf", "movable": True}],
            "folders": ["Clients"], "skipped": 1, "problems": [], "repos": ["inkwell"]}


@activity.defn(name="triage_email")
async def triage_email(a):
    await asyncio.sleep(PACE["s"])
    RUNS[a["id"]] = RUNS.get(a["id"], 0) + 1
    return {"label": "fyi", "why": "a note", "summary": "a note", "draft": "", "caught_by": []}


@activity.defn(name="llm_turn")
async def llm_turn(a):
    if a.get("schema") == "plan":
        plan = {"code": [{"repo": "inkwell", "goal": "add tests for slugify"}], "find": [], "prep_first": [], "message": "ok"}
        return {"message": {"role": "assistant", "content": json.dumps(plan)}, "content": plan, "calls": []}
    name = "forecast_dawn" if a["tools"] == "keeper" else "finish"
    call = {"name": name, "args": {} if name == "forecast_dawn" else {"summary": "Added tests; they pass."}}
    return {"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": call["args"]}}]},
            "calls": [call]}


FAKES = {
    "forecast_dawn": lambda a: {"nights": 9, "wake": soon(7200), "dawn": soon(3600), "curve": [], "lights_out": a["lights_out"]},
    "read_file_item": lambda a: {"summary": "a contract", "kind": "contract", "check": [], "answers": "",
                                 "move_to": a["folders"][0]},
    "read_thread": lambda a: {"label": "reply", "why": "Ana asks about lunch", "summary": "x", "draft": "Yes!", "caught_by": []},
    "prep_meeting": lambda a: {"prep": ["bring the contract"], "letters": [], "files": ["f01"]},
    "open_worktree": lambda a: {"path": "/nowhere", "branch": "ghost/x", "status": {"stale": []}, "baseline": {"passed": False, "tail": ""}},
    "run_tool": lambda a: {"text": "PASSED", "passed": True},
    "commit_work": lambda a: {"sha": "abc1234", "stat": "1 file changed", "diff": ""},
    "write_briefing": lambda a: "/nowhere/briefing.json",
    "unload_model": lambda a: None,
    "check_sleep": lambda a: {"idle_min": 30 if next(AWAKE_THEN_ASLEEP) else 2, "on_ac": True},
    "choose_model": lambda a: "fake",
}


def fake(name, fn):
    @activity.defn(name=name)
    async def run(a):
        return fn(a)
    return run


THINKING = ("read_file_item", "prep_meeting", "read_thread")
MAIN_ACTS = [gather] + [fake(n, f) for n, f in FAKES.items() if n not in THINKING]
CANDLE_ACTS = [triage_email, llm_turn] + [fake(n, FAKES[n]) for n in THINKING]


def workers(client):
    return (Worker(client, task_queue=MAIN, workflows=[NightShift], activities=MAIN_ACTS),
            Worker(client, task_queue=CANDLE, activities=CANDLE_ACTS, max_concurrent_activities=1))


def with_server(test):
    async def go():
        kw = {"dev_server_existing_path": str(OURS)} if OURS.exists() else {}
        async with await WorkflowEnvironment.start_local(**kw) as env:
            return await test(env.client)
    RUNS.clear()
    return asyncio.run(go())


def test_a_whole_night():
    async def go(client):
        main, candle = workers(client)
        async with main, candle:
            briefing = await client.execute_workflow(NightShift.run, night(), id=f"t-{uuid.uuid4()}", task_queue=MAIN)
        assert briefing["night"]["ended"] == "done"
        assert [m["label"] for m in briefing["mail"]] == ["fyi"] * 6
        assert briefing["code"][0]["state"] == "done" and briefing["code"][0]["passed"]
        assert briefing["today"][0]["files"] == ["f01"]
        assert briefing["messages"][0]["label"] == "reply" and briefing["messages"][0]["draft"] == "Yes!"
        assert briefing["files"][0]["move_to"] == "Clients" and briefing["skipped"] == 1
    PACE["s"] = 0.0
    with_server(go)


def test_dawn_cuts_the_night_short_but_the_briefing_is_written():
    async def go(client):
        main, candle = workers(client)
        async with main, candle:
            briefing = await client.execute_workflow(NightShift.run, night(dawn=soon(4)), id=f"t-{uuid.uuid4()}", task_queue=MAIN)
        assert briefing["night"]["ended"] == "dawn"
        assert "unread" in [m["label"] for m in briefing["mail"]]
    PACE["s"] = 1.5
    with_server(go)


def test_im_awake_ends_it_early():
    async def go(client):
        main, candle = workers(client)
        async with main, candle:
            handle = await client.start_workflow(NightShift.run, night(), id=f"t-{uuid.uuid4()}", task_queue=MAIN)
            while sum(RUNS.values()) < 2:
                await asyncio.sleep(0.2)
            await handle.signal(NightShift.wake)
            briefing = await handle.result()
        assert briefing["night"]["ended"] == "awake" and len(RUNS) < 6
    PACE["s"] = 1.0
    with_server(go)


def test_a_dead_worker_costs_no_finished_work():
    async def go(client):
        main, candle = workers(client)
        async with main, candle:   # the first worker reads a few letters, then dies mid-letter
            handle = await client.start_workflow(NightShift.run, night(), id=f"t-{uuid.uuid4()}", task_queue=MAIN)
            while sum(RUNS.values()) < 3:
                await asyncio.sleep(0.1)
        before = dict(RUNS)
        main, candle = workers(client)
        async with main, candle:   # a new worker picks the night up from Temporal's history
            briefing = await handle.result()
        assert briefing["night"]["ended"] == "done" and sorted(RUNS) == [f"m{i}" for i in range(6)]
        assert all(RUNS[k] == n for k, n in before.items())   # nothing finished was read twice
        history = (await handle.fetch_history()).to_json_dict()
        steps = replay.build(history)["steps"]
        assert len([s for s in steps if s["act"] == "triage_email" and s["outcome"] == "done"]) == 6
    PACE["s"] = 0.5
    with_server(go)


def test_the_ghosts_wait_for_evening_and_for_sleep():
    global AWAKE_THEN_ASLEEP
    AWAKE_THEN_ASLEEP = iter([False, True])   # the first peek finds you still up

    async def go(client):
        main, candle = workers(client)
        async with main, candle:
            n = night(wait=True, not_before=soon(2), peek_every=1, dawn=None)
            briefing = await client.execute_workflow(NightShift.run, n, id=f"t-{uuid.uuid4()}", task_queue=MAIN)
        assert briefing["night"]["peeks"] == 1 and briefing["night"]["ended"] == "done"
        started = datetime.fromisoformat(briefing["night"]["lights_out"]) + timedelta(minutes=30)
        assert started >= datetime.fromisoformat(n["not_before"])   # nobody rose before evening
    PACE["s"] = 0.0
    with_server(go)


def test_the_published_replay_is_the_published_history():
    folder = Path(__file__).parent.parent / "graveyard_shift" / "web" / "replay"
    if not (folder / "history.json").exists():
        return
    history = json.loads((folder / "history.json").read_text())
    meta = json.loads((folder / "meta.json").read_text())
    assert replay.build(history, meta) == json.loads((folder / "night.json").read_text())
    addresses = set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", (folder / "night.json").read_text()))
    assert all(a.endswith(".example") or a.endswith(".invalid") for a in addresses), addresses   # only the persona
    payloads = " ".join(base64.b64decode(d).decode("utf-8", "replace")
                        for d in re.findall(r'"data": "([A-Za-z0-9+/=]+)"', (folder / "history.json").read_text()))
    assert "/Users/" not in payloads                                          # no home folder, so no user name
    assert all(n.startswith("+1555") for n in re.findall(r"\+\d{9,}", payloads))   # only the persona's 555 numbers
