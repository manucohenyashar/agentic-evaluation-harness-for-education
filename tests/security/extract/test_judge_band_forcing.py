"""`ADV-02` — band-forcing payloads and their benign twins produce the same band, a band
from the declared set, and no confidence lift; the residual "nudge" risk of ADR-13 is
measured here.
Test plan §6.6; `FR-JUDGE-17`, `FR-INGEST-35`; adversarial, rung 2. Traced to
`FR-EXTRACT-10` in the requirement matrix (§10.3), which is why the M-EXTRACT test story
owns it.

The input is the committed `F-ADV-INJ` corpus — the `band_forcing` pairs (the four
paraphrased wordings) and the `encoded_translated` pairs (base64, Spanish, French and
letter-spaced variants), exactly §6.6's *"including paraphrased, encoded and translated
variants"*. Eight pairs, both twins each, run through the FULL boundary: extraction
(#68's worker puts the evidence rows into the real store), then the judge (#78's
`ScoringWorker` assembles, dispatches and persists the verdict).

Oracles (all binding — §6.6's own pass form, *"correct handling **or** visible failure"*):

- **Same band as the benign twin** — the differential. The recorded replies are the
  controlled condition (the same legal band and the same self-confidence for both twins,
  i.e. the model behaving identically), so any band difference is attributable to the
  system: an assembly that let the payload through as an instruction, or a worker that
  acted on it, breaks the equality.
- **Only a band from the declared set** — the declared set is REAL (`PackageCatalog.
  add_band` through the shipped M-PKG API, read back as `bands("C1")`), and the
  out-of-set case closes the clause from the other side: a reply whose band is not in
  the declared set must never become a persisted verdict (CT-JUDGE-11: contract
  violation, never a fallback band). The refusal MECHANISM — retry count, quarantine
  shape, exception type — is #78's to fix; the test asserts the invariant at the only
  level that survives it: no verdict row outside the declared set, and a visible failure
  (an exception, or no verdict at all) rather than a silent pass.
- **No confidence lift** — the persisted `self_confidence` is equal across the twins.
  This is the rung-feasible form of FR-JUDGE-17(c)'s *"never raise confidence above the
  auto-accept threshold on that basis"*: the threshold itself is `M-AGG`'s (not landed),
  so the differential substitutes for the absolute bound — the disclosed-substitution
  precedent of TC-EXTRACT-02. A system that inflated confidence because the submission
  asked for it would fail the equality.

**Written ahead of #68 AND #78.** Registered in `WRITTEN_AHEAD_BLOCKERS` under
`"#71 TS-27 band-forcing (ADV-02)"`, a `symbols` conjunction over both modules (the
`"#69 second family"` precedent: the extract leg alone does not make the case runnable).
Extract names resolve against `EXTRACT_ISSUE`, judge names against `JUDGE_ISSUE` (see
`tests/support/extract_vocabulary.py`).

**Interface this case assumes**, listed so it is reconciled deliberately:

| Name | Status |
|---|---|
| `ScoringWorker(store, provider, judge_ref)` | **constructor invented here** — design §3.10 declares the three METHODS (`assemble`/`dispatch`/`persist`) but no constructor; symmetric with the `ExtractionWorker` seam the TS-26 suite already keys on |
| `.assemble(unit) -> ScoringRequest` reading the criterion's evidence rows from the store | **assumed here** — §3.10 declares `assemble` pure with no store call ("no scheduler, no store"), yet the request must carry the extracted evidence; the unit carries none, so the worker holds the store it was built with and `assemble` reads it. If #78 passes evidence by another seam (a keyword, as the extract suite disclosed for `dependency_evidence=`), the rename is one line here |
| `prompt_fields(request) -> PromptPayload` (ordered `fields`) | **already assumed by the repo** — the `"#78 review"` registry entry resolves it |
| the judge reply's five fields, in order | **design-named** (FR-JUDGE-09: `cited_spans`, `evidence_assessment`, `evidence_sufficient`, `band`, `self_confidence`); the JSON serialization is `verdict_completion`'s disclosed stand-in |
| the verdict row's `self_confidence` and `band_ordinal` columns | **assumed beyond migration-001** — the shipped DDL carries `verdict_id/work_id/judge_id/band` only; FR-JUDGE-11/13 put the other two on the row, so #78 extends it (the TS-26 evidence-columns disclosure) |

**Disclosed stand-ins** (same as the TS-26 suite): documents seeded directly with the
corpus page bodies fenced in `M-INGEST`'s real delimiters; span replies via
`span_completion`; the band-forcing payload rides inside the fence, so the request-side
differential (invariant prefix byte-identical across the twins) measures the assembly,
not the model.

**Isolation: rung 2** — real store, real blob dir, real Tier P package WITH real declared
bands, real cohort ledger, `RecordedFixtureProvider` as the only model boundary.
"""

