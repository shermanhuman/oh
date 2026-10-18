"""PreToolUse guard: production actions that can't be undone.

A backstop for oh's always-on Production guard rule, deliberately narrow, so
the everyday release routine (rollout restarts, Argo refreshes, migration
Jobs, deploy scripts) never prompts. It looks only at what a shell would
execute, using the parser in shell.py.

Denied, because they are always the user's step:
- `gh pr merge`, `gh api` merging a pull request (REST PUT or a GraphQL
  merge/auto-merge mutation), `gh repo delete` and `gh api -X DELETE repos/o/r`;
- `git push` that forces (`--force`, `-f`, `--force-with-lease`, a `+refspec`),
  pushes every branch (`--mirror`, `--all`), or lands on the default branch
  (origin/HEAD, plus main and master).

Asked, so the user approves with one key:
- `kubectl delete`, `drain`, `cordon` and `scale --replicas=0`, and
  `helm uninstall`, on a kube context that isn't local (kind-*, k3d-*,
  minikube, docker-desktop, orbstack, rancher-desktop). A context the guard
  can't resolve counts as production. Dry runs pass.
- `psql` running DROP, TRUNCATE, ALTER TABLE ... DROP or DELETE without WHERE
  against a host that isn't local, or inside `kubectl exec` on a non-local
  context, or over ssh; SQL from -c, -f, a heredoc, `< file` or `cat file |`.

Codex can't ask from a hook (it logs the hook as failed and runs the command),
so there the asked cases are denied instead.

Not covered: interpreter code, a port-forwarded production database (it looks
like localhost), contexts or hosts named only through shell variables set
elsewhere. Fails open, with a note on stderr, on anything unexpected.
"""
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys


