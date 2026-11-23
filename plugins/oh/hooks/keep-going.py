#!/usr/bin/env python3
"""Stop hook (Claude Code and Codex): one nudge back to work for an agent
that ends its turn in its goal's build phase.

An agent working toward a goal carries Herdr tab labels (the `oh:goals` skill):
`goal=<slug>`, `goal.phase=intent|plan|build|paused|done`, `goal.owner=<its
session id>`, and `blocked=<link>` while no step can move until the user acts.

It pushes back at most once per turn (a turn it already continued is let through), and only when all of these hold:
- the stopping session owns the goal, so reviewers, child sessions and a later
  session in the same tab are never pushed;
- the phase is `build` and nothing is `blocked`;
- no background work or scheduled wake-up is pending (Claude Code reports both in the event);
- this turn wasn't already continued by a Stop hook (`stop_hook_active`).

Pushes are deliberately rare: every continuation rereads the whole context, which
is what makes always-on goal loops expensive. Every stop is appended to
~/.local/state/oh/goals/<slug>.jsonl, so the spend command can price the goal and
each push. It runs `hc` only when Herdr's socket accepts a connection, so it
never starts Herdr. It does nothing while ~/.local/state/oh/keep-going.off
exists. On anything unexpected it lets the stop through.
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

HC = shutil.which("hc") or os.path.expanduser("~/.local/bin/hc")
SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def state_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return pathlib.Path(base) / "oh"


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
    if (state_dir() / "keep-going.off").exists():
        return None
    terminal = env.get("HC_TERMINAL_ID")
    if not terminal or not herdr_up(env.get("HC_TERMINAL_SOCKET")):
        return None
    tab = labels(terminal)
    goal = tab.get("goal", "")
    if not SLUG.match(goal):
        return None
    session = str(event.get("session_id") or "")[:80]
    push = bool(session
                and tab.get("goal.owner") == session
                and tab.get("goal.phase") == "build"
                and not tab.get("blocked")
                and not event.get("stop_hook_active")
                and not event.get("background_tasks")
                and not event.get("session_crons"))
    log = state_dir() / "goals" / f"{goal}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "session": session or "unknown",
                            "host": "codex" if "turn_id" in event else "claude", "push": push}) + "\n")
    if not push:
        return None
    return {"decision": "block", "reason": (
        f"Goal `{goal}` is in its build phase and isn't done, so keep going with the next step of the plan "
        "rather than ending the turn. This is the only nudge this turn. You may stop if: "
        "the goal is done (run `~/.local/bin/hc label $HC_TERMINAL_ID goal.phase=done`); no step can move until the user acts "
        "(post the task under **Needs the user** on the goal's issue, then `~/.local/bin/hc label $HC_TERMINAL_ID blocked=<link>`); "
        "the user asked you to pause (`~/.local/bin/hc label $HC_TERMINAL_ID goal.phase=paused`); or you're waiting on background "
        "work or a scheduled wake-up that will report back.")}


def main():
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            return
        result = decide(event, os.environ)
    except Exception as e:  # fail open: a broken hook must never trap an agent
        print(f"oh keep-going: letting the stop through ({type(e).__name__}: {e})", file=sys.stderr)
        return
    if result:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
