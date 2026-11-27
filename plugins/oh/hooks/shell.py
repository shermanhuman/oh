"""Shell parsing shared by oh's PreToolUse guards.

Splits what a shell would execute into simple commands, strips wrappers
(sudo, env, timeout, mise exec, ...), and finds heredocs, command
substitutions and shell scripts about to run. The guards decide what to do
with the result; nothing here knows about any one rule.

Loaded by path (see `load` in each guard), because `python3 -I` leaves the
hook's own directory off sys.path.
"""
import os
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
    """Text that doesn't lex. With `lex_exact`, `kind` and `start` name the
    construct left open (squote, dquote, subst, arith, param) and where its
    content starts, and `inner` is the construct open inside it, if any."""

    def __init__(self, why, kind=None, start=None, inner=None):
        super().__init__(why)
        self.kind, self.start, self.inner = kind, start, inner


class Expanded(str):
    """A word bash may change before it runs: it holds a parameter, a command
    substitution, a glob or a brace. Compares equal to its text."""


# Bash's operators, longest first, so `|<` is `|` then `<` and `>|` is one redirect.
OPERATORS = (
    ";;&", "&>>", "<<<", "<<-", ";;", ";&", "&&", "||", "|&", "&>", "<<", ">>", ">|", "<>", "<&", ">&",
    "|", "&", ";", "<", ">", "(", ")", "\n",
)
ANSI_ESCAPES = {
    "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t",
    "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?",
}
PARAMETER_START = re.compile(r"[A-Za-z0-9_{@*#?$!-]")


def ansi_c(body):
    """The value of a $'...' string's body."""
    out, i, n = [], 0, len(body)
    while i < n:
        c = body[i]
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        e = body[i + 1]
        if e in ANSI_ESCAPES:
            out.append(ANSI_ESCAPES[e])
            i += 2
        elif e in "01234567":
            digits = re.match(r"[0-7]{1,3}", body[i + 1:]).group()
            out.append(chr(int(digits, 8) & 0xFF))
            i += 1 + len(digits)
        elif e in "xuU":
            width = {"x": 2, "u": 4, "U": 8}[e]
            digits = re.match(r"[0-9A-Fa-f]{0,%d}" % width, body[i + 2:]).group()
            value = int(digits, 16) if digits else None
            out.append(chr(value) if value is not None and value <= 0x10FFFF else "\\" + e + digits)
            i += 2 + len(digits)
        elif e == "c" and i + 2 < n:
            out.append(chr(ord(body[i + 2]) & 0x1F))
            i += 3
        else:
            out.append("\\" + e)
            i += 2
    return "".join(out)


def _squote_end(text, i):
    """Index of the ' closing the one at i."""
    close = text.find("'", i + 1)
    if close < 0:
        raise Unparsed("open single quote", "squote", i + 1)
    return close


def _ansi_end(text, i):
    """Index of the ' closing the $' at i."""
    k, n = i + 2, len(text)
    while k < n and text[k] != "'":
        k += 2 if text[k] == "\\" else 1
    if k >= n:
        raise Unparsed("open $'", "squote", i + 2)
    return k


def _backtick_end(text, i):
    """Index of the ` closing the one at i (a backslash escapes the next character)."""
    k, n = i + 1, len(text)
    while k < n and text[k] != "`":
        k += 2 if text[k] == "\\" else 1
    if k >= n:
        raise Unparsed("open backtick", "subst", i + 1)
    return k


def _dquote_end(text, i):
    """Index of the " closing the one at i, skipping what's nested inside."""
    k, n = i + 1, len(text)
    try:
        while k < n and text[k] != '"':
            k = _skip_nested(text, k, quoted=True)
    except Unparsed as inner:
        raise Unparsed("open double quote", "dquote", i + 1, inner)
    if k >= n:
        raise Unparsed("open double quote", "dquote", i + 1)
    return k


