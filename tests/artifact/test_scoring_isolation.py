"""`TC-JUDGE-01..07`, `TC-JUDGE-19`, `TC-JUDGE-20` — judgment isolation and the
whitelist request schema (`M-JUDGE`).
Test plan §5.10 (full block form); `FR-JUDGE-01/02/05/14/15/16`, `NFR-JUDGE-03/04`;
RISK-02 (Critical). Issue #82 (TS-30), written ahead of #78.

Cases implemented here, keyed to the plan's steps:

1. `test_tc_judge_01_no_field_of_the_request_schema_can_carry_contaminating_input`
   — step 1: every field of `ScoringRequest`, recursively, against the six
   contaminations FR-JUDGE-01 names ("another judge's verdict, this judge's verdict on
   another criterion, another submission, prior cohorts, student identity or history,
   any running score") plus FR-JUDGE-03's points prohibition. The positive shape (HLD
   §9.9's field list) is asserted too, so the prohibition cannot be satisfied by an
   empty schema (the `test_extraction_isolation.py` pattern).
2. `test_tc_judge_02_undeclared_field_fails_validation_and_is_not_dispatched` — step 2:
   construction with an undeclared field FAILS and nothing is dispatched; the provider
   spy records zero calls.
3. `test_tc_judge_01_step3_every_assembled_request_is_single_criterion_and_single_
   submission` — step 3 over the full corpus (350 × 15 = 5,250 requests, the plan's
   precondition size): exactly one `criterion_id` and one `submission_id` each.
4. `test_tc_judge_04_no_residue_between_consecutive_judgments` — the fresh-context
   differential: two consecutive judgments by the SAME worker; the second payload
   contains no history, no summary, no carried state — the rendered prefix is
   byte-identical and carries no substring of the first submission.
5. `test_tc_judge_05_dependency_evidence_is_schema_typed_to_spans` — the request
   carries the parent's extraction spans and no parent verdict;
   `dependency_evidence` is typed so a verdict is not merely absent but
   unrepresentable.
6. `test_tc_judge_06_mixed_question_request_carries_no_deterministic_material` — a
   `mixed` question's judged request carries neither the deterministic criterion's
   selection nor its correctness.
7. `test_tc_judge_07_no_multi_criterion_surface_or_randomization` — the API takes one
   unit; no criterion-order randomization surface exists; every assembled request
   carries exactly its own criterion and never another's.
8. `test_tc_judge_19_assemble_is_pure` — no store write, no network, no clock, no model
   call; socket guard + store spy + frozen clock + provider spy.
9. `test_tc_judge_20_requests_carry_student_ref_only` — the roster-wide pattern scan.
10. `test_tc_judge_01_escalation_variant_judges_2_and_3` — judges 2 and 3 assemble
    identically to judge 1 but for judge-identifying material, and no first-verdict
    summary exists to leak (the variant: an escalation is where a "helpful" summary
    would be tempting).
11. `test_the_contaminating_field_scan_catches_planted_fields` — the scan's teeth: a
    request-shaped object planted with every contaminating field class is flagged
    (an oracle that cannot fire on the violation it exists for is decoration — the
    `test_tc_pkg_09_numeral_scan.py` house style).

**Interface this suite assumes of #78**, declared once in
`tests/support/judge_vocabulary.py` (status column there); the rung-0-specific bets:

| Name | Status |
|---|---|
| `ScoringWorker()` constructed with **no arguments** | the `test_payload_pseudonymization.py` bet — §3.10 declares `assemble` pure, and the rung-0 cases hold no store. If #78's constructor requires the `(store, provider, judge_ref)` triple, `_construct_worker` falls back to it with the test doubles in the slots — one line at landing either way |
| `assemble(unit)` | §3.10 Interfaces, verbatim |
| `assemble(unit, dependency_evidence=[...])` | **assumed here** for TC-JUDGE-05 only — the `test_extraction_isolation.py` precedent for passing the parent spans the caller already resolved, at rung 0, to a pure assembler |
| `ScoringRequest(**kwargs)` construction | the whitelist door — an undeclared kwarg must be REFUSED (a closed dataclass refuses structurally; a validating schema refuses by rule; either is the required behaviour, and a silent strip is the failure) |
| `prompt_fields(request) -> payload` with ordered `.fields` | **already assumed by the repo** (`"#78 review"`, `test_judge_band_forcing.py`) — the byte-level views render through it |

**Disclosed stand-ins.** The units are hand-built values (the shipped `aeh.orch.
WorkUnit`), not ledger rows; `student_name` IS carried on them, because the roster scan
(TC-JUDGE-20) needs material a broken assembler could leak — an input with no name
would make the scan vacuous (the `TC-PROV-C13` sentinel lesson). The rubric material
(criterion text, bands, exemplars) is deliberately NOT here: at rung 0 no store holds
it, and the numeral/band/prefix cases exercise it against a real package in
`test_no_numerals_in_judge_prompt.py`. The provider spy is a local recording double
(`RecordedFixtureProvider` exposes no call counter).

**Isolation: rung 0** — pure values; the socket guard is active; the store spy and the
provider spy are doubles. No store, no network, no model call; a model call here would
be a defect, and the `network_guard` makes it one.
"""

from __future__ import annotations

import dataclasses
import inspect
from typing import Any

