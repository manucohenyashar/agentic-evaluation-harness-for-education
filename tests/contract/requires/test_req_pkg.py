"""`TS-78` (issue #151) — `Requires` pairwise integration into **`M-PKG`**: every consumer's
assumption about the package catalog, checked against the real `PackageCatalog` over a real Tier P
file.

Test plan §6.13, grouped one suite per provider module (§4.10). Each case drives the consumer
module, and observes the catalog call it makes or the value that reaches its output.

| Case | Consumer | Assumption checked here |
|---|---|---|
| TC-REQ-06 | `M-INGEST` | the question inventory is fixed for the version, so V4 compares against a stable target |
| TC-REQ-09 | `M-SETUP` | setup relies on the catalog's own checks, and a rejected write is a no-op |
| TC-REQ-15 | `M-ORCH` | the criteria are read a bounded number of times, not once per unit |
| TC-REQ-21 | `M-EXTRACT` | the assembled request is stable across repeated reads, and a later draft does not reach it |
| TC-REQ-28 | `M-JUDGE` | the band ordering by ordinal reaches the assembled request |
| TC-REQ-34 | `M-DET` | a key correction is a new version, and old grades still resolve to their old key |
| TC-REQ-39 | `M-AGG` | `points_for_band` is called exactly once per criterion score |
| TC-REQ-47 | `M-SYNTH` | criterion text and band descriptors are fixed for the pinned version |
| TC-REQ-51 | `M-GRADE` | recomputing from the pinned policy reproduces a stored grade exactly |
| TC-REQ-56 | `M-REVIEW` | an edit's `new_points` comes from the pinned mapping, never a separate calculation |
| TC-REQ-61 | `M-STATS` | `NoValidationData` survives the catalog round trip as the same type |
| TC-REQ-65 | `M-CALIB` | R0 survives R1, and the full lock list raises from the catalog for this caller |
| TC-REQ-80 | `M-CONSOLE` | bypassing the console screen still refuses the export |

Markers: `contract` and `integration` (§4.7).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import aeh.pkg as pkg
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.contract, pytest.mark.integration]


class _Calls:
    """Counts calls to named methods of a class, delegating to the real ones."""

    def __init__(self, monkeypatch, cls, names):
        self.counts = {name: 0 for name in names}
        for name in names:
            original = getattr(cls, name)

            def spy(*args, _name=name, _original=original, **kwargs):
                self.counts[_name] += 1
                return _original(*args, **kwargs)

            monkeypatch.setattr(cls, name, spy)


# -- TC-REQ-15 ----------------------------------------------------------------------------------


def test_tc_req_15_the_orchestrator_reads_the_criteria_a_bounded_number_of_times(
    tmp_data_dir, monkeypatch
):
    """`TC-REQ-15` (`M-ORCH` → `M-PKG`, CT-PKG-01/06/15): a run of 200 submissions over 12
    criteria enumerates thousands of units, and every one is leased and completed. Across that,
    the orchestrator's catalog reads (criteria, bands, dependency graph, topological order) stay
    a small constant, well under one per hundred units. That is the cache the row names, held
    against the real catalog. The graph is acyclic, so a topological order exists."""
    criteria = tuple({"criterion_id": f"C{i:02d}", "kind": "open", "scoring_model": "holistic",
                      **({"dependencies": (f"C{i - 1:02d}",)} if i > 1 else {})}
                     for i in range(1, 13))
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, version = seed_run(
            store, submissions=tuple(f"S{i:03d}" for i in range(1, 201)), criteria=criteria)
        order = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch").topological_order(version)
        calls = _Calls(monkeypatch, PackageCatalog,
                       ("criteria", "bands", "dependency_graph", "topological_order", "questions"))
        units = orchestrator.enumerate_units(run_id).units_enumerated
        orchestrator.start(run_id)
        leased = 0
        for stage in ("deterministic", "extract", "score"):
            while True:
                batch = orchestrator.lease("w-req-15", stage, 500)
                if not batch:
                    break
                for unit in batch:
                    orchestrator.complete(unit.work_id)
                leased += len(batch)
        monkeypatch.undo()
    finally:
        store.close()
    reads = sum(calls.counts.values())
    assert list(order) == [f"C{i:02d}" for i in range(1, 13)], f"no topological order: {order}"
    assert units >= 5000 and leased >= units * 0.9, f"fixture: {units} units, {leased} leased"
    assert reads <= units / 100, (
        f"the orchestrator read the catalog {reads} times ({calls.counts}) across {leased} leased "
        f"units: the criteria are not cached for the run (CT-PKG-15)")


# -- TC-REQ-21 ----------------------------------------------------------------------------------


def test_tc_req_21_the_extraction_request_is_stable_and_pinned_to_the_run_version(tmp_data_dir):
    """`TC-REQ-21` (`M-EXTRACT` → `M-PKG`, CT-PKG-01/06): M-EXTRACT's assembled request for one
    unit is identical across repeated catalog reads within the run. It is still identical after
    a new draft version edits the criterion, because the run is pinned to its own version."""
    from aeh.extract import assemble_request
    from aeh.orch import STAGE_EXTRACT
    from tests.contract.judge import _drive

    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, version = _drive.seed_world(store)
        unit = orchestrator.lease("w-req-21", STAGE_EXTRACT, 1)[0]
        first = assemble_request(unit, store=store)
        second = assemble_request(unit, store=store)
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        draft = catalog.create_version(version)
        catalog.update_criterion_field(draft, "C1", "construct_tag", "a different construct")
        catalog.update_band_field(draft, "C1", 0, "descriptor", "a rewritten descriptor")
        third = assemble_request(unit, store=store)
        with store.cohort(ORCH_COHORT_ID).transaction() as tx:
            tx.execute("UPDATE run SET package_version_id = :v WHERE run_id = :r", v=draft, r=run_id)
        against_draft = assemble_request(unit, store=store)
    finally:
        store.close()
    assert first == second, "two reads of the same package version assembled different requests"
    assert first == third, "a later draft version changed a running unit's assembled request"
    assert first.criterion.text and first.criterion.evidence_type and against_draft != first, (
        f"M-EXTRACT's request does not carry the package's criterion: text="
        f"{first.criterion.text!r}, evidence_type={first.criterion.evidence_type!r}, and "
        f"repointing the run at an edited version changes nothing, so extraction is not "
        f"anchored to the version the run pinned (CT-PKG-01/06). [When written: "
        f"extract.assemble_request builds Criterion(text='', evidence_type='') and reads no "
        f"catalog.]")


# -- TC-REQ-28 ----------------------------------------------------------------------------------


def test_tc_req_28_the_band_ordering_reaches_the_assembled_scoring_request(tmp_data_dir):
    """`TC-REQ-28` (`M-JUDGE` → `M-PKG`, CT-PKG-01/04/15): four bands are declared with names in
    reverse alphabetical order of their ordinals. The scoring request M-JUDGE assembles from the
    real catalog lists them in ordinal order, with each band's own ordinal and descriptor, and
    not by name."""
    from aeh.judge import ScoringWorker
    from aeh.prov import RecordedFixtureProvider
    from tests.contract.judge import _drive

    bands = (("zeta", 1.0, "barely"), ("theta", 2.0, "partly"), ("beta", 3.0, "mostly"),
             ("alpha", 4.0, "fully"))
    store = open_store(tmp_data_dir)
    try:
        provider = RecordedFixtureProvider(fixture_dir=tmp_data_dir / "fixtures")
        orchestrator, run_id, version = _drive.seed_world(store, bands=bands)
        _drive.drive_extract(orchestrator, store, provider)
        unit = _drive.lease_score_units(orchestrator)[0]
        judge_ref = {r.build_id: r for r in _drive.PANEL_REFS}[unit.judge]
        request = ScoringWorker(store, provider, judge_ref).assemble(unit)
    finally:
        store.close()
    got = [(b.band, b.ordinal, b.descriptor) for b in request.criterion.bands]
    assert got == [(name, i, descriptor) for i, (name, _p, descriptor) in enumerate(bands)], got


# -- TC-REQ-39 ----------------------------------------------------------------------------------


def test_tc_req_39_aggregation_calls_the_single_mapping_exactly_once_per_score(
    tmp_data_dir, monkeypatch
):
    """`TC-REQ-39` (`M-AGG` → `M-PKG`, CT-PKG-04/05/15), the RISK-05 boundary: over a real judged
    run, each `aggregate` call reaches `aeh.pkg.points_for_band` exactly once, with the bands the
    real catalog returns. The points it produces equal the catalog's own
    `points_for_band(criterion, band)`."""
    import aeh.agg as agg
    from aeh.prov import RecordedFixtureProvider
    from tests.contract.agg import _drive
    from tests.support.agg_vocabulary import criterion as agg_criterion
    from tests.support.agg_vocabulary import signals as agg_signals

    store = open_store(tmp_data_dir)
    try:
        provider = RecordedFixtureProvider(fixture_dir=tmp_data_dir / "fixtures")
        _orch, run_id, _version = _drive.drive_scored_run(
            store, provider, submissions=("SYN-001", "SYN-002"), monkeypatch=monkeypatch)
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        bands = catalog.bands("C1")
        mapped: list[tuple] = []
        real = agg.points_for_band

        def spy(*args, **kwargs):
            mapped.append(args)
            return real(*args, **kwargs)

        monkeypatch.setattr(agg, "points_for_band", spy)
        results = []
        for submission in ("SYN-001", "SYN-002"):
            rows = _drive.stored_verdicts(store, run_id, submission, "C1")
            before = len(mapped)
            score = agg.aggregate(rows, agg_criterion(bands, scoring_model="atomic",
                                                      criterion_id="C1"), agg_signals())
            results.append((len(mapped) - before, score))
        monkeypatch.undo()
    finally:
        store.close()
    assert [n for n, _s in results] == [1, 1], f"mapping calls per score: {[n for n, _s in results]}"
    for _n, score in results:
        assert score.points == catalog_points(tmp_data_dir, score.band), (score.band, score.points)


def catalog_points(data_dir: Path, band: str) -> float:
    store = open_store(data_dir)
    try:
        return PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch").points_for_band("C1", band)
    finally:
        store.close()


# -- TC-REQ-61 ----------------------------------------------------------------------------------


def test_tc_req_61_no_validation_data_survives_the_catalog_round_trip_as_one_type(tmp_data_dir):
    """`TC-REQ-61` (`M-STATS` → `M-PKG`, CT-PKG-07/12): a validation record is stored through the
    catalog under a six-part key and read back under that key. A key differing in any one part
    reads back as `NoValidationData`: the same class M-STATS exports, never a zero or a `None`."""
    import aeh.stats as stats

    store = open_store(tmp_data_dir)
    try:
        _orch, _run, version = seed_run(store, submissions=("S001",),
                                        criteria=({"criterion_id": "C01", "kind": "open",
                                                   "scoring_model": "holistic"},))
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        key = dict(population_scope_id="pop-a", backend_profile="edge-local",
                   panel_build_ref="pbr:aaaa", scoring_model="holistic", criterion_id="C01")
        import inspect

        params = inspect.signature(catalog.store_validation).parameters
        wanted = dict(key, agreement=0.71, n=40, v=version)
        dropped = [part for part in key if part not in params]
        assert not dropped, f"store_validation does not accept key part(s) {dropped}"
        catalog.store_validation(**{name: value for name, value in wanted.items() if name in params})
        hit = catalog.validation_for(version, **key)
        other_version = catalog.create_version(version)
        misses = [catalog.validation_for(version, **dict(key, **{part: "other"}))
                  for part in ("population_scope_id", "backend_profile", "panel_build_ref",
                               "scoring_model", "criterion_id")]
        misses.append(catalog.validation_for(other_version, **key))
    finally:
        store.close()
    problems = []
    if isinstance(hit, pkg.NoValidationData):
        problems.append(f"the stored record did not read back: {hit!r}")
    not_absent = [m for m in misses if not isinstance(m, pkg.NoValidationData)]
    if not_absent:
        problems.append(f"a key differing in one part did not read back as no data: {not_absent}")
    wrong_type = [m for m in misses if not isinstance(m, stats.NoValidationData)]
    if wrong_type:
        problems.append(
            f"the catalog's absence value is not M-STATS' NoValidationData type: "
            f"{type(wrong_type[0]).__module__}.{type(wrong_type[0]).__name__} vs "
            f"aeh.stats.NoValidationData. [When written: aeh.stats defines its own "
            f"NoValidationData class instead of reusing aeh.pkg's, so an isinstance check on "
            f"one module's type does not recognise the other's (CT-PKG-12).]")
    assert not problems, "; ".join(problems)


# -- TC-REQ-65 ----------------------------------------------------------------------------------


def test_tc_req_65_r0_survives_r1_and_every_locked_field_raises_from_the_catalog(tmp_path):
    """`TC-REQ-65` (`M-CALIB` → `M-PKG`, CT-PKG-02/03/12, CT-CALIB-06): a clarification applied
    through M-CALIB writes a new version by lineage. The published R0 keeps its descriptors, and
    `lineage(R1)` ends in R0 then R1. Forcing each field of the full lock list through M-CALIB
    raises `SchemaLockViolation` from the catalog's own guard: the catalog's violation counter
    moves once per field."""
    import aeh.calib as calib

    catalog = calib.catalog_for_test(tmp_path / "packages" / "pkg-calib-test.pkg.sqlite")
    base = catalog.latest_version()
    r0_bands = catalog.bands(catalog.criteria(base)[0]["criterion_id"])
    revised = calib.apply_answers({"q1": "broaden"}, catalog=catalog, package_version=base)

    raised = {}
    for field in calib.LOCKED_FIELD_NAMES:
        before = pkg.schema_lock_violation_count()
        try:
            calib.apply_answers({"q1": "broaden"}, catalog=catalog, package_version=base,
                                forced_edit=calib.edit_touching(field))
            raised[field] = "no raise"
        except pkg.SchemaLockViolation as error:
            moved = pkg.schema_lock_violation_count() - before
            raised[field] = "catalog" if moved == 1 and error.raised_by == "catalog" else f"moved {moved}"
    inner = catalog._catalog()
    lineage = inner.lineage(revised) if revised else ()
    r0_after = catalog.bands(catalog.criteria(base)[0]["criterion_id"])
    assert revised and revised != base, "fixture: the clarification minted no new version"
    assert lineage[-2:] == (base, revised), f"R1 is not a child of R0: {lineage}"
    assert r0_after == r0_bands, "R0's bands changed when R1 was written"
    bad = {field: how for field, how in raised.items() if how != "catalog"}
    assert not bad, f"locked fields not refused by the catalog for M-CALIB: {bad}"


# -- TC-REQ-80 ----------------------------------------------------------------------------------


def test_tc_req_80_the_export_gate_holds_without_the_console_screen(tmp_data_dir):
    """`TC-REQ-80` (`M-CONSOLE` → `M-PKG`, CT-PKG-07/13): a package with a `real_verbatim`
    exemplar is exported by calling the catalog directly, bypassing the console's export-gate
    screen. The catalog refuses with `ExportBlockedError` and writes no archive. The console's
    validation lookup for an unscoped population is the catalog's own `NoValidationData`."""
    from tests.integration.pkg.test_export_import import _rich_package

    store, catalog, version, _parent, blob_hash = _rich_package(tmp_data_dir)
    try:
        draft = catalog.create_version(version)
        catalog.add_exemplar(draft, "EX-REAL", "CRIT-1", "b1", provenance="real_verbatim",
                             blob_hash=blob_hash)
        catalog.publish(draft, "teacher")
        dest = tmp_data_dir / "blocked.pkgzip"
        with pytest.raises(pkg.ExportBlockedError):
            catalog.export(draft, dest)
        lookup = catalog.validation_for(draft, "pop-none", "edge-local", "pbr:none")
    finally:
        store.close()
    assert not dest.exists(), "a refused export still wrote an archive"
    assert isinstance(lookup, pkg.NoValidationData), f"the unscoped lookup returned {lookup!r}"


