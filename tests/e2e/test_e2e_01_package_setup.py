"""TC-E2E-01 — Package setup, from four PDFs to a published locked version.

The first of the three end-to-end journeys (TS-51, issue #144; design §4.2.1, test plan
§6.2). Rung 4 — the ASSEMBLED system: `M-CONSOLE`'s blocking-gate surface, `M-INGEST`'s
real gateway (real PDF bytes, real sanitizer, real rasterizer, one transcription call per
page), `M-SETUP`'s whole chain, `M-PKG`'s publication and §6.2 schema lock. No doubles at
any module boundary; the only double anywhere is the model boundary, and it is the
shipped `RecordedFixtureProvider` in its regeneration-then-replay shape (the
`test_smoke_ingest.py` precedent): a first sight of a request is answered by the
journey's script and **recorded through the shipped `record()`/request-key machinery**,
and every later identical request replays from the recording — `CT-PROV-10`'s only
egress, exercised as `F-RECORDED`'s own lifecycle.

**Happy path** (§4.2.1, in order): the teacher uploads assessment, reference, rubric and
marked calibration papers — four real PDFs through the real gateway; the inventory is
proposed and confirmed (blocking); answer keys are supplied (blocking); the rubric is
read back into criteria with even band sets; decomposability is classified and
confirmed; dependencies are proposed and declined; the grade policy is skipped and the
default recorded; the prefix budget is checked; the version publishes. **Oracle**: the
published package matches its golden manifest, and a post-publication edit to any locked
field raises `SchemaLockViolation`.

**Failure variant**: the rubric PDF fails V0. It surfaces on the **teacher upload
screen** — the refusal raises to the caller, which is the screen the teacher is on — and
never enters the operator quarantine queue (`FR-INGEST-32`: a setup artifact has no
operator), and setup remains resumable from that point: the same chain re-uploads a good
rubric and publishes.

**The golden manifest** (fixtures/baselines/TC-E2E-01/published-manifest.json) is the
committed expectation for the published artifact — §6.9's discipline applies even though
the six-entry registry does not name a `TC-E2E-*` row (the registry's table is §6.9's own
and pinned by its drift test). Reviewer: the package owner. Grounds for accepting a
diff: a schema-version bump or a declared setup-mapping change — **never** "the model
changed its mind"; a diff in a band, a key, a points figure or the policy is a defect,
not a baseline update. There is deliberately no regenerate helper here: the first
recording was run, inspected and committed in the PR that carried it.

Nondeterministic identifiers are normalized out of the manifest on purpose: the version
id and the document ids are minted per run (`uuid4`), so the manifest freezes the
package's CONTENT — questions, criteria, bands, keys, options, dependencies, the
recorded policy source and the journey's own step facts — and the identifier shapes are
asserted separately.

`Written ahead of implementation: yes` is stale — every module in the chain is landed
(#36, #51-#54, #118); the journeys run green by design, the smoke suite's precedent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aeh.console import ConsoleApp, render_setup_step
from aeh.ingest import Ingestor, PdfiumRasterizer, PypdfSanitizer, ResidencySlot
from aeh.prov import (
    Completion,
    FixtureMissingError,
    RecordedFixtureProvider,
    SamplingParams,
)
from aeh.setup import SetupService, default_grade_policy
from aeh.store import open_store
from harness.corpora.pdf_writer import typed_document
from tests.support.setup_harness import ASSESSMENT_MD, INVENTORY_REPLY, RUBRIC_MD

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

ISSUE = "#144"

COHORT_ID = "c-2026-11A-e2e-setup"
PACKAGE_ID = "pkg-e2e-setup"
TRANSCRIBER_BUILD = "vlm@sha256:e2e11ca"
SETUP_BUILD = "vlm@sha256:e2e22cb"
DPI = 72

#: The golden manifest's home — under `fixtures/baselines/` with the §6.9 baselines,
#: governed inline (the registry's table is §6.9's six `TC-REG-*` rows and is closed).
GOLDEN_MANIFEST = Path("fixtures") / "baselines" / "TC-E2E-01" / "published-manifest.json"

GOLDEN_REVIEWER = "The package owner"
GOLDEN_GROUNDS = (
    "Accepted only with a schema-version bump or a declared setup-mapping change; "
    "never 'the model changed its mind' — a diff in a band, a key, a points figure "
    "or the policy is a defect, not a baseline update"
)


# --- the four uploaded artifacts -------------------------------------------------------------

#: The reference document the teacher uploads with the assessment (kind `reference`) —
#: the model answers. ASCII only: the typed renderer's content streams are ASCII.
REFERENCE_MD = (
    "Reference solutions - Physics 102\n"
    "\n"
    "Q1. Impulse is the integral of net force over the contact time, J = F dt.\n"
    "\n"
    "Q2. The range follows by eliminating the flight time between the horizontal\n"
    "and vertical equations of motion.\n"
    "\n"
    "Q3. A 2 kg cart: draw the free-body diagram, then read the acceleration.\n"
)

#: The teacher-marked calibration paper (kind `submission` through the one gateway, but
#: a setup artifact with no cohort unit behind it - `FR-SETUP-15` stores the fact and
#: derives nothing: no ambiguity discovery runs until M-CALIB ships).
CALIBRATION_MD = (
    "Marked calibration paper - student 2101, marked 6/10\n"
    "\n"
    "Q1. Impulse is the net force acting over the contact time. [4/4]\n"
    "\n"
    "Q4. (A) [0/2]\n"
)


def _pdf_of(text: str) -> bytes:
    """A REAL one-page PDF carrying `text` - the shipped typed-document renderer, the
    same bytes a teacher's printed-to-PDF sheet enters the gateway by. The renderer's
    content streams are ASCII, so non-ASCII source text (the shared fixtures' em-dashes)
    renders transliterated - the canonical transcript is the staged reply, not the PDF's
    bytes, so this loses nothing the pipeline reads."""
    return typed_document([text.replace("—", "-").encode("ascii", "replace")
                           .decode("ascii")])


# --- the model boundary ---------------------------------------------------------------------

class JourneyProvider:
    """The model boundary for the setup journey: the shipped `RecordedFixtureProvider`
    owns the fixture store and every replay; the wrapper answers a *first* sight of an
    unknown request from the journey's script and records it through the shipped
    `record()`. Transcription calls (payload carries `page_no`) are keyed by the
    (source blob, page); the setup model's calls replay a reply queue in call order.
    `scripted_calls`/`replayed_calls` make the call budget observable."""

    def __init__(self, fixture_dir) -> None:
        self._inner = RecordedFixtureProvider(fixture_dir=fixture_dir)
        self._transcripts: dict[tuple[str, int], str] = {}
        self._setup_replies: list[str] = []
        self.scripted_calls = 0
        self.replayed_calls = 0

    def stage_transcript(self, blob_hash: str, pages: dict[int, str]) -> None:
        """Stage the transcription the VLM returns for one uploaded PDF's pages."""
        for page_no, text in pages.items():
            self._transcripts[(blob_hash, int(page_no))] = text

    def stage_setup_replies(self, replies: list[str]) -> None:
        """Queue the setup model's replies in the order the chain requests them."""
        self._setup_replies = list(replies)

    def complete(self, prompt, model_ref, params) -> Completion:
        try:
            completion = self._inner.complete(prompt, model_ref, params)
            self.replayed_calls += 1
            return completion
        except FixtureMissingError:
            pass
        fields = dict(prompt.fields)
        if "page_no" in fields:
            key = (fields.get("source_blob_hash"), int(fields["page_no"]))
            if key not in self._transcripts:
                raise AssertionError(
                    f"the journey's script has no transcript for page {key[1]} of blob "
                    f"{str(key[0])[:16]} - an upload the journey did not stage"
                )
            text = self._transcripts[key]
        else:
            if not self._setup_replies:
                raise AssertionError(
                    "the setup model was called with no staged reply left - the chain "
                    "made an unexpected extra model call"
                )
            text = self._setup_replies.pop(0)
        completion = Completion(
            text=text, tokens_in=10, tokens_out=5, latency_ms=1,
            resolved_build=model_ref.build_id, cached_prefix_tokens=0, cost=None,
        )
        self._inner.record(prompt, model_ref, params, completion)
        self.scripted_calls += 1
        return completion


# --- the world ------------------------------------------------------------------------------

class SetupJourney:
    """The journey's assembled system: store, real gateway, real catalog, real setup
    service, real console. The model boundary is the only double, per §4.2."""

    def __init__(self, tmp_data_dir, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HARNESS_INGEST_DPI", str(DPI))
        self.monkeypatch = monkeypatch
        self.store = open_store(tmp_data_dir)
        self.provider = JourneyProvider(tmp_path / "fixtures")
        self.handle = self.store.cohort(COHORT_ID)
        with self.handle.transaction() as tx:
            tx.execute(
                "INSERT INTO cohort (cohort_id, consent_class, created_at) "
                f"VALUES ('{COHORT_ID}', 'synthetic', '2026-01-01T00:00:00+00:00')")
        self.blobs = self.store.blobs()
        from aeh.conf import ModelRef
        self.ingestor = Ingestor(
            self.handle, self.blobs, self.provider,
            ModelRef(role="transcriber", provider="local",
                     build_id=TRANSCRIBER_BUILD, quantization="q4"),
            SamplingParams(temperature=0.0), PdfiumRasterizer(),
            residency=ResidencySlot.for_policy(("transcriber",)),
            sanitizer=PypdfSanitizer(),
        )
        from aeh.pkg import PackageCatalog
        self.package_id = PACKAGE_ID
        self.catalog = PackageCatalog(
            self.store.package(PACKAGE_ID), package_id=PACKAGE_ID, blobs=self.blobs)
        self.service = SetupService(
            self.catalog, self.ingestor, self.provider,
            ModelRef(role="extractor", provider="local", build_id=SETUP_BUILD,
                     quantization="q4"))

    def upload(self, text: str, kind: str, name: str) -> str:
        """The teacher uploads one PDF through the gateway: bytes into the blob store,
        exactly one transcription call per page, one immutable document row out."""
        blob = self.blobs.put(_pdf_of(text))
        self.provider.stage_transcript(blob, {1: text})
        return self.ingestor.ingest_document([blob], kind=kind,
                                             filenames={blob: name})

    def upload_bytes(self, payload: bytes, kind: str, name: str) -> str:
        """Upload raw bytes - the corrupted-PDF variant's entry point."""
        blob = self.blobs.put(payload)
        return self.ingestor.ingest_document([blob], kind=kind,
                                             filenames={blob: name})


# --- the setup replies ----------------------------------------------------------------------

#: The rubric read-back the journey scripts: two judged criteria - one taking the
#: derived two-band default, one with an even four-band partial-credit set - anchored
#: to confirmed questions Q1 and Q3.
RUBRIC_READBACK_REPLY = json.dumps({"criteria": [
    {"criterion_id": "CRIT-IMP", "question_id": "Q1", "kind": "open",
     "scoring_model": "holistic", "max_points": 4.0,
     "construct": "the response defines impulse as force acting over contact time",
     "evidence_type": "quoted_definition"},
    {"criterion_id": "CRIT-STEPS", "question_id": "Q3", "kind": "open",
     "scoring_model": "holistic", "max_points": 6.0,
     "construct": "the response carries the derivation through to a stated result",
     "band_count": 4,
     "bands": [
         {"band": "full", "ordinal": 1, "points": 6.0,
          "descriptor": "the response derives the relation, states each step, and "
                        "arrives at the stated result"},
         {"band": "partial", "ordinal": 2, "points": 4.0,
          "descriptor": "the response sets up the derivation correctly and completes "
                        "at least one intermediate step"},
         {"band": "partial", "ordinal": 3, "points": 2.0,
          "descriptor": "the response identifies the governing relation but stops "
                        "before an intermediate step"},
         {"band": "none", "ordinal": 4, "points": 0.0,
          "descriptor": "the response states no relation and shows no derivation"},
     ],
     "justification": "partial credit: the derivation earns points for each correct "
                      "step even when the final result is wrong"},
]})

#: The decomposability replies, one per judged criterion: every §5.3 question `yes`,
#: so both classify `atomic` (one judgment per criterion).
DECOMPOSITION_REPLIES = [
    json.dumps({"criterion_id": "CRIT-IMP",
                "answers": {"completeness": "yes", "non_interference": "yes",
                            "independence": "yes", "additivity": "yes",
                            "gates": "yes"},
                "reasoning": "scripted §5.3 answers for CRIT-IMP"}),
    json.dumps({"criterion_id": "CRIT-STEPS",
                "answers": {"completeness": "yes", "non_interference": "yes",
                            "independence": "yes", "additivity": "yes",
                            "gates": "yes"},
                "reasoning": "scripted §5.3 answers for CRIT-STEPS"}),
]

#: The dependency proposal the subject makes likely; the teacher declines it.
DEPENDENCY_REPLY = json.dumps({"dependencies": [
    {"criterion_id": "CRIT-STEPS", "depends_on": "CRIT-IMP",
     "reason": "error carried forward: the derivation is graded on work that "
               "presupposes the impulse definition"},
]})

#: The four setup steps' rendered asks, per `_SETUP_STEP_COPY`'s own keys - the
#: optional cards the walkthrough's teacher answers or skips.
OPTIONAL_STEP_ASKS = (
    "Approve how the rubric was understood",
    "Confirm decomposability classifications",
    "Declare the grade policy and boundaries",
)


def _stage_chain_replies(journey: SetupJourney) -> None:
    journey.provider.stage_setup_replies(
        [INVENTORY_REPLY, RUBRIC_READBACK_REPLY, *DECOMPOSITION_REPLIES,
         DEPENDENCY_REPLY])


def _drive_setup_chain(journey: SetupJourney, rubric_doc: str, assessment_doc: str):
    """The setup chain in §4.2.1's order. The two BLOCKING gates are explicit
    confirmations; the optional cards are answered or skipped with the default
    recorded either way. Returns the artifacts the oracles read."""
    service = journey.service
    proposal = service.propose_inventory(assessment_doc)
    service.confirm_inventory(proposal.proposal_id)
    service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["B"], "CRIT-Q6": ["A"]})
    readback = service.read_back_rubric(rubric_doc, assessment_doc)
    criteria = list(readback.criteria)
    assert criteria, (
        "TC-E2E-01: the rubric read back no criteria - the read-back leg produced "
        "nothing for the decomposability step to classify"
    )
    for draft in criteria:
        verdict = service.classify_decomposability(draft)
        assert verdict.classification == "atomic", (
            f"TC-E2E-01: criterion {draft.criterion_id} classified "
            f"{verdict.classification!r}; the journey's scripted answers are all `yes`, "
            "which is the atomic classification's"
        )
    service.confirm_classifications(
        {draft.criterion_id: "atomic" for draft in criteria})
    proposals = service.propose_dependencies()
    assert proposals, (
        "TC-E2E-01: no dependency proposal arrived - the journey declines a "
        "proposal, which needs one to exist"
    )
    service.confirm_dependencies([])  # declined: the empty graph is the base case
    policy = service.set_grade_policy(None)  # skipped: the default is recorded
    budget = service.check_prefix_budget()
    return readback, criteria, proposals, policy, budget


