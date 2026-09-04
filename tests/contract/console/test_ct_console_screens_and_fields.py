"""`CT-CONSOLE-07`, `-08` and `-09` — the three invariants HLD §11.6 says will be argued against.

Test plan §6.11.19, TS-76 (issue #131). §11.6 singles these out by name: *"Invariants 1, 2, 3 and 7
deserve emphasis because each will be argued against by a reasonable person during the first week
of use. A per-student progress bar will be requested and cannot honestly be built. A numeric entry
box will feel faster to the teacher and reintroduces the bias §5.10 exists to remove. An extra
blocking confirmation will feel safer and is exactly how R60 erodes."*

That paragraph is the reason all three are asserted as **exhaustive sweeps** rather than as spot
checks. Each will be eroded by one screen at a time, by somebody with a good argument, and a
sampled assertion is one that agrees with them until the sample happens to land on the new screen.

* `-07` — exactly two screens block, counted against the route table, and every other prompt
  renders a skip control **and its cost in the same view**.
* `-08` — no numeric score entry field anywhere, and the completeness half: wherever a band is
  displayed it is editable.
* `-09` — no per-student progress indicator, swept over routes **and API payloads**.

Keyed on **#123** (`-07`, `-09`: `FR-CONSOLE-06`, `-08`) and **#125** (`-08`, whose completeness
half is `FR-CONSOLE-20` and lands with invariants 15–21). Every name is invented; the surface is
settled in `console_vocabulary` and `console_security_vocabulary`.
"""

from __future__ import annotations

import pytest

from tests.support.console_security_vocabulary import (
    BLOCKING_SCREENS,
    PROGRESS_DIMENSIONS,
    PROGRESS_REPORT_FIELDS,
    editable_band_controls,
    numeric_score_entry_fields,
    per_student_progress_figures,
)
from tests.support.console_vocabulary import elements, visible_text
from tests.support.impl import CONSOLE_MODULE, require
from tests.support.store_spy import StoreSpy

pytestmark = pytest.mark.contract


# --- CT-CONSOLE-07 — two screens block, and every other prompt states its cost -------------------


@pytest.mark.writtenahead
def test_tc_console_c07_exactly_two_screens_block_and_they_are_s3_and_s4():
    """`CT-CONSOLE-07` / `FR-CONSOLE-06` — a count **and** an identity.

    The count alone is not enough. A console where three screens block and one of them is S3 fails
    the count; a console where two block and neither is S3 passes it and has moved the gate. `R60`'s
    test is the one that matters — *"could a teacher start a run, do nothing at all, and still have
    every student graded the next morning?"* — and both failures make the answer no.

    Asserted against the console's own enumeration rather than against §11.5, because `CT-SETUP-01`
    says the blocking set is enumerable at runtime *"so `CT-CONSOLE-07`'s count is asserted against
    setup rather than hard-coded in the UI"*. The transcription check that keeps §11.5 and the
    fixture in step is in the vocabulary file.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#123")

    app = build_console(store=StoreSpy())
    blocking = set(app.blocking_screens())

    assert blocking == BLOCKING_SCREENS, (
        f"the console blocks on {sorted(blocking)}; §11.5 marks {sorted(BLOCKING_SCREENS)}. "
        f"Extra: {sorted(blocking - BLOCKING_SCREENS)}. Missing: "
        f"{sorted(BLOCKING_SCREENS - blocking)}. An extra blocking confirmation 'will feel safer "
        f"and is exactly how R60 erodes' (HLD §11.6); a missing one means a package can be "
        f"published without its question inventory confirmed."
    )
    assert set(blocking) <= set(app.screens()), (
        "a blocking screen is not in the route table, so the count CT-CONSOLE-07 says is "
        "'assertable against the route table' is being made against something else"
    )


@pytest.mark.writtenahead
def test_tc_console_c07_every_skippable_prompt_renders_the_skip_and_its_cost_in_one_view():
    """The half that is easy to half-implement, and §6.11.19 says so.

    *"A skip control whose consequence is explained on another page is the design HLD `R62`
    rejects."* So the assertion is **same view**, not "both exist somewhere": the two are read
    together or the cost is not informing the decision.

    `FR-SETUP-14` is what makes the cost renderable at all — *"every non-blocking setup step … shall
    record in the package that the default was taken rather than leaving the state
    indistinguishable from an explicit choice"* — so a console that cannot state the cost is
    reading a store that does not know it was skipped.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#123")

    app = build_console(store=StoreSpy())
    failures: list[str] = []
    prompts_seen = 0

    for screen, route in app.screens().items():
        if screen in BLOCKING_SCREENS:
            continue
        page = app.render(route)
        if not elements(page.html, "prompt"):
            continue
        prompts_seen += 1
        skips = elements(page.html, "skip")
        # **The existence half.** Skipping this screen when it has no skip control at all would
        # let a console with none anywhere pass — only malformed controls would ever be condemned,
        # and "every other prompt renders a first-class skip control" is the requirement.
        if not skips:
            failures.append(f"{screen} ({route}) prompts for something and offers no skip control")
            continue
        for index, control in enumerate(skips):
            text = visible_text(control).lower()
            if not any(marker in text for marker in ("skip", "not now", "use the default")):
                failures.append(f"{screen}: skip control {index} has no skip affordance")
            if not any(
                marker in text
                for marker in ("cost", "if you skip", "means", "default", "instead", "without this")
            ):
                failures.append(
                    f"{screen}: skip control {index} states no cost in its own view — {text!r}"
                )

    assert prompts_seen >= 3, (
        f"only {prompts_seen} non-blocking prompt(s) were found, so this sweep asserted almost "
        f"nothing. §7.9's inventory has ten non-blocking touchpoints and HLD §11.5's S5 alone "
        f"carries three optional setup cards."
    )
    assert not failures, (
        f"{failures}. R62's design is that the cost of skipping is read at the moment of skipping; "
        f"a link to an explanation is the version it rejects."
    )


