# `aeh.conform`: design notes

These notes were the docstring of `src/aeh/conform.py` before it was split into the `aeh/conform/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

`M-CONFORM`'s fixture surface (#133): the pinned fixture set, the consent boundary, and the
ingest seam the adversarial tier drives.

`FR-CONFORM-01` requires 30-50 submissions spanning the score range; `-02/03/09` require consent
declarations, the real medium, and the adversarial tier; `NFR-CONFORM-01` requires the set to be
content-addressed and version-pinned. This module is what a conformance run **loads** those
fixtures through, and the two operations the clause suite drives on them:

* `load_fixture_set(pin)` — the fixture set as data: known reference scores, media and legibility
  classes, twin pairing, PDF threat kinds, and the content hash a result cites. Every file-backed
  entry is verified against its source bytes at load, because a conformance result measured
  against a corpus that changed between runs is not a result.
* `build_conformance_suite(provider=...)` — the suite surface design §3.18 declares: `run` (whose
  consent gate is live in this story; the divergence machinery is #134's) and `ingest_one`
  (the real ingest pipeline over one fixture, including the V0 quarantine the malicious PDFs
  must reach no model call past).

The consent boundary is **delegated, not re-implemented** (`CT-CONFORM-10`): `run` asks
`aeh.conf.consent_override_for` — the same function `M-ORCH` resolves runs through — and turns a
`ConsentGateError` into this module's `ConsentRefused`. This module reads `consent_class` to
carry it and decides nothing with it; `test_tc_conform_c10_the_suite_does_not_reimplement_the_
consent_check` asserts that structurally.

First cross-package import, stated rather than smuggled
-------------------------------------------------------
`aeh` is the system; `harness` is its test harness. No `aeh.*` module imports `harness` today
and no `harness.*` module imports `aeh`, and this module ends that symmetry on purpose: the
fixture set's identity is the corpora build's artifact (`F-CONFORM`'s manifest), so reading it
means reading `harness.corpora.manifest`, and the malicious-PDF fixtures' bytes come from
`harness.corpora.adv_pdf`'s generator. The walker is unaffected (nothing imports back), and the
dependency is one-way: `harness` never imports `aeh`.

Why `ingest_one` holds the declared refusal world
-------------------------------------------------
`FR-INGEST-33`'s strip knob has two declared worlds (SEC-05's fork): at its default the
sanitizer *strips* active constructs and the pipeline processes the stripped copy; with
`HARNESS_INGEST_STRIP_ACTIVE_CONTENT=false` the same construct **quarantines** and reaches no
model call. The adversarial tier is the second world — the F-ADV-PDF manifest's
`expected_outcome: quarantine` is written for it — so `ingest_one` sets the knob for the ingest
it performs and restores the caller's value afterwards. The knob stays where M-INGEST put it
(read from the environment at call time, so a run can retune without a code change); the suite
choosing the refusal world for the corpus it measures is the declared reading, not a bypass.

The strip knob alone is not that whole world. The decompression bomb (`ADV-PDF-09`) carries no
active content — its declared outcome (`reference_score_basis: "quarantine_at_v0"`) is written
for a world whose decompressed-bytes **ceiling** sits below its declared 64 MiB expansion.
M-INGEST's production default (512 MiB) accepts it at V0, and the construct is then rasterized
and transcribed: three model calls, quarantine at V1 — exactly the failure a review of this
module's first pass caught, because `_markdown_pages`' sibling wrapper pinned only the strip
knob. So the ingest seam holds **both** knobs at the declared refusal world and restores them
afterwards: quarantine-at-V0-with-no-model-call is what every F-ADV-PDF row declares, and that
outcome only holds in a world whose ceilings refuse it.
