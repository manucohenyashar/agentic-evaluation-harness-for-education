"""`TC-JUDGE-C13` — the prefix share is a threshold, and the output cap rides the
knob (§6.11.10).

`CT-JUDGE-13` (perf): *"Assert roughly **1,500 of ~1,800** input tokens per call
are shared prefix, as a threshold on the ratio rather than on latency — because the
clause's warning is that a prompt change lowering it is a **performance regression
even when every test passes**. Assert output is bounded by `JUDGE_MAX_OUTPUT_TOKENS`
(400). This case is the standing detector for RISK-23: without it, losing prefix
share costs 5× wall clock and surfaces only as a run that missed the morning. A
loosened bound must edit this ratio in review."* (plan §6.11.10, verbatim)

Two cases carry it:

1. **the prefix-share threshold** — over a real driven batch at the dispatch
   boundary, every `ScoringResult` carries the stage-level observable the module
   discloses for this clause: the invariant prefix's byte share of the payload
   (`prefix_bytes` / `total_bytes` — the byte split is the transport-neutral form
   of the plan's token ratio, disclosed: the plan's 1,500 of ~1,800 is a tokenizer
   count and the tokenizer is the provider's; the fast tier's threshold is the
   plan's ratio 0.833 carried in bytes at **0.8**, and loosening it further must
   edit this constant in review, per RISK-33). The threshold's sensitivity is
   proven, not assumed: a regressed render — the per-submission material swollen
   until it dominates the payload — drives the same formula BELOW the bound, so
   the comparison can fire on the failure the clause warns about;
2. **the output cap rides the knob** — `HARNESS_JUDGE_MAX_OUTPUT_TOKENS` (the
   plan's `JUDGE_MAX_OUTPUT_TOKENS`) read at call time: set to 400, the boundary's
   recorded `SamplingParams` carry `max_tokens == 400` on the wire; UNSET, the
   parameters carry **no** cap at all (`None`) — the module ships no default cap of
   its own (the production 400 is the environment's value, the knob exists so a
   slower box can move it without a code change, and the unset-default divergence
   from the plan's exact number is disclosed here).

Cross-references, not duplicates: `TC-JUDGE-C08` holds the byte-identity
differential the ratio PRESUMES (the prefix can only be shared if it is
byte-identical — RISK-23's precondition limb); `TC-JUDGE-21`'s security suite owns
the LIVE token-share threshold at the plan's stated load, never executed in the
fast tier. This file is the threshold the gate runs: the byte form of the same
invariant, over the results the workers actually returned.

Isolation: rung 2 — real store, real workers, a transport double at the model
boundary (the call COUNT is the oracle, and the fixture key's replay collapses
counts by construction); the socket guard is autouse.
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.orch import STAGE_SCORE
from aeh.store import open_store
from tests.contract.judge._drive import (
    PANEL_REFS,
    RecordingTransport,
    drive_extract,
    offline_request,
    seed_world,
    spans,
)
from tests.support.extract_vocabulary import sampling_params, verdict_completion
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_vocabulary import fields_of

pytestmark = [pytest.mark.contract]

#: The story that owns the observable (`M-JUDGE` is complete — #78/#79/#80/#81).
ISSUE = "#78"

#: The output cap's knob (`aeh.judge`'s `MAX_OUTPUT_TOKENS_ENV`) — the plan's
#: `JUDGE_MAX_OUTPUT_TOKENS`.
MAX_OUTPUT_TOKENS_ENV = "HARNESS_JUDGE_MAX_OUTPUT_TOKENS"

#: The plan's exact production cap (`TC-JUDGE-C13`: "bounded by
#: `JUDGE_MAX_OUTPUT_TOKENS` (400)").
PLAN_CAP = 400

#: The prefix-share bound, in bytes. The plan's own ratio is 1,500 / ~1,800 ≈
#: 0.833 (tokens); `aeh.judge` surfaces the SAME invariant as a byte split (its
#: docstring: the tokenizer is the provider's, the byte split is the
#: transport-neutral form), so the fast tier's threshold is that ratio carried
#: into the byte domain at 0.8 — the disclosed conversion, NOT a loosening: a
#: regressed render must edit this constant in review (RISK-33).
_PREFIX_SHARE = 0.8

_SUBMISSIONS = ("SYN-001", "SYN-002", "SYN-003")

_JUDGE_BUILD = "build-judge-contract"

#: The rubric weight the plan's numbers presume: the production render carries a
#: full criterion definition, question, reference solution and exemplar set in the
#: invariant prefix (~1,500 tokens of ~1,800). The fixture's bare criterion is
#: lighter than production, so the threshold drive seeds a production-weight
#: exemplar set through the shipped catalog door — the exemplars are prefix
#: material BY DEFINITION (CT-JUDGE-08's list), so this is the production shape,
#: not a padded fixture.
_EXEMPLAR_MATERIALS: tuple[str, ...] = (
    "names the static friction balance explicitly and points to where the "
    "along-slope pull appears in the cited report's diagram",
    "shows the free-body diagram with the normal force drawn perpendicular to "
    "the contact surface, and labels every force it introduces",
    "derives the along-slope component step by step, keeping the angle as a "
    "named symbol until the final line substitutes the measured value",
    "discusses the measurement uncertainty honestly and lets the conclusion "
    "stay qualified where the data cannot carry more",
    "states the conclusion with the caveats attached and marks which claim "
    "each caveat weakens",
    "connects the answer to the passage's opening paragraph and quotes the "
    "sentence the support comes from",
    "explains why the crate holds in the limiting case before the pull grows "
    "past the maximum static value",
    "keeps the algebra readable, one balance per line, and defines each "
    "symbol the first time it appears",
    "answers the question asked, rather than the neighboring question the "
    "passage also raises, and says so explicitly",
    "closes with a check: the derived acceleration is compared against the "
    "report's observed figure and the difference is accounted for",
)


def _byte_share(fields: list[tuple[str, str]]) -> float:
    """The module's own observable, over any field list: the invariant prefix's
    byte share of the whole payload (`ScoringResult.prefix_bytes` /
    `total_bytes`, computed over `value.encode("utf-8")`)."""
    prefix = sum(len(value.encode("utf-8")) for _name, value in fields[:-1])
    total = sum(len(value.encode("utf-8")) for _name, value in fields)
    return prefix / total if total else 0.0


def test_tc_judge_c13_the_invariant_prefix_is_the_payloads_overwhelming_share(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C13` case 1 (`CT-JUDGE-13`, the threshold on the ratio, rung 2,
    P0) — every result the judged drive returns carries a prefix share at or above
    the bound, and the sensitivity control proves the bound would catch a payload
    the other way round: the detector can fire."""
    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        orchestrator, _run_id, version = seed_world(
            store, submissions=_SUBMISSIONS
        )
        # The production-weight prefix: exemplars ride the version through the
        # shipped catalog door (blob first, then the row).
        from aeh.pkg import PackageCatalog

        catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
        for index, material in enumerate(_EXEMPLAR_MATERIALS):
            blob_hash = store.blobs().put(
                f"{material} (worked example, item {index + 1} of "
                f"{len(_EXEMPLAR_MATERIALS)}).".encode("utf-8")
            )
            catalog.add_exemplar(version, f"ex-C13-{index}", "C1", "secure",
                                 blob_hash=blob_hash)
        drive_extract(orchestrator, store, provider)
        units = []
        for _ in range(8):
            batch = orchestrator.lease("w-c13", STAGE_SCORE, 8)
            if not batch:
                break
            units.extend(batch)
        assert len(units) == len(_SUBMISSIONS), (
            f"fixture bug: the drive leased {len(units)} unit(s) — the threshold "
            "is over the batch the workers actually judged"
        )
        refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
        results = []
        for unit in units:
            judge_ref = refs_by_build[unit.judge]
            worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
                store, provider, judge_ref
            )
            request = worker.assemble(unit)
            provider.record(
                require(JUDGE_MODULE, "prompt_fields", issue=ISSUE)(request),
                judge_ref,
                sampling_params(),
                verdict_completion("secure", 0.9, build_id=_JUDGE_BUILD,
                                   cited_spans=spans()),
            )
            result = worker.dispatch(request, judge_ref)
            worker.persist(unit, result)
            results.append(result)

        # The threshold: every result's prefix share at or above the bound.
        for result in results:
            share = result.prefix_bytes / result.total_bytes
            assert share >= _PREFIX_SHARE, (
                f"{result.work_id[:12]}: the invariant prefix is "
                f"{result.prefix_bytes} of {result.total_bytes} bytes "
                f"(share {share:.3f}) — below the {int(_PREFIX_SHARE * 100)}% "
                "bound: a prompt change that moved per-submission material into "
                "the prefix is a performance regression even when every test "
                "passes (CT-JUDGE-13, RISK-23; the loosening must be edited here "
                "in review, per RISK-33)"
            )

        # The threshold's sensitivity: the same formula over a regressed payload
        # — the per-submission material swollen until it dominates — MUST fall
        # below the bound, or the threshold above could never fire on the
        # regression the clause warns about.
        regressed = offline_request(
            submission_text="the submission's own words, at length. " * 400,
        )
        rendered = fields_of(require(JUDGE_MODULE, "prompt_fields", issue=ISSUE),
                             regressed)
        regressed_share = _byte_share(rendered)
        assert regressed_share < _PREFIX_SHARE, (
            f"fixture bug: the regressed control's share is {regressed_share:.3f} "
            "— the bound below cannot fire on it, so the threshold would be "
            "vacuous"
        )
        # And the REAL results sit far above the regressed control — the
        # differential is the share, not the payload's size.
        live_share = results[0].prefix_bytes / results[0].total_bytes
        assert live_share > regressed_share + 0.4, (
            f"the live share ({live_share:.3f}) is not meaningfully above the "
            f"regressed control's ({regressed_share:.3f}) — the threshold's "
            "margin has collapsed (CT-JUDGE-13)"
        )
    finally:
        store.close()