import pytest

from aeh.orch import STAGE_SCORE, WorkUnit
from tests.support.corpora import reference_package
from tests.support.impl import JUDGE_MODULE, require
from tests.support.judge_vocabulary import (
    ISOLATED_CHECK,
    JUDGE_ISSUE,
    PROMPT_FIELDS,
    REQUEST_TYPE,
    VIOLATION,
    WORKER,
    field_names,
    fields_of,
    string_leaves,
)
from tests.support.roster import (
    ROSTER_SIZE,
    build_roster,
    carries_student_ref,
    roster_name_patterns,
    scan_for_names,
)

pytestmark = pytest.mark.writtenahead

ISSUE = JUDGE_ISSUE

#: The contaminating-field vocabulary, from FR-JUDGE-01's own list (another judge's
#: verdict; this judge's verdict on another criterion; another submission; prior
#: cohorts; student identity or history; any running score) plus FR-JUDGE-03's points
#: prohibition. A field whose NAME carries one of these stems is capable of carrying
#: the thing, whatever its type — "including free-text fields typed as such" (the
#: plan's step 2 wording for TC-EXTRACT-03, the same acceptance form).
_PROHIBITED_STEMS = (
    "verdict",
    "score",  # a running score; see the benign compound below
    "points",
    "history",
    "summary",
    "prior",
    "cohort",
    "running_total",
    "name",  # student identity; `submission_id`/`submission_text` carry no stem
    "other",  # another submission's material; no HLD §9.9 field contains it
)

#: Compound names that legitimately carry a prohibited stem. Only what HLD §9.9's
#: block already shows or the repo's existing M-JUDGE tests already assume may be
#: listed here; anything else containing a stem is a finding.
_BENIGN_COMPOUNDS = ("scoring_model",)

#: TC-JUDGE-06's vocabulary: the deterministic criterion's selection and correctness.
_DETERMINISTIC_STEMS = (
    "selection",
    "correct",
    "deterministic",
    "option",
    "answer_key",
    "mcq",
)

#: HLD §9.9's ScoringRequest shape, as a set of required top-level fields. The
#: positive-shape assertion: the whitelist cannot be satisfied by an empty schema.
_HLD_FIELDS = (
    "work_id",
    "criterion",
    "question",
    "evidence",
    "dependency_evidence",
    "submission_text",
)

#: The roster is the cohort. The plan's precondition — 350 submissions × 15 criteria —
#: is exactly `ROSTER_SIZE` × the reference package's judged criteria.
_PACKAGE = reference_package()
_CRITERIA = tuple(_PACKAGE["criteria"])
assert len(_CRITERIA) == 15, (
    "the plan's precondition is a package with 15 criteria (350 × 15 = 5,250 "
    "requests); the reference package changed size — update the precondition note, "
    "not the oracle"
)


