"""PreToolUse guard: agents never read or write a Secret Manager value.

Secret values live in Google Secret Manager (project `waxseal-infra-secrets`)
and reach the cluster through External Secrets Operator; the user writes them
in the console (breakdown-infra's `.claude/rules/secrets.md`). A backstop for
that rule, deliberately narrow: it looks only at what a shell would execute,
never at code or prose. It refuses:

- any `gcloud secrets` verb other than list, describe, get-iam-policy,
  versions list|describe and locations, run directly, through a wrapper (sudo,
  env, xargs, mise exec, find -exec, ...), inside `bash -c`/`su -c`/`ssh`/
  `eval`/`watch`/`env -S` strings, a heredoc fed to a shell, a shell script
  about to run, or a command substitution;
- a Secret Manager URL handed to curl/wget/http/xh, directly or through a
  variable set in the same command;
- `kubeseal` (Sealed Secrets is retired), the same ways.

It reads the text the way bash does (`shell.lex_exact`). Where it can't be
sure it has (the text doesn't lex, a heredoc doesn't end the way bash would end
it, the text is too long or nested too deep, the program or a gcloud command
word is a variable or expansion, a shell reads commands from stdin, an alias
is defined), it refuses the text if it mentions Secret Manager (`MENTION`),
and otherwise lets it through as before.

Not covered, by design or because no per-command hook can see it: interpreter
code (Python, Node, Go ...) using a Secret Manager client; a `PATH` shim, an
alias or function from the user's shell snapshot, login profiles or
`$BASH_ENV` written by an earlier command; a persisted `gcloud config set
core/log_http true`. Commit messages, PR bodies, grep patterns and documents
written through heredocs are data and pass.

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
SHELLS, SSH_VALUE_OPTIONS, ASSIGNMENT, SHELL_SUFFIXES, MAX_TEXT = (
    shell.SHELLS, shell.SSH_VALUE_OPTIONS, shell.ASSIGNMENT, shell.SHELL_SUFFIXES, shell.MAX_TEXT
)
place_heredocs, exact_commands, exact_pipes, program, shell_script, command_text, Expanded = (
    shell.place_heredocs, shell.exact_commands, shell.exact_pipes, shell.program, shell.shell_script,
    shell.command_text, shell.Expanded,
)

NETWORK = {"curl", "wget", "http", "https", "xh"}
CONTAINERS = {"kubectl", "docker", "podman", "nerdctl"}
LOOKUPS = {"which", "type", "whereis", "hash"}
# Programs that run a string they're given with -c or --command.
STRING_RUNNERS = {"su", "runuser", "script", "flock"}
# Programs worth finding again as a later word of an argv (`find -exec`, `parallel`, `setsid` ...).
NESTED = SHELLS | {"gcloud", "eval"}

# The global and regional hosts (secretmanager.<region>.rep.googleapis.com), any port.
# Secret and version resources live under /v1/projects/...; the discovery document doesn't.
SECRET_HOST = re.compile(r"secretmanager(\.[a-z0-9-]+\.rep)?\.googleapis\.com(:\d+)?", re.I)
SECRET_API = re.compile(SECRET_HOST.pattern + r"/v\d\w*/projects/", re.I)
# Text that mentions Secret Manager: when the guard can't read a text for certain, it refuses it only if this matches.
MENTION = re.compile(r"(?i:secretmanager)|\bsecrets\b(?![./-])")
KUBESEAL_ARG = re.compile(r"(^|/)kubeseal($|[:@])|sealed-secrets-kubeseal")
GCLOUD_SWITCHES = {
    "-q", "--quiet", "-h", "--help", "--log-http", "--no-user-output-enabled", "--user-output-enabled",
    "--version", "--verbose",
}
GCLOUD_VALUE_FLAGS = {
    "--project", "--account", "--configuration", "--format", "--filter", "--flatten", "--limit", "--page-size",
    "--sort-by", "--location", "--impersonate-service-account", "--verbosity", "--billing-project",
    "--flags-file", "--trace-token", "--secret", "--region", "--zone",
}
GCLOUD_READS = (["list"], ["describe"], ["get-iam-policy"], ["versions", "list"], ["versions", "describe"], ["locations"])
MAX_READINGS = 64
DEPTH = 4

KUBESEAL = "runs kubeseal"
GCLOUD = "changes or reads Secret Manager with gcloud"
API = "calls the Secret Manager API directly"
UNSURE = "mentions Secret Manager in a form the guard can't read for certain"


def mentions(text):
    return bool(MENTION.search(text))


def gcloud_readings(args):
    """Every way gcloud could split args into command words: a flag it doesn't
    know (no `=`, before a word) may or may not take that word as its value."""
    readings = [[]]
    i = 0
    while i < len(args):
        arg = args[i]
        nxt = args[i + 1] if i + 1 < len(args) else None
        if arg == "--":
            break
        if arg.startswith("-"):
            known_switch = arg in GCLOUD_SWITCHES or arg.startswith("--no-") or "=" in arg
            if known_switch or nxt is None or nxt.startswith("-"):
                i += 1
            elif arg in GCLOUD_VALUE_FLAGS:
                i += 2
            else:
                if len(readings) * 2 > MAX_READINGS:
                    return None
                # Taking the value: the word is skipped. Not taking it: the word counts.
                readings = [r + ["\0skip"] for r in readings] + [r + [nxt] for r in readings]
                i += 2
            continue
        readings = [r + [arg] for r in readings]
        i += 1
    out = []
    for reading in readings:
        words = [w for w in reading if w != "\0skip"]
        while words and words[0] in ("alpha", "beta") and not isinstance(words[0], Expanded):
            words = words[1:]
        out.append(words)
    return out


def gcloud_reason(args, mentioned):
    readings = gcloud_readings(args)
    if readings is None:
        return UNSURE if mentioned else None
    for words in readings:
        if not words:
            # Bare gcloud: its command words may come from stdin (`… | xargs gcloud`).
            if mentioned:
                return UNSURE
            continue
        if isinstance(words[0], Expanded):
            if mentioned:
                return UNSURE
            continue
        if words[0] != "secrets":
            continue
        if any(isinstance(w, Expanded) for w in words[1:3]):
            return GCLOUD
        if not any(words[1:1 + len(read)] == read for read in GCLOUD_READS):
            return GCLOUD
    return None


def shell_command(args):
    """(string, script) for a shell's arguments: the -c string, or the script it runs."""
    i, run_string = 0, False
    while i < len(args):
        arg = args[i]
        if arg == "--":
            i += 1
            break
        if arg in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            i += 2
            continue
        if re.fullmatch(r"[-+][A-Za-z]+", arg):
            run_string = run_string or (arg[0] == "-" and "c" in arg)
            # `-euo pipefail`: o and O take the next word as their value.
            i += 2 if arg[-1] in "oO" else 1
            continue
        if arg.startswith("--"):
            i += 1
            continue
        break
    if i >= len(args):
        return None, None
    return (args[i], None) if run_string else (None, args[i])


