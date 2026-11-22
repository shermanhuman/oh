"""PreToolUse guard: kill one specific process at a time; never print secret files.

A backstop for oh's always-on *Secrets* and *Processes* rules, looking only at
what a shell would execute:

- **Kills.** Several sessions share the machine, so killing by name or pattern
  stops other sessions' runs too. Refuses `pkill` and `killall` (any form), and
  a `kill` that is fed by a process lookup (`pgrep`, `pidof`, `lsof`, `fuser`
  or `ps` in its own substitution, in the pipe feeding it through `xargs`, or
  in the variable it names, followed through assignments, `for` and
  `while read`), that targets a process group or every process (`kill 0`,
  `kill -9 -123`, `kill -- -$PGID`), or that names more than one target. One
  PID, `$!`, `%job`, a pidfile read or a variable not filled from a lookup
  passes, with any signal; so do `kill -0` and `kill -l`.
- **Secret files.** A redaction filter can fail open and put a secret in the
  transcript. Refuses printing commands (cat, head, tail, less, sed, awk,
  base64, xxd, ...) on credentials and private keys: `.env*` (not examples),
  `.netrc`, `.git-credentials`, `.pgpass`, `.npmrc`, `.dev.vars`,
  `mise.local.toml`, `credentials*`, `*.key`, private `*.pem` (not
  certificates), `id_*` and other keys in `~/.ssh`, `*.p12`/`*.pfx`,
  kubeconfigs, `*.tfstate`, hand-off files such as `~/.app-key`, and anything
  under `~/.config/mapleset-forge/`. Certificates, sealed-secret manifests and
  `.waxseal/` metadata are not secret. `grep` passes when it can't print
  values (`-c`, `-l`, `-q`, or, on key-value files such as `.env`, `-o` with
  an anchored pattern of `A-Z`, `0-9` and `_` classes that ends in `=`, such as
  `^[A-Z_][A-Z0-9_]*=`, and no flag beyond `-o`, `-E`, `-h`, `-H`, `-n` or `-N`;
  it prints names, plus at most a short all-capitals line before `=` padding,
  such as base32 or a key's last few base64 characters); `sed -i` and `sort -o` pass because they don't print values. `cut`
  doesn't pass: it prints a line with no delimiter whole, such as a multi-line
  key's body.

Interpreter code, text inside double-quoted substitutions and commands run on
other machines over ssh aren't inspected. Reads the hook event on stdin and
prints a deny decision, or nothing. Fails open on anything unexpected, with a
note on stderr and exit status 1 so the host shows it.
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
PRINTERS = {"cat", "head", "tail", "less", "more", "bat", "batcat", "nl", "tac", "strings", "xxd", "od",
            "hexdump", "base64", "sed", "awk", "gawk", "cut", "sort", "uniq", "column", "paste", "fold", "rev"}
GREPS = {"grep", "egrep", "rg"}
SECRET_NAME = re.compile(
    r"^(\.env(\..+)?|\.netrc|_netrc|\.git-credentials|\.pgpass|\.npmrc|\.dev\.vars|\.?mise\.local\.toml|"
    r"credentials.*|id_(rsa|dsa|ecdsa|ed25519)\w*|kubeconfig.*|.*\.(key|p12|pfx|jks|keystore|tfstate)|"
    r".*[-_]key|.*\.pem)$",
    re.I,
)
NOT_SECRET = re.compile(r"^\.env\.(example|sample|template|dist)$|\.pub$|sealed", re.I)
CERTIFICATE = re.compile(r"(^|[-_.])(cert|crt|chain|fullchain|ca)([-_.]|$)", re.I)
PRIVATE = re.compile(r"priv|key", re.I)
PUBLIC = re.compile(r"(^|[-_.])pub(lic)?([-_.]|$)", re.I)
SOURCE_OR_DOC = re.compile(r"\.(exs?|rb|go|tsx?|jsx?|mjs|cjs|py|rs|java|kt|swift|c|h|cpp|md|mdx|rst|html|heex|erb|vue|svelte|css|scss)$", re.I)
KEY_VALUE_FILE = re.compile(r"^(\.env(\..+)?|\.?mise\.local\.toml|\.dev\.vars|\.npmrc|\.pgpass|\.netrc|credentials.*)$", re.I)
VALUE_OPTIONS = {
    "grep": {"-m", "-A", "-B", "-C", "-d", "-D", "--include", "--exclude", "--exclude-dir", "--max-count", "--context",
             "--after-context", "--before-context", "--label", "--binary-files"},
    "rg": {"-m", "-A", "-B", "-C", "-g", "-t", "-T", "-j", "-M", "-E", "-r", "-d", "--glob", "--iglob", "--type", "--type-not",
           "--threads", "--max-columns", "--encoding", "--replace", "--max-count", "--context", "--after-context",
           "--before-context", "--color", "--colors", "--sort", "--sortr", "--max-depth", "--type-add"},
    "sed": {"-l", "--line-length"},
    "awk": {"-v", "-F", "--assign", "--field-separator"},
}
VALUE_OPTIONS["egrep"] = VALUE_OPTIONS["grep"]
VALUE_OPTIONS["gawk"] = VALUE_OPTIONS["awk"]
SSH_PUBLIC = re.compile(r"^(known_hosts|config|authorized_keys)([.\-_].*)?$")
SECRET_DIRS = ("/.config/mapleset-forge",)
KILL = "kills by name or pattern, or more than one process; kill one specific PID you started (`pgrep -fa <name>` shows them)"
PRINT = "prints a file that holds secrets; list key names instead (`grep -oE '^[A-Z_][A-Z0-9_]*=' FILE` on an env file, `grep -c NAME FILE`)"


class Skipped(Exception):
    pass


def secret_path(arg, cwd):
    if not arg or arg.startswith("-") or "=" in arg:
        return False
    home = os.path.expanduser("~")
    raw = os.path.expanduser(arg.strip("'\"").replace("${HOME}", home).replace("$HOME", home))
    full = os.path.normpath(raw if os.path.isabs(raw) else os.path.join(cwd, raw))
    if "/.waxseal/" in full + "/":
        return False
    if any(full == os.path.expanduser("~") + d or full.startswith(os.path.expanduser("~") + d + "/") for d in SECRET_DIRS):
        return True
    name = os.path.basename(full)
    if os.path.dirname(full).endswith("/.kube") and name.startswith("config"):
        return True
    if os.path.dirname(full) == os.path.expanduser("~/.ssh"):
        return not (SSH_PUBLIC.match(name) or name.endswith(".pub"))
    if not SECRET_NAME.match(name) or NOT_SECRET.search(name):
        return False
    if re.search(r"\.(pem|crt|cer)$", name, re.I) and CERTIFICATE.search(name) and not PRIVATE.search(name):
        return False  # a certificate; never a .key, .p12 or .pfx
    if re.search(r"\.(pem|key)$", name, re.I) and PUBLIC.search(name) and not re.search(r"priv", name, re.I):
        return False  # a public key
    if re.match(r"(credentials|kubeconfig)", name, re.I) and SOURCE_OR_DOC.search(name):
        return False  # code or docs about credentials
    return True


def operands(name, args):
    """The file arguments of a printer or grep: its pattern or script is not a file."""
    positional, skip, explicit = [], False, False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if name in GREPS | {"sed", "awk", "gawk"}:
            if a in ("-e", "-f", "--regexp", "--file", "--expression"):
                explicit, skip = True, True
                continue
            if re.match(r"--(regexp|file|expression)=", a):
                explicit = True
                continue
            if a in VALUE_OPTIONS.get(name, ()):
                skip = True
                continue
        if not a.startswith("-") or a == "-":
            positional.append(a)
    if name in GREPS | {"sed", "awk", "gawk"} and not explicit and positional:
        positional = positional[1:]
    return positional


ONLY_MATCHING_SHORT = set("oEhHnN")
ONLY_MATCHING_LONG = {"--only-matching", "--extended-regexp", "--no-filename", "--with-filename", "--line-number",
                      "--no-line-number"}


def grep_prints(name, args):
    flags = [a for a in args if re.fullmatch(r"-[A-Za-z]+", a)]
    safe = "clq" + ("L" if name != "rg" else "")
    if any(set(f[1:]) & set(safe) for f in flags) or any(a in ("--count", "--files-with-matches", "--quiet", "--silent") for a in args):
        return False
    if any("o" in f[1:] for f in flags) or "--only-matching" in args:
        # One exact shape: -o with a names-only pattern and nothing else that
        # changes what prints (-i, -v, context, --passthru, a second -e all do).
        for a in args:
            if a.startswith("--"):
                if a not in ONLY_MATCHING_LONG:
                    return True
            elif a.startswith("-") and len(a) > 1 and set(a[1:]) - ONLY_MATCHING_SHORT:
                return True
        pattern = next((a for a in args if not a.startswith("-")), "")
        # Names only: classes of A-Z, 0-9 and _ up to a literal `=`. Lowercase and
        # base64 characters stay out, so a value line can't match.
        return not re.fullmatch(r"\^(\[(A-Z|0-9|_)+\][*+]?)+( \*)?=", pattern)
    return True


LOOKUP = re.compile(r"(^|[\s;|&(`$/])(pgrep|pidof|lsof|fuser|ps)\b")
KILL_VALUE_OPTIONS = {"-s", "-n", "--signal"}
ONE_TARGET = re.compile(r"^(\d+|\$!|%(\w+|[+%-])|\$\d|\$[A-Za-z_]\w*|\$\{[A-Za-z_]\w*\}|)$")
DECLARERS = {"local", "export", "declare", "readonly", "typeset"}


def is_lookup(word, substs=(), tainted=()):
    """A process lookup, or a variable already filled from one."""
    if LOOKUP.search(word) or any(LOOKUP.search(sub) for sub in substs):
        return True
    return any(name in tainted for text in (word, *substs) for name in re.findall(r"\$\{?([A-Za-z_]\w*)", text))


def kill_commands(text):
    """Each simple command as a list of (word, substitutions inside it), with the
    operator that ends it. Unlike `shell.simple_commands`, a substitution stays
    attached to the word it sits in, so a lookup is matched to its own kill."""
    try:
        chunks = [shell.lex(text)]
    except shell.Unparsed:
        chunks = []
        for line in text.split("\n"):
            try:
                chunks.append(shell.lex(line))
            except shell.Unparsed:
                pass
    out = []
    for chunk in chunks:
        words, pending, redirect = [], [], False
        for kind, value in chunk:
            if kind == "subst":
                pending.append(value)
            elif kind == "op" and set(value) & set("<>"):
                if words and re.fullmatch(r"\d", words[-1][0]) and not words[-1][1]:
                    words.pop()  # the file descriptor of `2>/dev/null`
                redirect = True
            elif kind == "op":
                out.append((words, value))
                words, pending, redirect = [], [], False
            elif redirect:
                redirect, pending = False, []
            else:
                words.append((value, pending))
                pending = []
        out.append((words, None))
    return [(words, end) for words, end in out if words]


def kill_target_reason(args, fed_by_lookup, tainted):
    """Why this kill's arguments break the one-process rule, or None."""
    targets, signal_seen, i = [], False, 0
    while i < len(args):
        word, substs = args[i]
        if word in ("-l", "-L", "--list", "--help") and not targets:
            return None
        if word == "--":
            targets.extend(args[i + 1:])
            break
        if not signal_seen and not targets and word in KILL_VALUE_OPTIONS:
            if i + 1 < len(args) and args[i + 1][0] == "0":
                return None  # kill -s 0: a liveness check
            signal_seen, i = True, i + 2
            continue
        variable_signal = re.fullmatch(r"-\$\{?[A-Za-z_]\w*\}?", word) and i + 1 < len(args)
        if not signal_seen and not targets and not substs and (re.fullmatch(r"-[A-Za-z0-9+]+|--signal=\S+", word) or variable_signal):
            if word in ("-0", "--signal=0"):
                return None
            signal_seen, i = True, i + 1
            continue
        targets.append(args[i])
        i += 1
    if not targets:
        return KILL if fed_by_lookup else None  # `pgrep … | xargs kill`
    if len(targets) > 1:
        return KILL
    word, substs = targets[0]
    if word.startswith("-") or word == "0" or not ONE_TARGET.match(word.strip("\"'")) and "$(" not in word:
        return KILL
    if is_lookup(word, substs, tainted) or (word == "" and not substs):
        return KILL
    var = re.fullmatch(r"\$\{?([A-Za-z_]\w*)\}?", word)
    if var and var.group(1) in tainted:
        return KILL
    return None


