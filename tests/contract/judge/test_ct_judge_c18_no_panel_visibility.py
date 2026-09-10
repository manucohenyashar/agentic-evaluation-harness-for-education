"""`TC-JUDGE-C18` — a judge has no visibility of any other judge's verdict, and no
operation will ever expose panel state to a member (§6.11.10).

`CT-JUDGE-18` (behaviour, non-promise): *"**Not promised:** a judge has no visibility
of any other judge's verdict, at any point, including its own on another criterion.
There is no operation exposing panel state to a member, and none will be added."*
(detailed design, verbatim). The plan row states the two forms: *"Assert there is
**no operation exposing panel state to a member**, by reflecting over the surface
rather than by sampling requests, since the clause says 'and none will be added'.
Then assert it dynamically: run a full panel at rung 3 with sentinel verdicts and
assert no sentinel appears in any other member's assembled request, including
across criteria for the same submission."*

Two cases carry it:

1. **the surface reflection (rung 0, artifact assertion)** — the prohibition has no
   sunset ("and none will be added"), so the static limb reflects over the module's
   surface in three arms, each a different landing spot for a future exposure:

   - the statement registry (`JUDGE_STATEMENTS`): no statement READS the verdict
     table. Writing the verdict row is the module's own job (`CT-JUDGE-12`'s
     sanctioned INSERT); reading verdicts back is the exposure — an operation that
     hands a member panel state must, at bottom, read the table, and a declared
     statement is where that read would live;
   - the module text (the completeness arm): the whitespace-normalized text of
     `src/aeh/judge.py` carries no `FROM verdict` / `JOIN verdict` — a read
     assembled outside the registry (an inline query, a string built at runtime,
     the shape the write-side scan in `TC-JUDGE-C12` names as its boundary) still
     trips. A `DELETE FROM verdict` trips too: the module's sanctioned verdict
     statement is the INSERT, and no clause sanctions destroying panel rows;
   - the declared surface (`__all__` unioned with every public attribute): no
     public name carries a panel-visibility stem (`panel`, `verdict`, `peer`) —
     the clause's "none will be added" is a name-level prohibition, because an
     operation a member can reach must be declared public. The stems are a
     vocabulary bet, the same bet `_PROHIBITED_STEMS` makes for field names; here
     for operation names.

   The scanners are validated against positive controls first: a synthetic verdict
   read must be flagged, a read of another table and the sanctioned INSERT must
   not be, and a synthetic public name carrying a stem must be flagged.

2. **the sentinel panel (rung 3, dynamic)** — the full panel (both criteria
   holistic: three judges each, six requests over one submission) driven with ONE
   verdict carrying a sentinel `self_confidence` — a value no default completion
   carries and whose digits appear in no transcript, rubric or render. Three
   assertions compose:

   - the sentinel is real panel state: exactly one verdict row in the run carries
     it, on the arm the program planted it on (the positive control — without
     this the scan below is vacuous);
   - the sentinel scan: the needle appears in NO member's assembled request — not
     in another judge's (requests assembled after the sentinel verdict persisted,
     so a leak had material to leak), not in the sentinel judge's OWN request on
     the OTHER criterion (the clause's "including its own on another criterion" —
     every judge judged both criteria, so that pair exists by construction);
   - the byte-identity differential: every request re-assembled AFTER the whole
     drive — when every verdict the panel landed exists in the ledger — is
     byte-identical to the request its dispatch actually sent. Assembly is a pure
     function of the unit and the rubric; if it consulted panel state AT ALL (any
     verdict, any judge, any criterion), the re-assembly drifts from the capture,
     whatever the sentinel scan missed. `drive_score_captured` exists for exactly
     this differential.

Cross-references, not duplicates: `TC-JUDGE-C02` (`test_closed_whitelist.py`) holds
the whitelist from the schema side — the request has no field capable of CARRYING
a verdict (`_PROHIBITED_STEMS` includes the verdict stem; `assert_isolated`
raises), which is the plan row's "the schema has no field for it"; this file holds
the operation side — no operation PRODUCES panel state for a member, "*and* no
operation produces it". `TC-JUDGE-C12` holds the WRITE side of the same table (one
verdict row per work unit, nothing else written); `TC-JUDGE-C10` holds the parent
verdict's absence for dependent criteria (`dependency_evidence` is typed to spans
only and cannot represent one); the shipped no-history file
(`test_no_numerals_no_history.py`, `FR-JUDGE-05`) holds the no-conversation/
no-accumulated-summary half of isolation. `TC-JUDGE-C08` runs the byte-identity
differential over a different property (prefix identity within a batch); this file
runs it over the panel's verdict-blindness.

Isolation: rung 0 (static reflection, no store) and rung 3 (real store, real
workers, the full panel through the recorded fixture provider, re-assembly
post-drive); the socket guard is autouse.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import aeh.judge
import pytest

from aeh.store import open_store
from tests.contract.judge._drive import (
    BANDS,
    drive_extract,
    drive_score_captured,
    seed_world,
    spans,
)
from tests.support.conf_builders import EDGE_JUDGE
from tests.support.extract_vocabulary import verdict_completion
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_vocabulary import fields_of, string_leaves
from tests.support.orch_run import ORCH_COHORT_ID

pytestmark = [pytest.mark.contract]

#: The story that owns the judge surface the clause prohibits (`M-JUDGE` is
#: complete — #78/#79/#80/#81); the clause's consumer is `M-AGG`.
ISSUE = "#78"

_JUDGE_BUILD = "build-judge-contract"

#: The sentinel: a `self_confidence` no default completion carries (the drive's
#: default is `0.9`), whose digits appear in no transcript, rubric or render. The
#: scan's needle is the digit run — any repr of the value contains it.
SENTINEL_CONFIDENCE = 0.91337
_NEEDLE = "91337"

#: Both criteria `holistic`: each enumerates one score unit per panel arm, so one
#: submission drives the full panel twice — every judge judged BOTH criteria,
#: which is what makes the clause's "including its own on another criterion" a
#: real pair in the fixture rather than a nominal one.
_BOTH_HOLISTIC = [
    {"criterion_id": "C1", "kind": "open", "scoring_model": "holistic",
     "band_count": len(BANDS)},
    {"criterion_id": "C2", "kind": "open", "scoring_model": "holistic",
     "band_count": len(BANDS)},
]

#: The verdict-table READ forms — the mechanism a panel-state exposure bottoms
#: out in. Word-bounded over whitespace-normalized text, so a statement wrapped
#: across lines cannot evade and `insert_verdict` cannot false-positive.
_VERDICT_READ_RE = re.compile(r"\b(?:FROM|JOIN)\s+verdict\b", re.IGNORECASE)

#: The panel-visibility stems for the declared-name scan — the clause's own
#: vocabulary ("panel state", "another judge's verdict") snake-cased. A name
#: carrying one of these stems is capable of naming the exposure, whatever the
#: rest of the name does; no exemption, like `_PROHIBITED_STEMS`.
_VISIBILITY_STEMS = ("panel", "verdict", "peer")


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _verdict_reads(sql_or_text: str) -> list[str]:
    """The verdict-table reads in one statement's or module's text, found over the
    whitespace-normalized text so a statement wrapped across lines cannot evade
    the scan. The sanctioned write (`INSERT ... INTO verdict`) is not a read and
    does not match; a read of any OTHER table does not either — the clause forbids
    visibility of panel state, and an over-broad scan would go red against a
    compliant module."""
    return [
        match.group(0).lower()
        for match in _VERDICT_READ_RE.finditer(_normalized(sql_or_text))
    ]


def _visibility_offenders(names: Iterable[str]) -> list[str]:
    """The names carrying a panel-visibility stem, sorted — the declared-surface
    scan's one implementation, shared by the positive control and the assertion."""
    return sorted({
        str(name) for name in names for stem in _VISIBILITY_STEMS
        if stem in str(name).lower()
    })


