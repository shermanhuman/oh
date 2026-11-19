import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

GUARD = pathlib.Path(__file__).resolve().parent.parent / "plugins/oh/hooks/agent-guard.py"
OUTSIDE = tempfile.mkdtemp(prefix="agent-guard-")

# Pattern kills and printing secret files.
DENIED = [
    "pkill -f 'mix test'",
    "pkill node",
    "killall -9 beam.smp",
    "sudo killall postgres",
    "kill $(pgrep -f 'serve.py 7879')",
    "kill `pgrep -f vite`",
    "pgrep -f 'mix test' | xargs kill",
    "pgrep node | xargs -r kill -9",
    "bash -c 'pkill -f vite'",
    "cd app && pkill -f phx.server",
    "cat .env",
    "cat ./config/.env.production",
    "head -5 mise.local.toml",
    "cat mise.local.toml | sed -E 's/(=\\s*\").*(\")/…/'",
    "tail ~/.netrc",
    "less ~/.kube/config",
    "cat ~/.ssh/id_ed25519",
    "base64 -w0 tls.key",
    "xxd private-key.pem",
    "awk -F= '{print $2}' .env",
    "grep API_KEY .env",
    "grep -i token mise.local.toml",
    "cat ~/.config/mapleset-forge/app.json",
    "sed -n 1,5p credentials.json",
    "cat < .env",
]

# Everyday commands near these.
ALLOWED = [
    "kill 12345",
    "kill -TERM 12345 12346",
    "pgrep -fa 'mix test'",
    "ps aux | grep beam",
    "grep -c ANTHROPIC_API_KEY mise.local.toml",
    "grep -l TOKEN .env",
    "grep -q DATABASE_URL .env && echo set",
    "grep -o '^[A-Za-z_]*' mise.local.toml",
    "grep -o '^[A-Z_]*' .env",
    "cat .env.example",
    "cat ~/.ssh/id_ed25519.pub",
    "ls -la ~/.config/mapleset-forge/",
    "chmod 600 .env",
    "waxseal key add ns-app API_KEY --from-file .env.key",
    "cat README.md",
    "head -20 mix.exs",
    "git diff -- .env.example",
    "echo 'never cat .env'",
    "git commit -m 'pkill is blocked now'",
    "grep -rn pkill docs/",
    "ssh vm 'cat /etc/app/.env'",
]


def run(command, cwd=OUTSIDE):
    event = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})
    result = subprocess.run([sys.executable, "-I", str(GUARD)], input=event, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else None


class Guard(unittest.TestCase):
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

    def test_off_inside_oh(self):
        self.assertIsNone(run("pkill -f x", cwd=str(GUARD.parent.parent.parent.parent)))

    def test_fails_open(self):
        result = subprocess.run([sys.executable, "-I", str(GUARD)], input="not json", capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "")
        self.assertIn("skipped", result.stderr)


if __name__ == "__main__":
    unittest.main()
