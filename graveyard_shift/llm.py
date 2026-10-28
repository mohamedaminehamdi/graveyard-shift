"""Local Gemma 4 through Ollama on this Mac. Nothing here talks to anything but 127.0.0.1."""
import json
import re
import subprocess
import urllib.request

OLLAMA = "http://127.0.0.1:11434"
NIGHT = "gemma4:26b-a4b-it-qat"   # 15.6 GB, fits the Air's ~19 GB GPU budget; the plain 26b tag (18.7 GB) spills
LIGHT = "gemma4:e4b"              # the fallback when the big one can't keep up
CTX = 16384                       # the same on every call: a different num_ctx makes Ollama reload the model


def chat(messages, model=NIGHT, schema=None, tools=None, timeout=900):
    """One reply. No streaming and no thinking: Gemma 4's tool calls leak into the thinking field when either is on."""
    if "cloud" in model:
        raise ValueError(f"{model} would run off this Mac; the ghosts only use local models")
    body = {"model": model, "messages": messages, "stream": False, "think": False, "keep_alive": "20m",
            "options": {"num_ctx": CTX, "temperature": 0.2}}
    if schema:
        body["format"] = schema
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(f"{OLLAMA}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)
    if "error" in out:
        raise RuntimeError(out["error"])
    return out


def ask(system, user, schema, model=NIGHT):
    """A JSON answer that matches the schema (Ollama constrains decoding to it), plus token counts."""
    out = chat([{"role": "system", "content": system}, {"role": "user", "content": user}], model=model, schema=schema)
    answer = json.loads(out["message"]["content"])
    return answer, {"in": out.get("prompt_eval_count", 0), "out": out.get("eval_count", 0)}


def unload(model):
    """Free the GPU at dawn."""
    req = urllib.request.Request(f"{OLLAMA}/api/generate", data=json.dumps({"model": model, "keep_alive": 0}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except OSError:
        pass


def ready(model):
    """Is Ollama up, with this model downloaded?"""
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=5) as r:
            return any(m["name"] == model for m in json.load(r)["models"])
    except OSError:
        return False


def free_gb():
    """Memory macOS can hand out without swapping: free, inactive, speculative and purgeable pages."""
    out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    page = int(re.search(r"page size of (\d+)", out).group(1))
    pages = sum(int(re.search(rf"{k}:\s+(\d+)", out).group(1)) for k in ("free", "inactive", "speculative", "purgeable"))
    return pages * page / 1e9


def pick():
    """The biggest Gemma that fits tonight. With Chrome and an editor open, the 26B would push ~20 GB to swap."""
    return NIGHT if ready(NIGHT) and free_gb() >= 18 else LIGHT
