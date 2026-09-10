"""`TC-ORCH-C06` — exactly one submission per dispatched request, with no mechanism
to batch two (§6.11.7).

`CT-ORCH-06`'s two limbs, at the plan's rungs:

1. **The payload cardinality and the sentinel differential (steps 1 and 4).** A
   complete run over a cohort whose submissions carry deliberately distinctive
   sentinel content, every dispatched request captured at the transport seam, and
   the ASSEMBLED PAYLOADS — the rendered `prompt_fields` — read back: exactly one
   submission's sentinel appears in each payload, across BOTH closed schemas
   (`ScoringRequest` and `ExtractionRequest` — the plan's step 1: "asserted over
   the assembled payloads, not over the dispatch call signature, since the
   batching would appear in the payload"). A payload carrying a second
   submission's sentinel is the cross-contamination the differential names; a
   payload carrying none is a fixture that never reached the assembler.

2. **The surface admits no batching (step 2, adversarial form).** The plan's
   construction — "add request batching behind a `ORCH_BATCH_SIZE` knob defaulting
   to 1" — is the erosion that stays invisible to every functional case, so the
   case asserts the CAPABILITY's absence, not merely its disuse: an env-knob census
   over the dispatch modules' sources (`aeh.orch`, `aeh.judge`, `aeh.extract`,
   `aeh.synth`, and `aeh.conf` where `RunConfig` reads its knobs) in which no knob
   name carries `BATCH_SIZE` (the plan's named shape) and no knob pairs
   `SUBMISSION` with a batching stem — plus the closed request schemas, which carry
   no submission-sequence field: the submission field is a scalar view, and a
   list-valued submission argument is the "second door" the census exists to keep
   shut. The unit-count knobs that legitimately exist (`HARNESS_ORCH_ENUM_COMMIT_BATCH`,
   `HARNESS_ORCH_DISPATCH_WALK_BATCH`) batch at the persistence/claim dimension —
   each unit still assembles exactly one request — and the census names the
   distinction rather than banning the word.

Relationship to shipped cases, disclosed (the plan itself: C06 "shares assertions
with `TC-ORCH-19` and `ADV-04`"): `tests/artifact/test_one_submission_per_request.py`
holds the corpus half over a complete run (its step 1) and the API reflection —
`ScoringWorker.assemble` takes exactly one unit, no method parameter or
`RunConfig` field accepts a submission sequence. Neither file drives the sentinel
differential (its submissions are plain or delimiter-mimicking, not
mutually-distinctive) and neither runs the knob census — the adversarial
construction is this case's own. The plan's step 3 (the rung-4 E2E journey over
~23,000 units) is the load tier's limb: the corpus half here asserts the same
property at contract scale, and the load story's own cases own the 23,000-unit
figure (`TC-ORCH-C18`'s thresholds).

Isolation: rung 3 — real store, real package, real documents; the capturing seam is
the only double, and it is the same shape the artifact suite's corpus half keys on.
"""

from __future__ import annotations

import re
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import get_origin, get_type_hints

import pytest

from aeh.extract import ExtractionRequest
from aeh.extract import prompt_fields as extract_prompt_fields
from aeh.judge import ScoringRequest
from aeh.judge import prompt_fields as judge_prompt_fields
from aeh.prov import Completion
from aeh.store import open_store
from tests.support.orch_run import PLAIN_TRANSCRIPT, seed_document, seed_run

pytestmark = [pytest.mark.contract]

_SUBMISSIONS = ("SYN-001", "SYN-002", "SYN-003")

_CRITERIA = (
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "holistic"},
)

#: Step 4's deliberately distinctive content: one sentinel per submission, each a
#: string no other submission's document holds, so a payload that renders two
#: submissions renders two sentinels and the cardinality read names it.
_SENTINELS = {
    "SYN-001": "SENTINEL-C06-QX7-ALPHA",
    "SYN-002": "SENTINEL-C06-QX7-BRAVO",
    "SYN-003": "SENTINEL-C06-QX7-CHARLIE",
}


