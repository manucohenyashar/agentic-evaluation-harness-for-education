"""`TS-78` (issue #151) — `Requires` pairwise integration into **`M-PROV`**: every consumer's
assumption about the provider boundary, checked against a real provider implementation.

Test plan §6.13, grouped one suite per provider module (§4.10). The live implementation
(`LocalServerProvider`) runs over a capturing transport, the `FR-PROV-15` seam, so each case reads
the **dispatched bytes**, the JSON body the provider actually sends. The consumer clauses these rows
cite (`CT-EXTRACT-06`, `CT-JUDGE-08/09/17`) hold only if they survive the wire.

| Case | Consumer | Assumption checked here |
|---|---|---|
| TC-REQ-04 | `M-INGEST` | one call per page, `transcriber_ref` records the served build, retry is the provider's |
| TC-REQ-10 | `M-SETUP` | the proposal payload is dispatched byte-identically as assembled |
| TC-REQ-14 | `M-ORCH` | a terminal provider error pauses the run, with no fallback; a cost estimate exists before dispatch |
| TC-REQ-19 | `M-EXTRACT` | the submission-last ordering holds on the dispatched bytes |
| TC-REQ-30 | `M-JUDGE` | a byte-identical prefix and the submission last on the wire; no re-sampling; no reproducibility assumed |
| TC-REQ-44 | `M-SYNTH` | one call per unit, the payload dispatched as assembled, no re-sampling of a parsed output |
| TC-REQ-67 | `M-CALIB` | an unavailable off-panel model raises rather than falling back onto the panel |
| TC-REQ-71 | `M-CONFORM` | the implementations are substitutable, the fixture provider is hermetic, text is never compared |

Markers: `contract` and `integration` (§4.7).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from aeh.prov import HttpResponse, LocalServerProvider, SamplingParams
from aeh.store import open_store
from tests.support.orch_run import ORCH_COHORT_ID, seed_run
from tests.support.prov_contract import CountingClock, flat_ok

pytestmark = [pytest.mark.contract, pytest.mark.integration]


@dataclass
class WireTransport:
    """A transport that answers each POST through `reply(fields)` and keeps every dispatched body.

    `script` holds responses (or exceptions) served first, one per attempt, before `reply` is
    consulted. That is how a retry is programmed."""

    reply: object
    build: str = "served-build-7"
    script: list = field(default_factory=list)
    bodies: list = field(default_factory=list)
    attempts: int = 0

    def send(self, request):
        if request.method != "POST":
            return HttpResponse(200, {}, b"{}")
        self.attempts += 1
        if self.script:
            outcome = self.script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        body = json.loads(request.body.decode("utf-8")) if isinstance(request.body, bytes) else request.body
        self.bodies.append(body)
        return flat_ok(text=self.reply([tuple(f) for f in body["prompt"]["fields"]]), build=self.build)

    def fields(self):
        return [[tuple(f) for f in body["prompt"]["fields"]] for body in self.bodies]


def wire_provider(transport: WireTransport) -> LocalServerProvider:
    return LocalServerProvider(base_url="http://local/v1", transport=transport, clock=CountingClock())


# -- TC-REQ-04 ----------------------------------------------------------------------------------


def test_tc_req_04_ingest_makes_one_call_per_page_and_records_the_served_build(tmp_data_dir):
    """`TC-REQ-04` (`M-INGEST` → `M-PROV`, CT-PROV-01/03/06/07): a three-page document is ingested
    through the real `Ingestor` and a real provider. The provider is dispatched exactly one
    completion per page, and the first page's transport failure is retried inside the provider,
    not by ingest. The document's `transcriber_ref` records the build the response reported
    (`served-build-7`), not the build ingest requested."""
    from aeh.conf import ModelRef
    from aeh.ingest import Ingestor, PageImage, ResidencySlot
    from aeh.prov import TransportError
    from tests.support.setup_harness import ScriptedRasterizer, ScriptedSanitizer

    class ThreePages(ScriptedRasterizer):
        def rasterize(self, pdf_bytes, dpi):
            self.calls += 1
            return [PageImage(page_no=n, png=b"page-%d" % n, width_px=1000, height_px=1400)
                    for n in (1, 2, 3)]

    import itertools

    page_numbers = itertools.count(1)

    def distinct_page(fields):
        # Each page reads differently, so the duplicate-page gate (FR-INGEST-08) stays quiet.
        n = next(page_numbers)
        return f"Page {n}. " + " ".join(f"topic{n}term{i}" for i in range(40))

    transport = WireTransport(reply=distinct_page,
                              script=[TransportError("connection reset on page one")])
    requested = ModelRef(role="transcriber", provider="local", build_id="requested-build-3",
                         quantization="q4")
    store = open_store(tmp_data_dir)
    try:
        ingestor = Ingestor(store.cohort("c-setup"), store.blobs(), wire_provider(transport),
                            requested, SamplingParams(temperature=0.0), ThreePages(),
                            residency=ResidencySlot.for_policy(("transcriber",)),
                            sanitizer=ScriptedSanitizer())
        source = store.blobs().put(b"three page assessment")
        document_id = ingestor.ingest_document([source], kind="assessment",
                                               filenames={source: "a.pdf"})
        row = store.cohort("c-setup").query(
            "SELECT transcriber_ref FROM document WHERE document_id = :d", d=document_id)[0]
    finally:
        store.close()
    assert len(transport.bodies) == 3, f"{len(transport.bodies)} completions for three pages"
    assert transport.attempts == 4, f"the transport failure was not retried once: {transport.attempts}"
    assert "served-build-7" in row["transcriber_ref"] and "requested-build-3" not in row["transcriber_ref"], (
        f"transcriber_ref records {row['transcriber_ref']!r}, not the build that answered")


# -- TC-REQ-10 ----------------------------------------------------------------------------------


def test_tc_req_10_the_setup_proposal_payload_is_dispatched_as_assembled(tmp_data_dir):
    """`TC-REQ-10` (`M-SETUP` → `M-PROV`, CT-PROV-01/05/07): M-SETUP's inventory proposal is an
    ordinary completion. The fields on the wire are exactly the pinned instruction followed by the
    document's transcript: byte-identical, in order, nothing added. A pinned template is
    therefore a pinned prompt."""
    import aeh.setup as setup
    from tests.support.setup_harness import INVENTORY_REPLY, ingest_document, stage_chain

    chain = stage_chain(tmp_data_dir)
    try:
        assessment = ingest_document(chain.store)
        transport = WireTransport(reply=lambda fields: INVENTORY_REPLY)
        service = setup.SetupService(chain.catalog, chain.ingestor, wire_provider(transport),
                                     setup.ModelRef(role="extractor", provider="local",
                                                    build_id="setup-build", quantization="q4"))
        service.propose_inventory(assessment)
        transcript = chain.ingestor.read_document(assessment)
    finally:
        chain.store.close()
    assert transport.fields() == [[("instruction", setup._INVENTORY_INSTRUCTION),
                                   ("assessment_transcript", transcript)]], (
        "the dispatched proposal differs from the assembled payload")


# -- TC-REQ-14 ----------------------------------------------------------------------------------


@pytest.mark.parametrize("terminal", ["ProviderUnavailableError", "BuildChangedError"])
def test_tc_req_14_a_terminal_provider_error_pauses_the_run_without_a_fallback(
    tmp_data_dir, terminal
):
    """`TC-REQ-14` (`M-ORCH` → `M-PROV`, CT-PROV-07/08/09, CT-ORCH-12): the run's single
    model-call seam raises a terminal error from M-PROV's taxonomy.

    1. **It surfaces rather than degrades.** The dispatch pass raises the error, and no score unit
       is completed by anything else, because there is no second seam to fall back to.
    2. **It maps to pause.** `pause(run_id, cause=error)` moves the run to `paused` with a rendered
       reason, and leaves the frozen provider snapshot untouched.
    3. **Paused means no dispatch.** A further pass calls the seam no more.
    4. **The estimate precedes dispatch.** With a provider seam that prices units, `start`
       writes a cost estimate before any unit is dispatched.

    Disclosed shape: the dispatch loop surfaces the terminal error, and the driver holding the
    batch calls `pause(cause=...)`, as `TC-E2E-02`'s provider-unavailable variant does."""
    import aeh.prov as prov
    from decimal import Decimal

    from aeh.orch import Orchestrator
    from tests.support.orch_run import seed_documents

    error_cls = getattr(prov, terminal)

    class TerminalSeam:
        calls = 0

        def call(self, request):
            TerminalSeam.calls += 1
            raise error_cls(f"injected {terminal}")

    class PricingProvider:
        estimates = 0

        def estimate_cost(self, unit):
            PricingProvider.estimates += 1
            return Decimal("0.002")

    store = open_store(tmp_data_dir)
    try:
        seam = TerminalSeam()
        orchestrator, run_id, _v = seed_run(store, submissions=("S001", "S002"), criteria=(
            {"criterion_id": "C01", "kind": "open", "scoring_model": "holistic"},), transport=seam)
        seed_documents(store, ("S001", "S002"))
        orchestrator.enumerate_units(run_id)
        pricing = Orchestrator(store, transport=seam, provider=PricingProvider())
        pricing.start(run_id)
        cohort = store.cohort(ORCH_COHORT_ID)
        before = cohort.query("SELECT cost_estimate, provider_config FROM run WHERE run_id = :r",
                              r=run_id)[0]
        for stage in ("extract", "deterministic"):
            for unit in orchestrator.lease("w-req-14", stage, 64):
                orchestrator.complete(unit.work_id)
        with pytest.raises(error_cls) as caught:
            orchestrator.progress(run_id)
        calls_at_error = TerminalSeam.calls
        status = orchestrator.pause(run_id, cause=caught.value)
        try:
            orchestrator.progress(run_id)
        except error_cls:
            pass
        row = cohort.query("SELECT status, pause_reason, provider_config FROM run WHERE run_id = :r",
                           r=run_id)[0]
        scored_done = cohort.query(
            "SELECT COUNT(*) AS n FROM work_unit WHERE run_id = :r AND stage = 'score' "
            "AND status = 'done'", r=run_id)[0]["n"]
    finally:
        store.close()
    problems = []
    if calls_at_error < 1:
        problems.append("fixture: the dispatch never reached the seam")
    if scored_done:
        problems.append(f"{scored_done} score unit(s) completed although the only provider failed")
    if status != "paused" or row["status"] != "paused" or not row["pause_reason"]:
        problems.append(f"pause(cause={terminal}) left the run {row['status']!r}, reason {row['pause_reason']!r}")
    if row["provider_config"] != before["provider_config"]:
        problems.append("the pause changed the run's frozen provider snapshot")
    if TerminalSeam.calls > calls_at_error:
        problems.append(f"the paused run dispatched again ({TerminalSeam.calls} seam calls)")
    if PricingProvider.estimates == 0 or before["cost_estimate"] is None:
        problems.append("start wrote no cost estimate before dispatch (CT-PROV-09, FR-ORCH-15)")
    assert not problems, "\n".join(problems)