# -- TC-REQ-06 ----------------------------------------------------------------------------------


def test_tc_req_06_the_v4_structural_signal_compares_against_a_fixed_version(tmp_data_dir):
    """`TC-REQ-06` (`M-INGEST` → `M-PKG`, CT-PKG-01/08): M-INGEST's V4 structural signal compares
    a submission's regions (ingest's `document_region` row shape: `element_kind` naming the
    question, `region_kind`, selection fields) against the package's question inventory. Over the
    pinned version it answers the same on repeated reads, and still the same after a later draft
    adds a question. Against that draft the answer differs, which shows it is read from the
    package and not assumed."""
    from tests.support.setup_harness import build_ingestor

    regions = [
        {"element_kind": q, "region_kind": "answer", "selection_state": None, "selection": None}
        for q in ("Q1", "Q2")
    ]
    store = open_store(tmp_data_dir)
    try:
        _orch, _run, version = seed_run(store, submissions=("S001",), criteria=(
            {"criterion_id": "C01", "question_id": "Q1", "kind": "open", "scoring_model": "holistic"},
            {"criterion_id": "C02", "question_id": "Q2", "kind": "open", "scoring_model": "holistic"}))
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        ingestor = build_ingestor(store)
        first = ingestor._v4_structural_signal(regions, version, catalog)
        second = ingestor._v4_structural_signal(regions, version, catalog)
        draft = catalog.create_version(version)
        catalog.add_criterion(draft, "C09", question_id="Q9", kind="open")
        pinned_after = ingestor._v4_structural_signal(regions, version, catalog)
        against_draft = ingestor._v4_structural_signal(regions, draft, catalog)
    finally:
        store.close()
    assert first[1]["question_count"] and first[1]["question_numbering"], (
        f"fixture: the regions do not match the pinned version's inventory: {first}")
    assert first == second == pinned_after, (first, second, pinned_after)
    assert against_draft != first, (
        "control: the V4 signal did not change against a version with another question, so it "
        "is not reading the package inventory")