def string_runner(name, args):
    """The command string `su -c`, `runuser -c`, `script -c` or `flock -c` runs."""
    for i, arg in enumerate(args):
        if arg.startswith("--command="):
            return arg.split("=", 1)[1]
        if (arg == "--command" or re.fullmatch(r"-[A-Za-z]*c", arg)) and i + 1 < len(args):
            return args[i + 1]
    return None


def split_string(argv):
    """The string `env -S '…'` (or --split-string) splits into a command, if any."""
    for i, word in enumerate(argv):
        if word == "env":
            for option in argv[i + 1:]:
                if option.startswith("--split-string="):
                    return option.split("=", 1)[1]
                if option.startswith("-S") and len(option) > 2:
                    return option[2:]
                if option in ("-S", "--split-string"):
                    k = argv.index(option, i + 1)
                    return argv[k + 1] if k + 1 < len(argv) else None
                if not option.startswith("-") and not ASSIGNMENT.match(option):
                    return None
            return None
        if not ASSIGNMENT.match(word) and word not in shell.KEYWORDS and word not in shell.RUNNERS:
            return None
    return None


def argv_reason(argv, cwd, depth, mentioned, nested=True):
    string = split_string(argv)
    if string is not None:
        return reason_for(string, cwd, depth + 1, mentioned)
    argv = program(argv)
    if not argv:
        return None
    name = os.path.basename(argv[0])
    args = argv[1:]
    if mentioned and (isinstance(argv[0], Expanded) or argv[0] == ""):
        return UNSURE  # `$g secrets …`, `$(echo gcloud) secrets …`, `{gcloud,} secrets …`
    if name in LOOKUPS and not (name == "hash" and "-p" in args):
        return None
    why = first_reason(argv, name, args, cwd, depth, mentioned)
    if why or not nested:
        return why
    # A program run by another one: `find -exec gcloud …`, `parallel gcloud …`, `setsid bash -c …`.
    for j in range(1, len(argv)):
        if os.path.basename(argv[j]) in NESTED and not isinstance(argv[j], Expanded):
            why = argv_reason(argv[j:], cwd, depth + 1, mentioned, nested=False)
            if why:
                return why
    return None


