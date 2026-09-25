"""`TS-92` (issue #386) — `TC-SETUP-23`: `M-SETUP` declares each criterion's evaluation mode
rather than leaving it to the column default (`FR-SETUP-17`, `FR-PKG-22`).

| Input | Expected |
|---|---|
| a package built with one `FR-SETUP-13` deterministic criterion and one open criterion | the rows are written with an **explicit** `evaluation_mode` (a spy on the write shows the column bound, not defaulted) |
| — | `SCORING_MODELS == ("atomic", "atomic_with_gate", "holistic")` |

**"Bound, not defaulted" is the whole case, and the two are indistinguishable in the store.**
`criterion.evaluation_mode` is `NOT NULL DEFAULT 'judged'`, so a service that never mentions
the column produces rows that read `judged` — which is correct for the open criterion and
wrong for the MCQ one, and the store cannot tell you which happened. The only place the
difference is observable is the write itself, so the oracle is a spy on the record handed to
`PackageCatalog.write_readback`, not a query afterwards.

**Why it matters that the service decides.** `FR-SETUP-13`'s criteria are the deterministic
ones, and M-SETUP is the module that knows which those are — it ran the classification. Leaving
the mode to a column default pushes that knowledge into M-PKG's DDL, where it becomes the
retired `kind = 'mcq'` equivalence again under a different name (RISK-57): the one reading
`FR-PKG-22` exists to remove.

**`SCORING_MODELS` is asserted as an exact tuple, order included.** It is a closed vocabulary
that `FR-AGG-06` and the setup classifier both read; a fourth member added without a decision
is how a scoring model nobody costed enters the system, and the order is what
`_classify_answers`' table is written against.

**Isolation: rung 2** — the real Stage A chain over real tiers (`stage_chain`), with the
scripted provider as the only double.
"""

from __future__ import annotations

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
from aeh.pkg import EVALUATION_MODES, default_evaluation_mode
from aeh.setup import SCORING_MODELS

pytestmark = pytest.mark.integration

#: `FR-SETUP-13`'s deterministic shape, and its judged counterpart.
DETERMINISTIC_KIND = "mcq"
JUDGED_KIND = "open"


# --- TC-SETUP-23, the vocabulary ---------------------------------------------------------------


def test_tc_setup_23_the_scoring_model_vocabulary_is_exactly_the_declared_three():
    """`SCORING_MODELS == ("atomic", "atomic_with_gate", "holistic")`, order included.

    A closed vocabulary, asserted as a tuple rather than a set: `_classify_answers`' decision
    table is written against this order, and `FR-AGG-06` reads the same names. A fourth member
    is how a scoring model nobody costed enters the system.
    """
    assert SCORING_MODELS == ("atomic", "atomic_with_gate", "holistic"), (
        f"SCORING_MODELS is {SCORING_MODELS}"
    )


def test_tc_setup_23_the_evaluation_mode_vocabulary_is_closed_at_two():
    """`EVALUATION_MODES` is `("judged", "deterministic")` — the column's CHECK domain.

    Pinned beside `SCORING_MODELS` because the two are easy to conflate: a scoring model says
    HOW a judged criterion is scored, and the evaluation mode says WHETHER it is judged at all.
    A third mode would need a routing decision in M-ORCH that does not exist.
    """
    assert EVALUATION_MODES == ("judged", "deterministic"), (
        f"EVALUATION_MODES is {EVALUATION_MODES}"
    )


def test_tc_setup_23_the_shape_default_maps_mcq_to_deterministic():
    """`default_evaluation_mode` is the shape reading the service starts from.

    Not the reading any *consumer* may make — that is TC-ORCH-48's census — but the one
    M-SETUP applies when it decides, which is why the service's write must carry the result
    rather than the shape.
    """
    assert default_evaluation_mode(DETERMINISTIC_KIND) == "deterministic"
    assert default_evaluation_mode(JUDGED_KIND) == "judged"
    assert default_evaluation_mode(None) == "judged", (
        "an unknown shape must default to judged: sending an unclassified criterion to a "
        "deterministic walk grades it against an answer key it may not have"
    )


# --- TC-SETUP-23, the write ---------------------------------------------------------------------


