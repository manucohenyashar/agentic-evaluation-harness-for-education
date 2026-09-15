"""`TS-48` (issue #129) — the two queues and the operator screens over really-ingested and
really-scored state: quarantine vs review (S8/S9), deterministic criteria kept off the teacher's
queue, S6 preflight and S8 quarantine.

Test plan §5.19, `TC-CONSOLE-11`, `-12`, `-28`, `-29`, all Integration / rung 3.

**Why these are not the clause cases again.** `CT-CONSOLE-C12` asserts the queue separation
on `StoreSpy`, where the console *fabricates* one standing review item and one standing
quarantine item because the double's reads return nothing (`ConsoleApp.review_queue`'s own
comment). A real store switches both fabrications off — so here the queues are populated by
the modules that populate them in production: `M-INGEST`'s `Ingestor` parks submissions and
trips the V4 breaker (scripted VLM, pass-through sanitizer — `tests/support/console_world.py`),
`M-DET`/`M-GRADE` score and route. The console is read against the store, and every absence is
anchored by first reading the store to show the thing it must not render really exists.

**Written ahead of implementation.** The issue says `yes`; stale — `M-CONSOLE` landed (#122,
#124, #126). Failures here are defects in the landed console, named in their messages.
"""

from __future__ import annotations

import html as html_lib
import re
from collections import deque

import pytest

from aeh.console import SCREENS, build_console, render_preflight
from aeh.conf import CohortRef, resolve_run_config
from aeh.grade import GradingService
from aeh.orch import Orchestrator
from aeh.store import open_store
from tests.support.conf_builders import edge_cfg
from tests.support.console_world import (
    MCQ_CRITERIA,
    IngestWorld,
    rows,
    seed_scored_run,
)
from tests.support.grade_vocabulary import write_criterion_scores

pytestmark = [pytest.mark.integration]

_REVIEW_ROUTE = SCREENS["S9"]
_QUARANTINE_ROUTE = SCREENS["S8"]


def _fail_with(problems: list[str]) -> None:
    assert not problems, "\n\n".join(problems)


def _queue_teacher_items(store, cohort_id: str, submission_ids, criterion_ids) -> None:
    """Judged scores awaiting the teacher.

    **Disclosed stand-in** for `M-AGG`'s routing: `criterion_score.routing = 'queued'` is the
    advisory routing `M-REVIEW` admits into the teacher's queue (`review._admitted`). Nothing is
    planted in `review_queue`: `M-GRADE` is that table's only production writer, and what it
    writes there is operator routing for missing inputs ("rescan"), not teacher review items.
    """
    cohort = store.cohort(cohort_id)
    with cohort.transaction() as tx:
        for submission_id in submission_ids:
            for criterion_id in criterion_ids:
                tx.execute(
                    "INSERT OR REPLACE INTO criterion_score (run_id, submission_id, criterion_id, band, "
                    "points, judge_count, routing, state) VALUES (COALESCE((SELECT run_id FROM run ORDER BY COALESCE(started_at, '') DESC, run_id DESC LIMIT 1), 'run-fixture'), :s, :c, 'B2', 2.0, 3, "
                    "'queued', 'provisional_unreviewed')",
                    s=submission_id, c=criterion_id,
                )


def _create_run(store, world: IngestWorld, run_id: str) -> str:
    resolved = resolve_run_config(
        edge_cfg(), CohortRef(cohort_id=world.cohort_id, consent_class="synthetic")
    )
    return Orchestrator(store).create_run(world.cohort_id, world.version, resolved, run_id=run_id)


def _console_links(page_html: str) -> set[str]:
    """Every in-console target a page offers: `href`, `action` and `formaction` values that are
    console routes (the stylesheet and image assets are not navigation)."""
    targets = set()
    for attribute in ("href", "action", "formaction"):
        for value in re.findall(rf'{attribute}="([^"]*)"', page_html):
            value = html_lib.unescape(value)
            if value.startswith("/") and not value.startswith("/assets/"):
                targets.add(value.split("?", 1)[0])
    return targets


