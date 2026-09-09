"""`M-PKG` — Assessment Package Catalog (design §3.4).

Owns Tier P: package identity and version lineage, the §6.2 schema lock, criteria and
bands, the dependency graph, exemplars, the grade policy, and validation records. This
file landed **#26** — version lineage and published-version immutability
(`FR-PKG-01`, `-02`, `-04`, `NFR-PKG-01`); #27-#31 have since added the schema lock's
enumerable list, bands and the dependency graph, validation records, the grade policy,
boundaries, answer keys and elicitation history, and single-file export/import with the
provenance gate (`FR-PKG-10..13`).

It owns **no student text**: Tier P never contains student work (design §3.3's tier
table), and nothing here reads or writes any other tier.

Immutability is enforced twice (`NFR-PKG-01`: "a database constraint or a data-layer
guard"):

1. **Data-layer guard** — every mutating `PackageCatalog` method calls `_refuse_mutation`,
   which raises `PublishedVersionImmutableError` before a statement is attempted.
2. **Database triggers** — migration `pkg_version_lineage` installs `BEFORE UPDATE`
   triggers on `package_version` and every table referencing it, so a write that routes
   around the catalog (a raw handle, another process) fails at the database. The trigger
   is the backstop that makes "no caller, including `M-CALIB`, can route around it" a
   property of the *data*, not of who remembers to call the guard.
"""

from __future__ import annotations

import atexit
import hashlib
import hmac
import json
import logging
import math
import os
import sqlite3
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeh.store import (
    Migration,
    STATEMENTS,
    Statement,
    Tier,
    TIER_MIGRATIONS,
    current_schema_version,
    open_store,
)

__all__ = [
    "BandSetError",
    "CyclicDependencyError",
    "ExportBlockedError",
    "ExportReport",
    "ExportSummary",
    "GateRule",
    "GradePolicy",
    "GradePolicyError",
    "ImportReport",
    "InventoryError",
    "QUESTION_TYPES",
    "InMemoryCatalog",
    "Manifest",
    "NoValidationData",
    "PROVENANCE_VOCABULARY",
    "PackageCatalog",
    "PackageDraft",
    "PackageError",
    "PackageVersionId",
    "ProvenanceEntry",
    "ProvenanceReport",
    "PublishedVersionImmutableError",
    "SCHEMA_LOCK_FIELDS",
    "ScaleRule",
    "SCHEMA_LOCK_VIOLATIONS",
    "SchemaLockViolation",
    "SchemaTooNewError",
    "schema_lock_violation_count",
    "default_grade_policy",
    "export_package",
    "in_memory_catalog",
    "points_for_band",
    "record_validation",
]

#: A package version's id: an opaque string the catalog mints.
PackageVersionId = str

#: Module observability (`CT-PKG-16`): every export/import logged with version,
#: provenance and destination; every `SchemaLockViolation` at WARN.
LOGGER = logging.getLogger("aeh.pkg")


class _ViolationCounter:
    """The monotone count of refused §6.2-locked edits (`CT-PKG-16`'s alert signal).

    The NAME is contract (`RISK-35`): a rising `schema_lock_violation_count` means a
    caller is attempting something the design forbids, and an alert on a renamed signal
    is an alert that silently watches nothing. Exposed through
    `schema_lock_violation_count()`; the rate ops alerts on is this counter's
    derivative, which a monitor computes — the module owns the count, not the clock."""

    def __init__(self) -> None:
        self._value = 0

    def increment(self) -> None:
        self._value += 1

    @property
    def value(self) -> int:
        return self._value


#: The stable-name signal itself. Module-level, so every catalog instance's refusals
#: contribute to the one number ops watches.
SCHEMA_LOCK_VIOLATIONS = _ViolationCounter()


def schema_lock_violation_count() -> int:
    """`CT-PKG-16`'s stable-name accessor: §6.2-locked edits refused, monotone over the
    process lifetime. A rising rate is an alert signal meaning a caller is attempting
    something the design forbids."""
    return SCHEMA_LOCK_VIOLATIONS.value

#: The export archive format tag and version. Import refuses an unknown NEWER format
#: (the same forward-only rule the schema itself follows) and accepts older ones.
EXPORT_FORMAT_VERSION = 1
EXPORT_FORMAT_TAG = "aeh-package-export"

#: The signing key's environment knob (design §3.4's Configuration). Read at CALL time,
#: never at import — a test or a deployment sets it per operation, not per process
#: load. Optional by design (NFR-PKG-04): a school with no PKI still exports.
SIGNING_KEY_ENV = "HARNESS_PACKAGE_SIGNING_KEY"

#: A safe package id for import: the manifest's package_id becomes a FILENAME in the
#: receiving installation's packages directory, so an attacker-controlled archive must
#: not carry `..`, separators, or anything else that escapes it.
_SAFE_PACKAGE_ID = __import__("re").compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")

#: The manifest/peek SQL the import runs against a RAW sqlite3 connection (an in-memory
#: copy of the archived database, before a single byte touches the target filesystem).
#: These never touch the store's handles, so they live outside PKG_STATEMENTS.
_PEEK_TABLES = "SELECT name FROM sqlite_master WHERE type = 'table'"
_PEEK_VERSIONS = "SELECT package_version_id FROM package_version"
_PEEK_SCHEMA_VERSION = "SELECT MAX(version) AS v FROM schema_version"
_PEEK_PACKAGES = "SELECT package_id FROM package"
#: The exported database travels in DELETE journal mode: a single-file artifact with no
#: -wal/-shm sidecars (they do not travel in the archive, and a WAL header cannot even be
#: inspected through an in-memory copy). The pragma checkpoints and rewrites the header.
_SNAPSHOT_JOURNAL_MODE = "PRAGMA journal_mode=DELETE"


def _zip_entry(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    """Write one archive entry with a fixed timestamp and owner-only permissions, so the
    member LISTING (names and digests, TC-REG-02's baseline) is stable for identical
    content and the artifact is not world-readable where the filesystem honours it. The
    manifest carries no timestamp for the same reason: every field in it is derived from
    the content or the declared vocabulary."""
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, data)


def _signature_of(content_hash: str, key: str) -> str:
    """HMAC-SHA256 over the content hash (NFR-PKG-04). The hash pins the database
    bytes; the key pins who produced it."""
    return hmac.new(key.encode("utf-8"), content_hash.encode("ascii"),
                    hashlib.sha256).hexdigest()


class PackageError(Exception):
    """Base for every `M-PKG` failure. Siblings, never a chain — the exact-type oracle
    convention every module's error taxonomy follows."""


class BandSetError(PackageError):
    """A band set violates the structural rules the scoring pipeline assumes
    (`FR-PKG-06`): a `band_count` that is odd or outside 2..6, ordinals that are not
    contiguous from 0, or `points` that are not non-decreasing in ordinal.

    The monotone mapping is what `M-AGG` and `M-GRADE` assume; the even count is the
    design rule that removes the safe middle band a hesitant judge retreats to
    (design §5.10, R40). Not retryable by mutation — the band set is rewritten as a
    whole."""

    retryable = False


class CyclicDependencyError(PackageError):
    """A `criterion_dependency` write would make the dependency graph cyclic
    (`FR-PKG-05`).

    The extraction sweep's two-pass order rests on the graph being a DAG; a cycle would
    strand the cycle's criteria in the second pass forever. Not retryable — the edge is
    the mistake."""

    retryable = False


class SchemaLockViolation(PackageError):
    """An edit the HLD §6.2 lock forbids was attempted (`FR-PKG-03`).

    The message names the offending field, because `M-CALIB` routes every rubric edit
    through this module (`FR-CALIB-07`) and an operator fixing a refused edit needs the
    field, not a generic refusal. The forbidden-field list is `SCHEMA_LOCK_FIELDS` — one
    place in the source, enumerable at runtime (`NFR-PKG-03`); a second copy of the list
    is how a locked field quietly becomes editable.

    Not retryable by mutation: the sanctioned vehicle for every clarification is a new
    version (`FR-PKG-04`).
    """

    retryable = False


class PublishedVersionImmutableError(PackageError):
    """An update was attempted on a published (`locked = 1`) `package_version`, or on any
    row referencing one (`FR-PKG-01`).

    A published version is the anchor a grade issued years ago resolves to; mutating it —
    or any criterion, band or exemplar beneath it — silently rewrites history. Not
    retryable: the fix is a **revision** (`create_version` with the published version as
    parent), never a mutation."""

    retryable = False


class GradePolicyError(PackageError):
    """A grade policy outside the closed rule vocabulary, or a malformed boundary
    table (`FR-PKG-14`). Answer-key refusals raise the module base `PackageError` —
    the key is FR-PKG-17's surface, not the policy vocabulary's.

    The vocabulary — weighted sum, gate, best-k-of-n, drop-lowest-n, scale, rounding,
    boundary table — is closed on purpose (the ADR): an executable formula in a package
    is an arbitrary-code surface and an un-auditable grade, so a policy that is not a
    structured object is refused at construction, at write and at read. Not retryable —
    the policy is the mistake, and rewriting it is a draft edit."""


class ExportBlockedError(PackageError):
    """Export was attempted while `package.contains_real_student_text = 1`
    (`FR-PKG-11`).

    The exported artifact must be free of verbatim student text (`CT-PKG-13`): a caller
    may treat it as such, so the gate cannot pass while any `real_verbatim` exemplar
    row exists. `export_provenance_report()` lists exactly what must be
    paraphrased-and-approved or dropped — the gate is actionable, not a dead end. Not
    retryable until the rows are remediated."""

    retryable = False

    def __init__(self, message: str, report: "ProvenanceReport | None" = None) -> None:
        super().__init__(message)
        #: The provenance report taken at refusal time, so the caller does not need a
        #: second call to act on the refusal.
        self.report = report


class SchemaTooNewError(PackageError):
    """An import whose schema version exceeds this binary's (`FR-PKG-13`).

    The message names the required upgrade, and nothing is partially imported — a
    partial import of a newer package is worse than a refused one. Mirrors
    `M-STORE`'s refusal of a too-new tier file; this is the package-archive half."""

    retryable = False


class InventoryError(PackageError):
    """A confirmed question-inventory write is structurally invalid (`FR-SETUP-01`).

    The question vocabulary, the option-set/type pairing, unique ids and ordinals —
    these are the structural constraints `M-PKG` owns (`CT-PKG-12`: every Tier P write
    is validated here, whatever the caller already checked). Retryable by fixing the
    records, not by re-sending them unchanged."""

    retryable = False


#: The question-type vocabulary the `question` table's CHECK enforces (`FR-SETUP-01`,
#: HLD §9.5). `open` — a ruled response area with nothing to circle; `mcq` — an
#: enumerated option set; `mixed` — both parts on one question. The list lives here, at
#: the data layer whose CHECK enforces it; `M-SETUP` reads it from this module rather
#: than carrying a second copy that could drift from the schema.
QUESTION_TYPES: tuple[str, ...] = ("open", "mcq", "mixed")


#: The §6.2 schema lock, in exactly one place (`NFR-PKG-03`): every `(table, field)` edit
#: a published version refuses, enumerable at runtime so a test can assert the list
#: matches HLD §6.2 field for field. `question_type` is the HLD's name for the physical
#: `kind` column — the HLD name is what the list carries, because the enumeration test
#: reads it against the HLD text.
SCHEMA_LOCK_FIELDS: tuple[tuple[str, str], ...] = (
    ("criterion", "max_points"),
    ("criterion", "add"),
    ("criterion", "remove"),
    ("criterion", "question_type"),
    ("criterion", "scoring_model"),
    ("criterion", "construct_tag"),
    ("band", "label"),
    ("band", "ordinal"),
    ("band", "descriptor"),
    ("band", "points"),
    ("criterion_dependency", "add"),
    ("criterion_dependency", "remove"),
    ("criterion_dependency", "alter"),
)


# --- the grade policy: a structured object from a closed vocabulary (FR-PKG-14/-15/-19) ---------
#
# The vocabulary is CLOSED by an explicit ADR: weighted sum, gate, best-k-of-n,
# drop-lowest-n, scale, rounding, boundary table. A free-text formula or an executable
# expression in a package is an arbitrary-code surface and an un-auditable grade, so the
# policy exists only as this structured object — validated at construction, at write and
# at read — and its `plain_language` wording is GENERATED from the object (`FR-PKG-15`),
# never accepted as input, so the approved wording and the executed policy cannot diverge.

#: The combination rules: how criterion scores become one total. Exactly one is in force.
COMBINATION_RULES: tuple[str, ...] = ("weighted_sum", "best_k_of_n", "drop_lowest_n")

#: The rounding modes. Rounding is declarative — `M-GRADE` executes it (FR-GRADE-02).
ROUNDING_MODES: tuple[str, ...] = ("nearest", "up", "down")


@dataclass(frozen=True)
class GateRule:
    """A gate: the named criterion must reach `minimum` for the computed grade to stand
    (FR-GRADE-02's "optional gate"). The policy records the rule; the consequence is
    M-GRADE's declared behaviour — the policy never encodes it a second way."""

    criterion_id: str
    minimum: float


@dataclass(frozen=True)
class ScaleRule:
    """A scale: the raw total is multiplied by `factor` (e.g. target-max / raw-max)."""

    factor: float


