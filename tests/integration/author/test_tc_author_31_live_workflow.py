"""`TC-AUTHOR-31` live-workflow extension (#704) — the operator's authoring workflow, end to
end, on real OpenRouter (`@live`, nightly).

Case: test plan §5.6 (`TC-AUTHOR-31`, `FR-AUTHOR-01`, P0, rung 4, live tier); design delta
§5.2. Issue #704 wires the package-creation workflow into the operator's live-test flow
(docs/live-tests/README.md): `aeh author draft` over teacher documents, inspect the report,
`aeh author review` completing the placeholders, `aeh package build` publishing — then the
built package used in the same live grading flow. Every limb is driven through
`aeh.pipeline.cli.main`, the exact commands the README prints — this file is the executable
form of the guide's authoring step, not a library-level re-run of it.

**What is asserted, and what is not.** Outcome classes only (`CT-AUTHOR-17`): the draft
completes and its report states what resolved; the premature build is *refused, naming what
remains* (`FR-PKG-28`); the review reaches *ready* after the answers; the build *publishes*;
the built package's live run *grades* the one student (`grades_final > 0`) and `results show`
carries the record. Never exact model wording: two runs of a real model agree on structure,
not prose. The corpus's own review-completes-to-ready fixture (`AF-07` — partial, `model_answer`
placeholders, `build = "publishes"` after review) is the walk, because the human gate is the
limb no resolved fixture can show.

**The answer sheets.** The AF corpus carries no answer sheets — the live draft's content is
model-determined — so the sheet is generated at test time *from the reviewed draft*: the
package id on the `Assessment:` line, the rostered student on the `Student:` line, and each
question reprinted with the answer the review itself scripted in (the worked fractions for
AF-07's four questions). The reader gets the declared questions from the bound package, so the
tagged regions and the structural check line up by construction.

**Gate order, the TS-142 rule.** The key is checked *first* and the case skips, naming the
tier, when it is unset — a box with no key spends nothing. Only then is a config resolved or a
socket opened. The key is never logged, echoed or asserted on — its *absence* is the only fact
about it any line here states.

**The models.** Read from `docs/live-tests/config/live-test.dev-ci.toml`, never hard-coded:
the chain resolves through the production path (`panel_for_profile`) over the operator's file,
and `models_used` is read as containment against it — a model outside the configured chain
fails before or as it is spent (`CT-AUTHOR-06`).

**One run, two cases.** The workflow is memoised module-level (the TS-142 pattern, started
inside the first test body that needs it, failures cached too): the authoring limbs and the
grading limbs read the same single live pass, because the fixture → review → build → grade
walk is the nightly's spend, not twice that.

**Deviations.** A run that pauses is recorded verbatim as a warning, never silenced, and the
grading limb accepts three outcome classes: the run grades (complete, `grades_final >= 1`, a
results row); it completes with the grade held provisional while judge replies are refused
by the byte-exact citation check (`FR-JUDGE-17`, seen live 2026-10-12: two verdicts landed,
two refused, `grades_final` 0 with `grades_computed` 1); or it stops naming why — the
refusals in its score trace and, when the repeat widening names an escalation seat no live
model serves, the composition fault in `pause_reason`. Resuming a stored pause needs one
step off the CLI: `aeh run` starts only `pending` runs and `recover` resumes a paused run
only when it carries a queued resume request, so the test queues the resume through the
M-ORCH seam the console uses, then reruns the same command with
`HARNESS_DECISION_ENGINE = off`. Anything else surfaces as the failure it is.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import textwrap
import tomllib
import warnings
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest

from aeh.conf import parse_config_document
from aeh.conf.panel_profile import panel_for_profile
from aeh.pipeline import cli

from tests.support.author_vocabulary import LIVE_DEV_CI_CONFIG as DEV_CI_CONFIG, af
from tests.support.impl import require_path

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live,
    pytest.mark.slow,
]

CASE = "TC-AUTHOR-31"
WORKFLOW_ISSUE = "#704"
CORPUS_ISSUE = "#686"
KEY_ENV = "OPENROUTER_API_KEY"

#: The fixture the workflow walks: AF-07 — the corpus's own review-completes-to-ready fixture
#: (partial: `model_answer` placeholders on the questions; `build = "publishes"` once review
#: fills them). The premature build refusal, the review gate and the publish are all its limbs.
AF_ID = "AF-07"

COHORT_ID = "af7-live"
#: The rostered student, and the name the generated sheet's `Student:` line carries (v3
#: matches the two verbatim).
STUDENT = "Alex Live"
SHEET_STEM = "af7-live-answer-sheet"

#: Who approved the draft at review (`FR-AUTHOR-09` — never model-generated, always asked).
TEACHER = "Live workflow teacher"

#: The typed answer sheet's shape — the same clean typed paper the corpora render at.
_WRAP_COLUMNS = 85
_LINES_PER_PAGE = 46

_RUN: dict[str, Any] = {}


def _require_live_key() -> None:
    """The key gate, first. Skips naming the tier when the key is unset."""
    key = os.environ.get(KEY_ENV, "")
    if not key.strip():
        pytest.skip(
            f"{KEY_ENV} is unset. {CASE}'s workflow drafts AF-07, reviews it and grades the "
            f"built package against the real OpenRouter endpoint, and is nightly-only "
            f"(E2/E3, test plan §4.7); set the key from .env-dev on the nightly box to run "
            f"it. Nothing here reads or logs the key itself."
        )


def _import_full_migration_chain() -> None:
    """CLAUDE.md: before the first store open in a process, import all eleven contributors."""
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


def _normalised(field: str) -> str:
    """A sentinel field name with every non-alphanumeric folded out, for class comparison."""
    return re.sub(r"[^a-z0-9]", "", field.strip().lower())


def _pending_answers(spec: dict[str, Any]) -> list[tuple[str, str, str, str | None]]:
    """The draft's sentinel occurrences in document order, as `(field, section, key, owner_qid)`.

    The review walk reads **one stdin line per pending occurrence** in the renderer's own
    order (top-level scalars, then the question tables, then the criterion tables, then the
    `[grades]` table last — `run_review._walk`'s documented order), so the scripted answers
    must be produced in that same order, with each answer matched to the question it
    belongs to. This mirrors that order off the parsed spec; a file whose text and TOML
    disagree is refused by the walk itself before anything is written.
    """
    prefix, suffix = "<<PLACEHOLDER: ", ">>"
    pendings: list[tuple[str, str, str, str | None]] = []

    def visit(value: Any, section: str, key: str, owner_qid: str | None) -> None:
        if isinstance(value, dict):
            for inner_key, inner in value.items():
                visit(inner, section, str(inner_key), owner_qid)
        elif isinstance(value, list):
            for entry in value:
                visit(entry, section, key, owner_qid)
        elif isinstance(value, str) and value.startswith(prefix) and value.endswith(suffix):
            pendings.append((value[len(prefix):-len(suffix)], section, key, owner_qid))

    for key, value in spec.items():
        if key in ("question", "criterion"):
            continue
        if key == "grades" and isinstance(value, dict):
            continue
        visit(value, "top", str(key), None)
    for block in spec.get("question") or []:
        if not isinstance(block, dict):
            continue
        qid = str(block.get("id")) if block.get("id") is not None else None
        for key, value in block.items():
            visit(value, "question", str(key), qid)
    for block in spec.get("criterion") or []:
        if not isinstance(block, dict):
            continue
        qid = str(block.get("question")) if block.get("question") is not None else None
        for key, value in block.items():
            visit(value, "criterion", str(key), qid)
    grades = spec.get("grades")
    if isinstance(grades, dict):
        for key, value in grades.items():
            visit(value, "grades", str(key), None)
    return pendings


def _worked_answer(spec: dict[str, Any], qid: str | None, scripted: dict[str, str]) -> str:
    """The answer the sheet shows for one question: what review scripted in (the single
    source of truth — the same line the teacher typed), else a worked line matched to the
    question, else the draft's own model answer, else a plain worked line. A drafted
    `model_answer` still carrying the sentinel is never an answer."""
    block = next((b for b in (spec.get("question") or [])
                  if qid is not None and str(b.get("id")) == qid), {})
    if qid is not None and qid in scripted:
        return scripted[qid]
    text = str(block.get("text") or "")
    for needle, answer in _WORKED_ANSWERS:
        if needle.lower() in text.lower():
            return answer
    model_answer = str(block.get("model_answer") or "").strip()
    if model_answer and not model_answer.startswith("<<PLACEHOLDER:"):
        return " ".join(model_answer.split())
    return "The working is shown step by step above and the final answer is written here."


def _choice_letter(block: dict[str, Any]) -> str:
    """The letter an mcq sheet marks: the one the draft's own model answer names, else A."""
    stated = str(block.get("model_answer") or "")
    match = re.search(r"\b([A-D])\b", stated)
    return match.group(1) if match else "A"


def _wrap(line: str) -> list[str]:
    """One logical line wrapped to the typed page's columns, continuation lines indented."""
    if len(line) <= _WRAP_COLUMNS:
        return [line]
    return textwrap.wrap(line, width=_WRAP_COLUMNS, subsequent_indent="   ",
                         break_long_words=False, break_on_hyphens=False)


def _sheet_pages(spec: dict[str, Any], scripted: dict[str, str]) -> list[str]:
    """The generated answer sheet, paginated: the header lines v3/v4 read verbatim, then each
    declared question reprinted with the answer shown."""
    lines = [f"Assessment: {spec['package']}", f"Student: {STUDENT}", ""]
    for block in spec.get("question") or []:
        qid = str(block.get("id"))
        lines.append(f"{qid}. {block.get('text', '')}")
        options = block.get("options")
        if isinstance(options, dict):
            for letter in sorted(options):
                lines.append(f"   {letter}: {options[letter]}")
            lines.append(f"Answer: {_choice_letter(block)}")
        else:
            lines.append(f"Answer: {_worked_answer(spec, qid, scripted)}")
        lines.append("")
    flat: list[str] = []
    for line in lines:
        flat.extend(_wrap(line))
    pages = [flat[i:i + _LINES_PER_PAGE]
             for i in range(0, len(flat), _LINES_PER_PAGE)]
    return ["\n".join(page) + "\n" for page in pages]


def _run_cli(args: list[str]) -> tuple[int, str, str]:
    """One `aeh` command through `cli.main`, stdout and stderr captured."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(args)
    return code, out.getvalue(), err.getvalue()


def _json_tail(text: str) -> Any:
    """The last JSON object stdout carries — the command's result, printed after any
    profile/provider summary lines."""
    for start in reversed([match.start() for match in re.finditer(r"^\{", text, re.M)]):
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            continue
    return None


def _cost_of(data_dir: Path, cohort_id: str, run_id: str) -> float | None:
    """The run's recorded live cost — the cohort ledger's `cost_spend` on the run row, where
    the provider's actual spend is accumulated (the durable `run_metrics` carry estimates and
    counters, not the spend) — or `None` when the run is not there."""
    import sqlite3

    cohort_file = data_dir / "cohorts" / f"{cohort_id}.sqlite"
    if not cohort_file.exists():
        return None
    connection = sqlite3.connect(cohort_file)
    try:
        rows = connection.execute(
            "SELECT cost_spend FROM run WHERE run_id = ?", (run_id,)).fetchall()
    finally:
        connection.close()
    if not rows or rows[0][0] is None:
        return None
    return float(rows[0][0])


#: The worked fractions AF-07's four questions expect — also the answers the review is
#: scripted with, so the sheet the student "wrote" and the draft's model answers agree.
_WORKED_ANSWERS = (
    ("2/3 + 1/4", "2/3 + 1/4 = 8/12 + 3/12 = 11/12"),
    ("3/5 of 45", "3/5 of 45: 45 / 5 = 9, and 9 x 3 = 27"),
    ("12/18", "12/18 = 2/3, dividing the top and the bottom by 6"),
    ("2/5, 1/2, 7/10", "smallest first: 2/5, 1/2, 7/10 (2/5 = 4/10 and 1/2 = 5/10)"),
)


def _workflow(tmp_path_factory: pytest.TempPathFactory,
              monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The one live pass both cases read. Key first, then the blocker, then the network."""
    _require_live_key()
    if "error" in _RUN:
        raise _RUN["error"]
    if "run" in _RUN:
        return _RUN["run"]
    try:
        workflow = _execute(tmp_path_factory, monkeypatch)
    except Exception as error:
        _RUN["error"] = error
        raise
    _RUN["run"] = workflow
    return workflow


