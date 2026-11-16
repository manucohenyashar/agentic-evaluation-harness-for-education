"""Validity T4 (issue #897): label identity, origin, draw-time routing, the blind seat and the
actor, over a real store behind a real console. These are the cases whose implementations have
merged, so they run unmarked: #867 (PR #921, labels), #875 (PR #924, the seat and the stored
draw).

| Case | What it pins | Rung |
|---|---|---|
| TC-REG-24 | SV-12: a console blind label's `run_id` is not the cohort id and its `student_ref` is not a submission id. The full TC-REVIEW-100 oracle runs over it | 3, HTTP |
| TC-REVIEW-101 | origin derivation: base, base + escalation, base + random arm give base, escalation, random_arm; an underivable cell is refused by name and writes nothing; no `"escalation"` default in the source | 1 (table) + 3 (HTTP) + census |
| TC-REVIEW-102 | a cell `queued` at draw and accepted before Finish: the blind label keeps `queued`, the accept label carries `reviewed`, and no later action rewrites a stored routing | 3, HTTP |
| TC-REVIEW-106 | the seat's exact key set, its answer text and bands, and a query trace that never touches `criterion_score`, `verdict` or `extraction` | 3, service over the real store |
| TC-REVIEW-107 (b) | every label the console writes, blind or operational, has actor `teacher` | 3, HTTP |

**Disclosed departures (in the PR as well).**

1. *The Finish stand-in.* The console's `blind-sample finish` action is S12's (#882) and has
   not landed. These cases draft over HTTP through the shipped `blind-sample submission`
   action, then close the draw through the console's own review service
   (`label_identity_world.ServedRun.finish_through_the_consoles_service`). That is the same
   service, actor and scope. TC-REVIEW-100 and TC-REVIEW-107 (a), which drive Finish over
   HTTP, are written ahead in `test_tc_review_100_107_console_blind_finish.py`.
2. *The mutation sites moved.* The plan's mutation names `console/effects.py:412-445`. #867
   fixed SV-12 in `review/actions.py`: `_attribution_run` used to fall back to the cohort id,
   and `_persist_label` wrote `student_ref=item.submission_id`. The mutation check restores
   those two, and TC-REG-24 goes red under each.
3. *TC-REVIEW-106 is traced at the service.* The seat shape is M-REVIEW's
   (`ReviewService.blind_seats`, #875). The console's `GET /api/v1/blind-seats` still serves
   #875-era identity fields until S12, so its allowlist is TC-CONSOLE-107's (T8). Each console
   request rebuilds the review service, and that rebuild reads `criterion_score` for the queue.
   So the trace window is the draw and the seat reads on a built service. That is the plan's
   "during `blind_sample` and seat reads". `document_region` is on the allowlist: it is the
   canonical artifact's region, where the answer text comes from.
4. *TC-REVIEW-107's operator arm is not implementable as specified.* No CLI or live-check path
   writes a label today. The review constructors default to `actor="teacher"`, and nothing in
   `src/` builds a review service with `actor="operator"`. Asserting that a hand-built
   operator service records `operator` would be a tautology. So (b) pins the console half,
   and the operator half is reported as a gap.
"""

from __future__ import annotations

import re
import sqlite3

import pytest

from harness.corpora import dev_pipe
from tests.support.label_identity_world import (
    assert_agreement_scope_is_accepted,
    assert_label_identity,
    served_run,
)
from tests.support.source_tree import package_source

pytestmark = pytest.mark.integration


def _draft_blind(served, cells_and_bands) -> None:
    """Draw (the console's blind-seats read draws once), then draft each cell over HTTP."""
    status, read = served.get("/api/v1/blind-seats", run_id=served.run_id)
    assert status == 200, f"the blind-seats read answered {status}: {read!r}"
    drawn = {(seat["submission_id"], seat["criterion_id"]) for seat in read["seats"]}
    for (submission_id, criterion_id), band in cells_and_bands:
        assert (submission_id, criterion_id) in drawn, (
            f"fixture: {submission_id}/{criterion_id} is not in the draw {sorted(drawn)}")
        served.dispatched("blind-sample submission", run_id=served.run_id,
                          submission_id=submission_id, criterion_id=criterion_id, band=band)


