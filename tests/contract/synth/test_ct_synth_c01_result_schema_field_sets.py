"""`TC-SYNTH-C01` — the result schema carries no score, by field-set equality (§6.11.13).

`CT-SYNTH-01`'s data clause at rung 0, over the *result* type: `SynthesisResult` is
exactly `{work_id, question_id, text}` at L1 and `{work_id, text}` at L2 — the L2
`question_id` is simply absent (`None`), never a second question-ish field — and the
structural prohibition that gives the clause its force: **no numeric field exists**.
Not points, not band, not grade, not confidence — a schema with nowhere for a number
is a stronger guarantee than any text scan, which is why the clause is phrased as a
schema fact and asserted as one.

Relationship to shipped cases, disclosed:

- `tests/artifact/test_synth_score_free_schema.py` (`TC-SYNTH-02/07`) scans the
  dataclass source for forbidden field *names* and probes the `L2Request` type. A
  name scan cannot see a field that carries a score under a name the scan does not
  list (`confidence`, `weight`, `normalized`), so this case asserts the set
  **equality** — any added field turns it red, whatever the field is called — and
  the type-level prohibition: every field's declared type must be text-or-absent,
  so a numeric slot cannot be introduced under any name.
- The set-equality oracle is the one the sibling explicitly leaves to "TC-SYNTH-C01
  (issue #100's contract suite)".

Isolation: rung 0 — dataclasses and one constructor call per level, no store, no
provider.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from tests.support.impl import SYNTH_MODULE, require
from tests.support.synth_vocabulary import RESULT_TYPE, SYNTH_ISSUE

pytestmark = [pytest.mark.contract]

#: The design's field sets, verbatim from CT-SYNTH-01 ("exactly ... at L1 and ...
#: at L2, by set equality per level").
RESULT_FIELDS = frozenset({"work_id", "question_id", "text"})


def test_tc_synth_c01_result_field_set_is_exact_per_level():
    """`TC-SYNTH-C01` (P0) — `SynthesisResult` carries exactly the three design
    fields; `question_id` is `None` at L2 rather than a different type or a missing
    attribute, and no numeric field exists on the type at all."""
    Result = require(SYNTH_MODULE, RESULT_TYPE, issue=SYNTH_ISSUE)

    declared = {field.name for field in fields(Result)}
    assert declared == RESULT_FIELDS, (
        f"SynthesisResult carries {sorted(declared)}; CT-SYNTH-01 fixes the result "
        f"schema at exactly {sorted(RESULT_FIELDS)}. A field added under any name — "
        "including an innocuous one — is a place for a score to arrive through the "
        "back door, which is the thing this clause closes."
    )

    l1 = Result(work_id="nar:r:s:l1_question:Q1", question_id="Q1", text="prose")
    l2 = Result(work_id="nar:r:s:l2_test:__test__", question_id=None, text="prose")
    assert l1.question_id == "Q1" and isinstance(l1.question_id, str), (
        "at L1 the question the narrative belongs to must be present"
    )
    assert l2.question_id is None, (
        f"an L2 result carries question_id={l2.question_id!r} — the L2 row is "
        "submission-scoped (sentinel-keyed, CT-SYNTH-06) and design says the member "
        "is absent, not defaulted to some other question-shaped value"
    )


def test_tc_synth_c01_no_numeric_field_exists_on_the_result():
    """`TC-SYNTH-C01` (P0, the structural prohibition) — no field of the result can
    hold a number: checked on the declared annotations AND behaviourally on a
    constructed value, because a consumer reads the value, not the annotation."""
    Result = require(SYNTH_MODULE, RESULT_TYPE, issue=SYNTH_ISSUE)

    numeric_annoted = [
        field.name
        for field in fields(Result)
        if any(
            token.strip() in {"int", "float", "bool"}
            for token in str(field.type).split("|")
        )
    ]
    assert not numeric_annoted, (
        f"SynthesisResult declares numeric field(s) {numeric_annoted} — CT-SYNTH-01: "
        "no numeric field exists, not points, band, grade or confidence. A schema "
        "with nowhere for a number is what keeps the narrative from becoming a "
        "second competing grade (RISK-19) even if every scan upstream misses."
    )
    for value in (
        Result(work_id="nar:r:s:l1_question:Q1", question_id="Q1", text="prose"),
        Result(work_id="nar:r:s:l2_test:__test__", question_id=None, text="prose"),
    ):
        numeric_holding = [
            name for name in RESULT_FIELDS
            if isinstance(getattr(value, name), (int, float))
        ]
        assert not numeric_holding, (
            f"the constructed result holds numbers in {numeric_holding} — a consumer "
            "reading the result object would find a score-shaped value, which the "
            "clause forbids at the type level"
        )
