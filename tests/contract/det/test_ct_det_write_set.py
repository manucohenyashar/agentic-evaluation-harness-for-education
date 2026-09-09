"""`CT-DET-09` — the write set (`TC-DET-C09`), the state clause.

Case of test plan §6.11.11; issue #90 (TS-68). Green by design — `M-DET`
shipped via #246/#249.

The clause: writes `criterion_score` rows for deterministic criteria,
`mcq_item_stats`/`mcq_item_summary`, and an `audit_record` with
`evaluation_mode = 'deterministic'`, **null** `panel_config`, **null**
`prompt_template_v`, **non-null** `answer_key_ref` and `selection_read`.
Writes **no** verdict, no narrative, no package row (`FR-DET-10`, RISK-38's
negative half: what the module does NOT write is the case).

The clause discriminator: the FR-level case asserts the audit record's shape
on one pass; this case asserts the write set as OWNERSHIP —
- **under a write audit**: a before/after row-count delta over EVERY table in
  EVERY tier the pass can touch, so a write to any unowned table — verdict,
  narrative, package, label, review_queue, work_unit, whatever a refactor
  adds tomorrow — fails the case by name;
- **statically**: the module's entire declared statement registry, parsed for
  writes, touches exactly the four owned tables — the absence holds for paths
  the behavioral audit never exercised;
- **per field**: every audit_record null and non-null asserted explicitly —
  a populated `panel_config` on a deterministic row would make it look
  panel-scored to every statistic downstream.
"""

from __future__ import annotations

import re

import pytest

from aeh.det import DET_STATEMENTS, DeterministicEvaluator
from tests.support.det_vocabulary import (
    open_det_store,
    seed_det_world,
    seed_selection_answers,
)

pytestmark = pytest.mark.contract

from tests.contract.det._doubles import ISSUE  # noqa: F401 — register citation

#: The tables the clause lets M-DET write, per tier.
OWNED_COHORT = {"criterion_score"}
OWNED_DURABLE = {"mcq_item_stats", "mcq_item_summary", "audit_record"}


def _table_counts(handle) -> dict[str, int]:
    names = handle.query(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT "
        "LIKE 'sqlite_%'"
    )
    return {
        row["name"]: handle.query(
            f"SELECT COUNT(*) AS n FROM {row['name']}"
        )[0]["n"]
        for row in names
    }


def test_tc_det_c09_write_audit_over_every_tier(tmp_data_dir):
    """`TC-DET-C09` (the audit) — a mixed cohort pass (scored, blank,
    unresolved): the row-count delta over every cohort-tier table and every
    durable-tier table stays inside the owned set. No verdict row, no
    narrative, no package row, no label, no review_queue entry, no work_unit
    — the negative half asserted by delta, not by convention."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version, cohort_id = seed_det_world(
            store,
            submissions=("S-hit", "S-miss", "S-blank", "S-ambig",
                         "S-absent"),
            criteria=[
                {"criterion_id": "M1", "question_id": "Q1", "key": ("B",)},
                {"criterion_id": "M2", "question_id": "Q2", "key": ("B",)},
            ],
        )
        seed_selection_answers(
            store, cohort_id,
            [
                {"submission_id": "S-hit", "selection": "B"},
                {"submission_id": "S-miss", "selection": "C"},
                {"submission_id": "S-blank", "content_state": "blank"},
                {"submission_id": "S-ambig", "content_state": "present",
                 "selection_state": "ambiguous"},
                {"submission_id": "S-absent", "omit_document": True},
            ],
        )
        cohort = store.cohort(cohort_id)
        durable = store.durable()
        before_cohort = _table_counts(cohort)
        before_durable = _table_counts(durable)
        before_package = _table_counts(store.package("pkg-det"))

        report = DeterministicEvaluator(store).evaluate_cohort(run_id)
        assert report.criteria == 2 and report.evaluations == 10
        assert report.audit_records_written > 0, (
            "TC-DET-C09: the audit saw no audit_record writes — it would "
            "pass vacuously."
        )

        after_cohort = _table_counts(cohort)
        after_durable = _table_counts(durable)
        after_package = _table_counts(store.package("pkg-det"))

        changed_cohort = {t for t, n in after_cohort.items()
                          if n != before_cohort.get(t, 0)}
        changed_durable = {t for t, n in after_durable.items()
                           if n != before_durable.get(t, 0)}
        changed_package = {t for t, n in after_package.items()
                           if n != before_package.get(t, 0)}

        assert changed_cohort <= OWNED_COHORT, (
            f"TC-DET-C09: the pass wrote {sorted(changed_cohort - OWNED_COHORT)} "
            "outside the cohort write set."
        )
        assert {"criterion_score"} <= changed_cohort, (
            "TC-DET-C09: the audit saw no score writes — vacuous."
        )
        assert changed_durable <= OWNED_DURABLE, (
            f"TC-DET-C09: the pass wrote "
            f"{sorted(changed_durable - OWNED_DURABLE)} outside the durable "
            "write set."
        )
        assert {"mcq_item_stats", "mcq_item_summary",
                "audit_record"} <= changed_durable, (
            f"TC-DET-C09: the audit saw no stats/audit writes: "
            f"{sorted(changed_durable)}."
        )
        assert changed_package == set(), (
            f"TC-DET-C09: the pass wrote package-tier tables "
            f"{sorted(changed_package)} — no package row is the clause's "
            "explicit prohibition."
        )
        # The named prohibitions, spelled out even though the delta covers
        # them — the clause names verdict, narrative and package rows.
        for table in ("verdict", "narrative"):
            assert after_cohort.get(table, 0) == 0
        for table in ("package", "package_version", "criterion", "band",
                      "label", "review_queue", "work_unit"):
            before = (before_package if table in before_package
                      else before_cohort if table in before_cohort
                      else before_durable)
            after = (after_package if table in after_package
                     else after_cohort if table in after_cohort
                     else after_durable)
            assert after[table] == before[table], (
                f"TC-DET-C09: {table} changed during the pass."
            )
    finally:
        store.close()


def test_tc_det_c09_the_declared_registry_writes_only_owned_tables():
    """`TC-DET-C09` (the static half) — every statement in the module's
    declared registry that WRITES (INSERT/UPDATE/DELETE, including upserts)
    names exactly the four owned tables. A new write cannot enter the module
    without either passing through the registry (and failing here) or
    assembling SQL (which SEC-15's own guard refuses)."""
    write_pattern = re.compile(
        r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE
    )
    table_pattern = re.compile(
        r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|REPLACE\s+INTO)\s+"
        r"([A-Za-z_][A-Za-z0-9_]*)",
        re.IGNORECASE,
    )
    surface: dict[str, str] = {}
    for name, stmt in DET_STATEMENTS.items():
        sql = str(stmt).strip()
        if write_pattern.match(sql):
            match = table_pattern.search(sql)
            assert match, f"TC-DET-C09: cannot parse write target of {name}."
            surface[name] = match.group(1)
    assert surface, "TC-DET-C09: the registry parsed no writes — vacuous."
    owned = OWNED_COHORT | OWNED_DURABLE
    offenders = {name: table for name, table in surface.items()
                 if table not in owned}
    assert not offenders, (
        f"TC-DET-C09: the registry writes outside the owned set: {offenders}."
    )
    # And every owned table is actually written by something — the surface is
    # the whole write set, not a subset that happens to be clean.
    assert set(surface.values()) == owned, (
        f"TC-DET-C09: owned tables never written: {owned - set(surface.values())}."
    )


