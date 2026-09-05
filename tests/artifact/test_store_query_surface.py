"""`SEC-15` — the store-interface boundary. Test plan §6.5, TS-57 (issue #150).

*"Attempt free-text and similarity queries against every tier reachable from the scoring path.
No such interface exists; parameterized declared statements only."* — `FR-STORE-08`, Injection /
OWASP A03.

**Two halves, and only one of them is the plan's stated probe.**

The probe §6.5 names is *behavioural*: call into a real `Store` and assert the method is not
there. That needs `M-STORE`, which does not exist, so it lands behind `writtenahead` at the bottom
of this file.

The other half is an **addition**, not a substitute: a source-level scan asserting no module
assembles SQL from anything but a declared statement. It is worth having because it catches the
defect the behavioural probe structurally cannot see — a store with a perfectly clean surface can
still build a `WHERE` clause with an f-string *inside* a declared statement, and every
absence-assertion over the public interface passes while it does.

Design §3.3 is what makes the source half assertable rather than a matter of taste:

    class TierHandle(Protocol):
        def query(self, stmt: Statement, **params) -> Sequence[Row]: ...

A `Statement`, not a `str`; parameters as keywords, not interpolated text. There is no place to
put an injection because there is no place to put free text — a *shape* defence, and a shape is
something a parser can check.

**Why the positive control below is not decoration.** `src/` holds `aeh.conf` and `aeh.prov`, and
neither issues a single SQL statement. "Zero assembled-SQL sites in the source tree" is therefore
true of the tree, true of a scanner that returns `[]` unconditionally, and true of a scanner with
a typo in every pattern — three claims a green result cannot tell apart. The control makes them
distinguishable, and it has already earned its keep: it caught a chain assembled across three
lines that every text-shape rule in the walker walked straight past, which is why `sql_scan` now
asserts on what reaches `execute()` rather than only on what looks like SQL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.impl import STORE_MODULE, require
from tests.support.sql_scan import (
    EXECUTE_METHODS,
    execute_call_sites,
    is_search_name,
    scan_module,
    scan_tree,
)

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The deliberately-bad module the walker is proved against. Outside `src/`, so `scan_tree` does
#: not walk it — a control that failed the assertion it supports would be useless.
BROKEN_SQL_FIXTURE = REPO_ROOT / "tests" / "support" / "broken_sql_fixture.py"


# --- the source-level half (an addition to the plan's probe) ----------------------------------


def test_sec_15_no_module_assembles_a_sql_statement():
    """No module under `src/` or `harness/` builds SQL from anything but a declared statement.

    The oracle is an **artifact assertion over the source tree**: zero sites, each violation
    naming module, file, line and the form it took, so the failure is actionable without opening
    the walker.

    Green today because no module issues SQL at all. That is a real state of the system, not a
    vacuous pass — the control below is what proves the scanner would speak up — and this case
    is the one that fires on the first `M-STORE` commit that reaches for an f-string.
    """
    violations = scan_tree(REPO_ROOT)

    assert not violations, (
        "SEC-15: SQL is being assembled rather than declared. `FR-STORE-08` offers keyed lookup "
        "and declared statements only, and design §3.3 types the argument as `Statement` "
        "precisely so free text has nowhere to go:\n  "
        + "\n  ".join(str(v) for v in violations)
    )


@pytest.mark.parametrize(
    "function, form, kind",
    [
        ("by_name", "f-string", "fstring"),
        ("by_cohort", "concatenation", "concat"),
        ("by_status", "percent formatting", "percent"),
        ("ordered_by", ".format()", "format-call"),
        ("migrate", "executescript", "executescript"),
        ("split_across_lines", "a chain assembled across statements", "computed-statement"),
    ],
)
def test_sec_15_the_walker_catches_every_form_of_assembly(function, form, kind):
    """The positive control, one row per **rule** the walker claims to enforce.

    The `kind` column is the whole assertion, and its absence was a blocker. The first draft
    checked only that *some* violation fell inside the function's line range — and every one of
    these functions is caught twice, once by the rule it is named after and once by the
    execute-argument rule. So disabling four of the six rules outright (review did it, by
    stubbing `_looks_like_sql` to return `False`) left all six rows green. Six assertions
    collapsed to two.

    Asserting the kind pins each rule to the row that exists for it, so a regression names the
    form that stopped being caught rather than reporting nothing at all.
    """
    import ast

    source = BROKEN_SQL_FIXTURE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(BROKEN_SQL_FIXTURE))
    target = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function
    )

    within = {
        v.kind for v in scan_module("broken_sql_fixture", BROKEN_SQL_FIXTURE, REPO_ROOT)
        if target.lineno <= v.line <= (target.end_lineno or target.lineno)
    }

    assert kind in within, (
        f"SEC-15: the walker no longer catches {function}() ({form}) by its own rule. It "
        f"reported {sorted(within) or 'nothing'}, and {kind!r} is missing. The control exists "
        "because the real tree issues no SQL, so a silent rule and a clean tree look identical."
    )


#: The legitimate ways a store names a statement. Every one of these must scan clean.
#:
#: One negative control was not enough, and review proved it with measurement: four of these five
#: were flagged by the first draft, including the shape the single control itself wrote. `sql`,
#: `stmt` and `query` are the commonest identifiers in a store module, so a walker that
#: false-positives here reds the build on the first ordinary `M-STORE` commit — a *false* finding,
#: which against this issue's Goal ("fail the build on a finding") is worse than a miss.
DECLARED_FORMS: dict[str, str] = {
    "a module constant, used directly": '''
SELECT_BY_ID = "SELECT id, status FROM work_unit WHERE id = ?"

def fetch(connection, unit_id):
    return connection.execute(SELECT_BY_ID, (unit_id,))
''',
    "a local literal, while an unrelated helper binds the same name": '''
def unrelated_helper(raw):
    stmt = raw.strip()
    return stmt

def fetch(connection, unit_id):
    stmt = "SELECT id, status FROM work_unit WHERE id = ?"
    return connection.execute(stmt, (unit_id,))
''',
    "textwrap.dedent over a multi-line literal": '''
import textwrap

SELECT_BY_ID = textwrap.dedent("""
    SELECT id, status
    FROM work_unit
    WHERE id = ?