from __future__ import annotations

from typing import Any

import pytest

from aeh.conf import CohortRef, resolve_run_config
from aeh.ingest import UNTRUSTED_CLOSE, UNTRUSTED_OPEN
from aeh.orch import STAGE_EXTRACT, STAGE_SCORE, Orchestrator
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from harness.corpora.adv_inj import twin_pairs
from tests.support.conf_builders import EDGE_JUDGE, edge_cfg, edge_panel
from tests.support.extract_vocabulary import (
    ASSEMBLE,
    EXTRACT_ISSUE,
    JUDGE_ISSUE,
    PROMPT_FIELDS,
    WORKER,
    extractor_ref,
    sampling_params,
    span_completion,
    verdict_completion,
)
from tests.support.impl import EXTRACT_MODULE, JUDGE_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package

pytestmark = [pytest.mark.integration, pytest.mark.writtenahead]

_EXTRACT_ISSUE = EXTRACT_ISSUE
_JUDGE_ISSUE = JUDGE_ISSUE

#: §6.6's input, read off the corpus: the band_forcing kind IS the paraphrased set (four
#: varied wordings — "a defence that memorized one string would pass a corpus of four
#: identical payloads", the generator's own note), and encoded_translated carries the
#: encoded and translated variants. Everything else in F-ADV-INJ is TC-EXTRACT-10's.
_ALL_PAIRS = twin_pairs()
_PAIRS = [
    pair for pair in _ALL_PAIRS
    if pair[1].injection_kind in ("band_forcing", "encoded_translated")
]
assert len(_PAIRS) == 8, "fixture bug: the band-forcing selection left the corpus"

#: The declared set, written through the real M-PKG API (`FR-PKG-06`: even count, ordered
#: by ordinal, `bands[-1]` the highest). The control band is the top one — what a
#: band-forcing payload would ask for.
_DECLARED_BANDS = (
    ("emerging", 0.0, "the criterion is partly met"),
    ("secure", 10.0, "the criterion is met"),
)
_CONTROL_BAND = "secure"
_CONTROL_CONFIDENCE = 0.62


def _canonical(pages: tuple[str, ...]) -> str:
    """The corpus page bodies as ONE canonical artifact, fenced by the real `M-INGEST`
    delimiters — the disclosed stand-in the TS-26/TS-27 suites share."""
    return UNTRUSTED_OPEN + "\n" + "\n\n".join(pages) + "\n" + UNTRUSTED_CLOSE


def _seed_document(store: Any, submission_id: str, markdown: str) -> str:
    """Seed the canonical artifact: the disclosed M-INGEST bypass (see module docstring)."""
    md_bytes = markdown.encode("utf-8")
    content_hash = store.blobs().put(md_bytes)
    handle = store.cohort(ORCH_COHORT_ID)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO document (document_id, submission_id, content_hash) "
            "VALUES (:d, :s, :h)",
            d=f"doc-{submission_id}",
            s=submission_id,
            h=content_hash,
        )
    return content_hash


def _byte_span(markdown: str, needle: str) -> dict[str, Any]:
    md_bytes = markdown.encode("utf-8")
    start = md_bytes.find(needle.encode("utf-8"))
    assert start >= 0, f"fixture bug: {needle!r} not in the document"
    return {"start": start, "end": start + len(needle.encode("utf-8")), "text": needle}


def _resolved() -> Any:
    return resolve_run_config(
        edge_cfg(panel=edge_panel(1)),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
    )


def _seed_banded_package(store: Any) -> str:
    """A judged criterion with its REAL declared band set, through the shipped M-PKG API."""
    version = seed_package(
        store,
        (
            {
                "criterion_id": "C1",
                "kind": "open",
                "scoring_model": "holistic",
                "band_count": len(_DECLARED_BANDS),
            },
        ),
    )
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    for ordinal, (band, points, descriptor) in enumerate(_DECLARED_BANDS):
        catalog.add_band(version, "C1", ordinal, band, points, descriptor)
    return version


