"""`TC-AUTHOR-13` — the build-gate parity arms the landing audit added (issue #693).

The #693 landing's reviewer audit found two rule families `aeh package build` enforces at
build time that `validate_draft` did not wrap — exactly the drift RISK-121's differential
exists to catch, on rules neither `plan_package` nor the shipped corpus carried:

- the `[grades]` boundary rules `set_boundaries` refuses at build time (`FR-PKG-16`,
  `pkg/policy_and_keys.py`): an empty grade label, a non-finite floor and duplicate floors
  all pass `plan_package` (which only checks each value is a number) and are refused only
  when the build sets the table;
- the composite-shape rule `_composite_problems` refuses at build time (`CT-PKG-21`,
  `FR-JUDGE-38`): an `evidence_sum` criterion with no aspect criterion naming it passes
  `plan_package` and dies at publish.

The non-finite floor was also reachable through the shipped model path: `parse_grades`
accepted any `float`, and `json.loads` parses the JSON `Infinity`/`NaN` literals, so a
model reply `{"grades": {"A": Infinity}}` entered the draft having passed its proposal
gate — the Goal's prohibited case. The finiteness arm closes it at the proposal gate.

Layer attribution (the TC-AUTHOR-13 spine): all four malformed arms are `criteria`-layer
rules — `plan_package` must NOT refuse, `validate_draft` must, and the real build must.
The differential runs the real `aeh package build` in process, a fresh data directory per
entry, exactly as the parent file's corpus does.
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
from aeh.author.grades import parse_grades
from aeh.pipeline import cli
from aeh.pipeline.packages import plan_package

from tests.support.author_vocabulary import AUTHOR_MODULE
from tests.support.impl import require

REPO = Path(__file__).resolve().parents[3]
SAMPLE_SPEC = REPO / "docs" / "live-tests" / "config" / "ps9-forces-01.package.toml"

#: The `[grades]` table's anchor — each one-line mutation edits one line of it, so the
#: whole table is the asserted-unique anchor (the C23 pattern).
GRADES_TABLE = "A = 8\nB = 6\nC = 4\nD = 2\nF = 0\n"

#: A composite that carries no bands, no key and declares its points — shape-clean for
#: `plan_package`, which is exactly why its missing aspects are a build-time refusal.
COMPOSITE_WITHOUT_ASPECTS = """
[[criterion]]
id = "C10"
question = "Q4"
score_method = "evidence_sum"
points = 2
"""

#: Two composites naming each other: each satisfies the other's "named by an aspect" scan,
#: but the build stores `component_of` only on judged lines — composites are dropped, so
#: publish refuses both with the no-aspect rule. Only a judged line counts as an aspect.
MUTUALLY_NAMING_COMPOSITES = """
[[criterion]]
id = "C10"
question = "Q4"
score_method = "evidence_sum"
points = 2
component_of = "C11"

[[criterion]]
id = "C11"
question = "Q4"
score_method = "evidence_sum"
points = 2
component_of = "C10"
"""

#: `(label, edits, append, the refusal phrase the real build prints)`. Every arm is a
#: `criteria`-layer rule: `plan_package` passes, `validate_draft` refuses, the build refuses.
MALFORMED_ARMS = (
    (
        "duplicate grade floors",
        ((GRADES_TABLE, GRADES_TABLE.replace("D = 2", "D = 4")),),
        "",
        "duplicate scaled floors",
    ),
    (
        "non-finite grade floor",
        ((GRADES_TABLE, GRADES_TABLE.replace("A = 8", "A = inf")),),
        "",
        "finite scaled scores",
    ),
    (
        "empty grade label",
        ((GRADES_TABLE, GRADES_TABLE + '"" = 9\n'),),
        "",
        "names each grade",
    ),
    (
        "composite without aspects",
        (),
        COMPOSITE_WITHOUT_ASPECTS,
        "no aspect criteria",
    ),
    (
        "mutually naming composites",
        (),
        MUTUALLY_NAMING_COMPOSITES,
        "no aspect criteria",
    ),
)


def _mutated_text(edits, append: str = "") -> str:
    """The sample spec with each asserted-unique edit applied and any block appended."""
    text = SAMPLE_SPEC.read_text(encoding="utf-8")
    for old, new in edits:
        assert text.count(old) == 1, f"anchor is not unique in the sample spec: {old!r}"
        text = text.replace(old, new)
    if append:
        if not text.endswith("\n"):
            text += "\n"
        text += append
    return text


def test_tc_author_13_the_sample_spec_stays_build_gate_clean():
    """The untouched sample spec carries no findings — the new grades and composite sweeps
    hold their false-positive rate at zero on the valid side of the differential."""
    author = require(AUTHOR_MODULE, issue="#693")
    require(AUTHOR_MODULE, "validate_draft", issue="#693")
    assert author.validate_draft(tomllib.loads(SAMPLE_SPEC.read_text(encoding="utf-8"))) == []


@pytest.mark.parametrize("label,edits,append,phrase", MALFORMED_ARMS,
                         ids=[arm[0] for arm in MALFORMED_ARMS])
def test_tc_author_13_the_build_time_rule_is_wrapped_and_the_real_gate_agrees(
        label, edits, append, phrase, tmp_path, tmp_data_dir, capsys):
    """Each build-time rule the landing audit found unwrapped: `plan_package` passes (the
    rule is not the pure pre-check's), `validate_draft` names it (a `DraftIssue` with a
    field and a message), and the real `aeh package build` refuses with the rule's own
    phrase — the differential agrees on the arm, in both directions."""
    author = require(AUTHOR_MODULE, issue="#693")
    require(AUTHOR_MODULE, "validate_draft", issue="#693")
    spec_path = tmp_path / "draft.package.toml"
    spec_path.write_text(_mutated_text(edits, append), encoding="utf-8")
    parsed = tomllib.loads(spec_path.read_text(encoding="utf-8"))

    plan = plan_package(parsed, tmp_path / "planprobe")
    assert plan.package_id == "PS9-FORCES-01", (
        f"{label}: the pure pre-check must not own this rule (the criteria layer owns it)")

    issues = author.validate_draft(parsed)
    assert issues, f"{label}: the validator accepted what the build refuses"
    for issue in issues:
        assert isinstance(issue, author.DraftIssue), f"{label}: {issue!r} is not a DraftIssue"
        assert issue.field and issue.message, f"{label}: an unnamed finding: {issue!r}"

    code = cli.main(["package", "build", "--data-dir", str(tmp_data_dir),
                     "--spec", str(spec_path)])
    err = capsys.readouterr().err
    assert code == 1, f"{label}: the real build accepted the malformed proposal: {err!r}"
    assert phrase in err, f"{label}: the refusal is not this rule's: {err!r}"


def test_tc_author_13_the_grades_reply_gate_refuses_non_finite_boundaries():
    """The model-path arm: a grades reply carrying the JSON `Infinity`/`NaN` literals —
    which `json.loads` parses — is a complaint at the proposal gate, never a value that
    enters the draft (the Goal's prohibited case). The duplicate-floor rule was already
    wrapped; finiteness is the arm the audit added."""
    author = require(AUTHOR_MODULE, issue="#693")
    require(AUTHOR_MODULE, "validate_draft", issue="#693")
    value, complaints = parse_grades('{"grades": {"A": Infinity, "B": NaN, "C": 6}}')
    assert value is None, "a non-finite boundary table was accepted at the proposal gate"
    assert complaints, "the non-finite reply carried no complaint"
    assert any("finite" in complaint for complaint in complaints), (
        f"the complaint is not the finiteness rule's: {complaints!r}")