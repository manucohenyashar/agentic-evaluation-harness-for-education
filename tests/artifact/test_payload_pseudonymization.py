"""No assembled payload carries a student's name.

Cases: `TC-PROV-21` (`NFR-PROV-04`, **P0**, artifact assertion, rung 0, test plan §5.2) and
`SEC-04` (`NFR-PROV-04`, `NFR-JUDGE-04`, §6.5). Issue #24 (TS-07).

Both cases have the same oracle — a pattern scan over assembled payloads against the roster's
real names — and differ in scope: `TC-PROV-21` asserts it of the payloads a 350-submission run
assembles, `SEC-04` asserts it as a trust-boundary property with the disclosure named
(*machine to remote provider*, information disclosure). They are one scan, run twice, because
the plan states them as two cases and the RTM counts them separately.

`NFR-PROV-04` names its own acceptance form: *"an assertion over assembled payloads is the
acceptance form."* Design §3.2 is explicit that redaction is **not** the mitigation — the judge
needs the actual submission text — so pseudonymization at assembly is the only thing standing
between a cohort's names and a remote provider.

**Written ahead of implementation** (issue #78, the `M-JUDGE` story that owns request
assembly). Expected to fail with `NotImplementedYet` until it lands. Remove the `writtenahead`
marker — not the test — when #78 closes.

Why #78 is the whole blocker, and no orchestrator is needed
------------------------------------------------------------
Both cases read as though they need a full 350-submission *run*, which would put them behind
`M-ORCH`, `M-INGEST` and most of the pipeline. They do not. Design §3.10 declares
`assemble(unit) -> ScoringRequest` **pure** — the comment in the Interfaces block says so in as
many words: `# pure, testable`. A pure assembler can be driven 350 times by a test with no
scheduler, no store and no model call, which is exactly why the design made it pure and is what
keeps these two P0 cases at rung 0 rather than rung 3.

What is genuinely deferred: `M-EXTRACT`, `M-SYNTH` and `M-INGEST` assemble payloads too, and
`SEC-04`'s "every assembled payload" includes theirs. Their assemblers join `_assemblers()`
below when those modules land; until then this asserts the scoring path, which is the one
carrying the submission text. Recorded here rather than left to be noticed.

Interface expectations this test places on #78
-----------------------------------------------
Stated in full, so a signature mismatch is a deliberate reconciliation rather than a surprise —
the same courtesy `TS-00` extended to #18.

| Name | Status in the design |
|---|---|
| `aeh.judge` as `M-JUDGE`'s module | convention from `tests/support/impl.py` |
| `ScoringWorker.assemble(unit) -> ScoringRequest` | defined, design §3.10 Interfaces |
| `WorkUnit`, imported from `aeh.orch` | **defined in design v1.5**, §3.7 — `M-ORCH` owns the ledger, so the type belongs there rather than in §3.10 where it is merely consumed. Its fields had been nowhere specified; raised as a finding in PR #161 |
| `WorkUnit(student_ref=, student_name=, submission_id=, criterion_id=, submission_text=, ...)` | matches v1.5's definition, which also carries `work_id`, `run_id`, `stage`, `judge` and `attempt` — none of which this scan reads. `student_name` being **on** the unit is now design, with `work_unit_fields()`'s reasoning quoted as the reason: the pseudonymization boundary is at assembly, not at the ledger |
| A concrete `ScoringWorker` implementation | **not named in the design** — resolved by duck-typing whatever `aeh.judge` exports |

The scan itself places no requirement on `ScoringRequest`'s shape: `strings_in()` walks
dataclasses, mappings and sequences alike, deliberately, because `NFR-PROV-04` is a property of
the whole assembled object rather than of a field list somebody remembered to enumerate.
"""

from __future__ import annotations

import pytest

from tests.support.impl import JUDGE_MODULE, ORCH_MODULE, require
from tests.support.roster import (
    ROSTER_SIZE,
    NameHit,
    Student,
    build_roster,
    carries_student_ref,
    roster_name_patterns,
    scan_for_names,
    strings_in,
    students_named,
)

ISSUE = "#78"


def _assemblers():
    """Every assembler whose output `SEC-04` must scan.

    One entry today. `M-EXTRACT` (#68), `M-SYNTH` and `M-INGEST` join it as they land — each
    assembles a payload carrying submission text, and each is therefore in `SEC-04`'s scope.
    """
    worker_cls = require(JUDGE_MODULE, "ScoringWorker", issue=ISSUE)
    return (("judge", worker_cls),)


