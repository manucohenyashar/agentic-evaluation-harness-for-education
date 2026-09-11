"""`TC-STATS-11` — the planted surface-proxy signal, detected and carried.

Test plan §5.16 (`TC-STATS-11`), issue #120 (TS-43). Traces to `FR-STATS-07`.
The plan's row: *"Scores regressed against response length, vocabulary
complexity, OCR quality, legibility band and formatting regularity, with a
planted length correlation. The planted correlation is detected and stored in
`package_validation.surface_proxy_flags`; subgroup breakdowns run only where
enabled and lawful."* Planted-signal detection, P1.

Two halves, this file and the store:

- **the detection half (here, rung 0)** — a planted length correlation is
  detected: `surface_proxy_flags` names exactly the features whose ``|r|``
  reaches the declared threshold, the alert fires (`CT-STATS-19` — the
  surface-proxy alert is the only detector for a criterion with an excellent
  κ and no validity), and the negative control shows the report silent where
  nothing was planted. Detection that fires on every channel is no detector.
- **the durable half** — the same flags reaching
  `package_validation.surface_proxy_flags` through `promote` (`CT-STATS-15`'s
  indirection), stored as the record's field. That half is
  `test_tc_stats_11_promote_flags.py` in the integration tier: a
  `package_validation` row needs a store, and this file stays at the plan's
  Unit / 0 level.

The *subgroup breakdowns only where enabled and lawful* half of the row is
`CT-STATS-C18` (off by default, a refusal when requested while closed) and
`test_tc_stats_23_subgroup_enabled.py` (the enabled case) — cross-referenced,
not repeated.

The correlations arrive through the declared channel (`surface_correlations=`,
the constructor's measured channel — #116's pattern): the regression against
the five surface features is the pipeline's computation, and what `M-STATS`
owns is the interpretation. The planted values are hand-picked around the
declared threshold 0.7 so every flag decision is checkable: a planted
``+0.82`` on response length, a planted ``−0.75`` on OCR quality (the equity
direction `NFR-INGEST-07` opened — OCR error tracks handwriting, not
understanding, and a negative correlation is as much the finding as a
positive one), and a below-threshold ``+0.30`` that must be disclosed without
being flagged.

Isolation: rung 0 — in-memory labels through `build_stats`. Interface: the
landed `surface_proxies` surface (#117) and the alerts (#118).
"""

from __future__ import annotations

import pytest

from tests.support import broken_stats_fixtures as broken
from tests.support.impl import STATS_MODULE, require

pytestmark = pytest.mark.contract

CRITERION = "C-01"

#: The planted channel. Every value is hand-picked against the declared
#: threshold (`STATS_SURFACE_PROXY_CORRELATION_THRESHOLD` = 0.7): two planted
#: signals, one on each sign, and one quiet feature the report must not flag.
PLANTED_CHANNEL: dict[str, dict[str, float]] = {
    CRITERION: {
        "response_length_tokens": 0.82,
        "ocr_quality_score": -0.75,
        "vocabulary_complexity": 0.30,
    },
}
#: The same channel, minus the planting — the negative control's shape.
QUIET_CHANNEL: dict[str, dict[str, float]] = {
    CRITERION: {
        "response_length_tokens": 0.11,
        "ocr_quality_score": -0.04,
        "vocabulary_complexity": 0.30,
    }
}


def _population() -> list:
    """A blind judged population for the criterion — the figures the
    correlations are *about*. The proxy decision reads the channel, but the
    report's ``n`` is the population's, so a real one keeps the report
    honest about what it speaks for."""
    return broken.agreeing_population()


def _report(channel: dict[str, dict[str, float]]):
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(
        labels=_population(),
        scoring_models={CRITERION: "atomic"},
        band_counts={CRITERION: 4},
        surface_correlations=channel,
    )
    return stats, stats.surface_proxies()


# --- the planted signal -----------------------------------------------------------------------


def test_tc_stats_11_the_planted_correlations_are_flagged_exactly():
    """The planted length and OCR correlations are the flags; the quiet
    feature is disclosed, not flagged.

    ``surface_proxy_flags`` is the shape the validation record stores —
    exactly `CT-STATS-11`'s detection claim — so the assertion is on its
    exact value: two features, both signs, the below-threshold one absent
    from the flags but present in ``correlations`` (a feature not captured is
    absent from the disclosure, not measured at zero — and a measured one is
    disclosed at its value, never collapsed into the flag)."""
    stats, report = _report(PLANTED_CHANNEL)
    assert report.surface_proxy_flags == {
        CRITERION: {
            "response_length_tokens": 0.82,
            "ocr_quality_score": -0.75,
        }
    }, (
        f"the flags were {report.surface_proxy_flags!r}; the planted channel "
        "carries +0.82 on response length and −0.75 on OCR quality against "
        "the declared 0.7 threshold, and the +0.30 on vocabulary complexity "
        "must be disclosed without being flagged (FR-STATS-07)"
    )
    assert report.correlations[CRITERION]["vocabulary_complexity"] == 0.30, (
        "the below-threshold feature vanished from the disclosure; the flags "
        "are the *decision*, the correlations are the *measurement*, and a "
        "report that keeps only the decision can be re-thresholded by nobody"
    )


