"""`TS-48` (issue #129) — the console's life-cycle controls over a real store: amendment,
the review window, the export provenance gate, and the two honest absences.

Test plan §5.19, `TC-CONSOLE-21`, `-22`, `-23`, `-24`, `-26`, all Integration / rung 3.

**What these add over the clause suite.** `CT-CONSOLE-C15`, `-C16` and `-C11b/c`
(`tests/contract/console/`) assert the same invariants against `StoreSpy`, where the console
settles a headless batch in memory and records control rows as payloads. That is the path a
real deployment never takes. Here the console is handed a store whose `data_dir` is real, so
every figure is read back from the ledger the shipped modules wrote — **not** from the
console's own return values — and every "the console remembered it" answer is checked by a
second, freshly built console over the same store: `FR-CONSOLE-01` makes the console
stateless, so anything only the first instance knows was never written.

**Diagnostics.** The red-by-defect cases collect every violated clause before failing, so one
run names all of them rather than the first.

**Written ahead of implementation.** The issue says `yes`; that is stale — `M-CONSOLE` landed
(#122 … #127), so these are written against the shipped module and are expected to pass. Where
one fails, the failure is a defect in the landed console, named in the assertion message.
"""

from __future__ import annotations

import re

import pytest

from aeh.console import (
    NO_NEW_VALIDATION_EVIDENCE,
    NO_VALIDATION_FOR_POPULATION,
    ProvenanceRefused,
    amend_finalized_grade,
    build_console,
    export_package,
)
from aeh.pkg import PackageCatalog, record_promotion
from aeh.store import open_store
from tests.support.console_vocabulary import element_text, visible_text
from tests.support.console_world import rows, seed_scored_run

pytestmark = [pytest.mark.integration]

_CURRENT_GRADES = (
    "SELECT submission_id, revision, is_current, state, total, finalized_at "
    "FROM submission_grade WHERE run_id = :run_id ORDER BY submission_id, revision"
)


def _fail_with(problems: list[str]) -> None:
    assert not problems, "\n\n".join(problems)


# --- TC-CONSOLE-21 — amendment preserves finalized_at and writes a new revision ------------------


def test_tc_console_21_amending_a_finalized_grade_writes_a_new_revision_in_the_ledger(
    tmp_data_dir,
):
    """`TC-CONSOLE-21` / `FR-CONSOLE-21` (invariant 17) — over a run M-GRADE really finalized.

    Oracle, exact values read from `submission_grade`: the amendment lands as revision 2
    with the delivered `finalized_at` carried forward and the corrected total (the C-01
    edit to `incorrect` takes one point off the delivered 3.0); revision 1 stays in the
    ledger byte-for-byte, now superseded. The console's own return value is not the oracle —
    a fresh console over the same store must read both revisions back, because a revision
    only the amending instance holds was never written.
    """
    store = open_store(tmp_data_dir)
    try:
        world = seed_scored_run(store, finalize=True)
        cohort = store.cohort(world.cohort_id)
        submission = world.submissions[0]
        delivered = [r for r in rows(cohort, _CURRENT_GRADES, run_id=world.run_id)
                     if r["submission_id"] == submission]
        assert len(delivered) == 1 and delivered[0]["finalized_at"], (
            f"fixture: {submission} must carry exactly one finalized revision before the "
            f"amendment, got {delivered!r}"
        )
        assert delivered[0]["total"] == 3.0, "fixture: every key selected, so 3.0 delivered"
        delivered = delivered[0]

        problems: list[str] = []
        app = build_console(store=store)
        try:
            amend_finalized_grade(
                app, submission_ref=submission, criterion_id="C-01", new_band="incorrect",
                actor="teacher-a",
            )
        except KeyError as refusal:
            problems.append(
                f"the console refused to amend {submission}: {refusal}. The store holds that "
                f"grade finalized at {delivered['finalized_at']!r} (M-GRADE finalized the batch), "
                f"but the console only amends grades its own instance settled in memory — a "
                f"console restarted after delivery, or a second tab, has no amendment path at "
                f"all (FR-CONSOLE-21, FR-CONSOLE-01)."
            )

        after = [r for r in rows(cohort, _CURRENT_GRADES, run_id=world.run_id)
                 if r["submission_id"] == submission]
        revisions = [r["revision"] for r in after]
        if revisions != [1, 2]:
            problems.append(
                f"the ledger holds revisions {revisions} for {submission} after the amendment, "
                f"expected [1, 2]. FR-CONSOLE-21: an amendment writes a new grade revision — a "
                f"correction the console holds only in memory is lost the moment the tab closes, "
                f"and no export, rollup or second console ever sees it (M-GRADE's "
                f"GradingService.amend is the shipped writer)."
            )
        else:
            original, amended = after
            for column in ("finalized_at", "total", "state"):
                if original[column] != delivered[column]:
                    problems.append(
                        f"revision 1's {column} changed from {delivered[column]!r} to "
                        f"{original[column]!r}: the delivered grade was mutated, not superseded"
                    )
            if amended["finalized_at"] != delivered["finalized_at"]:
                problems.append(
                    f"revision 2's finalized_at is {amended['finalized_at']!r}, expected the "
                    f"delivered {delivered['finalized_at']!r} — an amendment preserves when the "
                    f"batch was delivered"
                )
            if amended["total"] != 2.0:
                problems.append(
                    f"revision 2's total is {amended['total']!r}, expected 2.0 (C-01 amended "
                    f"to incorrect, 0 points, over a delivered 3.0)"
                )
            if (original["is_current"], amended["is_current"]) != (0, 1):
                problems.append(
                    f"is_current is {(original['is_current'], amended['is_current'])} for "
                    f"revisions (1, 2), expected (0, 1)"
                )

        fresh = build_console(store=store)
        first = fresh.grade_revision(submission_ref=submission, revision=1)
        if first is None or first.finalized_at != delivered["finalized_at"]:
            problems.append(
                f"a fresh console reads revision 1 as {first!r}; the ledger's delivered "
                f"finalized_at is {delivered['finalized_at']!r}. The console must present the "
                f"delivered grade as delivered, from the store."
            )
        second = fresh.grade_revision(submission_ref=submission, revision=2)
        if second is None:
            problems.append(
                "a fresh console over the same store cannot read revision 2 — the amendment "
                "exists only inside the console instance that made it (FR-CONSOLE-01: the "
                "console holds no pipeline state)."
            )
        _fail_with(problems)
    finally:
        store.close()


