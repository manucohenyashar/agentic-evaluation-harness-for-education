"""`TC-SYNTH-C11` — the pinned template is a work_id input; the pattern list is a
contract (§6.11.13).

`CT-SYNTH-11`'s configuration clause, both differentials:

- `SYNTH_PROMPT_TEMPLATE_V` is pinned **and is a `work_id` input**: the version
  renders into every synthesis prompt (the version the provider boundary hashes),
  and changing it changes the work id `compute_work_id` derives — dependent work
  invalidates. A template change that did not invalidate would let two template
  generations' units share a work identity, which is the drift `FR-ORCH-01` exists
  to prevent.
- `SYNTH_SCORE_CLAIM_PATTERNS`: changing the list **changes what gets suppressed**,
  both directions — a narrowed list RELEASES a narrative the default list caught,
  and an extended list SUPPRESSES a narrative the default list passed. That
  visibility is the point: loosening the pattern list is a contract-affecting change
  reviewable as one, not a quiet edit to a constant. The list is deliberately not an
  env knob (it is the prohibition's content), so the differential substitutes the
  module attribute — the same attribute the shipped check reads at call time.

Relationship to shipped cases: `tests/unit/synth/test_score_claim_patterns.py`
(`TC-SYNTH-04`) pins the default list's classes; this case pins that the list is a
CONFIGURATION — the differential, not the classes.

Isolation: rung 0 for the template and work-id halves (pure, one hash over
strings) and rung 2 for the suppression differential (real store, a one-question
drive, the capture provider at the model boundary).
"""

from __future__ import annotations

import pytest

from aeh.orch import compute_work_id
from aeh.store import open_store
from tests.support.impl import SYNTH_MODULE, require
from tests.support.orch_run import seed_run
from tests.support.synth_vocabulary import (
    COHORT_ID,
    SYNTH_ISSUE,
    WORKER,
    CaptureProvider,
    narrative_completion,
    seed_scored_submission,
    synth_ref,
)

pytestmark = [pytest.mark.contract]

_SUBMISSION = "SYN-001"
_ONE_QUESTION = {"Q1": ("Q1C1", "Q1C2")}
_ONE_QUESTION_CRITERIA = tuple(
    {"criterion_id": criterion_id, "kind": "open", "scoring_model": "holistic"}
    for criterion_id in ("Q1C1", "Q1C2")
)

#: A numeral-adjacent-mark claim — caught by the DEFAULT list's class (1), and NOT
#: by the holistic-only narrowing (it carries no holistic phrase).
_NUMERAL_CLAIM = (
    "Question 1: the working is careful and complete; the answer earned 17 marks "
    "overall."
)
#: A paraphrase the DEFAULT list releases and an extension names.
_PARAPHRASE = (
    "Question 1: the working is set out clearly; overall a model response to this "
    "task."
)
_CLEAN = "Question 1: the response states the hypothesis and cites the worked steps."


def _replies(text: str, count: int) -> list:
    """`count` identical replies — the feed a twice-claiming ladder consumes."""
    return [narrative_completion(text, ("Q1C1", "Q1C2")) for _ in range(count)]


def _drive(store_dir, replies, patterns):
    """One one-question synthesis under the given pattern list; returns
    `(report, l1_rows)`. `store_dir` is a fresh per-drive directory (`seed_run`
    seeds its cohort once per store). The list is substituted on the module (the
    same attribute the shipped check reads at call time), never on a copy."""
    import aeh.synth as synth

    monkey_target = synth.SYNTH_SCORE_CLAIM_PATTERNS
    try:
        synth.SYNTH_SCORE_CLAIM_PATTERNS = patterns
        Worker = require(SYNTH_MODULE, WORKER, issue=SYNTH_ISSUE)
        store = open_store(store_dir)
        try:
            _, run_id, _ = seed_run(
                store, submissions=(_SUBMISSION,), criteria=_ONE_QUESTION_CRITERIA
            )
            seed_scored_submission(
                store, run_id, _SUBMISSION, criteria_by_question=_ONE_QUESTION,
                complete_questions=set(_ONE_QUESTION),
            )
            report = Worker(
                store, CaptureProvider(replies), synth_ref()
            ).synthesize_submission(run_id, _SUBMISSION)
            rows = [
                dict(row)
                for row in store.cohort(COHORT_ID).query(
                    "SELECT question_id, text, score_claim_flag FROM narrative "
                    "WHERE run_id = :r AND level = 'l1_question'",
                    r=run_id,
                )
            ]
            return report, rows
        finally:
            store.close()
    finally:
        synth.SYNTH_SCORE_CLAIM_PATTERNS = monkey_target


