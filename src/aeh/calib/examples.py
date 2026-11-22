"""The teacher's marked examples, graded under R0 and compared (FR-CALIB-16/17, D5, ADR-59).

A package version's marked examples live in their own cohort, `purpose = 'calibration'`
(Cohort migration 38), whose id carries the store's reserved prefix
(`aeh.store.CALIBRATION_COHORT_PREFIX`). That is what keeps them out of every class list,
result, export, review queue, label and statistic (CT-CALIB-18): the readers that serve classes
enumerate cohort files through `aeh.store.class_cohort_keys`, which never opens one.

The flow, each step headless (seam 1):

1. `add_examples` reads each uploaded PDF into the calibration cohort through M-PIPE's paper
   door (the same reader, the same five intake checks a class's papers get). The cohort lists
   one roster entry per example, named after its file; an example's own name never matches
   one, so each parks at the identity check by design and is then given to its entry and
   released (`assign_identity_parked_paper`) — only when identity is its one failed check. A
   page carrying marks (`clean_copy_check`) keeps it parked, never graded.
2. The teacher's bands are stored on the package version (M-PKG `record_example_marks`).
3. `grade_examples` grades the examples under the version the marks were made under (R0)
   through the composition root's driver (`aeh.pipeline.drive_run` -> `run_to_completion`,
   CT-PIPE-01), so the result carries a class run's stage set, the cost counts against the run
   cost ceiling, and the consent gate applies. R31 is stricter than the consent gate: on a
   remote profile, any consent class but `synthetic` is refused before anything is read.
   Nothing here promotes an administration — the examples never produce agreement (D5).
4. `compare` runs `discover` -> `triage` -> `elicit` over the stored rows, every time it is
   read: nothing derived is persisted, so there is no second copy to drift.
5. `answer_questions` applies the teacher's answers through `apply_answers` (M-PKG's §6.2
   lock) on the published R0, giving R1 pending its gates (FR-CALIB-18); `skip_examples`
   records each open question as skipped in the elicitation history and grades with R0, the
   ambiguous criteria lower-confidence (FR-CALIB-13).

No value this module returns carries a count of matches, a rate or an agreement figure
(CT-CALIB-03): with a dozen papers the teacher chose, a percentage would say nothing.
"""

from __future__ import annotations

import hashlib
import threading
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from typing import Any

from aeh.store import CALIBRATION_COHORT_PREFIX, Statement

from .constants import LOGGER, MODEL_FAILURE, RUBRIC_AMBIGUITY, TEACHER_INCONSISTENCY
from .discovery import Disagreement, DiscoveryReport, TriageVerdict, discover, triage
from .driver import CalibrationRunOutcome, assignment, run_for_assignment
from .elicitation import ElicitationQuestion, Finding, apply_answers, elicit
from .errors import CalibrationError

#: The roster ref prefix of an example's entry in its calibration cohort.
EXAMPLE_REF_PREFIX = "example-"

#: What a skipped question's history row records as the teacher's answer (FR-CALIB-14).
SKIPPED_ANSWER = "skipped"

#: The intake statuses that leave a paper graded (FR-INGEST-29).
_ADMITTED = frozenset({"ok", "low_confidence_ocr"})

#: The run statuses that end a grading (the run will not move on its own).
_SETTLED = frozenset({"complete", "failed", "paused"})


#: `elicit` keeps the questions it asked in a process-global session that `apply_answers`
#: resolves `q1..qn` against. The console serves reads on many threads, so a comparison and an
#: answer hold this lock: no other comparison can replace the session between the two.
_SESSION_LOCK = threading.RLock()


class ExamplesRefused(CalibrationError):
    """A refusal of the examples step, worded for the teacher; nothing was written."""


