"""The structural checks on the confirmed inventory and the read-back before they are written."""

from __future__ import annotations

import math
from typing import Mapping, Sequence

from .vocabulary import _declared_evaluation_mode, QUESTION_TYPES
from .errors import BandSetError, InventoryError, PackageError


class SetupChecksMixin:
    """Validates the structure of an inventory or read-back before it is written."""

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
                # `FR-SETUP-17`/`FR-PKG-22`: validated HERE so the declaration survives
                # into the write. This dict is what `write_readback` binds from, so a key
                # dropped here is a declaration the caller cannot make — and the mode
                # would then be re-derived from `kind`, which is precisely the
                # shape-decides-evaluation reading this story retires. Validating it here
                # also makes the vocabulary refusal reachable instead of dead.
                "evaluation_mode": _declared_evaluation_mode(record),
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
