import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

GUARD = pathlib.Path(__file__).resolve().parent.parent / "plugins/oh/hooks/prod-guard.py"

# A home like this machine's: ~/.kube/config names no current-context. Kubeconfigs for each side beside it.
HOME = pathlib.Path(tempfile.mkdtemp(prefix="prod-guard-"))
(HOME / ".kube").mkdir()
(HOME / ".kube/config").write_text("apiVersion: v1\ncontexts: []\n")
(HOME / "prod.yaml").write_text("apiVersion: v1\ncurrent-context: \"default\"\n")
(HOME / "kind.yaml").write_text("apiVersion: v1\ncurrent-context: kind-breakdown-rehearsal\n")
(HOME / "drop.sql").write_text("BEGIN;\n-- clean up\nDROP TABLE old_runs;\nCOMMIT;\n")
(HOME / "read.sql").write_text("SELECT count(*) FROM shops; -- DROP nothing\n")
OUTSIDE = str(HOME)
REPLICA = "kubectl exec -i -n default \"$replica\" -c postgres -- psql -U postgres -d breakdown_admin_prod -v ON_ERROR_STOP=1 -At <<'SQL'\n{}\nSQL"

# Always the user's step.
DENIED = [
    "gh pr merge 12 --squash",
    "mise exec -- gh pr merge 12 --auto --merge",
    "MISE_EXEC_AUTO_INSTALL=false mise exec -- gh -R o/r pr merge 12",
    "gh api -X PUT repos/o/r/pulls/12/merge",
    "gh api repos/o/r/pulls/12/merge -f merge_method=squash",
    "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"x\"}) { clientMutationId } }'",
    "gh api graphql -F query='mutation { enablePullRequestAutoMerge(input: {pullRequestId: \"x\"}) { clientMutationId } }'",
    "gh api -X DELETE repos/o/r",
    "gh repo delete o/r --yes",
    "git push --force",
    "git push -f origin feat/x",
    "git push -uf origin feat/x",
    "git push --force-with-lease origin feat/x",
    "git push --force-with-lease=feat/x:abc origin feat/x",
    "git push origin +feat/x:feat/x",
    "git push --mirror",
    "git push origin --all",
    "git push origin HEAD:main",
    "git push origin feat:refs/heads/main",
    "git push origin master",
    "git push origin --delete main",
    "cd /tmp && git push origin HEAD:master",
    "bash -c 'git push origin HEAD:main'",
    "ssh vm 'cd repo && git push origin main'",
    "echo ok && $(gh pr merge 3)",
]

# Irreversible in production: the user approves each one.
ASKED = [
    "kubectl delete pvc data --context default",
    "kubectl delete pod x",
    "kubectl --context default -n prod delete pods -l app=x",
    "kubectl --context=default delete deploy x",
    "kubectl delete ns x --all --context default",
    f"KUBECONFIG={HOME}/prod.yaml kubectl delete ns x",
    f"export KUBECONFIG={HOME}/prod.yaml; kubectl delete ns x",
    f"kubectl --kubeconfig {HOME}/prod.yaml drain node1",
    f"kubectl --kubeconfig={HOME}/missing.yaml:{HOME}/prod.yaml cordon node1",
    "KUBECONFIG=$SCRATCH/prod.yaml kubectl delete ns x",
    "kubectl --context \"$CTX\" delete job x",
    "kubectl scale deploy/x --replicas=0 --context default",
    "kubectl scale deploy/x --replicas 0 --context default",
    "helm uninstall x --kube-context default",
    f"helm --kubeconfig {HOME}/prod.yaml uninstall x",
    "ssh vm 'kubectl delete ns x'",
    "ssh vm kubectl get pods; ssh vm kubectl delete pod x",
    "psql \"postgres://u@db.prod/app\" -c 'TRUNCATE t'",
    "psql -h db.prod -c 'DELETE FROM t'",
    "psql --host=10.0.0.5 --command='drop table t'",
    "PGHOST=db.prod psql -c 'DROP TABLE t'",
    "psql 'host=db.prod dbname=app' -c 'ALTER TABLE t DROP COLUMN c'",
    "psql -h db.prod -f drop.sql",
    "psql -h db.prod < drop.sql",
    "cat drop.sql | psql -h db.prod",
    "kubectl exec -n prod pg-0 -- psql -c 'DROP TABLE t'",
    "kubectl exec -it pg-0 --context default -- sh -c \"psql -c 'DROP TABLE t'\"",
    REPLICA.format("TRUNCATE t;"),
    REPLICA.format("BEGIN;\nDELETE FROM jobs;\nCOMMIT;"),
    "cat <<'SQL' | psql -h db.prod\nDROP TABLE t;\nSQL",
    "ssh vm psql -c 'DROP TABLE t'",
    "ssh vm <<'EOF'\npsql -c 'DROP TABLE t'\nEOF",
]