""")

def fetch(connection, unit_id):
    return connection.execute(SELECT_BY_ID, (unit_id,))
''',
    "implicit concatenation across lines": '''
def fetch(connection, unit_id):
    return connection.execute(
        "SELECT id, status "
        "FROM work_unit "
        "WHERE id = ?",
        (unit_id,),
    )
''',
    "a table of declared statements": '''
STATEMENTS = {"by_id": "SELECT id, status FROM work_unit WHERE id = ?"}

def fetch(connection, unit_id):
    return connection.execute(STATEMENTS["by_id"], (unit_id,))
''',
}


@pytest.mark.parametrize("form", sorted(DECLARED_FORMS), ids=lambda f: f[:38])
def test_sec_15_the_walker_reports_nothing_against_a_declared_statement(form, tmp_path):
    """The negative controls — the walker must not flag the *correct* forms.

    A scanner that flags everything passes every positive control above and is worthless: the
    first `M-STORE` commit turns it off. So each shape `FR-STORE-08` sanctions gets its own row,
    and the row names the shape so a false positive says which one broke.

    Written into `tmp_path`, not the repository. The first draft wrote its probe into
    `tests/support/` and unlinked it in a `finally` — a killed process left an untracked file
    behind in the tree the sibling case scans.
    """
    probe = tmp_path / "declared_probe.py"
    probe.write_text(DECLARED_FORMS[form], encoding="utf-8")

    violations = scan_module("declared_probe", probe, tmp_path)

    assert not violations, (
        f"SEC-15: the walker flagged a correctly declared statement ({form}). A scanner with "
        "false positives on the sanctioned form is one somebody switches off:\n  "
        + "\n  ".join(str(v) for v in violations)
    )


#: Every place in `src/` or `harness/` that hands a statement to SQLite, as `module:line`.
#:
#: Transcribed rather than computed, for the reason `SEC-14` transcribes the dependency set — the
#: value of the constant is that changing it is a diff somebody reads.
#:
#: **Two entries, and one place SQL actually reaches SQLite.** `M-STORE` routes every statement
#: through a single `_run()` helper, so this list stays something a reviewer reads rather than
#: scrolls. #10 built that helper; #11 added the write queue, its batch `BEGIN`/`COMMIT`/
#: `ROLLBACK` and `Tx.execute`, all of them through `_run`; #12 added the blob store and the
#: lease clock; #13 added the Tier D guard, the purge machinery and the name vocabulary. The
#: line number has moved as each story declared constants above it (710 -> 778 -> 916 -> 1493
#: on this line), which is the re-read this constant exists to force.
#:
#: **The second entry is not a second place SQL reaches SQLite.**
#: `aeh.store:2268` is `LeaseClock._persist` calling `tx.execute(STATEMENTS["upsert_lease_clock"],
#: ...)` — `Tx.execute` is the module's own declared-statement API and delegates to `_run`, which
#: is still the only site that touches a `sqlite3` cursor. The walker cannot see that, and
#: shouldn't: it flags every `execute()` and asks a human whether the argument is a declared
#: statement with keyword parameters. It is — from the registry, which is the shape
#: `sql_scan._statement_problem` names as sanctioned. `aeh.store:1493` is `_run` itself, moved
#: again by #12's and #13's own declarations. What is passed there is `declared.sql` — an attribute of a declared
#: `Statement`, which is the shape `sql_scan._statement_problem` sanctions — never the parameter,
#: which would mean "whatever the caller passed reaches SQLite unchecked".
#:
#: The line number is part of the entry, so an edit above the site fails this case. That is
#: annoying and it is the point: the constant exists to be re-read, and a site that moved is a
#: site somebody should look at again.
KNOWN_EXECUTE_SITES: frozenset[str] = frozenset({"aeh.store:1493", "aeh.store:2268"})


def test_sec_15_every_database_execute_site_is_one_somebody_has_looked_at():
    """The set of execute sites, asserted as an exact set rather than reported.

    This is what tells "clean tree" apart from "clean store". The scan above returns zero
    violations today because nothing in `src/` issues SQL at all — a true result that says
    nothing about `M-STORE`, and a reader has no way to know which of the two they are seeing.

    A `pytest.skip` here was the first draft and it was worse than nothing: a test that always
    skips is a line in the output nobody reads, and it would have gone on skipping after the
    store landed. As a **set equality** it is a tripwire instead — the first `execute()` in the
    source tree fails this case and puts the site in front of a reviewer, next to the walker that
    has to be right about it.
    """
    sites = set(execute_call_sites(REPO_ROOT))

    assert EXECUTE_METHODS, "the walker recognizes no execute method, so it inspects nothing"
    assert sites == KNOWN_EXECUTE_SITES, (
        "SEC-15: the set of database execute sites changed.\n"
        f"  new:     {sorted(sites - KNOWN_EXECUTE_SITES)}\n"
        f"  gone:    {sorted(KNOWN_EXECUTE_SITES - sites)}\n"
        "Each new site is a place a statement reaches SQLite. Confirm it passes a declared "
        "statement with keyword parameters (FR-STORE-08, design §3.3), then add it here."
    )


# --- the behavioural half: the plan's own probe, blocked on M-STORE ---------------------------


def test_sec_15_no_tier_exposes_a_free_text_or_similarity_query():
    """`SEC-15`'s stated probe — *"attempt free-text and similarity queries against every tier
    reachable from the scoring path"*.

    An **absence assertion over the real interface**, which is the only form that answers the
    threat. `FR-STORE-08`: *"no method that performs similarity, embedding, or free-text search
    over any tier reachable from the scoring path; the store interface offers keyed lookup and
    declared queries only."*

    **What this checks, precisely.** `Store` and `TierHandle` are `Protocol`s, so the assertion
    is reflective — every public member of both, plus the module surface — rather than a call
    against a live tier. §6.5's probe says *"every tier reachable from the scoring path"*, and
    `package()`, `cohort()` and `durable()` all return a `TierHandle`, so checking the protocol
    covers all three *as far as the protocol goes*. It does **not** reach a concrete class that
    implements `TierHandle` and adds an off-protocol `search()`. Closing that needs a real
    instance, which needs the tiers to be constructible; it belongs with `TS-08`/`TS-09` (#14,
    #15), and is recorded here rather than implied by a green tick.

    The second half is what makes it more than a name check: `TierHandle.query` must take a
    `Statement`, not a `str`. A store that grew `query(sql: str)` exposes no method *named*
    search and is an arbitrary-SQL passthrough, which is exactly A03.

    **Registered on #10, not #13.** `FR-STORE-08` belongs to #13, but the discriminating question
    is *which single blocker, resolved, makes this test runnable and non-vacuous* — and that is
    #10, which creates `aeh.store` and the `Store`/`TierHandle` protocols. An absence assertion
    over a class becomes real the moment the class exists; keying on #13 would leave it red for
    two stories after it could have been catching things. Same reasoning that moved `TC-CONF-17`
    to #57 and `TC-CONF-C14` step 3 to #122.
    """
    import inspect

    store_module = require(STORE_MODULE, issue="#10")
    Store = require(STORE_MODULE, "Store", issue="#10")
    TierHandle = require(STORE_MODULE, "TierHandle", issue="#10")

    offenders: list[str] = []

    for owner in (Store, TierHandle):
        for name in dir(owner):
            if name.startswith("_"):
                continue
            if is_search_name(name):
                offenders.append(f"{owner.__name__}.{name}() is a search surface")

    # `query` takes a declared `Statement`, never a raw string.
    #
    # The first draft read `parameters.get("stmt", "").annotation`, which had three faults review
    # found by simulating four candidate signatures: it raised `AttributeError` on a differently
    # named parameter (`sql`, `statement`) rather than reporting a finding, and — the real hole —
    # an **unannotated** `stmt` stringified to `<class 'inspect._empty'>`, containing neither
    # "str" nor "Statement", so a raw-SQL passthrough with no type hint passed silently. That is
    # the exact A03 shape this limb exists to catch.
    query = getattr(TierHandle, "query", None)
    assert query is not None, "TierHandle exposes no query() at all — design §3.3 declares one"

    parameters = [
        parameter for name, parameter in inspect.signature(query).parameters.items()
        if name != "self" and parameter.kind not in (
            inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD
        )
    ]
    assert parameters, "TierHandle.query takes no statement argument at all"
    statement_parameter = parameters[0]

    if statement_parameter.annotation is inspect.Parameter.empty:
        offenders.append(
            f"TierHandle.query({statement_parameter.name}) is unannotated, so nothing stops a "
            "raw SQL string being passed — design §3.3 types it `Statement` precisely to close "
            "that door"
        )
    else:
        annotation = str(statement_parameter.annotation)
        if "Statement" not in annotation:
            offenders.append(
                f"TierHandle.query({statement_parameter.name}: {annotation}) does not take a "
                "declared Statement — a raw-SQL passthrough is A03 whatever the method is called"
            )

    # And nothing at module level either: a free function taking a tier and a search string is
    # the same surface one indirection away.
    for name in dir(store_module):
        if not name.startswith("_") and is_search_name(name):
            offenders.append(f"{STORE_MODULE}.{name}() is a module-level search surface")

    assert not offenders, (
        "SEC-15: the store exposes a free-text or similarity surface. FR-STORE-08 offers keyed "
        "lookup and declared queries only:\n  " + "\n  ".join(offenders)
    )