def test_tc_judge_c18_no_operation_exposes_panel_state_to_a_member():
    """`TC-JUDGE-C18` (`CT-JUDGE-18`, the surface reflection, rung 0, artifact
    assertion, P0) — no statement of the module reads the verdict table, no read
    is assembled outside the registry either, and no declared public name carries
    a panel-visibility stem: the clause says there is no operation exposing panel
    state to a member 'and none will be added', and this reflection is what holds
    that line against the day somebody adds one."""
    # Positive controls first: the scanner flags the defect and leaves the
    # compliant shapes alone.
    assert _verdict_reads(
        "SELECT band, self_confidence FROM verdict WHERE work_id = :w"
    ), (
        "fixture bug: the scanner no longer detects a verdict read — the "
        "prohibition below would be vacuous"
    )
    assert _verdict_reads(
        "SELECT v.band FROM verdict v JOIN work_unit w ON w.work_id = v.work_id"
    ), (
        "fixture bug: the scanner misses the JOIN form — a read of panel state "
        "reaches the table through a join as often as through a plain FROM"
    )
    assert _verdict_reads(
        "INSERT OR IGNORE INTO verdict (verdict_id, band) VALUES ('x', 'secure')"
    ) == [], (
        "fixture bug: the scanner flags the sanctioned write — the module's own "
        "verdict INSERT is CT-JUDGE-12's whole write surface, and reading panel "
        "state is the clause's prohibition, not writing the row"
    )
    assert _verdict_reads(
        "SELECT e.evidence_id FROM evidence e JOIN work_unit w "
        "ON w.work_id = e.work_id"
    ) == [], (
        "fixture bug: the scanner flags reads of other tables — an over-broad "
        "scan would go red against a compliant module and be disabled"
    )
    assert _visibility_offenders(
        ["prompt_fields", "ScoringWorker", "REPLY_FIELDS", "assemble"]
    ) == [], (
        "fixture bug: the stem scan flags compliant public names — the "
        "declared-surface prohibition below would be vacuous or over-broad"
    )
    assert _visibility_offenders(
        ["panel_state", "read_verdicts", "peer_verdicts"]
    ) == ["panel_state", "peer_verdicts", "read_verdicts"], (
        "fixture bug: the stem scan misses a panel-visibility name — the "
        "declared-surface prohibition below would be vacuous"
    )

    # Arm 1 — the statement registry: no statement reads the verdict table. The
    # sanctioned INSERT is present and is not a read, which is also the control
    # that the scan below ran over the real registry rather than over nothing.
    statements = require(JUDGE_MODULE, "JUDGE_STATEMENTS", issue=ISSUE)
    assert statements, (
        "fixture bug: the judge module declares no statements — the registry "
        "scan below would be vacuous"
    )
    assert "insert_verdict" in statements, (
        "fixture bug: the sanctioned verdict INSERT is not in the registry — "
        "the write-side contract this module's read scan sits beside is "
        "TC-JUDGE-C12's, and its subject has moved"
    )
    reads = {key: _verdict_reads(statement.sql)
             for key, statement in statements.items()}
    offenders = {key: found for key, found in reads.items() if found}
    assert offenders == {}, (
        f"aeh.judge's statement registry carries verdict read(s) {offenders} — "
        "a judge that reads the verdict table has other members' verdicts (and "
        "its own, on any criterion) in its hands at assembly time: the clause "
        "says a judge has no visibility of any other judge's verdict, at any "
        "point, and there is no operation exposing panel state to a member "
        "(CT-JUDGE-18)"
    )

    # Arm 2 — the module text (the completeness arm): a read assembled outside
    # the registry still trips.
    module_text = Path(aeh.judge.__file__).read_text(encoding="utf-8")
    found = _verdict_reads(module_text)
    assert found == [], (
        f"aeh/judge.py's text carries verdict read(s) {found} — the registry "
        "scan above catches a declared read; this arm catches one assembled "
        "outside it (an inline query, a string built at runtime): there is no "
        "operation exposing panel state to a member, and none will be added "
        "(CT-JUDGE-18)"
    )

    # Arm 3 — the declared surface: no public name carries a visibility stem.
    # A member's reach is the module's public surface, so any future operation
    # must be declared here — the name is the shape a future violation must take.
    declared = list(aeh.judge.__all__)
    public = [name for name in dir(aeh.judge) if not name.startswith("_")]
    surface = sorted(set(declared) | set(public))
    assert surface, (
        "fixture bug: the module declares no public surface — the reflection "
        "below would be vacuous"
    )
    offenders = _visibility_offenders(surface)
    assert offenders == [], (
        f"aeh.judge declares public name(s) {offenders} carrying a panel-"
        "visibility stem — the clause's prohibition has no sunset ('and none "
        "will be added'), and an operation a member can reach must be declared "
        "public: a panel-state read cannot be added to this surface without "
        "failing here (CT-JUDGE-18)"
    )


