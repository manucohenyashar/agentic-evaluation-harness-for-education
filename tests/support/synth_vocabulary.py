"""The assumed surface of `aeh.synth` (`M-SYNTH`, #97/#98) — settled in one place.

Design §3.13 pins the `SynthesisResult` *shape* ("`{work_id, question_id, text}` at L1 and
`{work_id, text}` at L2"), the `narrative` key (`(run_id, submission_id, level,
question_id)`, `question_id NOT NULL`, sentinel `'__test__'` for `level = 'l2_test'` rows),
and the configuration names (`SYNTH_PROMPT_TEMPLATE_V`, `SYNTH_SCORE_CLAIM_PATTERNS`,
`SYNTH_MAX_OUTPUT_TOKENS`) — but pins **no Python names at all**: no Interfaces block, no
Protocol (grep of detailed-design.md returns none; the `"#97 TS-24 synthesis boundary"`
registry entry already records this). Thirteen TS-37 cases cannot each guess a different
surface, so — the `extract_vocabulary` precedent — every name the TS-37 suite resolves is
declared HERE, once, with its status, and the tests import from here. If #97/#98 ship a
name differently, the rename is one line in this file and nowhere else.

| Name in this file | Assumed `aeh.synth` name | Status |
|---|---|---|
| `WORKER` | `SynthesisWorker` | **invented here** — the driver class; the shipped `ExtractionWorker` (extract suite) / `ScoringWorker` (review suite) precedent for a store+provider+model_ref worker |
| `SYNTHESIZE` | `synthesize` | **reserved by the repo** — the `"#97 TS-24 synthesis boundary (RES-07)"` registry entry keys on it and the RES-07 test calls it; this suite does NOT key on it (the worker + report are its surfaces) but records the same bet |
| `REPORT` | `SynthesisReport` | **invented here** — the per-call report the fourth seam (stage-level observability) requires; `CT-SYNTH-08`'s signals are read off it |
| `L1_REQUEST` / `L2_REQUEST` | `L1Request` / `L2Request` | **invented here** — the two request types `CT-SYNTH-02`'s type-level boundary lives on; design names no request type. `L2Request` must be a type on which no field can carry a raw verdict — that is NFR-SYNTH-03's "enforced by the request type, not by prompt instruction" |
| `RESULT_TYPE` | `SynthesisResult` | **design-named** (§3.13 `CT-SYNTH-01`) — the type name, not any member |
| `SCORE_CLAIM_CHECK` | `has_score_claim` | **invented here** — the pure text predicate TC-SYNTH-04 drives at rung 0; the `verify_span` precedent for a module-level pure entry the rung-0 cases call. True means a claim matched |
| `PATTERNS` | `SYNTH_SCORE_CLAIM_PATTERNS` | **design-named** (§3.13 Configuration, `CT-SYNTH-11`) — assumed exported from `aeh.synth`; if #98 hangs it off `aeh.conf`, the rename is one line |
| `LEVEL_L1` | `"l1_question"` | **invented here** — the L1 level literal; only the L2 literal is design-named |
| `LEVEL_L2` | `"l2_test"` | **design-named** (§3.13 `CT-SYNTH-06`, ADR-8) |
| `TEST_SENTINEL` | `"__test__"` | **design-named** (`CT-SYNTH-06`, ADR-8) — the `question_id` stored for L2 rows |
| `SCORE_CLAIM_FLAG` | `score_claim_flag` | **invented here** — the narrative column `CT-SYNTH-03`'s "stored with a flag and suppressed from display" requires; read back as a 0/1 integer |
| `QUESTION_OF` | question↔criterion grouping | **invented here, data-side** — the shipped criterion spec carries no question field, so the TS-37 fixtures group criteria by naming convention (`Q1C1`, `Q2C1`, ...) and this file exposes the grouping; #97's request assembly owns the real mapping and reconciles at landing |

The assumed *member* surface of the worker, used by the integration files:

- `SynthesisWorker(store, provider, model_ref)` — the store it writes narratives through,
  the provider it calls, and the synthesis model (`ModelRef`; the `synthesizer` role
  literal is **assumed** — shipped `aeh.conf.ModelRole` is `judge/transcriber/extractor/
  off_panel`, and #97 adds the fifth role; `synth_ref()` below discloses it in one place).
- `.synthesize_question(run_id, submission_id, question_id) -> SynthesisResult` — one L1
  composition: reads that question's criterion verdicts and evidence for that ONE
  submission (`FR-SYNTH-01`, `FR-SYNTH-05`), writes the L1 narrative row.
- `.synthesize_submission(run_id, submission_id) -> SynthesisReport` — the two-level
  driver: L1 for each of the submission's questions whose criteria are complete
  (`FR-SYNTH-06` skips incomplete ones), then one L2 composition reading **only** the L1
  syntheses (`FR-SYNTH-01`), writing the L2 narrative row with the `'__test__'` sentinel
  (`FR-SYNTH-07`). Signature reconciliation happens at #97's landing, as the RES-07
  docstring already discloses for `synthesize` itself.

The assumed *report* surface (`SynthesisReport`), read by the observability file — every
name disclosed, per the fourth seam (`IngestReport.gates` precedent — per-stage detail
next to the status, never one boolean):

- `model_calls` (int) — L1 plus L2 calls actually made (`NFR-SYNTH-02`'s ~2,100 for 350
  students is 6 per submission: 5 L1 + 1 L2).
- `narratives` (int), `failures` (int) — the failure-rate numerator and denominator.
- `rejected_score_claims` (int) — outputs rejected by the score-claim check and
  re-requested (`CT-SYNTH-03`).
- `mean_narrative_length` (float) — mean stored-narrative length in words.
- `sample` (tuple of narrative texts, may be empty) — the quality sample drawn for
  `M-STATS` (`FR-SYNTH-04`, `NFR-SYNTH-01`; the measurement itself is `TC-STATS-19`'s).
- `citation_validity_rate` (float or None when unsampled) — measured on the sample.

The assumed *response* format the synthesis completion carries is fixed here too
(`narrative_completion`), because the recorded-fixture tests must construct one: a JSON
object whose `narrative` is the text and whose `citations` list names criterion ids —
**disclosed stand-in**, one function, one place; the module's parse of the model's reply
is #97's to fix, and the worker is free to parse whatever it likes as long as the
narrative text and its criterion anchors come out.

Nothing in this file imports `aeh.synth`; resolution happens inside the test bodies via
`tests.support.impl.require`, so a missing module is a stated failure, not a collection
error.
"""