#: Every statement this module runs, declared (SEC-15, FR-STORE-08): reads only, each against
#: the calibration cohort's own file except the run's cost, which `run_metrics` keeps in
#: Durable.
EXAMPLES_STATEMENTS: dict[str, Statement] = {
    "select_example_papers": Statement(
        "SELECT s.submission_id, s.student_ref, s.ingest_status, s.quarantined, r.full_name "
        "FROM submission s JOIN roster r ON r.student_ref = s.student_ref "
        "WHERE s.cohort_id = :cohort_id ORDER BY s.student_ref"
    ),
    "select_roster_entries": Statement(
        "SELECT student_ref, full_name FROM roster WHERE cohort_id = :cohort_id "
        "ORDER BY student_ref"
    ),
    "select_submission_document": Statement(
        "SELECT document_id, markdown FROM document WHERE submission_id = :submission_id "
        "ORDER BY CASE kind WHEN 'submission' THEN 0 ELSE 1 END, document_id LIMIT 1"
    ),
    "select_document_markdown": Statement(
        "SELECT markdown FROM document WHERE document_id = :document_id"
    ),
    "select_question_regions": Statement(
        "SELECT content FROM document_region WHERE document_id = :document_id "
        "AND question_id = :question_id ORDER BY position, region_id"
    ),
    "select_version_runs": Statement(
        "SELECT run_id, status, started_at FROM run WHERE cohort_id = :cohort_id "
        "AND package_version_id = :package_version_id ORDER BY started_at, run_id"
    ),
    "select_run_provider_config": Statement(
        "SELECT provider_config FROM run WHERE run_id = :run_id"
    ),
    "select_run_scores": Statement(
        "SELECT submission_id, criterion_id, band, state, evidence_present "
        "FROM criterion_score WHERE run_id = :run_id ORDER BY submission_id, criterion_id"
    ),
    "select_run_reasons": Statement(
        "SELECT w.submission_id, w.criterion_id, v.band, v.evidence_assessment "
        "FROM verdict v JOIN work_unit w ON w.work_id = v.work_id "
        "WHERE w.run_id = :run_id ORDER BY v.verdict_id"
    ),
    "select_run_cost": Statement(
        "SELECT metric, value, submission_id, criterion_id FROM run_metrics "
        "WHERE run_id = :run_id "
        "AND metric IN ('actual_cost', 'estimated_cost', 'cost_currency')"
    ),
}


# --- identity and the R31 refusal ---------------------------------------------------------------


def calibration_cohort_id(package_version_id: str) -> str:
    """The calibration cohort that holds one package version's marked examples: the reserved
    prefix and a digest of the version id (a version id may hold characters a file name may
    not)."""
    digest = hashlib.sha256(str(package_version_id).encode("utf-8")).hexdigest()[:24]
    return f"{CALIBRATION_COHORT_PREFIX}{digest}"


def _profile_of(config: Mapping[str, Any]) -> str:
    return str(config.get("HARNESS_PROFILE") or config.get("backend_profile") or "")


def refuse_remote_real_work(config: Mapping[str, Any], consent_class: str) -> None:
    """R31: on a remote profile the examples may only be made-up practice work. Stricter than
    the consent gate (`HARNESS_ALLOW_REMOTE_REAL_WORK` does not lift it): the examples are the
    teacher's own chosen papers, graded for nobody's results. Raises before anything is read or
    sent."""
    from aeh.conf import REMOTE_PROFILES

    if _profile_of(config) in REMOTE_PROFILES and consent_class != "synthetic":
        raise ExamplesRefused(
            "Your own students' papers cannot be sent to an online model to check your "
            "examples. Use made-up practice papers, or switch to the local models in the "
            "settings. Nothing was sent.")


# --- the catalog and the cohort ----------------------------------------------------------------


def _catalog(store: Any, package_version_id: str) -> Any:
    from aeh.orch import default_package_id_for
    from aeh.pkg import PackageCatalog

    package_id = default_package_id_for(package_version_id)
    return PackageCatalog(store.package(package_id), package_id=package_id,
                          blobs=store.blobs())


def _cohort_exists(store: Any, cohort_id: str) -> bool:
    from pathlib import Path

    path = getattr(store, "cohort_path", None)
    return bool(path) and Path(path(cohort_id)).exists()


def _rows(store: Any, key: str, name: str, /, **params: Any) -> list[dict[str, Any]]:
    """One declared read against the calibration cohort file `key`."""
    return [dict(row) for row in
            store.cohort(key).query(EXAMPLES_STATEMENTS[name], **params)]


def _number_of(ref: str) -> int:
    """An example's place in upload order, from its roster ref's trailing digits."""
    digits = "".join(ch for ch in ref[len(EXAMPLE_REF_PREFIX):] if ch.isdigit())
    return int(digits) if digits else 0


