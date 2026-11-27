import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

GUARD = pathlib.Path(__file__).resolve().parent.parent / "plugins/oh/hooks/waxseal-guard.py"
OUTSIDE = tempfile.mkdtemp(prefix="guard-")

# What a shell would execute: kubeseal, gcloud secrets changes or reads, Secret Manager URLs.
DENIED = [
    "kubeseal --format yaml < secret.yaml > sealed.yaml",
    "kubectl create secret generic x --dry-run=client -o yaml | kubeseal --cert cert.pem",
    "FOO=1 sudo -E /usr/local/bin/kubeseal --version",
    "sudo -u deploy kubeseal --version",
    "timeout 30 kubeseal --fetch-cert",
    "nice -n 10 kubeseal --version",
    "mise exec -- kubeseal --fetch-cert",
    "echo start; $(kubeseal --version)",
    "cd x && kubeseal --version",
    "bash -c 'kubeseal --version'",
    "bash -lc 'cd /tmp; kubeseal --version'",
    "eval 'kubeseal --version'",
    "ssh vm 'kubeseal --fetch-cert > cert.pem'",
    "ssh vm <<'EOF'\nset -e\nkubeseal --fetch-cert > cert.pem\nEOF",
    "cat > seal.sh <<'EOF'\nset -e\nkubeseal --fetch-cert\nEOF",
    "kubectl exec -n kube-system deploy/sealed-secrets -- kubeseal --version",
    "kubectl exec -it pod -- sh -c 'kubeseal --version'",
    "docker run --rm -i ghcr.io/bitnami-labs/sealed-secrets/kubeseal:latest --cert cert.pem < s.yaml",
    "go run github.com/bitnami-labs/sealed-secrets/cmd/kubeseal@v0.27.1 --version",
    "gcloud secrets versions access latest --secret foo",
    "PASS=$(gcloud secrets versions access latest --secret foo)",
    "gcloud --project p secrets versions add foo --data-file=-",
    "gcloud --verbosity=debug secrets versions access latest --secret foo",
    "gcloud alpha secrets versions access latest --secret foo",
    "mise exec -- gcloud secrets create foo --replication-policy automatic",
    "gcloud secrets delete foo --quiet",
    "gcloud secrets update foo --update-labels=x=y",
    "gcloud secrets versions destroy 3 --secret foo",
    "gcloud secrets versions disable 3 --secret foo",
    "gcloud secrets add-iam-policy-binding foo --member=serviceAccount:x --role=roles/secretmanager.secretAccessor",
    "echo foo | xargs -I{} gcloud secrets versions access latest --secret {}",
    'curl -fsS -H "Authorization: Bearer $T" "https://secretmanager.googleapis.com/v1/projects/p/secrets/s/versions/1:access"',
    "curl -X POST https://secretmanager.googleapis.com/v1/projects/p/secrets/s/versions/1:destroy",
    "if kubeseal --fetch-cert; then echo ok; fi",
    "for s in a b; do gcloud secrets versions access latest --secret $s; done",
    "while true; do kubeseal --version; break; done",
    "cat <<'EOF' | bash\nkubeseal --fetch-cert\nEOF",
    "cat <<'EOF' | ssh vm bash\nkubeseal --fetch-cert\nEOF",
    "bash -o pipefail -c 'kubeseal --version | head -1'",
    "bash -euo pipefail -c 'kubeseal --version'",
    "caffeinate -t 600 kubeseal --version",
    "CERT=`kubeseal --fetch-cert`",
    "printf '%s\\n' '# status'; kubeseal --fetch-cert",
    "curl https://secretmanager.googleapis.com:443/v1/projects/p/secrets/s/versions/latest:access",
    "curl https://secretmanager.us-central1.rep.googleapis.com/v1/projects/p/locations/us-central1/secrets/s/versions/1:access",
    "echo \"v=`kubeseal --version`\"",
    "BASE=https://secretmanager.googleapis.com/v1; curl -H \"Authorization: Bearer $T\" \"$BASE/projects/p/secrets/s/versions/latest:access\"",
]

