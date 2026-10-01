# `aeh.pipeline`: design notes

These notes were the docstring of `src/aeh/pipeline.py` before it was split into the `aeh/pipeline/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

`M-PIPE` — run composition (issue #364, `FR-PIPE-01…06`, `FR-PIPE-10`).

Turns "a started run" into a completed one by calling each stage module's public door in
§4.2.2's order. It owns no table, no statement and no migration; every row it causes is
written by the module that owns it (`CT-PIPE-05`), and every model call goes through a stage
worker holding the governed provider (`CT-PIPE-06`), so `RecordedFixtureProvider` stays the
single egress point.

**What this module is.** A loop and seven hooks. `Orchestrator.progress` runs one dispatch
pass through the executor bound here; then the cells the orchestrator reports ready get their
integrity and aggregation hooks; then the loop asks whether the run is done. Nothing here
decides what a unit *means* — that is the stage door's — and nothing here leases, orders or
sets escalation policy, which is `M-ORCH`'s.

**Why a separate module.** `aeh.orch` is an ancestor of every stage module in the import
graph (the migration registry's contributor order), so the orchestrator cannot import the
workers at module scope. Composition has to live in a leaf, and this is it (ADR-15).

Gaps in the design's declared inputs, resolved here and reported on #364 / #365
-------------------------------------------------------------------------------
Each is a place where the requirement names a call whose arguments the declared inputs cannot
supply. None is papered over: the resolution is stated, and the reason it is safe is stated
with it.

**1. `should_escalate` gets no history and no baseline.** `FR-PIPE-04` step 4 says to evaluate
it; its signature is `should_escalate(score, criterion, history, baseline, *, config)`. Nothing
in `src/aeh/` produces either value — the journeys passed doubles from
`tests/support/agg_vocabulary.py`. Both are passed as `None`, which `agg._row_field` reads as
the absent sentinel, and the module's own rule is that an absent field "is not making the
claim, and the limb is skipped". So the override-history and distributional-anomaly limbs make
no claim, and escalation runs on the limbs whose inputs this module *does* hold: interior band
position, the six integrity signals, and the uncited mark.

That has a consequence worth stating plainly: **the anomaly limb never fires in production**,
and it is precisely the limb that makes every judged cell of `F-DEV-PIPE` escalate under the
journey baseline (`mean=2.0, std=0.5`, calibrated for the reference package's four-band scale).
A production baseline reader is `M-STATS`' territory and is not in `FR-PIPE`'s table.

**2. The extractor ref has no home in `RunConfig`.** `RunConfig`'s twelve fields carry `panel`,
`transcriber` and `off_panel_checker`; `ModelRole` also declares `"extractor"` and
`"synthesizer"`, and neither has a field. `ExtractionWorker` refuses a `model_ref` whose role
is not `"extractor"` (`extract.py:857`), so one must be produced. `extractor=` and
`second_family=` are therefore optional keywords here, and when they are absent the extractor
is the **transcriber's backend identity re-roled**: same provider, build and quantization,
`role="extractor"`. That is a declared default, not a guess dressed as one — a deployment
running one local backend gets the backend it configured, and a deployment running two passes
the second explicitly.

**3. Extension arms are not in the panel.** `M-ORCH` mints `escalation-arm-<k>` identities for
a widened panel (`orch.py:1747`), and those ids are not `RunConfig.panel` members. An arm's
`ModelRef` is derived from the panel's **first** arm with the build id swapped, so a widened
panel runs on the backend the run froze. `judge_refs=` overrides that for a caller who knows
better — which is what a replay against a recorded corpus needs, because the recorded arms
carry whatever identity the capture used.

**4. No provider factory exists.** `FR-PIPE-08` has the command resolve its configuration and
drive the run, but nothing says which provider object a backend profile maps to, and `M-PROV`
ships three classes and leaves construction to the caller. `_provider_for` makes the mapping
in the open and refuses an unconfigured profile by name rather than guessing.

**Deterministic units are evaluated here, not by the dispatch pass.** `FR-PIPE-02` forbids a
unit reaching `done` without its payload row. The orchestrator's deterministic walk closes
those units directly (`orch.py:5608`, `self.complete(unit.work_id)`) and never calls
`DeterministicEvaluator` — no model call exists for the stage, so the ledger transition *is*
its dispatch. Left alone that would close a deterministic unit with no `criterion_score` row.
So this module runs `DeterministicEvaluator.evaluate_cohort(run_id)` **before** the first
dispatch pass, which is idempotent under redelivery and puts every row in place before any
unit closes over it.
