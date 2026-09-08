"""`M-SETUP`'s teacher-time budget, rung 4 — written ahead of #51/#52/#53 (issue #55).

`TC-SETUP-21` and `UAT-02` (test plan §5.6 / §6.3) share one scenario — a 15-criterion
package carried from four uploaded PDFs to a published version by one teacher — and so
share this file's fixture and flow helpers. The path is the headless one
(`SetupService` over real tiers, `CT-CONSOLE-01`): the transports are the only doubles;
the store, the ingest chain and the catalog are real (`stage_chain`).

Disclosures the plan's wording forces:

- **`tests/uat/` is new.** The repo had no UAT/rung-4 directory before this story (the
  rung-4 timing precedent, `TC-INGEST-47`, lives beside its module's integration
  files). The UAT cases are kept apart because their tier is the *business goal* —
  "setup takes minutes, not an evening" — not one module's behavior.
- **The 20-minute ceiling is reported, not machine-gated** (the `TC-INGEST-47`
  pattern): the guided path is timed with `time.perf_counter` around the whole teacher
  flow, the measurement is printed and embedded in the final assertion message, and the
  only timing assertion is `elapsed > 0`. The budget belongs to a teacher working at
  human speed; a CI box's wall clock measures the machine, not the teacher, and gating
  on it would make the suite flake on slow hardware rather than catch a wrong
  interaction count.
- **The interaction count is the gate.** NFR-SETUP-01 / NFR-SYS-07 / CT-SETUP-13 bound
  teacher time *structurally*: at most `SETUP_MAX_CONFIRMATIONS` (6) decomposability
  confirmations plus the two blocking screens — asserted exactly. The scripted replies
  make all 15 criteria unclear (so every one surfaces), which means an implementation
  that surfaces every criterion reds here; only the cap makes the count 6.
- **Stated bets**, the same policy as the rung-0 decomposition file: §3.6 pins the
  method signatures and `DecomposabilityVerdict`'s fields, not the model replies. The
  read-back reply's payload, the per-criterion classify replies, the empty dependency
  proposal reply, the `RubricReadback.criteria` accessor and the `CRIT-Q4/Q5/Q6` ids
  the answer keys name are this file's bets; when #51/#52/#53 land, the `_replies`,
  `_criterion_row` and `_criterion_ids` helpers are the lines that move — the
  per-case expectations (the counts, the blocking pair, the measured-not-gated budget)
  do not change. The confirmation count reads the per-verdict
  `needs_teacher_confirmation` flags, sharing `TC-SETUP-10`'s stated bet about where
  #52 enforces the cap.
- **UAT-02's "the teacher can state what the system will do with the rubric"** is
  pinned to the observable that exists today and §3.6 keeps stable: the enumerated step
  list (`TC-SETUP-03`'s shape) names a non-blocking `rubric_readback` step whose name
  and note say what the system will do with the stored rubric, and `headline()` states
  where the teacher stands. The console's rendering of that surface is the console's
  story (`FR-CONSOLE-25`), not this case's.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from tests.support.impl import SETUP_MODULE, require, require_attr
from tests.support.setup_harness import (
    ASSESSMENT_MD,
    INVENTORY_REPLY,
    SUBMISSION_MD,
    build_ingestor,
    stage_chain,
)

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

#: The five §5.3 questions, in the order the HLD names them.
FIVE_QUESTIONS = ("completeness", "non_interference", "independence", "additivity",
                  "gates")

#: The package size the budget is measured over: a 15-criterion rubric.
CRITERIA_COUNT = 15

#: The reference solution the teacher uploads alongside the assessment — one of the
#: four PDFs, and never read back as a rubric (a distinct transcript keeps that honest).
REFERENCE_MD = (
    "Reference solution — Physics 102\n"
    "\n"
    "Q1. Impulse is the net force acting over the contact time.\n"
    "\n"
    "Q3. Eliminating the flight time gives the range equation.\n"
    "\n"
    "Q4. (A)\n"
)

#: The 15-criterion rubric the scenario uploads — the document the read-back consumes.
RUBRIC_15_MD = (
    "Marking rubric — Physics 102 (15 criteria)\n"
    "\n"
    + "\n\n".join(
        f"CRIT-{index:02d} (Q{(index - 1) % 6 + 1}). The response carries the "
        f"Q{(index - 1) % 6 + 1} construct through to a stated result."
        for index in range(1, CRITERIA_COUNT + 1)
    )
    + "\n"
)


def _criterion_row(index: int) -> dict:
    """One read-back criterion row: two bands, descriptors stating what a response
    does, no magnitude phrasing (the shape FR-SETUP-04/05 demand of the read back)."""
    number = f"{index:02d}"
    question = f"Q{(index - 1) % 6 + 1}"
    return {
        "criterion_id": f"CRIT-{number}",
        "question_id": question,
        "kind": "open",
        "construct": f"the response carries the {question} construct through to a "
                     "stated result",
        "band_count": 2,
        "bands": [
            {"band_id": "met",
             "descriptor": f"the response carries the {question} construct through "
                           "to a stated result"},
            {"band_id": "not met",
             "descriptor": "the response stops before a stated result"},
        ],
    }


#: The read-back reply for `RUBRIC_15_MD`: all fifteen criteria in rubric order.
READBACK_REPLY = json.dumps(
    {"criteria": [_criterion_row(index) for index in range(1, CRITERIA_COUNT + 1)]}
)


def _unclear_reply(criterion_id: str) -> str:
    """One scripted §5.3 answer set for a borderline criterion: every question `yes`
    except an unclear additivity, plus a warning sign — the classifier must default
    `holistic` and surface it, so an uncapped implementation would request all
    fifteen confirmations and blow the budget."""
    return json.dumps({
        "criterion_id": criterion_id,
        "answers": {**{question: "yes" for question in FIVE_QUESTIONS},
                    "additivity": "unclear"},
        "warning_signs": ["straddles two constructs"],
        "reasoning": f"scripted unclear §5.3 answers for {criterion_id}",
    })


#: The dependency-proposal reply: nothing proposed, so nothing needs approval —
#: CT-SETUP-08's base case (a published package with an empty dependency graph).
DEPENDENCIES_REPLY = json.dumps({"proposals": []})


def _replies() -> list[str]:
    """The scripted reply sequence for one full guided path, in call order: the
    inventory proposal, the read back, one classify reply per criterion in read-back
    order, then the dependency proposals. Every later step (confirmations,
    grade policy, prefix budget, publish) takes no model call."""
    return (
        [INVENTORY_REPLY, READBACK_REPLY]
        + [_unclear_reply(f"CRIT-{index:02d}")
           for index in range(1, CRITERIA_COUNT + 1)]
        + [DEPENDENCIES_REPLY]
    )


def _ingest(chain, *, kind: str, transcript: str, name: str) -> str:
    """Ingest one single-page PDF of `kind` with its own canonical transcript."""
    source = chain.store.blobs().put(f"{name} bytes".encode())
    ingestor = build_ingestor(chain.store, transcript)
    return ingestor.ingest_document([source], kind=kind, filenames={source: name})


def _criterion_ids(readback) -> list[str]:
    """The criterion ids in read-back order — the one place the `RubricReadback` shape
    is touched, so a #51 that lands a different accessor moves this line only."""
    rows = list(readback.criteria)  # stated bet: the read-back carries its criteria
    return [row["criterion_id"] if isinstance(row, dict) else row.criterion_id
            for row in rows]


