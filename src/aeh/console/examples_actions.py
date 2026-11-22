"""The teacher's marked examples as the console serves them (FR-CONSOLE-86/87, #886).

Five actions — `examples upload`, `examples mark`, `examples grade`, `examples answer`,
`examples skip` — and three reads: `GET /api/v1/calibration/examples` (the step's state and
what checking the examples cost, NFR-CALIB-05), `GET /api/v1/calibration/differences` and
`GET /api/v1/calibration/questions`.

M-CALIB owns the work (`aeh.calib.examples`): the calibration cohort, grading under R0 through
M-PIPE, and discovery, triage and the questions over the stored rows. M-SETUP owns the form's
rules and the clean-copy check (FR-SETUP-20/21). This module composes them, runs the two long
steps (reading the uploads, grading) as jobs on worker threads that open their own store
(FR-CONSOLE-04), and words every outcome for the teacher. `aeh.calib` is imported inside each
function, never at module scope: the console runs whole with M-CALIB absent (CT-CALIB-01), and
then these actions refuse and `touchpoint_surface` reports the step unavailable.

**No read or action here carries a count of matching marks, a rate or an agreement figure**
(CT-CALIB-03, D5): with a dozen papers the teacher chose, a percentage would say nothing.
"""

from __future__ import annotations

import base64
import binascii
import threading
import uuid
from typing import Any, Mapping

from .html import _now
from .records import ControlOutcome
from .spa_reads import _strip_exception_name

#: The five actions, in the order the step uses them.
EXAMPLES_ACTIONS: tuple[str, ...] = (
    "examples upload",
    "examples mark",
    "examples grade",
    "examples answer",
    "examples skip",
)

#: The job kinds the two long steps register (`ADR-47`).
EXAMPLES_UPLOAD_JOB_KIND = "examples_upload"
EXAMPLES_GRADE_JOB_KIND = "examples_grade"

#: FR-UI-45's fixed sentence, shown with the differences and the questions.
NO_PERCENTAGE_SENTENCE = (
    "With a dozen papers you chose, a percentage would not tell you how accurate the marking "
    "is. That's what the blind sample is for."
)

#: The three causes a difference is grouped by (FR-UI-45), each with what happens next.
CAUSES: dict[str, tuple[str, str]] = {
    "rubric_ambiguity": ("The rubric may be unclear",
                         "A question below asks how you meant it."),
    "model_failure": ("The system misread a clear rule",
                      "We've reported this; your rubric is not changed."),
    "teacher_inconsistency": ("Two similar answers were marked differently",
                              "Both are shown side by side; nothing is changed."),
}

#: The versions whose examples are being checked now, so a second Check is refused.
_GRADING: set[str] = set()
_GRADING_GUARD = threading.Lock()

#: The step's format line (FR-UI-44).
UPLOAD_FORMAT = "Unmarked PDF copies, one per student, 10 to 15 recommended (at most 25)."


def _calib() -> Any:
    """`aeh.calib.examples`, or None when M-CALIB is absent (CT-CALIB-01)."""
    try:
        from aeh.calib import examples
    except ImportError:
        return None
    return examples


def examples_available() -> bool:
    """Whether M-CALIB is present, so the examples step can be served."""
    return _calib() is not None


def _refused(detail: str, next_action: str | None = None) -> ControlOutcome:
    return ControlOutcome(rows_written=(), refused=True, dispatched=False, detail=detail,
                          next_action=next_action)


def _version(app: Any, params: Mapping[str, Any]) -> str | None:
    """The package version the step is about, when it is stored (an unknown id's open would
    create its file)."""
    version = str(params.get("package_version") or params.get("package_version_id") or "")
    if not version or app._package_of(version) == "":
        return None
    return version


def _config(app: Any) -> dict[str, Any]:
    from .run_start import compose_run_start_config

    return compose_run_start_config(app, {})


#: What the teacher reads when a refusal is not one worded for them (FR-UI-23: no ids,
#: references, paths or settings names reach teacher text).
_GENERIC_REFUSAL = "This could not be done. Nothing was changed; please try again."