# --- the golden manifest --------------------------------------------------------------------

def _published_manifest(journey: SetupJourney, version: str, budget) -> dict:
    """The published package's canonical content, as the oracles freeze it.

    Every field is read through M-PKG's own surfaces; nothing is copied from the
    journey's inputs, so a setup chain that lost a step cannot reproduce the frozen
    artifact. Nondeterministic identifiers are normalized out deliberately: the
    version id and the document ids are minted per run (`uuid4`), so the calibration
    step's payload freezes a COUNT, not ids, and the prefix step's payload drops
    `ceiling_tokens` (an env knob, not package content - its over/under facts stay).
    The manifest freezes the package's CONTENT - the confirmed inventory, criteria,
    bands, keys, options, dependencies, the policy the version carries, and every
    setup step's recorded provenance status. `inventory`/`rubric_readback` read as
    null because their provenance lives in the proposal and read-back tables, not
    in a step row."""
    catalog = journey.catalog
    rows = sorted(catalog.criteria(version), key=lambda row: row["criterion_id"])
    criteria = []
    for row in rows:
        criterion_id = row["criterion_id"]
        entry = {
            "criterion_id": criterion_id,
            "question_id": row["question_id"],
            "kind": row["kind"],
            "scoring_model": row["scoring_model"],
            "max_points": row["max_points"],
            "evidence_type": row["evidence_type"],
            "band_justification": row["band_justification"],
            "bands": [
                {"band": band["band"], "ordinal": band["ordinal"],
                 "points": band["points"], "descriptor": band["descriptor"]}
                for band in catalog.bands(criterion_id)
            ],
        }
        if row["kind"] != "open":
            entry["answer_key"] = list(catalog.answer_key(criterion_id))
            entry["options"] = [
                {"option_id": option_id, "label": label}
                for option_id, label in catalog.mcq_options(version, criterion_id)
            ]
        criteria.append(entry)
    policy = catalog.grade_policy(version)
    steps = {}
    for step_id in ("inventory", "answer_keys", "rubric_readback",
                    "decomposability", "grade_policy", "prefix_budget",
                    "calibration_papers"):
        record = catalog.step_record(version, step_id)
        if record is None:
            steps[step_id] = None
            continue
        entry = {"status": record.get("status")}
        payload = record.get("payload")
        if isinstance(payload, str) and payload:
            try:
                entry["payload"] = json.loads(payload)
            except ValueError:
                entry["payload"] = payload
        payload = entry.get("payload")
        if isinstance(payload, dict):
            # Per-run identifiers and env-derived ceilings are not package content.
            if isinstance(payload.get("document_ids"), list):
                payload["document_ids"] = (
                    f"<{len(payload['document_ids'])} documents, ids are per-run>")
            for pair in payload.get("pairs") or ():
                pair.pop("ceiling_tokens", None)
            payload.pop("ceiling_tokens", None)
        steps[step_id] = entry
    return {
        "package_id": PACKAGE_ID,
        "version_prefix": version.split("@", 1)[0],
        "locked": catalog.is_locked(version),
        "questions": [
            {"question_id": q["question_id"],
             "question_type": q["question_type"],
             "max_points": q["max_points"]}
            for q in sorted(catalog.questions(version),
                            key=lambda r: r["question_id"])
        ],
        "criteria": criteria,
        "dependencies": {
            criterion: list(parents)
            for criterion, parents in catalog.dependency_graph(version).items()
        },
        "grade_policy": {
            "is_default": policy.to_dict() == default_grade_policy().to_dict(),
            "policy": policy.to_dict(),
        },
        "prefix_budget": {
            "over_budget": budget.over_budget,
            "dropped_exemplars": sorted(budget.dropped_exemplars),
        },
        "steps": steps,
    }