from __future__ import annotations

import json
from typing import Any

#: The implementing stories. #97 owns the module, the two-level boundary, the
#: completeness gate and the narrative schema; #98 owns the score-claim prohibition and
#: the evidence anchoring.
SYNTH_ISSUE = "#97"
SCORE_CLAIM_ISSUE = "#98"

WORKER = "SynthesisWorker"
SYNTHESIZE = "synthesize"
REPORT = "SynthesisReport"
L1_REQUEST = "L1Request"
L2_REQUEST = "L2Request"
RESULT_TYPE = "SynthesisResult"
SCORE_CLAIM_CHECK = "has_score_claim"
PATTERNS = "SYNTH_SCORE_CLAIM_PATTERNS"

LEVEL_L1 = "l1_question"
LEVEL_L2 = "l2_test"
TEST_SENTINEL = "__test__"
SCORE_CLAIM_FLAG = "score_claim_flag"

#: The cohort id the synth fixtures seed (`orch_run.seed_run` writes `c-2026-7B-orch`;
#: the synth suite reuses the same helper and so the same cohort id).
COHORT_ID = "c-2026-7B-orch"

#: Five questions of two criteria each, the TC-SYNTH-01 fixture's shape, as criterion
#: specs for `orch_run.seed_package`. The question grouping is the naming convention
#: above: a criterion `Q<n>C<k>` belongs to question `Q<n>`.
FIVE_QUESTION_CRITERIA = tuple(
    {"criterion_id": f"Q{q}C{k}", "kind": "open", "scoring_model": "holistic"}
    for q in range(1, 6)
    for k in range(1, 3)
)


