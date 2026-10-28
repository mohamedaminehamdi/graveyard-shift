"""Turn a night's raw Temporal history into the graveyard's script.

Every step on the page is one activity from the history: when it was queued, when a ghost picked it up, which attempt
it was (a retry after a crash shows as a ghost rising again), and its result. Nothing is added; CI rebuilds the
published night.json from the published history.json and fails if they differ.
"""
import base64
import hashlib
import json
from datetime import datetime


def _payload(p):
    items = (p or {}).get("payloads") or []
    return json.loads(base64.b64decode(items[0]["data"])) if items and items[0].get("data") else None


def _when(stamp):
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _short(text, n=140):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _result(name, arg, res):
    """Only what the scene and its captions need."""
    if res is None:
        return None
    if name == "triage_email":
        return {"label": res["label"], "why": _short(res["why"], 90), "caught_by": res.get("caught_by", [])}
    if name == "read_file_item":
        return {"kind": res["kind"], "summary": _short(res["summary"]), "answers": res["answers"], "check": len(res["check"])}
    if name == "prep_meeting":
        return {"prep": len(res["prep"]), "letters": res["letters"], "files": res["files"]}
    if name == "llm_turn":
        if res.get("content") is not None:   # the Keeper's plan
            return {"plan": {k: res["content"].get(k) for k in ("code", "find", "prep_first")}}
        calls = [{"name": c["name"], "path": c["args"].get("path", c["args"].get("pattern", ""))} for c in res["calls"]]
        return {"calls": calls, "said": _short(res["message"].get("content"), 120)}
    if name == "run_tool":
        call = arg["call"]
        return {"tool": call["name"], "path": call["args"].get("path", call["args"].get("pattern", "")), "passed": res["passed"]}
    if name == "open_worktree":
        return {"branch": res["branch"], "baseline": res["baseline"]["passed"], "stale": res["status"]["stale"]}
    if name == "commit_work":
        return {"sha": res["sha"], "stat": res["stat"].splitlines()[-1] if res["stat"] else ""}
    if name == "forecast_dawn":
        return {k: res.get(k) for k in ("lights_out", "wake", "dawn", "nights", "curve")}
    if name == "check_sleep":
        return res
    if name == "choose_model":
        return {"model": res}
    if name == "gather":
        return res
    return None


def build(history, meta=None):
    events = history["events"]
    start = _when(events[0]["eventTime"])
    at = lambda e: round((_when(e["eventTime"]) - start).total_seconds(), 1)
    queued, steps, marks, final = {}, [], [], None
    for e in events:
        kind = e["eventType"].removeprefix("EVENT_TYPE_")
        attrs = next((v for k, v in e.items() if k.endswith("EventAttributes")), {})
        if kind == "ACTIVITY_TASK_SCHEDULED":
            queued[e["eventId"]] = {"act": attrs["activityType"]["name"], "arg": _payload(attrs.get("input")) or {},
                                    "queued": at(e), "queue": attrs["taskQueue"]["name"]}
        elif kind == "ACTIVITY_TASK_STARTED":
            q = queued[attrs["scheduledEventId"]]
            q.update(start=at(e), attempt=attrs.get("attempt", 1),
                     retried=_short((attrs.get("lastFailure") or {}).get("message"), 100) or None)
        elif kind.startswith("ACTIVITY_TASK_") and kind.split("_")[-1] in ("COMPLETED", "FAILED", "OUT", "CANCELED"):
            q = queued[attrs["scheduledEventId"]]
            arg, res = q["arg"], _payload(attrs.get("result"))
            steps.append({
                "t": q.get("start", q["queued"]), "end": at(e), "queued": q["queued"], "act": q["act"],
                "ghost": arg.get("ghost", "keeper"), "target": arg.get("target", ""), "candle": q["queue"] == "candle",
                "attempt": q.get("attempt", 1), "retried": q.get("retried"),
                "outcome": {"COMPLETED": "done", "FAILED": "failed", "OUT": "timed out", "CANCELED": "cancelled"}[kind.split("_")[-1]],
                "result": _result(q["act"], arg, res), "tokens": (res or {}).get("tokens") if isinstance(res, dict) else None,
                "model": arg.get("model"),
            })
        elif kind == "TIMER_FIRED":
            marks.append({"t": at(e), "mark": "peek"})
        elif kind == "WORKFLOW_EXECUTION_SIGNALED":
            marks.append({"t": at(e), "mark": attrs.get("signalName", "signal")})
        elif kind == "WORKFLOW_EXECUTION_COMPLETED":
            final = _payload(attrs.get("result"))
    raw = json.dumps(history, sort_keys=True).encode()
    header = {"workflow_id": events[0].get("workflowExecutionStartedEventAttributes", {}).get("workflowId")
              or (final or {}).get("night", {}).get("id"),
              "started": start.isoformat(), "length_s": at(events[-1]), "events": len(events),
              "history_sha256": hashlib.sha256(raw).hexdigest(), **(meta or {})}
    return {"header": header, "steps": sorted(steps, key=lambda s: s["t"]), "marks": marks, "briefing": final}
