"""`CT-CONSOLE-15`, `-16`, `-17` — finalization that does not end editing, an export that cannot
leak, and a life cycle with no silent gaps.

Test plan §6.11.19, TS-77 (issue #132). All three are `FR-CONSOLE-21` … `-25`, which is **#125**
(interface invariants 15–21). What they have in common is that each guards a promise the console
makes to someone who is not in the room when it breaks:

* `-15` — the teacher who has to change a grade after it was delivered. §10's automation argument
  rests on *"the standing ability to change any grade at any time"*; a console that can only
  finalize has made finalization the end of the teacher's authority (`R69`).
* `-16` — the student whose real work would leave the building inside an exported package
  (`R71`). The console is where the export attempt is made, so the refusal is asserted here as
  well as at `M-PKG`.
* `-17` — whoever builds Phase 3 or 4 and inherits *"a labelled placeholder, not a gap"* (`R72`).

Written ahead of #125. `CT-CONSOLE-19`'s measurement half also lands on #125 and lives in
`test_ct_console_runtime_and_config.py` with the rest of the runtime clauses.
"""

from __future__ import annotations

import pytest

from tests.support.console_vocabulary import (
    MVP_ABSENT_TOUCHPOINT,
    TEACHER_TOUCHPOINTS,
    visible_text,
)
from tests.support.impl import CONSOLE_MODULE, require

pytestmark = pytest.mark.contract


# --- CT-CONSOLE-15 — finalization does not end editing ---------------------------------------------


@pytest.mark.writtenahead
def test_tc_console_c15_an_amendment_preserves_finalized_at_and_writes_a_new_revision():
    """`FR-CONSOLE-21` — three assertions, because the partial implementation is the plausible one.

    *"An amendment path exists, preserves `finalized_at`, and writes a new grade revision rather
    than mutating the delivered one."* §6.11.19 names the trap directly: **preserving the row while
    overwriting the timestamp** is what a reasonable implementer writes. It looks like an
    amendment, the grade changes, and the record of when the batch was delivered is gone — so a
    later dispute cannot establish what was delivered or when.

    All three are asserted separately, and the revision assertion is a **differential**: the
    superseded revision must still be readable afterwards, not merely a different object. An
    implementation that returns a new object while updating the same row satisfies "writes a new
    revision" by identity and has still destroyed the delivered grade.
    """
    amend = require(CONSOLE_MODULE, "amend_finalized_grade", issue="#125")
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    app = build_console()
    delivered = app.finalize_batch(run_id="r-1")["s-0007"]
    assert delivered.finalized_at is not None, "the batch did not finalize, so there is nothing to amend"

    amended = amend(app, submission_ref="s-0007", criterion_id="c3", new_band="met")

    assert amended.finalized_at == delivered.finalized_at, (
        f"the amendment moved finalized_at from {delivered.finalized_at} to "
        f"{amended.finalized_at}. FR-CONSOLE-21 preserves it: the timestamp records when the batch "
        f"was delivered, and an amendment is a later correction, not a re-delivery."
    )
    assert amended.revision != delivered.revision, (
        "the amendment did not write a new grade revision"
    )

    superseded = app.grade_revision(submission_ref="s-0007", revision=delivered.revision)
    assert superseded is not None and superseded.bands == delivered.bands, (
        "the delivered revision is no longer readable after the amendment, so the new revision "
        "mutated it rather than superseding it — which is the failure that looks correct from "
        "every angle except a dispute"
    )


@pytest.mark.writtenahead
def test_tc_console_c15_a_review_window_delays_finalization_and_never_withholds_a_grade():
    """`FR-CONSOLE-22` — the console-side guard on RISK-11.

    *"A configured review window shall delay finalization and never withhold a grade; provisional
    grades shall export normally throughout it."* Two claims that a single implementation can split
    apart, so both are asserted with the window **open**:

    - finalization is delayed — `finalized_at` is still unset;
    - and every grade is nonetheless present, complete, and exportable.

    The second is the one RISK-11 is about. A window that withheld grades until it lapsed would be
    a Phase 1 feature that had acquired the power to stop grade delivery, which is the risk the
    whole design is arranged to prevent — and it would look like correct behaviour to whoever built
    it, because "the window has not closed yet" is a reason.
    """
    amend = require(CONSOLE_MODULE, "amend_finalized_grade", issue="#125")
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    app = build_console()
    app.set_review_window(run_id="r-1", hours=24)
    state = app.finalize_batch(run_id="r-1")

    assert all(grade.finalized_at is None for grade in state.values()), (
        "the review window did not delay finalization, so setting one has no effect"
    )

    exported = app.export_grades(run_id="r-1")
    assert len(exported) == len(state) and exported, (
        f"{len(state) - len(exported)} grades were withheld while the review window was open. "
        f"FR-CONSOLE-22: the window delays finalization and never withholds a grade (RISK-11)."
    )
    assert all(row.provisional for row in exported), (
        "grades exported during an open window are not marked provisional, so a reader cannot "
        "tell a delivered grade from one still inside its window"
    )
    assert amend is not None


