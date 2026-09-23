"""`PipeWorld` — the assembled system over `F-DEV-PIPE`, and the capture that records it.

Issue #435. The M-PIPE cases need a corpus whose model responses are **already on disk**, so a
self-driving `run_to_completion` can replay a whole run with no network and no record-as-you-go
step. `SynthWorld` cannot be that corpus: it records each response inside its drive loop,
immediately before dispatching it, because a score request is keyed on the assembled prompt
*including the extracted evidence* — so the score prompts do not exist until extraction has
run, and nothing can pre-record what a self-driving composer will ask for.

The way out is not to pre-compute the keys but to **drive the pipeline once and keep what it
recorded**. `capture()` below does exactly that, and the recordings it leaves under
`fixtures/F-DEV-PIPE/recordings/` are what every later run replays from. That is what makes
F-DEV-PIPE a committed corpus rather than a fixture built at test time.

Why the recordings are reproducible
-----------------------------------
Measured, not assumed (#435's probes, on three submissions):

- 265 of 280 recordings were already byte-identical across two independent drives. Minted
  submission ids do not reach the hashed payload for extraction, scoring or transcription —
  `extract.prompt_fields` renders the criterion, question, dependency evidence and the
  submission's *transcript*, and no identifier.
- The 15 that moved were the `l1_question` narratives, and they moved for one reason:
  `synth.prompt_for` puts `request.submission_id` — an opaque `uuid4` minted per ingest
  (`ingest.py:4167`) — straight into the prompt payload. Nothing reads it back out.
- With the mint pinned (`pinned_uuid4`), all 280 match, ids included.

So `PipeWorld` pins the mint around its own construction — the point where `M-INGEST` mints
the submission ids — and every consumer gets the corpus's ids without knowing any of this.
Pinning at construction rather than around the whole drive is enough because the run, work and
document ids minted later never reach a hashed payload, and making it the world's own business
rather than a caller's contract removes the failure mode where a consumer forgets and then
misses every narrative recording with nothing to say why.

The submission-id-in-prompt finding is filed separately: it also means every synthesis request
is a permanent provider-cache miss in production, which is a defect in `M-SYNTH`, not in this
corpus.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import os
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from aeh.prov import Completion, FixtureMissingError, RecordedFixtureProvider
from aeh.conf import ModelRef
from aeh.orch import ESCALATION_BUDGET_ENV
from aeh.synth import LEVEL_L1, LEVEL_L2
from harness.corpora import dev_pipe
from harness.corpora.manifest import CORPUS_ROOT
from tests.support.e2e_world import SynthWorld, _wrap_region
from tests.support.extract_vocabulary import span_completion, verdict_completion

#: The cohort and run the capture drives. Fixed rather than minted: the M-PIPE cases name
#: cells by `(run, submission, criterion)` and a run id that moved per build would make
#: TC-PIPE-08's `(R,S1,C2)` unaddressable.
PIPE_COHORT_ID = "coh-dev-pipe"
PIPE_RUN_ID = "run-dev-pipe"

#: The seed the `uuid4` mint is pinned to, for the reason the module docstring gives. Part of
#: the corpus contract: change it and every narrative recording stops matching.
PINNED_UUID_SEED = 20260104

#: Where the recordings live inside the corpus.
RECORDINGS_DIRNAME = "recordings"


def recordings_dir(root: Path | None = None) -> Path:
    """The committed recordings directory for F-DEV-PIPE."""
    return (root or CORPUS_ROOT) / "F-DEV-PIPE" / RECORDINGS_DIRNAME


def two_run_dir(run: str, root: Path | None = None) -> Path:
    """One of F-DEV-PIPE-TWO-RUN's two recordings directories (`run-a` / `run-b`).

    A directory per set rather than one shared store, because the two sets answer
    byte-identical judge requests with different bands - see `dev_pipe.TWO_RUN_ORDINALS`. The
    corpus carries no manifest or submissions of its own: it IS F-DEV-PIPE's, which is what
    §4.4's *"F-DEV-PIPE plus a second recorded response set"* says.
    """
    assert run in dev_pipe.TWO_RUN_ORDINALS, (
        f"{run!r} is not a declared two-run set: {sorted(dev_pipe.TWO_RUN_ORDINALS)}")
    return (root or CORPUS_ROOT) / "F-DEV-PIPE-TWO-RUN" / run


@contextmanager
def pinned_uuid4(seed: int = PINNED_UUID_SEED) -> Iterator[None]:
    """Pin `uuid.uuid4` to a seeded, collision-free sequence for the duration.

    Process-wide rather than per-module, because the ids that must line up are minted in
    `M-INGEST` while `M-ORCH`, `M-DET`, `M-GRADE` and `M-PKG` mint their own from the same
    function; pinning one module's view would leave the drive's mint order dependent on which
    module called first. Nothing outside the submission ids reaches a hashed payload (the
    265/280 measurement), so the others are pinned only to keep the sequence stable.
    """
    real = uuid.uuid4
    rng = random.Random(seed)
    uuid.uuid4 = lambda: uuid.UUID(int=rng.getrandbits(128), version=4)  # type: ignore[assignment]
    try:
        yield
    finally:
        uuid.uuid4 = real  # type: ignore[assignment]


class StrictReplayProvider:
    """The model boundary for a run that must invent nothing.

    `JourneyProvider` answers a first sight of an unknown request from the world's own
    computation and records it. That is right for a journey and wrong for F-DEV-PIPE's fifth
    acceptance criterion, where a request with no recording is the failure being tested for:
    a fallback would silently paper over exactly the gap the case exists to find. So this
    wrapper replays and, on a miss, says which request had no answer.
    """

    def __init__(self, fixture_dir: Any) -> None:
        self._inner = RecordedFixtureProvider(fixture_dir=fixture_dir)
        self.replayed_calls = 0
        self.misses: list[dict[str, str]] = []

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        try:
            completion = self._inner.complete(prompt, model_ref, params)
        except FixtureMissingError as error:
            fields = dict(prompt.fields)
            self.misses.append({
                "role": model_ref.role,
                "build_id": model_ref.build_id,
                "fields": ", ".join(sorted(fields)[:6]),
            })
            raise AssertionError(
                f"F-DEV-PIPE has no recording for a {model_ref.role} request on build "
                f"{model_ref.build_id!r} (fields: {sorted(fields)[:6]}). The corpus is "
                f"incomplete for a run driven without record-as-you-go - re-capture it with "
                f"`python -m tests.support.pipe_world`."
            ) from error
        self.replayed_calls += 1
        return completion

    def record(self, prompt: Any, model_ref: Any, params: Any,
               completion: Any) -> str:  # pragma: no cover - guarded by the world
        raise AssertionError(
            "a replay-only world recorded a response - the point of the replay drive is that "
            "every reply is already on disk"
        )

    def stage_transcript(self, blob_hash: str, pages: dict[int, str]) -> None:
        """Accepted and ignored: the transcription replies replay from the corpus like every
        other request, so there is nothing to stage."""

    def unavailable(self) -> bool:
        return False

    def estimate_cost(self, unit: Any) -> Decimal:
        return Decimal("0.001")


class PipeWorld(SynthWorld):
    """`SynthWorld` over `PKG-DEV-PIPE`: 3 submissions, 2 judged criteria and one MCQ.

    Every difference from the reference world goes through one of the seams `SynthWorld`
    declares, so the drive — orchestrator, deterministic evaluator, extraction workers,
    integrity gate, aggregation walk, synthesis worker and closer — is the same code the three
    journeys run. A second copy of the drive is a second place for it to be wrong.
    """

    def __init__(self, data_dir: Any, fixture_dir: Any, *,
                 uniform_panel_ordinal: int | None = None, **kwargs: Any) -> None:
        # `F-DEV-PIPE-TWO-RUN`'s mode: every judged criterion's panel unanimous at ONE ordinal,
        # every arm, every submission - §4.4's `(1,1,1)` and `(3,3,3)`. None is F-DEV-PIPE's
        # own shape, where the panel varies per criterion and per submission.
        self.uniform_panel_ordinal = uniform_panel_ordinal
        kwargs.setdefault("cohort_id", PIPE_COHORT_ID)
        kwargs.setdefault("run_id", PIPE_RUN_ID)
        # The mint is pinned around CONSTRUCTION, which is where `ingest_submission` mints the
        # submission ids - the only minted value that reaches a hashed prompt payload
        # (`synth.prompt_for`). Pinning here rather than asking callers to wrap the drive
        # makes the corpus self-contained: a consumer that forgot would re-mint different ids
        # and miss every narrative recording, with nothing to say why. The run and work ids
        # minted later are free to vary, because nothing hashes them.
        # The corpus is captured and replayed with the escalation budget raised, for the
        # reason `CORPUS_ESCALATION_BUDGET` gives: at the shipped default M-ORCH defers this
        # cohort's widened pairs and the run can never reach a pending count of zero.
        monkeypatch = kwargs.get("monkeypatch")
        if monkeypatch is not None:
            monkeypatch.setenv(ESCALATION_BUDGET_ENV, CORPUS_ESCALATION_BUDGET)
        else:
            os.environ[ESCALATION_BUDGET_ENV] = CORPUS_ESCALATION_BUDGET
        with pinned_uuid4():
            self._construct(data_dir, fixture_dir, **kwargs)

    def _construct(self, data_dir: Any, fixture_dir: Any, **kwargs: Any) -> None:
        super().__init__(
            data_dir,
            fixture_dir,
            n_submissions=dev_pipe.DEV_PIPE_COUNT,
            # No quarantines: three submissions, and every M-PIPE case needs all three
            # admitted. The quarantine path is `SynthWorld`'s subject, not this corpus's.
            quarantine_indices=(),
            package=dev_pipe,
            **kwargs,
        )

    def _make_provider(self, fixture_dir: Any) -> Any:
        """`JourneyProvider` while capturing; the strict replayer once the corpus exists."""
        if self.record_as_you_go:
            return CaptureProvider(self, fixture_dir)
        return StrictReplayProvider(fixture_dir)

    # -- the corpus seams ------------------------------------------------------------------------

    def _cohort_submissions(self, n_submissions: int) -> tuple[Any, ...]:
        return dev_pipe.dev_pipe_set()[:n_submissions]

    def _render_band(self, criterion_id: str, ordinal: int) -> str:
        return dev_pipe.render_band(criterion_id, ordinal)

    def _mcq_band_rows(self) -> tuple[tuple[str, int, float], ...]:
        """The corpus's own declaration of the mcq band names.

        Returns the same `incorrect` / `correct` pair the base does — `M-DET` produces those
        names itself and prices them through the catalog, so neither package is free to choose
        (see `dev_pipe.MCQ_BANDS`). The override earns its place by sourcing them from the
        CORPUS rather than from `e2e_world`'s constant: the manifest's `reference_bands` and
        the band the run writes then come from one declaration, and a corpus whose reference
        labels disagree with its own run's output is one no agreement figure means anything
        against.
        """
        return tuple((b, o, p) for b, o, p, _descriptor in dev_pipe.MCQ_BANDS)

    def _grade_boundaries(self) -> tuple[tuple[str, float], ...]:
        """Scaled to this package's 11 points, at the same proportions the reference world
        uses (33/47, 24/47, 15/47). The reference table's floors sit above this package's
        maximum on two of four bands, which would put every submission in `D`."""
        return (("A", 7.5), ("B", 5.5), ("C", 3.5), ("D", 0.0))

    def _assessment_transcript(self) -> str:
        """The assessment artifact: the declared-identifier line and one region per question."""
        lines: list[str] = [
            f"Assessment: {self.package_id}",
            "Reference paper for the ramp equilibrium assessment",
            "",
        ]
        for question in dev_pipe.QUESTIONS:
            lines.append("")
            lines.append(_wrap_region(
                "transcribed_text", question.question_id, 0.95, question.prompt))
            lines.append("")
        return "\n".join(lines).strip("\n")

    def _pages_for(self, submission: Any, *, with_student: bool) -> list[str]:
        """The submission's single page, region-marked per the marker protocol.

        `Q1`'s prose becomes one `transcribed_text` region; `Q2`'s item line becomes ONE
        resolved `selection_mark` region with the item line left OUTSIDE any marker, because
        V2 fails prose tagged a declared mcq question. The identity lines sit outside the
        markers too — V3 reads `Student:` and V4 reads `Assessment:`.
        """
        raw = submission.pages[0].split("\n")
        assert raw[0].startswith("Page 1 of 1"), (
            "fixture bug: the F-DEV-PIPE page header moved")
        out: list[str] = [raw[0], ""]
        if with_student:
            out.append(f"Student: {submission.student_ref}")
        out.append(f"Assessment: {self.package_id}")

        current: str | None = None
        block: list[str] = []

        def flush() -> None:
            nonlocal current, block
            if current is None or not block:
                current, block = None, []
                return
            if current == dev_pipe.QUESTIONS[1].question_id:
                choice = self._mcq_choice(block)
                out.append("")
                out.append(_wrap_region(
                    "selection_mark", current, 0.95, choice, selection=choice))
                out.append("")
                out.extend(block)
            else:
                out.append("")
                out.append(_wrap_region(
                    "transcribed_text", current, 0.90, "\n".join(block)))
            current, block = None, []

        for line in raw[1:]:
            if line.startswith("## "):
                flush()
                current = line[3:].strip()
                out.append("")
                out.append(f"## {current}")
            elif line.strip() and current is not None:
                block.append(line)
        flush()
        return ["\n".join(out).strip("\n")]

    @staticmethod
    def _mcq_choice(item_lines: list[str]) -> str:
        """The option letter the page's MCQ item line carries."""
        for cid in dev_pipe.MCQ_CRITERION_IDS:
            prefix = f"{cid}: "
            for line in item_lines:
                if line.startswith(prefix):
                    choice = line[len(prefix):].strip()
                    assert choice in dev_pipe.MCQ_OPTIONS, (
                        f"fixture bug: {line!r} carries no declared option")
                    return choice
        raise AssertionError(
            "fixture bug: the F-DEV-PIPE page carries no MCQ item line")

    # -- the disagreeing panel -------------------------------------------------------------------

    def _judge_band(self, sid: str, cid: str, judge: str | None = None) -> str:
        """The band THIS arm records — §4.4's `(2,4,4)` on `C2`, or a two-run set's uniform band.

        The reference world's arms all return the submission's own corpus band, so its panels
        agree and nothing escalates. F-DEV-PIPE's whole purpose includes the escalation half of
        TC-PIPE-08, so the arm's position in the panel selects its ordinal from
        `dev_pipe.PANEL_ORDINALS`, and the two extension arms read `ESCALATION_ORDINALS`.

        The MCQ criterion never reaches here — `M-DET` scores it from the selection mark.
        """
        assert judge is not None, (
            "PipeWorld's panel disagrees by construction, so a verdict cannot be chosen "
            "without knowing which arm is asking")
        if self.uniform_panel_ordinal is not None:
            # The two-run sets: one ordinal for every arm, every judged criterion and every
            # submission, extension arms included - so each run's cells settle unanimously and
            # a band that leaked between runs is visible as a band.
            return dev_pipe.band_at(cid, self.uniform_panel_ordinal)
        #: The submission's own reference band — what a criterion with no declared panel
        #: answers, on every arm. `C1` reads differently on each of the three submissions
        #: because of this; a constant would make the panel ignore the student's work.
        reference = self.cohort[self.index_by_sid[sid] - 1].bands[cid]

        arms = list(self.escalation_refs)
        if judge in arms:
            escalation = dev_pipe.ESCALATION_ORDINALS.get(cid)
            if escalation is None:
                # A criterion that escalates without declaring extension bands settles where
                # its panel already sat. `C1` reaches here on any interior band, which on a
                # six-band scale is most of them.
                return reference
            return dev_pipe.band_at(cid, escalation[arms.index(judge)])

        panel = dev_pipe.PANEL_ORDINALS.get(cid)
        arms = [ref.build_id for ref in self.panel_refs]
        assert judge in arms, (
            f"score unit names judge {judge!r} - not one of the world's panel or "
            f"extension arms {arms + list(self.escalation_refs)}")
        if panel is None:
            return reference
        return dev_pipe.band_at(cid, panel[arms.index(judge)])


