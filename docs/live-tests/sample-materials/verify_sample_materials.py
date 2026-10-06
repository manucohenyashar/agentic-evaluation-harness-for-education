#!/usr/bin/env python3
"""Check the sample PDFs against the system's real intake gates, with no network and no model.

What this proves, and what it does not
--------------------------------------
It builds the two sample packages through the real package writer, puts the sample students on a
roster, and sends every sample PDF through the real intake (`aeh.ingest.Ingestor`): the file
integrity gate (V0), page-count gate (V1), structure gate (V2), identity gate (V3) and
right-test gate (V4), then prints what each sheet did.

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
from aeh.conf import ModelRef  # noqa: E402
from aeh.ingest import Ingestor, PdfiumRasterizer, PypdfSanitizer, ResidencySlot  # noqa: E402
from aeh.pkg import PackageCatalog  # noqa: E402
from aeh.prov import Completion, SamplingParams  # noqa: E402
from aeh.store import open_store  # noqa: E402

STAMP = "2026-01-01T00:00:00+00:00"
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
    """Stands in for the page-reading model: answers a page request with the text staged for it."""

    def __init__(self) -> None:
        self.pages: dict[tuple[str, int], str] = {}

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


# ---- the two packages ---------------------------------------------------------------------------

def build_package(store, test_id: str, rubric: list, mcq_options: dict, answer_keys: dict,
                  boundaries: list) -> tuple[PackageCatalog, str]:
    handle = store.package(test_id)
    with handle.transaction() as tx:
        tx.execute("INSERT INTO package (package_id, created_at) VALUES (:p, :c)", p=test_id, c=STAMP)
    catalog = PackageCatalog(handle, package_id=test_id, blobs=store.blobs())
    version = catalog.create_version(None)
    for cid, qid, _name, detail in rubric:
        if cid in mcq_options:
            catalog.add_criterion(version, cid, question_id=qid, kind="mcq", max_points=1.0,
                                  scoring_model="atomic", band_count=2)
            catalog.add_band(version, cid, 0, "incorrect", 0.0)
            catalog.add_band(version, cid, 1, "correct", 1.0)
            catalog.set_mcq_options(version, cid, [(k, f"Option {k}") for k in mcq_options[cid]])
            catalog.set_answer_key(version, cid, [answer_keys[cid]])
        elif isinstance(detail, str):  # a yes/no written line
            catalog.add_criterion(version, cid, question_id=qid, kind="open", max_points=1.0,
                                  scoring_model="atomic", band_count=2)
            catalog.add_band(version, cid, 0, "not met", 0.0, "The answer does not do this.")
            catalog.add_band(version, cid, 1, "met", 1.0, detail)
        else:  # a four-band written line
            catalog.add_criterion(version, cid, question_id=qid, kind="open", max_points=3.0,
                                  scoring_model="holistic", band_count=4)
            for ordinal, (label, text) in enumerate(reversed(detail)):
                name = label.split(" (")[0].lower()
                catalog.add_band(version, cid, ordinal, name, float(ordinal), text)
    catalog.set_boundaries(version, boundaries)
    catalog.publish(version, approved_by="Sample-materials check")
    return catalog, version


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

        worlds = [
            (sm.PHYSICS_ID, sm.PHYSICS_RUBRIC,
             {"C1": "ABCD", "C2": "ABCD", "C3": "ABCD", "C5": "ABC"},
             {"C1": "C", "C2": "B", "C3": "C", "C5": "B"},
             [("A", 8.0), ("B", 6.0), ("C", 4.0), ("D", 2.0), ("F", 0.0)], sm.PHYSICS_SHEETS),
            (sm.ENGLISH_ID, sm.ENGLISH_RUBRIC, {}, {},
             [("pass", 6.0), ("not yet", 0.0)], sm.ENGLISH_SHEETS),
        ]
        for test_id, rubric, opts, keys, bounds, sheets in worlds:
            catalog, version = build_package(store, test_id, rubric, opts, keys, bounds)
            cohort = f"coh-{test_id.lower()}"
            handle = store.cohort(cohort)
            with handle.transaction() as tx:
                tx.execute("INSERT INTO cohort (cohort_id, consent_class, created_at) "
                           "VALUES (:c, 'synthetic', :t)", c=cohort, t=STAMP)
                for sheet in sheets:
                    # S9-006 left its name off the page, but it is still a student on the roster.
                    ref = sheet["student"] or "S9-006"
                    tx.execute("INSERT INTO roster (cohort_id, student_ref) VALUES (:c, :s)",
                               c=cohort, s=ref)
            ingestor = Ingestor(handle, blobs, reader, TRANSCRIBER, SamplingParams(temperature=0.0),
                                PdfiumRasterizer(), residency=ResidencySlot.for_policy(("transcriber",)),
                                sanitizer=PypdfSanitizer())
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
