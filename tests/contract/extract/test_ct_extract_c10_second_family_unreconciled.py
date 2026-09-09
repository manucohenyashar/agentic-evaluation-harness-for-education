"""`CT-EXTRACT-10` — both second-family span sets are persisted, and this module
never picks a winner (`TC-EXTRACT-C10`).

Case of test plan §6.11.8; issue #72 (TS-65). Written ahead of #68 (`M-EXTRACT`) and
#69 (the Phase-2 second-family mechanism); registered in `WRITTEN_AHEAD_BLOCKERS`
under `"#69 extraction contract second family (TS-65)"` — the suite's full TS-26
conjunction plus `second_family_model` (this file resolves the whole surface through
`require_extract_surface`, unlike the TS-26 integration file's two-name key).

The clause: where a second-family extraction runs (high-risk criteria, Phase 2),
**both** span sets are persisted for comparison rather than reconciled here
(FR-EXTRACT-07). This module never picks a winner — `M-INTEG` owns the compare
(FR-INTEG-06), and a module that quietly reconciled would destroy
`extractor_disagreement` while every functional test passed.

Halves:
1. **Both sets survive, rung 2** — the flagged criterion sees two calls to two
   different model references, and the ONE evidence row (the `CT-EXTRACT-03` keying —
   a row per family would need a new key dimension) carries both span sets: each
   complete, and persisted SEPARATELY — two lists, not one merged list — with no
   reconciliation key anywhere in the payload, at any depth.
2. **No reconciliation path exists, rung 2, artifact** — a source scan over
   `aeh.extract`: no name carries the reconciliation vocabulary. Vacuity-guarded like
   the `TC-EXTRACT-C07` sweep. The scan reads source text, so a docstring that
   mentions reconciliation trips it too — the wording is part of the contract ("this
   module never picks a winner").

Discriminator: a worker that merges the families' span sets into one list, drops one
set, or writes a winner/agreement key turns half 1 red; a `#68` that implements
selection, arbitration or reconciliation under any spelling turns half 2 red — while
every `FR-EXTRACT-*` case, which never runs a flagged criterion against two families,
stays green. (The second-family *mechanism* — when the second extraction happens, the
unflagged differential — is TS-26's `TC-EXTRACT-07`; this case is the persistence
contract on top of it.)

**Disclosed stand-ins** (suite register, `_doubles.py`): D1 (the two replies are
`span_completion`'s stand-in; the second set's distinct spans are the fixture, since a
merge would be invisible if both replies were identical), D3, and the TS-26
second-family file's disclosed instrument (a two-model stub that answers per model
reference — the interesting fact is which model was asked). The one-payload bet —
`evidence` is keyed with no judge or family dimension, so both sets share the row —
is the vocabulary's disclosed row bet. **Isolation: rung 2** — real store, real
ledger, real blob directory; the model boundary the only fake.
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any

import pytest

from aeh.ingest import UNTRUSTED_CLOSE, UNTRUSTED_OPEN
from aeh.orch import STAGE_EXTRACT, Orchestrator
from tests.support.conf_builders import edge_panel
from tests.support.extract_vocabulary import (
    SECOND_FAMILY_MODEL,
    WORKER,
    extractor_ref,
    span_completion,
)
from tests.support.impl import EXTRACT_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID
from tests.contract.extract._doubles import (
    byte_span,
    build_markdown,
    make_world,
    payload_bytes,
    require_extract_surface,
    resolved_config,
)

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

_MARKDOWN = build_markdown("The crate accelerates at 2 m/s^2.\n")
_PRIMARY_TEXT = "The crate accelerates"
_SECOND_TEXT = "at 2 m/s^2."
_CRITERIA = [{"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"}]

#: The reconciliation vocabulary — what "never picks a winner" means as a source
#: scan. Tight by design: SQL's SELECT must not trip it, and a false negative is
#: acceptable where a false positive would need disclosure at landing.
_RECONCILIATION_WORD = re.compile(
    r"reconcil|winner|arbitrat|final_spans|agreement_score|pick_a_winner"
    r"|choose_a_winner",
    re.IGNORECASE,
)


def _primary_span() -> dict[str, Any]:
    return byte_span(_MARKDOWN, _PRIMARY_TEXT, "transcribed_text")


def _second_span() -> dict[str, Any]:
    return byte_span(_MARKDOWN, _SECOND_TEXT, "transcribed_text")


class _TwoModelProvider:
    """One reply per model reference; counts calls and remembers which model each was
    addressed to. The TS-26 second-family file's instrument, reused."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        spans = (
            [_primary_span()] if model_ref.build_id.endswith("primary")
            else [_second_span()]
        )
        self.calls.append((model_ref.build_id, json.dumps({"spans": spans})))
        return span_completion(spans, build_id=model_ref.build_id)


def _span_lists(node: Any, acc: list[Any]) -> list[Any]:
    """Every list of span-shaped dicts in the payload, recursively."""
    if isinstance(node, dict):
        for value in node.values():
            _span_lists(value, acc)
    elif isinstance(node, (list, tuple)):
        if node and all(isinstance(item, dict) and "text" in item for item in node):
            acc.append(node)
        else:
            for item in node:
                _span_lists(item, acc)
    return acc


