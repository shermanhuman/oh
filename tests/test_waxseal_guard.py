import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

GUARD = pathlib.Path(__file__).resolve().parent.parent / "plugins/oh/hooks/waxseal-guard.py"


def run(command, cwd=None, raw=None):
    event = raw if raw is not None else json.dumps({
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd or tempfile.gettempdir(),
    })
    result = subprocess.run([sys.executable, "-I", str(GUARD)], input=event, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else None


class Blocks(unittest.TestCase):
    def assertBlocked(self, command):
        out = run(command)
        self.assertIsNotNone(out, command)
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("waxseal", out["permissionDecisionReason"])

    def test_kubeseal(self):
        for command in [
            "kubeseal --format yaml < secret.yaml > sealed.yaml",
            "kubectl create secret generic x --dry-run=client -o yaml | kubeseal --cert cert.pem",
            "FOO=1 sudo -E /usr/local/bin/kubeseal --version",
            "mise exec -- kubeseal --fetch-cert",
            "echo start; $(kubeseal --version)",
            "bash -c 'kubeseal --version'",
            "bash -lc 'cd /tmp; kubeseal --version'",
            "cd x && kubeseal --version",
            "ssh vm <<'EOF'\nset -e\nkubeseal --fetch-cert > cert.pem\nEOF",
        ]:
            self.assertBlocked(command)

    def test_gcloud_secret_values(self):
        for command in [
            "gcloud secrets versions access latest --secret foo",
            "gcloud --project p secrets versions add foo --data-file=-",
            "mise exec -- gcloud secrets create foo --replication-policy automatic",
        ]:
            self.assertBlocked(command)

    def test_secret_manager_api(self):
        self.assertBlocked('curl -fsS -H "Authorization: Bearer $T" "https://secretmanager.googleapis.com/v1/projects/p/secrets/s/versions/1:access"')
        self.assertBlocked("python3 - <<'PY'\nfrom google.cloud import secretmanager\nc.access_secret_version(name=n)\nPY")

    def test_codex_list_command(self):
        out = run(None, raw=json.dumps({"tool_name": "shell", "tool_input": {"command": ["bash", "-lc", "kubeseal --version"]}, "cwd": "/"}))
        self.assertEqual(out["permissionDecision"], "deny")


class Allows(unittest.TestCase):
    def test_waxseal_and_reads(self):
        for command in [
            "waxseal --repo . --no-input --yes key add ns-app API_KEY --from-file -",
            "waxseal reseal default-app",
            "grep -rn kubeseal docs/",
            "git log --oneline -- '*sealed*.yaml'",
            "gcloud secrets list --project p",
            "gcloud secrets describe foo",
            "echo 'kubeseal is not used here'",
            "kubectl get sealedsecret -A",
            "git commit -m 'fix; kubeseal is gone, use waxseal'",
            "gh pr create --title 'no kubeseal' --body-file body.md",
        ]:
            self.assertIsNone(run(command), command)

    def test_unparseable_input_passes(self):
        self.assertIsNone(run(None, raw="not json"))
        self.assertIsNone(run(None, raw=json.dumps({"tool_name": "Write", "tool_input": {"file_path": "x"}})))

    def test_waxseal_source_repo_is_exempt(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "go.mod").write_text("module github.com/shermanhuman/waxseal\n\ngo 1.25\n")
            (pathlib.Path(d) / "internal").mkdir()
            self.assertIsNone(run("kubeseal --version", cwd=str(pathlib.Path(d) / "internal")))
            other = pathlib.Path(d) / "other"
            other.mkdir()
            (other / "go.mod").write_text("module example.com/other\n")
            self.assertIsNotNone(run("kubeseal --version", cwd=str(other)))


if __name__ == "__main__":
    unittest.main()
