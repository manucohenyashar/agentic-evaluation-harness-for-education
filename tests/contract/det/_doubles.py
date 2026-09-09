"""Shared doubles for the `M-DET` contract suite (`TS-68`, issue #90).

The clause cases of §6.11.11 stand on the world-shaped fixtures the integration
track already ships (`tests/support/det_vocabulary.py`): a real store, a real
Tier P package with declared keys/options/bands, a real run row written by
`M-ORCH`, and head documents with answer regions. This module adds only what a
*clause* case needs and an `FR-*` case does not:

- `SITUATION_TABLE` — the HLD §7.8 situation table as data (cells 1-11 plus the
  two variants §5.11 names), with the exact expected value per cell, so C01 can
  enumerate it exhaustively and C03 can sweep the three-way distinction off the
  same transcription.
- `canonical_table_bytes` — one deterministic serialization of a whole-table
  evaluation, the byte string C01 compares across backend profiles.
- `CollapseDistinctionMutant` — C03's executable adversarial construction: a
  kernel that maps `ambiguous` to the darkest mark and `absent` to `incorrect`
  "because an unanswered question is worth zero anyway". The case asserts it
  agrees with the real module on every resolved cell (every `FR-DET-*` case
  stays green under it) and differs on every unresolved cell (the clause case
  goes red) — RISK-03 in its most concrete form.

Disclosures (the reconciliation register for this suite; each case's docstring
names the ones it carries):

- `multi_select` / `partial_credit` columns are written directly by
  `det_vocabulary.seed_det_package` — no pkg setter exists yet (inherited from
  TS-33's disclosure, unchanged).
- `label` rows are seeded directly: det owns the `evaluation_mode` COLUMN but
  the write set of `CT-DET-09` admits no label writes; population is the duty
  of whichever module records a label over a deterministic result (det.py's
  module docstring; inherited from TS-33's disclosure, unchanged).
- The rung-3 consumer sweeps (M-AGG, M-GRADE, M-REVIEW, M-CONSOLE, M-STATS)
  are disclosed per case: none of those modules is shipped yet, so each sweep
  is asserted at the data/vocabulary level the shipped modules actually
  expose — the exact surface the consumer will read — and the sweep itself
  lands with the module that owns it (κ/α consumers land with M-STATS).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from aeh.det import DetOutcome, UndeclaredPartialCreditPolicy

ISSUE = "#90"

#: The option set every kernel cell is evaluated against (the store path reads
#: it from `mcq_option`; the kernel takes it as the declared option set).
OPTION_SET = ("A", "B", "C", "D", "E")

SINGLE_KEY = ("B",)
MULTI_KEY = ("B", "D")


# --- the HLD §7.8 situation table ---------------------------------------------------------------


@dataclass(frozen=True)
class SituationCell:
    """One cell of the §7.8 table, transcribed from test-plan §5.11.

    `raises` cells carry the exception type instead of an outcome — cell 11 is
    the contract's decisive negative (`CT-DET-05`), not a score.
    """

    cell: str
    content_state: str
    selection_state: str | None
    selection: tuple[str, ...] | None
    key: tuple[str, ...]
    multi_select: bool = False
    partial_credit: str | None = None
    option_set: tuple[str, ...] | None = OPTION_SET
    band: str | None = None
    state: str | None = None
    routing: str | None = None
    credit: float | None = None
    reason: str | None = None
    selection_read: tuple[str, ...] | None = None
    raises: type[Exception] | None = None


#: The full table, §5.11's rows 1-11 plus the two named variants. The expected
#: values are the plan's, resolved through the design's per_option rule (each
#: non-key selection cancels one earned credit, floored at zero) — cells 9/10
#: both earn 1 of 2 credits: cell 9 selects one of the two key options, cell 10
#: selects both but over-selects one.
SITUATION_TABLE: tuple[SituationCell, ...] = (
    SituationCell("1", "present", "resolved", ("B",), SINGLE_KEY,
                  band="correct", state="final", routing="auto", credit=1.0,
                  reason="key_match", selection_read=("B",)),
    SituationCell("2", "present", "resolved", ("C",), SINGLE_KEY,
                  band="incorrect", state="final", routing="auto", credit=0.0,
                  reason="key_miss", selection_read=("C",)),
    SituationCell("3", "present", "ambiguous", None, SINGLE_KEY,
                  band="unresolved", state="unresolved_selection", routing="triage",
                  credit=0.0, reason="ambiguous_mark", selection_read=None),
    SituationCell("4", "present", "multiple_marks", None, SINGLE_KEY,
                  band="unresolved", state="unresolved_selection", routing="triage",
                  credit=0.0, reason="multiple_marks", selection_read=None),
    SituationCell("5", "absent", None, None, SINGLE_KEY,
                  band="unresolved", state="unresolved_selection", routing="triage",
                  credit=0.0, reason="absent_region", selection_read=None),
    SituationCell("6", "blank", None, None, SINGLE_KEY,
                  band="incorrect", state="final", routing="auto", credit=0.0,
                  reason="blank_legitimate_zero", selection_read=None),
    SituationCell("7", "present", "resolved", ("B", "D"), MULTI_KEY,
                  multi_select=True, partial_credit="all_or_nothing",
                  band="correct", state="final", routing="auto", credit=1.0,
                  reason="key_match", selection_read=("B", "D")),
    SituationCell("8", "present", "resolved", ("B",), MULTI_KEY,
                  multi_select=True, partial_credit="all_or_nothing",
                  band="incorrect", state="final", routing="auto", credit=0.0,
                  reason="key_miss", selection_read=("B",)),
    SituationCell("9", "present", "resolved", ("B",), MULTI_KEY,
                  multi_select=True, partial_credit="per_option",
                  band="incorrect", state="final", routing="auto", credit=0.5,
                  reason="key_miss", selection_read=("B",)),
    SituationCell("10", "present", "resolved", ("B", "D", "E"), MULTI_KEY,
                  multi_select=True, partial_credit="per_option",
                  band="incorrect", state="final", routing="auto", credit=0.5,
                  reason="key_miss", selection_read=("B", "D", "E")),
    SituationCell("11", "present", "resolved", ("B",), MULTI_KEY,
                  multi_select=True, partial_credit=None,
                  raises=UndeclaredPartialCreditPolicy),
    # Variant 1: a selection whose option id is not in the option set at all.
    SituationCell("v1-out-of-set", "present", "resolved", ("Z",), SINGLE_KEY,
                  band="unresolved", state="unresolved_selection", routing="triage",
                  credit=0.0, reason="selection_outside_option_set",
                  selection_read=None),
    # Variant 2: a key referencing an option a later version removed. The
    # phantom option can never be matched — a student marking the surviving
    # option reads as incorrect, and nothing errors (CT-DET-14's boundary: the
    # module compares against the key it was given).
    SituationCell("v2-removed-option", "present", "resolved", ("B",), ("X",),
                  band="incorrect", state="final", routing="auto", credit=0.0,
                  reason="key_miss", selection_read=("B",)),
)

#: The cells the three-way distinction of `CT-DET-03` is about: the unresolved
#: states and the blank that is their mirror.
UNRESOLVED_CELLS: tuple[str, ...] = ("3", "4", "5")


def evaluate_cell(cell: SituationCell) -> DetOutcome:
    """Evaluate one table cell through the real kernel's exact signature."""
    from aeh.det import evaluate

    return evaluate(
        content_state=cell.content_state,
        selection_state=cell.selection_state,
        selection=cell.selection,
        key=cell.key,
        multi_select=cell.multi_select,
        partial_credit=cell.partial_credit,
        option_set=cell.option_set,
    )


