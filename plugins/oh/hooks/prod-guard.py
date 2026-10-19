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
  context, or over ssh; SQL from -c, -f, a heredoc, a here-string, `< file`,
  or `cat`/`echo`/`printf` piped in.

Files written earlier in the same command (`cat > run.sh <<EOF`,
`printf ... > drop.sql`) are read as written when a later command runs them.

Codex can't ask from a hook (it logs the hook as failed and runs the command),
so there the asked cases are denied instead.

Not covered: interpreter code, a port-forwarded production database (it
looks like localhost), a database named by a pg_service.conf entry, and text
inside double-quoted command substitutions, or a heredoc inside a quoted
command string (`ssh vm 'psql <<EOF ...'`). Contexts and hosts named only
through shell variables set elsewhere count as production and ask. Fails open, with a note on stderr, on anything unexpected.
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
SHELLS, SSH_VALUE_OPTIONS, ASSIGNMENT, MAX_TEXT = shell.SHELLS, shell.SSH_VALUE_OPTIONS, shell.ASSIGNMENT, shell.MAX_TEXT
split_heredocs, simple_commands, piped_commands, program, shell_script, command_text = (
    shell.split_heredocs, shell.simple_commands, shell.piped_commands, shell.program, shell.shell_script,
    shell.command_text,
)

DENY, ASK = "deny", "ask"
DEPTH = 4
LOCAL_CONTEXT = re.compile(r"(kind|k3d)-.+|minikube|docker-desktop|orbstack|rancher-desktop")
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
DEFAULT_BRANCHES = {"main", "master"}
CURRENT_CONTEXT = re.compile(r"^current-context:\s*[\"']?([^\s\"']+)", re.M)
MERGE_MUTATION = re.compile(r"\b(mergePullRequest|enablePullRequestAutoMerge)\b")
GITHUB_API = re.compile(r"api\.github\.com/(repos/[^/\s?#]+/[^/\s?#]+(?:/pulls/[^/\s?#]+/merge)?)/?(?:[?#\s]|$)")
NETWORK = {"curl", "wget", "http", "https", "xh"}
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

