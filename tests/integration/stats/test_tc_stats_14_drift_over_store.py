"""`TC-STATS-14` — the drift check over a store's population, against a
package baseline, advisory by value and by record.

Test plan §5.16 (`TC-STATS-14`), issue #120 (TS-43). Traces to `FR-STATS-09`.
The plan's row: *"A 20-30 submission sample against a package baseline. The
drift check covers **judged criteria only** and is presented as **advisory,
never as a gate** — asserted by confirming no code path lets its result block
a run."* Exact value plus prohibition assertion, P1.

`CT-STATS-C12` (`test_ct_stats_records_and_absence.py`) pins the range
boundaries, the judged-only declaration and the console's no-gate over the
declared channels. This file adds the rung-2 leg over a real store, where
the *current* side is the store's admissible population (`sample_source`
names the constructor population, and the disclosure is in that field
precisely so the sample's size and the population's are never confused):

- three criteria with hand-computed total-variation distances against the
  declared baseline: one undrifted (0.0), one planted-drifted (0.4, the
  panel's shape moved half the way), one at the boundary (exactly the 0.1
  tolerance, which is drifted — the drift test is `>=`, the same strictness
  `CT-STATS-12`'s boundary discipline uses elsewhere);
- the report's advisory fields are exact values: `advisory` True,
  `binding_threshold` None, and the `why_not_binding` statement in the
  value — the advisory presentation is a property of the value, not of the
  screen rendering it;
- the **prohibition leg**: no code path lets the result block a run. The
  paths that could consume a drift verdict are the console preflight
  (`CT-STATS-C12`'s) and the promotion record — the claim the validation
  tier reads. The record's own shape is pinned here: `promote`'s returned
  `ValidationUpdate` carries no drift field, and the durable
  `package_validation` table holds no drift column — a verdict with nowhere
  to land in the claim cannot gate it.

Isolation: rung 2 — real store, real label rows through `record_label`, the
population `open_stats` reads; the baseline is the declared channel the
design gives `M-PKG`'s records. No provider is reachable (`network_guard`
is autouse and each case asserts it).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import REVIEW_MODULE, STATS_MODULE, require

pytestmark = pytest.mark.integration

#: The baseline `M-PKG`'s record declares, per criterion — five labels at
#: band "1" and five at band "2" is the shape every current distribution is
#: compared against (halfway between the bands, at the scale's middle). The
#: keys are the durable vocabulary's strings: the `label` table's band
#: columns are TEXT (probed), so `open_stats`' read keys its distributions
#: with the record's own spelling and the declared baseline must meet it.
BASELINE: dict[str, tuple[str, ...]] = {
    "C-01": ("1", "1", "1", "1", "1", "2", "2", "2", "2", "2"),
    "C-02": ("1", "1", "1", "1", "1", "2", "2", "2", "2", "2"),
    "C-03": ("1", "1", "1", "2", "2", "2", "2", "2"),
}

#: The current population, per criterion, planted to three distances:
#: C-01 identical (TV = 0.0), C-02 moved (18 at band 1, 2 at band 2 →
#: TV = 0.4), C-03 exactly at the boundary — planted at a *binary-exact*
#: TV of 0.125 (6/12 = 0.5 against 3/8 and 5/8), read under the declared
#: tolerance knob set to 0.125, because 0.1 itself is not representable and
#: an "exactly at tolerance" case computed in decimal rounds into a flap:
#: the boundary is probed where the arithmetic is exact, not where floats
#: decide it.
CURRENT_TABLE: dict[str, dict[tuple[int, int], int]] = {
    "C-01": {(1, 1): 10, (2, 2): 10},
    "C-02": {(1, 1): 18, (2, 2): 2},
    "C-03": {(1, 1): 6, (2, 2): 6},
}

#: The submission sample, inside the declared range (25 ∈ [20, 30]).
SUBMISSIONS = tuple(f"sub-{i:02d}" for i in range(1, 26))


def _seed_store(tmp_data_dir) -> None:
    """The store's blind judged population: the three criteria's planted
    distributions."""
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")
    labels = []
    for criterion, table in CURRENT_TABLE.items():
        for index, ((system, teacher), count) in enumerate(sorted(table.items())):
            for j in range(count):
                labels.append(
                    broken.Label(
                        label_id=f"drift-{criterion}-{index}-{j}",
                        criterion_id=criterion,
                        band=system,
                        teacher_band=teacher,
                    )
                )
    for label in labels:
        record_label(data_dir=tmp_data_dir, label=label)


def _report(tmp_data_dir):
    stats = require(STATS_MODULE, "open_stats", issue="#115")(data_dir=tmp_data_dir)
    drift_check = require(STATS_MODULE, "drift_check", issue="#117")
    return drift_check(
        stats,
        package_version="pkg-v14",
        sample=SUBMISSIONS,
        baseline={criterion: bands for criterion, bands in BASELINE.items()},
    )


# --- the report over the store's population -----------------------------------------------------


def test_tc_stats_14_the_store_population_is_the_current_side(tmp_data_dir, network_guard):
    """The current side is the store's admissible population, and the
    disclosure says so.

    `sample_size` is the submission sample's size (25, inside the declared
    range); the distributions are the constructor population's — the two
    are different disclosures, and `sample_source` is the field that keeps
    them apart. A report that filled the distributions from the sample's
    submission identities would be comparing a baseline against a count of
    submissions nobody labelled."""
    _seed_store(tmp_data_dir)
    report = _report(tmp_data_dir)

    assert report.sample_size == 25
    assert report.sample_ids == SUBMISSIONS
    assert report.sample_source == "constructor_population", (
        f"the report named sample_source={report.sample_source!r}; the current "
        "side came from the store's admissible population, and the disclosure "
        "is in this field precisely so the sample's 25 and the population's "
        "60 are never confused (FR-STATS-09)"
    )
    network_guard.assert_no_network()


def test_tc_stats_14_the_distances_are_the_hand_computed_ones(
    tmp_data_dir, network_guard, monkeypatch
):
    """Per-criterion total variation, exact: 0.0, 0.4 and the 0.125 boundary.

    - C-01: identical shapes → 0.0, not drifted;
    - C-02: current (0.9, 0.1) against (0.5, 0.5) → 0.5·(0.4 + 0.4) = 0.4,
      past the tolerance — the planted drift;
    - C-03: (0.5, 0.5) against (0.375, 0.625) → 0.5·(0.125 + 0.125) = 0.125,
      exactly the tolerance the knob declares for this comparison, and the
      drift test is `>=` — the boundary is drifted, and an implementation
      using `>` leaves a planted drift unnamed. The knob is set to a
      binary-exact value so the case measures the boundary and not decimal
      rounding: 0.1's own boundary arithmetic rounds below itself."""
    monkeypatch.setenv("STATS_DRIFT_TOLERANCE", "0.125")
    _seed_store(tmp_data_dir)
    report = _report(tmp_data_dir)

    assert report.distances["C-01"] == pytest.approx(0.0), (
        f"identical shapes are 0.0, not None — a computed zero is a real "
        f"distance, and the report must say the comparison was made "
        f"(distances were {report.distances!r}; a key-type mismatch between "
        "the store's TEXT bands and the declared baseline reads as disjoint "
        "support, TV = 1.0, not as a comparison failure)"
    )
    assert report.distances["C-02"] == pytest.approx(0.4), (
        "18/20 against 5/10 at band 1 is 0.5·(0.4 + 0.4) = 0.4 — the planted "
        "drift"
    )
    assert report.distances["C-03"] == pytest.approx(0.125), (
        "6/12 against 3/8 and 5/8 is 0.5·(0.125 + 0.125) = 0.125 — exactly "
        "the declared tolerance"
    )
    assert report.drifted == ("C-02", "C-03"), (
        f"the drifted criteria were {report.drifted!r}; the 0.4 criterion and "
        "the boundary one are drifted at the declared tolerance, and the "
        "undrifted one is not — a report naming C-03 un-drifted has silently "
        "changed the boundary test"
    )
    assert report.severity == pytest.approx(0.4)
    assert report.baseline_distributions == {
        "C-01": {"1": 5, "2": 5},
        "C-02": {"1": 5, "2": 5},
        "C-03": {"1": 3, "2": 5},
    }, (
        "the declared baseline did not arrive verbatim; the comparison's "
        "other side is the record's own shape and is reported beside the "
        "distances"
    )
    network_guard.assert_no_network()


