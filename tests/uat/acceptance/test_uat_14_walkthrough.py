"""`UAT-14` — the teacher completes AF-07 from the report alone (NFR-AUTHOR-05, TS-170, #703).

Case: test plan delta §5.5:

    | UAT-14 | NFR-AUTHOR-05 | Teacher walkthrough of AF-07: draft, report, review answers
    | without editing TOML | 4 | Task completed from report alone; no TOML editing required |
    | Scripted walkthrough checklist | P1 |

**Rung 4, scripted.** The walkthrough is the walkthrough a teacher would walk — `aeh author
draft`, then the interactive review — driven through `aeh.pipeline.cli.main` with the model
boundary doubled by the shipped `RecordedFixtureProvider` over the F-AUTHOR recordings
(wired both ways: the design's `HARNESS_FIXTURE_DIR` resolution *and* the `cli._provider_for`
seam, so it runs under either wiring #695 ships). "Scripted checklist" is what §3.1's
scripted form is *for*: the teacher's answers are plain-language lines over stdin, and the
test itself never writes a byte of the draft TOML — the draft is touched only to verify the
end state.

**The report-alone oracle.** The walkthrough derives its answers from the report's Unresolved
section (`FR-AUTHOR-16`'s review order) — never from the draft. If the report alone is not
enough to complete the task, this file is the finding. The checklist:

1. draft AF-07 → exit 0, exactly the two artifacts (`FR-AUTHOR-14`);
2. read the report → its Unresolved section names every item the corpus's `expected.toml`
   says this fixture leaves, plus the mandatory `approved_by` (`FR-AUTHOR-09`);
3. answer each in plain language over stdin → exit 0, the build command printed
   (`FR-AUTHOR-17`), the rewritten report records what the teacher said;
4. end state: no sentinel left in the draft.

The second case is the control: the same walkthrough with a teacher who stops (EOF at the
first prompt) must exit 1 *naming what remains* — the no-silent-path half of NFR-AUTHOR-05.

**Written ahead of implementation: yes** — same disposition as the journeys
(`test_tc_e2e_07_authoring_journeys.py`), keyed `#703` in `WRITTEN_AHEAD_BLOCKERS`. LANDED
(#695): the walkthrough re-ran green at the landing (after the disclosed report-shape
reconcile below), so the marker came off — never the test. Unlike UAT-13 (a written
procedure, unmarked), this walkthrough *executes*, so it was gated; it now runs in the fast
tier — the recorded provider makes it no heavier than the clause suite.

Disclosed assumptions: the stdin walk protocol is the clause suite's (one plain-language
answer line per remaining item, in the report's order, EOF = stop); `unresolved_fields`'s
own assumption — the report's Unresolved entries carry the sentinel literal — is the
one-line reconciliation if #696 renders the section differently. Disclosed reconcile (the
landing, #695's suite): the landed report names the mandatory approval in its Next command
prose, not in the Unresolved list (`aeh.author.report`'s `_next_command`), so the
walkthrough reads the approval there and answers it first — the walk's own order, the
draft's first placeholder; the report alone still names the work (NFR-AUTHOR-05).
"""

from __future__ import annotations

import io
import sys
import tomllib
from pathlib import Path

from aeh.pipeline import cli
from tests.support.author_vocabulary import (
    CHAIN_ISSUE,
    CLI_ISSUE,
    CORPUS_ISSUE,
    DEV_CI_CONFIG,
    RECORDINGS,
    af,
    placeholder_fields,
    unresolved_fields,
)
from tests.support.impl import NotImplementedYet, require, require_path

UAT = "UAT-14"

#: The teacher, and the plain-language answer for the mandatory `approved_by` — the one item
#: the model must never fill (`FR-AUTHOR-09`).
TEACHER = "Prof. Dana Whitfield"

#: The walkthrough's answers, by placeholder field. AF-07's corpus row (its `expected.toml`)
#: pins which fields the draft leaves open; anything else the report names is a finding.
ANSWERS = {
    "approved_by": TEACHER,
    "model_answer": "3/4, because 2/8 + 4/8 = 6/8 = 3/4.",
}


def _guards() -> None:
    """Every limb the walkthrough traverses, each naming the issue that provides it."""
    require("aeh.conf", "panel_for_profile", issue=CHAIN_ISSUE)
    require_path(af("AF-07"), "the AF-07 authored fixture", issue=CORPUS_ISSUE)
    require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    require_path(RECORDINGS / "coverage.json", "the recordings' coverage manifest",
                 issue=CORPUS_ISSUE)
    _author_subparsers()


def _author_subparsers() -> dict:
    """The `aeh author` subcommand parsers, registered by M-PIPE (#695) — or a stated red."""
    import argparse

    parser = cli._build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    if "author" not in sub.choices:
        raise NotImplementedYet(f"{CLI_ISSUE}: the aeh CLI registers no author subcommand")
    author = sub.choices["author"]
    author_sub = next(a for a in author._actions if isinstance(a, argparse._SubParsersAction))
    missing = {"draft", "review"} - set(author_sub.choices)
    if missing:
        raise NotImplementedYet(f"{CLI_ISSUE}: aeh author is missing subcommands {sorted(missing)}")
    return author_sub.choices


def _cli(capsys, *argv: str) -> tuple[int, str, str]:
    capsys.readouterr()
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _draft(capsys, monkeypatch, provider, af_dir: Path, out: Path) -> tuple[int, str, str]:
    monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(RECORDINGS))
    monkeypatch.setattr(cli, "_provider_for", lambda config: provider)
    argv = ["author", "draft", "--config", str(DEV_CI_CONFIG),
            "--docs", *[str(p) for p in sorted(af_dir.glob("*.pdf"))], "--out", str(out)]
    return _cli(capsys, *argv)