# -- TC-REQ-09 ----------------------------------------------------------------------------------


def test_tc_req_09_setup_relies_on_the_catalogs_own_checks_and_a_rejected_write_is_a_no_op(
    tmp_data_dir
):
    """`TC-REQ-09` (`M-SETUP` → `M-PKG`, CT-PKG-03/04/11/12): the band structure is enforced by
    the catalog. A band whose ordinal breaks contiguity is refused with the catalog's own
    `BandSetError`, and the refused write leaves no band row. Bands read back in ordinal order
    whatever their names. M-SETUP carries no second copy of those checks: its source raises no
    `BandSetError` and has no contiguity or evenness test of its own.

    Disclosed scope: M-SETUP's own write door, `write_readback`, needs a confirmed inventory
    before it accepts any criterion. So the refusal is exercised through the catalog's band door
    (`add_band`), and the "no second copy" half is read from M-SETUP's source."""
    import inspect
    import re

    import aeh.setup as setup

    store = open_store(tmp_data_dir)
    try:
        _orch, _run, version = seed_run(store, submissions=("S001",), criteria=(
            {"criterion_id": "C01", "kind": "open", "scoring_model": "holistic", "band_count": 4},))
        handle = store.package("pkg-orch")
        catalog = PackageCatalog(handle, package_id="pkg-orch")
        count = lambda: handle.query("SELECT COUNT(*) AS n FROM band")[0]["n"]  # noqa: E731
        for ordinal, name in enumerate(("zulu", "alpha", "mike", "bravo")):
            catalog.add_band(version, "C01", ordinal, name, float(ordinal), f"level {ordinal}")
        before = count()
        with pytest.raises(pkg.BandSetError):
            catalog.add_band(version, "C01", 6, "gap", 6.0, "a gap in the ordinals")
        after_reject = count()
        read_back = [(getattr(b, "ordinal", None) if not isinstance(b, dict) else b["ordinal"])
                     for b in catalog.bands("C01")]
    finally:
        store.close()
    source = inspect.getsource(setup)
    second_copy = [token for token in ("BandSetError",) if token in source] + re.findall(
        r"ordinals?\s*!=\s*list\(range|%\s*2\s*!=\s*0|contiguous\(", source)
    assert after_reject == before, f"a refused band write left a row: {before} -> {after_reject}"
    assert read_back == [0, 1, 2, 3], f"bands did not read back in ordinal order: {read_back}"
    assert not second_copy, (
        f"M-SETUP carries its own copy of the catalog's checks: {second_copy}. [When written: "
        f"setup.py's read-back reply parser refuses an odd or out-of-range band_count "
        f"(`band_count % 2 != 0`, FR-SETUP-04) before any catalog write, a second copy of "
        f"CT-PKG-04's even band set.]")


