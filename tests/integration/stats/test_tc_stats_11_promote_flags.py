"""`TC-STATS-11` — the durable half: the planted flags reach the
validation record.

Test plan §5.16 (`TC-STATS-11`), issue #120 (TS-43). Traces to `FR-STATS-07`.
The plan's row ends *"The planted correlation is detected and **stored** in
`package_validation.surface_proxy_flags`"* — and storage is a claim about a
durable row, not about a return value. The detection half is
`test_tc_stats_11_surface_proxy_detection.py` (rung 0); this file drives the
same planted channel through `promote` over a real store and asserts the row
the package tier reads:

- the channel is declared on the constructor — `ValidationStats` accepts
  both ``data_dir=`` (the rung-2 claim's durable file) and
  ``surface_correlations=`` (the measured channel) as declared parameters,
  and this leg is the combination the two constructor channels make
  reachable (`open_stats` reads the store and carries no correlations
  channel; `build_stats` carries the channel and no store — the record's
  flags need both);
- the record's payload carries the **flagged** criteria, not the channel's:
  a two-criterion channel with one planted and one quiet criterion writes
  exactly the planted one — an implementation carrying the channel's keys,
  or the feature names, or nothing, each fails a different assertion here;
- the quiet-channel control writes the empty JSON array on a row that
  *does* carry evidence — the same blind population, the same counters — so
  the empty flags say "nothing flagged", never "no evidence" (the
  `NO_NEW_VALIDATION_EVIDENCE` message is the no-evidence shape, and the two
  must not collapse).

The rung-2 shape with **no** channel declared — ``surface_proxy_flags == ()``,
"the record says so rather than inventing flags" — is `#119`'s pinned
cross-reference (`test_administration_records.py`), not repeated here.

Isolation: rung 2 — real store, real label rows through `record_label`, the
durable `package_validation` row read back through sqlite3 (`TC-STATS-14`'s
prohibition leg's read path). No provider is reachable (`network_guard` is
autouse and each case asserts it).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import REVIEW_MODULE, STATS_MODULE, require

pytestmark = pytest.mark.integration

#: The two criteria the channel spans: C-01 carries the planted signals
#: (+0.82 response length, −0.75 OCR quality — the unit file's planted
#: channel, against the declared 0.7 threshold), C-02 the quiet one. The
#: discriminating shape: "store the flagged criteria" and "store the
#: channel's criteria" differ by exactly C-02's absence.
PLANTED_CHANNEL: dict[str, dict[str, float]] = {
    "C-01": {
        "response_length_tokens": 0.82,
        "ocr_quality_score": -0.75,
        "vocabulary_complexity": 0.30,
    },
    "C-02": {
        "response_length_tokens": 0.11,
        "ocr_quality_score": -0.04,
        "vocabulary_complexity": 0.30,
    },
}
#: The same channel, minus the planting — the durable negative control.
QUIET_CHANNEL: dict[str, dict[str, float]] = {
    "C-01": {
        "response_length_tokens": 0.11,
        "ocr_quality_score": -0.04,
        "vocabulary_complexity": 0.30,
    },
    "C-02": {
        "response_length_tokens": 0.11,
        "ocr_quality_score": -0.04,
        "vocabulary_complexity": 0.30,
    },
}

COHORT = "coh-11"
PACKAGE_VERSION = "pkg-v11"

#: Ten blind judged labels per criterion — the population the claim counts,
#: so the record's row speaks for real evidence, not the no-evidence shape.
LABELS_PER_CRITERION = 10


def _seed_store(tmp_data_dir) -> None:
    """The store's blind judged population: ten agreeing labels per
    criterion, inserted with no cohort — the unclaimed rows `promote` claims."""
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")
    for criterion in PLANTED_CHANNEL:
        for index in range(LABELS_PER_CRITERION):
            record_label(
                data_dir=tmp_data_dir,
                label=broken.Label(
                    label_id=f"proxy-{criterion}-{index}",
                    criterion_id=criterion,
                    band=3,
                    teacher_band=3,
                ),
            )


def _stats(tmp_data_dir, channel):
    """The record's writer over the store, with the correlations channel
    declared — the two constructor channels combined."""
    validation_stats = require(STATS_MODULE, "ValidationStats", issue="#115")
    return validation_stats(
        [],
        scoring_models={criterion: "atomic" for criterion in channel},
        band_counts={criterion: 4 for criterion in channel},
        surface_correlations=channel,
        data_dir=tmp_data_dir,
    )


def _durable_row(tmp_data_dir):
    """The `package_validation` row the promote wrote, read back."""
    database_path = Path(tmp_data_dir) / "durable.sqlite"
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "SELECT surface_proxy_flags, blind_count, message "
            "FROM package_validation "
            "WHERE package_version_id = ? AND cohort_id = ?",
            (PACKAGE_VERSION, COHORT),
        ).fetchall()
    finally:
        connection.close()
    assert len(rows) == 1, (
        f"{len(rows)} durable rows keyed ({PACKAGE_VERSION!r}, {COHORT!r}); "
        "the record is one row per (package_version_id, cohort_id) and the "
        "assertions below read exactly that row"
    )
    return rows[0]


# --- the planted flags reach the durable row ---------------------------------------------------


def test_tc_stats_11_the_planted_flags_are_stored_in_package_validation(
    tmp_data_dir, network_guard
):
    """The planted channel's flags are on the record's return value and in
    the durable row — the flagged criterion, and only it.

    `surface_proxy_flags` on the update is the tuple of criterion ids whose
    flags the threshold decision produced; the durable column carries the
    same payload as the JSON document `record_promotion` transports. The
    channel spans two criteria and only C-01 was planted, so the record's
    payload discriminates three failure shapes at once: carrying the
    channel's keys writes ["C-01", "C-02"], carrying the feature names
    writes the features, and dropping the channel writes [] — each fails
    here for its own reason."""
    _seed_store(tmp_data_dir)
    update = _stats(tmp_data_dir, PLANTED_CHANNEL).promote(
        cohort_id=COHORT, package_version=PACKAGE_VERSION
    )

    assert update.blind_count == 2 * LABELS_PER_CRITERION, (
        "precondition: the claim counted no blind population, so the durable "
        "assertions below would pin flags on a no-evidence row"
    )
    assert update.message == "", (
        "precondition: the record carried the no-evidence message, so the "
        "flags below ride a row that speaks for nothing"
    )
    assert update.surface_proxy_flags == ("C-01",), (
        f"the update carried {update.surface_proxy_flags!r}; the planted "
        "channel spans C-01 (flagged: +0.82, −0.75) and C-02 (quiet), and "
        "the record's payload is the flagged criteria — not the channel's "
        "keys and not the features (FR-STATS-07)"
    )

    row = _durable_row(tmp_data_dir)
    assert json.loads(row["surface_proxy_flags"]) == ["C-01"], (
        f"package_validation.surface_proxy_flags was "
        f"{row['surface_proxy_flags']!r}; the stored record must name the "
        "flagged criterion — the durable shape the package tier reads "
        "(TC-STATS-11's storage claim)"
    )
    assert row["blind_count"] == 2 * LABELS_PER_CRITERION
    network_guard.assert_no_network()


# --- the durable negative control --------------------------------------------------------------


def test_tc_stats_11_a_quiet_channel_stores_an_empty_record_on_a_real_row(
    tmp_data_dir, network_guard
):
    """The quiet channel stores `[]` — on a row that carries evidence.

    The durable negative control: nothing above the threshold was planted,
    so the record says `[]` while still claiming the store's blind
    population. An implementation that stored the channel's criteria
    regardless of the threshold writes ["C-01", "C-02"] here and fails; one
    that refused to write a row at all when no flags exist also fails — the
    row is the administration's record, and *nothing flagged* is a finding
    about the pipeline, not the absence of one."""
    _seed_store(tmp_data_dir)
    update = _stats(tmp_data_dir, QUIET_CHANNEL).promote(
        cohort_id=COHORT, package_version=PACKAGE_VERSION
    )

    assert update.blind_count == 2 * LABELS_PER_CRITERION
    assert update.message != vocab.NO_NEW_VALIDATION_EVIDENCE, (
        "precondition: this row is the no-evidence shape, so the empty "
        "flags asserted next would not say 'nothing flagged' — they would "
        "say nothing at all"
    )
    assert update.surface_proxy_flags == (), (
        f"the quiet channel's update carried {update.surface_proxy_flags!r}; "
        "nothing above the threshold was planted, so a flag here is the "
        "detector firing on noise, stored (the unit tier's quiet control "
        "pins the report; this pins its record)"
    )

    row = _durable_row(tmp_data_dir)
    assert json.loads(row["surface_proxy_flags"]) == [], (
        f"package_validation.surface_proxy_flags was "
        f"{row['surface_proxy_flags']!r} on the quiet channel; the empty "
        "record is the honest 'nothing flagged' — the row still claims the "
        "store's blind population, and the flags column says the regression "
        "found no surface proxy (FR-STATS-07)"
    )
    network_guard.assert_no_network()