def _review(served, cell, decision: str, band: str | None = None) -> dict:
    submission_id, criterion_id = cell
    params = {"run_id": served.run_id, "submission_id": submission_id,
              "criterion_id": criterion_id, "decision": decision}
    if band is not None:
        params["new_band"] = band
    return served.dispatched("review action", **params)


def _other_band(served, cell, ordinal: int) -> str:
    """A band for `cell` that differs from its stored band, so an edit or override is one."""
    stored = served.rows("SELECT band FROM criterion_score WHERE run_id = ? AND "
                         "submission_id = ? AND criterion_id = ?", served.run_id, *cell)[0]["band"]
    for candidate in (ordinal, ordinal - 1, ordinal + 1, 0):
        band = dev_pipe.band_at(cell[1], candidate)
        if band != stored:
            return band
    raise AssertionError(f"fixture: no band other than {stored!r} for {cell}")


def _label_and_review_the_world(served) -> None:
    """The TC-REVIEW-100 drive, minus S12: three C1 seats drafted over HTTP with a spread of
    bands, Finish, then one accept, one edit and one override on the C2 cells over HTTP."""
    c1 = served.cells("C1")
    c2 = served.cells("C2")
    assert len(c1) == 3 and len(c2) == 3, f"fixture: queued cells C1={c1} C2={c2}"
    _draft_blind(served, [(cell, dev_pipe.band_at("C1", ordinal))
                          for cell, ordinal in zip(c1, (1, 3, 5))])
    report = served.finish_through_the_consoles_service()
    assert len(report.label_ids) == 3, report
    _review(served, c2[0], "accept")
    _review(served, c2[1], "edit", _other_band(served, c2[1], 2))
    _review(served, c2[2], "override", _other_band(served, c2[2], 4))


# --- TC-REG-24 -------------------------------------------------------------------------------


def test_tc_reg_24_a_console_blind_label_names_the_run_and_the_roster_student(
        tmp_path, monkeypatch, network_guard):
    """TC-REG-24 (SV-12 pinned): a blind label written through the console carries the run's
    id, not the cohort's, and the student's roster ref, not the submission id. The full
    TC-REVIEW-100 row oracle runs over every label: the three blind labels and the accept,
    edit and override labels. Agreement over the blind labels is a figure the console's scope
    rule accepts.

    Mutation (checked, see the module docstring): `_attribution_run` falling back to the
    cohort id turns `run_id` red. `_persist_label` writing `student_ref=item.submission_id`
    turns `student_ref` red."""
    with served_run(tmp_path / "w", monkeypatch, network_guard) as served:
        _label_and_review_the_world(served)
        labels = served.labels()
        blind = [label for label in labels if label["label_type"] == "blind"]
        operational = [label for label in labels if label["label_type"] != "blind"]
        assert len(blind) == 3 and len(operational) == 3, (
            f"expected 3 blind and 3 operational labels, got "
            f"{[(label['label_type'], label['review_queue_action']) for label in labels]}")
        for label in blind:
            assert label["run_id"] != served.cohort_id, (
                f"a console blind label is keyed on the cohort {served.cohort_id!r} (SV-12)")
            submission_id = str(label["score_id"]).rsplit(":", 1)[0]
            assert label["student_ref"] != submission_id, (
                f"a console blind label names the submission {submission_id!r} as its "
                "student (SV-12)")
        assert_label_identity(served, labels)
        assert_agreement_scope_is_accepted(served, "C1", blind_count=3)


# --- TC-REVIEW-101 ---------------------------------------------------------------------------


