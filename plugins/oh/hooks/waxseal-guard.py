"""PreToolUse guard: agents never read or write a Secret Manager value.

Secret values live in Google Secret Manager (project `waxseal-infra-secrets`)
and reach the cluster through External Secrets Operator; the user writes them
in the console (breakdown-infra's `.claude/rules/secrets.md`). A backstop for
that rule for trusted agents (board item 392): it catches the ways an agent
would plausibly write such a command, not a command deliberately disguised to
get past it. It looks only at what a shell would execute. It refuses:

- any `gcloud secrets` verb other than list, describe, get-iam-policy,
  versions list|describe and locations, run directly, through a wrapper (sudo,
  env, xargs, mise exec, coproc, find -exec, ...), inside `bash -c`, `su -c`,
  `ssh`, `eval`, `watch`, `env -S` or `trap` strings, a heredoc fed to a shell,
  a script a shell or `source` runs, or a command substitution;
- a Secret Manager URL (global, regional or `.mtls` host) handed to
  curl/wget/http/xh, directly or through a variable set in the same command;
- `kubeseal` (Sealed Secrets is retired), the same ways.

It reads the text the way bash does (`shell.lex_exact`, `place_heredocs`), so
operators, fd numbers, CR, quoting, `$'…'`, arithmetic and heredocs can't hide
a command by accident. Where it still can't be sure (the text doesn't lex, a
heredoc doesn't end the way bash would end it, the text is too long or nested
too deep, the program or gcloud's command group is a variable or expansion, a
shell reads commands from stdin, an alias is defined, a script can't be read,
or the guard itself fails or runs past its 5 s deadline), it refuses the text
if it mentions Secret Manager (`MENTION`) and lets it through otherwise.

Not covered, by design: a command deliberately disguised to get past the guard
(agents are trusted, board item 392); interpreter code (Python, Node, Go ...)
using a Secret Manager client; a `PATH` shim, the user's aliases and functions,
login profiles or `$BASH_ENV`; a persisted `gcloud config set core/log_http
true`. Commit messages, PR bodies, grep patterns and documents written through
heredocs are data and pass, even when they quote these commands.

Reads the hook event on stdin (Claude Code and Codex send the same shape for
the Bash tool) and prints a deny decision, or nothing to let the call through.
It fails open, with a note on stderr, on anything unexpected unless the text
mentions Secret Manager: a broken guard must not stop every command. Off inside
waxseal's and oh's own source trees, whose code and tests use these tools on
purpose.
"""
import importlib.util
import json
import os
import pathlib
import re
import signal
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
NESTED = SHELLS | {"gcloud", "eval"} | {"curl", "wget", "http", "https", "xh"}
# Programs that run their later words; under these an unsure reading of a later word counts too.
RUNS_LATER = {"find", "xargs", "parallel", "setsid", "nohup", "flock", "ionice", "chrt", "taskset", "nice", "timeout", "time"}
# The global and regional hosts (secretmanager.<region>.rep.googleapis.com), any port.
# Secret and version resources live under /v1/projects/...; the discovery document doesn't.
SECRET_HOST = re.compile(r"secretmanager(\.mtls)?(\.[a-z0-9-]+\.rep)?\.googleapis\.com(:\d+)?", re.I)
SECRET_API = re.compile(SECRET_HOST.pattern + r"/v\d\w*/projects/", re.I)
# Text that mentions Secret Manager: when the guard can't read a text for certain, it refuses it only if this matches.
MENTION = re.compile(r"(?i:secretmanager)|(?<![-_./])\bsecrets\b(?![-_./])")
ARRAY_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=")
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
# Verbs that change or read a value; a later word (`grep -rn gcloud secrets docs`) counts
# only when one of these follows, since `gcloud secrets` there is usually data.
SECRET_VERBS = {"access", "add", "create", "delete", "destroy", "disable", "enable", "update", "set-iam-policy",
                "add-iam-policy-binding", "remove-iam-policy-binding"}
GCLOUD_READS = (["list"], ["describe"], ["get-iam-policy"], ["versions", "list"], ["versions", "describe"], ["locations"])
MAX_STATES = 2000
DEPTH = 4
# Per decision: literal assignments seen (`S=/abs/dir`), and files the command writes from a
# heredoc (`cat > run <<EOF`), by resolved path, so a later `bash run` reads the body.
STATE = {"vars": {}, "heredoc_files": {}, "text": ""}
TIME_LIMIT = 5  # seconds; the hook's own timeout is 10, and a killed guard lets the command run