def _teacher_words(error: BaseException) -> str:
    """A refusal as the teacher reads it: M-CALIB's and M-SETUP's own refusals are written for
    the teacher and pass through; anything else becomes a plain sentence."""
    calib = _calib()
    worded: tuple[type, ...] = ()
    if calib is not None:
        worded += (calib.ExamplesRefused,)
    try:
        from aeh.setup import MarkedExampleRefused

        worded += (MarkedExampleRefused,)
    except ImportError:  # pragma: no cover - M-SETUP always ships with the console
        pass
    if not worded or not isinstance(error, worded):
        return _GENERIC_REFUSAL
    text = _strip_exception_name(error) or _GENERIC_REFUSAL
    return text if text.endswith((".", "!", "?")) else text + "."


# --- the jobs -----------------------------------------------------------------------------


def _start_job(app: Any, *, kind: str, version: str, label: str, work: Any) -> str:
    """Register a job and run `work(worker_store)` on a worker thread with its own store; the
    job's `current` line is the sentence `work` returns, or the refusal it raised."""
    from aeh.pipeline.runtime import _open_store

    job_id = f"{kind}-{uuid.uuid4().hex[:12]}"
    registry = app._jobs
    registry.register(job_id=job_id, kind=kind, total=1, current=label, started_at=_now())
    data_dir = str(app._store.data_dir)

    def run() -> None:
        store = None
        try:
            registry.update(job_id, state="running")
            store = _open_store(data_dir)
            sentence = work(store)
            registry.update(job_id, done=1, current=sentence)
            registry.finish(job_id, state="succeeded", finished_at=_now())
        except Exception as error:  # noqa: BLE001 — the refusal is the job's outcome
            registry.finish(job_id, state="failed", finished_at=_now(),
                            error_detail=_teacher_words(error),
                            error_next_action="check the examples, then try again.")
        finally:
            if store is not None:
                store.close()

    thread = threading.Thread(target=run, name=f"aeh-{job_id}", daemon=True)
    thread.start()
    threads = getattr(app, "_examples_threads", None)
    if threads is None:
        threads = {}
        try:
            app._examples_threads = threads
        except AttributeError:  # pragma: no cover - an app that refuses attributes
            pass
    threads[job_id] = thread
    return job_id


def _decoded(entry: Any) -> tuple[str, bytes] | None:
    if not isinstance(entry, Mapping):
        return None
    name = str(entry.get("name") or "").strip()
    raw = entry.get("content_base64")
    if not name or not isinstance(raw, str):
        return None
    try:
        return name, base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None


# --- the five actions ---------------------------------------------------------------------


def upload_effect(app: Any, params: Mapping[str, Any]) -> ControlOutcome:
    """`examples upload` (package version, documents, the test paper once, the consent class
    once): checked now, read as a job. Each file is read into the version's calibration cohort,
    checked for marks (FR-SETUP-21) and kept only when clean and readable."""
    calib = _calib()
    if calib is None:
        return _refused("Checking marked examples is not available in this installation.")
    version = _version(app, params)
    if version is None:
        return _refused("Choose the test these examples answer, then upload them again.",
                        "choose a test from the list.")
    documents = params.get("documents")
    files = [_decoded(entry) for entry in documents] if isinstance(documents, list) else []
    if not files or any(entry is None for entry in files):
        return _refused(
            "Choose the examples to upload. " + UPLOAD_FORMAT + " Nothing was stored.",
            "choose the PDF files again.")
    test_paper = _decoded(params.get("test_paper")) if params.get("test_paper") else None
    consent = str(params.get("consent") or params.get("consent_class") or "") or None
    stored = _stored_consent(app._store, calib.calibration_cohort_id(version))
    if stored is None and consent is None:
        return _refused(
            "Say whether these are made-up practice papers or your students' real work, then "
            "upload them again. Nothing was stored.",
            "choose practice papers or real work.")
    try:
        config = _config(app)
        calib.refuse_remote_real_work(config, stored or str(consent))
    except Exception as error:  # noqa: BLE001 — refused before anything is read
        return _refused(_teacher_words(error))
    from aeh.setup import MARKED_EXAMPLES_MAX, marked_pages

    def work(store: Any) -> str:
        outcome = calib.add_examples(
            store, version, [f for f in files if f is not None], config=config,
            consent_class=consent, test_paper=test_paper, clean_copy_check=marked_pages,
            limit=MARKED_EXAMPLES_MAX, actor=str(params.get("actor") or "teacher"))
        sentence = f"{len(outcome.added)} example(s) added; you now have {len(outcome.examples)}."
        for name, why in outcome.refused:
            sentence += f" {name} was not used: {why}"
        return sentence

    job_id = _start_job(app, kind=EXAMPLES_UPLOAD_JOB_KIND, version=version,
                        label=f"Reading {len(files)} example(s)", work=work)
    return ControlOutcome(rows_written=(), refused=False, dispatched=True, job_id=job_id,
                          detail=f"Reading {len(files)} example(s). Each is checked for marks "
                                 "before it is used.")


