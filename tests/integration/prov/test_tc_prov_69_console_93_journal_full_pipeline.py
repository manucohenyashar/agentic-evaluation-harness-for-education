"""`TC-PROV-69` and `TC-CONSOLE-93` (issue #820): a full fixture pipeline, a drafting job and a
help question, journaled through the entry points' own slot, and where the files land.

Console clarity test plan §3.3, story T7.

| Case | What is asserted |
|---|---|
| PROV-69 (FR-PROV-45) | over the whole run: zero `unlabelled` records; each of `page_reading`, `package_drafting`, `answer_extraction`, `jev_decision`, `ai_judge`, `feedback_writing` and `help_question` appears at least once, and an `ai_judge` record is on the cell the decision engine left below its gate |
| CONSOLE-93 (FR-CONSOLE-77) | the class's calls are under `logs/ai-calls/<cohort_id>/<YYYY-MM-DD>.jsonl` (the file's date is each record's UTC date), the drafting calls under `_packages/<package_id>/`, the help call under `_help/`, and nothing anywhere else; every raw line parses as a JSON object; `python -m aeh run` and the console server each journal with no sink installed by the test, and each leaves the slot as it found it |

**The run.** One data folder, three legs in sequence (rung 3: a real store, the real composed
pipeline, a real console on a loopback port):

1. *The pipeline, through `aeh.pipeline.cli.main(["run", "--data-dir", ...])`.* The CLI's own
   `main` installs the journal; the subcommand body (`_dispatch_command`) is replaced by the
   F-JEV-DECISIONS replay drive: the world's construction (test paper and answer sheets read
   through the real `Ingestor`), then `run_to_completion` with the decision engine on. The real
   `aeh run` body cannot replay this corpus: the recordings are keyed on the corpus's model
   refs (`pipe_world.corpus_refs()`), which the command's config resolution never produces.
2. *A drafting job*, the console's `draft package from documents` action over the recorded
   F-AUTHOR AF-02 documents.
3. *A help question*, the console's `GET /api/v1/help/ask`, answered by the help suite's
   recorded double (`help_vocabulary.QaDouble`, over `RecordedFixtureProvider`) in place of
   `provider_for` — the provider seam, not the journal.

**Disclosed divergences.**

* *ENG7 → F-JEV-DECISIONS.* The plan names "the full fixture pipeline for ENG7"; no recorded
  ENG7 pipeline corpus exists (ENG7 is a live-test package with sample PDFs only). F-JEV-DECISIONS
  is the committed corpus that runs intake, extract, judge with Jev on and synth, and has a
  `below_gate` cell (S2/C1), which is what the case needs.
* *The test paper's class context.* The world reads the test paper by calling
  `Ingestor.ingest_document(kind="assessment")` directly. In production the one caller of that
  is `aeh.pipeline.intake.ingest_files`, which wraps the read in
  `call_context(cohort_id=<class>)`; the world's construction is wrapped the same way here, so
  the strict "nothing under `_unfiled`" oracle holds the production layout. Without the wrap
  that one record is filed under `_unfiled`, which is the world bypassing intake, not a defect.

**Markers.** `integration` (the fast tier excludes it). Not written ahead: #807 is merged.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain before the first store open (CLAUDE.md)
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
from aeh.console import serve_console
from aeh.prov import (
    CALL_KINDS,
    JsonlCallJournal,
    UNLABELLED_KIND,
    call_context,
    installed_call_journal,
    journal_root,
)
from aeh.store import open_store
from tests.support import help_vocabulary as hv
from tests.support import pipe_world
from tests.support.author_vocabulary import RECORDINGS
from tests.support.console_redesign_world import (
    _close_console_store,
    _request,
    draft_read,
    recorded_authoring_config,
    run_draft_job,
)

pytestmark = pytest.mark.integration

COHORT = pipe_world.PIPE_COHORT_ID
#: The kinds TC-PROV-69 requires at least once.
REQUIRED_KINDS = ("page_reading", "package_drafting", "answer_extraction", "jev_decision",
                  "ai_judge", "feedback_writing", "help_question")
DATED_FILE = re.compile(r"\A\d{4}-\d{2}-\d{2}\.jsonl\Z")


@dataclass
class JournaledDay:
    data_dir: Path
    package_id: str
    run_status: str
    cli_exit: int
    #: (submission_id, criterion_id) of every cell the decision engine left below its gate.
    below_gate: set[tuple[str, str]]
    #: The installed slot observed at each boundary: name -> sink (or None).
    slot: dict[str, Any] = field(default_factory=dict)
    #: What the sink in force was while each leg ran.
    sink_seen: dict[str, Any] = field(default_factory=dict)


def _pipeline_leg(day: dict[str, Any], data_dir: Path, mp: pytest.MonkeyPatch) -> None:
    """`python -m aeh run`'s entry point with the corpus drive as the subcommand body."""
    from aeh.pipeline import cli

    def corpus_drive(args: Any) -> int:
        assert Path(args.data_dir) == data_dir
        day["sink_seen"]["cli"] = installed_call_journal()
        # The production intake's own wrap (module docstring): the world reads the test paper
        # around `ingest_files`, so the class context `ingest_files` sets is set here.
        with call_context(cohort_id=COHORT):
            world = pipe_world.jev_replay_world(data_dir, monkeypatch=mp)
        day["world"] = world
        world.build_run()
        world.start_run()
        result = pipe_world.drive_composed(world)
        day["run_status"] = result.status
        return 0 if result.status == "complete" else 3

    mp.setattr(cli, "_dispatch_command", corpus_drive)
    day["slot"]["before cli"] = installed_call_journal()
    day["cli_exit"] = cli.main([
        "run", "--data-dir", str(data_dir), "--cohort", COHORT,
        "--package-version", "corpus-package"])
    day["slot"]["after cli"] = installed_call_journal()


