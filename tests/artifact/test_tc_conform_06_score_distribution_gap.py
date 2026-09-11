"""`TC-CONFORM-06`, the gap half — the score-distribution gate is recorded as not computable.

Case: test plan §5.18, `FR-CONFORM-06`, §2.3 Q-02, §7.4. Oracle: **artifact assertion** (the
case's other half, the exact verdict for the testable half, is behavioral and lives in
`tests/integration/conform/test_tc_conform_06_divergence_gate_and_gap.py`).

    | TC-CONFORM-06 | Integration / 3 | A divergence in score distribution; and a divergence in
    | evidence-integrity failure rate | The integrity-rate divergence is treated as a §7.4 **gate
    | failure**, not a metrics note; ordinary divergences are reported as findings. The
    | score-distribution gate's threshold is **not computable as written** — see §2.3 Q-02 and
    | §7.4; this case asserts the integrity half and records the other as a gap |

**Green, and that is not a mistake.** "Records the other as a gap" is a statement about the plan,
and the plan is a committed artifact: §2.3 raises Q-02 as a testability question, §7.4 records
the gap with its compensating controls, and the RTM row carries the same note. Those rows are
what "recorded as a gap" means — without them the untestable gate would look like coverage, and
a consumer would read a green suite as a green gate. This file asserts they are there and say
what they say; it is green exactly because the plan keeps its own record, and red the day the
gap quietly disappears — which is the failure mode §7.4's own preamble names: *"a gap that
silently disappears from a plan is indistinguishable from one that was quietly dropped"*.

**Rung 0.** No code under test — assertions over the plan's own tables, located by unique cell
text so a renumbered table cannot silently strand them.
"""

from __future__ import annotations

from tests.support.doc_tables import find_row, markdown_rows, read_repo_text

CASE = "TC-CONFORM-06"
PLAN = "docs/design/test-plan.md"


def test_tc_conform_06_the_score_distribution_gate_is_recorded_as_not_computable(repo_root):
    """§2.3 Q-02 — the question is raised, with the resolution a statistic would need.

    The row must do two things at once: state that the gate is not computable *as written*
    (otherwise the case's oracle would be a threshold that does not exist), and name what would
    retire the question — a declared statistic **and** a numeric threshold, declared **before**
    the first comparison rather than chosen after. The second half is what keeps the gap honest:
    a question with no stated resolution path is not a gap, it is a shrug.
    """
    rows = markdown_rows(read_repo_text(repo_root, PLAN))
    q02_rows = [row for row in rows if row and row[0] == "Q-02"]
    assert len(q02_rows) == 1, (
        f"expected exactly one §2.3 question row keyed Q-02, found {len(q02_rows)}; the gap "
        f"register has drifted"
    )
    row = " ".join(q02_rows[0])
    assert "fr-conform-06" in row.lower(), (
        "Q-02 no longer names FR-CONFORM-06's divergence gate; the score-distribution gate's "
        "untestability has lost its requirement"
    )
    assert "no statistic and no threshold are declared" in row.lower(), (
        "Q-02 no longer states why the gate is not computable. The gap is 'no declared statistic "
        "and no threshold' — anything vaguer would let a threshold-less implementation claim the "
        "gate was merely waiting."
    )
    assert "declared before" in row, (
        "Q-02 no longer requires the statistic to be declared before the first comparison. That "
        "ordering is the point: a threshold chosen after seeing the data is not a gate, it is a "
        "description of whatever happened."
    )


def test_tc_conform_06_the_gap_register_records_the_untestable_gate_and_its_controls(repo_root):
    """§7.4's row — the gap is managed, not hidden, and its compensating controls are named.

    Three compensating controls, and the case's own split depends on which of them exists:
    the evidence-integrity-rate half **is** computable and **is** gated (the behavioral half of
    this case), the score-distribution half is reported as a finding for human judgement, and
    build substitution — the failure a dead gate would miss — is still caught by
    `TC-CONFORM-08`'s detector. Each is named in the row; this assertion is what stops them
    being rewritten into a quieter sentence that promises less.

    The register also has to say what kind of risk it is. **Accepted**, in the table's own words
    — not managed, and not silently upgraded: a gate that cannot fire is an accepted risk until
    a statistic and threshold are declared, and a reader is owed that word.
    """
    plan = read_repo_text(repo_root, PLAN)
    gap_row = find_row(markdown_rows(plan), "the divergence gate (Q-02)")
    row = " ".join(gap_row)

    assert "no statistic and no threshold are declared, so the gate is not computable" in (
        row.lower()
    ), (
        "§7.4's gap row no longer states the score-distribution gate is not computable. A gap "
        "register that no longer says why a row is untestable is a list, not a register."
    )
    assert "is** computable and is gated" in row, (
        "the gap row no longer records which half IS computable and gated. The integrity-rate "
        "half is the testable half this case asserts; without the row saying so, the split is "
        "invisible and the gate reads as wholly dead."
    )
    assert "tc-conform-08" in row.lower(), (
        "the gap row no longer names TC-CONFORM-08 as the control that still catches build "
        "substitution. The substitution path is what survives the dead gate; dropping it from "
        "the register drops the reason the gap is accepted rather than fatal."
    )
    assert "accepted risk" in row.lower(), (
        "the gap row no longer says Accepted risk. The register's own rule is that a gap without "
        "a compensating control is accepted and says so in those words, so accepting it was a "
        "decision someone made."
    )

    # And the RTM carries the note, so a reader tracing FR-CONFORM-06 sees the gate is not
    # computable before they reach the cases — the trace is where coverage claims are made.
    rtm_row = find_row(markdown_rows(plan), "gate not computable")
    assert rtm_row[0].lower() == "fr-conform-06", (
        f"the RTM row carrying the gate-not-computable note is keyed {rtm_row[0]!r}; the note "
        f"belongs to FR-CONFORM-06"
    )
    assert "tc-conform-06" in " ".join(rtm_row).lower(), (
        "the RTM row for FR-CONFORM-06 no longer names TC-CONFORM-06, so the testable half's "
        "coverage claim has silently moved"
    )