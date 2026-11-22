"""keep-going.py: pushes back only in a goal's build phase, at most three times
per user message, never without Herdr, and lets the stop through on any error."""
import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import unittest

HOOK = pathlib.Path(__file__).resolve().parents[1] / "plugins/oh/hooks/keep-going.py"


class KeepGoing(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        d = pathlib.Path(self.dir.name)
        self.state = d / "state"
        self.calls = d / "calls"
        bin_ = d / "bin"
        bin_.mkdir()
        fake = bin_ / "hc"
        fake.write_text("#!/bin/sh\necho \"$@\" >> \"$HC_CALLS\"\nprintf '%s' \"$FAKE_HC_JSON\"\n")
        fake.chmod(0o755)
        self.sock_path = str(d / "herdr.sock")
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.sock_path)
        self.server.listen(8)
        self.env = {"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(d), "XDG_STATE_HOME": str(self.state),
                    "HC_TERMINAL_ID": "t9", "HC_TERMINAL_SOCKET": self.sock_path, "HC_CALLS": str(self.calls)}

    def tearDown(self):
        self.server.close()
        self.dir.cleanup()

    def run_hook(self, labels, event=None, env=None, raw=None):
        e = {**self.env, "FAKE_HC_JSON": json.dumps({"address": "t9", "labels": labels}), **(env or {})}
        stdin = raw if raw is not None else json.dumps(event or {"session_id": "s1", "stop_hook_active": False})
        out = subprocess.run([sys.executable, "-IB", str(HOOK)], input=stdin, capture_output=True, text=True, env=e, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout) if out.stdout.strip() else None

    def test_build_phase_blocks_with_the_goal_named(self):
        r = self.run_hook({"goal": "rules-release", "goal.phase": "build"})
        self.assertEqual(r["decision"], "block")
        self.assertIn("rules-release", r["reason"])
        self.assertIn("push 1 of 3", r["reason"])

    def test_other_phases_let_the_stop_through(self):
        for phase in ("intent", "plan", "done", ""):
            self.assertIsNone(self.run_hook({"goal": "g", "goal.phase": phase}), phase)

    def test_blocked_lets_the_stop_through(self):
        self.assertIsNone(self.run_hook({"goal": "g", "goal.phase": "build", "blocked": "https://x/1"}))

    def test_no_goal_or_bad_slug_lets_the_stop_through(self):
        self.assertIsNone(self.run_hook({"goal.phase": "build"}))
        self.assertIsNone(self.run_hook({"goal": "../etc", "goal.phase": "build"}))

    def test_three_pushes_per_user_message_then_stop(self):
        lab = {"goal": "g", "goal.phase": "build"}
        self.assertIsNotNone(self.run_hook(lab, {"session_id": "s1", "stop_hook_active": False}))
        self.assertIsNotNone(self.run_hook(lab, {"session_id": "s1", "stop_hook_active": True}))
        self.assertIsNotNone(self.run_hook(lab, {"session_id": "s1", "stop_hook_active": True}))
        self.assertIsNone(self.run_hook(lab, {"session_id": "s1", "stop_hook_active": True}))
        # the user's next message starts the count again
        self.assertIsNotNone(self.run_hook(lab, {"session_id": "s1", "stop_hook_active": False}))

    def test_without_herdr_hc_is_never_called(self):
        self.assertIsNone(self.run_hook({"goal": "g", "goal.phase": "build"}, env={"HC_TERMINAL_SOCKET": self.sock_path + ".gone"}))
        self.assertIsNone(self.run_hook({"goal": "g", "goal.phase": "build"}, env={"HC_TERMINAL_ID": ""}))
        self.assertFalse(self.calls.exists())

    def test_malformed_input_lets_the_stop_through(self):
        self.assertIsNone(self.run_hook({"goal": "g", "goal.phase": "build"}, raw="not json"))
        self.assertIsNone(self.run_hook({"goal": "g", "goal.phase": "build"}, raw="[1]"))
        self.assertIsNone(self.run_hook({"goal": "g", "goal.phase": "build"}, env={"FAKE_HC_JSON": "garbage"}))

    def test_sessions_are_recorded_under_the_goal(self):
        self.run_hook({"goal": "g", "goal.phase": "plan"}, {"session_id": "claude-1"})
        self.run_hook({"goal": "g", "goal.phase": "build"}, {"session_id": "codex-1", "turn_id": "x"})
        state = json.loads((self.state / "oh/goals/g.json").read_text())
        self.assertEqual(state["sessions"]["claude-1"]["host"], "claude")
        self.assertEqual(state["sessions"]["codex-1"]["host"], "codex")


if __name__ == "__main__":
    unittest.main()