def _assert_matches_golden_manifest(repo_root: Path, manifest: dict) -> None:
    """Compare the published artifact against its frozen baseline, with §6.9's
    governance in the failure message - the same shape `tests.support.baselines`
    gives the registry's own rows."""
    golden_path = repo_root / GOLDEN_MANIFEST
    assert golden_path.exists(), (
        f"TC-E2E-01: no golden manifest recorded at {GOLDEN_MANIFEST}. The published "
        f"artifact is the journey's whole output; freezing it is a deliberate act "
        f"(run the journey, inspect what it emitted, commit it with the reviewer - "
        f"{GOLDEN_REVIEWER}) - never a regenerate-until-green keypress."
    )
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    assert manifest == golden, (
        f"TC-E2E-01: the published package no longer matches its golden manifest.\n\n"
        f"baseline: {GOLDEN_MANIFEST}\n"
        f"  reviewer: {GOLDEN_REVIEWER}\n"
        f"  grounds for accepting a diff: {GOLDEN_GROUNDS}\n"
        f"(test plan §6.9's discipline; a diff in a band, a key, a points figure or "
        f"the policy is a defect, not a baseline update)"
    )


# --- TC-E2E-01: the happy path --------------------------------------------------------------

def _skip_section(page: str) -> str:
    """The one `data-role="skip"` element of a rendered prompt - the affordance and
    its cost are ONE structural element (`R62`: read together or not informing)."""
    start = page.find('<div data-role="skip">')
    assert start != -1, (
        "TC-E2E-01: the rendered prompt carries no skip control - FR-CONSOLE-06 "
        "gives every non-blocking setup prompt a first-class skip control."
    )
    end = page.find("</div>", start)
    assert end != -1, "TC-E2E-01: the skip control's element is not closed - bad HTML."
    return page[start:end + len("</div>")]