def question_of(criterion_id: str) -> str:
    """The question a convention-named criterion belongs to (`Q2C1` -> `Q2`)."""
    return criterion_id.split("C", 1)[0]


def synth_ref(build_id: str = "/models/qwen3-30b-a3b.gguf@sha256:syn7h",
              provider: str = "ollama",
              quantization: str = "q4") -> Any:
    """A `ModelRef` for the synthesis role.

    **Disclosed**: `role="synthesizer"` is not in shipped `aeh.conf.ModelRole` — #97
    adds the fifth literal. Constructing the ref before that lands is exactly one of the
    failures the writtenahead tests are expected to hit, so it is translated into the
    stated one rather than a bare `ConfigurationError` a reader would misread as a
    fixture bug.
    """
    from tests.support.impl import NotImplementedYet

    try:
        from aeh.conf import ModelRef

        return ModelRef(
            role="synthesizer",
            provider=provider,
            build_id=build_id,
            quantization=quantization,
        )
    except Exception as exc:
        raise NotImplementedYet(
            'aeh.conf does not admit ModelRef role "synthesizer" yet (blocked on #97, '
            f"which adds the synthesis role): {exc}. This fixture is written ahead of "
            "its implementation (test plan §8.2)."
        ) from None


def narrative_completion(text: str,
                         citations: tuple[str, ...] = (),
                         *,
                         build_id: str = "synth-build-ts37") -> Any:
    """A `Completion` whose text is the assumed synthesis reply for `text`.

    **Disclosed stand-in** (see the module docstring): the reply format the worker parses
    is #97's to fix. `citations` are the criterion ids the narrative's claims anchor to
    (`FR-SYNTH-04`).
    """
    from aeh.prov import Completion

    return Completion(
        text=json.dumps({"narrative": text, "citations": list(citations)}, sort_keys=True),
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
        resolved_build=build_id,
        cached_prefix_tokens=0,
        cost=None,
    )


def sampling_params() -> Any:
    """The sampling parameters the suite records and the worker is assumed to send."""
    from aeh.prov import SamplingParams

    return SamplingParams(temperature=0.0)


class CaptureProvider:
    """The model-boundary double the §4.2 rule permits: counts and captures `complete`
    calls, replies from a canned list in order.

    The captured `PromptPayload` objects are what TC-SYNTH-01's oracle inspects (the
    assembled L1/L2 requests); the call count is TC-SYNTH-12's; the canned replies are
    `narrative_completion` payloads in the order the two levels are assumed to call.
    """

    def __init__(self, replies: list[Any]) -> None:
        self._replies = list(replies)
        self.calls = 0
        self.prompts: list[Any] = []

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        self.calls += 1
        self.prompts.append(prompt)
        if not self._replies:
            raise AssertionError(
                "CaptureProvider ran dry: the worker made more model calls than the "
                "fixture canned — disclose the extra call in the test, do not paper "
                "over it"
            )
        return self._replies.pop(0)

    @property
    def prompt_text(self) -> str:
        """Every captured prompt's fields joined, for containment/difference scans."""
        return "\n".join(
            f"{name}={value}" for prompt in self.prompts for name, value in prompt.fields
        )


__all__ = [
    "COHORT_ID",
    "FIVE_QUESTION_CRITERIA",
    "LEVEL_L1",
    "L1_REQUEST",
    "L2_REQUEST",
    "PATTERNS",
    "REPORT",
    "RESULT_TYPE",
    "SCORE_CLAIM_CHECK",
    "SCORE_CLAIM_FLAG",
    "SCORE_CLAIM_ISSUE",
    "SYNTHESIZE",
    "SYNTH_ISSUE",
    "TEST_SENTINEL",
    "WORKER",
    "CaptureProvider",
    "evidence_marker",
    "narrative_completion",
    "question_of",
    "sampling_params",
    "seed_scored_submission",
    "synth_ref",
]


