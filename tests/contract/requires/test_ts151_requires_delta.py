"""TS-151 (#640): design 1.10-delta §3's new `Requires` rows, one pairwise case each against the
real provider.

| Case | Pair | Assertion |
|---|---|---|
| TC-REQ-130 | M-HELP → M-PROV | the Q&A request crosses the provider seam — exactly one egress per answer, through the recorded transport, with no credential in the assembled payload |
| TC-REQ-131 | M-HELP → M-CONF | the model the QA call names is `provider_config.qa_model` as M-CONF resolved it; on `edge-local` it is the panel's first seat |
| TC-REQ-132 | M-JUDGE/M-ORCH → M-PKG | through the real enumerator, a composite package dispatches exactly its aspect criteria — the composite is never a unit, so nothing dispatches it |
| TC-REQ-133 | M-SETUP → M-PKG | every package the confirmed setup flow publishes satisfies `CT-PKG-21` (the stored-row checker), over 30 seeded setup flows, one `general` and one `evidence_sum` criterion each |

The QA cases are the same rung-2 rig the TS-150 cases drive (`tests/support/help_vocabulary.py`:
the recorded QA double behind `RecordedFixtureProvider`, the only egress point). The composition
case is the same `F-RUBRIC-METHODS` world the TS-146 cases seed (`tests/support/composition_world.py`),
driven one step further than `TC-JUDGE-45`'s enumeration pin: the score stage actually runs through
the real lease → assemble → dispatch → persist → complete cycle, with a counting provider at the
boundary. The setup case reuses `tests/support/setup_rubric_methods.py`'s flow and
`tests/support/rubric_methods.py`'s stored-row checker.

Marker state (test plan §8.2): all four run unmarked. 132's blockers (#626, #622) and 133's
blocker (#624) landed with their stories, green since. 130 and 131 were written ahead of #636
(`M-HELP`); #636 landed before this story finished, the two cases were re-checked green against
the landed assistant unmarked, and the markers were dropped with them — no
`WRITTEN_AHEAD_BLOCKERS` entry ever stood (the file was registered only for the marker the
SPA-side cases carry; those wait on #635/#638 and are keyed in the SPA file).

Isolation: rung 2 — real store, real modules, `RecordedFixtureProvider` (or its QA double) at the
model boundary; no network (`network_guard`).
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.conf import CohortRef, ModelRef, effective_config, resolve_run_config
from aeh.orch import STAGE_EXTRACT, STAGE_SCORE
from aeh.store import open_store
from tests.support import help_vocabulary as hv
from tests.support import rubric_methods as rm
from tests.support import setup_rubric_methods as sm
from tests.support.composition_world import (
    ASPECTS,
    COMPOSITE,
    JUDGED,
    seed_rubric_run,
    work_units,
)
from tests.support.conf_builders import (
    EDGE_PANEL_3,
    HOSTED_JUDGE,
    HOSTED_PANEL_3,
    edge_cfg,
    hosted_cfg,
    seed_credentials,
)
from tests.support.extract_vocabulary import (
    extractor_ref,
    sampling_params,
    span_completion,
    verdict_completion,
)
from tests.support.judge_run import verdict_rows, warm_judged_modules, work_unit_row

EXTRACT_WORKER = "w-extract-ts151"
SCORE_WORKER = "w-judge-ts151"
PANEL = 3


# --- TC-REQ-130 -------------------------------------------------------------------------------


@pytest.mark.integration
def test_tc_req_130_the_qa_request_crosses_the_recorded_provider_seam_and_leaks_no_credential(
    tmp_path, tmp_data_dir, network_guard, monkeypatch
):
    """`TC-REQ-130` / M-HELP→M-PROV (P0) — one ask over the rung-2 rig: the assistant makes
    exactly ONE provider call (one egress per answer), its completion is the recorded
    transport's replay of the declared transcript (the bytes are the double's, not a live
    model's), the socket guard saw no attempt beyond loopback, and no credential reached the
    assembled payload."""
    credential = seed_credentials(monkeypatch)
    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec", model_ref=HOSTED_JUDGE)
    problems: list[str] = []
    try:
        result = rig.assistant.ask(hv.GROUNDED_T.question)
        if len(rig.double.calls) != 1:
            problems.append(
                f"{len(rig.double.calls)} provider calls for one answer — the QA call crosses "
                "the provider seam exactly once per answer (CT-PROV-10, the recorded transport)")
        if rig.double.calls:
            call = rig.double.calls[0]
            if hv.profile_of(call.model_ref) != hv.profile_of(HOSTED_JUDGE):
                problems.append(
                    f"the QA call used profile {hv.profile_of(call.model_ref)}, not the "
                    f"configured {hv.profile_of(HOSTED_JUDGE)}")
            replayed = hv.norm(call.completion.text)
            if replayed != hv.norm(hv.GROUNDED_T.reply):
                problems.append(
                    f"the completion is not the recorded transport's replay: "
                    f"{call.completion.text!r} != {hv.GROUNDED_T.reply!r}")
        if hv.norm(hv.answer_text(result)) != hv.norm(hv.GROUNDED_T.reply):
            problems.append(
                f"the answer rendered is not the recorded replay: {hv.answer_text(result)!r} != "
                f"{hv.GROUNDED_T.reply!r}")
        for text in rig.double.payloads():
            if credential in text:
                problems.append(
                    "the OPENROUTER credential reached the assembled payload (CT-PROV-13: no "
                    "credential in what crosses the seam)")
    finally:
        rig.store.close()
    network_guard.assert_no_network()
    assert not problems, "\n\n".join(problems)


# --- TC-REQ-131 -------------------------------------------------------------------------------

QA_OVERRIDE = "vendor/qa-model-a@2026-09-01"
QA_COHORT = CohortRef("c-ts151-qa", "synthetic")


def _resolved_qa(cfg: dict[str, Any], environ: Mapping[str, str]) -> Any:
    config = resolve_run_config(effective_config(cfg, environ=environ), QA_COHORT)
    provider_config = config.to_persisted_dict()["provider_config"]
    assert "qa_model" in provider_config, (
        "precondition: the resolved Q&A model is on provider_config (CT-CONF-22)")
    qa = provider_config["qa_model"]
    assert isinstance(qa, Mapping), qa
    return qa


def _qa_ref(qa: Mapping[str, Any]) -> Any:
    return ModelRef(role=str(qa.get("role") or "judge"), provider=str(qa["provider"]),
                    build_id=str(qa["build_id"]), quantization=str(qa.get("quantization")))


@pytest.mark.integration
@pytest.mark.parametrize("arm", ["cloud-hosted override", "edge-local"])
def test_tc_req_131_the_qa_call_names_the_configured_qa_model(tmp_path, tmp_data_dir, arm):
    """`TC-REQ-131` / M-HELP→M-CONF (P0) — the QA assistant is built on the model M-CONF
    resolved (`provider_config.qa_model`, read back through the persisted dict), and the call
    the assistant makes names exactly that model. On `edge-local` the resolved value is the
    panel's first seat; there is no knob, so the assistant cannot have been built on anything
    else."""
    if arm == "cloud-hosted override":
        qa = _resolved_qa(hosted_cfg(panel=HOSTED_PANEL_3, HARNESS_DECISION_ENGINE="off"),
                          {"HARNESS_QA_MODEL": QA_OVERRIDE})
    else:
        qa = _resolved_qa(edge_cfg(panel=EDGE_PANEL_3, HARNESS_DECISION_ENGINE="off"), {})
        first = EDGE_PANEL_3[0]
        assert (str(qa["provider"]), str(qa["build_id"])) == (first.provider, first.build_id), (
            f"precondition: edge-local's resolved Q&A model is the panel's first seat, got "
            f"{qa['provider']}:{qa['build_id']}")
    ref = _qa_ref(qa)
    rig = hv.build_rig(tmp_data_dir, tmp_path / "rec", model_ref=ref)
    try:
        rig.assistant.ask(hv.GROUNDED_T.question)
        assert rig.double.calls, "no QA call was made — nothing names a model"
        call = rig.double.calls[0]
        assert (call.model_ref.provider, call.model_ref.build_id) == (ref.provider, ref.build_id), (
            f"the QA call named {call.model_ref.provider}:{call.model_ref.build_id}, not the "
            f"resolved qa_model {ref.provider}:{ref.build_id} (M-HELP→M-CONF)")
    finally:
        rig.store.close()


# --- TC-REQ-132 -------------------------------------------------------------------------------

SUBMISSIONS = ("s-151-a", "s-151-b")


def _top_band_name(shape: Any, criterion_id: str) -> str:
    """The declared band a valid judge reply names: the top band of the criterion's set."""
    criterion = next(c for c in shape.criteria if c.criterion_id == criterion_id)
    return max(criterion.bands, key=lambda band: band.points).band


