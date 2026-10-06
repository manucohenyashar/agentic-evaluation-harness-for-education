"""The M-SETUP rubric-method flows, as the TS-145 cases drive them (#623, written ahead of #624).

`TC-SETUP-24`, `TC-SETUP-25` and `TC-SETUP-C17` (operator-requirements test plan §5.5) drive the
setup flow's two new teacher-facing steps:

* the `general` derivation read-back (`FR-SETUP-18`, `CT-SETUP-17`): the teacher's prose
  description goes to the setup model, which derives a band set; the card shows it back; nothing
  publishes until the teacher confirms it (as derived, or edited);
* the evidence-sum builder (`FR-SETUP-19`): the teacher names aspects and per-aspect points, setup
  generates one 2-band aspect criterion per aspect (descriptors derived from the aspect name,
  editable before confirmation), and an aspect that needs levels is proposed for promotion to a
  standalone `bands` criterion instead.

**The interface below is invented, and invented here once.** The design
(`operator_requirements_design_delta.md` §3.6) fixes the behaviour and the data model
(`criterion.score_method`, `criterion.component_of`, Package migration 15) but names no Python
surface for either step. Every assumed name lives in THIS file; the test bodies call the helpers
below and assert on `SetupService.publish`, `PackageCatalog.is_locked` and raw `.pkg.sqlite` rows.
If #624 lands different names, this is the one file to re-point (and the `WRITTEN_AHEAD_BLOCKERS`
entry keyed on all six members with it). The vocabulary follows #621's
`tests/support/rubric_methods.py` (PR #643): `description`, a band as `ordinal / band / points /
descriptor`, `confirmed_by`, `score_method`, `component_of`.

Assumed `SetupService` members (#624):

* `derive_general_bands(criterion_id, *, question_id, description)` — calls the setup model with
  the teacher's description and stages a `general` criterion on the draft. Returns the card: a
  record (attributes or mapping keys) carrying `criterion_id`, `description`, `bands` (each with
  `ordinal`, `band`, `points`, `descriptor`) and `confirmed` (False). A reply it cannot accept —
  a descriptor carrying a numeral (`RISK-112`) — is re-requested within an attempt budget or
  refused with a `SetupError`; it is never staged.
* `derivation_card(criterion_id)` — the same card, read back (a resuming console renders it).
* `confirm_general_derivation(criterion_id, *, confirmed_by, bands=None)` — the teacher's
  confirmation; `bands` is the teacher-edited band set (mappings in the band shape above), and
  `None` confirms the derived set as shown.
* `build_evidence_sum(criterion_id, *, question_id, aspects)` — `aspects` is a sequence of
  mappings `{"name", "points"}`, plus `"levels"` (the teacher's level descriptions) for an aspect
  the teacher describes as needing levels. Returns a draft carrying `aspects` (each with
  `criterion_id`, `name`, `points`, `bands`) and `promotions` (each with `aspect`, the aspect's
  name, and `score_method == "bands"`, the proposed standalone method).
* `edit_aspect_descriptor(criterion_id, aspect_criterion_id, *, ordinal, descriptor)` — the
  teacher's edit of one generated descriptor, before confirmation.
* `confirm_evidence_sum(criterion_id, *, confirmed_by)` — the teacher's confirmation.

The derivation reply the scripted setup model returns is `{"criterion_id", "bands": [...]}` in
the band shape above — the read-back reply's band vocabulary (`tests/integration/setup/
test_tc_setup_12_evidence_type.py`). Also an assumption, also centralised here.

Two further stated bets:

* The evidence-sum builder makes NO model call: FR-SETUP-19 says the aspect descriptors are
  "derived from the aspect name", read here as a deterministic derivation that contains the
  aspect's name. If #624 routes the builder through the setup model, script its reply here
  (the provider otherwise replays the inventory reply) and relax the name check in TC-SETUP-25.
* The derivation card spends its optional confirmation when it is SHOWN (requested), the way
  `classify_decomposability` counts a confirmation when it requests one — not when confirmed.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Mapping, Sequence

from tests.support.impl import require_attr
from tests.support.judge_vocabulary import offending_numeral
from tests.support.setup_harness import ingest_document, stage_chain

ISSUE = "#624"

#: The assumed `SetupService` member names (see the module docstring).
DERIVE = "derive_general_bands"
CARD = "derivation_card"
CONFIRM_GENERAL = "confirm_general_derivation"
BUILD_SUM = "build_evidence_sum"
EDIT_ASPECT = "edit_aspect_descriptor"
CONFIRM_SUM = "confirm_evidence_sum"

TEACHER = "teacher-1"

#: The question the method cases attach to: `Q2` of the harness inventory, open, 5 marks.
QUESTION = "Q2"
GENERAL = "CRIT-GEN"
GENERAL_2 = "CRIT-GEN-2"
COMPOSITE = "CRIT-SUM"

#: The teacher's prose. Digit-free on purpose: whether teacher prose with a digit is accepted is
#: not what these cases test — the numeral arrives through the MODEL's derivation (`RISK-112`).
DESCRIPTION = (
    "Full credit when the student carries the derivation through to the range equation and "
    "states the assumptions; most credit when the equation is reached but the assumptions are "
    "missing; some credit when the method is set up but not finished; nothing otherwise."
)

#: A clean derivation: four bands, points ascending, numeral-free labels and descriptors.
DERIVED_BANDS: tuple[dict[str, Any], ...] = (
    {"ordinal": 0, "band": "not started", "points": 0.0,
     "descriptor": "The method is not set up."},
    {"ordinal": 1, "band": "set up", "points": 2.0,
     "descriptor": "Sets up the method but does not finish the derivation."},
    {"ordinal": 2, "band": "reached", "points": 4.0,
     "descriptor": "Reaches the range equation without stating the assumptions."},
    {"ordinal": 3, "band": "complete", "points": 5.0,
     "descriptor": "Reaches the range equation and states the assumptions."},
)

#: The same derivation for `Q3` (open, 6 marks): the top band at the question's maximum.
DERIVED_BANDS_Q3: tuple[dict[str, Any], ...] = tuple(
    {**b, "points": 6.0} if b["ordinal"] == 3 else dict(b) for b in DERIVED_BANDS)

#: The `RISK-112` derivation: the model counts details into the descriptors ("3 details = top
#: band"). Every band label is clean, so only a scan of the DESCRIPTORS catches it.
NUMERAL_BANDS: tuple[dict[str, Any], ...] = (
    {"ordinal": 0, "band": "not started", "points": 0.0,
     "descriptor": "Names 0 of the required details."},
    {"ordinal": 1, "band": "set up", "points": 2.0,
     "descriptor": "Names 1 required detail."},
    {"ordinal": 2, "band": "reached", "points": 4.0,
     "descriptor": "Names 2 required details."},
    {"ordinal": 3, "band": "complete", "points": 5.0,
     "descriptor": "3 details = top band."},
)

#: The teacher's edit of `DERIVED_BANDS`: two descriptors rewritten and one label renamed, points
#: unchanged — a structure that differs from the derived one in every compared column but points.
EDITED_BANDS: tuple[dict[str, Any], ...] = (
    {"ordinal": 0, "band": "not started", "points": 0.0,
     "descriptor": "The method is not set up."},
    {"ordinal": 1, "band": "begun", "points": 2.0,
     "descriptor": "Writes the equations of motion but stops before eliminating the time."},
    {"ordinal": 2, "band": "reached", "points": 4.0,
     "descriptor": "Reaches the range equation without stating the assumptions."},
    {"ordinal": 3, "band": "complete", "points": 5.0,
     "descriptor": "Reaches the range equation and names level ground and no air resistance."},
)

#: The evidence-sum builder's input: three aspects, points summing to Q2's five marks.
ASPECTS: tuple[dict[str, Any], ...] = (
    {"name": "correct details", "points": 2.0},
    {"name": "clear structure", "points": 1.0},
    {"name": "coherent conclusion", "points": 2.0},
)

#: An aspect the teacher describes as needing levels (TC-SETUP-25 (b)).
LEVELLED_ASPECT: dict[str, Any] = {
    "name": "structure", "points": 2.0,
    "levels": ["no structure", "partially correct structure", "correct structure"],
}


# --- reading records of either shape -----------------------------------------------------------


def field(record: Any, name: str) -> Any:
    """`record.name` or `record[name]`: the card and draft records may be dataclasses or
    mappings; the cases do not care which."""
    if isinstance(record, Mapping):
        return record[name]
    return getattr(record, name)


def band_tuples(bands: Iterable[Any]) -> list[tuple[int, str, float, str]]:
    """(ordinal, band, points, descriptor), ordered by points then ordinal — comparable across
    the card, the scripted reply and the stored rows, whichever order each arrives in."""
    out = [(int(field(b, "ordinal")), str(field(b, "band")), float(field(b, "points")),
            str(field(b, "descriptor") or "")) for b in bands]
    return sorted(out, key=lambda t: (t[2], t[0]))


def comparable(bands: Iterable[Any]) -> list[tuple[str, float, str]]:
    """`band_tuples` without the ordinal: the stored order is renumbered from 0 (FR-PKG-06), so
    ordinals are not part of what the teacher confirmed."""
    return [(band, points, descriptor) for _o, band, points, descriptor in band_tuples(bands)]


def numeral_offenses(bands: Iterable[Any]) -> list[str]:
    """FR-JUDGE-03's rubric-surface scan (the one `judge_vocabulary` shares with TC-PKG-09) over
    every band label and descriptor. Empty means the band set passes."""
    problems = []
    for b in bands:
        for name in ("band", "descriptor"):
            text = str(field(b, name) or "")
            hit = offending_numeral(text, rubric=True)
            if hit is not None:
                problems.append(f"{name} {text!r} carries the numeral {hit!r}")
    return problems


# --- the scripted model ------------------------------------------------------------------------


def derivation_reply(criterion_id: str, bands: Sequence[Mapping[str, Any]]) -> str:
    return json.dumps({"criterion_id": criterion_id, "bands": [dict(b) for b in bands]})


def borderline_reply(criterion_id: str) -> str:
    """A §5.3 answer set that passes with one warning sign — TC-SETUP-C13's borderline reply,
    the population the confirmation cap counts."""
    return json.dumps({
        "criterion_id": criterion_id,
        "answers": {q: "yes" for q in ("completeness", "non_interference", "independence",
                                        "additivity", "gates")},
        "warning_signs": ["straddles two constructs"],
        "reasoning": f"scripted borderline answers for {criterion_id}",
    })


# --- the flow ----------------------------------------------------------------------------------


def confirmed_chain(tmp_data_dir: Any, package_id: str = "pkg-methods") -> Any:
    """The Stage A chain through the confirmed inventory, with the staged deterministic criteria
    keyed — so publish's two existing gates are out of the way and a refusal can only be the
    derivation gate (or a defect the case names)."""
    chain = stage_chain(tmp_data_dir, package_id)
    assessment = ingest_document(chain.store)
    proposal = chain.service.propose_inventory(assessment)
    chain.service.confirm_inventory(proposal.proposal_id)
    chain.service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["A"], "CRIT-Q6": ["A"]})
    chain.version = chain.catalog.draft_version()
    return chain


def _member(service: Any, name: str) -> Any:
    from aeh.setup import SetupService

    require_attr(SetupService, name, issue=ISSUE)
    return getattr(service, name)


def derive(chain: Any, criterion_id: str, *, replies: Sequence[str] | None = None,
           description: str = DESCRIPTION, question_id: str = QUESTION) -> Any:
    """Script the model's derivation reply(ies), then ask setup for the derivation card."""
    member = _member(chain.service, DERIVE)
    chain.provider.replies = list(replies if replies is not None
                                  else [derivation_reply(criterion_id, DERIVED_BANDS)])
    return member(criterion_id, question_id=question_id, description=description)


