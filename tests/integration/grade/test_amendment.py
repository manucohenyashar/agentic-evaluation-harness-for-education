"""`TC-GRADE-13` — amending a finalized grade writes a new revision and never mutates
the delivered one.

Test plan §5.14 (block form); `FR-GRADE-12`, `NFR-GRADE-02`, ADR-9; RISK-12 (Critical);
P0; rung 2 — real store, real audit trail. Seven steps against the shipped `amend`
(src/aeh/grade.py, landed with #101):

1. amend one criterion's points with an actor and a reason (the edit lands as the
   criterion's points override — the band→points mapping is `M-AGG`'s pinned one, and
   what `amend` records and replays is the resulting override);
2. revision 2 exists with `is_current = 1`; revision 1 is retained with `is_current = 0`
   and its row is unchanged — every stored column byte-identical apart from the
   current flag, the strongest form of the case's "row hash unchanged" oracle;
3. `finalized_at` is preserved on the amendment;
4. the amendment record names who changed what, when and why;
5. the partial unique index permits exactly one `is_current = 1` row per
   (run, submission), by attempting a second;
6. re-exporting revision 1 reproduces the original export byte for byte, and the
   export names the revision it was produced from;
7. recomputing the grade from the stored criterion scores, policy version and key
   version alone reproduces the stored value — through the amendment replay, the
   recomputed content equals the stored amended content and writes nothing
   (`NFR-GRADE-02`'s round trip, `NFR-GRADE-05`'s no-write).

**Disclosed limbs, as landed by #103.** The plan's step 2 names a `superseded_at` on
the superseded revision; #103 landed the column (migration 19, `aeh/grade.py`) and
the demotion now stamps it — so the immutability oracle below names it beside
`is_current` as the demotion's declared write set: a delivered revision's CONTENT is
still byte-identical after the amendment, with the lifecycle bookkeeping the two
columns carry. The plan's step 4 names "the audit record": the shipped amendment
record is the `amendments` JSON on the grade row itself (who / what / when / why),
asserted below; #103 additionally lands the `audit_record`-row form (one Tier D row
per amendment call, `decided_by` the actor, `evaluation_mode='judged'`) — the two
records are the revision-local trail and the durable audit trail, and this suite
pins the revision-local one the recomputation replays.

**Variant — two amendments in sequence (revisions 2 and 3).** Implemented below with
the oracle the design actually pins, which is deliberately semantics-neutral on the
one question the shipped code leaves open: when the second amendment composes, does it
apply over the *stored* scores or over the *first amendment's* result? FR-GRADE-12
pins the revision structure, the retention, the preserved `finalized_at`, the
who/what/when/why record and "shall not mutate the delivered revision" — all
asserted — but pins neither composition rule. So the oracle here is the
recomputability guarantee both readings must satisfy (`NFR-GRADE-02` /
CT-GRADE-03): each revision's total equals the policy applied over the stored
criterion scores **plus that revision's own recorded amendment map** — the record and
the figure must agree, whichever composition rule produced them. The composition
question itself (the shipped `amend` recomputes each edit over the stored rows and
records only that call's edits, so a second edit silently reverts the first
displayed amendment) is a finding on #103's PR, disclosed in this suite's PR body,
not pinned red here against a documented #101 contract. **As landed by #103**: the
replace semantics stand (disclosed in the PR body; the recomputability oracle above
is what pins the record/figure agreement either way).

**Variant — an amendment that changes nothing must produce no new revision** (the
plan cites `NFR-GRADE-05`). Shipped `amend` documents "the amended grade lands as
revision n+1" and always mints — so this variant is red against the shipped contract.
It is deliberately **not** written as a marked test here: a writtenahead marker keys
on a symbol whose landing makes the test runnable, and no symbol gates a behaviour
change inside a landed method; the conflict is between the plan's variant note and
#101's documented contract, and its reconciliation is #103's (amendment revisions).
Disclosed in the PR body rather than pinned red against a landed, documented decision
(the TC-SETUP-12 deferral precedent). **#103's reconciliation**: `amend()` now
short-circuits on content — an edit whose application reproduces the current
revision's content exactly mints nothing (`_content_of`/`_stored_content`, the same
comparison the compute passes honor), settling the current revision `final` in place
when the state model pressures it and recording the call in the audit trail either
way. Verified against the real store at the landing (the four-limb script in the PR
body: no mint, retention with the `superseded_at` stamp, one audit row per call, the
trigger refusing the in-place edit); the variant case itself remains the test plan's
to write.

**Disclosed stand-ins** (`grade_vocabulary.py`, header): the run-completion UPDATE —
`M-ORCH` is the run row's single writer, so the test writes the `status = 'complete'`
state the automatic finalization path reads (`test_finalization.py`'s pattern), which
is how revision 1 gets its recorded `finalized_at`; and `write_criterion_scores`
standing in for `M-AGG`'s single-writer rows.

**Isolation:** rung 2 — real store, real package lineage, real grade ledger.
"""

