"""`TC-JUDGE-C15` — the template pin invalidates through the work id, and temperature
zero is a sampling parameter, not a determinism guarantee (§6.11.10).

`CT-JUDGE-15` (config): *"`JUDGE_PROMPT_TEMPLATE_V` is pinned and is an input to
`work_id`, so a template change invalidates dependent work automatically.
`JUDGE_TEMPERATURE` (Assumption: 0) is a sampling parameter, **not** a determinism
guarantee — see CT-JUDGE-17."* (detailed design, verbatim). The plan row adds the
explicit disclaimer asserted as a negative: "Assert no code path treats temperature 0
as licence to cache, dedupe or skip a re-run — which is the assumption `CT-JUDGE-17`
forbids and this knob invites."

Three cases carry it:

1. **the pin and the invalidation differential** (rung 2) — the run is created with
   the caller's declared `prompt_template_v` equal to the module's
   `JUDGE_PROMPT_TEMPLATE_V` pin (the production linkage: the run declares the
   version the judge renders by), every score unit's `work_id` re-derives from its
   nine ledger inputs with that version, and varying ONLY
   `prompt_template_version` — the one input the clause names — re-addresses the
   work: the bumped version computes a DIFFERENT id, so a template change produces
   new units rather than a cleanup job (`FR-ORCH-01`, `NFR-EXTRACT-03`);
2. **the knob rides and the boundary re-samples** (rung 2) —
   `HARNESS_JUDGE_TEMPERATURE` read at call time: set to 0.5, the boundary's
   recorded `SamplingParams` carry 0.5 on the wire verbatim; the SAME request
   dispatched again under the default temperature zero is dispatched AGAIN — one
   fresh call, a different valid reply accepted, no code path treating temperature
   0 as licence to cache, dedupe or skip a re-run;
3. **the artifact assertion on the absence of determinism assumptions** (rung 0) —
   the module's AST carries no caching decorator (`functools.cache`/`lru_cache`/
   `cached_property`) and no comparison branch that conditions on a temperature —
   the two shapes a "temperature 0 means replay" assumption takes. Positive
   controls prove both scans fire; the module constant is pinned at its Assumption
   value 0.0 in case 2 so the scan's subject exists.

Cross-references, not duplicates: `TC-EXTRACT-C12`
(`tests/contract/extract/test_ct_extract_c12_versions_in_work_id.py`) owns the
EXTRACTION side of the versions-in-work-id contract (the extractor's own knobs);
this file is the judge side — the template the JUDGE renders by. The
extraction-side artifact case is `tests/artifact/test_extraction_prompt_template.py`
(TS-28's pin); this file pins the judge template by the same convention. The
nine-input re-derivation over a WHOLE run is `TC-ORCH-34`'s property case
(`tests/property/test_orch_34_enumeration_totals.py`) — this file re-derives the
judge-side unit and does the version-bump differential the property case does not.
The consumer sweep that must stay correct UNDER verdict variation is
`TC-JUDGE-C17` (`test_nonpromise_reproducibility.py`); this file holds the
producer-side knob the disclaimer names.

Isolation: rung 2 — real store, real workers, a transport double at the model
boundary; rung 0 for the AST limb; the socket guard is autouse.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.orch import EXTRACTOR_VERSION, compute_work_id
from aeh.store import open_store
from tests.contract.judge._drive import (
    BANDS,
    PANEL_REFS,
    RecordingTransport,
    add_bands,
    drive_extract,
    lease_score_units,
    seed_world,
    spans,
)
from tests.support.conf_builders import EDGE_PANEL_3, edge_cfg
from tests.support.extract_vocabulary import verdict_completion
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_vocabulary import PROMPT_ISSUE, TEMPLATE_VERSION
from tests.support.orch_run import ORCH_COHORT_ID, seed_documents, seed_run

pytestmark = [pytest.mark.contract]

#: The story that owns the knob and the pin (`M-JUDGE` is complete — #78/#79/#80/#81;
#: the template pin itself is #79's surface).
ISSUE = "#78"

#: The plan's pin: `JUDGE_PROMPT_TEMPLATE_V` = "judge-prompt/2" (#81's render).
TEMPLATE_PIN = "judge-prompt/2"

#: The one input varied for the invalidation differential — everything else held.
_BUMPED = TEMPLATE_PIN + "-bumped"

_SUBMISSIONS = ("SYN-001", "SYN-002")

_JUDGE_BUILD = "build-judge-contract"

_C1_SPEC = {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic",
            "band_count": len(BANDS)}


def _seed_run_declaring_the_pin(store: Any, submissions: tuple[str, ...]) -> Any:
    """The `seed_world` chain with one override: the run's `prompt_template_v` is the
    module's own pin — the production linkage (the caller declares the version the
    judge renders by), so the re-derivation below reads the pin through the ledger."""
    cfg = resolve_run_config(
        edge_cfg(HARNESS_PROFILE="edge-local", panel=EDGE_PANEL_3,
                 prompt_template_v=TEMPLATE_PIN),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
    )
    orchestrator, run_id, version = seed_run(
        store, submissions=submissions, criteria=[_C1_SPEC], cfg=cfg,
    )
    add_bands(store, version, "C1", BANDS)
    seed_documents(store, submissions)
    orchestrator.enumerate_units(run_id)
    assert orchestrator.start(run_id) == "running", (
        "fixture bug: the seeded run did not start"
    )
    return orchestrator, run_id, version


def test_tc_judge_c15_the_template_pin_is_pinned_and_invalidates_through_the_id(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C15` case 1 (`CT-JUDGE-15`, the pin + the hash differential, rung 2,
    P0) — the module constant is the pinned version, the run declares it, every score
    unit's id re-derives from its nine ledger inputs with that version, and varying
    ONLY the version addresses different work: a template change invalidates
    automatically."""
    store = open_store(tmp_data_dir)
    try:
        # The pin: the module constant is the version the templates render by.
        pin = require(JUDGE_MODULE, TEMPLATE_VERSION, issue=PROMPT_ISSUE)
        assert pin == TEMPLATE_PIN, (
            f"JUDGE_PROMPT_TEMPLATE_V is {pin!r}, not the pinned {TEMPLATE_PIN!r} "
            "— the version pin is the template-change discriminator and must be "
            "bumped WITH the templates it pins (CT-JUDGE-15, FR-JUDGE-06/07)"
        )

        orchestrator, run_id, _version = _seed_run_declaring_the_pin(
            store, _SUBMISSIONS
        )
        drive_extract(orchestrator, store, make_fixture_provider())
        run_row = store.cohort(ORCH_COHORT_ID).query(
            "SELECT panel_config, prompt_template_v, package_version_id FROM run "
            "WHERE run_id = :r",
            r=run_id,
        )[0]
        # The production linkage: the caller's declared value IS the module's pin.
        assert run_row["prompt_template_v"] == pin, (
            f"the run declared prompt_template_v={run_row['prompt_template_v']!r} "
            f"but the module renders by {pin!r} — a render built under a version "
            "the run does not declare cannot be invalidated by that version "
            "(CT-JUDGE-15)"
        )

        units = lease_score_units(orchestrator)
        assert len(units) == len(_SUBMISSIONS), (
            f"fixture bug: the drive leased {len(units)} unit(s) — the "
            "re-derivation is over the run's real score units"
        )
        rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT work_id, stage, submission_id, criterion_id, judge_id "
            "FROM work_unit WHERE run_id = :r AND stage = 'score' ORDER BY work_id",
            r=run_id,
        )
        assert len(rows) == len(units), (
            f"fixture bug: the ledger holds {len(rows)} score unit(s) for "
            f"{len(units)} leased"
        )
        # The re-derivation: every unit's id is compute_work_id over its nine
        # ledger inputs, with the run's declared (pinned) version in place.
        for row in rows:
            expected = compute_work_id(
                run_id=run_id, stage=row["stage"],
                submission_id=row["submission_id"],
                criterion_id=row["criterion_id"], judge_id=row["judge_id"],
                package_version_id=run_row["package_version_id"],
                panel_config=run_row["panel_config"],
                prompt_template_version=pin,
                extractor_version=EXTRACTOR_VERSION,
            )
            assert row["work_id"] == expected, (
                f"score unit for {row['submission_id']} carries "
                f"{row['work_id'][:12]}… but its nine inputs recompute to "
                f"{expected[:12]}… — the judge template pin is not the address's "
                "input (CT-JUDGE-15, FR-ORCH-01)"
            )
        # The invalidation: varying ONLY prompt_template_version re-addresses the
        # work — the bumped version is a DIFFERENT unit, so a template change
        # produces new units rather than reusing the old ones.
        row = rows[0]
        bumped = compute_work_id(
            run_id=run_id, stage=row["stage"],
            submission_id=row["submission_id"],
            criterion_id=row["criterion_id"], judge_id=row["judge_id"],
            package_version_id=run_row["package_version_id"],
            panel_config=run_row["panel_config"],
            prompt_template_version=_BUMPED,
            extractor_version=EXTRACTOR_VERSION,
        )
        assert bumped != row["work_id"], (
            "compute_work_id ignores prompt_template_version — a template change "
            "could not invalidate dependent work through the id, and the stale "
            "units would be judged under a rubric they were never addressed to "
            "(CT-JUDGE-15, FR-ORCH-01, NFR-EXTRACT-03)"
        )
    finally:
        store.close()