# --- the cases ---------------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_prov_21_no_assembled_payload_carries_a_student_name(network_guard):
    """TC-PROV-21 — across a 350-submission run, every payload carries `student_ref` and none
    carries a name.

    Oracle (§5.2): *pattern scan over assembled artifacts*. Both halves of the expected result
    are asserted:

    - **no name**, scanned against the full roster rather than against the student the payload
      belongs to. Scanning only the payload's own student would pass a bug that leaked
      *someone else's* name into a request — a worse disclosure, since it crosses students as
      well as the boundary, and one this case would otherwise be structurally unable to see;
    - **`student_ref` present**, because a payload carrying neither the name nor the ref is not
      a privacy success. It is an unattributable judgment.

    The socket guard is asserted too: assembly is pure, so nothing here may reach the network.
    """
    roster = build_roster()
    assert len(roster) == ROSTER_SIZE

    patterns = roster_name_patterns(roster)
    hits: list[NameHit] = []
    missing_ref: list[str] = []

    for kind, worker_cls in _assemblers():
        worker = worker_cls()
        for student in roster:
            unit = _work_unit_for(student)
            payload = worker.assemble(unit)
            payload_id = f"{kind}/{student.student_ref}"
            hits.extend(scan_for_names(payload_id, payload, roster, patterns))
            if not carries_student_ref(payload, student):
                missing_ref.append(payload_id)

    assert not hits, (
        "NFR-PROV-04: assembled payloads carry student_ref only and never a student name. "
        f"{len(hits)} disclosure(s):\n  " + "\n  ".join(str(h) for h in hits[:20])
    )
    assert not missing_ref, (
        "these payloads carry no student_ref, so the judgment they produce cannot be "
        "attributed: " + ", ".join(missing_ref[:20])
    )
    network_guard.assert_no_network()


@pytest.mark.writtenahead
def test_sec_04_a_full_run_discloses_no_name_to_the_provider(network_guard):
    """SEC-04 — the same scan as a trust-boundary probe. §6.5.

    | Field | Value |
    |---|---|
    | Trust boundary | prompt payloads, machine to remote provider |
    | Threat | information disclosure |
    | Probe | scan every assembled payload in a full run against the roster's real names |
    | Expected defense | `student_ref` only; no name in any payload |

    The same property as `TC-PROV-21`, computed the other way round: `TC-PROV-21` walks each
    payload and reports the names in it, this one collects every string the run would dispatch
    and asks which roster names appear anywhere in that set.

    Both are here because the plan states them as two cases and the RTM counts them separately
    — `TC-PROV-21` against `NFR-PROV-04`, `SEC-04` against `NFR-PROV-04` **and**
    `NFR-JUDGE-04`, at the machine-to-provider trust boundary. Neither is stronger than the
    other, and an earlier draft of this docstring claimed it was: it argued that
    `TC-PROV-21` used a "per-student framing" a whole-roster embed would slip past. That was
    simply false — `TC-PROV-21` scans each payload against the **full** roster and would catch
    that leak 350 times over. Manufacturing a distinction makes the RTM look better covered
    than it is, which is the failure mode a test plan exists to prevent.
    """
    roster = build_roster()
    patterns = roster_name_patterns(roster)

    dispatched: set[str] = set()
    for _, worker_cls in _assemblers():
        worker = worker_cls()
        for student in roster:
            dispatched.update(strings_in(worker.assemble(_work_unit_for(student))))

    disclosed = sorted(
        {name for name, pattern in patterns.items() if any(pattern.search(t) for t in dispatched)}
    )

    assert not disclosed, (
        "SEC-04: a name reached the payloads that cross the machine-to-provider boundary. "
        "NFR-PROV-04 protects student text by pseudonymization, not redaction (design §3.2), "
        "so a name here is disclosed verbatim to the provider. Names found: "
        + ", ".join(disclosed[:20])
    )
    network_guard.assert_no_network()


