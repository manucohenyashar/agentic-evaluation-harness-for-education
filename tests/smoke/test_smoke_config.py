"""The smoke suite (TS-50, issue #143) — configuration resolution and its report.

`TC-SMOKE-02` (`FR-CONF-01`) — `resolve_run_config` succeeds for the configured profile and
reports it; fails if unresolvable or defaulted. `TC-SMOKE-11` (`FR-CONF-09`) — the build
version, resolved model builds and backend profile are all reported and match configuration;
fails on version drift between what is deployed and what is reported.

Both run over the real `M-CONF` on the suite's `edge-local` builders, and both oracles are
**exact** rather than exception-shaped: the profile that comes back is the one that was
configured (an implementation that silently defaulted would report a different name), and
every build the summary names is `BuildSummary.of` the ref the configuration carried, in
panel order. The three-judge panel matters here for the reason `conf_builders` documents:
with a single-member panel, an implementation that reports only `panel[:1]` is
indistinguishable from a correct one, so the drift half of the oracle uses `EDGE_PANEL_3`.

`Written ahead of implementation: yes` is stale — `M-CONF` landed with #4-#8; the cases run
green by design.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from aeh.conf import (
    BuildSummary,
    ConfigurationError,
    compute_panel_build_ref,
    log_run_start,
    resolve_run_config,
)
from tests.support.conf_builders import (
    EDGE_JUDGE,
    EDGE_JUDGE_2,
    EDGE_JUDGE_3,
    EDGE_PANEL_3,
    EDGE_TRANSCRIBER,
    PROMPT_TEMPLATE_V,
    SYNTHETIC_COHORT,
    edge_cfg,
)


def _resolve(**overrides):
    return resolve_run_config(edge_cfg(**overrides), SYNTHETIC_COHORT)


def test_tc_smoke_02_resolve_run_config_reports_the_configured_profile():
    """`TC-SMOKE-02` — resolution succeeds for the configured profile and reports exactly
    what was configured.

    Oracle: **exact value, both directions**. The resolved `RunConfig` carries the configured
    profile name, panel and transcriber — a resolver that defaulted or second-guessed the
    configuration reports a different name or a different panel and reds here. Unresolvable
    input (an unrecognized profile, an absent profile key) raises `ConfigurationError`
    rather than defaulting: `CT-CONF-11` makes "no key has a silent default that selects a
    backend" contract, and a resolver that picked an edge profile when the operator misspelled
    one would send a run to hardware that does not exist.
    """
    resolved = _resolve(panel=EDGE_PANEL_3)
    assert resolved.backend_profile == "edge-local"
    assert resolved.panel == EDGE_PANEL_3
    assert resolved.transcriber == EDGE_TRANSCRIBER
    assert resolved.prompt_template_v == PROMPT_TEMPLATE_V
    # "reports it" — the run-start report names the configured profile, not a default's.
    assert resolved.profile_summary().backend_profile == "edge-local"

    unrecognized = edge_cfg(HARNESS_PROFILE="gpu-cluster")
    with pytest.raises(ConfigurationError):
        resolve_run_config(unrecognized, SYNTHETIC_COHORT)
    absent = edge_cfg()
    del absent["HARNESS_PROFILE"]
    with pytest.raises(ConfigurationError):
        resolve_run_config(absent, SYNTHETIC_COHORT)


def test_tc_smoke_11_reported_builds_and_profile_match_configuration():
    """`TC-SMOKE-11` — the build version, resolved model builds and backend profile are all
    reported, and match configuration.

    Oracle: **field-by-field equality against the configuration**. Every panel build appears
    in panel order (all three, not the first), the transcriber appears, each reported
    `BuildSummary` carries exactly the provider/build-id/quantization the configured ref
    names (the build id *is* the build version — `@sha256:` or a dated tag — so a summary
    that names a different version than the config deployed is drift, reported here), the
    backend profile matches, and `panel_build_ref` is the hash over the **configured ordered
    panel** — the identity every audit record files the run under. The drift check is
    bidirectional: a one-quantization change in the panel must change the reported ref, so a
    reporter that recomputes over a stale or truncated panel cannot pass.

    `log_run_start` returns the record it logged (`CT-CONF-13`), and it must be the same
    record `profile_summary()` reports — one grader identity, not two.
    """
    resolved = _resolve(panel=EDGE_PANEL_3)
    summary = resolved.profile_summary()

    assert summary.backend_profile == "edge-local"
    assert summary.panel == tuple(
        BuildSummary.of(ref) for ref in EDGE_PANEL_3
    ), (
        "TC-SMOKE-11: the reported panel builds do not match the configured ones, in panel "
        "order. A summary that drops a judge or reorders the panel describes a run that "
        "never happened."
    )
    assert summary.transcriber == BuildSummary.of(EDGE_TRANSCRIBER)
    assert summary.panel_build_ref == compute_panel_build_ref(EDGE_PANEL_3), (
        "TC-SMOKE-11: the reported panel_build_ref is not the hash of the configured "
        "panel. This is the identity the audit files the run under — drift here means the "
        "deployed grader and the recorded one are different systems."
    )
    # Distinct labels, first-seen order: two q4 judges plus a q4 transcriber dedup to one
    # "q4", and EDGE_JUDGE_3's q8 adds a second label — the mixed-panel read.
    assert summary.quantization == ("q4", "q8")

    # Deterministic by construction: resolving the same configuration twice reports the
    # same identity.
    assert _resolve(panel=EDGE_PANEL_3).profile_summary().panel_build_ref == (
        summary.panel_build_ref
    )
    # Drift is visible: change one panel build, the reported identity changes with it.
    q8_judge = replace(EDGE_JUDGE_2, quantization="q8")
    different = _resolve(panel=(EDGE_JUDGE, q8_judge, EDGE_JUDGE_3))
    assert different.profile_summary().panel_build_ref != summary.panel_build_ref, (
        "TC-SMOKE-11: changing one panel build's quantization did not change the reported "
        "panel_build_ref. A grader identity that survives a build change is version drift "
        "between what is deployed and what is reported — FR-CONF-09's failure mode."
    )

    logged = log_run_start(resolved)
    assert logged == summary, (
        "TC-SMOKE-11: the summary logged at run start differs from the one "
        "profile_summary() reports. Two graders' identities for one run is exactly the "
        "drift TC-CONF-17's differential exists to forbid."
    )