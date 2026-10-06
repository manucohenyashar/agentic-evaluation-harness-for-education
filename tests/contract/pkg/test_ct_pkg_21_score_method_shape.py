"""`TS-144` (issue #621) — `TC-PKG-C21`: `CT-PKG-21`'s clause suite (operator-requirements test
plan §5.5 and §6.11).

> **CT-PKG-21** (data). Every criterion carries `score_method` in the closed three-value set;
> `evidence_sum` criteria have ≥ 1 aspect criterion, each 2-band, each with `component_of`
> naming the composite; composites never carry bands or keys. `bands` and `general` criteria
> have `component_of = NULL`. Consumers: M-SETUP, M-JUDGE, M-GRADE, M-ORCH.

Two halves, as the plan states them:

1. **The TC-PKG-34/35 matrix as the provider's clause suite** — the same one-defect mutations of
   `F-RUBRIC-METHODS`, run here so the clause has its own suite a consumer's blast-radius run
   selects (`TC-PKG-34..36` live with the integration cases).
2. **A property: 50 seeded random valid packages all satisfy the shape.** Built through the real
   catalog into a real store and checked over the stored rows, not over the generator's intent.
   The closed set is a literal in `tests/support/rubric_methods.py`, never imported from
   `aeh.pkg` — so **a widened domain fails even if no fixture names the new value**: each seed
   also attempts a random non-member method and requires the refusal.

**Breaks if** the domain widens silently or a composite ships without aspects.

**Written ahead of #622** (`writtenahead`, keyed to #622). Today every arm fails on a `TypeError`
for the catalog's missing `score_method` argument. The generator's coverage test is not written
ahead and runs green now: a degenerate corpus (say, all-`bands`) would make the property hold
vacuously the day the marker comes off.
"""

from __future__ import annotations

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
from aeh.store import open_store
from tests.support import rubric_methods as rm

pytestmark = pytest.mark.contract

#: The plan's sample size for the property ("50 seeded random valid packages").
SEEDS = range(50)


@pytest.fixture
def store(tmp_data_dir):
    opened = open_store(tmp_data_dir)
    try:
        yield opened
    finally:
        opened.close()


# --- half 1: the clause matrix -----------------------------------------------------------------


def test_tc_pkg_c21_the_valid_fixture_satisfies_the_clause(store):
    """The matrix's positive control: F-RUBRIC-METHODS publishes and its rows satisfy CT-PKG-21."""
    shape = rm.rubric_methods("C21-VALID")
    _catalog, version = rm.build(store, shape)
    path = store.package_path(shape.package_id)
    assert rm.locked_versions(path) == [version]
    assert rm.shape_violations(path, version) == []


@pytest.mark.parametrize("mutation", rm.MUTATIONS, ids=lambda m: m.case)
def test_tc_pkg_c21_every_clause_violation_is_refused_at_publish(store, mutation):
    refusal = rm.attempt_build(store, mutation.apply(rm.rubric_methods("C21-BAD")))
    missing = rm.missing_names(mutation, str(refusal.error))
    assert not missing, (
        f"{mutation.case} ({mutation.what}): the refusal does not name {missing}: "
        f"{str(refusal.error)!r}")
    assert refusal.locked_versions == [], (
        f"{mutation.case}: a refused publish locked {refusal.locked_versions}")


# --- half 2: the property ----------------------------------------------------------------------


def test_tc_pkg_c21_the_generator_covers_every_method_in_every_package():
    """Not written ahead — the generator is the untested half of a written-ahead property.

    Every seed yields at least one `bands`, exactly one `general` and at least one composite with
    at least one aspect; across the 50 seeds composites of 1 and of 4 aspects both occur, and
    every band count 2, 4 and 6 is drawn. Deterministic in the seed.
    """
    aspect_counts: set[int] = set()
    band_counts: set[int] = set()
    for seed in SEEDS:
        shape = rm.random_shape(seed)
        assert rm.random_shape(seed) == shape, f"seed {seed}: the generator is not deterministic"
        got = rm.coverage(shape)
        assert got["bands"] >= 1 and got["general"] == 1 and got["evidence_sum"] >= 1, (
            f"seed {seed}: {got}")
        for c in shape.criteria:
            if c.score_method == "evidence_sum":
                aspects = [a for a in shape.criteria if a.component_of == c.criterion_id]
                assert aspects, f"seed {seed}: composite {c.criterion_id} has no aspect"
                assert all(len(a.bands) == 2 for a in aspects), f"seed {seed}"
                assert not c.bands, f"seed {seed}: generated composite with bands"
                aspect_counts.add(len(aspects))
            elif c.component_of is None:
                band_counts.add(len(c.bands))
        assert rm.random_non_member(seed) not in rm.SCORE_METHODS
    assert {1, 4} <= aspect_counts, aspect_counts
    assert {2, 4, 6} <= band_counts, band_counts


def test_tc_pkg_c21_fifty_seeded_valid_packages_all_satisfy_the_shape(store):
    """Property: every seeded valid package publishes and its stored rows satisfy CT-PKG-21 —
    closed domain, every composite with ≥ 1 two-band aspect whose `component_of` names it, no
    composite carrying bands or a key, standalone criteria with `component_of` NULL."""
    for seed in SEEDS:
        shape = rm.random_shape(seed)
        _catalog, version = rm.build(store, shape)
        path = store.package_path(shape.package_id)
        assert rm.locked_versions(path) == [version], f"seed {seed}: did not publish"
        problems = rm.shape_violations(path, version)
        assert problems == [], f"seed {seed}: CT-PKG-21 does not hold: {problems}"
        stored = rm.criteria_rows(path, version)
        assert set(stored) == {c.criterion_id for c in shape.criteria}, (
            f"seed {seed}: stored criteria {sorted(stored)} differ from the generated ones")
        for c in shape.criteria:
            got = stored[c.criterion_id]["score_method"]
            # `general` may store as `general` or as `bands` (FR-PKG-26: "the stored form is a
            # `bands` criterion"); every other declared method stores as itself, and an aspect
            # (declared without a method) stores the column default.
            allowed = ({"general", "bands"} if c.score_method == "general"
                       else {c.score_method or "bands"})
            assert got in allowed, (
                f"seed {seed}: {c.criterion_id} declared {c.score_method!r} but stored {got!r}")


def test_tc_pkg_c21_a_random_non_member_method_is_refused_for_every_seed(store):
    """The other face of the closed domain: per seed, one standalone `bands` line re-declared with
    a random value outside the set — refused, naming the closed set, nothing locked."""
    for seed in SEEDS:
        shape = rm.random_shape(seed)
        value = rm.random_non_member(seed)
        target = next(c.criterion_id for c in shape.criteria if c.score_method == "bands")
        shape = rm.with_criterion(shape, target, score_method=value)
        shape.package_id = f"RM-NONMEMBER-{seed:02d}"
        refusal = rm.attempt_build(store, shape)
        message = str(refusal.error)
        missing = rm.names_every_method(message)
        assert not missing, (
            f"seed {seed}: score_method {value!r} refused without naming {missing}: {message!r}")
        assert refusal.locked_versions == [], f"seed {seed}: {refusal.locked_versions}"
