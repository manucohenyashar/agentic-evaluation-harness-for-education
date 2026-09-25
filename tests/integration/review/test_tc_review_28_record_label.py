"""`TS-89` (issue #383) — `TC-REVIEW-28`: `FR-REVIEW-21`'s eight label columns, recorded at
the moment the label is written.

| Input | Expected |
|---|---|
| system band ordinal 1, teacher ordinal 3 | `band_distance = 2`, `agreed = 0` |
| package without a population scope | `assignment_type` NULL |
| package **with** scope `assignment_type='lab'` | `'lab'` — **not expressible**, see below |
| an agreeing label | `band_distance = 0`, `agreed = 1` |
| every arm | `package_version_id`, `system_points`, `teacher_points`, `panel_config` and `recorded_at` populated |

**Why the distance is recorded rather than derived later.** A string comparison cannot say how
far a teacher moved a band: `"proficient"` and `"developing"` are two names, and only the
package's ordinals know they are adjacent. `agreed` is recorded beside it for the opposite
reason — it needs no scale, so it survives on a store with no package behind it, and it is the
figure `FR-STATS-24` counts. Six consumers re-deriving either one is six chances to disagree
about what a NULL band means.

**Nothing defaults to a flattering value.** A `band_distance` the scale cannot supply is
`None`, never `0` — a zero would read as "the teacher agreed" about a judgement the writer
could not see the bands for, and that is an override silently uncounted.

**The `assignment_type='lab'` arm is NOT expressible, and finding that is a result.** The
column exists on `label` (Durable 10) and `_label_judgement_columns` reads it — but only as
`if "assignment_type" in entry.keys()` over a criterion row, and **no package schema declares
such a column**: `grep -rn "assignment_type" src/aeh/*.py` finds it in `review.py` and
`stats.py` only, never in `pkg.py`. So `facts["assignment_type"]` is `None` for every label
that can be written today, the reader is unreachable, and M-STATS's
`assignment_type_not_recorded` is the only answer its partition can ever give. The NULL arm is
asserted; the `'lab'` arm is reported by #383 as a gap between `FR-REVIEW-21`'s column and
`M-PKG`'s schema, not faked with a hand-written column.

**Isolation: rung 2** — a real store, a real package with a real band scale, and the service
route (`act`), which is the only route that populates these columns: the durable collection
route writes them all `None` deliberately, because it carries no run and therefore no package.
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
from aeh.pkg import PackageCatalog
from aeh.review import open_review
from aeh.store import Statement, open_store
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration

SUBMISSION = "S001"
CRITERION = "C1"

#: Four bands, ordinals 0..3, monotone points. The case's system band sits at ordinal 1 and
#: the teacher's at ordinal 3, so the distance is 2 — a figure no string comparison can reach.
BANDS = (
    (0, "emerging", 2.0),
    (1, "developing", 4.0),
    (2, "proficient", 6.0),
    (3, "exemplary", 8.0),
)
SYSTEM_BAND = "developing"   # ordinal 1
TEACHER_BAND = "exemplary"   # ordinal 3
EXPECTED_DISTANCE = 2

CRITERIA = (
    {
        "criterion_id": CRITERION,
        "kind": "open",
        "scoring_model": "atomic",
        "band_count": len(BANDS),
    },
)

_LABELS = Statement("SELECT * FROM label ORDER BY rowid")


@pytest.fixture
def label_world(tmp_data_dir):
    """A stored run whose package declares the band scale, with one queued score to act on.

    The store stays open for the test's life because the service is handed this package's
    `catalog=`: without it the service falls back to `REVIEW_DEFAULT_BANDS` (`B1`…`B5`) and
    cannot price a band this package declares — which is a real behaviour, but not this case's
    subject. `band_distance` comes from a catalog `_label_judgement_columns` builds for itself
    off the run row, so it would resolve either way; the points would not.
    """
    store = open_store(tmp_data_dir)
    try:
        _orchestrator, run_id, version = seed_run(
            store, submissions=(SUBMISSION,), criteria=CRITERIA,
        )
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        for ordinal, band, points in BANDS:
            catalog.add_band(version, CRITERION, ordinal, band, points)
        write_criterion_scores(
            store.cohort(ORCH_COHORT_ID),
            [(SUBMISSION, CRITERION, SYSTEM_BAND, 4.0, "provisional")],
        )
        yield tmp_data_dir, catalog, run_id
    finally:
        store.close()


def _labels(tmp_data_dir) -> list[dict[str, Any]]:
    store = open_store(tmp_data_dir)
    try:
        return [dict(row) for row in store.durable().query(_LABELS)]
    finally:
        store.close()


def _act(world, action: str, new_band: str | None) -> None:
    tmp_data_dir, catalog, run_id = world
    # The REAL run id, not the cohort id. `_label_judgement_columns` resolves the package
    # through `select_run_package(run_id=...)`, so a cohort id there finds no run row and
    # every package-derived column comes back NULL — with the label still written.
    # `open_review` loads by COHORT (the rows it admits live on the cohort ledger), while
    # `build_queue`'s run_id is what `_label_judgement_columns` resolves the package
    # through. They are different identifiers and the case needs both: a cohort id in the
    # second position finds no run row, and every package-derived column comes back NULL
    # with the label still written.
    service = open_review(tmp_data_dir, run_id=ORCH_COHORT_ID, catalog=catalog)
    queue = service.build_queue(run_id, 60, record=False)
    entry = queue.shown[0]
    members = getattr(entry, "members", None)
    item = members[0] if members else entry
    service.act(item, action, new_band=new_band)


# --- TC-REVIEW-28 ---------------------------------------------------------------------------


def test_tc_review_28_a_moved_band_records_its_distance_and_disagreement(label_world):
    """System ordinal 1, teacher ordinal 3 → `band_distance = 2`, `agreed = 0`.

    The distance is the figure the package's ordinals supply and a string comparison cannot.
    An implementation that recorded `1` for "any disagreement" would satisfy `agreed` and lose
    the magnitude M-STATS reads.
    """
    _act(label_world, "override", TEACHER_BAND)

    rows = _labels(label_world[0])
    assert len(rows) == 1, f"the action wrote {len(rows)} labels, not one"
    label = rows[0]

    assert label["band_distance"] == EXPECTED_DISTANCE, (
        f"band_distance is {label['band_distance']!r}, not {EXPECTED_DISTANCE}: the system "
        f"proposed {SYSTEM_BAND!r} (ordinal 1) and the teacher chose {TEACHER_BAND!r} "
        "(ordinal 3). Only the package's ordinals can answer how far that is"
    )
    assert label["agreed"] == 0, (
        f"agreed is {label['agreed']!r} for a label that changed the band"
    )


def test_tc_review_28_an_agreeing_label_records_distance_zero(label_world):
    """An `accept` of the proposed band → `band_distance = 0`, `agreed = 1`.

    The pair that makes the case above meaningful: `0` and `None` are different answers, and
    this is the arm where `0` is the *correct* one. An implementation that wrote `None`
    whenever it could not be bothered would pass the disagreement case and lose every
    agreement from the override history.
    """
    _act(label_world, "accept", None)

    label = _labels(label_world[0])[0]

    assert label["band_distance"] == 0, (
        f"band_distance is {label['band_distance']!r} for a label that kept the system's band"
    )
    assert label["agreed"] == 1, f"agreed is {label['agreed']!r} for an agreeing label"


def test_tc_review_28_the_package_derived_columns_are_populated(label_world):
    """`package_version_id`, `system_points`, `teacher_points`, `panel_config` and
    `recorded_at` all carry values.

    Asserted together because they share one failure mode: `_label_judgement_columns` resolves
    them inside a `try/except Exception: pass`, so a single raise anywhere in the block leaves
    every one of them `None` and the label still writes successfully. One missing column is a
    gap; all five missing is that swallowed exception, and this case tells them apart.
    """
    _act(label_world, "override", TEACHER_BAND)

    label = _labels(label_world[0])[0]
    missing = [
        name
        for name in (
            "package_version_id",
            "system_points",
            "teacher_points",
            "panel_config",
            "recorded_at",
        )
        if label[name] is None
    ]

    assert missing == [], (
        f"FR-REVIEW-21 columns left NULL: {missing}. `_label_judgement_columns` resolves all "
        "of these inside one `except Exception: pass`, so several missing at once means a "
        "raise was swallowed rather than a column being genuinely unknowable"
    )
    assert float(label["system_points"]) == 4.0, (
        f"system_points is {label['system_points']!r}; {SYSTEM_BAND!r} is worth 4.0"
    )
    assert float(label["teacher_points"]) == 8.0, (
        f"teacher_points is {label['teacher_points']!r}; {TEACHER_BAND!r} is worth 8.0"
    )


def test_tc_review_28_a_package_declaring_no_population_scope_records_null(label_world):
    """`assignment_type` is NULL where the package declares no scope.

    Absence is the value: M-STATS reads a missing `assignment_type` as "not recorded" and
    refuses to partition on it, which is the honest answer. Substituting `construct_tag` — a
    different dimension that *is* declared — would produce a confident figure partitioned on
    the wrong axis, and the shipped code says so explicitly.
    """
    _act(label_world, "override", TEACHER_BAND)

    label = _labels(label_world[0])[0]
    assert label["assignment_type"] is None, (
        f"assignment_type is {label['assignment_type']!r} for a package that declares no "
        "population scope; an undeclared scope is not an assumed one"
    )


def test_tc_review_28_no_package_schema_can_declare_a_population_scope(label_world):
    """The `'lab'` arm, recorded as the gap it is rather than left silently unwritten.

    `_label_judgement_columns` reads `entry["assignment_type"]` off a criterion row, and no
    criterion row has ever had that column: `aeh.pkg` does not declare it, `add_criterion` does
    not accept it, and no migration adds it. So the reader is unreachable and the column is
    dead on every label the system can write.

    Asserted as the absence, so the day M-PKG declares the column this case goes red and the
    `'lab'` arm gets written properly. #383 reports it.
    """
    import inspect

    import aeh.pkg as pkg

    assert "assignment_type" not in inspect.getsource(pkg), (
        "`aeh.pkg` now mentions `assignment_type`. If M-PKG has declared the population "
        "scope, TC-REVIEW-28's 'lab' arm is now expressible and belongs in this file — "
        "replace this case with it (#383 reported the gap)"
    )

    store = open_store(label_world[0])
    try:
        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        version = catalog.criteria
        assert callable(version)
    finally:
        store.close()
