"""What the two rubric-method flows share: the pending record, the band-set check, the gate.

Both flows (`general_derivation.py`, `evidence_sum.py`) hold their work as a PENDING setup
step record — one per criterion — and write criterion and band rows only when the teacher
confirms. The reason is M-PKG's draft surface: a criterion row cannot be removed and a band
cannot be deleted, so rows staged before confirmation would be stranded by an edit that
changes the band count or by the teacher switching method. A pending record carries the
whole card, so a resuming console renders it without calling the model again (CT-SETUP-03).

The blocking gate (`CT-SETUP-17`, and its evidence-sum twin) reads those records: a
criterion whose record is still `pending` refuses publish, named.
"""

from __future__ import annotations

import json
import math
from typing import Any, Mapping, Sequence

from aeh.pkg import PackageVersionId

from .settings import DEFAULT_RUBRIC_METHOD, RUBRIC_METHOD_CHOICES
from .errors import SetupError, SetupOrderError
from .records import ProposedBand, RubricMethodChoice
from .readback import _descriptor_offense as text_offense

#: The step-record id prefixes, one record per criterion: `<prefix><criterion id>`.
GENERAL_STEP_PREFIX = "rubric_method.general:"
EVIDENCE_SUM_STEP_PREFIX = "rubric_method.evidence_sum:"

#: A method record's lifecycle. `superseded` is a pending record the teacher abandoned by
#: choosing the other method for the same criterion: it holds no gate.
PENDING = "pending"
CONFIRMED = "confirmed"
SUPERSEDED = "superseded"

#: FR-PKG-06's band-count rule, checked here so a set the catalog would refuse is caught
#: (and, for a model reply, re-requested) before the teacher is asked to confirm it.
MIN_BANDS, MAX_BANDS = 2, 6


def typed_bands(raw_bands: Any) -> tuple[ProposedBand, ...]:
    """A band set from mappings, in the stored order (`FR-PKG-06`): points ascending, the
    given ordinal breaking ties, ordinals renumbered from 0. Raises `ValueError` naming what
    is malformed; callers turn that into a re-request or a `SetupError`."""
    if not isinstance(raw_bands, (list, tuple)) or not raw_bands:
        raise ValueError("the band set is empty or not a list")
    typed: list[tuple[float, int, ProposedBand]] = []
    for position, raw in enumerate(raw_bands):
        if not isinstance(raw, Mapping):
            raise ValueError(f"band {position} is not an object")
        try:
            points = float(raw["points"])
            label = str(raw["band"]).strip()
            descriptor = str(raw.get("descriptor") or "").strip()
            given = int(raw.get("ordinal", position))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"band {position} needs band, points and descriptor "
                             f"({error})") from error
        typed.append((points, given, ProposedBand(band=label, ordinal=given,
                                                  points=points, descriptor=descriptor)))
    typed.sort(key=lambda entry: (entry[0], entry[1]))
    return tuple(
        ProposedBand(band=band.band, ordinal=ordinal, points=band.points,
                     descriptor=band.descriptor)
        for ordinal, (_points, _given, band) in enumerate(typed)
    )


def band_set_problems(bands: Sequence[ProposedBand], max_points: float) -> list[str]:
    """Every reason a band set cannot be shown for confirmation: FR-PKG-06's even count and
    non-negative points, a label and a descriptor on every band, distinct labels, the top
    band at the question's maximum (when the inventory states one), and the rubric-surface
    scan over every label and descriptor (`RISK-112`: the scan runs on derivation OUTPUT)."""
    problems: list[str] = []
    count = len(bands)
    if count < MIN_BANDS or count > MAX_BANDS or count % 2:
        problems.append(f"{count} band(s): a band set has an even count, at least "
                        f"{MIN_BANDS} and at most {MAX_BANDS} (FR-PKG-06)")
    labels = [band.band.lower() for band in bands]
    if len(set(labels)) != len(labels):
        problems.append("two bands share a label")
    for band in bands:
        if not math.isfinite(band.points) or band.points < 0:
            problems.append(f"band {band.band!r} has points {band.points}")
        for name, text in (("label", band.band), ("descriptor", band.descriptor)):
            if not text:
                problems.append(f"a band has an empty {name}")
                continue
            offense = text_offense(text)
            if offense is not None:
                problems.append(f"the {name} {text!r} carries {offense} (FR-JUDGE-03)")
    if bands and max_points > 0 and not math.isclose(bands[-1].points, max_points):
        problems.append(f"the top band is worth {bands[-1].points}, not the question's "
                        f"maximum of {max_points}")
    return problems


def bands_to_json(bands: Sequence[ProposedBand]) -> list[dict]:
    return [{"ordinal": b.ordinal, "band": b.band, "points": b.points,
             "descriptor": b.descriptor} for b in bands]


def bands_from_json(rows: Sequence[Mapping[str, Any]]) -> tuple[ProposedBand, ...]:
    return tuple(ProposedBand(band=str(r["band"]), ordinal=int(r["ordinal"]),
                              points=float(r["points"]), descriptor=str(r["descriptor"]))
                 for r in rows)


