"""Shared instruments for the `M-SYNTH` contract suite (issue #100, TS-70).

The suite behind `TC-SYNTH-C01..C14` (test plan §6.11.13). The synth-shaped world —
real store, real cohort ledger, the scored-submission fixture, the capture provider
— is `tests/support/synth_vocabulary.py`'s (built by #98's suite); this file adds
nothing new: the write audit `TC-SYNTH-C07` needs is
`tests/contract/orch/_doubles.py`'s `LedgerAuditHandle`/`install_audit` **verbatim,
re-exported** rather than re-spelled — the same pass-through `TierHandle` wrapper
that records every statement with the module that issued it (the frame walk skipping
`aeh.store` and this file), because the writership clause reads the same log shape
the run-ledger clause does and a second spelling would drift from the first.

The install mechanics are disclosed there once and apply here unchanged: the store
caches one handle per `(tier, key)` in `SqliteStore._handles`, the wrapper takes the
cached entry's place, and every `store.cohort(...)` the worker resolves hands back
the wrapper. Touching the store's private cache is test scaffolding, disclosed in
the orch module's docstring; no production module may do this. Nothing here stands
in for the store (§4.2) — the writes land, the queries answer, and only the
observation is injected.
"""

from __future__ import annotations

from tests.contract.orch._doubles import (
    LedgerAuditHandle,
    WriteRecord,
    install_audit,
)

__all__ = [
    "LedgerAuditHandle",
    "WriteRecord",
    "install_audit",
]
