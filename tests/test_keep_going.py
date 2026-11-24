"""keep-going.py: pushes back in a goal's build phase, or on a question to the
user in its plan or build phase, at most once per turn, only for the session
that owns the goal, never in plan mode or without Herdr, and lets the stop
through on any error."""
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

    OWNED = {"goal": "g", "goal.phase": "build", "goal.owner": "s1"}

    def stop(self, **kw):
        return {"session_id": "s1", "stop_hook_active": False, **kw}

    def test_owner_in_build_gets_one_push_naming_the_goal_and_the_exits(self):
        r = self.run_hook(dict(self.OWNED, goal="rules-release"), self.stop())
        self.assertEqual(r["decision"], "block")
        for text in ("rules-release", "only nudge this turn", "goal.phase=done", "blocked=", "goal.phase=paused", "background"):
            self.assertIn(text, r["reason"])

    def said(self, text, **kw):
        return self.stop(last_assistant_message=text, **kw)

    def test_a_turn_ending_on_a_question_is_nudged_to_post_it(self):
        for phase in ("plan", "build"):
            r = self.run_hook(dict(self.OWNED, **{"goal.phase": phase}), self.said("Done.\n\n**Shall I use the Mapleset web repos?**"))
            self.assertEqual(r["decision"], "block", phase)
            for text in ("sugar post", "can't be undone", "Only if no step can move", "carry on"):
                self.assertIn(text, r["reason"])
        log = (self.state / "oh/goals/g.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(log[-1])["nudge"], "question")

    def test_no_question_nudge_outside_plan_and_build_or_in_plan_mode(self):
        q = "What should it be called?"
        for phase in ("intent", "paused", "done", "", "Plan"):
            self.assertIsNone(self.run_hook(dict(self.OWNED, **{"goal.phase": phase}), self.said(q)), phase)
        self.assertIsNone(self.run_hook(dict(self.OWNED, **{"goal.phase": "plan"}), self.said(q, permission_mode="plan")))
        self.assertIsNone(self.run_hook(dict(self.OWNED, **{"goal.phase": "plan", "blocked": "http://board.example.invalid/items/9"}), self.said(q)))
        self.assertIsNone(self.run_hook(dict(self.OWNED, **{"goal.phase": "plan"}), {"session_id": "reviewer-7", "stop_hook_active": False, "last_assistant_message": q}))

    def test_no_nudge_of_either_kind_in_plan_mode(self):
        self.assertIsNone(self.run_hook(self.OWNED, self.stop(permission_mode="plan")))

    def test_things_that_only_end_in_a_question_mark_are_not_questions(self):
        for text in ("Posted the plan. Waiting on the approval ask.",
                     "Checked the predicate `Accounts.admin?`",
                     "The search link is https://example.invalid/search?",
                     "Done.\n\n> Why does it fail?",
                     "Done.\n\n## Why does it fail?",
                     "Done.\n\n    if ok?",
                     "Done.\n\n```\nready?\n```"):
            self.assertIsNone(self.run_hook(dict(self.OWNED, **{"goal.phase": "plan"}), self.said(text)), text)

    def test_a_turn_already_continued_is_not_pushed_again(self):
        self.assertIsNone(self.run_hook(self.OWNED, self.stop(stop_hook_active=True)))

    def test_other_sessions_are_never_pushed(self):
        self.assertIsNone(self.run_hook(self.OWNED, {"session_id": "reviewer-7", "stop_hook_active": False}))
        self.assertIsNone(self.run_hook({"goal": "g", "goal.phase": "build"}, self.stop()))  # no owner label

    def test_other_phases_blocked_and_background_work_let_the_stop_through(self):
        for phase in ("intent", "plan", "paused", "done", ""):
            self.assertIsNone(self.run_hook(dict(self.OWNED, **{"goal.phase": phase}), self.stop()), phase)
        self.assertIsNone(self.run_hook(dict(self.OWNED, blocked="https://x/1"), self.stop()))
        self.assertIsNone(self.run_hook(self.OWNED, self.stop(background_tasks=[{"id": "b1"}])))
        self.assertIsNone(self.run_hook(self.OWNED, self.stop(session_crons=[{"id": "c1"}])))

    def test_bad_slug_lets_the_stop_through(self):
        self.assertIsNone(self.run_hook(dict(self.OWNED, goal="../etc"), self.stop()))

    def test_without_herdr_hc_is_never_called(self):
        self.assertIsNone(self.run_hook(self.OWNED, env={"HC_TERMINAL_SOCKET": self.sock_path + ".gone"}))
        self.assertIsNone(self.run_hook(self.OWNED, env={"HC_TERMINAL_ID": ""}))
        self.assertFalse(self.calls.exists())

    def test_off_switch(self):
        (self.state / "oh").mkdir(parents=True, exist_ok=True)
        (self.state / "oh/keep-going.off").write_text("")
        self.assertIsNone(self.run_hook(self.OWNED, self.stop()))
        self.assertFalse(self.calls.exists())

    def test_malformed_input_lets_the_stop_through(self):
        self.assertIsNone(self.run_hook(self.OWNED, raw="not json"))
        self.assertIsNone(self.run_hook(self.OWNED, raw="[1]"))
        self.assertIsNone(self.run_hook(self.OWNED, self.stop(), env={"FAKE_HC_JSON": "garbage"}))

    def test_every_stop_is_logged_with_its_host_and_push(self):
        self.run_hook(dict(self.OWNED, **{"goal.phase": "plan"}), {"session_id": "claude-1"})
        self.run_hook(self.OWNED, self.stop(turn_id="x"))
        rows = [json.loads(l) for l in (self.state / "oh/goals/g.jsonl").read_text().splitlines()]
        self.assertEqual([(r["session"], r["host"], r["push"]) for r in rows], [("claude-1", "claude", False), ("s1", "codex", True)])


if __name__ == "__main__":
    unittest.main()
