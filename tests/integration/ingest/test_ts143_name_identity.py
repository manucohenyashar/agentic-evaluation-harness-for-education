"""TS-143 (issue #619): students are identified by name — TC-INGEST-56, TC-INGEST-57, TC-INGEST-58
and the SEC-19 re-run (operator-requirements test plan §5.4, §5.0; design delta §3.5, ADR-38).

| Case | What it pins |
|---|---|
| TC-INGEST-56 | Each F-NAMES normalization arm (case, whitespace, diacritics dropped and added, decomposed, surname-first, `ß`/`ss`, combined) resolves to its intended `student_ref`; the unnormalized comparison matches none (corpus check); the arm's paper matches nothing once its row is removed (leave-one-out: the match is that row, not a loose one); the name lands in no Tier D or Tier P file |
| TC-INGEST-57 | The collision pair: (a) both candidates, triage, no auto-accept — and no deterministic or score unit for the paper in a run's enumeration; (b) the paper's `Student ID:` line resolves to row 2, and another student's ID does not; (c) no row → triage, zero candidates; (d) a prefix → triage |
| TC-INGEST-58 | (a) a names-only roster through `aeh cohort create`: refs generated, opaque, distinct, stable across reopen; (b) an IDs-only roster, and a row with an empty name, refused naming the requirement, nothing written; (c) a Cohort 32 store migrated to 33: column present, old rows NULL and still resolving by ref, pin 33, CLAUDE.md names the migration; (d) one name in two cohorts → two refs |
| SEC-19 (re-run) | Over every arm and cell: the assembled transcription request and the V4 semantic-escalation request (which carries the transcript, `Student:` head included) carry no name, the triage candidate list is `student_ref`s only, and no log record carries a name |

**Written ahead of implementation: yes** — every case is keyed to #620 (`WRITTEN_AHEAD_BLOCKERS`,
"#620 TS-143 ..."). Before #620 the roster has no `full_name` column and each case fails at the
world's precondition with `NotImplementedYet` naming #620.

**Readings and interface choices, disclosed in the PR.**

* The roster file for `aeh cohort create` names its name column `full_name` (the schema column
  ADR-38 adds); `student_ref` stays the optional ID column.
* An ID written on the paper is a `Student ID: <id>` line under the `Student:` line.
* The triage payload is the V3 finding's `candidates: [...]` list (TC-INGEST-27's format). The
  extracted name may appear in that finding (TC-INGEST-56 allows "Tier C rows and the triage
  payload"); SEC-19's "student_ref only" is read as: every *candidate* is a roster ref.
* 57 (a)'s "no `criterion_score` row" is driven through `Orchestrator.enumerate_units` over a
  package with a deterministic (`mcq`) criterion: today's enumeration admits every submission to
  the `deterministic` stage (FR-ORCH-22's exception), which is a path to a score row for a paper
  whose student is unknown. #620 has to close it for identity-triaged papers.
* 58 (b)'s console half is TC-CONSOLE-55's (TS-148): it is the differential against this CLI
  path, and the console has no cohort-creation surface until that story.
* 58 (a)'s "stable" is asserted across re-reads and a store reopen, not across data folders.
* 58 (b) pins IDs-only as a CSV with only a `student_ref` header. What the headerless
  one-entry-per-line shape (today's `ps9-roster.txt`) becomes is left to #620: read as names it
  would turn IDs into "names", read as IDs it must be refused — either way the CSV cell is the
  unambiguous one.
* 58 (c) has a nameless pre-migration row resolve from a ref written on the `Student:` line —
  the old papers' channel, kept for rows with no name.
* The V4 escalation arm of SEC-19 is red against today's code for a reason beyond the missing
  column: the escalation sends the transcript verbatim, so #620 must replace the `Student:`
  head with the ref (or drop it) before that request is assembled.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import unicodedata
from pathlib import Path

import pytest

import aeh.agg  # noqa: F401 — the full cohort chain (CLAUDE.md: all eleven contributors)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.store import COMPLETE_SCHEMA_VERSIONS, TIER_MIGRATIONS, Tier, _SCHEMA_VERSION_TABLE, open_store
from tests.support import f_names as fx
from tests.support.impl import NotImplementedYet

pytestmark = pytest.mark.integration

ISSUE = fx.ISSUE
REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_NAME = "ingest_roster_names"
MIGRATION_VERSION = 33


def _world(tmp_data_dir: Path, tag: str, rows=fx.ROWS) -> fx.NamesWorld:
    return fx.NamesWorld(tmp_data_dir / f"w-{tag}", rows=rows)


def _assert_triaged(world, report, cell: str) -> None:
    row = world.submission(report.submission_id)
    assert report.gates.get("v3") != "pass", (
        f"{cell}: V3 passed a paper it must route to triage (FR-INGEST-39, never guessed)")
    assert row["quarantined"] == 1, f"{cell}: the paper was not held for triage"
    assert row["student_ref"] == "unknown", (
        f"{cell}: a student_ref ({row['student_ref']!r}) was assigned to an unresolved identity "
        f"— a grade would land on that child's record (RISK-110)")


def _assert_no_name_in_tier_d_or_p(root: Path, cell: str) -> None:
    files = fx.non_cohort_files(root)
    assert any(p.name.startswith("durable.sqlite") for p in files), (
        "fixture: the Tier D file is missing, so the sweep would be vacuous")
    for path in files:
        hits = fx.scan_bytes_for_names(path)
        assert not hits, (
            f"{cell}: a student name reached {path.relative_to(root)} ({hits}) — names live in "
            f"Tier C only (FR-STORE-12, CT-INGEST-23)")


# --- TC-INGEST-56 ------------------------------------------------------------------------------


def test_tc_ingest_56_the_corpus_is_hand_computed_and_normalization_is_load_bearing():
    """The F-NAMES self-check (no system call): every hand key is what the fold gives, the
    collision pair shares one key and no other pair does, and **no arm's written name equals any
    stored name byte for byte** — the unnormalized comparison matches none of them."""
    for row in fx.ROWS:
        assert fx.hand_fold(row.full_name) == row.hand_key, row
    keys = [row.hand_key for row in fx.ROWS]
    assert [r.student_ref for r in fx.ROWS if keys.count(r.hand_key) > 1] == list(
        fx.COLLISION_REFS)
    stored = {row.full_name for row in fx.ROWS}
    for arm in fx.ARMS:
        assert arm.written.strip() not in stored, f"{arm.arm_id}: matches unnormalized"
        assert fx.hand_fold(arm.written) == fx.BY_REF[arm.intended_ref].hand_key, arm.arm_id


@pytest.mark.writtenahead
@pytest.mark.parametrize("arm", fx.ARMS, ids=[a.arm_id for a in fx.ARMS])
def test_tc_ingest_56_each_normalization_arm_resolves_to_its_student(tmp_data_dir, arm):
    """Every arm resolves to the intended `student_ref`, and the name reaches no Tier D/P file."""
    world = _world(tmp_data_dir, arm.arm_id)
    try:
        report = world.ingest(arm.arm_id, arm.written)
        row = world.submission(report.submission_id)
        assert report.gates.get("v3") == "pass", (
            f"{arm.arm_id}: {arm.written!r} did not match {arm.intended_ref} under "
            f"normalization (FR-INGEST-39); V3 said {report.gates.get('v3')!r}: "
            f"{fx.v3_findings(report)}")
        assert row["student_ref"] == arm.intended_ref, (
            f"{arm.arm_id}: resolved to {row['student_ref']!r}, expected {arm.intended_ref}")
        assert row["quarantined"] == 0
    finally:
        world.close()
    _assert_no_name_in_tier_d_or_p(world.root, f"TC-INGEST-56 {arm.arm_id}")


@pytest.mark.writtenahead
@pytest.mark.parametrize("arm", fx.ARMS, ids=[a.arm_id for a in fx.ARMS])
def test_tc_ingest_56_an_arm_without_its_row_matches_nobody(tmp_data_dir, arm):
    """Leave-one-out: the same paper against the roster minus its intended row is triaged — the
    arm matched *that* row, not whatever looked similar."""
    rows = tuple(r for r in fx.ROWS if r.student_ref != arm.intended_ref)
    world = _world(tmp_data_dir, f"loo-{arm.arm_id}", rows=rows)
    try:
        report = world.ingest(arm.arm_id, arm.written)
        _assert_triaged(world, report, f"TC-INGEST-56 leave-one-out {arm.arm_id}")
    finally:
        world.close()


# --- TC-INGEST-57 ------------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_ingest_57_a_a_name_matching_both_collision_rows_goes_to_triage_with_both(
        tmp_data_dir):
    world = _world(tmp_data_dir, "57a")
    try:
        report = world.ingest("57a", fx.COLLISION_WRITTEN)
        _assert_triaged(world, report, "TC-INGEST-57 (a)")
        assert report.gates.get("v3") == "ambiguous", (
            f"(a): two rows normalize equally — V3 is 'ambiguous', got "
            f"{report.gates.get('v3')!r}")
        assert sorted(fx.triage_candidates(report) or []) == list(fx.COLLISION_REFS), (
            f"(a): the triage item must offer exactly both collision rows, got "
            f"{fx.v3_findings(report)!r}")
    finally:
        world.close()


@pytest.mark.writtenahead
def test_tc_ingest_57_a_a_triaged_paper_gets_no_scoring_work_and_no_score(tmp_data_dir):
    """Until triage resolves, no `criterion_score` row exists for the paper. Driven through the
    run's enumeration over a package with a deterministic criterion, because the deterministic
    stage admits every submission today — the one path from a held paper to a score row.

    **Narrower than the plan's oracle, disclosed.** The plan states the oracle on
    `criterion_score`; this asserts the unit level (no `deterministic` or `score` unit for the
    held paper), so a #620 that enumerates the unit and refuses it at the deterministic stage
    would meet the plan and still fail here. The unit level is chosen because no score exists
    at enumeration time to assert on, and because a filter on `quarantined` would break
    TC-ORCH-25 (an `unreadable` paper's re-ingest adds exactly two units): the exclusion has to
    be identity-specific, which is what an enumeration-level check pins."""
    from aeh.conf import CohortRef, resolve_run_config
    from aeh.orch import STAGE_DETERMINISTIC, STAGE_SCORE, Orchestrator
    from tests.support.conf_builders import edge_cfg, edge_panel
    from tests.support.orch_run import seed_package

    world = _world(tmp_data_dir, "57a-run")
    try:
        held = world.ingest("57a-held", fx.COLLISION_WRITTEN)
        clean = world.ingest("57a-clean", "AMARA OKAFOR")
        assert world.submission(clean.submission_id)["student_ref"] == "S-0401", (
            "precondition: the control paper resolves (TC-INGEST-56's case arm)")
        _assert_triaged(world, held, "TC-INGEST-57 (a) run")
        version = seed_package(world.store, (
            {"criterion_id": "C1", "kind": "mcq"},
            {"criterion_id": "C2", "kind": "open", "scoring_model": "holistic"},
        ))
        orchestrator = Orchestrator(world.store)
        resolved = resolve_run_config(edge_cfg(panel=edge_panel(3)),
                                      CohortRef(cohort_id=fx.COHORT, consent_class="synthetic"))
        run_id = orchestrator.create_run(fx.COHORT, version, resolved)
        orchestrator.enumerate_units(run_id)
        units = world.handle.query(
            "SELECT stage, submission_id, criterion_id FROM work_unit WHERE run_id = :r",
            r=run_id)
        held_units = [(u["stage"], u["criterion_id"]) for u in units
                      if u["submission_id"] == held.submission_id]
        assert any(u["submission_id"] == clean.submission_id for u in units), (
            "precondition: the enumeration wrote no units for the resolved paper")
        assert not [u for u in held_units if u[0] in (STAGE_DETERMINISTIC, STAGE_SCORE)], (
            f"(a): the identity-triaged paper got scoring work {held_units} — it would be "
            f"scored under no student (or the wrong one) before triage resolves")
    finally:
        world.close()


@pytest.mark.writtenahead
def test_tc_ingest_57_b_the_declared_id_resolves_the_collision_to_row_2(tmp_data_dir):
    world = _world(tmp_data_dir, "57b")
    try:
        report = world.ingest("57b", fx.COLLISION_WRITTEN, student_id="S-0410")
        row = world.submission(report.submission_id)
        assert report.gates.get("v3") == "pass", (
            f"(b): the secondary ID must resolve an ambiguous name (FR-INGEST-39), V3 said "
            f"{report.gates.get('v3')!r}: {fx.v3_findings(report)}")
        assert row["student_ref"] == "S-0410", f"(b): resolved to {row['student_ref']!r}"
    finally:
        world.close()


@pytest.mark.writtenahead
def test_tc_ingest_57_b_an_id_outside_the_candidates_does_not_resolve_the_collision(
        tmp_data_dir):
    """(b)'s negative twin: the ID only *disambiguates among the name's candidates*. An
    ambiguous name with another student's ID (row 1's) is still triaged — "any roster ID wins"
    would put the paper on Amara's record."""
    world = _world(tmp_data_dir, "57b-foreign")
    try:
        report = world.ingest("57b-foreign", fx.COLLISION_WRITTEN, student_id="S-0401")
        _assert_triaged(world, report, "TC-INGEST-57 (b) foreign ID")
    finally:
        world.close()