# -- TC-REQ-19 / TC-REQ-30 ----------------------------------------------------------------------


def _world_with_wire(store, tmp_data_dir, reply):
    from tests.contract.judge import _drive

    orchestrator, run_id, version = _drive.seed_world(store, submissions=("SYN-001", "SYN-002"))
    return _drive, orchestrator, run_id, WireTransport(reply=reply)


def test_tc_req_19_the_extraction_ordering_survives_the_wire(tmp_data_dir):
    """`TC-REQ-19` (`M-EXTRACT` → `M-PROV`, CT-PROV-01/05/06, CT-EXTRACT-06): every extraction unit
    of a two-submission run is processed by the real `ExtractionWorker` over a real provider. Each
    dispatched body carries exactly M-EXTRACT's assembled fields in their assembled order, with
    the submission field last. One completion is dispatched per unit."""
    from aeh.extract import ExtractionWorker, assemble_request, prompt_fields
    from aeh.orch import STAGE_EXTRACT
    from tests.support.extract_vocabulary import extractor_ref, span_completion

    store = open_store(tmp_data_dir)
    try:
        drive, orchestrator, _run, transport = _world_with_wire(
            store, tmp_data_dir, reply=lambda fields: span_completion(drive_spans(), build_id="served-build-7").text)
        worker = ExtractionWorker(store, wire_provider(transport), extractor_ref())
        assembled = []
        units = 0
        while True:
            batch = orchestrator.lease("w-req-19", STAGE_EXTRACT, 8)
            if not batch:
                break
            for unit in batch:
                assembled.append([tuple(f) for f in prompt_fields(assemble_request(unit, store=store)).fields])
                worker.process(unit)
                units += 1
    finally:
        store.close()
    wire = transport.fields()
    assert units and len(wire) == units, f"{len(wire)} dispatches for {units} extraction units"
    assert wire == assembled, "a dispatched extraction body differs from the assembled payload"
    last = {fields[-1][0] for fields in wire}
    assert len(last) == 1 and "submission" in next(iter(last)), (
        f"the submission is not the last field on the wire: {last}")


