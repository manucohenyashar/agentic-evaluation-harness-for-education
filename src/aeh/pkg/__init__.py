"""M-PKG: the assessment package catalog (design §3.4).

A package holds everything needed to grade one assessment: its questions, criteria, bands,
worked examples, answer keys, grade policy and grade boundaries. Each package lives in its own
Tier P database file and is versioned. Once a version is published it is locked: the fields
listed in the schema lock can never change, and a correction is made by minting a new version.
Every read and write of a package goes through `PackageCatalog`.

The catalog also keeps the package's validation record (how well the system agreed with
teachers, per population), the provenance gate that blocks export while real student text is
present, and the signed export/import format used to move a package between schools.

Files:
    vocabulary.py       question types, evaluation modes and provenance words
    errors.py           the errors this package raises
    lock.py             the schema lock: which fields are frozen, and the violation counter
    grade_policy.py     `GradePolicy`, its rules, the default policy, and `points_for_band`
    export_format.py    the archive format: entries, signature, snapshot statements
    records.py          reports, the manifest, `NoValidationData` and `PackageDraft`
    schema.py           the Tier P and durable-tier migrations
    statements.py       the SQL statements M-PKG runs
    validation.py       the validation record's durable writes and baselines
    graph.py            the criterion dependency graph and its checks
    criteria.py         editing criteria, bands and exemplars
    policy_and_keys.py  grade policy, boundaries, answer keys and options on the catalog
    validation_reads.py the catalog's validation reads and the manifest
    versions.py         minting, publishing and finding versions
    exchange.py         the provenance gate, export and import
    setup_records.py    what M-SETUP records: proposals, inventory, read-back, steps
    setup_checks.py     the structural checks on the inventory and read-back writes
    rubric_methods.py   score methods: the composite shape and the general derivation
    catalog.py          `PackageCatalog`
    in_memory.py        the module-level entry points over an in-memory catalog

Detailed design notes (the full original module description): `docs/code-notes/pkg.md`.
"""

from __future__ import annotations

from .vocabulary import (
    DEFAULT_SCORE_METHOD,
    default_evaluation_mode,
    EVALUATION_MODES,
    LOGGER,
    PackageVersionId,
    PROVENANCE_VOCABULARY,
    QUESTION_TYPES,
    SCORE_METHODS,
)
from .errors import (
    BandSetError,
    CyclicDependencyError,
    ExportBlockedError,
    GradePolicyError,
    InventoryError,
    PackageError,
    PackageIntegrityError,
    PublishedVersionImmutableError,
    SchemaLockViolation,
    SchemaTooNewError,
)
from .lock import (
    _LOCKED_FIELD_HLD_NAMES,
    SCHEMA_LOCK_FIELDS,
    schema_lock_violation_count,
    SCHEMA_LOCK_VIOLATIONS,
)
from .grade_policy import (
    COMBINATION_RULES,
    default_grade_policy,
    GateRule,
    GradePolicy,
    points_for_band,
    ROUNDING_MODES,
    ScaleRule,
)
from .export_format import EXPORT_FORMAT_TAG, EXPORT_FORMAT_VERSION, SIGNING_KEY_ENV
from .records import (
    ExportReport,
    ImportReport,
    Manifest,
    ManifestEntry,
    NO_DATA_REASONS,
    NoValidationData,
    PackageDraft,
    ProvenanceEntry,
    ProvenanceReport,
)
from . import schema  # noqa: F401  (imported for its registrations)
from .statements import PKG_STATEMENTS
from .validation import (
    BASELINE_NO_HISTOGRAM,
    BASELINE_NO_PACKAGES,
    BASELINE_NO_SUCH_VERSION,
    BASELINE_PUBLISHED,
    BASELINE_RECORDED,
    BASELINE_UNDECLARED_BAND,
    BaselineWrite,
    NONINFERIORITY_VERDICTS,
    promotion_record,
    record_noninferiority,
    record_promotion,
    record_validation_baseline,
)
from .graph import DependencyGraphMixin
from .criteria import CriterionEditsMixin
from .policy_and_keys import PolicyAndKeysMixin
from .validation_reads import ValidationReadsMixin
from .versions import VersionsMixin
from .exchange import ExchangeMixin
from .setup_records import SetupRecordsMixin
from .setup_checks import SetupChecksMixin
from .catalog import PackageCatalog
from .in_memory import (
    export_package,
    ExportSummary,
    in_memory_catalog,
    InMemoryCatalog,
    NO_NEW_VALIDATION_EVIDENCE,
    record_validation,
    _VALIDATION_ADMINISTRATION_RECORDS,
    validation_for,
    ValidationEvidenceGap,
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
    "PackageIntegrityError",
    "ImportReport",
    "InventoryError",
    "QUESTION_TYPES",
    "InMemoryCatalog",
    "BASELINE_RECORDED",
    "BaselineWrite",
    "Manifest",
    "NO_NEW_VALIDATION_EVIDENCE",
    "NoValidationData",
    "record_validation_baseline",
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
    "ValidationEvidenceGap",
    "default_grade_policy",
    "export_package",
    "in_memory_catalog",
    "points_for_band",
    "record_promotion",
    "record_validation",
    "validation_for",
]
