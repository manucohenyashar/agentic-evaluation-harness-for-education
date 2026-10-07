"""`SynthesisWorker`: runs the two synthesis levels for one submission and stores the results."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from aeh.orch import ORCH_MAX_ATTEMPTS, ORCH_STATEMENTS, _cohort_keys_on_filesystem, _env_int
from aeh.pkg import PackageCatalog, is_composite
from aeh.prov import PromptPayload, ProviderError, SamplingParams

from .schema import SYNTH_STATEMENTS
from .settings import (
    _env_float,
    LEVEL_L1,
    LEVEL_L2,
    LOGGER,
    MAX_ATTEMPTS_SYNTH_ENV,
    MAX_OUTPUT_TOKENS_ENV,
    SAMPLE_RATE_ENV,
    SCORE_CLAIM_FLAG,
    SYNTH_MAX_OUTPUT_TOKENS,
    SYNTH_SAMPLE_RATE,
    TEST_SENTINEL,
)
from .score_claims import has_score_claim
from .records import (
    CriterionVerdict,
    L1Request,
    L2Request,
    narrative_work_id,
    _question_of_criterion,
    SynthesisReport,
    SynthesisResult,
)
from .prompts import parse_narrative, _payload_span_texts, prompt_for


class SynthesisWorker:
    """Runs synthesis for one submission: takes its fully scored criteria and writes the L1 and L2
    narrative rows.

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
        # The score-claim ladder's counters (`CT-SYNTH-12`): every model output that
        # parsed carries a claim check, and every claim it carried is a rejection the
        # report owes the operator. They are inputs to the report, and the report is
        # per driver call, so `synthesize_submission` resets them at entry — a worker
        # reused across submissions reports each submission's rejection rate, not a
        # lifetime blend (`_model_calls` follows the same per-call scope).
        self._parsed_outputs = 0
        self._rejected_score_claims = 0

    # -- resolution -------------------------------------------------------------------------

    def _resolve_run(self, run_id: str) -> tuple[Any, Any]:
        """Find `(cohort handle, run row)` for the run by walking the cohort files, the same way
        the orchestrator finds runs."""
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
        """The run's package catalog, pinned to the run's package version. Criterion text and the
        question mapping come from M-PKG."""
        return PackageCatalog(
            self._store.package(run_row["package_id"]),
            package_id=run_row["package_id"],
        )

    def _questions(self, catalog: Any, version: Any) -> "dict[str, tuple[str, ...]]":
        """The version's criteria grouped by question and sorted by question id, using the
        package's `question_id` when a criterion has one and the naming convention otherwise. A
        criterion with no question gets no L1 narrative."""
        grouped: dict[str, list[str]] = {}
        for row in catalog.criteria(version):
            # A composite has no score unit of its own (FR-JUDGE-38): its aspects stand for it,
            # and waiting on it would leave the question never complete.
            if is_composite(row):
                continue
            question_id = _question_of_criterion(
                row["question_id"] or "", row["criterion_id"]
            )
            if question_id:
                grouped.setdefault(question_id, []).append(row["criterion_id"])
        return {q: tuple(ids) for q, ids in sorted(grouped.items())}

    # -- the reads a request is assembled from ----------------------------------------------

    def _verdicts(self, cohort: Any, units: list[dict],
                  criterion_id: str) -> tuple[CriterionVerdict, ...]:
        """One criterion's verdicts, read from its completed score units. Only this question's
        verdicts are read; an L2 request has no field that could carry them."""
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
        """The question's evidence: each criterion's evidence rows decoded from their stored spans,
        or the document's Markdown when a row has no span payload. That fallback only reads a
        document that belongs to this submission."""
        texts: list[str] = []
        seen_documents: set[str] = set()
        for unit in units:
            if unit["criterion_id"] not in criterion_ids:
                continue
            for row in cohort.query(
                SYNTH_STATEMENTS["select_synth_evidence"], work_id=unit["work_id"]
            ):
                if row["payload"] is not None:
                    texts.extend(_payload_span_texts(row["payload"]))
                    continue
                document_id = row["document_id"]
                if not document_id or document_id in seen_documents:
                    continue
                seen_documents.add(document_id)
                documents = cohort.query(
                    SYNTH_STATEMENTS["select_synth_document"], document_id=document_id
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
        """Whether the question is ready to narrate: every criterion has a completed score unit and
        at least one verdict (FR-SYNTH-06). Checking both catches either way a failure can leave
        the question incomplete."""
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

    def _call(self, payload: PromptPayload) -> "tuple[str, tuple[str, ...], bool]":
        """Make one narrative's model call. Transport and parse failures share one attempt budget
        (`HARNESS_SYNTH_MAX_ATTEMPTS`, defaulting to the ledger's own limit), and every reply that
        parses goes through the score-claim check (CT-SYNTH-03).

        The ladder is the design's own two-step, not a knob: an output matching
        `SYNTH_SCORE_CLAIM_PATTERNS` is rejected and re-requested **once**; a second
        matching output is terminal — returned with its flag set, so the caller stores
        it suppressed rather than shown (`CT-SYNTH-03`), and the rejection is counted
        for the rate `CT-SYNTH-12` alerts on. Returns `(text, citations, flagged)`;
        raises the last error when the transport/parse budget runs out, and the caller
        records the failure and moves on (`CT-SYNTH-08` — nothing here fails a
        grade)."""
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
        claims_seen = 0
        for _attempt in range(1, budget + 1):
            try:
                self._model_calls += 1
                completion = self._provider.complete(payload, self._model_ref, params)
                text, citations = parse_narrative(completion.text)
            except (ProviderError, ValueError) as error:
                last_error = error
                continue
            self._parsed_outputs += 1
            if not has_score_claim(text):
                return text, citations, False
            claims_seen += 1
            self._rejected_score_claims += 1
            if claims_seen >= 2:
                # The re-request also claimed: stored flagged and suppressed, never
                # shown — and never deleted, which would erase the count above.
                LOGGER.warning(
                    "narrative claimed a score twice — stored with %s set and "
                    "suppressed rather than shown (CT-SYNTH-03)",
                    SCORE_CLAIM_FLAG,
                )
                return text, citations, True
            # First claim: rejected and re-requested — exactly one more attempt.
            LOGGER.info("narrative rejected on a score claim — re-requested once")
        if claims_seen:
            # The budget ran out while a claim was outstanding — with a very small
            # knob the model DID answer, it claimed; the error must say that, not
            # "did not answer".
            raise ValueError(
                f"synthesis produced no acceptable narrative after {budget} attempts: "
                f"the last output claimed a score and no clean replacement arrived "
                f"(last transport/parse error: {last_error})"
            )
        raise ValueError(f"synthesis did not answer after {budget} attempts: {last_error}")

    def _store_narrative(self, cohort: Any, *, run_id: str, submission_id: str,
                         level: str, question_id: str, text: str,
                         citations: tuple[str, ...],
                         score_claim_flag: int = 0) -> bool:
        """Store one narrative row, keyed `(run_id, submission_id, level, question_id)` (ADR-8).
        `score_claim_flag` is 0 when the narrative passed the score-claim check and 1 when it
        failed twice; a flagged text is kept for the record but not shown (CT-SYNTH-03). Returns
        False when the key already holds a row."""
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
                    score_claim_flag=score_claim_flag,
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
        """The submission's stored narratives, keyed `(level, question_id)`. A retried synthesis
        reuses these, and L2 is composed from them."""
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
        """Write one question's L1 narrative from its criterion verdicts and evidence, for this one
        submission (FR-SYNTH-01).

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
                SYNTH_STATEMENTS["select_synth_score_units"],
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
        text, citations, flagged = self._call(prompt_for(request))
        self._store_narrative(
            cohort,
            run_id=run_id,
            submission_id=submission_id,
            level=LEVEL_L1,
            question_id=question_id,
            text=text,
            citations=citations,
            score_claim_flag=1 if flagged else 0,
        )
        return SynthesisResult(
            work_id=narrative_work_id(run_id, submission_id, LEVEL_L1, question_id),
            question_id=question_id,
            text=text,
        )

    def synthesize_submission(self, run_id: str, submission_id: str) -> SynthesisReport:
        """Run both levels for one submission: an L1 narrative for each complete question, then one
        L2 narrative composed from the L1 narratives only (FR-SYNTH-01). Returns the report
        operators read."""
        cohort, run_row = self._resolve_run(run_id)
        catalog = self._catalog(run_row)
        questions = self._questions(catalog, run_row["package_version_id"])

        # The report is per driver call, so the counters reset here: the rejection
        # rate's denominator is THIS call's parsed outputs, the same scope as the
        # failure rate computed on the same report (the reviewer's #98 finding on
        # mixed scopes for a reused worker). A standalone `synthesize_question`
        # call's counts fall outside every report window — only the driver produces
        # a report; the headless entry point constructs a fresh worker per call.
        self._model_calls = 0
        self._parsed_outputs = 0
        self._rejected_score_claims = 0

        failures = 0
        for question_id, criterion_ids in questions.items():
            stored = self._stored(cohort, run_id, submission_id)
            if (LEVEL_L1, question_id) in stored:
                continue  # the retried unit absorbs: the stored narrative stands
            units = [
                dict(row)
                for row in cohort.query(
                    SYNTH_STATEMENTS["select_synth_score_units"],
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
        # verdict, and the driver never even assembles one at this level. A narrative
        # the score-claim check flagged is suppressed here too (`CT-SYNTH-03`): a
        # caught claim must not reach the student through the level that re-states the
        # per-question prose, so the flagged row is withheld from composition exactly
        # as it is withheld from display.
        stored = self._stored(cohort, run_id, submission_id)
        l1_rows = [
            row for (level, _question_id), row in sorted(stored.items())
            if level == LEVEL_L1 and not row["score_claim_flag"]
        ]
        if l1_rows and (LEVEL_L2, TEST_SENTINEL) not in stored:
            try:
                request = L2Request(
                    run_id=run_id,
                    submission_id=submission_id,
                    syntheses=tuple(row["text"] for row in l1_rows),
                )
                text, citations, flagged = self._call(prompt_for(request))
                self._store_narrative(
                    cohort,
                    run_id=run_id,
                    submission_id=submission_id,
                    level=LEVEL_L2,
                    question_id=TEST_SENTINEL,
                    text=text,
                    citations=citations,
                    score_claim_flag=1 if flagged else 0,
                )
            except (ProviderError, ValueError):
                failures += 1

        return self._report(cohort, catalog, run_row, submission_id, failures)

    # -- the report -------------------------------------------------------------------------

    def _report(self, cohort: Any, catalog: Any, run_row: Any, submission_id: str,
                failures: int) -> SynthesisReport:
        """Build the report from the stored narratives, so its figures describe what synthesis
        actually wrote. A flagged narrative is stored but hidden from display, and it is still
        counted here (#98)."""
        run_id = run_row["run_id"]
        rows = sorted(
            self._stored(cohort, run_id, submission_id).values(),
            key=lambda row: (row["level"], row["question_id"]),
        )
        narratives = len(rows)
        total = narratives + failures
        criteria_rows = [
            row for row in catalog.criteria(run_row["package_version_id"])
            if not is_composite(row)  # anchored through its aspects, as `_questions` groups
        ]
        criterion_ids = {row["criterion_id"] for row in criteria_rows}
        # The per-question anchoring map (`FR-SYNTH-04`, #98's stricter form): the
        # criteria each question's L1 narrative must anchor to — the same mapping the
        # request assembly used, so a narrative is measured against the criteria whose
        # evidence that student's own work fed it.
        criteria_by_question: "dict[str, set[str]]" = {}
        for row in criteria_rows:
            question_id = _question_of_criterion(row["question_id"] or "", row["criterion_id"])
            if question_id:
                criteria_by_question.setdefault(question_id, set()).add(row["criterion_id"])

        word_counts = [len(row["text"].split()) for row in rows]
        mean_length = sum(word_counts) / narratives if narratives else 0.0

        rate = _env_float(SAMPLE_RATE_ENV, SYNTH_SAMPLE_RATE)
        sample_size = min(narratives, max(1, int(rate * narratives + 0.5))) if narratives else 0
        sample_rows = rows[:sample_size]
        sample = tuple(row["text"] for row in sample_rows)

        if sample_rows:
            # Citation semantics, disclosed (#98's per-claim form, replacing the
            # package-level reading #97 shipped while the check was absent): a claim is
            # anchored when the criterion it names is one the narrative's OWN question
            # resolves to — that is the criterion whose evidence came from this
            # student's own work — so an L1 narrative citing another question's criteria
            # counts as HALLUCINATING, and an L1 narrative citing nothing is not
            # citation-valid either (a claim that names no criterion is anchored to
            # nothing). An L2 row is measured at the package level and an EMPTY citation
            # list is valid for it: it composes from syntheses, legitimately carries no
            # criterion citation, and no claim of its own reaches outside the package.
            # The rates stay measured, never gated (§2.3 Q-06).
            valid_narratives = 0
            hallucinated_narratives = 0
            for row in sample_rows:
                try:
                    citations = tuple(json.loads(row["citations"] or "[]"))
                except ValueError:
                    citations = ()
                if row["level"] == LEVEL_L1:
                    anchored_to = criteria_by_question.get(row["question_id"], set())
                else:
                    anchored_to = criterion_ids
                unanchored = [c for c in citations if c not in anchored_to]
                if unanchored:
                    hallucinated_narratives += 1
                elif citations and all(c in anchored_to for c in citations):
                    valid_narratives += 1
                elif row["level"] == LEVEL_L2:
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
            # The score-claim ladder's counters, live now the check is configured:
            # every parsed output the model returned was scanned, and each claim it
            # carried is a rejection the rate reports (`CT-SYNTH-12`).
            rejected_score_claims=self._rejected_score_claims,
            synthesis_failure_rate=failures / total if total else 0.0,
            score_claim_rejection_rate=(
                self._rejected_score_claims / self._parsed_outputs
                if self._parsed_outputs
                else 0.0
            ),
            mean_narrative_length=mean_length,
            sample=sample,
            sample_size=len(sample),
            citation_validity_rate=citation_validity_rate,
            hallucinated_claim_rate=hallucinated_claim_rate,
        )


# --- the headless driver (the first seam) ---------------------------------------------------------


def synthesize(store: Any, provider: Any, model_ref: Any, run_id: str, *,
               submission_id: str) -> SynthesisReport:
    """Run one submission's two-level synthesis from code, with no console (CT-CONSOLE-01). Returns
    the same report as `SynthesisWorker.synthesize_submission`."""
    return SynthesisWorker(store, provider, model_ref).synthesize_submission(
        run_id, submission_id
    )
