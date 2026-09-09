"""Boundaries, answer keys and append-only elicitation history against real Tier P.

Cases `TC-PKG-16`, `TC-PKG-17`, `TC-PKG-18`, `TC-PKG-19`, `TC-PKG-20` (`FR-PKG-16`,
`-17`, `-18`, `-19`, `-20`), test plan §5.4. Issue #30 (paired with #33/TS-12), plus one
inline regression: `is_locked` resolved an undefined `_SELECT_VERSION` name — every call
raised `NameError` on main (defect found while landing #30; no existing `TC-*` case
exercised the accessor, so the regression rides here and test-plan §5.4 carries it as
`TC-PKG-29`).

Rung 2 — real Tier P files: the append-only oracle is a **state assertion over the
table after an attempted rewrite**, and the no-correctness-column oracle is asserted
against the **live schema** — neither survives a fake.

`Written ahead of implementation: yes` is stale — the surface landed with #30; the
cases run green by design.
"""

from __future__ import annotations

import sqlite3

import pytest

from aeh.pkg import (
    GradePolicy,
    GradePolicyError,
    PackageCatalog,
    PackageDraft,
    PackageError,
    PublishedVersionImmutableError,
)
from aeh.store import Statement, open_store
from tests.support.store_api import statement

pytestmark = pytest.mark.integration

ISSUE = "#30"

#: TC-PKG-16's boundary table: cuts at 40, 55, 70, 85 — the plan's own fixture.
CUTS = (("D", 40.0), ("C", 55.0), ("B", 70.0), ("A", 85.0))


def _catalog(tmp_data_dir, *, with_mcq: bool = True):
    store = open_store(tmp_data_dir)
    handle = store.package("pkg-30")
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO package (package_id, created_at) "
            "VALUES ('pkg-30', '2026-01-01')", issue=ISSUE), p="pkg-30")
    catalog = PackageCatalog(handle, package_id="pkg-30")
    v = catalog.create_version(None, PackageDraft(title="grade policy target"))
    catalog.add_criterion(v, "CRIT-1", question_id="Q-1", kind="open", max_points=4.0,
                          band_count=2)
    catalog.add_band(v, "CRIT-1", 0, "b0", 0.0)
    catalog.add_band(v, "CRIT-1", 1, "b1", 1.0)
    if with_mcq:
        catalog.add_criterion(v, "MCQ-1", question_id="Q-2", kind="mcq")
        catalog.set_mcq_options(v, "MCQ-1", [("A", "alpha"), ("B", "beta"),
                                             ("C", "gamma")])
    return store, handle, catalog, v


# -- TC-PKG-16: the boundary lookups are pure over grade_boundary --------------------------------


def test_tc_pkg_16_boundary_for_resolves_per_the_declared_inclusive_rule(tmp_data_dir):
    """`TC-PKG-16` — *'boundary_for resolves each per the declared inclusive or
    exclusive rule, which must be stated'*.

    The declared rule: floors are INCLUSIVE — `boundary_for` answers the grade with the
    greatest floor <= the score, so exactly-on-a-cut belongs to the cut's grade. A score
    below the lowest floor has no grade; no boundary table answers None (`CT-PKG-10`) —
    the caller handles it; nothing invents a boundary."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    catalog.set_boundaries(v, CUTS)
    assert catalog.boundary_for(v, 39.999) is None
    assert catalog.boundary_for(v, 40.0) == "D"
    assert catalog.boundary_for(v, 40.001) == "D"
    assert catalog.boundary_for(v, 84.999) == "B"
    assert catalog.boundary_for(v, 85.0) == "A"
    assert catalog.boundary_for(v, 100.0) == "A"
    assert catalog.boundary_for(v, 0.0) is None
    assert catalog.boundary_for(v, -5.0) is None
    store.close()


def test_tc_pkg_16_distance_to_nearest_boundary_is_exact_at_every_point(tmp_data_dir):
    """`TC-PKG-16` — *'distance_to_nearest_boundary is exact at every point including
    exactly on a cut'* — zero ON a cut, the raw distance off it, from either side."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    catalog.set_boundaries(v, CUTS)
    assert catalog.distance_to_nearest_boundary(v, 40.0) == 0.0
    assert catalog.distance_to_nearest_boundary(v, 85.0) == 0.0
    assert catalog.distance_to_nearest_boundary(v, 39.999) == pytest.approx(0.001)
    assert catalog.distance_to_nearest_boundary(v, 84.999) == pytest.approx(0.001)
    assert catalog.distance_to_nearest_boundary(v, 100.0) == pytest.approx(15.0)
    assert catalog.distance_to_nearest_boundary(v, 0.0) == pytest.approx(40.0)
    assert catalog.distance_to_nearest_boundary(v, -5.0) == pytest.approx(45.0)
    store.close()


