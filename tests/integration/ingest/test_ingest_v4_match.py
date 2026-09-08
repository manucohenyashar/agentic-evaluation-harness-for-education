"""V4: the three-valued assessment match, the recorded signals, the cohort breaker (`M-INGEST`).

Cases `TC-INGEST-25` (the decision table), `-28` (the breaker boundary), `-39` (the
proposal) and `ADV-07` (the fingerprint attack) of test plan §5.5/§6.6 (TS-17, issue
#46), against the V4 #41 landed. Rung 2 — real SQLite, real blob directory; the VLM
is a scripted double that dispatches per call kind (transcription payloads carry
`page_no`; ADR-7's escalation payload does not). `Written ahead of implementation:
yes` is stale for V4 itself — #41 shipped it; these cases run green by design.

The decision table's five cells are the plan's §6.6 table verbatim. The semantic
signal needs exactly one assessment lineage in the store, which shapes the fixtures:
cell (b)'s "clearly assessment B" is a one-question paper against a two-question
package — identifier, structural and semantic all mismatch, no V2 contradiction (Q1
is declared and its shape is `open`). Cell (e) is fixed by the implementation as
`match` (absent identifier and structural agreement with matching semantics decide
nothing against it); the plan allowed `match` or `uncertain` provided the design
declares one — `match` is asserted exactly, as declared.

Finding disclosed here rather than shipped red (**F6**, probe-backed): **the
proposal's ranked-candidates promise cannot list more than one candidate.** A
proposal is built only for a `mismatch` (FR-INGEST-26), and a `mismatch` requires
all three decisive signals to mismatch — but the semantic signal is `absent`
whenever the store holds two assessment lineages (the module refuses to guess
between two papers), which caps the outcome at `uncertain`, which builds no
proposal. Probe: two stored assessments; a submission printing the second's
identifier with a three-question shape → outcome `uncertain`, zero proposal rows.
`TC-INGEST-39`'s "two plausible candidates" fixture is therefore unimplementable as
specified; the proposal row, its ranking, and the schema distinction from an
assignment are pinned with the one reachable candidate, and the two-candidate half
waits on the design's answer (a semantic signal that discriminates between
lineages, or a proposal path from `uncertain`).

One fixture-order note the development itself surfaced: the store's tier migrations
are contributed per module at import time, so a Tier P file opened before
`aeh.pkg` is imported builds with the base schema only and the failure surfaces
later as a bare `no such column`. This file imports `aeh.pkg` at module top — the
same order every catalog-touching suite in the repo already follows.
"""

from __future__ import annotations

import json

import pytest

from aeh.conf import ModelRef
from aeh.ingest import (
    IngestCohortBreakerTripped,
    Ingestor,
    PageImage,
    PdfSanitizer,
    ResidencySlot,
    SanitizeResult,
)
from aeh.pkg import PackageCatalog, PackageDraft
from aeh.prov import Completion, SamplingParams
from aeh.store import open_store

pytestmark = pytest.mark.integration

ISSUE = "#46"
PACKAGE_ID = "pkg-v4"
COHORT = "c-v4"

A_QUESTION_1 = "explain the water cycle from evaporation to rainfall"
A_QUESTION_2 = "describe how forces balance on a stationary bridge"
MATCH_ANSWER_1 = "the water cycle moves water by evaporation then rainfall"
MATCH_ANSWER_2 = "the forces on a stationary bridge balance to zero"
MISMATCH_ANSWER_1 = "medieval kingdoms traded silk plus spices"
MISMATCH_ANSWER_2 = "kings held courts where scribes recorded taxes"


def _model() -> ModelRef:
    return ModelRef(role="transcriber", provider="local",
                    build_id="vlm@sha256:cccc", quantization="q4")


class ThroughSanitizer(PdfSanitizer):
    """The fast-tier sanitizer double: no constructs, the bytes pass through."""

    def sanitize(self, pdf_bytes, *, strip=True, **kwargs):
        return SanitizeResult(pdf_bytes=pdf_bytes)