def drive_spans():
    from tests.contract.judge import _drive

    return _drive.spans()


def test_tc_req_30_the_judge_prompt_invariants_survive_the_wire_and_no_verdict_is_resampled(
    tmp_data_dir
):
    """`TC-REQ-30` (`M-JUDGE` → `M-PROV`, CT-PROV-01/05/06/16, CT-JUDGE-08/09/17):

    1. **CT-JUDGE-08 on the wire.** Two submissions scored by the same judge on the same criterion
       share a byte-identical dispatched prefix, meaning every field before the submission block.
    2. **CT-JUDGE-09 on the wire.** The submission and its evidence are the last fields
       dispatched.
    3. **No re-sampling.** Each persisted verdict corresponds to exactly one dispatch.
    4. **No reproducibility assumed (CT-JUDGE-17 / CT-PROV-16).** The same request, dispatched
       twice with two different replies, yields the two different bands. M-JUDGE neither caches
       the first answer nor refuses the second as inconsistent."""
    from aeh.judge import ScoringWorker
    from aeh.prov import RecordedFixtureProvider
    from tests.support.extract_vocabulary import verdict_completion

    bands = iter(["secure", "emerging"] * 50)
    store = open_store(tmp_data_dir)
    try:
        drive, orchestrator, run_id, transport = _world_with_wire(
            store, tmp_data_dir,
            reply=lambda fields: verdict_completion(next(bands), 0.9, build_id="served-build-7",
                                                    cited_spans=drive_spans()).text)
        fixture = RecordedFixtureProvider(fixture_dir=tmp_data_dir / "fixtures")
        drive.drive_extract(orchestrator, store, fixture)
        units = drive.lease_score_units(orchestrator)
        provider = wire_provider(transport)
        by_judge: dict[str, list] = {}
        persisted = 0
        for unit in units:
            judge_ref = {r.build_id: r for r in drive.PANEL_REFS}[unit.judge]
            worker = ScoringWorker(store, provider, judge_ref)
            request = worker.assemble(unit)
            result = worker.dispatch(request, judge_ref)
            worker.persist(unit, result)
            persisted += 1
            by_judge.setdefault(unit.judge, []).append(transport.fields()[-1])
        repeat_ref = {r.build_id: r for r in drive.PANEL_REFS}[units[0].judge]
        repeat_worker = ScoringWorker(store, provider, repeat_ref)
        repeat_request = repeat_worker.assemble(units[0])
        bands = iter(["secure", "emerging"])
        again = [repeat_worker.dispatch(repeat_request, repeat_ref).band for _ in range(2)]
    finally:
        store.close()

    def split(fields):
        index = next(i for i, (name, _v) in enumerate(fields) if "submission" in name)
        return fields[:index], fields[index:]

    problems = []
    if transport.bodies[:persisted] and len(transport.bodies) - 2 != persisted:
        problems.append(f"{len(transport.bodies) - 2} dispatches for {persisted} persisted verdicts")
    for judge, dispatched in by_judge.items():
        prefixes = {json.dumps(split(fields)[0]) for fields in dispatched}
        if len(dispatched) > 1 and len(prefixes) != 1:
            problems.append(f"judge {judge}: the dispatched prefix differs across submissions")
        for fields in dispatched:
            tail_names = [name for name, _v in split(fields)[1]]
            if any("submission" not in name and "evidence" not in name for name in tail_names):
                problems.append(f"judge {judge}: a non-submission field follows the submission: {tail_names}")
    if not any(len(d) > 1 for d in by_judge.values()):
        problems.append("fixture: no judge scored two submissions, so the prefix was never compared")
    if again != ["secure", "emerging"]:
        problems.append(f"two dispatches of one request did not yield both replies: {again}")
    assert not problems, "\n".join(problems)


