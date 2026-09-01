"""The consent gate — student work does not leave the machine without consent.

Cases: `TC-CONF-08` (`FR-CONF-08`, **P0**, RISK-10 **Critical**) and `SEC-02` (§6.5), test plan
§5.1. Rung 0.

RISK-10 is the risk register's worst entry for this module: *"Real, non-consented student work is
dispatched to a remote provider"* — blast radius "every student in the cohort; a reportable
data-protection incident", **not** detectable ("the run succeeds") and **not** recoverable
("disclosure is irreversible"). Nothing downstream catches it. This gate is the only thing
between a mis-declared cohort and that outcome, which is why the decision table below is
enumerated rather than sampled.
"""

from __future__ import annotations

import pytest

from aeh.conf import (
    ConfigurationError,
    ConsentGateError,
    ConsentOverride,
    consent_override_for,
    resolve_run_config,
)
from tests.support.conf_builders import (
    EDGE_PANEL_3,
    HOSTED_PANEL_3,
    edge_cfg,
    hosted_cfg,
)
from aeh.conf import CohortRef

SUPPLIER = "head-of-year@school.example"

#: A cohort per `consent_class`, plus one created with **no explicit declaration** — which ADR-5
#: requires default to `real`. That last row is the one `TC-CONF-08` calls "the difference
#: between a fail-closed and a fail-open design", so it is built by *omitting* the argument
#: rather than by passing `"real"`: passing it would test the wrong thing, since a gate that
#: ignored the default entirely would still pass.
COHORTS = {
    "synthetic": CohortRef("c-2026-7B", "synthetic"),
    "consented": CohortRef("c-2026-7B", "consented"),
    "real": CohortRef("c-2026-7B", "real"),
    "undeclared": CohortRef("c-2026-7B"),
}


def _cfg(backend: str, *, override: object = None, supplier: object = None, panel_3: bool = False):
    if backend == "edge-local":
        cfg = edge_cfg(panel=EDGE_PANEL_3) if panel_3 else edge_cfg()
    else:
        cfg = hosted_cfg(backend, panel=HOSTED_PANEL_3) if panel_3 else hosted_cfg(backend)
    if override is not None:
        cfg["HARNESS_ALLOW_REMOTE_REAL_WORK"] = override
    if supplier is not None:
        cfg["allow_remote_real_work_supplied_by"] = supplier
    return cfg


# --- TC-CONF-08: the decision table -----------------------------------------------------------

#: Every cell of `TC-CONF-08`'s table, enumerated. `edge-local` is crossed with **all four**
#: consent classes rather than the plan's "any", because "any" is the claim being tested.
_DECISION_TABLE = [
    pytest.param("edge-local", "synthetic", None, None, id="edge-local_synthetic"),
    pytest.param("edge-local", "consented", None, None, id="edge-local_consented"),
    pytest.param("edge-local", "real", None, None, id="edge-local_real"),
    pytest.param("edge-local", "undeclared", None, None, id="edge-local_undeclared"),
    pytest.param("edge-local", "real", "true", None, id="edge-local_real_override"),
    pytest.param("cloud-hosted", "synthetic", None, None, id="cloud-hosted_synthetic"),
    pytest.param("cloud-hosted", "consented", None, None, id="cloud-hosted_consented"),
    pytest.param("cloud-hosted", "real", None, ConsentGateError, id="cloud-hosted_real"),
    pytest.param("cloud-hosted", "undeclared", None, ConsentGateError, id="cloud-hosted_undeclared"),
    pytest.param("cloud-hosted", "real", "true", None, id="cloud-hosted_real_with_override"),
    pytest.param("dev-ci", "real", None, ConsentGateError, id="dev-ci_real"),
    pytest.param("dev-ci", "undeclared", None, ConsentGateError, id="dev-ci_undeclared"),
    pytest.param("dev-ci", "synthetic", None, None, id="dev-ci_synthetic"),
]


