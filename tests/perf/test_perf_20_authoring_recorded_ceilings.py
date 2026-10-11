"""`PERF-20`'s recorded half — the full fixture set's wall clock and call budget (issue #702).

Case: test plan §5.5 (`PERF-20`, `NFR-AUTHOR-02`, `CT-AUTHOR-13`, P0, rung 1, recorded tier);
design delta §3.1 (Performance) and §5.2 (tier policy). Issue #702 (TS-169). The live half of
the same case — the p95 wall-clock assumption over the real endpoint — runs beside
`TC-AUTHOR-31` in `tests/integration/author/test_tc_author_31_live_fixtures.py`, because a
wall clock over real models can only be read where the network is; this file deliberately
touches none (the isolation row: *perf — recorded provider, no network*).

| Recorded full run wall-clock; provider call count; live p95 | Recorded set under 5s; call
| count (authoring-level `complete()` calls — `M-PROV`'s retry budget sits underneath) ≤
| steps × items × ATTEMPTS × chain length; live p95 < 10 min |

**What this adds over `TC-AUTHOR-C13`.** The clause suite's C13 case
(`tests/contract/author/test_cs_author_c13_c14_budget_and_knobs.py`) bounds **AF-01 alone**.
A bound that holds one fixture at a time says nothing about the load the fast tier actually
budgets: the design's Performance requirement is for the **set** — "the full fixture set (§5)
drafts in < 5 s" — and a corpus whose thirteen fixtures each pass C13 could still sum past the
budget. This is that measurement, at the stated load: all thirteen fixtures in one run, one
clock over the whole set, and the call ceiling summed over every fixture's own item count.

**What is counted, and what sits underneath.** `CountingProvider` (the clause suite's double)
wraps the real `RecordedFixtureProvider`, so one `complete` is one authoring-level model call
(`InferenceProvider`'s own contract: no batching, no speculative second sample). The ceiling
`steps × items × HARNESS_AUTHOR_ATTEMPTS × |chain|` is the design's construction bound on the
*reasoning* calls. Transcription (AF-10's scanned document, `FR-AUTHOR-02`) is bounded
separately: one authoring-level transcription request per scanned page — a failed transcription
is recorded in the report, never retried above `M-PROV` (`TC-AUTHOR-30`'s matrix), so
`M-PROV`'s own retry budget sits underneath it exactly as it does under the ceiling. If a red
here names a legitimate design (page chunking, a transcription fallback), the case is *edited*
— a loosened bound is RISK-33's most-missed breaking change and must be visible in review,
never absorbed silently.

**Written ahead of implementation (#690's service, #692's steps, #693's validation gate).**
The guards fail as `NotImplementedYet` naming the story until the surface exists, and the
recordings limb names #686 — the recorded tier has nothing to replay until #690's capture pass
runs. The registry entry (`'#702 TS-169 PERF-20 ...'` in `tests/support/impl.py`) fires only
when every limb lands; these guards re-check the same limbs at unmarking time.
"""

from __future__ import annotations

import time
import tomllib
from pathlib import Path

import pytest

from tests.support.author_vocabulary import (
    AUTHOR_MODULE,
    CountingProvider,
    RECORDINGS,
    af,
    chain_from_config,
    make_service,
    transcriber_from_config,
)
from tests.support.impl import require, require_path

pytestmark = [pytest.mark.integration, pytest.mark.slow, pytest.mark.writtenahead]

CASE = "PERF-20"
#: The stated load: the whole corpus (design delta §5.1: AF-01..AF-13).
AF_IDS = tuple(f"AF-{i:02d}" for i in range(1, 14))

#: The reasoning steps in run order (§3.1's `StepId`: inventory → rubric → grades).
STEPS = 3
#: `HARNESS_AUTHOR_ATTEMPTS`' default (§3.1: 2, refuse <1 or >5). The clause suite's C14 case
#: pins the default itself; this case runs under it — the ceilings below are computed with it.
ATTEMPTS_DEFAULT = 2
#: The fast tier's budget for the whole set (§3.1 Performance: "< 5 s").
BUDGET_S = 5.0


