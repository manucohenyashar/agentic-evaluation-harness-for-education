"""`M-PKG` — Assessment Package Catalog (design §3.4).

Owns Tier P: package identity and version lineage, the §6.2 schema lock, criteria and
bands, the dependency graph, exemplars, the grade policy, and validation records. This
file landed **#26** — version lineage and published-version immutability
(`FR-PKG-01`, `-02`, `-04`, `NFR-PKG-01`); #27-#30 have since added the schema lock's
enumerable list, bands and the dependency graph, validation records, and the grade
policy, boundaries, answer keys and elicitation history; #31 adds export/import.

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

import json
import math
import uuid
from dataclasses import dataclass
from typing import Any, Sequence

from aeh.store import (
    Migration,
    STATEMENTS,
    Statement,
    Tier,
    TIER_MIGRATIONS,
    current_schema_version,
)

__all__ = [
    "BandSetError",
    "CyclicDependencyError",
    "GateRule",
    "GradePolicy",
    "GradePolicyError",
    "Manifest",
    "NoValidationData",
    "PackageCatalog",
    "PackageDraft",
    "PackageError",
    "PackageVersionId",
    "PublishedVersionImmutableError",
    "SCHEMA_LOCK_FIELDS",
    "ScaleRule",
    "SchemaLockViolation",
    "default_grade_policy",
]

#: A package version's id: an opaque string the catalog mints.
PackageVersionId = str


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


class CyclicDependencyError(PackageError):
    """A `criterion_dependency` write would make the dependency graph cyclic
    (`FR-PKG-05`).

    The extraction sweep's two-pass order rests on the graph being a DAG; a cycle would
    strand the cycle's criteria in the second pass forever. Not retryable — the edge is
    the mistake."""


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


class PublishedVersionImmutableError(PackageError):
    """An update was attempted on a published (`locked = 1`) `package_version`, or on any
    row referencing one (`FR-PKG-01`).

    A published version is the anchor a grade issued years ago resolves to; mutating it —
    or any criterion, band or exemplar beneath it — silently rewrites history. Not
    retryable: the fix is a **revision** (`create_version` with the published version as
    parent), never a mutation."""


class GradePolicyError(PackageError):
    """A grade policy outside the closed rule vocabulary, or a malformed boundary
    table (`FR-PKG-14`). Answer-key refusals raise the module base `PackageError` —
    the key is FR-PKG-17's surface, not the policy vocabulary's.

    The vocabulary — weighted sum, gate, best-k-of-n, drop-lowest-n, scale, rounding,
    boundary table — is closed on purpose (the ADR): an executable formula in a package
    is an arbitrary-code surface and an un-auditable grade, so a policy that is not a
    structured object is refused at construction, at write and at read. Not retryable —
    the policy is the mistake, and rewriting it is a draft edit."""


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
        "INSERT INTO criterion (package_version_id, criterion_id, question_id, kind, "
        "answer_key) SELECT :new, criterion_id, question_id, kind, answer_key "
        "FROM criterion WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_band": Statement(
        "INSERT INTO band (package_version_id, criterion_id, ordinal, band, points) "
        "SELECT :new, criterion_id, ordinal, band, points FROM band "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_dependency": Statement(
        "INSERT INTO criterion_dependency (package_version_id, criterion_id, depends_on) "
        "SELECT :new, criterion_id, depends_on FROM criterion_dependency "
        "WHERE package_version_id = :old"
    ),
    "pkg_revision_copy_exemplar": Statement(
        "INSERT INTO exemplar (exemplar_id, package_version_id, criterion_id, band) "
        "SELECT hex(randomblob(8)), :new, criterion_id, band FROM exemplar "
        "WHERE package_version_id = :old"
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
    "insert_criterion": Statement(
        "INSERT INTO criterion (package_version_id, criterion_id, question_id, kind, "
        "max_points, scoring_model, construct_tag, band_count) VALUES (:v, "
        ":criterion_id, :question_id, :kind, :max_points, :scoring_model, "
        ":construct_tag, :band_count)"
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
        "INSERT INTO exemplar (exemplar_id, package_version_id, criterion_id, band) "
        "VALUES (:exemplar_id, :v, :criterion_id, :band)"
    ),
    "select_criteria": Statement(
        "SELECT criterion_id, question_id, kind, max_points, scoring_model, "
        "construct_tag, band_count, answer_key FROM criterion "
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
)

#: The revision copy order: parents before children, so every copied row's FK is
#: satisfied at insert time. Each key names a statement in `PKG_STATEMENTS`.
_REVISION_COPY_KEYS: tuple[str, ...] = (
    "pkg_revision_copy_criterion",
    "pkg_revision_copy_band",
    "pkg_revision_copy_dependency",
    "pkg_revision_copy_exemplar",
    "pkg_revision_copy_mcq_option",
    "pkg_revision_copy_grade_policy",
    "pkg_revision_copy_grade_boundary",
)
# elicitation_history is deliberately NOT a revision copy: it is the append-only
# calibration trail (FR-PKG-20), whose rows reference the version the conversation was
# about — copying them would duplicate history, and no process may rewrite it.


# --- the catalog --------------------------------------------------------------------------------


@dataclass(frozen=True)
class PackageDraft:
    """A new package version's content, as `M-SETUP`/`M-CALIB` hand it over.

    #26's scope is identity and lineage, so the draft carries the version's identity
    fields; #28 adds criteria and bands to this shape (the dataclass grows fields, which
    is additive per §3.2's compatibility rule)."""

    title: str = ""