def _console_cfg() -> dict[str, Any]:
    """`recorded_authoring_config()` with its model tables as `ModelRef`s, the form a loaded
    config file carries: the help read resolves its model as `panel[0]` and needs a `ModelRef`
    (the raw-table form is converted by the authoring service only)."""
    from aeh.conf import ModelRef

    cfg = recorded_authoring_config()
    profile = cfg["profiles"]["dev-ci"]
    profile["transcriber"] = ModelRef(quantization=None, **profile["transcriber"])
    profile["panel"] = [ModelRef(quantization=None, **ref) for ref in profile["panel"]]
    return cfg


def _console_leg(day: dict[str, Any], data_dir: Path, scratch: Path,
                 mp: pytest.MonkeyPatch) -> None:
    """The drafting job and the help question through a console served over the same folder."""
    from aeh.console import help_read

    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        mp.delenv(name, raising=False)
    mp.setenv("HARNESS_PROFILE", "dev-ci")
    mp.setenv("HARNESS_FIXTURE_DIR", str(RECORDINGS))
    qa_recordings = scratch / "qa-recordings"
    qa_recordings.mkdir()
    mp.setattr(help_read, "provider_for", lambda _model_ref: hv.QaDouble(qa_recordings))

    store = open_store(data_dir)
    day["slot"]["before console"] = installed_call_journal()
    server = serve_console(store=store, cfg=_console_cfg())
    try:
        day["sink_seen"]["console"] = installed_call_journal()
        port = server.socket.getsockname()[1]
        answer, record = run_draft_job(port, "AF-02")
        assert record["state"] == "succeeded", f"the draft job did not finish: {record!r}"
        day["package_id"] = draft_read(port)["draft"]["package_id"]
        query = urllib.parse.urlencode({"q": hv.QA_MANUALS_QUESTION})
        status, _headers, raw = _request(port, "GET", f"/api/v1/help/ask?{query}")
        assert status == 200, f"the help ask answered {status}: {raw[:400]!r}"
    finally:
        server.terminate()
        day["slot"]["after console"] = installed_call_journal()
        _close_console_store(store)


@pytest.fixture(scope="module")
def journaled_day(tmp_path_factory: pytest.TempPathFactory) -> JournaledDay:
    """The three legs over one data folder. Every knob is set and undone inside the fixture,
    so nothing it sets outlives it (TC-REG-10)."""
    scratch = tmp_path_factory.mktemp("prov69")
    data_dir = scratch / "data"
    data_dir.mkdir()
    assert installed_call_journal() is None, "a sink was already installed before the run"
    day: dict[str, Any] = {"slot": {}, "sink_seen": {}}
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", "0")  # the suite root's pin (conftest)
        _pipeline_leg(day, data_dir, mp)
        world = day.pop("world")
        below_gate = {
            (row["submission_id"], row["criterion_id"])
            for row in world.handle.query(
                "SELECT submission_id, criterion_id FROM decision_prescreen "
                "WHERE outcome = 'below_gate'")}
        world.store.close()
        _console_leg(day, data_dir, scratch, mp)
    return JournaledDay(data_dir=data_dir, package_id=day["package_id"],
                        run_status=day["run_status"], cli_exit=day["cli_exit"],
                        below_gate=below_gate, slot=day["slot"], sink_seen=day["sink_seen"])


def _raw_journal(data_dir: Path) -> dict[Path, list[bytes]]:
    """Every file under the journal root (any name), with its raw lines."""
    root = journal_root(data_dir)
    return {path: path.read_bytes().splitlines()
            for path in sorted(root.rglob("*")) if path.is_file()}


def _parsed(day: JournaledDay) -> list[tuple[Path, dict[str, Any]]]:
    out: list[tuple[Path, dict[str, Any]]] = []
    for path, lines in _raw_journal(day.data_dir).items():
        for line in lines:
            out.append((path, json.loads(line.decode("utf-8"))))
    return out


# --- TC-PROV-69 ---------------------------------------------------------------------------------