@pytest.mark.parametrize("backend,consent,override,expected", _DECISION_TABLE)
def test_tc_conf_08_the_consent_decision_table(backend, consent, override, expected):
    """TC-CONF-08 — every cell of the decision table, with its exact outcome.

    Oracle (§5.1): exact exception type or exact success.

    The `edge-local` rows are not filler. The plan writes them as "any / any", which is a claim —
    that a local run is ungated because nothing can leave the machine — and a gate that refused
    a `real` cohort locally would make the air-gapped tier (§4.5 E5) unrunnable for exactly the
    cohorts it exists to serve. The `edge-local` + override row resolves for the same reason:
    an override where no gate applies is an inapplicable key, handled like every other one in
    this module.
    """
    cohort = COHORTS[consent]
    supplier = SUPPLIER if override else None
    cfg = _cfg(backend, override=override, supplier=supplier)

    if expected is None:
        config = resolve_run_config(cfg, cohort)
        assert config.backend_profile == backend
        return

    with pytest.raises(expected) as caught:
        resolve_run_config(cfg, cohort)
    assert type(caught.value) is expected


def test_tc_conf_08_an_undeclared_cohort_is_refused_exactly_as_a_real_one_is():
    """The load-bearing row, asserted as an equivalence rather than as two separate outcomes.

    `TC-CONF-08`: *"The undeclared-cohort row is the load-bearing one: it is the difference
    between a fail-closed and a fail-open design."* ADR-5 makes `real` the column default "so a
    cohort created without an explicit declaration cannot be dispatched remotely by accident".

    Asserting that the two refusals are the **same type** is stronger than asserting each
    refuses: it fails an implementation that special-cases the undeclared cohort into some
    softer outcome — a warning, a different error, a different code path — which is precisely
    how fail-open is reintroduced by someone trying to be helpful.
    """
    outcomes = {}
    for label in ("real", "undeclared"):
        with pytest.raises(ConsentGateError) as caught:
            resolve_run_config(_cfg("cloud-hosted"), COHORTS[label])
        outcomes[label] = type(caught.value)

    assert outcomes["undeclared"] is outcomes["real"] is ConsentGateError
    assert COHORTS["undeclared"].consent_class == "real", "ADR-5's default is the whole mechanism"


@pytest.mark.parametrize("falsy", ["false", "False", "FALSE", " false ", "0", "no", "off", ""])
def test_tc_conf_08_variant_the_override_is_not_truthy_coerced(falsy):
    """TC-CONF-08's stated variant: *"`allow_remote_real_work` supplied as the string `"false"`
    must not be truthy-coerced."*

    Every non-empty string is truthy in Python, so `if cfg.get(key):` opens the gate for the
    operator who set it to turn the override **off** — the failure mode that reads as a
    deliberate authorisation in the audit trail and was the opposite.
    """
    with pytest.raises(ConsentGateError):
        resolve_run_config(_cfg("cloud-hosted", override=falsy, supplier=SUPPLIER), COHORTS["real"])


@pytest.mark.parametrize("malformed", ["y", "yes please", "enabled", "TRUE!", 1, 2, 1.0, [], {}])
def test_tc_conf_08_variant_a_malformed_override_never_opens_the_gate(malformed):
    """The third equivalence class on the override axis, and the one that was missing.

    The truthy-coercion case above uses only *recognized* falsy tokens. A value that is neither
    recognized-true nor recognized-false is a different branch, and the failure it guards is the
    worse one: `parse_allow_remote_real_work` returning `True` for anything it does not
    understand. Verified by mutation — under that defect,
    `HARNESS_ALLOW_REMOTE_REAL_WORK="y"` with a named supplier dispatches real student work to a
    remote provider, and every other cell of this table still passes.

    Refused as `ConfigurationError`: the value is unparseable, so the gate never gets a verdict
    to act on. Either declared type is a refusal; what must never happen is a resolution.
    """
    cfg = _cfg("cloud-hosted", supplier=SUPPLIER)
    cfg["HARNESS_ALLOW_REMOTE_REAL_WORK"] = malformed

    with pytest.raises((ConfigurationError, ConsentGateError)):
        resolve_run_config(cfg, COHORTS["real"])