# -- TC-REQ-34 ----------------------------------------------------------------------------------


def test_tc_req_34_old_grades_resolve_to_old_keys_after_a_key_correction(tmp_data_dir):
    """`TC-REQ-34` (`M-DET` → `M-PKG`, CT-PKG-01/04/08): a correction of M1's key is written as a
    new version, and M-DET re-derives under it. Afterwards the original version still holds its
    original key. Every audit record's `answer_key_ref` names a version whose key, read from the
    catalog pinned to that version, is exactly the key the record carries. The deterministic
    band set is the fixed two-band `correct`/`incorrect`."""
    import json

    from aeh.det import DeterministicEvaluator
    from tests.support.det_vocabulary import (
        open_det_store,
        seed_answer_region,
        seed_det_world,
        seed_head_document,
    )

    store = open_det_store(tmp_data_dir)
    try:
        submissions = ("S001", "S002", "S003")
        run_id, v1, cohort_id = seed_det_world(
            store, submissions=submissions,
            criteria=[{"criterion_id": "M1", "question_id": "Q1", "key": ("B",)}])
        for submission, selection in zip(submissions, ("B", "C", "B")):
            document_id = seed_head_document(store, cohort_id, submission)
            seed_answer_region(store, cohort_id, document_id, "Q1", selection=selection)
        evaluator = DeterministicEvaluator(store)
        evaluator.evaluate_cohort(run_id)
        catalog = PackageCatalog(store.package("pkg-det"), package_id="pkg-det")
        v2 = catalog.create_version(parent=v1)
        catalog.set_answer_key(v2, "M1", ("C",))
        evaluator.rederive_for_key_change(cohort_id, "M1", v2)
        refs = [row["answer_key_ref"] for row in store.durable().query(
            "SELECT answer_key_ref FROM audit_record WHERE criterion_id = 'M1'")]
        keys = {v: [r for r in catalog.criteria(v) if r["criterion_id"] == "M1"][0]["answer_key"]
                for v in (v1, v2)}
        bands = {row["band"] for row in store.cohort(cohort_id).query(
            "SELECT DISTINCT band FROM criterion_score WHERE criterion_id = 'M1'")}
    finally:
        store.close()
    assert refs and {r.split(":", 1)[0] for r in refs} == {v1, v2}, f"audit refs: {refs}"
    mismatched = []
    for ref in refs:
        version, recorded = ref.split(":", 1)
        stored = keys[version]
        stored = json.loads(stored) if isinstance(stored, str) else list(stored)
        if list(json.loads(recorded)) != list(stored):
            mismatched.append((ref, stored))
    assert json.loads(keys[v1]) == ["B"] if isinstance(keys[v1], str) else list(keys[v1]) == ["B"], (
        f"the original version's key changed after the correction: {keys[v1]}")
    assert not mismatched, f"audit records whose key does not match their version's key: {mismatched}"
    assert bands <= {"correct", "incorrect", "unresolved"}, f"deterministic bands: {bands}"


