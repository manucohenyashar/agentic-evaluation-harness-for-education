"""The errors M-PKG raises. They are siblings, never a chain, so callers catch exactly one."""

from __future__ import annotations

from .records import ProvenanceReport


class PackageError(Exception):
    """Base class for every M-PKG failure. The error types are siblings, never a chain, so each can
    be caught exactly."""


class BandSetError(PackageError):
    """A band set breaks the structural rules scoring relies on (FR-PKG-06): a `band_count` that is
    odd or outside 2..6, ordinals not running from 0 without gaps, or points that decrease.

    The monotone mapping is what `M-AGG` and `M-GRADE` assume; the even count is the
    design rule that removes the safe middle band a hesitant judge retreats to
    (design §5.10, R40). Not retryable by mutation — the band set is rewritten as a
    whole."""

    retryable = False


class CyclicDependencyError(PackageError):
    """A dependency write would make the dependency graph cyclic (FR-PKG-05).

    The extraction sweep's two-pass order rests on the graph being a DAG; a cycle would
    strand the cycle's criteria in the second pass forever. Not retryable — the edge is
    the mistake."""

    retryable = False


class SchemaLockViolation(PackageError):
    """An edit to a field frozen by the schema lock was attempted (FR-PKG-03).

    The message names the offending field, because `M-CALIB` routes every rubric edit
    through this module (`FR-CALIB-07`) and an operator fixing a refused edit needs the
    field, not a generic refusal. The forbidden-field list is `SCHEMA_LOCK_FIELDS` — one
    place in the source, enumerable at runtime (`NFR-PKG-03`); a second copy of the list
    is how a locked field quietly becomes editable.

    Not retryable by mutation: the sanctioned vehicle for every clarification is a new
    version (`FR-PKG-04`).
    """

    retryable = False

    #: Where the refusal is raised. Every raise site is the catalog's `_guard` — the one
    #: check every mutation funnels through (`NFR-PKG-03`) — so the value is a constant
    #: rather than a per-instance field. `M-CALIB` routes its edits through this surface
    #: precisely so it needs no lock check of its own (`FR-CALIB-07`, `CT-CALIB-06`: a
    #: second implementation of one rule is what drifts), and the attribute lets a caller
    #: verify the refusal came from the lock instead of from a caller-side copy of it.
    raised_by = "catalog"


class PublishedVersionImmutableError(PackageError):
    """An update was attempted on a published version, or on a row belonging to one (FR-PKG-01).

    A published version is the anchor a grade issued years ago resolves to; mutating it —
    or any criterion, band or exemplar beneath it — silently rewrites history. Not
    retryable: the fix is a **revision** (`create_version` with the published version as
    parent), never a mutation."""

    retryable = False


class GradePolicyError(PackageError):
    """A grade policy uses a rule outside the allowed list, or its boundary table is malformed
    (FR-PKG-14). Answer-key refusals raise `PackageError` instead.

    The vocabulary — weighted sum, gate, best-k-of-n, drop-lowest-n, scale, rounding,
    boundary table — is closed on purpose (the ADR): an executable formula in a package
    is an arbitrary-code surface and an un-auditable grade, so a policy that is not a
    structured object is refused at construction, at write and at read. Not retryable —
    the policy is the mistake, and rewriting it is a draft edit."""


class PackageIntegrityError(PackageError):
    """A package version's declarations contradict each other (FR-ORCH-31).

    The first member is the grade policy naming a criterion the version does not declare: the
    package is internally inconsistent, so a run started against it would grade by a rule
    referring to something that is not there. The refusal names **every** offending id, not the
    first — an operator fixing a package needs the list, and a refusal that names one id per
    attempt turns one edit into four. Not retryable: the package is the mistake."""

    retryable = False


class ExportBlockedError(PackageError):
    """Export was attempted while the package still contains real student text (FR-PKG-11).

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
    """An imported package's schema is newer than this code supports (FR-PKG-13).

    The message names the required upgrade, and nothing is partially imported — a
    partial import of a newer package is worse than a refused one. Mirrors
    `M-STORE`'s refusal of a too-new tier file; this is the package-archive half."""

    retryable = False


class InventoryError(PackageError):
    """A confirmed question inventory is structurally invalid (FR-SETUP-01).

    The question vocabulary, the option-set/type pairing, unique ids and ordinals —
    these are the structural constraints `M-PKG` owns (`CT-PKG-12`: every Tier P write
    is validated here, whatever the caller already checked). Retryable by fixing the
    records, not by re-sending them unchanged."""

    retryable = False