def test_tc_pkg_16_no_boundary_table_answers_null_equivalents_and_the_lookups_stay_pure(
    tmp_data_dir,
):
    """`TC-PKG-16`/`CT-PKG-10` — *'for a package declaring no boundary table, assert
    both return null-equivalents and that no caller-visible default appears'* — then
    the purity half: the lookups neither create a table nor rewrite a row, so the
    canonical representation stays exactly what the teacher declared."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    v_bare = catalog.create_version(None, PackageDraft(title="no boundaries"))
    assert catalog.boundary_for(v_bare, 50.0) is None
    assert catalog.distance_to_nearest_boundary(v_bare, 50.0) is None
    catalog.set_boundaries(v, CUTS)
    rows_before = handle.query(statement(
        "SELECT grade, scaled_floor FROM grade_boundary "
        "WHERE package_version_id = :v ORDER BY scaled_floor", issue=ISSUE), v=v)
    for _ in range(3):
        catalog.boundary_for(v, 60.0)
        catalog.distance_to_nearest_boundary(v, 60.0)
    rows_after = handle.query(statement(
        "SELECT grade, scaled_floor FROM grade_boundary "
        "WHERE package_version_id = :v ORDER BY scaled_floor", issue=ISSUE), v=v)
    assert [tuple(r) for r in rows_before] == [tuple(r) for r in rows_after] == [
        ("D", 40.0), ("C", 55.0), ("B", 70.0), ("A", 85.0)]
    store.close()


def test_tc_pkg_16_a_boundary_table_may_not_be_ambiguous(tmp_data_dir):
    """`TC-PKG-16`'s single-canonical-representation premise — duplicate labels or
    duplicate cuts are refused (`GradePolicyError`), because two grades sharing one cut
    is an ambiguous resolution and the table is the ONE place the rule lives."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    with pytest.raises(GradePolicyError):
        catalog.set_boundaries(v, [("A", 70.0), ("A", 85.0)])
    with pytest.raises(GradePolicyError):
        catalog.set_boundaries(v, [("B", 70.0), ("A", 70.0)])
    assert catalog.boundary_for(v, 70.0) is None  # nothing was written
    store.close()


# -- TC-PKG-17: criterion.answer_key is the single canonical key ---------------------------------


def test_tc_pkg_17_mcq_option_carries_no_correctness_column_in_the_live_schema(
    tmp_data_dir,
):
    """`TC-PKG-17`/`ADR-1` — *'mcq_option has no correctness column, asserted against
    the live schema'* — `PRAGMA table_info` on the real Tier P file, not a schema
    document. A correctness column by ANY name fails: the key lives once, on
    `criterion.answer_key`, so a corrected key cannot leave two disagreeing sources."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    columns = [row["name"] for row in handle.query(statement(
        "PRAGMA table_info(mcq_option)", issue=ISSUE))]
    assert columns == ["package_version_id", "criterion_id", "option_id", "label"]
    assert not any("correct" in column.lower() for column in columns)
    store.close()


def test_tc_pkg_17_the_key_round_trips_through_criterion_answer_key(tmp_data_dir):
    """`TC-PKG-17` — *'criterion.answer_key is the single canonical key'* — the key is
    the sequence of acceptable option ids (one for single-select, several for
    multi-select), readable through the accessor AND the version-pinned criteria
    projection, and readable by another module's fresh catalog instance (the M-DET /
    M-INGEST access path)."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    catalog.set_answer_key(v, "MCQ-1", ["A"])
    assert catalog.answer_key("MCQ-1") == ("A",)
    assert catalog.criteria(v)[1]["answer_key"] == ("A",)
    catalog.set_answer_key(v, "MCQ-1", ["A", "C"])  # a multi-select correction, draft
    assert catalog.answer_key("MCQ-1") == ("A", "C")
    # Another module reaches the same key through its own catalog over the same handle:
    other = PackageCatalog(handle, package_id="pkg-30")
    assert other.answer_key("MCQ-1") == ("A", "C")
    # No key declared yet answers the empty tuple — never None, never a guess:
    assert catalog.answer_key("CRIT-1") == ()
    store.close()