# Ways past the guard that bash really runs (oh#59 and its comments, plus the
# same classes found while fixing them): (label, command, whether the bash
# oracle below can run it). `{BIN}` is the directory holding gcloud.
# A refused verb the backstop (NAMED_DENIED) doesn't name, so these test the reading itself.
ACCESS = "secrets versions destroy 3 --secret=x"
HOLES = [
    ("1 pipe+redirect <", f"true |</dev/null gcloud {ACCESS}", True),
    ("1 amp+redirect <", f"true &</dev/null gcloud {ACCESS}", True),
    ("1 pipe+redirect >", f"true |>/dev/null gcloud {ACCESS}", True),
    ("2 quoted <<", f": '<<EOF'\ngcloud {ACCESS}", True),
    ("2 arithmetic <<", f"echo $((1<<n))\ngcloud {ACCESS}", True),
    ("3 ansi-c quote", f": $'\\''; gcloud {ACCESS}; : $'\\''", True),
    ("4 --no-log-http", f"gcloud --no-log-http {ACCESS}", True),
    ("4 --no-quiet", f"gcloud --no-quiet {ACCESS}", True),
    ("5 variable program", f"g=gcloud; $g {ACCESS}", True),
    ("6 CR comment", f"true\r#; gcloud {ACCESS}", True),
    ("7 dq backslash-newline", f"bash -c \"true\\\n#; gcloud {ACCESS}\"", True),
    ("8 over MAX_TEXT", f"gcloud {ACCESS}; : " + "a" * 256_001, True),
    ("d8 here-string <<<", f"cat <<<EOF\ngcloud {ACCESS}\nEOF", True),
    ("d8 delimiter EOF\"X\"", f"cat <<EOF\"X\"\nbody\nEOFX\ngcloud {ACCESS}\nEOF", True),
    ("d8 brace program", f"{{gcloud,}} {ACCESS}", True),
    ("d8 function \"$@\"", f"g() {{ gcloud \"$@\"; }}; g {ACCESS}", True),
    ("d8 alias", f"shopt -s expand_aliases\nalias g=gcloud\ng {ACCESS}", True),
    ("d8 hash -p", f"hash -p {{BIN}}/gcloud g; g {ACCESS}", True),
    ("d8 env -S", f"env -S 'gcloud {ACCESS}'", True),
    ("d8 flock -c", f"flock /tmp/guard-holes.lock -c 'gcloud {ACCESS}'", True),
    ("d8 script -c", f"script -qc 'gcloud {ACCESS}' /dev/null", True),
    ("d8 su -c", f"su -c 'gcloud {ACCESS}' deploy", False),
    ("d8 runuser -c", f"runuser -u deploy -- sh -c 'gcloud {ACCESS}'", False),
    ("d8 pipe into bash", f"echo 'gcloud {ACCESS}' | bash", True),
    ("d8 bash -s here-string", f"bash -s <<< 'gcloud {ACCESS}'", True),
    ("d8 xargs bare gcloud", f"echo '{ACCESS}' | xargs gcloud", True),
    ("d8 find -exec", f"find . -maxdepth 0 -exec gcloud {ACCESS} \;", True),
    ("d8 bash -c -o", f"bash -c -o pipefail 'gcloud {ACCESS}'", True),
    ("d8 subst program", f"$(echo gcloud) {ACCESS}", True),
    ("d8 backtick program", f"`echo gcloud` {ACCESS}", True),
    ("d8 dq substitution", f"echo \"$(gcloud {ACCESS})\"", True),
    ("d8 variable group word", "s=secrets; gcloud $s versions destroy 3 --secret=x", True),
    ("fd-number redirect", f"2>/dev/null gcloud {ACCESS}", True),
    ("{fd} redirect", f"{{fd}}>/dev/null gcloud {ACCESS}", True),
    ("fd-number before a variable program", f"g=gcloud; 2>/dev/null $g {ACCESS}", True),
    ("quotes split the word", "g=gcloud; $g secret\"s\" versions destroy 3 --secret=x", True),
    ("unquoted heredoc body runs substitutions", f"cat <<EOF > notes.md\n$(gcloud {ACCESS})\nEOF", True),
    ("delimiter E\"OF\"", f"cat <<E\"OF\"\nb\nEOF\ngcloud {ACCESS}\nE", True),
    ("delimiter E\\OF", f"cat <<E\\OF\nb\nEOF\ngcloud {ACCESS}\nE", True),
    ("backslash-newline inside double quotes", f"\"gcl\\\noud\" {ACCESS}", True),
    ("ansi-c decoded program", f"$'\\x67cloud' {ACCESS}", True),
    ("heredoc ended by EOF)", f"x=$(cat <<EOF\nhi\nEOF)\ngcloud {ACCESS}\nEOF", True),
    ("bash --rcfile", f"bash --rcfile /dev/null -c 'gcloud {ACCESS}'", True),
    ("unknown switch before the group", f"gcloud --foo {ACCESS}", True),
    ("pipe+redirect before a variable program", f"g=gcloud; true |</dev/null $g {ACCESS}", True),
    ("case branch", f"case x in a|x) gcloud {ACCESS};; esac", True),
    ("/usr/bin/env -S", f"/usr/bin/env -S 'gcloud {ACCESS}'", True),
    ("bash a process substitution", f"bash <(echo 'gcloud {ACCESS}')", True),
    ("source a process substitution", f"source <(echo 'gcloud {ACCESS}')", True),
    ("bash run on gcloud's own path", f"bash {{BIN}}/gcloud {ACCESS}", True),
    ("parameter default spells the group", "gcloud ${x:-secrets} versions destroy 3 --secret=x", True),
    ("xargs replace string", "xargs -I{} gcloud {} versions destroy 3 --secret=x <<< secrets", True),
    ("xargs -I% from a pipe", "echo secrets | xargs -I% gcloud % versions destroy 3 --secret=x", True),
    ("find start path as the group", "mkdir -p secrets; find secrets -maxdepth 0 -exec gcloud {} versions destroy 3 --secret=x \\;", True),
    ("parallel placeholder", "parallel gcloud {} versions destroy 3 --secret=x ::: secrets", False),
    ("\\U out of range, then $'' in the group", ": $'\\UFFFFFFFF'; gcloud sec$'r'ets versions destroy 3 --secret=x", True),
    ("case inside $(…), then $'' in the group", "x=$(case a in a) echo;; esac); g=gcloud; $g sec$'r'ets versions destroy 3 --secret=x", True),
    ("{ inside ${…}", ": ${x/{/}; g=gcloud; $g sec$'r'ets versions destroy 3 --secret=x", True),
    ("\\U escape spells the group", "g=gcloud; $g $'\\U00000073'ecrets versions destroy 3 --secret=x", True),
    ("source /dev/stdin", f"source /dev/stdin <<< 'gcloud {ACCESS}'", True),
    ("group word from a file", "gcloud $(cat args.txt)", False),
    ("group word from stdin via xargs", "xargs -a args.txt gcloud", False),
    ("group word from a parameter operator", "a=destroy; x=/secrets; gcloud ${x#/} versions $a 3 --secret=x", True),
    ("lines piped into parallel", f"echo 'gcloud {ACCESS}' | parallel", False),
    ("trap string", "s=secrets; trap \"gcloud $s versions destroy 3 --secret=x\" EXIT", True),
]

