"""NightShift: one durable night.

The workflow only decides; every side effect is an activity. So a crash, a reboot or a closed lid only pauses the
night, and when the worker comes back it carries on from Temporal's history: finished letters are never read twice.

  dusk    gather the day's letters, chats, files and agenda (while you're awake for any permission prompt)
  graves  durable timers: peek every 5 minutes until you've been away 20 minutes (and the Mac is on power)
  keeper  the Keeper reads your note, asks TabPFN when you'll wake, and plans the night
  work    five ghosts at once, taking turns on the GPU (the candle), until done, dawn, or "I'm awake"
  dawn    the briefing
"""
import asyncio
import re
from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, is_cancelled_exception

with workflow.unsafe.imports_passed_through():
    from . import ghosts
    from .llm import LIGHT

MAIN, CANDLE = "graveyard", "candle"
QUICK = {"start_to_close_timeout": timedelta(minutes=10), "retry_policy": RetryPolicy(maximum_attempts=3)}
THINK = {"task_queue": CANDLE, "start_to_close_timeout": timedelta(minutes=20), "heartbeat_timeout": timedelta(seconds=60),
         "retry_policy": RetryPolicy(initial_interval=timedelta(seconds=5), maximum_attempts=3)}
TOOL = {"start_to_close_timeout": timedelta(minutes=8), "heartbeat_timeout": timedelta(seconds=60),
        "retry_policy": RetryPolicy(maximum_attempts=2)}


