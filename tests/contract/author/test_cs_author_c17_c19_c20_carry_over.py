"""CT-AUTHOR-17 (non-promise), CT-AUTHOR-19 and CT-AUTHOR-20 — wording is free, answers are recorded, carry-over is accountable (TS-165, #689).

| TC ID | Clause | Breaks if |
|---|---|---|
| TC-AUTHOR-C17 | CT-AUTHOR-17 behaviour (**not promised**) | some consumer depends on the unpromised wording: band names, band counts and question ids are varied on a ready draft and every consumer — the field sets, the deterministic rules, reaching ready and the build — must still behave |
| TC-AUTHOR-C19 | CT-AUTHOR-20 data | the report's Items section does not record, per answered item, the answer and the fingerprint of the content it was given against; or the fingerprint moves when only the answer moved (it is a hash over the item's id and underlying content, FR-AUTHOR-23); or a report with no answer records carries anything into a later re-draft |
| TC-AUTHOR-C20 | CT-AUTHOR-19 behaviour | a re-draft after the teacher edited their description silently drops an answer, mis-applies one, or presents a carried-over answer as final |

The wording variation is done by the test itself (parse the ready draft, rename every band,
add two zero-point bands to every bands set with room under the six-band ceiling, rename every
question id consistently with the criterion references, re-emit TOML) — CT-AUTHOR-17 says
these are model-produced and may vary, so a consumer that stops working when they do is the
defect. The TOML emitter is a small writer for the operator vocabulary's shapes (scalars,
inline tables, arrays of tables). Splitting a band into three keeps the band count even, so
the varied spec still passes the deterministic rules — the variation must be *legal*, only
unpromised.

Rung 1, guards first (#689 then #686). The carry-over pair is AF-01 → AF-13 (design §5.1:
AF-13 is AF-01's test with one question reworded and the rubric memo edited — same package id,
so the re-draft sees the prior report). Disclosed: AF-01's outcome class is fully resolved, so
its only review answer is `approved_by` — the carry-over assertions therefore pin the
*accountability* (every recorded answer is either carried as provisional or named as dropped
with a reason), not the size of the answer set; and what counts as "recorded" is read off the
PRIOR report, so the case holds whether or not #686's AF-01 expected class counts the
mandatory `approved_by` placeholder (FR-AUTHOR-09). Provisional-ness is checked by behaviour,
not by a report token: a fresh `review(answers=[])` over the re-draft must still ask for the
carried item (the empty list is the scripted form answering nothing; `None` would mean the
interactive walk).

The library form of the CLI's `--force` is `FORCE_KWARG` (the vocabulary's disclosed bet).
"""

from __future__ import annotations

import copy
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from tests.support.author_vocabulary import (
    AF13_PAIR,
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    FORCE_KWARG,
    RECORDINGS,
    af,
    chain_from_config,
    make_service,
    placeholder_fields,
    scripted_answers,
)
from tests.support.impl import require, require_attr, require_path

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]

TEACHER = "Sample-materials teacher"
HEX_RE = re.compile(r"\b[0-9a-fA-F]{8,64}\b")


def _guards(make_fixture_provider) -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names
    require_attr(author, "AuthoringInputError", issue=AUTHOR_ISSUE)
    for fixture in (AF13_PAIR[0], AF13_PAIR[1], "AF-07"):
        require_path(af(fixture), f"the {fixture} authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, recordings


def _service(author, recordings, make_fixture_provider):
    return make_service(author, chain_from_config(), make_fixture_provider(recordings))


def _draft(author, recordings, af_id: str, out: Path, make_fixture_provider):
    return _service(author, recordings, make_fixture_provider).draft(
        documents=sorted(af(af_id).glob("*.pdf")), output_dir=out)


def _draft_and_review(author, recordings, af_id: str, out: Path,
                      make_fixture_provider, answers: dict[str, str]):
    service = _service(author, recordings, make_fixture_provider)
    result = service.draft(documents=sorted(af(af_id).glob("*.pdf")), output_dir=out)
    text = result.draft_path.read_text(encoding="utf-8")
    review = service.review(draft_path=result.draft_path,
                            answers=scripted_answers(author, text, answers))
    return result, review, text


def _hexes_on_item_lines(report: str, item_id: str) -> list[str]:
    """The fingerprint-shaped hex strings on the report lines that name `item_id`."""
    lines = [line for line in report.splitlines() if item_id in line]
    return sorted({h for line in lines for h in HEX_RE.findall(line)})


# --- the wording variation (CT-AUTHOR-17's instrument) ----------------------------------------


def _emit_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {_emit_value(v)}" for k, v in value.items()) + " }"
    if isinstance(value, (list, tuple)):
        return "[ " + ", ".join(_emit_value(item) for item in value) + " ]"
    raise TypeError(f"the emitter does not know {type(value).__name__}")


