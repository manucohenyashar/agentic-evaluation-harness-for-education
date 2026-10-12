r"""`TC-AUTHOR-04`..`TC-AUTHOR-08` (TS-156, #708) — the chain, the fallback and the repair budget.

| TC ID | FRs / clauses | Breaks if |
|---|---|---|
| TC-AUTHOR-04 | FR-AUTHOR-03, CT-PROV-15 | `aeh.author` imports an HTTP client (or one of the planted SDK canaries), a request payload never carries a document's extracted text, or one carries a credential from the environment |
| TC-AUTHOR-05 | FR-AUTHOR-04, CT-CONF-03 | the reasoning chain does not resolve from the named profile — (a) dev-ci's one judge, (b) ordered and de-duplicated with escalations after the panel and the cross-section duplicate collapsing, (c) an empty panel refused before any call even with escalations present (Q-O7) |
| TC-AUTHOR-06 | FR-AUTHOR-05, CT-AUTHOR-06 | a head that cannot answer does not defer in declared order, the failure reasons are not recorded in fallback order, or the winner is not the first model whose proposal passes |
| TC-AUTHOR-07 | FR-AUTHOR-05, CT-AUTHOR-06 | an unparseable reply or a validator-failing proposal is not repaired with the rejection reason inside the budget; `HARNESS_AUTHOR_ATTEMPTS=1` repairs, `=5` does not exhaust; 0 and 6 are accepted |
| TC-AUTHOR-08 | FR-AUTHOR-05, NFR-AUTHOR-01 | an item whose every repair attempt is exhausted kills the run instead of being marked unresolved and listed first in the report's Unresolved section |

Everything rides the §3.1 surface through `tests.support.author_vocabulary` (the shared
disclosed-bets table) and the doubles defined there — `GarbageProvider` (every reply
unparseable, no recording needed) and `ScriptedProvider` (a parseable proposal, then a
parseable-but-invalid one). The order oracle of TC-AUTHOR-06 is the CS-C06 technique:
cross-run equality of the failure reasons, so no reason *text* is pinned.

**Disclosed bets.** (i) TC-AUTHOR-07b's proposal reply is the spec vocabulary itself —
`{"question": [...]}` / `{"criterion": [...]}` objects mirroring the
`[[question]]`/`[[criterion]]` tables of `docs/live-tests/config/ps9-forces-01.package.toml`
— which the parser accepts and `validate_draft` then rejects on a crafted five-band
criterion (an odd band count, the design's canonical example); the repair payload is
asserted to carry one of the very messages `validate_draft` returns for that spec. (ii) The
ATTEMPTS oracle ("=1 skips repair", "=5 exhausts") reads the knob as *total tries per
attempt*, while design §3.1's config table words it "repair attempts"; the boundary test
asserts the facts that hold under either reading and pins the oracle's reading with the
repair-pair check — a repair-attempts reading fails there at unmarking, which is exactly
the reconciliation that discrepancy needs. (iii) `GarbageProvider`/`ScriptedProvider`
assume transcription may or may not ride the provider: every chain assertion is made over
the calls addressed to the reasoning chain's builds, so a transcriber call cannot desync
them either way. (iv) `DraftResult.unresolved`/`.placeholders`/`.resolved` are **counts**
(design §3.1's data block), so per-item state is derived from `outcomes` by `status` —
asserted as the union `{"unresolved", "placeholder"}`, since FR-AUTHOR-05 words the
exhausted mark *unresolved* while NFR-AUTHOR-01 words the affected items *placeholders*
and `ItemStatus` carries both; the count fields are asserted where a count is meant. (v)
TC-AUTHOR-08's report scan anchors each section name at a line start (optional `#` heading
mark, case-sensitive): CT-AUTHOR-05/FR-AUTHOR-12 pin the section set and order, not the
heading rendering — if the headings render otherwise, the one-line change is the scan's
pattern.

Written ahead of #691 ("chain resolution, fallback and the repair budget"), keyed in
`WRITTEN_AHEAD_BLOCKERS` as the `command` probe `#691 chain fallback` — the registry
entry's comment block records why not the issue's suggested `symbol` key
(`aeh.author:AuthoringService` resolves the day #690 lands, the early-fire direction) and
what the probe discriminates instead. At resolution: re-check these five cases GREEN before
unmarking, never on the notice alone.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib

import pytest

from aeh.conf import ConfigurationError, panel_for_profile, parse_config_document

from tests.support.author_vocabulary import (
    ABSENT_HEAD_BUILD,
    ABSENT_SECOND_BUILD,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    DEV_CI_CONFIG,
    FALLBACK_ISSUE,
    RECORDINGS,
    GarbageProvider,
    ScriptedProvider,
    absent_ref,
    af,
    chain_from_config,
    make_service,
    placeholder_fields,
    repair_pairs,
    transcriber_from_config,
)
from tests.support.conf_builders import (
    HOSTED_ESCALATION_A,
    HOSTED_ESCALATION_DUPLICATE,
    HOSTED_JUDGE,
    HOSTED_JUDGE_2,
    HOSTED_JUDGE_3,
    HOSTED_PANEL_3,
    hosted_cfg,
)
from tests.support.impl import require, require_path



def _surface():
    """The §3.1 surface via `require` — the written-ahead gate names #691 first."""
    author = require(AUTHOR_MODULE, issue=FALLBACK_ISSUE)
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=FALLBACK_ISSUE)
    return author