from __future__ import annotations

import json
import re

import pytest

from aeh.grade import apply_policy, policy_version_of
from aeh.pkg import GradePolicy, PackageCatalog
from aeh.store import open_store
from tests.support.grade_vocabulary import (
    GRADE_BLOCKER,
    grade_rows,
    score,
    write_criterion_scores,
)
from tests.support.impl import GRADE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.integration]

ISSUE = GRADE_BLOCKER

_PACKAGE = "pkg-orch"
_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"},
)


def _complete_run(cohort, run_id):
    """The disclosed stand-in for #61's control-row write (`test_finalization.py`'s
    pattern): the run state the automatic finalization path reads."""
    with cohort.transaction() as tx:
        tx.execute("UPDATE run SET status = 'complete' WHERE run_id = :r", r=run_id)


def _seed_finalized_run(store, submissions):
    """A run whose every submission holds a finalized revision 1 with a recorded
    `finalized_at` — the case's precondition — under a windowless policy (the run
    completes, so finalization rides the automatic path)."""
    require(GRADE_MODULE, "open_grade", issue=ISSUE)
    _orchestrator, run_id, version = seed_run(
        store, submissions=submissions, criteria=_CRITERIA
    )
    catalog = PackageCatalog(store.package(_PACKAGE), package_id=_PACKAGE)
    policy = GradePolicy(combination="weighted_sum")
    catalog.set_grade_policy(version, policy)
    cohort = store.cohort(ORCH_COHORT_ID)
    write_criterion_scores(
        cohort,
        [
            (sid, "C1", "B2", 7.0, "auto")
            for sid in submissions
        ]
        + [
            (sid, "C2", "B1", 6.0, "auto")
            for sid in submissions
        ],
    )
    svc = require(GRADE_MODULE, "open_grade", issue=ISSUE)(store)
    svc.compute_all(run_id)
    _complete_run(cohort, run_id)
    svc.compute_all(run_id)  # the settlement pass: revision 1 reads final in place
    return run_id, cohort, svc, policy


def _rows_for(grades, submission_id):
    return [g for g in grades if g["submission_id"] == submission_id]


def _current(grades, submission_id):
    current = [g for g in _rows_for(grades, submission_id) if g["is_current"]]
    assert len(current) == 1, (
        f"submission {submission_id!r} has {len(current)} current rows — exactly one "
        "is_current row per (run, submission) is ADR-9's key invariant"
    )
    return current[0]


def _revisions(grades, submission_id):
    return sorted(g["revision"] for g in _rows_for(grades, submission_id))


def _same_except(row, other, *changed):
    """The immutability oracle: two stored rows are byte-identical apart from the
    named fields. `is_current` and `superseded_at` are the two fields a demotion
    writes (the flag clears, the supersession stamp lands — migration 19); a
    revision's own issuance fields (`total`, `computed_at`, `amendments`) differ
    between revisions by construction, so the chain's immutability assertion names
    them there."""
    return (
        {key: value for key, value in row.items() if key not in changed}
        == {key: value for key, value in other.items() if key not in changed}
    )


