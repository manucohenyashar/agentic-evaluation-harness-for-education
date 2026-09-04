"""The green half of TS-76: does the fixture still match the design, and do the rules still fire?

**None of this is coverage of a `CT-CONSOLE` clause.** All twelve of `-C01` … `-C12` are
behaviourally red behind `writtenahead`, waiting on four stories (#122, #123, #125, #126). What
runs here is what they stand on:

* the **transcription** — HLD §9.9's `ScoringRequest` leaves, §11.8's Effect column at field
  granularity, §11.5's thirteen screens and the two that block, `CT-ORCH-10`'s progress shape —
  each checked against the document it was copied from;
* the **rules** — numeric-score entry, editable bands, external origins, browser storage,
  per-student progress, provenance, the agreement block and query reachability — each checked
  against markup a *correct* console renders as well as against the violation.

The second direction is where the work is, and in this suite it is unusually easy to get wrong.
A correct console is **full** of numeric inputs (HLD §10's queue is budgeted in minutes), **has** a
per-student screen (S13, `/students/{ref}`), and **does** load a stylesheet, a font and an image.
Each of those is condemned by the obvious version of the rule beside it, so each has a control.

One test here is not a control but a **finding**: `test_the_literal_clause_is_unsatisfiable_and_the
_hld_scopes_it` asserts that `CT-CONSOLE-04`'s intersection is non-empty when read literally
against §11.8's own table, and that the two sentences the scoping rests on are still in the HLD. It
should be deleted the day the clause is rewritten.
"""

from __future__ import annotations

import re

import pytest

from tests.support import broken_console_security_fixtures as fixtures
from tests.support.console_security_vocabulary import (
    AGREEMENT_LEVELS,
    BLOCKING_SCREENS,
    CHANCE_CORRECTED_STATISTICS,
    CLOUD_HOSTED_PROFILE,
    CONSOLE_WRITE_FIELDS,
    LOOPBACK_ADDRESSES,
    NO_NEW_VALIDATION_EVIDENCE,
    NO_VALIDATION_FOR_POPULATION,
    OPERATOR_SCREENS,
    PRE_LOCK_ACTIONS,
    PROGRESS_DIMENSIONS,
    PROGRESS_REPORT_FIELDS,
    PROVENANCE_FIELDS,
    QUARANTINE_STATES,
    REFUSAL_SWEEP_SETTINGS,
    REPLAY_ROUTES,
    SCORING_PROMPT_FIELDS,
    SCREENS,
    STALE_STATE_OUTCOMES,
    agreement_block_problems,
    browser_storage_writes,
    editable_band_controls,
    external_origins,
    grade_views_missing_provenance,
    numeric_score_entry_fields,
    per_student_progress_figures,
    post_lock_write_fields,
    queries_reaching,
    replayed_writes_are_idempotent,
)
from tests.support.console_vocabulary import CONTROL_SURFACE_ACTIONS, ROUTABLE_BIND
from tests.support.doc_tables import read_repo_text

pytestmark = pytest.mark.contract

DESIGN = "docs/design/detailed-design.md"
HLD = "docs/agentic-evaluation-harness-for-education.md"


def _normalized(repo_root, relative: str) -> str:
    """A document with its line wrapping removed, lower-cased.

    Every transcription check below is a substring match against prose, and the design documents
    wrap mid-sentence — TS-75 lost two green tests to exactly that before normalizing.
    """
    return " ".join(read_repo_text(repo_root, relative).lower().split())


# --- the transcriptions -------------------------------------------------------------------------


