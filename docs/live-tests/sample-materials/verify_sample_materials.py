#!/usr/bin/env python3
"""Check the sample PDFs against the system's real intake gates, with no network and no model.

What this proves, and what it does not
--------------------------------------
It builds the two sample packages from the package specs the live test uses
(`config/ps9-forces-01.package.toml`, `config/eng7-read-01.package.toml`) through the real
`aeh package build` code, creates each class from its shipped roster file, and sends every
sample PDF through the real intake (`aeh.ingest.Ingestor`): the file integrity gate (V0),
page-count gate (V1), structure gate (V2), identity gate (V3) and right-test gate (V4), then
prints what each sheet did.

It then checks the rubric methods (FR-PKG-24): between them the two packages carry every
scoring method the system supports (`bands`, `evidence_sum`, `general`, and the multiple-choice
key lookup), and a `dev-ci` run created from `config/live-test.dev-ci.toml` over the admitted
sheets enumerates work for every rubric line except the evidence-sum composite, which is never
dispatched (FR-JUDGE-38): its two aspects are. No model is called and no key is needed: the run
is created and its work listed, never started.

The one thing replaced is the page-reading model. A scripted stand-in returns the page text a
perfect reader would produce (the header lines carried over verbatim, one marked region per
answer). So this proves the SAMPLE FILES and the intake rules fit together: that a good sheet is
admitted, and that the wrong-test sheet, the sheet with no name and the sheet with two marks are
parked. It does NOT prove that a live page-reading model reads these pages that well. That is the
live test's job.

Run from the repository root. It needs the system installed (`pip install .`, which brings the
libraries that read PDFs with it):

    python docs/live-tests/sample-materials/verify_sample_materials.py

    -v               also print the four right-test signals for every sheet
    --answers-only   play a page reader that returns ONLY the student's handwriting, not the printed
                     question beside it. Many good sheets are then parked by the right-test check;
                     this reproduces the risk described in 02-live-readiness-and-blockers.md. In
                     this mode the script reports the outcome and exits 0 whatever it is.

It writes its working files into a fresh private folder under your home directory and removes
them afterwards. The system refuses to keep student work in a world-writable folder such as /tmp,
which is why the folder is under your home directory.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "src"))

import aeh.agg  # noqa: F401,E402  — all eleven modules that own a migration, before the first open
import aeh.det  # noqa: F401,E402
import aeh.extract  # noqa: F401,E402
import aeh.grade  # noqa: F401,E402
import aeh.ingest  # noqa: F401,E402
import aeh.integ  # noqa: F401,E402
import aeh.judge  # noqa: F401,E402
import aeh.orch  # noqa: F401,E402
import aeh.pkg  # noqa: F401,E402
import aeh.review  # noqa: F401,E402
import aeh.synth  # noqa: F401,E402

import build_sample_materials as sm  # noqa: E402
from aeh.conf import ModelRef, effective_config, parse_config_document  # noqa: E402
from aeh.conf import resolve_run_config  # noqa: E402
from aeh.ingest import Ingestor, PdfiumRasterizer, PypdfSanitizer, ResidencySlot  # noqa: E402
from aeh.orch import Orchestrator  # noqa: E402
from aeh.orch.cohorts import create_cohort  # noqa: E402
from aeh.pipeline.packages import build_package, read_package_spec  # noqa: E402
from aeh.pipeline.rosters import read_roster_file  # noqa: E402
from aeh.pkg import PackageCatalog  # noqa: E402
from aeh.prov import Completion, SamplingParams  # noqa: E402
from aeh.store import open_store  # noqa: E402

CONFIG = HERE.parent / "config"
LIVE_CONFIG = CONFIG / "live-test.dev-ci.toml"

# The package spec and the class list the live test uses for each sample test.
MATERIALS = {
    sm.PHYSICS_ID: (CONFIG / "ps9-forces-01.package.toml", CONFIG / "ps9-roster.txt"),
    sm.ENGLISH_ID: (CONFIG / "eng7-read-01.package.toml", CONFIG / "eng7-roster.txt"),
}

# The scoring method of each rubric line, in the live-test guide's words. `key` is a
# multiple-choice line: stored as a two-band line and marked by key lookup, never judged.
EXPECTED_METHODS = {
    sm.PHYSICS_ID: {"C1": "key", "C2": "key", "C3": "key", "C4": "bands", "C5": "key",
                    "C6": "bands"},
    sm.ENGLISH_ID: {"C1": "evidence_sum", "C1a": "aspect of C1", "C1b": "aspect of C1",
                    "C2": "bands", "C3": "general"},
}

TRANSCRIBER = ModelRef(role="transcriber", provider="local", build_id="scripted-reader@sha256:0",
                       quantization="q4")


# What the live-test guide tells the operator to expect for each sample sheet at intake.
EXPECTED_STATUS = {
    "S9-001-strong": "ok", "S9-002-middle": "ok", "S9-003-weak": "ok",
    "S9-004-doubled-mark-and-blank": "incomplete",   # two marks on Q1: structure gate (V2) fails
    "S9-005-wrong-test": "unmatched_assessment",     # names another test: right-test gate (V4) mismatch
    "S9-006-no-name": "incomplete",                  # no student name: identity gate (V3) unmatched
    "E7-001-strong": "ok", "E7-002-middle": "ok", "E7-003-weak": "ok", "E7-004-mostly-blank": "ok",
}


class ScriptedReader:
    """Stands in for the page-reading model: answers a page request with the text staged for it.

    It answers with perfect markup whatever it is asked, so it also checks what it was asked: a
    page request must state the mark protocol (`selection=`) and name the package's questions.
    A reader that ignored its request is how the first live run's markup bug got past this
    check (TC-REG-15)."""

    def __init__(self) -> None:
        self.pages: dict[tuple[str, int], str] = {}
        self.request_problems: list[str] = []

    def stage(self, blob: str, pages: list[str]) -> None:
        for number, text in enumerate(pages, start=1):
            self.pages[(blob, number)] = text

    def unavailable(self) -> bool:
        return False

    def complete(self, prompt, model_ref, params) -> Completion:
        fields = dict(prompt.fields)
        if fields.get("instruction", "").startswith("Decide whether"):
            # The right-test gate's optional second opinion: recorded, never applied.
            return Completion(text="uncertain", tokens_in=10, tokens_out=1, latency_ms=1,
                              resolved_build=model_ref.build_id, cached_prefix_tokens=0, cost=None)
        key = (fields.get("source_blob_hash"), int(fields["page_no"]))
        if "selection=" not in fields.get("instruction", ""):
            self.request_problems.append(f"page {key[1]}: the prompt never asks for selection=")
        if not fields.get("declared_questions"):
            self.request_problems.append(f"page {key[1]}: the request names no declared questions")
        if key not in self.pages:
            raise AssertionError(f"no staged page for {key}")
        return Completion(text=self.pages[key], tokens_in=10, tokens_out=5, latency_ms=1,
                          resolved_build=model_ref.build_id, cached_prefix_tokens=0, cost=None)


# ---- what a perfect page reader would return ----------------------------------------------------

def region(kind: str, qid: str, body: str, *, conf: float = 0.95, state: str = "present",
           selection: str | None = None, selection_state: str | None = None) -> str:
    head = f"<!-- region: kind={kind} question_id={qid} conf={conf} state={state}"
    if selection_state:
        head += f" selection_state={selection_state}"
        if selection:
            head += f" selection={selection}"
    return f"{head} -->\n{body}\n<!-- /region -->"


def assessment_transcript(test_id: str) -> str:
    lines = [f"Assessment: {test_id}", ""]
    if test_id == sm.PHYSICS_ID:
        for qid, prompt, options, _key in sm.PHYSICS_MCQ:
            lines += [region("transcribed_text", qid, prompt + " " + "; ".join(
                f"{k}. {v}" for k, v in options.items())), ""]
        lines += [region("transcribed_text", sm.PHYSICS_Q4[0], sm.PHYSICS_Q4[1]), ""]
        _q, stem, a_part, _opts, _k, b_part = sm.PHYSICS_Q5
        lines += [region("transcribed_text", "Q5a", f"{stem} {a_part}"), ""]
        lines += [region("transcribed_text", "Q5b", b_part), ""]
    else:
        lines += [region("transcribed_text", "PASSAGE", " ".join(sm.ENGLISH_PASSAGE)), ""]
        for qid, prompt in sm.ENGLISH_QUESTIONS:
            lines += [region("transcribed_text", qid, prompt), ""]
    return "\n".join(lines).strip()


def sheet_transcript(sheet: dict) -> str:
    """The page as an ideal reader returns it: header lines first, then one region per question.
    A written answer's region carries the printed question and the student's words together,
    because the reader is asked to transcribe the page verbatim."""
    out = [f"Assessment: {sheet['test']}"]
    if sheet["student"]:
        out.append(f"Student: {sheet['student']}")
    out.append("")
    if sheet["test"] == sm.PHYSICS_ID or sheet["mcq"]:
        for qid, _prompt, options, _key in sm.PHYSICS_MCQ:
            out += [f"## {qid}", "", mcq_region(qid, sheet["mcq"].get(qid, [])), ""]
        out += ["## Q4", "", written_region("Q4", sm.PHYSICS_Q4[1], sheet["written"].get("Q4", "")), ""]
        out += ["## Q5a", "", mcq_region("Q5a", sheet["mcq"].get("Q5a", [])), ""]
        out += ["## Q5b", "", written_region("Q5b", sm.PHYSICS_Q5[5], sheet["written"].get("Q5b", "")), ""]
    else:
        for qid, prompt in sm.ENGLISH_QUESTIONS:
            out += [f"## {qid}", "", written_region(qid, prompt, sheet["written"].get(qid, "")), ""]
    return "\n".join(out).strip()


def mcq_region(qid: str, letters: list[str]) -> str:
    if len(letters) == 1:
        return region("selection_mark", qid, letters[0], selection=letters[0],
                      selection_state="resolved")
    return region("selection_mark", qid, " ".join(letters), selection_state="multiple_marks",
                  conf=0.9)


ANSWERS_ONLY = "--answers-only" in sys.argv


def written_region(qid: str, printed_question: str, text: str) -> str:
    if not text:
        return region("transcribed_text", qid, "" if ANSWERS_ONLY else printed_question,
                      state="blank", conf=0.9)
    if ANSWERS_ONLY:
        return region("transcribed_text", qid, text, conf=0.9)
    return region("transcribed_text", qid, f"{printed_question} {text}", conf=0.9)


# ---- the two packages, built the way `aeh package build` builds them ----------------------------

def build_package_from_spec(store, test_id: str) -> tuple[PackageCatalog, str]:
    """Build and publish `test_id`'s package from its shipped spec, through the real build code."""
    spec_path, _roster = MATERIALS[test_id]
    built = build_package(store, read_package_spec(spec_path))
    catalog = PackageCatalog(store.package(built.package_id), package_id=built.package_id,
                             blobs=store.blobs())
    return catalog, built.package_version