def kill_reason(text):
    """Walk the commands in order: refuse a kill fed by a process lookup (its own
    substitution, the pipe feeding it, or a variable filled from a lookup), a
    group or all-process target, or more than one target."""
    tainted, pipeline_lookup = set(), False
    for words, end in kill_commands(text):
        plain = [w for w, _ in words]
        run = shell.program(plain)
        offset = len(words) - len(run)
        for word, substs in words[:offset]:
            name = word.split("=", 1)[0]
            if shell.ASSIGNMENT.match(word):
                (tainted.add if is_lookup(word.split("=", 1)[1], substs, tainted) else tainted.discard)(name)
        if run:
            name, args = os.path.basename(run[0]), words[offset + 1:]
            if name in DECLARERS:
                for word, substs in args:
                    if shell.ASSIGNMENT.match(word):
                        (tainted.add if is_lookup(word.split("=", 1)[1], substs, tainted) else tainted.discard)(word.split("=", 1)[0])
            elif name == "for" and len(args) >= 2 and args[1][0] == "in":
                if any(is_lookup(w, subs, tainted) for w, subs in args[2:]):
                    tainted.add(args[0][0])
            elif name == "read" and pipeline_lookup:
                tainted.update(w for w, _ in args if re.fullmatch(r"[A-Za-z_]\w*", w))
            elif name == "kill":
                why = kill_target_reason(args, pipeline_lookup, tainted)
                if why:
                    return why
        this_lookup = is_lookup(" ".join(plain), [x for _, subs in words for x in subs], tainted)
        pipeline_lookup = (pipeline_lookup or this_lookup) if end in ("|", "|&") else False
    return None