# --- TC-CONSOLE-22 — a review window delays finalization and withholds nothing -------------------


def test_tc_console_22_a_review_window_delays_finalization_and_grades_export_provisional(
    tmp_data_dir,
):
    """`TC-CONSOLE-22` / `FR-CONSOLE-22` (invariant 18) — a window set, then finalize, mid-window.

    Exact values from the ledger: no current grade carries a `finalized_at` (finalization is
    delayed), every submission still has its grade with its total (nothing withheld), and the
    export — through a fresh console, since the window is store state rather than tab state —
    returns one record per submission, each marked provisional.

    **Control**: a second run, finalized with no window, must export `provisional=False` — so the
    provisional flag is read from the grade's state rather than being true of every export.
    """
    store = open_store(tmp_data_dir)
    try:
        world = seed_scored_run(store)
        cohort = store.cohort(world.cohort_id)
        app = build_console(store=store)
        app.set_review_window(world.run_id, hours=48)
        app.finalize_batch(world.run_id, actor="teacher-a")

        problems: list[str] = []
        current = [r for r in rows(cohort, _CURRENT_GRADES, run_id=world.run_id)
                   if r["is_current"]]
        if sorted(r["submission_id"] for r in current) != sorted(world.submissions):
            problems.append(
                f"current grades exist for {sorted(r['submission_id'] for r in current)}, "
                f"expected every submission {sorted(world.submissions)} — a review window "
                f"never withholds a grade"
            )
        if any(r["total"] is None for r in current):
            problems.append(f"a current grade carries no total inside the window: {current!r}")
        stamped = [r["submission_id"] for r in current if r["finalized_at"]]
        if stamped:
            problems.append(
                f"{stamped} were finalized although the batch was finalized inside a 48-hour "
                f"review window. FR-CONSOLE-22: the window delays finalization. (The console's "
                f"set_review_window must reach the store — grade_policy.review_window_hours — "
                f"or M-GRADE's finalize cannot know a window exists.)"
            )

        exported = build_console(store=store).export_grades(world.run_id)
        if len(exported) != len(world.submissions):
            problems.append(
                f"the export returned {len(exported)} record(s) for a run with "
                f"{len(world.submissions)} graded submissions. FR-CONSOLE-22: provisional "
                f"grades export normally throughout the window."
            )
        elif not all(record.provisional for record in exported):
            problems.append(
                f"inside the review window the export marks provisional only "
                f"{[r.provisional for r in exported]} — every grade in it is provisional"
            )

        control = seed_scored_run(store, cohort_id="c-ts48-nowindow", run_id="r-ts48-nowindow",
                                  package_id="pkg-ts48-nowindow")
        build_console(store=store).finalize_batch(control.run_id, actor="teacher-a")
        delivered = build_console(store=store).export_grades(control.run_id)
        if len(delivered) != len(control.submissions) or any(r.provisional for r in delivered):
            problems.append(
                f"a run finalized with no review window exports {[r.provisional for r in delivered]}"
                f" as provisional — expected one non-provisional record per submission, so the "
                f"window's provisional marking is distinguishable from an export that marks "
                f"everything provisional"
            )
        _fail_with(problems)
    finally:
        store.close()


