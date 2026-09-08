"""`M-SETUP` Stage A, rung 2: the proposal, the two gates, and the locks (issue #54).

The shipped half of `TC-SETUP-01/02/04/19/20` (test plan §5.6) against the implementation
that landed with #50 (`aeh.setup`): a real store, a real ingest chain, and every model call
scripted (`tests/support/setup_harness.py`) — the transports are the only doubles, because
"the tiers are real" is what this rung is for.

The remaining §5.6 cases wait on #51/#52/#53 (`read_back_rubric`, `classify_decomposability`,
`propose_dependencies`, `set_grade_policy`); they live in the written-ahead files beside
this one and are registered in `tests/support/impl.py`. `TC-SETUP-11/14/16/17/18` are
deferred outright; the PR carries the per-case disclosure.

Every exception text below was probed against the shipped code first and is quoted in
`match=`: a wording change should be a visible failure, not a silent drift. The steps
named S1–S4 are detailed-design §4.2.1's: S1 propose, S2 confirm, S3 answer keys, S4
publish — the exact numbering the shipped error messages use.
"""

from __future__ import annotations

import pytest

from aeh.pkg import PackageCatalog, PublishedVersionImmutableError, SchemaLockViolation
from aeh.setup import SetupError, SetupOrderError

from tests.support.setup_harness import (
    ScriptedSetupProvider,
    ingest_document,
    make_setup_service,
    stage_chain,
)

pytestmark = pytest.mark.integration


def _confirm(chain, doc_id: str):
    """S1→S3: propose, confirm, and key the one deterministic criterion the package has."""
    proposal = chain.service.propose_inventory(doc_id)
    version = chain.catalog.draft_version()
    chain.service.confirm_inventory(proposal.proposal_id)
    chain.catalog.add_criterion(version, "CRIT-Q4", question_id="Q4", kind="mcq",
                                scoring_model="atomic", max_points=2.0)
    return proposal, version


# --- TC-SETUP-01 ---------------------------------------------------------------------------


def test_tc_setup_01_one_proposal_per_package_with_option_sets_and_no_call_during_ingest(
    tmp_data_dir,
):
    """`TC-SETUP-01` (FR-SETUP-01, P0) — an assessment of three open, two MCQ and one mixed
    question yields *one* `question_type` proposal per question, with option sets only where
    a type has choices — and the proposal is produced exactly once per package, spied on the
    setup transport: re-proposing returns the stored proposal without a second call, and
    ingesting a submission makes no proposal call at all."""
    chain = stage_chain(tmp_data_dir)
    doc_id = ingest_document(chain.store, chain.ingestor)

    proposal = chain.service.propose_inventory(doc_id)

    by_id = {q.question_id: q for q in proposal.questions}
    assert list(by_id) == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
    assert [by_id[q].question_type for q in by_id] == (
        ["open", "open", "open", "mcq", "mcq", "mixed"]
    )
    # Option sets travel with the types that have choices — open questions carry none.
    assert by_id["Q1"].options == () and by_id["Q2"].options == () and by_id["Q3"].options == ()
    assert [o.option_id for o in by_id["Q4"].options] == ["A", "B", "C", "D"]
    assert [o.option_id for o in by_id["Q5"].options] == ["A", "B", "C"]
    assert [o.option_id for o in by_id["Q6"].options] == ["A", "B"]
    # One model call produced all of this.
    assert len(chain.provider.calls) == 1

    # Exactly once per package: resume returns the stored proposal, making no new call...
    resumed = chain.service.propose_inventory(doc_id)
    assert resumed.proposal_id == proposal.proposal_id
    assert len(chain.provider.calls) == 1

    # ...and submission ingest — the pipeline's other model customer — triggers no proposal.
    ingest_document(chain.store, chain.ingestor, kind="submission", name="scan-01.md")
    assert len(chain.provider.calls) == 1


# --- TC-SETUP-02 ---------------------------------------------------------------------------


