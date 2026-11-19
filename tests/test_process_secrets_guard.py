import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

GUARD = pathlib.Path(__file__).resolve().parent.parent / "plugins/oh/hooks/process-secrets-guard.py"
OUTSIDE = tempfile.mkdtemp(prefix="process-secrets-guard-")
INSIDE_OH = str(GUARD.parent.parent.parent.parent)

# Pattern kills, more than one target, lookups feeding kill, printing secret files.
DENIED = [
    "pkill -f 'mix test'",
    "pkill node",
    "pkill -x qbittorrent",
    "pkill -P 4242",
    "killall -9 beam.smp",
    "sudo killall postgres",
    "kill $(pgrep -f 'serve.py 7879')",
    "kill \"$(pgrep -f vite)\"",
    "kill `pgrep -f vite`",
    "pgrep -f 'mix test' | xargs kill",
    "pgrep node | xargs -r kill -9",
    "PID=$(pgrep -f vite); kill $PID",
    "pgrep -f vite | while read p; do kill $p; done",
    "kill 123 456",
    "kill -9 123 456",
    "kill -- -4242",
    "kill 0",
    "kill -TERM -1",
    "bash -c 'pkill -f vite'",
    "cd app && pkill -f phx.server",
    "cat .env",
    "cat ./config/.env.production",
    "head -5 mise.local.toml",
    "cat mise.local.toml | sed -E 's/(=\\s*\").*(\")/…/'",
    "tail ~/.netrc",
    "less ~/.kube/config",
    "cat ~/.ssh/id_ed25519",
    "cat ~/.ssh/deploy_hetzner",
    "base64 -w0 tls.key",
    "xxd private-key.pem",
    "awk -F= '{print $2}' .env",
    "grep API_KEY .env",
    "grep -i token mise.local.toml",
    "grep -o '[A-Za-z0-9_-]*' .env",
    "cat ~/.config/mapleset-forge/app.json",
    "grep -r KEY ~/.config/mapleset-forge/",
    "sed -n 1,5p credentials.json",
    "cat < .env",
    "sudo cat < .env",
    "X=1 cat < .env",
    "/bin/cat < .env",
    "cat .git-credentials",
    "cat ~/.pgpass",
    "cat .dev.vars",
    "head -c 8 ~/.app-key",
    "cat terraform.tfstate",
    "bash <<'EOF'\npkill -f vite\nEOF",
]

# Everyday commands near these.
ALLOWED = [
    "kill 12345",
    "kill -TERM 12345",
    "kill -s TERM 12345",
    "kill $!",
    "kill %1",
    "kill -0 12345",
    "kill -l",
    "kill 12345; sleep 1; pgrep -f serve.py || echo gone",
    "pgrep -fa 'mix test'",
    "ps aux | grep beam",
    "pkill --help",
    "grep -c ANTHROPIC_API_KEY mise.local.toml",
    "grep -l TOKEN .env",
    "grep -q DATABASE_URL .env && echo set",
    "grep -o '^[A-Za-z_]*' mise.local.toml",
    "grep -o '^[A-Z_]*' .env",
    "grep -oE '^[A-Z_]+' .env",
    "cut -d= -f1 .env",
    "sed -i 's/^PORT=.*/PORT=4001/' .env",
    "cat .env.example",
    "cat ~/.ssh/id_ed25519.pub",
    "cat ~/.ssh/config",
    "cat ~/.ssh/known_hosts",
    "cat cert.pem",
    "cat priv/cert/selfsigned_cert.pem",
    "cat keys/pub-cert.pem",
    "cat apps/app/sealed-secrets.yaml",
    "cat .waxseal/metadata/app-secrets.yaml",
    "ls -la ~/.config/mapleset-forge/",
    "chmod 600 .env",
    "waxseal key add ns-app API_KEY --from-file .env.key",
    "cat README.md",
    "head -20 mix.exs",
    "git diff -- .env.example",
    "echo 'never cat .env'",
    "git commit -m 'pkill is blocked now'",
    "grep -rn pkill docs/",
    "grep -rn credentials src/",
    "rg kubeconfig",
    "rg -n mise.local.toml .",
    "grep -r id_rsa .",
    "grep -rn '.env' docs/",
    "awk '/kubeconfig/' docs/setup.md",
    "sed -i 's/foo/.env/' README.md",
    "ssh vm 'cat /etc/app/.env'",
    "cat > docs/bash-tips.md <<'EOF'\npkill -f vite is refused; cat .env too\nEOF",
    "gh pr create --title 'fix sh quoting' --body-file - <<'EOF'\npkill -f vite\nEOF",
]


def run(command, cwd=OUTSIDE):
    event = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})
    result = subprocess.run([sys.executable, "-I", str(GUARD)], input=event, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"guard failed open on {command!r}: {result.stderr}")
    return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else None


class Guard(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(OUTSIDE, ignore_errors=True)

    def test_denied(self):
        for command in DENIED:
            with self.subTest(command=command):
                out = run(command)
                self.assertIsNotNone(out, command)
                self.assertEqual(out["permissionDecision"], "deny")

    def test_allowed(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                self.assertIsNone(run(command), command)

    def test_on_inside_oh(self):
        self.assertIsNotNone(run("pkill -f x", cwd=INSIDE_OH))

    def test_fails_open_visibly(self):
        result = subprocess.run([sys.executable, "-I", str(GUARD)], input="not json", capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("skipped", result.stderr)

    def test_long_commit_message_is_fast(self):
        import time
        start = time.monotonic()
        self.assertIsNone(run("git commit -m '" + "x < y and kill " * 8000 + "'"))
        self.assertLess(time.monotonic() - start, 3)


if __name__ == "__main__":
    unittest.main()
