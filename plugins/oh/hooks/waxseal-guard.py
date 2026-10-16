"""PreToolUse guard: sealed secrets go through the waxseal CLI only.

A backstop for oh's always-on rule, deliberately narrow: it looks only at what
a shell would execute, never at code or prose. It refuses:

- `kubeseal`, run directly or through a wrapper (sudo, timeout, nice, env,
  xargs, mise exec, ...), inside `bash -c`/`ssh`/`eval`/`watch` strings, a
  heredoc fed to a shell, a shell script about to run, or named as the program
  in `kubectl exec`/`docker run`/`go run`;
- any `gcloud secrets` verb other than list, describe, get-iam-policy,
  versions list|describe and locations;
- a Secret Manager URL handed to curl/wget/http/xh, directly or through a
  variable set in the same command.

Interpreter code (Python, Node, Go ...) is not inspected, and neither is text
inside quotes, so a script using a Secret Manager client library gets
through: the rule still forbids it. Commit messages, PR bodies, grep patterns
and documents written through heredocs are data and always pass.

Reads the hook event on stdin (Claude Code and Codex send the same shape for
the Bash tool) and prints a deny decision, or nothing to let the call through.
It fails open, with a note on stderr, on anything unexpected: a broken guard
must not stop every command. Off inside waxseal's and oh's own source trees,
whose code and tests use these tools on purpose.
"""
import json
import os
import pathlib
import re
import shlex
import sys

SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
NETWORK = {"curl", "wget", "http", "https", "xh"}
CONTAINERS = {"kubectl", "docker", "podman", "nerdctl"}
LOOKUPS = {"which", "type", "whereis", "hash"}

