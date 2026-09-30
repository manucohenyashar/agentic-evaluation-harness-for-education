# `aeh.synth`: design notes

These notes were the docstring of `src/aeh/synth.py` before it was split into the `aeh/synth/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

`M-SYNTH` (#97) — two-level narrative synthesis, submission isolation, the
completeness gate.

Design §3.13 pins the *shapes* — L1 reads one question's criterion verdicts and
evidence for one submission; L2 reads only the L1 syntheses; the `narrative` key is
`(run_id, submission_id, level, question_id)` with `question_id NOT NULL` and the
`'__test__'` sentinel on L2 rows (ADR-8) — and pins **no Python names**. The assumed
surface lives in `tests/support/synth_vocabulary.py` and this module implements it
(`WORKER`, `SYNTHESIZE`, `REPORT`, `L1_REQUEST`, `L2_REQUEST`, `RESULT_TYPE`,
`LEVEL_L1`, `LEVEL_L2`, `TEST_SENTINEL`, `SCORE_CLAIM_FLAG`), plus the design's
configuration names (`SYNTH_PROMPT_TEMPLATE_V`, `SYNTH_MAX_OUTPUT_TOKENS`).

**The two-level boundary is a type, not a prompt instruction** (`NFR-SYNTH-03`).
`L1Request` carries the question's criterion verdicts and evidence; `L2Request` carries
the L1 syntheses and **no field that could carry a verdict** — there is nowhere on the
type for thirty verdicts to ride, so a later change cannot hand them to the small
model that composes the test-level prose. `SynthesisResult` is
`{work_id, question_id, text}` — no numeric field exists to write a score into
(`FR-SYNTH-02`; CT-AGG-16 audits the write-set disjointness statically, and this
module declares no statement touching `criterion_score` or `submission_grade`).

**The completeness gate** (`FR-SYNTH-06`): a question's criteria are complete when each
criterion's `score` unit stands `done` AND carries at least one verdict — both surfaces
the incompleteness shows at (`CT-SYNTH-05`). A question that is not complete gets no L1
call and no narrative; the remaining questions still compose the L2 narrative, so a
consumer infers incompleteness from the MISSING question's narrative.

**Idempotence** (`CT-ORCH-04`, ADR-8): every narrative identity is keyed
`(run_id, submission_id, level, question_id)` in the schema, and the worker reads what
is already stored before it calls the model — a retried synthesis absorbs into the
existing rows (no provider call for a stored identity) and a concurrent duplicate hits
the declared primary key and conflicts rather than duplicating.

**The score-claim prohibition** (`FR-SYNTH-03`, story #98): every
narrative the model returns is scanned against `SYNTH_SCORE_CLAIM_PATTERNS` — the
configured pattern list, one enumerable place (`CT-SYNTH-11`), holding the four
classes FR-SYNTH-03 names. A matching output is rejected and re-requested **once**;
a second matching output is terminal: the text is stored **with the
`score_claim_flag` set and suppressed** — from display by the flag a consumer reads,
and from further composition (an L2 narrative is composed only from unflagged L1
rows), because a prose verdict above a mark is functionally a second competing grade
(RISK-19) and feeding suppressed prose to the next level is how a caught claim
propagates. The stored-but-flagged row (never a deletion) is what keeps the
rejection-rate metric `CT-SYNTH-12` alerts on countable. The check itself is the
pure module-level predicate `has_score_claim` (`TC-SYNTH-04`'s rung-0 entry); the
`narrative` table has carried the `score_claim_flag` column since migration 13, so
the schema does not move under this story.

**The four seams.** Headless: `synthesize()` and the worker return a structured
`SynthesisReport` — no console anywhere. Transport: the provider arrives by injection
and `RecordedFixtureProvider` remains the only egress point; this module has no
network, no backend name and no socket. Knobs: the strike budget
(`HARNESS_SYNTH_MAX_ATTEMPTS`, defaulting to the ledger's own ceiling), the output
cap (`HARNESS_SYNTH_MAX_OUTPUT_TOKENS`) and the quality-sample rate
(`HARNESS_SYNTH_SAMPLE_RATE`) are read at **call** time — production values are the
defaults, and a slower box adjusts without a code change. Observability: the report
carries the design's four signals next to the status — synthesis failure rate,
score-claim rejection rate, mean narrative length and the citation-validity /
hallucinated-claim rates on the sampled subset (`CT-SYNTH-12`) — plus the sample
itself with its size attached, for `M-STATS` (`FR-SYNTH-04`).

**Disclosed interpretations** (design agrees on the shape, this module fixes the
reading):
- The question a criterion belongs to comes from the package's `criterion.question_id`
  column (the real mapping, `M-PKG`'s own field); a criterion with no `question_id`
  falls back to the `Q<n>C<k>` naming convention the test fixtures group by. A
  criterion that resolves to no question at all gets no L1 narrative (there is no
  question to name).
- Evidence for an L1 request: the question's criteria's evidence rows are read and
  their persisted span payload (byte offsets into the canonical document) is decoded
  to text; an evidence row with no payload falls back to the **addressed document's
  markdown** — the row is a pointer into that document, and the pointer's target is
  the evidence a payload-less ledger has. A malformed payload is skipped with a logged
  error, never a crash: `CT-SYNTH-08` — nothing here fails a grade.
- `work_id` on `SynthesisResult` is the stored narrative's deterministic id
  (`nar:<run>:<submission>:<level>:<question>`) — the design's `{work_id, ...}` shape
  with the only work identity a narrative row has.
- L1 composition order is the sorted question id; the L2 call follows the L1 calls
  (the order the capture fixtures disclose).
- The narrative text is parsed from the model's JSON reply (`{"narrative": ...,
  "citations": [...]}`) — `parse_narrative` is the module's own reading of the reply
  format the recorded fixtures disclose; a reply that will not parse is a strike, and
  the budget is the retry knob.
- The quality sample is the first `k` stored narratives in deterministic order,
  `k = max(1, round(rate * n))` — a sample drawn for measurement, never a gate
  (§2.3 Q-06: the rates are reported, never enforced).

Migration 13 rebuilds the shipped `narrative` table (cohort schema) to the ADR-8 key:
the three legacy columns lead unchanged, the key columns follow with defaults so the
copy preserves every legacy row (a legacy narrative had `narrative_id` +
`submission_id` + `criterion_id` and no run/level/question identity — its `criterion_id`
moves into the `question_id` slot, the closest identity it carried), and the declared
primary key enforces the uniqueness the retry conflict rests on.