# Everyday work, including the release routine, local clusters and local databases.
ALLOWED = [
    "kubectl rollout restart deploy/breakdown-rosearch --context default",
    "kubectl -n argocd annotate application production-apps argocd.argoproj.io/refresh=hard --overwrite --context default",
    "kubectl -n argocd patch application production-apps --type merge -p '{\"operation\":{\"sync\":{}}}' --context default",
    "kubectl create -f job.yaml --context default",
    "kubectl get pods -A --context default",
    "kubectl logs deploy/x --context default",
    "kubectl delete pod x --context kind-breakdown-rehearsal",
    f"KUBECONFIG={HOME}/kind.yaml kubectl delete ns x",
    "kubectl delete pod x --context default --dry-run=server",
    "kubectl scale deploy/x --replicas=2 --context default",
    "kubectl describe node drain --context default",
    "helm upgrade --install x chart --kube-context default",
    "helm uninstall x --kube-context k3d-dev",
    "git push -u origin feat/x",
    "git push origin feat/x:feat/x",
    "git push origin v1.2.3",
    "git push --follow-tags origin feat/x",
    "git push origin --delete feat/old",
    "git fetch origin main && git merge origin/main",
    "git commit -m 'never git push --force to main; gh pr merge is the user'\"'\"'s'",
    "gh pr create --draft --title x --body \"$(cat <<'EOF'\nDon't run gh pr merge or kubectl delete ns x --context default.\nEOF\n)\"",
    "gh pr view 12 --json mergeable",
    "gh pr checks 12 --watch",
    "gh api repos/o/r/pulls/12/merge",
    "gh api -X PATCH repos/o/r/pulls/12 -F body=@body.md",
    "gh api graphql -f query='query { repository(owner:\"o\", name:\"r\") { name } }'",
    "gh api repos/o/r/issues/18/comments -f body='use mergePullRequest? no'",
    "psql -h localhost -c 'DROP TABLE t'",
    "psql -c 'DROP DATABASE scratch'",
    "psql postgres://u@127.0.0.1:5432/app -c 'TRUNCATE t'",
    "psql -h /tmp -c 'DROP TABLE t'",
    "psql -h db.prod -c 'DELETE FROM t WHERE id = 1'",
    "psql -h db.prod -c 'SELECT drop_count FROM stats'",
    "psql -h db.prod -c 'ALTER TABLE t DROP CONSTRAINT c'",
    "psql -h db.prod -f read.sql",
    "psql -h db.prod < read.sql",
    "kubectl exec -n default pg-0 --context kind-test -- psql -c 'DROP TABLE t'",
    REPLICA.format("SELECT count(*) FROM shops;"),
    REPLICA.format("DELETE FROM t\nWHERE id = 1;"),
    "cat > notes.md <<'EOF'\nkubectl delete ns x --context default\nDROP TABLE t;\nEOF",
    "grep -rn 'kubectl delete' docs/",
    "docker exec -i pg psql -U postgres <<'SQL'\nDROP TABLE t;\nSQL",
    "MIX_ENV=test mix test",
]