@pytest.mark.parametrize("units, origin", [
    (("base",), "base"),
    (("base", "escalation"), "escalation"),
    (("base", "random_arm"), "random_arm"),
    (("base", "escalation", "random_arm"), "random_arm"),
], ids=["base", "base+escalation", "base+random_arm", "all-three"])
def test_tc_review_101_a_origin_is_derived_from_the_cells_scoring_units(units, origin):
    """TC-REVIEW-101, the table (rung 1): a cell's work-unit origins derive the label origin.
    The random arm wins over an escalation, which wins over the base panel (FR-REVIEW-25)."""
    from aeh.review.actions import derive_label_origin

    assert derive_label_origin(list(units), "sub-x/C1") == origin


@pytest.mark.parametrize("units", [(), ("mystery",), ("base", "mystery")],
                         ids=["no-units", "unknown-origin", "base+unknown"])
def test_tc_review_101_b_an_underivable_cell_is_refused_by_name(units):
    """TC-REVIEW-101, the negative (rung 1): no units, or an origin outside the three, is
    refused naming the cell. It is never defaulted to `escalation`."""
    from aeh.review import LabelProvenanceError
    from aeh.review.actions import derive_label_origin

    with pytest.raises(LabelProvenanceError) as refused:
        derive_label_origin(list(units), "sub-underivable/C9")
    assert "sub-underivable/C9" in str(refused.value)


def test_tc_review_101_c_origins_through_the_console_and_the_refusal_writes_nothing(
        tmp_path, monkeypatch, network_guard):
    """TC-REVIEW-101 at rung 3. Three queued C2 cells have work units base only, base +
    escalation, and base + random arm. An accept through the console's review action labels
    them `base`, `escalation` and `random_arm`. A C1 cell whose scoring units are gone has no
    derivable provenance: its review action is refused naming the cell, and no label is
    written for it."""
    with served_run(tmp_path / "w", monkeypatch, network_guard) as served:
        base_only, with_escalation, with_random = served.cells("C2")
        underivable = served.cells("C1")[0]

        def units(cell, *origins):
            served.execute("DELETE FROM work_unit WHERE run_id = ? AND submission_id = ? AND "
                           "criterion_id = ? AND stage = 'score'", served.run_id, *cell)
            for origin in origins:
                served.execute(
                    "INSERT INTO work_unit (work_id, run_id, submission_id, criterion_id, "
                    "stage, status, origin) VALUES (?, ?, ?, ?, 'score', 'done', ?)",
                    f"t4-{origin}:{cell[0]}:{cell[1]}", served.run_id, *cell, origin)

        units(base_only, "base")
        units(with_escalation, "base", "escalation")
        units(with_random, "base", "random_arm")
        units(underivable)

        for cell in (base_only, with_escalation, with_random):
            _review(served, cell, "accept")
        by_cell = {label["score_id"]: label["origin"] for label in served.labels()}
        assert by_cell == {
            f"{base_only[0]}:C2": "base",
            f"{with_escalation[0]}:C2": "escalation",
            f"{with_random[0]}:C2": "random_arm",
        }, by_cell

        before = len(served.labels())
        status, outcome = served.action(
            "review action", run_id=served.run_id, submission_id=underivable[0],
            criterion_id="C1", decision="accept")
        assert status == 200 and outcome.get("dispatched") is False, (status, outcome)
        assert f"{underivable[0]}/C1" in str(outcome.get("detail")), (
            f"the refusal does not name the cell: {outcome!r}")
        assert len(served.labels()) == before, "a refused review wrote a label"
        assert not [label for label in served.labels()
                    if label["score_id"] == f"{underivable[0]}:C1"]


#: An origin default: `getattr(row, "origin", "escalation")` or `... or "escalation"`.
_ESCALATION_DEFAULT = re.compile(
    r"""getattr\([^)]*["']origin["']\s*,\s*["']escalation["']\s*\)"""
    r"""|\bor\s+["']escalation["']""")

