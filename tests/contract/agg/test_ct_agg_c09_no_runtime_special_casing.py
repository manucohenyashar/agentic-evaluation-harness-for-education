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
  the package (RISK-27), so the scan asserts exactly that: outside the sanctioned
  readers, no module references `scoring_model` at all — `aeh.agg` (the policy the
  distinction is), `aeh.pkg`/`aeh.setup` (the package side that classifies and stores
  it, `CT-SETUP-05`'s home), `aeh.orch`, whose single reference is the declared
  `FR-SETUP-08` base-depth map, `aeh.review`, whose references are a closed
  declared set — the `FR-AGG-06` tie-break at both of the ranking's shapes plus the
  wire field that carries the row's package-declared value (`CT-AGG-09`'s own ranking
  mandate; reconciled at #108's landing, when the queue first read the model — the
  ban is on deriving a second distinction, not on the declared read) — and
  `aeh.stats`, whose references are likewise a closed declared set: the wire field
  that keys every agreement figure with the model it is a claim about
  (`FR-STATS-02`/`NFR-STATS-02`), the criterion-declared default and the pass-through
  that stores the package's declaration (`CT-SETUP-05` again — reconciled at #115's
  landing, when the figure first carried the model).

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
#: side the distinction comes from (`CT-SETUP-05`). `aeh.review` and `aeh.orch` are
#: sanctioned separately, each as a closed set of declared sites (below).
_PACKAGE_SIDE = ("agg", "pkg", "setup")
#: `M-ORCH`'s single sanctioned reading: `FR-SETUP-08`'s declared base-depth map
#: (`SCORING_MODEL_BASE_DEPTH` — the sanctioned scoring_model branch outside
#: agg/pkg/setup, declared by the design, not a special case).
_ORCH_MAP_NAME = "SCORING_MODEL_BASE_DEPTH"
#: The review queue's sanctioned scoring-model reads, each its clause: the
#: tie-break `FR-AGG-06` mandates (holistic first at equal expected value) at
#: both of the ranking's declared shapes, the wire field that carries the row's
#: package-declared value, the pass-through that reads it, the honest default
#: for the stored rows the store cannot enrich, and the docstring that names
#: the contract. Reconciled at #108's landing — the queue first read the model
#: there, and the ranking differential is `CT-AGG-09`'s own mandate. Anything
#: else — a per-model threshold, a second mapping, a multiplier — is the run-time
#: special case the clause bans, and lands here as an unsanctioned site.
_REVIEW_SANCTIONED = (
    '0 if getattr(row, "scoring_model", None) == "holistic" else 1',
    '0 if getattr(ranked, "scoring_model", None) == "holistic" else 1',
    'scoring_model: str | None',
    'scoring_model=getattr(row, "scoring_model", None),',
    'self.scoring_model = "atomic"',
    '``expected_value`` and ``scoring_model``',
)
#: The agreement figure's sanctioned scoring-model reads, each its clause: the
#: wire field that carries the row's package-declared value (`FR-STATS-02`
#: keys every statistic with the scoring model it is a claim about), the
#: criterion-declared default that reads what the package classified
#: (`CT-SETUP-05`), the echo into the figure's own fields, the declaration
#: pass-through that stores the package's mapping, its two signatures, and
#: the same pass-through re-applied when a sub-surface is built over a
#: narrowed population (`#116`'s step 4 — the per-assignment-type figures are
#: built on a sub-``ValidationStats`` carrying the same stored declaration).
#: Reconciled at #115's landing — the figure first carried the model there,
#: and `NFR-STATS-02` makes the carry mandatory; re-pinned at #116's for the
#: sub-surface pass-through. Anything else — a per-model
#: branch, a second mapping, a multiplier — is the run-time special case the
#: clause bans, and lands here as an unsanctioned site.
_STATS_SANCTIONED = (
    "scoring_model: str",
    "if scoring_model is None:",
    'scoring_model = self._scoring_models.get(criterion_id or "")',
    "scoring_model=scoring_model,",
    "scoring_models: Mapping[str, str] | None = None,",
    "self._scoring_models = dict(scoring_models or {})",
    "scoring_models=scoring_models,",
    "scoring_models=stats._scoring_models,",
)
#: M-CALIB's sanctioned scoring-model references, each its clause: the §6.2 vocabulary
#: entry naming the locked field (the HLD's own name for it, the same name
#: `SCHEMA_LOCK_FIELDS` carries in `aeh.pkg`), and the forced-edit door's routing to the
#: catalog call whose guard covers that field. Reconciled at #138's landing — CT-CALIB-06
#: sweeps EVERY locked field from M-CALIB's side by routing the edit through the catalog
#: and watching the catalog's own guard refuse it, so the module must be able to name the
#: field and offer the edit. The ban is on deriving a second distinction, not on the
#: declared read (the same reading that sanctioned review's wire field): calib never
#: branches on the model's VALUE — no per-model threshold, multiplier, or second mapping —
#: it hands the locked-field edit to `M-PKG`'s guard. Anything else lands here as an
#: unsanctioned site.
_CALIB_SANCTIONED = (
    '"scoring_model",',
    'elif field == "scoring_model":',
    'catalog.update_criterion_field(base, criterion, "scoring_model", "atomic")',
)

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
    assertion, P0) — outside the sanctioned readers, no shipped module references
    `scoring_model` at all; `M-ORCH`'s single reference is the declared
    base-depth map, and `aeh.review`'s references are the closed declared set —
    the `FR-AGG-06` tie-break at both of the ranking's shapes, the wire field,
    the pass-through, and the store default. The scanner is validated against a
    positive control first: a synthetic module text that branches on the model
    must be flagged, or the all-clear below proves nothing."""
    src = Path(aeh.__file__).parent

    # Positive control: the detector catches the defect it exists to catch.
    assert _scoring_model_sites(
        "if criterion.scoring_model == 'holistic':\n    rank *= 2\n"
    ), "fixture bug: the scanner no longer detects a scoring-model branch"

    offenders: dict[str, list[str]] = {}
    orch_sites: list[str] = []
    review_sites: list[str] = []
    stats_sites: list[str] = []
    calib_sites: list[str] = []
    for path in sorted(src.glob("*.py")):
        name = path.stem
        if name in _PACKAGE_SIDE:
            continue
        sites = _scoring_model_sites(path.read_text(encoding="utf-8"))
        if name == "orch":
            orch_sites = sites
            continue
        if name == "review":
            review_sites = sites
            continue
        if name == "stats":
            stats_sites = sites
            continue
        if name == "calib":
            calib_sites = sites
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
    # The queue's sites are the closed declared set (see `_REVIEW_SANCTIONED`):
    # a new reference — a per-model threshold, a second mapping, a multiplier —
    # lands here and fails.
    unsanctioned = [
        site for site in review_sites
        if not any(shape in site for shape in _REVIEW_SANCTIONED)
    ]
    assert unsanctioned == [], (
        f"aeh.review reads the scoring model outside its declared sites "
        f"{unsanctioned!r} — the queue's sanctioned reading is the tie-break "
        "`FR-AGG-06` mandates (holistic first at equal expected value) and the "
        "wire field that carries the package-declared value; anything else is "
        "a run-time special case drifting from the package (CT-AGG-09, RISK-27)"
    )
    # The figure's sites are the closed declared set (see `_STATS_SANCTIONED`):
    # a new reference — a per-model branch, a second mapping, a multiplier —
    # lands here and fails.
    unsanctioned_stats = [
        site for site in stats_sites
        if not any(shape in site for shape in _STATS_SANCTIONED)
    ]
    assert unsanctioned_stats == [], (
        f"aeh.stats reads the scoring model outside its declared sites "
        f"{unsanctioned_stats!r} — the figure's sanctioned reading is the wire "
        "field that keys every statistic with the model it is a claim about "
        "(`FR-STATS-02`) and the pass-through that stores the package's "
        "declaration (`CT-SETUP-05`); anything else is a run-time special case "
        "drifting from the package (CT-AGG-09, RISK-27)"
    )
    # M-CALIB's sites are the closed declared set (see `_CALIB_SANCTIONED`): a
    # new reference — a per-model branch, a second mapping, a multiplier —
    # lands here and fails.
    unsanctioned_calib = [
        site for site in calib_sites
        if not any(shape in site for shape in _CALIB_SANCTIONED)
    ]
    assert unsanctioned_calib == [], (
        f"aeh.calib reads the scoring model outside its declared sites "
        f"{unsanctioned_calib!r} — its sanctioned references are the §6.2 "
        "vocabulary naming the locked field and the forced-edit door's routing "
        "of that edit through the catalog's guard (`CT-CALIB-06`); anything "
        "else is a run-time special case drifting from the package "
        "(CT-AGG-09, RISK-27)"
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
