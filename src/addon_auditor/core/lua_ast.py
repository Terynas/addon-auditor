"""Lua 5.1 lexer, recursive-descent parser and scope resolver.

WoW runs Lua 5.1, so this parser targets that grammar. It keeps comments
(for inline suppressions), line/column positions, parent links, and marks
every ``Name`` as local or global after :func:`resolve_scopes`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any


class LuaSyntaxError(Exception):
    def __init__(self, message: str, line: int, col: int) -> None:
        super().__init__(f"{message} at line {line}:{col}")
        self.line = line
        self.col = col


# --------------------------------------------------------------------------- lexer

KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function", "if", "in",
    "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while",
}

_SYMBOLS = ["...", "..", "==", "~=", "<=", ">=", "::", "+", "-", "*", "/", "%", "^", "#", "<", ">",
            "=", "(", ")", "{", "}", "[", "]", ";", ":", ",", "."]


@dataclass(slots=True)
class Token:
    kind: str  # name | keyword | number | string | op | eof
    value: str
    line: int
    col: int


@dataclass(slots=True)
class Comment:
    text: str
    line: int
    end_line: int


def _long_bracket_level(src: str, i: int) -> int:
    """If src[i] starts ``[==[`` return level, else -1."""
    if src[i] != "[":
        return -1
    j = i + 1
    level = 0
    while j < len(src) and src[j] == "=":
        level += 1
        j += 1
    if j < len(src) and src[j] == "[":
        return level
    return -1


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
            "\\": "\\", '"': '"', "'": "'", "\n": "\n"}


def tokenize(src: str) -> tuple[list[Token], list[Comment]]:
    tokens: list[Token] = []
    comments: list[Comment] = []
    i = 0
    n = len(src)
    line = 1
    line_start = 0

    if src.startswith("\ufeff"):
        i = 1
        line_start = 1
    if src.startswith("#", i):  # shebang
        while i < n and src[i] != "\n":
            i += 1

    def read_long(start: int, level: int) -> tuple[str, int]:
        nonlocal line, line_start
        close = "]" + "=" * level + "]"
        body_start = start + level + 2
        end = src.find(close, body_start)
        if end < 0:
            raise LuaSyntaxError("unfinished long string/comment", line, start - line_start + 1)
        body = src[body_start:end]
        for k, ch in enumerate(body):
            if ch == "\n":
                line += 1
                line_start = body_start + k + 1
        if body.startswith("\r\n"):
            body = body[2:]
        elif body.startswith("\n"):
            body = body[1:]
        return body, end + len(close)

    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            line_start = i
            continue
        if c in " \t\r\f\v":
            i += 1
            continue
        col = i - line_start + 1
        if c == "-" and src.startswith("--", i):
            start_line = line
            j = i + 2
            if j < n and src[j] == "[":
                level = _long_bracket_level(src, j)
                if level >= 0:
                    body, i = read_long(j, level)
                    comments.append(Comment(body, start_line, line))
                    continue
            k = src.find("\n", j)
            k = n if k < 0 else k
            comments.append(Comment(src[j:k], start_line, start_line))
            i = k
            continue
        if c.isalpha() or c == "_":
            j = i + 1
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            tokens.append(Token("keyword" if word in KEYWORDS else "name", word, line, col))
            i = j
            continue
        if c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i
            if src.startswith(("0x", "0X"), i):
                j += 2
                while j < n and (src[j] in "0123456789abcdefABCDEF."):
                    j += 1
                if j < n and src[j] in "pP":
                    j += 1
                    if j < n and src[j] in "+-":
                        j += 1
                    while j < n and src[j].isdigit():
                        j += 1
            else:
                while j < n and (src[j].isdigit() or src[j] == "."):
                    j += 1
                if j < n and src[j] in "eE":
                    j += 1
                    if j < n and src[j] in "+-":
                        j += 1
                    while j < n and src[j].isdigit():
                        j += 1
            tokens.append(Token("number", src[i:j], line, col))
            i = j
            continue
        if c in "\"'":
            j = i + 1
            buf: list[str] = []
            while True:
                if j >= n or src[j] == "\n":
                    raise LuaSyntaxError("unfinished string", line, col)
                ch = src[j]
                if ch == c:
                    j += 1
                    break
                if ch == "\\":
                    j += 1
                    if j >= n:
                        raise LuaSyntaxError("unfinished string", line, col)
                    e = src[j]
                    if e in _ESCAPES:
                        buf.append(_ESCAPES[e])
                        if e == "\n":
                            line += 1
                            line_start = j + 1
                        j += 1
                    elif e.isdigit():
                        k = j
                        while k < n and k < j + 3 and src[k].isdigit():
                            k += 1
                        buf.append(chr(min(int(src[j:k]), 255)))
                        j = k
                    else:
                        buf.append(e)
                        j += 1
                    continue
                buf.append(ch)
                j += 1
            tokens.append(Token("string", "".join(buf), line, col))
            i = j
            continue
        if c == "[":
            level = _long_bracket_level(src, i)
            if level >= 0:
                start_line = line
                body, i = read_long(i, level)
                tokens.append(Token("string", body, start_line, col))
                continue
        for sym in _SYMBOLS:
            if src.startswith(sym, i):
                tokens.append(Token("op", sym, line, col))
                i += len(sym)
                break
        else:
            raise LuaSyntaxError(f"unexpected character {c!r}", line, col)
    tokens.append(Token("eof", "", line, i - line_start + 1))
    return tokens, comments


# --------------------------------------------------------------------------- AST

# Scope-resolution back-links; not part of the tree (they form cycles).
_SEMANTIC_KEYS = frozenset({"decl", "refs"})


@dataclass(eq=False)
class Node:
    kind: str
    line: int
    col: int = 0
    end_line: int = 0
    a: dict[str, Any] = field(default_factory=dict)
    parent: Node | None = field(default=None, repr=False)

    def __getattr__(self, name: str) -> Any:
        # Only called when normal lookup fails -> attribute fields.
        a = object.__getattribute__(self, "a")
        if name in a:
            return a[name]
        raise AttributeError(name)

    def children(self) -> Iterator[Node]:
        for k, v in self.a.items():
            if k in _SEMANTIC_KEYS:
                continue
            if isinstance(v, Node):
                yield v
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, Node):
                        yield item
                    elif isinstance(item, tuple):
                        for sub in item:
                            if isinstance(sub, Node):
                                yield sub

    def walk(self) -> Iterator[Node]:
        stack: list[Node] = [self]
        while stack:
            node = stack.pop()
            yield node
            kids = list(node.children())
            stack.extend(reversed(kids))

    def ancestors(self) -> Iterator[Node]:
        p = self.parent
        while p is not None:
            yield p
            p = p.parent

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Node({self.kind}@{self.line})"


def N(kind: str, tok: Token, **attrs: Any) -> Node:
    return Node(kind, tok.line, tok.col, tok.line, dict(attrs))


_BINARY_PRIORITY = {
    "or": (1, 1), "and": (2, 2),
    "<": (3, 3), ">": (3, 3), "<=": (3, 3), ">=": (3, 3), "~=": (3, 3), "==": (3, 3),
    "..": (5, 4),  # right associative
    "+": (6, 6), "-": (6, 6),
    "*": (7, 7), "/": (7, 7), "%": (7, 7),
    "^": (10, 9),  # right associative
}
_UNARY_PRIORITY = 8


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.toks = tokens
        self.p = 0

    # -- token helpers
    @property
    def tok(self) -> Token:
        return self.toks[self.p]

    def peek(self, k: int = 1) -> Token:
        return self.toks[min(self.p + k, len(self.toks) - 1)]

    def next(self) -> Token:
        t = self.toks[self.p]
        if self.p < len(self.toks) - 1:
            self.p += 1
        return t

    def check(self, value: str) -> bool:
        t = self.tok
        return t.kind in ("op", "keyword") and t.value == value

    def accept(self, value: str) -> Token | None:
        if self.check(value):
            return self.next()
        return None

    def expect(self, value: str, opener: Token | None = None) -> Token:
        if self.check(value):
            return self.next()
        t = self.tok
        extra = f" (to close {opener.value!r} at line {opener.line})" if opener else ""
        raise LuaSyntaxError(f"expected {value!r} near {t.value or t.kind!r}{extra}", t.line, t.col)

    def expect_name(self) -> Token:
        t = self.tok
        if t.kind != "name":
            raise LuaSyntaxError(f"expected name near {t.value or t.kind!r}", t.line, t.col)
        return self.next()

    def prev_line(self) -> int:
        return self.toks[self.p - 1].line if self.p else 1

    # -- blocks
    def chunk(self) -> Node:
        start = self.tok
        body = self.block()
        if self.tok.kind != "eof":
            t = self.tok
            raise LuaSyntaxError(f"'<eof>' expected near {t.value!r}", t.line, t.col)
        node = N("Chunk", start, body=body)
        node.end_line = self.prev_line()
        return node

    def block_follow(self) -> bool:
        t = self.tok
        return t.kind == "eof" or (t.kind == "keyword" and t.value in ("else", "elseif", "end", "until"))

    def block(self) -> Node:
        start = self.tok
        stmts: list[Node] = []
        while not self.block_follow():
            if self.check("return"):
                stmts.append(self.return_stmt())
                break
            if self.check("break"):
                t = self.next()
                stmts.append(N("Break", t))
                self.accept(";")
                continue
            st = self.statement()
            if st is not None:
                stmts.append(st)
        node = N("Block", start, body=stmts)
        node.end_line = self.prev_line()
        return node

    def return_stmt(self) -> Node:
        t = self.next()
        exprs: list[Node] = []
        if not self.block_follow() and not self.check(";"):
            exprs = self.exprlist()
        self.accept(";")
        return N("Return", t, values=exprs)

    def statement(self) -> Node | None:
        t = self.tok
        if self.accept(";"):
            return None
        if t.kind == "keyword":
            v = t.value
            if v == "if":
                return self.if_stmt()
            if v == "while":
                self.next()
                cond = self.expr()
                self.expect("do")
                body = self.block()
                self.expect("end", t)
                return self._end(N("While", t, cond=cond, body=body))
            if v == "do":
                self.next()
                body = self.block()
                self.expect("end", t)
                return self._end(N("Do", t, body=body))
            if v == "for":
                return self.for_stmt()
            if v == "repeat":
                self.next()
                body = self.block()
                self.expect("until", t)
                cond = self.expr()
                return self._end(N("Repeat", t, body=body, cond=cond))
            if v == "function":
                return self.function_stmt()
            if v == "local":
                self.next()
                if self.accept("function"):
                    name = self.expect_name()
                    fn = self.funcbody(t, name=name.value)
                    target = N("Name", name, id=name.value)
                    return self._end(N("LocalFunction", t, name=target, func=fn))
                names = [self.expect_name()]
                while self.accept(","):
                    names.append(self.expect_name())
                values: list[Node] = []
                if self.accept("="):
                    values = self.exprlist()
                return self._end(N("Local", t, names=[N("Name", nt, id=nt.value) for nt in names], values=values))
        if self.check("::"):  # 5.2 label; tolerate
            self.next()
            self.expect_name()
            self.expect("::")
            return None
        return self.expr_stat()

    def _end(self, node: Node) -> Node:
        node.end_line = self.prev_line()
        return node

    def if_stmt(self) -> Node:
        t = self.next()
        clauses: list[tuple[Node, Node]] = []
        cond = self.expr()
        self.expect("then")
        clauses.append((cond, self.block()))
        orelse: Node | None = None
        while True:
            if self.accept("elseif"):
                c = self.expr()
                self.expect("then")
                clauses.append((c, self.block()))
                continue
            if self.accept("else"):
                orelse = self.block()
            self.expect("end", t)
            break
        node = N("If", t, clauses=clauses)
        if orelse is not None:
            node.a["orelse"] = orelse
        return self._end(node)

    def for_stmt(self) -> Node:
        t = self.next()
        first = self.expect_name()
        if self.accept("="):
            start = self.expr()
            self.expect(",")
            stop = self.expr()
            step = self.expr() if self.accept(",") else None
            self.expect("do")
            body = self.block()
            self.expect("end", t)
            node = N("NumFor", t, var=N("Name", first, id=first.value), start=start, stop=stop, body=body)
            if step is not None:
                node.a["step"] = step
            return self._end(node)
        names = [first]
        while self.accept(","):
            names.append(self.expect_name())
        self.expect("in")
        exprs = self.exprlist()
        self.expect("do")
        body = self.block()
        self.expect("end", t)
        return self._end(N("GenFor", t, names=[N("Name", nt, id=nt.value) for nt in names], iters=exprs, body=body))

    def function_stmt(self) -> Node:
        t = self.next()
        n = self.expect_name()
        target: Node = N("Name", n, id=n.value)
        dotted = [n.value]
        is_method = False
        while self.check(".") or self.check(":"):
            sep = self.next()
            key = self.expect_name()
            dotted.append(key.value)
            target = N("Index", key, obj=target, key=N("String", key, value=key.value), dot=True)
            if sep.value == ":":
                is_method = True
                break
        fn = self.funcbody(t, name=".".join(dotted), is_method=is_method)
        return self._end(N("FunctionDecl", t, target=target, func=fn, is_method=is_method))

    def funcbody(self, t: Token, name: str | None = None, is_method: bool = False) -> Node:
        opener = self.expect("(")
        params: list[Node] = []
        if is_method:
            params.append(Node("Name", t.line, t.col, t.line, {"id": "self", "implicit": True}))
        vararg = False
        if not self.check(")"):
            while True:
                if self.accept("..."):
                    vararg = True
                    break
                p = self.expect_name()
                params.append(N("Name", p, id=p.value))
                if not self.accept(","):
                    break
        self.expect(")", opener)
        body = self.block()
        self.expect("end", t)
        node = N("Function", t, params=params, body=body, vararg=vararg, fname=name)
        return self._end(node)

    def expr_stat(self) -> Node:
        t = self.tok
        e = self.suffixedexp()
        if self.check("=") or self.check(","):
            targets = [e]
            while self.accept(","):
                targets.append(self.suffixedexp())
            self.expect("=")
            values = self.exprlist()
            for tg in targets:
                if tg.kind not in ("Name", "Index"):
                    raise LuaSyntaxError("syntax error near '='", tg.line, tg.col)
            return self._end(N("Assign", t, targets=targets, values=values))
        if e.kind not in ("Call", "Method"):
            raise LuaSyntaxError("syntax error (statement expected)", t.line, t.col)
        return self._end(N("CallStmt", t, call=e))

    # -- expressions
    def exprlist(self) -> list[Node]:
        out = [self.expr()]
        while self.accept(","):
            out.append(self.expr())
        return out

    def primaryexp(self) -> Node:
        t = self.tok
        if t.kind == "name":
            self.next()
            return N("Name", t, id=t.value)
        if self.check("("):
            self.next()
            e = self.expr()
            self.expect(")", t)
            return self._end(N("Paren", t, expr=e))
        raise LuaSyntaxError(f"unexpected symbol near {t.value or t.kind!r}", t.line, t.col)

    def suffixedexp(self) -> Node:
        e = self.primaryexp()
        while True:
            t = self.tok
            if self.check("."):
                self.next()
                k = self.expect_name()
                e = Node("Index", e.line, e.col, k.line, {"obj": e, "key": N("String", k, value=k.value), "dot": True})
            elif self.check("["):
                self.next()
                k2 = self.expr()
                self.expect("]", t)
                e = Node("Index", e.line, e.col, self.prev_line(), {"obj": e, "key": k2, "dot": False})
            elif self.check(":"):
                self.next()
                m = self.expect_name()
                args = self.callargs()
                e = Node("Method", e.line, e.col, self.prev_line(), {"obj": e, "name": m.value, "args": args, "name_line": m.line})
            elif self.check("(") or self.check("{") or t.kind == "string":
                args = self.callargs()
                e = Node("Call", e.line, e.col, self.prev_line(), {"func": e, "args": args, "call_line": t.line})
            else:
                return e

    def callargs(self) -> list[Node]:
        t = self.tok
        if t.kind == "string":
            self.next()
            return [N("String", t, value=t.value)]
        if self.check("{"):
            return [self.table()]
        opener = self.expect("(")
        if self.accept(")"):
            return []
        args = self.exprlist()
        self.expect(")", opener)
        return args

    def table(self) -> Node:
        t = self.expect("{")
        fields: list[Node] = []
        while not self.check("}"):
            if self.check("["):
                ft = self.next()
                k = self.expr()
                self.expect("]", ft)
                self.expect("=")
                v = self.expr()
                fields.append(Node("Field", ft.line, ft.col, v.end_line or v.line, {"key": k, "value": v}))
            elif self.tok.kind == "name" and self.peek().kind == "op" and self.peek().value == "=":
                kt = self.next()
                self.next()
                v = self.expr()
                fields.append(Node("Field", kt.line, kt.col, v.end_line or v.line,
                                   {"key": N("String", kt, value=kt.value), "value": v, "named": True}))
            else:
                v = self.expr()
                fields.append(Node("Item", v.line, v.col, v.end_line or v.line, {"value": v}))
            if not (self.accept(",") or self.accept(";")):
                break
        self.expect("}", t)
        return self._end(N("Table", t, fields=fields))

    def simpleexp(self) -> Node:
        t = self.tok
        if t.kind == "number":
            self.next()
            return N("Number", t, value=t.value)
        if t.kind == "string":
            self.next()
            return N("String", t, value=t.value)
        if t.kind == "keyword":
            if t.value == "nil":
                self.next()
                return N("Nil", t)
            if t.value == "true":
                self.next()
                return N("True", t)
            if t.value == "false":
                self.next()
                return N("False", t)
            if t.value == "function":
                self.next()
                return self.funcbody(t)
        if self.check("..."):
            self.next()
            return N("Vararg", t)
        if self.check("{"):
            return self.table()
        return self.suffixedexp()

    def expr(self, limit: int = 0) -> Node:
        t = self.tok
        if (t.kind == "keyword" and t.value == "not") or (t.kind == "op" and t.value in ("-", "#")):
            self.next()
            operand = self.expr(_UNARY_PRIORITY)
            left: Node = Node("UnOp", t.line, t.col, operand.end_line or operand.line, {"op": t.value, "operand": operand})
        else:
            left = self.simpleexp()
        while True:
            op = self.tok
            if op.kind not in ("op", "keyword") or op.value not in _BINARY_PRIORITY:
                break
            lp, rp = _BINARY_PRIORITY[op.value]
            if lp <= limit:
                break
            self.next()
            right = self.expr(rp)
            left = Node("BinOp", left.line, left.col, right.end_line or right.line,
                        {"op": op.value, "left": left, "right": right})
        return left


# --------------------------------------------------------------------------- scopes


def _link_parents(root: Node) -> None:
    stack = [root]
    while stack:
        node = stack.pop()
        for child in node.children():
            child.parent = node
            stack.append(child)


class _Scope:
    __slots__ = ("names", "parent", "func")

    def __init__(self, parent: _Scope | None, func: Node | None) -> None:
        self.names: dict[str, Node] = {}
        self.parent = parent
        self.func = func

    def lookup(self, name: str) -> Node | None:
        s: _Scope | None = self
        while s is not None:
            if name in s.names:
                return s.names[name]
            s = s.parent
        return None


def resolve_scopes(chunk: Node) -> None:
    """Annotate ``Name`` nodes: ``decl`` (declaring Name node or None) and ``is_global``.

    Declaring names get ``is_decl=True``. Declarations also collect ``refs``.
    """

    def declare(scope: _Scope, name_node: Node) -> None:
        name_node.a["is_decl"] = True
        name_node.a["is_global"] = False
        name_node.a.setdefault("refs", [])
        scope.names[name_node.id] = name_node

    def use(scope: _Scope, name_node: Node, write: bool = False) -> None:
        decl = scope.lookup(name_node.id)
        name_node.a["decl"] = decl
        name_node.a["is_global"] = decl is None
        name_node.a["is_write"] = write
        if decl is not None:
            decl.a["refs"].append(name_node)

    def visit_block(block: Node, scope: _Scope) -> None:
        for st in block.body:
            visit_stmt(st, scope)

    def visit_func(fn: Node, scope: _Scope) -> None:
        inner = _Scope(scope, fn)
        for p in fn.params:
            declare(inner, p)
        visit_block(fn.body, inner)

    def visit_target(tg: Node, scope: _Scope) -> None:
        if tg.kind == "Name":
            use(scope, tg, write=True)
        else:
            visit_expr(tg, scope)

    def visit_stmt(st: Node, scope: _Scope) -> None:
        k = st.kind
        if k == "Local":
            for v in st.values:
                visit_expr(v, scope)
            for nm in st.names:
                declare(scope, nm)
        elif k == "LocalFunction":
            declare(scope, st.name)
            visit_func(st.func, scope)
        elif k == "FunctionDecl":
            visit_target(st.target, scope)
            visit_func(st.func, scope)
        elif k == "Assign":
            for v in st.values:
                visit_expr(v, scope)
            for tg in st.targets:
                visit_target(tg, scope)
        elif k == "CallStmt":
            visit_expr(st.call, scope)
        elif k == "Do":
            visit_block(st.body, _Scope(scope, scope.func))
        elif k == "While":
            visit_expr(st.cond, scope)
            visit_block(st.body, _Scope(scope, scope.func))
        elif k == "Repeat":
            inner = _Scope(scope, scope.func)
            visit_block(st.body, inner)
            visit_expr(st.cond, inner)
        elif k == "If":
            for cond, body in st.clauses:
                visit_expr(cond, scope)
                visit_block(body, _Scope(scope, scope.func))
            if "orelse" in st.a:
                visit_block(st.orelse, _Scope(scope, scope.func))
        elif k == "NumFor":
            visit_expr(st.start, scope)
            visit_expr(st.stop, scope)
            if "step" in st.a:
                visit_expr(st.step, scope)
            inner = _Scope(scope, scope.func)
            declare(inner, st.var)
            visit_block(st.body, inner)
        elif k == "GenFor":
            for e in st.iters:
                visit_expr(e, scope)
            inner = _Scope(scope, scope.func)
            for nm in st.names:
                declare(inner, nm)
            visit_block(st.body, inner)
        elif k == "Return":
            for v in st.values:
                visit_expr(v, scope)

    def visit_expr(e: Node, scope: _Scope) -> None:
        k = e.kind
        if k == "Name":
            use(scope, e)
        elif k == "Function":
            visit_func(e, scope)
        elif k == "Index":
            visit_expr(e.obj, scope)
            visit_expr(e.key, scope)
        elif k == "Call":
            visit_expr(e.func, scope)
            for a in e.args:
                visit_expr(a, scope)
        elif k == "Method":
            visit_expr(e.obj, scope)
            for a in e.args:
                visit_expr(a, scope)
        elif k == "Table":
            for f in e.fields:
                if f.kind == "Field":
                    visit_expr(f.key, scope)
                visit_expr(f.value, scope)
        elif k == "BinOp":
            visit_expr(e.left, scope)
            visit_expr(e.right, scope)
        elif k == "UnOp":
            visit_expr(e.operand, scope)
        elif k == "Paren":
            visit_expr(e.expr, scope)

    visit_block(chunk.body, _Scope(None, None))


# --------------------------------------------------------------------------- helpers


def parse(src: str) -> tuple[Node, list[Comment]]:
    tokens, comments = tokenize(src)
    chunk = Parser(tokens).chunk()
    _link_parents(chunk)
    resolve_scopes(chunk)
    return chunk, comments


def dotted_name(node: Node | None) -> str | None:
    """``C_Timer.After`` / ``frame.SetScript`` style name for Name/Index chains with string keys."""
    if node is None:
        return None
    if node.kind == "Name":
        return node.id
    if node.kind == "Index" and node.key.kind == "String" and node.dot:
        base = dotted_name(node.obj)
        if base is None:
            return None
        return f"{base}.{node.key.value}"
    if node.kind == "Index" and node.key.kind == "String":
        base = dotted_name(node.obj)
        return f"{base}.{node.key.value}" if base else None
    return None


def root_name(node: Node) -> Node | None:
    """Leftmost Name of an Index/Call/Method chain."""
    cur: Node | None = node
    while cur is not None:
        if cur.kind == "Name":
            return cur
        if cur.kind in ("Index", "Method"):
            cur = cur.obj
        elif cur.kind == "Call":
            cur = cur.func
        elif cur.kind == "Paren":
            cur = cur.expr
        else:
            return None
    return None


def call_name(call: Node) -> str | None:
    """Name of the called function: ``CreateFrame``, ``C_Timer.After``; methods return ``:Name``."""
    if call.kind == "Call":
        return dotted_name(call.func)
    if call.kind == "Method":
        return ":" + call.name
    return None


def string_arg(call: Node, index: int) -> str | None:
    args = call.args
    if index < len(args) and args[index].kind == "String":
        return str(args[index].value)
    return None


def enclosing_function(node: Node) -> Node | None:
    for anc in node.ancestors():
        if anc.kind == "Function":
            return anc
    return None


def loops_between(node: Node, stop: Node | None) -> list[Node]:
    """Loop statements enclosing ``node`` up to (not including) ``stop``."""
    out = []
    for anc in node.ancestors():
        if anc is stop:
            break
        if anc.kind in ("While", "Repeat", "NumFor", "GenFor"):
            out.append(anc)
    return out


def find_all(root: Node, pred: Callable[[Node], bool]) -> list[Node]:
    return [n for n in root.walk() if pred(n)]
