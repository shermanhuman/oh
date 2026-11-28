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
  a script named by its literal path from the event's directory (`bash x.sh`,
  `source x.sh`, `./x.sh`, `bash < x.sh`; its commands read from that directory
  and from its own), a heredoc this command writes and then runs by the same
  spelling, or a command substitution;
- a Secret Manager URL (global, regional or `.mtls` host) handed to
  curl/wget/http/xh, directly or through a variable set in the same command;
- `kubeseal` (Sealed Secrets is retired), the same ways.

It reads the text the way bash does (`shell.lex_exact`, `place_heredocs`), so
operators, fd numbers, CR, quoting, `$'…'`, arithmetic and heredocs can't hide
a command by accident. Where it still can't be sure (the text doesn't lex, a
heredoc doesn't end the way bash would end it, the text is too long or nested
too deep, the program or gcloud's command group is a variable or expansion, a
shell reads commands from stdin or a process substitution, an alias is defined,
a script it runs was written with `>` or `>>` by a command whose own words
mention Secret Manager (`echo 'gcloud secrets …' > run.sh`), a script it runs
is too long or can't be read, or the guard itself fails or runs past its 5 s
deadline), it refuses the text if it mentions Secret Manager (`MENTION`) and
lets it through otherwise.

Not covered, by design: a command deliberately disguised to get past the guard
(agents are trusted, board item 392); a script the guard can't find at its
literal path: one reached through a `cd`, a variable or loop path, or one the
command makes some other way than a heredoc (`cp`, `curl -o`), even when the
command mentions Secret Manager (board item 396); interpreter code (Python,
Node, Go ...) using a Secret Manager client; a `PATH` shim, the user's aliases and functions,
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
# Per decision, what the command itself sets up: every literal value assigned to a name (read
# for a variable program and a URL, never for a script path), and every heredoc it writes to a
# file, keyed by the target as spelled and as a literal path from the event's directory. A
# script is read from each candidate, the disk included, and any that refuses refuses the command.
# `redirected`: files written with `>` or `>>` by a command whose own words mention Secret Manager
# (`echo 'gcloud secrets …' >> run.sh`), which the guard doesn't read; one of those run is unsure.
STATE = {"vars": {}, "written": {}, "host": False, "redirected": set()}
MAX_CANDIDATES = 64  # past this a variable's readings count as unsure


class Deadline(BaseException):
    """The guard ran past TIME_LIMIT. Not an OSError or Exception, so no file read swallows it."""
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
        if arg in ("--", "-"):  # bash and sh read `-` as `--`: `bash -` reads stdin, `bash - x.sh` runs x.sh
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
    if isinstance(argv[0], Expanded) and any(k in STATE["written"] for k in keys(argv[0], cwd)):
        return script_reason(argv[0], cwd, depth, mentioned)  # `f=$(mktemp); cat > "$f" <<EOF …; "$f"`
    known = re.fullmatch(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", str(argv[0])) if isinstance(argv[0], Expanded) else None
    values = STATE["vars"].get(known.group(1), []) if known else []
    if values:
        # `G=/path/to/gcloud; $G secrets …`, `GS="gcloud secrets"; $GS versions …`: read each value it's given.
        for value in [v for v in values if "$" not in v and "`" not in v]:
            why = argv_reason(value.split() + list(args), cwd, depth + 1, mentioned, nested)
            if why:
                return why
        if all("$" not in v and "`" not in v for v in values):
            return None
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
            why = argv_reason(argv[j:], cwd, depth + 1, mentioned, nested=name in RUNS_LATER)
            if why and (why != UNSURE or name in RUNS_LATER):
                return why
    return None


def spelled(word):
    """A word's spelling with `${NAME}` written as `$NAME`, so `${f}` and `$f` are one key."""
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}(?![A-Za-z0-9_])", r"$\1", str(word))


def expand(word):
    """(every other text a URL word may become from the literal values this command assigns,
    whether the list was cut)."""
    texts, cut = [str(word)], False
    for _ in range(4):
        grown = []
        for text in texts:
            m = re.search(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]*\])?\}|\$([A-Za-z_][A-Za-z0-9_]*)", text)
            values = STATE["vars"].get(m.group(1) or m.group(2)) if m else None
            grown += [text[:m.start()] + v + text[m.end():] for v in values] if values else [text]
        grown = list(dict.fromkeys(grown))
        cut = cut or len(grown) > MAX_CANDIDATES
        texts = grown[:MAX_CANDIDATES]
    return [t for t in texts if t != str(word)], cut


def resolve(word, cwd):
    """The literal path a word names from the event's directory (`~` expanded), or None when
    it holds an expansion. The guard doesn't follow `cd`s or variables into a path (item 396)."""
    text = str(word)
    if "$" in text or "`" in text:
        return None
    return os.path.normpath(os.path.join(cwd, os.path.expanduser(text)))


