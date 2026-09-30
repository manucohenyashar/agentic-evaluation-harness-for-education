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
        """`baseline_for` for every criterion of `v`, each under its OWN declared scoring model
        (FR-PIPE-15, #525): the caller names the run's part of the key, and the package
        supplies the criterion's part, so no consumer branches on the model (CT-AGG-09)."""
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
        """`#373`: one criterion's baseline distribution, or `NoValidationData`.

        Shaped for `aeh.agg.should_escalate`'s ``baseline=`` argument — the keys are ``mean``
        and ``std``, the names it reads — so the figure this module stores reaches the rule
        that needs it without a caller in between reshaping (and possibly rescaling) it.

        **The signature mirrors `validation_for` deliberately**, down to the argument order
        and the `scoring_model` default, because it reads the SAME row under the same
        six-part key (`FR-PKG-08`). Naming the key is the caller's job here exactly as it is
        there: defaults on `backend_profile` and `panel_build_ref` would let a caller who
        names neither read back a `NoValidationData` for a baseline that IS stored, and
        `record_validation_baseline` writes both (they are the two parts `M-STATS` carries).
        `criterion_id` is required rather than optional — see the statement's own note.

        `NoValidationData` is returned for BOTH "no row" and "a row with no baseline", and
        the second case is the one that matters: a `validation_record` written by
        ``store_validation`` carries agreement and n but no baseline until an administration
        is promoted, and its three NULL columns are not a distribution. Returning the same
        sentinel `validation_for` returns keeps absence one type on this surface rather than
        two, and it is what makes the distributional-anomaly rule skip (`FR-AGG-08`) instead
        of dividing by a zero that was never measured.

        Named `baseline_for` rather than `validation_baseline` so the surface keeps
        `CT-PKG-07`'s prohibition legible: every public name carrying "validation" on this
        class is the keyed record read or its write, and nothing else.
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

    def noninferiority_for(
        self, v: PackageVersionId, *, criterion_id: str, population_scope_id: str = "",
        backend_profile: str = "", panel_build_ref: str = "", scoring_model: str = "",
    ) -> str | None:
        """FR-PKG-23 (#454): the recorded engine non-inferiority verdict on the criterion's
        validation record row — `'true'`, `'false'` or `'insufficient_data'` — or `None`
        when it was never measured (no row, or NULL). Independent of whether the row also
        carries an agreement figure: a promote records the verdict on its own."""
        rows = self._handle.query(
            PKG_STATEMENTS["select_validation_noninferiority"], v=v, criterion_id=criterion_id,
            population_scope_id=population_scope_id, backend_profile=backend_profile,
            panel_build_ref=panel_build_ref, scoring_model=scoring_model)
        return str(rows[0]["decision_engine_noninferior"]) if rows and rows[0][
            "decision_engine_noninferior"] is not None else None
