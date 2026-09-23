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

So the capture pins the mint, and a replaying run pins it the same way. `PINNED_UUID_SEED` is
part of the corpus contract, not a detail of the capture script — a consumer that does not pin
it re-mints different ids and misses every narrative recording. `replay_world()` is the
supported way to get that right without knowing the trick.

The submission-id-in-prompt finding is filed separately: it also means every synthesis request
is a permanent provider-cache miss in production, which is a defect in `M-SYNTH`, not in this
corpus.
"""

from __future__ import annotations

import random
import shutil
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator

from aeh.prov import FixtureMissingError, RecordedFixtureProvider
from harness.corpora import dev_pipe
from harness.corpora.manifest import CORPUS_ROOT
from tests.support.e2e_world import SynthWorld, _wrap_region

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

    def __init__(self, data_dir: Any, fixture_dir: Any, **kwargs: Any) -> None:
        kwargs.setdefault("cohort_id", PIPE_COHORT_ID)
        kwargs.setdefault("run_id", PIPE_RUN_ID)
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
            return super()._make_provider(fixture_dir)
        return StrictReplayProvider(fixture_dir)

    # -- the corpus seams ------------------------------------------------------------------------

    def _cohort_submissions(self, n_submissions: int) -> tuple[Any, ...]:
        return dev_pipe.dev_pipe_set()[:n_submissions]

    def _render_band(self, criterion_id: str, ordinal: int) -> str:
        return dev_pipe.render_band(criterion_id, ordinal)

    def _mcq_band_rows(self) -> tuple[tuple[str, int, float], ...]:
        """`not_met` / `met` — the corpus's own names.

        The reference world renames these to `incorrect` / `correct`; here the catalog
        declares what `dev_pipe` declares, so the manifest's `reference_bands` and the band
        `M-DET` writes are the same string. A corpus whose reference labels disagree with the
        run's own output is a corpus no agreement figure means anything against.
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
        """The band THIS arm records — §4.4's `(2,4,4)` on `C2`.

        The reference world's arms all return the submission's own corpus band, so its panels
        agree and nothing escalates. F-DEV-PIPE's whole purpose includes the escalation half of
        TC-PIPE-08, so the arm's position in the panel selects its ordinal from
        `dev_pipe.PANEL_ORDINALS`, and the two extension arms read `ESCALATION_ORDINALS`.

        The MCQ criterion never reaches here — `M-DET` scores it from the selection mark.
        """
        assert judge is not None, (
            "PipeWorld's panel disagrees by construction, so a verdict cannot be chosen "
            "without knowing which arm is asking")
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


def capture(destination: Path | None = None) -> int:
    """Drive F-DEV-PIPE once with record-as-you-go and keep what it recorded.

    Returns the number of recordings written. The destination is emptied first: a stale
    recording nothing asks for any more would sit in the corpus forever, and `--check` does not
    look inside a recorded golden.
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
        with pinned_uuid4():
            world = PipeWorld(data_dir, staging)
            drive_full_run(world)
            world.store.close()

        written = sorted(staging.rglob("*.json"))
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for path in written:
            shutil.copy2(path, target / path.name)
    return len(written)


def replay_world(data_dir: Path, *, recordings: Path | None = None,
                 monkeypatch: Any = None) -> PipeWorld:
    """A `PipeWorld` bound to the COMMITTED recordings, with the mint pinned.

    The supported way to drive F-DEV-PIPE without recording: every request the run assembles
    has its reply on disk already, so `RecordedFixtureProvider` answers from the corpus and
    never falls through. Callers stay inside `pinned_uuid4` for the whole drive — see the
    module docstring on why the mint is part of the contract.
    """
    for sub in ("packages", "cohorts", "blobs"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    return PipeWorld(data_dir, recordings or recordings_dir(), monkeypatch=monkeypatch,
                     record_as_you_go=False)


if __name__ == "__main__":  # pragma: no cover - the capture entry point
    count = capture()
    print(f"wrote {count} recordings to {recordings_dir()}")
