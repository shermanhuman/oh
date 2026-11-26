"""PreToolUse guard: agents don't read or write Secret Manager values.

A backstop for oh's always-on rule, deliberately narrow: it looks only at what
a shell would execute, never at code or prose. It refuses:

- `kubeseal`, run directly or through a wrapper (sudo, timeout, nice, env,
  xargs, mise exec, ...), inside `bash -c`/`ssh`/`eval`/`watch` strings, a
  heredoc fed to a shell, a shell script about to run, or named as the program
  in `kubectl exec`/`docker run`/`go run`;
- any `gcloud secrets` verb other than list, describe, get-iam-policy,
  versions list|describe and locations, with one exception: a made-up staging
  value, generated in the same pipe that stores it and never printed (the
  owner's decision D-3462, 2026-11-26). Exactly
  `openssl rand -hex|-base64 <n of 16 or more> | tr -d '\n' | gcloud secrets
  versions add staging-<entry> --data-file=- --project=waxseal-infra-secrets`,
  and the whole command must be such pipes and `versions list` calls and
  nothing else (optionally inside a bare `bash -c`): no other statement,
  function, alias, assignment, redirect, subshell, substitution, variable or
  glob, any of which could change what the pipe does (oh#58 round 1);
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
SHELLS, SSH_VALUE_OPTIONS, ASSIGNMENT, SHELL_SUFFIXES, HEREDOC, MAX_TEXT = (
    shell.SHELLS, shell.SSH_VALUE_OPTIONS, shell.ASSIGNMENT, shell.SHELL_SUFFIXES, shell.HEREDOC, shell.MAX_TEXT
)
split_heredocs, simple_commands, program, shell_script, command_text = (
    shell.split_heredocs, shell.simple_commands, shell.program, shell.shell_script, shell.command_text
)

NETWORK = {"curl", "wget", "http", "https", "xh"}
CONTAINERS = {"kubectl", "docker", "podman", "nerdctl"}
LOOKUPS = {"which", "type", "whereis", "hash"}

# The global and regional hosts (secretmanager.<region>.rep.googleapis.com), any port.
# Secret and version resources live under /v1/projects/...; the discovery document doesn't.
SECRET_HOST = re.compile(r"secretmanager(\.[a-z0-9-]+\.rep)?\.googleapis\.com(:\d+)?", re.I)
SECRET_API = re.compile(SECRET_HOST.pattern + r"/v\d\w*/projects/", re.I)
KUBESEAL_ARG = re.compile(r"(^|/)kubeseal($|[:@])|sealed-secrets-kubeseal")
GCLOUD_SWITCHES = {"-q", "--quiet", "-h", "--help", "--log-http", "--no-user-output-enabled", "--user-output-enabled"}
GCLOUD_READS = (["list"], ["describe"], ["get-iam-policy"], ["versions", "list"], ["versions", "describe"], ["locations"])
# The one write (D-3462): a made-up value for a staging entry, in this project.
MADE_UP_PROJECT = "waxseal-infra-secrets"
MADE_UP_ENTRY = re.compile(r"staging-[A-Za-z0-9_-]+")
MADE_UP_MIN_BYTES = 16
DEPTH = 4

KUBESEAL = "runs kubeseal"
GCLOUD = "changes or reads Secret Manager with gcloud"
API = "calls the Secret Manager API directly"


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


def made_up_add(argv):
    """gcloud secrets versions add staging-<entry> --data-file=- --project=<ours>, nothing else."""
    if argv[:4] != ["gcloud", "secrets", "versions", "add"]:
        return False
    entry, data, project, rest, i = None, None, None, argv[4:], 0
    while i < len(rest):
        arg = rest[i]
        name, eq, value = arg.partition("=")
        if name in ("--data-file", "--project"):
            if not eq:
                if i + 1 >= len(rest):
                    return False
                value, i = rest[i + 1], i + 1
            if name == "--data-file" and data is None:
                data = value
            elif name == "--project" and project is None:
                project = value
            else:
                return False
        elif not arg.startswith("-") and entry is None:
            entry = arg
        else:
            return False
        i += 1
    return bool(entry and MADE_UP_ENTRY.fullmatch(entry)) and data == "-" and project == MADE_UP_PROJECT


def made_up_statement(stages):
    """`openssl rand -hex|-base64 <n> | tr -d '\\n' | gcloud ... add ...`, or `gcloud secrets versions list ...`."""
    if len(stages) == 1:
        return stages[0][:4] == ["gcloud", "secrets", "versions", "list"]
    if len(stages) != 3 or stages[1] != ["tr", "-d", "\\n"] or not made_up_add(stages[2]):
        return False
    rand = stages[0]
    return (len(rand) == 4 and rand[:2] == ["openssl", "rand"] and rand[2] in ("-hex", "-base64")
            and rand[3].isdigit() and int(rand[3]) >= MADE_UP_MIN_BYTES)


def made_up_text(text, depth=0):
    """True only when the whole text is D-3462's made-up staging value, with
    nothing beside it: one or more exact pipes or version listings, joined by
    `;`, `&&` or newlines, optionally as the one argument of a bare `bash -c`.
    No other statement, function, alias, assignment, redirect, subshell,
    process or command substitution, variable or glob can sit next to it and
    change what the pipe does."""
    if depth > 1 or not text or len(text) > MAX_TEXT:
        return False
    try:
        tokens = shell.lex(text)
    except Exception:
        return False
    words = [v for kind, v in tokens if kind == "word"]
    if len(tokens) == 3 and len(words) == 3 and words[0] in ("bash", "sh") and words[1] in ("-c", "-lc"):
        return made_up_text(words[2], depth + 1)
    statements, stages, argv = [], [], []
    for kind, value in tokens + [("op", ";")]:
        if kind == "word":
            if ASSIGNMENT.match(value) or re.search(r"[$`*?\[\]{}~]", value):
                return False
            argv.append(value)
        elif kind == "op" and value in ("|", ";", "\n", "&&"):
            if not argv:
                if value == "|" or stages:
                    return False
                continue
            stages.append(argv)
            argv = []
            if value != "|":
                statements.append(stages)
                stages = []
        else:
            return False
    adds = [s for s in statements if len(s) == 3]
    return bool(adds) and all(made_up_statement(s) for s in statements)


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



def decide(event):
    if not isinstance(event, dict):
        return None
    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    if exempt(cwd):
        return None
    text = command_text(event.get("tool_input"))
    if made_up_text(text):
        return None
    why = reason_for(text, cwd)
    if not why:
        return None
    return (
        f"Blocked by oh: this command {why}. Secrets are External Secrets Operator `ExternalSecret`s "
        "reading Google Secret Manager at pinned versions; agents change only those manifests, in PRs "
        "(breakdown-infra's `.claude/rules/secrets.md`), and the user writes values in the Secret Manager console. "
        "Agents may run `gcloud secrets versions list <entry>` (names and states, no values) and add a made-up "
        "staging value, never printed (D-3462): `openssl rand -hex 24 | tr -d '\\n' | gcloud secrets versions add "
        f"staging-<entry> --data-file=- --project={MADE_UP_PROJECT}`, one literal entry per pipe. "
        "For anything else, stop and ask the user; don't work around it. "
        "If gcloud reports expired credentials, ask the user to run `! gcloud auth login`."
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
