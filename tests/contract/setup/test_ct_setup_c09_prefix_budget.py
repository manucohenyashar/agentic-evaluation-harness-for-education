"""`CT-SETUP-09` — the prefix-budget check runs before publication; the drop
policy spares the reference solution and criterion text (`TC-SETUP-C09`).

Case of test plan §6.11.6; issue #56 (TS-63). **Landed with #53** — the
budget check (`check_prefix_budget`, §3.6's signature) exists, and the
`writtenahead` marker and its `WRITTEN_AHEAD_BLOCKERS` entry ("#56 C09 prefix
budget") are gone. The fixture was aligned once at the landing: the two bands'
POINTS were re-ordered to be non-decreasing in ordinal (FR-PKG-06 — the
zero-point band at ordinal 0), which moved the band names with them; the
value semantics the stated bet describes (the zero-point band's exemplars are
the lowest-value things in the prefix) and every assertion are unchanged.

The clause (FR-SETUP-11), asserted in its four parts:

1. **Event order.** The check runs BEFORE publication and reports the overage
   while it is still fixable — a check that runs after publication is advice
   nobody can act on. Asserted by driving an over-budget draft, taking the
   report, and asserting the version is still UNLOCKED with the overage
   visible; the package then publishes after remediation.
2. **The drop policy.** Where the ceiling is still exceeded, the LOWEST-VALUE
   exemplars are dropped — never the reference solution, never the criterion
   text. The exemplars here are constructed so value ordering is the points
   ordering of their band (the zero-point band's exemplar is the lowest-value
   thing in the prefix); **stated bet**: if #53 defines exemplar value
   differently, this fixture re-orders — the assertions below do not change.
3. **The record.** WHICH exemplars were dropped is recorded on the report —
   a silent drop would leave the teacher unable to audit what left the prefix.
4. **The second check** (found by the #53 reviewer, pinned at the landing): the
   ceiling is the run config's per-profile value, and a resumed service's
   re-check does not erase the record of what an earlier check removed.

**Payload-shape bets** (§3.6 pins the signature, not `PrefixBudgetReport`'s
fields — the TC-INGEST-38 rule: no assertion invents storage): the report
carries `over_budget` and `dropped_exemplars` (sequence of exemplar ids);
align the names when #53 lands — the three assertions above do not change.
Exemplar survival is read from the stored `exemplar` table raw (no read
accessor exists on the catalog to assert through — the table itself is the
package's record).
"""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from aeh.prov import ModelRef
from aeh.setup import SetupService
from tests.contract.setup._doubles import db_file_for, ingest_document, stage_chain
from tests.support.impl import require_attr
from tests.support.setup_harness import SETUP_BUILD

pytestmark = pytest.mark.contract

ISSUE = "#53"


def _stored_exemplar_ids(data_dir, package_id: str, version: str) -> set[str]:
    """The version's surviving exemplar ids, from the package tier file raw."""
    conn = sqlite3.connect(f"file:{db_file_for(data_dir, package_id)}?mode=ro",
                           uri=True)
    try:
        rows = conn.execute(
            "SELECT exemplar_id FROM exemplar WHERE package_version_id = ?",
            (version,)).fetchall()
    finally:
        conn.close()
    return {row[0] for row in rows}


def _stored_budget_record(data_dir, package_id: str, version: str) -> dict:
    """The version's `prefix_budget` step record, raw from the package tier file
    (asserted through the table, not through the accessor the code itself uses)."""
    conn = sqlite3.connect(f"file:{db_file_for(data_dir, package_id)}?mode=ro",
                           uri=True)
    try:
        row = conn.execute(
            "SELECT payload FROM setup_step_record "
            "WHERE package_version_id = ? AND step_id = 'prefix_budget'",
            (version,)).fetchone()
    finally:
        conn.close()
    assert row is not None, (
        "the prefix-budget check wrote no step record — the check's own "
        "provenance is missing (CT-SETUP-C09, the record clause)"
    )
    return json.loads(row[0])