KUBESEAL = "runs kubeseal"
GCLOUD = "changes or reads Secret Manager with gcloud"
API = "calls the Secret Manager API directly"
UNSURE = "mentions Secret Manager in a form the guard can't read for certain"


ANSI_STRING = re.compile(r"\$'((?:[^'\\]|\\.)*)'")
PARAMETER_OPERATOR = re.compile(r"\$\{[#!]?[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?(?::?[-=+?]|##?|%%?|//?|/#|/%|\^\^?|,,?|:)?")
# Words xargs, find and parallel replace before the command runs.
PLACEHOLDER = re.compile(r"\{[^{}\s]*\}")


def plain(text):
    """text with quoting taken out: escapes decoded (\\x73, \\163, \\u0073),
    then backslash-newlines, quotes and backslashes removed, so a word split by
    quotes or spelled in escapes (`secr''ets`, `$'\\x73ecrets'`) reads whole."""
    text = ANSI_STRING.sub(lambda m: shell.ansi_c(m.group(1)), text).replace('$"', '"')
    text = re.sub(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*", "", text)  # `sec${x}rets`
    text = PARAMETER_OPERATOR.sub(" ", text)
    text = re.sub(r"\\x([0-9A-Fa-f]{1,2})|\\u([0-9A-Fa-f]{1,4})", lambda m: chr(int(m.group(1) or m.group(2), 16)), text)
    text = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8) & 0xFF), text)
    return re.sub(r"['\"\\]", "", text.replace("\\\n", ""))


def mentions(text):
    return bool(MENTION.search(text) or MENTION.search(plain(text)))


def gcloud_readings(args):
    """The first three command words of every way gcloud could read args (a
    flag it doesn't know, with no `=`, before a word may or may not take that
    word as its value), or None past MAX_STATES. Each word is (text, expanded)."""
    frontier, results, count = {0: {()}}, set(), 0
    for i in range(len(args) + 1):
        states = frontier.pop(i, None)
        if not states:
            continue
        count += len(states)
        if count > MAX_STATES:
            return None
        if i == len(args) or args[i] == "--":
            results |= states
            continue
        arg = args[i]
        nxt = args[i + 1] if i + 1 < len(args) else None
        if arg.startswith("-") and arg != "-":
            switch = arg in GCLOUD_SWITCHES or arg.startswith("--no-") or "=" in arg
            if switch or nxt is None or nxt.startswith("-"):
                frontier.setdefault(i + 1, set()).update(states)
            elif arg in GCLOUD_VALUE_FLAGS:
                frontier.setdefault(i + 2, set()).update(states)
            else:  # taking the value skips the word; not taking it leaves the word to count
                frontier.setdefault(i + 2, set()).update(states)
                frontier.setdefault(i + 1, set()).update(states)
            continue
        # 2: an expansion that is most likely a flag's value (right after an unknown flag) or
        # the caller's arguments (`"$@"` in a wrapper function); 1: any other expansion.
        maybe = isinstance(arg, Expanded) and (
            str(arg) in ("$@", "${@}", "$*", "${*}") or (i > 0 and args[i - 1].startswith("--") and "=" not in args[i - 1])
        )
        word = (str(arg), 2 if maybe else 1 if isinstance(arg, Expanded) else 0)
        moved = set()
        for state in states:
            if not state and word in (("alpha", 0), ("beta", 0)):
                moved.add(state)
            elif len(state) < 3 and not (state and state[0] != ("secrets", 0)):
                moved.add(state + (word,))
            else:
                moved.add(state)
        frontier.setdefault(i + 1, set()).update(moved)
    return [list(state) for state in results]


def gcloud_reason(args, mentioned, fed=False, later=False):
    """fed: gcloud runs under xargs or parallel, which add words from stdin or a file.
    later: gcloud is a later word of another program's argv, and may be data."""
    if any(a in ("--help", "-h") for a in args):
        return None
    readings = gcloud_readings(args)
    if readings is None:
        return UNSURE if mentioned else None
    for words in readings:
        if not words:
            # Bare gcloud: under xargs or parallel its command words come from stdin or a file.
            if fed and mentioned:
                return UNSURE
            continue
        if words[0][1]:
            if mentioned:
                return UNSURE  # `gcloud $(cat args)`, `s=secrets; gcloud $s versions …`
            continue

        if words[0][0] != "secrets":
            continue
        texts = [text for text, _ in words[1:3]]
        if later and not (texts[:1] and texts[0] in SECRET_VERBS or texts[:1] == ["versions"] and texts[1:2] and texts[1] in SECRET_VERBS):
            continue
        if texts in ([], ["versions"]):
            # No verb: gcloud prints help. Under xargs or parallel the verb may come from stdin.
            if fed and mentioned:
                return UNSURE
            continue
        texts = [text for text, _ in words[1:3]]
        if not any(texts[:len(read)] == read for read in GCLOUD_READS):
            return GCLOUD
    return None


