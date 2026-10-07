"""The control actions and their write fields, the states, and the console's fixed wording."""

from __future__ import annotations

from typing import Any


#: The control actions, verbatim: HLD §11.8's fifteen, then the operator-requirements delta's
#: cohort creation (`FR-CONSOLE-42`). The runtime surface is **exactly** this set
#: (`FR-CONSOLE-32`); an extra entry is the undeclared write path the clause exists to expose.
#: `CT-CONSOLE-30` admits a new API mutation only as an enumerated control row, which is why the
#: roster editor's write is a sixteenth action rather than a route of its own.
CONTROL_SURFACE_ACTIONS: tuple[str, ...] = (
    "approve question inventory",
    "supply answer keys",
    "accept or correct rubric read-back",
    "set review window",
    "start run",
    "pause/resume",
    "resolve quarantine item",
    "review action",
    "blind-sample submission",
    "correct an answer key after a run",
    "finalize batch",
    "amend a finalized grade",
    "approve exemplar paraphrases at export",
    "export/import package",
    "purge cohort",
    "create cohort",
)


#: The three actions that write before the §6.2 lock; everything else is post-lock.
PRE_LOCK_ACTIONS: frozenset[str] = frozenset(
    {
        "approve question inventory",
        "supply answer keys",
        "accept or correct rubric read-back",
    }
)


#: The per-action field contract (§11.8's Effect column): the store fields each action may
#: write, as dotted `table.field` names. `perform` writes no field outside this map, which is
#: what makes the dynamic sweep decisive.
CONSOLE_WRITE_FIELDS: dict[str, tuple[str, ...]] = {
    "approve question inventory": (
        "question.question_id",
        "question.prompt_text",
        "question.order",
    ),
    "supply answer keys": ("criterion.answer_key",),
    "accept or correct rubric read-back": (
        "criterion.text",
        "criterion.decomposable",
        "criterion_band.band",
        "criterion_band.descriptor",
        "grade_policy.rule",
        "grade_boundary.cut",
    ),
    "set review window": ("grade_policy.review_window_hours",),
    "start run": ("run.run_id", "run.status"),
    "pause/resume": ("run.status",),
    "resolve quarantine item": (
        "submission.ingest_status",
        "submission.quarantined",
    ),
    "review action": (
        "review_queue.action",
        "review_queue.new_band",
        "review_queue.acted_at",
        "label.label_type",
        "label.band",
    ),
    "blind-sample submission": ("label.label_type", "label.band"),
    "correct an answer key after a run": ("criterion.answer_key",),
    "finalize batch": ("submission_grade.finalized_at", "audit_record.actor"),
    "amend a finalized grade": (
        "submission_grade.revision",
        "submission_grade.bands",
        "audit_record.actor",
    ),
    "approve exemplar paraphrases at export": (
        "exemplar.provenance",
        "package.contains_real_student_text",
    ),
    "export/import package": ("package_file.path",),
    "purge cohort": ("cohort.purged_at",),
    # FR-CONSOLE-42: the roster editor, through M-ORCH's `create_cohort` (the CLI's own door).
    "create cohort": (
        "cohort.cohort_id",
        "cohort.consent_class",
        "cohort.created_at",
        "roster.cohort_id",
        "roster.student_ref",
        "roster.full_name",
    ),
}


#: The quarantine vocabulary, as the schema spells it (`FR-INGEST-30`). The park is the
#: FLAG M-INGEST writes — `submission.quarantined` (0/1, ingest migration 7) — and
#: `ingest_status` is the diagnosis beside it, whose CHECK domain is exactly
#: `('ok', 'low_confidence_ocr', 'unreadable', 'incomplete', 'unmatched_assessment')`.
#: These three are the parked diagnoses: `unreadable` and `unmatched_assessment` halt
#: scoring outright, `incomplete` is the close-as-unresolvable terminal state (S8's
#: close writes it and clears the flag). Deliberately absent: `low_confidence_ocr` is
#: flagged-but-available (`FR-INGEST-29` — admitted to scoring like `ok`, never
#: quarantined), and `unresolved_selection`/`triage` are det.py criterion-level states,
#: not submission statuses — a vocabulary this module once guessed and the store's CHECK
#: constraint refused. The review queue's reads never reach any of these (`CT-CONSOLE-12`).
QUARANTINE_STATES: tuple[str, ...] = (
    "unreadable",
    "incomplete",
    "unmatched_assessment",
)