@dataclass(frozen=True)
class GradePolicy:
    """The grade policy as a structured object (`FR-PKG-14`).

    Fields are the closed vocabulary; everything not selected must be absent, so the
    object never carries a parameter no rule executes (a free parameter is how a formula
    re-enters through the back door). Validation runs in `__post_init__`: an
    out-of-vocabulary rule — including a formula string, an executable expression, or a
    lambda-shaped string — cannot become an object at all.

    The boundary-table vocabulary member has NO field here by design: `grade_boundary`
    rows are the single canonical representation of the grade resolution rule
    (`FR-PKG-16`), and a flag on the policy would be a second copy that can disagree
    with the table — the same ADR-1 reasoning as the answer key.

    `review_window_hours` is ADR-3's column: nullable, and null means finalize on run
    completion (`FR-PKG-19`) rather than wait indefinitely.
    """

    combination: str = "weighted_sum"
    weights: tuple[tuple[str, float], ...] = ()
    k: int | None = None
    drop: int | None = None
    gate: GateRule | None = None
    scale: ScaleRule | None = None
    rounding: str | None = None
    decimals: int | None = None
    review_window_hours: int | None = None

    def __post_init__(self) -> None:
        if self.combination not in COMBINATION_RULES:
            raise GradePolicyError(
                f"grade-policy rule {self.combination!r} is not in the closed "
                f"vocabulary {COMBINATION_RULES} (FR-PKG-14). A free-text formula, an "
                "executable expression or a lambda-shaped string is refused: the policy "
                "is a structured object a machine can execute and a teacher can read, "
                "never a formula."
            )
        if self.combination == "weighted_sum":
            if self.k is not None or self.drop is not None:
                raise GradePolicyError(
                    "a weighted_sum policy carries no k or drop — a parameter no rule "
                    "executes is a latent formula (FR-PKG-14)."
                )
            for criterion_id, weight in self.weights:
                if not criterion_id:
                    raise GradePolicyError(
                        "a weighted_sum weight names an empty criterion id."
                    )
                if not weight > 0:
                    raise GradePolicyError(
                        f"the weight for {criterion_id!r} is {weight!r}; weights are "
                        "positive — a zero or negative weight is a formula's job, not a "
                        "vocabulary member's."
                    )
        elif self.combination == "best_k_of_n":
            if self.k is None or self.k < 1:
                raise GradePolicyError(
                    "a best_k_of_n policy declares k >= 1 (FR-PKG-14)."
                )
            if self.weights or self.drop is not None:
                raise GradePolicyError(
                    "a best_k_of_n policy carries no weights or drop — a parameter no "
                    "rule executes is a latent formula (FR-PKG-14)."
                )
        else:  # drop_lowest_n
            if self.drop is None or self.drop < 1:
                raise GradePolicyError(
                    "a drop_lowest_n policy declares drop >= 1 (FR-PKG-14)."
                )
            if self.weights or self.k is not None:
                raise GradePolicyError(
                    "a drop_lowest_n policy carries no weights or k — a parameter no "
                    "rule executes is a latent formula (FR-PKG-14)."
                )
        if self.gate is not None and (not self.gate.criterion_id
                                      or self.gate.minimum < 0):
            raise GradePolicyError(
                "a gate names a criterion and a minimum >= 0 (FR-GRADE-02's optional "
                "gate, as a vocabulary member of FR-PKG-14)."
            )
        if self.scale is not None and not (self.scale.factor > 0):
            raise GradePolicyError(
                "a scale factor is positive — a zero or negative factor is not a "
                "scaling rule (FR-PKG-14)."
            )
        if self.rounding is not None:
            if self.rounding not in ROUNDING_MODES:
                raise GradePolicyError(
                    f"rounding mode {self.rounding!r} is not in {ROUNDING_MODES} "
                    "(FR-PKG-14)."
                )
            if self.decimals is None or self.decimals < 0:
                raise GradePolicyError(
                    "a rounding rule declares its decimals >= 0 (FR-PKG-14)."
                )
        elif self.decimals is not None:
            raise GradePolicyError(
                "decimals without a rounding mode is a parameter no rule executes "
                "(FR-PKG-14) — set rounding with it."
            )
        if self.review_window_hours is not None:
            if (isinstance(self.review_window_hours, bool)
                    or not isinstance(self.review_window_hours, int)
                    or self.review_window_hours < 0):
                raise GradePolicyError(
                    f"review_window_hours is {self.review_window_hours!r}; it is a "
                    "nullable INTEGER >= 0 (ADR-3, FR-PKG-19): null means finalize on "
                    "run completion, a negative window would end before it begins."
                )

    @property
    def plain_language(self) -> str:
        """The approved wording, GENERATED from the object (`FR-PKG-15`).

        A property, not a field: there is no constructor argument, no setter and no
        stored form, so independent wording cannot enter through any API and the
        approved wording and the executed policy cannot diverge. Regenerating from the
        same object is byte-stable (a pure function of the fields)."""
        if self.combination == "weighted_sum":
            if self.weights:
                listing = ", ".join(f"{criterion} x{weight:g}"
                                    for criterion, weight in self.weights)
                head = f"Weighted sum of criterion points ({listing})."
            else:
                head = "Sum of criterion points, summed into question and test totals."
        elif self.combination == "best_k_of_n":
            head = f"Best {self.k} of the criteria count toward the total."
        else:
            head = f"The lowest {self.drop} criterion scores are dropped before summing."
        parts = [head]
        if self.gate is not None:
            parts.append(f"Gate: {self.gate.criterion_id} must reach "
                         f"{self.gate.minimum:g} points.")
        if self.scale is not None:
            parts.append(f"The total is scaled by {self.scale.factor:g}.")
        if self.rounding is not None:
            word = {"nearest": "to the nearest", "up": "up", "down": "down"}[
                self.rounding]
            parts.append(f"Rounded {word} at {self.decimals} decimal place(s).")
        if self.review_window_hours is None:
            parts.append("Finalizes on run completion.")
        else:
            parts.append(f"Review window: {self.review_window_hours} hour(s) before "
                         "finalization.")
        return " ".join(parts)

    def to_dict(self) -> dict:
        """The structured content as stored. `review_window_hours` is absent on purpose:
        it lives in its own column (ADR-3), the single canonical place — writing it
        twice in one row would be two representations of one rule."""
        return {
            "combination": self.combination,
            "weights": [list(pair) for pair in self.weights],
            "k": self.k,
            "drop": self.drop,
            "gate": ({"criterion_id": self.gate.criterion_id,
                      "minimum": self.gate.minimum} if self.gate else None),
            "scale": ({"factor": self.scale.factor} if self.scale else None),
            "rounding": self.rounding,
            "decimals": self.decimals,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GradePolicy":
        """Rebuild from stored JSON — re-validating against the closed vocabulary, so a
        row hand-edited to hold a formula refuses on read too (`FR-PKG-14` holds at
        every door, not only at the write)."""
        fields = dict(data)
        if isinstance(fields.get("gate"), dict):
            fields["gate"] = GateRule(**fields["gate"])
        if isinstance(fields.get("scale"), dict):
            fields["scale"] = ScaleRule(**fields["scale"])
        if isinstance(fields.get("weights"), list):
            fields["weights"] = tuple((str(c), float(w)) for c, w in fields["weights"])
        try:
            return cls(**fields)
        except (TypeError, ValueError, KeyError) as error:
            # A stored row that is not a valid policy dict (hand-edited, corrupt) is a
            # vocabulary refusal, not a raw TypeError: FR-PKG-14 holds at read too.
            raise GradePolicyError(
                f"the stored grade policy is not a structured object from the closed "
                f"rule vocabulary (FR-PKG-14): {error}"
            ) from error


def default_grade_policy() -> GradePolicy:
    """`FR-SETUP-12`'s default: unweighted sum of criteria into question and test
    totals, raw points, no transforms, null review window (finalize on run completion).
    `grade_policy()` answers this for a version with no stored policy, so M-GRADE
    always finds a policy and never invents one (`CT-SETUP-10`); recording that the
    default was used is M-SETUP's obligation, discharged by storing the policy."""
    return GradePolicy()


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
    """One `real_verbatim` exemplar the export gate is holding (`FR-PKG-11`)."""

    exemplar_id: str
    package_version_id: str
    criterion_id: str
    band: str


@dataclass(frozen=True)
class ProvenanceReport:
    """What `export_provenance_report()` answers: the gate state and every row holding
    it, so the console's approval screen is actionable (`FR-PKG-12`)."""

    package_id: str
    package_version_id: str
    contains_real_student_text: bool
    real_verbatim: tuple[ProvenanceEntry, ...]


@dataclass(frozen=True)
class ExportReport:
    """What one export did (`CLAUDE.md` seam 4 — per-field, not a boolean)."""

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
    """What one import did. `package_version_id` is the Protocol's answer;
    `signature_status` is NFR-PKG-04's mandatory report — an unsigned or mismatched
    package is REPORTED and imported, never silently accepted, never refused outright.

    `signature_status` ∈ verified | unsigned | mismatched | unverifiable (a signature
    is present but this installation holds no key — distinct from both unsigned and
    mismatched; test plan §2.3 Q-07 leaves the finer grading open)."""

    package_version_id: str
    package_id: str
    schema_version: int
    signature_status: str
    blobs_imported: int
    src: str


#: The exemplar provenance vocabulary (ADR-4). `real_verbatim` is the canonical value
#: for a real student response used verbatim — the export gate's one test.
PROVENANCE_VOCABULARY: tuple[str, ...] = ("synthetic", "paraphrased", "real_verbatim")


# --- validation records, NoValidationData, the manifest (FR-PKG-08/-09/-12/-21) -----------------
#
# The structural rule: a package can never advertise a single "validated" figure. Every
# validation row is keyed by population, backend, panel build and scoring model; the query
# surface returns records per key or an explicit `NoValidationData` — never an aggregate,
# never zero, never a figure from an adjacent key. HLD §2.1's error (a package-level
# headline across populations) is made unrepresentable in the query surface.


class NoValidationData:
    """The explicit result for a validation key with no matching row (`FR-PKG-09`).

    Distinguishable **in type** from a zero or a low figure — a caller that renders it as
    `0.0` has reintroduced the failure this requirement exists to prevent. Not an
    exception: "no data" is a normal state of a brand-new package version, and the
    console displays it as its own thing (`FR-CONSOLE-24`)."""

    _instance: "NoValidationData | None" = None

    def __new__(cls) -> "NoValidationData":
        # A singleton keeps every absent-key answer the same object: `result is
        # NoValidationData()` is a second, type-level way to test, and equality across
        # calls is free.
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "NoValidationData()"

    def __str__(self) -> str:
        return "no validation data for this key"


@dataclass(frozen=True)
class ManifestEntry:
    """One population's validation entry in the manifest (`FR-PKG-21`)."""

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
    """The package manifest (`FR-PKG-21`): per-population validation entries, the
    weakest criterion per population, exemplar provenance and schema version — and
    deliberately **no** field aggregating validation across populations. A package that
    advertises one headline number repeats HLD §2.1's error in portable form; the shape
    makes it unrepresentable."""

    package_version_id: str
    schema_version: int
    entries: tuple[ManifestEntry, ...]
    exemplar_provenance: tuple[str, ...]


def _weakest_entry(entries: list[ManifestEntry]) -> list[ManifestEntry]:
    """Flag the weakest entry per population (`FR-STATS-13`'s travel-along): the lowest
    agreement with n >= 1. The manifest carries it deliberately — a package advertising
    only its overall number is the portable form of the §2.1 error."""
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


# --- the Tier P migration this module contributes (design §3.3's decision table) ---------------
#
# `M-STORE` owns the migration *mechanism*; the owning module contributes the migrations.
# #26's migration adds the lineage columns the schema's minimal 001 set did not carry and
# installs the immutability triggers — the database half of `NFR-PKG-01`.

_PKG_SCHEMA_LOCK_COLUMNS = Migration(
    version=3,
    name="pkg_schema_lock_columns",
    statements=(
        Statement("ALTER TABLE criterion ADD COLUMN max_points REAL"),
        Statement("ALTER TABLE criterion ADD COLUMN band_count INTEGER"),
        Statement("ALTER TABLE criterion ADD COLUMN scoring_model TEXT"),
        Statement("ALTER TABLE criterion ADD COLUMN construct_tag TEXT"),
        Statement("ALTER TABLE band ADD COLUMN descriptor TEXT"),
        Statement("ALTER TABLE exemplar ADD COLUMN provenance TEXT"),
    ),
)

_PKG_VALIDATION_KEYS = Migration(
    version=4,
    name="pkg_validation_keys",
    statements=(
        Statement("ALTER TABLE validation_record ADD COLUMN criterion_id TEXT"),
        Statement(
            "ALTER TABLE validation_record ADD COLUMN population_scope_id TEXT"),
        Statement("ALTER TABLE validation_record ADD COLUMN scoring_model TEXT"),
        Statement("ALTER TABLE validation_record ADD COLUMN agreement REAL"),
        Statement("ALTER TABLE validation_record ADD COLUMN n INTEGER"),
        Statement(
            "CREATE UNIQUE INDEX validation_record_key ON validation_record "
            "(package_version_id, criterion_id, population_scope_id, backend_profile, "
            "panel_build_ref, scoring_model)"
        ),
    ),
)

_PKG_GRADE_POLICY_AND_KEYS = Migration(
    version=5,
    name="pkg_grade_policy_and_keys",
    statements=(
        # FR-PKG-17: the key is a column on criterion — one canonical representation.
        Statement("ALTER TABLE criterion ADD COLUMN answer_key TEXT"),
        # ADR-1: the options table carries NO correctness column — not is_correct, not
        # correct_option, nothing. The key lives once, on criterion.answer_key; a second
        # representation is how a corrected key leaves two disagreeing sources behind.
        Statement(
            """
            CREATE TABLE mcq_option (
                package_version_id TEXT NOT NULL,
                criterion_id       TEXT NOT NULL,
                option_id          TEXT NOT NULL,
                label              TEXT NOT NULL,
                PRIMARY KEY (package_version_id, criterion_id, option_id),
                FOREIGN KEY (package_version_id, criterion_id)
                    REFERENCES criterion(package_version_id, criterion_id)
            )
            """
        ),
        # FR-PKG-16: the boundary table is the single canonical representation of the
        # grade resolution rule. Floors are INCLUSIVE — boundary_for resolves the grade
        # with the greatest floor <= the scaled score.
        Statement(
            """
            CREATE TABLE grade_boundary (
                package_version_id TEXT NOT NULL REFERENCES package_version(package_version_id),
                grade              TEXT NOT NULL,
                scaled_floor       REAL NOT NULL,
                PRIMARY KEY (package_version_id, grade)
            )
            """
        ),
        # ADR-3: the review window is a column, not a policy-JSON field.
        Statement("ALTER TABLE grade_policy ADD COLUMN review_window_hours INTEGER"),
        # FR-PKG-20 / FR-CALIB-14: the calibration audit trail — every question asked,
        # options offered, answer given, resulting edit. It is the record that answers
        # "why does the rubric say this now", which is why it is append-only below.
        Statement(
            """
            CREATE TABLE elicitation_history (
                elicitation_id     TEXT NOT NULL PRIMARY KEY,
                package_version_id TEXT NOT NULL REFERENCES package_version(package_version_id),
                question           TEXT NOT NULL,
                options_offered    TEXT NOT NULL,
                answer_given       TEXT NOT NULL,
                resulting_edit     TEXT NOT NULL DEFAULT '',
                asked_at           TEXT NOT NULL
            )
            """
        ),
        # FR-PKG-20: append-only IN PRACTICE, not by convention — an unconditional
        # trigger pair aborts any UPDATE or DELETE, including raw SQL around the catalog.
        Statement(
            "CREATE TRIGGER elicitation_history_append_only_update "
            "BEFORE UPDATE ON elicitation_history "
            "BEGIN SELECT RAISE(ABORT, 'elicitation_history is append-only: rows are "
            "never updated (FR-PKG-20)'); END"
        ),
        Statement(
            "CREATE TRIGGER elicitation_history_append_only_delete "
            "BEFORE DELETE ON elicitation_history "
            "BEGIN SELECT RAISE(ABORT, 'elicitation_history is append-only: rows are "
            "never deleted (FR-PKG-20)'); END"
        ),
        # The 002 pattern, carried to the new content tables: a published version's
        # options and boundaries are immutable — plus the DELETE refusal 002's tables
        # predate. grade_policy gets one too: this diff introduces its first DELETE
        # statement (set_grade_policy's draft rewrite), so the backstop moves with it.
        # elicitation_history is deliberately NOT here: appends are always allowed (the
        # trail records conversations about the rubric as published).
        Statement(
            "CREATE TRIGGER grade_policy_delete_refused BEFORE DELETE ON grade_policy "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: grade policy "
            "removed from a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER mcq_option_immutable BEFORE UPDATE ON mcq_option "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: mcq_option "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER mcq_option_insert_locked BEFORE INSERT ON mcq_option "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: mcq_option "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER mcq_option_delete_refused BEFORE DELETE ON mcq_option "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: mcq_option "
            "removed from a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER grade_boundary_immutable BEFORE UPDATE ON grade_boundary "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: grade_boundary "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER grade_boundary_insert_locked BEFORE INSERT ON grade_boundary "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: grade_boundary "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER grade_boundary_delete_refused BEFORE DELETE ON grade_boundary "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: grade_boundary "
            "removed from a published version'); END"
        ),
    ),
)

_PKG_EXPORT_GATE = Migration(
    version=6,
    name="pkg_export_gate",
    statements=(
        # ADR-4: the flag is DERIVED from exemplar presence — the catalog recomputes it
        # on every exemplar write, so flag and rows cannot disagree. A stored column,
        # because the export gate (FR-PKG-11) and the console read one value.
        Statement(
            "ALTER TABLE package ADD COLUMN contains_real_student_text INTEGER NOT NULL "
            "DEFAULT 0 CHECK (contains_real_student_text IN (0, 1))"
        ),
        # CT-STORE-07: exemplar material lives in the content-addressed blob store; the
        # reference is the hash itself (verified on get, no FK — blobs are content-
        # addressed across the whole installation). Nullable: a text-only exemplar.
        Statement("ALTER TABLE exemplar ADD COLUMN blob_hash TEXT"),
    ),
)

_PKG_VERSION_LINEAGE = Migration(
    version=2,
    name="pkg_version_lineage",
    statements=(
        Statement(
            "ALTER TABLE package_version ADD COLUMN parent_version_id "
            "REFERENCES package_version(package_version_id)"
        ),
        Statement("ALTER TABLE package_version ADD COLUMN published_by TEXT"),
        Statement("ALTER TABLE package_version ADD COLUMN published_at TEXT"),
        # The immutability backstops: UPDATE triggers on every guarded table, plus
        # INSERT triggers on the child tables (adding a row to a published version's
        # content is the §6.2 edit-in-place FR-PKG-04 refuses). Both fire only when the
        # referenced version is locked, so a revision's copies into its own unlocked
        # version pass.
        Statement(
            "CREATE TRIGGER package_version_immutable BEFORE UPDATE ON package_version "
            "WHEN OLD.locked = 1 "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: create a "
            "revision instead'); END"
        ),
        Statement(
            "CREATE TRIGGER criterion_immutable BEFORE UPDATE ON criterion "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: criterion "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER band_immutable BEFORE UPDATE ON band "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: band references "
            "a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER criterion_dependency_immutable BEFORE UPDATE ON "
            "criterion_dependency "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: dependency "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER exemplar_immutable BEFORE UPDATE ON exemplar "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: exemplar "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER grade_policy_immutable BEFORE UPDATE ON grade_policy "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: grade policy "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER validation_record_immutable BEFORE UPDATE ON "
            "validation_record "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: validation "
            "record references a published version'); END"
        ),
        # INSERT triggers on the child tables: ADDING a sub-criterion (or band, exemplar,
        # policy, dependency) to a published version is the §6.2 edit-in-place
        # FR-PKG-04 refuses — the new rows would silently change what the published
        # version contains. They fire only when the referenced version is locked, so a
        # revision's copies into its own unlocked version pass.
        Statement(
            "CREATE TRIGGER criterion_insert_locked BEFORE INSERT ON criterion "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: criterion added "
            "to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER band_insert_locked BEFORE INSERT ON band "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: band added to a "
            "published version'); END"
        ),
        Statement(
            "CREATE TRIGGER criterion_dependency_insert_locked BEFORE INSERT ON "
            "criterion_dependency "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: dependency "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER exemplar_insert_locked BEFORE INSERT ON exemplar "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: exemplar added "
            "to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER grade_policy_insert_locked BEFORE INSERT ON grade_policy "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: grade policy "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER validation_record_insert_locked BEFORE INSERT ON "
            "validation_record "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: validation "
            "record added to a published version'); END"
        ),
    ),
)

# The question inventory (HLD §9.5's `question` and per-question option tables) and the
# setup-proposal record #50 stages. Ownership: M-PKG is Tier P's sole writer (`CT-PKG-12`,
# §3.4's "questions and MCQ options"); M-SETUP reaches these rows only through the catalog
# methods below. Rows are written ONCE, at `confirm_inventory` — the teacher's assertion
# about content — and the confirmation lock engages there (FR-SETUP-02), deliberately
# earlier than publication. The tables are empty until that confirmation.
#
# Two locks, in trigger form (NFR-PKG-01: at the data layer, so a caller that routes
# around the catalog hits the database's own refusal):
#   * published immunity — the 002 pattern, carried to all three tables: a published
#     version's rows refuse UPDATE, INSERT and DELETE.
#   * the confirmation lock — a CONFIRMED question row refuses edits of its content
#     columns (prompt, ordinal, points, type) and its removal, while
#     `reference_solution` stays writable (the rubric read-back, #51, fills it on a
#     confirmed version); an option of a confirmed question refuses UPDATE and DELETE.
#     The option table's INSERT path is deliberately NOT confirmation-locked: the
#     revision copy's vehicle is an INSERT into the child version, whose copied
#     questions are born confirmed — a trigger there would break FR-PKG-02's copy.
#     The catalog's `write_confirmed_inventory` (which refuses an already-confirmed
#     proposal) is the only sanctioned writer, and a raw-SQL option INSERT can only
#     ADD to a confirmed inventory, never unconfirm it: `publish`'s gate reads
#     `setup_proposal.confirmed_at` plus the question rows, so the hole fails closed.
#
# Named divergence from the HLD §9.5 DDL: the per-question option table is
# `question_option`, because migration 005 took `mcq_option` for the criterion-scoped
# table (#31) and two tables of one name cannot share a schema. ADR-1's shape is kept:
# NO correctness column — the key lives on `criterion.answer_key` (FR-PKG-17), and
# option correctness is not declared at setup time at all.
_PKG_QUESTION_INVENTORY = Migration(
    version=7,
    name="pkg_question_inventory",
    statements=(
        # `confirmed_at` is NOT NULL on purpose: a question row exists ONLY because the
        # inventory was confirmed, and the schema should say so — the same taste as the
        # §6.2 lock itself (a constraint, not a convention).
        Statement(
            """
            CREATE TABLE question (
                package_version_id TEXT    NOT NULL REFERENCES package_version(package_version_id),
                question_id        TEXT    NOT NULL,
                ordinal            INTEGER NOT NULL CHECK (ordinal >= 0),
                prompt_text        TEXT    NOT NULL,
                question_type      TEXT    NOT NULL CHECK (question_type IN ('open', 'mcq', 'mixed')),
                max_points         REAL    NOT NULL DEFAULT 0.0 CHECK (max_points >= 0),
                reference_solution TEXT,
                confirmed_at       TEXT    NOT NULL,
                PRIMARY KEY (package_version_id, question_id)
            )
            """
        ),
        Statement(
            """
            CREATE TABLE question_option (
                package_version_id TEXT    NOT NULL,
                question_id        TEXT    NOT NULL,
                option_id          TEXT    NOT NULL,
                ordinal            INTEGER NOT NULL CHECK (ordinal >= 0),
                label              TEXT    NOT NULL,
                PRIMARY KEY (package_version_id, question_id, option_id),
                FOREIGN KEY (package_version_id, question_id)
                    REFERENCES question(package_version_id, question_id)
            )
            """
        ),
        # One proposal per version (the PK): `propose_inventory` runs once per version
        # (CT-SETUP-16); re-requests after an unparseable model reply UPDATE the same
        # row (payload + attempts), and confirmation stamps `confirmed_at`. The payload
        # is the proposal JSON as proposed — the provenance of what the teacher saw.
        Statement(
            """
            CREATE TABLE setup_proposal (
                package_version_id TEXT    NOT NULL PRIMARY KEY
                    REFERENCES package_version(package_version_id),
                proposal_id        TEXT    NOT NULL,
                assessment_doc_id  TEXT    NOT NULL,
                payload            TEXT    NOT NULL,
                template_version   TEXT    NOT NULL,
                model_ref          TEXT    NOT NULL,
                attempts           INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
                created_at         TEXT    NOT NULL,
                confirmed_at       TEXT
            )
            """
        ),
        # -- published immunity (the 002 pattern) --
        Statement(
            "CREATE TRIGGER question_immutable BEFORE UPDATE ON question "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: question "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER question_insert_locked BEFORE INSERT ON question "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: question added "
            "to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER question_delete_refused BEFORE DELETE ON question "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: question "
            "removed from a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER question_option_immutable BEFORE UPDATE ON question_option "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: question_option "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER question_option_insert_locked BEFORE INSERT ON "
            "question_option "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: question_option "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER question_option_delete_refused BEFORE DELETE ON "
            "question_option "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: question_option "
            "removed from a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_proposal_immutable BEFORE UPDATE ON setup_proposal "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: setup_proposal "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_proposal_insert_locked BEFORE INSERT ON "
            "setup_proposal "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: setup_proposal "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_proposal_delete_refused BEFORE DELETE ON "
            "setup_proposal "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: setup_proposal "
            "removed from a published version'); END"
        ),
        # -- the confirmation lock (FR-SETUP-02): engages at confirm_inventory, before
        # -- publication. One trigger per content column, so the refusal names the field.
        Statement(
            "CREATE TRIGGER question_confirmed_prompt_text BEFORE UPDATE ON question "
            "WHEN OLD.confirmed_at IS NOT NULL "
            "AND OLD.prompt_text IS NOT NEW.prompt_text "
            "BEGIN SELECT RAISE(ABORT, 'confirmed question rows are locked "
            "(FR-SETUP-02): prompt_text is the teacher-confirmed content'); END"
        ),
        Statement(
            "CREATE TRIGGER question_confirmed_ordinal BEFORE UPDATE ON question "
            "WHEN OLD.confirmed_at IS NOT NULL "
            "AND OLD.ordinal IS NOT NEW.ordinal "
            "BEGIN SELECT RAISE(ABORT, 'confirmed question rows are locked "
            "(FR-SETUP-02): ordinal is the teacher-confirmed order'); END"
        ),
        Statement(
            "CREATE TRIGGER question_confirmed_max_points BEFORE UPDATE ON question "
            "WHEN OLD.confirmed_at IS NOT NULL "
            "AND OLD.max_points IS NOT NEW.max_points "
            "BEGIN SELECT RAISE(ABORT, 'confirmed question rows are locked "
            "(FR-SETUP-02): max_points is the teacher-confirmed content'); END"
        ),
        Statement(
            "CREATE TRIGGER question_confirmed_question_type BEFORE UPDATE ON question "
            "WHEN OLD.confirmed_at IS NOT NULL "
            "AND OLD.question_type IS NOT NEW.question_type "
            "BEGIN SELECT RAISE(ABORT, 'confirmed question rows are locked "
            "(FR-SETUP-02): question_type is the teacher-confirmed content — HLD §7.8 "
            "names the open/mcq conversion a redefinition'); END"
        ),
        Statement(
            "CREATE TRIGGER question_confirmed_delete_refused BEFORE DELETE ON question "
            "WHEN OLD.confirmed_at IS NOT NULL "
            "BEGIN SELECT RAISE(ABORT, 'confirmed question rows are locked "
            "(FR-SETUP-02): a confirmed question is not removed — corrections happen "
            "before confirmation'); END"
        ),
        Statement(
            "CREATE TRIGGER question_option_confirmed BEFORE UPDATE ON question_option "
            "WHEN EXISTS (SELECT 1 FROM question q WHERE q.package_version_id "
            "= OLD.package_version_id AND q.question_id = OLD.question_id "
            "AND q.confirmed_at IS NOT NULL) "
            "BEGIN SELECT RAISE(ABORT, 'confirmed question rows are locked "
            "(FR-SETUP-02): an option of a confirmed question is not editable'); END"
        ),
        Statement(
            "CREATE TRIGGER question_option_confirmed_delete_refused BEFORE DELETE ON "
            "question_option "
            "WHEN EXISTS (SELECT 1 FROM question q WHERE q.package_version_id "
            "= OLD.package_version_id AND q.question_id = OLD.question_id "
            "AND q.confirmed_at IS NOT NULL) "
            "BEGIN SELECT RAISE(ABORT, 'confirmed question rows are locked "
            "(FR-SETUP-02): an option of a confirmed question is not removed'); END"
        ),
    ),
)

# The rubric read-back (§3.6, #51): the provenance row for the one read-back per version
# (CT-SETUP-16, the proposal row's twin) and the two criterion columns the read back fills.
#
# `evidence_type` (FR-SETUP-09) declares what kind of textual evidence satisfies the
# criterion — M-INTEG routes on it (FR-INTEG-03: empty evidence is routed, never
# auto-scored). The design pins no closed vocabulary for it (M-EXTRACT's interface example
# names `textual_span`), so the column is TEXT without a CHECK: a CHECK would invent the
# vocabulary the design withholds.
#
# `band_justification` (FR-SETUP-04) records WHY a criterion carries more than the default
# two bands — partial credit genuinely part of the construct — so the wider band set is
# auditable rather than arbitrary. Written only through `write_readback`, which refuses a
# band_count above two without one.
#
# Neither column joins SCHEMA_LOCK_FIELDS: the §6.2 list enumerates the HLD's named fields
# (13, unchanged), and a published version's criterion rows already refuse EVERY UPDATE
# through the migration-002 triggers — a new column is locked by the same backstop, not by
# a second list.
#
# The read-back row is written ONCE, after the criteria it produced are written, in the
# same transaction; a draft re-runs nothing (resume returns the stored row, CT-SETUP-03).
# Published immunity is the 002 pattern carried to the new table. No confirmation lock:
# criteria are not question rows — they are mutable until the version publishes.
_PKG_SETUP_READBACK = Migration(
    version=8,
    name="pkg_setup_readback",
    statements=(
        Statement(
            "ALTER TABLE criterion ADD COLUMN evidence_type TEXT"
        ),
        Statement(
            "ALTER TABLE criterion ADD COLUMN band_justification TEXT"
        ),
        Statement(
            """
            CREATE TABLE setup_readback (
                package_version_id TEXT    NOT NULL PRIMARY KEY
                    REFERENCES package_version(package_version_id),
                rubric_doc_id      TEXT    NOT NULL,
                assessment_doc_id  TEXT    NOT NULL,
                payload            TEXT    NOT NULL,
                template_version   TEXT    NOT NULL,
                model_ref          TEXT    NOT NULL,
                attempts           INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
                created_at         TEXT    NOT NULL
            )
            """
        ),
        # -- published immunity (the 002 pattern) --
        Statement(
            "CREATE TRIGGER setup_readback_immutable BEFORE UPDATE ON setup_readback "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: setup_readback "
            "references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_readback_insert_locked BEFORE INSERT ON "
            "setup_readback "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: setup_readback "
            "added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_readback_delete_refused BEFORE DELETE ON "
            "setup_readback "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: setup_readback "
            "removed from a published version'); END"
        ),
    ),
)

_PKG_SETUP_CLASSIFICATION = Migration(
    # #52: the decomposability verdicts and the setup steps' provenance rows. Two
    # tables, because they answer two different audit questions:
    #
    # `setup_classification` — one row per (version, criterion): the classification
    # the §5.3 table produced (`source='default'`, the module's own decision) and the
    # one the teacher confirmed over it (`source='teacher'`, upserted by
    # `confirm_classifications`). HLD R62's distinction: M-CALIB and M-STATS must be
    # able to tell a teacher's judgment from a system default, so a skipped
    # confirmation leaves the default row standing rather than nothing at all.
    # `decomposition_basis` is FR-SETUP-06's record of WHICH question decided —
    # an audit field, not a scoring input (the scoring input is the criterion's
    # `scoring_model`, which the read back writes from the same table).
    #
    # `setup_step_record` — one row per (version, step_id): how each non-blocking
    # setup step was completed (`FR-SETUP-14`: a default taken is recorded, never
    # indistinguishable from an explicit choice). #53's grade-policy and prefix-budget
    # steps write the same table; the row exists so a skip-only run still leaves
    # stored provenance naming the step.
    version=9,
    name="pkg_setup_classification",
    statements=(
        Statement(
            """
            CREATE TABLE setup_classification (
                package_version_id TEXT    NOT NULL,
                criterion_id       TEXT    NOT NULL,
                classification     TEXT    NOT NULL,
                decomposition_basis TEXT,
                source             TEXT    NOT NULL
                    CHECK (source IN ('default', 'teacher')),
                recorded_at        TEXT    NOT NULL,
                PRIMARY KEY (package_version_id, criterion_id),
                FOREIGN KEY (package_version_id)
                    REFERENCES package_version(package_version_id)
            )
            """
        ),
        Statement(
            """
            CREATE TABLE setup_step_record (
                package_version_id TEXT    NOT NULL,
                step_id            TEXT    NOT NULL,
                status             TEXT    NOT NULL,
                payload            TEXT    NOT NULL,
                recorded_at        TEXT    NOT NULL,
                PRIMARY KEY (package_version_id, step_id),
                FOREIGN KEY (package_version_id)
                    REFERENCES package_version(package_version_id)
            )
            """
        ),
        # -- published immunity (the 002/8 pattern): a published version's setup
        #    provenance is part of the record a defended grade leans on --
        Statement(
            "CREATE TRIGGER setup_classification_immutable BEFORE UPDATE ON "
            "setup_classification "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "setup_classification references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_classification_insert_locked BEFORE INSERT ON "
            "setup_classification "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "setup_classification added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_classification_delete_refused BEFORE DELETE ON "
            "setup_classification "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "setup_classification removed from a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_step_record_immutable BEFORE UPDATE ON "
            "setup_step_record "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "setup_step_record references a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_step_record_insert_locked BEFORE INSERT ON "
            "setup_step_record "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= NEW.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "setup_step_record added to a published version'); END"
        ),
        Statement(
            "CREATE TRIGGER setup_step_record_delete_refused BEFORE DELETE ON "
            "setup_step_record "
            "WHEN EXISTS (SELECT 1 FROM package_version pv WHERE pv.package_version_id "
            "= OLD.package_version_id AND pv.locked = 1) "
            "BEGIN SELECT RAISE(ABORT, 'published version is immutable: "
            "setup_step_record removed from a published version'); END"
        ),
    ),
)

# --- the owning-module contribution to the store's migration registry ---------------------------
#
# Appended at import: after this module is imported, Tier P's current schema version is 2
# and every store opened afterwards applies the lineage migration. The migration's
# statements are registered in the store's STATEMENTS registry too — the store's rule is
# that every statement it can issue is registered, and the registry is built when store.py
# is imported, so the contribution extends it here.

PKG_STATEMENTS: dict[str, Statement] = {
    f"pkg_version_lineage_{index:02d}": statement
    for index, statement in enumerate(_PKG_VERSION_LINEAGE.statements)
}
PKG_STATEMENTS.update({
    "select_version": Statement(
        "SELECT package_version_id, package_id, revision, locked, parent_version_id "
        "FROM package_version WHERE package_version_id = :v"
    ),
    "insert_first_version": Statement(
        "INSERT INTO package_version (package_version_id, package_id, revision, locked) "
        "VALUES (:v, :p, 1, 0)"
    ),
    "insert_revision": Statement(
        "INSERT INTO package_version (package_version_id, package_id, revision, locked, "
        "parent_version_id) VALUES (:v, :p, :rev, 0, :parent)"
    ),
    "publish": Statement(
        "UPDATE package_version SET locked = 1, published_by = :by, "
        "published_at = datetime('now') WHERE package_version_id = :v"
    ),
    "count_package": Statement(
        "SELECT COUNT(*) AS n FROM package WHERE package_id = :p"
    ),
    "pkg_revision_copy_criterion": Statement(
        # The copy is VERBATIM — every column the M-PKG module defines on the table
        # (#230): a revision that drops criterion fields is mutation by omission, and
        # CT-PKG-02's invariant (a PackageVersionId identifies content permanently)
        # fails with it. The #51-era note stands: a revision copies the read-back
        # payload row too, so a payload asserting an evidence_type cannot sit beside
        # criterion rows whose evidence_type the copy silently NULLed.
        "INSERT INTO criterion (package_version_id, criterion_id, question_id, kind, "
        "max_points, scoring_model, construct_tag, band_count, answer_key, "
        "evidence_type, band_justification) "
        "SELECT :new, criterion_id, question_id, kind, max_points, scoring_model, "
        "construct_tag, band_count, answer_key, evidence_type, band_justification "
        "FROM criterion WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_band": Statement(
        # The descriptor rides with the set (#230): a band without its descriptor is
        # the judge-facing mapping half-erased.
        "INSERT INTO band (package_version_id, criterion_id, ordinal, band, points, "
        "descriptor) SELECT :new, criterion_id, ordinal, band, points, descriptor "
        "FROM band WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_dependency": Statement(
        "INSERT INTO criterion_dependency (package_version_id, criterion_id, depends_on) "
        "SELECT :new, criterion_id, depends_on FROM criterion_dependency "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_exemplar": Statement(
        "INSERT INTO exemplar (exemplar_id, package_version_id, criterion_id, band, "
        "provenance, blob_hash) SELECT hex(randomblob(8)), :new, criterion_id, band, "
        "provenance, blob_hash FROM exemplar WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_grade_policy": Statement(
        "INSERT INTO grade_policy (package_version_id, policy, review_window_hours) "
        "SELECT :new, policy, review_window_hours FROM grade_policy "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_mcq_option": Statement(
        "INSERT INTO mcq_option (package_version_id, criterion_id, option_id, label) "
        "SELECT :new, criterion_id, option_id, label FROM mcq_option "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_grade_boundary": Statement(
        "INSERT INTO grade_boundary (package_version_id, grade, scaled_floor) "
        "SELECT :new, grade, scaled_floor FROM grade_boundary "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_question": Statement(
        "INSERT INTO question (package_version_id, question_id, ordinal, prompt_text, "
        "question_type, max_points, reference_solution, confirmed_at) SELECT :new, "
        "question_id, ordinal, prompt_text, question_type, max_points, "
        "reference_solution, confirmed_at FROM question WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_question_option": Statement(
        "INSERT INTO question_option (package_version_id, question_id, option_id, "
        "ordinal, label) SELECT :new, question_id, option_id, ordinal, label "
        "FROM question_option WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_setup_proposal": Statement(
        "INSERT INTO setup_proposal (package_version_id, proposal_id, "
        "assessment_doc_id, payload, template_version, model_ref, attempts, "
        "created_at, confirmed_at) SELECT :new, proposal_id, assessment_doc_id, "
        "payload, template_version, model_ref, attempts, created_at, confirmed_at "
        "FROM setup_proposal WHERE package_version_id = :old"
    ),
    "insert_criterion": Statement(
        "INSERT INTO criterion (package_version_id, criterion_id, question_id, kind, "
        "max_points, scoring_model, construct_tag, band_count, evidence_type) VALUES "
        "(:v, :criterion_id, :question_id, :kind, :max_points, :scoring_model, "
        ":construct_tag, :band_count, :evidence_type)"
    ),
    "insert_dependency": Statement(
        "INSERT INTO criterion_dependency (package_version_id, criterion_id, "
        "depends_on) VALUES (:v, :criterion_id, :depends_on)"
    ),
    "insert_band": Statement(
        "INSERT INTO band (package_version_id, criterion_id, ordinal, band, points, "
        "descriptor) VALUES (:v, :criterion_id, :ordinal, :band, :points, :descriptor)"
    ),
    "insert_exemplar": Statement(
        "INSERT INTO exemplar (exemplar_id, package_version_id, criterion_id, band, "
        "provenance, blob_hash) VALUES (:exemplar_id, :v, :criterion_id, :band, "
        ":provenance, :blob_hash)"
    ),
    "select_criteria": Statement(
        "SELECT criterion_id, question_id, kind, max_points, scoring_model, "
        "construct_tag, band_count, answer_key, evidence_type, band_justification "
        "FROM criterion "
        "WHERE package_version_id = :v ORDER BY criterion_id"
    ),
    "select_bands": Statement(
        "SELECT criterion_id, ordinal, band, points, descriptor FROM band "
        "WHERE package_version_id = :v ORDER BY criterion_id, ordinal"
    ),
    "select_bands_by_criterion": Statement(
        "SELECT criterion_id, ordinal, band, points, descriptor FROM band "
        "WHERE criterion_id = :criterion_id ORDER BY ordinal"
    ),
    "select_dependencies": Statement(
        "SELECT criterion_id, depends_on FROM criterion_dependency "
        "WHERE package_version_id = :v"
    ),
    "delete_dependencies": Statement(
        "DELETE FROM criterion_dependency WHERE package_version_id = :v"
    ),
    "select_validation": Statement(
        "SELECT criterion_id, population_scope_id, backend_profile, panel_build_ref, "
        "scoring_model, agreement, n FROM validation_record "
        "WHERE package_version_id = :v "
        "AND (:criterion_id IS NULL OR criterion_id = :criterion_id) "
        "AND population_scope_id = :population_scope_id "
        "AND backend_profile = :backend_profile "
        "AND panel_build_ref = :panel_build_ref "
        "AND scoring_model = :scoring_model"
    ),
    "select_all_validations": Statement(
        "SELECT criterion_id, population_scope_id, backend_profile, panel_build_ref, "
        "scoring_model, agreement, n FROM validation_record "
        "WHERE package_version_id = :v"
    ),
    "insert_validation": Statement(
        "INSERT INTO validation_record (validation_record_id, package_version_id, "
        "criterion_id, population_scope_id, backend_profile, panel_build_ref, "
        "scoring_model, agreement, n, recorded_at) VALUES (hex(randomblob(8)), :v, "
        ":criterion_id, :population_scope_id, :backend_profile, :panel_build_ref, "
        ":scoring_model, :agreement, :n, datetime('now'))"
    ),
    "select_exemplar_provenance": Statement(
        "SELECT DISTINCT provenance FROM exemplar WHERE package_version_id = :v "
        "AND provenance IS NOT NULL"
    ),
    "select_latest_version": Statement(
        "SELECT package_version_id FROM package_version ORDER BY revision DESC LIMIT 1"
    ),
    # -- grade policy, boundaries, answer keys, elicitation history (#30) ----------------
    "select_policy": Statement(
        "SELECT policy, review_window_hours FROM grade_policy "
        "WHERE package_version_id = :v"
    ),
    "insert_policy": Statement(
        "INSERT INTO grade_policy (package_version_id, policy, review_window_hours) "
        "VALUES (:v, :policy, :review_window_hours)"
    ),
    "delete_policy": Statement(
        "DELETE FROM grade_policy WHERE package_version_id = :v"
    ),
    "select_boundaries": Statement(
        "SELECT grade, scaled_floor FROM grade_boundary "
        "WHERE package_version_id = :v ORDER BY scaled_floor"
    ),
    "delete_boundaries": Statement(
        "DELETE FROM grade_boundary WHERE package_version_id = :v"
    ),
    "insert_boundary": Statement(
        "INSERT INTO grade_boundary (package_version_id, grade, scaled_floor) "
        "VALUES (:v, :grade, :scaled_floor)"
    ),
    "select_answer_key_latest": Statement(
        "SELECT c.answer_key AS answer_key FROM criterion c "
        "JOIN package_version pv ON pv.package_version_id = c.package_version_id "
        "WHERE c.criterion_id = :criterion_id "
        "ORDER BY pv.revision DESC LIMIT 1"
    ),
    "update_criterion_answer_key": Statement(
        "UPDATE criterion SET answer_key = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "select_mcq_options": Statement(
        "SELECT option_id, label FROM mcq_option WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id ORDER BY option_id"
    ),
    "delete_mcq_options": Statement(
        "DELETE FROM mcq_option WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "insert_mcq_option": Statement(
        "INSERT INTO mcq_option (package_version_id, criterion_id, option_id, label) "
        "VALUES (:v, :criterion_id, :option_id, :label)"
    ),
    "insert_elicitation": Statement(
        "INSERT INTO elicitation_history (elicitation_id, package_version_id, question, "
        "options_offered, answer_given, resulting_edit, asked_at) "
        "VALUES (:id, :v, :question, :options_offered, :answer_given, "
        ":resulting_edit, datetime('now'))"
    ),
    # -- export gate, provenance, import (#31) --------------------------------------------
    "select_package_flag": Statement(
        "SELECT contains_real_student_text AS flag FROM package WHERE package_id = :p"
    ),
    "refresh_package_flag": Statement(
        "UPDATE package SET contains_real_student_text = "
        "CASE WHEN EXISTS (SELECT 1 FROM exemplar WHERE provenance = 'real_verbatim') "
        "THEN 1 ELSE 0 END WHERE package_id = :p"
    ),
    "select_real_verbatim_exemplars": Statement(
        "SELECT exemplar_id, package_version_id, criterion_id, band FROM exemplar "
        "WHERE provenance = 'real_verbatim' ORDER BY exemplar_id"
    ),
    "select_exemplar_blob_hashes": Statement(
        "SELECT DISTINCT blob_hash FROM exemplar WHERE blob_hash IS NOT NULL"
    ),
    "select_exemplar_by_id": Statement(
        "SELECT exemplar_id FROM exemplar WHERE package_version_id = :v "
        "AND exemplar_id = :exemplar_id"
    ),
    "update_exemplar_provenance": Statement(
        "UPDATE exemplar SET provenance = :value WHERE package_version_id = :v "
        "AND exemplar_id = :exemplar_id"
    ),
    "delete_exemplar": Statement(
        "DELETE FROM exemplar WHERE package_version_id = :v "
        "AND exemplar_id = :exemplar_id"
    ),
    "select_exemplars": Statement(
        "SELECT exemplar_id, criterion_id, band, provenance, blob_hash FROM exemplar "
        "WHERE package_version_id = :v ORDER BY exemplar_id"
    ),
    # -- question inventory and setup proposal (#50) --------------------------------------
    # The package row `create_version` refuses to mint (`_refuse_no_such_package`'s
    # message names M-SETUP as its writer): the initial version's setup flow creates it.
    "insert_package": Statement(
        "INSERT INTO package (package_id, created_at) VALUES (:p, datetime('now'))"
    ),
    "select_latest_draft_version": Statement(
        "SELECT package_version_id FROM package_version WHERE package_id = :p "
        "AND locked = 0 ORDER BY revision DESC LIMIT 1"
    ),
    "select_latest_package_version": Statement(
        "SELECT package_version_id FROM package_version WHERE package_id = :p "
        "ORDER BY revision DESC LIMIT 1"
    ),
    "select_has_version": Statement(
        "SELECT 1 AS one FROM package_version WHERE package_id = :p LIMIT 1"
    ),
    "insert_question": Statement(
        "INSERT INTO question (package_version_id, question_id, ordinal, prompt_text, "
        "question_type, max_points, reference_solution, confirmed_at) VALUES (:v, "
        ":question_id, :ordinal, :prompt_text, :question_type, :max_points, "
        ":reference_solution, :confirmed_at)"
    ),
    "select_questions": Statement(
        "SELECT question_id, ordinal, prompt_text, question_type, max_points, "
        "reference_solution, confirmed_at FROM question "
        "WHERE package_version_id = :v ORDER BY ordinal, question_id"
    ),
    "select_question": Statement(
        "SELECT question_id, ordinal, prompt_text, question_type, max_points, "
        "reference_solution, confirmed_at FROM question "
        "WHERE package_version_id = :v AND question_id = :question_id"
    ),
    "update_question_prompt_text": Statement(
        "UPDATE question SET prompt_text = :value WHERE package_version_id = :v "
        "AND question_id = :question_id"
    ),
    "update_question_ordinal": Statement(
        "UPDATE question SET ordinal = :value WHERE package_version_id = :v "
        "AND question_id = :question_id"
    ),
    "update_question_max_points": Statement(
        "UPDATE question SET max_points = :value WHERE package_version_id = :v "
        "AND question_id = :question_id"
    ),
    "update_question_question_type": Statement(
        "UPDATE question SET question_type = :value WHERE package_version_id = :v "
        "AND question_id = :question_id"
    ),
    "update_question_reference_solution": Statement(
        "UPDATE question SET reference_solution = :value WHERE package_version_id = :v "
        "AND question_id = :question_id"
    ),
    "insert_question_option": Statement(
        "INSERT INTO question_option (package_version_id, question_id, option_id, "
        "ordinal, label) VALUES (:v, :question_id, :option_id, :ordinal, :label)"
    ),
    "select_question_options": Statement(
        "SELECT question_id, option_id, ordinal, label FROM question_option "
        "WHERE package_version_id = :v ORDER BY question_id, ordinal"
    ),
    "select_options_by_question": Statement(
        "SELECT option_id, ordinal, label FROM question_option "
        "WHERE package_version_id = :v AND question_id = :question_id ORDER BY ordinal"
    ),
    "select_proposal": Statement(
        "SELECT proposal_id, assessment_doc_id, payload, template_version, model_ref, "
        "attempts, created_at, confirmed_at FROM setup_proposal "
        "WHERE package_version_id = :v"
    ),
    "insert_proposal": Statement(
        "INSERT INTO setup_proposal (package_version_id, proposal_id, "
        "assessment_doc_id, payload, template_version, model_ref, attempts, created_at) "
        "VALUES (:v, :proposal_id, :assessment_doc_id, :payload, :template_version, "
        ":model_ref, :attempts, datetime('now'))"
    ),
    "update_proposal_payload": Statement(
        "UPDATE setup_proposal SET payload = :payload, attempts = :attempts "
        "WHERE package_version_id = :v"
    ),
    "confirm_proposal": Statement(
        "UPDATE setup_proposal SET confirmed_at = :confirmed_at "
        "WHERE package_version_id = :v"
    ),
    # -- rubric read-back (#51): the provenance row and the columns it fills --------------
    "select_readback": Statement(
        "SELECT rubric_doc_id, assessment_doc_id, payload, template_version, "
        "model_ref, attempts, created_at FROM setup_readback "
        "WHERE package_version_id = :v"
    ),
    "insert_readback": Statement(
        "INSERT INTO setup_readback (package_version_id, rubric_doc_id, "
        "assessment_doc_id, payload, template_version, model_ref, attempts, created_at) "
        "VALUES (:v, :rubric_doc_id, :assessment_doc_id, :payload, :template_version, "
        ":model_ref, :attempts, :created_at)"
    ),
    "insert_readback_criterion": Statement(
        "INSERT INTO criterion (package_version_id, criterion_id, question_id, kind, "
        "max_points, scoring_model, construct_tag, band_count, evidence_type, "
        "band_justification) VALUES (:v, :criterion_id, :question_id, :kind, "
        ":max_points, :scoring_model, :construct_tag, :band_count, :evidence_type, "
        ":band_justification)"
    ),
    "pkg_revision_copy_setup_readback": Statement(
        "INSERT INTO setup_readback (package_version_id, rubric_doc_id, "
        "assessment_doc_id, payload, template_version, model_ref, attempts, created_at) "
        "SELECT :new, rubric_doc_id, assessment_doc_id, payload, template_version, "
        "model_ref, attempts, created_at FROM setup_readback WHERE package_version_id = :old"
    ),
    # -- #52: the classification and step-provenance writes ------------------------------
    "insert_classification": Statement(
        "INSERT INTO setup_classification (package_version_id, criterion_id, "
        "classification, decomposition_basis, source, recorded_at) VALUES (:v, "
        ":criterion_id, :classification, :decomposition_basis, :source, :recorded_at) "
        "ON CONFLICT (package_version_id, criterion_id) DO UPDATE SET "
        "classification = excluded.classification, "
        "decomposition_basis = excluded.decomposition_basis, "
        "source = excluded.source, recorded_at = excluded.recorded_at"
    ),
    "select_classifications": Statement(
        "SELECT criterion_id, classification, decomposition_basis, source, "
        "recorded_at FROM setup_classification WHERE package_version_id = :v "
        "ORDER BY criterion_id"
    ),
    "select_classification": Statement(
        "SELECT criterion_id, classification, decomposition_basis, source, "
        "recorded_at FROM setup_classification WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "insert_step_record": Statement(
        "INSERT INTO setup_step_record (package_version_id, step_id, status, payload, "
        "recorded_at) VALUES (:v, :step_id, :status, :payload, :recorded_at) "
        "ON CONFLICT (package_version_id, step_id) DO UPDATE SET "
        "status = excluded.status, payload = excluded.payload, "
        "recorded_at = excluded.recorded_at"
    ),
    "select_step_record": Statement(
        "SELECT step_id, status, payload, recorded_at FROM setup_step_record "
        "WHERE package_version_id = :v AND step_id = :step_id"
    ),
    "select_step_records": Statement(
        "SELECT step_id, status, payload, recorded_at FROM setup_step_record "
        "WHERE package_version_id = :v ORDER BY step_id"
    ),
    "pkg_revision_copy_setup_classification": Statement(
        "INSERT INTO setup_classification (package_version_id, criterion_id, "
        "classification, decomposition_basis, source, recorded_at) "
        "SELECT :new, criterion_id, classification, decomposition_basis, source, "
        "recorded_at FROM setup_classification WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_setup_step_record": Statement(
        "INSERT INTO setup_step_record (package_version_id, step_id, status, payload, "
        "recorded_at) SELECT :new, step_id, status, payload, recorded_at "
        "FROM setup_step_record WHERE package_version_id = :old"
    ),
    "pkg_revision_copied_counts": Statement(
        # #230's observability half: the revision result names what was copied, with
        # per-table row counts — one read over the child's copies rather than one per
        # table. The surface list mirrors `_REVISION_COPY_KEYS`; extend both together.
        "SELECT 'criterion' AS surface, COUNT(*) AS n FROM criterion "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'band', COUNT(*) FROM band "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'question', COUNT(*) FROM question "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'question_option', COUNT(*) FROM question_option "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'criterion_dependency', COUNT(*) FROM criterion_dependency "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'exemplar', COUNT(*) FROM exemplar "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'mcq_option', COUNT(*) FROM mcq_option "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'grade_policy', COUNT(*) FROM grade_policy "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'grade_boundary', COUNT(*) FROM grade_boundary "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'setup_proposal', COUNT(*) FROM setup_proposal "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'setup_readback', COUNT(*) FROM setup_readback "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'setup_classification', COUNT(*) FROM setup_classification "
        "WHERE package_version_id = :v "
        "UNION ALL SELECT 'setup_step_record', COUNT(*) FROM setup_step_record "
        "WHERE package_version_id = :v"
    ),
    # Per-field UPDATE statements: the SET column cannot be a bound parameter, so each
    # lockable field carries its own literal — the registry stays the one place a
    # statement exists, and the guard selects by field name.
    "update_criterion_max_points": Statement(
        "UPDATE criterion SET max_points = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "update_criterion_question_type": Statement(
        "UPDATE criterion SET kind = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "update_criterion_scoring_model": Statement(
        "UPDATE criterion SET scoring_model = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "update_criterion_construct_tag": Statement(
        "UPDATE criterion SET construct_tag = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id"
    ),
    "update_band_label": Statement(
        "UPDATE band SET label = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id AND ordinal = :ordinal"
    ),
    "update_band_ordinal": Statement(
        "UPDATE band SET ordinal = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id AND ordinal = :ordinal"
    ),
    "update_band_descriptor": Statement(
        "UPDATE band SET descriptor = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id AND ordinal = :ordinal"
    ),
    "update_band_points": Statement(
        "UPDATE band SET points = :value WHERE package_version_id = :v "
        "AND criterion_id = :criterion_id AND ordinal = :ordinal"
    ),
})
STATEMENTS.update(PKG_STATEMENTS)
TIER_MIGRATIONS[Tier.PACKAGE] = (
    TIER_MIGRATIONS[Tier.PACKAGE]
    + (_PKG_VERSION_LINEAGE,)
    + (_PKG_SCHEMA_LOCK_COLUMNS,)
    + (_PKG_VALIDATION_KEYS,)
    + (_PKG_GRADE_POLICY_AND_KEYS,)
    + (_PKG_EXPORT_GATE,)
    + (_PKG_QUESTION_INVENTORY,)
    + (_PKG_SETUP_READBACK,)
    + (_PKG_SETUP_CLASSIFICATION,)
)

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
    """A new package version's content, as `M-SETUP`/`M-CALIB` hand it over.

    `criteria` names the judged criteria as bare ids (kind `open`, no bands yet) — the
    shape `create_version` writes. Bands, dependencies, options and keys are declared
    afterwards through their own methods, so a draft grows additively."""

    title: str = ""
    criteria: Sequence[str] = ()


class PackageCatalog:
    """Tier P's data-access layer, over `M-STORE`'s `package(id)` handle.

    Every mutating method funnels through `_refuse_mutation` — the data-layer guard —
    and the database triggers installed by migration 002 backstop the same rule for
    writes that bypass the catalog. The catalog holds one Tier P database (one package
    file), so `catalog = PackageCatalog(store.package(package_id), package_id=package_id)`.
    """

    def __init__(self, handle, *, package_id: str, blobs: Any | None = None) -> None:
        self._handle = handle
        self._package_id = package_id
        # The content-addressed blob store (`store.blobs()`), needed only to carry
        # exemplar-referenced blobs in an export (CT-STORE-07). Optional: a catalog
        # built without one exports text-only packages and refuses a blob-referencing
        # one with a clear error rather than a silent omission.
        self._blobs = blobs
        # The per-run cache (NFR-PKG-05): loaded once against a version, invalidated on
        # publish and on any edit. ~23,000 unit reads per run must not re-query SQLite.
        self._cache: dict | None = None
        self._cache_version: str | None = None

    @property
    def package_id(self) -> str:
        """The package's identity as the catalog knows it — the name `M-INGEST`'s V4
        identifier signal compares a submission's printed 'Assessment:' line against
        (`FR-INGEST-25`). `PackageDraft.title` is not persisted in this schema, so the
        id is the declared identity until `M-SETUP` carries a human-readable one."""
        return self._package_id

    def _guard(self, tx, v: PackageVersionId, field: str) -> None:
        """The one lock check every mutation funnels through.

        A published version refuses EVERY in-place edit; a locked-field edit is named
        specifically (`SchemaLockViolation`), everything else as
        `PublishedVersionImmutableError` — the two errors' distinct meanings, in one
        place. Drafts (locked = 0) edit freely: the copy-on-revision flow exists to give
        clarifications a vehicle, not to forbid authoring."""
        row = tx.execute(PKG_STATEMENTS["select_version"], v=v)[0]
        if not row["locked"]:
            return
        if field in {f"{table}.{name}" for table, name in SCHEMA_LOCK_FIELDS}:
            SCHEMA_LOCK_VIOLATIONS.increment()
            LOGGER.warning(
                "schema lock violation: the %r edit on package version %r is refused "
                "(FR-PKG-03) — a rising rate means a caller is attempting something "
                "the design forbids", field, v,
            )
            raise SchemaLockViolation(
                f"the {field!r} edit on package version {v!r} is refused by the §6.2 "
                f"schema lock (FR-PKG-03): changing what is measured invalidates every "
                f"accumulated validation record. The sanctioned vehicle is a new version "
                f"(create_version(parent={v!r}))."
            )
        raise PublishedVersionImmutableError(
            f"package version {v!r} is published (locked = 1) and immutable (FR-PKG-01)."
        )

    def add_criterion(self, v: PackageVersionId, criterion_id: str) -> None:
        """Add a criterion in place — refused on published versions (`TC-PKG-03` case 2);
        the sanctioned vehicle is a revision (`FR-PKG-04`)."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.add")

    def remove_criterion(self, v: PackageVersionId, criterion_id: str) -> None:
        """Remove a criterion in place — refused on published versions (case 3)."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.remove")

    def set_dependencies(
        self, v: PackageVersionId, edges: Sequence[tuple[str, str]]
    ) -> None:
        """Declare the version's dependency edges in one write (`FR-PKG-05`): each edge
        is (before, after) — `after` depends on `before`, i.e. `before` is extracted
        first. Replaces the version's edge set; a cycle raises
        `CyclicDependencyError` INSIDE the transaction, so the write rolls back and the
        refusal is a no-op (`CT-PKG-11`) — a published version whose graph cannot be
        ordered must never exist, not merely fail later at read time."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion_dependency.alter")
            tx.execute(PKG_STATEMENTS["delete_dependencies"], v=v)
            for before, after in edges:
                if before == after:
                    # The self-edge is refused HERE, with the graph error, before the
                    # INSERT: the DDL's CHECK (criterion_id <> depends_on) would refuse
                    # the raw write, but FR-PKG-05 promises the caller
                    # CyclicDependencyError, and a caller branching on the exact type
                    # would otherwise see sqlite3.IntegrityError for this one cell.
                    raise CyclicDependencyError(
                        f"the dependency edge ({before!r}, {after!r}) is a self-edge "
                        f"(FR-PKG-05): a criterion cannot depend on itself. The "
                        "database's CHECK (criterion_id <> depends_on) backstops the "
                        "same rule for writes that route around the catalog."
                    )
                tx.execute(PKG_STATEMENTS["insert_dependency"],
                           v=v, criterion_id=after, depends_on=before)
            graph = {row["criterion_id"]: set() for row in tx.execute(
                PKG_STATEMENTS["select_criteria"], v=v)}
            for row in tx.execute(PKG_STATEMENTS["select_dependencies"], v=v):
                graph.setdefault(row["criterion_id"], set()).add(row["depends_on"])
                graph.setdefault(row["depends_on"], set())
            self._assert_acyclic(graph)
        self._invalidate()

    def update_criterion_dependency(self, v: PackageVersionId) -> None:
        """Add/remove/alter a dependency row in place — refused on published versions
        (cases 11-13). The row-level shape is #28's; the lock fires here first."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion_dependency.alter")

    # -- validation records and the manifest (#29) ----------------------------------------------

    def store_validation(
        self, v: PackageVersionId, criterion_id: str, population_scope_id: str,
        backend_profile: str, panel_build_ref: str, scoring_model: str,
        agreement: float, n: int,
    ) -> None:
        """Store one validation record, keyed by the six-part key `FR-PKG-08` fixes.
        Refused on published versions only if the record would CHANGE an existing row
        (validation records are append-only in practice: new keys, never rewrites)."""
        with self._handle.transaction() as tx:
            row = tx.execute(PKG_STATEMENTS["select_validation"],
                             v=v, criterion_id=criterion_id,
                             population_scope_id=population_scope_id,
                             backend_profile=backend_profile,
                             panel_build_ref=panel_build_ref,
                             scoring_model=scoring_model)
            if row:
                self._guard(tx, v, "validation_record.alter")
            tx.execute(PKG_STATEMENTS["insert_validation"],
                       v=v, criterion_id=criterion_id,
                       population_scope_id=population_scope_id,
                       backend_profile=backend_profile,
                       panel_build_ref=panel_build_ref,
                       scoring_model=scoring_model, agreement=agreement, n=n)
        self._invalidate()

    def validation_for(
        self, v: PackageVersionId, population_scope_id: str, backend_profile: str,
        panel_build_ref: str, scoring_model: str = "", criterion_id: str | None = None,
    ) -> Any:
        """`FR-PKG-09`: the record for one key, or `NoValidationData` — **distinguishable
        in type** from a zero or a low figure. No aggregate exists anywhere on this
        surface (`CT-PKG-07`): the caller names the key, the catalog answers the key."""
        rows = self._handle.query(PKG_STATEMENTS["select_validation"],
                                  v=v, criterion_id=criterion_id,
                                  population_scope_id=population_scope_id,
                                  backend_profile=backend_profile,
                                  panel_build_ref=panel_build_ref,
                                  scoring_model=scoring_model)
        if not rows:
            return NoValidationData()
        return dict(rows[0])

    def manifest(self, v: PackageVersionId) -> Manifest:
        """`FR-PKG-21`: per-population validation entries, the weakest criterion per
        population, exemplar provenance and schema version — and no cross-population
        aggregate field (the shape makes the §2.1 error unrepresentable)."""
        rows = self._handle.query(PKG_STATEMENTS["select_all_validations"], v=v)
        entries = _weakest_entry([
            ManifestEntry(
                population_scope_id=row["population_scope_id"],
                criterion_id=row["criterion_id"],
                backend_profile=row["backend_profile"],
                panel_build_ref=row["panel_build_ref"],
                scoring_model=row["scoring_model"],
                agreement=float(row["agreement"]),
                n=int(row["n"]),
                is_weakest=False,
            ) for row in rows
        ])
        provenance = tuple(
            row["provenance"] for row in self._handle.query(
                PKG_STATEMENTS["select_exemplar_provenance"], v=v)
        )
        return Manifest(
            package_version_id=v,
            schema_version=self._handle._open_report.schema_version_after,
            entries=tuple(entries),
            exemplar_provenance=provenance,
        )

    # -- structure, graph and the per-run cache (#28) ------------------------------------------

    def add_criterion(
        self, v: PackageVersionId, criterion_id: str, *, question_id: str = "",
        kind: str = "open", max_points: float = 0.0, scoring_model: str = "atomic",
        construct_tag: str = "", dependencies: Sequence[str] = (),
        band_count: int | None = None, evidence_type: str | None = None,
    ) -> None:
        """Add a criterion with its dependency edges, refusing a cycle (`FR-PKG-05`) —
        the guard's add-refusal applies to published versions; drafts add freely. The
        content arguments default so a published version's refusal fires before any
        content is needed (TC-PKG-03 row 2 passes only the id).

        `evidence_type` (`FR-SETUP-09`, #232) declares what kind of textual evidence
        satisfies a JUDGED criterion — the declaration M-INTEG routes on
        (`FR-INTEG-03`). The read back attaches it for every criterion it commits;
        a criterion entered through THIS surface (the degraded read back routes the
        teacher here) carries the declaration from its write or stays NULL — and
        M-SETUP's publish gate refuses a draft holding a judged criterion without
        one. `mcq` criteria are keyed, not judged, and legitimately carry NULL.

        `band_count` is the DECLARED band-set size (`FR-PKG-06`): odd or outside 2..6
        fails at the declare — a set that can never satisfy the even-count rule should
        not exist even as a draft. `add_band` refuses past the declared count."""
        if band_count is not None and (band_count < 2 or band_count > 6
                                       or band_count % 2 != 0):
            raise BandSetError(
                f"a band_count of {band_count} is odd or outside 2..6 (FR-PKG-06). The "
                "even count removes the safe middle band a hesitant judge retreats to "
                "(design §5.10, R40) — declared at the criterion, not discovered after "
                "the bands are written."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.add")
            tx.execute(PKG_STATEMENTS["insert_criterion"],
                       v=v, criterion_id=criterion_id, question_id=question_id,
                       kind=kind, max_points=max_points, scoring_model=scoring_model,
                       construct_tag=construct_tag, band_count=band_count,
                       evidence_type=evidence_type)
            for depends_on in dependencies:
                if depends_on == criterion_id:
                    # Same self-edge refusal as set_dependencies: the graph error the
                    # design promises, raised before the DDL's CHECK can answer with a
                    # bare IntegrityError (FR-PKG-05).
                    raise CyclicDependencyError(
                        f"criterion {criterion_id!r} cannot depend on itself "
                        f"(FR-PKG-05). The database's CHECK (criterion_id <> "
                        "depends_on) backstops the same rule for raw writes."
                    )
                tx.execute(PKG_STATEMENTS["insert_dependency"],
                           v=v, criterion_id=criterion_id, depends_on=depends_on)
            graph = {row["criterion_id"]: set() for row in tx.execute(
                PKG_STATEMENTS["select_criteria"], v=v)}
            for row in tx.execute(PKG_STATEMENTS["select_dependencies"], v=v):
                graph.setdefault(row["criterion_id"], set()).add(row["depends_on"])
                graph.setdefault(row["depends_on"], set())
            self._assert_acyclic(graph)
        self._invalidate()

    def add_band(
        self, v: PackageVersionId, criterion_id: str, ordinal: int,
        band: str, points: float, descriptor: str = "",
    ) -> None:
        """Add one band, enforcing the structural rules on the whole set (`FR-PKG-06`).

        The validation runs INSIDE the transaction, so a refused band is a no-op
        (`CT-PKG-11`): the whole-set rules (contiguity, monotone points, the declared
        count) can only be checked after the row is inserted, and checking after the
        commit would leave the invalid set on disk behind the raised error. The set is
        read version-scoped — a criterion id is shared with every revision that copied
        it, and the parent's bands are not this version's set."""
        declared = self._band_count(v, criterion_id)
        with self._handle.transaction() as tx:
            self._guard(tx, v, "band.add-unpublished")
            if declared is not None and ordinal >= declared:
                raise BandSetError(
                    f"band ordinal {ordinal} exceeds the criterion's declared "
                    f"band_count of {declared} (FR-PKG-06)."
                )
            existing = [row for row in tx.execute(
                PKG_STATEMENTS["select_bands"], v=v)
                if row["criterion_id"] == criterion_id]
            if any(row["ordinal"] == ordinal for row in existing):
                # Refused here, with the structural error, before the INSERT: the
                # ordinal is half of the primary key, so the database would refuse the
                # duplicate anyway — but with a bare IntegrityError, not the
                # BandSetError the band rules' error taxonomy promises.
                raise BandSetError(
                    f"criterion {criterion_id!r} already declares band ordinal "
                    f"{ordinal} (FR-PKG-06): ordinals are contiguous from 0, so a "
                    "duplicate is a gap wearing another ordinal's name."
                )
            tx.execute(PKG_STATEMENTS["insert_band"],
                       v=v, criterion_id=criterion_id, ordinal=ordinal,
                       band=band, points=points, descriptor=descriptor)
            rows = [row for row in tx.execute(PKG_STATEMENTS["select_bands"], v=v)
                    if row["criterion_id"] == criterion_id]
            self._validate_band_order(rows)
            if declared is not None and len(rows) == declared:
                self._validate_band_count(len(rows))
        self._invalidate()

    def add_exemplar(
        self, v: PackageVersionId, exemplar_id: str, criterion_id: str, band: str,
        provenance: str = "synthetic", blob_hash: str | None = None,
    ) -> None:
        """Add an exemplar, refusing a band that does not name a band declared for the
        criterion (`FR-PKG-07`).

        `provenance` is ADR-4's closed vocabulary (synthetic | paraphrased |
        real_verbatim); anything else — including the superseded `real_consented` — is
        refused, because two names for one state is the drift the gate exists to
        prevent. `blob_hash` references the content-addressed blob carrying the
        exemplar's material (CT-STORE-07). The `contains_real_student_text` flag is
        DERIVED (`ADR-4`): the same transaction refreshes it from the rows, so flag and
        exemplars cannot disagree (TC-PKG-24's invariant)."""
        if provenance not in PROVENANCE_VOCABULARY:
            raise PackageError(
                f"exemplar provenance {provenance!r} is not in the vocabulary "
                f"{PROVENANCE_VOCABULARY} (ADR-4). 'real_consented' is the superseded "
                "name for 'real_verbatim' — the canonical value is the only one the "
                "export gate tests."
            )
        declared = {row["band"] for row in self._handle.query(
            PKG_STATEMENTS["select_bands"], v=v)
            if row["criterion_id"] == criterion_id}
        if band not in declared:
            raise BandSetError(
                f"exemplar names band {band!r}, which criterion {criterion_id!r} does "
                f"not declare (declared: {sorted(declared)}). An exemplar anchored to an "
                "undeclared band would train judges toward a level the scoring pipeline "
                "cannot produce."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "exemplar.add-unpublished")
            tx.execute(PKG_STATEMENTS["insert_exemplar"],
                       v=v, exemplar_id=exemplar_id, criterion_id=criterion_id,
                       band=band, provenance=provenance, blob_hash=blob_hash)
            tx.execute(PKG_STATEMENTS["refresh_package_flag"], p=self._package_id)
        self._invalidate()

    def set_exemplar_provenance(
        self, v: PackageVersionId, exemplar_id: str, provenance: str
    ) -> None:
        """Record the paraphrase-and-approval outcome on a draft exemplar
        (`FR-PKG-11`'s remediation half): 'real_verbatim' → 'paraphrased' clears the
        gate once every such row is through it. Drafts only — a published version's
        exemplars are history (the sanctioned vehicle is a revision)."""
        if provenance not in PROVENANCE_VOCABULARY:
            raise PackageError(
                f"exemplar provenance {provenance!r} is not in the vocabulary "
                f"{PROVENANCE_VOCABULARY} (ADR-4)."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "exemplar.provenance")
            if not tx.execute(PKG_STATEMENTS["select_exemplar_by_id"], v=v,
                              exemplar_id=exemplar_id):
                raise PackageError(
                    f"exemplar {exemplar_id!r} does not exist in version {v!r}."
                )
            tx.execute(PKG_STATEMENTS["update_exemplar_provenance"],
                       v=v, exemplar_id=exemplar_id, value=provenance)
            tx.execute(PKG_STATEMENTS["refresh_package_flag"], p=self._package_id)
        self._invalidate()

    def remove_exemplar(self, v: PackageVersionId, exemplar_id: str) -> None:
        """Drop a draft exemplar (`FR-PKG-11`'s other remediation half); the derived
        flag refreshes in the same transaction. Drafts only, like every content
        edit."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "exemplar.remove")
            if not tx.execute(PKG_STATEMENTS["select_exemplar_by_id"], v=v,
                              exemplar_id=exemplar_id):
                raise PackageError(
                    f"exemplar {exemplar_id!r} does not exist in version {v!r}."
                )
            tx.execute(PKG_STATEMENTS["delete_exemplar"], v=v,
                       exemplar_id=exemplar_id)
            tx.execute(PKG_STATEMENTS["refresh_package_flag"], p=self._package_id)
        self._invalidate()

    def exemplars(self, v: PackageVersionId) -> tuple[dict, ...]:
        """The version's exemplar rows, ordered by exemplar id (`#53`): the read
        the prefix budget's per-pair assembly consumes (`FR-SETUP-11` — a
        (question, criterion) prefix includes its exemplars' material)."""
        return tuple(
            dict(row) for row in
            self._handle.query(PKG_STATEMENTS["select_exemplars"], v=v)
        )

    def blob_text(self, blob_hash: str | None) -> str:
        """One blob's content as text, by hash — the exemplar material a judge
        prompt would carry, which the prefix budget counts (`#53`, `FR-SETUP-11`).

        None (a text-only exemplar) answers the empty string. A hash with NO blob
        store attached to this catalog refuses: silently under-counting the
        prefix is the opposite of the check's purpose. Missing content answers
        the empty string — a dangling hash is a storage inconsistency the budget
        report cannot fix, and the exemplar's absence of material is the honest
        count."""
        if blob_hash is None:
            return ""
        if self._blobs is None:
            raise PackageError(
                f"exemplar blob {blob_hash!r} cannot be read: this catalog was "
                "opened without a blob store, so the prefix budget would "
                "under-count the assembled prompt (FR-SETUP-11). Reopen the "
                "catalog with blobs=store.blobs()."
            )
        data = self._blobs.get(blob_hash)
        if not data:
            return ""
        return data.decode("utf-8", errors="replace")

    def topological_order(self, v: PackageVersionId) -> tuple[str, ...]:
        """A valid topological order over the version's dependency graph — dependencies
        before dependents, which is `M-ORCH`'s extraction sweep order (`FR-PKG-05`)."""
        return self._toposort(self._version_graph(v))

    def dependency_graph(self, v: PackageVersionId) -> dict[str, tuple[str, ...]]:
        """The version's dependency topology, criterion -> its direct dependencies
        (`FR-PKG-05`) — the read side of `set_dependencies`, over the same graph
        `topological_order` sorts. `M-ORCH` consumes the topology rather than
        re-deriving it: the extraction sweep's order is `topological_order`'s, and the
        scoring gate (`FR-ORCH-06`) needs the edges themselves. Every criterion of the
        version appears as a key, dependencies sorted — deterministic where nothing
        depends on the order."""
        graph = self._version_graph(v)
        return {
            criterion_id: tuple(sorted(deps))
            for criterion_id, deps in graph.items()
        }

    def criteria(self, v: PackageVersionId, question_id: str | None = None) -> tuple:
        """The version's criteria, from the per-run cache (`NFR-PKG-05`: read on every
        one of ~23,000 units)."""
        cached = self._cache_get(v)
        if question_id is None:
            return cached["criteria"]
        return tuple(c for c in cached["criteria"] if c["question_id"] == question_id)

    def bands(self, criterion_id: str) -> tuple:
        """The criterion's bands, ordered by ordinal, from the per-run cache."""
        cached = self._cache_current()
        return cached["bands"].get(criterion_id, ())

    def points_for_band(self, criterion_id: str, band: str) -> float:
        """The band→points mapping, monotone in ordinal (`FR-PKG-06`'s guarantee).

        The per-criterion face of the module-level `points_for_band` — the single
        canonical mapping (`CT-PKG-05`): one definition, in M-PKG, and every
        consumer (`M-AGG`'s post-aggregation mapping at #91 included) routes
        through it (`NFR-AGG-02`)."""
        try:
            return points_for_band(self.bands(criterion_id), band)
        except PackageError as error:
            raise PackageError(
                f"criterion {criterion_id!r} declares no band {band!r}."
            ) from error

    def _cache_get(self, v: PackageVersionId) -> dict:
        if self._cache_version != v or self._cache is None:
            self._cache = self._load_version(v)
            self._cache_version = v
        return self._cache

    def _cache_current(self) -> dict:
        """The cache, loaded against the file's latest version when no version has been
        read yet — `bands(criterion_id)` carries no version argument by contract
        (`CT-PROV`'s sibling shape: bands belong to the file's current version)."""
        if self._cache is None:
            rows = self._handle.query(PKG_STATEMENTS["select_latest_version"])
            if not rows:
                raise PackageError(
                    "this Tier P database holds no package_version — the cache has "
                    "nothing to load."
                )
            self._cache_get(rows[0]["package_version_id"])
        return self._cache

    def _invalidate(self) -> None:
        """Invalidation on publish and on any edit: the cache must not become a second
        source of truth (design §3.4, #28's own acceptance criterion)."""
        self._cache = None
        self._cache_version = None

    def _load_version(self, v: PackageVersionId) -> dict:
        criteria = []
        for r in self._handle.query(PKG_STATEMENTS["select_criteria"], v=v):
            row = dict(r)
            try:
                row["answer_key"] = (
                    tuple(json.loads(row["answer_key"])) if row["answer_key"] else ()
                )
            except (TypeError, ValueError) as error:
                # A malformed key must not poison the per-run cache loader with a raw
                # JSONDecodeError — CT-PKG-11: caller errors are this module's own.
                raise PackageError(
                    f"version {v!r} holds a malformed answer key for criterion "
                    f"{row['criterion_id']!r}: {error}"
                ) from error
            criteria.append(row)
        bands_by_criterion: dict[str, tuple] = {}
        for row in self._handle.query(PKG_STATEMENTS["select_bands"], v=v):
            bands_by_criterion.setdefault(row["criterion_id"], []).append(dict(row))
        bands = {c: tuple(rows) for c, rows in bands_by_criterion.items()}
        return {"criteria": tuple(criteria), "bands": bands}

    def _read_bands(self, criterion_id: str) -> list:
        """Bands read straight from the database — the validators and the exemplar guard
        run against the truth, not against the cache."""
        return self._handle.query(PKG_STATEMENTS["select_bands_by_criterion"],
                                  criterion_id=criterion_id)

    def _version_graph(self, v: PackageVersionId) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = {
            row["criterion_id"]: set()
            for row in self._handle.query(PKG_STATEMENTS["select_criteria"], v=v)
        }
        for row in self._handle.query(PKG_STATEMENTS["select_dependencies"], v=v):
            graph.setdefault(row["criterion_id"], set()).add(row["depends_on"])
            graph.setdefault(row["depends_on"], set())
        return graph

    def _assert_acyclic(self, graph: dict[str, set[str]]) -> None:
        """Kahn's algorithm: a DAG consumes every node; whatever remains is the cycle
        (`FR-PKG-05`)."""
        remaining = {node: set(edges) for node, edges in graph.items()}
        consumed: set[str] = set()
        while remaining:
            ready = [node for node, edges in remaining.items() if edges <= consumed]
            if not ready:
                cycle = sorted(next(iter(remaining.values())) | set(remaining))
                raise CyclicDependencyError(
                    f"the dependency graph is cyclic among {cycle}. The extraction "
                    "sweep's two-pass order (FR-PKG-05) rests on the graph being a DAG."
                )
            for node in ready:
                consumed.add(node)
                del remaining[node]

    def _toposort(self, graph: dict[str, set[str]]) -> tuple[str, ...]:
        """Kahn's algorithm, deterministic: ready nodes emit in sorted order so the
        extraction sweep's order is reproducible."""
        remaining = {node: set(edges) for node, edges in graph.items()}
        consumed: set[str] = set()
        order: list[str] = []
        while remaining:
            ready = sorted(node for node, edges in remaining.items()
                           if edges <= consumed)
            if not ready:
                raise CyclicDependencyError(
                    f"the dependency graph is cyclic among {sorted(remaining)}."
                )
            for node in ready:
                order.append(node)
                consumed.add(node)
                del remaining[node]
        return tuple(order)

    def _band_count(self, v: PackageVersionId, criterion_id: str) -> int | None:
        for row in self._handle.query(PKG_STATEMENTS["select_criteria"], v=v):
            if row["criterion_id"] == criterion_id:
                return row["band_count"]
        return None

    def _validate_band_order(self, rows) -> None:
        """`FR-PKG-06`'s order half: ordinals contiguous from 0, points non-decreasing
        in ordinal — the monotone mapping M-AGG and M-GRADE assume."""
        ordinals = sorted(row["ordinal"] for row in rows)
        points = [float(row["points"]) for row in sorted(rows, key=lambda r: r["ordinal"])]
        if ordinals != list(range(len(ordinals))):
            raise BandSetError(
                f"the band ordinals {ordinals} are not contiguous from 0 (FR-PKG-06). "
                "Gaps would leave an unreachable band in the middle of the mapping."
            )
        if any(later < earlier for earlier, later in zip(points, points[1:])):
            raise BandSetError(
                f"the band points {points} are not non-decreasing in ordinal (FR-PKG-06). "
                "M-AGG and M-GRADE assume the monotone band-to-points mapping."
            )

    def _validate_band_count(self, count: int) -> None:
        """`FR-PKG-06`'s count half: even, within 2..6 — the even count removes the safe
        middle band a hesitant judge retreats to (design §5.10, R40)."""
        if count < 2 or count > 6 or count % 2 != 0:
            raise BandSetError(
                f"a band set of {count} bands is outside 2..6 or odd (FR-PKG-06). The "
                "even count removes the safe middle band a hesitant judge retreats to."
            )

    def _validate_band_sets(self, rows_of, *, boundary: str) -> None:
        """`FR-PKG-06`'s count half over ONE version's rows: every declared
        `band_count` fully populated and even/2..6. `rows_of` resolves a statement name
        to that version's rows — through the handle at the publish boundary, through
        the open transaction at the revision copy (#230) — so what is validated is
        exactly that version's own rows, never another revision's copied ids.

        At the copy the failure refuses the revision: a parent whose declared band set
        was never completed would otherwise ship the half set as the child's
        inheritance — a half-copied child is mutation by omission (`CT-PKG-02`)."""
        populated: dict[str, int] = {}
        for row in rows_of("select_bands"):
            populated[row["criterion_id"]] = populated.get(row["criterion_id"], 0) + 1
        for row in rows_of("select_criteria"):
            declared = row["band_count"]
            if declared is not None:
                count = populated.get(row["criterion_id"], 0)
                if count != declared:
                    raise BandSetError(
                        f"criterion {row['criterion_id']!r} declares a band_count of "
                        f"{declared} but carries {count} band(s) (FR-PKG-06): a "
                        f"partially populated band set must not be {boundary} — the "
                        "judge would see fewer bands than the declared mapping."
                    )
                self._validate_band_count(count)

    def update_criterion_field(
        self, v: PackageVersionId, criterion_id: str, field: str, value: Any
    ) -> None:
        """Set one criterion column — the guarded mutation surface `M-CALIB` writes
        through (`FR-CALIB-07`). Refuses locked fields on published versions with
        `SchemaLockViolation` naming the field; permits everything on drafts.

        `answer_key` is refused here regardless of lock state: the key has exactly one
        write door, `set_answer_key` (ADR-1's single canonical representation) — this
        generic path stores the raw value, and an unvalidated one would poison every
        later read of the version."""
        if field == "answer_key":
            raise PackageError(
                "answer_key is written through set_answer_key (FR-PKG-17, ADR-1) — "
                "the canonical setter validates and serializes the key; this generic "
                "field path would store it raw."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, f"criterion.{field}")
            tx.execute(
                PKG_STATEMENTS[f"update_criterion_{field}"],
                v=v, criterion_id=criterion_id, value=value,
            )
        self._invalidate()

    def update_band_field(
        self, v: PackageVersionId, criterion_id: str, ordinal: int,
        field: str, value: Any,
    ) -> None:
        """Set one band column, under the same guard (`TC-PKG-03` cases 7-10)."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, f"band.{field}")
            tx.execute(
                PKG_STATEMENTS[f"update_band_{field}"],
                v=v, criterion_id=criterion_id, ordinal=ordinal, value=value,
            )
        self._invalidate()

    # -- grade policy, boundaries, answer keys, elicitation history (#30) --------------------

    def set_grade_policy(self, v: PackageVersionId, policy: GradePolicy) -> None:
        """Store the executed policy (`FR-PKG-14`). Only a `GradePolicy` instance is
        accepted — a string (a free-text formula, an executable expression, a
        lambda-shaped string) is refused HERE rather than stored and interpreted later,
        because an executable formula in a package is an arbitrary-code surface and an
        un-auditable grade. `plain_language` needs no storage: it is generated from the
        object on read (`FR-PKG-15`)."""
        if not isinstance(policy, GradePolicy):
            raise GradePolicyError(
                f"the grade policy must be a GradePolicy object drawn from the closed "
                f"rule vocabulary (FR-PKG-14); got {type(policy).__name__}. A "
                "free-text formula or an executable expression is refused — it is an "
                "arbitrary-code surface and an un-auditable grade."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "grade_policy.set")
            tx.execute(PKG_STATEMENTS["delete_policy"], v=v)
            tx.execute(PKG_STATEMENTS["insert_policy"], v=v,
                       policy=json.dumps(policy.to_dict(), sort_keys=True),
                       review_window_hours=policy.review_window_hours)
        self._invalidate()

    def grade_policy(self, v: PackageVersionId) -> GradePolicy:
        """The executed policy as a structured object (`FR-PKG-14`): parsed from the
        stored JSON and RE-VALIDATED against the closed vocabulary, so a hand-edited row
        holding a formula refuses on read too. `review_window_hours` comes from its
        column (ADR-3) — null means finalize on run completion (`FR-PKG-19`), never wait
        indefinitely. A version with no stored policy answers the default
        (`FR-SETUP-12`) — M-GRADE always finds a policy and never has to invent one."""
        rows = self._handle.query(PKG_STATEMENTS["select_policy"], v=v)
        if not rows:
            return default_grade_policy()
        try:
            data = json.loads(rows[0]["policy"])
        except (TypeError, ValueError) as error:
            # A row that is not even JSON — a formula stored by hand — is exactly the
            # FR-PKG-14 refusal, not a raw JSONDecodeError from the read path.
            raise GradePolicyError(
                f"the stored grade policy for version {v!r} is not a structured "
                f"object from the closed rule vocabulary (FR-PKG-14): {error}"
            ) from error
        data["review_window_hours"] = rows[0]["review_window_hours"]
        return GradePolicy.from_dict(data)

    def grade_policy_declared(self, v: PackageVersionId) -> bool:
        """Whether a grade-policy ROW is stored for the version (`#53`): the
        distinction `grade_policy()` cannot make, since it answers the default
        when no row exists — `FR-SETUP-12`'s recording obligation needs to know
        whether the default was ever written down."""
        return bool(self._handle.query(PKG_STATEMENTS["select_policy"], v=v))

    def set_boundaries(
        self, v: PackageVersionId, boundaries: Sequence[tuple[str, float]]
    ) -> None:
        """Declare the version's grade boundary table (`FR-PKG-16`) — the SINGLE
        canonical representation of the grade resolution rule; the policy object carries
        no copy of it. Each pair is (grade, scaled_floor). Floors are INCLUSIVE:
        `boundary_for` resolves a scaled score to the grade with the greatest floor
        <= the score. An empty sequence clears the table (a draft's no-boundary-table
        state); CT-PKG-10's null-equivalent is the ABSENCE of rows, and callers handle
        that rather than inventing boundaries."""
        grades = [grade for grade, _ in boundaries]
        floors = [float(floor) for _, floor in boundaries]
        if any(not grade for grade in grades):
            raise GradePolicyError(
                "a boundary table names each grade (FR-PKG-16) — an empty label "
                "resolves to nothing."
            )
        if len(set(grades)) != len(grades):
            raise GradePolicyError(
                f"duplicate grade labels {grades} — one label, one cut "
                "(FR-PKG-16's single canonical representation)."
            )
        if any(not math.isfinite(floor) for floor in floors):
            raise GradePolicyError(
                "boundary floors are finite scaled scores (FR-PKG-16)."
            )
        if len(set(floors)) != len(floors):
            raise GradePolicyError(
                f"duplicate scaled floors {floors} — two grades sharing one cut is "
                "an ambiguous resolution (FR-PKG-16)."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "grade_boundary.set")
            tx.execute(PKG_STATEMENTS["delete_boundaries"], v=v)
            for grade, floor in boundaries:
                tx.execute(PKG_STATEMENTS["insert_boundary"], v=v,
                           grade=grade, scaled_floor=float(floor))
        self._invalidate()

    def boundary_for(self, v: PackageVersionId, scaled_score: float) -> str | None:
        """`FR-PKG-16`/`CT-PKG-10`: the grade for a scaled score — a PURE lookup over
        `grade_boundary`, the single canonical representation. Floors are INCLUSIVE
        (the declared rule): the grade with the greatest floor <= the score. A score
        below the lowest floor has no grade, and a version with NO boundary table
        answers None — never an invented boundary."""
        resolved: str | None = None
        for row in self._handle.query(PKG_STATEMENTS["select_boundaries"], v=v):
            if float(row["scaled_floor"]) <= scaled_score:
                resolved = row["grade"]
            else:
                break
        return resolved

    def distance_to_nearest_boundary(
        self, v: PackageVersionId, scaled_score: float
    ) -> float | None:
        """`FR-PKG-16`: how far a scaled score sits from the nearest cut — M-REVIEW's
        boundary-proximity ranking signal. Exactly 0.0 ON a cut. None where the version
        declares no boundary table (`CT-PKG-10`) — the caller handles it; no invented
        distance."""
        rows = self._handle.query(PKG_STATEMENTS["select_boundaries"], v=v)
        if not rows:
            return None
        return min(abs(float(row["scaled_floor"]) - scaled_score) for row in rows)

    def set_answer_key(
        self, v: PackageVersionId, criterion_id: str, key: Sequence[str]
    ) -> None:
        """Declare the multiple-choice key (`FR-PKG-17`, ADR-1):
        `criterion.answer_key` is the SINGLE canonical representation — `mcq_option`
        carries no correctness column, so a corrected key cannot leave two disagreeing
        sources. The key is the sequence of acceptable option ids (one for
        single-select, several for multi-select). Refused on a published version: a key
        CORRECTION is a new version (`FR-PKG-18`) — create_version(parent, ...) copies
        the prior key into the child, the correction lands there, and
        `audit_record.answer_key_ref` resolves to exactly the key that produced a given
        grade."""
        ids = [str(option) for option in key]
        if not ids or any(not option for option in ids):
            raise PackageError(
                "an answer key is a non-empty sequence of option ids (FR-PKG-17); an "
                "empty or blank key would grade every submission wrong identically."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.answer_key")
            if criterion_id not in {row["criterion_id"] for row in tx.execute(
                    PKG_STATEMENTS["select_criteria"], v=v)}:
                raise PackageError(
                    f"criterion {criterion_id!r} does not exist in version {v!r}."
                )
            tx.execute(PKG_STATEMENTS["update_criterion_answer_key"],
                       v=v, criterion_id=criterion_id, value=json.dumps(ids))
        self._invalidate()

    def answer_key(self, criterion_id: str) -> tuple[str, ...]:
        """`FR-PKG-17`/`CT-PKG-08`: the criterion's key, from the version currently at
        the top of the lineage — the one a grade produced NOW pins by
        `answer_key_ref`. A prior version's key stays exactly where it was (read it
        version-pinned via `criteria(parent_v)`), which is what makes `FR-PKG-18`'s
        resolution exact. No key declared yet answers the empty tuple."""
        rows = self._handle.query(PKG_STATEMENTS["select_answer_key_latest"],
                                  criterion_id=criterion_id)
        if not rows or rows[0]["answer_key"] is None:
            return ()
        try:
            return tuple(json.loads(rows[0]["answer_key"]))
        except (TypeError, ValueError) as error:
            raise PackageError(
                f"criterion {criterion_id!r} holds a malformed answer key: {error}"
            ) from error

    def set_mcq_options(
        self, v: PackageVersionId, criterion_id: str,
        options: Sequence[tuple[str, str]],
    ) -> None:
        """Declare the criterion's options as (option_id, label) pairs (`FR-PKG-17`).
        Deliberately NO correctness column exists on `mcq_option` (ADR-1): the key
        lives once, on `criterion.answer_key`. Drafts only — the triggers refuse
        published versions."""
        ids = [option_id for option_id, _ in options]
        if any(not option_id for option_id in ids):
            raise PackageError("an mcq option carries a non-empty option_id.")
        if len(set(ids)) != len(ids):
            raise PackageError(f"duplicate option ids {ids} — options are distinct.")
        with self._handle.transaction() as tx:
            self._guard(tx, v, "mcq_option.set")
            if criterion_id not in {row["criterion_id"] for row in tx.execute(
                    PKG_STATEMENTS["select_criteria"], v=v)}:
                raise PackageError(
                    f"criterion {criterion_id!r} does not exist in version {v!r}."
                )
            tx.execute(PKG_STATEMENTS["delete_mcq_options"], v=v,
                       criterion_id=criterion_id)
            for option_id, label in options:
                tx.execute(PKG_STATEMENTS["insert_mcq_option"], v=v,
                           criterion_id=criterion_id, option_id=option_id,
                           label=label)
        self._invalidate()

    def mcq_options(self, v: PackageVersionId, criterion_id: str) -> tuple:
        """The criterion's declared options, as (option_id, label) pairs — the display
        half of `FR-PKG-17`. Correctness is NOT here (ADR-1): read the key."""
        rows = self._handle.query(PKG_STATEMENTS["select_mcq_options"], v=v,
                                  criterion_id=criterion_id)
        return tuple((row["option_id"], row["label"]) for row in rows)

    def append_elicitation(
        self, v: PackageVersionId, question: str, options_offered: Sequence[str],
        answer_given: str, resulting_edit: str = "",
    ) -> str:
        """Append one calibration-history row (`FR-PKG-20`, `FR-CALIB-14`): the question
        asked, the options offered, the teacher's answer, the resulting edit. Appends
        are allowed on PUBLISHED versions — the trail records conversations about the
        rubric as it stands. The table is append-only in practice, not by convention:
        migration 005 installs unconditional BEFORE UPDATE / BEFORE DELETE triggers,
        and this surface offers no update or delete at all."""
        elicitation_id = uuid.uuid4().hex
        with self._handle.transaction() as tx:
            tx.execute(PKG_STATEMENTS["insert_elicitation"], id=elicitation_id, v=v,
                       question=question,
                       options_offered=json.dumps(list(options_offered)),
                       answer_given=answer_given, resulting_edit=resulting_edit)
        return elicitation_id

    # -- export, import and the provenance gate (#31) -----------------------------------------

    def export_provenance_report(self, v: PackageVersionId) -> ProvenanceReport:
        """`FR-PKG-12`: the gate state and every `real_verbatim` exemplar holding it —
        the list the console's approval screen works from (`FR-CONSOLE-23`). The scope
        is the whole Tier P file, because that is what an export ships."""
        self._refuse_unknown_version(v)
        entries = tuple(
            ProvenanceEntry(
                exemplar_id=row["exemplar_id"],
                package_version_id=row["package_version_id"],
                criterion_id=row["criterion_id"],
                band=row["band"],
            ) for row in self._handle.query(
                PKG_STATEMENTS["select_real_verbatim_exemplars"])
        )
        flag = bool(self._handle.query(PKG_STATEMENTS["select_package_flag"],
                                       p=self._package_id)[0]["flag"])
        return ProvenanceReport(
            package_id=self._package_id,
            package_version_id=v,
            contains_real_student_text=flag,
            real_verbatim=entries,
        )

    def export(self, v: PackageVersionId, dest: Path) -> ExportReport:
        """`FR-PKG-10`: one self-contained archive — the Tier P database plus every
        blob its exemplars reference (`CT-STORE-07`) — importable with no network and
        no shared filesystem (`NFR-PKG-02`).

        The gate first (`FR-PKG-11`): a 1 in the DERIVED
        `package.contains_real_student_text` column refuses with `ExportBlockedError`
        carrying the provenance report, because a caller may treat any exported package
        as free of verbatim student text (`CT-PKG-13`). The database is snapshotted
        through SQLite's backup API (a consistent copy even beside a live WAL), hashed,
        and — when `HARNESS_PACKAGE_SIGNING_KEY` is set — signed with HMAC-SHA256 over
        the hash (`NFR-PKG-04`)."""
        self._refuse_unknown_version(v)
        flag = bool(self._handle.query(PKG_STATEMENTS["select_package_flag"],
                                       p=self._package_id)[0]["flag"])
        if flag:
            report = self.export_provenance_report(v)
            raise ExportBlockedError(
                f"package {self._package_id!r} carries real student text "
                f"(`contains_real_student_text = 1`): export is refused until every "
                f"real_verbatim exemplar is paraphrased-and-approved or dropped "
                f"(FR-PKG-11). The report on this error lists them.",
                report,
            )
        blob_hashes = tuple(row["blob_hash"] for row in self._handle.query(
            PKG_STATEMENTS["select_exemplar_blob_hashes"]))
        blob_data: dict[str, bytes] = {}
        if blob_hashes:
            if self._blobs is None:
                raise PackageError(
                    "this catalog holds no blob store, so the exemplar-referenced "
                    "blobs cannot travel. Construct it with blobs=store.blobs() "
                    "(CT-STORE-07: the export must be self-contained)."
                )
            for blob_hash in blob_hashes:
                try:
                    blob_data[blob_hash] = self._blobs.get(blob_hash)
                except (KeyError, ValueError) as error:
                    raise PackageError(
                        f"exemplar references blob {blob_hash}, which the blob store "
                        f"does not hold: {error}. The export would not be "
                        "self-contained (FR-PKG-10); declare the exemplar's material "
                        "or drop the reference."
                    ) from error
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        db_path = self._handle._open_report.path  # noqa: SLF001 -- the module's own substrate
        with tempfile.TemporaryDirectory() as snapshot_dir:
            snapshot = Path(snapshot_dir) / "package.pkg.sqlite"
            source = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
            try:
                copy = sqlite3.connect(snapshot)
                try:
                    source.backup(copy)
                    copy.execute(_SNAPSHOT_JOURNAL_MODE)
                    copy.commit()
                finally:
                    copy.close()
            finally:
                source.close()
            db_bytes = snapshot.read_bytes()
        content_hash = hashlib.sha256(db_bytes).hexdigest()
        key = os.environ.get(SIGNING_KEY_ENV)
        signed = key is not None
        provenance = tuple(row["provenance"] for row in self._handle.query(
            PKG_STATEMENTS["select_exemplar_provenance"], v=v))
        manifest = {
            "format": EXPORT_FORMAT_TAG,
            "format_version": EXPORT_FORMAT_VERSION,
            "package_id": self._package_id,
            "package_version_id": v,
            "schema_version": self._handle._open_report.schema_version_after,
            "content_hash": content_hash,
            "signature": _signature_of(content_hash, key) if signed else None,
            "blobs": list(blob_hashes),
            # FR-PKG-12: the exemplar provenance ACTUALLY exported travels in the
            # archive, so validated-with-real and exported-with-synthetic are
            # distinguishable on the receiving side, not only in the sender's log.
            "exemplar_provenance": list(provenance),
        }
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
            _zip_entry(archive, "manifest.json",
                       json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8"))
            _zip_entry(archive, "package.pkg.sqlite", db_bytes)
            for blob_hash in sorted(blob_data):
                _zip_entry(archive, f"blobs/{blob_hash}", blob_data[blob_hash])
        LOGGER.info(
            "exported package %s version %s provenance=%s dest=%s",
            self._package_id, v, list(provenance), dest,
        )
        return ExportReport(
            package_id=self._package_id,
            package_version_id=v,
            dest=str(dest),
            schema_version=manifest["schema_version"],
            content_hash=content_hash,
            signed=signed,
            blobs_included=blob_hashes,
            exemplar_provenance=provenance,
            bytes_written=dest.stat().st_size,
        )

    def import_file(self, src: Path) -> ImportReport:
        """`FR-PKG-10`/`FR-PKG-13`/`NFR-PKG-02`/`NFR-PKG-04`: import one export
        archive, all-or-nothing.

        Every check runs against bytes in memory BEFORE anything is written: format
        tag, content hash (the archive is intact), schema version (a package newer than
        this binary refuses with `SchemaTooNewError` NAMING the required upgrade —
        a partial import of a newer package is worse than a refused one), signature
        (REPORTED — verified | unsigned | mismatched | unverifiable — never a silent
        accept and never a refusal; NFR-PKG-04), target collision, and the archived
        database's own integrity (it is a Tier P file, it carries the manifest's
        version and package, its schema version matches the manifest's claim).

        The signature (if any) is HMAC-SHA256 over the content hash under
        `HARNESS_PACKAGE_SIGNING_KEY`. The report returns the imported version id —
        the Protocol's `PackageVersionId` answer, carried on the report because
        NFR-PKG-04's report is mandatory and a bare id cannot hold it.

        The returned report describes the import; the imported file migrates to this
        binary's schema version on its first `store.package()` open, exactly as any
        older tier file does."""
        src = Path(src)
        try:
            archive_bytes = zipfile.ZipFile(src)
        except zipfile.BadZipFile as error:
            raise PackageError(
                f"{src} is not a readable zip archive: {error}. Nothing was imported."
            ) from error
        with archive_bytes as archive:
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except KeyError as error:
                raise PackageError(
                    f"{src} carries no manifest.json; nothing was imported."
                ) from error
            if not isinstance(manifest, dict):
                raise PackageError(
                    f"the manifest in {src} is not a JSON object; nothing was imported."
                )
            for field in ("package_id", "package_version_id", "schema_version",
                          "content_hash"):
                if field not in manifest:
                    raise PackageError(
                        f"the manifest in {src} declares no {field!r}; nothing was "
                        "imported."
                    )
            if manifest.get("format") != EXPORT_FORMAT_TAG:
                raise PackageError(
                    f"{src} is not an AEH package export (format "
                    f"{manifest.get('format')!r})."
                )
            if manifest.get("format_version") != EXPORT_FORMAT_VERSION:
                raise PackageError(
                    f"the export format version {manifest.get('format_version')!r} is "
                    f"not {EXPORT_FORMAT_VERSION}; refusing an unknown format rather "
                    "than guessing at its contents."
                )
            db_bytes = archive.read("package.pkg.sqlite")
            content_hash = hashlib.sha256(db_bytes).hexdigest()
            if content_hash != manifest.get("content_hash"):
                raise PackageError(
                    f"the package in {src} does not match its content hash — the "
                    "archive is corrupt or was altered in transit; nothing was "
                    "imported."
                )
            current = current_schema_version(Tier.PACKAGE)
            file_schema = int(manifest["schema_version"])
            if file_schema > current:
                raise SchemaTooNewError(
                    f"the package in {src} was written by schema version "
                    f"{file_schema}; this binary provides {current}. Upgrade the "
                    f"binary to schema version {file_schema} or later — nothing was "
                    "imported (FR-PKG-13)."
                )
            signature = manifest.get("signature")
            key = os.environ.get(SIGNING_KEY_ENV)
            if signature is None:
                signature_status = "unsigned"
            elif key is None:
                signature_status = "unverifiable"
            elif not isinstance(signature, str):
                signature_status = "mismatched"
            else:
                expected = _signature_of(manifest["content_hash"], key)
                signature_status = ("verified" if hmac.compare_digest(signature, expected)
                                    else "mismatched")
            package_id = manifest["package_id"]
            if (not isinstance(package_id, str)
                    or not _SAFE_PACKAGE_ID.fullmatch(package_id)):
                raise PackageError(
                    f"the archive declares package id {package_id!r}, which is not a "
                    "safe package name; refusing it rather than writing outside the "
                    "packages directory."
                )
            target = self._handle._open_report.path.parent / f"{package_id}.pkg.sqlite"
            if target.exists():
                raise PackageError(
                    f"package {package_id!r} already exists in this installation; "
                    "importing would overwrite it — nothing was imported."
                )
            blob_data: dict[str, bytes] = {}
            for name in archive.namelist():
                if not name.startswith("blobs/"):
                    continue
                blob_hash = name.split("/", 1)[1]
                data = archive.read(name)
                if hashlib.sha256(data).hexdigest() != blob_hash:
                    raise PackageError(
                        f"blob {blob_hash} does not match its content hash; the "
                        "archive is corrupt — nothing was imported."
                    )
                blob_data[blob_hash] = data
            # Integrity peek on an IN-MEMORY copy: the archive's database must be a
            # Tier P file carrying the manifest's package and version, at the manifest's
            # schema version. Nothing has touched the target filesystem yet.
            peek = sqlite3.connect(":memory:")
            try:
                peek.deserialize(db_bytes)
                tables = {row[0] for row in peek.execute(_PEEK_TABLES)}
                if not {"package", "package_version", "schema_version"} <= tables:
                    raise PackageError(
                        f"the database in {src} is not a Tier P package file; nothing "
                        "was imported."
                    )
                in_file_schema = peek.execute(_PEEK_SCHEMA_VERSION).fetchone()[0]
                if in_file_schema != file_schema:
                    raise PackageError(
                        f"the archived database is at schema version "
                        f"{in_file_schema}, but its manifest claims {file_schema}; "
                        "nothing was imported."
                    )
                if package_id not in {
                    row[0] for row in peek.execute(_PEEK_PACKAGES)
                }:
                    raise PackageError(
                        f"the archived database does not carry package "
                        f"{package_id!r}; nothing was imported."
                    )
                if manifest["package_version_id"] not in {
                    row[0] for row in peek.execute(_PEEK_VERSIONS)
                }:
                    raise PackageError(
                        f"the manifest's version does not exist in the archived "
                        "database; nothing was imported."
                    )
            finally:
                peek.close()
            if blob_data and self._blobs is None:
                raise PackageError(
                    f"the archive carries {len(blob_data)} blob(s) its exemplars "
                    "reference, but this catalog holds no blob store. Importing would "
                    "silently drop them — a partial import (CT-PKG-14). Construct the "
                    "catalog with blobs=store.blobs()."
                )
            staging = target.parent / f".import-{uuid.uuid4().hex}.tmp"
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                staging.write_bytes(db_bytes)
                for blob_hash, data in blob_data.items():
                    self._blobs.put(data)
                os.replace(staging, target)
            finally:
                if staging.exists():
                    staging.unlink()
            # The flag is NOT re-derived here: it travels with the rows it derives
            # from, under the content hash this import just verified — re-writing it
            # would break the byte-level round-trip the archive guarantees, and any
            # tampering with either half already failed the hash check. The catalog's
            # own write path re-derives it on every exemplar write (ADR-4, TC-PKG-24);
            # files older than the column migrate on first open.
        report = ImportReport(
            package_version_id=manifest["package_version_id"],
            package_id=package_id,
            schema_version=file_schema,
            signature_status=signature_status,
            blobs_imported=len(blob_data),
            src=str(src),
        )
        LOGGER.info(
            "imported package %s version %s provenance=%s signature=%s src=%s",
            package_id, report.package_version_id, manifest.get("exemplar_provenance"),
            signature_status, src,
        )
        return report

    def _refuse_unknown_version(self, v: PackageVersionId) -> None:
        rows = self._handle.query(PKG_STATEMENTS["select_version"], v=v)
        if not rows:
            raise PackageError(
                f"package version {v!r} does not exist in this Tier P database."
            )

    # -- the lineage surface -----------------------------------------------------------------

    def create_version(
        self, parent: PackageVersionId | None, draft: PackageDraft | None = None
    ) -> PackageVersionId:
        """Mint a version: a brand-new package's first version (`parent=None`) or a
        revision of an existing one (`FR-PKG-02`).

        A revision **copies** the parent's content rows into the new version — the copy is
        how a §6.2 clarification edit happens (`FR-PKG-04`): the edit lands in the new,
        unlocked version, and the parent is untouched. The new version is born unlocked."""
        version_id = f"{self._package_id}@{uuid.uuid4().hex[:12]}"
        with self._handle.transaction() as tx:
            if parent is None:
                self._refuse_no_such_package(tx)
                tx.execute(PKG_STATEMENTS["insert_first_version"],
                           v=version_id, p=self._package_id)
            else:
                # NOTE: the parent may be published — a revision of a published version
                # is exactly FR-PKG-02's flow. create_version only READS the parent
                # (the copy) and INSERTs new rows, so no guard fires here; the triggers
                # backstop the parent's rows against UPDATE, not the lineage copy.
                revision = self._next_revision(tx, parent)
                parent_row = tx.execute(PKG_STATEMENTS["select_version"], v=parent)[0]
                tx.execute(PKG_STATEMENTS["insert_revision"],
                           v=version_id, p=self._package_id, rev=revision,
                           parent=parent)
                for key in _REVISION_COPY_KEYS:
                    tx.execute(PKG_STATEMENTS[key], new=version_id, old=parent)
                # The copy's completeness gate (#230): a criterion that fails the copy —
                # a declared band_count the copied bands do not satisfy (FR-PKG-06's
                # even-band bar) — refuses the revision HERE, inside the transaction,
                # rather than shipping a half-copied child (CT-PKG-02). The refusal is
                # a no-op on disk: the child row and every copy roll back together.
                self._validate_band_sets(
                    lambda name: tx.execute(PKG_STATEMENTS[name], v=version_id),
                    boundary="shipped as a revision",
                )
        for criterion_id in (draft.criteria if draft is not None else ()):
            tx.execute(PKG_STATEMENTS["insert_criterion"], v=version_id,
                       criterion_id=criterion_id, question_id=criterion_id,
                       kind="open", max_points=0.0, scoring_model="atomic",
                       construct_tag="", band_count=None, evidence_type=None)
        if parent is not None:
            copied = ", ".join(
                f"{row['surface']}={row['n']}" for row in self._handle.query(
                    PKG_STATEMENTS["pkg_revision_copied_counts"], v=version_id))
            LOGGER.info(
                "created package version %s (package %s, parent %s): revision %d -> "
                "%d, copied verbatim %s — the copy changed no field; explicit edits "
                "land on the unlocked child through the guarded write surface",
                version_id, self._package_id, parent, parent_row["revision"],
                revision, copied)
        else:
            LOGGER.info("created package version %s (package %s, parent %s)",
                        version_id, self._package_id, parent)
        return version_id

    def publish(self, v: PackageVersionId, approved_by: str) -> None:
        """Set `locked = 1` — the one permitted update to a version row, and the moment
        its immutability begins (`FR-PKG-01`).

        `FR-PKG-06`'s count half runs at the publish boundary — every declared
        band_count fully populated and even/2..6 — and BEFORE the lock flips, so a
        refused publish is a no-op: a version locked with an incomplete band set would
        be an immutable invalid instrument, which is worse than an unpublished one."""
        self._refuse_mutation(v)
        # The validation counts THIS VERSION's rows from the database — not the
        # per-run cache (which holds whatever version was read last), and not a
        # criterion-id lookup (which would count every revision's copied bands of the
        # same criterion id; the parent's rows are not this version's).
        self._validate_band_sets(
            lambda name: self._handle.query(PKG_STATEMENTS[name], v=v),
            boundary="publishable",
        )
        with self._handle.transaction() as tx:
            tx.execute(PKG_STATEMENTS["publish"], by=approved_by, v=v)
            LOGGER.info("published package version %s by %s at %s",
                        v, approved_by, datetime.now(timezone.utc).isoformat())
        self._invalidate()

    def is_locked(self, v: PackageVersionId) -> bool:
        """Whether `v` is published. Read surface for the tests and the console."""
        return bool(self._handle.query(
            PKG_STATEMENTS["select_version"], v=v)[0]["locked"])

    def lineage(self, v: PackageVersionId) -> tuple[PackageVersionId, ...]:
        """The version's ancestry, oldest first — the chain a grade resolves through."""
        chain: list[PackageVersionId] = []
        current: str | None = v
        seen: set[str] = set()
        while current is not None and current not in seen:
            seen.add(current)
            chain.append(current)
            row = self._handle.query(PKG_STATEMENTS["select_version"], v=current)[0]
            current = row["parent_version_id"] if row["parent_version_id"] else None
        return tuple(reversed(chain))

    # -- the question inventory and setup proposal (#50) --------------------------------------
    #
    # The Tier P storage M-SETUP's Stage A reaches: the package row its first version
    # needs, the proposal record, and the confirmed question inventory. M-PKG validates
    # every structural constraint on the way in (CT-PKG-12) — whatever M-SETUP checked,
    # the data layer checks again — and the confirmation lock lives with the data
    # (FR-SETUP-02): `update_question_field` is the surface that proves it.

    def ensure_package(self) -> None:
        """Create the package row if absent. `create_version` refuses to mint one —
        its refusal names M-SETUP's initial version as the writer (`FR-SETUP-16`'s
        first move is exactly this) — so setup's `ensure_version` calls here first."""
        if not self._handle.query(PKG_STATEMENTS["count_package"],
                                  p=self._package_id)[0]["n"]:
            with self._handle.transaction() as tx:
                tx.execute(PKG_STATEMENTS["insert_package"], p=self._package_id)
            LOGGER.info("created package %s (M-SETUP's initial version)", self._package_id)

    def draft_version(self) -> PackageVersionId | None:
        """The package's latest UNPUBLISHED version, or None — the version setup works
        on, across processes (nothing is held in memory: resume is a fresh catalog
        reading the same Tier P file, CT-SETUP-03). A published version is never the
        draft: setup has already finished for it."""
        rows = self._handle.query(PKG_STATEMENTS["select_latest_draft_version"],
                                  p=self._package_id)
        return rows[0]["package_version_id"] if rows else None

    def has_version(self) -> bool:
        """Whether the package holds ANY version — the read that distinguishes
        `setup has not started` (no version at all) from `setup has finished` (a
        published version, no draft) in the console's step report."""
        return bool(self._handle.query(PKG_STATEMENTS["select_has_version"],
                                       p=self._package_id))

    def latest_version(self) -> PackageVersionId | None:
        """The package's most recent version, published or not (`#53`): the read
        the FINISHED step report needs — once setup finishes the draft is gone,
        but the step records the published version carries are still the truth
        about what was taken, and the console reads them through this."""
        rows = self._handle.query(PKG_STATEMENTS["select_latest_package_version"],
                                  p=self._package_id)
        return rows[0]["package_version_id"] if rows else None

    def record_proposal(
        self, v: PackageVersionId, *, proposal_id: str, assessment_doc_id: str,
        payload: str, template_version: str, model_ref: str, attempts: int,
    ) -> None:
        """Record (first write) or replace (a re-request's payload, CT-SETUP-12) the
        version's UNCONFIRMED inventory proposal. Refused when a proposal is already
        confirmed — the inventory is locked then (FR-SETUP-02), and proposing again is
        out of order (CT-SETUP-16: one proposal per version)."""
        self._refuse_unknown_version(v)
        self._refuse_mutation(v)
        row = self._handle.query(PKG_STATEMENTS["select_proposal"], v=v)
        if row and row[0]["confirmed_at"] is not None:
            raise PackageError(
                f"the inventory for version {v!r} was confirmed at "
                f"{row[0]['confirmed_at']}; the question rows are locked (FR-SETUP-02) "
                "and proposing again is out of order (CT-SETUP-16). A new instrument "
                "is a new version (FR-PKG-02)."
            )
        with self._handle.transaction() as tx:
            if row:
                tx.execute(PKG_STATEMENTS["update_proposal_payload"], v=v,
                           payload=payload, attempts=attempts)
            else:
                tx.execute(PKG_STATEMENTS["insert_proposal"], v=v,
                           proposal_id=proposal_id,
                           assessment_doc_id=assessment_doc_id, payload=payload,
                           template_version=template_version, model_ref=model_ref,
                           attempts=attempts)
        LOGGER.info("recorded inventory proposal %s for version %s (attempt %d)",
                    proposal_id, v, attempts)

    def proposal(self, v: PackageVersionId) -> dict | None:
        """The version's proposal row, or None — the read half (resume re-reads it
        instead of re-proposing)."""
        rows = self._handle.query(PKG_STATEMENTS["select_proposal"], v=v)
        return dict(rows[0]) if rows else None

    def write_confirmed_inventory(
        self, v: PackageVersionId, *, proposal_id: str,
        questions: Sequence[Mapping], confirmed_at: str,
    ) -> None:
        """Write the confirmed inventory in ONE transaction (`FR-SETUP-02`): the
        question rows, their options, and the proposal's confirmation stamp, all or
        nothing — a half-written inventory that publish's gate could misread is worse
        than a refused confirmation.

        Each question record is a mapping with `question_id`, `ordinal`,
        `prompt_text`, `question_type`, `max_points` and `options` (a sequence of
        mappings with `option_id`, `ordinal`, `label`). The structural validation here
        is M-PKG's own (CT-PKG-12) — it does not trust the caller's check. Refused when
        the proposal is unknown, already confirmed, or a different proposal id; refused
        on a published version. `reference_solution` is NOT written here: confirmation
        locks everything except it, and the rubric read-back (#51) fills it."""
        self._refuse_unknown_version(v)
        self._refuse_mutation(v)
        row = self._handle.query(PKG_STATEMENTS["select_proposal"], v=v)
        if not row:
            raise PackageError(
                f"no inventory proposal is recorded for version {v!r}: confirm_inventory "
                "confirms a proposal, and propose_inventory has not run."
            )
        if row[0]["confirmed_at"] is not None:
            raise PackageError(
                f"the inventory for version {v!r} is already confirmed "
                f"(at {row[0]['confirmed_at']}); it is locked (FR-SETUP-02) and cannot "
                "be confirmed again."
            )
        if row[0]["proposal_id"] != proposal_id:
            raise PackageError(
                f"confirmation names proposal {proposal_id!r} but version {v!r} holds "
                f"{row[0]['proposal_id']!r} — a stale or foreign confirmation is "
                "refused; the teacher confirms what was proposed."
            )
        validated = self._validated_inventory(questions)
        with self._handle.transaction() as tx:
            for question in validated:
                tx.execute(PKG_STATEMENTS["insert_question"], v=v,
                           question_id=question["question_id"],
                           ordinal=question["ordinal"],
                           prompt_text=question["prompt_text"],
                           question_type=question["question_type"],
                           max_points=question["max_points"],
                           reference_solution=None, confirmed_at=confirmed_at)
                for option in question["options"]:
                    tx.execute(PKG_STATEMENTS["insert_question_option"], v=v,
                               question_id=question["question_id"],
                               option_id=option["option_id"],
                               ordinal=option["ordinal"], label=option["label"])
            tx.execute(PKG_STATEMENTS["confirm_proposal"], v=v,
                       confirmed_at=confirmed_at)
        LOGGER.info("confirmed inventory for version %s: %d question(s), proposal %s",
                    v, len(validated), proposal_id)

    def questions(self, v: PackageVersionId) -> tuple[dict, ...]:
        """The version's confirmed question rows, in confirmed order."""
        return tuple(
            dict(row) for row in
            self._handle.query(PKG_STATEMENTS["select_questions"], v=v)
        )

    def question_options(
        self, v: PackageVersionId, question_id: str
    ) -> tuple[dict, ...]:
        """One confirmed question's option set, in declared order."""
        return tuple(
            dict(row) for row in
            self._handle.query(PKG_STATEMENTS["select_options_by_question"],
                               v=v, question_id=question_id)
        )

    def update_question_field(
        self, v: PackageVersionId, question_id: str, field: str, value: Any
    ) -> None:
        """Edit one question field in place — the confirmation lock's write surface.

        A CONFIRMED question row refuses every field except `reference_solution`
        (`FR-SETUP-02`: the lock engages at confirmation, earlier than publication —
        the confirmation IS the teacher's assertion about content, and HLD §7.8 names
        the open/mcq conversion a redefinition). A published version refuses everything
        (`PublishedVersionImmutableError`), and the triggers backstop the same rule for
        writes that route around the catalog."""
        writable = ("prompt_text", "ordinal", "max_points", "question_type",
                    "reference_solution")
        if field not in writable:
            raise PackageError(
                f"question field {field!r} is not writable here; writable fields: "
                f"{', '.join(writable)}."
            )
        self._refuse_unknown_version(v)
        self._refuse_mutation(v)
        rows = self._handle.query(PKG_STATEMENTS["select_question"], v=v,
                                  question_id=question_id)
        if not rows:
            raise PackageError(
                f"question {question_id!r} does not exist in version {v!r}."
            )
        if rows[0]["confirmed_at"] is not None and field != "reference_solution":
            SCHEMA_LOCK_VIOLATIONS.increment()
            LOGGER.warning(
                "schema lock violation: the question.%r edit on question %r in version "
                "%r is refused (FR-SETUP-02) — the inventory was confirmed and the "
                "edit would redefine what was asked", field, question_id, v,
            )
            raise SchemaLockViolation(
                f"the question.{field} edit on question {question_id!r} in version "
                f"{v!r} is refused: the inventory was confirmed at "
                f"{rows[0]['confirmed_at']} and its content is locked (FR-SETUP-02). "
                "Corrections happen before confirmation; a published version's "
                f"sanctioned vehicle is a new version (create_version(parent={v!r}))."
            )
        with self._handle.transaction() as tx:
            tx.execute(PKG_STATEMENTS[f"update_question_{field}"], v=v,
                       question_id=question_id, value=value)

    def readback(self, v: PackageVersionId) -> dict | None:
        """The version's rubric read-back row, or None — the read half (resume re-reads
        the stored row instead of re-reading the rubric, `CT-SETUP-03`; the row exists
        only after a read back completed or degraded, never mid-flight)."""
        rows = self._handle.query(PKG_STATEMENTS["select_readback"], v=v)
        return dict(rows[0]) if rows else None

    # -- #52: the decomposability verdicts and the setup steps' provenance ---------------

    def record_classification(
        self, v: PackageVersionId, *, criterion_id: str, classification: str,
        decomposition_basis: str | None, source: str, recorded_at: str,
    ) -> None:
        """Write one decomposability classification row (`#52`, `FR-SETUP-06`, R62).

        `source` is `'default'` (the module's §5.3 table decided, the teacher has not
        spoken) or `'teacher'` (`confirm_classifications` upserts over the default row
        — the teacher's judgment replaces it as the stored record, which is exactly
        the distinction M-CALIB and M-STATS read). Refused on a published version
        (the published-immunity triggers)."""
        if source not in ("default", "teacher"):
            raise PackageError(
                f"classification source {source!r} is outside the vocabulary "
                "('default', 'teacher') — a row that cannot say who spoke cannot "
                "distinguish a teacher's judgment from a system default (R62)."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.add")
            tx.execute(PKG_STATEMENTS["insert_classification"], v=v,
                       criterion_id=criterion_id, classification=classification,
                       decomposition_basis=decomposition_basis, source=source,
                       recorded_at=recorded_at)
        self._invalidate()

    def classifications(self, v: PackageVersionId) -> tuple[dict, ...]:
        """The version's stored classification rows, ordered by criterion id — the
        audit read (`M-CALIB`/`M-STATS`'s teacher-vs-default distinction)."""
        return tuple(
            dict(row) for row in
            self._handle.query(PKG_STATEMENTS["select_classifications"], v=v)
        )

    def classification(self, v: PackageVersionId,
                       criterion_id: str) -> dict | None:
        """One criterion's stored classification row, or None."""
        rows = self._handle.query(PKG_STATEMENTS["select_classification"], v=v,
                                  criterion_id=criterion_id)
        return dict(rows[0]) if rows else None

    def record_step(
        self, v: PackageVersionId, *, step_id: str, status: str, payload: str,
        recorded_at: str,
    ) -> None:
        """Upsert one setup step's provenance row (`FR-SETUP-14`, `#52`).

        The write half of "a default taken is recorded": each optional setup step
        names itself here when it completes — by the teacher's action or, at
        publish, as a recorded default. `payload` is the step's own JSON summary."""
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.add")
            tx.execute(PKG_STATEMENTS["insert_step_record"], v=v, step_id=step_id,
                       status=status, payload=payload, recorded_at=recorded_at)
        self._invalidate()

    def record_default_step(
        self, v: PackageVersionId, *, step_id: str, status: str, payload: str,
        recorded_at: str,
    ) -> bool:
        """Record a step's default-taken row ONLY where the step carries no row of
        its own — the publish-time skip record (`FR-SETUP-14`). Returns whether a
        row was written: a step the teacher (or the step itself) already recorded is
        never overwritten by a default."""
        if self.step_record(v, step_id) is not None:
            return False
        # The guard runs BEFORE the transaction, not inside it — the shape the
        # catalog's own publish() uses. This write sits on the publish path's
        # happy tail, and CT-SETUP-02 audits that path to exactly ONE
        # lock-carrying statement: an in-transaction guard would put a second
        # package_version statement (the guard's SELECT) in the audited window.
        self._refuse_mutation(v)
        with self._handle.transaction() as tx:
            tx.execute(PKG_STATEMENTS["insert_step_record"], v=v, step_id=step_id,
                       status=status, payload=payload, recorded_at=recorded_at)
        self._invalidate()
        return True

    def set_default_grade_policy(self, v: PackageVersionId,
                                 policy: GradePolicy) -> bool:
        """Write the default policy row ONLY where no policy exists — the
        publish-path twin of `record_default_step` (`FR-SETUP-12`): a policy the
        teacher declared is never overwritten by the default. Returns whether a
        row was written. The guards run BEFORE the transaction, for the same
        reason `record_default_step`'s do: this write sits on the publish path's
        happy tail, and CT-SETUP-02 audits that path to exactly ONE lock-carrying
        statement — an in-transaction guard would put a second package_version
        statement (the guard's SELECT) in the audited window."""
        if not isinstance(policy, GradePolicy):
            raise GradePolicyError(
                f"the grade policy must be a GradePolicy object drawn from the closed "
                f"rule vocabulary (FR-PKG-14); got {type(policy).__name__}."
            )
        if self.grade_policy_declared(v):
            return False
        self._refuse_mutation(v)
        with self._handle.transaction() as tx:
            tx.execute(PKG_STATEMENTS["delete_policy"], v=v)
            tx.execute(PKG_STATEMENTS["insert_policy"], v=v,
                       policy=json.dumps(policy.to_dict(), sort_keys=True),
                       review_window_hours=policy.review_window_hours)
        self._invalidate()
        return True

    def step_record(self, v: PackageVersionId, step_id: str) -> dict | None:
        """One setup step's provenance row, or None — the done half of the console's
        step enumeration reads this."""
        rows = self._handle.query(PKG_STATEMENTS["select_step_record"], v=v,
                                  step_id=step_id)
        return dict(rows[0]) if rows else None

    def step_records(self, v: PackageVersionId) -> tuple[dict, ...]:
        """All of the version's step-provenance rows, ordered by step id."""
        return tuple(
            dict(row) for row in
            self._handle.query(PKG_STATEMENTS["select_step_records"], v=v)
        )

    def write_readback(
        self, v: PackageVersionId, *, rubric_doc_id: str, assessment_doc_id: str,
        criteria: Sequence[Mapping], payload: str, template_version: str,
        model_ref: str, attempts: int, created_at: str,
    ) -> None:
        """Write the rubric read-back in ONE transaction (`FR-SETUP-04/-05/-09`, #51):
        every criterion row with its band set, `evidence_type` and `band_justification`,
        plus the read-back provenance row — all or nothing (`CT-PKG-11`: a rejected
        write is a no-op, so a failed read-back leaves nothing behind and the next
        attempt re-proposes onto a clean draft).

        Each criterion record is a mapping with `criterion_id`, `question_id`, `kind`,
        `max_points`, `scoring_model`, `band_count`, `evidence_type`,
        `band_justification` and `bands` (a sequence of mappings with `band`, `ordinal`,
        `points`, `descriptor`). The structural validation here is M-PKG's own
        (`CT-PKG-12`) — the band rules are the same ones `add_criterion`/`add_band`
        enforce (`FR-PKG-06`), plus the read-back's own rule: a `band_count` above two
        carries a recorded justification (`FR-SETUP-04`). Descriptor CONTENT is not
        checked here — the magnitude-phrase bar is M-SETUP's Configuration
        (`FR-SETUP-05`), and this module does not import it. Refused when a read-back
        row already exists for the version (one read back per version, `CT-SETUP-16`),
        on a published version, or for a criterion id the version already carries."""
        self._refuse_unknown_version(v)
        self._refuse_mutation(v)
        if self._handle.query(PKG_STATEMENTS["select_readback"], v=v):
            raise PackageError(
                f"version {v!r} already holds a rubric read-back (CT-SETUP-16: one "
                "read back per version) — the stored row is provenance and is not "
                "replaced; the rubric read-back resumes from it."
            )
        validated = self._validated_readback(criteria)
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion.add")
            for criterion in validated:
                existing = [row["criterion_id"] for row in tx.execute(
                    PKG_STATEMENTS["select_criteria"], v=v)]
                if criterion["criterion_id"] in existing:
                    raise PackageError(
                        f"criterion {criterion['criterion_id']!r} already exists in "
                        f"version {v!r} — the read back writes criteria onto a clean "
                        "draft, not over rows another path added."
                    )
                if not tx.execute(PKG_STATEMENTS["select_question"], v=v,
                                  question_id=criterion["question_id"]):
                    raise PackageError(
                        f"criterion {criterion['criterion_id']!r} names question "
                        f"{criterion['question_id']!r}, which the version's CONFIRMED "
                        "inventory does not carry — criteria anchor to confirmed "
                        "questions (FR-SETUP-02)."
                    )
                tx.execute(PKG_STATEMENTS["insert_readback_criterion"], v=v,
                           criterion_id=criterion["criterion_id"],
                           question_id=criterion["question_id"],
                           kind=criterion["kind"],
                           max_points=criterion["max_points"],
                           scoring_model=criterion["scoring_model"],
                           construct_tag=criterion["construct_tag"],
                           band_count=criterion["band_count"],
                           evidence_type=criterion["evidence_type"],
                           band_justification=criterion["band_justification"])
                for band in criterion["bands"]:
                    tx.execute(PKG_STATEMENTS["insert_band"], v=v,
                               criterion_id=criterion["criterion_id"],
                               ordinal=band["ordinal"], band=band["band"],
                               points=band["points"], descriptor=band["descriptor"])
                rows = [row for row in tx.execute(
                    PKG_STATEMENTS["select_bands"], v=v)
                    if row["criterion_id"] == criterion["criterion_id"]]
                self._validate_band_order(rows)
            tx.execute(PKG_STATEMENTS["insert_readback"], v=v,
                       rubric_doc_id=rubric_doc_id,
                       assessment_doc_id=assessment_doc_id, payload=payload,
                       template_version=template_version, model_ref=model_ref,
                       attempts=attempts, created_at=created_at)
        self._invalidate()
        LOGGER.info(
            "wrote rubric read-back for version %s: %d criterion(s), prompt %s, "
            "attempt %d", v, len(validated), template_version, attempts,
        )

    def _validated_readback(
        self, criteria: Sequence[Mapping]
    ) -> tuple[dict, ...]:
        """The structural half of the read-back write (`CT-PKG-12`): ids, the question
        anchor, the band rules (`FR-PKG-06`) and the justification rule
        (`FR-SETUP-04`). Descriptor content is M-SETUP's bar, not this module's."""
        validated: list[dict] = []
        seen_ids: set[str] = set()
        for index, record in enumerate(criteria):
            where = f"read-back criterion record #{index}"
            criterion_id = str(record.get("criterion_id", "") or "")
            if not criterion_id:
                raise PackageError(f"{where}: criterion_id must be non-empty.")
            if criterion_id in seen_ids:
                raise PackageError(
                    f"{where}: duplicate criterion_id {criterion_id!r} — criteria are "
                    "distinct."
                )
            seen_ids.add(criterion_id)
            question_id = str(record.get("question_id", "") or "")
            if not question_id:
                raise PackageError(
                    f"{where} ({criterion_id!r}): question_id must be non-empty — a "
                    "criterion anchors to a confirmed question."
                )
            kind = record.get("kind")
            if kind not in ("open", "mcq"):
                raise PackageError(
                    f"{where} ({criterion_id!r}): kind {kind!r} is outside the "
                    "vocabulary ('open', 'mcq')."
                )
            scoring_model = str(record.get("scoring_model", "") or "")
            if not scoring_model:
                raise PackageError(
                    f"{where} ({criterion_id!r}): scoring_model must be non-empty."
                )
            try:
                max_points = float(record.get("max_points", 0.0))
            except (TypeError, ValueError) as error:
                raise PackageError(
                    f"{where} ({criterion_id!r}): max_points must be a number, got "
                    f"{record.get('max_points')!r}."
                ) from error
            if max_points < 0:
                raise PackageError(
                    f"{where} ({criterion_id!r}): max_points {max_points} is negative."
                )
            if not math.isfinite(max_points):
                raise PackageError(
                    f"{where} ({criterion_id!r}): max_points {max_points} is not a "
                    "finite number — SQLite stores NaN as NULL, so a NaN would trip "
                    "the NOT NULL constraint instead of a validation error."
                )
            construct_tag = str(record.get("construct_tag", "") or "")
            evidence_type = record.get("evidence_type")
            if evidence_type is not None and not str(evidence_type).strip():
                raise PackageError(
                    f"{where} ({criterion_id!r}): evidence_type, when given, must be "
                    "non-empty (FR-SETUP-09) — a declaration of nothing satisfies no "
                    "criterion."
                )
            band_count = record.get("band_count")
            if (not isinstance(band_count, int) or isinstance(band_count, bool)
                    or band_count < 2 or band_count > 6 or band_count % 2 != 0):
                raise BandSetError(
                    f"{where} ({criterion_id!r}): band_count {band_count!r} is odd or "
                    "outside 2..6 (FR-PKG-06). The even count removes the safe middle "
                    "band a hesitant judge retreats to (design §5.10, R40)."
                )
            justification = record.get("band_justification")
            justification = str(justification) if justification is not None else ""
            if band_count > 2 and not justification.strip():
                raise BandSetError(
                    f"{where} ({criterion_id!r}): band_count {band_count} exceeds the "
                    "two-band default without a recorded justification (FR-SETUP-04) — "
                    "partial credit that is genuinely part of the construct is "
                    "recorded, not silent."
                )
            raw_bands = record.get("bands", ()) or ()
            if len(raw_bands) != band_count:
                raise BandSetError(
                    f"{where} ({criterion_id!r}): {len(raw_bands)} band(s) written "
                    f"against a declared band_count of {band_count} (FR-PKG-06) — "
                    "`add_band` refuses past the declared count, so an under-filled "
                    "set would strand the criterion half-mapped."
                )
            bands: list[dict] = []
            for band_index, band in enumerate(raw_bands):
                band_where = f"{where} ({criterion_id!r}) band #{band_index}"
                label = str(band.get("band", "") or "")
                if not label.strip():
                    raise BandSetError(
                        f"{band_where}: band label must be non-empty."
                    )
                ordinal = band.get("ordinal")
                if (not isinstance(ordinal, int) or isinstance(ordinal, bool)
                        or ordinal < 0):
                    raise BandSetError(
                        f"{band_where}: ordinal must be a non-negative integer, got "
                        f"{ordinal!r}."
                    )
                try:
                    points = float(band.get("points", 0.0))
                except (TypeError, ValueError) as error:
                    raise BandSetError(
                        f"{band_where}: points must be a number, got "
                        f"{band.get('points')!r}."
                    ) from error
                if points < 0:
                    raise BandSetError(f"{band_where}: points {points} is negative.")
                if not math.isfinite(points):
                    raise BandSetError(
                        f"{band_where}: points {points} is not a finite number — "
                        "SQLite stores NaN as NULL, and an infinity is not a points "
                        "value a band can carry."
                    )
                bands.append({"band": label, "ordinal": ordinal, "points": points,
                              "descriptor": str(band.get("descriptor", "") or "")})
            validated.append({
                "criterion_id": criterion_id, "question_id": question_id,
                "kind": kind, "max_points": max_points,
                "scoring_model": scoring_model, "construct_tag": construct_tag,
                "band_count": band_count, "evidence_type": evidence_type,
                "band_justification": justification or None, "bands": tuple(bands),
            })
        return tuple(validated)

    def _validated_inventory(
        self, questions: Sequence[Mapping]
    ) -> tuple[dict, ...]:
        """The structural half of the confirmed write (`CT-PKG-12`): vocabulary, ids,
        ordinals, and the option-set/type pairing — `mcq`/`mixed` carry a non-empty
        option set, `open` carries none (a typed mismatch is a proposal bug, and the
        schema's CHECK would refuse the row anyway; refusing it here keeps the exact
        `InventoryError` type instead of a bare sqlite error)."""
        if not questions:
            raise InventoryError(
                "a confirmed inventory carries at least one question — confirming an "
                "empty inventory would publish an instrument with nothing on it."
            )
        validated: list[dict] = []
        seen_ids: set[str] = set()
        seen_ordinals: set[int] = set()
        for index, record in enumerate(questions):
            where = f"question record #{index}"
            question_id = str(record.get("question_id", "") or "")
            if not question_id:
                raise InventoryError(f"{where}: question_id must be non-empty.")
            if question_id in seen_ids:
                raise InventoryError(
                    f"{where}: duplicate question_id {question_id!r} — questions are "
                    "distinct."
                )
            seen_ids.add(question_id)
            ordinal = record.get("ordinal")
            if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
                raise InventoryError(
                    f"{where} ({question_id!r}): ordinal must be a non-negative "
                    f"integer, got {ordinal!r}."
                )
            if ordinal in seen_ordinals:
                raise InventoryError(
                    f"{where} ({question_id!r}): duplicate ordinal {ordinal} — two "
                    "questions cannot share a position."
                )
            seen_ordinals.add(ordinal)
            prompt_text = str(record.get("prompt_text", "") or "")
            if not prompt_text.strip():
                raise InventoryError(
                    f"{where} ({question_id!r}): prompt_text must be non-empty — an "
                    "empty prompt asks nothing."
                )
            question_type = record.get("question_type")
            if question_type not in QUESTION_TYPES:
                raise InventoryError(
                    f"{where} ({question_id!r}): question_type {question_type!r} is "
                    f"outside the vocabulary {QUESTION_TYPES} (FR-SETUP-01)."
                )
            max_points = record.get("max_points", 0.0)
            try:
                max_points = float(max_points)
            except (TypeError, ValueError) as error:
                raise InventoryError(
                    f"{where} ({question_id!r}): max_points must be a number, got "
                    f"{max_points!r}."
                ) from error
            if max_points < 0:
                raise InventoryError(
                    f"{where} ({question_id!r}): max_points {max_points} is negative."
                )
            raw_options = record.get("options", ()) or ()
            options: list[dict] = []
            option_ids: set[str] = set()
            option_ordinals: set[int] = set()
            for option_index, option in enumerate(raw_options):
                option_id = str(option.get("option_id", "") or "")
                label = str(option.get("label", "") or "")
                option_ordinal = option.get("ordinal")
                if not option_id:
                    raise InventoryError(
                        f"{where} ({question_id!r}) option #{option_index}: option_id "
                        "must be non-empty."
                    )
                if option_id in option_ids:
                    raise InventoryError(
                        f"{where} ({question_id!r}): duplicate option_id {option_id!r} "
                        "— options are distinct."
                    )
                if not label.strip():
                    raise InventoryError(
                        f"{where} ({question_id!r}) option {option_id!r}: label must "
                        "be non-empty — an option a student cannot read."
                    )
                if (not isinstance(option_ordinal, int)
                        or isinstance(option_ordinal, bool) or option_ordinal < 0):
                    raise InventoryError(
                        f"{where} ({question_id!r}) option {option_id!r}: ordinal must "
                        f"be a non-negative integer, got {option_ordinal!r}."
                    )
                if option_ordinal in option_ordinals:
                    raise InventoryError(
                        f"{where} ({question_id!r}): duplicate option ordinal "
                        f"{option_ordinal} — two options cannot share a position."
                    )
                option_ordinals.add(option_ordinal)
                option_ids.add(option_id)
                options.append({"option_id": option_id, "ordinal": option_ordinal,
                                "label": label})
            if question_type in ("mcq", "mixed") and not options:
                raise InventoryError(
                    f"{where} ({question_id!r}): a {question_type} question carries a "
                    "non-empty option set — the teacher would have nothing to mark."
                )
            if question_type == "open" and options:
                raise InventoryError(
                    f"{where} ({question_id!r}): an open question carries no option "
                    f"set — the model proposed {len(options)} option(s); a typed "
                    "mismatch is a proposal bug, not a content choice."
                )
            validated.append({
                "question_id": question_id, "ordinal": ordinal,
                "prompt_text": prompt_text, "question_type": question_type,
                "max_points": max_points, "options": tuple(options),
            })
        return tuple(validated)

    # -- the guards ---------------------------------------------------------------------------

    def _refuse_mutation(self, v: PackageVersionId) -> None:
        """The data-layer guard (`NFR-PKG-01`): raise before any statement touches a
        published version's rows."""
        row = self._handle.query(PKG_STATEMENTS["select_version"], v=v)
        if not row:
            return  # an unknown version is the caller's next statement's problem
        if row[0]["locked"]:
            raise PublishedVersionImmutableError(
                f"package version {v!r} is published (locked = 1) and immutable "
                f"(FR-PKG-01). A revision is a NEW version with parent_version_id "
                f"(FR-PKG-02) — mint it via create_version(parent={v!r})."
            )

    def _refuse_no_such_package(self, tx) -> None:
        rows = tx.execute(PKG_STATEMENTS["count_package"], p=self._package_id)
        if not rows[0]["n"]:
            raise PackageError(
                f"package {self._package_id!r} does not exist in this Tier P database. "
                "A version is minted into an existing package; the package row arrives "
                "with M-SETUP's initial version."
            )

    def _next_revision(self, tx, parent: PackageVersionId) -> int:
        row = tx.execute(PKG_STATEMENTS["select_version"], v=parent)[0]
        return int(row["revision"]) + 1


# --- the module-level export seam (the written-ahead contract's surface) ------------------------
#
# `TC-REG-02` (`FR-PKG-10`'s golden), `CT-STATS-13`/`CT-STATS-20` and `CT-CONFORM-14` were all
# written ahead (test plan §8.2) against a module-level `aeh.pkg:export_package` /
# `record_validation` / `in_memory_catalog` — names **neither design document declares** (the
# entries in `tests/support/impl.py` say so explicitly). This section lands those seams as thin,
# honest wrappers rather than leaving three suites permanently red behind a story that closed:
#
# - `export_package(package_version, dest=None, population=None)` — with `dest`, materializes the
#   reference corpus package and writes a REAL archive through `PackageCatalog.export`; without
#   `dest`, answers the validation figures the module-level registry holds for the version
#   (the exported-package payload `CT-STATS-13` audits). Installations export through
#   `PackageCatalog.export`; this seam is the contract tests' surface and says so.
# - `record_validation` — the write side the design never named (`M-STATS`/`M-CONFORM` write
#   "through M-PKG" per `CT-PKG-12`): catalog-backed for the in-memory catalog, registry-backed
#   for the module-level summary.
# - `in_memory_catalog()` — a catalog LIFETIME for in-process tests: one shared scratch Tier P
#   store (per-version isolation; version ids are minted unique), with the validation-summary
#   rendering `CT-CONFORM-14`'s sweep audits.

#: The module-level validation registry, keyed by package version then population scope.
_VALIDATION_BROADCAST: dict[str, dict[str, dict]] = {}

#: The shared scratch store behind every `in_memory_catalog()` (lazy; cleaned at exit).
_IN_MEMORY_STATE: tuple[tempfile.TemporaryDirectory, Any] | None = None

_IN_MEMORY_PACKAGE_ID = "in-memory"

#: The stamp the reference materializer writes into `schema_version`. The store's own
#: migrations stamp `datetime('now')`, which would make every build's bytes differ and the
#: TC-REG-02 baseline useless; a fixed stamp is the same device the migration fixtures use.
_REFERENCE_STAMP = "2026-01-01T00:00:00Z"

_SCHEMA_VERSION_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_version ("
    "version INTEGER NOT NULL PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
)


def _apply_statement(connection: sqlite3.Connection, statement: Statement) -> None:
    """Execute one declared `Statement` on a raw connection — the same
    parameter-bound shape `_run` uses in the store, so the scanner reads it as the
    declared statement it is."""
    connection.execute(statement.sql)


@dataclass(frozen=True)
class ExportSummary:
    """The exported-package payload without the archive: what a receiving school would
    read about a version's validation, as `CT-STATS-13` audits it. `validation` is a
    plain dict carrying `weakest_per_population` (the figure that must travel BESIDE any
    headline) and `headline_per_population` — never an aggregate across populations."""

    package_version_id: str
    validation: dict


class InMemoryCatalog:
    """A catalog lifetime over the shared scratch Tier P store, with the validation
    summary rendering `CT-CONFORM-14` audits. Delegates the package protocol to a real
    `PackageCatalog`; isolation between instances is per-version (ids are minted
    unique), which is exactly the isolation the property tests need."""

    def __init__(self, catalog: PackageCatalog) -> None:
        self._catalog = catalog
        self._records: list[Any] = []

    def create_version(self, parent: PackageVersionId | None = None,
                       draft: PackageDraft | None = None) -> PackageVersionId:
        return self._catalog.create_version(parent, draft)

    def set_dependencies(self, version: PackageVersionId,
                         edges: Sequence[tuple[str, str]]) -> None:
        self._catalog.set_dependencies(version, edges)

    def topological_order(self, version: PackageVersionId) -> tuple[str, ...]:
        return self._catalog.topological_order(version)

    def record_validation(self, record: Any) -> None:
        self._records.append(record)

    def render_validation_summary(self, backend_profile: str,
                                  panel_build_ref: str) -> str:
        """The validation records for one backend and panel build, rendered as text.

        Deliberately scoped per line and per record — `CT-STATS-20`'s detector reads
        framing, so a summary that aggregated across backends would fail the sweep it
        feeds — and deliberately WITHOUT equivalence vocabulary: the score-distribution
        gate is `unavailable` here, and an unavailable gate must never be rendered as a
        claim that the backends agree (`CT-CONFORM-14`)."""
        lines: list[str] = []
        for record in self._records:
            if record.backend_profile != backend_profile:
                continue
            panel = getattr(record, "panel_build_ref", panel_build_ref)
            if panel is not None and panel != panel_build_ref:
                continue
            lines.append(f"backend {backend_profile} validation summary, "
                         f"panel build {panel_build_ref}:")
            for dimension, classification in getattr(
                    record, "classification", {}).items():
                lines.append(f"  {dimension}: {classification} for this backend "
                             "and panel build")
            for dimension in getattr(record, "unavailable_dimensions", ()):
                lines.append(f"  {dimension}: unavailable — the gate cannot fire for "
                             "this backend and panel build, so no agreement claim "
                             "covers it")
        return "\n".join(lines)


def in_memory_catalog() -> InMemoryCatalog:
    """A fresh `InMemoryCatalog` over the shared scratch store (created on first use,
    closed at process exit). One store, not one per call: the property suites build
    hundreds of catalogs, and a scratch file per example would leak a thousand temp
    dirs per run — per-version isolation is what the tests actually need."""
    global _IN_MEMORY_STATE
    if _IN_MEMORY_STATE is None:
        scratch = tempfile.TemporaryDirectory(prefix="aeh-in-memory-pkg-")

        def _cleanup() -> None:
            try:
                store.close()
            except Exception:
                pass
            try:
                scratch.cleanup()
            except Exception:
                pass

        store = open_store(Path(scratch.name))
        handle = store.package(_IN_MEMORY_PACKAGE_ID)
        with handle.transaction() as tx:
            tx.execute(
                "INSERT INTO package (package_id, created_at) VALUES (:p, :created)",
                p=_IN_MEMORY_PACKAGE_ID, created=_REFERENCE_STAMP)
        atexit.register(_cleanup)
        _IN_MEMORY_STATE = (scratch, store)
    _, store = _IN_MEMORY_STATE
    return InMemoryCatalog(PackageCatalog(
        store.package(_IN_MEMORY_PACKAGE_ID), package_id=_IN_MEMORY_PACKAGE_ID,
        blobs=store.blobs()))


def record_validation(catalog: InMemoryCatalog | None = None, record: Any = None, *,
                      package_version: str | None = None,
                      population_scope: str | None = None, headline: dict | None = None,
                      weakest_per_population: dict | None = None) -> None:
    """Record one validation figure set — the write side `CT-PKG-12` routes through this
    module and the design never named (the `tests/support/impl.py` entry says so).

    Two shapes, because two suites were written ahead against this name:

    - `record_validation(catalog, record)` — writes through the given in-memory
      catalog, whose `render_validation_summary` the `CT-CONFORM-14` sweep reads.
    - `record_validation(package_version=..., population_scope=..., headline=...,
      weakest_per_population=...)` — writes the module-level registry that
      `export_package(package_version=...)` serves. Every figure is keyed by population
      scope; there is no cross-population aggregate to record.
    """
    if catalog is not None:
        if record is None:
            raise PackageError(
                "record_validation(catalog, record) needs the record to write."
            )
        catalog.record_validation(record)
        return
    if package_version is None or population_scope is None:
        raise PackageError(
            "record_validation needs a catalog and a record, or package_version and "
            "population_scope."
        )
    _VALIDATION_BROADCAST.setdefault(package_version, {})[population_scope] = {
        "headline": dict(headline or {}),
        "weakest_per_population": dict(weakest_per_population or {}),
    }


def _render_validation_text(package_version: str, population: str,
                            records: dict[str, dict]) -> str:
    """The validation figures for ONE population, rendered per line with its scope
    beside every figure (`CT-STATS-20`: a number with no scope near it is the violation,
    per line, not per document)."""
    record = records.get(population)
    if record is None:
        # No figures recorded for this population: say so, scoped, with no number —
        # never an invented zero and never an unscoped headline (CT-STATS-20).
        return (f"package {package_version} validation figures, "
                f"population {population}: no validation figures recorded for this "
                "population.")
    lines = [f"package {package_version} validation figures, "
             f"population {population}:"]
    headline = record["headline"]
    if headline:
        kappa = headline.get("kappa")
        n = headline.get("n")
        lines.append(f"  population {population} headline: kappa {kappa} with "
                     f"n = {n} for this population")
    for scope, weakest in record["weakest_per_population"].items():
        lines.append(f"  population {scope} weakest criterion "
                     f"{weakest.get('criterion_id')}: kappa "
                     f"{weakest.get('kappa')} for this population, backend "
                     f"{weakest.get('backend', 'as recorded')} and panel "
                     f"{weakest.get('panel', 'as recorded')}")
    return "\n".join(lines)


def _reference_spec() -> dict:
    """The reference package corpus (`fixtures/package/reference-package.json`), read
    relative to this file so the repo checkout serves it. A wheel install has no
    fixtures directory; the seam says so rather than guessing."""
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / "fixtures" / "package" / "reference-package.json"
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise PackageError(
        "the module-level export seam serves the reference corpus, and the corpus "
        "fixture (fixtures/package/reference-package.json) is not installed with this "
        "package. Export through PackageCatalog.export."
    )


def export_package(package_version: str, dest: Path | str | None = None,
                   population: str | None = None) -> Any:
    """The module-level export seam the written-ahead suites key on.

    - `dest` given: materialize the reference corpus package into a deterministic Tier P
      file (fixed ids, fixed `schema_version` stamps — the migration fixtures' device)
      and write a REAL archive through `PackageCatalog.export`. The archive's member
      listing is stable for identical content, which is `TC-REG-02`'s baseline.
    - `dest` omitted, `population` omitted: the validation summary as
      `ExportSummary.validation` (`CT-STATS-13`).
    - `dest` omitted, `population` given: the validation figures for that ONE
      population, rendered per line with its scope beside every figure
      (`CT-STATS-20`'s consumer sweep).
    """
    if dest is None:
        records = _VALIDATION_BROADCAST.get(package_version) or {}
        if population is not None:
            return _render_validation_text(package_version, population, records)
        if not records:
            raise PackageError(
                f"no validation figures recorded for package version "
                f"{package_version!r}. record_validation(...) seeds the registry the "
                "module-level export seam reads."
            )
        weakest: dict = {}
        for record in records.values():
            weakest.update(record["weakest_per_population"])
        return ExportSummary(
            package_version_id=package_version,
            validation={
                "weakest_per_population": weakest,
                "headline_per_population": {
                    scope: record["headline"] for scope, record in records.items()
                },
            },
        )
    spec = _reference_spec()
    if str(spec.get("package_version")) != str(package_version):
        raise PackageError(
            f"the module-level export seam materializes the reference corpus "
            f"(version {spec.get('package_version')!r}); {package_version!r} has no "
            "materialization here. Export a live package through PackageCatalog.export."
        )
    package_id = spec["package_id"]
    version_id = str(spec["package_version"])
    with tempfile.TemporaryDirectory(prefix="aeh-reference-pkg-") as tmp:
        root = Path(tmp)
        db_path = root / "packages" / f"{package_id}.pkg.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(_SCHEMA_VERSION_DDL)
            for migration in TIER_MIGRATIONS[Tier.PACKAGE]:
                for statement_text in migration.statements:
                    _apply_statement(connection, statement_text)
                connection.execute(
                    "INSERT INTO schema_version (version, name, applied_at) "
                    "VALUES (?, ?, ?)",
                    (migration.version, migration.name, _REFERENCE_STAMP))
            connection.execute(
                "INSERT INTO package (package_id, created_at) VALUES (?, ?)",
                (package_id, _REFERENCE_STAMP))
            connection.execute(
                "INSERT INTO package_version (package_version_id, package_id, "
                "revision, locked) VALUES (?, ?, 1, 0)", (version_id, package_id))
            for criterion in spec["criteria"]:
                answer_key = (json.dumps(criterion["answer_key"])
                              if criterion.get("answer_key") else None)
                connection.execute(
                    "INSERT INTO criterion (package_version_id, criterion_id, "
                    "question_id, kind, max_points, scoring_model, construct_tag, "
                    "band_count, answer_key) VALUES (?, ?, ?, ?, NULL, 'atomic', "
                    "'', NULL, ?)",
                    (version_id, criterion["criterion_id"], criterion["question_id"],
                     criterion["kind"], answer_key))
                for band in criterion.get("bands", ()):
                    connection.execute(
                        "INSERT INTO band (package_version_id, criterion_id, ordinal, "
                        "band, points, descriptor) VALUES (?, ?, ?, ?, ?, ?)",
                        (version_id, criterion["criterion_id"], band["ordinal"],
                         band["band"], band["points"],
                         band.get("descriptor", "")))
            connection.commit()
        finally:
            connection.close()
        store = open_store(root)
        try:
            catalog = PackageCatalog(store.package(package_id),
                                     package_id=package_id, blobs=store.blobs())
            return catalog.export(version_id, Path(dest))
        finally:
            store.close()


# --- the single band→points mapping ---------------------------------------------------------------


def points_for_band(bands: Sequence[Any], band_name: str) -> float:
    """The canonical band→points mapping, module-level and pure (`CT-PKG-05`,
    `NFR-AGG-02`; issue #91's mapping stage).

    One definition, in M-PKG, of the only sanctioned reader of a band table's
    points: every consumer routes through this function rather than re-deriving a
    mapping — `M-AGG`'s aggregation maps the *aggregated* band through it exactly
    once, after the median is taken (`FR-AGG-02`), and a per-judge average of
    mapped points has no code path and may not gain one.

    `bands` is the declared band set in any row shape the module already produces
    — the store cache's mappings (`{"band": ..., "points": ...}`) or the declared
    value objects (`.band`/`.points`) a criterion carries (`CT-PKG-04`). The
    points are a **lookup**: the row's own value, returned untouched and never
    computed (`FR-PKG-06`'s monotone guarantee is the table's property, not this
    function's to enforce).
    """
    for row in bands:
        name = row["band"] if isinstance(row, dict) else getattr(row, "band")
        if name == band_name:
            points = row["points"] if isinstance(row, dict) else getattr(row, "points")
            return float(points)
    raise PackageError(f"the declared band set carries no band {band_name!r}.")
