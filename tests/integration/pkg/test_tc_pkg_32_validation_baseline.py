"""`TS-92` (issue #386) — `TC-PKG-32`: the promoted administration's judged distribution
becomes the criterion's baseline (`FR-AGG-08`'s baseline input, `#373`, Q-21).

| Input | Expected |
|---|---|
| promote an administration with judged band histogram `{1: 10, 2: 20, 3: 10}` for `C1` | `expected_mean = 2.0`, `expected_sd = 0.7071` (population SD), `expected_histogram` equal as JSON |

**Hand-computed, and the arithmetic is pinned here because a wrong scale is invisible.** Over
ordinals 1, 2 and 3 with counts 10, 20 and 10:

    n     = 40
    mean  = (1·10 + 2·20 + 3·10) / 40 = 80 / 40 = 2.0
    var   = (10·(1−2)² + 20·(2−2)² + 10·(3−2)²) / 40 = 20 / 40 = 0.5
    sd    = √0.5 = 0.70710678…

**Population SD, not sample.** The histogram *is* the administration's judged distribution,
not a draw from a larger one to be estimated, so the divisor is `n` rather than `n − 1`. The
two differ here by √(40/39) ≈ 1.3% — small enough to look like rounding and large enough to
move a z-score at the escalation boundary. Dividing by `n` also keeps a single-label
administration expressible as sd 0.0 rather than a division by zero.

**The scale is the DECLARED band ordinal, and that is the load-bearing part.**
`should_escalate` computes `z = (ordinal − expected_mean) / expected_sd` against the score's
declared ordinal. A baseline computed on any other scale — the band's name read as a number,
or an inferred rank — would be a z-score between two different spaces: wrong by a constant for
every package, and silently so. This fixture names its bands so that name and ordinal are
*different* (`"band-1"` at ordinal 1), which is what makes the two scales distinguishable; a
fixture whose bands were named `"1"`, `"2"`, `"3"` would pass either way.

**Isolation: rung 2** — a real Tier P package on disk, its real band table, and the real
writer.
"""

from __future__ import annotations

import json
import math
import sqlite3
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
from aeh.pkg import (
    BASELINE_RECORDED,
    BASELINE_UNDECLARED_BAND,
    PackageCatalog,
    record_validation_baseline,
)
from aeh.store import open_store

pytestmark = pytest.mark.integration

CRITERION = "C1"
PACKAGE_ID = "pkg-baseline"

#: Bands whose NAME differs from their ORDINAL, so a baseline computed on the wrong scale is
#: distinguishable. Ordinal 0 exists because the table is 0-based and contiguous; it carries no
#: labels in this administration, which is ordinary.
BANDS = ((0, "band-0", 0.0), (1, "band-1", 2.0), (2, "band-2", 4.0), (3, "band-3", 6.0))

#: The plan's histogram, by band NAME — what `M-STATS` counts, because a label carries a name.
HISTOGRAM = {"band-1": 10, "band-2": 20, "band-3": 10}

EXPECTED_MEAN = 2.0
EXPECTED_SD = math.sqrt(0.5)  # 0.70710678…
EXPECTED_HISTOGRAM = {"1": 10, "2": 20, "3": 10}


@pytest.fixture
def package_world(tmp_data_dir):
    """A real package version declaring `C1` over the four bands."""
    store = open_store(tmp_data_dir)
    try:
        handle = store.package(PACKAGE_ID)
        with handle.transaction() as tx:
            tx.execute(
                "INSERT INTO package (package_id, created_at) VALUES (:p, :created)",
                p=PACKAGE_ID, created="2026-01-01T00:00:00+00:00",
            )
        catalog = PackageCatalog(handle, package_id=PACKAGE_ID)
        version = catalog.create_version(None)
        catalog.add_criterion(
            version, CRITERION, kind="open", scoring_model="atomic",
            band_count=len(BANDS),
        )
        for ordinal, band, points in BANDS:
            catalog.add_band(version, CRITERION, ordinal, band, points)
    finally:
        store.close()
    return tmp_data_dir, version


def _record(tmp_data_dir, version: str) -> dict[str, Any] | None:
    for path in sorted((tmp_data_dir / "packages").glob("*.pkg.sqlite")):
        connection = sqlite3.connect(str(path))
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                "SELECT expected_mean, expected_sd, expected_histogram FROM "
                "validation_record WHERE package_version_id = ? AND criterion_id = ?",
                (version, CRITERION),
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        finally:
            connection.close()
        if rows:
            return dict(rows[0])
    return None


# --- TC-PKG-32 --------------------------------------------------------------------------------


