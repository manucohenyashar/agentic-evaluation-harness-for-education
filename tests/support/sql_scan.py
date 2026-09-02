"""The SQL-construction walker behind `SEC-15`.

`FR-STORE-08`: *"The module shall expose no method that performs similarity, embedding, or
free-text search over any tier reachable from the scoring path; the store interface offers keyed
lookup and declared queries only."* Design §3.3 makes "declared" concrete in the type:

    class TierHandle(Protocol):
        def query(self, stmt: Statement, **params) -> Sequence[Row]: ...

A `Statement`, not a `str`, and parameters as keywords rather than interpolated text. That is the
whole defence, and it is a *shape* defence: there is no place to put an injection because there is
no place to put free text.

**This module is the source-level half, and it is not SEC-15's stated probe.** §6.5's probe is
behavioural — *"attempt free-text and similarity queries against every tier reachable from the
scoring path"* — which needs a real `Store`, and `M-STORE` does not exist yet. That half lives in
`test_store_query_surface.py` behind `writtenahead`. This half is an addition: it asserts that no
module in the source tree *builds* SQL by string manipulation, which is the defect the behavioural
probe cannot see (a store with a perfectly clean surface can still assemble a `WHERE` clause with
an f-string inside a declared statement).

Parses rather than greps, for the reason `import_graph` gives: an f-string SQL fragment split
across a `+` chain, or built in a helper and passed in, is invisible to a line scan and is exactly
what an author reaches for when a literal will not do.

**Deliberately narrow.** It flags SQL text assembled from non-literal parts, and nothing else. A
literal string containing `%s` is fine (it may not even be SQL); a `.format()` call on a string
with no SQL keyword is fine. The scan asks one question: *does a value that reaches a database
execute path carry a fragment this module cannot see?*
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from tests.support.import_graph import SOURCE_ROOTS, source_files

#: The keywords that make a string SQL rather than prose. Deliberately the *statement-initial*
#: verbs plus the clause keywords an injection lands in — a docstring mentioning "select" in
#: English does not match, because the check is on a word-boundary uppercase-insensitive match
#: against a string that also carries a second SQL token (see `_looks_like_sql`).
SQL_KEYWORDS: frozenset[str] = frozenset(
    {
        "select", "insert", "update", "delete", "create", "drop", "alter",
        "from", "where", "values", "join", "into", "set", "table", "index",
        "pragma", "attach", "vacuum", "order by", "group by", "limit",
    }
)

#: The calls that hand a string to SQLite. `executescript` is included and is the sharpest of
#: them: it takes no parameters at all, so *every* value in it is interpolated by construction.
EXECUTE_METHODS: frozenset[str] = frozenset(
    {"execute", "executemany", "executescript", "execute_insert", "execute_fetchall"}
)

#: Method names that would mean the store had grown a search surface. `FR-STORE-08` names
#: similarity, embedding and free-text search; the rest are the words an author reaches for when
#: adding one without calling it search.
SEARCH_METHOD_NAMES: frozenset[str] = frozenset(
    {
        "search", "similarity", "similar", "embedding", "embed", "vector_search",
        "nearest", "knn", "match", "fulltext", "full_text", "fts", "like_query",
        "find_text", "text_search", "semantic_search", "rank", "relevance",
    }
)


@dataclass(frozen=True)
class SqlViolation:
    """One place SQL text is assembled from something other than a literal.

    Carries a file:line a reader can open, for the same reason `import_graph.Violation` does: a
    security case whose failure message says only "3 violations" gets muted rather than fixed.
    """

    module: str
    path: str  # repo-relative, POSIX separators
    line: int
    kind: str  # "fstring" | "concat" | "percent" | "format-call" | "executescript"
    detail: str

    def __str__(self) -> str:
        return f"{self.module} ({self.path}:{self.line}) {self.kind}: {self.detail}"


def _string_parts(node: ast.AST) -> list[str]:
    """Every literal string fragment reachable from `node` without evaluating anything."""
    parts: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            parts.append(child.value)
    return parts


def _looks_like_sql(text: str) -> bool:
    """Two distinct SQL keywords, so English prose does not trip the scan.

    One keyword is not enough — "set the value" and "update the roster" are ordinary sentences,
    and a scanner that flags them gets silenced. Two is the point where a string is a statement:
    `select ... from`, `insert ... into`, `update ... set`.
    """
    lowered = f" {text.lower()} "
    hits = {kw for kw in SQL_KEYWORDS if f" {kw} " in lowered}
    return len(hits) >= 2


def _flag(node: ast.AST, kind: str, detail: str, module: str, relative: str) -> SqlViolation:
    return SqlViolation(
        module=module,
        path=relative,
        line=getattr(node, "lineno", 0),
        kind=kind,
        detail=detail,
    )


def _computed_names(tree: ast.AST) -> set[str]:
    """Names assigned from something other than a string literal, per file.

    The cheap half of dataflow, and it earns its place: `sql = head + body; execute(sql)` passes
    a bare `Name` to `execute`, so an argument-shape rule alone waves it through. Whole-file
    rather than per-function scope, deliberately — that over-approximates (a name computed in one
    function and a literal in another is flagged), and over-approximating is the safe direction
    for a security case: a false positive is a conversation, a false negative is an injection.
    """
    computed: set[str] = set()
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AugAssign):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                computed.add(target.id)
    return computed


def scan_module(module: str, path: Path, repo_root: Path) -> list[SqlViolation]:
    """Every SQL string in one file that is assembled rather than declared."""
    relative = path.relative_to(repo_root).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:  # a file that does not parse is a defect, not a pass
        return [_flag(ast.Module(), "unparseable", str(exc), module, relative)]

    violations: list[SqlViolation] = []
    computed = _computed_names(tree)

    for node in ast.walk(tree):
        # -- an f-string whose literal parts read as SQL
        if isinstance(node, ast.JoinedStr):
            literal = "".join(
                v.value for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
            interpolated = any(isinstance(v, ast.FormattedValue) for v in node.values)
            if interpolated and _looks_like_sql(literal):
                violations.append(
                    _flag(node, "fstring", f"f-string SQL: {literal.strip()[:60]!r}",
                          module, relative)
                )

        # -- `"SELECT ..." + variable`, in either order and at any depth of the chain
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            parts = _string_parts(node)
            if parts and _looks_like_sql(" ".join(parts)):
                non_literal = any(
                    not (isinstance(side, ast.Constant) and isinstance(side.value, str))
                    and not isinstance(side, (ast.BinOp, ast.JoinedStr))
                    for side in (node.left, node.right)
                )
                if non_literal:
                    violations.append(
                        _flag(node, "concat", f"SQL built by +: {' '.join(parts)[:60]!r}",
                              module, relative)
                    )

        # -- `"SELECT ... %s" % value`
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            parts = _string_parts(node.left)
            if parts and _looks_like_sql(" ".join(parts)):
                violations.append(
                    _flag(node, "percent", f"SQL built by %: {' '.join(parts)[:60]!r}",
                          module, relative)
                )

        elif isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None)

            # -- `"SELECT ... {}".format(value)`
            if name == "format" and isinstance(func, ast.Attribute):
                parts = _string_parts(func.value)
                if parts and _looks_like_sql(" ".join(parts)):
                    violations.append(
                        _flag(node, "format-call",
                              f"SQL built by .format(): {' '.join(parts)[:60]!r}",
                              module, relative)
                    )

            # -- `executescript` takes no parameters, so everything in it is interpolated.
            #    Flagged wherever it appears, literal or not: it is the one execute path with
            #    no parameterized form available.
            elif name == "executescript":
                violations.append(
                    _flag(node, "executescript",
                          "executescript() accepts no parameters, so nothing in it can be "
                          "parameterized; use execute() with a declared statement",
                          module, relative)
                )

            # -- what actually reaches an execute path. This is the rule that matters, and it
            #    came from the positive control: `head + body + tail`, each part assigned on its
            #    own line, carries no single string a keyword check can read, so every
            #    text-shape rule above walks past it. `FR-STORE-08` asks for *declared* queries,
            #    so the assertion is about the argument's shape rather than its contents — a
            #    literal, or a name bound to one, and nothing computed.
            if name in EXECUTE_METHODS and name != "executescript" and node.args:
                statement = node.args[0]
                if isinstance(statement, (ast.JoinedStr, ast.BinOp, ast.Call)):
                    violations.append(
                        _flag(node, "computed-statement",
                              f"{name}() is given a statement computed inline "
                              f"({type(statement).__name__}); declared statements only",
                              module, relative)
                    )
                elif isinstance(statement, ast.Name) and statement.id in computed:
                    violations.append(
                        _flag(node, "computed-statement",
                              f"{name}() is given {statement.id!r}, which is assigned from a "
                              f"computed expression rather than a literal",
                              module, relative)
                    )

    return violations


def scan_tree(repo_root: Path, roots: Iterable[str] = SOURCE_ROOTS) -> list[SqlViolation]:
    """Every assembled-SQL site under the scanned roots."""
    violations: list[SqlViolation] = []
    for module, path in source_files(repo_root, roots):
        violations.extend(scan_module(module, path, repo_root))
    return violations


def execute_call_sites(repo_root: Path, roots: Iterable[str] = SOURCE_ROOTS) -> list[str]:
    """Every call to a database execute method, as `module:line`.

    Exposed so a test can assert the scan has something to look at. A "no assembled SQL"
    result over a tree that issues no SQL at all is true and worthless, and this is how that
    is told apart from a real pass.
    """
    sites: list[str] = []
    for module, path in source_files(repo_root, roots):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) in EXECUTE_METHODS:
                sites.append(f"{module}:{node.lineno}")
    return sites
