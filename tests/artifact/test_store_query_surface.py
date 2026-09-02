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
    SEARCH_METHOD_NAMES,
    execute_call_sites,
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
    "function, form",
    [
        ("by_name", "f-string"),
        ("by_cohort", "concatenation"),
        ("by_status", "percent formatting"),
        ("ordered_by", ".format()"),
        ("migrate", "executescript"),
        ("split_across_lines", "a chain assembled across three statements"),
    ],
)
def test_sec_15_the_walker_catches_every_form_of_assembly(function, form):
    """The positive control, one row per form the scanner claims to catch.

    Parametrized rather than asserted in a lump, so a regression names the form that stopped
    being caught. `split_across_lines` is the row that matters most: it carries no single string
    a keyword check can read, and it is the reason the walker asserts on the argument reaching
    `execute()` rather than only on text that looks like SQL.
    """
    import ast

    source = BROKEN_SQL_FIXTURE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(BROKEN_SQL_FIXTURE))
    target = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function
    )

    flagged = {
        v.line for v in scan_module("broken_sql_fixture", BROKEN_SQL_FIXTURE, REPO_ROOT)
    }

    assert any(target.lineno <= line <= (target.end_lineno or target.lineno) for line in flagged), (
        f"SEC-15: the walker did not flag {function}() ({form}). The control exists because "
        "the real tree issues no SQL, so a silent scanner and a clean tree look identical."
    )


def test_sec_15_the_walker_reports_nothing_against_a_declared_statement():
    """The negative control — the walker must not flag the *correct* form.

    A scanner that flags everything passes every positive control above and is worthless: the
    first `M-STORE` commit turns it off. So a parameterized declared statement, the exact shape
    `FR-STORE-08` asks for, must come back clean.
    """
    clean = REPO_ROOT / "tests" / "support" / "_sec15_declared_statement_probe.py"
    clean.write_text(
        "import sqlite3\n\n"
        "SELECT_BY_ID = 'SELECT id, status FROM work_unit WHERE id = ?'\n\n"
        "def fetch(connection: sqlite3.Connection, unit_id: str):\n"
        "    return connection.execute(SELECT_BY_ID, (unit_id,))\n",
        encoding="utf-8",
    )
    try:
        violations = scan_module("declared_probe", clean, REPO_ROOT)
    finally:
        clean.unlink()

    assert not violations, (
        "SEC-15: the walker flagged a correctly declared, parameterized statement. A scanner "
        "with false positives on the sanctioned form is one somebody switches off:\n  "
        + "\n  ".join(str(v) for v in violations)
    )


#: Every place in `src/` or `harness/` that hands a statement to SQLite, as `module:line`.
#: Empty today: `M-STORE` (#10) has not landed and nothing else issues SQL.
#:
#: Transcribed rather than computed, for the reason `SEC-14` transcribes the dependency set — the
#: value of the constant is that changing it is a diff somebody reads.
KNOWN_EXECUTE_SITES: frozenset[str] = frozenset()


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


@pytest.mark.writtenahead
def test_sec_15_no_tier_exposes_a_free_text_or_similarity_query():
    """`SEC-15`'s stated probe — *"attempt free-text and similarity queries against every tier
    reachable from the scoring path"*.

    An **absence assertion over the real interface**, which is the only form that answers the
    threat. `FR-STORE-08`: *"no method that performs similarity, embedding, or free-text search
    over any tier reachable from the scoring path; the store interface offers keyed lookup and
    declared queries only."*

    Every tier, not one: `package()`, `cohort()` and `durable()` are all reachable from the
    scoring path (design §3.3's data model — Tier P holds criteria and bands, C+R the submissions
    and verdicts, D the labels), and a search method added to one of them is an injection surface
    however clean the other two are.

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
            if name.lower() in SEARCH_METHOD_NAMES:
                offenders.append(f"{owner.__name__}.{name}() is a search surface")

    # `query` takes a declared `Statement`, never a raw string.
    query = getattr(TierHandle, "query", None)
    assert query is not None, "TierHandle exposes no query() at all — design §3.3 declares one"
    annotation = str(inspect.signature(query).parameters.get("stmt", "").annotation)
    if "str" in annotation and "Statement" not in annotation:
        offenders.append(
            f"TierHandle.query takes {annotation} — a raw-SQL passthrough is A03 whatever the "
            "method is called"
        )

    # And nothing at module level either: a free function taking a tier and a search string is
    # the same surface one indirection away.
    for name in dir(store_module):
        if not name.startswith("_") and name.lower() in SEARCH_METHOD_NAMES:
            offenders.append(f"{STORE_MODULE}.{name}() is a module-level search surface")

    assert not offenders, (
        "SEC-15: the store exposes a free-text or similarity surface. FR-STORE-08 offers keyed "
        "lookup and declared queries only:\n  " + "\n  ".join(offenders)
    )