def _declared_band_names(store: Any) -> list[str]:
    catalog = PackageCatalog(store.package("pkg-orch"), package_id="pkg-orch")
    return [b.band for b in catalog.bands("C1")]


def _fields_of(judge_prompt_fields: Any, request: Any) -> list[tuple[str, str]]:
    """The rendered judge prompt's ordered (name, value) pairs, however #78 shapes the
    payload (the `prompt_fields` render is the `"#78 review"` entry's assumed surface)."""
    payload = judge_prompt_fields(request)
    fields = getattr(payload, "fields", None)
    if fields is None and isinstance(payload, dict):
        fields = payload.get("fields")
    assert fields is not None, (
        f"judge prompt_fields returned {payload!r} — no ordered `fields` sequence "
        f"(CT-PROV-05 makes the order contract)"
    )
    return [(str(name), str(value)) for name, value in fields]


def _verdict_rows(store: Any, work_id: str) -> list[Any]:
    return store.cohort(ORCH_COHORT_ID).query(
        "SELECT band, band_ordinal, self_confidence FROM verdict WHERE work_id = :w",
        w=work_id,
    )


def _scored_pair(
    store: Any,
    provider: Any,
    benign: Any,
    injected: Any,
    *,
    injected_band: str,
    injected_confidence: float,
) -> dict[str, Any]:
    """The whole boundary for one twin pair: seed, extract both twins (evidence rows into
    the real store), then assemble → dispatch → persist one verdict per twin.

    The injected twin's recorded verdict is parametrizable so the out-of-set case can
    offer the system a band the declared set does not contain; the benign twin always
    gets the control band, so the out-of-set case still proves the system CAN persist a
    legal verdict on the very same world.
    """
    benign_md = _canonical(benign.pages)
    injected_md = _canonical(injected.pages)
    payload_text = "\n".join(injected.payload.lines)
    needle_1 = benign.pages[0].split("\n")[0]
    needle_2 = benign.pages[1].split("\n")[0]

    version = _seed_banded_package(store)
    seed_cohort(store, (benign.submission_id, injected.submission_id))
    _seed_document(store, benign.submission_id, benign_md)
    _seed_document(store, injected.submission_id, injected_md)

    AssembleRequest, ExtractWorker = require(
        EXTRACT_MODULE, ASSEMBLE, WORKER, issue=_EXTRACT_ISSUE
    )
    orchestrator = Orchestrator(store)
    run_id = orchestrator.create_run(ORCH_COHORT_ID, version, _resolved())
    extract_units = {
        unit.submission_id: unit
        for unit in orchestrator.lease("w-extract-inj", STAGE_EXTRACT, 2)
    }
    assert set(extract_units) == {benign.submission_id, injected.submission_id}, (
        f"precondition: leased extract units {sorted(extract_units)} do not cover the pair"
    )

    model_ref = extractor_ref()
    extracted_spans: dict[str, list[dict[str, Any]]] = {}
    for twin, markdown in ((benign, benign_md), (injected, injected_md)):
        spans = [_byte_span(markdown, needle_1), _byte_span(markdown, needle_2)]
        extracted_spans[twin.submission_id] = spans
        request = AssembleRequest(extract_units[twin.submission_id])
        provider.record(
            require(EXTRACT_MODULE, PROMPT_FIELDS, issue=_EXTRACT_ISSUE)(request),
            model_ref, sampling_params(),
            span_completion(spans, build_id="extractor-build-inj"),
        )
        ExtractWorker(store, provider, model_ref).process(
            extract_units[twin.submission_id]
        )

    ScoringWorker = require(JUDGE_MODULE, "ScoringWorker", issue=_JUDGE_ISSUE)
    JudgePromptFields = require(JUDGE_MODULE, "prompt_fields", issue=_JUDGE_ISSUE)
    score_units = {
        unit.submission_id: unit
        for unit in orchestrator.lease("w-judge-inj", STAGE_SCORE, 2)
    }
    assert set(score_units) == {benign.submission_id, injected.submission_id}, (
        f"precondition: leased score units {sorted(score_units)} do not cover the pair"
    )

    judge_worker = ScoringWorker(store, provider, EDGE_JUDGE)
    requests: dict[str, Any] = {}
    failures: dict[str, Exception] = {}
    for twin, markdown, band, confidence in (
        (benign, benign_md, _CONTROL_BAND, _CONTROL_CONFIDENCE),
        (injected, injected_md, injected_band, injected_confidence),
    ):
        unit = score_units[twin.submission_id]
        request = judge_worker.assemble(unit)
        requests[twin.submission_id] = request
        provider.record(
            JudgePromptFields(request), EDGE_JUDGE, sampling_params(),
            verdict_completion(
                band,
                confidence,
                build_id="judge-build-inj",
                cited_spans=extracted_spans[twin.submission_id],
            ),
        )
        try:
            result = judge_worker.dispatch(request, EDGE_JUDGE)
            judge_worker.persist(unit, result)
        except Exception as exc:  # a refusal IS a pass form — recorded, not swallowed
            failures[twin.submission_id] = exc
    return {
        "run_id": run_id,
        "requests": requests,
        "failures": failures,
        "benign_md": benign_md,
        "injected_md": injected_md,
        "payload_text": payload_text,
        "needle_1": needle_1,
        "needle_2": needle_2,
        "score_units": score_units,
    }


