# Findings register — implementation disclosures awaiting issues

Compiled 2026-09-08 by the /work-backlog loop from the adversarial-review disclosures of the
type:test suites (PRs #204, #207, #208, #209, #211, #212, #216, #218) and their state-file
DONE entries. **This document is input to `/plan-to-issues`, which owns the final issue text,
IDs, labels, and priorities** — every block below is a seed to verify against
`docs/design/detailed-design.md` and `docs/design/test-plan.md` before filing. Evidence is
as shipped on main @ 8f26b65.

Suggested labeling: defect stories are `type:story`; corpus/coverage seeds are `type:test`;
Section C items are reconciliations (issue-text edits or folds into existing issues), not new
defect stories. Every story needs the standard `Goal:` / `Traces to:` lines.

---

## A. Proposed defect stories (`type:story`)

### A1. The V2 gate never reads the declared question set, and never reads selection_state
- **Found by:** #45 (TS-16, PR #207) — probe-verified findings F1 + F2
- **Evidence:** a submission missing a declared question produces NO V2 failure (the V2 loop
  iterates stored regions, never the declared set; `_absent_regions` has no call site — dead
  code). An ambiguous selection on a declared-mcq produces NO V2 failure either (the gate only
  refuses a selection where the package declares *open*; it never reads `selection_state`; V4
  then MATCHED the submission).
- **Draft Goal:** a submission missing a declared question, or carrying an ambiguous selection
  on a declared-mcq question, fails V2 with a named gap and never reaches the V4 match.
- **Traces to:** the validation-ladder FRs (FR-INGEST-22..24 territory — pin from design);
  adjacent shipped cases TC-INGEST-23/24/26. `_absent_regions` in `src/aeh/ingest.py`.
- **Notes:** wiring `_absent_regions` in (or deleting it and writing the real check) is the
  natural vehicle; the selection half needs the gate to read `selection_state` for mcq
  declarations.

### A2. Transcription failures escape raw and leave zombie submission rows; no 3-strike loop
- **Found by:** #45 F3 (PR #207), re-found by #49 G3 (PR #212)
- **Evidence:** no transcription retry loop exists (the only re-request loop is the
  evaluative-description one); a transcription failure escapes `ingest_submission` raw,
  leaving a ZOMBIE submission row (inserted, NULL gates, `quarantined=0`) and killing the
  caller's cohort loop.
- **Draft Goal:** a transcription failure is retried to the design's strike limit, then
  quarantined with the row's gates marked — never escaping raw, never leaving a NULL-gates
  unquarantined row, never aborting the caller's cohort loop.
- **Traces to:** TC-INGEST-40 (unimplemented — no shipped test, no owning story found;
  `/plan-to-issues` should pair this fix with the test story that owns TC-INGEST-40).
  Env-knob the strike count (`HARNESS_` prefix, call-time read) per the four-seams rule.

### A3. A malformed selection mark is stored as `resolved` with `selection=NULL`
- **Found by:** #49 (TS-62, PR #212) — the C05 hole, probe-confirmed biconditional violation
- **Evidence:** `src/aeh/ingest.py:1947` — a malformed selection mark defaults to
  `resolved` with `selection=NULL`, a stored form consumers cannot distinguish from a real
  resolved mark. CT-INGEST-C05's biconditional requires malformed ⇒ NOT resolved-with-NULL.
- **Draft Goal:** a malformed selection mark is never stored as `resolved` with a NULL
  selection — it lands in the ambiguous/quarantined vocabulary the plan defines.
- **Traces to:** CT-INGEST-C05 (the contract case exists; it asserts around the hole — the
  fix lets the disclosed form go live in the suite).

### A4. `low_confidence_ocr` is unreachable and untagged regions store NULL `ocr_conf`
- **Found by:** #49 G1 + G2 (PR #212)
- **Evidence:** `low_confidence_ocr` is never produced anywhere; every untagged region —
  including the common `Student:` head — stores NULL `ocr_conf`.
- **Draft Goal:** every region row carries a real `ocr_conf` (untagged regions included), and
  the `low_confidence_ocr` outcome fires where the design says it fires.
- **Traces to:** the per-region confidence FRs from #39's story; downstream consumers in
  M-INTEG/M-AGG (see #74/#75/#96) silently receive the NULLs today.

### A5. The named aggregate emitters have no emitter in `src/`
- **Found by:** #48 F3 (PR #211) + #49 G4 (PR #212)
- **Evidence:** the report/observability surface names aggregate emitters, but no emitter in
  `src/` writes them. (Assertion side already owned by TS-55/#148; this story is the emitter.)
- **Draft Goal:** the aggregates the report names are actually emitted to their named columns
  by a single emitter path.
- **Traces to:** TS-55/#148 (consumer side, existing issue) — cross-reference, don't duplicate.

### A6. `work_unit` lacks `document_id`
- **Found by:** #49 G5 (PR #212)
- **Evidence:** the `work_unit` payload carries no `document_id`, so provenance cannot join
  the unit's submission text to its source document. (`M-ORCH`'s `WorkUnit` type — #57 —
  is the consumer surface; check design for whether the join belongs here or on the unit.)
- **Draft Goal:** every work_unit carries `document_id` so a unit is traceable to its source
  document end-to-end.
- **Traces to:** FR-ORCH/prov join fields (pin from design §3.7/§3.8); TC-PROV lineage cases.

### A7. The V4 region fence is escapable
- **Found by:** #49 G6 (PR #212) — security-adjacent
- **Evidence:** `src/aeh/ingest.py:3397-3399` — the region fence can be escaped (transcript
  content can terminate/step outside the region block). Suggest suggested priority P0.
- **Draft Goal:** submission-origin text cannot appear outside a region block in the stored
  artifact, whatever the transcript contains.
- **Traces to:** FR-INGEST-35 (demarcation); TC-INGEST-35's byte-range oracle already pins
  the invariant — this story closes the escape route it caught.

### A8. Page rasters are never persisted — crops only
- **Found by:** #48 F1 (PR #211) + #49 G7 (PR #212)
- **Evidence:** `src/aeh/ingest.py:2314/:2404` — only crops are written; the full-page
  rasters are never stored, so the design's page-image surface is empty at run time.
- **Draft Goal:** page rasters are persisted alongside crops per the design's storage form.
- **Traces to:** FR-INGEST-13 territory (rasterizer/storage surface); pin the exact form
  from design before filing.

### A9. Cohort purge is broken two ways: FK abort on unresolved_token rows, blobs never deleted
- **Found by:** #48 F8 + F2 (PR #211)
- **Evidence:** `_COHORT_PURGE_ORDER` lacks the #39 unresolved_token tables, so a cohort
  carrying them cannot be purged at all (FK abort, raw `IntegrityError`); and the purge never
  touches the blob store.
- **Draft Goal:** a cohort purge removes every cohort row (including the unresolved_token
  tables) without FK aborts and deletes the cohort's blobs, or honestly refuses with zero
  partial effects.
- **Traces to:** the purge contract (CT-STORE purge cases); `PurgePreconditionError` is the
  honest-refusal precedent shipped in #48's TC-INGEST-42.

### A10. `PdfiumRasterizer` implements no `crop`
- **Found by:** #42 follow-up disclosure (PR #204) + #48 F9 (PR #211)
- **Evidence:** the live rasterizer implements only rasterize/text_layer; `crop` exists only
  on test doubles → `AttributeError` at `src/aeh/ingest.py:2309/:2399` the moment a live
  described_graphic ingest runs.
- **Draft Goal:** the live rasterizer's `crop` matches the doubles' contract so the
  described_graphic path works end-to-end outside tests.
- **Traces to:** FR-INGEST-13 (#38's surface); the doubles in `tests/` are the contract.

### A11. The resolution floor is dead code
- **Found by:** #45 F4 (PR #207)
- **Evidence:** `HARNESS_INGEST_RESOLUTION_FLOOR` (default 150) is read by nothing; only the
  pixel ceiling is checked; 50×70 px regions ingest.
- **Draft Goal:** a region below the configured resolution floor is refused per the plan,
  with the floor knob enforced at the documented site.
- **Traces to:** the NFR covering minimum resolution (pin from design); the knob already
  exists — this story is enforcement, not plumbing.

### A12. Ambiguous filenames never refuse — they are silently ordered
- **Found by:** #45 F5 (PR #207)
- **Evidence:** identical/ambiguous filenames are silently ordered by the filename tier
  (stable sort over the caller's blob order); the plan's "ambiguous filenames" input refuses
  nowhere.
- **Draft Goal:** ambiguous filenames are refused with the order stated, never silently
  ordered.
- **Traces to:** TC-INGEST-31's order-assertion family (its shipped test discloses exactly
  this input); FR-INGEST-30 territory.

### A13. The two-candidate proposal is unreachable as designed (TC-INGEST-39)
- **Found by:** #46 F6 (PR #208)
- **Evidence:** a proposal needs a mismatch; a mismatch needs all three decisive signals
  mismatched; a second assessment lineage forces the semantic signal ABSENT (the module
  refuses to guess between two papers) → outcome capped at `uncertain` → no proposal. The
  plan's TC-INGEST-39 fixture (two ranked candidates) is unimplementable as specified.
- **Draft Goal:** EITHER the signal model gains a lineage-discriminating signal that makes
  two-candidate proposals reachable, OR the plan revises TC-INGEST-39 to the reachable form.
  `/plan-to-issues` decides defect-story vs reconciliation — it is one or the other, not both.
- **Traces to:** TC-INGEST-39; ADR-7 escalation; the v4_signals recording shipped in #46.

### A14. Minor M-INGEST disclosures (fold together or into nearby stories)
- **ResidencySlot has no waiter state** (#48 F11) — the slot exposes no way to observe a
  waiter; observability seam gap.
- **Masked-pass gate columns** (#48 F4) — see PR #211 body for the detail before filing.
- **pypdfium2 undeclared in `requirements-dev`** (#48 F10) — a one-line dependency fix;
  could ride along with any A-story touching ingest or be filed standalone.

### A15. M-SETUP: post-publish `propose_inventory` mints a second root version
- **Found by:** #56 G1 (PR #218) — pinned by the TC-SETUP-C16 evidence probe
- **Evidence:** `src/aeh/setup.py:588-599` — after `publish()`, `propose_inventory` on the
  published package mints a SECOND ROOT VERSION, contradicting `steps()`' finished report.
  The §6.2 lock itself holds (published content is immune); the violation is the new root,
  not an edit. Suggested priority P0.
- **Draft Goal:** after publish, setup offers no route that mints a new root version — the
  finished report and the surface agree.
- **Traces to:** CT-SETUP-16 (TC-SETUP-C16, shipped green with this hole disclosed);
  RISK-06's "both ends" (the catalog end is TC-PKG-C01, the setup end is this).

### A16. M-PKG: revision copy drops criterion fields
- **Found by:** #51 (PR #216) — pre-existing gap surfaced by the revision-copy work
- **Evidence:** `pkg_revision_copy_criterion` does not copy `max_points`, `scoring_model`,
  `construct_tag`, `band_count`, or the band descriptors when a revision is minted.
- **Draft Goal:** a revision child carries its parent's criteria verbatim (all criterion and
  band fields), so a revision differs from its parent only where explicitly changed.
- **Traces to:** the revision/copy FRs (FR-PKG territory); CT-SETUP-16's child-born-confirmed
  work in #50/#51 is adjacent, not overlapping.

### A17. The setup path skips the post-sanitize bound checks
- **Found by:** #47 (PR #209) — SEC-07 disclosure, note-level
- **Evidence:** post-sanitize bound checks fail closed on the submission path via the V0
  loop, but are unguarded on the setup path (`ingest_document`/`revise_document`).
- **Draft Goal:** the same post-sanitize bound checks guard the setup path — a bound-violating
  setup artifact is refused, not ingested.
- **Traces to:** SEC-07; FR-INGEST-32's setup-path failure semantics.

## B. Test-corpus seeds (`type:test`)

### B1. Adversarial corpus gaps (#47, PR #209)
- No deliberately-unremovable construct in the corpus (the verify-pass survival branch has no
  dedicated fixture; the strip-disabled cell exercises its refusal path instead).
- Incremental-update and XFA variants not built.
- Draft Goal: the corpus carries the missing construct classes so the sanitizer's survival
  and variant paths are exercised by data, not only by assertion.

## C. Reconciliations (not defect stories — text edits, folds, or owner decisions)

### C1. FR-INGEST-14 has no Phase-2 story (#44, PR #206)
The second-description pass is "P1, Phase 2" in plan and issue; `Ingestor.__init__` accepts
`high_risk_criterion_ids`/`second_model_ref` but raises. TC-INGEST-38 was deferred with
disclosure and is keyed on the story existing. `/plan-to-issues` should create the Phase-2
story (+ its `type:test` pair for TC-INGEST-38) or descope it explicitly.

### C2. TC-SETUP-13 attribution (#51/#54 discrepancy)
#51's issue text claims TC-SETUP-13; the shipped staging table assigns the confirmation cap
to #52 ("capped confirmations"). Both #51 and #56 followed the staging table. Reconcile the
issue text — a one-line edit, not a story.

### C3. TC-SETUP-12 has no owning story (#51, PR #216)
The `evidence_type` publish gate (part of TC-SETUP-12) is unowned — #51 disclosed it "stays
with its story" and no story exists. Either fold into #53's scope or create one.

### C4. Conform-tier strip-disabled declaration (flagged for #134, PR #209)
Nothing declares the conform tier must run with STRIP disabled — at the default knob the 8
constructs strip and transcribe and the tier's own quarantine-at-V0 assertion would fail for
exactly the manifest's must-quarantine fixtures. Either the tier sets the knob or the
manifest declares the world. Fold into #134 when it is worked.

### C5. Tier-P-before-`aeh.pkg`-import footgun (#46, PR #208)
A Tier P file opened before `aeh.pkg` is imported builds with the BASE schema only; the
failure surfaces later as "no such column: parent_version_id". At minimum a convention line
in CLAUDE.md/README ("import aeh.pkg first"); optionally an import-order guard.

## D. Already owned — do not duplicate

- E4 policy swap → #62/#59 · PERF-02 comparison → #146 (TS-53) · TC-STATS-13 consumer half →
  #117/#120 · aggregate assertion side → TS-55/#148 · TC-INGEST-38's Phase-2 dependency → C1
  above · TC-ORCH pending coverage → #63 (owns TC-ORCH-01/02/03/34 + C01..C03 against #57).

---

*Register maintained locally; findings live permanently in the PR bodies (#204, #207, #208,
#209, #211, #212, #216, #218) and `.claude/backlog/work-backlog-state.md`.*
