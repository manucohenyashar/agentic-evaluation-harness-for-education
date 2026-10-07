"""The teacher's-day world: `SynthWorld` over `F-RUBRIC-METHODS` (TC-E2E-06, issue #641).

The journey's oracle is differential — the same teacher's-day journey driven through the
SPA's surfaces must write exactly the rows the same journey driven through the CLI writes,
into a twin store. Both twins run the real composed pipeline (`run_to_completion`) over a
shared recording set: this world CAPTURES that set once (a computing provider answers a
first sight from the fixture's own declarations and records through the shipped
`record()`/request-key machinery — `RecordedFixtureProvider` stays the only egress,
`CT-PROV-10`), and the twins then REPLAY it.

**Why a synthesis-only replay fallback exists** (the one mechanism here that has no
precedent to copy): the request key hashes every prompt field, and `synth.prompt_for` is
the one composer that puts the MINTED `submission_id` into its payload (`L1Request`
carries `submission`; `L2Request` carries it too). Extraction, judging, transcription and
the deterministic leg key on content alone, so their recordings replay across the twins'
fresh stores byte-for-byte — but a synthesis recording captured under this world's minted
ids can never be found by a twin whose ids were minted again. Pinning the mint across
three separately-driven stores was considered and rejected: the ingest legs run in
different orders (a worker thread on the console side), so mint order is not controllable.
The twins therefore replay through `ReplayWithSynthFallback`, a thin wrapper over
`RecordedFixtureProvider` that answers ONLY a first sight whose payload declares a
synthesis `level` (`LEVEL_L1`/`LEVEL_L2`) by calling `synth_reply(fields)` — the SAME
function the capture answered with, so the narrative texts match — and re-raises every
other miss, which stays a loud fixture bug (`CT-PROV-08` has no fallback for it).

**Profile.** The world resolves `dev-ci` (`conf_builders.hosted_cfg("dev-ci", ...)`), for
the same reason the console differential test runs its twins hosted: the twins' model refs
are provider-pinned slugs, `edge-local` would demand the edge-weights build form, and the
console refuses to serve `cloud-hosted` outright. `_provider_for` answers `dev-ci` with
the fixture provider when `HARNESS_FIXTURE_DIR` is set, which is what makes both twins'
`aeh run` / console-start paths egress-free.

**Escalation budget.** Captured and replayed with `HARNESS_ORCH_ESCALATION_BUDGET="1.0"`
(the `CORPUS_ESCALATION_BUDGET` finding: at the shipped default M-ORCH defers this small
cohort's widened pairs and the run can never reach a pending count of zero).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

# The eleven-module import chain FIRST (CLAUDE.md): every contributor's migrations
# must be registered before the first store open in any process.
import aeh.agg  # noqa: F401
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401

from aeh.conf import CohortRef, resolve_run_config
from aeh.ingest import Ingestor, PdfiumRasterizer, PypdfSanitizer, ResidencySlot
from aeh.orch import (
    CRITERION_BREAKER_RATE_ENV,
    ESCALATION_BUDGET_ENV,
    Orchestrator,
)
from aeh.prov import (
    Completion,
    FixtureMissingError,
    ModelRef,
    RecordedFixtureProvider,
    SamplingParams,
)
from aeh.synth import LEVEL_L1, LEVEL_L2

from tests.support.conf_builders import (
    HOSTED_PANEL_3,
    HOSTED_TRANSCRIBER,
    hosted_cfg,
)
from tests.support.console_api_vocabulary import tier_rows
from tests.support.e2e_world import SynthWorld, set_world_env, _pdf_of, _wrap_region
from tests.support.extract_vocabulary import span_completion, verdict_completion
from tests.support import rubric_methods
from tests.support.pipe_world import (
    CORPUS_ESCALATION_ARMS,
    CORPUS_ESCALATION_BUDGET,
    StrictReplayProvider,
    pinned_uuid4,
)
from tests.support.rubric_methods import (
    ASPECTS,
    BANDS,
    COMPOSITE,
    GENERAL,
    MCQ,
)

#: The cohort and run the journey names. Fixed ids: the differential masks the minted
#: ones, and a named id in the store rows reads as the journey it is.
COHORT_ID = "coh-teachers-day"
RUN_ID = "run-teachers-day"

#: The escalation budget the journey is captured and replayed under — the same raise
#: `PipeWorld` makes for the same reason (a three-student cohort grows no headroom, so
#: the shipped default would defer every widened pair and stall the run).
ESCALATION_BUDGET = CORPUS_ESCALATION_BUDGET

_SHAPE = rubric_methods.rubric_methods()


@dataclass
class Student:
    """One student's papers as the fixture declares them: the full name the roster
    carries (names only — RISK-110's roster has no ids), the band each judged
    criterion's evidence shows, and the option letter ticked on the MCQ."""

    student_ref: str
    bands: dict[str, str]
    mcq: str


#: The three students. Each judged criterion reads a different level of the work, so the
#: narratives, the aggregates and the grade have something real to say; the panel's third
#: arm answers one ordinal below the reference (see `TeachersDayWorld._judge_band`), so
#: some cells escalate and settle and others never leave the first panel.
STUDENTS: tuple[Student, ...] = (
    Student(
        "Amara Okafor",
        {BANDS: "full", GENERAL: "balanced",
         ASPECTS[0]: "present", ASPECTS[1]: "present", ASPECTS[2]: "present"},
        "B",
    ),
    Student(
        "Ben Whitfield",
        {BANDS: "adequate", GENERAL: "one",
         ASPECTS[0]: "present", ASPECTS[1]: "absent", ASPECTS[2]: "present"},
        "A",
    ),
    Student(
        "Chen Wei",
        {BANDS: "limited", GENERAL: "neither",
         ASPECTS[0]: "absent", ASPECTS[1]: "absent", ASPECTS[2]: "present"},
        "C",
    ),
)

_CRITERION_RE = re.compile(r"criterion_id:\s*(\S+)")


def _by_id() -> dict[str, rubric_methods.Criterion]:
    return {c.criterion_id: c for c in _SHAPE.criteria}


def _descriptor(cid: str, ordinal: int) -> str:
    for band in _by_id()[cid].bands:
        if band.ordinal == ordinal:
            return band.descriptor
    raise KeyError(f"{cid} has no band at ordinal {ordinal}")


def render_band(cid: str, ordinal: int) -> str:
    """One criterion's evidence line as the pages carry it — the needle the stored
    markdown is cut at, and the reply an arm's verdict reads as the band's prose."""
    return f"{cid}: {_descriptor(cid, ordinal)}"


def synth_reply(fields: dict[str, str]) -> str:
    """The narrative reply, shared by the capture and the twins' fallback.

    Numeral-free so the score-claim ladder leaves it unflagged; the L1 narrative cites
    the request's own criteria. It reads nothing that varies between the twins — the
    criteria and verdicts are the same, and the minted submission id never enters the
    text — which is exactly why a cross-store synthesis miss can be answered here
    without the twins' narratives drifting apart."""
    if fields.get("level") == LEVEL_L1:
        criteria = [c.strip() for c in fields.get("criteria", "").split(",") if c.strip()]
        return json.dumps({
            "narrative": (
                "The response addresses the criteria the panel read, citing the work's "
                "own words as evidence; where the work stops short, the narrative says "
                "so in the same terms the criteria name."
            ),
            "citations": criteria,
        })
    return json.dumps({
        "narrative": (
            "The submission's questions are narrated above; the whole reads as one "
            "response whose strengths and gaps the question narratives already state."
        ),
        "citations": [],
    })


class RubricMethodsPackage:
    """The surface `SynthWorld` reads off a package module, backed by the fixture shape.

    The catalog build itself goes through `rubric_methods.build` — the real M-PKG
    writer, with the `general` derivation recorded and confirmed — so this adapter only
    carries what the world's own bookkeeping reads: the id sets, the band lookup and the
    MCQ options."""

    PACKAGE_ID = _SHAPE.package_id
    MCQ_OPTIONS = _by_id()[MCQ].options
    #: The judged cells, in PAGE ORDER — `_stage_spans` walks them with a single search
    #: cursor, so the order must match the order the pages carry the lines in.
    OPEN_CRITERION_IDS = (BANDS, GENERAL, *ASPECTS)
    MCQ_CRITERION_IDS = (MCQ,)

    def __init__(self) -> None:
        self._by_id = _by_id()
        self.CRITERIA = _SHAPE.criteria
        self.BY_ID = self._by_id

    def points_for(self, cid: str, band: str) -> float:
        for b in self._by_id[cid].bands:
            if b.band == band:
                return b.points
        raise KeyError(f"{cid} has no band {band!r}")


class JourneyCaptureProvider:
    """The model boundary while CAPTURING through the composed pipeline.

    `run_to_completion` pre-records nothing — it hands units to the stage workers and the
    workers call the provider — so the capture needs a boundary that can answer an
    extraction or a verdict *on demand* (the `pipe_world.CaptureProvider` pattern, over
    this fixture's declarations). The cell is recovered from the REQUEST — the criterion
    id from the criterion field, the submission from the student line no V-gate ever
    strips — and the reply is the span set or the band the fixture declares for it.
    Nothing is invented here that the fixture does not already state."""

    def __init__(self, world: Any, fixture_dir: Any) -> None:
        self._world = world
        self._inner = RecordedFixtureProvider(fixture_dir=fixture_dir)
        self._transcripts: dict[tuple[str, int], str] = {}
        self.scripted_calls = 0
        self.replayed_calls = 0

    # -- the boundary --------------------------------------------------------------------

    def stage_transcript(self, blob_hash: str, pages: dict[int, str]) -> None:
        for page_no, text in pages.items():
            self._transcripts[(blob_hash, int(page_no))] = text

    def unavailable(self) -> bool:
        return False

    def estimate_cost(self, unit: Any) -> Decimal:
        return Decimal("0.001")

    def record(self, prompt: Any, model_ref: Any, params: Any, completion: Any) -> str:
        return self._inner.record(prompt, model_ref, params, completion)

    def decision_capabilities(self, model_ref: Any) -> Any:
        return self._inner.decision_capabilities(model_ref)

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        try:
            answer = self._inner.complete(prompt, model_ref, params)
            self.replayed_calls += 1
            return answer
        except FixtureMissingError:
            pass
        fields = dict(prompt.fields)
        completion = self._compose(fields, model_ref)
        self._inner.record(prompt, model_ref, params, completion)
        self.scripted_calls += 1
        return completion

    # -- composing one reply -------------------------------------------------------------

    def _compose(self, fields: dict, model_ref: Any) -> Any:
        role = getattr(model_ref, "role", "")
        if "page_no" in fields:
            key = (fields.get("source_blob_hash"), int(fields["page_no"]))
            if key not in self._transcripts:
                raise AssertionError(
                    f"the capture staged no transcript for page {key[1]} of blob "
                    f"{str(key[0])[:16]}")
            return self._completion(self._transcripts[key], model_ref)
        if fields.get("instruction", "").startswith("Decide whether"):
            return self._completion("match", model_ref)
        if fields.get("level") in (LEVEL_L1, LEVEL_L2):
            return self._completion(synth_reply(fields), model_ref)
        sid, cid = self._cell(fields)
        spans = self._world.spans_by_cell[(sid, cid)]
        if role == "extractor":
            return span_completion(spans, build_id=model_ref.build_id)
        if role == "judge":
            band = self._world._judge_band(sid, cid, judge=model_ref.build_id)
            return verdict_completion(
                band, 0.9, build_id=model_ref.build_id, cited_spans=spans)
        raise AssertionError(
            f"the capture cannot answer a first sight for role {role!r} "
            f"(fields: {sorted(fields)})")

    def _cell(self, fields: dict) -> tuple[str, str]:
        """The (store submission id, criterion id) this request is about, from the
        request itself: the criterion field carries `criterion_id: <id>`, and the
        submission field carries the canonical document whose `Student:` line V3
        matched to the roster."""
        criterion = _CRITERION_RE.search(fields.get("criterion", "") or "")
        if criterion is None:
            raise AssertionError(
                "the capture cannot tell which criterion a request is about: "
                f"criterion field {fields.get('criterion', '')!r}")
        submission = fields.get("submission", "") or ""
        for sid, ref in self._world.student_ref_by_sid.items():
            if f"Student: {ref}" in submission:
                return sid, criterion.group(1)
        raise AssertionError(
            "the capture cannot tell which submission a request is about: no rostered "
            "student line appears in the submission field")

    @staticmethod
    def _completion(text: str, model_ref: Any) -> Any:
        return Completion(
            text=text, tokens_in=10, tokens_out=5, latency_ms=1,
            resolved_build=model_ref.build_id, cached_prefix_tokens=0, cost=None,
        )


class ReplayWithSynthFallback:
    """The twins' boundary: strict replay, with ONE declared first-sight answer.

    Everything but synthesis replays from the shared recording set — a miss anywhere
    else re-raises as the fixture bug it is. A synthesis miss is answered with
    `synth_reply(fields)`, the same function the capture answered with (see the module
    docstring for why synthesis alone needs this): the wrapper records the computed
    reply through the inner provider, so a second identical request replays and the
    fixture dir ends the run complete for the stage that asked."""

    def __init__(self, fixture_dir: Any) -> None:
        self._inner = RecordedFixtureProvider(fixture_dir=fixture_dir)
        self.scripted_calls = 0
        self.replayed_calls = 0

    def unavailable(self) -> bool:
        return False

    def estimate_cost(self, unit: Any) -> Decimal:
        """The composed pipeline prices a leased UNIT (`WorkUnit`) through this method —
        the corpus providers' shape (`StrictReplayProvider`'s precedent) — not the
        `CallPlan` shape the fixture provider itself declares."""
        return Decimal("0.001")

    def record(self, prompt: Any, model_ref: Any, params: Any, completion: Any) -> str:
        return self._inner.record(prompt, model_ref, params, completion)

    def decision_capabilities(self, model_ref: Any) -> Any:
        return self._inner.decision_capabilities(model_ref)

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        try:
            answer = self._inner.complete(prompt, model_ref, params)
            self.replayed_calls += 1
            return answer
        except FixtureMissingError as miss:
            fields = dict(prompt.fields)
            if fields.get("level") not in (LEVEL_L1, LEVEL_L2):
                raise miss
        fields = dict(prompt.fields)
        completion = Completion(
            text=synth_reply(fields), tokens_in=10, tokens_out=5, latency_ms=1,
            resolved_build=model_ref.build_id, cached_prefix_tokens=0, cost=None,
        )
        self._inner.record(prompt, model_ref, params, completion)
        self.scripted_calls += 1
        return completion


class TeachersDayWorld(SynthWorld):
    """`SynthWorld` over `F-RUBRIC-METHODS`: three named students, one MCQ line, one
    `bands` line, one `general` line (derivation confirmed) and one `evidence_sum`
    composite with three aspects.

    Every difference from the reference world goes through a seam `SynthWorld` declares,
    so the drive — orchestrator, deterministic evaluator, extraction workers, integrity
    gate, aggregation walk, synthesis worker and closer — is the same code the journeys
    run. A second copy of the drive is a second place for it to be wrong.
    """

    def __init__(self, data_dir: Any, fixture_dir: Any, *, monkeypatch: Any = None,
                 record_as_you_go: bool = True) -> None:
        self._shape = _SHAPE
        self._by_id = _by_id()
        # Restored after the test when no monkeypatch is given (TC-REG-10).
        set_world_env(ESCALATION_BUDGET_ENV, ESCALATION_BUDGET, monkeypatch)
        # The e2e journeys' breaker raise (`e2e_world.aggregate_walk`'s default): the
        # interior-band escalation share of a three-student cohort trips the shipped
        # 0.50 criterion breaker mid-run, and WHERE it trips depends on the order the
        # verdicts land in — the two twins would diverge on which cells got widened,
        # which is scheduling, not a surface difference.
        set_world_env(CRITERION_BREAKER_RATE_ENV, "1.0", monkeypatch)
        # The mint is pinned around CONSTRUCTION, which is where `ingest_submission`
        # mints the submission ids — the only minted value that reaches a hashed prompt
        # payload (`synth.prompt_for`). Pinning here rather than asking callers to wrap
        # the drive makes the capture self-contained, the `PipeWorld` precedent.
        with pinned_uuid4():
            super().__init__(
                data_dir, fixture_dir,
                n_submissions=len(STUDENTS),
                cohort_id=COHORT_ID,
                run_id=RUN_ID,
                monkeypatch=monkeypatch,
                quarantine_indices=(),
                panel_size=len(HOSTED_PANEL_3),
                package=RubricMethodsPackage(),
                record_as_you_go=record_as_you_go,
            )
        # The twins' identities are the hosted panel, not `edge_panel`'s — the world's
        # bookkeeping (which arm answers what) must name the same builds the run's
        # config resolves, or `_judge_band` would key disagreement to arms the
        # pipeline never sends.
        self.panel_refs = HOSTED_PANEL_3
        self.judge_refs = {ref.build_id: ref for ref in HOSTED_PANEL_3}
        self.escalation_refs = {
            arm: self._judge_ref(arm) for arm in CORPUS_ESCALATION_ARMS
        }
        # The requests' redacted `Student:` head carries the store's RESOLVED ref — the
        # roster writer's generated one, not the declared name — so the capture's cell
        # recovery (and the report's identity column) reads the resolved refs off the
        # store. The base class's map holds the declared names, which only coincide
        # under the legacy nameless-roster channel this world does not use.
        self.student_ref_by_sid = {
            str(row["submission_id"]): str(row["student_ref"])
            for row in self.handle.query(
                "SELECT submission_id, student_ref FROM submission")
        }

    # -- the seams -----------------------------------------------------------------------

    def _build_cohort(self) -> None:
        """The cohort through the same roster writer the twins' class legs call
        (``aeh.orch.cohorts.create_cohort`` — the journey test's console leg calls it
        directly, the CLI side through ``aeh cohort create --roster``): one writer, so
        the three stores' rosters are row-identical, and the refs the redacted request
        heads carry are the same deterministic generated refs on every side."""
        from aeh.orch.cohorts import create_cohort

        create_cohort(self.store, self.cohort_id, "synthetic",
                      [{"full_name": s.student_ref} for s in STUDENTS])

    def _make_provider(self, fixture_dir: Any) -> Any:
        """`JourneyCaptureProvider` while capturing; the strict replayer once the
        recordings exist (the twins wrap it themselves — see `ReplayWithSynthFallback`)."""
        if self.record_as_you_go:
            return JourneyCaptureProvider(self, fixture_dir)
        return StrictReplayProvider(fixture_dir)

    def _judge_ref(self, build_id: str) -> Any:
        """The extension arms as `executor.judge_for` derives them: the FIRST panel
        member with the build swapped, so provider and quantization travel unchanged."""
        first = HOSTED_PANEL_3[0]
        return ModelRef(role="judge", provider=first.provider, build_id=build_id,
                        quantization=first.quantization)

    def _cohort_submissions(self, n_submissions: int) -> tuple[Student, ...]:
        return STUDENTS[:n_submissions]

    def _ingestor(self) -> Ingestor:
        """The twins' transcription identity: the dev-ci config's transcriber, not the
        reference world's local one — the ingest keys must be the keys the twins mint."""
        return Ingestor(
            self.handle, self.blobs, self.provider, HOSTED_TRANSCRIBER,
            SamplingParams(temperature=0.0), PdfiumRasterizer(),
            residency=ResidencySlot.for_policy(("transcriber",)),
            sanitizer=PypdfSanitizer(),
        )

    def _assessment_transcript(self) -> str:
        """The assessment artifact: the declared-identifier line and one region per
        question — the V4 lineage head the submissions' regions are compared against."""
        lines: list[str] = [
            f"Assessment: {self.package_id}",
            "Reference paper for the forces-and-balancing assessment",
            "",
        ]
        for question in self._shape.questions:
            lines.append("")
            lines.append(_wrap_region(
                "transcribed_text", question.question_id, 0.95, question.prompt_text))
            lines.append("")
        return "\n".join(lines).strip("\n")

    def _pages_for(self, submission: Student, *, with_student: bool) -> list[str]:
        """The submission's single page, region-marked per the marker protocol.

        The MCQ's choice is ONE resolved `selection_mark` region with the item line
        left OUTSIDE any marker (V2 fails prose tagged a declared mcq question); each
        open question's evidence line is one `transcribed_text` region. The identity
        lines sit outside the markers too — V3 reads `Student:`, V4 reads
        `Assessment:`."""
        out: list[str] = []
        if with_student:
            out.append(f"Student: {submission.student_ref}")
        out.append(f"Assessment: {self.package_id}")
        for question in self._shape.questions:
            out.append("")
            out.append(f"## {question.question_id}")
            out.append("")
            if question.question_type == "mcq":
                out.append(f"{MCQ}: {submission.mcq}")
                out.append(_wrap_region(
                    "selection_mark", question.question_id, 0.95,
                    submission.mcq, selection=submission.mcq))
                continue
            lines = [
                render_band(cid, self._ordinal_for(submission, cid))
                for cid in self.package.OPEN_CRITERION_IDS
                if self._by_id[cid].question_id == question.question_id
            ]
            out.append(_wrap_region(
                "transcribed_text", question.question_id, 0.90, "\n".join(lines)))
        return ["\n".join(out).strip("\n")]

    def _render_band(self, criterion_id: str, ordinal: int) -> str:
        return render_band(criterion_id, ordinal)

    def _mcq_band_rows(self) -> tuple[tuple[str, int, float], ...]:
        """The MCQ band names the catalog declares — `M-DET` scores with these."""
        return tuple(
            (b.band, b.ordinal, b.points) for b in self._by_id[MCQ].bands
        )

    def _grade_boundaries(self) -> tuple[tuple[str, float], ...]:
        return self._shape.grades

    def _judge_band(self, sid: str, cid: str, judge: str | None = None) -> str:
        """The band THIS arm records.

        The submission's own reference band is what the fixture declares; the panel's
        first two arms answer it and the third answers one ordinal down, so a cell whose
        reference is not already at the bottom shows the panel a disagreement for
        M-ORCH's ladder to widen — and the extension arms answer the reference band, so
        every widened cell settles where the fixture says the work sits. The MCQ
        criterion never reaches here — `M-DET` scores it from the selection mark."""
        assert judge is not None, (
            "the journey's panel disagrees by construction, so a verdict cannot be "
            "chosen without knowing which arm is asking")
        student = self.cohort[self.index_by_sid[sid] - 1]
        reference = student.bands[cid]
        if judge in self.escalation_refs:
            return reference
        arms = [ref.build_id for ref in self.panel_refs]
        assert judge in arms, (
            f"score unit names judge {judge!r} - not one of the world's panel or "
            f"extension arms {arms + list(self.escalation_refs)}")
        if arms.index(judge) < len(arms) - 1:
            return reference
        return _band_name(cid, max(0, self._ordinal_for(student, cid) - 1))

    # -- the build -----------------------------------------------------------------------

    def _build(self) -> None:
        """The package through `rubric_methods.build` (the real M-PKG writer, with the
        `general` derivation recorded and confirmed — what the twins build too), then
        the reference world's own cohort and ingest legs."""
        from tests.support import rubric_methods as rm

        _catalog, self.version = rm.build(self.store, self._shape)
        self.catalog = _catalog
        self._build_cohort()
        self._ingest_assessment()
        self._ingest_submissions()

    def build_run(self) -> str:
        """Create and enumerate the run through the real orchestrator, the dev-ci
        config resolved as the run's config — the config the twins resolve too, so the
        derived extractor, synthesizer, panel and extension arms are the same refs on
        every side. Not started — the journey asserts on the enumeration and the
        estimate first. `HARNESS_FIXTURE_DIR` must be in the environment (the test sets
        it): `_provider_for` answers `dev-ci` with the fixture provider only then."""
        self.orchestrator = Orchestrator(self.store, provider=self.provider)
        resolved = resolve_run_config(
            hosted_cfg("dev-ci", panel=HOSTED_PANEL_3, transcriber=HOSTED_TRANSCRIBER),
            CohortRef(cohort_id=self.cohort_id, consent_class="synthetic"),
        )
        self.resolved = resolved
        self.run_id = self.orchestrator.create_run(
            self.cohort_id, self.version, resolved, run_id=self.run_id)
        self.enumeration = self.orchestrator.enumerate_units(self.run_id)
        self._stage_spans()
        return self.run_id


def _band_name(cid: str, ordinal: int) -> str:
    for band in _by_id()[cid].bands:
        if band.ordinal == ordinal:
            return band.band
    raise KeyError(f"{cid} has no band at ordinal {ordinal}")


# --- the differential's mask -------------------------------------------------------------------


def _sqlite_readonly(path: Path) -> Any:
    import sqlite3

    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _surrogate_rows(data_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """The minted-surrogate rows the differential must pair: every submission with the
    roster name it belongs to, every document with its submission, every region with
    its document, page and element — plus the published package version and every work
    unit with its identity, whose ids are minted or minted-input hashes — read
    read-only from the store files."""
    rows: dict[str, list[dict[str, Any]]] = {
        "submission": [], "document": [], "region": [], "work_unit": [],
        "package_version": [], "escalation_request": [],
    }
    for db in sorted(Path(data_dir).rglob("*.sqlite")):
        connection = _sqlite_readonly(db)
        try:
            names = {r["name"] for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "submission" in names:
                rows["submission"] = [dict(r) for r in connection.execute(
                    "SELECT submission_id, student_ref FROM submission")]
            if "document" in names:
                rows["document"] = [dict(r) for r in connection.execute(
                    "SELECT document_id, submission_id FROM document")]
            if "document_region" in names:
                rows["region"] = [dict(r) for r in connection.execute(
                    "SELECT region_id, document_id, page_no, element_kind, "
                    "region_kind FROM document_region")]
            if "work_unit" in names:
                rows["work_unit"] = [dict(r) for r in connection.execute(
                    "SELECT work_id, submission_id, stage, criterion_id, judge_id, "
                    "origin FROM work_unit")]
            if "package_version" in names:
                rows["package_version"] = [dict(r) for r in connection.execute(
                    "SELECT package_version_id FROM package_version")]
            if "escalation_request" in names:
                rows["escalation_request"] = [dict(r) for r in connection.execute(
                    "SELECT request_id, submission_id, criterion_id FROM "
                    "escalation_request")]
        finally:
            connection.close()
    return rows


def pairing_mask(console_dir: Path, cli_dir: Path) -> dict[str, str]:
    """The surrogate-id mask the row-for-row differential needs, built by PAIRING.

    The two journeys mint different submission, document and region ids for the same
    work (`sub-`/`doc-`/`reg-` prefixed 12-hex ids, too short for
    `console_api_vocabulary.MINTED_ID`), so the mask maps each console id and its CLI
    twin to ONE placeholder, paired through what the row means: submissions through
    the roster name, documents through their submission, regions through their
    document, page and element kind. Everything else — work ids, verdict ids, content
    and policy hashes — is content-addressed and stays unmasked, so a real drift in
    what the pipeline wrote still shows."""
    console, cli = _surrogate_rows(console_dir), _surrogate_rows(cli_dir)
    mask: dict[str, str] = {}

    def make_student_lookup(side: list[dict[str, Any]]):
        by_sid = {str(row["submission_id"]): str(row["student_ref"])
                  for row in side["submission"]}

        def student_of(sid: str | None) -> str:
            if sid is None:
                return "assessment"
            return by_sid.get(sid, sid)

        return student_of

    for side in (console, cli):
        # The published version: minted per build (`RUBRIC-METHODS@<12hex>`), one per
        # store here — both sides map to one placeholder, so every row that cites the
        # version (the run's, the grade's, the audit's, the mcq rollup's) compares.
        versions = sorted(str(row["package_version_id"])
                          for row in side["package_version"])
        assert len(versions) == 1, (
            f"fixture bug: expected one published package version, found {versions}")
        mask[versions[0]] = "<package-version>"
        student_of = make_student_lookup(side)
        docs_by_submission: dict[str | None, list[dict[str, Any]]] = {}
        for row in side["document"]:
            docs_by_submission.setdefault(row["submission_id"], []).append(row)
        for row in side["submission"]:
            sid, student = row["submission_id"], row["student_ref"]
            mask[sid] = f"<student {student}>"
            for order, doc in enumerate(
                    sorted(docs_by_submission.get(sid, []),
                           key=lambda r: str(r["document_id"])), start=1):
                mask[doc["document_id"]] = f"<doc {student} #{order}>"
        assessment = docs_by_submission.get(None, [])
        for order, doc in enumerate(
                sorted(assessment, key=lambda r: str(r["document_id"])), start=1):
            mask[doc["document_id"]] = f"<doc assessment #{order}>"
        regions_by_doc: dict[str, list[dict[str, Any]]] = {}
        for row in side["region"]:
            regions_by_doc.setdefault(str(row["document_id"]), []).append(row)
        for doc_id, regions in regions_by_doc.items():
            placeholder_doc = mask.get(doc_id, doc_id)
            for region in sorted(
                    regions,
                    key=lambda r: (str(r["element_kind"]), int(r["page_no"]),
                                   str(r["region_kind"]))):
                mask[region["region_id"]] = (
                    f"<region {placeholder_doc}:{region['element_kind']}:"
                    f"{region['page_no']}:{region['region_kind']}>")
        # The work units: a unit's id hashes its identity inputs, which include the
        # store's own minted ids, so the twins' ids for the same unit differ. Paired
        # through what the unit IS — student, stage, criterion, judge, origin — both
        # sides map to one placeholder, which also canonicalizes the cell-phase
        # `panel_state` lists that carry the ids.
        for row in side["work_unit"]:
            student = student_of(row["submission_id"])
            judge = row["judge_id"] or "-"
            criterion = row["criterion_id"] or "-"
            mask[row["work_id"]] = (
                f"<work {student}:{row['stage']}:{criterion}:{judge}:{row['origin']}>")
        # The escalation requests: their ids hash their identity inputs, which carry
        # the store's own minted ids. Paired through student and criterion, in a
        # stable order within the group — so a cell that escalated a different NUMBER
        # of times on one side still shows, as a pairing mismatch.
        requests: dict[tuple[str, str], list[str]] = {}
        for row in side["escalation_request"]:
            key = (student_of(row["submission_id"]), str(row["criterion_id"]))
            requests.setdefault(key, []).append(str(row["request_id"]))
        for (student, criterion), ids in requests.items():
            for order, request_id in enumerate(sorted(ids), start=1):
                mask[request_id] = f"<escalation {student}:{criterion}:{order}>"
    return mask


_PANEL_STATE_CELL = re.compile(r"\('panel_state', '([^']*)'\)")


def canonical_tier_rows(data_dir: Path, *, mask: dict[str, str] | None = None,
                        skip_tables: tuple[str, ...] = ("schema_version",)
                        ) -> dict[str, list[str]]:
    """`tier_rows`, with the timing artifacts the differential cannot read as rows
    removed or canonicalized:

    * a `cell_phase` row's `panel_state` lists the units the panel consumed — and the
      LIST ORDER is the order the units happened to complete in, which is scheduler
      variance, not a surface difference (the same set of units is the claim). The
      tokens inside the cell are sorted, so the row compares as a set; the row set
      itself stays order-sensitive.
    * a `work_unit` row's `done_ticks` is the lease clock's tick at completion — a
      monotonic-clock reading, wall-clock by another name — so the cell is dropped,
      the way `tier_rows` drops the `_at`/`_time` columns.
    * `run_metrics` (wall clock, peak concurrency) and `store_lease_clock` (the
      persisted tick and wall-clock head) are timing records no independent drive
      can match, and are skipped entirely.
    """
    rows = tier_rows(data_dir, mask=mask, skip_tables=skip_tables + (
        "run_metrics", "store_lease_clock"))
    for key, lines in rows.items():
        if key.endswith(":cell_phase"):
            rows[key] = [
                _PANEL_STATE_CELL.sub(_sort_panel_state, line) for line in lines
            ]
        elif key.endswith(":work_unit"):
            rows[key] = [_DONE_TICKS_CELL.sub("", line) for line in lines]
    return rows


def _sort_panel_state(match: Any) -> str:
    tokens = sorted(match.group(1).split(","))
    return "('panel_state', '" + ",".join(tokens) + "')"


#: The `work_unit.done_ticks` cell (a monotonic-tick reading) wherever it sits in the
#: row's repr — mid-row with its trailing separator, or last with the leading one.
_DONE_TICKS_CELL = re.compile(r", \('done_ticks', [^)]*\)|\('done_ticks', [^)]*\), ")