@dataclass(frozen=True)
class MarkedExample:
    """One example as the teacher uploaded it: the transcript its bands are keyed by, its paper
    in the calibration cohort, the file name the teacher chose, and its place in upload order."""

    document_id: str
    submission_id: str
    file_name: str
    number: int


def examples_of(store: Any, package_version_id: str) -> tuple[MarkedExample, ...]:
    """The version's examples that were accepted (read, checked clean and released to grading),
    in upload order. Empty when the version has no calibration cohort."""
    cohort_id = calibration_cohort_id(package_version_id)
    if not _cohort_exists(store, cohort_id):
        return ()
    found: list[MarkedExample] = []
    for row in _rows(store, cohort_id, "select_example_papers", cohort_id=cohort_id):
        ref = str(row["student_ref"] or "")
        if (not ref.startswith(EXAMPLE_REF_PREFIX) or row["quarantined"]
                or str(row["ingest_status"] or "") not in _ADMITTED):
            continue
        documents = _rows(store, cohort_id, "select_submission_document",
                          submission_id=row["submission_id"])
        if not documents:
            continue
        found.append(MarkedExample(
            document_id=str(documents[0]["document_id"]),
            submission_id=str(row["submission_id"]),
            file_name=str(row["full_name"] or ""),
            number=_number_of(ref),
        ))
    return tuple(found)


# --- upload ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ExamplesUpload:
    """What one upload did: the examples it added as (file name, document id), the files it
    refused with the reason in the teacher's words, and every accepted example now held."""

    cohort_id: str
    added: tuple[tuple[str, str], ...]
    refused: tuple[tuple[str, str], ...]
    examples: tuple[MarkedExample, ...]
    notes: tuple[str, ...] = ()


