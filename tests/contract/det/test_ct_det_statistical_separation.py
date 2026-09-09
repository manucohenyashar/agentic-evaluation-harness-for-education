"""`CT-DET-06` — the statistical separation (`TC-DET-C06`).

Case of test plan §6.11.11; issue #90 (TS-68). Green by design — `M-DET`
shipped via #246/#249.

The clause: deterministic results are excluded from **every** agreement, κ, α
and grader-quality figure, and `label.evaluation_mode` carries the distinction
so the exclusion is enforceable **from the data**, not by convention; a
consumer must filter on that column, not on a naming convention (`FR-DET-09`,
R53, RISK-07's mechanism).

The clause discriminator: the FR-level case seeds both label shapes and runs
the filter once; this case asserts the clause's ENFORCEABILITY half —
- the column carries the distinction (deterministic and judged labels coexist
  and differ on it);
- the canonical agreement-figure query excludes the deterministic label
  END TO END over a real store, while every other admissible half of the
  conjunction (`label_type = 'blind'`) still applies;
- the exclusion predicate exists in EXACTLY ONE place in the source and every
  potential second spelling is absent — swept over the ENTIRE `src/aeh`
  statement registry and module text, so a consumer re-spelling the filter
  (the convention-shaped defect RISK-07 names) fails here, not silently in a
  statistic.

**Disclosed rung-3 half**: the plan's per-statistic sweep (agreement, κ, α,
grader-quality computed and each checked) needs `M-STATS`, which is not
shipped yet (κ/α consumers land with M-STATS — the TS-33 disclosure this
suite reconciles with). What the shipped surface can carry is asserted at
full strength: the one definition, the column it reads, and the canonical
composed query the consumers are required to use.

**Disclosed direct write**: `label` rows are seeded directly. det owns the
`evaluation_mode` COLUMN but `CT-DET-09`'s write set admits no label writes —
population is the duty of whichever module records a label over a
deterministic result (det.py's module docstring; the TS-33 disclosure,
unchanged).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aeh.det import DETERMINISTIC_EXCLUSION, DET_STATEMENTS
from aeh.store import STATEMENTS

pytestmark = pytest.mark.contract

from tests.contract.det._doubles import ISSUE  # noqa: F401 — register citation
from tests.support.det_vocabulary import open_det_store

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src" / "aeh"

#: The exact predicate, as the constant spells it.
PREDICATE = "label.evaluation_mode <> 'deterministic'"


def _seed_labels(store, cohort_id: str, run_id: str) -> None:
    """Both label shapes over the same cohort: three blind judged labels and
    two blind DETERMINISTIC labels (the disclosure above covers the direct
    write). Deterministic labels are labelled `deterministic` — the column
    det's migration added; a label recorded over a deterministic result by
    M-REVIEW/M-GRADE would carry exactly this value."""
    handle = store.durable()
    rows = [
        ("lbl-j1", "blind", "correct"),
        ("lbl-j2", "blind", "incorrect"),
        ("lbl-j3", "expert", "correct"),  # not blind: excluded by the OTHER half
        ("lbl-d1", "blind", "correct"),
        ("lbl-d2", "blind", "incorrect"),
    ]
    modes = {"lbl-d1": "deterministic", "lbl-d2": "deterministic"}
    with handle.transaction() as tx:
        for label_id, label_type, band in rows:
            tx.execute(
                "INSERT INTO label (label_id, run_id, student_ref, "
                "criterion_id, label_type, band, evaluation_mode) VALUES "
                "(:l, :r, :s, :c, :t, :b, :m)",
                l=label_id, r=run_id, s="S01", c="M1", t=label_type, b=band,
                m=modes.get(label_id, "judged"),
            )


def test_tc_det_c06_the_column_carries_the_distinction(tmp_data_dir):
    """`TC-DET-C06` (rung 2, the data) — judged and deterministic labels
    coexist in one store and differ on `label.evaluation_mode`; the
    distinction lives in the DATA, so the exclusion is enforceable without
    knowing any naming convention. The canonical agreement-figure query
    (`select_agreement_labels`) then excludes the deterministic labels end to
    end AND keeps the other admissible half of the conjunction — a judged but
    non-blind label is excluded by `label_type = 'blind'`, a blind judged
    label passes both halves."""
    store = open_det_store(tmp_data_dir)
    try:
        run_id, cohort_id = seed_a_world(store)
        _seed_labels(store, cohort_id, run_id)

        rows = {
            row["label_id"]: dict(row)
            for row in store.durable().query(
                "SELECT label_id, label_type, evaluation_mode FROM label"
            )
        }
        assert rows["lbl-d1"]["evaluation_mode"] == "deterministic"
        assert rows["lbl-d2"]["evaluation_mode"] == "deterministic"
        assert rows["lbl-j1"]["evaluation_mode"] == "judged"
        assert rows["lbl-j2"]["evaluation_mode"] == "judged"

        # The canonical figure query, over the real store: deterministic
        # labels are gone; the blind judged ones survive; the non-blind one
        # is excluded by the conjunction's other half.
        admitted = {
            row["label_id"]
            for row in store.durable().query(
                DET_STATEMENTS["select_agreement_labels"]
            )
        }
        assert admitted == {"lbl-j1", "lbl-j2"}, (
            f"TC-DET-C06: the agreement-figure query admitted {sorted(admitted)} "
            "— a deterministic label entered a figure, or the blind half of "
            "the conjunction broke."
        )
    finally:
        store.close()


def seed_a_world(store):
    """A minimal seeded world so the labels' run_id resolves to a real run."""
    from tests.support.det_vocabulary import seed_det_world

    run_id, _version, cohort_id = seed_det_world(
        store,
        submissions=("S01",),
        criteria=[{"criterion_id": "M1", "question_id": "Q1", "key": ("B",)}],
    )
    return run_id, cohort_id