def run(command, cwd=OUTSIDE, raw=None, env=None):
    event = raw if raw is not None else json.dumps({
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd,
    })
    environment = {"HOME": str(HOME), "PATH": os.environ.get("PATH", "/usr/bin:/bin"), **(env or {})}
    result = subprocess.run(
        [sys.executable, "-IB", str(GUARD)], input=event, capture_output=True, text=True, check=True, env=environment,
    )
    return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else None


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class Guard(unittest.TestCase):
    def check(self, commands, decision, cwd=OUTSIDE):
        for command in commands:
            with self.subTest(command=command):
                out = run(command, cwd=cwd)
                if decision is None:
                    self.assertIsNone(out)
                else:
                    self.assertIsNotNone(out)
                    self.assertEqual(out["permissionDecision"], decision)

    def test_denied(self):
        self.check(DENIED, "deny")

    def test_asked(self):
        self.check(ASKED, "ask")

    def test_allowed(self):
        self.check(ALLOWED, None)

    def test_reasons_say_what_and_where(self):
        self.assertIn("kube context `default`", run("kubectl delete ns x --context default")["permissionDecisionReason"])
        self.assertIn("can't resolve", run("kubectl --context $C delete ns x")["permissionDecisionReason"])
        self.assertIn("! <command>", run("gh pr merge 1")["permissionDecisionReason"])

    def test_unknown_context_counts_as_production(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run("kubectl delete ns x", env={"HOME": d})["permissionDecision"], "ask")
        self.assertIsNone(run("kubectl delete ns x", env={"KUBECONFIG": str(HOME / "kind.yaml")}))
        self.assertEqual(run("kubectl delete ns x", env={"KUBECONFIG": str(HOME / "prod.yaml")})["permissionDecision"], "ask")

    def test_codex_gets_deny_for_asked_cases(self):
        event = {"tool_name": "Bash", "turn_id": "t1", "cwd": OUTSIDE,
                 "tool_input": {"command": ["bash", "-lc", "kubectl delete ns x --context default"]}}
        out = run(None, raw=json.dumps(event))
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("Codex can't ask", out["permissionDecisionReason"])

    def test_deny_wins_over_ask(self):
        out = run("kubectl delete ns x --context default; gh pr merge 1")
        self.assertEqual(out["permissionDecision"], "deny")

    def test_default_branch_comes_from_the_repository(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            git("init", "-q", "--bare", "-b", "trunk", "origin.git", cwd=d)
            git("clone", "-q", "origin.git", "work", cwd=d)
            work = root / "work"
            git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x", cwd=work)
            git("push", "-q", "origin", "trunk", cwd=work)
            git("remote", "set-head", "origin", "trunk", cwd=work)
            self.check(["git push", "git push origin HEAD", "git push -u origin HEAD", "git push origin trunk"], "deny", cwd=str(work))
            self.check([f"git -C {work} push", f"cd {work} && git push"], "deny")
            git("switch", "-q", "-c", "feat/x", cwd=work)
            self.check(["git push", "git push origin HEAD", "git push -u origin feat/x"], None, cwd=str(work))
            self.check(["git push origin HEAD:trunk", "git push origin main"], "deny", cwd=str(work))
            git("config", "push.default", "upstream", cwd=work)
            git("branch", "-q", "--set-upstream-to", "origin/trunk", cwd=work)
            self.check(["git push"], "deny", cwd=str(work))

    def test_shell_scripts_are_read_before_they_run(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "drill.sh").write_text("#!/bin/sh\nkubectl --context \"$CTX\" delete cluster \"$DRILL\"\n")
            (root / "deploy.sh").write_text(
                "#!/usr/bin/env bash\nset -e\nkubectl get deploy \"$1\"\n"
                "kubectl -n argocd patch application production-apps --type merge -p '{}'\n"
                "kubectl rollout restart deploy/\"$1\"\nkubectl rollout status deploy/\"$1\"\n"
            )
            self.check(["bash drill.sh", "./drill.sh"], "ask", cwd=d)
            self.check([f"KUBECONFIG={HOME}/prod.yaml scripts/../deploy.sh x", "bash deploy.sh x", "cat drill.sh"], None, cwd=d)

    def test_fast_on_large_input(self):
        commands = [
            "cat > notes.md <<'EOF'\n" + "- never kubectl delete ns x --context default\n" * 5000 + "EOF\n",
            "echo " + "word " * 40000 + "\"unterminated",
        ]
        for command in commands:
            start = time.monotonic()
            self.assertIsNone(run(command))
            self.assertLess(time.monotonic() - start, 5)

    def test_bad_input_passes(self):
        self.assertIsNone(run(None, raw="not json"))
        for event in [
            {"tool_name": "Write", "tool_input": {"file_path": "x"}},
            {"tool_name": "Bash", "tool_input": {"command": "gh pr merge 1"}, "cwd": 123},
            {"tool_name": "Bash", "tool_input": ["gh pr merge 1"], "cwd": OUTSIDE},
            {"tool_name": "Bash", "tool_input": {"command": {"a": 1}}, "cwd": OUTSIDE},
        ]:
            with self.subTest(event=event):
                result = subprocess.run([sys.executable, "-IB", str(GUARD)], input=json.dumps(event), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
