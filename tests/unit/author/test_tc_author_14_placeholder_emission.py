"""`TC-AUTHOR-14` (FR-AUTHOR-11, CT-AUTHOR-04, FR-PKG-27, P0) — placeholder emission across
AF-06/07/08/09/11 (#710, the package-authoring test plan §5.1; design delta §3.1).

Written ahead of #693: `aeh.author` does not exist yet, so every case is red until the
emission half lands. The file carries `writtenahead`, keyed `#693 validation gate` (the
same registry entry as TC-AUTHOR-13's file — #693 is one story, and `validate_draft` is
its §3.1-named gate; see that entry's comment block in `tests/support/impl.py` for the
choice, the residual early-fire risk and the rename path). When #693 closes the marker
comes off — never the test.

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
  equals the parsed field count (CT-AUTHOR-05's report names item ids that are the
  sentinel fields; the count is what the review walk's completeness reads).

The build-refusal half of AF-09/AF-11 (`expected.toml`'s `build = "refused"`) is not
re-asserted here: the sentinel-refusal differential is `TC-PKG-C23`'s clause suite (the
sentinel gate precedes every other check, #688) and the validator differential is
TC-AUTHOR-13's. This file holds what only the emitting module can lie about: the shape,
the reason comments and the counts.
"""

from __future__ import annotations

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

pytestmark = [pytest.mark.writtenahead]

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
    expected = tomllib.loads(
        (af(af_id) / "expected.toml").read_text(encoding="utf-8"))["placeholders"]
    assert set(fields) == set(expected), (
        f"{af_id}: the sentinel fields {sorted(set(fields))} are not the fixture's declared "
        f"placeholders {sorted(set(expected))}")

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

    occurrences = len(SENTINEL_RE.findall(draft_text))
    assert result.placeholders == occurrences == len(fields), (
        f"{af_id}: the counts disagree — DraftResult.placeholders={result.placeholders}, "
        f"sentinel occurrences={occurrences}, fields={len(fields)}")

    network_guard.assert_no_network()