@pytest.mark.parametrize("supplier", [None, "", "   "])
def test_tc_conf_08_an_override_without_a_named_supplier_is_refused(supplier):
    """TC-CONF-08's oracle: *"a record naming the override but not its supplier fails."*

    An override nobody is accountable for is the set-once-and-forget configuration flag ADR-5
    set out to replace — *"explicit and logged rather than a flag someone sets once and
    forgets"*. `ConsentGateError` rather than `ConfigurationError` because the outcome is a
    refused remote binding for non-consented work, and `CT-CONF-08` makes the four types a
    closed taxonomy that `M-ORCH` branches on to raise consent-required UX.
    """
    cfg = _cfg("cloud-hosted", override="true")
    if supplier is not None:
        cfg["allow_remote_real_work_supplied_by"] = supplier

    with pytest.raises(ConsentGateError) as caught:
        resolve_run_config(cfg, COHORTS["real"])
    assert type(caught.value) is ConsentGateError


def test_tc_conf_08_the_override_row_writes_an_audit_record_naming_both():
    """TC-CONF-08's artifact assertion on the override row.

    `FR-CONF-08` says the override "and its supplier are written to the audit record". `M-CONF`
    writes nothing (`CT-CONF-09`), so it *produces* the record and `M-ORCH` persists it — the
    assertion here is that the record exists and carries both facts, which is what makes the
    dispatch attributable six months later.
    """
    cfg = _cfg("cloud-hosted", override="true", supplier=SUPPLIER)
    cohort = COHORTS["real"]

    resolve_run_config(cfg, cohort)  # resolves, per the table
    record = consent_override_for(cfg, cohort)

    assert isinstance(record, ConsentOverride)
    assert record.supplied_by == SUPPLIER, "a record without its supplier fails this case"
    assert record.cohort_id == cohort.cohort_id
    assert record.consent_class == "real", "the record must say what it overrode"
    assert record.backend_profile == "cloud-hosted"


@pytest.mark.parametrize(
    "backend,consent",
    [("cloud-hosted", "synthetic"), ("cloud-hosted", "consented"), ("edge-local", "real")],
)
def test_tc_conf_08_no_audit_record_when_no_override_was_needed(backend, consent):
    """The negative half of the artifact assertion. A record produced for a run that needed no
    override would put a spurious "someone authorised remote real work" row in the audit trail —
    and an audit trail with false entries is worse than one with none."""
    assert consent_override_for(_cfg(backend), COHORTS[consent]) is None


def test_tc_conf_08_the_gate_and_the_audit_record_cannot_disagree():
    """`consent_override_for` and the gate inside `resolve_run_config` must be one rule.

    Two implementations of the same decision is how a run gets dispatched under an override
    while the audit record says none was used, or the reverse. Swept over the whole table:

    * whenever resolution **succeeds**, asking for the record must also succeed, and the record
      must be non-`None` exactly when an override was what let it through;
    * whenever resolution **refuses**, asking for the record must refuse identically — a
      caller cannot obtain an authorisation record for a dispatch that was never authorised.

    That second half is why `consent_override_for` is asserted to raise rather than to return
    `None` on a refused config: `None` reads as "no override was needed", which is the opposite
    of what happened.
    """
    for backend in ("edge-local", "cloud-hosted", "dev-ci"):
        for label, cohort in COHORTS.items():
            for override in (None, "true"):
                cfg = _cfg(backend, override=override, supplier=SUPPLIER if override else None)
                where = f"{backend}/{label}/override={override}"

                try:
                    resolve_run_config(cfg, cohort)
                    resolved = True
                except (ConsentGateError, ConfigurationError):
                    resolved = False

                if not resolved:
                    # The **same** type, not "one of two". `CT-CONF-08`'s taxonomy is what
                    # `M-ORCH` branches on to raise consent-required UX, so a record request
                    # that refused with `ConfigurationError` where resolution said
                    # `ConsentGateError` is a real divergence — and a disjunction here would
                    # not see it.
                    with pytest.raises(ConsentGateError) as caught:
                        consent_override_for(cfg, cohort)
                    assert type(caught.value) is ConsentGateError, where
                    continue

                record = consent_override_for(cfg, cohort)
                needed_override = (
                    backend in ("cloud-hosted", "dev-ci") and cohort.consent_class == "real"
                )
                if needed_override:
                    assert record is not None, f"{where} resolved under an unrecorded override"
                    assert record.supplied_by == SUPPLIER, where
                else:
                    assert record is None, f"{where} recorded an override that was never needed"