def test_tc_judge_c18_no_sentinel_from_any_verdict_reaches_any_members_request(
    tmp_data_dir, make_fixture_provider
):
    """`TC-JUDGE-C18` (`CT-JUDGE-18`, the sentinel panel + the re-assembly
    differential, rung 3, P0) — one verdict of the full panel carries a sentinel
    confidence, no member's assembled request contains it, and re-assembling
    every request after the whole drive — every verdict then existing — renders
    byte-identically to what the dispatch actually sent: assembly is
    verdict-blind, at any point, including the judge's own verdict on another
    criterion."""
    store = open_store(tmp_data_dir)
    try:
        provider = make_fixture_provider()
        orchestrator, run_id, _version = seed_world(
            store, submissions=("SYN-001",), criterion_specs=_BOTH_HOLISTIC,
        )
        drive_extract(orchestrator, store, provider)

        def completion_for(unit: Any, judge_ref: Any) -> Any:
            """The sentinel rides exactly one panel arm — this criterion, this
            judge — so every OTHER request, and this judge's own request on the
            OTHER criterion, are assembled with the sentinel verdict either
            already persisted or about to be."""
            if unit.criterion_id == "C2" and judge_ref.build_id == EDGE_JUDGE.build_id:
                return verdict_completion(
                    "secure", SENTINEL_CONFIDENCE, build_id=_JUDGE_BUILD,
                    cited_spans=spans(),
                )
            return verdict_completion(
                "secure", 0.9, build_id=_JUDGE_BUILD, cited_spans=spans(),
            )

        judged, captured = drive_score_captured(
            orchestrator, store, provider, completion_for=completion_for,
        )

        # Fixture sanity: the full panel over both criteria, one submission.
        assert judged == 6, (
            f"fixture bug: the drive judged {judged} unit(s) — the full panel "
            "is two holistic criteria by three judges over one submission "
            "(six requests), which is what makes every (judge, criterion) arm "
            "of the clause a real pair here"
        )
        assert len(captured) == judged, (
            "fixture bug: the capture missed a dispatch — the differential "
            "below is over every request the panel assembled"
        )
        judges = {judge_ref.build_id for _unit, judge_ref, _request in captured}
        arms = {(unit.criterion_id, judge_ref.build_id)
                for unit, judge_ref, _request in captured}
        assert len(judges) == 3, (
            f"fixture bug: the drive judged through {len(judges)} judge(s) — "
            "the clause's 'any other judge' needs the full three-judge panel"
        )
        assert arms == {(criterion, judge)
                        for criterion in ("C1", "C2") for judge in judges}, (
            f"fixture bug: the panel judged {sorted(map(str, arms))} — every "
            "judge must have judged BOTH criteria, or the clause's 'including "
            "its own on another criterion' has no pair to test"
        )

        sentinel_triples = [
            (index, unit, judge_ref)
            for index, (unit, judge_ref, _request) in enumerate(captured)
            if unit.criterion_id == "C2" and judge_ref.build_id == EDGE_JUDGE.build_id
        ]
        assert len(sentinel_triples) == 1, (
            "fixture bug: the sentinel completion did not land on exactly one "
            "(criterion, judge) arm — the scan below needs one sentinel verdict"
        )
        sentinel_index, sentinel_unit, _sentinel_ref = sentinel_triples[0]
        assert sentinel_index < len(captured) - 1, (
            "fixture bug: the sentinel arm judged last — no member's request "
            "was assembled after the sentinel verdict existed, and the scan "
            "below would sweep only pre-verdict assemblies"
        )

        # The positive control: the sentinel is real panel state — exactly one
        # verdict row in the run carries it, on the arm the program planted it
        # on, and no other verdict carries anything like it.
        handle = store.cohort(ORCH_COHORT_ID)
        rows = handle.query(
            "SELECT v.verdict_id, v.self_confidence FROM verdict v "
            "JOIN work_unit w ON w.work_id = v.work_id WHERE w.run_id = :r",
            r=run_id,
        )
        assert len(rows) == judged, (
            f"fixture bug: the ledger holds {len(rows)} verdict row(s) for a "
            f"{judged}-unit drive — the panel state below is incomplete"
        )
        sentinel_rows = [
            dict(row) for row in rows
            if float(row["self_confidence"]) == pytest.approx(SENTINEL_CONFIDENCE)
        ]
        assert len(sentinel_rows) == 1, (
            f"fixture bug: {len(sentinel_rows)} verdict row(s) carry the "
            f"sentinel ({SENTINEL_CONFIDENCE}) — the scan below needs exactly "
            "one sentinel verdict, or the needle is not panel state but noise"
        )
        assert sentinel_rows[0]["verdict_id"] == sentinel_unit.work_id, (
            "fixture bug: the sentinel persisted on a different arm than the "
            "program planted it on — the scan below would sweep a panel with "
            "no sentinel in it"
        )

        # The sentinel scan, over every captured request (the pre-dispatch
        # renders, in drive order). The needle must be absent from ALL of them:
        # the arms judged after the sentinel verdict persisted (another judge's
        # verdict — the leak had material), and the sentinel judge's own request
        # on the OTHER criterion (its own verdict — the clause's named case).
        for index, (unit, judge_ref, request) in enumerate(captured):
            leaves = string_leaves(request)
            assert leaves, (
                f"fixture bug: request {index} rendered no string leaves — the "
                "scan below would be vacuous for this arm"
            )
            paths = [path for path, value in leaves if _NEEDLE in value]
            assert paths == [], (
                f"request {index} ({unit.criterion_id}/{judge_ref.build_id}) "
                f"carries the sentinel at {paths} — a member's assembled "
                "request contains a verdict: a judge has no visibility of any "
                "other judge's verdict, at any point, including its own on "
                "another criterion, and there is no operation exposing panel "
                "state to a member (CT-JUDGE-18)"
            )

        # The differential: re-assemble every unit AFTER the whole drive — when
        # every verdict the panel landed exists — and the render is byte-
        # identical to the request the dispatch actually sent. Whatever the
        # sentinel scan could miss (a verdict read that formats the value away),
        # a consultation of ANY verdict drifts the re-assembly from a capture
        # taken while verdicts were still accumulating.
        payload_fn = require(JUDGE_MODULE, "prompt_fields", issue=ISSUE)
        worker_type = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)
        for index, (unit, judge_ref, request) in enumerate(captured):
            reassembled = worker_type(store, provider, judge_ref).assemble(unit)
            assert fields_of(payload_fn, request) == \
                fields_of(payload_fn, reassembled), (
                f"re-assembling arm {index} ({unit.criterion_id}/"
                f"{judge_ref.build_id}) after the whole drive differs from the "
                "request its dispatch actually sent — assembly consulted panel "
                "state: every verdict then existed in the ledger, so a verdict-"
                "read drifts the re-assembly from a capture taken while "
                "verdicts were still accumulating. Assemble is a pure function "
                "of the unit and the rubric, and there is no operation "
                "exposing panel state to a member (CT-JUDGE-18)"
            )
            leaves = string_leaves(reassembled)
            paths = [path for path, value in leaves if _NEEDLE in value]
            assert paths == [], (
                f"the re-assembled arm {index} carries the sentinel at {paths} "
                "— with every verdict in the ledger the re-assembly had the "
                "whole panel available to leak, and it did (CT-JUDGE-18)"
            )
    finally:
        store.close()