def first_reason(argv, name, args, cwd, depth, mentioned):
    """Why this command itself is refused, or None."""
    if name in LOOKUPS:
        if name == "hash" and "-p" in args and mentioned:
            return UNSURE
        return None
    if name == "alias" and mentioned and any("=" in a for a in args):
        return UNSURE
    if name == "kubeseal":
        return KUBESEAL
    if name in SHELLS:
        string, script = shell_command(args)
        if string is not None:
            return reason_for(string, cwd, depth + 1, mentioned)
        if script is not None:
            path, text = shell_script(script, cwd)
            return reason_for(text, str(path.parent), depth + 1, mentioned) if text else None
        return None
    if name in STRING_RUNNERS:
        string = string_runner(name, args)
        if string is not None:
            return reason_for(string, cwd, depth + 1, mentioned)
    if "/" in argv[0]:
        path, text = shell_script(argv[0], cwd)
        if text:
            return reason_for(text, str(path.parent), depth + 1, mentioned)
    if name == "eval":
        return reason_for(" ".join(args), cwd, depth + 1, mentioned)
    if name == "ssh":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if len(args[i]) == 2 and args[i][1] in SSH_VALUE_OPTIONS else 1
        return reason_for(" ".join(args[i + 1:]), cwd, depth + 1, mentioned) if i + 1 < len(args) else None
    if name == "watch":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in ("-n", "--interval") else 1
        return reason_for(" ".join(args[i:]), cwd, depth + 1, mentioned) if i < len(args) else None
    if name in CONTAINERS or (name == "go" and args[:1] == ["run"]):
        # kubectl's own arguments are resource names; only the command after -- runs.
        if name != "kubectl" and any(KUBESEAL_ARG.search(arg) for arg in args):
            return KUBESEAL
        return argv_reason(args[args.index("--") + 1:], cwd, depth + 1, mentioned) if "--" in args else None
    if name == "gcloud":
        return gcloud_reason(args, mentioned)
    if name in NETWORK:
        return API if any(SECRET_API.search(arg) for arg in args) else None
    return None