def _emit_toml(spec: dict[str, Any]) -> str:
    scalars, arrays, tables = [], [], []
    for key, value in spec.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            arrays.append((key, value))
        elif isinstance(value, dict):
            tables.append((key, value))
        else:
            scalars.append((key, value))
    lines = [f"{k} = {_emit_value(v)}" for k, v in scalars]
    for key, rows in arrays:
        for row in rows:
            lines.append(f"[[{key}]]")
            lines.extend(f"{k} = {_emit_value(v)}" for k, v in row.items())
    for key, table in tables:
        lines.append(f"[{key}]")
        lines.extend(f"{k} = {_emit_value(v)}" for k, v in table.items())
    return "\n".join(lines) + "\n"


def _vary_wording(spec: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Rename every question id (and the criterion references), rename every band name, and —
    where a bands set has room under the six-band ceiling (2..6, even) — split one band into
    three, adding two zero-point shifts. Returns (varied, split_any)."""
    varied = copy.deepcopy(spec)
    id_map = {q["id"]: f"{q['id']}-v" for q in varied.get("question", [])}
    for question in varied.get("question", []):
        question["id"] = id_map[question["id"]]
    split_any = False
    for criterion in varied.get("criterion", []):
        if criterion.get("question") in id_map:
            criterion["question"] = id_map[criterion["question"]]
        if "bands" in criterion:
            for band in criterion["bands"]:
                band["name"] = f"z-{band['name']}"
            if len(criterion["bands"]) <= 4:  # +2 must stay under the six-band ceiling
                first = criterion["bands"][0]
                criterion["bands"][0:1] = [
                    {"name": f"{first['name']}-a", "points": first["points"],
                     "descriptor": first["descriptor"]},
                    {"name": f"{first['name']}-b", "points": first["points"],
                     "descriptor": first["descriptor"]},
                ]
                split_any = True
    return varied, split_any


# --- TC-AUTHOR-C17 ----------------------------------------------------------------------------


def test_tc_author_c17_varying_the_unpromised_wording_keeps_every_consumer_working(
        tmp_path, tmp_data_dir, make_fixture_provider):
    """A ready AF-01 draft builds; the same draft with every band renamed, an extra zero-point
    pair wherever a bands set had room under the ceiling, and every question id renamed still
    validates clean and still builds — and the variation is real, not cosmetic."""
    author, recordings = _guards(make_fixture_provider)
    from aeh.pipeline import cli

    out = tmp_path / "out"
    result, review, text = _draft_and_review(
        author, recordings, AF13_PAIR[0], out, make_fixture_provider, {"approved_by": TEACHER})
    assert review.ready and review.remaining == ()

    assert cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(result.draft_path)]) == 0

    original = tomllib.loads(text)
    varied, split_any = _vary_wording(original)
    # The variation is real: band names and the question ids all moved — and wherever the
    # split fired, a band count moved too.
    original_bands = {b["name"] for c in original["criterion"] for b in c.get("bands", [])}
    varied_bands = {b["name"] for c in varied["criterion"] for b in c.get("bands", [])}
    assert original_bands and not (original_bands & varied_bands)
    if split_any:
        assert any(len(c["bands"]) != len(o["bands"])
                   for c, o in zip(varied["criterion"], original["criterion"]))
    assert [q["id"] for q in varied["question"]] != [q["id"] for q in original["question"]]

    varied_path = out / "varied.package.draft.toml"
    varied_path.write_text(_emit_toml(varied), encoding="utf-8")
    assert author.validate_draft(varied) == [], (
        "the varied spec must still pass the deterministic rules")
    assert cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(varied_path)]) == 0, (
        "the build must not depend on the unpromised wording")


# --- TC-AUTHOR-C19 ----------------------------------------------------------------------------


def test_tc_author_c19_answer_records_and_content_fingerprints_in_report_items(
        tmp_path, make_fixture_provider):
    """Two identical AF-07 flows whose answers differ: the report records every answer and a
    fingerprint per item, and the fingerprint is equal where the content is equal — even
    though the answers differ. A report with no answer records carries nothing into a re-draft."""
    author, recordings = _guards(make_fixture_provider)
    service = _service(author, recordings, make_fixture_provider)

    first = service.draft(documents=sorted(af("AF-07").glob("*.pdf")),
                          output_dir=tmp_path / "one")
    fields = placeholder_fields(first.draft_path.read_text(encoding="utf-8"))
    assert fields, "AF-07 must leave placeholders to answer"
    answers_one = {f: (TEACHER if "approved" in f.lower()
                       else "Answer one, the teacher's wording.") for f in fields}
    answers_two = dict(answers_one)
    changed = next(f for f in fields if "approved" not in f.lower())
    answers_two[changed] = "Answer two, deliberately different wording."

    review_one = service.review(draft_path=first.draft_path,
                                answers=scripted_answers(author, first.draft_path.read_text(
                                    encoding="utf-8"), answers_one))
    assert review_one.ready
    report_one = first.report_path.read_text(encoding="utf-8")

    second = service.draft(documents=sorted(af("AF-07").glob("*.pdf")),
                           output_dir=tmp_path / "two")
    review_two = service.review(draft_path=second.draft_path,
                                answers=scripted_answers(author, second.draft_path.read_text(
                                    encoding="utf-8"), answers_two))
    assert review_two.ready
    report_two = second.report_path.read_text(encoding="utf-8")

    for item_id, answer in answers_one.items():
        assert item_id in report_one and answer in report_one, (
            f"{item_id}: the answer record is missing from the report")
    assert answers_two[changed] in report_two and answers_one[changed] not in report_two

    # The fingerprint follows the content, not the answer: equal across the two flows.
    for item_id in fields:
        prints_one = _hexes_on_item_lines(report_one, item_id)
        prints_two = _hexes_on_item_lines(report_two, item_id)
        assert prints_one, f"{item_id}: no content fingerprint in the report"
        assert prints_one == prints_two, (
            f"{item_id}: the fingerprint moved although the content did not")

    # A report with no answer records carries nothing into a later re-draft: re-draft AF-07
    # over its own unreviewed draft (force, same directory) and nothing may be applied.
    plain = service.draft(documents=sorted(af("AF-07").glob("*.pdf")),
                          output_dir=tmp_path / "three")
    redraft = service.draft(documents=sorted(af("AF-07").glob("*.pdf")),
                            output_dir=tmp_path / "three", **{FORCE_KWARG: True})
    redraft_text = redraft.draft_path.read_text(encoding="utf-8")
    assert redraft.placeholders == plain.placeholders
    assert "Answer one" not in redraft_text and TEACHER not in redraft_text


# --- TC-AUTHOR-C20 ----------------------------------------------------------------------------


def test_tc_author_c20_carry_over_is_accountable_never_silent(
        tmp_path, make_fixture_provider):
    """Draft AF-01, answer at review, re-draft from AF-13's edited documents into the same
    directory with force: the recorded answer is either carried over as provisional (marked in
    the new report) or dropped with a named reason — never silently gone; and the re-draft
    really regenerated from the edited documents."""
    author, recordings = _guards(make_fixture_provider)
    out = tmp_path / "out"

    result, review, text = _draft_and_review(
        author, recordings, AF13_PAIR[0], out, make_fixture_provider, {"approved_by": TEACHER})
    assert review.ready
    prior_report = result.report_path.read_text(encoding="utf-8")
    prior_questions = {q["text"] for q in tomllib.loads(text)["question"]}

    redraft = _service(author, recordings, make_fixture_provider).draft(
        documents=sorted(af(AF13_PAIR[1]).glob("*.pdf")), output_dir=out,
        **{FORCE_KWARG: True})
    service = _service(author, recordings, make_fixture_provider)
    new_text = redraft.draft_path.read_text(encoding="utf-8")
    new_report = redraft.report_path.read_text(encoding="utf-8")

    # The re-draft really came from the edited documents.
    assert {q["text"] for q in tomllib.loads(new_text)["question"]} != prior_questions

    # The recorded answer is accounted for. What counts as "recorded" is decided by the PRIOR
    # report: if review recorded the answer, the re-draft either carries it as provisional
    # (marked in the new report, fingerprinted against the regenerated content) or drops it
    # by name — never silently; if nothing was recorded (whether #686's AF-01 class counts
    # the mandatory approved_by placeholder decides this), none of it may appear either.
    recorded = TEACHER in prior_report
    carried = TEACHER in new_text
    if recorded and carried:
        # Carried, but not final: a fresh scripted review answering nothing must still ask for
        # the carried item — provisional until the teacher confirms it at review. Checked by
        # behaviour, not by pinning any "provisional" wording in the report.
        reconfirmed = service.review(draft_path=redraft.draft_path, answers=[])
        assert not reconfirmed.ready, (
            "a carried-over answer must not count as confirmed at review")
        assert any("approved_by" in str(item) for item in reconfirmed.remaining), (
            f"the carried item must remain to confirm: {reconfirmed.remaining}")
        assert _hexes_on_item_lines(new_report, "approved_by"), (
            "the carried answer carries no fingerprint against the regenerated content")
    elif recorded:
        assert "approved_by" in new_report, (
            "a dropped answer must be named in the new report")
        assert "approved_by" in placeholder_fields(new_text), (
            "a dropped approved_by answer must leave the placeholder it must return to")
    else:
        assert not carried and TEACHER not in new_report, (
            "an answer no review recorded appeared in the re-draft anyway")