#: The five optional setup cards (§6.3), each with its own skip rate in the telemetry.
OPTIONAL_SETUP_STEPS: tuple[str, ...] = (
    "Approve how the rubric was understood",
    "Confirm decomposability classifications",
    "Declare the grade policy and boundaries",
    "Answer ambiguity-elicitation questions",
    "Mark 10 to 15 calibration papers",
)


#: S1's rule (`FR-CONSOLE-26`) and the rollup's: the exact sentences an honest card renders.
NO_VALIDATION_FOR_POPULATION = "no validation data for this population"


NO_NEW_VALIDATION_EVIDENCE = "no new validation evidence for this administration"


#: The calibration surface arrives in a later version (`FR-CONSOLE-25`): rendered
#: present-and-unavailable, naming the version, never silently absent.
CALIBRATION_ARRIVES_IN = "version 2 (Phase 4 calibration)"


#: The ingest gates and their columns in the cohort tier (the §9 table shape `M-INGEST`
#: writes and `M-CONSOLE`'s S6 ladder reads). Values outside both lists mean not reached.
_GATE_COLUMNS: dict[str, str] = {
    "v0": "v0_integrity",
    "v1": "v1_pages",
    "v2": "v2_structure",
    "v3": "v3_identity",
    "v4": "v4_match",
}


_GATE_PASS_VALUES: dict[str, tuple[str, ...]] = {
    "v0": ("pass",),
    "v1": ("pass",),
    "v2": ("pass",),
    "v3": ("pass",),
    "v4": ("match",),
}


_GATE_FAIL_VALUES: dict[str, tuple[str, ...]] = {
    "v0": ("fail",),
    "v1": ("fail",),
    "v2": ("fail",),
    "v3": ("unmatched", "ambiguous"),
    "v4": ("uncertain", "mismatch"),
}


_GATE_NOT_REACHED = "not_reached"


#: What each score state says to the teacher. The four states are the closed set `CT-AGG-07`
#: pins; a merged presentation of the breaker-refused and the ordinary provisional row is the
#: quiet degradation the clause exists to catch.
_STATE_PRESENTATION: dict[str, str] = {
    "final": "final",
    "provisional_unreviewed": "provisional and awaiting teacher review",
    "ungradeable_by_panel": (
        "the panel refused to grade this criterion — it is recorded as ungradeable, "
        "not as awaiting review"
    ),
    "unresolved_selection": "the selection could not be read; it is parked for triage",
}


# --- the band interface (HLD §11.6 invariant 16, `FR-CONSOLE-20`) ---------------------------------------
#
# "Wherever a band is displayed it is displayed as an editable band control. There is no view
# that shows a grade and cannot change it." The control is one shape used by every screen that
# displays a grade — a select over the rubric's bands, never a typed number (`FR-CONSOLE-07`)
# and never a disabled placeholder, which is the shape a read-only view actually takes.

#: The bands the correction interface offers, as the rubric's four-band scale spells them.
REVIEW_BANDS: tuple[str, ...] = ("met", "partially met", "not met")


#: The standing agreement figure the rollup renders on the audit double and the
#: storeless default build (`data_dir is None`, the same discriminator `_write_rows`
#: uses): HLD §11.5's S12 mock — κ = 0.63, n = 15 — scoped by the block that renders
#: it. A build that states `blind_labels_collected = 0` renders the absence sentence
#: instead (`FR-CONSOLE-24`); a real store renders the absence sentence too, until the
#: console reads `M-STATS`'s validation record — never this placeholder, which the
#: module cannot verify against any ledger.
STANDING_AGREEMENT_FIGURE: dict[str, Any] = {"kappa": 0.63, "n": 15}
