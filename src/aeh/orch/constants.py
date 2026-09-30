"""Stage names and the fixed values the ledger uses."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


#: The canonical JSON separators used for every config string the ledger stores. Chosen
#: once, here, so two code paths cannot serialize the same panel differently and silently
#: fork the work-ID space (`panel_config` is a hash input).
_JSON_SEPARATORS = (",", ":")


#: The extraction build this orchestrator enumerates for (`FR-ORCH-01`'s
#: `extractor_version` input). `M-EXTRACT` does not exist yet (#68) — when it lands it
#: owns this value and its release cadence; until then it is a module constant so the
#: ninth hash input is a real, stable string rather than a placeholder that changes.
EXTRACTOR_VERSION = "extract/1"


#: The work-unit stages (HLD §9.6's `work_unit.stage` comment). `deterministic` carries a
#: null judge: MCQ items are in the ledger so a run stays resumable and idempotent, but no
#: judge runs. `synth_l1`/`synth_l2` units are enumerated by `M-SYNTH` later, not here.
STAGE_EXTRACT = "extract"


STAGE_SCORE = "score"


STAGE_DETERMINISTIC = "deterministic"


#: The complete `ingest_status` admission rule for Sweep 1 (`FR-ORCH-22`, `CT-ORCH-14`):
#: a submission's extraction and scoring work is enumerated only when its status is in
#: this set. `CT-INGEST-11` fixes the set as the complete rule — the orchestrator treats
#: it as the whole of admission, never re-deriving ingest's gates.
#:
#: **Interpretation recorded (#59): a `NULL` `ingest_status` admits.** The column carries
#: no default (the ingest migration adds it bare), so a submission ingest has not yet
#: judged reads NULL — a state the five-value CHECK does not cover and the requirement's
#: three refused values are not. The refused work the requirement names is the work ingest
#: *assigned a refused status*; a row ingest has not judged is not that. The enumeration
#: tests' seeded submissions (which set no status) depend on this reading.
SWEEP1_ADMITTED_INGEST_STATUSES: frozenset[str] = frozenset(
    {"ok", "low_confidence_ocr"}
)


#: Where the base enumeration's depths come from (`FR-SETUP-08`): base scoring depth 1
#: for `atomic`/`atomic_with_gate` criteria and 3 for `holistic` ones. Unknown scoring
#: models enumerate at depth 1 — the conservative base — and a package introducing a new
#: model name must extend this map rather than inherit a guess.
SCORING_MODEL_BASE_DEPTH: Mapping[str, int] = MappingProxyType({
    "atomic": 1,
    "atomic_with_gate": 1,
    "holistic": 3,
})