def add_examples(
    store: Any,
    package_version_id: str,
    files: Sequence[tuple[str, bytes]],
    *,
    config: Mapping[str, Any],
    consent_class: str | None = None,
    test_paper: tuple[str, bytes] | None = None,
    provider: Any = None,
    clean_copy_check: Callable[[str], Sequence[int]] | None = None,
    limit: int = 25,
    actor: str = "teacher",
) -> ExamplesUpload:
    """Read marked examples into the version's calibration cohort (FR-SETUP-20, FR-CALIB-17).

    `files` are (file name, PDF bytes); `test_paper` is the test's blank paper, needed once per
    cohort (the right-test check compares each example with it). `consent_class` is needed when
    the cohort does not exist yet and has no default (FR-CONF-08's posture). Refused before
    anything is read: an unknown version, a version already graded from its examples, more than
    `limit` examples in all, no consent class, and remote work that is not `synthetic` (R31).
    Each file is then read; a file that cannot be read, is not this test, or shows marks
    (`clean_copy_check` returns the marked page numbers) is refused by name and never graded."""
    from aeh.orch import RosterEntry, add_to_roster, cohort_summary, create_cohort
    from aeh.pipeline import (
        assign_identity_parked_paper,
        cohort_has_test_paper,
        read_uploaded_paper,
    )

    files = [(str(name), bytes(data)) for name, data in files]
    if not files:
        raise ExamplesRefused("Choose at least one marked example to upload.")
    catalog = _catalog(store, package_version_id)
    if not catalog.criteria(package_version_id):
        raise ExamplesRefused("That test could not be found. Choose it again from the list.")
    cohort_id = calibration_cohort_id(package_version_id)
    summary = cohort_summary(store, cohort_id) if _cohort_exists(store, cohort_id) else None
    consent = summary.consent_class if summary is not None else consent_class
    if not consent:
        raise ExamplesRefused(
            "Say whether these are made-up practice papers or your students' real work, then "
            "upload them again. Nothing was stored.")
    refuse_remote_real_work(config, str(consent))
    if summary is not None and grading_run(store, package_version_id) is not None:
        raise ExamplesRefused(
            "Your examples have already been checked, so no more can be added to this test.")
    if test_paper is None and (summary is None or not cohort_has_test_paper(store, cohort_id)):
        raise ExamplesRefused(
            "Upload the blank test paper with your first examples: each example is checked "
            "against it. Nothing was read.")
    held = examples_of(store, package_version_id)
    if len(held) + len(files) > limit:
        raise ExamplesRefused(
            f"You can upload at most {limit} marked examples, and this would make "
            f"{len(held) + len(files)}.")
    entries = (_rows(store, cohort_id, "select_roster_entries", cohort_id=cohort_id)
               if summary is not None else [])
    next_number = 1 + max((_number_of(str(e["student_ref"])) for e in entries
                           if str(e["student_ref"]).startswith(EXAMPLE_REF_PREFIX)),
                          default=0)

    notes: list[str] = []
    added: list[tuple[str, str]] = []
    refused: list[tuple[str, str]] = []
    for name, data in files:
        ref = f"{EXAMPLE_REF_PREFIX}{next_number:02d}"
        next_number += 1
        entry = RosterEntry(full_name=name, student_ref=ref)
        if summary is None:
            summary = create_cohort(store, cohort_id, str(consent), [entry],
                                    purpose="calibration")
            notes.append(f"created calibration cohort {cohort_id} ({consent})")
        else:
            add_to_roster(store, cohort_id, [entry])
        if not cohort_has_test_paper(store, cohort_id):
            if test_paper is None:
                raise ExamplesRefused(
                    "Upload the blank test paper with your first examples: each example is "
                    "checked against it. Nothing was read.")
            read_uploaded_paper(store, config, cohort_id, package_version_id,
                                kind="assessment", filename=test_paper[0],
                                data=test_paper[1], provider=provider)
        result = read_uploaded_paper(store, config, cohort_id, package_version_id,
                                     kind="sheet", filename=name, data=data,
                                     provider=provider)
        sheet = result.sheets[0] if result.sheets else None
        if sheet is not None and sheet.status == "skipped":
            refused.append((name, "It was already uploaded."))
            continue
        if sheet is None or not sheet.submission_id or not sheet.document_id:
            refused.append((name, "It could not be read. Check it is a clear PDF scan."))
            continue
        if clean_copy_check is not None:
            markdown = _rows(store, cohort_id, "select_document_markdown",
                             document_id=sheet.document_id)
            pages = tuple(clean_copy_check(str(markdown[0]["markdown"]) if markdown else ""))
            if pages:
                refused.append((name, " ".join(
                    f"Page {page} of {name} has marks on it." for page in pages)
                    + " Please upload an unmarked copy, and enter your marks in the form."))
                continue
        if sheet.status not in _ADMITTED:
            try:
                assign_identity_parked_paper(
                    store, cohort_id, sheet.submission_id, ref, actor=actor,
                    note="marked example: given to its own entry (FR-CALIB-17)")
            except ValueError:
                refused.append((name, "It does not look like a paper for this test, or a "
                                      "page is missing, so it cannot be used."))
                continue
        added.append((name, sheet.document_id))
    LOGGER.info("marked examples for %s: %d added, %d refused (cohort %s)",
                package_version_id, len(added), len(refused), cohort_id)
    return ExamplesUpload(cohort_id=cohort_id, added=tuple(added), refused=tuple(refused),
                          examples=examples_of(store, package_version_id),
                          notes=tuple(notes))


# --- grading under R0 ------------------------------------------------------------------------


def grading_run(store: Any, package_version_id: str) -> tuple[str, str] | None:
    """The latest run grading the version's examples, as (run id, status), or None."""
    cohort_id = calibration_cohort_id(package_version_id)
    if not _cohort_exists(store, cohort_id):
        return None
    runs = _rows(store, cohort_id, "select_version_runs", cohort_id=cohort_id,
                 package_version_id=package_version_id)
    if not runs:
        return None
    return str(runs[-1]["run_id"]), str(runs[-1]["status"])