def test_tc_synth_c11_the_template_version_is_pinned_and_in_every_prompt():
    """`TC-SYNTH-C11` (P1, pin half) — `SYNTH_PROMPT_TEMPLATE_V` is the pinned
    value, and it renders into both levels' prompt payloads: the version the
    provider boundary hashes is visible in what the boundary actually sees."""
    template, prompt_for = require(
        SYNTH_MODULE, "SYNTH_PROMPT_TEMPLATE_V", "prompt_for", issue=SYNTH_ISSUE
    )
    L1Request, L2Request, CriterionVerdict = require(
        SYNTH_MODULE, "L1Request", "L2Request", "CriterionVerdict", issue=SYNTH_ISSUE
    )

    assert template == "synth-prompt/1", (
        f"SYNTH_PROMPT_TEMPLATE_V is {template!r} — the pinned template version is "
        "a named configuration value (CT-SYNTH-11); a silent bump invalidates every "
        "dependent work id and must be a reviewable change, not a drift"
    )
    l1_payload = prompt_for(
        L1Request(
            run_id="r", submission_id="s", question_id="Q1",
            criterion_ids=("Q1C1",),
            verdicts=(CriterionVerdict("Q1C1", "j1", "high"),),
            evidence=("span",),
        )
    )
    l2_payload = prompt_for(
        L2Request(run_id="r", submission_id="s", syntheses=("prose",))
    )
    for payload, level in ((l1_payload, "L1"), (l2_payload, "L2")):
        rendered = dict(payload.fields).get("prompt_template_v")
        assert rendered == template, (
            f"the {level} prompt renders prompt_template_v={rendered!r} — the "
            "pinned version must appear in every synthesis prompt, or the "
            "provider-side cache and the work id key on different template "
            "generations"
        )


def test_tc_synth_c11_changing_the_template_invalidates_dependent_work():
    """`TC-SYNTH-C11` (P1, work-id half) — `prompt_template_version` is a
    `compute_work_id` input: identical inputs except the template version derive
    different work ids, so a template change invalidates the dependent work rather
    than silently reusing it."""
    template = require(SYNTH_MODULE, "SYNTH_PROMPT_TEMPLATE_V", issue=SYNTH_ISSUE)

    def _work_id(template_version: str) -> str:
        return compute_work_id(
            run_id="run-1",
            stage="synth",
            submission_id="SYN-001",
            criterion_id="Q1C1",
            judge_id=None,
            package_version_id="pkg-v1",
            panel_config="panel/1",
            prompt_template_version=template_version,
            extractor_version="extract/1",
        )

    assert _work_id(template) != _work_id("synth-prompt/2"), (
        "two work ids derived under different prompt template versions are equal — "
        "SYNTH_PROMPT_TEMPLATE_V is pinned as a work_id input (CT-SYNTH-11): change "
        "it and the dependent work must invalidate, or a template generation change "
        "silently reuses the previous generation's work identity"
    )