def _skip_nested(text, k, quoted=False):
    """Index after the character or nested construct at k."""
    c = text[k]
    if c == "\\":
        return k + 2
    if c == "`":
        return _backtick_end(text, k) + 1
    if c == "$" and text[k + 1:k + 2] == "(":
        arith = _arith_end(text, k + 1)
        return arith if arith else _subst_end(text, k + 2) + 1
    if c == "$" and text[k + 1:k + 2] == "{":
        return _param_end(text, k + 2) + 1
    if not quoted and c == "'":
        return _squote_end(text, k) + 1
    if not quoted and c == "$" and text[k + 1:k + 2] == "'":
        return _ansi_end(text, k) + 1
    if not quoted and c == '"':
        return _dquote_end(text, k) + 1
    return k + 1


def _subst_end(text, i):
    """Index of the ) closing a $( whose content starts at i."""
    depth, k, n = 1, i, len(text)
    try:
        while k < n:
            c = text[k]
            if c == "#" and (k == i or text[k - 1] in " \t\n;|&("):
                end = text.find("\n", k)
                k = n if end < 0 else end
            elif c == "(":
                depth, k = depth + 1, k + 1
            elif c == ")":
                depth -= 1
                if not depth:
                    inner = text[i:k]
                    # A `case` pattern's ) would close it early: bash reads past it, so this can't be placed.
                    if len(re.findall(r"(?:^|[\s;&|(])case\s", inner)) > len(re.findall(r"\besac\b", inner)):
                        raise Unparsed("case inside $(", "subst", i)
                    return k
                k += 1
            else:
                k = _skip_nested(text, k)
    except Unparsed as inner:
        if inner.kind == "subst" and inner.start == i:
            raise
        raise Unparsed("open $(", "subst", i, inner)
    raise Unparsed("open $(", "subst", i)


def _param_end(text, i):
    """Index of the } closing a ${ whose content starts at i."""
    depth, k, n = 1, i, len(text)
    try:
        while k < n:
            c = text[k]
            if c == "}":
                depth -= 1
                if not depth:
                    return k
                k += 1
            else:
                k = _skip_nested(text, k)
    except Unparsed as inner:
        raise Unparsed("open ${", "param", i, inner)
    raise Unparsed("open ${", "param", i)


def _arith_end(text, i):
    """For `((` at i (or the `((` of `$((` at i): the index after its `))`, or
    None when it isn't arithmetic (bash then reads nested subshells)."""
    if text[i:i + 2] != "((":
        return None
    depth, k, n = 2, i + 2, len(text)
    try:
        while k < n:
            c = text[k]
            if c == "(":
                depth, k = depth + 1, k + 1
            elif c == ")":
                if depth == 2:
                    return k + 2 if text[k + 1:k + 2] == ")" else None
                depth, k = depth - 1, k + 1
            else:
                k = _skip_nested(text, k)
    except Unparsed as inner:
        raise Unparsed("open ((", "arith", i + 2, inner)
    raise Unparsed("open ((", "arith", i + 2)


def _inner_substs(text, start, end, quoted=False):
    """(start, end) of each command substitution inside text[start:end], the
    content of an arithmetic or ${...} expansion, which bash still runs."""
    spans, k = [], start
    while k < end:
        c, nxt = text[k], text[k + 1:k + 2]
        if c == "\\":
            k += 2
        elif c == "`":
            close = _backtick_end(text, k)
            spans.append((k + 1, close))
            k = close + 1
        elif c == "$" and nxt == "(":
            arith = _arith_end(text, k + 1)
            if arith:
                spans += _inner_substs(text, k + 3, arith - 2)
                k = arith
            else:
                close = _subst_end(text, k + 2)
                spans.append((k + 2, close))
                k = close + 1
        elif c == "$" and nxt == "{":
            close = _param_end(text, k + 2)
            spans += _inner_substs(text, k + 2, close)
            k = close + 1
        elif c == '"' and not quoted:
            close = _dquote_end(text, k)
            spans += _inner_substs(text, k + 1, close, quoted=True)
            k = close + 1
        elif c == "'" and not quoted:
            k = _squote_end(text, k) + 1
        elif c == "$" and nxt == "'" and not quoted:
            k = _ansi_end(text, k) + 1
        else:
            k += 1
    return spans


