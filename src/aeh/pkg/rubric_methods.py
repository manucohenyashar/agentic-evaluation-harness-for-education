"""Rubric methods (`FR-PKG-24`, `FR-PKG-26`, `CT-PKG-21`, ADR-39): the composite shape and the
`general` criterion's derivation provenance.

Every method is composition over the ordinary banded criterion, so no judge, aggregator or
confidence path changes: a `bands` criterion is today's criterion; a `general` criterion is a
`bands` criterion whose band set was derived from the teacher's prose and confirmed by the
teacher; an `evidence_sum` criterion is a grouping record (no bands, no key) over 2-band aspect
criteria that name it in `component_of`. The method value is refused at the write
(`declared_score_method`); the shape spans the whole version, so it is checked at publish,
before the lock flips — a refused publish is a no-op (`CT-PKG-11`).
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from .errors import PackageError
from .statements import PKG_STATEMENTS
from .vocabulary import SCORE_METHODS, PackageVersionId

#: The one method that composes others, and the methods that stand alone.
COMPOSITE_METHOD = "evidence_sum"
GENERAL_METHOD = "general"
#: An aspect is binary: absent / present (`FR-PKG-24`).
ASPECT_BAND_COUNT = 2

_CLOSED_SET = "{" + ", ".join(SCORE_METHODS) + "}"


def _row_field(row: Any, name: str) -> Any:
    """One column of a criterion row, whatever its shape (`sqlite3.Row`, dict or object); a
    row from before Package migration 15 has no such column and reads as None."""
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, None)


def is_composite(row: Any) -> bool:
    """Whether a criterion row declares the composite method (`evidence_sum`). A composite is a
    grouping record: never a score unit (`FR-JUDGE-38`), never a grade input of its own — its
    points are its aspects' sum (`FR-PKG-25`). The one predicate every consumer asks."""
    return _row_field(row, "score_method") == COMPOSITE_METHOD


def composite_aspects(rows: Sequence[Any]) -> dict[str, tuple[str, ...]]:
    """Each composite criterion of a version's criterion rows, mapped to its aspect criterion
    ids (those naming it in `component_of`), sorted. A version with none maps to `{}`."""
    aspects: dict[str, tuple[str, ...]] = {
        str(_row_field(row, "criterion_id")): () for row in rows if is_composite(row)
    }
    for row in rows:
        parent = _row_field(row, "component_of")
        if parent is not None and str(parent) in aspects:
            aspects[str(parent)] += (str(_row_field(row, "criterion_id")),)
    return {cid: tuple(sorted(ids)) for cid, ids in aspects.items()}


def _band_tuple(band: Mapping[str, Any]) -> tuple[int, str, float, str]:
    """A band as (ordinal, band, points, descriptor), the form two band sets compare in."""
    return (int(band["ordinal"]), str(band["band"]), float(band["points"]),
            str(band.get("descriptor") or ""))


def _has_key(answer_key: Any) -> bool:
    return answer_key not in (None, "", "[]")


