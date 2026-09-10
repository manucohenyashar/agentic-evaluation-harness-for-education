"""`TC-SYNTH-C02` — the two-level information boundary is the request type (§6.11.13).

`CT-SYNTH-02`'s behaviour clause at rung 0: an L1 request reads one question's
criterion verdicts and evidence for one submission; an L2 request reads **only** the
L1 syntheses — and the decisive assertion is *how* the boundary is enforced. Not by
prompt instruction (a prompt can be edited; nothing would fail when a later change
hands the small model thirty verdicts) but by the request **type**: `L2Request` has
no field that could carry a raw verdict, so a smuggled one cannot even be
constructed.

Relationship to shipped cases, disclosed:

- `tests/artifact/test_synth_score_free_schema.py` (`TC-SYNTH-07`) holds the
  smuggled-verdict construction probe (three smuggled kwargs) and the
  one-submission_id field check. This case re-derives the probe (the boundary's
  core, cheap at rung 0) and adds what the sibling does not hold: the per-level
  field-set equality over both request types, the probe across EVERY verdict- and
  evidence-shaped smuggle, and the rendered-prompt differential — the L2
  payload's field names prove the composition input is the syntheses and nothing
  else, which is the observable half of "reads only the L1 syntheses".
- `tests/integration/synth/test_two_level_boundary.py` (`TC-SYNTH-01`) drives the
  real worker and classifies each prompt by level; this case pins the type and
  renderer the worker routes through.

Isolation: rung 0 — dataclasses and `prompt_for`, no store, no provider.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from tests.support.impl import SYNTH_MODULE, require
from tests.support.synth_vocabulary import (
    L1_REQUEST,
    L2_REQUEST,
    SYNTH_ISSUE,
)

pytestmark = [pytest.mark.contract]

L1_FIELDS = frozenset(
    {"run_id", "submission_id", "question_id", "criterion_ids", "verdicts", "evidence"}
)
L2_FIELDS = frozenset({"run_id", "submission_id", "syntheses"})

_SMUGGLES = ("verdicts", "evidence", "criterion_ids", "bands", "scores")


def _l1(L1Request, CriterionVerdict):
    return L1Request(
        run_id="r",
        submission_id="s",
        question_id="Q1",
        criterion_ids=("Q1C1", "Q1C2"),
        verdicts=(CriterionVerdict("Q1C1", "j1", "high"),),
        evidence=("EVIDENCE-Q1: the student's own span.",),
    )


def test_tc_synth_c02_request_field_sets_are_exact_per_level():
    """`TC-SYNTH-C02` (P0) — L1 carries exactly the per-question surface; L2 carries
    exactly the syntheses surface and nothing else."""
    L1Request, L2Request = require(
        SYNTH_MODULE, L1_REQUEST, L2_REQUEST, issue=SYNTH_ISSUE
    )

    l1_names = {field.name for field in fields(L1Request)}
    l2_names = {field.name for field in fields(L2Request)}
    assert l1_names == L1_FIELDS, (
        f"L1Request carries {sorted(l1_names)}; the L1 request is one question's "
        "criteria, verdicts and evidence for one submission — nothing more, so the "
        "narrative model cannot be handed another question's or submission's data "
        "through an extra field."
    )
    assert l2_names == L2_FIELDS, (
        f"L2Request carries {sorted(l2_names)}; the L2 request is the L1 syntheses "
        "and NOTHING else (NFR-SYNTH-03) — every extra field is a channel a raw "
        "verdict could ride into the test-level composition."
    )


def test_tc_synth_c02_an_l2_request_cannot_represent_a_raw_verdict():
    """`TC-SYNTH-C02` (P0, the decisive assertion) — the boundary is the type: no
    verdict- or evidence-shaped field can be smuggled onto an L2 request, so the
    small model composing the test-level narrative cannot be handed the panel's
    verdicts no matter what a later change tries."""
    L2Request = require(SYNTH_MODULE, L2_REQUEST, issue=SYNTH_ISSUE)

    for smuggled in _SMUGGLES:
        with pytest.raises(TypeError) as refused:
            L2Request(
                run_id="r",
                submission_id="s",
                syntheses=("Question 1: prose.",),
                **{smuggled: ("band=high",)},
            )
        assert "unexpected keyword argument" in str(refused.value), (
            f"smuggling {smuggled!r} onto L2Request failed with "
            f"{refused.value!r} instead of the constructor's own refusal — the "
            "boundary must live in the type (no field to hold it), not in a check "
            "that could be relaxed"
        )


def test_tc_synth_c02_the_rendered_l2_payload_carries_syntheses_only():
    """`TC-SYNTH-C02` (P0, the observable half) — the L2 prompt's rendered fields
    name exactly the L2 request's surface: directive, template version, level, the
    syntheses and the submission — and no verdict/evidence/question field exists to
    render. The L1 payload, by contrast, renders the question, its criteria, its
    verdicts and its evidence: the two levels are visibly different requests."""
    L1Request, L2Request, CriterionVerdict, prompt_for = require(
        SYNTH_MODULE, L1_REQUEST, L2_REQUEST, "CriterionVerdict", "prompt_for",
        issue=SYNTH_ISSUE,
    )

    l2_payload = prompt_for(
        L2Request(run_id="r", submission_id="s", syntheses=("Q1 prose.", "Q2 prose."))
    )
    l2_fields = {name for name, _ in l2_payload.fields}
    assert l2_fields == {
        "directive", "prompt_template_v", "level", "syntheses", "submission",
    }, (
        f"the L2 payload renders {sorted(l2_fields)} — the composition prompt is "
        "built from the L1 syntheses alone; a rendered verdict/evidence field would "
        "mean the boundary was a prompt instruction after all"
    )
    syntheses_value = dict(l2_payload.fields)["syntheses"]
    assert "Q1 prose." in syntheses_value and "Q2 prose." in syntheses_value, (
        "the L2 prompt must carry the L1 syntheses it composes from"
    )

    l1_payload = prompt_for(_l1(L1Request, CriterionVerdict))

    l1_fields = {name for name, _ in l1_payload.fields}
    assert {"question", "criteria", "verdicts", "evidence", "submission"} <= l1_fields, (
        f"the L1 payload renders {sorted(l1_fields)} — the per-question surface "
        "(the verdicts and evidence FR-SYNTH-01 scopes) must be visible at L1"
    )
    verdict_lines = dict(l1_payload.fields)["verdicts"]
    assert "criterion=Q1C1" in verdict_lines and "j1" in verdict_lines, (
        "the L1 prompt's verdict block names the panel's verdicts for ITS question"
    )