def test_tc_setup_c09_overage_reported_while_fixable_and_drops_spare_the_text(
        tmp_data_dir):
    """An over-budget draft: the report names the overage pre-lock; the drop
    takes the lowest-value exemplars, never the reference solution or criterion
    text; and the dropped ids are recorded."""
    require_attr(SetupService, "check_prefix_budget", issue=ISSUE)

    chain = stage_chain(tmp_data_dir, package_id="pkg-c09")
    chain.doc = ingest_document(chain.store, kind="assessment")
    proposal = chain.service.propose_inventory(chain.doc)
    chain.service.confirm_inventory(proposal.proposal_id)
    version = chain.service.ensure_version()

    # The text the drop policy must SPARE: the question's reference solution
    # and the criterion's band descriptors (the criterion's stored text).
    reference = "the impulse-momentum theorem, stated and applied to the collision"
    chain.catalog.update_question_field(version, "Q1", "reference_solution",
                                        reference)
    chain.catalog.add_criterion(version, "CRIT-B", question_id="Q1",
                                kind="open", max_points=4.0, band_count=2)
    # The points are non-decreasing in ordinal (FR-PKG-06 — the shape the same
    # schema enforces everywhere), so the ZERO-point band sits at ordinal 0:
    # its exemplars are the lowest-value things in the prefix, as the stated
    # bet describes.
    bands_spec = (("b0", 0.0, "no method appears"),
                  ("b1", 1.0, "the derivation is complete and stated"))
    descriptors = tuple(spec[2] for spec in bands_spec)
    for ordinal, (band, points, descriptor) in enumerate(bands_spec):
        chain.catalog.add_band(version, "CRIT-B", ordinal, band, points,
                               descriptor=descriptor)
    chain.service.set_answer_keys({"CRIT-B": ["b1"]}
                                  | {"CRIT-Q4": ["A"], "CRIT-Q5": ["A"],
                                     "CRIT-Q6": ["A"]})

    # Exemplars across the value range, each carrying a large blob so the
    # assembled prefix is over ANY configured ceiling.
    for exemplar_id, band in (("EX-LOW", "b0"), ("EX-MID", "b0"),
                              ("EX-HIGH", "b1")):
        blob = chain.store.blobs().put(b"x" * 400_000)
        chain.catalog.add_exemplar(version, exemplar_id, "CRIT-B", band,
                                   provenance="synthetic", blob_hash=blob)

    # 1. Event order: the report is available BEFORE publication, and the
    # version it describes is still fixable.
    report = chain.service.check_prefix_budget()
    assert report.over_budget, (
        "the constructed over-budget draft reported no overage — the check "
        "did not compare against the ceiling (CT-SETUP-C09)"
    )
    assert not chain.catalog.is_locked(version), (
        "the budget check locked or published the version — the overage was "
        "reported after the teacher could no longer act on it (CT-SETUP-C09, "
        "event order)"
    )

    # 2. The drop policy: the LOWEST-VALUE exemplars went first (the zero-band
    # ones), and the highest-value exemplar survived.
    survivors = _stored_exemplar_ids(tmp_data_dir, "pkg-c09", version)
    assert "EX-LOW" not in survivors, (
        "the lowest-value exemplar survived the drop — the policy dropped the "
        "wrong end (CT-SETUP-C09)"
    )
    assert "EX-HIGH" in survivors, (
        "the highest-value exemplar was dropped before the lowest-value ones "
        "(CT-SETUP-C09)"
    )

    # ... and the spared text is intact, verbatim.
    questions = {q["question_id"]: q for q in
                 chain.catalog.questions(version)}
    assert questions["Q1"]["reference_solution"] == reference, (
        "the reference solution was altered by the budget remediation — the "
        "drop policy touched what it must never touch (CT-SETUP-C09)"
    )
    bands = chain.catalog.bands("CRIT-B")
    assert tuple(band["descriptor"] for band in bands) == descriptors, (
        "the criterion's band descriptors were altered by the budget "
        "remediation (CT-SETUP-C09)"
    )

    # 3. The record: the dropped ids are ON the report.
    assert "EX-LOW" in set(report.dropped_exemplars), (
        f"the report recorded dropped={report.dropped_exemplars!r} — the drop "
        "was silent about what it removed (CT-SETUP-C09)"
    )

    # 4. A SECOND check, in the resume shape — a fresh service re-running the
    # step — with a CONFIG-carried ceiling: the check compares against the run
    # config's per-profile `prefix_token_ceiling` (FR-SETUP-11 -> FR-CONF-10),
    # not this module's constant (found by the #53 reviewer: the ceiling never
    # reached RunConfig, so every package was checked against the fallback).
    resumed = SetupService(
        chain.catalog, chain.ingestor, chain.provider,
        ModelRef(role="extractor", provider="local", build_id=SETUP_BUILD,
                 quantization="q4"),
        run_config=SimpleNamespace(prefix_token_ceiling=999))
    second = resumed.check_prefix_budget()
    assert second.ceiling_tokens == 999, (
        f"the second check compared against {second.ceiling_tokens} — the "
        "ceiling must be the run config's value (FR-SETUP-11), not the module "
        "fallback"
    )
    # This check drops NOTHING — both remaining exemplars are the last of
    # their band (the calibration floor) — yet the durable record must still
    # name what the FIRST check removed: the `prefix_budget` row is UPSERTED,
    # so a second check that overwrote it with its own empty drop list would
    # erase the only record of EX-LOW (the exemplar rows are gone from
    # `exemplar`; nothing else in the database names what left the prefix).
    # Found by the #53 reviewer; the record carries the UNION of every
    # check's drops on this version.
    assert second.dropped_exemplars == (), (
        f"the second check dropped {second.dropped_exemplars!r} — the fixture "
        "promises both remaining exemplars are their bands' last, so the "
        "calibration floor leaves nothing to drop"
    )
    record = _stored_budget_record(tmp_data_dir, "pkg-c09", version)
    assert record["dropped_exemplars"] == ["EX-LOW"], (
        f"the second check's record names {record['dropped_exemplars']!r} — the "
        "record must carry the UNION of what every check on this version "
        "removed (FR-SETUP-11: WHICH exemplars were dropped is recorded, "
        "durably, not only on the report of the call that did it)"
    )

    # Remediated, the same package publishes — the check was advice the
    # teacher could act on.
    published = chain.service.publish("teacher-1")
    assert chain.catalog.is_locked(published)
