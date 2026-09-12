"""`TC-STATS-23` — the subgroup analysis with the knob set, and Tier D
pseudonymized in both states.

Test plan §5.16 (`TC-STATS-23`), issue #120 (TS-43). Traces to
`NFR-STATS-05`. The plan's row: *"Subgroup analysis with
`STATS_SUBGROUP_ANALYSIS_ENABLED` unset and set. Off by default; Tier D
remains pseudonymized in both cases."* Exact value, P0.

The gate's two halves live in different files by what each can fail on:

- **the off-by-default and the closed-gate refusal** are `CT-STATS-C18`'s
  (`test_ct_stats_checks_and_scope.py`): the knob defaults to its declared
  value, the report carries no breakdowns at the default, and a request
  while the gate is closed is the refusal, not an empty result.
  Cross-referenced, not repeated.
- **the enabled case is this file's** (`NFR-STATS-05`'s *"subgroup
  breakdowns run only where enabled and lawful"*, the lawfulness arm): with
  the knob set, the requested breakdown runs and its values are the declared
  ``subgroup_correlations=`` channel verbatim — the subgroup figures are the
  caller-declared measured channel, the same declared-channel pattern every
  #117 comparison reads. An implementation that shipped `None` where the
  knob is open, or that broke down criteria the request did not scope to,
  fails the exact-value assertions here.
- **Tier D remains pseudonymized in both cases** — the row's second clause,
  asserted at the schema: the durable tier's every table is swept for a
  student-name column with the knob **unset** and with it **set**, the sweep
  running after a real analysis in each state. Enabling a subgroup analysis
  is the act most likely to tempt a per-student figure, so the sweep runs in
  both states: the knob's position is not a licence the schema honors, and
  the guarantee is what makes the statistics tier permanent (Tier C is purged
  and Tier D is not — `CT-STORE-C09`'s reason, swept here in both knob states
  from the consumer side).

Isolation: rung 0 for the enabled report (in-memory population, declared
channel); rung 2 for the Tier D sweep (real store through `record_label`'s
durable route, the schema read back through sqlite3 — `TC-STATS-11`'s read
path). No provider is reachable (`network_guard` is autouse and each case
asserts it).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support import stats_vocabulary as vocab
from tests.support.impl import REVIEW_MODULE, STATS_MODULE, require

pytestmark = pytest.mark.integration

#: The declared knob's name (`#117`'s vocabulary), not a string this file
#: invents — the gate's two halves must read the same knob.
KNOB = vocab.SUBGROUP_ANALYSIS_KNOB

CRITERION = "C-01"
SUBGROUP = "declared_group"

#: The surface channel beside the subgroup one: nothing in it reaches the
#: declared 0.7 threshold, so the report's flags stay empty and the two
#: channels' figures are separable in the assertions below.
SURFACE_CHANNEL: dict[str, dict[str, float]] = {
    CRITERION: {"response_length_tokens": 0.11},
}


def _stats(subgroup_channel: dict[str, dict[str, float]]):
    """The rung-0 report's constructor with both declared channels: the
    surface correlations the flags read, the subgroup correlations the
    breakdown reads."""
    validation_stats = require(STATS_MODULE, "ValidationStats", issue="#115")
    return validation_stats(
        broken.agreeing_population(),
        scoring_models={CRITERION: "atomic"},
        band_counts={CRITERION: 4},
        surface_correlations=SURFACE_CHANNEL,
        subgroup_correlations=subgroup_channel,
    )


def test_tc_stats_23_the_enabled_knob_runs_the_requested_breakdown(
    network_guard, monkeypatch
):
    """`STATS_SUBGROUP_ANALYSIS_ENABLED=1`, subgroup requested by name: the
    breakdown is the declared channel, exactly.

    The exact-value assertion is what separates "enabled" from "runs
    something": the breakdown's values are the declared channel's — a
    breakdown computed from anything else, or `None` shipped under an open
    gate, is a subgroup analysis nobody declared (`NFR-STATS-05` gates the
    analysis on local lawfulness, which is the caller's declaration, not
    the module's guess). The refusal while closed is `CT-STATS-C18`'s, and
    the off-default is its knob default — both cross-referenced."""
    monkeypatch.setenv(KNOB, "1")
    stats = _stats({CRITERION: {"ocr_quality_score": 0.42}})

    report = stats.surface_proxies(
        cohort_id="coh-1", criterion_id=CRITERION, subgroup=SUBGROUP
    )
    assert report.subgroup_breakdowns == {CRITERION: {"ocr_quality_score": 0.42}}, (
        f"the enabled breakdown was {report.subgroup_breakdowns!r}; the open "
        "gate and the named subgroup run the declared channel exactly — a "
        "None here is the closed gate's shape arriving under an open one, "
        "and any other value is a breakdown nobody declared (NFR-STATS-05, "
        "TC-STATS-23)"
    )
    assert report.correlations == SURFACE_CHANNEL, (
        f"the report's surface correlations were {report.correlations!r}; "
        "the subgroup request rides beside the surface report — the flags' "
        "channel is not replaced or reshaped by asking for a breakdown"
    )
    assert report.surface_proxy_flags == {}, (
        "the surface channel carried nothing above the threshold and the "
        "subgroup request changed it; the breakdown rides beside the "
        "surface report, it does not replace its figures"
    )
    network_guard.assert_no_network()


def test_tc_stats_23_the_criterion_scope_holds_under_an_open_gate(
    network_guard, monkeypatch
):
    """With the gate open, a request scoped to one criterion breaks down only
    that criterion's channel.

    `NFR-STATS-05`'s gate opens the *analysis*, not every criterion's
    figures: the breakdown for a scoped request is the scoped channel's —
    a criterion outside the request's scope does not ride along in a report
    the caller narrowed on purpose."""
    monkeypatch.setenv(KNOB, "1")
    other = "C-02"
    subgroup_channel = {
        CRITERION: {"ocr_quality_score": 0.42},
        other: {"response_length_tokens": -0.61},
    }
    stats = _stats(subgroup_channel)

    report = stats.surface_proxies(
        cohort_id="coh-1", criterion_id=CRITERION, subgroup=SUBGROUP
    )
    assert report.subgroup_breakdowns == {CRITERION: {"ocr_quality_score": 0.42}}, (
        f"the scoped request broke down {report.subgroup_breakdowns!r}; the "
        "caller narrowed on C-01 and the breakdown is that criterion's "
        "channel — the other criterion's subgroup figures are not part of "
        "the narrowed report (NFR-STATS-05, TC-STATS-23)"
    )
    network_guard.assert_no_network()


# --- Tier D remains pseudonymized in both knob states ------------------------------------------


def _seed(tmp_data_dir) -> None:
    """Four blind judged labels through the durable collection route — the
    Tier D rows an enabled subgroup analysis would most plausibly want to
    name by student."""
    record_label = require(REVIEW_MODULE, "record_label", issue="#110")
    for index in range(4):
        record_label(
            data_dir=tmp_data_dir,
            label=broken.Label(
                label_id=f"tierd-{index}",
                criterion_id=CRITERION,
                band=3,
                teacher_band=3,
            ),
        )


def _tier_d_name_columns(tmp_data_dir) -> list[str]:
    """Every Tier D column carrying a student-name-shaped name — the sweep
    `CT-STORE-C09` pins from the store side, read here from the consumer
    side."""
    database_path = Path(tmp_data_dir) / "durable.sqlite"
    connection = sqlite3.connect(str(database_path))
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        assert tables, "Tier D has no tables, so the column sweep is vacuous"
        named = []
        for table in tables:
            columns = [
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            ]
            named += [
                f"{table}.{column}"
                for column in columns
                if any(
                    term in column.lower()
                    for term in ("student_name", "pupil_name", "family_name")
                )
            ]
        return named
    finally:
        connection.close()


def test_tc_stats_23_tier_d_remains_pseudonymized_in_both_knob_states(
    tmp_data_dir, network_guard, monkeypatch
):
    """The durable tier carries no student-name column, knob unset and set.

    The sweep runs twice over one real store, once after the lawful
    default-state analysis and once after the enabled run with the subgroup
    requested — the pseudonymization is the schema's, so the knob's state
    cannot move it, and the assertion is that the enabled analysis did not
    open a per-student hole: the store the subgroup report reads is the same
    pseudonymized Tier D either way (`NFR-STATS-05`, `CT-STORE-C09`'s
    guarantee, the pairing that makes the whole statistics tier permanent)."""
    _seed(tmp_data_dir)
    open_stats = require(STATS_MODULE, "open_stats", issue="#115")

    # The unset state, run as it ships: the knob where §3.16 leaves it, the
    # report requested without a subgroup (the closed-gate refusal for a
    # named request is CT-STATS-C18's, not re-asserted here).
    monkeypatch.delenv(KNOB, raising=False)
    open_stats(tmp_data_dir).surface_proxies(
        cohort_id="coh-23", criterion_id=CRITERION
    )
    unset_columns = _tier_d_name_columns(tmp_data_dir)

    # The enabled state: the knob set, the subgroup requested by name over
    # the same real store — the analysis most likely to tempt a per-student
    # figure has now actually run.
    monkeypatch.setenv(KNOB, "1")
    open_stats(tmp_data_dir).surface_proxies(
        cohort_id="coh-23", criterion_id=CRITERION, subgroup=SUBGROUP
    )
    set_columns = _tier_d_name_columns(tmp_data_dir)

    assert unset_columns == [] and set_columns == [], (
        f"with the knob unset the sweep found {unset_columns} and with it "
        f"set {set_columns}; Tier D remains pseudonymized in both states — "
        "enabling the subgroup analysis is the act most likely to tempt a "
        "per-student figure, and the durable tier (which survives the cohort "
        "purge) carries no name column either way (NFR-STATS-05, "
        "CT-STORE-C09)"
    )
    network_guard.assert_no_network()