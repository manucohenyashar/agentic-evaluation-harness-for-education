"""`TC-AGG-C18`, `C19` and `C21` — sole judged-score writership, `write_score`'s atomicity, and
the signal field set (§6.11, `CT-AGG-18/19/21`).

| Case | Clause | The violation it catches |
|---|---|---|
| `C18` | only M-AGG writes a judged `criterion_score`, only M-DET a deterministic one | `GradingService.compute_all` "repairing" a missing score with a provisional band |
| `C19` | `write_score` is a participant, not a transaction owner | `write_score` committing internally "for safety" |
| `C21` | `aggregation_signals` is six names with per-cap counts | a key renamed, or the caps collapsed into one total |

**C18's adversarial construction is the one to keep in mind**: a grading service that wrote a
row to fill a hole. Every `TC-GRADE` case that asserts a total stays green — the total is now
computable — and the score has no panel behind it. A census is the only oracle that sees it,
because the row it writes is a legal row.

**C19's third arm is the one that matters.** A `write_score` that opened its own transaction
would make `FR-ORCH-09`'s same-transaction guarantee a promise rather than a parameter: the
verdict and the score it implies could then commit separately, and a crash between them leaves
exactly the partial write `CT-STORE-03` forbids.

**C21's per-cap dimensionality is the contract.** One `caps_fired` total tells a moderation
meeting that something was capped; `{"ocr_overlap_risk": 12}` tells them the scans are bad.
Collapsing them keeps the key and loses the finding.

**Isolation: rung 0 for the censuses, rung 2 for the behaviour.**
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
import re
from typing import Any

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
from aeh.agg import AGG_CAP_TABLE, AggregationSignals, aggregation_signals
from aeh.store import open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = [pytest.mark.contract, pytest.mark.integration]

SUBMISSION = "S01"
CRITERION = "C1"
CRITERIA = ({"criterion_id": CRITERION, "kind": "open", "scoring_model": "atomic"},)

#: `CT-AGG-15`/`-21`'s declared signal names.
DECLARED_SIGNAL_FIELDS = {
    "band_histogram",
    "band_spread_distribution",
    "agreement_distribution",
    "escalation_rate",
    "auto_accept_rate",
    "caps_fired",
}

#: The two modules that may write `criterion_score`, and the statement each is allowed.
#: `det.py` has two because a key correction is a second evaluation under the corrected key
#: (`upsert_rederived_score`, `det.py:708`) — it lands on the same row and is M-DET's own,
#: which is the clause's point rather than an exception to it.
SANCTIONED_SCORE_WRITERS = {
    "agg.py": ["upsert_criterion_score"],
    "det.py": ["upsert_criterion_score", "upsert_rederived_score"],
}

#: Every other module that could reach the table. `pipeline.py` is on the list because
#: `CT-PIPE-05` forbids it SQL at all, so a write here would break two clauses at once.
SCANNED_MODULES = (
    "agg.py", "det.py", "synth.py", "grade.py", "review.py", "console.py", "pipeline.py",
)

#: `criterion_score` as the TARGET of a write, not merely mentioned in one. Anchored on
#: `INTO`/`UPDATE` so a migration that reads the old table while inserting into
#: `criterion_score_new` is not reported — `agg.py:1735` is exactly that, and a looser
#: pattern flags M-AGG's own schema history as a second writer.
_SCORE_WRITE = re.compile(
    r"(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|REPLACE\s+INTO|UPDATE)\s+criterion_score\s*[(\s]",
    re.IGNORECASE,
)


def _score_write_sites(module_name: str, source_text: str | None = None) -> list[str]:
    """Named statements in `module_name` that write `criterion_score`.

    Parsed rather than grepped: every one of these modules discusses the table in prose, and a
    text scan would report all seven. A dict entry is reported by its key, so a failure names
    the statement rather than a line that moves.
    """
    if source_text is None:
        path = pathlib.Path(aeh.agg.__file__).parent / module_name
        if not path.exists():
            return []
        source_text = path.read_text(encoding="utf-8")
    tree = ast.parse(source_text)

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

    found: list[str] = []
    attributed: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            constants = [
                inner for inner in ast.walk(value)
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str)
            ]
            if _SCORE_WRITE.search("".join(c.value for c in constants)) and isinstance(
                key, ast.Constant
            ):
                found.append(str(key.value))
                attributed.update(id(c) for c in constants)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings or id(node) in attributed:
            continue
        if _SCORE_WRITE.search(node.value):
            found.append(f"<literal@{node.lineno}>")
    return sorted(set(found))


# --- TC-AGG-C18 ----------------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", SCANNED_MODULES)
def test_tc_agg_c18_only_agg_and_det_write_a_criterion_score(module_name):
    """The census: `criterion_score` has exactly two writing statements, one per module.

    The construction this catches is a grading service that "repairs" a missing score by
    writing a row with the provisional band. Every `TC-GRADE` case asserting a total stays
    green — the total becomes computable — and the score has no panel behind it. Only a census
    sees that, because the row it wrote is a legal row.
    """
    sites = _score_write_sites(module_name)

    assert sites == SANCTIONED_SCORE_WRITERS.get(module_name, []), (
        f"{module_name} writes criterion_score at {sites}, not "
        f"{SANCTIONED_SCORE_WRITERS.get(module_name, [])}. A judged score is M-AGG's and a "
        "deterministic one is M-DET's; a third writer produces a score with no panel behind "
        "it, and the row is indistinguishable from a real one (CT-AGG-18)"
    )


def test_tc_agg_c18_the_score_census_recognises_a_write_it_forbids():
    """The census's control, through `_score_write_sites` itself.

    Without it the seven module cases above pass whenever the scan stops matching, which is
    indistinguishable from success.
    """
    probe = (
        'STATEMENTS = {\n'
        '    "repair_score": Statement(\n'
        '        "INSERT INTO criterion_score (run_id, band) VALUES (:r, :b)"\n'
        '    ),\n'
        '}\n'
    )
    assert _score_write_sites("probe.py", probe) == ["repair_score"], (
        "the census does not recognise a plain INSERT into criterion_score"
    )


def test_tc_agg_c18_the_test_support_seeding_helpers_are_a_reported_residual():
    """`tests/support` still seeds `criterion_score` directly, and the plan expects that.

    The plan's own words: "The same scan over `tests/support/*.py` flags the seeding helpers
    named in §4.2; the case is red until they are retired." They are not retired — nine of the
    suites in this repo, including several written in this change, stand on
    `grade_vocabulary.write_criterion_scores`, which is a **disclosed** M-AGG stand-in.

    So the residual is pinned rather than asserted away: this case fails the day the helpers
    go, which is when the clause becomes assertable at full strength. Asserting zero now would
    put a permanently red case in the suite over scaffolding the plan itself sanctions.
    """
    support = pathlib.Path(aeh.agg.__file__).parent.parent.parent / "tests" / "support"
    seeding = sorted(
        path.name for path in support.glob("*.py")
        if _score_write_sites(path.name, path.read_text(encoding="utf-8"))
    )

    assert seeding, (
        "no test-support module seeds criterion_score any more — the §4.2 helpers have been "
        "retired and CT-AGG-18's rung-0 scan can now include tests/support. Delete this case "
        "and extend the census above (#389 reported the residual)"
    )
    assert "grade_vocabulary.py" in seeding, (
        f"the seeding helpers moved: {seeding}. The census has to follow them"
    )


# --- TC-AGG-C19 ----------------------------------------------------------------------------------


def _scored_world(tmp_data_dir):
    store = open_store(tmp_data_dir)
    orchestrator, run_id, _version = seed_run(
        store, submissions=(SUBMISSION,), criteria=CRITERIA,
    )
    orchestrator.enumerate_units(run_id)
    return store, run_id


def _score() -> Any:
    """One aggregated score in the shape `write_score` persists."""
    from aeh.agg import CriterionScore

    return CriterionScore(
        criterion_id=CRITERION, band="B3", ordinal=3, points=6.0,
        modal_band="B3", band_spread=0, judge_count=3, agreement=1.0,
        agreement_degenerate=False, histogram={"B3": 3},
        state="final", routing="auto",
    )


def _signals() -> Any:
    """The six integrity inputs `write_score` records beside the score."""
    from types import SimpleNamespace

    return SimpleNamespace(
        spans_verified=True, evidence_present=True, sufficiency_flag=False,
        ocr_overlap_risk=False, described_evidence=False, extractor_disagreement=False,
        caps_fired=(),
    )


def _score_rows(store: Any, run_id: str) -> list[tuple]:
    from aeh.store import Statement

    return [
        tuple(row) for row in store.cohort(ORCH_COHORT_ID).query(
            Statement(
                "SELECT submission_id, criterion_id, band FROM criterion_score "
                "WHERE run_id = :r ORDER BY submission_id, criterion_id"
            ),
            r=run_id,
        )
    ]


def test_tc_agg_c19_write_score_never_opens_a_transaction_of_its_own(tmp_data_dir):
    """`write_score` takes a transaction; it does not create one.

    The clause's third arm, asserted at the signature rather than by watching for a `BEGIN`:
    a function whose first parameter is the caller's `tx` cannot commit independently, and one
    that opened its own could. `FR-ORCH-09`'s same-transaction guarantee is a *parameter*, not
    a promise — a verdict and the score it implies commit together or not at all, and a
    `write_score` that committed internally would make a crash between them leave exactly the
    partial write `CT-STORE-03` forbids.
    """
    import inspect

    from aeh.agg import write_score

    signature = inspect.signature(write_score)
    parameters = list(signature.parameters)
    assert parameters and parameters[0] == "tx", (
        f"write_score's first parameter is {parameters[:1]}, not `tx`. The caller's "
        "transaction is the first argument precisely so the function cannot own one "
        "(CT-AGG-19, CT-ORCH-08)"
    )

    assert parameters[1:4] == ["run_id", "submission_id", "score"], (
        f"write_score's leading parameters are {parameters[:5]}; the case's calls below are "
        "written against (tx, run_id, submission_id, score, signals)"
    )

    # Parsed, not substring-matched: `write_score`'s own docstring explains the contract with
    # the words `with handle.transaction() as tx`, so a text scan reports the explanation as
    # the violation. Only a real call node counts.
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(write_score)))
    owned = sorted({
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("transaction", "commit", "rollback")
    })
    assert owned == [], (
        f"write_score calls {owned}. It is a participant in the caller's transaction, not an "
        "owner: a function that committed internally would let the verdict and the score it "
        "implies commit separately, and a crash between them is the partial write "
        "CT-STORE-03 forbids"
    )


def test_tc_agg_c19_a_rolled_back_transaction_leaves_no_score(tmp_data_dir):
    """`write_score` inside a transaction that then raises leaves zero rows.

    The behavioural half of the same property. A `write_score` that committed internally
    "for safety" passes every happy-path case and leaves this one with a row the caller
    explicitly abandoned.
    """
    from aeh.agg import write_score

    store, run_id = _scored_world(tmp_data_dir)
    try:
        before = _score_rows(store, run_id)

        with pytest.raises(RuntimeError):
            with store.cohort(ORCH_COHORT_ID).transaction() as tx:
                write_score(tx, run_id, SUBMISSION, _score(), _signals())
                raise RuntimeError("the caller abandons its transaction")

        assert _score_rows(store, run_id) == before, (
            f"a rolled-back transaction left a score behind: {_score_rows(store, run_id)}. "
            "write_score is a participant in the caller's transaction, so the caller's abort "
            "is the score's abort (CT-AGG-19)"
        )
    finally:
        store.close()


def test_tc_agg_c19_two_identical_writes_leave_one_row(tmp_data_dir):
    """Redelivery is a no-op: the same score written twice is one row.

    The upsert is what makes a retried verdict safe. Without it a redelivered message would
    produce a second row for one cell, and every reader keyed on `(run, submission, criterion)`
    would see whichever the query returned first.
    """
    from aeh.agg import write_score

    store, run_id = _scored_world(tmp_data_dir)
    try:
        for _ in range(2):
            with store.cohort(ORCH_COHORT_ID).transaction() as tx:
                write_score(tx, run_id, SUBMISSION, _score(), _signals())

        rows = _score_rows(store, run_id)
        assert len(rows) == 1, f"two identical writes produced {len(rows)} rows: {rows}"
    finally:
        store.close()


# --- TC-AGG-C21 ----------------------------------------------------------------------------------


def test_tc_agg_c21_the_signal_field_set_is_exactly_the_declared_six():
    """`AggregationSignals`' fields equal the six declared names.

    Asserted on the dataclass, so an empty run cannot make the set look right by carrying
    nothing.
    """
    fields = {field.name for field in dataclasses.fields(AggregationSignals)}

    assert fields == DECLARED_SIGNAL_FIELDS, (
        f"AggregationSignals carries {sorted(fields)}; the contract names "
        f"{sorted(DECLARED_SIGNAL_FIELDS)} (CT-AGG-21)"
    )


def test_tc_agg_c21_caps_fired_is_keyed_per_cap_not_a_total(tmp_data_dir):
    """`caps_fired` is a mapping per criterion, keyed by cap name from `AGG_CAP_TABLE`.

    The dimensionality is the finding. One total tells a moderation meeting that something was
    capped; `{"ocr_overlap_risk": 12}` tells them the scans are bad and which afternoon to
    re-run. Collapsing the keys keeps the name and loses the only actionable part.
    """
    store, run_id = _scored_world(tmp_data_dir)
    try:
        signals = aggregation_signals(store.cohort(ORCH_COHORT_ID), run_id)
    finally:
        store.close()

    caps = signals.caps_fired
    assert hasattr(caps, "keys"), (
        f"caps_fired is a {type(caps).__name__}, not a mapping keyed by criterion"
    )
    for criterion_id, per_cap in caps.items():
        assert hasattr(per_cap, "keys"), (
            f"caps_fired[{criterion_id!r}] is a {type(per_cap).__name__}, not a per-cap "
            "mapping — a single count is the collapse CT-AGG-21 forbids"
        )
        unknown = sorted(set(per_cap) - set(AGG_CAP_TABLE))
        assert unknown == [], (
            f"caps_fired[{criterion_id!r}] names caps outside AGG_CAP_TABLE: {unknown}. The "
            f"registry is {sorted(AGG_CAP_TABLE)}"
        )


def test_tc_agg_c21_every_declared_signal_is_keyed_by_criterion(tmp_data_dir):
    """Each of the six is per-criterion, never a run-level scalar.

    Same reasoning as the caps: "the run escalated a lot" sends nobody anywhere, and "C3
    escalated a lot" names the criterion whose rubric needs looking at.
    """
    store, run_id = _scored_world(tmp_data_dir)
    try:
        signals = aggregation_signals(store.cohort(ORCH_COHORT_ID), run_id)
    finally:
        store.close()

    for name in sorted(DECLARED_SIGNAL_FIELDS):
        value = getattr(signals, name)
        assert hasattr(value, "keys"), (
            f"{name} is a {type(value).__name__}, not a mapping keyed by criterion "
            "(CT-AGG-21)"
        )