def test_tc_stats_11_the_flags_reach_the_threshold_on_absolute_value():
    """A negative correlation at the same magnitude is the same finding.

    OCR quality *degrading* as scores rise — the equity direction — is at
    least as serious as length tracking them, and an implementation flagging
    ``r >= threshold`` while missing ``r <= −threshold`` would stay silent on
    exactly the case the surface-proxy analysis exists for."""
    _stats, report = _report(PLANTED_CHANNEL)
    flagged = report.surface_proxy_flags[CRITERION]
    assert "ocr_quality_score" in flagged, (
        f"the negative planted correlation ({flagged!r}) was not flagged; the "
        "threshold reads |r|, and the inverse direction is the finding's "
        "equity half (NFR-INGEST-07's loop, TC-STATS-13's consumer)"
    )


def test_tc_stats_11_the_captured_features_name_what_the_channel_measured():
    """``captured_features`` is the channel's coverage of `SURFACE_FEATURES`.

    The disclosure is the honest scope of the regression: the three features
    the planted channel carries — and none of the two it does not. A report
    that names a feature the channel never measured would let a reader
    believe the pipeline regressed against it."""
    _stats, report = _report(PLANTED_CHANNEL)
    assert set(report.captured_features) == {
        "response_length_tokens",
        "ocr_quality_score",
        "vocabulary_complexity",
    }, (
        f"captured_features was {report.captured_features!r}; the channel "
        "carries exactly those three of the five declared features, and the "
        "uncaptured two (legibility band, formatting regularity) are absent "
        "from the disclosure, not measured at zero"
    )


def test_tc_stats_11_the_planted_signal_fires_the_surface_proxy_alert():
    """The alert fires on the flagged criterion, with the figures in its
    detail (`CT-STATS-19`).

    The surface-proxy alert is the only detector for a criterion with an
    excellent κ and no validity — every other view is downstream of the
    score. Its detail names the criterion and each flagged feature at its
    correlation, so an operator reading the alert sees the finding, not a
    count."""
    stats, planted = _report(PLANTED_CHANNEL)
    assert planted.surface_proxy_flags, (
        "precondition: the planted channel produced no flags, so this alert "
        "assertion would test the alert on nothing"
    )
    alerts = stats.alerts()
    names = [alert.name for alert in alerts]
    assert require(STATS_MODULE, "SURFACE_PROXY_ALERT", issue="#117") in names, (
        f"the alerts were {names!r}; a planted length correlation on "
        f"{CRITERION} fires the surface-proxy alert — the only detector that "
        "sees a score tracking surface features (CT-STATS-19)"
    )
    proxy_alerts = [alert for alert in alerts if alert.name == "surface_proxy_flag_on_criterion"]
    assert len(proxy_alerts) == 1, (
        f"{len(proxy_alerts)} surface-proxy alerts for one criterion's one "
        "channel; the alert is per flagged criterion, deterministic in sorted "
        "order"
    )
    assert CRITERION in proxy_alerts[0].detail, (
        f"the alert detail {proxy_alerts[0].detail!r} does not name the "
        "criterion the flag is about"
    )
    assert "response_length_tokens" in proxy_alerts[0].detail, (
        f"the alert detail {proxy_alerts[0].detail!r} does not name the "
        "planted feature"
    )


# --- the negative control ----------------------------------------------------------------------


def test_tc_stats_11_a_quiet_channel_produces_no_flags_and_no_alert():
    """The same channel without the planting: no flags, no alert.

    Detection that fires on every channel is no detector — the negative
    control is what makes the planted cases above a measurement of the
    threshold decision rather than a tautology. The below-threshold ``+0.30``
    rides along in both channels for the same reason: a report that flagged
    it would fail the planted case and this one alike."""
    stats, report = _report(QUIET_CHANNEL)
    assert report.surface_proxy_flags == {}, (
        f"the quiet channel flagged {report.surface_proxy_flags!r}; nothing "
        "above the threshold was planted, so a flag here is the detector "
        "firing on noise — and the planted case means nothing (FR-STATS-07)"
    )
    assert stats.alerts() == (), (
        f"the quiet channel fired {stats.alerts()!r}; the surface-proxy alert "
        "is the detector for a score tracking a surface feature, and a quiet "
        "channel is not that finding"
    )


def test_tc_stats_11_an_undeclared_channel_is_an_empty_report():
    """No channel declared: the empty report, not a zero (`CT-STATS-16`).

    The proxy interpretation reads a declared measured channel; nothing
    declared is nothing measured. A report carrying empty flags here would
    be indistinguishable from the quiet channel's — and 'the pipeline never
    ran the regression' would read as 'the pipeline found nothing'."""
    build_stats = require(STATS_MODULE, "build_stats", issue="#115")
    stats = build_stats(labels=_population())
    report = stats.surface_proxies()
    assert report.surface_proxy_flags == {}
    assert report.correlations == {}, (
        "no channel was declared and the report still carries correlations; "
        "the empty report is the absence value — nothing measured is not "
        "nothing found"
    )