def _teacher_package(tmp_data_dir):
    """Four PDFs in, one published package out — the shared UAT scenario.

    Ingests one document of each kind (the HLD's four-PDF upload), requires every
    member the guided path waits on (naming the issue that owns each), then walks the
    path with the two blocking screens answered and every optional step taken at its
    default. Returns what the budget assertions read: the surfaced confirmations, the
    flow's wall clock and the published version id.
    """
    setup = require(SETUP_MODULE, "SetupService", issue="#51/#52/#53")
    require_attr(setup, "read_back_rubric", issue="#51")
    require_attr(setup, "classify_decomposability", issue="#52")
    require_attr(setup, "confirm_classifications", issue="#52")
    require_attr(setup, "propose_dependencies", issue="#52")
    require_attr(setup, "set_grade_policy", issue="#53")
    require_attr(setup, "check_prefix_budget", issue="#53")

    chain = stage_chain(tmp_data_dir)
    chain.provider.replies = _replies()

    assessment_doc = _ingest(chain, kind="assessment", transcript=ASSESSMENT_MD,
                             name="assessment.pdf")
    reference_doc = _ingest(chain, kind="reference", transcript=REFERENCE_MD,
                            name="reference.pdf")
    rubric_doc = _ingest(chain, kind="rubric", transcript=RUBRIC_15_MD,
                         name="rubric.pdf")
    submission_doc = _ingest(chain, kind="submission", transcript=SUBMISSION_MD,
                             name="submission.pdf")

    service = chain.service
    started = time.perf_counter()
    proposal = service.propose_inventory(assessment_doc)
    # Blocking screen 1 of 2 (S2, FR-SETUP-02): the teacher confirms what was proposed.
    service.confirm_inventory(proposal.proposal_id)
    # Blocking screen 2 of 2 (S3): the answer keys for the mcq questions' criteria,
    # named by the shipped criterion-id convention (`CRIT-Q4`, the rung-2 precedent).
    service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["A"], "CRIT-Q6": ["A"]})
    readback = service.read_back_rubric(rubric_doc, assessment_doc)
    ids = _criterion_ids(readback)
    verdicts = {criterion_id: service.classify_decomposability(draft)
                for criterion_id, draft in zip(ids, readback.criteria)}
    surfaced = [criterion_id for criterion_id in ids
                if verdicts[criterion_id].needs_teacher_confirmation]
    # The teacher answers the surfaced confirmations by accepting the default —
    # the cheap path the budget exists to protect.
    service.confirm_classifications(
        {criterion_id: verdicts[criterion_id].classification
         for criterion_id in surfaced}
    )
    service.propose_dependencies()  # rendered; the teacher approves none
    service.set_grade_policy(None)  # the default policy, applied and recorded as default
    service.check_prefix_budget()
    version_id = service.publish(approved_by="teacher-1")
    elapsed = time.perf_counter() - started

    assert len(ids) == CRITERIA_COUNT, (
        f"the scripted read-back carries {CRITERIA_COUNT} criteria but the service "
        f"read back {len(ids)} — the fixture and the flow must agree on the package "
        "size the budget is measured over"
    )
    return SimpleNamespace(
        chain=chain, ids=ids, verdicts=verdicts, surfaced=surfaced,
        version_id=version_id, elapsed=elapsed,
        assessment_doc=assessment_doc, reference_doc=reference_doc,
        rubric_doc=rubric_doc, submission_doc=submission_doc,
    )