class PackageCatalog:
    """Tier P's data-access layer, over `M-STORE`'s `package(id)` handle.

    Every mutating method funnels through `_refuse_mutation` — the data-layer guard —
    and the database triggers installed by migration 002 backstop the same rule for
    writes that bypass the catalog. The catalog holds one Tier P database (one package
    file), so `catalog = PackageCatalog(store.package(package_id), package_id=package_id)`.
    """

    def __init__(self, handle, *, package_id: str) -> None:
        self._handle = handle
        self._package_id = package_id
        # The per-run cache (NFR-PKG-05): loaded once against a version, invalidated on
        # publish and on any edit. ~23,000 unit reads per run must not re-query SQLite.
        self._cache: dict | None = None
        self._cache_version: str | None = None

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
        band_count: int | None = None,
    ) -> None:
        """Add a criterion with its dependency edges, refusing a cycle (`FR-PKG-05`) —
        the guard's add-refusal applies to published versions; drafts add freely. The
        content arguments default so a published version's refusal fires before any
        content is needed (TC-PKG-03 row 2 passes only the id).

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
                       construct_tag=construct_tag, band_count=band_count)
            for depends_on in dependencies:
                tx.execute(PKG_STATEMENTS["insert_dependency"],
                           v=v, criterion_id=criterion_id, depends_on=depends_on)
        self._cache_get(v)
        self._assert_acyclic(self._version_graph(v))
        self._invalidate()

    def add_band(
        self, v: PackageVersionId, criterion_id: str, ordinal: int,
        band: str, points: float, descriptor: str = "",
    ) -> None:
        """Add one band, enforcing the structural rules on the whole set afterwards
        (`FR-PKG-06`)."""
        declared = self._band_count(v, criterion_id)
        with self._handle.transaction() as tx:
            self._guard(tx, v, "band.add-unpublished")
            if declared is not None and ordinal >= declared:
                raise BandSetError(
                    f"band ordinal {ordinal} exceeds the criterion's declared "
                    f"band_count of {declared} (FR-PKG-06)."
                )
            tx.execute(PKG_STATEMENTS["insert_band"],
                       v=v, criterion_id=criterion_id, ordinal=ordinal,
                       band=band, points=points, descriptor=descriptor)
        rows = self._read_bands(criterion_id)
        self._validate_band_order(rows)
        if declared is not None and len(rows) == declared:
            self._validate_band_count(len(rows))
        self._invalidate()

    def add_exemplar(
        self, v: PackageVersionId, exemplar_id: str, criterion_id: str, band: str,
    ) -> None:
        """Add an exemplar, refusing a band that does not name a band declared for the
        criterion (`FR-PKG-07`)."""
        declared = {row["band"] for row in self._read_bands(criterion_id)}
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
                       band=band)
        self._invalidate()

    def topological_order(self, v: PackageVersionId) -> tuple[str, ...]:
        """A valid topological order over the version's dependency graph — dependencies
        before dependents, which is `M-ORCH`'s extraction sweep order (`FR-PKG-05`)."""
        return self._toposort(self._version_graph(v))

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
        """The band→points mapping, monotone in ordinal (`FR-PKG-06`'s guarantee)."""
        for row in self.bands(criterion_id):
            if row["band"] == band:
                return float(row["points"])
        raise PackageError(f"criterion {criterion_id!r} declares no band {band!r}.")

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
        _ = draft  # #28 extends the draft with criteria; the identity write needs none
        return version_id

    def publish(self, v: PackageVersionId, approved_by: str) -> None:
        """Set `locked = 1` — the one permitted update to a version row, and the moment
        its immutability begins (`FR-PKG-01`)."""
        self._refuse_mutation(v)
        with self._handle.transaction() as tx:
            tx.execute(PKG_STATEMENTS["publish"], by=approved_by, v=v)
        # FR-PKG-06's count half, at the publish boundary: every declared band_count is
        # fully populated and even/2..6. The per-add checks covered order and ceiling.
        # The validation reads the DATABASE directly — the cache was just invalidated.
        for row in self._handle.query(PKG_STATEMENTS["select_criteria"], v=v):
            criterion = dict(row)
            declared = self._band_count(v, criterion["criterion_id"])
            if declared is not None:
                self._validate_band_count(len(self.bands(criterion["criterion_id"])))
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
