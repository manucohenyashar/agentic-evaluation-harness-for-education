"""M-DET — the Deterministic Evaluator (detailed-design.md §3.11; issue #86).

Deterministic criteria are scored by exact comparison of the selection the
ingestion module extracted against the teacher-supplied answer key. No model
call, no panel, no rubric interpretation — and nothing to retry, because
nothing here can fail transiently (`CT-DET-10`). This is the only part of the
scoring path that is byte-reproducible across runs and backends, and it earns
that by being a pure function of (selection, key, policy) (`NFR-DET-02`): the
HLD §7.8 situation table (test-plan §5.11, `TC-DET-03`) is finite, and the
module-level `evaluate` below is enumerable against every cell of it.

The load-bearing distinction (R36/R55, `CT-DET-03`): an unreadable mark is a
scanning problem routed to the operator — never a wrong answer — while a
genuinely empty answer IS a zero. Collapsing that in either direction silently
grades students down for their scanner.

Scope (#86): the pure kernel, the score-row write, and the cohort pass with
`mcq_item_stats` / `mcq_item_summary` writes. #87 added, on top of it and
without restructuring it (`FR-DET-07` through `FR-DET-10`): the `item_stats`
read API, `rederive_for_key_change`, the audit-record columns, and the
statistical-separation filter of `NFR-DET-03`.

Design interpretations this implementation commits to (the design fixes the
behaviour; each of these names the column-level reading it implies, and each is
recorded for review):

- An unresolved selection is a WRITTEN `criterion_score` row (`FR-DET-03`
  names the row's state) whose `band` column carries the marker `'unresolved'`
  — the base column is NOT NULL and no criterion band may be borrowed for a
  row that was never scored — with `state = 'unresolved_selection'`,
  `routing = 'triage'`, and NULL points. `CT-DET-03`'s negative then holds
  literally: no criterion_score with a zero or an incorrect VALUE exists for
  an unresolved state, because that row carries no score at all.
- A multi-select criterion with no declared partial-credit policy raises
  `UndeclaredPartialCreditPolicy` — a package-integrity failure
  (`TC-DET-03` cell 11, `CT-DET-C05`), never a runtime default. The module
  does not infer a policy, ever (`FR-DET-05`). The refusal is the criterion's,
  not the cell's: any evaluation of a multi-select criterion whose package
  declares nothing raises, including a blank one — a criterion whose scoring
  rule does not exist must be fixed at setup, not scored around.
- The declared over-selection rule under `per_option` (test-plan §5.11 cell
  10's "must be stated"): each selected option the key does not contain
  cancels one earned credit, floored at zero —
  credit = max(0, |sel ∩ key| − |sel \\ key|) / |key|. The row's `points`
  carry the fraction, scaled against the correct band's points; the band is
  `'correct'` only on an exact match, so the criterion's declared two-band
  scale is never exceeded. (The band-fully-determines-points invariant is a
  judged-aggregation rule — R41, "never an average of judges" — and cannot
  hold under a policy the teacher declared without erasing the policy.)
- Selections are sequences of option ids (HLD §9.6 stores `selection` as a
  JSON list). The current ingest writes at most one option id per resolved
  region (`FR-INGEST-17`), so the store path wraps the single id in a 1-tuple;
  the kernel is list-valued, which is what makes cells 7–10 of the situation
  table enumerable now.
- Retraction discipline (R47, applied to what M-INGEST recorded): live regions
  are those with a NULL `retraction`. Exactly one live region is the answer;
  more than one is multiple marks — unresolved, never "the darkest one"
  (`CT-DET-C03`'s boundary). A question whose every region is struck through
  is a blank — an empty answer is an answer, a legitimate zero. A question
  with no region at all is absent — unresolved (cell 5). The head document for
  a submission is the newest one (`ORDER BY created_at, document_id`, last
  row): page replacements append newer documents.
- `FR-DET-06` is structural here, not enforced: this module's write set is
  `criterion_score` plus `mcq_item_stats` / `mcq_item_summary` and nothing
  else. It writes no `review_queue` row, no `verdict` row, no narrative, no
  package row (`CT-DET-09`), and its routing vocabulary admits only `'auto'`
  and `'triage'` — a deterministic criterion has no path into the teacher's
  review queue, whose admission is `M-REVIEW`/`M-AGG`'s query concern.
- Registration assumption: this module's runtime SQL reads M-INGEST's
  `document` / `document_region` columns and M-ORCH's `run` table in the
  cohort tier. Migrations register at import, so a process must import
  `aeh.ingest` and `aeh.orch` before opening a fresh data dir — shipped
  wiring (console, orchestrator, tests) does. Importing `aeh.det` alone
  applies only the store's cohort migrations and det's own, and the first
  cohort read would then fail on the missing ingest/orch columns.

Design interpretations #87 commits to (same discipline as the list above;
each is a column-level reading the design leaves to the implementer, recorded
for review):

- Audit records are written for SCORED rows only (band `correct` /
  `incorrect`). An unresolved row has no grade and NULL points, and the
  HLD §9.7 `audit_record.final_points` is NOT NULL — there is no honest value
  for a row that was never scored. Its audit is the `criterion_score` row's
  own `state`/`routing` pair, which names `unresolved_selection`/`triage` in
  the cohort tier.
- `audit_record.selection_read` holds the JSON list of the extracted option
  ids — `[]` for a blank answer, which was READ (as an empty answer) and is a
  legitimate zero, never a judged row. Every deterministic audit row carries a
  non-null `selection_read` and a non-null `answer_key_ref`; the null of these
  columns is how a JUDGED row (written by `M-AGG`/`M-GRADE`, never here) is
  recognized from the data.
- `answer_key_ref` is `"<package_version_id>:<json list of option ids>"` —
  the version AND the key bytes in one resolvable string (ADR-1: a correction
  is a new version, so the pair resolves to exactly the key that produced the
  grade; pkg's version lineage keeps the old version's key readable).
- `audit_record.evaluation_mode` and `label.evaluation_mode` are added with
  `DEFAULT 'judged'`: the migration must be additive over rows that already
  exist (orch's run-level audit row predates the column), and every row in the
  store before det wrote grades was a judged artifact. #59 owns reconciling
  the run-level row's mode with its own unit semantics; det's per-grade rows
  always write `'deterministic'` explicitly.
- The separation filter (`NFR-DET-03`, `FR-DET-09`) is defined in this module
  exactly once — `DETERMINISTIC_EXCLUSION` below, composed into
  `select_agreement_labels` as the canonical agreement-figure query. det owns
  the COLUMN (`CT-DET-06`); `M-STATS` owns the admissible-label conjunction's
  other half (`label_type = 'blind'`, `NFR-STATS-04`). A consumer that
  re-spells the exclusion predicate instead of importing the constant or the
  statement is the defect `TC-DET-09`'s structural assertion exists to catch.
- `label.evaluation_mode` is det's column but not det's row: `CT-DET-09`'s
  write set admits no `label` writes. Population is the duty of whichever
  module records a label over a deterministic result (`M-REVIEW`/`M-GRADE`).
- `rederive_for_key_change` re-derives scores and appends audit records and
  does NOT rewrite `mcq_item_stats`/`mcq_item_summary`: those tables are
  keyed by package version, and the corrected figures belong to the new
  version's own full pass. The report's changed counts tell the caller when
  the old version's stats no longer describe the cohort's rows.
- The audit append is per evaluation event and deliberately NOT deduplicated:
  the design's idempotency-under-redelivery constraint names
  `rederive_for_key_change` and the item-stats writes, not the audit trail —
  an append-only trail of grading events is the trail's point.
- `item_stats` resolves the cohort's single package version from its run rows
  and refuses a cohort whose runs name SEVERAL versions: the report would
  silently mix two instruments' figures, and refusing names the ambiguity
  instead (`aeh.det` makes no claim about which one a caller meant).
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aeh.pkg import PackageCatalog
from aeh.store import (
    STATEMENTS,
    Migration,
    Statement,
    Store,
    Tier,
    TIER_MIGRATIONS,
)

# --- vocabulary ------------------------------------------------------------------------------------

BAND_CORRECT = "correct"
BAND_INCORRECT = "incorrect"
#: Marker value written to `criterion_score.band` for a row that was never
#: scored (an unresolved selection). Not a criterion band; no criterion declares
#: it, and the three-way distinction forbids every other value here.
BAND_UNRESOLVED = "unresolved"

STATE_FINAL = "final"
STATE_UNRESOLVED_SELECTION = "unresolved_selection"
ROUTING_AUTO = "auto"
ROUTING_TRIAGE = "triage"

POLICY_ALL_OR_NOTHING = "all_or_nothing"
POLICY_PER_OPTION = "per_option"
PARTIAL_CREDIT_POLICIES = (POLICY_ALL_OR_NOTHING, POLICY_PER_OPTION)

CONTENT_STATES = ("present", "blank", "absent")
SELECTION_STATES = ("resolved", "ambiguous", "multiple_marks")

# Per-situation reasons — the stage-level detail of the result (CLAUDE.md seam
# 4): a score row that just says 'incorrect' hides which §7.8 cell fired, and
# the blank/unresolved distinction is exactly the thing that must stay legible.
REASON_KEY_MATCH = "key_match"
REASON_KEY_MISS = "key_miss"
REASON_BLANK = "blank_legitimate_zero"
REASON_ABSENT_REGION = "absent_region"
REASON_AMBIGUOUS_MARK = "ambiguous_mark"
REASON_MULTIPLE_MARKS = "multiple_marks"
REASON_NO_SELECTION_READ = "no_selection_read"
REASON_SINGLE_SELECT_MULTIPLE = "single_select_multiple_options"
REASON_SELECTION_OUTSIDE_OPTION_SET = "selection_outside_option_set"

#: `CT-DET-13`'s alert threshold as a per-question rate of unresolved marks.
#: The default is a starting point, not a law — a slower scanner or a worse
#: scan batch adjusts it per environment without a code change.
DEFAULT_UNRESOLVED_ALERT_RATE = 0.05
UNRESOLVED_ALERT_RATE_ENV = "HARNESS_DET_UNRESOLVED_ALERT_RATE"

# --- the audit record and the statistical separation (FR-DET-09 / FR-DET-10) -----------------------

EVALUATION_MODE_JUDGED = "judged"
EVALUATION_MODE_DETERMINISTIC = "deterministic"
EVALUATION_MODES = (EVALUATION_MODE_JUDGED, EVALUATION_MODE_DETERMINISTIC)
DECIDED_BY_SYSTEM = "system"

#: `NFR-DET-03` — the statistical-separation filter, defined here EXACTLY ONCE.
#: Every agreement, kappa, alpha and grader-quality figure excludes deterministic
#: results through THIS predicate (`FR-DET-09`, `CT-DET-06`, R53): agreement with
#: an answer key is not agreement between judges, and mixing the two inflates
#: kappa toward whatever share of the assessment is multiple choice. det owns the
#: column (`label.evaluation_mode`); the consumer owns the rest of its admissible-
#: label conjunction (`NFR-STATS-04`'s `label_type = 'blind'`). The qualified form
#: survives a join, because the consumers' queries join.
DETERMINISTIC_EXCLUSION = "label.evaluation_mode <> 'deterministic'"


def unresolved_alert_rate(environ: Mapping[str, str] | None = None) -> float:
    """The unresolved-count alert rate, read at call time (`CLAUDE.md` seam 3).

    `HARNESS_DET_UNRESOLVED_ALERT_RATE` is a fraction of a question's cohort in
    (0, 1]. An unparseable or out-of-range value falls back to the default
    rather than raising: a mis-set knob must not stop grading, but the report
    records which value actually applied so the fallback is visible.
    """
    source = os.environ if environ is None else environ
    raw = source.get(UNRESOLVED_ALERT_RATE_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_UNRESOLVED_ALERT_RATE
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_UNRESOLVED_ALERT_RATE
    if not 0.0 < value <= 1.0:
        return DEFAULT_UNRESOLVED_ALERT_RATE
    return value


def _now() -> str:
    """The one wall-clock read the audit trail writes, UTC ISO-8601 — the same
    form `ingest._now` and `orch._now` use, so every recorded_at in the store
    reads the same way."""
    return datetime.now(timezone.utc).isoformat()


def _newest_run(runs: list[Any]) -> Any:
    """The cohort's newest run — latest non-null `started_at`, then `run_id` —
    the run a re-derivation attributes its audit rows to: the one whose grades
    the correction supersedes."""
    return max(runs, key=lambda row: (row["started_at"] or "", row["run_id"]))


# --- errors ----------------------------------------------------------------------------------------


class DeterministicError(Exception):
    """Base for every `M-DET` refusal. Nothing here is transient; no caller
    should retry (`CT-DET-10`), so there is deliberately no retry taxonomy."""


class MalformedSelectionRead(DeterministicError):
    """A region state outside the declared vocabularies — impossible from a
    migrated store, so it means a caller bypassed the store's CHECKs."""


