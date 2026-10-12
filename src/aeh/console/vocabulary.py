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
    # `FR-CONSOLE-41` (#632): recover is one of the operations the CLI offers that must be
    # reachable from the console. The control delegates to M-PIPE's `recover` — the same door
    # `aeh recover` opens — rather than queueing a row: recovery reclaims leases and settles
    # grades immediately, and a queued reclaim is exactly the stall the operator is asking to
    # clear.
    "recover runs",
    # `FR-CONSOLE-42` (#632): the roster editor also loads late students into an existing
    # cohort, through M-ORCH's `add_to_roster` — the door `aeh cohort add-students` opens.
    # A separate action rather than a widened `create cohort`, because `create_cohort` refuses
    # an existing cohort (a replayed submission writes nothing, `FR-CONSOLE-02`); merging the
    # two verbs would trade that guarantee for a shorter list.
    "add students",
    # The operator-requirements delta's second console action (FR-UI-05): the SPA's package
    # screen must be able to publish the M-SETUP draft, and `CT-CONSOLE-30` admits a new API
    # mutation only as an enumerated control row — the same rule that made cohort creation a
    # sixteenth action.
    "publish package",
    # The console-redesign delta's write action (FR-CONF-34): the guided configuration edit,
    # through M-CONF's `update_profile_edits` — validated with the loader's own rules and
    # written atomically. `CT-CONSOLE-02`'s enumeration must include it from the moment it
    # exists, so it enters this tuple with its effect, not after it.
    "update configuration",
    # The console-redesign delta's class vocabulary (`FR-CONSOLE-53`, #761, ADR-48): a class
    # is a cohort ledger in a roster-only state, created from a typed or pasted student list.
    # A separate enumerated row beside `create cohort` rather than a widened one, because the
    # two names are the console's vocabulary distinction (R0's map) over one storage concept,
    # and the SPA screens each by its own flow.
    "create class",
    # `FR-CONSOLE-54` (#761, ADR-48): copies a class ledger's roster into a new grading
    # cohort, consent state carried; the class stays intact and may seed many cohorts.
    "create cohort from class",
    # `FR-CONSOLE-63` (#761, §3.2.3): the roster file import — the one import path cohorts
    # and classes have. Targets the class state; the preview before its commit is the
    # `roster preview` read below, not a second write path.
    "import roster file",
    # The console-redesign delta's authoring actions (#760): §3.2.2's five rows. The four
    # authoring verbs drive `AuthoringService` through its console seam (`FR-AUTHOR-29/30`)
    # — a draft as a staged job, a review and an edit synchronous over the draft file, an
    # approval through M-PKG's own build door — and `cancel job` reaches every job the
    # registry holds (`ADR-47`), delegating for a run to the `pause/resume` row. They enter
    # this tuple with their effects, per `CT-CONSOLE-02`'s enumeration rule.
    "draft package from documents",  # FR-CONSOLE-61
    # The editor's from-scratch entry (`FR-UI-13`, #764): a package started without
    # documents opens the same editor over an empty draft, so the editor's one write
    # surface is the one the documents flow uses. The skeleton is deterministic — no model
    # call, no job — so this is a synchronous action beside the review and edit rows, not
    # a second staged job.
    "draft package from scratch",    # FR-UI-13
    "answer authoring review",       # FR-CONSOLE-55
    "edit draft package",            # FR-CONSOLE-56
    "approve draft package",         # FR-CONSOLE-62
    "cancel job",                    # FR-CONSOLE-57
)


#: The three actions that write before the §6.2 lock; everything else is post-lock.
PRE_LOCK_ACTIONS: frozenset[str] = frozenset(
    {
        "approve question inventory",
        "supply answer keys",
        "accept or correct rubric read-back",
    }
)


#: The run-start screen's read (FR-CONSOLE-43, #631): the profile banner and the cost
#: estimate behind the one confirmation. The run's profile is named per request
#: (`profile`), because a console process cannot run under `cloud-hosted` itself
#: (CT-CONSOLE-05).
RUN_START_PREVIEW_READ = "run start preview"

#: The results views' reads (FR-CONSOLE-44, #631): the class rollup, the per-student
#: records, and the school-facing export's bytes — each through the door the `aeh
#: results` subcommands call, so the two surfaces are one implementation.
RESULTS_CLASS_READ = "results class"
RESULTS_STUDENT_READ = "results student"
RESULTS_EXPORT_READ = "results export"

#: The CLI/console parity inventory's read (`FR-CONSOLE-41`, `NFR-CONSOLE-09`, #632): the
#: generated census the console's debugging-only help section renders.
CLI_HELP_READ = "CLI help"


#: The lifecycle screens' reads (FR-UI-03, #635): one JSON document per SPA screen, each
#: through the door the server-rendered console or the CLI calls for the same view. They are
#: reads, not controls — a screen render writes nothing (`TC-UI-C02`'s reload digest), so
#: the API adds no write path by carrying them.
PACKAGE_SETUP_READ = "package setup"
CLASS_ROSTER_READ = "class roster"
PAPERS_READ = "papers"
RUN_START_STATE_READ = "run start state"
MONITOR_READ = "monitor"
REVIEW_QUEUE_READ = "review queue"
BLIND_SEATS_READ = "blind seats"
RESULTS_SCREEN_READ = "results screen"
STUDENT_DETAIL_READ = "student detail"
SYSTEM_STATUS_READ = "system status"