# --- CT-CONSOLE-08 — no numeric score field, and no grade that cannot be changed -----------------


@pytest.mark.writtenahead
def test_tc_console_c08_no_route_anywhere_offers_a_numeric_score_entry_field():
    """`CT-CONSOLE-08` / `FR-CONSOLE-07` — *anywhere*, so the sweep is every route.

    §6.11.19 names the loophole: *"the clause says anywhere and the loophole would be a secondary
    screen"*. The review queue is where anyone would look, so it is where the field will not be —
    and S13 or an export preview is where it will.

    `R39`'s reason is that a numeric box is not a faster band selection, it is a different act: *"a
    judge that can see a 0..5 scale reasons on it whatever it is asked to emit"*, and the same is
    true of a teacher. §5.10 removes the scale from the interface for that reason, and one text box
    puts it back.

    The rule this calls is deliberately narrow: a correct console is **full** of numeric inputs —
    the minutes budget, the review window, a cohort size — and its control asserts every one of
    them passes.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#123")

    app = build_console(store=StoreSpy())
    offenders: list[str] = []
    fields_seen = 0
    for screen, route in app.screens().items():
        html = app.render(route).html
        fields_seen += html.count("<input") + html.count("<select") + html.count("<textarea")
        for field in numeric_score_entry_fields(html):
            offenders.append(f"{screen} ({route}) offers {field!r}")

    assert fields_seen, (
        "no route rendered a form control of any kind, so a sweep for a forbidden control passed "
        "over pages that have no controls. S3, S4, S5 and S9 are all forms."
    )
    assert not offenders, (
        f"{offenders}. FR-CONSOLE-07: all score edits are band selections, and FR-REVIEW-10 says "
        f"`new_points` is derived from `new_band` via the pinned mapping — a typed number has no "
        f"band to derive from."
    )


@pytest.mark.writtenahead
def test_tc_console_c08_every_route_that_shows_a_grade_shows_it_as_an_editable_band():
    """`FR-CONSOLE-20` / invariant 16 — the completeness half, and the one that keeps the first
    half honest.

    *"There is no view that shows a grade and cannot change it."* §6.11.19 gives the mechanism:
    a read-only grade view *"becomes the place teachers work around the band interface"*, which is
    how the numeric box comes back after being removed. `FR-REVIEW-15` is the same requirement from
    the other side — review actions are available *"from any view that displays a band, not only
    from within the budgeted queue"*.

    Keyed on **#125** rather than #123: `FR-CONSOLE-20` is invariant 16 and lands with that story,
    and a test keyed on the earlier one would be unmarked while the surface it sweeps did not exist.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#125")

    app = build_console(store=StoreSpy())
    failures: list[str] = []

    grade_views = 0
    for screen, route in app.screens().items():
        html = app.render(route).html
        displayed = elements(html, "band") + elements(html, "grade")
        if not displayed:
            continue
        grade_views += 1
        if not editable_band_controls(html):
            failures.append(f"{screen} ({route}) displays a band and offers no way to change it")

    assert grade_views >= 2, (
        f"only {grade_views} route(s) displayed a band or a grade, so 'wherever a band is "
        f"displayed' swept almost nothing. S9, S12 and S13 all display one."
    )
    assert not failures, (
        f"{failures}. A disabled select or a rendered label is not an editable band control — "
        f"which is precisely the shape a read-only view takes."
    )