def work_unit_fields(student: Student) -> dict[str, str]:
    """The fields of one scoring work unit — **carrying the name that must not get out.**

    `TC-PROV-C13` states the construction this case needs, in as many words: *"assert by
    scanning assembled bodies for a **sentinel student name present in the fixture**."* The
    emphasis is the whole case. A work unit built from `student_ref` alone hands the assembler
    nothing to leak, so the scan cannot find a name however broken the assembler is — the two
    P0 cases would then assert over an input where the disclosure they name is structurally
    impossible, and pass against an assembler that copies every field it is given.

    That is not hypothetical: it was the first draft of this file, and a reviewer's stub
    assembler — one that copied every attribute of the unit into the payload *and* added a
    `display_name` field — passed both cases.

    So the unit carries the roster identity the real one carries. A submission is a row that
    knows whose it is; `M-JUDGE`'s job (`FR-JUDGE-01`'s whitelist schema, `NFR-JUDGE-04`) is to
    put `student_ref` in the request and leave `student_name` behind. The submission *text*
    deliberately contains no name — design §3.2 says student text travels verbatim because the
    judge needs it, so asking the assembler to redact prose would be asserting a requirement
    the design does not make.
    """
    return {
        "student_ref": student.student_ref,
        # The sentinel. Present in the fixture, forbidden in the payload.
        "student_name": student.full_name,
        "submission_id": f"sub-{student.student_ref}",
        "criterion_id": "crit-friction-01",
        "submission_text": (
            "The block slides because friction is lower than gravity, so it accelerates."
        ),
    }


def _work_unit_for(student: Student):
    """One scoring work unit for `student`, built against design §3.7's `WorkUnit`.

    Kept in one place so the reconciliation with #78's actual signature is a single edit rather
    than one per case.
    """
    # `aeh.orch`, not `aeh.judge`: design v1.5 puts `WorkUnit` in §3.7 because `M-ORCH` owns
    # the ledger. `M-JUDGE` consumes it (§3.10's `assemble(unit)`), which is why this file's
    # blocker stays #78 — that is the story whose landing makes the case runnable, and it lands
    # strictly after the ledger it depends on.
    work_unit_cls = require(ORCH_MODULE, "WorkUnit", issue=ISSUE)
    return work_unit_cls(**work_unit_fields(student))


# --- controls for the scan itself ----------------------------------------------------------------
#
# Not written ahead: these assert about `tests/support/roster.py`, which exists now. They run in
# TEST_CMD and they are what stops the two cases above from being green-by-blindness once #78
# lands — a scan that finds nothing in a leaking payload is indistinguishable, from the report,
# from a payload that does not leak.


def test_the_work_unit_handed_to_the_assembler_actually_carries_a_name_to_leak():
    """The control that keeps the two cases above from becoming unfalsifiable.

    `TC-PROV-21` and `SEC-04` scan an assembled payload for a name. If the *input* to the
    assembler carries no name, neither case can fail — they pass against an assembler that
    copies every field it is handed, which is exactly the bug they exist to catch. That was
    the first draft of this file, and it passed against a deliberately leaky stub.

    Nothing about the two cases announces that failure when it happens: they go green. So the
    property is asserted here instead, against the fixture rather than the implementation,
    where it runs in `TEST_CMD` today and stays true regardless of what #78 builds.
    """
    roster = build_roster()

    for student in (roster[0], roster[174], roster[-1]):
        fields = work_unit_fields(student)
        hits = scan_for_names("work-unit", fields, roster)

        assert hits, (
            f"the work unit for {student.student_ref} carries no roster name, so TC-PROV-21 "
            f"and SEC-04 are scanning an input the disclosure cannot come from. TC-PROV-C13: "
            f"'a sentinel student name present in the fixture'."
        )
        assert student.student_ref in hits[0].student_refs
        # ...and it carries the ref too, so the *correct* assembler has something to emit.
        assert carries_student_ref(fields, student)


def test_the_scan_catches_a_planted_name_in_any_shape_of_payload():
    """The control that matters most. Each shape below is a payload that leaks.

    `strings_in` walks dataclasses, mappings and sequences because `NFR-PROV-04` is a property
    of the whole assembled object. If it silently stopped walking one of those shapes, both
    cases above would report a clean run over a payload carrying a name in plain sight.
    """
    roster = build_roster(size=3)
    victim = roster[0]

    shapes = {
        "flat string field": {"submission": f"Written by {victim.full_name}."},
        "nested mapping": {"meta": {"author": victim.given_name}},
        "list of fields": [("system", "score this"), ("submission", victim.family_name)],
        "tuple of tuples": (("header", victim.full_name),),
        "bytes": {"raw": f"name: {victim.given_name}".encode("utf-8")},
        "dict key": {victim.family_name: "value"},
    }

    for label, payload in shapes.items():
        hits = scan_for_names(label, payload, roster)
        assert hits, f"the scan missed a planted name in a payload shaped as a {label}"
        # The victim is named, and the report says so. A shared surname names several
        # students, which is why this is a membership test and not an equality.
        assert victim.student_ref in hits[0].student_refs