def dynamic_program(args):
    """For a program that is a variable or expansion: True when what follows
    could make it a Secret Manager command (`$g secrets …`, `$g $verb`, or
    nothing at all, as in `$cmd`)."""
    if not args:
        return True  # `$cmd`
    readings = gcloud_readings(args)
    if readings is None:
        return True
    # A path (`$V $S/run.py`) is never a gcloud command group.
    return any(words and ((words[0][1] and "/" not in words[0][0]) or words[0][0] == "secrets") for words in readings)


def shell_command(args):
    """(string, script) for a shell's arguments: the -c string, or the script it runs."""
    i, run_string = 0, False
    while i < len(args):
        arg = args[i]
        if arg == "--":
            i += 1
            break
        if arg in ("--rcfile", "--init-file"):
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
    """The string `env -S '…'` (or --split-string) splits into a command, if any,
    wherever env sits among the wrappers (`timeout 5 env -S …`, `env env -S …`)."""
    for i, word in enumerate(argv):
        if os.path.basename(word) != "env":
            continue
        k = i + 1
        while k < len(argv) and (argv[k].startswith("-") or ASSIGNMENT.match(argv[k])):
            option = argv[k]
            if option in ("-u", "--unset", "-C", "--chdir"):
                k += 2
                continue
            if option.startswith("--split-string="):
                return option.split("=", 1)[1]
            if option in ("-S", "--split-string"):
                return argv[k + 1] if k + 1 < len(argv) else None
            if option.startswith("-S"):
                return option[2:]
            k += 1
    return None


def unwrap(argv):
    """program(), also past `coproc cmd` and `coproc NAME { cmd; }`."""
    argv = program(argv)
    while argv and (argv[0] in ("coproc", "function") or ARRAY_ASSIGNMENT.match(argv[0])):
        if argv[0] == "function":  # `function NAME { cmd; }`
            argv = program(argv[2:])
        elif argv[0] == "coproc":
            argv = program(argv[2:] if len(argv) > 2 and argv[2] == "{" else argv[1:])
        else:  # `ROW[key]=value` and `x+=1` are assignments too
            argv = program(argv[1:])
    return argv


def placeholders(argv):
    """argv with the words xargs, find or parallel will replace marked Expanded."""
    names = [os.path.basename(w) for w in argv]
    marks = set()
    if "xargs" in names:
        args = argv[names.index("xargs") + 1:]
        for k, option in enumerate(args):
            if option == "-I" and k + 1 < len(args):
                marks.add(str(args[k + 1]))
            elif option.startswith("-I") and len(option) > 2:
                marks.add(option[2:])
            elif option in ("-i", "--replace"):
                marks.add("{}")
            elif option.startswith(("-i", "--replace=")):
                marks.add(option.split("=", 1)[1] if "=" in option else option[2:])
            elif option in shell.RUNNERS["xargs"]:
                continue
            elif not option.startswith("-") and not (k > 0 and args[k - 1] in shell.RUNNERS["xargs"]):
                break
    general = "find" in names or "parallel" in names
    out = []
    for w in argv:
        # The replaced word reads as an expansion, here and inside a `sh -c '{}'` string.
        text = PLACEHOLDER.sub("$OH_PLACEHOLDER", w) if general else w
        for m in marks:
            if m:
                text = text.replace(m, "$OH_PLACEHOLDER")
        out.append(Expanded(text) if text != w or isinstance(w, Expanded) else w)
    return out


