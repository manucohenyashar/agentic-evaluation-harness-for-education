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
import re
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

#: Word-stems that would mean the store had grown a search surface. `FR-STORE-08` names
#: similarity, embedding and free-text search; the rest are the words an author reaches for when
#: adding one without calling it search.
#:
#: Matched as **stems within the identifier**, not as whole names — review found that an exact
#: `name.lower() in SEARCH_METHOD_NAMES` check passed `similarity_search`, `find_similar`,
#: `search_text` and `query_by_text`, which is every realistic way such a method would actually be
#: named. See `is_search_name`.
SEARCH_METHOD_NAMES: frozenset[str] = frozenset(
    {
        "search", "similarity", "similar", "embedding", "embed", "vector_search",
        "nearest", "knn", "match", "fulltext", "fts", "find_text", "semantic",
        "relevance", "rank", "by_text", "free_text", "text_search", "text_query",
    }
)

#: Stems that are too short or too common to match as substrings without false positives, so they
#: are required to be a whole word within the identifier.
_WHOLE_WORD_STEMS: frozenset[str] = frozenset({"match", "rank", "knn", "fts", "similar"})


def is_search_name(name: str) -> bool:
    """Does this identifier name a search surface?

    Stem matching, because the exact-name check this replaced passed every compound an author
    would actually write. `similar` is a stem of `similarity`, so `find_similar`,
    `similarity_search` and `most_similar` all match; `match` is required to be a whole word so
    `batch_size` and `dispatch` do not.
    """
    lowered = name.lower()
    words = set(lowered.replace("-", "_").split("_"))
    for stem in SEARCH_METHOD_NAMES:
        if stem in _WHOLE_WORD_STEMS:
            if stem in words or any(word.startswith(stem) for word in words):
                return True
        elif stem in lowered:
            return True
    return False


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


#: Word-boundary match per keyword, over whitespace-normalized text.
#:
#: The first draft space-padded the string and searched for `" select "`, which meant a keyword
#: preceded by a newline never matched — so SQL written the way anyone writes it, across lines in
#: a triple-quoted literal, was invisible to every text-shape rule at once. Review found it by
#: measurement: `_looks_like_sql("SELECT id\\nFROM roster\\nWHERE n = 'x'")` returned `False`.
#: Punctuation-adjacency (`SELECT (id) FROM(t)`) failed the same way.
_KEYWORD_PATTERNS: dict[str, "re.Pattern[str]"] = {}


def _looks_like_sql(text: str) -> bool:
    """Two distinct SQL keywords, so English prose does not trip the scan.

    One keyword is not enough — "set the value" and "update the roster" are ordinary sentences,
    and a scanner that flags them gets silenced. Two is the point where a string is a statement:
    `select ... from`, `insert ... into`, `update ... set`.

    Whitespace is normalized first and each keyword is matched on word boundaries, so a statement
    formatted across lines reads the same as one on a single line — which is the whole point,
    since the multi-line form is the normal one.
    """
    normalized = " ".join(text.lower().split())
    hits = 0
    for keyword in SQL_KEYWORDS:
        pattern = _KEYWORD_PATTERNS.get(keyword)
        if pattern is None:
            pattern = re.compile(rf"\b{re.escape(keyword)}\b")
            _KEYWORD_PATTERNS[keyword] = pattern
        if pattern.search(normalized):
            hits += 1
            if hits >= 2:
                return True
    return False


#: Calls that return their string argument unchanged, so a statement wrapped in one is still
#: declared. Without these the walker flags `textwrap.dedent("""SELECT ...""")` — the ordinary way
#: to write a multi-line statement — which is a false positive on the sanctioned form.
_LITERAL_PRESERVING_CALLS: frozenset[str] = frozenset({"dedent", "strip", "lstrip", "rstrip"})


def _is_declared(node: ast.AST) -> bool:
    """Is this expression provably a string literal at parse time?

    A literal, a `+` chain of literals (implicit concatenation already folds to one `Constant`),
    or a literal wrapped in a call that cannot change it. Everything else is *not proven* declared
    — which is not the same as proven bad, and the caller decides what to do about the difference.
    """
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_declared(node.left) and _is_declared(node.right)
    if isinstance(node, ast.Call):
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name in _LITERAL_PRESERVING_CALLS and node.args:
            return _is_declared(node.args[0])
    return False


def _flag(node: ast.AST, kind: str, detail: str, module: str, relative: str) -> SqlViolation:
    return SqlViolation(
        module=module,
        path=relative,
        line=getattr(node, "lineno", 0),
        kind=kind,
        detail=detail,
    )


#: How a name reaching an execute call was bound, within one scope.
LITERAL = "literal"      # bound to a provably-declared statement
COMPUTED = "computed"    # bound to something assembled at run time
PARAMETER = "parameter"  # a function argument: whatever the caller passed