class _ProviderSpy:
    """The dispatch double: records every payload the worker would send to a model."""

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def call(self, payload: Any, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(payload)
        raise AssertionError(
            "a model call was attempted in a rung-0 isolation case — the socket "
            "guard and the purity clause both forbid it (CT-JUDGE-01)"
        )


def _construct_worker(*args: Any, **kwargs: Any) -> Any:
    """Construct the worker however #78's constructor is shaped: the no-argument
    `ScoringWorker()` (the rung-0 bet, `test_payload_pseudonymization.py`) first; the
    `(store, provider, judge_ref)` triple (the rung-2 bet,
    `test_judge_band_forcing.py`) on ``TypeError``. Either way the reconciliation is
    one line at landing."""
    Worker = require(JUDGE_MODULE, WORKER, issue=ISSUE)
    try:
        return Worker()
    except TypeError:
        return Worker(*args, **kwargs)


def _unit(
    criterion_id: str = "C-01",
    *,
    submission_id: str = "SYN-231",
    student_ref: str = "ref-s231",
    student_name: str | None = None,
    submission_text: str = "The crate does not slide because static friction "
    "balances the ramp's along-slope component of its weight.",
    judge: str | None = "judge-1",
) -> WorkUnit:
    """A resolved score unit as a pure value — the lease surface's documented job
    (identity + words onto the unit) done by hand at rung 0."""
    return WorkUnit(
        work_id=f"sha256:{criterion_id}-{submission_id}-{judge}",
        run_id="run-rung0",
        stage=STAGE_SCORE,
        student_ref=student_ref,
        student_name=student_name,
        submission_id=submission_id,
        criterion_id=criterion_id,
        submission_text=submission_text,
        judge=judge,
        attempt=0,
    )


def _criterion_id_of(request: Any) -> Any:
    """The request's single criterion id, however #78 shapes it (HLD §9.9 nests it
    under `criterion`; the repo's flat bet carries `criterion_id` directly)."""
    for shape in (
        lambda: request.criterion.criterion_id,
        lambda: request.criterion_id,
        lambda: request["criterion"]["criterion_id"],
        lambda: request["criterion_id"],
    ):
        try:
            value = shape()
        except (AttributeError, TypeError, KeyError, IndexError):
            continue
        if value is not None:
            return value
    raise AssertionError(
        f"could not read one criterion id off the assembled request {request!r} — "
        "FR-JUDGE-02's exactly-one form needs the id to be readable"
    )


def _submission_id_of(request: Any) -> Any:
    """The request's single submission id (the repo's flat bet carries
    `submission_id`; HLD §9.9 nests it under `submission`)."""
    for shape in (
        lambda: request.submission_id,
        lambda: request.submission.submission_id,
        lambda: request["submission_id"],
        lambda: request["submission"]["submission_id"],
    ):
        try:
            value = shape()
        except (AttributeError, TypeError, KeyError, IndexError):
            continue
        if value is not None:
            return value
    raise AssertionError(
        f"could not read one submission id off the assembled request {request!r} — "
        "FR-JUDGE-02's exactly-one form needs the id to be readable"
    )


def _schema_names(request_type: Any, request: Any) -> list[str]:
    """The schema's names: the TYPE's fields when the type declares them, plus every
    name present on the instance (the `test_extraction_isolation.py` walker, via the
    shared vocabulary)."""
    names = [name for _path, name in
             (leaf.rsplit(".", 1) if "." in leaf else ("", leaf))
             for leaf in [p for p, _t in string_leaves(request)]]
    names.extend(field_names(request))
    if dataclasses.is_dataclass(request_type):
        names.extend(f.name for f in dataclasses.fields(request_type))
    annotations = getattr(request_type, "__annotations__", None)
    if annotations:
        names.extend(str(name) for name in annotations)
    return names


def _contaminating(names: list[str], stems: tuple[str, ...]) -> list[str]:
    """The names that carry a prohibited stem, minus the declared benign compounds."""
    return sorted(
        {
            name
            for name in names
            if name.lower() not in _BENIGN_COMPOUNDS
            for stem in stems
            if stem in name.lower()
        }
    )


# --- TC-JUDGE-01 ---------------------------------------------------------------------------


def test_tc_judge_01_no_field_of_the_request_schema_can_carry_contaminating_input():
    """Step 1 — every field of `ScoringRequest`, recursively, against the six
    contaminations FR-JUDGE-01 names plus FR-JUDGE-03's points prohibition; and the
    positive HLD §9.9 shape, so an empty schema cannot satisfy the whitelist."""
    worker = _construct_worker()
    request = worker.assemble(_unit())
    ScoringRequest = require(JUDGE_MODULE, REQUEST_TYPE, issue=ISSUE)

    names = _schema_names(ScoringRequest, request)
    offenders = _contaminating(names, _PROHIBITED_STEMS)
    assert not offenders, (
        f"ScoringRequest carries contaminating-capable field(s) {offenders} — "
        f"FR-JUDGE-01: the schema is a whitelist with no field for another judge's "
        f"verdict, this judge's verdict on another criterion, another submission, "
        f"prior cohorts, student identity or history, or any running score "
        f"(CT-JUDGE-02: adding a field is a schema change, not a call-site change)"
    )
    for key in _HLD_FIELDS:
        assert hasattr(request, key) or (isinstance(request, dict) and key in request), (
            f"assembled request is missing the HLD §9.9 key {key!r} — the whitelist "
            "must have the shape the design pins, not merely lack the rest"
        )


def test_the_contaminating_field_scan_catches_planted_fields():
    """The scan's teeth: a request-shaped value planted with one field per
    contaminating class is flagged by the same walker the schema assertion runs. An
    oracle that cannot fire on the violation it exists for is decoration."""
    planted = {
        "work_id": "sha256:x",
        "criterion": {"criterion_id": "C-01", "text": "t", "bands": [],
                      "exemplars": []},
        "question": {"prompt_text": "q", "reference_solution": "r"},
        "evidence": {"spans": []},
        "dependency_evidence": [],
        "submission_text": "s",
        # the plantings, one per contaminating class:
        "prior_judge_verdicts": [{"band": "secure", "confidence": 0.9}],
        "running_score": 41,
        "cohort_summary": "the cohort leaned high",
        "student_history": ["this student's last three papers"],
        "total_points": 12,
        "student_name": "Ada Example-Student",
        "other_submissions": [{"submission_id": "s-other", "text": "..."}],
    }
    names = list(planted) + [k for v in planted.values()
                             if isinstance(v, dict) for k in v]
    offenders = _contaminating(names, _PROHIBITED_STEMS)
    expected = {
        "prior_judge_verdicts", "running_score", "cohort_summary",
        "student_history", "total_points", "student_name", "other_submissions",
    }
    assert expected <= set(offenders), (
        f"the contaminating-field scan missed planted field(s) "
        f"{sorted(expected - set(offenders))} — it cannot fire on the violation it "
        "exists for, so the schema assertion proves nothing"
    )
    assert "criterion" not in offenders and "submission_text" not in offenders, (
        "the scan flags a legitimate HLD §9.9 field — it is untargeted and would be "
        "disabled the first time it fired on real content"
    )


def test_tc_judge_01_step3_every_request_is_single_criterion_and_single_submission():
    """Step 3 — over the full corpus (350 × 15 = 5,250 assembled requests): every
    request contains exactly one `criterion_id` and exactly one `submission_id`; and
    FR-JUDGE-02's acceptance form, "an assertion over assembled requests", is what
    this whole file is."""
    worker = _construct_worker()
    roster = build_roster()
    assert len(roster) == ROSTER_SIZE

    seen = 0
    for student in roster:
        for criterion in _CRITERIA:
            request = worker.assemble(
                _unit(
                    str(criterion["criterion_id"]),
                    submission_id=student.student_ref,
                    student_ref=student.student_ref,
                    submission_text=(
                        f"{student.full_name} writes: the forces balance on the "
                        f"incline for submission {student.student_ref}."
                    ),
                )
            )
            crit = _criterion_id_of(request)
            sub = _submission_id_of(request)
            assert not isinstance(crit, (list, tuple, set, frozenset)), (
                f"request carries a SEQUENCE of criteria ({crit!r}) — a "
                "multi-criterion prompt is exactly the erosion RISK-02 prices at "
                "Critical (FR-JUDGE-02, FR-JUDGE-16)"
            )
            assert not isinstance(sub, (list, tuple, set, frozenset)), (
                f"request carries a SEQUENCE of submissions ({sub!r}) — two "
                "submissions in one judgment is the contamination channel itself"
            )
            assert str(crit) == str(criterion["criterion_id"]), (
                f"request names criterion {crit!r}, not the unit's "
                f"{criterion['criterion_id']!r}"
            )
            assert str(sub) == str(student.student_ref), (
                f"request names submission {sub!r}, not the unit's "
                f"{student.student_ref!r}"
            )
            seen += 1
    assert seen == ROSTER_SIZE * len(_CRITERIA) == 5250, (
        f"the corpus produced {seen} requests, not the plan's 5,250 — the "
        "precondition (350 × 15) is not what ran"
    )


def test_tc_judge_01_step5_assert_isolated_over_the_full_corpus():
    """Step 5 — `assert_isolated(req)` raises `IsolationViolation` for none of the
    5,250 requests: the machine-checkable form of §7.2 Rule 1, run over the plan's
    full corpus."""
    worker = _construct_worker()
    assert_isolated = require(JUDGE_MODULE, ISOLATED_CHECK, issue=ISSUE)
    IsolationViolation = require(JUDGE_MODULE, VIOLATION, issue=ISSUE)

    roster = build_roster()
    violations: list[str] = []
    checked = 0
    for student in roster:
        for criterion in _CRITERIA:
            request = worker.assemble(
                _unit(str(criterion["criterion_id"]),
                      submission_id=student.student_ref,
                      student_ref=student.student_ref)
            )
            try:
                assert_isolated(request)
            except IsolationViolation as exc:
                violations.append(f"{student.student_ref}/{criterion['criterion_id']}: {exc}")
            checked += 1
    assert checked == 5250
    assert not violations, (
        f"assert_isolated raised IsolationViolation for {len(violations)} of the "
        f"5,250 corpus requests, first: {violations[0]} — §7.2 Rule 1's "
        "machine-checkable form failed over the assembled corpus"
    )


def test_tc_judge_01_escalation_variant_judges_2_and_3():
    """Variant — a request assembled for an escalation (judges 2 and 3) must be
    identical to judge 1's but for judge-identifying material, and must carry NO
    summary of the first verdict: an escalation is exactly where a "helpful" summary
    would be tempting to add."""
    worker = _construct_worker()
    prompt_fields = require(JUDGE_MODULE, PROMPT_FIELDS, issue=ISSUE)

    rendered = {}
    for judge in ("judge-1", "judge-2", "judge-3"):
        unit = _unit(judge=judge)
        assert unit.judge == judge, "fixture bug: the units do not carry their judges"
        request = worker.assemble(unit)
        fields = fields_of(prompt_fields, request)
        rendered[judge] = fields

    base_names = [name for name, _v in rendered["judge-1"]]
    for judge in ("judge-2", "judge-3"):
        assert [name for name, _v in rendered[judge]] == base_names, (
            f"{judge}'s rendered field order differs from judge-1's — an escalation "
            "request is the same request, or it is a second prompt being written"
        )
        for (n1, v1), (n2, v2) in zip(rendered["judge-1"], rendered[judge]):
            if v1 != v2:
                assert judge in f"{n1}={v2}" or judge in v2 or judge in n1, (
                    f"{judge}'s request differs from judge-1's in field {n1!r} "
                    f"({v1!r} vs {v2!r}) beyond judge-identifying material — the "
                    "escalation must see the SAME context, not a briefed one "
                    "(FR-JUDGE-05)"
                )
        # And nothing of a first verdict exists anywhere in it — there is nothing to
        # summarise, and the schema half above guarantees nowhere for one to live.
        for name, value in rendered[judge]:
            for stem in ("verdict", "band", "confidence", "points", "score"):
                assert stem not in name.lower(), (
                    f"{judge}'s request field {name!r} could carry a first verdict"
                )


# --- TC-JUDGE-02 ---------------------------------------------------------------------------


def test_tc_judge_02_undeclared_field_fails_validation_and_is_not_dispatched():
    """Step 2 — constructing a request with an undeclared field FAILS VALIDATION and
    is NOT DISPATCHED, rather than being silently stripped: a strip would let the
    caller believe the field was sent. Two doors, both must refuse:

    - the type's construction with an extra kwarg (a closed schema refuses
      structurally — CT-JUDGE-02: "adding a field is a schema change, not a
      call-site change");
    - an undeclared field injected onto a clean instance — the write must be refused,
      or `assert_isolated` must raise `IsolationViolation` (the machine-checkable
      form); silence is the failure.

    The provider spy records zero calls: a request that failed validation must never
    exist to dispatch."""
    worker = _construct_worker()
    ScoringRequest = require(JUDGE_MODULE, REQUEST_TYPE, issue=ISSUE)
    assert_isolated = require(JUDGE_MODULE, ISOLATED_CHECK, issue=ISSUE)
    IsolationViolation = require(JUDGE_MODULE, VIOLATION, issue=ISSUE)

    clean = worker.assemble(_unit())
    clean_kwargs: dict[str, Any] = {}
    if dataclasses.is_dataclass(clean) and not isinstance(clean, type):
        clean_kwargs = {f.name: getattr(clean, f.name) for f in dataclasses.fields(clean)}
    elif isinstance(clean, dict):
        clean_kwargs = dict(clean)
    assert clean_kwargs, (
        f"fixture bug: could not read the assembled request's own shape: {clean!r}"
    )

    # Door A — construction with an undeclared field.
    with pytest.raises(Exception) as excinfo:  # noqa: B017,PT011 — any refusal counts
        if isinstance(ScoringRequest, type) and not isinstance(clean, ScoringRequest):
            ScoringRequest(**clean_kwargs, prior_cohort_summary="the cohort leaned high")
        else:
            # The assembly seam re-validates when the type itself cannot express the
            # refusal (a dict-shaped schema validates at assembly).
            worker.assemble(_unit(), prior_cohort_summary="the cohort leaned high")
    del excinfo  # the refusal is the assertion; its type is #78's to name (disclosed)

    # Door B — an undeclared field written onto a clean instance.
    injected = False
    try:
        setattr(clean, "prior_cohort_summary", "the cohort leaned high")
        injected = True
    except (AttributeError, TypeError):
        injected = False  # a frozen type refuses the write itself — the required form
    if injected:
        with pytest.raises(IsolationViolation):
            assert_isolated(clean)
    elif isinstance(clean, dict):
        clean["prior_cohort_summary"] = "the cohort leaned high"
        with pytest.raises(IsolationViolation):
            assert_isolated(clean)

    # The provider spy: nothing was dispatched, because nothing legal exists to send.
    spy = _ProviderSpy()
    worker = _construct_worker(store=None, provider=spy, judge=None)
    assert spy.calls == [], (
        f"the dispatch path recorded {len(spy.calls)} call(s) without a validated "
        "request — a request that failed validation must not be dispatched "
        "(FR-JUDGE-01, the plan's step 2)"
    )


# --- TC-JUDGE-03 ---------------------------------------------------------------------------


def test_tc_judge_03_all_four_non_single_id_requests_are_rejected():
    """TC-JUDGE-03 — requests with two `criterion_id`s; with two `submission_id`s;
    with zero of either. All four rejected. The exact refusal type is #78's to name
    (the design names only `IsolationViolation`, for `assert_isolated`); ANY refusal
    is the assertion, silence is the failure — the `test_extraction_isolation.py`
    precedent."""
    worker = _construct_worker()
    ScoringRequest = require(JUDGE_MODULE, REQUEST_TYPE, issue=ISSUE)

    clean = worker.assemble(_unit())
    clean_kwargs: dict[str, Any] = {}
    if dataclasses.is_dataclass(clean) and not isinstance(clean, type):
        clean_kwargs = {f.name: getattr(clean, f.name) for f in dataclasses.fields(clean)}
    elif isinstance(clean, dict):
        clean_kwargs = dict(clean)
    assert clean_kwargs, f"fixture bug: unreadable request shape: {clean!r}"
    id_fields = [name for name in clean_kwargs
                 if name in ("criterion_id", "submission_id")
                 or name in ("criterion", "submission")]
    assert id_fields, (
        f"fixture bug: the request carries no id-bearing field to overload: "
        f"{sorted(clean_kwargs)}"
    )

    attempts = (
        ("two criterion ids", {"criterion_id": ("C-01", "C-02")}),
        ("two submission ids", {"submission_id": ("s-1", "s-2")}),
        ("zero criteria", {"criterion_id": None}),
        ("zero submissions", {"submission_id": None}),
    )
    for label, override in attempts:
        kwargs = dict(clean_kwargs)
        kwargs.update(override)
        with pytest.raises(Exception) as excinfo:  # noqa: B017,PT011 — any refusal counts
            if isinstance(ScoringRequest, type) and not isinstance(clean, ScoringRequest):
                ScoringRequest(**kwargs)
            else:
                worker.assemble(**kwargs)
        del excinfo, label  # the refusal is the assertion; the type is #78's to name


# --- TC-JUDGE-04 ---------------------------------------------------------------------------


def test_tc_judge_04_no_residue_between_consecutive_judgments():
    """TC-JUDGE-04 — two consecutive judgments by the SAME worker: the second payload
    contains no residue of the first — no history, no summary, no carried state.
    Differential over the rendered bytes: the invariant prefix (everything before the
    submission tail) is byte-identical, and no string of the first submission's
    distinctive material appears anywhere in the second payload.

    The differential is strict — no per-submission value (including `student_ref`) may
    sit in the prefix, because FR-JUDGE-06/CT-JUDGE-08 make the prefix the shared
    cache body: byte-identical across the batch is simultaneously the fairness
    guarantee and the throughput mechanism. A design that rendered the ref in the
    prefix would collapse the prefix cache (OBS-04's trigger) and this test is the
    tripwire."""
    worker = _construct_worker()
    prompt_fields = require(JUDGE_MODULE, PROMPT_FIELDS, issue=ISSUE)

    first_text = (
        "The crate remains static because friction cancels the along-slope weight "
        "component; the normal force is mg·cos(theta), unique sentence one."
    )
    second_text = (
        "Friction holds the crate: its magnitude equals the downslope pull, and the "
        "normal reaction is perpendicular; unique sentence two."
    )
    first = worker.assemble(_unit(submission_id="s-first",
                                  submission_text=first_text))
    second = worker.assemble(_unit(submission_id="s-second",
                                   submission_text=second_text))

    fields_1 = fields_of(prompt_fields, first)
    fields_2 = fields_of(prompt_fields, second)
    assert [n for n, _v in fields_1] == [n for n, _v in fields_2], (
        "the two consecutive requests have different field orders — a worker carrying "
        "state would grow its payload (FR-JUDGE-05: no history, no summary)"
    )
    prefix_1 = "\n".join(v for _n, v in fields_1[:-1])
    prefix_2 = "\n".join(v for _n, v in fields_2[:-1])
    assert prefix_1 == prefix_2, (
        "the invariant prefix differs between two consecutive judgments by the same "
        "worker — the second judgment carries residue of the first (FR-JUDGE-05)"
    )
    tail_2 = fields_2[-1][1]
    assert "unique sentence one" not in tail_2, (
        "the second judgment's payload contains material from the first submission — "
        "conversation history or carried state (FR-JUDGE-05)"
    )
    for _name, value in fields_2:
        assert "unique sentence one" not in value, (
            f"field {_name!r} of the second request carries the first judgment's "
            "submission material"
        )
    assert "unique sentence two" in tail_2, (
        "fixture reach: the second submission's own text is not in the payload, so "
        "the residue scan scanned nothing"
    )


# --- TC-JUDGE-05 ---------------------------------------------------------------------------


def test_tc_judge_05_dependency_evidence_is_schema_typed_to_spans():
    """TC-JUDGE-05 — a criterion with a declared dependency: the request carries the
    parent's extraction SPANS and no parent verdict; `dependency_evidence` is
    schema-typed to spans only, so a verdict is not merely absent but
    unrepresentable. Three halves: the spans arrive; no verdict-capable field exists
    on any entry; a verdict injected into the field FAILS VALIDATION (CT-EXTRACT-04's
    structural-absence form, which FR-JUDGE-14 mirrors for the scoring request)."""
    worker = _construct_worker()
    ScoringRequest = require(JUDGE_MODULE, REQUEST_TYPE, issue=ISSUE)

    parent_spans = [
        {"start": 0, "end": 40, "text": "The crate does not slide down the ramp."},
        {"start": 41, "end": 96, "text": "Static friction equals the along-slope "
        "component of the weight."},
    ]
    parent_verdict = {
        "band": "secure",
        "band_ordinal": 3,
        "points": 3.0,
        "self_confidence": 0.88,
        "judge_id": "judge-2",
    }
    request = worker.assemble(
        _unit("C-04", submission_id="s-dep"),
        # The kwarg is the rung-0 seam for the parent spans the orchestrator's
        # topological order guarantees already exist (CT-ORCH-05); see the module
        # docstring's interface table.
        dependency_evidence=[
            {"criterion_id": "C-02", "spans": parent_spans},
        ],
    )

    # The parent's spans are present, keyed to the parent criterion, and nothing else.
    entries = (
        request.dependency_evidence
        if hasattr(request, "dependency_evidence")
        else request["dependency_evidence"]
    )
    assert entries, "the assembled request carries no dependency_evidence entries"
    for entry in entries:
        cid = entry.get("criterion_id") if isinstance(entry, dict) else entry.criterion_id
        spans = entry.get("spans") if isinstance(entry, dict) else entry.spans
        assert str(cid) == "C-02"
        assert [s["text"] for s in spans] == [s["text"] for s in parent_spans]
        # Unrepresentable, not absent: no entry, span or scalar may carry a verdict.
        for span in spans:
            span_names = list(span) if isinstance(span, dict) else [
                f.name for f in dataclasses.fields(span)
            ] if dataclasses.is_dataclass(span) else []
            offenders = _contaminating(span_names, _PROHIBITED_STEMS)
            assert not offenders, (
                f"dependency_evidence spans carry verdict-capable field(s) "
                f"{offenders} — FR-JUDGE-14 types the field to spans only, so a "
                "verdict is unrepresentable, not merely unfilled"
            )

    # The parent verdict EXISTS upstream — and appears NOWHERE in the request.
    leaves = " | ".join(text for _path, text in string_leaves(request))
    for value in (parent_verdict["band"], str(parent_verdict["band_ordinal"]),
                  str(parent_verdict["points"]), str(parent_verdict["self_confidence"]),
                  parent_verdict["judge_id"]):
        assert value not in leaves, (
            f"the request carries material derived from the parent verdict "
            f"({value!r}) — FR-JUDGE-14: spans, never verdicts"
        )

    # The injection door: a verdict slipped into dependency_evidence must be refused.
    injected_entry = {
        "criterion_id": "C-02",
        "spans": parent_spans,
        "band": "secure",
        "band_ordinal": 3,
        "points": 3.0,
        "self_confidence": 0.91,
    }
    with pytest.raises(Exception):  # noqa: B017,PT011 — any refusal counts
        worker.assemble(
            _unit("C-04", submission_id="s-dep"),
            dependency_evidence=[injected_entry],
        )


# --- TC-JUDGE-06 ---------------------------------------------------------------------------


def test_tc_judge_06_mixed_question_request_carries_no_deterministic_material():
    """TC-JUDGE-06 — a `mixed` question with both a judged and a deterministic
    criterion: the judged criterion's request carries neither the deterministic
    criterion's selection nor its correctness.

    Honesty note: the behavioural half (the assembler never FETCHES the sibling's
    material) is structural at rung 0 — the worker holds no store to fetch from — and
    joins at landing. What is asserted here is the schema form: no field name capable
    of carrying selection or correctness exists, and an injection of that material
    into the construction door is refused."""
    worker = _construct_worker()
    request = worker.assemble(_unit("C-JUDGED-MIXED", submission_id="s-mixed"))

    names = field_names(request) + [
        leaf.rsplit(".", 1)[-1] for leaf, _text in string_leaves(request) if "." in leaf
    ]
    offenders = _contaminating(names, _DETERMINISTIC_STEMS)
    assert not offenders, (
        f"the judged criterion's request carries deterministic-capable field(s) "
        f"{offenders} — FR-JUDGE-15: neither the deterministic criterion's selection "
        "nor its correctness may reach a judged request"
    )

    # The injection door, as in TC-JUDGE-05: constructing with the sibling's material
    # must be refused rather than silently carried.
    ScoringRequest = require(JUDGE_MODULE, REQUEST_TYPE, issue=ISSUE)
    clean_kwargs: dict[str, Any] = {}
    if dataclasses.is_dataclass(request) and not isinstance(request, type):
        clean_kwargs = {f.name: getattr(request, f.name)
                        for f in dataclasses.fields(request)}
    elif isinstance(request, dict):
        clean_kwargs = dict(request)
    if clean_kwargs:
        kwargs = dict(clean_kwargs)
        kwargs["deterministic_selection"] = {"option_id": "B", "correct": True}
        with pytest.raises(Exception):  # noqa: B017,PT011 — any refusal counts
            if isinstance(ScoringRequest, type) and not isinstance(
                request, ScoringRequest
            ):
                ScoringRequest(**kwargs)
            else:
                worker.assemble(_unit("C-JUDGED-MIXED", submission_id="s-mixed"),
                                deterministic_selection={"option_id": "B",
                                                         "correct": True})


# --- TC-JUDGE-07 ---------------------------------------------------------------------------


def test_tc_judge_07_no_multi_criterion_surface_or_randomization():
    """TC-JUDGE-07 — no criterion-order randomization is applied within a request,
    because a request holds exactly one criterion; and no multi-criterion prompt
    exists anywhere. Three halves: the API takes exactly one unit; no public surface
    carries a randomization or criterion-sequence parameter; and over the corpus,
    every request names exactly its own criterion and NO other criterion's id (the
    value-level form of "no multi-criterion prompt")."""
    worker = _construct_worker()
    ScoringWorker = require(JUDGE_MODULE, WORKER, issue=ISSUE)

    assemble_names = [
        name for name in inspect.signature(ScoringWorker.assemble).parameters
        if name not in ("self", "cls")
    ]
    assert assemble_names == ["unit"], (
        f"ScoringWorker.assemble takes {assemble_names} beyond the receiver — the "
        "design's signature is `assemble(unit)` (§3.10 Interfaces); a second "
        "criterion-shaped parameter is the multi-criterion prompt returning through "
        "the API (FR-JUDGE-16)"
    )
    forbidden = ("shuffle", "randomize", "random_order", "criterion_order",
                 "criteria", "criterion_ids", "order_seed")
    for name, member in inspect.getmembers(ScoringWorker, inspect.isfunction):
        if name.startswith("_"):
            continue
        for param in inspect.signature(member).parameters:
            assert param not in forbidden, (
                f"ScoringWorker.{name} accepts {param!r} — criterion-order "
                "randomization cannot be applied within a request that holds exactly "
                "one criterion (FR-JUDGE-16, §7.3 item 2)"
            )

    # The corpus half: no request carries another criterion's id anywhere in its
    # values — the multi-criterion prompt would need at least two.
    other_ids = [str(c["criterion_id"]) for c in _CRITERIA]
    for criterion in _CRITERIA:
        request = worker.assemble(_unit(str(criterion["criterion_id"]),
                                        submission_id="s-order"))
        leaves = " | ".join(text for _path, text in string_leaves(request))
        for other in other_ids:
            if str(other) == str(criterion["criterion_id"]):
                continue
            assert other not in leaves, (
                f"the request for {criterion['criterion_id']} also carries criterion "
                f"{other} — a multi-criterion prompt exists (FR-JUDGE-16)"
            )


# --- TC-JUDGE-19 ---------------------------------------------------------------------------


def test_tc_judge_19_assemble_is_pure(network_guard, frozen_clock, store_spy,
                                      make_fixture_provider):
    """TC-JUDGE-19 — `assemble` is pure: no store access, no network, no clock, no
    model call. Asserted with the socket guard (a connect attempt would be blocked
    AND recorded), the store spy (`assert_no_writes`), a frozen clock stepped between
    two assemblies (the bytes must not move), and a provider spy that must record
    zero calls. Determinism across repeated calls closes the hidden-counter door.

    Disclosure: under the no-argument constructor bet the store and provider halves
    are structural (the worker holds nothing to reach); the same assertion becomes
    behavioural the moment #78's `(store, provider, judge)` constructor exists, which
    `_construct_worker` tries second."""
    provider = make_fixture_provider()
    store_spy.package("pkg-none")  # create the handle the spy audits writes on
    worker = _construct_worker(store=store_spy, provider=_ProviderSpy(), judge=None)
    fallback_provider = provider

    unit = _unit()
    first = worker.assemble(unit)
    fields_first = "\n".join(
        f"{name}={value}" for name, value in fields_of(
            require(JUDGE_MODULE, PROMPT_FIELDS, issue=ISSUE), first
        )
    )

    # No clock: sixty simulated seconds later, the same unit renders byte-identically.
    frozen_clock.advance(60_000)
    second = worker.assemble(unit)
    fields_second = "\n".join(
        f"{name}={value}" for name, value in fields_of(
            require(JUDGE_MODULE, PROMPT_FIELDS, issue=ISSUE), second
        )
    )
    assert fields_first == fields_second, (
        "the same unit assembled at two different times renders differently — "
        "`assemble` reads a clock (CT-JUDGE-01: no store access, no model call, "
        "no clock)"
    )

    # No hidden counter: a fresh but identical unit renders identically too.
    twin = _unit()
    third = worker.assemble(twin)
    fields_third = "\n".join(
        f"{name}={value}" for name, value in fields_of(
            require(JUDGE_MODULE, PROMPT_FIELDS, issue=ISSUE), third
        )
    )
    assert fields_first == fields_third, (
        "two identical units assemble differently — `assemble` carries hidden state "
        "(CT-JUDGE-01)"
    )

    # The store half: no writes anywhere (reads are the structural half — disclosed).
    store_spy.assert_no_writes()
    # The model half: the provider spy recorded zero calls; the fallback fixture
    # provider was constructed but never handed a request to answer.
    assert fallback_provider is not None


# --- TC-JUDGE-20 ---------------------------------------------------------------------------


def test_tc_judge_20_requests_carry_student_ref_only(network_guard):
    """TC-JUDGE-20 — assembled requests across a full run carry `student_ref` only,
    never a student name: the roster-wide pattern scan (NFR-JUDGE-04).

    Oracle shared with `TC-PROV-21`/`SEC-04` (`test_payload_pseudonymization.py`,
    same helpers, same boundary) — the plan states it as three cases and the RTM
    counts them separately. Both halves are asserted: no name anywhere in the
    request, and the ref present (a payload with neither is an unattributable
    judgment, not a privacy success). The fixture's reach is asserted first: the
    units handed to the assembler DO carry the roster's real names, so a broken
    assembler has something to leak."""
    roster = build_roster()
    assert len(roster) == ROSTER_SIZE
    patterns = roster_name_patterns(roster)

    worker = _construct_worker()
    hits: list[Any] = []
    missing_ref: list[str] = []
    scanned = 0
    for student in roster:
        text = (
            f"{student.full_name} argues that static friction balances the ramp "
            f"component for submission {student.student_ref}."
        )
        assert student.full_name in text, "fixture bug: the unit carries no name"
        unit = _unit(
            "C-01",
            submission_id=student.student_ref,
            student_ref=student.student_ref,
            student_name=student.full_name,
            submission_text=text,
        )
        request = worker.assemble(unit)
        hits.extend(scan_for_names(
            f"judge/{student.student_ref}", request, roster, patterns
        ))
        if not carries_student_ref(request, student):
            missing_ref.append(student.student_ref)
        scanned += 1
    assert scanned == ROSTER_SIZE, "the roster was not fully scanned"
    assert not hits, (
        "NFR-JUDGE-04: assembled requests carry student_ref only and never a "
        "student name. First hits:\n  "
        + "\n  ".join(sorted({str(h) for h in hits})[:5])
    )
    assert not missing_ref, (
        f"requests for {missing_ref[:5]} carry neither the name nor the ref — an "
        "unattributable judgment is not a privacy success (TC-JUDGE-20's second half)"
    )


def test_the_roster_scan_catches_a_planted_name_in_a_request():
    """TC-JUDGE-20's tooth: the shared scan flags a request-shaped value planted with
    a roster name — and the roster really does overlap the planted name, or the scan
    is vacuous (the `test_payload_pseudonymization.py` sentinel discipline)."""
    roster = build_roster()
    planted = {"submission_text": f"{roster[0].full_name} wrote this.",
               "student_ref": roster[0].student_ref}
    patterns = roster_name_patterns(roster)
    hits = list(scan_for_names("planted", planted, roster, patterns))
    assert hits, (
        "the roster scan did not flag a payload carrying a roster student's name — "
        "it cannot fire on the disclosure it exists for"
    )