@workflow.defn
class NightShift:
    def __init__(self):
        self.phase, self.ended, self.awake, self.note = "dusk", None, False, None
        self.model, self.peeks, self.lights_out = None, 0, None
        self.inventory, self.forecast, self.plan = {}, {}, {}
        self.mail, self.threads, self.files, self.meetings, self.code = {}, {}, {}, {}, {}

    @workflow.signal
    def wake(self):
        """You're up: the ghosts finish the step in hand and write the briefing."""
        self.awake = True

    @workflow.signal
    def leave_note(self, note: str):
        """A note left after the night began (the 9 pm run is already waiting): the Keeper reads this one."""
        self.note = note

    @workflow.query
    def progress(self) -> dict:
        return {"phase": self.phase, "model": self.model, "peeks": self.peeks, "dawn": self.forecast.get("dawn"),
                "read": {"mail": len(self.mail), "threads": len(self.threads), "files": len(self.files),
                         "events": len(self.meetings)},
                "of": {k: len(self.inventory.get(k, [])) for k in ("mail", "threads", "files", "events")},
                "code": {k: v.get("state") for k, v in self.code.items()}}

    @workflow.run
    async def run(self, night: dict) -> dict:
        self.inventory = await workflow.execute_activity("gather", night, summary="Dusk: gather the day", **QUICK)
        if night.get("wait", True):
            self.phase = "graves"
            if not await self.wait_for_sleep(night):
                return await self.dawn(night, "no sleep tonight")
        else:
            self.lights_out = workflow.now().isoformat()
        self.phase = "keeper"
        self.model = night.get("model") or await workflow.execute_activity("choose_model", {}, **QUICK)
        await self.keeper(night)

        self.phase = "work"
        dawn = datetime.fromisoformat(night.get("dawn") or self.forecast["dawn"])
        work = asyncio.create_task(self.shift(night))
        try:
            await workflow.wait_condition(lambda: work.done() or self.awake,
                                          timeout=max(1.0, (dawn - workflow.now()).total_seconds()))
        except asyncio.TimeoutError:
            pass
        ended = "done" if work.done() else "awake" if self.awake else "dawn"
        if not work.done():
            work.cancel()
        try:
            await work
        except (asyncio.CancelledError, ActivityError):
            pass
        return await self.dawn(night, ended)

    async def wait_for_sleep(self, night):
        give_up = datetime.fromisoformat(night["give_up"])
        if night.get("not_before"):   # no rising at teatime: the graves stay shut until evening
            await workflow.sleep(max(timedelta(0), datetime.fromisoformat(night["not_before"]) - workflow.now()))
        while workflow.now() < give_up:
            seen = await workflow.execute_activity("check_sleep", {"ghost": "keeper", "target": "moon"}, **QUICK)
            if seen["idle_min"] >= night.get("idle_min", 20) and seen["on_ac"]:
                self.lights_out = (workflow.now() - timedelta(minutes=seen["idle_min"])).isoformat()
                return True
            self.peeks += 1
            await workflow.sleep(timedelta(seconds=night.get("peek_every", 300)))
        return False

    async def think(self, activity, arg, summary):
        """A Gemma call on the candle queue. If the big model fails three times, the small one takes over."""
        try:
            return await workflow.execute_activity(activity, {**arg, "model": self.model}, summary=summary, **THINK)
        except ActivityError as e:
            if is_cancelled_exception(e) or self.model == LIGHT:
                raise
            self.model = LIGHT
            return await workflow.execute_activity(activity, {**arg, "model": self.model}, summary=summary, **THINK)

    async def keeper(self, night):
        repos = [r["name"] for r in night["repos"]]
        note = self.note if self.note is not None else night["note"]
        messages = ghosts.keeper_messages(note, night["owner"], repos, night["tonight"])
        first = await self.think("llm_turn", {"messages": messages, "tools": "keeper", "ghost": "keeper", "target": "keeper"},
                                 "Keeper reads the note")
        self.forecast = await workflow.execute_activity(
            "forecast_dawn", {"lights_out": self.lights_out, "asked": bool(first["calls"]), "persona": bool(night.get("persona")),
                              "ghost": "keeper", "target": "moon"},
            summary="TabPFN: when will they wake?", **QUICK)
        said = (f"Lights went out around {self.forecast['lights_out'][11:16]}. TabPFN ({self.forecast['nights']} nights learned) "
                f"expects them back at the Mac around {self.forecast['wake'][11:16]}; "
                f"the briefing must be ready by {(night.get('dawn') or self.forecast['dawn'])[11:16]}.")
        if first["calls"]:
            messages += [first["message"], {"role": "tool", "tool_name": "forecast_dawn", "content": said}]
        else:
            messages += [first["message"], {"role": "user", "content": f"(The forecast, fetched for you: {said})"}]
        messages.append({"role": "user", "content": ghosts.PLAN_ASK.format(owner=night["owner"], repos=", ".join(repos))})
        plan = await self.think("llm_turn", {"messages": messages, "schema": "plan", "ghost": "keeper", "target": "keeper"},
                                "Keeper plans the night")
        self.plan = ghosts.clean_plan(plan["content"], repos)

    async def shift(self, night):
        code = [asyncio.create_task(self.code_ghost(night, task)) for task in self.plan["code"]]
        try:
            await asyncio.gather(self.mail_ghost(night), self.messages_ghost(night), self.files_ghost(night))
            await self.calendar_ghost(night)
            await asyncio.gather(*code)
        finally:
            for task in code:   # dawn: the code ghost stops too
                task.cancel()

    async def mail_ghost(self, night):
        for m in self.inventory["mail"]:
            try:
                self.mail[m["id"]] = await self.think(
                    "triage_email", {"dir": night["dir"], "id": m["id"], "owner": night["owner"],
                                     "ghost": "mail", "target": f"mail:{m['id']}"}, f"Mail ghost reads {m['id']}")
            except ActivityError as e:
                if is_cancelled_exception(e):
                    raise
                self.mail[m["id"]] = {"label": "unread", "why": "the ghost couldn't read this one"}

    async def messages_ghost(self, night):
        for t in self.inventory.get("threads", []):
            try:
                self.threads[t["id"]] = await self.think(
                    "read_thread", {"dir": night["dir"], "id": t["id"], "app": t["app"], "owner": night["owner"],
                                    "ghost": "messages", "target": f"thread:{t['id']}"}, f"Messages ghost reads {t['id']}")
            except ActivityError as e:
                if is_cancelled_exception(e):
                    raise
                self.threads[t["id"]] = {"label": "unread", "why": "the ghost couldn't read this one"}

    async def files_ghost(self, night):
        for f in self.inventory["files"]:
            try:
                self.files[f["id"]] = await self.think(
                    "read_file_item", {"dir": night["dir"], "id": f["id"], "find": self.plan["find"], "owner": night["owner"],
                                       "folders": self.inventory.get("folders", []) if f.get("movable") else [],
                                       "ghost": "files", "target": f"file:{f['id']}"}, f"Files ghost reads {f['id']}")
            except ActivityError as e:
                if is_cancelled_exception(e):
                    raise
                self.files[f["id"]] = {"summary": "The ghost couldn't read this one.", "check": [], "answers": ""}

    async def calendar_ghost(self, night):
        letters = [f"{m['id']} | {m['from']} | {m['subject']} | {self.mail.get(m['id'], {}).get('summary', '')}"
                   for m in self.inventory["mail"] if self.mail.get(m["id"], {}).get("label") in ("reply", "fyi")]
        letters += [f"{t['id']} | {t['with']} | a chat on {t['app']} | {self.threads.get(t['id'], {}).get('summary', '')}"
                    for t in self.inventory.get("threads", []) if self.threads.get(t["id"], {}).get("label") in ("reply", "fyi")]
        files = [f"{f['id']} | {f['folder']}/{f['name']} | {self.files.get(f['id'], {}).get('summary', '')} | "
                 f"{'; '.join(self.files.get(f['id'], {}).get('check', []))}" for f in self.inventory["files"]]
        for e in self.inventory["events"]:
            try:
                self.meetings[e["id"]] = await self.think(
                    "prep_meeting", {"dir": night["dir"], "id": e["id"], "letters": letters, "files": files,
                                     "owner": night["owner"], "ghost": "calendar", "target": f"event:{e['id']}"},
                    f"Calendar ghost prepares {e['title'][:40]}")
            except ActivityError as err:
                if is_cancelled_exception(err):
                    raise
                self.meetings[e["id"]] = {"prep": [], "letters": [], "files": []}

    async def code_ghost(self, night, task):
        repo = next(r for r in night["repos"] if r["name"] == task["repo"])
        target = f"repo:{repo['name']}"
        state = self.code[repo["name"]] = {"repo": repo["name"], "goal": task["goal"], "state": "opening"}
        slug = "-".join(re.findall(r"[a-z0-9]+", task["goal"].lower())[:4])[:32] + "-" + night["stamp"]
        try:
            await self.code_work(night, task, repo, target, state, slug)
        except (ActivityError, asyncio.CancelledError) as e:
            if is_cancelled_exception(e):
                state.update(state="stopped", summary="Dawn came first; the work so far is in the worktree, not committed.")
            else:
                state.update(state="failed", summary=f"The code ghost had to stop: {e.cause or e}"[:300])

    async def code_work(self, night, task, repo, target, state, slug):
        room = await workflow.execute_activity("open_worktree", {"repo": repo, "slug": slug, "ghost": "code", "target": target},
                                               summary=f"Code ghost opens {repo['name']}", **TOOL)
        state.update(room, state="working")
        tests_now = "pass" if room["baseline"]["passed"] else "fail"
        messages = [{"role": "system", "content": ghosts.CODE_SYSTEM.format(
                        repo=repo["name"], branch=room["branch"], owner=night["owner"], goal=task["goal"])},
                    {"role": "user", "content": "Begin. The repo's files:\n" + "\n".join(room.get("tree", [])) +
                     f"\n\nRight now the tests {tests_now}."}]
        summary = None
        for turn in range(ghosts.MAX_TURNS):
            reply = await self.think("llm_turn", {"messages": messages, "tools": "code", "ghost": "code", "target": target},
                                     f"Code ghost thinks ({turn + 1})")
            messages.append(reply["message"])
            if not reply["calls"]:
                messages.append({"role": "user", "content": "Use a tool, or call finish."})
                continue
            for call in reply["calls"]:
                if call["name"] == "finish":
                    summary = call["args"]["summary"]
                    break
                done = await workflow.execute_activity(
                    "run_tool", {"root": room["path"], "call": call, "test": repo["test"], "ghost": "code", "target": target},
                    summary=f"Code ghost: {call['name']} {call['args'].get('path', '')}".strip(), **TOOL)
                messages.append({"role": "tool", "tool_name": call["name"], "content": done["text"]})
            if summary is not None:
                break
        final = await workflow.execute_activity(
            "run_tool", {"root": room["path"], "call": {"name": "run_tests", "args": {}}, "test": repo["test"],
                         "ghost": "code", "target": target}, summary="Code ghost: last test run", **TOOL)
        saved = await workflow.execute_activity("commit_work", {"root": room["path"], "message": f"ghost: {task['goal']}"[:72],
                                                                "ghost": "code", "target": target}, **QUICK)
        state.update(saved, state="done", passed=final["passed"], tests=final["text"][-1500:],
                     summary=summary or "The ghost ran out of turns before finishing.", turns=turn + 1)

    async def dawn(self, night, ended):
        self.phase, self.ended = "dawn", ended
        inv = self.inventory
        briefing = {
            "night": {"id": night["id"], "owner": night["owner"], "persona": bool(night.get("persona")), "ended": ended,
                      "gmail": bool(night.get("gmail")),
                      "model": self.model, "lights_out": self.lights_out, "peeks": self.peeks, "forecast": self.forecast,
                      "plan": self.plan, "deadline": night.get("dawn") or self.forecast.get("dawn"),
                      "finished": workflow.now().isoformat()},
            "mail": [{**m, **self.mail.get(m["id"], {"label": "unread"})} for m in inv.get("mail", [])],
            "messages": [{**t, **self.threads.get(t["id"], {"label": "unread"})} for t in inv.get("threads", [])],
            "today": [{**e, **self.meetings.get(e["id"], {})} for e in inv.get("events", [])],
            "files": [{**f, **self.files.get(f["id"], {})} for f in inv.get("files", [])],
            "code": list(self.code.values()),
            "skipped": inv.get("skipped", 0), "problems": inv.get("problems", []),
        }
        await workflow.execute_activity("write_briefing", {"dir": night["dir"], "briefing": briefing, "ghost": "keeper",
                                                           "target": "dawn"}, summary="Dawn: write the briefing", **QUICK)
        if self.model:
            await workflow.execute_activity("unload_model", {"model": self.model}, **QUICK)
        return briefing
