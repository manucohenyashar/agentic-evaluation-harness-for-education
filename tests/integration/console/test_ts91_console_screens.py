"""TS-91 (#385) / TS-96 (#390): the console's service-backed screens on a real store.

| Case | Oracle |
|---|---|
| TC-CONSOLE-45 | 20 flagged items, a 10-minute budget: S9's header figures equal `ReviewService.build_queue(R, 10)`'s exactly; S3 renders editable rows; `console.py` carries none of the removed queries |
| TC-CONSOLE-47 (a) / TC-CONSOLE-C28 | For S2, S3, S9 and S12, the table the screen's reader needs is dropped: the page names what it could not read (`read_error`) and its unreadable section carries no numeric count |
| TC-CONSOLE-47 (b) | A non-schema fault (`ValueError`) in one per-ledger read: the page renders and its trace counts one skipped ledger |

TC-CONSOLE-C25 and TC-CONSOLE-C27 are carried where the plan puts them: C25 is TC-CONSOLE-43's three
GETs over the real socket (`test_tc_console_43_http_surface.py`), C27 is TC-CONSOLE-46 rows 2, 3 and 7
(`test_tc_console_46_environment_matrix.py`) plus SEC-16 (`test_sec_16_refusal_opens_no_socket.py`).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.orch  # noqa: F401,E401
import aeh.pkg, aeh.review, aeh.synth  # noqa: F401,E401
import aeh.console as console
from aeh import review
from aeh.console import SCREENS, build_console
from aeh.store import open_store
from tests.support.grade_vocabulary import write_criterion_scores
from tests.support.orch_run import ORCH_COHORT_ID, seed_run

pytestmark = pytest.mark.integration


def _flagged_store(data_dir: Path, n: int = 20) -> str:
    store = open_store(data_dir)
    try:
        subs = tuple(f"S{i:02d}" for i in range(n))
        _o, run_id, _v = seed_run(store, submissions=subs, criteria=(
            {"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},))
        write_criterion_scores(store.cohort(ORCH_COHORT_ID),
                               [(s, "C1", "B2", 1.0, "provisional") for s in subs])
    finally:
        store.close()
    with sqlite3.connect(data_dir / "cohorts" / f"{ORCH_COHORT_ID}.sqlite") as c:
        c.execute("UPDATE criterion_score SET spans_verified = 0")
    return run_id


def _items(queue) -> int:
    """Shown ITEMS: a signature-identical group is one entry of several members (FR-REVIEW-05),
    and S9's "Shown: N items" counts the members."""
    return sum(len(getattr(e, "members", None) or (e,)) for e in queue.shown)


def _build(data_dir, run_id, budget):
    service = review.open_review(data_dir, run_id=run_id)
    try:
        return service.build_queue(run_id=run_id, budget_minutes=budget)
    finally:
        service.close()


