"""The code ghost's room: a git worktree on its own branch, a path guard, and tests run inside a macOS sandbox
with no network, no writes outside the worktree, and no reads of your keys or personal folders.

The model writes the tests it runs, so the sandbox, not the test command, is the real boundary.
"""
import os
import subprocess
import tempfile
import time
from pathlib import Path

from .sources import git

HOME = Path.home()
PRIVATE = [".ssh", ".aws", ".config", ".gnupg", ".netrc", ".docker", ".kube", ".graveyard-shift/nights",
           "Library", "Desktop", "Documents", "Downloads", "Pictures", "Movies", "Music"]
PROFILE = """(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write* (subpath "{root}") (subpath "{tmp}") (literal "/dev/null") (literal "/dev/zero") (regex #"^/dev/(tty|fd/)"))
(deny file-read* {private})
"""
GHOST = ["-c", "user.name=Code ghost", "-c", "user.email=ghost@graveyard-shift.invalid"]


class Refused(Exception):
    pass


def inside(root, rel):
    """A path in the worktree, or Refused. Absolute paths, ../ escapes, symlinks out and .git are all refused."""
    root = Path(root).resolve()
    if not rel or os.path.isabs(rel) or rel.startswith("~"):
        raise Refused("Use a path relative to the repo root.")
    path = (root / rel).resolve()
    if path != root and root not in path.parents:
        raise Refused("That path is outside the repo.")
    if ".git" in path.relative_to(root).parts:
        raise Refused("The .git folder is off limits.")
    return path


def make_worktree(repo, root, slug):
    """A private copy of the repo on branch ghost/<slug>. Safe to call again after a crash."""
    branch, path = f"ghost/{slug}", Path(root) / f"{Path(repo).name}-{slug}"
    if not (path / ".git").exists():
        Path(root).mkdir(parents=True, exist_ok=True)
        exists = git(repo, "branch", "--list", branch).strip()
        git(repo, "worktree", "add", "-q", *([] if exists else ["-b", branch]), str(path), *([branch] if exists else ["HEAD"]))
    return {"path": str(path), "branch": branch}


def run_sandboxed(root, command, heartbeat=lambda: None, timeout=180):
    """Run the repo's test command in the sandbox. Returns (passed, output)."""
    root, tmp = os.path.realpath(root), os.path.realpath(tempfile.mkdtemp(prefix="ghost-tests-"))
    private = " ".join(f'(subpath "{os.path.realpath(HOME / p)}")' for p in PRIVATE)
    profile = PROFILE.format(root=root, tmp=tmp, private=private)
    env = {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "HOME": tmp, "TMPDIR": tmp + "/",
           "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.Popen(["/usr/bin/sandbox-exec", "-p", profile, "/bin/sh", "-c", command], cwd=root, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    give_up = time.monotonic() + timeout
    while True:
        try:
            out, _ = proc.communicate(timeout=10)
            return proc.returncode == 0, out
        except subprocess.TimeoutExpired:
            heartbeat()
            if time.monotonic() > give_up:
                os.killpg(proc.pid, 9)
                return False, (proc.communicate()[0] or "") + f"\n(stopped after {timeout} s)"


def run_tool(root, call, test_command, heartbeat=lambda: None):
    """Do one tool call from the code ghost and describe the result in words."""
    name, args = call["name"], call["args"]
    root = Path(root)
    try:
        if name == "list_dir":
            folder = inside(root, args["path"] or ".") if args["path"] not in ("", ".", "./") else root
            if not folder.is_dir():
                return "That is not a folder."
            names = sorted(p.name + "/" * p.is_dir() for p in folder.iterdir() if p.name not in (".git", "__pycache__"))
            return "\n".join(names[:200]) or "(empty folder)"
        if name == "read_file":
            path = inside(root, args["path"])
            if not path.is_file():
                return "No such file."
            text = path.read_text(errors="replace")
            return text[:8000] + ("\n…(cut: the file goes on)" if len(text) > 8000 else "")
        if name == "search":
            r = subprocess.run(["git", "-C", str(root), "grep", "-n", "-I", "-E", "--untracked", "-e", args["pattern"][:200], "--"],
                               capture_output=True, text=True, timeout=30)
            return "\n".join(r.stdout.splitlines()[:60]) or "No matches."
        if name == "write_file":
            path = inside(root, args["path"])
            if len(args["content"]) > 200_000:
                return "Refused: that file is too big."
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"])
            return f"Wrote {args['path']} ({args['content'].count(chr(10)) + 1} lines)."
        if name == "run_tests":
            passed, out = run_sandboxed(root, test_command, heartbeat)
            return ("PASSED" if passed else "FAILED") + "\n" + out[-3000:]
        if name == "git_diff":
            git(root, "add", "-A", "-N")
            diff = git(root, "diff")
            return diff[:6000] or "No changes yet."
    except Refused as e:
        return f"Refused: {e}"
    except (OSError, UnicodeError, RuntimeError, KeyError) as e:
        return f"That didn't work: {e}"
    return f"There is no tool called {name}."


def commit(root, message):
    """Commit the ghost's work on its branch (never on yours). Hooks stay off."""
    git(root, "add", "-A")
    if not git(root, "status", "--porcelain").strip():
        return {"sha": None, "stat": "", "diff": ""}
    git(root, *GHOST, "commit", "-qm", message)
    return {"sha": git(root, "rev-parse", "--short", "HEAD").strip(),
            "stat": git(root, "show", "--stat", "--format=", "HEAD").strip(),
            "diff": git(root, "show", "--format=", "HEAD")[:20000]}


def keep(repo, path):
    """Keep: the branch stays for you to merge; only the extra checkout goes."""
    git(repo, "worktree", "remove", "--force", str(path), check=False)


def exorcise(repo, path, branch):
    """Exorcise: the ghost's checkout and branch are gone, as if it never came."""
    if not branch.startswith("ghost/"):
        raise ValueError("only ghost branches can be exorcised")
    keep(repo, path)
    git(repo, "branch", "-D", branch, check=False)
