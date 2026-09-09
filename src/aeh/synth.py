"""`M-SYNTH` (#97) — two-level narrative synthesis, submission isolation, the
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

**The score-claim prohibition is #98's mechanism, deliberately not here yet.**
`FR-SYNTH-03`'s reject-and-re-request ladder hangs off `has_score_claim` and
`SYNTH_SCORE_CLAIM_PATTERNS` — story #98 ships the check and the configured pattern
list; until then this module's report carries `rejected_score_claims = 0` and the
rejection rate 0.0 (no check is configured, so nothing is rejected). The `narrative`
table already carries the `score_claim_flag` column #98's ladder writes, so the
schema lands once and does not move under #98.

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
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from aeh.orch import (
    ORCH_MAX_ATTEMPTS,
    ORCH_STATEMENTS,
    _cohort_keys_on_filesystem,
    _env_int,
)
from aeh.pkg import PackageCatalog
from aeh.prov import PromptPayload, ProviderError, SamplingParams
from aeh.store import Migration, Statement, Tier, TIER_MIGRATIONS

LOGGER = logging.getLogger(__name__)


# --- the schema step (FR-SYNTH-07, ADR-8) ---------------------------------------------------------

#: Tier C, migration 13: the `narrative` table rebuilt onto the ADR-8 key. SQLite cannot
#: add primary-key columns in place, so the rebuild is the create-copy-drop-rename
#: march — and the copy is the data-loss half the golden pins (`TC-STORE-04`): every
#: legacy row survives, its three legacy columns verbatim and its new key columns
#: defaulted (`criterion_id` becomes the legacy row's `question_id` — the identity it
#: actually carried). The declared `PRIMARY KEY (run_id, submission_id, level,
#: question_id)` with `question_id NOT NULL` is what makes a retried synthesis unit
#: conflict rather than duplicate — SQLite permits NULLs in the columns of a
#: non-INTEGER primary key, which is exactly the hole the NOT NULL closes.
#:
#: The legacy columns lead the declaration **in their original order** on purpose: the
#: migration golden's fixture rows are seeded positionally by the table's leading
#: columns at every schema version, and one fixture row shape that fits both the old
#: and the new table is what keeps that fixture honest across the rebuild.
#:
#: Known limitation, disclosed: a pre-13 ledger holding TWO narratives for one
#: `(submission_id, criterion_id)` under different `narrative_id`s — the duplicates
#: the old narrative_id-only key permitted — cannot copy cleanly onto the new key
#: (both would map to the same `('' , submission, 'l1_question', criterion_id)` row),
#: so the migration fails loudly at the open and rolls back rather than silently
#: dropping either row. No shipped ledger carries such a pair; if one ever does, the
#: remediation is a documented pre-dedup step in the same change, not a quiet
#: `INSERT OR IGNORE`.
_SYNTH_NARRATIVE_KEY: tuple[Statement, ...] = (
    Statement(
        """
        CREATE TABLE narrative_rekeyed (
            narrative_id     TEXT NOT NULL,
            submission_id    TEXT NOT NULL REFERENCES submission(submission_id),
            criterion_id     TEXT,
            run_id           TEXT NOT NULL DEFAULT '',
            level            TEXT NOT NULL DEFAULT 'l1_question'
                             CHECK (level IN ('l1_question', 'l2_test')),
            question_id      TEXT NOT NULL DEFAULT '',
            text             TEXT NOT NULL DEFAULT '',
            citations        TEXT NOT NULL DEFAULT '[]',
            score_claim_flag INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (run_id, submission_id, level, question_id)
        )
        """
    ),
    Statement(
        """
        INSERT INTO narrative_rekeyed (narrative_id, submission_id, criterion_id,
                                       run_id, level, question_id, text, citations,
                                       score_claim_flag)
        SELECT narrative_id, submission_id, criterion_id, '', 'l1_question',
               COALESCE(criterion_id, ''), '', '[]', 0
        FROM narrative
        """
    ),
    Statement("DROP TABLE narrative"),
    Statement("ALTER TABLE narrative_rekeyed RENAME TO narrative"),
)

TIER_MIGRATIONS[Tier.COHORT] = TIER_MIGRATIONS[Tier.COHORT] + (
    Migration(version=13, name="synth_narrative_key", statements=_SYNTH_NARRATIVE_KEY),
)


# --- the runtime statements (declared, never assembled — FR-STORE-08, SEC-15) ---------------------

SYNTH_STATEMENTS: dict[str, Statement] = {
    "select_score_units": Statement(
        "SELECT work_id, criterion_id, status FROM work_unit "
        "WHERE run_id = :run_id AND submission_id = :submission_id AND stage = 'score'"
    ),
    "select_verdicts": Statement(
        "SELECT verdict_id, work_id, judge_id, band FROM verdict WHERE work_id = :work_id"
    ),
    "select_evidence": Statement(
        "SELECT evidence_id, work_id, document_id, payload FROM evidence "
        "WHERE work_id = :work_id"
    ),
    "select_document": Statement(
        "SELECT document_id, submission_id, markdown FROM document "
        "WHERE document_id = :document_id"
    ),
    "select_narratives": Statement(
        "SELECT narrative_id, run_id, submission_id, level, question_id, text, "
        "citations, score_claim_flag FROM narrative "
        "WHERE run_id = :run_id AND submission_id = :submission_id"
    ),
    "insert_narrative": Statement(
        "INSERT INTO narrative (narrative_id, run_id, submission_id, level, "
        "question_id, text, citations, score_claim_flag) VALUES (:narrative_id, "
        ":run_id, :submission_id, :level, :question_id, :text, :citations, "
        ":score_claim_flag)"
    ),
}


# --- configuration (CT-SYNTH-11, the four seams) --------------------------------------------------

#: The pinned synthesis prompt template version (`CT-SYNTH-11`: pinned, a `work_id`
#: input — the run row's `prompt_template_v` carries it into the orchestration hash;
#: this module pins the value and renders by it).
SYNTH_PROMPT_TEMPLATE_V = "synth-prompt/1"

#: The output cap per synthesis call (`CT-SYNTH-09`: the call budget is bounded by
#: `SYNTH_MAX_OUTPUT_TOKENS`). The production default; `HARNESS_SYNTH_MAX_OUTPUT_TOKENS`
#: overrides at call time.
SYNTH_MAX_OUTPUT_TOKENS = 512

#: The quality-sample fraction (`NFR-SYNTH-01`: measured on a sample every
#: administration). `HARNESS_SYNTH_SAMPLE_RATE` overrides at call time.
SYNTH_SAMPLE_RATE = 0.25

MAX_ATTEMPTS_SYNTH_ENV = "HARNESS_SYNTH_MAX_ATTEMPTS"
MAX_OUTPUT_TOKENS_ENV = "HARNESS_SYNTH_MAX_OUTPUT_TOKENS"
SAMPLE_RATE_ENV = "HARNESS_SYNTH_SAMPLE_RATE"

LEVEL_L1 = "l1_question"
LEVEL_L2 = "l2_test"
TEST_SENTINEL = "__test__"
SCORE_CLAIM_FLAG = "score_claim_flag"

#: The naming-convention fallback for a criterion with no `question_id` on its package
#: row: the fixtures' `Q1C1` spelling groups by the leading `Q<n>`.
_QUESTION_CONVENTION = re.compile(r"\A(Q\d+)C")


def _env_float(name: str, default: float) -> float:
    """A float knob, read at call time: absent means the default, anything unparsable
    is REFUSED — a knob that guesses is a lie the deployment cannot see."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not a number — refused, not guessed") from None
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name}={raw!r} is not a fraction of the stored rows — refused")
    return value


