"""`CT-EXTRACT-12` — the version knobs are pinned and are inputs to `work_id`
(`TC-EXTRACT-C12`).

Case of test plan §6.11.8; issue #72 (TS-65). Written ahead of #68 (`M-EXTRACT`,
which owns `EXTRACTION_PROMPT_TEMPLATE_VERSION` — `aeh.orch`'s shipped
`EXTRACTOR_VERSION` stand-in comment names the same handover); registered in
`WRITTEN_AHEAD_BLOCKERS` under `"#68 extraction contract suite (TS-65)"`.

The clause: `extractor_version` and the prompt template version are **pinned** and
are **inputs to `work_id`** (NFR-EXTRACT-03, CT-ORCH-01), so changing either
invalidates dependent work automatically rather than by manual cleanup (RISK-09:
a template changes and stale evidence is silently reused).

Halves:
1. **The hash differential per knob, rung 0** — over the SHIPPED
   `compute_work_id`: nine identical inputs, then each knob changed alone changes
   the hash; both knob names are in the declared `WORK_ID_INPUTS`; and the
   extractor's pinned template constant is a non-empty string — a real pinned value,
   not a float or a version object the hash cannot take.
2. **The pinned constant flows the whole pipeline, rung 2** — a run configured with
   the extractor's OWN pinned constant as `prompt_template_v`: the ledger's
   enumerated extract-unit `work_id` recomputes exactly from the run row's stored
   inputs (the `TC-ORCH-C01` pairing, asserted from the extract side — enumeration
   hashes the configured value, not another one), and changing each knob alone moves
   the content address. That IS the automatic invalidation: evidence keyed under
   the old `work_id` can never be read as the new unit's, with no cleanup step
   anywhere.

Discriminator: a `#68` that unpins the template version (a value that drifts) turns
half 1 red on the constant-shape assertion; an extractor version or template change
that does NOT reach `work_id` (hashing a hard-coded string instead of the configured
one) turns half 2 red on the recomputation — while every `FR-EXTRACT-*` case, which
never changes a version, stays green. Both halves fail today only through the
designed blocker: the pinned constant is #68's.

**Disclosed stand-ins** (suite register, `_doubles.py`): none new — the case reads
the shipped `compute_work_id` / `WORK_ID_INPUTS` / `EXTRACTOR_VERSION` and the
vocabulary's `TEMPLATE_VERSION` name. **Isolation: rung 0 (half 1) / rung 2
(half 2)** — the differential is pure; the pipeline half runs the real store, real
ledger and real enumeration.
"""

from __future__ import annotations

import pytest

from aeh.orch import (
    EXTRACTOR_VERSION,
    STAGE_EXTRACT,
    WORK_ID_INPUTS,
    Orchestrator,
    compute_work_id,
)
from tests.support.conf_builders import edge_cfg, edge_panel
from tests.support.extract_vocabulary import TEMPLATE_VERSION
from tests.support.impl import EXTRACT_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID
from tests.contract.extract._doubles import (
    build_markdown,
    make_world,
    require_extract_surface,
    resolved_config,
)

pytestmark = pytest.mark.contract

_MARKDOWN = build_markdown("The buffer was bounded after the fix.\n")
_CRITERIA = [{"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"}]

#: The nine inputs `compute_work_id` hashes, held fixed except for the knob under test.
_BASE_INPUTS = {
    "run_id": "r-ct-c12",
    "stage": STAGE_EXTRACT,
    "submission_id": "SYN-001",
    "criterion_id": "C1",
    "judge_id": None,
    "package_version_id": "pv-1",
    "panel_config": '{"judges":["j1"]}',
    "prompt_template_version": "extract-prompt/7",
    "extractor_version": EXTRACTOR_VERSION,
}