#: The redesign SPA's read surface (FR-CONSOLE-47…52, FR-CONSOLE-60, #755): the secondary
#: pages' documents and the context header's switcher feed. Reads, not controls — each is
#: a pure store/service projection that writes nothing (`ADR-45`/`ADR-47`/`ADR-48`), so the
#: API adds no write path by carrying them. The one exception in shape is the authoring
#: preview, a POST whose body carries the uploaded documents (document content can never
#: travel in a URL or a query string, `CT-CONSOLE-34`); it writes nothing, and the census
#: admits it by its own named-exception mechanism, citing `FR-CONSOLE-50`.
CONTEXT_READ = "context"
IMPACT_READ = "impact"
JOBS_READ = "jobs"
JOB_READ = "job"
ISSUES_READ = "issues"
LOGS_READ = "logs"
PARKED_READ = "parked"
CONFIG_READ = "config"
AUTHORING_PREVIEW_READ = "authoring preview"
AUTHORING_DRAFT_READ = "authoring draft"
#: The roster file import's preview (`FR-CONSOLE-63`, #761): a POST read whose body carries
#: the uploaded roster file's text — file content can never travel in a URL or a query
#: string (`CT-CONSOLE-34`). It parses the rows and lists the malformed ones, and writes
#: nothing anywhere; the commit is the enumerated `import roster file` action above.
ROSTER_PREVIEW_READ = "roster preview"


#: The export reads (FR-CONSOLE-58, FR-CONSOLE-59, #762): the run's results workbook and
#: the package's readable export. Reads beside the existing results export
#: (`FR-CONSOLE-44`), not control rows — §3.2.2 lists them among the new actions, and
#: their behaviour column says what they are: *synchronous, returns the file like the
#: existing exports*. The existing exports are file-returning GET reads; bytes cannot
#: ride the control-outcome JSON, the exports write nothing the control surface owns,
#: and the write-surface enumeration (`FR-CONSOLE-32`) stays exactly the actions that
#: write store rows.
WORKBOOK_EXPORT_READ = "results workbook"
READABLE_EXPORT_READ = "readable package export"


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
    # FR-CONSOLE-42 (#632): the same roster rows, appended to an existing cohort's ledger
    # through M-ORCH's `add_to_roster` (the CLI's own door).
    "add students": (
        "roster.cohort_id",
        "roster.student_ref",
        "roster.full_name",
    ),
    # FR-CONSOLE-41 (#632): recovery delegates to M-PIPE's `recover`, which resumes open runs
    # (run.status), requeues expired leases (the work_unit lease columns) and settles the
    # grades whose review window lapsed (submission_grade.finalized_at).
    "recover runs": (
        "run.status",
        "work_unit.status",
        "work_unit.lease_owner",
        "work_unit.lease_expires_ticks",
        "work_unit.lease_expires_at",
        "submission_grade.finalized_at",
    ),
    # FR-UI-05: the SPA's package screen publishes the M-SETUP draft through `SetupService.
    # publish` — M-PKG's one-transaction lock flip on the version row (FR-PKG-01): `locked`
    # set and the approver recorded. The dotted names are the tables the flip touches, which
    # is what the all-tier digest sees when the confirmation writes.
    "publish package": (
        "package_version.locked",
        "package_version.published_by",
    ),
    # FR-CONF-34: the guided edit writes the configuration file through M-CONF's
    # `update_profile_edits` — no store row anywhere. The empty tuple is the declaration of
    # that: an action whose effect lands outside the store is still enumerated (so the census
    # and the dynamic sweep see it), it just admits no row.
    "update configuration": (),
    # `FR-CONSOLE-53`/`FR-CONSOLE-54`/`FR-CONSOLE-63` (#761, ADR-48): all three write the
    # same Tier C cohort and roster rows the roster editor's `create cohort` writes — one
    # storage concept, two states; no field a scoring prompt reads (NFR-PROV-04).
    "create class": (
        "cohort.cohort_id",
        "cohort.consent_class",
        "cohort.created_at",
        "roster.cohort_id",
        "roster.student_ref",
        "roster.full_name",
    ),
    "create cohort from class": (
        "cohort.cohort_id",
        "cohort.consent_class",
        "cohort.created_at",
        "roster.cohort_id",
        "roster.student_ref",
        "roster.full_name",
    ),
    "import roster file": (
        "cohort.cohort_id",
        "cohort.consent_class",
        "cohort.created_at",
        "roster.cohort_id",
        "roster.student_ref",
        "roster.full_name",
    ),
    # The authoring actions (#760): three write nothing the store owns — a draft's state is
    # the draft files (`ADR-45`) and a review/edit rewrite them through `aeh.author`; the
    # empty tuples declare that, exactly as `update configuration`'s does. `approve draft
    # package` builds through M-PKG's own door (`build_package`), whose flip touches the
    # same two version fields `publish package` names. `cancel job` pauses a run through
    # the one `run.status` row the run monitor writes; an authoring job's cancellation is
    # cooperative and touches no row.
    "draft package from documents": (),
    "draft package from scratch": (),
    "answer authoring review": (),
    "edit draft package": (),
    "approve draft package": (
        "package_version.locked",
        "package_version.published_by",
    ),
    "cancel job": ("run.status",),
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
