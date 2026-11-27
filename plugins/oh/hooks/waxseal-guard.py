"""PreToolUse guard: agents never read or write a Secret Manager value.

Secret values live in Google Secret Manager (project `waxseal-infra-secrets`)
and reach the cluster through External Secrets Operator; the user writes them
in the console (breakdown-infra's `.claude/rules/secrets.md`). A backstop for
that rule: it looks at what a shell would execute, never at what a program
does with its own arguments. Three layers:

1. **Reading the command** the way bash does (`shell.lex_exact`,
   `place_heredocs`): any `gcloud secrets` verb other than list, describe,
   get-iam-policy, versions list|describe and locations, wherever it runs
   (wrappers, `bash -c`/`su -c`/`env -S`/`eval`/`trap` strings, substitutions,
   heredocs and scripts a shell runs); a gcloud whose command group isn't
   written out (`gcloud $(cat args)`, `xargs gcloud`); a Secret Manager URL
   (the `.mtls` and regional hosts too) handed to curl/wget/http/xh.
2. **The backstop** (`BACKSTOP`): any command whose whole text, heredoc bodies
   included, read as written and with quotes and escapes taken out, names a
   value read or write (`secrets … versions … access|add`, `secrets … create …
   --data-file`, `…/versions/…:access`, `:addVersion`, the gRPC methods).
   Prose that quotes those goes through a file (`--body-file`, `-F`).
3. **Failing closed** (`UNSURE`) when the command mentions Secret Manager
   (`MENTION`: in its words, a heredoc body, or a file it names) and the guard
   can't see the code that will run: text that doesn't lex or a heredoc that
   doesn't end the way bash would end it; a variable or expansion as the
   program followed by `secrets`, another expansion or nothing; code from a
   pipe, a substitution, a variable, a process substitution or /dev/fd
   (`… | bash`, `bash -c "$c"`, `eval "$(…)"`, `bash <(…)`); a heredoc read by
   a program not known to treat it as data; a script run in a command where
   something else may write it first; an alias; the guard's own failure or a
   5 s deadline. Lists of known programs (`DATA_PROGRAMS`, `READ_ONLY`,
   `INTERPRETERS`) name the safe side: anything unlisted counts as running or
   writing code.

Not covered: a verb assembled at run time when nothing mentions Secret Manager
(`$a$b versions $v`), since any per-command hook would need to run the code
to see it; a `PATH` shim, the user's aliases and functions, login profiles,
`$BASH_ENV`, a persisted `gcloud config set core/log_http true`; interpreter
code using a client library without naming the method. kubeseal (Sealed
Secrets is retired) is refused best-effort, where a shell plainly runs it.

Reads the hook event on stdin (Claude Code and Codex send the same shape for
the Bash tool) and prints a deny decision, or nothing to let the call through.
On anything unexpected it fails open, with a note on stderr, unless the text
mentions Secret Manager: a broken guard must not stop every command. Inside
waxseal's and oh's own source trees only kubeseal is exempt.
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
NESTED = SHELLS | {"gcloud", "eval"}
# Programs whose later words are data, never a command they run (`grep -e gcloud $f`). Under
# any other program a later `gcloud`, shell or variable may be what it runs.
DATA_PROGRAMS = {
    "echo", "printf", "grep", "egrep", "fgrep", "rg", "ag", "ack", "git", "gh", "sed", "awk", "jq", "yq",
    "cat", "head", "tail", "less", "more", "wc", "sort", "uniq", "cut", "tr", "ls", "test", "[", "[[",
    "which", "type", "man", "diff", "comm", "column", "kubectl", "tee", "basename", "dirname", "realpath",
}
# Interpreters read a heredoc body as their own language, not shell: it's data to the shell
# reading (the backstop still reads it).
INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "php", "lua", "Rscript", "deno", "bun", "jq", "psql", "sqlite3", "mysql"}
# Programs that neither write files nor run commands. A command that runs a script and has
# anything else in it (or a `>` redirect) may change the script before it runs.
READ_ONLY = {
    "cd", "pwd", "ls", "cat", "grep", "egrep", "fgrep", "rg", "head", "tail", "wc", "echo", "printf",
    "test", "[", "[[", "true", "false", ":", "which", "type", "command", "export", "set", "sleep", "date",
    "stat", "file", "basename", "dirname", "realpath", "id", "uname", "hostname", "whoami",
}

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
GCLOUD_READS = (["list"], ["describe"], ["get-iam-policy"], ["versions", "list"], ["versions", "describe"], ["locations"])
# A value read or write named in the text the shell runs, however the guard reads the rest of it.
BACKSTOP = re.compile(
    r"\bsecrets\b[^\n]{0,120}?\bversions\b[^\n]{0,120}?\b(?:access|add)\b"
    r"|\bsecrets\b[^\n]{0,120}?\bcreate\b[^\n]*?--data-file"
    r"|/versions/[^\s'\"]{0,200}(?::|%3A)access\b|(?::|%3A)addVersion\b"
    r"|SecretManagerService/(?:Access|Add)SecretVersion\b"
)
MAX_STATES = 2000
DEPTH = 4
# Per decision: whether files the command names mention Secret Manager, and whether
# anything in it may write a file (so a script it runs may not be what's on disk now).
CONTEXT = {"file_mention": False, "writers": 0}
TIME_LIMIT = 5  # seconds; the hook's own timeout is 10, and a killed guard lets the command run

KUBESEAL = "runs kubeseal"
GCLOUD = "changes or reads Secret Manager with gcloud"
API = "calls the Secret Manager API directly"
UNSURE = "mentions Secret Manager in a form the guard can't read for certain"
NAMED = "names a Secret Manager value read or write"
UNWRITTEN = "runs gcloud with a command group that isn't written out"


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


def gcloud_reason(args, mentioned, fed=False):
    """fed: gcloud runs under xargs or parallel, which add words from stdin or a file."""
    readings = gcloud_readings(args)
    if readings is None:
        return UNWRITTEN
    for words in readings:
        if not words:
            # Bare gcloud: under xargs or parallel its command words come from stdin or a file.
            if fed:
                return UNWRITTEN
            continue
        if words[0][1] == 2:
            if mentioned:
                return UNSURE
            continue
        if words[0][1]:
            return UNWRITTEN  # `gcloud $(cat args)`, `gcloud ${x#/} versions …` (board item 383)

        if words[0][0] != "secrets":
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
    while argv and (argv[0] == "coproc" or ARRAY_ASSIGNMENT.match(argv[0])):
        if argv[0] == "coproc":
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
        if not isinstance(w, Expanded) and ((general and PLACEHOLDER.search(w)) or any(m and m in w for m in marks)):
            w = Expanded(w)
        out.append(w)
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
    if mentioned and (isinstance(argv[0], Expanded) or argv[0] == "") and dynamic_program(args):
        return UNSURE  # `$g secrets …`, `$(echo gcloud) secrets …`, `{gcloud,} secrets …`
    if name in LOOKUPS and not (name == "hash" and "-p" in args):
        return None
    if name == "gcloud":
        why = gcloud_reason(args, mentioned, fed)
        if why:
            return why
    why = first_reason(argv, name, args, cwd, depth, mentioned)
    if why or not nested:
        return why
    # A program run by another one: `find -exec gcloud …`, `parallel gcloud …`, `setsid bash -c …`.
    # Any program not known to treat its later words as data may run them.
    runner = name not in DATA_PROGRAMS
    for j in range(1, len(argv)):
        word = argv[j]
        if isinstance(word, Expanded):
            if runner and mentioned and j + 1 < len(argv) and argv[j + 1] == "secrets":
                return UNSURE  # `setsid $g secrets …`
            continue
        if os.path.basename(word) in NESTED:
            why = argv_reason(argv[j:], cwd, depth + 1, mentioned, nested=False)
            if why and (runner or why not in (UNSURE, UNWRITTEN)):
                return why
    return None


def binary(name, cwd):
    """True for an existing compiled program (not a script anyone could have just written)."""
    path = pathlib.Path(os.path.expanduser(str(name)))
    path = path if path.is_absolute() else pathlib.Path(cwd) / path
    try:
        with open(path, "rb") as handle:
            head = handle.read(1024)
    except OSError:
        return False
    return head.startswith((b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")) or b"\0" in head


def writer(run):
    """True when this command may write a file: anything not known to be read-only."""
    return bool(run) and os.path.basename(run[0]) not in READ_ONLY | SHELLS | {"source", "."}


def script_reason(script, cwd, depth, mentioned):
    """A file a shell is told to run, whatever its name; one it can't read, or one in a
    command that may write files first (so what's on disk now may not be what runs),
    counts as unsure."""
    if CONTEXT["writers"]:
        return UNSURE if mentioned else None
    path, text = shell.read_script(script, cwd)
    if text is None:
        return UNSURE if mentioned and str(script) != "/dev/null" else None
    return reason_for(text, str(path.parent), depth + 1, mentioned)


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
            if isinstance(string, Expanded) and mentioned:
                return UNSURE  # `bash -c "$c"`, `bash -c "$(cat < f)"`: code the guard can't see
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
            if isinstance(string, Expanded) and mentioned:
                return UNSURE
            return reason_for(string, cwd, depth + 1, mentioned)
    if "/" in argv[0]:
        # Another command in this text may write the file first (the program itself doesn't count).
        known = isinstance(argv[0], Expanded) and name in INTERPRETERS | DATA_PROGRAMS | READ_ONLY  # `$V/bin/python`
        if mentioned and CONTEXT["writers"] - writer(argv) > 0 and not known and not binary(argv[0], cwd):
            return UNSURE  # `cat > run <<EOF … EOF; ./run`: what runs may not be on disk yet
        path, text = shell_script(argv[0], cwd)
        if not text:
            # An executable text file with no #! line runs as a shell script too.
            path, text = shell.read_script(argv[0], cwd)
            if text is not None and (text.startswith("#!") or "\0" in text[:1024] or not os.access(path, os.X_OK)):
                text = None
        if text:
            return reason_for(text, str(path.parent), depth + 1, mentioned)
    if name == "eval":
        if mentioned and any(isinstance(a, Expanded) for a in args):
            return UNSURE  # `eval "$(…)"`, `eval "$l"`
        return reason_for(" ".join(args), cwd, depth + 1, mentioned)
    if name == "trap":
        action = next((a for a in args if not a.startswith("-")), None)
        if action is not None and isinstance(action, Expanded) and mentioned:
            return UNSURE
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
        return API if any(SECRET_API.search(arg) for arg in args) else None
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


def heredoc_reason(header, start, end, body, cwd, depth, mentioned):
    """A heredoc body is data only when a program known to treat it as data reads it (cat,
    tee, grep, git, an interpreter, ...); under any other reader (`bash`, `setsid bash`,
    `{ bash; }`, `ssh vm`, `xargs gcloud`) it's read as shell, as is one written to a script."""
    before, after = innermost(header[:start]), header[end:]
    commands = exact_commands(re.sub(r"\d*>>?\s*\S+", " ", before))[0] or [[]]
    argv = unwrap(commands[-1])
    name = os.path.basename(argv[0]) if argv else ""
    # The body piped on into another program: `cat <<EOF | bash`, `| ssh vm bash`.
    later = [unwrap(c) for c in exact_commands(re.sub(r"\d*>>?\s*\S+", " ", after))[0]]
    data = DATA_PROGRAMS | INTERPRETERS
    # A variable as the reader (`$V - <<EOF`) is judged as a program by `dynamic_program`.
    unknown = name not in data and not (argv and isinstance(argv[0], Expanded))
    if unknown or any(c and os.path.basename(c[0]) not in data and not isinstance(c[0], Expanded) for c in later):
        why = reason_for(body, cwd, depth + 1, mentioned)
        shells = SHELLS | {"ssh"}
        if why == KUBESEAL and name not in shells and not any(c and os.path.basename(c[0]) in shells for c in later):
            return None  # kubeseal stays refused only where a shell plainly runs the body
        return why
    if name in ("cat", "tee"):
        target = re.search(r">>?\s*(\S+)", header)
        written = target.group(1) if target else next((a for a in argv[1:] if not a.startswith("-")), "")
        if pathlib.Path(written.strip("'\"")).suffix in SHELL_SUFFIXES:
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
    # The whole text, heredoc bodies included: whichever program ends up reading a body,
    # a value read or write spelled out anywhere in it is refused (board item 383).
    if BACKSTOP.search(text) or BACKSTOP.search(plain(text)):
        return NAMED
    main, docs, placed = place_heredocs(text)
    commands, substs, lexed = exact_commands(main)
    stages = exact_pipes(main)[0]
    for argv, redirects, _ in stages:
        if any(">" in op for op, _ in redirects) or writer(unwrap(argv)):
            CONTEXT["writers"] += 1
    # Read for certain, the words say what bash sees (comments aren't words); otherwise the
    # raw text is all there is. Heredoc bodies count, since some program may run them, and
    # so do files the command names.
    mentioned = mentioned or CONTEXT["file_mention"] or any(mentions(doc[3]) for doc in docs) or (
        any(mentions(word) for argv in commands for word in argv) or any(mentions(inner) for inner in substs)
        or any(mentions(target) for _, redirects, _ in stages for _, target in redirects)
        if placed and lexed else mentions(text)
    )
    if mentioned and not (placed and lexed):
        return UNSURE
    for header, start, end, body, quoted in docs:
        why = heredoc_reason(header, start, end, body, cwd, depth, mentioned)
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
    for argv in commands:
        why = argv_reason(argv, cwd, depth, mentioned)
        if why:
            return why
    if mentioned and stdin_shell(stages):
        return UNSURE
    return None


def named_files_mention(text, cwd, limit=40, budget=2_000_000):
    """True when a file the command names (any word that is an existing file) mentions
    Secret Manager: `head f | bash` runs what's in f, which the text never shows."""
    seen = set()
    for word in re.findall(r"[^\s'\"<>|;&()`$=]+", text):
        if word in seen or len(seen) >= limit or word.startswith("-"):
            continue
        seen.add(word)
        path = pathlib.Path(os.path.expanduser(word))
        path = path if path.is_absolute() else pathlib.Path(cwd) / path
        try:
            if not path.is_file() or path.stat().st_size > MAX_TEXT or budget <= 0:
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        budget -= len(content)
        if mentions(content):
            return True
    return False


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
    text = command_text(event.get("tool_input"))
    CONTEXT.update(file_mention=named_files_mention(text, cwd), writers=0)
    why = reason_for(text, cwd)
    # Only kubeseal is exempt in waxseal's and oh's own trees: anyone can make such a tree,
    # so the Secret Manager checks apply everywhere (board item 383).
    if not why or (why == KUBESEAL and exempt(cwd)):
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
    if why == UNWRITTEN:
        message += " Write gcloud's command group out literally (`gcloud compute …`)."
    if why == NAMED:
        message += " If you're only writing about it (a commit message, a PR comment), write the text to a file with the Write tool and pass the file (`--body-file`, `-F`)."
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
