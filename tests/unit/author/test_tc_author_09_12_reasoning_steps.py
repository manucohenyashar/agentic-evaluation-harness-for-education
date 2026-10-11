"""`TC-AUTHOR-09…12` (FR-AUTHOR-06/07/08/09, P0) — the reasoning steps (TS-157, #709).

The four rung-1 cases over `#692`'s three reasoning steps — inventory (FR-AUTHOR-06),
rubric mapping (FR-AUTHOR-07), grades (FR-AUTHOR-08) — and the `approved_by` placeholder
(FR-AUTHOR-09), each driving one recorded replay draft per fixture through
`AuthoringService.draft` with `RecordedFixtureProvider` over the #686 corpus recordings
(`author_vocabulary.chain_from_config()` is the corpus coupling: the request key hashes the
assembled prompt, build id included). The oracles, in the plan's order (§5.1 rows 09–12):

- **09** paper order preserved (each question's text occurs in the extracted paper text at
  strictly increasing offsets, and the question count equals the paper's own `QUESTION n`
  header count); the full FR-AUTHOR-06 field set (`id`, `type`, `points`, `text`,
  `model_answer`, `options` iff mcq) present per question with no sentinel in any question
  field; and **exactly one inventory call per document set** — discriminated by
  `AUTHOR_INVENTORY_TEMPLATE_V`'s value in the assembled request payload. The semantics
  pinned here for #692's implementer: the pin rides its **own step's** requests (the
  step-scoped reading of FR-AUTHOR-20 — NFR-AUTHOR-06 ties each constant to its step
  file), not every request carrying every pin; if the implementation rides all three pins
  on every request, the count oracle fails and the reconciliation is this discriminator —
  one call for AF-01's four questions and still one call for AF-02's two-document set.
- **10** the rubric matrix: AF-03's mcq lines keyed from the question's declared options;
  AF-04's general criterion carrying `derivation_description` **byte-verbatim from the
  recorded reply** (compared at the provider boundary against the reply text itself, with
  the one escape-decoded variant a TOML/JSON string literal would force — a paraphrase
  changes letters, not escapes) with bands derived from the prose (even 2–6, worst first,
  non-decreasing points); AF-05's evidence_sum composite with binary two-band aspects
  naming it in `component_of`; AF-12's mixed mcq and judged lines, all resolved; every
  question covered by at least one criterion; **weighted scores never proposed** (every
  criterion is one of FR-AUTHOR-07's supported shapes — no weight field, no unsupported
  shape) and **dependency-implying prose never an edge** (no criterion carries a
  dependency field in any draft this suite drafts — design §3.1: authoring emits none);
  AF-09, the corpus's own unmappable-description fixture, resolves to its declared
  placeholders as unresolved notes in the report's Unresolved section.
- **11** the grades table: AF-01's stated ranges derive exactly
  (`A: 14-16. B: 10-13. C: 6-9. D: 0-5.` out of 16 → `{A: 14, B: 10, C: 6, D: 0}` — the
  package vocabulary's `[grades]` carries the lowest total that earns each grade, the ps9
  spec's own convention) with no sentinel; AF-11's unstated boundaries become the
  whole-table `<<PLACEHOLDER: grades>>` sentinel with its reason comment and **no boundary
  number anywhere in the draft** — never invented.
- **12** `approved_by` is the sentinel `<<PLACEHOLDER: approved_by>>` with its
  `# PLACEHOLDER(<reason>):` comment on the line above, in **every** one of the thirteen
  fixtures' drafts — never model-generated, even in AF-04 where the description speaks in
  the teacher's own voice ("MY OWN WORDS - FOR WHOEVER COVERS MY LESSONS" names no one and
  must not become a name); the teacher supplies it at review. The `expected.toml`
  `placeholders` lists count *content* placeholders; `approved_by` rides on top of every
  outcome class, which is why a "resolved" fixture's draft still carries exactly one
  sentinel — `approved_by`.

Disclosed fixture assumptions, to reconcile at the landing — the assertions stay the plan's:

- **AF-02's document order** is `expected.toml`'s `documents` list (the corpus README's
  hand-in order: test paper first, marking memo second). The recordings are keyed on the
  assembled request, document order included; if #690's capture pass sorts the paths
  instead, the reconciliation is `_documents` here and nowhere else.
- **TC-AUTHOR-11's partial-table arm (Q-O8's adopted default — stated rows derived,
  sentinel per missing row)**: no corpus fixture states *some but not all* boundaries, and
  no recording can replay a request the capture pass never made, so the middle arm is
  written ahead of a corpus input that can drive it. Both poles of the never-invent rule
  are pinned here on real fixtures — AF-01 (all stated → all derived, nothing sentineled)
  and AF-11 (nothing stated → whole-table placeholder, no numbers) — and a
  partial-boundaries fixture (or an AF-01-variant recording set, the
  `recordings-af01-variant` slot) extends this case to the middle arm without rewriting
  it. Reported as a deviation in the PR.
- **TC-AUTHOR-10's dependency-prose variant**: no corpus fixture carries prose implying a
  criterion dependency, so the arm is pinned mechanically — no criterion in any draft this
  suite drafts carries a dependency field (the never-an-edge half) — and the
  unresolved-note mechanism is pinned on AF-09, the corpus's own description the reasoning
  cannot map (its contradictory grading description resolves to unresolved notes, not to a
  rewritten rule). A fixture carrying genuine dependency prose extends this case to the
  variant's input half.
- **TC-AUTHOR-10's weighted-scores variant** (the row's first variant): no corpus fixture
  carries weighted-scores wording either, so its prohibition half is pinned mechanically —
  no criterion carries a weight-like field and every criterion is one of FR-AUTHOR-07's
  supported shapes (an unsupported shape would be the weighted proposal in disguise). A
  fixture carrying weighted-scores wording extends this case to the variant's input half.

Written ahead of #692 ("reasoning steps: inventory, rubric, grades, approved_by"), keyed
`#692 reasoning steps` in `WRITTEN_AHEAD_BLOCKERS` — a `command` probe; see the registry
comment for why the issue's prescribed `symbol` key on `aeh.author:AuthoringService` fires
two stories early (#690 ships the class), and re-check all four cases green before
unmarking — never on the notice alone.

Rung 1, guards first (#689's module surface, then #686's corpus and capture index).
"""

