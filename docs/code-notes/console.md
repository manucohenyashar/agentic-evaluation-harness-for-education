# `aeh.console`: design notes

These notes were the docstring of `src/aeh/console.py` before it was split into the `aeh/console/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

`M-CONSOLE` — the teacher/operator console as a read view over the §9 stores plus a
small control surface (HLD §11; issues #122 and #126).

#122 builds the process: the stateless `ConsoleApp` (every view a query, every change a
row the orchestrator reads on its own schedule — §11.1, §11.8), the fifteen-action control
surface (`FR-CONSOLE-32`), the upload handler that streams and dispatches (`FR-CONSOLE-04`,
`NFR-CONSOLE-06`), the run monitor that polls the ledger and writes nothing (`CT-CONSOLE-19`),
the loopback refusal (`FR-CONSOLE-05`), the four observability metrics (§3.19) and the audit
surface that never presents an actor string as an identity (`CT-CONSOLE-23`). #126 builds
S1 Packages (`FR-CONSOLE-26`: a package never administered to this population renders *no
validation data for this population*, never a borrowed figure), S2 Upload (PDF only, several
files per logical document, the assembled page order shown **before** transcription starts,
calibration papers stored for a later version — never a promise of ambiguity discovery), S6
Preflight (the validation ladder per gate, the `FR-INGEST-28` cohort breaker withholding run
start, and the deliberate note that outstanding quarantine items do **not** withhold it —
quarantine is the operator's parallel workstream, §7.7) and S8 Quarantine (never
auto-reassigns; the image crop for an unreadable mark; closing as unresolvable marks criteria
MISSING and grade INCOMPLETE — never zero — the console face of `FR-GRADE-07`/`-08`).

## What is real, and what is deliberately absent

Design §3.19 declares no Python interface for this module, so the surface here is the one
settled in `tests/support/console_vocabulary.py` and
`tests/support/console_security_vocabulary.py`, disclosed there and reproduced here.

- **Every render is a read.** The console holds no pipeline state; a view derives from the
  store (or from nothing). Rendering never writes — asserted per screen by the complement
  sweep (`TC-CONSOLE-C02`). On the suite's `StoreSpy` (a write-audit double with no
  filesystem), reads are recorded against the spy's tier handles so the read path stays
  observable; on a real store, reads go through the tier handles at the same seam `M-GRADE`
  and `M-DET` use — and a render never *creates* a tier file: a tier that does not exist yet
  is rendered as the empties it honestly has.
- **Every control action writes rows, or says honestly why it wrote none.** `perform` writes
  one row per declared effect, whose payload names its table and carries only the fields
  §11.8 declares for that action — the contract the dynamic sweep checks per write against
  the union. On the spy the payload dict arrives at `enqueue_write` with its fields attached;
  on a real store each action writes the row the schema actually admits, in that row's own
  tier's transaction, never nested inside another tier's: `pause/resume` as a `run_control`
  row on the run's cohort ledger — exactly where `Orchestrator` writes its own control rows
  (whose CHECK admits `pause` and `resume` only), applied on its next read (CT-ORCH-13);
  S8's close-as-unresolvable as the operator's `submission` update (diagnosis `incomplete`,
  park flag cleared — never an automatic reassignment, and the MISSING-criteria /
  INCOMPLETE-grade consequence is `M-GRADE`'s landed missing-criteria rule). The other
  landed domain effects delegate to `M-GRADE` (`GradingService.finalize_batch`) and `M-STORE`
  (`purge_cohort`); an action with neither a schema-admitted row nor a landed owner reports
  `dispatched=False` with the deferral named — the console claims nothing it did not do.
- **Replay and staleness are refused into safety.** A replay through any route
  (`double_click`, `retried_request`, `back_navigation`) reports the already-settled rows and
  writes nothing (`FR-CONSOLE-02`: no additional row, not merely no exception); an action held
  mid-flight and released into moved state is refused with `refresh_required` and writes
  nothing (§3.19: idempotent or refused with a refresh, never partial).
- **The refusal keys on the deployment profile, first.** `serve_console`/`start_console`
  refuse `cloud-hosted` before any bind is inspected, then refuse any non-loopback bind
  (`FR-CONSOLE-05`) — the order matters, because a routable bind must not be able to argue
  with the profile refusal (`CT-CONSOLE-20`). A started server is ONE in-process
  `ThreadingHTTPServer` on the configured loopback socket (ADR-17): `GET` renders through
  `ConsoleApp.render`, `POST /actions/<slug>` performs a declared control action, `POST
  /upload` hands the body to `upload_scans`, every unknown route is a 404, and every response
  carries `Cache-Control: no-store`. There is no child process: runs execute in-process and
  the ledger makes them resumable, so a killed console loses only its memory and `recover`
  picks the run up (`NFR-CONSOLE-03`, `NFR-CONSOLE-08`).
- **The upload never materialises the batch, and it is PDF-only.** `upload_scans` walks the
  declared size in chunks (`HARNESS_CONSOLE_UPLOAD_CHUNK_BYTES`, default 4 MiB), digests each
  chunk, and hands the digests to the blob store when one is present; nothing of the declared
  size is ever allocated, which is what the ratio budget (`NFR-CONSOLE-06`) and the 1-second
  handler budget (`FR-CONSOLE-04`) measure. The S2 format rule (`FR-CONSOLE-13`) is enforced
  where the format is knowable — a stream's first chunk must carry the `%PDF-` magic, a
  declared filename must end `.pdf` — and the handler states plainly when it was given
  nothing to check.
- **The review queue renders the invariants, in order (§11.6's 8-10, #124).** The header
  states all three figures — flagged, shown and **left provisional** (`FR-CONSOLE-13`), the
  third as data attributes `review_queue_header` reads back and as visible text, because a
  figure computed but not printed has rendered nothing. Group actions render above per-item
  ones (`FR-CONSOLE-14`), and every item renders narrative before its mark with the narrative
  carrying no numeral-bearing or overall-quality claim (`FR-CONSOLE-15` — the order is the
  affordance: a narrative shown after the mark is read as justification rather than evidence).
  The renderer is polymorphic: over this module's `ConsoleApp` (the route's own view) and over
  `M-REVIEW`'s `ReviewService` (whose built queue it renders — the consumer half of
  `CT-REVIEW-04`, where the service's own three figures are rendered rather than recomputed).
  Over an empty store the screen renders its standing shape with the honest figures (zero) —
  the structure is what the invariants assert on, and the counts are the store's.
- **The blind flow is unreachable, not hidden (`FR-CONSOLE-16`, #124).** `blind_flow` and
  `blind_flow_requests` are the flow's declared transport face: the query plan reads the
  §3.15 pair (`submission`, `criterion`) plus the draw (`blind_sample`) and the rubric's
  band descriptors (`criterion_band` — package data), and never names a system-output table
  or column (`criterion_score`, `submission_grade`, the verdict and confidence columns, the
  queued review rows). `M-REVIEW`'s `BlindSession` carries the same guarantee as a property
  of the type; the payloads here hold identity fields and the fixed band scale, so a leak is
  not merely hidden but absent (`CT-REVIEW-09` step 3 lives on this surface, not `M-REVIEW`'s).
- **Invariants 15–21 (issue #125).** The blind reservation is read — and subtracted —
  before the ranking query runs (`review_queue`; the order is visible in the query log,
  `FR-CONSOLE-19`). Every grade-bearing screen renders the grade beside an editable band
  control (`_band_control`; `FR-CONSOLE-20`, invariant 16) and a provenance footer that
  carries the values (`CT-CONSOLE-10`). An amendment (`amend_finalized_grade`) preserves
  the delivered `finalized_at` and writes a new revision on an append-only history whose
  superseded revisions stay readable (`grade_revision`; `FR-CONSOLE-21`). A review window
  (`set_review_window`) delays finalization — the batch settles with `finalized_at`
  unset, marked provisional, and exports normally (`FR-CONSOLE-22`). The export gate
  (`export_package`/`ProvenanceRefused`) is a reachable screen (S14) whose outcome is
  written to the validation record (`FR-CONSOLE-23`). An administration with no blind
  labels renders `render_agreement_block`'s absence sentence — never a zero, never a
  blank, never a prior administration's figure in that position (`FR-CONSOLE-24`).
  `touchpoint_surface` enumerates §7.9's twelve rows, one present-and-unavailable naming
  its version (`FR-CONSOLE-25`).
- **The limitation is stated, not latent (`NFR-CONSOLE-07`, #127).** Every page the shell
  renders carries the English-and-left-to-right statement (`_LIMITATION_SECTION`) — a
  deliberate limitation named in the UI, never an omission discovered in the field, and
  `CT-CONSOLE-24`'s non-promise is honest on every route rather than on one. The
  student-text render for the correction flow (`render_submission_text`) rides the same
  statement, so a non-English or RTL submission degrades **visibly** — named on the page —
  never silently (`TC-CONSOLE-C24`).
- **The grade render carries its coverage, boundary language and criterion figures
  (`render_grade_coverage`, #107's carry-forward landed here).** A grade shown without its
  five coverage counters is a stronger claim than the system is making (`CT-GRADE-04`); a
  null grade never reads as "fine" (`CT-GRADE-05`); a deterministic criterion's withheld
  agreement figure presents as not-applicable, never as a zero that reads as perfect
  agreement (`CT-GRADE-13`); and a boundary-flagged grade reads as "could cross", never as
  a likelihood (`CT-GRADE-19`). The rollup's segments render the same presentation from
  their batch read, so the single-submission renderer and the screen cannot drift into two
  consoles.
- **S12's two halves (#127).** The answer-key correction action (`correct an answer key
  after a run`) writes a new key version (`FR-PKG-18`'s flow — M-PKG's `create_version`
  copies the parent, the correction lands in the child), re-derives the affected
  deterministic scores **by lookup** (M-DET's `rederive_for_key_change`, whose
  `panel_units_enqueued` is a declared zero — a lookup, never a re-judgement, `FR-DET-08`),
  re-runs the grade policy (M-GRADE's `compute_all` over the re-derived rows), and renders
  the updated grades immediately. The re-point of the run row to the corrected version is
  the correction flow's own re-baseline step — TC-GRADE-12's disclosed stand-in: the run
  row is `M-ORCH`'s alone to write and no orchestrator API exists yet, so the console
  performs it inside the action and names it in the outcome detail; when M-ORCH ships a
  re-point surface, this call site becomes that call. The rubric-findings block renders
  M-GRADE's `rollup_findings` — the criteria the escalation circuit breaker marked
  `ungradeable_by_panel` and the ones whose review queue rows exhausted the budget
  (`FR-CONSOLE-31`, `FR-ORCH-13`, `FR-REVIEW-04`) — beside the correction control, so the
  findings are visible to the person who can act on them.
- **`run_pipeline_for_test`** is the headless driver (`CT-CONSOLE-01`) with two disclosures:
  it pins the fixture's rubric version by inserting the version row directly (the same column
  shape `M-PKG`'s own first-version insert uses — `PackageCatalog.create_version` mints
  unguessable ids, and the driver needs `pkg-v1-r0`), and it overrides the orchestrator's
  package-id derivation for the same reason. Neither bypass reaches a shipped path.

## The four seams (CLAUDE.md)

1. **Headless driver** — `run_pipeline_for_test` runs the pipeline end-to-end from code and
   returns a structured result with a per-stage trace; `build_console().render(route)` renders
   any screen headlessly. Nothing requires a served process.
2. **Deterministic transport** — the console performs no inference at all (`CT-CONSOLE-01`),
   so it adds no egress point; the provider it is handed is held, never called.
3. **Env-gated knobs** — `CONSOLE_BIND`, `CONSOLE_PORT`, `CONSOLE_POLL_INTERVAL_MS` are the
   declared knobs, plus `HARNESS_CONSOLE_UPLOAD_PROBE_BYTES` (test vocabulary),
   `HARNESS_CONSOLE_UPLOAD_CHUNK_BYTES` (this module) for the upload walk,
   `HARNESS_CONSOLE_BLIND_RESERVE_MINUTES` for the queue's blind reservation and
   `HARNESS_CONSOLE_HEADLESS_BATCH` for the headless driver's batch size — all read at
   call time.
4. **Stage-level observability** — `telemetry()` carries the four declared metrics;
   `RenderedPage.queries` records what each render read; outcomes carry per-stage detail.

Store opens in this process require the full tier migration chain, so the ten contributor
imports stand at the top of this file — the same convention `tests/conftest.py` records
(`IncompleteMigrationChainError`, #234).

## Details moved out of the code

These notes were the longer parts of docstrings in `aeh.console`. Each section is named after the file and the function or class it describes.

### driver.py: run_pipeline_for_test

It never imports M-CALIB, which shows that calibration is not needed to deliver grades
(CT-CALIB-01, RISK-11).

Two fixture disclosures, both deliberate (see `docs/code-notes/console.md`): the rubric
version is pinned by inserting the version row directly, in the column shape `M-PKG`'s
own first-version insert uses, because `PackageCatalog.create_version` mints ids no
caller can pin; and the orchestrator's package-id derivation is overridden for the
same reason, because the default derives the package id from the version id and the
pinned id carries no `@`.

`cohort_id` (`#118`'s export seam) names the cohort the driver seeds, runs and reads
back — the fixed `_DRIVER_COHORT` when omitted, as every pre-existing caller sees. A
driver that could only ever run one cohort could not demonstrate the property the
seam exists for: a statistics promotion of a *named* administration. The seeding is
idempotent for that seam's differential (`CT-STATS-C17` times a run against a
baseline run **on the same data directory**): a package version already seeded is
seed-present, not a collision, and a run id the caller did not pin is derived from
the cohort — two administrations are two runs, and the run table's primary key is
the run id.

