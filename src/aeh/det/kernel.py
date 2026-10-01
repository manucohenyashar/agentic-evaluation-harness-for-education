"""The scoring rule: one selection read against one key under one partial-credit policy."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .constants import (
    BAND_CORRECT,
    BAND_INCORRECT,
    BAND_UNRESOLVED,
    CONTENT_STATES,
    PARTIAL_CREDIT_POLICIES,
    POLICY_ALL_OR_NOTHING,
    REASON_ABSENT_REGION,
    REASON_AMBIGUOUS_MARK,
    REASON_BLANK,
    REASON_KEY_MATCH,
    REASON_KEY_MISS,
    REASON_MULTIPLE_MARKS,
    REASON_NO_SELECTION_READ,
    REASON_SELECTION_OUTSIDE_OPTION_SET,
    REASON_SINGLE_SELECT_MULTIPLE,
    ROUTING_AUTO,
    ROUTING_TRIAGE,
    SELECTION_STATES,
    STATE_FINAL,
    STATE_UNRESOLVED_SELECTION,
)
from .errors import (
    MalformedAnswerKey,
    MalformedSelectionRead,
    UndeclaredPartialCreditPolicy,
    UnknownPartialCreditPolicy,
)


# --- the pure kernel: the §7.8 situation table ------------------------------------------------------


@dataclass(frozen=True)
class DetOutcome:
    """The resolved outcome for one cell of the design's situation table (§7.8).

    `band` is `'correct'` / `'incorrect'`, or the `'unresolved'` marker for a
    row that was never scored. `credit` is the earned fraction (1.0 on an
    exact match, the per_option fraction under partial credit, 0.0 on a miss
    and for every unresolved cell). `reason` names the cell — it is what keeps
    a stored score answerable about why it is what it is.
    """

    band: str
    state: str
    routing: str
    credit: float
    reason: str
    selection_read: tuple[str, ...] | None


def _unresolved(reason: str) -> DetOutcome:
    return DetOutcome(
        band=BAND_UNRESOLVED,
        state=STATE_UNRESOLVED_SELECTION,
        routing=ROUTING_TRIAGE,
        credit=0.0,
        reason=reason,
        selection_read=None,
    )


def evaluate(
    *,
    content_state: str,
    key: Sequence[str],
    selection_state: str | None = None,
    selection: Sequence[str] | None = None,
    multi_select: bool = False,
    partial_credit: str | None = None,
    option_set: Sequence[str] | None = None,
) -> DetOutcome:
    """Score one selection read against one answer key under one partial-credit policy.

    A pure function of (selection, key, policy) plus the two states
    M-INGEST recorded about the read — no I/O, no clock, no configuration
    (`CT-DET-01`, `NFR-DET-02`). Raises only on inputs that cannot come from
    a published package or a migrated store: a malformed key, a malformed
    state, or — the contract's decisive negative — a multi-select criterion
    with no declared policy (`TC-DET-03` cell 11).
    """
    if content_state not in CONTENT_STATES:
        raise MalformedSelectionRead(
            f"content_state {content_state!r} is outside {CONTENT_STATES}."
        )
    resolved_key = tuple(key)
    if not resolved_key:
        raise MalformedAnswerKey(
            "an empty answer key cannot be scored; FR-SETUP-03 makes a missing "
            "key a publication-time failure that cannot reach this module."
        )
    if not multi_select and len(resolved_key) != 1:
        raise MalformedAnswerKey(
            f"a single-select criterion is keyed to exactly one option; this "
            f"key holds {len(resolved_key)} ({resolved_key!r})."
        )
    if multi_select and partial_credit is None:
        # Consulted on the comparison path only — but raised here too, because
        # a caller evaluating a multi-select selection without a declared
        # policy must not discover the omission by getting a silently
        # defaulted score; the raise fires the moment the criterion says
        # multi-select and the package declares nothing.
        raise UndeclaredPartialCreditPolicy(
            "multi-select criterion with no declared partial-credit policy: "
            "FR-DET-05 forbids inferring one; declare all_or_nothing or "
            "per_option in the package."
        )
    if multi_select and partial_credit not in PARTIAL_CREDIT_POLICIES:
        raise UnknownPartialCreditPolicy(
            f"partial_credit {partial_credit!r} is outside {PARTIAL_CREDIT_POLICIES}."
        )

    if content_state == "absent":
        # Cell 5: the answer region does not exist. A scanning problem, never
        # a zero the student earned.
        return _unresolved(REASON_ABSENT_REGION)

    if content_state == "blank":
        # Cell 6: the mirror of the unresolved cells — a genuinely empty
        # answer IS a zero, a legitimate one, counted in blank_count and
        # never in unresolved_count.
        return DetOutcome(
            band=BAND_INCORRECT,
            state=STATE_FINAL,
            routing=ROUTING_AUTO,
            credit=0.0,
            reason=REASON_BLANK,
            selection_read=None,
        )

    # content_state == 'present'
    if selection_state is None:
        # A present region with no selection read at all (or a region_kind
        # that is not a selection mark where one was declared) is an
        # unreadable answer — route it, never guess.
        return _unresolved(REASON_NO_SELECTION_READ)
    if selection_state not in SELECTION_STATES:
        raise MalformedSelectionRead(
            f"selection_state {selection_state!r} is outside {SELECTION_STATES}."
        )
    if selection_state == "ambiguous":
        return _unresolved(REASON_AMBIGUOUS_MARK)
    if selection_state == "multiple_marks":
        # Cells 3/4 and CT-DET-C03's boundary: even a mark far darker than
        # the others stays unresolved. "Clearly they meant this one" is the
        # heuristic this module exists to refuse.
        return _unresolved(REASON_MULTIPLE_MARKS)

    # selection_state == 'resolved'
    if not selection:
        # CT-INGEST-04: selection is populated iff resolved. A violation of
        # that contract is not a score — it routes.
        return _unresolved(REASON_NO_SELECTION_READ)
    chosen: tuple[str, ...] = ()
    for option_id in selection:
        if option_id not in chosen:
            chosen = chosen + (option_id,)
    if option_set is not None:
        declared = set(option_set)
        if any(option_id not in declared for option_id in chosen):
            return _unresolved(REASON_SELECTION_OUTSIDE_OPTION_SET)

    if not multi_select:
        if len(chosen) != 1:
            return _unresolved(REASON_SINGLE_SELECT_MULTIPLE)
        matched = chosen[0] == resolved_key[0]
        return DetOutcome(
            band=BAND_CORRECT if matched else BAND_INCORRECT,
            state=STATE_FINAL,
            routing=ROUTING_AUTO,
            credit=1.0 if matched else 0.0,
            reason=REASON_KEY_MATCH if matched else REASON_KEY_MISS,
            selection_read=chosen,
        )

    chosen_set = set(chosen)
    key_set = set(resolved_key)
    exact = chosen_set == key_set
    if partial_credit == POLICY_ALL_OR_NOTHING:
        # Cells 7/8: everything or nothing — a subset and a superset are
        # equally not the answer.
        return DetOutcome(
            band=BAND_CORRECT if exact else BAND_INCORRECT,
            state=STATE_FINAL,
            routing=ROUTING_AUTO,
            credit=1.0 if exact else 0.0,
            reason=REASON_KEY_MATCH if exact else REASON_KEY_MISS,
            selection_read=chosen,
        )
    # POLICY_PER_OPTION — cells 9/10, with the over-selection rule stated in
    # `docs/code-notes/det.md`: each non-key selection cancels one earned credit,
    # floored at zero.
    earned = len(chosen_set & key_set) - len(chosen_set - key_set)
    credit = max(0, earned) / len(resolved_key)
    return DetOutcome(
        band=BAND_CORRECT if exact else BAND_INCORRECT,
        state=STATE_FINAL,
        routing=ROUTING_AUTO,
        credit=credit,
        reason=REASON_KEY_MATCH if exact else REASON_KEY_MISS,
        selection_read=chosen,
    )


def _decode_answer_key(raw: Any, criterion_id: str) -> tuple[str, ...]:
    """Decode `criterion.answer_key`, a JSON list of option ids (one for single-select, several for
    multi-select). A malformed key is reported here as a package-integrity failure rather than as a
    JSON error."""
    if raw is None or raw == "":
        return ()
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise MalformedAnswerKey(
            f"criterion {criterion_id!r} carries a non-JSON answer key: {error}"
        ) from error
    if not isinstance(parsed, list) or not all(isinstance(o, str) for o in parsed):
        raise MalformedAnswerKey(
            f"criterion {criterion_id!r}'s answer key is not a list of option ids."
        )
    return tuple(parsed)