def lex_exact(text, marks=None):
    """Like `lex`, but reading the text the way bash does where `lex` doesn't:
    operators by bash's longest match (`|<` is `|` then `<`); CR is part of a
    word; inside double quotes a backslash is removed only before $ ` " \\ and
    newline, `\\`+newline vanishes, and `$(...)` and backticks are substitutions;
    `$'...'` is decoded; `$((...))`, `((...))` and `${...}` are one word part,
    with the substitutions inside them still reported. A word bash may change
    is an `Expanded`. With a list as `marks`, also appends ("word", start, end,
    value) and ("comment", start, end) as it goes, so they survive an Unparsed."""
    out, word, i, n = [], [], 0, len(text)
    state = {"started": False, "expanded": False, "start": 0, "glob": []}
    marks = marks if marks is not None else []

    def begin(at):
        if not state["started"]:
            state["started"], state["start"] = True, at

    def end_word(at):
        if state["started"]:
            value = "".join(word)
            # Unquoted glob or brace characters expand only in a pattern: `*`, `?`, `[…]`, `{a,b}`, `{1..3}`.
            if re.search(r"[*?]|\[.*\]|\{.*(,|\.\.).*\}", "".join(state["glob"])):
                state["expanded"] = True
            value = Expanded(value) if state["expanded"] else value
            out.append(("word", value))
            marks.append(("word", state["start"], at, value))
        word.clear()
        state["glob"].clear()
        state["started"] = state["expanded"] = False

    def subst(start, end):
        out.append(("subst", text[start:end]))
        marks.append(("subst", start, end))

    def backtick(start, end):
        # Inside backquotes a backslash before $ ` or \ is removed before the text runs.
        out.append(("subst", re.sub(r"\\([$`\\])", r"\1", text[start:end])))
        marks.append(("subst", start, end))

    def dollar(k):
        """A $-expansion at k: returns the index after it, or None for a plain $."""
        nxt = text[k + 1:k + 2]
        if nxt == "(":
            arith = _arith_end(text, k + 1)
            if arith:
                for span in _inner_substs(text, k + 3, arith - 2):
                    subst(*span)
                end = arith
            else:
                close = _subst_end(text, k + 2)
                subst(k + 2, close)
                end = close + 1
        elif nxt == "{":
            close = _param_end(text, k + 2)
            for span in _inner_substs(text, k + 2, close):
                subst(*span)
            end = close + 1
        elif nxt and PARAMETER_START.match(nxt):
            end = k + 2
        else:
            return None
        word.append(text[k:end])
        state["expanded"] = True
        return end

    while i < n:
        c = text[i]
        if c in " \t":
            end_word(i)
            i += 1
        elif c == "\\":
            begin(i)
            if text[i + 1:i + 2] == "\n":
                i += 2
            elif i + 1 < n:
                word.append(text[i + 1])
                i += 2
            else:
                word.append("\\")
                i += 1
        elif c == "'":
            begin(i)
            close = _squote_end(text, i)
            word.append(text[i + 1:close])
            i = close + 1
        elif c == "$" and text[i + 1:i + 2] == "'":
            begin(i)
            close = _ansi_end(text, i)
            word.append(ansi_c(text[i + 2:close]))
            i = close + 1
        elif c == '"' or (c == "$" and text[i + 1:i + 2] == '"'):
            begin(i)
            k = i + (1 if c == '"' else 2)
            try:
                while True:
                    if k >= n:
                        raise Unparsed("open double quote", "dquote", i + 1)
                    d = text[k]
                    if d == '"':
                        k += 1
                        break
                    if d == "\\":
                        nxt = text[k + 1:k + 2]
                        if nxt == "\n":
                            k += 2
                        elif nxt in ("$", "`", '"', "\\"):
                            word.append(nxt)
                            k += 2
                        else:
                            word.append("\\")
                            k += 1
                    elif d == "`":
                        close = _backtick_end(text, k)
                        backtick(k + 1, close)
                        word.append(text[k:close + 1])
                        state["expanded"] = True
                        k = close + 1
                    elif d == "$":
                        end = dollar(k)
                        if end is None:
                            word.append("$")
                            end = k + 1
                        k = end
                    else:
                        word.append(d)
                        k += 1
            except Unparsed as inner:
                if inner.kind == "dquote" and inner.start == i + 1:
                    raise
                raise Unparsed("open double quote", "dquote", i + 1, inner)
            i = k
        elif c == "#" and not state["started"]:
            end = text.find("\n", i)
            end = n if end < 0 else end
            marks.append(("comment", i, end))
            i = end
        elif c == "`":
            begin(i)
            close = _backtick_end(text, i)
            backtick(i + 1, close)
            word.append(text[i:close + 1])
            state["expanded"] = True
            i = close + 1
        elif c == "$":
            begin(i)
            end = dollar(i)
            if end is None:
                word.append("$")
                end = i + 1
            i = end
        elif c == "(" and not state["started"] and _arith_end(text, i):
            arith = _arith_end(text, i)
            begin(i)
            for span in _inner_substs(text, i + 2, arith - 2):
                subst(*span)
            word.append(text[i:arith])
            state["expanded"] = True
            i = arith
        elif c in "<>" and text[i + 1:i + 2] == "(":
            # Process substitution: a word (a file name) whose content runs.
            begin(i)
            close = _subst_end(text, i + 2)
            subst(i + 2, close)
            word.append(text[i:close + 1])
            state["expanded"] = True
            i = close + 1
        elif c in ";&|<>()\n":
            op = next(o for o in OPERATORS if text.startswith(o, i))
            if state["started"] and set(op) & set("<>") and re.fullmatch(r"\d+|\{[A-Za-z_][A-Za-z0-9_]*\}", text[state["start"]:i]):
                # `2>/dev/null` and `{fd}>&-`: the number or {name} belongs to the redirect.
                word.clear()
                state["started"] = state["expanded"] = False
            end_word(i)
            if op in ("<<", "<<-"):
                marks.append(("<<", i))
            out.append(("op", op))
            i += len(op)
        else:
            begin(i)
            state["glob"].append(c)
            word.append(c)
            i += 1
    end_word(n)
    return out


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
            marks.append(("subst", i + 1, close))
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