def test_tc_det_c09_audit_record_field_contract(tmp_data_dir):
    """`TC-DET-C09` (per field) — every deterministic audit record carries
    `evaluation_mode = 'deterministic'`, NULL `panel_config`, NULL
    `prompt_template_v`, non-null `answer_key_ref` and `selection_read` —
    each null and non-null asserted EXPLICITLY, plus `decided_by = 'system'`
    and non-null `final_points` (unresolved rows write no audit record at
    all: no grade, no points, nothing for a NOT NULL column to carry)."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, version, cohort_id = seed_det_world(
            store,
            submissions=("S-hit", "S-blank", "S-ambig"),
            criteria=[{"criterion_id": "M1", "question_id": "Q1",
                       "key": ("B",)}],
        )
        seed_selection_answers(
            store, cohort_id,
            [
                {"submission_id": "S-hit", "selection": "B"},
                {"submission_id": "S-blank", "content_state": "blank"},
                {"submission_id": "S-ambig", "content_state": "present",
                 "selection_state": "ambiguous"},
            ],
        )
        report = DeterministicEvaluator(store).evaluate_cohort(run_id)
        # Two scored rows (hit + blank); the unresolved one writes none.
        assert report.audit_records_written == 2

        rows = [dict(r) for r in store.durable().query(
            "SELECT * FROM audit_record WHERE criterion_id = 'M1'"
        )]
        assert len(rows) == 2
        for row in rows:
            assert row["evaluation_mode"] == "deterministic", (
                f"TC-DET-C09: evaluation_mode {row['evaluation_mode']!r} — "
                "the row does not name its own mode."
            )
            assert row["panel_config"] is None, (
                f"TC-DET-C09: panel_config {row['panel_config']!r} — a "
                "populated one makes the row look panel-scored to every "
                "statistic downstream."
            )
            assert row["prompt_template_v"] is None, (
                f"TC-DET-C09: prompt_template_v "
                f"{row['prompt_template_v']!r} — no prompt exists for a "
                "lookup."
            )
            assert row["answer_key_ref"], (
                "TC-DET-C09: answer_key_ref is null — the grade is not "
                "answerable to the key that produced it."
            )
            assert row["selection_read"] is not None, (
                "TC-DET-C09: selection_read is null — what was read must "
                "travel with the grade (a blank reads as [])."
            )
            assert row["decided_by"] == "system"
            assert row["final_points"] is not None
            assert row["package_version_id"] == version
        # The blank's selection_read is [] — an empty answer was READ.
        blank_rows = [r for r in rows if r["submission_id"] == "S-blank"]
        assert blank_rows and blank_rows[0]["selection_read"] == "[]"
        # And the unresolved submission has NO audit record at all.
        unresolved = [r for r in rows if r["submission_id"] == "S-ambig"]
        assert unresolved == []
    finally:
        store.close()