class MalformedAnswerKey(DeterministicError):
    """A key that cannot be compared: empty, bad JSON, or shaped for a
    different select count. `FR-SETUP-03` makes a missing key a
    publication-time failure, so this cannot be raised by a published
    package — the guard exists to name the impossible situation loudly."""


class UndeclaredPartialCreditPolicy(DeterministicError):
    """A multi-select criterion scored with no declared policy (`TC-DET-03`
    cell 11). The module never infers one."""


class UnknownPartialCreditPolicy(DeterministicError):
    """A declared policy outside the closed vocabulary."""


class NotDeterministicCriterion(DeterministicError):
    """A criterion whose evaluation is not lookup reached the lookup module —
    an `M-ORCH` admission failure (`FR-ORCH-08`), never a scoring outcome."""


class UnknownCriterion(DeterministicError):
    """No such criterion in the named package version."""


class UnknownRun(DeterministicError):
    """No run row in any cohort ledger for the given run id."""


class UnknownCohort(DeterministicError):
    """No cohort ledger on file for the given cohort id. Opening the tier handle
    would CREATE the file, so the lookup checks the ledger directory first — a
    typo'd cohort id must be named, not silently materialized."""


# --- the pure kernel: the §7.8 situation table ------------------------------------------------------


@dataclass(frozen=True)
class DetOutcome:
    """One cell of the §7.8 situation table, resolved.

    `band` is `'correct'` / `'incorrect'`, or the `'unresolved'` marker for a
    row that was never scored. `credit` is the earned fraction (1.0 on an
    exact match, the per_option fraction under partial credit, 0.0 on a miss
    and for every unresolved cell). `reason` names the cell — it is what keeps
    a stored score answerable about why it is what it is.
    """

    band: str
    state: str
    routing: str
    credit: float
    reason: str
    selection_read: tuple[str, ...] | None


def _unresolved(reason: str) -> DetOutcome:
    return DetOutcome(
        band=BAND_UNRESOLVED,
        state=STATE_UNRESOLVED_SELECTION,
        routing=ROUTING_TRIAGE,
        credit=0.0,
        reason=reason,
        selection_read=None,
    )