# -- TC-REQ-47 ----------------------------------------------------------------------------------


def test_tc_req_47_synthesis_reads_the_criteria_of_the_runs_pinned_version(
    tmp_data_dir, monkeypatch
):
    """`TC-REQ-47` (`M-SYNTH` → `M-PKG`, CT-PKG-01/04): a later draft version exists with an
    extra question when a submission is synthesized. Every catalog read M-SYNTH makes names the
    run's own `package_version_id`, and the narrative is produced over that version's
    questions. Descriptors and criterion text are read from a version nothing mutates for the
    run's life."""
    from aeh.synth import SynthesisWorker
    from tests.support.synth_vocabulary import (
        COHORT_ID,
        FIVE_QUESTION_CRITERIA,
        CaptureProvider,
        narrative_completion,
        seed_scored_submission,
        synth_ref,
    )

    questions = tuple(f"Q{q}" for q in range(1, 6))
    replies = [narrative_completion(f"Question {q[1:]}: the response states its reasoning.",
                                    (f"{q}C1", f"{q}C2")) for q in questions]
    replies.append(narrative_completion("Overall: each complete question is addressed in turn."))
    store = open_store(tmp_data_dir)
    try:
        _orch, run_id, version = seed_run(store, submissions=("SYN-001",),
                                          criteria=FIVE_QUESTION_CRITERIA)
        seed_scored_submission(store, run_id, "SYN-001", complete_questions=set(questions))
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        draft = catalog.create_version(version)
        catalog.add_criterion(draft, "Q6C1", question_id="Q6", kind="open")
        read_versions: list[str] = []
        real_criteria = PackageCatalog.criteria

        def spy(self, v, *args, **kwargs):
            read_versions.append(v)
            return real_criteria(self, v, *args, **kwargs)

        monkeypatch.setattr(PackageCatalog, "criteria", spy)
        SynthesisWorker(store, CaptureProvider(replies), synth_ref()).synthesize_submission(
            run_id, "SYN-001")
        monkeypatch.undo()
        narratives = store.cohort(COHORT_ID).query(
            "SELECT question_id FROM narrative WHERE run_id = :r", r=run_id)
    finally:
        store.close()
    assert read_versions, "control: synthesis made no catalog read"
    assert set(read_versions) == {version}, f"synthesis read versions {set(read_versions)}, not {version}"
    assert "Q6" not in {row["question_id"] for row in narratives}, "the later draft's question reached the run"
    assert narratives, "fixture: synthesis wrote no narrative"