def _recompute_total(rows, amendments_raw, policy):
    """The round-trip recomputation of one revision's total from stored data alone
    (`NFR-GRADE-02`): the stored criterion scores with **that revision's recorded
    amendment map** replayed, under the policy the provenance column names. This is
    the same recipe the shipped compute passes run — the amendment replay over the
    ledger — read here from the test side, so the oracle is the recipe the design
    pins, not the writer's own code path."""
    overrides = {
        entry["criterion_id"]: float(entry["points"])
        for entry in json.loads(amendments_raw or "[]")
    }
    replayed = [
        score(row["criterion_id"], float(overrides.get(row["criterion_id"],
                                                      row["points"])),
              band=row["band"], routing=row["routing"])
        for row in rows
    ]
    return apply_policy(replayed, policy).total


# --- TC-GRADE-13: the seven-step block form --------------------------------------------------


def test_tc_grade_13_amendment_writes_a_new_revision_and_never_mutates_the_delivered_one(
    tmp_data_dir, monkeypatch
):
    """`TC-GRADE-13` — the seven steps: a new revision, the delivered one retained and
    byte-unchanged, `finalized_at` preserved, who/what/when/why recorded, the partial
    unique index enforced, the superseded revision still exporting byte for byte, and
    the amended grade recomputing exactly from stored data."""
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort, svc, policy = _seed_finalized_run(store, ("S-A1", "S-A2"))
        monkeypatch.setenv("HARNESS_GRADE_EXPORT_DIR", str(tmp_data_dir / "exports"))

        before = grade_rows(cohort)
        delivered = _current(before, "S-A1")
        assert delivered["state"] == "final" and delivered["finalized_at"], (
            "fixture drift: revision 1 is not a finalized grade with a recorded "
            "finalized_at — the case's precondition"
        )
        original_export = svc.export(run_id, 1, "csv")
        assert re.fullmatch(r"grade-.+-rev1\.csv", original_export.name), (
            f"the export is named {original_export.name!r} — it must name the revision "
            "it was produced from (grade-{run}-rev{revision}.csv, TC-GRADE-13 step 6)"
        )

        # --- step 1: amend one criterion's points, with an actor and a reason --------
        revision = svc.amend(
            run_id, "S-A1", {"C1": 4.0},
            actor="t-may",
            reason="band re-read against the rubric",
        )

        after = grade_rows(cohort)
        # --- step 2: revision 2 current; revision 1 retained and byte-unchanged ------
        assert _revisions(after, "S-A1") == [1, 2], (
            f"the amended submission's revisions are {_revisions(after, 'S-A1')} — the "
            "amendment must write revision 2 and retain revision 1 (TC-GRADE-13 step 2, "
            "FR-GRADE-12, ADR-9)"
        )
        second = _current(after, "S-A1")
        assert second["revision"] == 2
        retained = [g for g in _rows_for(after, "S-A1") if g["revision"] == 1][0]
        assert not retained["is_current"], (
            "revision 1 still reads current after the amendment — the superseded "
            "revision is retained with is_current = 0 (TC-GRADE-13 step 2; the "
            "supersession stamp `superseded_at` lands beside it, migration 19)"
        )
        assert _same_except(retained, delivered, "is_current", "superseded_at"), (
            "revision 1's stored row changed when the amendment landed — the delivered "
            "revision must be byte-unchanged (TC-GRADE-13 step 2, FR-GRADE-12's 'shall "
            "not mutate the delivered revision')"
        )
        assert second["total"] == pytest.approx(10.0, abs=1e-9), (
            f"revision 2's total is {second['total']!r}, expected 10.0 — the edit "
            "moves C1 from 7.0 to 4.0 and C2 stays 6.0 (exact value, TC-GRADE-13)"
        )

        # --- step 3: finalized_at preserved on the amendment --------------------------
        assert second["finalized_at"] == delivered["finalized_at"], (
            f"the amendment's finalized_at is {second['finalized_at']!r}, revision 1's "
            f"was {delivered['finalized_at']!r} — amending preserves the original "
            "finalization timestamp (TC-GRADE-13 step 3, FR-GRADE-12)"
        )

        # --- step 4: the record names who changed what, when and why ------------------
        # The revision-local record is the `amendments` JSON on the grade row (the
        # durable audit_record row is #103's landed second trail — see the module
        # docstring).
        entries = json.loads(second["amendments"])
        assert len(entries) == 1, (
            f"revision 2 carries {len(entries)} amendment entries — one edit was made "
            "and exactly one must be recorded (TC-GRADE-13 step 4)"
        )
        entry = entries[0]
        assert entry["criterion_id"] == "C1" and entry["points"] == 4.0, (
            f"the amendment record names {entry!r} — it must record WHAT changed: the "
            "criterion and the points it was moved to (TC-GRADE-13 step 4)"
        )
        assert entry["actor"] == "t-may", (
            "the amendment record names no actor — WHO changed it must be recorded "
            "(TC-GRADE-13 step 4, FR-GRADE-12)"
        )
        assert entry["reason"] == "band re-read against the rubric", (
            "the amendment record names no reason — WHY it changed must be recorded "
            "(TC-GRADE-13 step 4, FR-GRADE-12)"
        )
        assert entry["at"] == second["computed_at"], (
            "the amendment record's timestamp does not match the revision's issuance — "
            "WHEN it changed must be recorded (TC-GRADE-13 step 4)"
        )

        # --- step 5: the partial unique index admits exactly one current row ----------
        # The TC-AGG-04 pattern: verify the constraint exists in the shipped DDL, then
        # attempt the refused write and assert the exact exception class.
        index_rows = cohort.query(
            "SELECT sql FROM sqlite_master WHERE type = 'index' "
            "AND name = 'uq_submission_grade_current'"
        )
        assert index_rows, (
            "uq_submission_grade_current does not exist — the partial unique index "
            "behind ADR-9's one-current-row invariant is not in the schema "
            "(migration 18, TC-GRADE-13 step 5)"
        )
        assert "WHERE is_current = 1" in index_rows[0]["sql"], (
            f"the shipped index is {index_rows[0]['sql']!r} — it must be the PARTIAL "
            "unique index on is_current = 1, not a whole-table constraint"
        )
        with pytest.raises(Exception) as refused:
            with cohort.transaction() as tx:
                tx.execute(
                    "INSERT INTO submission_grade (run_id, submission_id, revision, "
                    "is_current, state) VALUES (:r, :s, 9, 1, 'final')",
                    r=run_id, s="S-A1",
                )
        assert type(refused.value).__name__ == "IntegrityError", (
            f"a second is_current row for one (run, submission) raised "
            f"{type(refused.value).__name__!r} — the partial unique index must refuse "
            "it with an IntegrityError (TC-GRADE-13 step 5)"
        )

        # --- step 6: the superseded revision still exports, byte for byte -------------
        replayed_export = svc.export(run_id, 1, "csv")
        assert replayed_export.read_bytes() == original_export.read_bytes(), (
            "re-exporting revision 1 after the amendment produced different bytes — "
            "the superseded revision must remain exportable exactly as delivered "
            "(TC-GRADE-13 step 6's golden oracle)"
        )
        header = original_export.read_text(encoding="utf-8").splitlines()[0]
        assert header.split(",")[2] == "revision", (
            f"the export header is {header!r} — the CSV must carry the revision column "
            "so the export names the revision it was produced from (TC-GRADE-13 step 6)"
        )

        # --- step 7: exact recomputation from stored data alone -----------------------
        # A recomputation pass replays the recorded amendment map over the stored
        # scores; the content matches, so no new revision is minted (NFR-GRADE-02's
        # round trip through NFR-GRADE-05's no-write).
        svc.compute_all(run_id)
        final_rows = grade_rows(cohort)
        assert _revisions(final_rows, "S-A1") == [1, 2], (
            f"a recomputation pass left {_revisions(final_rows, 'S-A1')} — the amended "
            "grade must recompute to its stored value and write nothing (TC-GRADE-13 "
            "step 7, NFR-GRADE-02, NFR-GRADE-05)"
        )
        stored = _current(final_rows, "S-A1")
        scores = cohort.query(
            "SELECT criterion_id, band, points, routing FROM criterion_score "
            "WHERE submission_id = 'S-A1' ORDER BY criterion_id"
        )
        assert _recompute_total([dict(row) for row in scores],
                                stored["amendments"], policy) == pytest.approx(
            stored["total"], abs=1e-9,
        ), (
            "the amended grade does not recompute exactly from the stored criterion "
            "scores, the recorded amendment map and the stored policy version — "
            "NFR-GRADE-02's non-repudiation guarantee (TC-GRADE-13 step 7)"
        )
        one = svc.compute_one(run_id, "S-A1")
        assert one.total == pytest.approx(stored["total"], abs=1e-9), (
            f"compute_one returns {one.total!r} against the stored "
            f"{stored['total']!r} — the single-submission entry point must land on the "
            "same recomputation (TC-GRADE-13 step 7)"
        )
        assert one.revision == 2, (
            "compute_one minted a new revision — the replay path is idempotent "
            "(NFR-GRADE-05)"
        )

        # The untouched submission's ledger is untouched: no revision, no drift.
        assert _revisions(final_rows, "S-A2") == [1], (
            "the unamended submission gained a revision — an amendment is scoped to "
            "its own submission"
        )
        assert _current(final_rows, "S-A2")["policy_version"] == (
            policy_version_of(policy)
        ), (
            "the stored policy_version is not the content hash of the effective "
            "policy — provenance must name the policy that produced the grade "
            "(FR-GRADE-02)"
        )
    finally:
        store.close()


