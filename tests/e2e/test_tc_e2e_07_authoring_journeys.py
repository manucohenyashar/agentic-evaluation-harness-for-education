"""`TC-E2E-07` — the three authoring journeys each end published or visibly gated (TS-170, #703).

Case: test plan delta §5.5, `FR-AUTHOR-01`. Oracle: **journey end states** — each journey
asserts where it ends (a published version id, or the visible gate naming file + field +
reason), and the suite fails on a silent path: a journey that ends neither published nor
visibly gated.

    | TC-E2E-07 | Three journeys: (a) AF-02 happy draft→review→ready→build publishes; (b) AF-11
    | gate — build refused→review completes→published; (c) AF-09 failure — all attempts
    | fail→review completes→ready. Each journey ends published or visibly gated; no silent path |

**Rung 4** — the ASSEMBLED system, driven the way the teacher drives it: every step goes
through `aeh.pipeline.cli.main` — `aeh author draft`, `aeh author review` (the interactive
walk, stdin-scripted), `aeh package build` — and the only double anywhere is the model
boundary, the shipped `RecordedFixtureProvider` over the F-AUTHOR recordings, wired through
the design's declared resolution (`HARNESS_FIXTURE_DIR` → the recorded provider, design
delta §3.1's Dependencies table) *and* the `cli._provider_for` seam the clause suite uses.
`tests/e2e/test_e2e_01_package_setup.py` is the tier precedent; this is the authoring
delta's three journeys, which the base plan's three do not reach.

**Why the end states are load-bearing.** FR-AUTHOR-01's promise is that nothing is silent:
the draft states exactly what is known and unknown, and the review/build surfaces say what
happened. Journey (b) is `FR-PKG-28`'s gate read end-to-end — the incomplete draft is
refused, the teacher completes it at review, the build then publishes — so the human gate is
load-bearing, not decorative. Journey (c) is NFR-AUTHOR-01's best-effort promise read
end-to-end — a total reasoning failure still ends *ready* once the teacher fills what the
model could not; the pre-review build's refusal (AF-09's `expected.toml` `build = "refused"`)
is the visible gate on the way, and the journey stops at *ready* as the issue states, not at
a publish: publishing a completed AF-09 is `TC-REQ-136`'s oracle, not this one's.

**Written ahead of implementation: yes** — `aeh.author` does not exist yet. The guards fail
with `NotImplementedYet` naming the issue that will provide each limb; the
`WRITTEN_AHEAD_BLOCKERS` entry (`#703`, the journeys) holds the marker until the chain lands.

Disclosed assumptions (each is the reconciliation point if an implementing story ships the
surface differently):
- **The stdin walk protocol** — the clause suite's (`test_cs_author_c02_c18_cli.py`'s):
  the interactive review reads one plain-language answer line per remaining item, in the
  report's order, and EOF at a prompt means *stop*. The journeys feed one answer per
  sentinel in the draft's document order — for a fresh (never-reviewed) draft the report's
  review order is the draft's own order, which is what `FR-AUTHOR-16` walks.
- **The answers are teacher prose** — `ANSWERS` below states each value in plain language
  the review walk must translate and re-validate (`FR-AUTHOR-16`, NFR-AUTHOR-05). If a
  translation is refused (Q-O9's rejected-answer path), the journey stops short of ready and
  this file is what reconciles the wording — that failure is a finding, not a test edit.
- **The provider seam** — the env var the design declares *and* the `cli._provider_for`
  patch the clause suite uses are both set, so the journey runs under either wiring #695
  ships.
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md), for the build's store open
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
from aeh.pipeline import cli
from tests.support.author_vocabulary import (
    CHAIN_ISSUE,
    CLI_ISSUE,
    CORPUS_ISSUE,
    DEV_CI_CONFIG,
    PKG_GATE_ISSUE,
    RECORDINGS,
    af,
    placeholder_fields,
    unresolved_fields,
)
from tests.support.impl import NotImplementedYet, PIPE_PACKAGES_MODULE, require, require_path

pytestmark = [pytest.mark.e2e, pytest.mark.slow, pytest.mark.writtenahead]

CASE = "TC-E2E-07"

#: The teacher's plain-language answers, per placeholder field. The review walk presents one
#: item at a time (`FR-AUTHOR-16`); the journey answers each in the language the teacher
#: would use. A value that fails re-validation (Q-O9) keeps its item open — the journey's
#: red then names the wording, and this mapping is the reconciliation point.
TEACHER = "Prof. Dana Whitfield"
ANSWERS = {
    "approved_by": TEACHER,
    "grades": ("A starts at 80, B at 65, C at 50, D at 35, E at 20, and F covers everything "
               "below 20."),
    "bands": ("Two bands, worst first: 0 points when the essay states no thesis at all; "
              "4 points when it states a clear thesis and supports it with evidence from "
              "the text."),
    # Disclosed reconcile (the landing): a rubric the chain could not map names its
    # placeholder after the whole criterion (`criterion <qid>` — the sentinel stands in
    # the criterion's `bands` field), so the journey's answer key rides the field's first
    # word; the prose is the same teacher answer the `bands` spelling would have carried.
    "criterion": ("Two bands, worst first: 0 points when the essay states no thesis at all; "
                  "4 points when it states a clear thesis and supports it with evidence "
                  "from the text."),
    "model_answer": "3/4, because 2/8 + 4/8 = 6/8 = 3/4.",
}


def _guards() -> None:
    """Every limb the journeys traverse, each naming the issue that provides it."""
    require("aeh.conf", "panel_for_profile", issue=CHAIN_ISSUE)
    require(PIPE_PACKAGES_MODULE, "PLACEHOLDER_SENTINEL", issue=PKG_GATE_ISSUE)
    for fixture in ("AF-02", "AF-09", "AF-11"):
        require_path(af(fixture), f"the {fixture} authored fixture", issue=CORPUS_ISSUE)
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


def _draft(capsys, af_dir: Path, out: Path, provider, monkeypatch) -> tuple[int, str, str]:
    """`aeh author draft` over the corpus's recordings — the design's declared resolution
    (`HARNESS_FIXTURE_DIR`) *and* the clause suite's `cli._provider_for` seam, so the
    journey runs under either wiring #695 ships."""
    monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(RECORDINGS))
    monkeypatch.setattr(cli, "_provider_for", lambda config: provider)
    return _cli(capsys, *_draft_args(af_dir, out))


