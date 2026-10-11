"""`TC-AUTHOR-19` (FR-AUTHOR-05, CT-AUTHOR-14, P0) — the knob contract (TS-155, #707; test
plan §5.1 row 19; design delta §3.1, ADR-42).

Case: the environment-sensitive constants behave as `CT-AUTHOR-14` pins them:

1. **Defaults hold** — attempts default 2 (one repair per item per model: two strikes on the
   head before the first fallback call), transcribe default `auto` (a textless page rides the
   transcriber with no env set).
2. **Refusals name the knob and the legal range** — `HARNESS_AUTHOR_ATTEMPTS`=0 and =6,
   `HARNESS_AUTHOR_TIMEOUT_S`=29, `HARNESS_AUTHOR_TRANSCRIBE`="maybe" each refuse, the
   message naming the knob and the legal range, *before any provider call*.
3. **ATTEMPTS=1 skips repair** — one strike on the head, then the fallback call.
4. **The chain is never env-overridable** (ADR-42) — a `HARNESS_AUTHOR_MODEL`-style override
   in the env changes nothing: only the injected chain's builds are ever called.

The provider boundary is `PerJudgeScript` (scripted per build, `tests/support/taxonomy.py`);
the boundary itself is the only place calls can be observed, and an unscripted call fails
loudly — the override limb exploits that: the uninvited build has no script, so a single call
to it would escape as an error rather than pass silently.

Written ahead of #690 ("the draft front door"), keyed in `WRITTEN_AHEAD_BLOCKERS` as a
`command` probe on the §3.1 surface beside TC-AUTHOR-03/30's entry (no recordings needed);
see that entry's comment block for why the issue's noted `symbol` key was widened. Re-check
the case green before unmarking — never on the notice alone.

Rung 1, guards first (#689's module surface, then the committed corpus limbs).

Disclosed assumptions, to reconcile at the landing (the oracles stay the plan's):
- The design names no refusal type for an out-of-range knob, so the type is pinned to
  `(ConfigurationError, ValueError)` and the oracle is the message content: the knob's name
  and its legal range. A dedicated refusal type from #690 is a one-line widening here.
- ATTEMPTS is read as the plan does: the total attempts per item per model, so the default 2
  is "one repair", and "ATTEMPTS=1 skips repair" means one strike then the fallback. (The
  alternative reading — ATTEMPTS as retries *after* the first try, default 2 = three calls —
  would change the counted numbers, not the oracle's shape; the plan's wording pins this one.)
- `HARNESS_AUTHOR_TIMEOUT_S`'s default (240) is **not observable at rung 1**: `SamplingParams`
  carries no timeout field and the injected boundary never times out, so the default's
  existence is exercised only through its refusal limb (=29). If M-PROV grows an observable
  timeout seam, the default assertion belongs there.
- The override env's exact name is not pinned ("a `HARNESS_AUTHOR_MODEL`-style override"), so
  the limb sets a plausible name and asserts the *behaviour*: no call outside the injected
  chain, whatever env is set.
"""

from __future__ import annotations

import pytest

from aeh.conf import ConfigurationError, ModelRef
from tests.support.author_vocabulary import (
    AUTHOR_ISSUE,
    AUTHOR_MODULE,
    AUTHOR_SURFACE,
    CORPUS_ISSUE,
    af,
    chain_from_config,
    make_service,
    transcriber_from_config,
)
from tests.support.impl import require, require_path
from tests.support.taxonomy import completion, PerJudgeScript

pytestmark = [pytest.mark.writtenahead]

CASE = "TC-AUTHOR-19"

#: A second reasoning seat, distinct from the dev-ci head, so fallback within the chain is
#: observable at the boundary.
SECOND_SEAT = ModelRef(role="judge", provider="openrouter",
                       build_id="openrouter/qwen/qwen3-32b@2026-06-01", quantization=None)

UNPARSEABLE_TEXT = "this is not JSON {"

#: Scripted-queue depth, sized beyond CT-AUTHOR-13's call ceiling (steps × items × ATTEMPTS ×
#: |chain|) so the boundary cannot exhaust mid-run: the limbs assert on call *prefixes* and
#: per-build counts, so depth only keeps a fixture-exhaustion `AssertionError` from masking
#: the assertion. AF-10 has two scanned pages (the corpus's own header text), and AF-01's
#: legal worst case is a few dozen calls — 64 leaves the boundary unable to run dry.
QUEUE_DEPTH = 64

#: AF-10's committed page count — one transcriber reply per page without a text layer
#: (FR-AUTHOR-02's per-page rule; TC-AUTHOR-02 pins the same count against the corpus).
AF10_PAGE_COUNT = 2

