## TC-E2E — the three end-to-end journeys (issue #144, TS-51, rung 4)

The assembled system, exercised journey-scale with no doubles at module
boundaries. The only double anywhere is the model boundary:
`RecordedFixtureProvider` in its shipped regeneration-then-replay shape.

### What landed

- **`tests/support/e2e_world.py`** — the assembled-system world all three
  journeys share: F-SYNTH cohorts synthesized into real ingested documents
  (real gateway, real 4-page PDFs at the 72 DPI floor, real sanitizer and
  rasterizer), the PKG-REF catalog built through the real M-PKG writer
  (GradePolicy attached before publication, ADR-3), a real store across the
  full migration chain, the run lifecycle through the real M-ORCH lease clock.
- **TC-E2E-01** (`tests/e2e/test_e2e_01_package_setup.py`) — the setup
  journey: four PDFs to a locked package. Blocking-gate surface, the whole
  M-SETUP chain, publication and the §6.2 lock.
- **TC-E2E-02** (`tests/e2e/test_e2e_02_overnight_run.py`) — the overnight
  run: 350 submissions in, 341 finalized grades out, zero teacher action.
  Happy path plus three injury variants: SIGKILL mid-run and the resume
  reproduces the untouched control's result set exactly;
  provider-unavailable pauses the run on the same backend and resumes;
  criterion-breaker halts escalation, marks `ungradeable_by_panel`, and the
  run still completes. The 350-submission result set is frozen as
  `fixtures/baselines/TC-E2E-02/result-set.json` under §6.9's governance.
- **TC-E2E-03** (`tests/e2e/test_e2e_03_review_morning.py`) — the review
  morning: queue triage, per-item and group decisions on real `ReviewItem`s,
  a whole-draw blind sitting, the honest residual, and the promote that
  refuses a blended headline over a multi-criterion population
  (CT-STATS-04/06: `agreement_kappa` is `None`).

### The real bug the journey found (and the fix that landed)

`ccaadee` — a really-ingested submission's document row carried a
`content_hash` with no blob behind it: M-INGEST writes the Markdown its hash
covers into the document row's markdown column, while the blob store's
declared inventory (FR-STORE-06) is source PDFs, page rasters and image
crops — so M-EXTRACT's blob-store read hit an empty transcript for every
journey-scale submission while the smoke test's seeded form (blob-first)
passed. The rule M-INTEG established settles it: the markdown column is
canonical (FR-INGEST-04), the content-addressed blob is the fallback, and
the hash must equal the bytes actually read either way (CT-INGEST-02),
failing closed otherwise. `extract.document_bytes` is now the shared
resolver used by both the assemble path and the worker's process path. The
journey found this within its first honest run at scale — the smoke test's
seeded shape masked it.

### The recovery this PR carries

Two agents died mid-flight on this issue (an upstream credit outage, then
context exhaustion); the branch is their committed work completed by the
dispatcher. The substantive completion:
- **variant (b) fix** — the provider-unavailable variant resumed on the SAME
  orchestrator; its mid-life LeaseClock read the aborted drive's in-flight
  leases as unexpired, the sweep reclaimed nothing, and the stranded units
  were invisible to every later drive (leased != pending) — their cells
  never reached the walk and `aggregate` raised `EmptyVerdictsError`. The
  operator restarts the worker after the outage: `reattach()` before the
  sweep, per the world's own restart rule.
- **the baseline freeze** — env-guarded (`AEH_E2E_CAPTURE_BASELINE`) inside
  `_assert_matches_baseline` so an ordinary run can never rewrite the
  baseline as a side effect; the capture ran once, was inspected, and is
  committed in this PR (`fixtures/baselines/TC-E2E-02/result-set.json`,
  1064 KB: 350 submissions, 341 finals, per-grade five-counter records,
  deterministic rows scored by lookup).

### Disclosures

- Test-support fixes (tests, not src): `quarantined_ids()` read a
  nonexistent `IngestReport.quarantined` attribute (the disclosed rule is
  `ingest_status not in SWEEP1_ADMITTED_INGEST_STATUSES`); variant control
  worlds get their own store files; `drive_deterministic` leases in batches
  until the stage drains (one 512 batch left 538 units un-done at N=350);
  `sweep()` pins no `HARNESS_ORCH_LEASE_SECONDS` (the restart rule).
- Markers: all three journey files carry `e2e` and `slow`; they run in the
  e2e tier (`./scripts/test.sh -m "not live and not writtenahead"`),
  outside the fast gate.
- Reviewer note: under the owner's credit constraint the reviewer subagent
  pass was replaced by the dispatcher's direct verification — the
  confirmation run (all 8 e2e tests green against the committed baseline,
  1:39:33) plus the fast tier (2245 passed / 3 skipped / 0 failed) on the
  shipped tree; the diff's src/ surface is one file (`extract.py`,
  `document_bytes` resolver) already reviewed when it landed in `ccaadee`.

### Tiers

- Fast tier (`./scripts/test.sh`): **2245 passed, 3 skipped, 598 deselected,
  exit 0** (375.98s).
- e2e tier (plain `pytest tests/e2e/`): **8 passed in 5973.39s (1:39:33)** —
  the confirmation run against the committed baseline.

Fixes #144

🤖 Generated with [Claude Code](https://claude.com/claude-code)