# Words that run the rest of the line as a command, and their options that take a value.
RUNNERS = {
    "sudo": {"-u", "-g", "-U", "-C", "-D", "-h", "-p", "-r", "-t", "-T"},
    "env": {"-u", "-C", "-S"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "nice": {"-n"},
    "xargs": {"-I", "-n", "-P", "-L", "-d", "-s", "-E", "-a"},
    "stdbuf": {"-i", "-o", "-e"},
    "exec": {"-a"},
    "nohup": set(), "time": set(), "command": set(), "builtin": set(), "caffeinate": set(),
}
SSH_VALUE_OPTIONS = set("BbcDEeFIiJLlmOoPpQRSWw")
OPERATORS = set("();<>|&\n")

# Secret and version resources live under /v1/projects/...; the discovery document doesn't.
SECRET_API = re.compile(r"secretmanager\.googleapis\.com/v\d\w*/projects/", re.I)
SECRET_HOST = re.compile(r"secretmanager\.googleapis\.com", re.I)
KUBESEAL_ARG = re.compile(r"(^|/)kubeseal($|[:@])|sealed-secrets-kubeseal")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
GCLOUD_READS = (["list"], ["describe"], ["get-iam-policy"], ["versions", "list"], ["versions", "describe"], ["locations"])
SHELL_SUFFIXES = {".sh", ".bash", ".zsh"}
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
MAX_TEXT = 256_000
DEPTH = 4

KUBESEAL = "runs kubeseal"
GCLOUD = "changes or reads Secret Manager with gcloud"
API = "calls the Secret Manager API directly"


def split_heredocs(text):
    """Return the text with heredoc bodies removed, and each (header line, body)."""
    kept, docs, lines, i = [], [], text.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        match = HEREDOC.search(line)
        i += 1
        if match:
            body = []
            while i < len(lines) and lines[i].strip() != match.group(2):
                body.append(lines[i])
                i += 1
            i += 1
            docs.append((line, "\n".join(body)))
    return "\n".join(kept), docs


def tokens(text):
    """Simple commands as argv lists: quotes removed, split on unquoted operators
    and newlines, `#` comments dropped."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    found, current, comment, redirect = [], [], False, False
    for token in lexer:
        if set(token) <= OPERATORS:
            if "\n" in token:
                comment = redirect = False
            elif comment:
                continue
            if set(token) <= set("<>&") and set(token) & set("<>"):
                redirect = True  # the next word is a file name, not a command
                continue
            found.append(current)
            current = []
        elif comment:
            continue
        elif redirect:
            redirect = False
        elif token.startswith("#"):
            comment = True
        else:
            current.append(token)
    found.append(current)
    return [argv for argv in found if argv]


def simple_commands(text):
    text = text.replace("\\\n", " ")
    try:
        return tokens(text)
    except ValueError:
        found = []
        for line in text.split("\n"):
            try:
                found.extend(tokens(line))
            except ValueError:
                pass
        return found


def program(argv):
    """Strip env assignments and wrapper commands; return the argv that runs."""
    i = 0
    while i < len(argv):
        word = argv[i]
        if ASSIGNMENT.match(word):
            i += 1
        elif word == "command" and i + 1 < len(argv) and argv[i + 1] in ("-v", "-V"):
            return ["which"] + argv[i + 2:]
        elif word in RUNNERS:
            value_options = RUNNERS[word]
            i += 1
            while i < len(argv) and argv[i].startswith("-"):
                i += 2 if argv[i] in value_options else 1
            if word == "timeout" and i < len(argv):
                i += 1
        elif word == "mise" and i + 1 < len(argv) and argv[i + 1] in ("exec", "x"):
            rest = argv[i + 2:]
            i = i + 2 + (rest.index("--") + 1 if "--" in rest else len(rest))
        else:
            break
    return argv[i:]


def shell_script(arg, cwd):
    """The path and text of a shell script about to run, if it is one."""
    path = pathlib.Path(arg)
    if not path.is_absolute():
        path = pathlib.Path(cwd) / path
    try:
        if not path.is_file() or path.stat().st_size > MAX_TEXT:
            return None, None
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None, None
    first = text.split("\n", 1)[0]
    if path.suffix in SHELL_SUFFIXES or (first.startswith("#!") and re.search(r"\b(ba|z|da|k)?sh\b", first)):
        return path, text
    return None, None


def argv_reason(argv, cwd, depth):
    argv = program(argv)
    if not argv:
        return None
    name = os.path.basename(argv[0])
    args = argv[1:]
    if name in LOOKUPS:
        return None
    if name == "kubeseal":
        return KUBESEAL
    if name in SHELLS:
        for i, flag in enumerate(args):
            if re.fullmatch(r"-[a-z]*c[a-z]*", flag) and i + 1 < len(args):
                return reason_for(args[i + 1], cwd, depth + 1)
            if not flag.startswith("-"):
                path, text = shell_script(flag, cwd)
                return reason_for(text, str(path.parent), depth + 1) if text else None
        return None
    if "/" in argv[0]:
        path, text = shell_script(argv[0], cwd)
        if text:
            return reason_for(text, str(path.parent), depth + 1)
    if name == "eval":
        return reason_for(" ".join(args), cwd, depth + 1)
    if name == "ssh":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if len(args[i]) == 2 and args[i][1] in SSH_VALUE_OPTIONS else 1
        return reason_for(" ".join(args[i + 1:]), cwd, depth + 1) if i + 1 < len(args) else None
    if name == "watch":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in ("-n", "--interval") else 1
        return reason_for(" ".join(args[i:]), cwd, depth + 1) if i < len(args) else None
    if name in CONTAINERS or (name == "go" and args[:1] == ["run"]):
        # kubectl's own arguments are resource names; only the command after -- runs.
        if name != "kubectl" and any(KUBESEAL_ARG.search(arg) for arg in args):
            return KUBESEAL
        return argv_reason(args[args.index("--") + 1:], cwd, depth + 1) if "--" in args else None
    if name == "gcloud" and "secrets" in args:
        verbs = [word for word in args[args.index("secrets") + 1:] if not word.startswith("-")]
        return None if any(verbs[:len(read)] == read for read in GCLOUD_READS) else GCLOUD
    if name in NETWORK:
        return API if any(SECRET_API.search(arg) for arg in args) else None
    return None


def heredoc_reason(header, body, cwd, depth):
    """A heredoc counts only when a shell runs it or it becomes a shell script."""
    before = HEREDOC.split(header, maxsplit=1)[0]
    commands = simple_commands(re.sub(r"\d*>>?\s*\S+", " ", before)) or [[]]
    argv = program(commands[-1])
    name = os.path.basename(argv[0]) if argv else ""
    if name in SHELLS or name == "ssh":
        return reason_for(body, cwd, depth + 1)
    if name in ("cat", "tee"):
        target = re.search(r">>?\s*(\S+)", header)
        written = target.group(1) if target else next((a for a in argv[1:] if not a.startswith("-")), "")
        if pathlib.Path(written.strip("'\"")).suffix in SHELL_SUFFIXES:
            return reason_for(body, cwd, depth + 1)
    return None


def reason_for(text, cwd, depth=0):
    if not text or depth > DEPTH or len(text) > MAX_TEXT:
        return None
    main, docs = split_heredocs(text)
    for header, body in docs:
        why = heredoc_reason(header, body, cwd, depth)
        if why:
            return why
    commands = simple_commands(main)
    # A Secret Manager URL kept in a variable, then fetched with it in the same command.
    names = {word.split("=", 1)[0] for argv in commands for word in argv if ASSIGNMENT.match(word) and SECRET_HOST.search(word)}
    for argv in map(program, commands):
        if names and argv and os.path.basename(argv[0]) in NETWORK:
            if any(f"${n}" in arg or f"${{{n}}}" in arg for n in names for arg in argv[1:]):
                return API
    for argv in commands:
        why = argv_reason(argv, cwd, depth)
        if why:
            return why
    return None


def exempt(cwd):
    """True inside waxseal's or oh's own source tree."""
    path = pathlib.Path(cwd).resolve()
    for directory in (path, *path.parents):
        if (directory / "plugins/oh/hooks/waxseal-guard.py").is_file():
            return True
        go_mod = directory / "go.mod"
        if go_mod.is_file():
            lines = go_mod.read_text(encoding="utf-8", errors="ignore").splitlines()
            return any(line.strip() == "module github.com/shermanhuman/waxseal" for line in lines)
    return False


def command_text(tool_input):
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, list):
        return shlex.join(str(part) for part in command)
    return command if isinstance(command, str) else ""


def decide(event):
    if not isinstance(event, dict):
        return None
    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    if exempt(cwd):
        return None
    why = reason_for(command_text(event.get("tool_input")), cwd)
    if not why:
        return None
    return (
        f"Blocked by oh: this command {why}. Sealed secrets go through the waxseal CLI only: "
        "`waxseal key add|set|edit`, `waxseal reseal`, `waxseal secret list|show|retire`, "
        "one visible command per call, values from --from-file, stdin or --generate. "
        "If waxseal can't do what you need, stop and ask the user; don't work around it. "
        "If gcloud needs a fresh login, ask the user to run `! gcloud auth login`."
    )


def main():
    try:
        message = decide(json.load(sys.stdin))
    except Exception as error:  # fail open, but say so
        print(f"waxseal-guard: skipped ({type(error).__name__}: {error})", file=sys.stderr)
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