@pytest.mark.writtenahead
def test_tc_ingest_57_c_a_name_matching_no_row_goes_to_triage_with_no_candidates(tmp_data_dir):
    world = _world(tmp_data_dir, "57c")
    try:
        report = world.ingest("57c", fx.UNMATCHED_WRITTEN)
        _assert_triaged(world, report, "TC-INGEST-57 (c)")
        assert report.gates.get("v3") == "unmatched"
        assert fx.triage_candidates(report) == [], (
            f"(c): an unmatched name offers zero candidates, got {fx.v3_findings(report)!r}")
    finally:
        world.close()


@pytest.mark.writtenahead
def test_tc_ingest_57_d_a_prefix_of_a_name_is_not_a_match(tmp_data_dir):
    world = _world(tmp_data_dir, "57d")
    try:
        report = world.ingest("57d", fx.PREFIX_WRITTEN)
        _assert_triaged(world, report, "TC-INGEST-57 (d) 'Zelda' vs 'Zelda Quartermaine'")
    finally:
        world.close()


# --- TC-INGEST-58 ------------------------------------------------------------------------------


def _names_csv(tmp_path: Path, name: str, rows) -> Path:
    path = tmp_path / name
    path.write_text("full_name\n" + "".join(f"{n}\n" for n in rows), encoding="utf-8")
    return path