def _stored_consent(store: Any, cohort_id: str) -> str | None:
    from aeh.orch import cohort_summary

    try:
        summary = cohort_summary(store, cohort_id)
    except Exception:  # noqa: BLE001 — no cohort yet
        return None
    return summary.consent_class if summary is not None else None


def mark_effect(app: Any, params: Mapping[str, Any]) -> ControlOutcome:
    """`examples mark` (package version, document, {criterion: band}): the teacher's band for
    every part marked by hand on one example, checked by M-SETUP's form rules and stored
    through M-PKG (FR-SETUP-20). Re-marking replaces the bands."""
    calib = _calib()
    if calib is None:
        return _refused("Checking marked examples is not available in this installation.")
    version = _version(app, params)
    if version is None:
        return _refused("Choose the test this example answers.", "choose a test from the list.")
    document_id = str(params.get("document_id") or "")
    bands = params.get("bands")
    held = {example.document_id: example for example in calib.examples_of(app._store, version)}
    if document_id not in held:
        return _refused("That example is not one of this test's examples. Upload it first.")
    if not isinstance(bands, Mapping) or not bands:
        return _refused("Enter a mark for each part you mark by hand, then save the form.")
    if calib.grading_run(app._store, version) is not None:
        return _refused("Your examples have already been checked, so their marks are kept "
                        "as they were.")
    from aeh.setup import check_example_bands

    catalog = calib._catalog(app._store, version)
    label = held[document_id].file_name or f"example {held[document_id].number}"
    clean = {str(k): str(v) for k, v in bands.items()}
    try:
        check_example_bands(catalog, version, clean, label)
        catalog.record_example_marks(version, document_id=document_id, bands=clean,
                                     marked_at=_now())
    except Exception as error:  # noqa: BLE001 — the form's own refusal
        return _refused(_teacher_words(error))
    marked = {str(row["document_id"]) for row in catalog.example_marks(version)}
    left = sum(1 for doc in held if doc not in marked)
    return ControlOutcome(rows_written=(), refused=False, dispatched=True,
                          detail=f"Saved your marks for {label}. "
                                 + (f"{left} example(s) still need marks."
                                    if left else "Every example is marked."))


