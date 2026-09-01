"""`profile_summary()` — the grader identity the console renders and the audit record keeps.

Case: `TC-CONF-09` (`FR-CONF-09`, P1), test plan §5.1. Rung 0.
Oracle: artifact assertion over the returned record — each field asserted present and non-empty
**by name**.

Written ahead of its implementation, and now **green**: issue #5 landed `profile_summary()`, so
the `writtenahead` marker came off and the `WRITTEN_AHEAD_BLOCKERS` entry keyed on
`aeh.conf:RunConfig.profile_summary` was removed. The test is unchanged — that is the point of
the rule: the marker goes, never the case.

`require_attr` stays. It costs nothing now and states what these assertions depend on.

Why this matters beyond the console: `FR-CONSOLE-09` puts this record on **any view showing a
grade**, and the audit record stores it verbatim. A summary missing the transcriber build means
a teacher looking at a grade cannot tell which model read the handwriting.
"""

from __future__ import annotations

import pytest

from aeh.conf import PROVIDER_MANAGED, RunConfig, resolve_run_config
from tests.support.conf_builders import (
    EDGE_PANEL_3,
    HOSTED_PANEL_3,
    SYNTHETIC_COHORT,
    edge_cfg,
    hosted_cfg,
)
from tests.support.impl import require_attr

ISSUE = "#5"


@pytest.mark.parametrize("profile", ["edge-local", "cloud-hosted", "dev-ci"])
def test_tc_conf_09_profile_summary_names_the_backend_every_build_and_the_quantization(profile):
    """TC-CONF-09 — "a resolved config for each profile"; the summary contains the backend
    profile, every panel build, the transcriber build, quantization, and — for cloud — the
    retention setting.

    Asserted **by name and non-empty**, per the oracle, rather than by comparing the whole record
    to an expected literal. A literal comparison would pin the record's shape, which `FR-CONF-09`
    deliberately leaves open (its Compatibility note makes a new `ProfileSummary` field additive);
    a by-name check fails on the thing that actually harms a reader — a field that is absent, or
    present and blank.
    """
    require_attr(RunConfig, "profile_summary", issue=ISSUE)

    cfg = edge_cfg() if profile == "edge-local" else hosted_cfg(profile)
    config = resolve_run_config(cfg, SYNTHETIC_COHORT)

    summary = config.profile_summary()
    rendered = _as_mapping(summary)

    assert rendered.get("backend_profile") == profile

    # Every panel build, not "a panel field that is truthy": a summary that lists the first judge
    # and drops the other two describes a panel that never ran.
    rendered_text = repr(rendered)
    for member in config.panel:
        assert member.build_id in rendered_text, f"panel build {member.build_id} missing"
    assert config.transcriber.build_id in rendered_text, "transcriber build missing"

    for field in ("backend_profile", "panel", "transcriber", "quantization"):
        assert field in rendered, f"{field} absent from profile_summary()"
        assert rendered[field] not in (None, "", (), [], {}), f"{field} present but empty"

    if profile == "cloud-hosted":
        assert rendered.get("retention_setting"), "retention_setting absent on cloud-hosted"


