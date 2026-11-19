"""PreToolUse guard: kill one specific process at a time; never print secret files.

A backstop for oh's *Process and secrets guard* rule, looking only at what a
shell would execute:

- **Kills.** Several sessions share the machine, so killing by name or pattern
  stops other sessions' runs too. Refuses `pkill` and `killall` (any form),
  `kill` fed by a process lookup (`$(pgrep …)`, `pgrep … | xargs kill`, a
  variable filled from `pgrep`/`pidof`/`lsof`), a process-group or all-process
  target (`kill -- -123`, `kill 0`, `kill -1`), and `kill` with more than one
  target. `kill` with one literal PID, `$!`, `%job` or a variable not filled
  from a lookup passes, and so does `kill -0` and `kill -l`.
- **Secret files.** A redaction filter can fail open and put a secret in the
  transcript. Refuses printing commands (cat, head, tail, less, sed, awk,
  base64, xxd, ...) on credentials and private keys: `.env*` (not examples),
  `.netrc`, `.git-credentials`, `.pgpass`, `.npmrc`, `.dev.vars`,
  `mise.local.toml`, `credentials*`, `*.key`, private `*.pem` (not
  certificates), `id_*` and other keys in `~/.ssh`, `*.p12`/`*.pfx`,
  kubeconfigs, `*.tfstate`, hand-off files such as `~/.app-key`, and anything
  under `~/.config/mapleset-forge/`. Certificates, sealed-secret manifests and
  `.waxseal/` metadata are not secret. `grep` passes when it can't print
  values (`-c`, `-l`, `-q`, or `-o` with an anchored `^[...]*` pattern);
  `sed -i`, `sort -o` and `cut -f1` pass because they don't print values.

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
LOOKUPS = {"pgrep", "pidof", "lsof"}
PRINTERS = {"cat", "head", "tail", "less", "more", "bat", "batcat", "nl", "tac", "strings", "xxd", "od",
            "hexdump", "base64", "sed", "awk", "gawk", "cut", "sort", "uniq", "column", "paste", "fold", "rev"}
GREPS = {"grep", "egrep", "rg"}
SECRET_NAME = re.compile(
    r"^(\.env(\..+)?|\.netrc|_netrc|\.git-credentials|\.pgpass|\.npmrc|\.dev\.vars|\.?mise\.local\.toml|"
    r"credentials.*|id_(rsa|dsa|ecdsa|ed25519)\w*|kubeconfig.*|.*\.(key|p12|pfx|jks|keystore|tfstate)|"
    r".*[-_]key|.*\.pem)$",
    re.I,
)
NOT_SECRET = re.compile(r"^\.env\.(example|sample|template|dist)$|\.pub$|sealed|(^|[-_.])(cert|crt|chain|fullchain|ca|public)([-_.]|$)", re.I)
SSH_PUBLIC = re.compile(r"^(known_hosts|config|authorized_keys)([.\-_].*)?$")
SECRET_DIRS = ("/.config/mapleset-forge",)
KILL = "kills by name or pattern, or more than one process; kill one specific PID you started (`pgrep -fa <name>` shows them)"
PRINT = "prints a file that holds secrets; list key names instead (`grep -o '^[A-Za-z_]*' FILE`, `grep -c NAME FILE`)"
GROUP_OR_ALL = re.compile(r"^(-\d+|0|-1)$")
ONE_TARGET = re.compile(r"^(\d+|\$!|%(\d+|[+-]|%)|\$[A-Za-z_]\w*|\$\{[A-Za-z_]\w*\})$")
SIGNAL_OPTIONS_WITH_VALUE = {"-s", "-n", "--signal"}


class Skipped(Exception):
    pass


def secret_path(arg, cwd):
    if not arg or arg.startswith("-") or "=" in arg:
        return False
    raw = os.path.expanduser(arg.strip("'\""))
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
    return bool(SECRET_NAME.match(name)) and not NOT_SECRET.search(name)


def operands(name, args):
    """The file arguments of a printer or grep: its pattern or script is not a file."""
    positional, skip, explicit = [], False, False
    for i, a in enumerate(args):
        if skip:
            skip = False
            continue
        if a in ("-e", "-f", "--regexp", "--file", "--expression") or (name in ("awk", "gawk") and a == "-f"):
            explicit, skip = True, True
            continue
        if name in GREPS | {"sed", "awk", "gawk"} and a in ("-m", "-A", "-B", "-C", "-g", "-t", "--glob", "--type"):
            skip = True
            continue
        if not a.startswith("-") or a == "-":
            positional.append(a)
    if name in GREPS | {"sed", "awk", "gawk"} and not explicit and positional:
        positional = positional[1:]
    return positional


def grep_prints(name, args):
    flags = [a for a in args if re.fullmatch(r"-[A-Za-z]+", a)]
    safe = "clq" + ("L" if name != "rg" else "")
    if any(set(f[1:]) & set(safe) for f in flags) or any(a in ("--count", "--files-with-matches", "--quiet", "--silent") for a in args):
        return False
    if any("o" in f[1:] for f in flags) or "--only-matching" in args:
        pattern = next((a for a in args if not a.startswith("-")), "")
        return not re.fullmatch(r"\^\[[^\]]+\][*+]", pattern)
    return True


def kill_reason(args, lookup_seen):
    targets, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("-l", "-L", "--list", "--help"):
            return None
        if a == "--":
            targets.extend(args[i + 1:])
            break
        if a in SIGNAL_OPTIONS_WITH_VALUE:
            i += 2
            continue
        if a == "-0":
            return None
        if a.startswith("-") and not GROUP_OR_ALL.match(a):
            i += 1
            continue
        targets.append(a)
        i += 1
    if not targets:
        return KILL if lookup_seen else None  # `pgrep … | xargs kill`
    if len(targets) > 1 or any(GROUP_OR_ALL.match(t) for t in targets):
        return KILL
    if targets and not ONE_TARGET.match(targets[0]):
        return KILL
    if targets and targets[0].startswith("$") and targets[0] != "$!" and lookup_seen:
        return KILL
    return None


def argv_reason(argv, redirects, cwd, depth, lookup_seen):
    run = shell.program(argv)
    if not run:
        return None
    name, args = os.path.basename(run[0]), run[1:]
    if redirects and args and re.fullmatch(r"\d", args[-1]):
        args = args[:-1]  # the file descriptor of `2>/dev/null`, not an argument
    if name in ("pkill", "killall"):
        return None if args and all(a in ("--help", "-V", "--version", "-l", "--list") for a in args) else KILL
    if name == "kill":
        return kill_reason(args, lookup_seen)
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
    if name == "cut" and any(re.fullmatch(r"(-f|--fields=?)1", a) for a in args) and not any(re.fullmatch(r"-f\S*[,-]\S*", a) for a in args):
        return None
    files = [a for a in operands(name, args) if secret_path(a, cwd)]
    files += [target for op, target in redirects if op == "<" and secret_path(target, cwd)]
    if not files:
        return None
    if name in PRINTERS or (name in GREPS and grep_prints(name, args)):
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
    commands, substs = shell.simple_commands(main)
    names = {os.path.basename(shell.program(c)[0]) for c in commands if shell.program(c)}
    lookup_seen = bool(names & LOOKUPS) or any(re.search(r"(^|[\s;|&(])(pgrep|pidof|lsof)\b", s) for s in substs)
    for inner in substs:
        why = reason_for(inner, cwd, depth + 1)
        if why:
            return why
    if "kill" in names and any(re.search(r"(^|[\s;|&(])(pgrep|pidof|lsof|ps)\b", s) for s in substs):
        return KILL
    for argv, redirects, _ in shell.piped_commands(main):
        why = argv_reason(argv, redirects, cwd, depth, lookup_seen)
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