def evaluate(
    *,
    content_state: str,
    key: Sequence[str],
    selection_state: str | None = None,
    selection: Sequence[str] | None = None,
    multi_select: bool = False,
    partial_credit: str | None = None,
    option_set: Sequence[str] | None = None,
) -> DetOutcome:
    """Score one selection read against one key under one policy.

    A pure function of (selection, key, policy) plus the two states
    M-INGEST recorded about the read — no I/O, no clock, no configuration
    (`CT-DET-01`, `NFR-DET-02`). Raises only on inputs that cannot come from
    a published package or a migrated store: a malformed key, a malformed
    state, or — the contract's decisive negative — a multi-select criterion
    with no declared policy (`TC-DET-03` cell 11).
    """
    if content_state not in CONTENT_STATES:
        raise MalformedSelectionRead(
            f"content_state {content_state!r} is outside {CONTENT_STATES}."
        )
    resolved_key = tuple(key)
    if not resolved_key:
        raise MalformedAnswerKey(
            "an empty answer key cannot be scored; FR-SETUP-03 makes a missing "
            "key a publication-time failure that cannot reach this module."
        )
    if not multi_select and len(resolved_key) != 1:
        raise MalformedAnswerKey(
            f"a single-select criterion is keyed to exactly one option; this "
            f"key holds {len(resolved_key)} ({resolved_key!r})."
        )
    if multi_select and partial_credit is None:
        # Consulted on the comparison path only — but raised here too, because
        # a caller evaluating a multi-select selection without a declared
        # policy must not discover the omission by getting a silently
        # defaulted score; the raise fires the moment the criterion says
        # multi-select and the package declares nothing.
        raise UndeclaredPartialCreditPolicy(
            "multi-select criterion with no declared partial-credit policy: "
            "FR-DET-05 forbids inferring one; declare all_or_nothing or "
            "per_option in the package."
        )
    if multi_select and partial_credit not in PARTIAL_CREDIT_POLICIES:
        raise UnknownPartialCreditPolicy(
            f"partial_credit {partial_credit!r} is outside {PARTIAL_CREDIT_POLICIES}."
        )

    if content_state == "absent":
        # Cell 5: the answer region does not exist. A scanning problem, never
        # a zero the student earned.
        return _unresolved(REASON_ABSENT_REGION)

    if content_state == "blank":
        # Cell 6: the mirror of the unresolved cells — a genuinely empty
        # answer IS a zero, a legitimate one, counted in blank_count and
        # never in unresolved_count.
        return DetOutcome(
            band=BAND_INCORRECT,
            state=STATE_FINAL,
            routing=ROUTING_AUTO,
            credit=0.0,
            reason=REASON_BLANK,
            selection_read=None,
        )

    # content_state == 'present'
    if selection_state is None:
        # A present region with no selection read at all (or a region_kind
        # that is not a selection mark where one was declared) is an
        # unreadable answer — route it, never guess.
        return _unresolved(REASON_NO_SELECTION_READ)
    if selection_state not in SELECTION_STATES:
        raise MalformedSelectionRead(
            f"selection_state {selection_state!r} is outside {SELECTION_STATES}."
        )
    if selection_state == "ambiguous":
        return _unresolved(REASON_AMBIGUOUS_MARK)
    if selection_state == "multiple_marks":
        # Cells 3/4 and CT-DET-C03's boundary: even a mark far darker than
        # the others stays unresolved. "Clearly they meant this one" is the
        # heuristic this module exists to refuse.
        return _unresolved(REASON_MULTIPLE_MARKS)

    # selection_state == 'resolved'
    if not selection:
        # CT-INGEST-04: selection is populated iff resolved. A violation of
        # that contract is not a score — it routes.
        return _unresolved(REASON_NO_SELECTION_READ)
    chosen: tuple[str, ...] = ()
    for option_id in selection:
        if option_id not in chosen:
            chosen = chosen + (option_id,)
    if option_set is not None:
        declared = set(option_set)
        if any(option_id not in declared for option_id in chosen):
            return _unresolved(REASON_SELECTION_OUTSIDE_OPTION_SET)

    if not multi_select:
        if len(chosen) != 1:
            return _unresolved(REASON_SINGLE_SELECT_MULTIPLE)
        matched = chosen[0] == resolved_key[0]
        return DetOutcome(
            band=BAND_CORRECT if matched else BAND_INCORRECT,
            state=STATE_FINAL,
            routing=ROUTING_AUTO,
            credit=1.0 if matched else 0.0,
            reason=REASON_KEY_MATCH if matched else REASON_KEY_MISS,
            selection_read=chosen,
        )

    chosen_set = set(chosen)
    key_set = set(resolved_key)
    exact = chosen_set == key_set
    if partial_credit == POLICY_ALL_OR_NOTHING:
        # Cells 7/8: everything or nothing — a subset and a superset are
        # equally not the answer.
        return DetOutcome(
            band=BAND_CORRECT if exact else BAND_INCORRECT,
            state=STATE_FINAL,
            routing=ROUTING_AUTO,
            credit=1.0 if exact else 0.0,
            reason=REASON_KEY_MATCH if exact else REASON_KEY_MISS,
            selection_read=chosen,
        )
    # POLICY_PER_OPTION — cells 9/10, with the over-selection rule stated in
    # the module docstring: each non-key selection cancels one earned credit,
    # floored at zero.
    earned = len(chosen_set & key_set) - len(chosen_set - key_set)
    credit = max(0, earned) / len(resolved_key)
    return DetOutcome(
        band=BAND_CORRECT if exact else BAND_INCORRECT,
        state=STATE_FINAL,
        routing=ROUTING_AUTO,
        credit=credit,
        reason=REASON_KEY_MATCH if exact else REASON_KEY_MISS,
        selection_read=chosen,
    )


# --- migrations ------------------------------------------------------------------------------------
# Appended to the registry at import, in the pattern pkg/ingest/orch set. Versions
# claimed: package 10, cohort 9, durable 3 and 4 — renumber on rebase if a sibling took
# one (#52's pkg_setup_classification took package 9, #58's orch_leasing took cohort 8).

_DET_SELECTION_POLICY = Migration(
    version=10,
    name="det_selection_policy_columns",
    statements=(
        # FR-DET-05: the partial-credit policy is DECLARED in the package or it
        # does not exist. multi_select marks a criterion keyed to several
        # options; a NULL partial_credit on such a criterion is refused at
        # scoring time, never defaulted (TC-DET-03 cell 11).
        Statement(
            "ALTER TABLE criterion ADD COLUMN multi_select INTEGER NOT NULL "
            "DEFAULT 0 CHECK (multi_select IN (0, 1))"
        ),
        Statement(
            "ALTER TABLE criterion ADD COLUMN partial_credit TEXT "
            "CHECK (partial_credit IS NULL OR partial_credit IN "
            "('all_or_nothing', 'per_option'))"
        ),
    ),
)

_DET_SCORE_STATE = Migration(
    version=9,
    name="det_score_state_columns",
    statements=(
        # FR-DET-02/03/04: the deterministic score row's shape. judge_count is
        # 0 and agreement NULL by construction; the CHECK is the HLD §9.6
        # constraint (0 or odd), so an even panel is a failed write the day
        # M-AGG starts writing these rows too. state and routing carry the
        # three-way distinction: 'unresolved_selection' routed to 'triage' is
        # expressible, and nothing in this module's vocabulary admits 'queued'.
        Statement("ALTER TABLE criterion_score ADD COLUMN points REAL"),
        Statement(
            "ALTER TABLE criterion_score ADD COLUMN judge_count INTEGER "
            "NOT NULL DEFAULT 0 CHECK (judge_count = 0 OR judge_count % 2 = 1)"
        ),
        Statement("ALTER TABLE criterion_score ADD COLUMN agreement REAL"),
        Statement(
            "ALTER TABLE criterion_score ADD COLUMN state TEXT NOT NULL "
            "DEFAULT 'final' CHECK (state IN ('final', 'provisional_unreviewed', "
            "'ungradeable_by_panel', 'unresolved_selection'))"
        ),
        Statement(
            "ALTER TABLE criterion_score ADD COLUMN routing TEXT NOT NULL "
            "DEFAULT 'auto' CHECK (routing IN ('auto', 'queued', 'reviewed', "
            "'provisional', 'triage'))"
        ),
    ),
)

_DET_ITEM_STATISTICS = Migration(
    version=3,
    name="det_item_statistic_columns",
    statements=(
        # FR-DET-07 / CT-DET-08: blank count and unresolved count are SEPARATE
        # figures with SEPARATE columns, so a later merge into one "not
        # answered" figure is a schema change, not an accident. is_key is
        # denormalized so the rollup needs no join (HLD §9.7).
        Statement(
            "ALTER TABLE mcq_item_stats ADD COLUMN is_key INTEGER NOT NULL "
            "DEFAULT 0 CHECK (is_key IN (0, 1))"
        ),
        Statement(
            "ALTER TABLE mcq_item_summary ADD COLUMN n INTEGER NOT NULL DEFAULT 0"
        ),
        Statement(
            "ALTER TABLE mcq_item_summary ADD COLUMN correct_rate REAL "
            "NOT NULL DEFAULT 0.0"
        ),
        Statement(
            "ALTER TABLE mcq_item_summary ADD COLUMN blank_count INTEGER "
            "NOT NULL DEFAULT 0"
        ),
        Statement(
            "ALTER TABLE mcq_item_summary ADD COLUMN unresolved_count INTEGER "
            "NOT NULL DEFAULT 0"
        ),
    ),
)

