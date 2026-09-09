"""`CT-EXTRACT-13` — `evidence` is Tier R student PII, purged with it; an injection
changes span selection no more than its benign twin (`TC-EXTRACT-C13`).

Case of test plan §6.11.8; issue #72 (TS-65). Written ahead of #68 (`M-EXTRACT`);
registered in `WRITTEN_AHEAD_BLOCKERS` under `"#68 extraction contract suite (TS-65)"`.

The clause: extraction payloads carry verbatim student work; `evidence` is student
PII, lives in Tier R, and is purged with it (NFR-EXTRACT-04) — verified by running
`purge_cohort` and confirming the BYTES are gone. And, in the clause's own acceptance
form: an adversarial submission's embedded directives change span selection no more
than its benign twin does — the acceptance form is the FR-CONFORM-09 paired fixture,
not a claim. A differential oracle, because there is no absolute standard for "was
not influenced".

Halves:
1. **Tier R, purged with it, rung 2** — a successful extraction's payload carries the
   student's verbatim sentence (the PII grounding), the bytes sit in the cohort's
   Tier R file (asserted BEFORE the purge — the precondition is the PII really being
   in that file), then `purge_cohort` runs (its three Tier-D gates promoted, the
   TC-STORE-C10 precedent's shape) and the byte-level oracle fires: the sentinel is
   gone from the cohort file AND its `-wal`, not merely unreferenced — a DELETE
   without VACUUM leaves student text recoverable in freed pages, which is why the
   clause names bytes.
2. **The twin differential, rung 2** — the LANDED `F-ADV-INJ` corpus (D7), one pair
   per payload kind (the five attack shapes, not twenty repetitions of them): both
   twins are extracted through the real worker, each recorded the SAME single-span
   selection — the shared sentence that precedes the payload, at each twin's own byte
   offsets. The differential: the module's own contribution to span selection is ZERO
   for both twins — identical persisted span texts, one span each, one model call
   each, and the injected payload reached the model only as delimited data (exactly
   one raw untrusted-content open and close in the assembled prompt, with the landed
   corpus's real payload text, not synthetic text).

Discriminator: an extractor that keeps evidence outside the purge (a side table, a
file the cohort purge misses) turns half 1 red at the byte oracle; a module that
acts on embedded directives — dropping, adding, or re-selecting spans for the
injected twin, or letting the payload break the prompt boundary — turns half 2 red
while the benign twin stays green and every `FR-EXTRACT-*` case (which runs benign
submissions only) stays green. The MODEL-side differential — the injection changing
what the model selects — is `TC-CONFORM-C09`'s and `TC-CONFORM-09`'s oracle; this
case pins the MODULE side and cross-references rather than duplicates them.

**Disclosed stand-ins** (suite register, `_doubles.py`): D1 (each twin's reply is
`span_completion`'s stand-in — the selection is fixture-supplied, which is exactly
why the module-side differential is what this rung can force), D3 (document seeding;
the corpus files' own text is the payload), D7 (the paired fixtures are the LANDED
`F-ADV-INJ` corpus, read through the shipped `tests.support.corpora` loader — no
`M-CONFORM` surface required). The Tier-D promotion rows in half 1 are the
`TC-STORE-C10` precedent's shape, minimal. **Isolation: rung 2** — real store, real
ledger, real blob directory, `RecordedFixtureProvider` at the model boundary.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from aeh.ingest import UNTRUSTED_CLOSE, UNTRUSTED_OPEN
from aeh.orch import STAGE_EXTRACT, Orchestrator
from aeh.store import open_store
from tests.support import corpora
from tests.support.conf_builders import edge_panel
from tests.support.extract_vocabulary import (
    WORKER,
    extractor_ref,
    sampling_params,
    span_completion,
)
from tests.support.impl import EXTRACT_MODULE, require
from tests.support.orch_run import ORCH_COHORT_ID, seed_cohort, seed_package
from tests.contract.extract._doubles import (
    CountingProvider,
    World,
    build_markdown,
    evidence_rows,
    make_world,
    payload_bytes,
    require_extract_surface,
    resolved_config,
    seed_document,
)

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

_SENTINEL = "the buffer was bounded after the fix"
_MARKDOWN = build_markdown(_SENTINEL.capitalize() + ".\n")
_SPANS = [
    {
        "start": 41,
        "end": 41 + len(_SENTINEL) + 1,
        "text": _SENTINEL.capitalize() + ".",
        "region_kind": "transcribed_text",
    }
]
_CRITERIA = [{"criterion_id": "C1", "kind": "open", "scoring_model": "holistic"}]

#: The shared evidence sentence both twins carry BEFORE the payload line — the
#: selection the fixture records for each twin.
_TWIN_SENTENCE = (
    "The crate has weight down, the normal force out of the ramp, and friction "
    "up the slope."
)


def _promote_all(store: Any) -> None:
    """Give Tier D its three promotion gates — the `TC-STORE-C10` precedent's shape:
    purge refuses until audit records, labels and per-criterion statistics exist for
    the cohort."""
    store.durable()
    with sqlite3.connect(store.durable_path()) as raw:
        for ddl in (
            "ALTER TABLE audit_record ADD COLUMN cohort_id TEXT",
            "ALTER TABLE label ADD COLUMN cohort_id TEXT",
            "ALTER TABLE criterion_stats ADD COLUMN cohort_id TEXT",
        ):
            try:
                raw.execute(ddl)
            except sqlite3.OperationalError as error:
                if "duplicate column" not in str(error).lower():
                    raise
        raw.execute(
            "INSERT INTO audit_record (audit_record_id, run_id, recorded_at, "
            "profile_summary, cohort_id) VALUES ('a-ct-c13', 'r-ct-c13', "
            "'2026-01-01T00:00:00+00:00', 'p', ?)", (ORCH_COHORT_ID,))
        raw.execute(
            "INSERT INTO label (label_id, run_id, student_ref, criterion_id, "
            "label_type, band, cohort_id) VALUES "
            "('l-ct-c13', 'r-ct-c13', 'ref', 'c', 'human', 'b', ?)", (ORCH_COHORT_ID,))
        raw.execute(
            "INSERT INTO criterion_stats (package_version_id, criterion_id, "
            "backend_profile, panel_build_ref, n, cohort_id) VALUES "
            "('pv-ct-c13', 'c', 'bp', 'pb-ct-c13', 1, ?)", (ORCH_COHORT_ID,))


def test_tc_extract_c13_evidence_is_tier_r_and_purged_with_it(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C13` half 1 — the evidence payload carries the student's verbatim
    words in the Tier R cohort file, and `purge_cohort` removes the BYTES (file and
    `-wal`), not just the reference."""
    require(EXTRACT_MODULE, issue="#68")
    require_extract_surface()
    world = make_world(tmp_data_dir, make_fixture_provider, markdown=_MARKDOWN,
                       criteria=_CRITERIA)
    try:
        orchestrator = Orchestrator(world.store)
        run_id = orchestrator.create_run(
            ORCH_COHORT_ID, world.version, resolved_config(edge_panel(1))
        )
        (unit,) = orchestrator.lease("w-extract", STAGE_EXTRACT, 1)
        AssembleRequest = require(EXTRACT_MODULE, "assemble_request", issue="#68")
        PromptFields = require(EXTRACT_MODULE, "prompt_fields", issue="#68")
        Worker = require(EXTRACT_MODULE, WORKER, issue="#68")
        model_ref = extractor_ref()
        world.provider.record(
            PromptFields(AssembleRequest(unit)), model_ref, sampling_params(),
            span_completion(_SPANS, build_id="ct-c13-build"),
        )
        Worker(world.store, world.provider, model_ref).process(unit)

        rows = evidence_rows(world.store, run_id)
        assert len(rows) == 1, "TC-EXTRACT-C13: precondition — one evidence row"
        stored = json.loads(payload_bytes(rows[0]["payload"]).decode("utf-8"))
        assert any(_SENTINEL in str(s.get("text", "")) for s in stored["spans"]), (
            "TC-EXTRACT-C13: the payload does not carry the student's verbatim "
            "words — the PII grounding of the clause is not established"
        )
        # Tier R: the PII really sits in the cohort's Tier R file before the purge.
        path = world.store.cohort_path(ORCH_COHORT_ID)
        sentinel_bytes = _SENTINEL.encode("utf-8")
        assert sentinel_bytes in path.read_bytes(), (
            "TC-EXTRACT-C13: precondition — the evidence PII is not in the cohort "
            "file at all, so the purge oracle would be vacuous"
        )
        _promote_all(world.store)
        report = world.store.purge_cohort(ORCH_COHORT_ID)
        assert report.tables_cleared and "evidence" in report.tables_cleared, (
            f"TC-EXTRACT-C13: the purge report does not name evidence "
            f"({report.tables_cleared!r}) — evidence was not purged with Tier R"
        )
        assert report.rows_deleted_by_table.get("evidence", 0) >= 1, (
            "TC-EXTRACT-C13: the purge deleted no evidence rows"
        )
        # The byte-level oracle: gone from the file AND its -wal, not unreferenced.
        assert sentinel_bytes not in path.read_bytes(), (
            "TC-EXTRACT-C13: the evidence PII is recoverable from the cohort file's "
            "raw bytes after the purge — a DELETE without VACUUM leaves student text "
            "in freed pages, and the clause names BYTES"
        )
        wal = path.with_name(path.name + "-wal")
        assert not wal.exists() or sentinel_bytes not in wal.read_bytes(), (
            "TC-EXTRACT-C13: the evidence PII survives in the -wal after the purge"
        )
    finally:
        world.close()