def argv_reason(argv, cwd, depth, mentioned, nested=True):
    argv = placeholders(argv)
    fed = any(os.path.basename(w) in ("xargs", "parallel") for w in argv)
    string = split_string(argv)
    if string is not None:
        return reason_for(string, cwd, depth + 1, mentioned)
    argv = unwrap(argv)
    if not argv:
        return None
    name = os.path.basename(argv[0])
    args = argv[1:]
    known = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", str(argv[0])) if isinstance(argv[0], Expanded) else None
    if known and known.group(1) in STATE["vars"] and "$" not in STATE["vars"][known.group(1)]:
        # `G=/path/to/gcloud; $G secrets …`, `GS="gcloud secrets"; $GS versions …`: read what it holds.
        return argv_reason(STATE["vars"][known.group(1)].split() + list(args), cwd, depth + 1, mentioned, nested)
    callers = ("$@", "${@}", "$*", "${*}")  # `run() { "$@"; }`: the call site is read anyway
    if mentioned and (isinstance(argv[0], Expanded) or argv[0] == "") and str(argv[0]) not in callers and dynamic_program(args):
        return UNSURE  # `$g secrets …`, `$(echo gcloud) secrets …`, `{gcloud,} secrets …`
    if name in LOOKUPS and not (name == "hash" and "-p" in args):
        return None
    if name == "gcloud":
        why = gcloud_reason(args, mentioned, fed, later=not nested)
        if why:
            return why
    why = first_reason(argv, name, args, cwd, depth, mentioned, fed)
    if why or not nested:
        return why
    # A program run by another one: `find -exec gcloud …`, `parallel gcloud …`, `setsid bash -c …`.
    # A later word may be data (`grep -e gcloud $f`), so an unsure reading counts only under
    # a program known to run its later words.
    for j in range(1, len(argv)):
        if os.path.basename(argv[j]) in NESTED and not isinstance(argv[j], Expanded):
            why = argv_reason(argv[j:], cwd, depth + 1, mentioned, nested=False)
            if why and (why != UNSURE or name in RUNS_LATER):
                return why
    return None


def resolve(word, cwd):
    """The path a word names, with `~` and literal variables from this command expanded,
    or None when it holds an expansion the guard can't follow."""
    text = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)",
                  lambda m: STATE["vars"].get(m.group(1) or m.group(2), m.group(0)), str(word))
    if "$" in text or "`" in text:
        return None
    path = pathlib.Path(os.path.expanduser(text))
    return str(path if path.is_absolute() else pathlib.Path(cwd) / path)


def script_reason(script, cwd, depth, mentioned):
    """A file a shell is told to run, whatever its name: one this command writes from a
    heredoc is read from the heredoc; one that isn't there counts as unsure."""
    path = resolve(script, cwd)
    if path is None or path == "/dev/null":
        return None  # a path built at run time isn't followed
    if path in STATE["heredoc_files"]:
        return reason_for(STATE["heredoc_files"][path], str(pathlib.Path(path).parent), depth + 1, mentioned)
    _, text = shell.read_script(path, cwd)
    if text is None:
        return UNSURE if mentioned else None
    return reason_for(text, str(pathlib.Path(path).parent), depth + 1, mentioned)


def first_reason(argv, name, args, cwd, depth, mentioned, fed=False):
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
            if os.path.basename(script) in NESTED and not isinstance(script, Expanded):
                # `bash /path/to/gcloud secrets …` runs gcloud's wrapper with these arguments.
                return argv_reason(args[args.index(script):], cwd, depth + 1, mentioned)
            return script_reason(script, cwd, depth, mentioned)
        return None
    if name in ("source", ".") and args:
        return script_reason(args[0], cwd, depth, mentioned)
    if name in STRING_RUNNERS:
        string = string_runner(name, args)
        if string is not None:
            return reason_for(string, cwd, depth + 1, mentioned)
    if "/" in argv[0] and (resolve(argv[0], cwd) or "") in STATE["heredoc_files"]:
        return script_reason(argv[0], cwd, depth, mentioned)  # `cat > run <<EOF … EOF; ./run`
    if "/" in argv[0] and name not in NESTED | {"kubeseal"}:  # not gcloud's own wrapper script
        path, text = shell_script(resolve(argv[0], cwd) or argv[0], cwd)
        if not text:
            # An executable text file with no #! line runs as a shell script too.
            path, text = shell.read_script(resolve(argv[0], cwd) or argv[0], cwd)
            if text is not None and (text.startswith("#!") or "\0" in text[:1024] or not os.access(path, os.X_OK)):
                text = None
        if text:
            return reason_for(text, str(path.parent), depth + 1, mentioned)
    if name == "eval":
        return reason_for(" ".join(args), cwd, depth + 1, mentioned)
    if name == "trap":
        action = next((a for a in args if not a.startswith("-")), None)
        return reason_for(action, cwd, depth + 1, mentioned) if action else None
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
    if name in NETWORK:
        if any(SECRET_API.search(arg) for arg in args):
            return API
        # `curl ".../v1/$NAME:access"`, `for u in …; do curl "$u"`, `… | xargs curl`: the URL is
        # built at run time; unsure when the command mentions Secret Manager.
        if SECRET_HOST.search(STATE["text"]) and (any(isinstance(a, Expanded) and not a.startswith("-") for a in args) or fed):
            return UNSURE
        return None
    return None