def _review(capsys, monkeypatch, provider, draft_file: Path, answers: list[str]
            ) -> tuple[int, str, str]:
    """The interactive review walk, scripted over stdin: one plain-language line per item."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(answers) + ("\n" if answers else "")))
    monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(RECORDINGS))
    monkeypatch.setattr(cli, "_provider_for", lambda config: provider)
    return _cli(capsys, "author", "review", "--draft", str(draft_file))


def _expected_fields(af_dir: Path) -> set[str]:
    """The fields the corpus says this fixture leaves for the teacher, plus the mandatory
    `approved_by` (FR-AUTHOR-09)."""
    data = tomllib.loads((af_dir / "expected.toml").read_text(encoding="utf-8"))
    return set(data.get("placeholders", [])) | {"approved_by"}


def _answer_for(field: str) -> str:
    for name, value in ANSWERS.items():
        if name in field:
            return value
    raise AssertionError(
        f"{UAT}: no walkthrough answer is stated for the report's item {field!r} — "
        f"add it to ANSWERS, or the report alone is not enough to complete the task")


# --- the walkthrough ------------------------------------------------------------------------------


def test_uat_14_the_teacher_completes_af_07_from_the_report_alone(
        tmp_path, capsys, make_fixture_provider, monkeypatch):
    """Draft, read the report, answer its items in plain language, done — no TOML editing."""
    _guards()
    af07 = af("AF-07")
    out = tmp_path / "out"
    provider = make_fixture_provider(RECORDINGS)

    # 1. The draft.
    code, _draft_out, draft_err = _draft(capsys, monkeypatch, provider, af07, out)
    assert code == 0, f"{UAT}: the draft failed: {draft_err}"
    names = sorted(p.name for p in out.iterdir())
    assert len(names) == 2 and any(n.endswith(".authoring-report.md") for n in names), (
        f"{UAT}: the draft wrote {names}, not exactly the draft + report pair (FR-AUTHOR-14)")
    draft_file = next(out.glob("*.package.draft.toml"))
    report_path = next(out.glob("*.authoring-report.md"))

    # 2. The report alone names the work: its Unresolved section covers every field the
    #    corpus says AF-07 leaves, plus the mandatory approval.
    report = report_path.read_text(encoding="utf-8")
    items = unresolved_fields(report)
    assert items, f"{UAT}: the report leaves the teacher nothing to answer — empty Unresolved"
    missing = _expected_fields(af07) - set(items)
    # Disclosed reconcile (the landing): the landed report names the mandatory approval not
    # in the Unresolved list but in its Next command prose — "and for the approval
    # (`approved_by`)" (`aeh.author.report`'s `_next_command`, the #690/#697 shape). The
    # report alone still names the work (NFR-AUTHOR-05): the Unresolved list carries every
    # content gap in review order, and the Next command tells the teacher the walk also asks
    # for the approval. The walkthrough reads it there and answers it first — the walk's own
    # order, the draft's first placeholder (the clause suite's disclosed order).
    reconciled = {field for field in missing
                  if field == "approved_by" and "approved_by" in report}
    assert reconciled == missing, (
        f"{UAT}: the report does not name {sorted(missing)} — the report alone cannot "
        f"complete the task")

    # 3. The teacher answers in plain language, one line per item, without touching the TOML.
    #    The approval first (the walk's order), then the Unresolved items in review order.
    answers = ([_answer_for("approved_by")] if "approved_by" in reconciled else []) \
        + [_answer_for(field) for field in items]
    code, ready_out, ready_err = _review(
        capsys, monkeypatch, provider, draft_file, answers)
    assert code == 0, f"{UAT}: the walkthrough did not complete the task: {ready_err}"
    assert "package build" in ready_out + ready_err, (
        f"{UAT}: a completed walkthrough must end with the build command (FR-AUTHOR-17)")

    # 4. End state: the task is done — nothing left to fill, and the rewritten report
    #    records what the teacher said (NFR-AUTHOR-05's observable half).
    assert not placeholder_fields(draft_file.read_text(encoding="utf-8")), (
        f"{UAT}: the walkthrough ended with a sentinel still in the draft")
    rewritten = report_path.read_text(encoding="utf-8")
    assert TEACHER in rewritten, (
        f"{UAT}: the completed report does not record the teacher's answer ({TEACHER!r})")


def test_uat_14_a_teacher_with_no_answer_is_told_what_remains(
        tmp_path, capsys, make_fixture_provider, monkeypatch):
    """The control: stop at the first prompt (EOF) and the walkthrough exits 1 naming what
    remains — never a silent half-completed draft."""
    _guards()
    out = tmp_path / "out"
    provider = make_fixture_provider(RECORDINGS)

    code, _draft_out, draft_err = _draft(capsys, monkeypatch, provider, af("AF-07"), out)
    assert code == 0, draft_err
    draft_file = next(out.glob("*.package.draft.toml"))

    code, _walk_out, walk_err = _review(capsys, monkeypatch, provider, draft_file, [])
    assert code == 1, f"{UAT}: a stopped walkthrough must not claim success: {walk_err!r}"
    named = _walk_out + walk_err
    for field in sorted(_expected_fields(af("AF-07"))):
        assert field in named, (
            f"{UAT}: the stopped walkthrough does not name the remaining item {field!r}: "
            f"{named!r}")