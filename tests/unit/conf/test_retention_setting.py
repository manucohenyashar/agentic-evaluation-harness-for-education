"""Zero-retention routing on `cloud-hosted`.

Case: `TC-CONF-12` (`FR-CONF-12`, **P0**, negative), test plan §5.1. Rung 0.
Oracle: exact exception type.

**Written ahead of implementation** (issue #6). Issue #4 passes `retention_setting` through
without validating it, deliberately — asserting `FR-CONF-12` before its code exists would make
#6's own case pass on arrival. Remove the `writtenahead` marker — not the test — when #6 closes.

Why P0 for a field that looks like a preference: `FR-CONF-12` and `R4`/`R31` make this the switch
that decides whether student work sent to a remote provider is retained by that provider. An
unset value resolving to "whatever the provider does by default" is the failure mode, and it is
invisible — the run completes, the grades are fine, and the data is somewhere else.
"""

from __future__ import annotations

import pytest

from aeh.conf import ConfigurationError, resolve_run_config
from tests.support.conf_builders import SYNTHETIC_COHORT, edge_cfg, hosted_cfg
from tests.support.impl import require_attr

pytestmark = pytest.mark.writtenahead

ISSUE = "#6"


def _require_retention_validation():
    """#6's landing signal.

    `FR-CONF-12` adds behaviour, not a name this test can predict, so it keys on
    `rehydrate_run_config` — fixed by design §3.1's Interfaces block, so #6 must add it under
    exactly that name. Same detector as `WRITTEN_AHEAD_BLOCKERS["#6"]`, so the marker and the
    failure reason cannot disagree.

    Returns the vocabulary #6 declared, so the cases below assert the *mechanism* rather than a
    set of literals. Neither `FR-CONF-12` nor the plan names the legal values — only
    "unrecognized refuses" — so hard-coding them here would invent a requirement with less
    design backing than the 1500/2000 Assumption `TC-CONF-10` deliberately refuses to cement.
    """
    import aeh.conf

    require_attr(aeh.conf, "rehydrate_run_config", issue=ISSUE)
    return set(getattr(aeh.conf, "RETENTION_SETTINGS", ()))


def test_tc_conf_12_an_unset_retention_setting_is_refused_on_cloud_hosted():
    """TC-CONF-12 — "unset refuses" (`FR-CONF-12` verbatim: "refuse to produce a `RunConfig` when
    it is unset for that profile").

    Fails closed: the absence of an instruction is not permission to use the provider's default.
    """
    _require_retention_validation()

    cfg = hosted_cfg("cloud-hosted")
    cfg.pop("retention_setting")

    with pytest.raises(ConfigurationError) as caught:
        resolve_run_config(cfg, SYNTHETIC_COHORT)
    assert type(caught.value) is ConfigurationError


@pytest.mark.parametrize("unrecognized", ["retain", "30-days", "", "true", "ZERO-RETENTION"])
def test_tc_conf_12_an_unrecognized_retention_setting_is_refused(unrecognized):
    """TC-CONF-12 — "unrecognized refuses".

    Each value is checked to be **outside** whatever set #6 declares before it is asserted to be
    refused, so this case never hardens into a demand that a particular vocabulary be rejected —
    only that a value the module does not recognize is. `ZERO-RETENTION` is here for the same
    reason `EDGE-LOCAL` is in `TC-CONF-01`: a case-insensitive match would accept a near-miss,
    and the cost is a run proceeding in the belief that retention is off.
    """
    recognized = _require_retention_validation()
    if unrecognized in recognized:
        pytest.skip(f"{unrecognized!r} is in the vocabulary #6 declared, so it is not a negative")

    with pytest.raises(ConfigurationError):
        resolve_run_config(
            hosted_cfg("cloud-hosted", retention_setting=unrecognized), SYNTHETIC_COHORT
        )


def test_tc_conf_12_a_recognized_retention_setting_is_recorded_on_the_config():
    """TC-CONF-12 — "set is recorded on the config", over every value #6 declares recognized.

    The positive half, and not a formality: a validator that checked the value and dropped it
    would pass both negatives above while leaving the audit record unable to say what the run
    was configured to do.
    """
    recognized = _require_retention_validation()
    assert recognized, (
        "FR-CONF-12 requires a recognized set to validate against. Issue #6 should expose it as "
        "`aeh.conf.RETENTION_SETTINGS` so this case and `conf_builders` read it rather than "
        "guessing a vocabulary the design never names."
    )

    for value in sorted(recognized):
        config = resolve_run_config(
            hosted_cfg("cloud-hosted", retention_setting=value), SYNTHETIC_COHORT
        )
        assert config.retention_setting == value


def test_tc_conf_12_retention_is_not_required_on_edge_local():
    """`CT-CONF-02` scopes the requirement to `cloud-hosted` — "`retention_setting` is non-null
    for `cloud-hosted`", and nothing leaves the machine on `edge-local`. A validator that
    demanded it everywhere would make the air-gapped tier (§4.5 E5) unrunnable."""
    _require_retention_validation()

    config = resolve_run_config(edge_cfg(), SYNTHETIC_COHORT)

    assert config.retention_setting is None