def _reachable_from(app, route: str, **params) -> dict[str, str]:
    """Breadth-first over the console's own link graph, starting at `route`. Returns every
    page reached, by route, with its HTML."""
    seen: dict[str, str] = {}
    frontier = deque([(route, params)])
    while frontier:
        current, current_params = frontier.popleft()
        if current in seen:
            continue
        page = app.render(current, **current_params).html
        seen[current] = page
        for target in _console_links(page):
            if target not in seen:
                frontier.append((target, {}))
    return seen


# --- TC-CONSOLE-11 — quarantine and review: separate routes, counts, and no path between ---------


def test_tc_console_11_no_quarantine_item_is_reachable_from_the_review_queue(tmp_data_dir):
    """`TC-CONSOLE-11` / `FR-CONSOLE-11` (invariant 6) — a run carrying both kinds of item.

    Quarantine items are real: `M-INGEST` parks a V4 mismatch and a V2 failure. Review items
    are judged scores queued for the teacher on the two submissions that ingested clean.
    Collected clauses:

    1. **separate counts** — the review queue's flagged count is the four queued judged items,
       the quarantine count is the store's parked rows, and neither view lists the other's;
    2. **reachability** — a breadth-first traversal of the console's link graph from the review
       route reaches no quarantine route and renders no parked submission's id; the quarantine
       page does render those ids, so the signature the traversal looks for is a real one. The
       shipped pages carry no navigation links today, so the traversal visits the review page
       alone — the clause is the review page itself until links exist, and the traversal is
       what keeps it honest when they do (the extractor is checked on a page built with links);
    3. **the differential** — closing one quarantine item moves the operator's count by exactly
       one and the teacher's count not at all.
    """
    store = open_store(tmp_data_dir)
    try:
        world = IngestWorld(store, "c-ts48-queues", "pkg-ts48-queues")
        clean = [world.submit_match(f"clean-{i}").submission_id for i in range(2)]
        world.submit_mismatch("parked-mismatch")
        world.submit("parked-v2", printed=world.package_id, answers={"Q2": "bridge"})
        run_id = _create_run(store, world, "r-ts48-queues")
        _queue_teacher_items(store, world.cohort_id, clean, ("C1", "C2"))
        # The grade pass writes M-GRADE's operator routing for every missing input — including
        # "rescan" rows for the parked papers — so the tempting cross-queue rows are real.
        GradingService(store).compute_all(run_id)
        routed = {r["submission_id"] for r in rows(world.handle,
                                                   "SELECT submission_id FROM review_queue")}
        assert routed, "fixture: M-GRADE wrote no review_queue routing for the missing inputs"

        parked = [r["submission_id"] for r in rows(
            world.handle, "SELECT submission_id FROM submission WHERE quarantined = 1")]
        assert len(parked) == 2, f"fixture: M-INGEST must park both papers, got {parked!r}"

        problems: list[str] = []
        app = build_console(store=store)
        review = app.review_queue(run_id)
        quarantine = app.quarantine(world.cohort_id)
        if review.queue.flagged_total != 4 or len(review.queue.shown) != 4:
            problems.append(
                f"the review queue reports flagged={review.queue.flagged_total}, "
                f"shown={len(review.queue.shown)} for a run with 4 judged items queued for the "
                f"teacher (criterion_score rows routed 'queued', the population M-REVIEW admits). "
                f"The console reads `review_queue WHERE run_id = :run_id ORDER BY rank_position` "
                f"instead — columns the cohort-tier table does not have, so the read errors, the "
                f"error is swallowed and the teacher's queue is empty on every real store. (Merely "
                f"dropping the two columns would not fix it: M-GRADE writes operator 'rescan' rows "
                f"into that table.) Separation asserted over an empty queue proves nothing "
                f"(FR-CONSOLE-11)."
            )
        if sorted(item.submission_id for item in quarantine.queue.shown) != sorted(parked):
            problems.append(
                f"the quarantine view lists {[i.submission_id for i in quarantine.queue.shown]}, "
                f"the store parks {parked}"
            )
        if {item.submission_id for item in review.queue.shown} & set(parked):
            problems.append("a parked submission is listed in the teacher's review queue")

        assert _console_links('<a href="/quarantine">q</a><form action="/runs/r/review">') == {
            "/quarantine", "/runs/r/review"
        }, "the link extractor does not find links on a page built to contain them"
        quarantine_page = app.render(_QUARANTINE_ROUTE).html
        assert all(submission in quarantine_page for submission in parked), (
            "the quarantine page does not render the parked ids, so their absence from the "
            "review side would not show separation"
        )
        reached = _reachable_from(app, _REVIEW_ROUTE, id=run_id)
        if _QUARANTINE_ROUTE in reached:
            problems.append(f"the quarantine route is reachable from {_REVIEW_ROUTE}")
        for route, page in reached.items():
            leaked = [submission for submission in parked if submission in page]
            if leaked:
                problems.append(
                    f"{route} (reachable from the review queue) renders parked submission(s) "
                    f"{leaked} — invariant 6: no quarantine item is reachable from the review queue"
                )

        outcome = app.perform("resolve quarantine item", submission_id=parked[0],
                              resolution="unresolvable")
        assert outcome.dispatched, f"the S8 close did not dispatch: {outcome.detail}"
        fresh = build_console(store=store)
        if fresh.quarantine(world.cohort_id).queue.flagged_total != len(parked) - 1:
            problems.append(
                f"closing one quarantine item left the operator count at "
                f"{fresh.quarantine(world.cohort_id).queue.flagged_total}, expected "
                f"{len(parked) - 1}"
            )
        if fresh.review_queue(run_id).queue.flagged_total != review.queue.flagged_total:
            problems.append("closing a quarantine item moved the teacher's review count")
        _fail_with(problems)
    finally:
        store.close()


