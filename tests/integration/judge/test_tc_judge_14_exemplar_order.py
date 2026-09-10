"""`TC-JUDGE-14` — exemplar presentation order: fixed WITHIN a batch, randomized
ACROSS batches, reproducible under the same salt (`FR-JUDGE-08`; issue #83 (TS-31)).

`_ordered_exemplars` seeds a permutation of the criterion's exemplars keyed on
(question, criterion) and the `HARNESS_JUDGE_EXEMPLAR_SEED` salt, read at call time.
Three oracles, per the case table:

- **fixed within a batch**: every submission in the same batch — the same criterion
  judged over a cohort — renders the SAME exemplar bytes in the SAME order, which is
  what keeps the invariant prefix one value across the batch (`FR-JUDGE-06`). Asserted
  as full view equality (id, band, text), not just ids;
- **randomized across batches**: a different salt moves the order — while the SET is
  invariant (a permutation, never a subset or a repetition), because a batch that lost
  an exemplar would not be a re-ordering but a different rubric. The salts below were
  verified empirically to give pairwise-distinct permutations of the four seeded
  exemplars under this world's digest key;
- **reproducible under one salt**: the same salt twice assembles the same order — the
  salt is a knob, not a source of per-call randomness, so a fixture recording
  reproduces exactly.

This is the coverage gap the #79 reviewer's report named — the exemplar ORDER cases —
owned here rather than patched into a landed suite.

Isolation: rung 2 store door — a real store, a real package version with exemplar
blobs, a real extraction leg (the Sweep-2 gate), then `assemble` per leased unit. No
judge leg, no provider call, no model, no network.
"""

from __future__ import annotations

import pytest

from aeh.orch import STAGE_SCORE
from aeh.store import open_store
from tests.support.conf_builders import edge_panel
from tests.support.extract_vocabulary import JUDGE_ISSUE
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_run import judge_world, warm_judged_modules
from tests.support.judge_vocabulary import EXEMPLAR_SEED_KNOB

pytestmark = [pytest.mark.integration]

#: Four exemplars for the one criterion — the permutation needs len >= 2 to engage
#: (`_ordered_exemplars` passes shorter lists through untouched, so fewer exemplars
#: would make every arm vacuous).
EXEMPLARS = (
    ("C1", "secure"),
    ("C1", "emerging"),
    ("C1", "secure"),
    ("C1", "emerging"),
)
SEEDED_IDS = ("ex-00", "ex-01", "ex-02", "ex-03")

#: The batch the order is asserted over — every submission is one member of the same
#: (question, criterion) batch.
SUBMISSIONS = ("s-14a", "s-14b", "s-14c", "s-14d")

#: Salts verified empirically under this world's digest key (sha256 over
#: `salt||C1`, base order ex-00..ex-03) to give THREE pairwise-distinct permutations:
#: the unset default (`judge-prompt/2`) -> (01,02,03,00), "salt-a" -> (01,03,00,02),
#: "salt-b" -> (00,02,01,03). If a rename ever makes two coincide, the fixture-bug
#: assertion in 14_b names it.
SALT_A = "salt-a"
SALT_B = "salt-b"


def _world(tmp_data_dir, make_fixture_provider, *, name: str = "a"):
    """The store door: a judged package carrying four exemplars, a real extraction
    leg, and the score units leased — nothing dispatched. `name` separates worlds
    built within one test (a fresh store per call, so re-seeding cannot collide)."""
    warm_judged_modules()
    store = open_store(tmp_data_dir / f"data-{name}")
    provider = make_fixture_provider()
    world = judge_world(
        store,
        provider,
        submissions=SUBMISSIONS,
        panel=1,
        exemplars=EXEMPLARS,
        judge_leg=False,
    )
    units = list(world["orchestrator"].lease("w-judge-tj31", STAGE_SCORE, 64))
    assert len(units) == len(SUBMISSIONS), (
        f"precondition: one score unit per submission expected, got {len(units)}"
    )
    return store, provider, units


def _views(request):
    """The request's exemplar views as comparable tuples — id, band, and the blob's
    text bytes, so byte-level drift within a batch is caught too."""
    return tuple(
        (view.exemplar_id, view.band, view.text)
        for view in request.criterion.exemplars
    )


def _assemble_all(store, provider, units):
    """Assemble every leased unit (the store door) and return
    submission_id -> exemplar view tuple."""
    ScoringWorker = require(JUDGE_MODULE, "ScoringWorker", issue=JUDGE_ISSUE)
    ref = edge_panel(1)[0]
    return {
        unit.submission_id: _views(ScoringWorker(store, provider, ref).assemble(unit))
        for unit in units
    }