# -- TC-REQ-51 ----------------------------------------------------------------------------------


def test_tc_req_51_recomputing_from_the_pinned_policy_reproduces_the_grade_exactly(tmp_data_dir):
    """`TC-REQ-51` (`M-GRADE` → `M-PKG`, CT-PKG-01/09/10, CT-GRADE-03): a run's grades are
    computed under the policy pinned to its package version. After a later version sets a
    different combination policy, recomputing the same run reproduces every stored grade row
    byte for byte, and mints no new revision."""
    from aeh.grade import open_grade
    from aeh.pkg import GradePolicy
    from tests.support.grade_vocabulary import grade_rows, write_criterion_scores

    submissions = tuple(f"S{i:03d}" for i in range(1, 11))
    store = open_store(tmp_data_dir)
    try:
        _orch, run_id, version = seed_run(store, submissions=submissions, criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},
            {"criterion_id": "C2", "kind": "open", "scoring_model": "atomic"}))
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        catalog.set_grade_policy(version, GradePolicy(combination="weighted_sum"))
        cohort = store.cohort(ORCH_COHORT_ID)
        write_criterion_scores(cohort, [(s, "C1", "B2", 7.0, "auto") for s in submissions]
                               + [(s, "C2", "B1", 3.0 + i, "auto") for i, s in enumerate(submissions)])
        service = open_grade(store)
        service.compute_all(run_id)
        first = grade_rows(cohort)
        later = catalog.create_version(version)
        catalog.set_grade_policy(later, GradePolicy(combination="best_k_of_n", k=1))
        service.compute_all(run_id)
        second = grade_rows(cohort)
    finally:
        store.close()
    assert len(first) == len(submissions)
    assert second == first, "recomputation from the pinned policy did not reproduce the stored grades"