class MethodDraftsMixin:
    """The method choices, the pending-record store, and the publish gate over it."""

    def rubric_method_choices(self) -> tuple[RubricMethodChoice, ...]:
        """The rubric methods a criterion can take, in teacher language, `bands` the default
        (`FR-SETUP-18`)."""
        return tuple(RubricMethodChoice(score_method=method, label=label,
                                        default=method == DEFAULT_RUBRIC_METHOD)
                     for method, label in RUBRIC_METHOD_CHOICES)

    # -- the pending records ---------------------------------------------------------------

    def _method_record(self, v: PackageVersionId, step_id: str) -> dict | None:
        """One method record's status and payload, or None when there is none. A payload that
        does not parse is a `SetupError`: the record is provenance, never silently replaced."""
        row = self._catalog.step_record(v, step_id)
        if row is None:
            return None
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError) as error:
            raise SetupError(f"the stored rubric-method record {step_id!r} of version "
                             f"{v!r} is malformed ({error}).") from error
        return {"status": str(row["status"]), "payload": payload,
                "recorded_at": row["recorded_at"]}

    def _write_method_record(self, v: PackageVersionId, step_id: str, status: str,
                             payload: Mapping[str, Any], recorded_at: str) -> None:
        self._catalog.record_step(v, step_id=step_id, status=status,
                                  payload=json.dumps(payload, sort_keys=True),
                                  recorded_at=recorded_at)

    def _pending_method_criteria(self, v: PackageVersionId) -> dict[str, list[str]]:
        """The criteria whose method is still awaiting the teacher, by method. A catalog
        without the step-record surface (a rung-0 double) has none."""
        reader = getattr(self._catalog, "step_records", None)
        pending: dict[str, list[str]] = {"general": [], "evidence_sum": []}
        if reader is None:
            return pending
        for row in reader(v):
            if row["status"] != PENDING:
                continue
            step_id = str(row["step_id"])
            if step_id.startswith(GENERAL_STEP_PREFIX):
                pending["general"].append(step_id[len(GENERAL_STEP_PREFIX):])
            elif step_id.startswith(EVIDENCE_SUM_STEP_PREFIX):
                pending["evidence_sum"].append(step_id[len(EVIDENCE_SUM_STEP_PREFIX):])
        return pending

    def _refuse_pending_methods(self, v: PackageVersionId) -> None:
        """The blocking read-back gate (`FR-SETUP-18`, `CT-SETUP-17`): refuse publish while any
        `general` derivation — or evidence-sum draft — awaits the teacher, naming each."""
        pending = self._pending_method_criteria(v)
        reasons = []
        if pending["general"]:
            reasons.append(
                "the derived band set of the general criteria "
                f"{', '.join(sorted(pending['general']))} is not confirmed — the "
                "derivation read-back card is blocking (FR-SETUP-18, CT-SETUP-17): "
                "confirm_general_derivation first")
        if pending["evidence_sum"]:
            reasons.append(
                "the evidence checklists of the criteria "
                f"{', '.join(sorted(pending['evidence_sum']))} are not confirmed "
                "(FR-SETUP-19): confirm_evidence_sum first")
        if reasons:
            raise SetupOrderError("publish refused: " + "; ".join(reasons) + ".")

    # -- the shared preconditions ----------------------------------------------------------

    def _method_question(self, v: PackageVersionId, question_id: str) -> dict:
        """The confirmed question a method criterion attaches to. Gate 1 first: a criterion
        anchors to a confirmed question (FR-SETUP-02)."""
        stored = self._catalog.proposal(v)
        if stored is None or not stored["confirmed_at"]:
            raise SetupOrderError(
                f"the inventory for version {v!r} is not confirmed yet — a rubric-method "
                "criterion anchors to a confirmed question, so gate 1 (§4.2.1) comes first "
                "(FR-SETUP-02).")
        for row in self._catalog.questions(v):
            if row["question_id"] == question_id:
                return dict(row)
        raise SetupError(f"question {question_id!r} is not in the confirmed inventory of "
                         f"version {v!r}.")

    def _require_unused_ids(self, v: PackageVersionId, criterion_ids: Sequence[str]) -> None:
        """Refuse a criterion id the draft already carries: a method criterion is a new
        criterion, and M-PKG cannot replace one."""
        existing = {row["criterion_id"] for row in self._catalog.criteria(v)}
        taken = [cid for cid in criterion_ids if cid in existing]
        if taken:
            raise SetupOrderError(
                f"criterion id(s) {', '.join(taken)} already exist in version {v!r}; a "
                "rubric-method criterion is a new criterion with an unused id.")

    def _supersede(self, v: PackageVersionId, step_id: str, recorded_at: str) -> None:
        """Mark the other method's pending record for the same criterion superseded: the
        teacher chose a different method, so its card no longer holds the gate. A confirmed
        record is not touched — its criterion exists, and `_require_unused_ids` refuses."""
        record = self._method_record(v, step_id)
        if record is not None and record["status"] == PENDING:
            self._write_method_record(v, step_id, SUPERSEDED, record["payload"],
                                      recorded_at)

    def _record_method_classification(self, v: PackageVersionId, criterion_id: str,
                                      classification: str, recorded_at: str) -> None:
        """The R62 audit row the read back writes for its criteria, for a method criterion:
        the default classification, source `default`."""
        recorder = getattr(self._catalog, "record_classification", None)
        if recorder is not None:
            recorder(v, criterion_id=criterion_id, classification=classification,
                     decomposition_basis=None, source="default", recorded_at=recorded_at)