def grade_effect(app: Any, params: Mapping[str, Any]) -> ControlOutcome:
    """`examples grade` (package version): grade the examples under the version they were
    marked under, as a job (FR-CALIB-17). The run counts against the run cost ceiling; on an
    online model only made-up practice papers are sent (R31)."""
    calib = _calib()
    if calib is None:
        return _refused("Checking marked examples is not available in this installation.")
    version = _version(app, params)
    if version is None:
        return _refused("Choose the test whose examples to check.",
                        "choose a test from the list.")
    store = app._store
    if not calib.examples_of(store, version):
        return _refused("Upload at least one marked example before checking them.")
    if calib.grading_run(store, version) is not None:
        return _refused("Your examples have already been checked.")
    try:
        config = _config(app)
        calib.refuse_remote_real_work(
            config, _stored_consent(store, calib.calibration_cohort_id(version)) or "real")
    except Exception as error:  # noqa: BLE001 — refused before any call
        return _refused(_teacher_words(error))

    # One check per test at a time: a double click must not start two workers on one run.
    with _GRADING_GUARD:
        if version in _GRADING:
            return _refused("Your examples are already being checked.")
        _GRADING.add(version)

    def work(worker_store: Any) -> str:
        try:
            grading = calib.grade_examples(worker_store, version, config=config)
        finally:
            with _GRADING_GUARD:
                _GRADING.discard(version)
        if grading.result.status != "complete":
            raise calib.ExamplesRefused(
                "The check of your examples stopped before it finished.")
        return "Your examples were checked. See where the system read your rubric differently."

    job_id = _start_job(app, kind=EXAMPLES_GRADE_JOB_KIND, version=version,
                        label="Checking your examples", work=work)
    return ControlOutcome(rows_written=(), refused=False, dispatched=True, job_id=job_id,
                          detail="Checking your examples with your rubric as written. This "
                                 "counts toward the run cost limit.")


def answer_effect(app: Any, params: Mapping[str, Any]) -> ControlOutcome:
    """`examples answer` (package version, {question: answer}, whether the rubric was given to
    students in advance): the answers applied through M-PKG's lock as a clarified version that
    is checked on the next class before it is used (FR-CALIB-16/18)."""
    calib = _calib()
    if calib is None:
        return _refused("Checking marked examples is not available in this installation.")
    version = _version(app, params)
    answers = params.get("answers")
    if version is None or not isinstance(answers, Mapping) or not answers:
        return _refused("Answer the questions shown, then send your answers.")
    in_advance = str(params.get("rubric_published_in_advance") or "").lower() in (
        "1", "true", "yes", "on")
    try:
        outcome = calib.answer_questions(app._store, version,
                                         {str(k): str(v) for k, v in answers.items()},
                                         rubric_published_in_advance=in_advance)
    except Exception as error:  # noqa: BLE001 — M-CALIB's refusal
        return _refused(_teacher_words(error))
    if in_advance:
        detail = ("Your students saw this rubric before the test, so it is not changed now: "
                  "this class is marked with it as written. Your answers are kept, and your "
                  "clarifications apply to the next class.")
    elif outcome.revised_version:
        detail = ("Thank you. Your answers made a clarified version of the rubric. It is "
                  "checked on your next class before it is used; this test is still marked "
                  "with your rubric as written.")
    else:
        detail = "Thank you. You kept the rubric as it is, so nothing changes."
    return ControlOutcome(rows_written=(), refused=False, dispatched=True, detail=detail)


def skip_effect(app: Any, params: Mapping[str, Any]) -> ControlOutcome:
    """`examples skip` (package version): at any point. The test is marked with the rubric as
    written, and the parts a question was about are treated with more caution (FR-CALIB-13).
    On a test still being set up, the step's default is recorded too (FR-SETUP-14)."""
    calib = _calib()
    version = _version(app, params)
    if version is None:
        return _refused("Choose the test whose examples step to skip.")
    if calib is None:
        return ControlOutcome(rows_written=(), refused=False, dispatched=True,
                              detail="Skipped. Your test is marked with your rubric as written.")
    try:
        outcome = calib.skip_examples(app._store, version)
    except Exception as error:  # noqa: BLE001 — M-CALIB's refusal
        return _refused(_teacher_words(error))
    detail = "Skipped. Your test is marked with your rubric as written."
    if outcome.lower_confidence_criteria:
        detail += (f" The {len(outcome.lower_confidence_criteria)} part(s) a question was "
                   "about are recorded as possibly unclear in your rubric.")
    return ControlOutcome(rows_written=(), refused=False, dispatched=True, detail=detail)