# --- TC-CONSOLE-23 — the export gate refuses real student text and records its outcome -----------


def test_tc_console_23_export_of_a_package_carrying_real_student_text_is_refused_and_recorded(
    tmp_data_dir,
):
    """`TC-CONSOLE-23` / `FR-CONSOLE-23` (invariant 19), negative — the flag is the package's.

    The package really carries real student text: a `real_verbatim` exemplar added through
    `PackageCatalog.add_exemplar`, which derives `package.contains_real_student_text = 1` in
    the same transaction (ADR-4). Rung 3 means the console is not told — it is asked to export
    the package, and the flag is what the store says. Three clauses, collected:

    1. the export is refused (`ProvenanceRefused`), read from the package, not from a
       caller-supplied argument — a gate the caller can argue past is not a gate;
    2. the provenance gate is a reachable screen (S14) for that version;
    3. the outcome is written to the validation record — read through a **fresh** console, so an
       outcome held only in the refusing instance's memory does not count as written.
    """
    store = open_store(tmp_data_dir)
    try:
        world = seed_scored_run(store)
        catalog = PackageCatalog(store.package(world.package_id), package_id=world.package_id)
        catalog.add_exemplar(world.package_version_id, "ex-verbatim-1", "C-01", "correct",
                             provenance="real_verbatim")
        flag = store.package(world.package_id).query(
            "SELECT contains_real_student_text AS flag FROM package WHERE package_id = :p",
            p=world.package_id,
        )[0]["flag"]
        assert flag == 1, "fixture: the real_verbatim exemplar must derive the package flag"

        problems: list[str] = []
        app = build_console(store=store)
        gate = app.render("/packages/{version}/export-gate", version=world.package_version_id)
        gate_text = visible_text(gate.html)
        if world.package_version_id not in gate_text or "real student text" not in gate_text:
            problems.append(
                "S14 did not render the export gate for the flagged version — the provenance "
                "gate must be a reachable screen (FR-CONSOLE-23)"
            )

        refused = False
        try:
            export_package(app, package_version=world.package_version_id, actor="teacher-a")
        except ProvenanceRefused:
            refused = True
        if not refused:
            problems.append(
                f"export_package exported {world.package_version_id} although the store's "
                f"package row says contains_real_student_text = 1. The console's gate reads "
                f"the flag from its caller's argument (default 0) instead of from the package, "
                f"and never reaches M-PKG's own refusal (PackageCatalog.export raises "
                f"ExportBlockedError) — FR-CONSOLE-23: export is unable to emit it."
            )

        outcome = build_console(store=store).validation_record(
            world.package_version_id
        ).provenance_gate_outcome
        if "refused" not in outcome:
            problems.append(
                f"a fresh console reads the version's validation record as {outcome!r} after "
                f"the gate ran. FR-CONSOLE-23: the gate's outcome is written to the validation "
                f"record — an outcome only the gating console instance remembers is "
                f"indistinguishable from a gate that was skipped (R71)."
            )
        _fail_with(problems)
    finally:
        store.close()


# --- TC-CONSOLE-24 — no blind labels this time: the absence, never last time's figure ------------


