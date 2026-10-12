"""`TC-AUTHOR-14` (FR-AUTHOR-11, CT-AUTHOR-04, FR-PKG-27, P0) — placeholder emission across
AF-06/07/08/09/11 (#710, the package-authoring test plan §5.1; design delta §3.1).

Landed (#690): `aeh.author` exists and the emission half runs green over the captured
recordings — the `writtenahead` marker came off (keyed `#693 validation gate`, the same
registry entry as TC-AUTHOR-13's file; the entry is dropped, the tests kept).

Rung 1 (headless in-process), the plan's isolation per case: the recorded provider over
the F-AUTHOR recordings (`CT-PROV-10`) and the autouse socket guard, asserted zero-egress
at the end of every case — no live calls in this suite. The recorded runs need nothing
`validate_draft` itself provides, but #693 is the story that ships the emission, so the
registry keys the file on that gate (the corpus and surface limbs land strictly earlier).

The oracle, exactly per case:

- **The draft parses** (`tomllib.loads` succeeds) — the sentinel is deliberately outside
  every legal value of every field it can occupy (CT-AUTHOR-04), so a sentinel that broke
  TOML grammar would be a sentinel inside a legal domain, and the parse is the proof it
  never is;
- **every sentinel line carries its reason comment on the line above** — the strict
  reading of FR-AUTHOR-11/CT-AUTHOR-04 ("on the line above"; "every sentinel line
  carries"). Disclosed: if #693 renders one comment above a *row* that carries two
  sentinels, the reconcile is this loop plus one line in the design note — the reason
  still names what the teacher must supply either way;
- **the sentinel fields are exactly the fixture's declared placeholders** — disclosed
  assumption: `expected.toml`'s `placeholders` entries are the sentinel `<field>` values
  verbatim, as a set of field names (AF-08's "key" names two occurrences — items 3 and 5 —
  with one field). If #693 names the fields differently, the reconcile is this assertion
  plus one `expected.toml` edit at the corpus's owner (#686/#693);
- **the counts match** — `DraftResult.placeholders` equals the sentinel occurrence count
  plus the report-only omissions, and equals the parsed field count plus those omissions
  (CT-AUTHOR-05's report names item ids that are the sentinel fields; the count is what
  the review walk's completeness reads). Disclosed reconcile (the landing): the count is
  the review walk's completeness denominator, so it also carries the *named omissions* —
  fields the module could not determine that have no sentinel in the draft (`AF-08`'s
  five questions state no marks, so each carries a report-only `points <qid>` omission);
  the reconcile reads the report's Unresolved section for those entries.

The build-refusal half of AF-09/AF-11 (`expected.toml`'s `build = "refused"`) is not
re-asserted here: the sentinel-refusal differential is `TC-PKG-C23`'s clause suite (the
sentinel gate precedes every other check, #688) and the validator differential is
TC-AUTHOR-13's. This file holds what only the emitting module can lie about: the shape,
the reason comments and the counts.
"""

from __future__ import annotations

import re
import tomllib

import pytest

from tests.support.author_vocabulary import (
    AUTHOR_MODULE,
    CORPUS_ISSUE,
    PLACEHOLDER_COMMENT_RE,
    RECORDINGS,
    SENTINEL_RE,
    af,
    chain_from_config,
    make_service,
    placeholder_fields,
)
from tests.support.impl import require, require_path

#: The five fixtures the TC row names, in the row's order.
PLACEHOLDER_FIXTURES = ("AF-06", "AF-07", "AF-08", "AF-09", "AF-11")


