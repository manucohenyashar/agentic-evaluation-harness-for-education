r"""CT-AUTHOR-13 and CT-AUTHOR-14 — the call ceiling and the knob contract (TS-165, #689).

| TC ID | Clause | Breaks if |
|---|---|---|
| TC-AUTHOR-C13 | CT-AUTHOR-13 perf | the recorded replay makes more than `steps × items × HARNESS_AUTHOR_ATTEMPTS × \|chain\|` authoring-level `complete()` calls, takes longer than the fast tier's 5 s budget, or ever calls a model outside the injected chain |
| TC-AUTHOR-C14 | CT-AUTHOR-14 config | a knob default shifts, an invalid knob value is accepted (or a refusal fails to name the knob and its legal bound), or any environment variable changes the chain — the reasoning chain is the run configuration's, never the environment's |

The ceiling is counted over the whole draft by a `CountingProvider` wrapped around the real
`RecordedFixtureProvider` — authoring-level calls, one `complete` per model call
(`InferenceProvider`'s own contract). The ATTEMPTS value in the ceiling is the knob's default
(2, design §3.1); C14 separately proves the default is in force. The replay must also be fast:
the recorded fixture set drafts in < 5 s (design §3.1 Performance), and one fixture is well
under that.

Rung 1, guards first (#689 then #686).
"""

from __future__ import annotations

import re
import time
import tomllib
from pathlib import Path

import pytest

from tests.support.author_vocabulary import (
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    CountingProvider,
    RECORDINGS,
    af,
    chain_from_config,
    make_service,
    transcriber_from_config,
)
from tests.support.impl import require, require_attr, require_path

pytestmark = [pytest.mark.contract, pytest.mark.writtenahead]


def _guards(make_fixture_provider) -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names
    require_attr(author, "AuthoringInputError", issue=AUTHOR_ISSUE)
    corpus = require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, corpus, recordings


# --- TC-AUTHOR-C13 ----------------------------------------------------------------------------


def test_tc_author_c13_recorded_replay_holds_the_call_ceiling_and_the_wall_clock(
        tmp_path, make_fixture_provider):
    """AF-01 replays with at most steps × items × ATTEMPTS × |chain| calls, under 5 s, and
    every call is addressed to a chain member or the profile transcriber."""
    author, corpus, recordings = _guards(make_fixture_provider)
    chain = chain_from_config()
    transcriber = transcriber_from_config()
    provider = CountingProvider(make_fixture_provider(recordings))

    started = time.perf_counter()
    result = make_service(author, chain, provider).draft(
        documents=sorted(corpus.glob("*.pdf")), output_dir=tmp_path / "out")
    elapsed = time.perf_counter() - started

    spec = tomllib.loads(result.draft_path.read_text(encoding="utf-8"))
    items = len(spec["question"])
    assert items >= 1, "the draft carries no questions to bound"
    ceiling = 3 * items * 2 * len(chain)  # steps × items × default ATTEMPTS × |chain|
    assert len(provider.calls) <= ceiling, (
        f"{len(provider.calls)} calls exceed the construction ceiling {ceiling} "
        f"(steps=3, items={items}, attempts=2, chain={len(chain)})")
    assert elapsed < 5.0, f"the recorded replay took {elapsed:.2f}s — the fast tier's budget is 5"

    allowed = {ref.build_id for ref in chain} | {transcriber.build_id}
    stray = {model for model in provider.models_called if model not in allowed}
    assert not stray, f"calls left the injected chain: {stray}"


# --- TC-AUTHOR-C14 ----------------------------------------------------------------------------