class _CallsByUnit:
    """The model boundary, counting every `complete` per work unit being dispatched."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.current: str | None = None
        self.calls: dict[str, int] = {}

    def complete(self, payload: Any, model_ref: Any, params: Any) -> Any:
        self.calls[self.current] = self.calls.get(self.current, 0) + 1
        return self._inner.complete(payload, model_ref, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@pytest.mark.integration
def test_tc_req_132_a_composite_package_dispatches_exactly_its_aspect_criteria(
    tmp_data_dir, make_fixture_provider, monkeypatch
):
    """`TC-REQ-132` / M-JUDGE/M-ORCH→M-PKG (P0) — the F-RUBRIC-METHODS composite package, run
    through the REAL enumerator and then the real score stage: extraction completes for every
    judged line, the lease hands out exactly the aspect-criteria score units, and every
    dispatch that actually reaches the provider names an aspect criterion (or the standalone
    `bands`/`general` lines) — the composite is never a unit and never reaches a judge."""
    monkeypatch.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", "0")
    warm = warm_judged_modules()
    ExtractAssemble, ExtractWorker = warm["extract"]
    ExtractPromptFields = warm["extract_prompt_fields"]
    from aeh.judge import ScoringWorker, prompt_fields  # deferred: the seam import

    store = open_store(tmp_data_dir)
    counting: _CallsByUnit | None = None
    try:
        world = seed_rubric_run(store, rm.rubric_methods("TS151-DISPATCH"), SUBMISSIONS, panel=PANEL)
        provider = make_fixture_provider()

        # FR-ORCH-06: score units are held behind their extract siblings — complete extraction.
        for _pass in range(4):
            batch = list(world.orchestrator.lease(EXTRACT_WORKER, STAGE_EXTRACT, 64))
            if not batch:
                break
            for unit in batch:
                request = ExtractAssemble(unit, store=store)
                provider.record(
                    ExtractPromptFields(request), extractor_ref(), sampling_params(),
                    span_completion(world.spans[unit.submission_id], build_id="extractor-ts151"))
                ExtractWorker(store, provider, extractor_ref()).process(unit)

        units = work_units(world)
        extract_units = [r for r in units if r["stage"] == STAGE_EXTRACT]
        assert len(extract_units) == len(SUBMISSIONS) * len(JUDGED), (
            f"precondition: extraction ran for every judged line — {len(extract_units)} extract "
            f"units for {len(SUBMISSIONS)} x {len(JUDGED)} expected")
        stuck = [(r["criterion_id"], r["status"]) for r in extract_units if r["status"] != "done"]
        assert not stuck, f"precondition: extraction did not complete: {stuck}"

        # The real score stage: lease, assemble, dispatch, persist, complete — through a
        # counting boundary.
        counting = _CallsByUnit(provider)
        judges = {ref.build_id: ref for ref in _edge_panel()}
        dispatched: dict[str, int] = {}
        passes = 0
        while True:
            # The run is edge-local (conf_builders' panel), so FR-ORCH-19's residency gate
            # keeps ONE judge claimable at a time: draining the stage takes one lease pass
            # per judge, each seen only after the previous judge's units are complete.
            batch = list(world.orchestrator.lease(SCORE_WORKER, STAGE_SCORE, 64))
            if not batch:
                break
            passes += 1
            if passes > 40:
                pytest.fail("the score stage did not drain within 40 lease passes — a unit "
                            "is stuck pending (see the still_open check below)")
            for unit in batch:
                assert unit.criterion_id != COMPOSITE, (
                    f"the enumerator handed the score stage a composite unit {unit.work_id!r} "
                    "(FR-JUDGE-38)")
                counting.current = unit.work_id
                ref = judges[unit.judge]
                worker = ScoringWorker(store, counting, ref)
                request = worker.assemble(unit)
                provider.record(
                    prompt_fields(request), ref, sampling_params(),
                    verdict_completion(_top_band_name(world.shape, unit.criterion_id), 0.9,
                                       build_id="judge-ts151",
                                       cited_spans=list(world.spans[unit.submission_id])))
                result = worker.dispatch(request, ref)
                worker.persist(unit, result)
                world.orchestrator.complete(unit.work_id)
                dispatched[unit.criterion_id] = dispatched.get(unit.criterion_id, 0) + 1

        assert set(dispatched) == set(JUDGED), (
            f"the composite package dispatched {sorted(dispatched)}, not exactly its judged "
            f"criteria {sorted(JUDGED)} — M-JUDGE→M-PKG")
        expected_per_criterion = len(SUBMISSIONS) * PANEL
        wrong = {c: n for c, n in dispatched.items() if n != expected_per_criterion}
        assert not wrong, (
            f"per-criterion dispatch counts {wrong} are not {expected_per_criterion} "
            f"(panel depth x submissions): the real enumerator's aspect dispatch is not exact")
        assert counting.calls and all(n == 1 for n in counting.calls.values()), (
            f"a dispatch reached the provider more than once: {counting.calls}")
        still_open = [(r["criterion_id"], r["status"]) for r in work_units(world)
                      if r["stage"] == STAGE_SCORE and r["status"] != "done"]
        assert not still_open, f"score units left undriven: {still_open}"
        for row in work_units(world):
            if row["stage"] == STAGE_SCORE:
                assert verdict_rows(store, row["work_id"]), (
                    f"no verdict row for the dispatched {row['criterion_id']} unit "
                    f"{row['work_id']}")
    finally:
        store.close()


def _edge_panel() -> tuple[Any, ...]:
    from tests.support.conf_builders import edge_panel

    return edge_panel(PANEL)


# --- TC-REQ-133 -------------------------------------------------------------------------------


def _seeded_inputs(seed: int) -> tuple[tuple[dict[str, Any], ...], list[dict[str, Any]]]:
    """The seeded setup flow's teacher inputs: the confirmed `general` derivation (a band
    set must have an even count, at least 2 and at most 6 — FR-PKG-06 — so the derivation is
    `DERIVED_BANDS`, 4 bands) and an evidence-sum aspect layout (2 or 3 aspects, integer
    points summing to Q2's five marks, every aspect >= 1). Numeral-free by construction."""
    rng = random.Random(seed)
    count = 2 + (seed % 2)
    cuts = sorted(rng.sample(range(1, 5), count - 1))
    points = [float(b - a) for a, b in zip((0, *cuts), (*cuts, 5))]
    names = ("details", "structure", "conclusion")
    aspects = [{"name": names[index], "points": points[index]} for index in range(count)]
    return sm.DERIVED_BANDS, aspects


@pytest.mark.integration
@pytest.mark.parametrize("seed", range(30))
def test_tc_req_133_every_published_setup_flow_package_satisfies_ct_pkg_21(tmp_data_dir, seed):
    """`TC-REQ-133` / M-SETUP→M-PKG (P1) — a seeded setup flow (confirmed inventory, keys, one
    derived-and-confirmed `general` criterion, one built-and-confirmed `evidence_sum`
    composite over 2–3 aspects, varied by seed) publishes, and the stored rows satisfy
    CT-PKG-21 exactly (`shape_violations` over the raw `.pkg.sqlite` — the same checker
    TS-144's clause suite holds). Each published package carries one `general` criterion
    (the 4-band `DERIVED_BANDS` derivation) and one composite whose aspects are the
    two-band criteria the builder generated."""
    chain = sm.confirmed_chain(tmp_data_dir)
    try:
        bands, aspects = _seeded_inputs(seed)
        sm.derive(chain, sm.GENERAL, replies=[sm.derivation_reply(sm.GENERAL, bands)])
        sm.confirm_general(chain, sm.GENERAL)
        sm.build_sum(chain, sm.COMPOSITE, aspects)
        sm.confirm_sum(chain, sm.COMPOSITE)
        version = chain.service.publish(sm.TEACHER)

        path = chain.store.package_path(chain.package_id)
        problems: list[str] = []
        if rm.locked_versions(path) != [version]:
            problems.append(f"precondition: the published version is not the locked one: "
                            f"{rm.locked_versions(path)}")
        problems += [f"CT-PKG-21: {v}" for v in rm.shape_violations(path, version)]

        crit = rm.criteria_rows(path, version)
        generals = [c for c, row in crit.items() if row.get("score_method") == "general"]
        composites = [c for c, row in crit.items() if row.get("score_method") == "evidence_sum"]
        if generals != [sm.GENERAL]:
            problems.append(f"the flow's one `general` criterion: {generals} != [{sm.GENERAL}]")
        if composites != [sm.COMPOSITE]:
            problems.append(f"the flow's one composite: {composites} != [{sm.COMPOSITE}]")
        stored = rm.bands_by_criterion(path, version)
        if generals and not stored.get(sm.GENERAL):
            problems.append(f"{sm.GENERAL} published with no band set")
        elif generals and sm.comparable(bands) != sm.comparable(stored[sm.GENERAL]):
            problems.append(f"{sm.GENERAL}'s stored bands are not the confirmed derivation: "
                            f"{sm.comparable(stored[sm.GENERAL])}")
        aspect_ids = [c for c, row in crit.items() if row.get("component_of") == sm.COMPOSITE]
        if len(aspect_ids) != len(aspects):
            problems.append(f"the composite carries {len(aspect_ids)} aspect(s), "
                            f"not the {len(aspects)} the builder generated")
        for aspect_id in aspect_ids:
            if len(stored.get(aspect_id, [])) != 2:
                problems.append(f"aspect {aspect_id} is not a 2-band criterion: "
                                f"{len(stored.get(aspect_id, []))} band(s)")
        assert not problems, f"seed {seed}:\n  " + "\n  ".join(problems)
    finally:
        chain.store.close()