class ScriptedRasterizer:
    """One page per source, every rasterization recorded."""

    def __init__(self) -> None:
        self.calls: list[bytes] = []

    def rasterize(self, pdf_bytes: bytes, dpi: int) -> list[PageImage]:
        self.calls.append(bytes(pdf_bytes))
        return [PageImage(page_no=1, png=b"page", width_px=100, height_px=140)]

    def crop(self, pdf_bytes: bytes, page_no: int, box, dpi: int) -> bytes:
        return b"crop"

    def text_layer(self, pdf_bytes: bytes, page_no: int) -> str:
        return ""


class V4Provider:
    """Dispatches per payload kind: transcription calls carry `page_no`; the
    escalation payload (ADR-7) does not. Every call is recorded by kind."""

    def __init__(self, escalation_reply: str = "uncertain") -> None:
        self.texts: dict = {}
        self.escalation_reply = escalation_reply
        self.escalations: list[dict] = []

    def complete(self, prompt, model_ref, params) -> Completion:
        fields = dict(prompt.fields)
        if "page_no" in fields:
            key = (fields["source_blob_hash"], int(fields["page_no"]))
            text = self.texts.get(key, "plain page")
        else:
            self.escalations.append({
                "assessment": fields.get("assessment"),
                "transcript_len": len(fields.get("submission_transcript", "")),
            })
            text = self.escalation_reply
        return Completion(text=text, tokens_in=1, tokens_out=1, latency_ms=1,
                          resolved_build=model_ref.build_id,
                          cached_prefix_tokens=0, cost=None)


class _V4:
    """One store, one cohort, one package (Q1/Q2 declared `open`), one assessment
    artifact, and the ingestor over them — the assessment artifact is the lineage
    the semantic signal compares against."""

    def __init__(self, tmp_data_dir, name: str) -> None:
        self.root = tmp_data_dir / f"v46-{name}"
        self.store = open_store(self.root)
        self.blobs = self.store.blobs()
        self.handle = self.store.cohort(COHORT)
        with self.handle.transaction() as tx:
            tx.execute("INSERT OR IGNORE INTO cohort (cohort_id, consent_class, "
                       "created_at) VALUES (:c, 'synthetic', 'x')", c=COHORT)
            tx.execute("INSERT INTO roster (cohort_id, student_ref) "
                       "VALUES (:c, 'amara-o')", c=COHORT)
        seed = self.store.package(PACKAGE_ID)
        with seed.transaction() as tx:
            tx.execute("INSERT INTO package (package_id, created_at) "
                       "VALUES (:p, 'x')", p=PACKAGE_ID)
        self.catalog = PackageCatalog(seed, package_id=PACKAGE_ID)
        self.version = self.catalog.create_version(None, PackageDraft(title="v4"))
        self.catalog.add_criterion(self.version, "C1", question_id="Q1",
                                   kind="open", max_points=4.0)
        self.catalog.add_criterion(self.version, "C2", question_id="Q2",
                                   kind="open", max_points=4.0)
        self.rasterizer = ScriptedRasterizer()
        self.provider = V4Provider()
        self.ingestor = Ingestor(self.handle, self.blobs, self.provider,
                                 _model(), SamplingParams(temperature=0.0),
                                 self.rasterizer,
                                 residency=ResidencySlot.for_policy(
                                     ("transcriber",)),
                                 sanitizer=ThroughSanitizer())

    def put_assessment(self, printed: str = "Assessment Alpha") -> str:
        """The store's one assessment artifact: the questions the semantic signal
        compares against, with its own identifier header for the proposal."""
        source = self.blobs.put(printed.encode())
        self.provider.texts[(source, 1)] = (
            f"Assessment: {printed}\n"
            f"<!-- region: kind=transcribed_text question_id=Q1 -->\n"
            f"{A_QUESTION_1}\n<!-- /region -->\n"
            f"<!-- region: kind=transcribed_text question_id=Q2 -->\n"
            f"{A_QUESTION_2}\n<!-- /region -->")
        return self.ingestor.ingest_document(
            [source], kind="assessment", filenames={source: "assessment.md"})

    def put_submission(self, printed: str | None, answers: dict[str, str],
                       tag: str) -> str:
        """`printed` is the paper's declared 'Assessment:' line (None for absent);
        `answers` maps question ids to answer bodies."""
        head = f"Assessment: {printed}\n" if printed else ""
        regions = "\n".join(
            f"<!-- region: kind=transcribed_text question_id={question_id} "
            f"state=present -->\n{body}\n<!-- /region -->"
            for question_id, body in answers.items())
        source = self.blobs.put(f"sub-{tag}".encode())
        self.provider.texts[(source, 1)] = f"{head}Student: amara-o\n{regions}"
        return source

    def submit(self, source: str, name: str = "scan-01.md"):
        return self.ingestor.ingest_submission(
            [source], cohort_id=COHORT, package_version=self.version,
            package_catalog=self.catalog, filenames={source: name})

    def signals_of(self, submission_id: str) -> dict:
        return json.loads(self.handle.query(
            "SELECT v4_signals FROM submission WHERE submission_id = :s",
            s=submission_id)[0]["v4_signals"])

    def proposals(self) -> list:
        return self.handle.query("SELECT * FROM assessment_match_proposal")

    def breaker(self) -> dict | None:
        return self.ingestor.cohort_breaker(COHORT)

    def close(self) -> None:
        self.store.close()