class RubricMethodsMixin:
    """The derivation-and-confirmation surface and the publish-time shape check."""

    # -- the `general` derivation (FR-PKG-26, FR-SETUP-18) -------------------------------------

    def record_derivation(
        self, v: PackageVersionId, criterion_id: str, *, description: str,
        derived_bands: Sequence[Mapping[str, Any]], recorded_at: str,
    ) -> None:
        """Record the system-derived band set of a `general` criterion beside the teacher's
        prose description. Recording again replaces the derivation and clears any
        confirmation: the teacher confirms one derived set, never a later one."""
        if not isinstance(description, str) or not description.strip():
            raise PackageError(
                f"general criterion {criterion_id!r}: the derivation needs the teacher's "
                "description — the provenance is the prose the bands were derived from "
                "(FR-PKG-26)."
            )
        bands = self._normalized_derived_bands(criterion_id, derived_bands)
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion_derivation.record")
            self._require_general(tx, v, criterion_id)
            tx.execute(PKG_STATEMENTS["upsert_criterion_derivation"],
                       v=v, criterion_id=criterion_id, description=description,
                       derived_bands=json.dumps(bands, sort_keys=True),
                       recorded_at=recorded_at)
        self._invalidate()

    def confirm_derivation(
        self, v: PackageVersionId, criterion_id: str, *, confirmed_by: str,
        confirmed_at: str,
    ) -> None:
        """The teacher's confirmation of the recorded derivation — what makes a `general`
        criterion publishable (CT-SETUP-17's gate, held at the data layer)."""
        if not isinstance(confirmed_by, str) or not confirmed_by.strip():
            raise PackageError(
                f"general criterion {criterion_id!r}: a confirmation names who confirmed "
                "the derived band set (FR-PKG-26)."
            )
        with self._handle.transaction() as tx:
            self._guard(tx, v, "criterion_derivation.confirm")
            recorded = {row["criterion_id"] for row in tx.execute(
                PKG_STATEMENTS["select_criterion_derivations"], v=v)}
            if criterion_id not in recorded:
                raise PackageError(
                    f"general criterion {criterion_id!r} has no recorded derivation to "
                    "confirm: record_derivation comes first (FR-PKG-26)."
                )
            tx.execute(PKG_STATEMENTS["confirm_criterion_derivation"], v=v,
                       criterion_id=criterion_id, confirmed_by=confirmed_by,
                       confirmed_at=confirmed_at)
        self._invalidate()

    def derivation(self, v: PackageVersionId, criterion_id: str) -> dict | None:
        """The stored provenance of a `general` criterion — `description`, `derived_bands`
        (ordinal order), `recorded_at`, `confirmed_by`, `confirmed_at` — or None."""
        return self._derivations(v).get(criterion_id)

    def _derivations(self, v: PackageVersionId) -> dict[str, dict]:
        found: dict[str, dict] = {}
        for row in self._handle.query(PKG_STATEMENTS["select_criterion_derivations"], v=v):
            record = dict(row)
            record["derived_bands"] = tuple(json.loads(record["derived_bands"]))
            found[record["criterion_id"]] = record
        return found

    def _require_general(self, tx, v: PackageVersionId, criterion_id: str) -> None:
        rows = [row for row in tx.execute(PKG_STATEMENTS["select_criteria"], v=v)
                if row["criterion_id"] == criterion_id]
        if not rows:
            raise PackageError(
                f"criterion {criterion_id!r} does not exist in version {v!r}; a "
                "derivation is recorded for an existing general criterion (FR-PKG-26)."
            )
        if rows[0]["score_method"] != GENERAL_METHOD:
            raise PackageError(
                f"criterion {criterion_id!r} declares score_method "
                f"{rows[0]['score_method']!r}: only a general criterion carries a "
                "derivation (FR-PKG-26)."
            )

    def _normalized_derived_bands(
        self, criterion_id: str, derived_bands: Sequence[Mapping[str, Any]],
    ) -> list[dict]:
        """The derived set as stored: ordinal order, every band rule of FR-PKG-06 applied —
        a derivation the teacher could confirm but the publish could never accept is not
        worth recording."""
        try:
            bands = sorted(
                ({"ordinal": int(b["ordinal"]), "band": str(b["band"]),
                  "points": float(b["points"]), "descriptor": str(b.get("descriptor") or "")}
                 for b in derived_bands),
                key=lambda b: b["ordinal"])
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise PackageError(
                f"general criterion {criterion_id!r}: each derived band needs ordinal, band "
                f"and points ({error}) (FR-PKG-26)."
            ) from error
        self._validate_band_order(bands)
        self._validate_band_count(len(bands))
        return bands

    # -- the publish-time shape check (FR-PKG-24, FR-PKG-26, CT-PKG-21) ------------------------

    def _validate_score_methods(self, v: PackageVersionId) -> None:
        """Refuse a version whose rubric methods break CT-PKG-21's shape, naming every
        offending criterion and the shape it breaks."""
        criteria = {row["criterion_id"]: dict(row) for row in self._handle.query(
            PKG_STATEMENTS["select_criteria"], v=v)}
        bands: dict[str, list[dict]] = {}
        for row in self._handle.query(PKG_STATEMENTS["select_bands"], v=v):
            bands.setdefault(row["criterion_id"], []).append(dict(row))
        derivations = self._derivations(v)
        problems: list[str] = []
        for criterion_id, row in criteria.items():
            problems += self._criterion_shape_problems(
                criterion_id, row, criteria, bands, derivations)
        if problems:
            raise PackageError(
                f"package version {v!r} is not publishable: its rubric methods break the "
                "declared shape (FR-PKG-24, FR-PKG-26, CT-PKG-21): " + "; ".join(problems)
            )

    def _criterion_shape_problems(
        self, criterion_id: str, row: dict, criteria: dict[str, dict],
        bands: dict[str, list[dict]], derivations: dict[str, dict],
    ) -> list[str]:
        method = row["score_method"]
        if method not in SCORE_METHODS:
            return [f"criterion {criterion_id!r} declares score_method {method!r}, outside "
                    f"the closed set {_CLOSED_SET}"]
        if method == COMPOSITE_METHOD:
            return _composite_problems(criterion_id, row, criteria, bands)
        problems: list[str] = []
        if row["component_of"] is not None:
            problems += _aspect_problems(criterion_id, row, criteria, bands)
        if method == GENERAL_METHOD:
            problems += _general_problems(criterion_id, bands, derivations)
        return problems