def test_tc_pkg_17_the_key_refuses_an_unknown_criterion_and_an_empty_key(tmp_data_dir):
    store, handle, catalog, v = _catalog(tmp_data_dir)
    with pytest.raises(PackageError):
        catalog.set_answer_key(v, "MCQ-ABSENT", ["A"])
    with pytest.raises(PackageError):
        catalog.set_answer_key(v, "MCQ-1", [])
    store.close()


# -- TC-PKG-18: a key correction is a new version, retaining the prior key -----------------------


def test_tc_pkg_18_a_correction_creates_a_new_version_and_retains_the_prior_key(
    tmp_data_dir,
):
    """`TC-PKG-18` — *'a new package_version is created retaining the prior key, so
    audit_record.answer_key_ref resolves to exactly the key that produced a given
    grade'* — the correction flow is create_version + set_answer_key on the child; the
    parent's key is byte-identical afterwards, and the lineage is exact.

    The revision-copy half is asserted too, immediately after the copy: the child
    inherits the parent's policy (window included), boundaries, options and key —
    dropping any copy statement would hand a corrected child a silently different
    instrument. `elicitation_history` is deliberately NOT copied: it is the append-only
    trail (FR-PKG-20), whose rows reference the version the conversation was about."""
    store, handle, catalog, v1 = _catalog(tmp_data_dir)
    catalog.set_grade_policy(v1, GradePolicy(review_window_hours=24))
    catalog.set_boundaries(v1, CUTS)
    catalog.set_answer_key(v1, "MCQ-1", ["A"])
    catalog.append_elicitation(v1, "Why option A?", ["A", "B"], "A", "key declared")
    catalog.publish(v1, "teacher")
    v2 = catalog.create_version(v1)
    # The copy is lossless — every content surface the child will edit is there:
    assert catalog.grade_policy(v2) == catalog.grade_policy(v1)
    assert catalog.grade_policy(v2).review_window_hours == 24
    assert catalog.boundary_for(v2, 60.0) == catalog.boundary_for(v1, 60.0) == "C"
    assert catalog.mcq_options(v2, "MCQ-1") == catalog.mcq_options(v1, "MCQ-1")
    assert catalog.criteria(v2)[1]["answer_key"] == ("A",)
    # The trail did NOT copy — two rows total, both referencing the version asked about:
    rows = handle.query(statement(
        "SELECT package_version_id, question FROM elicitation_history", issue=ISSUE))
    assert [tuple(r) for r in rows] == [(v1, "Why option A?")]
    # The correction lands in the child; the parent keeps its key:
    catalog.set_answer_key(v2, "MCQ-1", ["B"])
    catalog.publish(v2, "teacher")
    assert catalog.criteria(v1)[1]["answer_key"] == ("A",)
    assert catalog.criteria(v2)[1]["answer_key"] == ("B",)
    # The current lineage top answers the new key:
    assert catalog.answer_key("MCQ-1") == ("B",)
    assert catalog.lineage(v2) == (v1, v2)
    store.close()