#: The refusal matrix: (env name, illegal value, strings the refusal message must carry).
#: Each row's message must name the knob and its legal range (CT-AUTHOR-14).
REFUSAL_ROWS = (
    pytest.param("HARNESS_AUTHOR_ATTEMPTS", "0", ("HARNESS_AUTHOR_ATTEMPTS", "1", "5"),
                 id="attempts-below-range"),
    pytest.param("HARNESS_AUTHOR_ATTEMPTS", "6", ("HARNESS_AUTHOR_ATTEMPTS", "1", "5"),
                 id="attempts-above-range"),
    pytest.param("HARNESS_AUTHOR_TIMEOUT_S", "29", ("HARNESS_AUTHOR_TIMEOUT_S", "30"),
                 id="timeout-below-range"),
    pytest.param("HARNESS_AUTHOR_TRANSCRIBE", "maybe",
                 ("HARNESS_AUTHOR_TRANSCRIBE", "auto", "off"),
                 id="transcribe-unknown-value"),
)


def _guards() -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)
    # The surface guard: `require` with names returns the symbols (a tuple), not the module,
    # so the module the limbs drive comes from the zero-names call above and this call only
    # asserts the §3.1 surface exists (the two-call pattern the landed sibling files use).
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)
    require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    require_path(af("AF-10"), "the AF-10 authored fixture", issue=CORPUS_ISSUE)
    return author


def _two_seat_chain() -> list:
    chain = chain_from_config()
    return chain + [SECOND_SEAT]


def _unparseable_queue(build_id: str) -> list:
    """A generous queue of parse-strike completions for one build.

    Generous on purpose: the boundary raises when a call exceeds the script, and the limbs
    here assert the *budget boundary* (how many head calls precede the first fallback call),
    not the total call count — a queue deeper than CT-AUTHOR-13's legal ceiling (see
    `QUEUE_DEPTH`) keeps an over-budget run from failing on the fixture instead of on the
    assertion.
    """
    return [completion(UNPARSEABLE_TEXT, build_id=build_id) for _ in range(QUEUE_DEPTH)]


@pytest.mark.parametrize(("knob", "value", "needles"), REFUSAL_ROWS)
def test_tc_author_19_an_out_of_range_knob_refuses_naming_knob_and_range(
        tmp_path, monkeypatch, knob, value, needles, network_guard):
    """Each illegal knob value refuses, the message naming the knob and the legal range,
    before any provider call."""
    author = _guards()
    monkeypatch.setenv(knob, value)

    tripwire = PerJudgeScript(scripts={})
    output_dir = tmp_path / "never-written"
    with pytest.raises((ConfigurationError, ValueError)) as raised:
        make_service(author, chain_from_config(), tripwire).draft(
            documents=sorted(af("AF-01").glob("*.pdf")), output_dir=output_dir)

    message = str(raised.value)
    for needle in needles:
        assert needle in message, (
            f"{CASE}: the {knob}={value!r} refusal must name the knob and its legal range "
            f"(missing {needle!r}; CT-AUTHOR-14), got: {message}")
    assert tripwire.calls == [], (
        f"{CASE}: the {knob} refusal must fire before any provider call, got "
        f"{len(tripwire.calls)}")
    assert not output_dir.exists() or not any(output_dir.iterdir()), (
        f"{CASE}: the refused draft writes nothing")
    network_guard.assert_no_network()


def test_tc_author_19_the_default_attempts_budget_is_two_then_fallback(
        tmp_path, monkeypatch, network_guard):
    """With no env set, the head model gets its strikes (default 2 = one repair) before the
    first call to the next seat — read at the boundary, not inferred."""
    author = _guards()
    for knob in ("HARNESS_AUTHOR_ATTEMPTS", "HARNESS_AUTHOR_TRANSCRIBE",
                 "HARNESS_AUTHOR_TIMEOUT_S"):
        monkeypatch.delenv(knob, raising=False)

    chain = _two_seat_chain()
    scripts = {ref.build_id: _unparseable_queue(ref.build_id) for ref in chain}
    boundary = PerJudgeScript(scripts=scripts)
    output_dir = tmp_path / "af01-default-attempts"
    output_dir.mkdir()
    make_service(author, chain, boundary).draft(
        documents=sorted(af("AF-01").glob("*.pdf")), output_dir=output_dir)

    assert boundary.calls, f"{CASE}: the run made no provider calls"
    assert boundary.calls[0] == chain[0].build_id, (
        f"{CASE}: the first call must be the panel's seat 0, got {boundary.calls[0]!r}")
    head_strikes_before_fallback = boundary.calls[:boundary.calls.index(
        chain[1].build_id)].count(chain[0].build_id)
    assert head_strikes_before_fallback == 2, (
        f"{CASE}: the default attempts budget is 2 (one repair, CT-AUTHOR-14) — expected 2 "
        f"calls to the head before the first call to the next seat, got "
        f"{head_strikes_before_fallback}")
    network_guard.assert_no_network()