def test_tc_extract_c12_each_version_knob_alone_changes_the_work_id_hash():
    """`TC-EXTRACT-C12` half 1 — over the shipped hash: changing each version knob
    ALONE changes `work_id`; both knobs are declared inputs; the extractor's pinned
    template constant is a pinned string."""
    template_version = require(EXTRACT_MODULE, TEMPLATE_VERSION, issue="#68")
    require_extract_surface()
    assert isinstance(template_version, str) and template_version.strip(), (
        f"TC-EXTRACT-C12: EXTRACTION_PROMPT_TEMPLATE_VERSION is "
        f"{template_version!r} — the prompt template version must be a PINNED, "
        f"non-empty string (NFR-EXTRACT-03), not a value that drifts"
    )
    for knob in ("prompt_template_version", "extractor_version"):
        assert knob in WORK_ID_INPUTS, (
            f"TC-EXTRACT-C12: {knob} is not in the declared WORK_ID_INPUTS — a "
            f"version change would not invalidate dependent work"
        )
        changed = dict(_BASE_INPUTS)
        changed[knob] = _BASE_INPUTS[knob] + "-changed"
        base_id = compute_work_id(**_BASE_INPUTS)
        changed_id = compute_work_id(**changed)
        assert base_id != changed_id, (
            f"TC-EXTRACT-C12: changing {knob} alone left work_id unchanged — stale "
            f"evidence would be silently reused (RISK-09)"
        )
    # And the knobs do not cancel: changing BOTH differs from changing either alone.
    both = dict(_BASE_INPUTS)
    both["prompt_template_version"] += "-a"
    both["extractor_version"] += "-b"
    assert compute_work_id(**both) not in {
        compute_work_id(**_BASE_INPUTS),
        compute_work_id(**{**_BASE_INPUTS, "prompt_template_version": _BASE_INPUTS["prompt_template_version"] + "-a"}),
        compute_work_id(**{**_BASE_INPUTS, "extractor_version": _BASE_INPUTS["extractor_version"] + "-b"}),
    }, (
        "TC-EXTRACT-C12: the two knobs are not independent inputs to the hash"
    )


def test_tc_extract_c12_the_pinned_constant_flows_enumeration_and_invalidation(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C12` half 2 — the extractor's pinned template constant configured
    into a real run: the ledger's work_id recomputes from the run row's stored inputs
    (nothing else was hashed), and each knob changed alone moves the content address —
    invalidation is automatic, by address, with no cleanup step."""
    template_version = require(EXTRACT_MODULE, TEMPLATE_VERSION, issue="#68")
    require_extract_surface()
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        orchestrator = Orchestrator(world.store)
        run_id = orchestrator.create_run(
            ORCH_COHORT_ID, world.version,
            resolved_config(edge_cfg(
                panel=edge_panel(1), prompt_template_v=template_version,
            )),
        )
        # The shipped ledger enumerates lazily (at `lease`/`resume`); this case reads
        # the enumerated units directly, so it performs the enumeration itself.
        orchestrator.enumerate_units(run_id)
        handle = world.store.cohort(ORCH_COHORT_ID)
        (run_row,) = handle.query(
            "SELECT package_version_id, panel_config, prompt_template_v "
            "FROM run WHERE run_id = :r",
            r=run_id,
        )
        (unit,) = handle.query(
            "SELECT work_id, run_id, stage, submission_id, criterion_id, judge_id "
            "FROM work_unit WHERE run_id = :r AND stage = :st",
            r=run_id, st=STAGE_EXTRACT,
        )
        stored_inputs = {
            "run_id": unit["run_id"],
            "stage": unit["stage"],
            "submission_id": unit["submission_id"],
            "criterion_id": unit["criterion_id"],
            "judge_id": unit["judge_id"],
            "package_version_id": run_row["package_version_id"],
            "panel_config": run_row["panel_config"],
            "prompt_template_version": run_row["prompt_template_v"],
            "extractor_version": EXTRACTOR_VERSION,
        }
        assert stored_inputs["prompt_template_version"] == template_version, (
            f"TC-EXTRACT-C12: the run stored prompt_template_v="
            f"{stored_inputs['prompt_template_version']!r} but the extractor pins "
            f"{template_version!r} — the configured template and the extractor's "
            f"template have drifted apart (RISK-09)"
        )
        assert compute_work_id(**stored_inputs) == unit["work_id"], (
            "TC-EXTRACT-C12: the enumerated work_id does not recompute from the "
            "stored inputs — enumeration hashed something other than the configured "
            "versions (the TC-ORCH-C01 pairing, from the extract side)"
        )
        for knob in ("prompt_template_version", "extractor_version"):
            changed = dict(stored_inputs)
            changed[knob] = stored_inputs[knob] + "-changed"
            assert compute_work_id(**changed) != unit["work_id"], (
                f"TC-EXTRACT-C12: changing {knob} alone does not move the content "
                f"address — dependent work would not be invalidated automatically"
            )
    finally:
        world.close()