def keys(word, cwd):
    """What this command may have written a script under: its spelling and its literal path."""
    path = resolve(word, cwd)
    return [spelled(word)] + ([path] if path else [])


def write(target, body, cwd):
    """Remember a heredoc this command writes to target."""
    for key in keys(target, cwd):
        STATE["written"].setdefault(key, []).append(body)


def script_reason(script, cwd, depth, mentioned):
    """A file a shell is told to run, whatever its name: what this command wrote to it, and
    what's on disk at its literal path, read from the caller's directory (where its commands
    run) and from its own (where a `cd "$(dirname "$0")"` takes them). A script the guard can't
    find is a known gap (item 396); one a mention-bearing command wrote with `>` is unsure."""
    if str(script) == "/dev/null":
        return None
    if re.match(r"[<>]\(|/dev/(stdin|fd/)|/proc/self/fd/", str(script)):
        # `bash <(…)`, `source /dev/stdin <<< …`: the script is another command's output, as for a
        # shell reading stdin; unsure under a mention.
        return UNSURE if mentioned else None
    path = resolve(script, cwd)
    # A file is judged on what it says: the command's own mention doesn't make a `.bashrc` unsure.
    readings = [(cwd, body) for key in keys(script, cwd) for body in STATE["written"].get(key, [])]
    if path:
        _, text = shell.read_script(path, cwd)
        if text is not None:
            readings += [(cwd, text), (os.path.dirname(path), text)]
        elif mentioned and not absent(path):
            return UNSURE  # there, but too long or unreadable: a script the guard can't read, not a gap
    if mentioned and any(k in STATE["redirected"] for k in keys(script, cwd)):
        return UNSURE
    for here, text in dict.fromkeys(readings):
        why = reason_for(text, here, depth + 1)
        if why:
            return why
    return None


def absent(path):
    """True when nothing is at path. A directory the guard can't search isn't absent: it can't tell."""
    try:
        os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return True
    except OSError:
        return False
    return False


def unread_script(path):
    """True for a file run directly that looks like a script (a shell suffix, a `#!` line naming a
    shell, or executable text with no `#!`) but that the readers skipped: too long or unreadable."""
    if absent(path) or os.path.isdir(path):
        return False
    try:
        if os.path.getsize(path) <= MAX_TEXT and os.access(path, os.R_OK):
            return False  # read in full above: not a script, or a binary
        with open(path, "rb") as f:
            head = f.read(1024)
    except OSError:
        return True  # can't read even its first line: a script for all the guard knows
    first = head.split(b"\n", 1)[0]
    if pathlib.Path(path).suffix in SHELL_SUFFIXES or (first.startswith(b"#!") and re.search(rb"\b(ba|z|da|k)?sh\b", first)):
        return True
    return not first.startswith(b"#!") and b"\0" not in head and os.access(path, os.X_OK)


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
    if any(k in STATE["written"] for k in keys(argv[0], cwd)):
        return script_reason(argv[0], cwd, depth, mentioned)  # `cat > run <<EOF … EOF; ./run`, disk too
    if "/" in argv[0] and name not in NESTED | {"kubeseal"}:  # not gcloud's own wrapper script
        candidate = resolve(argv[0], cwd) or str(argv[0])
        if mentioned and any(k in STATE["redirected"] for k in keys(argv[0], cwd)):
            return UNSURE  # `echo '…' > run.sh; ./run.sh`: a script other output went into
        path, text = shell_script(candidate, cwd)
        if not text:
            # An executable text file with no #! line runs as a shell script too.
            path, text = shell.read_script(candidate, cwd)
            if text is not None and (text.startswith("#!") or "\0" in text[:1024] or not os.access(path, os.X_OK)):
                text = None
        if text:
            for here in dict.fromkeys([cwd, str(path.parent)]):
                why = reason_for(text, here, depth + 1)
                if why:
                    return why
        elif mentioned and unread_script(candidate):
            return UNSURE  # a script too long or unreadable to read; a binary still passes
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
        readings = [expand(arg) for arg in args]
        if any(SECRET_API.search(text) for arg, (texts, _) in zip(args, readings) for text in [str(arg), *texts]):
            return API
        # `curl ".../v1/$NAME:access"`, `for u in …; do curl "$u"`, `… | xargs curl`: the URL is
        # built at run time from something that names the Secret Manager host, or the readings
        # were cut in a command that mentions Secret Manager; unsure.
        host_values = any(SECRET_HOST.search(v) for values in STATE["vars"].values() for v in values)
        built = any(isinstance(a, Expanded) and not a.startswith("-")
                    and (SECRET_HOST.search(a) or host_values or (cut and mentioned))
                    for a, (_, cut) in zip(args, readings))
        if built or (fed and STATE["host"]):
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
    if outer.endswith("$("):
        outer = innermost(outer[:-2])  # `out=$(ssh host "$(cat <<'EOF'`: the command holding the `$(`
    marks = []
    try:
        shell.lex_exact(outer, marks)
    except shell.Unparsed:
        pass
    separators = {";", "&&", "||", "|", "|&", "&", "\n", "(", ";;"}
    last = max([m[1] for m in marks if m[0] == "op" and m[2] in separators], default=-1)
    words = [m[3] for m in marks if m[0] == "word" and m[1] > last]  # the command holding the `$(`
    run = unwrap(words)
    if not run:
        return False
    name = os.path.basename(run[0])
    return name in ("eval", "ssh") or (name in SHELLS and any(re.fullmatch(r"-[a-z]*c[a-z]*", w) for w in run[1:]))


