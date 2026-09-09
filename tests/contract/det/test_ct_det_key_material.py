"""`CT-DET-12` — the key never reaches a judge prompt (`TC-DET-C12`).

Case of test plan §6.11.11; issue #90 (TS-68). Green by design — `M-DET`
shipped via #246/#249.

The clause: the answer key is the sensitive artifact and is unreachable from
any judge prompt — **trivially, because a deterministic criterion generates no
judge request at all** (`CT-ORCH-07`). This is structural, not a filter.

The clause discriminator: a filter test would hand a request containing the
key to a redactor and check the output; a structural test asserts the request
never exists. This case is the structural one, asserted in the two places the
structure is observable —
- **the unit ledger's shape**: a mixed run (a keyed mcq criterion beside a
  judged one) enumerates exactly one `stage='deterministic'` unit with a null
  judge per deterministic submission, and NO extract or score unit ever names
  the mcq criterion — while the judged criterion beside it shows both stages,
  so the ledger demonstrably carries judge-bound work and its silence about
  `M1` is the claim, not an empty ledger;
- **a sentinel scan**: the key option is a distinctive id (`ZQ7`), every
  submission answers it, and the pass scores them all — the key was read, used
  and live throughout — yet every cell of every `work_unit` row, stringify
  everything, contains the sentinel nowhere. No filter chose to redact it;
  there was nothing to redact.

**Disclosed construction**: the judge-request surface itself (`M-JUDGE` prompt
assembly) has not landed, so the scan runs over the work ledger — the request
surface that exists today. The structural half is what carries the clause into
that future: any judge request a later story adds is enumerated from the unit
ledger, and the mcq criterion's unit is a terminal `deterministic` row with a
null judge — a request generator would have to grow out of a stage this case
pins to have none.
"""

from __future__ import annotations

import pytest

from aeh.conf import resolve_run_config
from aeh.det import DeterministicEvaluator
from aeh.orch import Orchestrator
from aeh.pkg import PackageCatalog
from tests.support.conf_builders import CohortRef, edge_cfg
from tests.support.det_vocabulary import (
    open_det_store,
    seed_answer_region,
    seed_cohort,
    seed_head_document,
)

pytestmark = pytest.mark.contract

from tests.contract.det._doubles import ISSUE  # noqa: F401 — register citation

#: The key option's id doubles as the sentinel: distinctive enough that no
#: orch-minted work id, judge id or status carries it by accident.
SENTINEL = "ZQ7"

_SUBMISSIONS = ("S1", "S2", "S3")


def _seed_mixed_world(store):
    """A cohort of three, one package version carrying BOTH shapes: `M1` (mcq,
    key on the sentinel option) and `J1` (open, judged) — then the run and its
    enumerated units. Returns `(orchestrator, run_id, version, cohort_id)`."""
    seed_cohort(store, _SUBMISSIONS, "c-det-keymat")
    package_handle = store.package("pkg-det")
    with package_handle.transaction() as tx:
        tx.execute(
            "INSERT INTO package (package_id, created_at) VALUES ('pkg-det', "
            "'2026-01-01T00:00:00+00:00')"
        )
    catalog = PackageCatalog(package_handle, package_id="pkg-det")
    version = catalog.create_version(None)
    catalog.add_criterion(version, "M1", question_id="Q1", kind="mcq",
                          scoring_model="atomic", band_count=2)
    catalog.add_band(version, "M1", 0, "incorrect", 0.0)
    catalog.add_band(version, "M1", 1, "correct", 1.0)
    catalog.set_mcq_options(version, "M1",
                            [(SENTINEL, "the sentinel option"),
                             ("B", "Option B"), ("C", "Option C"),
                             ("D", "Option D")])
    catalog.set_answer_key(version, "M1", (SENTINEL,))
    catalog.add_criterion(version, "J1", question_id="Q2", kind="open",
                          scoring_model="atomic", band_count=2)
    catalog.add_band(version, "J1", 0, "incorrect", 0.0)
    catalog.add_band(version, "J1", 1, "correct", 1.0)

    for s in _SUBMISSIONS:
        seed_head_document(store, "c-det-keymat", s)
        seed_answer_region(store, "c-det-keymat", f"doc-{s}", "Q1",
                           selection=SENTINEL)

    resolved = resolve_run_config(
        edge_cfg(), CohortRef(cohort_id="c-det-keymat", consent_class="synthetic")
    )
    orch = Orchestrator(store)
    run_id = orch.create_run("c-det-keymat", version, resolved)
    orch.enumerate_units(run_id)
    return orch, run_id, version, "c-det-keymat"


