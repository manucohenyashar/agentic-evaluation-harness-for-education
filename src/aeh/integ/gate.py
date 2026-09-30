"""`IntegrityGate`: verifies one cell's evidence and routes the cell."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aeh.store import open_store

from .schema import ALERT_SPAN_VERIFICATION_FAILURES, INTEG_RATE_METRICS, INTEG_STATEMENTS
from .settings import (
    _alert_threshold,
    _described_routes_enabled,
    _document_cache_entries,
    _ocr_conf_floor_override,
    _retry_limit,
)
from .verification import _FAULT, _region_items, _span_items, verify_span
from .signals import (
    _computed_insufficient,
    _disagreement_verdict,
    _failure_rate,
    IntegritySignals,
    _region_signals,
    _verification_outcome,
)


class IntegrityGate:
    """The verification-and-routing half of M-INTEG (design §3.9's Protocol).

    `handle` is the cohort handle documents and the work ledger are read
    through; `blobs` the content-addressed store a superseded document and a
    described region's crop resolve through; `extraction_view` the injected
    read model standing in for the extractor and the panel. `ocr_conf_floor`
    overrides the `INTEG_OCR_CONF_FLOOR` configuration; None (the default)
    reads the environment, whose own default is the declared Assumption.
    """

    def __init__(self, handle: Any, blobs: Any, extraction_view: Any,
                 ocr_conf_floor: "float | None" = None) -> None:
        self._handle = handle
        self._blobs = blobs
        self._view = extraction_view
        self._floor_override = ocr_conf_floor
        self._durable_store: Any = None
        self._durable: Any = None
        #: `FR-INTEG-11`: the canonical document bytes, cached per (run, content_hash) for
        #: this gate instance. The gate runs per CELL and a submission has many cells, so the
        #: uncached path re-read and re-hashed the same document once per criterion — the
        #: measurable part of the gate's share of run wall clock (`NFR-INTEG-01`, GAP-24).
        #: The content-hash re-verification runs once per entry, on the way in: a cached entry
        #: is one whose hash has already been checked against its own bytes.
        self._document_cache: "OrderedDict[tuple[str, str], bytes]" = OrderedDict()
        #: The cells this gate instance has already routed, with the panel state it routed on
        #: (`FR-INTEG-10`). Read from `cell_phase` when this instance has not seen the cell.
        self._routed_state: dict[tuple[str, str, str], str] = {}

    # -- reads ---------------------------------------------------------------------------------------

    def _document_bytes(self, submission_id: str, run_id: str = "") -> "bytes | None":
        """The submission's canonical document bytes, or None on any fault.

        The row's Markdown column is the canonical text when it carries one;
        otherwise the content-addressed blob named by `content_hash` is. The
        hash is re-verified against the bytes actually read either way — a
        superseded document is a read fault, never a stale acceptance
        (CT-INGEST-02's immutability, from the consumer's side).

        Cached per `(run, content_hash)` within this gate instance (`FR-INTEG-11`): the
        document row is still read to learn the hash — that read is what notices a superseded
        document — but the BYTES and their verification are paid once. The cache is an LRU
        bounded by `HARNESS_INTEG_DOCUMENT_CACHE_ENTRIES` (default 64), read at call time."""
        try:
            rows = self._handle.query(
                INTEG_STATEMENTS["read_document"], submission_id=submission_id
            )
        except Exception:
            return None
        if not rows:
            return None
        row = rows[0]
        markdown = row["markdown"]
        stored_hash = row["content_hash"]
        if isinstance(stored_hash, str) and stored_hash:
            cached = self._document_cache.get((run_id, stored_hash))
            if cached is not None:
                # Already read, already hash-verified against these very bytes. Re-verifying
                # would re-answer a question whose answer cannot have changed: the hash IS the
                # identity, so a different document is a different key.
                self._document_cache.move_to_end((run_id, stored_hash))
                return cached
        raw: "bytes | None" = None
        if isinstance(markdown, str) and markdown:
            raw = markdown.encode("utf-8")
        elif isinstance(stored_hash, str) and stored_hash:
            try:
                data = self._blobs.get(stored_hash)
            except Exception:
                return None
            if isinstance(data, (bytes, bytearray)):
                raw = bytes(data)
        if not isinstance(raw, bytes):
            return None
        if not isinstance(stored_hash, str) or hashlib.sha256(raw).hexdigest() != stored_hash:
            return None
        self._cache_document(run_id, stored_hash, raw)
        return raw

    def _cache_document(self, run_id: str, content_hash: str, raw: bytes) -> None:
        """Hold one verified document, evicting the least recently used past the bound."""
        limit = _document_cache_entries()
        cache = self._document_cache
        cache[(run_id, content_hash)] = raw
        cache.move_to_end((run_id, content_hash))
        while len(cache) > limit:
            cache.popitem(last=False)

    def _spans(self, submission_id: str, criterion_id: str) -> "list[tuple[int, int, bytes]] | None":
        """The extraction's spans for the cell, or None when the read faults."""
        try:
            return _span_items(self._view.spans(submission_id, criterion_id))
        except Exception:
            return None

    def _regions(self, document_id: str) -> "tuple[tuple[Any, int, int, Any, Any], ...] | None":
        try:
            return _region_items(self._view.regions(document_id))
        except Exception:
            return None

    def _panel_flags(self, submission_id: str, criterion_id: str) -> "tuple[bool, ...] | None":
        """Per-judge sufficiency flags, or None when the read faults or the
        answer is not a sequence of plain booleans."""
        try:
            panel = self._view.panel_sufficiency(submission_id, criterion_id)
            flags = getattr(panel, "evidence_sufficient", None)
            if flags is None and isinstance(panel, (tuple, list)):
                flags = panel
            if isinstance(flags, (tuple, list)) and flags and all(
                isinstance(flag, bool) for flag in flags
            ):
                return tuple(flags)
        except Exception:
            return None
        return None

    def _requires_citation(self, criterion_id: str) -> bool:
        """Whether the criterion's evidence type requires a citation — True on
        any fault, the routing-conservative reading (FR-INTEG-03)."""
        try:
            value = self._view.criterion_requires_citation(criterion_id)
        except Exception:
            return True
        return value if isinstance(value, bool) else True

    def _second_family(self, submission_id: str, criterion_id: str) -> Any:
        try:
            return self._view.second_family_spans(submission_id, criterion_id)
        except Exception:
            return _FAULT

    def _max_pending_attempts(
        self, run_id: str, submission_id: str, criterion_id: str,
    ) -> "int | None":
        """The highest attempt count among the cell's live extract units, read
        BEFORE this verify's bump — the repeat detector behind route 3's
        escalation half. A read fault returns None, which suppresses the
        escalation rather than firing it (the escalation is a widening, not a
        safety action; its trigger must be measured, not assumed)."""
        try:
            rows = self._handle.query(
                INTEG_STATEMENTS["max_retry_attempts"],
                run_id=run_id,
                submission_id=submission_id,
                criterion_id=criterion_id,
            )
        except Exception:
            return None
        if not rows:
            return None
        value = rows[0]["n"]
        return None if value is None else int(value)

    def _sufficiency_flag(
        self,
        run_id: str,
        submission_id: str,
        criterion_id: str,
        panel_flags: "tuple[bool, ...] | None",
    ) -> bool:
        """The REPORTED sufficiency flag: conservative while the cell is
        unjudged, computed once verdicts exist.

        Until the cell carries BOTH work units and verdict rows, a panel read
        cannot be believed either way — the flags describe judges who have not
        answered — so the flag reports True (the adverse value the consumer
        must act on). A faulted panel read is True outright. Once verdicts
        exist, the computed reading — any member reporting the evidence
        insufficient — is the answer (`CT-INTEG-11`)."""
        if panel_flags is None:
            return True
        try:
            unit_rows = self._handle.query(
                INTEG_STATEMENTS["count_units"],
                run_id=run_id,
                submission_id=submission_id,
                criterion_id=criterion_id,
            )
            verdict_rows = self._handle.query(
                INTEG_STATEMENTS["count_verdicts"],
                run_id=run_id,
                submission_id=submission_id,
                criterion_id=criterion_id,
            )
        except Exception:
            return True
        units = int(unit_rows[0]["n"]) if unit_rows else 0
        verdicts = int(verdict_rows[0]["n"]) if verdict_rows else 0
        if units == 0 or verdicts == 0:
            return True
        return any(not flag for flag in panel_flags)

    # -- the durable metrics surface (opened lazily, cached per gate) --------------------------------

    def _metrics_target(self) -> Any:
        """The durable handle the per-cell rates are written through.

        The cohort file lives under the store's `cohorts/` directory, so the
        file this handle's own connection has open names the data directory two
        parents up — the same directory `open_store` was given. Opened on the
        first emission and cached: the metrics path must not cost the timed
        verifier a store open per call (the differential's shared base).

        Deliberate reading, disclosed: a fault on this surface (no main
        database file reachable from the handle, a refused durable open, a
        failing metrics transaction) RAISES out of `verify()` after the
        routing writes have committed — the caller gets an exception, not six
        signals. That is fail-closed by exception rather than by value: nothing
        downstream can read the missing rates as a clean bill of health, and
        the review's alternative — swallowing the fault to return signals —
        would emit nothing while reporting success, the silent-failure shape
        the four seams exist to prevent. TC-INTEG-08's fault model covers the
        six SIGNAL reads; the metrics write surface failing is an environment
        fault the run's error path owns."""
        if self._durable is None:
            rows = self._handle.query(INTEG_STATEMENTS["database_list"])
            main_file = ""
            for row in rows:
                if row["name"] == "main":
                    main_file = row["file"]
                    break
            if not main_file:
                raise RuntimeError(
                    "IntegrityGate could not locate its cohort database file — the durable "
                    "rate surface is unreachable from a handle with no main database file"
                )
            self._durable_store = open_store(Path(main_file).parent.parent)
            self._durable = self._durable_store.durable()
        return self._durable

    def _emit_metrics(
        self,
        run_id: str,
        submission_id: str,
        criterion_id: str,
        *,
        present: bool,
        ocr_risk: bool,
        described: bool,
        sufficiency: bool,
        disagreement: "bool | None",
        failure_value: float,
    ) -> None:
        """Emit all six per-cell rates for this cell — latest value wins.

        The keys below are the SIGNAL names, zipped positionally against
        `INTEG_RATE_METRICS`: declared write set and emission order in one
        literal, so a seventh signal or a reordered tuple fails the write-set
        case rather than sliding past it. Every verify emits all six, whatever
        the routing did (`CT-INTEG-14`'s per-criterion emission). The alert
        rides the same cell only where the failure rate crosses the
        threshold — a fired alert names the cell it accuses."""
        values = {
            "spans_verified": failure_value,
            "evidence_present": 0.0 if present else 1.0,
            "ocr_overlap_risk": 1.0 if ocr_risk else 0.0,
            "described_evidence": 1.0 if described else 0.0,
            "sufficiency_flag": 1.0 if sufficiency else 0.0,
            "extractor_disagreement": 1.0 if disagreement is True else 0.0,
        }
        # `#432`: one execute for the six, not six. The zip is unchanged — the declared
        # write set and the emission order still come from `INTEG_RATE_METRICS` paired
        # positionally with `values` — and the parameters are named `metric_<i>`/`value_<i>`
        # in that same order, so a reordered tuple still moves the rows it always moved.
        parameters: dict[str, Any] = {
            "run_id": run_id,
            "submission_id": submission_id,
            "criterion_id": criterion_id,
        }
        for index, (signal_name, metric_name) in enumerate(
            zip(values, INTEG_RATE_METRICS)
        ):
            parameters[f"metric_{index}"] = metric_name
            parameters[f"value_{index}"] = values[signal_name]

        durable = self._metrics_target()
        with durable.transaction() as tx:
            tx.execute(INTEG_STATEMENTS["upsert_six_metrics"], **parameters)
            if failure_value > _alert_threshold():
                tx.execute(
                    INTEG_STATEMENTS["upsert_alert"],
                    run_id=run_id,
                    metric=ALERT_SPAN_VERIFICATION_FAILURES,
                    value=failure_value,
                    submission_id=submission_id,
                    criterion_id=criterion_id,
                )

    # -- routing writes ------------------------------------------------------------------------------

    def _own_unit_id(self, run_id: str, submission_id: str, criterion_id: str) -> str:
        return f"integ-unit-{run_id}-{submission_id}-{criterion_id}"

    # `#432`: `_bump_retries` and `_enqueue_review` are gone. Each opened a transaction of
    # its own for a single statement, and both are now `_bump()`/`_review()` inside
    # `verify` — parameter builders that append to the cell's batch rather than writers.
    # The statements (`bump_retries`, `enqueue_review`) are unchanged and still the only
    # ones that touch those rows; what moved is the transaction boundary.
    #
    # `enqueue_review`'s `run_id` is still `FR-REVIEW-20`'s column and still carried: a
    # queue row that named no run made two runs over one cohort share a queue, so a
    # re-run's flags and the previous run's were the same list to every reader.

    # -- the verify ----------------------------------------------------------------------------------

    def _panel_state(
        self, run_id: str, submission_id: str, criterion_id: str
    ) -> str | None:
        """The cell's panel state (`FR-INTEG-10`): its terminal extract and score `work_id`s.

        A string rather than a count, because the question is "has the evidence MOVED", and
        two units finishing while two others were requeued is not the same panel. A faulted
        read returns `None` — a sentinel, not a reserved string, because any string is a
        panel state some cell's `work_id`s could join to — so a gate that cannot see the
        ledger burns its retry rather than silently deciding it already had."""
        try:
            rows = self._handle.query(
                INTEG_STATEMENTS["read_cell_panel_state"],
                run_id=run_id, submission_id=submission_id, criterion_id=criterion_id,
            )
        except Exception:
            return None
        return ",".join(str(row["work_id"]) for row in rows)

    def _already_routed(
        self, run_id: str, submission_id: str, criterion_id: str, panel_state: str | None
    ) -> bool:
        """Whether this cell was already routed on exactly this panel state."""
        if panel_state is None:
            return False
        key = (run_id, submission_id, criterion_id)
        seen = self._routed_state.get(key)
        if seen is None:
            try:
                rows = self._handle.query(
                    INTEG_STATEMENTS["read_integrity_post"],
                    run_id=run_id, submission_id=submission_id, criterion_id=criterion_id,
                )
            except Exception:
                return False
            if not rows:
                return False
            seen = "" if rows[0]["panel_state"] is None else str(rows[0]["panel_state"])
            self._routed_state[key] = seen
        # A cell with no terminal units yet has the EMPTY panel state, and two calls over that
        # same emptiness are still the same call: comparing truthiness rather than equality
        # would make the commonest case — a cell routed before any unit finished — dedupe
        # never, which is exactly the retry-burning FR-INTEG-10 is about.
        return seen == panel_state

    def _record_routed(
        self, run_id: str, submission_id: str, criterion_id: str, panel_state: str | None
    ) -> None:
        """Record the panel state this cell was routed on, in `cell_phase`.

        Best-effort, deliberately: a gate that cannot write the phase keeps the record in
        memory for this instance and re-routes after a restart. Re-routing costs a retry;
        refusing to have routed would lose the route itself."""
        if panel_state is None:
            return
        self._routed_state[(run_id, submission_id, criterion_id)] = panel_state
        try:
            with self._handle.transaction() as tx:
                tx.execute(
                    INTEG_STATEMENTS["write_integrity_post"],
                    run_id=run_id, submission_id=submission_id, criterion_id=criterion_id,
                    # The count is what `FR-ORCH-28` declares the column to mean, and what
                    # `ready_cells` parses; the identity rides its own TEXT column.
                    units_consumed=len([w for w in panel_state.split(",") if w]),
                    panel_state=panel_state,
                    recorded_at=datetime.now(timezone.utc).isoformat(),
                )
        except Exception:
            # The in-memory record still stands for this instance; a gate that could not
            # write the phase is not a gate that should refuse to have routed.
            return

    def verify(self, run_id: str, submission_id: str, criterion_id: str) -> IntegritySignals:
        """Re-derive the six signals for one cell, route on them, emit the rates.

        Every read is fault-injected (a raising view method, a malformed
        payload, a missing document) and every fault lands on the adverse
        value; routing is exactly one route per call; the metrics surface
        always emits. Returns the six fields and nothing else."""
        raw = self._document_bytes(submission_id, run_id)
        span_items = self._spans(submission_id, criterion_id)
        citation = self._requires_citation(criterion_id)

        verified, present = _verification_outcome(
            raw, span_items, citation,
        )

        region_items = self._regions(f"doc-{submission_id}")
        floor = (
            float(self._floor_override)
            if self._floor_override is not None
            else _ocr_conf_floor_override()
        )
        ocr_risk, described, crop_ref = _region_signals(
            region_items, span_items, floor,
        )

        panel_flags = self._panel_flags(submission_id, criterion_id)
        sufficiency = self._sufficiency_flag(
            run_id, submission_id, criterion_id, panel_flags,
        )
        disagreement = _disagreement_verdict(
            self._second_family(submission_id, criterion_id), span_items,
        )

        # -- idempotence (`FR-INTEG-10`) ------------------------------------------------------
        # A repeat call on an UNCHANGED panel state routes nothing: no unit, no queue row, no
        # metric, and — the case that bit — no `bump_retries`, which increments on every call
        # and would otherwise burn a retry the cell never used. The key is the cell's terminal
        # extract and score `work_id`s, recorded in `cell_phase`'s `integrity_post` row
        # (`FR-ORCH-28`), so the answer survives the process that computed it: a composition
        # layer that verifies, restarts, and verifies again must not re-route either.
        #
        # A CHANGED panel state may route again, which is the point of keying on state rather
        # than on a boolean: an escalation's verdicts landing is exactly the new evidence the
        # gate should look at.
        #
        # The check is asked HERE, at the first write, rather than at the top of `verify`: a
        # call that routes nothing must not pay for two reads it has no use for
        # (`NFR-INTEG-01`'s 1% budget is measured over exactly those calls).
        panel_state = self._panel_state(run_id, submission_id, criterion_id)
        repeat = self._already_routed(run_id, submission_id, criterion_id, panel_state)

        # -- routing: exactly one route per call, in the declared order ------------------------------
        # The repeat is the FIRST arm, and the one that routes nothing: suppressing the whole
        # chain rather than only the bump is what the clause asks for. Suppressing only the
        # bump was tried and measured — the sufficiency arm's repeat half reads the bumped
        # `attempts` back and inserts two escalation units, so a bare repeat still wrote two
        # `work_unit` rows against a clause whose words are "writes no additional `work_unit`,
        # `review_queue` or `run_metrics` row".
        # `#432`: every cohort-tier write this routing decision makes is COLLECTED here and
        # issued in ONE transaction below. Eight transactions per verify became three (this
        # one, the durable metrics flush, and `_record_routed`'s), and the routing's writes
        # are now atomic with each other — a crash mid-route previously left the gate's own
        # pending unit without the retry bump that belongs with it.
        #
        # The write SET is unchanged (`CT-INTEG-04`): same statements, same parameters, same
        # order within the route. Only the transaction boundary moved.
        writes: list[tuple[str, dict[str, Any]]] = []

        def _own_unit(status: str) -> tuple[str, dict[str, Any]]:
            return "insert_unit", {
                "work_id": self._own_unit_id(run_id, submission_id, criterion_id),
                "run_id": run_id,
                "submission_id": submission_id,
                "criterion_id": criterion_id,
                "stage": "extract",
                "status": status,
                "attempts": 0,
            }

        def _bump() -> tuple[str, dict[str, Any]]:
            return "bump_retries", {
                "run_id": run_id,
                "submission_id": submission_id,
                "criterion_id": criterion_id,
                "max_attempts": _retry_limit(),
            }

        def _review(reason: str) -> tuple[str, dict[str, Any]]:
            return "enqueue_review", {
                "queue_id": f"integ-{reason}-{submission_id}-{criterion_id}",
                "run_id": run_id,
                "submission_id": submission_id,
                "criterion_id": criterion_id,
                "reason": reason,
            }

        if repeat:
            pass
        elif verified is False:
            writes.append(_own_unit("pending"))
            writes.append(_bump())
            if present is False and citation:
                writes.append(_review("empty-evidence"))
        elif present is False and citation:
            # Shadowed under the locked signal semantics (an empty or faulted
            # span read already verified False); kept so the fail-closed route
            # survives any future relaxation of the verification signal.
            writes.append(_own_unit("pending"))
            writes.append(_bump())
            writes.append(_review("empty-evidence"))
        elif sufficiency_input := _computed_insufficient(panel_flags):
            # Read BEFORE the insert, where it used to be read after it. The two agree:
            # the insert adds this gate's own unit at `attempts = 0`, a MAX cannot be
            # lowered by a 0, and the predicate below is `>= 1` — so the only case that
            # differs is "no pending unit at all", which reads `None` before and `0` after
            # and is False either way. Reading first is what lets the insert join the batch.
            pre_attempts = self._max_pending_attempts(run_id, submission_id, criterion_id)
            writes.append(_own_unit("pending"))
            writes.append(_bump())
            if pre_attempts is not None and pre_attempts >= 1:
                # The repeat half: widen the criterion's score units — the
                # escalation shape the ledger already knows how to express.
                for ordinal in ("a", "b"):
                    writes.append(("insert_escalation_unit", {
                        "work_id": (
                            f"integ-escalate-{run_id}-{submission_id}-"
                            f"{criterion_id}-{ordinal}"
                        ),
                        "run_id": run_id,
                        "submission_id": submission_id,
                        "criterion_id": criterion_id,
                    }))
        elif ocr_risk:
            writes.append(_review("ocr-overlap-risk"))
        elif described and _described_routes_enabled():
            review_id = f"integ-review-{run_id}-{submission_id}-{criterion_id}"
            if crop_ref:
                review_id = f"{review_id}-{crop_ref}"
            writes.append(("insert_review_unit", {
                "work_id": review_id,
                "run_id": run_id,
                "submission_id": submission_id,
                "criterion_id": criterion_id,
            }))
            writes.append(_review("described-evidence"))
        else:
            writes.append(_own_unit("done"))
            writes.append(("mark_extract_done", {
                "run_id": run_id,
                "submission_id": submission_id,
                "criterion_id": criterion_id,
            }))

        if writes:
            with self._handle.transaction() as tx:
                for statement_key, parameters in writes:
                    tx.execute(INTEG_STATEMENTS[statement_key], **parameters)
        # -- observability: the six per-cell rates, latest value wins --------------------------------
        failure_value = _failure_rate(raw, span_items, verified)
        self._emit_metrics(
            run_id, submission_id, criterion_id,
            present=present, ocr_risk=ocr_risk, described=described,
            sufficiency=sufficiency, disagreement=disagreement,
            failure_value=failure_value,
        )
        # The cell routed on this panel state; a repeat call with the same state will not
        # (`FR-INTEG-10`). Recorded AFTER the routing, so a route that raised is not recorded
        # as having happened, and only when this call was the one that routed.
        if not repeat:
            self._record_routed(run_id, submission_id, criterion_id, panel_state)
        return IntegritySignals(
            spans_verified=verified,
            evidence_present=present,
            sufficiency_flag=sufficiency,
            ocr_overlap_risk=ocr_risk,
            described_evidence=described,
            extractor_disagreement=disagreement,
        )

    def verify_span(self, doc: Any, span: Any) -> bool:
        """The Protocol's second member (design §3.9's `IntegrityGate`), the
        pure verifier as a method of the gate that holds the store seams.

        A pure delegation to the module-level `verify_span`: the rung-0 cases
        (TC-INTEG-01/09, FUZZ-03) call the function because they have no gate to
        construct, and a consumer holding the Protocol calls the method — one
        computation, two spellings, neither carrying state the other lacks. The
        method adds nothing around the call (no floor, no view, no ledger): a
        span verdict is a function of the bytes and the span alone, and a gate
        that enriched it would be a second verifier."""
        return verify_span(doc, span)