_DET_AUDIT_SEPARATION = Migration(
    version=4,
    name="det_audit_separation_columns",
    statements=(
        # FR-DET-10 / CT-DET-09: the deterministic grade's audit record, at the
        # HLD §9.7 column set. The per-grade columns (submission/criterion/
        # points/decided_by/version) are NULL on orch's run-level rows, which
        # predate this migration and carry only the profile summary; the
        # vocabulary columns default to 'judged' because every pre-existing row
        # is a judged artifact, and det writes 'deterministic' explicitly. The
        # NOT NULL + DEFAULT form is what an additive SQLite column on a
        # populated table can carry — see the module docstring's interpretations.
        Statement("ALTER TABLE audit_record ADD COLUMN submission_id TEXT"),
        Statement("ALTER TABLE audit_record ADD COLUMN criterion_id TEXT"),
        Statement("ALTER TABLE audit_record ADD COLUMN final_points REAL"),
        Statement("ALTER TABLE audit_record ADD COLUMN decided_by TEXT"),
        Statement("ALTER TABLE audit_record ADD COLUMN package_version_id TEXT"),
        Statement(
            "ALTER TABLE audit_record ADD COLUMN evaluation_mode TEXT "
            "NOT NULL DEFAULT 'judged' CHECK (evaluation_mode IN "
            "('judged', 'deterministic'))"
        ),
        Statement("ALTER TABLE audit_record ADD COLUMN panel_config TEXT"),
        Statement("ALTER TABLE audit_record ADD COLUMN prompt_template_v TEXT"),
        Statement("ALTER TABLE audit_record ADD COLUMN answer_key_ref TEXT"),
        Statement("ALTER TABLE audit_record ADD COLUMN selection_read TEXT"),
        # FR-DET-09 / CT-DET-06: the separation column itself. The exclusion it
        # enforces is DETERMINISTIC_EXCLUSION above — one predicate, every
        # statistics consumer (NFR-DET-03).
        Statement(
            "ALTER TABLE label ADD COLUMN evaluation_mode TEXT "
            "NOT NULL DEFAULT 'judged' CHECK (evaluation_mode IN "
            "('judged', 'deterministic'))"
        ),
    ),
)


DET_STATEMENTS: dict[str, Statement] = {
    "select_run": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id FROM run "
        "WHERE run_id = :run_id"
    ),
    "select_cohort_submissions": Statement(
        "SELECT submission_id FROM submission WHERE cohort_id = :cohort_id "
        "ORDER BY submission_id"
    ),
    "select_criterion": Statement(
        "SELECT criterion_id, question_id, kind, answer_key, multi_select, "
        "partial_credit FROM criterion WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "select_mcq_criteria": Statement(
        "SELECT criterion_id, question_id, kind, answer_key, multi_select, "
        "partial_credit FROM criterion WHERE package_version_id = :v "
        "AND kind = 'mcq' ORDER BY criterion_id"
    ),
    "select_options": Statement(
        "SELECT option_id FROM mcq_option WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id ORDER BY option_id"
    ),
    # M-INGEST's head-document query shape: page replacements append newer
    # documents, so the head is the last row.
    "select_document_head": Statement(
        "SELECT document_id, submission_id, content_hash, parent_doc_id, "
        "created_at FROM document WHERE submission_id = :submission_id "
        "ORDER BY created_at, document_id"
    ),
    "select_regions": Statement(
        "SELECT region_id, document_id, element_kind, region_kind, retraction, "
        "content_state, selection_state, selection FROM document_region "
        "WHERE document_id = :document_id ORDER BY position"
    ),
    "upsert_criterion_score": Statement(
        "INSERT INTO criterion_score (submission_id, criterion_id, band, points, "
        "judge_count, agreement, state, routing) VALUES (:submission_id, "
        ":criterion_id, :band, :points, :judge_count, :agreement, :state, "
        ":routing) ON CONFLICT (submission_id, criterion_id) DO UPDATE SET "
        "band = excluded.band, points = excluded.points, "
        "judge_count = excluded.judge_count, agreement = excluded.agreement, "
        "state = excluded.state, routing = excluded.routing"
    ),
    "delete_item_stats": Statement(
        "DELETE FROM mcq_item_stats WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "insert_item_stat": Statement(
        "INSERT INTO mcq_item_stats (package_version_id, criterion_id, option, "
        "chosen, is_key) VALUES (:v, :criterion_id, :option, :chosen, :is_key)"
    ),
    "delete_item_summary": Statement(
        "DELETE FROM mcq_item_summary WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "insert_item_summary": Statement(
        "INSERT INTO mcq_item_summary (package_version_id, criterion_id, n, "
        "correct_rate, blank_count, unresolved_count) VALUES (:v, "
        ":criterion_id, :n, :correct_rate, :blank_count, :unresolved_count)"
    ),
    # --- #87: rederivation, the audit record, the shared filter, the read API ---
    "select_cohort_runs": Statement(
        "SELECT run_id, cohort_id, package_version_id, package_id, started_at "
        "FROM run WHERE cohort_id = :cohort_id ORDER BY run_id"
    ),
    "select_criterion_scores": Statement(
        "SELECT submission_id, band, points, state, routing FROM criterion_score "
        "WHERE criterion_id = :criterion_id ORDER BY submission_id"
    ),
    "upsert_rederived_score": Statement(
        # The same shape as upsert_criterion_score: a re-derivation is an
        # evaluation under the corrected key, and a re-run of the same
        # (submission, criterion) lands on the same row.
        "INSERT INTO criterion_score (submission_id, criterion_id, band, points, "
        "judge_count, agreement, state, routing) VALUES (:submission_id, "
        ":criterion_id, :band, :points, :judge_count, :agreement, :state, "
        ":routing) ON CONFLICT (submission_id, criterion_id) DO UPDATE SET "
        "band = excluded.band, points = excluded.points, "
        "judge_count = excluded.judge_count, agreement = excluded.agreement, "
        "state = excluded.state, routing = excluded.routing"
    ),
    "insert_audit_record": Statement(
        "INSERT INTO audit_record (audit_record_id, run_id, recorded_at, "
        "profile_summary, submission_id, criterion_id, final_points, decided_by, "
        "package_version_id, evaluation_mode, panel_config, prompt_template_v, "
        "answer_key_ref, selection_read) VALUES (:audit_record_id, :run_id, "
        ":recorded_at, :profile_summary, :submission_id, :criterion_id, "
        ":final_points, :decided_by, :package_version_id, :evaluation_mode, "
        ":panel_config, :prompt_template_v, :answer_key_ref, :selection_read)"
    ),
    # NFR-DET-03's canonical composition: the agreement-figure query. The
    # exclusion half is DETERMINISTIC_EXCLUSION above — the ONE definition — and
    # the blind half is NFR-STATS-04's, recorded here so the whole conjunction
    # has a readable home. Consumers use this statement or compose the constant;
    # neither is re-spelled at a call site.
    "select_agreement_labels": Statement(
        "SELECT label_id, run_id, student_ref, criterion_id, label_type, band, "
        "evaluation_mode FROM label WHERE label_type = 'blind' AND "
        f"{DETERMINISTIC_EXCLUSION} ORDER BY label_id"
    ),
    "select_item_stats_for_version": Statement(
        "SELECT criterion_id, option, chosen, is_key FROM mcq_item_stats "
        "WHERE package_version_id = :v ORDER BY criterion_id, option"
    ),
    "select_item_summary_for_version": Statement(
        "SELECT criterion_id, n, correct_rate, blank_count, unresolved_count "
        "FROM mcq_item_summary WHERE package_version_id = :v ORDER BY criterion_id"
    ),
}
STATEMENTS.update(DET_STATEMENTS)
TIER_MIGRATIONS[Tier.PACKAGE] = TIER_MIGRATIONS[Tier.PACKAGE] + (_DET_SELECTION_POLICY,)
TIER_MIGRATIONS[Tier.COHORT] = TIER_MIGRATIONS[Tier.COHORT] + (_DET_SCORE_STATE,)
TIER_MIGRATIONS[Tier.DURABLE] = TIER_MIGRATIONS[Tier.DURABLE] + (
    _DET_ITEM_STATISTICS,
    _DET_AUDIT_SEPARATION,
)


# --- the stored result and the pass report ----------------------------------------------------------