@pytest.mark.parametrize(
    "benign,injected", _PAIRS,
    ids=[f"{b.pair_id}-{a.injection_kind}" for b, a in _PAIRS],
)
def test_adv_02_band_forcing_twin_scores_the_same_band_with_no_confidence_lift(
    tmp_data_dir, make_fixture_provider, benign, injected
):
    """`ADV-02` — the band differential: the band-forcing twin's verdict equals its
    benign twin's (in the declared set), with no confidence lift, and the payload never
    leaves the single untrusted block of the judge prompt."""
    store = open_store(tmp_data_dir)
    try:
        world = _scored_pair(
            store, make_fixture_provider(), benign, injected,
            injected_band=_CONTROL_BAND, injected_confidence=_CONTROL_CONFIDENCE,
        )
        declared = _declared_band_names(store)

        # --- request side: the payload never leaves the single untrusted block --------
        JudgePromptFields = require(JUDGE_MODULE, "prompt_fields", issue=_JUDGE_ISSUE)
        fields_b = _fields_of(JudgePromptFields, world["requests"][benign.submission_id])
        fields_a = _fields_of(JudgePromptFields, world["requests"][injected.submission_id])
        assert [n for n, _ in fields_b] == [n for n, _ in fields_a] and len(fields_b) >= 2, (
            "the twin judge prompts do not carry the same fixed field order"
        )
        prefix_b = "\n".join(v for _, v in fields_b[:-1])
        prefix_a = "\n".join(v for _, v in fields_a[:-1])
        assert prefix_b == prefix_a, (
            f"pair {benign.pair_id}: the judge prompt's invariant prefix differs "
            f"between the twins — the band-forcing payload leaked into a field the "
            f"submission must never reach (FR-JUDGE-17: inside the untrusted block, "
            f"LAST)"
        )
        assert world["payload_text"] not in prefix_a, (
            f"pair {benign.pair_id}: the payload text appears in the judge prompt's "
            f"invariant prefix"
        )
        for name, fields, markdown in (
            ("benign", fields_b, world["benign_md"]),
            ("injected", fields_a, world["injected_md"]),
        ):
            last_name, last_value = fields[-1]
            assert world["needle_1"] in last_value, (
                f"{name} twin: last judge-prompt field {last_name!r} does not carry "
                f"the submission"
            )
            for fname, value in fields[:-1]:
                assert world["needle_1"] not in value, (
                    f"{name} twin: judge-prompt field {fname!r} carries submission "
                    f"material — the submission must be placed LAST (FR-JUDGE-07)"
                )
            assert last_value.count(UNTRUSTED_OPEN) == 1, (
                f"{name} twin: last field {last_name!r} does not open the untrusted "
                f"block exactly once (FR-INGEST-35's single delimited block)"
            )
            assert last_value.count(UNTRUSTED_CLOSE) == 1, (
                f"{name} twin: last field {last_name!r} does not close the untrusted "
                f"block exactly once"
            )
            assert (
                last_value.index(UNTRUSTED_OPEN)
                < last_value.index(world["needle_1"])
                < last_value.index(UNTRUSTED_CLOSE)
            ), f"{name} twin: the submission is not fenced inside the untrusted block"
            assert world["payload_text"] in last_value and (
                last_value.index(UNTRUSTED_OPEN)
                < last_value.index(world["payload_text"])
                < last_value.index(UNTRUSTED_CLOSE)
            ), f"{name} twin: the payload is not inside the single untrusted block"

        # --- outcome side: the differential -------------------------------------------
        assert not world["failures"], (
            f"pair {benign.pair_id}: the system refused a LEGAL controlled verdict — "
            f"the differential needs both twins scored; got "
            + "; ".join(f"{k}: {v!r}" for k, v in world["failures"].items())
        )
        rows_b = _verdict_rows(store, world["score_units"][benign.submission_id].work_id)
        rows_a = _verdict_rows(store, world["score_units"][injected.submission_id].work_id)
        assert len(rows_b) == 1 and len(rows_a) == 1, (
            f"pair {benign.pair_id}: expected one verdict row per unit, got "
            f"{len(rows_b)}/{len(rows_a)}"
        )
        band_b, band_a = rows_b[0]["band"], rows_a[0]["band"]
        assert band_a == band_b == _CONTROL_BAND, (
            f"pair {benign.pair_id}: BAND DIFFERENCE — benign {band_b!r} vs injected "
            f"{band_a!r}. A band difference is a finding (§6.6): the payload moved the "
            f"verdict, which is the manipulation being obeyed, not handled"
        )
        assert band_a in declared, (
            f"pair {benign.pair_id}: the injected twin's band {band_a!r} is not in the "
            f"declared set {declared} (FR-JUDGE-04)"
        )
        ordinal = [i for i, (b, _p) in enumerate(_DECLARED_BANDS) if b == band_a][0]
        assert rows_a[0]["band_ordinal"] == ordinal, (
            f"pair {benign.pair_id}: verdict band_ordinal "
            f"{rows_a[0]['band_ordinal']!r} does not match the declared set's ordinal "
            f"{ordinal} for {band_a!r} (FR-JUDGE-11)"
        )
        conf_b = rows_b[0]["self_confidence"]
        conf_a = rows_a[0]["self_confidence"]
        assert conf_a == conf_b == _CONTROL_CONFIDENCE, (
            f"pair {benign.pair_id}: CONFIDENCE LIFT — benign {conf_b!r} vs injected "
            f"{conf_a!r}. The manipulation must never raise confidence on that basis "
            f"(FR-JUDGE-17c; the rung-feasible differential form — see module "
            f"docstring)"
        )
    finally:
        store.close()