def load(name):
    """A sibling module, loaded by path: `python3 -I` leaves this directory off sys.path."""
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(f"oh_{name}", pathlib.Path(__file__).with_name(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shell = load("shell")
SHELLS, SSH_VALUE_OPTIONS, ASSIGNMENT, HEREDOC, MAX_TEXT = (
    shell.SHELLS, shell.SSH_VALUE_OPTIONS, shell.ASSIGNMENT, shell.HEREDOC, shell.MAX_TEXT
)
split_heredocs, simple_commands, program, shell_script, command_text = (
    shell.split_heredocs, shell.simple_commands, shell.program, shell.shell_script, shell.command_text
)

DENY, ASK = "deny", "ask"
DEPTH = 4
LOCAL_CONTEXT = re.compile(r"(kind|k3d)-.+|minikube|docker-desktop|orbstack|rancher-desktop")
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
DEFAULT_BRANCHES = {"main", "master"}
CURRENT_CONTEXT = re.compile(r"^current-context:\s*[\"']?([^\s\"']+)", re.M)

KUBECTL_VALUE_OPTIONS = {
    "-n", "--namespace", "--context", "--kubeconfig", "--cluster", "--user", "-s", "--server", "--token",
    "--as", "--as-group", "--as-uid", "--request-timeout", "--certificate-authority", "--client-certificate",
    "--client-key", "--tls-server-name", "--cache-dir", "--log-file", "--username", "--password",
}
HELM_VALUE_OPTIONS = {
    "-n", "--namespace", "--kube-context", "--kubeconfig", "--kube-apiserver", "--kube-as-user",
    "--kube-as-group", "--kube-token", "--kube-ca-file", "--repository-config", "--repository-cache",
    "--registry-config", "--burst-limit", "--qps",
}
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
PUSH_VALUE_OPTIONS = {"--repo", "-o", "--push-option", "--receive-pack", "--exec"}
GH_VALUE_OPTIONS = {"-R", "--repo"}
GH_API_VALUE_OPTIONS = {
    "-X", "--method", "-H", "--header", "-f", "--raw-field", "-F", "--field", "--input", "-q", "--jq",
    "-t", "--template", "--hostname", "-p", "--preview", "--cache",
}
PSQL_VALUE_OPTIONS = {
    "-c", "--command", "-d", "--dbname", "-f", "--file", "-h", "--host", "-p", "--port", "-U", "--username",
    "-v", "--set", "--variable", "-o", "--output", "-L", "--log-file", "-T", "--table-attr", "-F",
    "--field-separator", "-R", "--record-separator", "-P", "--pset",
}


class Where:
    """Where a command runs: its directory, whether it runs on another machine
    (over ssh or inside a production pod), and variables set earlier in the text."""

    def __init__(self, cwd, remote=False, env=None):
        self.cwd, self.remote, self.env = cwd, remote, dict(env or {})

    def but(self, cwd=None, remote=None, env=None):
        return Where(cwd or self.cwd, self.remote if remote is None else remote, self.env if env is None else env)


def options(args, *names):
    """Every value given to these options: `--x v`, `--x=v`, and `-xv` for short ones."""
    values = []
    for i, arg in enumerate(args):
        for name in names:
            if arg == name and i + 1 < len(args):
                values.append(args[i + 1])
            elif name.startswith("--") and arg.startswith(name + "="):
                values.append(arg[len(name) + 1:])
            elif not name.startswith("--") and arg.startswith(name) and len(arg) > len(name) and not arg.startswith("--"):
                values.append(arg[len(name):])
    return values


def option(args, *names):
    values = options(args, *names)
    return values[0] if values else None


def positionals(args, value_options):
    """Arguments that aren't options or option values."""
    out, i = [], 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            return out + args[i + 1:]
        if arg.startswith("-") and len(arg) > 1:
            i += 2 if arg in value_options else 1
        else:
            out.append(arg)
            i += 1
    return out


def assignments(argv):
    """Variables set in front of the command itself: `KUBECONFIG=x kubectl ...`."""
    run = program(argv)
    return dict(word.split("=", 1) for word in argv[:len(argv) - len(run)] if ASSIGNMENT.match(word))


def read(path, cwd):
    path = pathlib.Path(path).expanduser()
    if not path.is_absolute():
        path = pathlib.Path(cwd) / path
    try:
        if path.is_file() and path.stat().st_size <= MAX_TEXT:
            return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pass
    return None


def current_context(kubeconfig, env, cwd):
    """The current-context of the first file in a KUBECONFIG list that names one; None if unknown."""
    for entry in kubeconfig.split(":"):
        expanded = _expand(entry, env)
        if "$" in expanded:
            return None
        text = read(expanded, cwd)
        match = CURRENT_CONTEXT.search(text) if text else None
        if match:
            return match.group(1)
    return None


def _expand(value, env):
    return re.sub(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", lambda m: env.get(m.group(1), m.group(0)), value)


def kube_context(args, where, env, flag="--context"):
    named = option(args, flag)
    if named:
        return None if "$" in named else named
    if where.remote:
        return None
    merged = {**os.environ, **where.env, **env}
    kubeconfig = option(args, "--kubeconfig") or merged.get("KUBECONFIG") or "~/.kube/config"
    return current_context(kubeconfig, merged, where.cwd)


def is_local(context):
    return bool(context) and bool(LOCAL_CONTEXT.fullmatch(context))


def describe(context):
    return f"kube context `{context}`" if context else "a kube context the guard can't resolve, so it counts as production"


def verb_of(args, value_options):
    """The first word that isn't an option or an option's value, and its index."""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            i += 2 if arg in value_options else 1
        else:
            return arg, i
    return None, len(args)


def kubectl_finding(args, where, env):
    verb, i = verb_of(args, KUBECTL_VALUE_OPTIONS)
    rest = args[i + 1:]
    if any(arg.startswith("--dry-run") and arg != "--dry-run=none" for arg in rest):
        return None
    if verb in ("delete", "drain", "cordon"):
        action = verb
    elif verb == "scale" and option(rest, "--replicas") == "0":
        action = "scale to zero"
    else:
        return None
    context = kube_context(args, where, env)
    if is_local(context):
        return None
    return ASK, f"runs `kubectl {action}` on {describe(context)}"


def helm_finding(args, where, env):
    verb, i = verb_of(args, HELM_VALUE_OPTIONS)
    if verb not in ("uninstall", "delete", "del", "un") or "--dry-run" in args[i + 1:]:
        return None
    context = kube_context(args, where, env, flag="--kube-context")
    if is_local(context):
        return None
    return ASK, f"runs `helm uninstall` on {describe(context)}"


def git(repo, *args):
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def git_finding(args, where):
    repo, i = pathlib.Path(where.cwd), 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] == "-C" and i + 1 < len(args):
            repo = repo / args[i + 1]
        i += 2 if args[i] in GIT_VALUE_OPTIONS else 1
    if args[i:i + 1] != ["push"]:
        return None
    rest = args[i + 1:]
    flags = [arg for arg in rest if arg.startswith("-")]
    if any(
        arg in ("--force", "--force-with-lease") or arg.startswith("--force-with-lease=")
        or re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", arg)
        for arg in flags
    ):
        return DENY, "force-pushes"
    if any(arg in ("--mirror", "--all", "--branches") for arg in flags):
        return DENY, "pushes every branch"
    words = positionals(rest, PUSH_VALUE_OPTIONS)
    remote, refspecs = (words[0] if words else "origin"), words[1:]
    if any(spec.startswith("+") for spec in refspecs):
        return DENY, "force-pushes"
    defaults = set(DEFAULT_BRANCHES)
    targets = []
    if not where.remote:
        head = git(repo, "symbolic-ref", "-q", "--short", f"refs/remotes/{remote}/HEAD")
        if head:
            defaults.add(head.split("/", 1)[-1])
    for spec in refspecs or ["HEAD"]:
        source, colon, destination = spec.partition(":")
        target = destination if colon else source
        if target == "HEAD":
            if where.remote:
                continue
            target = git(repo, "symbolic-ref", "-q", "--short", "HEAD") or ""
            if not refspecs and git(repo, "config", "push.default") in ("upstream", "tracking"):
                upstream = git(repo, "rev-parse", "--abbrev-ref", "@{upstream}") or ""
                targets.append(upstream.split("/", 1)[-1])
        targets.append(target.removeprefix("refs/heads/"))
    hit = next((t for t in targets if t in defaults), None)
    return (DENY, f"pushes to the default branch `{hit}`") if hit else None


def gh_finding(args):
    words = positionals(args, GH_VALUE_OPTIONS | GH_API_VALUE_OPTIONS)
    if words[:2] == ["pr", "merge"]:
        return DENY, "merges a pull request"
    if words[:2] == ["repo", "delete"]:
        return DENY, "deletes a repository"
    if words[:1] != ["api"] or len(words) < 2:
        return None
    endpoint = words[1].lstrip("/")
    fields = options(args, "-f", "--raw-field", "-F", "--field")
    method = (option(args, "-X", "--method") or ("POST" if fields or "--input" in args else "GET")).upper()
    if re.fullmatch(r"repos/[^/]+/[^/]+/pulls/[^/]+/merge", endpoint) and method in ("PUT", "POST"):
        return DENY, "merges a pull request"
    if endpoint == "graphql" and any(re.search(r"\b(mergePullRequest|enablePullRequestAutoMerge)\b", f) for f in fields):
        return DENY, "merges a pull request"
    if method == "DELETE" and re.fullmatch(r"repos/[^/]+/[^/]+/?", endpoint):
        return DENY, "deletes a repository"
    return None


def remote_host(args, env):
    """True when psql's host, from flags, a connection string or PGHOST, isn't local."""
    hosts = options(args, "-h", "--host")
    for arg in args:
        uri = re.match(r"postgres(?:ql)?://(?:[^@/]*@)?([^/?]*)", arg)
        if uri:
            hosts.append(re.sub(r":\d+$", "", uri.group(1)) if not uri.group(1).startswith("[") else uri.group(1))
            hosts += re.findall(r"[?&]host=([^&]+)", arg)
        hosts += re.findall(r"(?:^|\s)host=(\S+)", arg)
    if not hosts and env.get("PGHOST"):
        hosts = [env["PGHOST"]]
    for value in hosts:
        for host in value.split(","):
            host = host.strip("[]")
            if "$" in host or not (host in LOCAL_HOSTS or host.startswith("/")):
                return True
    return False


def destructive(sql):
    """What makes this SQL irreversible, or None."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    sql = "\n".join(line for line in sql.split("\n") if not line.lstrip().startswith("\\"))
    sql = re.sub(r"--[^\n]*", " ", sql)
    for statement in sql.split(";"):
        s = " ".join(statement.split()).upper()
        start = re.match(r"(DROP|TRUNCATE)\b", s)
        if start:
            return start.group(1)
        if re.match(r"ALTER\s+TABLE\b", s) and re.search(r"\bDROP\s+(?!CONSTRAINT|DEFAULT|NOT\b|IDENTITY|EXPRESSION)\w", s):
            return "ALTER TABLE ... DROP"
        delete = re.search(r"\bDELETE\s+FROM\b", s)
        if delete and not re.search(r"\bWHERE\b", s[delete.end():]):
            return "DELETE without WHERE"
    return None


def sql_ask(sql):
    why = destructive(sql) if sql else None
    return (ASK, f"runs {why} against a database that isn't local") if why else None


def psql_findings(args, where, env):
    if not (where.remote or remote_host(args, {**os.environ, **where.env, **env})):
        return
    for sql in options(args, "-c", "--command"):
        yield sql_ask(sql)
    for path in options(args, "-f", "--file"):
        yield sql_ask(read(path, where.cwd)) if path != "-" else None


def sql_consumer(argv, where):
    """For a command that reads SQL on stdin: whether its database is remote. None otherwise."""
    env = assignments(argv)
    run = program(argv)
    if not run:
        return None
    name, args = os.path.basename(run[0]), run[1:]
    if name == "psql":
        return where.remote or remote_host(args, {**os.environ, **where.env, **env})
    if name == "kubectl" and "--" in args and verb_of(args, KUBECTL_VALUE_OPTIONS)[0] == "exec":
        cut = args.index("--")
        if sql_consumer(args[cut + 1:], where) is not None:
            return where.remote or not is_local(kube_context(args[:cut], where, env))
    if name == "ssh":
        inner = ssh_command(args)
        if inner and re.search(r"(^|[\s/])psql(\s|$)", inner):
            return True
    return None


def shell_consumer(argv, where):
    """For a command that runs a script from stdin: where that script runs. None otherwise."""
    env = assignments(argv)
    run = program(argv)
    if not run:
        return None
    name, args = os.path.basename(run[0]), run[1:]
    if name in SHELLS and not any(re.fullmatch(r"-[a-z]*c[a-z]*", a) for a in args):
        return where
    if name == "ssh":
        return where.but(remote=True)
    if name == "kubectl" and "--" in args and verb_of(args, KUBECTL_VALUE_OPTIONS)[0] == "exec":
        cut = args.index("--")
        if shell_consumer(args[cut + 1:], where) is not None:
            return where.but(remote=where.remote or not is_local(kube_context(args[:cut], where, env)))
    return None


def ssh_command(args):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if len(args[i]) == 2 and args[i][1] in SSH_VALUE_OPTIONS else 1
    return " ".join(args[i + 1:]) if i + 1 < len(args) else None


def argv_findings(argv, where, depth):
    env = assignments(argv)
    run = program(argv)
    if not run:
        return
    name, args = os.path.basename(run[0]), run[1:]
    if name in SHELLS:
        for i, flag in enumerate(args):
            if re.fullmatch(r"-[a-z]*c[a-z]*", flag) and i + 1 < len(args):
                yield from findings(args[i + 1], where, depth + 1)
                return
            if i > 0 and re.fullmatch(r"[-+][a-zA-Z]*[oO]", args[i - 1]):
                continue
            if not flag.startswith(("-", "+")):
                path, text = shell_script(flag, where.cwd)
                if text:
                    yield from findings(text, where.but(cwd=str(path.parent)), depth + 1)
                return
        return
    if "/" in run[0]:
        path, text = shell_script(run[0], where.cwd)
        if text:
            yield from findings(text, where.but(cwd=str(path.parent)), depth + 1)
            return
    if name == "eval":
        yield from findings(" ".join(args), where, depth + 1)
    elif name == "ssh":
        inner = ssh_command(args)
        if inner:
            yield from findings(inner, where.but(remote=True), depth + 1)
    elif name == "watch":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 2 if args[i] in ("-n", "--interval") else 1
        yield from findings(" ".join(args[i:]), where, depth + 1)
    elif name == "kubectl":
        if "--" in args and verb_of(args, KUBECTL_VALUE_OPTIONS)[0] == "exec":
            cut = args.index("--")
            inside = where.but(remote=where.remote or not is_local(kube_context(args[:cut], where, env)))
            yield from argv_findings(args[cut + 1:], inside, depth + 1)
        else:
            yield kubectl_finding(args, where, env)
    elif name == "helm":
        yield helm_finding(args, where, env)
    elif name == "git":
        yield git_finding(args, where)
    elif name == "gh":
        yield gh_finding(args)
    elif name == "psql":
        yield from psql_findings(args, where, env)


def heredoc_findings(header, body, where, depth):
    """A heredoc counts when a shell runs it, or psql reads it as SQL."""
    parts = HEREDOC.split(header, maxsplit=1)
    strip = lambda text: re.sub(r"\d*>>?\s*\S+", " ", text)
    before = simple_commands(strip(parts[0]))[0] or [[]]
    later = simple_commands(strip(parts[3]))[0]
    for argv in [before[-1], *later]:
        runs_in = shell_consumer(argv, where)
        if runs_in is not None:
            yield from findings(body, runs_in, depth + 1)
            return
        remote = sql_consumer(argv, where)
        if remote is not None:
            if remote:
                yield sql_ask(body)
            return


def findings(text, where, depth=0):
    """(decision, why) for each guarded action in this shell text; None entries are skipped later."""
    if not text or depth > DEPTH or len(text) > MAX_TEXT:
        return
    main, docs = split_heredocs(text)
    for header, body in docs:
        yield from heredoc_findings(header, body, where, depth)
    commands, substs = simple_commands(main)
    for inner in substs:
        yield from findings(inner, where, depth + 1)
    here, remote_sql = where, False
    for argv in commands:
        run = program(argv)
        if not run or run[0] == "export":
            env = dict(here.env)
            env.update(word.split("=", 1) for word in (run[1:] if run else argv) if ASSIGNMENT.match(word))
            here = here.but(env=env)
            continue
        if run[0] == "cd" and len(run) == 2 and not here.remote:
            here = here.but(cwd=str(pathlib.Path(here.cwd) / os.path.expanduser(run[1])))
            continue
        remote_sql = remote_sql or bool(sql_consumer(argv, here))
        yield from argv_findings(argv, here, depth)
    if remote_sql:
        # SQL on psql's stdin: `psql < drop.sql`, `cat drop.sql | psql`.
        files = re.findall(r"(?<![<\d])<(?![<(])\s*([^\s;&|<>()]+)", main)
        for argv in map(program, commands):
            if argv and os.path.basename(argv[0]) == "cat":
                files += [arg for arg in argv[1:] if not arg.startswith("-")]
        for path in files:
            yield sql_ask(read(path, where.cwd))


def decide(event):
    if not isinstance(event, dict):
        return None
    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    found = [f for f in findings(command_text(event.get("tool_input")), Where(cwd)) if f]
    decision, why = next((f for f in found if f[0] == DENY), None) or (found[0] if found else (None, None))
    if not decision:
        return None
    if decision == DENY:
        return DENY, (
            f"Blocked by oh: this command {why}. That step is always the user's. Stop, tell them what you "
            "wanted to do and why, and hand them the exact command (they can run it with `! <command>`). "
            "Don't look for another route to the same result."
        )
    if "turn_id" in event:  # Codex: a hook's "ask" isn't supported, so it can't stand in for the user.
        return DENY, (
            f"Blocked by oh: this command {why}. That needs the user's approval, and Codex can't ask for it "
            "from a hook. Stop and hand the user the exact command to run themselves. "
            "Don't look for another route to the same result."
        )
    return ASK, f"oh production guard: this command {why}. It can't be undone; approve only if you meant to."


def main():
    try:
        result = decide(json.load(sys.stdin))
    except Exception as error:  # fail open, but say so
        print(f"prod-guard: skipped ({type(error).__name__}: {error})", file=sys.stderr)
        return
    if result:
        decision, reason = result
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        }))


if __name__ == "__main__":
    main()