# -- TC-REQ-44 ----------------------------------------------------------------------------------


def test_tc_req_44_synthesis_dispatches_each_unit_once_as_assembled(tmp_data_dir):
    """`TC-REQ-44` (`M-SYNTH` → `M-PROV`, CT-PROV-01/05/06): a five-question submission is
    synthesized through the real `SynthesisWorker` over a real provider. One completion is
    dispatched per L1 question and one for the L2 composition, every reply parses, and no parsed
    output is re-sampled (exactly six dispatches). Each dispatched body is the worker's assembled
    prompt, unchanged."""
    from aeh.synth import SynthesisWorker, prompt_for
    from tests.support.synth_vocabulary import (
        FIVE_QUESTION_CRITERIA,
        narrative_completion,
        seed_scored_submission,
        synth_ref,
    )

    questions = tuple(f"Q{q}" for q in range(1, 6))
    replies = iter([narrative_completion(f"Question {q[1:]}: the response states its reasoning.",
                                         (f"{q}C1", f"{q}C2")).text for q in questions]
                   + [narrative_completion("Overall: each question is addressed in turn.").text])
    transport = WireTransport(reply=lambda fields: next(replies))
    assembled = []
    real_prompt_for = prompt_for
    import aeh.synth as synth

    def recording_prompt_for(request):
        payload = real_prompt_for(request)
        assembled.append([tuple(f) for f in payload.fields])
        return payload

    store = open_store(tmp_data_dir)
    patch = pytest.MonkeyPatch()
    try:
        patch.setattr(synth, "prompt_for", recording_prompt_for)
        _orch, run_id, _v = seed_run(store, submissions=("SYN-001",), criteria=FIVE_QUESTION_CRITERIA)
        seed_scored_submission(store, run_id, "SYN-001", complete_questions=set(questions))
        SynthesisWorker(store, wire_provider(transport), synth_ref()).synthesize_submission(run_id, "SYN-001")
    finally:
        patch.undo()
        store.close()
    assert transport.attempts == len(transport.bodies) == 6, (
        f"{transport.attempts} dispatches for five L1 questions and one L2 composition")
    assert transport.fields() == assembled, "a dispatched synthesis body differs from the assembled prompt"


