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


#: The V3 outcomes that hold a paper for identity triage (FR-INGEST-39, CT-INGEST-23, #620).
#: Such a paper gets no scoring work of ANY stage — the deterministic stage's admit-all exception
#: included — because its score would land under no student, or the wrong one. Keyed on the
#: identity column, not on `quarantined`: a paper refused before V3 (unreadable at V0/V1) keeps
#: its deterministic unit (TC-ORCH-25 pins re-ingest adding exactly two units).
IDENTITY_TRIAGE_V3_OUTCOMES: frozenset[str] = frozenset({"ambiguous", "unmatched"})


#: The `provider_config` key under which a run's frozen extractor/synthesizer pins are
#: recorded (`FR-PIPE-19`). The CLI's `--extractor` / `--synthesizer` flags resolve to
#: `ModelRef`s the pipeline threads to `run_to_completion`, and M-ORCH freezes them here
#: beside the other provider identities — absent entirely when no pin was given, so a
#: pre-feature row round-trips byte-identically (`NFR-CONF-04`). The recorded extractor
#: pin feeds `compute_work_id`'s `extractor_version` input (`_unit` reads it from the row,
#: not from the caller, so a resumed run keeps its pin); the recorded synthesizer pin is
#: what a later `aeh recover` validates a fresh flag against. M-PIPE imports this name —
#: the schema is the owner's, never the reader's.
MODEL_PINS_KEY = "model_pins"


#: The two roles a run may pin. A `create_run` caller passing any other role is refused —
#: a pin that names a seat the pipeline does not drive would record an identity nothing
#: honours (`ModelRef`'s role vocabulary is wider than the two CLI flags).
MODEL_PIN_ROLES: tuple[str, ...] = ("extractor", "synthesizer")


#: Where the base enumeration's depths come from (`FR-SETUP-08`): base scoring depth 1
#: for `atomic`/`atomic_with_gate` criteria and 3 for `holistic` ones. Unknown scoring
#: models enumerate at depth 1 — the conservative base — and a package introducing a new
#: model name must extend this map rather than inherit a guess.
SCORING_MODEL_BASE_DEPTH: Mapping[str, int] = MappingProxyType({
    "atomic": 1,
    "atomic_with_gate": 1,
    "holistic": 3,
})