def test_the_scoring_prompt_fields_are_hld_9_9_s_own_leaves(repo_root):
    """`CT-CONSOLE-04` compares against a **complete** field set, so it must stay complete.

    §6.11.19 says the empty intersection is *"stronger than sampling prompts"* — and it is only
    stronger if both sides are whole. A field added to `ScoringRequest` and not here would make the
    intersection empty for the wrong reason, which is the vacuity TS-57 shipped.

    `CT-JUDGE-02` is what makes the comparison legitimate rather than a snapshot: the schema is a
    **closed whitelist**, so *"adding a field is a schema change, not a call-site change"*. This
    test is the console-side half of that promise: the schema changed, and this fixture did not.
    """
    hld = read_repo_text(repo_root, HLD)
    start = hld.find("// ScoringRequest")
    assert start != -1, (
        "HLD §9.9's ScoringRequest block is gone. CT-CONSOLE-04's intersection is computed against "
        "it, so the fixture below is no longer anchored to anything."
    )
    block = hld[start : hld.find("```", start)]

    # The leaves, by their JSON keys. Nested names are checked as the last segment, because that is
    # what appears in the document.
    for field in sorted(SCORING_PROMPT_FIELDS):
        leaf = field.split(".")[-1]
        assert f'"{leaf}"' in block, (
            f"the fixture claims a scoring prompt reads {field!r}, but §9.9's ScoringRequest no "
            f"longer declares {leaf!r}. Either the schema changed or the transcription drifted, "
            f"and CT-CONSOLE-04's intersection is wrong either way."
        )

    # And the other direction: a *new* leaf in the schema that the fixture does not carry.
    declared = {match for match in re.findall(r'"([a-z_]+)"\s*:', block)}
    ignored = {"band", "descriptor", "start", "end", "text", "spans", "criterion", "question",
               "evidence", "bands", "exemplars"}
    known = {field.split(".")[-1] for field in SCORING_PROMPT_FIELDS} | ignored
    assert not (declared - known), (
        f"§9.9 declares {sorted(declared - known)} and the fixture does not carry them. A field "
        f"the prompt reads and the intersection does not know about is a contamination channel "
        f"CT-CONSOLE-04 would report as clean."
    )

    # **A named floor, because leaf-name comparison cannot see a dropped dotted field.**
    # `criterion.text` and `criterion.exemplars.text` share the leaf `text`, so removing the first
    # leaves the second covering for it and both checks above still pass — which mutation showed.
    # These four are named because they are the ones §11.8's control surface writes *near*:
    # dropping any of them is precisely how the intersection goes quietly empty while the
    # contamination channel it was computed to find stays open.
    assert {
        "criterion.text",
        "criterion.bands.descriptor",
        "criterion.exemplars.text",
        "question.prompt_text",
    } <= SCORING_PROMPT_FIELDS, (
        f"the field set is missing one of the four the console's own write surface sits beside: "
        f"{sorted({'criterion.text', 'criterion.bands.descriptor', 'criterion.exemplars.text', 'question.prompt_text'} - SCORING_PROMPT_FIELDS)}"
    )


def test_the_write_field_map_covers_every_declared_control_action():
    """Fifteen actions in, fifteen actions out — and each writes something.

    `console_vocabulary.CONTROL_SURFACE_ACTIONS` already checks the fifteen **names** against the
    HLD (TS-77's vocabulary test), so this is the other column: §11.8's Effect, at field
    granularity. An action mapped to an empty tuple would silently drop out of every set operation
    built on this map.
    """
    assert set(CONSOLE_WRITE_FIELDS) == set(CONTROL_SURFACE_ACTIONS), (
        f"the write-field map and the action list disagree: "
        f"{sorted(set(CONSOLE_WRITE_FIELDS) ^ set(CONTROL_SURFACE_ACTIONS))}"
    )
    empty = [action for action, fields in CONSOLE_WRITE_FIELDS.items() if not fields]
    assert not empty, f"these control actions are mapped to no field at all: {empty}"

    assert PRE_LOCK_ACTIONS <= set(CONTROL_SURFACE_ACTIONS), (
        f"PRE_LOCK_ACTIONS names something that is not a control action: "
        f"{sorted(PRE_LOCK_ACTIONS - set(CONTROL_SURFACE_ACTIONS))}"
    )


def test_the_post_lock_write_set_is_non_empty_and_disjoint_from_the_prompt():
    """The fixture-level form of `CT-CONSOLE-04`, and its non-vacuity anchor.

    Two assertions, and the first is the one that matters. An empty post-lock write set makes the
    intersection empty for free — the exact shape TS-57 shipped, where a scan's control asserted
    only that *something* was flagged while four of six rules were dead. `criterion.answer_key`
    is the anchor: *"correct an answer key after a run"* is a genuine post-lock write that is
    correctly disjoint from everything a prompt reads.
    """
    post_lock = post_lock_write_fields()

    assert len(post_lock) >= 10, (
        f"only {len(post_lock)} fields are written after the lock, so the disjointness below is "
        f"nearly free. Eleven of the fifteen control actions are post-lock."
    )
    assert "criterion.answer_key" in post_lock, (
        "'correct an answer key after a run' no longer writes criterion.answer_key, so the "
        "intersection has lost the one post-lock write that touches a criterion at all — the "
        "anchor that keeps CT-CONSOLE-04 from passing vacuously"
    )
    assert not (post_lock & SCORING_PROMPT_FIELDS), (
        f"the console writes {sorted(post_lock & SCORING_PROMPT_FIELDS)} after the §6.2 lock, and "
        f"a scoring prompt reads them. That is R15's contamination channel reopened in the "
        f"fixture; CT-CONSOLE-04 asserts the same thing against the running console."
    )