def test_tc_synth_c11_narrowing_the_pattern_list_releases_a_suppressed_narrative(
    tmp_data_dir,
):
    """`TC-SYNTH-C11` (P1, differential direction 1) — the SAME claim-bearing reply
    is suppressed under the default list and released under a narrowed one: the
    default list flags it after the re-request, the holistic-only narrowing passes
    it untouched. What gets suppressed moved with the configuration."""
    import aeh.synth as synth

    holistic_only = tuple(
        pattern for pattern in synth.SYNTH_SCORE_CLAIM_PATTERNS
        if "one of the" in pattern
    )
    assert holistic_only, "fixture bug: the holistic class pattern was not found"

    default_report, default_rows = _drive(
        tmp_data_dir / "default",
        _replies(_NUMERAL_CLAIM, 2), synth.SYNTH_SCORE_CLAIM_PATTERNS,
    )
    assert default_rows and default_rows[0]["score_claim_flag"] == 1, (
        f"the default list stored the numeral claim with flag "
        f"{default_rows[0]['score_claim_flag'] if default_rows else None!r} — "
        "control: the claim must be suppressed under the list that catches it, or "
        "the differential below proves nothing"
    )
    assert default_report.rejected_score_claims >= 1, (
        f"{default_report.rejected_score_claims} rejections under the default "
        "list — control: the claim must be counted as caught, or the release "
        "below proves nothing"
    )
    narrowed_report, narrowed_rows = _drive(
        tmp_data_dir / "narrowed", _replies(_NUMERAL_CLAIM, 2), holistic_only
    )
    assert narrowed_rows and narrowed_rows[0]["score_claim_flag"] == 0, (
        "the narrowed list still suppressed the claim — the differential needs the "
        "narrowed list to RELEASE what the default caught (CT-SYNTH-11: changing "
        "the list changes what gets suppressed)"
    )
    assert narrowed_report.rejected_score_claims == 0, (
        f"{narrowed_report.rejected_score_claims} rejections under the narrowed "
        "list — a released narrative must not be counted as caught, or the rate "
        "reads a prohibition the configuration no longer makes"
    )


def test_tc_synth_c11_extending_the_pattern_list_suppresses_a_paraphrase(
    tmp_data_dir,
):
    """`TC-SYNTH-C11` (P1, differential direction 2) — the same paraphrase reply is
    clean under the default list and suppressed when the list is extended with a
    pattern naming it. The suppression is specific: the untouched clean narrative
    stays clean under the extended list, so the change is visible where it acts."""
    import aeh.synth as synth

    extended = synth.SYNTH_SCORE_CLAIM_PATTERNS + (r"\bmodel response\b",)

    default_report, default_rows = _drive(
        tmp_data_dir / "default",
        _replies(_PARAPHRASE, 2), synth.SYNTH_SCORE_CLAIM_PATTERNS,
    )
    assert default_rows and default_rows[0]["score_claim_flag"] == 0, (
        "the paraphrase was suppressed under the DEFAULT list — the extension "
        "direction needs a text the default releases, or the differential proves "
        "nothing (adjust the fixture, not the list)"
    )

    extended_report, extended_rows = _drive(
        tmp_data_dir / "extended", _replies(_PARAPHRASE, 2), extended
    )
    assert extended_rows and extended_rows[0]["score_claim_flag"] == 1, (
        "the paraphrase the extension names was not suppressed — changing "
        "SYNTH_SCORE_CLAIM_PATTERNS must change what gets suppressed (CT-SYNTH-11), "
        "or the list is a constant nobody can review as a contract change"
    )
    assert extended_report.rejected_score_claims >= 1, (
        "the extended list's catches are not counted — the differential must be "
        "visible in the report's rejection count too"
    )

    # Specificity control: a clean narrative stays clean under the extension — and
    # the control drive consumes 2 replies (1 L1 + 1 L2: the clean L1 leaves the L2
    # gate open, unlike the flagged drives above, which skip it).
    control_report, control_rows = _drive(
        tmp_data_dir / "control", _replies(_CLEAN, 2), extended
    )
    assert control_rows and control_rows[0]["score_claim_flag"] == 0, (
        "the extension suppressed a narrative it does not name — the differential "
        "must be scoped to the added pattern, not a blanket flag"
    )
    assert control_report.rejected_score_claims == 0, (
        f"{control_report.rejected_score_claims} rejections on the clean control — "
        "the extension must not count a narrative it does not name as caught"
    )