# -- TC-REQ-67 ----------------------------------------------------------------------------------


def test_tc_req_67_an_unavailable_off_panel_model_raises_rather_than_falling_back(monkeypatch):
    """`TC-REQ-67` (`M-CALIB` → `M-PROV`, CT-PROV-01/08): the back-translation gate, with no
    off-panel checker bound, raises `OffPanelUnavailable`. No provider implementation is asked
    to complete anything, so nothing on the panel was quietly substituted. The off-panel model is
    meant to be reachable through M-PROV's interface (`InferenceProvider.complete`), so M-CALIB's
    construction must dispatch through that interface."""
    import inspect

    import aeh.calib as calib
    import aeh.prov as prov

    calls = []
    for cls in (prov.RecordedFixtureProvider, prov.LocalServerProvider, prov.OpenRouterProvider):
        original = cls.complete
        monkeypatch.setattr(cls, "complete",
                            lambda self, *a, _o=original, _c=cls, **k: calls.append(_c.__name__) or _o(self, *a, **k))
    monkeypatch.delenv(calib.CALIB_OFF_PANEL_MODEL_ENV, raising=False)
    monkeypatch.setattr(calib, "CALIB_OFF_PANEL_MODEL", None, raising=False)
    with pytest.raises(calib.OffPanelUnavailable):
        calib.back_translate("pkg-v1", "pkg-v2")
    unbound = calib.OffPanelModelRef(provider="openrouter", build_id="off-panel/checker@2026-09")
    with pytest.raises(calib.OffPanelUnavailable):
        calib.back_translate("pkg-v1", "pkg-v2", off_panel=unbound)
    assert not calls, f"an unavailable off-panel gate still called a provider: {calls}"

    # Positive half: a checker whose provider is unavailable must surface as OffPanelUnavailable
    # through M-PROV, which requires M-CALIB to dispatch its construction through `complete()`.
    import ast as _ast

    tree = _ast.parse(inspect.getsource(calib))
    dispatches = [node for node in _ast.walk(tree)
                  if isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
                  and node.func.attr == "complete"]
    assert dispatches, (
        "M-CALIB never calls an InferenceProvider's complete(): its off-panel model is not "
        "reachable through M-PROV's interface, so an unavailable provider cannot surface as "
        "OffPanelUnavailable and CT-PROV-08's no-fallback guarantee is never exercised on this "
        "path. [When written: back_translate reads scripted construction sessions from "
        "_OFF_PANEL_SESSIONS.]")