# Exact reading, for the secrets guard. A deny-list built on a lexer can be
# fooled wherever the lexer reads text differently from bash, so these read it
# the way bash does and say when they can't be sure (`sure` false): the guard
# then refuses the text if it mentions what it guards.

# What a heredoc operator and its word become in `main`: a redirect from a name
# no command can spell, so `echo x < /dev/null | bash` isn't taken for a heredoc.
HEREDOC_PLACEHOLDER = "/dev/null/oh-heredoc-" + os.urandom(8).hex()


def heredoc_operators(text):
    """(offsets, clean): the `<<` and `<<-` operators bash sees in text, none
    inside quotes, comments or arithmetic, and those inside a command
    substitution still open at the end of text (a heredoc in `"$(cat <<'EOF'`);
    clean is true when nothing is left open at the end."""
    marks = []
    try:
        lex_exact(text, marks)
    except Unparsed as error:
        deepest = None
        while error is not None:
            if error.kind == "subst":
                deepest = error
            error = error.inner
        ops = [m[1] for m in marks if m[0] == "<<"]
        if deepest is not None:
            ops += [deepest.start + k for k in heredoc_operators(text[deepest.start:])[0]]
        return ops, False
    return [m[1] for m in marks if m[0] == "<<"], True


def place_heredocs(text):
    """(main, docs, sure). main is the text without heredoc bodies, each
    `<<WORD` turned into `< /dev/null` so nothing reads it as a heredoc again;
    docs is (header line, start, end, body, quoted) for each, start and end
    bounding the operator and its word in the header, quoted true when the word
    is quoted (bash then expands nothing in the body). A body ends where bash
    ends it: at a line equal to the word (after leading tabs for `<<-`). sure is
    false when a body never ends, the word is one bash would expand, or a line
    could end the body inside a command substitution (`EOF)`)."""
    lines, kept, docs, sure, i = text.split("\n"), [], [], True, 0
    pending = []  # kept lines since the last point where nothing was left open
    budget = 4 * MAX_TEXT  # characters re-lexed while something stays open; past it, give up placing
    while i < len(lines):
        line = lines[i]
        i += 1
        if "<<" not in line:
            kept.append(line)
            pending.append(line)
            continue
        before = "\n".join(pending + [""])
        budget -= len(before)
        if budget < 0:
            kept.extend(lines[i - 1:])
            return "\n".join(kept), docs, False
        found, clean = heredoc_operators(before + line)
        ops = [k - len(before) for k in found if k >= len(before)]
        cuts = []
        for op in ops:
            strip = line.startswith("<<-", op)
            word_start = op + (3 if strip else 2)
            marks = []
            try:
                lex_exact(line[word_start:], marks)
            except Unparsed:
                pass
            first = next((m for m in marks if m[0] in ("word", "comment")), None)
            if first is None or first[0] != "word" or line[word_start:word_start + first[1]].strip(" \t"):
                sure = False
                continue
            delimiter, end = first[3], word_start + first[2]
            quoted = any(q in line[word_start + first[1]:end] for q in "'\"\\")
            if isinstance(delimiter, Expanded) or not delimiter:
                sure = False
            body = []
            while i < len(lines):
                candidate = lines[i].lstrip("\t") if strip else lines[i]
                if candidate == delimiter:
                    break
                if candidate.startswith(delimiter) and candidate[len(delimiter):].lstrip(" \t")[:1] in (")", "`"):
                    sure = False
                body.append(lines[i])
                i += 1
            else:
                sure = False
            i += 1
            docs.append((line, op, end, "\n".join(body), quoted))
            cuts.append((op, end))
        for op, end in reversed(cuts):
            line = line[:op] + "< " + HEREDOC_PLACEHOLDER + line[end:]
        kept.append(line)
        pending = [] if clean else pending + [line]
    return "\n".join(kept), docs, sure


