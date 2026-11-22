"""Validity T9 (issue #902): `TC-SETUP-26` — accepting marked examples (FR-SETUP-20, amends
FR-SETUP-15; FR-SETUP-14).

Test plan (statistical-validity r2, §3.12):

- 1 PDF and 25 PDFs are accepted; 26 are refused, naming the limit.
- A band is required for every **judged** criterion; deterministic ones are not asked.
- Stored in `calibration_example_mark` with the version and time.
- Skipping records the default taken and never blocks approval.

**The world (rung 3 over real tiers).** `setup_harness.stage_chain`: a real store, a real
`Ingestor`, a real `PackageCatalog` and `SetupService`; only the model boundary is scripted. The
draft is read back with two judged criteria (`CRIT-MET`, `CRIT-TYPED`) and the inventory's
three deterministic ones (`CRIT-Q4`…`Q6`, keyed so publication's gates are met). Each example is
a really ingested document with its own bytes (the step reads each transcript for the
clean-copy check, so 25 accepted means 25 real documents read). The stored rows are read from
the version's `.pkg.sqlite` file directly, not through the catalog under test.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401

pytestmark = pytest.mark.integration

JUDGED = ("CRIT-MET", "CRIT-TYPED")
DETERMINISTIC = ("CRIT-Q4", "CRIT-Q5", "CRIT-Q6")


def _draft(tmp_data_dir: Path, package_id: str):
    """The chain through the read back and the keys: a draft ready to publish."""
    from tests.support.setup_harness import ingest_document, stage_chain

    chain = stage_chain(tmp_data_dir, package_id=package_id)
    assessment = ingest_document(chain.store)
    rubric = ingest_document(chain.store, kind="rubric", name="rubric.pdf")
    proposal = chain.service.propose_inventory(assessment)
    chain.service.confirm_inventory(proposal.proposal_id)
    chain.provider.replies = [json.dumps({"criteria": [
        {"criterion_id": "CRIT-MET", "question_id": "Q1", "kind": "open",
         "scoring_model": "holistic", "max_points": 4.0,
         "construct": "the response defines impulse as force acting over contact time"},
        {"criterion_id": "CRIT-TYPED", "question_id": "Q2", "kind": "open",
         "scoring_model": "holistic", "max_points": 5.0,
         "construct": "the response derives the range equation"},
    ]})]
    chain.service.read_back_rubric(rubric, assessment)
    chain.service.set_answer_keys({"CRIT-Q4": ["A"], "CRIT-Q5": ["A"], "CRIT-Q6": ["A"]})
    chain.version = chain.catalog.draft_version()
    return chain


def _examples(chain, count: int, start: int = 0) -> dict[str, str]:
    """`count` really ingested answer sheets, each its own bytes: document id -> file name."""
    from tests.support.setup_harness import build_ingestor, SUBMISSION_MD

    ingestor = build_ingestor(chain.store, SUBMISSION_MD)
    out: dict[str, str] = {}
    for number in range(start, start + count):
        name = f"example-{number:02d}.pdf"
        source = chain.store.blobs().put(f"marked example {number}".encode())
        document_id = ingestor.ingest_document([source], kind="submission",
                                               filenames={source: name})
        out[str(document_id)] = name
    return out


def _pkg_rows(tmp_data_dir: Path, package_id: str, sql: str, *params) -> list[dict]:
    path = next(Path(tmp_data_dir).rglob(f"{package_id}*.sqlite"))
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(sql, params).fetchall()]


def _bands(chain) -> dict[str, str]:
    """A band each judged criterion declares (its first), read from the catalog's rows."""
    return {criterion: str(chain.catalog.bands(criterion)[0]["band"]) for criterion in JUDGED}


# --- the limit ---------------------------------------------------------------------------------


def test_tc_setup_26_one_and_twenty_five_examples_are_accepted(tmp_data_dir):
    """1 is accepted; topping up to 25 is accepted; the step holds exactly what was uploaded."""
    from aeh.setup import MARKED_EXAMPLES_MAX

    chain = _draft(tmp_data_dir, "pkg-t26-ok")
    try:
        one = _examples(chain, 1)
        step = chain.service.add_marked_examples(one)
        assert step.total == 1 and dict(step.examples) == one, step
        more = _examples(chain, 24, start=1)
        step = chain.service.add_marked_examples(more)
    finally:
        chain.store.close()
    assert MARKED_EXAMPLES_MAX == 25
    assert step.total == 25, f"25 examples were uploaded and the step holds {step.total}"
    assert dict(step.examples) == {**one, **more}
    assert step.status == "uploaded", step.status