def _draft_args(af_dir: Path, out: Path) -> list[str]:
    return ["author", "draft", "--config", str(DEV_CI_CONFIG),
            "--docs", *[str(p) for p in sorted(af_dir.glob("*.pdf"))], "--out", str(out)]


def _review(capsys, draft_file: Path, answers: list[str], provider, monkeypatch
            ) -> tuple[int, str, str]:
    """The interactive review walk, scripted over stdin: one plain-language answer line per
    remaining item, in the order the walk presents them."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(answers) + "\n"))
    monkeypatch.setenv("HARNESS_FIXTURE_DIR", str(RECORDINGS))
    monkeypatch.setattr(cli, "_provider_for", lambda config: provider)
    return _cli(capsys, "author", "review", "--draft", str(draft_file))


def _answer_list(draft_text: str) -> list[str]:
    """One teacher answer per placeholder, in the draft's document order (a fresh draft's
    review order — see the docstring's disclosed stdin-protocol assumption)."""
    fields = placeholder_fields(draft_text)
    assert fields, f"{CASE}: the draft carries no placeholder to walk the teacher through"
    return [_answer_for(field) for field in fields]


def _answer_for(field: str) -> str:
    """The teacher's plain-language answer for one placeholder field."""
    for name, value in ANSWERS.items():
        if name in field:
            return value
    raise AssertionError(
        f"{CASE}: no walkthrough answer is stated for the placeholder field {field!r} — "
        f"add it to ANSWERS, or the journey cannot complete the draft the report describes")


def _sentinel_reason(draft_text: str, field: str) -> str:
    """The reason comment above the draft's sentinel for `field` (`FR-AUTHOR-11`)."""
    lines = draft_text.splitlines()
    for index, line in enumerate(lines):
        if f"<<PLACEHOLDER: {field}>>" in line and index:
            comment = re.search(r"#\s*PLACEHOLDER\(([^)]*)\)", lines[index - 1])
            if comment:
                return comment.group(1)
    raise AssertionError(
        f"{CASE}: the draft's sentinel for {field!r} carries no reason comment above it")


def _build(capsys, data_dir: Path, spec: Path, monkeypatch) -> tuple[int, str, str]:
    """`aeh package build` — the publishing gate the draft faces (`FR-PKG-28`'s refusal first)."""
    monkeypatch.delenv("HARNESS_FIXTURE_DIR", raising=False)
    monkeypatch.setattr(cli, "_provider_for",
                        lambda config: (_ for _ in ()).throw(
                            AssertionError("the build made a model call")))
    return _cli(capsys, "package", "build", "--data-dir", str(data_dir), "--spec", str(spec))