def _scope_bindings(tree: ast.AST) -> dict[ast.AST, dict[str, str]]:
    """`{scope node: {name: LITERAL | COMPUTED | PARAMETER}}`, one entry per function plus module.

    **Per scope, not per file**, and the difference is a blocker the review caught by
    measurement. The first draft collected computed names across the whole file, so an unrelated
    helper binding `stmt = raw.strip()` made *every* `execute(stmt)` in the module a violation —
    including the byte-for-byte shape this suite's own negative control declares sanctioned.
    `sql`, `stmt` and `query` are the three commonest identifiers in a store module, so that
    reds the build on the first ordinary `M-STORE` commit. A false finding is worse than a miss
    here: it is the one that gets the scanner switched off.

    Function parameters are their own category. `def _run(c, stmt): return c.execute(stmt)` is a
    passthrough — the walker cannot see what the caller passed, and "cannot see" is not "safe".
    """
    bindings: dict[ast.AST, dict[str, str]] = {}

    def visit(scope: ast.AST, body: list[ast.stmt], args: ast.arguments | None) -> None:
        names: dict[str, str] = {}
        if args is not None:
            for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                names[arg.arg] = PARAMETER
            for extra in (args.vararg, args.kwarg):
                if extra is not None:
                    names[extra.arg] = PARAMETER

        for node in ast.walk(scope):
            # A nested function has its own scope; its assignments are not this one's.
            if node is not scope and isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
            ):
                continue
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            elif isinstance(node, ast.AugAssign):
                targets, value = [node.target], node.value
            elif isinstance(node, ast.NamedExpr):
                # `if (q := build(t)): c.execute(q)` — missing from the first draft entirely.
                targets, value = [node.target], node.value
            else:
                continue
            if _is_declared(value):
                kind = LITERAL
            elif isinstance(value, ast.Name):
                # One hop of alias resolution: `stmt = SELECT_BY_ID` where `SELECT_BY_ID` is a
                # module-level literal is a declared statement, not a computed one. Without this
                # the walker flags the ordinary way a store names its statements — and a false
                # positive on the sanctioned form is what gets a scanner switched off.
                inherited = names.get(value.id) or bindings.get(tree, {}).get(value.id)
                kind = LITERAL if inherited == LITERAL else COMPUTED
            else:
                kind = COMPUTED
            for target in targets:
                if isinstance(target, ast.Name):
                    # An augmented assignment can only make a name less declared, never more.
                    if isinstance(node, ast.AugAssign) or names.get(target.id) != COMPUTED:
                        names[target.id] = COMPUTED if isinstance(node, ast.AugAssign) else kind
        bindings[scope] = names

    module_body = getattr(tree, "body", [])
    visit(tree, module_body, None)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit(node, node.body, node.args)
    return bindings


def _enclosing_scope(tree: ast.AST, target: ast.AST) -> ast.AST:
    """The innermost function containing `target`, or the module."""
    best: ast.AST = tree
    best_span = -1
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start, end = node.lineno, node.end_lineno or node.lineno
        line = getattr(target, "lineno", 0)
        if start <= line <= end and (end - start) >= 0:
            span = end - start
            if best_span < 0 or span <= best_span:
                best, best_span = node, span
    return best


#: Keyword names a statement can arrive under. `db.execute(sql=built)` reaches SQLite exactly as
#: `db.execute(built)` does, and the first draft read positional arguments only.
STATEMENT_KEYWORDS: frozenset[str] = frozenset({"sql", "stmt", "statement", "query", "operation"})


def _statement_problem(
    statement: ast.AST, names: dict[str, str], module_names: dict[str, str]
) -> str | None:
    """Why this expression is not a declared statement, or `None` if it is one.

    The three unprovable shapes are named separately because they fail for different reasons and
    a reader fixing one wants to know which.

    An `Attribute` or `Subscript` (`Statements.SELECT_BY_ID`, `STATEMENTS["by_id"]`) is **not**
    flagged: a table of declared statements is the sanctioned pattern, and whatever assembled a
    bad one is caught by the text-shape rules above. A `Name` the walker cannot find in any scope
    is likewise left alone — it is an import, conventionally a declared constant, and flagging
    every one would make the scan unusable in the module it exists for.
    """
    if _is_declared(statement):
        return None
    if isinstance(statement, ast.Starred):
        return "unpacked from a sequence, so its contents cannot be checked"
    if isinstance(statement, ast.JoinedStr):
        return "an f-string"
    if isinstance(statement, ast.BinOp):
        return "assembled by an operator"
    if isinstance(statement, ast.Call):
        return "the return value of a call"
    if isinstance(statement, ast.Name):
        binding = names.get(statement.id) or module_names.get(statement.id)
        if binding == COMPUTED:
            return f"{statement.id!r}, assigned from a computed expression"
        if binding == PARAMETER:
            return (
                f"{statement.id!r}, a parameter — whatever the caller passed reaches SQLite "
                f"unchecked"
            )
    return None


def scan_module(module: str, path: Path, repo_root: Path) -> list[SqlViolation]:
    """Every SQL string in one file that is assembled rather than declared."""
    relative = path.relative_to(repo_root).as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:  # a file that does not parse is a defect, not a pass
        return [_flag(ast.Module(), "unparseable", str(exc), module, relative)]

    violations: list[SqlViolation] = []
    bindings = _scope_bindings(tree)

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

            # -- what actually reaches an execute path. This is the rule that matters, and the
            #    positive control is what produced it: `head + body + tail`, each part assigned
            #    on its own line, carries no single string a keyword check can read, so every
            #    text-shape rule above walks past it. `FR-STORE-08` asks for *declared* queries,
            #    so the assertion is about the argument's provenance rather than its contents.
            if name in EXECUTE_METHODS and name != "executescript":
                scope = _enclosing_scope(tree, node)
                names = bindings.get(scope, {})
                module_names = bindings.get(tree, {})

                # Positionally, and by keyword. The first draft read `node.args[0]` only, so
                # `db.execute(sql=built)` and `c.execute(*[raw])` both walked through.
                candidates: list[tuple[str, ast.AST]] = []
                if node.args:
                    candidates.append(("statement", node.args[0]))
                for keyword in node.keywords:
                    if keyword.arg in STATEMENT_KEYWORDS:
                        candidates.append((keyword.arg, keyword.value))

                for label, statement in candidates:
                    problem = _statement_problem(statement, names, module_names)
                    if problem is not None:
                        violations.append(
                            _flag(node, "computed-statement",
                                  f"{name}() is given a {label} that is {problem}; "
                                  f"declared statements only (FR-STORE-08)",
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