#: The pre-#867 line in `review/blind.py` (`git show 1be9d80^`), the census's positive control.
_PRE_867_LINE = 'origin=str(getattr(row, "origin", "escalation") or "escalation")'


def test_tc_review_101_d_census_no_escalation_default_in_m_review():
    """TC-REVIEW-101's code census: no label origin defaults to `"escalation"` anywhere in
    M-REVIEW. The pattern is positive-controlled against the line #867 removed from
    `review/blind.py`, so a regex that can match nothing cannot pass."""
    import aeh.review as review

    assert _ESCALATION_DEFAULT.search(_PRE_867_LINE), "census pattern lost its positive control"
    source = package_source(review)
    hits = [line.strip() for line in source.splitlines() if _ESCALATION_DEFAULT.search(line)]
    assert not hits, f"M-REVIEW defaults a label origin to 'escalation': {hits}"


# --- TC-REVIEW-102 ---------------------------------------------------------------------------


def test_tc_review_102_a_blind_label_keeps_the_routing_its_cell_had_at_draw(
        tmp_path, monkeypatch, network_guard):
    """TC-REVIEW-102 (FR-REVIEW-29). A C1 cell is `queued` when the draw opens. It is drafted
    blind, then accepted through the console's review action before Finish, so the cell is
    `reviewed` by the time the blind label is written. Expected:
    - the blind label's routing is `queued`, the cell's routing at draw time, not now;
    - the accept's operational label carries `reviewed`;
    - no later action (an edit elsewhere, a refused second Finish, a seat read) rewrites any
      stored label's routing.

    A second C1 cell is `provisional` at draw and goes through the same steps. Its blind label
    must say `provisional`. This is what makes the case sensitive: the console rebuilds its
    review service per request, and a rebuilt service no longer loads a reviewed cell, so a
    writer that read the routing at Finish would fall back to `queued`. On the queued cell that
    fallback is indistinguishable from the right answer. On the provisional cell it is not
    (mutation-checked: reading the routing at close turns this red)."""
    with served_run(tmp_path / "w", monkeypatch, network_guard) as served:
        queued, provisional = served.cells("C1")[:2]
        served.execute("UPDATE criterion_score SET routing = 'provisional' WHERE run_id = ? "
                       "AND submission_id = ? AND criterion_id = ?", served.run_id, *provisional)
        _draft_blind(served, [(queued, dev_pipe.band_at("C1", 2)),
                              (provisional, dev_pipe.band_at("C1", 3))])
        for cell in (queued, provisional):
            _review(served, cell, "accept")
            now = served.rows("SELECT routing FROM criterion_score WHERE run_id = ? AND "
                              "submission_id = ? AND criterion_id = ?", served.run_id, *cell)
            assert now[0]["routing"] == "reviewed", (
                f"fixture: the accept left {cell} routed {now[0]['routing']!r}, so a label "
                "reading the routing at close could not be told from one reading it at draw")
        served.finish_through_the_consoles_service()

        for cell, at_draw in ((queued, "queued"), (provisional, "provisional")):
            score_id = f"{cell[0]}:C1"
            labels = [label for label in served.labels() if label["score_id"] == score_id]
            routing = {label["label_type"]: label["routing"] for label in labels}
            assert routing.get("blind") == at_draw, (
                f"the blind label on {score_id} records routing {routing.get('blind')!r}. "
                f"FR-REVIEW-29: a blind label carries the routing its cell had at draw time "
                f"({at_draw}), not the routing at Finish")
            operational = [label for label in labels if label["label_type"] != "blind"]
            assert [label["routing"] for label in operational] == ["reviewed"], (
                f"the accept's label on {score_id} records "
                f"{[label['routing'] for label in operational]}; an operational label carries "
                "`reviewed`, the routing its action creates")

        snapshot = {label["label_id"]: label["routing"] for label in served.labels()}
        other = served.cells("C2")[0]
        _review(served, other, "edit", _other_band(served, other, 1))
        with pytest.raises(Exception):
            served.finish_through_the_consoles_service()
        served.get("/api/v1/blind-seats", run_id=served.run_id)
        after = {label["label_id"]: label["routing"] for label in served.labels()}
        assert {k: after[k] for k in snapshot} == snapshot, (
            "a later review action rewrote a stored label's routing (FR-REVIEW-29)")


