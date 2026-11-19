"""PreToolUse guard: no killing by pattern, no printing secret files.

A backstop for two of oh's rules, looking only at what a shell would execute:

- **Kill only your own PIDs.** Several sessions share the machine, so a pattern
  kill stops other sessions' runs too. Refuses `pkill`, `killall`, and `kill`
  fed by `pgrep` (`kill $(pgrep -f x)`, `pgrep x | xargs kill`).
- **Never print a secret file.** A redaction filter can fail open and put the
  secret in the transcript. Refuses printing commands (cat, head, tail, less,
  sed, awk, base64, xxd, ...) on files that hold secrets: `.env*` (not
  `.env.example`), `.netrc`, `mise.local.toml`, credentials files, private
  keys (`*.pem`, `*.key`, `id_rsa`, ...), kubeconfigs, and anything under
  `~/.config/mapleset-forge/`. `grep` passes only when it can't print values
  (`-c`, `-l`, `-L`, `-q`, or `-o` with a pattern that stops at `=`).

Interpreter code isn't inspected. Reads the hook event on stdin and prints a
deny decision, or nothing. Fails open, with a note on stderr, on anything
unexpected. Off inside oh's own source tree, whose tests use these commands.
"""
import importlib.util
import json
import os
import pathlib
import re
import sys


def load(name):
    """A sibling module, loaded by path: `python3 -I` leaves this directory off sys.path."""
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(f"oh_{name}", pathlib.Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shell = load("shell")
DEPTH = 4
KILLERS = {"pkill", "killall"}
PRINTERS = {"cat", "head", "tail", "less", "more", "bat", "batcat", "nl", "tac", "strings", "xxd", "od",
            "hexdump", "base64", "sed", "awk", "gawk", "cut", "sort", "uniq", "column", "paste", "fold", "rev"}
GREP_SAFE = {"-c", "--count", "-l", "--files-with-matches", "-L", "--files-without-match", "-q", "--quiet", "--silent"}
SECRET_NAMES = re.compile(
    r"^(\.env(\..+)?|\.netrc|_netrc|mise\.local\.toml|\.mise\.local\.toml|credentials(\.json)?|"
    r"id_(rsa|dsa|ecdsa|ed25519)|kubeconfig.*|.*\.(pem|key|p12|pfx|jks|keystore)|.*secrets?\.(ya?ml|json|env|toml))$",
    re.I,
)
NOT_SECRET = re.compile(r"^\.env\.(example|sample|template|dist)$|.*\.pub$", re.I)
KILL = "kills processes by pattern, which also stops other sessions' runs; stop only a PID you started yourself"
PRINT = "prints a file that holds secrets; list key names instead (`grep -o '^[A-Za-z_]*' FILE`, `grep -c NAME FILE`)"


def secret_path(arg, cwd):
    if not arg or arg.startswith("-"):
        return False
    path = pathlib.Path(os.path.expanduser(arg))
    full = (pathlib.Path(cwd) / path) if not path.is_absolute() else path
    text = str(full)
    if "/.kube/config" in text or "/.config/mapleset-forge/" in text:
        return True
    name = path.name
    return bool(SECRET_NAMES.match(name)) and not NOT_SECRET.match(name)


def grep_prints(args):
    """True when grep could print matched text (values), not just counts or names."""
    if any(a in GREP_SAFE or (re.fullmatch(r"-[a-zA-Z]+", a) and set(a[1:]) & set("clLq")) for a in args):
        return False
    if any(a == "-o" or (re.fullmatch(r"-[a-zA-Z]+", a) and "o" in a[1:]) for a in args):
        patterns = [a for a in args if not a.startswith("-")][:1]
        return not patterns or "=" in patterns[0] or not re.search(r"\]\*|\[\^=\]", patterns[0])
    return True


def argv_reason(argv, cwd, depth, piped_pgrep):
    argv = shell.program(argv)
    if not argv:
        return None
    name, args = os.path.basename(argv[0]), argv[1:]
    if name in KILLERS:
        return KILL
    if name == "kill" and piped_pgrep:
        return KILL
    if name in shell.SHELLS:
        for i, flag in enumerate(args):
            if re.fullmatch(r"-[a-z]*c[a-z]*", flag) and i + 1 < len(args):
                return reason_for(args[i + 1], cwd, depth + 1)
        return None
    if name in ("eval", "watch"):
        return reason_for(" ".join(a for a in args if not a.startswith("-")), cwd, depth + 1)
    if name == "ssh":
        return None  # the remote machine's files aren't this one's
    files = [a for a in args if secret_path(a, cwd)]
    if not files:
        return None
    if name in PRINTERS:
        return PRINT
    if name in ("grep", "egrep", "rg") and grep_prints(args):
        return PRINT
    return None


def reason_for(text, cwd, depth=0):
    if not text or depth > DEPTH or len(text) > shell.MAX_TEXT:
        return None
    main, docs = shell.split_heredocs(text)
    for header, body in docs:
        if re.search(r"\b(bash|sh|zsh)\b", header.split("<<", 1)[0] + header.split("<<", 1)[-1]):
            why = reason_for(body, cwd, depth + 1)
            if why:
                return why
    commands, substs = shell.simple_commands(main)
    pgrep = any(shell.program(c) and os.path.basename(shell.program(c)[0]) == "pgrep" for c in commands) or any(
        re.search(r"(^|[\s;|&(])pgrep\b", s) for s in substs
    )
    for inner in substs:
        why = reason_for(inner, cwd, depth + 1)
        if why:
            return why
    for argv in commands:
        why = argv_reason(argv, cwd, depth, pgrep)
        if why:
            return why
    # `cat < .env`: a redirect into a printer.
    for match in re.finditer(r"(?:^|[\s;|&])(\w+)[^;|&\n]*?<\s*(\S+)", main):
        if match.group(1) in PRINTERS | {"grep"} and secret_path(match.group(2).strip("'\""), cwd):
            if match.group(1) != "grep":
                return PRINT
    return None


def exempt(cwd):
    """True inside oh's own source tree."""
    path = pathlib.Path(cwd).resolve()
    return any((d / "plugins/oh/hooks/agent-guard.py").is_file() for d in (path, *path.parents))


def decide(event):
    if not isinstance(event, dict):
        return None
    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    if exempt(cwd):
        return None
    why = reason_for(shell.command_text(event.get("tool_input")), cwd)
    return f"Blocked by oh: this command {why}." if why else None


def main():
    try:
        message = decide(json.load(sys.stdin))
    except Exception as error:  # fail open, but say so
        print(f"agent-guard: skipped ({type(error).__name__}: {error})", file=sys.stderr)
        return
    if message:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": message,
            }
        }))


if __name__ == "__main__":
    main()