def read_script(arg, cwd):
    """(path, text) of a file a shell is about to run, whatever its name, or
    (path, None) when it can't be read (missing, unreadable, too long)."""
    path = pathlib.Path(arg)
    if not path.is_absolute():
        path = pathlib.Path(cwd) / path
    try:
        if not path.is_file() or path.stat().st_size > MAX_TEXT:
            return path, None
        return path, path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return path, None


def _without_case_patterns(tokens):
    """tokens without the patterns of `case WORD in PATTERN) …;; esac`, which
    are words bash matches, not commands it runs."""
    out, cases, pattern, first, start = [], [], False, False, True
    for kind, value in tokens:
        if pattern:
            if kind == "op" and value == "\n":
                continue
            if first and kind == "word" and value == "esac":
                cases.pop()
                pattern, start = False, False
                out += [("op", ";"), (kind, value)]
                continue
            first = False
            if kind == "op" and value == ")":
                pattern, start = False, True
                out.append(("op", ";"))
            continue
        if kind == "word" and start and value == "case":
            cases.append("head")
        elif kind == "word" and cases and cases[-1] == "head" and value == "in":
            cases[-1], pattern, first = "body", True, True
            out.append((kind, value))
            continue
        elif kind == "word" and start and value == "esac" and cases:
            cases.pop()
        elif kind == "op" and value in (";;", ";&", ";;&") and cases and cases[-1] == "body":
            out.append(("op", ";"))
            pattern, first = True, True
            continue
        out.append((kind, value))
        start = kind == "op" or (kind == "word" and value in KEYWORDS)
    return out


def _exact_chunks(text):
    """(chunks, sure): the whole text lexed, or line by line when it doesn't lex."""
    try:
        return [_without_case_patterns(lex_exact(text))], True
    except Unparsed:
        chunks = []
        for line in text.split("\n"):
            try:
                chunks.append(_without_case_patterns(lex_exact(line)))
            except Unparsed:
                pass
        return chunks, False


def exact_commands(text):
    """(commands, substs, sure), as `simple_commands` reads them but with `lex_exact`."""
    chunks, sure = _exact_chunks(text)
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
    return [argv for argv in commands if argv], substs, sure


def exact_pipes(text):
    """(stages, sure), as `piped_commands` reads them but with `lex_exact`."""
    chunks, sure = _exact_chunks(text)
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
    return [(argv, redirects, end) for argv, redirects, end in out if argv or redirects], sure