def test_tc_pkg_18_a_correction_never_lands_in_place(tmp_data_dir):
    """`TC-PKG-18`'s refusal half — the key on a PUBLISHED version is immutable
    (`PublishedVersionImmutableError`): a correction that edited in place would break
    every `answer_key_ref` ever recorded against the version."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    catalog.set_answer_key(v, "MCQ-1", ["A"])
    catalog.publish(v, "teacher")
    with pytest.raises(PublishedVersionImmutableError):
        catalog.set_answer_key(v, "MCQ-1", ["B"])
    assert catalog.criteria(v)[1]["answer_key"] == ("A",)
    store.close()


# -- TC-PKG-19: review_window_hours — null, 0, 24, negative --------------------------------------


@pytest.mark.parametrize("window", [None, 0, 24])
def test_tc_pkg_19_the_window_is_stored_and_exposed_to_m_grade(tmp_data_dir, window):
    """`TC-PKG-19` — *'0 and 24 are stored and exposed to M-GRADE'*; null round-trips
    as null — *'null means finalize on run completion rather than wait indefinitely'*
    (ADR-3: a COLUMN, so `grade_policy()` answers it straight from the row)."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    catalog.set_grade_policy(v, GradePolicy(review_window_hours=window))
    stored = catalog.grade_policy(v)
    assert stored.review_window_hours == window
    # The column, read raw — the ADR-3 canonical place:
    row = handle.query(statement(
        "SELECT review_window_hours FROM grade_policy WHERE package_version_id = :v",
        issue=ISSUE), v=v)[0]
    assert row["review_window_hours"] == window
    # And the default policy a version with none answers carries null too:
    assert catalog.grade_policy(
        catalog.create_version(None, PackageDraft(title="w"))
    ).review_window_hours is None
    store.close()


def test_tc_pkg_19_a_negative_window_is_refused_with_the_exact_exception(tmp_data_dir):
    """`TC-PKG-19` — *'negative is rejected'* — exact exception: `GradePolicyError`, at
    construction (the object cannot exist) and therefore at the write."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    with pytest.raises(GradePolicyError):
        GradePolicy(review_window_hours=-1)
    with pytest.raises(GradePolicyError):
        GradePolicy(review_window_hours=1.5)
    store.close()


def test_tc_pkg_19_the_write_door_refuses_a_free_text_formula(tmp_data_dir):
    """`FR-PKG-14`'s write door — `set_grade_policy` accepts only a `GradePolicy`
    object: a string policy (a formula, an expression) is refused with
    `GradePolicyError` at the write, not stored and interpreted later. The
    construction-time half of the same refusal is TC-PKG-14's unit case."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    for formula in ("total = sum(scores)", "score * 0.8 + 5",
                    "lambda scores: sum(scores)"):
        with pytest.raises(GradePolicyError):
            catalog.set_grade_policy(v, formula)
    # Nothing was written — the version still answers the default:
    assert catalog.grade_policy(v) == GradePolicy()
    store.close()


def test_tc_pkg_19_the_generic_field_path_refuses_the_answer_key_door(tmp_data_dir):
    """`ADR-1`'s one-door rule, enforced — `update_criterion_field` cannot reach
    `criterion.answer_key` with an unvalidated value: the generic dispatch refuses the
    field and points at `set_answer_key`."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    with pytest.raises(PackageError, match="set_answer_key"):
        catalog.update_criterion_field(v, "MCQ-1", "answer_key", "not json at all")
    catalog.set_answer_key(v, "MCQ-1", ["A"])
    assert catalog.criteria(v)[1]["answer_key"] == ("A",)
    store.close()


def test_tc_pkg_19_corrupted_rows_refuse_inside_the_module_error_family(tmp_data_dir):
    """`CT-PKG-09`/`CT-PKG-11` — the vocabulary holds at READ too: a hand-edited policy
    row that is not a structured object refuses with `GradePolicyError`, and a
    hand-edited malformed answer key refuses with `PackageError` — never a raw
    `TypeError`/`JSONDecodeError` from the parse half-way through the surface. Both rows
    are written raw against a DRAFT (drafts edit freely; the corruption is the point)."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    catalog.set_grade_policy(v, GradePolicy())
    with handle.transaction() as tx:
        tx.execute(statement(
            "UPDATE grade_policy SET policy = 'total = sum(scores)' "
            "WHERE package_version_id = :v", issue=ISSUE), v=v)
    with pytest.raises(GradePolicyError):
        catalog.grade_policy(v)
    with handle.transaction() as tx:
        tx.execute(statement(
            "UPDATE criterion SET answer_key = '{not json' "
            "WHERE package_version_id = :v AND criterion_id = 'MCQ-1'", issue=ISSUE),
            v=v)
    with pytest.raises(PackageError):
        catalog.criteria(v)
    with pytest.raises(PackageError):
        catalog.answer_key("MCQ-1")
    store.close()


