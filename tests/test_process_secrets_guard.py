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
    # kill forms (round 2): group targets after a signal, lookups per kill
    "kill -9 -4242",
    "kill -INT -$PGID",
    "kill -- -$PGID",
    "ps aux | grep vite | awk '{print $2}' | xargs kill",
    "for p in $(pgrep -f vite); do kill $p; done",
    "P=$(pidof vite) && kill -9 $P",
    "kill -9 $(lsof -t -i :4000)",
    "kill vite",
    "PIDS=$(pgrep -f vite); echo $PIDS | xargs kill",
    "P=$(pgrep vite); kill $(echo $P | head -1)",
    "A=$(pgrep vite); B=$(echo $A); kill $B",
    "pgrep vite |& xargs kill",
    "/usr/bin/pgrep vite | xargs kill",
    "cat ca-privkey.pem",
    "cat fullchain_privkey.pem",
    "P=\"$P $(pgrep -x gh)\"; for p in $P; do kill -STOP $p; done",
    # certificate-looking private keys (M8), options, $HOME, cut and -o (m16-m20)
    "cat ca.key",
    "cat /etc/kubernetes/pki/ca.key",
    "cat ca-key.pem",
    "cat cert-key.pem",
    "base64 -w0 cert.p12",
    "tail -f .env",
    "cat -e .env",
    "sed --expression=p .env",
    "grep --regexp=KEY .env",
    "cat $HOME/.config/mapleset-forge/app.json",
    "cat \"$HOME/.ssh/senga_ci\"",
    "cut -f1 .env",
    "cut -d' ' -f1 .env",
    "cut -d= -f1 ~/.app-key",
    "grep -o '^[^#]*' .env",
    "grep -o '^[A-Za-z0-9+/=_-]*' ~/.app-key",
    "grep -o '^[A-Za-z0-9_-]*' ~/.app-key",
    # listings that print value text: a multi-line key's base64 body (oh#38)
    "cut -d= -f1 .env",
    "cut -s -d= -f1 .env",
    "cut -d'=' -f1 mise.local.toml",
    "grep -o '^[^=]*' .env",
    "grep -o '^[A-Z_]*' .env",
    "grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env",
    "grep -oiE '^[A-Z_][A-Z0-9_]*=' .env",
    "grep -ovE '^[A-Z_][A-Z0-9_]*=' .env",
    "grep -oE -C20 '^[A-Z_][A-Z0-9_]*=' .env",
    "grep -o --context=20 '^[A-Z_][A-Z0-9_]*=' .env",
    "grep -o --passthru '^[A-Z_][A-Z0-9_]*=' .env",
    "grep -oE '^[A-Z_][A-Z0-9_]*=' -e '.*' .env",
    "rg -o -C2 '^[A-Z_][A-Z0-9_]*=' .env",
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
    "grep -oE '^[A-Z_][A-Z0-9_]*=' .env",
    "grep -o '^[A-Z][A-Z0-9_]*=' mise.local.toml",
    "grep -oE '^[A-Z_][A-Z0-9_]* *=' mise.local.toml",
    "grep -ohE '^[A-Z_][A-Z0-9_]*=' .env .dev.vars",
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
    # kill forms (round 2)
    "kill -9 4242",
    "kill -15 4242",
    "kill -1 4242",
    "kill -9 \"$PID\"",
    "kill -9 $!",
    "sudo kill -9 4242",
    "kill -KILL 4242",
    "kill -s 9 4242",
    "kill $(cat server.pid)",
    "PID=$(cat server.pid); kill $PID",
    "kill %vite",
    "while kill -0 $P 2>/dev/null; do r=$(ps -o rss= -p $P); sleep 1; done",
    "kill -0 $(pgrep -x deskflow) && echo up",
    "monpid=$!; before=$(pgrep -c -x testbed); kill $monpid",
    "for p in 2630845 2630846; do kill $p; done; sleep 1; pgrep -af bwlimit",
    "P=$(pgrep -x d); P=4242; kill $P",
    "kill 83095 2>/dev/null; sleep 1; ps -p 83095 >/dev/null && echo still",
    "( sleep 60; kill $pid 2>/dev/null ) & wd=$!",
    # names, options and listing (round 2)
    "cat priv/cert/selfsigned_cert.pem",
    "cat docs/CREDENTIALS.md",
    "sed -n 1,40p lib/app/credentials.ex",
    "grep -rn --include '*.ex' api_key lib/",
    "grep -rn --exclude-dir node_modules secret_key .",
    "rg -n --sort path credentials",
    "awk -v OFS=, '/api_key/' data.csv",
    "cat $HOME/.ssh/config",
    "kill -$SIG $PID",
    "for sig in TERM KILL; do kill -$sig $PID; done",
    "cat jwt_public_key.pem",
    "cat public.key",
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
