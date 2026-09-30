"""What the catalog returns: provenance and export reports, the manifest, `NoValidationData`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


# --- export, import and the provenance gate (FR-PKG-10/-11/-12/-13, NFR-PKG-02/-04) -------------
#
# One self-contained archive: the Tier P database plus every blob its exemplars
# reference (CT-STORE-07). Import is all-or-nothing — every check (format, content
# hash, schema version, signature, collision, integrity) runs against an IN-MEMORY
# copy before a single byte touches the target installation. The provenance gate is
# the data half of FR-CONSOLE-23: export refuses while the derived flag is 1, and
# `export_provenance_report` lists exactly what must be remediated.


@dataclass(frozen=True)
class ProvenanceEntry:
    """One worked example marked `real_verbatim` that is holding the export gate (FR-PKG-11)."""

    exemplar_id: str
    package_version_id: str
    criterion_id: str
    band: str


@dataclass(frozen=True)
class ProvenanceReport:
    """What `export_provenance_report()` returns: the gate's state and every example holding it, so
    the console's approval screen can act on it (FR-PKG-12)."""

    package_id: str
    package_version_id: str
    contains_real_student_text: bool
    real_verbatim: tuple[ProvenanceEntry, ...]


@dataclass(frozen=True)
class ExportReport:
    """What one export did, field by field."""

    package_id: str
    package_version_id: str
    dest: str
    schema_version: int
    content_hash: str
    signed: bool
    blobs_included: tuple[str, ...]
    #: The exemplar provenance ACTUALLY exported (FR-PKG-12): the package validation
    #: record travels with the artifact, so validated-with-real and
    #: exported-with-synthetic are distinguishable on the receiving side.
    exemplar_provenance: tuple[str, ...]
    bytes_written: int


@dataclass(frozen=True)
class ImportReport:
    """What one import did. `package_version_id` is the imported version; `signature_status` says
    whether the signature checked out (NFR-PKG-04). An unsigned or mismatched package is imported
    and reported, never silently accepted or refused.

    `signature_status` ∈ verified | unsigned | mismatched | unverifiable (a signature
    is present but this installation holds no key — distinct from both unsigned and
    mismatched; test plan §2.3 Q-07 leaves the finer grading open)."""

    package_version_id: str
    package_id: str
    schema_version: int
    signature_status: str
    blobs_imported: int
    src: str


# --- validation records, NoValidationData, the manifest (FR-PKG-08/-09/-12/-21) -----------------
#
# The structural rule: a package can never advertise a single "validated" figure. Every
# validation row is keyed by population, backend, panel build and scoring model; the query
# surface returns records per key or an explicit `NoValidationData` — never an aggregate,
# never zero, never a figure from an adjacent key. HLD §2.1's error (a package-level
# headline across populations) is made unrepresentable in the query surface.


#: `NoValidationData.reason`'s declared values (base design §3.16's `Literal`, CT-STATS-03).
#: `None` is the package catalog's own "no row for this key" answer (`FR-PKG-09`).
NO_DATA_REASONS: tuple[str, ...] = (
    "no_blind_labels",
    # FR-STATS-24 (amended) / FR-STATS-28 (#433): labels exist, but fewer than the minimum n.
    "below_min_n",
    "no_data_for_population",
    "no_data_for_backend",
)


class NoValidationData:
    """The absence of validation evidence, as a value. The whole system uses this one type
    (FR-PKG-09, FR-STATS-04, CT-STATS-26).

    Defined here, in the lower module, and re-exported by `aeh.stats`, so
    `aeh.stats.NoValidationData is aeh.pkg.NoValidationData` and one `isinstance` check
    recognises every absence value either module returns (before #512 each module had its
    own class, and a check on one missed the other: TC-REQ-61, TC-REQ-83).

    Not a null, not a zero, not a sentinel float (`CT-STATS-03`): the value is **not
    numerically coercible by any route**. `float()`, arithmetic, threshold comparison,
    percent formatting and multiplication each raise, because the class defines none of the
    dunders those probes reach. A plain object is the whole defence. The console displays it
    as its own thing (`FR-CONSOLE-24`).

    `reason` is one of `NO_DATA_REASONS`, or `None` for the catalog's "no row for this key".
    What *was* measured travels with the absence as context (`n`, `excluded_count`, the
    interval where one applies), so "20 labels excluded, no figure" is reportable rather
    than a bare message (`CT-REVIEW-08` step 4, `TC-STATS-C01`).

    Called with no arguments it returns one shared instance, so `result is
    NoValidationData()` stays a type-level test of the catalog's answer (`FR-PKG-09`)."""

    _instance: "NoValidationData | None" = None

    def __new__(cls, **kwargs: Any) -> "NoValidationData":
        if kwargs:
            return super().__new__(cls)
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        *,
        reason: str | None = None,
        n: int | None = None,
        excluded_count: int | None = None,
        interval_low: float | None = None,
        interval_high: float | None = None,
    ) -> None:
        if reason is not None and reason not in NO_DATA_REASONS:
            raise ValueError(
                f"reason must be one of {NO_DATA_REASONS}, got {reason!r}. "
                "The Literal is part of the type: a reason outside it is not "
                "representable (CT-STATS-03)."
            )
        self.reason = reason
        self.n = n
        self.excluded_count = excluded_count
        self.interval_low = interval_low
        self.interval_high = interval_high

    def _fields(self) -> dict[str, Any]:
        return {name: value for name, value in (
            ("reason", self.reason), ("n", self.n), ("excluded_count", self.excluded_count),
            ("interval_low", self.interval_low), ("interval_high", self.interval_high),
        ) if value is not None}

    # copy, deepcopy and pickle rebuild through the keyword constructor, so a copy of an
    # absence carrying context is its own instance and never lands on (or overwrites) the
    # shared no-argument singleton; a copy of the singleton is the singleton.
    def __reduce__(self) -> tuple[Any, ...]:
        return (_rebuild_no_validation_data, (self._fields(),))

    def __copy__(self) -> "NoValidationData":
        return _rebuild_no_validation_data(self._fields())

    def __deepcopy__(self, memo: dict[int, Any]) -> "NoValidationData":
        return _rebuild_no_validation_data(self._fields())

    def __repr__(self) -> str:
        return "NoValidationData()" if self.reason is None else (
            f"NoValidationData(reason={self.reason!r})")

    def __str__(self) -> str:
        return ("no validation data for this key" if self.reason is None
                else f"no validation data ({self.reason})")