def test_tc_setup_02_publish_refused_before_confirmation_permitted_after_and_rows_lock_at_it(
    tmp_data_dir,
):
    """`TC-SETUP-02` (FR-SETUP-02, P0) — `publish()` is refused before the inventory is
    confirmed (blocking gate 1 of 2) and permitted after it; the question rows come under
    the schema lock *at confirmation*: they do not exist before it, they exist confirmed
    after it, and from that moment a `prompt_text` edit raises `SchemaLockViolation` while
    the reference solution stays writable."""
    chain = stage_chain(tmp_data_dir)
    doc_id = ingest_document(chain.store, chain.ingestor)

    assert chain.catalog.draft_version() is None  # nothing minted before setup starts
    proposal = chain.service.propose_inventory(doc_id)
    version = chain.catalog.draft_version()
    assert version is not None
    assert chain.catalog.questions(version) == ()  # no question rows before confirmation

    with pytest.raises(SetupOrderError, match=r"blocking gate 1 of 2"):
        chain.service.publish("teacher-1")
    assert not chain.catalog.is_locked(version)
    # S3 has no back door either: the keys come after the confirmed inventory.
    with pytest.raises(SetupOrderError, match=r"S3 blocks S4"):
        chain.service.set_answer_keys({"CRIT-Q4": ["A"]})

    chain.service.confirm_inventory(proposal.proposal_id)
    chain.catalog.add_criterion(version, "CRIT-Q4", question_id="Q4", kind="mcq",
                                scoring_model="atomic", max_points=2.0)
    rows = {row["question_id"]: row for row in chain.catalog.questions(version)}
    assert list(rows) == ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
    assert all(row["confirmed_at"] is not None for row in rows.values())
    with pytest.raises(
        SchemaLockViolation, match=r"question\.prompt_text edit on question 'Q1'"
    ):
        chain.catalog.update_question_field(version, "Q1", "prompt_text", "reworded")
    chain.catalog.update_question_field(version, "Q1", "reference_solution", "impulse = F dt")

    # Permitted after: the same publish that was refused above now goes through.
    chain.service.set_answer_keys({"CRIT-Q4": ["A"]})
    published = chain.service.publish("teacher-1")
    assert published == version
    assert chain.catalog.is_locked(published)


# --- TC-SETUP-04 ---------------------------------------------------------------------------


def test_tc_setup_04_deterministic_criterion_needs_its_key_no_default_no_skip_no_inference(
    tmp_data_dir,
):
    """`TC-SETUP-04` (FR-SETUP-03, P0) — a deterministic criterion without an answer key
    refuses publication, naming the criterion and gate 2 of 2; there is no default and no
    skip (an empty key mapping is refused and publication stays refused), and no inference
    path exists: setting the reference solution — the one field an inferring module would
    reach for — still leaves the key unset and the gate shut. The API assertion backs the
    behavioural one: `SetupService` carries no `infer*` member at all. (The fuller S4
    semantics — key validation against the stored option sets — is #53's story.)"""
    chain = stage_chain(tmp_data_dir)
    doc_id = ingest_document(chain.store, chain.ingestor)
    _, version = _confirm(chain, doc_id)

    with pytest.raises(
        SetupOrderError, match=r"CRIT-Q4.*blocking gate 2 of 2"
    ):
        chain.service.publish("teacher-1")

    # No default and no skip: the empty mapping is refused (a SetupError — an empty key
    # mapping is malformed in itself, `FR-PKG-17`'s non-empty-key rule) and nothing changes.
    with pytest.raises(SetupError, match="empty mapping"):
        chain.service.set_answer_keys({})
    with pytest.raises(
        SetupOrderError, match=r"CRIT-Q4.*blocking gate 2 of 2"
    ):
        chain.service.publish("teacher-1")

    # No inference path: the reference solution is set, and the gate stays shut.
    chain.catalog.update_question_field(version, "Q4", "reference_solution", "A")
    with pytest.raises(
        SetupOrderError, match=r"CRIT-Q4.*blocking gate 2 of 2"
    ):
        chain.service.publish("teacher-1")
    criteria = {row["criterion_id"]: row for row in chain.catalog.criteria(version)}
    assert not criteria["CRIT-Q4"]["answer_key"]  # nothing auto-keyed (unset reads ())
    assert not [name for name in dir(chain.service) if "infer" in name.lower()], (
        "TC-SETUP-04: an inference-shaped member appeared on SetupService — FR-SETUP-03 "
        "gives the key no default, no skip and no inference path"
    )

    # With the key supplied by the teacher, publication is permitted.
    chain.service.set_answer_keys({"CRIT-Q4": ["A"]})
    published = chain.service.publish("teacher-1")
    assert published == version


# --- TC-SETUP-19 ---------------------------------------------------------------------------


class _FailAfterPublishUpdate:
    """A store handle whose `transaction()` commits the publish UPDATE, then fails.

    The injection point is mid-statement: the publish statement has executed and raised
    before the transaction body exits, so "leaves nothing partially published" is observed
    against a store that has actually been asked to change state.
    """

    def __init__(self, real) -> None:
        self._real = real

    def transaction(self):
        real_tx = self._real.transaction()

        class _Tx:
            def __enter__(self_inner):
                return _FailingTx(real_tx.__enter__())

            def __exit__(self_inner, *args):
                return real_tx.__exit__(*args)

        return _Tx()

    def __getattr__(self, name):
        return getattr(self._real, name)


