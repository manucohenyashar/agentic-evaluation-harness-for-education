"""`TC-AUTHOR-13` (FR-AUTHOR-10, CT-AUTHOR-08, FR-PKG-27, P0) — the adversarial validator
corpus, the 50-seed valid-proposal property, and the differential against the real build
gate (#710, the package-authoring test plan §5.1; design delta §3.1, FR-AUTHOR-10).

#693 landed: `validate_draft` ships with `aeh.author` (the #690 module), so the validator
cases run in `TEST_CMD` — the per-test markers came off, the tests kept. The calibration
test below is unmarked and was green first, per the
`tests/property/test_extract_span_bounds.py` doctrine: the corpus and the generator are
calibrated green ahead of the red they justify, so the red can never be vacuous because
the mutations quietly stopped saying what they claim.

**The blocker's target, as issue #710 prescribes it.** Kind `symbol`,
`aeh.author:validate_draft` — the design names the exact signature (design delta §3.1's
Interfaces block; #693's own technical note: `validate_draft(spec: Mapping[str, Any]) ->
list[DraftIssue]`, pure), and `aeh.author` does not exist today, so the key cannot fire
early. The corpus/recordings/chain limbs land strictly earlier (#690 captures the
recordings and closes #686; #693 depends on #691/#692 which depend on it), so at
resolution everything the differential and the recorded half need exists. The residual
early-fire risk is #691's repair budget ("a validator-failing proposal → the repair prompt
carries the validator's issues"): if that story ships the public `validate_draft` before
#693's emission half, the gate fires early — the accepted `#689`/`#702` posture, and the
re-check rule covers it (re-check the cases green before unmarking, never on the notice
alone). Rename path: if #693 spells the name differently, one line in the registry target
plus the `require` calls here and in the TC-AUTHOR-14 file.

**Layer attribution is the case's spine** (FR-AUTHOR-10's code note): `plan_package`
(`pipeline/packages.py`, the build's pure pre-check) owns the key-in-options, the
every-question-graded and the evidence_sum-composite-shape rules, while band-count parity,
the 2..6 bound and monotone points are `pkg.criteria`'s own build-time rules — so the
corpus is split by layer: for the three `pkg.criteria`-only defects the case asserts
`plan_package` does **not** refuse while `validate_draft` does and the real build does;
for the three `plan_package`-owned defects it asserts both layers refuse. That split is
what keeps `validate_draft`'s two-layer wrap honest — a validator that delegated to
`plan_package` alone would pass the build but ship a 5-band draft.

**The differential's scope, disclosed.** The malformed side runs all six corpus entries
through the real `aeh package build` (`aeh.pipeline.cli.main`, in process, a fresh data
directory per entry — a refused `pkg.criteria` build removes the half-built package file
but may leave catalog rows, so entries must not share one). The valid side runs the
baseline plus three deterministic generated variants (2-band, 6-band, a different key) the
same way; the remaining valid proposals are the property's 50 seeded draws below, asserted
against `validate_draft` alone — a real build per hypothesis example would multiply the
suite's wall clock by the example count for no extra discrimination, because the build
gate's half is already pinned by the deterministic arms on both sides.

**The recorded "never enters a draft" limb is `TC-AUTHOR-C08`'s** (`tests/contract/author/
test_cs_author_c06_c07_c08_chain_rules.py`): the clause suite proves on recorded runs that
only validator-passing proposals enter a draft and that AF-09's shipped rows satisfy the
rules. This file owns the corpus, the property and the differential — the plan's split —
and asserts on the *malformed* side what C08 cannot: that each defect is named by the
validator and refused by the real gate, never silently accepted at either layer.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
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
from aeh.pipeline.packages import PackageSpecError, plan_package

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
except ImportError:  # pragma: no cover
    given = None

from tests.support.author_vocabulary import AUTHOR_MODULE
from tests.support.impl import require

REPO = Path(__file__).resolve().parents[3]
SAMPLE_SPEC = REPO / "docs" / "live-tests" / "config" / "ps9-forces-01.package.toml"

# --- the sample spec's anchors. Each must occur exactly once — a silent replacement of the
# --- wrong line would test a spec that does not say what the case claims (the C23 pattern).

#: Q1's key line with its question for context (`key = "C"` alone also appears on C3).
Q1_KEY_ANCHOR = 'question = "Q1"\nkey = "C"'

#: C4's worst, middle and best band lines — unique by their descriptors (C6's differ). The
#: count mutations insert after the middle band, so the points stay non-decreasing and the
#: odd count (not a monotonicity break) is the only defect each entry carries.
C4_NONE_LINE = (
    '  { name = "none", points = 0, descriptor = "No relevant force named, or a claim that '
    'contradicts the answer." },'
)
C4_ADEQUATE_LINE = (
    '  { name = "adequate", points = 2, descriptor = "Names both forces, but does not say '
    'they are equal or that the net force is zero." },'
)
C4_FULL_LINE = (
    '  { name = "full", points = 3, descriptor = "Names the weight (gravity) pulling down AND '
    'the normal (support) force pushing up, AND says they are equal so the net force is zero." },'
)

#: C1's whole criterion block — removing it leaves Q1 with no rubric line.
C1_BLOCK = '[[criterion]]\nid = "C1"\nquestion = "Q1"\nkey = "C"\n\n'

#: The C4 bands-list delimiters, for whole-list replacement (the valid variants).
C4_BANDS_START = 'id = "C4"\nquestion = "Q4"\nbands = [\n'
C4_BANDS_END = ']\n\n[[criterion]]\nid = "C5"'

#: A malformed evidence_sum composite: the one shape error FR-PKG-24/CT-PKG-21 name first —
#: the composite itself carrying bands (its aspects are the band carriers).
COMPOSITE_CARRYING_BANDS = """
[[criterion]]
id = "C9"
question = "Q4"
score_method = "evidence_sum"
points = 2
bands = [
  { name = "absent", points = 0, descriptor = "The evidence is absent." },
  { name = "present", points = 2, descriptor = "The evidence is present." },
]
"""

#: The corpus: `(label, edits, append, layer, the refusal phrase the real gate must print)`.
#: `layer` is the rule's owner per FR-AUTHOR-10's code note — "plan" for `plan_package`'s
#: own rules, "criteria" for the `pkg.criteria` build-time rules the validator must wrap.
MALFORMED_CORPUS = (
    (
        "5-band odd count",
        ((C4_ADEQUATE_LINE, C4_ADEQUATE_LINE
          + '\n  { name = "middle", points = 2, descriptor = "Between adequate and full." },'),),
        "",
        "criteria",
        "FR-PKG-06",
    ),
    (
        "7-band set",
        ((C4_ADEQUATE_LINE, C4_ADEQUATE_LINE
          + '\n  { name = "middle", points = 2, descriptor = "Between adequate and full." },'
          + '\n  { name = "spare", points = 2, descriptor = "As adequate." },'
          + '\n  { name = "surplus", points = 3, descriptor = "As full." },'),),
        "",
        "criteria",
        "FR-PKG-06",
    ),
    (
        "non-monotone points",
        ((C4_NONE_LINE, C4_NONE_LINE.replace("points = 0", "points = 2")),),
        "",
        "criteria",
        "FR-PKG-06",
    ),
    (
        "key not among the options",
        ((Q1_KEY_ANCHOR, 'question = "Q1"\nkey = "Z"'),),
        "",
        "plan",
        "is not among",
    ),
    (
        "uncovered question",
        ((C1_BLOCK, ""),),
        "",
        "plan",
        "no rubric line",
    ),
    (
        "composite carrying bands",
        (),
        COMPOSITE_CARRYING_BANDS,
        "plan",
        "carries no bands",
    ),
)

#: The valid side of the differential: `(label, bands-or-None, key)`. `bands` `None` keeps
#: the sample's own four C4 bands; otherwise the list replaces them whole.
VALID_VARIANTS = (
    ("the sample spec as authored", None, "C"),
    ("a two-band C4", (("none", 0, ""), ("full", 3, "")), "C"),
    (
        "a six-band C4",
        (
            ("none", 0, ""),
            ("base", 0, ""),
            ("low", 1, ""),
            ("mid", 1, ""),
            ("high", 2, ""),
            ("full", 3, ""),
        ),
        "C",
    ),
    ("a different key among Q1's options", None, "A"),
)


def _mutated_text(edits, append: str = "") -> str:
    """The sample spec with each edit applied (each anchor asserted unique) and any block
    appended — the corpus's single construction, shared by the calibration and the cases."""
    text = SAMPLE_SPEC.read_text(encoding="utf-8")
    for old, new in edits:
        assert text.count(old) == 1, f"anchor is not unique in the sample spec: {old!r}"
        text = text.replace(old, new)
    if append:
        if not text.endswith("\n"):
            text += "\n"
        text += append
    return text