# -- TC-INGEST-25: the decision table over the four signals ----------------------------------------


@pytest.mark.parametrize("cell", ["a", "b", "c", "d", "e"])
def test_tc_ingest_25_the_decision_table_over_the_four_signals(tmp_data_dir, cell):
    """`TC-INGEST-25` — the plan's five cells, exact `v4_match` per cell, every
    fired signal recorded on the row (`FR-INGEST-27`), the escalation exactly where
    the deterministic band puts it (ADR-7: one call in `uncertain`, none otherwise),
    and scoring halted for both non-match outcomes."""
    fx = _V4(tmp_data_dir, f"table-{cell}")
    fx.put_assessment()
    printed, answers = {
        "a": (PACKAGE_ID, {"Q1": MATCH_ANSWER_1, "Q2": MATCH_ANSWER_2}),
        "b": ("History Final", {"Q1": MISMATCH_ANSWER_1}),
        "c": ("Something Else", {"Q1": MATCH_ANSWER_1, "Q2": MATCH_ANSWER_2}),
        "d": (None, {"Q1": MISMATCH_ANSWER_1, "Q2": MISMATCH_ANSWER_2}),
        "e": (None, {"Q1": MATCH_ANSWER_1, "Q2": MATCH_ANSWER_2}),
    }[cell]
    source = fx.put_submission(printed, answers, tag=f"cell-{cell}")
    report = fx.submit(source)

    expected = {"a": "match", "b": "mismatch", "c": "uncertain",
                "d": "uncertain", "e": "match"}[cell]
    assert report.gates["v4"] == expected, (
        f"TC-INGEST-25 cell ({cell}): the three-valued outcome is declared, not "
        f"inferred — got {report.gates['v4']!r}, expected {expected!r}.")
    if expected == "match":
        assert report.ingest_status == "ok", (
            "TC-INGEST-25: a match does not halt scoring.")
        assert fx.proposals() == []
    else:
        assert report.ingest_status == "unmatched_assessment", (
            f"TC-INGEST-25 cell ({cell}): both `uncertain` and `mismatch` halt "
            "scoring for the submission (FR-INGEST-25).")
    assert len(fx.provider.escalations) == (1 if expected == "uncertain" else 0), (
        f"TC-INGEST-25 cell ({cell}): the model-assisted path runs only in the "
        "uncertain band, exactly once (ADR-7).")

    # The escalation's verdict is RECORDED, and in cell (c) the reply is the one
    # word a naive parser gets backwards: "mismatch" contains "match", so a
    # match-first substring scan reads it as a match — the recorded verdict must
    # be the reply's own word (the implementation's longest-candidate-first rule).
    if cell == "c":
        fx.provider.escalation_reply = "mismatch"
        source = fx.put_submission(printed, answers, tag="cell-c-reply")
        report = fx.submit(source)
        recorded_verdict = fx.signals_of(
            report.submission_id)["semantic_escalation"]["verdict"]
        assert recorded_verdict == "mismatch", (
            "TC-INGEST-25: the escalation's recorded verdict must be the reply's "
            f"own word, got {recorded_verdict!r} — a match-first substring scan "
            "reads 'mismatch' as 'match', exactly backwards in the uncertain "
            "band (ADR-7).")

    # FR-INGEST-27: every signal that fired is recorded — on the ROW, not just the
    # report, so the operator sees why (the record the console reads).
    recorded = fx.signals_of(report.submission_id)
    for family in ("identifier", "structural", "semantic", "roster_context"):
        assert family in recorded, (
            f"TC-INGEST-25 cell ({cell}): the {family} signal fired but is not "
            "recorded on the submission (FR-INGEST-27).")
    assert recorded["outcome"] == expected
    if expected == "uncertain":
        escalation = recorded["semantic_escalation"]
        assert escalation["parsed"] is True, (
            "TC-INGEST-25: the escalation's verdict is recorded, parsed (ADR-7).")
    fx.close()


