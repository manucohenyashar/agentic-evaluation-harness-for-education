"""CT-AUTHOR-04 and CT-AUTHOR-05 — the sentinel format and the report's section contract (TS-165, #689).

| TC ID | Clause | Breaks if |
|---|---|---|
| TC-AUTHOR-C04 | CT-AUTHOR-04 data | the sentinel `<<PLACEHOLDER: <field>>>` appears exactly in that shape with a `# PLACEHOLDER(<reason>):` comment on the line above; the sentinel is the *value* of the field it occupies and cannot collide with any legal TOML value; a fully resolved draft carries none beyond FR-AUTHOR-09's mandatory `approved_by` |
| TC-AUTHOR-C05 | CT-AUTHOR-05 data | the report is `<package>.authoring-report.md` beside `<package>.package.draft.toml`, named after the package id the documents state, with the sections Documents → Steps → Items → Unresolved → Next command in that order, and the Steps section states per item the outcome, the winning model, the attempt count and every failure reason |

Heading formatting is deliberately not pinned (the design pins the sections, not their markup):
the order check is a word-subsequence scan, and the per-item check is substring presence of
the module's own outcome fields. If the landing renders either differently, the reconciliation
happens here — one file — not in five consumer suites.

Rung 1, guards first: `aeh.author` (#689), then the corpus (#686). AF-11 states no grade
boundaries (FR-AUTHOR-08's never-invent rule) and AF-06 is the partial-description fixture,
so the placeholder limbs have real material to assert on.
"""

from __future__ import annotations

import re
import tomllib
import pytest

from tests.support.author_vocabulary import (
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    PLACEHOLDER_COMMENT_RE,
    RECORDINGS,
    SENTINEL_RE,
    af,
    chain_from_config,
    make_service,
    placeholder_fields,
)
from tests.support.impl import require, require_attr, require_path

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]