def _roster_rows(data_dir: Path, cohort_id: str) -> list[tuple[str, str | None]]:
    store = open_store(data_dir)
    try:
        handle = store.cohort(cohort_id)
        fx.require_names_column(handle)
        return sorted((r["student_ref"], r["full_name"]) for r in handle.query(
            "SELECT student_ref, full_name FROM roster WHERE cohort_id = :c", c=cohort_id))
    finally:
        store.close()


def _create(data_dir: Path, cohort_id: str, roster: Path) -> int:
    from aeh.pipeline import cli

    return cli.main(["cohort", "create", "--data-dir", str(data_dir), "--cohort", cohort_id,
                     "--consent", "synthetic", "--roster", str(roster)])


def _name_tokens(name: str) -> set[str]:
    return {t for t in fx.hand_fold(name).split() if len(t) >= 3}


def _require_migration_registered() -> None:
    names = {m.name for m in TIER_MIGRATIONS[Tier.COHORT]}
    if MIGRATION_NAME not in names:
        raise NotImplementedYet(
            f"no Cohort migration named {MIGRATION_NAME!r} is registered (blocked on {ISSUE})")


@pytest.mark.writtenahead
def test_tc_ingest_58_a_a_names_only_roster_creates_the_cohort_with_generated_refs(
        tmp_data_dir, tmp_path, capsys):
    _require_migration_registered()
    names = [row.full_name for row in fx.ROWS]
    assert _create(tmp_data_dir, "class-names", _names_csv(tmp_path, "names.csv", names)) == 0, (
        f"(a): a names-only roster was refused: {capsys.readouterr().err}")
    assert json.loads(capsys.readouterr().out)["roster_size"] == len(names)
    rows = _roster_rows(tmp_data_dir, "class-names")
    assert sorted(n for _, n in rows) == sorted(names), (
        f"(a): every row carries its full_name as written, got {rows}")
    refs = [ref for ref, _ in rows]
    assert all(isinstance(ref, str) and ref.strip() for ref in refs), f"(a): empty ref in {rows}"
    assert len(set(refs)) == len(refs), (
        f"(a): generated refs are not cohort-unique — the collision pair shares one? {rows}")
    for ref, name in rows:
        leaked = {t for t in _name_tokens(name) if t in fx.hand_fold(ref)}
        assert not leaked, (
            f"(a): the generated ref {ref!r} carries the name ({leaked}); refs are what model "
            f"requests carry (NFR-PROV-04), so a ref must be opaque")
    assert _roster_rows(tmp_data_dir, "class-names") == rows, (
        "(a): the refs changed across a store reopen — they must be stable")