# --- SEC-02 -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "profile", ["Cloud-Hosted", "cloud-hosted ", " cloud-hosted", "CLOUD-HOSTED", "cloud_hosted"]
)
def test_tc_conf_08_an_unrecognized_profile_cannot_yield_an_audit_record(profile):
    """The input class where the gate and the record could diverge, and the sweep above cannot
    reach: a `HARNESS_PROFILE` that is *nearly* a remote profile.

    `consent_override_for` reads the key directly while `resolve_run_config` validates it first,
    so a near-miss made resolution refuse while the record request answered `None` — which reads
    as "no override was needed" for a run that can never start. The two must refuse together.
    """
    cfg = _cfg("cloud-hosted")
    cfg["HARNESS_PROFILE"] = profile

    with pytest.raises(ConfigurationError):
        resolve_run_config(cfg, COHORTS["real"])
    with pytest.raises(ConfigurationError):
        consent_override_for(cfg, COHORTS["real"])


def test_sec_02_the_machine_to_remote_provider_boundary_refuses_unconsented_work():
    """SEC-02 (§6.5) — trust boundary: **machine to remote provider**. Threat: information
    disclosure / OWASP A01.

    Probe, verbatim: *"Attempt a `cloud-hosted` run against a cohort with `consent_class =
    'real'` and against one with none declared."* Expected defense: *"`ConsentGateError` in
    both; the override path is explicit and audited."*

    Written from the **boundary** rather than from the requirement, which is what makes it worth
    having next to `TC-CONF-08`: §6.5 notes that this threat model has no accounts, so
    authentication probes are replaced by boundary-refusal probes. The assertion is that
    *nothing* crosses this boundary for unconsented work — so it sweeps **every** remote profile
    the module knows, not the one the requirement happens to name. A fourth remote backend added
    later is caught here and by nothing else.
    """
    from aeh.conf import REMOTE_PROFILES

    assert REMOTE_PROFILES, "there must be at least one remote profile for this boundary to exist"

    for backend in sorted(REMOTE_PROFILES):
        for label in ("real", "undeclared"):
            with pytest.raises(ConsentGateError) as caught:
                resolve_run_config(_cfg(backend, panel_3=True), COHORTS[label])
            assert type(caught.value) is ConsentGateError, f"{backend}/{label}"


def test_sec_02_the_override_path_is_explicit_and_audited():
    """SEC-02's second clause — "the override path is explicit and audited".

    **Explicit**: it takes a deliberate value plus a named supplier; neither absence nor a falsy
    string opens it (asserted above and re-asserted here as the boundary property).
    **Audited**: crossing the boundary always leaves a record naming who authorised it.
    """
    from aeh.conf import REMOTE_PROFILES

    for backend in sorted(REMOTE_PROFILES):
        cfg = _cfg(backend, override="true", supplier=SUPPLIER, panel_3=True)
        config = resolve_run_config(cfg, COHORTS["real"])
        record = consent_override_for(cfg, COHORTS["real"])

        assert config.backend_profile == backend
        assert record is not None and record.supplied_by == SUPPLIER, (
            f"work crossed the boundary on {backend} with no attributable authorisation"
        )