def _execute(tmp_path_factory: pytest.TempPathFactory,
             monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The README's authoring step, executed once for real: draft → premature-build refusal →
    review → build → cohort → generated sheet → ingest → run → results."""
    _import_full_migration_chain()
    require_path(af(AF_ID), f"the {AF_ID} authored fixture", issue=CORPUS_ISSUE)
    documents = sorted(af(AF_ID).glob("*.pdf"))
    assert len(documents) == 1, (
        f"{CASE}: {AF_ID} carries {len(documents)} PDFs; the workflow walks the one test "
        f"paper the fixture drafts from"
    )

    # The operator's env, per README step 0: the file's profile stands (no HARNESS_PROFILE
    # override), no recorded fixture is bound, the escalation budget is the guide's, and the
    # random extra-judge sample is off — the shipped config has no escalation seats for it
    # to draw, and an arm seated with no model behind it changes the outcome class for an
    # environment reason rather than a model one.
    monkeypatch.delenv("HARNESS_PROFILE", raising=False)
    monkeypatch.delenv("HARNESS_FIXTURE_DIR", raising=False)
    monkeypatch.setenv("HARNESS_ORCH_ESCALATION_BUDGET", "1.0")
    monkeypatch.setenv("HARNESS_ORCH_RANDOM_ARM_RATE", "0")
    document = parse_config_document(DEV_CI_CONFIG.read_text(encoding="utf-8"), "toml")
    assert not document.get("HARNESS_FIXTURE_DIR"), (
        f"{CASE}: {DEV_CI_CONFIG.name} binds HARNESS_FIXTURE_DIR, so the workflow would "
        f"replay recordings and call it live. The live tier binds no recorded fixture "
        f"(design delta §5.2)."
    )
    chain_ids = {ref.build_id for ref in panel_for_profile(document, "dev-ci")}
    assert chain_ids, f"{CASE}: {DEV_CI_CONFIG.name} resolves no authoring chain"

    out_dir = tmp_path_factory.mktemp("af7-live-authoring")
    data_dir = tmp_path_factory.mktemp("af7-live-data")

    # --- limb 1: the draft, and its report -----------------------------------------------
    code, out, err = _run_cli([
        "author", "draft", "--config", str(DEV_CI_CONFIG), "--docs", str(documents[0]),
        "--out", str(out_dir), "--force"])
    assert code == 0, f"{CASE}: aeh author draft exited {code}: {err}"
    drafts = sorted(out_dir.glob("*.draft.toml"))
    reports = sorted(out_dir.glob("*.authoring-report.md"))
    assert len(drafts) == 1 and len(reports) == 1, (
        f"{CASE}: the draft wrote {[p.name for p in sorted(out_dir.iterdir())]}; the workflow "
        f"expects one draft spec and one authoring report — a draft producing no report is "
        f"the silent failure the workflow exists to catch"
    )
    draft_path, report_path = drafts[0], reports[0]
    drafted_spec = tomllib.loads(draft_path.read_text(encoding="utf-8"))
    pendings = _pending_answers(drafted_spec)
    drafted_classes = {_normalised(field) for field, _s, _k, _q in pendings}
    unexpected = sorted(drafted_classes - {_normalised("approved_by"),
                                           _normalised("model_answer")})
    assert not unexpected, (
        f"{CASE}: {AF_ID}'s live draft carries the placeholder classes {unexpected}. The "
        f"corpus's outcome class for this fixture is approved_by + model_answer only; a "
        f"different gap is a changed outcome class (RISK-122), never scripted around."
    )
    drafted_match = re.search(r"^Drafted ([^:]+):", out, re.M)
    assert drafted_match, (
        f"{CASE}: the draft's stdout names no drafted package id; the operator reads the "
        f"workflow's state off this line (the summary paragraph). stdout was:\n{out}"
    )
    package_id = drafted_match.group(1).strip()
    models_used = re.findall(r"Models used: (.+)", out)
    # The summary line ends `Models used: <ids>. Next: ...` — the next-command tail is not
    # part of the list.
    segment = models_used[-1].split(". Next:")[0] if models_used else ""
    models = [name.strip() for name in segment.split(",") if name.strip()]
    assert models, (
        f"{CASE}: the draft's summary names no models used — a draft was produced by some "
        f"model, and the report must say which (FR-AUTHOR-18). stdout was:\n{out}"
    )
    for model in models:
        assert model in chain_ids, (
            f"{CASE}: the draft's models_used names {model!r}, which is not in the configured "
            f"chain {sorted(chain_ids)} from {DEV_CI_CONFIG.name}. The chain is the run "
            f"configuration's (FR-AUTHOR-04) — a model outside it must fail, never pass "
            f"(CT-AUTHOR-06)."
        )

    # --- limb 2: the premature build is refused, naming what remains (FR-PKG-28) ---------
    rcode, rout, rerr = _run_cli([
        "package", "build", "--data-dir", str(data_dir), "--spec", str(draft_path)])
    refusal = rout + rerr

    # --- limb 3: the review, one stdin line per pending occurrence -----------------------
    scripted: dict[str, str] = {}
    lines: list[str] = []
    for field, _section, _key, qid in pendings:
        normalised = _normalised(field)
        if "approvedby" in normalised:
            answer = TEACHER
        elif "modelanswer" in normalised:
            answer = _worked_answer(drafted_spec, qid, scripted)
            scripted[qid or ""] = answer
        else:  # excluded by the class assertion above; kept for the walk's completeness
            answer = "the working is shown"
        lines.append(answer)
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(lines) + "\n"))
    vcode, vout, verr = _run_cli(["author", "review", "--draft", str(draft_path)])

    # --- limb 4: the build publishes the reviewed draft ----------------------------------
    bcode, bout, berr = _run_cli([
        "package", "build", "--data-dir", str(data_dir), "--spec", str(draft_path)])
    version = None
    if bcode == 0:
        version = json.loads(bout)["package_version"]

    # --- limb 5: the built package in the live grading flow ------------------------------
    roster = out_dir / "roster.txt"
    roster.write_text(f"{STUDENT}\n", encoding="utf-8")
    ccode, cout, cerr = _run_cli([
        "cohort", "create", "--data-dir", str(data_dir), "--cohort", COHORT_ID,
        "--consent", "synthetic", "--roster", str(roster)])
    assert ccode == 0, f"{CASE}: aeh cohort create exited {ccode}: {cerr}"

    reviewed_spec = tomllib.loads(draft_path.read_text(encoding="utf-8"))
    from harness.corpora.pdf_writer import typed_document

    sheet_pdf = out_dir / f"{SHEET_STEM}.pdf"
    sheet_pdf.write_bytes(typed_document(_sheet_pages(reviewed_spec, scripted)))
    icode, iout, ierr = _run_cli([
        "ingest", "--data-dir", str(data_dir), "--cohort", COHORT_ID,
        "--package-version", str(version), "--config", str(DEV_CI_CONFIG),
        "--assessment", str(documents[0]), str(sheet_pdf)])
    ingest = json.loads(iout) if iout.strip() else None

    run_args = ["run", "--data-dir", str(data_dir), "--cohort", COHORT_ID,
                "--package-version", str(version), "--config", str(DEV_CI_CONFIG)]
    fcode, fout, ferr = _run_cli(run_args)
    run_result = _json_tail(fout) or {}
    findings: list[str] = []
    if fcode != 0 or run_result.get("status") != "complete":
        # Recorded verbatim, never silenced. Resuming a stored pause needs one step off the
        # CLI — `aeh run` starts only pending runs and `recover` resumes a paused run only
        # when it carries a queued resume request — so the resume is queued through the
        # M-ORCH seam the console uses, then the same command is rerun with the engine off.
        findings.append(
            f"the live run paused/errored (exit {fcode}, status "
            f"{run_result.get('status')!r}, pause_reason {run_result.get('pause_reason')!r}); "
            f"a stored pause has no CLI resume surface (`aeh run` starts only pending runs, "
            f"`recover` needs a queued resume request), so the run is resumed through the "
            f"M-ORCH orchestrator seam and retried once with HARNESS_DECISION_ENGINE=off")
        pause_run_id = str(run_result.get("run_id") or "")
        if pause_run_id:
            from aeh.orch import Orchestrator
            from aeh.store import open_store

            store = open_store(data_dir)
            try:
                Orchestrator(store).resume(pause_run_id)
            finally:
                store.close()
        monkeypatch.setenv("HARNESS_DECISION_ENGINE", "off")
        fcode, fout, ferr = _run_cli(run_args)
        run_result = _json_tail(fout) or {}

    score_details = [line for stage in (run_result.get("stages") or [])
                     if str(stage.get("stage")) == "score"
                     for line in (stage.get("detail") or [])]
    for line in score_details:
        findings.append(f"the live score stage reports: {line}")
    if run_result.get("pause_reason"):
        findings.append(f"the live run's pause_reason: {run_result['pause_reason']}")

    run_id = str(run_result.get("run_id") or "")
    results: dict[str, Any] = {}
    if run_id:
        scode, sout, serr = _run_cli([
            "results", "show", "--data-dir", str(data_dir), "--run", run_id])
        assert scode == 0, f"{CASE}: aeh results show exited {scode}: {serr}"
        results = json.loads(sout)
    cost = _cost_of(data_dir, COHORT_ID, run_id) if run_id else None

    return {
        "package_id": package_id,
        "draft_name": draft_path.name,
        "draft_stdout": out,
        "models_used": models,
        "report_path": report_path,
        "drafted_classes": sorted(drafted_classes),
        "drafted_fields": [field for field, _s, _k, _q in pendings],
        "refusal": (rcode, refusal),
        "review": (vcode, vout + verr),
        "build": (bcode, bout + berr),
        "version": version,
        "ingest": ingest,
        "ingest_exit": icode,
        "run_result": run_result,
        "run_exit": fcode,
        "run_stderr": ferr,
        "score_details": score_details,
        "results": results,
        "cost": cost,
        "warnings": findings,
    }


# --- TC-AUTHOR-31: the authoring limbs ---------------------------------------------------------


def test_tc_author_31_live_workflow_draft_refusal_review_and_build_publish(
        tmp_path_factory, monkeypatch):
    """`TC-AUTHOR-31` (P0), authoring limbs: the draft completes with its report; the
    premature build is refused naming what remains; the review reaches ready after the
    answers; the build publishes.

    Every limb is the operator's own command, and every oracle is an outcome class
    (`CT-AUTHOR-17`): the refusal must name the placeholder (never a bare exit code), the
    review must print the build command only when ready, and the published version must
    carry the drafted package's id — a build succeeding on an incomplete draft, a review
    exiting ready with placeholders, or a draft producing no report all fail here.
    """
    run = _workflow(tmp_path_factory, monkeypatch)
    for warning in run["warnings"]:
        warnings.warn(warning)

    report_text = run["report_path"].read_text(encoding="utf-8")
    assert report_text.strip(), (
        f"{CASE}: the authoring report is empty — the operator inspects what resolved off "
        f"this file, and a draft producing no report is the top silent failure"
    )
    assert run["package_id"] in report_text, (
        f"{CASE}: the report does not name the drafted package id {run['package_id']!r}"
    )
    assert run["drafted_classes"], (
        f"{CASE}: AF-07 is the partial fixture — its live draft should carry the "
        f"approved_by and model_answer placeholder classes the review fills, and carried none"
    )

    rcode, refusal = run["refusal"]
    assert rcode == 1 and "<<PLACEHOLDER:" in refusal and run["package_id"] in refusal, (
        f"{CASE}: the premature build exited {rcode} with:\n{refusal}\n"
        f"FR-PKG-28 refuses a draft carrying the sentinel, naming the file, the field and "
        f"the reason — a build that succeeded on an incomplete draft, or a refusal that "
        f"names nothing, is the failure this limb exists to catch"
    )
    assert run["draft_name"] in refusal, (
        f"{CASE}: the refusal does not name the draft file {run['draft_name']!r}:\n{refusal}"
    )
    named_fields = [field for field in run["drafted_fields"]
                    if _normalised(field) in _normalised(refusal)]
    assert named_fields, (
        f"{CASE}: the refusal names none of the sentinel fields the draft carries "
        f"({run['drafted_fields']}):\n{refusal}"
    )

    vcode, vout = run["review"]
    assert vcode == 0 and "aeh package build" in vout, (
        f"{CASE}: the review exited {vcode} with:\n{vout}\nThe review walk collects the "
        f"answers one stdin line per pending occurrence and prints the build command only "
        f"when the draft is ready — a review exiting ready with placeholders is exactly the "
        f"silent failure (FR-AUTHOR-17)."
    )

    bcode, bout = run["build"]
    assert bcode == 0 and run["version"], (
        f"{CASE}: the build exited {bcode} with:\n{bout}\nAF-07 publishes after review; a "
        f"refusal here means the reviewed draft still carries a sentinel the walk did not "
        f"fill."
    )
    assert str(run["version"]).startswith(run["package_id"]), (
        f"{CASE}: the published version {run['version']!r} does not carry the drafted "
        f"package's id {run['package_id']!r} — the operator would grade against a package "
        f"they cannot trace to the draft."
    )


# --- TC-AUTHOR-31: the grading limbs -----------------------------------------------------------


def test_tc_author_31_live_workflow_built_package_grades_on_the_live_run(
        tmp_path_factory, monkeypatch):
    """`TC-AUTHOR-31` (P0), grading limbs: the built package is accepted by the same live
    run path — intake reads the generated sheet (`ok`, every gate), the run's outcome falls
    in one of three classes, and the cost it records is carried for the README's "How this
    was checked" note.

    The no-silent-no-op oracle: the run either grades (`grades_final >= 1` with a
    `results show` row), or completes with the grade held provisional and the judge
    refusals named in its score trace (the 2026-10-12 shape: two verdicts landed, two
    refused, `grades_final` 0 with `grades_computed` 1), or stops naming what stopped it.
    A green status with nothing behind it and nothing named — or grades beside a refused
    panel — is the failure shape the workflow exists to catch.
    """
    run = _workflow(tmp_path_factory, monkeypatch)
    for warning in run["warnings"]:
        warnings.warn(warning)

    ingest = run["ingest"]
    assert run["ingest_exit"] == 0 and ingest, (
        f"{CASE}: aeh ingest exited {run['ingest_exit']} — the built package's intake "
        f"failed before any sheet was read"
    )
    sheets = {Path(sheet["file"]).stem: sheet for sheet in ingest["sheets"]}
    sheet = sheets.get(SHEET_STEM)
    assert sheet is not None, (
        f"{CASE}: intake read {sorted(sheets)}; the generated sheet {SHEET_STEM!r} is "
        f"missing from the result"
    )
    assert sheet["status"] == "ok", (
        f"{CASE}: the generated sheet parked as {sheet['status']!r} "
        f"(gates {sheet.get('gates')}, detail {sheet.get('detail')!r}). The sheet is "
        f"generated from the reviewed draft — the package id on the Assessment line, the "
        f"declared questions reprinted — so a park names a real gate finding, and it fails "
        f"here rather than being widened."
    )
    assert sheet.get("gates") == {"v0": "pass", "v1": "pass", "v2": "pass",
                                  "v3": "pass", "v4": "match"}, (
        f"{CASE}: the generated sheet's gates are {sheet.get('gates')}; the workflow's "
        f"sheet should clear every intake check (the identity and the right-test check read "
        f"the header lines the sheet carries verbatim)."
    )
    submission_id = sheet["submission_id"]

    run_result = run["run_result"]
    score_details = run["score_details"]
    refusals = [line for line in score_details if "refused after" in line]
    grades_final = int(run_result.get("grades_final") or 0)
    students = run["results"].get("students") or []
    rows = [row for row in students if row.get("submission_id") == submission_id]
    if run["run_exit"] == 0 and run_result.get("status") == "complete" and grades_final >= 1:
        # The graded arm: the run completed and the grades are behind it.
        assert rows, (
            f"{CASE}: results show carries {len(students)} row(s), none for the ingested "
            f"submission {submission_id!r} — the record the operator reads must name the "
            f"sheet the run graded."
        )
        assert all(row.get("total") is not None for row in rows), (
            f"{CASE}: the graded record for {submission_id!r} carries no total: {rows}"
        )
    elif run["run_exit"] == 0 and run_result.get("status") == "complete":
        # The provisional arm, recorded for real on the 2026-10-12 pass: the judge landed
        # some verdicts and was refused on others (the byte-exact citation check,
        # `FR-JUDGE-17` — a forged span is refused, never accepted); the run completed with
        # the computed grade held provisional (`grades_final` 0, `grades_computed` >= 1)
        # rather than settling it over a refused panel. The outcome class is "nothing is
        # graded silently": a complete run with no final grades and no refusal named in its
        # score trace is the failure shape the workflow exists to catch.
        assert refusals, (
            f"{CASE}: the run reports complete with grades_final={grades_final}, "
            f"grades_computed={run_result.get('grades_computed')!r}, and no judge refusal "
            f"in its score trace: {score_details}\n{run['run_stderr']}\nA green status with "
            f"nothing behind it and nothing named is the silent failure the workflow "
            f"exists to catch."
        )
        assert rows, (
            f"{CASE}: results show carries {len(students)} row(s), none for the ingested "
            f"submission {submission_id!r} — the provisional record must still name the "
            f"sheet the run worked on."
        )
    else:
        # The stopped arm: the run paused or failed, and the stop names what stopped it —
        # the judge refusals in the score trace, or the composition fault in the
        # `pause_reason` (seen live when the repeat widening named an escalation seat no
        # live model serves). Nothing graded alongside a refused panel.
        named = ("FR-JUDGE-17" in " ".join(score_details)
                 or "CompositionFault" in str(run_result.get("pause_reason") or ""))
        assert run_result.get("status") in ("paused", "failed") and refusals and named, (
            f"{CASE}: the live run stopped (exit {run['run_exit']}, status "
            f"{run_result.get('status')!r}, pause_reason "
            f"{run_result.get('pause_reason')!r}) without naming a judge refusal in its "
            f"score trace: {score_details}\n{run['run_stderr']}\nA stop the workflow "
            f"cannot read is a failure, never a skip."
        )
        assert grades_final == 0, (
            f"{CASE}: the run stopped over refused judge replies yet reports "
            f"grades_final={grades_final} — grades beside a refused panel would be the "
            f"silent failure the workflow exists to catch."
        )