def _band_lines(bands) -> str:
    """The TOML lines for a C4 bands list: worst first, each with name, points, descriptor."""
    return "".join(
        f'  {{ name = "{name}", points = {points}, descriptor = "{descriptor}" }},\n'
        for name, points, descriptor in bands
    )


def _replace_c4_bands(text: str, bands) -> str:
    """The spec with C4's whole bands list replaced. The delimiters are asserted unique so
    a drifted sample spec fails loudly here rather than quietly mutating the wrong line."""
    assert text.count(C4_BANDS_START) == 1, "the C4 bands-list start anchor is not unique"
    assert text.count(C4_BANDS_END) == 1, "the C4 bands-list end anchor is not unique"
    start = text.index(C4_BANDS_START) + len('id = "C4"\nquestion = "Q4"\n')
    end = text.index(C4_BANDS_END, start)
    return text[:start] + "bands = [\n" + _band_lines(bands) + text[end:]


def _valid_variant_text(bands, key: str) -> str:
    """A valid proposal: the sample spec with C4's bands (optionally) replaced and Q1's key
    drawn from its declared options — every rule still holds by construction."""
    text = SAMPLE_SPEC.read_text(encoding="utf-8")
    if bands is not None:
        text = _replace_c4_bands(text, bands)
    assert text.count(Q1_KEY_ANCHOR) == 1
    return text.replace(Q1_KEY_ANCHOR, f'question = "Q1"\nkey = "{key}"')


