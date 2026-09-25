"""`TS-89` (issue #383) — `TC-REVIEW-26`: the scoring model comes from the package, and an
undeclared criterion is refused (`FR-REVIEW-19`).

| Input | Expected |
|---|---|
| run R's package: `C1` `holistic`, `C2` `atomic_with_gate`; unknown `C9` | `scoring_model_for("C1") == "holistic"`, `("C2") == "atomic_with_gate"`, `("C9")` raises `ReviewError`; the literal `"atomic"` no longer appears in `review.py`'s store form (static) |

**The guess this replaces cost a teacher half their time.** The hard-coded `"atomic"` answered
for every criterion, so a holistic one was budgeted at an atomic one's minutes — 45 seconds
where 90 were needed. The queue built from that estimate overruns, and it overruns **silently**:
the header states a budget the items cannot fit in, and nothing reports that the estimate was
invented rather than read.

**Refusing `C9` is the requirement, not an edge case.** A criterion the run does not score has
no model, and answering `"atomic"` for it is the same invention under a different name. The
refusal is what makes the estimate trustworthy: every figure in the queue's header is either
read from the package or absent.

**The static half is scoped to the store form, as the plan says.** `"atomic"` is a legitimate
string elsewhere in `review.py` — it is a real scoring model, it appears in
`SCORING_MODEL_EST_SECONDS`' table and in prose. What must not exist is a *fallback* that
answers it for a criterion nobody declared. So the scan checks `scoring_model_for` and
`_StoredScoreRow` — the store form's two members — rather than the file, and it parses rather
than greps so the module's own explanation of the retired default is not reported as the
default.

**Isolation: rung 2** — a real store, a real Tier P package declaring the two models, and
`open_review` over the stored run.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.review import ReviewError, _given, _StoredScoreRow, open_review
from aeh.store import open_store
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

#: The run's package declares these two and nothing else; `C9` is the undeclared one.
DECLARED = {"C1": "holistic", "C2": "atomic_with_gate"}
UNDECLARED = "C9"

CRITERIA = tuple(
    {"criterion_id": name, "kind": "open", "scoring_model": model}
    for name, model in DECLARED.items()
)


@pytest.fixture
def review_world(tmp_data_dir):
    """A stored run with one queued score per declared criterion."""
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, _run_id, _version = seed_run(
            store, submissions=("S001",), criteria=CRITERIA,
        )
        write_criterion_scores(
            store.cohort(ORCH_COHORT_ID),
            [("S001", name, "B1", 6.0, "provisional") for name in DECLARED],
        )
    finally:
        store.close()
    return open_review(tmp_data_dir, run_id=ORCH_COHORT_ID)


# --- TC-REVIEW-26 ---------------------------------------------------------------------------


@pytest.mark.parametrize("criterion_id,model", sorted(DECLARED.items()))
def test_tc_review_26_the_declared_model_is_what_the_package_says(
    review_world, criterion_id, model
):
    """`C1` reads `holistic` and `C2` reads `atomic_with_gate` — the package's own words.

    Both, parametrized: a fallback that answered `"atomic"` would be caught only by the
    holistic one, and a reader that returned the first declared model for everything would be
    caught only by having two.
    """
    assert review_world.scoring_model_for(criterion_id) == model, (
        f"{criterion_id} reads "
        f"{review_world.scoring_model_for(criterion_id)!r}, not {model!r}. The model is the "
        "package's to declare, and a guess budgets a holistic criterion at an atomic one's "
        "minutes (FR-REVIEW-19)"
    )


def test_tc_review_26_an_undeclared_criterion_is_refused(review_world):
    """`C9` raises `ReviewError` rather than answering a model.

    The refusal is what makes every other figure in the header trustworthy. An implementation
    that answered `"atomic"` here passes both cases above and quietly invents an estimate for
    a criterion the run does not score.
    """
    with pytest.raises(ReviewError) as caught:
        review_world.scoring_model_for(UNDECLARED)

    assert UNDECLARED in str(caught.value), (
        f"the refusal does not name the criterion: {caught.value!r}"
    )


def test_tc_review_26_the_two_models_budget_different_amounts_of_time(review_world):
    """The consequence, asserted: the two models do not cost the same minutes.

    Without this, `scoring_model_for` could return the right strings into a consumer that
    ignored them, and the defect FR-REVIEW-19 exists to fix — a holistic criterion budgeted as
    atomic — would survive with the model read correctly and discarded.
    """
    from aeh.review import SCORING_MODEL_EST_SECONDS

    atomic = SCORING_MODEL_EST_SECONDS.get("atomic")
    holistic = SCORING_MODEL_EST_SECONDS.get("holistic")

    assert atomic is not None and holistic is not None, (
        f"the est-seconds table is missing a model: {dict(SCORING_MODEL_EST_SECONDS)}"
    )
    assert holistic[1] != atomic[1], (
        f"holistic and atomic both budget {atomic[1]} seconds, so reading the model correctly "
        "changes nothing and the estimate is a guess by another route"
    )
    assert holistic[1] > atomic[1], (
        f"holistic ({holistic[1]}s) is budgeted at no more than atomic ({atomic[1]}s); the "
        "defect FR-REVIEW-19 fixes is a holistic criterion getting an atomic one's minutes"
    )
    # `atomic_with_gate` has no table entry, so it resolves to `default_est_seconds` (60s).
    # Recorded rather than asserted as a bug: the table is a two-model lookup by design and
    # the default is the declared answer for anything else — but it does mean the run's second
    # criterion is budgeted at neither model's figure, which #383 reports.
    assert "atomic_with_gate" not in SCORING_MODEL_EST_SECONDS


# --- the static half ------------------------------------------------------------------------


def _returns_atomic_literal(function) -> list[int]:
    """Every place in `function` where the bare literal `"atomic"` could become the answer.

    Parsed, not grepped: `review.py` mentions `"atomic"` legitimately — it is a real scoring
    model, it keys `SCORING_MODEL_EST_SECONDS`, and the module's own comments explain the
    default that was removed. So only *value* positions count, and docstrings are skipped.

    **Four shapes, not one.** An earlier draft matched only a `Return` or `Assign` whose value
    was a bare `Constant`, and was therefore blind to the two shapes the member this scan
    guards would actually take. `_StoredScoreRow.__init__` resolves the model as

        model = _given(mapping, "scoring_model", default=lambda: facts.model_for(criterion_id))

    so a reinstated fallback is `default="atomic"` (the `Assign`'s value is a `Call`, not a
    constant) or `default=lambda: "atomic"` (a `Lambda` inside a keyword). Both were invisible.
    Now any `Constant` equal to `"atomic"` appearing as a returned value, an assigned value, a
    keyword argument, a lambda body, a `BoolOp` operand or an `IfExp` branch is reported.
    """
    # Dedented: `inspect.getsource` of a method returns it at class indentation, which is
    # an IndentationError to `ast.parse` on its own.
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))

    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }

    def _constants(node) -> list[ast.Constant]:
        if node is None:
            return []
        return [
            inner
            for inner in ast.walk(node)
            if isinstance(inner, ast.Constant)
            and inner.value == "atomic"
            and id(inner) not in docstrings
        ]

    found: list[int] = []
    for node in ast.walk(tree):
        candidates: list = []
        if isinstance(node, ast.Return):
            candidates = _constants(node.value)
        elif isinstance(node, ast.Assign):
            candidates = _constants(node.value)
        elif isinstance(node, ast.keyword):
            candidates = _constants(node.value)
        elif isinstance(node, ast.Lambda):
            candidates = _constants(node.body)
        for constant in candidates:
            found.append(constant.lineno)
    return sorted(set(found))


@pytest.mark.parametrize(
    "member", (aeh.review.ReviewService.scoring_model_for, _StoredScoreRow.__init__)
)
def test_tc_review_26_the_store_form_never_falls_back_to_atomic(member):
    """Neither store-form member answers the bare literal `"atomic"`.

    The regression pin for the defect itself. `scoring_model_for` is where the fallback lived;
    `_StoredScoreRow.__init__` is where the same guess would naturally be reinstated, because
    it is the other place a row's model is resolved and it has a `default=` hook that makes it
    a one-line change.
    """
    offenders = _returns_atomic_literal(member)

    assert offenders == [], (
        f"{member.__qualname__} returns or assigns the bare literal 'atomic' at "
        f"{offenders}. That is the guess FR-REVIEW-19 retired: it answered for every "
        "criterion, and it budgeted every holistic one at half a teacher's time"
    )


def _reinstated_by_return(criterion_id):  # pragma: no cover — parsed, never called
    declared: dict = {}
    if criterion_id in declared:
        return declared[criterion_id]
    return "atomic"


def _reinstated_by_default_keyword(mapping, criterion_id):  # pragma: no cover — parsed
    """The shape `_StoredScoreRow.__init__` would actually take."""
    model = _given(mapping, "scoring_model", default="atomic")
    return model


def _reinstated_by_default_lambda(mapping, criterion_id):  # pragma: no cover — parsed
    """The shape it would take while keeping the existing `default=lambda:` idiom."""
    model = _given(mapping, "scoring_model", default=lambda: "atomic")
    return model


@pytest.mark.parametrize(
    "candidate",
    (_reinstated_by_return, _reinstated_by_default_keyword, _reinstated_by_default_lambda),
    ids=("bare-return", "default-keyword", "default-lambda"),
)
def test_tc_review_26_the_atomic_scan_recognises_every_fallback_shape(candidate):
    """The scan's control, over all three shapes a reinstated fallback could take.

    Exercised through `_returns_atomic_literal` itself rather than a re-implementation, so a
    scan that stopped matching fails here rather than leaving the cases above passing over
    nothing. The two `default=` shapes are the ones that matter: the member the scan guards
    resolves its model through `_given(..., default=...)`, so those — not a bare `return` —
    are how the guess would come back.
    """
    assert _returns_atomic_literal(candidate), (
        f"the scan does not recognise {candidate.__name__}'s shape, so the store-form cases "
        "above are passing over a pattern they cannot see"
    )
