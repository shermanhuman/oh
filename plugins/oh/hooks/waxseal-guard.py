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

# Shell keywords that can stand before a command.
KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "fi", "done"}

# Words that run the rest of the line as a command, and their options that take a value.
RUNNERS = {
    "sudo": {"-u", "-g", "-U", "-C", "-D", "-h", "-p", "-r", "-t", "-T"},
    "env": {"-u", "-C", "-S"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
    "nice": {"-n"},
    "xargs": {"-I", "-n", "-P", "-L", "-d", "-s", "-E", "-a"},
    "stdbuf": {"-i", "-o", "-e"},
    "exec": {"-a"},
    "nohup": set(), "time": set(), "command": set(), "builtin": set(), "caffeinate": {"-t", "-w"},
}
SSH_VALUE_OPTIONS = set("BbcDEeFIiJLlmOoPpQRSWw")

# The global and regional hosts (secretmanager.<region>.rep.googleapis.com), any port.
# Secret and version resources live under /v1/projects/...; the discovery document doesn't.
SECRET_HOST = re.compile(r"secretmanager(\.[a-z0-9-]+\.rep)?\.googleapis\.com(:\d+)?", re.I)
SECRET_API = re.compile(SECRET_HOST.pattern + r"/v\d\w*/projects/", re.I)
KUBESEAL_ARG = re.compile(r"(^|/)kubeseal($|[:@])|sealed-secrets-kubeseal")
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
GCLOUD_SWITCHES = {"-q", "--quiet", "-h", "--help", "--log-http", "--no-user-output-enabled", "--user-output-enabled"}
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


class Unparsed(ValueError):
    pass


def lex(text):
    """Split shell text into ("word", text) and ("op", text) tokens, the way a
    POSIX shell would: quotes are removed but never turn into operators or
    comments, `#` starts a comment only at the start of an unquoted word, and
    unquoted `$(...)` and backticks become ("subst", inner text)."""
    out, word, started, i, n = [], [], False, 0, len(text)

    def end_word():
        nonlocal word, started
        if started:
            out.append(("word", "".join(word)))
        word, started = [], False

    while i < n:
        c = text[i]
        if c in " \t\r":
            end_word()
            i += 1
        elif c == "\\":
            if i + 1 < n and text[i + 1] != "\n":
                word.append(text[i + 1])
                started = True
            i += 2
        elif c == "'":
            close = text.find("'", i + 1)
            if close < 0:
                raise Unparsed("open single quote")
            word.append(text[i + 1:close])
            started, i = True, close + 1
        elif c == '"':
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    i += 1
                word.append(text[i])
                i += 1
            if i >= n:
                raise Unparsed("open double quote")
            started, i = True, i + 1
        elif c == "#" and not started:
            while i < n and text[i] != "\n":
                i += 1
        elif c == "`":
            close = text.find("`", i + 1)
            if close < 0:
                raise Unparsed("open backtick")
            out.append(("subst", text[i + 1:close]))
            started, i = True, close + 1
        elif c == "$" and text[i + 1:i + 2] == "(":
            depth, k = 1, i + 2
            while k < n and depth:
                depth += {"(": 1, ")": -1}.get(text[k], 0)
                k += 1
            if depth:
                raise Unparsed("open $(")
            out.append(("subst", text[i + 2:k - 1]))
            started, i = True, k
        elif c in ";()\n":
            end_word()
            out.append(("op", c))
            i += 1
        elif c in "<>&|":
            end_word()
            k = i
            while k < n and text[k] in "<>&|":
                k += 1
            out.append(("op", text[i:k]))
            i = k
        else:
            word.append(c)
            started = True
            i += 1
    end_word()
    return out


def simple_commands(text):
    """Simple commands as argv lists, plus the text of every command substitution.
    Redirect targets are file names, not commands. Text that doesn't parse as a
    whole is tried line by line; lines that still don't are skipped."""
    try:
        chunks = [lex(text)]
    except Unparsed:
        chunks = []
        for line in text.split("\n"):
            try:
                chunks.append(lex(line))
            except Unparsed:
                pass
    commands, substs = [], []
    for chunk in chunks:
        current, redirect = [], False
        for kind, value in chunk:
            if kind == "subst":
                substs.append(value)
            elif kind == "op":
                if set(value) & set("<>"):
                    redirect = True
                    continue
                commands.append(current)
                current, redirect = [], False
            elif redirect:
                redirect = False
            else:
                current.append(value)
        commands.append(current)
    return [argv for argv in commands if argv], substs


def program(argv):
    """Strip env assignments and wrapper commands; return the argv that runs."""
    i = 0
    while i < len(argv):
        word = argv[i]
        if ASSIGNMENT.match(word) or word in KEYWORDS:
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


def gcloud_words(args):
    """gcloud's command words, without release tracks, flags or flag values."""
    words, i = [], 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            takes_value = "=" not in arg and arg not in GCLOUD_SWITCHES
            i += 2 if takes_value and i + 1 < len(args) and not args[i + 1].startswith("-") else 1
        else:
            if arg not in ("alpha", "beta") or words:
                words.append(arg)
            i += 1
    return words


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
            if i > 0 and re.fullmatch(r"[-+][a-zA-Z]*[oO]", args[i - 1]):
                continue
            if not flag.startswith(("-", "+")):
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
    if name == "gcloud":
        words = gcloud_words(args)
        if words[:1] == ["secrets"]:
            return None if any(words[1:1 + len(read)] == read for read in GCLOUD_READS) else GCLOUD
    if name in NETWORK:
        return API if any(SECRET_API.search(arg) for arg in args) else None
    return None


def heredoc_reason(header, body, cwd, depth):
    """A heredoc counts only when a shell runs it or it becomes a shell script."""
    before = HEREDOC.split(header, maxsplit=1)[0]
    commands = simple_commands(re.sub(r"\d*>>?\s*\S+", " ", before))[0] or [[]]
    argv = program(commands[-1])
    name = os.path.basename(argv[0]) if argv else ""
    # `bash <<EOF`, or the heredoc piped on into a shell: `cat <<EOF | bash`, `| ssh vm bash`.
    after = HEREDOC.split(header, maxsplit=1)[3]
    later = simple_commands(re.sub(r"\d*>>?\s*\S+", " ", after))[0]
    if name in SHELLS or name == "ssh" or any(
        program(c) and os.path.basename(program(c)[0]) in SHELLS | {"ssh"} for c in later
    ):
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
    commands, substs = simple_commands(main)
    for inner in substs:
        why = reason_for(inner, cwd, depth + 1)
        if why:
            return why
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