@dataclass(frozen=True)
class SelectionRead:
    """What M-INGEST recorded about one question's answer, as the kernel's
    inputs. `selection` is a tuple of option ids (one per resolved option;
    today's ingest delivers at most one) or None when nothing was read."""

    content_state: str
    selection_state: str | None
    selection: tuple[str, ...] | None


@dataclass(frozen=True)
class CriterionScore:
    """The score row this module wrote, returned to the caller — per-field,
    never a bare status (`CLAUDE.md` seam 4)."""

    run_id: str
    submission_id: str
    criterion_id: str
    question_id: str
    band: str
    state: str
    routing: str
    points: float | None
    judge_count: int
    agreement: float | None
    credit: float
    reason: str
    selection_read: tuple[str, ...] | None


@dataclass(frozen=True)
class CriterionSummary:
    """One question's item summary (`FR-DET-07`): n, correct rate, and — the
    separation that is contract (`CT-DET-08`) — blank count and unresolved
    count as separate figures. `most_chosen_distractor` is the highest-count
    non-key option (ties broken lexicographically, so the report is
    deterministic). `unresolved_rate` above the threshold alerts as a
    SCANNING problem; it is never item difficulty."""

    criterion_id: str
    question_id: str
    n: int
    correct: int
    correct_rate: float
    blank_count: int
    unresolved_count: int
    unresolved_rate: float
    most_chosen_distractor: str | None


@dataclass(frozen=True)
class DeterministicReport:
    """What one cohort pass did (`CLAUDE.md` seam 4): counts, per-question
    summaries, and the scanning alerts — a bare success on an empty detail is
    the silent-failure trap this exists to refuse."""

    run_id: str
    cohort_id: str
    package_version_id: str
    submissions: int
    criteria: int
    evaluations: int
    correct: int
    incorrect: int
    blank: int
    unresolved: int
    unresolved_alert_rate: float
    #: Audit records appended for this pass's scored rows (`FR-DET-10`). Unresolved
    #: rows write none — no grade, no points, nothing for `final_points NOT NULL`
    #: to carry (see the module docstring's interpretations).
    audit_records_written: int
    summaries: tuple[CriterionSummary, ...]
    alerts: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ItemOptionCount:
    """One option's chosen count within one question's stats (`FR-DET-07`):
    the count, and the denormalized key flag (`CT-DET-08`'s rollup needs no
    join)."""

    criterion_id: str
    option: str
    chosen: int
    is_key: bool


@dataclass(frozen=True)
class ItemStatsEntry:
    """One question's read-back statistics (`FR-DET-07`): the summary figures
    and the per-option counts they were built from. blank_count and
    unresolved_count stay separate figures here for the same reason they are
    separate columns (`CT-DET-08`)."""

    criterion_id: str
    n: int
    correct_rate: float
    blank_count: int
    unresolved_count: int
    options: tuple[ItemOptionCount, ...]


@dataclass(frozen=True)
class ItemStatsReport:
    """What `item_stats` returns for one cohort (`FR-DET-07`, `CT-DET-08`).
    `package_version_id` is None exactly when the cohort has no run rows — an
    empty report on an evaluated cohort is impossible, because the cohort pass
    writes the stats it summarizes."""

    cohort_id: str
    package_version_id: str | None
    items: tuple[ItemStatsEntry, ...]


@dataclass(frozen=True)
class RederiveChange:
    """One submission's score difference under the corrected key (`FR-DET-08`).
    `old_band` is None when no score row existed — the re-derivation created
    one. Unresolved rows appear here only as no-changes: they never depended on
    the key."""

    submission_id: str
    old_band: str | None
    new_band: str
    old_points: float | None
    new_points: float | None


@dataclass(frozen=True)
class RederiveReport:
    """What one key-correction re-derivation did (`FR-DET-08`, `CT-DET-07`):
    the versions involved, the diff, and the declared zeros — zero panel work
    enqueued is a FIELD, not an absence, so the refusal to enqueue is visible
    in the result (`CLAUDE.md` seam 4, `TC-DET-C07`'s exact zero)."""

    cohort_id: str
    criterion_id: str
    question_id: str | None
    new_version: str
    from_versions: tuple[str, ...]
    submissions_examined: int
    scores_changed: int
    scores_unchanged: int
    audit_records_written: int
    panel_units_enqueued: int
    changes: tuple[RederiveChange, ...]


def _cohort_keys_on_filesystem(store: Any) -> tuple[str, ...]:
    """The default cohort-key discovery, same layout the orchestrator walks:
    one `cohorts/<cohort_id>.sqlite` file per administration (§3.3). A store
    that lays the tier out differently injects its own key function."""
    data_dir = getattr(store, "data_dir", None)
    if data_dir is None:
        raise DeterministicError(
            "finding a run by id walks the store's cohort ledger files, which "
            "needs the store's data directory; this store exposes no `data_dir`. "
            "Inject a cohort_keys_for function."
        )
    return tuple(path.stem for path in Path(data_dir, "cohorts").glob("*.sqlite"))


def _decode_answer_key(raw: Any, criterion_id: str) -> tuple[str, ...]:
    """`criterion.answer_key` is a JSON list of option ids (one for
    single-select, several for multi-select). A malformed key is a
    package-integrity failure named here, not a JSON leak."""
    if raw is None or raw == "":
        return ()
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise MalformedAnswerKey(
            f"criterion {criterion_id!r} carries a non-JSON answer key: {error}"
        ) from error
    if not isinstance(parsed, list) or not all(isinstance(o, str) for o in parsed):
        raise MalformedAnswerKey(
            f"criterion {criterion_id!r}'s answer key is not a list of option ids."
        )
    return tuple(parsed)


