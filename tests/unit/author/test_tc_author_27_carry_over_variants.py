"""`TC-AUTHOR-27` (FR-AUTHOR-23 / CT-AUTHOR-19, CT-AUTHOR-20, P0) — the carry-over variants,
each pinned to its exact outcome (the package-authoring test plan §5.2; design delta §3.1).

    | AF-13 re-draft after teacher edit; variants: previously-answered item vanished;
    | fingerprint mismatch; prior report without answer records |
    Expected: unchanged answers re-applied as provisional; changed answers dropped and named
    with the reason; fingerprints recorded in report Items; vanished/mismatched/unrecorded
    carry nothing.
    Oracle: exact carry-over outcomes.

Story #697 (TS-163), which depends on #696. The library carry-over landed with #697
(`aeh.author.carryover`): this file's marker came off at that landing and the file rejoined
`TEST_CMD` (the test was kept, never rewritten — the assertions below are the ones written
ahead of the implementation). The `aeh.author` surface itself landed with the first service
story (#690).

**Rung 1 (headless in-process), and the limbs this case owns.** `TC-AUTHOR-C19`/`C20`'s
clause file pins the *accountability* (every recorded answer is either carried provisional
or named dropped) and the record/fingerprint format; the plan's §5.2 row for -27 pins the
*exact outcomes per variant*, and it is this file that constructs each variant deliberately.
The variants are built from the REAL flow — draft AF-01, answer `approved_by` at review — so
the record shape is never invented: the prior report's own answer-record lines are cloned and
mutated per variant (this is the disclosed reconciliation point: if the report format
changes, the cloning here follows it, because it is read off a real report, not parsed
against a fixed grammar). Each variant is then placed as the prior flow's two artifacts in
its own output directory — same package stem, since AF-13 is AF-01's test with one question
reworded (design §5.1, same package id) — and the re-draft runs with `force` over AF-13's
documents:

- **unchanged & matching** (the real report verbatim): the answer is carried — and only
  provisional: a fresh `review(answers=[])` over the re-draft must still ask for the item
  (behaviour, not a report token), and the new report carries a fingerprint for it against
  the regenerated content;
- **vanished** (the record's item id renamed to one no draft has): nothing is carried, and
  the vanished id is named in the new report — accountable, never silent. This naming
  assertion is non-vacuous: the vanished id appears in no draft, so the only way it reaches
  the new report is the drop account;
- **fingerprint-mismatched** (the record's fingerprint corrupted): nothing is carried —
  the item's placeholder returns — and the recorded ANSWER's value is named in the new
  report. The item id alone is NOT enough there: after a drop the item returns as a
  placeholder, and the report's Unresolved section names every placeholder the draft
  carries (`CT-AUTHOR-04`), so `"approved_by" in report` would pass with zero drop
  accounting. The answer's value, by contrast, reaches the report only through the account
  of the dropped answer — FR-AUTHOR-23's "named with the reason";
- **unrecorded** (the unreviewed flow's report, no answer records): nothing is carried at
  all — the C19 clause's no-records rule, pinned here on the AF-13 pair.

Isolation is the plan's rung-1 row: the injected provider is the recorded tree via the
conftest factory (`CT-PROV-10`), the chain is the one the config names (`chain_from_config`),
the autouse socket guard is armed throughout, and the final assertion is that it recorded
zero attempts — no live calls in this suite. The library form of the CLI's `--force` is
`FORCE_KWARG` (the vocabulary's disclosed bet).

Disclosed fixture assumptions, to reconcile at the landing (the assertions stay the plan's):
- AF-01's only review answer is `approved_by` (its outcome class is fully resolved), and
  `approved_by`'s content is unchanged between AF-01 and AF-13 — so the real report's record
  IS the unchanged-and-matching variant (AF-13's `carry_over` expectation names an unchanged
  item carried and a changed item dropped; the changed item is the reworded question, which
  AF-01's flow never answered). If #686's corpus contradicts this, the variant construction
  — not the assertions — moves.
- A carried answer appears in the re-draft's spec text (the clause suite's C20 bet, shared
  here); provisional-ness is checked by behaviour, not by any "provisional" token.
- A content fingerprint renders as a hex run (`_FINGERPRINT_RE` below, the clause suite's
  local `HEX_RE` shape — the design pins the record's existence, not its rendering; if #696
  renders it differently, this regex and the cloning are the one-line change).
"""

from __future__ import annotations

import re
import shutil
import tomllib
from pathlib import Path

from tests.support.author_vocabulary import (
    AF13_PAIR,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    FORCE_KWARG,
    RECORDINGS,
    RETRY_ISSUE,
    af,
    chain_from_config,
    make_service,
    placeholder_fields,
    scripted_answers,
)
from tests.support.impl import require, require_path

TEACHER = "Sample-materials teacher"
VANISHED_ITEM = "vanished-item-no-draft-has-this"