def _published_version_id(stdout: str) -> str:
    """The version id `aeh package build` printed, as `aeh run` quotes it."""
    built = json.loads(stdout)
    assert built.get("package_version"), f"{CASE}: the build printed no version id: {stdout!r}"
    return built["package_version"]


def _package_id(draft_file: Path) -> str:
    """The package id the draft file's own name states (`<package>.package.draft.toml`)."""
    name = draft_file.name
    assert name.endswith(".package.draft.toml"), (
        f"{CASE}: {name!r} is not an authoring draft's name")
    return name.removesuffix(".package.draft.toml")


def _only_draft_and_report(out: Path) -> None:
    """FR-AUTHOR-14's two-artifact rule, as the journeys see it."""
    names = sorted(p.name for p in out.iterdir())
    assert len(names) == 2, f"{CASE}: the draft wrote {names}, not exactly the two artifacts"
    assert any(n.endswith(".package.draft.toml") for n in names), names
    assert any(n.endswith(".authoring-report.md") for n in names), names


# --- journey (a): AF-02, the happy path ---------------------------------------------------------


def test_tc_e2e_07_journey_a_af02_happy_path_publishes(
        tmp_path, tmp_data_dir, capsys, make_fixture_provider, monkeypatch, network_guard):
    """AF-02 (two documents, happy path): draft→review→ready→build publishes — the journey
    ends at a published version id, never silently."""
    _guards()
    af02 = af("AF-02")
    out = tmp_path / "out"
    provider = make_fixture_provider(RECORDINGS)

    code, draft_out, draft_err = _draft(capsys, af02, out, provider, monkeypatch)
    assert code == 0, f"{CASE}: the happy draft failed: {draft_err}"
    _only_draft_and_report(out)
    draft_file = next(out.glob("*.package.draft.toml"))
    report = next(out.glob("*.authoring-report.md")).read_text(encoding="utf-8")

    # The draft states its own state (FR-AUTHOR-12's pinned section order) — the teacher is
    # never left guessing what is unresolved.
    assert "## Unresolved" in report or "# Unresolved" in report, (
        f"{CASE}: the report carries no Unresolved section")
    assert "Next command" in report, f"{CASE}: the report carries no Next command section"

    # Review completes the mandatory `approved_by` (FR-AUTHOR-09) — ready, build command.
    code, review_out, review_err = _review(
        capsys, draft_file, _answer_list(draft_file.read_text(encoding="utf-8")),
        provider, monkeypatch)
    assert code == 0, f"{CASE}: the review did not reach ready: {review_err}"
    assert "package build" in review_out + review_err, (
        f"{CASE}: a ready review must print the build command (FR-AUTHOR-17)")

    # The build publishes: the journey's end state is a version id.
    code, build_out, build_err = _build(capsys, tmp_data_dir, draft_file, monkeypatch)
    assert code == 0, f"{CASE}: the ready draft did not publish: {build_err}"
    version_id = _published_version_id(build_out)
    assert json.loads(build_out)["package_id"] == _package_id(draft_file), (
        f"{CASE}: the published package id does not match the draft's")
    network_guard.assert_no_network()
    assert version_id  # the end state, restated: a published version id exists


# --- journey (b): AF-11, the build gate ----------------------------------------------------------