#: The actions, by name.
EXAMPLES_ACTION_EFFECTS = {
    "examples upload": upload_effect,
    "examples mark": mark_effect,
    "examples grade": grade_effect,
    "examples answer": answer_effect,
    "examples skip": skip_effect,
}


def apply_examples_action(app: Any, action: str, params: Mapping[str, Any]) -> ControlOutcome:
    """Dispatch one examples action. Needs a data folder: the audit double has none."""
    if getattr(getattr(app, "_store", None), "data_dir", None) is None:
        return ControlOutcome(rows_written=(), refused=False, dispatched=False,
                              detail="no data folder is attached; nothing was done")
    return EXAMPLES_ACTION_EFFECTS[action](app, params)


# --- the three reads ------------------------------------------------------------------------


def _read_version(app: Any, query: Mapping[str, Any]) -> tuple[Any, str]:
    calib = _calib()
    if calib is None:
        raise ValueError("checking marked examples is not available in this installation")
    version = _version(app, query)
    if version is None:
        raise ValueError("choose a test: the read names no stored test")
    return calib, version


def _limit() -> int:
    from aeh.setup import MARKED_EXAMPLES_MAX

    return int(MARKED_EXAMPLES_MAX)


def _money(value: Any) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def examples_read(console: Any, app: Any, query: Mapping[str, Any]) -> dict[str, Any]:
    """`GET /api/v1/calibration/examples`: the step's state — each example and whether it is
    marked, the grading's status, and what checking the examples cost against the run cost
    limit (NFR-CALIB-05)."""
    calib, version = _read_version(app, query)
    store = app._store
    held = calib.examples_of(store, version)
    marked = {str(row["document_id"])
              for row in calib._catalog(store, version).example_marks(version)} if held else set()
    run = calib.grading_run(store, version)
    comparison = calib.compare(store, version) if run and run[1] == "complete" else None
    cost = calib.examples_cost(store, version)
    if run is None:
        status = "marked" if held and all(e.document_id in marked for e in held) else (
            "uploaded" if held else "not_started")
    elif run[1] != "complete":
        status = "checking" if run[1] in ("pending", "running") else "stopped"
    elif comparison is not None and comparison.answered:
        status = "answered"
    elif comparison is not None and comparison.skipped:
        status = "skipped"
    else:
        status = "checked"
    return {
        "package_version": version,
        "status": status,
        "format": UPLOAD_FORMAT,
        "limit": _limit(),
        "recommended": [10, 15],
        "examples": [
            {"document_id": e.document_id, "file_name": e.file_name, "number": e.number,
             "marked": e.document_id in marked}
            for e in held
        ],
        "cost": {
            "spent": _money(cost.spent),
            "estimate": _money(cost.estimated),
            "ceiling": _money(cost.ceiling),
            "currency": cost.currency,
            "text": _cost_text(cost),
        },
        # FR-CALIB-18: where the clarified rubric stands, in the teacher's words.
        "clarified_rubric": _clarified_rubric(store, version),
    }


#: What the teacher reads while the clarified rubric waits for, or is on, its first class.
_PENDING_TEXT = ("Your clarified rubric is checked on your next class before it is used; "
                 "that class is graded with your original rubric.")
_CHECKING_TEXT = ("Your clarified rubric is being checked on a class; that class is graded "
                  "with your original rubric.")


def _clarified_rubric(store: Any, version: str) -> dict[str, Any] | None:
    """The newest clarified version of `version`: its state and the sentence shown. None when
    the teacher's answers made none."""
    try:
        from aeh.calib import first_class
    except ImportError:
        return None
    status = first_class.revision_status(store, version)
    if status is None:
        return None
    if status["state"] == "pending":
        text = _CHECKING_TEXT if status["checking_on_a_class"] else _PENDING_TEXT
    else:
        text = status["reason"]
    return {"state": status["state"], "text": text}