# Refused only because they mention Secret Manager in text the guard can't read for certain.
UNSURE_DENIED = [
    "echo \"unclosed; gcloud secrets list",
    "$CMD --version; gcloud secrets list",
    "bash <<< 'gcloud secrets list'",
    "cat <<EOF\ngcloud secrets list",
]

# Refused because the text names a value read or write, heredoc bodies included, however the
# rest reads (board item 383): prose that quotes the command goes through a file and --body-file.
NAMED_DENIED = [
    "cat > docs/secrets.md <<'EOF'\n# Don't\n\ngcloud secrets versions access latest --secret foo\nEOF",
    "git commit -m \"$(cat <<'EOF'\nguard: gcloud secrets versions access is refused\nEOF\n)\"",
    "gh pr create --title \"secrets guard fixes\" --body \"$(cat <<'EOF'\n## gcloud secrets versions access\nnow refused (it's a hole)\nEOF\n)\"",
    "setsid bash <<'EOF'\ngcloud secrets versions access latest --secret=x\nEOF",
    "cat > run <<'EOF'\ngcloud secrets versions access latest --secret=x\nEOF\nbash run",
    "python3 - <<EOF\nimport subprocess; subprocess.run(['gcloud', 'secrets', 'versions', 'access', 'latest'])\nEOF",
    "rg 'secretmanager.googleapis.com/v1/projects/p/secrets/s/versions/1:access' docs/",
    "python3 -c \"import subprocess; subprocess.run(['gcloud','secrets','versions','access','latest'])\"",
    "trap 'gcloud secrets versions access latest --secret=x' EXIT",
    "mapfile -C 'gcloud secrets versions access latest --secret=x #' -c 1 < /etc/hostname",
    "gh pr comment 5 --body 'refuses gcloud secrets versions access now'",
    "H=secret; curl https://${H}manager.googleapis.com/v1/projects/p/secrets/s/versions/1:access",
]