def test_the_literal_clause_is_unsatisfiable_and_the_hld_scopes_it(repo_root):
    """A **finding**, asserted rather than described — and it should be deleted when the clause is.

    `CT-CONSOLE-04` reads *"The console writes no field that any scoring prompt reads"*, with no
    qualifier. Against §11.8's own table that is false: *"accept or correct rubric read-back"*
    writes `criterion.text` and `criterion_band.descriptor`, and a scoring prompt reads both. A
    test written to the literal clause goes red against a **compliant** console — the failure
    review caught three times in TS-77.

    The scoping is not invented to rescue the case. HLD §11.1 states it — *"nothing it writes is
    visible to a judge at inference time … Teacher review actions are written after scoring"* — and
    §11.8's rubric row bounds the read-back to *"before any scoring exists, inside the §6.2 lock"*.
    This test asserts both halves: that the naive reading really is unsatisfiable, and that the two
    sentences the phase scoping rests on are still in the document. If either sentence goes, the
    scoping loses its authority and `CT-CONSOLE-04` must be re-derived rather than quietly kept.
    """
    unscoped = frozenset(
        field for fields in CONSOLE_WRITE_FIELDS.values() for field in fields
    ) & SCORING_PROMPT_FIELDS
    assert unscoped, (
        "the unscoped intersection is now empty, which means §11.8's control surface no longer "
        "writes any field a scoring prompt reads. If that is a real design change, delete this "
        "test and the PRE_LOCK_ACTIONS scoping with it — CT-CONSOLE-04 can then be read literally."
    )

    hld = _normalized(repo_root, HLD)
    assert "nothing it writes is visible to a judge at inference time" in hld, (
        "HLD §11.1 no longer says nothing the console writes is visible to a judge at inference "
        "time. That sentence is what makes CT-CONSOLE-04's phase scoping the design's rather than "
        "this suite's."
    )
    assert "before any scoring exists, inside the §6.2 lock" in hld, (
        "HLD §11.8's rubric read-back row no longer bounds the write to before scoring exists. "
        "Without it, writing criterion.text is an unbounded violation rather than a scoped one."
    )


def test_the_screen_inventory_and_the_two_blocking_screens_match_hld_11_5(repo_root):
    """`CT-CONSOLE-07`'s count is *"assertable against the route table"*, so the table is checked.

    Enumerated rather than sampled, for `R60`'s reason: *"could a teacher start a run, do nothing
    at all, and still have every student graded the next morning?"* is false the moment a third
    screen blocks, and a sampled inventory would miss the third one.
    """
    hld = read_repo_text(repo_root, HLD)
    # **Every `S<n>` on the heading line, not the leading one.** §11.5 gives S10 and S11 a single
    # heading — "S10 — Whole-grade sample · S11 — Blind sample" — so a capture of the first id
    # silently drops the blind-sample screen, which is the screen `CT-CONSOLE-12` and `-14` both
    # turn on. The inventory would then be twelve rows and read as complete.
    heading_lines = re.findall(r"^#### (S\d+[^\n]*)$", hld, flags=re.MULTILINE)
    headings = [screen for line in heading_lines for screen in re.findall(r"\bS\d+\b", line)]
    blocking = {
        screen
        for line in heading_lines
        if "BLOCKS" in line
        for screen in re.findall(r"\bS\d+\b", line)
    }

    assert set(SCREENS) <= set(headings), (
        f"§11.5 no longer carries {sorted(set(SCREENS) - set(headings))}. The screen inventory is "
        f"what CT-CONSOLE-07 counts against and what CT-CONSOLE-08 and -10 sweep."
    )
    # And the other direction, which is the one that matters for an **exhaustive** sweep: a screen
    # in §11.5 that the fixture does not carry is a screen every route sweep in this suite skips.
    # Mutation deleted S11 Blind sample — the screen `CT-CONSOLE-12` and `-14` both turn on — and
    # containment alone did not notice.
    assert set(headings) <= set(SCREENS), (
        f"§11.5 declares {sorted(set(headings) - set(SCREENS))} and the fixture does not. Every "
        f"'swept over every route' assertion in TS-76 would silently skip it."
    )
    assert blocking == BLOCKING_SCREENS, (
        f"§11.5 marks {sorted(blocking)} as blocking; the fixture says {sorted(BLOCKING_SCREENS)}. "
        f"Invariant 1 is that exactly two block, and this is the count."
    )
    assert OPERATOR_SCREENS < set(SCREENS)
    assert not (OPERATOR_SCREENS & BLOCKING_SCREENS), (
        "an operator screen is marked blocking. HLD §11.3 is explicit that the operator surface "
        "blocks 'only the specific submissions it names' and the teacher's blocks never — a "
        "blocking operator screen is R60 eroding from the other side."
    )