@pytest.mark.writtenahead
@pytest.mark.parametrize("cell, text, words", [
    ("ids-only-csv", "student_ref\nS-1\nS-2\n", r"\bnames?\b"),
    ("empty-name", "full_name,student_ref\nAmara Okafor,S-1\n,S-2\n", r"line 3"),
])
def test_tc_ingest_58_b_a_roster_without_names_is_refused_at_creation(
        tmp_data_dir, tmp_path, capsys, cell, text, words):
    """FR-INGEST-40: IDs-only is refused naming the requirement; so is one row without a name
    (#620's failure path), naming the line. Nothing is written."""
    _require_migration_registered()
    roster = tmp_path / f"{cell}.csv"
    roster.write_text(text, encoding="utf-8")
    assert _create(tmp_data_dir, "class-ids", roster) == 1, f"{cell}: accepted"
    err = capsys.readouterr().err
    assert re.search(words, err, re.IGNORECASE), f"{cell}: the refusal does not say why: {err!r}"
    assert "Nothing was written" in err, err
    cohorts = tmp_data_dir / "cohorts"
    assert not cohorts.exists() or not list(cohorts.iterdir()), f"{cell}: a cohort file was made"


def _build_cohort_at_32(data_dir: Path, cohort_id: str, refs) -> Path:
    path = Path(data_dir) / "cohorts" / f"{cohort_id}.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(str(_SCHEMA_VERSION_TABLE))
        for migration in TIER_MIGRATIONS[Tier.COHORT]:
            if migration.version > MIGRATION_VERSION - 1:
                continue
            for statement in migration.statements:
                connection.execute(str(statement))
            connection.execute(
                "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, "2026-01-01T00:00:00Z"))
        connection.execute("INSERT INTO cohort (cohort_id, consent_class, created_at) "
                           "VALUES (?, 'synthetic', '2026-01-01T00:00:00Z')", (cohort_id,))
        for ref in refs:
            connection.execute("INSERT INTO roster (cohort_id, student_ref) VALUES (?, ?)",
                               (cohort_id, ref))
        connection.commit()
    finally:
        connection.close()
    return path


@pytest.mark.writtenahead
def test_tc_ingest_58_c_a_cohort_32_store_migrates_to_33_and_still_resolves_by_ref(
        tmp_data_dir):
    _require_migration_registered()
    head = max(m.version for m in TIER_MIGRATIONS[Tier.COHORT])
    assert head == MIGRATION_VERSION, f"(c): the Cohort head is {head}, expected 33"
    owner = [m for m in TIER_MIGRATIONS[Tier.COHORT] if m.version == MIGRATION_VERSION]
    assert [m.name for m in owner] == [MIGRATION_NAME], owner
    assert COMPLETE_SCHEMA_VERSIONS[Tier.COHORT] == MIGRATION_VERSION, (
        "(c): the Cohort pin must move to 33 in the same change (RISK-119)")
    claude_md = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert MIGRATION_NAME in claude_md, (
        "(c): CLAUDE.md's migration-chain paragraph must name `ingest_roster_names`")

    _build_cohort_at_32(tmp_data_dir, "c-old", ("S9-001", "S9-002"))
    store = open_store(tmp_data_dir)
    try:
        handle = store.cohort("c-old")
        fx.require_names_column(handle)
        rows = handle.query("SELECT student_ref, full_name FROM roster ORDER BY student_ref")
        assert [(r["student_ref"], r["full_name"]) for r in rows] == [
            ("S9-001", None), ("S9-002", None)], "(c): pre-migration rows must read NULL"
        versions = [r["version"] for r in handle.query("SELECT version FROM schema_version")]
        assert max(versions) == MIGRATION_VERSION
        from aeh.ingest import Ingestor, ResidencySlot
        from aeh.prov import SamplingParams

        provider = fx.RecordingProvider()
        ingestor = Ingestor(handle, store.blobs(), provider, fx._model(),
                            SamplingParams(temperature=0.0), fx.OnePageRasterizer(),
                            residency=ResidencySlot.for_policy(("transcriber",)),
                            sanitizer=fx.ThroughSanitizer())
        source = store.blobs().put(b"fnames-old-sheet")
        provider.texts[(source, 1)] = fx.transcript("S9-002")
        report = ingestor.ingest_submission([source], cohort_id="c-old", package_version="v0",
                                            filenames={source: "scan-old.pdf"})
        resolved = handle.query("SELECT student_ref FROM submission WHERE submission_id = :s",
                                s=report.submission_id)
        assert report.gates.get("v3") == "pass" and resolved[0]["student_ref"] == "S9-002", (
            f"(c): a nameless pre-migration row must still resolve by ref, V3 said "
            f"{report.gates.get('v3')!r}: {fx.v3_findings(report)}")
    finally:
        store.close()


@pytest.mark.writtenahead
def test_tc_ingest_58_d_one_name_in_two_cohorts_gets_two_refs(tmp_data_dir, tmp_path, capsys):
    _require_migration_registered()
    roster = _names_csv(tmp_path, "one.csv", ["Amara Okafor", "Benito Ruiz"])
    assert _create(tmp_data_dir, "class-one", roster) == 0, capsys.readouterr().err
    assert _create(tmp_data_dir, "class-two", roster) == 0, capsys.readouterr().err
    capsys.readouterr()
    one = dict((n, r) for r, n in _roster_rows(tmp_data_dir, "class-one"))
    two = dict((n, r) for r, n in _roster_rows(tmp_data_dir, "class-two"))
    assert one["Amara Okafor"] != two["Amara Okafor"], (
        f"(d): the same name in two cohorts must yield two refs, got {one} / {two}")
    assert dict((n, r) for r, n in _roster_rows(tmp_data_dir, "class-one")) == one, (
        "(d): within one cohort the ref must be stable across re-reads")


# --- SEC-19 (re-run against the name-based matcher) --------------------------------------------

#: Every arm and every TC-INGEST-57 cell, as (cell id, written name, written ID).
SWEEP_CELLS = tuple((a.arm_id, a.written, None) for a in fx.ARMS) + (
    ("collision", fx.COLLISION_WRITTEN, None),
    ("collision-with-id", fx.COLLISION_WRITTEN, "S-0410"),
    ("collision-foreign-id", fx.COLLISION_WRITTEN, "S-0401"),
    ("unmatched", fx.UNMATCHED_WRITTEN, None),
    ("prefix", fx.PREFIX_WRITTEN, None),
)


@pytest.mark.writtenahead
@pytest.mark.parametrize("cell, written, student_id", SWEEP_CELLS,
                         ids=[c[0] for c in SWEEP_CELLS])
def test_sec_19_the_v3_request_and_triage_payload_carry_refs_never_names(
        tmp_data_dir, caplog, cell, written, student_id):
    caplog.set_level(logging.DEBUG)
    world = _world(tmp_data_dir, f"sec19-{cell}")
    try:
        report = world.ingest(f"sec19-{cell}", written, student_id)
        assert world.provider.requests, "fixture: no V3 request was assembled"
        for request in world.provider.requests:
            hits = fx.find_names(request)
            assert not hits, f"SEC-19 {cell}: the assembled request carries {hits}"
        candidates = fx.triage_candidates(report)
        if candidates is not None:
            assert set(candidates) <= set(fx.REFS), (
                f"SEC-19 {cell}: a triage candidate is not a student_ref: {candidates}")
            assert not fx.find_names(repr(candidates)), candidates
    finally:
        world.close()
    hits = fx.find_names(caplog.text)
    assert not hits, f"SEC-19 {cell}: a log record carries {hits}"


@pytest.mark.writtenahead
@pytest.mark.parametrize("cell, written, student_id", SWEEP_CELLS,
                         ids=[c[0] for c in SWEEP_CELLS])
def test_sec_19_the_v4_escalation_request_carries_no_name(
        tmp_data_dir, caplog, cell, written, student_id):
    """The request a paper's transcript actually reaches after V3: V4's semantic escalation
    (ADR-7) sends the transcript, `Student:` head included, to a model. With names as the
    identity signal, that head is the child's name — it must not leave in the request."""
    caplog.set_level(logging.DEBUG)
    world = _world(tmp_data_dir, f"sec19-v4-{cell}")
    try:
        world.bind_assessment()
        world.ingest_escalated(f"sec19-v4-{cell}", written, student_id)
        assert world.provider.escalations == 1, (
            "fixture: the paper did not reach V4's escalation, so the sweep would be vacuous")
        for request in world.provider.requests:
            hits = fx.find_names(request)
            assert not hits, (
                f"SEC-19 {cell}: the V4 escalation request carries {hits} (NFR-PROV-04, "
                f"CT-INGEST-23)")
    finally:
        world.close()
    assert not fx.find_names(caplog.text), f"SEC-19 {cell}: a log record carries a name"


def test_sec_19_the_sweep_detects_a_planted_name():
    """The sweep is not vacuous: a request or log line carrying any spelling is caught."""
    assert fx.find_names("prompt: name=ANA   silva")  # collapsed + case-folded
    assert fx.find_names("field=ana silva")
    assert fx.find_names(unicodedata.normalize("NFD", "x Chloé Lefèvre x"))
    assert fx.find_names("Greta Strauß signed")
    assert fx.find_names("key=haddad ines")            # a normalized match key
    assert fx.find_names("Student: Benito \t   Ruiz")  # the raw whitespace spelling
    assert not fx.find_names("S-0409 and S-0410, Student: <name>")
