"""`CT-CALIB-01`, `-02`, `-15` — the clauses that make `M-CALIB` removable.

Test plan §6.11.17, TS-74 (issue #142). §6.11.17's own framing:

> The only module whose contract design §4.7 marks **provisional**, and the only one deliberately
> built to be removable: `CT-CALIB-01` says it is never on the critical path and every consumer
> must remain fully functional with it **absent or disabled**. That makes the first case in this
> suite a test of the *rest of the system*, not of this module.

That is the unusual thing about this file. `TC-CALIB-C01` asserts almost nothing about
`aeh.calib`; it asserts that `M-GRADE`, `M-CONSOLE` and `M-ORCH` do not need it. So its blocker is
the **pipeline**, not a calibration story — keyed on `M-CONSOLE` (#122), the last consumer to land.

`CT-CALIB-02`'s *"every failure mode ends at R₀"* is a universal claim, so its case is an
**exhaustive sweep** over the eight failure modes §6.11.17 enumerates, not a sample. `CT-CALIB-15`
makes phasing itself contractual, and splits: the dependency refusal is `M-CALIB`'s, the
present-and-unavailable rendering is `M-CONSOLE`'s.

**All of these are red, and the issue's `Written ahead of implementation: yes` is accurate** —
`aeh.calib` does not exist, nor do three of its consumers. See the module docstring in
`test_ct_calib_vocabulary.py` for what *is* green and why it is not coverage.
"""

from __future__ import annotations

import pytest

from tests.support.impl import CALIB_MODULE, CONSOLE_MODULE, require

pytestmark = pytest.mark.contract

#: The R₀ the fixtures pin, so "ended at R₀" is checked against a value **this test** chose.
#: Comparing two fields of the run's own report passes for an implementation that reports whatever
#: rubric it happened to use, which is the assertion these cases exist to make impossible.
R0_VERSION = "pkg-v1-r0"

#: `CT-CALIB-02`, verbatim from §6.11.17: *"teacher declines to answer, teacher abandons mid-flow,
#: a gate fails, dual-scoring rejects, back-translation finds a divergence, the model cannot
#: triage, the off-panel model is unavailable, the module crashes."*
#:
#: Eight, enumerated rather than sampled, because the clause's claim is universal. A sweep that
#: covered six would leave two paths on which a revision could ship, and the clause exists
#: precisely because any one of them shipping carries construct drift into every accumulated
#: validation record (RISK-06).
FAILURE_MODES: tuple[str, ...] = (
    "teacher_declines",
    "teacher_abandons_midflow",
    "gate_fails",
    "dual_scoring_rejects",
    "back_translation_diverges",
    "triage_unavailable",
    "off_panel_model_unavailable",
    "module_crashes",
)


# --- CT-CALIB-01 — never on the critical path ---------------------------------------------------