@pytest.mark.parametrize("split", [(26,), (24, 2)], ids=["one-upload", "cumulative"])
def test_tc_setup_26_a_twenty_sixth_example_is_refused_naming_the_limit(tmp_data_dir, split):
    """26 in one upload, or 24 then 2: refused with the limit named, and the refused upload
    stores nothing (the step is as it was)."""
    from aeh.setup import MarkedExampleRefused

    chain = _draft(tmp_data_dir, f"pkg-t26-{len(split)}")
    try:
        held = None
        if len(split) == 2:
            held = chain.service.add_marked_examples(_examples(chain, split[0]))
        extra = _examples(chain, split[-1], start=100)
        with pytest.raises(MarkedExampleRefused) as refused:
            chain.service.add_marked_examples(extra)
        after = chain.service.marked_examples()
    finally:
        chain.store.close()
    message = str(refused.value)
    assert "at most 25" in message and "26" in message, (
        f"the refusal does not name the limit and the count: {message!r}")
    expected = held.examples if held is not None else ()
    assert after.examples == expected, (
        "the refused upload changed the step: everything is checked before anything is "
        f"stored — held {len(after.examples)}, expected {len(expected)}")


# --- the form ----------------------------------------------------------------------------------


def test_tc_setup_26_the_form_needs_every_judged_criterion_and_never_a_deterministic_one(
        tmp_data_dir):
    """A form missing a judged criterion is refused; one naming a deterministic criterion is
    refused; neither stores a row. The complete judged form is stored in
    `calibration_example_mark`, one row per judged criterion, with the version and the time."""
    from aeh.setup import MarkedExampleRefused

    chain = _draft(tmp_data_dir, "pkg-t26-form")
    try:
        (document_id,) = _examples(chain, 1)
        chain.service.add_marked_examples({document_id: "example-00.pdf"})
        bands = _bands(chain)
        modes = {row["criterion_id"]: row["evaluation_mode"]
                 for row in chain.catalog.criteria(chain.version)}

        with pytest.raises(MarkedExampleRefused, match="1 of 2 still need"):
            chain.service.mark_example(document_id, {JUDGED[0]: bands[JUDGED[0]]})
        with pytest.raises(MarkedExampleRefused, match="marked automatically"):
            chain.service.mark_example(document_id, {**bands, DETERMINISTIC[0]: "A"})
        refused_rows = _pkg_rows(tmp_data_dir, "pkg-t26-form",
                                 "SELECT * FROM calibration_example_mark")

        step = chain.service.mark_example(document_id, bands)
    finally:
        chain.store.close()

    assert {c: modes[c] for c in JUDGED} == {c: "judged" for c in JUDGED}
    assert {c: modes[c] for c in DETERMINISTIC} == {c: "deterministic" for c in DETERMINISTIC}
    assert refused_rows == [], f"a refused form stored rows: {refused_rows}"
    rows = _pkg_rows(tmp_data_dir, "pkg-t26-form",
                     "SELECT package_version_id, document_id, criterion_id, band, marked_at "
                     "FROM calibration_example_mark ORDER BY criterion_id")
    assert [(r["criterion_id"], r["band"]) for r in rows] == sorted(bands.items()), (
        f"stored {rows}: one row per JUDGED criterion with the form's band, and no "
        "deterministic criterion")
    assert {r["package_version_id"] for r in rows} == {chain.version}
    assert {r["document_id"] for r in rows} == {document_id}
    assert all(str(r["marked_at"]).strip() for r in rows), "a mark stored with no time"
    assert step.status == "marked" and step.marked == (document_id,)


# --- the skip ----------------------------------------------------------------------------------


@pytest.mark.parametrize("skip", [True, False], ids=["explicit-skip", "untouched"])
def test_tc_setup_26_skipping_records_the_default_and_never_blocks_publication(
        tmp_data_dir, skip):
    """An explicit skip, or a step never touched: publication proceeds, and the step's row
    reads `default_taken` — provenance, not silence (FR-SETUP-14)."""
    from aeh.setup.marked_examples import MARKED_EXAMPLES_STEP

    package_id = f"pkg-t26-skip-{int(skip)}"
    chain = _draft(tmp_data_dir, package_id)
    try:
        if skip:
            assert chain.service.skip_marked_examples().status == "default_taken"
        version = chain.service.publish("teacher-1")
        locked = chain.catalog.is_locked(version)
    finally:
        chain.store.close()
    assert locked, "the version did not publish with the examples step skipped"
    rows = _pkg_rows(tmp_data_dir, package_id,
                     "SELECT status, payload FROM setup_step_record WHERE step_id = ?",
                     MARKED_EXAMPLES_STEP)
    assert [r["status"] for r in rows] == ["default_taken"], rows
    assert json.loads(rows[0]["payload"])["examples"] == []