@dataclass(frozen=True)
class ExamplesCost:
    """What grading the examples cost, as the run recorded it (NFR-CALIB-05): the spend, the
    run's estimate, the run cost ceiling it counted against, and the currency. Each is None when
    the run recorded none."""

    spent: Decimal | None = None
    estimated: Decimal | None = None
    ceiling: Decimal | None = None
    currency: str | None = None


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def examples_cost(store: Any, package_version_id: str) -> ExamplesCost:
    """The grading run's recorded cost and the ceiling it ran under (NFR-CALIB-05)."""
    import json

    found = grading_run(store, package_version_id)
    if found is None:
        return ExamplesCost()
    run_id = found[0]
    cohort_id = calibration_cohort_id(package_version_id)
    # `run_metrics` is Durable (M-ORCH writes it there for every run).
    metrics = {str(row["metric"]): row["value"] for row in store.durable().query(
        EXAMPLES_STATEMENTS["select_run_cost"], run_id=run_id)
        if not row["submission_id"] and not row["criterion_id"]}
    config_rows = _rows(store, cohort_id, "select_run_provider_config", run_id=run_id)
    try:
        frozen = json.loads(config_rows[0]["provider_config"]) if config_rows else {}
    except (TypeError, ValueError):
        frozen = {}
    currency = metrics.get("cost_currency") or frozen.get("cost_currency")
    return ExamplesCost(
        spent=_decimal(metrics.get("actual_cost")),
        estimated=_decimal(metrics.get("estimated_cost")),
        ceiling=_decimal(frozen.get("cost_ceiling")),
        currency=str(currency) if currency else None,
    )


@dataclass(frozen=True)
class ExamplesGrading:
    """One grading of the examples: the calibration cohort, the version graded (R0), and
    `run_to_completion`'s result — the same stage set as a class run (CT-PIPE-01)."""

    cohort_id: str
    package_version_id: str
    result: Any
    cost: ExamplesCost = field(default_factory=ExamplesCost)

    @property
    def run_id(self) -> str:
        return str(self.result.run_id)


def grade_examples(
    store: Any,
    package_version_id: str,
    *,
    config: Mapping[str, Any],
    provider: Any = None,
    **drive_keywords: Any,
) -> ExamplesGrading:
    """Grade the version's marked examples under that version (R0) through the composition
    root's driver (FR-CALIB-17): `aeh.pipeline.drive_run`, which resolves the configuration as
    `aeh run` does (the consent gate, the retention check, the run cost ceiling) and drives
    `run_to_completion`. Refused before any call: no example, no marked example, a grading
    already started, and remote work that is not `synthetic` (R31). Never promotes an
    administration: the examples produce no agreement figure (D5)."""
    from aeh.orch import cohort_summary
    from aeh.pipeline import drive_run

    cohort_id = calibration_cohort_id(package_version_id)
    held = examples_of(store, package_version_id)
    if not held:
        raise ExamplesRefused("Upload at least one marked example before checking them.")
    marked = {str(row["document_id"]) for row in
              _catalog(store, package_version_id).example_marks(package_version_id)}
    if not any(example.document_id in marked for example in held):
        raise ExamplesRefused("Enter your marks for at least one example before checking them.")
    summary = cohort_summary(store, cohort_id)
    refuse_remote_real_work(config, str(summary.consent_class if summary else "real"))
    if grading_run(store, package_version_id) is not None:
        raise ExamplesRefused("Your examples have already been checked.")
    result = drive_run(store, cohort_id=cohort_id, package_version_id=package_version_id,
                       config=config, provider=provider, **drive_keywords)
    LOGGER.info("graded %d marked example(s) of %s under R0: run %s %s",
                len(held), package_version_id, result.run_id, result.status)
    return ExamplesGrading(cohort_id=cohort_id, package_version_id=package_version_id,
                           result=result, cost=examples_cost(store, package_version_id))


# --- discovery, triage, elicitation over the stored rows (FR-CALIB-16) -------------------------


@dataclass(frozen=True)
class Difference:
    """One line where the teacher and the system marked an example differently: which example
    and part, the answer, the teacher's band, the system's band and its reason, and the triage
    verdict (its category says which of the three causes it is)."""

    example: MarkedExample
    criterion_id: str
    question_id: str
    answer: str
    teacher_band: str
    system_band: str
    system_reason: str
    verdict: TriageVerdict
    paired_with: MarkedExample | None = None


@dataclass(frozen=True)
class Comparison:
    """What the comparison found for one version: the discovery report, each difference with
    its triage verdict, the questions put to the teacher, and the elicitation history so far.
    No field counts matches or rates them (CT-CALIB-03)."""

    package_version_id: str
    run_id: str | None
    run_status: str | None
    examples: tuple[MarkedExample, ...]
    report: DiscoveryReport | None
    differences: tuple[Difference, ...]
    questions: tuple[ElicitationQuestion, ...]
    history: tuple[dict, ...]

    @property
    def ambiguous_criteria(self) -> tuple[str, ...]:
        return tuple(sorted({d.criterion_id for d in self.differences
                             if d.verdict.category == RUBRIC_AMBIGUITY}))

    @property
    def answered(self) -> bool:
        return any(str(row.get("answer_given")) != SKIPPED_ANSWER for row in self.history)

    @property
    def skipped(self) -> bool:
        return any(str(row.get("answer_given")) == SKIPPED_ANSWER for row in self.history)