def test_the_progress_shape_is_ct_orch_10_s_and_carries_no_per_student_field(repo_root):
    """`CT-CONSOLE-09` says the console renders *"exactly what `M-ORCH` exposes and nothing more"*.

    So the ceiling is `CT-ORCH-10`'s `ProgressReport`, and this checks the fixture still describes
    it. The negative half is the load-bearing one: the design says the report *"carries **no**
    per-student field"*, and that sentence is what makes `CT-CONSOLE-09` structural rather than a
    rendering choice the console could quietly reverse.
    """
    design = _normalized(repo_root, DESIGN)
    assert "no per-student field" in design, (
        "CT-ORCH-10 no longer says ProgressReport carries no per-student field. That sentence is "
        "the reason CT-CONSOLE-09 can assert 'and nothing more' rather than only 'not rendered'."
    )
    for dimension in PROGRESS_DIMENSIONS:
        assert f"({', '.join(PROGRESS_DIMENSIONS)})".lower() in design or dimension in design
    assert PROGRESS_REPORT_FIELDS >= {"done", "in_flight", "pending", "quarantined"}
    assert not (PROGRESS_REPORT_FIELDS & set(PROGRESS_DIMENSIONS)), (
        "a dimension has leaked into the report's top-level fields; the dimensions are how counts "
        "are keyed, not figures of their own"
    )


def test_the_two_absence_strings_are_the_design_s_own(repo_root):
    """`CT-CONSOLE-11`(b) and (c) assert on exact copy, so the copy is transcribed.

    Both are quoted in `FR-CONSOLE-24` and `FR-CONSOLE-26`. Asserting a paraphrase would let a
    console render *"no data"* and pass — and `R23`'s whole point is that a reader who sees a
    vague absence assumes a figure exists somewhere.
    """
    design = _normalized(repo_root, DESIGN)
    for phrase in (NO_NEW_VALIDATION_EVIDENCE, NO_VALIDATION_FOR_POPULATION):
        assert phrase in design, (
            f"the design no longer contains {phrase!r}. CT-CONSOLE-11 asserts this string exactly, "
            f"because 'no data' is the paraphrase a reader reads as 'not shown here'."
        )


# --- the rules, in both directions --------------------------------------------------------------