def _guards(af_id: str, make_fixture_provider) -> tuple:
    """The require-style gates, and the first thing each case body does: a missing
    implementation is `NotImplementedYet` naming the blocker — never a collection error.
    The names the case constructs through are the §3.1 surface's draft half; the corpus
    guards name #686, the corpus story, so the red names the right blocker at each layer."""
    author = require(AUTHOR_MODULE, issue="#693")  # the module itself
    require(AUTHOR_MODULE, "AuthoringService", "AuthoringSettings", issue="#693")  # draft half
    corpus = require_path(af(af_id), f"the {af_id} authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, corpus, make_fixture_provider(recordings)


@pytest.mark.parametrize("af_id", PLACEHOLDER_FIXTURES)
def test_tc_author_14_placeholders_are_emitted_outside_every_legal_toml_domain(
        af_id, tmp_path, make_fixture_provider, network_guard):
    """Recorded draft run: the draft parses, every sentinel line carries its reason comment
    on the line above, the sentinel fields are exactly the fixture's declared placeholders,
    and the counts match `DraftResult.placeholders`."""
    author, corpus, provider = _guards(af_id, make_fixture_provider)
    service = make_service(author, chain_from_config(), provider)

    result = service.draft(documents=sorted(corpus.glob("*.pdf")), output_dir=tmp_path / "out")
    draft_text = result.draft_path.read_text(encoding="utf-8")

    # Outside every legal TOML domain: the sentinel never breaks the grammar it sits in.
    parsed = tomllib.loads(draft_text)  # a broken draft fails here, before any oracle below
    assert parsed.get("package"), f"{af_id}: the draft is not a package spec"

    fields = placeholder_fields(draft_text)
    assert fields, f"{af_id}: the draft carries no sentinel"
    # Disclosed reconcile (the landing): `approved_by` rides on top of every outcome class
    # (TC-AUTHOR-12) and is never counted (TC-AUTHOR-01 pins AF-01 at zero), so the oracle
    # reads the *content* sentinels — the riding approval sentinel is excluded here, once.
    content_fields = [field for field in fields if field != "approved_by"]
    expected = tomllib.loads(
        (af(af_id) / "expected.toml").read_text(encoding="utf-8"))["placeholders"]
    assert set(content_fields) == set(expected), (
        f"{af_id}: the sentinel fields {sorted(set(content_fields))} are not the fixture's "
        f"declared placeholders {sorted(set(expected))}")

    lines = draft_text.splitlines()
    for index, line in enumerate(lines):
        if not SENTINEL_RE.search(line):
            continue
        assert index > 0, f"{af_id}: a sentinel on the draft's first line"
        comment = PLACEHOLDER_COMMENT_RE.search(lines[index - 1])
        assert comment, (
            f"{af_id}: the sentinel line {index + 1} has no `# PLACEHOLDER(<reason>):` "
            f"comment on the line above: {lines[index - 1]!r}")
        assert comment.group(1).strip(), (
            f"{af_id}: the reason comment above line {index + 1} carries no reason")

    occurrences = len([field for field in SENTINEL_RE.findall(draft_text)
                       if field != "approved_by"])
    # Disclosed reconcile (the landing): `DraftResult.placeholders` is the review walk's
    # completeness denominator — sentinel occurrences plus the report-only omissions (a
    # field the module could not determine that carries no sentinel in the draft, AF-08's
    # unstated marks). The report's Unresolved section names every named gap; an entry is
    # an omission when the sentinel it names is not a value anywhere in the draft — the
    # report quotes each gap's sentinel name (`<<PLACEHOLDER: points Q1>>` for a field the
    # draft carries no sentinel for), so the line's own token is not the discriminator; the
    # draft's sentinel set is.
    draft_sentinels = set(SENTINEL_RE.findall(draft_text))
    # Disclosed reconcile (the landing): the Unresolved section also lists the run's
    # non-converged outcome rows (`- <item id> — the reasoning did not converge: ...`,
    # TC-AUTHOR-08's flagged-first rule) — entries that name no sentinel and are not
    # named omissions either; their ids come from `result.outcomes`, and the omission
    # count skips them by the entry's leading item id.
    unresolved_rows = {outcome.item_id for outcome in result.outcomes
                       if outcome.status == "unresolved"}
    report = result.report_path.read_text(encoding="utf-8")
    match = re.search(r"^#+\s*Unresolved\b[^\n]*\n", report, re.M)
    omissions = 0
    if match is not None:
        rest = report[match.end():]
        end = re.search(r"^#+\s", rest, re.M)
        section = rest[:end.start()] if end else rest
        omissions = len([line for line in section.splitlines()
                         if line.strip().startswith("- ")
                         and line.strip()[2:].split()[0] not in unresolved_rows
                         and (SENTINEL_RE.search(line) is None
                              or SENTINEL_RE.search(line).group(1) not in draft_sentinels)])
    assert result.placeholders == occurrences + omissions == len(content_fields) + omissions, (
        f"{af_id}: the counts disagree — DraftResult.placeholders={result.placeholders}, "
        f"sentinel occurrences={occurrences}, report-only omissions={omissions}, "
        f"fields={len(content_fields)}")

    network_guard.assert_no_network()