def heredoc_reason(header, start, end, body, cwd, depth, mentioned):
    """A heredoc counts only when a shell runs it or it becomes a shell script."""
    before, after = header[:start], header[end:]
    commands = exact_commands(re.sub(r"\d*>>?\s*\S+", " ", before))[0] or [[]]
    argv = program(commands[-1])
    name = os.path.basename(argv[0]) if argv else ""
    # `bash <<EOF`, or the heredoc piped on into a shell: `cat <<EOF | bash`, `| ssh vm bash`.
    later = exact_commands(re.sub(r"\d*>>?\s*\S+", " ", after))[0]
    if name in SHELLS or name == "ssh" or any(
        program(c) and os.path.basename(program(c)[0]) in SHELLS | {"ssh"} for c in later
    ):
        return reason_for(body, cwd, depth + 1, mentioned)
    if name in ("cat", "tee"):
        target = re.search(r">>?\s*(\S+)", header)
        written = target.group(1) if target else next((a for a in argv[1:] if not a.startswith("-")), "")
        if pathlib.Path(written.strip("'\"")).suffix in SHELL_SUFFIXES:
            return reason_for(body, cwd, depth + 1, mentioned)
    return None


def stdin_shell(stages):
    """True when a shell reads its commands from stdin that isn't a heredoc:
    `… | bash`, `bash -s`, `bash <<< '…'`, `bash < file`."""
    previous = None
    for argv, redirects, end in stages:
        run = program(argv)
        if run and os.path.basename(run[0]) in SHELLS and shell_command(run[1:]) == (None, None) or (
            run and os.path.basename(run[0]) in SHELLS and "-s" in run[1:]
        ):
            heredoc = any(op == "<" and target == shell.HEREDOC_PLACEHOLDER for op, target in redirects)
            fed = previous is not None and any(
                op == "<" and target == shell.HEREDOC_PLACEHOLDER for op, target in previous[1]
            )
            reads_file_or_string = any(op in ("<", "<<<") and target != shell.HEREDOC_PLACEHOLDER for op, target in redirects)
            if reads_file_or_string or (previous is not None and not fed) or (not heredoc and not fed and "-s" in run[1:]):
                return True
        previous = (argv, redirects) if end == "|" else None
    return False


def reason_for(text, cwd, depth=0, mentioned=False):
    if not text:
        return None
    if depth > DEPTH or len(text) > MAX_TEXT:
        return UNSURE if mentioned or mentions(text) else None
    main, docs, sure = place_heredocs(text)
    mentioned = mentioned or mentions(main) or (not sure and mentions(text))
    if not sure and mentioned:
        return UNSURE
    for header, start, end, body in docs:
        why = heredoc_reason(header, start, end, body, cwd, depth, mentioned)
        if why:
            return why
    commands, substs, sure = exact_commands(main)
    if not sure and mentioned:
        return UNSURE
    for inner in substs:
        why = reason_for(inner, cwd, depth + 1, mentioned)
        if why:
            return why
    # A Secret Manager URL kept in a variable, then fetched with it in the same command.
    names = {word.split("=", 1)[0] for argv in commands for word in argv if ASSIGNMENT.match(word) and SECRET_HOST.search(word)}
    for argv in map(program, commands):
        if names and argv and os.path.basename(argv[0]) in NETWORK:
            if any(f"${n}" in arg or f"${{{n}}}" in arg for n in names for arg in argv[1:]):
                return API
    for argv in commands:
        why = argv_reason(argv, cwd, depth, mentioned)
        if why:
            return why
    if mentioned and stdin_shell(exact_pipes(main)[0]):
        return UNSURE
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
    why = reason_for(command_text(event.get("tool_input")), cwd)
    if not why:
        return None
    message = (
        f"Blocked by oh: this command {why}. Agents never read or write a secret value. "
        "Values live in Google Secret Manager (project waxseal-infra-secrets) and reach the cluster "
        "through External Secrets Operator; the user writes them in the Secret Manager console, "
        "as breakdown-infra's `.claude/rules/secrets.md` says. Metadata reads are fine "
        "(`gcloud secrets list|describe`, `gcloud secrets versions list|describe`), and so is editing "
        "an ExternalSecret manifest. If you need a value set or changed, ask the user; don't work around this."
    )
    if why == UNSURE:
        message += " If this command doesn't touch a secret value, write it more plainly (no variable or substitution as the program, no unclosed quotes, heredocs that end on their own line) and run it again."
    return message


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