def test_tc_setup_23_every_written_criterion_carries_an_explicit_evaluation_mode(
    tmp_data_dir, monkeypatch
):
    """The spy: each record handed to `write_readback` binds `evaluation_mode` itself, and
    the MCQ criterion binds `deterministic` while the open one binds `judged`.

    Asserted on the record rather than on the stored row, because the column's
    `DEFAULT 'judged'` makes "declared judged" and "never mentioned" identical in the store —
    and only one of them is `FR-SETUP-17`. The MCQ criterion is what tells them apart: an
    unbound write leaves it `judged`, which is the RISK-57 reading.
    """
    from aeh.pkg import PackageCatalog
    from tests.support.setup_harness import ingest_document, stage_chain

    written: list[dict[str, Any]] = []
    original = PackageCatalog.write_readback

    def _spy(self, *args: Any, **kwargs: Any):
        written.extend(dict(record) for record in kwargs.get("criteria", ()) or ())
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PackageCatalog, "write_readback", _spy)

    chain = stage_chain(tmp_data_dir, package_id="pkg-setup23")
    try:
        assessment = ingest_document(chain.store, kind="assessment")
        rubric = ingest_document(chain.store, kind="rubric", name="rubric.pdf")
        proposal = chain.service.propose_inventory(assessment)
        chain.service.confirm_inventory(proposal.proposal_id)

        # One FR-SETUP-13 criterion (mcq) and one judged one. The reply carries the §5.3
        # ANSWERS, never a classification: the module owns the table, so a service that
        # echoed a scripted verdict could not produce the pair below.
        mcq = {
            "criterion_id": "CRIT-MCQ", "question_id": "Q1", "kind": "mcq",
            "construct": "the response selects the correct option",
        }
        open_criterion = {
            "criterion_id": "CRIT-OPEN", "question_id": "Q2", "kind": "open",
            "construct": "the response states the definition",
            "answers": {"completeness": "yes", "non_interference": "yes",
                        "independence": "yes", "additivity": "yes", "gates": "yes"},
        }
        chain.provider.replies = [_readback_reply([mcq, open_criterion])]
        chain.service.read_back_rubric(rubric, assessment)
    finally:
        chain.store.close()

    assert written, (
        "no criterion record reached write_readback, so the spy observed nothing"
    )
    by_id = {record.get("criterion_id"): record for record in written}
    assert {"CRIT-MCQ", "CRIT-OPEN"} <= set(by_id), (
        f"the read back wrote {sorted(by_id)}, not both criteria"
    )

    missing = [name for name, record in by_id.items() if "evaluation_mode" not in record]
    assert missing == [], (
        f"criteria {missing} were written without binding evaluation_mode. The column is "
        "NOT NULL DEFAULT 'judged', so an unbound write produces a judged row that is "
        "indistinguishable from a declared one — and for an MCQ criterion it is wrong "
        "(FR-SETUP-17, RISK-57)"
    )
    assert by_id["CRIT-MCQ"]["evaluation_mode"] == "deterministic", (
        f"the MCQ criterion was written as "
        f"{by_id['CRIT-MCQ']['evaluation_mode']!r}. FR-SETUP-13's criteria are the "
        "deterministic ones and M-SETUP is the module that knows which those are"
    )
    assert by_id["CRIT-OPEN"]["evaluation_mode"] == "judged", (
        f"the open criterion was written as {by_id['CRIT-OPEN']['evaluation_mode']!r}"
    )


def test_tc_setup_23_the_stored_rows_agree_with_what_was_written(
    tmp_data_dir, monkeypatch
):
    """The other half: the modes the service bound are the modes the package ends up with.

    The spy proves the service decided; this proves the decision survived the write. Both are
    needed — a record that bound `deterministic` into a statement that never listed the column
    would satisfy the spy and store `judged`.
    """
    from tests.support.setup_harness import ingest_document, stage_chain

    chain = stage_chain(tmp_data_dir, package_id="pkg-setup23b")
    try:
        assessment = ingest_document(chain.store, kind="assessment")
        rubric = ingest_document(chain.store, kind="rubric", name="rubric.pdf")
        proposal = chain.service.propose_inventory(assessment)
        chain.service.confirm_inventory(proposal.proposal_id)
        version = proposal.package_version_id

        chain.provider.replies = [_readback_reply([
            {"criterion_id": "CRIT-MCQ", "question_id": "Q1", "kind": "mcq",
             "construct": "the response selects the correct option"},
            {"criterion_id": "CRIT-OPEN", "question_id": "Q2", "kind": "open",
             "construct": "the response states the definition",
             "answers": {"completeness": "yes", "non_interference": "yes",
                         "independence": "yes", "additivity": "yes", "gates": "yes"}},
        ])]
        chain.service.read_back_rubric(rubric, assessment)

        stored = {
            row["criterion_id"]: row["evaluation_mode"]
            for row in chain.catalog.criteria(version)
        }
    finally:
        chain.store.close()

    assert stored.get("CRIT-MCQ") == "deterministic", (
        f"the stored MCQ criterion reads {stored.get('CRIT-MCQ')!r}; the mode the service "
        "bound did not reach the row"
    )
    assert stored.get("CRIT-OPEN") == "judged", (
        f"the stored open criterion reads {stored.get('CRIT-OPEN')!r}"
    )


def _readback_reply(criteria: list[dict]) -> str:
    """One scripted read-back reply in the payload shape the setup oracles imply."""
    import json

    return json.dumps({"criteria": criteria})