def _devci_chain() -> list:
    """The dev-ci profile's reasoning chain, resolved through the production path."""
    cfg = parse_config_document(DEV_CI_CONFIG.read_text(encoding="utf-8"), "toml")
    return list(panel_for_profile(cfg, "dev-ci"))


def _reasoning_calls(provider, builds: set[str]) -> list:
    """The provider's calls addressed to the reasoning chain's builds.

    Transcription may or may not ride the provider (the vocabulary's disclosed bet); the
    chain oracle is about the reasoning walk, so the transcriber's calls — if any — are
    filtered out rather than assumed away.
    """
    return [call for call in provider.calls if call[1].build_id in builds]


def _unresolved_ids(result) -> set[str]:
    """The item ids the run could not fill, derived from `outcomes` by `status`.

    `DraftResult.unresolved` is a count (design §3.1's data block), so the per-item view
    comes from the outcomes — as the union `{"unresolved", "placeholder"}`: FR-AUTHOR-05
    records an exhausted item *unresolved*, NFR-AUTHOR-01 says the affected items *are
    placeholders*, and `ItemStatus` carries both words, so asserting the union survives
    whichever reading #691 ships. The count fields are asserted where a count is meant.
    """
    return {o.item_id for o in result.outcomes
            if o.status in ("unresolved", "placeholder")}


# --- TC-AUTHOR-04 ------------------------------------------------------------------------------