# --- TC-SETUP-21 ---------------------------------------------------------------------------


def test_tc_setup_21_fifteen_criteria_cost_at_most_six_confirmations_and_two_screens(
    tmp_data_dir,
):
    """`TC-SETUP-21` (NFR-SETUP-01, NFR-SYS-07, P1) — a 15-criterion package, one
    teacher: the guided path costs exactly two blocking screens plus at most six
    decomposability confirmations, asserted exactly, because that structural bound is
    what "total teacher time is minutes" means for the system (CT-SETUP-13: the cap is
    enforced by this module, not the console). The scripted replies make all fifteen
    criteria surface, so only the cap makes the count six — an implementation that
    requests a confirmation per criterion breaks the budget here.

    The 20-minute budget is MEASURED, not gated (the `TC-INGEST-47` pattern): the
    whole flow is timed with `time.perf_counter`, the measurement is printed and
    embedded in the final assertion's message, and the only timing assertion is
    `elapsed > 0` — a CI box's wall clock is the machine's, not the teacher's."""
    fx = _teacher_package(tmp_data_dir)

    cap = require(SETUP_MODULE, "SETUP_MAX_CONFIRMATIONS", issue="#52")
    assert cap == 6, (
        "TC-SETUP-21: SETUP_MAX_CONFIRMATIONS is the Configuration block's declared "
        "cap; a different cap changes NFR-SETUP-01's teacher-time promise"
    )
    blocking = [step.step_id for step in fx.chain.service.steps().steps
                if step.blocking]
    assert blocking == ["inventory", "answer_keys"], (
        f"TC-SETUP-21: the blocking set is {blocking}, not the two screens "
        "NFR-SYS-07 names — a third blocking demand would break the teacher-time "
        "budget structurally (CT-SETUP-01: the blocking set has two members)"
    )
    assert len(fx.surfaced) == min(CRITERIA_COUNT, cap), (
        f"TC-SETUP-21: {len(fx.surfaced)} decomposability confirmations were "
        f"requested for {CRITERIA_COUNT} surfacing criteria — the cap ({cap}) must "
        "bind (FR-SETUP-07, CT-SETUP-13); an implementation that surfaces every "
        "criterion is the evening, not the minutes, NFR-SETUP-01 promises"
    )
    assert fx.version_id, (
        "TC-SETUP-21: the guided path did not end in a published version — the "
        "budget is only meaningful over a path a teacher can actually finish"
    )
    measured = (
        f"teacher wall clock {fx.elapsed:.3f}s over the full guided path "
        f"(four PDFs -> {CRITERIA_COUNT}-criterion package -> published "
        f"{fx.version_id!r}, {len(fx.surfaced)} confirmations + 2 blocking screens)"
    )
    print(f"\nTC-SETUP-21 measured: {measured}; NFR-SETUP-01 budget: 20 minutes "
          f"({20 * 60}s) — reported, not machine-gated")
    assert fx.elapsed > 0.0, (
        f"TC-SETUP-21 measured: {measured}; NFR-SETUP-01/NFR-SYS-07 budget: at most "
        f"{cap} confirmations plus the two blocking screens, under 20 minutes — the "
        "budget is reported here, not machine-gated (TC-INGEST-47 pattern)"
    )