def _guards():
    """The limbs the registry probe carries, re-checked here at unmarking time.

    Order matters for the failure a reader sees: the authoring surface first (the deeper
    blocker, #690), then the corpus, then the recordings (#686) — so once #690 lands, the red
    names the next missing limb instead of the first one forever.
    """
    author = require(AUTHOR_MODULE, issue="#690")
    require(AUTHOR_MODULE, "AuthoringService", "DraftResult", "AuthoringSettings", issue="#690")
    require(AUTHOR_MODULE, "validate_draft", issue="#693")
    require_path(af("AF-01"), "the AF-01 authored fixture", issue="#686")
    require_path(
        RECORDINGS / "coverage.json",
        "the authoring recordings coverage index",
        issue="#686",
    )
    return author


def _knob_defaults_off(monkeypatch) -> None:
    """Run under the knob defaults: the ceilings are computed with `ATTEMPTS_DEFAULT`, and
    AF-10's transcription rides the `auto` default (FR-AUTHOR-02)."""
    monkeypatch.delenv("HARNESS_AUTHOR_ATTEMPTS", raising=False)
    monkeypatch.delenv("HARNESS_AUTHOR_TIMEOUT_S", raising=False)
    monkeypatch.delenv("HARNESS_AUTHOR_TRANSCRIBE", raising=False)


def _draft_the_set(author, recordings: Path, out_root: Path, chain):
    """One draft over every fixture, each into its own directory, each behind its own counter.

    Returns `{af_id: (result, provider, elapsed_s)}`. A fresh `CountingProvider` per fixture
    keeps every count attributable to one fixture — the ceiling is per-fixture by construction
    (`items` differ), and the total is their sum.
    """
    from pypdf import PdfReader

    results: dict[str, tuple] = {}
    for af_id in AF_IDS:
        fixture = af(af_id)
        documents = sorted(fixture.glob("*.pdf"))
        provider = CountingProvider(_fixture_provider(recordings))
        service = make_service(author, chain, provider)
        started = time.perf_counter()
        result = service.draft(documents=documents, output_dir=out_root / af_id)
        elapsed = time.perf_counter() - started
        # The page count the transcription bound is stated against, read from the same
        # documents the run was handed (a page with a text layer needs no transcription, so
        # this is an upper bound on the pages the transcriber can be asked for).
        pages = sum(len(PdfReader(path).pages) for path in documents)
        results[af_id] = (result, provider, elapsed, pages)
    return results


def _fixture_provider(recordings: Path):
    """The recorded transport, bound to the corpus's captured tree (FR-PROV-10).

    `RecordedFixtureProvider` is the shipped implementation, constructed here by name through
    `require` so a missing `aeh.prov` is a stated failure — the same binding the fast tier's
    `make_fixture_provider` fixture makes, without the per-test temp directory (this case
    replays a committed tree, it does not record one).
    """
    provider_cls = require("aeh.prov", "RecordedFixtureProvider", issue="#18")
    return provider_cls(fixture_dir=recordings)


def _items_count(result) -> int:
    """The draft's question count — the `items` in the ceiling, read off the artifact."""
    spec = tomllib.loads(result.draft_path.read_text(encoding="utf-8"))
    items = len(spec["question"])
    assert items >= 1, f"{CASE}: the draft carries no questions to bound"
    return items


# --- the wall-clock budget -------------------------------------------------------------------