def _assert_permutation(views_by_submission):
    """The set is invariant under any salt: the four seeded ids, each exactly once —
    a re-ordering, never a loss or a duplication."""
    assert len(views_by_submission) == len(SUBMISSIONS)
    for submission_id, views in views_by_submission.items():
        ids = tuple(view[0] for view in views)
        assert len(views) == len(SEEDED_IDS), (
            f"submission {submission_id} assembled {len(views)} exemplars, expected "
            f"{len(SEEDED_IDS)}"
        )
        assert sorted(ids) == sorted(SEEDED_IDS), (
            f"submission {submission_id} assembled exemplars {ids} — not the seeded "
            f"set {SEEDED_IDS}: a permutation must not lose or duplicate an exemplar"
        )


# --- fixed within the batch -------------------------------------------------------------------------


def test_tc_judge_14_a_the_exemplar_order_is_fixed_within_a_batch(
    tmp_data_dir, make_fixture_provider, monkeypatch
):
    """With the salt unset (the production default), every submission in the batch
    renders the SAME exemplar views in the SAME order — the invariant prefix's
    exemplar half, one value across the batch (`FR-JUDGE-06`)."""
    monkeypatch.delenv(EXEMPLAR_SEED_KNOB, raising=False)
    store, provider, units = _world(tmp_data_dir, make_fixture_provider)
    views_by_submission = _assemble_all(store, provider, units)
    _assert_permutation(views_by_submission)
    reference = views_by_submission[SUBMISSIONS[0]]
    assert reference, "precondition: the criterion's rubric carries exemplars"
    for submission_id, views in views_by_submission.items():
        assert views == reference, (
            f"submission {submission_id} rendered a different exemplar sequence than "
            f"{SUBMISSIONS[0]} within the same batch — the invariant prefix would "
            f"differ between two requests of one batch (FR-JUDGE-06, FR-JUDGE-08)"
        )


# --- randomized across batches ----------------------------------------------------------------------


def test_tc_judge_14_b_the_order_moves_across_batches_while_the_set_holds(
    tmp_data_dir, make_fixture_provider, monkeypatch
):
    """A different salt moves the order: the default-salt batch, the "salt-a" batch
    and the "salt-b" batch assemble three pairwise-distinct orders over the SAME
    exemplar set — no position bias survives from one batch to the next (`FR-JUDGE-08`),
    and the randomization is a permutation, not a re-draw."""
    orders = {}
    for index, salt in enumerate((None, SALT_A, SALT_B)):
        if salt is None:
            monkeypatch.delenv(EXEMPLAR_SEED_KNOB, raising=False)
        else:
            monkeypatch.setenv(EXEMPLAR_SEED_KNOB, salt)
        store, provider, units = _world(
            tmp_data_dir, make_fixture_provider, name=f"b{index}"
        )
        views_by_submission = _assemble_all(store, provider, units)
        _assert_permutation(views_by_submission)
        orders[salt or "default"] = views_by_submission[SUBMISSIONS[0]]
    for first, second in (("default", SALT_A), ("default", SALT_B), (SALT_A, SALT_B)):
        assert orders[first] != orders[second], (
            f"salts {first!r} and {second!r} produced the SAME exemplar order — the "
            f"salts were verified empirically to differ; if this fails after a "
            f"template bump, re-verify the salt pair (FR-JUDGE-08)"
        )


# --- reproducible under one salt --------------------------------------------------------------------


def test_tc_judge_14_c_the_same_salt_assembles_the_same_order_again(
    tmp_data_dir, make_fixture_provider, monkeypatch
):
    """The salt is read at call time, but the permutation is a FUNCTION of the salt:
    assembling the same units twice under one salt gives byte-identical views — the
    reproducibility a fixture recording depends on (the unset default included)."""
    ScoringWorker = require(JUDGE_MODULE, "ScoringWorker", issue=JUDGE_ISSUE)
    ref = edge_panel(1)[0]
    for index, salt in enumerate((None, SALT_A)):
        if salt is None:
            monkeypatch.delenv(EXEMPLAR_SEED_KNOB, raising=False)
        else:
            monkeypatch.setenv(EXEMPLAR_SEED_KNOB, salt)
        store, provider, units = _world(
            tmp_data_dir, make_fixture_provider, name=f"c{index}"
        )
        first = _assemble_all(store, provider, units)
        again = {
            unit.submission_id: _views(
                ScoringWorker(store, provider, ref).assemble(unit)
            )
            for unit in units
        }
        assert first == again, (
            f"under salt {salt!r} the second assembly of the same units rendered a "
            f"different exemplar order — the salt would not reproduce a recording"
        )