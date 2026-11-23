"""`TC-PROV-71` — retention checked before anything is sent (FR-PROV-48, CT-PROV-09; RSV-33).

Statistical-validity test plan r2 §3.23, story T21 (issue #905). Written ahead of S30 (#872),
which has landed: the `writtenahead` marker and its blocker entry are gone.

SV-33: zero retention was verified only for the decision engine before dispatch and for the
panel at the first call, and only on `cloud-hosted`. FR-PROV-48 widens FR-PROV-14 to every
remote profile: on `dev-ci` too, run start and the reading job call `verify_retention` for every
build they will dispatch to — panel, escalation judges, decision engine; the transcriber for the
reading job — and refuse before the first student byte leaves, naming the model.
Re-based on the owner decision of 2026-11-20: the Jev decision engine is exempt from zero
retention, so it is not probed and is recorded as `retention_exempt`.

Re-based again on the owner decision of 2026-11-22 ("All models should not ask for zero
retention as this policy is managed by my OpenRouter account outside the system"): no
OpenRouter-routed build — panel, escalation judges, Jev engine, transcriber — is probed or
refused, on any remote profile; the run records `retention = "managed by the OpenRouter
account"` with the builds under `retention_account_managed`, and no probe cost (nothing was
probed). The probe, its once-per-build census and the knob still apply to a remote-profile
build whose retention the account does not manage, which the knob case pins with a panel named
under a local provider.
`HARNESS_RETENTION_PRECHECK=0` turns the probe off for the recorded tier only. The probe's cost
is recorded on the run.

Isolation: rung 3. The console's own run start door (`start_run_in_background`, what "start
run" calls) over a real store, with the real `OpenRouterProvider` and `JevOpenRouterProvider` on
a programmed transport; and `TC-CONSOLE-77`'s reading job (`tests/support/reading_world.py`).

The probe's wire shape is still open (delta §10 Q12), so it is **not** pinned: the census reads
the builds each `verify_retention` call names. What is pinned is what the plan states — once per
distinct build, before any request reaches the model endpoint, and nothing carrying student text
on a refusal.

Interface bets (each a small reconcile when #872 lands):

* the probe's cost is recorded on the run as a `run_metrics` metric or a `provider_config` leaf
  (nested keys read by dotted path) whose name carries `retention` (or `probe`) and `cost`,
  with a figure (not None);
* the recorded tier is `RecordedFixtureProvider`, the provider the knob is scoped to;
* the probe goes through `verify_retention` (and OpenRouter's `retention_answers` seam). A probe
  sent as a one-token POST through the transport would be counted as a model request by the
  ordering check, and the reading world's stand-in would not know how to answer it; a models
  listing (a GET) is answered by both stand-ins;
* the refusal is synchronous: `start_run_in_background` raises and no run row exists, the house
  pattern of `create_run`'s cloud-hosted gate. A refusal that paused the run in the worker
  instead would read here as "not refused".

Note for the implementer: on `cloud-hosted` today the decision model is verified twice (in
`create_run`'s gate and again in `pipeline.decision_engine._decision_run_start_checks`).
Widening both to `dev-ci` as they stand fails "once per distinct build".
"""

from __future__ import annotations

import json
import re
from collections import Counter
from decimal import Decimal

import pytest

from aeh.conf import ModelRef
from aeh.prov import HttpResponse, JevOpenRouterProvider, RecordedFixtureProvider
from tests.support.conf_builders import hosted_cfg
from tests.support.orch_run import seed_cohort, seed_documents, seed_package
from tests.support.reading_world import (
    ProbingOpenRouter,
    make_class,
    reading_world,
    upload,
    wait_settled,
)

pytestmark = [pytest.mark.integration]

_BLOCKER = "S30 (#872) has not landed"

PANEL = tuple(ModelRef(role="judge", provider="openrouter",
                       build_id=f"openrouter/vendor/judge-{i}@2026-01-01", quantization=None)
              for i in range(3))
#: The same builds under a provider whose retention the OpenRouter account does not manage, so
#: the run-start probe still applies to them (re-based 2026-11-22).
UNMANAGED_PANEL = tuple(ModelRef(role="judge", provider="ollama",
                                 build_id=f"local/vendor/judge-{i}@2026-01-01", quantization=None)
                        for i in range(3))
ESCALATION = [{"role": "judge", "provider": "openrouter",
               "build_id": f"openrouter/vendor/escalation-{k}@2026-01-01"} for k in "ab"]
JEV_BUILD = "openrouter/typesafe/jev-1.13@2026-09-17"
#: What every submission says. A request carrying it is a student byte on the wire.
SENTINEL = "SENTINEL-STUDENT-ANSWER the block slides because friction is lower"


