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
