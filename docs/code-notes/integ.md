# `aeh.integ`: design notes

These notes were the docstring of `src/aeh/integ.py` before it was split into the `aeh/integ/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

M-INTEG — the integrity gate: span verification and the six-signal read model.

Design §3.9 (`M-INTEG`), issues #73 (the pure verifier) and #74 (the gate, the
signals, and the routing). R19/ADR-12 put this module OUTSIDE the extractor on
purpose: the code that produced the evidence must never be the code that
certifies it, so this file shares no code path with `aeh.extract` — the span
payload arrives through the injected extraction view, never through an import
(`CT-INTEG-05` pins the structure; the only first-party import here is the
store seam both modules read).

**What the gate does.** One call, `verify(run_id, submission_id, criterion_id)`,
re-derives the whole integrity picture from the ledger and the extraction view
and returns the six design-declared signals (`CT-INTEG-02`): whether every span
the extractor produced matches the document bytes exactly, whether any evidence
survived that check, whether the panel's sufficiency flags are clean, whether a
low-confidence transcription overlaps a cited span, whether the evidence lies
inside a described graphic, and whether a second extraction family disagrees.
Every read that can fail fails CLOSED (`CT-INTEG-03`): a fault yields the
adverse value, never the permissive one.

**The pure half.** `verify_span(doc, span)` is a module-level function of
(document bytes, span) and nothing else — no store read, no model call, no
network (NFR-INTEG-02). It never raises: any malformed input verifies False.
Coordinates are BYTE offsets into the canonical Markdown (CT-INGEST-03), so the
function compares `raw[start:end]` to the span text's UTF-8 encoding — no
normalization, no repair, no clamping (CT-INTEG-01/06: a mid-codepoint or
out-of-bounds span is rejected, not fixed).

**Fail-closed signal semantics** (each read's fault lands on the adverse side):

- span read fault, missing document, or the disabled switch → `spans_verified`
  False and `evidence_present` False;
- empty span set → `evidence_present` False, and `spans_verified` is vacuously
  True ONLY when the criterion does not require a citation (nothing was claimed,
  so nothing failed to match);
- region read fault (or a span read fault, which leaves the cited extents
  unknown) → `ocr_overlap_risk` True AND `described_evidence` True — both are
  routing-candidate values, and an unknown cannot be certified clear;
- panel read fault → `sufficiency_flag` True;
- second-family read fault → `extractor_disagreement` True (measured-and-adverse,
  never None: the second extraction ran, so "not measured" would be a lie);
- no second family at all → `extractor_disagreement` None, distinguishable from
  False by identity, never by truthiness.

**Routing.** Exactly one route fires per verify, in a fixed order, and every
route is a routing REQUEST — the module never writes a score row (FR-INTEG-08;
the whole write surface is the work ledger, the review queue, and the per-cell
rates):

1. verification failed → file a fresh re-extraction request (the ledger's
   attempt count grows in lockstep across the criterion's pending extract
   units, and a unit that has failed `INTEG_RETRY_LIMIT` times quarantines);
   when no evidence survived AND the criterion requires a citation, a review
   row is queued alongside the retry.
2. no evidence on a citation-requiring criterion → the same retry plus the
   review row (kept even though the locked signal semantics make it shadowed
   by route 1 — the fail-closed reading survives a future semantics change).
3. the panel's computed flags name a problem (any member reports the evidence
   insufficient) → the criterion's extract units are retried; on a REPEAT
   insufficiency two escalation score units join the ledger — the widened
   panel the ledger already knows how to express, never an automatic verdict.
4. a low-confidence transcription overlaps a cited span → a review row, so a
   human sees the text the machine was unsure of.
5. evidence lies wholly inside a described graphic → a review row and a review
   unit whose id carries the crop reference (FR-INTEG-05: retained and
   reachable in one action), gated behind `INTEG_DESCRIBED_EVIDENCE_ROUTES`.
Otherwise the criterion's extract units are released as done — verified
evidence needs no further extraction.

**Observability.** Every verify emits all six per-cell rates to the durable
ledger (`CT-INTEG-14`), positionally ordered by `INTEG_RATE_METRICS`, plus an
alert row wherever the span-verification failure rate crosses
`ALERT_SPAN_VERIFICATION_FAILURES`' threshold — a rate that moves only when the
extractor hallucinated, never when the data was the problem (an empty cell has
no verification to fail, and a read fault is a data problem, not a hallucination).
The sufficiency rate reads the consumer-facing flag, conservative default
included (`CT-INTEG-11`).

**The schema step.** Tier D migration 5 widens `run_metrics` with the criterion
dimension the per-cell rates require: the three legacy columns lead unchanged
(so the migration golden's positional fixture rows still fit), the two
dimension columns follow nullable (a legacy aggregate row has no cell), and the
declared primary key makes a re-emitted cell replace its earlier value rather
than stack a second one.

**Configuration** (seam rule 3 — every environment-sensitive value is read at
call time, production value the default): `INTEG_OCR_CONF_FLOOR` (Assumption
0.70; per-transcriber and unvalidated — no consumer may treat it as
calibrated), `INTEG_DESCRIBED_EVIDENCE_ROUTES` (default on),
`INTEG_SPAN_VERIFICATION_DISABLED` (the differential-timing seam the plan's own
oracle names), `INTEG_RETRY_LIMIT` (FR-EXTRACT-08's ladder, 3), and
`INTEG_ALERT_THRESHOLD` (default 0.10; an unreadable value lowers the threshold
to zero, which fires the alert rather than silencing it).