# -- TC-INGEST-28: the breaker boundary ------------------------------------------------------------


@pytest.mark.parametrize(("submissions", "flagged_positions", "trips"),
                         [(19, range(19), False), (20, range(3), False),
                          (20, range(4), True), (21, (0, 1, 2, 20), False)],
                         ids=["19x100%", "20x15%", "20x20%", "21x19%"])
def test_tc_ingest_28_the_breaker_trips_at_its_declared_boundary(
        tmp_data_dir, submissions, flagged_positions, trips):
    """`TC-INGEST-28` — the breaker trips only at or above 20% **and** at or above
    the 20-submission minimum, from both sides of each threshold (the plan's
    19/20/21% over 19/20/21 matrix at integral counts). The rate is evaluated over
    the cohort as each submission lands, so a cell's flag positions encode when the
    running rate crosses: `21x19%` holds its fourth flag to the 21st ingest — 3/20
    at the minimum boundary, then 4/21 = 19.05% — because a 20%-crossing at the
    20th ingest is the `20x20%` cell, not a dilution. (A 5-of-21 cohort is
    therefore not a separate cell: it necessarily passes through the 20% state at
    the 20th ingest, which is the crossing the trip asserts.)

    On tripping, the crossing call completes, the next ingest is refused before any
    cost, and exactly ONE cohort-level finding exists — one breaker row, not one
    triage item per submission."""
    fx = _V4(tmp_data_dir, f"breaker-{submissions}x{len(list(flagged_positions))}")
    fx.put_assessment()
    # A flagged submission is a true mismatch on all three decisive signals: a
    # foreign identifier printed, a short inventory, disjoint answers.
    mismatch_shape = ("History Final", {"Q1": MISMATCH_ANSWER_1})
    match_shape = (PACKAGE_ID, {"Q1": MATCH_ANSWER_1, "Q2": MATCH_ANSWER_2})
    flagged = set(flagged_positions)
    crossing = None
    for index in range(submissions):
        is_flagged = index in flagged
        printed, answers = mismatch_shape if is_flagged else match_shape
        source = fx.put_submission(printed, answers,
                                   tag=f"b{submissions}-{index}")
        report = fx.submit(source, name=f"scan-{index:02d}.md")
        if is_flagged:
            assert report.gates["v4"] == "mismatch", (
                "TC-INGEST-28: a flagged fixture must land in the flagged count.")
        if index == submissions - 1:
            crossing = report

    tripped = fx.breaker()
    if trips:
        assert tripped is not None, (
            f"TC-INGEST-28: {len(flagged)} of {submissions} must trip the breaker "
            "(at or above both the 20% rate and the 20-submission minimum).")
    else:
        assert tripped is None, (
            f"TC-INGEST-28: {len(flagged)} of {submissions} must not trip the "
            "breaker — below one of the two thresholds.")
    if not trips:
        assert crossing is not None
        assert fx.handle.query(
            "SELECT COUNT(*) AS n FROM v4_cohort_breaker")[0]["n"] == 0, (
            "TC-INGEST-28: no breaker row may exist below the boundary.")
        assert not any(f.get("cohort") for f in crossing.detail["findings"]), (
            "TC-INGEST-28: a cohort below the boundary must surface no "
            "cohort-level finding — one finding per crossing, not finding spam "
            "on every ingest.")
        fx.close()
        return

    # The crossing call surfaces ONE cohort-level finding, and the finding says so.
    cohort_findings = [f for f in crossing.detail["findings"] if f.get("cohort")]
    assert len(cohort_findings) == 1, (
        "TC-INGEST-28: exactly one cohort-level finding is surfaced — not one "
        f"triage item per submission, got {len(cohort_findings)}.")
    assert "ONE cohort-level finding" in cohort_findings[0]["finding"]
    # Exactly one breaker row — the schema's primary key makes it a property, not
    # caller discipline.
    rows = fx.handle.query("SELECT * FROM v4_cohort_breaker")
    assert len(rows) == 1, (
        "TC-INGEST-28: the breaker table holds exactly one row for the cohort "
        f"(FR-INGEST-28), got {len(rows)}.")
    preflight = fx.breaker()
    assert preflight is not None and preflight["flagged"] == len(flagged), (
        "TC-INGEST-28: the preflight read — the path that withholds run start "
        "(FR-CONSOLE-28) — returns the tripped breaker with its counts.")

    # Ingestion is halted: the next submission is refused before any cost.
    rasters_before = len(fx.rasterizer.calls)
    escalations_before = len(fx.provider.escalations)
    source = fx.put_submission(*match_shape, tag="after-trip")
    with pytest.raises(IngestCohortBreakerTripped):
        fx.submit(source, name="scan-after.md")
    assert len(fx.rasterizer.calls) == rasters_before, (
        "TC-INGEST-28: the refused ingestion rasterized nothing — halted before "
        "any cost.")
    assert len(fx.provider.escalations) == escalations_before
    fx.close()