def test_tc_judge_c13_the_output_cap_rides_the_knob(tmp_data_dir,
                                                    make_fixture_provider,
                                                    monkeypatch):
    """`TC-JUDGE-C13` case 2 (`CT-JUDGE-13`, the exact output bound, rung 2, P0) —
    the cap is read at call time from the environment: set to the plan's 400, the
    boundary's recorded parameters carry it on the wire; unset, no cap rides at
    all — the module ships no default of its own (the disclosed divergence)."""
    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        orchestrator, _run_id, _version = seed_world(store)
        drive_extract(orchestrator, store, provider)
        batch = orchestrator.lease("w-c13", STAGE_SCORE, 8)
        assert batch, "fixture bug: no score unit leased for the knob drive"
        unit = batch[0]
        refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
        judge_ref = refs_by_build[unit.judge]
        request = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, None, judge_ref
        ).assemble(unit)

        # Set to the plan's production value: the cap rides the wire.
        monkeypatch.setenv(MAX_OUTPUT_TOKENS_ENV, str(PLAN_CAP))
        transport = RecordingTransport(verdict_completion(
            "secure", 0.9, build_id=_JUDGE_BUILD, cited_spans=spans(),
        ))
        worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, transport, judge_ref
        )
        result = worker.dispatch(request, judge_ref)
        assert result.band == "secure", (
            "precondition: the knob drive's reply was refused"
        )
        sent = transport.params()[0]
        assert sent.max_tokens == PLAN_CAP, (
            f"the boundary was sent max_tokens={sent.max_tokens!r} under "
            f"{MAX_OUTPUT_TOKENS_ENV}={PLAN_CAP} — the output cap must ride the "
            "knob verbatim (CT-JUDGE-13): an env-calibrated constant that does "
            "not reach the wire is a phantom knob (CLAUDE.md seam 3)"
        )
        assert sent.temperature == 0.0, (
            f"the capped drive was sent temperature={sent.temperature!r} — "
            "judgment stays a temperature-zero task beside the cap "
            "(CT-JUDGE-13, FR-JUDGE-13)"
        )

        # Unset: the cap rides NOWHERE — the module's default is no cap at all.
        monkeypatch.delenv(MAX_OUTPUT_TOKENS_ENV, raising=False)
        transport = RecordingTransport(verdict_completion(
            "secure", 0.9, build_id=_JUDGE_BUILD, cited_spans=spans(),
        ))
        worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, transport, judge_ref
        )
        worker.dispatch(request, judge_ref)
        sent = transport.params()[0]
        assert sent.max_tokens is None, (
            f"with {MAX_OUTPUT_TOKENS_ENV} unset the boundary was sent "
            f"max_tokens={sent.max_tokens!r} — the module ships no default cap "
            "of its own: the production bound (400) is the environment's value, "
            "and an unset knob must mean 'provider profile decides', not a "
            "hard-coded number (CT-JUDGE-13; the divergence from the plan's "
            "exact cap is disclosed in this file's docstring)"
        )
    finally:
        store.close()