def test_tc_console_24_an_administration_without_blind_labels_never_shows_the_prior_figure(
    tmp_data_dir,
):
    """`TC-CONSOLE-24` / `FR-CONSOLE-24` (invariant 20) — two administrations of one package version.

    The first administration's validation record is real: written through `M-PKG`'s
    `record_promotion` (the durable `package_validation` row `M-STATS`' promote writes), with a
    distinctive κ of 0.7137 over 25 blind labels. The second administration — a second cohort and
    run on the **same package version** — collected none. Its rollup's agreement block must render
    the design's absence sentence, and the prior κ must appear nowhere in that position.

    **The positive control is what makes the absence mean something.** The first administration's
    own rollup must show its figure: a console that never reads the validation record renders the
    absence sentence on every rollup and would pass the second half vacuously. The shipped console
    does exactly that on a real store (`_render_rollup_screen`: "a real store renders the absence
    sentence too until the console reads M-STATS's validation record"), so this case is red until
    it reads the record — the defect is recorded in the PR.
    """
    store = open_store(tmp_data_dir)
    try:
        first = seed_scored_run(store, cohort_id="c-ts48-admin1", run_id="r-ts48-admin1",
                                package_id="pkg-ts48-shared")
        second = seed_scored_run(store, cohort_id="c-ts48-admin2", run_id="r-ts48-admin2",
                                 package_id="pkg-ts48-shared",
                                 reuse_version=first.package_version_id)
        assert second.package_version_id == first.package_version_id
        record_promotion(
            tmp_data_dir,
            package_version_id=first.package_version_id,
            cohort_id=first.cohort_id,
            cohorts_used=1,
            operational_count=0,
            blind_count=25,
            n=25,
            agreement_kappa=0.7137,
            weakest_per_population="{}",
            surface_proxy_flags="[]",
            message="blind sample promoted",
        )
        prior = store.durable().query(
            "SELECT agreement_kappa FROM package_validation WHERE package_version_id = :v",
            v=first.package_version_id,
        )
        assert [row["agreement_kappa"] for row in prior] == [0.7137], (
            "fixture: the first administration's figure must exist in the durable tier, or "
            "the absence asserted below is the absence of nothing"
        )

        problems: list[str] = []
        app = build_console(store=store)
        first_block = element_text(app.render("/runs/{id}/rollup", id=first.run_id).html,
                                   "agreement")
        if "0.7137" not in first_block:
            problems.append(
                f"the first administration's own rollup reads {first_block!r} although its "
                f"validation record holds kappa 0.7137 over n = 25. The console renders the "
                f"absence sentence on every real-store rollup (it never reads the record), so the "
                f"absence asserted for the second administration cannot tell honest absence from "
                f"not looking (FR-CONSOLE-24 needs the figure where it exists; FR-CONSOLE-10)."
            )

        page = app.render("/runs/{id}/rollup", id=second.run_id)
        block = element_text(page.html, "agreement")
        if NO_NEW_VALIDATION_EVIDENCE not in block:
            problems.append(
                f"the second administration's agreement block reads {block!r}. FR-CONSOLE-24: "
                f"with no blind labels it renders {NO_NEW_VALIDATION_EVIDENCE!r} — never a zero, "
                f"never a blank."
            )
        if "0.7137" in block:
            problems.append(
                "the prior administration's kappa renders in the second administration's "
                "agreement block. FR-CONSOLE-24 / RISK-08: last time's figure never stands there."
            )
        _fail_with(problems)
    finally:
        store.close()


# --- TC-CONSOLE-26 — S1 for a population the package was never administered to -------------------


def test_tc_console_26_s1_renders_no_borrowed_figure_for_a_population_never_administered(
    tmp_data_dir,
):
    """`TC-CONSOLE-26` / `FR-CONSOLE-26` — the package card, scoped to the current population.

    The package carries a real validation record, stored through `PackageCatalog.store_validation`
    under the six-part key, for population `pop-grade7-north` (agreement 0.8123, n 41). S1 is
    rendered for `pop-grade9-south`, where the package was never administered.

    Differential oracle: the same route for the population the record belongs to shows the
    record's figure — so the card can and does render figures — while the never-administered
    population's card renders the exact absence sentence and neither the figure, its sample size
    nor the other population's name.
    """
    store = open_store(tmp_data_dir)
    try:
        world = seed_scored_run(store)
        catalog = PackageCatalog(store.package(world.package_id), package_id=world.package_id)
        catalog.store_validation(
            world.package_version_id, "C-01", "pop-grade7-north", "edge-local",
            "/models/llama-3.3-70b.gguf@sha256:aaaa", "atomic", 0.8123, 41,
        )
        app = build_console(store=store)

        administered = visible_text(
            app.render("/packages", package_version=world.package_version_id,
                       population="pop-grade7-north").html
        )
        assert "0.8123" in administered, (
            "S1 does not show the validation record for the population it was measured on, so "
            "the absence assertion below could not tell a scoped card from a card that shows "
            f"nothing: {administered!r}"
        )

        never = app.render("/packages", package_version=world.package_version_id,
                           population="pop-grade9-south")
        text = visible_text(never.html)
        assert NO_VALIDATION_FOR_POPULATION in text, (
            f"S1 for a population the package was never administered to reads {text!r}; "
            f"FR-CONSOLE-26 requires {NO_VALIDATION_FOR_POPULATION!r}"
        )
        for borrowed in (r"0\.8123", r"\b41\b", r"pop-grade7-north"):
            assert not re.search(borrowed, text), (
                f"S1 for pop-grade9-south renders {borrowed!r} from pop-grade7-north's record. "
                f"FR-CONSOLE-26: never a figure borrowed from another population."
            )
    finally:
        store.close()