# --- CT-CONSOLE-09 — no per-student progress, rendered or merely available -----------------------


@pytest.mark.writtenahead
def test_tc_console_c09_no_route_or_payload_carries_a_per_student_progress_figure():
    """`CT-CONSOLE-09` / `FR-CONSOLE-08` — swept over **payloads** as well as routes.

    §6.11.19 names the realistic failure and it is not a rendering: *"a per-student figure
    available in a payload and merely unrendered"*. A console that computes it and does not draw it
    has already taken the decision; the next release draws it, and nothing in the diff looks like a
    contract change.

    The rule permits S13. `/students/{ref}` is a declared teacher route and Student detail is a
    screen in §11.5, so a per-student *value* is legal — what `R63` forbids is a per-student
    *progress* figure during a run, and its control asserts S13's payload passes.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#123")

    app = build_console(store=StoreSpy())
    offenders: list[str] = []
    payloads_seen = 0

    for screen, route in app.screens().items():
        payload = app.api_payload(route)
        if payload is None:
            continue
        payloads_seen += 1
        for path in per_student_progress_figures(payload):
            offenders.append(f"{screen} ({route}) serves {path}")

    assert payloads_seen, (
        "no route served a payload at all, so this sweep asserted nothing. §6.11.19 sweeps 'every "
        "route and every API response the console serves'."
    )
    assert not offenders, (
        f"{offenders}. HLD §11.6: 'a per-student progress bar will be requested and cannot "
        f"honestly be built' — it cannot, because a unit's state says nothing about when the "
        f"student's grade will exist."
    )


@pytest.mark.writtenahead
def test_tc_console_c09_progress_renders_at_the_three_dimensions_and_derives_nothing_more():
    """*"Exactly what `M-ORCH` exposes and nothing more"* — so the ceiling is asserted, not only
    the floor.

    Two directions. The console must render the three dimensions `CT-ORCH-10` provides, and it must
    not render a **fourth** figure of its own. The second is what makes this a clause case rather
    than a restatement of `CT-ORCH-10`: `ProgressReport` carrying no per-student field makes
    `CT-CONSOLE-09` structural, and the only way left to break it is for the console to derive
    something. A per-submission percentage computed in a template is exactly that.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#123")

    app = build_console(store=StoreSpy())
    report = app.progress(run_id="r-1")
    fields = set(report)

    assert not (fields - PROGRESS_REPORT_FIELDS), (
        f"the console's progress report carries {sorted(fields - PROGRESS_REPORT_FIELDS)}, which "
        f"CT-ORCH-10 does not expose. 'Nothing more' is the clause's own wording, and a derived "
        f"figure is the only way left to break invariant 3 once the report has no per-student "
        f"field."
    )
    assert PROGRESS_REPORT_FIELDS - fields <= {"escalation_rate_so_far", "estimated_completion"}, (
        f"the report is missing {sorted(PROGRESS_REPORT_FIELDS - fields)}; the four totals and the "
        f"keyed counts are what a run monitor is for"
    )
    for row in report.get("counts", ()):
        assert set(PROGRESS_DIMENSIONS) <= set(row), (
            f"a progress row is keyed by {sorted(set(row) & set(PROGRESS_DIMENSIONS))} rather than "
            f"by (stage, criterion, judge): {row!r}"
        )
    assert per_student_progress_figures(report) == [], (
        "the progress report itself carries a per-student figure"
    )
