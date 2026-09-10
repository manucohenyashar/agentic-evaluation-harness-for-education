"""`TC-AGG-C16` — `confidence` is not a probability, and nothing treats it as one (§6.11.12).

`CT-AGG-16` (**not promised**): "`confidence` is not a probability and must not be
presented as one. It is a bounded score combining agreement with integrity caps,
calibrated against nothing at Phase 1. Consumers may rank by it and threshold on it;
they may not say 'we are 80% sure'."

Two limbs:

- **the computation ban** (rung 0, executable now): nothing downstream feeds it
  into a computation that presumes a probability scale — the clause's named shape
  is **multiplying two confidences**. An AST scan over every shipped module runs
  the detector, validated against inline positive controls first. `aeh.agg` is
  excluded by name: it is where the figure is DEFINED, and the policy's own
  sanctioned arithmetic (cap `min`s, the escalation's weighted self-confidence)
  lives there — the clause binds the consumers. The permitted uses stay permitted:
  the shipped routing thresholds ON confidence, and that use is asserted live so
  the scan cannot drift into banning use altogether;
- **the presentation sweep** (rung 3, writtenahead per consumer — M-REVIEW's param
  runs since #108's landing; M-GRADE #101 and M-CONSOLE #123 stay red by design): each
  consumer's presentation of a low-confidence
  queued row carries no percentage framing, no "probability", no calibration
  language — "0.62" as a bare figure is the permitted thresholding input; "62%
  sure" is the violation, and it is violated in the UI layer and nowhere else,
  which is why the sweep reads rendered artifacts.

Isolation: rung 0 for the scan and the permitted-use smoke; rung 2 (real SQLite,
seeded cohort) for the rows the consumer sweep presents; the socket guard is
autouse.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import aeh
from aeh.store import open_store
from tests.support.agg_vocabulary import (
    band,
    criterion,
    panel,
    signals,
    agg_config,
)
from tests.support.impl import (
    AGG_MODULE,
    CONSOLE_MODULE,
    GRADE_MODULE,
    REVIEW_MODULE,
    require,
)
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort

pytestmark = [pytest.mark.contract]

_FOUR_BAND = criterion([band("B0", 0, 0.0), band("B1", 1, 1.0), band("B2", 2, 3.0),
                        band("B3", 3, 6.0)])
_UNANIMOUS_TOP = panel(("B3", 3), ("B3", 3), ("B3", 3))

#: The definition site: the policy that owns the figure's own arithmetic.
_DEFINITION_MODULE = "agg"

#: The binary operations that presume a probability scale when BOTH operands
#: carry a confidence figure — the clause's named shape (`Mult`), and its
#: compounding cousin (`Pow`).
_SUSPECT_OPS = (ast.Mult, ast.Pow)

#: The presentation framings the clause forbids, as substrings: a percentage
#: figure ("80%"), and the calibration vocabulary. A bare "0.62" is NOT here —
#: thresholding on the figure is the permitted use.
_FORBIDDEN_FRAMINGS = ("%", "probability", "prob.", "calibrat", "likelihood",
                       "confidence interval", "sure that")

_COHORT = ORCH_COHORT_ID
_SUBMISSION = "SYN-C16"
_CRITERION = "C-LOW"


def _confidence_names(node):
    """Every name in one operand's subtree that carries a confidence figure —
    a bare name, an attribute, or a string naming the column."""
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and "confidence" in sub.id.lower():
            names.add(sub.id)
        elif isinstance(sub, ast.Attribute) and "confidence" in sub.attr.lower():
            names.add(sub.attr)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                and "confidence" in sub.value.lower():
            names.add(sub.value)
    return names


def _multiplied_confidences(tree):
    """Every `(module, line, names)` where one binary operation combines TWO
    confidence-bearing operands — the clause's named computation."""
    sites = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, _SUSPECT_OPS):
            continue
        left, right = _confidence_names(node.left), _confidence_names(node.right)
        if left and right:
            sites.append((sorted(left), sorted(right), node.lineno))
    return sites


def test_tc_agg_c16_nothing_multiplies_two_confidences():
    """`TC-AGG-C16` (`CT-AGG-16`, behaviour / rung 0, artifact assertion, P0) —
    no shipped module composes two confidence figures into one number. The
    scanner is validated first: a synthetic multiply of two confidences must be
    flagged, and the policy's own sanctioned shapes — a confidence times a
    CONSTANT, the cap `min` — must not be. `aeh.agg` is excluded because it is
    where the figure is defined; the clause binds what consumes it."""
    src = Path(aeh.__file__).parent

    # Positive controls: the detector catches the named computation, and does
    # not flag the sanctioned single-confidence arithmetic.
    guilty = ast.parse("total = score.confidence * verdict.self_confidence\n")
    assert _multiplied_confidences(guilty), (
        "fixture bug: the scanner no longer detects two multiplied confidences"
    )
    compounding = ast.parse("compound = a.confidence ** b.self_confidence\n")
    assert _multiplied_confidences(compounding), (
        "fixture bug: the scanner no longer detects compounded confidences"
    )
    innocent = ast.parse("weighted = confidence * 0.25\nfloor = min(confidence, cap)\n")
    assert _multiplied_confidences(innocent) == [], (
        "fixture bug: the scanner flags single-confidence arithmetic — the "
        "clause permits ranking and thresholding, and an over-broad scan would "
        "forbid the policy's own sanctioned computation"
    )

    offenders: dict[str, list] = {}
    for path in sorted(src.glob("*.py")):
        if path.stem == _DEFINITION_MODULE:
            continue
        sites = _multiplied_confidences(ast.parse(path.read_text(encoding="utf-8")))
        if sites:
            offenders[path.stem] = sites

    assert offenders == {}, (
        f"modules {sorted(offenders)} multiply two confidences — a confidence "
        "is a bounded score calibrated against nothing at Phase 1, and "
        "composing two of them presumes a probability scale the figure does "
        "not have (CT-AGG-16)"
    )