# -- TC-PKG-20: elicitation_history is append-only in practice -----------------------------------


def test_tc_pkg_20_an_update_and_a_delete_are_refused_and_the_table_is_unchanged(
    tmp_data_dir,
):
    """`TC-PKG-20` — *'Both refused; appends succeed; the table is append-only in
    practice, not merely by convention'*.

    Oracle: exact exception (sqlite3.IntegrityError, the trigger's RAISE(ABORT)) plus a
    state assertion over the table AFTER the attempts — the row survives byte-identical.
    The rewrites are attempted through the handle's own transaction door, the same route
    a caller bypassing the catalog would take: the enforcement is in the DATA."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    catalog.publish(v, "teacher")  # appends must survive publication — the trail
    # records conversations about the rubric as it stands.
    elicitation_id = catalog.append_elicitation(
        v, "Why two bands?", ["one band", "two bands"], "two bands",
        "band_count declared 2")
    catalog.append_elicitation(v, "Why atomic scoring?", ["atomic", "holistic"],
                               "atomic")
    update = statement(
        "UPDATE elicitation_history SET question = :q, answer_given = :a "
        "WHERE elicitation_id = :id", issue=ISSUE)
    delete = statement(
        "DELETE FROM elicitation_history WHERE elicitation_id = :id", issue=ISSUE)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with handle.transaction() as tx:
            tx.execute(update, q="rewritten", a="forged", id=elicitation_id)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with handle.transaction() as tx:
            tx.execute(delete, id=elicitation_id)
    # State assertion — the attempts changed nothing:
    rows = handle.query(statement(
        "SELECT question, options_offered, answer_given, resulting_edit "
        "FROM elicitation_history ORDER BY question", issue=ISSUE))
    assert [tuple(r) for r in rows] == [
        ("Why atomic scoring?", '["atomic", "holistic"]', "atomic", ""),
        ("Why two bands?", '["one band", "two bands"]', "two bands",
         "band_count declared 2"),
    ]
    store.close()


def test_tc_pkg_20_appends_succeed_before_and_after_publication(tmp_data_dir):
    """`TC-PKG-20` — *'appends succeed'* — on a draft and on a published version: the
    history is not version content (no insert-locked trigger fires on it) and the
    catalog exposes no update or delete at all."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    first = catalog.append_elicitation(v, "Q1?", ["a", "b"], "a")
    catalog.publish(v, "teacher")
    second = catalog.append_elicitation(v, "Q2?", ["a", "b"], "b", "label edited")
    assert first and second and first != second
    elicitation_surface = [
        name for name in dir(catalog)
        if not name.startswith("_") and "elicitation" in name.lower()
    ]
    assert elicitation_surface == ["append_elicitation"], (
        f"TC-PKG-20: the elicitation surface is {elicitation_surface} — an append-only "
        "table has one append method and no rewrite API (FR-PKG-20)."
    )
    store.close()


# -- inline regression: is_locked resolved an undefined name -------------------------------------


def test_tc_pkg_29_is_locked_answers_the_versions_publication_state(tmp_data_dir):
    """`TC-PKG-29` (added to test-plan §5.4 with #30) — `is_locked` answers False on a
    draft, True on a published version, and False on a revision's child, resolving the
    version row on every call instead of raising — and an unknown version id raises
    rather than answering.

    Regression: `is_locked` referenced `_SELECT_VERSION`, a name the module never
    defined — every call raised `NameError` from the moment #26 landed. No existing
    `TC-*` case exercised the accessor, so the regression is written inline per the
    defect-fix rule and the case joins the plan in the same PR. #239 completes the
    oracle with the unknown-id negative half."""
    store, handle, catalog, v = _catalog(tmp_data_dir, with_mcq=False)
    assert catalog.is_locked(v) is False
    catalog.publish(v, "teacher")
    assert catalog.is_locked(v) is True
    child = catalog.create_version(v)
    assert catalog.is_locked(child) is False
    # The negative half: an unknown but well-formed version id must raise, never
    # answer — the row lookup finds nothing, and the accessor refuses to guess a
    # publication state for a version that does not exist (#239).
    with pytest.raises(IndexError):
        catalog.is_locked("pkg-30@000000000000")
    store.close()