def test_tc_prov_69_a_full_pipeline_with_drafting_and_help_labels_every_call(journaled_day):
    """`TC-PROV-69` (FR-PROV-45): zero `unlabelled`, and every pipeline, drafting and help kind
    the plan names appears at least once, `ai_judge` on the below-gate cell."""
    day = journaled_day
    assert day.run_status == "complete" and day.cli_exit == 0, (
        f"the pipeline leg did not complete: {day.run_status!r}, exit {day.cli_exit}")
    records = [record for _path, record in _parsed(day)]
    kinds = Counter(record["kind"] for record in records)
    problems: list[str] = []
    if kinds[UNLABELLED_KIND]:
        unlabelled = [r for r in records if r["kind"] == UNLABELLED_KIND]
        problems.append(f"{kinds[UNLABELLED_KIND]} unlabelled record(s), e.g. model "
                        f"{unlabelled[0]['model']!r} request {str(unlabelled[0]['request'])[:200]}")
    missing = [kind for kind in REQUIRED_KINDS if not kinds[kind]]
    if missing:
        problems.append(f"no record of kind(s) {missing}; census {dict(kinds)}")
    stray = sorted(set(kinds) - set(CALL_KINDS) - {UNLABELLED_KIND})
    if stray:
        problems.append(f"kinds outside the vocabulary: {stray}")
    assert day.below_gate, "precondition: the corpus run left no cell below the decision gate"
    judged_cells = {(r["submission_id"], r["criterion_id"])
                    for r in records if r["kind"] == "ai_judge"}
    if not day.below_gate & judged_cells:
        problems.append(f"no ai_judge record on a below-gate cell {sorted(day.below_gate)}")
    jev_cells = {(r["submission_id"], r["criterion_id"])
                 for r in records if r["kind"] == "jev_decision"}
    if not day.below_gate <= jev_cells:
        problems.append("a below-gate cell has no jev_decision record")
    assert not problems, "\n".join(problems)


# --- TC-CONSOLE-93 ------------------------------------------------------------------------------


def test_tc_console_93_files_land_where_specified_and_every_line_parses(journaled_day):
    """`TC-CONSOLE-93` (FR-CONSOLE-77): the class under `<cohort_id>/`, drafting under
    `_packages/<package_id>/`, help under `_help/`, each file named by its records' UTC date,
    nothing elsewhere, every raw line a JSON object."""
    day = journaled_day
    root = journal_root(day.data_dir)
    raw = _raw_journal(day.data_dir)
    assert raw, f"nothing was journaled under {root}"
    problems: list[str] = []
    for path, lines in raw.items():
        rel = path.relative_to(root)
        if not DATED_FILE.match(path.name):
            problems.append(f"{rel}: not a <YYYY-MM-DD>.jsonl file")
        for number, line in enumerate(lines, 1):
            try:
                document = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                problems.append(f"{rel}:{number} does not parse: {error}")
                continue
            if not isinstance(document, dict):
                problems.append(f"{rel}:{number} is not a JSON object")
                continue
            if path.name != f"{document['at'][:10]}.jsonl":
                problems.append(f"{rel}:{number} is dated {document['at']!r}")
            kind = document["kind"]
            if kind == "help_question":
                expected = Path("_help")
            elif kind == "package_drafting":
                expected = Path("_packages", day.package_id)
                if document["package_id"] != day.package_id:
                    problems.append(f"{rel}:{number} drafting record names package "
                                    f"{document['package_id']!r}, not {day.package_id!r}")
            else:
                expected = Path(COHORT)
                if document["cohort_id"] != COHORT:
                    problems.append(f"{rel}:{number} {kind} record names class "
                                    f"{document['cohort_id']!r}")
            if rel.parent != expected:
                problems.append(f"{rel}:{number} {kind} record is under {rel.parent}, "
                                f"not {expected}")
    folders = {path.relative_to(root).parent for path in raw}
    for folder in (Path(COHORT), Path("_packages", day.package_id), Path("_help")):
        if folder not in folders:
            problems.append(f"no journal file under {folder}; folders {sorted(map(str, folders))}")
    assert not problems, "\n".join(problems[:40])


def test_tc_console_93_both_entry_points_install_the_slot_and_restore_it(journaled_day):
    """`TC-CONSOLE-93`, the slot clause: the test installed no sink; `python -m aeh run` and the
    console each put a `JsonlCallJournal` on the data folder in force while they ran, and left
    the slot empty again when they ended."""
    day = journaled_day
    root = journal_root(day.data_dir)
    for leg in ("cli", "console"):
        sink = day.sink_seen.get(leg)
        assert isinstance(sink, JsonlCallJournal), f"{leg}: no journal in force while it ran"
        assert sink.root == root, f"{leg}: the journal writes to {sink.root}, not {root}"
    assert day.slot == {"before cli": None, "after cli": None,
                        "before console": None, "after console": None}, day.slot
