#!/usr/bin/env python3
"""Stop hook (Claude Code and Codex): keep an agent working on its goal.

An agent working toward a goal carries Herdr tab labels (the `oh:goals` skill):
`goal=<slug>`, `goal.phase=intent|plan|build|done`, and `blocked=<link>` while
only the user can unblock it. When the agent tries to end its turn in the
build phase, with nothing blocked, this hook sends it back to work: at most
three times since the user's last message, so a stuck agent can't spin.

It never pushes back outside the build phase, so conversation (the intent
questions, a status answer) ends turns normally. It runs `hc` only when Herdr's
socket accepts a connection, so it never starts Herdr. It records each session
under its goal (~/.local/state/oh/goals/<slug>.json) for the spend command.
On anything unexpected it lets the stop through.
"""
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import time

MAX_PUSHES = 3
HC = shutil.which("hc") or os.path.expanduser("~/.local/bin/hc")
SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def state_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return pathlib.Path(base) / "oh" / "goals"


def herdr_up(path):
    """True when Herdr's socket accepts a connection; never starts anything."""
    if not path or not os.path.exists(path):
        return False
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(path)
        return True
    except OSError:
        return False
    finally:
        s.close()


def labels(terminal):
    out = subprocess.run([HC, "get", terminal, "--json"], capture_output=True, text=True, timeout=3)
    return json.loads(out.stdout).get("labels") or {}


def decide(event, env):
    """The JSON to print, or None to let the stop through."""
    terminal = env.get("HC_TERMINAL_ID")
    if not terminal or not herdr_up(env.get("HC_TERMINAL_SOCKET")):
        return None
    tab = labels(terminal)
    goal = tab.get("goal", "")
    if not SLUG.match(goal):
        return None
    session = str(event.get("session_id") or "unknown")[:80]
    path = state_dir() / f"{goal}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError):
        state = {}
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    sessions = state.setdefault("sessions", {})
    seen = sessions.setdefault(session, {"first": now, "host": "codex" if "turn_id" in event else "claude"})
    seen["last"] = now
    pushes = state.setdefault("pushes", {})
    if not event.get("stop_hook_active"):
        pushes[session] = 0  # a new user message: the count starts again
    push = None
    if tab.get("goal.phase") == "build" and not tab.get("blocked") and pushes.get(session, 0) < MAX_PUSHES:
        pushes[session] = pushes.get(session, 0) + 1
        push = pushes[session]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(path)
    if push is None:
        return None
    return {"decision": "block", "reason": (
        f"Goal `{goal}` is in its build phase and isn't done (keep-going push {push} of {MAX_PUSHES}). "
        "Continue with the next step of the plan. If only the user can unblock it, post the task under "
        "**Needs the user** on the goal's issue (the `oh:goals` template) and run "
        f"`hc label {terminal} blocked=<link to it>`. When the goal is done, run "
        f"`hc label {terminal} goal.phase=done`.")}


def main():
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            return
        result = decide(event, os.environ)
    except Exception:  # fail open: a broken hook must never trap an agent
        return
    if result:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