# -- TC-INGEST-39: the proposal is a record, never an assignment -----------------------------------


def test_tc_ingest_39_the_proposal_is_a_record_never_an_assignment(tmp_data_dir):
    """`TC-INGEST-39` — a mismatched submission records a ranked proposal; nothing
    applies it. The row's resolution columns stay empty for the human, the
    submission keeps its own `mismatch`, and the module exposes no assignment path.

    The plan's fixture asks for **two** plausible candidates; this module
    docstring's F6 says why that cannot exist yet: a second assessment lineage
    makes the semantic signal `absent`, the outcome `uncertain`, and no proposal is
    built at all, so the ranked-candidates promise cannot list more than the one
    reachable candidate. Pinned here with one; the two-candidate half needs the
    design's answer."""
    fx = _V4(tmp_data_dir, "proposal")
    assessment_id = fx.put_assessment()
    source = fx.put_submission("History Final", {"Q1": MISMATCH_ANSWER_1},
                               tag="proposal")
    report = fx.submit(source)
    assert report.gates["v4"] == "mismatch"

    proposals = fx.proposals()
    assert len(proposals) == 1, (
        "TC-INGEST-39: the mismatch records exactly one proposal row.")
    proposal = proposals[0]
    assert proposal["submission_id"] == report.submission_id
    assert proposal["resolution"] is None and proposal["resolved_at"] is None, (
        "TC-INGEST-39: the resolution columns are the human's — the ladder never "
        "writes them (FR-INGEST-26).")
    candidates = json.loads(proposal["candidates"])
    assert candidates, "TC-INGEST-39: the proposal carries ranked candidates."
    scores = [candidate["score"] for candidate in candidates]
    assert scores == sorted(scores, reverse=True), (
        "TC-INGEST-39: the candidates are RANKED by score.")
    assert candidates[0]["assessment_document_id"] == assessment_id, (
        "TC-INGEST-39: the store's assessment artifact is the candidate.")
    assert candidates[0]["identifier"] == "Assessment Alpha", (
        "TC-INGEST-39: the candidate names the artifact it points at.")

    # The schema distinction: the proposal is the only submission→assessment link
    # the module can write, and nothing on the submission was reassigned.
    row = fx.handle.query("SELECT v4_match, student_ref FROM submission "
                          "WHERE submission_id = :s",
                          s=report.submission_id)[0]
    assert row["v4_match"] == "mismatch", (
        "TC-INGEST-39: the submission keeps its own verdict — a proposal is not "
        "an applied assignment (FR-INGEST-26).")
    reassigning = [name for name in dir(Ingestor)
                   if any(word in name.lower()
                          for word in ("assign", "reassign", "rebind",
                                       "apply", "adopt", "promote"))]
    assert reassigning == [], (
        f"TC-INGEST-39: no method reassigns a submission — found {reassigning!r}.")
    fx.close()