def test_numeric_score_entry_passes_the_numeric_fields_a_console_must_have():
    """`FR-CONSOLE-07` forbids a numeric **score** field, not a numeric field.

    The correct fixture carries four numeric inputs — a minutes budget (HLD §10's queue is
    *"budgeted in minutes"*), a page count, a cohort size and a review window — and every one is
    required by the design. A rule phrased as "no `input[type=number]`" condemns the whole screen,
    and a rule that fails a compliant console is a rule whoever hits it first switches off.
    """
    assert numeric_score_entry_fields(fixtures.CORRECT_REVIEW_SCREEN_HTML) == [], (
        "the numeric-score sweep condemns a correct review screen. Every input on it is required: "
        "the minutes budget is HLD §10's, the window is FR-CONSOLE-22's, and the band select is "
        "the interface FR-CONSOLE-07 mandates."
    )

    # **The correct fixture must actually be hard.** A screen with no numeric inputs on it passes
    # any rule ever written, so the control would be satisfied by a fixture that proves nothing —
    # and mutation showed exactly that, by turning the minutes budget into a hidden field with no
    # test noticing. Both counts are asserted: numeric fields at all, and the three whose names
    # carry a score word, which are what the not-a-score rescue exists for.
    typed_numbers = {
        name
        for name in re.findall(r'type="number"[^>]*name="([a-z_]+)"', fixtures.CORRECT_REVIEW_SCREEN_HTML)
    }
    assert {"review_minutes", "page_count", "cohort_size", "review_window_hours"} <= typed_numbers, (
        f"the correct review screen types only {sorted(typed_numbers)} as numbers. Mutation "
        f"demoted the minutes budget to a hidden field and nothing noticed — a screen with no "
        f"numeric inputs on it passes any rule ever written, so the control would be satisfied by "
        f"a fixture that could not fail."
    )
    for name in fixtures.REQUIRED_FIELDS_WHOSE_NAMES_CARRY_A_SCORE_WORD:
        assert f'name="{name}"' in fixtures.CORRECT_REVIEW_SCREEN_HTML, (
            f"the correct screen no longer carries {name!r}. Without a required field whose name "
            f"carries a score word, the rule's not-a-score rescue is dead code: none of the "
            f"minutes, page or cohort fields contains a score term at all."
        )

    # And **one case per shape**, so a shape cannot be deleted while the others cover for it. Only
    # the first is an `input[type=number]`; the last two are what somebody writes after the first
    # is rejected in review.
    for description, html in fixtures.SCORE_ENTRY_HTML.items():
        assert numeric_score_entry_fields(html), (
            f"{description} is not reported. FR-CONSOLE-07 says no numeric score entry field "
            f"exists **anywhere**, and R39's reason is that a free numeric box reintroduces the "
            f"centre-seeking judgment §5.10 removes."
        )


def test_editable_band_controls_distinguishes_a_shown_band_from_a_changeable_one():
    """Invariant 16 is a **completeness** requirement, so the rule must not count a disabled field.

    `R65`: there is no view that shows a grade and cannot change it, because a read-only grade view
    becomes the place a teacher works around the band interface — which is how the numeric box
    comes back. A rule that counts `<select name="band" disabled>` as a band control passes exactly
    the view the invariant exists to forbid.
    """
    assert editable_band_controls(fixtures.EDITABLE_GRADE_HTML), (
        "a plain band select is not recognised as an editable band control, so CT-CONSOLE-08's "
        "completeness half would report a violation against a correct rollup"
    )
    assert editable_band_controls(fixtures.READ_ONLY_GRADE_HTML) == [], (
        "a disabled select and a readonly radio count as editable band controls, so a read-only "
        "grade view passes invariant 16 — which is the view the invariant is about"
    )


def test_external_origins_passes_a_locally_vendored_page_and_catches_all_four_routes():
    """`FR-CONSOLE-18` / invariant 13, and HLD §11.7's reason: *assets vendored locally*.

    The correct page still loads a stylesheet, a script, a font, an image and a data URI. Reporting
    any URL at all condemns it. The four violations are the four routes an external origin actually
    arrives by, and the web font is the likeliest — it is one line in a stylesheet, and it is what
    *"renders blank at a school with no internet"* means in practice.
    """
    assert external_origins(fixtures.SELF_CONTAINED_PAGE_HTML) == [], (
        "a page whose every asset is same-origin is reported as loading external origins. It "
        "carries a font, a stylesheet, a script, a blob image and a data URI — all of which HLD "
        "§11.7 requires the console to have."
    )
    for description, html in fixtures.EXTERNAL_ORIGIN_HTML.items():
        assert external_origins(html), f"{description} is not reported as an external origin"

    # `@import url("…")` matches two patterns; one stylesheet must read as one origin.
    imported = external_origins(fixtures.EXTERNAL_ORIGIN_HTML["an @import in an inline stylesheet"])
    assert len(imported) == 1, f"one imported stylesheet counted as {len(imported)} origins"