#: A content fingerprint as the report renders it — a hex run of 8-64 characters (see the
#: module docstring's last disclosure; the same shape the clause suite's local `HEX_RE` uses).
_FINGERPRINT_RE = re.compile(r"\b[0-9a-fA-F]{8,64}\b")


def _guards(make_fixture_provider) -> tuple:
    """The require-style gates, and the first thing each test body does: a missing
    implementation is `NotImplementedYet` naming the blocker — never a collection error.
    The module surface is named with this file's own story (#697 — whose closure removes the
    marker); the corpus paths, the recordings and their capture manifest are #686's facts."""
    author = require(AUTHOR_MODULE, issue=RETRY_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=RETRY_ISSUE)  # the §3.1 names
    for fixture in AF13_PAIR:
        require_path(af(fixture), f"the {fixture} authored fixture", issue=CORPUS_ISSUE)
    require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    require_path(
        RECORDINGS / "coverage.json", "the authoring recordings' capture manifest",
        issue=CORPUS_ISSUE)
    return author, RECORDINGS


def _service(author, recordings, make_fixture_provider):
    return make_service(author, chain_from_config(), make_fixture_provider(recordings))


def _prints_on_item_lines(report: str, item_id: str) -> list[str]:
    """The fingerprint-shaped runs on the report lines that name `item_id`."""
    lines = [line for line in report.splitlines() if item_id in line]
    return sorted({h for line in lines for h in _FINGERPRINT_RE.findall(line)})


def _prior_flow(author, recordings, make_fixture_provider, tmp_path):
    """The real flow: draft AF-01 (unreviewed, for the no-records variant), then a second
    draft reviewed with `approved_by` (for the carried / mutated variants). Returns the
    reviewed flow's output directory, its artifact filenames, and the two report texts."""
    service = _service(author, recordings, make_fixture_provider)
    plain = service.draft(documents=sorted(af(AF13_PAIR[0]).glob("*.pdf")),
                          output_dir=tmp_path / "plain")
    plain_report = plain.report_path.read_text(encoding="utf-8")
    names = sorted(p.name for p in (tmp_path / "plain").iterdir())
    assert any(n.endswith(".package.draft.toml") for n in names), (
        "the unreviewed flow wrote its draft artifact")

    reviewed_out = tmp_path / "reviewed"
    reviewed = service.draft(documents=sorted(af(AF13_PAIR[0]).glob("*.pdf")),
                             output_dir=reviewed_out)
    review = service.review(
        draft_path=reviewed.draft_path,
        answers=scripted_answers(author, reviewed.draft_path.read_text(encoding="utf-8"),
                                 {"approved_by": TEACHER}))
    assert review.ready, "TC-AUTHOR-27's setup: AF-01's scripted review must reach ready"
    real_report = reviewed.report_path.read_text(encoding="utf-8")
    assert TEACHER in real_report, (
        "TC-AUTHOR-27's setup: the review recorded the answer in the report")
    assert _prints_on_item_lines(real_report, "approved_by"), (
        "TC-AUTHOR-27's setup: the answer record carries a content fingerprint")
    return reviewed_out, names, plain_report, real_report


def _variant_dir(source: Path, names: list[str], target: Path, report_text: str) -> None:
    """One variant's prior state: the real flow's two artifacts copied under the same package
    stem, with the report replaced by the variant's text."""
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(source / name, target / name)
    report_name = next(n for n in names if n.endswith(".authoring-report.md"))
    (target / report_name).write_text(report_text, encoding="utf-8")


def _redraft(author, recordings, make_fixture_provider, out: Path):
    """The force re-draft over AF-13's documents, reading the variant prior state."""
    return _service(author, recordings, make_fixture_provider).draft(
        documents=sorted(af(AF13_PAIR[1]).glob("*.pdf")), output_dir=out,
        **{FORCE_KWARG: True})