def _dicts(node: Any, acc: list[Any]) -> list[Any]:
    """Every dict in the payload, recursively — for the banned-key walk."""
    if isinstance(node, dict):
        acc.append(node)
        for value in node.values():
            _dicts(value, acc)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _dicts(item, acc)
    return acc


def test_tc_extract_c10_both_span_sets_persist_separately_and_never_a_winner(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C10` half 1 — the flagged criterion: two calls to two different
    model references, ONE evidence row carrying BOTH span sets separately and
    completely, and no reconciliation key at any depth of the payload."""
    require(EXTRACT_MODULE, issue="#68")
    require_extract_surface()
    second_ref = require(EXTRACT_MODULE, SECOND_FAMILY_MODEL, issue="#69")
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        orchestrator = Orchestrator(world.store)
        run_id = orchestrator.create_run(
            ORCH_COHORT_ID, world.version, resolved_config(edge_panel(1))
        )
        (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)
        Worker = require(EXTRACT_MODULE, WORKER, issue="#68")
        primary_ref = extractor_ref(build_id="/models/qwen3-30b.gguf@primary")
        provider = _TwoModelProvider()
        Worker(
            world.store, provider, primary_ref,
            second_family_model=second_ref,
            high_risk_criteria=("C1",),
        ).process(unit)

        # Precondition: a second-family extraction with a DIFFERENT reference
        # actually happened.
        assert len(provider.calls) == 2, (
            f"TC-EXTRACT-C10: precondition — a flagged criterion must extract twice, "
            f"saw {len(provider.calls)} calls"
        )
        assert provider.calls[0][0] != provider.calls[1][0], (
            f"TC-EXTRACT-C10: precondition — both calls hit the same model "
            f"reference: {[c[0] for c in provider.calls]}"
        )

        # Row-count oracle: exactly ONE row (the CT-EXTRACT-03 keying admits no
        # family dimension either).
        rows = world.store.cohort(ORCH_COHORT_ID).query(
            "SELECT payload FROM evidence WHERE work_id = :w", w=unit.work_id
        )
        assert len(rows) == 1, (
            f"TC-EXTRACT-C10: the flagged criterion wrote {len(rows)} evidence rows "
            f"— both span sets must persist in ONE row (no family key dimension)"
        )
        stored = json.loads(payload_bytes(rows[0]["payload"]).decode("utf-8"))

        # Both sets persisted, each complete.
        lists = _span_lists(stored, [])
        list_texts = [{d.get("text") for d in lst} for lst in lists]
        assert any(_PRIMARY_TEXT in texts for texts in list_texts), (
            "TC-EXTRACT-C10: the primary family's span set did not reach the "
            "persisted payload"
        )
        assert any(_SECOND_TEXT in texts for texts in list_texts), (
            "TC-EXTRACT-C10: the second family's span set did not reach the "
            "persisted payload"
        )
        # ...and SEPARATELY — one merged list is a reconciliation, and leaves
        # M-INTEG nothing to compare.
        merged = [
            texts for texts in list_texts
            if _PRIMARY_TEXT in texts and _SECOND_TEXT in texts
        ]
        assert not merged, (
            "TC-EXTRACT-C10: the two families' span sets were persisted MERGED — "
            "M-INTEG cannot compare what was not kept apart, so a merge is the "
            "reconciliation the clause forbids"
        )

        # Never picks a winner: no reconciliation key anywhere in the payload.
        banned = ("winner", "selected", "chosen", "agreement", "final_spans",
                  "reconcil")
        offenders = sorted({
            key
            for d in _dicts(stored, [])
            for key in d
            if any(b in str(key).lower() for b in banned)
        })
        assert not offenders, (
            f"TC-EXTRACT-C10: the payload carries reconciliation keys {offenders} — "
            f"the extract module picked a winner, and M-INTEG's "
            f"extractor_disagreement signal is destroyed"
        )
    finally:
        world.close()


def test_tc_extract_c10_no_reconciliation_code_path_exists():
    """`TC-EXTRACT-C10` half 2 — the artifact assertion: no name in `aeh.extract`
    carries the reconciliation vocabulary, and the sweep is proven able to fire."""
    module = require(EXTRACT_MODULE, issue="#69")
    require(EXTRACT_MODULE, SECOND_FAMILY_MODEL, issue="#69")
    require_extract_surface()
    source = inspect.getsource(module)
    matches = sorted({m.group(0).lower() for m in _RECONCILIATION_WORD.finditer(source)})
    assert matches == [], (
        f"TC-EXTRACT-C10: the extraction module carries reconciliation vocabulary "
        f"{matches} — a winner-picking code path exists in the module whose clause "
        f"is 'this module never picks a winner' (M-INTEG owns the compare, "
        f"FR-INTEG-06)"
    )
    # Vacuity guard: the sweep fires on a control string carrying the vocabulary.
    assert [
        m.group(0) for m in _RECONCILIATION_WORD.finditer("reconcile_spans, pick_a_winner")
    ] != [], (
        "TC-EXTRACT-C10: the reconciliation sweep matches nothing — it is vacuous"
    )