KUBECTL_VALUE_OPTIONS = {
    "-n", "--namespace", "--context", "--kubeconfig", "--cluster", "--user", "-s", "--server", "--token",
    "--as", "--as-group", "--as-uid", "--request-timeout", "--certificate-authority", "--client-certificate",
    "--client-key", "--tls-server-name", "--cache-dir", "--log-file", "--username", "--password",
    "-v", "--v", "--profile", "--profile-output", "--log-flush-frequency", "--vmodule",
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
    (over ssh or inside a production pod), variables set earlier in the text,
    and files written earlier in the text (path -> contents, shared by every copy)."""

    def __init__(self, cwd, remote=False, env=None, files=None):
        self.cwd, self.remote, self.env = cwd, remote, dict(env or {})
        self.files = {} if files is None else files

    def but(self, cwd=None, remote=None, env=None):
        return Where(cwd or self.cwd, self.remote if remote is None else remote,
                     self.env if env is None else env, self.files)

    def path(self, name):
        return os.path.normpath(os.path.join(self.cwd, os.path.expanduser(name)))


def options(args, *names):
    """Every value given to these options: `--x v`, `--x=v`, `-xv`, and a short one
    ending a cluster (`-Atc v`)."""
    values = []
    for i, arg in enumerate(args):
        for name in names:
            if (arg == name or (len(name) == 2 and re.fullmatch(r"-[a-zA-Z]+" + name[1], arg))) and i + 1 < len(args):
                values.append(args[i + 1])
            elif name.startswith("--") and arg.startswith(name + "="):
                values.append(arg[len(name) + 1:])
            elif not name.startswith("--") and arg.startswith(name) and len(arg) > len(name) and not arg.startswith("--"):
                values.append(arg[len(name):])
    return values


def option(args, *names):
    """The value that takes effect: CLIs read the last of repeated flags."""
    values = options(args, *names)
    return values[-1] if values else None


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


def read(name, where):
    """A file's text, as written earlier in the command if it was, else from disk."""
    if where.path(name) in where.files:
        return where.files[where.path(name)]
    path = pathlib.Path(where.path(name))
    try:
        if path.is_file() and path.stat().st_size <= MAX_TEXT:
            return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pass
    return None


def current_context(kubeconfig, env, where):
    """The current-context of the first file in a KUBECONFIG list that names one; None if unknown."""
    for entry in kubeconfig.split(":"):
        expanded = _expand(entry, env)
        if "$" in expanded:
            return None
        text = read(expanded, where)
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
    return current_context(kubeconfig, merged, where)


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
    # A bare --dry-run means client (`--dry-run none` makes "none" a resource name); the last one counts.
    dry = [arg.partition("=")[2] or "client" for arg in rest if arg == "--dry-run" or arg.startswith("--dry-run=")]
    if dry and dry[-1] not in ("none", "false", "0"):
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
    dry = [arg.partition("=")[2] or "true" for arg in args[i + 1:] if arg == "--dry-run" or arg.startswith("--dry-run=")]
    if verb not in ("uninstall", "delete", "del", "un") or (dry and dry[-1].lower() in ("true", "1", "t")):
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
    if any(arg == "--dry-run" or re.fullmatch(r"-[a-zA-Z]*n[a-zA-Z]*", arg) for arg in flags):
        return None
    if any(
        arg in ("--force", "--force-with-lease") or arg.startswith("--force-with-lease=")
        or re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", arg)
        for arg in flags
    ):
        return DENY, "force-pushes"
    if any(arg in ("--mirror", "--all", "--branches") for arg in flags):
        return DENY, "pushes every branch"
    words = positionals(rest, PUSH_VALUE_OPTIONS)
    named = option(rest, "--repo")
    remote, refspecs = (named, words) if named else ((words[0] if words else "origin"), words[1:])
    if any(spec.startswith("+") for spec in refspecs):
        return DENY, "force-pushes"
    defaults = set(DEFAULT_BRANCHES)
    targets = []
    if not where.remote:
        head = git(repo, "symbolic-ref", "-q", "--short", f"refs/remotes/{remote}/HEAD")
        if head:
            defaults.add(head.split("/", 1)[-1])
    for spec in refspecs or ([] if "--tags" in flags else ["HEAD"]):
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


def gh_finding(args, where):
    words = positionals(args, GH_VALUE_OPTIONS | GH_API_VALUE_OPTIONS)
    if words[:2] == ["pr", "merge"]:
        return DENY, "merges a pull request"
    if words[:2] == ["repo", "delete"]:
        return DENY, "deletes a repository"
    if words[:1] != ["api"] or len(words) < 2:
        return None
    endpoint = words[1].lstrip("/")
    fields = options(args, "-f", "--raw-field", "-F", "--field")
    request = option(args, "--input")
    method = (option(args, "-X", "--method") or ("POST" if fields or request else "GET")).upper()
    if re.fullmatch(r"repos/[^/]+/[^/]+/pulls/[^/]+/merge", endpoint) and method in ("PUT", "POST"):
        return DENY, "merges a pull request"
    bodies = [(read(f.split("=@", 1)[1], where) or "") if "=@" in f else f for f in fields]
    if request and request != "-":  # `--input -` reads stdin, checked where stdin is known
        bodies.append(read(request, where) or "")
    if endpoint == "graphql" and any(MERGE_MUTATION.search(body) for body in bodies):
        return DENY, "merges a pull request"
    if method == "DELETE" and re.fullmatch(r"repos/[^/]+/[^/]+/?", endpoint):
        return DENY, "deletes a repository"
    return None


def network_finding(args):
    """curl, wget, httpie or xh calling the GitHub REST API to merge a PR or delete a repository."""
    for arg in args:
        match = GITHUB_API.match(re.sub(r"^https?://", "", arg))
        if not match:
            continue
        method = option(args, "-X", "--request", "--method")
        if not method:
            named = [a.upper() for a in args if a.upper() in HTTP_METHODS]
            sends = any(a.startswith(("-d", "--data", "--json", "--form", "-F", "--post")) for a in args)
            method = named[0] if named else ("POST" if sends else "GET")
        method, path = method.upper(), match.group(1)
        if path.endswith("/merge") and method in ("PUT", "POST"):
            return DENY, "merges a pull request"
        if not path.endswith("/merge") and method == "DELETE":
            return DENY, "deletes a repository"
    return None


def remote_host(args, env):
    """True when psql's host, from flags, a connection string, PGHOST or PGHOSTADDR, isn't local.
    A connection argument held in a variable (`psql "$DATABASE_URL"`) can't be resolved, so it counts."""
    hosts = options(args, "-h", "--host")
    for arg in options(args, "-d", "--dbname") + positionals(args, PSQL_VALUE_OPTIONS):
        if "$" in arg:
            return True
        uri = re.match(r"postgres(?:ql)?://(?:[^@/]*@)?([^/?]*)", arg)
        if uri:
            hosts.append(re.sub(r"(\]|^[^\[\]]*):\d+$", r"\1", uri.group(1)))
            hosts += re.findall(r"[?&]host(?:addr)?=([^&]+)", arg)
        hosts += re.findall(r"(?:^|\s)host(?:addr)?=(\S+)", arg)
    if not hosts:
        hosts = [env[name] for name in ("PGHOST", "PGHOSTADDR") if env.get(name)]
    for value in hosts:
        for host in value.split(","):
            host = host.strip("[]")
            if "$" in host or not (host in LOCAL_HOSTS or host.startswith("/")):
                return True
    return False


def statements(sql):
    """SQL split on semicolons, without comments, with string literals emptied to ''.
    Quote-aware, so `'ok--'` isn't a comment and `';'` isn't a boundary."""
    sql = "\n".join(line for line in sql.split("\n") if not line.lstrip().startswith("\\"))
    out, current, i, n = [], [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "'":
            close = i + 1
            while close < n and not (sql[close] == "'" and sql[close + 1:close + 2] != "'"):
                close += 2 if sql[close:close + 2] == "''" else 1
            current.append("''")
            i = close + 1
        elif c == '"':
            close = sql.find('"', i + 1)
            close = n if close < 0 else close
            current.append(sql[i:close + 1])
            i = close + 1
        elif sql.startswith("--", i):
            while i < n and sql[i] != "\n":
                i += 1
        elif sql.startswith("/*", i):
            close = sql.find("*/", i + 2)
            i = n if close < 0 else close + 2
            current.append(" ")
        elif c == ";":
            out.append("".join(current))
            current, i = [], i + 1
        else:
            current.append(c)
            i += 1
    out.append("".join(current))
    return out


def destructive(sql):
    """What makes this SQL irreversible, or None."""
    for statement in statements(sql):
        s = " ".join(statement.split()).upper()
        start = re.match(r"(DROP|TRUNCATE)\b", s)
        if start:
            return start.group(1)
        if re.match(r"ALTER\s+TABLE\b", s) and re.search(r"\bDROP\s+(?!CONSTRAINT|DEFAULT|NOT\b|IDENTITY|EXPRESSION)[\w\"]", s):
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
        yield sql_ask(read(path, where)) if path != "-" else None


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
        return where.but(env={**where.env, **env})
    if name == "ssh":
        # stdin is a script only when the remote command is a shell reading it (`ssh vm`, `ssh vm bash -s`).
        inner = ssh_command(args)
        if inner is None:
            return where.but(remote=True)
        try:  # the remote shell re-lexes the joined words, so wrappers (`sudo bash`) count too
            words = [value for kind, value in shell.lex(inner) if kind == "word"]
        except shell.Unparsed:
            return None
        return where.but(remote=True) if shell_consumer(words, where) is not None else None
    if name == "kubectl" and "--" in args and verb_of(args, KUBECTL_VALUE_OPTIONS)[0] == "exec":
        cut = args.index("--")
        if shell_consumer(args[cut + 1:], where) is not None:
            return where.but(remote=where.remote or not is_local(kube_context(args[:cut], where, env)))
    return None


def script(name, where):
    """The path and text of a shell script about to run, including one written earlier in the command."""
    if where.path(name) in where.files:
        return pathlib.Path(where.path(name)), where.files[where.path(name)]
    return shell_script(name, where.cwd)


def printf(args):
    """printf's output for the common cases: escapes, %s and %b, the format reused until operands run out."""
    args = args[1:] if args[:1] == ["--"] else args
    if not args:
        return ""
    unescape = lambda s: s.replace("\\n", "\n").replace("\\t", "\t")
    parts = re.split(r"(%[-+ #0-9.]*[a-zA-Z%])", args[0])
    operands, out = list(args[1:]), []
    while True:
        for k, part in enumerate(parts):
            if k % 2 == 0:
                out.append(unescape(part))
            elif part == "%%":
                out.append("%")
            else:
                value = operands.pop(0) if operands else ""
                out.append(unescape(value) if part.endswith("b") else value)
        if not operands or not any(p != "%%" for p in parts[1::2]):
            return "".join(out)


def output(argv, where, stdin):
    """What a command prints, when the guard can tell: echo, printf, cat, and tee passing stdin on."""
    run = program(argv)
    if not run:
        return None
    name, args = os.path.basename(run[0]), run[1:]
    if name == "echo":
        return " ".join(arg for arg in args if arg not in ("-n", "-e", "-E")) + ("" if "-n" in args else "\n")
    if name == "printf":
        return printf(args)
    if name == "cat":
        files = [arg for arg in args if not arg.startswith("-")]
        return "\n".join(read(f, where) or "" for f in files) if files else stdin
    if name == "tee":
        return stdin
    return None


def ssh_command(args):
    """The remote command, joined the way ssh sends it. ssh takes options before
    and after the host (`ssh vm -t bash`) until `--`."""
    i, host = 0, None
    while i < len(args):
        if args[i] == "--":
            i += 1
            if host is None and i < len(args):
                host, i = args[i], i + 1
            break
        if args[i].startswith("-"):
            i += 2 if len(args[i]) == 2 and args[i][1] in SSH_VALUE_OPTIONS else 1
        elif host is None:
            host, i = args[i], i + 1
        else:
            break
    return " ".join(args[i:]) if host is not None and i < len(args) else None


def argv_findings(argv, where, depth):
    env = assignments(argv)
    run = program(argv)
    if not run:
        return
    name, args = os.path.basename(run[0]), run[1:]
    # A child shell inherits the command's variables (`PGHOST=x bash -c ...`), and a
    # script runs in the caller's directory, not its own.
    child = where.but(env={**where.env, **env})
    if name in SHELLS:
        for i, flag in enumerate(args):
            if re.fullmatch(r"-[a-z]*c[a-z]*", flag) and i + 1 < len(args):
                yield from findings(args[i + 1], child, depth + 1)
                return
            if i > 0 and re.fullmatch(r"[-+][a-zA-Z]*[oO]", args[i - 1]):
                continue
            if not flag.startswith(("-", "+")):
                text = script(flag, where)[1]
                if text:
                    yield from findings(text, child, depth + 1)
                return
        return
    if "/" in run[0]:
        text = script(run[0], where)[1]
        if text:
            yield from findings(text, child, depth + 1)
            return
    if name == "eval":
        yield from findings(" ".join(args), child, depth + 1)
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
        yield gh_finding(args, where)
    elif name == "psql":
        yield from psql_findings(args, where, env)
    elif name in NETWORK:
        yield network_finding(args)


def attach_heredocs(main, docs):
    """(bodies, substs): the body for each `<<` the main walk meets, in walk order,
    and the text of each unquoted command substitution with the heredocs inside it
    put back. A heredoc inside quotes (a commit message in "$(cat <<'EOF' ...)")
    is on neither list, so it can't be handed to the wrong command."""
    marks, offset = [], 0
    try:
        shell.lex(main, marks)
    except shell.Unparsed:
        for line in main.split("\n"):
            line_marks = []
            try:
                shell.lex(line, line_marks)
            except shell.Unparsed:
                pass
            marks += [(m[0], m[1] + offset, *[x + offset for x in m[2:]]) for m in line_marks]
            offset += len(line) + 1
    ops = {m[1] for m in marks if m[0] == "<<"}
    spans = [(m[1], m[2]) for m in marks if m[0] == "subst"]
    # Header lines are the lines of `main` that still match HEREDOC, in docs order.
    headers, offset = [], 0
    for line in main.split("\n"):
        match = shell.HEREDOC.search(line)
        if match:
            headers.append((offset + match.start(), match.group(2)))
        offset += len(line) + 1
    bodies, inserts = [], {span: [] for span in spans}
    for (start, delim), (header, body) in zip(headers, docs):
        if start in ops:
            bodies.append(body)
            continue
        inside = next((span for span in spans if span[0] <= start < span[1]), None)
        if inside:
            inserts[inside].append((start - inside[0], body, delim))
    substs = []
    for span in spans:
        inner = main[span[0]:span[1]]
        for rel, body, delim in sorted(inserts[span], reverse=True):
            cut = inner.find("\n", rel)
            cut = len(inner) if cut < 0 else cut
            inner = inner[:cut] + "\n" + body + "\n" + delim + inner[cut:]
        substs.append(inner)
    return bodies, substs


def findings(text, where, depth=0):
    """(decision, why) for each guarded action in this shell text; None entries are skipped later."""
    if not text or depth > DEPTH or len(text) > MAX_TEXT:
        return
    main, docs = split_heredocs(text)
    bodies, substs = attach_heredocs(main, docs)
    bodies = iter(bodies)
    for inner in substs:
        yield from findings(inner, where, depth + 1)
    here, piped = where, None
    for argv, redirects, end in piped_commands(main):
        # What the command reads: the previous stage of a pipe, `< file`, a here-string or a heredoc.
        inputs = [piped] if piped is not None else []
        for operator, target in redirects:
            if operator == "<":
                inputs.append(read(target, here))
            elif operator == "<<<":
                inputs.append(target)
            elif operator == "<<":  # `<<-EOF` lexes as `<<` and the word `-EOF`
                inputs.append(next(bodies, None))
        inputs = [text for text in inputs if text]
        piped = None
        run = program(argv)
        if not run or run[0] == "export":
            env = dict(here.env)
            env.update(word.split("=", 1) for word in (run[1:] if run else argv) if ASSIGNMENT.match(word))
            here = here.but(env=env)
            continue
        if run[0] == "cd" and len(run) == 2 and not here.remote:
            here = here.but(cwd=here.path(run[1]))
            continue
        stdin = "\n".join(inputs) if inputs else None
        printed = output(argv, here, stdin)
        if end in ("|", "|&"):
            piped = printed
        # Files written here are read as written when a later command runs them:
        # `cat > run.sh <<EOF`, `printf '...' > zap.sh`, `... | tee run.sh`.
        if printed is not None:
            for operator, target in redirects:
                if operator in (">", ">|", "&>"):
                    here.files[here.path(target)] = printed
                elif operator in (">>", "&>>"):
                    here.files[here.path(target)] = (read(target, here) or "") + printed
            if os.path.basename(run[0]) == "tee":
                append = any(arg in ("-a", "--append") for arg in run[1:])
                for name in positionals(run[1:], set()):
                    here.files[here.path(name)] = ((read(name, here) or "") if append else "") + printed
        if inputs and sql_consumer(argv, here):
            for sql in inputs:
                yield sql_ask(sql)
        runs_in = shell_consumer(argv, here) if inputs else None
        if runs_in is not None:
            for script_text in inputs:
                yield from findings(script_text, runs_in, depth + 1)
        if inputs and os.path.basename(run[0]) == "gh" and "graphql" in run and any(MERGE_MUTATION.search(x) for x in inputs):
            yield DENY, "merges a pull request"
        yield from argv_findings(argv, here, depth)


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