class _CapturingSeam:
    """The transport double: records every assembled request, answers one
    completion. The dispatch's batch arm closes on any `Completion` — the parse is
    the owning stage's — so one reply serves both closed schemas."""

    def __init__(self) -> None:
        self.requests: list = []

    def call(self, request: object) -> Completion:
        self.requests.append(request)
        return Completion(
            text="synthetic band: B",
            tokens_in=3,
            tokens_out=2,
            latency_ms=1,
            resolved_build="build-ct-c06-seam",
            cached_prefix_tokens=0,
            cost=None,
        )


def test_tc_orch_c06_every_dispatched_payload_carries_exactly_one_submission(
    tmp_data_dir,
):
    """Steps 1 and 4: over a complete run with every request captured, each rendered
    payload carries exactly one submission's sentinel — its own — and no other
    submission's content appears anywhere in it, over both closed schemas."""
    seam = _CapturingSeam()
    store = open_store(tmp_data_dir)
    try:
        orchestrator, run_id, _ = seed_run(
            store, submissions=_SUBMISSIONS, criteria=_CRITERIA, transport=seam,
        )
        for submission_id, marker in _SENTINELS.items():
            seed_document(
                store, submission_id, f"{PLAIN_TRANSCRIPT}\n\nCohort marker {marker}."
            )
        orchestrator.enumerate_units(run_id)
        orchestrator.start(run_id)
        report = orchestrator.progress(run_id)
        for _ in range(64):
            if report.complete:
                break
            report = orchestrator.progress(run_id)
        assert report.complete, (
            "the sentinel run never exhausted — a partial drive would let a payload "
            "the dispatch never sent stand in for one it did"
        )

        requests = seam.requests
        assert requests, (
            "the run dispatched no request — nothing about the one-submission "
            "prohibition was exercised"
        )
        prompt_fields_for = (
            (ScoringRequest, judge_prompt_fields),
            (ExtractionRequest, extract_prompt_fields),
        )
        seen: dict[str, set[type]] = {sid: set() for sid in _SENTINELS}
        for request in requests:
            for schema, render in prompt_fields_for:
                if isinstance(request, schema):
                    break
            else:
                raise AssertionError(
                    f"the dispatch dispatched {type(request).__name__}, not a closed "
                    "request schema — the payload cardinality is assertable only "
                    "over the closed types (CT-JUDGE-02)"
                )
            submission_id = request.submission.submission_id
            assert not isinstance(submission_id, (list, tuple, set, frozenset)), (
                f"assembled request carries a SEQUENCE of submissions "
                f"({submission_id!r}) — the batching the plan's adversarial "
                "construction describes, arrived in the payload"
            )
            assert submission_id in _SENTINELS, (
                f"the request names submission {submission_id!r}, which is not one "
                "of the cohort's — a request without exactly one known submission "
                "is a batching or identity failure (FR-ORCH-20)"
            )
            seen[submission_id].add(schema)

            payload = dict(render(request).fields)
            rendered = {name: str(value) for name, value in payload.items()}
            present = {
                candidate
                for candidate, marker in _SENTINELS.items()
                if any(marker in value for value in rendered.values())
            }
            assert present == {submission_id}, (
                f"the payload for {submission_id} renders "
                f"{sorted(present - {submission_id}) or 'no'} other submission('s) "
                "sentinel — the exact-cardinality oracle (step 1) and the "
                "cross-contamination differential (step 4) both read this set: "
                "exactly one submission's content, and never a neighbour's"
            )
            own_marker = _SENTINELS[submission_id]
            assert any(own_marker in value for value in rendered.values()), (
                f"the request's own sentinel never reached its rendered payload — "
                "an empty render would pass the cardinality read vacuously"
            )

        for submission_id, stages in seen.items():
            assert stages == {ScoringRequest, ExtractionRequest}, (
                f"submission {submission_id} was dispatched only through "
                f"{sorted(s.__name__ for s in stages)} — the differential must "
                "cover both closed schemas' payloads (the plan's step 1: every "
                "assembled scoring AND extraction request)"
            )
    finally:
        store.close()


#: The dispatch modules whose knobs and schemas the census reads — the model-call
#: path (`FR-ORCH-20`'s subjects) plus the config module `RunConfig` reads through.
_CENSUS_MODULES = ("orch.py", "judge.py", "extract.py", "synth.py", "conf.py")

