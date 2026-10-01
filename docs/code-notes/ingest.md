# `aeh.ingest`: design notes

These notes were the docstring of `src/aeh/ingest.py` before it was split into the `aeh/ingest/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

`M-INGEST` — the sole gateway from PDF to canonical Markdown (design §3.5).

This file lands **#36**: the gateway core — rasterize every page at the profile's
pinned DPI, transcribe each page with exactly ONE VLM call through `M-PROV`, and emit
one immutable content-hashed Markdown `document` row per logical document. A correction
(`revise_document`) creates a NEW row with `parent_doc_id` set; `document.markdown` is
never updated. The validation ladder (V0-V4, #40/#41), assembly order (#37), region
metadata (#38/#39) and the adversarial-input safety (#42) land on this foundation.

It owns **no judgment**: descriptions are descriptive only (`FR-INGEST-11`'s bar lands
with #38), and every model call goes through `M-PROV` — this module assembles payloads
and never reaches an endpoint itself.

The four seams (`CLAUDE.md`):
1. **Headless driver** — `Ingestor.ingest_document` is the pipeline entry point; nothing
   here needs a console.
2. **Deterministic transport** — the VLM is `M-PROV`'s `InferenceProvider` (the fast
   tier's `RecordedFixtureProvider`); the rasterizer is a `Rasterizer` seam with a
   scripted double for tests and a lazy-imported `pypdfium2` implementation for the
   acceptance run; the sanitizer is a `PdfSanitizer` seam the same way (#42) — a
   scripted double for the fast tier, a lazy-imported `pypdf` implementation for the
   acceptance run. A PDF is never rasterized unsanitized: the sanitizer is a required
   constructor argument, so there is no configuration that skips it.
3. **Env-gated knobs** — `HARNESS_INGEST_DPI` (the pinned rasterization DPI),
   `HARNESS_INGEST_MAX_TOKENS_PER_PAGE`, the transcription strike limit
   (`HARNESS_INGEST_TRANSCRIPTION_ATTEMPTS`, #220), and #42's adversarial-input
   ceilings (`HARNESS_INGEST_STRIP_ACTIVE_CONTENT`, `HARNESS_INGEST_MAX_PAGES_PER_DOC`,
   `HARNESS_INGEST_MAX_DECOMPRESSED_BYTES`, `HARNESS_INGEST_MAX_IMAGE_PIXELS`,
   `HARNESS_INGEST_MAX_FILE_SECONDS`, `HARNESS_INGEST_MAX_EMBEDDED_OBJECTS`);
   production values are the defaults.
4. **Stage-level observability** — `IngestReport` carries per-gate columns (populated by
   #40/#41) and the ingest surface logs page counts, hashes and the transcriber build.

## Details moved out of the code

These notes were the longer parts of docstrings in `aeh.ingest`. Each section is named after the file and the function or class it describes.

### aggregates.py: RunAggregatesMixin.run_aggregates

Signal definitions (each also stated in `basis`, with its denominator):

- `ocr_failure_rate`: submissions whose V0 or V1 gate failed, over all
  submissions — the file/OCR pipeline failed to deliver a usable
  transcript (remedy: re-scan/re-ingest). V2–V4's remedies differ,
  which is the clause's reason the rates are separate signals.
- `unresolved_mark_rate`: selection-mark regions whose
  `selection_state` is not `resolved`, over all selection-mark regions
  (remedy: operator reading — CT-INGEST-05).
- `pages_with_text_layer`: the count over the cohort's submission
  documents; 0 with no documents is the honest zero (a count, not a
  rate).
- `mean`/`max_text_layer_divergence`: over the documents that carry a
  measurement (each recorded value is that document's per-page
  maximum, F6); None when none measured.
- `gate_pass_counts`/`gate_fail_counts`: per gate over the five
  columns under `GATE_PASS_VALUES`/`GATE_FAIL_VALUES`;
  `not_reached`/`not_run` count in neither.
- `quarantine_counts_by_gate`: each quarantined row attributed to the
  FIRST failing gate in ladder order (the C19 derivation: a
  quarantined row names exactly one failing gate). A quarantined row
  that names none counts under `unattributed` — surfaced, never
  folded away.
- `second_pass_disagreement_rate`: second-described regions whose two
  descriptions disagree on a load-bearing fact or fall under the content
  floor (`description_disagreement`, FR-INGEST-14), over second-described
  regions; None when no region carries a second description, so a zero
  would lie. Failed second calls carry no second description and are not
  in this rate — they are in each document's `second_description_pass`.

### clusters.py: TokenClustersMixin.resolve_cluster

The per-kind rule:

* `transcribed_text` and `described_graphic` — the content is replaced and nothing
  else; `selection_state` is not the operator's to change by reading a word.
* `selection_mark` — the resolution must equal a declared `question_option.option_id`
  for the region's question (`question_id` since `#373`, `element_kind` for rows
  written before the column existed — M-DET's own reading). When it does,
  `selection` and `selection_state='resolved'` are written **together**, in one
  statement. Otherwise the region stays `ambiguous` with a NULL selection, its content
  is still replaced, and it is listed under `selection_unresolved` on the returned
  report — an operator who typed `E` for a four-option question learns it from the
  report rather than from a student's lost mark (RISK-50).

The declared options come from `package_catalog`/`package_version` — given here, or
bound once on the gateway. **Without them no selection mark resolves**: the module will
not guess an option set, and fail-closed here means a region left ambiguous and listed,
never a resolved mark with no selection (`CT-INGEST-21`). A caller that resolves ticks
must therefore name the package; a caller that only ever resolves illegible words need
not, and nothing it does can produce the forbidden row.

The returned `ClusterResolution` IS the tuple of affected document ids — the shape
every existing caller reads — with the report riding beside it.
