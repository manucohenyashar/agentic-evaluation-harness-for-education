"""The `evidence_sum` rubric method: the evidence-checklist builder (`FR-SETUP-19`, ADR-39).

The teacher names the aspects of a criterion and what each is worth; setup generates one
binary (absent / present) aspect criterion per aspect, its descriptors derived from the
aspect's name — deterministically, no model call — and editable before confirmation. An
aspect the teacher describes with more than two levels fails the decomposability test in
reverse: it is proposed for promotion to a standalone `bands` criterion, never created as an
aspect with more than two bands.

On confirmation the composite (`score_method='evidence_sum'`, no bands, no key) and its
aspects (`component_of` naming it, two bands each) are written; until then the draft is a
pending record and publish refuses, naming the criterion.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from aeh.pkg import PackageVersionId

from .settings import LOGGER, _now, SETUP_EVIDENCE_TYPE_DEFAULT
from .errors import SetupError, SetupOrderError
from .records import AspectDraft, AspectPromotion, EvidenceSumDraft, ProposedBand
from .method_drafts import (
    bands_from_json,
    bands_to_json,
    CONFIRMED,
    EVIDENCE_SUM_STEP_PREFIX,
    GENERAL_STEP_PREFIX,
    PENDING,
    text_offense,
)

COMPOSITE_METHOD = "evidence_sum"
PROMOTED_METHOD = "bands"
#: An aspect is binary (`FR-PKG-24`); a teacher-described aspect with more levels than this
#: is proposed for promotion instead.
ASPECT_LEVELS = 2
ABSENT_LABEL, PRESENT_LABEL = "absent", "present"
#: Neither the composite (never judged, FR-JUDGE-38) nor an aspect is classified by the
#: §5.3 table; NFR-SETUP-02's asymmetric default applies.
METHOD_SCORING_MODEL = "holistic"


def aspect_criterion_id(composite_id: str, position: int) -> str:
    """The generated id of the composite's aspect at `position` (from 1)."""
    return f"{composite_id}-a{position}"


def _aspect_bands(name: str, points: float,
                  levels: Sequence[str]) -> tuple[ProposedBand, ...]:
    """The aspect's two bands. Descriptors derive from the aspect's name, or are the teacher's
    own two levels (lower first) when given."""
    absent, present = (levels if len(levels) == ASPECT_LEVELS
                       else (f"Does not show {name}.", f"Shows {name}."))
    return (ProposedBand(band=ABSENT_LABEL, ordinal=0, points=0.0, descriptor=absent),
            ProposedBand(band=PRESENT_LABEL, ordinal=1, points=points, descriptor=present))


def _parse_aspect(criterion_id: str, raw: Any) -> tuple[str, float, tuple[str, ...]]:
    """(name, points, levels) of one teacher-named aspect, or `SetupError` naming the fault.
    The name becomes descriptor text a judge reads, so it passes the rubric-surface scan."""
    if not isinstance(raw, Mapping):
        raise SetupError(f"evidence-sum criterion {criterion_id!r}: each aspect is a mapping "
                         "with a name and its points (FR-SETUP-19).")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise SetupError(f"evidence-sum criterion {criterion_id!r}: an aspect has no name.")
    try:
        points = float(raw.get("points"))
    except (TypeError, ValueError) as error:
        raise SetupError(f"aspect {name!r}: its points are not a number.") from error
    if not math.isfinite(points) or points <= 0:
        raise SetupError(f"aspect {name!r}: an aspect is worth more than nothing "
                         f"(got {points}).")
    levels = tuple(str(level).strip() for level in (raw.get("levels") or ()))
    for text in (name, *levels):
        offense = text_offense(text)
        if offense is not None:
            raise SetupError(f"aspect {name!r}: {text!r} carries {offense} — the aspect's "
                             "descriptors are judge-facing text (FR-JUDGE-03).")
    return name, points, levels