def test_tc_pkg_32_the_baseline_carries_the_hand_computed_mean_and_population_sd(
    package_world,
):
    """`expected_mean = 2.0` and `expected_sd = √0.5`, from the declared ordinals."""
    tmp_data_dir, version = package_world

    written = record_validation_baseline(
        tmp_data_dir,
        package_version_id=version,
        criterion_id=CRITERION,
        band_histogram=HISTOGRAM,
    )

    assert written.recorded, f"the baseline was not written: {written}"
    assert written.reason == BASELINE_RECORDED, (
        f"a successful write reported {written.reason!r}; the reason is always set so a "
        "caller's log line never has to special-case success"
    )
    record = _record(tmp_data_dir, version)
    assert record is not None, "no validation_record row was created"

    assert record["expected_mean"] == pytest.approx(EXPECTED_MEAN), (
        f"expected_mean is {record['expected_mean']!r}, not {EXPECTED_MEAN}. Over ordinals "
        "1, 2, 3 with counts 10, 20, 10 the mean is 80/40"
    )
    assert record["expected_sd"] == pytest.approx(EXPECTED_SD, abs=1e-9), (
        f"expected_sd is {record['expected_sd']!r}, not {EXPECTED_SD:.7f}. The histogram IS "
        "the administration's distribution, so the divisor is n, not n−1 — the sample SD "
        f"here is {math.sqrt(20 / 39):.7f}, which differs by about 1.3% and looks like "
        "rounding while moving a z-score at the escalation boundary"
    )


def test_tc_pkg_32_the_stored_histogram_is_keyed_by_ordinal(package_world):
    """`expected_histogram` is `{"1": 10, "2": 20, "3": 10}` — ordinals, not band names.

    Keyed by the ordinal so the record is self-consistent: a reader that recomputes the mean
    from the stored histogram gets the stored mean back. Keyed by name it could not, because
    the names are not numbers — and this fixture's names are `band-1`…`band-3` precisely so
    that a name-keyed implementation is visible rather than coincidentally right.
    """
    tmp_data_dir, version = package_world
    record_validation_baseline(
        tmp_data_dir, package_version_id=version, criterion_id=CRITERION,
        band_histogram=HISTOGRAM,
    )

    record = _record(tmp_data_dir, version)
    stored = json.loads(str(record["expected_histogram"]))

    assert stored == EXPECTED_HISTOGRAM, (
        f"expected_histogram is {stored}, not {EXPECTED_HISTOGRAM}"
    )

    total = sum(stored.values())
    recomputed = sum(int(ordinal) * count for ordinal, count in stored.items()) / total
    assert recomputed == pytest.approx(record["expected_mean"]), (
        f"recomputing the mean from the stored histogram gives {recomputed}, but the row "
        f"holds {record['expected_mean']}. The record contradicts itself"
    )


def test_tc_pkg_32_the_scale_is_the_ordinal_and_not_the_band_name(package_world):
    """The mean is 2.0 — the ordinal scale — and not anything the names could produce.

    The discriminating case for `should_escalate`'s z-score. The bands are named `band-1`…
    `band-3`, so an implementation reading the name as a number cannot produce 2.0 at all; one
    ranking the names alphabetically would land on 1.0 (0-based rank over three present bands).
    Asserting the value is 2.0 *and* not 1.0 says which scale was used rather than only that
    some number arrived.
    """
    tmp_data_dir, version = package_world
    record_validation_baseline(
        tmp_data_dir, package_version_id=version, criterion_id=CRITERION,
        band_histogram=HISTOGRAM,
    )

    mean = _record(tmp_data_dir, version)["expected_mean"]

    assert mean == pytest.approx(EXPECTED_MEAN)
    assert mean != pytest.approx(1.0), (
        "the mean is 1.0, which is what a 0-based rank over the three PRESENT bands gives. "
        "`should_escalate` compares against the criterion's DECLARED ordinal, so a baseline "
        "on an inferred scale is a z-score between two different spaces — wrong by a constant "
        "for every package, and silently"
    )


def test_tc_pkg_32_a_histogram_naming_an_undeclared_band_is_refused(package_world):
    """A band the criterion does not declare refuses, and writes nothing.

    A mean over a scale the package does not declare is fabricated, and a partial mean over
    "the ones I recognised" is worse: it silently drops a band and shifts the baseline. The
    refusal carries its reason, so a caller can report what happened instead of assuming the
    write landed.
    """
    tmp_data_dir, version = package_world

    written = record_validation_baseline(
        tmp_data_dir,
        package_version_id=version,
        criterion_id=CRITERION,
        band_histogram={**HISTOGRAM, "band-nine": 5},
    )

    assert not written.recorded, "a histogram naming an undeclared band was accepted"
    assert written.reason == BASELINE_UNDECLARED_BAND, (
        f"the refusal's reason is {written.reason!r}"
    )
    assert _record(tmp_data_dir, version) is None, (
        "the refused write left a validation_record row behind"
    )


def test_tc_pkg_32_an_empty_histogram_writes_nothing(package_world):
    """No labels means no baseline — not a baseline of zero.

    The guard on the case above: a writer that accepted anything would also accept `{}` and
    store a mean over an empty population, which is a `ZeroDivisionError` at best and a
    fabricated 0.0 at worst.
    """
    tmp_data_dir, version = package_world

    written = record_validation_baseline(
        tmp_data_dir, package_version_id=version, criterion_id=CRITERION,
        band_histogram={},
    )

    assert not written.recorded
    assert _record(tmp_data_dir, version) is None