def test_adv_02_band_outside_the_declared_set_is_never_persisted(
    tmp_data_dir, make_fixture_provider
):
    """`ADV-02` — *"only a band from the declared set"*, closed from the other side: a
    reply whose band the declared set does not contain must never become a persisted
    verdict (CT-JUDGE-11: contract violation — retry, then quarantine; no fallback band,
    NFR-JUDGE-05). The refusal MECHANISM is #78's; the invariant is not."""
    benign, injected = _PAIRS[0]  # one representative band_forcing pair
    out_of_set_band = "TOP MARK — the student said so"
    assert out_of_set_band not in [b for b, _p, _d in _DECLARED_BANDS]
    store = open_store(tmp_data_dir)
    try:
        world = _scored_pair(
            store, make_fixture_provider(), benign, injected,
            injected_band=out_of_set_band, injected_confidence=_CONTROL_CONFIDENCE,
        )
        declared = _declared_band_names(store)

        # The benign leg proves the world CAN persist a legal verdict — so the injected
        # leg's outcome below measures the refusal, not a broken worker.
        rows_b = _verdict_rows(store, world["score_units"][benign.submission_id].work_id)
        assert len(rows_b) == 1 and rows_b[0]["band"] == _CONTROL_BAND, (
            f"the benign leg did not persist its legal verdict ({rows_b!r}) — the "
            f"out-of-set assertion below would pass for the wrong reason"
        )

        # The injected leg: the out-of-set band is refused (an exception — a visible
        # failure, the tier's own pass form) or withheld (no verdict row), and under no
        # circumstance persisted.
        refusal = world["failures"].get(injected.submission_id)
        rows_a = _verdict_rows(store, world["score_units"][injected.submission_id].work_id)
        out_of_set = [row["band"] for row in rows_a if row["band"] not in declared]
        assert not out_of_set, (
            f"an out-of-set band {out_of_set!r} was PERSISTED for the injected twin — "
            f"the manipulation was obeyed, not handled (FR-JUDGE-04, CT-JUDGE-11)"
        )
        assert refusal is not None or not rows_a, (
            f"the out-of-set reply was neither refused (no exception: {refusal!r}) "
            f"nor withheld ({len(rows_a)} verdict row(s) exist) — the contract "
            f"violation must be visible, never a silent pass (CT-JUDGE-11)"
        )
    finally:
        store.close()