def test_perf_20_the_recorded_fixture_set_drafts_under_the_fast_tier_budget(
        tmp_path, monkeypatch):
    """`PERF-20` (P0), wall-clock limb: the thirteen-fixture set drafts in < 5 s total.

    One clock over the whole set — the design's budget is for the *set*, not per fixture, and
    a sum of thirteen green C13 clocks is not that measurement.
    """
    author = _guards()
    _knob_defaults_off(monkeypatch)
    chain = chain_from_config()
    transcriber = transcriber_from_config()
    recordings = RECORDINGS

    results = _draft_the_set(author, recordings, tmp_path, chain)
    total = sum(entry[2] for entry in results.values())
    assert total < BUDGET_S, (
        f"{CASE}: the recorded fixture set took {total:.2f}s to draft — the fast tier's "
        f"budget for the full set is {BUDGET_S:.0f}s (design delta §3.1 Performance). "
        f"Per-fixture seconds: "
        f"{ {af_id: round(entry[2], 3) for af_id, entry in results.items()} }"
    )

    # Every call went to a chain member or the profile transcriber — nothing outside the
    # configured models answered, recorded tier included (CT-AUTHOR-06's order clause).
    allowed = {ref.build_id for ref in chain} | {transcriber.build_id}
    for af_id, (_result, provider, _elapsed, _pages) in results.items():
        stray = {model for model in provider.models_called if model not in allowed}
        assert not stray, (
            f"{CASE}: {af_id}'s recorded replay called {sorted(stray)} — outside the "
            f"configured chain and transcriber"
        )


# --- the call ceiling ------------------------------------------------------------------------


def test_perf_20_the_call_ceiling_holds_at_the_stated_load(tmp_path, monkeypatch):
    """`PERF-20` (P0), call-count limb: per fixture, authoring-level `complete()` calls stay
    within `steps × items × ATTEMPTS × |chain|`; the transcription calls stay within one per
    page; and the totals hold over the set.

    `items` is read from each fixture's own draft, so the ceiling is the fixture's own
    construction bound — a fixture with more questions is allowed proportionally more calls,
    and none of them may exceed it.
    """
    author = _guards()
    _knob_defaults_off(monkeypatch)
    chain = chain_from_config()
    chain_ids = {ref.build_id for ref in chain}
    transcriber_id = transcriber_from_config().build_id
    recordings = RECORDINGS

    results = _draft_the_set(author, recordings, tmp_path, chain)
    total_reasoning = 0
    total_ceiling = 0
    for af_id, (result, provider, _elapsed, pages) in results.items():
        items = _items_count(result)
        ceiling = STEPS * items * ATTEMPTS_DEFAULT * len(chain)
        reasoning_calls = sum(
            1 for model in provider.models_called if model in chain_ids)
        transcriber_calls = sum(
            1 for model in provider.models_called if model == transcriber_id)
        assert reasoning_calls <= ceiling, (
            f"{CASE}: {af_id} made {reasoning_calls} reasoning calls against a construction "
            f"ceiling of {ceiling} (steps={STEPS}, items={items}, "
            f"attempts={ATTEMPTS_DEFAULT}, |chain|={len(chain)}). The call budget is bounded "
            f"by construction (NFR-AUTHOR-02); an unbounded retry anywhere in the module "
            f"breaks it."
        )
        assert transcriber_calls <= pages, (
            f"{CASE}: {af_id} made {transcriber_calls} transcription calls for {pages} "
            f"pages. One authoring-level request per scanned page (FR-AUTHOR-02); a failed "
            f"transcription is recorded, never retried above M-PROV (TC-AUTHOR-30) — a red "
            f"here is a design conversation, not a bound to loosen (RISK-33)."
        )
        # The set total is summed over the same quantity the per-fixture ceilings bound:
        # reasoning calls only. Transcription is bounded separately above (one per page), so
        # folding it in here would compare a reasoning ceiling against a reasoning-plus-
        # transcription count — the two limbs must read the test plan's call-count bound the
        # same way (RISK-33: a bound read two ways is not a bound).
        total_reasoning += reasoning_calls
        total_ceiling += ceiling

    assert total_reasoning <= total_ceiling, (
        f"{CASE}: the full set made {total_reasoning} reasoning calls against a summed "
        f"ceiling of {total_ceiling} — the stated load's call budget (PERF-20) does not hold "
        f"even though every fixture holds its own"
    )