# --- the capture ----------------------------------------------------------------------------


def drive_full_run(world: PipeWorld, *, monkeypatch: Any = None) -> None:
    """One complete pass in §4.2.2's order — the same sequence journey 2 drives."""
    world.build_run()
    world.start_run()
    world.drive_deterministic()
    world.integrity_pass()
    world.drive_extract()
    world.drive_score()
    world.integrity_pass(capture=True)
    world.aggregate_walk(monkeypatch=monkeypatch)
    world.drive_score(include_escalations=True)
    world.aggregate_walk(monkeypatch=monkeypatch)
    world.drive_synthesis()
    world.finalize()


def drive_second_run(world: PipeWorld, run: str, *, run_id: str | None = None,
                     monkeypatch: Any = None) -> str:
    """Drive a SECOND run over the same store, from the other two-run recording set.

    This is the shape every two-run isolation case needs (TC-GRADE-25, ADV-13): one cohort,
    one ingest, one package, two runs whose judged bands differ. The world is rebound to the
    other set's recordings and given a fresh run id; everything else — submissions, documents,
    extraction — is the run before's, which is what makes a leak between the two visible.

    Returns the new run id.

    `Orchestrator` is imported HERE rather than at module scope, deliberately. `aeh.extract`
    and `aeh.judge` resolve `select_document_head` through the SHARED statement registry
    (`extract.py:84`, `judge.py:209` alias `store.STATEMENTS`, not `ingest.INGEST_STATEMENTS`),
    and `det.py:750` overwrites that key with a five-column spelling that has no `markdown`.
    Whichever module imports last wins, so a consumer whose first `aeh` import is `aeh.orch`
    gets det's spelling and extraction dies far away at `head["markdown"]` with
    `IndexError: No item with that key`. Importing inside the function keeps `e2e_world`'s
    eleven-module chain first in every caller. Reported separately — it is a defect in the
    registry, not in this corpus, and the workaround belongs here only until it is fixed.
    """
    from aeh.orch import Orchestrator

    world.run_id = run_id or f"{PIPE_RUN_ID}-{run}"
    world.uniform_panel_ordinal = dev_pipe.TWO_RUN_ORDINALS[run]
    world.provider = StrictReplayProvider(two_run_dir(run))
    world.orchestrator = Orchestrator(world.store, provider=world.provider)
    world.build_run()
    world.start_run()
    drive_composed(world)
    return world.run_id