# Everyday commands that only mention these tools, or read metadata.
ALLOWED = [
    "waxseal --repo . --no-input --yes key add ns-app API_KEY --from-file -",
    "waxseal reseal default-app",
    "waxseal --no-input key add sc-ghcr .dockerconfigjson --namespace sc --from-key default-ghcr/.dockerconfigjson",
    "waxseal --no-input key set sc-ghcr .dockerconfigjson --from-key default-ghcr/.dockerconfigjson",
    "waxseal check metadata && waxseal check gsm",
    "openssl rand -base64 32 | waxseal key set default-app key --from-file -",
    "command -v kubeseal",
    "which kubeseal",
    "mise which kubeseal",
    "brew info kubeseal",
    "kubectl get sealedsecret -A",
    "kubectl -n kubeseal get pods",
    "kubectl -n kube-system logs deploy/sealed-secrets | grep -i kubeseal",
    "gcloud secrets list --project p --format json",
    "gcloud secrets describe foo",
    "gcloud secrets versions list foo",
    "gcloud secrets get-iam-policy foo",
    "gcloud auth login",
    "gcloud auth application-default login",
    "cat <<'EOF' | grep -c kubeseal\nkubeseal --fetch-cert\nEOF",
    "ssh vm uptime; cat <<'EOF' > runbook.md\nkubeseal --fetch-cert\nEOF",
    "bash -c 'echo hi' && cat <<'EOF' > notes.md\nkubeseal --fetch-cert\nEOF",
    "gcloud secrets --project my-project list",
    "gcloud --project p secrets versions list foo --limit 5",
    "gcloud compute instances describe secrets --zone z",
    "printf '%s\\n' '' kubeseal",
    "grep '|' kubeseal",
    "echo 'a; kubeseal --version'",
    "echo \"x && kubeseal\"",
    "gcloud compute ssh vm --zone z --command 'uptime'",
    "curl -s 'https://secretmanager.googleapis.com/$discovery/rest?version=v1' | jq .revision",
    "DOCS=https://secretmanager.googleapis.com/; curl -s https://example.com/health",
    "grep -rn kubeseal docs/",
    "grep -rn access_secret_version plugins/ tests/",
    "git log --all --oneline --grep=kubeseal",
    "sed -i '' 's/kubeseal/waxseal/g' README.md",
    "echo 'kubeseal is not used here'",
    "echo \"it's fine; kubeseal is only mentioned",
    "git commit -m 'fix; kubeseal is gone, use waxseal'",
    "git commit -m 'docs: drop the `kubeseal` recipe'",
    "git commit -m 'guard: deny access_secret_version too'",
    "git commit -m \"$(cat <<'EOF'\nchore: drop kubeseal\n\nkubeseal is no longer installed.\nEOF\n)\"",
    "gh pr create --title x --body \"$(cat <<'EOF'\n## Changes\n- kubeseal removed\nEOF\n)\"",
    "gh pr comment 15 --body 'Fixed: `kubeseal` wrappers are denied now'",
    "gh pr create --title 'no kubeseal' --body-file body.md",
    "bash <<'EOF'\n# old: kubectl ... | kubeseal > x\necho ok\nEOF",
    "ssh root@vm 'bash -s prep' < local-e2e/kata-rehearsal/18-components.sh",
    "scp local-e2e/kata-rehearsal/18-components.sh root@vm:/root/",
    "MIX_ENV=test mix test test/foo_test.exs:12",
    "go test ./... -run TestSeal -count=1",
    "python3 -m pytest tests/ -k secret",
    "node -e 'console.log(1 << 3)'",
    "kubectl get secrets -n $ns",
    "$EDITOR secrets.yaml",
    "cat .claude/rules/secrets.md",
    "gcloud secrets --format json versions list foo",
    "gcloud --no-user-output-enabled secrets versions describe 3 --secret=foo --format='value(state)'",
    "bash <<'EOF'\ngcloud secrets list\nEOF",
    "gcloud secrets list && cat <<'EOF' | bash\necho ok\nEOF",
    "echo $((1<<3)); gcloud secrets list",
    "echo \"it's fine; gcloud is only mentioned",
    "find . -name '*.yaml' -exec grep -l secrets {} +",
    "which gcloud && gcloud secrets list",
    "S=~/.local/share/sugarhouse/bin/sugar; $S decide --question \"may agents run gcloud secrets versions list?\" --verdict accepted",
    "H=~/.local/bin/hc; $H send t2d \"the secrets guard PR is ready\"",
    "git commit -m \"$(cat <<'EOF'\nguard: it's fine :) and (secrets) stay put\nEOF\n)\"",
    "cat <<EOF > notes.md\nsecrets are listed with $(date)\nEOF",
    "echo $'it\\'s' && gcloud secrets list",
    "true |& tee log; gcloud secrets list",
    "echo ok 2>&1 | grep -c secrets",
    "gcloud secrets versions --no-quiet list foo",
    "declare -A ROW; ROW[secrets]=\"listed\"; [ -z \"$x\" ] && echo secrets",
    "kubectl get secret default-twenty-secrets -o name; D=~/x/secrets; ls $D",
    "cat > check.sh <<'EOF'\n# never prints secrets\n$CHECK --all\nEOF",
    "case $n in breakdown-*) echo web;; *) echo other;; esac; gcloud secrets list",
    "git commit -m \"$(cat <<'EOF'\nguard: refuse Secret Manager value reads (secrets stay in GSM)\nEOF\n)\"",
    "gh pr create --title \"secrets guard fixes\" --body \"$(cat <<'EOF'\n## gcloud secrets list still works\nit's fine :)\nEOF\n)\"",
    "gh pr comment 61 --body-file notes.md",
    "gcloud --version",
    "gcloud compute instances list --format json",
    "echo hi > out.txt; cat out.txt; gcloud secrets list",
    'grep -n -e "#171" -e "gcloud" $S/pr193-body.md | head -30',
]