class _ModelEndpoint:
    """The model endpoint: logs every request in the shared event log; refuses every POST with
    401, so a run that does dispatch pauses at once instead of grading."""

    def __init__(self, events: list) -> None:
        self.events = events
        self.requests: list = []

    def send(self, request):  # noqa: ANN001
        self.events.append(("send", request.method, request.url))
        self.requests.append(request)
        if request.method != "POST":
            return HttpResponse(200, {}, b'{"data": []}')
        return HttpResponse(401, {}, b'{"error": {"message": "No auth credentials found"}}')


class _ProbingJev(JevOpenRouterProvider):
    def __init__(self, events: list, unconfirmed: frozenset[str], **kwargs) -> None:
        self.events = events
        super().__init__(api_key="sk-or-test",
                         retention_answers=lambda b: ("retention: standard" if b in unconfirmed
                                                      else "zero-retention"), **kwargs)

    def verify_retention(self, model_refs):  # noqa: ANN001
        self.events.append(("probe", tuple(ref.build_id for ref in model_refs)))
        return super().verify_retention(model_refs)


class _ProbingFixtures(RecordedFixtureProvider):
    def __init__(self, events: list, fixture_dir) -> None:  # noqa: ANN001
        self.events = events
        super().__init__(fixture_dir=fixture_dir)

    def verify_retention(self, model_refs):  # noqa: ANN001
        self.events.append(("probe", tuple(ref.build_id for ref in model_refs)))
        return super().verify_retention(model_refs)


def _world(tmp_data_dir):
    import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.orch, aeh.pkg, aeh.review, aeh.synth  # noqa: F401,E401
    from aeh.store import open_store

    store = open_store(tmp_data_dir)
    cohort = seed_cohort(store, ["S1", "S2"])
    seed_documents(store, ["S1", "S2"], text=SENTINEL)
    version = seed_package(store, [{"criterion_id": "C1", "kind": "open",
                                    "scoring_model": "holistic"}])
    return store, cohort, version


def _flat(document, prefix: str = "") -> dict:
    """A nested record's leaves keyed by their dotted path, so `{"retention_probe": {"cost":
    ...}}` is found as `retention_probe.cost`."""
    if not isinstance(document, dict):
        return {prefix: document}
    leaves: dict = {}
    for key, value in document.items():
        leaves.update(_flat(value, f"{prefix}.{key}" if prefix else str(key)))
    return leaves


def _probed(events: list) -> list[str]:
    return [build for event in events if event[0] == "probe" for build in event[1]]


def _start(store, cohort, version, cfg, provider, **keywords):  # noqa: ANN001
    from aeh.pipeline.background import start_run_in_background

    run_id, thread = start_run_in_background(store, cohort_id=cohort,
                                             package_version_id=version, config=cfg,
                                             provider=provider, **keywords)
    thread.join(timeout=120)
    return run_id


def _live_bound(events: list, unconfirmed: frozenset[str] = frozenset()):
    from aeh.pipeline.runtime import _UnitPricedProvider

    endpoint = _ModelEndpoint(events)
    llm = ProbingOpenRouter(events=events, unconfirmed=unconfirmed, api_key="sk-or-test",
                            base_url="https://openrouter.test/api/v1", transport=endpoint)
    return _UnitPricedProvider(llm), _ProbingJev(events, unconfirmed), endpoint


def _dev_ci_cfg():
    return hosted_cfg("dev-ci", panel=PANEL, HARNESS_DECISION_ENGINE="jev",
                      HARNESS_JEV_BUILD=JEV_BUILD, escalation_judge=ESCALATION)


@pytest.mark.parametrize("knob", [None, "0"], ids=["default", "knob-off"])
def test_tc_prov_71_run_start_probes_no_openrouter_build_and_records_the_account(
        tmp_data_dir, monkeypatch, network_guard, knob):
    """Re-based 2026-11-22 (was "run start probes every distinct build once before any
    request"): an OpenRouter-routed build is never probed, whatever the knob says, and the run
    records retention as the OpenRouter account's — never as verified, and with no probe
    cost."""
    if knob is None:
        monkeypatch.delenv("HARNESS_RETENTION_PRECHECK", raising=False)
    else:
        monkeypatch.setenv("HARNESS_RETENTION_PRECHECK", knob)
    store, cohort, version = _world(tmp_data_dir)
    events: list = []
    bound, jev, endpoint = _live_bound(events)
    try:
        run_id = _start(store, cohort, version, _dev_ci_cfg(), bound, decision_provider=jev)

        wanted = [ref.build_id for ref in PANEL] + [e["build_id"] for e in ESCALATION]
        assert _probed(events) == [], f"an OpenRouter build was probed: {_probed(events)}"

        handle = store.cohort(cohort)
        # `run_metrics` lives in the durable tier (store migration 1), not the cohort's.
        metrics = {row["metric"]: row["value"] for row in store.durable().query(
            "SELECT metric, value FROM run_metrics WHERE run_id = :r", r=run_id)}
        provider_config = json.loads(handle.query(
            "SELECT provider_config FROM run WHERE run_id = :r", r=run_id)[0]["provider_config"])
        assert provider_config["retention"] == "managed by the OpenRouter account"
        assert provider_config["retention_account_managed"] == sorted([*wanted, JEV_BUILD])
        assert "retention_verified" not in provider_config
        assert "retention_exempt" not in provider_config
        # Nothing was probed, so no probe cost is recorded anywhere.
        named = re.compile(r"(retention|probe).*cost|cost.*(retention|probe)")
        figures = {k: v for k, v in {**_flat(provider_config), **metrics}.items()
                   if named.search(k)}
        assert figures == {}, f"a probe cost was recorded though nothing was probed: {figures}"
    finally:
        store.close()