def test_tc_judge_c15_temperature_is_a_sampling_parameter_not_a_licence(
    tmp_data_dir, make_fixture_provider, monkeypatch
):
    """`TC-JUDGE-C15` case 2 (`CT-JUDGE-15`, the knob + the re-sample, rung 2, P0) —
    the temperature knob rides the wire verbatim, and the SAME request dispatched
    under the default temperature zero is dispatched AGAIN: one fresh call, a
    different valid reply accepted, no cache, no dedupe, no skip."""
    provider = make_fixture_provider()
    store = open_store(tmp_data_dir)
    try:
        orchestrator, _run_id, _version = seed_world(store)
        drive_extract(orchestrator, store, provider)
        units = lease_score_units(orchestrator)
        assert units, "fixture bug: no score unit leased for the knob drive"
        unit = units[0]
        refs_by_build = {ref.build_id: ref for ref in PANEL_REFS}
        judge_ref = refs_by_build[unit.judge]
        temperature_env = require(JUDGE_MODULE, "TEMPERATURE_ENV", issue=ISSUE)
        request = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, None, judge_ref
        ).assemble(unit)

        # The knob rides verbatim: 0.5 is not clamped, not coerced, not defaulted.
        monkeypatch.setenv(temperature_env, "0.5")
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
        assert sent.temperature == 0.5, (
            f"the boundary was sent temperature={sent.temperature!r} under "
            f"{temperature_env}=0.5 — the sampling knob must ride the wire "
            "verbatim (CT-JUDGE-15; an env-calibrated constant that does not "
            "reach the wire is a phantom knob, CLAUDE.md seam 3)"
        )

        # The default temperature is zero — and zero is not a determinism
        # guarantee: the same request is dispatched AGAIN and the boundary calls
        # AGAIN, accepting a fresh completion (one new call, no skip).
        judge_temperature = require(
            JUDGE_MODULE, "JUDGE_TEMPERATURE", issue=ISSUE
        )
        assert judge_temperature == 0.0, (
            f"JUDGE_TEMPERATURE is {judge_temperature!r} — the clause's "
            "Assumption value is 0, and this case's re-sample limb is asserted "
            "AT the default (CT-JUDGE-15)"
        )
        monkeypatch.delenv(temperature_env, raising=False)
        transport = RecordingTransport(verdict_completion(
            "emerging", 0.0, build_id=_JUDGE_BUILD, cited_spans=spans(),
        ))
        worker = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)(
            store, transport, judge_ref
        )
        second = worker.dispatch(request, judge_ref)
        assert len(transport.calls) == 1, (
            f"the re-dispatch made {len(transport.calls)} call(s) — a request "
            "dispatched twice must be SAMPLED twice: temperature 0 is a sampling "
            "parameter, not a determinism guarantee, and no code path may treat "
            "it as licence to cache, dedupe or skip a re-run (CT-JUDGE-15, "
            "CT-JUDGE-17)"
        )
        assert transport.params()[-1].temperature == judge_temperature, (
            "the re-dispatch was not sent the default temperature — the knob's "
            "default is what the boundary sends when the environment is silent "
            "(CT-JUDGE-15)"
        )
        assert second.band == "emerging", (
            f"the re-dispatch landed {second.band!r} — a different valid reply on "
            "the identical request is ACCEPTED, not deduped to the first answer "
            "(CT-JUDGE-15, CT-JUDGE-17)"
        )
    finally:
        store.close()