`alongside` runs a callable **concurrently with the scoring run**, on a daemon thread
started just before the deterministic pass and joined before the store closes; its
first exception is re-raised on the caller's thread after the join, so a failed
concurrent export cannot pass as a successful run. This is what makes the seam's
claim checkable — that an analytical export running *during* scoring neither waits
the pipeline on a lock (`PipelineOutcome.lock_waits` stays 0) nor moves its wall
clock — instead of asserting it about an export that ran afterwards.

### key_correction.py: KeyCorrectionMixin._correct_answer_key

1. the run row names the cohort, package and version the grades were produced
   against. The GRAIN pre-checks run before any write — a re-derivation is
   cohort-grain (M-DET re-derives the criterion's scores for the whole cohort and
   attributes its audit rows to the cohort's NEWEST run), so a cohort whose runs
   name several packages, or a correction naming a run that is not that newest
   one, refuses honestly and writes nothing, rather than minting a version and
   then refusing (CT-CONSOLE-03's never-partially-applied rule) or filing the
   trail under a run whose grades it did not supersede. A criterion the version
   does not carry, a criterion that is not a multiple-choice one (its scores are
   panel outputs, not key lookups), or a key already equal to the stored one also
   refuses honestly and writes nothing;
2. the correction is a NEW package version (`FR-PKG-18`): the parent is
   copied verbatim, the corrected key lands on the unlocked child, and the
   parent — and every audit record that resolves to it — stays exact;
3. `M-DET` re-derives the affected deterministic scores BY LOOKUP against the
   corrected key (`rederive_for_key_change`) — no panel work anywhere: the
   report's `panel_units_enqueued` is a declared zero, and the detail below
   prints it, because a correction that quietly asked a panel to re-judge
   would be the exact violation the clause forbids;
4. the run re-points to the corrected version and M-GRADE re-runs the grade
   policy over the run (`compute_all`), so the settled grades are re-derived
   from the corrected scores.

The run re-point is TC-GRADE-12's disclosed stand-in: M-ORCH owns the run row
and no landed API re-points it, so the console writes the one column the
correction owes — and retires the site to M-ORCH's call when that lands.
