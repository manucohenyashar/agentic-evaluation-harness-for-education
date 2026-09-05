"""No search surface — over the *concrete* store, its statements, and its schema.

Case `TC-STORE-15` (`FR-STORE-08`, P0, Artifact assertion), test plan §5.3. Issue #14 (TS-08);
blocked on issue **#10**.

**This is the half `SEC-15` deliberately left open, not a duplicate of it.**
`tests/artifact/test_store_query_surface.py` asserts the same requirement over the `Protocol`s
and over the source tree, and its own docstring hands the rest here by name:

    "It does **not** reach a concrete class that implements `TierHandle` and adds an
     off-protocol `search()`. Closing that needs a real instance, which needs the tiers to be
     constructible; it belongs with `TS-08`/`TS-09` (#14, #15), and is recorded here rather
     than implied by a green tick."

So this file asserts exactly the three things that need a real store and that a protocol sweep
structurally cannot see, and asserts nothing `SEC-15` already covers:

1. the **concrete** classes `Store`, `TierHandle` and `BlobStore` resolve to at run time,
2. the **declared statement registry** — no statement performs a `LIKE`, `MATCH` or FTS query,
3. the **schema** — no FTS virtual table exists in any tier file.

`CT-STORE-08` calls this "the structural form of 'no cross-student contamination channel'" and
marks it a **safety property**: "none will be added ... `CT-STORE-08` is a safety property, not
a convenience". `R15` and HLD §9.1/§9.8 are the same rule seen from above. The reason it is P0
rather than a hygiene check is that a similarity lookup over Tier R would let one student's
scored work influence another's, silently, with every functional case still green.

**Registered on #10, not #13.** `FR-STORE-08` is #13's requirement, but the discriminating
question the registry asks is *which single blocker, resolved, makes this test runnable and
non-vacuous* — and all three limbs need a constructible store, which is #10. `SEC-15` records
the same reasoning for the same requirement, and the two files must not disagree about it.

Rung note, reported as a finding: the plan puts `TC-STORE-15` at **rung 0**. Limbs 1 and 3 need
a real instance and a real file, so they are rung 2. The plan's rung is achievable only for a
surface check over the protocols, which is what `SEC-15` already does.
"""

from __future__ import annotations

import inspect
import re

import pytest

from tests.support.impl import STORE_MODULE, require
from tests.support.sql_scan import is_search_name
from tests.support.store_api import open_store, statement
from tests.support.store_vocabulary import virtual_table_definitions

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

ISSUE = "#10"

#: The SQL shapes that perform a free-text or similarity search. `FR-STORE-08` names
#: "similarity, embedding, or free-text search"; `TC-STORE-15` adds content `LIKE` explicitly,
#: which is the one an author reaches for without thinking of it as search at all.
#: `LIKE` is matched as a bare word, not as `like\s+[:?']`. The narrower form missed
#: `WHERE lower(body) LIKE lower(:q)` — a function-wrapped comparison, which is the *more*
#: likely spelling for a case-insensitive content search and precisely the shape the plan
#: describes as the one "an author reaches for without thinking of it as search".
SEARCH_SQL_PATTERNS: dict[str, str] = {
    "LIKE": r"\blike\b",
    "GLOB": r"\bglob\b",
    "MATCH": r"\bmatch\b",
    "FTS virtual table": r"\bcreate\s+virtual\s+table\b",
    "fts module": r"\busing\s+fts\d*\b",
    "vector/embedding extension": r"\busing\s+(vss|vec|vector)\d*\b",
    "REGEXP": r"\bregexp\b",
}


def _concrete_members(instance) -> list[str]:
    """Every public attribute of the object as it actually exists at run time.

    `dir()` on the instance rather than on the `Protocol`: the whole point of this case is the
    member a concrete class adds that the protocol never declared.
    """
    return [name for name in dir(instance) if not name.startswith("_")]