def _assert_skip_carries_cost(ask: str) -> None:
    """`FR-CONSOLE-06`: the optional setup step renders its ask, a first-class skip
    control, and the skip's cost in the same view."""
    page = render_setup_step(ask)
    skip = _skip_section(page)
    assert "skip this step" in skip, (
        f"TC-E2E-01: the skip element for {ask!r} renders no skip affordance "
        f"({skip!r}) - it is not a first-class skip control."
    )
    cost_text = skip.split("If you skip:", 1)[1].strip()
    assert len(cost_text) > 20, (
        f"TC-E2E-01: the skip control for {ask!r} renders no cost beside the "
        f"affordance ({skip!r}) - the cost must live in the same view (R62)."
    )


def test_tc_e2e_01_four_pdfs_to_a_published_locked_version(
    tmp_data_dir, tmp_path, monkeypatch, repo_root,
):
    """`TC-E2E-01` happy path - four PDFs in; a published, schema-locked package out;
    the published artifact matches its golden manifest; a post-publication edit to any
    locked field raises `SchemaLockViolation`."""
    journey = SetupJourney(tmp_data_dir, tmp_path, monkeypatch)
    assessment = journey.upload(ASSESSMENT_MD, "assessment", "assessment.pdf")
    reference = journey.upload(REFERENCE_MD, "reference", "reference.pdf")
    rubric = journey.upload(RUBRIC_MD, "rubric", "rubric.pdf")
    calibration = journey.upload(CALIBRATION_MD, "submission", "calibration.pdf")

    # M-CONSOLE's blocking-gate surface (FR-CONSOLE-06): exactly two screens block -
    # S3 the question inventory and S4 the answer keys - and every optional setup
    # prompt carries a first-class skip control with its cost in the same view.
    app = ConsoleApp(store=journey.store)
    blocking = app.blocking_screens()
    assert tuple(blocking) == ("S3", "S4"), (
        f"TC-E2E-01: M-CONSOLE blocks progress on {blocking}; FR-CONSOLE-06 allows "
        "exactly two screens - S3 the question inventory and S4 the answer keys."
    )
    screens = app.screens()
    assert screens["S3"] == "/setup/inventory" and screens["S4"] == "/setup/answer-keys", (
        f"TC-E2E-01: the blocking screens are not the inventory and the answer keys "
        f"({screens['S3']!r}, {screens['S4']!r}) - FR-CONSOLE-06 names them."
    )
    for ask in ("Approve how the rubric was understood",
                "Confirm decomposability classifications",
                "Declare the grade policy and boundaries"):
        _assert_skip_carries_cost(ask)

    _stage_chain_replies(journey)
    readback, criteria, proposals, policy, budget = _drive_setup_chain(
        journey, rubric, assessment)
    journey.service.store_calibration_papers([reference, calibration])

    version = journey.service.publish("teacher-e2e")

    # Oracle 1: the published package matches its golden manifest.
    assert journey.catalog.is_locked(version), (
        "TC-E2E-01: the published version is not locked - FR-PKG-01's one-transaction "
        "lock flip did not take effect at publication."
    )
    assert version.startswith(f"{PACKAGE_ID}@"), (
        f"TC-E2E-01: the published version id {version!r} does not name its package."
    )
    _assert_matches_golden_manifest(repo_root, _published_manifest(
        journey, version, budget))

    # Oracle 2: the §6.2 lock takes effect on EVERY locked field - an edit through
    # M-PKG's surface to the published version is refused with the named error.
    from aeh.pkg import SchemaLockViolation
    with pytest.raises(SchemaLockViolation) as refused:
        journey.catalog.add_criterion(version, "CRIT-LATE")
    assert "schema lock" in str(refused.value).lower(), (
        f"TC-E2E-01: the post-publication edit was refused with {refused.value!r} - "
        "the §6.2 lock's refusal names the lock and the locked field."
    )
    # The refusal is not just API-deep: the criterion count did not move.
    assert {row["criterion_id"] for row in journey.catalog.criteria(version)} == {
        "CRIT-IMP", "CRIT-STEPS", "CRIT-Q4", "CRIT-Q5", "CRIT-Q6",
    }, (
        "TC-E2E-01: a criterion appeared on the locked version despite the refusal - "
        "the lock is decorative."
    )
    assert len(readback.criteria) == 2 and proposals, (
        "TC-E2E-01: precondition - the read back carried two criteria and the "
        "dependency step proposed one"
    )