@pytest.mark.parametrize("profile", ["edge-local", "cloud-hosted", "dev-ci"])
def test_tc_conf_09_every_build_appears_in_its_own_field_not_merely_somewhere(profile):
    """The placement half of the oracle, which the substring sweep above cannot see.

    `rendered_text = repr(rendered)` proves each `build_id` is *present*; it cannot prove it is
    in the right **field**. Found by mutation: five defects survived the whole fast tier —
    `panel` truncated to `panel[:1]`, `transcriber` and `panel[0]` swapped, `provider` and
    `quantization` blanked on every build, `quantization` empty instead of `PROVIDER_MANAGED`,
    `retention_setting` replaced by a constant. Every one of them keeps the build ids somewhere
    in the record.

    Three judges, deliberately: with the one-judge panel the other cases use, `panel[:1]` **is**
    the whole panel and a truncating implementation is indistinguishable from a correct one.
    """
    require_attr(RunConfig, "profile_summary", issue=ISSUE)

    panel = EDGE_PANEL_3 if profile == "edge-local" else HOSTED_PANEL_3
    cfg = edge_cfg(panel=panel) if profile == "edge-local" else hosted_cfg(profile, panel=panel)
    config = resolve_run_config(cfg, SYNTHETIC_COHORT)

    summary = config.profile_summary()

    assert len(summary.panel) == 3, "the summary dropped panel members"
    for position, (declared, reported) in enumerate(zip(config.panel, summary.panel)):
        assert reported.build_id == declared.build_id, f"panel[{position}] build_id"
        assert reported.provider == declared.provider, f"panel[{position}] provider"
        assert reported.role == declared.role, f"panel[{position}] role"
        assert reported.quantization == (declared.quantization or PROVIDER_MANAGED), (
            f"panel[{position}] quantization"
        )

    assert summary.transcriber.build_id == config.transcriber.build_id
    assert summary.transcriber.role == "transcriber", (
        "the transcriber slot holds something that is not the transcriber"
    )
    assert summary.transcriber.build_id != summary.panel[0].build_id, (
        "transcriber and panel[0] are the same build, so a swap would be invisible"
    )

    assert all(summary.quantization), "a quantization label is blank; use PROVIDER_MANAGED"
    if profile != "edge-local":
        assert PROVIDER_MANAGED in summary.quantization
    assert summary.panel_build_ref == config.panel_build_ref


def test_tc_conf_09_the_retention_setting_is_this_run_s_and_not_a_constant():
    """`retention_setting` replaced by a fixed string survives a "present and non-empty" check.

    Asserted against the config's own value, and across both hosted values, so a constant cannot
    match both.
    """
    require_attr(RunConfig, "profile_summary", issue=ISSUE)

    from aeh.conf import RETENTION_SETTINGS

    seen = set()
    for value in RETENTION_SETTINGS:
        config = resolve_run_config(
            hosted_cfg("cloud-hosted", panel=HOSTED_PANEL_3, retention_setting=value),
            SYNTHETIC_COHORT,
        )
        assert config.profile_summary().retention_setting == value
        seen.add(config.profile_summary().retention_setting)

    assert len(seen) == len(RETENTION_SETTINGS), "the summary reported a constant"


def test_tc_conf_09_the_summary_carries_no_credential(monkeypatch):
    """`CT-CONF-10` reaches this record too: "`to_persisted_dict()` and `profile_summary()`
    contain no credential value". The full four-surface sentinel scan is `TC-CONF-11` (issue #8);
    this is the one surface `TC-CONF-09` itself constructs, and leaving it unasserted here would
    let a summary ship a key for however long #8 takes to land.
    """
    require_attr(RunConfig, "profile_summary", issue=ISSUE)

    sentinel = "sk-or-v1-SENTINEL-0123456789abcdef"
    monkeypatch.setenv("OPENROUTER_API_KEY", sentinel)

    config = resolve_run_config(hosted_cfg("cloud-hosted"), SYNTHETIC_COHORT)

    assert sentinel not in repr(_as_mapping(config.profile_summary()))


def _as_mapping(summary: object) -> dict:
    """`ProfileSummary`'s concrete type is #5's choice — a dataclass, a `TypedDict`, or a mapping.

    Normalizing here rather than assuming one keeps this case about *content*, which is what the
    oracle names, and stops it failing for a reason `FR-CONF-09` does not care about.
    """
    if isinstance(summary, dict):
        return dict(summary)
    if hasattr(summary, "_asdict"):
        return dict(summary._asdict())
    import dataclasses

    if dataclasses.is_dataclass(summary):
        return dataclasses.asdict(summary)
    return {k: v for k, v in vars(summary).items() if not k.startswith("_")}
