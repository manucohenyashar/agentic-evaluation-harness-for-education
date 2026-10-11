"""CT-AUTHOR-06, CT-AUTHOR-07 and CT-AUTHOR-08 — fallback order, determinism, the validator gate (TS-165, #689).

| TC ID | Clause | Breaks if |
|---|---|---|
| TC-AUTHOR-C06 | CT-AUTHOR-06 behaviour | the fallback follows the injected chain in order — the first model whose reply passes the deterministic validator wins, and a head whose every call fails defers to the next position with its reason first in `failures` |
| TC-AUTHOR-C07 | CT-AUTHOR-07 behaviour | identical inputs and identical recordings produce byte-identical draft and report, and a run touches only its own two artifacts |
| TC-AUTHOR-C08 | CT-AUTHOR-08 behaviour | no proposal that fails the deterministic structural rules ever enters a draft, and `validate_draft` is a pure, model-independent, re-runnable function |

The fallback case needs no live flake and no extra recording (design §5.2, the compatibility
note's "a fixture set that does not reproduce the fallback path … does not honour this
contract"): `ABSENT_HEAD_BUILD` is a pinned build id the corpus records nothing for, so every
call for it raises `FixtureMissingError` — a `ProviderError`, exactly FR-AUTHOR-05a's
fallback trigger. Three runs pin the order without pinning any reason *text*:

- chain `[base]` — every winner is a chain member, seat 0 unless the corpus legitimately
  records an earlier rejection (a failing head or a same-model repair); any non-seat-0
  winner must say why the earlier position lost;
- chain `[absent]` — every item unresolved, and each failure reason is captured;
- chain `[absent, base]` — every item won by a base member, and `failures[0]` equals the
  reason the absent head produced alone in the `[absent]` run — same first-tried position,
  same reason, so the order is pinned without pinning any reason *text*.

Rung 1, guards first (#689 then #686). The reason *texts* are never matched verbatim beyond
that cross-run equality; the failure reasons are the module's own record and this file treats
their wording as free.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from tests.support.author_vocabulary import (
    ABSENT_HEAD_BUILD,
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    RECORDINGS,
    af,
    chain_from_config,
    make_service,
    sha256_of,
)
from tests.support.impl import require, require_attr, require_path

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]


def _guards(make_fixture_provider) -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names
    require_attr(author, "AuthoringInputError", issue=AUTHOR_ISSUE)
    corpus = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    af09 = require_path(af("AF-09"), "the AF-09 authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, corpus, af09, recordings


def _absent_ref():
    from aeh.conf import ModelRef

    return ModelRef(role="judge", provider="openrouter", build_id=ABSENT_HEAD_BUILD,
                    quantization=None)


def _draft(author, recordings, documents, out: Path, make_fixture_provider, chain):
    service = make_service(author, chain, make_fixture_provider(recordings))
    return service.draft(documents=sorted(documents), output_dir=out)


def _has_sentinel(value: object) -> bool:
    if isinstance(value, str):
        return "<<PLACEHOLDER" in value
    if isinstance(value, dict):
        return any(_has_sentinel(k) or _has_sentinel(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_has_sentinel(item) for item in value)
    return False


# --- TC-AUTHOR-C06 ----------------------------------------------------------------------------


def test_tc_author_c06_fallback_follows_the_chain_in_order_and_the_first_valid_reply_wins(
        tmp_path, make_fixture_provider):
    """Seat 0 wins when its replies pass; a head that cannot answer defers to the next
    position, its reason recorded first; the winner is never a model outside the chain."""
    author, corpus, _af09, recordings = _guards(make_fixture_provider)
    base = chain_from_config()
    assert base, "the dev-ci profile names no judge — the corpus coupling needs one"
    absent = _absent_ref()

    # Seat 0 with usable replies: every item is won by a chain member — seat 0 unless the
    # corpus records a legitimate earlier rejection; a non-seat-0 winner must say why.
    chain_ids = {ref.build_id for ref in base}
    solo = _draft(author, recordings, corpus.glob("*.pdf"), tmp_path / "solo",
                  make_fixture_provider, base)
    assert solo.outcomes
    for outcome in solo.outcomes:
        assert outcome.model in chain_ids, (
            f"{outcome.item_id}: won by a model outside the chain: {outcome.model}")
        if outcome.model != base[0].build_id:
            assert outcome.failures, (
                f"{outcome.item_id}: a non-seat-0 winner must record why seat 0 lost")

    # The absent head alone: every item unresolved, and each reason captured for the 3-run check.
    alone = _draft(author, recordings, corpus.glob("*.pdf"), tmp_path / "alone",
                   make_fixture_provider, [absent])
    alone_reasons = {o.item_id: o.failures for o in alone.outcomes}
    assert all(reasons for reasons in alone_reasons.values()), alone_reasons
    assert all(o.model is None for o in alone.outcomes)

    # The absent head first, the base judges second: every item is won by a base member and
    # the FIRST failure reason is the absent head's own — the absent head was tried first
    # (order preserved), and the model that never produced an accepted proposal is in no
    # outcome and in no models_used.
    fallback = _draft(author, recordings, corpus.glob("*.pdf"), tmp_path / "fallback",
                      make_fixture_provider, [absent, *base])
    for outcome in fallback.outcomes:
        assert outcome.model in chain_ids, (
            f"{outcome.item_id}: the fallback winner must be a chain position, "
            f"got {outcome.model}")
        assert outcome.failures, f"{outcome.item_id}: fell back with no failure recorded"
        assert outcome.failures[0] in alone_reasons.get(outcome.item_id, ()), (
            f"{outcome.item_id}: first failure reason is not the absent head's — "
            f"{outcome.failures[0]!r} vs {alone_reasons.get(outcome.item_id)}")
    assert ABSENT_HEAD_BUILD not in fallback.models_used, (
        "the model that never produced an accepted proposal must not be in models_used")


# --- TC-AUTHOR-C07 ----------------------------------------------------------------------------


def test_tc_author_c07_identical_inputs_and_recordings_are_byte_identical(
        tmp_path, make_fixture_provider):
    """Two runs over the same documents and recordings hash equal; a run seeded with an
    unrelated file leaves that file byte-for-byte alone and writes exactly its two artifacts."""
    author, corpus, _af09, recordings = _guards(make_fixture_provider)
    chain = chain_from_config()

    first = _draft(author, recordings, corpus.glob("*.pdf"), tmp_path / "one",
                   make_fixture_provider, chain)
    second = _draft(author, recordings, corpus.glob("*.pdf"), tmp_path / "two",
                    make_fixture_provider, chain)
    assert sha256_of(first.draft_path) == sha256_of(second.draft_path)
    assert sha256_of(first.report_path) == sha256_of(second.report_path)

    seeded = tmp_path / "three"
    seeded.mkdir()
    (seeded / "teacher-notes.txt").write_bytes(b"the teacher's own file\n")
    third = _draft(author, recordings, corpus.glob("*.pdf"), seeded,
                   make_fixture_provider, chain)
    assert {p.name for p in seeded.iterdir()} == {
        "teacher-notes.txt", third.draft_path.name, third.report_path.name}
    assert (seeded / "teacher-notes.txt").read_bytes() == b"the teacher's own file\n"


# --- TC-AUTHOR-C08 ----------------------------------------------------------------------------


def test_tc_author_c08_only_validator_passing_proposals_enter_a_draft(
        tmp_path, make_fixture_provider):
    """A fully resolved draft passes `validate_draft` clean; the AF-09 draft's shipped rows all
    satisfy the structural rules `aeh package build` enforces; the validator is a pure,
    re-runnable function that names its findings."""
    author, corpus, af09, recordings = _guards(make_fixture_provider)
    validate_draft = author.validate_draft
    chain = chain_from_config()

    # Happy path: everything the model proposed passed the gate before entering the draft.
    happy = _draft(author, recordings, corpus.glob("*.pdf"), tmp_path / "happy",
                   make_fixture_provider, chain)
    happy_spec = tomllib.loads(happy.draft_path.read_text(encoding="utf-8"))
    assert validate_draft(happy_spec) == []

    # The validator is deterministic and model-independent: same input, same findings, no
    # provider anywhere near it.
    assert validate_draft(happy_spec) == validate_draft(happy_spec)

    # A malformed spec gets named findings, with the DraftIssue shape.
    malformed = tomllib.loads(happy.draft_path.read_text(encoding="utf-8"))
    banded = next(c for c in malformed["criterion"] if "bands" in c)
    banded["bands"] = banded["bands"][:-1]  # an odd band count is the canonical violation
    issues = validate_draft(malformed)
    assert issues, "an odd band count must be named"
    assert all(isinstance(i, author.DraftIssue) and i.field and i.message for i in issues)

    # The AF-09 draft (reasoning failed to converge): whatever DID ship satisfies the rules —
    # rows carrying sentinels are placeholders and are skipped, nothing else gets a pass.
    failed = _draft(author, recordings, af09.glob("*.pdf"), tmp_path / "failed",
                    make_fixture_provider, chain)
    spec = tomllib.loads(failed.draft_path.read_text(encoding="utf-8"))
    # Every shipped question row is a legal reference target; only the rules-check skips
    # placeholder-carrying rows (their values are placeholders, not proposals to vet).
    questions = {q["id"]: q for q in spec.get("question", [])}
    covered = set()
    skipped_refs = set()
    for criterion in spec.get("criterion", []):
        if _has_sentinel(criterion):
            skipped_refs.add(criterion.get("question"))
            continue
        question = questions.get(criterion.get("question"))
        assert question is not None, f"{criterion.get('id')} references nothing known"
        covered.add(question["id"])
        if _has_sentinel(question):
            continue  # the referenced question is itself a placeholder; nothing to rule-check
        if "key" in criterion:
            assert criterion["key"] in question.get("options", {}), (
                f"{criterion['id']}: key {criterion['key']!r} is not one of the options")
        if "bands" in criterion:
            bands = criterion["bands"]
            assert len(bands) % 2 == 0 and 2 <= len(bands) <= 6, (
                f"{criterion['id']}: {len(bands)} bands")
            points = [band["points"] for band in bands]
            assert points == sorted(points), f"{criterion['id']}: points not worst-first {points}"
    # Coverage, scoped to a converging-failure draft: a question whose every criterion line
    # is a placeholder is exactly the unresolved item the clause allows; a clean question no
    # shipped criterion covers would be a silently dropped proposal.
    uncovered = {qid for qid, row in questions.items() if not _has_sentinel(row)} - covered
    assert uncovered <= skipped_refs, (
        f"clean questions no shipped criterion covers: {sorted(uncovered - skipped_refs)}")