@pytest.mark.writtenahead
def test_tc_calib_c01_grades_deliver_with_calibration_absent_and_with_it_disabled():
    """`CT-CALIB-01` — a **full-pipeline differential**, run twice: module absent, module disabled.

    This is a test of the rest of the system. `M-CALIB` is Phase 3/4 and the design built it to be
    removable; the risk it guards is RISK-11 — a Phase 3 feature acquiring the power to withhold
    grades. So the assertion is that `M-GRADE` finalizes, `M-CONSOLE` renders and `M-ORCH`
    completes in both configurations, with no reference to calibration on any path.

    **Two halves, and the second is the one that would be quiet.** Skipping calibration must grade
    the class with **R₀ unchanged** *and* mark the ambiguous criteria **lower-confidence**
    (`FR-CALIB-13`). Grading them silently at full confidence is also "grades delivered" — it looks
    identical from outside and it is the failure the clause names.

    Rung 3/4 and blocked on the **pipeline**, not on a calibration story: keyed on `M-CONSOLE`
    (#122), which depends on `M-STORE` (#10) and `M-ORCH` (#61), so resolving it means the
    consumers this case drives are all present. `M-CALIB` itself is *not* required — the case runs
    with it absent, which is the point.
    """
    console = require(CONSOLE_MODULE, issue="#122")
    run_pipeline = require(CONSOLE_MODULE, "run_pipeline_for_test", issue="#122")

    # **Absent means unimportable, not a kwarg.** An earlier draft passed `calibration=None` and
    # `calibration="disabled"` to one function — two values on one code path, which is not the
    # differential the Oracle names and which a single degenerate return value satisfies. Genuine
    # absence is `aeh.calib` not being importable at all, so the module is hidden from `sys.modules`
    # for the first run and the assertion below is that the pipeline never reached for it.
    import sys

    hidden = {name: sys.modules.pop(name) for name in list(sys.modules) if name.startswith(CALIB_MODULE)}
    sys.modules[CALIB_MODULE] = None  # an import raises rather than finding a stub
    try:
        absent = run_pipeline()
    finally:
        del sys.modules[CALIB_MODULE]
        sys.modules.update(hidden)

    disabled = run_pipeline(calibration="disabled")

    assert CALIB_MODULE not in absent.modules_imported, (
        "the pipeline imported aeh.calib on a run where calibration was absent, so the module is "
        "on the critical path after all (CT-CALIB-01, RISK-11)"
    )

    for label, outcome in (("absent", absent), ("disabled", disabled)):
        assert outcome.grades_delivered, (
            f"with calibration {label}, grades did not deliver. CT-CALIB-01: this module is never "
            "on the critical path of grade delivery (R11, R60, RISK-11)."
        )
        assert outcome.finalized, f"with calibration {label}, the batch did not finalize"
        assert outcome.rubric_version == R0_VERSION, (
            f"with calibration {label}, the class was graded against "
            f"{outcome.rubric_version!r} rather than the R₀ the fixture pinned ({R0_VERSION!r}). "
            "Comparing the run's own two fields to each other passes for an implementation that "
            "reports whatever it used."
        )
        assert outcome.lower_confidence_criteria, (
            f"with calibration {label}, no criterion was marked lower-confidence. FR-CALIB-13 "
            "requires the ambiguous criteria to be marked, and grading them silently at full "
            "confidence is the quiet failure this clause names."
        )

    assert absent.grades == disabled.grades, (
        "absent and disabled produced different grades, so one of them is on the critical path"
    )
    assert console is not None


# --- CT-CALIB-02 — every failure mode ends at R₀ -------------------------------------------------


@pytest.mark.writtenahead
@pytest.mark.parametrize("failure_mode", FAILURE_MODES)
def test_tc_calib_c02_every_failure_mode_ends_at_r0(failure_mode):
    """`CT-CALIB-02` — an **exhaustive sweep**, one row per failure mode, not a sample.

    The clause's claim is universal: *"every failure mode ends at R₀"*. Each of the eight resolves
    to the same terminal state — *grade with the rubric as given, be more conservative on the
    ambiguous criteria* (`FR-CALIB-10`).

    Parametrized rather than looped so a regression names **which** mode stopped ending at R₀. A
    single test asserting all eight reports one failure and hides the other seven.

    Then the categorical negative, asserted on every row: **no path ships a revision with a
    warning**. A warned revision is a revision — it goes live, it scores the class, and it carries
    construct drift into every accumulated validation record (RISK-06). "Shipped with a caveat" is
    the compromise this clause exists to forbid, and it is the one a reasonable implementer would
    reach for.
    """
    calib = require(CALIB_MODULE, issue="#139")
    outcome = calib.simulate_failure(failure_mode, r0=R0_VERSION)

    assert outcome.active_rubric == R0_VERSION, (
        f"{failure_mode}: the run ended on {outcome.active_rubric!r}, not the R₀ the fixture "
        f"pinned ({R0_VERSION!r}) (CT-CALIB-02, FR-CALIB-10)"
    )
    assert outcome.ambiguous_criteria_lower_confidence, (
        f"{failure_mode}: ended at R₀ but did not mark the ambiguous criteria lower-confidence — "
        "the clause's terminal state is both halves"
    )
    assert not outcome.revision_shipped, (
        f"{failure_mode}: a revision shipped anyway"
    )
    assert not outcome.shipped_with_warning, (
        f"{failure_mode}: a revision shipped carrying a warning. A warned revision is a revision "
        "— it scores the class and its results enter every accumulated validation record "
        "(RISK-06). CT-CALIB-02 forbids the path, not just the silent version of it."
    )