# --- variant: two amendments in sequence -----------------------------------------------------


def test_tc_grade_13_two_amendments_in_sequence_keep_the_ledger_consistent(
    tmp_data_dir,
):
    """`TC-GRADE-13`'s two-amendment variant — revisions 2 and 3 exist in sequence,
    both prior revisions are retained and byte-unchanged, each revision records its own
    who/what/when/why, and every revision's total recomputes exactly from the stored
    scores plus that revision's own recorded amendment map (`NFR-GRADE-02`).

    The oracle is deliberately semantics-neutral on the composition rule: the
    shipped `amend` applies each edit over the stored rows and records only that
    call's edits, so revision 3 here recomputes under the second edit alone. Whether
    #103 keeps replace semantics or makes an amendment compose over its predecessor's
    overrides, this test holds — the invariant it pins is that the recorded map and
    the recorded total agree for every revision in the chain. See the module
    docstring for the disclosed finding."""
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort, svc, policy = _seed_finalized_run(store, ("S-B1",))
        before = grade_rows(cohort)
        delivered = _current(before, "S-B1")

        svc.amend(run_id, "S-B1", {"C1": 4.0}, actor="t-may", reason="first re-read")
        revision = svc.amend(run_id, "S-B1", {"C2": 5.0}, actor="t-kay",
                             reason="second re-read")
        assert revision.revision == 3, (
            f"the second amendment minted revision {revision.revision}, expected 3 — "
            "two amendments in sequence produce revisions 2 and 3 (TC-GRADE-13's "
            "variant)"
        )

        rows = grade_rows(cohort)
        assert _revisions(rows, "S-B1") == [1, 2, 3], (
            f"the submission's revisions are {_revisions(rows, 'S-B1')} — the full "
            "chain is retained (ADR-9)"
        )
        first = [g for g in rows if g["revision"] == 1][0]
        second = [g for g in rows if g["revision"] == 2][0]
        third = _current(rows, "S-B1")
        for stale in (first, second):
            assert not stale["is_current"], (
                "a superseded revision still reads current — exactly one is_current "
                "row per submission (ADR-9's partial unique index)"
            )
        assert _same_except(first, delivered, "is_current", "superseded_at"), (
            "revision 1 was mutated by the second amendment — no revision in the "
            "chain is ever rewritten (FR-GRADE-12)"
        )
        assert _same_except(
            second, delivered,
            "is_current", "superseded_at", "revision", "total", "computed_at",
            "amendments",
        ), (
            "revision 2's stored row changed when revision 3 landed beyond the fields "
            "its own issuance writes — a superseded revision is never rewritten "
            "(FR-GRADE-12)"
        )
        assert second["total"] == pytest.approx(10.0, abs=1e-9), (
            f"revision 2's total is {second['total']!r}, expected 10.0 — the first "
            "edit's content must survive the second amendment (TC-GRADE-13's variant)"
        )
        assert third["finalized_at"] == delivered["finalized_at"], (
            "finalized_at did not survive two amendments (TC-GRADE-13 step 3 across "
            "the chain, FR-GRADE-12)"
        )

        third_record = json.loads(third["amendments"])
        assert third_record[0]["criterion_id"] == "C2", (
            f"revision 3's amendment record names {third_record!r} — each revision "
            "records the edit that produced it (TC-GRADE-13 step 4)"
        )
        assert third_record[0]["actor"] == "t-kay" and third_record[0]["reason"] == (
            "second re-read"
        ), (
            "revision 3's record does not name who changed what and why "
            "(TC-GRADE-13 step 4)"
        )
        second_record = json.loads(second["amendments"])
        assert second_record[0]["actor"] == "t-may", (
            "revision 2's record was overwritten by the second amendment — each "
            "revision's trail must survive the next (FR-GRADE-12's audit trail)"
        )

        # The recomputability guarantee, per revision: each stored total equals the
        # policy over the stored scores plus THAT revision's recorded map.
        scores = [
            dict(row)
            for row in cohort.query(
                "SELECT criterion_id, band, points, routing FROM criterion_score "
                "WHERE submission_id = 'S-B1' ORDER BY criterion_id"
            )
        ]
        for row in (second, third):
            assert _recompute_total(scores, row["amendments"], policy) == (
                pytest.approx(row["total"], abs=1e-9)
            ), (
                f"revision {row['revision']} stores total {row['total']!r} but its "
                "recorded amendment map recomputes to a different figure — the record "
                "and the figure must agree for every revision (NFR-GRADE-02, "
                "CT-GRADE-03; TC-GRADE-13's variant oracle)"
            )

        # And the chain is idempotent under the shipped replay: a recomputation
        # reproduces every revision's content and mints nothing (NFR-GRADE-05).
        svc.compute_all(run_id)
        final_rows = grade_rows(cohort)
        assert _revisions(final_rows, "S-B1") == [1, 2, 3], (
            f"a recomputation pass after two amendments left "
            f"{_revisions(final_rows, 'S-B1')} — the replay must reproduce the current "
            "amended content and write nothing (NFR-GRADE-05)"
        )
    finally:
        store.close()


# --- the refusal side: an edit that applies nowhere is never recorded ------------------------


def test_tc_grade_13_an_edit_naming_no_stored_score_is_refused(tmp_data_dir):
    """The amendment refusal `amend` ships with the case's family: an edit naming a
    criterion with no stored score row is refused — a missing input is filled by the
    operator routing (a rescan), never edited into place (CT-GRADE-15), and recording
    an edit that applied nowhere would claim a change that never happened."""
    store = open_store(tmp_data_dir)
    try:
        run_id, cohort, svc, _policy = _seed_finalized_run(store, ("S-C1",))
        with pytest.raises(Exception) as refused:
            svc.amend(run_id, "S-C1", {"C9": 5.0}, actor="t-may", reason="n/a")
        assert type(refused.value).__name__ == "GradeError", (
            f"an edit naming a criterion with no stored row raised "
            f"{type(refused.value).__name__!r}, expected GradeError — the refusal must "
            "be the module's own stated error, not a crash"
        )
        assert _revisions(grade_rows(cohort), "S-C1") == [1], (
            "a refused amendment left a new revision behind — a refusal writes nothing"
        )
    finally:
        store.close()