def test_tc_author_27_each_carry_over_variant_lands_on_its_exact_outcome(
        tmp_path, make_fixture_provider, network_guard):
    """Four prior-report variants, four exact outcomes — carried-provisional, vanished-dropped,
    mismatch-dropped, unrecorded-nothing — with nothing silent anywhere."""
    author, recordings = _guards(make_fixture_provider)
    reviewed_out, names, plain_report, real_report = _prior_flow(
        author, recordings, make_fixture_provider, tmp_path)
    prior_questions = {q["text"] for q in tomllib.loads(
        (reviewed_out / next(n for n in names if n.endswith(".package.draft.toml"))
         ).read_text(encoding="utf-8"))["question"]}

    # --- variant 1: unchanged and matching — the real report verbatim --------------------------
    carried_dir = tmp_path / "carried"
    _variant_dir(reviewed_out, names, carried_dir, real_report)
    redraft = _redraft(author, recordings, make_fixture_provider, carried_dir)
    carried_text = redraft.draft_path.read_text(encoding="utf-8")
    carried_report = redraft.report_path.read_text(encoding="utf-8")
    # The re-draft really regenerated from AF-13's edited documents.
    assert {q["text"] for q in tomllib.loads(carried_text)["question"]} != prior_questions
    # Carried — and provisional only.
    assert TEACHER in carried_text, (
        "TC-AUTHOR-27 variant 1: the unchanged, fingerprint-matching answer is carried into "
        "the re-draft (FR-AUTHOR-23)")
    reconfirmed = _service(author, recordings, make_fixture_provider).review(
        draft_path=redraft.draft_path, answers=[])
    assert not reconfirmed.ready, (
        "TC-AUTHOR-27 variant 1: a carried-over answer must not count as confirmed at review "
        "(FR-AUTHOR-23)")
    assert any("approved_by" in str(item) for item in reconfirmed.remaining), (
        f"TC-AUTHOR-27 variant 1: the carried item must remain to confirm: "
        f"{reconfirmed.remaining}")
    assert _prints_on_item_lines(carried_report, "approved_by"), (
        "TC-AUTHOR-27 variant 1: the carried answer carries a fingerprint against the "
        "regenerated content (FR-AUTHOR-23)")

    # --- variant 2: vanished — the record's item id exists in no draft ---------------------------
    vanished_dir = tmp_path / "vanished"
    _variant_dir(reviewed_out, names, vanished_dir,
                 real_report.replace("approved_by", VANISHED_ITEM))
    redraft = _redraft(author, recordings, make_fixture_provider, vanished_dir)
    vanished_text = redraft.draft_path.read_text(encoding="utf-8")
    vanished_report = redraft.report_path.read_text(encoding="utf-8")
    assert TEACHER not in vanished_text, (
        "TC-AUTHOR-27 variant 2: a record for an item no draft has carries nothing "
        "(FR-AUTHOR-23)")
    assert VANISHED_ITEM in vanished_report, (
        "TC-AUTHOR-27 variant 2: the vanished record is named in the new report — dropped "
        "answers are accounted for, never silent (FR-AUTHOR-23). Non-vacuous: the vanished "
        "id appears in no draft, so only the drop account can put it in the report")

    # --- variant 3: fingerprint mismatch — the record's fingerprint corrupted ---------------------
    mismatched_dir = tmp_path / "mismatched"
    prints = _prints_on_item_lines(real_report, "approved_by")
    corrupted = real_report
    for print_hex in prints:  # corrupt every fingerprint run on the item's lines
        corrupted = corrupted.replace(print_hex, "0" * len(print_hex))
    assert corrupted != real_report, "the corruption must actually change the report"
    _variant_dir(reviewed_out, names, mismatched_dir, corrupted)
    redraft = _redraft(author, recordings, make_fixture_provider, mismatched_dir)
    mismatched_text = redraft.draft_path.read_text(encoding="utf-8")
    mismatched_report = redraft.report_path.read_text(encoding="utf-8")
    assert TEACHER not in mismatched_text, (
        "TC-AUTHOR-27 variant 3: a fingerprint-mismatched answer is not carried — the "
        "content the answer was given against has moved (FR-AUTHOR-23)")
    assert "approved_by" in placeholder_fields(mismatched_text), (
        "TC-AUTHOR-27 variant 3: the dropped answer's placeholder returns to be answered "
        "again (FR-AUTHOR-23)")
    # The drop is ACCOUNTED for, not silent. The item id alone would be vacuous here — after
    # a drop the item returns as a placeholder and the report's Unresolved section names
    # every placeholder (CT-AUTHOR-04) — so the recorded ANSWER's value is what the account
    # must name (FR-AUTHOR-23: dropped answers "named with the reason").
    assert TEACHER in mismatched_report, (
        "TC-AUTHOR-27 variant 3: the mismatched record is named dropped in the new report — "
        "the recorded answer is accounted for, never silently gone (FR-AUTHOR-23)")

    # --- variant 4: unrecorded — the prior report carries no answer records ------------------------
    unrecorded_dir = tmp_path / "unrecorded"
    _variant_dir(reviewed_out, names, unrecorded_dir, plain_report)
    assert TEACHER not in plain_report, (
        "TC-AUTHOR-27's setup: the unreviewed report records no answers")
    redraft = _redraft(author, recordings, make_fixture_provider, unrecorded_dir)
    unrecorded_text = redraft.draft_path.read_text(encoding="utf-8")
    assert TEACHER not in unrecorded_text, (
        "TC-AUTHOR-27 variant 4: a report with no answer records carries nothing into a "
        "later re-draft (CT-AUTHOR-19)")
    assert "approved_by" in placeholder_fields(unrecorded_text), (
        "TC-AUTHOR-27 variant 4: with nothing carried, the item's placeholder returns "
        "(FR-AUTHOR-23)")

    # --- isolation, positively: zero egress across every limb ----------------------------------------
    network_guard.assert_no_network()