def _guards(make_fixture_provider) -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names
    require_attr(author, "AuthoringInputError", issue=AUTHOR_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, recordings


def _strings(value: object) -> list[str]:
    """Every string reachable in a parsed spec, however nested."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [*(k for k in value if isinstance(k, str)), *_strings(list(value.values()))]
    if isinstance(value, (list, tuple)):
        return [s for item in value for s in _strings(item)]
    return []


# --- TC-AUTHOR-C04 ----------------------------------------------------------------------------


def test_tc_author_c04_the_sentinel_shape_its_reason_and_no_collision_with_legal_values(
        tmp_path, make_fixture_provider):
    """AF-11 (no boundaries stated): the `[grades]` placeholder carries the sentinel value and
    its reason comment; every sentinel is a full-formed field value that no legal TOML value
    can imitate; AF-01 (fully resolved) carries no step-proposed sentinel — only FR-AUTHOR-09's
    mandatory `approved_by` may remain."""
    author, recordings = _guards(make_fixture_provider)
    af11 = require_path(af("AF-11"), "the AF-11 authored fixture", issue=CORPUS_ISSUE)
    af01 = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    service = make_service(author, chain_from_config(), make_fixture_provider(recordings))

    result = service.draft(documents=sorted(af11.glob("*.pdf")), output_dir=tmp_path / "af11")
    text = result.draft_path.read_text(encoding="utf-8")

    fields = SENTINEL_RE.findall(text)
    assert fields, "AF-11 must leave the grade boundaries as a named placeholder"
    assert result.placeholders == len(fields), (
        f"report counts {result.placeholders} placeholders, draft carries {len(fields)}")

    # Each sentinel line has its reason comment on the line above, naming what to supply.
    lines = text.splitlines()
    comments = 0
    for index, line in enumerate(lines):
        if "<<PLACEHOLDER:" in line:
            assert index > 0, f"sentinel on line {index + 1} has no room for its reason comment"
            match = PLACEHOLDER_COMMENT_RE.search(lines[index - 1])
            assert match, f"no `# PLACEHOLDER(<reason>):` comment above: {line!r}"
            assert match.group(1).strip() and match.group(2).strip(), (
                f"empty reason in {lines[index - 1]!r}")
            comments += 1
    assert comments == len(fields), "a reason comment without a sentinel, or vice versa"

    # The sentinel is the field's VALUE, and it cannot collide with any legal value: every
    # string in the parsed spec that contains the marker is exactly one full sentinel.
    spec = tomllib.loads(text)
    for value in _strings(spec):
        if "<<PLACEHOLDER" in value:
            assert SENTINEL_RE.fullmatch(value), (
                f"a legal-looking value imitates the sentinel: {value!r}")

    # The contrast: a fully resolved draft uses the same vocabulary with no STEP-proposed
    # sentinel anywhere. The one placeholder FR-AUTHOR-09 mandates — approved_by, never
    # model-generated — is the only one allowed; #686's expected class decides whether AF-01
    # counts it, and the suite accepts exactly that one or none at all.
    happy = service.draft(documents=sorted(af01.glob("*.pdf")), output_dir=tmp_path / "af01")
    happy_text = happy.draft_path.read_text(encoding="utf-8")
    happy_fields = placeholder_fields(happy_text)
    assert happy.placeholders == len(happy_fields)
    assert set(happy_fields) <= {"approved_by"}, (
        f"AF-01 is fully resolved: only approved_by may be a placeholder, got {happy_fields}")


# --- TC-AUTHOR-C05 ----------------------------------------------------------------------------


def test_tc_author_c05_report_named_for_the_package_with_sections_in_order_and_per_item_detail(
        tmp_path, make_fixture_provider):
    """AF-06 (one criterion placeholder): the two artifacts are named after the package id and
    sit beside each other; the five sections appear in order; the Steps section carries each
    outcome's item, winning model, attempts and failure reasons; the Unresolved section names
    the placeholder."""
    author, recordings = _guards(make_fixture_provider)
    af06 = require_path(af("AF-06"), "the AF-06 authored fixture", issue=CORPUS_ISSUE)
    service = make_service(author, chain_from_config(), make_fixture_provider(recordings))

    result = service.draft(documents=sorted(af06.glob("*.pdf")), output_dir=tmp_path / "out")
    spec = tomllib.loads(result.draft_path.read_text(encoding="utf-8"))
    package_id = spec["package"]

    assert result.draft_path.name == f"{package_id}.package.draft.toml"
    assert result.report_path.name == f"{package_id}.authoring-report.md"
    assert result.report_path.parent == result.draft_path.parent

    report = result.report_path.read_text(encoding="utf-8")
    # Section order, as a word subsequence — markup unpinned, order pinned.
    cursor = 0
    positions = {}
    for section in ("Documents", "Steps", "Items", "Unresolved", "Next command"):
        match = re.search(rf"\b{re.escape(section)}\b", report[cursor:], flags=re.IGNORECASE)
        assert match, f"the report has no {section!r} section"
        positions[section] = cursor + match.start()
        cursor += match.end()
    ordered = [positions[name] for name in
               ("Documents", "Steps", "Items", "Unresolved", "Next command")]

    # Per-item detail in the Steps section: item, model, attempt count, failure reasons.
    steps_text = report[positions["Steps"]:positions["Items"]]
    assert re.search(r"\battempts?\b", steps_text, flags=re.IGNORECASE), (
        "the Steps section states no attempt count")
    for outcome in result.outcomes:
        assert outcome.item_id in steps_text, f"{outcome.item_id} missing from Steps"
        if outcome.model:
            assert outcome.model in steps_text, (
                f"{outcome.item_id}: winning model {outcome.model} missing from Steps")
        for reason in outcome.failures:
            assert reason in steps_text, (
                f"{outcome.item_id}: failure reason {reason!r} missing from Steps")

    # The Unresolved section names every placeholder field the draft carries.
    unresolved_text = report[positions["Unresolved"]:positions["Next command"]]
    draft_text = result.draft_path.read_text(encoding="utf-8")
    for field in placeholder_fields(draft_text):
        assert field in unresolved_text, f"placeholder {field} not listed in Unresolved"