# -- TC-REQ-71 ----------------------------------------------------------------------------------


def test_tc_req_71_implementations_are_substitutable_hermetic_and_text_is_never_compared(tmp_path):
    """`TC-REQ-71` (`M-CONFORM` → `M-PROV`, CT-PROV-02/10/16):

    1. **Substitutable.** The three implementations expose the same public interface.
    2. **Hermetic.** The fixture provider refuses an unrecorded request with
       `FixtureMissingError`, under the socket guard, so the fast tier cannot reach a network.
    3. **No textual reproducibility assumed.** No comparison in M-CONFORM's source tests a
       completion's `.text` for equality; it compares bands and distributions."""
    import ast
    import inspect

    import aeh.conform as conform
    import aeh.prov as prov
    from aeh.conf import ModelRef
    from aeh.prov import PromptPayload

    def surface(cls):
        return {name for name, _ in inspect.getmembers(cls, callable) if not name.startswith("_")}

    surfaces = {cls.__name__: surface(cls) for cls in
                (prov.RecordedFixtureProvider, prov.LocalServerProvider, prov.OpenRouterProvider)}
    protocol = {name for name in dir(prov.InferenceProvider) if not name.startswith("_")}
    missing = {name: protocol - members for name, members in surfaces.items() if protocol - members}

    fixture = prov.RecordedFixtureProvider(fixture_dir=tmp_path)
    with pytest.raises(prov.FixtureMissingError):
        fixture.complete(PromptPayload(fields=(("submission", "never recorded"),)),
                         ModelRef(role="judge", provider="ollama", build_id="/m/x.gguf@sha256:ab",
                                  quantization="q4"), SamplingParams(temperature=0.0))

    text_equality = []
    for node in ast.walk(ast.parse(inspect.getsource(conform))):
        if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
            operands = [node.left, *node.comparators]
            if any(isinstance(o, ast.Attribute) and o.attr == "text" for o in operands):
                text_equality.append(ast.unparse(node))
    assert protocol, "control: InferenceProvider declares no members"
    assert not missing, f"implementations missing protocol members: {missing}"
    assert not text_equality, f"M-CONFORM compares generated text for equality: {text_equality}"
