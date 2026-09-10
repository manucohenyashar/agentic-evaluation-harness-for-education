"""`TC-JUDGE-C12` — one verdict row per work unit and nothing else, statically
prohibited everywhere else (§6.11.10).

`CT-JUDGE-12` (state): *"Assert the module writes **one `verdict` row per work unit
and nothing else**, under a rung-3 write audit. Then the prohibition: **no write
path** to `criterion_score`, `evidence`, `narrative`, or any package row — asserted
statically. Pairs with `CT-AGG-11`, which states the reciprocal; between them the
scoring and narrative paths cannot merge, which is what keeps a second competing
grade from existing (RISK-19)."* (plan §6.11.10, verbatim)

Two cases carry it:

1. **the rung-3 write audit** — the audit installed over a real driven run after
   the disclosed seeding, the judged drive running every score unit through the
   real workers, and the write log read back grouped by module: every
   `aeh.judge`-attributed write is either the sanctioned `insert_verdict` INSERT on
   `verdict` or the shared `mark_done` UPDATE on `work_unit` — BYTE-FOR-BYTE, no
   statement the module invented — one verdict INSERT per judged unit, one
   `mark_done` per unit, and no third table anywhere in the module's log. The
   positive control is the drive itself: the judge's writes must appear for the
   negative half to mean anything. And the at-least-once guard that makes "one
   verdict row per work unit" true under a re-run: RE-persisting one already-done
   unit with a different result executes exactly ONE new write (the guarded
   `mark_done`, changing nothing), NO verdict write, and the row the first writer
   left stands — the second completion never becomes a second verdict;
2. **the static prohibition (artifact assertion)** — `aeh/judge.py`'s text carries
   NO write path to `criterion_score`, `evidence` or `narrative` (the clause's
   named three), NO write path to any package-tier row (the package tables derived
   from the package module's own write statements, so a future package table is
   covered the day it exists), and — the completeness arm — EVERY write statement
   the module text declares names `verdict`: the module's whole write surface is
   its own verdict INSERT plus the shared `mark_done` it executes from M-ORCH's
   registry (referenced for `mark_done` and the `changes()` guard read and NOTHING
   else write-shaped). The scanner is validated against positive controls first:
   a synthetic write to each forbidden table must be flagged, and a read must not
   be.

Cross-references, not duplicates: `TC-AGG-C11` (`tests/contract/agg/
test_ct_agg_c11_write_sets.py`, #92) states the RECIPROCAL — `aeh.agg` writes
`criterion_score` and nothing else, and the two write sets must stay disjoint or a
second competing grade exists (RISK-19); this file is the `M-JUDGE` half.
`TC-ORCH-C17` (`tests/contract/orch/test_ct_orch_c17_sole_writership.py`) holds the
RUN-ledger boundary under a full dispatch — `work_unit`'s writers are the
orchestrator plus the two stage workers' shared `mark_done`, byte-for-byte; this
file asserts the judge's own write set over its OWN tier surface (`verdict` and the
done-marking it executes), which the dispatch-wide case cannot isolate. The
statement-literal structural guard over all of `src/aeh` is
`tests/artifact/test_agg_synth_write_sets.py` (`TC-AGG-16`) — literal-scoped, where
this limb's normalized scan catches a write assembled outside a string literal.

Isolation: rung 3 — real store, real workers, the completions from the recorded
fixture provider; the socket guard is autouse.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Any

import pytest

from aeh.orch import ORCH_STATEMENTS
from aeh.store import open_store
from tests.contract.judge._drive import (
    PANEL_REFS,
    drive_extract,
    lease_score_units,
    seed_world,
    spans,
)
from tests.contract.orch._doubles import install_audit
from tests.support.extract_vocabulary import sampling_params, verdict_completion
from tests.support.impl import JUDGE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = [pytest.mark.contract]

#: The story that owns the verdict write (`M-JUDGE` is complete — #78/#79/#80/#81).
ISSUE = "#78"

_SUBMISSIONS = ("SYN-001", "SYN-002")

_JUDGE_BUILD = "build-judge-contract"

#: The module text's write-statement form, as the audit and the static limb share
#: it: whitespace-normalized, so a statement wrapped across lines cannot evade.
_WRITE_FORMS = (
    "INSERT INTO {table}",
    "INSERT OR REPLACE INTO {table}",
    "UPDATE {table} SET",
    "DELETE FROM {table}",
    "REPLACE INTO {table}",
)

_WRITE_TABLE_RE = re.compile(
    r"(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM|REPLACE\s+INTO)"
    r"\s+[\"'`]?([a-z_][a-z0-9_]*)"
)


def _normalized(sql: str) -> str:
    return " ".join(sql.split())


def _write_paths(module_text: str, table: str) -> list[str]:
    """The write statements against `table` in one module's text, found over the
    whitespace-normalized text so a statement wrapped across lines cannot evade the
    scan. Reads (`SELECT`) never match: the clause forbids write paths, and an
    over-broad scan would go red against a compliant module."""
    normalized = " ".join(module_text.split())
    upper = normalized.upper()
    return [
        statement for statement in
        (form.format(table=table) for form in _WRITE_FORMS)
        if statement.upper() in upper
    ]


def test_tc_judge_c12_one_verdict_row_per_work_unit_and_nothing_else(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C12` (`CT-JUDGE-12`, the rung-3 write audit + the at-least-once
    guard, rung 3, write-audit log, P0) — under the audit, every judge-attributed
    write is the sanctioned verdict INSERT or the shared mark_done, byte-for-byte,
    one per unit and no third table; re-persisting a done unit adds exactly one
    guarded UPDATE and no second verdict, and the first writer's row stands."""
    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _version = seed_world(
            store, submissions=_SUBMISSIONS
        )
        # Extraction runs BEFORE the audit installs — the seeding and the extract
        # stage are the fixture's disclosed writes; the log below holds the judged
        # drive only, which is M-JUDGE's write surface.
        drive_extract(orchestrator, store, provider)
        cohort_audit, durable_audit = install_audit(store, ORCH_COHORT_ID)

        units = lease_score_units(orchestrator)
        assert len(units) == len(_SUBMISSIONS), (
            f"fixture bug: the drive leased {len(units)} unit(s) — the audit is "
            "over the whole judged drive, one request per submission"
        )
        refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
        results = []
        for unit in units:
            judge_ref = refs_by_build[unit.judge]
            worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
                store, provider, judge_ref
            )
            request = worker.assemble(unit)
            provider.record(
                require(JUDGE_MODULE, "prompt_fields", issue=ISSUE)(request),
                judge_ref,
                sampling_params(),
                verdict_completion("secure", 0.9, build_id=_JUDGE_BUILD,
                                   cited_spans=spans()),
            )
            result = worker.dispatch(request, judge_ref)
            worker.persist(unit, result)
            results.append((unit, result))
        assert all(result.band == "secure" for _unit, result in results), (
            "precondition: the judged drive did not land the recorded verdicts"
        )

        writes = cohort_audit.writes + durable_audit.writes
        judge_writes = [w for w in writes if w.module == "aeh.judge"]
        assert judge_writes, (
            "the audit recorded no judge-attributed write — the positive control "
            "failed, so the negative assertions below would be vacuous"
        )

        # The sanctioned pair, byte-for-byte: the module's own verdict INSERT and
        # the shared mark_done UPDATE — no other statement shape from any judge
        # frame.
        verdict_sql = " ".join(
            require(JUDGE_MODULE, "JUDGE_STATEMENTS", issue=ISSUE)
            ["insert_verdict"].sql.split()
        )
        mark_done_sql = " ".join(ORCH_STATEMENTS["mark_done"].sql.split())
        verdict_writes = [w for w in judge_writes if w.table == "verdict"]
        unit_writes = [w for w in judge_writes if w.table == "work_unit"]
        assert len(verdict_writes) == len(units) == len(_SUBMISSIONS), (
            f"the judged drive recorded {len(verdict_writes)} verdict write(s) "
            f"for {len(units)} unit(s) — ONE verdict row per work unit "
            "(CT-JUDGE-12, FR-JUDGE-11)"
        )
        for w in verdict_writes:
            assert w.sql == verdict_sql, (
                f"a judge frame wrote verdict with {w.sql[:80]!r} — the module's "
                "ONLY verdict statement is the sanctioned insert_verdict "
                "(CT-JUDGE-12)"
            )
        for w in unit_writes:
            assert w.sql == mark_done_sql, (
                f"a judge frame wrote work_unit with {w.sql[:80]!r} — the done "
                "transition is the SHARED mark_done the stage executes inside its "
                "own persist transaction; any other unit write is a second writer "
                "on the ledger (CT-JUDGE-12, TC-ORCH-C17's boundary)"
            )
        tables_judge_wrote = {w.table for w in judge_writes}
        assert tables_judge_wrote == {"verdict", "work_unit"}, (
            f"the judged drive wrote {sorted(tables_judge_wrote)} — the module "
            "writes ONE verdict row per work unit and NOTHING else: a write to "
            "any third table merges the scoring path with another module's "
            "(CT-JUDGE-12, RISK-19)"
        )

        # The rows: one per work unit, on the units the drive judged.
        handle = store.cohort(ORCH_COHORT_ID)
        rows = handle.query(
            "SELECT v.verdict_id, v.band FROM verdict v JOIN work_unit w "
            "ON w.work_id = v.work_id WHERE w.run_id = :r ORDER BY v.verdict_id",
            r=run_id,
        )
        assert [row["verdict_id"] for row in rows] == \
            sorted(unit.work_id for unit, _result in results), (
                f"the ledger holds {[row['verdict_id'] for row in rows]} for the "
                f"drive's {len(results)} unit(s) — one verdict row per work unit, "
                "keyed on the work id (CT-JUDGE-12)"
            )

        # The at-least-once guard: re-persist the FIRST unit with a DIFFERENT
        # result — exactly one new write (the guarded mark_done, changing nothing),
        # no verdict write, and the first writer's row stands.
        unit, first_result = results[0]
        before = len(judge_writes)
        # A different completion for the same work id: the band the second
        # dispatch would have landed.
        replumbed = dataclasses.replace(first_result, band="emerging",
                                        band_ordinal=0)
        worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, provider, refs_by_build[unit.judge]
        )
        worker.persist(unit, replumbed)
        judge_writes = [w for w in cohort_audit.writes + durable_audit.writes
                        if w.module == "aeh.judge"]
        fresh = judge_writes[before:]
        assert len(fresh) == 1 and fresh[0].table == "work_unit", (
            f"the re-persist wrote {fresh} — a re-run's persist on a DONE unit "
            "executes exactly the guarded mark_done and NOTHING else "
            "(CT-JUDGE-12, FR-JUDGE-11)"
        )
        assert fresh[0].sql == mark_done_sql, (
            "the re-persist's write is not the shared mark_done — a second "
            "verdict path would be a double write under a re-run (CT-JUDGE-12)"
        )
        rows = handle.query(
            "SELECT v.band FROM verdict v JOIN work_unit w "
            "ON w.work_id = v.work_id WHERE w.work_id = :w",
            w=unit.work_id,
        )
        assert len(rows) == 1 and rows[0]["band"] == "secure", (
            f"the re-persisted result left {rows} — another completion having "
            "landed first is the at-least-once contract working: ITS row stands "
            "(CT-JUDGE-12, FR-JUDGE-11)"
        )
    finally:
        store.close()