def test_tc_console_45_s9_header_is_build_queue_at_the_budget(tmp_data_dir):
    run_id = _flagged_store(tmp_data_dir)
    ten = _build(tmp_data_dir, run_id, 10)
    store = open_store(tmp_data_dir)
    try:
        app = build_console(store=store)
        view = app.review_queue(run_id, budget_minutes=10).queue  # the console's read at 10 minutes
        text = re.sub(r"<[^>]+>", " ", app.render(SCREENS["S9"], id=run_id).html)
    finally:
        store.close()
    assert ten.flagged_total == 20, f"fixture: {ten.flagged_total} flagged"
    assert (view.flagged_total, len(view.shown), view.residual_provisional, view.reserved_for_blind_minutes) == (
        ten.flagged_total, _items(ten), ten.residual_provisional, ten.reserved_for_blind_minutes), (
        "the console's 10-minute queue figures are not build_queue(R, 10)'s")
    # The rendered page, at the budget it states, equals build_queue at that budget.
    figures = re.search(r"Flagged for review: (\d+)\. Shown: (\d+) items?\. Left provisional: (\d+)", text)
    budget = re.search(r"Review budget: (\d+) minutes", text)
    assert figures and budget, text[:500]
    stated = _build(tmp_data_dir, run_id, int(budget.group(1)))
    assert tuple(map(int, figures.groups())) == (stated.flagged_total, _items(stated), stated.residual_provisional)
    import ast

    # The SQL the module can execute: its string literals, never the comments explaining the
    # removals (FR-CONSOLE-35).
    literals = [n.value for n in ast.walk(ast.parse(Path(console.__file__).read_text(encoding="utf-8")))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for removed in (r"\brank_position\b", r"\bFROM\s+review_budget\b", r"\bFROM\s+package_file\b",
                    r"\bFROM\s+setup_skip\b", r"\bFROM\s+sample_selection\b"):
        hits = [lit[:80] for lit in literals if re.search(r"\b(SELECT|UPDATE|INSERT)\b", lit, re.I)
                and re.search(removed, lit, re.I)]
        assert not hits, f"console.py still executes a removed query ({removed}): {hits}"


@pytest.mark.writtenahead
def test_tc_console_45_the_blind_flow_plan_names_no_removed_table():
    """Written ahead, owned by no issue yet: `_BLIND_FLOW_QUERIES`, the declared blind-flow plan
    (CT-CONSOLE-14's assertion surface), still reads `blind_sample`, a table FR-CONSOLE-35
    removed and no tier declares; M-REVIEW's `BlindSession` reads `submission` and `criterion`."""
    import ast

    literals = [n.value for n in ast.walk(ast.parse(Path(console.__file__).read_text(encoding="utf-8")))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    hits = [lit for lit in literals if re.search(r"\bFROM\s+blind_sample\b", lit, re.I)]
    assert not hits, hits


@pytest.mark.writtenahead
def test_tc_console_45_s3_renders_the_proposed_inventory_as_editable_rows(tmp_data_dir):
    """Written ahead, owned by no issue yet: with six questions proposed, S3 says "Questions read
    back from the package: 0" and renders no editable field — it reads only confirmed questions,
    so the teacher cannot see or correct the proposal the screen exists to confirm (HLD §11.5)."""
    from tests.contract.setup._doubles import ingest_document, stage_chain

    chain = stage_chain(tmp_data_dir / "live")
    try:
        chain.doc = ingest_document(chain.store, kind="assessment")
        chain.service.propose_inventory(chain.doc)
        s3 = build_console(store=chain.store).render(SCREENS["S3"]).html
    finally:
        chain.store.close()
    fields = re.findall(r"<(?:input|textarea|select)", s3)
    assert fields, "S3 renders the proposed inventory with no editable field (HLD §11.5)"
    assert "Q1" in s3 and "Q4" in s3, "S3 does not list the proposed questions"


@pytest.mark.writtenahead
def test_tc_console_45_s9_honours_the_configured_review_budget(tmp_data_dir, monkeypatch):
    """Written ahead, owned by no issue yet: S9 renders at `REVIEW_DEFAULT_BUDGET_MINUTES` (30)
    and ignores `HARNESS_REVIEW_DEFAULT_BUDGET_MINUTES`, the env knob M-REVIEW declares for it
    (seam 3): a teacher's configured 10-minute sitting is shown as 30."""
    monkeypatch.setenv("HARNESS_REVIEW_DEFAULT_BUDGET_MINUTES", "10")
    run_id = _flagged_store(tmp_data_dir)
    store = open_store(tmp_data_dir)
    try:
        text = re.sub(r"<[^>]+>", " ", build_console(store=store).render(SCREENS["S9"], id=run_id).html)
    finally:
        store.close()
    assert "Review budget: 10 minutes" in text, re.search(r"Review budget: \d+ minutes", text)


#: The table each service-backed screen's reader needs, by tier.
DROPS = {
    "S2": ("cohort", "upload_part"),
    "S9": ("cohort", "criterion_score"),
    "S12": ("cohort", "submission_grade"),
    "S3": ("package", "question"),
}


_UNOWNED = pytest.mark.writtenahead  # the screen renders an absence over an unreadable table


@pytest.mark.parametrize("screen", [
    pytest.param("S2", marks=_UNOWNED),   # "No parts have been uploaded" over a dropped upload_part
    pytest.param("S3", marks=_UNOWNED),   # "Questions read back from the package: 0" over a dropped question
    "S9", "S12"])
def test_tc_console_47_a_c28_an_unreadable_view_never_renders_a_zero(tmp_data_dir, screen):
    run_id = _flagged_store(tmp_data_dir, n=3)
    tier, table = DROPS[screen]
    if tier == "cohort":
        path = tmp_data_dir / "cohorts" / f"{ORCH_COHORT_ID}.sqlite"
    else:
        (path,) = sorted((tmp_data_dir / "packages").glob("*.pkg.sqlite"))
    with sqlite3.connect(path) as c:
        c.execute("PRAGMA foreign_keys = OFF")
        c.execute(f"DROP TABLE {table}")
    store = open_store(tmp_data_dir)
    try:
        page = build_console(store=store).render(SCREENS[screen], id=run_id, cohort_id=ORCH_COHORT_ID)
    finally:
        store.close()
    assert page.read_error, f"{screen} rendered over a dropped {table} without saying it could not read it"
    section = re.search(r'<section data-role="unreadable-view">(.*?)</section>', page.html, re.S)
    assert section and not re.search(r"\b0\b", re.sub(re.escape(page.read_error), "", section.group(1))), (
        f"{screen}'s unreadable section carries a number")


def test_tc_console_47_b_a_non_schema_fault_skips_one_ledger(tmp_data_dir, monkeypatch):
    import aeh.store as store_mod

    run_id = _flagged_store(tmp_data_dir, n=3)
    real = store_mod.SqliteTierHandle.query
    fired: list[bool] = []

    def query(self, statement, **params):
        import sys

        caller = sys._getframe(1).f_code.co_name
        if caller == "_read_cohort_files" and not fired:
            fired.append(True)
            raise ValueError("a transient non-schema fault")
        return real(self, statement, **params)

    monkeypatch.setattr(store_mod.SqliteTierHandle, "query", query)
    store = open_store(tmp_data_dir)
    try:
        page = build_console(store=store).render(SCREENS["S12"], id=run_id)
    finally:
        store.close()
    assert fired, "fixture: S12 made no per-ledger read"
    assert page.skipped_ledgers == 1 and not page.read_error, (page.skipped_ledgers, page.read_error)
    assert "<html" in page.html