from __future__ import annotations

import re
import tomllib

import pytest

from tests.support.author_vocabulary import (
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    PLACEHOLDER_COMMENT_RE,
    RECORDINGS,
    SENTINEL_RE,
    CountingProvider,
    af,
    chain_from_config,
    make_service,
    placeholder_fields,
)
from tests.support.impl import require, require_path

pytestmark = [pytest.mark.writtenahead]

#: The registry key this file is blocked on (the issue's own note, kept as the key).
STEPS_ISSUE = "#692 reasoning steps"
#: FR-AUTHOR-20's prompt pins — NFR-AUTHOR-06 lands each step file with its own constant,
#: so these are #692's to ship (TC-AUTHOR-20 asserts the ride and the bump).
STEP_PROMPT_PINS = (
    "AUTHOR_INVENTORY_TEMPLATE_V",
    "AUTHOR_RUBRIC_TEMPLATE_V",
    "AUTHOR_GRADES_TEMPLATE_V",
)

#: The paper's question headers, anchored to a line start so a prose mention ("answer
#: question 1.") does not count — a corpus edit adding one would otherwise false-fail the
#: count oracle. If the extraction flattens the headers off their own lines, this is the line.
_QUESTION_HEADER_RE = re.compile(r"^\s*QUESTION\s+\d+", re.IGNORECASE | re.MULTILINE)
_QUESTION_FIELDS = ("id", "type", "points", "text", "model_answer")
_SUPPORTED_SHAPES = frozenset(
    {"mcq key", "evidence_sum composite", "aspect", "general", "bands"}
)
#: The dependency-edge spellings a criterion row must never carry (design §3.1: "authoring
#: emits none"; `component_of` is the composite link, not a dependency, and is not here).
_DEPENDENCY_FIELDS = frozenset({"depends_on", "dependencies", "requires"})


# --- guards and shared draft helpers ---------------------------------------------------------


def _guards(af_ids):
    """The §3.1 surface plus the step pins (#692's), then the corpus and its capture index."""
    author = require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=STEPS_ISSUE)
    require(AUTHOR_MODULE, *STEP_PROMPT_PINS, issue=STEPS_ISSUE)
    for af_id in af_ids:
        require_path(af(af_id), f"the {af_id} authored fixture", issue=CORPUS_ISSUE)
    require_path(
        RECORDINGS / "coverage.json",
        "the authoring recordings capture index",
        issue=CORPUS_ISSUE,
    )
    return author