def _composite_problems(criterion_id: str, row: dict, criteria: dict[str, dict],
                        bands: dict[str, list[dict]]) -> list[str]:
    """An `evidence_sum` criterion: a grouping record, never an aspect, no band set, no key,
    at least one aspect naming it."""
    label = f"composite (evidence_sum) criterion {criterion_id!r}"
    problems: list[str] = []
    if row["component_of"] is not None:
        problems.append(f"{label} names component_of {row['component_of']!r}, but a "
                        "composite is never itself an aspect")
    carried = len(bands.get(criterion_id, ()))
    if carried or row["band_count"] is not None:
        problems.append(f"{label} carries a band set ({carried} band(s)); a composite carries "
                        "no bands — its aspects do")
    if _has_key(row["answer_key"]):
        problems.append(f"{label} carries an answer key; a composite carries none")
    if not any(other["component_of"] == criterion_id for other in criteria.values()):
        problems.append(f"{label} has no aspect criteria; it needs at least one 2-band "
                        "aspect whose component_of names it (FR-JUDGE-38)")
    return problems


def _aspect_problems(criterion_id: str, row: dict, criteria: dict[str, dict],
                     bands: dict[str, list[dict]]) -> list[str]:
    """A criterion with `component_of` set: a 2-band `bands` aspect of an existing composite.
    A `general` criterion is standalone by definition (CT-PKG-21: component_of NULL)."""
    target = row["component_of"]
    problems: list[str] = []
    if row["score_method"] == GENERAL_METHOD:
        problems.append(f"general criterion {criterion_id!r} names component_of {target!r}; "
                        "bands and general criteria are standalone (component_of NULL) — an "
                        "aspect is a 2-band bands criterion")
    parent = criteria.get(target)
    if parent is None or parent["score_method"] != COMPOSITE_METHOD:
        problems.append(f"criterion {criterion_id!r} has component_of {target!r}, which is not "
                        "an evidence_sum (composite) criterion of this version; an aspect "
                        "names its composite")
    carried = len(bands.get(criterion_id, ()))
    if carried != ASPECT_BAND_COUNT:
        problems.append(f"aspect criterion {criterion_id!r} carries {carried} band(s); an "
                        f"aspect is exactly {ASPECT_BAND_COUNT} bands (absent / present)")
    return problems


def _general_problems(criterion_id: str, bands: dict[str, list[dict]],
                      derivations: dict[str, dict]) -> list[str]:
    """A `general` criterion publishes only with a confirmed derivation whose band set IS the
    stored band set (FR-PKG-26: the stored form is a bands criterion with that provenance)."""
    label = f"general criterion {criterion_id!r}"
    record = derivations.get(criterion_id)
    if record is None:
        return [f"{label} has no recorded derivation; a general criterion is created only "
                "through the derivation-and-confirmation flow"]
    if record["confirmed_at"] is None:
        return [f"{label} has a derivation the teacher has not confirmed"]
    stored = sorted(_band_tuple(b) for b in bands.get(criterion_id, ()))
    derived = sorted(_band_tuple(b) for b in record["derived_bands"])
    if stored != derived:
        return [f"{label} stores bands unlike its confirmed derived bands; re-derive and "
                "confirm the bands it carries"]
    return []
