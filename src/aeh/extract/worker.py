"""`ExtractionWorker`: processes one leased extraction unit and stores its evidence."""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Sequence

from aeh.orch import (
    MAX_ATTEMPTS_ENV,
    ORCH_MAX_ATTEMPTS,
    ORCH_STATEMENTS,
    Orchestrator,
    WorkLedgerError,
    _env_int,
)
from aeh.orch import _cohort_keys_on_filesystem
from aeh.prov import SamplingParams
from aeh.prov import BuildChangedError, ProviderError, ProviderUnavailableError, RateLimitedError
from aeh.store import lease_clock

from .schema import EXTRACT_STATEMENTS
from .settings import _env_bool, SECOND_FAMILY_ENV, _second_family_ref
from .records import ExtractionResult, ExtractionSpan
from .assembly import assemble_request, _current_document, document_bytes
from .prompt import prompt_fields
from .spans import parse_spans


# --- the worker ----------------------------------------------------------------------------------


class ExtractionWorker:
    """Runs extraction for one leased unit: the unit in, the unit marked done and one evidence row
    out.

    `ExtractionWorker(store, provider, model_ref)` — the store the row and the ledger
    transition are written through, the provider boundary (injected; the recorded
    fixture provider stands in for the model), and the extractor's `ModelRef`
    (`role="extractor"`, the one small model of `NFR-EXTRACT-01`).

    The second family (`FR-EXTRACT-07`): a criterion on the injected
    `high_risk_criteria` register extracts a SECOND time on `second_family_model` —
    the deployment's when given, else the env override, else this module's default —
    and both span sets ride the ONE evidence payload, apart, for `M-INTEG` to
    compare. The register's contents are operator policy (`Q-12`) and arrive by
    injection; nothing here hardcodes them.

    At-least-once safe (`CT-ORCH-04`): a unit already `done` re-reads its evidence
    instead of re-calling the provider, and the done-marking inside the write
    transaction is guarded on the leased/pending states, so a double-run cannot
    double-write. A `quarantined` unit refuses processing outright.
    """

    def __init__(
        self,
        store: Any,
        provider: Any,
        model_ref: Any,
        *,
        second_family_model: Any | None = None,
        high_risk_criteria: Sequence[str] = (),
    ) -> None:
        if getattr(model_ref, "role", None) != "extractor":
            raise ValueError(
                f"extraction runs on the extractor model (role='extractor', "
                f"NFR-EXTRACT-01); got role={getattr(model_ref, 'role', None)!r}"
            )
        second_ref = _second_family_ref(second_family_model)
        if getattr(second_ref, "role", None) != "extractor":
            raise ValueError(
                f"the second family runs the extractor role too (NFR-EXTRACT-01: "
                f"one small-model role, no judge in it); got "
                f"role={getattr(second_ref, 'role', None)!r}"
            )
        if (second_ref.provider, second_ref.build_id) == (
            model_ref.provider, model_ref.build_id
        ):
            raise ValueError(
                f"the second-family model must differ from the primary extractor on "
                f"the build/provider pair (FR-EXTRACT-07 asks for a different "
                f"FAMILY, and a second call to the same build is not a second "
                f"opinion); got the same pair "
                f"{model_ref.provider}/{model_ref.build_id}"
            )
        if isinstance(high_risk_criteria, str):
            high_risk_criteria = (high_risk_criteria,)
        self._store = store
        self._provider = provider
        self._model_ref = model_ref
        self._second_family_model = second_ref
        self._high_risk = tuple(high_risk_criteria)
        self._orchestrator = Orchestrator(store)

    def process(self, unit: Any) -> ExtractionResult:
        """Run one extraction pass over `unit`.

        Resolves the submission's current document, assembles, calls the provider
        once per strike, parses, and writes evidence + the done transition in one
        transaction. A criterion on the injected register extracts a SECOND time on
        the different family (`FR-EXTRACT-07`) and both sets ride the one payload,
        apart, for `M-INTEG` to compare. A refusing reply is one strike reported to
        the ledger; the report that reaches the ceiling quarantines the unit and the
        outcome is returned (`status='quarantined'`) rather than raised — the ledger
        is the surface, and a raised exception would crash the lease loop mid-batch.
        """
        cohort, row = self._find_unit(unit)
        if row["status"] == "done":
            return self._result_from_ledger(cohort, unit)
        if row["status"] == "quarantined":
            raise WorkLedgerError(
                f"extraction refused for unit {unit.work_id[:12]}: the unit is "
                f"quarantined — its failure record stands until an operator "
                f"re-queues it."
            )
        head = _current_document(self._store, unit.submission_id)
        md_bytes = document_bytes(self._store, head)
        request = assemble_request(
            dataclasses.replace(unit, submission_text=md_bytes.decode("utf-8")),
            # The store resolves the criterion from the run's pinned package version
            # (#516); the transcript is already resolved above.
            store=self._store,
        )
        payload = prompt_fields(request)
        params = SamplingParams(temperature=0.0)
        budget = _env_int(MAX_ATTEMPTS_ENV, ORCH_MAX_ATTEMPTS)
        completion = None
        # `FR-EXTRACT-13`: the latency persisted is the SUCCESSFUL attempt's, so it is set
        # only once spans parsed — `completion` alone would carry a failed attempt's figure
        # on a path where the transport answered and the reply would not parse.
        success_latency: int | None = None
        spans: tuple[ExtractionSpan, ...] = ()
        error_text: str | None = None
        for attempt in range(1, budget + 1):
            try:
                completion = self._provider.complete(
                    payload, self._model_ref, params
                )
                spans = parse_spans(completion.text, md_bytes)
                success_latency = int(completion.latency_ms)
                break
            except (RateLimitedError, ProviderUnavailableError, BuildChangedError):
                # `FR-EXTRACT-11` / `CT-EXTRACT-16`: the provider taxonomy is not the unit's
                # fault. A rate limit waits, an outage or a build change pauses the run
                # (`FR-PROV-07`, `FR-ORCH-16/17`) — none consumes a strike, none writes
                # evidence, and the caller decides what the error means.
                raise
            except (ProviderError, ValueError) as error:
                error_text = f"extraction attempt {attempt}/{budget}: {error}"
                self._orchestrator.fail(unit.work_id, error_text)
        if completion is None:
            return ExtractionResult(
                work_id=unit.work_id,
                spans=(),
                extractor=None,
                notes=(
                    f"{self._status_after_budget(cohort, unit.work_id)}: "
                    f"{error_text}"
                ),
            )
        # The second family (`FR-EXTRACT-07`): a flagged criterion's SAME prompt runs
        # a second time on the different family, and BOTH sets ride the one payload,
        # apart — the compare is `M-INTEG`'s (`extractor_disagreement`,
        # `FR-INTEG-06`), never this module's act (`CT-EXTRACT-10`). A pass disabled
        # by the knob, or a family that failed after its budget, is said in `notes`
        # and in the family's own record — never silent.
        notes: str | None = None
        second: dict[str, Any] | None = None
        if unit.criterion_id in self._high_risk:
            if _env_bool(SECOND_FAMILY_ENV, True):
                second = self._second_family_pass(payload, params, md_bytes)
                if "error" in second:
                    notes = f"second family: {second['error']}"
            else:
                notes = (
                    f"second family: the pass is disabled by {SECOND_FAMILY_ENV}; "
                    f"the flagged criterion extracted once"
                )
        evidence_record: dict[str, Any] = {
            "spans": [dataclasses.asdict(span) for span in spans],
        }
        if second is not None:
            evidence_record["second_family"] = second
        spans_payload = json.dumps(evidence_record, sort_keys=True).encode("utf-8")
        with cohort.transaction() as tx:
            # #268's ledger records the monotonic completion tick; the accessor is
            # cached per store, so this is the same clock the orchestrator leases with.
            tx.execute(
                ORCH_STATEMENTS["mark_done"],
                work_id=unit.work_id,
                done_ticks=lease_clock(self._store).ticks(),
            )
            won = int(tx.execute(ORCH_STATEMENTS["select_changes"])[0]["n"])
            if won:
                tx.execute(
                    EXTRACT_STATEMENTS["insert_evidence"],
                    evidence_id=unit.work_id,
                    work_id=unit.work_id,
                    document_id=head["document_id"],
                    payload=spans_payload,
                    resolved_build=completion.resolved_build,
                    latency_ms=success_latency,
                )
        if not won:
            # Another worker's completion landed first (at-least-once leasing): its
            # evidence is the answer, and this pass' provider call is discarded.
            return self._result_from_ledger(cohort, unit)
        return ExtractionResult(
            work_id=unit.work_id,
            spans=spans,
            extractor=completion.resolved_build,
            notes=notes,
        )

    def _second_family_pass(
        self, payload: Any, params: Any, md_bytes: bytes
    ) -> dict[str, Any]:
        """Extract a flagged criterion a second time, with a model from a different family.

        The SAME rendered prompt (the second opinion reads the same fenced
        submission, `FR-EXTRACT-10`) and the same strike budget
        (`HARNESS_ORCH_MAX_ATTEMPTS` — one knob, one owner). NO ledger strikes: the
        budget belongs to the unit's primary extraction, and a family that failed
        after the primary answered is an outcome `M-INTEG` must see, not a fault
        that would discard the primary's evidence by quarantining the unit. The
        outcome — the family's spans, or its failure after the budget — is recorded
        as that family's own record in the payload, apart from the primary's.
        """
        budget = _env_int(MAX_ATTEMPTS_ENV, ORCH_MAX_ATTEMPTS)
        last_error: Exception | None = None
        for _attempt in range(1, budget + 1):
            try:
                completion = self._provider.complete(
                    payload, self._second_family_model, params
                )
                spans = parse_spans(completion.text, md_bytes)
                return {
                    "resolved_build": completion.resolved_build,
                    "spans": [dataclasses.asdict(span) for span in spans],
                }
            except (RateLimitedError, ProviderUnavailableError, BuildChangedError):
                # The same taxonomy rule as the primary pass (`FR-EXTRACT-11`): an outage on
                # the second family is the run's condition, not a family that failed — it
                # propagates before the primary's evidence is written.
                raise
            except (ProviderError, ValueError) as error:
                last_error = error
        return {
            "resolved_build": None,
            "spans": [],
            "error": f"no reply after {budget} attempts: {last_error}",
        }

    def _find_unit(self, unit: Any) -> tuple[Any, Any]:
        """The unit's cohort handle and ledger row, found by walking the cohort files the way the
        orchestrator does (FR-ORCH-02)."""
        for key in _cohort_keys_on_filesystem(self._store):
            cohort = self._store.cohort(key)
            rows = cohort.query(
                EXTRACT_STATEMENTS["select_work_unit"], work_id=unit.work_id
            )
            if rows:
                return cohort, rows[0]
        raise WorkLedgerError(
            f"work unit {unit.work_id[:12]} does not exist in any cohort ledger — "
            f"extracting a unit the ledger does not hold would write evidence with "
            f"no work-unit row beneath it."
        )

    def _status_after_budget(self, cohort: Any, work_id: str) -> str:
        """The unit's status after its attempts ran out, as the ledger records it."""
        rows = cohort.query(
            EXTRACT_STATEMENTS["select_work_unit"], work_id=work_id
        )
        status = rows[0]["status"] if rows else "failed"
        return status if status in ("quarantined", "failed") else "failed"

    def _result_from_ledger(self, cohort: Any, unit: Any) -> ExtractionResult:
        """The result stored for a unit that is already done, so a repeat call makes no provider
        call. With no evidence row, the ledger's status decides the result: the row is only missing
        when the unit was quarantined or ran out of attempts, and reporting a clean result would be
        false."""
        rows = cohort.query(EXTRACT_STATEMENTS["select_evidence"], work_id=unit.work_id)
        spans: tuple[ExtractionSpan, ...] = ()
        extractor: str | None = None
        notes: str | None = None
        if rows:
            row = rows[0]
            extractor = row["resolved_build"]
            if row["payload"] is not None:
                payload = json.loads(bytes(row["payload"]).decode("utf-8"))
                spans = tuple(
                    ExtractionSpan(
                        start=span["start"],
                        end=span["end"],
                        text=span["text"],
                        region_kind=span.get(
                            "region_kind", "transcribed_text"
                        ),
                    )
                    for span in payload.get("spans", ())
                )
        else:
            notes = (
                f"{self._status_after_budget(cohort, unit.work_id)}: the ledger "
                f"holds no evidence row for this unit"
            )
        return ExtractionResult(
            work_id=unit.work_id,
            spans=spans,
            extractor=extractor,
            notes=notes,
        )