def _answer_text(store: Any, cohort_id: str, document_id: str, question_id: str) -> str:
    regions = _rows(store, cohort_id, "select_question_regions", document_id=document_id,
                    question_id=question_id)
    return "\n".join(str(r["content"] or "").strip() for r in regions if r["content"]).strip()


def _category(paper: str, criterion_id: str, model: dict[str, dict[str, Any]],
              teacher: dict[str, dict[str, Any]], score: dict[str, Any]
              ) -> tuple[str, str | None]:
    """The deterministic triage rule, and the paired example a teacher inconsistency shows:

    - the system could not score the answer cleanly (a score that is not `final`, or no
      evidence found for it) -> `model_failure`, sent to the extraction stage;
    - another example the system put in the same band, which the teacher marked differently
      -> `teacher_inconsistency`, the two shown side by side and never fitted to;
    - otherwise -> `rubric_ambiguity`, the one category a question may come from."""
    if str(score.get("state") or "final") != "final" or score.get("evidence_present") == 0:
        return MODEL_FAILURE, None
    mine_model = model[paper][criterion_id]
    mine_teacher = teacher[paper][criterion_id]
    for other in sorted(model):
        if other == paper or criterion_id not in model[other]:
            continue
        if criterion_id not in teacher.get(other, {}):
            continue
        if (model[other][criterion_id] == mine_model
                and teacher[other][criterion_id] != mine_teacher):
            return TEACHER_INCONSISTENCY, other
    return RUBRIC_AMBIGUITY, None


def compare(store: Any, package_version_id: str, *,
            environ: Mapping[str, str] | None = None) -> Comparison:
    """`discover` -> `triage` -> `elicit` over the stored rows (see `_compare`), under the
    elicitation session's lock."""
    with _SESSION_LOCK:
        return _compare(store, package_version_id, environ=environ)