def _cost_text(cost: Any) -> str:
    if cost.spent is None and cost.estimated is None:
        return ("Checking your examples costs about as much as marking a class of the same "
                "size, and counts toward the run cost limit.")
    figure = cost.spent if cost.spent is not None else cost.estimated
    currency = f" {cost.currency}" if cost.currency else ""
    text = f"Checking your examples cost {_money(figure)}{currency}"
    if cost.ceiling is not None:
        text += f", within the run cost limit of {_money(cost.ceiling)}{currency}"
    return text + "."


def differences_read(console: Any, app: Any, query: Mapping[str, Any]) -> dict[str, Any]:
    """`GET /api/v1/calibration/differences` (FR-CONSOLE-87): per difference, the example, the
    part, the answer, the teacher's mark, the system's mark and its reason, grouped by cause.
    No count of matching marks, no rate (CT-CALIB-03)."""
    calib, version = _read_version(app, query)
    comparison = calib.compare(app._store, version)
    groups: dict[str, list[dict[str, Any]]] = {cause: [] for cause in CAUSES}
    for difference in comparison.differences:
        cause = difference.verdict.category
        item = {
            "example": difference.example.file_name or f"Example {difference.example.number}",
            "document_id": difference.example.document_id,
            "part": difference.question_id,
            "answer": difference.answer,
            "your_mark": difference.teacher_band,
            "system_mark": difference.system_band,
            "system_reason": difference.system_reason,
        }
        if difference.paired_with is not None:
            item["side_by_side_with"] = (difference.paired_with.file_name
                                         or f"Example {difference.paired_with.number}")
        groups.setdefault(cause, []).append(item)
    return {
        "package_version": version,
        "checked": comparison.run_status == "complete",
        "groups": [
            {"cause": cause, "heading": CAUSES[cause][0], "next": CAUSES[cause][1],
             "differences": items}
            for cause, items in groups.items() if items
        ],
        "sentence": NO_PERCENTAGE_SENTENCE,
    }


def questions_read(console: Any, app: Any, query: Mapping[str, Any]) -> dict[str, Any]:
    """`GET /api/v1/calibration/questions` (FR-CONSOLE-87): the questions, capped at
    `CALIB_MAX_QUESTIONS`, each with its options and two of the examples that raised it, and
    whether they were answered or skipped."""
    calib, version = _read_version(app, query)
    comparison = calib.compare(app._store, version)
    catalog = calib._catalog(app._store, version)
    rows = {str(r["criterion_id"]): dict(r) for r in catalog.criteria(version)}
    by_document = {e.document_id: e for e in comparison.examples}
    shown = {(d.example.document_id, d.criterion_id): d for d in comparison.differences}
    total = len(comparison.questions)
    questions = []
    for number, question in enumerate(comparison.questions, start=1):
        part = str(rows.get(question.criterion_id, {}).get("question_id") or "")
        bands = catalog.bands(question.criterion_id)
        level = next((b for b in bands if int(b["ordinal"]) == question.band_ordinal), None)
        examples = []
        for document_id in question.examples:
            if document_id is None or document_id not in by_document:
                continue
            difference = shown.get((document_id, question.criterion_id))
            examples.append({
                "example": by_document[document_id].file_name
                or f"Example {by_document[document_id].number}",
                "answer": difference.answer if difference else "",
                "your_mark": difference.teacher_band if difference else "",
                "system_mark": difference.system_band if difference else "",
            })
        level_name = str(level["band"]) if level else ""
        questions.append({
            "question_id": question.question_id,
            "heading": f"Question {number} of {total}",
            "part": part,
            "level": level_name,
            "descriptor": str(level["descriptor"] or "") if level else "",
            "text": (f"On {part or 'this part'}, you and the system read the level "
                     f"\"{level_name}\" differently in {question.submissions_affected} of your "
                     "examples. Should its description be broadened, narrowed, or kept as is? "
                     "You can also answer in your own words."),
            "options": list(question.options),
            "examples": examples,
        })
    return {
        "package_version": version,
        "status": ("answered" if comparison.answered else
                   "skipped" if comparison.skipped else
                   "open" if questions else "none"),
        "questions": questions,
        "sentence": NO_PERCENTAGE_SENTENCE,
    }
