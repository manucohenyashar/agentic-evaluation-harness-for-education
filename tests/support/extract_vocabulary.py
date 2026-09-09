"""The assumed surface of `aeh.extract` (`M-EXTRACT`, #68/#69) — settled in one place.

Design §3.8 pins the `ExtractionRequest` / `ExtractionResult` *shapes* ("exactly as HLD
§9.9 specifies, with the addition of a `region_kind` marker per span") but pins **no
Python names at all** — no Interfaces block, no Protocol. Fourteen TS-26 cases cannot
each guess a different shape, so — the `console_vocabulary` / `review_vocabulary`
precedent — every name the TS-26 suite resolves is declared HERE, once, with its status,
and the tests import from here. If #68 ships a name differently, the rename is one line
in this file and nowhere else.

| Name in this file | Assumed `aeh.extract` name | Status |
|---|---|---|
| `WORKER` | `ExtractionWorker` | **invented here** — the driver class; `ScoringWorker` is the #78 precedent the review suite already keys on for `M-JUDGE` |
| `ASSEMBLE` | `assemble_request` | **invented here** — pure request assembly; design §3.10 declares the analogous `assemble(unit) -> ScoringRequest` for `M-JUDGE`. Three keyword inputs the §3.8 request shape needs but a shipped `WorkUnit` carries no source for are disclosed here: `dependency_evidence=[...]` (the parent spans the caller resolved, TC-EXTRACT-03), `question={"prompt_text": ..., "reference_solution": ...}` (the `question` object §3.8 puts on the request; the shipped criterion spec carries no reference solution, so rung-0 files supply it — the lint reads it back, TC-EXTRACT-04) and `store=...` (the lease resolves identities, the assembler the words — `Orchestrator.lease`'s reconciliation — so a unit whose `submission_text` is None resolves its transcript from the submission's current document through the store; the rung-2 files pass it at their fixture-recording call sites) |
| `PROMPT_FIELDS` | `prompt_fields` | **already assumed by the repo** — `tests/contract/review/test_ct_review_limits_and_config.py` and the `"#68 review"` registry entry resolve it; this suite aligns with that bet rather than making a second one |
| `RESULT_TYPE` / `REQUEST_TYPE` | `ExtractionResult` / `ExtractionRequest` | **design-named** (§3.8 Interfaces prose) — the type names, not any member |
| `TEMPLATE_VERSION` | `EXTRACTION_PROMPT_TEMPLATE_VERSION` | **invented here** — the pinned template version constant `NFR-EXTRACT-03` requires; `SETUP_PROMPT_TEMPLATE_V` is the shipped setup-side precedent |
| `SPAN_PARSE` | `parse_spans` | **invented here** — the pure reply→spans conversion TC-EXTRACT-15's property drives at rung 0; the worker's parse is where a bounds violation is refused, which is what makes one impossible to persist (`NFR-EXTRACT-02`) |
| `SECOND_FAMILY_MODEL` | `second_family_model` | **invented here** — the different-family model #69 runs flagged criteria with (`FR-EXTRACT-07`); keyed on for TC-EXTRACT-07 |

The assumed *member* surface of the worker, used by the integration files:

- `ExtractionWorker(store, provider, model_ref)` — the store it writes evidence through,
  the provider it calls, and the small extractor model (`ModelRef(role="extractor", ...)`;
  the role literal is already shipped in `aeh.conf`).
- `.process(unit) -> ExtractionResult` — one leased `stage='extract'` unit in (an orch
  `WorkUnit`, the shipped type), a completed unit and a persisted evidence row out. The
  three-strike retry of FR-EXTRACT-08 happens inside: transport and parse failures retry
  three times, then the unit quarantines (design §3.8 error handling; `M-PROV`'s
  Requires row: "parse failures retry and then surface, which is what makes the
  three-strike quarantine well-defined").

The assumed *response* format the extractor's completion carries is fixed here too
(`span_completion`), because the recorded-fixture tests must construct one: the module's
parse of the model's reply is #68's, so the JSON shape below is a **disclosed stand-in**
— one function, one place, and the worker is free to parse whatever it likes as long as
the spans come out.

Nothing in this file imports `aeh.extract`; resolution happens inside the test bodies
via `tests.support.impl.require`, so a missing module is a stated failure, not a
collection error.
"""

from __future__ import annotations

import json
from typing import Any

#: The implementing stories. #68 owns the module (the repo pins it:
#: `src/aeh/orch.py` — "`M-EXTRACT` does not exist yet (#68)" — and the `"#68 review"`
#: registry entry); #69 owns the second-family mechanism (`FR-EXTRACT-07`, Phase 2).
EXTRACT_ISSUE = "#68"
SECOND_FAMILY_ISSUE = "#69"

WORKER = "ExtractionWorker"
ASSEMBLE = "assemble_request"
PROMPT_FIELDS = "prompt_fields"
REQUEST_TYPE = "ExtractionRequest"
RESULT_TYPE = "ExtractionResult"
TEMPLATE_VERSION = "EXTRACTION_PROMPT_TEMPLATE_VERSION"
SPAN_PARSE = "parse_spans"
SECOND_FAMILY_MODEL = "second_family_model"

