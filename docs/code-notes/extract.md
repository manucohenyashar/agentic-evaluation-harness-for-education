# `aeh.extract`: design notes

These notes were the docstring of `src/aeh/extract.py` before it was split into the `aeh/extract/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

`M-EXTRACT` (#68) — evidence spans, judge-independent evidence rows, fixed prompt
order.

Design §3.8 pins the *shapes* — an `ExtractionRequest` per (run, submission,
criterion), a prompt whose submission always arrives last inside the single delimited
untrusted block, and evidence rows that carry **byte-offset spans** into the
submission's canonical artifact plus the provider's **resolved build identity**. It
pins no Python names; the assumed surface lives in
`tests/support/extract_vocabulary.py` and this module implements it (`WORKER`,
`ASSEMBLE`, `PROMPT_FIELDS`, `REQUEST_TYPE`, `RESULT_TYPE`, `TEMPLATE_VERSION`,
`SPAN_PARSE`), plus the second-family mechanism (`FR-EXTRACT-07`): `second_family_model`,
the different-family model a flagged criterion's second extraction runs on.

**The one row per (run, submission, criterion).** `ExtractionWorker.process(unit)`
takes one leased `stage='extract'` unit, resolves the submission's **current**
document (the head `document` row — a supersession is a new immutable row, so a fresh
run re-extracts against the new version while old evidence stays addressed to its own
version, `TC-EXTRACT-12`), assembles the request, renders the fixed-order prompt,
calls the extractor once, parses the reply into byte-offset spans, and — in ONE
transaction — marks the unit done and writes the single `evidence` row. The row has
no judge dimension: three judges reading the same criterion read the same spans, and
the payload carries the span set and nothing else (`TC-EXTRACT-02`'s cross-panel
byte-identity pins that).

**Failure.** A `ProviderError` from the boundary or a refusing parse is one strike;
the strike is reported to the orchestrator's ledger (`Orchestrator.fail`), and the
report that reaches the ceiling quarantines the unit. A quarantined unit writes NO
evidence row — an empty row would be indistinguishable downstream from a student who
wrote nothing (`TC-EXTRACT-08`). The strike budget is the ledger's own ceiling
(`HARNESS_ORCH_MAX_ATTEMPTS`, read at call time) — one knob, one owner; the worker
does not keep a second count that could drift from the quarantine. A flagged
criterion's second family strikes the ledger not at all: the budget belongs to the
primary extraction, and the second family's outcome — its spans, or its failure after
the same budget — is recorded as that family's own record in the payload, so `M-INTEG`
sees one set where two were expected rather than losing the primary's evidence to a
quarantine.

**The four seams.** Headless: `process` returns a structured `ExtractionResult`
(status, spans, document_id, resolved_build, error) — no console anywhere. Transport:
the provider arrives by injection and `RecordedFixtureProvider` remains the only
egress. Knobs: the strike budget is the ledger's env knob, and the second family's
selection is its own pair (`HARNESS_EXTRACT_SECOND_FAMILY`,
`HARNESS_EXTRACT_SECOND_FAMILY_MODEL`) — the disable flag read per `process` call,
the model override resolved at construction like the primary ref itself.
Observability: the result carries the stage's outcome per unit (a disabled or failed
second family is said in `notes`), and the evidence row
carries the document version it addressed (`NFR-EXTRACT-02`'s version binding).

**Disclosed interpretations** (design agrees on the shape, this module fixes the
reading):
- `assemble_request(unit, *, dependency_evidence=None, question=None, store=None)` —
  a shipped `WorkUnit` carries `submission_text=None` (the lease resolves identities,
  the assembler the words, `Orchestrator.lease`'s docstring), so transcript resolution
  is the assembler's act: the unit's text when set, else the current document's blob
  decoded, via the `store` keyword. With a store, `criterion.text`/`evidence_type` are
  read from the package version the unit's run pinned (#516, CT-PKG-01/06): the wording
  is the question prompt, the construct and the band descriptors, and the evidence type
  defaults to `textual_span` when the criterion declares none. Without a store they stay
  empty.
- The transcript is rendered **verbatim** when it already carries the shipped
  `M-INGEST` delimiters (a canonical artifact is pre-fenced) and wrapped in exactly
  one fence otherwise — the rendered prompt always fences the submission exactly once.
- `prompt_fields()` with no argument returns the fixed field-NAME order — the
  `"#68 review"` registry entry's assumed surface (an iterable of field names) and
  the lint's fixed-order oracle are the same declaration.