def test_tc_judge_c15_no_code_path_treats_temperature_zero_as_determinism():
    """`TC-JUDGE-C15` case 3 (`CT-JUDGE-15`, the artifact assertion, rung 0, P0) —
    the module's AST carries no caching decorator and no comparison branch on a
    temperature: the two shapes a 'temperature 0 means replay' assumption takes.
    Positive controls prove both scans fire."""
    import aeh.judge

    judge_text = Path(aeh.judge.__file__).read_text(encoding="utf-8")
    parsed = ast.parse(judge_text)

    # Scan 1 — no caching decorator on anything the module defines. The bare form
    # (`@lru_cache`) is a Name; the parameterised form (`@lru_cache(maxsize=None)`)
    # is a Call around one — both count (the call form is the one a memo actually
    # ships with).
    def _decorator_name(decorator: Any) -> str | None:
        if isinstance(decorator, ast.Call):
            decorator = decorator.func
        if isinstance(decorator, ast.Name):
            return decorator.id
        if isinstance(decorator, ast.Attribute):
            return decorator.attr
        return None

    _CACHE_DECORATORS = {"lru_cache", "cache", "cached_property"}
    found: list[str] = []
    for node in ast.walk(parsed):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for decorator in node.decorator_list:
                name = _decorator_name(decorator)
                if name in _CACHE_DECORATORS:
                    found.append(f"{getattr(node, 'name', '?')}@{name}")
    assert found == [], (
        f"aeh.judge decorates {found} — a cached judgment is a stale verdict "
        "served on the assumption that an identical request owes an identical "
        "answer (CT-JUDGE-15, CT-JUDGE-17)"
    )

    # Scan 2 — no comparison branch reads a temperature: the constant feeds the
    # sampling default, never a conditional.
    temperature_compares = [
        compare.lineno for compare in ast.walk(parsed)
        if isinstance(compare, ast.Compare)
        and any(
            (isinstance(operand, ast.Name) and "temperature" in operand.id.lower())
            or (isinstance(operand, ast.Attribute) and "temperature" in operand.attr)
            for operand in [compare.left, *compare.comparators]
        )
    ]
    assert temperature_compares == [], (
        f"aeh.judge compares a temperature at line(s) {temperature_compares} — a "
        "comparison is how a 'temperature 0 means replay/skip' branch is written, "
        "and the knob is a sampling parameter, not a determinism guarantee "
        "(CT-JUDGE-15)"
    )

    # Positive controls: each scan flags its defect on synthetic text — both the
    # bare decorator form and the parameterised call form.
    control = ast.parse(
        "from functools import lru_cache\n"
        "@lru_cache\n"
        "def cached_judgment(x):\n"
        "    return x\n"
        "@lru_cache(maxsize=None)\n"
        "def cached_judgment_2(x):\n"
        "    return x\n"
        "if TEMPERATURE == 0:\n"
        "    cached_judgment(1)\n"
    )

    def _decorator_name(decorator: Any) -> str | None:
        if isinstance(decorator, ast.Call):
            decorator = decorator.func
        if isinstance(decorator, ast.Name):
            return decorator.id
        if isinstance(decorator, ast.Attribute):
            return decorator.attr
        return None

    control_decorators = [
        _decorator_name(d) for node in ast.walk(control)
        if isinstance(node, ast.FunctionDef) for d in node.decorator_list
    ]
    assert control_decorators == ["lru_cache", "lru_cache"], (
        "fixture bug: the decorator scan no longer detects cache decorators in "
        "both their forms — the prohibition above would be vacuous"
    )
    control_compares = [
        c for c in ast.walk(control)
        if isinstance(c, ast.Compare)
        and any(isinstance(op, ast.Name) and "temperature" in op.id.lower()
                for op in [c.left, *c.comparators])
    ]
    assert control_compares, (
        "fixture bug: the comparison scan no longer detects a temperature "
        "branch — the prohibition above would be vacuous"
    )