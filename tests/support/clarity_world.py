"""The console-clarity test world (#812, `console_clarity_test_plan.md` §2.4): the ENG7 world
helpers and the **Jev-final seed** the clarity cases read.

**The ENG7 world.** The shipped `docs/live-tests/config/eng7-read-01.package.toml` (Q1 2, Q2 3,
Q3 3, out of 8; C1 = C1a + C1b, an evidence checklist; grades pass = 6, not yet = 0), built
through the real `aeh package build` path (`build_package`), and the sample-materials roster
names (`E7-001`..`E7-004`; no real student data anywhere). The authoring variants of the same
test are `fixtures/F-AUTHOR/AF-22` (no grade table) and `AF-23` (pass named, no boundary).

**The Jev-final seed.** Two students, each with four cells — one per §2.4 kind, on the four
judged ENG7 lines:

| line | kind | student A (E7-001) | student B (E7-002) |
|---|---|---|---|
| C1a | an accepted decision verdict, gate 0.91 | present (1) | present (1) |
| C1b | an LLM-only single verdict | present (1) | absent (0) |
| C2 | a three-judge agreeing panel (decision + 2 LLM) | adequate (2) | limited (1) |
| C3 | a breaker-tripped criterion (one LLM verdict) | change (2) | retell (1) |

So student A is Q1 2/2, Q2 2/3, Q3 2/3 — 6 of 8, *pass* (TC-CONSOLE-97's roll-up) — and
student B is Q1 1/2 (C1a 1 + C1b 0), Q2 1/3, Q3 1/3 — 3 of 8, *not yet*. One cohort is
seeded `synthetic` and one `real` (RC-18); both administer the same package version.

**The disclosed stand-ins.** The judge stage is not run: the verdicts are the shipped
`StoredVerdict` record (`aeh.judge.results`, the type `verdicts_for` returns), built here, and
each cell is aggregated by the shipped `aeh.agg.aggregate` and stored by the shipped
`aeh.agg.write_score` — the same two calls the pipeline's aggregate hook makes
(`aeh.pipeline.hooks`), with `breaker_tripped=True` on C3 as the hook passes it for a latched
criterion. What the store keeps of each cell's inputs: the accepted decision's
`decision_prescreen` row (outcome `accepted`, `gate_confidence` 0.91, `threshold` 0.80) and C3's
`circuit_breaker` latch. No `verdict` / `work_unit` rows are written (a verdict row joins the
ledger, which this seed does not enumerate).

**Written ahead.** The *states* the seed stores are whatever the shipped aggregator decides, so
the seed tightens by itself as the clarity stories land: today a single decision verdict is
`provisional_unreviewed` (FR-AGG-07); after #806 (FR-AGG-20) it is `final` / `auto` with the gate
as its confidence. If #806 reads the gate from somewhere a `StoredVerdict` does not carry,
`_cell_verdicts` is the one place to pass it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The full migration chain before the first store open (CLAUDE.md).
import aeh.agg  # noqa: F401
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

REPO_ROOT = Path(__file__).resolve().parents[2]
ENG7_SPEC = REPO_ROOT / "docs" / "live-tests" / "config" / "eng7-read-01.package.toml"
ENG7_ROSTER = REPO_ROOT / "docs" / "live-tests" / "config" / "eng7-roster.txt"
AUTHOR_CORPUS = REPO_ROOT / "fixtures" / "F-AUTHOR"
#: The clarity authoring variants: the four ENG7 PDFs, rubric without / with a nameless pass.
AF22_DIR = AUTHOR_CORPUS / "AF-22"
AF23_DIR = AUTHOR_CORPUS / "AF-23"

STAMP = "2026-10-20T09:00:00+00:00"

#: The ENG7 test in paper order: question -> (its top-level lines, its points).
ENG7_QUESTIONS: dict[str, tuple[tuple[str, ...], int]] = {
    "Q1": (("C1",), 2), "Q2": (("C2",), 3), "Q3": (("C3",), 3)}
ENG7_TOTAL_MAX = 8
ENG7_PASS = 6

#: The decision engine's gate on the accepted cell, and the threshold it cleared (FR-JUDGE-27).
JEV_GATE = 0.91
JEV_THRESHOLD = 0.80
JEV_BUILD = "openjev/jev-small@2026-06-01"

#: The sample-materials names (`eng7-roster.txt`); students A and B.
STUDENT_A = "E7-001"
STUDENT_B = "E7-002"
STUDENTS = (STUDENT_A, STUDENT_B)

#: §2.4's four kinds, one per judged ENG7 line (the module docstring's table).
CELL_KINDS: dict[str, str] = {
    "C1a": "decision_accepted",
    "C1b": "llm_single",
    "C2": "panel_agreeing",
    "C3": "breaker_tripped",
}

#: The band each student's cell lands on (every judge of a panel agrees on it).
SEED_BANDS: dict[str, dict[str, str]] = {
    STUDENT_A: {"C1a": "present", "C1b": "present", "C2": "adequate", "C3": "change"},
    STUDENT_B: {"C1a": "present", "C1b": "absent", "C2": "limited", "C3": "retell"},
}

#: What the roll-up of the seed must read (FR-CONSOLE-76; TC-CONSOLE-97's expected values):
#: student -> ([(question, points_awarded, points_max)], total_points, grade).
EXPECTED_ROLLUP: dict[str, tuple[tuple[tuple[str, int, int], ...], int, str]] = {
    STUDENT_A: ((("Q1", 2, 2), ("Q2", 2, 3), ("Q3", 2, 3)), 6, "pass"),
    STUDENT_B: ((("Q1", 1, 2), ("Q2", 1, 3), ("Q3", 1, 3)), 3, "not yet"),
}

#: The not-final reason each kind must carry once FR-AGG-20 lands (None: final, no code).
EXPECTED_REASONS: dict[str, str | None] = {
    "decision_accepted": None,
    "llm_single": "one_grader_unsure",
    "panel_agreeing": None,
    "breaker_tripped": "graders_refused",
}

COHORTS: dict[str, str] = {"synthetic": "eng7-clarity-synthetic", "real": "eng7-clarity-real"}


@dataclass(frozen=True)
class JevFinalSeed:
    """One seeded cohort: the ids a case addresses, and nothing it computed."""

    cohort_id: str
    consent_class: str
    run_id: str
    package_id: str
    package_version_id: str
    #: student name -> submission id
    submissions: dict[str, str]


@dataclass(frozen=True)
class JevFinalWorld:
    """Both cohorts of the seed over one ENG7 package version."""

    synthetic: JevFinalSeed
    real: JevFinalSeed


def _clock() -> str:
    return STAMP


def roster_names() -> tuple[str, ...]:
    """The ENG7 sample-materials class list, in file order (comments skipped)."""
    lines = ENG7_ROSTER.read_text(encoding="utf-8").splitlines()
    return tuple(s for s in (line.strip() for line in lines) if s and not s.startswith("#"))


def build_eng7_package(store: Any) -> tuple[str, str]:
    """The shipped ENG7 spec, built and published through `aeh package build`'s own path.
    Returns `(package_id, package_version_id)`."""
    from aeh.pipeline.packages import build_package, read_package_spec

    built = build_package(store, read_package_spec(ENG7_SPEC))
    return built.package_id, built.package_version


def _criterion(catalog: Any, version: str, criterion_id: str) -> Any:
    """The criterion value `aggregate` reads, shaped as the aggregate hook builds it (catalog
    row + bands). One deviation: `evidence_required` is fixed False here, where the hook reads
    `criterion_requires_citation` (fail-closed True for ENG7); the seed's verdicts are cited
    and its signals favourable, so the `evidence_present` cap never binds either way."""
    from types import SimpleNamespace

    row = next(r for r in catalog.criteria(version) if str(r["criterion_id"]) == criterion_id)
    fields = {str(k): row[k] for k in row.keys()}
    bands = tuple(catalog.bands(criterion_id))
    fields.update(criterion_id=criterion_id, bands=bands, band_count=len(bands),
                  evidence_required=False)
    return SimpleNamespace(**fields)


def _ordinal(criterion: Any, band: str) -> int:
    for row in criterion.bands:
        if str(row["band"]) == band:
            return int(row["ordinal"])
    raise KeyError(f"{criterion.criterion_id} declares no band {band!r}")


def _work_id(submission_id: str, criterion_id: str, seat: int) -> str:
    return f"w-{submission_id}-{criterion_id}-{seat}"


def _cell_verdicts(kind: str, submission_id: str, criterion: Any, band: str) -> tuple[Any, ...]:
    """The verdicts one cell of `kind` carries, as the shipped `StoredVerdict` record."""
    from aeh.judge.results import StoredVerdict

    ordinal = _ordinal(criterion, band)
    engines = {"decision_accepted": ("decision",), "llm_single": ("llm",),
               "panel_agreeing": ("decision", "llm", "llm"), "breaker_tripped": ("llm",)}[kind]
    return tuple(
        StoredVerdict(
            work_id=_work_id(submission_id, criterion.criterion_id, seat),
            judge_id="jev-seat" if engine == "decision" else f"judge-{seat}",
            band=band, band_ordinal=ordinal, cited_spans=("quoted words",),
            evidence_sufficient=True, uncited=False, scoring_engine=engine)
        for seat, engine in enumerate(engines))


def _favourable_signals() -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(spans_verified=True, evidence_present=True, sufficiency_flag=False,
                           ocr_overlap_risk=False, described_evidence=False,
                           extractor_disagreement=False)


def seed_jev_final(store: Any, *, consent_class: str = "synthetic",
                   package: tuple[str, str] | None = None) -> JevFinalSeed:
    """Seed one ENG7 cohort with the Jev-final cells (the module docstring's table).

    `package` reuses an ENG7 version an earlier call built (a second administration);
    otherwise the shipped spec is built. Deterministic: every id is derived from the
    consent class and the student name, and every timestamp the seed writes is `STAMP`."""
    from aeh.agg import aggregate, write_score
    from aeh.conf import CohortRef, resolve_run_config
    from aeh.orch import Orchestrator
    from aeh.orch.cohorts import RosterEntry, create_cohort
    from aeh.pkg import PackageCatalog
    from tests.support.conf_builders import edge_cfg

    cohort_id = COHORTS[consent_class]
    package_id, version = package if package is not None else build_eng7_package(store)
    refs = {name: f"ref-{name.lower()}" for name in STUDENTS}
    create_cohort(store, cohort_id, consent_class,
                  [RosterEntry(full_name=name, student_ref=refs[name]) for name in STUDENTS],
                  created_at=STAMP)
    submissions = {name: f"sub-{cohort_id}-{name.lower()}" for name in STUDENTS}
    cohort = store.cohort(cohort_id)
    with cohort.transaction() as tx:
        for name, submission_id in submissions.items():
            tx.execute("INSERT INTO submission (submission_id, cohort_id, student_ref) "
                       "VALUES (:s, :c, :r)", s=submission_id, c=cohort_id, r=refs[name])
    resolved = resolve_run_config(edge_cfg(), CohortRef(cohort_id=cohort_id,
                                                         consent_class=consent_class))
    run_id = Orchestrator(store, clock=_clock).create_run(
        cohort_id, version, resolved, run_id=f"run-{cohort_id}")

    catalog = PackageCatalog(store.package(package_id), package_id=package_id)
    criteria = {cid: _criterion(catalog, version, cid) for cid in CELL_KINDS}
    signals = _favourable_signals()
    with cohort.transaction() as tx:
        tx.execute(
            "INSERT INTO circuit_breaker (breaker_id, run_id, criterion_id, kind, tripped_at, "
            "detail) VALUES (:b, :r, 'C3', 'criterion_escalation', :t, :d)",
            b=f"brk-{run_id}-C3", r=run_id, t=STAMP,
            d=json.dumps({"seeded": "the clarity seed's breaker-tripped criterion"}))
        for name, submission_id in submissions.items():
            for criterion_id, kind in CELL_KINDS.items():
                criterion = criteria[criterion_id]
                band = SEED_BANDS[name][criterion_id]
                verdicts = _cell_verdicts(kind, submission_id, criterion, band)
                for verdict in verdicts:
                    if verdict.scoring_engine == "decision":
                        tx.execute(
                            "INSERT INTO decision_prescreen (work_id, run_id, submission_id, "
                            "criterion_id, engine_build, outcome, gate_confidence, "
                            "band_confidence, argmax_band, threshold) VALUES (:w, :r, :s, :c, "
                            ":b, 'accepted', :g, :g, :band, :th)",
                            w=verdict.work_id, r=run_id, s=submission_id, c=criterion_id,
                            b=JEV_BUILD, g=JEV_GATE, band=band, th=JEV_THRESHOLD)
                score = aggregate(verdicts, criterion, signals,
                                  breaker_tripped=kind == "breaker_tripped")
                write_score(tx, run_id, submission_id, score, signals)
    return JevFinalSeed(cohort_id=cohort_id, consent_class=consent_class, run_id=run_id,
                        package_id=package_id, package_version_id=version,
                        submissions=submissions)


def seed_jev_final_world(store: Any) -> JevFinalWorld:
    """Both cohorts — `synthetic` then `real` — over one ENG7 package version (RC-18)."""
    synthetic = seed_jev_final(store, consent_class="synthetic")
    real = seed_jev_final(store, consent_class="real", package=(
        synthetic.package_id, synthetic.package_version_id))
    return JevFinalWorld(synthetic=synthetic, real=real)


def score_rows(store: Any, seed: JevFinalSeed) -> dict[tuple[str, str], dict[str, Any]]:
    """The seed's stored `criterion_score` rows, keyed `(student name, criterion_id)`."""
    by_submission = {sub: name for name, sub in seed.submissions.items()}
    rows = store.cohort(seed.cohort_id).query(
        "SELECT * FROM criterion_score WHERE run_id = :r", r=seed.run_id)
    return {(by_submission[str(r["submission_id"])], str(r["criterion_id"])): dict(r)
            for r in rows}


#: The columns a canonical snapshot drops: the package version id (built with a fresh
#: proposal id and timestamp by `build_package`) is compared through the seed's own fields.
def canonical_snapshot(store: Any, world: JevFinalWorld) -> dict[str, Any]:
    """Everything the seed wrote that a consumer reads, as plain sorted data."""
    snapshot: dict[str, Any] = {}
    for seed in (world.synthetic, world.real):
        cohort = store.cohort(seed.cohort_id)
        part: dict[str, Any] = {"consent_class": seed.consent_class}
        for table, sql in (
            ("cohort", "SELECT cohort_id, consent_class FROM cohort"),
            ("submission", "SELECT submission_id, cohort_id, student_ref FROM submission"),
            ("criterion_score", "SELECT * FROM criterion_score"),
            ("decision_prescreen", "SELECT * FROM decision_prescreen"),
            ("circuit_breaker", "SELECT * FROM circuit_breaker"),
        ):
            part[table] = sorted(
                json.dumps(dict(row), sort_keys=True, default=str) for row in cohort.query(sql))
        snapshot[seed.cohort_id] = part
    return snapshot


def eng7_draft_questions() -> list[dict[str, Any]]:
    """The ENG7 questions as the drafter's inventory states them (paper order, points)."""
    return [{"id": qid, "type": "open", "points": points, "text": qid}
            for qid, (_lines, points) in ENG7_QUESTIONS.items()]


def eng7_grade_gaps(grades: dict[str, float | None]) -> list[Any]:
    """The `grades*` gaps the shipped draft assembler asks for the ENG7 test, given the grade
    table the documents state (AF-22: `{}`; AF-23: pass named, no boundary)."""
    from aeh.author.spec import assemble

    questions = eng7_draft_questions()
    assembly = assemble("ENG7-READ-01", questions, {q["id"]: None for q in questions},
                        {}, {}, grades)
    return [gap for gap in assembly.gaps if gap.item_id.startswith("grades")]


# --- the written-ahead probes (`WRITTEN_AHEAD_BLOCKERS`, `command` kind) --------------------
# Behavioural, not name-based: each exits 0 exactly when the behaviour its marked cases
# assert has shipped, so the gate fires the moment they can be unmarked.

def author_questions_landed() -> bool:
    """#809 (FR-AUTHOR-31/32): a grade gap carries its typed, ranged answer."""
    (gap,) = eng7_grade_gaps({})
    return getattr(gap, "answer_kind", None) is not None


def jev_final_on_accept_landed() -> bool:
    """#806 (FR-AGG-20): the seed's accepted-decision cell is stored `final`."""
    import tempfile

    from aeh.store import open_store

    with tempfile.TemporaryDirectory() as scratch:
        store = open_store(Path(scratch))
        try:
            seed = seed_jev_final(store)
            return score_rows(store, seed)[(STUDENT_A, "C1a")]["state"] == "final"
        finally:
            store.close()


__all__ = [
    "author_questions_landed", "eng7_draft_questions", "eng7_grade_gaps",
    "jev_final_on_accept_landed",
    "AF22_DIR", "AF23_DIR", "CELL_KINDS", "COHORTS", "ENG7_PASS", "ENG7_QUESTIONS",
    "ENG7_SPEC", "ENG7_TOTAL_MAX", "EXPECTED_REASONS", "EXPECTED_ROLLUP", "JEV_GATE",
    "JEV_THRESHOLD", "JevFinalSeed", "JevFinalWorld", "SEED_BANDS", "STUDENTS", "STUDENT_A",
    "STUDENT_B", "build_eng7_package", "canonical_snapshot", "roster_names", "score_rows",
    "seed_jev_final", "seed_jev_final_world",
]
