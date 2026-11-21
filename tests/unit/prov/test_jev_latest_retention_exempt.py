"""Regression cases for two owner decisions of 2026-11-20 (no issue; no TC-* covered them).

1. "we should use Jev latest … its called typesafe/jev-latest": the decision build
   `openrouter/typesafe/jev-latest@<date>` is accepted and sent on the wire as
   `typesafe/jev-latest`. One drive of a run cannot drift: `BuildWatch` (FR-PROV-24) fixes the
   served build on the first answer and checks every later one (a run resumed in a new process
   may continue on a newer build; not covered here). A `~` alias and a `:latest` tag are
   still refused.
2. "do not worry about zero data retention for Jev models": a `dev-ci` / `cloud-hosted` run
   whose Jev decision model has no retention confirmation starts, and the run records the model
   as *exempt*, never as confirmed. An unconfirmed panel judge is still refused.

Supersedes FR-PROV-21's floating-alias refusal for Jev, and FR-PROV-28/43/48 and CT-PROV-09's
retention requirement for the decision model. Every case runs under the autouse network guard.
"""

from __future__ import annotations

import json
import re

import pytest

from aeh.conf import CohortRef, ConfigurationError, ModelRef, resolve_run_config
from aeh.orch import Orchestrator
from aeh.prov import OpenRouterProvider, RetentionPolicyError
from aeh.store import open_store
from tests.support.conf_builders import HOSTED_PANEL_3, hosted_cfg
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package

LATEST = "openrouter/typesafe/jev-latest@2026-11-20"
_CRITERIA = ({"criterion_id": "C01", "kind": "open", "scoring_model": "holistic"},)
_SYNTHETIC = CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic")


class _NoNetwork:
    def send(self, request):  # noqa: ANN001
        raise AssertionError(f"no request may leave at run start: {request.method} {request.url}")


def _jev(**kwargs):
    pytest.importorskip("typesafe_sdk")
    from aeh.prov import JevOpenRouterProvider

    return JevOpenRouterProvider(api_key="sk-or-test", transport=_NoNetwork(), **kwargs)


# --- decision 1: the `-latest` alias ----------------------------------------------------------


def test_jev_latest_is_accepted_and_sent_as_the_routers_alias() -> None:
    from aeh.prov.jev_openrouter import _jev_wire_model

    assert _jev_wire_model(LATEST) == "typesafe/jev-latest"
    ModelRef(role="decision", provider="openrouter-jev", build_id=LATEST, quantization=None)


def test_the_exemption_is_keyed_on_the_decision_provider_never_the_build_name() -> None:
    from aeh.prov import retention_exempt

    assert retention_exempt(ModelRef(role="decision", provider="openrouter-jev", build_id=LATEST,
                                     quantization=None))
    # A Jev-named build put on the panel through `openrouter` keeps the gate.
    assert not retention_exempt(ModelRef(role="judge", provider="openrouter", build_id=LATEST,
                                         quantization=None))


@pytest.mark.parametrize("build", ["~typesafe/jev-latest", "openrouter/typesafe/jev:latest@2026-11-20"])
def test_a_tilde_alias_or_a_latest_tag_is_still_refused(build) -> None:
    from aeh.prov.jev_openrouter import _jev_wire_model

    with pytest.raises(ConfigurationError):
        _jev_wire_model(build)


# --- decision 2: no retention gate for Jev decision models ------------------------------------


def _cfg(profile: str, panel=HOSTED_PANEL_3):
    return resolve_run_config(
        hosted_cfg(profile, panel=panel, HARNESS_DECISION_ENGINE="jev", HARNESS_JEV_BUILD=LATEST),
        _SYNTHETIC)


def _panel_provider(unconfirmed: frozenset[str] = frozenset()) -> OpenRouterProvider:
    return OpenRouterProvider(
        api_key="sk-or-test", base_url="https://openrouter.test/api/v1", transport=_NoNetwork(),
        retention_answers=lambda b: "retention: standard" if b in unconfirmed else "zero-retention")


@pytest.mark.parametrize("profile", ["dev-ci", "cloud-hosted"])
def test_an_unconfirmed_jev_engine_does_not_refuse_the_run_and_is_recorded_exempt(
        tmp_data_dir, network_guard, profile) -> None:
    jev = _jev(retention_answers=lambda _b: "retention: standard")
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, ("S001",))
        version = seed_package(store, _CRITERIA)
        run_id = Orchestrator(store, provider=_panel_provider(), decision_provider=jev).create_run(
            ORCH_COHORT_ID, version, _cfg(profile))
        recorded = json.loads(store.cohort(ORCH_COHORT_ID).query(
            "SELECT provider_config FROM run WHERE run_id = :r", r=run_id)[0]["provider_config"])
    finally:
        store.close()
    assert recorded["retention_exempt"] == [LATEST]
    assert LATEST not in recorded["retention_verified"], "an exemption must not read as confirmed"
    assert recorded["retention_verified"] == sorted(ref.build_id for ref in HOSTED_PANEL_3)
    # The engine's own provider is not armed to refuse either.
    assert not jev.verify_retention((_cfg(profile).decision_engine.model,)).unconfirmed
    network_guard.assert_no_network()


def test_an_unconfirmed_panel_judge_is_still_refused_beside_an_exempt_jev_engine(
        tmp_data_dir, network_guard) -> None:
    hedged = HOSTED_PANEL_3[1].build_id
    jev = _jev(retention_answers=lambda _b: "retention: standard")
    store = open_store(tmp_data_dir)
    try:
        seed_cohort(store, ("S001",))
        version = seed_package(store, _CRITERIA)
        with pytest.raises(RetentionPolicyError, match=re.escape(hedged)):
            Orchestrator(store, provider=_panel_provider(frozenset({hedged})),
                         decision_provider=jev).create_run(ORCH_COHORT_ID, version,
                                                           _cfg("cloud-hosted"))
        assert store.cohort(ORCH_COHORT_ID).query("SELECT count(*) AS n FROM run")[0]["n"] == 0
    finally:
        store.close()


def test_the_pipeline_run_start_check_does_not_refuse_an_unconfirmed_jev_engine() -> None:
    from aeh.pipeline.decision_engine import _decision_run_start_checks

    jev = _jev(retention_answers=lambda _b: "retention: standard")
    _decision_run_start_checks(_cfg("cloud-hosted"), jev)  # no raise


def test_a_jev_answer_served_outside_the_pinned_upstream_is_not_refused_for_retention() -> None:
    jev = _jev()
    document = {"provider": "some-other-upstream"}
    assert jev._prepare_document(document) is document
