"""`TC-PROV-71` — retention checked before anything is sent (FR-PROV-48, CT-PROV-09; RSV-33).

Statistical-validity test plan r2 §3.23, story T21 (issue #905). Written ahead of S30 (#872),
which has landed: the `writtenahead` marker and its blocker entry are gone.

SV-33: zero retention was verified only for the decision engine before dispatch and for the
panel at the first call, and only on `cloud-hosted`. FR-PROV-48 widens FR-PROV-14 to every
remote profile: on `dev-ci` too, run start and the reading job call `verify_retention` for every
build they will dispatch to — panel, escalation judges, decision engine; the transcriber for the
reading job — and refuse before the first student byte leaves, naming the model.
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


@pytest.mark.parametrize("knob", [None, "0"], ids=["default", "knob-off-still-probes-live"])
def test_tc_prov_71_run_start_probes_every_distinct_build_once_before_any_request(
        tmp_data_dir, monkeypatch, network_guard, knob):
    """`HARNESS_RETENTION_PRECHECK=0` is for the recorded tier only: on the live provider the
    census is the same with it set (a knob that silenced the check on live traffic is the
    dangerous mutation)."""
    if knob is None:
        monkeypatch.delenv("HARNESS_RETENTION_PRECHECK", raising=False)
    else:
        monkeypatch.setenv("HARNESS_RETENTION_PRECHECK", knob)
    store, cohort, version = _world(tmp_data_dir)
    events: list = []
    bound, jev, endpoint = _live_bound(events)
    try:
        run_id = _start(store, cohort, version, _dev_ci_cfg(), bound, decision_provider=jev)

        wanted = [ref.build_id for ref in PANEL] + [e["build_id"] for e in ESCALATION] + [JEV_BUILD]
        census = Counter(_probed(events))
        assert all(census[build] == 1 for build in wanted), (
            f"FR-PROV-48: run start on dev-ci must call verify_retention once per distinct "
            f"build (panel, escalation judges, decision engine) ({_BLOCKER}); probed: "
            f"{dict(census)}")
        assert max(census.values()) == 1, f"a build was probed twice: {dict(census)}"
        probes = [i for i, event in enumerate(events) if event[0] == "probe"]
        posts = [i for i, event in enumerate(events) if event[:2] == ("send", "POST")]
        assert not posts or max(probes) < min(posts), (
            "a request reached the model endpoint before every build was verified")

        # The probe's cost appears on the run.
        handle = store.cohort(cohort)
        # `run_metrics` lives in the durable tier (store migration 1), not the cohort's.
        metrics = {row["metric"]: row["value"] for row in store.durable().query(
            "SELECT metric, value FROM run_metrics WHERE run_id = :r", r=run_id)}
        provider_config = json.loads(handle.query(
            "SELECT provider_config FROM run WHERE run_id = :r", r=run_id)[0]["provider_config"])
        named = re.compile(r"(retention|probe).*cost|cost.*(retention|probe)")
        figures = {k: v for k, v in {**_flat(provider_config), **metrics}.items()
                   if named.search(k)}
        assert figures, (f"FR-PROV-48: the retention probe's cost is not on the run; "
                         f"metrics {sorted(metrics)}, provider_config {sorted(provider_config)}")
        assert all(v is not None and Decimal(str(v)) >= 0 for v in figures.values()), (
            f"the probe's cost is recorded without a figure: {figures}")
    finally:
        store.close()


def test_tc_prov_71_a_build_with_no_zero_retention_host_refuses_the_start_naming_it(
        tmp_data_dir, monkeypatch, network_guard):
    monkeypatch.delenv("HARNESS_RETENTION_PRECHECK", raising=False)
    store, cohort, version = _world(tmp_data_dir)
    events: list = []
    hedged = ESCALATION[1]["build_id"]
    bound, jev, endpoint = _live_bound(events, unconfirmed=frozenset({hedged}))
    try:
        try:
            _start(store, cohort, version, _dev_ci_cfg(), bound, decision_provider=jev)
        except Exception as error:  # noqa: BLE001 - the refusal's type is the gate's to choose
            refusal = str(error)
        else:
            raise AssertionError(
                f"FR-PROV-48: a dev-ci start with an escalation judge that has no "
                f"zero-retention host was not refused ({_BLOCKER})")
        assert hedged in refusal or "escalation-b" in refusal, (
            f"the refusal does not name the model: {refusal}")
        assert store.cohort(cohort).query("SELECT count(*) AS n FROM run")[0]["n"] == 0
        assert [r for r in endpoint.requests if r.method == "POST"] == []
        assert not [r for r in endpoint.requests if SENTINEL.encode() in (r.body or b"")], (
            "a request carrying student text left before the refusal")
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
        run_id = _start(store, cohort, version, hosted_cfg("dev-ci", panel=PANEL),
                        _ProbingFixtures(events, fixtures))
        assert store.cohort(cohort).query(
            "SELECT count(*) AS n FROM run WHERE run_id = :r", r=run_id)[0]["n"] == 1
        if probes_expected:
            census = Counter(_probed(events))
            assert all(census[ref.build_id] == 1 for ref in PANEL), (
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


def test_tc_prov_71_the_reading_job_probes_the_transcriber_before_the_first_page(reading):
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
    assert census[transcriber] == 1, (
        f"FR-PROV-48: the reading job on dev-ci must verify the transcriber's retention once "
        f"before reading ({_BLOCKER}); probed: {dict(census)}")
    first_probe = next(i for i, e in enumerate(events) if e[0] == "probe" and transcriber in e[1])
    first_post = next(i for i, e in enumerate(events) if e[:2] == ("send", "POST"))
    assert first_probe < first_post, "a page left before the transcriber was verified"