def test_tc_prov_71_an_unconfirmed_openrouter_build_does_not_refuse_the_start(
        tmp_data_dir, monkeypatch, network_guard):
    """Re-based 2026-11-22 (was "a build with no zero-retention host refuses the start naming
    it"): the OpenRouter account manages retention, so an escalation judge whose retention
    source would say "standard" is neither asked nor refused, and the run is created."""
    monkeypatch.delenv("HARNESS_RETENTION_PRECHECK", raising=False)
    store, cohort, version = _world(tmp_data_dir)
    events: list = []
    hedged = ESCALATION[1]["build_id"]
    bound, jev, endpoint = _live_bound(events, unconfirmed=frozenset({hedged}))
    try:
        run_id = _start(store, cohort, version, _dev_ci_cfg(), bound, decision_provider=jev)
        assert store.cohort(cohort).query(
            "SELECT count(*) AS n FROM run WHERE run_id = :r", r=run_id)[0]["n"] == 1
        assert _probed(events) == []
        provider_config = json.loads(store.cohort(cohort).query(
            "SELECT provider_config FROM run WHERE run_id = :r", r=run_id)[0]["provider_config"])
        assert hedged in provider_config["retention_account_managed"]
    finally:
        store.close()


@pytest.mark.parametrize("knob, probes_expected", [(None, True), ("0", False)],
                         ids=["default-on", "knob-off"])
def test_tc_prov_71_the_precheck_knob_turns_the_probe_off_for_the_recorded_tier(
        tmp_data_dir, tmp_path, monkeypatch, network_guard, knob, probes_expected):
    if knob is None:
        monkeypatch.delenv("HARNESS_RETENTION_PRECHECK", raising=False)
    else:
        monkeypatch.setenv("HARNESS_RETENTION_PRECHECK", knob)
    store, cohort, version = _world(tmp_data_dir)
    events: list = []
    fixtures = tmp_path / "recordings"
    fixtures.mkdir()
    try:
        # Re-based 2026-11-22: the knob only reaches a build the OpenRouter account does not
        # manage, so the panel is named under a local provider here.
        run_id = _start(store, cohort, version, hosted_cfg("dev-ci", panel=UNMANAGED_PANEL),
                        _ProbingFixtures(events, fixtures))
        assert store.cohort(cohort).query(
            "SELECT count(*) AS n FROM run WHERE run_id = :r", r=run_id)[0]["n"] == 1
        if probes_expected:
            census = Counter(_probed(events))
            assert all(census[ref.build_id] == 1 for ref in UNMANAGED_PANEL), (
                f"FR-PROV-48: the recorded tier on dev-ci probes by default ({_BLOCKER}); "
                f"probed: {dict(census)}")
            assert max(census.values()) == 1, f"a build was probed twice: {dict(census)}"
        else:
            assert _probed(events) == [], "HARNESS_RETENTION_PRECHECK=0 still probed"
    finally:
        store.close()


@pytest.fixture
def reading(tmp_data_dir, monkeypatch, capsys, network_guard):
    yield from reading_world(tmp_data_dir, monkeypatch, capsys, network_guard)


def test_tc_prov_71_the_reading_job_does_not_probe_an_openrouter_transcriber(reading):
    """Re-based 2026-11-22 (was "the reading job probes the transcriber before the first page"):
    the OpenRouter page reader's retention is the account's, so it is not probed, and the job
    still reads the paper."""
    port, version, events = reading["port"], reading["version"], reading["events"]
    make_class(port, reading["roster"])
    status, answer = upload(port, reading["paper"], cohort_id="ps9-class",
                            package_version=version, kind="assessment",
                            filename="01-test-paper.pdf")
    assert status == 200 and answer["dispatched"] is True, answer
    record = wait_settled(port, answer["job_id"])
    assert record["state"] == "succeeded", record

    census = Counter(_probed(events))
    transcriber = reading["transcriber_build"]
    assert census[transcriber] == 0, f"the OpenRouter page reader was probed: {dict(census)}"
    assert any(e[:2] == ("send", "POST") for e in events), "no page was read"
