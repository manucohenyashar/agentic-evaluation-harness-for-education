"""`TC-CONFORM-07` — the CI configuration wires the conformance suite, in both directions.

Case: test plan §5.18, `FR-CONFORM-07`, `NFR-SYS-06`, R28. Oracle: **CI configuration
assertion**, at rung 0 — there is no code under test at all, only the configuration the suite
is wired through.

    | The CI configuration and the test-tier definitions | The suite runs on every panel or
    | model change; the fast tier uses the recorded-fixture provider and needs no live model;
    | the full 23,000-call batch does **not** run per commit |

**Where this repo's CI configuration lives.** `.github/workflows/` holds two deliberately
`.disabled` files and `CLAUDE.md` states GitHub runs no agents here — so the wiring is written
down in exactly two places: test plan §4.7's suite table (one row per suite, with its command
and its trigger) and `scripts/test.sh`, which is what `TEST_CMD` and the Stop hook actually
run. That is the settled reading TS-75's `TC-CONFORM-C08` already asserts its clause against,
and this case asserts the same configuration against the **requirement's** three clauses
rather than the clause's own phrasing.

**Green, and that is not a mistake.** The issue says a red suite is expected; that holds for
the seven cases that wait on #134's run machinery. This case is Phase 1 and rung 0 — an
assertion about committed configuration, green exactly because the configuration is what
`FR-CONFORM-07` requires. A red one would mean the tiers drifted, not that code is missing.

**Overlap with TS-75's `TC-CONFORM-C08`, stated rather than hidden.** Both cases assert the
tier wiring, and `test_tc_conform_c08_the_configuration_keeps_the_full_suite_off_the_per_
commit_tier` runs the same controlled rule. They are two P0 rows in the RTM against one
configuration, and the overlap is the point: `FR-CONFORM-07` is the requirement, `CT-CONFORM-08`
is its clause, and a regression that slips past one detector's framing is caught by the other.
This file asserts what the §5.18 case adds — the fast tier's **provider** wiring (the recorded
double is pinned by name, and the plan declares the architecture in `FR-CONFORM-07`'s own
words), the E1 environment row, the §4.10 companion-real-test row, and the RTM trace — over the
shared `tier_wiring_problems` rule, whose controls run green in
`test_ct_conform_vocabulary.py` so a rule that stopped firing cannot masquerade as coverage.
"""

from __future__ import annotations

from tests.support.conform_vocabulary import tier_wiring_problems
from tests.support.doc_tables import find_row, markdown_rows, read_repo_text
from tests.support.impl import FIXTURE_PROVIDER_CLASS

CASE = "TC-CONFORM-07"
PLAN = "docs/design/test-plan.md"
TEST_SH = "scripts/test.sh"


def test_tc_conform_07_the_conformance_suite_is_wired_to_panel_and_model_changes(repo_root):
    """Clause 1 — *the suite runs on every panel or model change* — and clause 3's trigger half.

    The wiring is read through `tier_wiring_problems`, the controlled rule TS-75 settled:
    it locates the row **by the command** (`harness.conform`) rather than by the row's prose
    name, requires the trigger to name a change condition and to cite `FR-CONFORM-07`, refuses
    a per-commit wiring, and requires the duration budget that makes the run a gate rather
    than an advisory job (§6.11.18's own reading of the same table). Every rule fires by name
    in the vocabulary controls; a rule that silently stopped would be caught there, not here.
    """
    problems = tier_wiring_problems(
        read_repo_text(repo_root, PLAN), read_repo_text(repo_root, TEST_SH)
    )
    assert problems == [], (
        f"the conformance tier wiring has drifted: {problems}. FR-CONFORM-07 is a constraint "
        f"on §4.7's table, not a suggestion — the suite runs on every panel or model change "
        f"and never per commit."
    )

    # The configuration states its own rule. §4.7 closes with the sentence that makes the
    # table's shape load-bearing rather than incidental; deleting it would leave the table
    # free to drift back to a per-commit batch with no rule naming the drift.
    plan = read_repo_text(repo_root, PLAN)
    assert "fr-conform-07` is a constraint on this table, not a suggestion" in " ".join(
        plan.lower().split()
    ), (
        "§4.7 no longer states that FR-CONFORM-07 constrains the suite table. The requirement's "
        "wiring half is that sentence; without it the rows above are an intention, which is the "
        "word this case will not accept."
    )

    # The RTM row still traces this case to FR-CONFORM-07 — the case's own trace, asserted so
    # the coverage claim survives renumbering. Located by its first cell: the §5.18 case row
    # starts with the TC id, and no other table row starts with the requirement id.
    rtm_rows = [
        row for row in markdown_rows(plan) if row and row[0].lower() == "fr-conform-07"
    ]
    assert len(rtm_rows) == 1, (
        f"expected exactly one traceability row keyed {CASE}'s requirement, found "
        f"{len(rtm_rows)}; the RTM has drifted"
    )
    assert any("tc-conform-07" in cell.lower() for cell in rtm_rows[0]), (
        "the RTM row for FR-CONFORM-07 no longer names TC-CONFORM-07, so the requirement's "
        "coverage claim has silently moved"
    )