def declared_methods(catalog: PackageCatalog, version: str) -> dict[str, str]:
    """Each rubric line's scoring method, in the guide's words (see EXPECTED_METHODS)."""
    found = {}
    for row in map(dict, catalog.criteria(version)):
        if row["kind"] == "mcq":
            found[row["criterion_id"]] = "key"
        elif row["component_of"]:
            found[row["criterion_id"]] = f"aspect of {row['component_of']}"
        else:
            found[row["criterion_id"]] = row["score_method"]
    return found


def enumerated_lines(store, cohort: str, version: str) -> tuple[dict[str, set[str]], str]:
    """Create (never start) a dev-ci run from the live config over `cohort`, and return the rubric
    lines it enumerated work for, with their stages, and the enumeration's note on composites."""
    raw = parse_config_document(LIVE_CONFIG.read_text(encoding="utf-8"), "toml")
    orchestrator = Orchestrator(store)
    config = resolve_run_config(dict(effective_config(raw)), orchestrator.cohort_ref(cohort))
    run_id = orchestrator.create_run(cohort, version, config)
    report = orchestrator.enumerate_units(run_id)
    lines: dict[str, set[str]] = {}
    for row in store.cohort(cohort).query(
            "SELECT DISTINCT criterion_id, stage FROM work_unit WHERE run_id = :r", r=run_id):
        lines.setdefault(row["criterion_id"], set()).add(row["stage"])
    return lines, report.gates.get("composites", "")


