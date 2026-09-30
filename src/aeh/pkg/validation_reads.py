"""The catalog's validation reads: records, baselines, verdicts and the manifest."""

from __future__ import annotations

import json
from typing import Any

from .vocabulary import PackageVersionId
from .records import Manifest, ManifestEntry, NoValidationData, _weakest_entry
from .statements import PKG_STATEMENTS


class ValidationReadsMixin:
    """Stores and reads validation records, baselines and non-inferiority verdicts; builds the manifest."""

    # -- validation records and the manifest (#29) ----------------------------------------------

    def store_validation(
        self, v: PackageVersionId, criterion_id: str, population_scope_id: str,
        backend_profile: str, panel_build_ref: str, scoring_model: str,
        agreement: float, n: int,
    ) -> None:
        """Store one validation record under the six-part key (FR-PKG-08). On a published version
        it is refused only if it would change an existing row: records are append-only in practice.
        """
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
        """The validation record for one key, or `NoValidationData`, which cannot be confused with
        a zero or a low figure (FR-PKG-09). There is no aggregate anywhere here (CT-PKG-07): the
        caller names the key and gets that key's record."""
        rows = self._handle.query(PKG_STATEMENTS["select_validation_record"],
                                  v=v, criterion_id=criterion_id,
                                  population_scope_id=population_scope_id,
                                  backend_profile=backend_profile,
                                  panel_build_ref=panel_build_ref,
                                  scoring_model=scoring_model)
        if not rows:
            return NoValidationData()
        return dict(rows[0])

    def baselines_for(
        self, v: PackageVersionId, *, backend_profile: str, panel_build_ref: str,
        population_scope_id: str = "",
    ) -> dict[str, Any]:
        """`baseline_for` for every criterion of version `v`, each under its own scoring model
        (FR-PIPE-15). The caller supplies the run's part of the key and the package supplies each
        criterion's, so no consumer has to branch on the model (CT-AGG-09)."""
        out: dict[str, Any] = {}
        for row in self.criteria(v):
            model = str((row["scoring_model"] if "scoring_model" in row.keys() else "") or "")
            baseline = self.baseline_for(
                v, str(row["criterion_id"]), population_scope_id, backend_profile,
                panel_build_ref, model)
            if isinstance(baseline, NoValidationData) and model:
                # The undimensioned model key is the one `record_validation_baseline` writes by
                # default (promote names no model), so it is read when the criterion's own
                # model key holds nothing (#525 review).
                baseline = self.baseline_for(
                    v, str(row["criterion_id"]), population_scope_id, backend_profile,
                    panel_build_ref, "")
            out[str(row["criterion_id"])] = baseline
        return out

    def baseline_for(
        self, v: PackageVersionId, criterion_id: str, population_scope_id: str,
        backend_profile: str, panel_build_ref: str, scoring_model: str = "",
    ) -> Any:
        """One criterion's baseline band distribution, or `NoValidationData`.

        More detail: `docs/code-notes/pkg.md`, section `validation_reads.py: ValidationReadsMixin.baseline_for`.
        """
        rows = self._handle.query(PKG_STATEMENTS["select_validation_baseline"],
                                  v=v, criterion_id=criterion_id,
                                  population_scope_id=population_scope_id,
                                  backend_profile=backend_profile,
                                  panel_build_ref=panel_build_ref,
                                  scoring_model=scoring_model)
        if not rows:
            return NoValidationData()
        row = rows[0]
        if row["expected_mean"] is None or row["expected_sd"] is None:
            return NoValidationData()
        raw = row["expected_histogram"]
        return {
            "mean": float(row["expected_mean"]),
            "std": float(row["expected_sd"]),
            "histogram": json.loads(raw) if raw else {},
        }

    def manifest(self, v: PackageVersionId) -> Manifest:
        """The package manifest (FR-PKG-21): validation entries per population, the weakest
        criterion per population, worked-example provenance and the schema version, with no field
        that combines populations."""
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

    def noninferiority_for(
        self, v: PackageVersionId, *, criterion_id: str, population_scope_id: str = "",
        backend_profile: str = "", panel_build_ref: str = "", scoring_model: str = "",
    ) -> str | None:
        """The stored non-inferiority verdict on the criterion's validation record (FR-PKG-23):
        `'true'`, `'false'` or `'insufficient_data'`, or None when never measured. Independent of
        whether the row has an agreement figure."""
        rows = self._handle.query(
            PKG_STATEMENTS["select_validation_noninferiority"], v=v, criterion_id=criterion_id,
            population_scope_id=population_scope_id, backend_profile=backend_profile,
            panel_build_ref=panel_build_ref, scoring_model=scoring_model)
        return str(rows[0]["decision_engine_noninferior"]) if rows and rows[0][
            "decision_engine_noninferior"] is not None else None