def _span_over(markdown: str, needle: str) -> dict[str, Any]:
    md_bytes = markdown.encode("utf-8")
    start = md_bytes.find(needle.encode("utf-8"))
    assert start >= 0, f"fixture bug: {needle!r} not in the document"
    return {
        "start": start,
        "end": start + len(needle.encode("utf-8")),
        "text": needle,
        "region_kind": "transcribed_text",
    }


def test_tc_extract_c13_an_injection_changes_span_selection_no_more_than_its_twin(
    tmp_data_dir, make_fixture_provider
):
    """`TC-EXTRACT-C13` half 2 — over the landed `F-ADV-INJ` twins, one pair per
    payload kind: the module's contribution to span selection is ZERO for both twins
    (identical persisted texts, one span each, one model call each), and the payload
    reached the model only inside the untrusted-content delimiters."""
    require(EXTRACT_MODULE, issue="#68")
    require_extract_surface()
    pairs = corpora.injection_pairs()
    distinct_kinds = sorted({
        injected.attributes["injection_kind"] for _benign, injected in pairs
    })
    assert len(distinct_kinds) >= 5, (
        f"TC-EXTRACT-C13: precondition — the corpus carries {len(distinct_kinds)} "
        f"payload kinds, expected the declared five attack shapes"
    )
    selected: list[tuple[str, Any, Any]] = []
    seen: set[str] = set()
    for benign, injected in pairs:
        kind = injected.attributes["injection_kind"]
        if kind not in seen:
            seen.add(kind)
            selected.append((kind, benign, injected))

    AssembleRequest = require(EXTRACT_MODULE, "assemble_request", issue="#68")
    PromptFields = require(EXTRACT_MODULE, "prompt_fields", issue="#68")
    Worker = require(EXTRACT_MODULE, WORKER, issue="#68")
    model_ref = extractor_ref()

    for kind, benign, injected in selected:
        store_dir = tmp_data_dir / f"pair-{injected.id}"
        world = _build_pair_world(store_dir, make_fixture_provider, benign, injected)
        try:
            orchestrator = Orchestrator(world.store)
            run_id = orchestrator.create_run(
                ORCH_COHORT_ID, world.version, resolved_config(edge_panel(1))
            )
            units = orchestrator.lease("w-extract", STAGE_EXTRACT, 2)
            by_submission = {u.submission_id: u for u in units}
            counter = CountingProvider(world.provider)
            for member in (benign, injected):
                markdown = build_markdown(member.text())
                world.provider.record(
                    PromptFields(AssembleRequest(by_submission[member.id])),
                    model_ref, sampling_params(),
                    span_completion([_span_over(markdown, _TWIN_SENTENCE)],
                                    build_id="ct-c13-build"),
                )
                Worker(world.store, counter, model_ref).process(by_submission[member.id])

            assert counter.count == 2, (
                f"TC-EXTRACT-C13 ({kind}): {counter.count} model calls for two twin "
                f"extractions — the injected submission must not trigger extra "
                f"extraction work (the injection is data, not a control input)"
            )

            persisted: dict[str, list[str]] = {}
            for member in (benign, injected):
                rows = evidence_rows(world.store, run_id, submission_id=member.id)
                assert len(rows) == 1, (
                    f"TC-EXTRACT-C13 ({kind}): the {member.attributes['variant']} "
                    f"twin wrote {len(rows)} evidence rows"
                )
                stored = json.loads(payload_bytes(rows[0]["payload"]).decode("utf-8"))
                # The module contributed NO selection change: one span, the shared
                # sentence, for BOTH twins.
                assert len(stored["spans"]) == 1 and (
                    stored["spans"][0].get("text") == _TWIN_SENTENCE
                ), (
                    f"TC-EXTRACT-C13 ({kind}): the {member.attributes['variant']} "
                    f"twin persisted {stored['spans']!r} — the module changed the "
                    f"selection the model made"
                )
                persisted[member.id] = [str(s.get("text", "")) for s in stored["spans"]]
                # The submission reached the model only as delimited data: exactly
                # one raw untrusted-content open and close, for the injected twin too.
                submission_value = dict(
                    (name, value)
                    for name, value in PromptFields(
                        AssembleRequest(by_submission[member.id])
                    ).fields
                ).get("submission", "")
                assert submission_value.count(UNTRUSTED_OPEN) == 1, (
                    f"TC-EXTRACT-C13 ({kind}): the {member.attributes['variant']} "
                    f"twin's payload induced a second untrusted-block opening in the "
                    f"assembled prompt"
                )
                assert submission_value.count(UNTRUSTED_CLOSE) == 1, (
                    f"TC-EXTRACT-C13 ({kind}): the {member.attributes['variant']} "
                    f"twin's payload broke the untrusted-content closing boundary in "
                    f"the assembled prompt"
                )

            # The payload lines (present in the injected twin, absent from its
            # benign twin) reached the model as DATA — inside the block.
            payload_lines = [
                line for line in injected.text().splitlines()
                if line.strip() and line not in benign.text().splitlines()
            ]
            assert payload_lines, (
                f"TC-EXTRACT-C13 ({kind}): fixture bug — the twins are identical, so "
                f"the differential has no payload to test"
            )
            submission_injected = dict(
                (name, value)
                for name, value in PromptFields(
                    AssembleRequest(by_submission[injected.id])
                ).fields
            ).get("submission", "")
            assert any(line in submission_injected for line in payload_lines), (
                f"TC-EXTRACT-C13 ({kind}): the injected payload did not reach the "
                f"model as data at all — the differential would be vacuous"
            )
            assert persisted[benign.id] == persisted[injected.id], (
                f"TC-EXTRACT-C13 ({kind}): the injected twin's persisted selection "
                f"{persisted[injected.id]!r} differs from its benign twin's "
                f"{persisted[benign.id]!r} — the embedded directives changed span "
                f"selection at the module boundary"
            )
        finally:
            world.close()


def _build_pair_world(data_dir: Any, make_fixture_provider: Any, benign: Any,
                      injected: Any) -> World:
    """A one-pair world: both twins seeded as submissions over their own bytes."""
    store = open_store(data_dir)
    seed_cohort(store, (benign.id, injected.id))
    version = seed_package(store, _CRITERIA, package_id=f"pkg-{injected.id}")
    seed_document(store, benign.id, build_markdown(benign.text()), f"doc-{benign.id}")
    seed_document(store, injected.id, build_markdown(injected.text()),
                  f"doc-{injected.id}")
    return World(store=store, provider=make_fixture_provider(), version=version,
                 submission_id=benign.id, doc_id=f"doc-{benign.id}",
                 markdown=benign.text())