class EvidenceSumMixin:
    """`build_evidence_sum`, `evidence_sum_draft`, `set_aspect_descriptor`,
    `confirm_evidence_sum`."""

    def build_evidence_sum(self, criterion_id: str, *, question_id: str,
                           aspects: Sequence[Mapping[str, Any]]) -> EvidenceSumDraft:
        """Generate the composite's aspect criteria from the teacher's aspects (`FR-SETUP-19`):
        `aspects` is a sequence of `{"name", "points"}`, plus `"levels"` for an aspect the
        teacher describes with levels. More than two levels → a promotion proposal, not an
        aspect. Rebuilding a pending draft replaces it; a pending `general` card for the same
        id is superseded — the teacher chose another method."""
        v = self._require_draft_version()
        self._method_question(v, question_id)
        parsed = [_parse_aspect(criterion_id, raw) for raw in aspects]
        names = [name.lower() for name, _points, _levels in parsed]
        if not parsed or len(set(names)) != len(names):
            raise SetupError(f"evidence-sum criterion {criterion_id!r}: name at least one "
                             "aspect, each once (FR-SETUP-19).")
        built: list[AspectDraft] = []
        promotions: list[AspectPromotion] = []
        for name, points, levels in parsed:
            if len(levels) > ASPECT_LEVELS:
                promotions.append(AspectPromotion(
                    aspect=name, points=points, levels=levels, score_method=PROMOTED_METHOD,
                    reason=f"described with {len(levels)} levels; an aspect is present or "
                    "absent, so this is a standalone banded criterion (FR-SETUP-19)"))
                continue
            built.append(AspectDraft(
                criterion_id=aspect_criterion_id(criterion_id, len(built) + 1), name=name,
                points=points, bands=_aspect_bands(name, points, levels)))
        self._require_unused_ids(v, [criterion_id] + [a.criterion_id for a in built])
        step_id = EVIDENCE_SUM_STEP_PREFIX + criterion_id
        earlier = self._method_record(v, step_id)
        if earlier is not None and earlier["status"] == CONFIRMED:
            raise SetupOrderError(f"evidence-sum criterion {criterion_id!r} is already "
                                  "confirmed.")
        draft = EvidenceSumDraft(criterion_id=criterion_id, question_id=question_id,
                                 aspects=tuple(built), promotions=tuple(promotions),
                                 confirmed=False, confirmed_by=None)
        recorded_at = _now()
        self._supersede(v, GENERAL_STEP_PREFIX + criterion_id, recorded_at)
        self._write_method_record(v, step_id, PENDING, _draft_payload(draft), recorded_at)
        LOGGER.info("built evidence-sum criterion %s of version %s: %d aspect(s), %d "
                    "promotion proposal(s)", criterion_id, v, len(built), len(promotions))
        return draft

    def evidence_sum_draft(self, criterion_id: str) -> EvidenceSumDraft:
        """The stored draft, for a resuming console."""
        v = self._require_draft_version()
        record = self._method_record(v, EVIDENCE_SUM_STEP_PREFIX + criterion_id)
        if record is None or record["status"] not in (PENDING, CONFIRMED):
            raise SetupError(f"no evidence-sum draft is staged for criterion "
                             f"{criterion_id!r} in version {v!r}.")
        return _draft_from_payload(record["payload"])

    def set_aspect_descriptor(self, criterion_id: str, aspect_criterion_id: str, *,
                              ordinal: int, descriptor: str) -> EvidenceSumDraft:
        """The teacher's own wording for one generated descriptor, before confirmation
        (`FR-SETUP-19`). The text is judge-facing, so it passes the rubric-surface scan."""
        v = self._require_draft_version()
        draft = self._pending_draft(v, criterion_id)
        text = str(descriptor or "").strip()
        offense = text_offense(text) if text else "no text at all"
        if offense is not None:
            raise SetupError(f"aspect {aspect_criterion_id!r}: the descriptor {text!r} "
                             f"carries {offense} (FR-JUDGE-03).")
        aspects = []
        found = False
        for aspect in draft.aspects:
            if aspect.criterion_id == aspect_criterion_id:
                if ordinal not in range(len(aspect.bands)):
                    raise SetupError(f"aspect {aspect_criterion_id!r} has no band "
                                     f"ordinal {ordinal}.")
                found = True
                aspect = AspectDraft(
                    criterion_id=aspect.criterion_id, name=aspect.name, points=aspect.points,
                    bands=tuple(ProposedBand(band=b.band, ordinal=b.ordinal, points=b.points,
                                             descriptor=text if b.ordinal == ordinal
                                             else b.descriptor) for b in aspect.bands))
            aspects.append(aspect)
        if not found:
            raise SetupError(f"evidence-sum criterion {criterion_id!r} has no aspect "
                             f"{aspect_criterion_id!r}.")
        updated = EvidenceSumDraft(criterion_id=draft.criterion_id,
                                   question_id=draft.question_id, aspects=tuple(aspects),
                                   promotions=draft.promotions, confirmed=False,
                                   confirmed_by=None)
        self._write_method_record(v, EVIDENCE_SUM_STEP_PREFIX + criterion_id, PENDING,
                                  _draft_payload(updated), _now())
        return updated

    def confirm_evidence_sum(self, criterion_id: str, *,
                             confirmed_by: str) -> EvidenceSumDraft:
        """The teacher's confirmation: the composite and its aspect criteria are written, and
        the draft stops holding publish. A draft whose every aspect was proposed for promotion
        has nothing to sum and is refused."""
        v = self._require_draft_version()
        if not isinstance(confirmed_by, str) or not confirmed_by.strip():
            raise SetupError(f"evidence-sum criterion {criterion_id!r}: a confirmation names "
                             "who confirmed it.")
        draft = self._pending_draft(v, criterion_id)
        if not draft.aspects:
            raise SetupError(f"evidence-sum criterion {criterion_id!r} has no aspects left to "
                             "sum — every aspect was proposed for promotion; set those up as "
                             "standalone criteria instead (FR-SETUP-19).")
        self._require_unused_ids(v, [criterion_id] + [a.criterion_id for a in draft.aspects])
        recorded_at = _now()
        self._write_composite(v, draft, recorded_at)
        confirmed = EvidenceSumDraft(criterion_id=draft.criterion_id,
                                     question_id=draft.question_id, aspects=draft.aspects,
                                     promotions=draft.promotions, confirmed=True,
                                     confirmed_by=confirmed_by)
        self._write_method_record(v, EVIDENCE_SUM_STEP_PREFIX + criterion_id, CONFIRMED,
                                  _draft_payload(confirmed), recorded_at)
        LOGGER.info("evidence-sum criterion %s of version %s confirmed by %r: %d aspect(s)",
                    criterion_id, v, confirmed_by, len(draft.aspects))
        return confirmed

    # -- internals -------------------------------------------------------------------------

    def _pending_draft(self, v: PackageVersionId, criterion_id: str) -> EvidenceSumDraft:
        record = self._method_record(v, EVIDENCE_SUM_STEP_PREFIX + criterion_id)
        if record is None or record["status"] != PENDING:
            raise SetupOrderError(f"evidence-sum criterion {criterion_id!r} has no draft "
                                  "awaiting confirmation: build_evidence_sum first.")
        return _draft_from_payload(record["payload"])

    def _write_composite(self, v: PackageVersionId, draft: EvidenceSumDraft,
                         recorded_at: str) -> None:
        """The composite (a grouping record: no bands, no key, no evidence type — it is never
        judged) and each aspect, a 2-band criterion naming it in `component_of`."""
        self._catalog.add_criterion(
            v, draft.criterion_id, question_id=draft.question_id, kind="open",
            max_points=draft.max_points, scoring_model=METHOD_SCORING_MODEL,
            score_method=COMPOSITE_METHOD)
        for aspect in draft.aspects:
            self._catalog.add_criterion(
                v, aspect.criterion_id, question_id=draft.question_id, kind="open",
                max_points=aspect.points, scoring_model=METHOD_SCORING_MODEL,
                band_count=len(aspect.bands), evidence_type=SETUP_EVIDENCE_TYPE_DEFAULT,
                construct_tag=aspect.name, component_of=draft.criterion_id)
            for band in aspect.bands:
                self._catalog.add_band(v, aspect.criterion_id, band.ordinal, band.band,
                                       band.points, band.descriptor)
            self._record_method_classification(v, aspect.criterion_id,
                                               METHOD_SCORING_MODEL, recorded_at)