def _compare(store: Any, package_version_id: str, *,
             environ: Mapping[str, str] | None = None) -> Comparison:
    """`discover` -> `triage` -> `elicit` over the version's graded examples and the teacher's
    bands, read fresh from the stored rows (FR-CALIB-16). Before the grading has completed the
    comparison holds the examples and nothing else."""
    cohort_id = calibration_cohort_id(package_version_id)
    held = examples_of(store, package_version_id)
    catalog = _catalog(store, package_version_id)
    history = catalog.elicitation_history(package_version_id)
    found = grading_run(store, package_version_id)
    empty = Comparison(package_version_id=package_version_id,
                       run_id=found[0] if found else None,
                       run_status=found[1] if found else None, examples=held, report=None,
                       differences=(), questions=(), history=history)
    if found is None or found[1] != "complete" or not held:
        return empty
    run_id = found[0]
    criteria = {str(row["criterion_id"]): dict(row)
                for row in catalog.criteria(package_version_id)}
    by_document = {example.document_id: example for example in held}
    by_submission = {example.submission_id: example for example in held}
    teacher: dict[str, dict[str, Any]] = {}
    for row in catalog.example_marks(package_version_id):
        if str(row["document_id"]) in by_document:
            teacher.setdefault(str(row["document_id"]), {})[str(row["criterion_id"])] = (
                str(row["band"]))
    scores: dict[tuple[str, str], dict[str, Any]] = {}
    model: dict[str, dict[str, Any]] = {}
    for row in _rows(store, cohort_id, "select_run_scores", run_id=run_id):
        example = by_submission.get(str(row["submission_id"]))
        if example is None:
            continue
        model.setdefault(example.document_id, {})[str(row["criterion_id"])] = str(row["band"])
        scores[(example.document_id, str(row["criterion_id"]))] = row
    # The reason shown is a verdict's own assessment: one that landed on the band the score
    # kept, else the first one recorded.
    reasons: dict[tuple[str, str], str] = {}
    kept: set[tuple[str, str]] = set()
    for row in _rows(store, cohort_id, "select_run_reasons", run_id=run_id):
        example = by_submission.get(str(row["submission_id"]))
        if example is None or not row["evidence_assessment"]:
            continue
        key = (example.document_id, str(row["criterion_id"]))
        if key in kept:
            continue
        reasons.setdefault(key, str(row["evidence_assessment"]))
        if model.get(key[0], {}).get(key[1]) == str(row["band"]):
            reasons[key] = str(row["evidence_assessment"])
            kept.add(key)
    modes = {cid: str(row.get("evaluation_mode") or "") for cid, row in criteria.items()}
    papers = [example.document_id for example in held]
    report = discover(package_version_id, papers, teacher_bands=teacher, model_bands=model,
                      evaluation_modes=modes, environ=environ)

    differences: list[Difference] = []
    for disagreement in report.disagreements:
        paper = str(disagreement.sample_id)
        criterion_id = disagreement.criterion_id
        category, other = _category(paper, criterion_id, model, teacher,
                                    scores.get((paper, criterion_id), {}))
        examples: tuple[Any, ...] = ()
        if category == TEACHER_INCONSISTENCY and other is not None:
            examples = ((paper, teacher[paper][criterion_id]),
                        (other, teacher[other][criterion_id]))
        verdict = triage(replace(disagreement, category=category, examples=examples,
                                 pipeline_stage="extraction" if category == MODEL_FAILURE
                                 else None))
        question_id = str(criteria.get(criterion_id, {}).get("question_id") or "")
        differences.append(Difference(
            example=by_document[paper],
            criterion_id=criterion_id,
            question_id=question_id,
            answer=_answer_text(store, cohort_id, paper, question_id) if question_id else "",
            teacher_band=str(disagreement.teacher_band),
            system_band=str(disagreement.model_band),
            system_reason=reasons.get((paper, criterion_id), ""),
            verdict=verdict,
            paired_with=by_document.get(other) if other else None,
        ))

    questions = elicit(_findings(catalog, package_version_id, differences), environ=environ)
    return Comparison(package_version_id=package_version_id, run_id=run_id,
                      run_status=found[1], examples=held, report=report,
                      differences=tuple(differences), questions=questions, history=history)


def _findings(catalog: Any, package_version_id: str,
              differences: Sequence[Difference]) -> list[Finding]:
    """One finding per criterion with a rubric-ambiguity difference: how many examples it
    affects, two of them, and the band whose descriptor is in question (the one the teacher
    chose most often there)."""
    grouped: dict[str, list[Difference]] = {}
    for difference in differences:
        if difference.verdict.category == RUBRIC_AMBIGUITY:
            grouped.setdefault(difference.criterion_id, []).append(difference)
    catalog.criteria(package_version_id)  # load the version's bands into the read cache
    findings: list[Finding] = []
    for criterion_id, group in grouped.items():
        band = Counter(d.teacher_band for d in group).most_common(1)[0][0]
        ordinal = next((int(row["ordinal"]) for row in catalog.bands(criterion_id)
                        if str(row["band"]) == band), 0)
        findings.append(Finding(
            criterion_id=criterion_id, category=RUBRIC_AMBIGUITY,
            submissions_affected=len(group),
            examples=tuple(d.example.document_id for d in group[:2]),
            band_ordinal=ordinal,
        ))
    return findings


# --- answers and the skip ----------------------------------------------------------------------


def answer_questions(
    store: Any,
    package_version_id: str,
    answers: Mapping[str, str],
    *,
    rubric_published_in_advance: bool = False,
    environ: Mapping[str, str] | None = None,
) -> CalibrationRunOutcome:
    """Apply the teacher's answers (keyed by question id, `q1..qn`) through `apply_answers` on
    the published R0, under M-PKG's §6.2 lock (FR-CALIB-16): an edit lands on a new version R1,
    pending its gates on the first class (FR-CALIB-18); the class is still graded with R0. A
    rubric published to students in advance defaults to R0 and says the clarifications apply to
    the next class (CT-CALIB-10): nothing is applied, and the answers are kept in the
    elicitation history (no resulting edit) for the next class's rubric."""
    with _SESSION_LOCK:
        return _answer_questions(store, package_version_id, answers,
                                 rubric_published_in_advance=rubric_published_in_advance,
                                 environ=environ)