# -- TC-REQ-56 ----------------------------------------------------------------------------------


def test_tc_req_56_an_edits_points_come_from_the_pinned_mapping(tmp_data_dir, monkeypatch):
    """`TC-REQ-56` (`M-REVIEW` → `M-PKG`, CT-PKG-04/05/10): the criterion's bands carry points
    no default scale would produce. A teacher edit through M-REVIEW, with the real catalog
    attached, records `new_points` equal to the catalog's `points_for_band` for the chosen
    band, reached through exactly one catalog mapping call. A band the catalog does not declare
    is refused rather than given a number."""
    from aeh.review import build_review
    from tests.support import broken_review_fixtures as broken

    store = open_store(tmp_data_dir)
    try:
        _orch, _run, version = seed_run(store, submissions=("S001",), criteria=(
            {"criterion_id": "C-01", "kind": "open", "scoring_model": "holistic", "band_count": 4},))
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        for ordinal, (name, points) in enumerate((("B1", 0.0), ("B2", 3.5), ("B3", 7.25), ("B4", 11.0))):
            catalog.add_band(version, "C-01", ordinal, name, points, f"level {ordinal}")
        service = build_review(scores=broken.flagged_population(4, criteria=1), catalog=catalog)
        queue = service.build_queue(run_id="run-1", budget_minutes=600)
        item = queue.shown[0]
        calls = _Calls(monkeypatch, PackageCatalog, ("points_for_band",))
        service.act(item, "edit", new_band="B3")
        monkeypatch.undo()
        labels = [label for label in getattr(service, "labels", lambda: ())()
                  ] if callable(getattr(service, "labels", None)) else list(service._labels)
        with pytest.raises(pkg.PackageError):
            service.act(queue.shown[1], "edit", new_band="B9")
    finally:
        store.close()
    edited = [label for label in labels if getattr(label, "label_type", None) == "edit"]
    assert edited, f"fixture: the edit wrote no label ({labels})"
    assert edited[-1].new_points == catalog_points_of(tmp_data_dir, "C-01", "B3") == 7.25
    assert calls.counts["points_for_band"] == 1, calls.counts


def catalog_points_of(data_dir: Path, criterion_id: str, band: str) -> float:
    store = open_store(data_dir)
    try:
        return PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch").points_for_band(
            criterion_id, band)
    finally:
        store.close()