def heredoc_reason(header, start, end, body, cwd, depth, mentioned):
    """A heredoc counts when a shell runs it or it becomes a shell script (`*.sh`). One
    written to any file is remembered, so a later `bash run` or `./run` reads its body."""
    before, after = innermost(header[:start]), header[end:]
    commands = exact_commands(before)[0] or [[]]
    argv = unwrap(commands[-1])
    name = os.path.basename(argv[0]) if argv else ""
    # `bash <<EOF`, or the heredoc piped on into a shell: `cat <<EOF | bash`, `| ssh vm bash`.
    later = [unwrap(c) for c in exact_commands(after)[0]]
    runners = SHELLS | {"ssh", "source", "."}
    if (name in runners or any(c and os.path.basename(c[0]) in runners for c in later)
            or any(os.path.basename(w) in SHELLS for w in argv[1:]) or code_string(header[:start])):
        return reason_for(body, cwd, depth + 1, mentioned)
    for stage in later:
        if stage and os.path.basename(stage[0]) == "tee":  # `cat <<'EOF' | tee run.sh`
            for target in [a for a in stage[1:] if not a.startswith("-")]:
                write(target, body, cwd)
    if name in ("cat", "tee"):
        if name == "tee":
            targets = [a for a in argv[1:] if not a.startswith("-")][:1]
        else:
            # Every file a `>` on the heredoc's line sends output to (`| sort > run.sh`, `{ cat <<EOF; } > run.sh`),
            # not an earlier line's: the header now starts where nothing was left open.
            stages = exact_pipes(before)[0]
            lines = [k for k, (_, _, end) in enumerate(stages) if end == "\n"]
            stages = stages[lines[-1] + 1:] if lines else stages
            targets = [t for _, redirects, _ in stages + exact_pipes(after)[0] for op, t in redirects if ">" in op]
        for written in targets:
            write(written, body, cwd)
        if any(pathlib.Path(str(t)).suffix in SHELL_SUFFIXES for t in targets):
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
    # Literal assignments, for a variable program or URL in this command.
    STATE["host"] = STATE["host"] or bool(SECRET_HOST.search(text))
    for argv in commands:
        for word in argv:
            if ASSIGNMENT.match(word):
                key, value = word.split("=", 1)
                STATE["vars"].setdefault(key, []).append(os.path.expanduser(value))
        if len(argv) > 2 and argv[0] == "for" and argv[2] == "in":  # `for u in A B; do curl "$u"`
            STATE["vars"].setdefault(str(argv[1]), []).extend(str(w) for w in argv[3:])
    for argv, redirects, _ in stages:
        # Judged on what's written: `echo 'export …' >> ~/.bashrc; …; ls secrets` isn't unsure.
        if any(mentions(w) for w in argv) and not any(target == shell.HEREDOC_PLACEHOLDER for op, target in redirects):
            for op, target in redirects:
                if ">" in op and not op.startswith(">&") and target != "/dev/null":
                    STATE["redirected"].update(keys(target, cwd))
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
    # A file a shell reads its commands from: `bash < script`, `cat script | bash`.
    here, read = cwd, set()
    for k, (argv, redirects, end) in enumerate(stages):
        run = unwrap(argv)
        if not run:
            continue
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
    STATE.update(vars={}, written={}, host=False, redirected=set())
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
        message += " If this command doesn't touch a secret value, write it more plainly and run it again: no variable or substitution as the program or as gcloud's command group, no unclosed quotes, heredocs that end on their own line, no shell reading commands from a pipe, a here-string or a process substitution, no alias, no `-c`/`eval` string built at run time, and a script that's already on disk rather than one the command writes with echo."
    return message


def timed_out(signum, frame):
    raise Deadline(f"took over {TIME_LIMIT} seconds")


def main():
    raw = sys.stdin.read()
    try:
        signal.signal(signal.SIGALRM, timed_out)
        signal.alarm(TIME_LIMIT)
        message = decide(json.loads(raw))
        signal.alarm(0)
    except (Exception, Deadline) as error:
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