def evidence_marker(question: str) -> str:
    """The distinctive evidence phrase marker seeded for a question's spans.

    The seeded document embeds `EVIDENCE-Q<n>` markers so a prompt's evidence reads are
    attributable: an L1 request for `Q1` carries `EVIDENCE-Q1` and must not carry
    `EVIDENCE-Q2`; an L2 request must carry none at all (evidence is raw material the
    two-level boundary keeps at L1, FR-SYNTH-01).
    """
    return f"EVIDENCE-{question.upper()}"


def seed_scored_submission(
    store: Any,
    run_id: str,
    submission_id: str,
    *,
    criteria_by_question: "dict[str, tuple[str, ...]] | None" = None,
    complete_questions: "set[str] | None" = None,
    judges: "tuple[str, ...] | None" = None,
    band: str = "high",
    markdown: "str | None" = None,
) -> "dict[str, list[str]]":
    """Seed the store state synthesis reads for one submission: done `score` units,
    three verdicts per criterion, one document with per-question evidence, one evidence
    row per unit.

    Bypasses `M-EXTRACT`/`M-JUDGE`/`M-AGG` on the `seed_document`/`seed_work_unit`/
    `seed_verdict` helpers the integ vocabulary already ships — those upstream modules'
    artifacts are this fixture's *inputs*, and the fixture states them directly rather
    than standing in for three modules (`test_extract_document_invalidation.py`
    precedent: "Seeding bypasses the resolution").

    The question grouping is the naming convention (`Q1C1` -> `Q1`); `#97`'s request
    assembly owns the real mapping and reconciles at landing. An incomplete question
    (not in `complete_questions`) gets its `score` unit as `pending` with **no verdict
    rows** — the incomplete state expressed at both surfaces a completeness gate could
    read, whichever one `#97`'s gate reads.

    Returns `{question: [criterion ids]}`.
    """
    from tests.support.integ_vocabulary import (
        document_id_for,
        seed_document,
        seed_verdict,
        seed_work_unit,
    )

    criteria_by_question = criteria_by_question or {
        f"Q{q}": (f"Q{q}C1", f"Q{q}C2") for q in range(1, 6)
    }
    complete = complete_questions if complete_questions is not None else set(criteria_by_question)
    handle = store.cohort(COHORT_ID)

    if markdown is None:
        markdown = "\n\n".join(
            f"## Question {q[1:]}\n{evidence_marker(q)}: the student's own work for "
            f"question {q} — the span the narrative must cite or paraphrase."
            for q in criteria_by_question
        )
    document_id = seed_document(
        handle, document_id_for(submission_id), submission_id, markdown, COHORT_ID
    )

    seeded: "dict[str, list[str]]" = {}
    for question, criteria in criteria_by_question.items():
        seeded[question] = list(criteria)
        for criterion_id in criteria:
            work_id = f"wu-{submission_id}-{criterion_id}-score"
            seed_work_unit(
                handle,
                work_id,
                run_id,
                submission_id,
                criterion_id,
                stage="score",
                status="done" if question in complete else "pending",
            )
            if question in complete:
                panel = judges or (
                    f"judge-{question.lower()}-a",
                    f"judge-{question.lower()}-b",
                    f"judge-{question.lower()}-c",
                )
                for judge_id in panel:
                    seed_verdict(
                        handle,
                        f"vd-{work_id}-{judge_id}",
                        work_id,
                        judge_id,
                        band,
                    )
            with handle.transaction() as tx:
                tx.execute(
                    "INSERT INTO evidence (evidence_id, work_id, document_id) "
                    "VALUES (:e, :w, :d)",
                    e=f"ev-{work_id}",
                    w=work_id,
                    d=document_id,
                )
    return seeded