def _gate():
    """The require-style gate, and the first thing each red test body does: a missing
    validator is `NotImplementedYet` naming the blocker — never a collection error. The
    module and the gate are #693's together; the gate is what the registry key pins, so
    the red names it even once the module itself has landed."""
    author = require(AUTHOR_MODULE, issue="#693")  # the module itself
    require(AUTHOR_MODULE, "validate_draft", issue="#693")  # the §3.1 gate
    return author


# --- calibration (green today, unmarked): the corpus says what it claims ------------------------


def test_tc_author_13_the_corpus_mutations_and_the_generator_are_calibrated():
    """The sample spec is what the anchors assume; every malformed entry carries exactly the
    defect its label names; every valid variant parses and holds the rules by construction.
    Green first, so the validator cases' red could only ever be the missing validator."""
    text = SAMPLE_SPEC.read_text(encoding="utf-8")
    for anchor in (Q1_KEY_ANCHOR, C4_NONE_LINE, C4_ADEQUATE_LINE, C4_FULL_LINE, C1_BLOCK,
                   C4_BANDS_START, C4_BANDS_END):
        assert text.count(anchor) == 1, f"anchor is not unique in the sample spec: {anchor!r}"

    baseline = tomllib.loads(text)
    questions = {q["id"]: q for q in baseline["question"]}
    assert set(questions["Q1"]["options"]) == {"A", "B", "C", "D"}
    c4 = next(c for c in baseline["criterion"] if c["id"] == "C4")
    assert [b["points"] for b in c4["bands"]] == [0, 1, 2, 3]

    def _c4_bands(parsed):
        return next(c for c in parsed["criterion"] if c["id"] == "C4")["bands"]

    parsed = {
        label: tomllib.loads(_mutated_text(edits, append))
        for label, edits, append, _layer, _phrase in MALFORMED_CORPUS
    }
    assert len(_c4_bands(parsed["5-band odd count"])) == 5
    assert [b["points"] for b in _c4_bands(parsed["5-band odd count"])] == [0, 1, 2, 2, 3]
    assert len(_c4_bands(parsed["7-band set"])) == 7
    assert [b["points"] for b in _c4_bands(parsed["7-band set"])] == [0, 1, 2, 2, 2, 3, 3]
    assert [b["points"] for b in _c4_bands(parsed["non-monotone points"])] == [2, 1, 2, 3]
    stray = next(c for c in parsed["key not among the options"]["criterion"] if c["id"] == "C1")
    assert stray["key"] == "Z" and "Z" not in questions["Q1"]["options"]
    covered = {c["question"] for c in parsed["uncovered question"]["criterion"]}
    assert "Q1" not in covered
    composite = parsed["composite carrying bands"]["criterion"][-1]
    assert composite["id"] == "C9" and composite["score_method"] == "evidence_sum"
    assert "bands" in composite

    for _label, bands, key in VALID_VARIANTS:
        variant = tomllib.loads(_valid_variant_text(bands, key))
        vc4 = next(c for c in variant["criterion"] if c["id"] == "C4")
        points = [b["points"] for b in vc4["bands"]]
        assert len(points) % 2 == 0 and 2 <= len(points) <= 6
        assert points == sorted(points)
        q1 = next(q for q in variant["question"] if q["id"] == "Q1")
        vkey = next(c for c in variant["criterion"] if c["id"] == "C1")["key"]
        assert vkey in q1["options"]


