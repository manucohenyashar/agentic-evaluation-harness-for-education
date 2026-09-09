"""`CT-DET-10` — nothing here is retryable (`TC-DET-C10`), the error clause.

Case of test plan §6.11.11; issue #90 (TS-68). Green by design — `M-DET`
shipped via #246/#249.

The clause: nothing here is retryable, because nothing here can fail
transiently; an unresolvable selection is a *result* (`CT-DET-03`), not an
error; a missing answer key cannot reach this module — `FR-SETUP-03` makes it
a publication-time failure.

The clause discriminator: the plan flags the shape as unusual — the case
asserts the ABSENCE of a retry surface, a structural claim, not retry
behaviour. Asserted structurally: the module's public namespace carries no
retry/backoff/transient vocabulary; its error taxonomy has no transient or
retryable class (every `DeterministicError` subclass is a refusal); and no
function returns retry bookkeeping. Then the two behavioural claims that make
the structure true: every unreadable read returns a state (never raises), and
the keyless situation — hand-forced past publication through a direct write,
DISCLOSED below — is refused loudly and writes nothing, so even the situation
the module names impossible cannot produce a score.

**Disclosed construction**: the keyless criterion is created by a direct
column write, because a package that ships through setup's publication gates
cannot carry one (`CT-SETUP-07`: every deterministic criterion has a key
before publication — no default, no skip). The end-to-end publication flow is
the setup suite's case; here the impossible situation is forced by hand to
prove the module's guard holds even against it.
"""

from __future__ import annotations

import pytest

import aeh.det as det_module
from aeh.det import (
    DeterministicError,
    DeterministicEvaluator,
    MalformedAnswerKey,
    evaluate,
)
from tests.support.det_vocabulary import (
    open_det_store,
    seed_det_world,
    seed_selection_answers,
)

pytestmark = pytest.mark.contract

from tests.contract.det._doubles import ISSUE  # noqa: F401 — register citation

#: The vocabulary a retry surface would be spelled with. Any public name
#: carrying one of these stems is a retry path the clause forbids.
RETRY_STEMS = ("retry", "retries", "backoff", "transient", "retryable",
               "attempt", "requeue", "requeu")


def test_tc_det_c10_no_retry_surface_exists():
    """`TC-DET-C10` (the structural half) — the module exposes NO retry
    surface: no public function, class, constant or error name carries retry
    vocabulary; the error taxonomy (`DeterministicError` and its subclasses)
    contains no transient or retryable class; and the module's knobs name
    thresholds, not attempt counts. The absence is the claim — asserted over
    the whole namespace, so a helper added tomorrow fails here."""
    public = {name for name in dir(det_module) if not name.startswith("_")}
    offenders = {
        name for name in public
        if any(stem in name.lower() for stem in RETRY_STEMS)
    }
    assert not offenders, (
        f"TC-DET-C10: retry-vocabulary names in aeh.det's public surface: "
        f"{sorted(offenders)} — the module grew a retry surface."
    )

    taxonomy = {
        name for name in public
        if isinstance(getattr(det_module, name), type)
        and issubclass(getattr(det_module, name), DeterministicError)
    }
    assert {"DeterministicError"} | taxonomy <= public
    transient = {
        name for name in taxonomy
        if any(stem in name.lower() for stem in RETRY_STEMS)
    }
    assert not transient, (
        f"TC-DET-C10: the error taxonomy carries transient/retryable "
        f"classes: {sorted(transient)} — a refusal taxonomy is not a retry "
        "taxonomy."
    )
    # The one knob the module declares gates a THRESHOLD, not an attempt
    # count — nothing here counts tries.
    assert det_module.UNRESOLVED_ALERT_RATE_ENV == \
        "HARNESS_DET_UNRESOLVED_ALERT_RATE"


def test_tc_det_c10_an_unresolvable_selection_is_a_result_not_an_error(
        tmp_data_dir):
    """`TC-DET-C10` (the first behavioural half) — every unreadable read the
    kernel can be handed RETURNS a state: ambiguous, multiple marks, absent
    region, missing selection — none raises. Through the store path the same
    holds: `evaluate` writes the unresolved row and returns the score with
    `state = 'unresolved_selection'`, `routing = 'triage'`, and NULL points.
    An unresolvable selection is a result."""
    for content_state, selection_state, selection in (
        ("present", "ambiguous", None),
        ("present", "multiple_marks", None),
        ("absent", None, None),
        ("present", "resolved", None),
    ):
        outcome = evaluate(
            content_state=content_state,
            selection_state=selection_state,
            selection=selection,
            key=("B",),
        )
        assert outcome.state == "unresolved_selection" and \
            outcome.routing == "triage", (
                f"TC-DET-C10: ({content_state}, {selection_state}) produced "
                f"{outcome.state!r} — an unreadable read must return a "
                "state, not an error."
            )

    store = open_det_store(tmp_data_dir)
    try:
        run_id, _version, cohort_id = seed_det_world(
            store,
            submissions=("S-ambig",),
            criteria=[{"criterion_id": "M1", "question_id": "Q1",
                       "key": ("B",)}],
        )
        seed_selection_answers(
            store, cohort_id,
            [{"submission_id": "S-ambig", "content_state": "present",
              "selection_state": "ambiguous"}],
        )
        score = DeterministicEvaluator(store).evaluate(
            run_id, "S-ambig", "M1"
        )
        assert score.state == "unresolved_selection"
        assert score.routing == "triage"
        assert score.points is None
    finally:
        store.close()


