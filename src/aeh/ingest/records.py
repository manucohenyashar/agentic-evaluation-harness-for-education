"""What ingestion returns: reports, token clusters, page replacements and run aggregates."""

from __future__ import annotations

from dataclasses import dataclass, field

from .settings import DocumentId


class ClusterResolution(tuple):
    """What one cluster resolution touched (`FR-INGEST-36`).

    A tuple of the affected document ids — the shape every caller of `resolve_cluster` has
    always read — carrying the report beside it: `selection_unresolved` lists the region ids
    of selection marks the resolution did NOT match a declared option for. They keep their
    ambiguous state and their NULL selection; the list is how the operator learns the typed
    value was not one of the question's options."""

    def __new__(cls, documents, *, selection_unresolved=()):
        resolution = super().__new__(cls, tuple(documents))
        resolution.selection_unresolved = tuple(selection_unresolved)
        return resolution

    @property
    def documents(self) -> tuple:
        """The affected document ids, under a name that says what they are."""
        return tuple(self)


@dataclass(frozen=True)
class PageReplacement:
    """One replacement page for `revise_document` (`FR-INGEST-05`): the source blob
    holding the rescan, and the 1-based page it replaces."""

    blob_hash: str
    page_no: int


@dataclass
class TokenCluster:
    """One cohort-wide unresolved token (`FR-INGEST-20`): the token, the documents
    whose regions carry it, and — once resolved — the operator's reading. The id is
    derived from the token, so the same token always resolves through the same
    cluster."""

    cluster_id: str
    cohort_id: str
    token: str
    document_ids: list[str]


@dataclass
class IngestReport:
    """What one submission ingestion did (`CLAUDE.md` seam 4). The gate columns are
    per-gate by design (`FR-INGEST-29`, R13) — a bare status on top of five unrecorded
    gates is the silent-failure trap. #36 populates the identity and document fields;
    the V0-V4 gates fill in with #40/#41."""

    submission_id: str
    document_id: DocumentId
    gates: dict[str, str] = field(default_factory=dict)
    ingest_status: str = "ok"
    detail: dict = field(default_factory=dict)
    v4_signals: dict = field(default_factory=dict)


#: The per-gate PASS/FAIL values as the run aggregates count them (#222, the
#: F3/G4 emitter — the single counting path; a consumer that counts differently
#: is a second copy of the counts and is the bug the issue kills). A gate's
#: passing outcome is `pass` — except V4, whose column records `match` and
#: never the literal — and `not_reached`/`not_run` count in neither side: a
#: gate the ladder never reached is neither a pass nor a fail.
GATE_PASS_VALUES: dict[str, tuple[str, ...]] = {
    "v0": ("pass",), "v1": ("pass",), "v2": ("pass",), "v3": ("pass",),
    "v4": ("match",),
}


GATE_FAIL_VALUES: dict[str, tuple[str, ...]] = {
    "v0": ("fail",), "v1": ("fail",), "v2": ("fail",),
    "v3": ("unmatched", "ambiguous"), "v4": ("uncertain", "mismatch"),
}


#: The gate columns, keyed by the gates' report keys (`IngestReport.gates`).
GATE_COLUMNS_BY_GATE: dict[str, str] = {
    "v0": "v0_integrity", "v1": "v1_pages", "v2": "v2_structure",
    "v3": "v3_identity", "v4": "v4_match",
}


@dataclass
class RunAggregates:
    """The run-level signals CT-INGEST-19/OBS-01 name, emitted by the ONE
    emitter (`Ingestor.run_aggregates`, #222's F3/G4 fix) over the cohort's
    stored rows — the counts the report surface names are actually produced.
    A consumer (TS-55/#148) reads these; nothing recomputes them.

    Rates are fractions in [0, 1]; a signal with no denominator (no rows, no
    marks, no measurements, no second pass) is None — the honest absent, never
    a simulated zero — and `basis` records what each signal was computed over,
    because a bare number next to an empty provenance is the silent-failure
    trap the stage-detail seam exists to kill."""

    submissions: int
    ocr_failure_rate: float | None
    unresolved_mark_rate: float | None
    pages_with_text_layer: int
    mean_text_layer_divergence: float | None
    max_text_layer_divergence: float | None
    gate_pass_counts: dict[str, int]
    gate_fail_counts: dict[str, int]
    quarantine_counts_by_gate: dict[str, int]
    second_pass_disagreement_rate: float | None
    basis: dict[str, str] = field(default_factory=dict)