def innermost(text):
    """The text after the deepest command substitution still open at the end of text
    (`git commit -m "$(cat ` gives `cat `), or text itself."""
    try:
        shell.lex_exact(text)
    except shell.Unparsed as error:
        deepest = None
        while error is not None:
            if error.kind == "subst":
                deepest = error
            error = error.inner
        if deepest is not None:
            return innermost(text[deepest.start:])
    return text


def code_string(before):
    """True when the heredoc sits in a substitution whose text becomes code:
    `bash -c "$(cat <<'EOF'`, `eval "$(cat <<'EOF'`, `ssh host "$(cat <<'EOF'`."""
    inner = innermost(before)
    if inner == before:
        return False
    outer = before[:len(before) - len(inner)]
    marks = []
    try:
        shell.lex_exact(outer, marks)
    except shell.Unparsed:
        pass
    words = [m[3] for m in marks if m[0] == "word"]
    run = unwrap(words)
    if not run:
        return False
    name = os.path.basename(run[0])
    return name in ("eval", "ssh") or (name in SHELLS and any(re.fullmatch(r"-[a-z]*c[a-z]*", w) for w in run[1:]))


def heredoc_reason(header, start, end, body, cwd, depth, mentioned, cwds=()):
    """A heredoc counts when a shell runs it or it becomes a shell script (`*.sh`). One
    written to any file is remembered, so a later `bash run` or `./run` reads its body."""
    before, after = innermost(header[:start]), header[end:]
    commands = exact_commands(re.sub(r"\d*>>?\s*\S+", " ", before))[0] or [[]]
    argv = unwrap(commands[-1])
    name = os.path.basename(argv[0]) if argv else ""
    # `bash <<EOF`, or the heredoc piped on into a shell: `cat <<EOF | bash`, `| ssh vm bash`.
    later = [unwrap(c) for c in exact_commands(re.sub(r"\d*>>?\s*\S+", " ", after))[0]]
    runners = SHELLS | {"ssh", "source", "."}
    if (name in runners or any(c and os.path.basename(c[0]) in runners for c in later)
            or any(os.path.basename(w) in SHELLS for w in argv[1:]) or code_string(header[:start])):
        return reason_for(body, cwd, depth + 1, mentioned)
    if name in ("cat", "tee"):
        if name == "tee":
            written = next((a for a in argv[1:] if not a.startswith("-")), "")
        else:
            target = exact_pipes(innermost(header[:start]) + " " + header[end:])[0]
            written = next((t for _, redirects, _ in target for op, t in redirects if ">" in op), "")
        for here in {cwd, *cwds}:
            path = resolve(written, here) if written else None
            if path:
                STATE["heredoc_files"][path] = body
        if pathlib.Path(str(written)).suffix in SHELL_SUFFIXES:
            return reason_for(body, cwd, depth + 1, mentioned)
    return None