def _draft_payload(draft: EvidenceSumDraft) -> dict:
    return {
        "criterion_id": draft.criterion_id, "question_id": draft.question_id,
        "aspects": [{"criterion_id": a.criterion_id, "name": a.name, "points": a.points,
                     "bands": bands_to_json(a.bands)} for a in draft.aspects],
        "promotions": [{"aspect": p.aspect, "points": p.points, "levels": list(p.levels),
                        "score_method": p.score_method, "reason": p.reason}
                       for p in draft.promotions],
        "confirmed_by": draft.confirmed_by,
    }


def _draft_from_payload(payload: Mapping[str, Any]) -> EvidenceSumDraft:
    return EvidenceSumDraft(
        criterion_id=str(payload["criterion_id"]),
        question_id=str(payload["question_id"]),
        aspects=tuple(AspectDraft(criterion_id=str(a["criterion_id"]), name=str(a["name"]),
                                  points=float(a.get("points")), bands=bands_from_json(a["bands"]))
                      for a in payload["aspects"]),
        promotions=tuple(AspectPromotion(aspect=str(p["aspect"]), points=float(p.get("points")),
                                         levels=tuple(p["levels"]),
                                         score_method=str(p["score_method"]),
                                         reason=str(p["reason"]))
                         for p in payload["promotions"]),
        confirmed=payload.get("confirmed_by") is not None,
        confirmed_by=payload.get("confirmed_by"),
    )