# --- TC-REVIEW-106 ---------------------------------------------------------------------------

#: The exact seat keys FR-REVIEW-27 fixes, spelled from the plan, not imported from the code.
_SEAT_KEYS = frozenset({"seat_id", "student_name", "question", "criterion_id",
                        "answer_text", "page_refs", "bands", "draft_band"})

#: What the draw and the seat reads may touch: the submission and its roster name, the
#: criterion and its band set, the canonical artifact (document and its regions), the run and
#: its package's grade policy (the review window), and the draw's own tables.
_SEAT_READABLE = frozenset({"submission", "roster", "criterion", "band", "document",
                            "document_region", "run", "grade_policy", "blind_draw",
                            "blind_draw_seat", "blind_draft"})
_SEAT_FORBIDDEN = frozenset({"criterion_score", "verdict", "extraction"})

_TABLE = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([A-Za-z_][A-Za-z_0-9]*)", re.IGNORECASE)


def _tables(statements) -> set[str]:
    return {match.group(1).lower() for statement in statements
            for match in _TABLE.finditer(statement)}


def test_tc_review_106_the_seat_carries_the_answer_and_descriptors_and_nothing_graded(
        tmp_path, monkeypatch):
    """TC-REVIEW-106 (FR-REVIEW-27, CT-REVIEW-09 amended).
    - Every seat's key set equals the allowlist exactly.
    - `answer_text` equals the canonical document's text for the question's region. That is
      worked here from the stored region rows, independently of the seat code's reader.
      `page_refs` are those regions' pages.
    - `bands` are `[{name, descriptor}]` in the package's ordinal order, read from the package's
      band table, each with its descriptor.
    - A SQLite trace over the draw and the seat reads touches only the allowlisted tables,
      never `criterion_score`, `verdict` or `extraction`. Positive control: the same trace
      sees `criterion_score` while the review service is built.

    Mutation: add `system_band` (or `extracted_spans`) to the seat and the key-set equality
    goes red."""
    from aeh.console import build_console
    from tests.support import pipe_world

    statements: list[str] = []
    real_connect = sqlite3.connect

    def tracing_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracing_connect)  # before the store opens
    root = tmp_path / "w"
    world = pipe_world.replay_world(root, monkeypatch=monkeypatch)
    try:
        world.build_run()
        world.start_run()
        assert pipe_world.drive_composed(world).status == "complete"
        statements.clear()
        service = build_console(store=world.store)._review_service(world.run_id)
        assert "criterion_score" in _tables(statements), (
            "positive control: the trace saw no criterion_score read while the review service "
            "was built, so an empty trace below would prove nothing")
        statements.clear()
        session = service.blind_sample(world.run_id)
        seats = service.blind_seats(world.run_id)
        traced = _tables(statements)
    finally:
        world.store.close()
    monkeypatch.setattr(sqlite3, "connect", real_connect)

    assert session.items and len(seats) == len(session.items), (session.items, seats)
    assert traced, "the draw and the seat reads ran no statement the trace could see"
    assert not traced & _SEAT_FORBIDDEN, (
        f"the blind draw or seat reads touched {sorted(traced & _SEAT_FORBIDDEN)}: CT-REVIEW-09 "
        "says the session cannot join to criterion_score, verdict or extraction")
    assert traced <= _SEAT_READABLE, (
        f"the blind draw or seat reads touched {sorted(traced - _SEAT_READABLE)}, outside "
        "FR-REVIEW-27's readable set")

    cohort = root / "cohorts" / f"{world.cohort_id}.sqlite"
    with real_connect(cohort) as connection:
        connection.row_factory = sqlite3.Row
        package_version = connection.execute(
            "SELECT package_version_id FROM run WHERE run_id = ?", (world.run_id,)
        ).fetchone()[0]
        refs = dict(connection.execute("SELECT submission_id, student_ref FROM submission"))
        documents: dict[str, str] = {}
        for ref in session.items:
            document = connection.execute(
                "SELECT document_id FROM document WHERE submission_id = ? AND kind = "
                "'submission' ORDER BY document_id LIMIT 1", (ref.submission_id,)).fetchone()
            documents[ref.submission_id] = document[0]
    package_file = root / "packages" / f"{world.package_id}.pkg.sqlite"
    assert package_file.is_file(), f"fixture: no package file at {package_file}"
    with real_connect(package_file) as connection:
        bands_of = {
            criterion: [{"name": band, "descriptor": descriptor} for band, descriptor in
                        connection.execute(
                            "SELECT band, descriptor FROM band WHERE package_version_id = ? "
                            "AND criterion_id = ? ORDER BY ordinal",
                            (package_version, criterion))]
            for criterion in {ref.criterion_id for ref in session.items}
        }
        question_of = dict(connection.execute(
            "SELECT criterion_id, question_id FROM criterion WHERE package_version_id = ?",
            (package_version,)))

    for number, (ref, seat) in enumerate(zip(session.items, seats), start=1):
        assert set(seat) == _SEAT_KEYS, (
            f"seat {number} carries keys {sorted(set(seat) ^ _SEAT_KEYS)} beyond or short of "
            "FR-REVIEW-27's allowlist. Anything extra is a route for system output into the "
            "blind")
        assert seat["seat_id"] == f"seat-{number}" and seat["criterion_id"] == ref.criterion_id
        question = question_of[ref.criterion_id]
        assert seat["question"] == question
        assert seat["student_name"] in (refs[ref.submission_id],), seat["student_name"]
        with real_connect(cohort) as connection:
            rows = connection.execute(
                "SELECT page_no, content FROM document_region WHERE document_id = ? AND "
                "question_id = ? ORDER BY position, region_id",
                (documents[ref.submission_id], question)).fetchall()
        expected_text = "\n".join(str(content).strip() for _page, content in rows if content)
        assert expected_text, f"fixture: seat {number}'s question has no region text"
        assert seat["answer_text"] == expected_text, (
            f"seat {number}'s answer is not the canonical region's text:\n"
            f"{seat['answer_text']!r}\n!=\n{expected_text!r}")
        assert seat["page_refs"] == sorted({page for page, _content in rows if page})
        assert seat["bands"] == bands_of[ref.criterion_id], (
            f"seat {number}'s bands are not the package's, in ordinal order, with descriptors")
        assert all(band["descriptor"] for band in seat["bands"]), seat["bands"]
        assert seat["draft_band"] is None


# --- TC-REVIEW-107 ---------------------------------------------------------------------------


def test_tc_review_107_b_every_label_the_console_writes_is_the_teachers(
        tmp_path, monkeypatch, network_guard):
    """TC-REVIEW-107 (FR-REVIEW-28), the console half that has landed. Every label the
    console writes has actor `teacher`: the blind labels its service closes, and the accept,
    edit and override labels its review action writes. Before #867 the console's blind labels
    carried `operator`. The operator arm (a CLI or live-check label) has no path in `src/`;
    see the module docstring, departure 4."""
    with served_run(tmp_path / "w", monkeypatch, network_guard) as served:
        _label_and_review_the_world(served)
        actors = sorted({(label["label_type"], label["actor"]) for label in served.labels()})
    assert {actor for _type, actor in actors} == {"teacher"}, (
        f"labels the console wrote carry actors {actors}; FR-REVIEW-28 makes every one the "
        "teacher's")
    assert {label_type for label_type, _actor in actors} >= {"blind"}, actors