def test_browser_storage_writes_reads_scripts_not_prose():
    """`FR-CONSOLE-17`, and the honest page is the hard case.

    The console's own privacy note *says* "localStorage" — that is what an honest console tells its
    operator. A whole-document substring scan reports it, so the scan reads script bodies and event
    handlers only. The catching direction includes the *"remember my place"* addition #124's own
    issue names as the plausible violation: it is plausible precisely because it is helpful.
    """
    assert browser_storage_writes(fixtures.PAGE_THAT_MENTIONS_STORAGE_HONESTLY) == [], (
        "a page that promises in prose not to use browser storage is reported as using it. That "
        "rule fails the console's own privacy note."
    )
    for description, html in fixtures.STORAGE_WRITE_HTML.items():
        assert browser_storage_writes(html), f"{description} is not reported"

    assert fixtures.SENTINEL_STUDENT_NAME in fixtures.REMEMBER_MY_PLACE_HTML, (
        "the 'remember my place' fixture no longer carries a student name, so it demonstrates a "
        "preference being stored rather than FR-CONSOLE-17's student text"
    )


def test_per_student_progress_permits_s13_and_catches_a_figure_in_a_payload():
    """`FR-CONSOLE-08` forbids a per-student **progress indicator**, not a per-student view.

    `/students/{ref}` is a declared teacher route and S13 is a screen in §11.5, so a rule that
    condemns any per-student payload condemns the design. What makes the second fixture illegal is
    that it carries *progress* — and §6.11.19 names the realistic shape: *"a per-student figure
    available in a payload and merely unrendered"*, which is a decision already taken whether or
    not this release draws it.
    """
    assert per_student_progress_figures(fixtures.CORRECT_PROGRESS_PAYLOAD) == [], (
        "CT-ORCH-10's own progress shape is reported as carrying a per-student figure, so the "
        "console could render nothing at all and still fail CT-CONSOLE-09"
    )
    assert per_student_progress_figures(fixtures.CORRECT_STUDENT_DETAIL_PAYLOAD) == [], (
        "S13 Student detail is reported as a per-student progress indicator. It is a declared "
        "teacher route carrying results, not progress; R63 objects to the indicator during a run."
    )
    for description, payload in fixtures.PER_STUDENT_PROGRESS_PAYLOADS.items():
        assert per_student_progress_figures(payload), (
            f"a payload {description} is not reported, so the per-student progress bar R63 says "
            f"'cannot honestly be built' would ship in the API and wait for a UI"
        )


def test_provenance_rule_catches_a_missing_figure_and_an_empty_label():
    """`FR-CONSOLE-09`, and both ways a provenance footer fails.

    The first is §6.11.19's named gap — *"provenance present on the main screen and absent on the
    export preview"*. The second is subtler and is the reason the rule reads the **value**: three
    labels with nothing after them satisfy any substring check, and `RISK-12` is not addressed by a
    footer that names the fields it does not fill.
    """
    assert grade_views_missing_provenance(fixtures.GRADE_WITH_PROVENANCE_HTML) == [], (
        "a grade view carrying all three figures is reported as missing provenance"
    )
    assert grade_views_missing_provenance(fixtures.EXPORT_PREVIEW_MISSING_PROVENANCE_HTML) == [
        "backend_profile"
    ], "the export preview's missing backend profile is not reported, or the wrong figure is named"
    assert set(grade_views_missing_provenance(fixtures.PROVENANCE_LABELS_WITHOUT_VALUES_HTML)) == set(
        PROVENANCE_FIELDS
    ), (
        "a footer printing all three labels with no values passes. That is the same 'blank that "
        "reads as fine' §2.1 names, and it satisfies every substring check ever written."
    )


def test_agreement_block_problems_passes_a_correct_block_and_names_each_failure():
    """`FR-CONSOLE-10` is four requirements in one sentence, so the rule reports four separately.

    The correct block is the hard direction: it contains the word "agreement", two figures and two
    scopes, and a rule keyed on any of those alone condemns it. Each broken block below breaks
    exactly one requirement, so a rule that lost one check would still pass four of the five.
    """
    assert agreement_block_problems(fixtures.CORRECT_AGREEMENT_BLOCK) == [], (
        f"a correct agreement block is reported as broken: "
        f"{agreement_block_problems(fixtures.CORRECT_AGREEMENT_BLOCK)}"
    )
    for description, block in fixtures.BROKEN_AGREEMENT_BLOCKS.items():
        assert agreement_block_problems(block), f"an agreement block with {description} passes"

    assert any(stat in fixtures.CORRECT_AGREEMENT_BLOCK.lower() for stat in CHANCE_CORRECTED_STATISTICS)
    assert all(level in fixtures.CORRECT_AGREEMENT_BLOCK.lower() for level in AGREEMENT_LEVELS)

    # The carried-forward block is `FR-CONSOLE-24`'s failure and it is **well formed**: it passes
    # every check above, because there is nothing wrong with the figure except that it is last
    # term's. RISK-08 has no symptom, which is why C11(b) asserts a negative rather than a rule.
    assert agreement_block_problems(fixtures.CARRIED_FORWARD_AGREEMENT_BLOCK) == [], (
        "the carried-forward block is reported as malformed, which would let CT-CONSOLE-11(b) "
        "pass for the wrong reason: the silent carry-forward is invisible to a well-formedness "
        "check, and that is exactly what makes it RISK-08"
    )


