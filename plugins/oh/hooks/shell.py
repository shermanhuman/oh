"""Shell parsing shared by oh's PreToolUse guards.

Splits what a shell would execute into simple commands, strips wrappers
(sudo, env, timeout, mise exec, ...), and finds heredocs, command
substitutions and shell scripts about to run. The guards decide what to do
with the result; nothing here knows about any one rule.

Loaded by path (see `load` in each guard), because `python3 -I` leaves the
hook's own directory off sys.path.
"""
import pathlib
import re
import shlex

SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}

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
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
SHELL_SUFFIXES = {".sh", ".bash", ".zsh"}
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
MAX_TEXT = 256_000


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


def lex(text, marks=None):
    """Split shell text into ("word", text) and ("op", text) tokens, the way a
    POSIX shell would: quotes are removed but never turn into operators or
    comments, `#` starts a comment only at the start of an unquoted word, and
    unquoted `$(...)` and backticks become ("subst", inner text). With a list
    as `marks`, appends ("<<", offset) for each heredoc operator and
    ("subst", start, end) for each unquoted command substitution it meets."""
    out, word, started, i, n = [], [], False, 0, len(text)
    marks = marks if marks is not None else []

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
            marks.append(("subst", i + 2, k - 1))
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
            if text[i:k] == "<<":
                marks.append(("<<", i))
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



def command_text(tool_input):
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, list):
        return shlex.join(str(part) for part in command)
    return command if isinstance(command, str) else ""


def piped_commands(text):
    """Simple commands as (argv, redirects, end): redirects are (operator, target)
    pairs such as (">", "out.sh") or ("<<<", "here-string"), and end is the operator
    that ends the command ("|" when it feeds the next one). Command substitutions
    are left out; read them with simple_commands."""
    try:
        chunks = [lex(text)]
    except Unparsed:
        chunks = []
        for line in text.split("\n"):
            try:
                chunks.append(lex(line))
            except Unparsed:
                pass
    out = []
    for chunk in chunks:
        argv, redirects, pending = [], [], None
        for kind, value in chunk:
            if kind == "subst":
                continue
            if kind == "op" and set(value) & set("<>"):
                pending = value
            elif kind == "op":
                out.append((argv, redirects, value))
                argv, redirects, pending = [], [], None
            elif pending:
                redirects.append((pending, value))
                pending = None
            else:
                argv.append(value)
        out.append((argv, redirects, None))
    return [(argv, redirects, end) for argv, redirects, end in out if argv or redirects]