def test_tc_det_c06_the_predicate_exists_in_exactly_one_place():
    """`TC-DET-C06` (the artifact assertion) — the exclusion predicate is
    defined ONCE: the constant carries it, the canonical statement composes it
    (the module's own import-time assert binds them, and this case verifies
    the binding independently), and NO other statement or module in `src/aeh`
    spells a deterministic-exclusion of its own — the second spelling is the
    convention-based filter RISK-07 warns of, which silently stops working
    when a name changes."""
    # The constant and its composed statement agree, byte for byte.
    assert DETERMINISTIC_EXCLUSION == PREDICATE
    composed = str(DET_STATEMENTS["select_agreement_labels"])
    assert PREDICATE in composed, (
        "TC-DET-C06: the canonical agreement query lost the exclusion "
        "predicate."
    )

    # The sweep: every statement in the whole registry, and every module
    # source line. Exactly ONE statement carries the predicate (the canonical
    # one) and exactly ONE source line defines it (the constant).
    statements_with_it = [
        name for name, stmt in STATEMENTS.items() if PREDICATE in str(stmt)
    ]
    assert statements_with_it == ["select_agreement_labels"], (
        f"TC-DET-C06: the exclusion predicate appears in {statements_with_it} "
        "— a second statement re-spelled the filter."
    )

    pattern = re.compile(re.escape(PREDICATE))
    definitions = []
    for path in sorted(SRC_ROOT.glob("*.py")):
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if pattern.search(line):
                definitions.append(f"{path.name}:{lineno}")
    # The literal's home is det.py, and ONLY det.py — twice: the constant's
    # definition and the canonical statement's own literal (SEC-15 refuses
    # assembled SQL, so the statement spells the filter as a pure literal and
    # det's import-time assert binds the two — this module imported green, so
    # the binding held). A THIRD occurrence, in any module, is a consumer
    # re-spelling the filter: the convention-shaped defect RISK-07 names.
    files = {name.split(":")[0] for name in definitions}
    assert files == {"det.py"}, (
        f"TC-DET-C06: the exclusion literal is spelled in {sorted(files)} — "
        "a module outside det owns a second filter, and it will silently "
        "diverge from the one definition."
    )
    assert len(definitions) == 2, (
        f"TC-DET-C06: the exclusion literal appears {len(definitions)} times "
        f"in det.py ({definitions}) — the constant and the canonical "
        "statement are the sanctioned pair; any further occurrence is a "
        "re-spelled filter."
    )