class DeterministicEvaluator:
    """The design's `DeterministicEvaluator` (§3.11). A caller holding this
    module holds arithmetic: a selection compared to a key. No model, no
    panel, no interpretation, and no route into anything the teacher's minutes
    pay for (`FR-DET-06`)."""

    def __init__(
        self,
        store: Store,
        *,
        cohort_keys_for: Callable[[Any], tuple[str, ...]] | None = None,
    ) -> None:
        self._store = store
        self._cohort_keys_for = cohort_keys_for or _cohort_keys_on_filesystem

    # -- one criterion, one submission ----------------------------------------------------------

    def evaluate(
        self, run_id: str, submission_id: str, criterion_id: str
    ) -> CriterionScore:
        """Score one deterministic criterion for one submission, by exact
        answer-key lookup (`FR-DET-01`), and write its score row (`FR-DET-02`).
        Idempotent under redelivery: the upsert makes a re-run of the same
        (submission, criterion) a no-op, which is what at-least-once leasing
        requires. No verdict row, no review-queue row, no panel work — this
        write set is the whole of what this module touches."""
        run = self._run_row(run_id)
        cohort_handle = self._store.cohort(run["cohort_id"])
        package_handle = self._store.package(run["package_id"])
        catalog = self._catalog(run)
        criterion = self._criterion(
            package_handle, run["package_version_id"], criterion_id
        )
        outcome, points = self._score_one(
            cohort_handle, package_handle, run["package_version_id"], criterion,
            submission_id, catalog=catalog,
        )
        with cohort_handle.transaction() as tx:
            tx.execute(
                DET_STATEMENTS["upsert_criterion_score"],
                submission_id=submission_id,
                criterion_id=criterion_id,
                band=outcome.band,
                points=points,
                judge_count=0,
                agreement=None,
                state=outcome.state,
                routing=outcome.routing,
            )
        self._append_audit_records(
            run, run["package_version_id"], [(submission_id, criterion, outcome, points)]
        )
        return CriterionScore(
            run_id=run_id,
            submission_id=submission_id,
            criterion_id=criterion_id,
            question_id=criterion["question_id"],
            band=outcome.band,
            state=outcome.state,
            routing=outcome.routing,
            points=points,
            judge_count=0,
            agreement=None,
            credit=outcome.credit,
            reason=outcome.reason,
            selection_read=outcome.selection_read,
        )

    # -- the cohort pass -------------------------------------------------------------------------

    def evaluate_cohort(self, run_id: str) -> DeterministicReport:
        """Every deterministic criterion for every submission of the run, in
        one pass (`NFR-DET-01`): zero model calls, score rows in one Tier C
        transaction, item statistics in one Tier D transaction, per-question
        summaries and scanning alerts in the returned report. Unresolved
        counts above `HARNESS_DET_UNRESOLVED_ALERT_RATE` alert as a scanning
        problem — a rescan queue, never an item-difficulty reading."""
        run = self._run_row(run_id)
        cohort_handle = self._store.cohort(run["cohort_id"])
        package_handle = self._store.package(run["package_id"])
        catalog = self._catalog(run)
        version = run["package_version_id"]
        criteria = [
            dict(row)
            for row in package_handle.query(DET_STATEMENTS["select_mcq_criteria"], v=version)
        ]
        for criterion in criteria:
            criterion["answer_key"] = _decode_answer_key(
                criterion["answer_key"], criterion["criterion_id"]
            )
            criterion["multi_select"] = bool(criterion["multi_select"])
        option_sets = {
            criterion["criterion_id"]: tuple(
                row["option_id"]
                for row in package_handle.query(
                    DET_STATEMENTS["select_options"],
                    v=version,
                    criterion_id=criterion["criterion_id"],
                )
            )
            for criterion in criteria
        }
        submissions = [
            row["submission_id"]
            for row in cohort_handle.query(
                DET_STATEMENTS["select_cohort_submissions"], cohort_id=run["cohort_id"]
            )
        ]
        alert_rate = unresolved_alert_rate()
        tallies: dict[str, dict[str, Any]] = {}
        scored: list[tuple[str, dict[str, Any], DetOutcome, float | None]] = []
        for submission_id in submissions:
            reads = self._selection_reads(cohort_handle, submission_id)
            for criterion in criteria:
                outcome, points = self._score_one(
                    cohort_handle, package_handle, version, criterion, submission_id,
                    option_set=option_sets[criterion["criterion_id"]] or None,
                    catalog=catalog,
                    read=reads.get(
                        criterion["question_id"], SelectionRead("absent", None, None)
                    ),
                )
                scored.append((submission_id, criterion, outcome, points))
                tally = tallies.setdefault(
                    criterion["criterion_id"],
                    {
                        "criterion_id": criterion["criterion_id"],
                        "question_id": criterion["question_id"],
                        "key": tuple(criterion["answer_key"]),
                        "n": 0,
                        "correct": 0,
                        "incorrect": 0,
                        "blank": 0,
                        "unresolved": 0,
                        "chosen": {},
                        "options": option_sets[criterion["criterion_id"]],
                    },
                )
                tally["n"] += 1
                if outcome.band == BAND_CORRECT:
                    tally["correct"] += 1
                elif outcome.band == BAND_INCORRECT:
                    tally["incorrect"] += 1
                if outcome.reason == REASON_BLANK:
                    tally["blank"] += 1
                if outcome.state == STATE_UNRESOLVED_SELECTION:
                    tally["unresolved"] += 1
                if outcome.selection_read:
                    for option_id in outcome.selection_read:
                        tally["chosen"][option_id] = (
                            tally["chosen"].get(option_id, 0) + 1
                        )
        with cohort_handle.transaction() as tx:
            for submission_id, criterion, outcome, points in scored:
                tx.execute(
                    DET_STATEMENTS["upsert_criterion_score"],
                    submission_id=submission_id,
                    criterion_id=criterion["criterion_id"],
                    band=outcome.band,
                    points=points,
                    judge_count=0,
                    agreement=None,
                    state=outcome.state,
                    routing=outcome.routing,
                )
        self._write_item_statistics(tallies, version)
        audit_records_written = self._append_audit_records(
            run, version, scored
        )
        summaries: list[CriterionSummary] = []
        alerts: list[dict[str, Any]] = []
        for criterion in criteria:
            tally = tallies.get(criterion["criterion_id"])
            if tally is None:
                # A criterion over an empty cohort: nothing to summarize, and
                # an empty summary row would read as a 0.0 correct rate — say
                # nothing instead of summarizing nothing.
                continue
            n = tally["n"]
            summary = CriterionSummary(
                criterion_id=tally["criterion_id"],
                question_id=tally["question_id"],
                n=n,
                correct=tally["correct"],
                correct_rate=(tally["correct"] / n) if n else 0.0,
                blank_count=tally["blank"],
                unresolved_count=tally["unresolved"],
                unresolved_rate=(tally["unresolved"] / n) if n else 0.0,
                most_chosen_distractor=self._most_chosen_distractor(
                    tally["chosen"], tally["key"]
                ),
            )
            summaries.append(summary)
            if n and summary.unresolved_rate > alert_rate:
                alerts.append(
                    {
                        "criterion_id": summary.criterion_id,
                        "question_id": summary.question_id,
                        "n": n,
                        "unresolved_count": summary.unresolved_count,
                        "unresolved_rate": summary.unresolved_rate,
                        "threshold": alert_rate,
                        "kind": "scanning_problem",
                        "reads_as": "rescan_queue_never_item_difficulty",
                    }
                )
        return DeterministicReport(
            run_id=run_id,
            cohort_id=run["cohort_id"],
            package_version_id=version,
            submissions=len(submissions),
            criteria=len(criteria),
            evaluations=len(scored),
            correct=sum(t["correct"] for t in tallies.values()),
            incorrect=sum(t["incorrect"] for t in tallies.values()),
            blank=sum(t["blank"] for t in tallies.values()),
            unresolved=sum(t["unresolved"] for t in tallies.values()),
            unresolved_alert_rate=alert_rate,
            audit_records_written=audit_records_written,
            summaries=tuple(summaries),
            alerts=tuple(alerts),
        )

    # -- the key-correction path and the read API (FR-DET-08 / FR-DET-07) ----

    def rederive_for_key_change(
        self, cohort_id: str, criterion_id: str, new_version: str
    ) -> RederiveReport:
        """Re-derive one criterion's scores for one cohort under a corrected
        answer key (`FR-DET-08`, `CT-DET-07`). A correction is a new package
        version (`FR-PKG-18`); this reads the criterion, its options and its
        points from THAT version, re-runs the same §7.8 kernel over every
        submission's stored selection read — a lookup, not a re-judgement —
        and upserts only the rows whose value actually moves. No panel work,
        no review-queue row, no model call: `panel_units_enqueued` is a
        declared zero, and the audit records appended for the changed rows
        name `new_version` in their `answer_key_ref`, which is what makes a
        correction answerable years later while the untouched rows' audit
        trail still resolves each old grade to its old key.

        Idempotent (`CT-DET-07`, the M-ORCH redelivery constraint): against
        an unchanged key every re-derived value equals the stored one, so the
        change set is empty, nothing is written, and a second pass reports
        zeros across the board.

        The appended audit rows carry the cohort's NEWEST run as their
        `run_id` (latest non-null `started_at`, then run_id — the run whose
        grades the correction supersedes); which KEY version produced each
        grade travels in `answer_key_ref`, so the attribution stays exact
        even when the run named several versions.
        """
        runs = self._cohort_runs(cohort_id)
        if not runs:
            return RederiveReport(
                cohort_id=cohort_id,
                criterion_id=criterion_id,
                question_id=None,
                new_version=new_version,
                from_versions=(),
                submissions_examined=0,
                scores_changed=0,
                scores_unchanged=0,
                audit_records_written=0,
                panel_units_enqueued=0,
                changes=(),
            )
        package_ids = sorted({row["package_id"] for row in runs})
        if len(package_ids) > 1:
            raise DeterministicError(
                f"cohort {cohort_id!r}'s runs name several packages "
                f"({package_ids}); which one a key correction applies to is a "
                "caller decision this module will not guess at."
            )
        package_id = package_ids[0]
        from_versions = tuple(sorted({row["package_version_id"] for row in runs}))
        package_handle = self._store.package(package_id)
        criterion = self._criterion(package_handle, new_version, criterion_id)
        option_set = (
            tuple(
                row["option_id"]
                for row in package_handle.query(
                    DET_STATEMENTS["select_options"],
                    v=new_version,
                    criterion_id=criterion_id,
                )
            )
            or None
        )
        catalog = PackageCatalog(package_handle, package_id=package_id)
        catalog.criteria(new_version)  # pins the cache to the corrected version
        cohort_handle = self._store.cohort(cohort_id)
        submissions = [
            row["submission_id"]
            for row in cohort_handle.query(
                DET_STATEMENTS["select_cohort_submissions"], cohort_id=cohort_id
            )
        ]
        existing = {
            row["submission_id"]: row
            for row in cohort_handle.query(
                DET_STATEMENTS["select_criterion_scores"], criterion_id=criterion_id
            )
        }
        changed: list[tuple[str, dict[str, Any], DetOutcome, float | None]] = []
        report_changes: list[RederiveChange] = []
        unchanged = 0
        for submission_id in submissions:
            outcome, points = self._score_one(
                cohort_handle,
                package_handle,
                new_version,
                criterion,
                submission_id,
                option_set=option_set,
                catalog=catalog,
            )
            current = existing.get(submission_id)
            same = current is not None and (
                current["band"] == outcome.band
                and current["points"] == points
                and current["state"] == outcome.state
                and current["routing"] == outcome.routing
            )
            if same:
                unchanged += 1
                continue
            changed.append((submission_id, criterion, outcome, points))
            report_changes.append(
                RederiveChange(
                    submission_id=submission_id,
                    old_band=current["band"] if current is not None else None,
                    new_band=outcome.band,
                    old_points=current["points"] if current is not None else None,
                    new_points=points,
                )
            )
        if changed:
            with cohort_handle.transaction() as tx:
                for submission_id, criterion_row, outcome, points in changed:
                    tx.execute(
                        DET_STATEMENTS["upsert_rederived_score"],
                        submission_id=submission_id,
                        criterion_id=criterion_row["criterion_id"],
                        band=outcome.band,
                        points=points,
                        judge_count=0,
                        agreement=None,
                        state=outcome.state,
                        routing=outcome.routing,
                    )
            audit_records_written = self._append_audit_records(
                _newest_run(runs), new_version, changed
            )
        else:
            audit_records_written = 0
        return RederiveReport(
            cohort_id=cohort_id,
            criterion_id=criterion_id,
            question_id=criterion["question_id"],
            new_version=new_version,
            from_versions=from_versions,
            submissions_examined=len(submissions),
            scores_changed=len(changed),
            scores_unchanged=unchanged,
            audit_records_written=audit_records_written,
            panel_units_enqueued=0,
            changes=tuple(report_changes),
        )

    def item_stats(self, cohort_id: str) -> ItemStatsReport:
        """Read back one cohort's item statistics (`FR-DET-07`, `CT-DET-08`):
        per question, the summary figures and the per-option counts behind
        them, exactly as the cohort pass wrote them. blank_count and
        unresolved_count travel as the separate figures they are stored as —
        the unresolved count is a scanning problem, never item difficulty.
        A cohort with no runs reports an empty population under a None
        version; a cohort whose runs name several package versions is
        refused (see the module docstring)."""
        runs = self._cohort_runs(cohort_id)
        if not runs:
            return ItemStatsReport(
                cohort_id=cohort_id, package_version_id=None, items=()
            )
        versions = sorted({row["package_version_id"] for row in runs})
        if len(versions) > 1:
            raise DeterministicError(
                f"cohort {cohort_id!r}'s runs name several package versions "
                f"({versions}); one report cannot mix two instruments' figures "
                "and this module will not pick for you."
            )
        version = versions[0]
        durable_handle = self._store.durable()
        option_counts: dict[str, list[ItemOptionCount]] = {}
        for row in durable_handle.query(
            DET_STATEMENTS["select_item_stats_for_version"], v=version
        ):
            option_counts.setdefault(row["criterion_id"], []).append(
                ItemOptionCount(
                    criterion_id=row["criterion_id"],
                    option=row["option"],
                    chosen=row["chosen"],
                    is_key=bool(row["is_key"]),
                )
            )
        items = tuple(
            ItemStatsEntry(
                criterion_id=row["criterion_id"],
                n=row["n"],
                correct_rate=row["correct_rate"],
                blank_count=row["blank_count"],
                unresolved_count=row["unresolved_count"],
                options=tuple(option_counts.get(row["criterion_id"], ())),
            )
            for row in durable_handle.query(
                DET_STATEMENTS["select_item_summary_for_version"], v=version
            )
        )
        return ItemStatsReport(
            cohort_id=cohort_id, package_version_id=version, items=items
        )

    # -- private helpers -------------------------------------------------------------------------

    def _run_row(self, run_id: str) -> Any:
        """The run's ledger row, found by walking the cohort files — the same
        no-side-index walk the orchestrator makes (`FR-ORCH-02`'s reasoning
        applies unchanged: a run lives in its cohort's Tier C file, and a side
        index of run ids would be bookkeeping the ledger forbids)."""
        for key in self._cohort_keys_for(self._store):
            rows = self._store.cohort(key).query(
                DET_STATEMENTS["select_run"], run_id=run_id
            )
            if rows:
                return rows[0]
        raise UnknownRun(
            f"no run row named {run_id!r} exists in any cohort ledger; an "
            "explicit run_id that resolves to nothing is a caller error."
        )

    def _cohort_runs(self, cohort_id: str) -> list[Any]:
        """The cohort's run rows, the cohort-grain lookup `rederive_for_key_change`
        and `item_stats` resolve versions and package ids from. A cohort id that
        matches no ledger file on disk raises before the tier handle is touched —
        `store.cohort` would CREATE the missing file, and a typo must not
        materialize a cohort."""
        if cohort_id not in self._cohort_keys_for(self._store):
            raise UnknownCohort(
                f"no cohort ledger named {cohort_id!r} exists on the store's "
                "cohort tier; an explicit cohort_id that resolves to nothing is "
                "a caller error."
            )
        cohort_handle = self._store.cohort(cohort_id)
        return list(
            cohort_handle.query(
                DET_STATEMENTS["select_cohort_runs"], cohort_id=cohort_id
            )
        )

    def _append_audit_records(
        self,
        run: Any,
        version: str,
        entries: Iterable[tuple[str, dict[str, Any], DetOutcome, float | None]],
    ) -> int:
        """Append the audit records for scored rows (`FR-DET-10`, `CT-DET-09`):
        one Tier D transaction, one row per (submission, criterion) grade that
        actually carries points, in the shape the design fixes —
        `evaluation_mode='deterministic'`, NULL `panel_config` and
        `prompt_template_v` (a populated one would make the row look
        panel-scored to every statistic downstream), non-null
        `answer_key_ref` and `selection_read`. Unresolved rows are skipped:
        no grade, no points, nothing `final_points NOT NULL` could carry —
        their audit is the score row's `state`/`routing` (module docstring).
        Append-only: the trail records grading events, and the design's
        idempotency constraint names the rederivation and the stats writes,
        not the trail. Returns the count written."""
        written = 0
        durable_handle = self._store.durable()
        with durable_handle.transaction() as tx:
            for submission_id, criterion, outcome, points in entries:
                if outcome.band == BAND_UNRESOLVED:
                    continue
                tx.execute(
                    DET_STATEMENTS["insert_audit_record"],
                    audit_record_id=uuid.uuid4().hex,
                    run_id=run["run_id"],
                    recorded_at=_now(),
                    profile_summary=json.dumps(
                        {
                            "band": outcome.band,
                            "reason": outcome.reason,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    submission_id=submission_id,
                    criterion_id=criterion["criterion_id"],
                    final_points=points,
                    decided_by=DECIDED_BY_SYSTEM,
                    package_version_id=version,
                    evaluation_mode=EVALUATION_MODE_DETERMINISTIC,
                    panel_config=None,
                    prompt_template_v=None,
                    answer_key_ref=(
                        f"{version}:"
                        f"{json.dumps(list(criterion['answer_key']))}"
                    ),
                    selection_read=json.dumps(list(outcome.selection_read or ())),
                )
                written += 1
        return written

    def _criterion(
        self, package_handle: Any, version: str, criterion_id: str
    ) -> dict[str, Any]:
        """The criterion row for exactly this package version — the version the
        run names, never the file's latest, so an answer-key correction that
        created a new version does not silently re-key an in-flight run."""
        rows = package_handle.query(
            DET_STATEMENTS["select_criterion"], v=version, criterion_id=criterion_id
        )
        if not rows:
            raise UnknownCriterion(
                f"no criterion {criterion_id!r} in package version {version!r}."
            )
        criterion = dict(rows[0])
        criterion["answer_key"] = _decode_answer_key(
            criterion["answer_key"], criterion_id
        )
        criterion["multi_select"] = bool(criterion["multi_select"])
        return criterion

    def _score_one(
        self,
        cohort_handle: Any,
        package_handle: Any,
        version: str,
        criterion: dict[str, Any],
        submission_id: str,
        option_set: tuple[str, ...] | None = None,
        *,
        catalog: PackageCatalog,
        read: SelectionRead | None = None,
    ) -> tuple[DetOutcome, float | None]:
        """Read the answer, run the kernel, derive the points. Returns the
        outcome and the points to store (None for an unresolved row).
        `option_set`, `catalog` and `read` are injectable so the cohort pass
        reads each criterion's option rows once, holds one pinned catalog, and
        reads each submission's regions once, instead of per pair
        (`NFR-DET-01`)."""
        if criterion["kind"] != "mcq":
            # FR-ORCH-08: a non-mcq criterion reaching the deterministic
            # evaluator is an admission failure upstream, never a score.
            raise NotDeterministicCriterion(
                f"criterion {criterion['criterion_id']!r} has kind "
                f"{criterion['kind']!r}; only mcq criteria score by lookup."
            )
        key = tuple(criterion["answer_key"])
        if not key:
            raise MalformedAnswerKey(
                f"criterion {criterion['criterion_id']!r} carries no answer key; "
                "FR-SETUP-03 makes this a publication-time failure that a "
                "published package cannot produce."
            )
        if read is None:
            read = self._selection_read(
                cohort_handle, submission_id, criterion["question_id"]
            )
        if option_set is None:
            option_rows = package_handle.query(
                DET_STATEMENTS["select_options"],
                v=version,
                criterion_id=criterion["criterion_id"],
            )
            option_set = tuple(row["option_id"] for row in option_rows) or None
        outcome = evaluate(
            content_state=read.content_state,
            selection_state=read.selection_state,
            selection=read.selection,
            key=key,
            multi_select=bool(criterion["multi_select"]),
            partial_credit=criterion["partial_credit"],
            option_set=option_set,
        )
        return outcome, self._points(catalog, criterion["criterion_id"], outcome)

    def _selection_read(
        self, cohort_handle: Any, submission_id: str, question_id: str
    ) -> SelectionRead:
        """One question's answer regions in the head document, resolved to the
        kernel's inputs under R47's retraction discipline. The cohort pass uses
        `_selection_reads` (one query per submission) and looks the question up;
        this method is the single-criterion path."""
        return self._selection_reads(cohort_handle, submission_id).get(
            question_id,
            SelectionRead("absent", None, None),
        )

    def _selection_reads(
        self, cohort_handle: Any, submission_id: str
    ) -> dict[str, SelectionRead]:
        """Every question's answer in the head document, from one head query
        and one regions query — the shape the cohort pass needs to stay a
        single pass (`NFR-DET-01`)."""
        documents = cohort_handle.query(
            DET_STATEMENTS["select_document_head"], submission_id=submission_id
        )
        if not documents:
            return {}
        head = documents[-1]
        regions = cohort_handle.query(
            DET_STATEMENTS["select_regions"], document_id=head["document_id"]
        )
        mine: dict[str, list[Any]] = {}
        for row in regions:
            mine.setdefault(row["element_kind"], []).append(row)
        reads: dict[str, SelectionRead] = {}
        for question_id, rows in mine.items():
            reads[question_id] = self._read_from_regions(rows)
        return reads

    def _read_from_regions(self, mine: list[Any]) -> SelectionRead:
        """R47's retraction discipline applied to one question's regions (see
        module docstring). Live selection-mark regions take precedence: if any
        exist they are the candidates, and several of them are multiple marks
        — unresolved, never "darkest". A question with no live selection mark
        but other live regions still gets read — a letter written in the
        margin is a valid selection captured as a description (§7.8) — one
        such region is read, several are multiple marks. (So a single live
        selection_mark wins over coexisting non-mark regions; today's ingest
        writes one region per question, making the mixed case defensive.)"""
        live = [row for row in mine if row["retraction"] is None]
        if not live:
            # Every region for the question was struck through: the student
            # retracted their answer and left nothing — an empty answer, a
            # legitimate zero (R47's remaining-mark rule taken to its end).
            return SelectionRead("blank", None, None)
        marks = [row for row in live if row["region_kind"] == "selection_mark"]
        candidates = marks if marks else live
        if len(candidates) > 1:
            return SelectionRead("present", "multiple_marks", None)
        region = candidates[0]
        selection: tuple[str, ...] | None = None
        selection_state = region["selection_state"]
        if selection_state == "resolved" and region["selection"]:
            # FR-INGEST-17: selection is populated only when resolved, and
            # today's ingest writes at most one option id; the kernel is
            # list-valued so the situation table stays enumerable either way.
            selection = (region["selection"],)
        return SelectionRead(
            region["content_state"], selection_state, selection
        )

    def _catalog(self, run: Any) -> PackageCatalog:
        """pkg's catalog over the run's package file, its per-run cache pinned
        to the version the run names (never the file's latest — the same
        version discipline as `_criterion`). Points come from here because
        `points_for_band` is the band-to-points mapping's single canonical
        reader (`TC-PKG-C05`, RISK-05): det must not hold a second mapping
        that can drift from the declared instrument."""
        catalog = PackageCatalog(
            self._store.package(run["package_id"]),
            package_id=run["package_id"],
        )
        catalog.criteria(run["package_version_id"])  # pins the cache
        return catalog

    def _points(
        self,
        catalog: PackageCatalog,
        criterion_id: str,
        outcome: DetOutcome,
    ) -> float | None:
        """The row's points. An unresolved row was never scored: None, not
        zero (`CT-DET-03` — no zero value exists for an unresolved state). A
        scored row takes the criterion's declared band mapping, read through
        pkg's single-canonical `points_for_band` (`TC-PKG-C05`); a per_option
        fraction scales the correct band's points (see module docstring). A
        criterion missing a declared band raises pkg's own `PackageError` —
        the two-band declaration is pkg's invariant (`FR-SETUP-13`), not a
        key problem, so det does not re-label it."""
        if outcome.band == BAND_UNRESOLVED:
            return None
        if outcome.credit in (0.0, 1.0):
            return catalog.points_for_band(criterion_id, outcome.band)
        return outcome.credit * catalog.points_for_band(criterion_id, BAND_CORRECT)

    def _most_chosen_distractor(
        self, chosen: dict[str, int], key: tuple[str, ...]
    ) -> str | None:
        """The highest-count option the key does not contain, ties broken
        lexicographically so the report is deterministic (`CT-DET-13`)."""
        key_set = set(key)
        distractors = {
            option_id: count
            for option_id, count in chosen.items()
            if option_id not in key_set and count > 0
        }
        if not distractors:
            return None
        return sorted(distractors.items(), key=lambda item: (-item[1], item[0]))[0][0]

    def _write_item_statistics(
        self, tallies: dict[str, dict[str, Any]], version: str
    ) -> None:
        """`mcq_item_stats` (per-option chosen counts, key flag) and
        `mcq_item_summary` (n, correct rate, blank count, unresolved count),
        rewritten per criterion so a redelivery is idempotent (`CT-DET-08`).
        Tier D is its own transaction: the store refuses cross-tier
        transactions, and the score rows already committed in Tier C."""
        durable_handle = self._store.durable()
        with durable_handle.transaction() as tx:
            for criterion_id, tally in sorted(tallies.items()):
                tx.execute(
                    DET_STATEMENTS["delete_item_stats"],
                    v=version,
                    criterion_id=criterion_id,
                )
                key_set = set(tally["key"])
                option_ids = set(tally["chosen"]) | key_set | set(tally["options"])
                for option_id in sorted(option_ids):
                    tx.execute(
                        DET_STATEMENTS["insert_item_stat"],
                        v=version,
                        criterion_id=criterion_id,
                        option=option_id,
                        chosen=tally["chosen"].get(option_id, 0),
                        is_key=1 if option_id in key_set else 0,
                    )
                tx.execute(
                    DET_STATEMENTS["delete_item_summary"],
                    v=version,
                    criterion_id=criterion_id,
                )
                n = tally["n"]
                tx.execute(
                    DET_STATEMENTS["insert_item_summary"],
                    v=version,
                    criterion_id=criterion_id,
                    n=n,
                    correct_rate=(tally["correct"] / n) if n else 0.0,
                    blank_count=tally["blank"],
                    unresolved_count=tally["unresolved"],
                )