def outcome_bytes(cell: str, outcome: DetOutcome) -> str:
    """One cell's outcome as a deterministic byte string — the unit C01
    compares across runs and backend profiles. Every field of the outcome
    travels, so a change in any of them moves the bytes."""
    return json.dumps(
        {
            "cell": cell,
            "band": outcome.band,
            "state": outcome.state,
            "routing": outcome.routing,
            "credit": outcome.credit,
            "reason": outcome.reason,
            "selection_read": (
                list(outcome.selection_read)
                if outcome.selection_read is not None
                else None
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_table_bytes() -> bytes:
    """The whole table evaluated and serialized — the byte string that must be
    identical across runs and backend profiles (`CT-DET-01`)."""
    lines = []
    for cell in SITUATION_TABLE:
        if cell.raises is not None:
            try:
                evaluate_cell(cell)
            except Exception as error:  # noqa: BLE001 — the type IS the value here
                lines.append(json.dumps(
                    {"cell": cell.cell, "raises": type(error).__name__},
                    sort_keys=True, separators=(",", ":"),
                ))
            else:
                raise AssertionError(
                    f"cell {cell.cell} was expected to raise and did not"
                )
        else:
            lines.append(outcome_bytes(cell.cell, evaluate_cell(cell)))
    return "\n".join(lines).encode("utf-8")


# --- C03's adversarial construction: the collapse mutant ----------------------------------------


class CollapseDistinctionMutant:
    """The well-intentioned refactor `CT-DET-03` exists to refuse.

    It maps `ambiguous` to the darkest mark ("clearly they meant this one") and
    `absent` to `incorrect` ("an unanswered question is worth zero anyway").
    Under it the rollup gets cleaner, the triage queue empties, and students
    with faint pencils or poor scans are systematically marked down — while
    every resolved-selection case (every `FR-DET-*` case's input) produces
    exactly the band the real module produces.

    `darkest` is the option id the mutant's imaginary darkness metric would
    pick out of a `multiple_marks`/`ambiguous` scan; the real module's input
    vocabulary deliberately does not carry darkness, which is the point — the
    mutant needs information the contract refuses to give it.
    """

    def __init__(self, darkest: str = "B") -> None:
        self._darkest = darkest

    def evaluate(self, *, content_state: str, selection_state: str | None,
                 selection: tuple[str, ...] | None, key: tuple[str, ...],
                 **_: object) -> DetOutcome:
        from aeh.det import (
            BAND_CORRECT,
            BAND_INCORRECT,
            REASON_KEY_MATCH,
            REASON_KEY_MISS,
            ROUTING_AUTO,
            STATE_FINAL,
            DetOutcome,
        )

        key_tuple = tuple(key)
        if content_state == "absent":
            # "An unanswered question is worth zero anyway."
            return DetOutcome(
                band=BAND_INCORRECT, state=STATE_FINAL, routing=ROUTING_AUTO,
                credit=0.0, reason="key_miss", selection_read=None,
            )
        if content_state == "blank":
            return DetOutcome(
                band=BAND_INCORRECT, state=STATE_FINAL, routing=ROUTING_AUTO,
                credit=0.0, reason="blank_legitimate_zero", selection_read=None,
            )
        if selection_state == "ambiguous":
            # "Clearly they meant this one" — the darkest mark becomes the
            # student's answer.
            chosen = (self._darkest,)
        elif selection_state == "multiple_marks":
            chosen = (self._darkest,)
        elif selection_state == "resolved" and selection:
            chosen = (selection[0],)
        else:
            chosen = (self._darkest,)
        matched = chosen[0] == key_tuple[0]
        return DetOutcome(
            band=BAND_CORRECT if matched else BAND_INCORRECT,
            state=STATE_FINAL,
            routing=ROUTING_AUTO,
            credit=1.0 if matched else 0.0,
            reason=REASON_KEY_MATCH if matched else REASON_KEY_MISS,
            selection_read=chosen,
        )


def resolved_cells() -> tuple[SituationCell, ...]:
    """The cells a scoring refactor must NOT move: every resolved-selection
    cell, whose behaviour the `FR-DET-*` cases pin. The mutant agreeing here is
    what makes it invisible to the functional suite."""
    keep = {"1", "2", "7", "8", "9", "10", "v2-removed-option"}
    return tuple(c for c in SITUATION_TABLE if c.cell in keep and c.raises is None)