def _units(store, cohort_id):
    return store.cohort(cohort_id).query("SELECT * FROM work_unit")


def test_tc_det_c12_a_deterministic_criterion_generates_no_judge_request(
        tmp_data_dir):
    """`TC-DET-C12` (the structural half) — in a mixed run, the mcq
    criterion's entire unit inventory is exactly one `stage='deterministic'`
    row per submission, each with a null judge; NO extract unit and NO score
    unit names it. The judged criterion beside it shows both stages — the
    ledger demonstrably carries judge-bound work, so its silence about `M1`
    is the structure, not an artifact of an empty ledger."""
    store = open_det_store(tmp_data_dir)
    try:
        _orch, run_id, _version, cohort_id = _seed_mixed_world(store)

        units = _units(store, cohort_id)
        by_criterion: dict[str, list] = {}
        for row in units:
            by_criterion.setdefault(row["criterion_id"], []).append(row)
        assert set(by_criterion) == {"M1", "J1"}, (
            f"TC-DET-C12: the ledger carries {sorted(by_criterion)} — the "
            "mixed run did not enumerate both criteria; the case is vacuous."
        )

        m1 = by_criterion["M1"]
        assert len(m1) == len(_SUBMISSIONS), (
            f"TC-DET-C12: {len(m1)} units for the mcq criterion — exactly "
            "one per submission is the shape CT-ORCH-07 fixes."
        )
        wrong_stage = [u["work_id"] for u in m1 if u["stage"] != "deterministic"]
        assert not wrong_stage, (
            f"TC-DET-C12: mcq units at stage != 'deterministic': "
            f"{wrong_stage} — a judge request generator grew."
        )
        judged_units = [u for u in m1 if u["judge_id"] is not None]
        assert not judged_units, (
            f"TC-DET-C12: {len(judged_units)} mcq units carry a judge — the "
            "deterministic criterion reached a judge."
        )

        extract_or_score = [
            u["work_id"] for u in m1 if u["stage"] in ("extract", "score")
        ]
        assert extract_or_score == [], (
            f"TC-DET-C12: {len(extract_or_score)} extraction/scoring units "
            "name the mcq criterion — the key's criterion entered the judge "
            "pipeline."
        )
        # The contrast that keeps this from passing on an empty ledger: the
        # judged criterion beside it produced both stages.
        j1_stages = {u["stage"] for u in by_criterion["J1"]}
        assert {"extract", "score"} <= j1_stages, (
            f"TC-DET-C12: the judged criterion enumerated {sorted(j1_stages)} "
            "— the contrast half is vacuous."
        )
        assert run_id  # the enumeration belongs to the run under test
    finally:
        store.close()


def test_tc_det_c12_the_key_is_live_but_never_in_the_ledger(tmp_data_dir):
    """`TC-DET-C12` (the sentinel scan) — the key is demonstrably live: the
    criterion row carries the sentinel, every submission answered it, and the
    deterministic pass scored all three correct by looking it up. Yet every
    cell of every work_unit row — stringify the lot — contains the sentinel
    nowhere. The key moved through this run without ever entering the surface
    a judge request would be built from."""
    store = open_det_store(tmp_data_dir)
    try:
        _orch, run_id, version, cohort_id = _seed_mixed_world(store)

        # The key IS on file, in the package tier, under the sentinel id.
        key_raw = store.package("pkg-det").query(
            "SELECT answer_key FROM criterion WHERE package_version_id = :v "
            "AND criterion_id = 'M1'",
            v=version,
        )[0]["answer_key"]
        assert SENTINEL in key_raw, (
            "TC-DET-C12: the sentinel is not in the stored key — the scan "
            "would be vacuous; the key must be live for its absence to mean "
            "anything."
        )

        # And the pass used it: three lookups, three correct.
        report = DeterministicEvaluator(store).evaluate_cohort(run_id)
        assert (report.criteria, report.evaluations) == (1, 3)
        assert report.correct == 3, (
            f"TC-DET-C12: {report.correct} correct — the key lookup did not "
            "score against the sentinel key."
        )

        units = _units(store, cohort_id)
        assert units, "TC-DET-C12: the ledger is empty — nothing to scan."
        hits = [
            (row["work_id"], column)
            for row in units
            for column in row.keys()
            if SENTINEL in str(row[column])
        ]
        assert hits == [], (
            f"TC-DET-C12: the key material appears in the work ledger at "
            f"{hits} — a judge prompt built from any of these rows would "
            "carry the answer key."
        )
    finally:
        store.close()