def card(chain: Any, criterion_id: str) -> Any:
    return _member(chain.service, CARD)(criterion_id)


def confirm_general(chain: Any, criterion_id: str, *,
                    bands: Sequence[Mapping[str, Any]] | None = None) -> Any:
    member = _member(chain.service, CONFIRM_GENERAL)
    if bands is None:
        return member(criterion_id, confirmed_by=TEACHER)
    return member(criterion_id, confirmed_by=TEACHER, bands=[dict(b) for b in bands])


def build_sum(chain: Any, criterion_id: str, aspects: Sequence[Mapping[str, Any]], *,
              question_id: str = QUESTION) -> Any:
    member = _member(chain.service, BUILD_SUM)
    return member(criterion_id, question_id=question_id, aspects=[dict(a) for a in aspects])


def edit_aspect(chain: Any, criterion_id: str, aspect_id: str, *, ordinal: int,
                descriptor: str) -> Any:
    return _member(chain.service, EDIT_ASPECT)(criterion_id, aspect_id, ordinal=ordinal,
                                               descriptor=descriptor)


def confirm_sum(chain: Any, criterion_id: str) -> Any:
    return _member(chain.service, CONFIRM_SUM)(criterion_id, confirmed_by=TEACHER)


def stored_card(chain: Any, criterion_id: str) -> Any:
    """The card a resuming console would render, or None when setup refuses to show one (no
    derivation was staged)."""
    from aeh.pkg import PackageError
    from aeh.setup import SetupError

    try:
        return card(chain, criterion_id)
    except (SetupError, PackageError, KeyError, LookupError):
        return None