# --- CT-CONSOLE-16 — the export gate ------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_console_c16_export_refuses_a_package_carrying_real_student_text():
    """`FR-CONSOLE-23` / `R71` — asserted **at the console boundary**, where the attempt is made.

    `CT-PKG-13` asserts the same refusal inside `M-PKG`, and both cases stay. The console is where
    a teacher clicks export, and a console that filtered, warned or silently dropped the flag
    before calling `M-PKG` would leave `M-PKG`'s refusal never exercised on the real path — the
    guarantee would hold in a test and not in the building.

    The refusal is asserted as an **exception**, not as a falsy return: an export that returns
    `None` and writes nothing is indistinguishable, from the teacher's side, from one that
    succeeded quietly.
    """
    export = require(CONSOLE_MODULE, "export_package", issue="#125")
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")
    ProvenanceRefused = require(CONSOLE_MODULE, "ProvenanceRefused", issue="#125")

    app = build_console()
    with pytest.raises(ProvenanceRefused):
        export(app, package_version="pkg-v1", contains_real_student_text=1)

    # And the same call succeeds once the flag is clear, so the refusal above is the provenance
    # gate rather than an export that is broken for an unrelated reason.
    assert export(app, package_version="pkg-v1", contains_real_student_text=0) is not None


@pytest.mark.writtenahead
def test_tc_console_c16_the_provenance_gate_is_a_reachable_screen_and_records_its_outcome():
    """`FR-CONSOLE-23`'s other two halves — *"a reachable screen"*, and an outcome that is written.

    An internal check satisfies "export cannot emit real student text" and satisfies nothing else.
    The clause asks for a **screen**, because the decision is the teacher's: exemplar paraphrases
    are approved at export, and approving them is a judgment about somebody's work leaving the
    building. And it asks for the outcome to reach the validation record, so a later reader can see
    the gate ran — *"a gate whose result is not recorded is indistinguishable from one that was
    skipped"* is the same reasoning `CT-CONFORM-13` uses about resolved builds.
    """
    export = require(CONSOLE_MODULE, "export_package", issue="#125")
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    app = build_console()
    routes = {route for routes in app.routes().values() for route in routes}
    gate_routes = [route for route in routes if "provenance" in route or "export" in route]
    assert gate_routes, (
        f"no route reaches the provenance gate; the console's routes are {sorted(routes)}. "
        f"FR-CONSOLE-23 requires a reachable screen, not an internal check."
    )

    rendered = app.render(gate_routes[0], package_version="pkg-v1")
    assert visible_text(rendered.html).strip(), "the provenance gate screen renders nothing"

    export(app, package_version="pkg-v1", contains_real_student_text=0)
    record = app.validation_record(package_version="pkg-v1")
    assert record.provenance_gate_outcome is not None, (
        "the provenance gate ran and wrote no outcome to the validation record, so a later reader "
        "cannot tell it from a gate that was skipped (R71)"
    )


# --- CT-CONSOLE-17 — no touchpoint silently absent -----------------------------------------------------


@pytest.mark.writtenahead
def test_tc_console_c17_every_teacher_touchpoint_is_implemented_or_labelled_present_and_unavailable():
    """`FR-CONSOLE-25` / `R72` — an **enumerated** sweep over HLD §7.9's twelve rows.

    §6.11.19: *"enumerated against §7.9 rather than sampled"*, and *"the case fails on a missing
    route as loudly as on a broken one"*. Both halves matter and they fail differently:

    - a touchpoint the MVP implements must be **implemented**;
    - a touchpoint it does not must be **present and unavailable, naming the version it arrives
      in** — not absent.

    The clause's stated benefit is the assertion: someone building Phase 4 inherits *"a labelled
    placeholder, not a gap"*. And the teacher's side is worse than the builder's — HLD §11.2 is
    explicit that *"an absent step reads as one they skipped by accident"*. A teacher who was told
    the system would ask about their own marking, and finds no such step, concludes they missed it.

    Exactly one row takes the second branch (`MVP_ABSENT_TOUCHPOINT`), which is what keeps this
    from being satisfiable by a console that implements everything and has no placeholder
    mechanism at all — asserted in `test_ct_console_vocabulary.py`, green today.
    """
    # #125's symbol first: this case is registered against #125, and `require()` reports whichever
    # blocker it reaches first. Naming #122 on a test that #122 landing does not unmark is how a
    # gate stops being believed.
    touchpoints = require(CONSOLE_MODULE, "touchpoint_surface", issue="#125")
    build_console = require(CONSOLE_MODULE, "build_console", issue="#122")

    rendered = touchpoints(build_console())

    missing = [name for name in TEACHER_TOUCHPOINTS if name not in rendered]
    assert not missing, (
        f"these §7.9 touchpoints are silently absent from the console: {missing}. R72 forbids "
        f"exactly this — an absent step reads to the teacher as one they skipped by accident, and "
        f"to a Phase 4 builder as a gap rather than a placeholder."
    )

    for name in TEACHER_TOUCHPOINTS:
        surface = rendered[name]
        if name == MVP_ABSENT_TOUCHPOINT:
            assert not surface.implemented, (
                f"{name!r} is implemented, but HLD §11.2 places Stage B elicitation in Phase 4. If "
                f"that has changed, this suite's fixture is stale rather than this console wrong."
            )
            assert surface.present and not surface.available, (
                f"{name!r} is not rendered present-and-unavailable — it is simply not there"
            )
            assert surface.available_in_version, (
                f"{name!r} is marked unavailable without naming the version it arrives in, so a "
                f"teacher cannot tell 'later' from 'never'"
            )
        else:
            assert surface.implemented and surface.available, (
                f"{name!r} is a Phase 1 touchpoint and the console does not implement it"
            )