def test_the_scan_catches_a_name_in_an_object_that_is_not_a_dataclass():
    """A `ScoringRequest` need not be a dataclass. #78 has not chosen yet, and a scan that
    only understood dataclasses would go blind on an ordinary class without saying so."""
    roster = build_roster(size=2)
    victim = roster[1]

    class Request:
        def __init__(self, text: str) -> None:
            self.submission = text
            self.criterion_id = "crit-1"

    hits = scan_for_names("plain-object", Request(f"by {victim.full_name}"), roster)

    assert victim.full_name in {h.name for h in hits}
    assert all(victim.student_ref in h.student_refs for h in hits if h.name == victim.full_name)


def test_the_scan_is_case_insensitive_and_word_anchored():
    """Both properties, and both are load-bearing in opposite directions.

    Case-insensitive, because an implementation that lowercased a name before embedding it
    would disclose exactly as much while escaping a case-sensitive scan. Word-anchored, because
    an unanchored scan reports a substring of an unrelated word and the resulting false
    positives are what get a P0 gate exempted into uselessness.
    """
    roster = build_roster(size=1)
    victim = roster[0]

    assert scan_for_names("lowered", {"t": victim.given_name.lower()}, roster)
    assert scan_for_names("uppered", {"t": victim.full_name.upper()}, roster)
    assert not scan_for_names("substring", {"t": f"un{victim.given_name}able"}, roster)


def test_the_scan_reports_nothing_for_a_correctly_pseudonymized_payload():
    """The negative control. A scan that reports everything gets switched off as fast as one
    that reports nothing, and this is the payload the system is supposed to produce."""
    roster = build_roster(size=5)
    student = roster[2]
    payload = {
        "student_ref": student.student_ref,
        "criterion": "States that friction opposes motion.",
        "submission": "The block slides because friction is lower than gravity.",
    }

    assert scan_for_names("clean", payload, roster) == []
    assert carries_student_ref(payload, student)


def test_carries_student_ref_is_not_satisfied_by_a_different_students_ref():
    """`student_ref` present must mean *this* student's, or the attribution half of
    `TC-PROV-21` passes for a payload that credits the work to somebody else."""
    roster = build_roster(size=5)

    payload = {"student_ref": roster[0].student_ref}

    assert carries_student_ref(payload, roster[0])
    assert not carries_student_ref(payload, roster[1])


def test_a_shared_name_names_every_student_who_holds_it():
    """A disclosed surname discloses it for every student who has it, and the report says so.

    Found by the shape control above rather than by foresight: an earlier scanner reported one
    `student_ref` per hit — whichever won a dict lookup — so a shared surname named the wrong
    student in the failure report. A P0 security failure that fingers the wrong person reads as
    a test bug, and gets treated as one.
    """
    roster = build_roster()
    shared = next(
        name
        for name in {s.family_name for s in roster}
        if len(students_named(roster, name)) > 1
    )
    expected = students_named(roster, shared)

    hits = scan_for_names("leak", {"submission": f"see {shared}"}, roster)

    assert len(expected) > 1
    assert [h.student_refs for h in hits] == [expected]


def test_the_roster_is_deterministic_and_the_right_size():
    """§4.4: `F-SYNTH` is *"deterministically generated from a seed so the whole suite
    reproduces"*, and it is 350 submissions. A roster that varied between runs would make any
    failure above irreproducible — §4.6 treats that as a P1 defect in itself."""
    first = build_roster()
    second = build_roster()

    assert first == second
    assert len(first) == ROSTER_SIZE
    assert len({s.student_ref for s in first}) == ROSTER_SIZE
    assert len({s.full_name for s in first}) == ROSTER_SIZE


def test_no_roster_name_collides_with_ordinary_rubric_prose():
    """The property that lets this scan stay strict instead of accumulating exclusions.

    A roster of common given names turns "mark the diagram", "grace period" and "will not" into
    findings, and the fix people reach for is an exclusion list that grows until the scan
    cannot see a real leak. The roster is generated from an unusual syllable table precisely so
    that never starts; this asserts it against the kind of text the payloads actually carry.
    """
    roster = build_roster()
    prose = {
        "criterion": "The student must mark the free-body diagram and show their work.",
        "rubric": "Grace under partial credit: award the band if the will of the argument holds.",
        "submission": "The block slides because friction is lower than gravity; I will show why.",
        "system": "You are scoring one criterion. Do not award numeric points.",
    }

    assert scan_for_names("prose", prose, roster) == []