def test_tc_author_04_no_http_client_is_imported_and_payloads_carry_only_extracted_text(
        tmp_path, repo_root, network_guard):
    """The subprocess sweep finds no HTTP client (and none of the planted SDK canaries)
    in `sys.modules` after importing `aeh.author`; the payloads of a real garbage-reply run
    carry every document's extracted text, and never a credential from the environment."""
    author = _surface()
    corpus = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    documents = sorted(corpus.glob("*.pdf"))
    assert documents, "AF-01 carries no PDFs — the payload oracle needs the documents"

    # The import sweep (the oracle's subprocess half): a fresh interpreter imports the
    # module and reports which of the HTTP clients — real ones or the ADV-18 canaries —
    # came with it. The suspect list is calibrated on today's tree: none of these loads
    # through `aeh.conf` or `aeh.prov`, so a hit is `aeh.author`'s own doing.
    suspects = (
        "http.client", "urllib.request", "urllib3", "requests", "aiohttp", "httpx",
        "httpx2", "typesafe_sdk",
    )
    code = (
        "import sys, json;"
        f"sys.path[:0] = {[str(repo_root / 'src'), str(repo_root)]!r};"
        "import aeh.author;"
        f"suspects = {suspects!r};"
        "print(json.dumps([m for m in suspects if m in sys.modules]))"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=repo_root,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, f"the import sweep failed: {proc.stderr[-2000:]}"
    loaded = json.loads(proc.stdout.strip().splitlines()[-1])
    assert loaded == [], f"aeh.author imported HTTP clients: {loaded}"

    # The payload half: a real draft run whose every reply is garbage — the payloads are
    # the module's own assembled requests, independent of what the replies would have been.
    chain = _devci_chain()
    known_builds = {chain[0].build_id, transcriber_from_config().build_id}
    provider = GarbageProvider()
    service = make_service(author, chain, provider)
    result = service.draft(documents=documents, output_dir=tmp_path)
    assert provider.calls, "the run made no provider calls — the payload oracle is vacuous"
    for prompt, model_ref, _params in provider.calls:
        assert model_ref.build_id in known_builds, (
            f"a call went to {model_ref.build_id!r}, outside the injected chain and the "
            "profile transcriber (FR-AUTHOR-04)")
        assert prompt.fields and all(
            isinstance(name, str) and name and isinstance(value, str)
            for name, value in prompt.fields)

    # Every document's extracted text reaches the payloads (FR-AUTHOR-03: the payload is
    # the extracted document text plus the step prompt). Whitespace is normalised on both
    # sides — pypdf's rendering is the extractor's, and the module may fold it.
    import pypdf

    def norm(text: str) -> str:
        return " ".join(text.split())

    joined = norm("\n".join(
        value for prompt, _ref, _params in provider.calls
        for _name, value in prompt.fields))
    for document in documents:
        reader = pypdf.PdfReader(str(document))
        extracted = norm("".join(page.extract_text() or "" for page in reader.pages))
        assert extracted and extracted in joined, (
            f"{document.name}: the extracted text never reached any request payload")

    # No credential from the environment appears in any payload, name or value. The values
    # are never echoed — the assertion is boolean on purpose. Vacuous when no such variable
    # is set; the env-side sweep is SEC-26's own case.
    credentials = [
        value for key, value in os.environ.items()
        if any(tag in key.upper() for tag in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
        and isinstance(value, str) and len(value) >= 12
    ]
    for prompt, _ref, _params in provider.calls:
        blob = "\n".join(name + "\n" + value for name, value in prompt.fields)
        assert not any(credential in blob for credential in credentials), (
            "a request payload carries a credential-shaped environment value "
            "(FR-AUTHOR-03, CT-PROV-15); the value is deliberately not echoed")
    network_guard.assert_no_network()


# --- TC-AUTHOR-05 ------------------------------------------------------------------------------


def test_tc_author_05a_the_dev_ci_profile_resolves_one_judge_and_the_run_uses_only_it(
        tmp_path, make_fixture_provider, network_guard):
    """The chain matrix (a): dev-ci resolves to its single judge through the production
    resolver — equal to the corpus-coupling helper's chain — and the recorded AF-01 run
    addresses every reasoning call to that one model, converging with no placeholders."""
    author = _surface()
    corpus = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    chain = _devci_chain()
    assert chain == chain_from_config(), (
        "the production resolver and the corpus-coupling helper disagree — the recordings "
        "are keyed on the helper's chain (the vocabulary docstring's disclosure)")
    assert len(chain) == 1 and chain[0].is_resolved(), (
        f"dev-ci must resolve to one resolved judge, got {chain!r}")

    service = make_service(author, chain, make_fixture_provider(RECORDINGS))
    result = service.draft(documents=sorted(corpus.glob("*.pdf")), output_dir=tmp_path)
    assert result.outcomes, "the recorded run produced no outcomes"
    for outcome in result.outcomes:
        assert outcome.model == chain[0].build_id, (
            f"{outcome.item_id}: won by {outcome.model!r}, not the profile's one judge")
    assert set(result.models_used) == {chain[0].build_id}
    assert result.unresolved == 0 and result.placeholders == 0, (
        "AF-01's expectation is a converging run (expected.toml: outcome resolved)")
    assert _unresolved_ids(result) == set(), (
        "no item may be left unresolved or placeholder in the converging run")
    assert [field for field in placeholder_fields(result.draft_path.read_text(encoding="utf-8"))
            if field != "approved_by"] == [], (
        "the resolved draft carries a content sentinel (`approved_by` rides on every "
        "outcome class — TC-AUTHOR-12 — and is excluded here)")
    network_guard.assert_no_network()


def test_tc_author_05b_three_judges_and_two_escalations_with_a_duplicate_resolve_ordered(
        tmp_path, network_guard):
    """The chain matrix (b): the panel in declared order, then the escalations, the
    cross-section duplicate collapsed by build identity — and the service walks exactly
    that chain: seat 0 first, each escalation first seen only after the panel seat before
    it, four distinct models (never five), every item unresolved with a failure per chain
    position, and nothing in `models_used`."""
    author = _surface()
    corpus = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    assert HOSTED_ESCALATION_DUPLICATE == HOSTED_JUDGE_3 and (
        HOSTED_ESCALATION_DUPLICATE is not HOSTED_JUDGE_3), (
        "the duplicate fixture must equal HOSTED_JUDGE_3 by build identity, as a distinct "
        "object, or the de-duplication assertion below proves nothing")
    cfg = hosted_cfg(**{"panel": HOSTED_PANEL_3,
                        "escalation_judge": (HOSTED_ESCALATION_A,
                                             HOSTED_ESCALATION_DUPLICATE)})
    chain = list(panel_for_profile(cfg, "cloud-hosted"))
    assert chain == [*HOSTED_PANEL_3, HOSTED_ESCALATION_A], (
        f"the chain is {chain!r}; the design's is the panel in declared order then the "
        "escalation that names a new build, de-duplicated by build identity (FR-AUTHOR-04)")

    provider = GarbageProvider()
    service = make_service(author, chain, provider)
    result = service.draft(documents=sorted(corpus.glob("*.pdf")), output_dir=tmp_path)

    reasoning_calls = _reasoning_calls(provider, {ref.build_id for ref in chain})
    assert reasoning_calls, "the service never called the resolved chain"
    first_seen: dict[str, int] = {}
    for index, (_prompt, model_ref, _params) in enumerate(reasoning_calls):
        first_seen.setdefault(model_ref.build_id, index)
    assert set(first_seen) == {ref.build_id for ref in chain}, (
        "the reasoning walk called a build outside the resolved chain")
    order = sorted(first_seen, key=first_seen.get)
    assert order == [ref.build_id for ref in chain], (
        f"first-appearance order {order} is not the chain order — seat 0 first, "
        "escalations after the panel (FR-AUTHOR-04)")
    assert reasoning_calls[0][1].build_id == HOSTED_JUDGE.build_id, (
        "the first reasoning call did not go to the panel's seat 0")
    assert HOSTED_JUDGE_2.build_id in first_seen and HOSTED_JUDGE_3.build_id in first_seen, (
        "a panel seat was never tried — the fallback skipped a position")
    assert result.outcomes
    for outcome in result.outcomes:
        assert outcome.model is None, (
            f"{outcome.item_id}: every reply was garbage, yet a model is credited")
        assert len(outcome.failures) >= len(chain), (
            f"{outcome.item_id}: {len(outcome.failures)} failures recorded for a "
            f"{len(chain)}-position chain — at least one per position")
    assert _unresolved_ids(result) == {o.item_id for o in result.outcomes}, (
        "an item with no accepted proposal is not marked unresolved")
    assert list(result.models_used) == [], (
        "nothing was accepted, yet models_used credits a model")
    network_guard.assert_no_network()


def test_tc_author_05c_an_empty_panel_is_refused_before_any_call_even_with_escalations(
        tmp_path, network_guard):
    """The chain matrix (c): with escalations present but no panel, the refusal names the
    profile and fires before the provider sees a single call — and the service-level arm
    refuses an empty chain too (Q-O7: the escalations are never a chain on their own)."""
    author = _surface()
    corpus = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    documents = sorted(corpus.glob("*.pdf"))
    provider = GarbageProvider()
    assert HOSTED_ESCALATION_A.is_resolved(), (
        "the escalation fixture must be resolved, or the case confounds the empty-panel "
        "refusal with a resolution error")
    cfg = hosted_cfg(**{"panel": (), "escalation_judge": (HOSTED_ESCALATION_A,)})

    with pytest.raises(ConfigurationError) as refusal:
        chain = panel_for_profile(cfg, "cloud-hosted")
        service = make_service(author, list(chain), provider)
        service.draft(documents=documents, output_dir=tmp_path / "resolver-arm")
    assert "cloud-hosted" in str(refusal.value), (
        f"the refusal must name the profile: {refusal.value!r}")
    assert provider.calls == [], "the empty-panel refusal fired after a provider call"

    # The service-level arm: an empty chain is refused even when constructed directly —
    # before any call (design §3.1's error-handling table).
    with pytest.raises(ConfigurationError) as service_refusal:
        bare = author.AuthoringService(chain=[], provider=provider, transcriber=None,
                                       settings=author.AuthoringSettings())
        bare.draft(documents=documents, output_dir=tmp_path / "service-arm")
    assert provider.calls == [], "the empty-chain service drafted anyway"
    network_guard.assert_no_network()


# --- TC-AUTHOR-06 ------------------------------------------------------------------------------


def test_tc_author_06_the_head_that_cannot_answer_defers_in_order_and_the_winner_records(
        tmp_path, make_fixture_provider, network_guard):
    """A head whose every call fails defers to the next position in declared order: the
    fallback run's `failures[0]` is the first head's own reason (equality with its solo
    run), `failures[1]` the second head's, and the winner is the first model whose proposal
    passes. No reason text is pinned — cross-run equality pins the order (CS-C06)."""
    author = _surface()
    corpus = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    documents = sorted(corpus.glob("*.pdf"))
    base = chain_from_config()
    assert base, "the dev-ci profile names no judge — the corpus coupling needs one"

    def run(chain, out):
        service = make_service(author, chain, make_fixture_provider(RECORDINGS))
        return service.draft(documents=documents, output_dir=out)

    first = absent_ref(ABSENT_HEAD_BUILD)
    second = absent_ref(ABSENT_SECOND_BUILD)
    solo_first = run([first], tmp_path / "solo-first")
    solo_second = run([second], tmp_path / "solo-second")
    reasons_first = {o.item_id: o.failures for o in solo_first.outcomes}
    reasons_second = {o.item_id: o.failures for o in solo_second.outcomes}
    assert reasons_first and reasons_second, "the solo runs produced no outcomes"
    assert all(reasons for reasons in reasons_first.values()), reasons_first
    assert all(reasons for reasons in reasons_second.values()), reasons_second
    assert all(o.model is None for o in solo_first.outcomes)
    assert all(o.model is None for o in solo_second.outcomes)

    # A provider error is FR-AUTHOR-05a's trigger and defers immediately — no repair
    # against a model that raised — so the fallback run records exactly one failure per
    # failed head, in the order the heads were tried.
    fallback = run([first, second, *base], tmp_path / "fallback")
    assert fallback.outcomes
    checked = 0
    for outcome in fallback.outcomes:
        assert outcome.model == base[0].build_id, (
            f"{outcome.item_id}: the winner is {outcome.model!r}, not the first model "
            "whose proposal passes (CT-AUTHOR-06)")
        assert len(outcome.failures) == 2, (
            f"{outcome.item_id}: {len(outcome.failures)} failures recorded for two "
            "failed heads")
        # Disclosed reconcile (the landing): a solo run's inventory fails as a step — no
        # questions exist to carry the failure, so the failed item is the inventory itself
        # — while the fallback's succeeded inventory fans out one outcome per question
        # carrying that same call's reasons (CT-AUTHOR-03's one-outcome-per-item). The
        # cross-run equality therefore fires where the two runs named the same item: the
        # grades row by id, and every inventory row against the solo run's step-level
        # record. A rubric row has no solo counterpart (a solo inventory that failed
        # yielded no questions to map), and its two recorded failures are already pinned
        # by the count check above.
        def solo_reasons(reasons, _outcome=outcome):
            if _outcome.item_id in reasons:
                return reasons[_outcome.item_id]
            if _outcome.step == "inventory":
                return reasons.get("inventory")
            return None
        first_reasons = solo_reasons(reasons_first)
        if first_reasons is None:
            continue
        checked += 1
        assert outcome.failures[0] == first_reasons[0], (
            f"{outcome.item_id}: failures[0] is not the first head's own reason")
        assert outcome.failures[1] == solo_reasons(reasons_second)[0], (
            f"{outcome.item_id}: failures[1] is not the second head's own reason")
    assert checked, "no outcome had a solo counterpart to compare against"
    assert list(fallback.models_used) == [base[0].build_id], (
        f"models_used must show the sequence that actually answered, got "
        f"{fallback.models_used!r}")
    network_guard.assert_no_network()


# --- TC-AUTHOR-07 ------------------------------------------------------------------------------


def test_tc_author_07a_an_unparseable_reply_is_repaired_with_the_complaint_in_budget(
        tmp_path, monkeypatch, network_guard):
    """FR-AUTHOR-05b: an unparseable reply is repaired on the same model with the parser's
    complaint — the repair payloads are the same prompt PLUS non-empty added text — until
    the budget exhausts, and the item ends unresolved with the run intact (NFR-AUTHOR-01)."""
    author = _surface()
    corpus = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    chain = _devci_chain()
    reasoning = chain[0].build_id
    monkeypatch.delenv("HARNESS_AUTHOR_ATTEMPTS", raising=False)
    provider = GarbageProvider()
    service = make_service(author, chain, provider)
    result = service.draft(documents=sorted(corpus.glob("*.pdf")), output_dir=tmp_path)

    pairs = repair_pairs(provider.calls, build_id=reasoning)
    assert pairs, "no repair attempt followed an unparseable reply (FR-AUTHOR-05b)"
    assert result.unresolved, "a reply that never parses must leave the item unresolved"
    assert _unresolved_ids(result) == {o.item_id for o in result.outcomes}
    for p1, p2 in pairs:
        assert "\n".join(v for _n, v in p1.fields) != "\n".join(v for _n, v in p2.fields), (
            "a repair attempt re-sent the identical prompt — the complaint never reached "
            "the model")
    assert {p.name for p in tmp_path.iterdir()} == {
        result.draft_path.name, result.report_path.name}, (
        "the exhausted run did not complete with exactly its two artifacts")
    network_guard.assert_no_network()


def test_tc_author_07a_attempt_boundaries_one_skips_repair_and_five_exhausts(
        tmp_path, monkeypatch, network_guard):
    """The oracle's boundaries: `HARNESS_AUTHOR_ATTEMPTS=1` makes one attempt and no repair
    pair; `=5` exhausts the budget (calls grow, repairs happen) and still ends unresolved.

    The call-count bounds hold under either reading of the knob (total tries per attempt,
    or repair attempts on top of the first); the oracle's own words — "=1 skips repair" —
    hold only under the total-tries reading, which the repair-pair check pins. A
    repair-attempts reading fails there at unmarking, and that is the reconciliation the
    §3.1 config table ("repair attempts") vs the plan's oracle wording needs.
    """
    author = _surface()
    corpus = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    documents = sorted(corpus.glob("*.pdf"))
    chain = _devci_chain()
    reasoning = chain[0].build_id
    for name in ("HARNESS_AUTHOR_ATTEMPTS", "HARNESS_AUTHOR_TIMEOUT_S",
                 "HARNESS_AUTHOR_TRANSCRIBE"):
        monkeypatch.delenv(name, raising=False)

    def run(out):
        provider = GarbageProvider()
        service = make_service(author, chain, provider)
        result = service.draft(documents=documents, output_dir=out)
        return provider, result

    _provider_default, result_default = run(tmp_path / "default")
    monkeypatch.setenv("HARNESS_AUTHOR_ATTEMPTS", "1")
    provider_one, result_one = run(tmp_path / "one")
    monkeypatch.setenv("HARNESS_AUTHOR_ATTEMPTS", "5")
    provider_five, result_five = run(tmp_path / "five")

    assert len(provider_one.calls) < len(_provider_default.calls), (
        "ATTEMPTS=1 made at least as many calls as the default budget")
    assert repair_pairs(provider_one.calls, build_id=reasoning) == [], (
        "ATTEMPTS=1 must skip repair — the oracle's own words (total tries per attempt)")
    assert result_one.unresolved and result_five.unresolved, (
        "an unparseable reply leaves the item unresolved at either boundary")
    assert all(o.model is None for o in result_five.outcomes)
    calls_one, calls_five = len(provider_one.calls), len(provider_five.calls)
    assert 2 * calls_one <= calls_five <= 6 * calls_one, (
        f"ATTEMPTS=5 made {calls_five} calls against ATTEMPTS=1's {calls_one} — outside "
        "every reading of the knob (5x per unit at total-tries, 6x at repair-attempts)")
    assert repair_pairs(provider_five.calls, build_id=reasoning), (
        "ATTEMPTS=5 must exhaust the budget with repairs before the unresolved mark")
    network_guard.assert_no_network()


def test_tc_author_07_attempt_counts_outside_the_bounds_are_refused_by_name(
        tmp_path, monkeypatch, network_guard):
    """0 and 6 are outside ATTEMPTS's 1..5 bound (design §3.1's knobs table): the refusal
    names the knob and its legal bound. The exception type is deliberately not pinned (the
    C14 precedent), and the refusal fires before the provider sees a call."""
    author = _surface()
    corpus = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    documents = sorted(corpus.glob("*.pdf"))
    chain = _devci_chain()
    for value, bound in (("0", r"\b1\b"), ("6", r"\b5\b")):
        provider = GarbageProvider()
        monkeypatch.setenv("HARNESS_AUTHOR_ATTEMPTS", value)
        with pytest.raises(Exception) as refused:
            service = make_service(author, chain, provider)
            service.draft(documents=documents, output_dir=tmp_path / f"refused-{value}")
        assert "HARNESS_AUTHOR_ATTEMPTS" in str(refused.value), (
            f"ATTEMPTS={value}: the refusal must name the knob, got {refused.value!r}")
        assert re.search(bound, str(refused.value)), (
            f"ATTEMPTS={value}: the refusal must name the legal bound ({bound})")
        assert provider.calls == [], "the out-of-bounds knob reached a provider call"
    network_guard.assert_no_network()


def test_tc_author_07b_a_validator_failing_proposal_is_repaired_with_the_validator_complaint(
        tmp_path, monkeypatch, network_guard):
    """FR-AUTHOR-05c: a proposal the parser accepts and the deterministic rules reject is
    repaired with the validator's issues — some repair payload's added text carries one of
    the messages `validate_draft` returns for the crafted spec — until the budget
    exhausts, and no proposal that failed the gate enters the draft.

    The crafted violation is a five-band criterion (an odd band count, the design's
    canonical example) against a one-question open inventory; the reply envelope is the
    spec vocabulary (the file docstring's disclosed bet)."""
    author = _surface()
    corpus = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    chain = _devci_chain()
    reasoning = chain[0].build_id
    monkeypatch.delenv("HARNESS_AUTHOR_ATTEMPTS", raising=False)

    # The crafted spec stays in the spec vocabulary (validate_draft's own input); the
    # *scripted replies* carry the steps' reply envelopes.
    # Disclosed reconcile (the landing, docstring bet (i)): the steps' parsers take the
    # step envelopes the prompts pin — the inventory's `{"questions": [...]}` (package
    # optional) and the rubric's `{"bands": [...]}` — not the spec-vocabulary
    # `{"question": [...]}`/`{"criterion": [...]}` bet; the validator half of the bet
    # stands unchanged, and the repair oracle below is untouched.
    inventory_reply = {"questions": [{"id": "Q1", "type": "open", "points": 4,
                                      "text": "Explain the trade-off in one paragraph.",
                                      "model_answer": "The trade-off is ..."}]}
    crafted = {"question": [{"id": "Q1", "type": "open", "points": 4,
                             "text": "Explain the trade-off in one paragraph.",
                             "model_answer": "The trade-off is ..."}],
               "criterion": [{"id": "C1", "question": "Q1", "bands": [
        {"name": "none", "points": 0, "descriptor": "no explanation"},
        {"name": "partial", "points": 1, "descriptor": "one side only"},
        {"name": "adequate", "points": 2, "descriptor": "both sides, shallow"},
        {"name": "strong", "points": 3, "descriptor": "both sides, reasoned"},
        {"name": "exemplary", "points": 4, "descriptor": "both sides, evidenced"},
    ]}]}
    malformed = {"bands": crafted["criterion"][0]["bands"]}
    issues = author.validate_draft(crafted)
    assert issues, "the crafted five-band criterion must be rejected by validate_draft"
    assert all(isinstance(issue, author.DraftIssue) and issue.field and issue.message
               for issue in issues)
    messages = [issue.message for issue in issues]

    provider = ScriptedProvider(replies=[json.dumps(inventory_reply), json.dumps(malformed)],
                                build_id=reasoning)
    service = make_service(author, chain, provider)
    result = service.draft(documents=sorted(corpus.glob("*.pdf")), output_dir=tmp_path)

    assert result.unresolved, "a proposal that never validates leaves the item unresolved"
    pairs = repair_pairs(provider.calls, build_id=reasoning)
    assert pairs, "no repair attempt followed the validator-failing proposal"
    added_texts = []
    for p1, p2 in pairs:
        fields1, fields2 = list(p1.fields), list(p2.fields)
        set1 = set(fields1)
        if set1 <= set(fields2) and fields1 != fields2:
            added_texts.append("\n".join(
                pair[1] for pair in fields2 if pair not in set1))
            continue
        if [name for name, _v in fields1] == [name for name, _v in fields2]:
            extensions = [
                (v1, v2) for (_n1, v1), (_n2, v2) in zip(fields1, fields2)
                if v2 != v1 and v2.startswith(v1)
            ]
            if len(extensions) == 1:
                added_texts.append(extensions[0][1][len(extensions[0][0]):])
    assert any(message in added for added in added_texts for message in messages), (
        "no repair payload carries the validator's complaint (FR-AUTHOR-05); the validator "
        f"said {messages!r}")

    # And nothing that failed the gate entered the draft: every shipped criterion keeps
    # the band rules (even count, 2 to 6, worst-first) — CS-C08's rules on this run.
    # Disclosed reconcile (the landing): the unresolved rubric's criterion stands in the
    # draft with the sentinel string as its `bands` value (CT-AUTHOR-04 — the sentinel is
    # the field's value), so the scan reads only real band lists; the sentinel is the
    # build-refusal gate's business (FR-PKG-28), not a shipped set.
    spec = tomllib.loads(result.draft_path.read_text(encoding="utf-8"))
    for criterion in spec.get("criterion", []):
        if isinstance(criterion.get("bands"), list):
            count = len(criterion["bands"])
            assert count % 2 == 0 and 2 <= count <= 6, (
                f"{criterion.get('id')}: {count} bands shipped")
            points = [band["points"] for band in criterion["bands"]]
            assert points == sorted(points), (
                f"{criterion.get('id')}: bands not worst-first")
    network_guard.assert_no_network()


# --- TC-AUTHOR-08 ------------------------------------------------------------------------------


def test_tc_author_08_the_exhausted_run_marks_the_item_unresolved_and_lists_it_first(
        tmp_path, make_fixture_provider, network_guard):
    """AF-09 (contradictory) with every repair attempt exhausted: the run completes with
    no exception, writes exactly its two artifacts, marks the item unresolved, and the
    report's Unresolved section lists the first unresolved item first (NFR-AUTHOR-01,
    CT-AUTHOR-05's section order)."""
    author = _surface()
    af09 = require_path(af("AF-09"), "the AF-09 authored fixture", issue=CORPUS_ISSUE)
    require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    expected = tomllib.loads((af09 / "expected.toml").read_text(encoding="utf-8"))

    service = make_service(author, chain_from_config(), make_fixture_provider(RECORDINGS))
    result = service.draft(documents=sorted(af09.glob("*.pdf")), output_dir=tmp_path)

    assert result.unresolved, "AF-09's expectation is a converging-failure run"
    assert {p.name for p in tmp_path.iterdir()} == {
        result.draft_path.name, result.report_path.name}, (
        "the exhausted run did not complete with exactly its two artifacts")
    fields = placeholder_fields(result.draft_path.read_text(encoding="utf-8"))
    # Disclosed reconcile (the landing): `approved_by` rides on every outcome class
    # (TC-AUTHOR-12) and is never counted, so the draft oracle reads the content sentinels.
    fields = [field for field in fields if field != "approved_by"]
    assert sorted(fields) == sorted(expected.get("placeholders", [])), (
        f"the draft's sentinels {fields} are not the corpus expectation "
        f"{expected.get('placeholders', [])}")
    assert result.placeholders == len(expected.get("placeholders", [])), (
        f"the run counted {result.placeholders} placeholders against the corpus "
        f"expectation {expected.get('placeholders', [])}")

    report = result.report_path.read_text(encoding="utf-8")
    positions: dict[str, int] = {}
    cursor = 0
    for section in ("Documents", "Steps", "Items", "Unresolved", "Next command"):
        # Line-anchored and case-sensitive (the file docstring's disclosed bet (v)): a
        # heading opens a line, optionally with the `#` mark, so a section word inside
        # prose cannot satisfy the scan; sequential findability is the pinned order.
        match = re.search(rf"(?m)^\s*#*\s*{re.escape(section)}\b", report[cursor:])
        assert match, f"the report has no {section!r} section"
        positions[section] = cursor + match.start()
        cursor = positions[section] + len(section)
    unresolved_section = report[positions["Unresolved"]:positions["Next command"]]
    listed = [o.item_id for o in result.outcomes
              if o.status in ("unresolved", "placeholder")]
    assert listed, "the outcomes name no unresolved item"
    first_pos = unresolved_section.find(listed[0])
    assert first_pos >= 0, f"{listed[0]!r} is not named in the Unresolved section"
    for later in listed[1:]:
        later_pos = unresolved_section.find(later)
        if later_pos >= 0:
            assert later_pos > first_pos, (
                "the first unresolved item is not listed first in the report")
    network_guard.assert_no_network()