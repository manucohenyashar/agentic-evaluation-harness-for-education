"""`TC-AGG-C09` — the holistic distinction comes from the package, not a branch (§6.11.12).

`CT-AGG-09`: "A `holistic` criterion carries a lower auto-acceptance ceiling than an
`atomic` one and ranks higher in the review queue at equal expected value. The
distinction comes from the package (`CT-SETUP-05`), so no consumer special-cases it at
run time."

Disposition, disclosed:

- **the lower ceiling** — the shipped sibling
  `tests/unit/agg/test_routing_and_escalation.py`'s
  `test_tc_agg_07_the_holistic_ceiling_is_strictly_lower_at_identical_verdicts`
  (`TC-AGG-07`, #93) executes it at identical verdicts; not repeated here;
- **the ranking differential** — the review queue is `M-REVIEW`'s (#108), so the limb
  is `writtenahead` below, registered under
  `"#96 c09 holistic ranks higher at rung 3 (M-REVIEW)"`;
- **the artifact assertion on consumer branches** — this file's executable core. A
  run-time branch on the scoring model is a second source of truth that drifts from
  the package (RISK-27), so the scan asserts the reading is structurally impossible:
  `scoring_model` is referenced by NO module outside the sanctioned four — `aeh.agg`
  (the policy the distinction is), `aeh.pkg`/`aeh.setup` (the package side that
  classifies and stores it, `CT-SETUP-05`'s home), and `aeh.orch`, whose single
  reference is the declared `FR-SETUP-08` base-depth map. A consumer that cannot read
  the attribute cannot branch on it.

Isolation: rung 0 for the scan; rung 3 (real driven run) for the ranking limb; the
socket guard is autouse.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import aeh
from aeh.store import open_store
from tests.contract.agg._drive import (
    criterion_bands,
    drive_scored_run,
    stored_verdicts,
)
from tests.support.agg_vocabulary import (
    criterion,
    signals,
    agg_config,
)
from tests.support.impl import AGG_MODULE, REVIEW_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = [pytest.mark.contract]

#: The sanctioned readers of the scoring model: the policy itself, and the package
#: side the distinction comes from (`CT-SETUP-05`).
_PACKAGE_SIDE = ("agg", "pkg", "setup")
#: `M-ORCH`'s single sanctioned reading: `FR-SETUP-08`'s declared base-depth map
#: (`SCORING_MODEL_BASE_DEPTH` — the sanctioned scoring_model branch outside
#: agg/pkg/setup, declared by the design, not a special case).
_ORCH_MAP_NAME = "SCORING_MODEL_BASE_DEPTH"

_COHORT = ORCH_COHORT_ID
_SUBMISSION = "SYN-C09"

_INSERT = (
    "INSERT INTO criterion_score (submission_id, criterion_id, band, points, "
    "judge_count, agreement, state, routing) "
    "VALUES (:sid, :cid, :band, :points, :jc, :ag, :state, :routing)"
)


def _scoring_model_sites(text: str) -> list[str]:
    """The lines of one module's text that reference the scoring model — the
    detector the scan runs over every shipped module."""
    return [line for line in text.splitlines() if "scoring_model" in line]


def test_tc_agg_c09_no_consumer_special_cases_the_scoring_model_at_run_time():
    """`TC-AGG-C09` (`CT-AGG-09`, `NFR-AGG-02`'s single-source reading, artifact
    assertion, P0) — outside the sanctioned four, no shipped module references
    `scoring_model` at all, and `M-ORCH`'s single reference is the declared
    base-depth map. The scanner is validated against a positive control first: a
    synthetic module text that branches on the model must be flagged, or the
    all-clear below proves nothing."""
    src = Path(aeh.__file__).parent

    # Positive control: the detector catches the defect it exists to catch.
    assert _scoring_model_sites(
        "if criterion.scoring_model == 'holistic':\n    rank *= 2\n"
    ), "fixture bug: the scanner no longer detects a scoring-model branch"

    offenders: dict[str, list[str]] = {}
    orch_sites: list[str] = []
    for path in sorted(src.glob("*.py")):
        name = path.stem
        if name in _PACKAGE_SIDE:
            continue
        sites = _scoring_model_sites(path.read_text(encoding="utf-8"))
        if name == "orch":
            orch_sites = sites
            continue
        if sites:
            offenders[name] = sites

    assert offenders == {}, (
        f"modules {sorted(offenders)} reference the scoring model — a consumer "
        "that can read it can branch on it, and a run-time branch is a second "
        "source of truth that drifts from the package (CT-AGG-09, RISK-27); the "
        "distinction comes from the package (CT-SETUP-05), applied by the policy "
        "in `aeh.agg` and the declared base-depth map in `aeh.orch`"
    )
    assert len(orch_sites) == 1 and _ORCH_MAP_NAME in orch_sites[0], (
        f"orch reads the scoring model {orch_sites} — its one sanctioned reading "
        f"is the declared FR-SETUP-08 base-depth map (`{_ORCH_MAP_NAME}`); any "
        "other reading is a special case drifting from the package"
    )


@pytest.mark.writtenahead
def test_tc_agg_c09_a_holistic_criterion_ranks_higher_in_the_review_queue(
    tmp_data_dir, make_fixture_provider
):
    """`TC-AGG-C09` (`CT-AGG-09`, contract / rung 3, ranking differential,
    writtenahead on `aeh.review:build_review`, #108) — two criteria at EQUAL
    expected value, one atomic one holistic: the holistic one ranks higher in the
    review queue. The second of the case's two assertions — a ceiling without the
    ranking effect leaves holistic criteria under-reviewed."""
    build_review = require(REVIEW_MODULE, "build_review", issue="#108")
    aggregate = require(AGG_MODULE, "aggregate", issue="#93")

    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        # Two criteria, identical shape except the scoring model the package
        # declares — the distinction under test arrives from the package alone.
        _, run_id, _ = drive_scored_run(
            store, provider,
            submissions=(_SUBMISSION,),
            criterion_specs=[
                {"criterion_id": "C-ATOM", "kind": "open", "scoring_model": "atomic",
                 "band_count": 2},
                {"criterion_id": "C-HOL", "kind": "open", "scoring_model": "holistic",
                 "band_count": 2},
            ],
        )
        bands = criterion_bands(store, "C-ATOM")
        atom = aggregate(stored_verdicts(store, run_id, _SUBMISSION, "C-ATOM"),
                         criterion(bands, criterion_id="C-ATOM"),
                         signals(), config=agg_config())
        hol = aggregate(stored_verdicts(store, run_id, _SUBMISSION, "C-HOL"),
                        criterion(bands, scoring_model="holistic", criterion_id="C-HOL"),
                        signals(), config=agg_config())
        assert hol.routing == "queued", (
            "fixture bug: the holistic criterion did not route to the teacher's "
            "queue, so the ranking differential has nothing to rank"
        )
        # Equal expected value, by construction: the atomic twin carries the SAME
        # figures as the holistic row — the pair differs only in which criterion
        # (and therefore which package-declared model) it belongs to.
        atomic_twin = replace(atom, criterion_id="C-ATOM",
                              routing="queued", confidence=hol.confidence)

        cohort = store.cohort(_COHORT)
        with cohort.transaction() as tx:
            for cid, score in (("C-ATOM", atomic_twin), ("C-HOL", hol)):
                tx.execute(
                    _INSERT, sid=_SUBMISSION, cid=cid, band=score.band,
                    points=score.points, jc=score.judge_count, ag=score.agreement,
                    state=score.state, routing=score.routing,
                )

        queue = build_review(store).queue()
        order = [
            (item.get("criterion_id") if isinstance(item, dict)
             else getattr(item, "criterion_id", None))
            for item in queue
        ]
        assert "C-ATOM" in order and "C-HOL" in order, (
            f"the review queue {order!r} does not hold the pair — the ranking "
            "differential cannot be read (CT-AGG-09)"
        )
        assert order.index("C-HOL") < order.index("C-ATOM"), (
            f"the review queue ranks {order!r} — at equal expected value the "
            "HOLISTIC criterion ranks higher (CT-AGG-09: a ceiling without the "
            "ranking effect leaves holistic criteria under-reviewed)"
        )
    finally:
        store.close()