def _answer_questions(store: Any, package_version_id: str, answers: Mapping[str, str], *,
                      rubric_published_in_advance: bool,
                      environ: Mapping[str, str] | None) -> CalibrationRunOutcome:
    comparison = _compare(store, package_version_id, environ=environ)
    if not comparison.questions:
        raise ExamplesRefused("There are no questions to answer for this test.")
    if comparison.answered or comparison.skipped:
        raise ExamplesRefused("The questions for this test have already been dealt with.")
    asked = {question.question_id for question in comparison.questions}
    unknown = sorted(set(answers) - asked)
    if unknown or not answers:
        raise ExamplesRefused("Some answers do not match a question shown. Reload the "
                              "questions and answer them again.")
    if rubric_published_in_advance:
        from .elicitation import QUESTION_OPTIONS

        catalog = _catalog(store, package_version_id)
        by_id = {question.question_id: question for question in comparison.questions}
        for question_id, answer in sorted(answers.items()):
            catalog.append_elicitation(package_version_id, by_id[question_id].question,
                                       list(QUESTION_OPTIONS), str(answer), resulting_edit="")
        return run_for_assignment(assignment(
            rubric_published_in_advance=True, r0_version=package_version_id,
            ambiguous_criteria=comparison.ambiguous_criteria))
    catalog = _catalog(store, package_version_id)
    if catalog.published_by(package_version_id) is None:
        raise ExamplesRefused(
            "Publish the test first. Your answers then make a clarified version that is "
            "checked on your first class before it is used.")
    revised = apply_answers(dict(answers), catalog=catalog, package_version=package_version_id)
    gate_notes: tuple[str, ...] = ()
    if revised is not None:
        # FR-CALIB-18: back-translation runs at R1's creation, and R1 is recorded as pending
        # its non-inferiority check on the first class.
        from .first_class import open_revision

        opened = open_revision(store, package_version_id, revised)
        gate_notes = (f"back-translation at creation: {opened.back_translation}",)
    lower = comparison.ambiguous_criteria if revised is None else ()
    LOGGER.info("examples answers for %s: %d answer(s), revision %s", package_version_id,
                len(answers), revised or "none")
    return CalibrationRunOutcome(
        r0_version=package_version_id,
        active_rubric=package_version_id,
        fairness_note=(
            "the answers produced a revision pending its gates on the first class; this "
            "class is graded with R0" if revised else
            "every answer kept the rubric as is; graded with R0 unchanged"),
        skipped=revised is None,
        questions_asked=len(comparison.questions),
        revised_version=revised,
        lower_confidence_criteria=lower,
        revision_shipped=False,
        notes=("R1 pending: back-translation and the first-class dual score decide "
               "(FR-CALIB-18)",) + gate_notes if revised else (),
    )


def skip_examples(store: Any, package_version_id: str, *,
                  environ: Mapping[str, str] | None = None) -> CalibrationRunOutcome:
    """Skip at any point: the class is graded with R0 unchanged and the ambiguous criteria are
    lower-confidence (FR-CALIB-13). Open questions are recorded as skipped in the elicitation
    history (FR-CALIB-14), so the skip is provenance, not silence."""
    comparison = compare(store, package_version_id, environ=environ)
    if comparison.questions and not (comparison.answered or comparison.skipped):
        from .elicitation import QUESTION_OPTIONS

        catalog = _catalog(store, package_version_id)
        for question in comparison.questions:
            catalog.append_elicitation(package_version_id, question.question,
                                       list(QUESTION_OPTIONS), SKIPPED_ANSWER,
                                       resulting_edit="")
    return run_for_assignment(assignment(
        skip_elicitation=True, r0_version=package_version_id,
        ambiguous_criteria=comparison.ambiguous_criteria))


__all__ = [
    "Comparison",
    "Difference",
    "EXAMPLE_REF_PREFIX",
    "EXAMPLES_STATEMENTS",
    "ExamplesCost",
    "ExamplesGrading",
    "ExamplesRefused",
    "ExamplesUpload",
    "MarkedExample",
    "SKIPPED_ANSWER",
    "add_examples",
    "answer_questions",
    "calibration_cohort_id",
    "compare",
    "examples_cost",
    "examples_of",
    "grade_examples",
    "grading_run",
    "refuse_remote_real_work",
    "skip_examples",
]
