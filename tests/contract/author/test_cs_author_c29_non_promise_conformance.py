"""TC-AUTHOR-29 — the non-promise conformance case: wording varies, every promise holds (TS-165, #689).

Two recorded sets for AF-01 — `fixtures/F-AUTHOR/recordings/` and the variant set
(`AF01_VARIANT_RECORDINGS`) — whose drafts come out with different band names, different band
counts and different question ids. CT-AUTHOR-17 does not promise any of that wording, so this
case proves the two things that CAN be promised around it:

1. **Both drafts satisfy the CT-AUTHOR-03..08 field sets and rules** — the question/criterion
   field sets, the sentinel-and-reason discipline on the raw draft, the report's section order,
   and the deterministic rules (bands even, 2-6, worst-first non-decreasing; every question
   covered; the mcq key among the options) — with `validate_draft` clean on both.
2. **Both reach ready and build** — the scripted review answers `approved_by` (FR-AUTHOR-09's
   mandatory placeholder; AF-01's reasoning steps resolve fully), and `aeh package build`
   publishes both — so *nothing downstream diffs wording*: the variation is real (asserted),
   and every consumer accepts both.

The structural-equality rule (the plan's oracle column) is field sets and rules, never text.
Guards first: the `aeh.author` surface (#689), then both recorded sets and AF-01 (#686). The
variant set's path is the vocabulary's disclosed guess — if #686 lands it elsewhere, that is a
one-line reconciliation in `tests/support/author_vocabulary.py`.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from tests.support.author_vocabulary import (
    AF01_VARIANT_RECORDINGS,
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    PLACEHOLDER_COMMENT_RE,
    RECORDINGS,
    af,
    chain_from_config,
    make_service,
    placeholder_fields,
    scripted_answers,
)
from tests.support.impl import require, require_attr, require_path

pytestmark = [pytest.mark.contract]

TEACHER = "Sample-materials teacher"

QUESTION_FIELDS = {"id", "type", "points", "text", "model_answer"}
CRITERION_FIELDS = {"id", "question"}
REPORT_SECTIONS = ("Documents", "Steps", "Items", "Unresolved", "Next command")


def _guards(make_fixture_provider) -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names
    require_attr(author, "AuthoringInputError", issue=AUTHOR_ISSUE)
    require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    variant = require_path(AF01_VARIANT_RECORDINGS, "AF-01's variant recordings",
                           issue=CORPUS_ISSUE)
    return author, recordings, variant


def _sections_in_order(report_text: str) -> None:
    """The report's section headings appear as a word subsequence (CT-AUTHOR-05's order)."""
    cursor = 0
    for section in REPORT_SECTIONS:
        found = report_text.find(section, cursor)
        assert found != -1, f"the report does not carry the {section!r} section in order"
        cursor = found + len(section)


def _rules_hold(author, spec: dict) -> None:
    """The deterministic rules (CT-AUTHOR-08, FR-AUTHOR-10) on a ready AF-01 spec, field sets
    first (CT-AUTHOR-03)."""
    questions = spec["question"]
    assert questions, "a draft with no questions cannot be a package"
    for question in questions:
        assert QUESTION_FIELDS <= set(question), f"{question.get('id')}: missing question fields"
        if question["type"] == "mcq":
            assert question.get("options"), f"{question['id']}: an mcq with no options"
    criteria = spec["criterion"]
    assert criteria, "a draft with no criteria cannot be graded"
    covered = set()
    for criterion in criteria:
        assert CRITERION_FIELDS <= set(criterion), f"{criterion.get('id')}: missing criterion fields"
        assert criterion["question"] in {q["id"] for q in questions}, (
            f"{criterion['id']}: references an unknown question")
        covered.add(criterion["question"])
        if "bands" in criterion:
            bands = criterion["bands"]
            assert 2 <= len(bands) <= 6 and len(bands) % 2 == 0, (
                f"{criterion['id']}: {len(bands)} bands")
            points = [band["points"] for band in bands]
            assert points == sorted(points), f"{criterion['id']}: bands not worst-first"
            assert all("name" in band and "descriptor" in band for band in bands)
        else:
            assert criterion.get("key") is not None or "key" in criterion, (
                f"{criterion['id']}: neither bands nor a key")
            question = next(q for q in questions if q["id"] == criterion["question"])
            if question["type"] == "mcq":
                assert criterion["key"] in question["options"], (
                    f"{criterion['id']}: the key is not among the options")
    assert covered == {q["id"] for q in questions}, "a question is not covered by any criterion"
    assert author.validate_draft(spec) == []


def _conforming_flow(author, recordings: Path, out: Path, make_fixture_provider) -> dict:
    """Draft AF-01 against one recorded set; assert the promised properties on the way to a
    ready, buildable draft; return the parsed spec of the final draft."""
    service = make_service(author, chain_from_config(), make_fixture_provider(recordings))
    result = service.draft(documents=sorted(af("AF-01").glob("*.pdf")), output_dir=out)
    raw_text = result.draft_path.read_text(encoding="utf-8")

    # CT-AUTHOR-04's discipline on the raw draft: the mandatory approved_by placeholder
    # (FR-AUTHOR-09) carries its reason comment on the line above, and counts agree.
    lines = raw_text.splitlines()
    fields = placeholder_fields(raw_text)
    # Disclosed reconcile (the landing): `approved_by` rides on top of every outcome class
    # (TC-AUTHOR-12) and is never counted — TC-AUTHOR-01 pins AF-01 at zero placeholders —
    # so the count reads the content sentinels only, the same exclusion TC-AUTHOR-14's
    # oracle states once for the family.
    content_fields = [field for field in fields if field != "approved_by"]
    assert result.placeholders == len(content_fields), (result.placeholders, fields)
    for index, line in enumerate(lines):
        if "<<PLACEHOLDER:" in line:
            assert index > 0 and PLACEHOLDER_COMMENT_RE.search(lines[index - 1]), (
                f"line {index}: a sentinel without its reason comment above it")
    # CT-AUTHOR-05: the report is the complete trace, sections in order.
    _sections_in_order(result.report_path.read_text(encoding="utf-8"))

    review = service.review(draft_path=result.draft_path, answers=scripted_answers(
        author, raw_text, {"approved_by": TEACHER}))
    assert review.ready and review.remaining == (), review

    final_text = result.draft_path.read_text(encoding="utf-8")
    assert not placeholder_fields(final_text), "a ready draft still carries a sentinel"
    spec = tomllib.loads(final_text)
    _rules_hold(author, spec)
    return spec


def test_tc_author_c29_two_wordings_of_af01_every_promise_holds_on_both(
        tmp_path, tmp_data_dir, make_fixture_provider):
    """Draft AF-01 against both recorded sets: both conform to the field sets and rules, both
    review to ready and build — and the wording really differs, so the equal outcomes prove
    nothing downstream depends on it."""
    author, recordings, variant = _guards(make_fixture_provider)
    from aeh.pipeline import cli

    spec_main = _conforming_flow(author, recordings, tmp_path / "main", make_fixture_provider)
    spec_variant = _conforming_flow(author, variant, tmp_path / "variant", make_fixture_provider)

    # The variation is real — different band names, a different band count, different ids.
    bands_of = lambda spec: {b["name"] for c in spec["criterion"] for b in c.get("bands", [])}  # noqa: E731
    assert bands_of(spec_main) and not (bands_of(spec_main) & bands_of(spec_variant)), (
        "the variant recordings produced the same band names — the conformance case is vacuous")
    counts_main = [len(c["bands"]) for c in spec_main["criterion"] if "bands" in c]
    counts_variant = [len(c["bands"]) for c in spec_variant["criterion"] if "bands" in c]
    assert counts_main != counts_variant, "the variant recordings produced the same band counts"
    assert [q["id"] for q in spec_main["question"]] != [q["id"] for q in spec_variant["question"]]

    # Nothing downstream diffs wording: both build.
    main_spec_path = tmp_path / "main-built.toml"
    variant_spec_path = tmp_path / "variant-built.toml"
    main_spec_path.write_text(_emit(spec_main), encoding="utf-8")
    variant_spec_path.write_text(_emit(spec_variant), encoding="utf-8")
    assert cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(main_spec_path)]) == 0
    assert cli.main(["package", "build", "--data-dir", str(tmp_path / "variant-store"),
                     "--spec", str(variant_spec_path)]) == 0, (
        "the build depends on the unpromised wording")


def _emit(spec: dict) -> str:
    """Minimal TOML emitter for the operator vocabulary (tomli_w is not a dependency)."""
    scalars, arrays, tables = [], [], []
    for key, value in spec.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            arrays.append((key, value))
        elif isinstance(value, dict):
            tables.append((key, value))
        else:
            scalars.append((key, value))

    def value_of(value):
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            # json.dumps is the spec vocabulary's own `_toml_str` (spec_export): it escapes
            # the control characters (newlines in a `derivation_description`) a minimal
            # quote-and-backslash pass would emit raw into a single-line TOML string.
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, dict):
            return "{ " + ", ".join(f"{k} = {value_of(v)}" for k, v in value.items()) + " }"
        if isinstance(value, (list, tuple)):
            return "[ " + ", ".join(value_of(item) for item in value) + " ]"
        return str(value)

    lines = [f"{k} = {value_of(v)}" for k, v in scalars]
    for key, rows in arrays:
        for row in rows:
            lines.append(f"[[{key}]]")
            lines.extend(f"{k} = {value_of(v)}" for k, v in row.items())
    for key, table in tables:
        lines.append(f"[{key}]")
        lines.extend(f"{k} = {value_of(v)}" for k, v in table.items())
    return "\n".join(lines) + "\n"