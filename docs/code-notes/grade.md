# `aeh.grade`: design notes

These notes were the docstring of `src/aeh/grade.py` before it was split into the `aeh/grade/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

M-GRADE — automatic grade computation, policy application, boundaries and coverage.

Design §3.14 (`FR-GRADE-01`..`FR-GRADE-17`, `NFR-GRADE-01`/`02`). The module's one job:
every submission in a run leaves each `compute_all` pass with a `submission_grade` row —
no per-student teacher action anywhere in the path (`FR-GRADE-01`, `NFR-SYS-04`) —
computed from the package's **versioned** policy (`aeh.pkg.GradePolicy`, the closed rule
vocabulary `FR-PKG-14` validates at construction), resolved against the package's
`grade_boundary` table, and carrying the five-counter coverage record (`FR-GRADE-04`)
plus the boundary-risk fields (`FR-GRADE-05`). Recomputation from the stored criterion
scores plus the recorded policy version reproduces the grade exactly (`FR-GRADE-13`):
the computation is pure arithmetic over the ledger, never a judgment.

**NFR-GRADE-01 is a hard boundary.** Nothing here calls M-PROV, and there is no model
boundary at all in this module: every input is a stored row and every output is a
computed figure. That is also the module's deterministic-transport seam (CLAUDE.md
seam 2, adapted): the external dependency surface is empty by construction, so the
module runs with no network, no provider and no fixtures — determinism is structural,
not configured.

**The pinned readings** (each one a place the design left a boundary implicit, pinned
by the shipped cases rather than invented here):

- Rounding mode `nearest` at exactly .5 is **half-up** (`TC-GRADE-03`: 2.5 -> 3.0 and
  3.5 -> 4.0 — the pair that discriminates half-up from Python's half-even `round()`).
  The rounding runs in `decimal` on the figure-as-written, so 2.675 rounds on its
  decimal representation, not on float noise.
- A gate is **inclusive at its threshold** (`TC-GRADE-03`): a criterion scoring exactly
  `GateRule.minimum` stands; one notch below refuses. A gated criterion with **no row**
  refuses too — absence is not a zero, it is an unmet gate.
- Boundary floors are **inclusive** — the shipped `grade_boundary` DDL's own rule
  (aeh/pkg.py migration 5): the grade with the greatest floor <= the scaled score
  resolves. A package with no table yields a NULL grade, never an invented band
  (`FR-GRADE-03`, the NoValidationData honesty rule).
- `boundary_at_risk` asks whether the provisional criteria's plausible range could
  **move the student across** a boundary (`FR-GRADE-05`), so the flag needs a range
  of positive width: a zero-width range — no provisional criteria, or every
  provisional interval collapsed to nothing — cannot move anyone, and a settled
  grade sitting exactly on a floor is settled, not at risk (#102's degenerate limb
  of `TC-GRADE-06`). The range-edge predicate stays the inclusive
  floor-membership check on `[score_low, score_high]`; M-PKG's
  `distance_to_nearest_boundary` (`FR-PKG-16`) is a point-proximity signal for
  M-REVIEW's ranking and is deliberately NOT this predicate — reformulated as
  distance-at-midpoint it under-flags on ulp cases (a floor at the range's very
  edge), and the boundary table itself is the package's, read through
  `select_boundaries` (`CT-PKG-10`'s single-representation rule), never re-derived.
- The coverage classes map from `criterion_score.routing` (`CT-AGG-06`'s column):
  `auto` -> `criteria_auto`; `reviewed` -> `criteria_reviewed`; `provisional` and
  `queued` -> `criteria_provisional` (both are unsettled-acceptance judgment states,
  and both are scored inputs); `triage`, an unrecognized routing, or **no row at all**
  -> `criteria_missing`. `incomplete` is caused exclusively by ingestion failure
  (`CT-GRADE-08`), which is exactly the population `triage` and the absent row name.
- A missing criterion is a **row's absence** — never a state, never a value, never a
  substituted figure (`FR-GRADE-08`, RISK-03/RISK-11). The total is computed from the
  present criteria and only them; the absence is the coverage record's problem.

**Provenance columns are content refs, not foreign keys** (the `TC-GRADE-12`
reconciliation, recorded here because it is the least obvious shape in the schema):

- `policy_version` is the SHA-256 of the **effective policy's canonical JSON** — the
  `GradePolicy` object `grade_policy()` returns, default included, review window
  included. NOT the `package_version_id`: a policy change and a key correction are both
  new package versions (`FR-PKG-18`'s flow), and `create_version` copies the policy
  forward — so a version id would change the recorded version on revisions where
  nothing about the policy changed, and two grades under the identical default policy
  on two versions would disagree. The content hash says which *policy* produced the
  grade, which is what the column names.
- `answer_key_ref` is the SHA-256 of the version's **answer-key content** — every
  criterion's stored key, ordered, canonical JSON. Same reasoning, pinned by
  `TC-GRADE-12`'s third limb: revision 3 (a policy change on a version whose keys were
  copied from revision 2's version) must record the SAME key as revision 2 — the keys
  did not change — while the package version id did. It mirrors det.py's
  `answer_key_ref` in spirit (the version AND the key bytes in one resolvable string)
  but hashes the content rather than naming the version, because the copy-forward flow
  makes the version id the wrong identity for "which key produced this".

**Idempotence and revisions** (`NFR-GRADE-05`, ADR-9): a new revision is written only
when the recomputed **content** differs from the current revision's — content being the
total, the resolved grade, the five coverage counters, the boundary-risk triple and the
missing-criteria list. Provenance columns are recorded per revision but are NOT part of
the change test: a re-run under a new package version whose policy and keys were copied
forward unchanged reproduces the same content and writes nothing, which is what keeps
an unaffected submission at revision 1 through a correction that touched only another
submission (`TC-GRADE-12`'s "affected grades recomputed" clause, read in both
directions). An amendment is part of the content a pass must reproduce: the recorded
`amendments` map is replayed over the stored scores before the comparison, so a
recomputed revision can never "revert" a teacher's override (the override lives only
on the grade row — `CT-GRADE-14`) — an unchanged re-run of an amended submission
writes nothing, and a changed one carries the amendment record into the new revision.
Each revision also measures its own review window: a correction re-opens review for
content the teacher has not seen, rather than minting it pre-settled on the prior
issuance's lapsed anchor. **Finalization is not a recomputation**: the window lapse
and the run completion move the CURRENT revision's state in place (`provisional` ->
`final`, with `finalized_at` stamped) and never mint a revision — the state model's
arrow is a settlement, not a new computation.

**The state model** (§3.14): `provisional` at issuance; `final` on window lapse or run
completion — including on the service's own `compute_all` pass (`FR-GRADE-10`: no
configuration waits for a teacher action; ADR-3's null window means completion is the
only path); `incomplete` only while `criteria_missing > 0`, and never settled — an
incomplete grade is not a deliverable awaiting a window, it is a missing input awaiting
an operator, and each missing criterion is routed to `review_queue` with a reason that
names the action (the pinned reading: **rescan** — the wording is this module's
interpretation, disclosed in `test_incomplete_and_routing.py`'s docstring).

**The four seams** (CLAUDE.md):

1. **Headless driver** — `open_grade(store)` returns the service; `compute_all`,
   `finalize_batch` and `export` run end-to-end from code and return structured
   results (`GradeReport`, `FinalizationRecord`, a written `Path`). No console step
   exists in any path (`CT-CONSOLE-01`).
2. **Deterministic transport** — there is no external dependency to transport: every
   input is a store row and every output is arithmetic (`NFR-GRADE-01`: nothing may
   call M-PROV). See the paragraph above.
3. **Env-gated knobs** — `export_dir()` resolves `HARNESS_GRADE_EXPORT_DIR`, then the
   design §3.14 configuration name `GRADE_EXPORT_DIR`, then a default under the
   platform temp directory, **at call time, never at import** (the pkg.py
   `SIGNING_KEY_ENV` precedent). The review window itself is not an environment
   constant — it is per-package data (`ADR-3`'s column), which is a stronger
   adjustment story than a knob.
4. **Stage-level observability** — the coverage record IS the observability
   (`FR-CONSOLE-09`, `FR-GRADE-16`): every grade carries the five counters, the
   boundary-risk triple and the missing-criteria names next to its status, so a grade
   that says `incomplete` also says *what* it is missing and *where the operator goes*;
   `GradeReport` restates the batch's per-state counts next to its computed count.
   #103 adds the durable half: `record_grade_signals(run_id)` flushes the CT-GRADE-18
   signal set (grades by state, the `boundary_at_risk` count, the coverage
   distribution, the finalization paths, the amendment count) into the `run_metrics`
   EAV rows every other stage rides, and `evaluate_grade_alerts(run_id)` evaluates the
   outstanding-`incomplete` alert (`FR-GRADE-07`'s operator routing, actionable) plus
   the stale-provisional one over the same ledger.

**`class_rollup` and `cohort_with_mixed_revisions`** are the module-level seams
`CT-CALIB-09`'s consumer half calls: the rollup segments a cohort's current grades by
the rubric version that produced them (`package_version_id` on the grade row) and
annotates the versions covered — R0-scored and R1-scored results never share an
unannotated figure (`RISK-06`). The fixture helper builds the mixed-revision cohort and
registers it, keyed by cohort id, for the rollup to find; it is a fixture seam living on
the module because the case names the module as its surface.

**The rollup's statistics, separation and findings** (#104, `FR-GRADE-14`/`15`/`16`,
`CT-GRADE-12`/`13`): `criterion_band_figures(scores, band_order)` is the per-criterion
band-figure accessor — histogram, entropy in **nats** (the base is a convention the
design does not pin; the committed reference `0.75·ln 4` in `TC-GRADE-14` pins natural
log), and the interior rate against the declared band order — with entropy and
interior rate **null for deterministic criteria** (`CT-GRADE-13`'s data clause; a zero
would read as "no variation", which is a different claim from "the figure does not
apply"). A criterion is deterministic here when every band its score rows carry is one
of M-DET's result values (`correct` / `incorrect`, plus the never-scored marker
`unresolved`) — the bands are the deterministic-criterion marker the accessor has when
no package is in hand. The rollup classifies by the package's declared
`evaluation_mode` (#369: the column exists, and the old `kind='mcq'` reading of it is
retired — a judged multiple-choice criterion rolls into the judged block) and
trusts that verdict for the figures: its judged block computes real entropy and a
real interior rate for every criterion the package declared judged — even one whose
rubric names its bands like M-DET's (a judged pass/fail rubric may) — and falls
back to the band reading only for rows no declared criterion owns. (The pure
accessor, which holds no package, keeps the band reading as its only contract;
that is the pinned seam the unit case tests.)
`separated_rollup(run_id, store)` is the rollup with the separation built in: a judged
block and a deterministic block, each its own population and its own figures, and —
deliberately — **no** field anywhere on the record that could carry a combined figure
across the two (`FR-GRADE-15`'s refusal is structural, not a comment).
`rollup_findings(run_id, store)` surfaces the criteria the system could not apply: the
ones the escalation circuit breaker marked `ungradeable_by_panel` (the mark M-AGG
writes when the breaker trips, `FR-ORCH-13`/`CT-AGG-07`) and the ones whose review
queue rows exhausted the review budget (the residual `FR-REVIEW-04` leaves behind;
`review_queue` has no status column, so the exhaustion rides the reason text and is
matched **in Python** — a SQL `LIKE` is `TC-STORE-15`/C08's banned search shape) —
each naming the count of affected students.
`export_grade_artifacts(run_id, revision, dest)` is the school-facing export mapping
(`TC-REG-03`'s producer): one CSV of marks and one PDF per student, written into
`dest`; called without a store it materializes the module's reference cohort (the
`cohort_with_mixed_revisions` registry precedent) so the golden baselines are
reproducible from the shipped code alone. The per-student PDF is written by a minimal
deterministic PDF emitter — no timestamps, no producer string, nothing volatile — so
the per-student documents are byte-reproducible and the baseline's normalization has
nothing to strip.

**The append-only ledger and the amendment audit** (#103, `FR-GRADE-12`, `FR-DET-10`,
`TC-GRADE-23`): a delivered revision is never mutated in place — correction paths mint
revision n+1, and the schema enforces what the code promises. Migration 19 (Cohort)
adds ADR-9's `superseded_at` (the stamp a demotion leaves on the revision that lost the
current flag) and installs a `BEFORE UPDATE` trigger refusing every CONTENT-column
change on `submission_grade`; the lifecycle columns (`is_current`, `state`,
`finalized_at`, `computed_at`, `superseded_at`) stay writable because settlement and
supersession are the ledger's own bookkeeping, not edits of a delivered grade. Durable
migration 7 gives `audit_record` the blanket append-only pair (`aeh.pkg`'s
elicitation-history precedent) — rows are inserted, never updated or deleted.
`enforce_ledger_append_only()` is the enforcement's single home and inspectable form:
the migrations slice the same statement objects the function returns, so they cannot
drift apart. Every `amend()` call — minting or not — also appends one `audit_record`
row to Tier D after the cohort revision commits (separate tier files, so two
transactions; `decided_by` the actor, `evaluation_mode='judged'`, the criterion-level
detail in `profile_summary`), while the `amendments` JSON on the grade row stays the
revision-local record the recomputation replays. And the no-op rule: an amendment
whose application reproduces the current revision's content exactly mints nothing —
the same `_content_of`/`_stored_content` comparison the compute passes honor, so
NFR-GRADE-05's idempotence sentence holds for the manual path too; the review is still
real (a fully-scored no-op settles the current revision `final` in place) and the
audit row still records the call.

**Carried forward** (design-declared, unpinned by the shipped cases, and so left
minimal rather than invented): `criterion_stats` — §3.14 names this module the sole
writer of `submission_grade` and `criterion_stats`, but no `criterion_stats` table
exists in the shipped schema and no shipped case reads one; the table and its writer
land with the statistics story that consumes them (#118's M-STATS surface) rather than
invented here. The figures above are computed at read time over the stored
criterion-score rows; persisting them into Tier D is that landing's schema change, not
this one's (#104 pins the figures and the rollup surfaces, no migration).

## Details moved out of the code

These notes were the longer parts of docstrings in `aeh.grade`. Each section is named after the file and the function or class it describes.

### amendments.py: AmendmentMixin.amend

The overrides are stored on the grade row (`amendments`), which keeps the revision
recomputable (FR-GRADE-13): a later pass applies the stored overrides before comparing, so
an unchanged re-run reproduces the amended grade instead of undoing it.

The settlement follows the state model, not the action: an amendment of a
grade with all inputs present settles `final` (the teacher just reviewed it),
preserving the prior revision's `finalized_at`; one whose inputs are still
missing stays `incomplete` — an edit never launders an absence into a
deliverable. An edit naming a criterion with no stored score row is refused,
naming it: recording an edit that applied nowhere would claim a change that
never happened, and a missing input is the operator routing's to fill.

**No new revision without a change** (`NFR-GRADE-05`, TC-GRADE-13's no-op
variant): an edit whose application reproduces the current revision's content
EXACTLY — re-entering the points a revision already carries — writes no
revision. The comparison is the compute passes' own change-detection tuple, so
"changed" means the same thing here as everywhere else in the module. The
review the call records is still real: a no-op amendment settles the current
revision `final` in place when the state model pressures it (the teacher
reviewed it), and the call is appended to the audit trail either way — the
ledger records content changes, the audit trail records human actions.

Every amendment call — minting or not — also appends one `audit_record` row to
Tier D (the durable form of the who/what/when/why record; the `amendments` JSON
on the grade row stays the revision-local record the recomputation replays):
one row per call, `decided_by` the actor, `evaluation_mode='judged'` (a
teacher's decision, never a derivation), the full criterion-level detail
canonical-JSON in `profile_summary`. The write follows the cohort
transaction's commit — tiers are separate files, so the two writes cannot share
one transaction, and an audit row is never written for a revision that failed
to land.

### policy.py: apply_policy

The rule vocabulary, exactly as shipped on `aeh.pkg.GradePolicy`:

- `weighted_sum` — each criterion's points multiplied by its declared weight
  (a criterion with no declared weight weighs 1.0), summed. With no weights at all
  this is the plain sum (`FR-SETUP-12`'s default).
- `best_k_of_n` — the k highest points, summed. Ties at the cut are broken by
  criterion id for determinism; because tied values are equal, the total is
  invariant under every arrival order either way (`TC-GRADE-03`).
- `drop_lowest_n` — the n lowest points dropped before summing (scored out, never
  scored as zero).
- `gate` — the named criterion must reach `minimum`, inclusively (`TC-GRADE-03`'s
  pinned reading). A criterion with no row refuses the gate: absence is not a zero.
  A refusal is a `None` total, never an exception (`CT-GRADE-02`).
- `scale` — the combined total multiplied by the factor, after combination.
- `rounding` — applied last: `nearest` is HALF-UP at exactly .5 (`TC-GRADE-03`'s
  pinned reading — Python's `round()` is half-even and would fail the case),
  `up` rounds away from zero's floor, `down` truncates.

Sums run through `math.fsum` (exactly rounded, therefore order-independent over
criteria — `TC-GRADE-21`'s permutation limb reads the same total in every order).

The result also surfaces the population's breaker-refused criteria in
`panel_refused` (`CT-AGG-07`): a criterion the escalation breaker marked
`ungradeable_by_panel` contributes its stored figure — CT-ORCH-16 leaves it scored
single-judge provisional — and is named in the result, so the grade's presentation
of the breaker-refused row differs from its presentation of the identical
ordinary-provisional row.