def stdin_shell(stages):
    """True when a shell reads its commands from stdin that isn't a heredoc:
    `… | bash`, `bash -s`, `bash <<< '…'`, `bash < file`, and `… | parallel`
    with no command of its own."""
    previous = None
    for argv, redirects, end in stages:
        run = unwrap(argv)
        if run and os.path.basename(run[0]) == "parallel" and not any(not a.startswith("-") for a in run[1:]):
            return True
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
    main, docs, placed = place_heredocs(text)
    commands, substs, lexed = exact_commands(main)
    stages = exact_pipes(main)[0]
    # Read for certain, the words say what bash sees (comments and data heredocs aren't words);
    # otherwise the raw text is all there is.
    mentioned = mentioned or (
        any(mentions(word) for argv in commands for word in argv) or any(mentions(inner) for inner in substs)
        or any(mentions(target) for _, redirects, _ in stages for _, target in redirects)
        if placed and lexed else mentions(text)
    )
    if mentioned and not (placed and lexed):
        return UNSURE
    # Literal assignments and literal `cd`s, so a script path in this command resolves.
    cwds = []
    for argv in commands:
        for word in argv:
            if ASSIGNMENT.match(word) and not isinstance(word, Expanded):
                key, value = word.split("=", 1)
                STATE["vars"][key] = os.path.expanduser(value)
        run = unwrap(argv)
        if run and run[0] == "cd" and len(run) > 1:
            target = resolve(run[1], cwds[-1] if cwds else cwd)
            if target:
                cwds.append(target)
    for header, start, end, body, quoted in docs:
        why = heredoc_reason(header, start, end, body, cwd, depth, mentioned, cwds)
        if why:
            return why
        if not quoted:
            # An unquoted heredoc's body is expanded: its substitutions run, whoever reads it.
            try:
                spans = shell._inner_substs(body, 0, len(body), quoted=True)
            except shell.Unparsed:
                if mentioned or mentions(body):
                    return UNSURE
                spans = []
            for inner_start, inner_end in spans:
                why = reason_for(body[inner_start:inner_end], cwd, depth + 1, mentioned)
                if why:
                    return why
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
    for argv, redirects, _ in stages:
        run = unwrap(argv)
        if run and os.path.basename(run[0]) in ("echo", "printf"):
            # `echo '…' > run.sh; bash run.sh`: what it writes is what a later shell runs.
            for op, target in redirects:
                path = resolve(target, cwd) if ">" in op else None
                if path:
                    args = [str(a) for a in run[1:]]
                    printf = os.path.basename(run[0]) == "printf" and args and "%" in args[0]
                    STATE["heredoc_files"][path] = "\n".join(args[1:]) if printf else " ".join(args)
    here = cwd
    for argv in commands:
        run = unwrap(argv)
        if run and run[0] == "cd" and len(run) > 1:
            here = resolve(run[1], here) or here
        why = argv_reason(argv, here, depth, mentioned)
        if why:
            return why
    # A file a shell reads its commands from: `bash < script`, `cat script | bash`.
    here, read = cwd, set()
    for k, (argv, redirects, end) in enumerate(stages):
        run = unwrap(argv)
        if not run:
            continue
        if run[0] == "cd" and len(run) > 1:
            here = resolve(run[1], here) or here
        files = []
        if os.path.basename(run[0]) in SHELLS and shell_command(run[1:]) == (None, None):
            for op, target in redirects:
                if op == "<<<":  # `bash -s <<< '…'`: the string is the script
                    why = reason_for(target, here, depth + 1, mentioned)
                    if why:
                        return why
            files = [t for op, t in redirects if op == "<" and t not in (shell.HEREDOC_PLACEHOLDER, "/dev/null")]
        nxt = unwrap(stages[k + 1][0]) if end == "|" and k + 1 < len(stages) else None
        if os.path.basename(run[0]) == "cat" and nxt and os.path.basename(nxt[0]) in SHELLS and shell_command(nxt[1:]) == (None, None):
            files = [a for a in run[1:] if not a.startswith("-")]
        for name in files:
            why = script_reason(name, here, depth, mentioned)
            if why:
                return why
            read.add(k if os.path.basename(run[0]) in SHELLS else k + 1)
    if mentioned and stdin_shell([s for k, s in enumerate(stages) if k not in read]):
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
    text = command_text(event.get("tool_input"))
    STATE.update(vars={}, heredoc_files={}, text=text)
    why = reason_for(text, cwd)
    if not why:
        return None
    return message_for(why)


def message_for(why):
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


def timed_out(signum, frame):
    raise TimeoutError(f"took over {TIME_LIMIT} seconds")


def main():
    raw = sys.stdin.read()
    try:
        signal.signal(signal.SIGALRM, timed_out)
        signal.alarm(TIME_LIMIT)
        message = decide(json.loads(raw))
        signal.alarm(0)
    except Exception as error:
        signal.alarm(0)
        # Fail open, but say so; fail closed when the text mentions Secret Manager.
        print(f"waxseal-guard: skipped ({type(error).__name__}: {error})", file=sys.stderr)
        try:
            text = command_text(json.loads(raw).get("tool_input"))
        except Exception:
            text = raw
        message = message_for(UNSURE) if isinstance(text, str) and mentions(text) else None
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