def _expected(af_id):
    return tomllib.loads((af(af_id) / "expected.toml").read_text(encoding="utf-8"))


def _documents(af_id):
    """The fixture's documents in `expected.toml`'s declared order — the corpus README's
    hand-in order (see the module docstring's disclosed assumption)."""
    return [af(af_id) / name for name in _expected(af_id)["documents"]]


def _draft(author, make_fixture_provider, af_id, output_dir):
    """One recorded replay draft over the fixture's documents, with the replies kept."""
    counted = _ReplyRecorder(make_fixture_provider(RECORDINGS))
    result = make_service(author, chain_from_config(), counted).draft(
        documents=_documents(af_id), output_dir=output_dir
    )
    return result, counted


def _draft_toml(result):
    raw = result.draft_path.read_text(encoding="utf-8")
    return tomllib.loads(raw), raw


def _paper_text(documents):
    from pypdf import PdfReader

    return "\n".join(
        "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
        for path in documents
    )


def _norm(text):
    return re.sub(r"\s+", " ", text).casefold().strip()


def _payload_text(prompt):
    """The assembled request text: `PromptPayload.fields` is an ordered (name, value)
    sequence (CT-PROV-05), and the pins ride the joined values (TC-AUTHOR-20's precedent)."""
    return "\n".join(value for _name, value in prompt.fields)


