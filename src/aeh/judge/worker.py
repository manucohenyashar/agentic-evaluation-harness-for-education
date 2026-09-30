"""`ScoringWorker`: judges one leased score unit and stores the verdict."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from aeh.orch import ORCH_MAX_ATTEMPTS, ORCH_STATEMENTS, _env_float, _env_int, _judge_id_of
from aeh.prov import (
    BuildChangedError,
    MalformedResponseError,
    ProviderError,
    ProviderUnavailableError,
    RateLimitedError,
    SamplingParams,
)
from aeh.store import lease_clock

from .schema import JUDGE_STATEMENTS
from .settings import (
    ASSESSMENT_AMENDED,
    ASSESSMENT_RETRIES_DEFAULT,
    ASSESSMENT_RETRIES_ENV,
    JUDGE_TEMPERATURE,
    MAX_ATTEMPTS_ENV,
    MAX_OUTPUT_TOKENS_ENV,
    TEMPERATURE_ENV,
)
from .errors import JudgmentError, ProseAssessmentError
from .request import ScoringRequest
from .results import ScoringResult
from .prompt import prompt_fields, _span_document
from .assembly import assemble, _field_of, _find_cohort
from .replies import _amended_payload, _refuse_unverified_citations, _verdict_of
from .decision_engine import (
    Accepted,
    BelowGate,
    decision_eligibility,
    decision_request,
    gate_decision,
    Ineligible,
    _ordered_bands,
    scan_decision_request,
)


class ScoringWorker:
    """Runs judging for one leased score unit: the unit in, a verdict row out.

    `ScoringWorker(store, provider, judge)` — the store the rubric and evidence read
    from and the verdict written through, the provider boundary (injected;
    `RecordedFixtureProvider` stands in for the model and stays the only egress), and
    the judge's own ref for when the unit carries none. Every argument has a default,
    because `assemble` is PURE (§3.10: "`# pure, testable`") — the rung-0 cases drive
    `ScoringWorker()` with nothing bound at all, and only `dispatch`/`persist` need the
    seams. `assemble(unit)` keeps the design's one-argument signature: no second
    criterion-shaped parameter can exist for a multi-criterion prompt to return through
    (`FR-JUDGE-16`).
    """

    def __init__(self, store: Any = None, provider: Any = None, judge: Any = None, *,
                 decision_provider: Any = None, run_config: Any = None) -> None:
        self._store = store
        self._provider = provider
        self._judge = judge
        #: Jev design delta FR-JUDGE-22: the decision provider and the frozen run config (its
        #: engine and panel). With either absent, `dispatch` is byte-identical to today's.
        self._decision_provider = decision_provider
        self._run_config = run_config

    def assemble(self, unit: Any) -> ScoringRequest:
        """Build the whitelisted request for one unit. It takes exactly one parameter.

        The request itself stays pure. Beside it, the worker remembers the unit's roster name
        by `work_id` (#593): the request never carries the name, but the citation gate needs
        it to verify a span whose text assembly pseudonymized (`_verifies_as_pseudonymized`).
        """
        request = assemble(unit, store=self._store)
        name = _field_of(unit, "student_name")
        if isinstance(name, str) and name:
            self.__dict__.setdefault("_roster_names", {})[request.work_id] = name
        return request

    def _roster_name_of(self, request: ScoringRequest) -> Any:
        """The roster name `assemble` saw for this request's unit, or None (#593)."""
        return self.__dict__.get("_roster_names", {}).get(request.work_id)

    def dispatch(self, request: ScoringRequest, judge: Any) -> ScoringResult:
        """Produce one verdict for one unit (FR-JUDGE-22, FR-JUDGE-31). On the decision seat, with
        an engine configured, the decision engine answers first and its answer is the verdict when
        the gate passes. Otherwise, and for every other unit, the LLM path runs unchanged, with
        exactly the request it would send with the engine off (CT-JUDGE-22)."""
        engine = getattr(self._run_config, "decision_engine", None)
        prescreen_outcome: str | None = None
        if (engine is not None and self._decision_provider is not None
                and self._is_seat(judge)):
            outcome = self._prescreen(request, engine, judge)
            if isinstance(outcome, ScoringResult):
                return outcome
            prescreen_outcome = outcome
        result = self._dispatch_llm(request, judge)
        return dataclasses.replace(result, scoring_engine="llm",
                                   engine_build=result.resolved_build,
                                   prescreen_outcome=prescreen_outcome)

    def _is_seat(self, judge: Any) -> bool:
        """Whether the arm being dispatched is the decision seat, the frozen `RunConfig.panel[0]`
        (FR-JUDGE-23). Same answer as `is_decision_seat(unit, run_config)`."""
        panel = getattr(self._run_config, "panel", ()) or ()
        return bool(panel) and _judge_id_of(judge) == panel[0].build_id

    def _dispatch_llm(self, request: ScoringRequest, judge: Any) -> ScoringResult:
        """Send one assembled request to the model and parse the reply.

        Temperature zero by default — judgment is not a sampling task — with the knob
        (`HARNESS_JUDGE_TEMPERATURE`) and the output cap (`HARNESS_JUDGE_MAX_OUTPUT_
        TOKENS`) read at call time, and the retry budget is `HARNESS_JUDGE_MAX_
        ATTEMPTS` (production default `ORCH_MAX_ATTEMPTS`). Each refused reply (a
        transport failure, a malformed or re-ordered reply, a band outside the
        declared set, a citation that fails byte-exact verification against the
        canonical document — `FR-JUDGE-17`'s grounding gate) is a strike; when the
        budget runs out the refusal surfaces as `JudgmentError` — there is NO
        fallback verdict on any path (`NFR-JUDGE-05`), and nothing has been persisted.

        One refusal earns a MODIFIED prompt rather than a replay: a reply refused as
        `ProseAssessmentError` (magnitude-only `evidence_assessment`, `FR-JUDGE-10`)
        re-requests ONCE — the `HARNESS_JUDGE_ASSESSMENT_RETRIES` budget, default one —
        with the assessment ground-rules amendment inserted before the submission field
        (`_amended_payload`). The amended render is a different fully-assembled request,
        so the re-request is a new call, never a re-sampled verdict (`FR-PROV-06`); the
        re-request is logged in the strikes and accepted with the `ASSESSMENT_AMENDED`
        integrity flag. A prose-only reply that recurs after the amendment budget is
        spent strikes like any other refusal.
        """
        if not isinstance(request, ScoringRequest):
            raise TypeError(
                f"dispatch sends a ScoringRequest, got {type(request).__name__}"
            )
        if self._provider is None:
            raise JudgmentError(
                "no provider bound to this worker — the model boundary is injected "
                "(the third seam's knob is the strike budget, not the boundary itself)"
            )
        payload = prompt_fields(request)
        params = SamplingParams(
            temperature=_env_float(
                TEMPERATURE_ENV, JUDGE_TEMPERATURE, low=0.0, high=2.0
            ),
            max_tokens=_env_int(MAX_OUTPUT_TOKENS_ENV, 0) or None,
        )
        budget = _env_int(MAX_ATTEMPTS_ENV, ORCH_MAX_ATTEMPTS)
        amendment_budget = _env_int(ASSESSMENT_RETRIES_ENV, ASSESSMENT_RETRIES_DEFAULT)
        strikes: list[str] = []
        integrity_flags: list[str] = []
        amendments_used = 0
        violations = 0
        last_error: Exception | None = None
        for attempt in range(1, budget + 1):
            try:
                completion = self._provider.complete(payload, judge, params)
                verdict = _verdict_of(completion.text, request)
                # FR-JUDGE-17's third defence, composed here: the reply's citations,
                # verified byte-exactly against the canonical document BEFORE the
                # verdict can exist. Inside the same try — a failed verification is a
                # MalformedResponseError like any other contract refusal, struck within
                # the budget and never persisted (an obeying reply is routed out, not
                # obeyed). Vacuous for an uncited reply.
                _refuse_unverified_citations(verdict.cited_spans, request, self._store,
                                             self._roster_name_of(request))
            except (RateLimitedError, ProviderUnavailableError, BuildChangedError):
                # `FR-JUDGE-19` / `CT-JUDGE-19`: the provider taxonomy is not a refusal of the
                # reply — no strike, no FR-JUDGE-10 amended re-request, nothing persisted. It
                # propagates for the dispatch pass to wait or pause on. Violations this
                # dispatch already counted are still the judge's, so they are recorded before
                # the error leaves: an outage after a malformed reply must not erase it.
                self._record_contract_violations(request, judge, violations)
                raise
            except (ProviderError, ValueError) as error:
                last_error = error
                strikes.append(f"attempt {attempt}/{budget}: {error}")
                if isinstance(error, (MalformedResponseError, ValueError)):
                    # A reply that broke the response contract (FR-JUDGE-21) — a transport
                    # failure answered nothing and is not the judge's violation.
                    violations += 1
                if isinstance(error, ProseAssessmentError) and amendments_used < amendment_budget:
                    amendments_used += 1
                    payload = _amended_payload(payload)
                    if ASSESSMENT_AMENDED not in integrity_flags:
                        integrity_flags.append(ASSESSMENT_AMENDED)
                    strikes.append(
                        f"attempt {attempt}/{budget}: evidence_assessment re-requested "
                        f"with an amended prompt "
                        f"({amendments_used}/{amendment_budget}, FR-JUDGE-10)"
                    )
                continue
            self._record_contract_violations(request, judge, violations)
            return ScoringResult(
                work_id=request.work_id,
                judge_id=_judge_id_of(judge),
                band=verdict.band,
                band_ordinal=verdict.band_ordinal,
                self_confidence=verdict.self_confidence,
                cited_spans=verdict.cited_spans,
                uncited=not verdict.cited_spans,
                evidence_assessment=verdict.evidence_assessment,
                evidence_sufficient=verdict.evidence_sufficient,
                resolved_build=completion.resolved_build,
                attempts=attempt,
                notes="; ".join(strikes) or None,
                prefix_bytes=sum(
                    len(value.encode("utf-8")) for _name, value in payload.fields[:-1]
                ),
                total_bytes=sum(
                    len(value.encode("utf-8")) for _name, value in payload.fields
                ),
                integrity_flags=tuple(integrity_flags),
                latency_ms=int(completion.latency_ms),
            )
        self._record_contract_violations(request, judge, violations)
        raise JudgmentError(
            f"judgment for {request.work_id[:12]} refused after {budget} attempt(s); "
            f"last refusal: {last_error}. No fallback verdict exists (NFR-JUDGE-05)."
        )


    # -- the decision-seat pre-screen (FR-JUDGE-30…34) -------------------------------------------

    def _unit_keys(self, work_id: str) -> dict[str, str]:
        cohort = _find_cohort(self._store, work_id)
        row = cohort.query(JUDGE_STATEMENTS["select_work_unit"], work_id=work_id)[0]
        return {"run_id": row["run_id"], "submission_id": row["submission_id"],
                "criterion_id": row["criterion_id"]}

    def _write_prescreen(self, request: ScoringRequest, engine: Any, outcome: str, *,
                         reason: str | None = None, decision: Any = None,
                         gate: float | None = None, argmax_band: str | None = None) -> None:
        """Record one pre-screen row per decision-seat unit (insert-or-ignore on the work id), in
        its own transaction before the LLM path or `persist` (FR-JUDGE-34). A worker without a
        store records nothing."""
        if self._store is None:
            return
        keys = self._unit_keys(request.work_id)
        answers = getattr(decision, "answers", None) or {}
        band = answers.get("band")
        sufficiency = answers.get("evidence_sufficient")
        cites = {key[len("cite_"):]: float(answer.p_true)
                 for key, answer in answers.items() if key.startswith("cite_")}
        cohort = _find_cohort(self._store, request.work_id)
        with cohort.transaction() as tx:
            tx.execute(
                JUDGE_STATEMENTS["insert_prescreen"],
                work_id=request.work_id,
                run_id=keys["run_id"], submission_id=keys["submission_id"],
                criterion_id=keys["criterion_id"],
                engine_build=(decision.resolved_build if decision is not None else engine.model.build_id),
                outcome=outcome, reason=reason,
                gate_confidence=gate,
                band_confidence=None if band is None else float(band.confidence),
                sufficiency_p=None if sufficiency is None else float(sufficiency.p_true),
                argmax_band=argmax_band,
                band_probabilities=None if band is None else json.dumps(list(band.probabilities)),
                band_score=None if band is None else float(band.score),
                cite_probabilities=None if band is None else json.dumps(cites, sort_keys=True),
                threshold=float(engine.confidence_threshold),
                tokens_in=None if decision is None else int(decision.tokens_in),
                latency_ms=None if decision is None else int(decision.latency_ms),
                cost=None if decision is None or decision.cost is None else str(decision.cost),
            )

    def _stored_prescreen(self, work_id: str) -> Any:
        if self._store is None:
            return None
        rows = _find_cohort(self._store, work_id).query(JUDGE_STATEMENTS["select_prescreen"], work_id=work_id)
        return rows[0] if rows else None

    @staticmethod
    def _decision_from_row(row: Any) -> Any:
        """Rebuild the accepted decision from its stored pre-screen row (FR-JUDGE-33), so a
        redelivered unit gives the same verdict without calling the engine again."""
        from types import MappingProxyType

        from aeh.prov import Decision as _Decision, NoulAnswer, ScoreAnswer

        probabilities = tuple(float(p) for p in json.loads(row["band_probabilities"]))
        p_suff = float(row["sufficiency_p"])
        answers: dict[str, Any] = {
            "band": ScoreAnswer(float(row["band_score"]), probabilities,
                                float(row["band_confidence"]), "reported"),
            # Design 1.8 (FR-PROV-19): a Noul's confidence is its `p`, never `|2p − 1|`, so the
            # rebuilt gate equals the one the first dispatch passed.
            "evidence_sufficient": NoulAnswer(p_suff, p_suff, "reported"),
        }
        for label, p in json.loads(row["cite_probabilities"] or "{}").items():
            answers[f"cite_{label}"] = NoulAnswer(float(p), float(p), "reported")
        return _Decision(MappingProxyType(answers), int(row["tokens_in"] or 0), 0,
                         int(row["latency_ms"] or 0), row["engine_build"], None)

    def _prescreen(self, request: ScoringRequest, engine: Any, judge: Any) -> "ScoringResult | str":
        """The decision seat's pre-screen. Returns the engine's verdict when the gate passes,
        otherwise the outcome name (`ineligible`, `below_gate`, `rejected` or `malformed`) for the
        LLM fallback to record. Engine outages (`RateLimitedError`, `ProviderUnavailableError`,
        `BuildChangedError`) are raised: an outage pauses the run and is never a fallback
        (FR-JUDGE-32, CT-JUDGE-25)."""
        from aeh.prov import DecisionRequestRejectedError

        judge_id = _judge_id_of(judge)
        stored = self._stored_prescreen(request.work_id)
        if stored is not None:  # FR-JUDGE-33: one engine sample per unit, ever
            if stored["outcome"] != "accepted":
                return stored["outcome"]
            outcome = gate_decision(self._decision_from_row(stored), request, engine, judge_id=judge_id)
            if isinstance(outcome, Accepted):
                return outcome.result
            return "below_gate"
        capabilities = self._decision_provider.decision_capabilities(engine.model)
        eligibility = decision_eligibility(request, engine, capabilities)
        if isinstance(eligibility, Ineligible):
            self._write_prescreen(request, engine, "ineligible", reason=eligibility.reason)
            return "ineligible"
        from aeh.prov import DecisionRequestError

        try:
            decision_req = decision_request(request, engine)
        except DecisionRequestError as error:
            # Design §3.3 error handling: a request that cannot be built is a harness defect,
            # a strike, surfaced as JudgmentError (the executor's strike path), never a fallback.
            raise JudgmentError(f"the decision request for {request.work_id[:12]} cannot be built: {error}") from error
        scan_decision_request(request, decision_req)
        try:
            decision = self._decision_provider.decide(decision_req, engine.model)
        except DecisionRequestError as error:
            raise JudgmentError(
                f"the decision request for {request.work_id[:12]} exceeds the engine's declared "
                f"limits: {error}") from error
        except DecisionRequestRejectedError:
            self._write_prescreen(request, engine, "rejected", reason="rejected")
            return "rejected"
        except MalformedResponseError:
            self._write_prescreen(request, engine, "malformed", reason="malformed")
            return "malformed"
        outcome = gate_decision(decision, request, engine, judge_id=judge_id)
        bands = _ordered_bands(request)
        top = max(range(len(bands)), key=lambda i: decision.answers["band"].probabilities[i])
        if isinstance(outcome, BelowGate):
            self._write_prescreen(request, engine, "below_gate", reason=outcome.reason,
                                  decision=decision, gate=outcome.gate, argmax_band=bands[top].band)
            return "below_gate"
        try:
            # FR-JUDGE-30: cited spans must be the document's own bytes before the verdict exists.
            _refuse_unverified_citations(outcome.result.cited_spans, request, self._store,
                                         self._roster_name_of(request))
        except MalformedResponseError:
            self._write_prescreen(request, engine, "below_gate", reason="citation_unverified",
                                  decision=decision, gate=outcome.gate, argmax_band=bands[top].band)
            return "below_gate"
        self._write_prescreen(request, engine, "accepted", decision=decision, gate=outcome.gate,
                              argmax_band=outcome.result.band)
        return outcome.result

    def _record_contract_violations(
        self, request: ScoringRequest, judge: Any, violations: int
    ) -> None:
        """Add this dispatch's response-contract violations to the run's count per (criterion,
        judge) (FR-JUDGE-21). Nothing is written when there are none, or when the worker has no
        store.

        The count is of violating **responses**, not of units: it accumulates on conflict, so
        a redelivered unit's fresh provider calls add their own refusals rather than replacing
        the earlier ones — the rate `judge_signals` reads is over what judges actually
        returned. A `ProseAssessmentError` amended under `FR-JUDGE-10` is a refused reply like
        any other and counts."""
        if not violations or self._store is None:
            return
        try:
            cohort = _find_cohort(self._store, request.work_id)
        except ValueError:
            return  # no ledger row to name the run by — nothing to attribute the count to
        rows = cohort.query(JUDGE_STATEMENTS["select_work_unit"], work_id=request.work_id)
        with self._store.durable().transaction() as tx:
            tx.execute(
                JUDGE_STATEMENTS["add_contract_violations"],
                run_id=rows[0]["run_id"],
                n=float(violations),
                criterion_id=request.criterion.criterion_id,
                judge_id=_judge_id_of(judge),
            )

    def persist(self, unit: Any, result: ScoringResult) -> None:
        """Write one verdict row and mark the unit done, in one guarded transaction.

        The verdict row is insert-or-ignore on `verdict_id = work_id`. It carries the band, the
        band's position in the declared set, the judge's own confidence, the cited spans, the
        sufficiency answer and the uncited mark, and never a score value (FR-JUDGE-11). Marking
        the unit done only applies to a leased or pending unit, in the same transaction, so running
        twice cannot write twice; if another completion landed first, its row stands."""
        if self._store is None:
            raise JudgmentError(
                "no store bound to this worker — persist writes through the store the "
                "constructor was given"
            )
        cohort = _find_cohort(self._store, result.work_id)
        # The identity dispatch actually used comes first (the result carries what the
        # provider call was addressed by); the unit's own naming next; the worker's
        # bound judge last — and a judge that names no build identity is a
        # `JudgmentError` here, not the orchestrator's escalation error: persist is
        # the judge boundary, and its failures are judgment failures.
        judge_id = (
            result.judge_id
            or _field_of(unit, "judge")
            or _field_of(unit, "judge_id")
        )
        if not judge_id:
            try:
                judge_id = _judge_id_of(self._judge)
            except Exception as error:
                raise JudgmentError(
                    f"persist cannot name the judge for {result.work_id[:12]}: {error}"
                ) from error
        with cohort.transaction() as tx:
            tx.execute(
                ORCH_STATEMENTS["mark_done"],
                work_id=result.work_id,
                done_ticks=lease_clock(self._store).ticks(),
            )
            won = int(tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"])
            if won:
                # The response contract, persisted (`CT-JUDGE-06`): the cited-span
                # inventory as a JSON array — `NULL` when the reply cited nothing, a
                # null being FR-JUDGE-12's uncited verdict, persisted and marked below,
                # never discarded (a discarded verdict would shrink a three-judge panel
                # to two, which FR-AGG-03 forbids) — plus the sufficiency answer and
                # the uncited mark. No points value is written anywhere: the verdict
                # carries a band and its ordinal, and the table has no points column
                # (FR-JUDGE-11).
                tx.execute(
                    JUDGE_STATEMENTS["insert_verdict"],
                    verdict_id=result.work_id,
                    work_id=result.work_id,
                    judge_id=judge_id,
                    band=result.band,
                    band_ordinal=int(result.band_ordinal),
                    self_confidence=float(result.self_confidence),
                    cited_spans=(
                        json.dumps(
                            [_span_document(span) for span in result.cited_spans],
                            sort_keys=True,
                        )
                        if result.cited_spans
                        else None
                    ),
                    evidence_sufficient=int(bool(result.evidence_sufficient)),
                    uncited=int(bool(result.uncited)),
                    evidence_assessment=result.evidence_assessment,
                    latency_ms=result.latency_ms,
                    # FR-JUDGE-35: provenance on every row this module writes.
                    scoring_engine=getattr(result, "scoring_engine", "llm") or "llm",
                    engine_build=getattr(result, "engine_build", None),
                )