# --- the adversarial corpus: rejected by the validator, refused by the real gate -----------------


@pytest.mark.parametrize(
    "label,edits,append,layer,phrase", MALFORMED_CORPUS, ids=[m[0] for m in MALFORMED_CORPUS])
def test_tc_author_13_the_malformed_proposal_is_rejected_and_the_real_gate_agrees(
        label, edits, append, layer, phrase, tmp_path, tmp_data_dir, capsys):
    """Each malformed proposal: `validate_draft` names it (a `DraftIssue` with a field and a
    message), the layer that owns the rule behaves as FR-AUTHOR-10 attributes it, and the
    real `aeh package build` refuses with the rule's own phrase — the differential agrees,
    and a proposal either layer rejects can never reach a built package, let alone a draft."""
    author = _gate()
    spec_path = tmp_path / "draft.package.toml"
    spec_path.write_text(_mutated_text(edits, append), encoding="utf-8")
    parsed = tomllib.loads(spec_path.read_text(encoding="utf-8"))

    issues = author.validate_draft(parsed)
    assert issues, f"{label}: the validator accepted the malformed proposal"
    for issue in issues:
        assert isinstance(issue, author.DraftIssue), f"{label}: {issue!r} is not a DraftIssue"
        assert issue.field and issue.message, f"{label}: an unnamed finding: {issue!r}"

    probe_dir = tmp_path / "planprobe"
    if layer == "criteria":
        plan = plan_package(parsed, probe_dir)
        assert plan.package_id == "PS9-FORCES-01", (
            f"{label}: the pure pre-check must not own this rule (FR-AUTHOR-10's split)")
    else:
        with pytest.raises(PackageSpecError, match=phrase):
            plan_package(parsed, probe_dir)

    code = cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(spec_path)])
    err = capsys.readouterr().err
    assert code == 1, f"{label}: the real build accepted the malformed proposal: {err!r}"
    assert phrase in err, f"{label}: the refusal is not this rule's: {err!r}"


# --- the differential's valid side: the validator passes, the real build builds ------------------


@pytest.mark.parametrize("label,bands,key", VALID_VARIANTS, ids=[v[0] for v in VALID_VARIANTS])
def test_tc_author_13_the_valid_proposal_passes_and_the_real_gate_builds_it(
        label, bands, key, tmp_path, tmp_data_dir, capsys):
    """The baseline and three deterministic generated variants: `validate_draft` returns no
    findings and the real build exits 0 — the differential agrees in the passing direction
    too, so a validator stricter than the gate cannot hide behind the malformed corpus."""
    author = _gate()
    spec_path = tmp_path / "variant.package.toml"
    text = _valid_variant_text(bands, key)
    spec_path.write_text(text, encoding="utf-8")

    assert author.validate_draft(tomllib.loads(text)) == [], (
        f"{label}: the validator rejected a valid proposal")

    code = cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(spec_path)])
    err = capsys.readouterr().err
    assert code == 0, f"{label}: the real build refused a valid proposal: {err!r}"


# --- the property: 50 seeded valid proposals all pass --------------------------------------------


if given is not None:
    @pytest.mark.property
    @settings(deadline=None)
    @given(st.data())
    def test_tc_author_13_the_property_seeded_valid_proposals_all_pass(data):
        """Over seeded valid proposals — even band counts in 2..6, non-decreasing points,
        band names and descriptors drawn freely, Q1's key drawn from its declared options —
        the validator returns no findings. The default profile's 50 derandomized examples
        are the plan's "50 seeded valid proposals"; the `ci` profile raises the count."""
        author = _gate()

        count = data.draw(st.sampled_from([2, 4, 6]))
        points = sorted(data.draw(st.lists(st.integers(0, 3), min_size=count, max_size=count)))
        names = data.draw(st.lists(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8),
            min_size=count, max_size=count))
        descriptor = data.draw(st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=0, max_size=24))
        key = data.draw(st.sampled_from(list("ABCD")))

        text = _valid_variant_text(
            list(zip(names, points, [descriptor] * count)), key)
        parsed = tomllib.loads(text)

        assert author.validate_draft(parsed) == [], (
            "a valid proposal was rejected: "
            f"bands={list(zip(names, points))}, key={key!r}")
else:  # pragma: no cover
    def test_tc_author_13_the_property_seeded_valid_proposals_all_pass():
        pytest.skip("hypothesis is not installed")