def test_tc_det_c10_a_missing_key_cannot_reach_this_module(tmp_data_dir):
    """`TC-DET-C10` (the second behavioural half) — the keyless situation:
    the kernel refuses an empty key with the refusal that NAMES the
    publication-time rule (`FR-SETUP-03`); a criterion hand-forced past
    publication (direct write, disclosed) makes the cohort pass raise
    `MalformedAnswerKey` BEFORE any write lands — no score row, no stats, no
    audit record exists for the forced criterion; and a published-shaped
    package (every criterion keyed, as the gates require) evaluates clean.
    The module guards the impossible loudly instead of scoring it."""
    # Kernel: the refusal names the rule that makes it unreachable.
    with pytest.raises(MalformedAnswerKey) as excinfo:
        evaluate(content_state="present", selection_state="resolved",
                 selection=("B",), key=())
    assert "FR-SETUP-03" in str(excinfo.value), (
        "TC-DET-C10: the empty-key refusal does not name FR-SETUP-03 — the "
        "guard's reason for existing is the publication-time rule."
    )

    store = open_det_store(tmp_data_dir)
    try:
        run_id, version, cohort_id = seed_det_world(
            store,
            submissions=("S1", "S2"),
            criteria=[
                {"criterion_id": "M-keyed", "question_id": "Q1",
                 "key": ("B",)},
                {"criterion_id": "M-keyless", "question_id": "Q2",
                 "key": ("B",)},  # the key is stripped below, by hand
            ],
        )
        seed_selection_answers(
            store, cohort_id,
            [{"submission_id": "S1", "selection": "B"},
             {"submission_id": "S2", "selection": "C"}],
        )
        from tests.support.det_vocabulary import seed_answer_region

        for s in ("S1", "S2"):
            seed_answer_region(store, cohort_id, f"doc-{s}", "Q2",
                               selection="B")
        # DISCLOSED hand-force: strip the key the publication gates would
        # have required.
        package_handle = store.package("pkg-det")
        with package_handle.transaction() as tx:
            tx.execute(
                "UPDATE criterion SET answer_key = NULL WHERE "
                "package_version_id = :v AND criterion_id = 'M-keyless'",
                v=version,
            )

        audits_before = store.durable().query(
            "SELECT COUNT(*) AS n FROM audit_record")[0]["n"]

        with pytest.raises(MalformedAnswerKey):
            DeterministicEvaluator(store).evaluate_cohort(run_id)

        # The refusal landed BEFORE any write: nothing for the keyless
        # criterion, nothing at all — the pass is a refusal, not a partial.
        # (The audit table's baseline row is M-ORCH's run-level record from
        # create_run; the delta must be zero.)
        counts = store.cohort(cohort_id).query(
            "SELECT criterion_id, COUNT(*) AS n FROM criterion_score GROUP "
            "BY criterion_id"
        )
        assert list(counts) == [], (
            f"TC-DET-C10: score rows exist after the refusal: "
            f"{[dict(r) for r in counts]} — the module scored before "
            "refusing."
        )
        assert store.durable().query(
            "SELECT COUNT(*) AS n FROM audit_record")[0]["n"] == audits_before
        assert store.durable().query(
            "SELECT COUNT(*) AS n FROM audit_record WHERE criterion_id = "
            "'M-keyless'")[0]["n"] == 0

        # And the published-shaped half of the same package evaluates clean:
        # with the key restored (the hand-force undone), the whole package
        # evaluates — the impossible situation was the key's absence, and
        # nothing else.
        with package_handle.transaction() as tx:
            tx.execute(
                "UPDATE criterion SET answer_key = '[\"B\"]' WHERE "
                "package_version_id = :v AND criterion_id = 'M-keyless'",
                v=version,
            )
        report = DeterministicEvaluator(store).evaluate_cohort(run_id)
        assert report.criteria == 2 and report.evaluations == 4
    finally:
        store.close()
