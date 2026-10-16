"""PreToolUse guard: sealed secrets go through the waxseal CLI only.

Refuses shell commands that seal with kubeseal or touch Google Secret Manager
outside waxseal: any `gcloud secrets` verb other than list/describe, any
Secret Manager URL handed to curl/wget, and Secret Manager value calls in code
run by an interpreter. Those side paths skip waxseal's metadata, and reading
values puts plaintext in the session.

What counts is what would run, not what is mentioned: quoted text, commit
messages, PR bodies, grep patterns and heredocs written to documents are data.
Heredocs fed to a shell or an interpreter, `bash -c`/`ssh`/`eval` strings,
command substitutions, and script files about to be run are checked.

Reads the hook event on stdin (Claude Code and Codex send the same shape for
the Bash tool) and prints a deny decision, or nothing to let the call through.
Anything it can't parse is let through: a broken guard must not stop every
command. It is a backstop for the always-on rule, not a sandbox; a URL built
at runtime or a script fetched and piped in will get past it.

Off inside waxseal's and oh's own source trees, whose code and tests use these
tools and strings on purpose.
"""
import json
import os
import pathlib
import re
import shlex
import sys

SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
INTERPRETER = re.compile(r"(python[0-9.]*|node|nodejs|deno|bun|ruby|perl|php)")
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

SECRET_API = re.compile(r"secretmanager\.googleapis\.com", re.I)
SECRET_CALL = re.compile(r"(access|add|destroy)_?secret_?version", re.I)
GCLOUD_IN_CODE = re.compile(r"gcloud\W+(?:\S+\W+)*?secrets\W+(versions\W+(access|add|destroy|disable|enable)|create|delete|update)\b")
GCLOUD_READS = (["list"], ["describe"], ["get-iam-policy"], ["versions", "list"], ["versions", "describe"], ["locations"])
SCRIPT_SUFFIXES = {".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".php", ".go"}
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
MAX_SCRIPT_BYTES = 1_000_000
DEPTH = 4

KUBESEAL = "runs kubeseal"
GCLOUD = "changes or reads Secret Manager with gcloud"
API = "calls the Secret Manager API directly"


def code_reason(code):
    """Secret Manager use inside interpreter code, ignoring comment lines."""
    lines = [line for line in code.splitlines() if not line.lstrip().startswith(("#", "//"))]
    text = "\n".join(lines)
    if GCLOUD_IN_CODE.search(text):
        return GCLOUD
    return API if SECRET_API.search(text) or SECRET_CALL.search(text) else None


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
    """Simple commands as argv lists, split on unquoted operators and newlines."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    found, current = [], []
    for token in lexer:
        if set(token) <= set("();<>|&\n"):
            found.append(current)
            current = []
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
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", word):
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


def script_file(arg, cwd):
    path = pathlib.Path(arg)
    if not path.is_absolute():
        path = pathlib.Path(cwd) / path
    try:
        if path.is_file() and path.stat().st_size <= MAX_SCRIPT_BYTES:
            return path, path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pass
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
                path, content = script_file(flag, cwd)
                return reason_for(content, str(path.parent), depth + 1) if content else None
        return None
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
    if name in CONTAINERS:
        if any(re.search(r"(^|/)kubeseal($|[:@])|sealed-secrets-kubeseal", arg) for arg in args):
            return KUBESEAL
        return None
    if name == "gcloud" and "secrets" in args:
        rest = args[args.index("secrets") + 1:]
        verbs = [word for word in rest if not word.startswith("-")]
        if not any(verbs[:len(read)] == read for read in GCLOUD_READS):
            return GCLOUD
        return None
    if name == "go" and args[:1] == ["run"]:
        targets = [arg for arg in args[1:] if not arg.startswith("-")]
        if any(re.search(r"(^|/)kubeseal($|@)", arg) for arg in targets):
            return KUBESEAL
        for arg in targets:
            if arg.endswith(".go"):
                _, content = script_file(arg, cwd)
                if content and code_reason(content):
                    return code_reason(content)
        return None
    if name in NETWORK:
        return API if any(SECRET_API.search(arg) for arg in args) else None
    if INTERPRETER.fullmatch(name):
        for i, flag in enumerate(args):
            if flag in ("-c", "-e", "--eval", "-p", "--print", "-r") and i + 1 < len(args):
                return code_reason(args[i + 1])
            if flag == "-m":
                return None
            if not flag.startswith("-"):
                _, content = script_file(flag, cwd)
                return code_reason(content) if content else None
    return None


def heredoc_reason(header, body, cwd, depth):
    before = HEREDOC.split(header, maxsplit=1)[0]
    commands = simple_commands(re.sub(r"\d*>>?\s*\S+", " ", before)) or [[]]
    argv = program(commands[-1])
    name = os.path.basename(argv[0]) if argv else ""
    if name in SHELLS or name == "ssh":
        return reason_for(body, cwd, depth + 1)
    if INTERPRETER.fullmatch(name):
        return code_reason(body)
    if name in ("cat", "tee"):
        target = re.search(r">>?\s*(\S+)", header)
        written = target.group(1) if target else next((a for a in argv[1:] if not a.startswith("-")), "")
        suffix = pathlib.Path(written.strip("'\"")).suffix
        if suffix in (".sh", ".bash", ".zsh"):
            return reason_for(body, cwd, depth + 1)
        if suffix in SCRIPT_SUFFIXES:
            return code_reason(body)
    return None


def reason_for(text, cwd, depth=0):
    if not text or depth > DEPTH:
        return None
    main, docs = split_heredocs(text)
    for header, body in docs:
        why = heredoc_reason(header, body, cwd, depth)
        if why:
            return why
    commands = simple_commands(main)
    # A Secret Manager URL kept in a variable and then fetched.
    if any(SECRET_API.search(word) for argv in commands for word in argv if re.match(r"[A-Za-z_][A-Za-z0-9_]*=", word)):
        if any(os.path.basename(program(argv)[0]) in NETWORK for argv in commands if program(argv)):
            return API
    for argv in commands:
        why = argv_reason(argv, cwd, depth)
        if why:
            return why
        for arg in argv:
            for inner in re.findall(r"\$\(([^()]*)\)|`([^`]*)`", arg):
                why = reason_for(inner[0] or inner[1], cwd, depth + 1)
                if why:
                    return why
    return None


def exempt(cwd):
    """True inside waxseal's or oh's own source tree."""
    try:
        path = pathlib.Path(cwd).resolve()
    except (OSError, RuntimeError, TypeError):
        return False
    for directory in (path, *path.parents):
        if (directory / "plugins/oh/hooks/waxseal-guard.py").is_file():
            return True
        go_mod = directory / "go.mod"
        if go_mod.is_file():
            try:
                lines = go_mod.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                return False
            return any(line.strip() == "module github.com/shermanhuman/waxseal" for line in lines)
    return False


def command_text(tool_input):
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, list):
        return shlex.join(str(part) for part in command)
    return command if isinstance(command, str) else ""


def main():
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return
    if not isinstance(event, dict):
        return
    cwd = event.get("cwd") or os.getcwd()
    try:
        why = reason_for(command_text(event.get("tool_input")), cwd)
    except RecursionError:
        return
    if not why or exempt(cwd):
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