def check_methods(store, test_id: str, catalog: PackageCatalog, version: str,
                  cohort: str) -> list[str]:
    """Print the package's rubric methods and the lines a dev-ci run would grade; return any
    difference from what the live-test guide says."""
    failures = []
    methods = declared_methods(catalog, version)
    print("  rubric methods:  " + ", ".join(f"{c}={m}" for c, m in sorted(methods.items())))
    if methods != EXPECTED_METHODS[test_id]:
        failures.append(f"{test_id}: the guide says rubric methods {EXPECTED_METHODS[test_id]}, "
                        f"the built package has {methods}")
    lines, composites = enumerated_lines(store, cohort, version)
    print("  dev-ci run work: " + ", ".join(
        f"{c}({'+'.join(sorted(stages))})" for c, stages in sorted(lines.items())))
    print(f"  composites:      {composites}")
    graded = {c for c, m in methods.items() if m != "evidence_sum"}
    if set(lines) != graded:
        failures.append(f"{test_id}: a run should enumerate work for {sorted(graded)}, it "
                        f"enumerated {sorted(lines)}")
    return failures


def main() -> int:
    files = sm.build_all()
    home_tmp = Path(tempfile.mkdtemp(prefix=".aeh-sample-check-", dir=Path.home()))
    home_tmp.chmod(0o700)
    failures: list[str] = []
    try:
        store = open_store(home_tmp)
        reader = ScriptedReader()
        blobs = store.blobs()
        print(f"working folder: {home_tmp}\n")

        # The run created by the method check reads its profile from the live config file, and
        # leaves the random extra-judge sample off, as the one-judge live walkthrough does.
        os.environ.pop("HARNESS_PROFILE", None)
        os.environ["HARNESS_ORCH_RANDOM_ARM_RATE"] = "0"
        worlds = [(sm.PHYSICS_ID, sm.PHYSICS_SHEETS), (sm.ENGLISH_ID, sm.ENGLISH_SHEETS)]
        for test_id, sheets in worlds:
            catalog, version = build_package_from_spec(store, test_id)
            cohort = f"coh-{test_id.lower()}"
            # The shipped class list. S9-006 left its name off the page, but is on the list.
            create_cohort(store, cohort, "synthetic", read_roster_file(MATERIALS[test_id][1]))
            handle = store.cohort(cohort)
            ingestor = Ingestor(handle, blobs, reader, TRANSCRIBER, SamplingParams(temperature=0.0),
                                PdfiumRasterizer(), residency=ResidencySlot.for_policy(("transcriber",)),
                                sanitizer=PypdfSanitizer(),
                                package_catalog=catalog, package_version=version)
            blob = blobs.put(files[f"{test_id}/01-test-paper.pdf"])
            reader.stage(blob, [assessment_transcript(test_id)])
            ingestor.ingest_document([blob], kind="assessment", order_hint=[blob])

            print(f"== {test_id}: {len(sheets)} answer sheets")
            for sheet in sheets:
                data = files[f"{test_id}/answer-sheets/{sheet['stem']}.pdf"]
                blob = blobs.put(data)
                reader.stage(blob, [sheet_transcript(sheet)])
                report = ingestor.ingest_submission(
                    [blob], cohort, version, order_hint=[blob],
                    filenames={blob: sheet["stem"] + ".pdf"}, package_catalog=catalog)
                gates = " ".join(f"{k}={v}" for k, v in report.gates.items())
                print(f"  {sheet['stem']:<34} status={report.ingest_status:<12} {gates}")
                print(f"      expected: {sheet['note']}")
                if "-v" in sys.argv or ANSWERS_ONLY:
                    for name, signal in report.v4_signals.items():
                        if isinstance(signal, dict):
                            print(f"      v4 {name}: {signal}")
                want = EXPECTED_STATUS[sheet["stem"]]
                if report.ingest_status != want:
                    failures.append(f"{sheet['stem']}: the guide says {want!r}, intake gave "
                                    f"{report.ingest_status!r}")
            if not ANSWERS_ONLY:
                failures += check_methods(store, test_id, catalog, version, cohort)
        failures += [f"page request: {problem}" for problem in sorted(set(reader.request_problems))]
        store.close()
    finally:
        shutil.rmtree(home_tmp, ignore_errors=True)

    print()
    if ANSWERS_ONLY:
        print("answers-only mode: outcomes above are informational (the guide's table assumes the "
              "printed question is transcribed too).")
        return 0
    if failures:
        print("MISMATCH between what the guide says and what the intake did:")
        for failure in failures:
            print("  -", failure)
        return 1
    print("OK: every sample sheet behaved at intake as the live-test guide says it will.")
    print("OK: the two packages carry every rubric method (key, bands, evidence_sum, general), "
          "and a run grades every line but the evidence-sum composite, which is its aspects' sum.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