def test_tc_judge_c12_no_write_path_to_the_forbidden_tables_statically():
    """`TC-JUDGE-C12` (`CT-JUDGE-12`, the static prohibition, artifact assertion,
    P0) — `aeh/judge.py`'s text carries no write path to `criterion_score`,
    `evidence` or `narrative`, none to any package-tier row, and every write
    statement it declares names `verdict`: the module's whole write surface is its
    own INSERT plus the shared `mark_done`."""
    import aeh.judge
    import aeh.pkg

    judge_text = Path(aeh.judge.__file__).read_text(encoding="utf-8")

    # Positive controls: the scanner flags the defect and leaves reads alone.
    for forbidden in ("criterion_score", "evidence", "narrative", "band"):
        assert _write_paths(
            f"INSERT INTO {forbidden} (row_id) VALUES ('x')", forbidden
        ), (
            f"fixture bug: the scanner no longer detects a write to "
            f"{forbidden!r} — the prohibition below would be vacuous"
        )
    assert _write_paths("SELECT band FROM x", "band") == [], (
        "fixture bug: the scanner flags reads — the clause forbids write paths, "
        "and an over-broad scan would go red against a compliant module"
    )

    # The clause's named three: no write path from the judge module to any.
    for table in ("criterion_score", "evidence", "narrative"):
        found = _write_paths(judge_text, table)
        assert found == [], (
            f"aeh.judge declares write path(s) to {table}: {found} — the clause's "
            "named prohibition: the scoring path cannot merge with the "
            "deterministic grade, the extraction evidence or the narrative "
            "(CT-JUDGE-12); with CT-AGG-11's reciprocal arm, the merge is what "
            "would put a second competing grade in the world (RISK-19)"
        )

    # Any package row: the package tables derived from the package module's own
    # write statements, so a future package table is covered the day it exists.
    pkg_tables = sorted({
        table
        for statement in aeh.pkg.PKG_STATEMENTS.values()
        for table in _WRITE_TABLE_RE.findall(" ".join(statement.sql.split()))
    })
    assert pkg_tables, (
        "fixture bug: the package module declares no write statements — the "
        "package-row prohibition below is derived from them and derived nothing"
    )
    offenders = [table for table in pkg_tables if _write_paths(judge_text, table)]
    assert offenders == [], (
        f"aeh.judge declares write path(s) to package-tier table(s) {offenders} "
        f"of {pkg_tables} — a judge that writes a package row mutates the rubric "
        "itself, and the grades it then lands are graded by a contract it edited "
        "(CT-JUDGE-12)"
    )

    # The completeness arm: every write statement the module text DECLARES names
    # `verdict` — the verdict INSERT is the module's own statement, and the
    # work_unit boundary is the shared `mark_done` from M-ORCH's registry,
    # referenced for nothing else write-shaped.
    declared_tables = set(_WRITE_TABLE_RE.findall(" ".join(judge_text.split())))
    assert declared_tables == {"verdict"}, (
        f"aeh.judge's text declares write statements against {sorted(declared_tables)} "
        "— the module's whole write surface is its own verdict INSERT plus the "
        "shared mark_done (asserted byte-for-byte at rung 3 in this file's audit "
        "limb); any other declared write is a second writer (CT-JUDGE-12)"
    )
    referenced = set(re.findall(
        r"ORCH_STATEMENTS\[[\"']([a-z_]+)[\"']\]", judge_text
    ))
    assert referenced == {"mark_done", "select_changes"}, (
        f"aeh.judge reaches M-ORCH's statement registry for {sorted(referenced)} — "
        "the sanctioned boundary is exactly the shared mark_done (the done-marking "
        "the persist executes) and the changes() guard read; any other registry "
        "statement (a lease, a status, a metrics write) is a second writer on the "
        "ledger (CT-JUDGE-12, TC-ORCH-C17's boundary)"
    )