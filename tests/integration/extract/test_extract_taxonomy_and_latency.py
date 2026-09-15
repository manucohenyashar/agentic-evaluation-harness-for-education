"""`TS-87` (issue #381) — the extraction worker's half: provider taxonomy errors are not strikes
(`TC-EXTRACT-16`) and the evidence row carries the successful attempt's latency
(`TC-EXTRACT-18`).

Gap-fix test plan §5:

- `TC-EXTRACT-16` (`FR-EXTRACT-11`, P0, rung 2): `ExtractionWorker.process` over one unit, per
  error class from F-TAXONOMY. **Taxonomy three** (`RateLimitedError`, `ProviderUnavailableError`,
  `BuildChangedError`): the error propagates out of `process` as the same class; zero `evidence`
  rows; `attempts` unchanged; no `fail()` call (spy). **Contrasts** (`ProviderError("500")`,
  unparseable JSON): `attempts = 1` after one call, no propagation; after the third, quarantined
  and no evidence row. Oracle: exact state + spy.
- `TC-EXTRACT-18` (`FR-EXTRACT-13`, P2, rung 2): a `FrozenClock` advancing 250 ms during the
  successful call, after a failed attempt that took 900 ms → `evidence.latency_ms = 250`; the
  failed attempt wrote no row. Oracle: exact value.

**Which arms are red.** The contrasts pass today — a generic failure has always been a strike —
and stay green as the arms the plan requires. The taxonomy arms were written ahead of #353, which
makes the three errors propagate, and were unmarked when it landed. `TC-EXTRACT-18` is
`writtenahead` on #361, which adds the `evidence.latency_ms` column.

**Two witnesses for "the wall time of the successful attempt".** The design does not say whether
the worker times the call itself or reads the provider-reported `Completion.latency_ms`. The case
drives both to the same answer: the store's lease clock *is* the `FrozenClock` (injected through
`lease_clock(store, clock)`, the store's one clock seam, before the worker runs), advanced 900 ms
inside the failing call and 250 ms inside the successful one, and the successful `Completion`
reports `latency_ms=250`. An implementation that sums both attempts (1150), times from the first
attempt, or stores the failed attempt reads wrong under either witness. A worker timing with an
uninjected `time.monotonic()` stores about 0 and is also caught — the clock seam is the store's.

**Isolation: rung 2** — real store, ledger and blob directory; the provider boundary is the
F-TAXONOMY stub (`tests/support/taxonomy.py`).
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from aeh.orch import STAGE_EXTRACT, Orchestrator
from aeh.prov import ProviderError
from aeh.store import lease_clock, open_store
from tests.contract.extract._doubles import build_markdown, byte_span, resolved_config
from tests.support.clock import FrozenClock
from tests.support.conf_builders import edge_panel
from tests.support.extract_vocabulary import extractor_ref, span_completion
from tests.support.impl import EXTRACT_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package
from tests.support.taxonomy import (
    TAXONOMY_THREE,
    UNPARSEABLE,
    TaxonomyProvider,
    server_error,
)

pytestmark = pytest.mark.integration

_SENTENCE = "The equilibrium is stable for small perturbations."
_MARKDOWN = build_markdown(_SENTENCE + "\n")
_CRITERIA = ({"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},)


class _World:
    def __init__(self, tmp_data_dir: Any, clock: Any = None) -> None:
        self.store = open_store(tmp_data_dir)
        seed_cohort(self.store, ("SYN-001",))
        version = seed_package(self.store, _CRITERIA)
        content_hash = self.store.blobs().put(_MARKDOWN.encode("utf-8"))
        with self.store.cohort(ORCH_COHORT_ID).transaction() as tx:
            tx.execute(
                "INSERT INTO document (document_id, submission_id, content_hash) "
                "VALUES (:d, :s, :h)",
                d="doc-tax-1", s="SYN-001", h=content_hash,
            )
        if clock is not None:
            lease_clock(self.store, clock)
        self.orchestrator = Orchestrator(self.store, clock=clock) if clock else Orchestrator(
            self.store
        )
        self.run_id = self.orchestrator.create_run(
            ORCH_COHORT_ID, version, resolved_config(edge_panel(1))
        )
        (self.unit,) = self.orchestrator.lease("w-extract-tax", STAGE_EXTRACT, 1)

    def attempts(self) -> int:
        return int(self._row()["attempts"])

    def status(self) -> str:
        return str(self._row()["status"])

    def evidence_rows(self) -> list[Any]:
        return self.store.cohort(ORCH_COHORT_ID).query("SELECT * FROM evidence")

    def success(self, *, latency_ms: int = 0):
        spans = [byte_span(_MARKDOWN, _SENTENCE)]
        reply = span_completion(spans, build_id="extractor-build-tax")
        return dataclasses.replace(reply, latency_ms=latency_ms)

    def _row(self) -> Any:
        rows = self.store.cohort(ORCH_COHORT_ID).query(
            "SELECT attempts, status FROM work_unit WHERE work_id = :w", w=self.unit.work_id
        )
        return rows[0]

    def close(self) -> None:
        self.store.close()


def _spy_fail(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    real = Orchestrator.fail

    def spy(self, work_id, *args, **kwargs):
        calls.append((work_id, str(args[0]) if args else str(kwargs)))
        return real(self, work_id, *args, **kwargs)

    monkeypatch.setattr(Orchestrator, "fail", spy)
    return calls


# --- TC-EXTRACT-16 — the taxonomy three propagate, strike nothing, write nothing ---------------


@pytest.mark.parametrize("error_class", TAXONOMY_THREE, ids=lambda cls: cls.__name__)
def test_tc_extract_16_a_taxonomy_error_propagates_without_a_strike(
    tmp_data_dir, monkeypatch, error_class
):
    """`TC-EXTRACT-16`, taxonomy arm — same class out of `process`, zero evidence, attempts 0,
    no `fail()`."""
    Worker = require(EXTRACT_MODULE, "ExtractionWorker", issue="#353")
    world = _World(tmp_data_dir)
    try:
        fail_calls = _spy_fail(monkeypatch)
        # Three steps, so a worker that (wrongly) retries the error as a strike fails on the
        # assertions below rather than on the stub running out of script.
        provider = TaxonomyProvider([error_class] * 3, attempts_probe=world.attempts)

        with pytest.raises(ProviderError) as raised:
            Worker(world.store, provider, extractor_ref()).process(world.unit)

        assert type(raised.value) is error_class, (
            f"process raised {type(raised.value).__name__}, not the {error_class.__name__} "
            f"the boundary raised — a taxonomy error must propagate as itself (CT-EXTRACT-16)"
        )
        assert len(provider.calls) == 1, (
            f"the worker called the provider {len(provider.calls)} times after a "
            f"{error_class.__name__}; a taxonomy error is not retried as a strike"
        )
        assert fail_calls == [], f"fail() was called for a {error_class.__name__}: {fail_calls}"
        assert world.attempts() == 0, (
            f"a {error_class.__name__} consumed a strike (attempts={world.attempts()}) — a "
            f"provider outage would quarantine every in-flight unit (RISK-44)"
        )
        assert world.evidence_rows() == [], "a taxonomy error wrote an evidence row"
        assert world.status() != "quarantined"
    finally:
        world.close()


@pytest.mark.parametrize(
    "failure",
    [server_error, lambda: UNPARSEABLE],
    ids=["ProviderError-500", "unparseable-json"],
)
def test_tc_extract_16_contrast_a_generic_failure_is_still_a_strike(
    tmp_data_dir, monkeypatch, failure
):
    """`TC-EXTRACT-16`, contrast arm (green today, and must stay green) — attempts 1 after one
    call, no propagation; after the third, quarantined with no evidence row."""
    Worker = require(EXTRACT_MODULE, "ExtractionWorker", issue="#353")
    world = _World(tmp_data_dir)
    try:
        fail_calls = _spy_fail(monkeypatch)
        provider = TaxonomyProvider(
            [failure(), failure(), failure()], attempts_probe=world.attempts
        )

        Worker(world.store, provider, extractor_ref()).process(world.unit)  # does not raise

        assert [call["attempts_before"] for call in provider.calls] == [0, 1, 2], (
            f"the ledger's attempts before each call were "
            f"{[call['attempts_before'] for call in provider.calls]}; one strike per failed call"
        )
        assert len(fail_calls) == 3
        assert world.status() == "quarantined"
        assert world.evidence_rows() == [], "a quarantined unit left an evidence row"
    finally:
        world.close()


# --- TC-EXTRACT-18 — the evidence row carries the successful attempt's latency ------------------


@pytest.mark.writtenahead
def test_tc_extract_18_evidence_latency_is_the_successful_attempts_wall_time(tmp_data_dir):
    """`TC-EXTRACT-18` — 900 ms failed attempt, then a 250 ms success: `latency_ms = 250`, one
    row, and the failed attempt left nothing behind."""
    Worker = require(EXTRACT_MODULE, "ExtractionWorker", issue="#361")
    clock = FrozenClock()
    world = _World(tmp_data_dir, clock=clock)
    try:
        def slow_failure(payload, model_ref, params):
            clock.advance(0.9)
            return server_error()

        def timed_success(payload, model_ref, params):
            clock.advance(0.25)
            return world.success(latency_ms=250)

        provider = TaxonomyProvider([slow_failure, timed_success])
        Worker(world.store, provider, extractor_ref()).process(world.unit)

        rows = world.evidence_rows()
        assert len(rows) == 1, f"expected one evidence row, found {len(rows)}"
        columns = rows[0].keys()
        assert "latency_ms" in columns, (
            "the evidence row has no latency_ms column (FR-EXTRACT-13)"
        )
        # 249 is admitted for one reason only: `(0.9 + 0.25) - 0.9` is 0.2499999… in binary
        # floating point, so a correct worker that times with the injected clock and truncates
        # stores 249. Anything else — 0 (an uninjected real clock), 1150 (both attempts), 900
        # (the failed attempt) — is wrong under either witness.
        assert rows[0]["latency_ms"] in (249, 250), (
            f"evidence.latency_ms = {rows[0]['latency_ms']!r}; the successful attempt took "
            f"250 ms (the failed 900 ms attempt must not be counted)"
        )
    finally:
        world.close()