def test_tc_conform_07_the_fast_tier_uses_the_recorded_fixture_provider_and_needs_no_live_model(
    repo_root,
):
    """Clause 2 — the fast tier's model boundary is the recorded double, and no live model.

    Three places carry this wiring, and all three are asserted because each answers a
    different reading of the clause:

    * **The pin** — `FIXTURE_PROVIDER_CLASS` names `RecordedFixtureProvider`, and the harness
      self-test (`test_fast_tier_binds_the_recorded_fixture_provider`) exercises that the
      fast tier's factory really resolves it. That test runs in this tier and is green; this
      case cross-references the pin it binds rather than re-asserting the wiring.
    * **The declared architecture** — §4.2's own sentence: `NFR-SYS-06` and `FR-CONFORM-07`
      make the no-live-model fast tier and the smaller nightly live tier *the declared
      architecture*. Deleting that sentence would leave the provider pin pointing at nothing.
    * **The environment** — §4.5's E1 row is the fast tier's composition, and it says both
      halves explicitly: the recorded provider in its composition, *No live model* in its
      differences column.

    The full pipeline per backend is the live counterpart of the fast tier's recorded double —
    §4.10's double table names `TC-CONFORM-04` as the companion real test — which is what makes
    the tier split a measurement boundary rather than a convenience: the fast tier measures
    through the double, the change-triggered suite measures the real thing.
    """
    assert FIXTURE_PROVIDER_CLASS == "RecordedFixtureProvider", (
        f"the fast tier's model boundary is pinned to {FIXTURE_PROVIDER_CLASS!r}; FR-CONFORM-07 "
        f"requires the recorded-fixture provider (§4.2: a shipped implementation, not a test "
        f"fake). The binding that self-test exercises has been renamed."
    )

    plan = " ".join(read_repo_text(repo_root, PLAN).split())
    assert (
        "NFR-SYS-06` and `FR-CONFORM-07` make this the declared architecture: a fast tier "
        "needing no live model, and a smaller nightly tier making live calls"
    ) in plan, (
        "§4.2 no longer declares the two-tier architecture in FR-CONFORM-07's name. The fast "
        "tier's recorded provider would then be an accident of the markers rather than the "
        "declared boundary."
    )

    # The live counterpart is wired in the double table: the recorded double's companion real
    # test for the conformance suite is the full-pipeline-per-backend case, nightly. A fast
    # tier with no named live counterpart has no measurement the double could be drifting
    # from — which is RISK-37's exposure, not the architecture FR-CONFORM-07 declares. The
    # row is keyed by the double's real counterpart ("Local model server"), and this case's
    # own claim is the companion cell naming the live conformance case.
    double_row = find_row(markdown_rows(read_repo_text(repo_root, PLAN)), "Local model server")
    companion = " ".join(double_row)
    assert "tc-conform-04" in companion.lower() and "full pipeline per backend" in companion, (
        "§4.10's double table no longer names TC-CONFORM-04 as the recorded provider's "
        "companion real test. The fast tier's conformance coverage would then have no live "
        "half to catch the double drifting from the backend it stands in for (RISK-37)."
    )

    e1_row = find_row(markdown_rows(read_repo_text(repo_root, PLAN)), "E1 — developer laptop")
    row_text = " ".join(e1_row).lower()
    assert "recordedfixtureprovider" in row_text.replace(" ", "").replace("`", ""), (
        "the CI fast tier's environment row no longer composes RecordedFixtureProvider, so the "
        "boundary the tier runs under is no longer the declared one"
    )
    assert "no live model" in row_text, (
        "the CI fast tier's environment row no longer says no live model. FR-CONFORM-07 sizes "
        "the fast tier so it needs none; an environment row that admits one is the tier quietly "
        "growing a dependency the markers were supposed to keep out."
    )


def test_tc_conform_07_the_full_batch_does_not_run_per_commit(repo_root):
    """Clause 3 — the ~23,000-call batch is not wired into any per-push suite.

    Asserted over the rows, not over one phrase: the conformance command appears in exactly
    one §4.7 row, and that row's trigger is a change condition — so no amount of rewording the
    trigger cell can put the batch on the per-commit path without this going red. The per-push
    rows are swept as a set, since a second row carrying the command would be the batch back
    on every commit under a different suite's name.
    """
    rows = markdown_rows(read_repo_text(repo_root, PLAN))
    conformance_rows = [row for row in rows if any("harness.conform" in c for c in row)]
    assert len(conformance_rows) == 1, (
        f"the conformance command appears in {len(conformance_rows)} §4.7 rows; FR-CONFORM-07 "
        f"wires the batch to exactly one trigger"
    )
    trigger = " ".join(conformance_rows[0]).lower()
    assert "every push" not in trigger and "every commit" not in trigger and (
        "per commit" not in trigger
    ), (
        "the ~23,000-call conformance batch is wired to a per-commit trigger. FR-CONFORM-07 "
        "sizes the tiers so the fast tier carries the per-commit work; the batch gates a "
        "change, not a push."
    )

    per_push_with_batch = [
        row
        for row in rows
        if any("harness.conform" in c for c in row) and "every push" in " ".join(row).lower()
    ]
    assert not per_push_with_batch, (
        f"a per-push suite row carries the conformance batch: {per_push_with_batch}. The full "
        f"23,000-call batch must not run per commit (FR-CONFORM-07)."
    )