def _no_sentinel(value):
    if isinstance(value, str):
        return SENTINEL_RE.search(value) is None
    if isinstance(value, dict):
        return all(_no_sentinel(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(_no_sentinel(v) for v in value)
    return True


def _unresolved_fields(report_text):
    """The `<field>` of every sentinel the report's Unresolved section names, in review
    order — a local copy of `author_vocabulary.unresolved_fields`, whose section-shape
    assumption is disclosed there (CT-AUTHOR-05's section set, FR-AUTHOR-16's review
    order). The shared helper lands with the review-walk pair's vocabulary work, which is
    not on `main` yet; until it does this file carries its own copy so the designed red is
    a `require()` failure, not an import error. The reconciliation, if the shared helper
    moves, is this one function."""
    match = re.search(r"^#+\s*Unresolved\b[^\n]*\n", report_text, re.M)
    if match is None:
        return []
    rest = report_text[match.end():]
    end = re.search(r"^#+\s", rest, re.M)
    section = rest[: end.start()] if end else rest
    return SENTINEL_RE.findall(section)


class _ReplyRecorder(CountingProvider):
    """`CountingProvider` plus the raw completion text of every call.

    TC-AUTHOR-10's byte-verbatim oracle compares the draft's `derivation_description`
    against the recorded replies themselves — captured here at the provider boundary, not
    re-read from the recording files, so the comparison is against what the model actually
    returned. Delegation stays through the wrapped provider, the only egress point
    (`CT-PROV-15`).
    """

    def __init__(self, inner) -> None:
        super().__init__(inner)
        self.reply_texts: list[str] = []

    def complete(self, prompt, model_ref, params):
        completion = super().complete(prompt, model_ref, params)
        self.reply_texts.append(getattr(completion, "text", None) or str(completion))
        return completion


# --- TC-AUTHOR-09 ----------------------------------------------------------------------------


def _check_inventory_fields(af_id, questions, paper):
    """FR-AUTHOR-06's field set per question, paper order preserved, no sentinel in a
    resolved fixture's inventory."""
    norm_paper = _norm(paper)
    positions = []
    for index, question in enumerate(questions):
        for field in _QUESTION_FIELDS:
            assert question.get(field) is not None, (
                f"TC-AUTHOR-09 ({af_id}): question {index} carries no {field!r} — "
                "FR-AUTHOR-06's inventory field set is incomplete"
            )
        assert question["type"] in ("mcq", "open"), (
            f"TC-AUTHOR-09 ({af_id}): question {index} has type {question['type']!r} — "
            "the inventory types are mcq or open (FR-AUTHOR-06)"
        )
        assert isinstance(question["points"], int) and question["points"] > 0, (
            f"TC-AUTHOR-09 ({af_id}): question {index} carries points "
            f"{question['points']!r} — a positive integer from the paper's marks"
        )
        for field in ("id", "text", "model_answer"):
            assert str(question[field]).strip(), (
                f"TC-AUTHOR-09 ({af_id}): question {index}'s {field!r} is blank"
            )
        assert ("options" in question) == (question["type"] == "mcq"), (
            f"TC-AUTHOR-09 ({af_id}): question {index} — options ride mcq questions only "
            "(FR-AUTHOR-06), and an mcq question without options cannot take a key"
        )
        assert _no_sentinel(question), (
            f"TC-AUTHOR-09 ({af_id}): question {index} carries a sentinel but the "
            "fixture's outcome class is resolved — FR-AUTHOR-11 forbids a silent "
            "undetermined field and this inventory must be complete"
        )
        position = norm_paper.find(_norm(question["text"]))
        assert position >= 0, (
            f"TC-AUTHOR-09 ({af_id}): question {index}'s text does not appear in the "
            "paper's extracted text — the inventory carries the paper's question text"
        )
        positions.append(position)
    assert positions == sorted(positions) and len(set(positions)) == len(positions), (
        f"TC-AUTHOR-09 ({af_id}): the draft's questions are not in paper order — the "
        f"offsets of their texts in the paper are {positions} (FR-AUTHOR-06: paper order)"
    )


def test_tc_author_09_the_inventory_step_preserves_paper_order_with_the_full_field_set(
        tmp_path, make_fixture_provider):
    """AF-01 and the two-document variant AF-02: paper order, full field set, and exactly
    one inventory call per document set — not per document, not per question."""
    author = _guards(("AF-01", "AF-02"))
    inventory_pin = str(getattr(author, "AUTHOR_INVENTORY_TEMPLATE_V"))

    # --- AF-01, single document: four questions in paper order ------------------------------
    result, counted = _draft(author, make_fixture_provider, "AF-01", tmp_path / "af01")
    draft, _raw = _draft_toml(result)
    questions = draft.get("question") or []
    paper = _paper_text(_documents("AF-01"))
    assert len(questions) == len(_QUESTION_HEADER_RE.findall(paper)), (
        "TC-AUTHOR-09 (AF-01): the draft's question count does not match the paper's "
        "own QUESTION headers — the inventory proposes every question, in paper order"
    )
    _check_inventory_fields("AF-01", questions, paper)
    inventory_outcomes = [o for o in result.outcomes if o.step == "inventory"]
    assert len(inventory_outcomes) == len(questions), (
        "TC-AUTHOR-09 (AF-01): the inventory step recorded an outcome per question — one "
        "StepOutcome per item (CT-AUTHOR-03)"
    )
    assert all(o.status == "resolved" for o in inventory_outcomes), (
        "TC-AUTHOR-09 (AF-01): a resolved fixture's inventory items all resolve — the "
        "outcome class is resolved with zero content placeholders"
    )
    inventory_calls = [c for c in counted.calls if inventory_pin in _payload_text(c[0])]
    assert len(inventory_calls) == 1, (
        f"TC-AUTHOR-09 (AF-01): the inventory step made {len(inventory_calls)} calls — "
        "exactly one call per document set, not per question (FR-AUTHOR-06)"
    )

    # --- AF-02, the two-document variant: still one inventory call ---------------------------
    result, counted = _draft(author, make_fixture_provider, "AF-02", tmp_path / "af02")
    draft, _raw = _draft_toml(result)
    questions = draft.get("question") or []
    texts = {path.name: _paper_text([path]) for path in _documents("AF-02")}
    papers = [name for name, text in texts.items() if _QUESTION_HEADER_RE.search(text)]
    assert len(papers) == 1, (
        "TC-AUTHOR-09 (AF-02): disclosed fixture assumption — exactly one of AF-02's two "
        "documents carries the QUESTION headers (the test paper); if the corpus changes, "
        "this is the line that reconciles"
    )
    paper = texts[papers[0]]
    assert len(questions) == len(_QUESTION_HEADER_RE.findall(paper)), (
        "TC-AUTHOR-09 (AF-02): the draft's question count does not match the test paper's "
        "QUESTION headers — the memo carries the grading, not extra questions"
    )
    _check_inventory_fields("AF-02", questions, paper)
    inventory_outcomes = [o for o in result.outcomes if o.step == "inventory"]
    assert len(inventory_outcomes) == len(questions) and all(
        o.status == "resolved" for o in inventory_outcomes
    ), (
        "TC-AUTHOR-09 (AF-02): the two-document set's inventory items all resolve, one "
        "StepOutcome per question"
    )
    inventory_calls = [c for c in counted.calls if inventory_pin in _payload_text(c[0])]
    assert len(inventory_calls) == 1, (
        f"TC-AUTHOR-09 (AF-02): the two-document set made {len(inventory_calls)} inventory "
        "calls — one call per document set (two documents, three questions, still one "
        "call; FR-AUTHOR-06's variant limb)"
    )


# --- TC-AUTHOR-10 ----------------------------------------------------------------------------


def _shapes(criterion):
    """Which of FR-AUTHOR-07's supported shapes a criterion row carries. A row may carry
    `bands` alongside `general` (the prose kept verbatim with bands derived from it); a
    truthy `component_of` is the aspect link (a standalone row's is absent or empty)."""
    shapes = set()
    if "key" in criterion:
        shapes.add("mcq key")
    if criterion.get("score_method") == "evidence_sum":
        shapes.add("evidence_sum composite")
    if criterion.get("component_of"):
        shapes.add("aspect")
    if criterion.get("score_method") == "general":
        shapes.add("general")
    if "bands" in criterion or criterion.get("score_method") == "bands":
        shapes.add("bands")
    return shapes


def _check_no_edges_or_weights(af_id, criteria):
    """The two prohibitions, mechanical over every drafted criterion: weighted scores are
    never proposed, and dependency-implying prose never becomes an edge."""
    for index, criterion in enumerate(criteria):
        shapes = _shapes(criterion)
        assert shapes and shapes <= _SUPPORTED_SHAPES, (
            f"TC-AUTHOR-10 ({af_id}): criterion {index} carries shapes "
            f"{sorted(shapes)} — every criterion maps onto exactly one of FR-AUTHOR-07's "
            "supported shapes (mcq key, evidence_sum composite with binary aspects, bands, "
            "general); a weighted-scores description is refused, never proposed"
        )
        edges = _DEPENDENCY_FIELDS & set(criterion)
        assert not edges, (
            f"TC-AUTHOR-10 ({af_id}): criterion {index} carries dependency field(s) "
            f"{sorted(edges)} — dependency-implying prose is recorded as an unresolved "
            "note, never as a criterion edge (design §3.1: authoring emits none)"
        )
        assert not any("weight" in str(key).casefold() for key in criterion), (
            f"TC-AUTHOR-10 ({af_id}): criterion {index} carries a weight-like field — "
            "weighted scores are never proposed (FR-AUTHOR-07)"
        )


def _escape_variants(text):
    """The draft's decoded value, and the forms a TOML/JSON string literal in the reply
    would have forced: the `\\`-escaped form and the `\\uXXXX`-escaped form (AF-04's prose
    carries a right single quote a JSON literal could encode as `\\u2019`). A paraphrase
    changes letters, not escapes."""
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    unicode_escaped = re.sub(
        r"[^\x00-\x7f]", lambda m: "\\u%04x" % ord(m.group(0)), text
    )
    variants = {text, escaped, unicode_escaped}
    return {v for v in variants if v}


def test_tc_author_10_the_rubric_step_maps_onto_exactly_one_supported_shape(
        tmp_path, make_fixture_provider):
    """The matrix (AF-03 mcq key, AF-04 general verbatim, AF-05 evidence_sum, AF-12 mixed),
    the two prohibitions, and AF-09's unresolved notes — never an edge, never a weighted
    shape, never a re-worded derivation."""
    author = _guards(("AF-03", "AF-04", "AF-05", "AF-09", "AF-12"))
    drafts = {}
    replies = {}
    for af_id in ("AF-03", "AF-04", "AF-05", "AF-12"):
        result, counted = _draft(
            author, make_fixture_provider, af_id, tmp_path / af_id.casefold().replace("-", "")
        )
        replies[af_id] = counted.reply_texts
        draft, _raw = _draft_toml(result)
        criteria = draft.get("criterion") or []
        questions = draft.get("question") or []
        assert criteria, f"TC-AUTHOR-10 ({af_id}): the draft proposes no criteria"
        assert questions, (
            f"TC-AUTHOR-10 ({af_id}): the draft proposes no questions — an empty inventory "
            "would make the coverage and shape arms below vacuous instead of red"
        )
        _check_no_edges_or_weights(af_id, criteria)
        mapped = {c.get("question") for c in criteria if c.get("question")}
        question_ids = {q["id"] for q in questions}
        assert question_ids <= mapped, (
            f"TC-AUTHOR-10 ({af_id}): question(s) {sorted(question_ids - mapped)} carry no "
            "criterion — every question maps onto exactly one supported shape "
            "(FR-AUTHOR-07)"
        )
        drafts[af_id] = (draft, questions, criteria)

    # AF-03 — the mcq answer key, drawn from the question's declared options.
    draft, questions, criteria = drafts["AF-03"]
    for question in questions:
        assert question["type"] == "mcq", (
            f"TC-AUTHOR-10 (AF-03): question {question['id']!r} is {question['type']!r} — "
            "the mcq fixture's lines are all mcq"
        )
        keyed = [c for c in criteria if c.get("question") == question["id"] and "key" in c]
        assert keyed, (
            f"TC-AUTHOR-10 (AF-03): question {question['id']!r} carries no keyed criterion "
            "— the paper states the answer key, so the mcq shape is the mapping"
        )
        for criterion in keyed:
            assert criterion["key"] in question["options"], (
                f"TC-AUTHOR-10 (AF-03): criterion {criterion.get('id')!r} keys "
                f"{criterion['key']!r}, which is not one of question "
                f"{question['id']!r}'s declared options — the key is drawn from the "
                "declared options (FR-AUTHOR-07)"
            )

    # AF-04 — the general criterion: prose byte-verbatim from the reply, bands derived.
    draft, questions, criteria = drafts["AF-04"]
    generals = [c for c in criteria if "general" in _shapes(c)]
    assert len(generals) == 1, (
        f"TC-AUTHOR-10 (AF-04): {len(generals)} general criteria — the single open "
        "question maps to exactly one general criterion (FR-AUTHOR-07)"
    )
    description = generals[0].get("derivation_description")
    assert description and str(description).strip(), (
        "TC-AUTHOR-10 (AF-04): the general criterion carries no derivation_description — "
        "the teacher's prose kept verbatim (FR-AUTHOR-07)"
    )
    description = str(description)
    assert any(
        variant in reply
        for reply in replies["AF-04"]
        for variant in _escape_variants(description)
    ), (
        f"TC-AUTHOR-10 (AF-04): the draft's derivation_description {description!r} appears "
        "in no recorded reply byte-for-byte — the general criterion's prose is the "
        "teacher's own words kept verbatim from the reply (FR-AUTHOR-07), never re-worded; "
        "the escape-decoded variant only covers a reply that carried it inside a string "
        "literal"
    )
    bands = generals[0].get("bands") or []
    assert 2 <= len(bands) <= 6 and len(bands) % 2 == 0, (
        f"TC-AUTHOR-10 (AF-04): {len(bands)} bands — an even number, 2 to 6 "
        "(FR-AUTHOR-07's bands shape, derived from the stated scale)"
    )
    points = [band.get("points") for band in bands]
    assert all(isinstance(point, int) for point in points), (
        f"TC-AUTHOR-10 (AF-04): band points {points!r} are not integers"
    )
    assert points == sorted(points), (
        f"TC-AUTHOR-10 (AF-04): band points {points} are not non-decreasing — bands are "
        "worst first (FR-AUTHOR-07)"
    )

    # AF-05 — the evidence_sum composite with binary aspect criteria.
    draft, questions, criteria = drafts["AF-05"]
    for question in questions:
        composites = [
            c
            for c in criteria
            if c.get("question") == question["id"] and "evidence_sum composite" in _shapes(c)
        ]
        assert len(composites) == 1, (
            f"TC-AUTHOR-10 (AF-05): question {question['id']!r} maps to "
            f"{len(composites)} evidence_sum composites — the checklist wording ('Award 1 "
            "point if…', 'the score is the points added up; there are no bands') is the "
            "evidence_sum shape, one composite per question (FR-AUTHOR-07)"
        )
        aspects = [c for c in criteria if c.get("component_of") == composites[0].get("id")]
        assert aspects, (
            f"TC-AUTHOR-10 (AF-05): composite {composites[0].get('id')!r} has no aspects — "
            "an evidence_sum composite is binary aspect criteria naming it in "
            "component_of (FR-AUTHOR-07)"
        )
        for aspect in aspects:
            assert {"aspect", "bands"} <= _shapes(aspect), (
                f"TC-AUTHOR-10 (AF-05): aspect {aspect.get('id')!r} carries shapes "
                f"{sorted(_shapes(aspect))} — an aspect is a two-band bands row naming "
                "its composite in component_of"
            )
            assert len(aspect["bands"]) == 2, (
                f"TC-AUTHOR-10 (AF-05): aspect {aspect.get('id')!r} carries "
                f"{len(aspect['bands'])} bands — aspects are binary, two-band "
                "absent/present (FR-AUTHOR-07)"
            )

    # AF-12 — the mixed fixture: mcq lines keyed, judged lines banded or general.
    draft, questions, criteria = drafts["AF-12"]
    for question in questions:
        own = [c for c in criteria if c.get("question") == question["id"]]
        assert own, f"TC-AUTHOR-10 (AF-12): question {question['id']!r} carries no criterion"
        if question["type"] == "mcq":
            assert all("key" in c for c in own), (
                f"TC-AUTHOR-10 (AF-12): mcq question {question['id']!r}'s criteria are "
                "not all keyed — 'circle the answer' lines map to the mcq shape"
            )
            for criterion in own:
                assert criterion["key"] in question["options"], (
                    f"TC-AUTHOR-10 (AF-12): criterion {criterion.get('id')!r} keys "
                    f"{criterion['key']!r}, not one of question {question['id']!r}'s "
                    "declared options (FR-AUTHOR-07)"
                )
        else:
            assert all(_shapes(c) & {"bands", "general"} for c in own), (
                f"TC-AUTHOR-10 (AF-12): judged question {question['id']!r} maps to "
                f"{[sorted(_shapes(c)) for c in own]} — judged lines map to bands or "
                "general, never an unsupported shape (FR-AUTHOR-07)"
            )

    # AF-09 — the contradictory description resolves to unresolved notes, never an edge.
    result, _counted = _draft(author, make_fixture_provider, "AF-09", tmp_path / "af09")
    draft, raw = _draft_toml(result)
    _check_no_edges_or_weights("AF-09", draft.get("criterion") or [])
    declared = set(_expected("AF-09")["placeholders"])
    assert declared <= set(placeholder_fields(raw)), (
        f"TC-AUTHOR-10 (AF-09): the draft carries {sorted(set(placeholder_fields(raw)))} "
        f"but expected.toml declares {sorted(declared)} — the description the reasoning "
        "cannot map becomes placeholders, never a guessed mapping"
    )
    report = result.report_path.read_text(encoding="utf-8")
    assert declared <= set(_unresolved_fields(report)), (
        f"TC-AUTHOR-10 (AF-09): the report's Unresolved section names "
        f"{sorted(set(unresolved_fields(report)))} but expected.toml declares "
        f"{sorted(declared)} — the unmapped items are recorded as unresolved notes for "
        "the review walk (FR-AUTHOR-05), not dropped silently and not turned into edges"
    )


# --- TC-AUTHOR-11 ----------------------------------------------------------------------------


def test_tc_author_11_grades_derive_only_what_is_stated_and_placeholder_the_rest(
        tmp_path, make_fixture_provider):
    """AF-01's stated ranges derive exactly; AF-11's unstated boundaries are the whole-table
    placeholder with no number invented anywhere.

    Disclosure (Q-O8's middle arm): no corpus fixture states *some but not all* boundaries,
    so the partial arm — stated rows derived plus a sentinel per missing row — is written
    ahead of a corpus input that can drive it; both poles of the never-invent rule are
    pinned here on real fixtures (see the module docstring).
    """
    author = _guards(("AF-01", "AF-11"))

    # AF-01 — every boundary stated: derived exactly, nothing sentineled.
    result, _counted = _draft(author, make_fixture_provider, "AF-01", tmp_path / "af01")
    draft, _raw = _draft_toml(result)
    grades = draft.get("grades")
    assert isinstance(grades, dict) and grades == {"A": 14, "B": 10, "C": 6, "D": 0}, (
        f"TC-AUTHOR-11 (AF-01): the draft's [grades] table is {grades!r} — the paper "
        "states 'A: 14-16. B: 10-13. C: 6-9. D: 0-5.' out of 16 points, and the package "
        "vocabulary's [grades] carries the lowest total that earns each grade (the ps9 "
        "spec's own convention), so the derived table is A=14, B=10, C=6, D=0 — derived "
        "from the stated, never invented (FR-AUTHOR-08)"
    )
    assert _no_sentinel(grades), (
        "TC-AUTHOR-11 (AF-01): the grades table carries a sentinel although every "
        "boundary is stated — the stated boundaries are derived, not placeholderd"
    )
    grades_outcomes = [o for o in result.outcomes if o.step == "grades"]
    assert grades_outcomes and all(
        o.status in ("resolved", "derived") for o in grades_outcomes
    ), (
        "TC-AUTHOR-11 (AF-01): the grades step's outcomes are placeholder/unresolved "
        "although the paper states every boundary — the stated table is derived "
        "(FR-AUTHOR-08)"
    )

    # AF-11 — nothing stated: the whole [grades] table is one placeholder.
    result, _counted = _draft(author, make_fixture_provider, "AF-11", tmp_path / "af11")
    draft, raw = _draft_toml(result)
    lines = raw.splitlines()
    sentinel_lines = [
        (index, line)
        for index, line in enumerate(lines)
        if "<<PLACEHOLDER: grades>>" in line
    ]
    assert "grades" in placeholder_fields(raw) and sentinel_lines, (
        "TC-AUTHOR-11 (AF-11): the draft carries no <<PLACEHOLDER: grades>> sentinel — "
        "FR-AUTHOR-08 emits a placeholder for the whole [grades] table when the "
        "documents state no boundary; it must never invent one"
    )
    for index, _line in sentinel_lines:
        above = lines[index - 1] if index else ""
        match = PLACEHOLDER_COMMENT_RE.search(above)
        assert match and match.group(2).strip(), (
            "TC-AUTHOR-11 (AF-11): the grades sentinel line carries no "
            "'# PLACEHOLDER(<reason>): <what the teacher must supply>' comment with a "
            "reason on the line above (FR-AUTHOR-11, CT-AUTHOR-04)"
        )
    boundary_rows = [
        line
        for line in lines
        if re.fullmatch(r"\s*[A-Fa-f]\s*=\s*\d+\s*(#.*)?", line)
    ]
    assert not boundary_rows, (
        f"TC-AUTHOR-11 (AF-11): the draft carries grade-boundary row(s) {boundary_rows!r} "
        "next to the whole-table placeholder — the placeholder replaces the table, so no "
        "boundary number may be invented (FR-AUTHOR-08)"
    )
    grades_outcomes = [o for o in result.outcomes if o.step == "grades"]
    assert grades_outcomes and all(o.status == "placeholder" for o in grades_outcomes), (
        "TC-AUTHOR-11 (AF-11): the grades step's outcomes are not placeholders although "
        "the documents state no boundary — the whole table is the placeholder "
        "(FR-AUTHOR-08, Q-O8's whole-table rule)"
    )


# --- TC-AUTHOR-12 ----------------------------------------------------------------------------


def test_tc_author_12_approved_by_is_a_placeholder_in_every_fixture(
        tmp_path, make_fixture_provider):
    """All thirteen fixtures: `approved_by` is the sentinel plus its reason comment, in
    every draft — the one name the model must never generate, even where the description
    speaks in the teacher's own voice (AF-04)."""
    author = _guards(tuple(f"AF-{index:02d}" for index in range(1, 14)))
    for index in range(1, 14):
        af_id = f"AF-{index:02d}"
        result, _counted = _draft(
            author, make_fixture_provider, af_id, tmp_path / af_id.casefold().replace("-", "")
        )
        draft, raw = _draft_toml(result)
        value = draft.get("approved_by")
        match = SENTINEL_RE.fullmatch(str(value)) if value is not None else None
        assert match and match.group(1) == "approved_by", (
            f"TC-AUTHOR-12 ({af_id}): approved_by is {value!r}, not the "
            "'<<PLACEHOLDER: approved_by>>' sentinel — FR-AUTHOR-09: approved_by is "
            "emitted as a placeholder and filled by the teacher at review; it is never "
            "model-generated, even where the description speaks in the teacher's own "
            "voice (AF-04)"
        )
        lines = raw.splitlines()
        sentinel_index = next(
            (n for n, line in enumerate(lines) if "<<PLACEHOLDER: approved_by>>" in line),
            None,
        )
        assert sentinel_index is not None, (
            f"TC-AUTHOR-12 ({af_id}): the sentinel is in the parsed value but not on any "
            "line of the raw draft — the draft text is the artifact the teacher edits"
        )
        comment = PLACEHOLDER_COMMENT_RE.search(lines[sentinel_index - 1]) if sentinel_index else None
        assert comment and comment.group(2).strip(), (
            f"TC-AUTHOR-12 ({af_id}): the approved_by sentinel line carries no "
            "'# PLACEHOLDER(<reason>): <what the teacher must supply>' comment with a "
            "reason on the line above (FR-AUTHOR-11, CT-AUTHOR-04)"
        )