#: Every symbol the TS-26 suite resolves from `aeh.extract`, in one tuple — the
#: `WRITTEN_AHEAD_BLOCKERS` conjunction for the #68-keyed files is built from this, so
#: the registry cannot name a symbol the tests stopped using (or vice versa).
TS26_EXTRACT_SYMBOLS = (
    WORKER,
    ASSEMBLE,
    PROMPT_FIELDS,
    REQUEST_TYPE,
    RESULT_TYPE,
    TEMPLATE_VERSION,
    SPAN_PARSE,
)

# --- TS-27 (#71), the injection-resistance cases -------------------------------------------
#
# The TS-27 suite (TC-EXTRACT-10, ADV-02) reuses every TS-26 name above and adds exactly one
# invented name of its own — the judge-reply stand-in below. The judge symbols the ADV-02 file
# resolves (`aeh.judge:ScoringWorker`, `aeh.judge:prompt_fields`) are **already assumed by the
# repo** (the `"#78"`, `"#78 review"` and `"#78 rerun review"` registry entries), so they are
# referenced here rather than re-declared: a second declaration would be a second bet that could
# drift from the first.

#: The implementing story for `M-JUDGE` — the ADV-02 file resolves judge names against it, so
#: its writtenahead registry entry is a conjunction over BOTH modules (#68's driver makes the
#: extract leg runnable, #78's worker makes the band leg runnable — either absent is a red case).
JUDGE_ISSUE = "#78"

#: The subset of the TS-26 surface the TC-EXTRACT-10 file resolves. The writtenahead registry
#: entry for that file is built from this tuple (the `TS26_EXTRACT_SYMBOLS` pattern), so the
#: registry cannot name a symbol the file stopped using.
TS27_EXTRACT_SYMBOLS = (
    WORKER,
    ASSEMBLE,
    PROMPT_FIELDS,
    RESULT_TYPE,
    TEMPLATE_VERSION,
)


def verdict_completion(
    band: str,
    self_confidence: float,
    *,
    build_id: str,
    cited_spans: list[dict[str, Any]] | None = None,
    evidence_assessment: str = "the cited spans support the band",
    evidence_sufficient: bool = True,
) -> Any:
    """A `Completion` whose text is the assumed judge reply for one verdict.

    **Disclosed stand-in** (see the module docstring): the wire format of a judge reply is
    #78's to fix, but the five field NAMES and their ORDER are design-named — FR-JUDGE-09
    requires the response fields in exactly this order (`cited_spans`, `evidence_assessment`,
    `evidence_sufficient`, `band`, `self_confidence`) and rejects a reply whose fields arrive
    in a different order, so the stand-in serializes them in that order and never re-sorts.
    `band` is a band NAME from the criterion's declared set (FR-JUDGE-04); `self_confidence`
    is persisted but never alone determines routing (FR-JUDGE-13).
    """
    from aeh.prov import Completion

    reply = {
        "cited_spans": list(cited_spans or []),
        "evidence_assessment": evidence_assessment,
        "evidence_sufficient": evidence_sufficient,
        "band": band,
        "self_confidence": self_confidence,
    }
    return Completion(
        text=json.dumps(reply),  # insertion order IS the contract (FR-JUDGE-09)
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
        resolved_build=build_id,
        cached_prefix_tokens=0,
        cost=None,
    )


#: `ModelRef(role="extractor", ...)` — the single small model of NFR-EXTRACT-01, shaped
#: like `EDGE_TRANSCRIBER` (`tests/support/conf_builders.py`). Callers who need a
#: *different family* for #69 build the second ref themselves; both must be
#: `role="extractor"` — the role literal `aeh.conf` already declares.
def extractor_ref(build_id: str = "/models/qwen3-30b-a3b.gguf@sha256:eeee",
                  provider: str = "ollama",
                  quantization: str = "q4") -> Any:
    """A `ModelRef` for the extractor role, with the HLD §9.9 worked example's model."""
    from aeh.conf import ModelRef

    return ModelRef(
        role="extractor",
        provider=provider,
        build_id=build_id,
        quantization=quantization,
    )


def span_completion(spans: list[dict[str, Any]], *, build_id: str) -> Any:
    """A `Completion` whose text is the assumed extractor reply for `spans`.

    **Disclosed stand-in** (see the module docstring): the reply format the worker
    parses is #68's to fix. This builds the shape the TS-26 suite records — a JSON
    object whose `spans` list carries `start`, `end`, `text` and (where present)
    `region_kind`. `resolved_build` is what the fixture provider reports back
    (`FR-PROV-04`: the build that actually answered), which is what TC-EXTRACT-05's
    oracle compares the evidence row against.
    """
    from aeh.prov import Completion

    return Completion(
        text=json.dumps({"spans": spans}, sort_keys=True),
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
        resolved_build=build_id,
        cached_prefix_tokens=0,
        cost=None,
    )


def sampling_params() -> Any:
    """The sampling parameters the suite records and the worker is assumed to send."""
    from aeh.prov import SamplingParams

    return SamplingParams(temperature=0.0)