def test_tc_store_15_a_real_store_exposes_no_search_surface_no_search_statement_and_no_fts(
    tmp_data_dir,
):
    """`TC-STORE-15` — *"No method performs similarity, embedding, content `LIKE` or full-text
    search over any tier reachable from the scoring path; the registry contains no such
    statement and no FTS virtual table exists."*

    Oracle: **API and schema assertion**.

    Three limbs, and each closes a door the other two leave open.

    **The concrete surface.** `SEC-15` sweeps `Store` and `TierHandle` as protocols; a class
    implementing `TierHandle` and adding `find_similar()` satisfies the protocol and passes
    that sweep. Here the sweep runs over the live objects `package()`, `cohort()`, `durable()`
    and `blobs()` actually return — the tiers "reachable from the scoring path", named
    individually so a failure says which one grew the method.

    **The statement registry.** A store with a spotless method list can still hold a declared
    statement that does the searching, and `TierHandle.query(stmt: Statement)` is designed to
    take exactly that. So every statement the module declares is matched against the SQL shapes
    that search. `LIKE` is in the list because the plan names it: it is the form nobody
    classifies as search while writing it.

    **The schema.** An FTS virtual table adds full-text search to SQLite without adding a method
    or a statement anybody would recognise — the index is queried through ordinary-looking SQL.
    Neither of the first two limbs can see it, which is why the plan names the schema
    separately, and it is checked against every tier file on disk.
    """
    store_module = require(STORE_MODULE, issue=ISSUE)
    store = open_store(tmp_data_dir, issue=ISSUE)

    tiers = {
        "package('PKG-S')": store.package("PKG-S"),
        "cohort('COH-S')": store.cohort("COH-S"),
        "durable()": store.durable(),
        "blobs()": store.blobs(),
    }

    # --- limb 1: the concrete surface ---------------------------------------------------------
    offenders: list[str] = []
    for label, instance in tiers.items():
        for name in _concrete_members(instance):
            if is_search_name(name):
                offenders.append(
                    f"{label} -> {type(instance).__name__}.{name}() is a search surface"
                )

    for name in _concrete_members(store):
        if is_search_name(name):
            offenders.append(f"Store.{name}() is a search surface")

    # `CT-STORE-01` fixes the TierHandle surface at exactly three members. A concrete handle
    # that adds a fourth is where an off-protocol search arrives, so the *extra* members are
    # reported even when their names look innocent — `lookup_nearest` is not caught by any
    # name rule, and a reviewer seeing it listed here is.
    allowed = {"query", "enqueue_write", "transaction"}
    for label in ("package('PKG-S')", "cohort('COH-S')", "durable()"):
        extra = {
            name for name in _concrete_members(tiers[label])
            if callable(getattr(tiers[label], name, None)) and name not in allowed
        }
        if extra:
            offenders.append(
                f"{label} adds {sorted(extra)} beyond CT-STORE-01's query/enqueue_write/"
                "transaction — every added method is a surface this case cannot name in advance"
            )

    # --- limb 2: the declared statement registry ---------------------------------------------
    #
    # `STATEMENTS` is a fifth invented name, on the same footing as the four in
    # `tests/support/store_api.py` and reported with them: the plan requires "the registry
    # contains no such statement", and design §3.3 requires `query` to take a `Statement` rather
    # than a string — but nothing declares where the declared statements live. Resolved through
    # `require` so a missing registry reads as a written-ahead gap naming #10, not as a bare
    # assertion failure about an attribute nobody promised.
    registry = require(STORE_MODULE, "STATEMENTS", issue=ISSUE)
    declared = list(registry.values() if hasattr(registry, "values") else registry)
    assert declared, (
        "TC-STORE-15: the statement registry is empty, so the sweep below asserts nothing. A "
        "store that issues no declared statement at all cannot be the one under test — "
        "`TierHandle.query` takes a `Statement` and every read goes through one."
    )
    for entry in declared:
        text = str(getattr(entry, "sql", entry)).lower()
        for shape, pattern in SEARCH_SQL_PATTERNS.items():
            if re.search(pattern, text):
                offenders.append(
                    f"declared statement performs a {shape} search: {text[:120]!r}"
                )

    # --- limb 3: the schema ---------------------------------------------------------------
    for tier_file in sorted(tmp_data_dir.rglob("*.sqlite")):
        virtual = virtual_table_definitions(tier_file)
        for name, sql in virtual.items():
            offenders.append(
                f"{tier_file.name} declares virtual table {name!r}: {sql[:120]!r}"
            )

    assert not offenders, (
        "TC-STORE-15: the store offers a search surface. FR-STORE-08 offers keyed lookup and "
        "declared queries only, and CT-STORE-08 is a safety property — 'none will be added'. A "
        "similarity lookup over Tier R is a cross-student contamination channel (R15, HLD §9.1) "
        "that leaves every functional case green:\n  " + "\n  ".join(offenders)
    )