def test_tc_stats_14_advisory_and_never_binding_are_in_the_value(
    tmp_data_dir, network_guard
):
    """`advisory` is True and `binding_threshold` is None — on the report,
    at rung 2.

    The advisory presentation is a property of the value, not of whichever
    screen renders it: a rung-2 report that rendered a binding threshold
    would gate the next caller that trusts the field, regardless of what the
    console chose to do with it."""
    _seed_store(tmp_data_dir)
    report = _report(tmp_data_dir)

    assert report.advisory is True
    assert report.binding_threshold is None, (
        f"the report carried binding_threshold={report.binding_threshold!r}; "
        "FR-STATS-09: the check is advisory, and a value that names a "
        "binding threshold is a gate waiting for a reader"
    )
    assert report.why_not_binding, (
        "the advisory value carries no statement of what would make it "
        "binding and why none exists — the clause's statement in the value"
    )
    network_guard.assert_no_network()


# --- the prohibition: no code path lets the result block a run ----------------------------------


def test_tc_stats_14_no_drift_field_reaches_the_validation_record(
    tmp_data_dir, network_guard
):
    """The claim path cannot consult drift: the record's shape carries no
    drift field, durably.

    Two paths consume a validation run: the console preflight (`CT-STATS-C12`
    pins its no-gate) and the promotion record the package tier reads. This
    pins the second at its two surfaces — `promote`'s returned update and the
    `package_validation` table the record writes — so a future consumer
    cannot inherit a drift field that already sits there: the gate would
    appear as a column before anyone wrote the check for it."""
    _seed_store(tmp_data_dir)
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")
    stats = open_stats(data_dir=tmp_data_dir, cohort_id="coh-14")
    update = stats.promote(cohort_id="coh-14", package_version="pkg-v14")

    drift_fields = [
        name for name in dir(update) if "drift" in name.lower()
    ]
    assert drift_fields == [], (
        f"promote's record carries {drift_fields}; the validation record's "
        "shape has no drift field to consume, which is what keeps the "
        "advisory check out of the claim path (FR-STATS-09, CT-STATS-12)"
    )
    assert update.message != vocab.NO_NEW_VALIDATION_EVIDENCE or update.blind_count == 0, (
        "precondition: the record was the no-evidence message, so the "
        "promotion did not claim this store's labels and the durable column "
        "assertion below pins an empty shape"
    )

    database_path = Path(tmp_data_dir) / "durable.sqlite"
    connection = sqlite3.connect(str(database_path))
    try:
        columns = [
            row[1] for row in connection.execute("PRAGMA table_info(package_validation)")
        ]
    finally:
        connection.close()
    drift_columns = [name for name in columns if "drift" in name.lower()]
    assert drift_columns == [], (
        f"package_validation carries {drift_columns}; the durable record has "
        "no drift column, so no code path can read the advisory result into "
        "the claim the package tier makes (FR-STATS-09)"
    )
    network_guard.assert_no_network()