# --- TC-CONSOLE-12 — deterministic criteria never reach the review queue -------------------------


def test_tc_console_12_no_deterministic_criterion_appears_in_the_review_queue(tmp_data_dir):
    """`TC-CONSOLE-12` / `FR-CONSOLE-12` (invariant 7) — a package with three multiple-choice
    criteria and two judged ones, scored for real.

    The tempting row is real, not planted: sub-03's C-03 mark is ambiguous, `M-DET` parks it as
    `unresolved_selection`, and `M-GRADE`'s missing-input routing writes a `review_queue` row
    naming C-03 — a deterministic criterion in the very table the review screen reads. The
    judged criteria's items are queued for the teacher beside it.

    Exact value: the teacher's queue shows every judged item and zero items for C-01..C-03, and
    the rendered review page names no deterministic criterion. The first half is what keeps the
    second from being an absence over an empty queue.
    """
    store = open_store(tmp_data_dir)
    try:
        world = seed_scored_run(store, with_open_criteria=True,
                                choices=[("A", "B", "C"), ("A", "B", "C"), ("A", "B", None)])
        cohort = store.cohort(world.cohort_id)
        deterministic = {criterion_id for criterion_id, _, _ in MCQ_CRITERIA}
        tempting = [r for r in rows(cohort, "SELECT criterion_id FROM review_queue")
                    if r["criterion_id"] in deterministic]
        assert tempting, (
            "fixture: no deterministic criterion reached review_queue, so this case would assert "
            "an absence nobody was tempted to break"
        )
        judged = world.submissions[:2]
        _queue_teacher_items(store, world.cohort_id, judged, ("C-10",))

        app = build_console(store=store)
        shown = app.review_queue(world.run_id).queue.shown
        assert sorted((i.submission_id, i.criterion_id) for i in shown) == sorted(
            (submission, "C-10") for submission in judged
        ), (
            f"the teacher's queue shows {[(i.submission_id, i.criterion_id) for i in shown]} — "
            f"expected exactly the {len(judged)} judged C-10 items routed 'queued' (M-REVIEW's "
            f"admitted population). The console reads review_queue by run_id/rank_position — "
            f"columns that table does not have — so on a real store its queue is always empty "
            f"and the absence asserted next would be an absence over nothing; and that table "
            f"holds M-GRADE's rescan row for deterministic C-03, so reading it without the two "
            f"columns would break invariant 7 instead (FR-CONSOLE-12)."
        )
        leaked = sorted({i.criterion_id for i in shown} & deterministic)
        assert not leaked, (
            f"deterministic criteria {leaked} appear in the review queue — invariant 7: none does"
        )
        page = html_lib.unescape(app.render(_REVIEW_ROUTE, id=world.run_id).html)
        for criterion_id in sorted(deterministic):
            assert criterion_id not in page, (
                f"the review page names deterministic criterion {criterion_id}"
            )
    finally:
        store.close()


