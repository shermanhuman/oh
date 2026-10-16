import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

GUARD = pathlib.Path(__file__).resolve().parent.parent / "plugins/oh/hooks/waxseal-guard.py"
OUTSIDE = tempfile.mkdtemp(prefix="guard-")

# Commands that would seal or touch Secret Manager outside waxseal.
DENIED = [
    'gcloud secrets delete default-twenty-secrets-username --quiet',
    'gcloud secrets versions destroy 3 --secret default-twenty-secrets-password',
    'gcloud secrets versions disable 3 --secret foo',
    'gcloud secrets update foo --update-labels=x=y',
    'timeout 30 kubeseal --fetch-cert',
    'sudo -u deploy kubeseal --version',
    'nice -n 10 kubeseal --version',
    "ssh vm 'kubeseal --fetch-cert > cert.pem'",
    'kubectl exec -n kube-system deploy/sealed-secrets -- kubeseal --version',
    'docker run --rm -i ghcr.io/bitnami-labs/sealed-secrets/kubeseal:latest --cert cert.pem < s.yaml',
    'go run github.com/bitnami-labs/sealed-secrets/cmd/kubeseal@v0.27.1 --version',
    "eval 'kubeseal --version'",
    'curl -X POST -H "Authorization: Bearer $T" \'https://secretmanager.googleapis.com/v1/projects/p/secrets?secretId=foo\' -d \'{"replication":{"automatic":{}}}\'',
    'curl -X POST -H "Authorization: Bearer $T" https://secretmanager.googleapis.com/v1/projects/p/secrets/s/versions/1:destroy',
    'BASE=https://secretmanager.googleapis.com/v1; curl -H "Authorization: Bearer $T" "$BASE/projects/p/secrets/s/versions/latest:access"',
    "node - <<'EOF'\nconst [v] = await client.accessSecretVersion({name});\nEOF",
    'python3 -c "import subprocess; print(subprocess.check_output([\'gcloud\',\'secrets\',\'versions\',\'access\',\'latest\',\'--secret\',\'foo\']))"',
    'echo foo | xargs -I{} gcloud secrets versions access latest --secret {}',
    'kubeseal --format yaml < secret.yaml > sealed.yaml',
    'kubectl create secret generic x --dry-run=client -o yaml | kubeseal --cert cert.pem',
    'FOO=1 sudo -E /usr/local/bin/kubeseal --version',
    'mise exec -- kubeseal --fetch-cert',
    'echo start; $(kubeseal --version)',
    'echo "v=$(kubeseal --version)"',
    "bash -c 'kubeseal --version'",
    "bash -lc 'cd /tmp; kubeseal --version'",
    'cd x && kubeseal --version',
    "ssh vm <<'EOF'\nset -e\nkubeseal --fetch-cert > cert.pem\nEOF",
    'gcloud secrets versions access latest --secret foo',
    'gcloud --project p secrets versions add foo --data-file=-',
    'mise exec -- gcloud secrets create foo --replication-policy automatic',
    'curl -fsS -H "Authorization: Bearer $T" "https://secretmanager.googleapis.com/v1/projects/p/secrets/s/versions/1:access"',
    "python3 - <<'PY'\nfrom google.cloud import secretmanager\nc.access_secret_version(name=n)\nPY",
    "cat > seal.sh <<'EOF'\nset -e\ncurl -s https://secretmanager.googleapis.com/v1/x:access\nEOF",
    "cat > /tmp/m.go <<'EOF'\nresp, err := client.AccessSecretVersion(ctx, req)\nEOF",
]