def test_query_reachability_reports_a_filter_as_well_as_a_join():
    """`CT-CONSOLE-12`'s reachability half, and the asymmetry is deliberate.

    A query that *excludes* quarantined rows is reported, because excluding them proves the queue
    joined to a table that carries them — and a filter is one refactor from being dropped. §6.11.19
    asks for reachability *"over the queue's queries"* rather than over what it rendered for
    exactly that reason, the same discipline `CT-CONSOLE-14` applies to the blind flow.
    """
    assert queries_reaching(fixtures.CORRECT_QUEUE_QUERIES, QUARANTINE_STATES) == [], (
        "a correct queue's queries are reported as reaching quarantine. They read review_queue "
        "rows, which are never created for a quarantined submission."
    )
    for description, query in fixtures.LEAKY_QUEUE_QUERIES.items():
        assert queries_reaching([query], QUARANTINE_STATES), f"a query that {description} passes"


def test_replay_idempotency_accepts_a_refusal_and_rejects_a_second_row():
    """`CT-CONSOLE-03`'s helper: idempotent means **no additional row**, not "no error".

    A second `label`, a second `audit_record` or a second `run` is a corrupted run that raised
    nothing — which is what a double-clicked button produces. §3.19's error handling permits the
    other outcome explicitly: *"idempotent or refused with a refresh, never partially applied"*.
    """

    class _Outcome:
        def __init__(self, rows=(), refused=False):
            self.rows_written = list(rows)
            self.refused = refused

    first = _Outcome(rows=["label:l-1"])
    assert replayed_writes_are_idempotent(first, _Outcome(rows=[]))[0]
    assert replayed_writes_are_idempotent(first, _Outcome(rows=["label:l-1"]))[0]
    assert replayed_writes_are_idempotent(first, _Outcome(refused=True))[0]

    verdict, reason = replayed_writes_are_idempotent(first, _Outcome(rows=["label:l-2"]))
    assert not verdict, "a replay that wrote a second label row is reported as idempotent"
    assert "l-2" in reason, f"the failure does not name the row that was written: {reason!r}"

    assert set(REPLAY_ROUTES) == {"double_click", "retried_request", "back_navigation"}, (
        "the three routes §11.8 names are what the per-action sweep drives; dropping one leaves a "
        "control tested through two of the three ways a teacher actually triggers it twice"
    )
    assert "partially_applied" not in STALE_STATE_OUTCOMES, (
        "partial application has become an accepted stale-state outcome; §3.19 says 'never'"
    )


def test_the_refusal_sweep_is_a_product_and_the_bind_values_disagree():
    """`CT-CONSOLE-05`/`-20`: the sweep must be a product, and it must contain a routable address.

    §6.11.19 asks for *"every combination of settings"*, and the failure it is for is a refusal
    keyed on something other than the deployment profile — which a single combination cannot find.
    `ROUTABLE_BIND` has to be in the sweep or the case never tries the setting an operator would
    actually change to "make it work from the other machine".
    """
    combinations = 1
    for values in REFUSAL_SWEEP_SETTINGS.values():
        assert len(values) >= 2, "a setting with one value contributes nothing to a product sweep"
        combinations *= len(values)
    assert combinations >= 8, f"the sweep is {combinations} combinations, which is a sample"

    assert ROUTABLE_BIND in REFUSAL_SWEEP_SETTINGS["CONSOLE_BIND"], (
        f"{ROUTABLE_BIND!r} is not in the bind sweep, so CT-CONSOLE-20's 'a knob that could "
        f"disable a security refusal would make that refusal advisory' is never exercised"
    )
    assert ROUTABLE_BIND not in LOOPBACK_ADDRESSES, "the adversarial bind value is a loopback one"
    assert CLOUD_HOSTED_PROFILE == "cloud-hosted"