def test_tc_author_c14_knob_defaults_refusals_and_an_unoverridable_chain(
        tmp_path, make_fixture_provider, monkeypatch):
    """Defaults hold (a normal run succeeds and stays within the default attempt budget);
    `ATTEMPTS=1` is honoured; each invalid value is refused by name with its legal bound; and
    a plausible chain-override variable changes nothing."""
    author, corpus, recordings = _guards(make_fixture_provider)
    chain = chain_from_config()
    documents = sorted(corpus.glob("*.pdf"))

    def _run(out: Path):
        """One draft run; the knobs are read per invocation, so the env is set by the caller."""
        provider = CountingProvider(make_fixture_provider(recordings))
        service = make_service(author, chain, provider)
        result = service.draft(documents=documents, output_dir=out)
        return result, provider

    # Defaults: no knob set — the run succeeds and no winning model needed more than the
    # default 2 repair attempts.
    monkeypatch.delenv("HARNESS_AUTHOR_ATTEMPTS", raising=False)
    monkeypatch.delenv("HARNESS_AUTHOR_TIMEOUT_S", raising=False)
    monkeypatch.delenv("HARNESS_AUTHOR_TRANSCRIBE", raising=False)
    result, _provider = _run(tmp_path / "defaults")
    assert result.outcomes
    assert all(o.attempts <= 2 for o in result.outcomes), (
        "an outcome spent more than the default attempt budget")
    baseline_models = result.models_used
    assert baseline_models

    # ATTEMPTS=1 is honoured: the winning model's attempt count stays within it.
    monkeypatch.setenv("HARNESS_AUTHOR_ATTEMPTS", "1")
    result1, _ = _run(tmp_path / "one-attempt")
    assert all(o.attempts <= 1 for o in result1.outcomes)

    # Refusals, each naming the knob and the refused bound. The knobs are read per invocation;
    # the settings object is constructed inside the block too, so either read site refuses.
    monkeypatch.setenv("HARNESS_AUTHOR_ATTEMPTS", "0")
    with pytest.raises(Exception) as low:
        make_service(author, chain, make_fixture_provider(recordings)).draft(
            documents=documents, output_dir=tmp_path / "refused-low")
    assert "HARNESS_AUTHOR_ATTEMPTS" in str(low.value)
    assert re.search(r"\b1\b", str(low.value)), "the refusal does not state the legal floor"

    monkeypatch.setenv("HARNESS_AUTHOR_ATTEMPTS", "6")
    with pytest.raises(Exception) as high:
        make_service(author, chain, make_fixture_provider(recordings)).draft(
            documents=documents, output_dir=tmp_path / "refused-high")
    assert "HARNESS_AUTHOR_ATTEMPTS" in str(high.value)
    assert re.search(r"\b5\b", str(high.value)), "the refusal does not state the legal ceiling"

    monkeypatch.setenv("HARNESS_AUTHOR_ATTEMPTS", "2")
    monkeypatch.setenv("HARNESS_AUTHOR_TIMEOUT_S", "29")
    with pytest.raises(Exception) as timeout:
        make_service(author, chain, make_fixture_provider(recordings)).draft(
            documents=documents, output_dir=tmp_path / "refused-timeout")
    assert "HARNESS_AUTHOR_TIMEOUT_S" in str(timeout.value)
    assert re.search(r"\b30\b", str(timeout.value)), "the refusal does not state the floor"

    monkeypatch.setenv("HARNESS_AUTHOR_TIMEOUT_S", "240")
    monkeypatch.setenv("HARNESS_AUTHOR_TRANSCRIBE", "maybe")
    with pytest.raises(Exception) as transcribe:
        make_service(author, chain, make_fixture_provider(recordings)).draft(
            documents=documents, output_dir=tmp_path / "refused-transcribe")
    assert "HARNESS_AUTHOR_TRANSCRIBE" in str(transcribe.value)

    # The chain is never overridable from the environment: a plausible override variable is
    # simply ignored — the run replays the same recordings against the injected chain.
    monkeypatch.setenv("HARNESS_AUTHOR_TRANSCRIBE", "auto")
    monkeypatch.setenv("HARNESS_AUTHOR_MODEL", "openrouter/injected/chain-stealer@2026-01-01")
    monkeypatch.setenv("HARNESS_AUTHOR_CHAIN", "openrouter/injected/chain-stealer@2026-01-01")
    overridden, provider = _run(tmp_path / "override-ignored")
    assert overridden.models_used == baseline_models, (
        "an environment variable changed the reasoning chain")
    assert not {m for m in provider.models_called if "chain-stealer" in m}