def test_tc_agg_c16_the_permitted_uses_remain_permitted():
    """`TC-AGG-C16` (`CT-AGG-16`, behaviour / rung 0, permitted-use smoke, P0) —
    the two permitted uses stay live: the shipped policy thresholds ON the
    confidence (routing `auto` iff `confidence >= threshold`) and ranks by it.
    The scan above bans a computation, not the figure; this assertion keeps the
    ban from drifting into banning use."""
    aggregate = require(AGG_MODULE, "aggregate", issue="#91")

    unanimous = aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(),
                          config=agg_config())
    capped = aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(spans_verified=False),
                       config=agg_config())
    assert unanimous.confidence > capped.confidence, (
        "fixture bug: the two cells' confidences did not order"
    )
    assert unanimous.routing == "auto" and capped.routing == "queued", (
        f"thresholding on confidence stopped routing "
        f"({unanimous.routing!r}/{capped.routing!r}) — ranking and thresholding "
        "on the figure are the clause's PERMITTED uses (CT-AGG-16), and the "
        "shipped routing must keep using it"
    )


def _queued_low_confidence_row(aggregate):
    """The presentation sweep's row: a queued, low-confidence score — the figure
    whose presentation the clause binds."""
    return aggregate(_UNANIMOUS_TOP, _FOUR_BAND, signals(spans_verified=False),
                     config=agg_config())


@pytest.mark.parametrize(
    "consumer, module, entry, issue",
    [
        # Per-param keying, the sweep's own per-row convention: M-REVIEW's param
        # runs since #108's landing; the other two consumers are unlanded and
        # stay red by design until their stories land.
        pytest.param("M-GRADE", GRADE_MODULE, "apply_policy", "#101",
                     marks=pytest.mark.writtenahead),
        pytest.param("M-REVIEW", REVIEW_MODULE, "rank_queue_items", "#108"),
        pytest.param("M-CONSOLE", CONSOLE_MODULE, "render_review_queue", "#123",
                     marks=pytest.mark.writtenahead),
    ],
    ids=["m_grade", "m_review", "m_console"],
)
def test_tc_agg_c16_no_consumer_renders_confidence_as_a_probability(
    consumer, module, entry, issue, tmp_data_dir
):
    """`TC-AGG-C16` (`CT-AGG-16`, contract / rung 2-3, consumer presentation
    sweep, P0) — each consumer's presentation of the low-confidence queued row
    carries no percentage framing, no "probability", no calibration language:
    "0.62" as a bare figure is the permitted thresholding input; "62% sure" is
    the clause's named violation, violated in the UI layer and nowhere else."""
    surface = require(module, entry, issue=issue)
    aggregate = require(AGG_MODULE, "aggregate", issue="#91")
    score = _queued_low_confidence_row(aggregate)

    if consumer == "M-GRADE":
        from aeh.pkg import default_grade_policy

        rendered = surface([score], default_grade_policy())
    else:
        store_dir = tmp_data_dir / consumer.replace("-", "_").lower()
        store_dir.mkdir()
        store = open_store(store_dir)
        try:
            seed_cohort(store, [_SUBMISSION])
            cohort = store.cohort(_COHORT)
            with cohort.transaction() as tx:
                tx.execute(
                    "INSERT INTO criterion_score (submission_id, criterion_id, "
                    "band, points, judge_count, agreement, state, routing) "
                    "VALUES (:sid, :cid, :band, :points, :jc, :agreement, "
                    ":state, :routing)",
                    sid=_SUBMISSION, cid=_CRITERION, band=score.band,
                    points=score.points, jc=score.judge_count,
                    agreement=score.agreement, state=score.state,
                    routing=score.routing,
                )
            if consumer == "M-REVIEW":
                # Declared assumption (reconciled at #108's landing): the ranker
                # takes the stored rows and returns the ranked queue.
                rows = cohort.query(
                    "SELECT * FROM criterion_score WHERE submission_id = :s",
                    s=_SUBMISSION,
                )
                rendered = surface(rows)
            else:
                rendered = surface(store).render_scores(_SUBMISSION)
        finally:
            store.close()

    text = rendered if isinstance(rendered, str) else str(rendered)
    forbidden = [
        framing for framing in _FORBIDDEN_FRAMINGS if framing in text.lower()
    ]
    assert forbidden == [], (
        f"{consumer} renders the confidence with {forbidden} — a confidence is "
        "not a probability (CT-AGG-16): it may rank and it may threshold, but "
        "no consumer says 'we are 80% sure' of a figure calibrated against "
        "nothing"
    )
