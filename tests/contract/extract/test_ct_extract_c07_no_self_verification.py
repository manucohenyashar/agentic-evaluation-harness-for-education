"""`CT-EXTRACT-07` — no work for deterministic criteria, no self-verification
(`TC-EXTRACT-C07`).

Case of test plan §6.11.8; issue #72 (TS-65). Written ahead of #68 (`M-EXTRACT`) and
#73 (`M-INTEG`'s `verify_span`, the rung-3 half); registered in
`WRITTEN_AHEAD_BLOCKERS` under `"#68 extraction contract suite (TS-65)"` (rung-2
tests) and `"#73 extraction contract sweep (TS-65)"` (the rung-3 test, node ID —
the file mixes blockers).

The clause: the module generates no work for a `deterministic` criterion (FR-EXTRACT-06)
and performs no verification of its own output — that is `M-INTEG`, deliberately (R19,
ADR-12). A consumer must not read an extraction result as validated.

Halves:
1. **Exact empty set, rung 2** — a package carrying one deterministic and one judged
   criterion enumerates an extract unit ONLY for the judged one; the deterministic
   criterion's extract-unit set is empty, not a set of skipped units (the shipped
   ledger's status vocabulary has no `skipped` — a skipped unit would have to be a
   real unit, which is the violation).
2. **No verification path, rung 2** — an artifact assertion over the module's own
   source: no name in `aeh.extract` carries the verification vocabulary. Vacuity-guarded
   after the `test_gate_never_scores` pattern (the sweep must be able to fire; a
   control string proves it).
3. **The consumer re-derives, rung 3** — with `M-INTEG` real, `verify_span` re-derives
   verification from the document bytes rather than trusting anything the extraction
   result said: corrupting the document turns verification negative although the
   extraction result is byte-identical. The result carried no validity flag to trust.

Discriminator: an extract unit appearing for a deterministic criterion (however it is
statused) turns half 1 red; an extractor that "helpfully" verifies its own spans (a
`verified` flag on the result, a self-check pass) turns half 2 red; `M-INTEG` trusting
an extraction-side flag turns half 3 red — while every `FR-EXTRACT-*` case, which only
ever runs judged criteria through the happy path, stays green.

**Disclosed stand-ins** (suite register, `_doubles.py`): D1, D3, D6 (`verify_span`
resolved under #73's issue number — the integ vocabulary's own key). **Isolation**:
rung 2 (halves 1-2) / rung 3 (half 3) — real store, real package, real blob directory,
`RecordedFixtureProvider` at the model boundary.
"""

from __future__ import annotations

import inspect
import re

import pytest

from aeh.orch import STAGE_EXTRACT, Orchestrator
from tests.support.conf_builders import edge_panel
from tests.support.impl import INTEG_MODULE, EXTRACT_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID
from tests.contract.extract._doubles import (
    build_markdown,
    extract_once,
    make_world,
    require_extract_surface,
    resolved_config,
)

pytestmark = pytest.mark.contract

_MARKDOWN = build_markdown("The derivation holds for the open criterion.\n")
# The design's "deterministic criterion" is the shipped catalog's `kind: "mcq"` (the
# DDL admits only `open`/`mcq`); the shipped orchestrator enumerates it a
# `deterministic`-stage unit and NO extract unit — exactly the empty set half 1 asserts.
_CRITERIA = [
    {"criterion_id": "C0", "kind": "mcq", "scoring_model": "deterministic"},
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
]
_SPANS = [
    {"start": 41, "end": 84, "text": "The derivation holds for the open criterion.",
     "region_kind": "transcribed_text"},
]

#: The verification vocabulary — what "no verification of its own output" means as a
#: source scan. `verify`/`valid` in an extraction module can only mean self-verification:
#: verification is `M-INTEG`'s, deliberately.
_VERIFICATION_WORD = re.compile(
    r"\bverify|\bvalidated?\b|\bverified\b|is_valid|validity|self_check|selfcheck",
    re.IGNORECASE,
)