def test_tc_author_19_the_default_transcribe_mode_is_auto(
        tmp_path, monkeypatch, network_guard):
    """With no env set, a page without a text layer rides the transcriber — the auto default
    is the transcriber ride itself (FR-AUTHOR-02)."""
    author = _guards()
    for knob in ("HARNESS_AUTHOR_ATTEMPTS", "HARNESS_AUTHOR_TRANSCRIBE",
                 "HARNESS_AUTHOR_TIMEOUT_S"):
        monkeypatch.delenv(knob, raising=False)

    transcriber = transcriber_from_config()
    chain = chain_from_config()
    scripts = {
        # One reply per scanned page (AF-10 has two): a single reply would leave page 2's
        # call either escaping or swallowed as a second "failure" — the same per-page count
        # TC-AUTHOR-02 pins against the corpus.
        transcriber.build_id: [
            completion("GEO7-MAPWORK-01 scanned page text, transcribed",
                       build_id=transcriber.build_id)
            for _ in range(AF10_PAGE_COUNT)
        ],
        chain[0].build_id: _unparseable_queue(chain[0].build_id),
    }
    boundary = PerJudgeScript(scripts=scripts)
    output_dir = tmp_path / "af10-default-auto"
    output_dir.mkdir()
    make_service(author, chain, boundary).draft(
        documents=sorted((af("AF-10")).glob("*.pdf")), output_dir=output_dir)

    assert transcriber.build_id in boundary.calls, (
        f"{CASE}: with no env set the transcribe mode is auto — a page without a text layer "
        f"rides the transcriber (FR-AUTHOR-02), but no transcriber call was made")
    network_guard.assert_no_network()


def test_tc_author_19_attempts_one_skips_the_repair(
        tmp_path, monkeypatch, network_guard):
    """`HARNESS_AUTHOR_ATTEMPTS=1`: one strike on the head, then the fallback call — the
    repair budget is gone."""
    author = _guards()
    monkeypatch.setenv("HARNESS_AUTHOR_ATTEMPTS", "1")

    chain = _two_seat_chain()
    scripts = {ref.build_id: _unparseable_queue(ref.build_id) for ref in chain}
    boundary = PerJudgeScript(scripts=scripts)
    output_dir = tmp_path / "af01-attempts-1"
    output_dir.mkdir()
    make_service(author, chain, boundary).draft(
        documents=sorted(af("AF-01").glob("*.pdf")), output_dir=output_dir)

    assert boundary.calls, f"{CASE}: the run made no provider calls"
    head_strikes_before_fallback = boundary.calls[:boundary.calls.index(
        chain[1].build_id)].count(chain[0].build_id)
    assert head_strikes_before_fallback == 1, (
        f"{CASE}: ATTEMPTS=1 skips the repair (CT-AUTHOR-14) — expected exactly 1 call to "
        f"the head before the first call to the next seat, got "
        f"{head_strikes_before_fallback}")
    network_guard.assert_no_network()


def test_tc_author_19_a_model_override_env_never_overrides_the_chain(
        tmp_path, monkeypatch, network_guard):
    """A `HARNESS_AUTHOR_MODEL`-style override in the env changes nothing (ADR-42): the only
    builds ever called are the injected chain's — the uninvited build has no script, so one
    call to it would fail loudly."""
    author = _guards()
    monkeypatch.setenv("HARNESS_AUTHOR_MODEL", "openrouter/uninvited-model@2026-01-01")

    chain = _two_seat_chain()
    scripts = {ref.build_id: _unparseable_queue(ref.build_id) for ref in chain}
    boundary = PerJudgeScript(scripts=scripts)
    output_dir = tmp_path / "af01-override-ignored"
    output_dir.mkdir()
    make_service(author, chain, boundary).draft(
        documents=sorted(af("AF-01").glob("*.pdf")), output_dir=output_dir)

    chain_builds = {ref.build_id for ref in chain}
    unexpected = sorted(set(boundary.calls) - chain_builds)
    assert not unexpected, (
        f"{CASE}: the chain is never env-overridable (ADR-42) — calls reached "
        f"{unexpected}, which the injected chain does not name")
    assert boundary.calls, f"{CASE}: the run made no provider calls"
    network_guard.assert_no_network()