# --- TC-E2E-01: the failure variant ---------------------------------------------------------

def test_tc_e2e_01_rubric_v0_failure_surfaces_to_the_teacher_and_setup_resumes(
    tmp_data_dir, tmp_path, monkeypatch, repo_root,
):
    """`TC-E2E-01` failure variant - the rubric PDF fails V0. The refusal surfaces on
    the teacher upload screen (it raises to the caller the teacher's screen drives),
    the operator quarantine queue stays untouched (`FR-INGEST-32` - a setup artifact
    has no operator and no quarantinable unit), and setup remains resumable: the same
    chain re-uploads a good rubric and publishes."""
    from aeh.ingest import IngestError

    journey = SetupJourney(tmp_data_dir, tmp_path, monkeypatch)
    assessment = journey.upload(ASSESSMENT_MD, "assessment", "assessment.pdf")
    reference = journey.upload(REFERENCE_MD, "reference", "reference.pdf")
    calibration = journey.upload(CALIBRATION_MD, "submission", "calibration.pdf")

    # The teacher uploads the rubric scan; the PDF's bytes are not a PDF.
    corrupted = b"%PDF-1.4\nthis trailer references object 9 0 R which does not exist"
    with pytest.raises(IngestError) as surfaced:
        journey.upload_bytes(corrupted, "rubric", "rubric.pdf")

    # The refusal surfaced to the CALLER - the code path the teacher's upload screen
    # drives - and the upload screen still stands ready behind it.
    app = ConsoleApp(store=journey.store)
    page = app.render(app.screens()["S2"])
    assert "PDF only" in page.html, (
        f"TC-E2E-01: S2 does not render the upload screen the failure surfaces on "
        f"({page.html[:120]}...)."
    )
    # The operator quarantine queue is untouched (FR-INGEST-32): a setup artifact
    # has no operator and no quarantinable unit.
    rows = journey.handle.query("SELECT * FROM submission")
    assert not rows, (
        f"TC-E2E-01: the refused setup artifact produced {len(rows)} submission "
        "row(s) - setup artifacts are not quarantinable units; the failure surfaces "
        "to the uploading teacher (FR-INGEST-32), never to the operator triage view."
    )

    # Setup remains resumable from that point: a good rubric uploads, the chain
    # runs, the version publishes.
    rubric = journey.upload(RUBRIC_MD, "rubric", "rubric.pdf")
    _stage_chain_replies(journey)
    readback, criteria, proposals, policy, budget = _drive_setup_chain(
        journey, rubric, assessment)
    journey.service.store_calibration_papers([reference, calibration])
    version = journey.service.publish("teacher-e2e")
    assert journey.catalog.is_locked(version), (
        "TC-E2E-01: the resumed chain did not publish a locked version - the V0 "
        "failure on one upload must not cost the teacher the setup."
    )