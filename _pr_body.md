## TC-E2E — the three end-to-end journeys (issue #144, TS-51, rung 4)

The assembled system, exercised journey-scale with no doubles at module
boundaries. The only double anywhere is the model boundary:
`RecordedFixtureProvider` in its shipped regeneration-then-replay shape —
scripted on first sight, recorded through the real provider seam, replayed
request-keyed thereafter (CT-PROV-10, CT-PROV-15).

### What landed

- **`tests/support/e2e_world.py`** — the assembled-system world all three
  journeys share: F-SYNTH cohorts synthesized into real ingested documents
  (real gateway, real 4-page PDFs at the 72 DPI floor, real sanitizer and
  rasterizer), the PKG-REF catalog built through the real M-PKG writer
  (GradePolicy attached before publication, ADR-3), real store across the full
  migration chain, the run lifecycle through the real M-ORCH lease clock.
- **TC-E2E-01** (`tests/e2e/test_e2e_01_setup_journey.py`) — the setup
  journey: four PDFs to a locked package. Blocking-gate surface, whole
  M-SETUP chain, publication and the 6.2 lock.
- **TC-E2E-02** (`tests/e2e/test_e2e_02_overnight_run.py`) — the overnight
  run: 350 submissions in, 341 finalized grades out, zero teacher action.
  Happy path plus three injury variants: SIGKILL mid-run and the resume
  reproduces the untouched control's result set exactly; provider-unavailable
  pauses the run on the same backend and resumes; criterion-breaker halts
  escalation, marks `ungradeable_by_panel`, and the run still completes.
  The 350-submission result set is frozen as
  `fixtures/baselines/TC-E2E-02/result-set.json` under the §6.9 governance
  (registered in `NON_GOLDEN_BASELINE_ARTIFACTS`: the journey's own
  request-keyed provider produces it, the overnight run is its owner).
- **TC-E2E-03** (`tests/e2e/test_e2e_03_review_morning.py`) — the review
  morning: queue triage, per-item and group decisions on real `ReviewItem`s,
  a whole-draw blind sitting (no criterion filter), the honest residual, and
  the promote that refuses a blended headline over a multi-criterion
  population (CT-STATS-04/06: `agreement_kappa` is `None`, the weakest
  per-population entry carries the record rule).

### The real bug the journey found (and the fix that landed)

`ccaadee` — a really-ingested submission's document row carried a
`content_hash` with no blob behind it: M-INGEST writes the Markdown its hash
covers into the document row's markdown column, while the blob store's
declared inventory (FR-STORE-06) is source PDFs, page rasters and image crops
— so M-EXTRACT's blob-store read hit an empty transcript for every
journey-scale submission while the smoke test's seeded form (blob-first)
passed. The rule M-INTEG established settles it: the markdown column is
canonical (FR-INGEST-04), the content-addressed blob is the fallback, and the
hash must equal the bytes actually read either way (CT-INGEST-02), failing
closed otherwise. `extract.document_bytes` is now the shared resolver used by
both the assemble path and the worker's process path. The journey found this
within its first honest run at scale — the smoke test's seeded shape masked it.

### Disclosures

- Test-support fixes (tests, not src): `quarantined_ids()` read a
  nonexistent `IngestReport.quarantined` attribute (the disclosed rule is
  `ingest_status not in SWEEP1_ADMITTED_INGEST_STATUSES`); variant control
  worlds now get their own store files (`tmp_data_dir / "control"`);
  `drive_deterministic` leases in batches until the stage drains (one 512
  batch left 538 units un-done at N=350); `sweep()` pins no
  `HARNESS_ORCH_LEASE_SECONDS` (a fresh `LeaseClock` on reattach already
  expires every outstanding lease — the restart rule).
- Journey-01's file and `e2e_world.py` are the spec: they narrate the
  journeys' seams rather than repeat the module docstrings.
- Markers: all three journey files carry `e2e` and `slow`; they run in the
  e2e tier (`./scripts/test.sh -m "not live and not writtenahead"`), outside
  the fast gate.

### Tiers

- Fast tier (`./scripts/test.sh`): PASS — N passed in M (see run record).
- e2e tier (`./scripts/test.sh -m "not live and not writtenahead"`): PASS —
  all journey tests included (see run record).

Fixes #144

🤖 Generated with [Claude Code](https://claude.com/claude-code)