def assert_derivation_gate(chain: Any, refusal: Exception) -> None:
    """The refusal is the DERIVATION gate's, not an existing gate's: the step report does not
    call the draft ready (it reads the inventory and key gates, so a not-ready report with those
    met is the derivation gate), and the refusal is not FR-SETUP-09's evidence-type check, which
    also names criterion ids."""
    assert chain.service.steps().ready_to_publish is False, (
        "the step report calls the draft ready to publish while a `general` derivation is "
        "unconfirmed (CT-SETUP-17)")
    assert "evidence_type" not in str(refusal), (
        "the publish refusal is FR-SETUP-09's evidence-type check, not the derivation gate — "
        f"the staged `general` criterion lacks its evidence_type: {refusal}")


def publish_refusal(chain: Any) -> Exception:
    """Attempt publish, expecting the refusal; fail the case if it published. Catches the
    setup and package error families only — a `NotImplementedYet` or a `TypeError` from an
    unlanded surface propagates as the honest red."""
    from aeh.pkg import PackageError
    from aeh.setup import SetupError

    try:
        chain.service.publish(TEACHER)
    except (SetupError, PackageError) as error:
        return error
    raise AssertionError(
        "publish succeeded while a `general` criterion's derivation was unconfirmed — the "
        "read-back is a blocking gate (FR-SETUP-18, CT-SETUP-17), not an advisory card")


# --- raw reads: what the store holds -----------------------------------------------------------


def _rows(chain: Any, table: str) -> list[dict[str, Any]]:
    connection = sqlite3.connect(str(chain.store.package_path(chain.package_id)))
    connection.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in connection.execute(
            f"SELECT * FROM {table} WHERE package_version_id = ?", (chain.version,))]
    finally:
        connection.close()


def criteria_rows(chain: Any) -> dict[str, dict[str, Any]]:
    return {row["criterion_id"]: row for row in _rows(chain, "criterion")}


def stored_bands(chain: Any) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(_rows(chain, "band"), key=lambda r: (r["criterion_id"], r["ordinal"])):
        out.setdefault(row["criterion_id"], []).append(row)
    return out


def locked(chain: Any) -> bool:
    return bool(chain.catalog.is_locked(chain.version))