def argv_reason(argv, redirects, cwd, depth):
    run = shell.program(argv)
    if not run:
        return None
    name, args = os.path.basename(run[0]), run[1:]
    if redirects and args and re.fullmatch(r"\d", args[-1]):
        args = args[:-1]  # the file descriptor of `2>/dev/null`, not an argument
    if name in ("pkill", "killall"):
        return None if args and all(a in ("--help", "-V", "--version", "-l", "--list") for a in args) else KILL
    if name in shell.SHELLS:
        for i, flag in enumerate(args):
            if re.fullmatch(r"-[a-z]*c[a-z]*", flag) and i + 1 < len(args):
                return reason_for(args[i + 1], cwd, depth + 1)
        return None
    if name in ("eval", "watch"):
        return reason_for(" ".join(a for a in args if not a.startswith("-")), cwd, depth + 1)
    if name == "ssh":
        return None  # another machine's files and processes
    if name == "sed" and any(re.fullmatch(r"-[A-Za-z]*i\S*", a) or a.startswith("--in-place") for a in args):
        return None
    if name == "sort" and any(a == "-o" or a.startswith("--output") for a in args):
        return None
    files = [a for a in operands(name, args) if secret_path(a, cwd)]
    files += [target for op, target in redirects if op == "<" and secret_path(target, cwd)]
    if not files:
        return None
    if name in PRINTERS:
        return PRINT
    if name in GREPS and (grep_prints(name, args) or not all(KEY_VALUE_FILE.match(os.path.basename(f)) for f in files)
                          and any(re.fullmatch(r"-[A-Za-z]*o[A-Za-z]*", a) or a == "--only-matching" for a in args)):
        return PRINT
    return None