def test_tc_e2e_07_journey_b_af11_the_gate_refuses_then_the_review_publishes(
        tmp_path, tmp_data_dir, capsys, make_fixture_provider, monkeypatch, network_guard):
    """AF-11 (no grade boundaries stated): the premature build is refused naming file +
    field + reason (`FR-PKG-28`), the review completes the draft, and the build then
    publishes — the human gate is load-bearing, not decorative."""
    _guards()
    af11 = af("AF-11")
    out = tmp_path / "out"
    provider = make_fixture_provider(RECORDINGS)

    code, _draft_out, draft_err = _draft(capsys, af11, out, provider, monkeypatch)
    assert code == 0, f"{CASE}: the AF-11 draft failed: {draft_err}"
    _only_draft_and_report(out)
    draft_file = next(out.glob("*.package.draft.toml"))
    draft_text = draft_file.read_text(encoding="utf-8")
    fields = placeholder_fields(draft_text)
    assert any("grades" in field for field in fields), (
        f"{CASE}: AF-11's draft carries no [grades] placeholder: {fields}")

    # The premature build is REFUSED — the visible gate. The landed gate (`FR-PKG-28`) names
    # the draft's FIRST sentinel's field and reason and counts the rest, so the assertion
    # reads what the gate actually reports (`fields[0]`, as journey (c) does); that AF-11's
    # unresolved work includes `grades` is pinned at the draft level above, and the
    # post-review publish below proves the grades answer landed.
    first = fields[0]
    code, _build_out, refused = _build(capsys, tmp_data_dir, draft_file, monkeypatch)
    assert code == 1, f"{CASE}: the placeholder-carrying draft built: {refused}"
    assert draft_file.name in refused, f"{CASE}: the refusal does not name the file: {refused!r}"
    assert first in refused, f"{CASE}: the refusal does not name the field {first!r}: {refused!r}"
    reason = _sentinel_reason(draft_text, first)
    assert reason in refused, (
        f"{CASE}: the refusal does not carry the draft's own reason {reason!r}: {refused!r}")

    # The teacher completes the draft at review — the same draft, no re-draft.
    code, review_out, review_err = _review(capsys, draft_file, _answer_list(draft_text),
                                           provider, monkeypatch)
    assert code == 0, f"{CASE}: the review did not reach ready: {review_err}"
    assert "package build" in review_out + review_err

    # And the build then publishes — the gate was the path, not a dead end.
    code, build_out, build_err = _build(capsys, tmp_data_dir, draft_file, monkeypatch)
    assert code == 0, f"{CASE}: the completed draft did not publish: {build_err}"
    assert json.loads(build_out)["package_id"] == _package_id(draft_file)
    network_guard.assert_no_network()


# --- journey (c): AF-09, total reasoning failure --------------------------------------------------


def test_tc_e2e_07_journey_c_af09_total_failure_still_ends_ready(
        tmp_path, tmp_data_dir, capsys, make_fixture_provider, monkeypatch, network_guard):
    """AF-09 (contradictory grading description): every reasoning attempt fails, the run
    continues (`NFR-AUTHOR-01`), the premature build is refused, and the review completes
    what the model could not — the journey ends *ready*, placeholders are the path to
    ready, not a dead end."""
    _guards()
    af09 = af("AF-09")
    out = tmp_path / "out"
    provider = make_fixture_provider(RECORDINGS)

    # Provider exhaustion is NOT an error: the draft lands, stating what it could not do.
    code, _draft_out, draft_err = _draft(capsys, af09, out, provider, monkeypatch)
    assert code == 0, f"{CASE}: the failing draft must not raise: {draft_err}"
    _only_draft_and_report(out)
    draft_file = next(out.glob("*.package.draft.toml"))
    draft_text = draft_file.read_text(encoding="utf-8")
    fields = placeholder_fields(draft_text)
    # The failure is stated, not swallowed: the report's Unresolved section carries the
    # sentinels (FR-AUTHOR-01's no-silent-path, at the artifact level).
    report = next(out.glob("*.authoring-report.md")).read_text(encoding="utf-8")
    assert unresolved_fields(report), (
        f"{CASE}: AF-09's report leaves the failure unstated — an empty Unresolved section")
    # Disclosed reconcile (the landing): the unmappable rubric's placeholder is named for
    # the whole criterion (`criterion Q1`), not the `bands` field the draft's sentinel
    # stands in; the contested grade boundary is a per-grade gap (`grades A`), so the
    # substring pins are the criterion and the grades family.
    for expected in ("criterion", "grades"):
        assert any(expected in field for field in fields), (
            f"{CASE}: AF-09's draft carries no {expected!r} placeholder: {fields}")

    # The visible gate on the way: the premature build is refused (expected.toml: refused).
    code, _build_out, refused = _build(capsys, tmp_data_dir, draft_file, monkeypatch)
    assert code == 1, f"{CASE}: the failing draft built: {refused}"
    assert draft_file.name in refused and _sentinel_reason(draft_text, fields[0]) in refused, (
        f"{CASE}: the refusal does not name the draft and its reason: {refused!r}")

    # The teacher fills what the model could not — the walk reaches ready.
    code, review_out, review_err = _review(capsys, draft_file, _answer_list(draft_text),
                                           provider, monkeypatch)
    assert code == 0, f"{CASE}: the review did not reach ready: {review_err}"
    assert "package build" in review_out + review_err

    # The journey's end state: ready, visible in the draft itself — no sentinel left.
    assert "<<PLACEHOLDER:" not in draft_file.read_text(encoding="utf-8"), (
        f"{CASE}: the walkthrough ended with a sentinel still in the draft")
    network_guard.assert_no_network()