def _rebuild_no_validation_data(fields: dict[str, Any]) -> NoValidationData:
    """Rebuilds a `NoValidationData` for pickle and copy through the normal constructor, so the
    shared no-fields instance is never modified."""
    return NoValidationData(**fields)


@dataclass(frozen=True)
class ManifestEntry:
    """One population's validation entry in the package manifest (FR-PKG-21)."""

    population_scope_id: str
    criterion_id: str
    backend_profile: str
    panel_build_ref: str
    scoring_model: str
    agreement: float
    n: int
    is_weakest: bool


@dataclass(frozen=True)
class Manifest:
    """The package manifest (FR-PKG-21): validation entries per population, the weakest criterion
    per population, worked-example provenance and the schema version. There is deliberately no
    field combining populations: a package that advertises one headline number repeats the error
    described in HLD §2.1."""

    package_version_id: str
    schema_version: int
    entries: tuple[ManifestEntry, ...]
    exemplar_provenance: tuple[str, ...]


def _weakest_entry(entries: list[ManifestEntry]) -> list[ManifestEntry]:
    """Mark the weakest entry in each population: the lowest agreement with n of at least 1
    (FR-STATS-13)."""
    by_population: dict[str, list[ManifestEntry]] = {}
    for entry in entries:
        by_population.setdefault(entry.population_scope_id, []).append(entry)
    flagged: list[ManifestEntry] = []
    for population in sorted(by_population):
        weakest = min(by_population[population], key=lambda e: e.agreement)
        flagged.extend(
            entry if entry is not weakest
            else ManifestEntry(
                population_scope_id=entry.population_scope_id,
                criterion_id=entry.criterion_id,
                backend_profile=entry.backend_profile,
                panel_build_ref=entry.panel_build_ref,
                scoring_model=entry.scoring_model,
                agreement=entry.agreement,
                n=entry.n,
                is_weakest=True,
            )
            for entry in by_population[population]
        )
    return flagged


#: The revision copy order: parents before children, so every copied row's FK is
#: satisfied at insert time. Each key names a statement in `PKG_STATEMENTS`.
_REVISION_COPY_KEYS: tuple[str, ...] = (
    "pkg_revision_copy_criterion",
    "pkg_revision_copy_band",
    "pkg_revision_copy_question",
    "pkg_revision_copy_question_option",
    "pkg_revision_copy_dependency",
    "pkg_revision_copy_exemplar",
    "pkg_revision_copy_mcq_option",
    "pkg_revision_copy_grade_policy",
    "pkg_revision_copy_grade_boundary",
    "pkg_revision_copy_setup_proposal",
    "pkg_revision_copy_setup_readback",
    "pkg_revision_copy_setup_classification",
    "pkg_revision_copy_setup_step_record",
)


# elicitation_history is deliberately NOT a revision copy: it is the append-only
# calibration trail (FR-PKG-20), whose rows reference the version the conversation was
# about — copying them would duplicate history, and no process may rewrite it.
# The question inventory and its proposal ARE copied: a revision of a confirmed version
# is a clarification of the same instrument, so the child is born with the confirmed
# inventory (its gate is already satisfied) and the proposal row as provenance. The
# confirmation lock does not fight the copy — the copy INSERTs into the child (whose
# version is unlocked), and the lock's triggers fire on UPDATE/DELETE of confirmed
# rows, which the copy does not do.


# --- the catalog --------------------------------------------------------------------------------


@dataclass(frozen=True)
class PackageDraft:
    """The content of a new package version, as M-SETUP or M-CALIB hands it over.

    `criteria` names the judged criteria as bare ids (kind `open`, no bands yet) — the
    shape `create_version` writes. Bands, dependencies, options and keys are declared
    afterwards through their own methods, so a draft grows additively."""

    title: str = ""
    criteria: Sequence[str] = ()