def capture_all() -> dict[str, int]:
    """Capture F-DEV-PIPE and both F-DEV-PIPE-TWO-RUN sets. The entry point.

    Three drives of the same pipeline over the same submissions, differing only in what the
    panel answers. Returns the recording count per set.
    """
    counts = {"F-DEV-PIPE": capture()}
    for run, ordinal in dev_pipe.TWO_RUN_ORDINALS.items():
        counts[f"F-DEV-PIPE-TWO-RUN/{run}"] = capture(
            two_run_dir(run), uniform_panel_ordinal=ordinal)
    return counts


def capture(destination: Path | None = None, *,
            uniform_panel_ordinal: int | None = None) -> int:
    """Drive the corpus once with record-as-you-go and keep what it recorded.

    Returns the number of recordings written. The destination is emptied first: a stale
    recording nothing asks for any more would sit in the corpus forever, and `--check` does not
    look inside a recorded golden.

    With `uniform_panel_ordinal` this captures one of the two-run sets instead — same
    submissions, same extraction, a panel unanimous at that ordinal.
    """
    import tempfile

    target = destination or recordings_dir()
    # `ignore_cleanup_errors` because the store's sqlite handles are not all closed by
    # `store.close()` on this platform — the grade pass opens its own — and Windows refuses to
    # unlink an open file. The scratch directory is the OS's to reap; failing the capture over
    # it would throw away a drive that succeeded.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        scratch = Path(tmp)
        data_dir = scratch / "data"
        for sub in ("packages", "cohorts", "blobs"):
            (data_dir / sub).mkdir(parents=True)
        staging = scratch / "recordings"
        world = PipeWorld(data_dir, staging,
                          uniform_panel_ordinal=uniform_panel_ordinal)
        world.build_run()
        world.start_run()
        result = drive_composed(world)
        assert result.status == "complete", (
            f"the capture drive did not complete: status={result.status!r} "
            f"reason={result.pause_reason!r}")
        world.store.close()

        written = sorted(staging.rglob("*.json"))
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for path in written:
            # Rewritten with explicit LF rather than copied. `RecordedFixtureProvider.record`
            # writes through the platform's default newline, so a capture on Windows lands
            # CRLF - and `.gitattributes` pins `fixtures/**` to LF because content addressing
            # is over bytes. Copying verbatim would make every re-capture on a different
            # platform a diff of 52 files that say the same thing.
            text = path.read_text(encoding="utf-8")
            (target / path.name).write_text(text, encoding="utf-8", newline="\n")
    return len(written)