class _FailingTx:
    def __init__(self, real) -> None:
        self._real = real

    def execute(self, stmt, **kwargs):
        result = self._real.execute(stmt, **kwargs)
        if "locked" in str(stmt):
            raise RuntimeError("injected mid-publish failure")
        return result

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_tc_setup_19_publish_is_one_transaction_and_the_lock_engages_exactly_at_it(
    tmp_data_dir,
):
    """`TC-SETUP-19` (FR-SETUP-16, P0) — with both gates satisfied, `publish()` is one
    transaction: an injected failure after the publish statement has executed leaves
    nothing partially published (the version is unlocked, the confirmed inventory intact)
    and the same publish succeeds on retry. And the §6.2 published-immunity lock takes
    effect *exactly* at publication — a version edit one moment before the publish is
    accepted, and refused the moment it is published."""
    chain = stage_chain(tmp_data_dir)
    doc_id = ingest_document(chain.store, chain.ingestor)
    _, version = _confirm(chain, doc_id)
    chain.service.set_answer_keys({"CRIT-Q4": ["A"]})
    assert chain.service.steps().ready_to_publish

    # The lock is not engaged yet: a question edit one moment before publication is legal.
    chain.catalog.update_question_field(version, "Q4", "reference_solution", "A")

    real_handle = chain.store.package(chain.package_id)
    chain.catalog._handle = _FailAfterPublishUpdate(real_handle)
    try:
        with pytest.raises(RuntimeError, match="injected mid-publish failure"):
            chain.service.publish("teacher-1")
        # Nothing partially published: not locked, inventory and key still there.
        assert not chain.catalog.is_locked(version)
        rows = {row["question_id"] for row in chain.catalog.questions(version)}
        assert rows == {"Q1", "Q2", "Q3", "Q4", "Q5", "Q6"}
    finally:
        chain.catalog._handle = real_handle

    # The same publish, retried, goes through — and the lock engages exactly now.
    published = chain.service.publish("teacher-1")
    assert published == version
    assert chain.catalog.is_locked(published)
    with pytest.raises(PublishedVersionImmutableError):
        chain.catalog.update_question_field(version, "Q4", "reference_solution", "B")


# --- TC-SETUP-20 ---------------------------------------------------------------------------


def test_tc_setup_20_abandoned_after_s3_persists_unpublished_and_resumes_with_the_count(
    tmp_data_dir,
):
    """`TC-SETUP-20` (NFR-SETUP-04, P1) — setup abandoned after step 3 (S3, the answer
    keys: the last blocking step the shipped implementation carries) leaves the partially
    completed version persisting as unpublished and continuable; the remaining-step count
    tracks the truth across the abandonment: 1 while the inventory is unconfirmed, 0 once
    both blocking steps are done, and — after a *fresh* `SetupService` over the same tiers
    resumes the same version — the confirmed proposal, the done flags, and the publish."""
    chain = stage_chain(tmp_data_dir)
    doc_id = ingest_document(chain.store, chain.ingestor)

    proposal = chain.service.propose_inventory(doc_id)
    version = chain.catalog.draft_version()
    assert chain.service.steps().remaining_steps == 1  # unconfirmed inventory blocks
    chain.service.confirm_inventory(proposal.proposal_id)
    chain.catalog.add_criterion(version, "CRIT-Q4", question_id="Q4", kind="mcq",
                                scoring_model="atomic", max_points=2.0)
    chain.service.set_answer_keys({"CRIT-Q4": ["A"]})

    # Abandoned here: no publish. The version persists, unpublished, and is continuable.
    assert not chain.catalog.is_locked(version)
    progress = chain.service.steps()
    assert progress.remaining_steps == 0
    assert progress.ready_to_publish

    resumed_catalog = PackageCatalog(chain.store.package(chain.package_id),
                                     package_id=chain.package_id)
    resumed_provider = ScriptedSetupProvider()
    resumed = make_setup_service(resumed_catalog, chain.ingestor, resumed_provider)

    # Resuming sees exactly what was abandoned — and proposes nothing new.
    carried = resumed.current_proposal()
    assert carried.proposal_id == proposal.proposal_id
    assert carried.confirmed
    assert len(resumed_provider.calls) == 0

    progress = resumed.steps()
    assert [step.step_id for step in progress.steps if step.done] == [
        "inventory", "answer_keys",
    ]
    assert progress.remaining_steps == 0

    published = resumed.publish("teacher-1")
    assert published == version
    assert resumed_catalog.is_locked(published)