def test_tc_store_15_the_search_sql_patterns_catch_what_they_claim_to():
    """The positive control for limb 2's pattern list.

    Without it, "no declared statement searches" is true of a store with no search, true of an
    empty registry, and true of a pattern list with a typo in every entry — three claims a green
    result cannot tell apart. `SEC-15` learned this the expensive way and says so in its own
    docstring; the same reasoning applies to a regex list nobody has ever seen fire.

    Runs today, with no implementation, because it asserts about the patterns rather than about
    the store. It carries the module's `writtenahead` marker all the same: splitting one case
    across two markers would put half of `TC-STORE-15` in the gate and half outside it, and the
    registry's file-level accounting could not describe that.
    """
    probes = {
        "LIKE": "SELECT id FROM evidence WHERE lower(body) LIKE lower(:needle)",
        "GLOB": "SELECT id FROM evidence WHERE body GLOB '*essay*'",
        # The function-wrapped form, which the narrower `like\s+[:?']` pattern walked past.
        "MATCH": "SELECT id FROM evidence_fts WHERE evidence_fts MATCH :q",
        "FTS virtual table": "CREATE VIRTUAL TABLE evidence_fts USING fts5(body)",
        "fts module": "CREATE VIRTUAL TABLE x USING fts4(body)",
        "vector/embedding extension": "CREATE VIRTUAL TABLE emb USING vss0(vector(384))",
        "REGEXP": "SELECT id FROM evidence WHERE body REGEXP :pattern",
    }
    assert set(probes) == set(SEARCH_SQL_PATTERNS), (
        "TC-STORE-15: a shape in SEARCH_SQL_PATTERNS has no probe, so nothing proves it fires."
    )

    for shape, sql in probes.items():
        assert re.search(SEARCH_SQL_PATTERNS[shape], sql.lower()), (
            f"TC-STORE-15: the {shape!r} pattern no longer matches {sql!r}. A silent pattern "
            "and a clean store are indistinguishable from the assertion's point of view."
        )

    # The negative half: an ordinary keyed lookup must not trip any of them. A rule that flags
    # `FR-STORE-08`'s *sanctioned* form is one the first M-STORE commit switches off.
    for benign in (
        "SELECT id, status FROM work_unit WHERE id = :id",
        "INSERT INTO criterion_score (unit_id, points) VALUES (:unit_id, :points)",
        "SELECT student_ref FROM audit_record ORDER BY id",
        "UPDATE review_queue SET matched_at = :now WHERE id = :id",
    ):
        tripped = [
            shape for shape, pattern in SEARCH_SQL_PATTERNS.items()
            if re.search(pattern, benign.lower())
        ]
        assert not tripped, (
            f"TC-STORE-15: {tripped} flagged an ordinary keyed lookup: {benign!r}. False "
            "positives here red the build on the first legitimate statement, and `matched_at` "
            "is exactly the column name that makes a careless \\bmatch\\b rule unusable."
        )