def two_run_replay_world(data_dir: Path, run: str, *, monkeypatch: Any = None) -> PipeWorld:
    """A `PipeWorld` bound to one of F-DEV-PIPE-TWO-RUN's sets, replay-only.

    The ordinal is passed as well as the directory, and both come from the same declaration
    (`dev_pipe.TWO_RUN_ORDINALS`). The drive checks each replayed verdict against the band it
    expected for that arm (`e2e_world._drive_score_unit`), so a world pointed at `run-b`'s
    recordings while expecting `run-a`'s bands fails immediately rather than scoring a run out
    of the wrong set - which is the exact confusion a two-run isolation case exists to catch.
    """
    return replay_world(
        data_dir,
        recordings=two_run_dir(run),
        monkeypatch=monkeypatch,
        uniform_panel_ordinal=dev_pipe.TWO_RUN_ORDINALS[run],
    )


def replay_world(data_dir: Path, *, recordings: Path | None = None,
                 monkeypatch: Any = None,
                 uniform_panel_ordinal: int | None = None) -> PipeWorld:
    """A `PipeWorld` bound to the COMMITTED recordings, with the mint pinned.

    The supported way to drive F-DEV-PIPE without recording: every request the run assembles
    has its reply on disk already, so `RecordedFixtureProvider` answers from the corpus and
    never falls through. Callers need no ceremony — `PipeWorld` pins the mint around its own
    construction, which is where the ids that reach a prompt are minted.
    """
    for sub in ("packages", "cohorts", "blobs"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    return PipeWorld(data_dir, recordings or recordings_dir(), monkeypatch=monkeypatch,
                     record_as_you_go=False,
                     uniform_panel_ordinal=uniform_panel_ordinal)




# --- capturing through the composed pipeline ------------------------------------------------

#: The model identities the corpus is recorded against.
#:
#: They are declared HERE, by the corpus, rather than derived from `RunConfig` — because
#: `RunConfig` has no field for an extractor or a synthesizer (`M-PIPE`'s module docstring,
#: gap 2) and extension arms are not panel members (gap 3). A consumer replaying the corpus
#: passes these to `run_to_completion`; `corpus_refs()` hands over the whole set so nobody has
#: to reassemble it from three places and get one wrong.
CORPUS_EXTRACTOR_BUILD = "vlm@sha256:e2e02-extract"
CORPUS_SECOND_FAMILY_BUILD = "vlm@sha256:e2e02-extract-b"
CORPUS_SYNTH_BUILD = "vlm@sha256:e2e02-synth"
CORPUS_ESCALATION_ARMS = ("escalation-arm-4", "escalation-arm-5")

#: The escalation budget the corpus is captured and replayed under.
#:
#: The shipped default is 0.3 and F-DEV-PIPE escalates four of its six judged cells, so at the
#: default `M-ORCH` DEFERS the widened pairs and marks them provisional — the run's pending
#: count never reaches zero and it cannot complete. That is the budget working as designed on a
#: cohort too small to grow headroom, and the journeys raise it for the same reason. Raised
#: here so the corpus contains its escalation calls at all: §4.4 requires them recorded.
CORPUS_ESCALATION_BUDGET = "1.0"


def _corpus_ref(role: str, build_id: str) -> Any:
    return ModelRef(role=role, provider="local", build_id=build_id, quantization="q4")


def corpus_refs() -> dict[str, Any]:
    """Every model identity `run_to_completion` needs to replay this corpus, as keywords."""
    return {
        "extractor": _corpus_ref("extractor", CORPUS_EXTRACTOR_BUILD),
        "second_family": _corpus_ref("extractor", CORPUS_SECOND_FAMILY_BUILD),
        "synthesizer": _corpus_ref("synthesizer", CORPUS_SYNTH_BUILD),
        "judge_refs": {
            arm: _corpus_ref("judge", arm) for arm in CORPUS_ESCALATION_ARMS
        },
        "high_risk_criteria": dev_pipe.OPEN_CRITERION_IDS,
    }


class CaptureProvider:
    """The model boundary while CAPTURING through the composed pipeline.

    `JourneyProvider` cannot do this job. It answers a first sight of an unknown request only
    for transcription and synthesis, because the hand-rolled drive pre-recorded every extract
    and score reply immediately before dispatching it. `run_to_completion` pre-records nothing
    — it hands units to the stage workers and the workers call the provider — so the capture
    needs a boundary that can answer an extraction or a verdict *on demand*.

    It answers from the corpus's own declarations, which is the same knowledge the old drive
    used, reached differently: the cell is recovered from the REQUEST (`criterion_id: C1` in
    the criterion field, `Page 1 of 1 - S1` in the submission block) instead of being known in
    advance, and the reply is then the span set or the panel ordinal `dev_pipe` declares for
    that cell. Nothing is invented here that the corpus does not already state.
    """

    _CRITERION = re.compile(r"criterion_id:\s*(\S+)")
    _SUBMISSION = re.compile(r"Page\s+\d+\s+of\s+\d+\s+-\s+(\S+)")

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
            return self._completion(_synth_reply(fields), model_ref)
        if role == "extractor":
            return self._extraction(fields, model_ref)
        if role == "judge":
            return self._verdict(fields, model_ref)
        raise AssertionError(
            f"the capture has no reply for a {role!r} request: fields {sorted(fields)[:6]}")

    def _cell(self, fields: dict) -> tuple[str, str]:
        """The (store submission id, criterion id) this request is about, from the request."""
        criterion = self._CRITERION.search(fields.get("criterion", "") or "")
        submission = self._SUBMISSION.search(fields.get("submission", "") or "")
        if criterion is None or submission is None:
            raise AssertionError(
                "the capture cannot tell which cell a request is about: "
                f"criterion={criterion}, submission={submission}")
        corpus_id = submission.group(1)
        index = 1 + next(
            i for i, s in enumerate(self._world.cohort)
            if s.submission_id == corpus_id
        )
        return self._world.sid_by_index[index], criterion.group(1)

    def _extraction(self, fields: dict, model_ref: Any) -> Any:
        sid, cid = self._cell(fields)
        spans = self._world.spans_by_cell[(sid, cid)]
        return span_completion(spans, build_id=model_ref.build_id)

    def _verdict(self, fields: dict, model_ref: Any) -> Any:
        sid, cid = self._cell(fields)
        spans = self._world.spans_by_cell[(sid, cid)]
        band = self._world._judge_band(sid, cid, judge=model_ref.build_id)
        return verdict_completion(
            band, 0.9, build_id=model_ref.build_id, cited_spans=spans)

    @staticmethod
    def _completion(text: str, model_ref: Any) -> Any:
        return Completion(
            text=text, tokens_in=10, tokens_out=5, latency_ms=1,
            resolved_build=model_ref.build_id, cached_prefix_tokens=0, cost=None,
        )


def _synth_reply(fields: dict) -> str:
    """The narrative reply, numeral-free so the score-claim ladder leaves it unflagged."""
    if fields.get("level") == LEVEL_L1:
        criteria = [c.strip() for c in fields.get("criteria", "").split(",") if c.strip()]
        return json.dumps({
            "narrative": (
                "The response addresses the criteria the panel read, citing the work's own "
                "words as evidence; where the work stops short, the narrative says so in the "
                "same terms the criteria name."
            ),
            "citations": criteria,
        })
    return json.dumps({
        "narrative": (
            "The submission's questions are narrated above; the whole reads as one response "
            "whose strengths and gaps the question narratives already state."
        ),
        "citations": [],
    })


def drive_composed(world: Any, **overrides: Any) -> Any:
    """Drive the whole run through `M-PIPE` — the door this corpus exists to serve.

    This replaces the hand-rolled walk for every purpose that matters. `#364`'s technical notes
    say the walk goes once `run_to_completion` lands, and a corpus captured through a drive
    nobody ships is a corpus keyed on requests the shipped composer never makes: the earlier
    capture recorded its narratives under the journey baseline's escalate-everything panel,
    and production escalates four of six cells, so two of three L1 prompts missed.
    """
    from aeh.pipeline import run_to_completion

    keywords = corpus_refs()
    keywords.update(overrides)
    return run_to_completion(
        world.store, world.run_id, provider=world.provider,
        run_config=world.resolved, **keywords,
    )


if __name__ == "__main__":  # pragma: no cover - the capture entry point
    for _name, _count in capture_all().items():
        print(f"wrote {_count} recordings for {_name}")
