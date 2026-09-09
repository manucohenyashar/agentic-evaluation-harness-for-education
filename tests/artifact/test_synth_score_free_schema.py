"""`TC-SYNTH-02`, `TC-SYNTH-03`, `TC-SYNTH-07` — the score-free schema and the
type-enforced information boundary (`M-SYNTH`, TS-37, all P0, all rung 0).

- `TC-SYNTH-02` (`NFR-SYNTH-03`): L2's inability to read raw verdicts is enforced by the
  **request type**, not by prompt instruction — no field on the L2 request can carry a
  verdict, so a ten-question exam cannot hand it thirty verdicts after a later change.
- `TC-SYNTH-03` (`FR-SYNTH-02`): no points, band, score or grade field exists on the
  synthesis result, and no write path to `criterion_score` or `submission_grade` exists.
- `TC-SYNTH-07` (`FR-SYNTH-05`): the synthesis request carries exactly one
  `submission_id`; no other submission's content is reachable.

Written ahead of `#97` (test plan §8.2): every case fails only through
`NotImplementedYet` naming `#97`, or — once the module lands — through the assertion
itself.

**Static on purpose** (the `test_integ_write_set.py` precedent): the write-graph half of
TC-SYNTH-03 is an AST walk over `src/aeh/synth.py` itself, so it holds for code paths no
test exercises — a dynamic write-audit would only prove the paths the suite happened to
drive, which is the hole a `criterion_score` write smuggled into an untested branch
would hide in (RISK-19: a narrative module that can write a score is a second,
competing grade, invisible to any metric).

Interface assumed of `#97` (reconcile at landing, one line in
`tests/support/synth_vocabulary.py`):

- `aeh/synth.py` exists and exports the three types by the vocabulary's names
  (`L1Request`, `L2Request`, `SynthesisResult`).
- All three are dataclasses — the boundary NFR-SYNTH-03 demands is a *type*, and a type
  a test cannot introspect is not an enforceable one; `dataclasses.fields` is the
  introspection.
- The L2 construction probe (`TC-SYNTH-02`) is the design's own acceptance form
  (`CT-SYNTH-02`: "attempting to construct one and confirming the type rejects it"); a
  type that silently accepts a `criterion_verdicts=` kwarg fails the case.
- Exact field-set equality per level is `TC-SYNTH-C01`'s case (issue #100's contract
  suite); this file asserts the *prohibition* FR-SYNTH-02 states — the negative half —
  so a result that loses a field the design never gave it is not this file's failure,
  while a result that grows a score-shaped field is.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path
from typing import Any

import pytest

from tests.support.impl import SYNTH_MODULE, require
from tests.support.synth_vocabulary import (
    L1_REQUEST,
    L2_REQUEST,
    RESULT_TYPE,
    SYNTH_ISSUE,
)


#: The score-shaped names FR-SYNTH-02 forbids on the result — `points`, `band`, `score`,
#: `grade` are the clause's own four; the rest are the spellings a "helpful" later
#: change reaches for first (`confidence` is CT-SYNTH-01's explicit fourth, the others
#: are RISK-19's paraphrase surface).
RESULT_FORBIDDEN_FIELDS = frozenset({
    "points", "band", "score", "grade", "confidence",
    "percent", "percentage", "mark", "marks", "total",
})

#: The verdict carriers NFR-SYNTH-03 forbids on the L2 request. `judge` is included
#: because a raw verdict is identifiable by its judge trio even with the band renamed.
REQUEST_FORBIDDEN_FIELDS = frozenset({
    "verdict", "verdicts", "band", "bands", "points", "score", "grade",
    "judge", "judges", "judge_id", "criterion_verdicts", "raw",
})

_VERDICT_WRITE_SQL = re.compile(
    r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(criterion_score|submission_grade)\b",
    re.IGNORECASE,
)

#: The modules whose write sets own the two score tables (CT-AGG-11 names
#: `criterion_score`; `submission_grade` is M-GRADE's). An import of either from the
#: narrative module is a write path waiting for a "convenient" line of code.
SCORE_OWNERS = frozenset({"aeh.agg", "aeh.grade"})


def _synth_tree() -> tuple[Path, ast.AST]:
    """The parsed source of `aeh.synth` — the module file itself is the artifact."""
    require(SYNTH_MODULE, issue=SYNTH_ISSUE)
    path = Path(__file__).resolve().parents[2] / "src" / "aeh" / "synth.py"
    assert path.exists(), f"expected the M-SYNTH module at {path} (reconcile at landing)"
    return path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.AST) -> set[str]:
    """Modules `aeh.synth` imports, with every spelling resolved: `import aeh.agg`,
    `from aeh.agg import x`, `from aeh import agg` and the relative forms (synth.py
    lives in the `aeh` package, so `level > 0` resolves against it)."""
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = "aeh." * node.level + (node.module or "")
            if base:
                imported.add(base)
            imported.update(
                f"{base}.{alias.name}" if base else alias.name for alias in node.names
            )
    return imported


def _string_constants(node: ast.AST) -> "list[str]":
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [s for value in node.values for s in _string_constants(value)]
    return []


def _fields_named(owner: str, issue: str) -> "list[str]":
    """The field names of a request/result type, with the dataclass requirement stated."""
    cls = require(SYNTH_MODULE, owner, issue=issue)
    assert dataclasses.is_dataclass(cls), (
        f"aeh.synth.{owner} is not a dataclass — the boundary NFR-SYNTH-03 demands is a "
        "type, and a type whose fields a test cannot enumerate is not an enforceable one"
    )
    return [field.name for field in dataclasses.fields(cls)]


def test_tc_synth_02_l2_request_type_cannot_carry_a_verdict():
    """`TC-SYNTH-02` (P0, rung 0) — no field on the L2 request can carry a verdict.

    The boundary is the **type**, not the prompt: if a later change can construct an L2
    request that holds thirty verdicts for a ten-question exam, a small model gets them
    and nothing in the type system objects. The probe is `CT-SYNTH-02`'s own acceptance
    form — attempt the construction, expect the type to refuse it.
    """
    field_names = _fields_named(L2_REQUEST, issue=SYNTH_ISSUE)

    forbidden = {
        name for name in field_names
        if name.lower() in REQUEST_FORBIDDEN_FIELDS
        or set(name.lower().split("_")) & REQUEST_FORBIDDEN_FIELDS
    }
    assert not forbidden, (
        f"aeh.synth.{L2_REQUEST} carries verdict-shaped fields {sorted(forbidden)} — "
        "NFR-SYNTH-03: L2's inability to read raw verdicts is enforced by the request "
        "type, not by prompt instruction, so a ten-question exam cannot hand it thirty "
        "verdicts after a later change"
    )

    # The design's acceptance form: attempt to construct an L2 request carrying a raw
    # verdict set — thirty verdicts, a ten-question exam's three-judge panel — and
    # confirm the type rejects it, whatever field name the smuggler picks.
    thirty_verdicts = [
        {"criterion_id": f"Q{q}C{k}", "judge_id": f"judge-{j}", "band": "high"}
        for q in range(1, 11)
        for k in range(1, 4)
        for j in range(1, 4)
    ][:30]
    cls = require(SYNTH_MODULE, L2_REQUEST, issue=SYNTH_ISSUE)
    # The probe constructs a VALID request plus the smuggled field, so the TypeError it
    # expects can only be the unexpected-keyword refusal — not a missing-argument error
    # that any field set would raise (a probe satisfied by the wrong failure proves
    # nothing; reviewer, #97).
    valid_kwargs = {name: ("" if name != "syntheses" else ()) for name in field_names}
    for smuggled_kwarg in ("criterion_verdicts", "verdicts", "raw_verdicts"):
        try:
            cls(**valid_kwargs, **{smuggled_kwarg: thirty_verdicts})
        except TypeError:
            continue  # the type refused the smuggled field — the boundary held
        raise AssertionError(
            f"aeh.synth.{L2_REQUEST} accepted {smuggled_kwarg}= at construction — a "
            "request type that can represent a raw verdict lets a later change hand a "
            "small model thirty verdicts, and nothing fails (NFR-SYNTH-03's named "
            "failure)"
        )


def test_tc_synth_03_result_schema_and_write_graph_are_score_free():
    """`TC-SYNTH-03` (P0, rung 0) — no points, band, score or grade field exists on the
    synthesis result, and no write path to `criterion_score` or `submission_grade`
    exists."""
    field_names = _fields_named(RESULT_TYPE, issue=SYNTH_ISSUE)
    # Word-component match, not exact match: `total_score` and `score_hint` are the
    # "helpful later change" spellings this prohibition exists for, and an exact-name
    # intersection waves them through.
    hit = {
        name for name in field_names
        if set(name.lower().split("_")) & RESULT_FORBIDDEN_FIELDS
    }
    assert not hit, (
        f"aeh.synth.{RESULT_TYPE} carries score-shaped fields {sorted(hit)} — FR-SYNTH-02: "
        "a consumer cannot read a score out of this module because there is nowhere for "
        "one to be; a numeric field is the second, competing grade RISK-19 describes"
    )

    # The write-graph half, statically: no import of a score-owning module, and no SQL
    # write against the two tables anywhere in the module's source — including branches
    # no test drives, which is why this half is an AST walk and not a write audit.
    path, tree = _synth_tree()
    touched = _imported_modules(tree) & SCORE_OWNERS
    assert not touched, (
        f"{path.name} imports {sorted(touched)} — the module that writes narratives "
        "must not even reach for the module that scores (FR-SYNTH-02, §7.2 Rule 3; "
        "CT-AGG-11 states the reciprocal half)"
    )
    for node in ast.walk(tree):
        for text in _string_constants(node):
            match = _VERDICT_WRITE_SQL.search(text)
            assert match is None, (
                f"{path.name} contains a write against {match.group(2)!r} "
                f"({match.group(1)!r}) — FR-SYNTH-02 forbids any write path to "
                "criterion_score or submission_grade; the narrative write set and the "
                "score write set are disjoint by design"
            )


def test_tc_synth_07_request_carries_exactly_one_submission_id():
    """`TC-SYNTH-07` (P0, rung 0) — the synthesis request carries exactly one
    `submission_id`, and no other submission's content is reachable.

    Asserted at **both** levels: the boundary FR-SYNTH-05 states is the request schema's,
    and the L2 request is as much a synthesis request as the L1 one (§7.2 Rule 1: exactly
    one submission per dispatched request, with no mechanism to place two in one call and
    none to be added)."""
    for request_name in (L1_REQUEST, L2_REQUEST):
        names = _fields_named(request_name, issue=SYNTH_ISSUE)
        assert names.count("submission_id") == 1, (
            f"aeh.synth.{request_name} carries submission_id {names.count('submission_id')} "
            "times — exactly one is the schema fact FR-SYNTH-05 states"
        )
        plural = [
            name for name in names
            if name != "submission_id" and "submission" in name.lower()
        ]
        assert not plural, (
            f"aeh.synth.{request_name} carries submission-shaped fields {plural} — a "
            "collection field is another submission's content made reachable, which "
            "FR-SYNTH-05 forbids outright"
        )