# -- ADV-07: a fingerprinted paper is never graded against the wrong key ---------------------------


def test_adv_07_a_fingerprinted_paper_is_never_graded_against_the_wrong_key(
        tmp_data_dir):
    """`ADV-07` — both attacks on the assessment match: a paper for assessment B
    formatted to fingerprint as A (B's identifier, A's structure), and a paper with
    A's identifier and B's content. Neither is graded: the outcome is `uncertain`
    (exactly, with the differing signal profiles the two attacks produce), scoring
    halts, the signals are recorded, and nothing is reassigned."""
    fx = _V4(tmp_data_dir, "adv-07")
    fx.put_assessment()

    # Attack 1 — B's paper, A's fingerprint: B's identifier printed, A's question
    # inventory and region shapes, B's subject matter in the answers.
    attack_one = fx.put_submission("History Final",
                                   {"Q1": MISMATCH_ANSWER_1,
                                    "Q2": MISMATCH_ANSWER_2}, tag="adv-1")
    report = fx.submit(attack_one, name="adv-1.md")
    signals = fx.signals_of(report.submission_id)
    assert report.gates["v4"] in ("uncertain", "mismatch"), (
        "ADV-07: a fingerprinted paper must not match (FR-INGEST-25).")
    assert report.gates["v4"] == "uncertain", (
        "ADV-07: with the identifier refusing and the fingerprint agreeing, the "
        "declared band is `uncertain`.")
    assert report.ingest_status == "unmatched_assessment", (
        "ADV-07: scoring is halted for the fingerprinted paper.")
    assert signals["identifier"]["signal"] == "mismatch", (
        "ADV-07: the printed identifier refused — the signal that caught the "
        "attack is recorded.")
    assert signals["structural"]["signal"] == "match", (
        "ADV-07: the fingerprint held — recorded, so the operator sees the "
        "mimicry.")
    assert signals["semantic"]["signal"] == "mismatch"
    assert len(fx.provider.escalations) == 1, (
        "ADV-07: the uncertain band takes its one model-assisted look (ADR-7).")
    assert fx.proposals() == [], (
        "ADV-07: an `uncertain` outcome proposes nothing — and reassigns nothing.")

    # Attack 2 — A's identifier, B's content: the identifier signal agrees, the
    # semantics refuse. The two attacks are distinguished by their signals.
    attack_two = fx.put_submission(PACKAGE_ID,
                                   {"Q1": MISMATCH_ANSWER_1,
                                    "Q2": MISMATCH_ANSWER_2}, tag="adv-2")
    report = fx.submit(attack_two, name="adv-2.md")
    signals = fx.signals_of(report.submission_id)
    assert report.gates["v4"] == "uncertain"
    assert report.ingest_status == "unmatched_assessment"
    assert signals["identifier"]["signal"] == "match", (
        "ADV-07: the stolen identifier passes — recorded, not decisive alone.")
    assert signals["semantic"]["signal"] == "mismatch", (
        "ADV-07: B's content against A's questions is what refuses this paper.")
    assert fx.handle.query(
        "SELECT COUNT(*) AS n FROM assessment_match_proposal")[0]["n"] == 0, (
        "ADV-07: no reassignment was applied under either attack.")
    fx.close()