def heredoc_shell(header):
    """True when a heredoc on this header line is run by a shell: `bash <<EOF`, `cat <<EOF | sh`."""
    before, _, after = header.partition("<<")
    first = shell.piped_commands(before)[-1:] if before.strip() else []
    names = [os.path.basename(shell.program(argv)[0]) for argv, _, _ in first if shell.program(argv)]
    later = [os.path.basename(shell.program(argv)[0]) for argv, _, _ in shell.piped_commands(after.split(None, 1)[1] if len(after.split(None, 1)) > 1 else "") if shell.program(argv)]
    return bool(set(names + later) & shell.SHELLS)


def reason_for(text, cwd, depth=0):
    if not text:
        return None
    if depth > DEPTH or len(text) > shell.MAX_TEXT:
        raise Skipped("too long or too deeply nested to read")
    main, docs = shell.split_heredocs(text)
    for header, body in docs:
        if heredoc_shell(header):
            why = reason_for(body, cwd, depth + 1)
            if why:
                return why
    _, substs = shell.simple_commands(main)
    for inner in substs:
        why = reason_for(inner, cwd, depth + 1)
        if why:
            return why
    why = kill_reason(main)
    if why:
        return why
    for argv, redirects, _ in shell.piped_commands(main):
        why = argv_reason(argv, redirects, cwd, depth)
        if why:
            return why
    return None


def decide(event):
    if not isinstance(event, dict):
        return None
    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    why = reason_for(shell.command_text(event.get("tool_input")), cwd)
    return f"Blocked by oh: this command {why}." if why else None


def main():
    try:
        message = decide(json.load(sys.stdin))
    except Exception as error:  # fail open, but say so where the host shows it
        print(f"process-secrets-guard: skipped ({type(error).__name__}: {error})", file=sys.stderr)
        sys.exit(1)
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