# --- CT-CALIB-15 — phasing is part of the contract ------------------------------------------------


@pytest.mark.writtenahead
def test_tc_calib_c15_an_edit_against_a_package_predating_the_lock_is_refused():
    """`CT-CALIB-15`, first half — the **dependency direction**, asserted rather than assumed.

    *"Triage, dual-scoring non-inferiority and back-translation are Phase 3; elicitation is Phase
    4; the §6.2 lock they depend on is Phase 1 and belongs to `M-PKG`."*

    Phasing is contractual here because the lock is what makes `CT-CALIB-06` structural: every edit
    goes through `M-PKG`, so `FR-PKG-03`'s lock applies to calibration output without `M-CALIB`
    implementing a check of its own. If calibration could run against a package version predating
    the lock, that structural guarantee evaporates and the module becomes exactly the place
    construct drift enters (RISK-06).

    So the assertion is a refusal: an edit against a pre-lock package version raises. The declared
    phase of every protocol member is asserted alongside it, so a member added without a phase —
    the thing that makes "phasing is part of the contract" untrue — is caught.
    """
    calib = require(CALIB_MODULE, issue="#138")
    apply_answers = require(CALIB_MODULE, "apply_answers", issue="#138")

    pre_lock_version = calib.package_version_predating_schema_lock()

    with pytest.raises(calib.PhaseDependencyError):
        apply_answers({"q1": "a"}, package_version=pre_lock_version)

    # The member-phase sweep used to live here and was **broken**: `apply_answers` had no entry in
    # `DECLARED_PHASES`, so this test would have failed after `M-CALIB` landed — masked until then
    # by `require()` above. It touches no implementation, so it belongs in the green file where a
    # gap is visible today: `test_ct_calib_vocabulary.py::test_every_protocol_member_has_a_declared_phase`.


@pytest.mark.writtenahead
def test_tc_calib_c15_the_console_renders_phase_4_surfaces_as_present_and_unavailable():
    """`CT-CALIB-15`, second half — the **consumer rendering rule**, and its own blocker.

    `FR-CONSOLE-25`: a Phase 4 surface is rendered **present-and-unavailable naming the version**,
    **never silently absent**. Split from the half above because it is `M-CONSOLE`'s behaviour and
    lands at #122, while the dependency refusal is `M-CALIB`'s at #138 — keying both on the later
    would hold the refusal outside the gate for no reason.

    Silently absent is the failure that looks like success: the teacher sees a console with no
    calibration in it and concludes the feature does not exist, rather than that it arrives in a
    named later version. `M-CALIB` is the only module whose contract is provisional, so it is the
    one most likely to be rendered as though it were never planned.
    """
    console = require(CONSOLE_MODULE, issue="#122")
    render = require(CONSOLE_MODULE, "render_calibration_surface", issue="#122")

    rendered = render(phase_available=3)

    assert rendered.present, (
        "the Phase 4 calibration surface is absent from the console rather than rendered "
        "present-and-unavailable (CT-CALIB-15, FR-CONSOLE-25)"
    )
    assert not rendered.available
    assert rendered.available_in_version, (
        "the surface is marked unavailable without naming the version it arrives in, so a teacher "
        "cannot tell 'later' from 'never'"
    )
    assert console is not None