# Everyday commands that only mention these tools, or read metadata.
ALLOWED = [
    'command -v kubeseal',
    'which kubeseal',
    'git commit -m "$(cat <<\'EOF\'\nchore: drop kubeseal\n\nkubeseal is no longer installed on the runner.\nEOF\n)"',
    'gh pr create --title x --body "$(cat <<\'EOF\'\n## Changes\n- kubeseal removed from the rehearsal script\nEOF\n)"',
    "git commit -m 'guard: deny access_secret_version too'",
    'grep -rn access_secret_version plugins/ tests/',
    "rg 'secretmanager.googleapis.com/v1/projects/p/secrets/s/versions/1:access' docs/",
    "cat > docs/secrets.md <<'EOF'\n# Don't\n\ngcloud secrets versions access latest --secret foo\nEOF",
    "cat > .claude/rules/sealed-secrets.md <<'EOF'\n- Never wrap waxseal in a generated script, seal with `kubeseal`, or read GSM another way.\nEOF",
    'echo \'{"tool_name":"Bash","tool_input":{"command":"kubeseal --version"},"cwd":"/tmp"}\' | python3 -I plugins/oh/hooks/waxseal-guard.py',
    'echo \'{"tool_input":{"command":"curl https://secretmanager.googleapis.com/v1/p:access"}}\' | python3 -I plugins/oh/hooks/waxseal-guard.py',
    'mise exec -- gh pr comment 15 -R shermanhuman/oh --body-file /tmp/r.md',
    'mise exec -- kubectl get sealedsecret -n default default-twenty-secrets -o yaml',
    'gcloud secrets list --project waxseal-infra-secrets --format json',
    'gcloud secrets versions list default-twenty-secrets-password',
    'gcloud secrets get-iam-policy foo',
    'gcloud auth login',
    "printf 'twenty' | waxseal --no-input --yes key add default-twenty-secrets username --from-file - --rotation static",
    'waxseal check metadata && waxseal check gsm',
    'waxseal --dry-run key add default-twenty-secrets username --from-file - --rotation static --no-input',
    'openssl rand -base64 32 | waxseal key set default-breakdown-admin-secrets sites_service_key --from-file -',
    'cd /Users/s/github/_release/oh-waxseal && python3 -m unittest discover -s tests -v',
    'git log --all --oneline --grep=kubeseal',
    "sed -i '' 's/kubeseal/waxseal/g' README.md",
    'mise which kubeseal',
    'brew info kubeseal',
    'cat local-e2e/kata-rehearsal/18-components.sh',
    'bash local-e2e/kata-rehearsal/18-components.sh',
    'terraform plan',
    'echo "it\'s fine; kubeseal is only mentioned',
    "python3 - <<'PY'\n# we never call access_secret_version here\nprint(1)\nPY",
    'echo done',
    'waxseal reseal default-app',
    'kubectl get sealedsecret -A',
    "git commit -m 'fix; kubeseal is gone, use waxseal'",
    "gh pr create --title 'no kubeseal' --body-file body.md",
    'gcloud secrets describe foo',
]


def run(command, cwd=OUTSIDE, raw=None):
    event = raw if raw is not None else json.dumps({
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd,
    })
    result = subprocess.run([sys.executable, "-I", str(GUARD)], input=event, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else None


class Guard(unittest.TestCase):
    def test_denied(self):
        for command in DENIED:
            with self.subTest(command=command):
                out = run(command)
                self.assertIsNotNone(out)
                self.assertEqual(out["permissionDecision"], "deny")
                self.assertIn("waxseal", out["permissionDecisionReason"])

    def test_allowed(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                self.assertIsNone(run(command))

    def test_codex_list_command(self):
        event = {"tool_name": "Bash", "tool_input": {"command": ["bash", "-lc", "kubeseal --version"]}, "cwd": OUTSIDE}
        self.assertEqual(run(None, raw=json.dumps(event))["permissionDecision"], "deny")

    def test_script_files_are_read_before_they_run(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "read.py").write_text("from google.cloud import secretmanager\nc.access_secret_version(name=n)\n")
            (root / "m.go").write_text("resp, err := client.AccessSecretVersion(ctx, req)\n")
            (root / "seal.sh").write_text("#!/bin/sh\nkubeseal --format yaml < s.yaml\n")
            (root / "ok.sh").write_text("#!/bin/sh\nwaxseal reseal default-app\n")
            for command in ["python3 read.py", "go run m.go", "bash seal.sh", "sh ./seal.sh"]:
                with self.subTest(command=command):
                    self.assertIsNotNone(run(command, cwd=d))
            self.assertIsNone(run("bash ok.sh", cwd=d))

    def test_unparseable_input_passes(self):
        self.assertIsNone(run(None, raw="not json"))
        self.assertIsNone(run(None, raw=json.dumps({"tool_name": "Write", "tool_input": {"file_path": "x"}})))

    def test_source_trees_are_exempt(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "go.mod").write_text("module github.com/shermanhuman/waxseal\n\ngo 1.25\n")
            (root / "internal").mkdir()
            self.assertIsNone(run("kubeseal --version", cwd=str(root / "internal")))
            other = root / "other"
            other.mkdir()
            (other / "go.mod").write_text("module example.com/other\n")
            self.assertIsNotNone(run("kubeseal --version", cwd=str(other)))
        with tempfile.TemporaryDirectory() as d:
            hooks = pathlib.Path(d) / "plugins/oh/hooks"
            hooks.mkdir(parents=True)
            (hooks / "waxseal-guard.py").write_text("")
            self.assertIsNone(run("kubeseal --version", cwd=d))


if __name__ == "__main__":
    unittest.main()