def _question_of_criterion(question_id: str, criterion_id: str) -> str:
    """The question a criterion belongs to: the package's own mapping when it carries
    one, the naming convention otherwise, and nothing when neither does."""
    if question_id:
        return question_id
    matched = _QUESTION_CONVENTION.match(criterion_id)
    return matched.group(1) if matched else ""


def narrative_work_id(run_id: str, submission_id: str, level: str, question_id: str) -> str:
    """The deterministic work identity of one narrative row — the id a retried unit
    re-derives, so the conflict-on-duplicate is observable in the id itself."""
    return f"nar:{run_id}:{submission_id}:{level}:{question_id}"


# --- the request and result types (FR-SYNTH-01/02/05, NFR-SYNTH-03) -------------------------------


@dataclass(frozen=True)
class CriterionVerdict:
    """One criterion's verdict as an L1 request carries it — the judge's band, and
    nothing numeric: there is no score field to carry a per-judge number through."""

    criterion_id: str
    judge_id: str
    band: str


@dataclass(frozen=True)
class L1Request:
    """The per-question request: ONE question's criteria, verdicts and evidence for
    ONE submission (`FR-SYNTH-01`, `FR-SYNTH-05` — exactly one `submission_id`)."""

    run_id: str
    submission_id: str
    question_id: str
    criterion_ids: tuple[str, ...]
    verdicts: tuple[CriterionVerdict, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class L2Request:
    """The test-level request: the L1 syntheses and NOTHING else (`NFR-SYNTH-03`).

    The boundary is the type itself — there is no field here that could carry a raw
    verdict (`CT-SYNTH-02`'s construction probe proves a smuggled one is refused), so
    the small model composing the test-level narrative cannot be handed the panel's
    verdicts no matter what a later change tries.
    """

    run_id: str
    submission_id: str
    syntheses: tuple[str, ...]


@dataclass(frozen=True)
class SynthesisResult:
    """One synthesized narrative — `{work_id, question_id, text}` at L1 and
    `{work_id, text}` at L2 (`CT-SYNTH-01`: the `question_id` is simply absent at L2).
    No numeric field exists to write a score into."""

    work_id: str
    question_id: str | None
    text: str


@dataclass(frozen=True)
class SynthesisReport:
    """The per-call report — the fourth seam's surface (`CT-SYNTH-12`).

    `model_calls` counts the provider calls actually made (retries included);
    `narratives` and `failures` are the failure rate's stored and failed counts;
    `sample` is the quality sample drawn for `M-STATS` with `sample_size` attached;
    the two citation rates are `None` exactly when the sample is empty.
    """

    model_calls: int
    narratives: int
    failures: int
    rejected_score_claims: int
    synthesis_failure_rate: float
    score_claim_rejection_rate: float
    mean_narrative_length: float
    sample: tuple[str, ...]
    sample_size: int
    citation_validity_rate: float | None
    hallucinated_claim_rate: float | None


# --- the fixed prompts (FR-SYNTH-01, CT-PROV-05's order contract) ---------------------------------

_DIRECTIVE_L1 = (
    "You write the per-question feedback narrative for one student's submission. "
    "Read the question's criterion verdicts and the evidence below; compose prose "
    "that states what the student's own work shows, anchored to the criteria and "
    "paraphrasing the evidence. State no mark, no score, no band and no overall "
    "quality verdict: the narrative never grades. Reply as JSON with a 'narrative' "
    "text and a 'citations' list of the criterion ids the narrative anchors to."
)

_DIRECTIVE_L2 = (
    "You write the whole-test narrative for one student's submission, from the "
    "per-question narratives below and nothing else. Compose prose that draws the "
    "threads of those narratives together. State no mark, no score, no band and no "
    "overall quality verdict: the narrative never grades. Reply as JSON with a "
    "'narrative' text and a 'citations' list of criterion ids if any are named."
)


def prompt_for(request: L1Request | L2Request) -> PromptPayload:
    """The rendered prompt, in a fixed field order — the payload the provider boundary
    hashes. The level is visible in the fields: an L1 request carries its question's
    criteria, verdicts and evidence; an L2 request carries ONLY the syntheses, because
    that is all the type can hold."""
    if isinstance(request, L1Request):
        verdict_lines = "\n".join(
            f"criterion={v.criterion_id} judge={v.judge_id} band={v.band}"
            for v in request.verdicts
        )
        return PromptPayload(
            fields=(
                ("directive", _DIRECTIVE_L1),
                ("prompt_template_v", SYNTH_PROMPT_TEMPLATE_V),
                ("level", LEVEL_L1),
                ("question", request.question_id),
                ("criteria", ", ".join(request.criterion_ids)),
                ("verdicts", verdict_lines or "(no verdicts)"),
                ("evidence", "\n\n".join(request.evidence) or "(no evidence spans)"),
                ("submission", request.submission_id),
            )
        )
    if isinstance(request, L2Request):
        return PromptPayload(
            fields=(
                ("directive", _DIRECTIVE_L2),
                ("prompt_template_v", SYNTH_PROMPT_TEMPLATE_V),
                ("level", LEVEL_L2),
                ("syntheses", "\n\n".join(request.syntheses)),
                ("submission", request.submission_id),
            )
        )
    raise TypeError(
        f"prompt_for renders an L1Request or an L2Request, got {type(request).__name__}"
    )


# --- reply parsing (FR-SYNTH-04) ------------------------------------------------------------------


def parse_narrative(text: str) -> tuple[str, tuple[str, ...]]:
    """Parse the synthesis reply into `(narrative text, citations)`.

    The reply is a JSON object whose `narrative` is the prose and whose `citations`
    list the criterion ids the narrative anchors to (`FR-SYNTH-04`). A reply that is
    not that shape raises `ValueError` — one strike, never a half-parsed narrative."""
    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as error:
        raise ValueError(f"synthesis reply is not JSON: {error}") from None
    if not isinstance(payload, dict) or "narrative" not in payload:
        raise ValueError("synthesis reply carries no 'narrative' member")
    narrative = payload["narrative"]
    if not isinstance(narrative, str) or not narrative.strip():
        raise ValueError("synthesis reply 'narrative' is not non-empty text")
    citations = payload.get("citations", ())
    if not isinstance(citations, (list, tuple)) or not all(
        isinstance(entry, str) for entry in citations
    ):
        raise ValueError("synthesis reply 'citations' must be a list of criterion ids")
    return narrative, tuple(citations)


# --- the reads ------------------------------------------------------------------------------------


def _payload_span_texts(payload: bytes) -> tuple[str, ...]:
    """The evidence texts a persisted span payload decodes to.

    The payload is `M-EXTRACT`'s evidence record (a JSON object of byte-offset spans
    into the canonical document); the span texts are what the L1 request reads.
    A payload that will not decode is logged and skipped — the narrative still anchors
    by citation, and `CT-SYNTH-08` says nothing here fails a grade."""
    try:
        record = json.loads(bytes(payload).decode("utf-8"))
        spans = record["spans"]
        return tuple(str(span["text"]) for span in spans if span.get("text"))
    except (KeyError, TypeError, ValueError) as error:
        LOGGER.error("evidence payload did not decode (%s) — spans skipped", error)
        return ()


class SynthesisWorker:
    """The synthesis driver: one submission's complete criteria in, the two-level
    narrative rows out.

    `SynthesisWorker(store, provider, model_ref)` — the store the narratives are read
    and written through, the provider boundary (injected; the recorded fixture
    provider stands in for the model), and the synthesis model (`role='synthesizer'`,
    the fifth model role).

    At-least-once safe (`CT-ORCH-04`): a narrative identity already stored absorbs the
    retry without a provider call, and the schema's declared key conflicts a
    concurrent duplicate rather than storing two.
    """

    def __init__(self, store: Any, provider: Any, model_ref: Any, *,
                 max_output_tokens: int | None = None) -> None:
        if getattr(model_ref, "role", None) != "synthesizer":
            raise ValueError(
                f"synthesis runs on the synthesizer model (role='synthesizer', "
                f"NFR-SYNTH-01's fifth role); got role={getattr(model_ref, 'role', None)!r}"
            )
        self._store = store
        self._provider = provider
        self._model_ref = model_ref
        self._max_output_tokens = max_output_tokens
        self._model_calls = 0

    # -- resolution -------------------------------------------------------------------------

    def _resolve_run(self, run_id: str) -> tuple[Any, Any]:
        """(cohort handle, run row) — found by walking the cohort files, the
        orchestrator's no-side-index discovery consumed rather than re-spelled."""
        for key in _cohort_keys_on_filesystem(self._store):
            cohort = self._store.cohort(key)
            rows = cohort.query(ORCH_STATEMENTS["select_run"], run_id=run_id)
            if rows:
                return cohort, rows[0]
        raise ValueError(
            f"no run row named {run_id!r} exists in any cohort ledger — synthesis "
            f"writes narratives beside the run they belong to."
        )

    def _catalog(self, run_row: Any) -> Any:
        """The run's package catalog — criterion text and the question mapping are
        `M-PKG`'s, version-pinned by the run row (`M-PKG` dependency, §3.13)."""
        return PackageCatalog(
            self._store.package(run_row["package_id"]),
            package_id=run_row["package_id"],
        )

    def _questions(self, catalog: Any, version: Any) -> "dict[str, tuple[str, ...]]":
        """The version's criteria grouped into questions, sorted by question id — the
        package's `question_id` mapping when the row carries one, the naming
        convention when it does not. A criterion that resolves to no question gets no
        L1 narrative (there is no question to name)."""
        grouped: dict[str, list[str]] = {}
        for row in catalog.criteria(version):
            question_id = _question_of_criterion(
                row["question_id"] or "", row["criterion_id"]
            )
            if question_id:
                grouped.setdefault(question_id, []).append(row["criterion_id"])
        return {q: tuple(ids) for q, ids in sorted(grouped.items())}

    # -- the reads a request is assembled from ----------------------------------------------

    def _verdicts(self, cohort: Any, units: list[dict],
                  criterion_id: str) -> tuple[CriterionVerdict, ...]:
        """One criterion's verdicts, off its done score units — the panel the L1
        narrative reads. ONLY this question's criteria's verdicts are read here; the
        L2 request has no field that could carry them at all."""
        verdicts: list[CriterionVerdict] = []
        for unit in units:
            if unit["criterion_id"] != criterion_id:
                continue
            for row in cohort.query(
                SYNTH_STATEMENTS["select_verdicts"], work_id=unit["work_id"]
            ):
                verdicts.append(
                    CriterionVerdict(
                        criterion_id=criterion_id,
                        judge_id=row["judge_id"],
                        band=row["band"],
                    )
                )
        return tuple(verdicts)

    def _evidence(self, cohort: Any, units: list[dict],
                  criterion_ids: tuple[str, ...],
                  submission_id: str) -> tuple[str, ...]:
        """The question's evidence: each criterion's evidence rows decoded from their
        persisted spans, falling back to the addressed document's markdown when the
        row carries no payload (the fixture-shaped ledger). The fallback reads only a
        document that belongs to THIS submission — the column is fetched to be
        checked, and a document addressing another student's work is skipped, never
        composed into the narrative (FR-SYNTH-05, submission isolation)."""
        texts: list[str] = []
        seen_documents: set[str] = set()
        for unit in units:
            if unit["criterion_id"] not in criterion_ids:
                continue
            for row in cohort.query(
                SYNTH_STATEMENTS["select_evidence"], work_id=unit["work_id"]
            ):
                if row["payload"] is not None:
                    texts.extend(_payload_span_texts(row["payload"]))
                    continue
                document_id = row["document_id"]
                if not document_id or document_id in seen_documents:
                    continue
                seen_documents.add(document_id)
                documents = cohort.query(
                    SYNTH_STATEMENTS["select_document"], document_id=document_id
                )
                if not documents or documents[0]["submission_id"] != submission_id:
                    LOGGER.error(
                        "evidence %s addresses document %s outside submission %s — "
                        "skipped, not composed (FR-SYNTH-05)",
                        row["evidence_id"], document_id, submission_id,
                    )
                    continue
                if documents[0]["markdown"]:
                    texts.append(documents[0]["markdown"])
        return tuple(texts)

    def _question_complete(self, cohort: Any, units: list[dict],
                           criterion_ids: tuple[str, ...]) -> bool:
        """The completeness gate (`FR-SYNTH-06`): every criterion of the question has
        a `done` score unit AND at least one verdict on it — both surfaces
        incompleteness shows at, so the gate is honest whichever one a deployment's
        failure leaves behind."""
        for criterion_id in criterion_ids:
            done = [
                unit for unit in units
                if unit["criterion_id"] == criterion_id and unit["status"] == "done"
            ]
            if not done:
                return False
            judged = any(
                cohort.query(
                    SYNTH_STATEMENTS["select_verdicts"], work_id=unit["work_id"]
                )
                for unit in done
            )
            if not judged:
                return False
        return True

    # -- the model call and the write -------------------------------------------------------

    def _call(self, payload: PromptPayload) -> tuple[str, tuple[str, ...]]:
        """One narrative's call: the strike budget (`HARNESS_SYNTH_MAX_ATTEMPTS`,
        defaulting to the ledger's own ceiling — one knob, one owner) against
        transport and parse failures alike. Raises the last error when the budget
        runs out; the caller records the failure and moves on (`CT-SYNTH-08`)."""
        params = SamplingParams(
            temperature=0.0,
            max_tokens=(
                self._max_output_tokens
                if self._max_output_tokens is not None
                else _env_int(MAX_OUTPUT_TOKENS_ENV, SYNTH_MAX_OUTPUT_TOKENS)
            ),
        )
        budget = _env_int(MAX_ATTEMPTS_SYNTH_ENV, ORCH_MAX_ATTEMPTS)
        last_error: Exception | None = None
        for _attempt in range(1, budget + 1):
            try:
                self._model_calls += 1
                completion = self._provider.complete(payload, self._model_ref, params)
                return parse_narrative(completion.text)
            except (ProviderError, ValueError) as error:
                last_error = error
        raise ValueError(f"synthesis did not answer after {budget} attempts: {last_error}")

    def _store_narrative(self, cohort: Any, *, run_id: str, submission_id: str,
                         level: str, question_id: str, text: str,
                         citations: tuple[str, ...]) -> bool:
        """One narrative row, keyed `(run_id, submission_id, level, question_id)`
        (ADR-8). Returns False when the key already holds a narrative: the declared
        primary key conflicted the duplicate instead of storing a second row, which
        is the retried unit's contract — the first narrative stands."""
        try:
            with cohort.transaction() as tx:
                tx.execute(
                    SYNTH_STATEMENTS["insert_narrative"],
                    narrative_id=narrative_work_id(
                        run_id, submission_id, level, question_id
                    ),
                    run_id=run_id,
                    submission_id=submission_id,
                    level=level,
                    question_id=question_id,
                    text=text,
                    citations=json.dumps(list(citations), sort_keys=True),
                    score_claim_flag=0,
                )
            return True
        except sqlite3.IntegrityError:
            LOGGER.warning(
                "narrative %s already stored — the retried synthesis unit conflicted "
                "with the declared key rather than duplicating (ADR-8)",
                narrative_work_id(run_id, submission_id, level, question_id),
            )
            return False

    def _stored(self, cohort: Any, run_id: str, submission_id: str) -> dict[tuple[str, str], dict]:
        """The submission's stored narratives, keyed `(level, question_id)` — what a
        retried synthesis absorbs into, and what L2 composes from."""
        return {
            (row["level"], row["question_id"]): dict(row)
            for row in cohort.query(
                SYNTH_STATEMENTS["select_narratives"],
                run_id=run_id,
                submission_id=submission_id,
            )
        }

    # -- the two levels ---------------------------------------------------------------------

    def synthesize_question(self, run_id: str, submission_id: str,
                            question_id: str) -> SynthesisResult:
        """One L1 composition (`FR-SYNTH-01`): that question's criterion verdicts and
        evidence for that ONE submission, one narrative row out.

        A question whose criteria are incomplete raises `ValueError` (`FR-SYNTH-06`:
        synthesis does not run for it — the driver skips the question instead of
        narrating a partial result as though it were whole). A narrative already
        stored for the identity absorbs the call: no provider call, the stored text
        returned."""
        cohort, run_row = self._resolve_run(run_id)
        catalog = self._catalog(run_row)
        criterion_ids = self._questions(catalog, run_row["package_version_id"]).get(
            question_id
        )
        if criterion_ids is None:
            raise ValueError(
                f"question {question_id!r} names no criteria in run {run_id!r}'s "
                f"package version — there is nothing for an L1 narrative to anchor to."
            )
        stored = self._stored(cohort, run_id, submission_id)
        if (LEVEL_L1, question_id) in stored:
            row = stored[(LEVEL_L1, question_id)]
            return SynthesisResult(
                work_id=row["narrative_id"], question_id=question_id, text=row["text"]
            )
        units = [
            dict(row)
            for row in cohort.query(
                SYNTH_STATEMENTS["select_score_units"],
                run_id=run_id,
                submission_id=submission_id,
            )
        ]
        if not self._question_complete(cohort, units, criterion_ids):
            raise ValueError(
                f"question {question_id!r} is incomplete for submission "
                f"{submission_id!r} — FR-SYNTH-06: synthesis does not run, because a "
                f"narrative describing a partial result as though it were whole is "
                f"feedback about work the student has not finished."
            )
        request = L1Request(
            run_id=run_id,
            submission_id=submission_id,
            question_id=question_id,
            criterion_ids=criterion_ids,
            verdicts=sum(
                (
                    self._verdicts(cohort, units, criterion_id)
                    for criterion_id in criterion_ids
                ),
                (),
            ),
            evidence=self._evidence(cohort, units, criterion_ids, submission_id),
        )
        text, citations = self._call(prompt_for(request))
        self._store_narrative(
            cohort,
            run_id=run_id,
            submission_id=submission_id,
            level=LEVEL_L1,
            question_id=question_id,
            text=text,
            citations=citations,
        )
        return SynthesisResult(
            work_id=narrative_work_id(run_id, submission_id, LEVEL_L1, question_id),
            question_id=question_id,
            text=text,
        )

    def synthesize_submission(self, run_id: str, submission_id: str) -> SynthesisReport:
        """The two-level driver (`FR-SYNTH-01`): L1 for each complete question, then
        one L2 composition reading only the L1 syntheses. The report is the
        operator-readable surface the fourth seam requires."""
        cohort, run_row = self._resolve_run(run_id)
        catalog = self._catalog(run_row)
        questions = self._questions(catalog, run_row["package_version_id"])

        failures = 0
        for question_id, criterion_ids in questions.items():
            stored = self._stored(cohort, run_id, submission_id)
            if (LEVEL_L1, question_id) in stored:
                continue  # the retried unit absorbs: the stored narrative stands
            units = [
                dict(row)
                for row in cohort.query(
                    SYNTH_STATEMENTS["select_score_units"],
                    run_id=run_id,
                    submission_id=submission_id,
                )
            ]
            if not self._question_complete(cohort, units, criterion_ids):
                continue  # the gate: no call, no narrative, nothing described as whole
            try:
                self.synthesize_question(run_id, submission_id, question_id)
            except (ProviderError, ValueError):
                failures += 1

        # L2 reads the STORED L1 narratives and nothing else — the type cannot carry a
        # verdict, and the driver never even assembles one at this level.
        stored = self._stored(cohort, run_id, submission_id)
        l1_rows = [
            row for (level, _question_id), row in sorted(stored.items())
            if level == LEVEL_L1
        ]
        if l1_rows and (LEVEL_L2, TEST_SENTINEL) not in stored:
            try:
                request = L2Request(
                    run_id=run_id,
                    submission_id=submission_id,
                    syntheses=tuple(row["text"] for row in l1_rows),
                )
                text, citations = self._call(prompt_for(request))
                self._store_narrative(
                    cohort,
                    run_id=run_id,
                    submission_id=submission_id,
                    level=LEVEL_L2,
                    question_id=TEST_SENTINEL,
                    text=text,
                    citations=citations,
                )
            except (ProviderError, ValueError):
                failures += 1

        return self._report(cohort, catalog, run_row, submission_id, failures)

    # -- the report -------------------------------------------------------------------------

    def _report(self, cohort: Any, catalog: Any, run_row: Any, submission_id: str,
                failures: int) -> SynthesisReport:
        """The report, computed from the STORED narratives — the mean and the sample
        describe the rows a student will actually read, not a counter that could
        drift from the table."""
        run_id = run_row["run_id"]
        rows = sorted(
            self._stored(cohort, run_id, submission_id).values(),
            key=lambda row: (row["level"], row["question_id"]),
        )
        narratives = len(rows)
        total = narratives + failures
        criterion_ids = {
            row["criterion_id"] for row in catalog.criteria(run_row["package_version_id"])
        }

        word_counts = [len(row["text"].split()) for row in rows]
        mean_length = sum(word_counts) / narratives if narratives else 0.0

        rate = _env_float(SAMPLE_RATE_ENV, SYNTH_SAMPLE_RATE)
        sample_size = min(narratives, max(1, int(rate * narratives + 0.5))) if narratives else 0
        sample_rows = rows[:sample_size]
        sample = tuple(row["text"] for row in sample_rows)

        if sample_rows:
            # Citation semantics, disclosed: a narrative is citation-VALID when every
            # citation it names is a criterion of this run's package, and it counts as
            # HALLUCINATING when any named citation is not. An EMPTY citation list is
            # valid under this reading — no claim reaches outside the package, and the
            # L2 row legitimately carries none — so an unanchored L1 narrative is a
            # validity the rate does not flag; a stricter per-claim anchoring metric is
            # #98's evidence-anchoring work, and the rates here stay measured, never
            # gated (§2.3 Q-06).
            valid_narratives = 0
            hallucinated_narratives = 0
            for row in sample_rows:
                try:
                    citations = tuple(json.loads(row["citations"] or "[]"))
                except ValueError:
                    citations = ()
                unknown = [c for c in citations if c not in criterion_ids]
                if unknown:
                    hallucinated_narratives += 1
                elif all(c in criterion_ids for c in citations):
                    valid_narratives += 1
            cited = len(sample_rows)
            citation_validity_rate = valid_narratives / cited
            hallucinated_claim_rate = hallucinated_narratives / cited
        else:
            citation_validity_rate = None
            hallucinated_claim_rate = None

        return SynthesisReport(
            model_calls=self._model_calls,
            narratives=narratives,
            failures=failures,
            # The score-claim check is #98's mechanism: until it lands nothing is
            # configured to reject, so the count and the rate honestly read zero.
            rejected_score_claims=0,
            synthesis_failure_rate=failures / total if total else 0.0,
            score_claim_rejection_rate=0.0,
            mean_narrative_length=mean_length,
            sample=sample,
            sample_size=len(sample),
            citation_validity_rate=citation_validity_rate,
            hallucinated_claim_rate=hallucinated_claim_rate,
        )


# --- the headless driver (the first seam) ---------------------------------------------------------


def synthesize(store: Any, provider: Any, model_ref: Any, run_id: str, *,
               submission_id: str) -> SynthesisReport:
    """Run one submission's two-level synthesis from code alone — the entry point a
    driver, a worker process or a test all reach for the same shape (`CT-CONSOLE-01`).
    Returns the same report the worker returns."""
    return SynthesisWorker(store, provider, model_ref).synthesize_submission(
        run_id, submission_id
    )


__all__ = [
    "LEVEL_L1",
    "LEVEL_L2",
    "MAX_ATTEMPTS_SYNTH_ENV",
    "MAX_OUTPUT_TOKENS_ENV",
    "SAMPLE_RATE_ENV",
    "SCORE_CLAIM_FLAG",
    "SYNTH_MAX_OUTPUT_TOKENS",
    "SYNTH_PROMPT_TEMPLATE_V",
    "SYNTH_SAMPLE_RATE",
    "SYNTH_STATEMENTS",
    "L1Request",
    "L2Request",
    "CriterionVerdict",
    "SynthesisResult",
    "SynthesisReport",
    "SynthesisWorker",
    "narrative_work_id",
    "parse_narrative",
    "prompt_for",
    "synthesize",
    "TEST_SENTINEL",
]