# --- TC-CONSOLE-28 — S6: the breaker withholds run start, outstanding quarantine does not --------


def test_tc_console_28_preflight_withholds_start_on_the_breaker_and_not_on_quarantine(
    tmp_data_dir,
):
    """`TC-CONSOLE-28` / `FR-CONSOLE-28` — two cohorts, ingested for real.

    * Tripped: 20 submissions, 4 of them V4 mismatches — 20% at the 20-submission minimum, the
      `TC-INGEST-28` trip cell — so `M-INGEST` writes the `v4_cohort_breaker` row.
    * Untripped with quarantine outstanding: 20 submissions, 1 mismatch (5%) and 1 V2 failure —
      two parked items, no breaker row.

    Exact behaviour, read against the store: the per-gate ladder reports all five gates with the
    values the stored gate columns imply (V4 fails in both cohorts, V0 passes); start-run is
    withheld exactly when the breaker row exists; the untripped cohort's view counts the store's
    parked rows and still offers start-run. The rendered S6 page must say the same thing the
    view does — the differential between the two pages is the rendered half.
    """
    store = open_store(tmp_data_dir)
    try:
        tripped = IngestWorld(store, "c-ts48-tripped", "pkg-ts48-tripped")
        for index in range(20):
            if index in (3, 8, 13, 18):
                tripped.submit_mismatch(f"t-{index:02d}")
            else:
                tripped.submit_match(f"t-{index:02d}")
        outstanding = IngestWorld(store, "c-ts48-outstanding", "pkg-ts48-outstanding")
        for index in range(20):
            if index == 5:
                outstanding.submit_mismatch(f"o-{index:02d}")
            elif index == 11:
                outstanding.submit(f"o-{index:02d}", printed=outstanding.package_id,
                                   answers={"Q2": "bridge"})
            else:
                outstanding.submit_match(f"o-{index:02d}")

        breaker_rows = rows(tripped.handle, "SELECT flagged, ingested FROM v4_cohort_breaker")
        assert [(r["flagged"], r["ingested"]) for r in breaker_rows] == [(4, 20)], (
            f"fixture: M-INGEST must trip the breaker at 4/20, got {breaker_rows!r}"
        )
        assert not rows(outstanding.handle, "SELECT 1 FROM v4_cohort_breaker"), (
            "fixture: the outstanding-quarantine cohort must not trip the breaker"
        )
        parked = len(rows(outstanding.handle,
                          "SELECT 1 FROM submission WHERE quarantined = 1"))
        assert parked == 2, f"fixture: two parked items expected, got {parked}"

        withheld = render_preflight(tripped.cohort_id, store=store)
        assert set(withheld.gates) == {"v0", "v1", "v2", "v3", "v4"}, (
            f"S6's ladder reports gates {sorted(withheld.gates)}; FR-CONSOLE-28 reports each gate"
        )
        assert withheld.gates["v0"] == "pass" and withheld.gates["v4"] == "fail", (
            f"the tripped cohort's ladder reads {withheld.gates!r}; its stored V0 columns all "
            f"pass and four V4 columns mismatch"
        )
        assert withheld.breaker is not None and withheld.breaker["flagged"] == 4
        assert withheld.start_run_available is False, (
            "S6 offers start-run with the V4 cohort breaker tripped — FR-CONSOLE-28 withholds it"
        )

        allowed = render_preflight(outstanding.cohort_id, store=store)
        assert allowed.breaker is None and allowed.quarantined == parked, (
            f"the untripped cohort's view reports breaker={allowed.breaker!r}, "
            f"quarantined={allowed.quarantined}; the store holds no breaker row and {parked} "
            f"parked items"
        )
        assert allowed.start_run_available is True, (
            "S6 withholds start-run because quarantine items are outstanding — FR-CONSOLE-28: the "
            "run may start while they remain (quarantine is the operator's parallel workstream)"
        )

        app = build_console(store=store)
        withheld_page = html_lib.unescape(app.render(SCREENS["S6"], id=tripped.cohort_id).html)
        allowed_page = html_lib.unescape(app.render(SCREENS["S6"], id=outstanding.cohort_id).html)
        assert "start run withheld" in withheld_page and "start run available" not in withheld_page, (
            f"the tripped cohort's S6 page does not say start-run is withheld: {withheld_page!r}"
        )
        assert "start run available" in allowed_page, (
            f"the outstanding-quarantine cohort's S6 page does not offer start-run: "
            f"{allowed_page!r}"
        )
        for gate in ("v0", "v1", "v2", "v3", "v4"):
            assert f"{gate} (" in withheld_page, f"S6's rendered ladder omits gate {gate}"
    finally:
        store.close()


