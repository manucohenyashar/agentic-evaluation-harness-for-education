# `aeh.det`: design notes

These notes were the docstring of `src/aeh/det.py` before it was split into the `aeh/det/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

M-DET — the Deterministic Evaluator (detailed-design.md §3.11; issue #86).

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
  credit = max(0, |sel ∩ key| − |sel \ key|) / |key|. The row's `points`
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
- `final_points` is added NULLABLE, though the HLD §9.7 column says NOT
  NULL: SQLite cannot add a NOT NULL column without a default to a
  populated table, and orch's pre-existing run-level rows legitimately
  carry no points. The invariant is the writer's, not the schema's — det
  appends an audit row only for a scored (band, points) outcome — so
  nothing in the DDL stops a future writer from a deterministic row with
  NULL points. The gap is named here rather than papered over by this
  docstring.
- The summary's denominator: `n` counts every submission of the cohort for
  the criterion, and `correct_rate = correct / n` keeps blanks (a legitimate
  zero) AND unresolved reads in the denominator — a scanning-problem
  question reads as harder than it is, which is exactly why
  `unresolved_count` (and the report's `unresolved_rate`) are their own
  figures. The identity `correct + incorrect + unresolved = n` holds; a
  blank is inside `incorrect` band-wise, an unresolved read is in neither.
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
- That version-keying has a disclosed hazard: the store's Tier D DDL keys
  the stats `(package_version_id, criterion_id)`, not the HLD §9.7
  `(cohort_id, question_id)`. The rollup is computed over one cohort's
  rows, but a SECOND cohort whose runs name the same version overwrites the
  first's figures, and `item_stats` cannot detect that from the cohort it
  was asked about — it reads what survives. One cohort per version per
  store is the working assumption this column set leaves; re-keying is a
  schema change this story does not own.
- The audit append is per evaluation event and deliberately NOT deduplicated:
  the design's idempotency-under-redelivery constraint names
  `rederive_for_key_change` and the item-stats writes, not the audit trail —
  an append-only trail of grading events is the trail's point.
- `item_stats` resolves the cohort's single package version from its run rows
  and refuses a cohort whose runs name SEVERAL versions: the report would
  silently mix two instruments' figures, and refusing names the ambiguity
  instead (`aeh.det` makes no claim about which one a caller meant).
