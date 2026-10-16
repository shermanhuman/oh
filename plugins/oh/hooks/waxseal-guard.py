"""PreToolUse guard: sealed secrets go through the waxseal CLI only.

Refuses shell commands that seal with kubeseal or read or write Google Secret
Manager outside waxseal (gcloud secrets, the REST API, the client library).
Those side paths skip waxseal's metadata, and reading Secret Manager directly
puts plaintext in the session.

Reads the hook event on stdin (Claude Code and Codex use the same shape) and
prints a deny decision, or nothing to let the call through. Anything it can't
parse is let through: a broken guard must not stop every command.

Inside waxseal's own source repository the guard is off, because its tests
call kubeseal and Secret Manager on purpose.
"""
import json
import os
import pathlib
import re
import shlex
import sys

WAXSEAL_MODULE = "module github.com/shermanhuman/waxseal"

SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}

# Words that run the next word as the command.
PREFIXES = {"sudo", "exec", "command", "env", "time", "nice", "nohup", "xargs", "builtin"}

# Secret Manager reads and writes, wherever they appear in the command text
# (including scripts passed through a heredoc).
RAW_PATTERNS = [
    (re.compile(r"secretmanager\.googleapis\.com\S*:(access|addVersion)\b"), "calls the Secret Manager API directly"),
    (re.compile(r"\b(access_secret_version|add_secret_version)\b"), "uses the Secret Manager client library"),
]


def command_text(tool_input):
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, list):
        return shlex.join(str(part) for part in command)
    return command if isinstance(command, str) else ""


def commands(text):
    """Each simple command in the text as an argv list.

    Each line is tokenized the way a shell would, quotes and operators
    included, so quoted text such as a commit message is never read as a
    command. Lines shlex can't parse (an open quote spanning lines, a
    backtick) fall back to a plain split on separators.
    """
    found = []
    for line in text.splitlines():
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            lexer.commenters = ""
            current = []
            for token in lexer:
                if set(token) <= set("();<>|&"):
                    found.append(current)
                    current = []
                else:
                    current.append(token)
            found.append(current)
        except ValueError:
            for segment in re.split(r"[;&|()`]|\$\(", line):
                found.append(segment.split())
    return [argv for argv in found if argv]


def program(argv):
    """Strip env assignments, wrappers and `mise exec --`; return the real argv."""
    i = 0
    while i < len(argv):
        word = argv[i]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", word) or word in PREFIXES or word.startswith("-"):
            i += 1
        elif word == "mise" and i + 1 < len(argv) and argv[i + 1] in ("exec", "x"):
            rest = argv[i + 2:]
            i = i + 2 + (rest.index("--") + 1 if "--" in rest else 0)
        else:
            break
    return argv[i:]


def reason_for(text):
    for pattern, why in RAW_PATTERNS:
        if pattern.search(text):
            return why
    for argv in commands(text):
        argv = program(argv)
        if not argv:
            continue
        name = os.path.basename(argv[0])
        if name in SHELLS:
            for flag, script in zip(argv[1:], argv[2:]):
                if re.fullmatch(r"-[a-z]*c[a-z]*", flag):
                    nested = reason_for(script)
                    if nested:
                        return nested
                    break
            continue
        if name == "kubeseal":
            return "runs kubeseal"
        if name == "gcloud" and "secrets" in argv:
            rest = argv[argv.index("secrets") + 1:]
            if rest[:1] == ["create"] or rest[:2] in (["versions", "access"], ["versions", "add"]):
                return "reads or writes Secret Manager with gcloud"
    return None


def in_waxseal_source(cwd):
    try:
        path = pathlib.Path(cwd).resolve()
    except (OSError, RuntimeError, TypeError):
        return False
    for directory in (path, *path.parents):
        go_mod = directory / "go.mod"
        if go_mod.is_file():
            try:
                lines = go_mod.read_text(encoding="utf-8", errors="ignore").splitlines()
                return any(line.strip() == WAXSEAL_MODULE for line in lines)
            except OSError:
                return False
    return False


def main():
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return
    if not isinstance(event, dict):
        return
    why = reason_for(command_text(event.get("tool_input")))
    if not why or in_waxseal_source(event.get("cwd") or os.getcwd()):
        return
    message = (
        f"Blocked by oh: this command {why}. Sealed secrets go through the waxseal CLI only: "
        "`waxseal key add|set|edit`, `waxseal reseal`, `waxseal secret list|show|retire`, "
        "one visible command per call, values from --from-file, stdin or --generate. "
        "If waxseal can't do what you need, stop and ask the user; don't work around it. "
        "If gcloud needs a fresh login, ask the user to run `! gcloud auth login`."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        }
    }))


if __name__ == "__main__":
    main()