# --- TC-CONSOLE-29 — S8: never reassigns, shows the real crop, closes to MISSING / incomplete ----


def test_tc_console_29_s8_never_reassigns_shows_the_crop_and_closes_to_incomplete(tmp_data_dir):
    """`TC-CONSOLE-29` / `FR-CONSOLE-29` — S8 over three parked papers ingested for real: a V4
    mismatch, a paper with an unreadable (ambiguous) selection mark, and a paper with a described
    region `M-INGEST` cropped and stored (its `crop_ref` is a content hash in the blob store).

    Collected clauses:

    1. **never auto-reassigns** — after S8 renders and after an item is closed, the mismatch's
       V4 outcome is still `mismatch`, it is still parked, and its match proposal is still a
       proposal (`resolution`/`resolved_at` NULL: those columns are the human's);
    2. **the crop** — every image S8 shows for an item is that item's own stored crop (its
       content hash, resolvable in the blob store), and the described region's crop is among them.
       A single static asset shown beside every item is not "the image crop for the unreadable
       mark";
    3. **closing as unresolvable** — the closed paper is released from the park, and once the
       run's grade policy runs (`GradingService.compute_all`, the shipped rule) its grade is
       `incomplete` with every criterion missing and no grade. A scored control paper (the clean
       one, its criteria settled through the disclosed M-AGG stand-in) must come out *not*
       incomplete, so "incomplete" is shown to be the closure's consequence rather than every
       paper's state in an unscored world.

    Not asserted here, and why: `M-INGEST` stores no crop for a `selection_mark` region
    (FR-INGEST-13 requires `crop_ref` for `described_graphic` only), and `M-GRADE`'s stored
    `total` for an all-missing paper is that module's column (`CT-GRADE-07`), not this screen's.
    """
    store = open_store(tmp_data_dir)
    try:
        world = IngestWorld(store, "c-ts48-s8", "pkg-ts48-s8")
        clean = world.submit_match("clean").submission_id
        mismatch = world.submit_mismatch("mismatch").submission_id
        mark = ("\n<!-- region: kind=selection_mark question_id=Q1 selection_state=ambiguous "
                "crop=10,20,30,40 -->\nX\n<!-- /region -->")
        unreadable = world.submit("unreadable", printed=world.package_id,
                                  answers={"Q2": "the forces balance"},
                                  extra_regions=mark).submission_id
        graphic = ("\n<!-- region: kind=described_graphic element_kind=graph crop=5,5,50,50 -->\n"
                   "A bar chart of monthly rainfall\n<!-- /region -->")
        described = world.submit("described", printed=world.package_id,
                                 answers={"Q1": "evaporation then rain"},
                                 extra_regions=graphic).submission_id
        parked = {r["submission_id"] for r in rows(
            world.handle, "SELECT submission_id FROM submission WHERE quarantined = 1")}
        assert parked == {mismatch, unreadable, described}, f"fixture: parked {parked!r}"
        crops = rows(
            world.handle,
            "SELECT d.submission_id, r.crop_ref FROM document_region r JOIN document d "
            "ON d.document_id = r.document_id WHERE r.crop_ref IS NOT NULL",
        )
        described_crop = [r["crop_ref"] for r in crops if r["submission_id"] == described]
        assert len(described_crop) == 1 and world.blobs.get(described_crop[0]), (
            f"fixture: M-INGEST must store the described region's crop, got {crops!r}"
        )
        run_id = _create_run(store, world, "r-ts48-s8")

        problems: list[str] = []
        app = build_console(store=store)
        page = app.render(_QUARANTINE_ROUTE).html
        shown_sources = re.findall(r'<img[^>]*src="([^"]*)"', page)
        known = {r["crop_ref"] for r in crops}
        foreign = sorted({src for src in shown_sources if not any(ref in src for ref in known)})
        if foreign:
            problems.append(
                f"S8 shows image(s) {foreign} that are no stored crop — the page renders the same "
                f"static placeholder beside every parked item (including the V4 mismatch, which "
                f"has no mark at all) instead of the region's crop_ref. FR-CONSOLE-29: S8 shows "
                f"the image crop for the unreadable mark and for any described region."
            )
        if not any(described_crop[0] in src for src in shown_sources):
            problems.append(
                f"S8 does not show the described region's stored crop {described_crop[0][:12]}… "
                f"for {described}"
            )
        outcome = app.perform("resolve quarantine item", submission_id=unreadable,
                              resolution="unresolvable")
        if not outcome.dispatched:
            problems.append(f"closing {unreadable} as unresolvable did not dispatch: "
                            f"{outcome.detail}")
        after = {r["submission_id"]: r for r in rows(
            world.handle, "SELECT submission_id, quarantined, v4_match, ingest_status "
                          "FROM submission")}
        if after[mismatch]["v4_match"] != "mismatch" or after[mismatch]["quarantined"] != 1:
            problems.append(
                f"the V4 mismatch changed without an operator decision: {after[mismatch]!r}"
            )
        proposals = rows(world.handle, "SELECT resolution, resolved_at FROM "
                                       "assessment_match_proposal WHERE submission_id = :s",
                         s=mismatch)
        if not proposals or any(p["resolution"] or p["resolved_at"] for p in proposals):
            problems.append(
                f"the mismatch's proposal is {proposals!r}; a proposal is never resolved by the "
                f"console on its own — S8 never auto-reassigns"
            )
        if after[unreadable]["quarantined"] != 0:
            problems.append(f"{unreadable} is still parked after being closed")

        write_criterion_scores(world.handle, [(clean, "C1", "B2", 3.0, "auto"),
                                              (clean, "C2", "B2", 3.0, "auto")])
        GradingService(store).compute_all(run_id)
        control = rows(world.handle, "SELECT state, criteria_missing FROM submission_grade "
                                     "WHERE submission_id = :s AND is_current = 1", s=clean)
        assert control and control[0]["state"] != "incomplete" and not control[0][
            "criteria_missing"
        ], f"fixture: the scored control paper must not be incomplete: {control!r}"
        grade = rows(world.handle, "SELECT state, grade, total, criteria_total, criteria_missing "
                                   "FROM submission_grade WHERE submission_id = :s AND "
                                   "is_current = 1", s=unreadable)
        if len(grade) != 1:
            problems.append(f"no current grade for the closed paper: {grade!r}")
        else:
            settled = grade[0]
            if settled["state"] != "incomplete" or settled["grade"] is not None:
                problems.append(f"the closed paper's grade is {settled!r}; expected incomplete "
                                f"with no grade")
            if settled["criteria_missing"] != settled["criteria_total"] or not settled[
                "criteria_total"
            ]:
                problems.append(f"the closed paper's criteria are not all missing: {settled!r}")
        _fail_with(problems)
    finally:
        store.close()
