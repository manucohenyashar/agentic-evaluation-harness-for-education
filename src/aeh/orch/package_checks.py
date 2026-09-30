"""Checks on a package version before a run uses it, and finding the cohort files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import WorkLedgerError


# --- the orchestrator ---------------------------------------------------------------------------


def _cohort_keys_on_filesystem(store: Any) -> tuple[str, ...]:
    """The default cohort-key discovery: the ledger's own files.

    `SqliteStore` lays Tier C out as one file per cohort under `<data_dir>/cohorts/`
    (§3.3's layout); listing that directory is the no-bookkeeping way to find every
    ledger there is. A store that lays the tier out differently injects its own key
    function on the orchestrator.
    """
    data_dir = getattr(store, "data_dir", None)
    if data_dir is None:
        raise WorkLedgerError(
            "resume() with no arguments discovers runs from the store's cohort ledger "
            "files, which needs the store's data directory; this store exposes no "
            "`data_dir`. Pass an explicit run_id, or inject a cohort_keys_for function."
        )
    return tuple(
        path.stem for path in Path(data_dir, "cohorts").glob("*.sqlite")
    )


def validate_grade_policy(catalog: Any, package_version_id: str) -> None:
    """Refuse a version whose grade policy names criteria the version does not declare
    (`FR-ORCH-31`, `CT-ORCH-25`, `CT-GRADE-15`'s run-start half).

    Called by `create_run` before the run row exists, so a refusal leaves nothing behind: the
    policy's ghost criterion is caught at run start rather than at grading time, where the
    operator meets it as a missing input on a run that has already spent money.

    Every referencing field of the shipped `GradePolicy` is checked — the `weights` members and
    the `gate`'s criterion. `FR-ORCH-31` also names per-question rules and best-k members;
    neither has a field in the landed policy object (`best_k_of_n` carries `k`, a count, and no
    member list), so there is nothing to read for them today. A policy that grows either field
    must extend `_policy_criterion_ids` in the same change.

    A version with no declared policy is not an error: the default policy references nothing.
    """
    from aeh.pkg import PackageIntegrityError  # `aeh.pkg` owns Tier P's migrations (see
    # `_catalog`: the import stays local so registration order remains each module's own).

    declared_policy = getattr(catalog, "grade_policy_declared", None)
    if callable(declared_policy) and not declared_policy(package_version_id):
        return
    policy = catalog.grade_policy(package_version_id)
    referenced = _policy_criterion_ids(policy)
    if not referenced:
        return
    declared = {
        _criterion_id_of(row) for row in catalog.criteria(package_version_id)
    }
    missing = sorted(name for name in referenced if name not in declared)
    if missing:
        raise PackageIntegrityError(
            f"the grade policy of {package_version_id!r} names criteria the version does not "
            f"declare: {', '.join(repr(name) for name in missing)}. The run refuses to start "
            f"(FR-ORCH-31): a policy referring to a criterion that is not there grades by a "
            f"rule nobody can satisfy, and the package is what needs fixing. Declared: "
            f"{sorted(declared)}"
        )


def _criterion_id_of(row: Any) -> str:
    """One criterion row's id, whatever shape the catalog hands back (mapping or object)."""
    if isinstance(row, dict):
        return str(row.get("criterion_id"))
    try:
        return str(row["criterion_id"])
    except (TypeError, KeyError, IndexError):
        return str(getattr(row, "criterion_id", ""))


def _policy_criterion_ids(policy: Any) -> set[str]:
    """Every criterion id the policy references, across its referencing fields."""
    referenced: set[str] = set()
    for criterion_id, _weight in getattr(policy, "weights", ()) or ():
        if criterion_id:
            referenced.add(str(criterion_id))
    gate = getattr(policy, "gate", None)
    gate_criterion = getattr(gate, "criterion_id", None) if gate is not None else None
    if gate_criterion:
        referenced.add(str(gate_criterion))
    return referenced