_ENV_NAME = re.compile(r"HARNESS_[A-Z0-9_]+")

#: The stems a submission-batching knob would name. `BATCH` alone is NOT an
#: offender: `HARNESS_ORCH_ENUM_COMMIT_BATCH` and `HARNESS_ORCH_DISPATCH_WALK_BATCH`
#: batch at the persistence and unit-claim dimensions — each unit still assembles
#: exactly one request — which is the distinction the artifact suite's API half
#: draws and this census keeps (a submission batch is what is forbidden).
_BATCH_STEMS = ("BATCH", "GROUP", "MULTI", "MERGE", "PACK", "CHUNK", "COMBINE")

#: Field names a batching mechanism would hang on the closed request schemas.
_FORBIDDEN_FIELDS = frozenset({
    "submissions", "submission_ids", "submission_batch", "batch_submissions",
    "submissions_per_request", "batch_size", "batch",
})


def test_tc_orch_c06_the_dispatch_surface_admits_no_batching_mechanism():
    """Step 2, adversarial form: the plan's `ORCH_BATCH_SIZE`-behind-a-knob
    construction would leave every functional case green, so the capability's
    ABSENCE is asserted — no env knob names request batching, no knob pairs the
    submission dimension with a batching stem, and the closed request schemas carry
    no list-valued submission field."""
    import aeh.extract
    import aeh.judge
    import aeh.orch
    import aeh.synth

    root = Path(aeh.orch.__file__).resolve().parent
    census: dict[str, list[str]] = {}
    for name in _CENSUS_MODULES:
        text = (root / name).read_text(encoding="utf-8")
        census[name] = sorted(set(_ENV_NAME.findall(text)))
    all_names = sorted({n for names in census.values() for n in names})

    assert "HARNESS_ORCH_DISPATCH_WALK_BATCH" in all_names, (
        f"the census walked {all_names} — the dispatch module's own unit-claim "
        "knob is absent, so the walker read something other than the dispatch "
        "path and every refusal below would be vacuous"
    )

    # The plan's named construction, by name: a request-batching knob sized in
    # submissions — with ORCH_BATCH_SIZE the exact spelling the adversarial
    # construction proposes.
    exact = [n for n in all_names if "BATCH_SIZE" in n or "ORCH_BATCH" in n]
    assert not exact, (
        f"the dispatch surface exposes knob(s) {exact} — `ORCH_BATCH_SIZE` "
        "defaulting to 1 is the plan's own adversarial construction: off by "
        "default every functional case stays green while one configuration "
        "change correlates every grade in a cohort (CT-ORCH-06, RISK-02)"
    )
    paired = [
        n for n in all_names
        if "SUBMISSION" in n and any(stem in n for stem in _BATCH_STEMS)
    ]
    assert not paired, (
        f"knob(s) {paired} pair the submission dimension with a batching stem — "
        "a knob that groups submissions is the mechanism FR-ORCH-20 forbids "
        "providing, whatever its default"
    )

    # The second door: a list-valued submission argument on the closed request
    # schemas — the batching that would appear in the payload even with no knob.
    for schema, schema_name in (
        (ScoringRequest, "ScoringRequest"),
        (ExtractionRequest, "ExtractionRequest"),
    ):
        hints = get_type_hints(schema)
        assert hints, (
            f"{schema_name} resolved no field annotations — the schema walk read "
            "nothing, so the refusal below would be vacuous"
        )
        for field_name, field_type in hints.items():
            assert field_name not in _FORBIDDEN_FIELDS, (
                f"{schema_name}.{field_name} is a submission-batching field — a "
                "sequence-of-submissions request is the capability FR-ORCH-20 "
                "forbids (CT-ORCH-06: none will be added)"
            )
            if field_name == "submission":
                origin = get_origin(field_type)
                assert origin is None or origin not in (
                    list, tuple, set, frozenset,
                ), (
                    f"{schema_name}.submission is a {origin} — a list-valued "
                    "submission argument is exactly the second submission's door "
                    "in one model call (RISK-02)"
                )