# --- UAT-02 ---------------------------------------------------------------------------------


def test_uat_02_setup_takes_minutes_not_an_evening(tmp_data_dir):
    """`UAT-02` (NFR-SETUP-01, NFR-SYS-07) — **Given** four PDFs, **when** the teacher
    runs setup, **then** they answer two blocking screens and at most six optional
    confirmations; total elapsed teacher time is under 20 minutes, timed; and the
    teacher can state what the system will do with the rubric.

    Shares the scenario, fixture and flow with `TC-SETUP-21`. The UAT-shaped half this
    case adds is the teacher's model of the system, pinned to the observable step
    surface: the enumeration names a non-blocking `rubric_readback` step whose name and
    note state what the system will do with the stored rubric, and `headline()` states
    where the teacher stands. The console's rendering of that surface is
    `FR-CONSOLE-25`'s story, not this case's."""
    fx = _teacher_package(tmp_data_dir)

    # Given: the four PDFs are in — one of each kind, the HLD's upload set.
    for name, doc in (("assessment", fx.assessment_doc), ("reference", fx.reference_doc),
                      ("rubric", fx.rubric_doc), ("submission", fx.submission_doc)):
        assert doc, f"UAT-02: the {name} PDF did not produce an ingested document"

    # Then: two blocking screens answered; at most six optional confirmations.
    cap = require(SETUP_MODULE, "SETUP_MAX_CONFIRMATIONS", issue="#52")
    blocking = [step.step_id for step in fx.chain.service.steps().steps
                if step.blocking]
    assert blocking == ["inventory", "answer_keys"], (
        f"UAT-02: the scenario answers two blocking screens; the enumeration blocks "
        f"on {blocking}"
    )
    assert len(fx.surfaced) <= cap, (
        f"UAT-02: {len(fx.surfaced)} optional confirmations were requested — the "
        f"scenario promises at most {cap} (NFR-SYS-07)"
    )

    # The teacher can state what the system will do with the rubric: the step surface
    # names the read-back as an explained, non-blocking step.
    steps = {step.step_id: step for step in fx.chain.service.steps().steps}
    assert set(steps) == {"inventory", "answer_keys", "rubric_readback",
                          "decomposability", "grade_policy"}, (
        f"UAT-02: the enumerated steps drifted: {sorted(steps)} — the teacher's "
        "model of setup is the enumeration (TC-SETUP-03's shape)"
    )
    rubric_step = steps["rubric_readback"]
    assert rubric_step.blocking is False, (
        "UAT-02: the rubric read-back must not be a third blocking screen — it is "
        "one of the optional steps the budget counts separately"
    )
    assert rubric_step.name and rubric_step.note, (
        "UAT-02: the rubric_readback step is enumerated without a name or note — "
        "the teacher could not state what the system will do with the rubric from "
        "a blank (NFR-SETUP-04's present-and-explained convention)"
    )
    assert fx.chain.service.steps().headline(), (
        "UAT-02: the progress surface has no headline — the teacher cannot state "
        "where they stand (NFR-SETUP-04)"
    )

    measured = (
        f"teacher wall clock {fx.elapsed:.3f}s over the full guided path "
        f"(four PDFs -> {CRITERIA_COUNT}-criterion package -> published "
        f"{fx.version_id!r}, {len(fx.surfaced)} confirmations + 2 blocking screens)"
    )
    print(f"\nUAT-02 measured: {measured}; business goal: setup takes minutes, not "
          f"an evening (under {20 * 60}s of teacher time) — reported, not "
          "machine-gated")
    assert fx.elapsed > 0.0, (
        f"UAT-02 measured: {measured}; sign-off criterion: total elapsed teacher "
        "time under 20 minutes, timed — the reading is reported here, not "
        "machine-gated (TC-INGEST-47 pattern)"
    )