# Outside the guard's scope by design (the rule still forbids them): interpreter code.
NOT_COVERED = [
    "python3 - <<'PY'\nfrom google.cloud import secretmanager\nc.access_secret_version(name=n)\nPY",
    "node - <<'EOF'\nconst [v] = await client.accessSecretVersion({name});\nEOF",
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
                reason = out["permissionDecisionReason"]
                self.assertIn("External Secrets Operator", reason)
                self.assertIn("`.claude/rules/secrets.md`", reason)
                self.assertNotIn("waxseal CLI", reason)

    def test_holes_denied(self):
        for label, command, _ in HOLES:
            with self.subTest(label):
                out = run(command.replace("{BIN}", "/usr/lib/google-cloud-sdk/bin"))
                self.assertIsNotNone(out)
                self.assertEqual(out["permissionDecision"], "deny")

    def test_named_denied(self):
        for command in NAMED_DENIED:
            with self.subTest(command=command):
                out = run(command)
                self.assertIsNotNone(out)
                self.assertIn("names a Secret Manager value read or write", out["permissionDecisionReason"])
                self.assertIn("quoted heredoc", out["permissionDecisionReason"])

    def test_unsure_denied(self):
        for command in UNSURE_DENIED:
            with self.subTest(command=command):
                out = run(command)
                self.assertIsNotNone(out)
                self.assertIn("can't read for certain", out["permissionDecisionReason"])
                self.assertIn("write it more plainly", out["permissionDecisionReason"])

    @unittest.skipUnless(shutil.which("bash"), "needs bash")
    def test_holes_are_real(self):
        """Each hole, run in bash with a stand-in gcloud, really reaches a refused `gcloud secrets` verb."""
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            stubs, log, work = root / "bin", root / "log", root / "work"
            stubs.mkdir()
            work.mkdir()
            gcloud = stubs / "gcloud"
            gcloud.write_text(f'#!/bin/sh\necho "$*" >> {log}\n')
            gcloud.chmod(0o755)
            for label, command, oracle in HOLES:
                if not oracle:
                    continue
                with self.subTest(label):
                    log.write_text("")
                    script = root / "command.sh"
                    script.write_text(command.replace("{BIN}", str(stubs)))
                    subprocess.run(
                        ["env", "-i", f"PATH={stubs}:/usr/bin:/bin", "bash", str(script)],
                        cwd=work, capture_output=True, stdin=subprocess.DEVNULL, timeout=20,
                    )
                    self.assertRegex(log.read_text(), r"(?m)^(--\S+ )*secrets versions destroy")

    def test_allowed(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                self.assertIsNone(run(command))

    def test_scope_stays_narrow(self):
        for command in NOT_COVERED:
            with self.subTest(command=command):
                self.assertIsNone(run(command))

    def test_codex_list_command(self):
        event = {"tool_name": "Bash", "tool_input": {"command": ["bash", "-lc", "kubeseal --version"]}, "cwd": OUTSIDE}
        self.assertEqual(run(None, raw=json.dumps(event))["permissionDecision"], "deny")

    def test_shell_scripts_are_read_before_they_run(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "seal.sh").write_text("#!/bin/sh\nkubeseal --format yaml < s.yaml\n")
            (root / "seal").write_text("#!/usr/bin/env bash\nset -e\nkubeseal --fetch-cert\n")
            (root / "ok.sh").write_text("#!/bin/sh\nwaxseal reseal default-app\n")
            (root / "comment.sh").write_text("#!/bin/sh\n# usage: kubectl create secret x -o yaml | kubeseal > s.yaml\n#   1) kubeseal --fetch-cert\necho ok\n")
            (root / "read.py").write_text("c.access_secret_version(name=n)\n")
            for command in ["bash seal.sh", "sh ./seal.sh", "./seal.sh", "./seal"]:
                with self.subTest(command=command):
                    self.assertIsNotNone(run(command, cwd=d))
            (root / "plain").write_text("gcloud secrets versions destroy 3 --secret=x\n")
            for command in ["bash plain", "source plain", ". ./plain", "sh -e plain"]:
                with self.subTest(command=command):
                    self.assertIsNotNone(run(command, cwd=d))
            # Files a shell reads as commands are read too, and one this command writes first is unsure.
            (root / "args.sh").write_text("gcloud secrets versions destroy 3 --secret=x\n")
            (root / "noshebang").write_text("gcloud secrets versions destroy 3 --secret=x\n")
            (root / "noshebang").chmod(0o755)
            (root / "ok.sh").write_text("echo ok\n")
            for command in ["bash < args.sh", "cat args.sh | bash", "./noshebang", 'bash -c "$(< args.sh)"', 'eval "$(cat args.sh)"',
                            "printf '%s\\n' 'gcloud secrets versions destroy 3 --secret=x' > ok.sh; bash ok.sh"]:
                with self.subTest(command=command):
                    self.assertIsNotNone(run(command, cwd=d))
            self.assertIsNone(run("bash ok.sh", cwd=d))
            # A script that can't be read, in a command that mentions Secret Manager, is refused.
            self.assertIsNotNone(run("bash missing.sh; gcloud secrets list", cwd=d))
            self.assertIsNone(run("bash missing.sh", cwd=d))
            for command in ["bash ok.sh", "bash comment.sh", "python3 read.py", "cat seal.sh"]:
                with self.subTest(command=command):
                    self.assertIsNone(run(command, cwd=d))

    def test_fast_on_large_input(self):
        commands = [
            "cat > notes.md <<'EOF'\n" + "- kubeseal removed; see `gcloud secrets` ban\n" * 5000 + "EOF\n",
            "python3 -c \"s = 'gcloud " + "-" * 40 + "'\"",
            "echo " + "word " * 40000 + "\"unterminated",
        ]
        for command in commands:
            start = time.monotonic()
            self.assertIsNone(run(command))
            self.assertLess(time.monotonic() - start, 5)

    def test_fast_on_hostile_input(self):
        """Slow paths must finish well inside the hook's 10 s, or refuse: a killed guard lets the command run."""
        commands = [
            "gcloud " + " ".join(f"--f{i} v{i}" for i in range(40)) + " secrets versions destroy 3 --secret x",
            "\n".join(f"cat <<'EOF{i}'\nbody\nEOF{i}" for i in range(5000)) + "\ngcloud secrets versions destroy 3 --secret=x",
            "echo " + '"$(echo ' * 2000 + "x" + ')"' * 2000 + "; gcloud secrets list",
            "x='\n" + "<<\n" * 60000 + "'\ng=gcloud; $g sec$'r'ets versions destroy 3 --secret=x",
        ]
        for command in commands:
            with self.subTest(command=command[:40]):
                start = time.monotonic()
                out = run(command)
                self.assertLess(time.monotonic() - start, 4)
                self.assertIsNotNone(out)

    def test_bad_input_passes(self):
        self.assertIsNone(run(None, raw="not json"))
        for event in [
            {"tool_name": "Write", "tool_input": {"file_path": "x"}},
            {"tool_name": "Bash", "tool_input": {"command": "kubeseal"}, "cwd": 123},
            {"tool_name": "Bash", "tool_input": ["kubeseal"], "cwd": OUTSIDE},
            {"tool_name": "Bash", "tool_input": {"command": {"a": 1}}, "cwd": OUTSIDE},
        ]:
            with self.subTest(event=event):
                result = subprocess.run([sys.executable, "-I", str(GUARD)], input=json.dumps(event), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0)

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
            # Anyone can make such a tree, so a plain Secret Manager command is still refused there.
            self.assertIsNotNone(run("gcloud secrets versions destroy 3 --secret x", cwd=d))
            self.assertIsNotNone(run("curl https://secretmanager.googleapis.com/v1/projects/p/secrets/s/versions/1:access", cwd=d))
            # Only kubeseal is exempt there (board item 383).
            self.assertIsNotNone(run("grep -rn 'gcloud secrets versions access' tests/", cwd=d))
            self.assertIsNotNone(run("g=gcloud; $g secrets versions destroy 3 --secret=x", cwd=d))


if __name__ == "__main__":
    unittest.main()