def test_tc_extract_c07_no_extract_unit_exists_for_a_deterministic_criterion(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C07` half 1 — the deterministic criterion generates NO extract unit:
    an empty set, not a set of skipped units. The judged criterion DID get one, so the
    empty set is the module's answer for determinism, not an empty module."""
    require(EXTRACT_MODULE, issue="#68")
    require_extract_surface()
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        orchestrator = Orchestrator(world.store)
        run_id = orchestrator.create_run(
            ORCH_COHORT_ID, world.version, resolved_config(edge_panel(1))
        )
        # The shipped ledger enumerates lazily (at `lease`/`resume`); this case reads
        # the enumerated units directly, so it performs the enumeration itself.
        orchestrator.enumerate_units(run_id)
        rows = world.store.cohort(ORCH_COHORT_ID).query(
            "SELECT stage, status, criterion_id FROM work_unit WHERE run_id = :r",
            r=run_id,
        )
        assert rows, "fixture bug: enumeration produced no work units at all"
        deterministic_extract_units = [
            r for r in rows
            if r["stage"] == STAGE_EXTRACT and r["criterion_id"] == "C0"
        ]
        assert deterministic_extract_units == [], (
            f"TC-EXTRACT-C07: the deterministic criterion generated extract units "
            f"{deterministic_extract_units} — the clause promises an empty set, and a "
            f"skipped unit is a real unit, which is the violation"
        )
        assert any(
            r["stage"] == STAGE_EXTRACT and r["criterion_id"] == "C1" for r in rows
        ), (
            "TC-EXTRACT-C07: the judged criterion got no extract unit either — the "
            "empty set is not the module's answer for determinism, the module is "
            "simply not enumerating"
        )
    finally:
        world.close()


def test_tc_extract_c07_no_verification_vocabulary_in_the_modules_source(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C07` half 2 — no name in the extraction module's source carries the
    verification vocabulary, and the sweep is proven able to fire."""
    require(EXTRACT_MODULE, issue="#68")
    extract = require(EXTRACT_MODULE, issue="#68")
    source = inspect.getsource(extract)
    matches = sorted({m.group(0).lower() for m in _VERIFICATION_WORD.finditer(source)})
    assert matches == [], (
        f"TC-EXTRACT-C07: the extraction module carries verification vocabulary "
        f"{matches} — the module verifies its own output, which is M-INTEG's job "
        f"(R19, ADR-12), and a consumer may now read a result as validated"
    )
    # Vacuity guard: the sweep fires on a control string carrying the vocabulary.
    assert [m.group(0) for m in _VERIFICATION_WORD.finditer("verify_span, is_valid")] != [], (
        "TC-EXTRACT-C07: the verification sweep matches nothing — it is vacuous"
    )


@pytest.mark.writtenahead  # rung 3: `verify_span` is M-INTEG's (#73), not yet landed
def test_tc_extract_c07_m_integ_rederives_verification_rather_than_trusting_a_flag(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C07` half 3, rung 3 — verification is re-derived from the document
    bytes: corrupting the document flips `verify_span` negative although the extraction
    result is untouched, proving no extraction-side flag was trusted."""
    VerifySpan = require(INTEG_MODULE, "verify_span", issue="#73")
    require_extract_surface()
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        _request, result, _run_id, _unit = extract_once(
            world, panel=edge_panel(1), spans=_SPANS, build_id="ct-c07-build",
        )
        doc = _MARKDOWN.encode("utf-8")
        (span,) = list(result.spans)
        start = getattr(span, "start", None)
        end = getattr(span, "end", None)
        if start is None and isinstance(span, dict):
            start, end = span["start"], span["end"]
        assert VerifySpan(doc, {"start": start, "end": end,
                                "text": _SPANS[0]["text"]}) is True, (
            "TC-EXTRACT-C07: precondition — the intact span does not verify"
        )
        corrupted = doc[:start] + b"X" * (end - start) + doc[end:]
        assert VerifySpan(corrupted, {"start": start, "end": end,
                                      "text": _SPANS[0]["text"]}) is False, (
            "TC-EXTRACT-C07: verification stayed positive over corrupted bytes — "
            "M-INTEG trusted the extraction result instead of re-deriving"
        )
    finally:
        world.close()
